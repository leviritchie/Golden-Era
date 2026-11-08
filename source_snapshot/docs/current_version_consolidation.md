# Current Version Consolidation: 25672315

Status: installed-payload proven for the files listed in the 2026-10-04 promotion receipt. The receipt does not claim a whole-tree hash audit, startup smoke, or gameplay test. This is the current status hub for the 25672315 consolidation.

## Build And Path Identity

- Physical active install and launch target: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era` (`HeroesOldenEra.exe`).
- Installed `GameAssembly.dll` SHA-256: `d9972b0e7f7dd1c17758808e2f1b80e0a728946416d9a41deaa99bad744de53a`; this is Steam build `25672315`, depot manifest `7750145598966689713`.
- Select generated code scope by the installed `GameAssembly.dll` hash, not the folder name. The physical `Golden Era` path currently selects `GameBuildKind.Current`. Keep legacy `GameBuildKind.Golden` / D477 pins for compatibility and history; do not rename or rebind them.
- The promoted staging tree is no longer the active copy: `V:\olden_port_work\Current Era 25672315 BepInEx`. The prior Golden payload is recorded at rollback root `V:\olden_port_work\golden_era_legacy_rollback_20261004`; its prior GameAssembly hash was `d47706eb0ffedbda0ec07ede47abc778e6022ed820ae1a1fd23522d3acdb8416`. The receipt identifies this rollback location but does not document a restore test.

## Promotion Receipt

Receipt: [`promotion_receipt.json`](../artifacts/port_current/consolidation_25672315/promotion_receipt.json), status `promoted_installed_payload_proven`, recorded `2026-10-04T04:47:30.8191188Z`. It records two same-volume literal directory moves (0.02033 s moves, 0.52411 s total) and nine installed-file readbacks. It performed no recursive copy or whole-tree hash audit. The game was stopped; saves, cloud state, and profiles were not edited.

The readbacks include GameAssembly, executable, interop, level67, Core.zip, plugin DLL/PDB, ABI sidecar, and config. Installed OfflineUnlockMod DLL SHA-256 `0fd2009360dbd35a1cd62d3923ab3e80c527f0b5dc24455cda252b14a733d5d4` is byte-readback provenance only, not a compatibility pin. Plugin compatibility is ABI UnitBundle 1 / TownScene 2. Both optional diagnostic enable-flag files were absent; disabled copies were retained.

## Build And Findings

- Current compile completed in 20.23 s with 0 errors and 54 warnings. Explicit live-interop audit covered 1,218 references across 139 assemblies, with 9 existing allowlist entries and 0 new gaps.
- Five fixture tests and the isolated full-only target passed; invalid selector was refused and the Golden override was accepted. The strict current hint gate still fails with 39 flat findings and two confinement excesses. The explicit test-only exception is not release evidence. See `build_validation_tiers.md` and the scoped report in `../artifacts/port_current/preview_town_bugfix_25672315/README.md`.
- Performance: on 2026-10-03 the user confirmed the recurring hitch stopped after both optional diagnostics were disabled. The promotion receipt confirms both flags are absent. AI-driver versus live-probe cause was not isolated; this is not a code fix.
- Preview: the class-identity wrapper fix is source-reviewed, build-target proven, and included in the installed payload. The separate startup-deferral selector remains enabled, but its first-demand/lifecycle behavior has not been tested after promotion. Run 10 evidence belongs to an earlier candidate.
- Presentation: prior user feedback says neutral-unit previews tend to load custom meshes but town-aligned units show donors. New preview acceptance and the Stronghold Orc Tower recruitment glitch remain open. The native purchase callback, resulting screen/text and transaction are unlogged; no speculative fix was installed. No post-promotion launch or feature-level gameplay acceptance is recorded.

## Proof Boundary

| Tier | Current status |
| --- | --- |
| Source/static | Hash-to-scope identity and preview class-identity review are recorded. |
| Generated artifact | The 25672315 staged profile remains generation/build provenance, not an install pointer. Do not rewrite `live_parity_build_25672315.json` as an installed receipt. |
| Build target | Compile, explicit interop audit, five fixture tests, and isolated target results are recorded above; FullHint remains non-release. |
| Deployed/installed payload | Proven for the nine file readbacks in the promotion receipt only. |
| Startup smoke | Not run after promotion. |
| Runtime behavior | Hitch resolution is user-confirmed after diagnostic flags were disabled; current install behavior is otherwise untested. |
| User-visible gameplay | Prior neutral-preview feedback only; donor, town, recruitment, and post-promotion acceptance remain open. |

## Next Checks

Use the single in-game queue in `ingame_check_queue.md`. After a user-owned launch from the canonical path, record preview, town, battle, and Orc recruitment results there; do not create a second checklist. Keep the current receipt as installed-byte provenance, not a whole-install or gameplay certificate. The old F/V run history remains in `current_version_port_runtime_20261002.md` and does not override this post-promotion boundary.
