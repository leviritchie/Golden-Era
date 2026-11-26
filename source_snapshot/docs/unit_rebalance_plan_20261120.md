# Custom unit rebalance plan (2026-11-20)

Status: **proposal, awaiting owner decisions** (section 9). Nothing here is built or installed.
This is a dated plan, not an operational contract.

Survey data behind every number below (re-runnable scripts sit beside each file):

- Vanilla baseline, build 26615913: `V:\olden_port_work\unit_rebalance\vanilla\vanilla_units.csv`, `vanilla_tier_bands.md`
- Custom units as installed 2026-11-19: `V:\olden_port_work\unit_rebalance\custom\custom_units.csv`, `custom_findings.md`
- Faction ability rules and toolkit inventory: `V:\olden_port_work\unit_rebalance\faction_abilities_and_toolkit.md`

## 1. Where the custom units stand today

255 faction units (21 per faction, Factory 24), 17 neutrals, 142 Conflux fusion units.

**Stats are HoMM3 numbers copied 1:1**, with HoMM3 speed filling both Speed and Initiative and AI value used as squad value. Against vanilla units of the same tier (upgraded variants, custom median vs vanilla median):

| Tier | HP | Attack | Defence | Max damage | Speed | Initiative | Gold | Squad value |
|---|---|---|---|---|---|---|---|---|
| 1 | 6 vs 10 | 5 vs 4 | 3.5 vs 3.5 | 3 vs 3 | 5.5 vs 4 | 5.5 vs 5.5 | 60 vs 95 | 85 vs 96 |
| 2 | 16 vs 14 | 7 vs 6 | 6 vs 4 | 4 vs 5.5 | 6 vs 6 | 7 vs 7 | 155 vs 160 | 196 vs 164 |
| 3 | 24 vs 24.5 | 9 vs 7 | 8.5 vs 9 | 5 vs 7.5 | 7 vs 6 | 7 vs 7.5 | 240 vs 305 | 331 vs 347 |
| 4 | 35 vs 40 | 12 vs 12 | 10 vs 12 | 9 vs 13.5 | 7 vs 5 | 7 vs 6 | 400 vs 480 | 661 vs 500 |
| 5 | 47.5 vs 57.5 | 12.5 vs 15.5 | 12 vs 15 | 15 vs 17.5 | 7 vs 5 | 7 vs 7 | 600 vs 870 | 985 vs 1123 |
| 6 | 95 vs 120 | 17 vs 21 | 17 vs 23.5 | 24 vs 28.5 | 8 vs 6.5 | 8.5 vs 8 | 1100 vs 1650 | 1730 vs 2022 |
| 7 | 250 vs 250 | 22 vs 31.5 | 21 vs 30 | 50 vs 62.5 | 11 vs 8.5 | 11 vs 12 | 3500 vs 4050 | 6694 vs 6595 |

The systematic gaps:

- **Attack and Defence are far too low from tier 5 up.** 22 of 24 upgraded tier 6 units and 20 of 27 tier 7 units sit below the lowest vanilla Attack of their tier.
- **Speed is 1.5 to 2.5 hexes too high at every tier from 4 up**, because HoMM3 speed is also the movement range.
- **Damage is low at tiers 2 to 6, HP is low at tiers 1 and 4 to 6.**
- **Gold is 15 to 35% under vanilla** (tier 6 worst: 1100 vs 1650).
- **Squad value is scattered**: tier 4 runs 32% over vanilla, tier 5 runs 12% under, and single factions are far off (Conflux tier 2 is at 2.96x the vanilla median).

**Kits carry about 40% of vanilla complexity and do not grow with tier.** Mean abilities per unit: 1.4 custom vs 3.4 vanilla; at tier 7, 1.7 vs 4.2. 43 units have no ability at all and 125 have exactly one. Stronghold (0.9) and Fortress (1.0) are thinnest.

**Upgrade alternatives:** of 85 pairs, 19 have identical stats (all 8 Factory, all 7 Bulwark, Zealot/Priest, Wraith/Banshee, Power Lich/Lich Master, Sprite/Faerie) and 8 more differ in one stat. 20 upgrades have the same kit as their base.

**Chance effects:** none remain on the 255 faction units. Three remain elsewhere: fusion Hoarfrost (25% lose-turn on hit), neutral Azure Dragon Fearsome (10% skip), and the Hurricane-Psychic fusion's random-target active.

**Identity gaps**, the ten worst (full list in `custom_findings.md` section d): Dread Knight has no Death Blow; Efreet Sultan has no Fire Shield; Mechanic/Engineer cannot Repair; Dreadnought has no abilities; Unicorn has no resistance aura; Pegasus lost Magic Damper; Dwarves have no magic resistance; Angels have no Morale aura or hatred of Devils (no hatred exists on any unit); Magog's fireball is single-target; Cerberus attacks in a line instead of a three-headed sweep.

## 2. What vanilla does (the target)

- **Tier bands** as in section 1. The latest balance patch re-priced squad value upward at tiers 1 to 3 and 5, cut tier 6 gold, raised tier 7 Attack and Defence, pulled extremes in at tiers 4 to 6, and added actives broadly (138 to 157; units with no active 39 to 27).
- **An upgrade is mostly kit.** Stats barely move from base to upgrade (median +1 Speed, +1 to +2 Initiative); gold rises 33% at tier 1 up to 67% at tier 7.
- **The two upgrades are a trade at equal price.** In all 42 lines they share gold, squad value and growth. Stats are never all identical: typically 3 to 5 of the 7 differ, most often Initiative (36 lines) and Speed (33), by 1 to 2 points of Speed or Initiative, 2 to 5 of Attack or Defence, 15 to 25% of HP or damage. Four lines flip melee and ranged. The passive list differs in every line.
- **Kit size by tier** (median total abilities, excluding the attack-type marker):

| Tier | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| Base | 1.5 | 2 | 2.5 | 2 | 2 | 2.5 | 3.5 |
| Upgraded | 2.5 | 3.5 | 3.5 | 4 | 5 | 5 | 6 |

- **Focus costs:** 1 charge at tiers 1 to 2, 2 at tiers 3 to 6, 3 at tier 7. Cooldowns, per-battle charges and free actions are all in use.

## 3. Design rules

1. **Shape from HoMM3, scale from vanilla.** Each unit keeps its HoMM3/HotA profile relative to its tier-mates (who is the fastest tier 6, who is the tankiest tier 5), but the numbers are re-expressed inside the vanilla band for that tier. Method in section 4.
2. **Chance becomes Focus.** A HoMM3 proc becomes a Focus ability whose cost reflects chance times impact: frequent, mild procs become 1-Focus riders; rare, swingy ones (Death Blow, Death Stare, aging) become 2 to 3 Focus with a cooldown. Where the proc was the unit's whole identity and near-certain (Dendroid binding), it becomes a guaranteed passive at reduced strength. The three remaining chance effects are converted in the neutral/fusion wave.
3. **Alternates trade, never ladder.** Same gold, squad value and growth; at least three of seven stats differ; neither is better on every axis. Each faction has one **trade axis** drawn from the levers its faction ability rewards (section 5), so the choice matters most when you lean on that ability.
4. **Emergent, never wired.** A unit ability may only reference battlefield facts any army can produce: was attacked this round, has not moved, adjacent ally count, acted before the target, stack lost units, enemy is rooted. No unit ability names or reads a faction skill, its counters, or a faction tag. Test for every card: it must read as a complete, useful ability in an army with no hero skill at all.
5. **Kit size follows the vanilla table**, built from two layers:
   - a shared **keyword library** (about 40 passives that carry HoMM3 identity cheaply and recur across units: Magic Resistance, Fire/Mind/Spell Immunity by level, Hatred, Unlimited Retaliation, No Retaliation, Breath, Fear, Regeneration, Aura of Resistance, Undead, Construct...);
   - one **signature** per line (the thing only that creature does), normally an active on the upgrades.
6. **Native data first.** Abilities built from the game's own records are visible to the AI and the damage forecast; plugin-runtime mechanics are not. Runtime lanes are reserved for signatures that cannot be expressed natively.

## 4. Stat method

**Step 1: rank-preserving remap.** For each stat and tier, take the unit's percentile among the HoMM3/HotA creatures of the same level and place it at the same percentile of the vanilla band (min to max, anchored on the median). The Dread Knight stays the hardest-hitting tier 6; the Dendroid stays the slowest tier 5.

**Step 2: split Speed from Initiative.** HoMM3 speed maps to **Initiative** by the remap. **Speed** (hexes) is assigned by movement class inside the vanilla speed band: heavy walker, walker, cavalry/charger, flyer, teleporter. This removes the blanket +2 hexes while keeping fast things acting first.

**Step 3: price.** Gold and squad value go to the vanilla tier price (within the band; position by the unit's stat total), and both upgrades of a line get the same numbers, as the parity contract already enforces. Weekly growth already matches vanilla medians and stays.

**Step 4: budget check.** Fit a power model on the 126 vanilla faction units (stat block to squad value; the residual is what vanilla pays for kits at each tier). Squad value is the even blend of the model's value and the tier median, shared by the two upgrades of a line; gold follows the tier's gold-per-squad-value ratio. As built for the pilot the model only prices: vanilla units themselves scatter about 25% around it, so a 10% gate would reject vanilla. The hard gates are the tier bands and the alternate rules (`tools/validate_homm3_unit_design_table.py`).

**Step 5: uncarded leftovers.** 61 units carry Morale/Luck inherited from their donor unit that no card shows, and three units have an uncarded all-adjacent alternative attack. Each gets either a card or removal.

## 5. Trade axis per faction

Levers are from the current rules of each faction ability.

| Faction | Ability levers | Trade axis for the two upgrades |
|---|---|---|
| Rampart | Avenger: free melee strikes by stacks near the attacker, highest Initiative first; shooters strike with their melee profile | **Striker vs Ward.** One side has Initiative and a melee on-hit rider (wants the free strike). The other is durable, punishes or soaks being attacked, and holds the formation together. |
| Stronghold | Warcry: unbroken chain of attacks/abilities; moving without attacking, Wait or Defend breaks it | **Opener vs Finisher.** One side reaches melee on turn one or has an act-in-place active that keeps a chain alive. The other has slower, bigger Attack-scaling hits that cash the chain in. |
| Fortress | Predator Instinct: big bonus vs paired prey, penalty vs everyone else; area damage penalised | **Hunter vs Warden.** Mobile single-target burst that can reach its prey, against control and retaliation units whose value (petrify, poison, slow) does not depend on the damage multiplier. |
| Inferno | Gating: reserved stacks arrive in round 2 on a random hex, later in the enemy half | **Breacher vs Holder.** Units that want to appear among enemies (area around self, no retaliation, Fire Shield) against units that survive round 1 short-handed (ranged, durable, high Initiative). |
| Bulwark | Runes: levels from attacking, countering, being damaged and Defend; every 3 levels add stats | **Tempo vs Bastion.** Many small actions and extra retaliations (fast stacking) against front-loaded stats with Defend and damage-soak payoffs (slow stacking, higher floor). |
| Tower | Artificing: borrowed enemy passives grafted onto Tower lines | **Chassis vs Specialist.** Multi-hit, ranged or large-HP bodies with a lean kit (a graft multiplies on them) against a strong native kit on a single-hit body. |
| Conflux | Fusion: merged unit takes the host's attack, the higher Attack/Defence, the faster Speed/Initiative, both kits | **Host vs Donor.** An excellent attack shape with plain stats against lopsided stat spikes and passives worth inheriting. |
| Castle | Elite Strategem: choose enemy deployment (spread, compressed, surrounded) in neutral fights | **Cleave vs Lance.** Area and multi-target attacks against single-target burst and reach. |
| Dungeon | War Captives (post-battle; Eat restores a share of each stack's losses) | **Reckless vs Sustained.** High-damage units that trade bodies against self-sustaining ones. |
| Necropolis | Necromancy (post-battle; skeletons from living enemy value) | No combat lever: classic **role flip** (melee/ranged, drain/curse), plus a unit-level corpse economy (units that leave, consume or guard corpses). |
| Cove | Treasure Hunting (map; Speed and Despair picks) | No combat lever: **boarding vs broadside** (melee rush against gunpowder ranged), with Focus-fed shots as the internal theme. |
| Factory | Logistics Network (economy) | No combat lever: **crewed vs automated** (living units that Repair and buff against constructs that are immune and self-contained). |

For the last four the brief's condition applies (the ability does not affect combat), so the axis comes from the faction's HoMM3 character instead.

## 6. Pilot as built: Rampart

Built 2026-11-20 from `custom_factions/unit_designs/homm3_rampart.json` (not installed). Abilities are built with whatever the toolkit needs: game data keys composed freely (not only in combinations a vanilla unit ships), and plugin rules where data cannot express the design (owner, 2026-11-20: do not cut designs down to donor effects). Upgrade and alternate share gold and squad value. Stats read HP, Attack/Defence, damage, Speed, Initiative. (P) passive, (nF) active Focus cost.

| Line | Base | Striker (wants the avenging strike) | Ward (wants to be attacked) |
|---|---|---|---|
| T1 Centaur | **Centaur** 10 HP, 4/3, 2-3, Spd 4, Init 5; 75 gold. *Gallop* (P) +5% damage per hex moved. | **Centaur Captain** 11 HP, 5/3, 2-4, Spd 5, Init 6; 100 gold. *Gallop* 10%. *Lead the Charge* (1F, free action): adjacent allies +1 Initiative this round. *Wheeling Charge* (1F): strike and return to its hex. | **Centaur Ranger** (ranged) 10 HP, 4/4, 2-3, Spd 4, Init 5. *Skirmisher* (P): no melee penalty. *Pinning Shot* (1F): half damage, target -2 Speed for 2 rounds. |
| T2 Dwarf | **Dwarf** 16 HP, 5/6, 2-4, Spd 3, Init 4; 110 gold. *Magic Resistance 20%*. *Sturdy* (P): -10% from basic attacks. | **Dwarf Battlerager** 16 HP, 8/6, 3-5, Spd 4, Init 6; 150 gold. *Magic Resistance 20%*, *Sturdy*. *Grudge* (P): +25% damage to any enemy that has damaged it this battle. *Reckless Swing* (1F): 150% strike; the Battlerager then takes +25% damage until its next turn. | **Battle Dwarf** 18 HP, 6/8, 2-4, Spd 3, Init 4. *Magic Resistance 40%*, *Alert* (2 retaliations). *Shield Wall* (P): -10% damage per adjacent ally, up to -30%. *Runic Guard* (2F, free action). |
| T3 Elf | **Wood Elf** (ranged) 15 HP, 7/6, 4-6, Spd 5, Init 7; 205 gold. *Evasive* (P): -25% from ranged. *Aimed Shot* (1F): 130% shot. | **Elf Wardancer** (melee) 24 HP, 9/6, 5-7, Spd 7, Init 10; 300 gold. *Double Strike*, *Evasive*. *Dance of Blades* (2F): strikes every adjacent enemy at full damage, no retaliation. | **Grand Elf** (ranged) 17 HP, 9/8, 4-7, Spd 5, Init 8. *Double Shot*, *Sharpshooter*, *Evasive*. *Covering Fire* (2F, free action): until the end of the round, shoots the next enemy that attacks an adjacent ally. |
| T4 Pegasus | **Pegasus** 34 HP, 9/9, 8-11, Spd 6, Init 8; 340 gold. *Magic Damper* (+1 enemy spell cost), *Evasive*. | **Gold Pegasus** 36 HP, 13/9, 9-12, Spd 7, Init 10; 490 gold. *Magic Damper* +2, *No Retaliation*. *Swoop* (P): +5% damage per hex. *Dive* (2F): flies to any enemy and strikes it for 130%, no retaliation. | **Silver Pegasus** 42 HP, 9/13, 8-11, Spd 8, Init 9. *Magic Damper* +2. *Wing Shelter* (P): adjacent allies -15% from ranged. Keeps its reposition active. *Carry Off* (2F): swaps places with an ally within 4 hexes. |
| T5 Dendroid | **Dendroid Guard** 70 HP, 13/15, 12-16, Spd 3, Init 4; 525 gold. *Binding* (roots on hit, 2 rounds). *Bark Skin* (P): -20% from melee. | **Dendroid Soldier** 80 HP, 17/15, 15-19, Spd 3, Init 5; 760 gold. *Binding*, *Bark Skin*. *Strangle* (P): +30% damage to rooted enemies. *Lash Out* (2F): reach strike that roots. *Crushing Blow* (2F): 150% strike that roots. | **Dendroid Shaman** 85 HP, 13/18, 12-16, Spd 3, Init 5. *Binding*, *Bark Skin*. *Deep Roots* (P): unlimited retaliation. *Sap Mend* (2F, 2 charges): heal and revive an ally. *Thicket* (P): adjacent enemies -1 Speed. |
| T6 Unicorn | **Unicorn** 105 HP, 20/21, 20-25, Spd 6, Init 7; 1095 gold. *Aura of Resistance* 20% (adjacent allies). *Impale* (P): +5% per hex. *Blinding Strike* (3F). | **War Unicorn** 115 HP, 23/21, 22-28, Spd 8, Init 9; 1575 gold. *Aura* 20%, *Impale* 10%, *Alert*. *Blinding Strike* (2F, 3-round cooldown). | **Pristine Unicorn** 135 HP, 20/26, 20-25, Spd 6, Init 8. *Aura* 30% within 2 hexes, *Alert*. *Dazzle* (P): attackers lose 2 Attack. *Radiant Armor* (kept). *Purifying Horn* (2F): dispels negative effects from one adjacent ally. |
| T7 Dragon | **Green Dragon** 230 HP, 29/29, 45-55, Spd 7, Init 10; 2265 gold. *Breath*. *Spell Immunity* 1 to 3. *Dragon Scales* (P): -25% from ranged. | **Gold Dragon** 275 HP, 36/32, 52-65, Spd 9, Init 13; 3730 gold. *Breath*, *Spell Immunity* 1 to 4, *No Retaliation*, *Dragon Scales*, *Fearless* (immune to sleep, blind and berserk). *Fury of the Wood* (3F): 130% breath attack, then returns to its start hex. | **Diamond Dragon** 325 HP, 30/38, 48-58, Spd 7, Init 11. *Breath*, *Spell Immunity* 1 to 3, *Alert*. *Adamant Hide* (P): -25% from ranged and melee. *Diamond Scales* (P): no single hit deals more than 20% of the stack's full health. *Guardian Roar* (3F, free action): taunt. |

Why these fall out of Avenger without touching it: the Striker column's on-hit riders (root, blind, rage, double strike) fire again on every free avenging strike, and their Initiative wins the avenger slot. The Ward column makes the enemy's choice of target worse (taunt, damage reduction, extra retaliations) and keeps allies inside avenging range. In an army without Avenger each card still does its job.

Identity restored: Dwarf magic resistance, Pegasus Magic Damper, Unicorn Aura of Resistance, Dragon spell immunity levels and breath.

All eight abilities of the first draft that the first build had swapped for donor-shaped ones are restored:

| Ability | How it is built |
|---|---|
| Lead the Charge, Thicket, Fury of the Wood, Fearless | Game data, in combinations no vanilla unit uses (area buff on allies, Speed aura on enemies, breath shape on a strike-and-return, effect immunity). |
| Dance of Blades, Dive, Purifying Horn | Game data: the whirlwind shape as a Focus ability at full damage; a jump aimed at one enemy unit with unlimited range; the dispel as a range-1 single-ally cast. |
| Reckless Swing drawback | Game data: a hidden passive that fires when the unit uses an ability and puts a one-round +25% damage-taken effect on itself. It fires on any ability, so the builder refuses it on a unit with more than one active. |
| Shield Wall, Diamond Scales | Plugin rules on the damage step. Shield Wall counts adjacent friendly stacks (cap 30%) and applies to every damage source. Diamond Scales caps the final damage of a hit at 20% of the largest health total the stack has had in the battle. The damage forecast shows neither. |
| Carry Off | Game data (the native swap). The player selects the Pegasus first, then the ally. |
| Grudge, Strangle | Plugin rule on the damage step, keyed by unit (`Homm3UnitKitRuntime.cs`, table generated from the design table). The damage forecast does not show the bonus. |
| Covering Fire | Game data arms a buff; the plugin queues the reaction shot through the same attack queue Avenger uses, in any army. One shot per arming. |

Nothing in the built cards now differs from the first draft.

Not yet seen in game (each needs a look after install): everything in the table above, the two-step Carry Off targeting, Dazzle, Sap Mend's amounts, and the aura strengths. The three with the most doubt: where the Pegasus lands when Dive targets a unit (the only vanilla unit-targeted jump destroys itself on arrival), whether the Reckless Swing drawback lasts through the enemy's turn or expires at once, and Dance of Blades together with Double Strike.

## 7. Toolkit use and limits

Available now and barely used: 16 native triggers (custom units use two), 45 attack patterns, about 70 buff stat keys (taunt radius, untargetable, extra action, damage caps, damage per hex, extra retaliations, armour penetration), 62 mechanics (heal/revive/drain, corpse consumption, dispel/steal/copy buffs, teleport/push/swap, Focus and action-point gain, cooldown forcing, summons, traps), and the mod runtime lanes (queued free attacks, per-hit damage scaling, action/round events, on-hit buff rewrite, delayed entry).

Limits the designs must respect:

- A buff cannot change a unit's attack shape; shape changes need a separate attack or active.
- There is no ammo and no unit size field in this game.
- No ownership transfer of stacks, no source-bound buffs.
- Code-driven push/teleport fails live; use the native mechanics.
- The AI and the damage forecast ignore plugin-side mechanics.
- Per the 2026-11-12 audit, **no custom unit ability is individually runtime-proven**. The keyword library is therefore proven once per keyword in a battle test, then reused.

Three things to prove before designs lean on them: a Hatred keyword (typed outgoing damage modifier by unit family), reaction shots (*Covering Fire*), and forced targeting at range (*Guardian Roar* via taunt radius).

## 8. Delivery

**Source of truth.** One design table per faction (stats + kit per unit) replaces the 1:1 HoMM3 copy and the 211-entry 2026-06-25 adjustments contract as the stat source. The pair-parity contract keeps its price rule and loses its stat floor, which contradicts rule 3.

**Gates** (all static, seconds each, generated from the vanilla CSV):

- tier band: every stat inside the vanilla band for its tier, exceptions listed with a reason;
- alternates: equal price, at least three stats differ, neither dominates;
- kit size inside the tier's range; no chance text or chance stat;
- price: squad value from the power model blended with the tier median, equal for both upgrades.

The existing exact-value validators (balance-adjustment readback, Fortress alt stats, ability redesign costs) are re-pinned per faction as it lands.

**Order.**

1. Tooling: HoMM3 percentile table, remap, power model, the four gates.
2. Keyword library: specify, build natively, prove each keyword once in battle.
3. Pilot faction end to end: cards approved, built, installed, in-game check.
4. Combat-ability factions: Stronghold, Fortress, Inferno, Bulwark (parallel lanes, one per faction).
5. Tower and Conflux (including the 142 fusion units, which inherit from the 15 elementals).
6. Castle, Dungeon, Necropolis, Cove, Factory; then the 17 neutrals.
7. Whole-roster pass: cross-faction duels at equal gold, ability text audit, catalog doc refresh.

Each faction's cards come to the owner for review before anything is built.

## 9. Decisions (accepted 2026-11-20)

1. **Speed** comes down to the vanilla bands; HoMM3 speed drives Initiative.
2. **Price** follows the vanilla tier price, rank preserved.
3. **Alternates** may be re-conceived, keeping names and models.
4. **Pilot faction** is Rampart (section 6).
5. **Non-combat factions** (Necropolis, Dungeon, Cove, Factory) use the HoMM3-character axes in section 5.

## 10. As built: all factions (2026-11-21)

Installed to Golden Era 2026-11-21 (DLL `e4075e17`, Core `137b252b`; commits `bef6ce6b04`, `382a510f83`). Not yet checked in game; one row per faction in `docs/ingame_check_queue.md`.

**How ability power is valued.** `tools/release_port/unit_power_model.py` scores each unit on effective output: expected damage over a three-round fight with the whole kit (range falloff, time to contact, Double Strike/Shot, area shapes, counters, each Focus ability per use, buffs and debuffs by their stat effect) times effective HP, times weekly growth. It is calibrated on the 126 vanilla faction units. A unit must land within 0.85 to 1.15 of the vanilla median for its tier and form, the two alternates within 0.10 of each other. `tools/release_port/unit_design_lab.py check --faction <f>` runs this in seconds; `validate_homm3_unit_design_table.py --core` gates the built Core.

**Rules added by the owner on 2026-11-20.** A strong kit is paid for with a smaller body, not a weaker card (exceptionally strong passives excepted). No upgrade has any stat below its base (vanilla: 1 exception in 588 pairs).

**What the model does not price** (those units were trimmed by hand with `powerTarget`): effects applied by basic attacks (poison, on-hit debuffs), armour penetration stored on a passive, life drain, control, heals, summons. Units most likely to be off: Fortress Wyvern, Gorgon and Serpent Fly upgrades; Cove Nix line and Sea Witch line; Conflux Psychic upgrades and Phoenixes; Factory Glassworm and Clockwork.

**Known compromises.** Bases were sized up from HoMM3-sized bodies (they scored 0.5 to 0.75), and squad values follow the model, so several are lower than before (Cavalier 1946 to 1223, Angel 5019 to 3731). Stronghold: Hobgoblin is the slower finisher; Ancient Behemoth has 50% Armor Rend, not 80%. Castle: Monk line and Cavalier upgrades keep an uncarded Morale bonus. Fortress: Swarm of Bees, Dragonflight, Inner Flame and Hksmilla's Rampage are gone. Kept abilities keep their old card text. The 17 neutrals are not redesigned.

**Plugin rules the designs wished for**: built on 2026-11-21, see section 11.

## 11. Wished rules as built (2026-11-21)

The first all-faction pass shipped fifteen rules as plain data stand-ins. They are now built. "Data" means Core rows
only; "plugin" means `Homm3UnitKitRuntime.cs` (rule table `Homm3UnitKitRules.g.cs`, generated from the design tables).
None of them has been seen in game yet.

| Rule | Units | How it is built | Open point |
| --- | --- | --- | --- |
| Hatred | Genie line and Efreet line; Angel line and Devil line; Titans and Black Dragons (both ways, +50% Damage) | Data. Keyword `hatred`: `stats.outDmgModsByTargetTags` against a tag that the build puts on the hated unit rows | Vanilla uses this stat on one unit (dragon hunter) |
| Rotating wish | Master Genie "Wish" (replaces Wish of Might and Wish of Shelter) | Plugin. `rotate` on the kit entry; the buff-add hook turns each use into the next of +4 Attack, -20% Damage taken, +2 Initiative, counted per Genie stack per battle | If the game also adds buffs while the AI weighs a move, the order could skip a step |
| Pikeman against charges | Pikeman line "Braced Pikes" | Data. Keyword `brace`: -25% Damage from any unit whose Damage grows per hex moved (tag `h3_kit_charger`, 57 rows) | Deviation: it does not cancel the charge bonus itself. The plugin cannot read how far the attacker moved |
| Army Morale | Angel line "Aura of Valor" (was +2/+3 Attack to adjacent allies) | Data. Keyword `army_stat`: `globalPassives`, all friendly creatures +1 Morale, strongest only | None known; same shape as the Devil's Ill Omen |
| Freeze buildup | Ice Elemental "Frostbite" | Plugin plus data. `escalate` on the kit entry: a hit on a target that still has Frostbite applies Frozen (skip one turn, no counterattack), then Thawed blocks another freeze for 3 rounds. Frostbite now lasts to the end of the next round | The one-round length of Frozen relies on `maxDuration` |
| Fire Shield | Energy Elemental (replaces Corona); Efreet Sultan already had it | Data. Keyword `reflect`: `revenge_damage` flat, 5 Magic Damage per creature in the stack to each melee attacker | The per-creature reading of the flat values is not confirmed in game |
| Elemental weaknesses | Air: Lightning Bolt, Chain Lightning. Water: Fireball, Firewall, Armageddon. Fire: Ice Bolt, Circle of Winter. Earth: Cave In, Stone Fangs (double Damage) | Data. `weak` on the existing immunity or resist card: positive `inDmgMods` on the spell's damage tag | Whether `inDmgMods` matches per-spell damage tags is not confirmed |
| Always-return attack | Harpy and Harpy Hag "Hit and Run" (was a 1 Focus ability) | Data. Keyword `always_return`: sets `returnToStartAfterAttack: true` on every melee `defaultAttacks` entry (counterattacks unchanged) | Prior passive `sequenceEffect: return_to_start_after_attack` failed in the 2026-11-24 test; `returnToStartAfterAttack: true` matches stock `assassin`/`sunlight_cavalry_upg_alt` attack rows |
| Act in place | Stronghold Warcry | Plugin. A creature that used an ability and then waits or defends no longer breaks the Warcry | None known |
| Revenge | Haspid | Plugin rule `loss_fury`: +1% Damage per 1% of the stack lost this battle, up to +50% | The damage forecast does not show plugin rules |
| Construct-only Repair | Mechanic line | Data. The cast accepts only rows tagged `h3_kit_construct` (15 rows: Factory automatons and dreadnoughts, Tower gargoyles and golems, two vanilla constructs) | Whether a fully dead construct stack can still be picked |
| Death damage number | Automaton line "Volatile Reactor" | Text only: the card now says 10 Magic Damage multiplied by the hero's level, which is what the copied vanilla block carries | The hero-level multiplier is read from the data, not seen in game |
| Short debuffs | Yeti line "Shrug Off" | Data. Keyword `short_debuffs`: `stats.maxInComingNegativeBuffDuration` 1 | Vanilla grants this stat through a sub-skill, not a unit row |
| Defend multiplier | War Mammoth "Tusker Guard" | Data. The Defend buff is now +50% Defence (`defencePerc`) instead of -25% Damage | None known |
| Corpse guarding | Skeleton Archer upgrade "Grave Watch" | Data. Keyword `corpse_ward`: `globalPassives` puts the corpse-consumption disablers on every friendly creature | Not known whether a global passive still covers a dead stack; it also stops the own side's Bone Harvest |
| Corpse-count scaling | Skeleton Warrior "Grave Tide" | Plugin rule `death_toll`: +5% Damage per stack fallen this battle (either side), up to +30% | A revived stack still counts as fallen |

Kit entries can now carry `offMult` / `toughMult` so the power model prices what the built rows cannot show.

**Tower Artificing.** Catalog regenerated: 699 schematics, 473 graftable. The graft slot is 10 bits wide (was 9; low bits unchanged, so existing saves read the same). 162 cards that change an attack's shape or hit effect cannot be grafted.
