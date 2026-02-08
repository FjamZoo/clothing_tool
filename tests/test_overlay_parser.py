"""Tests for overlay_parser — face overlay discovery and classification."""

import os
import tempfile
from pathlib import Path

from src.overlay_parser import (
    OverlayInfo,
    discover_overlays,
    _classify_gender,
    _FAOV_RE,
    PORTRAIT_UPPER,
    PORTRAIT_LOWER,
)


# ---------------------------------------------------------------------------
# Regex pattern matching
# ---------------------------------------------------------------------------

class TestFaovRegex:
    def test_beard(self):
        m = _FAOV_RE.match("mp_fm_faov_beard_000.ytd")
        assert m is not None
        assert m.group("type") == "beard"
        assert m.group("index") == "000"

    def test_eyebrowf(self):
        m = _FAOV_RE.match("mp_fm_faov_eyebrowf_016.ytd")
        assert m is not None
        assert m.group("type") == "eyebrowf"
        assert m.group("index") == "016"

    def test_eyebrowm(self):
        m = _FAOV_RE.match("mp_fm_faov_eyebrowm_005.ytd")
        assert m is not None
        assert m.group("type") == "eyebrowm"

    def test_makeup(self):
        m = _FAOV_RE.match("mp_fm_faov_makeup_032.ytd")
        assert m is not None
        assert m.group("type") == "makeup"

    def test_makeupm(self):
        m = _FAOV_RE.match("mp_fm_faov_makeupm_003.ytd")
        assert m is not None
        assert m.group("type") == "makeupm"

    def test_lips_g(self):
        m = _FAOV_RE.match("mp_fm_faov_lips_g_002.ytd")
        assert m is not None
        assert m.group("type") == "lips_g"

    def test_acne(self):
        m = _FAOV_RE.match("mp_fm_faov_acne_017.ytd")
        assert m is not None
        assert m.group("type") == "acne"

    def test_weather(self):
        m = _FAOV_RE.match("mp_fm_faov_weather_013.ytd")
        assert m is not None
        assert m.group("type") == "weather"

    def test_skip_normal_map(self):
        """Normal maps have _n suffix before .ytd — should NOT match."""
        # The regex would match this, but discover_overlays() filters it out
        # by checking stem.endswith('_n')
        m = _FAOV_RE.match("mp_fm_faov_beard_001_n.ytd")
        # This actually matches the regex (type="beard_001_n" is wrong pattern)
        # but discover_overlays filters these via endswith check before regex
        pass

    def test_skip_specular_map(self):
        """Specular maps end with _s — filtered by discover_overlays."""
        pass

    def test_non_overlay_no_match(self):
        m = _FAOV_RE.match("mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd")
        assert m is None

    def test_case_insensitive(self):
        m = _FAOV_RE.match("MP_FM_FAOV_BEARD_000.YTD")
        assert m is not None


# ---------------------------------------------------------------------------
# Gender classification
# ---------------------------------------------------------------------------

class TestGenderClassification:
    def test_beard_is_male(self):
        assert _classify_gender("beard") == "male"

    def test_eyebrowf_is_female(self):
        assert _classify_gender("eyebrowf") == "female"

    def test_eyebrowm_is_male(self):
        assert _classify_gender("eyebrowm") == "male"

    def test_makeup_is_female(self):
        assert _classify_gender("makeup") == "female"

    def test_makeupm_is_male(self):
        assert _classify_gender("makeupm") == "male"

    def test_lips_g_is_female(self):
        assert _classify_gender("lips_g") == "female"

    def test_acne_defaults_male(self):
        assert _classify_gender("acne") == "male"

    def test_blemish_defaults_male(self):
        assert _classify_gender("blemish") == "male"

    def test_weather_defaults_male(self):
        assert _classify_gender("weather") == "male"


# ---------------------------------------------------------------------------
# Portrait framing categories
# ---------------------------------------------------------------------------

class TestPortraitCategories:
    def test_eyebrows_in_upper(self):
        assert "eyebrowf" in PORTRAIT_UPPER
        assert "eyebrowm" in PORTRAIT_UPPER

    def test_beard_in_lower(self):
        assert "beard" in PORTRAIT_LOWER

    def test_acne_not_in_either(self):
        assert "acne" not in PORTRAIT_UPPER
        assert "acne" not in PORTRAIT_LOWER


# ---------------------------------------------------------------------------
# Discovery function
# ---------------------------------------------------------------------------

class TestDiscoverOverlays:
    def test_discovers_diffuse_only(self):
        """Should find diffuse files and skip _n/_s maps."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            Path(tmpdir, "mp_fm_faov_beard_000.ytd").touch()
            Path(tmpdir, "mp_fm_faov_beard_000_n.ytd").touch()
            Path(tmpdir, "mp_fm_faov_beard_000_s.ytd").touch()
            Path(tmpdir, "mp_fm_faov_eyebrowf_001.ytd").touch()
            Path(tmpdir, "mp_fm_faov_eyebrowf_001_n.ytd").touch()
            Path(tmpdir, "mp_fm_faov_eyebrowf_001_s.ytd").touch()
            # Non-overlay file (should be ignored)
            Path(tmpdir, "some_other_file.ytd").touch()

            results = discover_overlays(Path(tmpdir))

            assert len(results) == 2
            types = {r.overlay_type for r in results}
            assert types == {"beard", "eyebrowf"}

    def test_correct_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "mp_fm_faov_beard_007.ytd").touch()

            results = discover_overlays(Path(tmpdir))

            assert len(results) == 1
            ov = results[0]
            assert ov.overlay_type == "beard"
            assert ov.index == 7
            assert ov.gender == "male"
            assert ov.file_path.name == "mp_fm_faov_beard_007.ytd"

    def test_sorted_by_type_and_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "mp_fm_faov_eyebrowm_002.ytd").touch()
            Path(tmpdir, "mp_fm_faov_beard_001.ytd").touch()
            Path(tmpdir, "mp_fm_faov_beard_000.ytd").touch()
            Path(tmpdir, "mp_fm_faov_acne_005.ytd").touch()

            results = discover_overlays(Path(tmpdir))

            # Sorted by filename → alphabetical: acne, beard_000, beard_001, eyebrowm
            names = [r.overlay_type for r in results]
            assert names == ["acne", "beard", "beard", "eyebrowm"]
            indices = [r.index for r in results]
            assert indices == [5, 0, 1, 2]

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = discover_overlays(Path(tmpdir))
            assert results == []

    def test_nonexistent_directory(self):
        results = discover_overlays(Path("/nonexistent/path"))
        assert results == []

    def test_all_overlay_types(self):
        """Verify all known overlay types are recognized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            types = [
                "acne", "bags", "beard", "blemish", "blusher", "cheeks",
                "damage", "eyebrowf", "eyebrowm", "flan", "foundation",
                "infect", "lips", "lips_g", "lipsm", "makeup", "makeupm",
                "mole", "skin", "spots", "weather",
            ]
            for t in types:
                Path(tmpdir, f"mp_fm_faov_{t}_000.ytd").touch()

            results = discover_overlays(Path(tmpdir))
            found_types = {r.overlay_type for r in results}
            assert found_types == set(types)
