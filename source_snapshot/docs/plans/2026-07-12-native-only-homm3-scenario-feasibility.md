# Stock-Native HoMM3 Scenario Translation

Status: source/static + generated-artifact + validator proven for the current
batch under the raw-parity pipeline (`pipeline: vanilla_stock_raw_parity`),
including map-event Dialog/`GiveRes` QuestScript parity on stock hosts
(Twins event pilot). Runtime load and gameplay in stock Olden remain unvalidated.

## Goal

Emit lossy but loadable HoMM3 scenarios that reference only SIDs/tiles present in
the stock Olden `Core.zip`, with no Golden Era plugin or custom Core overlay
dependency. This is a separate opt-in delivery lane and does not change the
Golden Era campaign path.

## Current Implementation

- `experiments/campaign_port_poc/vanilla_stock/`: stock alignment IR, terrain,
  object mapping, gate-face rotation wrapper, placement ground truth, map
  emission, and validation modules.
- Pipeline stages (mirrors raw_translation without GE content):
  1. standalone `.h3m` → alignment IR (`propEntities` + `layeredMapData`)
  2. stock terrain projection (Sand ocean basin, Dirt subterranean/rock,
     biome `waterMap` rivers, Chebyshev-2 tunnel clearance)
  3. stock-SID object emit + scenery footprints
  4. stock-safe gate-face rotation
  5. placement ground truth + fail-closed validator
- `tools/build_vanilla_stock_map.py`: single-map build entrypoint.
- `tools/build_vanilla_stock_batch.py`: batch build from
  `scenarios/vanilla_stock/batch_manifest.json` (2 victory pilots + Twins event
  pilot + extended Complete/HotA maps).
- Map events: unguarded `fx_quest_mark_gold_01` + Dialog Before +
  `ObjectInteractionAfter` GiveRes; guarded `random-squad` +
  `SquadInteraction`/`SquadKill`. Stock has no `Zone 1x1`. Optional dialog
  Core overlay is text-only.
- `tools/validate_vanilla_stock_map_contract.py`: single-map validator.
- `tools/validate_vanilla_stock_batch_contract.py`: batch validator.
- `tools/build_vanilla_stock_regression.py` + `tools/validate_vanilla_stock_regression_contract.py`:
  RoE/AB/SoD golden-fingerprint regression sample (HotA soft-fail);
  baselines under `scenarios/vanilla_stock/regression_baselines/`.
- `artifacts/campaign_port_poc/vanilla_stock/<scenario_id>/`

Stock Core.zip currently exposes tiles `{1..7}` and waters `{1..7}` only.
Golden Era tiles Burrow(15) / Water(18-22) / Void(23) are forbidden on this lane.

## Batch coverage

| Role | Maps |
| --- | --- |
| Pilot | Dungeon Keeper (`WINSTANDARD`), Treasure Hunt (`TAKEMINES`) |
| Event pilot | Twins (`WINSTANDARD`, 6 map events: Dialog/`GiveRes` + guarded squads) |
| Extended | Elbow Room, Chasing a Dream, Jihad, Sands of Blood, Time's Up, Ascension, Darwin's Prize, Dragon Pass, Faeries |

Extended maps are WINSTANDARD-only today. Many other Complete maps still fail closed
on H3M walk gaps, unsupported victory types, or gate/monolith pairing conflicts.
Tower/Stronghold/Fortress/Conflux/Cove player towns have no stock counterpart and
therefore become editable stock faction/hero choices rather than forced Temple
or a fabricated faction mapping.

## Feasibility Boundary

| Goal | Verdict |
| --- | --- |
| Stock scenery and most adventure buildings | feasible through explicit stock SID mapping |
| Lossy towns, dwellings, neutrals, and heroes | feasible only through declared faction/unit remaps |
| Faithful HoMM3 factions, creatures, and heroes | impossible without custom content; stock has no `h3_*`/`homm3_*` rows |
| Current Golden Era boats/flotsam and custom land-on objects | not stock-native; must be remapped or blocked |
| GE Burrow/Water/Void tiles | absent from stock Core; ocean uses Sand basin; subterranean/rock use Dirt |
| Silent Core overlay generation | forbidden |

## Design Rules

- Stock Core is an allowlist, not a donor suggestion.
- Every replacement is explicit and reviewable; unsupported families fail closed.
- No `homecoming_custom_objects.json`, custom squads, custom factions, or plugin runtime hooks.
- The output SID and artifact root remain separate from Golden Era scenario outputs.
- Static validation must not be described as runtime load, interaction, pathfinding, AI, or win-condition proof.

## Validation

```powershell
$env:PYTHONUTF8 = '1'
python tools/build_vanilla_stock_batch.py --install
python tools/validate_vanilla_stock_batch_contract.py --require-installed
```

Single-map checks remain available via `tools/build_vanilla_stock_map.py` and
`tools/validate_vanilla_stock_map_contract.py`.

The next proof tier is a stock-install runtime load and focused gameplay pass. Until that happens, keep runtime behavior explicitly unvalidated.
