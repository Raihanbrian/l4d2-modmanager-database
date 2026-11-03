"""M6.3 isolated fixtures only; no live Steam or real game data."""
from dataclasses import replace
from datetime import timedelta
import json
import sqlite3
from threading import Event
import time
from unittest.mock import patch
from contextlib import closing

from .test_catalog import CatalogFixture
from .helpers import FixtureTestCase
from . import test_m61 as m61,test_m62 as m62
from l4d2_mod_db.classification import catalog_cards,refresh_classification
from l4d2_mod_db.catalog_view import branches,matches_branch,row_status,row_replacement
from l4d2_mod_db.conflict_explanations import explain_overlap,RuntimeIncident,NO_OVERLAPS
from l4d2_mod_db.conflicts import analyze_conflicts
from l4d2_mod_db.migrations import upgrade,logical_digest
from l4d2_mod_db.planning import planning_report
from l4d2_mod_db.settings import AppSettings
from l4d2_mod_db.security import ScopedWorkshopAccess
from l4d2_mod_db.storage import CatalogDatabase,validate_schema
from l4d2_mod_db.suggestions import suggest_replacement
from l4d2_mod_db.workshop_metadata import parse_response,cached_metadata,fetch_collection,readable_description,MetadataError


class MigrationAndMetadataTests(CatalogFixture):
    def setUp(self):
        super().setUp();upgrade(self.db,target_version=4);self.add();self.settle()

    def test_v5_preserves_every_v4_value_and_backup(self):
        before={r[0]:self.rows(r[0]) for r in self.db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result=upgrade(self.db,target_version=5);validate_schema(self.db.connection)
        for table,values in before.items():self.assertEqual(self.rows(table),values)
        self.assertEqual(self.scalar('PRAGMA user_version'),5)
        with closing(sqlite3.connect(result.backup_path)) as copy:self.assertEqual(copy.execute('PRAGMA user_version').fetchone()[0],4)
        self.assertIsNone(upgrade(self.db,target_version=5))

    def test_v5_rollback_at_every_fault_stage(self):
        before=logical_digest(self.db.connection)
        for stage in ('after_backup','after_ddl','before_commit'):
            def fail(point):
                if point==stage:raise RuntimeError('fault')
            with self.assertRaises(RuntimeError):upgrade(self.db,target_version=5,fault=fail)
            self.assertEqual(self.scalar('PRAGMA user_version'),4);self.assertEqual(logical_digest(self.db.connection),before);validate_schema(self.db.connection)

    def test_description_preserves_exact_raw_and_restart(self):
        upgrade(self.db,target_version=5);raw='[b]名称[/b] &amp; <i>notes</i>\n[url=https://example.invalid]text[/url]'
        fetch_collection(self.db,self.repo.installation_id,['123'],transport=lambda ids:m61.steam_body(description=raw),now=m61.NOW)
        self.assertEqual(cached_metadata(self.db.connection,['123'])['123']['description_raw'],raw)
        self.db.close();self.db=CatalogDatabase(self.policy)
        self.assertEqual(cached_metadata(self.db.connection,['123'])['123']['description_raw'],raw)
        self.assertEqual(readable_description(raw),'名称 & notes\ntext')

    def test_description_failure_or_absent_field_retains_good_cache(self):
        upgrade(self.db,target_version=5)
        def fetch(body,day):fetch_collection(self.db,self.repo.installation_id,['123'],transport=lambda ids:body,now=m61.NOW+timedelta(days=day))
        fetch(m61.steam_body(description='Good exact text'),0)
        for day,body in enumerate((m61.steam_body(description='x'*65537),m61.steam_body(description=42),m61.steam_body()),2):
            fetch(body,day);self.assertEqual(cached_metadata(self.db.connection,['123'])['123']['description_raw'],'Good exact text')
        fetch(m61.steam_body(description=''),10);self.assertEqual(cached_metadata(self.db.connection,['123'])['123']['description_raw'],'')

    def test_hostile_description_is_inert_and_never_an_identity_source(self):
        raw='<script>steal()</script><img src="https://evil.invalid">[url=https://evil.invalid]Name replaces Rochelle[/url]'
        self.assertEqual(readable_description(raw),'Name replaces Rochelle')
        card=m62.metadata(type('Card',(),{'workshop_id':'123'})(),'Unclear title')
        self.assertEqual(parse_response(m61.steam_body(description=raw),['123'])[0].description_raw,raw)

    def test_cancellation_prevents_new_batches(self):
        upgrade(self.db,target_version=5);calls=[]
        result=fetch_collection(self.db,self.repo.installation_id,['123'],transport=lambda ids:calls.append(ids),cancelled=lambda:True)
        self.assertFalse(calls);self.assertEqual(result['ok'],0)

    def test_cache_survives_offline_and_respects_backoff(self):
        upgrade(self.db,target_version=5)
        fetch_collection(self.db,self.repo.installation_id,['123'],transport=lambda ids:m61.steam_body(description='saved'),now=m61.NOW)
        def offline(ids):raise MetadataError('network_error','offline')
        fetch_collection(self.db,self.repo.installation_id,['123'],transport=offline,now=m61.NOW+timedelta(days=2))
        with patch('l4d2_mod_db.workshop_metadata.request_details',side_effect=AssertionError('unexpected')):
            result=fetch_collection(self.db,self.repo.installation_id,['123'],transport=lambda ids:(_ for _ in ()).throw(AssertionError()),now=m61.NOW+timedelta(days=2,minutes=1))
        self.assertEqual(result['cached'],1);self.assertEqual(cached_metadata(self.db.connection,['123'])['123']['description_raw'],'saved')

    def test_database_rejects_oversize_raw_description(self):
        upgrade(self.db,target_version=5)
        fetch_collection(self.db,self.repo.installation_id,['123'],transport=lambda ids:m61.steam_body(),now=m61.NOW)
        with self.assertRaises(sqlite3.IntegrityError):self.db.connection.execute('UPDATE workshop_metadata SET description_raw=?',('x'*65537,))


class ViewAndExplanationTests(CatalogFixture):
    def setUp(self):super().setUp();upgrade(self.db,target_version=5)

    def card(self,paths):
        self.add(paths=paths);self.settle();refresh_classification(self.db,self.repo.installation_id)
        return catalog_cards(self.db.connection,self.repo.installation_id)[0]

    def finding(self,paths,left=m62.NICK,right=m62.ROCHELLE):
        self.add('1.vpk',(left,*paths));self.add('2.vpk',(right,*paths));self.settle();refresh_classification(self.db,self.repo.installation_id)
        report=analyze_conflicts(self.db.connection,self.repo.installation_id,include_retained=True)
        return report,planning_report(report,[p.package_id for p in report.packages]).findings[0]

    def test_same_survivor_model_is_competition_not_crash(self):
        report,f=self.finding((),m62.ROCHELLE,m62.ROCHELLE);x=explain_overlap(f)
        self.assertEqual(x.category,'Replacement competition');self.assertIn('survivor:rochelle',x.reason);self.assertEqual(x.crash_evidence,'Not verified')

    def test_different_targets_shared_materials(self):
        _,f=self.finding(('materials/shared.vmt','materials/shared.vtf'));x=explain_overlap(f)
        self.assertEqual(x.category,'Shared resources');self.assertIn('targets differ',x.reason);self.assertEqual(x.roles,('material',))

    def test_shared_script_config(self):
        _,f=self.finding(('scripts/a.nut','scripts/weapon_rifle.txt'));x=explain_overlap(f)
        self.assertEqual(x.category,'Needs investigation');self.assertIn('script/config',x.reason)

    def test_shared_model_dependencies(self):
        _,f=self.finding(('models/custom/a.vvd','materials/custom/a.vmt'));x=explain_overlap(f)
        self.assertEqual(x.category,'Needs investigation');self.assertIn('not evaluated',x.reason)

    def test_metadata_only_is_informational(self):
        _,f=self.finding(('addoninfo.txt','addonimage.jpg'));self.assertEqual(explain_overlap(f).category,'Informational')

    def test_unknown_non_utf8_paths_preserve_raw_evidence(self):
        report,f=self.finding(('unknown/a.dat',));before=report.to_dict()
        self.assertIn('unknown',explain_overlap(f).reason);self.assertEqual(report.to_dict(),before)
        path=b'unknown/\xff.dat';x=explain_overlap(replace(f,pair=replace(f.pair,canonical_paths=(path,))))
        self.assertEqual(x.category,'Needs investigation');self.assertEqual(path.hex(),'756e6b6e6f776e2fff2e646174')

    def test_stale_never_current(self):
        _,f=self.finding(('materials/a.vmt',));x=explain_overlap(replace(f,pair=replace(f.pair,evidence_freshness='retained')))
        self.assertEqual(x.freshness,'retained');self.assertIn('refresh first',x.reason)

    def test_reported_crash_is_not_verified_cause(self):
        _,f=self.finding(('materials/a.vmt',));x=explain_overlap(f,RuntimeIncident('crash','Fictional tester','Exited during loading'))
        self.assertEqual(x.category,'Reported runtime problem');self.assertIn('not independently verified',x.crash_evidence);self.assertIn('Causation is not established',x.reason)

    def test_consistency_join_and_visual_report_are_not_crashes(self):
        _,f=self.finding(('materials/a.vmt',))
        for kind in ('consistency','join','visual'):
            x=explain_overlap(f,RuntimeIncident(kind,'Fictional tester','Observed issue'))
            self.assertTrue(x.crash_evidence.startswith('Not verified'));self.assertIn(kind,x.crash_evidence)
        with self.assertRaises(ValueError):RuntimeIncident('crash','','no source')

    def test_no_overlap_never_compatibility_guarantee(self):
        self.assertIn('does not prove',NO_OVERLAPS)
        self.add('1.vpk',('a.txt',));self.add('2.vpk',('b.txt',));self.settle()
        self.assertFalse(analyze_conflicts(self.db.connection,self.repo.installation_id).current_findings)

    def test_all_m4_counts_unchanged_after_explanations(self):
        report,f=self.finding(('materials/a.vmt','addoninfo.txt'));before=report.to_dict()
        for _ in range(10):explain_overlap(f)
        self.assertEqual(report.to_dict(),before);self.assertEqual(report.counts['current_unique_paths'],2)

    def test_status_and_replacement_are_separate(self):
        card=self.card((m62.ROCHELLE,));meta=m62.metadata(card)
        self.assertEqual(row_status(card,meta),'Suggested');self.assertEqual(row_replacement(card,meta),'Violet')
        self.assertEqual(row_status(replace(card,index_status='pending'),meta),'Stale')
        self.assertEqual(row_status(card,{}),'Needs Review')

    def test_component_only_description_requires_matching_title_and_evidence(self):
        for path,title,kind in (('sound/a.wav','New weapon sounds','sound'),('materials/a.vtf','Clean textures','material'),('resource/a.txt','Minimal HUD','ui'),('scripts/a.nut','Gameplay script changes','script')):
            card=self.card((path,));result=suggest_replacement(card,m62.metadata(card,title,()))
            self.assertEqual(result.rule_id,'component-description-'+kind);self.assertIn('does not identify',result.reason)
            self.assertIsNone(suggest_replacement(card,m62.metadata(card,'Mysterious addon',())).name)

    def test_additional_explicit_model_slot_grammar(self):
        card=self.card((m62.ROCHELLE,))
        for title in ('Violet (Rochelle)','Violet replaces Rochelle','Violet for Rochelle'):
            self.assertEqual(suggest_replacement(card,m62.metadata(card,title)).name,'Violet')
        result=suggest_replacement(card,m62.metadata(card,'Custom animations for Rochelle',('Animations',)))
        self.assertEqual(result.rule_id,'animation-title-description');self.assertIn('not evaluated',result.reason)

    def test_hierarchy_local_target_is_not_fabricated_steam_tag(self):
        card=self.card((m62.SCAR,));targets=tuple(dict(r) for r in self.db.connection.execute('SELECT * FROM targets'))
        meta=m62.metadata(card,'FN SCAR-H (SCAR)',('Weapons','Rifle'));before=dict(meta)
        self.assertIn(('Weapons','Rifle','Local target: Desert Rifle / SCAR'),branches(card,meta,targets))
        self.assertTrue(matches_branch(card,meta,targets,'Weapons','Rifle','Local target: Desert Rifle / SCAR'))
        self.assertFalse(matches_branch(card,meta,targets,'Survivors'));self.assertEqual(meta,before)


class PreferencesTests(FixtureTestCase):
    def test_options_survive_restarts_and_root_only_save(self):
        settings=AppSettings(self.workspace/'prefs');access=ScopedWorkshopAccess(self.game)
        settings.save(access,auto_online=False,online_notice_seen=True);settings.save(access)
        fresh=AppSettings(self.workspace/'prefs');self.assertFalse(fresh.options()['auto_online']);self.assertTrue(fresh.options()['online_notice_seen']);self.assertEqual(fresh.load(),str(self.game))

    def test_legacy_v1_upgrades_without_losing_root(self):
        settings=AppSettings(self.workspace/'prefs');settings.policy.prepare()
        settings.path.write_text(json.dumps(dict(version=1,game_root=str(self.game))))
        settings.save(ScopedWorkshopAccess(self.game));self.assertEqual(json.loads(settings.path.read_text())['version'],2)


class M63GuiTests(FixtureTestCase):
    setUp=m62.M62GuiTests.setUp
    tearDown=m62.M62GuiTests.tearDown
    wait=m61.UXTests.wait
    details_window=m61.UXTests.details_window

    def test_simple_default_details_hides_effect_and_component_editor(self):
        window=self.details_window();self.root.update()
        self.assertEqual(len(window.tabs.tabs()),1);self.assertEqual(str(window.tabs.select()),str(window.edit_host))
        self.assertFalse(window.advanced_editor.winfo_manager());self.assertEqual(window.current_effect().component_id,'model')
        window.replacement.set('My corrected replacement');window.save_all();self.wait();self.assertFalse(window.dirty())
        self.assertTrue(any(e.replacement=='My corrected replacement' for e in window.card.effects))

    def test_background_metadata_keeps_draft_and_save_responsive(self):
        entered=Event();release=Event();window=self.details_window();window.replacement.set('Unsent draft')
        def sync(**kwargs):entered.set();release.wait(3);return self.app.state.metadata,dict(ok=0,cached=2,failed=0)
        self.backend.sync_metadata=sync
        try:
            self.app.start_metadata_sync(manual=True);self.assertTrue(entered.wait(1));self.assertFalse(self.app.busy)
            window.save_all();self.wait();self.assertFalse(window.dirty());self.assertFalse(self.app.network_future.done())
        finally:release.set();self.app.network_executor.shutdown(wait=True)
        self.root.update();self.assertTrue(any(e.replacement=='Unsent draft' for e in window.card.effects))

    def test_selected_pair_table_uses_three_readable_columns(self):
        for card in self.app.state.cards:self.app.submit(action=('selection',dict(package_id=card.package_id,selected=True)));self.wait()
        row=self.app.warning_tree.get_children()[0]
        self.assertEqual([self.app.warning_tree.heading(k,'text') for k in ('mods','paths','kind')],['Mod','Conflicts with','Reason'])
        self.assertIn('Shared material/texture',self.app.warning_tree.set(row,'kind'));self.assertFalse(self.app.review_tabs.winfo_manager())
        self.app.warning_tree.selection_set(row);self.app.show_warning();self.assertIn('Crash evidence: Not verified',self.app.warning_text.get('1.0','end'))

    def test_no_live_http_from_injected_test_backend(self):
        self.assertFalse(self.app.auto_online.get())
        with patch.object(self.backend,'sync_metadata',side_effect=AssertionError('HTTP disabled')):self.app.start_metadata_sync()

    def test_hierarchy_resets_empty_choices(self):
        self.app.select_filter(('Weapons','Rifles'));self.root.update()
        self.assertTrue(self.app.catalog_tree.get_children());self.app.select_filter(('Survivors','Rochelle'));self.root.update()
        self.assertEqual(self.app.filter_path,('Survivors','Rochelle'));self.assertEqual(len(self.app.catalog_tree.get_children()),1)

    def test_automatic_tick_is_background_and_can_be_disabled(self):
        called=Event()
        def sync(**kwargs):called.set();return self.app.state.metadata,dict(ok=0,cached=2,failed=0)
        self.backend.sync_metadata=sync;self.app.auto_online.set(True);self.app.metadata_tick()
        self.assertTrue(called.wait(1));self.assertFalse(self.app.busy)
        self.app.network_executor.shutdown(wait=True);self.root.update()
        self.app.auto_online.set(False)
        with patch.object(self.backend,'sync_metadata',side_effect=AssertionError('disabled')):self.app.start_metadata_sync()

    def test_default_details_target_choice_preserves_replacement_draft(self):
        window=self.details_window();window.replacement.set('My draft');window.simple_target.set('Nick');window.assign_simple_target()
        self.assertEqual(window._effect_values()['target_ids'],('survivor:nick',));window.save_all();self.wait()
        effect=window.current_effect();self.assertEqual(effect.target_ids,('survivor:nick',));self.assertEqual(effect.replacement,'My draft')

    def test_multiple_targets_use_plain_labels_and_keep_both_drafts(self):
        self.put('left4dead2/addons/workshop/2.vpk',m62.build_vpk((m62.NICK,m62.ROCHELLE)))
        self.app.open_root(scan=True);self.wait();card=next(c for c in self.app.state.cards if c.workshop_id=='2')
        self.app.catalog_tree.selection_set(card.package_id);self.app.open_details();self.root.update();window=self.app.details[-1]
        for label,name in (('Nick','Fictional Nick replacement'),('Rochelle','Fictional Rochelle replacement')):
            window.edit_target.set(label);window.choose_simple_effect();window.replacement.set(name)
        window.save_all();self.wait()
        replacements={e.target_labels:e.replacement for e in window.card.effects if e.active}
        self.assertEqual(replacements[('Nick',)],'Fictional Nick replacement');self.assertEqual(replacements[('Rochelle',)],'Fictional Rochelle replacement');self.assertFalse(window.dirty())
