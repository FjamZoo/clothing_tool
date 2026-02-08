# Face Overlay Portrait Rendering

**Date**: 2026-02-08
**Status**: Planned
**Goal**: Render face portraits for eyebrows, facial hair (beards), and chest hair overlays

## Overview

Face overlays (eyebrows, beards, chest hair) are GTA V head overlay textures stored as `mp_fm_faov_{type}_{index}.ytd` files. These are alpha-blended UV textures that the game composites onto the freemode head mesh at runtime via `SetPedHeadOverlay`.

We need to generate portrait previews by compositing these overlay textures onto the base head model in Blender and rendering close-up face shots.

## Available Assets

### Overlay Files (cleaned, in `overlays/`)
- `mp_fm_faov_beard_{000-025}.ytd` — 26 facial hair variants (+ `_n`, `_s` maps)
- `mp_fm_faov_eyebrowf_{000-016}.ytd` — 17 female eyebrow variants (+ `_n`, `_s`)
- `mp_fm_faov_eyebrowm_{000-016}.ytd` — 17 male eyebrow variants (no `_n`/`_s`)
- Total: **60 diffuse overlays** to render

### Base Head Assets (in `base_game/base/`)
- **Male head mesh**: `mp_m_freemode_01/head_000_r.ydd`
- **Female head mesh**: `mp_f_freemode_01/head_000_r.ydd`
- **Male head texture**: `mp_m_freemode_01/head_diff_000_a_whi.ytd` (white/neutral skin)
- **Female head texture**: `mp_f_freemode_01/head_diff_000_a_whi.ytd`
- **Skeleton**: `mp_m_freemode_01.yft` / `mp_f_freemode_01.yft` (if needed for import)

### Key Facts
- Overlay textures are 512x512 DXT5 with alpha channel (alpha = overlay shape)
- Beards are shared (unisex) — use male head for preview
- Eyebrows are gendered: `eyebrowf` → female head, `eyebrowm` → male head
- Overlay textures share the same UV space as the head mesh
- The game tints beards/eyebrows via `SetPedHeadOverlayColor` — raw textures may be grayscale/greenish and need tinting to dark brown/black for preview

## Architecture

### Approach: Pre-Composite + Existing 3D Pipeline

Rather than adding shader node manipulation in Blender (complex, fragile), we:

1. **Pre-composite** the overlay onto the base head texture in Python (PIL)
2. **Save** as a single DDS file
3. **Import** the head YDD into Blender with this composited texture
4. **Render** a portrait using the existing `render_item()` with a portrait camera mode

This reuses ~90% of the existing Blender pipeline.

### Pre-Compositing Logic (Python/PIL)

```
base_head_texture (512x512 RGBA)  ← from head_diff_000_a_whi.ytd
overlay_texture   (512x512 RGBA)  ← from mp_fm_faov_beard_000.ytd

# Tint the overlay to dark brown (beards/eyebrows use tint mask)
tinted_overlay = apply_tint(overlay_texture, color=(80, 60, 40))

# Composite: paste tinted overlay on top of base head
composited = Image.alpha_composite(base_head_texture, tinted_overlay)

# Save as DDS for Blender import
save_as_dds(composited, temp_path)
```

The overlay alpha channel controls where the beard/eyebrow appears. The RGB channels may contain a grayscale mask that the game uses for tinting. We use the alpha as the blend factor and apply our own tint color to the RGB.

### Portrait Camera Mode

New camera framing for face close-ups:
- **Elevation**: 0-5 degrees (nearly straight-on, not looking down)
- **Framing**: Crop to upper 60% of head bbox (face area, not full head)
- **For beards**: Frame center-to-chin area
- **For eyebrows**: Frame forehead-to-nose area
- **Ortho scale**: Tighter than default (less padding)

## Implementation Plan

### Step 1: New Module — `src/overlay_parser.py`

Discovers and parses face overlay files from the `overlays/` directory.

```python
# Filename pattern
_FAOV_RE = re.compile(
    r'^mp_fm_faov_(?P<type>beard|eyebrowf|eyebrowm|chesthair)_(?P<index>\d{3})\.ytd$',
    re.IGNORECASE,
)

@dataclass
class OverlayInfo:
    file_path: str        # Absolute path to .ytd
    overlay_type: str     # "beard", "eyebrowf", "eyebrowm", "chesthair"
    index: int            # 0-25 for beards, 0-16 for eyebrows
    gender: str           # "male", "female", or "unisex"

def discover_overlays(overlays_dir: Path) -> list[OverlayInfo]:
    """Scan overlays directory for diffuse face overlay .ytd files.

    Skips _n (normal) and _s (specular) maps.
    Returns sorted list of OverlayInfo.
    """
```

**Gender mapping:**
- `beard` → `"male"` (render on male head; beards are male-only in practice)
- `eyebrowf` → `"female"`
- `eyebrowm` → `"male"`
- `chesthair` → `"male"` (if files ever appear)

**Files to create:** `src/overlay_parser.py` (~60 lines)

### Step 2: Pre-Compositing — `src/overlay_compositor.py`

Composites an overlay texture onto a base head texture.

```python
def composite_overlay(
    overlay_ytd_path: Path,
    base_head_ytd_path: Path,
    output_dds_path: Path,
    tint_color: tuple[int, int, int] = (60, 45, 30),  # Dark brown
) -> None:
    """Extract overlay + base textures, tint overlay, composite, save as DDS.

    Steps:
      1. Parse overlay .ytd → extract diffuse → decode to RGBA PIL Image
      2. Parse base head .ytd → extract diffuse → decode to RGBA PIL Image
      3. Resize overlay to match base if needed (both should be 512x512)
      4. Tint overlay: use alpha as mask, apply tint_color to RGB
      5. Alpha-composite overlay onto base
      6. Encode composited image back to DDS (DXT5)
      7. Save to output_dds_path
    """

def _extract_diffuse_image(ytd_path: Path) -> Image.Image:
    """Parse .ytd → select diffuse → build DDS → Pillow decode → RGBA."""

def _tint_overlay(overlay: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    """Apply tint color to overlay using its alpha as mask.

    The overlay texture is typically a grayscale mask where:
    - Alpha = shape of the beard/eyebrow
    - RGB = luminance/tint mask (often grayscale or greenish)

    We replace RGB with our tint color, modulated by the original luminance,
    keeping the alpha channel intact.
    """
```

**Tint approach detail:**
```python
# For each pixel:
luminance = (R * 0.299 + G * 0.587 + B * 0.114) / 255.0
new_R = tint_color[0] * luminance
new_G = tint_color[1] * luminance
new_B = tint_color[2] * luminance
new_A = original_alpha  # Preserve overlay shape
```

**DDS encoding for output:**
We need to write the composited image back as DDS so Blender/Sollumz can load it. Options:
- Use `src/dds_builder.py` in reverse (build a DDS with uncompressed A8R8G8B8 format — Blender can load this)
- Or save as PNG and let Blender load PNG directly (simpler, Blender supports PNG natively)

**Recommendation:** Save as PNG. The DDS is only needed for Sollumz auto-texture-matching. Since we'll manually assign the texture via `fix_missing_textures()`, PNG is fine and avoids DDS encoding complexity.

**Files to create:** `src/overlay_compositor.py` (~100 lines)

### Step 3: Blender Script — Portrait Camera Mode

Add a new rendering function to `src/blender_script.py` for face overlay portraits.

**Option A: New `render_face_overlay()` function**

```python
def render_face_overlay(item: dict, cam_obj: bpy.types.Object,
                        work_base: str) -> dict:
    """Render a face overlay portrait.

    item keys:
      - ydd_path: path to head .ydd mesh
      - dds_files: [path to composited texture PNG/DDS]
      - output_path: output .webp path
      - overlay_type: "beard", "eyebrowf", "eyebrowm"
      - category: "head" (for existing flat-mesh detection to skip)
    """
    # 1. Clear scene (keep camera + lights)
    # 2. Import head YDD
    # 3. Fix missing textures (apply composited texture)
    # 4. Fix alpha modes
    # 5. Frame camera in PORTRAIT mode (see below)
    # 6. Render
```

**Option B: Extend existing `render_item()` with portrait flag**

Add a `"portrait_mode"` key to the work item dict. When set, `frame_camera()` uses tighter framing:

```python
def frame_camera_portrait(cam_obj, overlay_type="beard"):
    """Frame camera for face portrait - tighter than product shot."""
    bbox = get_mesh_bounding_box()
    bb_min, bb_max = bbox
    center = (bb_min + bb_max) / 2
    size = bb_max - bb_min

    # For face overlays, frame just the face area
    # Head mesh Z range: chin to top of head
    # Face is roughly the front 70% height
    if overlay_type in ("eyebrowf", "eyebrowm"):
        # Frame upper half of head (forehead area)
        frame_center_z = center.z + size.z * 0.15
        frame_height = size.z * 0.5
    elif overlay_type == "beard":
        # Frame lower 2/3 of head (jaw/chin area)
        frame_center_z = center.z - size.z * 0.05
        frame_height = size.z * 0.6
    else:
        # Full face
        frame_center_z = center.z
        frame_height = size.z * 0.7

    cam_obj.data.ortho_scale = max(size.x, frame_height) * 1.1
    # Position: straight-on, 0-3° elevation
    distance = 5
    cam_obj.location = Vector((center.x, center.y - distance, frame_center_z))
    direction = Vector((center.x, center.y, frame_center_z)) - cam_obj.location
    rot = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot.to_euler()
```

**Recommendation:** Option B (extend `render_item()`). Less code duplication. The item dict just needs `"portrait_mode": true` and `"overlay_type": "beard"`.

**Files to modify:** `src/blender_script.py` — add `frame_camera_portrait()` (~30 lines), modify `render_item()` to check for portrait_mode (~5 lines)

### Step 4: Scanner Integration

Modify `src/scanner.py` to discover and process overlays.

**4a. New CLI flag in `cli.py`:**
```python
parser.add_argument("--overlays", type=str, default=None,
    help="Path to face overlay directory (mp_fm_faov_*.ytd files)")
```

**4b. New discovery step in `scanner.py`:**
```python
def _discover_overlay_items(
    overlays_dir: Path,
    base_game_dir: Path,
    output_dir: Path,
) -> list[dict]:
    """Discover face overlay files and create work items.

    For each overlay:
      1. Determine gender → pick base head mesh + texture
      2. Pre-composite overlay onto base head texture
      3. Create work item for Blender rendering
    """
    overlays = discover_overlays(overlays_dir)
    items = []

    for ov in overlays:
        # Pick base head based on gender
        if ov.gender == "female":
            head_ydd = base_game_dir / "base/mp_f_freemode_01/head_000_r.ydd"
            head_ytd = base_game_dir / "base/mp_f_freemode_01/head_diff_000_a_whi.ytd"
        else:
            head_ydd = base_game_dir / "base/mp_m_freemode_01/head_000_r.ydd"
            head_ytd = base_game_dir / "base/mp_m_freemode_01/head_diff_000_a_whi.ytd"

        # Output path
        output_webp = output_dir / f"textures/overlays/{ov.overlay_type}/{ov.index:03d}.webp"
        texture_rel = f"overlays/{ov.overlay_type}/{ov.index:03d}.webp"
        catalog_key = f"overlay_{ov.overlay_type}_{ov.index:03d}"

        items.append({
            "ytd_path": str(ov.file_path),
            "head_ydd_path": str(head_ydd),
            "head_ytd_path": str(head_ytd),
            "output_webp": str(output_webp),
            "texture_rel": texture_rel,
            "catalog_key": catalog_key,
            "overlay_type": ov.overlay_type,
            "overlay_index": ov.index,
            "gender": ov.gender,
            "portrait_mode": True,
        })

    return items
```

**4c. Processing phase in scanner.py:**

New rendering phase after existing phases:

```python
# Phase 6: Face overlay portraits
if overlays_dir and base_game_dir:
    overlay_items = _discover_overlay_items(overlays_dir, base_game_dir, output_dir)

    # Pre-composite all overlays (parallel, CPU-bound)
    composited_items = _precomposite_overlays(overlay_items, tmp_dir)

    # Render via existing Blender pipeline
    overlay_results = render_batch(composited_items, blender_path, render_config)

    # Build catalog entries
    for item, result in zip(composited_items, overlay_results):
        if result["success"]:
            catalog[item["catalog_key"]] = CatalogItem(
                dlc_name="base",
                gender=item["gender"],
                category=item["overlay_type"],
                drawable_id=item["overlay_index"],
                texture_path=item["texture_rel"],
                variants=0,
                source_file=os.path.basename(item["ytd_path"]),
                width=512, height=512,
                original_width=512, original_height=512,
                format_name="3D_RENDER",
                render_type="3d",
                item_type="overlay",
            )
```

**Files to modify:** `src/scanner.py` (~80 lines added), `cli.py` (~3 lines)

### Step 5: Blender Renderer Integration

Modify `src/blender_renderer.py` to handle overlay work items.

The overlay items flow through the existing `render_batch()` pipeline. The only difference is the work item has:
- `ydd_path` = head mesh (not a clothing mesh)
- `dds_files` = [composited PNG/DDS] (not original clothing texture)
- `portrait_mode` = True
- `overlay_type` = "beard" / "eyebrowf" / "eyebrowm"
- `category` = "head" (so flat-mesh detection doesn't reject it)

The `_pre_extract_dds_single()` function won't be used for overlays since we pre-composite ourselves. Instead, the composited PNG is passed directly as a DDS file.

**Modification needed in `blender_renderer.py`:**
- Skip DDS pre-extraction for overlay items (they already have composited textures)
- Pass `portrait_mode` and `overlay_type` fields through to the Blender work item

**Files to modify:** `src/blender_renderer.py` (~15 lines)

### Step 6: Catalog Extension

Add overlay support to `src/catalog.py`.

The existing `CatalogItem` dataclass already has `item_type` field. We add `"overlay"` as a new value.

**Output JSON for overlays:**
```json
{
    "overlay_beard_000": {
        "dlcName": "base",
        "gender": "male",
        "category": "beard",
        "drawableId": 0,
        "texture": "overlays/beard/000.webp",
        "variants": 0,
        "source": "mp_fm_faov_beard_000.ytd",
        "width": 512,
        "height": 512,
        "format": "3D_RENDER",
        "renderType": "3d",
        "itemType": "overlay"
    }
}
```

**Files to modify:** `src/catalog.py` — minimal changes, existing structure supports this.

### Step 7: Output Directory Structure

```
output/textures/overlays/
    beard/
        000.webp    (portrait of head with beard 0)
        001.webp
        ...
        025.webp
    eyebrowf/
        000.webp    (portrait of female head with eyebrow 0)
        ...
        016.webp
    eyebrowm/
        000.webp    (portrait of male head with eyebrow 0)
        ...
        016.webp
```

## Implementation Order

1. **`src/overlay_parser.py`** — Discovery module (new file, ~60 lines)
2. **`src/overlay_compositor.py`** — Pre-compositing module (new file, ~100 lines)
3. **`src/blender_script.py`** — Portrait camera framing (modify, ~35 lines)
4. **`src/blender_renderer.py`** — Skip DDS pre-extract for overlays (modify, ~15 lines)
5. **`src/scanner.py`** — Overlay discovery + processing phase (modify, ~80 lines)
6. **`cli.py`** — `--overlays` flag (modify, ~3 lines)
7. **Tests** — `tests/test_overlay_parser.py`, `tests/test_overlay_compositor.py`

## Open Questions / Risks

1. **Tinting**: The overlay textures may already be colored (not grayscale). Need to check a few actual textures to see if tinting is needed or if they render fine as-is. If they're already colored, skip the tint step.

2. **Portrait framing**: May need iteration on camera positioning. Eyebrows are tiny on a full head render. Consider rendering at 1024x1024 and cropping to the relevant face region rather than camera framing.

3. **Chest hair**: No `chesthair` files found in the dump. If user extracts them later, they'll need a torso body mesh instead of a head mesh, with different camera framing. The architecture supports this via `overlay_type` branching.

4. **Normal/specular maps**: The `_n` and `_s` companion files could improve render quality by adding depth/shininess to beards. For v1, skip these. For v2, load them as additional Blender material nodes.

5. **Base head selection**: Using `head_000` (first heritage parent) as the base. This is a generic neutral face. May want to offer a choice of base head for different ethnicities.

6. **DDS encoding**: If Blender/Sollumz rejects PNG for texture loading, we may need to write the composited image as uncompressed DDS (A8R8G8B8). Our `dds_builder.py` already supports this format — we'd just need a reverse function.

## Estimated Scope

- **New files**: 2 (~160 lines total)
- **Modified files**: 4 (~135 lines total)
- **Test files**: 2 (~80 lines total)
- **Total**: ~375 lines of new/modified code
