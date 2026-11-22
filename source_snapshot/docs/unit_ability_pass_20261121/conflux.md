# Conflux: unit ability variety pass (draft, 2026-11-21)

Trade axis: Host (striker, a good attack shape on an even body) versus Donor (ward, stat spikes, riders and support casts). Every elemental row also feeds `custom_factions/conflux_fusion` (142 fused units), so each card below also says what it does to fusions. The fusion section near the end has the details.

Compared with Cove and Factory (also drafted by me), no new trick here is reused in either of those files. The overlaps with other agents' factions are listed under Risks.

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| Elusive (-20% Ranged Damage) | Pixie, Sprite, Pixie alt | Generic resist, and the same number on all three rows. |
| Body of Air (-20% Ranged Damage part) | Air, Air upg, Air alt | Generic resist. The lightning weakness is the HoMM3 part. |
| Stone Body (-15/-15/-25% basic attacks) | Earth, Earth upg, Earth alt | Generic resist. |
| Frozen Heart (-25% Magic Damage) | Water alt | Generic resist. |
| Live Current (counterattacks twice) | Fire alt | Generic second counterattack ("Alert"). |
| Haste (+2 Speed) vs Jumpstart (+3 Initiative) | Air alt, Fire upg | Two lines with the same "free single-ally tempo buff" active. |
| Eruption (alt swirl 50%) vs Mind Blast (alt swirl 50%) | Earth upg, Psychic line | Same alternative attack on two lines. |
| Arcane Storm | Psychic upg | Plain whirlwind (`swirl_strike`), and a third swirl on a line that already has Sweeping Strike and Mind Blast. |
| Buffeting Winds (-2 Initiative rider) | Air alt | Rampart's War Unicorn draft uses the same rider. Weak identity for an Air elemental. |
| Molten Skin vs Burning Plumage | Earth alt, Firebird alt | Word-for-word identical cards (`when_damaged_adjacent_debuff`, -3 Defence). |
| Sacred Flame (adjacent allies -25% Magic) | Firebird alt | Generic resist aura, and Factory's Jade Scales is the same card. |
| Blazing Flight (+5%/hex) | Firebird upg | Flat damage per hex (`gallop` 0.05). |
| Firestorm Pass | Firebird upg | "Breath for +30%, no counterattack, return": a strike-for-x%-no-counter variant. |

## 2. Proposed kits

Focus and cooldown are written F/CD. P = passive.

| Unit | Card | P / A | Card text | How it is built | Replaces |
|---|---|---|---|---|---|
| Pixie | Flutter Away | P | After this creature survives a Melee attack, it flies 1 hex directly away from the attacker if that hex is free. | NEW plugin rule `scatter` {hexes 1} | Elusive |
| Sprite (Pixie upg) | Swift Strike | P | kept | `no_retaliation` | kept (HoMM3 identity) |
| | Flutter Away | P | (as Pixie) | `scatter` {hexes 1} | Elusive |
| | Flit | A 1F / CD1 | Performs a Melee attack, then returns to its original position. | `melee_strike` mult 1.0 with return (unchanged); the redundant "no counterattack" text is dropped because Swift Strike already covers it | kept (text trimmed) |
| Pixie alt | Sweeping Strike | P | kept | `card` (swipe) | kept |
| | Flutter Away | P | After this creature survives a Melee attack, it flies up to 2 hexes directly away from the attacker, as far as the hexes are free. | `scatter` {hexes 2} | Elusive |
| | Leeching Hop | A 2F | kept | `keep_ability` | kept |
| Air Elemental | Body of Air | P | Takes double Damage from Lightning Bolt and Chain Lightning. | `resist` with the ranged entry removed, weakness kept (or `card` + the existing weakness rows) | Body of Air (ranged resist removed) |
| | Air Spark | A 2F | kept | `keep_ability` | kept |
| Air upg | Body of Air | P | (as Air Elemental) | as above | resist part removed |
| | Sharpshooter | P | kept | `sharpshooter` | kept |
| | Thunderbolt | A 2F / CD2 | kept | `conflux_spell` mult 0.8 | kept |
| Air alt | Body of Air | P | (as Air Elemental) | as above | resist part removed |
| | Whirling Gale | P | Its counterattacks strike every enemy adjacent to it. | NEW keyword `counter_shape`: the counterattack row takes the hydra whirlwind pattern that `kw_alt_swirl` already uses; the basic attack stays single target | Buffeting Winds |
| | Haste | A 2F | kept | `keep_ability` | kept |
| Water Elemental | Living Water | P | kept | `conflux_immunity` | kept |
| Water upg | Living Water, Ice Blades | P | kept | `conflux_immunity`, `skirmisher` | kept |
| | Ice Bolt | A 2F / CD2 | kept | `shot` mult 1.2 (+ slow rider) | kept |
| Water alt | Living Water | P | kept | `conflux_immunity` | kept |
| | Frostbite | P | Basic attacks and counterattacks stop the target from restoring Health or being revived until the end of the next round. A target that already has Frostbite is Frozen instead: it skips its next turn and takes +25% Damage while Frozen. A creature cannot be Frozen again for 3 rounds. | `on_hit_buff` (unchanged) + buff edit on `h3_kit_conflux_frozen_effect`: add an all-damage `inDmgMods` +0.25 entry | Frostbite (stronger), Frozen Heart |
| Fire Elemental | Born of Flame, Searing Touch | P | kept | `conflux_immunity`, `on_hit_buff` | kept |
| Fire upg | Born of Flame, Searing Touch, Fire Shield | P | kept | as now (`reflect` for Fire Shield) | kept |
| | Ignite | A 2F / CD2, free | Sets an enemy creature within 6 hexes on fire. At the start of each of its next 2 turns it takes Magic Damage equal to 40% of this stack's basic attack Damage. Does not end this creature's turn. | NEW keyword `dot_cast`: free single-enemy cast (`conflux_spell` envelope, no direct damage) that applies NEW buff `h3_kit_conflux_ignite_effect` (clone of vanilla `phoenix_ignition`, start_turn `magic_pure`); the per-stack amount needs NEW buff-add rewrite `scale_by_caster` | Jumpstart |
| Fire alt | Born of Flame, Searing Touch, Sweeping Strike | P | kept | as now | kept |
| | Static Build-up | P | Whenever this creature takes Damage, it gains 1 extra Focus. | NEW keyword `focus_on_damage`: passive action, trigger `unit_took_damage`, allegiance self, mechanic `add_energy` ["energy","self","1","0","1"] (layout from `h3_imp_upg`) | Live Current |
| | Chain Lightning | A 2F / CD2 | kept | `conflux_spell` mult 1.0 | kept |
| Earth Elemental | Stone Body | P | A single attack can destroy at most 35% of this stack's full Health. | `runtime hit_cap` {percent 35} | Stone Body (-15% basic) |
| | Grounded | P | kept | `conflux_immunity` | kept |
| Earth upg | Stone Body | P | A single attack can destroy at most 30% of this stack's full Health. | `runtime hit_cap` {percent 30} | Stone Body (-15% basic) |
| | Magma Heart, Molten Fists | P | kept | `conflux_immunity`, `conflux_stat` | kept |
| | Fireball | A 2F / CD2 | kept | `conflux_spell` mult 0.8 | kept |
| | (removed) | | | | Eruption (dropped; Mind Blast stays the only alt swirl) |
| Earth alt | Stone Body | P | A single attack can destroy at most 20% of this stack's full Health. | `runtime hit_cap` {percent 20} | Stone Body (-25% basic) |
| | Lava Heart, Molten Skin, Unstoppable Flow | P | kept | as now | kept (Molten Skin is now the only copy) |
| | Firewall | A 2F | kept | `keep_ability` | kept |
| Psychic Elemental | Sweeping Strike, Swift Strike, Mind Blast | P / alt attack | kept | `card`, `no_retaliation`, `alt_swirl` 0.5 | kept |
| Psychic upg | Sweeping Strike, Swift Strike, Mind Blast, Spell Immunity V | P | kept | as now | kept |
| | Psychic Feedback | P | Whenever an enemy creature within 3 hexes uses an ability, it takes Magic Damage equal to 30% of this stack's basic attack Damage. | NEW plugin rule `ability_feedback` {radius 3, percent 30} on the ability-commit hook, dealt through the queued-attack path | Arcane Storm |
| Psychic alt | Swift Strike, Unbound Mind, Astral Interference | P | kept | as now | kept |
| | Mind Fray | P | Basic attacks and counterattacks stop the target from gaining Focus until the end of the next round. | `on_hit_buff` with NEW buff `h3_kit_conflux_mind_fray_effect` (clone of `succubus_debuff_3`: `stats.blockEnergyRegen`, maxDuration 2) | Mind Fray (-3 Attack) |
| | Misfortune | A 2F / CD3 | kept | `conflux_spell` | kept |
| Firebird | Dragonbreath Strike, Born of Flame | P | kept | `card`, `conflux_immunity` | kept |
| Firebird upg | Dragonbreath Strike, Born of Flame, Rebirth | P | kept | as now | kept |
| | Sunfall | A 3F / CD3 | Flies to any free hex on the battlefield and deals 60% of its basic attack Damage to every enemy adjacent to where it lands. Enemies do not counterattack. | `landing` {enemiesOnly true, push false, mult 0.6} (donor `black_dragon_upg_alt` ability 1, verified) | Firestorm Pass, Blazing Flight |
| Firebird alt | Dragonbreath Strike, Born of Flame, Rebirth | P | kept | as now | kept |
| | Renewing Flame | P | At the start of each round, friendly creatures adjacent to this creature restore Health equal to 10% of their stack's full Health. This can revive fallen creatures up to the stack's starting size. | NEW keyword `round_pulse`: passive action on `start_round`, rumble x1 pattern around self, affect allynoself, mechanic `heal_percent` ["until start amount","max_squad","0.10","0.00","true"] (layout from `h3_walking_dead_upg`, verified) | Sacred Flame, Burning Plumage |
| | Purifying Fire | A 3F / CD3 | kept | `cleanse` range 1 | kept |

Kit sizes after the pass: Pixie 1 / 3 / 3, Air 2 / 3 / 3, Water 1 / 3 / 2, Fire 2 / 4 / 5, Earth 2 / 4 / 5, Psychic 3 / 5 / 5, Firebird 2 / 4 / 5. Every upgrade is still larger than its base.

## 3. New mechanics needed

- **Plugin rule `scatter`** {hexes}. After the damage step of a Melee attack, if the defender is a unit with this rule and it is still alive, move it up to N hexes along the attacker-to-defender direction, stopping at the first blocked hex. Run it after the counterattack resolves so the counterattack still happens. Uses the same post-attack dispatch as Covering Fire. No native donor: `push_unit_from_caster` (minos ability 0) pushes the target away from the caster, but here the unit moves itself away from its attacker.
- **Keyword `counter_shape`** {pattern}. Writes `attackPatternSid` on the counterattack row only. The pattern is the hydra whirlwind that `kw_alt_swirl` already reads. The Bulwark draft's `pierce_attack` edits the same field.
- **Buff edit `h3_kit_conflux_frozen_effect`.** Add an all-damage `inDmgMods` +0.25 entry. Because it is a buff row, every fusion that inherits Frostbite (as a rider or a passive) gets it automatically.
- **Keyword `dot_cast` + buff `h3_kit_conflux_ignite_effect` + buff-add rewrite `scale_by_caster`.** The buff clones vanilla `phoenix_ignition` (start_turn, `magic_pure`, flat 60, verified in `units_buffs_nature.json`). Flat damage does not scale with stack size. So the new rewrite, next to `rotate` and `escalate` in the buff-add hook, sets the damage to percent × the caster's basic attack Damage when the buff lands. The cast envelope is `conflux_spell` with the damage dealer removed and the buff attached.
- **Keyword `focus_on_damage`.** Passive action: trigger `unit_took_damage`, condition allegiance self, mechanic `add_energy` ["energy","self","1","0","1"]. The `add_energy` layout is verified on `h3_imp_upg`, `godslayer_upg` and `graverobber_upg_alt`. This is not done with the `energyPerTakeDamage` stat on purpose: fusions keep host stats, but they inherit guest passives.
- **Plugin rule `ability_feedback`** {radius, percent}. On ability commit (the Warcry runtime already hooks it), if the caster is an enemy within radius of a unit with the rule, queue magic damage of percent × that unit's basic attack Damage against the caster. One trigger per cast per Psychic stack. The native fallback is a passive on trigger `unit_cast_ability` with allegiance enemy. That trigger is verified, but I could not confirm that a passive's dealer can target the triggering unit, so plugin first.
- **Buff `h3_kit_conflux_mind_fray_effect`.** Clone `succubus_debuff_3` (verified: `stats.blockEnergyRegen`, maxDuration 2). Rewrite the name and description.
- **Keyword `round_pulse`** {pattern, affect, mechanic, values}. A passive action on `start_round` that uses the `kw_rally` rumble x1 shape (minos_upg_alt) with `heal_percent`. The verified layout is `h3_walking_dead_upg` ["until start amount","max_squad","0.25",...]; here it is set to 0.10.
- **`hit_cap` and `scatter` and `ability_feedback` fusion propagation.** See section 4.

## 4. What changes for fusions

How the fusion build works (`tools/release_port/homm3_conflux_fusion_core_overlay.py`, `build_fused_unit`):

- The host gives the attack rows, stat keys and aura.
- Guest logic passives are appended, deduplicated by JSON.
- The guest's attack rider is copied only when the host has none.
- `inDmgMods`/`outDmgMods` are merged by tag.
- Actives are host then guest, deduplicated by name.
- A `passive` signature clears passives, riders and damage mods.
- Stage-2 units take only their own signature parts.
- SID-keyed runtime rules are not inherited at all.

What the pass does to fusions:

1. **Resists removed (Elusive, Body of Air ranged part, Frozen Heart, Stone Body).** The merged `inDmgMods` lose these entries. Fusions with a pixie, air, water alt or earth half become squishier by the same amount as the elementals. The fusion power pass has to re-price them, or `homm3_conflux_fusion_core_overlay.py` has to scale fused bodies off the new parent power.
2. **Stone Body (`hit_cap`), Flutter Away (`scatter`) and Psychic Feedback (`ability_feedback`) are SID-keyed runtime rules.** Today a fusion would silently lose them. Proposed change to `build_unit_kit_runtime_table.py`: for every fused SID, emit the host's rules plus the guest's rules (merged by kind, host value wins). Emit none when the pair's signature kind is `passive`, and none for stage-2 units. The earth line hosts 12/14/13 fusions, so this matters most for Stone Body. Without the change, earth fusions lose their main defence, while today they keep the resist through `inDmgMods`.
3. **Whirling Gale (`counter_shape`)** sits on the counterattack row, which comes from the host. Air alt hosts 4 fusions and is the guest in 10. As a guest it gives nothing, so it is a host-only gift. That fits the axis (host = attack shape). Optional: let `_merge_attack_riders` copy the guest counter pattern when the host counter row uses the plain single pattern.
4. **Frostbite, Mind Fray and Ignite** are buff-based. Frostbite and Mind Fray are attack riders: a guest rider is copied only when the host has none. The Frozen +25% edit reaches every fusion that already carries Frostbite. Ignite is an active, so it merges by name as Jumpstart did.
5. **Static Build-up and Renewing Flame** are logic passives, so guests pass them on. That is why they are passives and not stats or auras.
6. **Sunfall** replaces Firestorm Pass. Firebird is not an elemental row, so no fusion changes.
7. **Eruption removed** from Earth upg: the 14 earth-upg host fusions lose the alt swirl. Psychic-hosted fusions keep Mind Blast.
8. **Signatures:** no signature references elemental row indices (checked in the earlier read of `fusion_units.json`), so none break. The 52 `active` signatures replace actives as before.

Validators to re-run after the build: `validate_homm3_conflux_fusion_data` and the fusion glossary check. Card names that change (Mind Fray text, Stone Body text) appear in the fusion glossary.

## 5. Power notes

These are estimates from the model's formulas, not a scratch run. The new rules are plugin-side, so a scratch table would only carry guessed `offMult`/`toughMult` values. Rerun `unit_design_lab.py check` once real multipliers are attached.

- **Pixie line:** removing Elusive costs about 8% toughness. Flutter Away gives some of it back. Give it `toughMult` 1.05 (2 hexes: 1.08). Net: Pixie and Sprite +1 HP, Pixie alt +1 Defence.
- **Air line:** the ranged resist is gone (about -8% toughness). Air +1 HP. Air upg +1 Defence. Air alt: Whirling Gale is offence on counters (`offMult` about 1.10). Leave its body; it was 0.96x.
- **Water alt:** losing Frozen Heart is about -10% toughness, and the Frozen vulnerability adds a little offence. Water alt has 1.04x headroom, so no change.
- **Fire upg:** Ignite (2 turns of 40%) is stronger than Jumpstart for the model (`offMult` about 1.12). Fire upg was 0.93x, so it lands near 1.03x. No body change.
- **Fire alt:** losing the second counterattack costs offence. Static Build-up is utility (+0.5 util). Fire alt was 0.97x; give it +1 Attack.
- **Earth line:** `hit_cap` toughness from the model formula is 35% → x1.04, 30% → x1.08, 20% → x1.17, compared with the old resists at about x1.13 to x1.25. Earth base keeps roughly its value (+3 HP). Earth upg also loses Eruption (offence down about 8%), so give it +1 Attack and +4 HP. Earth alt is about even.
- **Psychic upg:** Feedback is unseen by the model. Give it `offMult` 1.08. Losing Arcane Storm costs about the same, so no change. **Psychic alt:** Focus block is utility (keep util 2.0). No change.
- **Firebird upg:** the model's gallop and breath strike are gone (both counted). Sunfall `offMult` about 1.15. Expect about 0.90x: give it +2 Attack. **Firebird alt:** loses an aura and a rider and gains a heal pulse (util +1). No change; check the pair gap stays at or under 0.10.

## 6. Risks

- **Fusion inheritance of SID-keyed rules** (Stone Body, Flutter Away, Psychic Feedback) needs the new propagation in `build_unit_kit_runtime_table.py`. Without it, 39 earth fusions and the psychic and pixie fusions lose their cards silently. This is the top risk.
- **`scatter` moving a unit after it is hit** is unproven. Pathing, the move animation and the AI not expecting the move are untested. Without the plugin, the card does nothing.
- **`ability_feedback`** queues damage in the middle of another unit's ability. If it kills the caster before the ability resolves, the ability may fire from a dead stack. Queue the damage to run after the ability.
- **`round_pulse` on `start_round`** as a unit passive with a rumble pattern is unverified. Natively, `start_round` actions are on buffs.
- **`scale_by_caster`** is a new buff-add rewrite. Until it exists, Ignite's damage is flat and weak late.
- **Cross-faction overlaps (other agents):** Rampart's War Unicorn takes the -2 Initiative rider that Air alt drops. Stronghold's Clobber and Fortress's Droning Wings use `force_unit_cd` and `blockEnergyRegen`; Mind Fray is a rider, not an aura, so it is a different shape. Rampart's Diamond Dragon already uses `hit_cap`; Stone Body uses different numbers on a different line.
