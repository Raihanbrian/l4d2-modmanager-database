"""Reproducible, read-only M2 smoke validation; no default game root or writes."""

import argparse
from collections import Counter
import json

from l4d2_mod_db.cli import _positive_seconds
from l4d2_mod_db.monitor import PackageStatus, WorkshopMonitor, watch
from l4d2_mod_db.scanner import discover
from l4d2_mod_db.security import PathPolicyError, ScopedWorkshopAccess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True)
    parser.add_argument("--settle-seconds", type=_positive_seconds, default=2.0)
    args = parser.parse_args()
    try:
        access = ScopedWorkshopAccess(args.game_root)
    except PathPolicyError as error:
        parser.error(f"[{error.code}] {error}")
    before = discover(access)
    monitor = WorkshopMonitor(access, settle_seconds=args.settle_seconds)
    reports = list(watch(monitor, interval=args.settle_seconds, cycles=3))
    final = reports[-1]
    after = discover(access)
    indexes = [record.index for record in final.records if record.index]
    result = {
        "discovery_status": after.status.value,
        "vpk_candidates": len(after.packages),
        "matching_previews": sum(package.preview is not None for package in after.packages),
        "current_indexes": sum(record.status == PackageStatus.INDEXED for record in final.records),
        "versions": dict(Counter(index.version for index in indexes)),
        "asset_entries": sum(len(index.assets) for index in indexes),
        "header_tree_bytes_read": sum(index.bytes_read for index in indexes),
        "non_utf8_paths": sum(index.non_utf8_paths for index in indexes),
        "non_utf8_packages": sum(index.non_utf8_paths > 0 for index in indexes),
        "external_archive_packages": sum(bool(index.external_archives) for index in indexes),
        "parse_attempts_after_index": reports[1].parse_attempts,
        "parse_attempts_after_unchanged_poll": final.parse_attempts,
        "unchanged_poll_events": len(final.events),
        "vpk_and_jpg_references_unchanged": before == after,
        "ready": final.ready,
        "errors": [
            {"filename": record.package.file.filename, "code": record.diagnostic.code, "message": record.diagnostic.message}
            for record in final.records if record.diagnostic
        ],
    }
    print(json.dumps(result, indent=2))
    return 0 if final.ready and before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
