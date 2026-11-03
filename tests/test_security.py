from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from l4d2_mod_db.scanner import discover
from l4d2_mod_db.security import (
    DiscoveryStatus, PathPolicyError, ScopedWorkshopAccess, validate_workshop_filename,
)

from .helpers import FixtureTestCase


class RootPolicyTests(FixtureTestCase):
    def test_valid_structure_is_plausible_without_reading_game_files(self):
        with patch("builtins.open", side_effect=AssertionError("No content reads")):
            access = ScopedWorkshopAccess(self.game)
            self.assertEqual(access.list_workshop_files().status, DiscoveryStatus.COMPLETE)

    def test_unrelated_directory_is_rejected_without_search(self):
        unrelated = self.workspace / "unrelated"
        unrelated.mkdir()
        with patch("l4d2_mod_db.security.os.scandir", side_effect=AssertionError("No searching")):
            with self.assertRaisesRegex(PathPolicyError, "left4dead2/addons"):
                ScopedWorkshopAccess(unrelated)

    def test_install_name_alone_is_not_validation(self):
        named_like_game = self.workspace / "Left 4 Dead 2"
        named_like_game.mkdir()
        with self.assertRaises(PathPolicyError):
            ScopedWorkshopAccess(named_like_game)

    def test_missing_root_is_rejected(self):
        with self.assertRaises(PathPolicyError):
            ScopedWorkshopAccess(self.workspace / "absent")

    def test_file_as_root_is_rejected(self):
        file = self.workspace / "file"
        file.write_bytes(b"not a directory")
        with self.assertRaises(PathPolicyError) as caught:
            ScopedWorkshopAccess(file)
        self.assertEqual(caught.exception.code, "NOT_DIRECTORY")

    def test_relative_traversal_network_and_device_roots_are_rejected(self):
        for root in ("", ".", "relative/game", "../game", self.game / ".." / "game",
                     "C:game", "\\\\server\\share", "\\\\?\\C:\\game", "\\\\.\\C:\\game", "//server/share", "bad\x00root"):
            with self.subTest(root=str(root)):
                with self.assertRaises(PathPolicyError) as caught:
                    ScopedWorkshopAccess(root)
                self.assertEqual(caught.exception.code, "INVALID_ROOT")

    def test_expected_addons_directory_must_be_directory(self):
        self.workshop.rmdir()
        addons = self.workshop.parent
        addons.rmdir()
        addons.write_bytes(b"not a directory")
        with self.assertRaises(PathPolicyError) as caught:
            ScopedWorkshopAccess(self.game)
        self.assertEqual(caught.exception.code, "NOT_DIRECTORY")

    def test_permission_failure_has_safe_root_diagnostic(self):
        original = Path.lstat
        def denied(path, *args, **kwargs):
            if path == self.game / "left4dead2":
                raise PermissionError("sensitive path that must not be printed")
            return original(path, *args, **kwargs)
        with patch.object(Path, "lstat", denied):
            with self.assertRaises(PathPolicyError) as caught:
                ScopedWorkshopAccess(self.game)
        self.assertEqual(caught.exception.code, "INVALID_STRUCTURE")
        self.assertNotIn("sensitive", str(caught.exception))


class FilenamePolicyTests(FixtureTestCase):
    def test_only_direct_vpk_or_jpg_names_are_accepted(self):
        for filename in ("123.vpk", "named mod.VPK", "123.JPG", ".vpk", "no-id.jpg"):
            with self.subTest(filename=filename):
                validate_workshop_filename(filename)

    def test_path_injection_traversal_ads_and_reserved_names_are_rejected(self):
        names = ("../evil.vpk", "..\\evil.vpk", "/evil.vpk", "C:\\evil.vpk", "C:evil.vpk",
                 "workshop/evil.vpk", "workshop\\evil.vpk", "\\\\server\\evil.vpk", "",
                 ".", "..", "123.vpk:secret", "123:stream.vpk", "123.vpk ", "123.vpk.",
                 "*.vpk", "?.jpg", "bad\nname.vpk", "bad\x00name.vpk", "NUL.vpk", "COM1.jpg",
                 "lpt¹.vpk", "CONOUT$.vpk", "NUL .vpk", "COM1 .jpg", str(self.workshop / "absolute.vpk"))
        for filename in names:
            with self.subTest(filename=filename):
                with self.assertRaises(PathPolicyError):
                    validate_workshop_filename(filename)

    def test_disallowed_extensions_are_rejected(self):
        for filename in ("addonlist.txt", "123.png", "123.vpk.bak", "123.jpeg", "123", "123.zip"):
            with self.subTest(filename=filename):
                with self.assertRaises(PathPolicyError) as caught:
                    validate_workshop_filename(filename)
                self.assertEqual(caught.exception.code, "OUT_OF_SCOPE")


class EscapeTests(FixtureTestCase):
    def test_symlink_mode_is_rejected_without_resolving_target(self):
        candidate = self.put("left4dead2/addons/workshop/123.vpk")
        original = Path.lstat
        def symlink(path, *args, **kwargs):
            if path == candidate:
                return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0)
            return original(path, *args, **kwargs)
        with patch.object(Path, "lstat", symlink):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertFalse(report.packages)
        self.assertEqual(report.diagnostics[0].code, "REPARSE_POINT")

    def test_mocked_root_ancestor_reparse_is_rejected_before_enumeration(self):
        original = Path.lstat
        def reparse(path, *args, **kwargs):
            if path == self.game.parent:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0x400)
            return original(path, *args, **kwargs)
        with patch.object(Path, "lstat", reparse):
            with patch("l4d2_mod_db.security.os.scandir", side_effect=AssertionError("No enumeration")):
                with self.assertRaises(PathPolicyError) as caught:
                    ScopedWorkshopAccess(self.game)
        self.assertEqual(caught.exception.code, "REPARSE_POINT")

    def test_mocked_workshop_reparse_is_not_enumerated(self):
        original = Path.lstat
        def reparse(path, *args, **kwargs):
            if path == self.workshop:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0x400)
            return original(path, *args, **kwargs)
        with patch.object(Path, "lstat", reparse):
            with patch("l4d2_mod_db.security.os.scandir", side_effect=AssertionError("No enumeration")):
                report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.REJECTED)
        self.assertEqual(report.diagnostics[0].code, "REPARSE_POINT")

    def test_resolved_game_root_prefix_escape_is_rejected_before_enumeration(self):
        access = ScopedWorkshopAccess(self.game)
        original = Path.resolve
        outside = self.workspace / "game Other/left4dead2/addons/workshop"
        def changed_resolution(path, *args, **kwargs):
            return outside if path == self.workshop else original(path, *args, **kwargs)
        with patch.object(Path, "resolve", changed_resolution):
            with patch("l4d2_mod_db.security.os.scandir", side_effect=AssertionError("No prefix escape enumeration")):
                report = discover(access)
        self.assertEqual(report.status, DiscoveryStatus.REJECTED)
        self.assertEqual(report.diagnostics[0].code, "OUTSIDE_ROOT")

    def test_external_file_symlink_is_rejected(self):
        target = self.workspace / "outside.vpk"
        target.write_bytes(b"outside")
        self.symlink_or_skip(self.workshop / "123.vpk", target)
        report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.PARTIAL)
        self.assertFalse(report.packages)
        self.assertIn("REPARSE_POINT", [item.code for item in report.diagnostics])

    def test_inside_root_file_symlink_is_also_rejected(self):
        target = self.put("left4dead2/addons/workshop/123.vpk")
        self.symlink_or_skip(self.workshop / "456.vpk", target)
        report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual([package.file.filename for package in report.packages], ["123.vpk"])
        self.assertEqual(report.status, DiscoveryStatus.PARTIAL)

    def test_workshop_symlink_to_prefix_sibling_is_not_followed(self):
        sibling = self.make_game("game Other") / "left4dead2/addons/workshop"
        (sibling / "outside.vpk").write_bytes(b"outside")
        self.workshop.rmdir()
        self.symlink_or_skip(self.workshop, sibling, directory=True)
        with patch("l4d2_mod_db.security.os.scandir", side_effect=AssertionError("Do not enumerate escaped Workshop")):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(report.status, DiscoveryStatus.REJECTED)
        self.assertFalse(report.packages)

    def test_selected_root_symlink_is_rejected(self):
        link = self.workspace / "selected-link"
        self.symlink_or_skip(link, self.game, directory=True)
        with self.assertRaises(PathPolicyError) as caught:
            ScopedWorkshopAccess(link)
        self.assertEqual(caught.exception.code, "REPARSE_POINT")

    def test_symlink_ancestor_of_selected_root_is_rejected(self):
        link = self.workspace / "ancestor-link"
        self.symlink_or_skip(link, self.workspace, directory=True)
        try:
            with self.assertRaises(PathPolicyError) as caught:
                ScopedWorkshopAccess(link / "game")
            self.assertEqual(caught.exception.code, "REPARSE_POINT")
        finally:
            # This fixture intentionally points back at its ancestor: remove
            # only the link before the temporary workspace's recursive cleanup.
            link.unlink() if os.name != "nt" else link.rmdir()

    def test_resolved_path_prefix_attack_is_rejected(self):
        candidate = self.put("left4dead2/addons/workshop/123.vpk")
        access = ScopedWorkshopAccess(self.game)
        original = Path.resolve
        sibling = self.game / "left4dead2/addons/workshop Other/123.vpk"
        def changed_resolution(path, *args, **kwargs):
            return sibling if path == candidate else original(path, *args, **kwargs)
        with patch.object(Path, "resolve", changed_resolution):
            report = discover(access)
        self.assertFalse(report.packages)
        self.assertEqual(report.diagnostics[0].code, "OUTSIDE_WORKSHOP")

    def test_windows_reparse_attribute_rejects_even_non_symlink_files(self):
        candidate = self.put("left4dead2/addons/workshop/123.vpk")
        original = Path.lstat
        def reparse(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == candidate:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info
        with patch.object(Path, "lstat", reparse):
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertFalse(report.packages)
        self.assertEqual(report.diagnostics[0].code, "REPARSE_POINT")

    def test_real_windows_junction_escape_is_not_enumerated(self):
        if os.name != "nt":
            self.skipTest("Windows junction integration test")
        target = self.workspace / "junction-target"
        target.mkdir()
        (target / "outside.vpk").write_bytes(b"outside")
        self.workshop.rmdir()
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(self.workshop), str(target)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            self.skipTest(f"Synthetic junction creation failed: {result.stderr.strip()}")
        try:
            self.assertTrue(self.workshop.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            with patch("l4d2_mod_db.security.os.scandir", side_effect=AssertionError("No junction enumeration")):
                report = discover(ScopedWorkshopAccess(self.game))
            self.assertEqual(report.status, DiscoveryStatus.REJECTED)
            self.assertFalse(report.packages)
            self.assertEqual((target / "outside.vpk").read_bytes(), b"outside")
        finally:
            # rmdir on the verified junction removes the link, not its target.
            self.assertEqual(self.workshop.parent.resolve(), (self.game / "left4dead2/addons").resolve())
            self.workshop.rmdir()


class ReadOnlyBoundaryTests(FixtureTestCase):
    def test_no_content_opens_or_mutations_and_only_workshop_is_enumerated(self):
        self.put("left4dead2/addons/workshop/123.vpk", b"must remain unchanged")
        self.put("left4dead2/addons/workshop/123.JPG", b"image fixture")
        self.put("left4dead2/addons/manual.vpk", b"manual out of scope")
        self.put("left4dead2/base_dir.vpk", b"base game out of scope")
        self.put("left4dead2/addonlist.txt", b"saved game state out of scope")
        self.put("left4dead2/addons/workshop/ignored.txt", b"ignored")
        self.put("left4dead2/addons/workshop/nested/deep.vpk", b"never recurse")
        def snapshot():
            return {
                str(path.relative_to(self.game)): (path.stat().st_mode, path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
                for path in [self.game, *self.game.rglob("*")]
            }
        before = snapshot()
        original_scandir = os.scandir
        original_lstat = Path.lstat
        enumerated = []
        inspected = []
        def scoped_scandir(path):
            enumerated.append(Path(path))
            self.assertEqual(Path(path), self.workshop)
            return original_scandir(path)
        def tracked_lstat(path, *args, **kwargs):
            inspected.append(path)
            return original_lstat(path, *args, **kwargs)
        with ExitStack() as stack:
            for api in ("builtins.open", "io.open", "os.open", "os.mkdir", "os.makedirs", "os.remove", "os.unlink",
                        "os.rename", "os.replace", "os.rmdir", "os.chmod", "os.utime", "os.link", "os.symlink"):
                stack.enter_context(patch(api, side_effect=AssertionError(f"Runtime must not call {api}")))
            stack.enter_context(patch("l4d2_mod_db.security.os.scandir", scoped_scandir))
            stack.enter_context(patch.object(Path, "lstat", tracked_lstat))
            report = discover(ScopedWorkshopAccess(self.game))
        self.assertEqual(before, snapshot())
        self.assertEqual(enumerated, [self.workshop])
        self.assertEqual([package.file.filename for package in report.packages], ["123.vpk"])
        for forbidden in ("left4dead2/addons/manual.vpk", "left4dead2/base_dir.vpk", "left4dead2/addonlist.txt",
                          "left4dead2/addons/workshop/ignored.txt", "left4dead2/addons/workshop/nested/deep.vpk"):
            self.assertNotIn(self.game / forbidden, inspected)
