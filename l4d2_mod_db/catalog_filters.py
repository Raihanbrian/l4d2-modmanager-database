"""Frontend hierarchy with source-labelled matches; never assigns game identifiers."""
from dataclasses import dataclass
from .catalog_view import FAMILIES
from .presentation import category_labels,LOCAL_NAMES,TOP_CATEGORIES

MAJORS=('Survivors','Infected','Weapons','Items','Campaigns','Sounds','Scripts','UI','Miscellaneous')
SURVIVORS=('Bill','Francis','Louis','Zoey','Coach','Ellis','Nick','Rochelle')
FAMILY_LABELS={'Rifle':'Rifles','Shotgun':'Shotguns','SMG':'SMGs','Sniper':'Snipers','Pistol':'Pistols','Melee':'Melee','Other weapons':'Other weapons'}
TARGET_LABELS={'Assault Rifle':'M16','Desert Rifle':'Desert Rifle'}
INFECTED={'Common Infected':('Common Infected',),'Special Infected':('Special Infected',),
    'Tank':('Tank',),'Witch':('Witch',),**{name:('Special Infected',name) for name in ('Boomer','Charger','Hunter','Jockey','Smoker','Spitter')}}


@dataclass(frozen=True)
class FilterEvidence:
    path: tuple[str,...]
    source: str
    detail: str


def filter_evidence(card,metadata,targets):
    """Union of discoverability sources, without promoting tags to verified targets."""
    evidence=set();by_id={t['target_id']:t for t in targets}
    corrected=bool(card.user_edit and card.user_edit['category_mode']=='replace')
    labels={label if label in MAJORS else 'Miscellaneous' for label in category_labels(card,metadata)}
    def add(path,source,detail):
        if not corrected or path[0] in labels:evidence.add(FilterEvidence(tuple(path),source,detail))
    if corrected:
        for label in labels:add((label,),'user category',label)
    else:
        for label in card.categories:
            major=LOCAL_NAMES.get(label,label);add((major if major in MAJORS else 'Miscellaneous',),'local category',label)
        for tag in metadata.get('tags',()):
            if tag in TOP_CATEGORIES:add((tag if tag in MAJORS else 'Miscellaneous',),'Steam tag',tag)
        if not evidence:add(('Miscellaneous',),'unclassified','No supported category')
    tag_targets={}
    for key,t in by_id.items():
        label=TARGET_LABELS.get(t['label'],t['label'])
        if key.startswith('survivor:'):path=('Survivors',label)
        elif key.startswith('weapon:'):
            family=next((name for name,ids in FAMILIES.items() if key[7:] in ids),'Other weapons')
            path=('Weapons',FAMILY_LABELS[family],label)
        else:continue
        for alias in (t['label'],label):tag_targets[alias.casefold()]=path
        if key=='weapon:weapon_rifle_desert':tag_targets['scar']=path
    for effect in card.effects:
        if effect.active:
            for key in effect.target_ids:
                if key in by_id:
                    t=by_id[key];path=tag_targets.get(TARGET_LABELS.get(t['label'],t['label']).casefold())
                    if path:add(path,'user target' if effect.target_source=='user' else 'local target',key)
    for tag in metadata.get('tags',()):
        path=tag_targets.get(tag.casefold())
        if path:add(path,'Steam tag',tag)
        infected=next((path for name,path in INFECTED.items() if name.casefold()==tag.casefold()),None)
        if infected:add(('Infected',*infected),'Steam tag',tag)
        for singular,plural in FAMILY_LABELS.items():
            if tag.casefold() in (singular.casefold(),plural.casefold()):add(('Weapons',plural),'Steam tag',tag)
    return tuple(sorted(evidence,key=lambda item:(item.path,item.source,item.detail)))


def matches_filter(card,metadata,targets,path=()):
    return not path or any(item.path[:len(path)]==tuple(path) for item in filter_evidence(card,metadata,targets))


def filter_options(cards,metadata,targets):
    options={():set()}
    for card in cards:
        for item in filter_evidence(card,metadata.get(card.workshop_id,{}),targets):
            for size in range(len(item.path)+1):options.setdefault(item.path[:size],set()).add(item.source)
    return {path:tuple(sorted(sources)) for path,sources in options.items()}


def path_sort_key(path):
    order=MAJORS if len(path)==1 else SURVIVORS if path and path[0]=='Survivors' else tuple(FAMILY_LABELS.values()) if len(path)==2 and path[0]=='Weapons' else ()
    return (order.index(path[-1]) if path and path[-1] in order else len(order),path[-1:] or ('',))


def filter_caption(path):return 'All Mods' if not path else ' › '.join(path)
