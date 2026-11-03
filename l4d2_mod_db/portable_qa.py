"""Explicit developer-only smoke mode, restricted to an isolated workspace profile."""
import json
import os
from pathlib import Path
import time
import tkinter as tk

from .desktop import DesktopApp,filedialog
from .settings import AppSettings
from .storage import CatalogError


def run(game_root, *, unavailable=False):
    allowed=(Path.cwd()/'.test-tmp').resolve(strict=True)
    profile=Path(os.environ.get('LOCALAPPDATA','')).resolve(strict=True)
    if not profile.is_relative_to(allowed) or not profile.name.startswith(('m63-portable-','m64-portable-')):
        raise CatalogError('Portable QA requires a dedicated .test-tmp/m64-portable-* LOCALAPPDATA profile.')
    game=Path(game_root).resolve(strict=not unavailable)
    if not game.is_relative_to(allowed):raise CatalogError('Portable QA permits only synthetic workspace fixtures.')
    report={};chooser_calls=[];settings=AppSettings();previous=settings.load()
    original=filedialog.askdirectory
    filedialog.askdirectory=lambda **kwargs:chooser_calls.append(True) or str(game)
    root=tk.Tk();root.withdraw();errors=[];root.report_callback_exception=lambda *args:errors.append(str(args[1]))
    app=DesktopApp(root,settings=settings,auto_sync=False)
    def wait(require_state=True):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            root.update()
            if app.backend is not None and not app.busy and (app.state is not None or not require_state):break
            time.sleep(.01)
        root.update()
        if (require_state and app.state is None) or app.busy:raise RuntimeError('Catalog did not load within the QA deadline.')
    try:
        if unavailable:
            wait(False);report.update(recoverable_error='Change Game Folder' in app.status.get(),previous_root_preserved=settings.load()==str(game),tk_errors=errors)
            report['ok']=report['recoverable_error'] and report['previous_root_preserved'] and not errors
            return 0 if report['ok'] else 1
        wait();report['chooser_calls']=len(chooser_calls);report['expected_chooser_calls']=0 if previous else 1
        report['packages']=len(app.state.cards);report['ids']=sorted(c.package_id for c in app.state.cards)
        app.select_filter(('Survivors','Rochelle'));report['rochelle_filter_count']=len(app.catalog_tree.get_children())
        app.show_category_chooser();root.update();report['unified_filter_available']=('Weapons','Rifles','Desert Rifle') in app.category_chooser.nodes
        report['filter_actions_ordered']=app.category_chooser.cancel_button.pack_info()['side']=='left' and app.category_chooser.apply_button.pack_info()['side']=='right'
        app.category_chooser.window.destroy();app.select_filter(('Weapons','Rifles','Desert Rifle'));report['desert_rifle_filter_count']=len(app.catalog_tree.get_children())
        app.select_filter(());report['all_mods_restored']=len(app.catalog_tree.get_children())==report['packages']
        card=app.state.cards[0];app.catalog_tree.selection_set(card.package_id);app.open_details();root.update();window=app.details[-1]
        report['custom_name_secondary']=not bool(window.more_options.winfo_manager())
        report['cached_steam_title']=app.state.metadata.get(card.workshop_id,{}).get('title')
        if previous:
            report['saved_name_retained']=card.display_name=='Portable QA name'
            report['planning_retained']=card.package_id in app.state.planning.selected_ids
            report['replacement_retained']=any(e.replacement=='Portable QA replacement' for e in card.effects)
        else:
            window.toggle_more();window.name.set('Portable QA name');window.toggle_more();window.replacement.set('Portable QA replacement');window.save_all();wait()
            for member in app.state.cards:
                if member.workshop_id in ('123','124','125'):app.submit(action=('selection',dict(package_id=member.package_id,selected=True)));wait()
            report['saved_name_retained']=app.state.cards[0].display_name=='Portable QA name'
            report['planning_retained']=card.package_id in app.state.planning.selected_ids
            report['replacement_retained']=any(e.replacement=='Portable QA replacement' for e in app.state.cards[0].effects)
        settings.save(__import__('l4d2_mod_db.security',fromlist=['ScopedWorkshopAccess']).ScopedWorkshopAccess(game),auto_online=False,online_notice_seen=True)
        report['tk_errors']=errors
        report['preview_loaded']=bool(app.images)
        report['planning_resource_pairs']=app.state.planning.counts['selected_attention']
        report['planning_conflict_highlights']=all('attention' in app.plan_tree.item(row,'tags') for row in app.plan_tree.get_children()) and str(app.plan_tree.tag_configure('attention','background'))=='#fde2e2'
        report['planning_reasons']=[app.warning_tree.set(row,'kind') for row in app.warning_tree.get_children()]
        from .storage import CatalogReader,StoragePolicy
        from .security import ScopedWorkshopAccess
        with CatalogReader(StoragePolicy.production(ScopedWorkshopAccess(game),create=False)) as reader:
            report['integrity']=reader.connection.execute('PRAGMA integrity_check').fetchone()[0]
            report['foreign_keys']=len(reader.connection.execute('PRAGMA foreign_key_check').fetchall())
        report['ok']=bool(report['chooser_calls']==report['expected_chooser_calls'] and report['packages']==5 and report['rochelle_filter_count']==2 and report['desert_rifle_filter_count']==1 and report['unified_filter_available'] and report['filter_actions_ordered'] and report['all_mods_restored'] and report['custom_name_secondary'] and report['planning_resource_pairs']==2 and report['planning_conflict_highlights'] and report['integrity']=='ok' and not report['foreign_keys'] and (not previous or report['cached_steam_title']) and report['preview_loaded'] and all(report[k] for k in ('saved_name_retained','planning_retained','replacement_retained')) and not errors)
    except Exception as error:report.update(ok=False,error=repr(error))
    finally:
        filedialog.askdirectory=original
        if not app.destroyed:app._destroy()
        app.executor.shutdown(wait=True);app.network_executor.shutdown(wait=True)
        (profile/'qa-report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return 0 if report.get('ok') else 1
