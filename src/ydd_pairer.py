"""YDD-YTD File Pairing

Given a .ytd texture path, find the corresponding .ydd model file.
The pairing is based on shared prefix and drawable ID:

  YTD: mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd
  YDD: mp_f_freemode_01_rhclothing^accs_000_u.ydd

Both share the prefix ``mp_f_freemode_01_rhclothing^accs`` and the
drawable ID ``000``.  The YDD file has a suffix like ``_u`` or ``_r``.

Search order:
  1. Same directory as the .ytd file
  2. Parent directory
  3. Sibling directories of the .ytd (handles the [replacements]/textures/ layout
     where .ytd files are in a centralized textures/ folder while .ydd files are
     in category subdirectories like F_ACCS/, F_HAIR/, etc.)
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# Regex to extract prefix + drawable from a .ytd filename.
# Captures everything up to the category, then the drawable ID.
# Example: "mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd"
#   -> prefix = "mp_f_freemode_01_rhclothing^accs"
#   -> drawable = "000"
# Props may lack suffix: "mp_f_freemode_01_p_rhclothing^p_head_diff_000_a.ytd"
_YTD_PREFIX_RE = re.compile(
    r'^(?P<prefix>.+?\^[a-z_]+)_diff_(?P<drawable>\d+)_[a-z](?:_[a-z]+)?\.ytd$',
    re.IGNORECASE,
)

# Base game pattern: "accs_diff_000_a_uni.ytd" -> prefix="accs", drawable="000"
# Also matches prop categories: "p_head_diff_000_a.ytd" -> prefix="p_head"
# Props may lack suffix after variant letter.
_BASE_GAME_PREFIX_RE = re.compile(
    r'^(?P<prefix>[a-z_]+)_diff_(?P<drawable>\d+)_[a-z](?:_[a-z]+)?\.ytd$',
    re.IGNORECASE,
)

# Preferred YDD suffixes, in order of preference.
_YDD_SUFFIX_PREFERENCE = ['_u', '_r']

# Minimum YDD file size in bytes.  Some base game DLCs ship stub .ydd
# files (~500 bytes) that contain no real mesh data.  These produce
# degenerate renders (thin strips) in Blender, so we skip them.
_MIN_YDD_SIZE = 1024

# Higher minimum for standalone-object categories (task=armor, hand=bags).
# Base game ships ~1.5KB "empty container" YDDs for these that pass the
# normal 1024B threshold but contain no visible geometry.  Real meshes
# in these categories are 100KB+.
_MIN_YDD_SIZE_STANDALONE = 10240

# Categories where the mesh is a standalone 3D object (not a body overlay).
# These use _MIN_YDD_SIZE_STANDALONE for fallback filtering.
# Props (p_head, p_eyes, etc.) are also standalone objects.
_STANDALONE_CATEGORIES = {"hand", "task", "p_head", "p_eyes", "p_ears", "p_lwrist", "p_rwrist"}

# Categories that have viable base body meshes (>10KB) for fallback rendering.
# Other categories (berd, decl, hair, teef) only have stubs.
# Props are standalone objects and can also use fallback meshes.
_FALLBACK_CATEGORIES = {"accs", "feet", "hand", "jbib", "lowr", "task", "uppr",
                        "p_head", "p_eyes", "p_ears", "p_lwrist", "p_rwrist"}


def _scan_dir_for_ydd(
    directory: str, ydd_prefix: str, min_size: int = _MIN_YDD_SIZE,
) -> list[str]:
    """Scan a single directory for .ydd files matching the prefix.

    Matches both suffixed files (``{prefix}_u.ydd``) and unsuffixed prop
    files (``{prefix}.ydd`` where prefix already includes the trailing ``_``
    before the suffix, e.g. ``p_head_000_`` matches ``p_head_000.ydd``).

    Skips stub files smaller than *min_size* bytes (default _MIN_YDD_SIZE).
    """
    candidates: list[str] = []
    # Also match files with no suffix: "p_head_000.ydd" when prefix is "p_head_000_"
    exact_nosuffix = ydd_prefix.rstrip("_") + ".ydd"
    try:
        for entry in os.scandir(directory):
            if not entry.is_file():
                continue
            name_lower = entry.name.lower()
            if not name_lower.endswith(".ydd"):
                continue
            if name_lower.startswith(ydd_prefix) or name_lower == exact_nosuffix:
                if entry.stat().st_size < min_size:
                    logger.debug("Skipping stub YDD: %s (%d bytes, min=%d)",
                                 entry.name, entry.stat().st_size, min_size)
                    continue
                candidates.append(entry.path)
    except OSError:
        pass
    return candidates


def _rank_and_pick(candidates: list[str]) -> str:
    """Pick the best .ydd from candidates, preferring _u then _r suffix."""
    def _suffix_rank(path: str) -> int:
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        for rank, suffix in enumerate(_YDD_SUFFIX_PREFERENCE):
            if stem.endswith(suffix):
                return rank
        return len(_YDD_SUFFIX_PREFERENCE)

    candidates.sort(key=_suffix_rank)
    return candidates[0]


def find_ydd_for_ytd(ytd_path: str) -> str | None:
    """Find the .ydd model file corresponding to a .ytd texture file.

    Search strategy:
      1. Same directory as the .ytd file
      2. Parent directory of the .ytd file
      3. All sibling directories (handles [replacements]/textures/ layout
         where .ydd files are in F_ACCS/, F_HAIR/, etc.)

    Prefers ``_u`` suffix, then ``_r``, then any other.

    Args:
        ytd_path: Path to a .ytd file.

    Returns:
        Absolute path to the matching .ydd file, or None if not found.
    """
    filename = os.path.basename(ytd_path)
    match = _YTD_PREFIX_RE.match(filename)
    if match is None:
        match = _BASE_GAME_PREFIX_RE.match(filename)
    if match is None:
        logger.debug("Cannot extract prefix from YTD filename: %s", filename)
        return None

    prefix = match.group("prefix")       # e.g. "mp_f_freemode_01_rhclothing^accs"
    drawable = match.group("drawable")    # e.g. "000"

    directory = os.path.dirname(ytd_path)
    if not directory:
        directory = "."

    # Build the pattern we're looking for: {prefix}_{drawable}_*.ydd
    ydd_prefix = f"{prefix}_{drawable}_".lower()

    # --- Strategy 1: Same directory ---
    candidates = _scan_dir_for_ydd(directory, ydd_prefix)
    if candidates:
        chosen = _rank_and_pick(candidates)
        logger.debug("Paired %s -> %s (same dir)", filename, os.path.basename(chosen))
        return chosen

    # --- Strategy 2: Parent directory ---
    parent = os.path.dirname(directory)
    if parent and parent != directory:
        candidates = _scan_dir_for_ydd(parent, ydd_prefix)
        if candidates:
            chosen = _rank_and_pick(candidates)
            logger.debug("Paired %s -> %s (parent dir)", filename, os.path.basename(chosen))
            return chosen

        # --- Strategy 3: Sibling directories ---
        # Handles [replacements]/FEMALE/textures/ where .ydd files are in
        # sibling dirs like F_ACCS/, F_HAIR/, F_JBIB/, SKIN/, etc.
        try:
            for entry in os.scandir(parent):
                if not entry.is_dir():
                    continue
                # Skip the directory we already checked
                if os.path.normcase(entry.path) == os.path.normcase(directory):
                    continue
                sibling_candidates = _scan_dir_for_ydd(entry.path, ydd_prefix)
                candidates.extend(sibling_candidates)
        except OSError:
            pass

        if candidates:
            chosen = _rank_and_pick(candidates)
            logger.debug("Paired %s -> %s (sibling dir)", filename, os.path.basename(chosen))
            return chosen

    logger.debug("No .ydd found for prefix=%s drawable=%s", prefix, drawable)
    return None


def find_base_body_ydd(ydd_path: str, category: str) -> str | None:
    """Find the base body mesh (drawable 000) in the same directory as ydd_path.

    For body overlay categories (uppr, lowr), flat overlay shells should be
    replaced with the base body mesh for proper 3D rendering.

    Args:
        ydd_path: Path to the item's own .ydd file.
        category: Component category (e.g. "uppr", "lowr").

    Returns:
        Path to the base body .ydd (drawable 000), or None if not found
        or if ydd_path already IS the base mesh.
    """
    directory = os.path.dirname(ydd_path)
    if not directory:
        directory = "."

    prefix = f"{category.lower()}_000_"
    candidates = _scan_dir_for_ydd(directory, prefix)
    if not candidates:
        return None

    chosen = _rank_and_pick(candidates)
    # Don't return the same file we already have
    if os.path.normcase(chosen) == os.path.normcase(ydd_path):
        return None

    return chosen


def find_fallback_ydd(
    category: str, gender: str, base_game_dir: str,
    drawable_id: int | None = None,
) -> str | None:
    """Find a base body mesh as fallback for items with stub YDDs.

    When a DLC item has only a stub .ydd (no real geometry), the game
    applies the texture onto the default base body mesh for that
    component slot.  This function locates that base mesh.

    Strategy (same-ID first, then largest):
      1. Try the same drawable ID from the base ped directory.
      2. If that's also a stub, pick the largest real YDD in the category.

    Args:
        category: Component category (e.g. "jbib", "uppr", "lowr", "task").
        gender: "female" or "male".
        base_game_dir: Path to the base_game/ directory.
        drawable_id: Optional drawable ID to try first (same-ID match).

    Returns:
        Path to the base body .ydd file, or None if not available.
    """
    if category.lower() not in _FALLBACK_CATEGORIES:
        return None

    # Props live in a separate "_p" directory in base game
    is_prop = category.lower().startswith("p_")

    if gender == "female":
        ped_dir = os.path.join(base_game_dir, "base",
                               "mp_f_freemode_01_p" if is_prop else "mp_f_freemode_01")
    elif gender == "male":
        ped_dir = os.path.join(base_game_dir, "base",
                               "mp_m_freemode_01_p" if is_prop else "mp_m_freemode_01")
    else:
        return None

    if not os.path.isdir(ped_dir):
        return None

    cat = category.lower()
    # Use higher threshold for standalone-object categories (task, hand)
    min_sz = (_MIN_YDD_SIZE_STANDALONE if cat in _STANDALONE_CATEGORIES
              else _MIN_YDD_SIZE)

    # Strategy 1: Try same drawable ID first
    if drawable_id is not None:
        prefix = f"{cat}_{drawable_id:03d}_"
        candidates = _scan_dir_for_ydd(ped_dir, prefix, min_size=min_sz)
        if candidates:
            chosen = _rank_and_pick(candidates)
            logger.debug("Fallback same-ID mesh for %s/%s: %s",
                          gender, category, os.path.basename(chosen))
            return chosen

    # Strategy 2: Pick the largest real YDD in this category
    all_prefix = f"{cat}_"
    all_candidates = _scan_dir_for_ydd(ped_dir, all_prefix, min_size=min_sz)
    if all_candidates:
        # Sort by file size descending, pick the largest
        all_candidates.sort(key=lambda p: os.path.getsize(p), reverse=True)
        chosen = all_candidates[0]
        logger.debug("Fallback largest mesh for %s/%s: %s (%d bytes)",
                      gender, category, os.path.basename(chosen),
                      os.path.getsize(chosen))
        return chosen

    return None
