"""Blender 3D Renderer Orchestrator

Connects our Python pipeline to Blender headless rendering:
  1. Pre-extract DDS textures in parallel (ProcessPoolExecutor)
  2. Feed items to persistent Blender worker processes via stdin/stdout IPC
  3. Post-process: validate, downscale 1024→512 WebP, quality-check
"""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial
from io import BytesIO
from dataclasses import dataclass

import numpy as np
from PIL import Image

from src import rsc7, ytd_parser, dds_builder, image_processor
from src.render_quality import is_flat_texture_fallback

logger = logging.getLogger(__name__)

# Path to the blender_script.py relative to this file
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BLENDER_SCRIPT = os.path.join(_SCRIPT_DIR, "blender_script.py")

DEFAULT_BATCH_SIZE = 100   # kept for API compat, unused by worker pool
MIN_RETRY_BATCH_SIZE = 10  # kept for API compat
DEFAULT_PARALLEL_BLENDERS = 8

# Per-item timeout for Blender rendering (seconds)
_ITEM_TIMEOUT = 120

# Maximum crash restarts per worker before giving up
_MAX_WORKER_CRASHES = 3


@dataclass
class RenderResult:
    """Result of rendering a single item."""
    catalog_key: str
    output_png: str
    output_webp: str
    success: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# Blender auto-detection
# ---------------------------------------------------------------------------

def find_blender() -> str | None:
    """Try to auto-detect the Blender executable path.

    Checks common installation locations on Windows.

    Returns:
        Path to the blender executable, or None.
    """
    # Check if blender is on PATH
    blender_on_path = shutil.which("blender")
    if blender_on_path:
        return blender_on_path

    # Common Windows install locations
    common_paths = [
        r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
    ]
    for path in common_paths:
        if os.path.isfile(path):
            return path

    return None


# ---------------------------------------------------------------------------
# DDS extraction
# ---------------------------------------------------------------------------

def _find_all_variant_ytds(ytd_path: str) -> list[str]:
    """Find all sibling variant .ytd files for the same drawable.

    Given ``..._diff_015_a_uni.ytd``, returns paths for ``_a_``, ``_b_``,
    ``_c_``, etc.  The model's default material may reference any variant's
    texture name, so we need to extract them all.
    """
    directory = os.path.dirname(ytd_path)
    filename = os.path.basename(ytd_path)

    # Build prefix: everything up to and including the drawable ID + "_"
    # e.g. "mp_f_freemode_01_rhclothing^accs_diff_015_"
    import re
    match = re.match(r'^(.+_diff_\d+_)[a-z]_', filename, re.IGNORECASE)
    if not match:
        return [ytd_path]

    prefix = match.group(1).lower()

    results = []
    try:
        for entry in os.scandir(directory):
            if entry.is_file() and entry.name.lower().startswith(prefix) and entry.name.lower().endswith('.ytd'):
                results.append(entry.path)
    except OSError:
        return [ytd_path]

    return results if results else [ytd_path]


def extract_dds_for_ydd(ytd_path: str, dds_output_dir: str) -> list[str]:
    """Extract textures from a .ytd and all its sibling variants as DDS files.

    The model's default material may reference a texture name from any
    variant (``_a_``, ``_b_``, ``_c_``, etc.), not just the base ``_a_``
    variant.  We extract all of them so Sollumz can find whichever name
    it needs.

    Args:
        ytd_path: Path to the base ``_a_`` .ytd file.
        dds_output_dir: Directory to write DDS files into.

    Returns:
        List of paths to the created DDS files.
    """
    os.makedirs(dds_output_dir, exist_ok=True)

    all_ytds = _find_all_variant_ytds(ytd_path)
    logger.debug("Extracting DDS from %d variant YTD files", len(all_ytds))

    dds_paths = []
    seen_names: set[str] = set()

    for variant_ytd in all_ytds:
        try:
            resource = rsc7.parse_rsc7(variant_ytd)
            textures = ytd_parser.parse_texture_dictionary(
                resource.virtual_data, resource.physical_data
            )
        except Exception as exc:
            logger.debug("Skipping variant %s: %s",
                         os.path.basename(variant_ytd), exc)
            continue

        for tex in textures:
            if not tex.raw_data:
                continue
            safe_name = tex.name.replace("/", "_").replace("\\", "_")
            if not safe_name:
                safe_name = f"texture_{len(dds_paths)}"
            # Skip duplicates (same texture name from different variants)
            if safe_name.lower() in seen_names:
                continue
            seen_names.add(safe_name.lower())

            dds_bytes = dds_builder.build_dds(tex)
            dds_path = os.path.join(dds_output_dir, f"{safe_name}.dds")
            with open(dds_path, "wb") as f:
                f.write(dds_bytes)
            dds_paths.append(dds_path)
            logger.debug("Extracted DDS: %s (%d bytes)", dds_path, len(dds_bytes))

    return dds_paths


def fix_green_tint_dds(dds_paths: list[str]) -> int:
    """Detect green tint-mask hair textures and remap to natural brown.

    GTA V hair uses a special shader where the raw diffuse is a green
    gradient remapped at runtime.  Without that shader, hair renders green.
    This detects green-dominant DDS textures using Pillow and overwrites
    them with a brown-tinted version.

    Returns the number of files corrected.
    """
    fixed = 0
    for dds_path in dds_paths:
        try:
            img = Image.open(dds_path)
            img_rgba = img.convert("RGBA")
        except Exception:
            continue

        pixels = np.array(img_rgba, dtype=np.float32)
        # Only consider non-transparent pixels with some brightness
        alpha = pixels[:, :, 3]
        rgb_max = pixels[:, :, :3].max(axis=2)
        mask = (alpha > 25) & (rgb_max > 12)
        if mask.sum() < 100:
            continue

        visible = pixels[mask][:, :3]
        avg_r = visible[:, 0].mean()
        avg_g = visible[:, 1].mean()
        avg_b = visible[:, 2].mean()

        # Green-dominant = tint mask
        if not (avg_g > avg_r * 1.4 and avg_g > avg_b * 1.4):
            continue

        # Remap: use green channel as luminance, tint to warm brown
        lum = pixels[:, :, 1].astype(np.float32)
        pixels[:, :, 0] = np.clip(lum * (180 / 255), 0, 255)   # R
        pixels[:, :, 1] = np.clip(lum * (130 / 255), 0, 255)   # G
        pixels[:, :, 2] = np.clip(lum * (90 / 255), 0, 255)    # B
        # Alpha stays untouched

        result = Image.fromarray(pixels.astype(np.uint8), "RGBA")
        # Save as PNG next to the DDS (Blender can load PNG fine)
        png_path = dds_path.rsplit(".", 1)[0] + ".png"
        result.save(png_path)

        # Replace the DDS path with the PNG path in-place
        idx = dds_paths.index(dds_path)
        dds_paths[idx] = png_path

        fixed += 1
        logger.info("Remapped green tint mask: %s (avg RGB: %.0f, %.0f, %.0f)",
                     os.path.basename(dds_path), avg_r, avg_g, avg_b)

    if fixed:
        logger.info("Fixed %d green hair tint mask(s) -> brown", fixed)
    return fixed


# ---------------------------------------------------------------------------
# Parallel DDS pre-extraction (for persistent worker pool)
# ---------------------------------------------------------------------------

def _pre_extract_dds_single(item: dict, tmp_dir: str,
                            green_hair_fix: bool = True) -> dict:
    """Pre-extract DDS textures for a single item.

    This is a top-level function (picklable for ProcessPoolExecutor) that
    performs ONE RSC7/YTD parse for both placeholder detection AND DDS
    extraction — eliminating the double-parse in the old _render_chunk().

    Args:
        item: Work item dict with catalog_key, ytd_path, ydd_path,
              output_webp, category, etc.
        tmp_dir: Base temporary directory for DDS extraction.
        green_hair_fix: Whether to apply green hair tint fix.

    Returns:
        Augmented copy of the item dict with added keys:
          - dds_files: list[str] — extracted DDS paths
          - dds_dir: str — directory containing the DDS files
          - is_placeholder: bool — True if the texture is a placeholder
          - pre_extract_error: str | None — error message if extraction failed
    """
    result = dict(item)
    result["dds_files"] = []
    result["dds_dir"] = ""
    result["is_placeholder"] = False
    result["pre_extract_error"] = None

    catalog_key = item["catalog_key"]
    ytd_path = item["ytd_path"]
    category = item.get("category", "")

    # Single RSC7/YTD parse for both placeholder check + DDS extraction
    try:
        resource = rsc7.parse_rsc7(ytd_path)
        textures = ytd_parser.parse_texture_dictionary(
            resource.virtual_data, resource.physical_data
        )
    except Exception as exc:
        result["pre_extract_error"] = (
            f"RSC7/YTD parse: {type(exc).__name__}: {exc}"
        )
        return result

    # Placeholder detection — check the diffuse texture
    try:
        diff_tex = ytd_parser.select_diffuse_texture(textures)
        if diff_tex is not None:
            dds_bytes = dds_builder.build_dds(diff_tex)
            img = Image.open(BytesIO(dds_bytes)).convert("RGBA")
            if image_processor._is_placeholder(img):
                result["is_placeholder"] = True
                return result
    except Exception:
        pass  # Not a placeholder or detection error — continue with extraction

    # DDS extraction for all variant YTDs
    dds_dir = os.path.join(tmp_dir, "dds", catalog_key)
    try:
        dds_files = extract_dds_for_ydd(ytd_path, dds_dir)
        # Fix green tint masks for hair textures
        if green_hair_fix and category == "hair" and dds_files:
            fix_green_tint_dds(dds_files)
        result["dds_files"] = dds_files
        result["dds_dir"] = dds_dir
    except Exception as exc:
        result["pre_extract_error"] = (
            f"DDS extraction: {type(exc).__name__}: {exc}"
        )

    return result


# ---------------------------------------------------------------------------
# Persistent Blender Worker
# ---------------------------------------------------------------------------

class BlenderCrashError(Exception):
    """Raised when a Blender worker process has died unexpectedly."""


class BlenderWorker:
    """A persistent Blender subprocess communicating via stdin/stdout IPC."""

    def __init__(self, worker_id: int, blender_path: str,
                 render_config: dict | None = None):
        self.worker_id = worker_id
        self.blender_path = blender_path
        self.render_config = render_config or {}
        self.process: subprocess.Popen | None = None
        self._stderr_thread: threading.Thread | None = None

    def start(self) -> bool:
        """Launch the Blender worker process and wait for READY.

        Returns True if the worker started successfully.
        """
        cmd = [
            self.blender_path,
            "-b",                   # headless
            "-P", BLENDER_SCRIPT,   # Python script
            "--",                   # separator
            "--worker",             # worker mode flag
        ]

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW

        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                creationflags=creation_flags,
            )
        except FileNotFoundError:
            logger.error("Worker %d: Blender not found: %s",
                         self.worker_id, self.blender_path)
            return False

        # Drain stderr in a daemon thread to prevent pipe buffer deadlock
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True
        )
        self._stderr_thread.start()

        # Wait for READY signal (timeout: 60s for Blender startup)
        if not self._wait_for_ready(timeout=60):
            logger.error("Worker %d: did not receive READY signal", self.worker_id)
            self.shutdown()
            return False

        # Send render config if provided
        if self.render_config:
            self._send_config(self.render_config)

        logger.info("Worker %d: started (pid=%d)", self.worker_id,
                     self.process.pid)
        return True

    def _drain_stderr(self) -> None:
        """Read stderr lines and log them (prevents pipe buffer deadlock)."""
        proc = self.process
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                line = line.rstrip("\n")
                if line:
                    logger.debug("[Worker %d stderr] %s", self.worker_id, line)
        except (ValueError, OSError):
            pass  # pipe closed

    def _send_config(self, config: dict) -> None:
        """Send a CONFIG line to the Blender worker."""
        proc = self.process
        if proc is None or proc.stdin is None:
            return
        try:
            line = f"CONFIG:{json.dumps(config, separators=(',', ':'))}\n"
            proc.stdin.write(line)
            proc.stdin.flush()
            # Read CONFIG_OK or CONFIG_ERR response
            resp = self._readline_with_timeout(10)
            if resp and resp.strip().startswith("CONFIG_ERR"):
                logger.warning("Worker %d: config error: %s",
                               self.worker_id, resp.strip())
        except (BrokenPipeError, OSError) as exc:
            logger.warning("Worker %d: config send failed: %s",
                           self.worker_id, exc)

    def _wait_for_ready(self, timeout: float) -> bool:
        """Read stdout lines until READY is found, or timeout."""
        deadline = time.monotonic() + timeout
        proc = self.process
        if proc is None or proc.stdout is None:
            return False

        while time.monotonic() < deadline:
            # Use a thread to do the blocking readline with a timeout
            result_container: list[str | None] = [None]

            def _read() -> None:
                try:
                    result_container[0] = proc.stdout.readline()  # type: ignore[union-attr]
                except (ValueError, OSError):
                    result_container[0] = None

            reader = threading.Thread(target=_read, daemon=True)
            reader.start()
            remaining = deadline - time.monotonic()
            reader.join(timeout=max(remaining, 0.1))

            if reader.is_alive():
                # Still blocking — check if process died
                if proc.poll() is not None:
                    return False
                continue

            line = result_container[0]
            if line is None or line == "":
                # EOF — process exited
                return False

            line = line.rstrip("\n")
            if line == "READY":
                return True
            # Other startup output — ignore

        return False

    def render_item(self, item: dict) -> dict:
        """Send a single item to the Blender worker and return the result.

        Args:
            item: Dict with keys ydd_path, dds_files, output_path, category, etc.

        Returns:
            Dict with keys output_path, success, error.

        Raises:
            BlenderCrashError: If the worker process has died.
            TimeoutError: If the item takes longer than _ITEM_TIMEOUT.
        """
        proc = self.process
        if proc is None or proc.poll() is not None:
            raise BlenderCrashError(
                f"Worker {self.worker_id}: process not running"
            )

        # Send the item as a single JSON line
        json_line = json.dumps(item, separators=(",", ":")) + "\n"
        try:
            proc.stdin.write(json_line)  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
        except (BrokenPipeError, OSError) as exc:
            raise BlenderCrashError(
                f"Worker {self.worker_id}: stdin write failed: {exc}"
            ) from exc

        # Read stdout until we get a RESULT: line
        deadline = time.monotonic() + _ITEM_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Worker {self.worker_id}: item timed out after "
                    f"{_ITEM_TIMEOUT}s"
                )

            line = self._readline_with_timeout(remaining)

            if line is None or line == "":
                # EOF — Blender crashed
                raise BlenderCrashError(
                    f"Worker {self.worker_id}: stdout EOF (crash)"
                )

            line = line.rstrip("\n")
            if line.startswith("RESULT:"):
                payload = line[7:]  # strip "RESULT:" prefix
                try:
                    return json.loads(payload)
                except json.JSONDecodeError as exc:
                    return {
                        "output_path": item.get("output_path", ""),
                        "success": False,
                        "error": f"Worker result JSON error: {exc}",
                    }
            # Any other output is logging — ignore

    def _readline_with_timeout(self, timeout: float) -> str | None:
        """Read one line from stdout with a timeout (Windows-compatible)."""
        proc = self.process
        if proc is None or proc.stdout is None:
            return None

        result_container: list[str | None] = [None]

        def _read() -> None:
            try:
                result_container[0] = proc.stdout.readline()  # type: ignore[union-attr]
            except (ValueError, OSError):
                result_container[0] = None

        reader = threading.Thread(target=_read, daemon=True)
        reader.start()
        reader.join(timeout=timeout)

        if reader.is_alive():
            # Timed out — check if process died
            if proc.poll() is not None:
                return None
            # Still alive but blocked — return None to trigger timeout
            return None

        return result_container[0]

    def shutdown(self) -> None:
        """Gracefully shut down the worker by closing stdin."""
        proc = self.process
        if proc is None:
            return

        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except OSError:
            pass

        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Worker %d: killing unresponsive process",
                           self.worker_id)
            proc.kill()
            proc.wait(timeout=5)

        self.process = None
        logger.debug("Worker %d: shut down", self.worker_id)

    def restart(self) -> bool:
        """Kill the current process and start a new one.

        Returns True if restart succeeded.
        """
        logger.warning("Worker %d: restarting...", self.worker_id)
        proc = self.process
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            self.process = None

        return self.start()

    def is_alive(self) -> bool:
        """Check if the worker process is still running."""
        proc = self.process
        return proc is not None and proc.poll() is None


# ---------------------------------------------------------------------------
# Worker thread + pool orchestration
# ---------------------------------------------------------------------------

def _worker_thread(
    worker: BlenderWorker,
    work_queue: queue.Queue,
    results: list,
    results_lock: threading.Lock,
    tmp_dir: str,
    output_size: int = 0,
    webp_quality: int = 0,
) -> None:
    """Consumer thread: pulls items from the queue and feeds them to a BlenderWorker.

    Args:
        worker: The BlenderWorker to send items to.
        work_queue: Thread-safe queue of pre-extracted item dicts.
        results: Shared results list (append under lock).
        results_lock: Lock protecting the results list.
        tmp_dir: Temp directory for render output PNGs.
        output_size: Final output image size (0 = module default).
        webp_quality: WebP quality 1-100 (0 = module default).
    """
    crash_count = 0

    while True:
        try:
            item = work_queue.get_nowait()
        except queue.Empty:
            break

        catalog_key = item["catalog_key"]
        output_webp_render = os.path.join(tmp_dir, "renders", f"{catalog_key}.webp")

        # Build Blender item (only fields the Blender script needs)
        blender_item = {
            "ydd_path": item["ydd_path"],
            "dds_files": item.get("dds_files", []),
            "output_path": output_webp_render,    # Blender writes WebP directly
            "category": item.get("category", ""),
        }

        # Props: rotation
        category = item.get("category", "")
        if category.startswith("p_"):
            blender_item["rotation_steps"] = [[-math.pi, -math.pi / 2, 0]]
            blender_item["camera_elevation"] = 0

        # Fallback base body mesh
        fallback = item.get("fallback_ydd_path")
        if fallback:
            blender_item["fallback_ydd"] = fallback

        try:
            bresult = worker.render_item(blender_item)
        except BlenderCrashError:
            crash_count += 1
            logger.warning("Worker %d: crash #%d while rendering %s",
                           worker.worker_id, crash_count, catalog_key)

            if crash_count <= _MAX_WORKER_CRASHES:
                # Re-queue the item and restart the worker
                work_queue.put(item)
                if not worker.restart():
                    logger.error("Worker %d: restart failed — stopping thread",
                                 worker.worker_id)
                    break
            else:
                logger.error("Worker %d: too many crashes — recording failure",
                             worker.worker_id)
                rr = RenderResult(
                    catalog_key=catalog_key,
                    output_png="",
                    output_webp=item["output_webp"],
                    success=False,
                    error="Blender worker crashed too many times",
                )
                with results_lock:
                    results.append(rr)
                break
            continue
        except TimeoutError:
            logger.warning("Worker %d: item %s timed out",
                           worker.worker_id, catalog_key)
            rr = RenderResult(
                catalog_key=catalog_key,
                output_png="",
                output_webp=item["output_webp"],
                success=False,
                error=f"Render timed out after {_ITEM_TIMEOUT}s",
            )
            with results_lock:
                results.append(rr)
            # Restart worker after timeout (it may be stuck)
            if not worker.restart():
                logger.error("Worker %d: restart after timeout failed",
                             worker.worker_id)
                break
            continue

        # Post-process: validate, render→WebP, quality check
        rr = _post_process_result(bresult, item,
                                  output_size=output_size,
                                  webp_quality=webp_quality)
        with results_lock:
            results.append(rr)

        work_queue.task_done()


# ---------------------------------------------------------------------------
# Batch rendering
# ---------------------------------------------------------------------------

def render_batch(
    items: list[dict],
    blender_path: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    parallel: int = DEFAULT_PARALLEL_BLENDERS,
    render_size: int = 0,
    taa_samples: int = 0,
    output_size: int = 0,
    webp_quality: int = 0,
    green_hair_fix: bool = True,
) -> list[RenderResult]:
    """Render a batch of items via persistent Blender worker processes.

    Two-phase pipeline:
      Phase 1: Parallel DDS pre-extraction (ProcessPoolExecutor)
      Phase 2: Persistent Blender worker pool (N Popen processes with
               stdin/stdout IPC, consumed by N threads from a shared queue)

    Each item dict must contain:
      - catalog_key: str
      - ytd_path: str (path to .ytd file)
      - ydd_path: str (path to .ydd file)
      - output_webp: str (final .webp output path)

    Args:
        items: List of work item dicts.
        blender_path: Path to the Blender executable.
        batch_size: Deprecated, kept for API compatibility.
        parallel: Number of persistent Blender worker processes.
        render_size: Blender render resolution (default: blender_script.RENDER_SIZE).
        taa_samples: TAA render samples (default: blender_script.TAA_SAMPLES).
        output_size: Final output image size (default: image_processor.CANVAS_SIZE).
        webp_quality: WebP quality 1-100 (default: image_processor.WEBP_QUALITY).
        green_hair_fix: Whether to apply green hair tint fix (default: True).

    Returns a list of RenderResult for each item.
    """
    # Resolve effective settings (0 = use module defaults)
    eff_output_size = output_size or image_processor.CANVAS_SIZE
    eff_webp_quality = webp_quality or image_processor.WEBP_QUALITY
    eff_webp_method = image_processor.WEBP_METHOD

    # Build config for Blender workers
    render_config: dict = {}
    if render_size:
        render_config["render_size"] = render_size
    if taa_samples:
        render_config["taa_samples"] = taa_samples
    render_config["green_hair_fix"] = green_hair_fix

    all_results: list[RenderResult] = []
    tmp_dir = tempfile.mkdtemp(prefix="clothing_pool_")

    try:
        # ==================================================================
        # Phase 1: Parallel DDS pre-extraction
        # ==================================================================
        print(f"  Phase 1: Pre-extracting DDS for {len(items)} items...")

        dds_workers = min(os.cpu_count() or 4, len(items))
        extracted_items: list[dict] = []
        extract_fn = partial(_pre_extract_dds_single, tmp_dir=tmp_dir,
                             green_hair_fix=green_hair_fix)

        with ProcessPoolExecutor(max_workers=dds_workers) as pool:
            futures = {
                pool.submit(extract_fn, item): item
                for item in items
            }
            for future in as_completed(futures):
                orig_item = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    # Entire extraction blew up
                    all_results.append(RenderResult(
                        catalog_key=orig_item["catalog_key"],
                        output_png="",
                        output_webp=orig_item["output_webp"],
                        success=False,
                        error=f"DDS pre-extract: {type(exc).__name__}: {exc}",
                    ))
                    continue

                # Handle placeholders immediately
                if result.get("is_placeholder"):
                    logger.debug("Placeholder texture for %s",
                                 result["catalog_key"])
                    output_webp = result["output_webp"]
                    out_dir = os.path.dirname(output_webp)
                    if out_dir:
                        os.makedirs(out_dir, exist_ok=True)
                    canvas = Image.new(
                        "RGBA",
                        (eff_output_size, eff_output_size),
                        (0, 0, 0, 0),
                    )
                    canvas.save(
                        output_webp, "WEBP",
                        quality=eff_webp_quality,
                        method=eff_webp_method,
                    )
                    all_results.append(RenderResult(
                        catalog_key=result["catalog_key"],
                        output_png="",
                        output_webp=output_webp,
                        success=True,
                    ))
                    continue

                # Handle extraction errors
                if result.get("pre_extract_error"):
                    all_results.append(RenderResult(
                        catalog_key=result["catalog_key"],
                        output_png="",
                        output_webp=result["output_webp"],
                        success=False,
                        error=result["pre_extract_error"],
                    ))
                    continue

                extracted_items.append(result)

        placeholders = sum(1 for r in all_results if r.success)
        errors = sum(1 for r in all_results if not r.success)
        print(f"    {len(extracted_items)} ready for 3D, "
              f"{placeholders} placeholders, {errors} errors")

        if not extracted_items:
            return all_results

        # ==================================================================
        # Phase 2: Persistent Blender worker pool
        # ==================================================================
        print(f"  Phase 2: Starting {parallel} persistent Blender worker(s)...")

        # Create render output dir
        os.makedirs(os.path.join(tmp_dir, "renders"), exist_ok=True)

        # Start workers
        workers: list[BlenderWorker] = []
        for i in range(parallel):
            w = BlenderWorker(i, blender_path, render_config=render_config)
            if w.start():
                workers.append(w)
            else:
                logger.warning("Worker %d failed to start", i)

        if not workers:
            logger.error("All Blender workers failed to start")
            for item in extracted_items:
                all_results.append(RenderResult(
                    catalog_key=item["catalog_key"],
                    output_png="",
                    output_webp=item["output_webp"],
                    success=False,
                    error="All Blender workers failed to start",
                ))
            return all_results

        print(f"    {len(workers)} worker(s) ready, "
              f"feeding {len(extracted_items)} items...")

        # Fill work queue
        work_queue: queue.Queue = queue.Queue()
        for item in extracted_items:
            work_queue.put(item)

        # Shared results list + lock
        pool_results: list[RenderResult] = []
        results_lock = threading.Lock()

        # Start consumer threads (one per worker)
        threads: list[threading.Thread] = []
        for w in workers:
            t = threading.Thread(
                target=_worker_thread,
                args=(w, work_queue, pool_results, results_lock, tmp_dir,
                      eff_output_size, eff_webp_quality),
                daemon=True,
            )
            t.start()
            threads.append(t)

        # Wait for all threads to finish
        for t in threads:
            t.join()

        # Shutdown all workers
        for w in workers:
            w.shutdown()

        all_results.extend(pool_results)

        succeeded = sum(1 for r in pool_results if r.success)
        print(f"    3D rendering complete: {succeeded}/{len(extracted_items)} "
              f"succeeded")

    finally:
        # Clean up temp directory
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    return all_results


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
        visible = int(np.count_nonzero(alpha))
        return visible < threshold
    except Exception:
        return True


def _post_process_result(bresult: dict, orig: dict,
                         output_size: int = 0,
                         webp_quality: int = 0) -> RenderResult:
    """Post-process a single Blender render result.

    Validates the render, downscales to output_size WebP, and checks quality.

    Args:
        bresult: Dict from Blender with keys: output_path, success, error.
        orig: Original item dict with keys: catalog_key, output_webp, category.
        output_size: Final output image size (0 = module default).
        webp_quality: WebP quality 1-100 (0 = module default).

    Returns:
        A RenderResult for this item.
    """
    eff_size = output_size or image_processor.CANVAS_SIZE
    eff_quality = webp_quality or image_processor.WEBP_QUALITY
    eff_method = image_processor.WEBP_METHOD

    output_render = bresult["output_path"]
    catalog_key = orig["catalog_key"]
    output_webp = orig["output_webp"]

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

    # Downscale render -> output_size and save as final WebP
    try:
        img = Image.open(output_render).convert("RGBA")
        if img.width != eff_size or img.height != eff_size:
            img = img.resize(
                (eff_size, eff_size),
                Image.LANCZOS,
            )
        out_dir = os.path.dirname(output_webp)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        img.save(
            output_webp, "WEBP",
            quality=eff_quality,
            method=eff_method,
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


