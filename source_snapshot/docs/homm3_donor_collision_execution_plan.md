# HoMM3 Donor Collision Execution Plan

Created May 14, 2026 after Fortress exposed the long-term donor collision problem.

## Policy

Donor collisions are allowed. Donor-only reverse lookup is not allowed.

Custom faction unit identity must stay on the custom SID (`h3_*`) wherever the game path can carry it. Donor SIDs are native shell inputs for specific engine lookups, not stable custom-faction identity.

## What Can Break

- A global `hydra -> h3_*` map can route vanilla Dungeon, Stronghold Cyclops, or Fortress Hydra into the wrong portrait, HUD, tooltip, map billboard, or battle visual.
- A shared donor dwelling such as `barracks_dungeon_6` can be painted as the wrong faction if map-object aliasing does not know which custom city was seen in the current map/session.
- Fortress uses mixed donor factions per unit line. Any path that assumes one donor faction per custom faction can load the wrong native prefab root.
- Runtime fallbacks can hide missing data. If a custom SID has no registry/import/payload entry, the path should fail validation or leave native behavior alone rather than inventing a donor-to-custom guess.

## Required Shape

- `custom -> donor` is globally safe and can be resolved from the registry.
- `donor -> custom` requires context: current faction SID, current city SID, saved original custom SID, map object SID/prefix, or equivalent session context.
- Ambiguous donor-only reverse lookups must fail closed.
- Manifest data in `custom_factions/*.json` is the source of truth; `Homm3CustomFactionRegistry` is the compiled runtime mirror until deliberate runtime manifest loading exists.

## Execution Steps

1. Keep documenting the invariant in agent-facing docs and this plan.
2. Audit every runtime hook and release generator for donor-only reverse maps.
3. Move donor unit faction/root data into `Homm3CustomFactionRegistry`, not local Stronghold/Tower/Fortress tables.
4. Convert UI, portrait, map-object, and battle hooks to context-aware registry calls.
5. Extend `tools/validate_custom_faction_manifests.py` so manifest data and compiled registry data cannot drift.
6. Treat remaining Stronghold-named helpers as temporary adapters only; do not add new faction-specific donor maps there.

## Initial Slice (Implemented)

The first execution slice moved tooltip donor-prefab loading away from a hard-coded Stronghold/Dungeon table. The registry and manifest validator now cover context-aware reverse lookup and visual ownership beyond this initial slice. Use current `Homm3CustomFactionRegistry.cs` and `tools/validate_custom_faction_manifests.py` for the implemented contract.

