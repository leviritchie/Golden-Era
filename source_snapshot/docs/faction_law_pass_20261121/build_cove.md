# Cove law build (2026-11-21)

Data: `custom_factions/law_overrides/homm3_cove.json`. It holds `lawOverrides` (all 34 indices), `lawTree` and `lawRules`. `lawBuffs` is empty.

## Tree

Costs by rank are 27 / 31 / 35 / 26 / 27, 146 in total.

| Rank | Kingdom | Army |
|---|---|---|
| r0 | 3 Riches, 5 Spyglass Watch, 7 Lucky Doubloons, 8 Privateers' Pact | 4 Elite Nymphs, 10 Elite Crew Mates |
| r1 | 1 Tax Collectors, 14 Mining: Mercury, 9 Finder's Fee, 22 Grog Rations | 11 Elite Pirates, 17 Elite Stormbirds, 12 Boarding Actions |
| r2 | 16 Riches, 21 Prize Shares, 20 Quick Shovels, 15 Navigator's Charts | 23 Elite Sea Witches, 26 Broadside, 31 Keelhaul |
| r3 | 32 Cartographers' Guild, 33 Star Charts | 24 Elite Nix, 13 Boarding Hooks, 18 Powder Kegs |
| r4 | 29 Riches, 27 King's Ransom, 28 Smugglers' Tribute | 30 Elite Sea Serpents, 25 Jolly Roger |

- Riches 3/16/29 are first in their kingdom column and set to `{"enabled": false}` in the overrides.
- Unused indices 2, 6, 19 and 34 are `{"enabled": false}`.

## Changes from the draft

These were the caller's decisions:
- **#9 Finder's Fee replaces Crew Ashore.** It is a single-hero Treasure Hunting law at r1 that pays 250/500 Gold for each map piece collected, cost 2/2.
- **#8 Privateers' Pact replaces Letters of Marque.** It gives `heroStat diplomacyEfficiencyPerBonus` +0.25/+0.50, the vanilla dungeon_16 shape, cost 3/3.

Other deviations:
- **#18 Powder Kegs** uses `modifierSet outDmgMods ability 0.15/0.30` on every Cove SID. The installed Core gives its ability damage dealers the generic `ability` tag, and there is no Cove-only tag.
- **#33 Star Charts** gives `astrologyExp` 500/1000 and uses the human_34 icon.

## Kit rules (`lawRules`)

All three apply to the faction's creatures:
- 12 Boarding Actions: `counter_state` left0, melee, 10/20%.
- 26 Broadside: `turn_state` unacted_target, ranged, 10/20%.
- 31 Keelhaul: `wall_slam`, 10/15%.

## Checks

- Local `law_tree_problems`: 0 errors, 0 warnings.
- `collect_law_rules`: passes.

## Plugin levers

New file `OfflineUnlockMod/Homm3CoveLawHooks.cs`.
- Law ranks come from the owning player's data side (`TryResolveSide` and `CustomLawRank`).
- They are cached for 1.5 s per side.
- It fails closed: a missing law or a failed read gives level 0.

| Law | Where | What it does |
|---|---|---|
| #5 Spyglass Watch | `Homm3CoveTreasureRuntime.cs:238`, `Homm3CoveTreasureAi.cs:63` | Search radius is 3, +1/+2 hexes with the law (`AreasInSearchRange` takes a radius). |
| #9 Finder's Fee | `Homm3CoveTreasureRuntime.cs:587` | Collect queues the Gold. `FlushFindersFees` at `:599` pays it through `Homm3CovePlunderHook.Grant`. `FlushAiPayouts` in TreasureAi calls the flush. |
| #20 Quick Shovels | `Homm3CoveTreasureDig.cs:142`, `:193`; `Homm3CoveTreasurePopup.cs:280` | L1: digging needs half a day's movement. L2: it also spends only half (new `TrySetMovement`). The refusal banner, the popup dig fact and the `movementSpent` flag follow the law level. |
| #27 King's Ransom | `Homm3CoveTreasureDig.cs:236`, `:274` | Dug Gold and resources +20/40/60%, applied at payout. |
| #32 Cartographers' Guild | `Homm3CoveTreasureRuntime.cs:623` | `LeadCount` and `FalseLeadStart` remove 1/2 false leads. They are used by the chart, the markers, the picks, the AI and the popup. |

## Family indices reused for new effects

Retire the old profiles for **18, 25, 27 and 28**. Index 13 (Boarding Hooks) is kept as it was.

## Shared-file asks

- Retire the family profiles for 18, 25, 27 and 28 in `Homm3CustomLawEffectProfiles.cs`.
- Translate the new law names and texts for 5, 7, 8, 9, 20, 22, 32, 33, 18, 27, 28 and 25.

## Not built, or limits

- King's Ransom does not raise the AI's fallback payout (`PayAi` when the hero is gone pays `contents.Total()`). It is a rare edge case.
- Spyglass Watch only changes how far heroes search. The marker layer's area sweep is unchanged.
