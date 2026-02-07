"""Tests for tattoo metadata parser — shop_tattoo.meta and overlays XML."""

import tempfile
import os

import pytest

from src.tattoo_parser import (
    parse_shop_tattoo_meta,
    parse_overlays_xml,
    build_tattoo_meta,
    _normalize_zone,
)


class TestNormalizeZone:
    def test_pdz_prefix(self):
        assert _normalize_zone("PDZ_TORSO") == "torso"

    def test_zone_prefix(self):
        assert _normalize_zone("ZONE_LEFT_ARM") == "left_arm"

    def test_no_prefix(self):
        assert _normalize_zone("HEAD") == "head"

    def test_empty(self):
        assert _normalize_zone("") == ""


class TestParseShopTattooMeta:
    def test_basic_parsing(self, tmp_path):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<TattooShopItemArray>
  <TattooShopItems>
    <Item>
      <textLabel>TEST_TAT_000</textLabel>
      <preset>testtattoo_000_M</preset>
      <zone>PDZ_TORSO</zone>
      <eFacing>TATTOO_BACK</eFacing>
    </Item>
    <Item>
      <textLabel>TEST_TAT_001</textLabel>
      <preset>testtattoo_001_F</preset>
      <zone>PDZ_HEAD</zone>
      <eFacing>TATTOO_FRONT</eFacing>
    </Item>
  </TattooShopItems>
</TattooShopItemArray>"""
        f = tmp_path / "shop_tattoo.meta"
        f.write_text(xml, encoding="utf-8")

        result = parse_shop_tattoo_meta(str(f))
        assert "testtattoo_000" in result
        assert "testtattoo_001" in result
        assert result["testtattoo_000"]["label"] == "TEST_TAT_000"
        assert result["testtattoo_000"]["zone"] == "torso"
        assert result["testtattoo_000"]["facing"] == "back"
        assert result["testtattoo_001"]["zone"] == "head"
        assert result["testtattoo_001"]["facing"] == "front"

    def test_deduplicates_gender_variants(self, tmp_path):
        xml = """<?xml version="1.0"?>
<TattooShopItemArray>
  <TattooShopItems>
    <Item>
      <preset>tat_000_M</preset>
      <textLabel>TAT_000</textLabel>
      <zone>PDZ_TORSO</zone>
      <eFacing>TATTOO_LEFT</eFacing>
    </Item>
    <Item>
      <preset>tat_000_F</preset>
      <textLabel>TAT_000</textLabel>
      <zone>PDZ_TORSO</zone>
      <eFacing>TATTOO_LEFT</eFacing>
    </Item>
  </TattooShopItems>
</TattooShopItemArray>"""
        f = tmp_path / "shop_tattoo.meta"
        f.write_text(xml, encoding="utf-8")

        result = parse_shop_tattoo_meta(str(f))
        # Should have one entry (deduplicated by base name)
        assert len(result) == 1
        assert "tat_000" in result

    def test_wrong_root_raises(self, tmp_path):
        xml = "<WrongRoot><Item/></WrongRoot>"
        f = tmp_path / "bad.meta"
        f.write_text(xml, encoding="utf-8")
        with pytest.raises(ValueError, match="Expected <TattooShopItemArray>"):
            parse_shop_tattoo_meta(str(f))

    def test_lenient_xml_with_stray_tag(self, tmp_path):
        """Handles XML with duplicate </Item> closing tags (real-world issue)."""
        xml = """<?xml version="1.0"?>
<TattooShopItemArray>
  <TattooShopItems>
    <Item>
      <preset>tat_000_M</preset>
      <textLabel>TAT_000</textLabel>
      <zone>PDZ_TORSO</zone>
      <eFacing>TATTOO_BACK</eFacing>
    </Item>
		</Item>
    <Item>
      <preset>tat_001_M</preset>
      <textLabel>TAT_001</textLabel>
      <zone>PDZ_HEAD</zone>
      <eFacing>TATTOO_FRONT</eFacing>
    </Item>
  </TattooShopItems>
</TattooShopItemArray>"""
        f = tmp_path / "shop_tattoo.meta"
        f.write_text(xml, encoding="utf-8")

        result = parse_shop_tattoo_meta(str(f))
        assert len(result) == 2


class TestParseOverlaysXml:
    def test_basic_gender_extraction(self, tmp_path):
        xml = """<?xml version="1.0"?>
<PedDecorationCollection>
  <presets>
    <Item>
      <txdHash>testtattoo_000</txdHash>
      <gender>GENDER_MALE</gender>
    </Item>
    <Item>
      <txdHash>testtattoo_000</txdHash>
      <gender>GENDER_FEMALE</gender>
    </Item>
    <Item>
      <txdHash>testtattoo_001</txdHash>
      <gender>GENDER_MALE</gender>
    </Item>
  </presets>
</PedDecorationCollection>"""
        f = tmp_path / "test_overlays.xml"
        f.write_text(xml, encoding="utf-8")

        result = parse_overlays_xml(str(f))
        assert result["testtattoo_000"] == ["male", "female"]
        assert result["testtattoo_001"] == ["male"]

    def test_no_presets_returns_empty(self, tmp_path):
        xml = "<PedDecorationCollection></PedDecorationCollection>"
        f = tmp_path / "empty.xml"
        f.write_text(xml, encoding="utf-8")
        result = parse_overlays_xml(str(f))
        assert result == {}


class TestBuildTattooMeta:
    def test_empty_directory(self, tmp_path):
        result = build_tattoo_meta(str(tmp_path))
        assert result == {}

    def test_nonexistent_directory(self):
        result = build_tattoo_meta("/nonexistent/path")
        assert result == {}

    def test_integration_with_real_files(self):
        """Test against actual stream data if available."""
        stream_path = "stream"
        if not os.path.isdir(stream_path):
            pytest.skip("stream/ not available")

        result = build_tattoo_meta(stream_path)
        # Should find the rushtattoo entries
        if result:
            assert any("rushtattoo" in k for k in result)
            # Check a known entry
            if "rushtattoo_000" in result:
                meta = result["rushtattoo_000"]
                assert meta.index == 0
                assert meta.zone in ("torso", "head", "left_arm", "right_arm",
                                     "left_leg", "right_leg", "unknown")
                assert meta.label != ""
