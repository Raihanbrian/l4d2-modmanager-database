"""M4 fixture, read-snapshot, byte-safety and CLI regression coverage."""

from contextlib import closing
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import patch

from l4d2_mod_db.conflicts import AnalysisLimits, ConflictAnalysisError, analyze_conflicts, format_conflicts
from l4d2_mod_db.scanner import discover
from l4d2_mod_db.security import DiscoveryStatus
from l4d2_mod_db.storage import CatalogDatabase, CatalogReader, StoragePolicy
from tools.create_demo import create_demo
from .helpers import FixtureTestCase, PROJECT_ROOT
from .test_catalog import CatalogFixture
from .vpk_fixtures import build_vpk


class ConflictTests(CatalogFixture):
    def test_inconsistent_saved_physical_path_is_not_current_evidence(self):
        self.overlapping()
        self.db.connection.execute("UPDATE packages SET relative_path='../../unrelated.vpk' WHERE workshop_id='2'")
        report = self.analyze(include_retained=True)
        self.assertEqual(report.current_findings + report.retained_findings, ())
        self.assertEqual(report.coverage.current_eligible_packages, 1)
        self.assertFalse(report.coverage.complete)
        package = next(package for package in report.packages if package.workshop_id == "2")
        self.assertIn("INVALID_PACKAGE_METADATA", [reason.code for reason in package.reasons])

    def test_generated_collection_matches_independent_sql_join_oracle(self):
        import random
        randomizer = random.Random(20261029)
        for number in range(8):
            paths = tuple(f"scripts/path_{index}.txt" for index in range(9) if randomizer.randrange(3) == 0)
            self.add(f"{number}.vpk", paths)
        self.settle()
        actual = {(pair.package_a.package_id, pair.package_b.package_id, path)
            for pair in self.analyze().current_findings for path in pair.canonical_paths}
        expected = {tuple(row) for row in self.db.connection.execute("""SELECT a.package_id,b.package_id,a.canonical_path_bytes
            FROM assets a JOIN assets b ON a.canonical_path_bytes=b.canonical_path_bytes AND a.package_id<b.package_id""")}
        self.assertEqual(actual, expected)

    def analyze(self, **options):
        return analyze_conflicts(self.db.connection, self.repo.installation_id, **options)

    def overlapping(self, count=2, paths=("materials/shared.vmt",)):
        for number in range(count): self.add(f"{number+1}.vpk", paths)
        self.settle()

    def test_two_packages_one_path_and_identity(self):
        self.overlapping()
        report = self.analyze()
        self.assertEqual(report.counts["current_package_pairs"], 1)
        self.assertEqual(report.counts["current_unique_paths"], 1)
        pair = report.current_findings[0]
        self.assertNotEqual(pair.package_a.package_id, pair.package_b.package_id)
        self.assertEqual(pair.canonical_paths, (b"materials/shared.vmt",))
        self.assertEqual({pair.package_a.workshop_id, pair.package_b.workshop_id}, {"1", "2"})
        self.assertEqual({pair.package_a.filename, pair.package_b.filename}, {"1.vpk", "2.vpk"})
        self.assertTrue(report.coverage.complete)
        self.assertEqual(report.coverage.current_asset_entries, 2)

    def test_multiple_paths_are_one_pair(self):
        self.overlapping(paths=("sound/shared.wav", "materials/shared.vmt", "scripts/shared.txt"))
        report = self.analyze()
        self.assertEqual(report.counts["current_package_pairs"], 1)
        self.assertEqual(report.counts["current_unique_paths"], 3)
        self.assertEqual(report.current_findings[0].overlapping_path_count, 3)

    def test_four_owners_generate_all_six_pairs_not_six_paths(self):
        self.overlapping(count=4)
        report = self.analyze()
        self.assertEqual(report.counts["current_package_pairs"], 6)
        self.assertEqual(report.counts["current_unique_paths"], 1)
        identities = {(pair.package_a.package_id, pair.package_b.package_id) for pair in report.current_findings}
        self.assertEqual(len(identities), 6)
        self.assertTrue(all(left < right for left, right in identities))

    def test_disjoint_paths_and_self_overlap_never_reported(self):
        self.add("1.vpk", ("scripts/one.txt",)); self.add("2.vpk", ("scripts/two.txt",)); self.settle()
        self.assertEqual(self.analyze().current_findings, ())
        self.assertTrue(self.analyze().coverage.complete)

    def test_original_case_and_separator_spelling_uses_approved_key(self):
        self.add("1.vpk", (r"Materials\Shared/Finish.vmt",))
        self.add("2.vpk", ("materials/shared/finish.vmt",)); self.settle()
        self.assertEqual(self.analyze().current_findings[0].canonical_paths, (b"materials/shared/finish.vmt",))

    def test_non_utf8_matching_and_nonmatching_bytes(self):
        for name, raw in (("1.vpk", b"\xb8\xb1\xb1\xbe"), ("2.vpk", b"\xb8\xb1\xb1\xbe"), ("3.vpk", b"\xb8\xb1\xb1\xbf")):
            content = build_vpk(("Sound/Voice_ABCD.wav",)).replace(b"ABCD", raw)
            self.put("left4dead2/addons/workshop/" + name, content)
        self.settle(); report = self.analyze()
        self.assertEqual(report.counts["current_package_pairs"], 1)
        path = report.current_findings[0].canonical_paths[0]
        self.assertEqual(path, b"sound/voice_\xb8\xb1\xb1\xbe.wav")
        rendered = json.dumps(report.to_dict(), ensure_ascii=True)
        self.assertNotIn("\ufffd", rendered)
        self.assertIn("b8b1b1be", rendered)
        self.assertIn("\\\\xb8", rendered)

    def test_stable_results_no_duplicate_audit_join_multiplication(self):
        self.overlapping(paths=("scripts/a.txt", "scripts/b.txt"))
        for _ in range(4): self.settle(self.new_session())
        before = self.snapshot(); total_changes = self.db.connection.total_changes
        first = self.analyze().to_dict()
        for _ in range(10): self.assertEqual(self.analyze().to_dict(), first)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.db.connection.total_changes, total_changes)
        self.assertEqual(first["counts"]["current_package_pairs"], 1)
        self.assertEqual(len(first["current_findings"][0]["paths"]), 2)

    def test_corrupt_update_excluded_but_optional_retained_pair(self):
        self.overlapping(); (self.workshop / "2.vpk").write_bytes(b"broken"); self.settle()
        current = self.analyze()
        self.assertEqual(current.current_findings, ())
        self.assertFalse(current.coverage.complete)
        self.assertEqual(current.coverage.uncertain_active_packages, 1)
        retained = self.analyze(include_retained=True)
        self.assertEqual(len(retained.retained_findings), 1)
        self.assertEqual(retained.retained_findings[0].evidence_freshness, "retained")
        self.assertEqual(retained.counts["current_package_pairs"], 0)
        self.assertIn("INCOMPLETE", format_conflicts(current))
        self.assertNotIn("No conflicts", format_conflicts(current))

    def test_two_stale_packages_form_retained_pair_only(self):
        self.overlapping()
        self.db.connection.execute("UPDATE packages SET presence_status='unavailable',index_status='unavailable'")
        report = self.analyze(include_retained=True)
        self.assertEqual(report.current_findings, ())
        self.assertEqual(len(report.retained_findings), 1)
        self.assertEqual(report.coverage.current_asset_entries, 0)
        self.assertEqual(report.coverage.retained_asset_entries, 2)

    def test_pending_existing_index_is_not_current(self):
        self.overlapping(); self.db.connection.execute("UPDATE packages SET index_status='pending' WHERE workshop_id='2'")
        self.assertEqual(self.analyze().current_findings, ())
        self.assertEqual(len(self.analyze(include_retained=True).retained_findings), 1)

    def test_missing_pending_is_not_current(self):
        self.overlapping(); (self.workshop / "2.vpk").unlink(); self.session.poll()
        self.assertEqual(self.analyze().coverage.current_eligible_packages, 1)
        self.assertFalse(self.analyze().coverage.complete)

    def test_new_corrupt_and_pending_have_no_fabricated_evidence(self):
        self.overlapping()
        self.put("left4dead2/addons/workshop/broken.vpk", b"bad"); self.settle()
        self.add("pending.vpk"); self.session.poll()
        report = self.analyze(include_retained=True)
        self.assertEqual(report.coverage.current_eligible_packages, 2)
        self.assertEqual(report.coverage.uncertain_active_packages, 2)
        self.assertEqual(len(report.current_findings), 1)
        excluded = [package for package in report.packages if package.included_as == "excluded"]
        self.assertEqual(len(excluded), 2)
        self.assertTrue(all(package.asset_entries == 0 for package in excluded))

    def test_removed_always_excluded_including_retained_mode(self):
        self.overlapping(); (self.workshop / "2.vpk").unlink(); self.settle()
        report = self.analyze(include_retained=True)
        self.assertEqual(report.current_findings + report.retained_findings, ())
        self.assertEqual(report.coverage.removed_packages, 1)
        self.assertEqual(report.coverage.uncertain_active_packages, 0)
        self.assertTrue(report.coverage.complete)
        self.assertEqual(self.scalar("SELECT count(*) FROM assets"), 2)

    def test_mixed_triple_separates_current_and_retained_counts(self):
        self.overlapping(count=3)
        self.db.connection.execute("UPDATE packages SET index_status='error' WHERE workshop_id='3'")
        report = self.analyze(include_retained=True)
        self.assertEqual(report.counts, dict(current_package_pairs=1, current_unique_paths=1,
            retained_package_pairs=2, retained_unique_paths=1, combined_unique_paths=1, combined_package_pairs=3))

    def test_policy_incompatibility_is_explicit_and_not_compared(self):
        self.overlapping()
        self.db.connection.execute("UPDATE package_indexes SET canonicalization_version='unknown-path-v2' WHERE package_id=(SELECT package_id FROM packages WHERE workshop_id='2')")
        report = self.analyze(include_retained=True)
        self.assertEqual(report.current_findings + report.retained_findings, ())
        excluded = next(package for package in report.packages if package.workshop_id == "2")
        self.assertEqual(excluded.canonicalization_version, "unknown-path-v2")
        self.assertIn("INCOMPATIBLE_CANONICALIZATION", [reason.code for reason in excluded.reasons])

    def test_unsupported_parser_is_excluded(self):
        self.overlapping(); self.db.connection.execute("UPDATE package_indexes SET parser_version='unknown-parser'")
        self.assertEqual(self.analyze(include_retained=True).coverage.current_eligible_packages, 0)

    def test_source_mismatch_despite_current_status_downgrades_evidence(self):
        self.overlapping(); self.db.connection.execute("UPDATE packages SET observed_size_bytes=observed_size_bytes+1 WHERE workshop_id='2'")
        report = self.analyze(include_retained=True)
        self.assertEqual(report.counts["current_package_pairs"], 0)
        self.assertEqual(report.counts["retained_package_pairs"], 1)

    def test_invalid_canonical_bytes_exclude_entire_index(self):
        self.overlapping(paths=("scripts/a.txt", "scripts/b.txt"))
        self.db.connection.execute("UPDATE assets SET canonical_path_bytes=X'7a7a' WHERE package_id=(SELECT package_id FROM packages WHERE workshop_id='2') AND canonical_path_bytes=?", (b"scripts/b.txt",))
        report = self.analyze(include_retained=True)
        self.assertEqual(report.current_findings + report.retained_findings, ())
        self.assertEqual(report.coverage.current_eligible_packages, 1)

    def test_incomplete_directory_and_failed_audit_warn_even_with_valid_indexes(self):
        self.overlapping()
        self.db.connection.execute("UPDATE scan_runs SET directory_status='partial' WHERE outcome='committed'")
        report = self.analyze()
        self.assertFalse(report.coverage.complete)
        self.assertEqual(len(report.current_findings), 1)
        self.assertIn("INCOMPLETE_DIRECTORY", [reason.code for reason in report.coverage.diagnostics])

    def test_unconfirmed_newer_attempt_marks_coverage_incomplete(self):
        self.overlapping()
        self.db.connection.execute("INSERT INTO scan_runs(installation_id,started_at,outcome,base_generation) VALUES (?,'2026-10-29T01:00:00.000000Z','started',1)", (self.repo.installation_id,))
        self.assertFalse(self.analyze().coverage.complete)

    def test_unknown_scope_and_uncommitted_catalog(self):
        with self.assertRaises(ConflictAnalysisError): analyze_conflicts(self.db.connection, "unknown")
        self.assertFalse(self.analyze().coverage.complete)
        self.session.poll()
        self.assertTrue(self.analyze().coverage.complete)

    def test_existing_caller_transaction_is_not_committed_or_rolled_back(self):
        self.db.connection.execute("BEGIN")
        try:
            with self.assertRaises(ConflictAnalysisError): self.analyze()
            self.assertTrue(self.db.connection.in_transaction)
        finally: self.db.connection.rollback()

    def test_budget_failures_are_explicit_not_truncated_clean_results(self):
        self.overlapping(count=3)
        for limits in (AnalysisLimits(max_asset_entries=2), AnalysisLimits(max_pair_path_matches=2)):
            with self.subTest(limits=limits), self.assertRaisesRegex(ConflictAnalysisError, "ANALYSIS_LIMIT"):
                self.analyze(limits=limits)
            self.assertFalse(self.db.connection.in_transaction)
        with self.assertRaises(ValueError): AnalysisLimits(max_pair_path_matches=0)

    def test_after_persisted_update_and_database_restart(self):
        self.overlapping()
        identities = {package.package_id for package in self.analyze().packages}
        self.add("2.vpk", ("scripts/disjoint.txt",)); self.settle()
        self.db.close(); self.db = CatalogDatabase(self.policy)
        self.assertEqual(self.analyze().current_findings, ())
        self.assertEqual({package.package_id for package in self.analyze().packages}, identities)

    def test_different_apparent_survivor_targets_still_share_material(self):
        self.add("zoey_example.vpk", ("models/survivors/zoey_example.mdl", "materials/shared/finish.vmt"))
        self.add("rochelle_example.vpk", ("models/survivors/rochelle_example.mdl", "materials/shared/finish.vmt")); self.settle()
        self.assertEqual(self.analyze().current_findings[0].canonical_paths, (b"materials/shared/finish.vmt",))

    def test_fresh_metadata_matches_without_opening_vpk_contents(self):
        self.overlapping()
        with patch.object(self.access, "open_vpk", side_effect=AssertionError("No parser reads in analysis")):
            report = self.analyze(observation=discover(self.access))
        self.assertTrue(report.coverage.complete)
        self.assertEqual(report.coverage.live_verification, "metadata_observation")

    def test_fresh_observation_catches_new_missing_and_changed_files(self):
        self.overlapping(count=3)
        (self.workshop / "1.vpk").unlink()
        self.add("2.vpk", ("scripts/changed.txt",)); self.add("4.vpk")
        report = self.analyze(observation=discover(self.access), include_retained=True)
        self.assertEqual(report.coverage.current_eligible_packages, 1)
        self.assertEqual(report.coverage.uncertain_active_packages, 2)
        self.assertEqual(report.coverage.uncataloged_observed_packages, 1)
        self.assertEqual(report.current_findings, ())
        self.assertEqual(len(report.retained_findings), 3)
        self.assertEqual(self.scalar("SELECT count(*) FROM packages WHERE removed_at IS NOT NULL"), 0)

    def test_incomplete_fresh_observation_never_establishes_complete_coverage(self):
        self.overlapping()
        observation = replace(discover(self.access), status=DiscoveryStatus.PARTIAL)
        report = self.analyze(observation=observation)
        self.assertFalse(report.coverage.complete)

    def test_other_installation_resources_are_never_joined(self):
        from l4d2_mod_db.catalog import CatalogRepository
        from l4d2_mod_db.security import ScopedWorkshopAccess
        self.add("1.vpk"); self.settle()
        other = self.make_game("another")
        (other / "left4dead2/addons/workshop/2.vpk").write_bytes(build_vpk(("Models/Weapons/Example.mdl",)))
        self.settle(self.new_session(CatalogRepository(self.db, ScopedWorkshopAccess(other))))
        self.assertEqual(self.analyze().current_findings, ())
        self.assertEqual(len(self.analyze().packages), 1)

    def test_reader_readonly_snapshot_and_concurrent_writer(self):
        self.overlapping()
        with CatalogReader(self.policy) as reader:
            with self.assertRaises(sqlite3.OperationalError): reader.connection.execute("DELETE FROM assets")
            changed = [False]
            def trace(sql):
                if not changed[0] and sql.startswith("SELECT original_path_bytes"):
                    changed[0] = True
                    self.db.connection.execute("UPDATE packages SET index_status='pending' WHERE workshop_id='2'")
            reader.connection.set_trace_callback(trace)
            report = analyze_conflicts(reader.connection, reader.installation_id(self.access))
            self.assertEqual(len(report.current_findings), 1)
            reader.connection.set_trace_callback(None)
            self.assertEqual(analyze_conflicts(reader.connection, self.repo.installation_id).current_findings, ())


class DemoConflictTests(FixtureTestCase):
    def test_approved_demo_A_E_share_exactly_two_paths(self):
        demo = PROJECT_ROOT / "examples/m3-demo/m3_demo.sqlite3"
        before = hashlib.sha256(demo.read_bytes()).digest()
        with closing(sqlite3.connect(demo.as_uri() + "?mode=ro", uri=True, isolation_level=None)) as connection:
            report = analyze_conflicts(connection, "7c1a9e306b454d0d9a651827d9f3ac10", include_retained=True)
        self.assertEqual(report.counts["current_package_pairs"], 1)
        self.assertEqual(report.counts["current_unique_paths"], 2)
        pair = report.current_findings[0]
        self.assertEqual((pair.package_a.package_id, pair.package_b.package_id), ("0cda40ac6e9b4a31b8876270e6b508a1", "5e9d71346c2741f4a8803d96b3a429e5"))
        self.assertEqual(pair.canonical_paths, (b"materials/shared/finish.vmt", b"models/weapons/v_rifle_ak47.mdl"))
        self.assertEqual(report.coverage.current_eligible_packages, 3)
        self.assertEqual(report.coverage.current_asset_entries, 7)
        self.assertEqual(report.coverage.uncertain_active_packages, 2)
        self.assertFalse(report.coverage.complete)
        self.assertEqual(hashlib.sha256(demo.read_bytes()).digest(), before)


class ConflictCliTests(CatalogFixture):
    def test_read_only_validation_utility_reports_observation_and_evidence(self):
        self.create_production_fixture()
        result = subprocess.run([sys.executable, "-B", "-m", "tools.validate_conflicts", "--game-root", str(self.game), "--settle-seconds", "0.01"],
            cwd=PROJECT_ROOT, env=dict(os.environ, LOCALAPPDATA=str(self.workspace)), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["observed_vpk_count"], 2)
        self.assertEqual(report["overlap_counts"]["current_package_pairs"], 1)
        self.assertTrue(report["stable_repeated_results"])
        self.assertTrue(report["catalog_row_counts_unchanged"])
        self.assertEqual(report["catalog_connection_changes"], 0)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", "-m", "l4d2_mod_db", "--game-root", str(self.game), *args],
            cwd=PROJECT_ROOT, env=dict(os.environ, LOCALAPPDATA=str(self.workspace)), capture_output=True, text=True, timeout=20)

    def create_production_fixture(self):
        self.add("1.vpk", ("materials/shared.vmt",)); self.add("2.vpk", ("materials/shared.vmt",))
        result = self.run_cli("--index", "--catalog", "--settle-seconds", "0.01")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_readable_and_json_outputs_preserve_catalog(self):
        self.create_production_fixture()
        path = self.workspace / "L4D2ModDatabase/catalog.sqlite3"
        before = path.read_bytes()
        readable = self.run_cli("--conflicts")
        self.assertEqual(readable.returncode, 0, readable.stderr)
        self.assertIn("potential resource conflicts", readable.stdout)
        self.assertIn("not proof", readable.stdout)
        structured = self.run_cli("--conflicts", "--json")
        self.assertEqual(structured.returncode, 0, structured.stderr)
        result = json.loads(structured.stdout)
        self.assertEqual(result["counts"]["current_package_pairs"], 1)
        self.assertEqual(result["coverage"]["live_verification"], "not_performed")
        self.assertEqual(path.read_bytes(), before)

    def test_missing_catalog_creates_no_directory_or_fallback(self):
        result = self.run_cli("--conflicts", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], "CONFLICT_ANALYSIS_FAILED")
        self.assertFalse((self.workspace / "L4D2ModDatabase").exists())

    def test_incomplete_coverage_json_exit_one(self):
        self.create_production_fixture()
        with closing(sqlite3.connect(self.workspace / "L4D2ModDatabase/catalog.sqlite3")) as connection:
            connection.execute("UPDATE packages SET index_status='error'"); connection.commit()
        result = self.run_cli("--conflicts", "--include-retained", "--json")
        self.assertEqual(result.returncode, 1)
        parsed = json.loads(result.stdout)
        self.assertFalse(parsed["coverage"]["complete"])
        self.assertEqual(parsed["counts"]["retained_package_pairs"], 1)

    def test_invalid_flag_combinations_fail_before_storage(self):
        for args in (("--json",), ("--include-retained",), ("--conflicts", "--catalog"), ("--conflicts", "--index")):
            with self.subTest(args=args): self.assertEqual(self.run_cli(*args).returncode, 2)

    def test_analysis_never_enumerates_workshop_or_opens_game_contents(self):
        from contextlib import redirect_stdout
        import io
        from l4d2_mod_db.cli import main
        self.create_production_fixture()
        with patch.dict(os.environ, LOCALAPPDATA=str(self.workspace)), patch("l4d2_mod_db.security.os.scandir", side_effect=AssertionError("No discovery")), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--game-root", str(self.game), "--conflicts"]), 0)
