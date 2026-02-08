#!/usr/bin/env python3
"""Face Overlay Deduplication & Validation Tool

Scans an overlays directory containing mp_fm_faov_*.ytd files extracted
from GTA V RPF archives. When extracting with OpenIV, duplicate filenames
from different RPFs (base game, patchday1, patchday4) get Windows-style
suffixes like (1), (2), (3).

This tool:
  1. Groups files by base name (stripping the (N) suffix)
  2. Validates each file through the RSC7 → YTD → DDS pipeline
  3. Compares duplicates by texture resolution, format, and data hash
  4. Reports which file to keep per group (latest/best version)
  5. Optionally cleans up — deletes losers and renames winners

Filters to only the overlay types you care about (beard, eyebrowf, eyebrowm,
chesthair, etc.) via --types.

Usage:
    python tools/validate_overlays.py overlays/
    python tools/validate_overlays.py overlays/ --types beard eyebrowf eyebrowm
    python tools/validate_overlays.py overlays/ --clean   # actually delete/rename
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Add project root to path so we can import src modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.rsc7 import parse_rsc7                                    # noqa: E402
from src.ytd_parser import parse_texture_dictionary, select_diffuse_texture  # noqa: E402
from src.dds_builder import build_dds                               # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pattern: mp_fm_faov_{type}_{index}[_n|_s][(N)].ytd
_FAOV_RE = re.compile(
    r'^(?P<base>mp_fm_faov_(?P<type>[a-z_]+?)_(?P<index>\d{3})'
    r'(?P<channel>_[ns])?)(?:\((?P<dup>\d+)\))?\.ytd$',
    re.IGNORECASE,
)

# Overlay types relevant for the clothing tool (user-facing categories)
DEFAULT_TYPES = {"beard", "eyebrowf", "eyebrowm"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileValidation:
    """Result of validating a single .ytd file."""
    path: Path
    valid: bool = False
    error: str = ""
    file_size: int = 0
    tex_count: int = 0
    diffuse_width: int = 0
    diffuse_height: int = 0
    diffuse_format: str = ""
    diffuse_data_hash: str = ""
    diffuse_data_size: int = 0
    can_decode_dds: bool = False


@dataclass
class OverlayGroup:
    """A group of files sharing the same base name (differing only by dup suffix)."""
    base_name: str          # e.g. mp_fm_faov_beard_000
    overlay_type: str       # e.g. beard
    index: int              # e.g. 0
    channel: str            # "" for diffuse, "_n" for normal, "_s" for specular
    files: list[FileValidation] = field(default_factory=list)
    winner: FileValidation | None = None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_ytd(path: Path) -> FileValidation:
    """Run the full RSC7 → YTD → DDS pipeline on a single file."""
    result = FileValidation(path=path, file_size=path.stat().st_size)

    # Step 1: RSC7 parse
    try:
        resource = parse_rsc7(path)
    except Exception as exc:
        result.error = f"RSC7: {exc}"
        return result

    # Step 2: Parse texture dictionary
    try:
        textures = parse_texture_dictionary(resource.virtual_data, resource.physical_data)
    except Exception as exc:
        result.error = f"YTD: {exc}"
        return result

    result.tex_count = len(textures)
    if not textures:
        result.error = "YTD: 0 textures in dictionary"
        return result

    # Step 3: Select diffuse
    diffuse = select_diffuse_texture(textures)
    if diffuse is None:
        result.error = "YTD: no diffuse texture found"
        return result

    result.diffuse_width = diffuse.width
    result.diffuse_height = diffuse.height
    result.diffuse_format = diffuse.format_name
    result.diffuse_data_size = len(diffuse.raw_data)
    result.diffuse_data_hash = hashlib.md5(diffuse.raw_data).hexdigest()

    # Step 4: DDS build (validates format is supported)
    try:
        dds_bytes = build_dds(diffuse)
    except Exception as exc:
        result.error = f"DDS: {exc}"
        return result

    # Step 5: Try to decode with Pillow
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(dds_bytes))
        img.load()  # force decode
        result.can_decode_dds = True
    except Exception as exc:
        result.error = f"Pillow: {exc}"
        return result

    result.valid = True
    return result


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def discover_and_group(
    overlays_dir: Path,
    types_filter: set[str] | None = None,
) -> list[OverlayGroup]:
    """Scan directory, match faov files, group by base name."""
    groups: dict[str, OverlayGroup] = {}

    for f in sorted(overlays_dir.iterdir()):
        if not f.is_file():
            continue
        m = _FAOV_RE.match(f.name)
        if not m:
            continue

        overlay_type = m.group("type")
        if types_filter and overlay_type not in types_filter:
            continue

        base_name = m.group("base")      # includes _n/_s if present
        channel = m.group("channel") or ""
        index = int(m.group("index"))

        key = base_name.lower()
        if key not in groups:
            groups[key] = OverlayGroup(
                base_name=base_name,
                overlay_type=overlay_type,
                index=index,
                channel=channel,
            )

        # Placeholder — validation happens next
        groups[key].files.append(FileValidation(path=f))

    return sorted(groups.values(), key=lambda g: (g.overlay_type, g.index, g.channel))


# ---------------------------------------------------------------------------
# Selection logic
# ---------------------------------------------------------------------------

def pick_winner(group: OverlayGroup) -> None:
    """Among valid files in a group, pick the best one.

    Heuristic (in priority order):
      1. Valid files beat invalid ones
      2. Higher resolution beats lower
      3. Larger data size beats smaller (more complete mipchain)
      4. Larger file size beats smaller (tie-breaker)
    """
    valid = [f for f in group.files if f.valid]
    if not valid:
        group.winner = None
        return

    if len(valid) == 1:
        group.winner = valid[0]
        return

    # Check if all valid files have identical diffuse data
    hashes = {f.diffuse_data_hash for f in valid}
    if len(hashes) == 1:
        # All identical — pick the base (no parentheses) if available, else first
        base_file = next((f for f in valid if "(" not in f.path.name), None)
        group.winner = base_file or valid[0]
        return

    # Different content — pick best by resolution, then data size, then file size
    group.winner = max(
        valid,
        key=lambda f: (
            f.diffuse_width * f.diffuse_height,
            f.diffuse_data_size,
            f.file_size,
        ),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(groups: list[OverlayGroup], verbose: bool = False) -> None:
    """Print a human-readable validation report."""
    total_files = sum(len(g.files) for g in groups)
    total_groups = len(groups)
    total_valid = sum(1 for g in groups for f in g.files if f.valid)
    total_invalid = total_files - total_valid
    total_dupes = sum(max(0, len(g.files) - 1) for g in groups)

    # Only diffuse groups (no _n/_s)
    diffuse_groups = [g for g in groups if not g.channel]
    normal_groups = [g for g in groups if g.channel == "_n"]
    spec_groups = [g for g in groups if g.channel == "_s"]

    print(f"\n{'='*70}")
    print(f"  Face Overlay Validation Report")
    print(f"{'='*70}")
    print(f"  Total files scanned:     {total_files}")
    print(f"  Unique overlays (groups): {total_groups}")
    print(f"    Diffuse:  {len(diffuse_groups)}")
    print(f"    Normal:   {len(normal_groups)}")
    print(f"    Specular: {len(spec_groups)}")
    print(f"  Valid files:             {total_valid}")
    print(f"  Invalid/corrupt files:   {total_invalid}")
    print(f"  Duplicate files:         {total_dupes}")

    # Breakdown by type
    type_counts: dict[str, int] = defaultdict(int)
    for g in diffuse_groups:
        if g.winner:
            type_counts[g.overlay_type] += 1
    print(f"\n  Usable diffuse textures by type:")
    for t in sorted(type_counts):
        print(f"    {t:15s}  {type_counts[t]:3d}")

    # Invalid files
    invalid_files = [(g, f) for g in groups for f in g.files if not f.valid]
    if invalid_files:
        print(f"\n{'-'*70}")
        print(f"  INVALID FILES ({len(invalid_files)}):")
        print(f"{'-'*70}")
        for g, f in invalid_files:
            print(f"  {f.path.name}")
            print(f"    Error: {f.error}")

    # Groups where duplicates differ
    differing = [
        g for g in groups
        if len([f for f in g.files if f.valid]) > 1
        and len({f.diffuse_data_hash for f in g.files if f.valid}) > 1
    ]
    if differing:
        print(f"\n{'-'*70}")
        print(f"  GROUPS WITH DIFFERING CONTENT ({len(differing)}):")
        print(f"{'-'*70}")
        for g in differing:
            print(f"\n  {g.base_name}:")
            for f in g.files:
                status = "VALID" if f.valid else "BROKEN"
                winner = " << WINNER" if f is g.winner else ""
                res = f"{f.diffuse_width}x{f.diffuse_height}" if f.valid else "n/a"
                fmt = f.diffuse_format if f.valid else "n/a"
                h = f.diffuse_data_hash[:8] if f.valid else "n/a"
                print(f"    {f.path.name:50s} [{status}] {res:>10s} {fmt:>6s} hash={h}{winner}")

    if verbose:
        print(f"\n{'-'*70}")
        print(f"  ALL GROUPS:")
        print(f"{'-'*70}")
        for g in groups:
            n_valid = sum(1 for f in g.files if f.valid)
            n_total = len(g.files)
            winner_name = g.winner.path.name if g.winner else "NONE"
            print(f"  {g.base_name:45s}  {n_valid}/{n_total} valid  winner={winner_name}")

    # Summary of what to clean
    to_delete = []
    to_rename = []
    for g in groups:
        if not g.winner:
            to_delete.extend(f.path for f in g.files)
            continue
        for f in g.files:
            if f is not g.winner:
                to_delete.append(f.path)
        # If winner has a (N) suffix, it should be renamed to the base name
        if "(" in g.winner.path.name:
            clean_name = re.sub(r'\(\d+\)', '', g.winner.path.name)
            to_rename.append((g.winner.path, g.winner.path.parent / clean_name))

    print(f"\n{'-'*70}")
    print(f"  CLEANUP SUMMARY:")
    print(f"{'-'*70}")
    print(f"  Files to delete: {len(to_delete)}")
    print(f"  Files to rename: {len(to_rename)}")
    print(f"  Run with --clean to apply changes")
    print(f"{'='*70}\n")

    return to_delete, to_rename


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def apply_cleanup(to_delete: list[Path], to_rename: list[tuple[Path, Path]]) -> None:
    """Delete losers and rename winners to clean base names."""
    for p in to_delete:
        print(f"  DELETE  {p.name}")
        p.unlink()

    for src, dst in to_rename:
        # The base name file might already be deleted, but check just in case
        if dst.exists():
            print(f"  SKIP RENAME  {src.name} -> {dst.name}  (target exists)")
        else:
            print(f"  RENAME {src.name} -> {dst.name}")
            src.rename(dst)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and deduplicate face overlay .ytd files",
    )
    parser.add_argument("overlays_dir", type=Path, help="Path to overlays directory")
    parser.add_argument(
        "--types", nargs="+", default=list(DEFAULT_TYPES),
        help="Overlay types to process (default: beard eyebrowf eyebrowm)",
    )
    parser.add_argument("--all-types", action="store_true", help="Process all overlay types")
    parser.add_argument("--clean", action="store_true", help="Actually delete/rename files")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all groups")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    if not args.overlays_dir.is_dir():
        print(f"Error: {args.overlays_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    types_filter = None if args.all_types else set(args.types)

    # Discover and group
    print(f"Scanning {args.overlays_dir} for overlay types: "
          f"{'ALL' if args.all_types else ', '.join(sorted(types_filter))}...")

    groups = discover_and_group(args.overlays_dir, types_filter)
    if not groups:
        print("No matching overlay files found.")
        sys.exit(0)

    # Validate all files
    total = sum(len(g.files) for g in groups)
    print(f"Validating {total} files across {len(groups)} groups...")

    done = 0
    for g in groups:
        validated = []
        for fv in g.files:
            result = validate_ytd(fv.path)
            validated.append(result)
            done += 1
            if done % 20 == 0 or done == total:
                print(f"  [{done}/{total}]", end="\r")
        g.files = validated
        pick_winner(g)

    print()  # clear progress line

    # Report
    to_delete, to_rename = print_report(groups, verbose=args.verbose)

    # Cleanup
    if args.clean and (to_delete or to_rename):
        print("Applying cleanup...")
        apply_cleanup(to_delete, to_rename)
        print("Done!")
    elif args.clean:
        print("Nothing to clean.")


if __name__ == "__main__":
    main()
