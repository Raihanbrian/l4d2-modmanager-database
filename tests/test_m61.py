"""M6.1 isolated UX, preview, migration and mocked Steam regressions. No live HTTP."""

from datetime import datetime,timedelta,timezone
from io import BytesIO
import json
import sqlite3
import time
import tkinter as tk
from unittest.mock import patch,Mock

from l4d2_mod_db.classification import catalog_cards,refresh_classification,save_mod_edit
from l4d2_mod_db.desktop import DesktopApp
from l4d2_mod_db.desktop_model import DesktopBackend
from l4d2_mod_db.editing import save_details
from l4d2_mod_db.migrations import upgrade,logical_digest
from l4d2_mod_db.previews import PreviewCache,Image
from l4d2_mod_db.presentation import category_labels,original_name,replacement_name,steam_name,metadata_discrepancies
from l4d2_mod_db.scanner import discover
from l4d2_mod_db.security import PathPolicyError,ScopedWorkshopAccess
from l4d2_mod_db.settings import AppSettings
from l4d2_mod_db.storage import CatalogError,CatalogDatabase
from l4d2_mod_db.workshop_metadata import valid_id,workshop_url,parse_response,request_details,MetadataError,fetch_collection,cached_metadata,MAX_RESPONSE
from .test_catalog import CatalogFixture
from . import test_m6 as m6
from .helpers import FixtureTestCase
from .vpk_fixtures import build_vpk


NOW=datetime(2026,10,29,9,tzinfo=timezone.utc)


def steam_body(ids=('123',),*,title='Exact “Violet” 名称 [Rochelle]',tags=('Survivors','Rochelle','Models','Models'),**fields):
    items=[dict(publishedfileid=key,result=1,consumer_app_id=550,visibility=0,title=title,tags=[{'tag':tag} for tag in tags],**fields) for key in ids]
    return json.dumps({'response':{'resultcount':len(items),'publishedfiledetails':items}},ensure_ascii=False).encode('utf8')


class ResponseTests(FixtureTestCase):
    def test_exact_unicode_title_and_case_sensitive_tags(self):
        item=parse_response(steam_body(tags=('Models','models',' 日本語 ')),['123'])[0]
        self.assertEqual(item.title,'Exact “Violet” 名称 [Rochelle]');self.assertEqual(item.tags,('Models','models',' 日本語 '))

    def test_invalid_ids_links_and_uint64_limits(self):
        for value in ('0','01','١٢٣','-1','1?x=y','18446744073709551616',None):
            self.assertFalse(valid_id(value));self.assertIsNone(workshop_url(value))
        self.assertEqual(workshop_url('2829092183'),'https://steamcommunity.com/sharedfiles/filedetails/?id=2829092183')

    def test_non_success_and_nonpublic_are_uncertain_not_deleted(self):
        payload=json.loads(steam_body());item=payload['response']['publishedfiledetails'][0];item['result']=9
        result=parse_response(json.dumps(payload).encode(),['123'])[0]
        self.assertEqual(result.status,'unavailable');self.assertIn('does not establish',result.diagnostic)
        item['result']=1;item['visibility']=2
        self.assertEqual(parse_response(json.dumps(payload).encode(),['123'])[0].status,'unavailable')

    def test_wrong_app_and_malformed_title_are_not_accepted(self):
        payload=json.loads(steam_body());item=payload['response']['publishedfiledetails'][0];item['consumer_app_id']=730
        self.assertEqual(parse_response(json.dumps(payload).encode(),['123'])[0].status,'wrong_app')
        item['consumer_app_id']=550;item['title']='x'*4097
        self.assertEqual(parse_response(json.dumps(payload).encode(),['123'])[0].status,'malformed')
        item['result']=2**100
        self.assertEqual(parse_response(json.dumps(payload).encode(),['123'])[0].status,'malformed')

    def test_malformed_envelopes_duplicate_or_unrequested_ids_fail_closed(self):
        for body in (b'<html>error</html>',b'{}',b'\xff',b'['*2000,steam_body(('123','123')),steam_body(('456',))):
            with self.assertRaises(MetadataError):parse_response(body,['123'])
        with self.assertRaises(MetadataError):parse_response(b' '* (MAX_RESPONSE+1),['123'])

    def test_network_fixed_https_and_no_redirect(self):
        response=Mock(status=302);connection=Mock();connection.getresponse.return_value=response
        with patch('l4d2_mod_db.workshop_metadata.http.client.HTTPSConnection',return_value=connection) as factory:
            with self.assertRaises(MetadataError):request_details(['123'])
        self.assertEqual(factory.call_args.args[0],'api.steampowered.com');self.assertEqual(factory.call_args.kwargs['timeout'],8)
        self.assertEqual(connection.request.call_args.args[:2],('POST','/ISteamRemoteStorage/GetPublishedFileDetails/v1/'));connection.close.assert_called_once()

    def test_http_normal_body_and_stream_overflow_are_bounded(self):
        for body,success in ((steam_body(),True),(b'x'*(MAX_RESPONSE+1),False)):
            response=Mock(status=200);response.getheader.side_effect=lambda key,default=None:'application/json' if key=='Content-Type' else default
            response.read.side_effect=[body,b''];connection=Mock();connection.getresponse.return_value=response
            with patch('l4d2_mod_db.workshop_metadata.http.client.HTTPSConnection',return_value=connection):
                if success:self.assertEqual(request_details(['123']),body)
                else:
                    with self.assertRaises(MetadataError):request_details(['123'])
            headers=connection.request.call_args.args[3];self.assertNotIn('Authorization',headers);self.assertNotIn('Cookie',headers)

    def test_no_network_at_catalog_start_or_local_refresh(self):
        self.put('left4dead2/addons/workshop/1.vpk',build_vpk(('a.txt',)))
        with patch('l4d2_mod_db.workshop_metadata.http.client.HTTPSConnection',side_effect=AssertionError('Unexpected HTTP')):
            backend=DesktopBackend(str(self.game),test_directory=self.workspace/'offline',settle_seconds=.01)
            first=backend.load(scan=True);second=backend.load();self.assertEqual(first.cards[0].package_id,second.cards[0].package_id)

    def test_http_429_timeout_content_encoding_and_response_size(self):
        for status,headers in ((429,{}),(200,{'Content-Length':str(MAX_RESPONSE+1)}),(200,{'Content-Encoding':'gzip'})):
            response=Mock(status=status);response.getheader.side_effect=lambda key,default=None:headers.get(key,default)
            connection=Mock();connection.getresponse.return_value=response
            with patch('l4d2_mod_db.workshop_metadata.http.client.HTTPSConnection',return_value=connection):
                with self.assertRaises(MetadataError):request_details(['123'])
        connection=Mock();connection.request.side_effect=TimeoutError()
        with patch('l4d2_mod_db.workshop_metadata.http.client.HTTPSConnection',return_value=connection):
            with self.assertRaisesRegex(MetadataError,'could not be reached'):request_details(['123'])


class MetadataPersistenceTests(CatalogFixture):
    def setUp(self):
        super().setUp();upgrade(self.db,target_version=4);self.add(paths=('models/survivors/survivor_producer.mdl','materials/shared.vmt'))
        self.settle();refresh_classification(self.db,self.repo.installation_id)

    def fetch(self,body=None,now=NOW,ids=('123',)):
        return fetch_collection(self.db,self.repo.installation_id,ids,transport=lambda requested:body or steam_body(requested),now=now,pause=lambda seconds:None)

    def test_multiple_tags_unique_links_and_restart_persistence(self):
        self.fetch();self.fetch();self.assertEqual(self.scalar('SELECT count(*) FROM workshop_item_tags'),3)
        identity=self.scalar('SELECT package_id FROM packages');self.db.close();self.db=CatalogDatabase(self.policy)
        cached=cached_metadata(self.db.connection,['123'])['123']
        self.assertEqual(cached['title'],'Exact “Violet” 名称 [Rochelle]');self.assertEqual(identity,self.scalar('SELECT package_id FROM packages'))

    def test_changed_title_and_tags_atomically_replace_only_steam_values(self):
        card=catalog_cards(self.db.connection,self.repo.installation_id)[0];save_mod_edit(self.db,self.repo.installation_id,card.package_id,friendly_name='My correction')
        self.fetch();self.fetch(steam_body(title='New exact title!',tags=('UI','Sounds')),now=NOW+timedelta(days=2))
        cached=cached_metadata(self.db.connection,['123'])['123'];self.assertEqual(cached['title'],'New exact title!');self.assertEqual(cached['tags'],('Sounds','UI'))
        self.assertEqual(catalog_cards(self.db.connection,self.repo.installation_id)[0].display_name,'My correction')

    def test_offline_failed_fetch_preserves_last_good_title_tags_timestamp(self):
        self.fetch();before=cached_metadata(self.db.connection,['123'])['123']
        def offline(ids):raise MetadataError('network_error','offline fixture')
        fetch_collection(self.db,self.repo.installation_id,['123'],transport=offline,now=NOW+timedelta(days=2))
        after=cached_metadata(self.db.connection,['123'])['123']
        for key in ('title','tags','last_success_at'):self.assertEqual(before[key],after[key])
        self.assertEqual(after['retrieval_status'],'network_error')

    def test_inaccessible_wrong_app_and_malformed_never_erase_cache(self):
        self.fetch()
        for number,change in enumerate(({'result':9},{'consumer_app_id':730},{'title':None})):
            payload=json.loads(steam_body());payload['response']['publishedfiledetails'][0].update(change)
            self.fetch(json.dumps(payload).encode(),now=NOW+timedelta(days=number+2))
            self.assertIsNotNone(cached_metadata(self.db.connection,['123'])['123']['title']);self.assertEqual(self.scalar('SELECT count(*) FROM workshop_item_tags'),3)

    def test_scope_deduplication_and_cooldown(self):
        calls=[]
        def transport(ids):calls.append(ids);return steam_body(ids)
        fetch_collection(self.db,self.repo.installation_id,['123','123','999','0'],transport=transport,now=NOW)
        fetch_collection(self.db,self.repo.installation_id,['123'],transport=transport,now=NOW+timedelta(hours=1))
        self.assertEqual(calls,[['123']]);self.assertEqual(self.scalar('SELECT count(*) FROM workshop_metadata'),1)

    def test_discrepancy_preserves_original_target_and_manual_categories(self):
        self.fetch(steam_body(tags=('Survivors','Nick','Sounds')))
        card=catalog_cards(self.db.connection,self.repo.installation_id)[0];metadata=cached_metadata(self.db.connection,['123'])['123']
        targets=[dict(row) for row in self.db.connection.execute('SELECT * FROM targets')]
        self.assertTrue(metadata_discrepancies(card,metadata,targets));self.assertEqual(original_name(card),'Rochelle');self.assertEqual(replacement_name(card),'Not set')
        self.assertIn('Sounds',category_labels(card,metadata))
        save_mod_edit(self.db,self.repo.installation_id,card.package_id,category_mode='replace',category_ids=('ui',))
        card=catalog_cards(self.db.connection,self.repo.installation_id)[0];self.assertEqual(category_labels(card,metadata),('UI',));self.assertEqual(steam_name(card,metadata),metadata['title'])

    def test_steam_updates_roll_back_when_tag_insert_fails(self):
        self.fetch();before=cached_metadata(self.db.connection,['123'])
        self.db.connection.execute("CREATE TEMP TRIGGER reject_tags BEFORE INSERT ON workshop_item_tags BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.fetch(steam_body(title='Changed',tags=('UI',)),now=NOW+timedelta(days=2))
        self.assertEqual(cached_metadata(self.db.connection,['123']),before)


class MigrationAndEditTests(CatalogFixture):
    def test_slow_first_poll_cannot_publish_a_premature_startup_audit(self):
        self.add();original=self.session.monitor.poll
        def slow():
            report=original();self.now+=2.1;return report
        self.session.monitor.poll=slow;self.session.poll()
        self.assertEqual(self.scalar('SELECT count(*) FROM scan_runs'),0)
        self.session.poll();self.assertEqual(self.scalar('SELECT count(*) FROM scan_runs'),1)
        self.session.poll();self.assertEqual(self.scalar('SELECT count(*) FROM scan_runs'),1)

    def test_v3_to_v4_backup_rollback_reopen_and_reference_integrity(self):
        upgrade(self.db,target_version=3);self.add();self.settle();refresh_classification(self.db,self.repo.installation_id)
        card=catalog_cards(self.db.connection,self.repo.installation_id)[0];save_mod_edit(self.db,self.repo.installation_id,card.package_id,friendly_name='Keep me')
        from l4d2_mod_db.planning import set_membership
        set_membership(self.db,self.repo.installation_id,card.package_id,True);before=logical_digest(self.db.connection)
        def fail(stage):
            if stage=='after_ddl':raise RuntimeError('injected')
        with self.assertRaises(RuntimeError):upgrade(self.db,target_version=4,fault=fail)
        self.assertEqual(logical_digest(self.db.connection),before)
        result=upgrade(self.db,target_version=4);backup=sqlite3.connect('file:'+result.backup_path.replace('\\','/')+'?mode=ro',uri=True)
        try:self.assertEqual(logical_digest(backup),before)
        finally:backup.close()
        self.db.close();self.db=CatalogDatabase(self.policy)
        self.assertEqual(self.scalar('PRAGMA user_version'),4);self.assertEqual(self.scalar("SELECT count(*) FROM sqlite_master WHERE type='table'"),23)
        self.assertEqual(self.scalar('SELECT count(*) FROM planning_members'),1);self.assertEqual(self.scalar('SELECT friendly_name FROM user_mod_edits'),'Keep me')
        self.assertEqual(self.db.connection.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_unified_save_validation_rolls_back_every_section(self):
        upgrade(self.db,target_version=4);self.add();self.settle();refresh_classification(self.db,self.repo.installation_id)
        card=catalog_cards(self.db.connection,self.repo.installation_id)[0]
        before=logical_digest(self.db.connection)
        with self.assertRaises(ValueError):save_details(self.db,self.repo.installation_id,package_id=card.package_id,mod={'friendly_name':'Should roll back'},effects={card.effects[0].effect_id:{'replacement_mode':'value','replacement':'x'*513}})
        self.assertEqual(logical_digest(self.db.connection),before)


class PreviewAndSettingsTests(FixtureTestCase):
    def setUp(self):
        super().setUp();self.access=ScopedWorkshopAccess(self.game);self.put('left4dead2/addons/workshop/123.vpk',build_vpk(('a.txt',)))

    def image(self,format='JPEG',size=(640,480)):
        if Image is None:self.skipTest('Pillow desktop extra is not installed')
        stream=BytesIO();Image.new('RGB',size,'navy').save(stream,format=format);return stream.getvalue()

    def test_real_jpeg_bounded_decode_cache_and_game_bytes_unchanged(self):
        path=self.put('left4dead2/addons/workshop/123.jpg',self.image());before=path.read_bytes();package=discover(self.access).packages[0];cache=PreviewCache()
        ppm=cache.load(self.access,package);self.assertTrue(ppm.startswith(b'P6\n'));self.assertEqual(cache.load(self.access,package),ppm);self.assertEqual(before,path.read_bytes())

    def test_bad_format_dimensions_and_missing_previews_fall_back(self):
        cache=PreviewCache();self.assertIsNone(cache.load(self.access,discover(self.access).packages[0]))
        for data in (b'invalid JPEG',self.image('BMP'),self.image(size=(5000,1))):
            self.put('left4dead2/addons/workshop/123.jpg',data);self.assertIsNone(cache.load(self.access,discover(self.access).packages[0]))

    def test_png_and_gif_content_in_validated_jpg_files(self):
        for format in ('PNG','GIF'):
            self.put('left4dead2/addons/workshop/123.jpg',self.image(format));self.assertIsNotNone(PreviewCache().load(self.access,discover(self.access).packages[0]))

    def test_preview_pairing_size_race_and_vpk_only_api(self):
        self.put('left4dead2/addons/workshop/123.jpg',self.image());self.put('left4dead2/addons/workshop/456.jpg',self.image());report=discover(self.access);package=report.packages[0]
        other=next(preview for preview in report.previews if preview.filename=='456.jpg')
        with self.assertRaises(PathPolicyError):self.access.read_preview(package.file,other)
        with self.assertRaises(PathPolicyError):
            with self.access.open_vpk(package.preview):pass
        self.put('left4dead2/addons/workshop/123.jpg',b'changed')
        with self.assertRaises(PathPolicyError):self.access.read_preview(package.file,package.preview)
        self.put('left4dead2/addons/workshop/123.jpg',b'x'*(4*1024*1024+1));package=discover(self.access).packages[0]
        with self.assertRaises(PathPolicyError):self.access.read_preview(package.file,package.preview)

    def test_preferences_persist_missing_and_malformed_without_scanning(self):
        settings=AppSettings(self.workspace/'prefs');self.assertEqual(settings.load(),'');settings.save(self.access)
        self.assertEqual(AppSettings(self.workspace/'prefs').load(),str(self.access.validated_root))
        settings.path.write_text('{bad',encoding='utf8')
        with self.assertRaises(CatalogError):settings.load()


class UXTests(FixtureTestCase):
    wait=m6.DesktopGuiTests.wait

    def setUp(self):
        super().setUp()
        self.put('left4dead2/addons/workshop/1.vpk',build_vpk(('models/w_models/weapons/w_rifle_ak47.mdl','materials/shared.vmt','addoninfo.txt')))
        self.put('left4dead2/addons/workshop/2.vpk',build_vpk(('models/survivors/survivor_producer.mdl','materials/shared.vmt','addoninfo.txt')))
        self.backend=DesktopBackend(str(self.game),test_directory=self.workspace/'ui-data',settle_seconds=.01);self.backend.load(scan=True)
        self.root=tk.Tk();self.root.withdraw();self.tk_errors=[];self.root.report_callback_exception=lambda *error:self.tk_errors.append(error)
        self.app=DesktopApp(self.root,str(self.game),backend_factory=lambda root:self.backend,autoload=False);self.app.open_root();self.wait()

    def tearDown(self):
        self.wait()
        with patch('l4d2_mod_db.details.messagebox.askyesno',return_value=True):self.app.close()
        self.app.executor.shutdown(wait=True);self.assertEqual(self.tk_errors,[]);super().tearDown()

    def details_window(self):
        self.app.catalog_tree.selection_set(self.app.catalog_tree.get_children()[0]);self.app.open_details();self.root.update();return self.app.details[-1]

    def test_unsaved_replacement_is_saved_with_package_name(self):
        window=self.details_window();window.replacement.set('Unsaved fictional replacement');window.name.set('A manual display name');window.save_mod();self.wait()
        card=next(card for card in self.app.state.cards if card.package_id==window.card.package_id)
        self.assertEqual(card.display_name,'A manual display name');self.assertTrue(any(effect.replacement=='Unsaved fictional replacement' for effect in card.effects));self.assertFalse(window.dirty())

    def test_effect_switch_and_refresh_keep_all_drafts(self):
        window=self.details_window();first=window.loaded_effect_id;window.replacement.set('Draft one')
        second=next(key for key in window.effect_tree.get_children() if key!=first);window.effect_tree.selection_set(second);window.load_effect();window.replacement.set('Draft two')
        self.app.open_root(scan=True);self.wait();self.assertEqual(window.replacement.get(),'Draft two')
        window.effect_tree.selection_set(first);window.load_effect();self.assertEqual(window.replacement.get(),'Draft one')
        window.save_all();self.wait();card=next(card for card in self.app.state.cards if card.package_id==window.card.package_id)
        self.assertTrue({'Draft one','Draft two'}.issubset({effect.replacement for effect in card.effects}));self.assertFalse(window.dirty())

    def test_close_exit_and_folder_switch_can_cancel_discard(self):
        window=self.details_window();window.replacement.set('Keep this draft')
        with patch('l4d2_mod_db.details.messagebox.askyesno',return_value=False) as prompt:
            window.close();self.app.close();self.assertTrue(window.window.winfo_exists());self.assertTrue(self.root.winfo_exists());self.assertEqual(prompt.call_count,2)
            with patch('l4d2_mod_db.desktop.filedialog.askdirectory') as chooser:self.app.browse();chooser.assert_not_called()
        self.assertEqual(window.replacement.get(),'Keep this draft')

    def test_failed_save_and_stale_refresh_do_not_erase_drafts(self):
        window=self.details_window();window.name.set('x'*257);window.replacement.set('Keep replacement');window.save_all();self.wait()
        self.assertEqual(window.name.get(),'x'*257);self.assertEqual(window.replacement.get(),'Keep replacement');self.assertIn('256',window.notice.get())
        self.put('left4dead2/addons/workshop/'+window.card.filename,b'corrupt');self.app.open_root(scan=True);self.wait()
        self.assertEqual(window.replacement.get(),'Keep replacement');self.assertTrue(window.dirty())

    def test_typing_during_unrelated_selection_action_is_preserved(self):
        window=self.details_window();window.replacement.set('Draft while selecting');package_id=window.card.package_id
        self.app.catalog_tree.selection_set(package_id);self.app.toggle_catalog();self.wait()
        self.assertEqual(window.replacement.get(),'Draft while selecting');self.assertIn(package_id,self.app.state.planning.selected_ids)

    def test_typing_during_own_save_is_kept_for_next_save(self):
        window=self.details_window();window.name.set('Submitted name');original=self.backend.load
        def slow(**kwargs):time.sleep(.12);return original(**kwargs)
        self.backend.load=slow;window.save_all();window.name.set('Newer unsaved name');self.wait()
        self.assertEqual(window.name.get(),'Newer unsaved name');self.assertTrue(window.dirty())
        card=next(card for card in self.app.state.cards if card.package_id==window.card.package_id);self.assertEqual(card.display_name,'Submitted name')

    def test_close_during_worker_checks_final_draft_and_can_cancel(self):
        window=self.details_window();original=self.backend.load
        def slow(**kwargs):time.sleep(.12);return original(**kwargs)
        self.backend.load=slow;self.app.submit();self.app.close();window.replacement.set('Typed while waiting')
        with patch('l4d2_mod_db.details.messagebox.askyesno',return_value=False):self.wait()
        self.assertFalse(self.app.destroyed);self.assertEqual(window.replacement.get(),'Typed while waiting');self.assertFalse(self.app.closing)

    def test_first_run_chooser_builds_and_saves_folder_once(self):
        settings=AppSettings(self.workspace/'first-preferences');other=tk.Toplevel(self.root)
        app=DesktopApp(other,backend_factory=lambda root:self.backend,settings=settings,autoload=True)
        try:
            with patch('l4d2_mod_db.desktop.filedialog.askdirectory',return_value=str(self.game)) as chooser:
                deadline=time.monotonic()+8
                while app.state is None and time.monotonic()<deadline:self.root.update();time.sleep(.01)
                self.assertIsNotNone(app.state);self.assertEqual(chooser.call_count,1);self.assertEqual(settings.load(),str(self.game))
        finally:app.close();app.executor.shutdown(wait=True)

    def test_mouse_and_keyboard_checkboxes_and_selected_only_plan(self):
        self.root.deiconify();self.root.geometry('1280x690');self.root.update()
        row=self.app.catalog_tree.get_children()[0];self.app.catalog_tree.see(row);self.root.update();x,y,width,height=self.app.catalog_tree.bbox(row,'selection')
        self.app.catalog_tree.event_generate('<Button-1>',x=x+width//2,y=y+height//2);self.wait()
        self.assertEqual(self.app.plan_tree.get_children(),(row,));self.assertEqual(self.app.catalog_tree.set(row,'selection'),'☑')
        self.app.catalog_tree.focus_force();self.app.catalog_tree.selection_set(row);self.app.catalog_tree.event_generate('<space>');self.wait()
        self.assertEqual(self.app.plan_tree.get_children(),());self.assertFalse(self.app.state.planning.selected_ids)

    def test_links_only_on_action_and_official_title_search(self):
        links=[];self.app.link_opener=links.append;row=self.app.catalog_tree.get_children()[0];card=next(card for card in self.app.state.cards if card.package_id==row)
        self.app.state.metadata[card.workshop_id]={'title':'Exact public title 日本語','tags':('Survivors','Models'),'retrieval_status':'ok'}
        self.app.render_catalog();self.assertEqual(links,[]);self.assertEqual(self.app.catalog_tree.set(row,'steam'),'Exact public title 日本語')
        self.app.search.set('日本語');self.root.update();self.assertEqual(len(self.app.catalog_tree.get_children()),1)
        self.app.open_link(row);self.assertEqual(links,[workshop_url(card.workshop_id)]);self.assertEqual(original_name(card),'AK-47')

    def test_sort_columns_neutral_catalog_and_hidden_technical_details(self):
        self.root.geometry('1200x660');self.root.update();self.assertEqual(self.app.catalog_tree.heading('steam')['text'],'Steam Name')
        self.app.sort_by(self.app.catalog_tree,'original');values=[self.app.catalog_tree.set(row,'original') for row in self.app.catalog_tree.get_children()];self.assertEqual(values,sorted(values,key=str.casefold))
        window=self.details_window();self.assertNotIn(str(window.evidence_tab),window.tabs.tabs());window.show_technical();self.root.update();self.assertIn('Canonical hex:',window.evidence_text.get('1.0','end'))

    def test_small_viewport_keeps_planning_paths_and_save_visible(self):
        self.root.deiconify();self.root.geometry('1000x520');self.app.notebook.select(self.app.plan_tab);self.app.toggle_paths(show=True);self.root.update()
        self.assertTrue(self.app.warning_text.winfo_ismapped())
        self.assertLessEqual(self.app.warning_text.winfo_rooty()+self.app.warning_text.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
        self.app.notebook.select(self.app.catalog_tab);window=self.details_window();window.window.geometry('800x510');self.root.update()
        self.assertLessEqual(window.save_button.winfo_rooty()+window.save_button.winfo_height(),window.window.winfo_rooty()+window.window.winfo_height())
        window.tabs.select(window.edit_host);self.root.update();self.assertTrue(window.edit_canvas.winfo_ismapped())

    def test_first_selection_saved_second_launch_auto_opens_without_chooser(self):
        settings=AppSettings(self.workspace/'preferences');self.app.settings=settings;self.app.open_root();self.wait();self.assertEqual(settings.load(),str(self.game))
        other=tk.Toplevel(self.root)
        app=DesktopApp(other,backend_factory=lambda root:self.backend,settings=settings,autoload=True)
        try:
            with patch('l4d2_mod_db.desktop.filedialog.askdirectory') as chooser:
                deadline=time.monotonic()+8
                while app.state is None and time.monotonic()<deadline:self.root.update();time.sleep(.01)
                self.assertIsNotNone(app.state);chooser.assert_not_called()
            self.assertEqual({card.package_id for card in app.state.cards},{card.package_id for card in self.app.state.cards})
        finally:app.close();app.executor.shutdown(wait=True)

    def test_invalid_saved_root_reselection_retains_catalog(self):
        settings=AppSettings(self.workspace/'preferences');settings.save(ScopedWorkshopAccess(self.game))
        self.app.backend_factory=lambda root:DesktopBackend(root,test_directory=self.workspace/'ui-data',settle_seconds=.01)
        self.app.settings=settings;self.app.path.set(str(self.workspace/'missing-game'));self.app.open_root();self.wait();self.assertIn('Change Game Folder',self.app.status.get())
        with patch('l4d2_mod_db.desktop.filedialog.askdirectory',return_value=str(self.game)):self.app.browse()
        self.wait();self.assertEqual(len(self.app.state.cards),2);self.assertEqual(settings.load(),str(self.game))
