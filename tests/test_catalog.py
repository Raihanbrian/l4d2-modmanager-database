"""M3 lifecycle/integrity tests on isolated synthetic installations and storage."""

from contextlib import contextmanager, closing
import json
import os
from pathlib import Path, PureWindowsPath
import sqlite3
import subprocess
import sys
from unittest.mock import patch

from l4d2_mod_db.catalog import CatalogMonitor, CatalogRepository
from l4d2_mod_db.security import DiscoveryStatus, ScopedWorkshopAccess, WorkshopSnapshot
from l4d2_mod_db.storage import CatalogDatabase, CatalogError, StoragePolicy, root_key, validate_schema
from tools.create_demo import fictional_records, create_demo
from .helpers import FixtureTestCase, PROJECT_ROOT, FakeScandir
from .vpk_fixtures import build_vpk


class CatalogFixture(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.now = 0.0
        self.access = ScopedWorkshopAccess(self.game)
        self.policy = StoragePolicy.isolated_test(self.workspace / "catalog", self.access)
        self.db = CatalogDatabase(self.policy)
        self.repo = CatalogRepository(self.db, self.access)
        self.session = self.new_session()

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def new_session(self, repository=None):
        return CatalogMonitor(repository or self.repo, clock=lambda: self.now)

    def add(self, name="123.vpk", paths=("Models/Weapons/Example.mdl",)):
        return self.put("left4dead2/addons/workshop/" + name, build_vpk(paths))

    def settle(self, session=None):
        session = session or self.session
        session.poll()
        self.now += 2.1
        return session.poll()

    def scalar(self, sql):
        return self.db.connection.execute(sql).fetchone()[0]

    def rows(self, table):
        return [tuple(row) for row in self.db.connection.execute("SELECT * FROM " + table)]

    def snapshot(self):
        return {table: self.rows(table) for table in ("installations", "packages", "package_indexes", "assets", "workshop_items")}


class CatalogLifecycleTests(CatalogFixture):
    def test_empty_collection_has_zero_counts_and_quiet_audit(self):
        self.assertTrue(self.session.poll().ready)
        self.assertEqual(self.repo.counts(), dict(packages=0, current_indexes=0, matching_previews=0, current_assets=0, retained_assets=0))
        self.session.poll()
        self.assertEqual(self.scalar("SELECT count(*) FROM scan_runs"), 1)

    def test_new_then_quiet_polls_preserve_ids_and_audit(self):
        self.add(); self.put("left4dead2/addons/workshop/123.jpg", b"fake preview")
        report = self.settle()
        self.assertTrue(report.ready)
        self.assertEqual(self.repo.counts(), dict(packages=1, current_indexes=1, matching_previews=1, current_assets=1, retained_assets=1))
        before = self.snapshot()
        for _ in range(100):
            self.now += 1; self.session.poll()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.scalar("SELECT count(*) FROM scan_runs"), 1)
        self.assertEqual(self.session.monitor.parse_attempts, 1)

    def test_restart_is_provisional_reuses_index_and_keeps_uuid(self):
        self.add(); self.settle()
        identity = self.scalar("SELECT package_id FROM packages")
        before = self.rows("package_indexes"), self.rows("assets")
        self.db.close(); self.db = CatalogDatabase(self.policy)
        self.repo = CatalogRepository(self.db, self.access)
        session = self.new_session()
        report = session.poll()
        self.assertTrue(report.records[0].stale)
        self.now += 2.1; report = session.poll()
        self.assertTrue(report.ready)
        self.assertEqual(session.monitor.parse_attempts, 0)
        self.assertEqual(identity, self.scalar("SELECT package_id FROM packages"))
        self.assertEqual(before, (self.rows("package_indexes"), self.rows("assets")))
        self.assertEqual(self.scalar("SELECT count(*) FROM scan_runs"), 2)

    def test_update_keeps_uuid_and_replaces_assets_atomically(self):
        path = self.add(); self.settle()
        identity = self.scalar("SELECT package_id FROM packages")
        replacement = self.workshop / "replace.tmp"
        replacement.write_bytes(build_vpk(("sound/changed.wav", "scripts/changed.txt")))
        replacement.replace(path)
        self.settle()
        self.assertEqual(identity, self.scalar("SELECT package_id FROM packages"))
        self.assertEqual(self.scalar("SELECT generation FROM package_indexes"), 2)
        self.assertEqual(self.scalar("SELECT count(*) FROM assets"), 2)
        self.assertEqual(self.scalar("SELECT canonical_path_bytes FROM assets ORDER BY canonical_path_bytes LIMIT 1"), b"scripts/changed.txt")

    def test_corrupt_update_retains_old_assets_across_restart(self):
        path = self.add(); self.settle()
        saved = self.rows("assets"), self.rows("package_indexes")
        path.write_bytes(b"broken")
        report = self.settle()
        self.assertTrue(report.records[0].stale)
        self.assertEqual(self.scalar("SELECT index_status FROM packages"), "error")
        self.assertEqual(self.scalar("SELECT observed_size_bytes FROM packages"), 6)
        self.assertEqual(saved, (self.rows("assets"), self.rows("package_indexes")))
        runs = self.scalar("SELECT count(*) FROM scan_runs")
        for _ in range(30):
            self.now += 6; self.session.poll()
        self.assertEqual(runs, self.scalar("SELECT count(*) FROM scan_runs"))
        self.session = self.new_session(); self.settle()
        self.assertEqual(saved, (self.rows("assets"), self.rows("package_indexes")))

    def test_new_corrupt_then_recovery(self):
        path = self.put("left4dead2/addons/workshop/123.vpk", b"bad")
        self.settle()
        self.assertEqual(self.scalar("SELECT count(*) FROM package_indexes"), 0)
        identity = self.scalar("SELECT package_id FROM packages")
        path.write_bytes(build_vpk()); self.settle()
        self.assertEqual(identity, self.scalar("SELECT package_id FROM packages"))
        self.assertEqual(self.scalar("SELECT generation FROM package_indexes"), 1)

    def test_confirmed_removal_then_return_creates_new_uuid(self):
        path = self.add(); self.settle()
        identity = self.scalar("SELECT package_id FROM packages")
        path.unlink(); self.session.poll()
        self.assertEqual(self.scalar("SELECT presence_status FROM packages"), "missing_pending")
        self.now += 2.1; self.session.poll()
        self.assertEqual(self.repo.counts()["packages"], 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM assets"), 1)
        self.add(); self.settle()
        active = self.scalar("SELECT package_id FROM packages WHERE removed_at IS NULL")
        self.assertNotEqual(identity, active)
        self.assertEqual(self.scalar("SELECT count(*) FROM packages"), 2)
        self.assertEqual(self.scalar("SELECT count(*) FROM workshop_items"), 1)

    def test_brief_absence_retains_uuid(self):
        path = self.add(); self.settle(); identity = self.scalar("SELECT package_id FROM packages")
        contents = path.read_bytes(); path.unlink(); self.session.poll()
        path.write_bytes(contents); self.settle()
        self.assertEqual(identity, self.scalar("SELECT package_id FROM packages"))
        self.assertIsNone(self.scalar("SELECT removed_at FROM packages"))

    def test_missing_workshop_folder_never_confirms_removal(self):
        self.add(); self.settle(); saved = self.rows("assets")
        renamed = self.workshop.with_name("offline")
        self.workshop.rename(renamed)
        try:
            self.session.poll(); self.now += 100; self.session.poll()
            self.assertEqual(self.scalar("SELECT presence_status FROM packages"), "unavailable")
            self.assertEqual(self.rows("assets"), saved)
            self.assertIsNone(self.scalar("SELECT removed_at FROM packages"))
        finally:
            renamed.rename(self.workshop)
        self.assertTrue(self.settle().ready)

    def test_partial_scan_never_removes_or_loses_preview(self):
        self.add(); self.put("left4dead2/addons/workshop/123.jpg", b"jpg"); self.settle()
        for names in ([], ["123.vpk"]):
            with patch("l4d2_mod_db.security.os.scandir", return_value=FakeScandir(names, fail_after=True)):
                self.session.poll(); self.now += 10; self.session.poll()
            self.assertIsNone(self.scalar("SELECT removed_at FROM packages"))
            self.assertEqual(self.scalar("SELECT preview_status FROM packages"), "unknown")
            self.assertTrue(self.scalar("SELECT preview_relative_path FROM packages").endswith("123.jpg"))
        self.assertEqual(self.scalar("SELECT count(*) FROM assets"), 1)

    def test_outage_resets_removal_timer(self):
        path = self.add(); self.settle(); path.unlink(); self.session.poll()
        with patch.object(self.access, "list_workshop_files", return_value=WorkshopSnapshot(DiscoveryStatus.UNAVAILABLE)):
            self.now += 10; self.session.poll()
        self.now += 10; self.session.poll()
        self.assertEqual(self.scalar("SELECT presence_status FROM packages"), "missing_pending")
        self.now += 2.1; self.session.poll()
        self.assertEqual(self.scalar("SELECT presence_status FROM packages"), "removed")

    def test_restart_resets_removal_timer(self):
        path = self.add(); self.settle(); path.unlink(); self.session.poll()
        self.now += 100; self.session = self.new_session(); self.session.poll()
        self.assertIsNone(self.scalar("SELECT removed_at FROM packages"))
        self.now += 2.1; self.session.poll()
        self.assertEqual(self.scalar("SELECT presence_status FROM packages"), "removed")

    def test_preview_only_update_does_not_reindex(self):
        self.add(); self.settle(); before = self.rows("package_indexes")
        self.put("left4dead2/addons/workshop/123.jpg", b"jpg"); self.session.poll()
        self.assertEqual(self.rows("package_indexes"), before)
        self.assertEqual(self.repo.counts()["matching_previews"], 1)

    def test_pending_write_progress_is_coalesced(self):
        self.add(); self.settle()
        path = self.add("changing.vpk"); self.session.poll()
        runs = self.scalar("SELECT count(*) FROM scan_runs")
        for i in range(20):
            path.write_bytes(b"x" * (i + 1)); self.now += 1; self.session.poll()
        self.assertEqual(runs, self.scalar("SELECT count(*) FROM scan_runs"))
        self.now += 2.1; self.session.poll()
        self.assertGreater(self.scalar("SELECT count(*) FROM scan_runs"), runs)

    def test_startup_with_unstable_file_still_persists_other_packages(self):
        self.add(); path = self.add("changing.vpk"); self.session.poll()
        self.now += 2.1; path.write_bytes(b"x"); self.session.poll()
        self.assertEqual(self.repo.counts()["packages"], 2)
        self.assertEqual(self.repo.counts()["current_indexes"], 1)

    def test_nonnumeric_and_leading_zero_ids(self):
        self.add("000123.VPK"); self.add("Custom.VpK"); self.settle()
        self.assertEqual([row[0] for row in self.db.connection.execute("SELECT workshop_id FROM packages ORDER BY relative_path")], ["000123", None])

    def test_lossless_non_utf8_blob_roundtrip(self):
        raw = build_vpk(("Sound/VoicePack_ABCD.wav",)).replace(b"ABCD", b"\xb8\xb1\xb1\xbe")
        self.put("left4dead2/addons/workshop/123.vpk", raw); self.settle()
        row = self.db.connection.execute("SELECT *,typeof(original_path_bytes) AS kind FROM assets").fetchone()
        self.assertEqual(row["kind"], "blob")
        self.assertEqual(row["original_path_bytes"], b"Sound/VoicePack_\xb8\xb1\xb1\xbe.wav")
        self.assertEqual(row["canonical_path_bytes"], b"sound/voicepack_\xb8\xb1\xb1\xbe.wav")
        self.assertEqual(row["utf8_valid"], 0)
        session = self.new_session(); self.settle(session)
        self.assertEqual(session.monitor.parse_attempts, 0)
        self.assertEqual(self.scalar("SELECT length(index_sha256) FROM package_indexes"), 32)


class CatalogTransactionTests(CatalogFixture):
    def test_rollback_after_delete_retains_previous_snapshot(self):
        path = self.add(); self.settle()
        path.write_bytes(build_vpk(("scripts/updated.txt",))); self.session.poll()
        before = self.snapshot(); self.now += 2.1
        def fail(stage):
            if stage == "after_asset_delete": raise sqlite3.OperationalError("injected")
        with self.assertRaises(sqlite3.Error): self.session.poll(fault=fail)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.scalar("SELECT outcome FROM scan_runs ORDER BY scan_id DESC LIMIT 1"), "failed")
        self.assertTrue(self.settle().ready)
        self.assertEqual(self.scalar("SELECT generation FROM package_indexes"), 2)

    def test_interrupt_before_commit_rolls_back_whole_batch(self):
        self.add(); self.settle(); self.add("456.vpk"); self.session.poll(); self.now += 2.1
        before = self.snapshot()
        def interrupt(stage):
            if stage == "before_commit": raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): self.session.poll(fault=interrupt)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.scalar("SELECT outcome FROM scan_runs ORDER BY scan_id DESC LIMIT 1"), "interrupted")

    def test_concurrent_writer_supersedes_staged_removal_and_resets_timers(self):
        path = self.add(); self.settle()
        with CatalogDatabase(self.policy) as second:
            other = self.new_session(CatalogRepository(second, self.access))
            self.settle(other)  # startup publishes a newer generation
            path.unlink(); report = self.session.poll()
            self.assertEqual(self.session.last_outcome, "superseded")
            self.assertFalse(report.ready)
            self.assertIsNone(self.scalar("SELECT removed_at FROM packages"))
            self.session.poll()
            self.assertIsNone(self.scalar("SELECT removed_at FROM packages"))
            self.now += 2.1; self.session.poll()
            self.assertEqual(self.scalar("SELECT presence_status FROM packages"), "removed")

    def test_killed_process_leaves_unconfirmed_audit_but_valid_catalog(self):
        path = self.add(); self.settle(); before = self.snapshot()
        path.write_bytes(build_vpk(("scripts/changed.txt",)))
        self.db.close()
        script = """
import os,sys
from pathlib import Path
from l4d2_mod_db.catalog import CatalogMonitor,CatalogRepository
from l4d2_mod_db.storage import CatalogDatabase,StoragePolicy
from l4d2_mod_db.security import ScopedWorkshopAccess
access=ScopedWorkshopAccess(sys.argv[1]); clock=[0]
db=CatalogDatabase(StoragePolicy.isolated_test(Path(sys.argv[2]),access))
session=CatalogMonitor(CatalogRepository(db,access),clock=lambda:clock[0])
session.poll(); clock[0]=3
def die(stage):
    if stage=='after_asset_delete': os._exit(37)
session.poll(fault=die)
"""
        result = subprocess.run([sys.executable, "-B", "-c", script, str(self.game), str(self.policy.directory)], cwd=PROJECT_ROOT, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 37, result.stderr)
        self.db = CatalogDatabase(self.policy); self.repo = CatalogRepository(self.db, self.access)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.scalar("SELECT outcome FROM scan_runs ORDER BY scan_id DESC LIMIT 1"), "started")
        self.assertEqual(self.scalar("PRAGMA integrity_check"), "ok")
        self.session = self.new_session(); self.assertTrue(self.settle().ready)


class CatalogSchemaTests(CatalogFixture):
    def test_ddl_matches_approved_proposal_exactly(self):
        import re
        from l4d2_mod_db.schema import SCHEMA_SQL
        text = (PROJECT_ROOT / "M3_SCHEMA_PROPOSAL.md").read_text(encoding="utf-8")
        sql = re.search(r"```sql\n(.*?)```", text, re.S)[1]
        self.assertEqual(SCHEMA_SQL.strip(), sql[sql.index("CREATE TABLE"):].strip())

    def test_exact_schema_and_pragmas(self):
        validate_schema(self.db.connection)
        self.assertEqual(self.scalar("PRAGMA user_version"), 1)
        self.assertEqual(self.scalar("PRAGMA foreign_keys"), 1)
        self.assertEqual(self.scalar("PRAGMA journal_mode"), "wal")
        self.assertEqual(self.scalar("PRAGMA synchronous"), 2)
        self.assertEqual(self.scalar("PRAGMA temp_store"), 2)
        self.assertEqual(self.scalar("PRAGMA busy_timeout"), 5000)
        self.assertEqual(len(self.db.connection.execute("PRAGMA table_list").fetchall()), 9)  # 7 + SQLite's 2 system tables

    def test_key_and_type_constraints(self):
        self.add(); self.settle()
        connection = self.db.connection
        violations = [
            "UPDATE assets SET canonical_path_bytes='text'",
            "UPDATE assets SET crc32=-1",
            "UPDATE assets SET utf8_valid=2",
            "UPDATE package_indexes SET index_sha256=X'00'",
            "UPDATE packages SET removed_at='now'",
            "UPDATE packages SET index_status='invented'",
            "UPDATE packages SET state_scan_id=99999",
            "UPDATE workshop_items SET workshop_id='abc'",
            "DELETE FROM installations",
            "DELETE FROM packages",
            "DELETE FROM scan_runs",
            "INSERT INTO assets SELECT * FROM assets",
            "INSERT INTO packages SELECT * FROM packages",
        ]
        for sql in violations:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                with self.db.transaction(): connection.execute(sql)
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_scoped_foreign_keys_reject_cross_installation(self):
        self.add(); self.settle()
        other_game = self.make_game("other")
        other_repo = CatalogRepository(self.db, ScopedWorkshopAccess(other_game))
        for sql in ("UPDATE package_indexes SET installation_id=?", "UPDATE packages SET installation_id=?"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                with self.db.transaction(): self.db.connection.execute(sql, (other_repo.installation_id,))

    def test_unknown_version_refused_without_migration(self):
        self.db.connection.execute("PRAGMA user_version=99"); self.db.close()
        with self.assertRaises(CatalogError): CatalogDatabase(self.policy)

    def test_changed_schema_refused(self):
        self.db.connection.execute("CREATE TABLE unexpected(x)"); self.db.close()
        with self.assertRaises(CatalogError): CatalogDatabase(self.policy)

    def test_forged_saved_path_never_authorizes_access(self):
        self.add(); self.settle()
        self.db.connection.execute("UPDATE packages SET relative_path='../../outside.vpk'")
        with self.assertRaises((CatalogError, ValueError)): self.new_session()

    def test_root_key_exact_policy(self):
        self.assertEqual(root_key(r"E:\FictionalSteam\steamapps\common\Left 4 Dead 2"), "e:/fictionalsteam/steamapps/common/left 4 dead 2")
        self.assertNotEqual(root_key("E:/Caf\u00e9"), root_key("E:/Cafe\u0301"))
        self.assertEqual(root_key("E:\\"), "e:/")

    def test_root_casefold_collision_refused(self):
        self.db.connection.execute("UPDATE installations SET root_path='E:\\different'")
        with self.assertRaises(CatalogError): CatalogRepository(self.db, self.access)


class StorageBoundaryTests(CatalogFixture):
    def test_resolved_alias_cannot_bypass_game_storage_separation(self):
        original = Path.resolve
        directory = self.policy.directory
        def resolve(path, *args, **kwargs):
            return self.workshop if path == directory else original(path, *args, **kwargs)
        with patch.object(Path, "resolve", resolve):
            with self.assertRaises(CatalogError): self.policy.check()

    def test_no_missing_localappdata_fallback(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": ""}):
            with self.assertRaises(CatalogError): StoragePolicy.production(self.access)

    def test_production_directory_disjoint_and_only_app_owned(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.workspace)}):
            policy = StoragePolicy.production(self.access)
        self.assertEqual(policy.directory, self.workspace / "L4D2ModDatabase")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.game)}):
            with self.assertRaises(CatalogError): StoragePolicy.production(self.access)
        self.assertFalse((self.game / "L4D2ModDatabase").exists())

    def test_test_store_cannot_target_game_or_outside_test_workspace(self):
        with self.assertRaises(CatalogError): StoragePolicy.isolated_test(self.workshop / "db", self.access)
        with self.assertRaises(CatalogError): StoragePolicy.isolated_test(PROJECT_ROOT / "db", self.access)

    def test_storage_reparse_attribute_is_refused(self):
        from types import SimpleNamespace
        actual = Path.lstat
        directory = self.policy.directory
        def inspect(path, *args, **kwargs):
            result = actual(path, *args, **kwargs)
            if path == directory:
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result
        with patch.object(Path, "lstat", inspect):
            with self.assertRaises(CatalogError): self.policy.check()

    def test_database_hardlink_refused(self):
        from types import SimpleNamespace
        actual = Path.lstat
        database = self.policy.database
        def inspect(path, *args, **kwargs):
            result = actual(path, *args, **kwargs)
            if path == database:
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0, st_nlink=2)
            return result
        with patch.object(Path, "lstat", inspect):
            with self.assertRaises(CatalogError): self.policy.check()

    def test_cli_requires_opt_in_and_preserves_fixture(self):
        self.add()
        before = {p.name: p.read_bytes() for p in self.workshop.iterdir()}
        env = dict(os.environ, LOCALAPPDATA=str(self.workspace))
        args = [sys.executable, "-B", "-m", "l4d2_mod_db", "--game-root", str(self.game)]
        plain = subprocess.run(args + ["--index", "--settle-seconds", "0.01"], cwd=PROJECT_ROOT, env=env, capture_output=True, timeout=20)
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertFalse((self.workspace / "L4D2ModDatabase").exists())
        catalog = subprocess.run(args + ["--index", "--catalog", "--settle-seconds", "0.01"], cwd=PROJECT_ROOT, env=env, capture_output=True, timeout=20)
        self.assertEqual(catalog.returncode, 0, catalog.stderr)
        self.assertIn(b"M3 catalog: committed", catalog.stdout)
        self.assertTrue((self.workspace / "L4D2ModDatabase/catalog.sqlite3").exists())
        db_path = self.workspace / "L4D2ModDatabase/catalog.sqlite3"
        with closing(sqlite3.connect(db_path)) as connection:
            identity = connection.execute("SELECT package_id FROM packages").fetchone()[0]
        restarted = subprocess.run(args + ["--index", "--catalog", "--settle-seconds", "0.01"], cwd=PROJECT_ROOT, env=env, capture_output=True, timeout=20)
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        self.assertIn(b"parse attempts: 0", restarted.stdout)
        with closing(sqlite3.connect(db_path)) as connection:
            self.assertEqual(connection.execute("SELECT package_id FROM packages").fetchone()[0], identity)
            self.assertEqual(connection.execute("SELECT generation FROM package_indexes").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM scan_runs").fetchone()[0], 2)
        invalid = subprocess.run(args + ["--catalog"], cwd=PROJECT_ROOT, env=env, capture_output=True, timeout=20)
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.workshop.iterdir()})


class DemoTests(FixtureTestCase):
    def test_demo_exact_records_constraints_and_standalone(self):
        path = create_demo(self.workspace / "demo.sqlite3")
        with closing(sqlite3.connect(path)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            validate_schema(connection)
            for table, records in fictional_records().items():
                actual = [dict(row) for row in connection.execute("SELECT * FROM " + table)]
                self.assertCountEqual(actual, records)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(connection.execute("SELECT count(*) FROM assets WHERE utf8_valid=0").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM packages WHERE removed_at IS NULL").fetchone()[0], 5)
        self.assertFalse(path.with_name(path.name + "-wal").exists())
        self.assertFalse(path.with_name(path.name + "-shm").exists())
        with self.assertRaises(FileExistsError): create_demo(path)

    def test_demo_select_queries_have_documented_results(self):
        import re
        path = create_demo(self.workspace / "queries.sqlite3")
        text = (PROJECT_ROOT / "M3_SAMPLE_DATA.md").read_text(encoding="utf-8")
        queries = re.findall(r"```sql\n(.*?)```", text, re.S)
        parameters = dict(installation_id="7c1a9e306b454d0d9a651827d9f3ac10", package_id="3a2f7c196d404b8a9e650aa243b9e702")
        with closing(sqlite3.connect(path)) as connection:
            results = [connection.execute(query, parameters).fetchall() for query in queries]
        self.assertEqual(len(results), 4)
        self.assertEqual([len(rows) for rows in results], [5, 6, 1, 7])
        self.assertEqual([row[-1] for row in results[3]], [1, 0, 1, 1, 0, 1, 2])
        # Check every displayed result cell against the teaching document, not only counts.
        for number, letter in enumerate("ABCD"):
            part = text.split("### Query " + letter)[1]
            if number < 3: part = part.split("### Query " + "ABCD"[number+1])[0]
            else: part = part.split("## 7.")[0]
            lines = [line for line in part.splitlines() if line.startswith("|")][2:]
            expected = [[cell.strip().strip('`') for cell in line.strip('|').split('|')] for line in lines]
            displayed = [["NULL" if value is None else str(value) for value in row] for row in results[number]]
            self.assertEqual(displayed, expected)

    def test_delivered_demo_matches_reproducible_copy(self):
        delivered = PROJECT_ROOT / "examples/m3-demo/m3_demo.sqlite3"
        copy = create_demo(self.workspace / "copy.sqlite3")
        with closing(sqlite3.connect(delivered)) as left, closing(sqlite3.connect(copy)) as right:
            for table in fictional_records():
                self.assertEqual(left.execute("SELECT * FROM " + table).fetchall(), right.execute("SELECT * FROM " + table).fetchall())


class CatalogAdditionalTests(CatalogFixture):
    def test_multiple_installations_do_not_merge_packages(self):
        self.add(); self.settle()
        other_game = self.make_game("other")
        (other_game / "left4dead2/addons/workshop/123.vpk").write_bytes(build_vpk())
        other = CatalogRepository(self.db, ScopedWorkshopAccess(other_game))
        self.settle(self.new_session(other))
        self.assertEqual(self.scalar("SELECT count(*) FROM installations"), 2)
        self.assertEqual(self.scalar("SELECT count(*) FROM packages"), 2)
        self.assertEqual(self.scalar("SELECT count(DISTINCT package_id) FROM packages"), 2)
        self.assertEqual(self.scalar("SELECT count(*) FROM workshop_items"), 1)

    def test_partial_scan_can_add_positive_observations(self):
        self.add(); self.settle(); self.add("456.vpk")
        with patch("l4d2_mod_db.security.os.scandir", return_value=FakeScandir(["456.vpk"], fail_after=True)):
            self.settle()
        self.assertEqual(self.repo.counts()["packages"], 2)
        self.assertEqual(self.scalar("SELECT count(*) FROM assets"), 2)
        self.assertEqual(self.scalar("SELECT count(*) FROM packages WHERE removed_at IS NOT NULL"), 0)

    def test_complete_scan_confirms_preview_removal(self):
        self.add(); preview = self.put("left4dead2/addons/workshop/123.jpg", b"jpg"); self.settle()
        preview.unlink(); self.session.poll()
        self.assertEqual(self.scalar("SELECT preview_status FROM packages"), "missing")
        self.assertIsNone(self.scalar("SELECT preview_relative_path FROM packages"))

    def test_unchanged_folder_errors_are_coalesced(self):
        from l4d2_mod_db.security import Diagnostic
        self.add(); self.settle()
        error = WorkshopSnapshot(DiscoveryStatus.UNAVAILABLE, diagnostics=(Diagnostic("ENUMERATION_FAILED", "Synthetic inaccessible Workshop."),))
        with patch.object(self.access, "list_workshop_files", return_value=error):
            self.session.poll(); saved = self.rows("scan_runs"), self.rows("scan_issues")
            for _ in range(30): self.now += 1; self.session.poll()
        self.assertEqual(saved, (self.rows("scan_runs"), self.rows("scan_issues")))

    def test_parser_policy_change_reindexes_without_changing_uuid(self):
        self.add(); self.settle(); identity = self.scalar("SELECT package_id FROM packages")
        self.db.connection.execute("UPDATE package_indexes SET parser_version='older-parser'")
        session = self.new_session(); self.settle(session)
        self.assertEqual(session.monitor.parse_attempts, 1)
        self.assertEqual(identity, self.scalar("SELECT package_id FROM packages"))
        self.assertEqual(self.scalar("SELECT generation FROM package_indexes"), 2)

    def test_saved_blob_tampering_is_refused(self):
        self.add(); self.settle()
        self.db.connection.execute("UPDATE assets SET canonical_path_bytes=X'7878'")
        with self.assertRaises(CatalogError): self.new_session()

    def test_configurable_saved_resource_guard(self):
        from l4d2_mod_db.vpk import ParserLimits
        self.add(paths=("scripts/a.txt", "scripts/b.txt")); self.settle()
        repository = CatalogRepository(self.db, self.access, limits=ParserLimits(max_entries=1))
        with self.assertRaises(CatalogError): self.new_session(repository)

    def test_failed_audit_finalization_leaves_started_without_catalog_damage(self):
        path = self.add(); self.settle(); path.write_bytes(build_vpk(("scripts/updated.txt",)))
        self.session.poll(); self.now += 2.1; before = self.snapshot()
        original = self.db.transaction
        failed = [False]
        @contextmanager
        def transactions():
            if failed[0]:
                failed[0] = False
                raise sqlite3.OperationalError("injected audit failure")
            with original() as connection:
                yield connection
        def fault(stage):
            if stage == "after_asset_delete":
                failed[0] = True
                raise sqlite3.OperationalError("injected commit failure")
        with patch.object(self.db, "transaction", transactions):
            with self.assertRaises(sqlite3.Error): self.session.poll(fault=fault)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.scalar("SELECT outcome FROM scan_runs ORDER BY scan_id DESC LIMIT 1"), "started")

    def test_case_only_filename_change_keeps_uuid(self):
        path = self.add(); self.settle(); identity = self.scalar("SELECT package_id FROM packages")
        middle = path.with_name("intermediate.tmp"); path.rename(middle); middle.rename(path.with_name("123.VPK"))
        self.settle()
        self.assertEqual(identity, self.scalar("SELECT package_id FROM packages"))

    def test_database_failure_does_not_print_sensitive_exception(self):
        import io
        from contextlib import redirect_stdout
        from l4d2_mod_db.cli import main
        output = io.StringIO()
        with patch("l4d2_mod_db.cli.StoragePolicy.production", side_effect=CatalogError("sensitive path")), redirect_stdout(output):
            code = main(["--game-root", str(self.game), "--index", "--catalog"])
        self.assertEqual(code, 1)
        self.assertNotIn("sensitive path", output.getvalue())
