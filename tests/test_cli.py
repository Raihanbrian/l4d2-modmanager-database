from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import os
import subprocess
import sys
from unittest.mock import patch

from l4d2_mod_db.cli import main

from .helpers import FixtureTestCase, PROJECT_ROOT


class CliTests(FixtureTestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                exit_code = main(arguments)
            except SystemExit as exit:
                exit_code = exit.code
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_explicit_root_is_required_without_searching(self):
        with patch("l4d2_mod_db.security.os.scandir", side_effect=AssertionError("No implicit search")):
            code, out, err = self.invoke([])
        self.assertEqual(code, 2)
        self.assertFalse(out)
        self.assertIn("--game-root", err)

    def test_report_has_filenames_relative_locations_ids_previews_and_counts(self):
        for name in ("123.vpk", "123.JPG", "custom.vpk", "orphan.jpg"):
            self.put(f"left4dead2/addons/workshop/{name}")
        code, out, err = self.invoke(["--game-root", str(self.game)])
        self.assertEqual(code, 0)
        self.assertFalse(err)
        self.assertIn('VPK: "123.vpk"', out)
        self.assertIn('Relative path: "left4dead2/addons/workshop/123.vpk"', out)
        self.assertIn("Workshop ID (inferred): 123", out)
        self.assertIn("Workshop ID (inferred): Unknown", out)
        self.assertIn('Matching JPG: "left4dead2/addons/workshop/123.JPG"', out)
        self.assertIn("Matching JPG: None safely discovered", out)
        self.assertIn('Unmatched JPG: "left4dead2/addons/workshop/orphan.jpg"', out)
        self.assertIn("2 VPK(s), 2 JPG(s); 1 package(s)", out)
        self.assertNotIn(str(self.workspace), out)
        self.assertEqual((code, out, err), self.invoke(["--game-root", str(self.game)]))

    def test_missing_workshop_is_success_with_explicit_diagnostic(self):
        self.workshop.rmdir()
        code, out, err = self.invoke(["--game-root", str(self.game)])
        self.assertEqual(code, 0)
        self.assertIn("0 Workshop mods / folder not found", out)
        self.assertIn("WORKSHOP_MISSING", out)
        self.assertFalse(err)

    def test_empty_workshop_is_distinct_from_missing(self):
        code, out, err = self.invoke(["--game-root", str(self.game)])
        self.assertEqual(code, 0)
        self.assertIn("Status: complete", out)
        self.assertIn("0 VPK(s), 0 JPG(s)", out)
        self.assertNotIn("WORKSHOP_MISSING", out)

    def test_invalid_root_returns_safe_error_and_exit_2(self):
        code, out, err = self.invoke(["--game-root", str(self.workspace)])
        self.assertEqual(code, 2)
        self.assertFalse(out)
        self.assertIn("INVALID_STRUCTURE", err)
        self.assertNotIn(str(self.workspace), err)

    def test_inaccessible_workshop_returns_exit_1_and_incomplete_warning(self):
        with patch("l4d2_mod_db.security.os.scandir", side_effect=PermissionError("private details")):
            code, out, err = self.invoke(["--game-root", str(self.game)])
        self.assertEqual(code, 1)
        self.assertIn("Status: unavailable", out)
        self.assertIn("Incomplete discovery", out)
        self.assertIn("ENUMERATION_FAILED", out)
        self.assertNotIn("private details", out + err)

    def test_rejected_workshop_returns_exit_1(self):
        self.workshop.rmdir()
        self.workshop.write_bytes(b"not a folder")
        code, out, err = self.invoke(["--game-root", str(self.game)])
        self.assertEqual(code, 1)
        self.assertIn("Status: rejected", out)

    def test_partial_discovery_returns_exit_1(self):
        (self.workshop / "123.vpk").mkdir()
        code, out, err = self.invoke(["--game-root", str(self.game)])
        self.assertEqual(code, 1)
        self.assertIn("Status: partial", out)

    def test_help_and_version_do_not_need_a_root(self):
        for arguments, expected in ((["--help"], "--game-root"), (["--version"], "0.1.0")):
            with self.subTest(arguments=arguments):
                with patch("l4d2_mod_db.security.os.scandir", side_effect=AssertionError("No scanning")):
                    code, out, err = self.invoke(arguments)
                self.assertEqual(code, 0)
                self.assertIn(expected, out)

    def test_module_entrypoint_in_subprocess(self):
        self.put("left4dead2/addons/workshop/765.vpk", b"opaque bytes, no parser")
        result = subprocess.run(
            [sys.executable, "-B", "-m", "l4d2_mod_db", "--game-root", str(self.game)],
            cwd=PROJECT_ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Workshop ID (inferred): 765", result.stdout)
        self.assertIn("Accepted candidates: 1 VPK(s), 0 JPG(s)", result.stdout)
