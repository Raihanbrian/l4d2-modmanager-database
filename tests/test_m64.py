"""M6.4 filters/editor/release regressions. Synthetic roots and mocked HTTP only."""
from dataclasses import replace
from unittest.mock import patch
import json
from pathlib import Path
import shutil
import zipfile

from .test_catalog import CatalogFixture
from .helpers import FixtureTestCase
from . import test_m61 as m61,test_m62 as m62
from l4d2_mod_db.catalog_filters import filter_evidence,filter_options,matches_filter,filter_caption
from l4d2_mod_db.classification import catalog_cards,refresh_classification,save_effect_edit,save_mod_edit
from l4d2_mod_db.migrations import upgrade,logical_digest


class UnifiedFilterTests(CatalogFixture):
    def setUp(self):super().setUp();upgrade(self.db,target_version=5)

    def card(self,paths=(m62.ROCHELLE,),name='123.vpk'):
        self.add(name,paths);self.settle();refresh_classification(self.db,self.repo.installation_id)
        return next(c for c in catalog_cards(self.db.connection,self.repo.installation_id) if c.filename==name)

    @property
    def targets(self):return tuple(dict(r) for r in self.db.connection.execute('SELECT * FROM targets'))

    def test_rochelle_matches_local_and_published_sources_without_duplicate_nodes(self):
        card=self.card();meta=m62.metadata(card)
        evidence=[e for e in filter_evidence(card,meta,self.targets) if e.path==('Survivors','Rochelle')]
        self.assertEqual({e.source for e in evidence},{'local target','Steam tag'})
        options=filter_options((card,),{card.workshop_id:meta},self.targets)
        self.assertIn(('Survivors','Rochelle'),options);self.assertTrue(matches_filter(card,meta,self.targets,('Survivors',)))
        self.assertEqual(filter_caption(('Survivors','Rochelle')),'Survivors › Rochelle')

    def test_desert_rifle_umbrella_and_specific_choice(self):
        card=self.card((m62.SCAR,));meta=m62.metadata(card,'FN SCAR-H (SCAR)',('Weapons','Rifle'))
        for path in ((),('Weapons',),('Weapons','Rifles'),('Weapons','Rifles','Desert Rifle')):self.assertTrue(matches_filter(card,meta,self.targets,path))
        self.assertFalse(matches_filter(card,meta,self.targets,('Survivors',)))
        self.assertFalse(matches_filter(card,meta,self.targets,('Weapons','Shotguns')))

    def test_tags_can_support_related_filter_but_do_not_assign_original_target(self):
        card=self.card();meta=m62.metadata(card,tags=('Survivors','Nick'));before=logical_digest(self.db.connection)
        for name in ('Rochelle','Nick'):self.assertTrue(matches_filter(card,meta,self.targets,('Survivors',name)))
        self.assertEqual({t for e in card.effects for t in e.target_ids},{'survivor:rochelle'})
        self.assertEqual(logical_digest(self.db.connection),before)

    def test_unknown_and_unsupported_tags_are_not_fabricated_targets(self):
        card=self.card(('unknown/a.bin',));meta=m62.metadata(card,'Made-up weapon',('NewGun 2000','Rochelle-ish'))
        self.assertTrue(matches_filter(card,meta,self.targets,('Miscellaneous',)))
        self.assertFalse(matches_filter(card,meta,self.targets,('Survivors','Rochelle')))
        self.assertFalse(any('NewGun' in str(path) for path in filter_options((card,),{card.workshop_id:meta},self.targets)))

    def test_multiple_targets_and_categories_remain_discoverable(self):
        card=self.card((m62.NICK,m62.ROCHELLE,m62.SCAR,'resource/a.txt'));meta=m62.metadata(card,tags=('UI','Weapons','Survivors'))
        for path in (('Survivors','Nick'),('Survivors','Rochelle'),('Weapons','Rifles','Desert Rifle'),('UI',)):
            self.assertTrue(matches_filter(card,meta,self.targets,path),path)

    def test_user_categories_take_precedence_without_erasing_published_tags(self):
        card=self.card();meta=m62.metadata(card);save_mod_edit(self.db,self.repo.installation_id,card.package_id,category_mode='replace',category_ids=('sound',))
        card=catalog_cards(self.db.connection,self.repo.installation_id)[0]
        self.assertTrue(matches_filter(card,meta,self.targets,('Sounds',)));self.assertFalse(matches_filter(card,meta,self.targets,('Survivors',)))
        self.assertEqual(meta['tags'],('Survivors','Rochelle'))

    def test_user_target_source_is_preserved(self):
        card=self.card();effect=next(e for e in card.effects if e.target_ids)
        save_effect_edit(self.db,self.repo.installation_id,effect.effect_id,target_mode='replace',target_ids=('survivor:nick',))
        card=catalog_cards(self.db.connection,self.repo.installation_id)[0]
        evidence=filter_evidence(card,{},self.targets);self.assertTrue(any(e.source=='user target' and e.path==('Survivors','Nick') for e in evidence))

    def test_infected_types_and_melee_tag_do_not_invent_canonical_ids(self):
        card=self.card(('unknown/a.bin',));meta=m62.metadata(card,tags=('Infected','Hunter','Tank','Melee'))
        for path in (('Infected','Special Infected','Hunter'),('Infected','Tank'),('Weapons','Melee')):self.assertTrue(matches_filter(card,meta,self.targets,path))
        self.assertFalse(any(e.target_ids for e in card.effects))

    def test_stale_mods_remain_discoverable_but_not_new_current_evidence(self):
        card=replace(self.card(),index_status='stale');self.assertTrue(matches_filter(card,{},self.targets,('Survivors','Rochelle')))

    def test_options_hide_empty_groups_and_keep_all_mods(self):
        card=self.card();options=filter_options((card,),{},self.targets)
        self.assertIn((),options);self.assertNotIn(('Weapons','Rifles'),options);self.assertNotIn(('Infected',),options)
        self.assertEqual(filter_options((),{},self.targets),{():()})

    def test_filtering_is_readonly_stable_and_preserves_byte_safe_assets(self):
        card=self.card((m62.ROCHELLE,'materials/qq.vmt'));before=logical_digest(self.db.connection)
        first=filter_evidence(card,m62.metadata(card),self.targets)
        for _ in range(5):self.assertEqual(filter_evidence(card,m62.metadata(card),self.targets),first)
        self.assertEqual(before,logical_digest(self.db.connection));self.assertEqual(self.db.connection.execute('PRAGMA user_version').fetchone()[0],5)


class M64GuiTests(FixtureTestCase):
    setUp=m62.M62GuiTests.setUp
    tearDown=m62.M62GuiTests.tearDown
    wait=m61.UXTests.wait
    details_window=m61.UXTests.details_window

    def test_single_chooser_has_no_technical_filter_labels(self):
        self.app.show_category_chooser();self.root.update();chooser=self.app.category_chooser
        captions=[chooser.tree.item(node,'text') for node in chooser.paths]
        self.assertIn('All Mods',captions);self.assertIn('All Survivors',captions);self.assertIn('Rochelle',captions)
        self.assertFalse(any('Local target:' in label or 'Steam tag:' in label for label in captions))
        self.assertFalse(hasattr(self.app,'subcategory_combo'));self.assertFalse(hasattr(self.app,'exact_target_combo'))

    def test_apply_specific_target_and_clear_to_all(self):
        self.app.show_category_chooser();chooser=self.app.category_chooser
        chooser.tree.selection_set(chooser.nodes[('Survivors','Rochelle')]);chooser.apply();self.root.update()
        self.assertEqual(len(self.app.catalog_tree.get_children()),1);self.assertEqual(self.app.filter_path,('Survivors','Rochelle'))
        self.app.select_filter(());self.assertEqual(len(self.app.catalog_tree.get_children()),2)

    def test_cancel_chooser_does_not_change_filter_or_details_draft(self):
        window=self.details_window();window.replacement.set('Keep replacement draft');self.app.show_category_chooser();self.app.category_chooser.window.destroy()
        self.assertEqual(self.app.filter_path,());self.assertEqual(window.replacement.get(),'Keep replacement draft')

    def test_filter_cancel_left_and_use_filter_right(self):
        self.root.deiconify();self.app.show_category_chooser();self.root.update();chooser=self.app.category_chooser
        self.assertLess(chooser.cancel_button.winfo_rootx(),chooser.apply_button.winfo_rootx())
        chooser.tree.selection_set(chooser.nodes[('Survivors','Rochelle')]);chooser.apply_button.invoke();self.root.update()
        self.assertEqual(self.app.filter_path,('Survivors','Rochelle'))
        self.app.show_category_chooser();self.app.category_chooser.cancel_button.invoke();self.root.update()
        self.assertEqual(self.app.filter_path,('Survivors','Rochelle'))

    def select_all_for_plan(self):
        for card in self.app.state.cards:
            self.app.submit(action=('selection',dict(package_id=card.package_id,selected=True)));self.wait()

    def test_only_conflicting_selected_mods_red_and_deselection_clears_highlight(self):
        self.put('left4dead2/addons/workshop/3.vpk',m62.build_vpk(('resource/unique_hud.txt','addoninfo.txt')))
        self.app.open_root(scan=True);self.wait();self.select_all_for_plan()
        by_id={card.workshop_id:card.package_id for card in self.app.state.cards}
        for workshop_id in ('1','2'):self.assertIn('attention',self.app.plan_tree.item(by_id[workshop_id],'tags'))
        self.assertFalse(self.app.plan_tree.item(by_id['3'],'tags'))
        red,green,blue=self.root.winfo_rgb(self.app.plan_tree.tag_configure('attention','background'))
        self.assertGreater(red,green);self.assertEqual(green,blue)
        self.assertTrue(all(not self.app.catalog_tree.item(row,'tags') for row in self.app.catalog_tree.get_children()))
        self.app.submit(action=('selection',dict(package_id=by_id['2'],selected=False)));self.wait()
        self.assertGreater(self.app.state.planning.counts['candidate_attention'],0)
        self.assertEqual(self.app.state.planning.counts['selected_informational'],1)
        self.app.include_info.set(True);self.app.render_plan()
        self.assertTrue(all(not self.app.plan_tree.item(row,'tags') for row in self.app.plan_tree.get_children()))

    def test_retained_evidence_is_not_colored_as_current_conflict(self):
        from l4d2_mod_db.desktop_model import uncertain_state
        self.select_all_for_plan();self.assertEqual(self.app.state.planning.counts['selected_attention'],1)
        self.app.state=uncertain_state(self.app.state);self.app.render_plan()
        self.assertEqual(self.app.state.planning.counts['selected_attention'],0)
        self.assertEqual(self.app.state.planning.counts['selected_retained'],1)
        for row in self.app.plan_tree.get_children():
            self.assertEqual(self.app.plan_tree.item(row,'tags'),('retained',))
            self.assertIn('Refresh stale',self.app.plan_tree.set(row,'warning'))
        self.assertFalse(self.app.plan_tree.tag_configure('retained','background'))

    def test_missing_filter_matches_remain_zero_until_user_clears(self):
        self.app.select_filter(('Infected','Tank'));self.assertFalse(self.app.catalog_tree.get_children())
        self.app.render_catalog();self.assertEqual(self.app.filter_path,('Infected','Tank'));self.app.select_filter(());self.assertEqual(len(self.app.catalog_tree.get_children()),2)

    def test_custom_catalog_name_hidden_and_separate_from_replacement(self):
        window=self.details_window();self.root.update()
        self.assertFalse(window.more_options.winfo_manager());self.assertTrue(window.primary.winfo_manager())
        window.toggle_more();window.name.set('My catalog nickname');window.toggle_more();window.replacement.set('My actual replacement')
        self.assertEqual(window.name.get(),'My catalog nickname');window.save_all();self.wait()
        self.assertEqual(window.card.display_name,'My catalog nickname');self.assertTrue(any(e.replacement=='My actual replacement' for e in window.card.effects))
        self.assertFalse(window.dirty());self.assertFalse(window.more_options.winfo_manager())

    def test_official_steam_title_not_replaced_by_custom_catalog_name(self):
        from l4d2_mod_db.storage import CatalogDatabase,StoragePolicy
        from l4d2_mod_db.security import ScopedWorkshopAccess
        from l4d2_mod_db.workshop_metadata import fetch_collection
        card=next(c for c in self.app.state.cards if c.workshop_id=='2');meta=m62.metadata(card)
        with CatalogDatabase(StoragePolicy.isolated_test(self.workspace/'data',ScopedWorkshopAccess(self.game))) as db:
            installation=db.connection.execute('SELECT installation_id FROM installations').fetchone()[0]
            fetch_collection(db,installation,['2'],transport=lambda ids:m61.steam_body(ids,title=meta['title']))
        self.app.open_root();self.wait()
        self.app.catalog_tree.selection_set(card.package_id);self.app.open_details();self.root.update();window=self.app.details[-1]
        window.name.set('Custom name');window.save_all();self.wait()
        self.assertEqual(window.title.cget('text'),meta['title']);self.assertEqual(self.app.catalog_tree.set(card.package_id,'steam'),meta['title'])

    def test_replacement_first_layout_more_options_and_draft_survive_refresh(self):
        window=self.details_window();window.toggle_more();window.name.set('Keep custom draft');window.replacement.set('Keep replacement draft');window.description.insert('1.0','Keep description')
        window.toggle_more();self.app.open_root();self.wait()
        self.assertEqual(window.name.get(),'Keep custom draft');self.assertEqual(window.replacement.get(),'Keep replacement draft');self.assertEqual(window.description.get('1.0','end-1c'),'Keep description')
        self.assertTrue(window.dirty());self.assertFalse(window.advanced_editor.winfo_manager())

    def test_use_suggestion_stays_unconfirmed_until_single_save(self):
        card=next(c for c in self.app.state.cards if c.workshop_id=='2');self.app.state.metadata[card.workshop_id]=m62.metadata(card)
        self.app.catalog_tree.selection_set(card.package_id);self.app.open_details();self.root.update();window=self.app.details[-1]
        self.assertIn('Suggested',window.replacement_status.get());window.use_suggestion();self.assertEqual(window.replacement.get(),'Violet');self.assertIsNone(window.current_effect().user_edit)
        window.save_all();self.wait();self.assertIn('Confirmed',window.replacement_status.get());self.assertEqual(window.current_effect().replacement,'Violet')

    def test_small_viewport_save_visible_with_more_options_collapsed(self):
        self.root.deiconify();window=self.details_window();window.window.geometry('800x510');self.root.update()
        self.assertTrue(window.save_button.winfo_ismapped());self.assertLessEqual(window.save_button.winfo_rooty()+window.save_button.winfo_height(),window.window.winfo_rooty()+window.window.winfo_height())

    def test_unavailable_root_keeps_data_and_reselection_recovers(self):
        ids={c.package_id for c in self.app.state.cards};self.app.backend_factory=lambda root:__import__('l4d2_mod_db.desktop_model',fromlist=['DesktopBackend']).DesktopBackend(root,test_directory=self.workspace/'data',settle_seconds=.01)
        self.app.path.set(str(self.workspace/'missing-game'));self.app.open_root();self.wait();self.assertIn('Change Game Folder',self.app.status.get())
        self.app.path.set(str(self.game));self.app.open_root();self.wait();self.assertEqual({c.package_id for c in self.app.state.cards},ids)

    def unindexed_window(self):
        self.put('left4dead2/addons/workshop/3.vpk',b'corrupt fixture');self.app.open_root(scan=True);self.wait()
        card=next(c for c in self.app.state.cards if c.workshop_id=='3');self.assertFalse(card.effects)
        self.app.catalog_tree.selection_set(card.package_id);self.app.open_details();self.root.update();return self.app.details[-1]

    def test_unindexed_corrupt_package_disables_unsaveable_replacement_but_saves_notes(self):
        window=self.unindexed_window();self.assertEqual(str(window.replacement_entry['state']),'disabled');self.assertEqual(str(window.simple_target_combo['state']),'disabled')
        self.assertIn('No indexed change',window.replacement_status.get());window.description.insert('1.0','Wait for a valid Workshop download');window.save_all();self.wait()
        self.assertEqual(window.card.description,'Wait for a valid Workshop download');self.assertFalse(window.dirty())

    def test_recovered_index_reenables_replacement_editing(self):
        window=self.unindexed_window();self.put('left4dead2/addons/workshop/3.vpk',m62.build_vpk((m62.ROCHELLE,)))
        self.app.open_root(scan=True);self.wait();self.assertEqual(str(window.replacement_entry['state']),'normal');self.assertTrue(window.current_effect().active)
        window.replacement.set('Fictional recovered replacement');window.save_all();self.wait();self.assertEqual(window.current_effect().replacement,'Fictional recovered replacement')


class PublicSourceTests(FixtureTestCase):
    def test_public_allowlist_excludes_owner_artifacts_and_only_allows_demo_database(self):
        from tools.prepare_source import source_files
        from .helpers import PROJECT_ROOT
        paths=[p.relative_to(PROJECT_ROOT).as_posix() for p in source_files(PROJECT_ROOT)]
        self.assertIn('README.md',paths);self.assertIn('tests/test_m64.py',paths);self.assertIn('docs/PRIVACY.md',paths)
        self.assertIn('examples/m3-demo/fictional_records.json',paths);self.assertIn('examples/m3-demo/README.md',paths)
        self.assertEqual([p for p in paths if p.endswith('.sqlite3')],['examples/m3-demo/m3_demo.sqlite3'])
        self.assertFalse(any(p.startswith(('M63/','Handoffs/','.test-tmp/','docs/screenshots/m63/','docs/internal/')) or p in ('DECISIONS.md','TEST_RESULTS.md') for p in paths))

    def test_source_zip_is_reproducible_and_has_no_absolute_paths(self):
        from tools.prepare_source import prepare
        from .helpers import PROJECT_ROOT
        first=prepare(PROJECT_ROOT,self.workspace/'out');second=prepare(PROJECT_ROOT,self.workspace/'out')
        self.assertEqual(first['sha256'],second['sha256'])
        with zipfile.ZipFile(second['archive']) as archive:
            self.assertIsNone(archive.testzip());self.assertTrue(all(not p.startswith(('/','\\')) and ':' not in p and '..' not in Path(p).parts for p in archive.namelist()))
            self.assertTrue(any(p.endswith('/PUBLIC_SOURCE_MANIFEST.json') for p in archive.namelist()))

    def test_source_export_rejects_user_specific_literal_paths(self):
        from tools.prepare_source import source_files
        from .helpers import PROJECT_ROOT
        copy=self.workspace/'public-copy';copy.mkdir()
        for source in source_files(PROJECT_ROOT):
            target=copy/source.relative_to(PROJECT_ROOT);target.parent.mkdir(exist_ok=True,parents=True);shutil.copy2(source,target)
        (copy/'README.md').write_text('C:'+'\\Users'+'\\User'+'\\Private',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'Owner-specific path'):source_files(copy)

    def test_gitignore_has_explicit_private_game_and_generated_boundaries(self):
        from .helpers import PROJECT_ROOT
        text=(PROJECT_ROOT/'.gitignore').read_text()
        for pattern in ('.test-tmp/','dist/','build/','*.vpk','*.rar','/Handoffs/','/M[0-9]*/','/preferences.json','/docs/screenshots/m63/','!/M3_SAMPLE_DATA.md'):self.assertIn(pattern,text)

    def test_unavailable_qa_cannot_accept_production_profile(self):
        from l4d2_mod_db.portable_qa import run
        with patch.dict('os.environ',{'LOCALAPPDATA':str(self.workspace)}):
            with self.assertRaisesRegex(Exception,'dedicated'):run(str(self.game),unavailable=True)

    def test_review_fixture_is_fictional_and_refuses_overwrite(self):
        from tools.review_fixture import make_game,DEMO
        game=make_game(self.workspace/'fictional-fixture');self.assertEqual(len(list((game/'left4dead2/addons/workshop').glob('*.vpk'))),5)
        self.assertTrue(all(name[0] for name in DEMO.values()))
        with self.assertRaises(ValueError):make_game(game)
