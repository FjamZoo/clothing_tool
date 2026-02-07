"""
YTD Texture Dictionary Parser

Parses the TextureDictionary structure from decompressed RSC7 virtual/physical
segments and extracts individual texture metadata + raw pixel data.

GTA V RSC7 resources use two virtual address spaces:
  - 0x50000000 base -> virtual segment (struct data)
  - 0x60000000 base -> physical segment (raw pixel data)

Pointers in the structs are resolved by subtracting the appropriate base
to get an offset into the corresponding data buffer.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pointer resolution
# ---------------------------------------------------------------------------

VIRTUAL_BASE = 0x50000000
PHYSICAL_BASE = 0x60000000


def resolve_pointer(ptr: int) -> tuple[str, int]:
    """Resolve a GTA V resource pointer to a segment name and offset.

    Returns:
        ('virtual', offset), ('physical', offset), or ('null', 0).

    Raises:
        ValueError: If the pointer doesn't fall in a known address range.
    """
    if ptr == 0:
        return ('null', 0)
    if ptr >= PHYSICAL_BASE:
        return ('physical', ptr - PHYSICAL_BASE)
    if ptr >= VIRTUAL_BASE:
        return ('virtual', ptr - VIRTUAL_BASE)
    raise ValueError(f"Unknown pointer base: 0x{ptr:08X}")


# ---------------------------------------------------------------------------
# Texture format table
# ---------------------------------------------------------------------------

TEXTURE_FORMATS: dict[int, tuple[str, int]] = {
    21:         ("A8R8G8B8", 32),
    22:         ("X8R8G8B8", 32),
    25:         ("A1R5G5B5", 16),
    28:         ("A8", 8),
    32:         ("A8B8G8R8", 32),
    50:         ("L8", 8),
    0x31545844: ("DXT1", 4),
    0x33545844: ("DXT3", 8),
    0x35545844: ("DXT5", 8),
    0x31495441: ("ATI1", 4),
    0x32495441: ("ATI2", 8),
    0x20374342: ("BC7", 8),
}

# Block-compressed formats and their per-block byte sizes
_BLOCK_COMPRESSED = {
    "DXT1": 8,
    "ATI1": 8,
    "DXT3": 16,
    "DXT5": 16,
    "ATI2": 16,
    "BC7":  16,
}


# ---------------------------------------------------------------------------
# Data size calculation
# ---------------------------------------------------------------------------

def _calc_mip_size(width: int, height: int, format_name: str, bpp: int) -> int:
    """Return the byte size of a single mip level."""
    block_size = _BLOCK_COMPRESSED.get(format_name)
    if block_size is not None:
        blocks_x = max(1, (width + 3) // 4)
        blocks_y = max(1, (height + 3) // 4)
        return blocks_x * blocks_y * block_size
    # Uncompressed
    return width * height * (bpp // 8)


def _calc_total_data_size(width: int, height: int, mip_levels: int,
                          format_name: str, bpp: int) -> int:
    """Sum byte sizes across all mip levels."""
    total = 0
    w, h = width, height
    for _ in range(mip_levels):
        total += _calc_mip_size(w, h, format_name, bpp)
        w = max(1, w // 2)
        h = max(1, h // 2)
    return total


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------

@dataclass
class TextureInfo:
    """Parsed texture from a YTD TextureDictionary."""
    name: str
    width: int
    height: int
    format_code: int
    format_name: str
    mip_levels: int
    stride: int
    raw_data: bytes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_null_terminated_string(data: bytes, offset: int, max_len: int = 256) -> str:
    """Read a null-terminated ASCII string from *data* starting at *offset*."""
    end = data.find(b'\x00', offset, offset + max_len)
    if end == -1:
        end = offset + max_len
    return data[offset:end].decode('ascii', errors='replace')


def _read_u16(data: bytes, offset: int) -> int:
    return struct.unpack_from('<H', data, offset)[0]


def _read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from('<I', data, offset)[0]


def _read_u64(data: bytes, offset: int) -> int:
    return struct.unpack_from('<Q', data, offset)[0]


def _read_u8(data: bytes, offset: int) -> int:
    return data[offset]


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def parse_texture_dictionary(
    virtual_data: bytes,
    physical_data: bytes,
) -> list[TextureInfo]:
    """Parse all textures from a decompressed RSC7 resource.

    Args:
        virtual_data:  The virtual (system) segment — struct data.
        physical_data: The physical (graphics) segment — raw pixel data.

    Returns:
        List of TextureInfo, one per texture in the dictionary.

    Raises:
        ValueError: On structural inconsistencies.
    """
    if len(virtual_data) < 64:
        raise ValueError(
            f"Virtual data too small for TextureDictionary header "
            f"({len(virtual_data)} bytes, need >= 64)"
        )

    # ------------------------------------------------------------------
    # TextureDictionary header (64 bytes at virtual offset 0)
    # ------------------------------------------------------------------
    textures_ptr_raw = _read_u64(virtual_data, 0x30)
    textures_ptr = textures_ptr_raw & 0xFFFFFFFF          # lower 32 bits only
    textures_count = _read_u16(virtual_data, 0x38)
    textures_capacity = _read_u16(virtual_data, 0x3A)

    logger.debug(
        "TextureDictionary: textures_ptr=0x%08X count=%d capacity=%d",
        textures_ptr, textures_count, textures_capacity,
    )

    if textures_count == 0:
        logger.warning("TextureDictionary has 0 textures")
        return []

    # Resolve the pointer to the texture-pointer array
    seg, arr_offset = resolve_pointer(textures_ptr)
    if seg != 'virtual':
        raise ValueError(
            f"TexturesPointer resolves to '{seg}' segment — expected 'virtual'"
        )

    # ------------------------------------------------------------------
    # Read array of 64-bit pointers (one per texture)
    # ------------------------------------------------------------------
    tex_pointers: list[int] = []
    for i in range(textures_count):
        raw_ptr = _read_u64(virtual_data, arr_offset + i * 8)
        tex_pointers.append(raw_ptr & 0xFFFFFFFF)

    # ------------------------------------------------------------------
    # Parse each Texture struct (144 bytes)
    # ------------------------------------------------------------------
    results: list[TextureInfo] = []

    for idx, tptr in enumerate(tex_pointers):
        seg, tex_offset = resolve_pointer(tptr)
        if seg != 'virtual':
            logger.warning(
                "Texture #%d pointer resolves to '%s' — skipping", idx, seg
            )
            continue

        if tex_offset + 144 > len(virtual_data):
            logger.warning(
                "Texture #%d at offset %d overflows virtual_data (%d bytes) — skipping",
                idx, tex_offset, len(virtual_data),
            )
            continue

        # --- Name ---
        name_ptr_raw = _read_u64(virtual_data, tex_offset + 0x28)
        name_ptr = name_ptr_raw & 0xFFFFFFFF
        name = ""
        if name_ptr != 0:
            nseg, noff = resolve_pointer(name_ptr)
            if nseg == 'virtual' and noff < len(virtual_data):
                name = _read_null_terminated_string(virtual_data, noff)
            else:
                logger.debug("Texture #%d name pointer in '%s' segment", idx, nseg)

        # --- Dimensions and format ---
        width = _read_u16(virtual_data, tex_offset + 0x50)
        height = _read_u16(virtual_data, tex_offset + 0x52)
        stride = _read_u16(virtual_data, tex_offset + 0x56)
        format_code = _read_u32(virtual_data, tex_offset + 0x58)
        mip_levels = _read_u8(virtual_data, tex_offset + 0x5D)

        fmt_entry = TEXTURE_FORMATS.get(format_code)
        if fmt_entry is not None:
            format_name, bpp = fmt_entry
        else:
            format_name = f"UNKNOWN(0x{format_code:X})"
            bpp = 0
            logger.warning(
                "Texture #%d '%s': unknown format code 0x%X",
                idx, name, format_code,
            )

        # --- Data pointer ---
        data_ptr_raw = _read_u64(virtual_data, tex_offset + 0x70)
        data_ptr = data_ptr_raw & 0xFFFFFFFF
        raw_data = b""

        if data_ptr != 0 and bpp > 0:
            dseg, doff = resolve_pointer(data_ptr)
            if dseg == 'physical':
                # Calculate expected total size across all mip levels
                data_size = _calc_total_data_size(
                    width, height, max(1, mip_levels), format_name, bpp,
                )
                # Clamp to available data
                available = len(physical_data) - doff
                if available < data_size:
                    logger.debug(
                        "Texture #%d '%s': expected %d bytes but only %d available "
                        "— clamping",
                        idx, name, data_size, available,
                    )
                    data_size = max(0, available)
                raw_data = physical_data[doff:doff + data_size]
            else:
                logger.debug(
                    "Texture #%d '%s': data pointer in '%s' segment",
                    idx, name, dseg,
                )

        logger.debug(
            "Texture #%d: name='%s' %dx%d fmt=%s mips=%d stride=%d data=%d bytes",
            idx, name, width, height, format_name, mip_levels, stride, len(raw_data),
        )

        results.append(TextureInfo(
            name=name,
            width=width,
            height=height,
            format_code=format_code,
            format_name=format_name,
            mip_levels=mip_levels,
            stride=stride,
            raw_data=raw_data,
        ))

    return results


# ---------------------------------------------------------------------------
# Diffuse texture selector
# ---------------------------------------------------------------------------

# Suffixes that indicate non-diffuse texture channels
_NON_DIFFUSE_SUFFIXES = ('_n', '_s', '_m')


def select_diffuse_texture(textures: list[TextureInfo]) -> TextureInfo | None:
    """Pick the diffuse texture from a texture dictionary.

    Selection rules:
      1. If only one texture, return it regardless of name.
      2. Exclude textures whose names end with _n (normal), _s (specular),
         or _m (mask).
      3. From the remaining candidates, pick the one with the highest
         resolution (width * height).
      4. If all textures are excluded by name, return None.
    """
    if not textures:
        return None

    if len(textures) == 1:
        return textures[0]

    candidates = [
        t for t in textures
        if not any(t.name.lower().endswith(sfx) for sfx in _NON_DIFFUSE_SUFFIXES)
    ]

    if not candidates:
        return None

    return max(candidates, key=lambda t: t.width * t.height)
