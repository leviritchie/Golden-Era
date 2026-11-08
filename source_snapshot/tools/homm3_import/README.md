# HoMM3 import lane (B) — segregated from esquire

This folder is **lane B**: new creatures and experiments. **Lane A** (esquire / pikeman) stays in [`../custom_prefab_pipeline/`](../custom_prefab_pipeline/) and must not depend on this tree.

## Layout

| Path | Role |
|------|------|
| [`units_inventory.json`](units_inventory.json) | Python extract inputs (LOD entry or loose `.def`, output basenames, optional JSON path rewrite). |
| [`extract_creature.py`](extract_creature.py) | `lod_extract` → `defextract_py3` → `Assets/CustomUnits/homm3_lab/<unitSid>/extracted_*`. |
| [`fix_defextract_json_paths.py`](fix_defextract_json_paths.py) | Rewrites `something.dir/` prefixes in defextract JSON (like the pikeman `fix_avwpike_json_paths.py`). |
| [`audit_unit_animation_frames.py`](audit_unit_animation_frames.py) | Checks battle DEF group coverage, attack-family selection, and stock attack-variant override mappings. |
| [`stage_homm3_unit_audio.py`](stage_homm3_unit_audio.py) | Copies HoMM3 `Heroes3.snd` creature WAVs into `homm3_lab/<unitSid>/sounds/` as `HOMM3_<unitSid>_*.wav` (needs `sndBattlePrefix` in `units_inventory.json`). |
| [`unity_editor/Homm3BattleSoundPrefabsBuild.cs`](unity_editor/Homm3BattleSoundPrefabsBuild.cs) | One `AudioSource` prefab per staged WAV (same idea as lane A `EsquireBattleSoundPrefabsBuild`). Run from `build_homm3_units` after staging. |
| [`unity_editor/Homm3BillboardAnimatorBuild.cs`](unity_editor/Homm3BillboardAnimatorBuild.cs) | Fork of esquire billboard builder; reads **`authoring.json`** (`-homm3UnitSid` or `-homm3AuthoringPath`). **Do not edit** `EsquireBillboardAnimatorBuild.cs` for lane B. |
| [`homm3_units_manifest.json`](homm3_units_manifest.json) | `BuildCustomUnitBundles` input (lane B bundles only). |
| [`build_homm3_units.cmd`](build_homm3_units.cmd) / [`.sh`](build_homm3_units.sh) | xcopy scripts → **SND stage** → `Homm3BattleSoundPrefabsBuild` → Unity batch animator → bundle build. |
| [`build_out/`](build_out/) | Generated bundles (copy to `BepInEx/plugins/OfflineUnlockMod/homm3_bundles/`). |
| [`example_authoring/sample_creature_authoring.json`](example_authoring/sample_creature_authoring.json) | Template for Unity `homm3_lab/<unit>/authoring.json`. |
| [`bootstrap_homm3_lab.py`](bootstrap_homm3_lab.py) | **Non-interactive scaffold:** copy esquire `battle.prefab` / `map.prefab` / `battle_billboard_mesh.mat` / `Reference/StockEsquireBattle.controller` into `homm3_lab/<unit>/` (assets only, never their `.meta`: Unity assigns fresh GUIDs) and install `presets/<unit>/authoring.json`. |
| [`verify_homm3_build.py`](verify_homm3_build.py) | Assert `build_out/<bundleName>` exists; optional `--emit-bundle-path` for deploy scripts. |
| [`run_e2e_until_game.cmd`](run_e2e_until_game.cmd) | **One-shot automation:** extract → bootstrap → `build_homm3_units` → verify; optional 2nd arg = mod folder for bundle + `homm3_import.json`. |

## Non-interactive e2e (everything except launching the game)

**Goal:** one command produces a verified `build_out/custom_units_*` artifact (and optionally stages it beside the mod DLL).

**Prerequisite:** the Unity project must contain **`Assets/CustomUnits/esquire/`** (same lab as lane A). `bootstrap_homm3_lab.py` copies that scaffold so no manual prefab creation is required for CI. *Future improvement:* vendor a minimal prefab triple in-repo so esquire is not required on the build agent.

From this directory (or repo root with adjusted paths):

```bat
set OLDENERA_UNITY_PROJECT=C:\path\to\oldenera_factions
run_e2e_until_game.cmd temple_griffon
```

Optional deploy (copies bundle + `presets\<unitSid>\homm3_import.json`):

```bat
run_e2e_until_game.cmd temple_griffon "D:\game\BepInEx\plugins\OfflineUnlockMod"
```

Still manual before play: install/update **`OfflineUnlockMod.dll`** and set **`homm3ImportEnabled`** / **`homm3ImportApplyHarmony`** in `config.json`.

## Workflow

1. **Inventory** — Add a row to `units_inventory.json` (`unitSid`, `battleLod` + `battleLodEntry` or `battleDefPath`, optional `mapDefPath`, optional **`sndBattlePrefix`** for battle SFX staging, `jsonPathRewrite` if defextract dir name ≠ basename).
2. **Extract** - `build_homm3_units.cmd <unitSid>` extracts by default. Set `SKIP_EXTRACT=1` only when intentionally reusing cached `extracted_battle` frames. `HOM3_EXTRACT=0` is the lower-level compatibility switch.
   `py -3 tools/homm3_import/extract_creature.py --unit <unitSid> --unity-project <oldenera_factions>`.
3. **Unity authoring (manual path)** — Skip if you use **`bootstrap_homm3_lab.py`** + **`presets/<unitSid>/authoring.json`**. Otherwise under `Assets/CustomUnits/homm3_lab/<unitSid>/`:
   - Copy [`example_authoring/sample_creature_authoring.json`](example_authoring/sample_creature_authoring.json) to `authoring.json` and fix paths.
   - Add `battle_billboard_mesh.mat`, `battle.prefab`, `map.prefab`, **`Reference/StockBattle.controller`** (AssetRipper / AssetStudio — see [`../custom_prefab_pipeline/unity_editor/StockEsquireBattle_IMPORT.txt`](../custom_prefab_pipeline/unity_editor/StockEsquireBattle_IMPORT.txt)).
4. **Manifest** — Add a `units[]` entry to `homm3_units_manifest.json` (`meshKey` / `mapMeshKey` must match `homm3_import.json` Res paths you will drive in-game).
5. **Build** — `build_homm3_units.cmd <unitSid>` runs **SND staging** (if `Heroes3.snd` is present), **`Homm3BattleSoundPrefabsBuild`**, animator rebuild, then `BuildCustomUnitBundles` (Unity `6000.0.66f2`, project from `OLDENERA_UNITY_PROJECT` or `../../oldenera_factions`).
6. **Runtime (optional)** — Copy `build_out/custom_units_<unitSid>` to `BepInEx/plugins/OfflineUnlockMod/homm3_bundles/`. Copy [`homm3_import.example.json`](homm3_import.example.json) or [`presets/temple_griffon/homm3_import.json`](presets/temple_griffon/homm3_import.json) beside the mod DLL as `homm3_import.json`. Optional JSON field **`audioStemPrefix`** overrides the default `HOMM3_<folder-from-battlePrefabAssetPath>_` stem used for battle SFX. Optional per-entry **`gameUnitSids`** lists extra in-game unit config SIDs (e.g. `h3_goblin`) whose **tooltip portrait** should reuse that entry’s HoMM3 battle prefab texture. Battle swaps may use synthetic **`battleResPath`** values under `units/homm3_import/...`, with **`battlePresentationResPath`** pointing at a real vanilla donor for layer data. Map swaps should keep **`mapResPath`** on the real vanilla map donor so `UnitViewConfig.rtd()` enters the native fog-of-war lifecycle; **`mapShellResPath`** is available only as a fallback shell hint. In `config.json`: `homm3ImportEnabled` and `homm3ImportApplyHarmony` enable **UI spawner**, **`dzk.bath` battle pool**, and **`UnitViewConfig.rtd` adventure map** swaps for every entry in that table. Battle audio uses the same **clip-driven** path as Esquire (`Homm3LabBattleAudioPlayer` + `Homm3LabClipAudioDriver`); volume follows **`esquireBattleSfxVolume`** in mod config.

**Battle SFX stem contract:** `audioStemPrefix` must match the `homm3_lab` folder used by `battlePrefabAssetPath`, because `stage_homm3_unit_audio.py` and `Homm3BattleSoundPrefabsBuild` emit `HOMM3_<labSid>_*` clips. Do not include the custom faction in this prefix: `Assets/CustomUnits/homm3_lab/h3_beholder/battle.prefab` uses `HOMM3_h3_beholder_`, not `HOMM3_dungeon_h3_beholder_`.

## HotA Factory / Bulwark / neutrals (source-prep lane)

Prepare inventory/manifest rows from local HotA zips (no Core/deploy):

```bat
python tools/homm3_import/prepare_hota_factory_bulwark_neutral_bundles.py --faction all
python tools/homm3_import/prepare_hota_factory_bulwark_neutral_bundles.py --faction all --extract-bootstrap --unity-project oldenera_factions
```

Multi-option alt-upgrade **sprite-edit** galleries (unlocked until user picks).
These use battle standing frames (group 2) with material-class remaps + pixel accents —
not portrait icons and not a global hue filter. Open `recolor_galleries/index.html`.

```bat
python tools/homm3_import/generate_hota_alt_recolor_gallery.py --faction all
```

Outputs live under [`recolor_galleries/`](recolor_galleries/). Validate with:

```bat
python tools/validate_hota_factory_bulwark_neutral_asset_contract.py
```

Neutral pool registry: `tools/homm3_import/faction_concepts/homm3_hota_neutral_pool.json`.

## Battle sprite framing

HoMM3 creature DEF extracts in this lane use a 450x400 battle canvas. Keep the authored battle quad at `battleQuadLocalScaleX=13.5`, `battleQuadLocalScaleY=12.0`, `battleQuadLocalPositionX=0.75`, `battleQuadLocalPositionY=2.01`, and `battleQuadLocalPositionExtraY=0.0`. This preserves the 450:400 source aspect ratio while keeping the existing vertical size and aligning the shared HoMM3 foot line around source y=267 to the prefab root.

Run [`normalize_battle_quad_authoring.py`](normalize_battle_quad_authoring.py) after adding or regenerating presets. Do not leave the older square `12x12` quad in new custom-faction presets; it horizontally squeezes battle sprites and makes Tower/Stronghold-style units read as misaligned even when the DEF frame margins are correct.

## Battle sprite source accuracy

Run [`audit_unit_sprite_sources.py`](audit_unit_sprite_sources.py) before rebuilding or deploying custom-faction bundles when a unit visually looks like the wrong creature. It compares `units_inventory.json` against both `presets/<unitSid>/authoring.json` and the Unity project copy in `oldenera_factions/Assets/CustomUnits/homm3_lab/<unitSid>/authoring.json`.

Do not trust stale `tools/build_temp_homm3/*` folders as source-of-truth evidence. For Stronghold, `h3_wolf_rider` must use `CBWLFR` and `h3_wolf_raider` must use `CUWLFR`; swapping those produces the exact class of battle-sprite mismatch where the unit is framed correctly but belongs to the wrong creature.

## Battle animation - RIFE v4 at 60 FPS (production wrappers)

Production wrappers use RIFE v4.6 with `HOMM3_TARGET_FPS=60` by default. The interpolation script honors an explicit target FPS; legacy `.rife120_done.json` names and older 120 FPS batch comments are compatibility identifiers, not the current default.

**Setup (once, on V:):**

```bash
bash tools/homm3_import/setup_vfi_env.sh
```

**Full array timing rebake (no RIFE, all manifest units)** — after Griffin/Pikeman looked correct:

```bat
tools\homm3_import\run_homm3_array_timing_rebundle_all.cmd
```

Uses `run_homm3_rife_production.cmd` with `SKIP_RIFE=1`, mirror, one animator rebuild, and batched bundle builds. The final ordinary `dotnet build` deploys plugin/source assets but intentionally does not copy `build_out\custom_units_*`; bundle deployment requires explicit `DeployHomm3Bundles=true` after payload validation.

If Phase 3 already finished, run bundles only:

```bat
set SKIP_ANIM=1
tools\homm3_import\run_homm3_array_timing_bundle_batches.cmd
```

**Fast array timing rebake (no RIFE, two units)** — when `extracted_battle` already has 60fps frames but timing clips/manifests are still 120fps:

```bat
tools\homm3_import\build_homm3_array_timing_test.cmd
tools\homm3_import\build_and_deploy_homm3_griffin_pikeman_timing.cmd
```

Uses one `RebuildAllFromManifest` + one filtered `BuildCustomUnitBundles` for `h3_griffin` / `h3_pikeman` only. Set `SKIP_MIRROR=0` if Unity lab PNGs are stale; `SKIP_BUNDLE=1` to skip bundle output (manifest/lab only).

**Single unit** (also wired into `build_homm3_units.cmd` unless `SKIP_RIFE=1`):

```bat
py -3 tools/homm3_import/interpolate_homm3_battle_sequences.py --units h3_angel
```

**All lab units** (resumable via the legacy-named `extracted_battle/.rife120_done.json`; target FPS comes from the current script/default):

```bat
tools\homm3_import\interpolate_homm3_battle_all.cmd
```

- Backs up the first run to `extracted_battle_source_12fps/`.
- Composites RGBA → opaque gray RGB before RIFE; restores alpha after inference (never feed RGBA to Vulkan RIFE).
- Sets `flipBookFps` / `deathClipFps` to the selected target FPS (production default 60) in the unit `authoring.json`.
- Bulk preset FPS: `py -3 tools/homm3_import/set_homm3_battle_flipbook_fps.py`
- WebM comparison gallery (not used in-game): `build_animation_ai_interpolation_comparison.py`

## Battle animation frame accuracy

Run [`audit_unit_animation_frames.py`](audit_unit_animation_frames.py) before deploying rebuilt HoMM3 unit bundles:

```bat
python tools/homm3_import/audit_unit_animation_frames.py --unit h3_orc --unit h3_wood_elf
```

The audit catches three common failure classes: missing Unity lab authoring for a unit that still has a stale bundle, DEF group coverage problems, and `AnimatorOverrideController` mappings where stock attack variants (`15.Skill_1` through `19.Skill_5`) point to `21.Death`. Do not classify death clips with a raw `kill` substring; `Skill_*` contains `kill`, which made Orc/Nereid-style attacks play falling/death frames.

Default attack-family selection is source-driven. If a battle DEF has shooter groups `14/15/16`, the generated `14.Attack` clip and `Homm3BattleDiskTextureRemap` prefer those groups; melee groups are `11/12/13`. Converted HotA/ToA JSON animations can lack movement group `0` while still having valid group `1`, idle, attack, hit, and death frames. Keep the importer movement fallback (`0 -> 1 -> idle`) instead of falling back to flat-folder slices.

Shooter units that also have melee groups must keep a separate melee alternative clip. `14.Attack` should use shooter groups for the default ranged attack, but `15.Skill_1` should use melee groups so release-port `animationIndex=1` melee alternatives do not visually shoot at adjacent targets. The audit fails shooter units with melee DEF groups when the generated `15.Skill_1` clip is missing or mapped to the wrong override.

Cove Nymph/Oceanid/Nereid are a special teleport movement case. Their source animation uses group `20` for leaving/submerge and group `21` for arriving/surface; the generated `01.Walk` clip must be built from `20+21`, and the runtime disk remap must use the same order. The stock controller drives these units through `10.Tp_Start`, `11.Tp_End`, `12.Tp_Ability_Start`, and `13.Tp_Ability_End`; start clips must override to generated group `20` clips, and end clips must override to generated group `21` clips. Binding every teleport clip to full `01.Walk` makes the unit dive again on the destination tile. The audit fails those units when `01.Walk` still points at the ordinary group `1` fallback, when single-phase teleport clips are missing, or when the teleport controller clips bind to the wrong phase.

## Adventure map: Hex/Lit vs Sprites/Default

`authoring.json` sets **`templateMaterialPath`** (battle quad; often `Sprites/Default`). For **`esquirePikemanMapBillboardMaterialMode`: `hexLitVanilla`**, the mod reclones the **vanilla unit’s** `Hex/Lit` map material at runtime. To avoid a Sprites→Hex rebake mismatch and make Unity-authored map frames match fog early:

1. Export a stock map material from the game (e.g. **`esquire_map`** mesh slot `Esquire_mat`) via AssetStudio / AssetRipper into your Unity project.
2. Duplicate it to e.g. `map_hexlit_billboard_template.mat`, assign **`Hex/Lit`**, remove secondary maps / skinned-only keywords in the Inspector (single quad = only `_MainTex` + fog).
3. Set **`mapTemplateMaterialPath`** in `authoring.json` to that asset; rebuild map materials with **`Homm3BillboardAnimatorBuild.RebuildMapMeshBillboard`** / full batch.

Then keep **`hexLitVanilla`** in mod `config.json`. Runtime donor rebind still harmonizes fog uniforms with the live vanilla prefab; baked templates reduce black/corruption from fighting `Sprites/Default` defaults.

## Reference docs (shared rules)

- Rendering / DEF groups: [`../custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md`](../custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md)  
- Esquire batch (lane A): [`../custom_prefab_pipeline/BUILD.md`](../custom_prefab_pipeline/BUILD.md)  
- Pikeman LOD example: [`../unity_exports/pikeman/README.md`](../unity_exports/pikeman/README.md)

## `OfflineUnlockMod` integration

- Config keys: `homm3ImportEnabled`, `homm3ImportApplyHarmony` (defaults `false`).  
- Code: `Homm3ImportVisuals.cs`, `Homm3ImportNarrowSpawnerHook.cs`, `Homm3ImportBattlePoolHook.cs`, `Homm3ImportUnitViewHook.cs`, `Homm3LabBattleAudioPlayer.cs`, `Homm3LabClipAudioDriver.cs`.  
- Esquire code paths are unchanged.
