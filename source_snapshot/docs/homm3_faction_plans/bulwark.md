# HotA Bulwark Faction Plan

Evidence level: **active runtime manifest + generated Core/bundles exist** (`custom_factions/homm3_bulwark.json`, town refs, import bundles).  
Proof boundaries (honest):

| Boundary | Status |
| --- | --- |
| Source / static manifests & validators | Validated |
| Generated town/runtime assets & UnityFS unit bundles | Present under plugin/import paths |
| Owned city world path (`cityFactory` compositor) | **Wired** via shared owned-world registrar; **not Bulwark-specific user-visible proven** |
| Runes faction skill | Core load shape + rank text prepared; `Homm3BulwarkRunesRuntime` **registered** (Defend/Skip and other gain paths). Combat live-positive / `PROOF.json` **unproven** |
| Focus actives (16) | Native Core dealers + allowlisted transforms; **source/static + installed Core readback** via `validate_homm3_bulwark_ability_repair_contract`; combat unproven |
| Frostbound Skies | Source/static + `Homm3BulwarkUnitAbilityRuntime` flyer Slow **wired**; combat live-positive **unproven** |
| Campaign / StoryHub / raw_translation | **Absent** |
| HotA Sieidi / Altar of Runes authentic town mechanics | **Not claimed** |

## Source lane

- Archive: `vcmi/Mods/hota/mods/bulwark/content.zip`
- Active manifest: `custom_factions/homm3_bulwark.json`
- Concept draft (inventory / import join): `tools/homm3_import/faction_concepts/homm3_bulwark.json`
- Handoff: `docs/factory_bulwark_implementation_handoff.md`
- Prepare: `python tools/homm3_import/prepare_hota_factory_bulwark_neutral_bundles.py --faction bulwark`
- Validate: `python tools/validate_hota_factory_bulwark_runtime_assets.py`
- Town paradigm: `docs/custom_town_scene_paradigm.md`

## Roster notes

- Standard seven-tier line (Kobold through Jotunn). Eight Chieftains + eight Elders; Haugir excluded (`onlyOnWaterMap`).
- Material-class alternate upgrades are **user-locked** in `tools/homm3_import/alternate_upgrade_concepts/material_class_hs_selections.json`. Older `awaiting_user_choice` prose is stale.
- Biome: faction-owned **Permafrost** (Snow presentation clone, tile 30). Not Tower Tundra. Donor scaffolding: Nature city.
- Faction skill: Runes (per-stack levels; caps 3/6/9). Do not treat Wait as Defend.

## Remaining gaps

See consolidated order: `docs/factory_bulwark_hard_backlog_execution.md` and
`docs/homm3_faction_proofs/factory_bulwark/README.md`.

1. Phase 0 static/code shared with Factory — **landed** (proof scaffolding,
   force-setup pilot, IA/Training non-constructible without `nativeLevels`).
2. Live: Bulwark town smoke (cold start, Custom Game).
3. Live: Split Assembly proofs on Factory lane; then ability P0 including Jotunn Slow combat proof.
4. Live: Runes combat proof pack (`artifacts/bulwark_combat_proof/v1/` — runtime registered; no pass `PROOF.json` yet).
5. PARKED: Sieidi/Altar, Brand Phase C, Campaign B/C, Fair research beyond Trade Carnival.

- Runes battle registration is **done** (`Homm3BulwarkRunesRuntime`); remaining work is installed gameplay proof, not “bind Defend then register.”
- Frostbound Skies flyer Slow is **source-wired**; remaining work is combat live-positive proof.
- Bulwark-specific owned-town presentation proof (shared path is wired only).
- Authentic HotA Sieidi / Altar / Fair mechanics.
- Unfinished additive scaffolds (War Mammoth Defend Defense, Yeti recovery, Argali amp).
- Campaign / StoryHub continuity for Bulwark.
