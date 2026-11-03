"""Create ONLY the explicitly requested fictional teaching artifact. No game access."""

import json
from pathlib import Path
import sqlite3

from l4d2_mod_db.schema import SCHEMA_SQL, SCHEMA_VERSION
from l4d2_mod_db.storage import validate_schema

PROJECT = Path(__file__).resolve().parents[1]
DEMO = PROJECT / "examples/m3-demo/m3_demo.sqlite3"
RECORDS = PROJECT / "examples/m3-demo/fictional_records.json"


def fictional_records():
    rows = json.loads(RECORDS.read_text(encoding="utf-8"))
    return {table: [{key: bytes.fromhex(value["hex"]) if isinstance(value, dict) else value
                     for key, value in row.items()} for row in records] for table, records in rows.items()}


def create_demo(path: Path = DEMO):
    if path != DEMO and not path.is_relative_to(PROJECT / ".test-tmp"):
        raise ValueError("Demo output must be the designated artifact or isolated test storage.")
    if path.exists() or path.is_symlink():
        raise FileExistsError("Demo already exists; no silent overwrite.")
    for component in (*reversed(path.parent.parents), path.parent):
        info = component.lstat()
        if component.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Demo output refuses reparse paths.")
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA_SQL)
        for table, records in fictional_records().items():
            for row in records:
                connection.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        validate_schema(connection)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        connection.commit()
        # DELETE mode: a closed, self-contained DB Browser artifact without WAL companions.
        assert connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    return path


if __name__ == "__main__":
    print(create_demo())
