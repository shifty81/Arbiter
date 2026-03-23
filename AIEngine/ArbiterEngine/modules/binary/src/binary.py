"""Binary module — binary file analysis: info, hex dump, string extraction, patching."""
from __future__ import annotations
import binascii
import os
import re
import struct
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

# Common ELF/PE/Mach-O magic bytes → format name
_MAGIC_MAP: list[tuple[bytes, str]] = [
    (b"\x7fELF", "ELF"),
    (b"MZ", "PE (Windows Executable)"),
    (b"\xce\xfa\xed\xfe", "Mach-O 32-bit (little-endian)"),
    (b"\xcf\xfa\xed\xfe", "Mach-O 64-bit (little-endian)"),
    (b"\xfe\xed\xfa\xce", "Mach-O 32-bit (big-endian)"),
    (b"\xfe\xed\xfa\xcf", "Mach-O 64-bit (big-endian)"),
    (b"PK\x03\x04", "ZIP archive"),
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
    (b"\xfd7zXZ", "XZ"),
    (b"\x89PNG\r\n\x1a\n", "PNG image"),
    (b"\xff\xd8\xff", "JPEG image"),
    (b"GIF8", "GIF image"),
    (b"RIFF", "RIFF (WAV/AVI)"),
]


def _detect_format(data: bytes) -> str:
    for magic, name in _MAGIC_MAP:
        if data[: len(magic)] == magic:
            return name
    # Try UTF-8/ASCII text
    try:
        data[:512].decode("utf-8")
        return "UTF-8 text"
    except UnicodeDecodeError:
        pass
    return "unknown binary"


def binary_info(path: str, **kwargs) -> dict:
    """Return basic information about a binary file: size, format, and entropy."""
    p = Path(path)
    if not p.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    data = p.read_bytes()
    size = len(data)

    fmt = _detect_format(data)

    # Shannon entropy
    import math
    if size > 0:
        freq = [0] * 256
        for b in data:
            freq[b] += 1
        entropy = -sum((c / size) * math.log2(c / size) for c in freq if c > 0)
    else:
        entropy = 0.0

    info: dict = {
        "path": str(p.resolve()),
        "size_bytes": size,
        "format": fmt,
        "entropy": round(entropy, 4),
    }

    # ELF-specific header fields
    if fmt == "ELF" and size >= 16:
        ei_class = data[4]
        ei_data = data[5]
        info["elf"] = {
            "class": "64-bit" if ei_class == 2 else "32-bit",
            "endianness": "little" if ei_data == 1 else "big",
        }
        if ei_class == 2 and size >= 64:
            (e_type, e_machine) = struct.unpack_from("<HH", data, 16)
            info["elf"]["type"] = e_type
            info["elf"]["machine"] = e_machine

    return {"status": "ok", **info}


def binary_disasm(path: str, offset: int = 0, length: int = 64, **kwargs) -> dict:
    """Return a hexadecimal/byte listing of *length* bytes starting at *offset*.

    This is a lightweight hex+ASCII view (not a full disassembler) that works
    without any external tools.  Use ``binary_hex`` for a pure hex dump.
    """
    p = Path(path)
    if not p.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    data = p.read_bytes()
    if offset >= len(data):
        return {"status": "error", "error": f"Offset {offset} beyond file size {len(data)}"}

    chunk = data[offset: offset + length]
    lines: list[str] = []
    for i in range(0, len(chunk), 16):
        row = chunk[i: i + 16]
        hex_part = " ".join(f"{b:02x}" for b in row)
        ascii_part = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in row)
        lines.append(f"{offset + i:08x}  {hex_part:<47}  |{ascii_part}|")

    return {
        "status": "ok",
        "path": str(p),
        "offset": offset,
        "length": len(chunk),
        "listing": "\n".join(lines),
    }


def binary_strings(path: str, min_length: int = 4, **kwargs) -> dict:
    """Extract printable ASCII strings from a binary file.

    Returns strings of at least *min_length* consecutive printable characters.
    """
    p = Path(path)
    if not p.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    data = p.read_bytes()
    # Regex to find sequences of printable ASCII
    pattern = rb"[\x20-\x7e]{" + str(min_length).encode() + rb",}"
    strings = [m.group().decode("ascii") for m in re.finditer(pattern, data)]
    return {
        "status": "ok",
        "path": str(p),
        "min_length": min_length,
        "count": len(strings),
        "strings": strings,
    }


def binary_patch(path: str, offset: int, data: str, **kwargs) -> dict:
    """Patch bytes in a binary file at *offset*.

    *data* is a hex string (e.g. ``"deadbeef"``).  The file is modified in-place.
    A backup is written to ``<path>.bak`` before patching.
    """
    p = Path(path)
    if not p.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    try:
        patch_bytes = bytes.fromhex(data.replace(" ", ""))
    except ValueError as exc:
        return {"status": "error", "error": f"Invalid hex data: {exc}"}

    content = bytearray(p.read_bytes())
    if offset + len(patch_bytes) > len(content):
        return {"status": "error", "error": f"Patch extends beyond file size ({len(content)} bytes)"}

    # Backup
    bak = p.with_suffix(p.suffix + ".bak")
    bak.write_bytes(bytes(content))

    content[offset: offset + len(patch_bytes)] = patch_bytes
    p.write_bytes(bytes(content))

    return {
        "status": "ok",
        "path": str(p),
        "offset": offset,
        "patched_bytes": len(patch_bytes),
        "backup": str(bak),
    }


def binary_hex(path: str, offset: int = 0, length: int = 256, **kwargs) -> dict:
    """Return a formatted hex dump of *length* bytes from *path* starting at *offset*."""
    p = Path(path)
    if not p.exists():
        return {"status": "error", "error": f"File not found: {path}"}

    data = p.read_bytes()
    if offset >= len(data):
        return {"status": "error", "error": f"Offset {offset} beyond file size {len(data)}"}

    chunk = data[offset: offset + length]
    lines: list[str] = []
    for i in range(0, len(chunk), 16):
        row = chunk[i: i + 16]
        hex_cols = " ".join(f"{b:02x}" for b in row)
        ascii_cols = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in row)
        lines.append(f"{offset + i:08x}  {hex_cols:<47}  {ascii_cols}")

    return {
        "status": "ok",
        "path": str(p),
        "offset": offset,
        "length": len(chunk),
        "hex_dump": "\n".join(lines),
    }
