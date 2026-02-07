"""Parse structured .ytd filenames into metadata components.

Handles three filename patterns:
  1. Standard MP freemode: mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd
  2. Custom peds:          strafe^accs_diff_001_a_uni.ytd
  3. Tattoo overlays:      rushtattoo_000.ytd

Also handles prop files which use p_ prefixed categories:
  - mp_f_freemode_01_p_rhclothing^p_head_diff_000_a.ytd
  - p_head_diff_000_a_uni.ytd (base game)

Gender is derived from directory path first ([female]/[male]), then from
model prefix (mp_f_/mp_m_), defaulting to "unknown" for custom peds.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

# Standard freemode model pattern.
# The dlcname part uses .+? (non-greedy) to capture everything between
# "mp_[fm]_freemode_01_" and the "^" separator. This handles DLC names
# that contain underscores and embedded sub-DLC names like
# "mp_f_gunrunning_01" in "mp_f_freemode_01_mp_f_gunrunning_01^accs_diff_000_a_uni.ytd".
YTD_PATTERN = re.compile(
    r'^(?P<model>mp_[fm]_freemode_01)_'
    r'(?P<dlcname>.+?)\^'
    r'(?P<category>[a-z_]+)_'
    r'diff_'
    r'(?P<drawable>\d+)_'
    r'(?P<variant>[a-z])'
    r'(?:_(?P<suffix>[a-z]+))?'
    r'\.ytd$'
)

# Custom ped pattern (no mp_f/mp_m prefix).
# Model name is everything before the "^".
CUSTOM_PED_PATTERN = re.compile(
    r'^(?P<model>[a-zA-Z0-9_]+)\^'
    r'(?P<category>[a-z_]+)_'
    r'diff_'
    r'(?P<drawable>\d+)_'
    r'(?P<variant>[a-z])'
    r'(?:_(?P<suffix>[a-z]+))?'
    r'\.ytd$'
)

# Base game pattern (no DLC/model prefix, no ^ separator).
# e.g. accs_diff_000_a_uni.ytd, jbib_diff_001_b_uni.ytd
# Also matches prop categories: p_head_diff_000_a.ytd (no suffix)
BASE_GAME_PATTERN = re.compile(
    r'^(?P<category>[a-z_]+)_'
    r'diff_'
    r'(?P<drawable>\d+)_'
    r'(?P<variant>[a-z])'
    r'(?:_(?P<suffix>[a-z]+))?'
    r'\.ytd$'
)

# Tattoo overlay pattern: prefix_NNN.ytd (e.g. rushtattoo_000.ytd)
TATTOO_PATTERN = re.compile(
    r'^(?P<prefix>[a-zA-Z][a-zA-Z0-9]*tattoo)_(?P<index>\d{3})\.ytd$'
)

# Prop categories — these are GTA V "prop" components (hats, glasses, etc.)
# as opposed to "component" clothing (accs, jbib, lowr, etc.).
PROP_CATEGORIES = frozenset({"p_head", "p_eyes", "p_ears", "p_lwrist", "p_rwrist"})

# Display names for prop categories (used in output paths and catalog).
PROP_DISPLAY_NAMES: dict[str, str] = {
    "p_head": "hat",
    "p_eyes": "glass",
    "p_ears": "ear",
    "p_lwrist": "watch",
    "p_rwrist": "bracelet",
}


def is_prop_category(category: str) -> bool:
    """Return True if the category is a prop (p_head, p_eyes, etc.)."""
    return category in PROP_CATEGORIES


def prop_display_name(category: str) -> str:
    """Return the display name for a prop category, or the category unchanged."""
    return PROP_DISPLAY_NAMES.get(category, category)


@dataclass
class YtdFileInfo:
    """Parsed metadata from a .ytd texture filename."""
    file_path: str
    model: str          # "mp_f_freemode_01" or custom ped name
    dlc_name: str       # "rhclothing", or model name for custom peds
    gender: str         # "female", "male", or "unknown"
    category: str       # "accs", "jbib", "lowr", etc.
    drawable_id: int    # 0, 1, 2, ...
    variant: str        # "a", "b", "c", ...
    is_base: bool       # True if variant == "a"


def _derive_gender(file_path: str, model: str) -> str:
    """Derive gender from directory path or model prefix.

    Priority:
      1. Path contains [female] -> "female"
      2. Path contains [male]   -> "male"
      3. Model starts with mp_f_ -> "female"
      4. Model starts with mp_m_ -> "male"
      5. Otherwise -> "unknown"
    """
    # Normalize path separators for consistent matching
    normalized = file_path.replace("\\", "/").lower()

    if "[female]" in normalized or "/female/" in normalized:
        return "female"
    if "[male]" in normalized or "/male/" in normalized:
        return "male"

    # Check for base game ped directory names in path
    if "mp_f_freemode_01" in normalized:
        return "female"
    if "mp_m_freemode_01" in normalized:
        return "male"

    # Fall back to model prefix
    if model.startswith("mp_f_"):
        return "female"
    if model.startswith("mp_m_"):
        return "male"

    return "unknown"


# Regex to detect base game ped directories with optional sub-pack suffix.
# Matches e.g. "mp_f_freemode_01" or "mp_f_freemode_01_female_freemode_beach".
_BASE_GAME_DIR_RE = re.compile(
    r'mp_(?P<gchar>[fm])_freemode_01(?:_(?P<suffix>.+))?$'
)

# Legacy hardcoded overrides — canonical casing is now loaded from
# data/*.json at runtime (see scanner._load_collection_casing).
_BASE_GAME_NAME_OVERRIDES: dict[str, str] = {}


def _derive_base_game_info(file_path: str) -> tuple[str, str]:
    """Derive (dlc_name, gender) for base game files from directory path.

    Examines parent directory names to detect sub-packs like mpbeach:
      mp_f_freemode_01                        -> ("base", "female")
      mp_f_freemode_01_female_freemode_beach  -> ("Female_freemode_beach", "female")
      mp_m_freemode_01_male_freemode_beach    -> ("Male_freemode_beach", "male")

    Prop directories have a "_p" or "_p_<subpack>" suffix:
      mp_f_freemode_01_p                      -> ("base", "female")
      mp_f_freemode_01_p_mp_f_airraces_01     -> ("mp_f_airraces_01", "female")
    """
    normalized = file_path.replace("\\", "/")
    parts = normalized.split("/")

    # Walk parent directories (skip filename) looking for a ped directory
    for part in reversed(parts[:-1]):
        m = _BASE_GAME_DIR_RE.match(part)
        if m:
            gender = "female" if m.group("gchar") == "f" else "male"
            suffix = m.group("suffix")
            if suffix:
                # Strip prop directory prefix: "p" -> base, "p_xxx" -> "xxx"
                if suffix == "p":
                    return "base", gender
                if suffix.startswith("p_"):
                    suffix = suffix[2:]

                # Check hardcoded overrides first
                if suffix in _BASE_GAME_NAME_OVERRIDES:
                    dlc_name = _BASE_GAME_NAME_OVERRIDES[suffix]
                # mp_ prefixed names stay lowercase; others capitalize first letter
                elif suffix.startswith("mp_"):
                    dlc_name = suffix
                else:
                    dlc_name = suffix[0].upper() + suffix[1:]
                return dlc_name, gender
            else:
                return "base", gender

    # Fallback to existing gender derivation
    return "base", _derive_gender(file_path, "base_game")


def parse_ytd_filename(file_path: str) -> YtdFileInfo | None:
    """Extract metadata from a .ytd filename.

    Args:
        file_path: Full or relative path to a .ytd file.

    Returns:
        YtdFileInfo with parsed components, or None if the filename
        does not match any recognized pattern.
    """
    filename = os.path.basename(file_path)

    # Try standard freemode pattern first
    match = YTD_PATTERN.match(filename)
    if match:
        model = match.group("model")
        dlc_name = match.group("dlcname")
        category = match.group("category")
        variant = match.group("variant")
        # Prop files have DLC name prefixed with "p_":
        #   mp_f_freemode_01_p_rhclothing^p_head_diff_000_a.ytd
        # Strip the "p_" prefix to normalize to the real DLC name.
        if is_prop_category(category) and dlc_name.startswith("p_"):
            dlc_name = dlc_name[2:]
        return YtdFileInfo(
            file_path=file_path,
            model=model,
            dlc_name=dlc_name,
            gender=_derive_gender(file_path, model),
            category=category,
            drawable_id=int(match.group("drawable")),
            variant=variant,
            is_base=(variant == "a"),
        )

    # Try custom ped pattern
    match = CUSTOM_PED_PATTERN.match(filename)
    if match:
        model = match.group("model")
        variant = match.group("variant")
        # For custom peds, dlc_name is set to the model name
        return YtdFileInfo(
            file_path=file_path,
            model=model,
            dlc_name=model,
            gender=_derive_gender(file_path, model),
            category=match.group("category"),
            drawable_id=int(match.group("drawable")),
            variant=variant,
            is_base=(variant == "a"),
        )

    # Try base game pattern (no DLC prefix, no ^)
    match = BASE_GAME_PATTERN.match(filename)
    if match:
        variant = match.group("variant")
        dlc_name, gender = _derive_base_game_info(file_path)
        return YtdFileInfo(
            file_path=file_path,
            model="base_game",
            dlc_name=dlc_name,
            gender=gender,
            category=match.group("category"),
            drawable_id=int(match.group("drawable")),
            variant=variant,
            is_base=(variant == "a"),
        )

    return None


def count_variants(file_path: str) -> int:
    """Count sibling variant files for a given base (_a_) file.

    Given a path to an _a_ variant .ytd file, counts how many total
    variant files exist in the same directory with the same prefix
    (including _a_ itself).

    Args:
        file_path: Path to a .ytd file (should be an _a_ variant).

    Returns:
        Total number of variant files (e.g., 22 if a-v exist).
        Returns 0 if the file doesn't match the pattern or directory
        doesn't exist.
    """
    info = parse_ytd_filename(file_path)
    if info is None:
        return 0

    directory = os.path.dirname(file_path)
    if not os.path.isdir(directory):
        return 0

    filename = os.path.basename(file_path)

    # Build the prefix: everything before the variant letter.
    # e.g. "mp_f_freemode_01_rhclothing^accs_diff_000_" from
    #      "mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd"
    # or   "p_head_diff_000_" from "p_head_diff_000_a.ytd" (props, no suffix)
    # Find the drawable ID in the filename to locate the prefix boundary.
    drawable_str = f"_diff_{info.drawable_id:03d}_"
    idx = filename.lower().find(drawable_str.lower())
    if idx < 0:
        return 0
    prefix = filename[: idx + len(drawable_str)]

    # Count files in the directory that match this prefix pattern
    count = 0
    try:
        for entry in os.scandir(directory):
            if not entry.is_file():
                continue
            name = entry.name
            if name.startswith(prefix) and name.endswith(".ytd") and "diff" in name:
                # Verify it's actually a variant of the same drawable
                sibling_info = parse_ytd_filename(os.path.join(directory, name))
                if (
                    sibling_info is not None
                    and sibling_info.model == info.model
                    and sibling_info.dlc_name == info.dlc_name
                    and sibling_info.category == info.category
                    and sibling_info.drawable_id == info.drawable_id
                ):
                    count += 1
    except OSError:
        return 0

    return count


# ---------------------------------------------------------------------------
# Tattoo filename parsing
# ---------------------------------------------------------------------------

@dataclass
class TattooFileInfo:
    """Parsed metadata from a tattoo .ytd filename."""
    file_path: str
    prefix: str         # "rushtattoo"
    index: int          # 0, 1, 2, ...


def parse_tattoo_filename(file_path: str) -> TattooFileInfo | None:
    """Extract metadata from a tattoo .ytd filename.

    Args:
        file_path: Full or relative path to a .ytd file.

    Returns:
        TattooFileInfo with parsed components, or None if the filename
        does not match the tattoo pattern.
    """
    filename = os.path.basename(file_path)
    match = TATTOO_PATTERN.match(filename)
    if match is None:
        return None
    return TattooFileInfo(
        file_path=file_path,
        prefix=match.group("prefix"),
        index=int(match.group("index")),
    )
