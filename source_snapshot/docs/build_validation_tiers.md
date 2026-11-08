# OfflineUnlockMod build validation tiers

Operational contract, adopted 2026-10-01 at the user's request. Before this, every plugin build ran about 137 Python contract validators one after another, roughly 13 minutes per build. A unit that the cs-bake rollout was rebuilding at that moment could fail an unrelated plugin deploy, and did so twice in one day. Deploys had become slower than the coding they shipped.

## Tiers

| Tier | How | Runs |
|---|---|---|
| Quick (default) | `dotnet build -c Release -p:OfficialDeobfBuild=true -p:DeployPluginToGame=true "-p:GameRoot=<Golden Era>"` | Compile; `ValidatePluginLiveInteropRefs`; `ValidateGameSymbolsHintContract`; `RefuseDeployWhileGameRunning`; `ValidateHomm3SkillIcons` (file existence); `ValidateOfflineUnlockModDeployHash` (installed DLL readback); `EmitPluginPayloadAbiSidecar` / `ValidatePluginPayloadAbiSidecar` (payload-version sidecar written for the deployed DLL and read back, guard warn-only; docs/plugin_payload_abi.md); the bundle payload checks inside `DeployPluginToGame` when a bundle deploy flag is set |
| Full | add `-p:FullValidation=true`, or set `ReleaseCandidateBuild=true` | Everything above plus every `Validate*` / `Audit*` contract target, the vocabulary generator and the post-deploy readback validators, exactly as before the tiers existed |
| Opt-in audits | `RunExpensiveArtifactAudits`, `RunExpensiveHomecomingArtifactAudits`, the `Deploy*Probe*` / scenario-payload flags | Unchanged; off by default in both tiers |

## Current-build GameSymbols gate

The active port is Steam build `25672315` (manifest `7750145598966689713`), selected by its
`GameAssembly.dll` SHA-256 `d9972b0e7f7dd1c17758808e2f1b80e0a728946416d9a41deaa99bad744de53a`.
The `Golden Era` folder name is not a build-kind selector. Official Deobf builds now run
`ValidateGameSymbolsHintContract` against the current interop by default. An intentional legacy check
must explicitly pass `-p:GameSymbolsHintContractBuild=golden`; any other value fails closed.

Until 2026-10-06 the current-interop baseline failed this gate. The captured run evaluated 121 flat
type-hint groups and left 39 unallowlisted flat findings (20 ambiguous, 19 misses). Symbol-literal
confinement also reported two files with three `AccessTools.Method` calls each, against an allowance
of two. Every build since then, the v0.1.319 RC included, passed `SkipGameSymbolsHintContract=true`.
The captured report is
`artifacts/port_current/preview_town_bugfix_25672315/current_game_symbols_hint_contract.json`.

The gate passes again as of 2026-10-06:
- The extra lookups go through `GameMember.FindOwnedPatchMethod`, and both confinement lines were removed.
- The current flat check now evaluates each group as `GameSymbolsCurrent.g.cs` binds it at runtime.
  A scoped group is checked by its generated live literals. A group the generator refused is reported
  as `refused`, which is fail-closed and not a finding. Before this, the check used Golden Era literals
  that the runtime never resolves on the current build.
- Of the 39 findings, 23 resolve to exactly one live type, and 2 are generator-refused
  (`AiDriverScreenDump.WorldHeroScanTypeHints`, `BattleForecast.CalculatorTypeHints`).
- 17 multi-type lists remain. 14 of them are left from the 39. The other 3 show up only now, because
  they had looked ok only through reused Golden names. Each one matches an existing `golden|flat|…|ambiguous`
  line and ships on both builds, so they were seeded as `current|…` lines in
  `tools/game_symbols_hint_allowlist.txt`. Those lines are shrink-only.

The selector, flat-ownership and current-flat fixtures (nine since 2026-10-06) run in the full tier as
`ValidateGameSymbolsHintContractSelector`; the target has a 30-second timeout and no GPU stage.
The original five tests passed in 0.003 seconds; the measured Python invocation took 0.346 seconds with
22.2 MiB sampled peak working set and no child workers or VRAM use. The receipt is
`artifacts/port_current/preview_town_bugfix_25672315/selector_fixture_metrics.json`.

For a narrowly scoped test build only, `-p:SkipGameSymbolsHintContract=true` is an explicit exception
when the known current baseline would block an unrelated candidate fix. Such a build must separately
run the touched owning validator and `ValidatePluginLiveInteropRefs`; it is not a full-gate or release
validation result. Do not use the exception for release or claim the current symbol contract passed.

The quick tier keeps only the checks that protect the installed game:
- a call the live interop doesn't have crashes the game at runtime;
- a deploy over a running game, or one that never reached disk, leaves the install in an unknown state.

Contract drift is the full tier's job.

## Code-only deployment

Add `-p:DeployPluginBinaryOnly=true` for a code-only change that keeps the installed asset contract intact. The established deploy target then writes only `OfflineUnlockMod.dll`, its optional PDB, and the generated payload-ABI sidecar. It does not republish art, catalogs, the import table, auxiliary bundles, or asset cleanup deletions. Default deployment remains unchanged. Invalid boolean values and conflicting main-target bundle/scenario deploy flags are refused, not silently converted to a broader deploy.

The existing live-interop, GameSymbols, game-running refusal, ABI, and installed-hash checks still run. This mode does not replace asset delivery when a change needs new content, and separately requested standalone payload/diagnostic targets are not its scope. Runtime compatibility remains a separate proof tier.

The owning gate is `tools/validate_binary_only_plugin_deploy_contract.py`, run in the full tier and before an explicit binary-only deploy. Source/XML checks and its full-tier target passed on 2026-10-02; isolated MSBuild option checks accepted true/false and refused an invalid value and each main bundle/scenario conflict. Independent review found no current asset-write leak. The first code-only Golden Era deploy passed compile, live-interop, GameSymbols, installed DLL/PDB hash, and ABI readback; all three intended files also matched independent source/installed hashes. Evidence: `V:/olden_port_work/golden_era_map_loading/deploy_20261002_171401.log` and its `_readback.json` sibling. This is installed-payload proof, not startup or runtime proof.

## When the full tier is required

- Before any release or release-candidate package. `tools/release_installer/package_stronghold_release.ps1` passes `-p:FullValidation=true`, and releases still need the user's approval.
- When a change touches the contract a validator owns. Run that validator directly (`python tools/validate_<contract>.py`) or run the full tier.
- On demand, when anyone wants a whole-tree contract check.

## Rules

- New contracts still get a validator wired into the csproj, gated as `'$(FullValidationNormalized)' == 'true' and (...)`. A new validator joins the quick tier only if a failure would crash the game or corrupt the install.
- A quick-tier deploy is **build target proven** plus **deployed payload proven** for the DLL only. Do not claim a contract holds on the strength of a quick build.
- `-p:DeployPluginToGame=true` is required for any deploy. Without it the build compiles and the deploy-hash readback fails against the old installed DLL, which is the intended signal.

## Performance contracts

Validation processes have finite timeouts. Existing short limits stay intact;
general checks have a five-minute refusal ceiling, while the existing CS-bake
and town zero-streak GPU fixture contracts have a separate 35-minute ceiling.
These limits are not measured execution times or quality exemptions. A timeout
fails validation. The quick tier keeps the same validation scope. Its existing
game-process check now uses the shared launch guard's game-only mode, which
refuses running or unknown process state without disk, memory or GPU checks.

The full tier also runs one lightweight synthetic performance regression gate,
`ValidateValidatorPerformanceContract`, protecting invocation-local reuse,
reservation ordering, explicit local scope and build budgets. Its suite budget
is 90 seconds, with a two-minute MSBuild timeout. See
`docs/validator_performance_corrections.md` for integrity boundaries and measured
evidence. Source/fixture and isolated full-only target checks are proven; the
target is skipped in the default tier. The existing town-scene target now runs
bounded synthetic CUDA boundary parity before complete all-catalog coverage.
That target passed in 45.74 s and the lightweight regression target in 9.738 s,
both with deployment disabled. This does not prove a whole full-tier build or
runtime/gameplay behavior.

## Measured

On 2026-10-01 the quick tier took 27 s for a fresh compile plus readback and 12 s incremental with deploy, against about 13 min before. Cove and Fortress `ssr_v1` were installed on plugin `72fd8d0e` deployed this way.
