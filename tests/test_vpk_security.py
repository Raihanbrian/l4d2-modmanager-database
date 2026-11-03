from contextlib import ExitStack
from dataclasses import replace
import io
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from l4d2_mod_db import security
from l4d2_mod_db.monitor import index_package
from l4d2_mod_db.scanner import discover
from l4d2_mod_db.security import FileReference, PathPolicyError, ScopedWorkshopAccess
from l4d2_mod_db.vpk import ParserLimits
from .helpers import FixtureTestCase
from .vpk_fixtures import build_vpk


class VpkContentBoundaryTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.data = build_vpk()
        self.candidate = self.put("left4dead2/addons/workshop/123.vpk", self.data)
        self.access = ScopedWorkshopAccess(self.game)
        self.package = discover(self.access).packages[0]

    def test_opened_handle_is_read_only_and_matches_reference(self):
        with self.access.open_vpk(self.package.file) as stream:
            self.assertTrue(stream.readable())
            self.assertFalse(stream.writable())
            with self.assertRaises(io.UnsupportedOperation):
                stream.write(b"never")
            with self.assertRaises(OSError):
                os.write(stream.fileno(), b"never")
            self.assertEqual(stream.read(12), self.data[:12])
        self.assertTrue(stream.closed)
        self.assertEqual(self.candidate.read_bytes(), self.data)

    def test_forged_paths_and_jpgs_are_refused_before_open(self):
        jpg = self.put("left4dead2/addons/workshop/123.jpg")
        references = (
            replace(self.package.file, filename="../outside.vpk"),
            replace(self.package.file, relative_path="left4dead2/base.vpk"),
            replace(self.package.file, filename="123.vpk:stream"),
            FileReference(jpg.name, "left4dead2/addons/workshop/123.jpg", jpg.stat().st_size, jpg.stat().st_mtime_ns),
        )
        for reference in references:
            with self.subTest(reference=reference):
                with patch("l4d2_mod_db.security._open_readonly", side_effect=AssertionError("Do not open")):
                    with self.assertRaises(PathPolicyError):
                        with self.access.open_vpk(reference):
                            self.fail("Unsafe reference was exposed")

    def test_discovery_to_open_change_is_rejected_before_open(self):
        self.candidate.write_bytes(build_vpk(("scripts/changed.txt",)))
        with patch("l4d2_mod_db.security._open_readonly", side_effect=AssertionError("Stale reference")):
            with self.assertRaises(PathPolicyError) as caught:
                with self.access.open_vpk(self.package.file):
                    pass
        self.assertEqual(caught.exception.code, "FILE_CHANGED")

    def test_wrong_descriptor_is_rejected_before_any_content_is_exposed(self):
        outside = self.workspace / "outside.vpk"
        outside.write_bytes(self.data)
        real_open = security._open_readonly
        with patch("l4d2_mod_db.security._open_readonly", side_effect=lambda path: real_open(outside)):
            with self.assertRaises(PathPolicyError) as caught:
                with self.access.open_vpk(self.package.file):
                    self.fail("Mismatching descriptor was exposed")
        self.assertEqual(caught.exception.code, "FILE_CHANGED")

    def test_write_during_open_discards_result(self):
        with self.assertRaises(PathPolicyError) as caught:
            with self.access.open_vpk(self.package.file) as stream:
                stream.read(12)
                self.candidate.write_bytes(self.data + b"concurrent writer")
        self.assertEqual(caught.exception.code, "FILE_CHANGED")

    def test_directory_swap_before_content_exposure_is_rejected(self):
        real_open = security._open_readonly
        def swap(path):
            self.workshop.rename(self.workshop.with_name("old-workshop"))
            self.workshop.mkdir()
            self.candidate.write_bytes(self.data)
            return real_open(path)
        with patch("l4d2_mod_db.security._open_readonly", swap):
            with self.assertRaises(PathPolicyError):
                with self.access.open_vpk(self.package.file):
                    self.fail("Directory swap was not rejected")

    def test_hardlink_metadata_is_refused_before_open(self):
        original = Path.lstat
        def linked(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == self.candidate:
                fields = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}
                fields["st_nlink"] = 2
                return SimpleNamespace(**fields)
            return info
        with patch.object(Path, "lstat", linked):
            with patch("l4d2_mod_db.security._open_readonly", side_effect=AssertionError("No hardlink reads")):
                with self.assertRaises(PathPolicyError) as caught:
                    with self.access.open_vpk(self.package.file):
                        pass
        self.assertEqual(caught.exception.code, "HARDLINK")

    def test_indexing_uses_only_one_vpk_read_and_never_mutates_fixture(self):
        self.put("left4dead2/addons/workshop/123.jpg")
        self.put("left4dead2/addonlist.txt", b"do not read")
        def snapshot():
            return {str(path.relative_to(self.game)): (path.stat().st_mtime_ns, path.stat().st_mode, path.read_bytes() if path.is_file() else None)
                    for path in [self.game, *self.game.rglob("*")]}
        before = snapshot()
        real_open = security._open_readonly
        opened = []
        def guarded(path):
            self.assertEqual(path, self.candidate)
            opened.append(path)
            return real_open(path)
        with ExitStack() as stack:
            for api in ("builtins.open", "os.mkdir", "os.makedirs", "os.remove", "os.unlink", "os.rename", "os.replace",
                        "os.rmdir", "os.chmod", "os.utime", "os.link", "os.symlink"):
                stack.enter_context(patch(api, side_effect=AssertionError(f"No runtime {api}")))
            stack.enter_context(patch("l4d2_mod_db.security._open_readonly", guarded))
            index = index_package(self.access, self.package, ParserLimits())
        self.assertEqual(len(index.assets), 1)
        self.assertEqual(opened, [self.candidate])
        self.assertEqual(snapshot(), before)
