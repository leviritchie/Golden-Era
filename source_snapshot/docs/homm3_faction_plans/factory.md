# HotA Factory Faction Plan

Evidence level: **active runtime manifest + generated Core/bundles exist** (`custom_factions/homm3_factory.json`, town refs, import bundles).  
Proof boundaries (honest):

| Boundary | Status |
| --- | --- |
| Source / static manifests & validators | Validated |
| Generated town/runtime assets & UnityFS unit bundles | Present under plugin/import paths |
| Owned `cityFactory` world art, native `BhBuilding` clicks, hall construction open | **User-visible gameplay proven** (Golden Era, 2026-07-23) — see `docs/custom_town_scene_paradigm.md` |
| Split Assembly combat buff apply | Source/compile wired; **combat runtime / user-visible unproven** |
| Campaign / StoryHub / raw_translation | **Absent** (out of scope for this faction lane) |
| Authored `cityFactory.unity` | **Absent** (synthetic container still LoadScene+Move from Castle) |
| Gantry / Mother Nature / Intelligence / Training Range as native Castle `BhBuilding` slots | **Debt** — Gantry art exists; Castle graph has no `Factory_Gantry` slot |

## Source lane

- Archive: `vcmi/Mods/hota/mods/factory/content.zip`
- Active manifest: `custom_factions/homm3_factory.json`
- Concept draft (inventory / import join): `tools/homm3_import/faction_concepts/homm3_factory.json`
- Handoff: `docs/factory_bulwark_implementation_handoff.md`
- Prepare: `python tools/homm3_import/prepare_hota_factory_bulwark_neutral_bundles.py --faction factory`
- Validate: `python tools/validate_hota_factory_bulwark_runtime_assets.py`
- Town paradigm: `docs/custom_town_scene_paradigm.md`

## Roster notes

- Seven primary tiers terminate in Couatl. Dreadnought is an explicit second tier-7 line via `additionalRecruitmentLines` → `Build_Factory_Gantry` / `barracks_homm3_factory_8` / `AVGdread.dir/00_00.png`.
- Material-class alternate upgrades are **user-locked** in `tools/homm3_import/alternate_upgrade_concepts/material_class_hs_selections.json` (Firebug, Tinker, Plated Armadillo, Clockwork Automaton, Glassworm, Marshal, Jade Coatl, Ironclad). Older `awaiting_user_choice` prose is stale.
- Biome: faction-owned **Foundry** (Sand presentation clone, tile 29). Not Stronghold Wasteland.
- Faction skill: Split Assembly (Natural / Industrial line counting).

## Remaining gaps

See consolidated order: `docs/factory_bulwark_hard_backlog_execution.md` and
`docs/homm3_faction_proofs/factory_bulwark/README.md`.

1. Phase 0 static/code — **landed** (portrait hashes, IA/Training strip,
   Split Assembly log enrichment, shared force-setup pilot, proof scaffolding).
2. Live: Bulwark town smoke, then Split Assembly C0–CNeg–C5 with force-setup.
3. Live: ability P0 combat proof (Blow Up / Locust / Jotunn Slow — dealers are
   data-wired; live-positive unproven).
4. Live: Runes combat proof (runtime registered; see Bulwark plan).
5. PARKED: authored `cityFactory.unity`, Gantry/MN scene v2, Campaign B/C,
   Sieidi/Altar, Brand Phase C.

- Split Assembly live combat proof (`planned:` / `applied unit buffs:` with
  `unitSid=` / `verified=`). Artifact scaffold:
  `artifacts/factory_split_assembly_combat_proof/v1/` (no pass `PROOF.json` yet).
- Authored `cityFactory.unity` (still Castle LoadScene donor + owned container).
- Native Castle slots for Gantry (and other Factory specials without slots).
- Intelligence Academy / Training Range stay non-constructible until
  `nativeLevels` maps authentic art (unbound Castle-slot fail-closed).
- Focus remaps that still need combat proof (Blow Up, Locust Harvest, Wind-Up,
  Taunting Plate, etc.) plus real remaining runtime debt: Ironclad immobility
  lock beyond Carapace; Locust larva support deferred.
- Campaign / StoryHub continuity for Factory.
- Conflux completeness / construct-refresh edges on the owned town path.
