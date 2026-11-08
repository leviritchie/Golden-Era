# Town Unity Scene Replace Plan

Status: **Preferred paradigm** is documented in `docs/custom_town_scene_paradigm.md`. Factory owns `cityFactory` via Core/manifest `citySceneName` plus Castle-parity LoadScene/Move ownership. Failed playtest `city_hive` helpers remain forbidden. Phase 4 ownership, native building lifecycle, HotA world art on native slots, native building clicks, and town-hall construction menu open are **user-visible gameplay proven** on Golden Era (2026-07-23). Route A UI posters are not the destination. See `docs/factory_city_scene_runtime_pilot_breakage_catalog.md` for remaining edges.

Authoring later may still ship an AssetBundle; the current pilot loads authored `cityHuman2`, moves its live roots into a `CreateScene_Injected("cityFactory")` container, and never instantiates scene roots.

Proof labels follow `AGENTS.md`: source/static → generated artifact → build target → deployed/installed → startup smoke → runtime behavior → user-visible gameplay.

**Preferred paradigm (read first):** `docs/custom_town_scene_paradigm.md`
**Handoff (pick up cold):** `docs/town_unity_scene_replace_handoff.md`

Related evidence:

- Runtime ledgers: `docs/vanilla_town_scene_graph_ledger.md`, `docs/factory_town_scene_graph_ledger.md`, matching `artifacts/*/ledger.json`
- Static ownership map: `docs/town_scene_render_static_mapping.md` (historical Route A analysis; **not** the preferred product path)
- Overlay owner (legacy/comparison lane only): `Homm3StrongholdTownLayers.cs`
- Install build settings: `Assets/Scenes/City/cityHuman2.unity` et al. in Golden Era `globalgamemanagers`

## 1. Goal (locked)

**Abandon the donor Unity city scene** for custom factions (Factory first) by shipping a **Factory-owned Unity city world** that follows the **vanilla Castle contract**.

**Authoring choice:** Run the authored `cityHuman2` LoadScene lifecycle, move its vanilla-shaped graph into Factory ownership, then replace presentation without replacing native manager or click ownership.

**Load choice:** Additive `LoadScene("cityHuman2")` plus `MoveGameObjectToScene` into a runtime `CreateScene_Injected("cityFactory")` container. AssetBundle shipping is a later packaging option.

Success means the player’s town world is `cityFactory` (or equivalent Factory-owned scene), while native **CityUI** still works. Native click/hover stays on `BhBuilding` / `BhBuildingsManager` in the replacement world.

## 2. Rejected paths

| Rejected | Why |
| --- | --- |
| Hide donor meshes / keep `cityHuman2` | Still donor ownership |
| Refuse/skip without replacement world | Superseded by Castle-parity clone |
| Port failed playtest `city_hive` helpers / treat them as load-path evidence | Failed experiment; forbidden |
| CanvasCityPanel / town prefab UI as destination | Overlay/poster path |
| Alias Factory onto another live faction city (`cityDemon`, `cityHuman2`, …) | Cross-faction collision (vanilla Hive keeps `cityDemon`) |

## 3. What runtime dumps proved

Label: **runtime behavior proven** for early donor-ledger dumps (bridge `0.1.299`). Current Factory ownership and presentation proof is newer — see `docs/custom_town_scene_paradigm.md` and the breakage catalog.

| Fact | Vanilla (`human`) | Factory (preferred path) |
| --- | --- | --- |
| Active world scene | `cityHuman2` | **`cityFactory`** (LoadScene/Move ownership) |
| Overlay / Route A posters | off | **off** on owned world (skip poster path) |
| Manager / slots / buildings | active; 20 slots; 34 buildings | same Castle-parity graph in owned world |
| Building visuals | Castle meshes | HotA world art on native `BhBuilding` slots |
| City camera | FOV 47.6 | same contract |
| CityUI | separate ScreenSpaceCamera | same; hall open via HUD construction nav |

Interpretation: Factory owns a vanilla-shaped 3D city world. Overlay/poster lanes are legacy, not the destination.

## 4. How Olden Era chooses/loads city scenes today

### Fraction → scene name

1. Manifest `releaseScaffold.citySceneName` (Factory **`cityFactory`**).
2. `tools/release_port/apply_release_core_overlay.py` writes Core city `sceneName`.
3. Validators require scaffold ↔ city row match.

### Enum → Unity scene

Live `EScene` includes: `cityCore` (18), `cityUI` (19), `cityHuman2` (20), … `cityGnome` (26).

Install City `*.unity` list has faction cities + `cityCore` / `CityUI`. **`cityGnome` has no matching City `.unity` in `globalgamemanagers`.** Unknown Core names historically fail `Enum.Parse`.

### World contents

Faction city world holds manager, slots, buildings, cameras. CityUI is separate.

## 5. Why overlay is not the destination

`Homm3StrongholdTownLayers` is UGUI under `CanvasCityPanel`. It does not unload Castle’s city world or register a Factory city scene. Prefer the owned-world paradigm in `docs/custom_town_scene_paradigm.md`: HotA art on native `BhBuilding`s, CityUI kept native, hall open via HUD `BuildingsConstruction` select, and visually gated peer-panel close.

## 6. Phases (active)

### Phase 0 — Docs / contract freeze

This plan + handoff: Castle-parity clone; Hive forbidden; refuse/skip superseded.

### Phase 1 — Decomp pin load/session owners

Pin sceneName → EScene → Unity load and session `cft(EScene, Scene)` registration for Golden Era before coding hooks.

### Phase 2 - Castle-parity `cityFactory` world (LoadScene/Move ownership)

Authored `cityHuman2` is loaded additively so its Unity lifecycle runs, then its live roots are moved into `cityFactory`. No root is instantiated. This preserves real `BhBuildingsManager`, `BhBuilding`, camera, collider, and event ownership.

### Phase 3 — From-scratch Factory registrar

Landed in `Homm3FactoryCitySceneRegistrar.cs`. The registrar pins ordinal 26 to `cityFactory`, loads the donor additively, moves its roots, unloads the empty donor scene, binds Di2, and allows native `Void(EScene)`. It does not alias a live faction city.

### Phase 4 — Runtime pilot

Pass recorded 2026-07-22 (ownership): active world `cityFactory`; manager/slots/buildings gated after move; CityCamera present; CityUI; Route A skip; Castle world user-visible after `CityCamera`+`Lights` activate. Catalog: `docs/factory_city_scene_runtime_pilot_breakage_catalog.md`.

Pass: active world `cityFactory`; manager/slots/camera; CityUI; no silent `cityHuman2` restore; no Hive.

### Phase 5 — Replace Castle art with Factory art

**Current preferred implementation (user-visible proven for Factory hall/clicks/art path):** every active supported manager-owned slot is joined through an explicit native-to-Factory level map and rendered as world art on native buildings. Lower cumulative variants are hidden; colliders stay native-owned. No force activation, click relay, or manufactured collider. Town-hall Main opens construction via HUD navigation (`TryOpenOwnedCityHallConstructionMenu`); peer upgrade close is gated with `IsReleaseTownPanelVisuallyOpen`.

World Factory backdrop frames the town; CityCamera clearFlags stay native (no SolidColor-black Route A workaround). Conflux completeness and some construct-refresh edges may still need focused proof — those gaps do not revive Route A as destination.

## 7. Hard unknowns (narrowing)

1. Exact live parse/load/session hooks — Phase 1.
2. Scene AssetBundle additive load proof — Phase 2–4.
3. `cityGnome` unused gate — Phase 3.
4. Post-load breakage catalog (clicks, construct, music) — Phase 4.

## 8. Smallest gated pilot

Ship Castle-parity `cityFactory` world + from-scratch registrar; prove Factory town active world ≠ `cityHuman2`.

### Pass

1. Active town world scene name is `cityFactory` (logged).
2. Manager + 20 slot names + camera present in that scene.
3. CityUI interactive; breakage catalog written for remaining gaps.
4. No Hive code path; no alias to live faction cities.

### Fail

- Mesh-hide or poster scored as pass.
- Silent restore of `cityHuman2`.
- Playtest `city_hive` helper revival or aliasing onto vanilla Hive `cityDemon`.
- Wrong faction gated.
- Crash without diagnostic.

## 9. What NOT to do

- Do not port `_decompiled_shipped` playtest `city_hive` helpers, and do not cite them as how custom cities load.
- Do not implement hide-donor or refuse/skip as the product pilot.
- Do not expand `homm3_town_prefabs` as world geometry.
- Do not invent a second building click system before measuring native ownership in `cityFactory`.

## Assumptions and short logical proof

Assumption: A vanilla-shaped Factory town must be a Unity city world with Castle’s manager/slot/building/camera contract, loaded through the city session path that authored faction cities use.

Proof: Ledgers show that contract lives in `cityHuman2` today; install lists real City `*.unity` assets; unknown `sceneName` fails enum parse — therefore Factory needs its own scene name and a registrar that owns Di2/session binding without aliasing onto another live faction city.
