"""Regression test for black-square rendering bug (issue: accs_008).

The texture mp_f_freemode_01_rhclothing^accs_diff_008_a_uni.ytd contains a
DXT5 texture named 'Swatch_1_Diffuse_1' (1024x2048) where ~87% of pixels
are fully transparent.  When rendered in 3D via Blender, the alpha channel
caused the entire garment to be invisible, producing a fully transparent
(black-square) output.

This test validates that:
  1. The flat pipeline produces a visible image for this texture.
  2. The is_image_empty() helper correctly detects blank images.
  3. The texture extraction and DDS building work correctly.
"""

import os
import tempfile

import pytest
from PIL import Image

from src.rsc7 import parse_rsc7
from src.ytd_parser import parse_texture_dictionary, select_diffuse_texture
from src.dds_builder import build_dds
from src.image_processor import process_texture, is_image_empty

# Path to the problematic .ytd file
YTD_PATH = os.path.join(
    "stream", "rhclothing", "stream", "[female]", "accs",
    "mp_f_freemode_01_rhclothing^accs_diff_008_a_uni.ytd",
)


@pytest.fixture
def texture_008():
    """Parse and extract the diffuse texture from accs_008."""
    rsc = parse_rsc7(YTD_PATH)
    textures = parse_texture_dictionary(rsc.virtual_data, rsc.physical_data)
    tex = select_diffuse_texture(textures)
    assert tex is not None, "No diffuse texture found in accs_008"
    return tex


class TestAccs008Extraction:
    """Verify texture extraction from the problematic file."""

    def test_file_exists(self):
        assert os.path.isfile(YTD_PATH), f"Test fixture missing: {YTD_PATH}"

    def test_rsc7_parses(self):
        rsc = parse_rsc7(YTD_PATH)
        assert len(rsc.virtual_data) > 64
        assert len(rsc.physical_data) > 0

    def test_texture_has_data(self, texture_008):
        assert len(texture_008.raw_data) > 0, "Raw data is empty"
        # Verify not all zeros
        non_zero = sum(1 for b in texture_008.raw_data[:4096] if b != 0)
        assert non_zero > 0, "Raw data is all zeros"

    def test_texture_metadata(self, texture_008):
        assert texture_008.width == 1024
        assert texture_008.height == 2048
        assert texture_008.format_name == "DXT5"

    def test_dds_builds(self, texture_008):
        dds = build_dds(texture_008)
        assert dds[:4] == b"DDS ", "DDS magic bytes missing"
        assert len(dds) > 128, "DDS file too small"


class TestAccs008FlatRender:
    """Verify the flat pipeline produces a visible image."""

    def test_flat_render_not_empty(self, texture_008):
        dds = build_dds(texture_008)
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
            out_path = f.name
        try:
            w, h = process_texture(dds, out_path)
            assert w == 1024
            assert h == 2048

            img = Image.open(out_path).convert("RGBA")
            assert img.size == (512, 512)

            # Count visible pixels (alpha > 0)
            alpha = img.getchannel("A")
            visible = sum(1 for p in alpha.tobytes() if p > 0)
            assert visible > 1000, (
                f"Flat render has only {visible} visible pixels — "
                f"expected at least 1000 for a valid clothing texture"
            )
        finally:
            os.unlink(out_path)

    def test_flat_render_has_color(self, texture_008):
        """Verify the rendered image has actual color variation, not just noise."""
        dds = build_dds(texture_008)
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
            out_path = f.name
        try:
            process_texture(dds, out_path)
            img = Image.open(out_path).convert("RGBA")

            # Check that RGB channels have meaningful range where alpha > 0
            pixels = list(zip(*[iter(img.tobytes())] * 4))
            visible_rgb = [(r, g, b) for r, g, b, a in pixels if a > 0]
            assert len(visible_rgb) > 0, "No visible pixels at all"

            # Check color range
            r_vals = [p[0] for p in visible_rgb]
            g_vals = [p[1] for p in visible_rgb]
            b_vals = [p[2] for p in visible_rgb]
            max_range = max(max(r_vals) - min(r_vals),
                           max(g_vals) - min(g_vals),
                           max(b_vals) - min(b_vals))
            assert max_range > 10, (
                f"Color range is only {max_range} — image may be solid black/white"
            )
        finally:
            os.unlink(out_path)


class TestIsImageEmpty:
    """Test the is_image_empty() safety-net function."""

    def test_empty_image_detected(self):
        """A fully transparent image should be detected as empty."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            out_path = f.name
        try:
            img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
            img.save(out_path)
            assert is_image_empty(out_path) is True
        finally:
            os.unlink(out_path)

    def test_black_opaque_not_empty(self):
        """A black but opaque image should NOT be detected as empty."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            out_path = f.name
        try:
            img = Image.new("RGBA", (512, 512), (0, 0, 0, 255))
            img.save(out_path)
            assert is_image_empty(out_path) is False
        finally:
            os.unlink(out_path)

    def test_real_texture_not_empty(self, texture_008):
        """The flat render of accs_008 should NOT be detected as empty."""
        dds = build_dds(texture_008)
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
            out_path = f.name
        try:
            process_texture(dds, out_path)
            assert is_image_empty(out_path) is False
        finally:
            os.unlink(out_path)

    def test_sparse_image_not_empty(self):
        """An image with few but some visible pixels should not be empty."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            out_path = f.name
        try:
            img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
            # Draw 200 visible pixels
            for i in range(200):
                img.putpixel((i, 0), (255, 0, 0, 255))
            img.save(out_path)
            assert is_image_empty(out_path) is False
        finally:
            os.unlink(out_path)
