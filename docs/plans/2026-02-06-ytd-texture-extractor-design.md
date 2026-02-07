# YTD Texture Extractor — Complete Implementation Plan

## Purpose

Build a Python CLI tool that batch-extracts diffuse textures from GTA V `.ytd` files (RSC7 format) used in FiveM clothing resource packs, converts them to optimized `.webp` previews (via flat 2D extraction or optional 3D rendering through Blender), and generates a `catalog.json` for a web-based clothing shop UI.

---

## Context & Data

### Input Data Location

```
clothing_tool/
  stream/
    government_clothing/   # Resource pack
    new_overlays/          # Tattoo overlays (skip)
    rhaddonfaces/          # Face textures
    rhclothing/            # Main clothing pack
    rhclothing2/           # Extended clothing
    rhpeds/                # Custom ped models
```

### Key Statistics

- **10,341** total `.ytd` files across 6 resource packs
- **1,246** base textures (`*_a_uni.ytd`) — these are the only ones we process
- File sizes range from 65 bytes (empty/corrupt) to ~4MB
- 6 resource packs, each with `.meta` XML files containing `<dlcName>`
- Common texture formats encountered: DXT1 (BC1), DXT5 (BC3), BC7
- Common texture dimensions: 512x512, 1024x1024, 1024x2048, 2048x2048

### Directory Structure Per Resource Pack

```
{resource_pack}/
  fxmanifest.lua                              # FiveM manifest
  mp_f_freemode_01_{dlcname}.meta             # Female clothing meta (XML)
  mp_m_freemode_01_{dlcname}.meta             # Male clothing meta (XML)
  stream/
    [female]/
      accs/                                   # Accessories
        mp_f_freemode_01_{dlcname}^accs_diff_000_a_uni.ytd
        mp_f_freemode_01_{dlcname}^accs_diff_000_b_uni.ytd  # variant
        mp_f_freemode_01_{dlcname}^accs_000_u.ydd           # 3D model (for 3D rendering)
        ...
      jbib/                                   # Jackets/tops
      lowr/                                   # Lower body
      feet/                                   # Shoes
      hair/                                   # Hair
      hand/                                   # Gloves
      uppr/                                   # Upper body overlays
      teef/                                   # Teeth
      berd/                                   # Beard
      p_head/                                 # Head props
      p_eyes/                                 # Eye props
      ...
    [male]/
      (same categories)
    [replacements]/                           # Replacement textures (edge case)
    [strafe]/                                 # Custom ped models (rhpeds only)
```

### Filename Anatomy

#### YTD (Texture) Files

```
mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd
│                  │          │    │    │   │  │
│                  │          │    │    │   │  └─ uni = universal
│                  │          │    │    │   └─ a = base variant (b,c,d... = color swaps)
│                  │          │    │    └─ 000 = drawable ID
│                  │          │    └─ diff = diffuse texture type
│                  │          └─ accs = component category
│                  └─ rhclothing = DLC name
└─ mp_f_freemode_01 = ped model (f=female, m=male)
```

#### YDD (3D Model) Files

```
mp_f_freemode_01_rhclothing^accs_000_u.ydd
│                  │          │    │   │
│                  │          │    │   └─ u = LOD suffix (u=highest, r=medium)
│                  │          │    └─ 000 = drawable ID (matches YTD)
│                  │          └─ accs = component category
│                  └─ rhclothing = DLC name
└─ mp_f_freemode_01 = ped model
```

**We only process files matching `*_a_uni.ytd`** — the base diffuse texture. Variants (`_b_`, `_c_`, etc.) are color swaps; we just count them.

### Meta File Format

Each resource pack has XML `.meta` files:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<ShopPedApparel>
    <pedName>mp_f_freemode_01</pedName>
    <dlcName>rhclothing</dlcName>
    <fullDlcName>mp_f_freemode_01_rhclothing</fullDlcName>
    <eCharacter>SCR_CHAR_MULTIPLAYER_F</eCharacter>
    <creatureMetaData>mp_creaturemetadata_f_rhclothing</creatureMetaData>
    <pedOutfits></pedOutfits>
    <pedComponents></pedComponents>
    <pedProps></pedProps>
</ShopPedApparel>
```

Key field: `<dlcName>` — used as the top-level grouping key in the catalog.

**Important:** Only files whose stem starts with `mp_f_freemode_01_` or `mp_m_freemode_01_` are apparel meta files. Skip `peds.meta`, `shop_tattoo.meta`, `pedalternativevariations_*.meta`, etc.

---

## Output

### File Structure

```
output/
  textures/
    rhclothing/
      female/
        accs/
          000.webp
          001.webp
          ...
        jbib/
        lowr/
        ...
      male/
        ...
    rhgovernment/
      ...
  failed/
    rhclothing_female_accs_003.log    # Error log per failed file
  catalog.json
```

### catalog.json Schema

```json
{
  "generated_at": "2026-02-06T12:00:00Z",
  "total_items": 1200,
  "total_failed": 46,
  "items": {
    "rhclothing_female_accs_000": {
      "dlcName": "rhclothing",
      "gender": "female",
      "category": "accs",
      "drawableId": 0,
      "texture": "rhclothing/female/accs/000.webp",
      "variants": 22,
      "source": "mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd",
      "width": 512,
      "height": 512,
      "originalWidth": 1024,
      "originalHeight": 1024,
      "format": "DXT5",
      "renderType": "flat"
    }
  }
}
```

**Catalog key format:** `{dlcName}_{gender}_{category}_{drawableId:03d}`

**renderType values:**
- `"flat"` — 2D texture extraction (default pipeline)
- `"3d"` — Blender-rendered product shot (optional pipeline)

### WebP Output Spec

- 512x512 pixels, RGBA
- Aspect ratio preserved via `thumbnail()`, centered on transparent canvas
- Quality 80, method 6 (best compression)
- Expected size: ~20-80KB per image
- For 3D renders: Blender renders at 2048x2048, then downscaled to 512x512 with Lanczos (supersampling)

---

## Architecture

### Project Structure

```
clothing_tool/
  stream/                     # INPUT — untouched
  docs/plans/                 # This plan
  src/
    __init__.py
    rsc7.py                   # RSC7 container: header, decompression, page splitting
    ytd_parser.py             # TextureDictionary struct parsing
    dds_builder.py            # Construct DDS file headers from texture metadata
    image_processor.py        # DDS → RGBA → resize → .webp export + PNG→WebP + empty detection
    meta_parser.py            # Parse .meta XML for dlcName mapping
    filename_parser.py        # Extract metadata from .ytd filename patterns
    catalog.py                # Assemble catalog.json from processed items
    scanner.py                # Recursive file discovery + batch orchestration
    ydd_pairer.py             # Pair .ytd textures with .ydd 3D models
    blender_renderer.py       # Blender orchestrator: DDS extraction, manifest, subprocess
    blender_script.py         # Blender-side script: Sollumz import, scene setup, rendering
  tests/
    test_catalog.py           # CatalogBuilder unit tests
    test_black_square_008.py  # Regression test for alpha transparency bug
  cli.py                      # CLI entry point
  requirements.txt
  output/                     # OUTPUT — generated
```

### Dependencies

```
# requirements.txt
pillow>=10.2.0    # DDS reading (DXT1/DXT3/DXT5/BC7 via DX10 header)
```

Optional fallback (only if Pillow fails on exotic formats):
```
pydds             # Native C DDS decoder, handles all BC formats
```

Optional for 3D rendering:
```
Blender 4.x       # External application (not pip-installed)
Sollumz addon     # Blender addon for GTA V model import (installed in Blender)
```

No other external dependencies. The RSC7 parser, struct parsing, and DDS header construction are all pure Python using only `struct`, `zlib`, `io`, `xml.etree.ElementTree` from stdlib.

---

## Pipeline Overview

There are two rendering paths. Both produce identical 512x512 `.webp` output.

### Pipeline A: Flat Texture Extraction (Default)

```
.ytd file
  → RSC7 header validation + raw deflate decompression
  → Split into virtual (structs) + physical (pixel data) segments
  → Parse TextureDictionary → locate Texture structs
  → Select diffuse texture (exclude _n, _s, _m suffixes)
  → Extract raw pixel data from physical segment
  → Build DDS header (magic + 124-byte header + optional DX10 extension)
  → Append raw pixel data → complete in-memory DDS file
  → Pillow: Image.open(BytesIO(dds)) → convert("RGBA")
  → Resize with thumbnail(512,512) → center on transparent canvas
  → Save as .webp (quality=80, method=6)
```

### Pipeline B: 3D Blender Rendering (Optional `--render-3d`)

```
.ytd file → pair with .ydd file in same directory
  → Extract DDS textures from ALL variant YTDs (_a_, _b_, _c_...)
  → Write DDS files to temp directory
  → Write manifest.json with: ydd_path, dds_files[], output_png
  → Invoke: blender -b -P blender_script.py -- manifest.json results.json
    Inside Blender:
      → Enable Sollumz addon
      → Clear scene, set up Eevee renderer (2048x2048, transparent BG)
      → Create 3-point studio lighting (key + fill + rim)
      → Create orthographic camera
      → For each item:
        → Copy .ydd + DDS textures to work directory
        → Import .ydd via Sollumz
        → Fix missing textures (manual DDS→material binding)
        → Fix alpha modes (BLEND→CLIP, disconnect alpha from BSDF)
        → Frame camera on mesh bounding box
        → Render to PNG
      → Write results.json
  → Validate render isn't empty (is_image_empty check)
  → Convert rendered PNG → 512x512 WebP
  → Falls back to Pipeline A if: no .ydd found, Blender fails, render is empty
```

---

## Implementation Steps

### Step 1: `src/rsc7.py` — RSC7 Container Parser

**Purpose:** Open a `.ytd` file, validate the RSC7 header, decompress the payload, and split it into virtual (struct) and physical (pixel data) segments.

**RSC7 Header (16 bytes, little-endian):**

```
Offset  Size  Type    Field           Description
0x00    4     uint32  magic           0x37435352 = "RSC7" in little-endian
0x04    4     uint32  version         13 = PC/legacy, 5 = Gen9
0x08    4     uint32  system_flags    Encodes virtual segment page sizes
0x0C    4     uint32  graphics_flags  Encodes physical segment page sizes
```

**Page size calculation from flags** (from CodeWalker `RpfFile.cs`):

```python
def get_size_from_flags(flags: int) -> int:
    """Calculate decompressed segment size from RSC7 flag field.

    Each flag encodes a combination of page counts at different size
    multiples of a base page size. Ported from CodeWalker RpfFile.cs.
    """
    s0 = ((flags >> 27) & 0x1)  << 0
    s1 = ((flags >> 26) & 0x1)  << 1
    s2 = ((flags >> 25) & 0x1)  << 2
    s3 = ((flags >> 24) & 0x1)  << 3
    s4 = ((flags >> 17) & 0x7F) << 4
    s5 = ((flags >> 11) & 0x3F) << 5
    s6 = ((flags >> 7)  & 0xF)  << 6
    s7 = ((flags >> 5)  & 0x3)  << 7
    s8 = ((flags >> 4)  & 0x1)  << 8
    ss = (flags >> 0) & 0xF
    base_size = 0x200 << ss
    total = s0 + s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8
    return base_size * total
```

**Decompression:**

The data after the 16-byte header is **raw deflate** (no zlib/gzip wrapper):

```python
import zlib
decompressed = zlib.decompress(compressed_data, -15)  # -15 = raw deflate
```

**Segment splitting:**

```python
virtual_size = get_size_from_flags(system_flags)
physical_size = get_size_from_flags(graphics_flags)
virtual_data = decompressed[:virtual_size]
physical_data = decompressed[virtual_size:virtual_size + physical_size]
```

**Public API:**

```python
@dataclass
class RSC7Resource:
    version: int
    virtual_data: bytes    # Contains struct data (TextureDictionary, Texture structs, name strings)
    physical_data: bytes   # Contains raw pixel data (DDS payloads without headers)

def parse_rsc7(file_path: str | Path) -> RSC7Resource:
    """Parse an RSC7 container file, returning decompressed virtual and physical segments.

    Raises:
        ValueError: Invalid magic, file too small, or segment sizes exceed decompressed data.
        zlib.error: Decompression failure.
        FileNotFoundError: File doesn't exist.
    """
```

**Validation:**
- Magic must be `0x37435352`
- Version should be 13 (log warning if different but still attempt)
- `virtual_size + physical_size` must not exceed decompressed length
- Minimum file size check: reject files < 32 bytes

---

### Step 2: `src/ytd_parser.py` — TextureDictionary Parser

**Purpose:** Parse the decompressed virtual data to extract texture metadata and locate raw pixel data in the physical segment.

**Pointer resolution:**

GTA V resources use two virtual address spaces:
- `0x50000000` base → virtual segment (subtract to get offset within `virtual_data`)
- `0x60000000` base → physical segment (subtract to get offset within `physical_data`)

```python
VIRTUAL_BASE  = 0x50000000
PHYSICAL_BASE = 0x60000000

def resolve_pointer(ptr: int) -> tuple[str, int]:
    """Returns ('virtual', offset) or ('physical', offset) or ('null', 0)."""
    if ptr == 0:
        return ('null', 0)
    if ptr >= PHYSICAL_BASE:
        return ('physical', ptr - PHYSICAL_BASE)
    if ptr >= VIRTUAL_BASE:
        return ('virtual', ptr - VIRTUAL_BASE)
    raise ValueError(f"Unknown pointer base: 0x{ptr:08X}")
```

**TextureDictionary structure (at virtual offset 0, 64 bytes):**

```
Offset  Size  Type     Field
0x00    4     uint32   VFT (virtual function table pointer — skip)
0x04    4     uint32   Unknown_04h (always 1)
0x08    4     uint32   PagesInfo pointer
0x0C    4     uint32   padding
0x10    4     uint32   Unknown_10h (always 0)
0x14    4     uint32   Unknown_14h (always 0)
0x18    4     uint32   Unknown_18h (always 1)
0x1C    4     uint32   Unknown_1Ch (always 0)
0x20    8     ptr+cnt  TextureNameHashesPointer (uint64: pointer to hash array)
0x28    2     uint16   TextureNameHashesCount
0x2A    2     uint16   TextureNameHashesCapacity
0x2C    4     uint32   padding
0x30    8     ptr+cnt  TexturesPointer (uint64: pointer to array of Texture pointers)
0x38    2     uint16   TexturesCount
0x3A    2     uint16   TexturesCapacity
0x3C    4     uint32   padding
```

**CRITICAL NOTE ON 64-BIT POINTERS:** The pointer fields at 0x20 and 0x30 are 64-bit. However, in RSC7 resources, only the lower 32 bits matter for offset resolution. The upper 32 bits contain type/flag information. Read as uint64 but mask with `& 0xFFFFFFFF` for pointer resolution.

**Texture struct (144 bytes per texture, in virtual data):**

```
Offset  Size  Type     Field
0x00    4     uint32   VFT
0x04    4     uint32   Unknown_04h
0x08-0x27  32 bytes   (base class fields, skip)
0x28    8     uint64   NamePointer (points to null-terminated ASCII string in virtual data)
0x30-0x4F  32 bytes   (texture base fields, skip)
0x50    2     uint16   Width
0x52    2     uint16   Height
0x54    2     uint16   Depth (usually 1)
0x56    2     uint16   Stride (row pitch in bytes)
0x58    4     uint32   Format (DDS format code — see format table below)
0x5C    1     uint8    Unknown_5Ch
0x5D    1     uint8    MipLevels
0x5E    2     uint16   Unknown_5Eh
0x60-0x6F  16 bytes   padding
0x70    8     uint64   DataPointer (points to raw pixel data in physical data)
0x78-0x8F  24 bytes   padding
```

**Texture format codes:**

```python
TEXTURE_FORMATS = {
    # Uncompressed
    21:           ("A8R8G8B8", 32),     # 0x15 — 32bpp ARGB
    22:           ("X8R8G8B8", 32),     # 0x16 — 32bpp XRGB
    25:           ("A1R5G5B5", 16),     # 0x19 — 16bpp
    28:           ("A8", 8),            # 0x1C — 8bpp alpha only
    32:           ("A8B8G8R8", 32),     # 0x20 — 32bpp ABGR
    50:           ("L8", 8),            # 0x32 — 8bpp luminance

    # Compressed (FourCC values)
    0x31545844:   ("DXT1", 4),          # BC1 — 4bpp
    0x33545844:   ("DXT3", 8),          # BC2 — 8bpp
    0x35545844:   ("DXT5", 8),          # BC3 — 8bpp
    0x31495441:   ("ATI1", 4),          # BC4 — 4bpp
    0x32495441:   ("ATI2", 8),          # BC5 — 8bpp
    0x20374342:   ("BC7", 8),           # BC7  — 8bpp
}
```

**Block-compressed formats and their per-block byte sizes:**

```python
_BLOCK_COMPRESSED = {
    "DXT1": 8,   "ATI1": 8,
    "DXT3": 16,  "DXT5": 16,
    "ATI2": 16,  "BC7":  16,
}
```

**Calculating raw pixel data size:**

For block-compressed formats (DXT1, DXT3, DXT5, BC7, ATI1, ATI2):
```python
def calc_mip_size_compressed(width, height, block_size):
    """block_size: 8 for DXT1/ATI1, 16 for DXT5/DXT3/BC7/ATI2"""
    blocks_x = max(1, (width + 3) // 4)
    blocks_y = max(1, (height + 3) // 4)
    return blocks_x * blocks_y * block_size
```

For uncompressed formats:
```python
def calc_mip_size_uncompressed(width, height, bpp):
    return width * height * (bpp // 8)
```

Total data size = sum of all mip levels (each mip is half the dimensions of the previous). Clamp to available physical data if undersized.

**Public API:**

```python
@dataclass
class TextureInfo:
    name: str
    width: int
    height: int
    format_code: int
    format_name: str        # "DXT5", "BC7", etc.
    mip_levels: int
    stride: int
    raw_data: bytes         # Raw pixel data (no DDS header)

def parse_texture_dictionary(virtual_data: bytes, physical_data: bytes) -> list[TextureInfo]:
    """Parse all textures from a decompressed RSC7 resource."""
```

**Texture selection logic (within this module):**

```python
_NON_DIFFUSE_SUFFIXES = ('_n', '_s', '_m')

def select_diffuse_texture(textures: list[TextureInfo]) -> TextureInfo | None:
    """Pick the diffuse texture from a texture dictionary.

    1. If only one texture, return it regardless of name.
    2. Exclude textures with names ending in _n (normal), _s (specular), or _m (mask).
    3. From remaining candidates, pick the one with highest resolution (width * height).
    4. If all textures are excluded by name, return None.
    """
```

---

### Step 3: `src/dds_builder.py` — DDS Header Construction

**Purpose:** Build a valid DDS file in memory from texture metadata + raw pixel data, so Pillow can open it.

**Supported formats:** DXT1, DXT3, DXT5, ATI1, ATI2, BC7, A8R8G8B8, X8R8G8B8, A8B8G8R8, L8, A8.

**DDS file structure:**

```
Bytes 0-3:     Magic "DDS " (0x20534444)
Bytes 4-127:   DDS_HEADER (124 bytes)
Bytes 128-147: DDS_HEADER_DXT10 (20 bytes, only for BC7)
Bytes 128+:    Raw pixel data (all mip levels)
```

**DDS_HEADER (124 bytes):**

```
Offset  Size  Field              Value for our use
0x00    4     dwSize             124
0x04    4     dwFlags            DDSD_CAPS|DDSD_HEIGHT|DDSD_WIDTH|DDSD_PIXELFORMAT|DDSD_MIPMAPCOUNT|DDSD_LINEARSIZE
                                 = 0x000A1007
0x08    4     dwHeight           texture height
0x0C    4     dwWidth            texture width
0x10    4     dwPitchOrLinearSize  Size of first mip level in bytes
0x14    4     dwDepth            0
0x18    4     dwMipMapCount      mip level count
0x1C    44    dwReserved1[11]    All zeros
0x48    32    ddspf              DDS_PIXELFORMAT (see below)
0x68    4     dwCaps             DDSCAPS_TEXTURE | DDSCAPS_MIPMAP | DDSCAPS_COMPLEX = 0x401008
0x6C    16    dwCaps2-4+Rsv      All zeros
```

**DDS_PIXELFORMAT (32 bytes at offset 0x48):**

For FourCC-based formats (DXT1, DXT3, DXT5, ATI1, ATI2):
```
dwSize=32, dwFlags=DDPF_FOURCC(0x4), dwFourCC=<fourcc>, rest=0
```

For BC7 (requires DX10 extended header):
```
dwSize=32, dwFlags=DDPF_FOURCC(0x4), dwFourCC="DX10"(0x30315844), rest=0
```

Then append DDS_HEADER_DXT10 (20 bytes):
```
dxgiFormat=98(BC7_UNORM), resourceDimension=3(TEXTURE2D), miscFlag=0, arraySize=1, miscFlags2=0
```

For uncompressed A8R8G8B8/X8R8G8B8/A8B8G8R8:
```
dwSize=32, dwFlags=DDPF_RGB|DDPF_ALPHAPIXELS(0x41), dwRGBBitCount=32
dwRBitMask=0x00FF0000, dwGBitMask=0x0000FF00, dwBBitMask=0x000000FF, dwABitMask=0xFF000000
```

For L8 (luminance):
```
dwSize=32, dwFlags=DDPF_LUMINANCE(0x20000), dwRGBBitCount=8, dwRBitMask=0xFF
```

**IMPORTANT: A8 format workaround:** Pillow's DDS loader doesn't support the pure-alpha pixel format flag (0x2). Since A8 and L8 have the same data layout (1 byte/pixel), emit A8 as luminance so Pillow can open it.

**Public API:**

```python
def build_dds(texture: TextureInfo) -> bytes:
    """Construct a complete DDS file (header + pixel data) from a TextureInfo.

    Returns bytes that can be opened by Pillow via Image.open(BytesIO(dds_bytes)).
    Raises ValueError for unsupported formats.
    """
```

---

### Step 4: `src/image_processor.py` — Image Conversion & Export

**Purpose:** Convert DDS bytes to a 512x512 RGBA `.webp` file. Also handles PNG→WebP conversion for 3D renders and empty-image detection.

**Flat texture processing:**

```python
def process_texture(dds_bytes: bytes, output_path: str) -> tuple[int, int]:
    """Convert DDS bytes to a 512x512 centered .webp file.

    Returns (original_width, original_height) for catalog metadata.
    """
    img = _decode_dds(dds_bytes)       # Pillow primary, pydds fallback
    img = img.convert("RGBA")
    original_size = (img.width, img.height)

    img.thumbnail((512, 512), Image.LANCZOS)

    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    offset = ((512 - img.width) // 2, (512 - img.height) // 2)
    canvas.paste(img, offset)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    canvas.save(output_path, "WEBP", quality=80, method=6)

    return original_size
```

**3D render post-processing:**

```python
def convert_rendered_png(png_path: str, output_path: str) -> None:
    """Convert a Blender-rendered PNG to a 512x512 WebP.

    Blender renders at 2048x2048 for quality; this downscales with
    Lanczos resampling (supersampling anti-aliasing).
    """
```

**Empty image detection (safety net for 3D renders):**

```python
def is_image_empty(image_path: str, threshold: int = 100) -> bool:
    """Check if a rendered image is effectively empty (all transparent/black).

    Returns True if the image has fewer than `threshold` visible pixels
    (pixels with alpha > 0). Used to detect failed 3D renders that
    produce fully transparent output.
    """
```

**DDS decoding with fallback:**

```python
def _decode_dds(dds_bytes: bytes) -> Image.Image:
    """Attempt to decode DDS bytes, first with Pillow, then pydds fallback."""
    try:
        return Image.open(BytesIO(dds_bytes))
    except Exception as pillow_err:
        try:
            from dds import decode_dds
            return decode_dds(dds_bytes)
        except ImportError:
            raise pillow_err
```

---

### Step 5: `src/meta_parser.py` — Meta File Parser

**Purpose:** Parse `.meta` XML files to build a mapping from resource pack directory to DLC name.

**Key implementation details:**
- Only process `.meta` files whose stem starts with `mp_f_freemode_01_` or `mp_m_freemode_01_`
- Silently skip other meta files: `peds.meta`, `shop_tattoo.meta`, `pedalternativevariations_*.meta`
- Walk first-level subdirectories under `stream/`, then `rglob("*.meta")` within each
- Warn on conflicting dlcName mappings for the same directory

```python
def parse_meta_file(meta_path: str | Path) -> dict:
    """Parse a single ShopPedApparel .meta file.

    Returns: {
        'pedName': 'mp_f_freemode_01',
        'dlcName': 'rhclothing',
        'fullDlcName': 'mp_f_freemode_01_rhclothing',
        'gender': 'female'
    }

    Validates root tag is <ShopPedApparel>.
    Derives gender from pedName: '_f_' -> 'female', '_m_' -> 'male'.
    """

def build_dlc_map(stream_root: str | Path) -> dict[str, str]:
    """Scan all ShopPedApparel .meta files under stream_root.

    Returns: {
        'government_clothing': 'rhgovernment',
        'rhaddonfaces':        'rhaddonfaces',
        'rhclothing':          'rhclothing',
        'rhclothing2':         'rhclothing2',
    }
    """
```

---

### Step 6: `src/filename_parser.py` — Filename Metadata Extraction

**Purpose:** Parse structured `.ytd` filenames into metadata components.

**Regex patterns:**

```python
# Standard freemode model pattern.
# IMPORTANT: dlcname uses .+? (non-greedy) — NOT [a-zA-Z0-9]+
# because DLC names can contain underscores and embedded sub-DLC names like
# "mp_f_gunrunning_01" in "mp_f_freemode_01_mp_f_gunrunning_01^accs_diff_000_a_uni.ytd"
YTD_PATTERN = re.compile(
    r'^(?P<model>mp_[fm]_freemode_01)_'
    r'(?P<dlcname>.+?)\^'              # non-greedy to capture everything up to ^
    r'(?P<category>[a-z_]+)_'
    r'diff_'
    r'(?P<drawable>\d+)_'
    r'(?P<variant>[a-z])_'
    r'(?P<suffix>[a-z]+)'
    r'\.ytd$'
)

# Custom ped pattern (no mp_f/mp_m prefix).
# Model name allows underscores: [a-zA-Z0-9_]+
CUSTOM_PED_PATTERN = re.compile(
    r'^(?P<model>[a-zA-Z0-9_]+)\^'
    r'(?P<category>[a-z_]+)_'
    r'diff_'
    r'(?P<drawable>\d+)_'
    r'(?P<variant>[a-z])_'
    r'(?P<suffix>[a-z]+)'
    r'\.ytd$'
)
```

**LESSON LEARNED:** The original plan used `[a-zA-Z0-9]+` for dlcname, but real-world DLC names contain underscores and even embedded ped model prefixes (e.g., `mp_f_gunrunning_01`). The fix is to use `.+?` (non-greedy match up to `^`).

**Public API:**

```python
@dataclass
class YtdFileInfo:
    file_path: str
    model: str          # "mp_f_freemode_01" or custom ped name
    dlc_name: str       # "rhclothing", or model name for custom peds
    gender: str         # "female", "male", or "unknown"
    category: str       # "accs", "jbib", "lowr", etc.
    drawable_id: int    # 0, 1, 2, ...
    variant: str        # "a", "b", "c", ...
    is_base: bool       # True if variant == "a"

def parse_ytd_filename(file_path: str) -> YtdFileInfo | None:
    """Extract metadata from a .ytd filename. Returns None if pattern doesn't match."""

def count_variants(file_path: str) -> int:
    """Count sibling variant files (a, b, c, ...) for a given base (_a_) file.

    Scans same directory for files with same prefix but different variant letter.
    Verifies each sibling by re-parsing its filename and matching model/dlc/category/drawable.
    """
```

**Gender derivation (priority order):**
1. Path contains `[female]` or `/female/` → `"female"`
2. Path contains `[male]` or `/male/` → `"male"`
3. Model starts with `mp_f_` → `"female"`
4. Model starts with `mp_m_` → `"male"`
5. Otherwise → `"unknown"`

---

### Step 7: `src/catalog.py` — Catalog Builder

**Purpose:** Accumulate processed items and write `catalog.json`.

```python
@dataclass
class CatalogItem:
    dlc_name: str
    gender: str
    category: str
    drawable_id: int
    texture_path: str       # Relative: "rhclothing/female/accs/000.webp"
    variants: int
    source_file: str        # Original .ytd filename
    width: int              # Output width (512)
    height: int             # Output height (512)
    original_width: int     # Source texture width
    original_height: int    # Source texture height
    format_name: str        # "DXT5", "BC7", "3D_RENDER", etc.
    render_type: str = "flat"  # "flat" or "3d"

class CatalogBuilder:
    def __init__(self):
        self.items: dict[str, CatalogItem] = {}
        self.failed: list[dict] = []

    def add_item(self, item: CatalogItem):
        """Key format: {dlc_name}_{gender}_{category}_{drawable_id:03d}"""

    def add_failure(self, file_path: str, error: str):
        """Record a failed file."""

    def write(self, output_path: str):
        """Write catalog.json. Items sorted by key. camelCase JSON fields."""
```

---

### Step 8: `src/ydd_pairer.py` — YTD↔YDD File Pairing

**Purpose:** Given a `.ytd` texture path, find the corresponding `.ydd` 3D model file. Required for Pipeline B (3D rendering).

**Pairing logic:**

```
YTD: mp_f_freemode_01_rhclothing^accs_diff_000_a_uni.ytd
YDD: mp_f_freemode_01_rhclothing^accs_000_u.ydd
                                       ↑↑↑ ↑↑↑
                                  shared prefix + drawable ID
```

Both share the prefix (model + DLC + category) and drawable ID. The YDD file has a LOD suffix like `_u` (highest quality) or `_r` (medium).

```python
# Extract prefix + drawable from YTD filename
_YTD_PREFIX_RE = re.compile(
    r'^(?P<prefix>.+?\^[a-z_]+)_diff_(?P<drawable>\d+)_[a-z]_[a-z]+\.ytd$',
    re.IGNORECASE,
)

# YDD suffix preference (try _u first, then _r, then any)
_YDD_SUFFIX_PREFERENCE = ['_u', '_r']

def find_ydd_for_ytd(ytd_path: str) -> str | None:
    """Find the .ydd model file corresponding to a .ytd texture file.

    Searches the same directory. Prefers _u suffix, then _r, then any.
    Returns absolute path or None.
    """
```

---

### Step 9: `src/blender_renderer.py` — Blender Orchestrator

**Purpose:** Bridge between the Python pipeline and Blender headless rendering. Handles DDS extraction, manifest creation, subprocess invocation, and result processing.

**DDS extraction for 3D rendering:**

```python
def extract_dds_for_ydd(ytd_path: str, dds_output_dir: str) -> list[str]:
    """Extract DDS textures from ALL sibling variant YTDs (_a_, _b_, _c_...).

    IMPORTANT: The model's default material may reference a texture name from
    ANY variant, not just the base _a_. We must extract all of them so Sollumz
    can find whichever name it needs.

    Deduplicates by texture name (case-insensitive).
    Returns list of paths to created DDS files.
    """
```

**Blender invocation:**

```python
def _invoke_blender(blender_path: str, manifest_path: str, results_path: str) -> bool:
    """Invoke Blender headless: blender -b -P blender_script.py -- manifest.json results.json

    - 10 minute timeout per batch
    - Captures stdout/stderr for logging
    - Returns True on success
    """
```

**Batch rendering with retry:**

```python
def render_batch(items: list[dict], blender_path: str, batch_size: int = 50) -> list[RenderResult]:
    """Render items via Blender in sub-batches.

    If an entire batch fails (likely a Blender crash), retries with batch_size=5.
    For each item: extracts DDS → writes manifest → invokes Blender → validates render → converts PNG→WebP.
    """
```

**Blender auto-detection:**

```python
def find_blender() -> str | None:
    """Try shutil.which("blender"), then common Windows install paths
    (C:\\Program Files\\Blender Foundation\\Blender 4.x\\blender.exe)."""
```

---

### Step 10: `src/blender_script.py` — Blender-Side Render Script

**Purpose:** Runs inside Blender as a Python script. Imports models via Sollumz, sets up scene, renders product shots.

**Requirements:**
- Blender 4.x with Eevee Next renderer
- Sollumz addon installed and enabled

**Sollumz addon discovery:**

```python
# Try multiple module names (Sollumz can be installed under different names)
_SOLLUMZ_MODULES = [
    "bl_ext.blender_org.sollumz_dev",
    "bl_ext.blender_org.sollumz",
    "SollumzPlugin",
]
```

**Scene setup:**

```python
RENDER_SIZE = 2048          # High-res render, downscaled to 512x512 later
CAMERA_ELEVATION_DEG = 10   # Slight top-down angle
PADDING_FACTOR = 1.15       # 15% padding around bounding box

def setup_render_settings():
    """Eevee Next, 2048x2048, transparent background, PNG RGBA output."""

def setup_lighting():
    """3-point studio setup:
    - Key light: AREA, energy=150, size=3, position=(2.5, -2.5, 3.5)
    - Fill light: AREA, energy=60, size=4, position=(-3, -1.5, 2)
    - Rim light: AREA, energy=100, size=2, position=(0, 3, 4)
    All aimed at origin.
    """

def setup_camera():
    """Orthographic camera for consistent product shots."""
```

**Model import via Sollumz:**

```python
def prepare_work_dir(ydd_path, dds_files, work_dir):
    """Copy .ydd + DDS textures into temp directory.
    Sollumz looks for textures in {import_dir}/{ydd_stem}/."""

def import_ydd(ydd_path):
    """bpy.ops.sollumz.import_assets(directory=..., files=[{"name": ...}])"""
```

**Critical post-import fixes:**

```python
def fix_missing_textures(dds_files: list[str]) -> int:
    """Force-load DDS textures into materials that failed auto-lookup.

    Sollumz auto-lookup only works when texture names match. Many assets use
    arbitrary names (p1, 1, Swatch_1_Diffuse_1) that never match.
    Finds every DiffuseSampler image node with no pixel data and replaces
    it with the matching or first available DDS file.
    """

def fix_alpha_modes() -> int:
    """Force all materials to CLIP alpha instead of BLEND.

    BUG DISCOVERED: DXT5/BC7 textures often have alpha channels representing
    UV-unused regions (fully transparent). When Sollumz sets BLEND alpha mode,
    these regions make the garment invisible, producing black-square renders.

    Fix: Switch to CLIP with threshold=0.01, disconnect alpha from Principled BSDF,
    set alpha input to 1.0.
    """
```

**Camera framing:**

```python
def frame_camera(cam_obj):
    """Compute combined world-space bounding box of all mesh objects.
    Position orthographic camera to frame the mesh with 15% padding.
    Camera faces front (negative Y), slightly elevated."""
```

**Render loop:**

```python
def render_item(item, cam_obj, work_base):
    """For each item:
    1. Remove previous mesh objects (keep camera + lights)
    2. Purge orphan data
    3. Copy .ydd + textures to temp work dir
    4. Import via Sollumz
    5. Fix missing textures
    6. Fix alpha modes
    7. Frame camera
    8. Render to PNG
    """
```

---

### Step 11: `src/scanner.py` — Batch Orchestrator

**Purpose:** Discover files, coordinate processing, manage parallelism, handle 3D/flat routing.

```python
def scan_and_process(
    input_dir: str, output_dir: str, workers: int = 4,
    dry_run: bool = False, force: bool = False, verbose: bool = False,
    render_3d: bool = False, blender_path: str | None = None,
    batch_size: int = 50,
):
    """Main orchestration function.

    Steps:
    1. build_dlc_map() from .meta files
    2. Walk input_dir, find all *_a_uni.ytd files (case-insensitive)
    3. Parse each filename → YtdFileInfo (skip non-matching)
    4. Determine DLC name: prefer meta-derived mapping, fall back to filename
    5. Build output paths: {output_dir}/textures/{dlcName}/{gender}/{category}/{drawableId:03d}.webp
    6. Skip if output .webp already exists (unless force=True)
    7. If render_3d: pair with .ydd files, split into 3d_items / flat_items
    8. Process 3D items via Blender (falls back to flat on failure)
    9. Process flat items via ProcessPoolExecutor(max_workers=workers)
    10. Collect results, build catalog
    11. Write catalog.json
    12. Print summary with timing
    """
```

**Worker function (runs in subprocess for flat pipeline):**

```python
def process_single_ytd(ytd_path: str, output_webp_path: str) -> dict:
    """Process a single .ytd file end-to-end. MUST be top-level for pickling.

    Returns: {"original_width": int, "original_height": int, "format": str}
    """
```

**DLC name resolution priority:**
1. Meta-derived mapping: `dlc_map[resource_pack_dir_name]`
2. Filename-derived: `YtdFileInfo.dlc_name`

---

### Step 12: `cli.py` — Command Line Interface

```python
"""
Usage:
    python cli.py [OPTIONS]

Options:
    --input PATH       Root stream/ directory (default: ./stream)
    --output PATH      Output directory (default: ./output)
    --workers INT      Parallel workers (default: 4)
    --dry-run          Scan and report counts only
    --force            Re-process even if .webp exists
    --verbose          Per-file progress output
    --single FILE      Process a single .ytd file (for debugging)
    --render-3d        Use Blender 3D rendering (requires Blender + Sollumz)
    --blender-path     Path to Blender executable (default: auto-detect)
    --batch-size INT   Items per Blender session (default: 50)
    --log-level        DEBUG/INFO/WARNING/ERROR (default: WARNING)
"""
```

The `--single` flag is critical for development — test the full pipeline on one file before batch processing 1,246 files. When `--single` is used on a file that doesn't match the naming pattern, it outputs to `debug.webp`.

---

## Error Handling Matrix

| Error | Detection | Action |
|-------|-----------|--------|
| File too small (<32 bytes) | Size check before parsing | Skip, log "file too small" |
| Bad RSC7 magic | First 4 bytes != `RSC7` | Skip, log "not RSC7 format" |
| Decompression failure | `zlib.error` exception | Skip, log zlib error message |
| Bad page sizes (0 or huge) | `get_size_from_flags` returns 0 or > decompressed size | Skip, log "invalid flags" |
| No textures in dictionary | Texture count = 0 | Skip, log "empty texture dictionary" |
| All textures are normal/specular | `select_diffuse_texture` returns None | Skip, log "no diffuse texture found" |
| Unknown DDS format code | Format not in `TEXTURE_FORMATS` dict | Skip, log format code for future support |
| DDS header construction failure | Exception in `build_dds` | Skip, log error |
| Pillow can't decode DDS | `Image.open()` raises | Try pydds fallback, if both fail: skip, log |
| WebP save failure | `canvas.save()` raises | Skip, log error |
| Filename doesn't match pattern | `parse_ytd_filename` returns None | Skip, log "unrecognized filename pattern" |
| No .ydd model found (3D mode) | `find_ydd_for_ytd` returns None | Fall back to flat rendering |
| Sollumz import failure | `import_ydd` returns False | Fall back to flat rendering |
| Blender subprocess crash | Non-zero exit code or timeout | Retry with smaller batch, then fall back to flat |
| Empty 3D render (black square) | `is_image_empty()` returns True | Fall back to flat rendering |
| DXT5/BC7 alpha transparency bug | Materials use BLEND alpha mode | Fix: switch to CLIP, disconnect alpha, set to 1.0 |
| Missing textures in Blender | DiffuseSampler has no image data | Force-load DDS files by name or use first available |

Every failure is **non-fatal**. The batch always continues. Failed files are logged to `output/failed/{key}.log` with source path, output path, and error message.

---

## Execution Order

This is the build sequence — each step should be completed and tested before moving to the next.

### Phase 1: Foundation (can run `--single` on one file)

1. **`src/rsc7.py`** + test with a real `.ytd` file
   - Test: decompress a known `.ytd`, verify virtual/physical sizes are non-zero

2. **`src/ytd_parser.py`** + test
   - Test: parse decompressed data, verify at least one texture extracted with valid dimensions
   - Test: verify pointer resolution works for both virtual and physical segments

3. **`src/dds_builder.py`** + test
   - Test: build DDS from extracted texture, verify magic bytes `"DDS "` and header is 124 bytes
   - Test: verify BC7 produces DX10 extended header

4. **`src/image_processor.py`** + test
   - Test: open built DDS with Pillow, convert to .webp, verify output file exists and is valid
   - Test: verify non-square textures (e.g. 1024x2048) are properly centered on canvas
   - Test: verify `is_image_empty()` detects transparent images and accepts opaque ones

### Phase 2: Metadata (can parse filenames and .meta files)

5. **`src/meta_parser.py`** + test
   - Test: parse real `.meta` files, verify dlcName extraction
   - Test: verify non-apparel meta files are skipped

6. **`src/filename_parser.py`** + test
   - Test: parse standard freemode filenames
   - Test: parse custom ped filenames
   - Test: handle DLC names with underscores (`.+?` non-greedy pattern)
   - Test: `count_variants()` returns correct sibling count

### Phase 3: Orchestration (full batch processing)

7. **`src/catalog.py`** + test
   - Test: add items, verify key format `{dlc}_{gender}_{cat}_{id:03d}`
   - Test: write catalog.json, verify JSON structure and camelCase fields
   - Test: sorted output keys

8. **`src/scanner.py`**
   - Integrate all modules
   - Test: `--dry-run` mode
   - Test: `--single` on one file from each resource pack

9. **`cli.py`**
   - Wire up argparse
   - Test: full batch with `--verbose`

### Phase 4: 3D Rendering (optional feature)

10. **`src/ydd_pairer.py`** + test
    - Test: pair known .ytd with .ydd files
    - Test: prefer `_u` suffix over `_r`

11. **`src/blender_renderer.py`**
    - Test: DDS extraction from all variant YTDs
    - Test: manifest generation
    - Test: Blender subprocess invocation
    - Test: PNG→WebP conversion

12. **`src/blender_script.py`**
    - Test: scene setup in Blender
    - Test: Sollumz import
    - Test: texture fixing, alpha mode fixing
    - Test: camera framing
    - Test: render output

### Phase 5: Validation

13. Run `python cli.py --dry-run` to verify discovery
14. Run `python cli.py --single <file>` on files from different resource packs
15. Run full flat batch: `python cli.py --workers 4 --verbose`
16. Verify catalog.json: expected item count, all referenced `.webp` files exist, no zero-byte outputs
17. Spot-check .webp outputs visually
18. (Optional) Run with `--render-3d` and verify 3D renders

---

## Testing Strategy

### Unit Tests

Located in `tests/`, run with `pytest`.

**`tests/test_catalog.py`** — CatalogBuilder tests:
- Key format validation (`{dlc}_{gender}_{cat}_{id:03d}`)
- Duplicate key overwrites last value
- Failure recording
- JSON output structure (camelCase fields, sorted keys, `generated_at` timestamp)
- Empty catalog handling

**`tests/test_black_square_008.py`** — Regression test for alpha transparency bug:
- Uses real fixture: `rhclothing^accs_diff_008_a_uni.ytd` (1024x2048 DXT5, ~87% transparent)
- Validates RSC7 parsing, texture extraction, DDS building
- Verifies flat render produces visible image (>1000 visible pixels)
- Verifies flat render has color variation (not solid black/white)
- Tests `is_image_empty()` with transparent, opaque, sparse, and real texture images

### Integration Testing

- **Manual spot-check**: Pick one `.ytd` from each resource pack, process it, visually verify
- **Known-good reference**: Open same `.ytd` in OpenIV or CodeWalker, export texture, compare
- **Full batch validation**: After batch run, verify catalog.json counts, all `.webp` files exist, no zero-byte outputs

---

## Known Bugs & Lessons Learned

### 1. DLC Names With Underscores

**Problem:** Original regex `[a-zA-Z0-9]+` for dlcname failed on filenames like `mp_f_freemode_01_mp_f_gunrunning_01^accs_diff_000_a_uni.ytd` where the DLC name itself contains underscores.

**Fix:** Use `.+?` (non-greedy) to capture everything between the model prefix and the `^` separator.

### 2. Black Square / Invisible Garment in 3D Renders

**Problem:** DXT5 and BC7 textures often have alpha channels where large regions (UV-unused areas) are fully transparent. When Sollumz imports the model and sets materials to BLEND alpha mode, the entire garment becomes invisible.

**Fix:** After import, force all materials to CLIP alpha mode with a very low threshold (0.01), disconnect the alpha channel from the Principled BSDF node, and set alpha input to 1.0.

### 3. Missing Textures in Blender

**Problem:** Sollumz auto-texture lookup only works when the internal texture name matches the material's image reference. Many assets use arbitrary names (`p1`, `1`, `Swatch_1_Diffuse_1`) that never match.

**Fix:** After import, find every `DiffuseSampler` image node with no pixel data and replace it with the matching DDS file (by name), or fall back to the first available DDS as default.

### 4. Variant Textures Needed for 3D Rendering

**Problem:** A model's material may reference a texture name that exists in a variant YTD (`_b_`, `_c_`), not the base `_a_`. If we only extract from `_a_`, the material has no texture.

**Fix:** Extract DDS textures from ALL sibling variant YTDs, deduplicating by texture name.

### 5. A8 Format Pillow Incompatibility

**Problem:** Pillow's DDS loader doesn't support the pure-alpha pixel format flag (0x2) used for A8 textures.

**Fix:** Emit A8 format as L8 (luminance) in the DDS header since they have identical data layout (1 byte per pixel).

### 6. Physical Data Undersize

**Problem:** Some textures report a data size (calculated from dimensions + mip levels) larger than what's actually available in the physical segment.

**Fix:** Clamp data extraction to `min(calculated_size, available_bytes)` rather than failing.

---

## Edge Cases

1. **`new_overlays/` resource pack** — Contains `rushtattoo_*.ytd` tattoo overlays, not clothing. Decision: **skip** (filename pattern won't match).

2. **`[replacements]` directory** — Contains replacement textures with potentially different naming. Decision: **skip** unless filename pattern matches.

3. **`[strafe]` custom ped (rhpeds)** — Uses `strafe^accs_diff_001_a_uni.ytd` naming (no `mp_f_`/`mp_m_` prefix). Handled by `CUSTOM_PED_PATTERN` regex. Gender = `"unknown"`, dlc_name = model name.

4. **Files with 0 textures** — Empty stub `.ytd` files. Skip gracefully.

5. **Multiple diffuse textures** — Rare. Selection logic picks largest by pixel count.

6. **Non-square textures** — Common (e.g. 1024x2048). Handled by aspect-ratio-preserving resize + centering on transparent canvas.

7. **Files < 32 bytes** — Corrupt/empty stubs (some as small as 65 bytes). Skip with size check.

8. **Textures with high transparency** — (e.g. accs_008: 87% transparent). Flat pipeline handles these correctly. 3D pipeline needs alpha fix + empty detection fallback.

9. **`os.path.dirname("")`** returns `""` — When output_path has no directory component, `os.makedirs("")` would fail. Guard with `or "."`.

---

## Performance Estimates

- **1,246 files** to process
- **Flat pipeline:** ~50-200ms per file → with 4 workers: ~1-4 minutes total
- **3D pipeline:** ~2-5 seconds per file in Blender → ~40-100 minutes for all items
- Output size: ~1,246 files * ~50KB avg = ~60MB of .webp files

---

## Key References

- **CodeWalker source** (C#): https://github.com/dexyfex/CodeWalker
  - `RpfFile.cs` — RSC7 header, flags, decompression
  - `Resources/Texture.cs` — TextureDictionary, Texture structs
  - `Resources/ResourceBuilder.cs` — Compress/Decompress
  - `Resources/ResourceDataReader.cs` — Pointer resolution
  - `FileTypes/YtdFile.cs` — Top-level YTD loading
- **ytdtool** (C): https://github.com/kngrektor/ytdtool
- **Pillow DDS support**: https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#dds
- **DDS file format**: https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dx-graphics-dds-pguide
- **Sollumz** (Blender addon): https://github.com/Skylumz/Sollumz — GTA V model import/export for Blender
- **Blender Python API**: https://docs.blender.org/api/current/ — bpy reference for headless rendering
