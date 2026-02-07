"""Tests for body skin texture filtering.

Verifies that the skin_filter module correctly identifies and removes
body skin textures (duplicated opaque textures in uppr/lowr categories)
while preserving unique clothing textures.
"""

import hashlib
import os
import struct
import tempfile
import zlib

import pytest
from PIL import Image

from src.skin_filter import (
    BODY_OVERLAY_CATEGORIES,
    _DUPLICATE_THRESHOLD,
    _OPACITY_THRESHOLD,
    _texture_hash_and_opacity,
    filter_body_skin_items,
)


# ---------------------------------------------------------------------------
# Helpers: create minimal .ytd files with controlled textures
# ---------------------------------------------------------------------------

def _make_dxt1_data(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Create minimal DXT1-compressed data that decodes to a solid color.

    DXT1 uses 4x4 pixel blocks, each 8 bytes:
      - 2 bytes: color0 (RGB565)
      - 2 bytes: color1 (RGB565)
      - 4 bytes: index bits (all 0 → every pixel uses color0)
    """
    r, g, b = rgb
    # Pack as RGB565 (5 bits R, 6 bits G, 5 bits B)
    color565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    color_bytes = struct.pack("<H", color565)

    block = color_bytes + color_bytes + b"\x00\x00\x00\x00"  # 8 bytes per block

    blocks_x = max(1, (width + 3) // 4)
    blocks_y = max(1, (height + 3) // 4)
    return block * (blocks_x * blocks_y)


def _build_ytd_bytes(
    tex_name: str,
    width: int,
    height: int,
    raw_data: bytes,
    format_code: int = 0x31545844,  # DXT1
) -> bytes:
    """Build a minimal RSC7 .ytd resource with one texture.

    This creates a valid RSC7 file that rsc7.parse_rsc7() can decompress
    and ytd_parser.parse_texture_dictionary() can parse.
    """
    # --- Virtual segment (structs) ---
    # TextureDictionary header: 64 bytes
    # Texture pointer array: 8 bytes (one pointer)
    # Texture struct: 144 bytes
    # Texture name: variable

    name_bytes = tex_name.encode("ascii") + b"\x00"
    # Pad name to 4-byte alignment
    while len(name_bytes) % 4 != 0:
        name_bytes += b"\x00"

    # Layout offsets within virtual segment:
    DICT_OFFSET = 0           # TextureDictionary header (64 bytes)
    PTR_ARRAY_OFFSET = 64     # Pointer array (8 bytes)
    TEX_OFFSET = 72           # Texture struct (144 bytes)
    NAME_OFFSET = 216         # Name string

    virtual_size = NAME_OFFSET + len(name_bytes)
    virtual = bytearray(virtual_size)

    # TextureDictionary header
    # 0x30: pointer to texture pointer array
    textures_ptr = 0x50000000 + PTR_ARRAY_OFFSET
    struct.pack_into("<Q", virtual, 0x30, textures_ptr)
    # 0x38: count, 0x3A: capacity
    struct.pack_into("<H", virtual, 0x38, 1)   # count = 1
    struct.pack_into("<H", virtual, 0x3A, 1)   # capacity = 1

    # Pointer array: one 64-bit pointer to the texture struct
    tex_ptr = 0x50000000 + TEX_OFFSET
    struct.pack_into("<Q", virtual, PTR_ARRAY_OFFSET, tex_ptr)

    # Texture struct (144 bytes at TEX_OFFSET)
    # 0x28: name pointer
    name_ptr = 0x50000000 + NAME_OFFSET
    struct.pack_into("<Q", virtual, TEX_OFFSET + 0x28, name_ptr)
    # 0x50: width, 0x52: height
    struct.pack_into("<H", virtual, TEX_OFFSET + 0x50, width)
    struct.pack_into("<H", virtual, TEX_OFFSET + 0x52, height)
    # 0x56: stride
    struct.pack_into("<H", virtual, TEX_OFFSET + 0x56, width)
    # 0x58: format code
    struct.pack_into("<I", virtual, TEX_OFFSET + 0x58, format_code)
    # 0x5D: mip levels
    virtual[TEX_OFFSET + 0x5D] = 1
    # 0x70: data pointer (into physical segment at offset 0)
    data_ptr = 0x60000000
    struct.pack_into("<Q", virtual, TEX_OFFSET + 0x70, data_ptr)

    # Name string
    virtual[NAME_OFFSET:NAME_OFFSET + len(name_bytes)] = name_bytes

    # --- Physical segment (pixel data) ---
    physical = bytes(raw_data)

    # --- RSC7 container ---
    virtual_flags = _encode_rsc7_flags(len(virtual))
    physical_flags = _encode_rsc7_flags(len(physical))

    # Pad segments to match the sizes that get_size_from_flags() returns.
    # The parser uses flag-derived sizes to split the decompressed data.
    from src.rsc7 import get_size_from_flags
    virt_padded_size = get_size_from_flags(virtual_flags)
    phys_padded_size = get_size_from_flags(physical_flags)

    padded_virtual = bytes(virtual) + b"\x00" * (virt_padded_size - len(virtual))
    padded_physical = physical + b"\x00" * (phys_padded_size - len(physical))

    # Compress with raw deflate (no zlib header/trailer)
    combined = padded_virtual + padded_physical
    compressed = zlib.compress(combined, 6)[2:-4]

    header = struct.pack("<4I", 0x37435352, 13, virtual_flags, physical_flags)
    return header + compressed


def _encode_rsc7_flags(size: int) -> int:
    """Encode a segment size into RSC7 flags.

    RSC7 flags use base_size = 0x200 << ss, where ss = bits 0-3.
    Pages are encoded in bits 4-27 as a weighted sum:
      s0 (bit27)=1x, s1 (bit26)=2x, s2 (bit25)=4x, s3 (bit24)=8x,
      s4 (bits17-23)=16x, ...
    Total size = base_size * (s0+s1+s2+s3+s4+...).
    """
    if size == 0:
        return 0

    # Use ss=0 → base_size=512. Compute pages needed.
    base_size = 0x200  # 512
    pages = (size + base_size - 1) // base_size

    # Encode pages into s0-s3 (bits 27-24) for pages <= 15
    # and s4 (bits 17-23) for the 16x multiplier
    flags = 0
    remainder = pages

    # s4: bits 17-23, value * 16 pages (0-127)
    s4_val = min(remainder // 16, 127)
    remainder -= s4_val * 16
    flags |= (s4_val << 17)

    # s3: bit 24, 8 pages
    if remainder >= 8:
        flags |= (1 << 24)
        remainder -= 8
    # s2: bit 25, 4 pages
    if remainder >= 4:
        flags |= (1 << 25)
        remainder -= 4
    # s1: bit 26, 2 pages
    if remainder >= 2:
        flags |= (1 << 26)
        remainder -= 2
    # s0: bit 27, 1 page
    if remainder >= 1:
        flags |= (1 << 27)

    return flags


def _write_ytd_file(
    directory: str,
    filename: str,
    rgb: tuple[int, int, int] = (172, 135, 121),
    width: int = 64,
    height: int = 64,
) -> str:
    """Write a synthetic .ytd file with a solid-color DXT1 texture."""
    tex_name = filename.replace(".ytd", "")
    raw_data = _make_dxt1_data(width, height, rgb)
    ytd_bytes = _build_ytd_bytes(tex_name, width, height, raw_data)
    path = os.path.join(directory, filename)
    with open(path, "wb") as f:
        f.write(ytd_bytes)
    return path


# ---------------------------------------------------------------------------
# Tests for _texture_hash_and_opacity
# ---------------------------------------------------------------------------

class TestTextureHashAndOpacity:
    """Test the low-level hash + opacity extraction."""

    def test_returns_hash_and_opacity_for_valid_ytd(self, tmp_path):
        path = _write_ytd_file(str(tmp_path), "test_diff_000_a_uni.ytd")
        result = _texture_hash_and_opacity(path)
        assert result is not None
        md5, opacity = result
        assert len(md5) == 32  # full MD5 hex
        assert 0.0 <= opacity <= 1.0

    def test_solid_color_is_fully_opaque(self, tmp_path):
        """DXT1 solid color = no alpha → 100% opaque."""
        path = _write_ytd_file(str(tmp_path), "test_diff_000_a_uni.ytd",
                               rgb=(172, 135, 121))
        result = _texture_hash_and_opacity(path)
        assert result is not None
        _, opacity = result
        assert opacity >= 0.95

    def test_identical_textures_produce_same_hash(self, tmp_path):
        """Two .ytd files with the same pixel data should have the same hash."""
        path_a = _write_ytd_file(str(tmp_path), "uppr_diff_000_a_whi.ytd",
                                 rgb=(172, 135, 121))
        path_b = _write_ytd_file(str(tmp_path), "uppr_diff_001_a_whi.ytd",
                                 rgb=(172, 135, 121))
        result_a = _texture_hash_and_opacity(path_a)
        result_b = _texture_hash_and_opacity(path_b)
        assert result_a is not None and result_b is not None
        assert result_a[0] == result_b[0]  # same hash

    def test_different_textures_produce_different_hash(self, tmp_path):
        """Different pixel data → different hash."""
        path_a = _write_ytd_file(str(tmp_path), "uppr_diff_000_a_whi.ytd",
                                 rgb=(172, 135, 121))
        path_b = _write_ytd_file(str(tmp_path), "uppr_diff_001_a_uni.ytd",
                                 rgb=(30, 30, 30))
        result_a = _texture_hash_and_opacity(path_a)
        result_b = _texture_hash_and_opacity(path_b)
        assert result_a is not None and result_b is not None
        assert result_a[0] != result_b[0]

    def test_returns_none_for_nonexistent_file(self):
        result = _texture_hash_and_opacity("/nonexistent/path.ytd")
        assert result is None

    def test_returns_none_for_corrupt_file(self, tmp_path):
        path = os.path.join(str(tmp_path), "corrupt.ytd")
        with open(path, "wb") as f:
            f.write(b"not a valid ytd file")
        result = _texture_hash_and_opacity(path)
        assert result is None


# ---------------------------------------------------------------------------
# Tests for filter_body_skin_items
# ---------------------------------------------------------------------------

class TestFilterBodySkinItems:
    """Test the main filtering function."""

    def _make_work_item(self, tmp_path, dlc="base_game", gender="female",
                        category="uppr", drawable_id=0,
                        rgb=(172, 135, 121)) -> dict:
        """Create a work item with a real .ytd file on disk."""
        filename = f"{category}_diff_{drawable_id:03d}_a_whi.ytd"
        ytd_path = _write_ytd_file(str(tmp_path), filename, rgb=rgb)
        return {
            "ytd_path": ytd_path,
            "dlc_name": dlc,
            "gender": gender,
            "category": category,
            "drawable_id": drawable_id,
            "source_file": filename,
            "output_webp": f"textures/{dlc}/{gender}/{category}/{drawable_id:03d}.webp",
            "texture_rel": f"{dlc}/{gender}/{category}/{drawable_id:03d}.webp",
            "catalog_key": f"{dlc}_{gender}_{category}_{drawable_id:03d}",
        }

    def test_filters_duplicate_opaque_uppr_textures(self, tmp_path):
        """3+ identical opaque uppr textures → all skipped."""
        items = [
            self._make_work_item(tmp_path, category="uppr", drawable_id=i)
            for i in range(5)
        ]
        filtered, skipped = filter_body_skin_items(items)
        assert skipped == 5
        assert len(filtered) == 0

    def test_keeps_unique_uppr_textures(self, tmp_path):
        """Each uppr texture has a different color → all kept."""
        colors = [(172, 135, 121), (30, 30, 30), (200, 50, 50),
                  (50, 200, 50), (50, 50, 200)]
        items = [
            self._make_work_item(tmp_path, category="uppr", drawable_id=i,
                                 rgb=colors[i])
            for i in range(5)
        ]
        filtered, skipped = filter_body_skin_items(items)
        assert skipped == 0
        assert len(filtered) == 5

    def test_keeps_non_overlay_categories(self, tmp_path):
        """jbib, accs, etc. are never filtered regardless of duplicates."""
        items = [
            self._make_work_item(tmp_path, category="jbib", drawable_id=i)
            for i in range(5)
        ]
        filtered, skipped = filter_body_skin_items(items)
        assert skipped == 0
        assert len(filtered) == 5

    def test_mixed_categories_only_filters_overlay(self, tmp_path):
        """Only uppr/lowr items with duplicates are filtered; jbib is kept."""
        uppr_items = [
            self._make_work_item(tmp_path, category="uppr", drawable_id=i)
            for i in range(4)
        ]
        jbib_items = [
            self._make_work_item(tmp_path, category="jbib", drawable_id=i)
            for i in range(3)
        ]
        all_items = uppr_items + jbib_items
        filtered, skipped = filter_body_skin_items(all_items)
        assert skipped == 4  # all uppr items
        assert len(filtered) == 3  # only jbib items

    def test_below_threshold_not_filtered(self, tmp_path):
        """2 identical textures (below threshold of 3) → kept."""
        items = [
            self._make_work_item(tmp_path, category="uppr", drawable_id=i)
            for i in range(2)
        ]
        filtered, skipped = filter_body_skin_items(items)
        assert skipped == 0
        assert len(filtered) == 2

    def test_separate_groups_filtered_independently(self, tmp_path):
        """Duplicates in base_game don't count toward rhclothing."""
        base_items = [
            self._make_work_item(tmp_path, dlc="base_game", category="uppr",
                                 drawable_id=i)
            for i in range(4)
        ]
        # DLC items with a different color → unique
        dlc_items = [
            self._make_work_item(tmp_path, dlc="rhclothing", category="uppr",
                                 drawable_id=i, rgb=(80, 80, 80))
            for i in range(4)
        ]
        all_items = base_items + dlc_items
        filtered, skipped = filter_body_skin_items(all_items)
        # base_game: 4 identical → skip 4
        # rhclothing: 4 identical → skip 4
        assert skipped == 8
        assert len(filtered) == 0

    def test_mixed_unique_and_duplicate_in_group(self, tmp_path):
        """Group with 3 duplicates + 2 unique → keeps the 2 unique."""
        items = []
        # 3 identical (body skin)
        for i in range(3):
            items.append(
                self._make_work_item(tmp_path, category="uppr",
                                     drawable_id=i, rgb=(172, 135, 121))
            )
        # 2 unique (clothing)
        items.append(
            self._make_work_item(tmp_path, category="uppr",
                                 drawable_id=10, rgb=(30, 30, 30))
        )
        items.append(
            self._make_work_item(tmp_path, category="uppr",
                                 drawable_id=11, rgb=(200, 50, 50))
        )
        filtered, skipped = filter_body_skin_items(items)
        assert skipped == 3
        assert len(filtered) == 2
        kept_ids = sorted(item["drawable_id"] for item in filtered)
        assert kept_ids == [10, 11]

    def test_empty_input(self):
        """Empty list returns empty list with 0 skipped."""
        filtered, skipped = filter_body_skin_items([])
        assert filtered == []
        assert skipped == 0

    def test_lowr_category_also_filtered(self, tmp_path):
        """lowr duplicates are filtered just like uppr."""
        items = [
            self._make_work_item(tmp_path, category="lowr", drawable_id=i)
            for i in range(4)
        ]
        filtered, skipped = filter_body_skin_items(items)
        assert skipped == 4
        assert len(filtered) == 0

    def test_head_items_passed_through(self, tmp_path):
        """Head items with is_head=True are not filtered even if duplicated."""
        items = [
            self._make_work_item(tmp_path, category="head", drawable_id=i)
            for i in range(4)
        ]
        # head is not in BODY_OVERLAY_CATEGORIES
        filtered, skipped = filter_body_skin_items(items)
        assert skipped == 0
        assert len(filtered) == 4


# ---------------------------------------------------------------------------
# Integration test with real files (if available)
# ---------------------------------------------------------------------------

_REAL_BASE_GAME = os.path.join(
    os.path.dirname(__file__), "..", "base_game", "base", "mp_f_freemode_01"
)


@pytest.mark.skipif(
    not os.path.isdir(_REAL_BASE_GAME),
    reason="Real base_game files not available",
)
class TestWithRealFiles:
    """Integration tests using actual GTA V base_game .ytd files."""

    def test_base_game_uppr_all_filtered(self):
        """All 16 base_game female uppr textures should be filtered."""
        items = []
        for i in range(16):
            ytd_path = os.path.join(
                _REAL_BASE_GAME, f"uppr_diff_{i:03d}_a_whi.ytd"
            )
            if not os.path.isfile(ytd_path):
                pytest.skip(f"Missing file: uppr_diff_{i:03d}_a_whi.ytd")
            items.append({
                "ytd_path": ytd_path,
                "dlc_name": "base_game",
                "gender": "female",
                "category": "uppr",
                "drawable_id": i,
                "source_file": f"uppr_diff_{i:03d}_a_whi.ytd",
                "output_webp": f"textures/base_game/female/uppr/{i:03d}.webp",
                "texture_rel": f"base_game/female/uppr/{i:03d}.webp",
                "catalog_key": f"base_game_female_uppr_{i:03d}",
            })

        filtered, skipped = filter_body_skin_items(items)
        assert skipped == 16
        assert len(filtered) == 0

    def test_real_texture_hash_and_opacity(self):
        """Verify hash+opacity extraction works on real .ytd files."""
        ytd_path = os.path.join(_REAL_BASE_GAME, "uppr_diff_000_a_whi.ytd")
        if not os.path.isfile(ytd_path):
            pytest.skip("uppr_diff_000_a_whi.ytd not available")

        result = _texture_hash_and_opacity(ytd_path)
        assert result is not None
        md5, opacity = result
        assert len(md5) == 32
        # Base game body skin should be 100% opaque
        assert opacity >= 0.99


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
