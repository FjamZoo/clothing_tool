"""End-to-end test for tattoo texture extraction pipeline.

Tests the full pipeline: RSC7 parse -> YTD parse -> DDS build -> WebP output
on real tattoo .ytd files from stream/new_overlays/.
"""

import os
import tempfile

import pytest
from PIL import Image

from src.rsc7 import parse_rsc7
from src.ytd_parser import parse_texture_dictionary, select_diffuse_texture
from src.dds_builder import build_dds
from src.image_processor import process_texture, is_image_empty

# Pick a few representative tattoo files to test
TATTOO_DIR = os.path.join("stream", "new_overlays", "stream")
TATTOO_FILES = [
    os.path.join(TATTOO_DIR, "rushtattoo_000.ytd"),
    os.path.join(TATTOO_DIR, "rushtattoo_042.ytd"),
    os.path.join(TATTOO_DIR, "rushtattoo_084.ytd"),
]


@pytest.fixture(params=TATTOO_FILES, ids=lambda p: os.path.basename(p))
def tattoo_path(request):
    path = request.param
    if not os.path.isfile(path):
        pytest.skip(f"Test fixture not available: {path}")
    return path


@pytest.fixture
def tattoo_texture(tattoo_path):
    """Extract the diffuse texture from a tattoo .ytd file."""
    rsc = parse_rsc7(tattoo_path)
    textures = parse_texture_dictionary(rsc.virtual_data, rsc.physical_data)
    tex = select_diffuse_texture(textures)
    assert tex is not None, f"No diffuse texture in {tattoo_path}"
    return tex


class TestTattooExtraction:
    def test_rsc7_parses(self, tattoo_path):
        rsc = parse_rsc7(tattoo_path)
        assert rsc.version == 13
        assert len(rsc.virtual_data) >= 64

    def test_has_textures(self, tattoo_path):
        rsc = parse_rsc7(tattoo_path)
        textures = parse_texture_dictionary(rsc.virtual_data, rsc.physical_data)
        assert len(textures) >= 1

    def test_texture_has_valid_dimensions(self, tattoo_texture):
        assert tattoo_texture.width > 0
        assert tattoo_texture.height > 0
        assert tattoo_texture.width <= 4096
        assert tattoo_texture.height <= 4096

    def test_texture_has_known_format(self, tattoo_texture):
        known_formats = {"DXT1", "DXT3", "DXT5", "ATI1", "ATI2", "BC7",
                         "A8R8G8B8", "X8R8G8B8", "A8B8G8R8", "L8", "A8"}
        assert tattoo_texture.format_name in known_formats

    def test_texture_has_data(self, tattoo_texture):
        assert len(tattoo_texture.raw_data) > 0


class TestTattooRendering:
    def test_produces_webp(self, tattoo_texture):
        dds = build_dds(tattoo_texture)
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
            out_path = f.name
        try:
            w, h = process_texture(dds, out_path)
            assert os.path.isfile(out_path)
            assert os.path.getsize(out_path) > 100  # Not an empty file
        finally:
            os.unlink(out_path)

    def test_webp_is_512x512(self, tattoo_texture):
        dds = build_dds(tattoo_texture)
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
            out_path = f.name
        try:
            process_texture(dds, out_path)
            img = Image.open(out_path)
            assert img.size == (512, 512)
            img.close()
        finally:
            os.unlink(out_path)

    def test_webp_not_empty(self, tattoo_texture):
        dds = build_dds(tattoo_texture)
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
            out_path = f.name
        try:
            process_texture(dds, out_path)
            assert is_image_empty(out_path) is False
        finally:
            os.unlink(out_path)

    def test_webp_has_visible_pixels(self, tattoo_texture):
        dds = build_dds(tattoo_texture)
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
            out_path = f.name
        try:
            process_texture(dds, out_path)
            img = Image.open(out_path).convert("RGBA")
            alpha = img.getchannel("A")
            visible = sum(1 for p in alpha.tobytes() if p > 0)
            assert visible > 500, (
                f"Tattoo render has only {visible} visible pixels"
            )
        finally:
            os.unlink(out_path)
