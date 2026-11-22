# Fortress: ability variety draft (2026-11-21)

Draft only. Nothing here is built. Trade axis (unchanged):

- **Hunter** (striker): fast, single-target burst against its one mark.
- **Warden** (ward): durable control and retaliation, whose value is not the damage it deals.

Each Hunter below picks its mark by a different battlefield fact:

- isolated;
- unhurt;
- higher tier;
- petrified;
- pinned;
- chosen.

Each Warden controls in a different way:

- curse;
- slow;
- Focus denial;
- a zone;
- killing on retaliation;
- area poison;
- taunt.

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| Damage per hex (`gallop` 0.03 to 0.07): Run Down, Darting Strike, Pounce, Stampede, Swoop, Lunge | Gnoll upg, Serpent Fly alt, Basilisk alt, Gorgon alt, all 3 Wyverns, Hydra alt | 8 rows. The same trigger, only re-numbered. |
| Alert (`counters` 2) | Dragon Fly, Greater Basilisk, Mighty Gorgon, Wyvern Monarch | 4 Wardens with the same generic retaliation card. |
| Speed debuffs: Bog Curse (-1), Crippling Shot (-2), Numbing Bite (-1), Numbing Venom (-2) | Gnoll alt, Lizard Warrior, Greater Basilisk, Wyvern Monarch | 4 Wardens whose control is the same stat. |
| `resist`: Tough Hide, Scaled Shield, Elusive, Stony Hide, Iron Hide, Leathery Wings | 3 Gnolls, Lizard Warrior, Dragon Fly, Greater Basilisk, 3 Gorgons, 3 Wyverns | 12 generic damage-reduction rows. |
| "+x% strike" actives: Aimed Shot, Flail Frenzy, Gore, Devour | Lizardman, Gnoll upg, Gorgon alt, Hydra alt | Damage multipliers with nothing else. Devour also has no counterattack. |
| Long Thrust equivalent: Flame Spit (`reach_strike`) | Basilisk alt | A banned pattern. |
| Dive anywhere: Thunder Dive | Wyvern alt | The same as Stronghold's Stoop and the old Spectral Pounce. |
| Handcuffs + Burn the Bound | Basilisk alt | An old redesign leftover with no HoMM3 root, wired to its own debuff. |
| `when_damaged_adjacent_debuff` x2 (Bog Curse, Acid Blood) | Gnoll alt, Chaos Hydra | Same trigger, different debuff. Kept: they are now the only two in my three factions (Bulwark's Frost Rune is cut), and they differ in kind (Speed versus Damage dealt). |

## 2. Proposed kits

| Unit | Card | P / A | Card text | How it is built | Replaces |
|---|---|---|---|---|---|
| Gnoll | Scavenge | A 1/2 | Devours a corpse on an adjacent hex and restores Health equal to 50% of one creature's maximum Health. This does not revive fallen creatures. | new keyword `scavenge`: corpse-eating cast from the olgoi line (`olgoi_l.json`, `destroy_corpse_and_heal`), heal value set to 0.5 of one creature, range 1 | Tough Hide |
| Gnoll Marauder (Hunter) | Scavenge | A 1/2 | (as Gnoll) | `scavenge` (line identity) | Tough Hide |
| | Pick Off | P | Deals +30% Damage to an enemy that has no friendly creature adjacent to it. | new plugin rule `isolated` percent 30 | Run Down, Flail Frenzy |
| Gnoll alt (Warden) | Scavenge | A 1/2 | (as Gnoll) | `scavenge` (line identity) | Tough Hide |
| | Shorten Shadow | A 1/- | (old text) | kept (`keep_ability`) | - |
| | Bog Curse | P | Whenever this creature takes Damage, all adjacent enemies have -1 Speed until the end of the next round. | kept | - |
| Lizardman | Venom Shot | A 1/1 | Performs a Ranged attack and poisons the target for 2 rounds. At the start of its turn the poisoned creature takes 4 Magic Damage plus 1 per creature in this stack. | `shot` + `h3_kit_fortress_lizard_venom_effect` (moved down from the alt) | Aimed Shot |
| Lizard Warrior (Warden) | Skirmisher | P | Receives no penalty in Melee range, dealing full Damage. | kept | - |
| | Crippling Shot | A 1/1 | Performs a Ranged attack that deals 50% Damage. The target has -2 Speed until the end of the next round. | kept (the faction's one Speed-debuff shot) | Scaled Shield |
| Lizard alt (Hunter) | Sharpshooter | P | (shared keyword text) | kept | - |
| | Venom Shot | A 1/1 | (as Lizardman) | kept (line identity) | - |
| | Giant Slayer | P | Deals +5% Damage for each tier the target is above this creature. | native `damagePerDeltaLevel` 0.05 on the unit stats (donor trick_demon "Topple the Strong!", `damagePerDeltaLevel` 0.03) | - |
| Serpent Fly | Dispel Strike | A 1/- | (old text) | kept (HoMM3 dispel) | - |
| Dragon Fly (Warden) | Weakening Dispel | A 1/- | (old text) | kept (HoMM3 weakness + dispel) | - |
| | Droning Wings | P | Adjacent enemy creatures gain no Focus. | `stat_aura` radius 1, enemy, stats `{blockEnergyRegen: true}` (donor stat: succubus_debuff_3, magic_despair_effect_old) | Alert, Elusive |
| Serpent Fly alt (Hunter) | Dispel Strike | A 1/- | (old text) | kept | - |
| | No Retaliation | P | (shared keyword text) | kept | - |
| | First Sting | P | Deals +30% Damage to an enemy stack that has lost no creatures this battle. | new plugin rule `unhurt` percent 30 | Darting Strike |
| Basilisk | Stone Gaze | A 2/- | Spend 2 Focus to petrify an enemy for 1 round. | kept (HoMM3 identity) | - |
| Greater Basilisk (Warden) | Stone Gaze | A 2/- | (as Basilisk) | kept | - |
| | Lingering Gaze | P | An enemy that ends its movement next to this creature has -2 Initiative until the end of the next round. | new keyword `glare_aura`: aura radius 1 on enemies carrying a hidden buff whose action is `unit_end_move` (allegiance self), which applies `h3_kit_fortress_glared_effect` (-2 Initiative, 2 rounds) to itself. Donor of the trigger shape: magic_nairas_kiss_effect_0 (`unit_end_move` on the moving unit's own buff) | Stony Hide, Alert, Numbing Bite |
| Basilisk alt (Hunter) | Stone Gaze | A 2/3 | (as Basilisk, cooldown 3) | new keyword `petrify_gaze`: clone of h3_basilisk ability 0 (a `keep_ability` cannot reach the base row's view) | Handcuffs |
| | Shatter | P | Deals +50% Damage to a petrified enemy. | `runtime damage_vs_buff` percent 50, buffs = the basilisk petrify buff sid plus `medusa_stone` | Pounce, Burn the Bound, Flame Spit |
| Gorgon | Iron Hide | P | Takes -15% Melee Damage. | kept | - |
| | Unstoppable | P | Immune to effects that reduce Speed or prevent movement. | kept | - |
| Mighty Gorgon (Warden) | Iron Hide | P | Takes -20% Melee Damage. | kept | - |
| | Unstoppable | P | (as Gorgon) | kept | - |
| | Death Stare | A 2/- | (old text) | kept (HoMM3 identity) | - |
| | Withering Gaze | P | Counterattacks also kill 1 creature in the attacking stack. | new keyword `counter_kill`: the unit's counterAttacks dealer gains `kill_stacks ["1"]` (verified donor: h3_gorgon_upg Death Stare carries `kill_stacks`) | Alert, Baleful Presence |
| Gorgon alt (Hunter) | Iron Hide | P | (as Gorgon) | kept | - |
| | Unstoppable | P | (as Gorgon) | kept | - |
| | Corrosive Breath | P | Basic attacks and counterattacks corrode the target. It has -3 Defense until the end of the next round. | kept | - |
| | Lock Horns | A 2/2 | Performs a Melee attack. The target cannot move until the end of the next round. | `melee_strike` mult 1.0 counter true + buff `h3_kit_fortress_locked_effect` = clone of `ent_root` (h3_dendroid_soldier), maxDuration 2 | Stampede, Gore |
| Wyvern | Leathery Wings | P | Takes -20% Ranged Damage. | kept | - |
| | Tail Sting | A 2/2 | Performs a Melee attack and poisons the target for 2 rounds. At the start of its turn the poisoned creature takes 6 Magic Damage plus 3 per creature in this stack. | `melee_strike` mult 1.0 + new buff `h3_kit_fortress_wyvern_sting_effect` (wyvern venom clone, 6 + 3) | Swoop |
| Wyvern Monarch (Warden) | Leathery Wings | P | (as Wyvern) | kept | - |
| | Venomous Sting | P | Basic attacks and counterattacks poison the target for 2 rounds. At the start of its turn the poisoned creature takes 10 Magic Damage plus 5 per creature in this stack. | kept (HoMM3 identity) | - |
| | Toxic Cloud | A 2/3 | Poisons every adjacent enemy with Wyvern Venom for 2 rounds. Does not end this creature's turn. | `kw_rally` envelope (minos_upg_alt rumble, `actionCost` 0) with `castTarget_` enemy and buff `h3_kit_fortress_wyvern_venom_effect`; new keyword `venom_burst` | Swoop, Alert, Numbing Venom |
| Wyvern alt (Hunter) | Leathery Wings | P | (as Wyvern) | kept | - |
| | No Retaliation | P | (shared keyword text) | kept | - |
| | Quarry | A 1/1 | Marks an enemy creature as this stack's quarry until it dies or another is marked. This creature deals +35% Damage to its quarry. Does not end this creature's turn. | new keyword `mark_cast` (enemy-target free cast: the gnoll Shorten Shadow cast envelope with `actionCost` 0, visible debuff `h3_kit_fortress_quarry_effect`, no stats) + new plugin rule `quarry` percent 35 | Swoop, Thunder Dive |
| Hydra | Swipe card, No Retaliation, Whirlwind of Heads | P / alt attack | (as now) | kept (HoMM3 identity) | - |
| Chaos Hydra (Warden) | Swipe card, No Retaliation, Whirlwind of Heads | | (as Hydra) | kept | - |
| | Many Heads | P | Can counterattack unlimited times per round. | kept (now the only unlimited counterattack in my three factions) | - |
| | Acid Blood | P | Whenever this creature takes Damage, all adjacent enemies deal -25% Damage until the end of the next round. | kept | - |
| | Menacing Hiss | A 3/3 | All enemies within a 2-hex radius can target only this creature until the end of the next round. Does not end this creature's turn. | kept (now the only taunt in my three factions) | - |
| Hydra alt (Hunter) | Swipe card, No Retaliation, Whirlwind of Heads | | (as Hydra) | kept | - |
| | Regeneration | P | At the start of its turn, restores Health equal to 50% of one creature's maximum Health. This does not revive fallen creatures. | kept | - |
| | Devour | A 3/3 | Every head bites one enemy: performs a Melee attack on that enemy only, dealing +50% Damage, and this creature restores Health equal to half the Damage dealt. | `melee_strike` mult 1.5 counter **true**, pattern `attack_single_x100` + mechanic `vampirism ["0.5"]` (donor: the magic_fatal_decay `vampirism` values layout) | Lunge, Devour (+80%, no counterattack) |

What each card asks of the player:

- **Hunters:**
  - Pick Off wants the Gnoll Marauder on enemy flanks and stragglers.
  - First Sting wants fresh stacks.
  - Giant Slayer wants high tiers.
  - Shatter wants a petrify first: Stone Gaze from this stack or any Basilisk or Medusa.
  - Lock Horns pins a runner for the rest of the army.
  - Quarry is a declared mark that the player keeps re-targeting.
  - Devour is the Hydra choosing one enemy instead of everything around it, and sustaining itself through the bite.
- **Wardens:**
  - Droning Wings sits next to casters.
  - Lingering Gaze punishes anyone who walks up.
  - Withering Gaze makes attacking the Mighty Gorgon cost creatures.
  - Toxic Cloud rewards being surrounded.
  - Menacing Hiss pulls attacks onto the Hydra.

**Gallop: 8 to 0. Alert: 4 to 0. Speed debuffs: 4 to 2. Resist: 12 to 6, and the 6 are the Gorgon and Wyvern line identities.**

## 3. New mechanics needed

- **Keyword `scavenge`** (Gnoll line):
  - Corpse cast at range 1 with `destroy_corpse_and_heal`. The donor is the olgoi line ability, `olgoi_l.json` and `olgoi_upg_l.json`: the vanilla corpse-eater, verified in the Core to carry the mechanic.
  - Values: heal 50% of one creature, no revive.
  - Different from Necropolis corpse use: it heals only, raises nothing, and takes the corpse away from enemy necromancy.
- **Plugin rule `isolated`** (Pick Off):
  - Caster side, +percent when the receiver has 0 adjacent creatures of its own side.
  - Uses `CountAdjacentAllies(receiver)` from the Avenger runtime unchanged.
  - The mirror of Stronghold's `flank`: same helper, opposite condition, other faction. Both can ship from one rule kind with a `mode` field.
- **Plugin rule `unhurt`** (First Sting):
  - Caster side, +percent when the receiver's stack health equals the largest health seen for it.
  - Uses `TrackFullHealth` from `loss_fury`. A revived or healed-to-full stack counts as unhurt again, which is intended.
- **Native `damagePerDeltaLevel`** (Giant Slayer): a stat on the unit block, as on trick_demon (0.03). The builder needs a two-line keyword `giant_slayer` that writes the stat and a card.
- **Keyword `glare_aura`** (Lingering Gaze):
  - `aura` (one per unit) that puts a hidden buff `h3_kit_fortress_glare_watch` on enemies within 1.
  - That buff has an action `trigger: unit_end_move` with `allegiance self`, whose dealer applies the visible `h3_kit_fortress_glared_effect` (clone of `h3_kit_bulwark_chilled_effect` shape: -2 Initiative, maxDuration 2) to self.
  - Trigger shape verified on magic_nairas_kiss_effect_0 (`unit_end_move`).
- **Keyword `petrify_gaze`:** a deep copy of h3_basilisk ability 0 with cd 3. Needed because `keep_ability` only keeps the unit's own pre-rebalance row.
- **Keyword `counter_kill`** (Withering Gaze):
  - Appends `{"mech": "kill_stacks", "values": ["1"]}` to `counterAttacks[0].damageDealer.targetMechanics`.
  - Donor: h3_gorgon_upg Death Stare (`kill_stacks`). Copy its value layout exactly.
- **Buff `h3_kit_fortress_locked_effect`** (Lock Horns): `ent_root` clone (h3_dendroid_soldier), maxDuration 2, name "Locked", text "Cannot move.".
- **Buff `h3_kit_fortress_wyvern_sting_effect`:** a `h3_kit_fortress_wyvern_venom_effect` clone with base 6 and per-stack 3.
- **Keyword `venom_burst`** (Toxic Cloud): the `kw_rally` body (minos_upg_alt ability 1 rumble, `actionCost` 0) with `castTarget_` enemy and the buff aimed at enemies. In practice this is `kw_rally` with a `target` parameter.
- **Keyword `mark_cast` and plugin rule `quarry`** (Quarry):
  - The cast is the gnoll_upg_alt "Shorten Shadow" enemy-buff cast envelope with `actionCost` 0, applying the visible `h3_kit_fortress_quarry_effect` (hydra_debuff clone, no stats, infinite while the caster lives).
  - The plugin records `casterKey -> targetKey` on the ability-commit hook (the Warcry runtime already hooks commit), replacing any earlier mark for that caster.
  - The rule `quarry` adds +percent when the receiver is the caster's recorded quarry.
  - Because the plugin keeps the pair, it does not rely on a source-bound buff (plan limit). The visible buff is only the marker the player sees.
- **`melee_strike` parameter `mech`** (Devour): appends `vampirism ["0.5"]` to the strike dealer. Copy the values layout from `magic_fatal_decay_effect_0` (137 native rows use `vampirism`).

## 4. Power notes

Scratch run: `V:/olden_port_work/unit_rebalance/ability_pass/sfb/homm3_fortress_draft.json`. The faction median moves from 0.97 to 0.92, with no gate errors. All rows land inside 0.85 to 1.15.

- **Grow:**
  - Wyvern Monarch (0.87): +8% HP. The model cannot price Venomous Sting and Toxic Cloud, so this is a floor.
  - Greater Basilisk (0.88): +1 Defence.
  - Gnoll Marauder (0.89): +1 damage max.
  - Hydra alt (0.89): +10 HP. Devour now takes a counterattack.
- **Shrink:**
  - Wyvern alt by about 5% HP once `quarry` carries `offMult` 1.25. A free mark plus No Retaliation is a strong Hunter loop.
  - Lizard alt: raise its `offMult` rather than its body. Giant Slayer is priced by the model only if the lab reads `damagePerDeltaLevel`. If it does not, add `offMult` 1.10.
- **Watch:** Withering Gaze is far stronger at low tiers, where one creature is a large share of the stack. The Mighty Gorgon is tier 5, so tier 1 to 3 attackers lose real value per swing. If it proves oppressive, change it to "kills 1 creature of tier 5 or higher" with a plugin cap. Do not shrink the body.

## 5. Risks

- **`counter_kill`:** whether `kill_stacks` on a counterattack dealer fires (natively it sits on an ability) is unseen. It is the biggest risk in this file.
- **`glare_aura`:** an aura-granted buff whose own trigger fires `unit_end_move` is unproven. The aura may re-apply after the move ends, or the trigger may fire for every hex moved. The fallback is a plain `stat_aura` (-2 Initiative to adjacent enemies), which is weaker but native.
- **`blockEnergyRegen` as an aura stat:** native only on debuffs. It may also block Focus from taking damage, which is fine, and it does not stop hero spells.
- **`quarry`, `unhurt` and `isolated`** are plugin rules, invisible to the AI and the forecast. The AI will not know to Quarry its best target.
- **Scavenge** depends on corpses existing next to the Gnoll. In practice the AI may never use it well, and it is dead in the first round.
- **Devour with `vampirism` on a strike** (natively a buff mechanic) may heal off the whole damage before the multiplier, or not at all.
