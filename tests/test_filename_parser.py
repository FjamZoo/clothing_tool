"""Tests for filename_parser — clothing, prop, and tattoo pattern matching."""

import os

from src.filename_parser import (
    parse_ytd_filename,
    parse_tattoo_filename,
    is_prop_category,
    prop_display_name,
    PROP_CATEGORIES,
    PROP_DISPLAY_NAMES,
    YtdFileInfo,
    TattooFileInfo,
)


# ---------------------------------------------------------------------------
# Standard freemode pattern
# ---------------------------------------------------------------------------

class TestStandardPattern:
    def test_female_basic(self):
        path = r"stream\rhclothing\stream\[female]\accs\mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.model == "mp_f_freemode_01"
        assert info.dlc_name == "rhclothing"
        assert info.gender == "female"
        assert info.category == "accs"
        assert info.drawable_id == 0
        assert info.variant == "a"
        assert info.is_base is True

    def test_male_basic(self):
        path = "stream/rhclothing/stream/[male]/jbib/mp_m_freemode_01_rhclothing^jbib_diff_003_b_uni.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.model == "mp_m_freemode_01"
        assert info.gender == "male"
        assert info.category == "jbib"
        assert info.drawable_id == 3
        assert info.variant == "b"
        assert info.is_base is False

    def test_gender_from_path_overrides_model(self):
        # Path says [male] but model says mp_f_ — path wins
        path = "stream/test/[male]/mp_f_freemode_01_dlc^lowr_diff_001_a_uni.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.gender == "male"

    def test_dlc_with_underscores(self):
        path = "mp_f_freemode_01_mp_f_gunrunning_01^accs_diff_000_a_uni.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.dlc_name == "mp_f_gunrunning_01"

    def test_high_drawable_id(self):
        path = "mp_f_freemode_01_dlc^lowr_diff_999_a_uni.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.drawable_id == 999


# ---------------------------------------------------------------------------
# Custom ped pattern
# ---------------------------------------------------------------------------

class TestCustomPedPattern:
    def test_strafe_basic(self):
        path = r"stream\rhpeds\stream\[strafe]\accs\strafe^accs_diff_001_a_uni.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.model == "strafe"
        assert info.dlc_name == "strafe"
        assert info.category == "accs"
        assert info.drawable_id == 1
        assert info.variant == "a"
        assert info.is_base is True

    def test_custom_ped_gender_unknown(self):
        path = "custped^jbib_diff_000_a_uni.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.gender == "unknown"


# ---------------------------------------------------------------------------
# Non-matching filenames
# ---------------------------------------------------------------------------

class TestNoMatch:
    def test_tattoo_file_returns_none(self):
        assert parse_ytd_filename("rushtattoo_000.ytd") is None

    def test_random_ytd_returns_none(self):
        assert parse_ytd_filename("something_random.ytd") is None

    def test_meta_file_returns_none(self):
        assert parse_ytd_filename("shop_tattoo.meta") is None

    def test_non_base_variant_still_parses(self):
        # Variant _c_ should still parse (it's valid, just not base)
        path = "mp_f_freemode_01_dlc^accs_diff_000_c_uni.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.variant == "c"
        assert info.is_base is False


# ---------------------------------------------------------------------------
# Tattoo pattern
# ---------------------------------------------------------------------------

class TestTattooPattern:
    def test_basic_tattoo(self):
        path = r"stream\new_overlays\stream\rushtattoo_000.ytd"
        info = parse_tattoo_filename(path)
        assert info is not None
        assert info.prefix == "rushtattoo"
        assert info.index == 0

    def test_high_index(self):
        info = parse_tattoo_filename("rushtattoo_084.ytd")
        assert info is not None
        assert info.index == 84

    def test_different_prefix(self):
        info = parse_tattoo_filename("customtattoo_012.ytd")
        assert info is not None
        assert info.prefix == "customtattoo"
        assert info.index == 12

    def test_clothing_file_returns_none(self):
        path = "mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd"
        assert parse_tattoo_filename(path) is None

    def test_non_tattoo_returns_none(self):
        assert parse_tattoo_filename("something_000.ytd") is None

    def test_no_three_digit_index_returns_none(self):
        assert parse_tattoo_filename("rushtattoo_0.ytd") is None
        assert parse_tattoo_filename("rushtattoo_00.ytd") is None

    def test_file_path_preserved(self):
        path = r"C:\full\path\to\rushtattoo_042.ytd"
        info = parse_tattoo_filename(path)
        assert info is not None
        assert info.file_path == path


# ---------------------------------------------------------------------------
# Prop category helper
# ---------------------------------------------------------------------------

class TestPropCategory:
    def test_prop_categories(self):
        assert is_prop_category("p_head") is True
        assert is_prop_category("p_eyes") is True
        assert is_prop_category("p_ears") is True
        assert is_prop_category("p_lwrist") is True
        assert is_prop_category("p_rwrist") is True

    def test_clothing_categories_are_not_props(self):
        assert is_prop_category("accs") is False
        assert is_prop_category("jbib") is False
        assert is_prop_category("lowr") is False
        assert is_prop_category("head") is False

    def test_prop_categories_constant(self):
        assert len(PROP_CATEGORIES) == 5
        assert "p_head" in PROP_CATEGORIES

    def test_prop_display_names(self):
        assert prop_display_name("p_head") == "hat"
        assert prop_display_name("p_eyes") == "glass"
        assert prop_display_name("p_ears") == "ear"
        assert prop_display_name("p_lwrist") == "watch"
        assert prop_display_name("p_rwrist") == "bracelet"

    def test_prop_display_name_passthrough(self):
        # Non-prop categories pass through unchanged
        assert prop_display_name("accs") == "accs"
        assert prop_display_name("jbib") == "jbib"
        assert prop_display_name("head") == "head"

    def test_prop_display_names_constant(self):
        assert len(PROP_DISPLAY_NAMES) == 5
        assert PROP_DISPLAY_NAMES["p_head"] == "hat"


# ---------------------------------------------------------------------------
# Prop filename parsing — standard freemode
# ---------------------------------------------------------------------------

class TestPropStandardPattern:
    def test_female_p_head(self):
        # Props have no suffix (no _uni) — just _diff_NNN_a.ytd
        path = r"stream\government_clothing\stream\[female]\p_head\mp_f_freemode_01_p_rhgovernment^p_head_diff_000_a.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.model == "mp_f_freemode_01"
        assert info.dlc_name == "rhgovernment"  # p_ stripped from DLC name
        assert info.gender == "female"
        assert info.category == "p_head"
        assert info.drawable_id == 0
        assert info.variant == "a"
        assert info.is_base is True

    def test_male_p_eyes(self):
        path = "stream/rhclothing/stream/[male]/p_eyes/mp_m_freemode_01_p_rhclothing^p_eyes_diff_001_a.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.model == "mp_m_freemode_01"
        assert info.dlc_name == "rhclothing"  # p_ stripped
        assert info.gender == "male"
        assert info.category == "p_eyes"
        assert info.drawable_id == 1

    def test_p_ears(self):
        path = "mp_f_freemode_01_p_rhclothing2^p_ears_diff_002_a.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.dlc_name == "rhclothing2"  # p_ stripped
        assert info.category == "p_ears"

    def test_p_lwrist(self):
        path = "mp_m_freemode_01_p_rhgovernment^p_lwrist_diff_000_a.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.dlc_name == "rhgovernment"
        assert info.category == "p_lwrist"

    def test_p_rwrist(self):
        path = "mp_m_freemode_01_p_rhclothing^p_rwrist_diff_003_c.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.dlc_name == "rhclothing"
        assert info.category == "p_rwrist"
        assert info.variant == "c"
        assert info.is_base is False

    def test_prop_variant_b_still_parses(self):
        path = "mp_f_freemode_01_p_rhclothing^p_head_diff_000_b.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.variant == "b"
        assert info.is_base is False
        assert info.dlc_name == "rhclothing"

    def test_prop_with_suffix_still_works(self):
        # Some props may have a suffix — ensure backward compat
        path = "mp_f_freemode_01_p_rhclothing^p_head_diff_000_a_uni.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.dlc_name == "rhclothing"
        assert info.category == "p_head"


# ---------------------------------------------------------------------------
# Prop filename parsing — base game
# ---------------------------------------------------------------------------

class TestPropBaseGamePattern:
    def test_base_game_p_head(self):
        # Base game props have no suffix: p_head_diff_000_a.ytd
        path = "base_game/base/mp_f_freemode_01_p/p_head_diff_000_a.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.model == "base_game"
        assert info.dlc_name == "base"
        assert info.gender == "female"
        assert info.category == "p_head"
        assert info.drawable_id == 0

    def test_base_game_p_eyes(self):
        path = "base_game/base/mp_m_freemode_01_p/p_eyes_diff_003_a.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.dlc_name == "base"
        assert info.gender == "male"
        assert info.category == "p_eyes"

    def test_base_game_subpack_prop(self):
        path = "base_game/airraces/mp_f_freemode_01_p_mp_f_airraces_01/p_head_diff_000_a.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.dlc_name == "mp_f_airraces_01"  # p_ stripped from suffix
        assert info.gender == "female"
        assert info.category == "p_head"

    def test_base_game_subpack_prop_male(self):
        path = "base_game/mpbiker/mp_m_freemode_01_p_mp_m_bikerdlc_01/p_rwrist_diff_000_a.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.dlc_name == "mp_m_bikerdlc_01"
        assert info.gender == "male"
        assert info.category == "p_rwrist"


# ---------------------------------------------------------------------------
# Prop filename parsing — custom ped
# ---------------------------------------------------------------------------

class TestPropCustomPed:
    def test_custom_ped_prop(self):
        path = "stream/rhpeds/stream/[strafe]/p_head/strafe^p_head_diff_000_a.ytd"
        info = parse_ytd_filename(path)
        assert info is not None
        assert info.model == "strafe"
        assert info.dlc_name == "strafe"  # no p_ to strip for custom peds
        assert info.category == "p_head"
        assert info.drawable_id == 0
