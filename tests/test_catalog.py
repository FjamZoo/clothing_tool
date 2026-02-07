"""Quick tests for CatalogBuilder and catalog.json output structure."""

import json
import os
import tempfile

from src.catalog import CatalogBuilder, CatalogItem


def _make_item(**overrides) -> CatalogItem:
    defaults = dict(
        dlc_name="rhclothing",
        gender="female",
        category="accs",
        drawable_id=0,
        texture_path="rhclothing/female/accs/000.webp",
        variants=22,
        source_file="mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd",
        width=512,
        height=512,
        original_width=1024,
        original_height=1024,
        format_name="DXT5",
    )
    defaults.update(overrides)
    return CatalogItem(**defaults)


def test_add_item_key_format():
    builder = CatalogBuilder()
    builder.add_item(_make_item(dlc_name="mydlc", gender="male", category="jbib", drawable_id=7))
    assert "mydlc_male_jbib_007" in builder.items


def test_add_item_overwrites_duplicate():
    builder = CatalogBuilder()
    builder.add_item(_make_item(variants=5))
    builder.add_item(_make_item(variants=10))
    key = "rhclothing_female_accs_000"
    assert builder.items[key].variants == 10


def test_add_failure():
    builder = CatalogBuilder()
    builder.add_failure("bad_file.ytd", "corrupt header")
    assert len(builder.failed) == 1
    assert builder.failed[0]["file"] == "bad_file.ytd"
    assert builder.failed[0]["error"] == "corrupt header"


def test_write_creates_directories_and_valid_json():
    builder = CatalogBuilder()

    builder.add_item(_make_item())
    builder.add_item(_make_item(
        dlc_name="rhclothing",
        gender="male",
        category="jbib",
        drawable_id=3,
        texture_path="rhclothing/male/jbib/003.webp",
        variants=4,
        source_file="mp_m_freemode_01_rhclothing^jbib_diff_003_a_uni.ytd",
        original_width=2048,
        original_height=2048,
        format_name="BC7",
    ))
    builder.add_item(_make_item(
        dlc_name="government",
        gender="female",
        category="lowr",
        drawable_id=12,
        texture_path="government/female/lowr/012.webp",
        variants=1,
        source_file="mp_f_freemode_01_government^lowr_diff_012_a_uni.ytd",
        original_width=512,
        original_height=512,
        format_name="DXT1",
    ))

    builder.add_failure("corrupt.ytd", "file too small")
    builder.add_failure("broken.ytd", "unknown format 0xFF")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "subdir", "catalog.json")
        builder.write(out_path)

        assert os.path.isfile(out_path)

        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)

    # Top-level fields
    assert "generated_at" in data
    assert data["total_items"] == 3
    assert data["total_failed"] == 2

    # Items dict
    items = data["items"]
    assert len(items) == 3

    # Check specific item camelCase keys
    entry = items["rhclothing_female_accs_000"]
    assert entry["dlcName"] == "rhclothing"
    assert entry["gender"] == "female"
    assert entry["category"] == "accs"
    assert entry["drawableId"] == 0
    assert entry["texture"] == "rhclothing/female/accs/000.webp"
    assert entry["variants"] == 22
    assert entry["source"] == "mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd"
    assert entry["width"] == 512
    assert entry["height"] == 512
    assert entry["originalWidth"] == 1024
    assert entry["originalHeight"] == 1024
    assert entry["format"] == "DXT5"
    assert entry["renderType"] == "flat"

    # Check the BC7 item
    jbib = items["rhclothing_male_jbib_003"]
    assert jbib["format"] == "BC7"
    assert jbib["originalWidth"] == 2048

    # Check sorted order of keys
    keys = list(items.keys())
    assert keys == sorted(keys)


def test_write_empty_catalog():
    builder = CatalogBuilder()
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "catalog.json")
        builder.write(out_path)

        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)

    assert data["total_items"] == 0
    assert data["total_failed"] == 0
    assert data["items"] == {}


if __name__ == "__main__":
    test_add_item_key_format()
    test_add_item_overwrites_duplicate()
    test_add_failure()
    test_write_creates_directories_and_valid_json()
    test_write_empty_catalog()
    print("All catalog tests passed!")
