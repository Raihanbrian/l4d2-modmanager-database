"""Separate M6 membership, presentation, worker and real Tk widget tests."""

import time
import tkinter as tk
from dataclasses import replace
from unittest.mock import patch

from l4d2_mod_db.classification import catalog_cards,refresh_classification,save_mod_edit
from l4d2_mod_db.conflicts import analyze_conflicts
from l4d2_mod_db.desktop import DesktopApp
from l4d2_mod_db.desktop_model import DesktopBackend,filter_cards,short_summary
from l4d2_mod_db.migrations import upgrade,logical_digest
from l4d2_mod_db.planning import planning_report,selected_packages,set_membership
from l4d2_mod_db.storage import CatalogDatabase,CatalogError
from .test_catalog import CatalogFixture
from .helpers import FixtureTestCase
from .vpk_fixtures import build_vpk


class PlanningTests(CatalogFixture):
    def test_failed_removal_transaction_preserves_membership_until_success(self):
        report=self.collection();package=report.packages[0]
        set_membership(self.db,self.repo.installation_id,package.package_id,True)
        (self.workshop/package.filename).unlink();self.session.poll();self.now+=2.1
        def fail(stage):
            if stage=='before_commit':raise RuntimeError('injected publication failure')
        with self.assertRaises(RuntimeError):self.session.poll(fault=fail)
        self.assertIn(package.package_id,selected_packages(self.db.connection,self.repo.installation_id))
        self.settle()
        self.assertNotIn(package.package_id,selected_packages(self.db.connection,self.repo.installation_id))

    def setUp(self):
        super().setUp();upgrade(self.db,target_version=3)

    def collection(self,resources=True):
        paths=("addoninfo.txt","addonimage.jpg")+(("materials/shared.vmt",) if resources else ())
        for number in range(3):self.add(f"{number}.vpk",paths)
        self.settle();refresh_classification(self.db,self.repo.installation_id)
        return analyze_conflicts(self.db.connection,self.repo.installation_id,include_retained=True)

    def test_one_set_persistence_unique_members_and_restart(self):
        report=self.collection();package_id=report.packages[0].package_id
        set_membership(self.db,self.repo.installation_id,package_id,True)
        set_membership(self.db,self.repo.installation_id,package_id,True)
        self.assertEqual(self.scalar('SELECT count(*) FROM planning_sets'),1)
        self.assertEqual(self.scalar('SELECT count(*) FROM planning_members'),1)
        self.db.close();self.db=CatalogDatabase(self.policy)
        self.assertEqual(selected_packages(self.db.connection,self.repo.installation_id),frozenset((package_id,)))
        set_membership(self.db,self.repo.installation_id,package_id,False)
        self.assertEqual(selected_packages(self.db.connection,self.repo.installation_id),frozenset())

    def test_selected_and_candidate_counts_use_only_selection_context(self):
        report=self.collection();ids=[package.package_id for package in report.packages]
        self.assertTrue(all(value==0 for value in planning_report(report,()).counts.values()))
        one=planning_report(report,ids[:1]);self.assertEqual(one.counts['candidate_attention'],2);self.assertEqual(one.counts['selected_attention'],0)
        two=planning_report(report,ids[:2]);self.assertEqual(two.counts['selected_attention'],1);self.assertEqual(two.counts['candidate_attention'],2)
        self.assertEqual(report.counts['current_package_pairs'],3)

    def test_metadata_only_is_informational_without_changing_raw_evidence(self):
        report=self.collection(resources=False);before=report.to_dict()
        plan=planning_report(report,(report.packages[0].package_id,))
        self.assertEqual(plan.counts['candidate_informational'],2)
        self.assertEqual(plan.counts['candidate_attention'],0)
        self.assertEqual(report.to_dict(),before)
        self.assertTrue(all(len(finding.pair.canonical_paths)==2 for finding in plan.findings))

    def test_similar_nested_metadata_name_is_resource_evidence(self):
        for number in range(2):self.add(f'{number}.vpk',('materials/addonimage.jpg',))
        self.settle();report=analyze_conflicts(self.db.connection,self.repo.installation_id)
        plan=planning_report(report,(report.packages[0].package_id,))
        self.assertEqual(plan.counts['candidate_attention'],1)

    def test_retained_evidence_is_not_red_current_warning(self):
        report=self.collection();self.db.connection.execute("UPDATE packages SET index_status='error'")
        report=analyze_conflicts(self.db.connection,self.repo.installation_id,include_retained=True)
        plan=planning_report(report,(report.packages[0].package_id,))
        self.assertEqual(plan.counts['candidate_retained'],2);self.assertEqual(plan.counts['candidate_attention'],0)
        self.assertFalse(plan.coverage_complete)

    def test_confirmed_removal_clears_membership_but_outage_preserves_it(self):
        report=self.collection();package=report.packages[0]
        set_membership(self.db,self.repo.installation_id,package.package_id,True)
        self.db.connection.execute("UPDATE packages SET presence_status='unavailable',index_status='unavailable' WHERE package_id=?",(package.package_id,))
        self.assertIn(package.package_id,selected_packages(self.db.connection,self.repo.installation_id))
        (self.workshop/package.filename).unlink();self.settle()
        self.assertNotIn(package.package_id,selected_packages(self.db.connection,self.repo.installation_id))
        self.add(package.filename);self.settle()
        self.assertEqual(selected_packages(self.db.connection,self.repo.installation_id),frozenset())

    def test_other_scope_and_removed_package_cannot_be_selected(self):
        report=self.collection()
        with self.assertRaises(CatalogError):set_membership(self.db,'other',report.packages[0].package_id,True)
        self.assertEqual(self.scalar('SELECT count(*) FROM planning_sets'),0)

    def test_v2_to_v3_migration_preserves_manual_fields_and_failure_rolls_back(self):
        # Separate v2 catalog so this tests the actual production upgrade boundary.
        from l4d2_mod_db.storage import StoragePolicy
        from l4d2_mod_db.catalog import CatalogRepository
        with CatalogDatabase(StoragePolicy.isolated_test(self.workspace/'v2',self.access)) as database:
            upgrade(database)
            repository=CatalogRepository(database,self.access)
            self.add(paths=('models/survivors/survivor_producer.mdl',))
            self.settle(self.new_session(repository));refresh_classification(database,repository.installation_id)
            card=catalog_cards(database.connection,repository.installation_id)[0]
            save_mod_edit(database,repository.installation_id,card.package_id,friendly_name='Preserved v2 correction',description='User-owned text')
            original=logical_digest(database.connection)
            def fail(stage):
                if stage=='after_ddl':raise RuntimeError('injected')
            with self.assertRaises(RuntimeError):upgrade(database,target_version=3,fault=fail)
            self.assertEqual(database.connection.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertEqual(logical_digest(database.connection),original)
            upgrade(database,target_version=3)
            self.assertEqual(database.connection.execute('PRAGMA user_version').fetchone()[0],3)
            saved=catalog_cards(database.connection,repository.installation_id)[0]
            self.assertEqual(saved.display_name,'Preserved v2 correction');self.assertEqual(saved.description,'User-owned text')


class BackendTests(FixtureTestCase):
    def test_generation_mismatch_retries_once_then_fails_closed(self):
        import l4d2_mod_db.desktop_model as model
        self.seed();original=model.analyze_conflicts;calls=[]
        def once(*args,**kwargs):
            report=original(*args,**kwargs);calls.append(True)
            return replace(report,coverage=replace(report.coverage,catalog_generation=report.coverage.catalog_generation-1)) if len(calls)==1 else report
        with patch.object(model,'analyze_conflicts',once):state=self.backend().load()
        self.assertEqual(len(calls),2);self.assertTrue(state.overlaps.coverage.complete)
        def always(*args,**kwargs):
            report=original(*args,**kwargs)
            return replace(report,coverage=replace(report.coverage,catalog_generation=report.coverage.catalog_generation-1))
        with patch.object(model,'analyze_conflicts',always):
            with self.assertRaisesRegex(CatalogError,'changed while loading'):self.backend().load()

    def backend(self):return DesktopBackend(str(self.game),test_directory=self.workspace/'appdata',settle_seconds=.01)

    def seed(self):
        self.put('left4dead2/addons/workshop/1.vpk',build_vpk(('models/w_models/weapons/w_rifle_ak47.mdl','materials/shared.vmt')))
        self.put('left4dead2/addons/workshop/2.vpk',build_vpk(('models/survivors/survivor_producer.mdl','materials/shared.vmt')))
        return self.backend().load(scan=True)

    def test_missing_catalog_shows_instruction_not_fake_current_data(self):
        with self.assertRaisesRegex(CatalogError,'Scan / Refresh'):self.backend().load()

    def test_search_category_review_and_index_filters(self):
        state=self.seed()
        self.assertEqual(len(filter_cards(state.cards,'AK-47')),1)
        self.assertEqual(len(filter_cards(state.cards,category='Survivor')),1)
        self.assertEqual(len(filter_cards(state.cards,review='Needs Review')),2)
        self.assertEqual(len(filter_cards(state.cards,index='current')),2)
        self.assertIn('[weapon_rifle_ak47]',short_summary(next(card for card in state.cards if card.workshop_id=='1')))

    def test_fresh_source_change_downgrades_view_without_erasing_saved_evidence(self):
        self.seed();self.put('left4dead2/addons/workshop/1.vpk',b'corrupt')
        state=self.backend().load()
        card=next(card for card in state.cards if card.workshop_id=='1')
        self.assertEqual(card.index_status,'stale');self.assertTrue(card.review_status.startswith('Stale'))
        self.assertFalse(state.overlaps.coverage.complete)

    def test_worker_actions_keep_game_bytes_and_catalog_identity(self):
        state=self.seed();before={path.name:path.read_bytes() for path in self.workshop.iterdir()}
        card=state.cards[0]
        edited=self.backend().load(action=('mod',dict(package_id=card.package_id,friendly_name='Fictional alpha name')))
        self.assertEqual(next(item for item in edited.cards if item.package_id==card.package_id).display_name,'Fictional alpha name')
        self.assertEqual({card.package_id for card in state.cards},{card.package_id for card in edited.cards})
        self.assertEqual(before,{path.name:path.read_bytes() for path in self.workshop.iterdir()})


class DesktopGuiTests(FixtureTestCase):
    def test_failed_refresh_keeps_cached_evidence_visibly_stale(self):
        package_id=self.app.catalog_tree.get_children()[0];self.app.catalog_tree.selection_set(package_id);self.app.toggle_catalog();self.wait()
        original=self.backend.load
        def fail(**kwargs):raise OSError('synthetic storage outage')
        self.backend.load=fail;self.app.submit();self.wait()
        self.assertTrue(all(card.review_status.startswith('Stale') for card in self.app.state.cards))
        self.assertEqual(self.app.state.planning.counts['candidate_attention'],0)
        self.assertEqual(self.app.state.planning.counts['candidate_retained'],1)
        self.backend.load=original;self.app.submit();self.wait()
        self.assertTrue(self.app.state.overlaps.coverage.complete)

    def setUp(self):
        super().setUp()
        self.put('left4dead2/addons/workshop/1.vpk',build_vpk(('models/w_models/weapons/w_rifle_ak47.mdl','materials/shared.vmt','addoninfo.txt')))
        self.put('left4dead2/addons/workshop/2.vpk',build_vpk(('models/survivors/survivor_producer.mdl','materials/shared.vmt','addoninfo.txt')))
        self.backend=DesktopBackend(str(self.game),test_directory=self.workspace/'ui-data',settle_seconds=.01)
        self.backend.load(scan=True)
        self.root=tk.Tk();self.root.withdraw();self.tk_errors=[]
        self.root.report_callback_exception=lambda *error:self.tk_errors.append(error)
        self.app=DesktopApp(self.root,str(self.game),backend_factory=lambda root:self.backend,autoload=False)
        self.app.open_root();self.wait()

    def wait(self):
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            self.root.update()
            if not self.app.busy:
                self.root.update();return
            time.sleep(.01)
        self.fail('GUI worker did not finish')

    def tearDown(self):
        self.wait()
        with patch('l4d2_mod_db.details.messagebox.askyesno',return_value=True):self.app.close()
        self.app.executor.shutdown(wait=True)
        self.assertEqual(self.tk_errors,[])
        super().tearDown()

    def test_startup_navigation_search_filters_and_neutral_catalog(self):
        self.assertEqual(len(self.app.catalog_tree.get_children()),2)
        self.assertEqual(self.app.notebook.tabs().__len__(),2)
        self.app.notebook.select(self.app.plan_tab);self.root.update()
        self.assertEqual(len(self.app.plan_tree.get_children()),0)  # M6.1: selected mods only.
        self.app.search.set('AK-47');self.root.update();self.assertEqual(len(self.app.catalog_tree.get_children()),1)
        self.app.search.set('');self.app.category.set('Survivor');self.root.update()
        self.assertEqual(len(self.app.catalog_tree.get_children()),1)
        self.assertTrue(all(not self.app.catalog_tree.item(item,'tags') for item in self.app.catalog_tree.get_children()))

    def test_detail_edit_save_and_evidence_navigation(self):
        package_id=self.app.catalog_tree.get_children()[0];self.app.catalog_tree.selection_set(package_id);self.app.open_details()
        self.root.update();window=self.app.details[-1]
        window.name.set('Fictional M4A1 alpha');window.description.insert('1.0','A synthetic description');window.save_mod_button.invoke();self.wait()
        self.assertEqual(next(card for card in self.app.state.cards if card.package_id==package_id).display_name,'Fictional M4A1 alpha')
        window.target_mode.set('Assign selected targets');window.target_list.selection_clear(0,'end')
        target_index=next(number for number,target in enumerate(self.app.state.targets) if target['target_id']=='weapon:weapon_rifle_ak47')
        window.target_list.selection_set(target_index)
        window.replacement_mode.set('Named replacement');window.replacement.set('M4A1 Carbine');window.component.set('Model')
        window.save_effect_button.invoke();self.wait()
        card=next(card for card in self.app.state.cards if card.package_id==package_id)
        self.assertTrue(any(effect.replacement=='M4A1 Carbine' for effect in card.effects))
        window.category_mode.set('Assign selected categories');window.category_list.selection_clear(0,'end')
        category_index=next(number for number,category in enumerate(self.app.state.categories) if category['category_id']=='weapon')
        window.category_list.selection_set(category_index);window.save_mod_button.invoke();self.wait()
        displayed=self.app.catalog_tree.set(package_id,'category')
        self.assertIn('Weapon',displayed)
        self.assertIn('Model',window.card.components)  # Components now belong in Details.
        window.show_technical();self.root.update()
        self.assertIn('Canonical hex:',window.evidence_text.get('1.0','end'))

    def test_selection_candidate_warning_details_and_removal(self):
        package_id=self.app.catalog_tree.get_children()[0];self.app.catalog_tree.selection_set(package_id);self.app.toggle_catalog();self.wait()
        self.assertIn(package_id,self.app.state.planning.selected_ids)
        self.assertEqual(self.app.state.planning.counts['candidate_attention'],1)
        self.app.show_candidates.set(True);self.app.toggle_candidates()
        warning=self.app.candidate_tree.get_children()[0];self.app.candidate_tree.selection_set(warning);self.app.show_warning(tree=self.app.candidate_tree)
        self.assertIn('materials/shared.vmt',self.app.warning_text.get('1.0','end'))
        self.assertTrue(all(not self.app.catalog_tree.item(item,'tags') for item in self.app.catalog_tree.get_children()))
        self.app.plan_tree.selection_set(package_id);self.app.toggle_plan();self.wait()
        self.assertFalse(self.app.state.planning.selected_ids)

    def test_background_worker_leaves_tk_main_thread_responsive(self):
        original=self.backend.load
        def slow(**kwargs):time.sleep(.15);return original(**kwargs)
        self.backend.load=slow
        heartbeat=[];self.root.after(20,lambda:heartbeat.append(True));self.app.submit();self.wait()
        self.assertTrue(heartbeat)

    def test_form_validation_error_retains_unsaved_input(self):
        self.app.catalog_tree.selection_set(self.app.catalog_tree.get_children()[0]);self.app.open_details();window=self.app.details[-1]
        window.name.set('x'*257);window.save_mod();self.wait()
        self.assertEqual(window.name.get(),'x'*257)
        self.assertIn('256',window.notice.get())

    def test_metadata_only_context_is_not_rendered_red(self):
        for name in ('1.vpk','2.vpk'):self.put('left4dead2/addons/workshop/'+name,build_vpk(('addoninfo.txt','addonimage.jpg')))
        self.app.open_root(scan=True);self.wait()
        package_id=self.app.catalog_tree.get_children()[0];self.app.catalog_tree.selection_set(package_id);self.app.toggle_catalog();self.wait()
        self.assertEqual(self.app.state.planning.counts['candidate_informational'],1)
        self.assertEqual(self.app.state.planning.counts['candidate_attention'],0)
        self.assertTrue(all('attention' not in self.app.plan_tree.item(item,'tags') for item in self.app.plan_tree.get_children()))
        self.assertEqual(self.app.state.overlaps.counts['current_package_pairs'],1)
