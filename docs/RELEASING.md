# Release preparation (no publication authorized)

Proposed first release: **0.1.0rc4**, explicitly marked pre-release. The milestone
label is M6.4; it is not a promise of stable 1.0. Preserve the approved MIT license and copyright notice; confirm runtime
redistribution rights, owner UX acceptance and final artifact checks before any
upload. No remote repository, push or release is created by these instructions.

## Reproducible local preparation

On Windows x64 with the pinned build environment:

```powershell
.\Build-Portable.ps1
.venv\Scripts\python -B -m unittest discover -s tests -t .
.venv\Scripts\python -B -m tools.smoke_portable --launcher
.venv\Scripts\python -B -m tools.smoke_portable --zip dist\L4D2ModDatabase-0.1.0rc4-win-x64.zip
.venv\Scripts\python -B -m tools.prepare_source
```

The build restricts DLL discovery to the chosen Python installation and Windows
and locates Pillow notices through that interpreter. Use `-Python` to select an
existing pinned build environment outside the checkout.

Review the portable ZIP and `.sha256` sidecar. The smoke test extracts to a new
ordinary writable test folder, removes Python from the EXE child's PATH, uses a
separate application-data profile, tests unavailable/recovered fixture roots and
checks database/game preservation. It never mutates real game files. Optional
imports reported by PyInstaller must be distinguished from tested required DLLs.

Only the explicit public-source allowlist enters the source ZIP. Private handoffs,
review archives, developer conversations, real collection screenshots, logs,
credentials and personal databases are excluded. The one included demo SQLite DB
is entirely fictional, reproducible and tested. Screenshots use fictional data.
Source ZIP timestamps/order are deterministic; binary builds are reproducible as a
pinned procedure, not promised byte-identical across machines and build times.

## Clean repository setup for owner review

If Git is not initialized, review/extract the generated source archive into a new
folder first. From that **clean source folder**, the owner can run:

```powershell
git init
git status --short --ignored
```

Inspect every source file and ignore rule before staging. Local staging/commits,
remote URL creation, uploads and public release must be deliberate owner actions;
no invented remote or credentials are required here. Do not initialize/publish the
entire private development workspace by accident.

## Proposed public structure

README and release notes at the root; code/tests/tools in their own folders; public
privacy/licensing/developer/beta/conflict guides under docs; sanitized screenshots
under docs/screenshots/m64; issue template under .github; synthetic teaching DB in
examples; runtime notices under release. Generated EXEs belong in release Assets,
not committed build directories. Original source and documentation use the approved MIT license (LICENSE).

## Final owner gates

- Preserve the approved MIT source license, copyright (c) 2026 RABrian, and
  third-party notices. Confirm Microsoft runtime distribution rights for binaries.
  Private development-review materials are outside the public source package.
- Review final GUI/filter/editor/Planning screenshots and acceptance checklist.
- Distinguish automated source/EXE results, manual GUI checks, real scoped reads
  and owner-reported external beta results; do not claim unexecuted tests passed.
- Verify ZIP hash/contents, ordinary-folder extraction and offline/error behavior.
- Decide whether the unsigned pre-release is acceptable. Explain trust warnings
  without asking users to disable antivirus/OS protections.
- Approve the repository name, public documentation, source package and final
  binary/release notes before creating/pushing/publishing anything.
