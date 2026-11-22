# Hidden damage conditional cap (option B: max 2 per faction)

Draft only (2026-11-21). Nothing here is built.

**Counts:** plugin damage-step rules (`Homm3UnitKitRuntime`) that change Damage dealt or taken based on a condition. Each card kind counts once per faction, even across several rows of one line.
**Does not count:** native data (buff stat keys, tag mods, triggers, sequence effects), queued attacks (guard_strike, zone_shot, covering_fire, overwatch), kill_refund, extra-turn-on-kill and the H hooks.

Donors were checked in `V:/olden_port_work/unit_rebalance/core_overlay_work/Core.zip` (read with zipfile, not extracted).

## Summary

| Faction | Before | Kept | Converted to native |
|---|---|---|---|
| Castle | 3 | Stand Ground, Retribution | Challenge |
| Stronghold | 3 | Pack Hunt, Pulverize | Safety in Numbers → Expendable |
| Rampart | 5 | Shield Wall, Diamond Scales | Strangle (same card), Grudge (same card), Hunter's Eye (reworked) |
| Tower | 2 | Swarm Fire, Relentless Blades | none |
| Fortress | 4 | Quarry, Gore | Shatter (same card), First Sting → Deadly Sting |
| Bulwark | 2 | Stubborn Fleece, Pent-up Fury | none |
| Inferno | 4 | Run Down, Hellfire Burst | Fan the Flames (same card), Bloodied Fury (same card) |
| Necropolis | 3 | Exsanguinate, Death Blow | Grave Tide (same card) |
| Dungeon | 3 | Ambush, Wall Slam | Carrion Wings → Foul Swoop |
| Conflux | 1 | Opening Gust | none |
| Cove | 2 | Run Aground, Revenge | none |
| Factory | 1 | Bounty | none |

"Same card" means the text barely changes and only the build moves to native data.

## The native trick used below: tag mods on a buff

Buffs can carry `inDmgModsByCasterTags` and `outDmgModsByTargetTags`, the same as units. For example, `homm3_tower_graft_716` has `inDmgModsByCasterTags [{"t":"h3_kit_charger","v":-0.25}]` and `homm3_tower_graft_60` has `outDmgModsByTargetTags [{"t":"dragon","v":1.0}]`. The builder already adds its own unit tags, such as `h3_kit_charger`, `h3_kit_hated_by_*` and `h3_kit_construct`.

That turns "+X% vs a target carrying buff B" into native data: give B the line `inDmgModsByCasterTags [{"t":"h3_kit_<reader>","v":X}]` and give the reading unit the tag `h3_kit_<reader>`. The forecast shows it because it is a damage mod on the target.

## Castle (3 → 2)

**Hidden conditionals:** Stand Ground (turn_state), Retribution (retribution; Monk and Zealot count once), Challenge (duel_mark).

**Kept (owner):** Stand Ground and Retribution. Smite (Monk alt) is a native tag mod, so it does not count.

| Unit | Card | P/A | Text | Build |
|---|---|---|---|---|
| h3_swordsman_upg (Crusader) | Challenge | A, 2 Focus, CD 2 | Performs a Melee attack. Until the end of the next round, the target deals -50% Damage to creatures other than Crusaders. | `castle_strike` (counter true) + buff `h3_kit_castle_challenged_effect` (cloneOf `hydra_debuff`, outAllDmgMod -0.5, `outDmgModsByTargetTags [{"t":"h3_kit_challenger","v":0.5}]`, maxDuration 2). Add the unit tag `h3_kit_challenger` to h3_swordsman_upg. |

## Stronghold (3 → 2)

**Hidden conditionals:** Safety in Numbers (adjacent_ally_ward, on h3_goblin, _upg and _upg_alt, counts once), Pack Hunt (adjacency) and Pulverize (counter_state). Surprise Attack is native.

**Kept (owner):** Pack Hunt and Pulverize. The owner's count missed Safety in Numbers, which ships on the Goblin line, so it is converted here.

| Unit | Card | P/A | Text | Build |
|---|---|---|---|---|
| h3_goblin, h3_goblin_upg, h3_goblin_upg_alt | Expendable | P | When this stack is destroyed, adjacent friendly creatures gain +2 Attack until the end of the next round. | Passive on the `unit_died` trigger (shape: peasant passive 0, allegiance self), cast at allies only using the shape of `minos_upg_alt` `attack_rumble_x1_x100`. It applies buff `h3_kit_stronghold_expendable_effect` (cloneOf `sunlightCavalry_buff_1`, stats {offence 2}, maxDuration 2). |

The new Gang Mark, Gore, Hamstring and Siege Breaker cards are all native. Name clash: the Orc alt passive "Hamstring" now shares its name with the Orc line's active Hamstring. Rename one of them; Cripple is suggested for the passive.

## Rampart (5 → 2)

**Hidden conditionals:**
- Hunter's Eye (adjacency; h3_centaur and h3_centaur_captain)
- Shield Wall (adjacent_ally_ward)
- Grudge (grudge)
- Strangle (damage_vs_buff ent_root)
- Diamond Scales (hit_cap)

Covering Fire is a queue, so it does not count.

**Kept:**
- Shield Wall: the shipped Battle Dwarf signature. A native ward needs adjacency, which data cannot express.
- Diamond Scales: no native equivalent. `maxInDmg` is an absolute cap, not a percent of max HP.

| Unit | Card | P/A | Text | Build |
|---|---|---|---|---|
| h3_dendroid_soldier | Strangle | P | Deals +30% Damage to creatures rooted by Dendroids. | Binding (all 3 Dendroid rows) and Overgrowth apply `h3_kit_rampart_bound_effect` (cloneOf `ent_root` + `inDmgModsByCasterTags [{"t":"h3_kit_strangler","v":0.3}]`) instead of vanilla `ent_root`. Add the tag `h3_kit_strangler` to h3_dendroid_soldier. |
| h3_dwarf_battlerager_upg_alt | Grudge | P | Whenever this creature takes Damage, adjacent enemies bear its Grudge for the rest of the battle: they take +25% Damage from Battleragers. | `when_damaged_adjacent_debuff` (shape: h3_gnoll_upg_alt, unit_took_damage self → swirl) with buff `h3_kit_rampart_grudge_effect` (negative, infinite duration, `inDmgModsByCasterTags [{"t":"h3_kit_grudge","v":0.25}]`). Add the tag `h3_kit_grudge` to the unit. |
| h3_centaur / h3_centaur_captain | Hunter's Eye | P | Attacks ignore 20% (Captain: 30%) of the target's Defence. | `castle_stat` armorPen 0.2 / 0.3 (donors: h3_angel_upg 0.25, h3_pikeman_upg_alt 0.3). |

## Tower (2): no change

Swarm Fire and Relentless Blades. Arcane Volley is a queue. Perch, Granite Riposte and Gathering Momentum are native.

## Fortress (4 → 2)

**Hidden conditionals:** First Sting (unhurt), Shatter (damage_vs_buff), Gorgon alt Gore (damage_vs_buff Corroded, abilityOnly) and Quarry (quarry). Raider is a native tag mod.

**Kept:**
- Quarry: the faction's hunt verb.
- Gore: it cashes in the Gorgon alt's own Corrosive Breath (`h3_kit_fortress_corroded_effect`). It is abilityOnly, which the tag trick cannot express.

| Unit | Card | P/A | Text | Build |
|---|---|---|---|---|
| h3_basilisk_upg_alt | Shatter | P | Deals +50% Damage to creatures it has petrified. | Stone Gaze applies `h3_kit_fortress_shatter_stone_effect` (cloneOf `medusa_stone` + `inDmgModsByCasterTags [{"t":"h3_kit_shatter","v":0.5}]`). Add the tag `h3_kit_shatter` to the unit. |
| h3_serpent_fly_upg_alt | Deadly Sting | P | Always deals maximum Damage. | Infinite self buff cloned from `magic_sharp_edge_effect_0_special`, keeping only `alwaysMaxDmg true`. Replaces First Sting. |

## Bulwark (2): no change

Stubborn Fleece (first_hit) and Pent-up Fury (stored_fury). This assumes Duck Behind Shields is built from a native trigger. If it is built as a plugin first-hit rule, Bulwark goes to 3.

## Inferno (4 → 2)

**Hidden conditionals:** Run Down (moved; 3 rows, counts once), Hellfire Burst (crowd), Bloodied Fury (loss_fury) and Fan the Flames (damage_vs_buff Burning).

**Kept:**
- Run Down: the swap and charge verb.
- Hellfire Burst: the crowd winner in REVIEW section 1 #6.

| Unit | Card | P/A | Text | Build |
|---|---|---|---|---|
| h3_efreeti | Fan the Flames | P | Deals +25% Damage to Burning creatures. | The three new Inferno Burning buffs each get `inDmgModsByCasterTags [{"t":"h3_kit_fan_the_flames","v":0.25}]`. Add the tag to h3_efreeti. |
| Bloodied Fury unit (per inferno.md) | Bloodied Fury | P | Whenever this creature takes Damage, it deals +5% Damage until the end of the battle, up to +40%. | `when_damaged_self_buff` (shape: h3_armadillo_upg_alt Curl Up, unit_took_damage self → self) with a buff of outAllDmgMod 0.05, stacked by the escalate hook up to 8 times, infinite duration. |

## Necropolis (3 → 2)

**Hidden conditionals:** Grave Tide (death_toll, shipped on h3_skeleton_upg; the draft marks it kept but did not count it), Exsanguinate (damage_vs_hp) and Death Blow (damage_vs_buff). Mark of Death is native. Deathly Plunge is kill_refund.

**Kept:** Exsanguinate and Death Blow. Death Blow carries the faction verb.

| Unit | Card | P/A | Text | Build |
|---|---|---|---|---|
| h3_skeleton_upg | Grave Tide | P | Whenever any stack dies, deals +5% Damage until the end of the battle, up to +30%. | Passive on `unit_died` with both allegiances (shape: godslayer_upg_alt, allegiance [self, enemy]) → self buff outAllDmgMod 0.05, escalate up to 6 stacks, infinite duration. |

## Dungeon (3 → 2)

**Hidden conditionals:** Ambush (unacted_target), Carrion Wings (spent_counter) and Wall Slam (wall_slam). Vigilant Eye is a queue (overwatch). Headlong uses the native `h3dungeon_reckless`.

**Kept:**
- Ambush: REVIEW section 1 #3 winner, and the timing verb.
- Wall Slam: it combos with Bull Rush and Cave-In.

| Unit | Card | P/A | Text | Build |
|---|---|---|---|---|
| h3_harpy_upg (Harpy Hag) | Foul Swoop | P | Basic attacks stop the target from making Ranged attacks until the end of the round. | `on_hit_buff` with buff `h3_kit_dungeon_fouled_effect` (cloneOf `magic_twilight_effect`, disablers `[{"ability":"all","attack":"shoot"}]` only, maxDuration 1). Replaces Carrion Wings. |

## Conflux (1), Cove (2), Factory (1): no change

- Conflux: Opening Gust. Frozen +25% is a native buff. Psychic Feedback is a queue.
- Cove: Run Aground and Revenge.
- Factory: Bounty. Guardian Protocol is an H hook.

## Collisions checked

- **Against REVIEW section 1 tricks:**
  - Foul Swoop is not Paralyzing Sting, Petrifying Strike or Twilight: it blocks shooting only and does not skip a turn.
  - Deadly Sting is not a Sharp Edge copy on any other unit.
  - The armorPen on Hunter's Eye does not reuse a section 1 trick. Castle armorPen units are a separate faction, so it is not a within-faction duplicate.
  - The counter-damage version of Hunter's Eye was rejected because it is too close to Conflux Opening Gust (#11).
- **Against the reserved resist replacements:** no replacement uses or resembles Scurry, Duck Behind Shields, Momentum Hide, Shrug Off, Corroding Hide, Iron Rush, Updraft, Wing Shield, Climb Away, Tailwind or Gathering Storm. All of those are taken-damage reductions; none of the new cards reduces taken Damage.
- **Within each faction:**
  - Expendable (+Attack on death) differs from Gang Mark and Gore, which are debuffs.
  - Bloodied Fury (+% Damage dealt, battle-long) differs from Blood Rage and Pent-up Fury in stat and duration.
  - Grave Tide is close to Castle's Vengeance of Heaven, but that card is in another faction and is not a section 1 entry.
  - Grudge, Cinder Skin, Bog Curse and Acid Blood share the trigger shape but have different effects.
  - Foul Swoop does not duplicate Venom (DoT) or Gang Mark (-Defence).

## Flags

1. **There are no undead, demon, shooter or flyer tags on h3 units.** Only vanilla units carry undead (22), demon (23) and dragon (21). Shooter is on just 3 units, and flying is the stat moveType `fly`, not a tag. The section 1 tag-mod cards (Smite vs undead and demons, Raider vs shooters, Wind Reader and Bedrock vs flyers) need new `h3_kit_undead`, `h3_kit_demon`, `h3_kit_shooter` and `h3_kit_flyer` unit tags stamped by the builder, or they will miss every h3 target.
2. **Vanilla petrify already doubles Damage.** `medusa_stone` carries inDmgMods normal_damage +1.0, a skip turn, the counter disabler and magic immunity. Shatter's +50% stacks on top of that, so check the power before ship.
3. **Challenge depends on how mods stack.** If percent mods multiply instead of adding, the exemption tag needs v 1.0 instead of 0.5. Fallback: a plain -30% outAllDmgMod debuff.
4. **Expendable depends on whether a dead unit can cast from its own hex** on `unit_died`. The peasant donor proves the trigger, not the cast at an area.
5. **Grudge only marks adjacent enemies**, so ranged attackers escape it. Casting a buff on the attacker is unproven: `revenge_damage` reaches the attacker, but only as damage.
6. **The tag trick narrows Strangle and Shatter to their own buffs.** Roots from vanilla ents and petrify from vanilla medusas no longer trigger them.
7. **Grave Tide counts deaths on both sides.** The unit_died trigger with both allegiances is proven on godslayer_upg_alt.
