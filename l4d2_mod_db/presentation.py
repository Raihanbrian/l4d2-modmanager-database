"""Plain catalog fields with independent Steam/local/user provenance."""

TOP_CATEGORIES=('Survivors','Infected','Campaigns','Weapons','Items','Sounds','Scripts','UI','Miscellaneous','Models','Textures')
LOCAL_NAMES={'Survivor':'Survivors','Weapon':'Weapons','Model':'Models','Materials / textures':'Textures','Sound':'Sounds','Script':'Scripts','UI / HUD':'UI','Unknown component':'Miscellaneous'}


def category_labels(card, metadata=None):
    metadata = metadata or {}
    steam = tuple(tag for tag in metadata.get('tags',()) if tag in TOP_CATEGORIES)
    local = tuple(dict.fromkeys(LOCAL_NAMES.get(label,label) for label in card.categories))
    if card.user_edit and card.user_edit['category_mode']=='replace': return local
    return tuple(dict.fromkeys((*steam,*local))) or ('Miscellaneous',)


def original_name(card):
    names = tuple(dict.fromkeys(label for effect in card.effects if effect.active for label in effect.target_labels))
    return names[0] if len(names)==1 else 'Multiple targets' if names else 'Unknown'


def replacement_name(card,metadata=None):
    values = tuple(dict.fromkeys(effect.replacement for effect in card.effects if effect.active and effect.replacement))
    extra=any(effect.active and not effect.replacement for effect in card.effects)
    if values:return values[0]+(' (+ other changes)' if extra else '') if len(values)==1 else 'Multiple changes'
    if metadata:
        from .suggestions import suggest_replacement
        suggestion=suggest_replacement(card,metadata)
        if suggestion.name:return suggestion.name
    return 'Not set'


def steam_name(card, metadata=None):
    if metadata and metadata.get('title'): return metadata['title']
    if card.user_edit and card.user_edit.get('friendly_name'): return card.display_name+' (your name)'
    fallback='Workshop '+card.workshop_id if card.workshop_id else 'Local addon'
    return fallback+(' (info unavailable)' if metadata else ' (not fetched)')


def metadata_discrepancies(card, metadata, targets):
    if not metadata or not metadata.get('title'): return ()
    tags = {tag.casefold() for tag in metadata.get('tags',())}
    steam_survivors = {target['target_id'] for target in targets if target['family']=='survivor' and target['label'].casefold() in tags}
    # Compare Steam claims with raw inferred targets even when a user corrected them.
    from .references import reference_match
    raw = {match[0] for effect in card.effects if effect.active for evidence in effect.evidence
           if (match:=reference_match(evidence['canonical_path_bytes']))}
    local_survivors={target for target in raw if target.startswith('survivor:')}
    issues=[]
    if steam_survivors and local_survivors and steam_survivors.isdisjoint(local_survivors):
        issues.append('Steam survivor tags differ from the local model evidence. Needs Review.')
    if ('Survivors' in metadata.get('tags',()) and raw and all(target.startswith('weapon:') for target in raw)) or ('Weapons' in metadata.get('tags',()) and local_survivors):
        issues.append('Steam category and local target evidence differ. Needs Review.')
    if card.user_edit and card.user_edit['category_mode']=='replace':
        steam={tag for tag in metadata.get('tags',()) if tag in TOP_CATEGORIES}
        if steam and steam.isdisjoint(category_labels(card)): issues.append('Your category differs from Steam tags; your choice is retained.')
    return tuple(issues)
