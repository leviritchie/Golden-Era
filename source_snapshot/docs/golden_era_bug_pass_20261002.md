# Golden Era Bug Pass - 2026-10-02

Status: scoped pass complete; source/fixture validated and Golden Era build target proven. Nothing from this pass has been installed or runtime-tested.

## Scope

Log-led review of current Golden Era plugin code, with bounded independent reviews of recent town/UI and water/audio changes. This is not an exhaustive audit of every feature or asset pipeline. Existing dirty work and concurrent map-death/live-port changes are outside this pass.

## Latest Runtime Evidence

The logs describe plugin `0.1.318` on Golden Era. Both files ended before the faction-icon fix `71f529b7c5` (15:26 CDT) and build-tree change `21fb0ec403` (15:27 CDT); they cannot validate those changes.

| Evidence | Captured State |
| --- | --- |
| Golden Era `BepInEx/LogOutput.log` | 2026-10-02 15:16:05 CDT; 10,112 lines; 1,736,916 bytes; SHA256 `43E0A374A7FA4277E3C70C17ED3CE87F7E3010F958993D4B83FD404503542356` |
| `C:/Users/<user>/AppData/LocalLow/Unfrozen/HeroesOldenEra/Player.log` | 2026-10-02 15:16:13 CDT; 8,502 lines; 369,954 bytes; SHA256 `655B10EE62580A978D0C299883FB1ACAEC7024E72A959493B03D5CE01D144B7E` |
| Live runtime | No game process found by log triage; bridge frame 75664 stayed unchanged across a 1.6-second sample. Its `ready` record is stale, not runtime proof. No bridge requests or game mutations were made. |

Repo `live.log` is an older port-tool failure, and `error.log` contains Codex backend traces, not game diagnostics. The other LocalLow `HeroesOE/Player.log` is from May and is not the current session.

### Actionable Findings

- Six plugin material self-check errors concern `HEX_VERTEX_DISPLACEMENT_FLAG` on energy, plasma, and ice elementals. The presenter clears donor displacement, then deliberately applies the catalog-approved body-flow effect; its subsequent self-check incorrectly rejects that effect. This is a diagnostic false positive, not evidence that those models were invisible.
- The plugin log has 1,157 Harmony `AccessTools` lookup warnings. Repeated Bulwark rune reads probe each exact accessor/field hint as multiple member kinds through logging APIs. These expected metadata misses produce misleading warnings and repeated logging work. The pass targets that confirmed reader, not every warning in the log.
- Six real Unity `NullReferenceException`s occur in selection-outline updates at `Renderer.set_sortingLayerID`, through the native chain `bep.kzm -> ets.bhiq -> fau.binj`. Player.log lines 1432, 5145, 5162, 6070, 8372, and 8389 identify the failures. Ownership remains under investigation; no broad exception suppression is justified.

### Other Unresolved Evidence

Player.log has 14 missing city ambient additional-sound config errors (seven Rampart, seven Inferno), two battle-music lookup failures, and 34 `Hero by id -1 not found` messages. Its 162 `Critical Error` headers are mostly side-state transitions (144) and SmoothOpening messages (15), plus the two music failures and one EOS login-state transition. These counts do not establish 162 crashes; the session ends with orderly player-leave and asset unloading.

Installed `DB/city_ambient_sounds.json` does contain Rampart/Inferno faction rows; their `additionalSound` values are empty, inherited from the `nature`/`demon` donors. No arbitrary additional track was assigned to silence the errors. Native city-music lookup errors are separate from battle-music errors: Rampart/Inferno sidecar music loads and starts in the plugin log, while the native battle-music failures at Player.log 4853/4872 remain unexplained. Unit clip-audio routing does not own the battle background-music lookup.

The outline trace found no renderer identity linking the native failure to a plugin-owned object. Failures occur through Update, input, and focus paths, not only town exits. Before changing cleanup or adding a guard, capture the failing renderer's identity/hierarchy and correlate it with owned-root teardown. No exception finalizer or broad suppression was added.

The latest town log shows repeated Inferno environment/layer application and native-owned mesh picks, without a pick-filter exception. The current Bone Foundry menu failure remains tracked in `docs/homm3_necropolis_bone_foundry_investigation.md` and the single in-game queue; a blank icon alone does not establish its dispatch cause.

## Changes

- The Hex/Lit visibility check now accepts FLAG displacement only when one matching catalog row, the current mesh color stream, the battle/map lane, and every displacement material value agree. TREE and unconfigured displacement still fail. The shared readback predicate handles already-rebound materials on repeated presentation passes and rejects NaN/non-finite results; no transient/global material allowlist is used. No visual effect or lane selection was changed. The existing mesh-FX build validator pins the source contract; this is not a Unity runtime behavioral test.
- Bulwark rune reads now use the pure-BCL `GameMemberValueReader`, preserving exact alias order, property/field/zero-argument-method priority, and derived-to-base lookup. Property/field metadata uses exact lookups rather than allocating whole-member arrays. Expected misses no longer generate Harmony warnings. Real getter or metadata failures stop the read and retain the feature's capped diagnostic instead of silently reading another alias.
- The full build tier runs the new reader validator and an executable fixture compiled from the production reader. The fixture requires PowerShell 7 (`pwsh`), fails clearly when it is unavailable, and has a 30-second execution limit; there is no legacy-shell fallback. It covers alias order, inheritance/member-kind priority, null continuation, zero-argument overloads, indexers, ambiguous metadata, private inherited members, and throwing getters.
- The symbol-confinement allowlist was shrunk for the three removed Bulwark `AccessTools` calls. No new allowance was added. Bone Foundry documentation now distinguishes its earlier icon-log capture from the newer session instead of presenting obsolete line numbers as current evidence.

## Verification

Baseline normal Release build with `OfficialDeobfBuild=true`, explicit Golden Era `GameRoot`, and `DeployPluginToGame=false`: passed in 57.46 seconds. Live interop audit: 1,206 member references, 10 pre-existing allowlisted findings, zero new findings. Golden Era symbol gate: 20 pre-existing allowlisted findings, zero new findings. Build warnings include existing assembly-version conflicts and NuGet vulnerability-feed SSL failure; neither is presented as resolved by this pass.

Final normal no-deploy Release build: passed in 10.63 seconds, zero errors, 33 existing warnings. Live interop audit remains 1,206 references into 139 assemblies, 10 pre-existing allowlisted findings, zero new findings. Golden Era symbol gate remains 20 pre-existing allowlisted findings, zero new findings. An earlier post-change build correctly failed on stale allowlist counts; shrinking only those removed-call entries resolved it without bypassing a gate.

Focused results:

| Check | Result / Proof |
| --- | --- |
| `ValidateGameMemberValueReaderContract` MSBuild target with `FullValidation=true` | Passed, including the production-reader executable fixture |
| Reader validator/fixture after private-member and exact-lookup review additions | Passed |
| Mesh-FX catalog/source contract | Passed, 366 entries; source/static only |
| Runtime UI sprite-persistence source contract | Passed; does not validate the post-log icon fix in game |
| Town scene3D pick contract `--static-only` | Passed. The unscoped measured artifact audit timed out after 90 seconds; it was not rerun broadly or represented as passed. No town-pick code changed in this pass. |
| Unit clip-audio source contract | Passed, 11 stock states |
| Symbol literal confinement | Passed: 272 pre-existing allowed AccessTools calls, 619 allowed literals; allowance only shrank |
| Obfuscated-symbol audit on the four touched runtime source files | One existing `count` string finding outside changed lines; no new raw generated-name reference introduced |
| Documentation contract | Passed |
| Independent scoped code review | Closed with no remaining findings after idempotency, fail-closed numeric checks, and fixture/validator coverage were corrected |

The full validator fleet was not run; owning validators and relevant focused checks were run. The working-tree build also included concurrent map-death/live-port work, which this pass neither altered nor claimed. No installed-payload, startup, runtime, or gameplay claim is made, and no candidate was added to the installed-only in-game queue.
