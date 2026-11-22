# Factory: unit ability variety pass (draft, 2026-11-21)

Trade axis: Crewed (striker: Repairs constructs, buffs, shelters and marks targets for the army; worth more with army around it) versus Automated (ward: self-contained resistances, self buffs, counterattacks and sustain). The pass removes most of the copied resists and Alerts. It gives the crewed side more "army around it" cards (Huddle, Bell Toll, Guardian Protocol, Field Fortification) and the automated side self-contained ones (Burrow, Sealed Hull).

Cross-check with my other two factions: Factory's bodyguard, barricade, burrow and Focus-gift cards are not used in Conflux or Cove. Huddle and Conflux's Renewing Flame share one keyword shape (an adjacent-ally pulse), but they use different triggers (Defend vs round start) and different effects (Defence vs healing).

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| Armor Plates / Iron Hull / Armor Belt / Brass Casing / Burrower / Feathered Coils | Armadillo line, Dreadnought line, Automaton alt, Sandworm line, Couatl line | Generic resists on six lines. |
| Alert (counterattack twice or unlimited) | Armadillo alt, Sentinel, Bounty Hunter, Gunslinger alt, Dreadnought alt | Generic extra counterattack on four lines. |
| Swoop (+5/+10% per hex) | Couatl line | Flat damage per hex. |
| Field Drive (+2 Speed to an ally) | Engineer | The same card as Conflux's Haste and Cove's Rising Tide in spirit; a third tempo buff. |
| Long Reach | Mechanic alt | A Long Thrust equivalent (`reach_strike`). |
| Stampede (adjacent allies +15% Damage) | Bellwether | A `rally`, the same shape as Cove's Rising Tide. |
| Herd Leader (+2 Defence aura) and Sentinel Field (-15% Ranged aura) | Bellwether, Sentinel | Generic defence auras. |
| Dead or Alive (+50% shot) | Bounty Hunter | A strike-for-x% active. |
| Swallow (+50%, no counterattack) | Olgoi-Khorkhoi | Strike for x%, no counterattack. |
| Skyfall (fly to any enemy, +30%, no counterattack) | Crimson Couatl | A strike-for-x% dive; it would clash with Cove's Swing Aboard. |
| Jade Scales (allies -25% Magic) and Soothing Coil (cleanse) | Couatl alt | Jade Scales is Conflux's Sacred Flame word for word; Soothing Coil is Conflux's Purifying Fire word for word. |
| Fortress Mode (-30% Damage and taunt) | Dreadnought alt | Taunt duplicates the Armadillo alt's Taunting Plate, and the damage cut duplicates Crimson's Meditation. |

## 2. Proposed kits

| Unit | Card | P / A | Card text | How it is built | Replaces |
|---|---|---|---|---|---|
| Halfling | Positive Luck | P | kept | `card` | kept |
| Halfling Grenadier | Positive Luck, Defense Pierce | P | kept | as now | kept |
| | Bombardier Mark | A 1F / CD1 | kept | `shot` mult 0.5 + rider | kept |
| Halfling alt | Positive Luck, Flamethrower | P | kept | as now | kept |
| | Ember Canister | A 1F / CD2 | kept | `factory_pattern_shot` 0.8 | kept |
| Mechanic | Dragonbreath Strike | P | kept | `card` (reach default attack) | kept |
| | Repair | A 1F / CD2 | kept | `factory_repair` | kept |
| Engineer | Dragonbreath Strike | P | kept | `card` | kept |
| | Repair | A 1F / CD2 | kept | `factory_repair` | kept |
| | Field Fortification | A 1F / CD2, free | Builds a barricade on a free hex within 3 hexes. It blocks movement until the end of the next round. Does not end this creature's turn. | NEW keyword `barricade`: the `spawn_object` envelope from Suppressing Fire (gunslinger_upg_alt ability 0), spawning a blocking obstacle object with a 2-round lifetime instead of a trap | Field Drive |
| Mechanic alt | Dragonbreath Strike | P | Deals Damage to the target and any creature on the hex directly behind it. | `card` (reach default attack, as on the Mechanic) | Long Reach |
| | Repair | A 1F / CD2 | kept | `factory_repair` | kept |
| | Overclock | A 1F / CD1 | kept | `self_buff` | kept |
| Armadillo | Huddle | P | When this creature Defends, friendly creatures adjacent to it gain +3 Defence until the end of the round. | NEW keyword `defend_pulse`: passive action on trigger `unit_skip`, allegiance self, rumble x1 shape around self (the `kw_rally` shape from minos_upg_alt), affect allynoself, NEW buff `h3_kit_factory_huddle_effect` (defence +N, maxDuration 1) | Armor Plates |
| Bellwether | Huddle | P | (as Armadillo, +5 Defence) | `defend_pulse` {defence 5} | Armor Plates, Herd Leader |
| | Bell Toll | A 1F / CD2, free | Adjacent friendly creatures gain 1 Focus. Does not end this creature's turn. | NEW keyword `focus_rally`: the `kw_rally` envelope with mechanic `add_energy` ["energy","ally","1","0","1"] (layout from `h3_imp_upg`, verified) in place of a buff | Stampede |
| Armadillo alt | Huddle | P | (as Armadillo) | `defend_pulse` {defence 3} | Armor Plates |
| | Curl Up | P | kept | `when_damaged_self_buff` | kept |
| | Taunting Plate | A 2F | kept | `keep_ability` | kept (Factory's only taunt) |
| | (removed) | | | | Alert |
| Automaton | Construct, Volatile Reactor | P | kept | as now | kept |
| Sentinel Automaton | Construct, Volatile Reactor | P | kept | as now | kept |
| | Guardian Protocol | P | Takes 30% of the Damage dealt to adjacent friendly creatures in their place. | NEW plugin rule `bodyguard` {percent 30} | Sentinel Field, Alert |
| | Blow Up | A 2F | kept | `keep_ability` | kept |
| Automaton alt | Construct, Volatile Reactor, Swift Strike | P | kept | as now | kept |
| | Wind-Up | A 2F | kept | `keep_ability` | kept |
| | (removed) | | | | Brass Casing |
| Sandworm | Blink, Spell Immunity III | P | kept | `card`, `spell_immunity` | kept |
| | Burrow | P | When this creature Waits, it burrows: it cannot be targeted until its next action or until it takes Damage. | NEW keyword `wait_burrow`: passive action on trigger `unit_wait`, allegiance self, applies NEW buff `h3_kit_factory_burrow_effect` (clone of `magic_shade_cloak_effect_0`, verified: `stats.untargetable`, with the `unit_wait` removal line dropped and the took_damage, end_move, skip and cast removals kept) | Burrower |
| Olgoi-Khorkhoi | Blink, Spell Immunity III, Burrow | P | (as Sandworm) | as above | Burrower |
| | Gorge | A 2F / CD2 | Performs a Melee attack. This creature restores Health equal to 50% of the Damage dealt, and can revive fallen creatures this way. | NEW keyword `drain_strike`: `melee_strike` mult 1.0 (counter on) with dealer mechanic `vampirism` ["0.5"] (value layout from `magic_fatal_decay_effect_0`) | Swallow |
| | Devour Corpses | A 2F | kept | `keep_ability` | kept |
| Sandworm alt | Blink, Spell Immunity III, Burrow | P | (as Sandworm) | as above | Burrower |
| | Glass Shards | P | kept | `on_hit_buff` | kept |
| | Shatter | A 2F / CD2 | kept | `melee_strike` 1.0 + rider | kept |
| Gunslinger | Parry, Countershot | P | kept | `factory_first_strike`, `factory_countershot` | kept |
| Bounty Hunter | Parry, Countershot, Sharpshooter | P | kept | as now | kept |
| | Bounty | P | Deals +30% Damage to the enemy stack with the most total Health on the battlefield. | NEW plugin rule `bounty` {percent 30}: at the damage step, compare the target's current total Health with every living enemy stack | Dead or Alive, Alert |
| Gunslinger alt | Parry, Countershot | P | kept | as now | kept |
| | Suppressing Fire, Deputize | A 2F | kept | `keep_ability`, `factory_cast_buff` | kept |
| | (removed) | | | | Alert |
| Couatl | Radiant Plumage | P | Enemy creatures adjacent to this creature have -2 Attack. | `stat_aura` {radius 1, target enemy, stats {offence: -2}} | Feathered Coils, Swoop |
| Crimson Couatl | Radiant Plumage | P | Enemy creatures adjacent to this creature have -4 Attack. | `stat_aura` {radius 1, enemy, offence -4} | Feathered Coils, Swoop |
| | Swift Strike | P | kept | `no_retaliation` | kept |
| | Meditation | A 3F / CD3 | kept | `self_buff` | kept |
| | (removed) | | | | Skyfall |
| Couatl alt | Radiant Plumage | P | (as Couatl, -2 Attack) | `stat_aura` {radius 1, enemy, offence -2} | Feathered Coils, Swoop, Jade Scales (the unit's single aura slot moves to Plumage) |
| | Jade Ward | A 3F / CD3 | kept | `factory_cast_buff` | kept |
| | (removed) | | | | Soothing Coil |
| Dreadnought | Construct | P | kept | `card` | kept |
| | Heat Stroke | A 3F / CD3 | kept | `factory_pattern_strike` | kept (line identity) |
| | (removed) | | | | Iron Hull |
| Juggernaut | Construct, Sweeping Strike | P | kept | as now | kept |
| | Heat Stroke, Boiler Rampage | A 3F | kept | `factory_pattern_strike`, `keep_ability` | kept |
| | (removed) | | | | Iron Hull |
| Dreadnought alt | Construct | P | kept | `card` | kept |
| | Sealed Hull | P | Negative effects on this creature last at most 1 round. | `short_debuffs` {rounds 1} (donor `sub_skill_resistance_3_alt` `maxInComingNegativeBuffDuration`) | Armor Belt, Alert, Fortress Mode |
| | Heat Stroke | A 3F / CD3 | kept | `factory_pattern_strike` | kept |

Kit sizes after the pass: Halfling 1 / 3 / 3, Mechanic 2 / 3 / 3, Armadillo 1 / 2 / 3, Automaton 2 / 4 / 4, Sandworm 3 / 5 / 5, Gunslinger 2 / 4 / 4, Couatl 1 / 3 / 2, Dreadnought 2 / 4 / 3. Every upgrade is larger than its base.

## 3. New mechanics needed

- **Keyword `barricade`** {range, rounds}. Copy the `spawn_object` envelope of Suppressing Fire (gunslinger_upg_alt ability 0) and point it at a blocking battlefield object instead of the trap. 37 Core rows use `spawn_object`; the obstacle object id still has to be picked from the Core's object list (the Conflux Firewall spawns a fire wall, not a blocker).
- **Keyword `defend_pulse`** {defence}. A passive action on trigger `unit_skip` (the Defend action) with condition allegiance self. Its dealer uses the `kw_rally` rumble x1 shape around the unit, affects allynoself, and applies NEW buff `h3_kit_factory_huddle_effect`. That buff clones `minos_selfbuff` with a `defence` stat and maxDuration 1.
- **Keyword `focus_rally`.** The `kw_rally` envelope (minos_upg_alt ability 1, free) with mechanic `add_energy` ["energy","ally","1","0","1"] (verified layout on `h3_imp_upg`) instead of a buff.
- **Plugin rule `bodyguard`** {percent}. At the damage step, when the target is adjacent to a living friendly unit that has the rule, move percent of the final damage onto the bodyguard (applied as damage to it, after its own Defence). With several bodyguards, use only the one with the most Health. A bodyguard never redirects damage aimed at itself. No native donor: `transfer_hp` moves Health, not incoming damage.
- **Keyword `wait_burrow` + buff `h3_kit_factory_burrow_effect`.** Clone `magic_shade_cloak_effect_0` (verified in `buffs_night_magics.json`: `stats.untargetable`, removed by `zero_duration_on_damage` on unit_took_damage, unit_wait, unit_skip, unit_end_move and unit_cast_ability). Drop the `unit_wait` removal line so the Wait itself does not remove it. Grant it from a passive action on `unit_wait`, allegiance self. Set maxDuration 2 so it survives into the delayed turn.
- **Keyword `drain_strike`.** `melee_strike` plus mechanic `vampirism` ["0.5"]. The Fortress draft proposes the same `mech` parameter on `melee_strike` for its Devour; build it once.
- **Plugin rule `bounty`** {percent}. At the damage step, +percent when the target's current total Health is the highest among living enemy stacks (ties count).
- Card-only changes: Mechanic alt's Long Reach becomes the reach default attack the Mechanic already has. Couatl line and Dreadnought alt use existing keywords (`stat_aura`, `short_debuffs`).

## 4. Power notes

These are estimates from the model's formulas, not a scratch run.

- **Engineer:** Field Fortification and Field Drive are both utility (keep util 1.0). No change.
- **Mechanic alt:** Long Reach becomes a passive reach attack. The model scores pattern attacks higher (offence about +5%). Give it -1 Attack, or leave it if it is still under 1.05x.
- **Armadillo line:** losing Armor Plates costs about 12% toughness. Huddle is unseen (util +0.5; it protects others). Armadillo +3 HP. Bellwether loses an aura and a rally and gains Bell Toll (util +1): give it +2 HP. Armadillo alt loses two cards: give it +1 Defence and +3 HP. Check the Bellwether/alt gap.
- **Sentinel:** `bodyguard` adds toughness to allies and costs its own. Model it as util +1.0 and `toughMult` 0.95. Losing Alert and Sentinel Field means the 1.01x body drops to about 0.92x: give it +4 HP and +1 Attack.
- **Automaton alt:** losing Brass Casing is about -8% toughness. Give it +2 HP.
- **Sandworm line:** Burrower (-25% ranged) was worth about 10% toughness. Burrow is a tempo tool (`toughMult` 1.05). All three rows +3 HP. Olgoi: Gorge at 1.0 with a counterattack and lifesteal is weaker offence than Swallow at 1.5 with none (about -10%), but adds sustain (`toughMult` 1.05). Give it +1 Attack.
- **Bounty Hunter:** losing unlimited counterattacks and a +50% shot costs about 15% offence. Bounty at 30% on the biggest stack is about `offMult` 1.12. Give it +1 Attack.
- **Gunslinger alt:** losing Alert costs about 5% offence. Give it +1 Attack.
- **Couatl line:** losing the ranged resist (-10% toughness) and Swoop (-12% offence on a fast flyer). The Attack aura counts as toughness for adjacent fights (`toughMult` about 1.08 at -2, 1.15 at -4). Couatl +2 Attack and +10 HP. Crimson also loses Skyfall: give it +2 Attack. Couatl alt also loses Jade Scales and Soothing Coil: give it +2 Defence and +10 HP.
- **Dreadnought line:** Iron Hull was about 7% toughness. Dreadnought and Juggernaut +12 HP each. Dreadnought alt loses Armor Belt, Alert and Fortress Mode (about -25% toughness, -8% offence); Sealed Hull is `toughMult` about 1.05. Give it +4 Defence and +20 HP, then re-check the pair gap.

## 5. Risks

- **`bodyguard` is a new damage-redirect rule.** Interactions with `hit_cap`, Rebirth, overkill protection and the damage forecast are untested. The AI cannot see it, so it will keep attacking guarded stacks.
- **`unit_skip` as the Defend trigger** is assumed from the trigger list. If `unit_skip` also fires on a forced skip (Frozen, stun), Huddle would trigger while the unit is disabled. That is acceptable, but it should be confirmed in game.
- **`untargetable` granted on Wait** is unproven. The cloak's own removal lines may fire in the wrong order: if `unit_wait` dispatch runs after the grant, the original line would remove it, which is why it is dropped. AoE spells and patterns still hit an untargetable unit.
- **`barricade`** needs a spawnable blocking object with a lifetime. If none exists in the Core, Field Fortification falls back to a trap-style object, and the card text changes.
- **`stat_aura` with negative Attack** on enemies works for Speed today, but Attack has not been shown as an aura stat.
- **Cross-faction:** `drain_strike` (Fortress Devour) shares a keyword with Gorge. Gorge revives and Devour is an area bite.
