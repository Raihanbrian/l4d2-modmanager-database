"""Separate replacement confirmation from source freshness in plain language."""

from dataclasses import dataclass
from .suggestions import suggest_replacement


@dataclass(frozen=True)
class ReplacementReview:
    text: str
    confirmation: str
    freshness: str
    explanation: str


def replacement_review(card,metadata=None):
    effects=[effect for effect in card.effects if effect.active]
    values=tuple(dict.fromkeys(effect.replacement for effect in effects if effect.replacement))
    stale=card.presence_status!='present' or card.index_status!='current'
    freshness='Stale / Needs Review' if stale else 'Current file evidence'
    if values:
        name=values[0] if len(values)==1 else 'Multiple changes'
        if len(values)==1 and any(not effect.replacement for effect in effects):name+=' (+ other changes)'
        old_entry=stale or any(effect.replacement and effect.review_status.startswith('Stale') for effect in effects)
        text=('Stale entry: ' if old_entry else 'Confirmed: ')+name
        return ReplacementReview(text,'User confirmed replacement',freshness,
            'The replacement name was saved by you. Other targets/components may still need review. '+
            ('Source evidence may be outdated after a change or failed refresh. Refresh, inspect and confirm again.' if stale else
             'The files are current, but a saved name refers to older classification evidence. Inspect and confirm it again.' if old_entry else 'Open Edit Info to correct your saved name.'))
    suggestion=suggest_replacement(card,metadata)
    if suggestion.name:
        return ReplacementReview('Suggested: '+suggestion.name,'Suggested / Needs Review',freshness,
            'Needs Review means this is unconfirmed information, not a file error. '+suggestion.reason+' Nothing is saved until Save Changes.')
    return ReplacementReview('Not set · '+('Stale' if stale else 'Needs Review'),'Unknown / Needs Review',freshness,
        ('Stale means evidence may be outdated after source changes or an unsuccessful refresh. Refresh Mods, then inspect Edit Info. ' if stale else
         'Needs Review means a replacement name has not been confirmed. Enter it in Edit Info if you know it. ')+suggestion.reason)


def classification_help(card):
    return ('Stale means the retained evidence may be outdated after changed files or a failed refresh; it does not erase saved names. Refresh and review.'
        if card.review_status.startswith('Stale') else 'User confirmed refers to saved user corrections; it is not proof of gameplay compatibility.'
        if card.review_status=='User confirmed' else 'Needs Review means some information is unconfirmed or unknown. Review the target, replacement and components in Edit Info.')
