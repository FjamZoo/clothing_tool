"""Tests for overlay_compositor — texture compositing and tinting."""

import numpy as np
from PIL import Image

from src.overlay_compositor import _tint_overlay


# ---------------------------------------------------------------------------
# Tinting
# ---------------------------------------------------------------------------

class TestTintOverlay:
    def test_preserves_alpha(self):
        """Alpha channel should remain unchanged after tinting."""
        arr = np.zeros((4, 4, 4), dtype=np.uint8)
        arr[:, :, 3] = 128  # Semi-transparent
        arr[:, :, 0] = 200  # Some RGB values
        arr[:, :, 1] = 200
        arr[:, :, 2] = 200
        overlay = Image.fromarray(arr, "RGBA")

        tinted = _tint_overlay(overlay, (60, 45, 30))

        result = np.array(tinted)
        np.testing.assert_array_equal(result[:, :, 3], 128)

    def test_black_stays_black(self):
        """Black pixels (luminance=0) should remain black regardless of tint."""
        arr = np.zeros((4, 4, 4), dtype=np.uint8)
        arr[:, :, 3] = 255  # Fully opaque
        overlay = Image.fromarray(arr, "RGBA")

        tinted = _tint_overlay(overlay, (255, 128, 64))

        result = np.array(tinted)
        assert result[:, :, 0].max() == 0
        assert result[:, :, 1].max() == 0
        assert result[:, :, 2].max() == 0

    def test_white_gets_tint_color(self):
        """White pixels (luminance=1.0) should get the full tint color."""
        arr = np.full((4, 4, 4), 255, dtype=np.uint8)
        overlay = Image.fromarray(arr, "RGBA")

        tinted = _tint_overlay(overlay, (60, 45, 30))

        result = np.array(tinted)
        assert result[0, 0, 0] == 60   # R
        assert result[0, 0, 1] == 45   # G
        assert result[0, 0, 2] == 30   # B
        assert result[0, 0, 3] == 255  # A

    def test_gray_modulates_tint(self):
        """50% gray should produce approximately half the tint color."""
        arr = np.full((4, 4, 4), 128, dtype=np.uint8)
        arr[:, :, 3] = 255
        overlay = Image.fromarray(arr, "RGBA")

        tinted = _tint_overlay(overlay, (200, 100, 50))

        result = np.array(tinted)
        # 128/255 ≈ 0.502, luminance formula for gray:
        # L = 128 * (0.299 + 0.587 + 0.114) / 255 ≈ 0.502
        # Expected R ≈ 200 * 0.502 ≈ 100
        assert abs(int(result[0, 0, 0]) - 100) < 5
        assert abs(int(result[0, 0, 1]) - 50) < 5
        assert abs(int(result[0, 0, 2]) - 25) < 5

    def test_output_is_rgba(self):
        """Output should be RGBA mode."""
        arr = np.full((4, 4, 4), 128, dtype=np.uint8)
        overlay = Image.fromarray(arr, "RGBA")

        tinted = _tint_overlay(overlay, (60, 45, 30))
        assert tinted.mode == "RGBA"

    def test_transparent_overlay_stays_transparent(self):
        """Fully transparent pixels should stay transparent."""
        arr = np.zeros((4, 4, 4), dtype=np.uint8)
        arr[:, :, 0:3] = 200  # Some color
        arr[:, :, 3] = 0      # Fully transparent
        overlay = Image.fromarray(arr, "RGBA")

        tinted = _tint_overlay(overlay, (60, 45, 30))

        result = np.array(tinted)
        assert result[:, :, 3].max() == 0
