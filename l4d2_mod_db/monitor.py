"""M2 in-memory indexing/reconciliation with a direct-folder polling watcher.

No database, persisted catalog, game writes or OS-wide watcher. Missing folders
and incomplete scans never imply mass removal. All content reads use security.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from enum import Enum
import math
import time

from .scanner import WorkshopPackage, discover
from .security import Diagnostic, DiscoveryStatus, PathPolicyError, ScopedWorkshopAccess
from .vpk import ParserLimits, VpkError, VpkIndex, parse_vpk


class PackageStatus(str, Enum):
    PENDING = "pending"
    INDEXED = "indexed"
    ERROR = "error"
    UNAVAILABLE = "unavailable"
    MISSING_PENDING = "missing_pending"


@dataclass(frozen=True, slots=True)
class IndexedPackage:
    package: WorkshopPackage
    status: PackageStatus
    index: VpkIndex | None = None
    indexed_signature: tuple[int, ...] | None = None
    diagnostic: Diagnostic | None = None

    @property
    def stale(self) -> bool:
        return self.index is not None and self.status != PackageStatus.INDEXED


@dataclass(frozen=True, slots=True)
class IndexEvent:
    kind: str
    relative_path: str
    message: str


@dataclass(frozen=True, slots=True)
class MonitorReport:
    discovery_status: DiscoveryStatus
    records: tuple[IndexedPackage, ...]
    diagnostics: tuple[Diagnostic, ...]
    events: tuple[IndexEvent, ...]
    parse_attempts: int
    observed_paths: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.discovery_status in {DiscoveryStatus.COMPLETE, DiscoveryStatus.MISSING} and all(
            record.status == PackageStatus.INDEXED for record in self.records
        )


def _signature(package: WorkshopPackage) -> tuple[int, ...]:
    file = package.file
    return file.signature or (file.size_bytes, file.modified_ns)


def index_package(access: ScopedWorkshopAccess, package: WorkshopPackage, limits: ParserLimits) -> VpkIndex:
    with access.open_vpk(package.file) as stream:
        return parse_vpk(stream, package.file.size_bytes, limits)


class WorkshopMonitor:
    """One explicitly scoped collection, reconstructed at startup, cached in RAM.

    A file must have the same metadata across at least two polls spanning the
    settle interval. Failed or absent observations reset stability. Failed parses
    preserve earlier indexes and retry with backoff. Removal also requires two
    complete scans spanning the settle interval; a missing folder is an outage.
    """

    def __init__(
        self, access: ScopedWorkshopAccess, *, settle_seconds: float = 2.0,
        retry_seconds: float = 5.0, limits: ParserLimits = ParserLimits(),
        max_total_assets: int = 1_000_000, clock: Callable[[], float] = time.monotonic,
        initial_records: tuple[IndexedPackage, ...] = (),
    ):
        if not all(math.isfinite(value) and value > 0 for value in (settle_seconds, retry_seconds)):
            raise ValueError("Settle and retry intervals must be positive finite seconds.")
        if max_total_assets <= 0:
            raise ValueError("The collection asset limit must be positive.")
        self.access, self.settle_seconds, self.retry_seconds = access, settle_seconds, retry_seconds
        self.limits, self.max_total_assets, self.clock = limits, max_total_assets, clock
        self._records: dict[str, IndexedPackage] = {
            record.package.file.relative_path.casefold(): record for record in initial_records
        }
        self._observed: dict[str, tuple[tuple[int, ...], float]] = {}
        self._missing: dict[str, float] = {}
        self._retry: dict[str, tuple[tuple[int, ...], float]] = {}
        self._previous_status: DiscoveryStatus | None = None
        self.parse_attempts = 0

    def poll(self) -> MonitorReport:
        now = self.clock()
        snapshot = discover(self.access)
        records = dict(self._records)
        events: list[IndexEvent] = []
        if snapshot.status != self._previous_status:
            events.append(IndexEvent("discovery", "left4dead2/addons/workshop", snapshot.status.value))
        self._previous_status = snapshot.status
        present = {package.file.relative_path.casefold(): package for package in snapshot.packages}
        accessible = snapshot.status in {DiscoveryStatus.COMPLETE, DiscoveryStatus.PARTIAL}
        if not accessible:
            self._observed.clear()
            self._missing.clear()
            for key, record in records.items():
                records[key] = replace(record, status=PackageStatus.UNAVAILABLE)
        else:
            for key, package in present.items():
                self._missing.pop(key, None)
                previous = records.get(key)
                signature = _signature(package)
                observed = self._observed.get(key)
                if observed is None or observed[0] != signature:
                    self._observed[key] = (signature, now)
                    self._retry.pop(key, None)
                    records[key] = IndexedPackage(
                        package, PackageStatus.PENDING,
                        previous.index if previous else None,
                        previous.indexed_signature if previous else None,
                    )
                    continue
                if now - observed[1] < self.settle_seconds:
                    records[key] = replace(previous, package=package, status=PackageStatus.PENDING)
                    continue
                if previous is not None and previous.indexed_signature == signature:
                    records[key] = replace(previous, package=package, status=PackageStatus.INDEXED, diagnostic=None)
                    continue
                retry = self._retry.get(key)
                if retry is not None and retry[0] == signature and now < retry[1]:
                    records[key] = replace(previous, package=package)
                    continue
                self.parse_attempts += 1
                try:
                    index = index_package(self.access, package, self.limits)
                    retained_count = sum(len(record.index.assets) for other, record in records.items() if other != key and record.index)
                    if retained_count + len(index.assets) > self.max_total_assets:
                        raise VpkError("COLLECTION_LIMIT", "Collection asset budget exceeded; previous valid indexes retained.")
                    records[key] = IndexedPackage(package, PackageStatus.INDEXED, index, signature)
                    self._retry.pop(key, None)
                except (VpkError, PathPolicyError, OSError) as error:
                    diagnostic = Diagnostic(
                        getattr(error, "code", "VPK_UNAVAILABLE"),
                        str(error) if isinstance(error, (VpkError, PathPolicyError)) else "VPK could not be read; retry scheduled.",
                        package.file.relative_path,
                    )
                    records[key] = IndexedPackage(
                        package, PackageStatus.ERROR,
                        previous.index if previous else None,
                        previous.indexed_signature if previous else None,
                        diagnostic,
                    )
                    self._retry[key] = (signature, now + self.retry_seconds)

            for key in sorted(set(records) - set(present)):
                self._observed.pop(key, None)
                self._retry.pop(key, None)
                if snapshot.status != DiscoveryStatus.COMPLETE:
                    self._missing.pop(key, None)
                    records[key] = replace(records[key], status=PackageStatus.UNAVAILABLE)
                    continue
                since = self._missing.setdefault(key, now)
                if now - since >= self.settle_seconds:
                    removed = records.pop(key)
                    self._missing.pop(key, None)
                    events.append(IndexEvent("removed", removed.package.file.relative_path, "Confirmed absent in complete scans; removed from the in-memory collection."))
                else:
                    records[key] = replace(records[key], status=PackageStatus.MISSING_PENDING)

        for key, record in records.items():
            previous = self._records.get(key)
            if record != previous:
                kind = record.status.value
                if record.status == PackageStatus.INDEXED and previous and previous.index is not None:
                    kind = "updated" if record.indexed_signature != previous.indexed_signature or record.package != previous.package else "recovered"
                detail = f"[{record.diagnostic.code}] {record.diagnostic.message}" if record.diagnostic else record.status.value
                events.append(IndexEvent(kind, record.package.file.relative_path, detail))
        # Publish one complete new immutable snapshot after reconciliation.
        self._records = records
        ordered = tuple(records[key] for key in sorted(records))
        return MonitorReport(snapshot.status, ordered, snapshot.diagnostics, tuple(events), self.parse_attempts, tuple(present))


def watch(
    monitor: WorkshopMonitor, *, interval: float = 1.0, cycles: int | None = None,
    sleep: Callable[[float], None] | None = None,
) -> Iterator[MonitorReport]:
    """Poll only the scoped directory until Ctrl+C or an optional cycle bound."""
    if not math.isfinite(interval) or interval <= 0 or (cycles is not None and cycles <= 0):
        raise ValueError("Watch interval and optional cycle count must be positive.")
    count = 0
    while cycles is None or count < cycles:
        yield monitor.poll()
        count += 1
        if cycles is None or count < cycles:
            (sleep or time.sleep)(interval)
