# Vanilla Stock Scenery Footprints

## Decision

The vanilla translator now treats the HoMM3 8x6 bottom-right-anchored block
mask as the scenery pathing contract, matching the raw-translation lane.

1. Prefer a same-family stock `ObjectConfig` whose occupied-node offsets exactly
   match the complete source block mask.
2. When no exact stock shape exists, place an explicitly configured stock 1x1
   blocker on every source blocked cell.
3. When the source mask is empty, use an explicitly configured stock decoration
   with no occupied nodes.
4. Fail generation when a table row's `sourceBlockCount` disagrees with the
   decoded mask, or when an explicit stock pathing equivalent is unavailable.

The stock lane does not emit a Core overlay. Consequently, residual 1x1 fill
objects are visible; raw translation can instead use its custom invisible
pathing blocker. This limitation is recorded in each generated manifest rather
than hidden behind a fallback.

## Validation

`validate_vanilla_stock_map` reconstructs every scenery placement's occupied
nodes from stock `Core.zip` and requires their union to equal the projected H3
mask. The build/deploy entry point invokes this validator before installation.

On 2026-07-13, generated-artifact validation passed with zero footprint
mismatches for Dungeon Keeper and Treasure Hunt. Runtime loading, pathfinding,
and user-visible scenery quality remain unvalidated.
