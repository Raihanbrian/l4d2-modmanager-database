"""Reviewed factual reference data; no downloaded source code or runtime network."""

RULE_VERSION = "classification-v1"
SURVIVOR_SOURCE = "https://github.com/ConfoglTeam/l4d2util/blob/master/scripting/include/l4d2util_constants.inc"
WEAPON_SOURCE = "https://github.com/raziEiL/l4d2_weapons/blob/master/scripting/include/l4d2_weapons.inc"
SCRIPT_SOURCE = "https://github.com/ValveSoftware/source-sdk-2013/blob/master/src/game/shared/weapon_parse.cpp"
COMPONENT_SOURCE = "local:classification-v1/structural-path-rules"

SURVIVORS = (
    ("coach", "Coach"), ("gambler", "Nick"), ("producer", "Rochelle"),
    ("mechanic", "Ellis"), ("manager", "Louis"), ("teenangst", "Zoey"),
    ("namvet", "Bill"), ("biker", "Francis"),
)
# classname, friendly original-slot label, reviewed world-model basename.
WEAPONS = (
    ("weapon_rifle_ak47", "AK-47", "w_rifle_ak47"),
    ("weapon_rifle", "Assault Rifle", "w_rifle_m16a2"),
    ("weapon_rifle_desert", "Desert Rifle", "w_desert_rifle"),
    ("weapon_smg", "Submachine Gun", "w_smg_uzi"),
    ("weapon_smg_silenced", "Silenced SMG", "w_smg_a"),
    ("weapon_pumpshotgun", "Pump Shotgun", "w_shotgun"),
    ("weapon_shotgun_chrome", "Chrome Shotgun", "w_pumpshotgun_a"),
    ("weapon_autoshotgun", "Auto Shotgun", "w_autoshot_m4super"),
    ("weapon_shotgun_spas", "Combat Shotgun", "w_shotgun_spas"),
    ("weapon_hunting_rifle", "Hunting Rifle", "w_sniper_mini14"),
    ("weapon_sniper_military", "Military Sniper", "w_sniper_military"),
    ("weapon_pistol_magnum", "Magnum", "w_desert_eagle"),
    ("weapon_smg_mp5", "MP5", "w_smg_mp5"),
    ("weapon_rifle_sg552", "SG 552", "w_rifle_sg552"),
    ("weapon_sniper_awp", "AWP", "w_sniper_awp"),
    ("weapon_sniper_scout", "Scout", "w_sniper_scout"),
    ("weapon_rifle_m60", "M60", "w_m60"),
    ("weapon_grenade_launcher", "Grenade Launcher", "w_grenade_launcher"),
)
COMPONENTS = (("model", "Model"), ("material", "Materials / textures"), ("sound", "Sound"),
    ("ui", "UI / HUD"), ("script", "Script"), ("other", "Unknown component"))
CATEGORIES = (("weapon", "Weapon"), ("survivor", "Survivor"), *COMPONENTS)


def target_records():
    return [("survivor:" + label.casefold(), label, "survivor", None, SURVIVOR_SOURCE) for _, label in SURVIVORS] + [
        ("weapon:" + classname, label, "weapon", classname, WEAPON_SOURCE) for classname, label, _ in WEAPONS]


def seed_references(connection):
    connection.executemany("INSERT INTO targets VALUES (?,?,?,?,?) ON CONFLICT(target_id) DO NOTHING", target_records())
    connection.executemany("INSERT INTO components VALUES (?,?) ON CONFLICT(component_id) DO NOTHING", COMPONENTS)
    connection.executemany("INSERT INTO categories VALUES (?,?) ON CONFLICT(category_id) DO NOTHING", CATEGORIES)


def reference_match(path: bytes):
    """Only exact reviewed model/sidecar stems or exact known script classnames."""
    for stem, label in SURVIVORS:
        prefix = ("models/survivors/survivor_" + stem).encode()
        if any(path == prefix + suffix for suffix in (b".mdl", b".vvd", b".dx90.vtx", b".dx80.vtx", b".phy")):
            return "survivor:" + label.casefold(), SURVIVOR_SOURCE, "survivor-model-slot"
    for classname, label, model in WEAPONS:
        prefix = ("models/w_models/weapons/" + model).encode()
        if any(path == prefix + suffix for suffix in (b".mdl", b".vvd", b".dx90.vtx", b".dx80.vtx", b".phy")):
            return "weapon:" + classname, WEAPON_SOURCE, "weapon-world-model-slot"
        if path == ("scripts/" + classname + ".txt").encode():
            return "weapon:" + classname, SCRIPT_SOURCE, "weapon-script-slot"
    return None


def component_for(path: bytes) -> str:
    if path.startswith((b"materials/vgui/", b"resource/", b"scripts/hud/")):
        return "ui"
    if path.startswith(b"sound/") and path.endswith((b".wav", b".mp3", b".ogg")):
        return "sound"
    if path.startswith(b"materials/") and path.endswith((b".vmt", b".vtf")):
        return "material"
    if path.startswith(b"models/") and path.endswith((b".mdl", b".vvd", b".vtx", b".phy")):
        return "model"
    if path.startswith(b"scripts/") and path.endswith((b".txt", b".nut", b".cfg")):
        return "script"
    return "other"
