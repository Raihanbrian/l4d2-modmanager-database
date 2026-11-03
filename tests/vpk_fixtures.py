"""Tiny synthetic VPK writer used ONLY by tests; no extraction/runtime writer."""

from dataclasses import dataclass
import struct
import zlib


@dataclass(frozen=True)
class FixtureEntry:
    extension: str = "txt"
    directory: str = "scripts"
    basename: str = "fixture"
    preload: bytes = b""
    body: bytes = b"synthetic asset"
    archive: int = 0x7FFF
    offset: int | None = None
    terminator: int = 0xFFFF


def build_vpk(paths: tuple[str, ...] = ("scripts/fixture.txt",), *, version=1, entries=None) -> bytes:
    if entries is None:
        entries = []
        for path in paths:
            directory, slash, filename = path.rpartition("/")
            basename, dot, extension = filename.rpartition(".")
            entries.append(FixtureEntry(extension if dot else " ", directory if slash else " ", basename if dot else filename))
    groups = {}
    for entry in entries:
        groups.setdefault(entry.extension, {}).setdefault(entry.directory, []).append(entry)
    tree, data = bytearray(), bytearray()
    def string(value):
        tree.extend(value.encode("utf-8") + b"\0")
    for extension, directories in groups.items():
        string(extension)
        for directory, files in directories.items():
            string(directory)
            for entry in files:
                string(entry.basename)
                offset = len(data) if entry.offset is None else entry.offset
                tree.extend(struct.pack("<IHHIIH", zlib.crc32(entry.preload + entry.body), len(entry.preload), entry.archive, offset, len(entry.body), entry.terminator))
                tree.extend(entry.preload)
                if entry.archive == 0x7FFF:
                    data.extend(entry.body)
            tree.append(0)
        tree.append(0)
    tree.append(0)
    header = struct.pack("<III", 0x55AA1234, version, len(tree))
    if version == 2:
        header += struct.pack("<IIII", len(data), 0, 48, 0)
    return header + tree + data + (b"\0" * 48 if version == 2 else b"")
