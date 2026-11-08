# Vanilla Town Scene-Graph Ledger

Proof label: **runtime behavior proven** (live probe bridge dump while active scene was `cityHuman2`).

Not claimed: scene-replace readiness, deployed-payload validation, or user-visible replacement gameplay.

Abandon-donor plan (next work, not implemented here): `docs/town_unity_scene_replace_plan.md`. Cold-start handoff: `docs/town_unity_scene_replace_handoff.md`. Hide-donor-meshes is **rejected** as the product pilot.

## Capture context

- Bridge build `0.1.299`, profile `OfficialDeobf`, frames `48735` → `60345`.
- Active scene: `cityHuman2`; fraction `human`.
- Custom town layer overlay: **not active** (`layers.rootExists: false`) — clean native graph.
- Machine inventory: `artifacts/vanilla_town_scene_dump/ledger.json`.
- Raw probe responses: `artifacts/vanilla_town_scene_dump/probe_raw/`.

## Assumptions and short proof

Assumptions: vanilla Castle town (not Factory); bridge stayed ready; decomp `dxg` = live `MonoBehaviourPublicStBhbuceBhInceStBhceUnique`; its string field is the sceneSlot key used by manager lookup.

Proof: 34 `BhBuilding` in `cityHuman2` (3 activeInHierarchy); manager slot list Count=20; each list entry's sceneSlot backing field is a string; `buildingsInSlot.Length` across slots sums to 34; CityUI canvases report `ScreenSpaceCamera` + `UICamera(Clone)`.

## World scene (`cityHuman2`)

### BhBuildingsManager

- Object `human_city_all_objects` id `1923292` scene `cityHuman2` activeInHierarchy=`True`.
- Path note: Path contains Cyrillic U+0441 in the city segment of the root (human_\u0441ity_allobject).
- `constructOnStart` = `False` (live field read).
- Slot list field `field_Private_List_1_MonoBehaviourPublicStBhbuceBhInceStBhceUnique_0` Count = **20**.

### Scene slots (sceneSlot found: yes)

| # | sceneSlot | buildingsInSlot.Length | active BhBuilding | inactive BhBuilding |
| --- | --- | ---: | ---: | ---: |
| 0 | `Main` | 3 | 1 | 2 |
| 1 | `Tier_1` | 2 | 1 | 1 |
| 2 | `Tier_2` | 2 | 1 | 1 |
| 3 | `Tier_3` | 2 | 0 | 2 |
| 4 | `Tier_4` | 2 | 0 | 2 |
| 5 | `Tier_5` | 2 | 0 | 2 |
| 6 | `Tier_6` | 2 | 0 | 2 |
| 7 | `Tier_7` | 2 | 0 | 2 |
| 8 | `Artifact_Market` | 1 | 0 | 1 |
| 9 | `Intelligence_Academy` | 1 | 0 | 1 |
| 10 | `Golden_Calf` | 1 | 0 | 1 |
| 11 | `Tavern` | 1 | 0 | 1 |
| 12 | `Magic_Guild` | 4 | 0 | 4 |
| 13 | `Training_Range` | 1 | 0 | 1 |
| 14 | `Treasury` | 1 | 0 | 1 |
| 15 | `Bank` | 1 | 0 | 1 |
| 16 | `Market` | 1 | 0 | 1 |
| 17 | `Walls` | 3 | 0 | 3 |
| 18 | `Resource_Depot` | 1 | 0 | 1 |
| 19 | `Resource_Depot_2` | 1 | 0 | 1 |

Live type pin: decomp `dxg` → `MonoBehaviourPublicStBhbuceBhInceStBhceUnique`; sceneSlot field `<cecz>k__BackingField`.

### BhBuilding inventory

- Total in `cityHuman2`: **34**
- activeInHierarchy: **3** → `H_build_Main_Level_1`, `H_build_Tier_1_Level_1`, `H_build_Tier_2_Level_1`
- inactiveInHierarchy: **31**

Active buildings are the currently constructed/visible upgrade variants; inactive siblings in the same slot are alternate levels/variants kept in the scene graph.

### Camera

- `CityCamera` id `1920362` active; components include `BhCityCameraController`, `BhCityCameraHelper`.
- World position: `{'x': 74.46, 'y': 2.65, 'z': 35.456}`.
- `MainCamera` id `1920300` path `CityCamera/MainCamera` active.
- Camera props: FOV=`47.6`, near=`0.01`, far=`1000`, orthographic=`False`, depth=`0`.
- Other faction city cameras loaded but inactive: `CityUndead2`, `cityUnfrozen2`, `cityDungeon`, `cityDemon`, `cityNature`.

### Renderers under human city paths

- `MeshRenderer` (scene=`cityHuman2`, pathContains=`human`): total **106** (returned 106, truncated=False); activeInHierarchy in returned set: 13.
- `SkinnedMeshRenderer` (same filter): total **24** (returned 24); activeInHierarchy in returned set: 13.
- `unity_renderers` nameContains=`H_build`: returned 80 (truncated=True); cityHuman2 subset count=80 active=4.

## UI scene (`CityUI`)

- `CanvasCityPanel`: renderMode=`ScreenSpaceCamera`, worldCamera=`UICamera(Clone)`, sortingOrder=`118`, sortingLayer=`UI`, planeDistance=`500`.
- `CanvasCityTechHUDPanel`: renderMode=`ScreenSpaceCamera`, worldCamera=`UICamera(Clone)`, sortingOrder=`121`, sortingLayer=`UI`, planeDistance=`500`.
- `GarnisonPanel` nests under `CanvasCityPanel` (samples confirm same ScreenSpaceCamera canvas).

## Still missing for an abandon-donor pilot

- No refuse/skip of `cityHuman2` load for custom factions proven; no dedicated empty/custom city scene load proven.
- No write/replace of city scene content or slot visibility outside the donor proven.
- vfxRoot on sampled active BhBuilding read as null (may be unassigned or only set for some buildings).
- unity_object_components often reports opaque UnityEngine.Component type names for IL2CPP behaviours; use field_signatures + component_member_path instead.
- Il2Cpp List indexing requires allowProperties=true so the list is typed; without it indexer fails.
- Config-side BuildingData.sceneSlot string inventory (data layer) not dumped here — only scene-side slot strings.
- Interaction hitboxes / pointer path beyond BhBuilding presence not exercised.
- Camera controller lookAt/settings fields not fully dumped.
- Hiding native MeshRenderers while keeping `cityHuman2` loaded is **not** the abandon-donor success bar (rejected product path).

## Evidence files

- `artifacts/vanilla_town_scene_dump/ledger.json`
- `artifacts/vanilla_town_scene_dump/probe_raw/` (per-command responses)
- Static background: `docs/town_scene_render_static_mapping.md`, decomp `BhBuilding` / `BhBuildingsManager` / `dxg`
