"""
Image Processor — DDS to WebP Conversion

Decodes DDS textures at full resolution, then downscales to 512x512 .webp
preview images with LANCZOS resampling.

Primary decoder: Pillow (supports DXT1, DXT5, BC7 with Pillow >= 10.2.0).
Fallback decoder: pydds (if installed) for any formats Pillow cannot handle.
"""

from __future__ import annotations

import logging
import os
from io import BytesIO

from PIL import Image

logger = logging.getLogger(__name__)

# Output canvas dimensions
CANVAS_SIZE = 512

# WebP quality setting (0-100, higher = better quality / larger file)
WEBP_QUALITY = 100

# WebP compression method (0-6, higher = slower but better compression)
# method=4 is ~3-5x faster than method=6 with negligible quality difference
WEBP_METHOD = 4

# Placeholder textures: GTA V uses small checkerboard textures (≤128px)
# as invisible placeholders. DXT1 compression artifacts can push the
# unique color count up to ~30, but real textures at ≤128px have 474+
# colors. Threshold of 50 catches all placeholders with a wide margin.
_PLACEHOLDER_MAX_SIZE = 128
_PLACEHOLDER_MAX_COLORS = 50


def _is_placeholder(img: Image.Image) -> bool:
    """Detect GTA V checkerboard placeholder textures."""
    if img.width > _PLACEHOLDER_MAX_SIZE or img.height > _PLACEHOLDER_MAX_SIZE:
        return False
    colors = img.getcolors(maxcolors=_PLACEHOLDER_MAX_COLORS + 1)
    return colors is not None and len(colors) <= _PLACEHOLDER_MAX_COLORS


def process_texture(
    dds_bytes: bytes,
    output_path: str,
    canvas_size: int = 0,
    webp_quality: int = 0,
    webp_method: int = 0,
) -> tuple[int, int]:
    """Convert DDS bytes to a centered .webp file.

    Decodes the full-resolution texture, then downscales to canvas_size with
    high-quality LANCZOS resampling.

    Placeholder textures (small checkerboards) are detected and output as
    fully transparent images.

    Args:
        dds_bytes:    Raw DDS file bytes (including the DDS header).
        output_path:  Destination path for the .webp file.
        canvas_size:  Output image size in pixels (default: module CANVAS_SIZE).
        webp_quality: WebP quality 1-100 (default: module WEBP_QUALITY).
        webp_method:  WebP method 0-6 (default: module WEBP_METHOD).

    Returns:
        (original_width, original_height) tuple for catalog metadata.

    Raises:
        Exception: If neither Pillow nor pydds can decode the DDS data.
    """
    cs = canvas_size or CANVAS_SIZE
    wq = webp_quality or WEBP_QUALITY
    wm = webp_method or WEBP_METHOD

    img = _decode_dds(dds_bytes)
    img = img.convert("RGBA")

    original_size = (img.width, img.height)

    if _is_placeholder(img):
        logger.debug("Placeholder texture detected (%dx%d), outputting transparent",
                      img.width, img.height)
        canvas = Image.new("RGBA", (cs, cs), (0, 0, 0, 0))
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        canvas.save(output_path, "WEBP", quality=wq, method=wm)
        return original_size

    logger.debug(
        "Processing texture: %dx%d -> %dx%d canvas",
        img.width, img.height, cs, cs,
    )

    # Fast path: square textures (vast majority of GTA V textures) —
    # resize directly to canvas size, no intermediate canvas needed
    if img.width == img.height:
        if img.width != cs:
            img = img.resize((cs, cs), Image.LANCZOS)
        canvas = img
    else:
        # Non-square: resize preserving aspect ratio, center on canvas
        img.thumbnail((cs, cs), Image.LANCZOS)
        canvas = Image.new("RGBA", (cs, cs), (0, 0, 0, 0))
        offset = ((cs - img.width) // 2, (cs - img.height) // 2)
        canvas.paste(img, offset)

    # Ensure output directory exists (handle empty dirname for bare filenames)
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    canvas.save(output_path, "WEBP", quality=wq, method=wm)

    return original_size


def convert_rendered_png(
    png_path: str,
    output_path: str,
    canvas_size: int = 0,
    webp_quality: int = 0,
    webp_method: int = 0,
) -> None:
    """Convert a Blender-rendered image to a WebP at canvas_size.

    The render is produced at a higher resolution (e.g. 1024x1024) for
    quality, then downscaled here with Lanczos resampling (supersampling).

    Args:
        png_path:     Path to the source image file (from Blender).
        output_path:  Destination path for the .webp file.
        canvas_size:  Output image size in pixels (default: module CANVAS_SIZE).
        webp_quality: WebP quality 1-100 (default: module WEBP_QUALITY).
        webp_method:  WebP method 0-6 (default: module WEBP_METHOD).
    """
    cs = canvas_size or CANVAS_SIZE
    wq = webp_quality or WEBP_QUALITY
    wm = webp_method or WEBP_METHOD

    img = Image.open(png_path)
    img = img.convert("RGBA")

    if img.width != cs or img.height != cs:
        img = img.resize((cs, cs), Image.LANCZOS)

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    img.save(output_path, "WEBP", quality=wq, method=wm)

    logger.info("Converted PNG->WebP: %s (%d bytes)",
                output_path, os.path.getsize(output_path))


def is_image_empty(image_path: str, threshold: int = 100) -> bool:
    """Check if a rendered image is effectively empty (all transparent/black).

    Args:
        image_path: Path to the image file.
        threshold: Minimum number of non-transparent pixels to consider
                   the image non-empty.

    Returns:
        True if the image has fewer than *threshold* visible pixels.
    """
    try:
        import numpy as np
        img = Image.open(image_path).convert("RGBA")
        alpha = np.array(img.getchannel("A"))
        return int(np.count_nonzero(alpha)) < threshold
    except ImportError:
        # Fallback if numpy not available
        try:
            img = Image.open(image_path).convert("RGBA")
            alpha = img.getchannel("A")
            visible = sum(1 for p in alpha.tobytes() if p > 0)
            return visible < threshold
        except Exception:
            return True
    except Exception:
        return True


def _decode_dds(dds_bytes: bytes) -> Image.Image:
    """Attempt to decode DDS bytes, first with Pillow, then pydds fallback.

    Args:
        dds_bytes: Raw DDS file bytes.

    Returns:
        A PIL Image.

    Raises:
        Exception: If decoding fails with all available decoders.
    """
    # Primary: Pillow's built-in DDS support
    saved_err: Exception | None = None
    try:
        return Image.open(BytesIO(dds_bytes))
    except Exception as pillow_err:
        logger.debug("Pillow DDS decode failed: %s", pillow_err)
        saved_err = pillow_err

    # Fallback: pydds library
    try:
        from dds import decode_dds  # type: ignore[import-untyped]

        logger.debug("Falling back to pydds for DDS decoding")
        return decode_dds(dds_bytes)
    except ImportError:
        logger.error(
            "Pillow failed to decode DDS and pydds is not installed. "
            "Install pydds for broader format support: pip install pydds"
        )
        # Re-raise the original Pillow error since pydds isn't available
        raise saved_err  # type: ignore[misc]
    except Exception as pydds_err:
        logger.error("pydds decode also failed: %s", pydds_err)
        raise
