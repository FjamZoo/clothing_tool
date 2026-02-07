"""
DDS File Builder

Constructs valid DDS files from TextureInfo objects (raw pixel data with no
DDS header) so they can be opened by Pillow via Image.open(BytesIO(dds_bytes)).

Supports: DXT1, DXT3, DXT5, ATI1, ATI2, BC7, A8R8G8B8, L8, A8.

BC7 textures use the DX10 extended header (DXGI_FORMAT_BC7_UNORM = 98).
All other block-compressed formats use the classic FourCC pixel format.
"""

from __future__ import annotations

import struct
from src.ytd_parser import TextureInfo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DDS_MAGIC = b"DDS "  # 0x20534444

# dwFlags bitmask for DDS_HEADER
_DDSD_CAPS        = 0x1
_DDSD_HEIGHT      = 0x2
_DDSD_WIDTH       = 0x4
_DDSD_PIXELFORMAT = 0x1000
_DDSD_MIPMAPCOUNT = 0x20000
_DDSD_LINEARSIZE  = 0x80000
_HEADER_FLAGS = (
    _DDSD_CAPS | _DDSD_HEIGHT | _DDSD_WIDTH
    | _DDSD_PIXELFORMAT | _DDSD_MIPMAPCOUNT | _DDSD_LINEARSIZE
)  # 0x000A1007

# dwCaps
_DDSCAPS_TEXTURE = 0x1000
_DDSCAPS_MIPMAP  = 0x400000
_DDSCAPS_COMPLEX = 0x8
_HEADER_CAPS = _DDSCAPS_TEXTURE | _DDSCAPS_MIPMAP | _DDSCAPS_COMPLEX  # 0x401008

# DDS_PIXELFORMAT dwFlags
_DDPF_ALPHAPIXELS = 0x1
_DDPF_ALPHA       = 0x2
_DDPF_FOURCC      = 0x4
_DDPF_RGB         = 0x40
_DDPF_LUMINANCE   = 0x20000

# FourCC codes (little-endian u32)
_FOURCC_DXT1 = 0x31545844
_FOURCC_DXT3 = 0x33545844
_FOURCC_DXT5 = 0x35545844
_FOURCC_ATI1 = 0x31495441
_FOURCC_ATI2 = 0x32495441
_FOURCC_DX10 = 0x30315844

# Block sizes in bytes per 4x4 block
_BLOCK_SIZES: dict[str, int] = {
    "DXT1": 8,
    "ATI1": 8,
    "DXT3": 16,
    "DXT5": 16,
    "ATI2": 16,
    "BC7":  16,
}

# FourCC lookup for classic block-compressed formats
_FOURCC_MAP: dict[str, int] = {
    "DXT1": _FOURCC_DXT1,
    "DXT3": _FOURCC_DXT3,
    "DXT5": _FOURCC_DXT5,
    "ATI1": _FOURCC_ATI1,
    "ATI2": _FOURCC_ATI2,
}


# ---------------------------------------------------------------------------
# Pixel-data size helpers
# ---------------------------------------------------------------------------

def _mip0_size(width: int, height: int, format_name: str) -> int:
    """Calculate the byte size of the first mip level."""
    block_size = _BLOCK_SIZES.get(format_name)
    if block_size is not None:
        blocks_x = max(1, (width + 3) // 4)
        blocks_y = max(1, (height + 3) // 4)
        return blocks_x * blocks_y * block_size

    # Uncompressed formats
    if format_name in ("A8R8G8B8", "X8R8G8B8", "A8B8G8R8"):
        return width * height * 4
    if format_name in ("A1R5G5B5",):
        return width * height * 2
    if format_name in ("L8", "A8"):
        return width * height * 1

    raise ValueError(f"Cannot compute mip0 size for format: {format_name}")


# ---------------------------------------------------------------------------
# DDS_PIXELFORMAT builders (32 bytes each)
# ---------------------------------------------------------------------------

def _pixfmt_fourcc(fourcc: int) -> bytes:
    """Build a 32-byte DDS_PIXELFORMAT for a FourCC-based format."""
    return struct.pack(
        "<II4sIIIII",
        32,             # dwSize
        _DDPF_FOURCC,   # dwFlags
        struct.pack("<I", fourcc),  # dwFourCC as 4 raw bytes
        0, 0, 0, 0, 0, # dwRGBBitCount, masks — unused for FourCC
    )


def _pixfmt_a8r8g8b8() -> bytes:
    """32-byte DDS_PIXELFORMAT for uncompressed A8R8G8B8."""
    return struct.pack(
        "<IIIIIIII",
        32,                              # dwSize
        _DDPF_RGB | _DDPF_ALPHAPIXELS,  # dwFlags = 0x41
        0,                               # dwFourCC (unused)
        32,                              # dwRGBBitCount
        0x00FF0000,                      # dwRBitMask
        0x0000FF00,                      # dwGBitMask
        0x000000FF,                      # dwBBitMask
        0xFF000000,                      # dwABitMask
    )


def _pixfmt_l8() -> bytes:
    """32-byte DDS_PIXELFORMAT for L8 (8-bit luminance)."""
    return struct.pack(
        "<IIIIIIII",
        32,              # dwSize
        _DDPF_LUMINANCE, # dwFlags = 0x20000
        0,               # dwFourCC
        8,               # dwRGBBitCount
        0xFF,            # dwRBitMask
        0,               # dwGBitMask
        0,               # dwBBitMask
        0,               # dwABitMask
    )


def _pixfmt_a8() -> bytes:
    """32-byte DDS_PIXELFORMAT for A8 (8-bit alpha only)."""
    return struct.pack(
        "<IIIIIIII",
        32,          # dwSize
        _DDPF_ALPHA, # dwFlags = 0x2
        0,           # dwFourCC
        8,           # dwRGBBitCount
        0,           # dwRBitMask
        0,           # dwGBitMask
        0,           # dwBBitMask
        0xFF,        # dwABitMask
    )


def _build_pixelformat(format_name: str) -> bytes:
    """Return the 32-byte DDS_PIXELFORMAT for the given format."""
    # Classic FourCC block-compressed formats
    if format_name in _FOURCC_MAP:
        return _pixfmt_fourcc(_FOURCC_MAP[format_name])

    # BC7 uses DX10 extended header — FourCC is "DX10"
    if format_name == "BC7":
        return _pixfmt_fourcc(_FOURCC_DX10)

    # Uncompressed formats
    if format_name in ("A8R8G8B8", "X8R8G8B8", "A8B8G8R8"):
        return _pixfmt_a8r8g8b8()
    if format_name == "L8":
        return _pixfmt_l8()
    if format_name == "A8":
        # Pillow's DDS loader doesn't support the pure-alpha pixel format
        # flag (0x2).  A8 and L8 have the same data layout (1 byte/pixel),
        # so we emit it as luminance so Pillow can open it.
        return _pixfmt_l8()

    raise ValueError(f"Unsupported DDS pixel format: {format_name}")


# ---------------------------------------------------------------------------
# DDS_HEADER_DXT10 (20 bytes, only for BC7)
# ---------------------------------------------------------------------------

def _build_dx10_header() -> bytes:
    """Build the 20-byte DDS_HEADER_DXT10 extension for BC7."""
    return struct.pack(
        "<IIIII",
        98,  # dxgiFormat = DXGI_FORMAT_BC7_UNORM
        3,   # resourceDimension = D3D10_RESOURCE_DIMENSION_TEXTURE2D
        0,   # miscFlag
        1,   # arraySize
        0,   # miscFlags2
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_dds(texture: TextureInfo) -> bytes:
    """Construct a complete DDS file from a TextureInfo.

    Returns bytes openable by Pillow via Image.open(BytesIO(dds_bytes)).
    Raises ValueError for unsupported formats.
    """
    fmt = texture.format_name
    w = texture.width
    h = texture.height
    mips = max(1, texture.mip_levels)

    # Compute linear size of the first mip level
    linear_size = _mip0_size(w, h, fmt)

    # Build the pixel format block (32 bytes)
    pixfmt = _build_pixelformat(fmt)

    # --- Assemble the 124-byte DDS_HEADER ---
    header = struct.pack(
        "<I",     # dwSize
        124,
    )
    header += struct.pack(
        "<I",     # dwFlags
        _HEADER_FLAGS,
    )
    header += struct.pack(
        "<I",     # dwHeight
        h,
    )
    header += struct.pack(
        "<I",     # dwWidth
        w,
    )
    header += struct.pack(
        "<I",     # dwPitchOrLinearSize
        linear_size,
    )
    header += struct.pack(
        "<I",     # dwDepth
        0,
    )
    header += struct.pack(
        "<I",     # dwMipMapCount
        mips,
    )
    header += b"\x00" * 44            # dwReserved1[11] — 11 x uint32 = 44 bytes
    header += pixfmt                   # ddspf — 32 bytes
    header += struct.pack(
        "<I",     # dwCaps
        _HEADER_CAPS,
    )
    header += b"\x00" * 16            # dwCaps2, dwCaps3, dwCaps4, dwReserved2

    assert len(header) == 124, f"DDS header should be 124 bytes, got {len(header)}"

    # --- Assemble the full DDS file ---
    parts = [DDS_MAGIC, header]

    if fmt == "BC7":
        parts.append(_build_dx10_header())

    parts.append(texture.raw_data)

    return b"".join(parts)
