# Fictional M3 teaching database

`m3_demo.sqlite3` contains **synthetic teaching records only**, exactly as specified
in `M3_SAMPLE_DATA.md`. It has no real collection, user data or usable game assets.
The imaginary E: installation path is a label; generating or browsing this file
never accesses that location. This file is never a production fallback.

Open it with DB Browser for SQLite → Open Database. Browse all seven tables;
BLOB fields appear as bytes/hex. Execute the teaching document's SELECT queries
in Execute SQL. SQL results include full UUIDs. SQLite foreign keys are per
connection: enable `PRAGMA foreign_keys=ON` before experimenting with edits.

Row counts: installations 1, workshop_items 5, scan_runs 7, packages 6,
package_indexes 5, assets 10, scan_issues 6. Active/provisional packages: 5;
current indexes: 3, current assets: 7. B retains 2 assets after corruption;
C retains 1 asset after removal. One original/canonical path is non-UTF-8.

`fictional_records.json` is the complete reproducible fixture, including hex BLOBs.
`python -B -m tools.create_demo` generates the designated artifact only if absent;
it refuses silent overwrite. Tests generate their own isolated copy. No production
database is copied. The delivered closed database uses DELETE journal mode and
needs no WAL/SHM files. Production uses WAL instead.
