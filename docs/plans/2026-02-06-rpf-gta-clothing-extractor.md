# RPF7 GTA V Base Clothing Extractor — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A standalone Python script that reads GTA V's RPF archives directly from the game install directory, finds all freemode ped clothing textures (male + female), identifies their DLC/collection name, and exports the `.ytd` files into an organized folder structure grouped by collection — ready for the existing clothing_tool extraction pipeline to process.

**Architecture:** The script traverses the GTA V directory, opens RPF7 archives (handling NG encryption via CodeWalker's pre-extracted key files), recursively descends into nested RPFs, locates all `mp_f_freemode_01_*` and `mp_m_freemode_01_*` directories containing clothing `.ytd` files, and extracts them into `output/{collection_name}/[female]/` or `output/{collection_name}/[male]/` folders. The collection name is derived from the RPF path (DLC pack name + ped folder name).

**Tech Stack:** Python 3.10+, struct, zlib, pathlib. No new dependencies beyond stdlib.

---

## Context & Key Technical Facts

### RPF7 Archive Format
- **Magic:** `0x52504637` ("RPF7") — 4 bytes LE at offset 0
- **Header:** 16 bytes total: `(magic, entry_count, names_length, encryption_type)`
- **Encryption types:**
  - `0x4E45504F` ("OPEN") — unencrypted (modded RPFs)
  - `0x0FFFFFF9` — AES-256-ECB
  - `0x0FEFFFFF` — NG (Rockstar custom cipher, PC version)
- **After header:** Entry table (`entry_count * 16` bytes) + Name table (`names_length` bytes) — these are what gets encrypted
- **Entry types** (each 16 bytes, determined by 2nd uint32):
  - Directory: 2nd uint32 == `0x7FFFFF00` → `(name_offset, 0x7FFFFF00, entries_index, entries_count)`
  - Binary file: bit 31 of 2nd uint32 clear → nested RPFs, .meta files
  - Resource file: bit 31 of 2nd uint32 set → `.ytd`, `.ydd`, `.yft` etc.
- **File offsets** are in 512-byte blocks: `actual_pos = file_offset * 512`
- **Nested RPFs:** RPFs can contain other RPFs (binary file entries). Clothing data is typically 2-3 levels deep.

### NG Decryption
- Key selection: `key_index = (gta5_hash(rpf_filename) + file_size + 101 - 40) % 101`
- `gta5_hash()` uses a 256-byte LUT (NOT standard Jenkins)
- 17-round block cipher on 16-byte blocks, with lookup tables (17×16×256 uint32s)
- Keys are pre-extracted by CodeWalker into `Keys/` folder as `.dat` files
- We read 4 files: `gtav_aes_key.dat` (32B), `gtav_ng_key.dat` (27,472B), `gtav_ng_decrypt_tables.dat` (278,528B), `gtav_hash_lut.dat` (256B)

### GTA V Clothing RPF Paths
```
GTA V Install/
  x64v.rpf                           ← base game (has streamedpeds_mp.rpf inside)
  update/
    x64/
      dlcpacks/
        mpheist/dlc.rpf/             ← each DLC has a dlc.rpf (sometimes dlc1.rpf too)
          x64/models/cdimages/
            mpheist_female.rpf/      ← inner RPF with female clothing
              mp_f_freemode_01_mp_f_heist/
                accs_diff_000_a_uni.ytd
                jbib_diff_000_a_uni.ytd
                ...
            mpheist_male.rpf/
              mp_m_freemode_01_mp_m_heist/
                ...
```

### Collection Name Derivation
Inside each DLC's inner RPF, directories are named like:
- `mp_f_freemode_01_mp_f_heist` → collection = `mp_f_heist` (strip `mp_f_freemode_01_` prefix)
- `mp_m_freemode_01_mp_m_heist` → collection = `mp_m_heist`
- But we want the **DLC-level** collection name to group male+female together, so:
  - DLC pack folder name: `mpheist` → collection = `mpheist`
  - Or we can use the ped subfolder name to preserve the exact in-game DLC reference

The output structure we want:
```
output/
  mpheist/
    [female]/
      mp_f_freemode_01_mp_f_heist^accs_diff_000_a_uni.ytd
      ...
    [male]/
      mp_m_freemode_01_mp_m_heist^accs_diff_000_a_uni.ytd
      ...
  mpluxe/
    [female]/
      ...
```

The `.ytd` files inside RPFs have short names like `accs_diff_000_a_uni.ytd`. We need to **reconstruct** the full freemode filename by prepending `{ped_folder_name}^` so the existing clothing_tool pipeline can parse them (it expects the `mp_f_freemode_01_{dlcname}^{category}_diff_...` pattern).

---

## Output Structure

```
rpf_extract/
  rpf_extractor.py          ← standalone CLI script
  src/
    __init__.py
    rpf7_parser.py           ← RPF7 archive reading + entry tree
    ng_crypto.py             ← NG decryption + AES decryption + GTA5 hash
    clothing_finder.py       ← traversal logic to find clothing dirs + extract
  tests/
    __init__.py
    test_ng_crypto.py
    test_rpf7_parser.py
    test_clothing_finder.py
```

This lives at `C:\Users\lauri\Desktop\scripts\clothing_tool\rpf_extract\` — a sibling directory structure inside the project but completely independent from the existing `src/` pipeline.

---

## Task 1: Project Scaffolding

**Files:**
- Create: `rpf_extract/src/__init__.py`
- Create: `rpf_extract/tests/__init__.py`

**Step 1: Create directory structure**

```bash
mkdir -p rpf_extract/src rpf_extract/tests
```

**Step 2: Create empty init files**

Create `rpf_extract/src/__init__.py` — empty file.
Create `rpf_extract/tests/__init__.py` — empty file.

**Step 3: Commit**

```bash
git add rpf_extract/
git commit -m "scaffold: rpf_extract project structure"
```

---

## Task 2: NG Crypto Module — Key Loading

**Files:**
- Create: `rpf_extract/src/ng_crypto.py`
- Create: `rpf_extract/tests/test_ng_crypto.py`

This module loads the CodeWalker-extracted `.dat` key files and implements the NG block cipher + GTA5 hash function.

**Step 1: Write the failing test for key loading**

```python
# rpf_extract/tests/test_ng_crypto.py
"""Tests for NG crypto key loading and decryption."""
import struct
import pytest
from rpf_extract.src.ng_crypto import load_ng_keys, NGKeys


class TestLoadKeys:
    """Test loading .dat key files from CodeWalker."""

    def test_load_keys_returns_ng_keys(self, tmp_path):
        """Verify load_ng_keys reads the 4 .dat files and returns an NGKeys object."""
        # Create minimal valid .dat files
        aes_key = bytes(range(32))
        ng_key = b"\x00" * (272 * 101)
        ng_tables = b"\x00" * (17 * 16 * 256 * 4)
        hash_lut = bytes(range(256))

        (tmp_path / "gtav_aes_key.dat").write_bytes(aes_key)
        (tmp_path / "gtav_ng_key.dat").write_bytes(ng_key)
        (tmp_path / "gtav_ng_decrypt_tables.dat").write_bytes(ng_tables)
        (tmp_path / "gtav_hash_lut.dat").write_bytes(hash_lut)

        keys = load_ng_keys(tmp_path)

        assert isinstance(keys, NGKeys)
        assert keys.aes_key == aes_key
        assert len(keys.ng_keys) == 101
        assert len(keys.ng_keys[0]) == 272
        assert len(keys.ng_decrypt_tables) == 17
        assert len(keys.ng_decrypt_tables[0]) == 16
        assert len(keys.ng_decrypt_tables[0][0]) == 256
        assert keys.hash_lut == list(range(256))

    def test_load_keys_missing_file(self, tmp_path):
        """Verify load_ng_keys raises FileNotFoundError for missing .dat files."""
        with pytest.raises(FileNotFoundError):
            load_ng_keys(tmp_path)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest rpf_extract/tests/test_ng_crypto.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Implement key loading**

```python
# rpf_extract/src/ng_crypto.py
"""NG encryption/decryption for GTA V RPF7 archives.

Loads pre-extracted key tables from CodeWalker's Keys/ directory and provides
decryption functions for NG-encrypted RPF7 entry tables and name blocks.

Key files required (from CodeWalker Keys/ folder):
    gtav_aes_key.dat           - 32 bytes, AES-256 key
    gtav_ng_key.dat            - 27,472 bytes (101 expanded key schedules, 272 bytes each)
    gtav_ng_decrypt_tables.dat - 278,528 bytes (17 rounds × 16 positions × 256 entries × 4 bytes)
    gtav_hash_lut.dat          - 256 bytes, lookup table for GTA5 hash function
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass
class NGKeys:
    """Loaded NG crypto key material."""
    aes_key: bytes                           # 32 bytes
    ng_keys: list[bytes]                     # 101 entries, 272 bytes each
    ng_decrypt_tables: list[list[list[int]]] # [17][16][256] of uint32
    hash_lut: list[int]                      # 256 byte values


def load_ng_keys(keys_dir: str | Path) -> NGKeys:
    """Load NG decryption keys from CodeWalker's Keys/ directory.

    Args:
        keys_dir: Path to the directory containing the .dat key files.

    Returns:
        NGKeys with all loaded key material.

    Raises:
        FileNotFoundError: If any required .dat file is missing.
        ValueError: If any file has an unexpected size.
    """
    keys_dir = Path(keys_dir)

    # AES key: 32 bytes
    aes_path = keys_dir / "gtav_aes_key.dat"
    aes_key = aes_path.read_bytes()
    if len(aes_key) != 32:
        raise ValueError(f"Expected 32 bytes for AES key, got {len(aes_key)}")

    # NG keys: 101 × 272 bytes
    ng_key_path = keys_dir / "gtav_ng_key.dat"
    ng_key_data = ng_key_path.read_bytes()
    expected_ng = 101 * 272
    if len(ng_key_data) != expected_ng:
        raise ValueError(f"Expected {expected_ng} bytes for NG keys, got {len(ng_key_data)}")
    ng_keys = [ng_key_data[i * 272:(i + 1) * 272] for i in range(101)]

    # NG decrypt tables: 17 × 16 × 256 × 4 bytes
    tables_path = keys_dir / "gtav_ng_decrypt_tables.dat"
    tables_data = tables_path.read_bytes()
    expected_tables = 17 * 16 * 256 * 4
    if len(tables_data) != expected_tables:
        raise ValueError(f"Expected {expected_tables} bytes for NG tables, got {len(tables_data)}")

    ng_tables: list[list[list[int]]] = []
    offset = 0
    for _round in range(17):
        round_tables: list[list[int]] = []
        for _pos in range(16):
            block = tables_data[offset:offset + 1024]
            round_tables.append(list(struct.unpack("<256I", block)))
            offset += 1024
        ng_tables.append(round_tables)

    # Hash LUT: 256 bytes
    lut_path = keys_dir / "gtav_hash_lut.dat"
    lut_data = lut_path.read_bytes()
    if len(lut_data) != 256:
        raise ValueError(f"Expected 256 bytes for hash LUT, got {len(lut_data)}")
    hash_lut = list(lut_data)

    return NGKeys(
        aes_key=aes_key,
        ng_keys=ng_keys,
        ng_decrypt_tables=ng_tables,
        hash_lut=hash_lut,
    )
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest rpf_extract/tests/test_ng_crypto.py::TestLoadKeys -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rpf_extract/src/ng_crypto.py rpf_extract/tests/test_ng_crypto.py
git commit -m "feat(rpf): add NG crypto key loading from CodeWalker .dat files"
```

---

## Task 3: NG Crypto Module — GTA5 Hash + Block Cipher

**Files:**
- Modify: `rpf_extract/src/ng_crypto.py`
- Modify: `rpf_extract/tests/test_ng_crypto.py`

**Step 1: Write failing tests for gta5_hash and NG decryption**

Add to `rpf_extract/tests/test_ng_crypto.py`:

```python
class TestGTA5Hash:
    """Test the GTA5 custom hash function."""

    def test_hash_empty_string(self):
        """Empty string should return the final avalanche of 0."""
        from rpf_extract.src.ng_crypto import gta5_hash
        # With a zero LUT, all chars map to 0, so hash of "" is just the avalanche of 0
        lut = [0] * 256
        result = gta5_hash("", lut)
        assert result == 0

    def test_hash_deterministic(self):
        """Same input always produces same output."""
        from rpf_extract.src.ng_crypto import gta5_hash
        lut = list(range(256))  # identity LUT
        h1 = gta5_hash("test.rpf", lut)
        h2 = gta5_hash("test.rpf", lut)
        assert h1 == h2
        assert isinstance(h1, int)
        assert 0 <= h1 < 0x100000000

    def test_hash_different_inputs(self):
        """Different filenames produce different hashes."""
        from rpf_extract.src.ng_crypto import gta5_hash
        lut = list(range(256))
        h1 = gta5_hash("dlc.rpf", lut)
        h2 = gta5_hash("update.rpf", lut)
        assert h1 != h2


class TestNGDecryptBlock:
    """Test the NG 16-byte block cipher."""

    def test_decrypt_block_returns_16_bytes(self):
        """Decryption of a 16-byte block returns 16 bytes."""
        from rpf_extract.src.ng_crypto import decrypt_ng_block
        data = bytes(16)
        key = bytes(272)
        # Zero tables — not realistic but tests the plumbing
        tables = [[[0] * 256 for _ in range(16)] for _ in range(17)]
        result = decrypt_ng_block(data, key, tables)
        assert len(result) == 16
        assert isinstance(result, (bytes, bytearray))

    def test_decrypt_block_uses_tables(self):
        """Non-zero tables should produce non-trivial output."""
        from rpf_extract.src.ng_crypto import decrypt_ng_block
        import os
        data = os.urandom(16)
        key = os.urandom(272)
        # Random tables
        import random
        random.seed(42)
        tables = [[[random.randint(0, 0xFFFFFFFF) for _ in range(256)]
                   for _ in range(16)] for _ in range(17)]
        result = decrypt_ng_block(data, key, tables)
        assert len(result) == 16
        # Should be different from input (with overwhelming probability)
        assert result != data


class TestNGDecryptData:
    """Test bulk NG decryption (multi-block)."""

    def test_decrypt_preserves_trailing_bytes(self):
        """Data smaller than 16 bytes should pass through unchanged."""
        from rpf_extract.src.ng_crypto import decrypt_ng_data, NGKeys
        keys = NGKeys(
            aes_key=bytes(32),
            ng_keys=[bytes(272)] * 101,
            ng_decrypt_tables=[[[0] * 256 for _ in range(16)] for _ in range(17)],
            hash_lut=[0] * 256,
        )
        data = b"short"
        result = decrypt_ng_data(data, "test.rpf", 100, keys)
        assert result == data

    def test_decrypt_trailing_bytes_untouched(self):
        """For 20-byte input, first 16 are decrypted, last 4 pass through."""
        from rpf_extract.src.ng_crypto import decrypt_ng_data, NGKeys
        keys = NGKeys(
            aes_key=bytes(32),
            ng_keys=[bytes(272)] * 101,
            ng_decrypt_tables=[[[0] * 256 for _ in range(16)] for _ in range(17)],
            hash_lut=[0] * 256,
        )
        data = bytes(20)
        result = decrypt_ng_data(data, "test.rpf", 100, keys)
        assert len(result) == 20
        # Last 4 bytes should be unchanged (all zeros)
        assert result[16:] == b"\x00\x00\x00\x00"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest rpf_extract/tests/test_ng_crypto.py -v`
Expected: FAIL (functions not defined)

**Step 3: Implement gta5_hash, decrypt_ng_block, decrypt_ng_data**

Add to `rpf_extract/src/ng_crypto.py`:

```python
def gta5_hash(text: str, lut: list[int]) -> int:
    """GTA5's custom hash for NG key selection.

    This is NOT standard Jenkins one-at-a-time. Uses a 256-byte LUT
    and custom mixing constants.

    Args:
        text: The filename string to hash.
        lut: The 256-byte hash lookup table from gtav_hash_lut.dat.

    Returns:
        32-bit unsigned hash value.
    """
    h = 0
    for ch in text:
        idx = ord(ch) & 0xFF
        temp = (1025 * (lut[idx] + h)) & 0xFFFFFFFF
        h = ((temp >> 6) ^ temp) & 0xFFFFFFFF
    step1 = (9 * h) & 0xFFFFFFFF
    step2 = ((step1 >> 11) ^ step1) & 0xFFFFFFFF
    return (32769 * step2) & 0xFFFFFFFF


def decrypt_ng_block(data: bytes | bytearray, key: bytes,
                     tables: list[list[list[int]]]) -> bytearray:
    """Decrypt a single 16-byte block using the NG cipher.

    Args:
        data: Exactly 16 bytes of ciphertext.
        key: 272 bytes (17 round keys × 16 bytes each, read as 68 uint32s).
        tables: [17][16][256] array of uint32 lookup values.

    Returns:
        16-byte decrypted block.
    """
    buf = bytearray(data)
    key_u32 = struct.unpack("<68I", key)

    def round_a(d: bytearray, rk: tuple, tbl: list[list[int]]) -> bytearray:
        x1 = tbl[0][d[0]] ^ tbl[1][d[1]] ^ tbl[2][d[2]] ^ tbl[3][d[3]] ^ rk[0]
        x2 = tbl[4][d[4]] ^ tbl[5][d[5]] ^ tbl[6][d[6]] ^ tbl[7][d[7]] ^ rk[1]
        x3 = tbl[8][d[8]] ^ tbl[9][d[9]] ^ tbl[10][d[10]] ^ tbl[11][d[11]] ^ rk[2]
        x4 = tbl[12][d[12]] ^ tbl[13][d[13]] ^ tbl[14][d[14]] ^ tbl[15][d[15]] ^ rk[3]
        out = bytearray(16)
        struct.pack_into("<4I", out, 0, x1 & 0xFFFFFFFF, x2 & 0xFFFFFFFF,
                         x3 & 0xFFFFFFFF, x4 & 0xFFFFFFFF)
        return out

    def round_b(d: bytearray, rk: tuple, tbl: list[list[int]]) -> bytearray:
        x1 = tbl[0][d[0]] ^ tbl[7][d[7]] ^ tbl[10][d[10]] ^ tbl[13][d[13]] ^ rk[0]
        x2 = tbl[1][d[1]] ^ tbl[4][d[4]] ^ tbl[11][d[11]] ^ tbl[14][d[14]] ^ rk[1]
        x3 = tbl[2][d[2]] ^ tbl[5][d[5]] ^ tbl[8][d[8]] ^ tbl[15][d[15]] ^ rk[2]
        x4 = tbl[3][d[3]] ^ tbl[6][d[6]] ^ tbl[9][d[9]] ^ tbl[12][d[12]] ^ rk[3]
        out = bytearray(16)
        struct.pack_into("<4I", out, 0, x1 & 0xFFFFFFFF, x2 & 0xFFFFFFFF,
                         x3 & 0xFFFFFFFF, x4 & 0xFFFFFFFF)
        return out

    # Rounds 0-1: RoundA
    buf = round_a(buf, key_u32[0:4], tables[0])
    buf = round_a(buf, key_u32[4:8], tables[1])
    # Rounds 2-15: RoundB
    for k in range(2, 16):
        buf = round_b(buf, key_u32[k * 4:(k + 1) * 4], tables[k])
    # Round 16: RoundA
    buf = round_a(buf, key_u32[64:68], tables[16])

    return buf


def decrypt_ng_data(data: bytes, rpf_name: str, rpf_size: int,
                    keys: NGKeys) -> bytes:
    """Decrypt a buffer using NG encryption (entry table or name table).

    Processes 16-byte blocks. Trailing bytes (< 16) are left unchanged.

    Args:
        data: The encrypted bytes.
        rpf_name: The RPF filename (e.g. "dlc.rpf") used for key selection.
        rpf_size: The total RPF file size in bytes, used for key selection.
        keys: Loaded NGKeys instance.

    Returns:
        Decrypted bytes, same length as input.
    """
    key_index = (gta5_hash(rpf_name, keys.hash_lut) + rpf_size + 0x3D) % 0x65
    key = keys.ng_keys[key_index]
    tables = keys.ng_decrypt_tables

    result = bytearray()
    full_blocks = len(data) // 16
    for i in range(full_blocks):
        block = data[i * 16:(i + 1) * 16]
        result.extend(decrypt_ng_block(block, key, tables))

    # Trailing bytes pass through unchanged
    remainder = len(data) % 16
    if remainder:
        result.extend(data[full_blocks * 16:])

    return bytes(result)


def decrypt_aes_data(data: bytes, aes_key: bytes) -> bytes:
    """Decrypt a buffer using AES-256-ECB.

    Processes 16-byte blocks. Trailing bytes are left unchanged.
    Uses Python's built-in hashlib/hmac — no external crypto library needed
    since we can implement AES-ECB with the standard library's AES.

    Note: We use a minimal AES implementation here to avoid requiring
    pycryptodome. If performance is an issue, install pycryptodome and
    switch to Crypto.Cipher.AES.
    """
    try:
        from Crypto.Cipher import AES
        cipher = AES.new(aes_key, AES.MODE_ECB)
        # Process full blocks
        full_len = (len(data) // 16) * 16
        if full_len == 0:
            return data
        decrypted = cipher.decrypt(data[:full_len])
        if full_len < len(data):
            decrypted += data[full_len:]
        return decrypted
    except ImportError:
        raise ImportError(
            "AES decryption requires pycryptodome. Install with: pip install pycryptodome\n"
            "Note: Most GTA V PC RPFs use NG encryption, not AES. AES is only used on console."
        )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest rpf_extract/tests/test_ng_crypto.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rpf_extract/src/ng_crypto.py rpf_extract/tests/test_ng_crypto.py
git commit -m "feat(rpf): implement NG block cipher, GTA5 hash, and AES decryption"
```

---

## Task 4: RPF7 Parser — Header and Entry Table Parsing

**Files:**
- Create: `rpf_extract/src/rpf7_parser.py`
- Create: `rpf_extract/tests/test_rpf7_parser.py`

**Step 1: Write failing tests for RPF7 header + entry parsing**

```python
# rpf_extract/tests/test_rpf7_parser.py
"""Tests for RPF7 archive parsing."""
import struct
import pytest
from rpf_extract.src.rpf7_parser import (
    parse_rpf7_header, RPF7Header, RPF7_MAGIC,
    parse_entries, RPF7DirEntry, RPF7BinaryEntry, RPF7ResourceEntry,
)


def _build_rpf_header(magic=0x52504637, entry_count=1,
                      names_length=8, encryption=0x4E45504F):
    """Build a minimal RPF7 header."""
    return struct.pack("<4I", magic, entry_count, names_length, encryption)


class TestParseHeader:
    def test_valid_header(self):
        data = _build_rpf_header()
        h = parse_rpf7_header(data)
        assert h.magic == 0x52504637
        assert h.entry_count == 1
        assert h.names_length == 8
        assert h.encryption == 0x4E45504F

    def test_invalid_magic(self):
        data = _build_rpf_header(magic=0xDEADBEEF)
        with pytest.raises(ValueError, match="Invalid RPF7 magic"):
            parse_rpf7_header(data)

    def test_too_short(self):
        with pytest.raises(ValueError, match="too small"):
            parse_rpf7_header(b"\x00" * 12)


class TestParseEntries:
    def test_directory_entry(self):
        """Entry with 2nd uint32 == 0x7FFFFF00 is a directory."""
        # name_offset=0, identifier=0x7FFFFF00, entries_index=1, entries_count=3
        entry_data = struct.pack("<4I", 0, 0x7FFFFF00, 1, 3)
        names_data = b"root\x00"
        entries = parse_entries(entry_data, names_data, 1)
        assert len(entries) == 1
        assert isinstance(entries[0], RPF7DirEntry)
        assert entries[0].name == "root"
        assert entries[0].entries_index == 1
        assert entries[0].entries_count == 3

    def test_resource_entry(self):
        """Entry with bit 31 set in 2nd uint32 is a resource."""
        # Construct a resource entry:
        # bytes 0-1: name_offset (uint16) = 0
        # bytes 2-4: file_size (3 bytes LE) = 100
        # bytes 5-7: file_offset (3 bytes LE) with bit 23 set = 0x800001 (offset=1)
        # bytes 8-11: system_flags
        # bytes 12-15: graphics_flags
        name_off = 0
        file_size = 100
        file_offset_raw = 0x800001  # bit 23 set + offset 1
        first_bytes = struct.pack("<H", name_off) + \
            file_size.to_bytes(3, "little") + \
            file_offset_raw.to_bytes(3, "little")
        sys_flags = 0x10000100  # some valid flags
        gfx_flags = 0x10000100
        entry_data = first_bytes + struct.pack("<2I", sys_flags, gfx_flags)

        names_data = b"test.ytd\x00"
        entries = parse_entries(entry_data, names_data, 1)
        assert len(entries) == 1
        assert isinstance(entries[0], RPF7ResourceEntry)
        assert entries[0].name == "test.ytd"
        assert entries[0].file_size == 100
        assert entries[0].file_offset == 1  # masked: 0x800001 & 0x7FFFFF = 1

    def test_binary_entry(self):
        """Entry with bit 31 clear and not 0x7FFFFF00 is a binary file."""
        # Pack as uint64: name_offset(16) | file_size(24) | file_offset(24)
        name_off = 0
        file_size = 200
        file_offset = 5
        val = name_off | (file_size << 16) | (file_offset << 40)
        first_8 = struct.pack("<Q", val)
        uncompressed_size = 400
        encryption_type = 0
        entry_data = first_8 + struct.pack("<2I", uncompressed_size, encryption_type)

        names_data = b"nested.rpf\x00"
        entries = parse_entries(entry_data, names_data, 1)
        assert len(entries) == 1
        assert isinstance(entries[0], RPF7BinaryEntry)
        assert entries[0].name == "nested.rpf"
        assert entries[0].file_size == 200
        assert entries[0].file_offset == 5
        assert entries[0].uncompressed_size == 400
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest rpf_extract/tests/test_rpf7_parser.py -v`
Expected: FAIL

**Step 3: Implement RPF7 header and entry parsing**

```python
# rpf_extract/src/rpf7_parser.py
"""RPF7 Archive Parser for GTA V.

Parses RPF7 archive headers, entry tables, and name tables to build a
directory tree of archive contents. Supports OPEN, AES, and NG encryption.

RPF7 Layout:
    [Header: 16 bytes]
    [Entry Table: entry_count × 16 bytes]  ← may be encrypted
    [Name Table: names_length bytes]        ← may be encrypted
    [File Data: aligned to 512-byte blocks]
"""

from __future__ import annotations

import logging
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

RPF7_MAGIC = 0x52504637  # "RPF7" as little-endian uint32
RPF7_HEADER_SIZE = 16
BLOCK_SIZE = 512  # File offsets are in 512-byte blocks

# Encryption type constants
ENC_OPEN = 0x4E45504F   # "OPEN" — unencrypted
ENC_AES = 0x0FFFFFF9     # AES-256-ECB
ENC_NG = 0x0FEFFFFF      # NG custom cipher


@dataclass
class RPF7Header:
    magic: int
    entry_count: int
    names_length: int
    encryption: int


@dataclass
class RPF7DirEntry:
    """Directory entry in the RPF7 archive."""
    name: str
    name_offset: int
    entries_index: int
    entries_count: int


@dataclass
class RPF7BinaryEntry:
    """Binary (non-resource) file entry — e.g. nested .rpf archives, .meta files."""
    name: str
    name_offset: int
    file_size: int          # on-disk (compressed) size in bytes
    file_offset: int        # in 512-byte blocks
    uncompressed_size: int
    encryption_type: int    # 0 = not encrypted, 1 = encrypted


@dataclass
class RPF7ResourceEntry:
    """Resource file entry — .ytd, .ydd, .yft, etc."""
    name: str
    name_offset: int
    file_size: int          # compressed size in bytes
    file_offset: int        # in 512-byte blocks (bit 23 masked out)
    system_flags: int
    graphics_flags: int


RPF7Entry = RPF7DirEntry | RPF7BinaryEntry | RPF7ResourceEntry


def parse_rpf7_header(data: bytes) -> RPF7Header:
    """Parse the 16-byte RPF7 header.

    Args:
        data: At least 16 bytes from the start of the RPF file.

    Returns:
        RPF7Header with parsed fields.

    Raises:
        ValueError: If data is too short or magic doesn't match.
    """
    if len(data) < RPF7_HEADER_SIZE:
        raise ValueError(f"Data too small for RPF7 header ({len(data)} bytes, need {RPF7_HEADER_SIZE})")
    magic, entry_count, names_length, encryption = struct.unpack_from("<4I", data, 0)
    if magic != RPF7_MAGIC:
        raise ValueError(f"Invalid RPF7 magic: 0x{magic:08X} (expected 0x{RPF7_MAGIC:08X})")
    return RPF7Header(magic=magic, entry_count=entry_count,
                      names_length=names_length, encryption=encryption)


def _read_name(names_data: bytes, offset: int) -> str:
    """Read a null-terminated string from the name table."""
    end = names_data.index(b"\x00", offset)
    return names_data[offset:end].decode("ascii", errors="replace")


def parse_entries(entry_data: bytes, names_data: bytes,
                  entry_count: int) -> list[RPF7Entry]:
    """Parse the entry table into typed entry objects.

    Args:
        entry_data: Raw (decrypted) entry table bytes.
        names_data: Raw (decrypted) name table bytes.
        entry_count: Number of entries.

    Returns:
        List of RPF7DirEntry, RPF7BinaryEntry, or RPF7ResourceEntry.
    """
    entries: list[RPF7Entry] = []

    for i in range(entry_count):
        off = i * 16
        chunk = entry_data[off:off + 16]

        # Read first two uint32s to classify entry type
        y, x = struct.unpack_from("<2I", chunk, 0)

        if x == 0x7FFFFF00:
            # Directory entry
            name_offset = y
            entries_index, entries_count = struct.unpack_from("<2I", chunk, 8)
            name = _read_name(names_data, name_offset)
            entries.append(RPF7DirEntry(
                name=name, name_offset=name_offset,
                entries_index=entries_index, entries_count=entries_count,
            ))
        elif (x & 0x80000000) == 0:
            # Binary file entry
            val = struct.unpack_from("<Q", chunk, 0)[0]
            name_offset = val & 0xFFFF
            file_size = (val >> 16) & 0xFFFFFF
            file_offset = (val >> 40) & 0xFFFFFF
            uncompressed_size, encryption_type = struct.unpack_from("<2I", chunk, 8)
            name = _read_name(names_data, name_offset)
            entries.append(RPF7BinaryEntry(
                name=name, name_offset=name_offset,
                file_size=file_size, file_offset=file_offset,
                uncompressed_size=uncompressed_size,
                encryption_type=encryption_type,
            ))
        else:
            # Resource file entry
            name_offset = struct.unpack_from("<H", chunk, 0)[0]
            file_size = chunk[2] | (chunk[3] << 8) | (chunk[4] << 16)
            raw_offset = chunk[5] | (chunk[6] << 8) | (chunk[7] << 16)
            file_offset = raw_offset & 0x7FFFFF
            system_flags, graphics_flags = struct.unpack_from("<2I", chunk, 8)
            name = _read_name(names_data, name_offset)
            entries.append(RPF7ResourceEntry(
                name=name, name_offset=name_offset,
                file_size=file_size, file_offset=file_offset,
                system_flags=system_flags, graphics_flags=graphics_flags,
            ))

    return entries
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest rpf_extract/tests/test_rpf7_parser.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rpf_extract/src/rpf7_parser.py rpf_extract/tests/test_rpf7_parser.py
git commit -m "feat(rpf): implement RPF7 header and entry table parsing"
```

---

## Task 5: RPF7 Parser — Archive Opening with Decryption and Tree Building

**Files:**
- Modify: `rpf_extract/src/rpf7_parser.py`
- Modify: `rpf_extract/tests/test_rpf7_parser.py`

**Step 1: Write failing tests for full archive opening**

Add to `rpf_extract/tests/test_rpf7_parser.py`:

```python
from rpf_extract.src.rpf7_parser import RPF7Archive, open_rpf7


def _build_open_rpf(entries_data: bytes, names_data: bytes) -> bytes:
    """Build a minimal OPEN-encrypted RPF7 archive."""
    entry_count = len(entries_data) // 16
    names_length = len(names_data)
    header = struct.pack("<4I", 0x52504637, entry_count, names_length, 0x4E45504F)
    return header + entries_data + names_data


class TestOpenRPF7:
    def test_open_single_dir(self, tmp_path):
        """Archive with just a root directory."""
        # Root dir: name_offset=0, 0x7FFFFF00, entries_index=0, entries_count=0
        entries = struct.pack("<4I", 0, 0x7FFFFF00, 0, 0)
        names = b"\x00"  # empty root name
        rpf_bytes = _build_open_rpf(entries, names)
        rpf_file = tmp_path / "test.rpf"
        rpf_file.write_bytes(rpf_bytes)

        archive = open_rpf7(rpf_file, ng_keys=None)
        assert archive.header.entry_count == 1
        assert len(archive.entries) == 1
        assert isinstance(archive.entries[0], RPF7DirEntry)

    def test_open_with_resource_entry(self, tmp_path):
        """Archive with root dir + one resource file."""
        # Root dir: children start at index 1, count 1
        dir_entry = struct.pack("<4I", 0, 0x7FFFFF00, 1, 1)
        # Resource entry: name_offset=5, file_size=64, file_offset=1 | 0x800000
        name_off = 5
        file_size = 64
        file_offset_raw = 0x800001
        res_bytes = struct.pack("<H", name_off) + \
            file_size.to_bytes(3, "little") + \
            file_offset_raw.to_bytes(3, "little") + \
            struct.pack("<2I", 0x10000100, 0x10000100)
        entries = dir_entry + res_bytes
        names = b"root\x00test.ytd\x00"
        rpf_bytes = _build_open_rpf(entries, names)
        rpf_file = tmp_path / "test.rpf"
        rpf_file.write_bytes(rpf_bytes)

        archive = open_rpf7(rpf_file, ng_keys=None)
        assert len(archive.entries) == 2
        assert archive.entries[1].name == "test.ytd"


class TestBuildTree:
    def test_tree_structure(self, tmp_path):
        """Verify the directory tree maps parent dirs to children."""
        # Root dir (idx 0): children at 1..2
        dir0 = struct.pack("<4I", 0, 0x7FFFFF00, 1, 2)
        # Subdir (idx 1): no children
        dir1 = struct.pack("<4I", 5, 0x7FFFFF00, 0, 0)
        # Resource file (idx 2)
        name_off = 12
        res_bytes = struct.pack("<H", name_off) + \
            (64).to_bytes(3, "little") + \
            (0x800001).to_bytes(3, "little") + \
            struct.pack("<2I", 0x10000100, 0x10000100)
        entries = dir0 + dir1 + res_bytes
        names = b"root\x00models\x00foo.ytd\x00"
        rpf_bytes = _build_open_rpf(entries, names)
        rpf_file = tmp_path / "test.rpf"
        rpf_file.write_bytes(rpf_bytes)

        archive = open_rpf7(rpf_file, ng_keys=None)
        tree = archive.build_tree()
        # Root (idx 0) should have children [1, 2]
        assert 0 in tree
        assert len(tree[0]) == 2
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest rpf_extract/tests/test_rpf7_parser.py -v`
Expected: FAIL

**Step 3: Implement RPF7Archive with open_rpf7 and build_tree**

Add to `rpf_extract/src/rpf7_parser.py`:

```python
@dataclass
class RPF7Archive:
    """Opened RPF7 archive with parsed entries."""
    path: Path
    header: RPF7Header
    entries: list[RPF7Entry]
    raw_data: bytes  # Full archive bytes for extracting file data

    def build_tree(self) -> dict[int, list[int]]:
        """Build a parent→children index mapping.

        Returns:
            Dict mapping directory entry index to list of child entry indices.
        """
        tree: dict[int, list[int]] = {}
        for i, entry in enumerate(self.entries):
            if isinstance(entry, RPF7DirEntry):
                children = list(range(entry.entries_index,
                                      entry.entries_index + entry.entries_count))
                tree[i] = children
        return tree

    def extract_binary(self, entry: RPF7BinaryEntry) -> bytes:
        """Extract a binary file entry's data (decompresses if needed).

        Args:
            entry: A binary file entry from this archive.

        Returns:
            Decompressed file data bytes.
        """
        offset = entry.file_offset * BLOCK_SIZE
        data = self.raw_data[offset:offset + entry.file_size]

        # Decompress if compressed
        if entry.file_size != entry.uncompressed_size and entry.file_size > 0:
            data = zlib.decompress(data, -15)

        return data

    def extract_resource_raw(self, entry: RPF7ResourceEntry) -> bytes:
        """Extract raw resource file data (the RSC7 container, still compressed).

        Returns the bytes starting at the file offset, including the RSC7 header.
        This can be saved as a .ytd file and parsed by the existing rsc7.py module.

        Args:
            entry: A resource file entry from this archive.

        Returns:
            Raw bytes of the resource file (RSC7 header + compressed data).
        """
        offset = entry.file_offset * BLOCK_SIZE

        # Determine actual size
        if entry.file_size == 0xFFFFFF:
            # Size is in the RSC7 header at the offset — read it
            # RSC7 header: magic(4) + version(4) + sys_flags(4) + gfx_flags(4)
            # We need to calculate from flags, but for extraction we just
            # read until we have enough data. Use a generous upper bound.
            logger.warning("Resource %s has 0xFFFFFF size marker — reading from RSC7 header",
                          entry.name)
            # Read the RSC7 header to compute size from flags
            rsc7_header = self.raw_data[offset:offset + 16]
            _, _, sys_flags, gfx_flags = struct.unpack_from("<4I", rsc7_header, 0)
            from rpf_extract.src.rpf7_parser import _get_size_from_flags
            total_decompressed = _get_size_from_flags(sys_flags) + _get_size_from_flags(gfx_flags)
            # Compressed size is unknown; take remaining data up to next block boundary
            # This is a rare edge case — in practice we estimate
            data = self.raw_data[offset:offset + total_decompressed]
        else:
            data = self.raw_data[offset:offset + entry.file_size]

        return data


def _get_size_from_flags(flags: int) -> int:
    """Calculate decompressed segment size from RSC7 flags. Same as rsc7.py."""
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


def open_rpf7(rpf_path: str | Path, ng_keys=None) -> RPF7Archive:
    """Open and parse an RPF7 archive file.

    Args:
        rpf_path: Path to the .rpf file.
        ng_keys: Optional NGKeys instance for NG-encrypted archives.
                 Required if the archive uses NG encryption.

    Returns:
        RPF7Archive with parsed header, entries, and raw data.

    Raises:
        ValueError: If the file is not a valid RPF7 archive.
        FileNotFoundError: If the file does not exist.
    """
    path = Path(rpf_path)
    raw = path.read_bytes()

    header = parse_rpf7_header(raw)

    # Read entry table and name table
    entry_start = RPF7_HEADER_SIZE
    entry_end = entry_start + header.entry_count * 16
    names_end = entry_end + header.names_length

    entry_data = bytearray(raw[entry_start:entry_end])
    names_data = bytearray(raw[entry_end:names_end])

    # Decrypt if needed
    if header.encryption == ENC_NG:
        if ng_keys is None:
            raise ValueError("NG-encrypted RPF requires ng_keys to be provided")
        from rpf_extract.src.ng_crypto import decrypt_ng_data
        rpf_name = path.name
        rpf_size = len(raw)
        entry_data = bytearray(decrypt_ng_data(bytes(entry_data), rpf_name, rpf_size, ng_keys))
        names_data = bytearray(decrypt_ng_data(bytes(names_data), rpf_name, rpf_size, ng_keys))
    elif header.encryption == ENC_AES:
        if ng_keys is None:
            raise ValueError("AES-encrypted RPF requires ng_keys (for AES key)")
        from rpf_extract.src.ng_crypto import decrypt_aes_data
        entry_data = bytearray(decrypt_aes_data(bytes(entry_data), ng_keys.aes_key))
        names_data = bytearray(decrypt_aes_data(bytes(names_data), ng_keys.aes_key))
    # ENC_OPEN and 0x00000000 = no decryption needed

    entries = parse_entries(bytes(entry_data), bytes(names_data), header.entry_count)

    return RPF7Archive(
        path=path,
        header=header,
        entries=entries,
        raw_data=raw,
    )


def open_rpf7_from_bytes(data: bytes, name: str, ng_keys=None) -> RPF7Archive:
    """Open an RPF7 archive from in-memory bytes (for nested RPFs).

    Args:
        data: Raw bytes of the RPF7 archive.
        name: The archive filename (for key derivation).
        ng_keys: Optional NGKeys instance.

    Returns:
        RPF7Archive with parsed contents.
    """
    header = parse_rpf7_header(data)

    entry_start = RPF7_HEADER_SIZE
    entry_end = entry_start + header.entry_count * 16
    names_end = entry_end + header.names_length

    entry_data = bytearray(data[entry_start:entry_end])
    names_data = bytearray(data[entry_end:names_end])

    if header.encryption == ENC_NG:
        if ng_keys is None:
            raise ValueError("NG-encrypted nested RPF requires ng_keys")
        from rpf_extract.src.ng_crypto import decrypt_ng_data
        entry_data = bytearray(decrypt_ng_data(bytes(entry_data), name, len(data), ng_keys))
        names_data = bytearray(decrypt_ng_data(bytes(names_data), name, len(data), ng_keys))
    elif header.encryption == ENC_AES:
        if ng_keys is None:
            raise ValueError("AES-encrypted nested RPF requires ng_keys")
        from rpf_extract.src.ng_crypto import decrypt_aes_data
        entry_data = bytearray(decrypt_aes_data(bytes(entry_data), ng_keys.aes_key))
        names_data = bytearray(decrypt_aes_data(bytes(names_data), ng_keys.aes_key))

    entries = parse_entries(bytes(entry_data), bytes(names_data), header.entry_count)

    return RPF7Archive(
        path=Path(name),
        header=header,
        entries=entries,
        raw_data=data,
    )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest rpf_extract/tests/test_rpf7_parser.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rpf_extract/src/rpf7_parser.py rpf_extract/tests/test_rpf7_parser.py
git commit -m "feat(rpf): add RPF7Archive with decryption, tree building, and extraction"
```

---

## Task 6: Clothing Finder — DLC Discovery and Traversal

**Files:**
- Create: `rpf_extract/src/clothing_finder.py`
- Create: `rpf_extract/tests/test_clothing_finder.py`

This is the core logic that traverses the GTA V directory structure, finds DLC RPFs, descends into nested RPFs, and locates freemode clothing directories.

**Step 1: Write failing tests**

```python
# rpf_extract/tests/test_clothing_finder.py
"""Tests for clothing finder / DLC discovery."""
import pytest
from rpf_extract.src.clothing_finder import (
    find_dlc_rpf_paths,
    derive_collection_name,
    is_freemode_clothing_dir,
    reconstruct_ytd_filename,
)


class TestFindDLCPaths:
    def test_finds_dlcpacks_dir(self, tmp_path):
        """Should locate the update/x64/dlcpacks directory."""
        dlcpacks = tmp_path / "update" / "x64" / "dlcpacks"
        dlcpacks.mkdir(parents=True)
        # Create a fake DLC
        heist = dlcpacks / "mpheist"
        heist.mkdir()
        (heist / "dlc.rpf").write_bytes(b"\x00" * 16)

        paths = find_dlc_rpf_paths(tmp_path)
        assert len(paths) >= 1
        assert any("mpheist" in str(p) for p in paths)

    def test_finds_dlc1_rpf(self, tmp_path):
        """Should also find dlc1.rpf (some DLCs have both)."""
        dlcpacks = tmp_path / "update" / "x64" / "dlcpacks" / "mpsecurity"
        dlcpacks.mkdir(parents=True)
        (dlcpacks / "dlc.rpf").write_bytes(b"\x00" * 16)
        (dlcpacks / "dlc1.rpf").write_bytes(b"\x00" * 16)

        paths = find_dlc_rpf_paths(tmp_path)
        rpf_names = [p.name for p in paths]
        assert "dlc.rpf" in rpf_names
        assert "dlc1.rpf" in rpf_names

    def test_empty_dir(self, tmp_path):
        """No dlcpacks dir → empty list."""
        paths = find_dlc_rpf_paths(tmp_path)
        assert paths == []


class TestDeriveCollectionName:
    def test_from_dlc_pack_name(self):
        """Collection name = DLC pack folder name."""
        assert derive_collection_name("mpheist") == "mpheist"

    def test_strips_mp_prefix(self):
        """mpheist stays as mpheist (we keep the mp prefix)."""
        assert derive_collection_name("mpheist") == "mpheist"


class TestIsFreemodeClothingDir:
    def test_female_freemode(self):
        assert is_freemode_clothing_dir("mp_f_freemode_01_mp_f_heist") is True

    def test_male_freemode(self):
        assert is_freemode_clothing_dir("mp_m_freemode_01_mp_m_heist") is True

    def test_non_freemode(self):
        assert is_freemode_clothing_dir("props_p_heist") is False

    def test_streamed_ped_model(self):
        """Ped model files, not clothing dirs."""
        assert is_freemode_clothing_dir("mp_f_freemode_01") is False


class TestReconstructFilename:
    def test_standard_ytd(self):
        """Prepend ped dir name to get full filename."""
        result = reconstruct_ytd_filename(
            "accs_diff_000_a_uni.ytd",
            "mp_f_freemode_01_mp_f_heist"
        )
        assert result == "mp_f_freemode_01_mp_f_heist^accs_diff_000_a_uni.ytd"

    def test_preserves_category(self):
        result = reconstruct_ytd_filename(
            "jbib_diff_003_b_uni.ytd",
            "mp_m_freemode_01_mp_m_gunrunning_01"
        )
        assert result == "mp_m_freemode_01_mp_m_gunrunning_01^jbib_diff_003_b_uni.ytd"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest rpf_extract/tests/test_clothing_finder.py -v`
Expected: FAIL

**Step 3: Implement the clothing finder module**

```python
# rpf_extract/src/clothing_finder.py
"""Clothing finder — discovers and extracts freemode ped clothing from GTA V.

Traverses the GTA V directory structure:
  1. Finds all DLC RPF files under update/x64/dlcpacks/
  2. Also checks x64v.rpf for base game clothing
  3. Opens each RPF, descends into nested RPFs (clothing is 2-3 levels deep)
  4. Locates directories matching mp_f_freemode_01_* and mp_m_freemode_01_*
  5. Extracts .ytd files with reconstructed full filenames

Output structure:
  output_dir/{collection_name}/[female]/{full_filename}.ytd
  output_dir/{collection_name}/[male]/{full_filename}.ytd
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Pattern for freemode clothing directories inside RPFs
_FREEMODE_DIR_PATTERN = re.compile(
    r"^mp_[fm]_freemode_01_.+$"
)

# Pattern for clothing .ytd files
_CLOTHING_YTD_PATTERN = re.compile(
    r"^[a-z_]+_diff_\d+_[a-z]_[a-z]+\.ytd$"
)


def find_dlc_rpf_paths(gta_root: str | Path) -> list[Path]:
    """Find all DLC RPF files in a GTA V installation.

    Looks for dlc.rpf and dlc1.rpf files inside each DLC pack directory
    under update/x64/dlcpacks/. Also includes x64v.rpf from the game root.

    Args:
        gta_root: Path to the GTA V installation directory.

    Returns:
        List of Path objects to .rpf files, sorted by name.
    """
    root = Path(gta_root)
    rpf_paths: list[Path] = []

    # Base game RPF
    x64v = root / "x64v.rpf"
    if x64v.is_file():
        rpf_paths.append(x64v)

    # DLC packs
    dlcpacks = root / "update" / "x64" / "dlcpacks"
    if not dlcpacks.is_dir():
        return rpf_paths

    for dlc_dir in sorted(dlcpacks.iterdir()):
        if not dlc_dir.is_dir():
            continue
        for rpf_name in ("dlc.rpf", "dlc1.rpf", "dlc2.rpf"):
            rpf_path = dlc_dir / rpf_name
            if rpf_path.is_file():
                rpf_paths.append(rpf_path)

    return rpf_paths


def derive_collection_name(dlc_pack_name: str) -> str:
    """Derive the collection name from the DLC pack folder name.

    Args:
        dlc_pack_name: The folder name under dlcpacks/ (e.g. "mpheist").

    Returns:
        The collection name (same as folder name).
    """
    return dlc_pack_name


def is_freemode_clothing_dir(name: str) -> bool:
    """Check if a directory name represents a freemode clothing directory.

    Must match mp_f_freemode_01_* or mp_m_freemode_01_* and have content
    after the ped prefix (i.e. not just "mp_f_freemode_01" itself).

    Args:
        name: Directory entry name from the RPF.

    Returns:
        True if this is a freemode clothing directory.
    """
    return bool(_FREEMODE_DIR_PATTERN.match(name))


def gender_from_dir_name(name: str) -> str:
    """Derive gender from a freemode directory name.

    Args:
        name: e.g. "mp_f_freemode_01_mp_f_heist"

    Returns:
        "female" or "male"
    """
    if name.startswith("mp_f_"):
        return "female"
    if name.startswith("mp_m_"):
        return "male"
    return "unknown"


def reconstruct_ytd_filename(short_name: str, ped_dir_name: str) -> str:
    """Reconstruct the full .ytd filename from its short name and parent dir.

    Inside RPFs, files are stored with short names like "accs_diff_000_a_uni.ytd".
    The existing clothing_tool expects the full pattern:
      mp_f_freemode_01_mp_f_heist^accs_diff_000_a_uni.ytd

    Args:
        short_name: The filename from the RPF (e.g. "accs_diff_000_a_uni.ytd").
        ped_dir_name: The parent directory name (e.g. "mp_f_freemode_01_mp_f_heist").

    Returns:
        Full reconstructed filename with ^ separator.
    """
    return f"{ped_dir_name}^{short_name}"


def is_clothing_ytd(name: str) -> bool:
    """Check if a filename looks like a clothing diffuse texture.

    Args:
        name: Filename to check.

    Returns:
        True if this matches the clothing YTD pattern.
    """
    return bool(_CLOTHING_YTD_PATTERN.match(name))
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest rpf_extract/tests/test_clothing_finder.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rpf_extract/src/clothing_finder.py rpf_extract/tests/test_clothing_finder.py
git commit -m "feat(rpf): add clothing finder with DLC discovery and filename reconstruction"
```

---

## Task 7: RPF Recursive Traversal — Extract Clothing from Nested RPFs

**Files:**
- Modify: `rpf_extract/src/clothing_finder.py`
- Modify: `rpf_extract/tests/test_clothing_finder.py`

This adds the core recursive function that opens an RPF, looks for nested RPFs containing clothing, and extracts `.ytd` files.

**Step 1: Write failing test for the extraction logic**

Add to `rpf_extract/tests/test_clothing_finder.py`:

```python
from unittest.mock import MagicMock, patch
from rpf_extract.src.clothing_finder import extract_clothing_from_rpf, ClothingFile


class TestExtractClothing:
    def test_returns_clothing_file_list(self):
        """Mock test: verify the function returns ClothingFile objects."""
        # This is more of an integration test placeholder —
        # we test the real thing with actual RPFs in Task 9
        cf = ClothingFile(
            collection="mpheist",
            gender="female",
            original_name="accs_diff_000_a_uni.ytd",
            full_name="mp_f_freemode_01_mp_f_heist^accs_diff_000_a_uni.ytd",
            data=b"fake_ytd_data",
        )
        assert cf.collection == "mpheist"
        assert cf.gender == "female"
        assert cf.full_name.startswith("mp_f_freemode_01")
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest rpf_extract/tests/test_clothing_finder.py::TestExtractClothing -v`
Expected: FAIL

**Step 3: Implement the recursive extraction**

Add to `rpf_extract/src/clothing_finder.py`:

```python
from dataclasses import dataclass


@dataclass
class ClothingFile:
    """An extracted clothing .ytd file."""
    collection: str    # DLC/collection name (e.g. "mpheist")
    gender: str        # "female" or "male"
    original_name: str # Short name from RPF (e.g. "accs_diff_000_a_uni.ytd")
    full_name: str     # Reconstructed full filename with ^ separator
    data: bytes        # Raw file data (RSC7 container)


def extract_clothing_from_rpf(
    archive,  # RPF7Archive
    collection_name: str,
    ng_keys=None,
) -> list[ClothingFile]:
    """Recursively extract freemode clothing .ytd files from an RPF archive.

    Descends into nested RPFs, looking for directories matching
    mp_f_freemode_01_* or mp_m_freemode_01_*, then extracts all
    clothing .ytd files from those directories.

    Args:
        archive: An opened RPF7Archive.
        collection_name: The DLC/collection name for these files.
        ng_keys: Optional NGKeys for decrypting nested RPFs.

    Returns:
        List of ClothingFile objects with extracted data.
    """
    from rpf_extract.src.rpf7_parser import (
        RPF7DirEntry, RPF7BinaryEntry, RPF7ResourceEntry,
        open_rpf7_from_bytes,
    )

    results: list[ClothingFile] = []
    tree = archive.build_tree()

    def _walk(dir_idx: int, is_clothing_parent: bool, ped_dir_name: str):
        """Recursively walk the directory tree."""
        entry = archive.entries[dir_idx]
        if not isinstance(entry, RPF7DirEntry):
            return

        child_indices = tree.get(dir_idx, [])
        for ci in child_indices:
            child = archive.entries[ci]

            if isinstance(child, RPF7DirEntry):
                if is_freemode_clothing_dir(child.name):
                    # Found a clothing directory — extract its contents
                    _walk(ci, True, child.name)
                else:
                    # Keep looking deeper
                    _walk(ci, is_clothing_parent, ped_dir_name)

            elif isinstance(child, RPF7ResourceEntry) and is_clothing_parent:
                # Inside a clothing dir — extract .ytd files
                if is_clothing_ytd(child.name):
                    try:
                        raw = archive.extract_resource_raw(child)
                        full_name = reconstruct_ytd_filename(child.name, ped_dir_name)
                        gender = gender_from_dir_name(ped_dir_name)
                        results.append(ClothingFile(
                            collection=collection_name,
                            gender=gender,
                            original_name=child.name,
                            full_name=full_name,
                            data=raw,
                        ))
                    except Exception as exc:
                        logger.warning("Failed to extract %s: %s", child.name, exc)

            elif isinstance(child, RPF7BinaryEntry) and child.name.endswith(".rpf"):
                # Nested RPF — open it and recurse
                try:
                    nested_data = archive.extract_binary(child)
                    nested_archive = open_rpf7_from_bytes(
                        nested_data, child.name, ng_keys
                    )
                    nested_results = extract_clothing_from_rpf(
                        nested_archive, collection_name, ng_keys
                    )
                    results.extend(nested_results)
                except Exception as exc:
                    logger.warning("Failed to open nested RPF %s: %s", child.name, exc)

    # Start from root (entry 0)
    if archive.entries:
        _walk(0, False, "")

    return results
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest rpf_extract/tests/test_clothing_finder.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add rpf_extract/src/clothing_finder.py rpf_extract/tests/test_clothing_finder.py
git commit -m "feat(rpf): add recursive clothing extraction from nested RPFs"
```

---

## Task 8: CLI Script — rpf_extractor.py

**Files:**
- Create: `rpf_extract/rpf_extractor.py`

This is the standalone entry point that ties everything together.

**Step 1: Implement the CLI script**

```python
#!/usr/bin/env python3
"""RPF7 GTA V Base Clothing Extractor

Extracts freemode ped clothing textures from GTA V's RPF archives and
organizes them by DLC/collection into a folder structure compatible with
the clothing_tool extraction pipeline.

Usage:
    python rpf_extractor.py --gta-dir "C:/Program Files/Grand Theft Auto V" \
                            --keys-dir "C:/CodeWalker/Keys" \
                            --output ./gta_clothing

Output structure:
    output/
      mpheist/
        [female]/
          mp_f_freemode_01_mp_f_heist^accs_diff_000_a_uni.ytd
          ...
        [male]/
          mp_m_freemode_01_mp_m_heist^accs_diff_000_a_uni.ytd
          ...
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Add parent directory to path so we can import from src/
sys.path.insert(0, str(Path(__file__).parent.parent))

from rpf_extract.src.ng_crypto import load_ng_keys
from rpf_extract.src.rpf7_parser import open_rpf7
from rpf_extract.src.clothing_finder import (
    find_dlc_rpf_paths,
    derive_collection_name,
    extract_clothing_from_rpf,
)

logger = logging.getLogger("rpf_extractor")


def main():
    parser = argparse.ArgumentParser(
        description="Extract freemode clothing from GTA V RPF archives."
    )
    parser.add_argument(
        "--gta-dir", required=True,
        help="Path to your GTA V installation directory"
    )
    parser.add_argument(
        "--keys-dir", required=True,
        help="Path to CodeWalker's Keys/ directory containing .dat files"
    )
    parser.add_argument(
        "--output", default="./gta_clothing",
        help="Output directory for extracted .ytd files (default: ./gta_clothing)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List what would be extracted without writing files"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    gta_dir = Path(args.gta_dir)
    keys_dir = Path(args.keys_dir)
    output_dir = Path(args.output)

    if not gta_dir.is_dir():
        logger.error("GTA V directory not found: %s", gta_dir)
        sys.exit(1)

    # Load NG keys
    logger.info("Loading NG decryption keys from %s ...", keys_dir)
    try:
        ng_keys = load_ng_keys(keys_dir)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Failed to load keys: %s", exc)
        sys.exit(1)
    logger.info("Keys loaded successfully.")

    # Find all DLC RPF files
    logger.info("Scanning GTA V directory: %s", gta_dir)
    rpf_paths = find_dlc_rpf_paths(gta_dir)
    logger.info("Found %d RPF files to process.", len(rpf_paths))

    if not rpf_paths:
        logger.warning("No RPF files found. Is --gta-dir pointing to the right directory?")
        sys.exit(1)

    # Process each RPF
    total_files = 0
    total_collections = set()
    start = time.time()

    for rpf_path in rpf_paths:
        # Derive collection name from the DLC pack folder
        # e.g. update/x64/dlcpacks/mpheist/dlc.rpf → "mpheist"
        if "dlcpacks" in rpf_path.parts:
            idx = rpf_path.parts.index("dlcpacks")
            collection = derive_collection_name(rpf_path.parts[idx + 1])
        else:
            # Base game RPF (x64v.rpf)
            collection = "basegame"

        logger.info("Processing: %s (collection: %s)", rpf_path.name, collection)

        try:
            archive = open_rpf7(rpf_path, ng_keys=ng_keys)
        except Exception as exc:
            logger.warning("  Failed to open %s: %s", rpf_path.name, exc)
            continue

        clothing_files = extract_clothing_from_rpf(archive, collection, ng_keys)

        if not clothing_files:
            logger.debug("  No clothing found in %s", rpf_path.name)
            continue

        logger.info("  Found %d clothing files", len(clothing_files))

        for cf in clothing_files:
            gender_dir = f"[{cf.gender}]"
            out_path = output_dir / cf.collection / gender_dir / cf.full_name

            if args.dry_run:
                print(f"  {cf.collection}/{gender_dir}/{cf.full_name} ({len(cf.data)} bytes)")
            else:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(cf.data)

            total_files += 1
            total_collections.add(cf.collection)

    elapsed = time.time() - start
    action = "Would extract" if args.dry_run else "Extracted"
    logger.info(
        "%s %d clothing files across %d collections in %.1fs",
        action, total_files, len(total_collections), elapsed,
    )

    if not args.dry_run and total_files > 0:
        logger.info("Output directory: %s", output_dir.resolve())


if __name__ == "__main__":
    main()
```

**Step 2: Test manually with --dry-run**

Run: `python rpf_extract/rpf_extractor.py --gta-dir "C:/path/to/GTAV" --keys-dir "C:/path/to/CodeWalker/Keys" --output ./gta_clothing --dry-run -v`

This should list all clothing files that would be extracted without writing anything.

**Step 3: Commit**

```bash
git add rpf_extract/rpf_extractor.py
git commit -m "feat(rpf): add rpf_extractor.py CLI for GTA V clothing extraction"
```

---

## Task 9: Integration Testing — Real RPF File

**Files:**
- Modify: `rpf_extract/tests/test_rpf7_parser.py`

This task is for **manual testing** with a real GTA V RPF file to validate the full pipeline. It is not automated because it requires access to the game files.

**Step 1: Create a small integration test script**

Create `rpf_extract/test_integration.py`:

```python
#!/usr/bin/env python3
"""Quick integration test — open one DLC RPF and list clothing entries.

Usage:
    python rpf_extract/test_integration.py \
        "C:/path/to/GTAV/update/x64/dlcpacks/mpheist/dlc.rpf" \
        "C:/path/to/CodeWalker/Keys"
"""
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rpf_extract.src.ng_crypto import load_ng_keys
from rpf_extract.src.rpf7_parser import open_rpf7, RPF7DirEntry, RPF7BinaryEntry, RPF7ResourceEntry
from rpf_extract.src.clothing_finder import extract_clothing_from_rpf

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")


def main():
    rpf_path = sys.argv[1]
    keys_dir = sys.argv[2]

    keys = load_ng_keys(keys_dir)
    print(f"Keys loaded. Opening {rpf_path}...")

    archive = open_rpf7(rpf_path, ng_keys=keys)
    print(f"RPF opened: {archive.header.entry_count} entries")

    # List all entries
    for i, entry in enumerate(archive.entries):
        if isinstance(entry, RPF7DirEntry):
            print(f"  [{i}] DIR:  {entry.name}  (children: {entry.entries_index}..{entry.entries_index + entry.entries_count - 1})")
        elif isinstance(entry, RPF7BinaryEntry):
            print(f"  [{i}] BIN:  {entry.name}  (size: {entry.file_size}, uncompressed: {entry.uncompressed_size})")
        elif isinstance(entry, RPF7ResourceEntry):
            print(f"  [{i}] RES:  {entry.name}  (size: {entry.file_size}, offset: {entry.file_offset})")

    # Try extracting clothing
    print("\nExtracting clothing...")
    clothing = extract_clothing_from_rpf(archive, "test_dlc", keys)
    print(f"Found {len(clothing)} clothing files:")
    for cf in clothing:
        print(f"  {cf.gender:8s} {cf.full_name} ({len(cf.data)} bytes)")


if __name__ == "__main__":
    main()
```

**Step 2: Run against a real DLC RPF**

Run: `python rpf_extract/test_integration.py "C:\path\to\GTAV\update\x64\dlcpacks\mpheist\dlc.rpf" "C:\path\to\CodeWalker\Keys"`

**Step 3: Debug and fix any issues found**

Common issues to watch for:
- NG key selection producing wrong results (check `rpf_name` is just the filename, not full path)
- Entry table corruption after decryption (means decryption key is wrong)
- Nested RPF offsets being wrong (check `BLOCK_SIZE` multiplication)
- Resource entries with `file_size == 0xFFFFFF` edge case

**Step 4: Commit fixes**

```bash
git add rpf_extract/test_integration.py
git commit -m "test(rpf): add integration test script for real RPF validation"
```

---

## Task 10: Performance — Handle Large Archives Efficiently

**Files:**
- Modify: `rpf_extract/src/rpf7_parser.py`
- Modify: `rpf_extract/rpf_extractor.py`

The base game + all DLCs have ~60GB of RPFs. Loading each fully into memory is wasteful — most RPFs don't contain clothing. This task adds file-handle-based reading instead of `read_bytes()` for large files.

**Step 1: Add memory-mapped or seekable file access**

Modify `open_rpf7` in `rpf7_parser.py` to use `mmap` for large files:

```python
import mmap

def open_rpf7(rpf_path: str | Path, ng_keys=None) -> RPF7Archive:
    path = Path(rpf_path)
    file_size = path.stat().st_size

    # For files > 100MB, use mmap to avoid loading everything into RAM
    if file_size > 100 * 1024 * 1024:
        with open(path, "rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            raw = mm  # mmap supports slicing like bytes
            # ... same parsing logic but using mm[start:end] ...
            # We need to keep the mmap alive, so store it
    else:
        raw = path.read_bytes()

    # ... rest of parsing
```

The key change: store the mmap object in RPF7Archive instead of `raw_data: bytes` so large files aren't fully buffered.

**Step 2: Add progress reporting to the CLI**

Add a simple progress counter to `rpf_extractor.py`:

```python
for idx, rpf_path in enumerate(rpf_paths, 1):
    logger.info("[%d/%d] Processing: %s", idx, len(rpf_paths), rpf_path.name)
```

**Step 3: Run full extraction and measure performance**

Run: `python rpf_extract/rpf_extractor.py --gta-dir "C:/path/to/GTAV" --keys-dir "C:/path/to/CodeWalker/Keys" --output ./gta_clothing -v`

**Step 4: Commit**

```bash
git add rpf_extract/src/rpf7_parser.py rpf_extract/rpf_extractor.py
git commit -m "perf(rpf): use mmap for large RPFs, add progress reporting"
```

---

## Task 11: Meta File Generation for Clothing Tool Compatibility

**Files:**
- Modify: `rpf_extract/rpf_extractor.py`
- Modify: `rpf_extract/src/clothing_finder.py`

The existing clothing_tool pipeline reads `.meta` XML files to build the DLC map. We need to either:
1. Generate fake `.meta` files for each collection so the existing pipeline works as-is, OR
2. Just rely on the filename pattern (the existing `filename_parser.py` can extract the DLC name from the full reconstructed filename)

Option 2 is simpler. The reconstructed filename `mp_f_freemode_01_mp_f_heist^accs_diff_000_a_uni.ytd` already contains all the information the existing pipeline needs:
- model: `mp_f_freemode_01`
- dlcname: `mp_f_heist` (extracted by regex)
- category: `accs`
- drawable: `000`
- variant: `a`

The collection folders we create (`mpheist/[female]/`, `mpheist/[male]/`) provide the gender context and organizational grouping.

**Step 1: Generate a minimal .meta file per collection for cleaner integration**

Add to `rpf_extract/src/clothing_finder.py`:

```python
def generate_meta_file(collection: str, gender: str, ped_dir_names: list[str]) -> str:
    """Generate a minimal ShopPedApparel .meta XML for a collection.

    This enables the existing clothing_tool pipeline to discover the DLC name
    without modification.

    Args:
        collection: The DLC/collection name (e.g. "mpheist").
        gender: "female" or "male".
        ped_dir_names: List of freemode ped directory names found in this collection.

    Returns:
        XML string for the .meta file.
    """
    prefix = "mp_f" if gender == "female" else "mp_m"
    ped_name = f"{prefix}_freemode_01"

    # Use the first ped_dir_name to derive the DLC name
    # e.g. "mp_f_freemode_01_mp_f_heist" → dlcName = "mp_f_heist"
    dlc_name = ""
    for name in ped_dir_names:
        if name.startswith(f"{ped_name}_"):
            dlc_name = name[len(f"{ped_name}_"):]
            break

    if not dlc_name:
        dlc_name = collection

    full_dlc = f"{ped_name}_{dlc_name}"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ShopPedApparel>
  <pedName>{ped_name}</pedName>
  <dlcName>{dlc_name}</dlcName>
  <fullDlcName>{full_dlc}</fullDlcName>
</ShopPedApparel>
"""
```

**Step 2: Write meta files in the CLI**

Add to `rpf_extractor.py` after the extraction loop:

```python
# Generate .meta files for each collection/gender
for collection in total_collections:
    for gender in ("female", "male"):
        gender_dir = f"[{gender}]"
        coll_dir = output_dir / collection / gender_dir
        if not coll_dir.is_dir():
            continue

        # Gather ped dir names from extracted files
        ped_dirs = set()
        for f in coll_dir.iterdir():
            if f.name.endswith(".ytd") and "^" in f.name:
                ped_dirs.add(f.name.split("^")[0])

        if ped_dirs:
            prefix = "mp_f" if gender == "female" else "mp_m"
            meta_content = generate_meta_file(collection, gender, sorted(ped_dirs))
            first_ped = sorted(ped_dirs)[0]
            meta_name = f"{first_ped}.meta"
            meta_path = coll_dir / meta_name
            if not args.dry_run:
                meta_path.write_text(meta_content, encoding="utf-8")
                logger.info("  Generated %s", meta_path)
```

**Step 3: Test that existing clothing_tool can parse the output**

Run: `python cli.py --input gta_clothing --output output_gta --dry-run`

Verify the existing pipeline discovers and correctly parses the extracted files.

**Step 4: Commit**

```bash
git add rpf_extract/
git commit -m "feat(rpf): generate .meta files for clothing_tool pipeline compatibility"
```

---

## Task 12: Documentation and Final Cleanup

**Files:**
- Create: `rpf_extract/README.md` (only because this is a separate sub-tool that needs usage docs)

**Step 1: Write README**

```markdown
# RPF7 GTA V Clothing Extractor

Extracts base GTA V freemode clothing textures from RPF archives, organized
by DLC collection, ready for the clothing_tool pipeline.

## Prerequisites

1. GTA V installed on your PC
2. CodeWalker installed (for NG decryption keys)
   - Run CodeWalker once pointing at your GTA V directory
   - This generates the `Keys/` folder with decryption tables
3. Python 3.10+

## Usage

```bash
python rpf_extract/rpf_extractor.py \
    --gta-dir "C:\Program Files\Rockstar Games\Grand Theft Auto V" \
    --keys-dir "C:\path\to\CodeWalker\Keys" \
    --output ./gta_clothing
```

### Options

| Flag | Description |
|------|-------------|
| `--gta-dir` | Path to GTA V installation (required) |
| `--keys-dir` | Path to CodeWalker Keys/ directory (required) |
| `--output` | Output directory (default: `./gta_clothing`) |
| `--dry-run` | List files without extracting |
| `-v` | Verbose debug logging |

## Output Structure

```
gta_clothing/
  mpheist/
    [female]/
      mp_f_freemode_01_mp_f_heist^accs_diff_000_a_uni.ytd
      mp_f_freemode_01_mp_f_heist.meta
    [male]/
      mp_m_freemode_01_mp_m_heist^accs_diff_000_a_uni.ytd
      mp_m_freemode_01_mp_m_heist.meta
  mpluxe/
    ...
```

## Then Process with clothing_tool

```bash
python cli.py --input gta_clothing --output output_gta
```
```

**Step 2: Run full test suite**

Run: `python -m pytest rpf_extract/tests/ -v`
Expected: ALL PASS

**Step 3: Final commit**

```bash
git add rpf_extract/
git commit -m "docs(rpf): add README for RPF clothing extractor"
```

---

## Summary

| Task | Component | Estimated Complexity |
|------|-----------|---------------------|
| 1 | Project scaffolding | Trivial |
| 2 | NG crypto — key loading | Small |
| 3 | NG crypto — hash + block cipher | Medium |
| 4 | RPF7 parser — header + entries | Medium |
| 5 | RPF7 parser — archive open + tree | Medium |
| 6 | Clothing finder — DLC discovery | Small |
| 7 | Recursive RPF traversal + extraction | Large |
| 8 | CLI script | Medium |
| 9 | Integration testing with real RPFs | Large (debugging) |
| 10 | Performance (mmap for large files) | Small |
| 11 | Meta file generation for compatibility | Small |
| 12 | Documentation + cleanup | Trivial |

**Total: 12 tasks, ~8 files to create, 0 modifications to existing clothing_tool code.**
