"""Tests for DDS header construction."""

import struct

import pytest

from src.ytd_parser import TextureInfo
from src.dds_builder import build_dds, _mip0_size


def _make_texture(fmt: str = "DXT5", width: int = 1024, height: int = 1024,
                  mips: int = 1, data_size: int | None = None) -> TextureInfo:
    if data_size is None:
        data_size = _mip0_size(width, height, fmt)
    return TextureInfo(
        name="test",
        width=width,
        height=height,
        format_code=0,
        format_name=fmt,
        mip_levels=mips,
        stride=0,
        raw_data=b"\x00" * data_size,
    )


class TestMip0Size:
    def test_dxt1_4x4_min(self):
        assert _mip0_size(4, 4, "DXT1") == 8

    def test_dxt5_4x4_min(self):
        assert _mip0_size(4, 4, "DXT5") == 16

    def test_dxt1_1024(self):
        # 256 * 256 blocks * 8 bytes
        assert _mip0_size(1024, 1024, "DXT1") == 256 * 256 * 8

    def test_bc7_512(self):
        # 128 * 128 blocks * 16 bytes
        assert _mip0_size(512, 512, "BC7") == 128 * 128 * 16

    def test_a8r8g8b8(self):
        assert _mip0_size(256, 256, "A8R8G8B8") == 256 * 256 * 4

    def test_l8(self):
        assert _mip0_size(128, 128, "L8") == 128 * 128

    def test_unknown_format_raises(self):
        with pytest.raises(ValueError, match="Cannot compute"):
            _mip0_size(64, 64, "UNKNOWN_FMT")


class TestBuildDDS:
    def test_magic_bytes(self):
        tex = _make_texture("DXT5")
        dds = build_dds(tex)
        assert dds[:4] == b"DDS "

    def test_header_size_124(self):
        tex = _make_texture("DXT1")
        dds = build_dds(tex)
        # Byte 4..7 is dwSize = 124
        size = struct.unpack_from("<I", dds, 4)[0]
        assert size == 124

    def test_width_and_height(self):
        tex = _make_texture("DXT5", width=512, height=256)
        dds = build_dds(tex)
        height = struct.unpack_from("<I", dds, 12)[0]
        width = struct.unpack_from("<I", dds, 16)[0]
        assert width == 512
        assert height == 256

    def test_bc7_has_dx10_header(self):
        tex = _make_texture("BC7", width=512, height=512)
        dds = build_dds(tex)
        # DX10 header starts at offset 128 (4 magic + 124 header)
        # First field is dxgiFormat = 98
        dxgi_format = struct.unpack_from("<I", dds, 128)[0]
        assert dxgi_format == 98

    def test_dxt1_no_dx10_header(self):
        tex = _make_texture("DXT1", width=64, height=64)
        dds = build_dds(tex)
        # Total size = 4 (magic) + 124 (header) + data
        expected_data_size = _mip0_size(64, 64, "DXT1")
        assert len(dds) == 4 + 124 + expected_data_size

    def test_unsupported_format_raises(self):
        tex = TextureInfo(
            name="bad", width=64, height=64, format_code=0,
            format_name="FAKE_FORMAT", mip_levels=1, stride=0,
            raw_data=b"\x00" * 64,
        )
        with pytest.raises(ValueError):
            build_dds(tex)
