"""
Meta File Parser

Parses ShopPedApparel .meta XML files found under the stream/ directory to
build a mapping from resource-pack directory name to DLC name.

Each clothing resource pack (e.g. "government_clothing") contains one or two
.meta files named like ``mp_f_freemode_01_<dlcName>.meta`` (female) and/or
``mp_m_freemode_01_<dlcName>.meta`` (male).  These are standard GTA V
ShopPedApparel XML files with <pedName>, <dlcName>, and <fullDlcName> elements.

Files that do NOT follow the ``mp_f_freemode_01_*`` / ``mp_m_freemode_01_*``
naming convention (e.g. ``peds.meta``, ``shop_tattoo.meta``,
``pedalternativevariations_*.meta``) are silently skipped.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

# Only consider .meta files whose stem starts with one of these prefixes.
_APPAREL_META_PREFIX = re.compile(r"^mp_[fm]_freemode_01_")


def parse_meta_file(meta_path: str | Path) -> dict:
    """Parse a single ShopPedApparel .meta file.

    Args:
        meta_path: Path to the .meta XML file.

    Returns:
        A dict with the following keys::

            {
                'pedName':     'mp_f_freemode_01',
                'dlcName':     'rhclothing',
                'fullDlcName': 'mp_f_freemode_01_rhclothing',
                'gender':      'female',   # '_f_' -> 'female', '_m_' -> 'male'
            }

    Raises:
        FileNotFoundError: If *meta_path* does not exist.
        ValueError: If required XML elements are missing or the root tag is
            not ``<ShopPedApparel>``.
        ET.ParseError: If the file is not valid XML.
    """
    path = Path(meta_path)
    tree = ET.parse(path)
    root = tree.getroot()

    if root.tag != "ShopPedApparel":
        raise ValueError(
            f"Expected <ShopPedApparel> root element, got <{root.tag}> in {path.name}"
        )

    ped_name_el = root.find("pedName")
    dlc_name_el = root.find("dlcName")
    full_dlc_name_el = root.find("fullDlcName")

    if ped_name_el is None or not (ped_name_el.text or "").strip():
        raise ValueError(f"Missing or empty <pedName> in {path.name}")
    if dlc_name_el is None or not (dlc_name_el.text or "").strip():
        raise ValueError(f"Missing or empty <dlcName> in {path.name}")
    if full_dlc_name_el is None or not (full_dlc_name_el.text or "").strip():
        raise ValueError(f"Missing or empty <fullDlcName> in {path.name}")

    ped_name = ped_name_el.text.strip()
    dlc_name = dlc_name_el.text.strip()
    full_dlc_name = full_dlc_name_el.text.strip()

    # Derive gender from pedName
    if "_f_" in ped_name:
        gender = "female"
    elif "_m_" in ped_name:
        gender = "male"
    else:
        gender = "unknown"
        logger.warning("Cannot determine gender from pedName '%s' in %s", ped_name, path.name)

    return {
        "pedName": ped_name,
        "dlcName": dlc_name,
        "fullDlcName": full_dlc_name,
        "gender": gender,
    }


def build_dlc_map(stream_root: str | Path) -> dict[str, str]:
    """Scan all ShopPedApparel .meta files under *stream_root*.

    Only files matching ``mp_f_freemode_01_*.meta`` or
    ``mp_m_freemode_01_*.meta`` directly inside a first-level subdirectory
    are considered.  Other .meta files (``peds.meta``, ``shop_tattoo.meta``,
    ``pedalternativevariations_*.meta``) are silently skipped.

    Args:
        stream_root: Path to the top-level ``stream/`` directory.

    Returns:
        A dict mapping resource-pack directory name to dlcName, e.g.::

            {
                'government_clothing': 'rhgovernment',
                'rhaddonfaces':        'rhaddonfaces',
                'rhclothing':          'rhclothing',
                'rhclothing2':         'rhclothing2',
            }
    """
    root = Path(stream_root)
    if not root.is_dir():
        raise FileNotFoundError(f"Stream root directory does not exist: {root}")

    dlc_map: dict[str, str] = {}

    # Walk first-level subdirectories only
    for resource_dir in sorted(root.iterdir()):
        if not resource_dir.is_dir():
            continue

        # Find qualifying .meta files anywhere under this resource dir
        for meta_file in resource_dir.rglob("*.meta"):
            if not _APPAREL_META_PREFIX.match(meta_file.stem):
                logger.debug("Skipping non-apparel meta file: %s", meta_file)
                continue

            try:
                info = parse_meta_file(meta_file)
            except (ValueError, ET.ParseError) as exc:
                logger.warning("Failed to parse %s: %s", meta_file, exc)
                continue

            dir_name = resource_dir.name
            dlc_name = info["dlcName"]

            # Warn if a directory already has a different dlcName mapped
            if dir_name in dlc_map and dlc_map[dir_name] != dlc_name:
                logger.warning(
                    "Conflicting dlcName for '%s': existing='%s', new='%s' (from %s)",
                    dir_name, dlc_map[dir_name], dlc_name, meta_file.name,
                )

            dlc_map[dir_name] = dlc_name
            logger.debug(
                "Mapped '%s' -> '%s' (from %s, gender=%s)",
                dir_name, dlc_name, meta_file.name, info["gender"],
            )

    logger.info("Built DLC map with %d entries from %s", len(dlc_map), root)
    return dlc_map


# ---------------------------------------------------------------------------
# Quick CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

    stream_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\lauri\Desktop\scripts\clothing_tool\stream"
    result = build_dlc_map(stream_path)

    print("\n=== DLC Map ===")
    for dir_name, dlc_name in sorted(result.items()):
        print(f"  {dir_name:30s} -> {dlc_name}")
    print(f"\nTotal: {len(result)} entries")
