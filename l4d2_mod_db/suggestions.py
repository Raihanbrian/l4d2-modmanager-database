"""Deterministic replacement candidates, never persisted or treated as user edits."""

from dataclasses import dataclass
import re

from .references import reference_match
from .workshop_metadata import SOURCE

RULE_VERSION='replacement-title-v2'
_COMPONENT_TITLE=re.compile(r'\b(?:anim(?:ation)?s?|audio|sounds?|voices?|voicelines?|music|sfx|scripts?|vscript|materials?|shaders?|textures?|retextures?|reskins?|hud|portraits?|icons?|fix(?:es)?|patch(?:es)?|particles?|rng|random|packs?|bundles?|collections?|viewmodels?)\b',re.I)
_MULTI=re.compile(r'(?:\s[+&/]\s|\b(?:all survivors|both|versus|vs\.?|and)\b)',re.I)
_NAME=re.compile(r"[^\W_][\w .’'\-]{1,99}",re.UNICODE)
_PERSONA=re.compile(r'(?P<name>.+?) \((?P<outfit>[^()]{1,70})\) - Persona [345](?: Royal| Reload| Golden)?',re.I)
# These are original-slot aliases, not replacement identities. Only this exact
# owner-requested SCAR alias is needed beyond the existing friendly target labels.
_WEAPON_ALIASES={'weapon:weapon_rifle_desert':{'scar','desert rifle'}}


@dataclass(frozen=True)
class ReplacementSuggestion:
    name: str | None
    rule_id: str | None
    reason: str
    title: str | None = None
    target_id: str | None = None
    effect_ids: tuple[str,...] = ()
    rule_version: str = RULE_VERSION


def suggest_replacement(card,metadata=None):
    """Require one fresh original model target and a verified public Steam cache."""
    def unknown(reason):return ReplacementSuggestion(None,None,reason)
    effects=[effect for effect in card.effects if effect.active]
    if any(effect.replacement or (effect.user_edit or {}).get('replacement_mode') in ('value','unknown') for effect in effects):
        return unknown('Your saved replacement choice takes precedence over title suggestions.')
    if card.presence_status!='present' or card.index_status!='current':
        return unknown('The file evidence may be outdated. Refresh Mods before considering a suggestion.')
    if card.review_status.startswith('Stale'):
        return unknown('Saved classification may refer to an earlier source revision. Inspect it before considering a title suggestion.')
    if not metadata or metadata.get('workshop_id')!=card.workshop_id or metadata.get('app_id')!=550 or metadata.get('source')!=SOURCE or not metadata.get('last_success_at') or metadata.get('retrieval_status')!='ok':
        return unknown('No currently successful, verified L4D2 Steam-title cache is available.')
    title=metadata.get('title')
    if not isinstance(title,str) or not title or len(title)>4096:
        return unknown('The cached title is missing or outside the supported limits.')
    # Match a trimmed copy only; provenance and the official cache keep exact text.
    parsed_title=title.strip()
    # Component descriptions are deliberately not character/weapon identities.
    component_words={'sound':r'\b(?:sounds?|voices?|music|audio|sfx)\b','material':r'\b(?:textures?|retextures?|materials?|reskins?)\b',
        'ui':r'\b(?:hud|ui|portraits?|icons?|interface)\b','script':r'\b(?:scripts?|vscript|config)\b'}
    known_components={e.component_id for e in effects if e.evidence}
    base_models=any(v['canonical_path_bytes'].endswith(b'.mdl') for e in effects for v in e.evidence)
    if known_components=={'model'} and re.search(r'\banim(?:ation)?s?\b',parsed_title,re.I) and not _MULTI.search(parsed_title) and len(parsed_title)<=130:
        eligible=tuple(sorted(e.effect_id for e in effects if e.component_id=='model' and e.basis_generation==card.index_generation and not e.review_status.startswith('Stale')))
        if eligible:return ReplacementSuggestion('Animation-related change: '+parsed_title,'animation-title-description',
            'The Steam title describes animation changes and current model paths are indexed. Animation payloads are not evaluated; this is not a whole-model identity.',title,None,eligible)
    if not base_models and not _MULTI.search(parsed_title) and len(known_components)==1:
        component=next(iter(known_components))
        if component in component_words and re.search(component_words[component],parsed_title,re.I) and len(parsed_title)<=150:
            eligible=tuple(sorted(e.effect_id for e in effects if e.component_id==component and e.basis_generation==card.index_generation and not e.review_status.startswith('Stale')))
            if eligible:
                label={'sound':'Sound changes','material':'Texture / material changes','ui':'UI changes','script':'Script / configuration changes'}[component]
                return ReplacementSuggestion(label+': '+parsed_title,'component-description-'+component,
                    'Change description from the exact Steam title, supported by current '+component+' paths. It does not identify a whole-model replacement.',title,None,eligible)
    if _COMPONENT_TITLE.search(parsed_title) or _MULTI.search(parsed_title):
        return unknown('The title describes a component, variation or multiple changes; a complete replacement is ambiguous.')
    known={target for effect in effects for target in effect.target_ids}
    if len(known)!=1:return unknown('A single supported original target is required; multi-target/unknown addons stay unset.')
    target_id=next(iter(known));models=[];labels=set()
    for effect in effects:
        if effect.component_id!='model' or effect.target_ids!=(target_id,) or effect.review_status.startswith('Stale') or effect.basis_generation!=card.index_generation:continue
        if any(evidence['canonical_path_bytes'].endswith(b'.mdl') and evidence.get('basis_generation')==card.index_generation
               and (match:=reference_match(evidence['canonical_path_bytes'])) and match[0]==target_id for evidence in effect.evidence):
            models.append(effect.effect_id);labels.update(effect.target_labels)
    if not models or len(labels)!=1:return unknown('No matching current base-model path supports a complete character/weapon candidate.')
    label=next(iter(labels));survivor=target_id.startswith('survivor:');weapon=target_id.startswith('weapon:')
    tags={tag.casefold() for tag in metadata.get('tags',())}
    survivor_labels={'bill','francis','louis','zoey','coach','ellis','nick','rochelle'}
    named_survivors=tags&survivor_labels
    if tags&{'sounds','scripts','animations'} and 'models' not in tags:
        return unknown('Steam tags emphasize component changes without a Models tag; a complete replacement is ambiguous.')
    if (survivor and ((named_survivors and named_survivors!={label.casefold()}) or 'weapons' in tags)) or (weapon and ('survivors' in tags or named_survivors)):
        return unknown('Steam tags disagree with the supported original target; review both sources first.')
    candidate=None;rule=None
    bracket=re.fullmatch(r'(.+?) \[([^\[\]]+)\]',parsed_title)
    if survivor and bracket and bracket[2].casefold()==label.casefold():
        candidate=bracket[1];rule='survivor-explicit-bracket-slot'
    persona=_PERSONA.fullmatch(parsed_title)
    if survivor and persona and re.search(r'\b(?:costume|outfit|uniform|suit|dress|jacket)\b',persona['outfit'],re.I):
        candidate=persona['name']+' ('+persona['outfit']+')';rule='survivor-persona-outfit'
    parts=parsed_title.split(' - ')
    if survivor and len(parts)==3 and parts[0] in ('Blue Archive','Persona 3','Persona 4','Persona 5') and parts[2].casefold()==label.casefold():
        candidate=parts[1];rule='survivor-franchise-name-slot'
    slot=re.fullmatch(r'(.+?) \(([^()]+)\)',parsed_title)
    if survivor and slot and slot[2].casefold()==label.casefold():
        candidate=slot[1];rule='survivor-explicit-parenthesized-slot'
    explicit=re.fullmatch(r'(.+?) (?:replaces|for) '+re.escape(label),parsed_title,re.I)
    if (survivor or weapon) and explicit:
        candidate=explicit[1];rule='model-explicit-slot-statement'
    if weapon and slot and slot[2].casefold() in ({label.casefold()}|_WEAPON_ALIASES.get(target_id,set())):
        candidate=slot[1];rule='weapon-explicit-parenthesized-slot'
    if not candidate:return unknown('No explicit supported title pattern matched. Keep Not set or enter a correction.')
    # Validate the identity part separately from the recognized outfit suffix.
    identity=persona['name'] if rule=='survivor-persona-outfit' else candidate
    if not _NAME.fullmatch(identity) or len(candidate)>180 or candidate.casefold()==label.casefold():
        return unknown('The candidate name is ambiguous or outside the supported title grammar.')
    return ReplacementSuggestion(candidate,rule,'Suggested from the exact cached Steam title plus one current original model target. '
        'This applies only to the named model effect; other components remain separate. Confirm or correct it in Edit Info.',
        title,target_id,tuple(sorted(models)))
