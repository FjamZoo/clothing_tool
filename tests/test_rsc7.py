"""Tests for RSC7 container parser — header validation, decompression, errors."""

import struct
import tempfile
import zlib

import pytest

from src.rsc7 import parse_rsc7, get_size_from_flags, RSC7_MAGIC, RSC7_HEADER_SIZE


class TestGetSizeFromFlags:
    def test_zero_flags(self):
        assert get_size_from_flags(0) == 0

    def test_known_flag_values(self):
        # A single base-page entry should produce a non-zero size
        # flags with ss=0 (base_size=0x200=512) and s4=1 page (bit 17 set, shift 4)
        flags = (1 << 17) | 0  # 1 page at 16x base, ss=0 -> 512 * 16 = 8192
        result = get_size_from_flags(flags)
        assert result > 0


class TestParseRSC7:
    def _make_rsc7(self, virtual_data: bytes, physical_data: bytes,
                   version: int = 13) -> bytes:
        """Build a minimal valid RSC7 file for testing."""
        combined = virtual_data + physical_data

        # Compute flags that encode the segment sizes.
        # For simplicity, use ss=0 (base=512) and s4 to encode page count.
        def encode_flags(size: int) -> int:
            if size == 0:
                return 0
            base = 0x200  # ss=0
            pages = (size + base * 16 - 1) // (base * 16)
            return (pages & 0x7F) << 17  # s4 field

        sys_flags = encode_flags(len(virtual_data))
        gfx_flags = encode_flags(len(physical_data))

        header = struct.pack("<4I", RSC7_MAGIC, version, sys_flags, gfx_flags)
        compressed = zlib.compress(combined)[2:-4]  # raw deflate (strip zlib wrapper)
        return header + compressed

    def test_valid_file(self, tmp_path):
        vdata = b"\x00" * 8192
        pdata = b"\xFF" * 8192
        raw = self._make_rsc7(vdata, pdata)
        f = tmp_path / "test.ytd"
        f.write_bytes(raw)

        resource = parse_rsc7(str(f))
        assert resource.version == 13
        assert len(resource.virtual_data) > 0
        assert len(resource.physical_data) > 0

    def test_file_too_small(self, tmp_path):
        f = tmp_path / "tiny.ytd"
        f.write_bytes(b"\x00" * 16)
        with pytest.raises(ValueError, match="too small"):
            parse_rsc7(str(f))

    def test_invalid_magic(self, tmp_path):
        f = tmp_path / "bad_magic.ytd"
        bad = struct.pack("<4I", 0xDEADBEEF, 13, 0, 0)
        f.write_bytes(bad + b"\x00" * 32)
        with pytest.raises(ValueError, match="Invalid RSC7 magic"):
            parse_rsc7(str(f))

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_rsc7("nonexistent_file.ytd")


class TestRealTattooFile:
    """Test RSC7 parsing on a real tattoo .ytd file."""

    TATTOO_PATH = "stream/new_overlays/stream/rushtattoo_000.ytd"

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        import os
        if not os.path.isfile(self.TATTOO_PATH):
            pytest.skip("Tattoo test fixture not available")

    def test_parses_successfully(self):
        resource = parse_rsc7(self.TATTOO_PATH)
        assert resource.version == 13
        assert len(resource.virtual_data) >= 64
        assert len(resource.physical_data) > 0

    def test_segments_have_data(self):
        resource = parse_rsc7(self.TATTOO_PATH)
        # Physical data should contain actual pixel data (not all zeros)
        non_zero = sum(1 for b in resource.physical_data[:4096] if b != 0)
        assert non_zero > 100, "Physical data appears to be mostly zeros"
