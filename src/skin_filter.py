"""Body skin texture filter.

GTA V's ``uppr`` (upper body) and ``lowr`` (lower body) categories are
overlay layers that include bare body skin textures alongside actual
clothing items.  Body skin textures are duplicated across many drawable
IDs — the same image appears 3-20+ times — while real clothing textures
are unique per drawable.

Detection strategy:
  1. Group work items by (dlc_name, gender, category).
  2. For ``uppr`` and ``lowr`` categories, parse each .ytd to extract the
     raw texture data hash.
  3. If a hash appears 3+ times AND the texture is >= 95% opaque,
     all items sharing that hash are body skin duplicates → skip.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from io import BytesIO

from PIL import Image

from src import rsc7, ytd_parser, dds_builder

logger = logging.getLogger(__name__)

# Categories that can contain body skin overlay textures
BODY_OVERLAY_CATEGORIES = frozenset({"uppr", "lowr"})

# Minimum number of textures sharing the same hash to be considered body skin
_DUPLICATE_THRESHOLD = 3

# Minimum fraction of opaque pixels (alpha > 200) for body skin detection
_OPACITY_THRESHOLD = 0.95


def _texture_hash(ytd_path: str) -> str | None:
    """Parse a .ytd and return the MD5 hex of its raw diffuse texture data.

    This is fast — only decompresses the RSC7 container and hashes the
    raw bytes, no image decoding needed.
    """
    try:
        resource = rsc7.parse_rsc7(ytd_path)
        textures = ytd_parser.parse_texture_dictionary(
            resource.virtual_data, resource.physical_data
        )
        tex = ytd_parser.select_diffuse_texture(textures)
        if tex is None or not tex.raw_data:
            return None
        return hashlib.md5(tex.raw_data).hexdigest()
    except Exception as exc:
        logger.debug("skin_filter: hash failed for %s: %s", ytd_path, exc)
        return None


def _texture_opacity(ytd_path: str) -> float:
    """Parse a .ytd and return the fraction of opaque pixels (alpha > 200).

    Only called for a small number of representative samples.
    """
    try:
        resource = rsc7.parse_rsc7(ytd_path)
        textures = ytd_parser.parse_texture_dictionary(
            resource.virtual_data, resource.physical_data
        )
        tex = ytd_parser.select_diffuse_texture(textures)
        if tex is None or not tex.raw_data:
            return 0.0

        dds_bytes = dds_builder.build_dds(tex)
        img = Image.open(BytesIO(dds_bytes)).convert("RGBA")
        total_pixels = img.width * img.height
        if total_pixels == 0:
            return 0.0

        alpha = img.getchannel("A")
        opaque_count = sum(1 for p in alpha.tobytes() if p > 200)
        return opaque_count / total_pixels
    except Exception:
        return 0.0


def _texture_hash_and_opacity(ytd_path: str) -> tuple[str, float] | None:
    """Parse a .ytd file and return (md5_hex, opacity_fraction).

    Returns None if the file cannot be parsed or has no diffuse texture.
    Used by tests and as a convenience wrapper.
    """
    md5 = _texture_hash(ytd_path)
    if md5 is None:
        return None
    opacity = _texture_opacity(ytd_path)
    return (md5, opacity)


def filter_body_skin_items(
    work_items: list[dict],
) -> tuple[list[dict], int]:
    """Filter out body skin textures from work items.

    For categories in :data:`BODY_OVERLAY_CATEGORIES`, detects and removes
    items that are body skin maps (duplicated opaque textures).

    Uses a two-phase approach for speed:
      Phase 1: Hash all textures in parallel (fast — no image decoding).
      Phase 2: For hashes that appear 3+ times, check opacity of ONE
               sample (only a few image decodes needed).

    Args:
        work_items: List of work item dicts, each containing at minimum
            ``ytd_path``, ``dlc_name``, ``gender``, ``category``.

    Returns:
        ``(filtered_items, skipped_count)`` — the items to keep and how
        many were removed.
    """
    # Separate items that need checking from those that don't
    to_check: list[dict] = []
    passthrough: list[dict] = []

    for item in work_items:
        if item.get("category", "") in BODY_OVERLAY_CATEGORIES:
            to_check.append(item)
        else:
            passthrough.append(item)

    if not to_check:
        return work_items, 0

    # Group by (dlc_name, gender, category)
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for item in to_check:
        key = (item["dlc_name"], item["gender"], item["category"])
        groups[key].append(item)

    # Phase 1: Hash all textures in parallel (fast, no image decode)
    workers = max(4, os.cpu_count() or 4)
    item_hashes: dict[int, str | None] = {}  # id(item) -> hash

    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_to_item = {
            executor.submit(_texture_hash, item["ytd_path"]): item
            for item in to_check
        }
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                item_hashes[id(item)] = future.result()
            except Exception:
                item_hashes[id(item)] = None

    # For each group, count hashes and detect duplicates
    kept: list[dict] = []
    skipped = 0

    for group_key, group_items in groups.items():
        # Build hash counts for this group
        hash_counts: dict[str, int] = defaultdict(int)
        hash_sample: dict[str, str] = {}  # hash -> sample ytd_path
        item_info: list[tuple[dict, str | None]] = []

        for item in group_items:
            md5 = item_hashes.get(id(item))
            item_info.append((item, md5))
            if md5 is not None:
                hash_counts[md5] += 1
                if md5 not in hash_sample:
                    hash_sample[md5] = item["ytd_path"]

        # Phase 2: Check opacity only for hashes that appear >= threshold
        candidate_hashes = {
            h for h, count in hash_counts.items()
            if count >= _DUPLICATE_THRESHOLD
        }
        hash_opaque: dict[str, bool] = {}
        for h in candidate_hashes:
            opacity = _texture_opacity(hash_sample[h])
            hash_opaque[h] = opacity >= _OPACITY_THRESHOLD

        # Filter
        for item, md5 in item_info:
            if md5 is None:
                kept.append(item)
                continue

            is_body_skin = (
                md5 in candidate_hashes
                and hash_opaque.get(md5, False)
            )

            if is_body_skin:
                skipped += 1
                logger.debug(
                    "Skipping body skin: %s (hash=%s, count=%d)",
                    item.get("source_file", "?"),
                    md5[:8],
                    hash_counts[md5],
                )
            else:
                kept.append(item)

    if skipped:
        logger.info(
            "Filtered %d body skin texture(s) from %s categories",
            skipped,
            "/".join(sorted(BODY_OVERLAY_CATEGORIES)),
        )

    return passthrough + kept, skipped
