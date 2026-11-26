# Castle law build (2026-11-21)

Data: `custom_factions/law_overrides/homm3_castle.json` (27 laws, `lawTree`, `lawBuffs`). No `lawRules`.
Checks run: column roles, Riches leads, 2-4 per column, duplicate effects and vanilla-icon rules (`custom_law_tree_layout` helpers against the live Core); all pass. Not compiled.

## Tree changes from the draft

- **War College (#7)** is built natively as `heroStat expPerBonus 0.10/0.20` (cost 4/4, icon `unfrozen_2`): "Your heroes gain +10%/+20% experience." The Strategem-battles-only version needs a battle-end experience hook that does not exist yet. This is the closest real version, and it is no longer an (S) law.
- **Knightly Training (#6)** keeps the shipped Mirth homm4 icon pair.
- Otherwise the tree is as drafted:

  | Rank | Kingdom | Army |
  |---|---|---|
  | r0 | 3, 2, 33, 5 | 4, 10, 34 |
  | r1 | 1, 14, 6, 22 | 11, 17 |
  | r2 | 16, 21, 15, 26 | 23, 20 |
  | r3 | 7, 9, 28 | 24, 8, 32 |
  | r4 | 29, 27, 31 | 30, 12 |

- Disabled: 13, 18, 19, 25. Indices 3, 16 and 29 are `{"enabled": false}` (Riches generated).

## Law buffs

- `h3_law_castle_holy_crusade_1/_2`:
  - Clone of `fraction_law_demon_6_unit_bonus`.
  - `infinite`, with `outDmgModsByTargetTags` `h3_kit_undead`/`h3_kit_demon` at 0.05/0.10.
  - Granted natively by `battleSubskillBonus unit_buff` on all 21 Castle sids.
- `h3_law_castle_drilled_effect_1/_2`:
  - Clone of `jaw_buff_2_upg`.
  - `maxDuration 1`, `outAllDmgMod` 0.10/0.20.
  - Added by the plugin.
- `h3_law_castle_ambushed_effect_1/_2`:
  - Clone of `magic_ice_bolt_effect_0`.
  - `maxDuration 1`, tags `negative`, Initiative and Defence -2/-4.
  - Added by the plugin.

## Plugin levers

All paths are under `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`.

- `Homm3CastleEliteStrategemRuntime.cs:160`: registers the new hooks file.
- `Homm3CastleEliteStrategemRuntime.cs:266` **Grand Strategem (#31)**:
  - The neutral-only gate also accepts a `Type_Hero` opponent with a hero when all of these hold:
    - it is not a siege (`arenaLogicSid` has no "siege")
    - the law is at level 1 or higher
    - for Ambush, the law is at level 2
  - Garrisons and towns stay excluded.
- `Homm3CastleEliteStrategemRuntime.cs:295` and `:346` **Standing Orders (#5)**: the token is still claimed before the mutation, then put back after a successful apply.
- `Homm3CastleEliteStrategemRuntime.cs:349`: on a successful apply, notes the battle for the hooks file.
- `Homm3CastleLawHooks.cs` (new):
  - Postfix on `BattleLogic.Init`: finds the owner's side wrapper on the clone.
  - RoundStarted postfix, round 1, once per battle (lines 255 and 258):
    - **Drilled Deployment (#20)** buff on the owner's stacks.
    - **Ambush Doctrine (#8)** buff on the enemy stacks of an Ambush battle.
- `Rank(...)` reads `CustomLawRank` from the `TransferSide`, then from its `logicHero`. Every path fails closed.

## Family indices reused for new effects

- New effects: 2, 6, 22, 33, 34.
- Same effect as the shipped row: 15, 21, 27, 28.

## Shared-file asks / coordinator checks

- (S) rows #5, #8, #20 and #31 have `"bonuses": []` at every level, because identical zero anchors would trip the duplicate-effect check. Please confirm that the overlay loads empty-bonus custom laws; there are runtime-owned precedents.
- Retire the family profiles for 2, 6, 22, 33 and 34.

## Not built / runtime risks

- War College is native; see above.
- Grand Strategem Spread Out / Compress against a hero army re-split or merge that hero's army through the same `TransferBattle` write-back as for neutrals. Survivors therefore return to that hero in the new split. This needs a live check.
