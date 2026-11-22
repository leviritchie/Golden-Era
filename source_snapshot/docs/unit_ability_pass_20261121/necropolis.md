# Necropolis (homm3_necropolis): ability variety draft

Draft only (2026-11-21). Nothing here is built. Trade axis is unchanged: **Reaper** (striker: drain, corpses, kills feed the next action) versus **Gravekeeper** (ward: curses, hexes, keeps the horde standing).

**Faction verb: the weak die faster.** Necropolis cards read how hurt the target already is: below half Health, at 25% of its number, already Cursed, already Diseased. The Reaper side finishes wounded stacks. The Gravekeeper side gets them there and stops them from escaping (Bone Pin, Bone Cage, Wail). The Inferno draft uses "moved this round" and Dungeon uses "has not acted / already counterattacked", so this "how wounded" condition belongs to Necropolis alone among my three factions.

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| Generic `resist` (Hollow Bones, Dead Flesh, Mist Form, Black Plate, Hollow Frame, Ghostly Form, Phylactery) | skeleton line, walking_dead_upg, vampire line, black_knight line, bone_dragon line, lich line | Seven different names for flat damage reduction across six lines. This is the faction's biggest cut. |
| Mana Channel (mana transfer 2-6) | wight_upg | The same mechanic as Inferno's Familiar's Gift. Spirit Feast is already the Wraith's mana card. |
| Keening / Dread / Aura of Dread / Chill of the Grave / Sorrow | wight_upg_alt, bone_dragon line, black_knight_upg_alt, bone_dragon_upg | Five "enemies nearby lose Attack/Morale" auras. Dread Presence (Bone Dragon Morale) and Aura of Dread (BK alt Attack) are kept as the two distinct ones. |
| Feeding Frenzy, Death Blow, Soul Rend, Life Drain | vampire_upg, black_knight_upg, bone_dragon_upg_alt | Strike +x% actives. Two are almost identical (+50% no counterattack). |
| Withering Cloud, Curse of Frailty | lich_upg_alt, black_knight_upg_alt | Both are "-Defence hex on one target", the same as the Zombie alt's Rotting Ray. |
| Stench | walking_dead_upg_alt | A generic adjacent Attack aura that duplicates Aura of Dread. |
| Marrow Arrow | skeleton_upg_alt | A plain "shot +x%". |

## 2. Proposed kits

| Unit | Card | P / active | Card text | How it is built | Replaces |
|---|---|---|---|---|---|
| h3_skeleton | Bone Wall | P | Adjacent friendly stacks take 5% less Damage, up to 15% when surrounded by Skeletons. | existing runtime `adjacent_ally_ward` {percent 5, cap 15} | Hollow Bones |
| h3_skeleton_upg | Bone Wall | P | Adjacent friendly stacks take 5% less Damage, up to 15%. | `adjacent_ally_ward` {5, 15} | Hollow Bones |
| h3_skeleton_upg | Bone Harvest | P | kept | kept | kept |
| h3_skeleton_upg | Grave Tide | P | kept | kept | kept |
| h3_skeleton_upg_alt | Bone Wall | P | Adjacent friendly stacks take 8% less Damage, up to 16%. | `adjacent_ally_ward` {8, 16}. Same rule, different numbers: a higher floor and a lower cap. | Hollow Bones |
| h3_skeleton_upg_alt | Grave Watch | P | kept | kept | kept |
| h3_skeleton_upg_alt | Bone Pin | 1 Focus, CD 1 | Performs a Ranged attack that deals 80% Damage. The target cannot counterattack until the end of the round. | `shot` mult 0.8 with buff `h3_kit_necropolis_pinned_effect` (cloneOf `medusa_stone`, keep only `data.disablers [{ability: counter_attack, attack: all}]`, drop `skip_turn`, maxDuration 1) | Marrow Arrow |
| h3_walking_dead (Zombie) | Disease | P | kept | kept | kept |
| h3_walking_dead_upg | Disease into Plague | P | Basic attacks infect the target with Disease (-2 Attack, -2 Defence). Hitting an already Diseased stack turns it into Plague: -4 Attack, -4 Defence, and it cannot restore Health, for 3 rounds. | `on_hit_buff` with `escalate` (existing buff-add hook): disease → new `h3_kit_necropolis_plague_effect` (cloneOf disease, stats doubled, heal immunity data from `magic_fatal_decay_effect_1`) | Dead Flesh |
| h3_walking_dead_upg | Feast | | kept | kept | kept |
| h3_walking_dead_upg_alt | Contagious Disease | P | Basic attacks infect the target with Disease. At the start of a Diseased creature's turn, the Disease spreads to every creature of its own side standing next to it. | `on_hit_buff` with new buff `h3_kit_necropolis_contagion_effect` (cloneOf disease + a `start_turn` / allegiance self action casting the same buff on swirl pattern, `castTarget ally`, the hydra_upg start-turn action shape) | Stench |
| h3_walking_dead_upg_alt | Rotting Ray | 0 Focus | kept | kept | kept |
| h3_wight | Regeneration | P | kept | kept | kept |
| h3_wight_upg (Wraith) | Regeneration | P | kept | kept | kept |
| h3_wight_upg | Mana Drain | P | At the start of each of its turns, takes 2 mana from the enemy hero and gives it to your hero. | new kw `necropolis_mana_drain`: `start_turn` / allegiance self action (hydra_upg shape) with `change_mana ["transfer","ally","2","2","1","false"]` (the `imp_upg_alt` value form). This is HoMM3's Wraith drain. | Mana Channel |
| h3_wight_upg | Spirit Feast | | kept | kept | kept |
| h3_wight_upg_alt | Regeneration | P | kept | kept | kept |
| h3_wight_upg_alt | Wail | 2 Focus, CD 2 | Every adjacent enemy gets -4 Initiative until the end of the next round. Does not end this creature's turn. | `self_buff`-shaped untargeted cast on swirl pattern, `actionCost 0`, buff `h3_kit_necropolis_wail_effect` (cloneOf `hydra_debuff`, stat initiative -4, maxDuration 2) | Keening |
| h3_vampire | No Retaliation | P | kept | kept | kept |
| h3_vampire_upg (Vampire Lord) | No Retaliation | P | kept | kept | kept |
| h3_vampire_upg | Life Drain | P | Restores Health equal to 50% of the Damage dealt and can raise creatures that died. Creatures raised beyond the stack's starting number stay until the end of the battle. | `vampirism` with the fourth value changed to "until start, then temporary" (overflow becomes temporary units) | Life Drain (capped at start), Mist Form |
| h3_vampire_upg | Exsanguinate | 2 Focus, CD 2 | Performs a Melee attack. Deals +50% Damage if the target has lost more than half of its starting Health. | `melee_strike` mult 1.0 + new runtime rule `damage_vs_hp` {percent 50, below 50, abilityOnly true} | Feeding Frenzy |
| h3_vampire_upg_alt | No Retaliation, Blood Tithe, Hypnotic Gaze | | kept | kept | kept (Mist Form removed) |
| h3_lich | Death Cloud | P | Ranged attacks also hit every creature around the target, friend or foe, for 60% Damage. Undead, constructs and elementals are not harmed by it. | existing Death Cloud attack pattern with the cloud mult 0.6 and the immunity tags `undead_immunities`, `construct_immunities`, `embodiment_immunities` added to the cloud damage action (the `kw_revive` immunity pattern) | Death Cloud (enemies only), Phylactery |
| h3_lich_upg (Power Lich) | Death Cloud | P | as Lich | as above | Phylactery |
| h3_lich_upg | Death Harvest, Corpse Explosion | | kept | kept | kept |
| h3_lich_upg_alt | Death Cloud | P | as Lich | as above | Phylactery |
| h3_lich_upg_alt | Bone Cage | 2 Focus, CD 2 | An enemy stack within 5 hexes cannot move until the end of the next round. It can still attack and shoot. | `necropolis_hex` with buff `h3_kit_necropolis_bone_cage_effect` (cloneOf `ent_root`: tags negative + movementNegative, statOverrides speed 0, maxDuration 2) | Withering Cloud |
| h3_lich_upg_alt | Animate Dead | | kept | kept | kept |
| h3_black_knight | Cursed Blade | P | kept | kept | kept (Black Plate removed) |
| h3_black_knight_upg (Dread Knight) | Cursed Blade | P | kept | kept | kept |
| h3_black_knight_upg | Harvest of Souls | P | kept | kept | kept |
| h3_black_knight_upg | Death Blow | 2 Focus, CD 2 | Performs a Melee attack. Deals double Damage if the target is Cursed. | `melee_strike` mult 1.0 + existing runtime `damage_vs_buff` {percent 100, buffs [wasp_debuff / the Cursed Blade buff], new flag abilityOnly true} | Death Blow (+50%, no counterattack), Black Plate |
| h3_black_knight_upg_alt | Cursed Blade, Aura of Dread | P | kept | kept | kept |
| h3_black_knight_upg_alt | Mark of Death | 2 Focus, CD 2 | Marks an enemy stack within 4 hexes for 2 rounds. While marked, the stack dies outright if it falls to 25% or less of its starting number. | `necropolis_hex` with buff `h3_kit_necropolis_marked_effect` (cloneOf `magic_deaths_call_effect_0`: `unit_took_damage` → `assasinate ["0.25","0.0"]`, maxDuration 2) | Curse of Frailty, Black Plate |
| h3_bone_dragon | Dread Presence | P | kept | kept | kept (Hollow Frame removed) |
| h3_bone_dragon_upg (Ghost Dragon) | Dread Presence, Aging Touch | P | kept | kept | kept |
| h3_bone_dragon_upg | Chill of the Grave | P | Enemies adjacent to this creature get -2 Speed. | the existing aura reduced to stat speed -2 only | Chill (Attack + Speed), Ghostly Form, Sorrow |
| h3_bone_dragon_upg_alt | Dread Presence, Corpse Eater | P | kept | kept | kept |
| h3_bone_dragon_upg_alt | Deathly Plunge | 3 Focus, CD 3 | Performs a Melee attack. If it destroys the target stack, this creature may act again this round (once per round). | `melee_strike` mult 1.0 + new plugin rule `kill_extra_action` (on ability commit, if the target stack died, grant `add_action_points ["1"]`, the hero-buff donor at `sub_skills_battle_hero_buffs[164]`; once per round) | Life Drain, Soul Rend |

## 3. New mechanics needed

- **`h3_kit_necropolis_pinned_effect`** (Bone Pin). Clone `medusa_stone` (verified: `data.disablers [{"ability":"counter_attack","attack":"all"}]` plus `sequenceEffect skip_turn`). Keep the disablers, drop the skip_turn, 1 round. A native buff on an existing `shot`.
- **Plague escalate** (Zombie upg). Use the existing `escalate` buff-add rewrite. The new top buff clones disease with doubled stats and takes the heal immunity block from `magic_fatal_decay_effect_1` (verified: it blocks healing).
- **`h3_kit_necropolis_contagion_effect`** (Zombie alt). Disease plus a `start_turn` / allegiance self action that casts the contagion buff on the swirl pattern around the bearer, `castTarget ally` *relative to the bearer* (so it spreads to the bearer's own side). The duration is capped at 2 so the chain cannot keep itself alive forever. Native data if `ally` resolves relative to the buff owner; otherwise a small plugin rule `spread_to_neighbours`.
- **`necropolis_mana_drain`** (Wraith). A `start_turn` action from the hydra_upg shape with `change_mana ["transfer","ally","2","2","1","false"]` (verified value form on `imp_upg_alt`).
- **Vampirism overflow**. Change the fourth `vampirism` value to "until start, then temp" so overflow becomes temporary creatures. This must be checked against the vampire_upg_alt and vanilla vampire rows; if the engine has no such value, fall back to a plugin `overflow_temp` rule.
- **Runtime rule `damage_vs_hp`** {percent, below, abilityOnly}: +percent when the target's current total Health is below `below`% of its starting total. The abilityOnly flag limits it to the unit's active.
- **`damage_vs_buff` abilityOnly flag**. Add one bool to the existing rule so Death Blow's bonus applies only to the active and not to counterattacks.
- **Death Cloud immunity tags**. Add `undead_immunities`, `construct_immunities` and `embodiment_immunities` to the cloud damage action (the same pattern `kw_revive` uses to exclude those creatures) and allow friendly targets in the cloud swirl. This restores HoMM3's "hits everything living" rule.
- **`h3_kit_necropolis_bone_cage_effect`**. Clone `ent_root` (verified: tags negative + movementNegative, statOverrides speed 0). Cast through the existing `necropolis_hex`.
- **`h3_kit_necropolis_marked_effect`**. Clone `magic_deaths_call_effect_0` (verified: `unit_took_damage` → `assasinate ["0.20","0.0"]`, text "Dies if the stack size is lower than or equal to {0}% of its original number"). The threshold becomes 0.25.
- **Plugin rule `kill_extra_action`**. On ability commit, after damage resolves, if the target stack is destroyed, grant one extra action (`add_action_points ["1"]`, verified at `sub_skills_battle_hero_buffs[164]`). Stamp the round so it fires once per round.

## 4. Power notes

These numbers come from a dry run with `unit_design_lab.py tune --design V:/olden_port_work/unit_rebalance/ability_pass/scratch_homm3_necropolis.json`, with no write.

- Removing seven `resist` cards costs toughness. Black Knight bodies grow: hp about 84 / 88 / 110 (base / Dread / alt). Ghost Dragon hp about 174.
- Vampire Lord shrinks: Attack 9 → 6. Overflow Life Drain plus Exsanguinate is the strongest Reaper kit in the faction.
- Lich base sits at 1.05x, against the floor. That gap existed before (1.07x). The Death Cloud mult is 0.6 so the friendly-fire risk is priced in. Accept 1.05x or give the Lich +1 Defence.
- The other rows move only a few points of hp. The faction median after tuning is 0.95x.

## 5. Risks

- **Contagion ally targeting.** If `castTarget ally` resolves relative to the caster's side and not the buff bearer's, Disease would spread to the Zombie's own army. This needs one in-game test before anything ships.
- **Death Cloud friendly fire.** The AI may shoot next to its own living stacks. Also check that the immunity tags really exclude undead from the cloud and not from the main shot.
- **Vampirism overflow value** may not exist natively. If it does not, it needs a plugin rule.
- **`kill_extra_action`** could chain with Bone Dragon haste effects. Keep the once-per-round stamp.
- **Mark of Death + Bone Cage + Wail** is a strong Gravekeeper lock. Watch for it in playtests.
- Plugin rules (`damage_vs_hp`, abilityOnly `damage_vs_buff`, `kill_extra_action`) are invisible to the damage forecast.
