"""Generate fictional, workspace-isolated QA/review data. Never copies a real addon."""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from PIL import Image,ImageDraw
from tests.vpk_fixtures import build_vpk

DEMO={
 '123':('Quartz Agent (Rochelle)',('Survivors','Rochelle','Models'),('models/survivors/survivor_producer.mdl','materials/demo/shared.vmt','addoninfo.txt'),'#466d90','Q'),
 '124':('Ember Agent (Nick)',('Survivors','Nick','Models'),('models/survivors/survivor_gambler.mdl','materials/demo/shared.vmt','addoninfo.txt'),'#9a653d','E'),
 '125':('Echo Agent (Rochelle)',('Survivors','Rochelle','Models'),('models/survivors/survivor_producer.mdl','addoninfo.txt'),'#58794e','A'),
 '126':('Field Carbine (SCAR)',('Weapons','Rifle','Models'),('models/w_models/weapons/w_desert_rifle.mdl','addoninfo.txt'),'#6e5d89','F'),
 '127':('Quiet HUD',('UI',),('resource/demo_hud.txt','addoninfo.txt'),'#3e7c7e','H'),
}


def make_game(folder):
    allowed=Path(__file__).resolve().parents[1]/'.test-tmp'
    if not folder.resolve().is_relative_to(allowed.resolve()) or folder.exists():raise ValueError('A new isolated .test-tmp fixture folder is required.')
    workshop=folder/'left4dead2/addons/workshop';workshop.mkdir(parents=True)
    for key,(title,tags,paths,color,letter) in DEMO.items():
        (workshop/(key+'.vpk')).write_bytes(build_vpk(paths))
        preview=Image.new('RGB',(96,72),color);ImageDraw.Draw(preview).text((38,22),letter,fill='white',font_size=28);preview.save(workshop/(key+'.jpg'))
    return folder


def steam_fixture(ids):
    return json.dumps({'response':{'resultcount':len(ids),'publishedfiledetails':[
        dict(publishedfileid=key,result=1,consumer_app_id=550,visibility=0,title=DEMO[key][0],tags=[{'tag':t} for t in DEMO[key][1]],description='Fictional QA example. No Workshop content or real item data.') for key in ids]}}).encode('utf8')


def seed_profile(game,profile):
    from l4d2_mod_db.security import ScopedWorkshopAccess
    from l4d2_mod_db.storage import CatalogDatabase,StoragePolicy
    from l4d2_mod_db.catalog import CatalogRepository,CatalogMonitor
    from l4d2_mod_db.migrations import upgrade
    from l4d2_mod_db.classification import refresh_classification
    from l4d2_mod_db.planning import set_membership
    from l4d2_mod_db.settings import AppSettings
    from l4d2_mod_db.workshop_metadata import fetch_collection
    profile.mkdir(parents=True,exist_ok=True)
    access=ScopedWorkshopAccess(game);directory=profile/'L4D2ModDatabase'
    with CatalogDatabase(StoragePolicy.isolated_test(directory,access)) as db:
        upgrade(db,target_version=5);repo=CatalogRepository(db,access);clock=[0.]
        monitor=CatalogMonitor(repo,clock=lambda:clock[0]);monitor.poll();clock[0]=3.;monitor.poll()
        refresh_classification(db,repo.installation_id);fetch_collection(db,repo.installation_id,set(DEMO),transport=steam_fixture,pause=lambda seconds:None)
        for row in db.connection.execute("SELECT package_id FROM packages WHERE workshop_id IN ('123','124','125')").fetchall():set_membership(db,repo.installation_id,row[0],True)
    AppSettings(directory).save(access,auto_online=False,online_notice_seen=True)


def main():
    root=Path(__file__).resolve().parents[1];folder=root/'.test-tmp'/('m64-review-'+uuid4().hex)
    game=make_game(folder/'fictional-game');profile=folder/'profile';seed_profile(game,profile)
    result=dict(game=str(game),profile=str(profile),fictional=True);(folder/'fixture.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return 0

if __name__=='__main__':raise SystemExit(main())
