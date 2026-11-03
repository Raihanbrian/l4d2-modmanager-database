from dataclasses import replace
import math
from unittest.mock import patch

from l4d2_mod_db.monitor import PackageStatus, WorkshopMonitor, watch
from l4d2_mod_db.scanner import discover
from l4d2_mod_db.security import DiscoveryStatus, ScopedWorkshopAccess
from l4d2_mod_db.vpk import VpkError
from .helpers import FixtureTestCase
from .vpk_fixtures import build_vpk


class MonitorTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.now = 0.0
        self.access = ScopedWorkshopAccess(self.game)
        self.monitor = WorkshopMonitor(self.access, settle_seconds=1, retry_seconds=3, clock=lambda: self.now)

    def put_vpk(self, name="123.vpk", paths=("scripts/fixture.txt",)):
        return self.put(f"left4dead2/addons/workshop/{name}", build_vpk(paths))

    def tick(self, seconds=1):
        self.now += seconds
        return self.monitor.poll()

    def indexed(self):
        self.put_vpk()
        self.monitor.poll()
        result = self.tick()
        self.assertTrue(result.ready)
        return result

    def test_startup_waits_for_two_observations_spanning_settle_interval(self):
        self.put_vpk()
        first = self.monitor.poll()
        self.assertEqual(first.records[0].status, PackageStatus.PENDING)
        self.assertEqual(first.parse_attempts, 0)
        self.assertEqual(self.tick(0.5).parse_attempts, 0)
        result = self.tick(0.5)
        self.assertEqual(result.parse_attempts, 1)
        self.assertTrue(result.ready)

    def test_unchanged_packages_are_cached_without_reopening_content(self):
        before = self.indexed()
        with patch("l4d2_mod_db.monitor.index_package", side_effect=AssertionError("Use cache")):
            result = self.tick(10)
        self.assertEqual(result.parse_attempts, 1)
        self.assertIs(result.records[0].index, before.records[0].index)
        self.assertFalse(result.events)

    def test_new_addition_is_indexed_automatically(self):
        self.indexed()
        self.put_vpk("456.vpk", ("models/new.mdl",))
        self.assertEqual(self.tick().records[1].status, PackageStatus.PENDING)
        result = self.tick()
        self.assertEqual(len(result.records), 2)
        self.assertTrue(result.ready)
        self.assertEqual(result.parse_attempts, 2)

    def test_modification_keeps_stale_index_until_stable_then_replaces_it(self):
        before = self.indexed()
        self.put_vpk(paths=("scripts/updated.txt", "materials/new.vmt"))
        pending = self.tick()
        self.assertTrue(pending.records[0].stale)
        self.assertIs(pending.records[0].index, before.records[0].index)
        result = self.tick()
        self.assertEqual(len(result.records[0].index.assets), 2)
        self.assertFalse(result.records[0].stale)
        self.assertIn("updated", [event.kind for event in result.events])

    def test_repeated_writes_reset_stability_and_are_not_parsed_mid_write(self):
        self.put_vpk()
        self.monitor.poll()
        self.put_vpk(paths=("scripts/first-write.txt",))
        self.assertEqual(self.tick(0.8).parse_attempts, 0)
        self.put_vpk(paths=("scripts/second-write.txt",))
        self.assertEqual(self.tick(0.8).parse_attempts, 0)
        self.assertEqual(self.tick(0.8).parse_attempts, 0)
        self.assertEqual(self.tick(0.3).parse_attempts, 1)

    def test_removal_requires_two_complete_scans_and_settle_interval(self):
        self.indexed()
        (self.workshop / "123.vpk").unlink()
        pending = self.tick()
        self.assertEqual(pending.records[0].status, PackageStatus.MISSING_PENDING)
        self.assertTrue(pending.records[0].stale)
        result = self.tick()
        self.assertFalse(result.records)
        self.assertIn("removed", [event.kind for event in result.events])

    def test_temporary_disappearance_does_not_remove_the_record(self):
        before = self.indexed()
        candidate = self.workshop / "123.vpk"
        parked = self.workspace / "parked.vpk"
        candidate.rename(parked)
        self.assertEqual(self.tick().records[0].status, PackageStatus.MISSING_PENDING)
        parked.rename(candidate)
        self.assertEqual(self.tick(0.5).records[0].status, PackageStatus.PENDING)
        result = self.tick()
        self.assertEqual(len(result.records), 1)
        self.assertTrue(result.ready)
        self.assertEqual(result.records[0].index.index_sha256, before.records[0].index.index_sha256)

    def test_inaccessible_folder_retains_data_and_recovers_after_settling(self):
        before = self.indexed()
        with patch("l4d2_mod_db.security.os.scandir", side_effect=PermissionError("private path")):
            failed = self.tick(100)
        self.assertEqual(failed.discovery_status, DiscoveryStatus.UNAVAILABLE)
        self.assertTrue(failed.records[0].stale)
        self.assertIs(failed.records[0].index, before.records[0].index)
        self.assertFalse(failed.ready)
        self.assertEqual(self.tick().records[0].status, PackageStatus.PENDING)
        result = self.tick()
        self.assertTrue(result.ready)
        self.assertEqual(result.parse_attempts, 1)

    def test_missing_workshop_directory_is_outage_not_mass_removal(self):
        before = self.indexed()
        parked = self.workshop.with_name("offline-workshop")
        self.workshop.rename(parked)
        for _ in range(3):
            failed = self.tick(10)
            self.assertEqual(failed.discovery_status, DiscoveryStatus.MISSING)
            self.assertIs(failed.records[0].index, before.records[0].index)
            self.assertFalse(failed.ready)
        parked.rename(self.workshop)
        self.tick()
        self.assertTrue(self.tick().ready)

    def test_rejected_folder_context_retains_previous_data(self):
        before = self.indexed()
        snapshot = discover(self.access)
        with patch("l4d2_mod_db.monitor.discover", return_value=replace(snapshot, status=DiscoveryStatus.REJECTED, packages=())):
            failed = self.tick(100)
        self.assertEqual(len(failed.records), 1)
        self.assertTrue(failed.records[0].stale)
        self.assertIs(failed.records[0].index, before.records[0].index)

    def test_partial_scan_never_confirms_removals_and_resets_absence_timer(self):
        self.indexed()
        (self.workshop / "123.vpk").unlink()
        self.tick()
        snapshot = discover(self.access)
        with patch("l4d2_mod_db.monitor.discover", return_value=replace(snapshot, status=DiscoveryStatus.PARTIAL)):
            self.assertEqual(len(self.tick(100).records), 1)
        pending = self.tick()
        self.assertEqual(pending.records[0].status, PackageStatus.MISSING_PENDING)
        self.assertFalse(self.tick().records)

    def test_parse_failure_preserves_previous_assets_and_retries_with_backoff(self):
        before = self.indexed()
        self.put("left4dead2/addons/workshop/123.vpk", b"not a VPK; temporary partial download")
        self.tick()
        failed = self.tick()
        self.assertEqual(failed.records[0].status, PackageStatus.ERROR)
        self.assertIs(failed.records[0].index, before.records[0].index)
        self.assertTrue(failed.records[0].stale)
        self.assertEqual(failed.parse_attempts, 2)
        self.assertEqual(self.tick().parse_attempts, 2)
        self.assertEqual(self.tick(3).parse_attempts, 3)
        self.put_vpk(paths=("scripts/repaired.txt",))
        self.tick()
        recovered = self.tick()
        self.assertTrue(recovered.ready)
        self.assertEqual(recovered.records[0].index.assets[0].canonical_path, "scripts/repaired.txt")

    def test_new_damaged_file_is_explicit_error_without_fabricated_assets(self):
        self.put("left4dead2/addons/workshop/123.vpk", b"bad")
        self.monitor.poll()
        result = self.tick()
        self.assertEqual(result.records[0].status, PackageStatus.ERROR)
        self.assertIsNone(result.records[0].index)
        self.assertFalse(result.ready)

    def test_temporary_content_access_failure_retains_and_retries_index(self):
        before = self.indexed()
        self.put_vpk(paths=("scripts/new-version.txt",))
        self.tick()
        with patch("l4d2_mod_db.monitor.index_package", side_effect=PermissionError("private location")):
            failed = self.tick()
        self.assertEqual(failed.records[0].diagnostic.code, "VPK_UNAVAILABLE")
        self.assertNotIn("private", str(failed.records[0].diagnostic))
        self.assertIs(failed.records[0].index, before.records[0].index)
        recovered = self.tick(3)
        self.assertTrue(recovered.ready)

    def test_file_changed_during_indexing_does_not_replace_valid_index(self):
        before = self.indexed()
        self.put_vpk(paths=("scripts/new-version.txt",))
        self.tick()
        with patch("l4d2_mod_db.monitor.index_package", side_effect=VpkError("FILE_CHANGED", "Injected concurrent change")):
            failed = self.tick()
        self.assertIs(failed.records[0].index, before.records[0].index)
        self.assertEqual(failed.records[0].status, PackageStatus.ERROR)

    def test_preview_arrivals_and_modifications_do_not_reparse_unchanged_vpk(self):
        self.indexed()
        self.put("left4dead2/addons/workshop/123.jpg", b"preview1")
        result = self.tick()
        self.assertIsNotNone(result.records[0].package.preview)
        self.assertEqual(result.parse_attempts, 1)
        self.put("left4dead2/addons/workshop/123.jpg", b"preview changed")
        self.assertEqual(self.tick().parse_attempts, 1)
        (self.workshop / "123.jpg").unlink()
        self.assertIsNone(self.tick().records[0].package.preview)

    def test_startup_reconstructs_current_collection_after_closed_changes(self):
        self.indexed()
        (self.workshop / "123.vpk").unlink()
        self.put_vpk("456.vpk")
        restarted = WorkshopMonitor(self.access, settle_seconds=1, clock=lambda: self.now)
        restarted.poll()
        self.now += 1
        result = restarted.poll()
        self.assertEqual([record.package.file.filename for record in result.records], ["456.vpk"])
        self.assertTrue(result.ready)

    def test_collection_asset_budget_preserves_previously_valid_index(self):
        self.monitor.max_total_assets = 1
        before = self.indexed()
        self.put_vpk(paths=("scripts/a.txt", "scripts/b.txt"))
        self.tick()
        failed = self.tick()
        self.assertEqual(failed.records[0].diagnostic.code, "COLLECTION_LIMIT")
        self.assertIs(failed.records[0].index, before.records[0].index)

    def test_watch_loop_uses_periodic_reconciliation_and_bounded_cycles(self):
        self.put_vpk()
        def sleep(seconds):
            self.now += seconds
            if self.now == 2:
                self.put_vpk("456.vpk")
        reports = list(watch(self.monitor, interval=1, cycles=4, sleep=sleep))
        self.assertEqual(len(reports), 4)
        self.assertEqual(len(reports[-1].records), 2)
        self.assertTrue(reports[-1].ready)
        self.assertEqual(reports[-1].parse_attempts, 2)

    def test_observed_65_to_71_scenario_has_eight_arrivals_and_two_removals(self):
        # These IDs are artificial; the owner did not supply the real changed IDs.
        for number in range(1000, 1065):
            self.put_vpk(f"{number}.vpk")
            if number < 1064:
                self.put(f"left4dead2/addons/workshop/{number}.jpg")
        self.monitor.poll()
        baseline = self.tick()
        self.assertEqual(len(baseline.records), 65)
        self.assertEqual(sum(record.package.preview is not None for record in baseline.records), 64)
        for number in (1000, 1001):
            (self.workshop / f"{number}.vpk").unlink()
            (self.workshop / f"{number}.jpg").unlink()
        for number in range(2000, 2008):
            self.put_vpk(f"{number}.vpk")
            self.put(f"left4dead2/addons/workshop/{number}.jpg")
        self.put("left4dead2/addons/workshop/1064.jpg")
        self.tick()
        after = self.tick()
        self.assertEqual(len(after.records), 71)
        self.assertEqual(sum(record.package.preview is not None for record in after.records), 71)
        self.assertEqual(sum(event.kind == "indexed" for event in after.events), 8)
        self.assertEqual(sum(event.kind == "removed" for event in after.events), 2)
        self.assertEqual(after.parse_attempts, 73)  # 65 initial + 8 new; 63 cached.
        self.assertTrue(after.ready)

    def test_invalid_monitor_and_watcher_configuration_is_rejected(self):
        for value in (0, -1, math.nan, math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    WorkshopMonitor(self.access, settle_seconds=value)
                with self.assertRaises(ValueError):
                    list(watch(self.monitor, interval=value, cycles=1))
        with self.assertRaises(ValueError):
            list(watch(self.monitor, cycles=0))
