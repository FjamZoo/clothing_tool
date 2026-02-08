"""
Overlay Compositor

Composites a face overlay texture onto a base head texture, producing
a single PNG that Blender can load as the head's diffuse map.

Steps:
  1. Extract diffuse from overlay .ytd → decode to RGBA
  2. Extract diffuse from base head .ytd → decode to RGBA
  3. Tint overlay RGB using luminance modulation (optional)
  4. Alpha-composite overlay onto base
  5. Save as PNG
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from src.dds_builder import build_dds
from src.rsc7 import parse_rsc7
from src.ytd_parser import parse_texture_dictionary, select_diffuse_texture

logger = logging.getLogger(__name__)

# Default tint: dark brown for beards/eyebrows
DEFAULT_TINT = (60, 45, 30)


def _extract_diffuse_image(ytd_path: Path) -> Image.Image:
    """Parse .ytd → select diffuse → build DDS → Pillow decode → RGBA."""
    rsc = parse_rsc7(ytd_path)
    textures = parse_texture_dictionary(rsc.virtual_data, rsc.physical_data)
    diffuse = select_diffuse_texture(textures)
    if diffuse is None:
        raise ValueError(f"No diffuse texture found in {ytd_path.name}")

    dds_bytes = build_dds(diffuse)
    img = Image.open(BytesIO(dds_bytes))
    return img.convert("RGBA")


def _tint_overlay(
    overlay: Image.Image,
    color: tuple[int, int, int],
) -> Image.Image:
    """Apply tint color to overlay using luminance modulation.

    The overlay texture is typically a grayscale/greenish mask where:
    - Alpha = shape of the overlay (beard, eyebrow, etc.)
    - RGB = luminance/tint mask

    We replace RGB with tint_color modulated by the original luminance,
    keeping the alpha channel intact.
    """
    arr = np.array(overlay, dtype=np.float32)

    # Compute luminance from RGB channels
    luminance = (
        arr[:, :, 0] * 0.299 +
        arr[:, :, 1] * 0.587 +
        arr[:, :, 2] * 0.114
    ) / 255.0

    # Apply tint
    arr[:, :, 0] = color[0] * luminance
    arr[:, :, 1] = color[1] * luminance
    arr[:, :, 2] = color[2] * luminance
    # Alpha stays unchanged (arr[:, :, 3])

    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA")


def composite_overlay(
    overlay_ytd_path: Path,
    base_head_ytd_path: Path,
    output_png_path: Path,
    tint_color: tuple[int, int, int] | None = DEFAULT_TINT,
) -> None:
    """Extract overlay + base textures, tint overlay, composite, save as PNG.

    Args:
        overlay_ytd_path: Path to the face overlay .ytd file.
        base_head_ytd_path: Path to the base head diffuse .ytd file.
        output_png_path: Where to save the composited PNG.
        tint_color: RGB tint to apply to overlay. None to skip tinting.
    """
    # Extract both textures
    overlay_img = _extract_diffuse_image(overlay_ytd_path)
    base_img = _extract_diffuse_image(base_head_ytd_path)

    # Resize overlay to match base if dimensions differ
    if overlay_img.size != base_img.size:
        overlay_img = overlay_img.resize(base_img.size, Image.LANCZOS)

    # Tint overlay
    if tint_color is not None:
        overlay_img = _tint_overlay(overlay_img, tint_color)

    # Alpha-composite overlay onto base
    composited = Image.alpha_composite(base_img, overlay_img)

    # Save as PNG
    output_png_path.parent.mkdir(parents=True, exist_ok=True)
    composited.save(str(output_png_path), "PNG")

    logger.debug(
        "Composited %s onto %s → %s",
        overlay_ytd_path.name, base_head_ytd_path.name, output_png_path.name,
    )
