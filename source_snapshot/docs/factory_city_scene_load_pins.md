# Factory City Scene — Load Path Pins (Golden Era)

Proof labels (keep separate):

- **Load / Di2 / EScene pins in this doc:** source/static (live `BepInEx/interop/Hex.dll` reflection against Golden Era install).
- **Owned town presentation for Factory:** user-visible gameplay proven for `cityFactory` world art, native `BhBuilding` clicks, and hall construction open (2026-07-23). See `docs/custom_town_scene_paradigm.md`.
- **Bulwark and other peers on the shared owned-world registrar:** wired onto the same `cityFactory` compositor path; not Bulwark-specific user-visible proven from this pin sheet alone.
- **Still unproven:** authored `cityFactory.unity`, Conflux completeness, some construct-refresh edges, Split Assembly combat apply, Bulwark Runes battle hooks.

Date: 2026-07-21 (pins); presentation proof updated 2026-07-23. Install: `Heroes of Might and Magic Olden Era - Golden Era`.

## Agent warning — do not learn load path from the old playtest `city_hive` experiment

**Vanilla Hive** (OE faction `demon`, city world `cityDemon`, etc.) is a normal shipped faction. It is not this experiment.

The **old OfflineUnlockMod playtest helpers** under `_decompiled_shipped` (`TryAliasHiveCityScene`, `city_hive` string alias, aliasing onto another faction’s `EScene` / city scene, `RegisterHiveCitySceneForSession`) were a **failed custom-town experiment**. They are incomplete, not a template, and not evidence of how custom factions should own a city world.

**Forbidden for agents:**
- Citing that playtest code as “the proven custom city load path.”
- Porting or reviving those helpers into live Factory work.
- Treating “Hive” in town-scene docs as shorthand for that failed alias path — say **playtest `city_hive` helpers** when you mean that, and **vanilla Hive / `cityDemon`** when you mean the shipped faction.
- Aliasing Factory (or any custom faction) onto a live faction city scene such as `cityDemon` or `cityHuman2`.

Derive load ownership from **vanilla Castle `cityHuman2` contract + live Di2/session pins + current runtime logs**, not from `_decompiled_shipped`.

## Goal verb

Load a Factory-owned Unity city world (`cityFactory`) through the same session city path vanilla uses for authored faction cities (e.g. `cityHuman2`).

Preferred end-to-end presentation/interaction rules (world art, native clicks, hall construction open, visually gated peer-panel close): `docs/custom_town_scene_paradigm.md`.

## Pins

| Role | Live type / member | Notes |
| --- | --- | --- |
| City row scene string | `Hex.Configs.ObjCityConfig.get_sceneName` / `set_sceneName` | Property over field `sceneName`. Do not Harmony-rewrite (IL2CPP field accessor; live-negative). |
| String → `EScene` | `ObjectPublicAbstractSealedihESaStjlhxESaStBoUnique.Method_Public_Static_EScene_String_0` (+ PDM_0/1/2 duplicates) | Fail-closed parse; unknown names throw historically (`cityHuman` proof). |
| Session scene entry | `ObjectPublicESScbwBoLibw1GacnESUnique` | Ctor `(EScene, Scene)`. Fields: `prop_EScene_0` / `_bwnh_k__BackingField`, `field_Private_Scene_0`. DiffableCs name `cft` is stale for this build. |
| Session all-scenes callback | `Hex.Session.Loader.Method_Protected_Virtual_Void_Il2CppReferenceArray_1_ObjectPublicESScbwBoLibw1GacnESUnique_0` | Live replacement for historical `Loader.lla`. Secondary to Di2 bind at town open. |
| Enum | `Hex.GameScenes.EScene` | Spare city slot ordinal **26** (historically named `cityGnome`). Frozen Golden Era pin renames that field to **`cityFactory`** in `global-metadata.dat` via `tools/pin_escene_city_factory.py` (same ordinal; no new enum member). No matching City `.unity` in `globalgamemanagers` — runtime `CreateScene("cityFactory")` still required for a named empty scene. |

## Related (not primary Factory hook)

Loaders for MainMenu / Pick / StoryHub / MapEditor / CustomBattle also accept the same entry array shape. Central helpers `ObjectPublicDi2ESObbwUnique` take entry arrays + `EScene[]`.

## Install scene assets

Faction worlds under `Assets/Scenes/City/`: `cityHuman2`, `cityDemon` (vanilla Hive), `cityDungeon`, `cityNature`, `cityUnfrozen2`, `CityUndead2`, `cityCore`, plus legacy `cityHuman` / `cityUnfrozen` / `CityUndead`. UI: `Assets/Scenes/UI/CityUI.unity`.

## Forbidden

- Porting `_decompiled_shipped` playtest `city_hive` helpers (`TryAliasHiveCityScene`, `RegisterHiveCitySceneForSession`, aliasing onto `cityDemon` / other live cities).
- Aliasing Factory onto any live faction city that still has a built-in `.unity`.
- Scoring Route A posters / donor-renderer suppress as Factory world ownership.

## Current load pilot (vanilla load lifecycle alignment)

Vanilla authored cities: `LoadScene` of a City `*.unity` → Di2/session entry → `Void(EScene)` activates that Scene.

Factory has no authored `cityFactory.unity` yet. Pilot alignment:

1. **Primary:** Core/manifest `citySceneName=cityFactory`. Live-negative: Harmony on `ObjCityConfig.get_sceneName` does not rewrite native reads.
2. Frozen install pins `EScene` ordinal 26 field name to `cityFactory`.
3. On Factory open: **additive `LoadScene(cityHuman2)`** (authored content lifecycle), **`MoveGameObjectToScene`** those roots into a `CreateScene_Injected("cityFactory")` container, unload empty donor, upsert Di2 dictionary, **allow native Void**.
   - **Forbidden:** `Object.Instantiate` of city roots (live-negative: Di2/Void/Route A could “succeed” while world stayed black).
   - `CreateScene` is only the Factory-owned **container** until an authored `cityFactory.unity` ships.
   - **Live-positive presentation gap:** after Void, `CityCamera` and `Lights` stayed `activeSelf=false` while terrain/buildings were active → black view. Probe `SetActive` on those roots restored Castle 3D. Production must call `EnsureOwnedCityPresentationActive` after own + after Void (required roots in `RequiredPresentationRootNames`).
4. When Factory owns `cityFactory`, disable Route A poster path (backdrop / donor suppress / SolidColor-black CityCamera). Prefer world HotA art on native `BhBuilding` slots per `docs/custom_town_scene_paradigm.md`.
5. Remaining gap vs full vanilla: no authored `cityFactory.unity` in build settings — container is synthetic; content must still come from a LoadScene’d authored city.

Enable with `homm3FactoryCitySceneReplace: true` while Core/manifest owns `cityFactory`. Factory presentation (world art, native clicks, hall construction) is user-visible proven per `docs/custom_town_scene_paradigm.md`. Load/Di2 pins above remain source/static evidence for the ownership path.

Phase 4 ownership catalog: `docs/factory_city_scene_runtime_pilot_breakage_catalog.md`.
