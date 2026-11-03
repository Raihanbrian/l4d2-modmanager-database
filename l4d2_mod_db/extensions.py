"""Additive M5/M6/M6.1 schemas. The approved v1/demo DDL stays immutable."""

M5_VERSION = 2
M6_VERSION = 3
M61_VERSION = 4
SUPPORTED_VERSIONS = (1, 2, 3, 4, 5)
M63_VERSION = 5

M5_SQL = r'''
CREATE TABLE targets (
    target_id TEXT PRIMARY KEY NOT NULL,
    label TEXT NOT NULL,
    family TEXT NOT NULL CHECK(family IN ('weapon','survivor','other')),
    canonical_game_id TEXT,
    reference_url TEXT NOT NULL
) STRICT;
CREATE TABLE components (
    component_id TEXT PRIMARY KEY NOT NULL,
    label TEXT NOT NULL UNIQUE
) STRICT;
CREATE TABLE categories (
    category_id TEXT PRIMARY KEY NOT NULL,
    label TEXT NOT NULL UNIQUE
) STRICT;
CREATE TABLE package_effects (
    effect_id TEXT PRIMARY KEY NOT NULL,
    package_id TEXT NOT NULL REFERENCES packages(package_id) ON DELETE RESTRICT,
    effect_key TEXT NOT NULL,
    component_id TEXT NOT NULL REFERENCES components(component_id) ON DELETE RESTRICT,
    origin TEXT NOT NULL CHECK(origin IN ('automatic','user')),
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    basis_generation INTEGER NOT NULL CHECK(basis_generation>=0),
    rule_version TEXT NOT NULL,
    automatic_status TEXT NOT NULL CHECK(automatic_status IN ('inferred','needs_review')),
    UNIQUE(package_id,effect_key)
) STRICT;
CREATE TABLE effect_targets (
    effect_id TEXT NOT NULL REFERENCES package_effects(effect_id) ON DELETE RESTRICT,
    target_id TEXT NOT NULL REFERENCES targets(target_id) ON DELETE RESTRICT,
    PRIMARY KEY(effect_id,target_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE effect_evidence (
    effect_id TEXT NOT NULL REFERENCES package_effects(effect_id) ON DELETE RESTRICT,
    canonical_path_bytes BLOB NOT NULL CHECK(length(canonical_path_bytes)>0),
    original_path_bytes BLOB NOT NULL CHECK(length(original_path_bytes)>0),
    basis_generation INTEGER NOT NULL CHECK(basis_generation>=1),
    rule_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    source_url TEXT NOT NULL,
    PRIMARY KEY(effect_id,canonical_path_bytes)
) STRICT, WITHOUT ROWID;
CREATE TABLE package_categories (
    package_id TEXT NOT NULL REFERENCES packages(package_id) ON DELETE RESTRICT,
    category_id TEXT NOT NULL REFERENCES categories(category_id) ON DELETE RESTRICT,
    PRIMARY KEY(package_id,category_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE user_mod_edits (
    package_id TEXT PRIMARY KEY NOT NULL REFERENCES packages(package_id) ON DELETE RESTRICT,
    friendly_name TEXT CHECK(length(friendly_name)<=256),
    user_description TEXT CHECK(length(user_description)<=32768),
    category_mode TEXT NOT NULL CHECK(category_mode IN ('inherit','replace')),
    basis_generation INTEGER NOT NULL CHECK(basis_generation>=0),
    updated_at TEXT NOT NULL
) STRICT;
CREATE TABLE user_categories (
    package_id TEXT NOT NULL REFERENCES user_mod_edits(package_id) ON DELETE RESTRICT,
    category_id TEXT NOT NULL REFERENCES categories(category_id) ON DELETE RESTRICT,
    PRIMARY KEY(package_id,category_id)
) STRICT, WITHOUT ROWID;
CREATE TABLE effect_user_edits (
    effect_id TEXT PRIMARY KEY NOT NULL REFERENCES package_effects(effect_id) ON DELETE RESTRICT,
    target_mode TEXT NOT NULL CHECK(target_mode IN ('inherit','replace','unknown')),
    replacement_mode TEXT NOT NULL CHECK(replacement_mode IN ('inherit','value','unknown')),
    replacement_text TEXT CHECK(length(replacement_text)<=512),
    component_mode TEXT NOT NULL CHECK(component_mode IN ('inherit','value','unknown')),
    component_id TEXT REFERENCES components(component_id) ON DELETE RESTRICT,
    basis_generation INTEGER NOT NULL CHECK(basis_generation>=0),
    updated_at TEXT NOT NULL,
    CHECK((replacement_mode='value')=(replacement_text IS NOT NULL)),
    CHECK(replacement_text IS NULL OR length(replacement_text)>0),
    CHECK((component_mode='value')=(component_id IS NOT NULL))
) STRICT;
CREATE TABLE effect_user_targets (
    effect_id TEXT NOT NULL REFERENCES effect_user_edits(effect_id) ON DELETE RESTRICT,
    target_id TEXT NOT NULL REFERENCES targets(target_id) ON DELETE RESTRICT,
    PRIMARY KEY(effect_id,target_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX ix_effects_package ON package_effects(package_id,active);
CREATE INDEX ix_effect_targets_target ON effect_targets(target_id,effect_id);
CREATE INDEX ix_user_targets_target ON effect_user_targets(target_id,effect_id);
CREATE INDEX ix_package_categories_category ON package_categories(category_id,package_id);
CREATE INDEX ix_user_categories_category ON user_categories(category_id,package_id);
'''


M6_SQL = r'''
CREATE TABLE planning_sets (
    installation_id TEXT PRIMARY KEY NOT NULL REFERENCES installations(installation_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
) STRICT;
CREATE TABLE planning_members (
    installation_id TEXT NOT NULL REFERENCES planning_sets(installation_id) ON DELETE RESTRICT,
    package_id TEXT NOT NULL,
    PRIMARY KEY(installation_id,package_id),
    FOREIGN KEY(installation_id,package_id) REFERENCES packages(installation_id,package_id) ON DELETE RESTRICT
) STRICT, WITHOUT ROWID;
CREATE INDEX ix_planning_members_package ON planning_members(package_id,installation_id);
'''


def extension_sql(version: int) -> str:
    if version == 1:
        return ""
    if version == 2:
        return M5_SQL
    if version == 3:
        return M5_SQL + M6_SQL
    if version == 4:
        return M5_SQL + M6_SQL + M61_SQL
    if version == 5:
        return M5_SQL + M6_SQL + M61_SQL + M63_SQL
    raise ValueError("Unsupported schema version")


M61_SQL = r'''
CREATE TABLE workshop_metadata (
    workshop_id TEXT PRIMARY KEY NOT NULL REFERENCES workshop_items(workshop_id) ON DELETE RESTRICT,
    title TEXT CHECK(length(title)<=4096),
    app_id INTEGER,
    source TEXT NOT NULL CHECK(source='Steam GetPublishedFileDetails v1'),
    last_success_at TEXT,
    last_attempt_at TEXT NOT NULL,
    next_attempt_at TEXT NOT NULL,
    retrieval_status TEXT NOT NULL CHECK(retrieval_status IN ('ok','unavailable','wrong_app','malformed','network_error','rate_limited')),
    result_code INTEGER,
    diagnostic TEXT NOT NULL,
    CHECK((title IS NULL AND app_id IS NULL AND last_success_at IS NULL) OR
          (title IS NOT NULL AND length(title)>0 AND app_id=550 AND last_success_at IS NOT NULL))
) STRICT;
CREATE TABLE steam_tags (
    tag_id INTEGER PRIMARY KEY,
    value TEXT NOT NULL UNIQUE COLLATE BINARY CHECK(length(value)>0 AND length(value)<=256)
) STRICT;
CREATE TABLE workshop_item_tags (
    workshop_id TEXT NOT NULL REFERENCES workshop_metadata(workshop_id) ON DELETE RESTRICT,
    tag_id INTEGER NOT NULL REFERENCES steam_tags(tag_id) ON DELETE RESTRICT,
    PRIMARY KEY(workshop_id,tag_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX ix_workshop_item_tags_tag ON workshop_item_tags(tag_id,workshop_id);
'''

M63_SQL = '''
ALTER TABLE workshop_metadata ADD COLUMN description_raw TEXT CHECK(length(description_raw)<=65536);
'''
