# Developer guide

The player-facing [README](../README.md) describes the product. This document
summarizes the architecture and repeatable checks for contributors.

## Layout

```text
l4d2_mod_db/       scanner, catalog, analysis, desktop and presentation services
tests/            synthetic fixtures and regression tests; live HTTP is mocked
tools/            demo generation, smoke validation and clean source packaging
docs/             public developer/privacy/licensing/conflict/beta guides
release/          portable end-user text and original runtime license notices
examples/m3-demo/ fully fictional teaching SQLite database
.github/          issue-report template
```

Private handoffs, owner milestone notes, real screenshots and review bundles are
kept out of public packaging. Generated `build/`, `dist/`, `.venv/` and `.test-tmp/`
are ignored. Source publishing uses an explicit allowlist; do not zip the workspace.

## Local development

Use Python 3.11+ with Tk for source development; the release build pins CPython
3.14.6 Windows x64 and requirements-build.txt. In a virtual environment:

```powershell
python -m pip install -e ".[desktop]"
python -B -m l4d2_mod_db.desktop
python -B -m unittest discover -s tests -t .
```

`Start-Alpha.cmd` prefers the workspace `.venv` and forwards command-line arguments.
CLI entry points remain `python -m l4d2_mod_db --help` and `l4d2-mod-db --help`.
Do not provide a default real game path in tests. Unit HTTP fixtures must never
depend on Steam being online. Native link tests may skip when OS rights disallow
creation; mocked boundary tests still run. See the owner release report for actual
executed results; this public guide does not claim every machine was tested.

## Boundaries and data model

M1/M2 scope all game access through security.py. The scanner lists only allowed
Workshop files; the VPK index parser does not execute/extract payloads. M3 uses
seven base STRICT SQLite tables: installations, workshop_items, scan_runs,
packages, package_indexes, assets and scan_issues. Package UUIDs are stable across
source changes; inferred Workshop IDs and physical locations are separate.
Original and canonical virtual paths are BLOBs. Failed/incomplete scans retain
last-valid evidence; confirmed completed absence is needed for removal.

Later normalized tables separate reference targets/components/categories, raw
evidence, user overrides, one Planning set and public Steam metadata/tags. Schema
v5 has 23 tables; its only addition to v4 is a nullable bounded raw description.
M6.4 changes no schema, parser, canonicalization or overlap algorithm. Migrations
use verified app-owned backups, transactional DDL and integrity/FK checks.
The original teaching [schema proposal](../M3_SCHEMA_PROPOSAL.md) and
[sample data](../M3_SAMPLE_DATA.md) document the seven-table foundation, not the
entire v5 extension. The demo DB is explicitly fictional and remains v1.

M4 derives overlaps in memory from indexed canonical paths; no conflict table or
severity score is stored. Planning presents selected-pair findings and freshness.
No exact match proves runtime incompatibility or a crash. All Mods is neutral.
See [conflict interpretation](CONFLICTS.md).

M6.4 filter evidence uses semantic hierarchy paths plus independent source/detail
fields (Steam tag, detected/user target, category). The UI merges related choices,
not evidence assertions. Explicit category corrections take precedence; tags do
not assign a canonical target. Unknowns stay unknown. Details keeps catalog-name
and replacement drafts separate and saves atomically with generation checks.

Background metadata uses its own worker/SQLite connection, never holds a write
transaction across HTTP, and respects persistent cache/retry bounds. Only a fixed
Steam HTTPS host/endpoint is used. No URL from a VPK is a network destination.
Descriptions are inert cached text; prose inference remains deferred.

## Build and isolated release checks

```powershell
.\Build-Portable.ps1
python -B -m tools.smoke_portable --launcher
python -B -m tools.smoke_portable --zip dist\L4D2ModDatabase-0.1.0rc4-win-x64.zip
python -B -m tools.prepare_source
```

Use the pinned virtual-environment Python when invoking tools. Smoke checks create
their own synthetic `.test-tmp` game/profile; test first launch, restart, unavailable
root and recovery; validate filters, edits, selected-pair reasons, cache and hashes.
The EXE child has external Python removed from PATH. Developer QA switches refuse
real roots/nonisolated profiles. Do not use them on a real installation.

The PyInstaller spec collects runtime code and required libraries, not the project
tree. SHA256 sidecars accompany release/source ZIPs. Source ZIP ordering/timestamps
are deterministic; onedir binary byte identity across build paths/times is not
promised. Nothing is uploaded. Publication/signing/licensing require owner review.
