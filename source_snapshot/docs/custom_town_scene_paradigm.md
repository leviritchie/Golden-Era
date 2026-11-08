# Custom Town Scene Paradigm (Preferred)

Status: **preferred product path** for HoMM3 custom faction towns.
Proof: Factory `cityFactory` ownership, HotA world art, native building clicks, and town-hall construction menu open are **user-visible gameplay proven** on Golden Era (2026-07-23). Conflux completeness and some construct-refresh edges may still need focused proof; do not treat those gaps as permission to revive Route A as the destination.

Related contracts: `tools/validate_factory_city_scene_contract.py`, `docs/factory_city_scene_load_pins.md`, `docs/town_unity_scene_replace_plan.md`.

## Preferred paradigm (one sentence)

Own a vanilla-shaped Unity **city world** (`cityFactory` or a later authored faction city), paint HotA art onto native `BhBuilding` slots in that world, keep CityUI native, and open construction through HUD navigation — not through UI posters, click relays, or “under the cursor” timing hacks.

## What to ship

| Layer | Owner | Rule |
| --- | --- | --- |
| Town world scene | `Homm3FactoryCitySceneRegistrar` (LoadScene donor → Move into owned scene → Di2/`Void`) | Active world name is the custom scene (`cityFactory`), not silent `cityHuman2`. |
| Building interaction | Native `BhBuilding` / `BhBuildingsManager` + PhysicsRaycaster | No second click system; no `Homm3TownLayerClickRelay` as product. Full-3D towns pick by the drawn meshes, and scenery occludes picks without becoming a pointer target (`Homm3TownScene3dPick`, docs/homm3_conflux_full_3d_town.md "Building picking"). |
| Building visuals | `Homm3FactoryCityWorldVisuals` (world quads on native slots) | Art follows native activation; do not force-activate unbound slots or reintroduce `bajs` load storms. Optional Meshy town-scene mesh lane (`homm3TownSceneMeshes`) exists but is off by default — not the product path until materials/backdrop strategy is settled. |
| CityUI menus | Native CityUI canvases (`BUILDING VIEW PANEL`, hire, upgrade, …) | Keep HUD; do not replace menus with Route A posters. |
| Town-hall construction open | `TryOpenOwnedCityHallConstructionMenu` → `BhNavigationView` `BuildingsConstruction` select | Skip native Main `Visit` when it diverges; match the working HUD build-tab path. |
| Peer-panel close before open | `CloseReleaseCityHireAndUpgradeSubwindows` / upgrade close | Close only panels that are **visually open** (`IsReleaseTownPanelVisuallyOpen`: Canvas.enabled + CanvasGroup). Hierarchy-active alone is not open. |
| Route A panel lift | `ShouldSkipRouteATownPanelLift` | Skip continuous sortingOrder lift on owned world towns; HotA world art is not competing on `CanvasCityPanel`. |
| Town music | `Homm3StrongholdCityMusic` + Core `DB/city_music_sounds.json` | When `<faction>_city_music` exists, Core must use `sounds/city/music/<faction_sid>` (Stronghold pattern), not a vanilla donor set — otherwise native donor BGM layers under the sidecar. Contract: `tools/validate_homm3_city_music_sidecar_contract.py`. |

## Rejected destinations

Do not treat these as the product end state for new custom towns:

- Route A / Route C: `CanvasCityPanel` posters, donor-renderer suppress, SolidColor-black CityCamera workarounds as the town world.
- Playtest `city_hive` helpers / aliasing onto another live faction city (`cityDemon`, etc.).
- UI click relays that forward world clicks into RawImage town layers.
- Deferred LateUpdate / next-frame hall opens assumed to fix “open then close” (live-negative; real close was upgrade `OnEscapeClick` on a visually closed panel).
- Constructed-variant activation via manager `bajs`/`BuildingMutationMethodName` invoke every presentation pass (live-negative black screen / load storm).

Route A remains a **comparison / legacy** lane for factions not yet on owned city worlds. It is not the preferred paradigm.

## CityUI closed-panel rule (live-positive)

CityUI primary panels often stay `activeInHierarchy` while closed by disabling `Canvas` and/or zeroing `CanvasGroup`. Calling native exit/escape on a visually closed `UPGRADE UNIT PANEL` still runs navigation `OnDeselect` → `Hide(BuildingsConstruction)` and tears down the hall menu that just opened.

**Assumption:** “Active in hierarchy” means “exists in the city UI stack,” not “user-visible.”
**Proof:** Idle `UPGRADE UNIT PANEL` had `activeInHierarchy=true`, `Canvas.enabled=false`, `alpha=0`; hall open then logged `ScUpgradeUnits.OnEscapeClick` → `BhNavigationView.Hide(BuildingsConstruction)` → `BhUIBuildingSession.OnHide`. Gating close on visual open fixed hall open (user-confirmed).

## New faction checklist (town)

1. Manifest / Core `citySceneName` owns a dedicated world name (Factory pattern: `cityFactory`).
2. Enable owned-world replace flag for that lane (`homm3FactoryCitySceneReplace` or successor).
3. Map HotA layers to Castle-parity native slots (`nativeLevels`); fail closed on missing joins. The Core city row's `sceneSlot` strings must be the **cityHuman2** ones (`Main`, `Tavern`, `Walls`, …), whatever donor city the row was cloned from: native `BhBuildingsManager` finds a building's slot by that string, and a donor string (nature_city `Build_Main`, demon `Wall`) binds nothing — the hall never activates and the owned presentation waits forever with Castle donor art showing (Conflux, 2026-09-26). The overlay's `align_owned_world_city_scene_slots` rewrites them; `validate_custom_faction_manifests.py --core` checks them against Core's `human_city.json`.
4. Keep clicks on native `BhBuilding`; open Main hall via HUD construction navigation.
5. Never call panel escape/hide unless `IsReleaseTownPanelVisuallyOpen`.
6. Do not reintroduce Route A poster lift or UI click relays for that owned world.
7. If a `<faction>_city_music` sidecar ships, Core `city_music_sounds` must not point at donor `soundSetName` values (human/nature/demon/…).

## Doc index

| Doc | Role |
| --- | --- |
| This file | Preferred paradigm (operational) |
| `town_unity_scene_replace_plan.md` / `_handoff.md` | Ownership phases and pick-up |
| `factory_city_scene_load_pins.md` | Load/Di2/EScene pins |
| `town_scene_render_static_mapping.md` | Historical Route A static map (not destination) |
| `factory_city_scene_runtime_pilot_breakage_catalog.md` | Phase 4/5 proof ledger |
