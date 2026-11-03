"""Two process launches, synthetic game/data only. Tests source launcher or EXE."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import zipfile
from tools.review_fixture import make_game,steam_fixture,DEMO
from l4d2_mod_db.security import ScopedWorkshopAccess
from l4d2_mod_db.storage import CatalogDatabase,StoragePolicy
from l4d2_mod_db.workshop_metadata import fetch_collection


def main():
    parser=argparse.ArgumentParser(description=__doc__);group=parser.add_mutually_exclusive_group();group.add_argument('--exe');group.add_argument('--zip');group.add_argument('--launcher',action='store_true');args=parser.parse_args()
    root=Path.cwd();folder=root/'.test-tmp'/('m64-portable-'+uuid4().hex);profile=folder/'m64-portable-profile';profile.mkdir(parents=True)
    game=make_game(folder/'synthetic-game');workshop=game/'left4dead2/addons/workshop'
    initial={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in workshop.iterdir()}
    environment=dict(os.environ,LOCALAPPDATA=str(profile),PYTHONDONTWRITEBYTECODE='1')
    if args.zip:
        extracted=folder/'Extracted portable app';extracted.mkdir()
        with zipfile.ZipFile(args.zip) as archive:
            if len(archive.infolist())>4096 or sum(i.file_size for i in archive.infolist())>400*1024*1024:raise ValueError('Unbounded release archive refused.')
            for item in archive.infolist():
                target=(extracted/item.filename).resolve()
                if not target.is_relative_to(extracted.resolve()) or (item.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe release member.')
            archive.extractall(extracted)
        args.exe=str(extracted/'L4D2ModDatabase/L4D2ModDatabase.exe')
    if args.exe:
        environment['PATH']=os.environ.get('SystemRoot',r'C:\Windows')+r'\System32'
        environment.pop('PYTHONPATH',None);environment.pop('PYTHONHOME',None)
    command=[str(Path(args.exe).resolve())] if args.exe else ['cmd.exe','/d','/c',str(root/'Start-Alpha.cmd')] if args.launcher else [str(root/'.venv/Scripts/python.exe'),'-B','-m','l4d2_mod_db.desktop']
    reports=[];started=time.perf_counter()
    def launch(flag='--qa-smoke'):
        report_path=profile/'qa-report.json'
        if report_path.exists():report_path.unlink()
        arguments=('cmd.exe /d /s /c ""'+str(root/'Start-Alpha.cmd')+'" '+flag+' "'+str(game)+'""') if args.launcher else [*command,flag,str(game)]
        run=subprocess.run(arguments,env=environment,cwd=root,timeout=90,capture_output=True,stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if not (profile/'qa-report.json').exists():raise RuntimeError(run.stdout.decode(errors='replace')+run.stderr.decode(errors='replace'))
        report=json.loads(report_path.read_text(encoding='utf8'));report.update(exit_code=run.returncode,scenario=flag);reports.append(report);return report
    for number in range(2):
        report=launch()
        if not report.get('ok') or report['exit_code']:break
        if number==0:
            access=ScopedWorkshopAccess(game)
            with CatalogDatabase(StoragePolicy.isolated_test(profile/'L4D2ModDatabase',access)) as db:
                installation=db.connection.execute('SELECT installation_id FROM installations').fetchone()[0]
                fetch_collection(db,installation,set(DEMO),transport=steam_fixture,pause=lambda seconds:None)
    unchanged_on_unavailable=False
    if len(reports)==2 and all(r.get('ok') for r in reports):
        database=profile/'L4D2ModDatabase/catalog.sqlite3';digest=hashlib.sha256(database.read_bytes()).hexdigest()
        moved=folder/'temporarily unavailable synthetic-game'
        if game.resolve().parent!=folder.resolve() or moved.parent.resolve()!=folder.resolve():raise ValueError('Refusing a fixture move outside its dedicated workspace.')
        game.rename(moved)
        try:
            launch('--qa-unavailable');unchanged_on_unavailable=hashlib.sha256(database.read_bytes()).hexdigest()==digest
        finally:moved.rename(game)
        launch()
    result=dict(mode='exe' if args.exe else 'launcher' if args.launcher else 'source',runs=reports,
        ids_stable=len(reports)==2 and reports[0]['ids']==reports[1]['ids'],game_bytes_unchanged=initial=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in workshop.iterdir()},seconds=round(time.perf_counter()-started,3),profile=str(profile))
    result.update(mode='extracted_zip' if args.zip else result['mode'],unavailable_database_unchanged=unchanged_on_unavailable)
    result['ids_stable']=len(reports)==4 and reports[0]['ids']==reports[1]['ids']==reports[3]['ids']
    result['distribution_has_no_user_data']=not args.exe or not any(p.suffix in ('.sqlite3','.db') or p.name=='preferences.json' for p in Path(args.exe).parent.rglob('*') if p.is_file())
    result['ok']=len(reports)==4 and all(r.get('ok') and r['exit_code']==0 for r in reports) and result['ids_stable'] and result['game_bytes_unchanged'] and unchanged_on_unavailable and result['distribution_has_no_user_data']
    (folder/'smoke-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));return 0 if result['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
