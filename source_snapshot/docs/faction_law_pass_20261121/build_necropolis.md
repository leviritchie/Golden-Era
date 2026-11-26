# Necropolis law build (2026-11-21)

Data: `custom_factions/law_overrides/homm3_necropolis.json` (27 laws, `lawTree`, `lawRules`).
Checks run:
- `collect_law_rules` loads Culling and Death's Toll.
- Column roles, Riches leads, 2-4 per column, duplicate effects and vanilla-icon rules all pass.

Not compiled.

## Tree changes from the draft (owner answers applied)

- **Bone Harvest (#12, r3 kingdom, (S), cost 5)** replaces Lords of the Dead: "Your heroes' Necromancy also raises Skeletons from your own army's fallen living creatures, at the Basic share (5%)."
- **Grave Chill (#26, r2 army, cost 6)** replaces Legion Without Banner. Data: `unitStat receiverAllegiance enemy initiative -1`, with the `dungeon_20` icon.
- **Death Grip (#13)**: the shipped runtime row is copied exactly, including its receivers and text.
- Unearthed Graves (#8) and Deathly Silence (#34) are built as approved.

| Rank | Kingdom | Army |
|---|---|---|
| r0 | 3, 7, 31 | 4, 5 |
| r1 | 1, 14, 8, 6 | 10, 11, 13 |
| r2 | 16, 15, 21, 9 | 24, 17, 26 |
| r3 | 12, 28 | 23, 20, 32 |
| r4 | 29, 27, 30, 34 | 25, 19 |

Disabled: 2, 18, 22, 33. Indices 3, 16 and 29 are `{"enabled": false}`.

## Rules (C)

- **Culling (#25)**: `damage_vs_hp` 5/10%, below 50. Zero anchor: `outAllDmgMod 0.0`.
- **Death's Toll (#19)**: `death_toll` 3/5%, cap 15/25. Zero anchor: `inAllDmgMod 0.0`, distinct from Culling's.
- Both have receivers: faction.

## Plugin levers (`Homm3SkeletalNecromancyProbe.cs`)

- `:39`: law constants. `:364` `NecropolisLawRank(...)` reads the `TransferSide`, then its `logicHero` (fail closed).
- `:206` and `:393` **Unearthed Graves (#8)**: a hero-less `Type_Garnison` winner raises `h3_skeleton` at the Basic 5%. The law owner is read in this order:
  1. directly from the side
  2. from its side id when that id is unique in the battle, through `Homm3BattleUnitLawOwnerRegistry.TryResolveGlobalDataSide`
- `:249` **Necromancy Amplifier (#7)**: share +2%/+4% (heroes only).
- `:256` **Bone Harvest (#12)**: adds the winner's own lost living value at 5% before the floor. The existing blocklist (undead, constructs, elementals) defines "living".
- `:262` **Dark Ascension (#30)**: also grants `h3_wight` worth 5%/10% of the enemy fallen. The battle counts as a success if either reward lands.
- `:432` **Skeleton Transformer (#9)**: when neither reward subskill applies, the reward becomes `h3_skeleton_upg`.

## Family indices reused for new effects

- New effects: 6, 19, 21, 25.
- Same effect as the shipped row: 13, 15, 27, 28, 34. These keep the shipped homm4 icon pairs for 13, 27 and 34.

## Shared-file asks / coordinator checks

- (S) rows #7, #8, #9, #12 and #30 have `"bonuses": []`. Please confirm that the overlay loads empty-bonus laws.
- Retire the family profiles for 6, 19, 21 and 25; the old Dread/25 profile must not fire on Culling.

## Not built / runtime risks

- The Unearthed Graves owner resolution is a heuristic: side id to global data side. It refuses whenever the id is ambiguous.
- The garrison write-back of granted stacks (`AddSpawnedUnit` on a garrison `TransferSide`) is runtime-unproven.
- Map garrison buildings also count as "garrisons".
