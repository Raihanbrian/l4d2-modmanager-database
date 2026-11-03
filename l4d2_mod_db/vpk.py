"""Bounded VPK v1/v2 directory indexing. Pure stream parser; no filesystem I/O.

Reads only the header and declared tree, including uninterpreted preload bytes.
Never extracts assets, follows archive references, or verifies payload checksums.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import PureWindowsPath
import struct
from typing import BinaryIO


MAGIC = 0x55AA1234
EMBEDDED_ARCHIVE = 0x7FFF


@dataclass(frozen=True, slots=True)
class ParserLimits:
    max_tree_bytes: int = 16 * 1024 * 1024
    max_entries: int = 200_000
    max_path_bytes: int = 4096

    def __post_init__(self):
        if min(self.max_tree_bytes, self.max_entries, self.max_path_bytes) <= 0:
            raise ValueError("Parser limits must be positive.")


class VpkError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AssetEntry:
    original_path: str
    canonical_path: str
    original_path_bytes: bytes
    canonical_path_bytes: bytes
    crc32: int
    preload_bytes: int
    archive_index: int
    archive_offset: int
    archive_length: int

    @property
    def size_bytes(self) -> int:
        return self.preload_bytes + self.archive_length


@dataclass(frozen=True, slots=True)
class VpkIndex:
    version: int
    tree_size: int
    index_sha256: str
    assets: tuple[AssetEntry, ...]
    external_archives: tuple[int, ...]
    bytes_read: int
    non_utf8_paths: int = 0


def canonicalize_virtual_path(original: str, *, max_bytes: int = 4096) -> str:
    try:
        raw = original.encode("utf-8", errors="surrogateescape")
    except UnicodeEncodeError:
        raise VpkError("UNSAFE_ASSET_PATH", "Invalid archive virtual path representation.") from None
    path = original.replace("\\", "/")
    parts = path.split("/")
    if (
        not path or path.startswith("/") or PureWindowsPath(path).drive
        or len(raw) > max_bytes
        or any(part in {"", ".", ".."} or part.endswith((".", " ")) for part in parts)
        or any(ord(char) < 32 or char in ':*?"<>|' for char in path)
    ):
        raise VpkError("UNSAFE_ASSET_PATH", "Unsafe or oversized archive virtual path; package index rejected.")
    return path.casefold()


def _read_exact(stream: BinaryIO, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        block = stream.read(count - len(chunks))
        if not block:
            raise VpkError("TRUNCATED_VPK", "VPK header or directory tree is truncated.")
        chunks.extend(block)
    return bytes(chunks)


class _TreeReader:
    def __init__(self, data: bytes, limits: ParserLimits):
        self.data, self.limits, self.offset = data, limits, 0

    def string(self) -> str:
        end = self.data.find(b"\0", self.offset, self.offset + self.limits.max_path_bytes + 1)
        if end < 0:
            raise VpkError("INVALID_TREE_STRING", "Unterminated or oversized VPK directory string.")
        raw = self.data[self.offset:end]
        self.offset = end + 1
        # Preserve unknown source encodings byte-for-byte, without guessing a
        # codepage or merging names through replacement characters. Callers get
        # explicit non-UTF-8 counts plus original/canonical byte keys per asset.
        return raw.decode("utf-8", errors="surrogateescape")

    def entry(self) -> tuple[int, int, int, int, int, int]:
        if self.offset + 18 > len(self.data):
            raise VpkError("TRUNCATED_ENTRY", "VPK directory entry is truncated.")
        fields = struct.unpack_from("<IHHIIH", self.data, self.offset)
        self.offset += 18
        return fields

    def skip_preload(self, count: int) -> None:
        if self.offset + count > len(self.data):
            raise VpkError("TRUNCATED_PRELOAD", "VPK preload bytes exceed the declared tree.")
        self.offset += count


def parse_vpk(stream: BinaryIO, file_size: int, limits: ParserLimits = ParserLimits()) -> VpkIndex:
    """Parse a fresh stream positioned at byte zero, within explicit budgets."""
    if file_size < 12:
        raise VpkError("TRUNCATED_VPK", "VPK is too short for its header.")
    header = _read_exact(stream, 12)
    magic, version, tree_size = struct.unpack("<III", header)
    if magic != MAGIC:
        raise VpkError("INVALID_MAGIC", "Not a VPK directory archive (or a data-only segment).")
    if version not in {1, 2}:
        raise VpkError("UNSUPPORTED_VERSION", "Only VPK directory versions 1 and 2 are supported.")
    if not 1 <= tree_size <= limits.max_tree_bytes:
        raise VpkError("TREE_LIMIT", "VPK tree size is empty or exceeds the configured resource limit.")
    header_size = 12 if version == 1 else 28
    if header_size + tree_size > file_size:
        raise VpkError("TRUNCATED_VPK", "Declared VPK header/tree exceeds the file size.")
    embedded_size = file_size - header_size - tree_size
    if version == 2:
        extra = _read_exact(stream, 16)
        header += extra
        embedded_size, archive_md5, other_md5, signature_size = struct.unpack("<IIII", extra)
        if header_size + tree_size + embedded_size + archive_md5 + other_md5 + signature_size > file_size:
            raise VpkError("INVALID_SECTIONS", "Declared VPK v2 sections exceed the file size.")
    tree = _read_exact(stream, tree_size)
    reader = _TreeReader(tree, limits)
    assets: list[AssetEntry] = []
    seen: set[str] = set()
    external: set[int] = set()
    while extension := reader.string():
        if extension != " " and ("/" in extension or "\\" in extension or extension in {".", ".."}):
            raise VpkError("UNSAFE_ASSET_PATH", "Invalid extension field in archive tree.")
        while directory := reader.string():
            while basename := reader.string():
                if "/" in basename or "\\" in basename or basename in {".", ".."}:
                    raise VpkError("UNSAFE_ASSET_PATH", "Invalid basename field in archive tree.")
                original = ("" if directory == " " else directory + "/") + basename + ("" if extension == " " else "." + extension)
                canonical = canonicalize_virtual_path(original, max_bytes=limits.max_path_bytes)
                if len(assets) >= limits.max_entries:
                    raise VpkError("ENTRY_LIMIT", "VPK entry count exceeds the configured resource limit.")
                if canonical in seen:
                    raise VpkError("DUPLICATE_ASSET", "Duplicate canonical asset path inside one package; index is ambiguous.")
                seen.add(canonical)
                crc, preload, archive, offset, length, terminator = reader.entry()
                if terminator != 0xFFFF:
                    raise VpkError("INVALID_TERMINATOR", "Invalid VPK entry terminator.")
                if archive > EMBEDDED_ARCHIVE:
                    raise VpkError("INVALID_ARCHIVE", "Unsupported VPK archive index.")
                if archive == EMBEDDED_ARCHIVE and length and offset + length > embedded_size:
                    raise VpkError("INVALID_OFFSET", "Embedded asset range exceeds the declared file-data section.")
                if archive != EMBEDDED_ARCHIVE and length:
                    external.add(archive)
                reader.skip_preload(preload)
                assets.append(AssetEntry(
                    original, canonical,
                    original.encode("utf-8", errors="surrogateescape"),
                    canonical.encode("utf-8", errors="surrogateescape"),
                    crc, preload, archive, offset, length,
                ))
    if reader.offset != tree_size:
        raise VpkError("TRAILING_TREE_DATA", "Unexpected bytes after the final directory terminator.")
    assets.sort(key=lambda asset: (asset.canonical_path, asset.original_path))
    non_utf8 = sum(any(0xDC80 <= ord(char) <= 0xDCFF for char in asset.original_path) for asset in assets)
    return VpkIndex(version, tree_size, hashlib.sha256(header + tree).hexdigest(), tuple(assets), tuple(sorted(external)), header_size + tree_size, non_utf8)
