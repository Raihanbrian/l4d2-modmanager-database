"""M1 discovery, M2 indexing, M3 persistence and M4 derived overlap reports."""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Sequence

from . import __version__
from .scanner import DiscoveryReport, discover
from .security import DiscoveryStatus, PathPolicyError, ScopedWorkshopAccess, WORKSHOP_RELATIVE
from .monitor import MonitorReport, PackageStatus, WorkshopMonitor, watch
from .catalog import CatalogMonitor, CatalogRepository
from .storage import CatalogDatabase, CatalogError, CatalogReader, StoragePolicy
from .conflicts import analyze_conflicts, format_conflicts
from .classification import catalog_cards, classification_statistics, refresh_classification
from .migrations import upgrade
import sqlite3


def format_report(report: DiscoveryReport) -> str:
    lines = ["L4D2 Mod Database - M1 Workshop discovery", f"Status: {report.status.value}"]
    if report.status not in {DiscoveryStatus.COMPLETE, DiscoveryStatus.MISSING}:
        lines.append("WARNING: Incomplete discovery; counts are accepted candidates, not a complete installed-mod list.")
    lines.append(f"Scope: {WORKSHOP_RELATIVE} (direct .vpk/.jpg files only)")
    for package in report.packages:
        lines.extend((
            "",
            f"VPK: {json.dumps(package.file.filename, ensure_ascii=True)}",
            f"  Relative path: {json.dumps(package.file.relative_path, ensure_ascii=True)}",
            f"  Workshop ID (inferred): {package.workshop_id or 'Unknown'}",
            f"  Matching JPG: {json.dumps(package.preview.relative_path, ensure_ascii=True) if package.preview else 'None safely discovered'}",
        ))
    matched = {package.preview.relative_path for package in report.packages if package.preview}
    for preview in report.previews:
        if preview.relative_path not in matched:
            lines.append(f"Unmatched JPG: {json.dumps(preview.relative_path, ensure_ascii=True)}")
    lines.append("")
    if report.status == DiscoveryStatus.MISSING:
        lines.append("0 Workshop mods / folder not found")
    lines.append(f"Accepted candidates: {len(report.packages)} VPK(s), {len(report.previews)} JPG(s); {len(matched)} package(s) with a matching JPG.")
    for diagnostic in report.diagnostics:
        location = f" ({json.dumps(diagnostic.relative_path, ensure_ascii=True)})" if diagnostic.relative_path else ""
        lines.append(f"[{diagnostic.code}]{location} {diagnostic.message}")
    lines.append("Metadata only; VPK validity, download stability and installed/enabled state are not verified.")
    return "\n".join(lines)


def format_index_report(report: MonitorReport, *, list_assets: bool = False, events_only: bool = False) -> str:
    current = sum(record.status == PackageStatus.INDEXED for record in report.records)
    stale = sum(record.stale for record in report.records)
    assets = sum(len(record.index.assets) for record in report.records if record.index and record.status == PackageStatus.INDEXED)
    undecoded = sum(record.index.non_utf8_paths for record in report.records if record.index)
    lines = [
        f"M2 discovery: {report.discovery_status.value}; current indexes: {current}/{len(report.records)}; stale retained: {stale}; current assets: {assets}; parse attempts: {report.parse_attempts}",
    ]
    if undecoded:
        lines.append(f"[NON_UTF8_PATHS] {undecoded} path(s) retained losslessly; source encoding and engine comparison behavior remain unverified.")
    if not events_only:
        for record in report.records:
            file = record.package.file
            index = record.index
            lines.append(f"VPK {json.dumps(file.filename)}: {record.status.value}; ID {record.package.workshop_id or 'Unknown'}; assets {len(index.assets) if index else 0}{' (last valid index; stale)' if record.stale else ''}")
            if index:
                lines.append(f"  VPK v{index.version}; header/tree SHA-256 {index.index_sha256}; index bytes read {index.bytes_read}")
                if index.external_archives:
                    lines.append(f"  External archive references: {index.external_archives}; payload availability/integrity unverified.")
                if index.non_utf8_paths:
                    lines.append(f"  [NON_UTF8_PATHS] {index.non_utf8_paths} path(s) preserved as raw bytes with escaped display; encoding/engine case behavior unverified.")
                if list_assets:
                    for asset in index.assets:
                        lines.append(f"  Asset {json.dumps(asset.original_path)} -> {json.dumps(asset.canonical_path)}")
            if record.diagnostic:
                lines.append(f"  [{record.diagnostic.code}] {record.diagnostic.message}")
    for event in report.events:
        lines.append(f"Event {event.kind}: {json.dumps(event.relative_path)}; {event.message}")
    for diagnostic in report.diagnostics:
        lines.append(f"[{diagnostic.code}] {diagnostic.message}")
    return "\n".join(lines)


def _positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Use positive finite seconds.") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("Use positive finite seconds.")
    return seconds


def _positive_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Use a positive whole number.") from None
    if count <= 0:
        raise argparse.ArgumentTypeError("Use a positive whole number.")
    return count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only discovery (M1), indexing (M2), opt-in catalog (M3) and saved-catalog path overlaps (M4).")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--game-root", required=True, help="Explicit absolute local L4D2 game root containing left4dead2/addons")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--index", action="store_true", help="Index stable VPK directories once (two observations)")
    modes.add_argument("--watch", action="store_true", help="Automatically poll and incrementally index until Ctrl+C")
    modes.add_argument("--conflicts", action="store_true", help="M4: analyze saved catalog path overlaps without scanning or catalog writes")
    modes.add_argument("--classify", action="store_true", help="M5: safely upgrade existing catalog and derive classifications from indexed evidence")
    parser.add_argument("--list-assets", action="store_true", help="With --index: list original and canonical internal paths")
    parser.add_argument("--catalog", action="store_true", help="With --index/--watch: persist in LOCALAPPDATA/L4D2ModDatabase")
    parser.add_argument("--include-retained", action="store_true", help="With --conflicts: include nonremoved stale evidence in a separate section")
    parser.add_argument("--json", action="store_true", help="With --conflicts: emit structured evidence and coverage JSON")
    parser.add_argument("--settle-seconds", type=_positive_seconds, default=2.0, help="Unchanged observation interval before index/removal (default: 2)")
    parser.add_argument("--poll-interval", type=_positive_seconds, default=1.0, help="Watch polling seconds (default: 1)")
    parser.add_argument("--cycles", type=_positive_count, help="Bound --watch to this many polls (default: continuous)")
    args = parser.parse_args(argv)
    if args.list_assets and not args.index:
        parser.error("--list-assets requires --index")
    if args.cycles is not None and not args.watch:
        parser.error("--cycles requires --watch")
    if args.catalog and not (args.index or args.watch):
        parser.error("--catalog requires --index or --watch")
    if args.include_retained and not args.conflicts:
        parser.error("--include-retained requires --conflicts")
    if args.json and not (args.conflicts or args.classify):
        parser.error("--json requires --conflicts or --classify")
    try:
        access = ScopedWorkshopAccess(args.game_root)
    except PathPolicyError as error:
        parser.error(f"[{error.code}] {error}")
    if args.classify:
        try:
            policy = StoragePolicy.production(access, create=False)
            with CatalogReader(policy) as reader:
                installation_id = reader.installation_id(access)
            with CatalogDatabase(policy) as database:
                migration = upgrade(database)
                changed = refresh_classification(database, installation_id)
                result = dict(classification_statistics(catalog_cards(database.connection, installation_id)),
                    refreshed_packages=changed, schema_version=database.connection.execute("PRAGMA user_version").fetchone()[0],
                    verified_backup=migration.backup_path if migration else None,
                    source="Saved current indexes; no remote metadata or replacement-identity detection.")
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 0
        except (CatalogError, PathPolicyError, sqlite3.Error, OSError, ValueError):
            print(json.dumps(dict(error="CLASSIFICATION_FAILED", message="Classification/upgrade could not complete; existing catalog and user input were preserved.")))
            return 1
    if args.conflicts:
        try:
            policy = StoragePolicy.production(access, create=False)
            with CatalogReader(policy) as reader:
                report = analyze_conflicts(reader.connection, reader.installation_id(access), include_retained=args.include_retained)
            print(json.dumps(report.to_dict(), ensure_ascii=True, indent=2) if args.json else format_conflicts(report))
            return 0 if report.coverage.complete else 1
        except (CatalogError, PathPolicyError, sqlite3.Error, OSError, UnicodeError) as error:
            reason = str(error) if isinstance(error, (CatalogError, PathPolicyError)) else "Catalog could not be read safely."
            payload = dict(error="CONFLICT_ANALYSIS_FAILED", coverage_status="not_evaluated", reason=reason,
                message="Saved catalog analysis failed or exceeded its safeguards; no complete overlap result was produced. No catalog was created or modified.")
            print(json.dumps(payload) if args.json else payload["message"] + "\n" + reason)
            return 1
    if args.index or args.watch:
        database = None
        report = None
        try:
            if args.catalog:
                database = CatalogDatabase(StoragePolicy.production(access))
                monitor = CatalogMonitor(CatalogRepository(database, access), settle_seconds=args.settle_seconds)
            else:
                monitor = WorkshopMonitor(access, settle_seconds=args.settle_seconds)
            if args.index:
                report = monitor.poll()
                if report.records:
                    time.sleep(args.settle_seconds)
                    report = monitor.poll()
                print(format_index_report(report, list_assets=args.list_assets), flush=True)
                if args.catalog:
                    print(f"M3 catalog: {monitor.last_outcome}; generation {monitor.generation}; " + json.dumps(monitor.repository.counts()), flush=True)
            else:
                previous_diagnostics = None
                for report in watch(monitor, interval=args.poll_interval, cycles=args.cycles):
                    if report.events or report.diagnostics != previous_diagnostics:
                        print(format_index_report(report, events_only=True), flush=True)
                    if args.catalog and monitor.last_scan_committed:
                        print(f"M3 catalog committed: generation {monitor.generation}", flush=True)
                    previous_diagnostics = report.diagnostics
        except KeyboardInterrupt:
            print("Monitoring stopped; game files were opened read-only.", flush=True)
        except (CatalogError, PathPolicyError, sqlite3.Error, OSError, UnicodeError):
            print("M3 catalog operation failed; prior committed data retained. No fallback database was created.", flush=True)
            return 1
        finally:
            if database is not None:
                database.close()
        return 0 if report is not None and report.ready else 1
    report = discover(access)
    print(format_report(report))
    return 0 if report.status in {DiscoveryStatus.COMPLETE, DiscoveryStatus.MISSING} else 1
