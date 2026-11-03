"""M4 read-only saved-catalog analysis plus bounded Workshop metadata validation."""

import argparse
from collections import defaultdict
from dataclasses import asdict, replace
import json
import sqlite3
import time

from l4d2_mod_db.cli import _positive_seconds
from l4d2_mod_db.conflicts import analyze_conflicts
from l4d2_mod_db.scanner import discover
from l4d2_mod_db.security import Diagnostic, DiscoveryStatus, PathPolicyError, ScopedWorkshopAccess
from l4d2_mod_db.storage import CatalogError, CatalogReader, StoragePolicy


def row_counts(connection):
    tables = ("installations", "workshop_items", "scan_runs", "packages", "package_indexes", "assets", "scan_issues")
    return {table: connection.execute("SELECT count(*) FROM " + table).fetchone()[0] for table in tables}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True)
    parser.add_argument("--settle-seconds", type=_positive_seconds, default=2.0)
    args = parser.parse_args()
    try:
        access = ScopedWorkshopAccess(args.game_root)
        before = discover(access)
        time.sleep(args.settle_seconds)
        observed = discover(access)
        stable_observations = before == observed
        if not stable_observations:
            observed = replace(observed, status=DiscoveryStatus.PARTIAL,
                diagnostics=observed.diagnostics + (Diagnostic("OBSERVATION_CHANGED", "Workshop metadata changed between observations; coverage uncertain."),))
        started = time.perf_counter()
        with CatalogReader(StoragePolicy.production(access, create=False)) as reader:
            open_seconds = time.perf_counter() - started
            installation_id = reader.installation_id(access)
            counts_before = row_counts(reader.connection)
            started = time.perf_counter()
            report = analyze_conflicts(reader.connection, installation_id, observation=observed)
            seconds = time.perf_counter() - started
            started = time.perf_counter()
            repeated = analyze_conflicts(reader.connection, installation_id, observation=observed)
            repeat_seconds = time.perf_counter() - started
            examples = []
            # Prefer multi-path examples; counters still include every path, including addon metadata.
            for pair in sorted(report.current_findings, key=lambda pair: (-pair.overlapping_path_count, pair.package_a.package_id, pair.package_b.package_id))[:5]:
                example = pair.to_dict()
                example["paths"] = example["paths"][:5]
                examples.append(example)
            path_owners = defaultdict(set)
            for pair in report.current_findings:
                for path in pair.canonical_paths:
                    path_owners[path].update((pair.package_a.package_id, pair.package_b.package_id))
            frequent_paths = [dict(display=path.decode("utf-8", "backslashreplace"), canonical_path_hex=path.hex(), packages=len(owners))
                for path, owners in sorted(path_owners.items(), key=lambda item: (-len(item[1]), item[0]))[:5]]
            result = dict(observed_workshop_status=observed.status.value, observed_vpk_count=len(observed.packages),
                observed_jpg_count=len(observed.previews), stable_observations=stable_observations,
                coverage=asdict(report.coverage), overlap_counts=report.counts,
                example_pairs=examples, most_shared_paths=frequent_paths,
                excluded_or_uncertain=[asdict(package) for package in report.packages if package.included_as != "current"],
                uncataloged_relative_paths=list(report.uncataloged_relative_paths),
                reader_open_and_schema_validation_seconds=round(open_seconds, 6), analysis_seconds=round(seconds, 6),
                repeated_analysis_seconds=round(repeat_seconds, 6), stable_repeated_results=report == repeated,
                catalog_row_counts_unchanged=counts_before == row_counts(reader.connection), catalog_connection_changes=reader.connection.total_changes,
                schema_version=reader.connection.execute("PRAGMA user_version").fetchone()[0],
                integrity_check=reader.connection.execute("PRAGMA integrity_check").fetchone()[0],
                foreign_key_violations=len(reader.connection.execute("PRAGMA foreign_key_check").fetchall()))
        result["workshop_references_unchanged_after_analysis"] = discover(access) == before
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0 if all((report.coverage.complete, stable_observations, result["stable_repeated_results"],
            result["catalog_row_counts_unchanged"], result["catalog_connection_changes"] == 0,
            result["integrity_check"] == "ok", result["foreign_key_violations"] == 0,
            result["workshop_references_unchanged_after_analysis"])) else 1
    except (CatalogError, PathPolicyError, sqlite3.Error, OSError) as error:
        reason = str(error) if isinstance(error, (CatalogError, PathPolicyError)) else "Catalog or Workshop metadata could not be read safely."
        print(json.dumps(dict(error="M4_VALIDATION_FAILED", reason=reason, message="Read-only validation could not complete; no complete result is claimed.")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
