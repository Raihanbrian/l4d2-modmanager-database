"""Interpret allowlisted references; never perform filesystem I/O here."""

from __future__ import annotations

from dataclasses import dataclass

from .security import Diagnostic, DiscoveryStatus, FileReference, ScopedWorkshopAccess


@dataclass(frozen=True, slots=True)
class WorkshopPackage:
    file: FileReference
    workshop_id: str | None
    preview: FileReference | None


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    status: DiscoveryStatus
    packages: tuple[WorkshopPackage, ...]
    previews: tuple[FileReference, ...]
    diagnostics: tuple[Diagnostic, ...]


def infer_workshop_id(filename: str) -> str | None:
    """A numeric basename is a convention-based hint, never a verified Steam ID.

    Preserve its exact ASCII digit spelling, including leading zeroes. Do not
    turn multipart names, signs, Unicode digits or replacement titles into IDs.
    """
    stem, separator, extension = filename.rpartition(".")
    if separator and extension.casefold() == "vpk" and stem and all("0" <= char <= "9" for char in stem):
        return stem
    return None


def discover(access: ScopedWorkshopAccess) -> DiscoveryReport:
    snapshot = access.list_workshop_files()
    previews = tuple(file for file in snapshot.files if file.filename.casefold().endswith(".jpg"))
    by_stem = {file.filename.rsplit(".", 1)[0].casefold(): file for file in previews}
    packages = tuple(
        WorkshopPackage(file, infer_workshop_id(file.filename), by_stem.get(file.filename.rsplit(".", 1)[0].casefold()))
        for file in snapshot.files if file.filename.casefold().endswith(".vpk")
    )
    return DiscoveryReport(snapshot.status, packages, previews, snapshot.diagnostics)
