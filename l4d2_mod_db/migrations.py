"""Additive upgrades with a verified app-owned SQLite backup and atomic rollback."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from .extensions import M5_SQL, M5_VERSION, M6_SQL, M61_SQL, M63_SQL, SUPPORTED_VERSIONS
from .references import seed_references
from .storage import CatalogDatabase, CatalogError, _check_component, validate_schema


@dataclass(frozen=True)
class MigrationResult:
    from_version: int
    to_version: int
    backup_path: str
    backup_digest: str


def logical_digest(connection):
    digest = hashlib.sha256()
    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for table in tables:
        # Only schema-validated, internal SQL identifiers enter these queries.
        columns = connection.execute("PRAGMA table_info(" + table + ")").fetchall()
        keys = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        digest.update(table.encode())
        for row in connection.execute("SELECT * FROM " + table + " ORDER BY " + ",".join(keys)):
            encoded = [["blob", value.hex()] if isinstance(value, bytes) else [type(value).__name__, value] for value in row]
            digest.update(json.dumps(encoded, ensure_ascii=True, separators=(",", ":")).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def _backup(database, version, target):
    policy = database.policy
    policy.check()
    folder = policy.directory / "backups"
    if folder.exists() or folder.is_symlink():
        _check_component(folder, directory=True)
    else:
        folder.mkdir()
    _check_component(folder, directory=True)
    if folder.resolve(strict=True).parent != policy.directory.resolve(strict=True):
        raise CatalogError("Backup directory escapes app-owned storage.")
    final = folder / f"catalog-v{version}-to-v{target}-{uuid4().hex}.sqlite3"
    partial = final.with_suffix(".partial")
    descriptor = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    _check_component(partial, directory=False)
    source = destination = None
    try:
        source = sqlite3.connect(policy.database.as_uri() + "?mode=ro", uri=True, isolation_level=None)
        destination = sqlite3.connect(partial, isolation_level=None)
        source.execute("PRAGMA query_only=ON")
        destination.execute("PRAGMA synchronous=FULL")
        destination.execute("PRAGMA temp_store=MEMORY")
        source.backup(destination)
        if destination.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
            raise CatalogError("Backup could not be made standalone.")
        validate_schema(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise CatalogError("Migration backup integrity check failed.")
        fingerprint = logical_digest(destination)
        if fingerprint != logical_digest(database.connection):
            raise CatalogError("Migration backup does not match the locked source snapshot.")
        destination.close(); destination = None
        source.close(); source = None
        policy.check(); _check_component(folder, directory=True); _check_component(partial, directory=False)
        partial.rename(final)
        return str(final), fingerprint
    finally:
        if source is not None: source.close()
        if destination is not None: destination.close()
        # Failed .partial files are never offered as verified recovery backups.


def upgrade(database: CatalogDatabase, *, target_version: int = M5_VERSION, fault=None):
    if target_version not in SUPPORTED_VERSIONS:
        raise CatalogError("Unknown migration target.")
    result = None
    with database.transaction() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        original_version = version
        if version >= target_version:
            return None
        validate_schema(connection)
        backup, fingerprint = _backup(database, version, target_version)
        if fault: fault("after_backup")
        if version == 1 and target_version >= 2:
            for statement in M5_SQL.split(";"):
                if statement.strip(): connection.execute(statement)
            seed_references(connection)
            version = 2
        if version == 2 and target_version >= 3:
            for statement in M6_SQL.split(";"):
                if statement.strip(): connection.execute(statement)
            version = 3
        if version == 3 and target_version >= 4:
            for statement in M61_SQL.split(";"):
                if statement.strip(): connection.execute(statement)
            # Expand the existing category dictionary, without changing user sets.
            connection.executemany("INSERT INTO categories VALUES (?,?) ON CONFLICT DO NOTHING", (
                ('infected','Infected'),('campaign','Campaigns'),('items','Items'),('misc','Miscellaneous')))
            version = 4
        if version == 4 and target_version >= 5:
            for statement in M63_SQL.split(";"):
                if statement.strip(): connection.execute(statement)
            version = 5
        if fault: fault("after_ddl")
        connection.execute(f"PRAGMA user_version={version}")
        validate_schema(connection)
        if fault: fault("before_commit")
        result = MigrationResult(original_version, version, backup, fingerprint)
    return result
