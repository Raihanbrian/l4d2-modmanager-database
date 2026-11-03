# 0.1.0rc4 — draft pre-release notes

M6.4 stabilizes the Windows portable MVP. This draft is for review of a future
portable release. The [source repository](https://github.com/Raihanbrian/l4d2-modmanager-database)
is public; a portable GitHub release has not been published yet. Original source and documentation are licensed
under MIT, copyright (c) 2026 RABrian. Binary redistribution review and final
publication approval remain pending.

## Changes players will notice

- One Category / Target chooser replaces separate Group / target and Local target
  dropdowns. Find Survivors → Rochelle or Weapons → Rifles → Desert Rifle, choose
  All Weapons for the umbrella, or All Mods to clear the filter.
  Cancel is on the left and Use filter on the right.
- Mod Details puts Original Target and Replacement / Change first, with review
  status and Use Suggestion. Custom catalog name is now under More options and
  explains that it does not change the replacement or official Steam title.
- Existing drafts, manual corrections, suggestions, cached Steam information and
  one persistent Planning set are preserved. No schema migration is needed from v5.
- Planning retains the approved Mod / Conflicts with / Reason presentation and
  optional underlying paths. Current selected resource conflicts highlight the
  affected mods in pale red; unaffected, metadata-only and stale rows stay normal.
  A path overlap is not a verified crash; review marks retain the highlight.
- Updated beginner documentation, synthetic screenshots, beta checklist and
  clean source/release preparation; SHA256 sidecars accompany prepared ZIPs.

## Install or update

Extract the whole Windows x64 portable ZIP into a fresh local folder; keep
`_internal` beside `L4D2ModDatabase.exe`. Close old application windows first.
No Python/SQLite/admin install is required for normal use. Existing application
data remains in `%LOCALAPPDATA%\L4D2ModDatabase`; do not delete it to update.
The game stays strictly read-only. The EXE is unsigned; verify its source/hash and
do not disable system security globally to run it.

## Known limits

Conservative suggestions/target dictionary; description inference deferred;
some preview failures use placeholders; offline/private/deleted metadata may be
unavailable; static paths do not validate payloads, scripts, dependencies or engine
limits. Game Active, enabled-state editing, load-order changes, subscriptions and
multiple planning sets are not supported. Full Windows/Steam compatibility and
runtime crash/multiplayer behavior are not certified. Current native-link test
skips and engine path-comparison/VPK v2 coverage limits remain documented.

The owner reported one external M6.3 tester launch/detection success. It is not a
complete test matrix or an external pass for this rebuilt M6.4 binary. Exact final
executed results and remaining gates are in the owner review report; unchecked
checklist items must not be presented as completed tests.
