"""Small display/filter model; published tags remain distinct from local targets."""
from .presentation import category_labels
from .review import replacement_review
from .suggestions import suggest_replacement

FAMILIES={'Rifle':('weapon_rifle','weapon_rifle_ak47','weapon_rifle_desert','weapon_rifle_sg552','weapon_rifle_m60'),
 'Shotgun':('weapon_pumpshotgun','weapon_shotgun_chrome','weapon_autoshotgun','weapon_shotgun_spas'),
 'SMG':('weapon_smg','weapon_smg_silenced','weapon_smg_mp5'),
 'Sniper':('weapon_hunting_rifle','weapon_sniper_military','weapon_sniper_awp','weapon_sniper_scout'),
 'Pistol':('weapon_pistol','weapon_pistol_magnum'),'Melee':(), 'Other weapons':('weapon_grenade_launcher',)}
ALIASES={'Assault Rifle':'M16','Desert Rifle':'Desert Rifle / SCAR'}

def row_status(card,metadata=None):
    if card.presence_status!='present' or card.index_status!='current' or card.review_status.startswith('Stale'):return 'Stale'
    review=replacement_review(card,metadata)
    if review.confirmation=='User confirmed replacement':return 'Confirmed'
    return 'Suggested' if suggest_replacement(card,metadata).name else 'Needs Review'

def row_replacement(card,metadata=None):
    values=tuple(dict.fromkeys(e.replacement for e in card.effects if e.active and e.replacement))
    return (values[0] if len(values)==1 else 'Multiple changes') if values else suggest_replacement(card,metadata).name or 'Unknown'

def branches(card,metadata,targets):
    """Return (major, family/tag, exact local target) triples, with provenance labels."""
    result=set();by_id={t['target_id']:t for t in targets}
    for effect in card.effects:
        if not effect.active:continue
        for key in effect.target_ids:
            t=by_id.get(key)
            if not t:continue
            label='Local target: '+ALIASES.get(t['label'],t['label'])
            if key.startswith('survivor:'):result.add(('Survivors',label,'All'))
            elif key.startswith('weapon:'):
                family=next((name for name,ids in FAMILIES.items() if key[7:] in ids),'Other weapons')
                result.add(('Weapons',family,label))
    tags=metadata.get('tags',())
    infected={'Common Infected','Special Infected','Tank','Witch','Boomer','Charger','Hunter','Jockey','Smoker','Spitter'}
    for tag in tags:
        if tag in infected:result.add(('Infected','Steam tag: '+tag,'All'))
        if tag in ('Bill','Francis','Louis','Zoey','Coach','Ellis','Nick','Rochelle') and not any(a=='Survivors' and b=='Local target: '+tag for a,b,c in result):
            result.add(('Survivors','Steam tag: '+tag,'All'))
        if tag in FAMILIES:result.add(('Weapons',tag,'All'))
    for major in category_labels(card,metadata):result.add((major,'All','All'))
    return result

def matches_branch(card,metadata,targets,major='All',family='All',target='All'):
    return any((major=='All' or a==major) and (family=='All' or b==family) and (target=='All' or c==target)
               for a,b,c in branches(card,metadata,targets))
