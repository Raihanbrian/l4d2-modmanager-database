"""M6.2 pure suggestion rules, unchanged evidence, review and actual Tk regressions."""

from dataclasses import replace
from unittest.mock import patch

from l4d2_mod_db.classification import catalog_cards,refresh_classification,save_effect_edit
from l4d2_mod_db.conflicts import analyze_conflicts
from l4d2_mod_db.migrations import upgrade,logical_digest
from l4d2_mod_db.planning import planning_report,selected_warning_ids,ReviewSession
from l4d2_mod_db.presentation import replacement_name
from l4d2_mod_db.review import replacement_review
from l4d2_mod_db.storage import CatalogDatabase
from l4d2_mod_db.suggestions import suggest_replacement,RULE_VERSION
from l4d2_mod_db.workshop_metadata import SOURCE
from .test_catalog import CatalogFixture
from . import test_m61 as m61
from .helpers import FixtureTestCase
from .vpk_fixtures import build_vpk

ROCHELLE='models/survivors/survivor_producer.mdl'
NICK='models/survivors/survivor_gambler.mdl'
SCAR='models/w_models/weapons/w_desert_rifle.mdl'


def metadata(card,title='Violet [Rochelle]',tags=('Survivors','Rochelle')):
    return dict(workshop_id=card.workshop_id,title=title,tags=tags,app_id=550,source=SOURCE,
                last_success_at='2026-10-29T15:00:00+00:00',retrieval_status='ok')


class SuggestionTests(CatalogFixture):
    def setUp(self):super().setUp();upgrade(self.db,target_version=4)

    def card(self,paths=(ROCHELLE,'materials/shared.vmt')):
        self.add(paths=paths);self.settle();refresh_classification(self.db,self.repo.installation_id)
        return catalog_cards(self.db.connection,self.repo.installation_id)[0]

    def test_required_title_patterns_and_exact_title_provenance(self):
        card=self.card()
        for title,candidate in (('Violet [Rochelle]','Violet'),('Makoto Niijima (Phantom Thief Costume) - Persona 5','Makoto Niijima (Phantom Thief Costume)'),
                                ('Ren Amamiya (Phantom Thief Costume) - Persona 5','Ren Amamiya (Phantom Thief Costume)')):
            source=metadata(card,title);result=suggest_replacement(card,source)
            self.assertEqual(result.name,candidate);self.assertEqual(result.title,title);self.assertEqual(source['title'],title);self.assertEqual(result.rule_version,RULE_VERSION)
        card=self.card((SCAR,));self.assertEqual(suggest_replacement(card,metadata(card,'FN SCAR-H (SCAR)',('Weapons','Rifle'))).name,'FN SCAR-H')

    def test_trim_matching_copy_only_and_preserve_outfit_unicode(self):
        card=self.card();title='  Yusuke Kitagawa (Phantom Thief Outfit) - Persona 5\n'
        source=metadata(card,title);result=suggest_replacement(card,source)
        self.assertEqual(result.name,'Yusuke Kitagawa (Phantom Thief Outfit)');self.assertEqual(result.title,title);self.assertEqual(source['title'],title)
        self.assertEqual(suggest_replacement(card,metadata(card,'紫音 [Rochelle]')).name,'紫音')

    def test_explicit_franchise_name_slot_rule(self):
        card=self.card();self.assertEqual(suggest_replacement(card,metadata(card,'Blue Archive - Mika - Rochelle')).name,'Mika')

    def test_wrong_bracket_slot_and_weapon_alias_fail_closed(self):
        card=self.card();self.assertIsNone(suggest_replacement(card,metadata(card,'Violet [Coach]')).name)
        card=self.card((SCAR,));self.assertIsNone(suggest_replacement(card,metadata(card,'FN SCAR-H (AK-47)',('Weapons',))).name)

    def test_component_and_multi_titles_are_not_whole_model_replacements(self):
        card=self.card()
        for title in ('Violet Sound [Rochelle]','Violet Animations [Rochelle]','Violet Texture [Rochelle]','Violet Shader [Rochelle]',
                      'Violet Script [Rochelle]','Violet & Mika [Rochelle]','Violet / Mika [Rochelle]','Violet Pack [Rochelle]'):
            self.assertIsNone(suggest_replacement(card,metadata(card,title)).name,title)

    def test_base_model_required_not_script_or_sidecar(self):
        for paths,title,tags in ((('sound/rochelle.wav',),'Violet [Rochelle]',('Survivors',)),
                                 (('models/survivors/survivor_producer.vvd',),'Violet [Rochelle]',('Survivors',)),
                                 (('scripts/weapon_rifle_desert.txt',),'FN SCAR-H (SCAR)',('Weapons',))):
            card=self.card(paths);self.assertIsNone(suggest_replacement(card,metadata(card,title,tags)).name)

    def test_multiple_original_targets_and_disagreeing_tags_are_unknown(self):
        card=self.card((ROCHELLE,NICK));self.assertIsNone(suggest_replacement(card,metadata(card)).name)
        card=self.card();self.assertIsNone(suggest_replacement(card,metadata(card,tags=('Survivors','Nick'))).name)
        self.assertIsNone(suggest_replacement(card,metadata(card,tags=('Weapons',))).name)
        self.assertIsNone(suggest_replacement(card,metadata(card,tags=('Survivors','Sounds'))).name)

    def test_unverified_other_app_failed_cache_and_stale_source(self):
        card=self.card();source=metadata(card)
        for key,value in (('source','User nickname'),('app_id',730),('last_success_at',None),('retrieval_status','network_error'),('workshop_id','999')):
            self.assertIsNone(suggest_replacement(card,{**source,key:value}).name)
        for stale in (replace(card,index_status='pending'),replace(card,presence_status='unavailable'),replace(card,review_status='Stale / Needs Review')):
            self.assertIsNone(suggest_replacement(stale,source).name)

    def test_manual_value_and_explicit_unknown_take_precedence(self):
        card=self.card();effect=next(effect for effect in card.effects if effect.target_ids)
        save_effect_edit(self.db,self.repo.installation_id,effect.effect_id,replacement_mode='value',replacement='My verified Violet')
        card=catalog_cards(self.db.connection,self.repo.installation_id)[0]
        self.assertIsNone(suggest_replacement(card,metadata(card)).name);self.assertIn('Confirmed:',replacement_review(card,metadata(card)).text)
        save_effect_edit(self.db,self.repo.installation_id,effect.effect_id,replacement_mode='unknown')
        card=catalog_cards(self.db.connection,self.repo.installation_id)[0];self.assertIsNone(suggest_replacement(card,metadata(card)).name)

    def test_no_sql_mutation_idempotent_and_restart_stable(self):
        card=self.card();source=metadata(card);before=logical_digest(self.db.connection);result=suggest_replacement(card,source)
        for _ in range(10):self.assertEqual(suggest_replacement(card,source),result);self.assertTrue(replacement_review(card,source).text.startswith('Suggested:'))
        self.assertEqual(logical_digest(self.db.connection),before);self.db.close();self.db=CatalogDatabase(self.policy)
        self.assertEqual(suggest_replacement(catalog_cards(self.db.connection,self.repo.installation_id)[0],source),result)
        self.assertEqual(self.scalar("SELECT count(*) FROM sqlite_master WHERE type='table'"),23)

    def test_unknown_title_and_unsafe_name_remain_unset(self):
        card=self.card()
        for title in ('Amazing addon','Violet [Rochelle] extra','<script>Violet</script> [Rochelle]','A [Rochelle]','Violet [Nick/Rochelle]'):
            self.assertIsNone(suggest_replacement(card,metadata(card,title)).name)

    def test_freshness_is_separate_from_confirmation(self):
        card=self.card();effect=next(effect for effect in card.effects if effect.target_ids)
        save_effect_edit(self.db,self.repo.installation_id,effect.effect_id,replacement_mode='value',replacement='Saved name')
        card=catalog_cards(self.db.connection,self.repo.installation_id)[0];view=replacement_review(replace(card,index_status='error'),metadata(card))
        self.assertEqual(view.confirmation,'User confirmed replacement');self.assertEqual(view.freshness,'Stale / Needs Review');self.assertIn('Saved name',view.text)
        updated=replace(card,review_status='Stale / Needs Review',effects=tuple(replace(effect,review_status='Stale / Needs Review') if effect.replacement else effect for effect in card.effects))
        current_files=replacement_review(updated,metadata(card));self.assertEqual(current_files.freshness,'Current file evidence');self.assertTrue(current_files.text.startswith('Stale entry:'))

    def test_invalid_utf8_asset_bytes_do_not_change_title_candidate(self):
        self.card((ROCHELLE,'materials/q_shared.vmt'))
        self.put('left4dead2/addons/workshop/123.vpk',build_vpk((ROCHELLE,'materials/q_shared.vmt')).replace(b'q_shared',b'\xff_shared'))
        self.settle();refresh_classification(self.db,self.repo.installation_id);card=catalog_cards(self.db.connection,self.repo.installation_id)[0]
        self.assertEqual(suggest_replacement(card,metadata(card)).name,'Violet')


class PlanningClarityTests(CatalogFixture):
    def setUp(self):
        super().setUp();upgrade(self.db,target_version=4)
        for number,paths in enumerate(((NICK,'materials/selected.vmt','addoninfo.txt'),(ROCHELLE,'materials/selected.vmt','addoninfo.txt'),
                                      ('models/survivors/survivor_teenangst.mdl','materials/outside.vmt','addoninfo.txt'),
                                      ('models/survivors/survivor_coach.mdl','materials/outside.vmt','addoninfo.txt')),1):self.add(str(number)+'.vpk',paths)
        self.settle();self.report=analyze_conflicts(self.db.connection,self.repo.installation_id,include_retained=True)
        self.ids={package.filename:package.package_id for package in self.report.packages}

    def plan(self):return planning_report(self.report,[self.ids[name] for name in ('1.vpk','2.vpk','3.vpk')])

    def test_candidate_never_flags_otherwise_clean_selected_mod(self):
        plan=self.plan();self.assertEqual(selected_warning_ids(plan),{self.ids['1.vpk'],self.ids['2.vpk']})
        self.assertNotIn(self.ids['3.vpk'],selected_warning_ids(plan));self.assertEqual(plan.counts['selected_attention'],1);self.assertEqual(plan.counts['candidate_attention'],1)

    def test_information_only_and_no_selection_have_no_warning_ids(self):
        self.assertFalse(selected_warning_ids(planning_report(self.report,())))
        self.assertFalse(selected_warning_ids(planning_report(self.report,[self.ids['1.vpk'],self.ids['3.vpk']])))

    def test_acknowledgement_never_changes_raw_evidence_or_counts(self):
        plan=self.plan();finding=next(f for f in plan.findings if f.context=='selected' and f.presentation=='attention');before=self.report.to_dict();counts=plan.counts
        session=ReviewSession();session.toggle(finding);self.assertTrue(session.reviewed(finding));self.assertEqual(plan.counts,counts);self.assertEqual(self.report.to_dict(),before)
        session.toggle(finding);self.assertFalse(session.reviewed(finding));self.assertFalse(ReviewSession().reviewed(finding))

    def test_stale_and_candidate_acknowledgements_are_refused(self):
        plan=self.plan();candidate=next(f for f in plan.findings if f.context=='candidate')
        with self.assertRaises(ValueError):ReviewSession().toggle(candidate)
        current=next(f for f in plan.findings if f.context=='selected')
        with self.assertRaises(ValueError):ReviewSession().toggle(replace(current,pair=replace(current.pair,evidence_freshness='retained')))

    def test_update_outage_or_membership_change_clears_review(self):
        plan=self.plan();finding=next(f for f in plan.findings if f.context=='selected' and f.presentation=='attention');session=ReviewSession();session.toggle(finding)
        session.reconcile(plan);self.assertTrue(session.reviewed(finding))
        changed=replace(finding,pair=replace(finding.pair,package_a=replace(finding.pair.package_a,index_generation=finding.pair.package_a.index_generation+1)))
        session.reconcile(replace(plan,findings=(changed,)));self.assertFalse(session.reviewed(changed))
        session.toggle(finding);session.reconcile(planning_report(self.report,[self.ids['1.vpk']]));self.assertFalse(session.reviewed(finding))
        session.toggle(finding);session.reconcile(replace(plan,findings=(replace(finding,pair=replace(finding.pair,evidence_freshness='retained')),)));self.assertFalse(session.reviewed(finding))

    def test_retained_overlap_not_current_selected_flag(self):
        self.db.connection.execute("UPDATE packages SET index_status='error' WHERE package_id=?",(self.ids['1.vpk'],))
        report=analyze_conflicts(self.db.connection,self.repo.installation_id,include_retained=True);plan=planning_report(report,[self.ids['1.vpk'],self.ids['2.vpk']])
        self.assertFalse(selected_warning_ids(plan));self.assertEqual(plan.counts['selected_retained'],1)

    def test_persisted_package_update_invalidates_session_acknowledgement(self):
        plan=self.plan();finding=next(f for f in plan.findings if f.context=='selected' and f.presentation=='attention');session=ReviewSession();session.toggle(finding)
        self.add('1.vpk',(NICK,'materials/selected.vmt','materials/changed.vmt','addoninfo.txt'));self.settle()
        changed=planning_report(analyze_conflicts(self.db.connection,self.repo.installation_id,include_retained=True),plan.selected_ids)
        session.reconcile(changed);self.assertTrue(all(not session.reviewed(f) for f in changed.findings))


class M62GuiTests(FixtureTestCase):
    wait=m61.UXTests.wait
    details_window=m61.UXTests.details_window

    # setUp/tearDown use zero-argument super(), so execute them on a compatible
    # base via explicit wrappers below rather than borrowing bound implementations.
    def setUp(self):
        FixtureTestCase.setUp(self)
        from l4d2_mod_db.desktop_model import DesktopBackend
        from l4d2_mod_db.desktop import DesktopApp
        import tkinter as tk
        self.put('left4dead2/addons/workshop/1.vpk',build_vpk(('models/w_models/weapons/w_rifle_ak47.mdl','materials/shared.vmt','addoninfo.txt')))
        self.put('left4dead2/addons/workshop/2.vpk',build_vpk((ROCHELLE,'materials/shared.vmt','addoninfo.txt')))
        self.backend=DesktopBackend(str(self.game),test_directory=self.workspace/'data',settle_seconds=.01);self.backend.load(scan=True)
        self.root=tk.Tk();self.root.withdraw();self.tk_errors=[];self.root.report_callback_exception=lambda *args:self.tk_errors.append(args)
        self.app=DesktopApp(self.root,str(self.game),backend_factory=lambda root:self.backend,autoload=False);self.app.open_root();self.wait()

    def tearDown(self):
        self.wait()
        with patch('l4d2_mod_db.details.messagebox.askyesno',return_value=True):self.app.close()
        self.app.executor.shutdown(wait=True);self.assertEqual(self.tk_errors,[]);FixtureTestCase.tearDown(self)

    def suggested_window(self):
        card=next(card for card in self.app.state.cards if card.workshop_id=='2');self.app.state.metadata[card.workshop_id]=metadata(card)
        self.app.render_catalog();self.app.catalog_tree.selection_set(card.package_id);self.app.open_details();self.root.update();return self.app.details[-1]

    def test_suggestion_visible_but_not_a_draft_or_saved_edit_until_action(self):
        window=self.suggested_window();self.assertEqual(self.app.catalog_tree.set(window.card.package_id,'status'),'Suggested')
        self.assertEqual(window.replacement.get(),'');self.assertFalse(window.dirty());self.assertIsNone(window.current_effect().user_edit)
        window.use_suggestion();self.assertEqual(window.replacement.get(),'Violet');self.assertTrue(window.dirty());self.assertIsNone(window.current_effect().user_edit)

    def test_confirm_or_correct_suggestion_through_one_save(self):
        window=self.suggested_window();window.use_suggestion();window.replacement.set('Violet, checked by me');window.save_all();self.wait()
        self.assertEqual(self.app.catalog_tree.set(window.card.package_id,'status'),'Confirmed')
        self.assertTrue(any(effect.replacement=='Violet, checked by me' for effect in window.card.effects));self.assertFalse(window.dirty())

    def test_suggestion_cannot_overwrite_draft_without_confirmation(self):
        window=self.suggested_window();window.replacement.set('Keep my draft')
        with patch('l4d2_mod_db.details.messagebox.askyesno',return_value=False):window.use_suggestion()
        self.assertEqual(window.replacement.get(),'Keep my draft')

    def test_suggestion_rechecks_source_after_unsaved_refresh(self):
        window=self.suggested_window();window.name.set('Unrelated draft');self.put('left4dead2/addons/workshop/2.vpk',b'corrupt')
        self.app.open_root(scan=True);self.wait();window.use_suggestion();self.assertEqual(window.replacement.get(),'');self.assertEqual(window.name.get(),'Unrelated draft')

    def test_changed_target_draft_or_cached_title_blocks_old_suggestion(self):
        window=self.suggested_window();window.target_mode.set('Unknown');window.use_suggestion();self.assertEqual(window.replacement.get(),'')
        window.target_mode.set('Use evidence');self.app.state.metadata[window.card.workshop_id]['title']='Another name [Rochelle]'
        window.use_suggestion();self.assertEqual(window.replacement.get(),'');self.assertIn('source changed',window.notice.get())

    def test_candidate_is_optional_and_does_not_color_clean_selection(self):
        package_id=self.app.state.cards[0].package_id;self.app.catalog_tree.selection_set(package_id);self.app.toggle_catalog();self.wait()
        self.assertEqual(self.app.warning_tree.get_children(),());self.assertNotIn(str(self.app.candidate_tab),self.app.review_tabs.tabs())
        self.assertFalse(self.app.plan_tree.item(package_id,'tags'));self.assertIn('No selected-pair',self.app.plan_tree.set(package_id,'warning'))
        self.app.show_candidates.set(True);self.app.toggle_candidates();self.root.update();self.assertEqual(len(self.app.candidate_tree.get_children()),1)
        row=self.app.candidate_tree.get_children()[0];self.app.candidate_tree.selection_set(row);self.app.show_warning(tree=self.app.candidate_tree)
        self.assertIn('outside your set',self.app.warning_text.get('1.0','end'));self.assertEqual(str(self.app.mark_reviewed_button['state']),'disabled')

    def test_selected_overlap_red_highlight_review_mark_preserves_counts(self):
        for card in self.app.state.cards:
            self.app.catalog_tree.selection_set(card.package_id);self.app.toggle_catalog();self.wait()
        self.assertEqual(len(self.app.warning_tree.get_children()),1);self.assertEqual(self.app.candidate_tree.get_children(),())
        for card in self.app.state.cards:self.assertIn('attention',self.app.plan_tree.item(card.package_id,'tags'))
        self.assertEqual(str(self.app.plan_tree.tag_configure('attention','foreground')),'#8b1a1a')
        self.assertEqual(str(self.app.plan_tree.tag_configure('attention','background')),'#fde2e2')
        before=self.app.state.overlaps.to_dict();row=self.app.warning_tree.get_children()[0]
        self.app.warning_tree.selection_set(row);self.app.show_warning();self.app.mark_reviewed()
        self.assertIn('Reviewed this session',self.app.warning_tree.set(row,'kind'));self.assertEqual(self.app.state.overlaps.to_dict(),before)
        for card in self.app.state.cards:self.assertIn('attention',self.app.plan_tree.item(card.package_id,'tags'))

    def test_review_tooltip_explains_confirmation_and_freshness(self):
        window=self.suggested_window();column='#'+str(tuple(self.app.catalog_tree['displaycolumns']).index('replacement')+1)
        text=self.app.cell_text(self.app.catalog_tree,window.card.package_id,column)
        self.assertIn('unconfirmed',text);self.assertIn('Current file evidence',text);self.assertIn('Edit Info',text)
