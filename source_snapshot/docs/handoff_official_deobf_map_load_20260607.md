# Agent Handoff: Golden Era Map Load (2026-06-07)

**Branch:** `codex/recover-detached-map-state-20260602`
**Prior transcript:** [Golden Era map load thread](1b15eb74-a897-4acb-8383-452d5d100849)
**Target install:** `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`
**Port-smoke config:** `tools/official_deobf_port_smoke/config.port_smoke.json` (Blitz auto-launch, Stronghold vs Human)

---

## Goal of this thread

Fix **Golden Era** runtime so the port-smoke profile can **start the plugin** and **load Blitz** with HoMM3 custom factions (terrain, unit map meshes, town/dwelling billboards, battle presentation). This thread focused on **startup** and **map load** blockers after v4 presentation work.

---

## What is fixed (verified by automated probe)

| Symptom | Status | Fix |
|--------|--------|-----|
| Plugin startup fail (selected-unit HUD action bar) | **Fixed** (`002a88bf`) | Shape-first `GameMember.FindFirstMethod` for `BhUnitControlsView` on deobf interop |
| Map load `MissingMethodException` on `ConfigElementBase.get_id()` | **Fixed** (`a9b14b63`) | `DeobfInteropCompat.GetConfigElementId` reads `field_Public_String_0` on `ConfigElementBase` base only |
| Map load `MissingFieldException` on ambient `ciwk` (hero prefix regression) | **Fixed** (`a9b14b63`) | Lookup prefix uses narrow `EnsureHeroBiomeSoundLookupMappings`; ambient static uses `TryExtendStaticArraySlot` |
| Unit map mesh swaps during load | **Working** | Hundreds of `Homm3Import UnitViewHook: swapped` lines in probe log |
| Custom terrain tile-code registration | **Partially working** | Tile codes 8–17 register; packed terrain material rebuild is still unresolved on Golden Era |
| Scene reaches playable map | **Working** | `worldLight` reached in 120s probe |

**Latest good probe:** `artifacts/official_deobf_startup_probe_20260607-140610/`
- `STARTUP_OK`, `AUTO_LAUNCH_OK`, `MAP_LOAD` hit, 0× `PLUGIN_LOAD_ERROR` / `LOG_FATAL` / `REGISTER_REQUIRED_FAIL` / `get_id`

---

## What is NOT fixed (known open debt)

### 1. Hero biome sound — custom tile codes (high priority, non-blocking for load)

- **Symptom:** ~3k–7k `IndexOutOfRangeException` lines from native `ezc.bicr(int)` when hero footstep sounds query custom tile codes 8–17 after map is up.
- **Stack:** `ObjectPublicEHciMaItciEHciEHUnique.Method_Private_EHeroSoundType_Int32_0` → native `ezc.bicr`.
- **Evidence extension never applies:** zero log lines like `extended hero biome lookup mappings` in probe runs.
- **Deobf discovery** (via `tools/_probe_config_id/Program.cs` on Golden Era `Hex.dll`):
  - Hero type: `ObjectPublicEHciMaItciEHciEHUnique`
  - Instance array: property `field_Private_Il2CppStructArray_1_EHeroSoundType_0` (`Il2CppStructArray<EHeroSoundType>`)
  - Golden Era names `ciwe`/`ciwc`/`ciws`/`ciwk` do **not** exist on deobf interop
- **Likely root cause:** native `bicr` indexes a different storage (possibly static on another type) than the instance property we extend; and/or `Il2CppStructArray` write-back via reflection fails silently (read-only generated property).
- **`PatchHeroBiomeController` is implemented but NOT registered** — `RegisterRequired()` calls `PatchHeroBiomeLookup` + `PatchHeroBiomeSelectors` only (line ~119); `PatchHeroBiomeController` (~line 245) is dead code. Wire it or remove if disproven.

**Recommended next steps:**
1. Static trace Golden Era `GameAssembly.dll`: `Method_Private_EHeroSoundType_Int32_0` → `bicr` → backing array field owner.
2. Register `PatchHeroBiomeController` from `RegisterRequired` if `ezh`/controller lifecycle still applies on deobf.
3. Extend arrays on the **actual** owner `bicr` reads; prefer typed `new Il2CppStructArray<EHeroSoundType>(n)` + field/property set, not `Activator.CreateInstance`.
4. Add one-shot diagnostic when lookup prefix sees `tileCode >= 8` and extension returns false (fail loud, not silent).
5. Re-probe; gate on zero `bicr` IOO and at least one `extended … mappings` log line.

### 2. Town / map billboard presentation (v4 slice, separate from load)

Probe logs show deobf map-object SID reads still weak:
- `HoMM3 custom town billboard: map object without readable custom city sid`
- PropCity route misses (`not-generic-city-object`, `no-objects-properties`)
- `GameMember stale-hints: map.customTownBillboard.rootGameObject on ObjectPublicObInbvByInSiLi1MaLiUnique`

Town scene/backdrop/layer diagnostics were in scope for v4 but not re-verified end-to-end after map-load fixes. See earlier v4 commits (`aeff72f0`, `4c1c89c6`) and port-smoke grep keys in `tools/official_deobf_port_smoke/README.md`.

### 3. Stale GameMember hints (noise, not blockers)

~26–28 `GameMember stale-hints` warnings per probe (ambient fog refresh, hero portrait binders, battle controls, etc.). Shape resolution succeeds; hints should be updated to deobf names when those surfaces are actively debugged.

---

## Key files changed this thread

| File | Role |
|------|------|
| `OfflineUnlockMod/DeobfInteropCompat.cs` | Config `id` via base-type string fields; map-object/city helpers for deobf |
| `OfflineUnlockMod/Homm3SwampAutumnTintProof.cs` | Hero biome prefix split, static/instance array accessors, `Il2CppStructArray` extend helpers |
| `OfflineUnlockMod/GameSymbols.cs` | `ConfigIdFields` field-first; deobf hero array symbol first in `HeroBiomeInstanceArrays` |
| `OfflineUnlockMod/Homm3CustomTownMapBillboard.cs` | `GetConfigElementId` for city SID |
| `OfflineUnlockMod/Homm3StrongholdDwellingMapBillboard.cs` | Reflective SID via `GetConfigElementId` |
| `OfflineUnlockMod/Homm3ImportBhSelectedUnitHudFix.cs` | Startup fix for action-bar surfaces (prior commit) |
| `AGENTS.md` | June 7 notes: ConfigElement id, hero biome deobf, HUD startup |

---

## Commits (this thread, newest first)

```
a9b14b63 Fix Golden Era map load after broken ConfigElement id and hero biome prefix regressions.
dfeef391 Document Golden Era action-bar shape-first HUD startup fix.
002a88bf Fix Golden Era selected-unit HUD startup on action-bar surfaces.
c6441380 Document Golden Era v4 presentation fixes in AGENTS notes.
aeff72f0 Fix Golden Era v4 presentation regressions across map, terrain, battle, and abilities.
```

Historical handoff state at that checkpoint: source was committed; only `bin`/`obj`/artifact noise was unstaged. This section is not a live `git status` snapshot.

---

## Continuation Results (2026-06-07, `18a426c5`)

- Built and deployed `OfflineUnlockMod.dll` from exact source commit `18a426c5`; deployed SHA256 is `3D5D4461E71F4F4BA1E36785D6D9D9F74B02E5F90F2144C223A589E9FB9254DB`.
- Computer Use launched `HeroesOldenEra.exe` from the isolated Golden Era install. Port-smoke auto-launch started Blitz and reached `scene='worldLight'`; the checked log had no `LogFatal`.
- Terrain remains unresolved: `ObjectPublicInbsTeInbsCoReVebsInUnique.Method_Private_Void_PDM_0` invoked after map build, but postconditions rejected it because `SoTerrainMaterial.terrainMaterial` stayed null. Do not record this method as a successful packed-material rebuild.
- Crash-safety follow-up: after a later runtime pass reported an unusually long map load followed by a crash, the generated zero-arg rebuild candidates were removed from `GameSymbols.TerrainMaterial.RendererRebuildMaterialArrays`. Keep only the historical semantic packed-material names until static tracing identifies the Golden Era rebuild method and runtime postconditions prove non-null packed material plus sufficient texture-array depth.
- Crash log follow-up: the next Golden Era run still crashed, but the crash moved to hero portrait identity caching. `ErrorLog.log` shows `AccessViolationException` under `Hex.Session.Logic.Hero.Method_Public_get_Hero_0()` called through `Homm3HeroPortraitHook.TryGetMemberValue` / `RememberHeroIdentityTree`. Golden Era's latest log reaches `BhHeroUIElement.Init(eta)` and replaces `HERO ICON`; Golden Era must use centralized backing fields (`_ciez_k__BackingField` / `<ciez>k__BackingField` / `ciez`) and must not walk generated `prop_Hero_*` properties.
- Load-time follow-up: after `eba3247c`, Golden Era no longer crashed but hit a 93.7s `worldLight` main-thread stall. The dominant difference from Golden was deployed asset payload drift, not `homm3_import.json` drift: all three import manifests had SHA256 `FAE336050E29144B4042955DFB4193CE66F7AF7CD9B1397C8D05CF2C2E89CAD8`, but Official had only 224 `homm3_bundles` files and 0 `.manifest` sidecars while Golden had 435 files and 211 `.manifest` sidecars. Official logs showed 167 `map_array.mat` missing fallbacks and 352 native-shell transplant lines; Golden showed none of those map-array-missing fallbacks. On 2026-06-07 18:35 -05:00, Golden Era `homm3_bundles` was synced from Golden Era excluding backup files and verified against Golden with 431 non-backup files, zero name/size mismatches, and aggregate SHA256 `9B36BFCEF4A2D3680BC773BF172512D193731E9F1FB28FB6377F5F156CE5278E`. Retest this payload before changing code for load time.
- Restart-crash follow-up: the post-sync restart crash is in `Homm3StrongholdDwellingMapBillboard`, not terrain or combat. `ErrorLog.log` shows `AccessViolationException` from `DescribeAvailableMembers` reading generated property `ObjectPublicHeObInObciSiObVeSeObUnique.get__ciez_k__BackingField()` after Official patched eight one-arg `Object1PublicObcjIncjUnique`/`fbx` methods as hire init hooks. Static interop comparison shows this Official `fbx` has no `ObjHire`/`ObjHireConfig` surface, unlike Golden `fbx`, so the fix is field-only diagnostics, field-first exact access, and skipping stale one-arg hero-wrapper hire hooks fail-closed. Do not restore the generated `ObjectPublicHeObInObciSiObVeSeObUnique` names to `GameSymbols.CustomDwellingHire.HireWorldObjectInit`.
- Terrain follow-up: assets are present. Official, Golden, and repo source contain the 27 `homm3_runtime_assets/custom_biomes` PNGs plus 3 swamp terrain-tint PNGs that runtime loads for custom biome material registration, all logged at `512x512`; relevant Core terrain JSON rows also match Golden except ordering-only `DB/biomes_info.json`. Black terrain remains because Official registers custom biome rows and renderer lookup (`8->7 ... 17->16`) but skips packed terrain material rebuild on `ObjectPublicInbsTeInbsCoReVebsInUnique` because no verified rebuild method hint matches. Next target is static tracing the Official rebuild equivalent of Golden `beg.nac`/`ivz`/`kwe`/`bbd` and validating non-null `SoTerrainMaterial.terrainMaterial` plus renderer texture-array depth through slot 16.
- Remaining map billboard/fog follow-up: after bundle sync, `map_array.mat missing=0` and slice-to-Hex/Lit runs for most units. Skeptical re-check found current logs can show `h3_gargoyle_upg_alt` / lab `h3_elemental_gargoyle` hydrating and attaching correctly, so do not document that SID as a permanent miss without fresh logs. The unsafe fallback is raw `OldenEra/Homm3/BillboardArray` material being transplanted onto the native shell after a failed first slice copy; that path now fails closed to the engine-driven donor shell instead of pretending it is Hex/Lit. Fog-visible custom billboards are separate: `homm3ReleaseMapSquadVisualController=false` means bridge/transplant draw paths never receive native squad visibility changes. Fix the Official controller remap separately; do not revive runtime attach/mirror/fog polling.
- Generic town route remains unresolved: `city-spawner` / `random-city` reaches `ObjectPublicMabvBoLibv1ObDi2InUnique`, but PropCity list/id/faction accessors are still unmapped.
- Combat donor-mesh follow-up: Official battle drawer `Object1PublicIncfUnIncfObBhIncfAnUnique` has the current visual field, but its placement/orientation fields moved to supplemental base `ObjectPublicGacfTrInGaTrcfBoBocfUnique` (`edg`): `field_Public_GameObject_0`, `_cfnw_k__BackingField`, `_cfnx_k__BackingField`, and `field_Protected_Transform_0`. These are now centralized in `GameSymbols.BattleVisual` / `Homm3BattleVisualInterop.ResolveDrawerSupplementalBaseType`; if custom battle prefabs still do not replace donors, inspect the new replacement log before widening fields.
- Hero portraits are split: `BhHeroUIElement.Init` resolves `homm3_stronghold_hero_13` and target `heroIcon`, but selected hero HUD `BhHeroHUDPanel` still logs `iconKey='?'` and no target image.
- June 8 code follow-up (not runtime-verified by Codex; user is testing): terrain no longer clears `SoTerrainMaterial.terrainMaterial` during generic biome registration, and unproven Golden Era generated zero-arg rebuild candidates, including `ObjectPublicInbsTeInbsCoReVebsInUnique.Method_Public_Void_PDM_0`, remain excluded until static proof plus runtime postconditions exist. If a historical semantic rebuild hint resolves and then fails postconditions, the previous cached terrain material is restored instead of leaving terrain null. Town billboard routing now includes stable Official `Hex.Map.ObjectsProperties` getters (`Method_Public_get_ObjectsProperties_0`, `Method_Public_get_List_1_PropCity_0`, `Method_Public_List_1_ObjectProp_EType_Int32_*`) and only accepts missing embedded PropCity ids from explicit `(ObjectProp.EType.MapObject, placedMapObjectId)` lookups. Dwelling pending-root pairing now uses placed-object property id / `DataObject.idMapObject` instead of the init node. Hero selected HUD now targets nested `BhTooltipHeroItemView.heroFace`, patches Official wrapper binds separately, keeps `SessionHeroWrapperHeroFields` field-only for identity traversal, and allows normal hero-config getters. Selected-unit action bar symbols now include Official `BhUnitControlsView` click-enable/hotkey methods plus Official ability manager/wrapper type names.
- Startup-smoke follow-up after that build: `artifacts/official_deobf_startup_probe_20260607-220347/` failed plugin load in the selected-unit HUD guard because old wrapper hint `elz` resolved to the wrong Official type before the explicit generated wrapper name was tried. `GameSymbols.SelectedUnitHud.AbilityManagerTypeNames` / `AbilityViewWrapperTypeNames` now list current Official generated names first. Follow-up probe `artifacts/official_deobf_startup_probe_20260607-220633/` reports `STARTUP_OK`, 0 plugin-load errors, 0 `LogFatal`, 0 `GameMember MISS`, auto-launch started Blitz, and map-load reached `loadingScene`.

---

## Build, deploy, verify

```bash
# Build Golden Era profile (required flag)
cd "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"
dotnet build -c Release -p:OfficialDeobfBuild=true \
  "-p:GameRoot=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era" \
  -clp:ErrorsOnly

# Deploy port-smoke + 120s auto-launch probe
cd "V:/Games/Olden Era Playtest Tweak"
DEPLOY=1 WAIT_SEC=120 bash tools/launch_official_deobf_startup_probe.sh
```

**Probe pass criteria (map load):**
- `STARTUP_OK`, `AUTO_LAUNCH_OK`
- No `get_id`, no `ciwk` `MissingFieldException`, no `TargetException` from static array on instance property
- `Homm3Import UnitViewHook: swapped` lines present
- `scene='worldLight'` in stall monitor

**Grep keys in** `artifacts/official_deobf_startup_probe_*/LogOutput.after.log`:
```bash
rg "get_id|MissingFieldException.*ciwk|TargetException|IndexOutOfRangeException|worldLight|UnitViewHook: swapped|extended hero biome" LogOutput.after.log
```

**Live game logs:**
- `BepInEx/LogOutput.log` under Golden Era install
- `C:\Users\<user>\AppData\LocalLow\Unfrozen\HeroesOldenEra\Player.log`

---

## Critical AGENTS.md warnings (do not regress)

1. **ConfigElement id:** Never call `ConfigElementBase<T>.id` on Golden Era. Use `DeobfInteropCompat.GetConfigElementId` only. Derived types may have their own `field_Public_String_0` for unrelated members.
2. **Hero biome lookup prefix:** Do **not** call full `EnsureBiomeSoundMappings` from lookup prefix — pulls ambient static `ciwk` and throws on deobf.
3. **Ambient static extension:** Use `TryExtendStaticArraySlot` (fail-soft), not throwing `ExtendStaticArraySlot`.
4. **Static vs instance arrays:** `TryExtendStaticArraySlot` must not use instance-property shape fallback (`GetValue(null)` → `TargetException`).
5. **Golden Era StreamingAssets:** `HeroesOldenEra_Data/StreamingAssets/Core.zip`, not `HeroesOE_Data`.
6. **Build gate:** Always `-p:OfficialDeobfBuild=true` for this install; compile success ≠ runtime port success.
7. **Deploy gate:** Do not use full `DeployPluginToGame=true` for Golden Era while repo `homm3_bundles` is stale. It overwrote 167 Golden-synced bundle files on 2026-06-07 and regressed map billboards; the install was restored from Golden and verified `Same=435 Diff=0` in `artifacts/official_deobf_bundle_restore_20260607-223109`.

---

## Helper tooling left in repo

- `tools/_probe_config_id/` — small .NET probe for Golden Era `Hex.dll` type/field discovery (hero sound type, etc.)
- `tools/launch_official_deobf_startup_probe.sh` — automated deploy + probe + report
- `tools/official_deobf_port_smoke/` — config, deploy/restore scripts, README

---

## Suggested priority for next agent

1. **Terrain packed-material rebuild** — statically trace `ObjectPublicInbsTeInbsCoReVebsInUnique` to find the real Golden Era path that creates a non-null `SoTerrainMaterial.terrainMaterial` and texture arrays deep enough for material slots `7..16`.
2. **Generic town PropCity** — trace `ObjectPublicMabvBoLibv1ObDi2InUnique` / native `ObjectsProperties` accessors for `city-spawner` and `random-city`; avoid broad property getter diagnostics.
3. **Selected hero HUD portrait** — map `BhHeroHUDPanel` payload/target image path separately from working `BhHeroUIElement.Init`.
4. **Map-array/fog gaps** — raw `map_array` transplant fallback is now blocked; next trace should focus on fresh slice-copy failures only when logs show `_MainTexArray*` still null, and remap/re-enable the map squad visual controller path so custom draw targets receive native fog visibility events.
5. **Lock GameMember hints** for surfaces being actively fixed (reduce stale-hint noise).

---

## User-facing status (one line)

Map load on Golden Era Blitz reaches `worldLight`; terrain packed-material rebuild, generic town PropCity routing, selected hero HUD portrait, and some map-array material hydration paths remain open.
