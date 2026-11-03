"""Approved M3 schema v1. No later-milestone tables."""

SCHEMA_VERSION = 1
PARSER_VERSION = "vpk-index-v1"
CANONICALIZATION_VERSION = "vpk-path-v1"
LOCATION_KEY_VERSION = "location-key-v1"

SCHEMA_SQL = r'''
CREATE TABLE installations (
    installation_id TEXT NOT NULL PRIMARY KEY,
    root_path TEXT NOT NULL,
    root_key TEXT NOT NULL UNIQUE,
    catalog_generation INTEGER NOT NULL DEFAULT 0
        CHECK (catalog_generation >= 0),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE workshop_items (
    workshop_id TEXT NOT NULL PRIMARY KEY
        CHECK (length(workshop_id) > 0
               AND workshop_id NOT GLOB '*[^0-9]*'),
    first_seen_at TEXT NOT NULL
) STRICT;

CREATE TABLE scan_runs (
    scan_id INTEGER PRIMARY KEY,
    installation_id TEXT NOT NULL
        REFERENCES installations(installation_id) ON DELETE RESTRICT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN
        ('started','committed','failed','interrupted','superseded')),
    directory_status TEXT CHECK (directory_status IN
        ('complete','missing','partial','unavailable','rejected')),
    base_generation INTEGER NOT NULL CHECK (base_generation >= 0),
    committed_generation INTEGER CHECK (committed_generation >= 0),
    UNIQUE (installation_id, scan_id),
    CHECK ((outcome = 'started' AND finished_at IS NULL)
        OR (outcome <> 'started' AND finished_at IS NOT NULL)),
    CHECK ((outcome = 'committed' AND committed_generation IS NOT NULL
            AND committed_generation = base_generation + 1
            AND directory_status IS NOT NULL)
        OR (outcome <> 'committed' AND committed_generation IS NULL))
) STRICT;

CREATE TABLE packages (
    package_id TEXT NOT NULL PRIMARY KEY,
    installation_id TEXT NOT NULL
        REFERENCES installations(installation_id) ON DELETE RESTRICT,
    workshop_id TEXT
        REFERENCES workshop_items(workshop_id) ON DELETE RESTRICT,
    relative_path TEXT NOT NULL,
    relative_path_key TEXT NOT NULL,
    presence_status TEXT NOT NULL CHECK (presence_status IN
        ('present','missing_pending','unavailable','removed')),
    index_status TEXT NOT NULL CHECK (index_status IN
        ('pending','current','error','unavailable')),
    observed_device_id TEXT NOT NULL,
    observed_file_id TEXT NOT NULL,
    observed_mode INTEGER NOT NULL CHECK (observed_mode >= 0),
    observed_size_bytes INTEGER NOT NULL CHECK (observed_size_bytes >= 0),
    observed_mtime_ns INTEGER NOT NULL,
    observed_ctime_ns INTEGER NOT NULL,
    observed_attributes INTEGER NOT NULL CHECK (observed_attributes >= 0),
    preview_relative_path TEXT,
    preview_status TEXT NOT NULL CHECK (preview_status IN
        ('present','missing','unknown')),
    first_seen_scan_id INTEGER NOT NULL,
    last_seen_scan_id INTEGER NOT NULL,
    state_scan_id INTEGER NOT NULL,
    removed_at TEXT,
    UNIQUE (installation_id, package_id),
    FOREIGN KEY (installation_id, first_seen_scan_id)
        REFERENCES scan_runs(installation_id, scan_id) ON DELETE RESTRICT,
    FOREIGN KEY (installation_id, last_seen_scan_id)
        REFERENCES scan_runs(installation_id, scan_id) ON DELETE RESTRICT,
    FOREIGN KEY (installation_id, state_scan_id)
        REFERENCES scan_runs(installation_id, scan_id) ON DELETE RESTRICT,
    CHECK ((presence_status = 'removed') = (removed_at IS NOT NULL)),
    CHECK (presence_status <> 'removed' OR index_status = 'unavailable'),
    CHECK (index_status <> 'current' OR presence_status = 'present'),
    CHECK (preview_status <> 'present' OR preview_relative_path IS NOT NULL),
    CHECK (preview_status <> 'missing' OR preview_relative_path IS NULL)
) STRICT;

CREATE UNIQUE INDEX uq_packages_active_location
    ON packages(installation_id, relative_path_key)
    WHERE removed_at IS NULL;

CREATE TABLE package_indexes (
    package_id TEXT NOT NULL PRIMARY KEY,
    installation_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    indexed_scan_id INTEGER NOT NULL,
    vpk_version INTEGER NOT NULL CHECK (vpk_version IN (1,2)),
    tree_size INTEGER NOT NULL CHECK (tree_size > 0),
    index_sha256 BLOB NOT NULL CHECK (length(index_sha256) = 32),
    parser_version TEXT NOT NULL,
    canonicalization_version TEXT NOT NULL,
    source_device_id TEXT NOT NULL,
    source_file_id TEXT NOT NULL,
    source_mode INTEGER NOT NULL CHECK (source_mode >= 0),
    source_size_bytes INTEGER NOT NULL CHECK (source_size_bytes >= 0),
    source_mtime_ns INTEGER NOT NULL,
    source_ctime_ns INTEGER NOT NULL,
    source_attributes INTEGER NOT NULL CHECK (source_attributes >= 0),
    FOREIGN KEY (installation_id, package_id)
        REFERENCES packages(installation_id, package_id) ON DELETE RESTRICT,
    FOREIGN KEY (installation_id, indexed_scan_id)
        REFERENCES scan_runs(installation_id, scan_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE assets (
    package_id TEXT NOT NULL
        REFERENCES package_indexes(package_id) ON DELETE CASCADE,
    canonical_path_bytes BLOB NOT NULL CHECK (length(canonical_path_bytes) > 0),
    original_path_bytes BLOB NOT NULL CHECK (length(original_path_bytes) > 0),
    utf8_valid INTEGER NOT NULL CHECK (utf8_valid IN (0,1)),
    crc32 INTEGER NOT NULL CHECK (crc32 BETWEEN 0 AND 4294967295),
    preload_bytes INTEGER NOT NULL CHECK (preload_bytes BETWEEN 0 AND 65535),
    archive_index INTEGER NOT NULL CHECK (archive_index BETWEEN 0 AND 32767),
    archive_offset INTEGER NOT NULL CHECK (archive_offset BETWEEN 0 AND 4294967295),
    archive_length INTEGER NOT NULL CHECK (archive_length BETWEEN 0 AND 4294967295),
    PRIMARY KEY (package_id, canonical_path_bytes),
    UNIQUE (package_id, original_path_bytes)
) STRICT, WITHOUT ROWID;

CREATE TABLE scan_issues (
    issue_id INTEGER PRIMARY KEY,
    installation_id TEXT NOT NULL,
    scan_id INTEGER NOT NULL,
    package_id TEXT,
    relative_path TEXT,
    severity TEXT NOT NULL CHECK (severity IN ('warning','error')),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY (installation_id, scan_id)
        REFERENCES scan_runs(installation_id, scan_id) ON DELETE RESTRICT,
    FOREIGN KEY (installation_id, package_id)
        REFERENCES packages(installation_id, package_id) ON DELETE RESTRICT
) STRICT;

CREATE INDEX ix_scan_runs_installation_time
    ON scan_runs(installation_id, started_at, scan_id);
CREATE INDEX ix_packages_workshop ON packages(workshop_id);
CREATE INDEX ix_packages_state
    ON packages(installation_id, presence_status, index_status);
CREATE INDEX ix_packages_first_seen
    ON packages(installation_id, first_seen_scan_id);
CREATE INDEX ix_packages_last_seen
    ON packages(installation_id, last_seen_scan_id);
CREATE INDEX ix_packages_state_scan
    ON packages(installation_id, state_scan_id);
CREATE INDEX ix_indexes_scan
    ON package_indexes(installation_id, indexed_scan_id);
CREATE INDEX ix_assets_canonical
    ON assets(canonical_path_bytes, package_id);
CREATE INDEX ix_issues_scan ON scan_issues(scan_id, issue_id);
CREATE INDEX ix_issues_package ON scan_issues(package_id, scan_id);
'''
