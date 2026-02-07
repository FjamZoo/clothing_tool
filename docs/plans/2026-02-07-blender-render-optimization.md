# Blender Render Pipeline Optimization

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce per-item Blender render time from ~1.9s to ~0.8s, reaching ~10 img/sec with 8 workers.

**Architecture:** Four independent optimizations applied to the existing persistent-worker pipeline: (1) render at 1024px instead of 2048px, (2) drop TAA from 8 to 1, (3) have Blender output WebP directly (eliminating the Python PNG→WebP post-process), (4) replace the pure-Python `is_image_empty()` with a numpy one-liner. GPU (AMD HIP) is already configured and Eevee is inherently GPU-accelerated — no Cycles switch needed.

**Tech Stack:** Blender 4.x Python API (`bpy`), Pillow, numpy

---

## Background: Where Time Goes Today

| Phase | Time | % |
|---|---|---|
| Eevee render + PNG write (2048x2048, 8 TAA) | ~1000ms | 53% |
| Sollumz import (.ydd) | ~350ms | 18% |
| Post-processing (blocks GPU idle!) | ~250ms | 13% |
| Fix missing textures (DDS load) | ~100ms | 5% |
| IPC/thread overhead | ~100ms | 5% |
| Flat check, file copy, cleanup, misc | ~100ms | 5% |

## Key Technical Decisions

### Why NOT switch to Cycles for GPU?
Eevee Next is already GPU-accelerated by default — it's a rasterizer, not a ray tracer. Cycles would be **slower** for these simple product shots (ray tracing overhead for 3-point lighting on simple meshes). The AMD RX 9070 XT HIP backend is already configured (`blender_script.py:97`). No change needed.

### Why Blender-native WebP?
Blender 4.x supports `file_format = 'WEBP'` natively with `quality` (0-100, lossy) and `color_mode = 'RGBA'`. This eliminates:
- Writing a ~16MB uncompressed PNG to disk (2048x2048 RGBA @ 0 compression)
- Python reading that PNG back with Pillow
- Python resizing + saving as WebP
- Deleting the temp PNG

Instead, Blender renders at 1024x1024 and writes a ~50KB WebP directly. The Python side only needs to downscale 1024→512 (trivial).

### Why 1024 instead of 512 directly?
2x supersampling (1024→512) still provides excellent anti-aliasing for the final output. Going to 512 directly with TAA=1 would produce visible jaggies on thin geometry (watch bands, earring wires, etc.).

---

## Task 1: Reduce render resolution to 1024x1024

**Files:**
- Modify: `src/blender_script.py:52` (constant)

**Step 1: Change the RENDER_SIZE constant**

In `src/blender_script.py`, change line 52:

```python
# Before:
RENDER_SIZE = 2048           # 2K render, downscaled to 512 output (4x supersampling)

# After:
RENDER_SIZE = 1024           # 1K render, downscaled to 512 output (2x supersampling)
```

**Step 2: Verify no other code hard-codes 2048**

Search the codebase for any hard-coded references to `2048` in render-related contexts. The only reference should be the docstring in `image_processor.py` which we'll update in Task 3.

**Step 3: Run tests**

Run: `python -m pytest tests/ -v`
Expected: All 156+ tests pass (none depend on the render resolution constant).

**Step 4: Commit**

```bash
git add src/blender_script.py
git commit -m "perf: reduce Blender render resolution from 2048 to 1024 (2x SSAA is sufficient for 512px thumbnails)"
```

**Estimated savings:** ~400ms per item (4x fewer pixels to rasterize)

---

## Task 2: Reduce TAA samples from 8 to 1

**Files:**
- Modify: `src/blender_script.py:140`

**Step 1: Change TAA samples**

In `src/blender_script.py`, change line 140:

```python
# Before:
        eevee.taa_render_samples = 8       # minimal samples (product shots don't need AA)

# After:
        eevee.taa_render_samples = 1       # single sample — AA handled by 2x supersampling
```

**Step 2: Run tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass.

**Step 3: Commit**

```bash
git add src/blender_script.py
git commit -m "perf: reduce Eevee TAA samples from 8 to 1 (2x SSAA from 1024→512 provides sufficient AA)"
```

**Estimated savings:** ~300ms per item (7 fewer full-screen passes eliminated)

---

## Task 3: Native WebP output from Blender

This is the core optimization — eliminate the PNG intermediary entirely.

**Files:**
- Modify: `src/blender_script.py:128-131` (output format settings)
- Modify: `src/blender_script.py:614-616` (render filepath + call)
- Modify: `src/blender_script.py:618` (output file check)
- Modify: `src/blender_script.py:533` (result dict key name)
- Modify: `src/blender_script.py:692-694` (IPC protocol)
- Modify: `src/blender_renderer.py:599` (output path generation)
- Modify: `src/blender_renderer.py:602-607` (blender_item construction)
- Modify: `src/blender_renderer.py:863-938` (`_post_process_result`)
- Modify: `src/image_processor.py:109-133` (`convert_rendered_png` — keep but may become unused)
- Modify: `src/image_processor.py:135-154` (`is_image_empty` — optimize)

### Step 1: Change Blender output format from PNG to WebP

In `src/blender_script.py`, replace the output format block (lines 127-131):

```python
# Before:
    # Output format — minimal compression for speed
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.render.image_settings.compression = 0  # no compression — temp files, speed matters

# After:
    # Output format — WebP with transparency, high quality for downscale source
    scene.render.image_settings.file_format = 'WEBP'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.quality = 90     # lossy quality (final resize is lossless anyway)
```

Note: We remove `color_depth` (not applicable to WebP) and `compression` (replaced by `quality`).

### Step 2: Update render_item to use .webp extension

In `src/blender_script.py`, the `render_item()` function receives `output_png` from the orchestrator. Rename the field in the IPC protocol to `output_path` (it's no longer necessarily PNG). Update the result dict key similarly.

In `render_item()` (line 516+), rename all references from `output_png` to `output_path`:

```python
def render_item(item: dict, cam_obj: bpy.types.Object,
                work_base: str) -> dict:
    ydd_path = item["ydd_path"]
    dds_files = item.get("dds_files", [])
    output_path = item["output_path"]       # was "output_png"
    category = item.get("category", "")

    result = {"output_path": output_path, "success": False, "error": None}  # was "output_png"
    ...
        # Render
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        bpy.context.scene.render.filepath = output_path
        bpy.ops.render.render(write_still=True)

        if os.path.isfile(output_path):
            result["success"] = True
        ...
```

Also update `worker_main()` to use the new key name in the result line (line 744).

### Step 3: Update the orchestrator to send WebP paths

In `src/blender_renderer.py`, update `_worker_thread()` (line 599):

```python
# Before:
        output_png = os.path.join(tmp_dir, "renders", f"{catalog_key}.png")

# After:
        output_webp_render = os.path.join(tmp_dir, "renders", f"{catalog_key}.webp")
```

Update the `blender_item` dict construction (lines 602-607):

```python
# Before:
        blender_item = {
            "ydd_path": item["ydd_path"],
            "dds_files": item.get("dds_files", []),
            "output_png": output_png,
            "category": item.get("category", ""),
        }

# After:
        blender_item = {
            "ydd_path": item["ydd_path"],
            "dds_files": item.get("dds_files", []),
            "output_path": output_webp_render,    # Blender writes WebP directly
            "category": item.get("category", ""),
        }
```

### Step 4: Simplify _post_process_result — no more PNG→WebP conversion

The post-processing now only needs to:
1. Check if the Blender WebP is empty
2. Downscale from 1024→512 (since Blender renders at 1024)
3. Quality-check (flat texture strip detection)

Rewrite `_post_process_result()` in `src/blender_renderer.py`:

```python
def _post_process_result(bresult: dict, orig: dict) -> RenderResult:
    """Post-process a single Blender render result.

    Validates the render, downscales 1024→512 WebP, and checks quality.
    """
    output_render = bresult["output_path"]       # 1024x1024 WebP from Blender
    catalog_key = orig["catalog_key"]
    output_webp = orig["output_webp"]            # final 512x512 destination

    if not bresult["success"]:
        return RenderResult(
            catalog_key=catalog_key,
            output_png="",
            output_webp=output_webp,
            success=False,
            error=bresult.get("error", "Unknown Blender error"),
        )

    # Validate render isn't empty (all-transparent)
    if is_render_empty(output_render):
        logger.warning(
            "Render for %s produced empty image — falling back to flat",
            catalog_key,
        )
        return RenderResult(
            catalog_key=catalog_key,
            output_png="",
            output_webp=output_webp,
            success=False,
            error="Render produced empty/transparent image",
        )

    # Downscale 1024 → 512 and save as final WebP
    try:
        img = Image.open(output_render).convert("RGBA")
        if img.width != image_processor.CANVAS_SIZE or img.height != image_processor.CANVAS_SIZE:
            img = img.resize(
                (image_processor.CANVAS_SIZE, image_processor.CANVAS_SIZE),
                Image.LANCZOS,
            )
        out_dir = os.path.dirname(output_webp)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        img.save(
            output_webp, "WEBP",
            quality=image_processor.WEBP_QUALITY,
            method=image_processor.WEBP_METHOD,
        )
    except Exception as exc:
        return RenderResult(
            catalog_key=catalog_key,
            output_png="",
            output_webp=output_webp,
            success=False,
            error=f"Resize/save: {type(exc).__name__}: {exc}",
        )

    # Quality check: reject flat texture strips
    category = orig.get("category", "")
    if is_flat_texture_fallback(output_webp, category=category):
        logger.warning(
            "Render for %s looks like a flat texture strip — rejecting",
            catalog_key,
        )
        try:
            os.remove(output_webp)
        except OSError:
            pass
        return RenderResult(
            catalog_key=catalog_key,
            output_png="",
            output_webp=output_webp,
            success=False,
            error="Render produced flat texture strip, not 3D",
        )

    return RenderResult(
        catalog_key=catalog_key,
        output_png="",
        output_webp=output_webp,
        success=True,
    )
```

### Step 5: Update the RenderResult references

Update all places that reference `bresult["output_png"]` to `bresult["output_path"]` in `_worker_thread()` and `_post_process_result()`. Also update the `RenderResult` dataclass — the `output_png` field is now vestigial (always `""`) but keep it for API compat with catalog builder.

### Step 6: Update error paths in _worker_thread

Update lines 637-644 and 651-658 to use `output_webp_render` instead of `output_png`:

```python
                rr = RenderResult(
                    catalog_key=catalog_key,
                    output_png="",                    # no longer used
                    output_webp=item["output_webp"],
                    ...
                )
```

### Step 7: Run tests

Run: `python -m pytest tests/ -v`
Expected: All tests pass. The unit tests don't invoke Blender directly, so the IPC protocol change won't break them.

### Step 8: Commit

```bash
git add src/blender_script.py src/blender_renderer.py
git commit -m "perf: render to WebP natively in Blender, eliminating PNG intermediate step"
```

**Estimated savings:** ~150-200ms per item (no 16MB PNG write + no Python PNG read/decode + no temp file I/O)

---

## Task 4: Optimize is_image_empty with numpy

**Files:**
- Modify: `src/image_processor.py:135-154`
- Modify: `src/blender_renderer.py` (add new `is_render_empty` function)

### Step 1: Write a fast numpy-based empty check

The current `is_image_empty()` uses a pure-Python generator expression over 4 million bytes:
```python
visible = sum(1 for p in alpha.tobytes() if p > 0)  # ~150ms
```

Replace with numpy in a new function in `blender_renderer.py` (since it already imports numpy):

```python
def is_render_empty(image_path: str, threshold: int = 100) -> bool:
    """Check if a rendered image is effectively empty (fast numpy version).

    Args:
        image_path: Path to the image file.
        threshold: Minimum number of non-transparent pixels to consider
                   the image non-empty.

    Returns:
        True if the image has fewer than *threshold* visible pixels.
    """
    try:
        img = Image.open(image_path).convert("RGBA")
        alpha = np.array(img.getchannel("A"))
        visible = np.count_nonzero(alpha)
        return visible < threshold
    except Exception:
        return True
```

This is a one-liner numpy operation: `np.count_nonzero()` on a 1024x1024 uint8 array takes <1ms vs ~150ms for the Python loop.

### Step 2: Update _post_process_result to use the new function

Already done in Task 3 Step 4 — we call `is_render_empty()` instead of `image_processor.is_image_empty()`.

### Step 3: Keep the old is_image_empty for backward compat

The old function in `image_processor.py` may be used elsewhere (flat texture path). Keep it but also optimize it:

```python
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
```

### Step 4: Run tests

Run: `python -m pytest tests/ -v`
Expected: All tests pass.

### Step 5: Commit

```bash
git add src/image_processor.py src/blender_renderer.py
git commit -m "perf: replace pure-Python is_image_empty with numpy (150ms → <1ms)"
```

**Estimated savings:** ~150ms per item

---

## Task 5: Update docstrings and comments

**Files:**
- Modify: `src/blender_script.py:1-8` (module docstring references 512x512 PNG)
- Modify: `src/image_processor.py:1-8` (module docstring references 2048x2048)
- Modify: `src/image_processor.py:109-113` (convert_rendered_png docstring)

### Step 1: Update stale comments

Update the module docstring in `blender_script.py` to say "1024x1024 WebP" instead of "512x512 transparent PNG".

Update the module docstring in `image_processor.py` to remove the "typically 2048x2048" reference.

### Step 2: Commit

```bash
git add src/blender_script.py src/image_processor.py
git commit -m "docs: update comments to reflect new render resolution and format"
```

---

## Task 6: End-to-end smoke test

**Files:** None (manual testing)

### Step 1: Run a small batch render

Run the full pipeline on a small subset (e.g. 10-20 items) with `--render-3d` to verify:
1. Blender produces valid WebP files at 1024x1024
2. Post-processing correctly downscales to 512x512
3. Empty image detection still works
4. Quality check (flat texture rejection) still works
5. Fallback to flat texture still triggers for invisible meshes

### Step 2: Compare output quality

Compare a few renders before/after to verify 2x SSAA at 1024px + TAA=1 looks acceptable vs the old 4x SSAA at 2048px + TAA=8.

### Step 3: Measure throughput

Time the rendering phase and compute img/sec. Target: ~9-10 img/sec with 8 workers.

---

## Projected Impact Summary

| Optimization | Savings | Cumulative per-item |
|---|---|---|
| Baseline | — | 1.9s |
| 1024px render (Task 1) | ~400ms | 1.5s |
| TAA 1 (Task 2) | ~300ms | 1.2s |
| Native WebP output (Task 3) | ~150ms | 1.05s |
| numpy empty check (Task 4) | ~150ms | 0.9s |
| **Total with 8 workers** | | **~8.9 img/sec** |

## What We Explicitly Do NOT Change

- **GPU backend**: Already AMD HIP auto-detected. Eevee is inherently GPU-accelerated. No Cycles.
- **Worker count**: 8 persistent Blender instances is already well-tuned.
- **Sollumz import**: ~350ms is inherent to the addon, no optimization possible from our side.
- **IPC protocol**: JSON-over-stdin/stdout is fast enough (~1ms overhead).
- **Async post-processing thread pool**: The savings from Tasks 3+4 make this unnecessary — post-processing drops from ~250ms to ~30ms, so it no longer blocks the GPU meaningfully.
