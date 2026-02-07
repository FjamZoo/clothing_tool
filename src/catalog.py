"""Accumulate processed items and write catalog.json."""

from dataclasses import dataclass
import json
import os
from datetime import datetime, timezone


@dataclass
class CatalogItem:
    dlc_name: str
    gender: str
    category: str
    drawable_id: int
    texture_path: str       # Relative: "rhclothing/female/accs/000.webp"
    variants: int
    source_file: str        # Original .ytd filename
    width: int              # Output width (512)
    height: int             # Output height (512)
    original_width: int     # Source texture width
    original_height: int    # Source texture height
    format_name: str        # "DXT5", "BC7", etc.
    render_type: str = "flat"  # "flat" or "3d"
    item_type: str = "clothing"  # "clothing" or "tattoo"
    zone: str = ""          # Body zone for tattoos: "torso", "head", etc.


class CatalogBuilder:
    def __init__(self):
        self.items: dict[str, CatalogItem] = {}
        self.failed: list[dict] = []

    def add_item(self, item: CatalogItem):
        """Add a successfully processed item."""
        key = f"{item.dlc_name}_{item.gender}_{item.category}_{item.drawable_id:03d}"
        self.items[key] = item

    def add_failure(self, file_path: str, error: str):
        """Record a failed file."""
        self.failed.append({"file": file_path, "error": error})

    def write(self, output_path: str):
        """Write catalog.json to disk.

        Creates parent directories if they don't exist.  The output
        follows the camelCase JSON schema expected by the web UI.
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        catalog = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_items": len(self.items),
            "total_failed": len(self.failed),
            "items": {
                key: {
                    "dlcName": item.dlc_name,
                    "gender": item.gender,
                    "category": item.category,
                    "drawableId": item.drawable_id,
                    "texture": item.texture_path,
                    "variants": item.variants,
                    "source": item.source_file,
                    "width": item.width,
                    "height": item.height,
                    "originalWidth": item.original_width,
                    "originalHeight": item.original_height,
                    "format": item.format_name,
                    "renderType": item.render_type,
                    "itemType": item.item_type,
                    **({"zone": item.zone} if item.zone else {}),
                }
                for key, item in sorted(self.items.items())
            },
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(catalog, f, indent=2, ensure_ascii=False)
            f.write("\n")
