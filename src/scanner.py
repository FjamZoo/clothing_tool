"""
Batch Scanner and Orchestrator

Discovers all base-texture .ytd files under the input directory, processes
them in parallel via ProcessPoolExecutor, and writes:
  - 512x512 .webp previews to {output_dir}/textures/{dlcName}/{gender}/{category}/{drawableId:03d}.webp
  - catalog.json to {output_dir}/catalog.json
  - Error logs to {output_dir}/failed/{dlcName}_{gender}_{category}_{drawableId:03d}.log
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import json

from src import rsc7, ytd_parser, dds_builder, image_processor
from src.catalog import CatalogBuilder, CatalogItem
from src.filename_parser import parse_ytd_filename, parse_tattoo_filename, count_variants, is_prop_category, prop_display_name, category_display_name
from src.meta_parser import build_dlc_map
from src.tattoo_parser import build_tattoo_meta
from src.ydd_pairer import find_ydd_for_ytd, find_fallback_ydd, find_base_body_ydd

logger = logging.getLogger(__name__)

import sys as _sys


def _emit_json(data: dict) -> None:
    """Write a single JSON line to stdout for GUI progress tracking."""
    _sys.stdout.write(json.dumps(data, separators=(",", ":")) + "\n")
    _sys.stdout.flush()


def _load_collection_casing(data_dir: str | None) -> dict[str, str]:
    """Build a lowercase→correct-case lookup from data/*.json collection names.

    Reads clothing.json and props.json, extracts every non-empty "collection"
    value, and returns a dict mapping the lowercased name to the original casing.
    This ensures our catalog uses the exact names FiveM expects.
    """
    if data_dir is None or not os.path.isdir(data_dir):
        return {}

    lookup: dict[str, str] = {}
    for fname in ("clothing.json", "props.json"):
        fpath = os.path.join(data_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", fpath, exc)
            continue
        for gender_key in data:
            for cat in data[gender_key]:
                for item in data[gender_key][cat]:
                    coll = item.get("collection", "")
                    if coll:
                        lookup[coll.lower()] = coll
    return lookup


def _auto_workers() -> int:
    """Return the number of worker processes to use by default.

    Uses all available CPU cores (os.cpu_count()), minimum 4.
    """
    return max(4, os.cpu_count() or 4)


# ---------------------------------------------------------------------------
# Worker function — MUST be top-level for pickling by ProcessPoolExecutor
# ---------------------------------------------------------------------------

def process_single_ytd(ytd_path: str, output_webp_path: str,
                       output_size: int = 0, webp_quality: int = 0) -> dict:
    """Process a single .ytd file end-to-end.

    Returns metadata dict on success, raises on failure.
    This runs in a worker process -- must be self-contained.
    """
    resource = rsc7.parse_rsc7(ytd_path)
    textures = ytd_parser.parse_texture_dictionary(
        resource.virtual_data, resource.physical_data
    )
    texture = ytd_parser.select_diffuse_texture(textures)
    if texture is None:
        raise ValueError("No diffuse texture found")
    dds_bytes = dds_builder.build_dds(texture)
    original_size = image_processor.process_texture(
        dds_bytes, output_webp_path,
        canvas_size=output_size, webp_quality=webp_quality,
    )
    return {
        "original_width": original_size[0],
        "original_height": original_size[1],
        "format": texture.format_name,
    }


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _get_resource_pack(file_path: str, input_dir: str) -> str | None:
    """Extract the first-level subdirectory name under input_dir.

    Given input_dir = "stream" and file_path = "stream/rhclothing/stream/[female]/accs/foo.ytd",
    returns "rhclothing".
    """
    try:
        rel = os.path.relpath(file_path, input_dir)
    except ValueError:
        # On Windows, relpath raises ValueError if paths are on different drives
        return None
    parts = Path(rel).parts
    if len(parts) < 2:
        return None
    return parts[0]


def _discover_files(input_dir: str) -> list[str]:
    """Walk input_dir recursively and find all base-variant .ytd files.

    Finds ``*_a_uni.ytd`` (most categories) as well as head/skin files
    with ethnicity suffixes like ``*_a_whi.ytd``, ``*_a_bla.ytd``, etc.
    Also matches prop files without suffix: ``*_diff_NNN_a.ytd``.

    Skips [replacements] directories.
    """
    import re
    _base_a_re = re.compile(r'_diff_\d+_a(?:_[a-z]+)?\.ytd$', re.IGNORECASE)
    results = []
    for dirpath, dirnames, filenames in os.walk(input_dir):
        dirnames[:] = [d for d in dirnames if d.lower() != "[replacements]"]
        for fname in filenames:
            if _base_a_re.search(fname):
                results.append(os.path.join(dirpath, fname))
    results.sort()
    return results


def _discover_base_game_files(base_game_dir: str) -> list[str]:
    """Walk base_game_dir recursively and find all base-variant .ytd files.

    Most categories use the ``_a_uni`` suffix, but some (head, uppr, lowr,
    feet) use ethnicity suffixes like ``_a_whi``, ``_a_bla``, etc.
    Props have no suffix: ``p_head_diff_000_a.ytd``.
    We match any ``_diff_NNN_a[_SUFFIX].ytd`` file.

    Base game files live in flat directories like:
        base_game/base/mp_f_freemode_01/accs_diff_000_a_uni.ytd
        base_game/base/mp_m_freemode_01/head_diff_000_a_whi.ytd
        base_game/base/mp_f_freemode_01_p/p_head_diff_000_a.ytd
    """
    import re
    _base_a_re = re.compile(r'_diff_\d+_a(?:_[a-z]+)?\.ytd$', re.IGNORECASE)
    results = []
    for dirpath, _dirnames, filenames in os.walk(base_game_dir):
        for fname in filenames:
            if _base_a_re.search(fname):
                results.append(os.path.join(dirpath, fname))
    results.sort()
    return results


def _discover_tattoo_files(input_dir: str) -> list[str]:
    """Walk input_dir recursively and find all tattoo .ytd files.

    Tattoo files match the pattern: *tattoo_NNN.ytd (e.g. rushtattoo_000.ytd).
    """
    results = []
    for dirpath, _dirnames, filenames in os.walk(input_dir):
        for fname in filenames:
            if parse_tattoo_filename(os.path.join(dirpath, fname)) is not None:
                results.append(os.path.join(dirpath, fname))
    results.sort()
    return results


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def scan_and_process(
    input_dir: str,
    output_dir: str,
    workers: int = 0,
    dry_run: bool = False,
    force: bool = False,
    verbose: bool = False,
    render_3d: bool = False,
    blender_path: str | None = None,
    batch_size: int = 50,
    base_game_dir: str | None = None,
    data_dir: str | None = None,
    json_progress: bool = False,
    scan_only: bool = False,
    dlcs: list[str] | None = None,
    categories: list[str] | None = None,
    taa_samples: int = 0,
    render_size: int = 0,
    supersampling: int = 0,
    output_size: int = 0,
    webp_quality: int = 0,
    green_hair_fix: bool = True,
):
    """Main orchestration function.

    Steps:
        1. build_dlc_map() from .meta files
        2. Walk input_dir, find all *_a_uni.ytd files
        3. Parse each filename -> YtdFileInfo
        4. Skip if output .webp already exists (unless force=True)
        5. Process files with ProcessPoolExecutor(max_workers=workers)
        6. Each worker: rsc7.parse -> ytd_parser.parse -> dds_builder.build -> image_processor.process
        7. Collect results, build catalog
        8. Write catalog.json
        9. Print summary
    """
    t_start = time.perf_counter()

    # ------------------------------------------------------------------
    # Step 0: Resolve render settings
    # ------------------------------------------------------------------
    # If supersampling is set, compute render_size from it
    if supersampling and output_size:
        render_size = supersampling * output_size
    elif supersampling and not output_size:
        render_size = supersampling * 512  # default output_size

    # ------------------------------------------------------------------
    # Step 0a: Auto-detect worker count
    # ------------------------------------------------------------------
    if workers <= 0:
        workers = _auto_workers()
    print(f"Using {workers} worker processes (CPU cores: {os.cpu_count()})")

    # ------------------------------------------------------------------
    # Step 0b: Load canonical collection name casing from data/*.json
    # ------------------------------------------------------------------
    casing_map = _load_collection_casing(data_dir)
    if casing_map:
        print(f"Loaded {len(casing_map)} canonical collection names from data/")

    # ------------------------------------------------------------------
    # Step 1: Build DLC map from .meta files
    # ------------------------------------------------------------------
    print("Building DLC map from .meta files...")
    dlc_map = build_dlc_map(input_dir)
    print(f"  Found {len(dlc_map)} resource pack(s) with DLC mappings:")
    for dir_name, dlc_name in sorted(dlc_map.items()):
        print(f"    {dir_name} -> {dlc_name}")

    # ------------------------------------------------------------------
    # Step 1b: Build tattoo metadata from shop_tattoo.meta / *_overlays.xml
    # ------------------------------------------------------------------
    print("\nBuilding tattoo metadata...")
    tattoo_meta = build_tattoo_meta(input_dir)
    if tattoo_meta:
        print(f"  Found metadata for {len(tattoo_meta)} tattoo(s)")
    else:
        print("  No tattoo metadata found")

    # ------------------------------------------------------------------
    # Step 2: Discover all base texture files
    # ------------------------------------------------------------------
    print("\nScanning for base texture files (*_a_uni.ytd)...")
    all_ytd_files = _discover_files(input_dir)
    if base_game_dir:
        base_game_files = _discover_base_game_files(base_game_dir)
        all_ytd_files.extend(base_game_files)
        all_ytd_files.sort()
        print(f"  Found {len(all_ytd_files)} candidate files "
              f"({len(all_ytd_files) - len(base_game_files)} DLC + {len(base_game_files)} base game)")
    else:
        print(f"  Found {len(all_ytd_files)} candidate files")

    # ------------------------------------------------------------------
    # Step 3: Parse filenames and build work items
    # ------------------------------------------------------------------
    work_items: list[dict] = []
    skipped_parse = 0

    for ytd_path in all_ytd_files:
        info = parse_ytd_filename(ytd_path)
        if info is None:
            skipped_parse += 1
            if verbose:
                print(f"  SKIP (no pattern match): {os.path.basename(ytd_path)}")
            continue

        # Determine the DLC name: prefer meta-derived mapping, fall back to filename
        resource_pack = _get_resource_pack(ytd_path, input_dir)
        if resource_pack and resource_pack in dlc_map:
            dlc_name = dlc_map[resource_pack]
        else:
            dlc_name = info.dlc_name

        # Normalize casing to match canonical FiveM collection names
        dlc_name = casing_map.get(dlc_name.lower(), dlc_name)

        # MP freemode heads are shared between male/female — store in
        # a shared heads/ folder and deduplicate.
        is_mp_head = (
            info.category == "head"
            and info.model in ("mp_f_freemode_01", "mp_m_freemode_01", "base_game")
        )

        # Gendered base game sub-packs (e.g. Female_freemode_beach) have
        # gender embedded in dlc_name — skip separate gender subfolder.
        is_gendered_pack = (
            info.model == "base_game" and dlc_name != "base"
        )

        # Use display names for props in output paths / catalog keys
        display_cat = prop_display_name(info.category)

        if is_mp_head:
            # Temporary path/key for dedup — will be renumbered below
            texture_rel = os.path.join(
                "heads", dlc_name, f"{info.drawable_id:03d}.webp"
            )
            catalog_key = f"{dlc_name}_head_{info.drawable_id:03d}"
        elif is_gendered_pack:
            texture_rel = os.path.join(
                dlc_name, display_cat, f"{info.drawable_id:03d}.webp"
            )
            catalog_key = f"{dlc_name}_{display_cat}_{info.drawable_id:03d}"
        else:
            texture_rel = os.path.join(
                dlc_name, info.gender, display_cat, f"{info.drawable_id:03d}.webp"
            )
            catalog_key = f"{dlc_name}_{info.gender}_{display_cat}_{info.drawable_id:03d}"

        output_webp = os.path.join(output_dir, "textures", texture_rel)

        work_items.append({
            "ytd_path": ytd_path,
            "output_webp": output_webp,
            "texture_rel": texture_rel.replace("\\", "/"),
            "catalog_key": catalog_key,
            "dlc_name": dlc_name,
            "gender": "unisex" if is_mp_head else info.gender,
            "category": info.category,
            "display_category": display_cat,
            "drawable_id": info.drawable_id,
            "source_file": os.path.basename(ytd_path),
            "is_head": is_mp_head,
            "is_prop": is_prop_category(info.category),
        })

    # ------------------------------------------------------------------
    # Filter by --dlcs if specified
    # ------------------------------------------------------------------
    if dlcs:
        dlcs_lower = {d.lower() for d in dlcs}
        work_items = [item for item in work_items
                      if item["dlc_name"].lower() in dlcs_lower]
        print(f"  Filtered to {len(work_items)} items matching --dlcs: {', '.join(dlcs)}")

    # ------------------------------------------------------------------
    # Filter by --categories if specified
    # ------------------------------------------------------------------
    if categories:
        cats_lower = {c.lower() for c in categories}
        work_items = [item for item in work_items
                      if item["display_category"].lower() in cats_lower]
        print(f"  Filtered to {len(work_items)} items matching --categories: {', '.join(categories)}")

    # Deduplicate shared heads (identical between male/female)
    seen_keys: set[str] = set()
    deduped_items: list[dict] = []
    skipped_dup_heads = 0
    for item in work_items:
        if item["catalog_key"] in seen_keys:
            skipped_dup_heads += 1
            continue
        seen_keys.add(item["catalog_key"])
        deduped_items.append(item)
    work_items = deduped_items

    # Renumber heads into a single flat folder: base_game keeps 0-45,
    # other DLC heads continue sequentially from 46+.
    head_items = [item for item in work_items if item.get("is_head")]
    non_head_items = [item for item in work_items if not item.get("is_head")]

    # Sort: base_game first by drawable_id, then other DLCs alphabetically
    head_items.sort(key=lambda x: (
        0 if x["dlc_name"] == "base_game" else 1,
        x["dlc_name"],
        x["drawable_id"],
    ))

    # Base game heads keep their original IDs; others start after
    base_game_max = max(
        (item["drawable_id"] for item in head_items if item["dlc_name"] == "base_game"),
        default=-1,
    )
    next_head_id = base_game_max + 1

    for item in head_items:
        if item["dlc_name"] == "base_game":
            head_id = item["drawable_id"]
        else:
            head_id = next_head_id
            next_head_id += 1

        item["drawable_id"] = head_id
        texture_rel = os.path.join("heads", f"{head_id:03d}.webp")
        item["texture_rel"] = texture_rel.replace("\\", "/")
        item["output_webp"] = os.path.join(output_dir, "textures", texture_rel)
        item["catalog_key"] = f"head_{head_id:03d}"

    work_items = non_head_items + head_items

    if skipped_parse:
        print(f"  Skipped {skipped_parse} files (filename did not match pattern)")
    if skipped_dup_heads:
        print(f"  Skipped {skipped_dup_heads} duplicate head textures (shared between male/female)")
    if head_items:
        print(f"  {len(head_items)} heads renumbered into heads/ folder (IDs 0-{next_head_id - 1})")
    prop_count = sum(1 for item in work_items if item.get("is_prop"))
    clothing_count = len(work_items) - prop_count
    print(f"  {len(work_items)} files to process ({clothing_count} clothing, {prop_count} props)")

    # ------------------------------------------------------------------
    # Step 3b: Discover and build tattoo work items
    # ------------------------------------------------------------------
    print("\nScanning for tattoo files...")
    all_tattoo_files = _discover_tattoo_files(input_dir)
    print(f"  Found {len(all_tattoo_files)} tattoo files")

    tattoo_work_items: list[dict] = []
    for tpath in all_tattoo_files:
        tinfo = parse_tattoo_filename(tpath)
        if tinfo is None:
            continue

        # Look up metadata from shop_tattoo.meta
        meta = tattoo_meta.get(f"{tinfo.prefix}_{tinfo.index:03d}")
        zone = meta.zone if meta else "unknown"
        label = meta.label if meta else ""

        # Determine DLC name from the resource pack directory
        resource_pack = _get_resource_pack(tpath, input_dir)
        dlc_name = tinfo.prefix

        # Build output path: {output_dir}/textures/tattoos/{prefix}/{index:03d}.webp
        texture_rel = os.path.join("tattoos", tinfo.prefix, f"{tinfo.index:03d}.webp")
        output_webp = os.path.join(output_dir, "textures", texture_rel)

        catalog_key = f"{tinfo.prefix}_tattoo_{tinfo.index:03d}"

        tattoo_work_items.append({
            "ytd_path": tpath,
            "output_webp": output_webp,
            "texture_rel": texture_rel.replace("\\", "/"),
            "catalog_key": catalog_key,
            "dlc_name": dlc_name,
            "zone": zone,
            "label": label,
            "index": tinfo.index,
            "source_file": os.path.basename(tpath),
        })

    # Filter tattoos by --dlcs if specified
    if dlcs:
        dlcs_lower = {d.lower() for d in dlcs}
        tattoo_work_items = [item for item in tattoo_work_items
                             if item["dlc_name"].lower() in dlcs_lower]

    # Filter tattoos by --categories if specified
    if categories:
        cats_lower = {c.lower() for c in categories}
        if "tattoo" not in cats_lower:
            tattoo_work_items = []

    print(f"  {len(tattoo_work_items)} tattoo files to process")

    # ------------------------------------------------------------------
    # Scan-only mode: output JSON summary and exit
    # ------------------------------------------------------------------
    if scan_only:
        # Build DLC item counts for scan-only output
        stream_dlcs: dict[str, dict] = {}
        base_game_dlcs: dict[str, dict] = {}
        cat_counts: dict[str, int] = {}

        for item in work_items + tattoo_work_items:
            dn = item["dlc_name"]
            # Determine if base_game by checking the source path
            is_bg = (base_game_dir and
                     os.path.normcase(item["ytd_path"]).startswith(
                         os.path.normcase(base_game_dir)))
            target = base_game_dlcs if is_bg else stream_dlcs
            if dn not in target:
                target[dn] = {"name": dn, "items": 0}
            target[dn]["items"] += 1

            # Count items per display category
            cat_key = item.get("display_category", item.get("category", "unknown"))
            # Tattoo items don't have display_category — use "tattoo"
            if "index" in item:
                cat_key = "tattoo"
            cat_counts[cat_key] = cat_counts.get(cat_key, 0) + 1

        result = {
            "stream": sorted(stream_dlcs.values(), key=lambda x: x["name"]),
            "base_game": sorted(base_game_dlcs.values(), key=lambda x: x["name"]),
            "categories": sorted(
                [
                    {"key": k, "label": category_display_name(k), "items": v}
                    for k, v in cat_counts.items()
                ],
                key=lambda x: x["label"],
            ),
        }
        print(json.dumps(result, indent=2))
        return

    # ------------------------------------------------------------------
    # Step 4: Filter out already-processed files (unless --force)
    # ------------------------------------------------------------------
    skipped_existing = 0
    if not force:
        filtered = []
        for item in work_items:
            if os.path.exists(item["output_webp"]):
                skipped_existing += 1
                if verbose:
                    print(f"  SKIP (exists): {item['catalog_key']}")
            else:
                filtered.append(item)
        work_items = filtered

        filtered_tattoos = []
        for item in tattoo_work_items:
            if os.path.exists(item["output_webp"]):
                skipped_existing += 1
                if verbose:
                    print(f"  SKIP (exists): {item['catalog_key']}")
            else:
                filtered_tattoos.append(item)
        tattoo_work_items = filtered_tattoos

        if skipped_existing:
            print(f"  Skipped {skipped_existing} files (output already exists)")

    to_process = len(work_items) + len(tattoo_work_items)

    # ------------------------------------------------------------------
    # Emit JSON scan event (DLC breakdown for GUI)
    # ------------------------------------------------------------------
    if json_progress:
        # Build DLC item counts
        dlc_counts: dict[str, int] = {}
        for item in work_items:
            dn = item["dlc_name"]
            dlc_counts[dn] = dlc_counts.get(dn, 0) + 1
        for item in tattoo_work_items:
            dn = item["dlc_name"]
            dlc_counts[dn] = dlc_counts.get(dn, 0) + 1
        _emit_json({
            "type": "scan",
            "dlcs": [{"name": n, "count": c} for n, c in sorted(dlc_counts.items())],
        })

    # ------------------------------------------------------------------
    # Dry-run: print summary and exit
    # ------------------------------------------------------------------
    if dry_run:
        print(f"\n=== DRY RUN SUMMARY ===")
        print(f"  Base textures discovered: {len(all_ytd_files)}")
        print(f"  Tattoo files discovered:  {len(all_tattoo_files)}")
        print(f"  Skipped (no pattern):     {skipped_parse}")
        print(f"  Skipped (already exist):  {skipped_existing}")
        prop_ct = sum(1 for i in work_items if i.get("is_prop"))
        cloth_ct = len(work_items) - prop_ct
        print(f"  Would process:            {to_process} ({cloth_ct} clothing, {prop_ct} props, {len(tattoo_work_items)} tattoos)")

        # Show breakdown by DLC + gender
        breakdown: dict[str, int] = {}
        for item in work_items:
            key = f"{item['dlc_name']} / {item['gender']}"
            breakdown[key] = breakdown.get(key, 0) + 1
        if tattoo_work_items:
            breakdown["tattoos"] = len(tattoo_work_items)
        if breakdown:
            print(f"\n  Breakdown by DLC / gender:")
            for key in sorted(breakdown.keys()):
                print(f"    {key}: {breakdown[key]}")

        return

    if to_process == 0:
        print("\nNothing to process. All files are up to date.")
        if json_progress:
            _emit_json({"type": "done", "processed": 0, "failed": 0,
                        "skipped": skipped_parse + skipped_existing,
                        "elapsed": time.perf_counter() - t_start})
        return

    # Emit start event for JSON progress
    if json_progress:
        _emit_json({"type": "start", "total": to_process})

    # Track progress counter for JSON output
    _progress_counter = 0

    # ------------------------------------------------------------------
    # Step 5: Pair with .ydd files if 3D rendering is enabled
    # ------------------------------------------------------------------
    render_3d_items: list[dict] = []
    flat_items: list[dict] = []

    if render_3d:
        # Validate Blender availability
        from src.blender_renderer import find_blender
        if blender_path is None:
            blender_path = find_blender()
        if blender_path is None:
            print("\nERROR: Blender not found. Install Blender or use --blender-path.")
            print("Falling back to flat texture rendering for all items.")
            render_3d = False

    # Categories where a flat overlay mesh should fall back to base body mesh
    _BODY_OVERLAY_CATEGORIES = {"uppr", "lowr"}

    if render_3d:
        paired = 0
        paired_fallback = 0
        for item in work_items:
            # For base game task items, DLCs ship body-skin shells instead
            # of real armor meshes.  Always prefer the base ped fallback
            # which has proper standalone armor geometry.
            # (Stream DLC task items have proper meshes — only base_game affected.)
            is_base_game_file = (base_game_dir and
                os.path.normcase(item["ytd_path"]).startswith(
                    os.path.normcase(base_game_dir)))
            if item["category"] == "task" and is_base_game_file:
                fb = find_fallback_ydd(
                    "task", item["gender"], base_game_dir,
                    drawable_id=item.get("drawable_id"),
                )
                if fb is not None:
                    item["ydd_path"] = fb
                    render_3d_items.append(item)
                    paired_fallback += 1
                    continue

            ydd_path = find_ydd_for_ytd(item["ytd_path"])
            if ydd_path is not None:
                item["ydd_path"] = ydd_path

                # For body overlay categories, provide the base body mesh
                # so Blender can fall back to it if the mesh is a flat shell
                if item["category"] in _BODY_OVERLAY_CATEGORIES:
                    base_mesh = find_base_body_ydd(ydd_path, item["category"])
                    if base_mesh:
                        item["fallback_ydd_path"] = base_mesh
                # For hand (bags), provide a fallback from base game
                # in case the paired mesh is a flat shell
                elif base_game_dir and item["category"] == "hand":
                    fb = find_fallback_ydd(
                        item["category"], item["gender"], base_game_dir,
                        drawable_id=item.get("drawable_id"),
                    )
                    if fb and os.path.normcase(fb) != os.path.normcase(ydd_path):
                        item["fallback_ydd_path"] = fb

                render_3d_items.append(item)
                paired += 1
            elif base_game_dir:
                # Try base body mesh as fallback for stub-only items
                fallback = find_fallback_ydd(
                    item["category"], item["gender"], base_game_dir,
                    drawable_id=item.get("drawable_id"),
                )
                if fallback is not None:
                    item["ydd_path"] = fallback
                    render_3d_items.append(item)
                    paired_fallback += 1
                else:
                    flat_items.append(item)
            else:
                flat_items.append(item)

        print(f"\n3D rendering: {paired} items paired with .ydd files")
        if paired_fallback:
            print(f"  {paired_fallback} items using base body mesh fallback")
        if flat_items:
            print(f"  {len(flat_items)} items without .ydd — falling back to flat texture")
    else:
        flat_items = work_items

    # ------------------------------------------------------------------
    # Step 6: Process files
    # ------------------------------------------------------------------
    catalog = CatalogBuilder()
    processed = 0
    failed = 0
    failed_dir = os.path.join(output_dir, "failed")

    # --- 3D rendering via Blender ---
    if render_3d_items:
        from src.blender_renderer import render_batch, DEFAULT_PARALLEL_BLENDERS

        parallel = min(DEFAULT_PARALLEL_BLENDERS, max(2, workers // 2))
        print(f"\nRendering {len(render_3d_items)} items in 3D via Blender "
              f"(batch_size={batch_size}, {parallel} parallel instances)...")

        render_results = render_batch(
            render_3d_items, blender_path,
            batch_size=batch_size, parallel=parallel,
            render_size=render_size,
            taa_samples=taa_samples,
            output_size=output_size,
            webp_quality=webp_quality,
            green_hair_fix=green_hair_fix,
        )

        for rr in render_results:
            # Find the original item
            item = next(
                (i for i in render_3d_items if i["catalog_key"] == rr.catalog_key),
                None,
            )
            if item is None:
                continue

            if rr.success:
                # WebP conversion already done by blender_renderer
                variants = count_variants(item["ytd_path"])
                catalog.add_item(CatalogItem(
                    dlc_name=item["dlc_name"],
                    gender=item["gender"],
                    category=item["display_category"],
                    drawable_id=item["drawable_id"],
                    texture_path=item["texture_rel"],
                    variants=variants,
                    source_file=item["source_file"],
                    width=512,
                    height=512,
                    original_width=512,
                    original_height=512,
                    format_name="3D_RENDER",
                    render_type="3d",
                    item_type="prop" if item.get("is_prop") else "clothing",
                ))
                processed += 1
                _progress_counter += 1
                if json_progress:
                    _emit_json({"type": "progress", "current": _progress_counter,
                                "total": to_process,
                                "file": item["texture_rel"], "status": "ok"})
                if verbose:
                    print(f"  [3D] OK: {item['source_file']}")
            else:
                # 3D render failed — fall back to flat texture
                if verbose:
                    print(f"  [3D] FAIL: {item['source_file']} -- {rr.error} "
                          f"(falling back to flat)")
                flat_items.append(item)

    # --- Pre-create all output directories (avoid per-file makedirs overhead) ---
    all_work = flat_items + tattoo_work_items
    output_dirs_seen: set[str] = set()
    for item in all_work:
        d = os.path.dirname(item["output_webp"])
        if d and d not in output_dirs_seen:
            os.makedirs(d, exist_ok=True)
            output_dirs_seen.add(d)
    os.makedirs(failed_dir, exist_ok=True)

    # --- Process all flat textures + tattoos in a single worker pool ---
    all_flat_total = len(all_work)
    if all_flat_total > 0:
        flat_prop_ct = sum(1 for i in flat_items if i.get("is_prop"))
        flat_cloth_ct = len(flat_items) - flat_prop_ct
        print(f"\nProcessing {all_flat_total} files ({flat_cloth_ct} clothing, "
              f"{flat_prop_ct} props, {len(tattoo_work_items)} tattoos) with {workers} workers...")

        t_proc_start = time.perf_counter()

        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_item = {}
            for item in all_work:
                future = executor.submit(
                    process_single_ytd,
                    item["ytd_path"],
                    item["output_webp"],
                    output_size,
                    webp_quality,
                )
                future_to_item[future] = item

            for future in as_completed(future_to_item):
                item = future_to_item[future]
                current = processed + failed + 1

                try:
                    result = future.result()

                    is_tattoo = "index" in item

                    if is_tattoo:
                        catalog.add_item(CatalogItem(
                            dlc_name=item["dlc_name"],
                            gender="unisex",
                            category="tattoo",
                            drawable_id=item["index"],
                            texture_path=item["texture_rel"],
                            variants=1,
                            source_file=item["source_file"],
                            width=512,
                            height=512,
                            original_width=result["original_width"],
                            original_height=result["original_height"],
                            format_name=result["format"],
                            item_type="tattoo",
                            zone=item["zone"],
                        ))
                    else:
                        variants = count_variants(item["ytd_path"])
                        catalog.add_item(CatalogItem(
                            dlc_name=item["dlc_name"],
                            gender=item["gender"],
                            category=item.get("display_category", item["category"]),
                            drawable_id=item["drawable_id"],
                            texture_path=item["texture_rel"],
                            variants=variants,
                            source_file=item["source_file"],
                            width=512,
                            height=512,
                            original_width=result["original_width"],
                            original_height=result["original_height"],
                            format_name=result["format"],
                            item_type="prop" if item.get("is_prop") else "clothing",
                        ))
                    processed += 1
                    _progress_counter += 1

                    if json_progress:
                        _emit_json({"type": "progress",
                                    "current": _progress_counter,
                                    "total": to_process,
                                    "file": item["texture_rel"],
                                    "status": "ok"})

                    if verbose:
                        elapsed_so_far = time.perf_counter() - t_proc_start
                        rate = processed / elapsed_so_far if elapsed_so_far > 0 else 0
                        extra = (f" zone={item['zone']}" if is_tattoo else "")
                        print(
                            f"  [{current}/{to_process}] OK: {item['source_file']} "
                            f"({result['original_width']}x{result['original_height']} "
                            f"{result['format']}{extra}) "
                            f"[{rate:.1f} img/s]"
                        )

                except Exception as exc:
                    failed += 1
                    _progress_counter += 1
                    error_msg = f"{type(exc).__name__}: {exc}"
                    catalog.add_failure(item["ytd_path"], error_msg)

                    if json_progress:
                        _emit_json({"type": "progress",
                                    "current": _progress_counter,
                                    "total": to_process,
                                    "file": item.get("texture_rel", item["source_file"]),
                                    "status": "failed",
                                    "error": error_msg})

                    if verbose:
                        print(
                            f"  [{current}/{to_process}] FAIL: {item['source_file']} "
                            f"-- {error_msg}"
                        )

                    try:
                        is_tattoo = "index" in item
                        if is_tattoo:
                            log_name = f"tattoo_{item['dlc_name']}_{item['index']:03d}.log"
                        else:
                            log_name = (
                                f"{item['dlc_name']}_{item['gender']}_{item['category']}"
                                f"_{item['drawable_id']:03d}.log"
                            )
                        log_path = os.path.join(failed_dir, log_name)
                        with open(log_path, "w", encoding="utf-8") as f:
                            f.write(f"Source: {item['ytd_path']}\n")
                            f.write(f"Output: {item['output_webp']}\n")
                            f.write(f"Error:  {error_msg}\n")
                    except OSError as log_err:
                        logger.warning("Failed to write error log: %s", log_err)

        # Print throughput stats
        t_proc_elapsed = time.perf_counter() - t_proc_start
        if t_proc_elapsed > 0 and processed > 0:
            rate = processed / t_proc_elapsed
            print(f"\n  Throughput: {rate:.1f} images/sec "
                  f"({processed} images in {t_proc_elapsed:.1f}s)")

    # ------------------------------------------------------------------
    # Step 7-8: Write catalog
    # ------------------------------------------------------------------
    catalog_path = os.path.join(output_dir, "catalog.json")
    catalog.write(catalog_path)
    print(f"\nCatalog written to {catalog_path}")

    # ------------------------------------------------------------------
    # Step 9: Summary
    # ------------------------------------------------------------------
    elapsed = time.perf_counter() - t_start
    rate = processed / elapsed if elapsed > 0 and processed > 0 else 0
    print(f"\n=== PROCESSING COMPLETE ===")
    print(f"  Total processed:  {processed}")
    print(f"  Total failed:     {failed}")
    print(f"  Total skipped:    {skipped_parse + skipped_existing}")
    print(f"  Catalog entries:  {len(catalog.items)}")
    print(f"  Elapsed time:     {elapsed:.1f}s")
    print(f"  Avg throughput:   {rate:.1f} images/sec")

    if json_progress:
        _emit_json({"type": "done", "processed": processed, "failed": failed,
                    "skipped": skipped_parse + skipped_existing,
                    "elapsed": round(elapsed, 1)})
