"""App-owned SQLite boundary. Never opens a game file or accepts a CLI DB path."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path, PureWindowsPath
import sqlite3
import stat

from .schema import SCHEMA_SQL, SCHEMA_VERSION
from .extensions import SUPPORTED_VERSIONS, extension_sql
from .security import PathPolicyError, ScopedWorkshopAccess


class CatalogError(RuntimeError):
    """Safe diagnostic, without OS paths or arbitrary SQLite error text."""


def root_key(path: str | Path) -> str:
    """location-key-v1; input must already have passed root security checks."""
    return PureWindowsPath(path).as_posix().casefold()


def _check_component(path: Path, *, directory: bool) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise CatalogError("App storage refuses symlinks, junctions and reparse points.")
    if directory and not stat.S_ISDIR(info.st_mode):
        raise CatalogError("App storage requires regular directories.")
    if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
        raise CatalogError("App database and sidecars must be regular single-link files.")


@dataclass(frozen=True)
class StoragePolicy:
    directory: Path
    game_root: Path | None

    @classmethod
    def production(cls, access: ScopedWorkshopAccess, *, create: bool = True) -> StoragePolicy:
        raw = os.environ.get("LOCALAPPDATA", "")
        base = Path(raw)
        if not raw or not base.is_absolute() or raw.startswith(("\\\\", "//")) or ".." in base.parts:
            raise CatalogError("An absolute local LOCALAPPDATA directory is required; no fallback is permitted.")
        policy = cls(base / "L4D2ModDatabase", access.validated_root)
        if create:
            policy.prepare()
        else:
            policy.check()
        return policy

    @classmethod
    def isolated_test(cls, directory: Path, access: ScopedWorkshopAccess) -> StoragePolicy:
        allowed = Path(__file__).resolve().parents[1] / ".test-tmp"
        if not directory.is_absolute() or not directory.is_relative_to(allowed) or directory == allowed:
            raise CatalogError("Test storage must be isolated under the repository .test-tmp directory.")
        policy = cls(directory, access.validated_root)
        policy.prepare()
        return policy

    @property
    def database(self) -> Path:
        return self.directory / "catalog.sqlite3"

    def check(self) -> None:
        if not self.directory.is_absolute() or ".." in self.directory.parts:
            raise CatalogError("App storage requires an absolute path without traversal.")
        if self.game_root is not None and (
            self.directory.is_relative_to(self.game_root) or self.game_root.is_relative_to(self.directory)
        ):
            raise CatalogError("App storage must be disjoint from the selected game tree.")
        for component in (*reversed(self.directory.parents), self.directory):
            if component.exists() or component.is_symlink():
                _check_component(component, directory=True)
        # Resolve only after rejecting reparse components. Native aliases (e.g.
        # Windows 8.3 spellings) must not bypass the game/app-data separation.
        resolved = self.directory.resolve(strict=True) if self.directory.exists() else self.directory.parent.resolve(strict=True) / self.directory.name
        if self.game_root is not None and (
            resolved.is_relative_to(self.game_root) or self.game_root.is_relative_to(resolved)
        ):
            raise CatalogError("Resolved app storage must be disjoint from the selected game tree.")
        for suffix in ("", "-wal", "-shm", "-journal"):
            candidate = self.directory / ("catalog.sqlite3" + suffix)
            if candidate.exists() or candidate.is_symlink():
                _check_component(candidate, directory=False)

    def prepare(self) -> None:
        self.check()
        # Only the dedicated final directory is created; never invent missing ancestors.
        self.directory.mkdir(exist_ok=True)
        self.check()


def _schema_shape(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return [tuple(row) for row in connection.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    )]


def validate_schema(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in SUPPORTED_VERSIONS:
        raise CatalogError("Unsupported catalog schema version.")
    expected = sqlite3.connect(":memory:")
    try:
        expected.executescript(SCHEMA_SQL + extension_sql(version))
        if _schema_shape(connection) != _schema_shape(expected):
            raise CatalogError("Catalog schema differs from a supported version; automatic repair is refused.")
    finally:
        expected.close()
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise CatalogError("Catalog foreign-key validation failed.")
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise CatalogError("Catalog integrity validation failed.")


class CatalogDatabase:
    def __init__(self, policy: StoragePolicy):
        self.policy = policy
        self.connection: sqlite3.Connection | None = None
        try:
            policy.prepare()
            if sqlite3.sqlite_version_info < (3, 37, 0):
                raise CatalogError("SQLite 3.37 or newer is required for STRICT tables.")
            self.connection = sqlite3.connect(policy.database, isolation_level=None, timeout=5)
            self.connection.row_factory = sqlite3.Row
            connection = self.connection
            for pragma in ("foreign_keys=ON", "busy_timeout=5000", "temp_store=MEMORY", "synchronous=FULL"):
                connection.execute("PRAGMA " + pragma)
            if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise CatalogError("Catalog requires WAL journal mode.")
            checks = {"foreign_keys": 1, "busy_timeout": 5000, "temp_store": 2, "synchronous": 2}
            if any(connection.execute("PRAGMA " + key).fetchone()[0] != value for key, value in checks.items()):
                raise CatalogError("Required SQLite connection safeguards could not be enabled.")
            with self.transaction():
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    if _schema_shape(connection):
                        raise CatalogError("Unversioned existing database refused.")
                    for statement in SCHEMA_SQL.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                elif version not in SUPPORTED_VERSIONS:
                    raise CatalogError("Unsupported catalog schema version; reviewed migration required.")
            validate_schema(connection)
        except BaseException as error:
            self.close()
            if isinstance(error, (sqlite3.Error, OSError, PathPolicyError)):
                raise CatalogError("Catalog storage could not be opened safely.") from None
            raise

    @contextmanager
    def transaction(self):
        self.policy.check()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
            self.policy.check()
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class CatalogReader:
    """Existing app catalog only: no creation, migrations, registration or writes.

    Do not use immutable=1: that can ignore a live WAL. SQLite may coordinate
    WAL shared-memory sidecars in the same app directory; catalog rows stay read-only.
    """

    def __init__(self, policy: StoragePolicy):
        self.policy, self.connection = policy, None
        try:
            policy.check()
            if not policy.database.is_file():
                raise CatalogError("No saved catalog exists; run --index --catalog first.")
            self.connection = sqlite3.connect(policy.database.as_uri() + "?mode=ro", uri=True, isolation_level=None, timeout=5)
            self.connection.row_factory = sqlite3.Row
            for pragma in ("query_only=ON", "foreign_keys=ON", "busy_timeout=5000", "temp_store=MEMORY"):
                self.connection.execute("PRAGMA " + pragma)
            if self.connection.execute("PRAGMA user_version").fetchone()[0] not in SUPPORTED_VERSIONS:
                raise CatalogError("Unsupported catalog schema version; no analysis performed.")
            if self.connection.execute("PRAGMA query_only").fetchone()[0] != 1:
                raise CatalogError("Read-only catalog safeguards could not be enabled.")
            validate_schema(self.connection)
            policy.check()
        except BaseException as error:
            self.close()
            if isinstance(error, (sqlite3.Error, OSError)):
                raise CatalogError("Saved catalog could not be read safely.") from None
            raise

    def installation_id(self, access: ScopedWorkshopAccess) -> str:
        root = access.validated_root
        row = self.connection.execute("SELECT installation_id,root_path FROM installations WHERE root_key=?", (root_key(root),)).fetchone()
        if row is None:
            raise CatalogError("The explicitly selected installation has no saved catalog.")
        if Path(row["root_path"]) != root:
            raise CatalogError("Root comparison-key collision; analysis refused.")
        return row["installation_id"]

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
