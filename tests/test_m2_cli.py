from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import queue
import subprocess
import sys
import threading
from unittest.mock import patch

from l4d2_mod_db.cli import main
from .helpers import FixtureTestCase, PROJECT_ROOT
from .vpk_fixtures import build_vpk


class M2CliTests(FixtureTestCase):
    def invoke(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(["--game-root", str(self.game), *arguments])
            except SystemExit as exit:
                code = exit.code
        return code, out.getvalue(), err.getvalue()

    def test_one_shot_index_and_asset_listing(self):
        self.put("left4dead2/addons/workshop/123.vpk", build_vpk(("Materials/Test.VMT",)))
        code, out, err = self.invoke(["--index", "--list-assets", "--settle-seconds", "0.01"])
        self.assertEqual(code, 0, err)
        self.assertIn("current indexes: 1/1", out)
        self.assertIn('"Materials/Test.VMT" -> "materials/test.vmt"', out)
        self.assertIn("VPK v1", out)
        self.assertNotIn(str(self.workspace), out)

    def test_index_errors_return_one(self):
        self.put("left4dead2/addons/workshop/123.vpk", b"damaged")
        code, out, err = self.invoke(["--index", "--settle-seconds", "0.01"])
        self.assertEqual(code, 1)
        self.assertIn("TRUNCATED_VPK", out)

    def test_non_utf8_paths_are_escaped_and_disclosed(self):
        self.put("left4dead2/addons/workshop/123.vpk", build_vpk().replace(b"scripts", b"script\xff"))
        code, out, err = self.invoke(["--index", "--list-assets", "--settle-seconds", "0.01"])
        self.assertEqual(code, 0)
        self.assertIn("NON_UTF8_PATHS", out)
        self.assertIn("\\udcff", out)
        out.encode("ascii")  # Report is safe on restricted terminal encodings.

    def test_empty_and_missing_workshop_index_without_waiting(self):
        for missing in (False, True):
            if missing:
                self.workshop.rmdir()
            with patch("l4d2_mod_db.cli.time.sleep", side_effect=AssertionError("No file stability wait needed")):
                code, out, err = self.invoke(["--index"])
            self.assertEqual(code, 0)
            self.assertIn("current indexes: 0/0", out)

    def test_invalid_modes_and_intervals_fail_before_scanning(self):
        invalid = (["--list-assets"], ["--cycles", "2"], ["--index", "--watch"],
                   ["--watch", "--list-assets"], ["--watch", "--cycles", "0"],
                   ["--index", "--settle-seconds", "0"], ["--watch", "--poll-interval", "nan"],
                   ["--watch", "--poll-interval", "inf"], ["--watch", "--cycles", "1.5"])
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                with patch("l4d2_mod_db.cli.ScopedWorkshopAccess", side_effect=AssertionError("Reject before filesystem access")):
                    self.assertEqual(self.invoke(arguments)[0], 2)

    def test_bounded_watch_reports_initial_index_then_stays_quiet(self):
        self.put("left4dead2/addons/workshop/123.vpk", build_vpk())
        code, out, err = self.invoke(["--watch", "--cycles", "4", "--poll-interval", "0.02", "--settle-seconds", "0.01"])
        self.assertEqual(code, 0)
        self.assertEqual(out.count("M2 discovery:"), 2)
        self.assertIn("Event indexed:", out)

    def test_ctrl_c_stops_cleanly(self):
        with patch("l4d2_mod_db.monitor.time.sleep", side_effect=KeyboardInterrupt):
            code, out, err = self.invoke(["--watch"])
        self.assertEqual(code, 0)
        self.assertIn("Monitoring stopped", out)

    def test_watch_subprocess_detects_live_fixture_add_modify_and_remove(self):
        candidate = self.put("left4dead2/addons/workshop/123.vpk", build_vpk())
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "l4d2_mod_db", "--game-root", str(self.game),
             "--watch", "--cycles", "30", "--poll-interval", "0.05", "--settle-seconds", "0.05"],
            cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, text=True,
        )
        lines = queue.Queue()
        def collect():
            for line in process.stdout:
                lines.put(line)
        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        captured = []
        def await_event(kind, filename):
            while True:
                try:
                    line = lines.get(timeout=5)
                except queue.Empty:
                    self.fail(f"Timed out waiting for {kind} {filename}: {captured}")
                captured.append(line)
                if f"Event {kind}:" in line and filename in line:
                    return
        try:
            await_event("indexed", "123.vpk")
            self.put("left4dead2/addons/workshop/456.vpk", build_vpk(("models/new.mdl",)))
            await_event("indexed", "456.vpk")
            candidate.write_bytes(build_vpk(("scripts/updated.txt",)))
            await_event("updated", "123.vpk")
            (self.workshop / "456.vpk").unlink()
            await_event("removed", "456.vpk")
            self.assertEqual(process.wait(timeout=5), 0, process.stderr.read())
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            reader.join(timeout=1)
            process.stdout.close()
            process.stderr.close()

    def test_validation_utility_reuses_indexes_and_preserves_references(self):
        self.put("left4dead2/addons/workshop/123.vpk", build_vpk())
        result = subprocess.run(
            [sys.executable, "-B", "-m", "tools.validate_collection", "--game-root", str(self.game), "--settle-seconds", "0.01"],
            cwd=PROJECT_ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, check=False, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertTrue(summary["vpk_and_jpg_references_unchanged"])
        self.assertTrue(summary["ready"])
        self.assertEqual(summary["parse_attempts_after_unchanged_poll"], 1)
        self.assertFalse(summary["errors"])
