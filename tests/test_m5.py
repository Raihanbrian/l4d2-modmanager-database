"""M5 checkpoint tests. M6/Tk modules are deliberately absent from this phase."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import patch

from l4d2_mod_db.classification import (add_user_effect, catalog_cards, classification_statistics,
    refresh_classification, save_mod_edit, save_effect_edit, retire_user_effect)
from l4d2_mod_db.conflicts import analyze_conflicts
from l4d2_mod_db.migrations import logical_digest, upgrade
from l4d2_mod_db.storage import CatalogDatabase, CatalogReader, CatalogError, validate_schema
from .test_catalog import CatalogFixture
from .helpers import PROJECT_ROOT
from .vpk_fixtures import build_vpk


class MigrationTests(CatalogFixture):
    def test_verified_backup_and_additive_upgrade_preserve_all_core_rows(self):
        self.add(); self.settle(); before = self.snapshot(); fingerprint = logical_digest(self.db.connection)
        result = upgrade(self.db)
        self.assertEqual((result.from_version, result.to_version), (1, 2))
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(Path(result.backup_path).as_uri()+"?mode=ro", uri=True)) as backup:
            validate_schema(backup)
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(backup.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(logical_digest(backup), fingerprint)
            self.assertEqual(result.backup_digest, fingerprint)
        self.assertEqual(self.scalar("PRAGMA user_version"), 2)
        self.assertIsNone(upgrade(self.db))

    def test_failure_at_each_boundary_rolls_back_and_recovery_succeeds(self):
        self.add(); self.settle(); before = self.snapshot()
        for boundary in ("after_backup", "after_ddl", "before_commit"):
            def fault(stage):
                if stage == boundary: raise RuntimeError("injected failure")
            with self.subTest(boundary=boundary), self.assertRaises(RuntimeError): upgrade(self.db, fault=fault)
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.scalar("PRAGMA user_version"), 1)
            validate_schema(self.db.connection)
        self.assertIsNotNone(upgrade(self.db))

    def test_backup_verification_failure_prevents_ddl(self):
        self.add(); self.settle(); before = self.snapshot()
        with patch("l4d2_mod_db.migrations.logical_digest", side_effect=["backup", "different-source"]):
            with self.assertRaises(CatalogError): upgrade(self.db)
        self.assertEqual(self.scalar("PRAGMA user_version"), 1)
        self.assertEqual(before, self.snapshot())

    def test_backup_reparse_path_is_refused(self):
        folder = self.policy.directory / "backups"; folder.mkdir()
        with patch("l4d2_mod_db.migrations._check_component", side_effect=CatalogError("reparse")):
            with self.assertRaises(CatalogError): upgrade(self.db)
        self.assertEqual(self.scalar("PRAGMA user_version"), 1)

    def test_interrupted_migration_keeps_original_database(self):
        self.add(); self.settle(); before = self.snapshot()
        def interrupt(stage):
            if stage == "before_commit": raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): upgrade(self.db, fault=interrupt)
        self.assertEqual(self.scalar("PRAGMA user_version"), 1)
        self.assertEqual(before, self.snapshot())

    def test_killed_migration_process_recovers_without_reinitialization(self):
        self.add(); self.settle(); before = self.snapshot(); self.db.close()
        code = """
from pathlib import Path
import sys,os
from l4d2_mod_db.security import ScopedWorkshopAccess
from l4d2_mod_db.storage import CatalogDatabase,StoragePolicy
from l4d2_mod_db.migrations import upgrade
access=ScopedWorkshopAccess(sys.argv[1])
with CatalogDatabase(StoragePolicy.isolated_test(Path(sys.argv[2]),access)) as db:
    def die(stage):
        if stage=='after_ddl': os._exit(41)
    upgrade(db,fault=die)
"""
        result = subprocess.run([sys.executable,"-B","-c",code,str(self.game),str(self.policy.directory)], cwd=PROJECT_ROOT, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 41, result.stderr)
        self.db = CatalogDatabase(self.policy)
        self.assertEqual(self.scalar("PRAGMA user_version"), 1)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.scalar("PRAGMA integrity_check"), "ok")
        upgrade(self.db)

    def test_readers_and_m4_accept_extended_schema(self):
        self.add("1.vpk"); self.add("2.vpk"); self.settle(); upgrade(self.db)
        with CatalogReader(self.policy) as reader:
            report = analyze_conflicts(reader.connection, self.repo.installation_id)
            self.assertEqual(report.counts["current_package_pairs"], 1)
        self.db.close(); self.db = CatalogDatabase(self.policy)
        self.assertEqual(self.scalar("PRAGMA user_version"), 2)

    def test_new_keys_types_and_scoped_user_edit_integrity(self):
        self.add(); self.settle(); upgrade(self.db); refresh_classification(self.db,self.repo.installation_id)
        bad = ["UPDATE package_effects SET component_id='bad'", "UPDATE package_effects SET active=3",
               "INSERT INTO effect_targets SELECT effect_id,'bad' FROM package_effects",
               "DELETE FROM packages", "INSERT INTO effect_evidence SELECT * FROM effect_evidence"]
        for sql in bad:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                with self.db.transaction(): self.db.connection.execute(sql)
        self.assertEqual(self.db.connection.execute("PRAGMA foreign_key_check").fetchall(), [])


class ClassificationTests(CatalogFixture):
    def setUp(self):
        super().setUp(); upgrade(self.db)

    def classify(self, paths):
        self.add(paths=paths); self.settle(); refresh_classification(self.db,self.repo.installation_id)
        return catalog_cards(self.db.connection,self.repo.installation_id)[0]

    def cards(self): return catalog_cards(self.db.connection,self.repo.installation_id)

    def test_supported_original_survivor_target_not_replacement(self):
        card = self.classify(("models/survivors/survivor_producer.mdl",))
        effect = card.effects[0]
        self.assertEqual(effect.target_labels, ("Rochelle",))
        self.assertEqual(effect.game_identifiers, (None,))
        self.assertIsNone(effect.replacement)
        self.assertEqual(effect.review_status, "Needs Review")
        self.assertIn("Rochelle → Unknown replacement", card.summary)

    def test_weapon_world_model_and_script_use_reviewed_canonical_identifier(self):
        card = self.classify(("models/w_models/weapons/w_rifle_ak47.mdl", "scripts/weapon_rifle_ak47.txt"))
        self.assertEqual(len(card.effects), 2)
        self.assertTrue(all(effect.game_identifiers == ("weapon_rifle_ak47",) for effect in card.effects))
        self.assertTrue(all(effect.replacement is None for effect in card.effects))

    def test_unverified_viewmodel_spelling_stays_unknown(self):
        card = self.classify(("models/weapons/v_rifle_ak47.mdl", "models/v_models/v_rifle_ak47.mdl"))
        self.assertTrue(all(not effect.target_ids for effect in card.effects))

    def test_multiple_originals_and_components_remain_separate_effects(self):
        card = self.classify(("models/survivors/survivor_producer.mdl", "models/survivors/survivor_teenangst.mdl",
            "materials/shared/finish.vmt", "sound/ui/notice.wav", "resource/hud.res", "scripts/unknown.nut"))
        self.assertEqual(len(card.effects), 6)
        self.assertEqual({label for effect in card.effects for label in effect.target_labels}, {"Rochelle","Zoey"})
        self.assertEqual(set(card.category_ids), {"survivor","model","material","sound","ui","script"})

    def test_ambiguous_material_and_custom_name_do_not_invent_targets(self):
        card = self.classify(("materials/models/rochelle/M4A1.vmt",))
        self.assertFalse(card.effects[0].target_ids)
        self.assertIsNone(card.effects[0].replacement)

    def test_unknown_only_metadata_and_empty_indexes(self):
        card = self.classify(("addoninfo.txt", "addonimage.jpg"))
        self.assertEqual(card.review_status,"Needs Review")
        self.assertFalse(card.effects[0].target_ids)
        self.add(paths=()); self.settle(); refresh_classification(self.db,self.repo.installation_id)
        self.assertEqual(self.cards()[0].review_status,"Needs Review")

    def test_idempotent_classification_and_stable_effect_ids(self):
        card = self.classify(("models/survivors/survivor_producer.mdl",))
        changes = self.db.connection.total_changes
        self.assertEqual(refresh_classification(self.db,self.repo.installation_id), 0)
        self.assertEqual(changes, self.db.connection.total_changes)
        self.assertEqual(self.cards()[0].effects[0].effect_id, card.effects[0].effect_id)

    def test_non_utf8_evidence_remains_exact_blobs(self):
        raw = build_vpk(("Sound/Voice_ABCD.wav",)).replace(b"ABCD",b"\xb8\xb1\xb1\xbe")
        self.put("left4dead2/addons/workshop/123.vpk",raw); self.settle()
        refresh_classification(self.db,self.repo.installation_id)
        evidence = self.cards()[0].effects[0].evidence[0]
        self.assertEqual(evidence["original_path_bytes"], b"Sound/Voice_\xb8\xb1\xb1\xbe.wav")
        self.assertIsInstance(evidence["canonical_path_bytes"],bytes)

    def test_manual_values_and_multiple_targets_survive_restart(self):
        card = self.classify(("scripts/unknown.nut",)); effect=card.effects[0]
        save_mod_edit(self.db,self.repo.installation_id,card.package_id,friendly_name="My pack",description="User description",category_mode="replace",category_ids=("weapon","sound"))
        save_effect_edit(self.db,self.repo.installation_id,effect.effect_id,target_mode="replace",target_ids=("survivor:rochelle","survivor:zoey"),replacement_mode="value",replacement="Custom Survivor",component_mode="value",component_id="model")
        self.db.close(); self.db=CatalogDatabase(self.policy)
        saved=self.cards()[0]
        self.assertEqual(saved.display_name,"My pack")
        self.assertEqual(saved.description,"User description")
        self.assertEqual(saved.effects[0].target_labels,("Rochelle","Zoey"))
        self.assertEqual(saved.effects[0].replacement,"Custom Survivor")
        self.assertEqual(saved.review_status,"User confirmed")

    def test_explicit_unknown_overrides_inferred_target(self):
        card=self.classify(("models/survivors/survivor_producer.mdl",))
        save_effect_edit(self.db,self.repo.installation_id,card.effects[0].effect_id,target_mode="unknown",replacement_mode="unknown",component_mode="unknown")
        effect=self.cards()[0].effects[0]
        self.assertFalse(effect.target_ids); self.assertIsNone(effect.replacement)
        self.assertEqual(effect.review_status,"Needs Review")

    def test_update_retains_user_input_but_marks_review_and_keeps_evidence_separate(self):
        card=self.classify(("models/survivors/survivor_producer.mdl",)); effect=card.effects[0]
        save_effect_edit(self.db,self.repo.installation_id,effect.effect_id,target_mode="replace",target_ids=("survivor:rochelle",),replacement_mode="value",replacement="Lunar Medic")
        save_mod_edit(self.db,self.repo.installation_id,card.package_id,friendly_name="Medic")
        self.add(paths=("models/survivors/survivor_producer.mdl","sound/new.wav")); self.settle()
        refresh_classification(self.db,self.repo.installation_id)
        saved=self.cards()[0]
        edited=next(item for item in saved.effects if item.effect_id==effect.effect_id)
        self.assertEqual(edited.replacement,"Lunar Medic")
        self.assertEqual(saved.display_name,"Medic")
        self.assertTrue(edited.review_status.startswith("Stale"))
        self.assertEqual(edited.evidence[0]["basis_generation"],2)
        self.assertEqual(edited.user_edit["basis_generation"],1)

    def test_stale_form_save_does_not_assert_new_generation_was_reviewed(self):
        card=self.classify(("scripts/unknown.nut",))
        self.add(paths=("scripts/unknown.nut","sound/new.wav")); self.settle(); refresh_classification(self.db,self.repo.installation_id)
        save_mod_edit(self.db,self.repo.installation_id,card.package_id,friendly_name="Old form",expected_generation=1)
        self.assertTrue(self.cards()[0].review_status.startswith("Stale"))

    def test_disappeared_effect_keeps_inactive_correction(self):
        card=self.classify(("models/survivors/survivor_producer.mdl",)); effect=card.effects[0]
        save_effect_edit(self.db,self.repo.installation_id,effect.effect_id,replacement_mode="value",replacement="User identity")
        self.add(paths=("sound/only.wav",)); self.settle(); refresh_classification(self.db,self.repo.installation_id)
        inactive=next(item for item in self.cards()[0].effects if item.effect_id==effect.effect_id)
        self.assertFalse(inactive.active); self.assertEqual(inactive.replacement,"User identity")
        self.assertNotIn("User identity",self.cards()[0].summary)

    def test_corrupt_update_retains_classification_as_stale(self):
        self.classify(("models/survivors/survivor_producer.mdl",))
        (self.workshop/'123.vpk').write_bytes(b'broken'); self.settle()
        self.assertEqual(refresh_classification(self.db,self.repo.installation_id),0)
        self.assertTrue(self.cards()[0].effects[0].review_status.startswith("Stale"))

    def test_confirmed_removal_reappearance_never_inherits_edits(self):
        card=self.classify(("scripts/unknown.nut",));save_mod_edit(self.db,self.repo.installation_id,card.package_id,friendly_name="Old identity")
        (self.workshop/'123.vpk').unlink();self.settle()
        self.assertEqual(self.cards(),())
        self.add(paths=("scripts/unknown.nut",));self.settle();refresh_classification(self.db,self.repo.installation_id)
        new=self.cards()[0]
        self.assertNotEqual(new.package_id,card.package_id);self.assertNotEqual(new.display_name,"Old identity")
        self.assertEqual(self.scalar("SELECT count(*) FROM user_mod_edits"),1)

    def test_user_effect_lifecycle_and_validation(self):
        card=self.classify(())
        effect_id=add_user_effect(self.db,self.repo.installation_id,card.package_id)
        save_effect_edit(self.db,self.repo.installation_id,effect_id,target_mode="replace",target_ids=("weapon:weapon_rifle_ak47",),replacement_mode="value",replacement="M4A1 Carbine",component_mode="value",component_id="model")
        self.assertEqual(next(effect for effect in self.cards()[0].effects if effect.effect_id==effect_id).replacement,"M4A1 Carbine")
        retire_user_effect(self.db,self.repo.installation_id,effect_id)
        self.assertFalse(next(effect for effect in self.cards()[0].effects if effect.effect_id==effect_id).active)
        with self.assertRaises(ValueError): save_effect_edit(self.db,self.repo.installation_id,effect_id,target_mode="replace")
        with self.assertRaises(ValueError): save_mod_edit(self.db,self.repo.installation_id,card.package_id,friendly_name="x"*257)

    def test_statistics_do_not_claim_automatic_replacement_names(self):
        self.classify(("models/survivors/survivor_producer.mdl",))
        stats=classification_statistics(self.cards())
        self.assertEqual(stats["packages_with_current_target_evidence"],1)
        self.assertEqual(stats["packages_needing_review"],1)
        self.assertEqual(stats["automatically_identified_replacement_identities"],0)

    def test_no_game_modification_or_unscoped_content_reads(self):
        self.classify(("models/survivors/survivor_producer.mdl",))
        before={p.name:p.read_bytes() for p in self.workshop.iterdir()}
        with patch.object(self.access,"open_vpk",side_effect=AssertionError("No content reads during classification")):
            refresh_classification(self.db,self.repo.installation_id);self.cards()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.workshop.iterdir()})
