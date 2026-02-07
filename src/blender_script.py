"""Blender-side Render Script

Runs inside Blender via:
    blender -b -P src/blender_script.py -- manifest.json results.json

Reads a manifest of .ydd/.dds items, imports each via Sollumz, sets up
camera and lighting, renders a 1024x1024 transparent WebP for each item,
and writes a results JSON file back.

Requires:
  - Blender 4.x with Eevee Next
  - Sollumz addon installed and enabled
"""

import json
import math
import os
import shutil
import sys
import tempfile
import traceback

import bpy                       # type: ignore[import-untyped]
import addon_utils               # type: ignore[import-untyped]
from mathutils import Vector     # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Enable Sollumz addon
# ---------------------------------------------------------------------------

_SOLLUMZ_MODULES = [
    "bl_ext.blender_org.sollumz_dev",
    "bl_ext.blender_org.sollumz",
    "SollumzPlugin",
]

for _mod_name in _SOLLUMZ_MODULES:
    try:
        addon_utils.enable(_mod_name)
        print(f"Enabled Sollumz addon: {_mod_name}")
        break
    except Exception:
        continue
else:
    print("WARNING: Could not enable Sollumz addon — imports may fail",
          file=sys.stderr)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RENDER_SIZE = 1024           # 1K render, downscaled to 512 output (2x supersampling)
TAA_SAMPLES = 1              # TAA render samples (overridable via manifest/worker config)
CAMERA_ELEVATION_DEG = 10    # slight top-down angle
PADDING_FACTOR = 1.15        # 15% padding around bounding box
GREEN_HAIR_FIX = True        # Whether to apply green hair tint fix


# ---------------------------------------------------------------------------
# Scene helpers
# ---------------------------------------------------------------------------

def clear_scene() -> None:
    """Delete all objects, meshes, materials, images, and collections."""
    # Deselect everything first
    bpy.ops.object.select_all(action='DESELECT')

    # Select and delete all objects
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # Purge orphan data
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for mat in list(bpy.data.materials):
        if mat.users == 0:
            bpy.data.materials.remove(mat)
    for img in list(bpy.data.images):
        if img.users == 0:
            bpy.data.images.remove(img)

    # Remove non-default collections
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)


def setup_render_settings() -> None:
    """Configure Eevee renderer for fast GPU-accelerated product-shot rendering."""
    scene = bpy.context.scene

    # --- Enable GPU rendering ---
    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons.get('cycles')
    # Try to enable HIP (AMD) or CUDA (NVIDIA) compute device
    try:
        cprefs = bpy.context.preferences.system
        # Try HIP first (AMD RX 9070 XT), then CUDA, then OPENCL
        for backend in ('HIP', 'CUDA', 'OPENCL'):
            try:
                cprefs.compute_device_type = backend
                bpy.context.preferences.system.compute_device_type = backend
                print(f"GPU compute backend set to: {backend}")
                break
            except Exception:
                continue
        # Enable all available GPU devices
        try:
            bpy.ops.preferences.addon_enable(module='cycles')
        except Exception:
            pass
        # Activate all devices
        if hasattr(cprefs, 'devices'):
            for device in cprefs.devices:
                device.use = True
                print(f"  Enabled device: {device.name} ({device.type})")
    except Exception as exc:
        print(f"GPU setup note: {exc}")

    # Renderer — Eevee Next is already GPU-accelerated by default
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.render.resolution_x = RENDER_SIZE
    scene.render.resolution_y = RENDER_SIZE
    scene.render.resolution_percentage = 100

    # Transparent background
    scene.render.film_transparent = True

    # Output format — WebP with transparency, high quality for downscale source
    scene.render.image_settings.file_format = 'WEBP'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.quality = 90     # lossy quality (final resize is lossless anyway)

    # --- Speed optimizations ---
    scene.render.use_simplify = True
    scene.render.simplify_subdivision = 0  # no subdivision

    # Eevee-specific speed settings
    eevee = scene.eevee
    if hasattr(eevee, 'taa_render_samples'):
        eevee.taa_render_samples = TAA_SAMPLES
    if hasattr(eevee, 'use_gtao'):
        eevee.use_gtao = False             # disable ambient occlusion
    if hasattr(eevee, 'use_bloom'):
        eevee.use_bloom = False            # disable bloom
    if hasattr(eevee, 'use_ssr'):
        eevee.use_ssr = False              # disable screen-space reflections
    if hasattr(eevee, 'use_motion_blur'):
        eevee.use_motion_blur = False
    if hasattr(eevee, 'shadow_cascade_size'):
        eevee.shadow_cascade_size = '512'  # smaller shadow maps
    if hasattr(eevee, 'shadow_cube_size'):
        eevee.shadow_cube_size = '256'


def setup_lighting() -> None:
    """Create a 3-point studio lighting setup."""
    # Key light — main light, slightly above and to the right
    _add_light("KeyLight", 'AREA', energy=150, size=3,
               location=(2.5, -2.5, 3.5))

    # Fill light — softer, from the left side
    _add_light("FillLight", 'AREA', energy=60, size=4,
               location=(-3, -1.5, 2))

    # Rim light — behind and above, for edge definition
    _add_light("RimLight", 'AREA', energy=100, size=2,
               location=(0, 3, 4))


def _add_light(name: str, light_type: str, energy: float,
               size: float, location: tuple) -> None:
    """Add a light to the scene, aimed at the origin."""
    light_data = bpy.data.lights.new(name=name, type=light_type)
    light_data.energy = energy
    if hasattr(light_data, 'size'):
        light_data.size = size

    light_obj = bpy.data.objects.new(name, light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    light_obj.location = location

    # Point at origin
    direction = Vector((0, 0, 0)) - Vector(location)
    rot = direction.to_track_quat('-Z', 'Y')
    light_obj.rotation_euler = rot.to_euler()


def setup_camera() -> bpy.types.Object:
    """Create an orthographic camera for consistent product shots."""
    cam_data = bpy.data.cameras.new("ProductCamera")
    cam_data.type = 'ORTHO'
    cam_data.clip_start = 0.01
    cam_data.clip_end = 100

    cam_obj = bpy.data.objects.new("ProductCamera", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    return cam_obj


# ---------------------------------------------------------------------------
# Import and framing
# ---------------------------------------------------------------------------

def prepare_work_dir(ydd_path: str, dds_files: list[str],
                     work_dir: str) -> str:
    """Copy .ydd and DDS textures into a temp work directory.

    Sollumz looks for textures in ``{import_dir}/{ydd_stem}/``.

    Returns:
        Path to the copied .ydd file in the work directory.
    """
    ydd_name = os.path.basename(ydd_path)
    ydd_stem = os.path.splitext(ydd_name)[0]

    # Copy .ydd
    dest_ydd = os.path.join(work_dir, ydd_name)
    shutil.copy2(ydd_path, dest_ydd)

    # Create texture subdirectory and copy DDS files
    tex_dir = os.path.join(work_dir, ydd_stem)
    os.makedirs(tex_dir, exist_ok=True)

    for dds_path in dds_files:
        dds_name = os.path.basename(dds_path)
        shutil.copy2(dds_path, os.path.join(tex_dir, dds_name))

    return dest_ydd


def import_ydd(ydd_path: str) -> bool:
    """Import a .ydd file via the Sollumz addon.

    Returns True on success, False on failure.
    """
    directory = os.path.dirname(ydd_path)
    filename = os.path.basename(ydd_path)

    try:
        bpy.ops.sollumz.import_assets(
            directory=directory + os.sep,
            files=[{"name": filename}],
        )
        return True
    except Exception as exc:
        print(f"Sollumz import failed: {exc}", file=sys.stderr)
        return False


def fix_missing_textures(dds_files: list[str]) -> int:
    """Force-load DDS textures into materials that failed auto-lookup.

    Sollumz auto-lookup only works when the texture name inside the .ytd
    matches the material's image reference.  Many assets use arbitrary
    names (``p1``, ``1``, ``Swatch_1_Diffuse_1``) that never match.

    This function finds every DiffuseSampler image node whose image has
    no pixel data and replaces it with the first available DDS file.

    Returns the number of textures fixed.
    """
    if not dds_files:
        return 0

    # Load all DDS files into Blender images, keyed by basename (no ext)
    loaded_images: dict[str, bpy.types.Image] = {}
    for dds_path in dds_files:
        name = os.path.splitext(os.path.basename(dds_path))[0]
        try:
            img = bpy.data.images.load(dds_path)
            loaded_images[name.lower()] = img
        except Exception as exc:
            print(f"    Could not load DDS {os.path.basename(dds_path)}: {exc}")

    if not loaded_images:
        return 0

    # Pick the first loaded image as the default diffuse fallback
    default_img = next(iter(loaded_images.values()))

    fixed = 0
    for mat in bpy.data.materials:
        if not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type != 'TEX_IMAGE':
                continue
            # Only fix DiffuseSampler nodes
            if node.name != 'DiffuseSampler':
                continue

            img = node.image
            # Check if the image is missing / not loaded
            if img is not None and img.has_data:
                continue  # already loaded fine

            # Try to match by name first
            if img is not None:
                # Normalize: strip Blender's .001 duplicate suffix and .dds ext
                # e.g. "uppr_diff_000_a_whi.dds.001" -> "uppr_diff_000_a_whi"
                match_name = img.name.lower()
                # Strip trailing .NNN Blender duplicate suffixes
                while match_name and match_name.rsplit('.', 1)[-1].isdigit():
                    match_name = match_name.rsplit('.', 1)[0]
                # Strip .dds extension
                if match_name.endswith('.dds'):
                    match_name = match_name[:-4]

                if match_name in loaded_images:
                    node.image = loaded_images[match_name]
                    fixed += 1
                    continue

            # No match — use the default (first) DDS
            node.image = default_img
            fixed += 1

    if fixed:
        print(f"    Fixed {fixed} missing diffuse texture(s)")

    return fixed


def fix_hair_tint() -> int:
    """Detect green tint-mask hair textures and remap to natural brown.

    GTA V hair uses a special shader where the raw diffuse is a green
    gradient that gets remapped at runtime.  Without that shader the hair
    renders as bright green.  This function detects green-dominant
    DiffuseSampler textures and converts them to a neutral brown using
    the green channel as luminance.

    Returns the number of images corrected.
    """
    if not GREEN_HAIR_FIX:
        return 0

    try:
        import numpy as np
    except ImportError:
        print("    WARNING: numpy not available — skipping hair tint fix")
        return 0

    fixed = 0
    for mat in bpy.data.materials:
        if not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type != 'TEX_IMAGE' or node.name != 'DiffuseSampler':
                continue

            img = node.image
            if img is None or not img.has_data:
                continue

            # Sample pixels to check if green-dominant
            w, h = img.size
            total_pixels = w * h
            if total_pixels == 0:
                continue

            pixels = np.array(img.pixels[:]).reshape(-1, 4)

            # Sample every Nth pixel for speed (at most 10k samples)
            stride = max(1, total_pixels // 10000)
            sample = pixels[::stride]

            # Only consider non-transparent pixels with some brightness
            mask = (sample[:, 3] > 0.1) & (sample[:, :3].max(axis=1) > 0.05)
            if mask.sum() < 100:
                continue

            visible = sample[mask]
            avg_r = visible[:, 0].mean()
            avg_g = visible[:, 1].mean()
            avg_b = visible[:, 2].mean()

            # Green-dominant = tint mask
            is_green = (avg_g > avg_r * 1.4) and (avg_g > avg_b * 1.4)
            if not is_green:
                continue

            # Remap: use green channel as luminance, tint to warm brown
            lum = pixels[:, 1].copy()
            pixels[:, 0] = lum * 0.55   # R
            pixels[:, 1] = lum * 0.40   # G
            pixels[:, 2] = lum * 0.28   # B
            # Alpha channel stays untouched

            img.pixels[:] = pixels.flatten().tolist()
            img.update()
            fixed += 1
            print(f"    Remapped green tint mask in {mat.name} "
                  f"(avg RGB: {avg_r:.2f}, {avg_g:.2f}, {avg_b:.2f})")

    if fixed:
        print(f"    Fixed {fixed} green hair tint mask(s) -> brown")
    return fixed


def fix_alpha_modes() -> int:
    """Force all materials to use OPAQUE or CLIP alpha instead of BLEND.

    DXT5/BC7 textures often have alpha channels that represent UV-unused
    regions (fully transparent).  When Sollumz sets up materials with
    BLEND alpha mode, these transparent regions make the garment invisible
    in the render.  Switching to CLIP (alpha test) or OPAQUE preserves
    visibility.

    Returns the number of materials fixed.
    """
    fixed = 0
    for mat in bpy.data.materials:
        if mat.blend_method in ('BLEND', 'HASHED'):
            mat.blend_method = 'CLIP'
            mat.alpha_threshold = 0.01  # very low threshold to keep almost everything visible
            fixed += 1
        # Also ensure the surface output isn't using alpha transparency
        if mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    # If alpha is connected to a texture, disconnect it
                    alpha_input = node.inputs.get('Alpha')
                    if alpha_input and alpha_input.is_linked:
                        for link in list(mat.node_tree.links):
                            if link.to_socket == alpha_input:
                                mat.node_tree.links.remove(link)
                                fixed += 1
                    # Set alpha to 1.0 (fully opaque)
                    if alpha_input:
                        alpha_input.default_value = 1.0

    if fixed:
        print(f"    Fixed {fixed} material alpha mode(s) -> CLIP/opaque")
    return fixed


def get_mesh_bounding_box() -> tuple[Vector, Vector] | None:
    """Compute the combined world-space bounding box of all mesh objects.

    Returns (min_corner, max_corner) or None if no meshes exist.
    """
    mesh_objects = [obj for obj in bpy.data.objects if obj.type == 'MESH']
    if not mesh_objects:
        return None

    all_min = Vector((float('inf'),) * 3)
    all_max = Vector((float('-inf'),) * 3)

    for obj in mesh_objects:
        # Get world-space bounding box corners
        for corner in obj.bound_box:
            world_corner = obj.matrix_world @ Vector(corner)
            for i in range(3):
                all_min[i] = min(all_min[i], world_corner[i])
                all_max[i] = max(all_max[i], world_corner[i])

    return all_min, all_max


def is_mesh_flat(depth_ratio: float = 0.05) -> bool:
    """Return True if the imported mesh is essentially flat (a thin overlay shell).

    Compares the Y-axis depth (front-to-back) against the largest of X/Z
    (width/height).  Flat body overlay meshes have depth < 5% of their span,
    while proper 3D clothing/body meshes have significant depth.
    """
    bbox = get_mesh_bounding_box()
    if bbox is None:
        return True

    bb_min, bb_max = bbox
    size = bb_max - bb_min
    span = max(size.x, size.z)  # width or height
    if span < 0.001:
        return True

    return size.y / span < depth_ratio


def frame_camera(cam_obj: bpy.types.Object,
                 elevation_deg: float | None = None) -> None:
    """Position the orthographic camera to frame all mesh objects.

    Args:
        cam_obj: The camera object.
        elevation_deg: Override camera elevation in degrees. If None, uses
            the default CAMERA_ELEVATION_DEG (10°).
    """
    bbox = get_mesh_bounding_box()
    if bbox is None:
        return

    bb_min, bb_max = bbox
    center = (bb_min + bb_max) / 2
    size = bb_max - bb_min

    elev = elevation_deg if elevation_deg is not None else CAMERA_ELEVATION_DEG
    elevation_rad = math.radians(elev)

    # Ortho scale: fit the largest visible span with padding.
    # At higher elevations we see more of the top (Y-depth) and less height (Z).
    visible_w = size.x
    visible_h = size.z * math.cos(elevation_rad) + size.y * math.sin(elevation_rad)
    max_dim = max(visible_w, visible_h)
    cam_obj.data.ortho_scale = max_dim * PADDING_FACTOR

    # Position camera in front, elevated
    distance = max(size.y, 5)  # far enough to not clip
    cam_obj.location = Vector((
        center.x,
        center.y - distance * math.cos(elevation_rad),
        center.z + distance * math.sin(elevation_rad),
    ))

    # Point camera at the center
    direction = center - cam_obj.location
    rot = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot.to_euler()


# ---------------------------------------------------------------------------
# Main render loop
# ---------------------------------------------------------------------------

def render_item(item: dict, cam_obj: bpy.types.Object,
                work_base: str) -> dict:
    """Render a single item and return a result dict.

    Args:
        item: Dict with keys: ydd_path, dds_files, output_path
        cam_obj: The camera object
        work_base: Base temp directory for this Blender session

    Returns:
        Dict with keys: output_path, success, error (if failed)
    """
    ydd_path = item["ydd_path"]
    dds_files = item.get("dds_files", [])
    output_path = item["output_path"]
    category = item.get("category", "")

    result = {"output_path": output_path, "success": False, "error": None}

    try:
        # Clear previous objects (keep camera and lights)
        for obj in list(bpy.data.objects):
            if obj.type not in ('CAMERA', 'LIGHT'):
                bpy.data.objects.remove(obj, do_unlink=True)
        # Purge orphan meshes/materials/images
        for mesh in list(bpy.data.meshes):
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        for mat in list(bpy.data.materials):
            if mat.users == 0:
                bpy.data.materials.remove(mat)
        for img in list(bpy.data.images):
            if img.users == 0:
                bpy.data.images.remove(img)

        # Prepare work directory with .ydd and textures
        item_work = os.path.join(work_base, f"item_{id(item)}")
        os.makedirs(item_work, exist_ok=True)

        dest_ydd = prepare_work_dir(ydd_path, dds_files, item_work)

        # Import via Sollumz
        if not import_ydd(dest_ydd):
            result["error"] = "Sollumz import failed"
            return result

        # Check if mesh is a flat overlay shell (body skin overlays).
        # If so and we have a fallback base body mesh, re-import with that.
        fallback_ydd = item.get("fallback_ydd")
        if fallback_ydd and is_mesh_flat():
            print(f"    Mesh is flat overlay — switching to base body mesh")
            # Clear the flat mesh
            for obj in list(bpy.data.objects):
                if obj.type not in ('CAMERA', 'LIGHT'):
                    bpy.data.objects.remove(obj, do_unlink=True)
            for mesh in list(bpy.data.meshes):
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            for mat in list(bpy.data.materials):
                if mat.users == 0:
                    bpy.data.materials.remove(mat)

            # Prepare and import the fallback mesh
            fallback_work = os.path.join(work_base, f"fallback_{id(item)}")
            os.makedirs(fallback_work, exist_ok=True)
            dest_fallback = prepare_work_dir(fallback_ydd, dds_files, fallback_work)
            if not import_ydd(dest_fallback):
                result["error"] = "Fallback Sollumz import failed"
                return result

        # Apply mesh rotations if specified (e.g. to face camera).
        # rotation_steps: list of [x,y,z] Euler triples applied sequentially.
        # Each step is baked into the mesh before the next step, so
        # step 1 = Z 180° (face camera), step 2 = X tilt (stand up)
        # produces the correct result.
        rot_steps = item.get("rotation_steps")
        if rot_steps:
            from mathutils import Euler as _Euler
            for step in rot_steps:
                step_euler = _Euler(step, 'XYZ')
                for obj in bpy.data.objects:
                    if obj.type == 'MESH':
                        obj.rotation_euler.rotate(step_euler)
                        bpy.context.view_layer.objects.active = obj
                        obj.select_set(True)
                bpy.ops.object.transform_apply(rotation=True)
                bpy.ops.object.select_all(action='DESELECT')

        # Fix textures that Sollumz couldn't auto-find
        fix_missing_textures(dds_files)

        # Force opaque/clip alpha to prevent invisible garments
        fix_alpha_modes()

        # Frame the camera on the imported mesh
        frame_camera(cam_obj, elevation_deg=item.get("camera_elevation"))

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

    return result


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
        #
        # Strategy: import ALL body parts first, then fix all textures in
        # one pass.  Sollumz's sequential imports overwrite image references
        # from earlier body parts, so per-part fix_missing_textures() fails.
        imported_any = False
        all_dds_files: list[str] = []

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
                dest = os.path.join(tex_dir, os.path.basename(dds_path))
                shutil.copy2(dds_path, dest)
                all_dds_files.append(dest)

            # Import via Sollumz (skeleton auto-detected from same directory)
            if import_ydd(dest_ydd):
                imported_any = True
            else:
                print(f"    WARNING: Failed to import {cat} ({ydd_basename})",
                      file=sys.stderr)

        if not imported_any:
            result["error"] = "No body parts imported successfully"
            return result

        # Disable external skeleton for subsequent normal renders
        _set_sollumz_external_skeleton(False)

        # Fix ALL textures in one pass after all imports are done
        fix_missing_textures(all_dds_files)

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
        for addon_name in ("bl_ext.blender_org.sollumz_dev",
                           "bl_ext.blender_org.sollumz"):
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


def _apply_config(config: dict) -> None:
    """Apply runtime config overrides to module-level constants."""
    global RENDER_SIZE, TAA_SAMPLES, GREEN_HAIR_FIX
    if "render_size" in config:
        RENDER_SIZE = int(config["render_size"])
    if "taa_samples" in config:
        TAA_SAMPLES = int(config["taa_samples"])
    if "green_hair_fix" in config:
        GREEN_HAIR_FIX = bool(config["green_hair_fix"])


def manifest_main() -> None:
    """Legacy entry point: blender -b -P ... -- manifest.json results.json"""
    argv = sys.argv
    sep_idx = argv.index("--") if "--" in argv else -1
    if sep_idx == -1 or sep_idx + 2 >= len(argv):
        print("Usage: blender -b -P blender_script.py -- manifest.json results.json",
              file=sys.stderr)
        sys.exit(1)

    manifest_path = argv[sep_idx + 1]
    results_path = argv[sep_idx + 2]

    # Load manifest
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Apply config overrides from manifest
    _apply_config(manifest.get("config", {}))

    items = manifest.get("items", [])
    print(f"Blender script: {len(items)} items to render")

    # One-time scene setup
    clear_scene()
    setup_render_settings()
    setup_lighting()
    cam_obj = setup_camera()

    # Create temp work directory for this session
    work_base = tempfile.mkdtemp(prefix="clothing_render_")

    results = []
    for i, item in enumerate(items):
        print(f"  [{i + 1}/{len(items)}] Rendering {os.path.basename(item['ydd_path'])}...")
        result = render_item(item, cam_obj, work_base)
        results.append(result)

        status = "OK" if result["success"] else f"FAIL: {result['error']}"
        print(f"    {status}")

    # Clean up temp work directory
    try:
        shutil.rmtree(work_base, ignore_errors=True)
    except Exception:
        pass

    # Write results
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, indent=2)

    print(f"Results written to {results_path}")

    succeeded = sum(1 for r in results if r["success"])
    print(f"Done: {succeeded}/{len(results)} rendered successfully")


def worker_main() -> None:
    """Persistent worker mode: blender -b -P ... -- --worker

    Reads JSON items one-per-line from stdin, renders each, and writes
    ``RESULT:{json}`` lines to stdout.  Exits cleanly when stdin is closed.

    IPC protocol:
      Python -> Blender (stdin):
        CONFIG:{"render_size":1024,"taa_samples":1,"green_hair_fix":true}  — optional, before items
        {"ydd_path":"...","dds_files":[...],"output_path":"...","category":"accs"}
      Blender -> Python (stdout):
        READY                           — startup complete
        RESULT:{"output_path":"...","success":true,"error":null}  — per item
    """
    # Read config line if available (sent before READY is expected)
    # Config is sent as CONFIG:{json} on stdin before items start
    # We'll check for it after scene setup in the main loop

    # One-time scene setup — may be re-done if CONFIG arrives
    clear_scene()
    setup_render_settings()
    setup_lighting()
    cam_obj = setup_camera()

    work_base = tempfile.mkdtemp(prefix="clothing_worker_")

    # Signal readiness
    print("READY", flush=True)

    rendered = 0
    while True:
        try:
            line = sys.stdin.readline()
        except Exception:
            break
        if not line:
            # EOF — parent closed stdin
            break

        line = line.strip()
        if not line:
            continue

        # Handle CONFIG line — reconfigure render settings
        if line.startswith("CONFIG:"):
            try:
                config = json.loads(line[7:])
                _apply_config(config)
                # Re-apply render settings with new values
                setup_render_settings()
                print(f"CONFIG_OK", flush=True)
            except Exception as exc:
                print(f"CONFIG_ERR:{exc}", flush=True)
            continue

        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            # Bad input — write error result
            error_result = {
                "output_path": "",
                "success": False,
                "error": f"JSON decode error: {exc}",
            }
            print(f"RESULT:{json.dumps(error_result)}", flush=True)
            continue

        rendered += 1
        ydd_name = os.path.basename(item.get("ydd_path", "?"))
        print(f"  [worker item {rendered}] Rendering {ydd_name}...",
              file=sys.stderr, flush=True)

        if item.get("type") == "full_ped":
            result = render_full_ped(item, cam_obj, work_base)
        else:
            result = render_item(item, cam_obj, work_base)

        status = "OK" if result["success"] else f"FAIL: {result['error']}"
        print(f"    {status}", file=sys.stderr, flush=True)

        # Write result line — prefixed so the parent can distinguish it
        print(f"RESULT:{json.dumps(result)}", flush=True)

    # Cleanup
    try:
        shutil.rmtree(work_base, ignore_errors=True)
    except Exception:
        pass

    print(f"Worker done: rendered {rendered} item(s)", file=sys.stderr,
          flush=True)


def main() -> None:
    """Entry point — dispatch to manifest mode or worker mode."""
    argv = sys.argv
    sep_idx = argv.index("--") if "--" in argv else -1

    # Check for --worker flag after "--"
    if sep_idx != -1:
        script_args = argv[sep_idx + 1:]
        if "--worker" in script_args:
            worker_main()
            return

    # Legacy manifest mode
    manifest_main()


if __name__ == "__main__":
    main()
