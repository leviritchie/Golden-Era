# Runtime Performance Profile - 2026-05-22

Scope: live Steam runtime at `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`, profile baseline from deployed `OfflineUnlockMod` build `0.1.294`; follow-up city-open fix deployed as build `0.1.295`.

Source/deployed DLL verification:

- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/bin/Release/netstandard2.1/OfflineUnlockMod.dll`
- `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.dll`
- Baseline profile SHA256: `D3C721D84D07370619229612930E4897512CBC7EC095A4DD5AE9F2D93CF1D6E1`
- Follow-up deployed build `0.1.295` SHA256: `F7A4C16E972D3BB9B0C8605ADDE24741F6BE939F891904F6CC10E1E376D28CDC`

Runtime evidence:

- `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\LogOutput.log`, last write `2026-05-22 14:51:59`.
- `C:\Users\<user>\AppData\LocalLow\Unfrozen\HeroesOldenEra\Player.log`, last write `2026-05-22 14:52:01`.
- Config was release-safe with `homm3ImportEnabled=true`, `homm3ReleaseUnitView=true`, `homm3ReleaseMapObjectUnitVisual=true`, `homm3ReleaseSafeCityTownUi=true`, `homm3CustomBiomeRegistration=true`, `homm3SwampAutumnTintProof=true`, broad `homm3ReleaseBattleUi=false`, and projectile disabled.

## Stall Timeline

`FrameStallMonitor` logged these main-thread gaps:

| Scene | Frame | Realtime | Gap |
| --- | ---: | ---: | ---: |
| `startMenu` | 473 | 6.370s | 3515 ms |
| `startMenu` | 733 | 11.050s | 2484 ms |
| `startMenu` | 742 | 20.442s | 8724 ms |
| `loadingScene` | 3958 | 56.511s | 6749 ms |
| `worldLight` | 3995 | 75.586s | 18097 ms |
| `cityNature` | 4265 | 81.355s | 2515 ms |

`Player.log` corroborates the same phase sequence:

- `Session: OnScenesLoaded` after game loading begins.
- Native asset cleanup before session load: `312.508300 ms` total, mostly `MarkObjects`.
- Native cleanup after battle/session exit: `994.849700 ms` total, mostly `MarkObjects` and `DeleteObjects`.
- City open timings: Fortress city open reported `2.519s` once and `1.474s` later.
- Battle setup was much smaller in this run: `grassArena = 0.234s`, plus `battle simulated by 664 frames`.

## Measured Mod Hot Spots

### UnitView map-swap / town-style unit billboard

`HOMM3_MAP_LOAD_PROFILE` rows show 100 native-shell custom map unit swaps:

| Shells | shellMs | townMs | diskFrameMs | idleLoadMs | postconditionMs |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 614.892 | 606.542 | 237.606 | 0.336 | 0.802 |
| 50 | 864.796 | 849.502 | 419.618 | 0.472 | 1.274 |
| 75 | 1055.225 | 1033.521 | 541.855 | 0.608 | 1.698 |
| 100 | 1211.389 | 1183.647 | 632.820 | 0.727 | 2.106 |

Profile interpretation:

- The map-swap path accounts for about `1.21s` total by 100 shells, or roughly `12.1 ms/shell`.
- `townMs` is almost the whole shell cost.
- `diskFrameMs` is `632.82 ms`, roughly `52%` of the measured shell path and `6.3 ms/shell`.
- Idle-frame bundle loads and postcondition checks are negligible in this run.
- The largest `worldLight` stall is `18.1s`, so map-swap work is real but not the whole stall. It is the clearest measured mod-owned slice inside map load.

Likely next root-cause target: cache or prewarm the per-entry disk map-frame texture path used by `TryLoadHomm3DiskFrameTexture`, while keeping missing/corrupt assets fail-closed. Do not replace missing bundle/frame handling with battle-frame fallbacks.

### Custom biome material registration

The log contains 78 repeated Il2CppInterop errors for stale `beg` renderer lookup fields:

- `bseu`, `bsey`
- `bsdu`, `bsdy`
- `bscg`, `bsck`

The same validation later succeeds through current fields:

- `bsge` material lookup
- `bsgi` road lookup

Profile interpretation:

- This is not the largest measured stall by itself, but repeated failed native field lookups and error logging during `worldLight` terrain setup are avoidable startup/map-load cost.
- The root cause is compatibility probing of known-stale terrain renderer fields after current fields already exist.

Likely next root-cause target: teach `Homm3SwampAutumnTintProof` to resolve and cache the current renderer dictionaries once, then stop probing stale field symbols for that renderer type/session. Keep the stale names in `GameSymbols.TerrainMaterial` as historical hints, but avoid repeated native lookup failures in hot terrain validation paths.

### City black-screen transition, backdrop, and town layers

City UI slow-call logs:

- `Player.log`: `SmoothOpening` entered city mode with `sleeping:180` before `ModeCity.Activate`.
- First Fortress entry: `time spent for City:"homm3_fortress_city" = 2.519`.
- Later Fortress re-entry: `time spent for City:"homm3_fortress_city" = 1.474`.
- `HoMM3 Stronghold town layers: sync took 372 ms`
- `Custom city backdrop apply took 476 ms`
- `Frame stall monitor: cityNature gap 2515 ms`

Profile interpretation:

- The player-visible black screen before town render is real and is mostly represented by native `SmoothOpening` city mode timing (`sleeping:180`, then `ModeCity.Activate`, then `time spent ... = 2.519` on the first entry).
- The custom city/town layer work happens after the city transition has already reached activation/logged city timing. It is a significant extra cost, but it is not the only or primary source of the several-second black screen.
- The earlier same-frame suppression regression is still relevant: do not reintroduce frame guards around visibility-critical city panel work.

Follow-up fix: build `0.1.295` adds `Homm3FastCityOpeningHook`, gated by `homm3FastCityOpening` (default `true`) and `homm3FastCityOpeningMaxFrames` (default `12`). It patches only the `SmoothOpening` city frame-count methods registered in `GameSymbols.SmoothOpening`, then clamps only registered HoMM3 custom city SIDs through `Homm3CustomFactionRegistry.IsCustomCitySid`. This skips the learned fade/zoom sleep for custom towns without bypassing `ModeCity.Activate`, `BhCityUISession`, town UI visibility recovery, or native gameplay activation.

Keep the boundary narrow: do not patch generic `SmoothOpening.Sleep(int)` or city activation methods to solve this symptom unless fresh logs prove the frame-count hook is no longer reached. A broad sleep patch can affect world/battle openings, while an activation patch risks creating real gameplay wait bugs.

Startup verification after clearing the stale BepInEx chainloader metadata cache:

- `HoMM3 fast city opening: patched 8 SmoothOpening frame-count method(s), maxFrames=12.`
- `Launcher config ... build=0.1.295`
- `Chainloader startup complete`

Second follow-up after user retest: city entries now showed `SmoothOpening mode city ... sleeping:14`, but `time spent for City:"homm3_cove_city"` still measured `2.189s` to `2.871s`. That means the original fade-window hypothesis was incomplete. The remaining measured mod-owned first-city costs were `HoMM3 Stronghold town layers: sync took 785 ms` and `Custom city backdrop apply took 882 ms`, so the next experiment prewarms static custom town presentation assets through the existing strict caches.

Startup smoke for the prewarm experiment loaded `10` backdrops and `549` layer textures in `4549 ms` with no failures. This should remove cold decode/file I/O from city entry, but it intentionally moves that cost to startup; keep it only if live city-open testing shows a worthwhile reduction.

## Noise That Distorts Profiling

These are not necessarily the primary stall causes, but they inflate log volume or exception overhead:

- 12 suppressed `BhSelectedUnitHud.beet` `KeyNotFoundException` warnings for `h3_lizardman`, `h3_serpent_fly`, and `h3_gnoll`.
- 23 recruitment icon postfix info logs.
- 27 hero portrait stale surface warnings.
- 12 custom game stale probe warnings.
- Combat music bundle load failed with `Method unstripping failed`.
- Stronghold town build effects sound load failed due missing `DownloadHandlerAudioClip..ctor(string, AudioType)`.
- `Player.log` repeated `BhTooltipUnitPassive.tng` null refs on recruitment ability hover.

Interpretation:

- The selected-HUD exceptions are behavior debt, not just logging noise. They run in combat and can leave stale UI state; fix the native SID seeding/alias root rather than downgrading the logs.
- Stale startup surface warnings should be pruned from required/profiled slices where they are known historical names, otherwise performance runs waste time and bury real drift.
- Audio load failures are currently feature failures and profiling noise. Fix by using a release-safe audio loading path or disabling the failed loaders during performance measurements.

## Ranked Optimization Backlog

### Adventure-map FPS pass (2026-07-26) — source/static + build proven; runtime FPS unproven

Implemented against persistent adventure-map FPS (not load/city stalls):

1. Play config: `homm3LiveProbeWorkbench` defaulted **false** (was true under release-safe profile) — removes 15-frame disk status writes during map play.
2. Change-gated map LateUpdates: native-shell transplant (mesh/MPB/transform), map material sync (material-id snapshot), map-array Hex/Lit presentation, camera-facing epsilon skip, idle/hero animator register thrash + idle Tick apply-on-advance.
3. Swamp tint: session cache of resolved native lookup symbols + negative cache of failed stale field probes (`bseu`/`bsey`/…) after live `bsge`/`bsgi` resolve.

**Proof tier:** Golden Era `OfficialDeobfBuild` compile succeeded; `validate_custom_town_billboard_contract` OK. Dense-map FPS A/B not yet run — do not claim user-visible FPS proven until a live adventure-map remeasure.

Remaining from May load/city backlog (deferred from this FPS pass):

1. Cache or prewarm UnitView map-frame disk textures for custom map unit billboards; the measured disk-frame slice is `632.82 ms` across 100 shell swaps.
2. After `Homm3FastCityOpeningHook` is deployed, rerun a city-open smoke and verify the log contains the clamp line plus a much smaller `SmoothOpening mode city ... sleeping:` value. Then optimize the remaining mod-owned city backdrop/layer cost by caching decoded town backdrop/layer assets by faction and current city-panel root identity. Do not cache visibility-critical screen state by frame alone.
3. Prune stale probe/name-hint warnings from normal release profiling runs, especially old hero/custom-game surfaces that are already known historical.
4. Fix selected-HUD custom SID seeding for sibling Fortress units so combat does not spend time throwing and suppressing `KeyNotFoundException`.
5. Separate audio-feature failures from performance runs: combat music and town build-effect audio currently fail in the live release path.

## Measurement Gaps

- The current built-in profile has aggregate timing for custom UnitView map swaps, but no aggregate timing for custom biome texture/material refresh, town layer file loads, or city UI visibility lifts.
- `FrameStallMonitor` only logs gaps above 2 seconds and does not bracket which mod operation was active. Keep it, but add narrowly scoped `Stopwatch` aggregates before making deeper performance claims.
- No fresh controlled A/B run was performed in this pass; this report uses the latest live logs and matching deployed DLL.
