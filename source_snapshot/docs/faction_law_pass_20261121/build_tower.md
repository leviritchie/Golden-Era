# Tower law tree: build notes (2026-11-21)

Spec: `tower.md`, REVIEW sections 2-4 and 6, BUILD_BRIEF. Not compiled, not installed, not committed.

## Files

- `custom_factions/law_overrides/homm3_tower.json`: 27 laws defined; 3/16/29 are left to the Resource Riches generator.
- `custom_factions/homm3_tower.json`: manifest `factionSkillName` is now "Artificing" (owner).
- New `OfflineUnlockMod/Homm3TowerLawHooks.cs`.
- `OfflineUnlockMod/Homm3TowerArtificingRuntime.cs` and `Homm3TowerArtificingPicker.cs`: law levers, each marked `// law pass 2026-11-21`.

## Tree (cost per level)

| Rank | Kingdom | Army |
|---|---|---|
| r0 | 3 Resource Riches I; 5 Scrying Lenses 2/2; 33 Cloud Observatory 2/2 | 4 Elite Gremlins 3/2; 10 Elite Gargoyles 3/2; 12 Unravelling Wards 3 |
| r1 | 1 Tax Collectors 2/2; 14 Mining: Gems 2/2; 6 Wall of Knowledge 2/2/2; 7 Essence Distillery 3/3 | 11 Elite Golems 3/2; 17 Elite Mages 3/2 |
| r2 | 16 Resource Riches II; 2 Library of the Clouds 3/3; 8 Twin Grafts 5; 21 Transmutation Ledger 4/2/2 | 23 Elite Genies 3/2; 26 Golem Factory 4 |
| r3 | 9 Warded Grafts 4; 34 Wizards' Cadence 4 | 24 Elite Nagas 3/2; 13 Reactive Wards 3/3; 20 Specialist Arcana 4; 15 Wizards' Patronage 5/5 |
| r4 | 29 Resource Riches III; 27 High Arcana 3; 28 Grand Schematic 3/3; 31 Arcane Battery 3 | 30 Elite Giants 3/2; 32 Wards of the Magi 5 |

Cost per rank (Resource Riches excluded): 22 / 30 / 30 / 33 / 25 = 140. `custom_law_tree_layout.law_tree_problems` returns 0 problems.

Changes from the draft:
- Unravelling Wards (#12, enemy `inComingBuffDuration -1`) replaces Overclocked Spellworks.
- Twin Grafts is at r2.
- Wizards' Patronage (#15, `unitUpgradingDiscount`) is in the **army** column. The validator classes `unitUpgradingDiscount` as army (see the asks below).

## Plugin levers

Each (S) law carries a native zero-strength anchor so the validator sees a distinct effect: 5 `viewRadius 0`, 7 `expPerBonus 0.0`, 8 `manaBonus 0`, 9 `movementBonus 0`, 28 `defence 0`. Every hook reads the level through `Homm3CustomFactionLawRuntime.CustomLawRank(logicHero, idx, "homm3_tower")` and fails closed to 0.

| # | Law | Lever |
|---|---|---|
| 5 | Scrying Lenses | `Homm3TowerLawHooks.ObservationChance`: +5 points per level, capped at 100. Used at `Homm3TowerArtificingRuntime.cs:1227`. The picker text shows the bonus (`Homm3TowerArtificingPicker.cs:652`, `ScryingNote`). |
| 7 | Essence Distillery | `EssenceAward`: essence x(1 + 0.25L), rounded down; MaxEssence still caps it. At `Runtime.cs:1386`. |
| 8 | Twin Grafts | `SlotsFor(rank, hero)`: the second slot opens from Basic. Used at `Runtime.cs:354` (battle ActiveGrafts), `:737` (map cache, keyed on slots too) and `:1548` (TryGraft). The picker uses it at 4 call sites. |
| 9 | Warded Grafts | `Runtime.cs:939`: round starts after the first call `RestoreWardedGrafts()` (`:1065`), which re-adds a graft buff missing from a living carrier when its side's hero owns the law. |
| 28 | Grand Schematic | `GraftCost`: cost x(1 - 0.2L), rounded to 5, minimum 5. At `Runtime.cs:1588` and in both picker cost sites (`Picker.cs:354`, `:451`). |

## Family indices reused (the coordinator should retire these family rows for Tower)

2, 15, 21, 27, 28, 34. Index 13 is kept (Reactive Wards). The law-pass families on 18, 19, 22 and 25 are dormant here: those indices are not placed (`enabled: false`).

## Not built / caveats

- With the Artificing policy **disabled**, the overlay (around `apply_release_core_overlay.py` line 19619) would label the Arcane Battery text "Artificing", because the manifest name changed. `validate_homm3_tower_arcane_battery_contract` expects "Arcane Battery" in that case. The policy is enabled today, and the contract passes against the installed Core ("faction skill: Artificing").
- `validate_homm3_tower_artificing_contract.py` fails on two needles in shared files (`Homm3RuntimeMechanicHooks.cs` now passes `__1`/`showNotification`). These failures were already there, are not from this pass, and the shared files were not touched.

## Shared-file asks

1. `tools/release_port/custom_law_tree_layout.py`: add `unitUpgradingDiscount` to `_KINGDOM_BONUS_TYPES`. Then #15 can move to the kingdom column.
2. Law families must skip Tower indices 2, 15, 21, 27, 28 and 34.
