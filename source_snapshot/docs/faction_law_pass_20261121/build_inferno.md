# Inferno law build (2026-11-21)

Data: `custom_factions/law_overrides/homm3_inferno.json` (27 laws, `lawTree`, `lawRules`, `lawBuffs`).
Checks run:
- `collect_law_rules` loads Hellforged.
- Column roles, Riches leads, 2-4 per column, duplicate effects and vanilla-icon rules all pass.

Not compiled.

## Tree changes from the draft

- **Frenzy (#22)** (`heroStat moral 1`) moved from r2 army to **r1 kingdom**: the validator classes heroStat as a hero law, which goes in the kingdom column.
- **Hellfire Brands (#26)** follows the owner change: `unitStat modifierSet outDmgMods overTime_effect 0.25/0.5` on the 21 Inferno sids, cost 2/2. Text: "Damage over time dealt by Inferno creatures increases by 25%/50%."

| Rank | Kingdom | Army |
|---|---|---|
| r0 | 3, 2, 5 | 4, 10, 26 |
| r1 | 1, 14, 6, 22 | 8, 11, 17 |
| r2 | 16, 15, 7, 21 | 23, 24 |
| r3 | 9, 20, 28 | 12, 32 |
| r4 | 29, 27, 34, 33 | 30, 31 |

Disabled: 13, 18, 19, 25. Indices 3, 16 and 29 are `{"enabled": false}`.

## Rules and buffs

- `lawRules`, Hellforged (#32):
  - `damage_vs_buff` 10% against `h3_kit_inferno_burning_effect`, `h3_kit_inferno_burning_lesser_effect` and `h3_kit_inferno_scorched_effect`.
  - Receivers: faction.
  - Zero anchor: `outAllDmgMod 0.0` on the Inferno sids.
- `h3_law_inferno_vanguard_effect_1/_2`:
  - Clone of `jaw_buff_2_upg`.
  - `maxDuration 1`, `outAllDmgMod` 0.15/0.30.
  - Added by the plugin.

## Plugin levers (`Homm3InfernoGatingRuntime.cs`)

- `:65`: law constants. `:326` `LawRank(...)` (fail closed). `:153`: a DataHero to LogicHero cache, filled in `ResolveDataHero`.
- `:368` **Legion Gate (#7)**: `ResolveAllowedSlots` adds +1. This works on the map strip and at battle start; both resolve through `ResolveDataHero(logicHero)`.
- `:563`: per-side ranks are read when a gating side is armed.
- **Open Gate Rites (#9)**:
  - L1 grants the action natively (`battleSubskillBonus hero_ability skill_faction_homm3_inferno_ability_open_gate`) and sets `OpenGate` without the subskill.
  - `:951` L2 refunds 1 Focus after the cast (`Homm3FocusNativeAdapter.TryGrantFocusToSide`).
- `:1033` **Gate Sigils (#5)**:
  - L1: enemy-half entry at any skill rank.
  - L2: prefers open hexes next to a living enemy stack, falling back to the whole enemy half.
- `:1085` **Brimstone Vanguard (#31)**: the vanguard buff on the arriving stack.
- `:1088` **Infernal Arrival (#8)**: `h3_kit_inferno_burning_lesser_effect` on adjacent enemy stacks, with the arriving stack as caster.
- Helpers are at `:1110` onward. Adjacency = distance within the smallest hex spacing x1.1.

## Family indices reused for new effects

- New effects: 2, 6, 15, 22, 33, 34.
- Same effect as the shipped row: 21, 27, 28. These keep the shipped homm4 icon pairs for 21, 22, 27 and 34.

## Shared-file asks / coordinator checks

- (S) rows #5, #7, #8 and #31 have `"bonuses": []`. Please confirm that the overlay loads empty-bonus laws.
- Retire the family profiles for 2, 6, 15, 22, 33 and 34.

## Not built / closest versions

- **Open Gate Rites L2** is a refund after the cast, not a lower cost: the action still needs 2 Focus to start.
- A hero who has both the subskill and the law may see Open Gate offered twice (native grant plus subskill). Both casts gate the same pending stacks.
- The Inferno laws act only in battles where Gating reserved stacks; Legion Gate also raises the map strip cap.
