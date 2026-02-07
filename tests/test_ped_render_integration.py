"""Integration test for full ped rendering pipeline."""

import json
import os


class TestPedCatalogEntry:
    """Test that ped previews are correctly added to the catalog."""

    def test_ped_preview_catalog_item(self, tmp_path):
        from src.catalog import CatalogBuilder, CatalogItem

        catalog = CatalogBuilder()
        catalog.add_item(CatalogItem(
            dlc_name="strafe",
            gender="unknown",
            category="preview",
            drawable_id=0,
            texture_path="strafe/preview.webp",
            variants=0,
            source_file="strafe.yft",
            width=512,
            height=512,
            original_width=1024,
            original_height=1024,
            format_name="3D_RENDER",
            render_type="3d",
            item_type="ped_preview",
        ))

        # Write and read back to verify JSON structure
        catalog_path = str(tmp_path / "catalog.json")
        catalog.write(catalog_path)

        with open(catalog_path, "r") as f:
            data = json.load(f)

        key = "strafe_unknown_preview_000"
        assert key in data["items"]
        assert data["items"][key]["itemType"] == "ped_preview"
        assert data["items"][key]["renderType"] == "3d"

    def test_ped_preview_texture_path(self, tmp_path):
        from src.catalog import CatalogBuilder, CatalogItem

        catalog = CatalogBuilder()
        catalog.add_item(CatalogItem(
            dlc_name="myped",
            gender="unknown",
            category="preview",
            drawable_id=0,
            texture_path="myped/preview.webp",
            variants=0,
            source_file="myped.yft",
            width=512,
            height=512,
            original_width=1024,
            original_height=1024,
            format_name="3D_RENDER",
            render_type="3d",
            item_type="ped_preview",
        ))

        catalog_path = str(tmp_path / "catalog.json")
        catalog.write(catalog_path)

        with open(catalog_path, "r") as f:
            data = json.load(f)

        key = "myped_unknown_preview_000"
        assert data["items"][key]["texture"] == "myped/preview.webp"
        assert data["items"][key]["format"] == "3D_RENDER"
