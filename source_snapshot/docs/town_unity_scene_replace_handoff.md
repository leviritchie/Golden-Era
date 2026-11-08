# Town Unity Scene Replace Ã¢â‚¬â€ Session Handoff

Pick-up doc for another agent or human. Operational only; not a chat log.

**Plan (authoritative next steps):** `docs/town_unity_scene_replace_plan.md`
**Preferred paradigm:** `docs/custom_town_scene_paradigm.md`
**Status:** Factory `cityFactory` LoadScene/Move ownership, HotA world art on native `BhBuilding` slots, native building clicks, and town-hall construction menu open are **user-visible gameplay proven** (Golden Era, 2026-07-23). Route A posters are not the destination. Failed playtest `city_hive` helpers remain forbidden.

Proof labels follow `AGENTS.md`: source/static Ã¢â€ â€™ generated Ã¢â€ â€™ build Ã¢â€ â€™ deployed Ã¢â€ â€™ startup smoke Ã¢â€ â€™ runtime Ã¢â€ â€™ user-visible gameplay.

---

## 1. Goal

Custom towns (Factory first) must **own** a vanilla-shaped Unity city world (`cityFactory`), not stay on Route A posters and not keep loading Castle's scene name as the town world. Canonical rules: `docs/custom_town_scene_paradigm.md`.

**Immediate success (locked):** Factory opens `cityFactory` through native session/Di2/`Void(EScene)` with active, bound `BhBuilding`s, native colliders, HotA world art, and HUD-equivalent hall construction open.

**Product path:** `LoadScene` authored city content -> `MoveGameObjectToScene` into `cityFactory` -> activate the root containing `BhBuildingsManager` -> Di2 bind -> native Void -> validate active/bound `BhBuilding`s -> activate presentation roots (`CityCamera`, `Lights`) -> Route A posters/suppress off -> world HotA art on native slots -> hall open via `BuildingsConstruction` navigation (visually gated peer-panel close).

Destination is **not** UI poster polish and **not** suppress-donor-meshes-under-overlay while `cityHuman2` still loads.

---

## 2. Rejected paths

| Path | Status |
| --- | --- |
| Hide donor meshes / keep loading `cityHuman2` as recommended pilot or product end state | **Rejected**. Diagnostic-only at most; never a product pass. |
| Refuse/skip `cityHuman2` without a replacement vanilla-shaped world | **Rejected** as product pilot (superseded by Castle-parity clone). |
| Revive / port failed playtest `city_hive` helpers (`TryAliasHiveCityScene`, alias onto `cityDemon`, `_decompiled_shipped` register helpers) | **Rejected**. Failed experiment; not a load-path template. Vanilla Hive / `cityDemon` stays a normal faction city Ã¢â‚¬â€ do not alias Factory onto it. |
| More `CanvasCityPanel` / RawImage z-order, Route A mirror polish, town prefab UI bundles as end state | **Rejected** as destination. Legacy/comparison only; see `docs/custom_town_scene_paradigm.md`. |
| Ã¢â‚¬Å“Poster is temporary but donor staysÃ¢â‚¬Â | **Rejected** as success definition. |

Superseded plan commit: `3579904f95` (hide-donor pilot) Ã¢â‚¬â€ do not follow.

---

## 3. What was proven (runtime)

Label: **runtime behavior proven** (bridge `0.1.299`, OfficialDeobf). Not claimed: Factory `cityFactory` load readiness or user-visible Factory city-scene gameplay.

### Ledgers

| Doc | Scope |
| --- | --- |
| `docs/vanilla_town_scene_graph_ledger.md` | Castle `human` on `cityHuman2`, overlay off |
| `docs/factory_town_scene_graph_ledger.md` | Factory `homm3_factory` on donor `cityHuman2`, overlay on; safe AÃ¢â‚¬â€œE complete |
| `artifacts/vanilla_town_scene_dump/ledger.json` | Machine inventory |
| `artifacts/factory_town_scene_dump/ledger.json` | Machine inventory (safe re-dump) |

### Key facts (historical donor-ledger proof; not current Factory ownership claim)

- Pre-cutover ledgers measured Factory and Castle on `cityHuman2`. Current runtime proof establishes Factory ownership under active scene `cityFactory` after LoadScene/Move.
- Manager slot list **20**; `sceneSlot` names match; `buildingsInSlot` length sum **34** both sides.
- Vanilla `BhBuilding`: 34 total; 3 activeInHierarchy. Factory overlay-era dump: 0 activeInHierarchy (poster path).
- City camera FOV **47.6**, near 0.01, far 1000.
- CityUI is a **separate** ScreenSpaceCamera domain; overlay lives there today.
- Install build settings include `Assets/Scenes/City/cityHuman2.unity` (and other faction cities). No `cityFactory` / `city_hive` in build list. `cityGnome` is in live `EScene` but **no** matching City `*.unity` in `globalgamemanagers`.

### Checkpoint commits

| Hash | What |
| --- | --- |
| `d47c2fe497` | Vanilla + partial Factory town scene-graph ledgers |
| `9ba3b286e9` / `01b99087af` | Safe Factory re-dump complete |
| `3579904f95` | Old hide-donor plan Ã¢â‚¬â€ **superseded** |

---

## 4. Current code / config reality

- Factory manifest + installed Core city row use `citySceneName` / `sceneName` = **`cityFactory`** (Harmony `get_sceneName` rewrite removed; IL2CPP field accessor was live-negative).
- Registrar: `Homm3FactoryCitySceneRegistrar` (ordinal pin -> additive donor load -> move roots -> unload donor -> Di2 bind -> native Void -> post-native lifecycle validation). Config flag `homm3FactoryCitySceneReplace` defaults false; the repo smoke config enables it.
- Product poster visuals may still exist under CityUI (`Homm3StrongholdTownLayers`); that is not abandon of the world scene.
- Failed playtest `city_hive` helpers exist only under `_decompiled_shipped` Ã¢â‚¬â€ **do not call, port, or treat as load-path evidence**. Vanilla Hive is unrelated.

Proof labels: ownership, HotA world art, native building clicks, and hall construction open are user-visible proven for Factory. Remaining edges (e.g. Conflux completeness, some construct-refresh cases) stay in `docs/factory_city_scene_runtime_pilot_breakage_catalog.md` and must not revive Route A as destination.

---

## 5. How scene load maps (static + tooling)

1. Fraction scaffold `citySceneName` Ã¢â€ â€™ Core city `sceneName` Ã¢â€ â€™ parse to `EScene` Ã¢â€ â€™ load matching Unity city scene (additive with `cityUI` / related city stack).
2. `BhBuildingsManager` / `BhBuilding` / city cameras live in the **faction city world**, not in CityUI.
3. Abandon means Factory's active town world is `cityFactory` with moved, native-lifecycle donor roots, not Castle `cityHuman2`.

---

## 6. Next work - Factory presentation runtime proof

1. ~~Decomp-pin~~ Done: `docs/factory_city_scene_load_pins.md`.
2. ~~Registrar~~ `Homm3FactoryCitySceneRegistrar` **deployed** to Golden Era; config `homm3FactoryCitySceneReplace: true`.
3. ~~Core/manifest~~ `citySceneName` / Core `sceneName` = `cityFactory` (installed Core readback proven).
4. ~~Runtime pilot (ownership)~~ Active world `cityFactory`, LoadScene+Move, Di2/Void, Route A skip, Castle world user-visible after presentation activate. Catalog: `docs/factory_city_scene_runtime_pilot_breakage_catalog.md`.
5. **Do not use playtest `city_hive` learnings.**
6. **Current preferred presentation:** manager ownership is active before native `Void(EScene)`; compositor joins supported slots through explicit native-to-Factory levels; hall Main opens via HUD `BuildingsConstruction` (`TryOpenOwnedCityHallConstructionMenu`); upgrade peer close uses `IsReleaseTownPanelVisuallyOpen`. Do not reintroduce Route A poster lift, UI click relays, deferred hall-open races, or `bajs` activation storms.

### Smoke checklist

| Check | Expect |
| --- | --- |
| Startup | `registered N patch surface(s)` (not `disabled`) |
| Installed Core | `DB/objects_logic/cities/homm3_factory_city.json` `sceneName` = `cityFactory` |
| Factory town open | `bound sceneName 'cityFactory' -> EScene ordinal 26` |
| | `moved N LoadScene'd root(s) ... into cityFactory (no Instantiate)` |
| | `activated presentation root(s): CityCamera, Lights` |
| | `native Void(EScene) returned; activeScene='cityFactory'` |
| | `skipping Route A poster/suppress` |
| | `Build_Main vertical slice: art on 'H_build_Main_Level_*'` |
| Active world | scene name `cityFactory` (not `cityHuman2`) |
| Click Main | Opens construction menu via HUD navigation path (stays open; no under-cursor deferral required) |
| Metadata pin | `validate_escene_city_factory_pin.py` OK on Golden Era install |
| Fail | any own/clone failed / refuse fallback / Fatal on registrar / Route A Factory layers as scored pass |

**Pass (Phase 4):** active town world = `cityFactory`; slot/camera/manager parity after move; CityUI; no silent `cityHuman2` restore; no playtest `city_hive` helpers. See breakage catalog for clicks/construct/Phase 5.
**Fail:** mesh-hide or poster scored as pass; alias to live faction cities (including vanilla Hive `cityDemon`); crash without diagnostic.

---

## 7. Top unknowns (narrowing)

1. ~~Exact live hooks~~ Pinned in `docs/factory_city_scene_load_pins.md` (source/static).
2. ~~Runtime ownership for Factory town entry~~ Proven: active world `cityFactory` (see breakage catalog).
3. Remaining gaps (Factory art runtime proof, clicks, construct refresh, Castle-after-Factory, repeat entry) are tracked in `docs/factory_city_scene_runtime_pilot_breakage_catalog.md`.

---

## 8. How to re-probe safely (if needed)

Do **not** reuse the aggressive full-sweep runner as-is (`artifacts/factory_town_scene_dump/crash_triage.md`).

Safe path: OfficialDeobf deploy; enter Factory town; batched AÃ¢â‚¬â€œE via `run_safe_batches.py` / `resume_safe_d_e.py`; assemble ledger; stop on `bridge_gone`.

---

## 9. Files to read first

1. `docs/custom_town_scene_paradigm.md` — preferred product path
2. `docs/town_unity_scene_replace_plan.md`
3. This handoff
4. `docs/vanilla_town_scene_graph_ledger.md` + `docs/factory_town_scene_graph_ledger.md`
5. `docs/town_scene_render_static_mapping.md` — historical Route A map only (not destination)
6. `custom_factions/homm3_factory.json` (`citySceneName`)
7. `.cursor/skills/decomp-search/SKILL.md` + `EScene` DiffableCs
8. `Homm3StrongholdTownLayers.cs` — legacy overlay owner (non-destination)

Do **not** treat `_decompiled_shipped` playtest `city_hive` helpers as a template or as load-path evidence. Vanilla Hive is a shipped faction; that experiment is unrelated.
