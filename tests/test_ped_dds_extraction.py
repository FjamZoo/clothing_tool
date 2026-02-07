"""Tests for DDS pre-extraction for full ped body parts."""

import os
import pytest
from unittest.mock import patch, MagicMock


class TestPreExtractPedDds:
    """Test DDS extraction for all body parts of a custom ped."""

    def test_extracts_dds_for_each_body_part(self, tmp_path):
        """Each body part's YTD should produce DDS files."""
        from src.blender_renderer import pre_extract_ped_dds

        # Create mock ped dict
        ped = {
            "model": "testped",
            "body_parts": {
                "head": {"ydd_path": str(tmp_path / "head.ydd"), "ytd_path": "/fake/head.ytd"},
                "uppr": {"ydd_path": str(tmp_path / "uppr.ydd"), "ytd_path": "/fake/uppr.ytd"},
            },
        }

        # Mock the actual DDS extraction to return fake files
        fake_dds = [str(tmp_path / "texture.dds")]
        (tmp_path / "texture.dds").write_bytes(b"\x00" * 100)

        with patch("src.blender_renderer.extract_dds_for_ydd", return_value=fake_dds):
            result = pre_extract_ped_dds(ped, str(tmp_path / "dds_cache"))

        assert "head" in result
        assert "uppr" in result
        assert isinstance(result["head"], list)
        assert len(result["head"]) > 0

    def test_handles_extraction_failure(self, tmp_path):
        """If DDS extraction fails for a part, it returns empty list."""
        from src.blender_renderer import pre_extract_ped_dds

        ped = {
            "model": "testped",
            "body_parts": {
                "head": {"ydd_path": str(tmp_path / "head.ydd"), "ytd_path": "/fake/head.ytd"},
            },
        }

        with patch("src.blender_renderer.extract_dds_for_ydd", side_effect=Exception("parse error")):
            result = pre_extract_ped_dds(ped, str(tmp_path / "dds_cache"))

        assert result["head"] == []
