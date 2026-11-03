"""M5 evidence-based components/slots and separate, generation-aware user edits."""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid4, uuid5

from .catalog import _asset, _signature, utc_now
from .references import COMPONENT_SOURCE, RULE_VERSION, component_for, reference_match
from .schema import CANONICALIZATION_VERSION, PARSER_VERSION
from .storage import CatalogError


def rows(connection, sql, parameters=()):
    import sqlite3
    cursor = connection.cursor(); cursor.row_factory = sqlite3.Row
    try: return cursor.execute(sql, parameters).fetchall()
    finally: cursor.close()


def _package_rows(connection, installation_id):
    return rows(connection, """SELECT p.*,ix.generation,ix.parser_version,ix.canonicalization_version,
        ix.source_device_id,ix.source_file_id,ix.source_mode,ix.source_size_bytes,
        ix.source_mtime_ns,ix.source_ctime_ns,ix.source_attributes
        FROM packages p LEFT JOIN package_indexes ix USING(package_id)
        WHERE p.installation_id=? ORDER BY p.relative_path_key,p.package_id""", (installation_id,))


def _current(package):
    return package["removed_at"] is None and package["presence_status"] == "present" and package["index_status"] == "current" and package["generation"] is not None and package["parser_version"] == PARSER_VERSION and package["canonicalization_version"] == CANONICALIZATION_VERSION and _signature(package, "observed_") == _signature(package, "source_")


def refresh_classification(database, installation_id):
    """Only current valid indexes generate fresh automatic evidence. User rows survive."""
    changed = 0
    with database.transaction() as connection:
        for package in _package_rows(connection, installation_id):
            if not _current(package): continue
            package_id, generation = package["package_id"], package["generation"]
            existing = rows(connection, "SELECT * FROM package_effects WHERE package_id=? AND origin='automatic' AND active=1", (package_id,))
            if existing and all(effect["basis_generation"] == generation and effect["rule_version"] == RULE_VERSION for effect in existing):
                continue
            assets = [_asset(asset) for asset in rows(connection, "SELECT * FROM assets WHERE package_id=? ORDER BY canonical_path_bytes", (package_id,))]
            substantive = [asset for asset in assets if asset.canonical_path_bytes not in {b"addoninfo.txt", b"addonimage.jpg"}]
            groups = {}
            for asset in substantive or assets:
                match = reference_match(asset.canonical_path_bytes)
                target, source, rule = match if match else (None, COMPONENT_SOURCE, "structural-component")
                component = component_for(asset.canonical_path_bytes)
                groups.setdefault((component, target), []).append((asset, source, rule))
            if not groups: groups[("other", None)] = []
            connection.execute("UPDATE package_effects SET active=0 WHERE package_id=? AND origin='automatic'", (package_id,))
            categories = set()
            for (component, target), evidence in sorted(groups.items(), key=lambda item: str(item[0])):
                key = component + "|" + (target or "unknown")
                effect_id = uuid5(NAMESPACE_URL, "l4d2-mod-db:" + package_id + ":" + key).hex
                connection.execute("""INSERT INTO package_effects VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(package_id,effect_key) DO UPDATE SET active=1,basis_generation=excluded.basis_generation,
                    rule_version=excluded.rule_version,automatic_status=excluded.automatic_status""",
                    (effect_id, package_id, key, component, "automatic", 1, generation, RULE_VERSION, "inferred" if target else "needs_review"))
                connection.execute("DELETE FROM effect_targets WHERE effect_id=?", (effect_id,))
                connection.execute("DELETE FROM effect_evidence WHERE effect_id=?", (effect_id,))
                if target:
                    connection.execute("INSERT INTO effect_targets VALUES (?,?)", (effect_id, target))
                    categories.add(target.split(":", 1)[0])
                categories.add(component)
                connection.executemany("INSERT INTO effect_evidence VALUES (?,?,?,?,?,?,?)", [
                    (effect_id, asset.canonical_path_bytes, asset.original_path_bytes, generation, rule,
                     "Reference-supported original slot; replacement identity is unknown." if target else
                     "Structural component evidence only; original target and replacement are unknown.", source)
                    for asset, source, rule in evidence])
            connection.execute("DELETE FROM package_categories WHERE package_id=?", (package_id,))
            connection.executemany("INSERT INTO package_categories VALUES (?,?)", [(package_id, category) for category in sorted(categories)])
            changed += 1
    return changed


def _text(value, limit):
    if value is None: return None
    if not isinstance(value, str): raise ValueError("User text must be text.")
    value = value.strip()
    if len(value) > limit: raise ValueError(f"Text must contain at most {limit} characters.")
    try: value.encode("utf-8")
    except UnicodeError: raise ValueError("User text contains unsupported Unicode.") from None
    return value or None


def _editable_package(connection, installation_id, package_id):
    found = [package for package in _package_rows(connection, installation_id) if package["package_id"] == package_id and package["removed_at"] is None]
    if not found: raise CatalogError("Only an active package in the selected installation can be edited.")
    return found[0]


def save_mod_edit(database, installation_id, package_id, *, friendly_name=None, description=None, category_mode="inherit", category_ids=(), expected_generation=None):
    name, description = _text(friendly_name, 256), _text(description, 32768)
    categories = sorted(set(category_ids))
    if category_mode not in {"inherit", "replace"} or (category_mode == "inherit" and categories):
        raise ValueError("Choose inherited categories or an explicit replacement set.")
    with database.transaction() as connection:
        package = _editable_package(connection, installation_id, package_id)
        connection.execute("""INSERT INTO user_mod_edits VALUES (?,?,?,?,?,?) ON CONFLICT(package_id)
            DO UPDATE SET friendly_name=excluded.friendly_name,user_description=excluded.user_description,
            category_mode=excluded.category_mode,basis_generation=excluded.basis_generation,updated_at=excluded.updated_at""",
            (package_id, name, description, category_mode, _basis(package, expected_generation), utc_now()))
        connection.execute("DELETE FROM user_categories WHERE package_id=?", (package_id,))
        connection.executemany("INSERT INTO user_categories VALUES (?,?)", [(package_id, category) for category in categories])


def add_user_effect(database, installation_id, package_id):
    effect_id = uuid4().hex
    with database.transaction() as connection:
        package = _editable_package(connection, installation_id, package_id)
        connection.execute("INSERT INTO package_effects VALUES (?,?,?,?,?,?,?,?,?)",
            (effect_id, package_id, "user:" + effect_id, "other", "user", 1, package["generation"] or 0, RULE_VERSION, "needs_review"))
    return effect_id


def retire_user_effect(database, installation_id, effect_id):
    with database.transaction() as connection:
        effect = rows(connection, "SELECT * FROM package_effects WHERE effect_id=? AND origin='user'", (effect_id,))
        if not effect: raise CatalogError("Only a manually added effect can be retired.")
        _editable_package(connection, installation_id, effect[0]["package_id"])
        connection.execute("UPDATE package_effects SET active=0 WHERE effect_id=?", (effect_id,))


def save_effect_edit(database, installation_id, effect_id, *, target_mode="inherit", target_ids=(),
        replacement_mode="inherit", replacement=None, component_mode="inherit", component_id=None, expected_generation=None):
    targets = sorted(set(target_ids)); replacement = _text(replacement, 512)
    if target_mode not in {"inherit", "replace", "unknown"} or (target_mode == "replace") != bool(targets):
        raise ValueError("Assign at least one known target, inherit evidence, or explicitly choose Unknown.")
    if replacement_mode not in {"inherit", "value", "unknown"} or (replacement_mode == "value") != bool(replacement):
        raise ValueError("Choose a replacement value or explicitly use Unknown/inherited evidence.")
    if component_mode not in {"inherit", "value", "unknown"} or (component_mode == "value") != bool(component_id):
        raise ValueError("Choose an assigned component or inherited/unknown component.")
    with database.transaction() as connection:
        effects = rows(connection, "SELECT * FROM package_effects WHERE effect_id=?", (effect_id,))
        if not effects: raise CatalogError("Effect no longer exists.")
        package = _editable_package(connection, installation_id, effects[0]["package_id"])
        if not effects[0]["active"]: raise CatalogError("Inactive historical corrections are retained; edit an active effect instead.")
        connection.execute("""INSERT INTO effect_user_edits VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(effect_id)
            DO UPDATE SET target_mode=excluded.target_mode,replacement_mode=excluded.replacement_mode,
            replacement_text=excluded.replacement_text,component_mode=excluded.component_mode,component_id=excluded.component_id,
            basis_generation=excluded.basis_generation,updated_at=excluded.updated_at""",
            (effect_id, target_mode, replacement_mode, replacement, component_mode, component_id, _basis(package, expected_generation), utc_now()))
        connection.execute("DELETE FROM effect_user_targets WHERE effect_id=?", (effect_id,))
        connection.executemany("INSERT INTO effect_user_targets VALUES (?,?)", [(effect_id, target) for target in targets])


@dataclass(frozen=True)
class EffectView:
    effect_id: str
    active: bool
    origin: str
    basis_generation: int
    target_ids: tuple[str, ...]
    target_labels: tuple[str, ...]
    game_identifiers: tuple[str | None, ...]
    target_source: str
    replacement: str | None
    replacement_source: str
    component_id: str | None
    component_label: str
    component_source: str
    review_status: str
    evidence: tuple[dict, ...]
    user_edit: dict | None

    @property
    def summary(self):
        return (", ".join(self.target_labels) or "Unknown target") + " → " + (self.replacement or "Unknown replacement") + " (" + self.component_label + ")"


@dataclass(frozen=True)
class CatalogCard:
    package_id: str
    workshop_id: str | None
    filename: str
    display_name: str
    description: str
    categories: tuple[str, ...]
    category_ids: tuple[str, ...]
    components: tuple[str, ...]
    review_status: str
    index_status: str
    presence_status: str
    index_generation: int | None
    effects: tuple[EffectView, ...]
    user_edit: dict | None

    @property
    def summary(self):
        active = [effect.summary for effect in sorted(self.effects, key=lambda effect: (not bool(effect.target_ids), effect.component_label, effect.effect_id)) if effect.active]
        return "; ".join(active) if active else "Unknown target → Unknown replacement (Needs Review)"


def _basis(package, expected):
    if expected is not None and (not isinstance(expected, int) or expected < 0):
        raise ValueError("Evidence generation must be a nonnegative integer.")
    return (package["generation"] or 0) if expected is None else expected


def catalog_cards(connection, installation_id):
    own_snapshot = not connection.in_transaction
    if own_snapshot: connection.execute("BEGIN")
    try: return _catalog_cards(connection, installation_id)
    finally:
        if own_snapshot: connection.rollback()


def _catalog_cards(connection, installation_id):
    cards = []
    target_refs = {row["target_id"]: row for row in rows(connection, "SELECT * FROM targets")}
    components = {row["component_id"]: row["label"] for row in rows(connection, "SELECT * FROM components")}
    categories = {row["category_id"]: row["label"] for row in rows(connection, "SELECT * FROM categories")}
    for package in _package_rows(connection, installation_id):
        if package["removed_at"] is not None: continue
        package_id, generation = package["package_id"], package["generation"] or 0
        current = _current(package)
        mod = rows(connection, "SELECT * FROM user_mod_edits WHERE package_id=?", (package_id,))
        mod = dict(mod[0]) if mod else None
        effects = []
        for effect in rows(connection, "SELECT * FROM package_effects WHERE package_id=? ORDER BY active DESC,effect_key", (package_id,)):
            edit = rows(connection, "SELECT * FROM effect_user_edits WHERE effect_id=?", (effect["effect_id"],))
            edit = dict(edit[0]) if edit else None
            target_mode = edit["target_mode"] if edit else "inherit"
            target_table = "effect_user_targets" if target_mode == "replace" else "effect_targets"
            target_ids = tuple(row[0] for row in rows(connection, f"SELECT target_id FROM {target_table} WHERE effect_id=? ORDER BY target_id", (effect["effect_id"],))) if target_mode != "unknown" else ()
            replacement = edit["replacement_text"] if edit and edit["replacement_mode"] == "value" else None
            component_mode = edit["component_mode"] if edit else "inherit"
            component = edit["component_id"] if component_mode == "value" else None if component_mode == "unknown" else effect["component_id"]
            stale = not current or not effect["active"] or effect["basis_generation"] != generation or effect["rule_version"] != RULE_VERSION or bool(edit and edit["basis_generation"] != generation)
            review = "Stale / Needs Review" if stale else "Needs Review" if not target_ids or not replacement or component in {None, "other"} else "User confirmed" if edit and target_mode == "replace" else "Inferred / Needs Review"
            evidence = tuple(dict(row) for row in rows(connection, "SELECT * FROM effect_evidence WHERE effect_id=? ORDER BY canonical_path_bytes", (effect["effect_id"],)))
            effects.append(EffectView(effect["effect_id"], bool(effect["active"]), effect["origin"], effect["basis_generation"], target_ids,
                tuple(target_refs[target]["label"] for target in target_ids), tuple(target_refs[target]["canonical_game_id"] for target in target_ids),
                "user" if target_mode != "inherit" else "inferred" if target_ids else "unknown", replacement,
                "user" if edit and edit["replacement_mode"] != "inherit" else "unknown", component, components.get(component, "Unknown component"),
                "user" if component_mode != "inherit" else "inferred", review, evidence, edit))
        active = [effect for effect in effects if effect.active]
        category_table = "user_categories" if mod and mod["category_mode"] == "replace" else "package_categories"
        category_ids = tuple(row[0] for row in rows(connection, f"SELECT category_id FROM {category_table} WHERE package_id=? ORDER BY category_id", (package_id,)))
        target_names = sorted({label for effect in active for label in effect.target_labels})
        fallback = ", ".join(target_names) + " addon" if target_names else ", ".join(sorted({effect.component_label for effect in active})) + " addon" if active else "Unclassified addon"
        name = mod["friendly_name"] if mod and mod["friendly_name"] else fallback + " · " + (package["workshop_id"] or package["relative_path"].rsplit("/", 1)[-1])
        stale = not current or bool(mod and mod["basis_generation"] != generation) or any(effect.review_status.startswith("Stale") for effect in active)
        review = "Stale / Needs Review" if stale else "User confirmed" if active and all(effect.review_status == "User confirmed" for effect in active) else "Needs Review"
        cards.append(CatalogCard(package_id, package["workshop_id"], package["relative_path"].rsplit("/", 1)[-1], name,
            mod["user_description"] or "" if mod else "", tuple(categories[category] for category in category_ids), category_ids,
            tuple(sorted({effect.component_label for effect in active})), review, package["index_status"], package["presence_status"],
            package["generation"], tuple(effects), mod))
    return tuple(cards)


def classification_statistics(cards):
    active_effects = [effect for card in cards for effect in card.effects if effect.active]
    return dict(packages=len(cards), packages_with_supported_or_user_target=sum(any(effect.target_ids for effect in card.effects if effect.active) for card in cards),
        packages_with_current_target_evidence=sum(not card.review_status.startswith("Stale") and any(effect.target_ids for effect in card.effects if effect.active) for card in cards),
        packages_with_unknown_original_target=sum(not any(effect.target_ids for effect in card.effects if effect.active) for card in cards),
        packages_needing_review=sum(card.review_status != "User confirmed" for card in cards),
        effects=len(active_effects), effects_with_original_target=sum(bool(effect.target_ids) for effect in active_effects),
        effects_with_unknown_target=sum(not effect.target_ids for effect in active_effects),
        stale_effects=sum(effect.review_status.startswith("Stale") for effect in active_effects),
        replacement_identities_known=sum(bool(effect.replacement) for effect in active_effects),
        replacement_identities_unknown=sum(not effect.replacement for effect in active_effects),
        automatically_identified_replacement_identities=0)
