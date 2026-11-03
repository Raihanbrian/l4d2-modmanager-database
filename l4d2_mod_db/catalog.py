"""M3 durable catalog, with M2 observations staged outside write transactions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import UUID, uuid4

from .monitor import IndexedPackage, MonitorReport, PackageStatus, WorkshopMonitor
from .scanner import WorkshopPackage, infer_workshop_id
from .schema import CANONICALIZATION_VERSION, PARSER_VERSION
from .security import Diagnostic, DiscoveryStatus, FileReference, ScopedWorkshopAccess, WORKSHOP_RELATIVE, validate_workshop_filename
from .storage import CatalogDatabase, CatalogError, root_key
from .vpk import AssetEntry, EMBEDDED_ARCHIVE, ParserLimits, VpkError, VpkIndex, canonicalize_virtual_path


SIGNATURE_FIELDS = ("device_id", "file_id", "mode", "size_bytes", "mtime_ns", "ctime_ns", "attributes")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _timestamp(value: str) -> None:
    try:
        valid = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%dT%H:%M:%S.%fZ") == value
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise CatalogError("Catalog timestamps require fixed UTC ISO 8601 format.")


def _uuid(value: str) -> None:
    try:
        identifier = UUID(value)
        valid = identifier.hex == value and identifier.version == 4
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise CatalogError("Catalog contains an invalid UUID.")


def _relative(value: str, extension: str = ".vpk") -> None:
    prefix = WORKSHOP_RELATIVE + "/"
    if not value.startswith(prefix):
        raise CatalogError("Catalog relative location is outside the allowlist.")
    try:
        validate_workshop_filename(value[len(prefix):])
    except ValueError:
        raise CatalogError("Catalog relative location is unsafe.") from None
    if not value.casefold().endswith(extension):
        raise CatalogError("Catalog relative location has the wrong file type.")


def _signature(row, prefix: str) -> tuple[int, ...]:
    values = tuple(row[prefix + field] for field in SIGNATURE_FIELDS)
    for value in values[:2]:
        if not value.isascii() or not value.isdecimal() or str(int(value)) != value:
            raise CatalogError("Catalog file identity is not canonical decimal text.")
    return tuple(int(value) for value in values)


def _metadata(signature: tuple[int, ...], prefix: str) -> dict:
    if len(signature) != 7:
        raise CatalogError("A complete safely observed file signature is required.")
    return {prefix + key: str(value) if index < 2 else value
            for index, (key, value) in enumerate(zip(SIGNATURE_FIELDS, signature))}


def _utf8(raw: bytes) -> int:
    try:
        raw.decode("utf-8")
        return 1
    except UnicodeDecodeError:
        return 0


def _asset(row, limits: ParserLimits = ParserLimits()) -> AssetEntry:
    original, canonical = row["original_path_bytes"], row["canonical_path_bytes"]
    if not isinstance(original, bytes) or not isinstance(canonical, bytes):
        raise CatalogError("Asset paths must be BLOBs.")
    display = original.decode("utf-8", "surrogateescape")
    try:
        expected = canonicalize_virtual_path(display, max_bytes=limits.max_path_bytes).encode("utf-8", "surrogateescape")
    except (VpkError, UnicodeError):
        raise CatalogError("Catalog resource path is unsafe or exceeds configured limits.") from None
    if expected != canonical or row["utf8_valid"] != _utf8(original):
        raise CatalogError("Asset comparison key or encoding flag is inconsistent.")
    return AssetEntry(display, canonical.decode("utf-8", "surrogateescape"), original, canonical,
                      *(row[key] for key in ("crc32", "preload_bytes", "archive_index", "archive_offset", "archive_length")))


def _insert(connection, table: str, values: dict) -> None:
    # Table/column identifiers are internal constants, all data is bound.
    connection.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))


class CatalogRepository:
    def __init__(self, database: CatalogDatabase, access: ScopedWorkshopAccess, *, limits: ParserLimits = ParserLimits(), max_total_assets: int = 1_000_000):
        self.database, self.access = database, access
        if max_total_assets <= 0:
            raise ValueError("The collection asset limit must be positive.")
        self.limits, self.max_total_assets = limits, max_total_assets
        root = access.validated_root
        with database.transaction() as connection:
            row = connection.execute("SELECT * FROM installations WHERE root_key=?", (root_key(root),)).fetchone()
            if row is None:
                self.installation_id = uuid4().hex
                _insert(connection, "installations", dict(installation_id=self.installation_id, root_path=str(root),
                    root_key=root_key(root), catalog_generation=0, created_at=utc_now()))
            else:
                # Path equivalence here is native lexical Windows equivalence, never broad Unicode casefold.
                if Path(row["root_path"]) != root:
                    raise CatalogError("Root comparison-key collision; installation scopes were not merged.")
                _uuid(row["installation_id"])
                _timestamp(row["created_at"])
                self.installation_id = row["installation_id"]

    @property
    def connection(self):
        return self.database.connection

    def load(self) -> tuple[int, tuple[IndexedPackage, ...]]:
        """Load a coherent saved snapshot. No saved path is opened as a game file."""
        with self.database.transaction() as connection:
            generation = connection.execute("SELECT catalog_generation FROM installations WHERE installation_id=?", (self.installation_id,)).fetchone()[0]
            rows = connection.execute("SELECT * FROM packages WHERE installation_id=? AND removed_at IS NULL ORDER BY relative_path_key", (self.installation_id,)).fetchall()
            records = []
            total = 0
            for row in rows:
                _uuid(row["package_id"])
                relative = row["relative_path"]
                _relative(relative)
                if row["relative_path_key"] != relative.casefold() or row["workshop_id"] != infer_workshop_id(relative.rsplit("/", 1)[1]):
                    raise CatalogError("Catalog physical comparison key or inferred ID is inconsistent.")
                signature = _signature(row, "observed_")
                preview = None
                if row["preview_relative_path"] is not None:
                    path = row["preview_relative_path"]
                    _relative(path, ".jpg")
                    preview = FileReference(path.rsplit("/", 1)[1], path, 0, 0)
                package = WorkshopPackage(FileReference(relative.rsplit("/", 1)[1], relative, signature[3], signature[4], signature), row["workshop_id"], preview)
                saved = connection.execute("SELECT * FROM package_indexes WHERE package_id=?", (row["package_id"],)).fetchone()
                index, indexed_signature = None, None
                if saved:
                    count = connection.execute("SELECT count(*) FROM assets WHERE package_id=?", (row["package_id"],)).fetchone()[0]
                    total += count
                    if total > self.max_total_assets or count > self.limits.max_entries or saved["tree_size"] > self.limits.max_tree_bytes:
                        raise CatalogError("Saved catalog exceeds the accepted resource limits.")
                    assets = tuple(_asset(asset, self.limits) for asset in connection.execute("SELECT * FROM assets WHERE package_id=? ORDER BY canonical_path_bytes", (row["package_id"],)))
                    index = VpkIndex(saved["vpk_version"], saved["tree_size"], saved["index_sha256"].hex(), assets,
                        tuple(sorted({asset.archive_index for asset in assets if asset.archive_index != EMBEDDED_ARCHIVE})),
                        saved["tree_size"] + (12 if saved["vpk_version"] == 1 else 28), sum(not _utf8(asset.original_path_bytes) for asset in assets))
                    if saved["parser_version"] == PARSER_VERSION and saved["canonicalization_version"] == CANONICALIZATION_VERSION:
                        indexed_signature = _signature(saved, "source_")
                # Saved state is always provisional, with fresh settling/removal timers.
                records.append(IndexedPackage(package, PackageStatus.UNAVAILABLE, index, indexed_signature))
            return generation, tuple(records)

    def publish(self, report: MonitorReport, base: int, started_at: str, *, issue_tokens: set = frozenset(), fault=None) -> tuple[str, int]:
        """Return outcome/generation only after commit. fault is an isolated test hook."""
        _timestamp(started_at)
        for record in report.records:
            _relative(record.package.file.relative_path)
            _metadata(record.package.file.signature, "observed_")
            if record.index:
                for asset in record.index.assets:
                    _asset(dict(original_path_bytes=asset.original_path_bytes, canonical_path_bytes=asset.canonical_path_bytes,
                        utf8_valid=_utf8(asset.original_path_bytes), crc32=asset.crc32, preload_bytes=asset.preload_bytes,
                        archive_index=asset.archive_index, archive_offset=asset.archive_offset, archive_length=asset.archive_length), self.limits)
        with self.database.transaction() as connection:
            cursor = connection.execute("INSERT INTO scan_runs(installation_id,started_at,outcome,base_generation) VALUES (?,?,'started',?)", (self.installation_id, started_at, base))
            scan_id = cursor.lastrowid
        try:
            with self.database.transaction() as connection:
                current = connection.execute("SELECT catalog_generation FROM installations WHERE installation_id=?", (self.installation_id,)).fetchone()[0]
                if current != base:
                    connection.execute("UPDATE scan_runs SET outcome='superseded',finished_at=?,directory_status=? WHERE scan_id=?", (utc_now(), report.discovery_status.value, scan_id))
                    return "superseded", current
                previous = {row["relative_path_key"]: row for row in connection.execute("SELECT * FROM packages WHERE installation_id=? AND removed_at IS NULL", (self.installation_id,))}
                ids = {}
                for record in report.records:
                    package = record.package
                    key = package.file.relative_path.casefold()
                    old = previous.get(key)
                    if old and Path(old["relative_path"]) != Path(package.file.relative_path):
                        raise CatalogError("Physical comparison-key collision; packages were not merged.")
                    package_id = old["package_id"] if old else uuid4().hex
                    ids[key] = package_id
                    if package.workshop_id:
                        connection.execute("INSERT INTO workshop_items VALUES (?,?) ON CONFLICT(workshop_id) DO NOTHING", (package.workshop_id, started_at))
                    seen = key in report.observed_paths
                    status = record.status
                    presence = "missing_pending" if status == PackageStatus.MISSING_PENDING else "unavailable" if status == PackageStatus.UNAVAILABLE else "present"
                    index_status = "current" if status == PackageStatus.INDEXED else "unavailable" if status in {PackageStatus.MISSING_PENDING, PackageStatus.UNAVAILABLE} else status.value
                    preview = package.preview.relative_path if seen and package.preview else old["preview_relative_path"] if old else None
                    preview_status = "present" if seen and package.preview else "missing" if seen and report.discovery_status == DiscoveryStatus.COMPLETE else "unknown"
                    if preview_status == "missing":
                        preview = None
                    values = dict(installation_id=self.installation_id, workshop_id=package.workshop_id,
                        relative_path=package.file.relative_path, relative_path_key=key, presence_status=presence,
                        index_status=index_status, **_metadata(package.file.signature, "observed_"),
                        preview_relative_path=preview, preview_status=preview_status,
                        first_seen_scan_id=old["first_seen_scan_id"] if old else scan_id,
                        last_seen_scan_id=scan_id if seen or not old else old["last_seen_scan_id"], state_scan_id=scan_id, removed_at=None)
                    if old:
                        connection.execute(f"UPDATE packages SET {','.join(column+'=?' for column in values)} WHERE package_id=?", (*values.values(), package_id))
                    else:
                        _insert(connection, "packages", dict(package_id=package_id, **values))
                    if status == PackageStatus.INDEXED and record.index:
                        self._save_index(connection, package_id, record, scan_id, fault)
                removals = {event.relative_path.casefold() for event in report.events if event.kind == "removed"}
                if removals and report.discovery_status != DiscoveryStatus.COMPLETE:
                    raise CatalogError("Removal requires confirmed complete observations.")
                for key in removals:
                    if key in previous and key not in ids:
                        if connection.execute("PRAGMA user_version").fetchone()[0] >= 3:
                            connection.execute("DELETE FROM planning_members WHERE installation_id=? AND package_id=?", (self.installation_id, previous[key]["package_id"]))
                        connection.execute("UPDATE packages SET presence_status='removed',index_status='unavailable',preview_relative_path=NULL,preview_status='missing',removed_at=?,state_scan_id=? WHERE package_id=?", (utc_now(), scan_id, previous[key]["package_id"]))
                for token in _issues(report):
                    if token not in issue_tokens:
                        relative, severity, code, message, signature = token
                        _insert(connection, "scan_issues", dict(installation_id=self.installation_id, scan_id=scan_id,
                            package_id=ids.get(relative.casefold()) if relative else None, relative_path=relative,
                            severity=severity, code=code, message=message))
                if fault:
                    fault("before_commit")
                connection.execute("UPDATE installations SET catalog_generation=? WHERE installation_id=?", (base + 1, self.installation_id))
                connection.execute("UPDATE scan_runs SET outcome='committed',finished_at=?,directory_status=?,committed_generation=? WHERE scan_id=?", (utc_now(), report.discovery_status.value, base + 1, scan_id))
            return "committed", base + 1
        except BaseException as error:
            try:
                with self.database.transaction() as connection:
                    connection.execute("UPDATE scan_runs SET outcome=?,finished_at=?,directory_status=? WHERE scan_id=?", ("interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed", utc_now(), report.discovery_status.value, scan_id))
                    _insert(connection, "scan_issues", dict(installation_id=self.installation_id, scan_id=scan_id, package_id=None,
                        relative_path=None, severity="error", code="CATALOG_COMMIT_FAILED", message="Catalog transaction rolled back; previous committed catalog retained."))
            except (sqlite3.Error, OSError, CatalogError):
                pass  # A started audit row is completion-unconfirmed, never a partial catalog.
            raise

    def _save_index(self, connection, package_id, record, scan_id, fault):
        index = record.index
        old = connection.execute("SELECT * FROM package_indexes WHERE package_id=?", (package_id,)).fetchone()
        if old and _signature(old, "source_") == record.indexed_signature and old["index_sha256"] == bytes.fromhex(index.index_sha256) and old["parser_version"] == PARSER_VERSION and old["canonicalization_version"] == CANONICALIZATION_VERSION:
            return
        values = dict(installation_id=self.installation_id, generation=old["generation"] + 1 if old else 1, indexed_scan_id=scan_id,
            vpk_version=index.version, tree_size=index.tree_size, index_sha256=bytes.fromhex(index.index_sha256),
            parser_version=PARSER_VERSION, canonicalization_version=CANONICALIZATION_VERSION, **_metadata(record.indexed_signature, "source_"))
        if old:
            connection.execute(f"UPDATE package_indexes SET {','.join(key+'=?' for key in values)} WHERE package_id=?", (*values.values(), package_id))
            connection.execute("DELETE FROM assets WHERE package_id=?", (package_id,))
        else:
            _insert(connection, "package_indexes", dict(package_id=package_id, **values))
        if fault:
            fault("after_asset_delete")
        connection.executemany("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?)", [
            (package_id, asset.canonical_path_bytes, asset.original_path_bytes, _utf8(asset.original_path_bytes), asset.crc32,
             asset.preload_bytes, asset.archive_index, asset.archive_offset, asset.archive_length) for asset in index.assets])

    def counts(self) -> dict:
        query = """SELECT count(*) packages, coalesce(sum(p.index_status='current'),0) current_indexes,
            coalesce(sum(p.preview_status='present'),0) matching_previews FROM packages p WHERE installation_id=? AND removed_at IS NULL"""
        result = dict(self.connection.execute(query, (self.installation_id,)).fetchone())
        result["current_assets"] = self.connection.execute("SELECT count(*) FROM assets a JOIN packages p USING(package_id) WHERE p.installation_id=? AND p.removed_at IS NULL AND p.index_status='current'", (self.installation_id,)).fetchone()[0]
        result["retained_assets"] = self.connection.execute("SELECT count(*) FROM assets a JOIN packages p USING(package_id) WHERE p.installation_id=?", (self.installation_id,)).fetchone()[0]
        return result


def _issues(report: MonitorReport) -> set:
    issues = {(item.relative_path, "error", item.code, item.message, ()) for item in report.diagnostics}
    for record in report.records:
        relative = record.package.file.relative_path
        if record.diagnostic and record.status == PackageStatus.ERROR:
            issues.add((relative, "error", record.diagnostic.code, record.diagnostic.message, record.package.file.signature))
        if record.index and record.index.non_utf8_paths and record.status == PackageStatus.INDEXED:
            issues.add((relative, "warning", "NON_UTF8_PATHS", "Internal resource paths contain undecoded bytes; original bytes retained.", record.indexed_signature))
    return issues


def _fingerprint(report: MonitorReport) -> tuple:
    return (report.discovery_status, tuple((record.package.file.relative_path, record.status,
        # Coalesce intermediate pending writes, but retain first pending and final outcomes.
        () if record.status == PackageStatus.PENDING else record.package.file.signature,
        record.package.preview.relative_path if record.package.preview else None,
        record.index.index_sha256 if record.index else None) for record in report.records), frozenset(_issues(report)))


class CatalogMonitor:
    """Opt-in durable wrapper. Reload/reset staged M2 state after failed/stale commits."""
    def __init__(self, repository: CatalogRepository, **monitor_options):
        self.repository, self.options = repository, monitor_options
        self.options.setdefault("limits", repository.limits)
        self.options.setdefault("max_total_assets", repository.max_total_assets)
        self.last_outcome = "provisional"
        self.last_scan_committed = False
        self._reload()

    def _reload(self):
        self.generation, records = self.repository.load()
        self.monitor = WorkshopMonitor(self.repository.access, initial_records=records, **self.options)
        self._fingerprint = None
        self._issue_tokens = set()
        self._startup = True
        self._startup_observed = False
        self._started_at = utc_now()
        self._startup_clock = self.monitor.clock()

    def poll(self, *, fault=None) -> MonitorReport:
        poll_started = utc_now()
        report = self.monitor.poll()
        first_startup_observation = self._startup and not self._startup_observed
        self._startup_observed = True
        fingerprint = _fingerprint(report)
        self.last_scan_committed = False
        # Combine startup settling observations into one attempt. Outages/empty roots publish immediately.
        startup_pending = self._startup and report.discovery_status == DiscoveryStatus.COMPLETE and any(record.status == PackageStatus.PENDING for record in report.records)
        if startup_pending and (first_startup_observation or self.monitor.clock() - self._startup_clock < self.monitor.settle_seconds):
            return report
        if fingerprint == self._fingerprint:
            return report
        try:
            outcome, generation = self.repository.publish(report, self.generation, self._started_at if self._startup else poll_started, issue_tokens=self._issue_tokens, fault=fault)
        except BaseException:
            self._reload()
            raise
        self.last_outcome = outcome
        if outcome == "superseded":
            self._reload()
            # Never expose the discarded candidate as a committed catalog view.
            return MonitorReport(DiscoveryStatus.UNAVAILABLE, tuple(self.monitor._records.values()),
                (Diagnostic("CATALOG_SUPERSEDED", "Another writer published newer data; fresh validation required."),), (), 0)
        self.generation = generation
        self.last_scan_committed = True
        self._startup = False
        self._fingerprint, self._issue_tokens = fingerprint, _issues(report)
        self._started_at = utc_now()
        return report
