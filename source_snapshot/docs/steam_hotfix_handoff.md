# Steam Hotfix — Handoff State (May 11, 2026)

## What was done

### Obfuscation mapping (map_obfuscation.py)
- Rewrote matching algorithm: structural fingerprint (sorted method signatures with type categories) + token-level Levenshtein distance
- Windowed global-optimal matching (50 types each direction)
- ~97.5% match rate, ~8s runtime
- Output: `rename_map.json` (833 type renames, 7091 method renames, 1774 field renames)

### Applied renames
1. **Type renames** (surgical_rename.py) — typeof, global::, nameof, new X(). 4 files.
2. **Method string-literal renames** (apply_method_renames.py) — `"oldName"` → `"newName"` in patch/reflection calls. 7091 renames, 20 files.
3. **Field string-literal renames** (same script, added field_renames) — 1759 renames, 21 files.
4. **Backing-field support** — `<oldName>k__BackingField` → `<newName>k__BackingField` added to same script.

### Runtime fixes
1. **`BhBuildingView.byza`** — was a pre-May-6 name; updated to `bzak` (current live name) in Plugin.cs.
2. **`fbi` class restructure** — old auto-properties `cjam`/`cjan` removed, replaced by explicit fields `cjby`/`cjbz`. Updated Plugin.cs and Homm3CustomUiIconHook.cs.

## What's deployed (Steam release build)
- `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.dll`
- `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\config.json`

## Remaining deferred issues

### May 11 targeted UI/combat follow-up
- Bottom selected-hero portrait is separate from the top/right `BhHeroUIElement.heroIcon`. The live surfaces added for the bottom HUD/city visiting hero are `BhHeroHUDPanel.vqv/gir/giq` and `BhHeroWithPartyCityView.tyt/tyu/tyv/tyw/tyx`.
- Backwards attack-facing should not trust the stale `ecd.bbvb -> ipd` mapping. Live `ipd` is no-arg; patch the `ecd` `void(object,BattleEventArgs)` handler shape and filter by attacker drawer/unit/root.
- Startup warning from the first May 11 attack-facing attempt: patching all live `ecd void(object,BattleEventArgs)` handlers registered 40 postfixes and was too broad for startup stability. Keep the release allowlist narrow (`cvf`, `mhg`, `bbuv`, `icf`, `myh`, `bbwc`, `nay`, `bbwm`, `mez`) until native tracing identifies the exact attack-start successor. `BepInEx/ErrorLog.log` later showed native crashes in generated wrappers for `can` and `bbwr`, so do not re-add those without native decompilation.
- Startup crash root cause, May 11: `BepInEx/ErrorLog.log` showed `AccessViolationException` in `Homm3ImportReleaseBattleUiHook.PatchBattleUiImageSetters` while Harmony/IL2CPP resolved Unity `Image.sprite` / `Image.overrideSprite` / `RawImage.texture` setters. Do not patch global Unity UI setters at plugin load on this release; use targeted view postfixes/components instead.
- Build-tree dwelling icons can be overwritten by no-arg `BhBuildingView` refreshes. Preserve the resolved key per view and prefer live `BhBuildingView.bzar` as the specific building SID before falling back to the broader `dvw` model.
- Static release `Core.zip` data for `h3_goblin` and `h3_wolf_rider` has `defaultAttacks[].damageDealer.triggerCounter=true`, no base passives, and `numCounters=1`. If they still fail to provoke counters, investigate the live attack command/selected-unit alias path instead of changing JSON first.
- May 12 retaliation regression: do not donor-alias the live release battle `Unit` SID/config ids inside `BhSelectedUnitHud.befv`. After the May 6 rename pass those writes hit real live fields (`Unit` + nested config objects), and even transient mutation can leak into battle action/retaliation state. The release HUD guard should seed missing dictionaries and apply portraits without mutating the actual `Unit`.
- May 12 attack-facing correction: the live precise target-direction surface is `BhBattleTimelineHelper.bbtg(Unit attacker, Unit target, ecd attackerDrawer, ecd targetDrawer)`, the rename of May 6 `bbsg`. Prefer that helper over chasing every `ecd void(object,BattleEventArgs)` listener; it has the attacker/target drawers directly and avoids stale event-name guesses.
- May 12 selected HUD recovery correction: base melee Stronghold units can legitimately have no release action-bar ability wrappers. Do not call `BhUnitControlsView.Clear()` / hide controls just because `FindReleaseActionBarAbilities` returns empty; preserve existing native controls and log `kept: no live release action-bar abilities`.
- May 12 combat log follow-up: if logs say `timeline helper patched=False`, the helper type lookup missed the live interop namespace. Resolve `Hex.Session.Battle.BhBattleTimelineHelper` or scan loaded assemblies by type `Name`, then patch the four-arg `Unit, Unit, ecd, ecd` method.
- May 12 adventure HUD warning: hero portrait replacement must not call `image.gameObject.SetActive(true)` on HUD children. Native code owns adventure HUD/city/battle visibility; portrait hooks should swap sprites only on already-created surfaces.
- May 12 selected HUD exception warning: repeated `BhSelectedUnitHud.befv` `KeyNotFoundException` rows for `h3_*` are noisy, but skipping the native handler in the prefix breaks native selected-unit state, including ability cooldown behavior and possibly HUD visibility after combat. Do not skip `befv`; keep native flow and suppress only the known dictionary exception in the finalizer.
- May 12 combat log follow-up 2: once `timeline helper patched=True`, do not also patch/log fallback `ecd` battle event handlers by default; their missing-attacker rows consume the diagnostic cap and obscure whether `BhBattleTimelineHelper.bbtg` actually fires. Use timeline-only logs unless the helper fails to register.
- May 12 selected HUD stale-event rollback: tracking the last selected custom SID and skipping stale/non-custom `BhSelectedUnitHud.befv` events regressed cooldown/HUD behavior. Do not repeat that approach; stale selected-HUD events still need native state updates even when their custom SID dictionary lookup is later suppressed.
- May 12 counterattack trace: the runtime warning `Didn't find correct target to attack...` is not present as a plain ASCII/UTF16 literal in live/May 6 dumps, Steam metadata, or `GameAssembly.dll`; do not waste time repeating literal searches. The active diagnostic instead filters `UnityEngine.Debug.LogWarning*` for that warning and `Multitarget doesn't support attacks with walking`, then logs a compact managed stack under `Homm3AttackCommandProbe unity.warning` so the native caller can be mapped from the exact emission path.
- May 12 counterattack trace 2: logs show custom-attacks-vanilla reaches vanilla defender counter lookup successfully (`caster='trogl*'`), but later `eiy.bdup` can execute with the custom attacker as `abilityCaster`. Native disassembly maps `een.bdig(Unit,Unit,Unit,dxs,int[],float,bool)` as the helper that constructs `eiy`; it passes its third Unit parameter as `eiy.cglf` (attack executor/caster) and second Unit parameter as `eiy.cglg` (target). The active probe logs this as `Homm3AttackCommandProbe een.counterEventBuilder`; use that before patching behavior so we know whether the bad caster is selected before `eiy::.ctor` or by a stale constructor signature assumption.
- May 12 counterattack trace 3: `Homm3AttackCommandProbe een.counterEventBuilder` now includes `role=...`, focused `unitAFlags`/`unitBFlags`/`unitCFlags`, and `unitCBuckets`. In the next run, compare `custom_executor_from_vanilla_builder` rows against nearby `event.eiy.bdup.pre` rows. If `unitC` is custom while `unitA`/`unitB` are vanilla and the ability owner has `bxpj:add_attack_after_counter_melee=True`, the bad `CounterAttack [0]` event is probably the native add-after-counter branch selecting the original custom attacker as executor.
- May 12 counterattack trace 4: fresh logs showed both the correctly scheduled vanilla-defender counter event and a later inverted `custom_executor_from_vanilla_builder` event. Live and May 6 `een.bdhu` disassembly still match around the `bdig` callsites. A controlled downstream test briefly stripped the second path array for active `h3_*` `CounterAttack` calls entering `ems.beyu`, but that was falsified because it made all retaliation stop. Keep this path diagnostic-only and trace upstream path construction/meaning instead.
- May 12 cooldown/UI adjacency: the blank one-turn cooldown slots on many Stronghold/Tower units are probably from the selected-unit HUD/native-state recovery path, not from custom unit JSON cooldown data. Live Core.zip samples for simple `h3_*` melee units have no action-bar `abilities`, no `alternativeAttacks`, and no cooldown fields on default/counter attacks. Existing selected HUD notes already warn that suppressing/mutating the native selected-unit path can regress one-turn cooldown display. Treat this as related recent damage, but do not use it as proof of the counterattack root: counterattack logs show a vanilla defender counter event is scheduled and reaches `ems.beyu` before being rejected with a non-empty walk path.
- May 12 path-strip rollback: the `ems.counterPathFix` experiment was falsified. Stripping `pathB` from counterattack calls made nothing retaliate, including custom-vs-custom retaliation that previously worked. Do not reintroduce this mutation; leave `ems.beyu` diagnostics read-only and trace the upstream path construction/meaning instead.

### Orphaned patches (commented out, need re-mapping)
Documented in `docs/steam_hotfix_orphaned_patches.md`. Each needs a developer to:

1. **BattleTooltipProbe.cs (7 patches)** — methods `tbw`/`tbx`/`tby`/`tca`/`tcb` on `BhTooltipUnit`, `tch`/`tar` on `BhTooltipUnitCountLosses`. Need to find new first-obfuscated-method in each type via live dump.

2. **Homm3StrongholdCityMusic.cs (8 patches)** — methods `mok`/`czu`/`blzt`/`lle` on `fvh`, `nev`/`blzo`/`fih`/`kfb` on `fvf`. Entire sound-registry patch block disabled. Need to verify `fvi`/`fvg` replacements.

3. **Homm3StrongholdTownLayers.cs (2 patches)** — `BhCityUISession.tvw` and `BhBuildingsManager.baeq`.

4. **Plugin.cs (3 patches)** — `BhDemoIconTxtUI.ypb`/`ypc`, `Loader.vdk`.

5. **RetaliationForecastFix.cs (1 patch)** — `ekx` type entirely removed; `BhHealDamageForecastPanel.Show` signature changed.

6. **Homm3WarcryWrapperProbe.cs (entire elo section)** — `dzs` type removed, `elo` fields (`cgxc`, `cgxd`, `hza`, `gbk`, `khv`, `cgxb`) renamed. The whole probe is behind `#if false`.

### Known runtime errors (gracefully handled but noisy)
- `fbi` fallback fields: `cidk`, `cidl`, `ciyy`, `ciyz`, `cjao` all fail silently after `cjby`/`cjbz` succeed. The code has fallback chains that try ~6 field names each; the first two now work.

### Build status
- Compiles 0 errors, 38 warnings (all pre-existing: unused variables in disabled blocks, etc.)
- `dotnet build` target: `netstandard2.1`
- Deploy path: `BepInEx\plugins\OfflineUnlockMod\`

### Tools created/modified
| Tool | Location | Purpose |
|------|----------|---------|
| `map_obfuscation.py` | `tools/` | Generates rename_map.json from two dump.cs files |
| `surgical_rename.py` | `tools/` | Applies type-level renames (typeof, global::, nameof, new) |
| `apply_method_renames.py` | `tools/` | Applies method/field string-literal renames with backing-field support |
| `apply_renames.py` | `tools/` | Original renamer (DEPRECATED — word-boundary approach unsafe for short names) |
| `verify_patch_surfaces.py` | `tools/` | Cross-references patches against live dump |

### Dump files
| Dump | Date | Location |
|------|------|----------|
| May 6 playtest | May 6 | `tools/il2cpp_out_20260506/dump.cs` (47 MB) |
| ~~Live Steam~~ | ~~May 10~~ | ~~`tools/il2cpp_out_live/`~~ **removed** — stale; regenerate per `tools/IL2CPP_DUMP.md` from Golden Era install |

Golden Era source path: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\` (`GameAssembly.dll` + `HeroesOldenEra_Data/il2cpp_data/Metadata/global-metadata.dat`).

### Next developer steps
1. Fix the orphaned patches (see above and `steam_hotfix_orphaned_patches.md`)
2. Run `verify_patch_surfaces.py` against each fix to confirm
3. Rebuild and test in-game
4. Clean up remaining false-positive field fallback chains in Plugin.cs
