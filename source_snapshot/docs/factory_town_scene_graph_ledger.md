# Factory Town Scene-Graph Ledger

Proof label: **runtime behavior proven (safe re-dump A-E complete)**.

Not claimed: broad MeshRenderer/SkinnedMesh inventory (intentionally skipped), abandon-donor readiness, user-visible Factory city-scene gameplay, deployed payload proven.

Abandon-donor plan (next work, not implemented here): `docs/town_unity_scene_replace_plan.md`. Cold-start handoff: `docs/town_unity_scene_replace_handoff.md`. Hide-donor-meshes is **rejected** as the product pilot.

## Capture context

- Bridge build `0.1.299`, profile `OfficialDeobf`, start frame `39450`, end frame `71190`.
- Active scene: `cityHuman2`; fraction `homm3_factory`.
- Custom town layer overlay: **active** (`layers.rootExists: True`, path `CanvasCityPanel/OfflineUnlockStrongholdTownLayers`, activeLayerCount=6, rawImageCount=6).
- Raw probes: `artifacts/factory_town_scene_dump/probe_raw_safe/`.
- Machine inventory: `artifacts/factory_town_scene_dump/ledger.json`.
- Safe progress: phase `COMPLETE`, batches `A,B,C,D,E`.

## Assumptions and short proof

Assumptions: Factory town on donor `cityHuman2`; OfficialDeobf live probe; safe A-E plan (no broad `unity_renderers`, no heavy `unity_object_components`); stop on bridge_gone without retry.

Proof: town_ui_state: activeScene=cityHuman2, fraction=homm3_factory, layers.rootExists=True path=CanvasCityPanel/OfflineUnlockStrongholdTownLayers activeLayerCount=6 rawImageCount=6. BhBuilding scene=cityHuman2 total=34; requireActiveHierarchy total=0. BhBuilding activeSelf=6 names=['H_build_Main_Level_1', 'H_build_Main_Level_2', 'H_build_Tier_1_Level_1', 'H_build_Tier_2_Level_1', 'H_build_Tier_3_Level_1', 'H_build_Tier_3_Level_2']. BhBuildingsManager objectId=1923292; constructOnStart=False; slot list Count=20; manager activeInHierarchy=False. Manager-indexed sceneSlot strings captured for indices with nameProbeOk; complete name+length pairs=20/20; known length sum=34 (vanilla full sum=34). CityCamera+MainCamera present in cityHuman2; overlay OfflineUnlockStrongholdTownLayers under CanvasCityPanel.

## World scene (`cityHuman2`)

### BhBuildingsManager

- Object `human_city_all_objects` id `1923292` activeInHierarchy=`False` (False under overlay; True in vanilla).
- `constructOnStart` = `False`.
- Slot list Count = **20**.

### Scene slots (manager-indexed; complete)

| # | sceneSlot | buildingsInSlot.Length | probe |
| --- | --- | ---: | --- |
| 0 | `Main` | 3 | ok |
| 1 | `Tier_1` | 2 | ok |
| 2 | `Tier_2` | 2 | ok |
| 3 | `Tier_3` | 2 | ok |
| 4 | `Tier_4` | 2 | ok |
| 5 | `Tier_5` | 2 | ok |
| 6 | `Tier_6` | 2 | ok |
| 7 | `Tier_7` | 2 | ok |
| 8 | `Artifact_Market` | 1 | ok |
| 9 | `Intelligence_Academy` | 1 | ok |
| 10 | `Golden_Calf` | 1 | ok |
| 11 | `Tavern` | 1 | ok |
| 12 | `Magic_Guild` | 4 | ok |
| 13 | `Training_Range` | 1 | ok |
| 14 | `Treasury` | 1 | ok |
| 15 | `Bank` | 1 | ok |
| 16 | `Market` | 1 | ok |
| 17 | `Walls` | 3 | ok |
| 18 | `Resource_Depot` | 1 | ok |
| 19 | `Resource_Depot_2` | 1 | ok |

Complete name+length pairs: **20/20**. Known length sum: **34** (vanilla full sum 34).

### BhBuilding inventory

- Total in `cityHuman2`: **34**
- activeInHierarchy: **0** (vanilla: 3)
- activeSelf: **6** → `H_build_Main_Level_1`, `H_build_Main_Level_2`, `H_build_Tier_1_Level_1`, `H_build_Tier_2_Level_1`, `H_build_Tier_3_Level_1`, `H_build_Tier_3_Level_2`

### Camera

- `CityCamera` cityHuman2 id `1920362` activeInHierarchy=`True`
- `MainCamera` cityHuman2 id `1920300` activeInHierarchy=`True`
- Batch E: fieldOfView=`47.6`, nearClipPlane=`0.01`, farClipPlane=`1000`.

## UI scene (`CityUI`)

- `CanvasCityPanel`: renderMode=`ScreenSpaceCamera`, worldCamera=`UICamera(Clone)`, sortingOrder=`22168`, planeDistance=`500`.
- `CanvasCityTechHUD`: renderMode=`ScreenSpaceCamera`, worldCamera=`UICamera(Clone)`, sortingOrder=`121`, planeDistance=`500`.
- Overlay object: `OfflineUnlockStrongholdTownLayers` path=`CanvasCityPanel/OfflineUnlockStrongholdTownLayers` activeInHierarchy=`True`.
- Overlay layer surfaces sampled: 4.

## Key vs-vanilla findings

- Same donor scene cityHuman2 and same 20 manager slot indices; sceneSlot strings match vanilla where compared.
- Factory overlay ON (6 RawImage layers) vs vanilla overlay OFF.
- Factory BhBuilding activeInHierarchy=0 vs vanilla=3; Factory still has activeSelf=6 (variants enabled but hierarchy suppressed under overlay).
- Manager activeInHierarchy=False under Factory overlay vs True in vanilla.
- Factory buildingsInSlot.Length sum for all 20 indices = 34; vanilla full table sums to 34.

## Remaining intentional gaps

- Broad MeshRenderer / SkinnedMesh counts (intentionally skipped in safe plan).
- Per-dxg object dumps (`70/71_*`) not part of safe A-E.

## Evidence files

- `artifacts/factory_town_scene_dump/ledger.json`
- `artifacts/factory_town_scene_dump/probe_raw_safe/`
- `artifacts/factory_town_scene_dump/safe_redump_progress.json`
- `artifacts/factory_town_scene_dump/run_safe_batches.py`
- `artifacts/factory_town_scene_dump/resume_safe_d_e.py`
- Compare baseline: `docs/vanilla_town_scene_graph_ledger.md`
