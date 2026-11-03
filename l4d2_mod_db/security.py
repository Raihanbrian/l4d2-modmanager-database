"""The only runtime module allowed to access the selected game filesystem.

M1 remains metadata-only. M2 adds guarded, read-only VPK handles. All directory
enumeration remains confined to direct Workshop children. This is no OS sandbox.
M6.1 adds bounded reads of directly paired JPG previews through the same guards.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path, PureWindowsPath
import stat
from typing import BinaryIO


WORKSHOP_RELATIVE = "left4dead2/addons/workshop"
_EXTENSIONS = frozenset({".vpk", ".jpg"})
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"{prefix}{number}" for prefix in ("com", "lpt") for number in "123456789¹²³"}
)


class DiscoveryStatus(str, Enum):
    COMPLETE = "complete"
    MISSING = "missing"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    relative_path: str | None = None


class PathPolicyError(ValueError):
    """A safe, fixed diagnostic; never propagate OS exception path dumps."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class FileReference:
    filename: str
    relative_path: str
    size_bytes: int
    modified_ns: int
    signature: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkshopSnapshot:
    status: DiscoveryStatus
    files: tuple[FileReference, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


def _extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].casefold() if dot >= 0 else ""


def validate_workshop_filename(filename: str) -> None:
    """Accept only one ordinary Windows filename, never an arbitrary path."""
    windows_path = PureWindowsPath(filename)
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or windows_path.drive
        or windows_path.root
        or any(ord(char) < 32 or char in ':*?"<>|' for char in filename)
        or filename.endswith((" ", "."))
        or filename.split(".", 1)[0].rstrip(" ").casefold() in _RESERVED_NAMES
    ):
        raise PathPolicyError("UNSAFE_FILENAME", "A direct, ordinary filename is required.")
    if _extension(filename) not in _EXTENSIONS:
        raise PathPolicyError("OUT_OF_SCOPE", "Only direct .vpk and .jpg files are permitted.")


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
    )


def _directory_identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _file_signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_mode,
        info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        getattr(info, "st_file_attributes", 0),
    )


def _checked_directory(path: Path) -> os.stat_result:
    info = path.lstat()
    if _is_reparse(info):
        raise PathPolicyError("REPARSE_POINT", "Symlinks, junctions and reparse points are refused.")
    if not stat.S_ISDIR(info.st_mode):
        raise PathPolicyError("NOT_DIRECTORY", "An expected directory is not a regular directory.")
    return info


def _open_readonly(path: Path) -> int:
    """Open existing files only. Verify Windows handle attributes/final path.

    Share read/write/delete so this tool does not lock Steam updates. No content
    is read until the caller verifies descriptor identity and directory context.
    """
    if os.name != "nt":
        return os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class HandleInfo(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
            ("accessed", wintypes.FILETIME), ("modified", wintypes.FILETIME),
            ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(HandleInfo)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    # GENERIC_READ, all sharing flags, OPEN_EXISTING, OPEN_REPARSE_POINT.
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x7, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("Read-only VPK open failed.")
    try:
        info = HandleInfo()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise OSError("Cannot inspect the opened VPK handle.")
        if info.attributes & (_REPARSE_ATTRIBUTE | 0x10) or kernel.GetFileType(handle) != 1:
            raise PathPolicyError("UNSAFE_HANDLE", "Opened VPK handle is not a regular disk file.")
        if info.links != 1:
            raise PathPolicyError("HARDLINK", "VPK content reads refuse files with multiple hardlinks.")
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise PathPolicyError("UNSAFE_HANDLE", "Cannot verify the opened VPK's final path.")
        final = buffer.value
        if final.startswith("\\\\?\\UNC\\"):
            raise PathPolicyError("UNSAFE_HANDLE", "Network VPK handles are refused.")
        if final.startswith("\\\\?\\"):
            final = final[4:]
        if Path(final) != path.resolve(strict=True):
            raise PathPolicyError("UNSAFE_HANDLE", "Opened VPK handle does not match its validated path.")
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = None  # Descriptor now owns the handle, including on later failure.
        return fd
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)


class ScopedWorkshopAccess:
    """Validate an explicitly selected root and expose only Workshop references.

    Expected directories and root ancestors receive metadata-only checks. No
    ancestor, game root, addons directory, or other location is enumerated.
    All reparse points are refused, including ones pointing inside the root.
    """

    def __init__(self, game_root: str | os.PathLike[str]) -> None:
        raw_root = os.fspath(game_root)
        if not isinstance(raw_root, str):
            raise PathPolicyError("INVALID_ROOT", "The selected root must be a text path.")
        root = Path(raw_root)
        if (
            not root.is_absolute()
            or raw_root.startswith(("\\\\", "//"))
            or ".." in root.parts
            or ".." in PureWindowsPath(raw_root).parts
            or any(ord(char) < 32 for char in raw_root)
        ):
            raise PathPolicyError(
                "INVALID_ROOT", "Select an absolute local game root without traversal or device paths."
            )

        # lstat every component before resolve, so a pre-existing link is never
        # accepted just because its target happens to look like a valid install.
        checked: list[tuple[Path, tuple[int, int]]] = []
        try:
            for path in (*reversed(root.parents), root):
                checked.append((path, _directory_identity(_checked_directory(path))))
            resolved_root = root.resolve(strict=True)
            for relative in ("left4dead2", "left4dead2/addons"):
                path = root / relative
                info = _checked_directory(path)
                if not path.resolve(strict=True).is_relative_to(resolved_root):
                    raise PathPolicyError("OUTSIDE_ROOT", "Expected directories must stay inside the selected root.")
                checked.append((path, _directory_identity(info)))
        except OSError:
            raise PathPolicyError(
                "INVALID_STRUCTURE",
                "Cannot validate the selected root; accessible left4dead2/addons directories are required.",
            ) from None

        self._root = root
        self._resolved_root = resolved_root
        self._directories = tuple(checked)
        self._workshop = root / WORKSHOP_RELATIVE

    @property
    def validated_root(self) -> Path:
        """Validated namespace for disjoint app storage; grants no file access."""
        self._check_context()
        return self._resolved_root

    def _check_context(self, workshop_identity: tuple[int, int] | None = None) -> None:
        for path, expected_identity in self._directories:
            if _directory_identity(_checked_directory(path)) != expected_identity:
                raise PathPolicyError("DIRECTORY_CHANGED", "A validated directory changed during discovery; retry.")
        if self._root.resolve(strict=True) != self._resolved_root:
            raise PathPolicyError("DIRECTORY_CHANGED", "The selected root changed during discovery; retry.")
        if workshop_identity is not None:
            info = _checked_directory(self._workshop)
            if _directory_identity(info) != workshop_identity:
                raise PathPolicyError("DIRECTORY_CHANGED", "The Workshop directory changed during discovery; retry.")
            if not self._workshop.resolve(strict=True).is_relative_to(self._resolved_root):
                raise PathPolicyError("OUTSIDE_ROOT", "The Workshop directory must stay inside the selected root.")

    def _inspect_file(self, filename: str) -> os.stat_result:
        validate_workshop_filename(filename)
        path = self._workshop / filename
        info = path.lstat()
        if _is_reparse(info):
            raise PathPolicyError("REPARSE_POINT", "Candidate is a symlink or reparse point; skipped.")
        if not stat.S_ISREG(info.st_mode):
            raise PathPolicyError("NOT_REGULAR_FILE", "Candidate is not a regular file; skipped.")
        # Path-component containment, never a vulnerable string-prefix check.
        resolved = path.resolve(strict=True)
        resolved_workshop = self._workshop.resolve(strict=True)
        if not resolved.is_relative_to(resolved_workshop) or resolved.parent != resolved_workshop:
            raise PathPolicyError("OUTSIDE_WORKSHOP", "Candidate resolves outside the direct Workshop folder; skipped.")
        if not resolved_workshop.is_relative_to(self._resolved_root):
            raise PathPolicyError("OUTSIDE_ROOT", "Candidate resolves outside the selected root; skipped.")
        return info

    @contextmanager
    def open_vpk(self, reference: FileReference) -> Iterator[BinaryIO]:
        """Read one observed direct VPK through a verified read-only descriptor.

        No modes, arbitrary paths, JPG readers or extraction destinations are
        accepted. Changes before/during reading invalidate the entire result.
        """
        with self._open_observed(reference, '.vpk') as stream:
            yield stream

    def read_preview(self, package: FileReference, preview: FileReference, *, max_bytes=4*1024*1024) -> bytes:
        """M6.1: one directly paired JPG, bounded, same guarded descriptor checks."""
        if not 1 <= max_bytes <= 4*1024*1024:
            raise PathPolicyError('OUT_OF_SCOPE', 'Preview read limit is out of range.')
        validate_workshop_filename(package.filename)
        if (_extension(package.filename) != '.vpk' or package.relative_path != f'{WORKSHOP_RELATIVE}/{package.filename}'
                or package.filename.rsplit('.',1)[0].casefold() != preview.filename.rsplit('.',1)[0].casefold()):
            raise PathPolicyError('OUT_OF_SCOPE', 'Only the directly associated Workshop JPG may be read.')
        self._check_context()
        before = self._inspect_file(package.filename)
        if (before.st_size,before.st_mtime_ns) != (package.size_bytes,package.modified_ns) or (package.signature and _file_signature(before) != package.signature):
            raise PathPolicyError('FILE_CHANGED','Package changed; refresh previews.')
        if preview.size_bytes > max_bytes:
            raise PathPolicyError('IMAGE_LIMIT','Preview exceeds the image byte limit.')
        with self._open_observed(preview,'.jpg') as stream:
            data = stream.read(max_bytes+1)
            if len(data)>max_bytes: raise PathPolicyError('IMAGE_LIMIT','Preview exceeds the image byte limit.')
        if _file_signature(self._inspect_file(package.filename)) != _file_signature(before):
            raise PathPolicyError('FILE_CHANGED','Package changed during preview reading.')
        return data

    @contextmanager
    def _open_observed(self, reference: FileReference, extension: str) -> Iterator[BinaryIO]:
        validate_workshop_filename(reference.filename)
        if _extension(reference.filename) != extension or reference.relative_path != f"{WORKSHOP_RELATIVE}/{reference.filename}":
            raise PathPolicyError("OUT_OF_SCOPE", "Content access requires an observed direct Workshop VPK reference.")
        self._check_context()
        workshop_identity = _directory_identity(_checked_directory(self._workshop))
        self._check_context(workshop_identity)
        before = self._inspect_file(reference.filename)
        if (before.st_size, before.st_mtime_ns) != (reference.size_bytes, reference.modified_ns) or (
            reference.signature and _file_signature(before) != reference.signature
        ):
            raise PathPolicyError("FILE_CHANGED", "VPK changed since discovery; wait for a fresh stable observation.")
        if before.st_nlink != 1:
            raise PathPolicyError("HARDLINK", "VPK content reads refuse files with multiple hardlinks.")
        fd = _open_readonly(self._workshop / reference.filename)
        try:
            # Own/close the descriptor immediately, including validation failures.
            stream = os.fdopen(fd, "rb", buffering=0)
        except BaseException:
            os.close(fd)
            raise
        with stream:
            opened = os.fstat(stream.fileno())
            self._check_context(workshop_identity)
            current = self._inspect_file(reference.filename)
            if not stat.S_ISREG(opened.st_mode) or _file_signature(current) != _file_signature(before) or (
                opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns
            ) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
                raise PathPolicyError("FILE_CHANGED", "Opened VPK does not match the observed file.")
            if opened.st_nlink != 1:
                raise PathPolicyError("HARDLINK", "VPK content reads refuse files with multiple hardlinks.")
            try:
                yield stream
            finally:
                self._check_context(workshop_identity)
                after = self._inspect_file(reference.filename)
                descriptor = os.fstat(stream.fileno())
                if _file_signature(after) != _file_signature(before) or (
                    descriptor.st_size, descriptor.st_mtime_ns, descriptor.st_nlink
                ) != (before.st_size, before.st_mtime_ns, 1):
                    raise PathPolicyError("FILE_CHANGED", "VPK changed during indexing; result discarded.")

    def list_workshop_files(self) -> WorkshopSnapshot:
        """Enumerate once, recheck identities/metadata, and return a scoped snapshot.

        Disallowed extensions are ignored without stat/open. Partial and failed
        scans are explicit and cannot be mistaken for a complete empty scan.
        These two observations do not establish Steam download stability (M2).
        """
        try:
            self._check_context()
            info = _checked_directory(self._workshop)
            workshop_identity = _directory_identity(info)
            self._check_context(workshop_identity)
        except FileNotFoundError:
            # A missing base directory is a failure, not an absent Workshop.
            try:
                self._check_context()
            except (OSError, PathPolicyError):
                return self._failed_context()
            return WorkshopSnapshot(DiscoveryStatus.MISSING, diagnostics=(Diagnostic(
                "WORKSHOP_MISSING", "Workshop folder not found; no other locations were searched.", WORKSHOP_RELATIVE,
            ),))
        except PathPolicyError as error:
            return WorkshopSnapshot(DiscoveryStatus.REJECTED, diagnostics=(Diagnostic(
                error.code, str(error), WORKSHOP_RELATIVE,
            ),))
        except OSError:
            return self._failed_context()

        names: list[str] = []
        diagnostics: list[Diagnostic] = []
        enumeration_complete = False
        try:
            with os.scandir(self._workshop) as entries:
                for entry in entries:
                    if _extension(entry.name) in _EXTENSIONS:
                        names.append(entry.name)
            enumeration_complete = True
        except OSError:
            diagnostics.append(Diagnostic(
                "ENUMERATION_FAILED", "Workshop enumeration failed or was interrupted; results are incomplete.",
                WORKSHOP_RELATIVE,
            ))

        try:
            self._check_context(workshop_identity)
        except (OSError, PathPolicyError):
            return self._failed_context()

        # Case-insensitive collisions (or repeated entries during a race) are
        # ambiguous. Do not choose a winner using enumeration order.
        counts = Counter(name.casefold() for name in names)
        observed: list[tuple[FileReference, tuple[int, ...]]] = []
        for name in sorted(set(names), key=lambda name: (name.casefold(), name)):
            relative = f"{WORKSHOP_RELATIVE}/{name}"
            if counts[name.casefold()] > 1:
                diagnostics.append(Diagnostic("DUPLICATE_NAME", "Ambiguous or repeated filename; skipped.", relative))
                continue
            try:
                self._check_context(workshop_identity)
                info = self._inspect_file(name)
                observed.append((FileReference(name, relative, info.st_size, info.st_mtime_ns, _file_signature(info)), _file_signature(info)))
            except PathPolicyError as error:
                diagnostics.append(Diagnostic(error.code, str(error), relative))
            except OSError:
                diagnostics.append(Diagnostic("FILE_UNAVAILABLE", "Candidate disappeared or its metadata is unavailable; skipped.", relative))

        files: list[FileReference] = []
        for reference, signature in observed:
            try:
                self._check_context(workshop_identity)
                if _file_signature(self._inspect_file(reference.filename)) != signature:
                    raise PathPolicyError("FILE_CHANGED", "Candidate changed during discovery; skipped until a later run.")
                files.append(reference)
            except PathPolicyError as error:
                diagnostics.append(Diagnostic(error.code, str(error), reference.relative_path))
            except OSError:
                diagnostics.append(Diagnostic("FILE_UNAVAILABLE", "Candidate disappeared or its metadata is unavailable; skipped.", reference.relative_path))

        try:
            self._check_context(workshop_identity)
        except (OSError, PathPolicyError):
            return self._failed_context()

        status = DiscoveryStatus.COMPLETE
        if diagnostics:
            status = DiscoveryStatus.PARTIAL
        if not enumeration_complete and not files:
            status = DiscoveryStatus.UNAVAILABLE
        diagnostics.sort(key=lambda item: (item.relative_path or "", item.code, item.message))
        return WorkshopSnapshot(status, tuple(files), tuple(diagnostics))

    @staticmethod
    def _failed_context() -> WorkshopSnapshot:
        return WorkshopSnapshot(DiscoveryStatus.UNAVAILABLE, diagnostics=(Diagnostic(
            "DIRECTORY_UNAVAILABLE", "A required directory is inaccessible or changed; no complete result is available.",
            WORKSHOP_RELATIVE,
        ),))
