# Custom-Town Siege Wall Contract

## Native owner

Siege walls are created by native battle initialization from `TransferBattle.cityArenaParams`. The arena parameters are built from the sieged `PropCity.buildingsConstructionSid` row, specifically its `Build_Wall` construction state and level. Town-screen `cityFactory` presentation assets do not supply siege-wall meshes.

## Contract

The release Core must contain exactly one `homm3_custom_town_buildings_construction` preset in `DB/buildings_constructions/custom_maps_buildings_presets.json`. Its `Build_Wall` row must be `isConstructed: true` with `level >= 1`; the release generator currently sets level 3 by cloning the native rich preset.

Generated and direct custom-town maps use that preset by default. Explicit procedural overrides remain supported for non-custom factions, but the procedural validator rejects any `homm3_*` city that names another construction preset. H3 raw-translation maps keep their per-town construction rows because those rows represent the decoded H3 built mask.

## Gates

- `tools/release_port/apply_release_core_overlay.py` creates or repairs the dedicated preset.
- `tools/validate_custom_faction_manifests.py` validates the Core preset.
- `experiments/campaign_port_poc/procedural_scenarios/validator.py` validates emitted custom-town rows.
- `experiments/campaign_port_poc/procedural_scenarios/preflight.py` validates construction SID resolution against Core.

## Proof status

Source/static, generated candidate, installed Core, direct scenario payloads, procedural payload, and map-load preflight are validated. Runtime startup, siege initialization, and user-visible wall rendering remain unproven until a live Golden Era siege is exercised.
