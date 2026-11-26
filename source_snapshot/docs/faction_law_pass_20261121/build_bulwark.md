# Bulwark law tree: build notes (2026-11-21)

Spec: `bulwark.md`, REVIEW sections 2-4 and 6, BUILD_BRIEF. Not compiled, not installed, not committed.

## Files

- `custom_factions/law_overrides/homm3_bulwark.json`: 27 laws defined; 3/16/29 are left to the Resource Riches generator. It also has 7 lawBuffs.
- New `OfflineUnlockMod/Homm3BulwarkLawHooks.cs`.
- `OfflineUnlockMod/Homm3BulwarkRunesRuntime.cs`: Rune levers, each marked `// law pass 2026-11-21`.

## Tree (cost per level)

| Rank | Kingdom | Army |
|---|---|---|
| r0 | 3 Resource Riches I; 2 Frontier Scouts 2; 33 Clear Mountain Sky 1/2 | 5 Elite Kobolds 3/2; 4 Elite Rams 3/2; 7 Runes Carved in Advance 3/3 |
| r1 | 1 Tax Collectors 2/2; 14 Mining: Gems 2/2; 6 Stone Bastions 2/2/2 | 10 Elite Snow Elves 3/2; 8 Clan Oath 3/3; 17 Hold the High Ground 2/2/2 |
| r2 | 16 Resource Riches II; 20 Mountain Homesteads 3/3; 28 Kobold Work Crews 3 | 9 Elite Yetis 3/2; 26 Elite Shamans 3/2; 11 Winter's Bite 4 |
| r3 | 21 Prosperous Holdings 4/2/2; 15 Primal Study 3; 25 Winter Stores 3/3 | 23 Elite Mammoths 3/2; 12 Shared Runes 4; 31 Shield Wall 3/3 |
| r4 | 29 Resource Riches III; 34 Rune-Fed Focus 3; 27 Mountain Passes 5/5 | 24 Elite Jotunns 3/2; 30 Elder Runes 5; 32 Stand Unbroken 4 |

Cost per rank: 22 / 31 / 25 / 32 / 30 = 140. The layout validator returns 0 problems.

Remaps: Elite Rams is #4 and Elite Shamans is #26. Mountain Passes is flat movement +15/+30, because `movementBonus` takes points, not %.

### lawBuffs

All buff ids use buffFile `units_buffs_nature.json`.
- **`h3_law_bulwark_rune_level_10/11/12`** (Elder Runes):
  - clone of `sunlightCavalry_buff_1`, infinite, `addition: data`;
  - +2 Attack / +2 Defense / +1 Speed (12 carries the haste tags);
  - tags include `homm3_bulwark_runes`.
  - The Rune runtime dispatches them itself, not through a law bonus.
- **`h3_law_bulwark_shield_wall_1/2`** (#31):
  - clone of `skill_formation_1_unit_bonus` (infinite, hidden donor);
  - one `unit_skip` action that gives `h3_law_bulwark_shield_wall_attack_1/2` (+2/+4 Attack, 1 round);
  - granted by `battleSubskillBonus ["unit_buff", id]` to all 21 Bulwark sids.
  - The overlay's automatic `bonus_buff_infos` row uses the defaults: duration 1, charges 1, ally. This matches vanilla `fraction_law_demon_6_bonus` over an infinite buff, so no spec override is needed.

## Plugin levers (Runes)

Each (S) law carries a native zero-strength anchor: 7 `outAllDmgMod 0`, 8 `inAllDmgMod 0`, 12 `hpPerc 0`, 30 `modifierSet inDmgMods basic_attack 0`. The laws are read from the stack owner's logic hero; `TryResolveEligibleStack` now also returns it (`:1409`). They are cached on the stack state (`:105`), so the cached-rank path keeps the last live read.

| # | Law | Lever |
|---|---|---|
| 30 | Elder Runes | `TryApplyGain` cap +3 (`:1175`). Thresholds 10/11/12 continue the cycle (Attack/Defence/Speed). `BuffSidForLevel` maps 10-12 to the law buffs (`:235`). |
| 8 | Clan Oath | `:1177`: Defend 3 → 4/5; at L2, first damage in an action 2 → 3 (`Homm3BulwarkLawHooks.DefendGain` / `DamageGain`). |
| 7 | Runes Carved in Advance | `Homm3BulwarkLawHooks` patches `BattleLogic.Init` and the round hub's RoundStarted. At round 1, every unit on the grid goes through `Homm3BulwarkRunesRuntime.ApplyCarvedInAdvance` (`:1280`), which grants min(L, cap) through the normal gain path, so the threshold buffs dispatch. A stack the round-1 grant missed (summoned later) gets the levels with its first Rune event (`:1182`). Each stack is granted once (`CarvedChecked`). |
| 12 | Shared Runes | `:1226`: each crossed 3/6/9/12 gives +1 to every adjacent friendly stack (`ShareRunes`, `:1259`). Adjacency is all six neighbours, read from the battle grid with the pathfinder's hex distance (`Homm3BulwarkLawHooks.AdjacentFriendlyUnits`). Shared gains never share again. The ally must itself be Rune-eligible (Bulwark-skill hero, not a war machine). |

The law hooks register from `Homm3BulwarkRunesRuntime.TryRegister` (`:165`), so `Plugin.cs` is unchanged. If the grid surfaces are missing, registration fails closed: Carved falls back to each stack's first Rune event, and Shared Runes does nothing.

Validators run (read-only):
- `validate_homm3_bulwark_runes_runtime_contract.py`: PASS.
- `validate_homm3_bulwark_runes_correlation_fixture.py`: PASS.
- `validate_native_hook_safety_contract.py`: OK.

## Family indices reused (the coordinator should retire these family rows for Bulwark)

2, 6, 15, 21, 25, 27, 28, 34. Index 13 is retired (not placed).

## Not built / caveats

- Winter's Bite has no terrain qualifier lever. It uses the `actionArea allied` fallback (all battles).
- AttackBonusForLevel / DefenseBonusForLevel / SpeedBonusForLevel now count up to level 12.

## Shared-file asks

1. Counter doctrine row 13 (`Homm3CounterattackDoctrineMutationRuntime.cs`): drop Bulwark.
2. Law families must skip Bulwark indices 2, 6, 15, 21, 25, 27, 28 and 34.
3. Alternative to the lawBuffs rows: the overlay could extend its `homm3_bulwark_rune_level_N` generator to 1..12. In that case, set `Homm3BulwarkLawHooks.ElderBuffSidPrefix` to `homm3_bulwark_rune_level_` and drop the three lawBuffs.
