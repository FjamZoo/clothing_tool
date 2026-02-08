"""
Face Overlay Parser

Discovers and parses face overlay .ytd files (eyebrows, beards, makeup, etc.)
from a dedicated overlays directory.

Overlay files follow the pattern:
    mp_fm_faov_{type}_{index:03d}.ytd

Companion normal (_n) and specular (_s) maps are skipped.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Filename pattern
# ---------------------------------------------------------------------------

# Matches diffuse overlay files only (no _n or _s suffix before .ytd)
_FAOV_RE = re.compile(
    r'^mp_fm_faov_(?P<type>[a-z_]+?)_(?P<index>\d{3})\.ytd$',
    re.IGNORECASE,
)

# Types that end with 'f' are female-specific
_FEMALE_TYPES = frozenset({"eyebrowf", "lips_g", "makeup"})

# Types that end with 'm' are male-specific
_MALE_TYPES = frozenset({"eyebrowm", "lipsm", "makeupm", "beard"})

# Portrait framing categories
PORTRAIT_UPPER = frozenset({"eyebrowf", "eyebrowm"})  # Forehead area
PORTRAIT_LOWER = frozenset({"beard"})                   # Jaw/chin area
# Everything else gets general face framing


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class OverlayInfo:
    """Parsed face overlay file metadata."""
    file_path: Path       # Absolute path to .ytd
    overlay_type: str     # e.g. "beard", "eyebrowf", "makeup", "acne"
    index: int            # e.g. 0-25 for beards, 0-16 for eyebrows
    gender: str           # "male" or "female"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _classify_gender(overlay_type: str) -> str:
    """Determine the gender for an overlay type.

    Female types use the female head mesh; everything else uses male.
    """
    if overlay_type in _FEMALE_TYPES:
        return "female"
    return "male"


def discover_overlays(overlays_dir: Path) -> list[OverlayInfo]:
    """Scan overlays directory for diffuse face overlay .ytd files.

    Skips _n (normal) and _s (specular) companion maps.
    Returns sorted list of OverlayInfo (by type, then index).
    """
    if not overlays_dir.is_dir():
        logger.warning("Overlays directory does not exist: %s", overlays_dir)
        return []

    results: list[OverlayInfo] = []

    for f in sorted(overlays_dir.iterdir()):
        if not f.is_file():
            continue

        # Skip normal and specular maps
        stem = f.stem.lower()
        if stem.endswith('_n') or stem.endswith('_s'):
            continue

        m = _FAOV_RE.match(f.name)
        if not m:
            continue

        overlay_type = m.group('type').lower()
        index = int(m.group('index'))
        gender = _classify_gender(overlay_type)

        results.append(OverlayInfo(
            file_path=f,
            overlay_type=overlay_type,
            index=index,
            gender=gender,
        ))

    logger.info(
        "Discovered %d face overlay files in %s",
        len(results), overlays_dir,
    )
    return results


def _scan_dir_for_faov(directory: Path) -> list[OverlayInfo]:
    """Recursively scan a directory for mp_fm_faov_* overlay .ytd files."""
    results: list[OverlayInfo] = []
    if not directory.is_dir():
        return results

    for f in sorted(directory.rglob("mp_fm_faov_*.ytd")):
        if not f.is_file():
            continue
        stem = f.stem.lower()
        if stem.endswith('_n') or stem.endswith('_s'):
            continue
        m = _FAOV_RE.match(f.name)
        if not m:
            continue
        overlay_type = m.group('type').lower()
        index = int(m.group('index'))
        gender = _classify_gender(overlay_type)
        results.append(OverlayInfo(
            file_path=f,
            overlay_type=overlay_type,
            index=index,
            gender=gender,
        ))
    return results


def discover_replacement_overlays(input_dir: Path) -> list[OverlayInfo]:
    """Scan stream [replacements] directories for face overlay .ytd files.

    These are custom replacements that override base game overlays.
    Walks all ``{input_dir}/*/stream/[replacements]/`` trees.
    """
    results: list[OverlayInfo] = []
    if not input_dir.is_dir():
        return results

    for pack_dir in sorted(input_dir.iterdir()):
        rep_dir = pack_dir / "stream" / "[replacements]"
        found = _scan_dir_for_faov(rep_dir)
        if found:
            logger.info(
                "Found %d replacement overlay(s) in %s",
                len(found), rep_dir,
            )
            results.extend(found)

    return results


def merge_overlays(
    base: list[OverlayInfo],
    replacements: list[OverlayInfo],
) -> list[OverlayInfo]:
    """Merge base overlays with replacements.

    Replacements override base entries with the same (type, index) key.
    New replacement entries (not in base) are added.
    Returns a sorted list.
    """
    by_key: dict[tuple[str, int], OverlayInfo] = {}

    for ov in base:
        by_key[(ov.overlay_type, ov.index)] = ov

    replaced = 0
    added = 0
    for ov in replacements:
        key = (ov.overlay_type, ov.index)
        if key in by_key:
            replaced += 1
        else:
            added += 1
        by_key[key] = ov

    if replaced or added:
        logger.info(
            "Overlay merge: %d replaced, %d new from replacements",
            replaced, added,
        )

    return sorted(by_key.values(), key=lambda o: (o.overlay_type, o.index))
