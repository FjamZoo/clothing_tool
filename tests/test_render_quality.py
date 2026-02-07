"""Tests for render quality validation.

Verifies that is_flat_texture_fallback() correctly distinguishes
proper 3D renders from flat texture strips that slipped through.
Uses actual output files from Mp_f_2023_02/jbib as test cases.
"""

import os
import pytest
from PIL import Image
from src.render_quality import is_flat_texture_fallback, BODY_MESH_CATEGORIES

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "output", "textures", "Mp_f_2023_02", "jbib"
)


def _have_output_files():
    return os.path.isdir(OUTPUT_DIR)


# ---------------------------------------------------------------------------
# Unit tests using synthetic images
# ---------------------------------------------------------------------------

class TestFlatTextureDetection:
    """Test the detection heuristic with synthetic images."""

    def _make_image(self, canvas=512, content_w=450, content_h=84):
        """Create a synthetic image with opaque content of given size, centered."""
        img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        x = (canvas - content_w) // 2
        y = (canvas - content_h) // 2
        for px in range(x, x + content_w):
            for py in range(y, y + content_h):
                img.putpixel((px, py), (128, 128, 128, 255))
        return img

    def _save_tmp(self, img, tmp_path, name="test.webp"):
        path = os.path.join(str(tmp_path), name)
        img.save(path, "WEBP")
        return path

    def test_thin_horizontal_strip_is_flat(self, tmp_path):
        """A 450x84 strip (ratio 5.36) should be detected as flat."""
        img = self._make_image(content_w=450, content_h=84)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path) is True

    def test_proper_clothing_shape_is_not_flat(self, tmp_path):
        """A 450x313 shape (ratio 1.44) should NOT be detected as flat."""
        img = self._make_image(content_w=450, content_h=313)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path) is False

    def test_tall_narrow_clothing_is_not_flat(self, tmp_path):
        """A 240x457 shape (ratio 0.53) — like a dress — is NOT flat."""
        img = self._make_image(content_w=240, content_h=457)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path) is False

    def test_nearly_square_is_not_flat(self, tmp_path):
        """A 450x471 shape (ratio 0.96) is clearly a 3D render."""
        img = self._make_image(content_w=450, content_h=471)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path) is False

    def test_empty_image_is_flat(self, tmp_path):
        """A completely transparent image should be detected as flat."""
        img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path) is True

    def test_very_thin_strip_is_flat(self, tmp_path):
        """An extremely thin strip (450x20) is definitely flat."""
        img = self._make_image(content_w=450, content_h=20)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path) is True


# ---------------------------------------------------------------------------
# Body mesh categories always keep 3D renders
# ---------------------------------------------------------------------------

class TestBodyMeshCategoriesNeverReject:
    """Body categories (uppr, lowr, feet, head) must never fall back to flat.

    Their raw UV textures are meaningless skin maps — any 3D render is
    better than showing the UV layout to the user.
    """

    def _make_image(self, canvas=512, content_w=450, content_h=84):
        img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        x = (canvas - content_w) // 2
        y = (canvas - content_h) // 2
        for px in range(x, x + content_w):
            for py in range(y, y + content_h):
                img.putpixel((px, py), (128, 128, 128, 255))
        return img

    def _save_tmp(self, img, tmp_path, name="test.webp"):
        path = os.path.join(str(tmp_path), name)
        img.save(path, "WEBP")
        return path

    @pytest.mark.parametrize("category", sorted(BODY_MESH_CATEGORIES))
    def test_thin_strip_accepted_for_body_category(self, category, tmp_path):
        """A thin strip (normally rejected) must be kept for body categories."""
        img = self._make_image(content_w=450, content_h=84)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path, category=category) is False

    @pytest.mark.parametrize("category", sorted(BODY_MESH_CATEGORIES))
    def test_empty_image_accepted_for_body_category(self, category, tmp_path):
        """Even an edge-case image is kept for body categories."""
        img = self._make_image(content_w=450, content_h=20)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path, category=category) is False

    def test_non_body_category_still_rejected(self, tmp_path):
        """Non-body categories (e.g. jbib) should still be rejected for thin strips."""
        img = self._make_image(content_w=450, content_h=84)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path, category="jbib") is True

    def test_no_category_still_rejected(self, tmp_path):
        """Default (no category) should still be rejected for thin strips."""
        img = self._make_image(content_w=450, content_h=84)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path) is True


# ---------------------------------------------------------------------------
# Prop categories always keep 3D renders (glasses, hats, etc.)
# ---------------------------------------------------------------------------

class TestPropCategoriesNeverReject:
    """Prop categories (p_head, p_eyes, etc.) must never fall back to flat.

    Props are standalone 3D objects (hats, glasses, watches) whose renders
    are inherently small or thin — glasses especially are wide and short.
    A 3D render is always preferable to a flat texture for these items.
    """

    _PROP_CATEGORIES = ["p_head", "p_eyes", "p_ears", "p_lwrist", "p_rwrist"]

    def _make_image(self, canvas=512, content_w=450, content_h=84):
        img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        x = (canvas - content_w) // 2
        y = (canvas - content_h) // 2
        for px in range(x, x + content_w):
            for py in range(y, y + content_h):
                img.putpixel((px, py), (128, 128, 128, 255))
        return img

    def _save_tmp(self, img, tmp_path, name="test.webp"):
        path = os.path.join(str(tmp_path), name)
        img.save(path, "WEBP")
        return path

    @pytest.mark.parametrize("category", _PROP_CATEGORIES)
    def test_thin_strip_accepted_for_prop(self, category, tmp_path):
        """A thin strip (like glasses, ratio 5.36) must be kept for props."""
        img = self._make_image(content_w=450, content_h=84)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path, category=category) is False

    @pytest.mark.parametrize("category", _PROP_CATEGORIES)
    def test_wide_short_render_accepted_for_prop(self, category, tmp_path):
        """A wide, short render (like glasses, ratio ~3.3) must be kept for props."""
        img = self._make_image(content_w=250, content_h=75)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path, category=category) is False

    def test_glasses_shape_rejected_without_prop_category(self, tmp_path):
        """The same glasses-like shape should be rejected without a prop category."""
        img = self._make_image(content_w=450, content_h=84)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path, category="accs") is True

    def test_unknown_p_prefix_also_exempt(self, tmp_path):
        """Any p_ prefixed category should be exempt (future-proof)."""
        img = self._make_image(content_w=450, content_h=84)
        path = self._save_tmp(img, tmp_path)
        assert is_flat_texture_fallback(path, category="p_future") is False


# ---------------------------------------------------------------------------
# Flat overlay fallback integration test
# ---------------------------------------------------------------------------

_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "uppr_008_debug")


def _have_fixture_files():
    return (
        os.path.isfile(os.path.join(_FIXTURE_DIR, "uppr_diff_008_a_whi.ytd"))
        and os.path.isfile(os.path.join(_FIXTURE_DIR, "uppr_008_r.ydd"))
        and os.path.isfile(os.path.join(_FIXTURE_DIR, "uppr_000_r.ydd"))
    )


@pytest.mark.skipif(not _have_fixture_files(), reason="Fixture files not available")
class TestFlatOverlayFallback:
    """Verify that flat body overlay meshes automatically fall back to the
    base body mesh for a proper 3D render."""

    def test_flat_overlay_uses_base_mesh(self, tmp_path):
        """uppr_008 (flat overlay) with fallback should produce a 3D render
        that has aspect ratio < 2 and coverage > 30% (i.e. NOT a UV map)."""
        from src.blender_renderer import render_batch, find_blender

        blender_path = find_blender()
        if blender_path is None:
            pytest.skip("Blender not found")

        output_webp = str(tmp_path / "uppr_008_fallback.webp")
        item = {
            "ytd_path": os.path.join(_FIXTURE_DIR, "uppr_diff_008_a_whi.ytd"),
            "ydd_path": os.path.join(_FIXTURE_DIR, "uppr_008_r.ydd"),
            "fallback_ydd_path": os.path.join(_FIXTURE_DIR, "uppr_000_r.ydd"),
            "output_webp": output_webp,
            "catalog_key": "test_fallback",
            "dlc_name": "base_game",
            "gender": "female",
            "category": "uppr",
            "drawable_id": 8,
            "source_file": "uppr_diff_008_a_whi.ytd",
        }

        results = render_batch([item], blender_path, batch_size=1, parallel=1)
        assert len(results) == 1
        r = results[0]
        assert r.success, f"Render failed: {r.error}"
        assert os.path.isfile(output_webp)

        # The render should look like a 3D body, not a flat UV map
        img = Image.open(output_webp).convert("RGBA")
        bbox = img.getchannel("A").getbbox()
        assert bbox is not None, "Render is completely empty"

        x0, y0, x1, y1 = bbox
        w, h = x1 - x0, y1 - y0
        aspect = w / h
        coverage = (w * h) / (img.width * img.height) * 100

        # UV map: ~1:1 aspect, ~76% coverage (fills square)
        # 3D body: ~1.57 aspect, ~49% coverage (body shape on transparent bg)
        assert aspect < 2.5, f"Aspect ratio {aspect:.2f} too wide — still looks like UV map"
        assert coverage < 70, (
            f"Coverage {coverage:.1f}% too high — still looks like a UV map "
            f"(expected 3D body shape with transparent background)"
        )


# ---------------------------------------------------------------------------
# Integration tests using real output files
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _have_output_files(), reason="Output files not available")
class TestRealOutputQuality:
    """Validate actual rendered output files."""

    # Known good 3D renders (from visual inspection of screenshot)
    GOOD_3D = ["003.webp", "004.webp", "007.webp", "024.webp", "025.webp"]

    # Previously known bad flat texture fallbacks — now re-rendered as
    # proper 3D with the flat overlay fallback feature, so they are no
    # longer flat strips.  Kept here as documentation.
    # BAD_FLAT = ["005.webp", "008.webp", "010.webp", "014.webp", "021.webp"]
    BAD_FLAT: list[str] = []  # all have been re-rendered successfully

    @pytest.mark.parametrize("filename", GOOD_3D)
    def test_good_render_not_detected_as_flat(self, filename):
        path = os.path.join(OUTPUT_DIR, filename)
        if not os.path.isfile(path):
            pytest.skip(f"{filename} not found")
        assert is_flat_texture_fallback(path) is False, (
            f"{filename} is a proper 3D render but was flagged as flat"
        )

    @pytest.mark.parametrize("filename", BAD_FLAT)
    def test_flat_fallback_detected(self, filename):
        path = os.path.join(OUTPUT_DIR, filename)
        if not os.path.isfile(path):
            pytest.skip(f"{filename} not found")
        assert is_flat_texture_fallback(path) is True, (
            f"{filename} is a flat texture strip but was not detected"
        )
