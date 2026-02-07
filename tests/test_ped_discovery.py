"""Tests for custom ped discovery."""

import os
import pytest
from src.scanner import discover_custom_peds


class TestDiscoverCustomPeds:
    """Test discovery of custom ped directories with .yft skeletons."""

    def test_finds_ped_with_yft(self, tmp_path):
        """A directory containing a .yft file is detected as a custom ped."""
        ped_dir = tmp_path / "stream" / "rhpeds" / "stream" / "[strafe]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "strafe.yft").write_bytes(b"\x00" * 100)
        # Create default body part YDDs + YTDs
        for cat in ("head", "uppr", "lowr", "feet", "hand"):
            (ped_dir / f"strafe^{cat}_000_u.ydd").write_bytes(b"\x00" * 2000)
            (ped_dir / f"strafe^{cat}_diff_000_a_uni.ytd").write_bytes(b"\x00" * 200)

        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert len(peds) == 1
        ped = peds[0]
        assert ped["model"] == "strafe"
        assert ped["yft_path"].endswith("strafe.yft")
        assert len(ped["body_parts"]) == 5
        assert set(ped["body_parts"].keys()) == {"head", "uppr", "lowr", "feet", "hand"}

    def test_skips_directory_without_yft(self, tmp_path):
        """A directory with YDDs but no .yft is NOT a custom ped."""
        ped_dir = tmp_path / "stream" / "pack" / "stream" / "[noped]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "noped^uppr_000_u.ydd").write_bytes(b"\x00" * 2000)
        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert len(peds) == 0

    def test_body_part_has_ydd_and_ytd(self, tmp_path):
        """Each body part dict has both ydd_path and ytd_path."""
        ped_dir = tmp_path / "stream" / "pack" / "stream" / "[test]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "testped.yft").write_bytes(b"\x00" * 100)
        (ped_dir / "testped^head_000_u.ydd").write_bytes(b"\x00" * 2000)
        (ped_dir / "testped^head_diff_000_a_uni.ytd").write_bytes(b"\x00" * 200)
        (ped_dir / "testped^uppr_000_u.ydd").write_bytes(b"\x00" * 2000)
        (ped_dir / "testped^uppr_diff_000_a_uni.ytd").write_bytes(b"\x00" * 200)

        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert len(peds) == 1
        head = peds[0]["body_parts"]["head"]
        assert head["ydd_path"].endswith("testped^head_000_u.ydd")
        assert head["ytd_path"].endswith("testped^head_diff_000_a_uni.ytd")

    def test_includes_optional_hair(self, tmp_path):
        """Hair (optional category) is included when present."""
        ped_dir = tmp_path / "stream" / "pack" / "stream" / "[myped]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "myped.yft").write_bytes(b"\x00" * 100)
        for cat in ("head", "uppr", "lowr", "feet", "hand", "hair"):
            (ped_dir / f"myped^{cat}_000_u.ydd").write_bytes(b"\x00" * 2000)
            (ped_dir / f"myped^{cat}_diff_000_a_uni.ytd").write_bytes(b"\x00" * 200)

        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert "hair" in peds[0]["body_parts"]

    def test_output_path(self, tmp_path):
        """Output path follows textures/{ped_name}/preview.webp convention."""
        ped_dir = tmp_path / "stream" / "pack" / "stream" / "[strafe]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "strafe.yft").write_bytes(b"\x00" * 100)
        for cat in ("head", "uppr", "lowr", "feet", "hand"):
            (ped_dir / f"strafe^{cat}_000_u.ydd").write_bytes(b"\x00" * 2000)
            (ped_dir / f"strafe^{cat}_diff_000_a_uni.ytd").write_bytes(b"\x00" * 200)

        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert peds[0]["output_rel"] == "strafe/preview.webp"

    def test_skips_replacements_directory(self, tmp_path):
        """Directories named [replacements] are skipped."""
        ped_dir = tmp_path / "stream" / "pack" / "stream" / "[replacements]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "someped.yft").write_bytes(b"\x00" * 100)
        (ped_dir / "someped^head_000_u.ydd").write_bytes(b"\x00" * 2000)
        (ped_dir / "someped^head_diff_000_a_uni.ytd").write_bytes(b"\x00" * 200)
        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert len(peds) == 0

    def test_ethnicity_suffix_ytd(self, tmp_path):
        """YTD files with ethnicity suffixes (_whi, _bla) are found."""
        ped_dir = tmp_path / "stream" / "pack" / "stream" / "[eped]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "eped.yft").write_bytes(b"\x00" * 100)
        (ped_dir / "eped^head_000_u.ydd").write_bytes(b"\x00" * 2000)
        (ped_dir / "eped^head_diff_000_a_whi.ytd").write_bytes(b"\x00" * 200)

        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert len(peds) == 1
        assert "head" in peds[0]["body_parts"]
        assert peds[0]["body_parts"]["head"]["ytd_path"].endswith("_whi.ytd")
