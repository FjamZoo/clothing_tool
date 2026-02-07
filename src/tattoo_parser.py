"""
Tattoo Metadata Parser

Parses shop_tattoo.meta and *_overlays.xml files to extract tattoo metadata
(zone, label, gender info) for each tattoo index.

shop_tattoo.meta structure:
    <TattooShopItemArray>
      <TattooShopItems>
        <Item>
          <textLabel>RUSHTATTOO_TAT_000</textLabel>
          <preset>rushtattoo_000_M</preset>
          <zone>PDZ_TORSO</zone>
          <eFacing>TATTOO_BACK</eFacing>
          ...
        </Item>
      </TattooShopItems>
    </TattooShopItemArray>

*_overlays.xml structure:
    <PedDecorationCollection>
      <presets>
        <Item>
          <nameHash>rushtattoo_000_M</nameHash>
          <txdHash>rushtattoo_000</txdHash>
          <zone>ZONE_TORSO</zone>
          <gender>GENDER_MALE</gender>
          ...
        </Item>
      </presets>
    </PedDecorationCollection>
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Zone name normalisation: strip PDZ_/ZONE_ prefix and lower-case
_ZONE_PREFIX = re.compile(r"^(?:PDZ_|ZONE_)", re.IGNORECASE)


def _normalize_zone(raw: str) -> str:
    """Normalize zone strings like 'PDZ_TORSO' or 'ZONE_LEFT_ARM' to 'torso'/'left_arm'."""
    return _ZONE_PREFIX.sub("", raw).lower()


@dataclass
class TattooMeta:
    """Metadata for a single tattoo index."""
    txd_name: str           # "rushtattoo_000" — matches .ytd filename without extension
    index: int              # 0
    label: str              # "RUSHTATTOO_TAT_000"
    zone: str               # "torso", "head", "left_arm", etc.
    facing: str             # "back", "front", "left", "right", "chest"
    genders: list[str] = field(default_factory=list)  # ["male", "female"]


def _lenient_parse_xml(path: Path) -> ET.Element:
    """Parse XML with lenient error handling for common GTA V meta issues.

    Some .meta files have stray closing tags or other minor XML errors.
    This attempts a strict parse first, then falls back to cleaning the
    XML text and retrying.
    """
    try:
        return ET.parse(path).getroot()
    except ET.ParseError:
        # Fallback: read as text, remove duplicate/stray closing tags, retry
        text = path.read_text(encoding="utf-8")
        # Remove lines that are just stray </Item> not preceded by item content
        # Simple heuristic: remove consecutive </Item> on adjacent lines
        import re as _re
        text = _re.sub(r"(</Item>\s*\n)\s*</Item>", r"\1", text)
        return ET.fromstring(text)


def parse_shop_tattoo_meta(meta_path: str | Path) -> dict[str, dict]:
    """Parse a shop_tattoo.meta file.

    Returns a dict keyed by preset base name (e.g. "rushtattoo_000") with
    values containing zone, facing, and label info.
    """
    path = Path(meta_path)
    root = _lenient_parse_xml(path)

    if root.tag != "TattooShopItemArray":
        raise ValueError(
            f"Expected <TattooShopItemArray> root, got <{root.tag}> in {path.name}"
        )

    results: dict[str, dict] = {}

    # Items may be directly under root or nested under <TattooShopItems>
    items = root.findall(".//Item")

    for item in items:
        preset_el = item.find("preset")
        if preset_el is None or not (preset_el.text or "").strip():
            continue

        preset = preset_el.text.strip()

        # Strip gender suffix (_M or _F) to get base name
        base_name = re.sub(r"_[MF]$", "", preset)

        # Only store first occurrence per base name (avoids gender duplicates)
        if base_name in results:
            continue

        label_el = item.find("textLabel")
        zone_el = item.find("zone")
        facing_el = item.find("eFacing")

        label = (label_el.text or "").strip() if label_el is not None else ""
        zone_raw = (zone_el.text or "").strip() if zone_el is not None else ""
        facing_raw = (facing_el.text or "").strip() if facing_el is not None else ""

        zone = _normalize_zone(zone_raw) if zone_raw else "unknown"
        facing = facing_raw.replace("TATTOO_", "").lower() if facing_raw else "unknown"

        results[base_name] = {
            "label": label,
            "zone": zone,
            "facing": facing,
        }

    return results


def parse_overlays_xml(xml_path: str | Path) -> dict[str, list[str]]:
    """Parse a *_overlays.xml file for gender information.

    Returns a dict keyed by txdHash (e.g. "rushtattoo_000") with a list
    of genders (e.g. ["male", "female"]).
    """
    path = Path(xml_path)
    tree = ET.parse(path)
    root = tree.getroot()

    genders: dict[str, list[str]] = {}

    # Find presets — could be nested under <presets><Item> or directly
    presets = root.find("presets")
    if presets is None:
        logger.warning("No <presets> element in %s", path.name)
        return genders

    for item in presets.findall("Item"):
        txd_el = item.find("txdHash")
        gender_el = item.find("gender")

        if txd_el is None or not (txd_el.text or "").strip():
            continue

        txd_name = txd_el.text.strip()
        gender_raw = (gender_el.text or "").strip() if gender_el is not None else ""

        if "FEMALE" in gender_raw.upper():
            g = "female"
        elif "MALE" in gender_raw.upper():
            g = "male"
        else:
            g = "unisex"

        if txd_name not in genders:
            genders[txd_name] = []
        if g not in genders[txd_name]:
            genders[txd_name].append(g)

    return genders


def build_tattoo_meta(stream_root: str | Path) -> dict[str, TattooMeta]:
    """Scan stream_root for tattoo metadata files and build a lookup dict.

    Searches all resource pack directories for shop_tattoo.meta and
    *_overlays.xml files.

    Returns:
        Dict keyed by txd_name (e.g. "rushtattoo_000") -> TattooMeta.
    """
    root = Path(stream_root)
    if not root.is_dir():
        return {}

    shop_meta: dict[str, dict] = {}
    gender_info: dict[str, list[str]] = {}

    for resource_dir in sorted(root.iterdir()):
        if not resource_dir.is_dir():
            continue

        # Find shop_tattoo.meta files
        for meta_file in resource_dir.rglob("shop_tattoo.meta"):
            try:
                parsed = parse_shop_tattoo_meta(meta_file)
                shop_meta.update(parsed)
                logger.debug("Parsed %d tattoo entries from %s", len(parsed), meta_file)
            except (ValueError, ET.ParseError) as exc:
                logger.warning("Failed to parse %s: %s", meta_file, exc)

        # Find *_overlays.xml files
        for xml_file in resource_dir.rglob("*_overlays.xml"):
            try:
                parsed_genders = parse_overlays_xml(xml_file)
                for txd, glist in parsed_genders.items():
                    if txd not in gender_info:
                        gender_info[txd] = []
                    for g in glist:
                        if g not in gender_info[txd]:
                            gender_info[txd].append(g)
                logger.debug("Parsed gender info for %d tattoos from %s",
                             len(parsed_genders), xml_file)
            except (ValueError, ET.ParseError) as exc:
                logger.warning("Failed to parse %s: %s", xml_file, exc)

    # Merge into TattooMeta objects
    result: dict[str, TattooMeta] = {}
    for txd_name, meta in shop_meta.items():
        # Extract index from txd_name (e.g. "rushtattoo_000" -> 0)
        parts = txd_name.rsplit("_", 1)
        try:
            index = int(parts[-1])
        except (ValueError, IndexError):
            index = -1

        result[txd_name] = TattooMeta(
            txd_name=txd_name,
            index=index,
            label=meta["label"],
            zone=meta["zone"],
            facing=meta["facing"],
            genders=gender_info.get(txd_name, ["unisex"]),
        )

    logger.info("Built tattoo metadata for %d tattoos from %s", len(result), root)
    return result
