"""
RSC7 Container Parser

Opens a .ytd file, validates the RSC7 header, decompresses the payload,
and splits it into virtual (struct) and physical (pixel data) segments.

RSC7 Header (16 bytes, little-endian):
    Offset  Size  Field           Description
    0x00    4     magic           0x37435352 ("RSC7")
    0x04    4     version         13 = PC/legacy, 5 = Gen9
    0x08    4     system_flags    Encodes virtual segment page sizes
    0x0C    4     graphics_flags  Encodes physical segment page sizes
"""

from __future__ import annotations

import logging
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

RSC7_MAGIC = 0x37435352
RSC7_HEADER_SIZE = 16
MINIMUM_FILE_SIZE = 32
EXPECTED_VERSION = 13


@dataclass
class RSC7Resource:
    """Decompressed RSC7 resource with virtual and physical segments."""
    version: int
    virtual_data: bytes   # Contains struct data (TextureDictionary, Texture headers)
    physical_data: bytes  # Contains raw pixel data


def get_size_from_flags(flags: int) -> int:
    """Calculate decompressed segment size from an RSC7 flag field.

    Ported from CodeWalker RpfFile.cs — each flag encodes a combination
    of page counts at different size multiples of a base page size.
    """
    s0 = ((flags >> 27) & 0x1) << 0
    s1 = ((flags >> 26) & 0x1) << 1
    s2 = ((flags >> 25) & 0x1) << 2
    s3 = ((flags >> 24) & 0x1) << 3
    s4 = ((flags >> 17) & 0x7F) << 4
    s5 = ((flags >> 11) & 0x3F) << 5
    s6 = ((flags >> 7) & 0xF) << 6
    s7 = ((flags >> 5) & 0x3) << 7
    s8 = ((flags >> 4) & 0x1) << 8
    ss = (flags >> 0) & 0xF
    base_size = 0x200 << ss
    total = s0 + s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8
    return base_size * total


def parse_rsc7(file_path: str | Path) -> RSC7Resource:
    """Parse an RSC7 container file, returning decompressed virtual and physical segments.

    Args:
        file_path: Path to the .ytd file.

    Returns:
        RSC7Resource with version, virtual_data, and physical_data.

    Raises:
        ValueError: If the file is too small, has invalid magic, or segment
                    sizes exceed the decompressed data length.
        zlib.error: If decompression of the payload fails.
        FileNotFoundError: If the file does not exist.
    """
    path = Path(file_path)
    raw = path.read_bytes()

    # --- Minimum size check ---
    if len(raw) < MINIMUM_FILE_SIZE:
        raise ValueError(
            f"File too small ({len(raw)} bytes, minimum {MINIMUM_FILE_SIZE}): {path.name}"
        )

    # --- Parse 16-byte header ---
    magic, version, system_flags, graphics_flags = struct.unpack_from("<4I", raw, 0)

    if magic != RSC7_MAGIC:
        raise ValueError(
            f"Invalid RSC7 magic: 0x{magic:08X} (expected 0x{RSC7_MAGIC:08X}) in {path.name}"
        )

    if version != EXPECTED_VERSION:
        logger.warning(
            "Unexpected RSC7 version %d (expected %d) in %s — attempting anyway",
            version, EXPECTED_VERSION, path.name,
        )

    # --- Compute expected segment sizes ---
    virtual_size = get_size_from_flags(system_flags)
    physical_size = get_size_from_flags(graphics_flags)

    logger.debug(
        "%s: version=%d  system_flags=0x%08X  graphics_flags=0x%08X  "
        "virtual_size=%d  physical_size=%d",
        path.name, version, system_flags, graphics_flags,
        virtual_size, physical_size,
    )

    # --- Decompress payload (raw deflate, no zlib/gzip wrapper) ---
    compressed_data = raw[RSC7_HEADER_SIZE:]
    decompressed = zlib.decompress(compressed_data, -15)

    # --- Validate segment sizes against decompressed length ---
    expected_total = virtual_size + physical_size
    if expected_total > len(decompressed):
        raise ValueError(
            f"Segment sizes ({virtual_size} + {physical_size} = {expected_total}) "
            f"exceed decompressed data length ({len(decompressed)}) in {path.name}"
        )

    # --- Split into virtual and physical segments ---
    virtual_data = decompressed[:virtual_size]
    physical_data = decompressed[virtual_size:virtual_size + physical_size]

    return RSC7Resource(
        version=version,
        virtual_data=virtual_data,
        physical_data=physical_data,
    )
