# Vanilla stock ownership / access / scenery transfer (2026-07-30)

## Scope

Transferred campaign raw_translation ownership and access contracts into
`vanilla_stock` without GE overlays or StoryHub profile behavior.

## Delivered

1. **Compact native owners** via `ownership_contract.apply_ownership_contract`
   wrapping `approach_cell.surface_emit.renumber_map_owners_to_native_compact`
   (human=1, AI=2..N). Sparse H3 colors (e.g. Elbow Room 1/2/3/6/7/8) renumber
   correctly; `meta.spawns` is derived only after renumber.
2. **AI multi-faction split + orphan bind** reused from surface_emit, with stock
   adaptations:
   - free-choice `random-city` seats are reserved so synthetic split owners cannot
     collide with playable provisional numbers;
   - when all seats 1..8 are already playable, minority mixed-faction towns demote
     to neutral with an explicit manifest report (no silent 9th owner).
3. **Human start audit**: vanilla already uses City/`mainTown` starts (heroes
   omitted). Recorded as `humanStartAudit.promotionRequired=false`.
4. **Victory / event audiences** translate through `h3ColorToFinalOwners`
   (WINSTANDARD PlayerDefeated + propActions sides). Unbound H3 mask bits drop.
5. **Access pass**: stock portal GATE + town south-approach clear
   (`access_contract.py`). No GE barracks/dialog.
6. **Scenery canon post-pass**: opt-in `--enable-scenery-canon-postpass` only.
7. **Serialization shape**: empty ObjectsProperties families expanded to match
   the stock Thirst template; `campaignInfo` preserved.

## Validators

`validate_map.py` pins compact `1..playersCount`, human owner 1, no mixed-faction
City seats, ownership/access/scenery/serialization manifest sections, and
victory finals ⊆ compact owners.

## Fan import

`the_mysterious_island` (HotA) remains `fan_import` build-optional: ownership
contract unit-tests pass for its non-red human, but HotA-only event artifact
SpawnMapObject / creature budgets still fail closed. Complete-map batch is green.

## Proof boundary

generated_artifact + validator proven; runtime lobby/load/gameplay unvalidated.
