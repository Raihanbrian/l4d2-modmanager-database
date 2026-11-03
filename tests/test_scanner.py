from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from l4d2_mod_db.scanner import discover, infer_workshop_id
from l4d2_mod_db.security import DiscoveryStatus, ScopedWorkshopAccess

from .helpers import FakeScandir, FixtureTestCase


class DiscoveryTests(FixtureTestCase):
    def test_deterministic_discovery_numeric_ids_and_same_stem_previews(self):
        for filename in ("zombie.vpk", "456.VPK", "123.vpk", "123.JPG", "zombie.jpg", "orphan.jpg"):
            self.put(f"left4dead2/addons/workshop/{filename}")
        first = discover(ScopedWorkshopAccess(self.game))
        second = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(first, second)
        self.assertEqual(first.status, DiscoveryStatus.COMPLETE)
        self.assertEqual([item.file.filename for item in first.packages], ["123.vpk", "456.VPK", "zombie.vpk"])
        self.assertEqual([item.workshop_id for item in first.packages], ["123", "456", None])
        self.assertEqual(first.packages[0].preview.filename, "123.JPG")
        self.assertIsNone(first.packages[1].preview)
        self.assertEqual(first.packages[2].preview.filename, "zombie.jpg")
        self.assertEqual(len(first.previews), 3)
        self.assertEqual(first.packages[0].file.relative_path, "left4dead2/addons/workshop/123.vpk")

    def test_empty_workshop_is_successfully_empty(self):
        report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.COMPLETE)
        self.assertFalse(report.packages)
        self.assertFalse(report.diagnostics)

    def test_missing_workshop_is_explicit_and_does_not_scan_elsewhere(self):
        self.workshop.rmdir()
        with patch("l4d2_mod_db.security.os.scandir", side_effect=AssertionError("No fallback scanning")):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.MISSING)
        self.assertEqual(report.diagnostics[0].code, "WORKSHOP_MISSING")
        self.assertFalse(self.workshop.exists())

    def test_workshop_as_regular_file_is_rejected(self):
        self.workshop.rmdir()
        self.workshop.write_bytes(b"not a directory")
        report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.REJECTED)
        self.assertFalse(report.packages)

    def test_only_allowed_extensions_and_no_recursion_or_manual_packages(self):
        for relative in ("left4dead2/addons/manual.vpk", "left4dead2/addons/workshop/nested/deep.vpk",
                         "left4dead2/addons/workshop/123.vpk.bak", "left4dead2/addons/workshop/123.jpeg",
                         "left4dead2/addons/workshop/123.png", "left4dead2/addons/workshop/123.txt"):
            self.put(relative)
        self.put("left4dead2/addons/workshop/123.vpk")
        report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.COMPLETE)
        self.assertEqual([item.workshop_id for item in report.packages], ["123"])
        self.assertFalse(report.previews)

    def test_directory_with_vpk_extension_is_rejected_without_recursion(self):
        directory = self.workshop / "123.vpk"
        directory.mkdir()
        (directory / "456.vpk").write_bytes(b"nested")
        report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.PARTIAL)
        self.assertFalse(report.packages)
        self.assertEqual(report.diagnostics[0].code, "NOT_REGULAR_FILE")

    def test_workshop_ids_use_only_exact_ascii_numeric_stems(self):
        expected = {"123.vpk": "123", "000123.VPK": "000123", "123_dir.vpk": None,
                    "123_000.vpk": None, "name.vpk": None, "-123.vpk": None, "+123.vpk": None,
                    "١٢٣.vpk": None, "１２３.vpk": None, ".vpk": None, "123.jpg": None, "123": None}
        for filename, workshop_id in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(infer_workshop_id(filename), workshop_id)

    def test_identical_filenames_in_separate_selected_roots_are_independent(self):
        self.put("left4dead2/addons/workshop/123.vpk", b"one")
        other = self.make_game("other-game")
        (other / "left4dead2/addons/workshop/123.vpk").write_bytes(b"different size")
        first = discover(ScopedWorkshopAccess(self.game))
        second = discover(ScopedWorkshopAccess(other))
        self.assertEqual(first.packages[0].workshop_id, second.packages[0].workshop_id)
        self.assertNotEqual(first.packages[0].file.size_bytes, second.packages[0].file.size_bytes)


class FailureAndRaceTests(FixtureTestCase):
    def test_inaccessible_directory_is_unavailable_not_empty_success(self):
        with patch("l4d2_mod_db.security.os.scandir", side_effect=PermissionError("sensitive path")):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.UNAVAILABLE)
        self.assertEqual(report.diagnostics[0].code, "ENUMERATION_FAILED")
        self.assertNotIn("sensitive", str(report))

    def test_mid_enumeration_failure_returns_explicit_partial_results(self):
        self.put("left4dead2/addons/workshop/123.vpk")
        with patch("l4d2_mod_db.security.os.scandir", return_value=FakeScandir(["123.vpk"], fail_after=True)):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.PARTIAL)
        self.assertEqual(len(report.packages), 1)
        self.assertEqual(report.diagnostics[0].code, "ENUMERATION_FAILED")

    def test_duplicate_enumeration_does_not_double_count_or_pick_a_winner(self):
        self.put("left4dead2/addons/workshop/123.vpk")
        with patch("l4d2_mod_db.security.os.scandir", return_value=FakeScandir(["123.vpk", "123.vpk"])):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertFalse(report.packages)
        self.assertEqual(report.status, DiscoveryStatus.PARTIAL)
        self.assertEqual(report.diagnostics[0].code, "DUPLICATE_NAME")

    def test_case_collisions_do_not_choose_arbitrary_preview(self):
        self.put("left4dead2/addons/workshop/123.vpk")
        self.put("left4dead2/addons/workshop/123.jpg")
        with patch("l4d2_mod_db.security.os.scandir", return_value=FakeScandir(["123.vpk", "123.jpg", "123.JPG"])):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(len(report.packages), 1)
        self.assertIsNone(report.packages[0].preview)
        self.assertFalse(report.previews)
        self.assertEqual(report.status, DiscoveryStatus.PARTIAL)

    def test_file_removed_after_enumeration_is_reported(self):
        with patch("l4d2_mod_db.security.os.scandir", return_value=FakeScandir(["gone.vpk"])):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.PARTIAL)
        self.assertFalse(report.packages)
        self.assertEqual(report.diagnostics[0].code, "FILE_UNAVAILABLE")

    def test_unreadable_candidate_metadata_is_reported(self):
        candidate = self.put("left4dead2/addons/workshop/123.vpk")
        original = Path.lstat
        def denied(path, *args, **kwargs):
            if path == candidate:
                raise PermissionError("private path")
            return original(path, *args, **kwargs)
        with patch.object(Path, "lstat", denied):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.PARTIAL)
        self.assertFalse(report.packages)
        self.assertEqual(report.diagnostics[0].code, "FILE_UNAVAILABLE")

    def test_file_modified_between_metadata_observations_is_skipped(self):
        candidate = self.put("left4dead2/addons/workshop/123.vpk", b"before")
        original = ScopedWorkshopAccess._inspect_file
        calls = 0
        def changed(access, filename):
            nonlocal calls
            calls += 1
            if calls == 2:
                candidate.write_bytes(b"synthetic concurrent writer after enumeration")
            return original(access, filename)
        with patch.object(ScopedWorkshopAccess, "_inspect_file", changed):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.PARTIAL)
        self.assertFalse(report.packages)
        self.assertEqual(report.diagnostics[0].code, "FILE_CHANGED")

    def test_file_removed_between_observations_is_skipped(self):
        candidate = self.put("left4dead2/addons/workshop/123.vpk")
        original = ScopedWorkshopAccess._inspect_file
        calls = 0
        def removed(access, filename):
            nonlocal calls
            calls += 1
            if calls == 2:
                candidate.unlink()
            return original(access, filename)
        with patch.object(ScopedWorkshopAccess, "_inspect_file", removed):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertFalse(report.packages)
        self.assertEqual(report.diagnostics[0].code, "FILE_UNAVAILABLE")

    def test_directory_replaced_during_enumeration_discards_results(self):
        self.put("left4dead2/addons/workshop/123.vpk")
        real_scandir = os.scandir
        renamed = self.workshop.with_name("previous-workshop")
        def swapped(path):
            self.workshop.rename(renamed)
            self.workshop.mkdir()
            return real_scandir(path)
        with patch("l4d2_mod_db.security.os.scandir", swapped):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.UNAVAILABLE)
        self.assertFalse(report.packages)

    def test_base_directory_removed_after_validation_is_not_missing_workshop(self):
        access = ScopedWorkshopAccess(self.game)
        self.workshop.rmdir()
        self.workshop.parent.rmdir()
        report = discover(access)
        self.assertEqual(report.status, DiscoveryStatus.UNAVAILABLE)
        self.assertFalse(report.packages)

    def test_traversal_entry_from_corrupt_enumeration_is_never_inspected(self):
        with patch("l4d2_mod_db.security.os.scandir", return_value=FakeScandir(["../outside.vpk"])):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.PARTIAL)
        self.assertFalse(report.packages)
        self.assertEqual(report.diagnostics[0].code, "UNSAFE_FILENAME")
