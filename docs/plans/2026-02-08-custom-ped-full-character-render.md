# Custom Ped Full Character Render — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generate a full-body character preview render for each custom ped (e.g., strafe) by assembling the default body parts (head, uppr, lowr, feet, hand) with the YFT skeleton, producing a single product-style image like GTA V loading screens.

**Architecture:** Discover custom peds by finding `.yft` skeleton files in stream directories. For each ped, import the YFT skeleton + default body parts (drawable ID 000 for each required category) into one Blender scene using Sollumz's `import_external_skeleton` feature, apply diffuse textures, render a full-body shot with adjusted camera framing. Outputs go to `textures/{ped_name}/preview.webp` and a new `"ped_preview"` entry in catalog.json.

**Tech Stack:** Python 3.12, Blender 4.5 + Sollumz (Eevee Next), existing blender_script.py worker IPC

---

## Background

### What We Have
- Custom ped `strafe` at `stream/rhpeds/stream/[strafe]/`
- Files: `strafe.yft` (16KB skeleton), `strafe.ymt` (metadata), 119 YDDs, 350 YTDs
- Default body parts exist at drawable ID 000: `head_000`, `uppr_000`, `lowr_000`, `feet_000`, `hand_000`
- Each YDD has matching `_diff_000_a_uni.ytd` textures
- Existing Blender pipeline renders single items — one YDD + one YTD per render

### What We Need
- A single full-body render showing the ped in its default outfit (all 000 drawables assembled)
- The YFT skeleton is critical — it positions body parts correctly in 3D space
- Sollumz has `import_external_skeleton` preference that auto-finds a `.yft` in the same directory and uses it as the armature for `.ydd` imports
- Camera needs full-body framing (existing `frame_camera()` already handles multi-object scenes)

### Key Categories for Full Body
Required (must exist for a valid ped render):
- `head` — face/head mesh
- `uppr` — upper body/torso
- `lowr` — lower body/legs
- `feet` — shoes/feet
- `hand` — hands (sometimes just finger geometry)

Optional (enhances the render but not required):
- `hair` — hair style (drawable 000)
- `accs` — accessories
- `teef` — teeth (usually not visible)
- `berd` — beard
- `decl` — decals/tattoo overlays

---

## Task 1: Discover Custom Peds and Their Default Parts

**Files:**
- Modify: `src/scanner.py`
- Test: `tests/test_ped_discovery.py` (new)

### Step 1: Write the failing test

```python
# tests/test_ped_discovery.py
"""Tests for custom ped discovery."""

import os
import tempfile
import pytest
from src.scanner import discover_custom_peds


class TestDiscoverCustomPeds:
    """Test discovery of custom ped directories with .yft skeletons."""

    def test_finds_ped_with_yft(self, tmp_path):
        """A directory containing a .yft file is detected as a custom ped."""
        ped_dir = tmp_path / "stream" / "rhpeds" / "stream" / "[strafe]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "strafe.yft").write_bytes(b"\x00" * 100)
        # Create default body part YDDs + YTDs
        for cat in ("head", "uppr", "lowr", "feet", "hand"):
            (ped_dir / f"strafe^{cat}_000_u.ydd").write_bytes(b"\x00" * 2000)
            (ped_dir / f"strafe^{cat}_diff_000_a_uni.ytd").write_bytes(b"\x00" * 200)

        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert len(peds) == 1
        ped = peds[0]
        assert ped["model"] == "strafe"
        assert ped["yft_path"].endswith("strafe.yft")
        assert len(ped["body_parts"]) == 5
        assert set(ped["body_parts"].keys()) == {"head", "uppr", "lowr", "feet", "hand"}

    def test_skips_directory_without_yft(self, tmp_path):
        """A directory with YDDs but no .yft is NOT a custom ped."""
        ped_dir = tmp_path / "stream" / "pack" / "stream" / "[noped]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "noped^uppr_000_u.ydd").write_bytes(b"\x00" * 2000)
        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert len(peds) == 0

    def test_body_part_has_ydd_and_ytd(self, tmp_path):
        """Each body part dict has both ydd_path and ytd_path."""
        ped_dir = tmp_path / "stream" / "pack" / "stream" / "[test]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "testped.yft").write_bytes(b"\x00" * 100)
        (ped_dir / "testped^head_000_u.ydd").write_bytes(b"\x00" * 2000)
        (ped_dir / "testped^head_diff_000_a_uni.ytd").write_bytes(b"\x00" * 200)
        (ped_dir / "testped^uppr_000_u.ydd").write_bytes(b"\x00" * 2000)
        (ped_dir / "testped^uppr_diff_000_a_uni.ytd").write_bytes(b"\x00" * 200)

        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert len(peds) == 1
        head = peds[0]["body_parts"]["head"]
        assert head["ydd_path"].endswith("testped^head_000_u.ydd")
        assert head["ytd_path"].endswith("testped^head_diff_000_a_uni.ytd")

    def test_includes_optional_hair(self, tmp_path):
        """Hair (optional category) is included when present."""
        ped_dir = tmp_path / "stream" / "pack" / "stream" / "[myped]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "myped.yft").write_bytes(b"\x00" * 100)
        for cat in ("head", "uppr", "lowr", "feet", "hand", "hair"):
            (ped_dir / f"myped^{cat}_000_u.ydd").write_bytes(b"\x00" * 2000)
            (ped_dir / f"myped^{cat}_diff_000_a_uni.ytd").write_bytes(b"\x00" * 200)

        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert "hair" in peds[0]["body_parts"]

    def test_output_path(self, tmp_path):
        """Output path follows textures/{ped_name}/preview.webp convention."""
        ped_dir = tmp_path / "stream" / "pack" / "stream" / "[strafe]"
        ped_dir.mkdir(parents=True)
        (ped_dir / "strafe.yft").write_bytes(b"\x00" * 100)
        for cat in ("head", "uppr", "lowr", "feet", "hand"):
            (ped_dir / f"strafe^{cat}_000_u.ydd").write_bytes(b"\x00" * 2000)
            (ped_dir / f"strafe^{cat}_diff_000_a_uni.ytd").write_bytes(b"\x00" * 200)

        peds = discover_custom_peds(str(tmp_path / "stream"))
        assert peds[0]["output_rel"] == "strafe/preview.webp"
```

### Step 2: Run test to verify it fails

Run: `python -m pytest tests/test_ped_discovery.py -v`
Expected: FAIL with `ImportError: cannot import name 'discover_custom_peds' from 'src.scanner'`

### Step 3: Implement `discover_custom_peds()`

Add to `src/scanner.py`:

```python
# ---------------------------------------------------------------------------
# Custom ped full-body discovery
# ---------------------------------------------------------------------------

_REQUIRED_BODY_CATEGORIES = ("head", "uppr", "lowr", "feet", "hand")
_OPTIONAL_BODY_CATEGORIES = ("hair", "accs", "teef", "berd", "decl")

def discover_custom_peds(input_dir: str) -> list[dict]:
    """Find custom ped directories that contain a .yft skeleton.

    Returns a list of dicts, each describing one custom ped:
        {
            "model": "strafe",
            "yft_path": "/abs/path/strafe.yft",
            "ped_dir": "/abs/path/[strafe]/",
            "body_parts": {
                "head": {"ydd_path": "...", "ytd_path": "..."},
                "uppr": {"ydd_path": "...", "ytd_path": "..."},
                ...
            },
            "output_rel": "strafe/preview.webp",
        }
    """
    import re
    peds = []

    for dirpath, dirnames, filenames in os.walk(input_dir):
        dirnames[:] = [d for d in dirnames if d.lower() != "[replacements]"]

        # Look for .yft files — each one defines a custom ped
        yft_files = [f for f in filenames if f.lower().endswith(".yft")]
        if not yft_files:
            continue

        for yft_name in yft_files:
            model = os.path.splitext(yft_name)[0]  # "strafe"
            yft_path = os.path.join(dirpath, yft_name)

            # Find default body part YDDs (drawable 000) and their textures
            body_parts: dict[str, dict] = {}
            all_cats = _REQUIRED_BODY_CATEGORIES + _OPTIONAL_BODY_CATEGORIES

            for cat in all_cats:
                # YDD: {model}^{cat}_000_u.ydd
                ydd_name = f"{model}^{cat}_000_u.ydd"
                ydd_path = os.path.join(dirpath, ydd_name)

                # YTD: {model}^{cat}_diff_000_a_uni.ytd (try _uni first, then plain _a)
                ytd_candidates = [
                    f"{model}^{cat}_diff_000_a_uni.ytd",
                    f"{model}^{cat}_diff_000_a.ytd",
                ]
                ytd_path = None
                for ytd_name in ytd_candidates:
                    candidate = os.path.join(dirpath, ytd_name)
                    if os.path.isfile(candidate):
                        ytd_path = candidate
                        break
                # Also try ethnicity suffixes (_whi, _bla, etc.)
                if ytd_path is None:
                    for suffix in ("whi", "bla", "lat", "chi", "pak", "ara"):
                        candidate = os.path.join(dirpath, f"{model}^{cat}_diff_000_a_{suffix}.ytd")
                        if os.path.isfile(candidate):
                            ytd_path = candidate
                            break

                if os.path.isfile(ydd_path) and ytd_path:
                    body_parts[cat] = {
                        "ydd_path": ydd_path,
                        "ytd_path": ytd_path,
                    }

            if body_parts:
                peds.append({
                    "model": model,
                    "yft_path": yft_path,
                    "ped_dir": dirpath,
                    "body_parts": body_parts,
                    "output_rel": f"{model}/preview.webp",
                })

    return peds
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/test_ped_discovery.py -v`
Expected: All 5 tests PASS

### Step 5: Commit

```bash
git add tests/test_ped_discovery.py src/scanner.py
git commit -m "feat: discover custom peds with .yft skeletons for full-body render"
```

---

## Task 2: Add Full-Body Render Command to Blender Script

**Files:**
- Modify: `src/blender_script.py`
- Test: Manual Blender test (Blender script tests are integration-only)

### Step 1: Add `render_full_ped()` function to blender_script.py

This is the core new function. It differs from `render_item()` in that:
1. It enables `import_external_skeleton` in Sollumz preferences
2. It copies the `.yft` skeleton into the work directory alongside each YDD
3. It imports multiple YDDs sequentially (each gets rigged to the skeleton automatically)
4. It applies textures for all body parts
5. Camera auto-frames the full assembled character

Add after the existing `render_item()` function (around line 632):

```python
def render_full_ped(item: dict, cam_obj: bpy.types.Object,
                    work_base: str) -> dict:
    """Render a full custom ped by assembling multiple body parts on a skeleton.

    Args:
        item: Dict with keys:
            - yft_path: Path to .yft skeleton file
            - body_parts: Dict of {category: {ydd_path, dds_files}}
            - output_path: Where to save the render
        cam_obj: The camera object
        work_base: Base temp directory for this Blender session

    Returns:
        Dict with keys: output_path, success, error (if failed)
    """
    yft_path = item["yft_path"]
    body_parts = item["body_parts"]
    output_path = item["output_path"]

    result = {"output_path": output_path, "success": False, "error": None}

    try:
        # Clear previous objects (keep camera and lights)
        for obj in list(bpy.data.objects):
            if obj.type not in ('CAMERA', 'LIGHT'):
                bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        for mat in list(bpy.data.materials):
            if mat.users == 0:
                bpy.data.materials.remove(mat)
        for img in list(bpy.data.images):
            if img.users == 0:
                bpy.data.images.remove(img)

        # Enable external skeleton import in Sollumz preferences
        _set_sollumz_external_skeleton(True)

        # Create a shared work directory and copy the YFT skeleton into it
        ped_work = os.path.join(work_base, f"ped_{id(item)}")
        os.makedirs(ped_work, exist_ok=True)
        yft_basename = os.path.basename(yft_path)
        dest_yft = os.path.join(ped_work, yft_basename)
        shutil.copy2(yft_path, dest_yft)

        # Import each body part YDD with its textures.
        # Sollumz will auto-detect the .yft in the same directory and use it
        # as the external skeleton/armature.
        imported_any = False
        for cat, part in body_parts.items():
            ydd_path = part["ydd_path"]
            dds_files = part.get("dds_files", [])

            # Copy YDD to work dir (alongside the YFT)
            ydd_basename = os.path.basename(ydd_path)
            dest_ydd = os.path.join(ped_work, ydd_basename)
            shutil.copy2(ydd_path, dest_ydd)

            # Copy DDS textures into a subdirectory matching the YDD stem
            ydd_stem = os.path.splitext(ydd_basename)[0]
            tex_dir = os.path.join(ped_work, ydd_stem)
            os.makedirs(tex_dir, exist_ok=True)
            for dds_path in dds_files:
                shutil.copy2(dds_path, os.path.join(tex_dir, os.path.basename(dds_path)))

            # Import via Sollumz (skeleton auto-detected from same directory)
            if import_ydd(dest_ydd):
                imported_any = True
                # Fix textures for this part
                fix_missing_textures(
                    [os.path.join(tex_dir, f) for f in os.listdir(tex_dir)]
                )
            else:
                print(f"    WARNING: Failed to import {cat} ({ydd_basename})")

        if not imported_any:
            result["error"] = "No body parts imported successfully"
            return result

        # Disable external skeleton for subsequent normal renders
        _set_sollumz_external_skeleton(False)

        # Fix alpha modes across all imported materials
        fix_alpha_modes()

        # Fix hair tint if hair was imported
        if GREEN_HAIR_FIX and "hair" in body_parts:
            fix_hair_tint()

        # Frame camera on the full assembled character
        frame_camera(cam_obj, elevation_deg=CAMERA_ELEVATION_DEG)

        # Render
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        bpy.context.scene.render.filepath = output_path
        bpy.ops.render.render(write_still=True)

        if os.path.isfile(output_path):
            result["success"] = True
        else:
            result["error"] = "Render produced no output file"

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc(file=sys.stderr)
    finally:
        # Always restore external skeleton setting
        try:
            _set_sollumz_external_skeleton(False)
        except Exception:
            pass

    return result


def _set_sollumz_external_skeleton(enabled: bool) -> None:
    """Toggle the 'Import External Skeleton' setting in Sollumz preferences."""
    try:
        prefs = bpy.context.preferences
        for addon_name in ("bl_ext.blender_org.sollumz_dev",
                           "bl_ext.blender_org.sollumz",
                           "SollumzPlugin"):
            addon_prefs = prefs.addons.get(addon_name)
            if addon_prefs and hasattr(addon_prefs, "preferences"):
                settings = getattr(addon_prefs.preferences, "import_settings", None)
                if settings and hasattr(settings, "import_ext_skeleton"):
                    settings.import_ext_skeleton = enabled
                    print(f"    Sollumz import_ext_skeleton = {enabled}")
                    return
        # Fallback: try via get_import_settings if available
        print(f"    WARNING: Could not find Sollumz preferences to set external skeleton")
    except Exception as exc:
        print(f"    WARNING: Could not set external skeleton preference: {exc}")
```

### Step 2: Add `"render_full_ped"` command handling to the worker loop

In the worker message handler (the `while True` loop that reads JSON commands from stdin), add handling for a new `"type": "full_ped"` message. Find the section where items are dispatched and add:

```python
# In the worker loop, after the normal render_item dispatch:
if item.get("type") == "full_ped":
    result = render_full_ped(item, cam_obj, work_base)
else:
    result = render_item(item, cam_obj, work_base)
```

### Step 3: Test manually with a single ped

Run from project root:
```bash
python -c "
from src.scanner import discover_custom_peds
peds = discover_custom_peds('stream')
for p in peds:
    print(f'Found: {p[\"model\"]} with {len(p[\"body_parts\"])} body parts')
    for cat, part in p['body_parts'].items():
        print(f'  {cat}: {part[\"ydd_path\"]}')
"
```

### Step 4: Commit

```bash
git add src/blender_script.py
git commit -m "feat: add render_full_ped() for multi-part character assembly with YFT skeleton"
```

---

## Task 3: Pre-Extract DDS Textures for Full-Ped Render

**Files:**
- Modify: `src/blender_renderer.py`
- Test: `tests/test_ped_dds_extraction.py` (new)

### Step 1: Write the failing test

```python
# tests/test_ped_dds_extraction.py
"""Tests for DDS pre-extraction for full ped body parts."""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock


class TestPreExtractPedDds:
    """Test DDS extraction for all body parts of a custom ped."""

    def test_extracts_dds_for_each_body_part(self, tmp_path):
        """Each body part's YTD should produce DDS files."""
        from src.blender_renderer import pre_extract_ped_dds

        # Create mock ped dict
        ped = {
            "model": "testped",
            "body_parts": {
                "head": {"ydd_path": str(tmp_path / "head.ydd"), "ytd_path": "/fake/head.ytd"},
                "uppr": {"ydd_path": str(tmp_path / "uppr.ydd"), "ytd_path": "/fake/uppr.ytd"},
            },
        }

        # Mock the actual DDS extraction to return fake files
        fake_dds = [str(tmp_path / "texture.dds")]
        (tmp_path / "texture.dds").write_bytes(b"\x00" * 100)

        with patch("src.blender_renderer.extract_dds_for_ydd", return_value=fake_dds):
            result = pre_extract_ped_dds(ped, str(tmp_path / "dds_cache"))

        assert "head" in result
        assert "uppr" in result
        assert isinstance(result["head"], list)
        assert len(result["head"]) > 0
```

### Step 2: Run test to verify it fails

Run: `python -m pytest tests/test_ped_dds_extraction.py -v`
Expected: FAIL with `ImportError: cannot import name 'pre_extract_ped_dds'`

### Step 3: Implement `pre_extract_ped_dds()`

Add to `src/blender_renderer.py`:

```python
def pre_extract_ped_dds(ped: dict, dds_cache_dir: str) -> dict[str, list[str]]:
    """Pre-extract DDS textures for all body parts of a custom ped.

    Args:
        ped: Custom ped dict from discover_custom_peds()
        dds_cache_dir: Directory to store extracted DDS files

    Returns:
        Dict mapping category -> list of DDS file paths
    """
    result: dict[str, list[str]] = {}
    for cat, part in ped["body_parts"].items():
        ytd_path = part["ytd_path"]
        ydd_path = part["ydd_path"]
        try:
            dds_files = extract_dds_for_ydd(ytd_path, ydd_path, dds_cache_dir)
            result[cat] = dds_files
        except Exception as exc:
            logger.warning("Failed to extract DDS for %s %s: %s", ped["model"], cat, exc)
            result[cat] = []
    return result
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/test_ped_dds_extraction.py -v`
Expected: PASS

### Step 5: Commit

```bash
git add src/blender_renderer.py tests/test_ped_dds_extraction.py
git commit -m "feat: add pre_extract_ped_dds() for full ped texture extraction"
```

---

## Task 4: Integrate Full-Ped Rendering into Scanner Pipeline

**Files:**
- Modify: `src/scanner.py` (add step between step 6 and step 7)
- Modify: `src/blender_renderer.py` (add `render_full_ped_batch()`)
- Modify: `src/catalog.py` (add `itemType: "ped_preview"` support)
- Test: `tests/test_ped_render_integration.py` (new)

### Step 1: Write the failing test

```python
# tests/test_ped_render_integration.py
"""Integration test for full ped rendering pipeline."""

import os
import pytest


class TestPedCatalogEntry:
    """Test that ped previews are correctly added to the catalog."""

    def test_ped_preview_catalog_item(self):
        from src.catalog import CatalogBuilder, CatalogItem

        catalog = CatalogBuilder()
        catalog.add_item(CatalogItem(
            dlc_name="strafe",
            gender="unknown",
            category="preview",
            drawable_id=0,
            texture_path="strafe/preview.webp",
            variants=0,
            source_file="strafe.yft",
            width=512,
            height=512,
            original_width=1024,
            original_height=1024,
            format_name="3D_RENDER",
            render_type="3d",
            item_type="ped_preview",
        ))

        items = catalog.build()
        key = "strafe_unknown_preview_000"
        assert key in items
        assert items[key]["itemType"] == "ped_preview"
```

### Step 2: Run test to verify it fails or passes

Run: `python -m pytest tests/test_ped_render_integration.py -v`
Expected: This should PASS already since CatalogItem is generic. If not, adjust.

### Step 3: Add `render_full_ped_batch()` to blender_renderer.py

Add a function that:
1. Pre-extracts DDS for all body parts
2. Sends a `type: "full_ped"` work item to the Blender worker pool
3. Returns success/failure result

```python
def render_full_ped_batch(
    peds: list[dict],
    blender_path: str,
    output_dir: str,
    render_size: int = 1024,
    taa_samples: int = 1,
    output_size: int = 512,
    webp_quality: int = 100,
) -> list[dict]:
    """Render full-body previews for discovered custom peds.

    Each ped is rendered as a single image with all body parts assembled
    on the YFT skeleton.

    Returns list of result dicts with output_path and success status.
    """
    if not peds:
        return []

    results = []
    dds_cache = tempfile.mkdtemp(prefix="ped_dds_")

    try:
        for ped in peds:
            # Pre-extract DDS textures for all body parts
            dds_by_cat = pre_extract_ped_dds(ped, dds_cache)

            # Build the work item for Blender
            output_path = os.path.join(output_dir, "textures", ped["output_rel"])
            body_parts_with_dds = {}
            for cat, part in ped["body_parts"].items():
                body_parts_with_dds[cat] = {
                    "ydd_path": part["ydd_path"],
                    "dds_files": dds_by_cat.get(cat, []),
                }

            work_item = {
                "type": "full_ped",
                "yft_path": ped["yft_path"],
                "body_parts": body_parts_with_dds,
                "output_path": output_path,
            }

            # Render via existing worker pool (reuse one worker for ped renders)
            # Ped renders are few (1-3 peds typically) so sequential is fine
            result = _render_single_ped(work_item, blender_path, render_size,
                                        taa_samples, output_size, webp_quality)
            result["model"] = ped["model"]
            result["output_rel"] = ped["output_rel"]
            results.append(result)
    finally:
        shutil.rmtree(dds_cache, ignore_errors=True)

    return results
```

### Step 4: Wire into scanner.py `scan_and_process()`

Add after existing 3D rendering (step 6) and before flat texture processing:

```python
# --- Step 6b: Full ped preview renders ---
if render_3d and blender_path:
    custom_peds = discover_custom_peds(input_dir)
    if custom_peds:
        logger.info("Rendering %d custom ped preview(s)...", len(custom_peds))
        _emit_json({"type": "phase", "phase": "ped_previews",
                     "total": len(custom_peds)})

        from src.blender_renderer import render_full_ped_batch
        ped_results = render_full_ped_batch(
            custom_peds, blender_path, output_dir,
            render_size=render_size,
            taa_samples=taa_samples,
            output_size=output_size,
            webp_quality=webp_quality,
        )

        for pr in ped_results:
            if pr.get("success"):
                catalog.add_item(CatalogItem(
                    dlc_name=pr["model"],
                    gender="unknown",
                    category="preview",
                    drawable_id=0,
                    texture_path=pr["output_rel"],
                    variants=0,
                    source_file=f"{pr['model']}.yft",
                    width=output_size,
                    height=output_size,
                    original_width=render_size,
                    original_height=render_size,
                    format_name="3D_RENDER",
                    render_type="3d",
                    item_type="ped_preview",
                ))
                logger.info("  %s: OK", pr["model"])
            else:
                logger.warning("  %s: FAILED — %s", pr["model"], pr.get("error"))
```

### Step 5: Commit

```bash
git add src/scanner.py src/blender_renderer.py src/catalog.py tests/test_ped_render_integration.py
git commit -m "feat: integrate full ped rendering into scanner pipeline with catalog support"
```

---

## Task 5: Handle Sollumz Preferences API for External Skeleton

**Files:**
- Modify: `src/blender_script.py`

### Step 1: Investigate Sollumz preferences access

The `_set_sollumz_external_skeleton()` function written in Task 2 needs to actually work. The Sollumz addon stores import settings as a `PointerProperty` on the addon preferences object. The API path is:

```python
# Sollumz preferences path (from sollumz_preferences.py):
# get_addon_preferences(context).import_settings.import_ext_skeleton
```

But from a headless Blender worker, we may need to access it differently. The Sollumz `get_import_settings()` helper function returns the settings directly:

```python
from sollumz_preferences import get_import_settings
settings = get_import_settings()
settings.import_ext_skeleton = True
```

However, since Sollumz is loaded as an extension, we need to import through the Blender extension namespace.

### Step 2: Implement robust preference setter

Replace `_set_sollumz_external_skeleton()` with a version that tries multiple access paths:

```python
def _set_sollumz_external_skeleton(enabled: bool) -> None:
    """Toggle the 'Import External Skeleton' setting in Sollumz preferences."""
    # Method 1: Try via Sollumz's own helper
    for mod_name in ("bl_ext.blender_org.sollumz_dev", "bl_ext.blender_org.sollumz"):
        try:
            import importlib
            mod = importlib.import_module(f"{mod_name}.sollumz_preferences")
            settings = mod.get_import_settings()
            settings.import_ext_skeleton = enabled
            print(f"    Sollumz import_ext_skeleton = {enabled} (via {mod_name})")
            return
        except Exception:
            continue

    # Method 2: Try via bpy.context.preferences.addons
    try:
        for addon_name in ("bl_ext.blender_org.sollumz_dev", "bl_ext.blender_org.sollumz"):
            addon_prefs = bpy.context.preferences.addons.get(addon_name)
            if addon_prefs:
                prefs_obj = addon_prefs.preferences
                if hasattr(prefs_obj, "import_settings"):
                    prefs_obj.import_settings.import_ext_skeleton = enabled
                    print(f"    Sollumz import_ext_skeleton = {enabled} (via addon prefs)")
                    return
    except Exception:
        pass

    print(f"    WARNING: Could not set Sollumz external skeleton preference")
```

### Step 3: Commit

```bash
git add src/blender_script.py
git commit -m "fix: robust Sollumz preferences access for external skeleton toggle"
```

---

## Task 6: Manual Integration Test

**Files:** None (testing only)

### Step 1: Run discovery to verify strafe ped is found

```bash
python -c "
from src.scanner import discover_custom_peds
peds = discover_custom_peds('stream')
for p in peds:
    print(f'Ped: {p[\"model\"]}')
    print(f'  YFT: {p[\"yft_path\"]}')
    print(f'  Body parts:')
    for cat, part in sorted(p['body_parts'].items()):
        print(f'    {cat}: {part[\"ydd_path\"]}')
    print(f'  Output: {p[\"output_rel\"]}')
"
```

### Step 2: Run a single ped render test

```bash
python -m src.scanner --input stream --output output_test --render-3d --categories preview
```

Or if no `--categories` filter exists, run the full pipeline and check:

```bash
python -m src.scanner --input stream --output output_test --render-3d
```

Then verify: `output_test/textures/strafe/preview.webp` exists and shows a full character.

### Step 3: Check catalog.json

```bash
python -c "
import json
with open('output_test/catalog.json') as f:
    data = json.load(f)
ped_items = {k: v for k, v in data['items'].items() if v.get('itemType') == 'ped_preview'}
print(json.dumps(ped_items, indent=2))
"
```

### Step 4: Visual inspection

Open `output_test/textures/strafe/preview.webp` and verify it shows a full standing character similar to the reference image (standing T-pose or A-pose with all body parts visible).

### Step 5: If render looks wrong, debug

Common issues:
- **Body parts floating/disconnected**: YFT skeleton not loading → check `_set_sollumz_external_skeleton`
- **Missing textures**: DDS extraction failed → check DDS pre-extraction logs
- **Camera too close/far**: `frame_camera()` should handle this automatically
- **Character facing wrong way**: May need rotation step → add `rotation_steps: [[0, 0, math.pi]]` to face camera

### Step 6: Commit final adjustments

```bash
git add -A
git commit -m "feat: complete custom ped full-body preview rendering"
```

---

## Summary

| Task | Description | Estimated Complexity |
|------|-------------|---------------------|
| 1 | Discover custom peds (find .yft + default body parts) | Low |
| 2 | Add `render_full_ped()` to Blender script | Medium |
| 3 | Pre-extract DDS textures for all body parts | Low |
| 4 | Wire into scanner pipeline + catalog | Medium |
| 5 | Robust Sollumz preferences API for external skeleton | Low |
| 6 | Manual integration test + visual QA | Low |

**Key Risk:** Sollumz `import_external_skeleton` may not work correctly in headless/worker mode, or may not properly rig multiple YDDs to the same skeleton. If this fails, the fallback approach is:
1. Import the YFT directly (it contains a base drawable + skeleton)
2. Import each YDD without skeleton — they'll appear at their raw vertex positions
3. GTA V YDDs for peds are already authored in world-space coordinates matching the skeleton, so they may align correctly even without explicit rigging

**Output:**
- `textures/{ped_name}/preview.webp` — 512x512 full-body character render
- catalog.json entry with `itemType: "ped_preview"`
