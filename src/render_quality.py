"""Render quality validation.

Detects flat-texture fallbacks that slipped through as 3D renders.
A proper 3D clothing render fills a reasonable portion of the 512x512
canvas with a roughly human-proportioned bounding box.  Flat texture
fallbacks are thin horizontal strips (e.g. 450x84).
"""

from __future__ import annotations

from PIL import Image

# A good 3D render's visible-content bounding box should have an aspect
# ratio no wider than this.  Flat texture strips typically hit 5+.
MAX_ASPECT_RATIO = 3.0

# Minimum percentage of the canvas covered by visible pixels.
# Flat strips cover ~14%; real renders cover 40%+.
MIN_AREA_PERCENT = 20.0

# Minimum bounding-box height as a fraction of canvas size.
# A 512px canvas with an 84px-tall strip = 16%.  Real renders are 50%+.
MIN_HEIGHT_FRACTION = 0.25

# Categories where the raw UV texture fallback is always worse than any
# 3D render (body meshes whose UV maps are meaningless as previews).
BODY_MESH_CATEGORIES = frozenset({"uppr", "lowr", "feet", "head"})


def is_flat_texture_fallback(image_path: str, category: str = "") -> bool:
    """Return True if the image looks like a flat texture strip, not a 3D render.

    Checks the bounding box of non-transparent pixels.  Flat diffuse
    textures produce thin horizontal strips when centered on a square
    canvas, while proper 3D renders fill a reasonable area.

    Body mesh categories (uppr, lowr, feet, head) always return False
    because their raw UV texture fallback is a meaningless skin map
    that is always worse than any 3D render.

    Prop categories (p_head, p_eyes, etc.) always return False because
    they are standalone 3D objects (hats, glasses, watches) whose
    renders are inherently small/thin and should never be rejected.
    """
    if category in BODY_MESH_CATEGORIES:
        return False

    # Props are standalone accessories — their 3D renders are always
    # preferable to flat textures, even if the bounding box is thin
    # (e.g. glasses are legitimately wide and short).
    if category.startswith("p_"):
        return False

    img = Image.open(image_path).convert("RGBA")
    canvas_size = img.height  # should be 512

    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        return True  # completely empty

    x0, y0, x1, y1 = bbox
    w = x1 - x0
    h = y1 - y0

    if h == 0 or w == 0:
        return True

    aspect = w / h
    area_pct = (w * h) / (canvas_size * canvas_size) * 100
    height_frac = h / canvas_size

    # Flat texture strips: very wide aspect ratio + low height
    if aspect > MAX_ASPECT_RATIO:
        return True

    # Very little of the canvas is used
    if area_pct < MIN_AREA_PERCENT and height_frac < MIN_HEIGHT_FRACTION:
        return True

    return False
