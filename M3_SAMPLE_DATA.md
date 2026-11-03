# M3 sample data — complete fictional teaching dataset

Implementation status, 29 October 2026: M3 is approved and implemented. The
separate synthetic database at `examples/m3-demo/m3_demo.sqlite3` contains exactly
these records. Tests executed all four queries and checked every expected result
cell, exact records/BLOBs, schema, FK and integrity checks. References below to
unexecuted SQL/design-only status describe the original pre-approval authoring
phase. The dataset remains entirely fictional.

Prepared 26 October 2026. **Original design-review status: No SQLite database, migration,
M3 implementation, GUI or classification engine has been created.** Every
installation, Workshop ID, package, OS file identity, title and event in this
document is fictional. Nothing was copied from the owner's real Workshop
collection. The `E:\FictionalSteam` path is an illustration and was not accessed.

This is the authoritative shared dataset for examples in
[M3_SCHEMA_PROPOSAL.md](M3_SCHEMA_PROPOSAL.md) and the future
[UI contract](UI_DATA_PRESENTATION_CONTRACT.md). The latter adds explicitly
fictional future user/metadata/classification values that do not exist in these
M3 rows.

All seven tables show **every proposed column**. Wide tables are split into views
joined by their full PK. SQL NULL is unquoted `NULL` in the actual model; Markdown
code formatting is only for readability. Columns named `reading_alias` below
are teaching aids, not schema columns. Full UUIDs, not aliases, appear in all PK/FK
cells. No row relies on an undefined ID.

## 1. Reading aids and final snapshot

| `reading_alias` | `uuid` | `meaning` |
| --- | --- | --- |
| `I` | `7c1a9e306b454d0d9a651827d9f3ac10` | `Fictional selected installation` |
| `A` | `0cda40ac6e9b4a31b8876270e6b508a1` | `Successful in-place update, latest index generation 2` |
| `B` | `3a2f7c196d404b8a9e650aa243b9e702` | `Corrupt update; last valid generation 1 retained` |
| `C` | `9b065137e4a4481bb3f07252c401d5a3` | `Confirmed removed; inactive row and index retained` |
| `D` | `f14a0cd2791e4ca1b64f2387ce890ad4` | `New/changing nonnumeric candidate, no valid index` |
| `E` | `5e9d71346c2741f4a8803d96b3a429e5` | `Current package with multiple fictional effects` |
| `F` | `a1706e2b2f09422d9ca47f6a315dc8f6` | `Current sound/UI component package` |

The final committed catalog is generation **6**. There are six package records,
five nonremoved/provisional packages, five retained indexes and ten retained
asset rows. Three packages have current indexes (A/E/F, seven assets). B's two
assets and removed C's one asset are retained but not current. D has no index.
There are five inferred Workshop item rows; D's ID is NULL. One path is not UTF-8.

The retained archive directories, CRCs, tree sizes and SHA-256 digests were
calculated from tiny **in-memory synthetic VPK fixtures** using the existing M2
fixture builder/parser. Payloads are repeating placeholder bytes, not real game
models/images/audio. OS stat identities/times are fictional assignments. No VPK
was written to a game folder; no SQL was executed. These are realistic catalog
shapes and internally matching metadata, not usable gameplay addons.

## 2. Canonical root and location keys

For the fictional selected root:

```text
root_path = E:\FictionalSteam\steamapps\common\Left 4 Dead 2
root_key  = e:/fictionalsteam/steamapps/common/left 4 dead 2

relative_path     = left4dead2/addons/workshop/9100001001.VPK
relative_path_key = left4dead2/addons/workshop/9100001001.vpk
```

Proposed policy tag: **location-key-v1**.

1. Actual runtime selection first passes M2's absolute-local-root, structural,
   component/reparse and containment checks. Reject literal `..`, UNC/device
   inputs and unsafe paths before resolution. Never turn a rejected path into
   an accepted one by normalizing away traversal.
2. After those checks, use the strict resolved native Windows root as
   `root_path`. Native path resolution supplies its canonical absolute spelling;
   it is not a recursive search. Preserve directory names/spaces.
3. Convert that resolved root to `PureWindowsPath(...).as_posix()`, then apply
   Python `str.casefold()` to form `root_key`. No Unicode NFC/NFKC normalization,
   environment-variable expansion, URL decoding, whitespace trimming or hash.
   Native path parsing removes redundant separators/single-dot syntax; resolution
   is attempted only after component checks, with residual TOCTOU risk. No trailing slash
   except a drive anchor such as `e:/`.
4. A relative package path is assembled only from the fixed
   `left4dead2/addons/workshop/` prefix plus an accepted direct filename. It has
   forward slashes and preserves filename spelling. Its key is exactly
   `relative_path.casefold()`; never accept an arbitrary user-supplied relative
   path. A different filename/location remains a different location key.
5. Comparison keys are lookup aids, never filesystem permissions. Unicode
   casefold can be broader than Windows name equivalence. If keys collide but
   validated native paths are not equivalent, fail with an ambiguity diagnostic;
   do not merge installations/packages. M2 already skips ambiguous casefold
   filename groups. Policy changes need a reviewed migration, not silent key
   rewriting.

Here the fictional resolved spelling is given explicitly. No resolution call
was made on `E:\FictionalSteam`. The illustrative key can be computed lexically.

Internal VPK resources use a **different** policy, `vpk-path-v1`: reversible UTF-8
surrogateescape decoding, validate path fields, normalize backslashes to forward
slashes, casefold, then encode with surrogateescape. Preserve both original and
canonical bytes. Reject unsafe/absolute/traversal/empty-component paths rather
than collapse them. This is a proposed stored version tag for existing M2
behavior, not proof of engine comparison semantics.

## 3. Complete records

### 3.1 installations — 1 row

| `installation_id` | `root_path` | `root_key` | `catalog_generation` | `created_at` |
| --- | --- | --- | --- | --- |
| `7c1a9e306b454d0d9a651827d9f3ac10` | `E:\FictionalSteam\steamapps\common\Left 4 Dead 2` | `e:/fictionalsteam/steamapps/common/left 4 dead 2` | `6` | `2026-10-26T07:59:00.000000Z` |

### 3.2 workshop_items — 5 rows

Numeric strings are fictional filename conventions, not claims that these item
numbers exist on Steam. Preserve the strings rather than parse them as integers.
There is no dictionary row called Unknown.

| `workshop_id` | `first_seen_at` |
| --- | --- |
| `9100001001` | `2026-10-26T08:00:00.000000Z` |
| `9100001002` | `2026-10-26T08:00:00.000000Z` |
| `9100001003` | `2026-10-26T08:00:00.000000Z` |
| `9100001004` | `2026-10-26T08:00:00.000000Z` |
| `9100001005` | `2026-10-26T08:00:00.000000Z` |

### 3.3 scan_runs — 7 rows

These are semantic reconciliation attempts, **not seven consecutive one-second
polls**. Thousands of unchanged polls could happen between them without adding
rows. All times below are UTC.

| `scan_id` | `installation_id` | `started_at` | `finished_at` |
| --- | --- | --- | --- |
| `1` | `7c1a9e306b454d0d9a651827d9f3ac10` | `2026-10-26T08:00:00.000000Z` | `2026-10-26T08:00:03.000000Z` |
| `2` | `7c1a9e306b454d0d9a651827d9f3ac10` | `2026-10-26T08:01:00.000000Z` | `2026-10-26T08:01:03.000000Z` |
| `3` | `7c1a9e306b454d0d9a651827d9f3ac10` | `2026-10-26T08:02:00.000000Z` | `2026-10-26T08:02:03.000000Z` |
| `4` | `7c1a9e306b454d0d9a651827d9f3ac10` | `2026-10-26T08:03:00.000000Z` | `2026-10-26T08:03:01.000000Z` |
| `5` | `7c1a9e306b454d0d9a651827d9f3ac10` | `2026-10-26T08:04:00.000000Z` | `2026-10-26T08:04:01.000000Z` |
| `6` | `7c1a9e306b454d0d9a651827d9f3ac10` | `2026-10-26T08:04:03.000000Z` | `2026-10-26T08:04:04.000000Z` |
| `7` | `7c1a9e306b454d0d9a651827d9f3ac10` | `2026-10-26T08:05:00.000000Z` | `2026-10-26T08:05:01.000000Z` |

| `scan_id` | `outcome` | `directory_status` | `base_generation` | `committed_generation` |
| --- | --- | --- | --- | --- |
| `1` | `committed` | `complete` | `0` | `1` |
| `2` | `committed` | `complete` | `1` | `2` |
| `3` | `committed` | `complete` | `2` | `3` |
| `4` | `committed` | `unavailable` | `3` | `4` |
| `5` | `committed` | `complete` | `4` | `5` |
| `6` | `committed` | `complete` | `5` | `6` |
| `7` | `failed` | `partial` | `6` | `NULL` |

Timeline:

| Scan | Fictional event |
| --- | --- |
| 1 | Startup/settling completes; A/B/C/E/F get generation-1 valid indexes |
| 2 | A's settled update succeeds; same package UUID, new OS file ID, index generation 2 |
| 3 | B is replaced by a 7-byte partial file; valid generation 1 is kept. D arrives but remains pending |
| 4 | Workshop becomes inaccessible. Commit only uncertainty/status and a diagnostic; retain all valid assets |
| 5 | Folder recovers. C is absent for the first completed observation; begin the removal timer. Other recovery observations are still settling |
| 6 | Completed observations confirm C absent across more than two seconds. A/E/F reuse valid indexes; B's retry still fails; D changes again and remains pending |
| 7 | A later interrupted enumeration is followed by an injected catalog transaction failure; rollback preserves generation 6. A separate best-effort audit transaction records failure |

Scan 4's `outcome=committed` means the **uncertainty status was committed safely**;
its `directory_status=unavailable` does not become a successful full enumeration.
Scan 7's `committed_generation=NULL` means no new catalog generation was published.
The illustrated failed audit was finalized successfully; an actual crash may
instead leave `started` with unconfirmed completion. No package points to scan 7.

### 3.4 packages — 6 rows, every column across four views

Identity/location view:

| `package_id` | `installation_id` | `workshop_id` | `relative_path` | `relative_path_key` |
| --- | --- | --- | --- | --- |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `7c1a9e306b454d0d9a651827d9f3ac10` | `9100001001` | `left4dead2/addons/workshop/9100001001.VPK` | `left4dead2/addons/workshop/9100001001.vpk` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `7c1a9e306b454d0d9a651827d9f3ac10` | `9100001002` | `left4dead2/addons/workshop/9100001002.vpk` | `left4dead2/addons/workshop/9100001002.vpk` |
| `9b065137e4a4481bb3f07252c401d5a3` | `7c1a9e306b454d0d9a651827d9f3ac10` | `9100001003` | `left4dead2/addons/workshop/9100001003.vpk` | `left4dead2/addons/workshop/9100001003.vpk` |
| `f14a0cd2791e4ca1b64f2387ce890ad4` | `7c1a9e306b454d0d9a651827d9f3ac10` | `NULL` | `left4dead2/addons/workshop/Mystery_Pack.VpK` | `left4dead2/addons/workshop/mystery_pack.vpk` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `7c1a9e306b454d0d9a651827d9f3ac10` | `9100001004` | `left4dead2/addons/workshop/9100001004.vpk` | `left4dead2/addons/workshop/9100001004.vpk` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `7c1a9e306b454d0d9a651827d9f3ac10` | `9100001005` | `left4dead2/addons/workshop/9100001005.vpk` | `left4dead2/addons/workshop/9100001005.vpk` |

State and durable audit view:

| `package_id` | `presence_status` | `index_status` | `first_seen_scan_id` | `last_seen_scan_id` | `state_scan_id` | `removed_at` |
| --- | --- | --- | --- | --- | --- | --- |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `present` | `current` | `1` | `6` | `6` | `NULL` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `present` | `error` | `1` | `6` | `6` | `NULL` |
| `9b065137e4a4481bb3f07252c401d5a3` | `removed` | `unavailable` | `1` | `3` | `6` | `2026-10-26T08:04:04.000000Z` |
| `f14a0cd2791e4ca1b64f2387ce890ad4` | `present` | `pending` | `3` | `6` | `6` | `NULL` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `present` | `current` | `1` | `6` | `6` | `NULL` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `present` | `current` | `1` | `6` | `6` | `NULL` |

Latest safely observed file metadata (B is the corrupt 7-byte update):

| `package_id` | `observed_device_id` | `observed_file_id` | `observed_mode` | `observed_size_bytes` | `observed_mtime_ns` | `observed_ctime_ns` | `observed_attributes` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `1301352571` | `302231454903657293676801` | `33206` | `82033` | `1793001660000000000` | `1793001660000000000` | `32` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `1301352571` | `302231454903657293676802` | `33206` | `7` | `1793001720000000000` | `1793001720000000000` | `32` |
| `9b065137e4a4481bb3f07252c401d5a3` | `1301352571` | `302231454903657293676547` | `33206` | `2118` | `1793001590000000000` | `1793001590000000000` | `32` |
| `f14a0cd2791e4ca1b64f2387ce890ad4` | `1301352571` | `302231454903657293676548` | `33206` | `64` | `1793001843000000000` | `1793001843000000000` | `32` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `1301352571` | `302231454903657293676549` | `33206` | `77988` | `1793001590000000000` | `1793001590000000000` | `32` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `1301352571` | `302231454903657293676550` | `33206` | `17514` | `1793001590000000000` | `1793001590000000000` | `32` |

Preview reference view:

| `package_id` | `preview_relative_path` | `preview_status` |
| --- | --- | --- |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `left4dead2/addons/workshop/9100001001.jpg` | `present` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `left4dead2/addons/workshop/9100001002.jpg` | `present` |
| `9b065137e4a4481bb3f07252c401d5a3` | `NULL` | `missing` |
| `f14a0cd2791e4ca1b64f2387ce890ad4` | `NULL` | `unknown` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `left4dead2/addons/workshop/9100001004.jpg` | `present` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `left4dead2/addons/workshop/9100001005.jpg` | `present` |

C's observation fields describe its **last observed file**, not a still-present
file. Removal changes availability and excludes C from active queries; it does
not erase evidence. D's preview state is unknown and it has no associated image
reference. D's pending file keeps changing, so no valid index is asserted.

`last_seen_scan_id` means the last **durably recorded** positive observation.
It is not updated by unchanged polls. Latest live-poll time belongs to RAM and,
eventually, UI freshness display. Failed scan 7 advances no package fields.
Intermediate size/mtime changes while D is already pending are coalesced in RAM;
scan 6 can capture its latest safe observation as part of the recovery/removal
batch, without creating an extra audit attempt for every write-progress poll.

### 3.5 package_indexes — 5 rows

No row exists for D. Each listed package has one retained successful index;
there is no second row for A's superseded generation 1.

| `package_id` | `installation_id` | `generation` | `indexed_scan_id` | `vpk_version` | `tree_size` | `parser_version` | `canonicalization_version` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `7c1a9e306b454d0d9a651827d9f3ac10` | `2` | `2` | `1` | `101` | `vpk-index-v1` | `vpk-path-v1` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `7c1a9e306b454d0d9a651827d9f3ac10` | `1` | `1` | `1` | `123` | `vpk-index-v1` | `vpk-path-v1` |
| `9b065137e4a4481bb3f07252c401d5a3` | `7c1a9e306b454d0d9a651827d9f3ac10` | `1` | `1` | `1` | `58` | `vpk-index-v1` | `vpk-path-v1` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `7c1a9e306b454d0d9a651827d9f3ac10` | `1` | `1` | `1` | `152` | `vpk-index-v1` | `vpk-path-v1` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `7c1a9e306b454d0d9a651827d9f3ac10` | `1` | `1` | `1` | `94` | `vpk-index-v1` | `vpk-path-v1` |

SHA-256 is stored as a 32-byte BLOB, displayed here as an SQL hexadecimal literal:

| `package_id` | `index_sha256` |
| --- | --- |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `X'E2108FBA70C8C95A68A7CB80129B7D5EDEABCD5190CE40D24D5AF9253F5FCB8C'` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `X'276FA00EB0F4F1359B2F65AF05721275DB94A2F244818274A0FE22AAF39B7D2F'` |
| `9b065137e4a4481bb3f07252c401d5a3` | `X'68B13920121800D5EB4B8756ED782321E288FBA24EF0AA2729F00B761F4C5FD5'` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `X'12D318CA8F74876C09662327097CACA267AF9E8A228CDEF259BE2B69E009604E'` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `X'9ADA3055A9B181B95F754233C89D8BBD70EB3867176B4954A91607820CD3FD40'` |

Metadata captured when the retained index succeeded:

| `package_id` | `source_device_id` | `source_file_id` | `source_mode` | `source_size_bytes` | `source_mtime_ns` | `source_ctime_ns` | `source_attributes` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `1301352571` | `302231454903657293676801` | `33206` | `82033` | `1793001660000000000` | `1793001660000000000` | `32` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `1301352571` | `302231454903657293676546` | `33206` | `82055` | `1793001590000000000` | `1793001590000000000` | `32` |
| `9b065137e4a4481bb3f07252c401d5a3` | `1301352571` | `302231454903657293676547` | `33206` | `2118` | `1793001590000000000` | `1793001590000000000` | `32` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `1301352571` | `302231454903657293676549` | `33206` | `77988` | `1793001590000000000` | `1793001590000000000` | `32` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `1301352571` | `302231454903657293676550` | `33206` | `17514` | `1793001590000000000` | `1793001590000000000` | `32` |

B has observed size **7** but successful source size **82055**. Its current file
ID also differs from the retained source file ID. Those are two different
observations, not contradictory copies of the same current fact. A/E/F have
matching observed/source signatures; C is removed regardless of signature equality.

### 3.6 assets — 10 rows

BLOB cells use SQLite `X'HEX'` notation. Every two hexadecimal digits represent
one byte: `41` is ASCII A, `61` is a, `2F` is slash, and raw `B8 B1 B1 BE`
is an undecoded byte sequence here. Hexadecimal display is not a TEXT replacement
for the stored bytes. It is a lossless way to inspect them.

Human-readable path legend; `asset_ref` is a teaching label only. Escapes such
as `\xB8` mean a raw byte, not a guessed character or a literal backslash in
the original filename.

| `asset_ref` | `package_id` | `original_path_display` | `canonical_path_display` |
| --- | --- | --- | --- |
| `A1` | `0cda40ac6e9b4a31b8876270e6b508a1` | `"Materials/Shared/Finish.vmt"` | `"materials/shared/finish.vmt"` |
| `A2` | `0cda40ac6e9b4a31b8876270e6b508a1` | `"Models/Weapons/v_Rifle_AK47.mdl"` | `"models/weapons/v_rifle_ak47.mdl"` |
| `B1` | `3a2f7c196d404b8a9e650aa243b9e702` | `"Models/Survivors/Rochelle_Replacer.mdl"` | `"models/survivors/rochelle_replacer.mdl"` |
| `B2` | `3a2f7c196d404b8a9e650aa243b9e702` | `"Sound/Survivors/VoicePack_\xB8\xB1\xB1\xBE.wav"` | `"sound/survivors/voicepack_\xB8\xB1\xB1\xBE.wav"` |
| `C1` | `9b065137e4a4481bb3f07252c401d5a3` | `"Materials/VGUI/HUD/Retired_Icons.vmt"` | `"materials/vgui/hud/retired_icons.vmt"` |
| `E1` | `5e9d71346c2741f4a8803d96b3a429e5` | `"materials/shared/finish.vmt"` | `"materials/shared/finish.vmt"` |
| `E2` | `5e9d71346c2741f4a8803d96b3a429e5` | `"Models/Survivors/Rochelle_Remix.mdl"` | `"models/survivors/rochelle_remix.mdl"` |
| `E3` | `5e9d71346c2741f4a8803d96b3a429e5` | `"Models/Weapons/v_Rifle_AK47.mdl"` | `"models/weapons/v_rifle_ak47.mdl"` |
| `F1` | `a1706e2b2f09422d9ca47f6a315dc8f6` | `"Scripts/Hud/Team_Colors.res"` | `"scripts/hud/team_colors.res"` |
| `F2` | `a1706e2b2f09422d9ca47f6a315dc8f6` | `"Sound/UI/Team_Notice.wav"` | `"sound/ui/team_notice.wav"` |

Complete stored path-key values:

| `package_id` | `original_path_bytes` | `canonical_path_bytes` | `utf8_valid` |
| --- | --- | --- | --- |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `X'4D6174657269616C732F5368617265642F46696E6973682E766D74'` | `X'6D6174657269616C732F7368617265642F66696E6973682E766D74'` | `1` |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `X'4D6F64656C732F576561706F6E732F765F5269666C655F414B34372E6D646C'` | `X'6D6F64656C732F776561706F6E732F765F7269666C655F616B34372E6D646C'` | `1` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `X'4D6F64656C732F5375727669766F72732F526F6368656C6C655F5265706C616365722E6D646C'` | `X'6D6F64656C732F7375727669766F72732F726F6368656C6C655F7265706C616365722E6D646C'` | `1` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `X'536F756E642F5375727669766F72732F566F6963655061636B5FB8B1B1BE2E776176'` | `X'736F756E642F7375727669766F72732F766F6963657061636B5FB8B1B1BE2E776176'` | `0` |
| `9b065137e4a4481bb3f07252c401d5a3` | `X'4D6174657269616C732F564755492F4855442F526574697265645F49636F6E732E766D74'` | `X'6D6174657269616C732F766775692F6875642F726574697265645F69636F6E732E766D74'` | `1` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `X'6D6174657269616C732F7368617265642F66696E6973682E766D74'` | `X'6D6174657269616C732F7368617265642F66696E6973682E766D74'` | `1` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `X'4D6F64656C732F5375727669766F72732F526F6368656C6C655F52656D69782E6D646C'` | `X'6D6F64656C732F7375727669766F72732F726F6368656C6C655F72656D69782E6D646C'` | `1` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `X'4D6F64656C732F576561706F6E732F765F5269666C655F414B34372E6D646C'` | `X'6D6F64656C732F776561706F6E732F765F7269666C655F616B34372E6D646C'` | `1` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `X'536372697074732F4875642F5465616D5F436F6C6F72732E726573'` | `X'736372697074732F6875642F7465616D5F636F6C6F72732E726573'` | `1` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `X'536F756E642F55492F5465616D5F4E6F746963652E776176'` | `X'736F756E642F75692F7465616D5F6E6F746963652E776176'` | `1` |

Complete stored entry metadata (joined to the preceding view by the composite PK):

| `package_id` | `canonical_path_bytes` | `crc32` | `preload_bytes` | `archive_index` | `archive_offset` | `archive_length` |
| --- | --- | --- | --- | --- | --- | --- |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `X'6D6174657269616C732F7368617265642F66696E6973682E766D74'` | `3958260987` | `0` | `32767` | `65536` | `16384` |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `X'6D6F64656C732F776561706F6E732F765F7269666C655F616B34372E6D646C'` | `2694514304` | `0` | `32767` | `0` | `65536` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `X'6D6F64656C732F7375727669766F72732F726F6368656C6C655F7265706C616365722E6D646C'` | `1900676229` | `0` | `32767` | `0` | `49152` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `X'736F756E642F7375727669766F72732F766F6963657061636B5FB8B1B1BE2E776176'` | `3720724249` | `8` | `32767` | `49152` | `32768` |
| `9b065137e4a4481bb3f07252c401d5a3` | `X'6D6174657269616C732F766775692F6875642F726574697265645F69636F6E732E766D74'` | `3081393376` | `0` | `32767` | `0` | `2048` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `X'6D6174657269616C732F7368617265642F66696E6973682E766D74'` | `125501382` | `0` | `32767` | `61440` | `16384` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `X'6D6F64656C732F7375727669766F72732F726F6368656C6C655F72656D69782E6D646C'` | `3731627212` | `0` | `32767` | `32768` | `28672` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `X'6D6F64656C732F776561706F6E732F765F7269666C655F616B34372E6D646C'` | `2694335761` | `0` | `32767` | `0` | `32768` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `X'736372697074732F6875642F7465616D5F636F6C6F72732E726573'` | `399713824` | `0` | `32767` | `16384` | `1024` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `X'736F756E642F75692F7465616D5F6E6F746963652E776176'` | `2826737651` | `0` | `32767` | `0` | `16384` |

For every row, `archive_index=32767` means embedded data. Offsets are relative to
the file-data section, not the start of the VPK. All declared ranges fit the
retained source version, including B's retained valid version—not its corrupt
7-byte current observation. The 8-byte preload for B2 is included in tree size;
its body length excludes preload. Declared CRCs are not payload-integrity checks.

Original uppercase spelling and canonical lowercase bytes are different values.
B2 is `utf8_valid=0`: decoding with surrogateescape and encoding back preserves
the original raw bytes exactly. Never use `errors='replace'`, infer a codepage,
or store the display string as the authoritative path.

### 3.7 scan_issues — 6 rows

| `issue_id` | `installation_id` | `scan_id` | `package_id` | `relative_path` | `severity` | `code` | `message` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `1` | `7c1a9e306b454d0d9a651827d9f3ac10` | `1` | `3a2f7c196d404b8a9e650aa243b9e702` | `left4dead2/addons/workshop/9100001002.vpk` | `warning` | `NON_UTF8_PATHS` | `1 internal resource path contains undecoded bytes; original bytes retained.` |
| `2` | `7c1a9e306b454d0d9a651827d9f3ac10` | `3` | `3a2f7c196d404b8a9e650aa243b9e702` | `left4dead2/addons/workshop/9100001002.vpk` | `error` | `TRUNCATED_VPK` | `VPK is too short for its header.` |
| `3` | `7c1a9e306b454d0d9a651827d9f3ac10` | `4` | `NULL` | `left4dead2/addons/workshop` | `error` | `ENUMERATION_FAILED` | `Workshop enumeration failed; previous valid indexes retained.` |
| `4` | `7c1a9e306b454d0d9a651827d9f3ac10` | `6` | `3a2f7c196d404b8a9e650aa243b9e702` | `left4dead2/addons/workshop/9100001002.vpk` | `error` | `TRUNCATED_VPK` | `VPK is too short for its header.` |
| `5` | `7c1a9e306b454d0d9a651827d9f3ac10` | `7` | `NULL` | `left4dead2/addons/workshop` | `error` | `ENUMERATION_FAILED` | `Workshop enumeration was interrupted; absence is unconfirmed.` |
| `6` | `7c1a9e306b454d0d9a651827d9f3ac10` | `7` | `NULL` | `left4dead2/addons/workshop` | `error` | `CATALOG_COMMIT_FAILED` | `Catalog transaction rolled back; previous committed catalog retained.` |

The NULL package IDs are legitimate folder/catalog-level issues, not orphan
references. Issue 1 is a warning: non-UTF-8 bytes do not invalidate B's old index.
Issues 2 and 4 are different semantic episodes separated by outage/recovery; they
are not permanent rows for every identical five-second retry. Scan 7's two
issues coexist with its failed outcome and do not mutate the catalog snapshot.

## 4. Data dictionary — every column, example and origin

All origins below describe the **fictional fixture or future repository**, not
data read from the owner's installation. Types/nullability and all constraints
are specified in the schema proposal. Examples are drawn from the rows above.

### installations

| `column` | `data_type` | `purpose` | `example` | `origin` |
| --- | --- | --- | --- | --- |
| `installation_id` | `TEXT` | Stable namespace PK | `7c1a9e306b454d0d9a651827d9f3ac10` | Repository generates UUID4 when a validated root is first registered |
| `root_path` | `TEXT` | Validated resolved absolute Windows root | `E:\FictionalSteam\steamapps\common\Left 4 Dead 2` | Explicit fictional selection/resolved spelling supplied for teaching; no access performed |
| `root_key` | `TEXT` | Unique deterministic root lookup key | `e:/fictionalsteam/steamapps/common/left 4 dead 2` | location-key-v1 applied after successful root validation |
| `catalog_generation` | `INTEGER` | Atomic catalog commit sequence | `6` | Repository increments only on committed semantic batches/startup validation |
| `created_at` | `TEXT` | Namespace registration time | `2026-10-26T07:59:00.000000Z` | UTC repository clock |

### workshop_items

| `column` | `data_type` | `purpose` | `example` | `origin` |
| --- | --- | --- | --- | --- |
| `workshop_id` | `TEXT` | Logical inferred item PK; string, not package identity | `9100001001` | ASCII-numeric VPK stem |
| `first_seen_at` | `TEXT` | First registered observation of that item hint | `2026-10-26T08:00:00.000000Z` | UTC observation time in first committed batch |

### scan_runs

| `column` | `data_type` | `purpose` | `example` | `origin` |
| --- | --- | --- | --- | --- |
| `scan_id` | `INTEGER` | Local audit PK | `1` | SQLite INTEGER primary-key allocation, only for durable semantic attempts |
| `installation_id` | `TEXT` | Scope FK | `7c1a9e306b454d0d9a651827d9f3ac10` | Selected installation PK |
| `started_at` | `TEXT` | Time the observed batch began | `2026-10-26T08:00:00.000000Z` | UTC scan clock retained in RAM before audit registration |
| `finished_at` | `TEXT` | Attempt finalization time; NULL until known | `2026-10-26T08:00:03.000000Z` | UTC commit/failure handling |
| `outcome` | `TEXT` | Database publication/completion result | `committed` | Repository transaction result, separate from directory access quality |
| `directory_status` | `TEXT` | Directory observation quality | `complete` | Scoped M2 discovery status |
| `base_generation` | `INTEGER` | Generation on which staged results were based | `0` | Installation generation read before staging |
| `committed_generation` | `INTEGER` | Published generation, NULL on failed/noncommitted attempt | `1` | base_generation + 1 only when final transaction commits |

### packages

| `column` | `data_type` | `purpose` | `example` | `origin` |
| --- | --- | --- | --- | --- |
| `package_id` | `TEXT` | Stable internal package PK | `0cda40ac6e9b4a31b8876270e6b508a1` | Repository UUID4 at first accepted lineage observation |
| `installation_id` | `TEXT` | Package namespace FK | `7c1a9e306b454d0d9a651827d9f3ac10` | Explicit selected installation record |
| `workshop_id` | `TEXT` | Optional inferred item FK | `9100001001` | Numeric filename stem or NULL; never invented from a title |
| `relative_path` | `TEXT` | Original allowed physical file location | `left4dead2/addons/workshop/9100001001.VPK` | Fixed Workshop prefix plus safely enumerated direct filename |
| `relative_path_key` | `TEXT` | Conditional unique active location key | `left4dead2/addons/workshop/9100001001.vpk` | Exact relative_path.casefold(), not a permission boundary |
| `presence_status` | `TEXT` | Observed/uncertain/removed availability | `present` | Completed scan evidence and M2 confirmation policy |
| `index_status` | `TEXT` | Freshness/readability of the retained index | `current` | Settling, parse and source-signature reconciliation |
| `observed_device_id` | `TEXT` | Latest safe observation: OS volume/device observation; decimal TEXT | `1301352571` | Fictional stat st_dev, assigned for this fixture |
| `observed_file_id` | `TEXT` | Latest safe observation: OS file identity observation; decimal TEXT, not stable package PK | `302231454903657293676801` | Fictional stat st_ino; may change on in-place replacement |
| `observed_mode` | `INTEGER` | Latest safe observation: File type/permission bits; 33206 is the synthetic regular-file mode | `33206` | Fictional stat st_mode |
| `observed_size_bytes` | `INTEGER` | Latest safe observation: Physical source version size in bytes | `82033` | Observed fixture stat size or generated valid VPK byte length |
| `observed_mtime_ns` | `INTEGER` | Latest safe observation: Source modification time in integer epoch nanoseconds | `1793001660000000000` | Fictional stat st_mtime_ns; UTC source time converted exactly |
| `observed_ctime_ns` | `INTEGER` | Latest safe observation: Source metadata-change time in epoch nanoseconds | `1793001660000000000` | Fictional stat st_ctime_ns; not a portable creation-time promise |
| `observed_attributes` | `INTEGER` | Latest safe observation: Windows file attribute flags; 32 is the synthetic Archive flag | `32` | Fictional stat st_file_attributes |
| `preview_relative_path` | `TEXT` | Last accepted same-stem JPG reference | `left4dead2/addons/workshop/9100001001.jpg` | Scoped discovery; retained as unknown during incomplete observations |
| `preview_status` | `TEXT` | Present/missing/unknown preview availability | `present` | Completed applicable scan or explicit uncertainty |
| `first_seen_scan_id` | `INTEGER` | First committed discovery of this UUID; scoped FK | `1` | Initial semantic batch |
| `last_seen_scan_id` | `INTEGER` | Last durably recorded safe positive observation; scoped FK | `6` | Latest persisted batch with this package reference, not unchanged polls |
| `state_scan_id` | `INTEGER` | Batch publishing current availability/index state; scoped FK | `6` | Most recent relevant committed state transition |
| `removed_at` | `TEXT` | Confirmed removal timestamp, otherwise NULL | `2026-10-26T08:04:04.000000Z` | UTC completion time after full-scan absence confirmation |

### package_indexes

| `column` | `data_type` | `purpose` | `example` | `origin` |
| --- | --- | --- | --- | --- |
| `package_id` | `TEXT` | PK and parent package FK; one last valid row | `0cda40ac6e9b4a31b8876270e6b508a1` | Existing package UUID, unchanged by index refresh |
| `installation_id` | `TEXT` | Composite-FK scope guard | `7c1a9e306b454d0d9a651827d9f3ac10` | Parent installation, checked against producing scan |
| `generation` | `INTEGER` | Successful-index revision, not filename/Workshop version | `2` | Repository increments on successful changed index; failed parses do not increment |
| `indexed_scan_id` | `INTEGER` | Producing scan FK | `2` | Batch that successfully indexed this retained source version |
| `vpk_version` | `INTEGER` | Declared archive directory version | `1` | Bounded synthetic header parse |
| `tree_size` | `INTEGER` | Declared directory bytes, including preload bytes | `101` | Synthetic VPK header/tree |
| `index_sha256` | `BLOB` | 32-byte header/tree fingerprint, not full payload hash | `X'E2108FBA70C8C95A68A7CB80129B7D5EDEABCD5190CE40D24D5AF9253F5FCB8C'` | SHA-256 of bounded synthetic header and tree |
| `parser_version` | `TEXT` | Version tag for index data contract/cache invalidation | `vpk-index-v1` | Proposed repository constant vpk-index-v1; not Steam metadata |
| `canonicalization_version` | `TEXT` | Policy under which resource comparison bytes were generated | `vpk-path-v1` | Proposed vpk-path-v1 tag for M2 behavior |
| `source_device_id` | `TEXT` | Retained successful observation: OS volume/device observation; decimal TEXT | `1301352571` | Fictional stat st_dev, assigned for this fixture |
| `source_file_id` | `TEXT` | Retained successful observation: OS file identity observation; decimal TEXT, not stable package PK | `302231454903657293676801` | Fictional stat st_ino; may change on in-place replacement |
| `source_mode` | `INTEGER` | Retained successful observation: File type/permission bits; 33206 is the synthetic regular-file mode | `33206` | Fictional stat st_mode |
| `source_size_bytes` | `INTEGER` | Retained successful observation: Physical source version size in bytes | `82033` | Observed fixture stat size or generated valid VPK byte length |
| `source_mtime_ns` | `INTEGER` | Retained successful observation: Source modification time in integer epoch nanoseconds | `1793001660000000000` | Fictional stat st_mtime_ns; UTC source time converted exactly |
| `source_ctime_ns` | `INTEGER` | Retained successful observation: Source metadata-change time in epoch nanoseconds | `1793001660000000000` | Fictional stat st_ctime_ns; not a portable creation-time promise |
| `source_attributes` | `INTEGER` | Retained successful observation: Windows file attribute flags; 32 is the synthetic Archive flag | `32` | Fictional stat st_file_attributes |

### assets

| `column` | `data_type` | `purpose` | `example` | `origin` |
| --- | --- | --- | --- | --- |
| `package_id` | `TEXT` | Parent retained-index FK; first PK component | `0cda40ac6e9b4a31b8876270e6b508a1` | Package UUID of the successful source index |
| `canonical_path_bytes` | `BLOB` | Canonical BLOB key; second PK component | `X'6D6174657269616C732F7368617265642F66696E6973682E766D74'` | Validated vpk-path-v1 normalization, then reversible byte encoding |
| `original_path_bytes` | `BLOB` | Original virtual resource spelling as BLOB | `X'4D6174657269616C732F5368617265642F46696E6973682E766D74'` | Reconstructed directory entry bytes, losslessly preserved |
| `utf8_valid` | `INTEGER` | Materialized 0/1 raw-path validation result | `1` | Strict UTF-8 decoding test of original bytes; no guessed encoding |
| `crc32` | `INTEGER` | Declared unsigned entry checksum | `3958260987` | Synthetic fixture header entry, computed from its placeholder preload + payload |
| `preload_bytes` | `INTEGER` | Declared preload byte count | `0` | Synthetic entry metadata |
| `archive_index` | `INTEGER` | Embedded/external location indicator | `32767` | Synthetic entry metadata; 32767 is embedded in these examples |
| `archive_offset` | `INTEGER` | Byte offset inside the indicated data section | `65536` | Synthetic entry metadata; not a filesystem path |
| `archive_length` | `INTEGER` | Body length excluding preload | `16384` | Synthetic entry metadata |

### scan_issues

| `column` | `data_type` | `purpose` | `example` | `origin` |
| --- | --- | --- | --- | --- |
| `issue_id` | `INTEGER` | Local diagnostic PK | `1` | SQLite INTEGER primary-key allocation for retained meaningful issue |
| `installation_id` | `TEXT` | Scope guard FK | `7c1a9e306b454d0d9a651827d9f3ac10` | Same installation as scan/package, when package exists |
| `scan_id` | `INTEGER` | Owning semantic attempt FK | `1` | Audit attempt that observed/finalized this issue |
| `package_id` | `TEXT` | Optional affected package FK | `3a2f7c196d404b8a9e650aa243b9e702` | Existing UUID, or NULL for folder/pre-identity/catalog failure |
| `relative_path` | `TEXT` | Safe relevant location, if known | `left4dead2/addons/workshop/9100001002.vpk` | Allowlisted relative reference or fixed Workshop folder |
| `severity` | `TEXT` | Warning/error level, independent from parse presence | `warning` | Controlled diagnostic classification |
| `code` | `TEXT` | Stable machine-readable reason | `NON_UTF8_PATHS` | Fixed scanner/parser/repository diagnostic code |
| `message` | `TEXT` | Safe readable explanation | `1 internal resource path contains undecoded bytes; original bytes retained.` | Controlled message, not arbitrary OS exception/absolute path dump |


## 5. Relationships, identities and constraints using these rows

- Installation `7c1a9e306b454d0d9a651827d9f3ac10` owns six package records and seven attempts: **1:M**.
- Workshop item `9100001001` is referenced by A's full UUID
  `0cda40ac6e9b4a31b8876270e6b508a1`. D has a NULL item FK, which does not require an Unknown parent row.
  Several physical package lineages may refer to the same item in future; ID is
  not a UNIQUE package column.
- A has exactly one retained index, generation 2. D has zero indexes: the
  package → retained-index relationship is **1:0..1**, not mandatory 1:1.
- A has two retained asset rows; E has three: successful index → assets is **1:M**.
- B's producing scan 1 exists in the same installation as B's package. Its latest
  state belongs to scan 6. The scoped FKs prohibit substituting a scan/package
  from another installation.
- Folder issues 3/5/6 have NULL package FKs intentionally. They still reference
  valid scans and the correct installation.

Composite PK example: A2 and E3 have the same canonical model path, but different
full package UUIDs. Both are valid rows. Inserting a second A asset with A2's same
canonical bytes would violate `PRIMARY KEY(package_id, canonical_path_bytes)`.
The same original spelling inside one package is also unique. This illustrates
a key constraint, not implemented conflict analysis.

The partial unique location constraint applies to **nonremoved** package rows.
C's inactive row frees its location for a future new UUID, without erasing old
data. An unavailable package still reserves its location; never allocate a
duplicate UUID merely because a scan cannot read it.

### A retains identity across an update

This is an explanatory timeline, not additional rows in a history table:

| `event` | `package_id` | `file_id` | `index_generation` |
| --- | --- | --- | --- |
| `Scan 1, first valid source` | `0cda40ac6e9b4a31b8876270e6b508a1` | `302231454903657293676545` | `1` |
| `Scan 2, settled replacement file` | `0cda40ac6e9b4a31b8876270e6b508a1` | `302231454903657293676801` | `2` |
| `Scan 6, unchanged source confirmed` | `0cda40ac6e9b4a31b8876270e6b508a1` | `302231454903657293676801` | `2` |

The UUID stays fixed; the OS file ID and source metadata can change. After the
successful refresh, only A's latest generation-2 index/asset rows remain in M3.
Future user edits attach to the UUID, with a basis generation for review.

### Failed/incomplete scans do not erase assets

At scan 3, B's current file becomes 7 bytes, so its retained index stays generation
1 with two assets from a valid 82,055-byte source. Scan 4 cannot enumerate the
folder; its state publication marks uncertainty, but still retains all valid
indexes. Recovery revalidates sources before declaring current state. Scan 7's
failed catalog mutation rolls back, leaving installation generation 6 and the
same ten retained assets. Treating inaccessible/unseen as removed would have
destroyed correct information about A/B/E/F; that transition is forbidden.

C differs: complete observations at scans 5 and 6 confirm absence over at least
two seconds. C is inactive and excluded from active queries, but its old index
and one asset remain retained. Neither storage retention nor a matching Workshop
ID is evidence that C is currently installed/subscribed.

## 6. JOIN queries and expected SELECT results

**No SQL below has been executed.** These are expected results derived from the
same literal records. Post-approval implementation/demo tests will execute the
DDL, load these rows and assert the results with SQLite.

### Query A — across all seven tables, without multiplying child rows

Pre-aggregate assets and issues so a package with several of each does not get
an inflated COUNT from an asset×issue join.

```sql
WITH asset_totals AS (
    SELECT package_id, COUNT(*) AS retained_assets,
           SUM(CASE WHEN utf8_valid=0 THEN 1 ELSE 0 END) AS undecoded_paths
    FROM assets GROUP BY package_id
),
issue_codes AS (
    SELECT package_id, scan_id, GROUP_CONCAT(code, ', ') AS codes
    FROM scan_issues
    WHERE package_id IS NOT NULL
    GROUP BY package_id, scan_id
)
SELECT p.package_id, w.workshop_id, p.presence_status, p.index_status,
       ix.generation, COALESCE(a.retained_assets,0) AS retained_assets,
       COALESCE(a.undecoded_paths,0) AS undecoded_paths,
       r.scan_id AS state_scan_id, COALESCE(s.codes,'none') AS issue_codes
FROM installations AS i
JOIN packages AS p ON p.installation_id=i.installation_id
LEFT JOIN workshop_items AS w ON w.workshop_id=p.workshop_id
LEFT JOIN package_indexes AS ix ON ix.package_id=p.package_id
LEFT JOIN asset_totals AS a ON a.package_id=p.package_id
JOIN scan_runs AS r
  ON r.installation_id=p.installation_id AND r.scan_id=p.state_scan_id
LEFT JOIN issue_codes AS s
  ON s.package_id=p.package_id AND s.scan_id=r.scan_id
WHERE i.installation_id=:installation_id AND p.removed_at IS NULL
ORDER BY p.relative_path_key;
```

Bind `:installation_id` to `7c1a9e306b454d0d9a651827d9f3ac10`. Expected rows:

| `package_id` | `workshop_id` | `presence_status` | `index_status` | `generation` | `retained_assets` | `undecoded_paths` | `state_scan_id` | `issue_codes` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `9100001001` | `present` | `current` | `2` | `2` | `0` | `6` | `none` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `9100001002` | `present` | `error` | `1` | `2` | `1` | `6` | `TRUNCATED_VPK` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `9100001004` | `present` | `current` | `1` | `3` | `0` | `6` | `none` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `9100001005` | `present` | `current` | `1` | `2` | `0` | `6` | `none` |
| `f14a0cd2791e4ca1b64f2387ce890ad4` | `NULL` | `present` | `pending` | `NULL` | `0` | `0` | `6` | `none` |

C is absent because confirmed removals are excluded. D remains visible because
LEFT JOIN does not require a Workshop item or successful index. B's retained
count is explicitly not described as a current valid index.

### Query B — see both halves of the optional 1:1 relationship

```sql
SELECT p.package_id, p.index_status, ix.generation
FROM packages AS p
LEFT JOIN package_indexes AS ix ON ix.package_id=p.package_id
WHERE p.installation_id=:installation_id
ORDER BY p.relative_path_key;
```

Expected rows, including removed history:

| `package_id` | `index_status` | `generation` |
| --- | --- | --- |
| `0cda40ac6e9b4a31b8876270e6b508a1` | `current` | `2` |
| `3a2f7c196d404b8a9e650aa243b9e702` | `error` | `1` |
| `9b065137e4a4481bb3f07252c401d5a3` | `unavailable` | `1` |
| `5e9d71346c2741f4a8803d96b3a429e5` | `current` | `1` |
| `a1706e2b2f09422d9ca47f6a315dc8f6` | `current` | `1` |
| `f14a0cd2791e4ca1b64f2387ce890ad4` | `pending` | `NULL` |

Using INNER JOIN would hide D, concealing a legitimate pending package.

### Query C — inspect non-UTF-8 bytes without lossy conversion

```sql
SELECT p.package_id, ix.generation,
       typeof(a.original_path_bytes) AS storage_type,
       hex(a.original_path_bytes) AS original_hex,
       hex(a.canonical_path_bytes) AS canonical_hex, a.utf8_valid
FROM packages AS p
JOIN package_indexes AS ix ON ix.package_id=p.package_id
JOIN assets AS a ON a.package_id=ix.package_id
WHERE p.package_id=:package_id AND a.utf8_valid=0;
```

Bind `:package_id` to B's UUID. Expected result:

| `package_id` | `generation` | `storage_type` | `original_hex` | `canonical_hex` | `utf8_valid` |
| --- | --- | --- | --- | --- | --- |
| `3a2f7c196d404b8a9e650aa243b9e702` | `1` | `blob` | `536F756E642F5375727669766F72732F566F6963655061636B5FB8B1B1BE2E776176` | `736F756E642F7375727669766F72732F766F6963657061636B5FB8B1B1BE2E776176` | `0` |

The BLOB contains raw `B8 B1 B1 BE`, not the UTF-8 encoding of a replacement
character or of a textual escape. `hex()` affects display only.

### Query D — audit outcomes without hiding attempts that have no issues

```sql
SELECT r.scan_id, r.outcome, r.directory_status, r.base_generation,
       r.committed_generation, COUNT(s.issue_id) AS issue_count
FROM scan_runs AS r
LEFT JOIN scan_issues AS s ON s.scan_id=r.scan_id
WHERE r.installation_id=:installation_id
GROUP BY r.scan_id,r.outcome,r.directory_status,
         r.base_generation,r.committed_generation
ORDER BY r.scan_id;
```

Expected results:

| `scan_id` | `outcome` | `directory_status` | `base_generation` | `committed_generation` | `issue_count` |
| --- | --- | --- | --- | --- | --- |
| `1` | `committed` | `complete` | `0` | `1` | `1` |
| `2` | `committed` | `complete` | `1` | `2` | `0` |
| `3` | `committed` | `complete` | `2` | `3` | `1` |
| `4` | `committed` | `unavailable` | `3` | `4` | `1` |
| `5` | `committed` | `complete` | `4` | `5` | `0` |
| `6` | `committed` | `complete` | `5` | `6` | `1` |
| `7` | `failed` | `partial` | `6` | `NULL` | `2` |

Scan 4 publishes a safe unavailable state; scan 7 publishes no new catalog
generation. Both differ from a completed accessible empty directory.

## 7. Normalization using these exact records

**1NF:** A's two resources and E's three resources are separate rows; there is
no `asset1/asset2` or comma-separated path list. B's undecodable path is one
atomic byte identifier, not a repeating group. Issue rows are likewise separate.
`GROUP_CONCAT` above is query output only, not a stored list.

**2NF:** For A2 versus E3, the same canonical path alone does not determine CRC,
length or offset: those depend on the package occurrence. For A1 versus A2,
the package UUID alone does not determine an entry's CRC. Entry metadata depends
on the full composite key `(package_id,canonical_path_bytes)`.

**3NF:** The root is stored once in installations; inferred item registration
once in workshop_items; directory/parser facts once per retained index; individual
asset facts in assets. B's observed seven-byte partial file is not copied into
every asset row. The prior 82,055-byte successful source is a different temporal
fact and intentionally survives separately.

**Intentional materialization:** `root_key` and `relative_path_key` are derived
lookup/uniqueness keys maintained from original paths. `utf8_valid` caches byte
validation so a review query need not decode raw bytes in SQL. Repeated installation
IDs allow composite FKs to reject cross-root links. These practical exceptions
are documented rather than calling the whole schema exception-free 3NF.

Counts and decoded labels are derived. The absence of title/replacement/target
columns is intentional: M3 does not invent future classified facts. The separate
UI contract describes their later normalized evidence/user layers.

## 8. Static consistency checks and approval boundary

Documentation-authoring checks verified every record's column set against the
proposed DDL, value types, UUID4 format, PK/unique/scoped FK links, lifecycle
relationships, generation arithmetic, current observed/source signatures and
embedded archive bounds. The existing M2 parser checked only the in-memory
fictional fixture directories used to calculate technical values. These checks
did not create a database, execute DDL, run migrations or access the real game.

After explicit M3 schema approval and implementation, provide a **separate demo
SQLite database** at `examples/m3-demo/m3_demo.sqlite3` in the repository, with
these seven tables and exactly these fictional rows. That location is a planned,
explicitly requested teaching-artifact/test exception; it is not a production
database path. Production stays at
`%LOCALAPPDATA%\L4D2ModDatabase\catalog.sqlite3`. The runtime must not fall back
to the demo, expose arbitrary database path overrides or treat its fictional root
as scan authorization.

The future demo generator must use literal synthetic rows only, never scan a game,
copy production records or require Steam. It must validate FK/integrity checks,
row counts, bytes and query results, checkpoint/close the demo so a standalone
file opens in DB Browser for SQLite, and include an adjacent warning README.
Creation/overwrite must be deliberate; the demo and production must never share
connections or data. **The demo is not created during this review.**

