"""Tests for YTD texture dictionary parser — diffuse texture selection."""

from src.ytd_parser import TextureInfo, select_diffuse_texture


def _make_texture(name: str = "diffuse", width: int = 1024, height: int = 1024,
                  fmt: str = "DXT5") -> TextureInfo:
    return TextureInfo(
        name=name,
        width=width,
        height=height,
        format_code=0,
        format_name=fmt,
        mip_levels=1,
        stride=0,
        raw_data=b"\x00" * 16,
    )


class TestSelectDiffuseTexture:
    def test_single_texture_returned(self):
        tex = _make_texture("anything")
        result = select_diffuse_texture([tex])
        assert result is tex

    def test_empty_list(self):
        assert select_diffuse_texture([]) is None

    def test_excludes_normal_map(self):
        diffuse = _make_texture("shirt_diff")
        normal = _make_texture("shirt_n", width=2048, height=2048)
        result = select_diffuse_texture([diffuse, normal])
        assert result is diffuse

    def test_excludes_specular(self):
        diffuse = _make_texture("shirt_diff")
        specular = _make_texture("shirt_s")
        result = select_diffuse_texture([diffuse, specular])
        assert result is diffuse

    def test_excludes_mask(self):
        diffuse = _make_texture("shirt_diff")
        mask = _make_texture("shirt_m")
        result = select_diffuse_texture([diffuse, mask])
        assert result is diffuse

    def test_picks_highest_resolution(self):
        small = _make_texture("tex_a", width=512, height=512)
        large = _make_texture("tex_b", width=2048, height=2048)
        result = select_diffuse_texture([small, large])
        assert result is large

    def test_all_non_diffuse_returns_none(self):
        textures = [
            _make_texture("thing_n"),
            _make_texture("thing_s"),
            _make_texture("thing_m"),
        ]
        assert select_diffuse_texture(textures) is None

    def test_case_insensitive_suffix(self):
        diffuse = _make_texture("shirt_diff")
        normal = _make_texture("shirt_N")  # uppercase
        # Our parser uses .lower() so this should be excluded
        result = select_diffuse_texture([diffuse, normal])
        assert result is diffuse
