# Unit ability variety pass: review of the 12 drafts (2026-11-21)

For owner approval. This file reviews the twelve faction drafts in this folder against `BRIEF.md` and the current tables in `custom_factions/unit_designs/`. Nothing has been built. The drafts, tables and code are unchanged.

Read it in this order:

- Section 1 settles what clashes across factions.
- Section 3 is the part to skim for creativity.
- Section 5 lists the calls only you can make.

Where this review overrides a draft, the per-faction line is marked **(R)**.

---

## 1. Cross-faction collisions

The four drafting agents each checked their own three factions, but nobody compared across agents. The result is **19 major collisions** (table) and **10 smaller clashes** (list below the table): in each, two or more factions got the same new trick, either the same mechanic or the same condition. For each major collision, a single faction keeps the trick and every other faction gets the concrete replacement listed. When a replacement says "drop", the unit's kit is still inside its tier range and still larger than its base.

| # | Trick | Who has it | Keeps it | Others get instead (card, text, build) |
|---|---|---|---|---|
| 1 | Ward on the first hit each round | Castle Swordsman and alt (Hold Fast 25/15), Bulwark Ram alt (Stubborn Fleece 50) | **Bulwark**: being hit is its Bastion engine | Castle Swordsman / Swordsman alt: **Shield Brother** (P). "Once per round, when an enemy attacks an adjacent friendly creature in Melee, this creature strikes that enemy for 50% Damage after the attack." The alt gets twice per round. Built on the Avenger / Covering Fire attack queue with a new trigger, "ally attacked in melee". |
| 2 | Kill → act again | Castle Swordsman alt (Follow Through), Stronghold Ancient Behemoth (Rampage), Necropolis Ghost Dragon alt (Deathly Plunge) | **Castle**. It fits Cleave ("many small stacks"). The Stronghold draft itself warned that Rampage on a T7 with 50% Armor Rend is its strongest card. | Stronghold Ancient Behemoth: **Overrun** (P). "When this creature's attack destroys a stack, the Damage left over is dealt to one adjacent enemy." New plugin `overkill_carry`. Necropolis Ghost Dragon alt: **Deathly Plunge** (A 3/3). "Performs a Melee attack. If it destroys the target stack, the Focus is refunded and the cooldown resets." Plugin `kill_refund` on the ability-commit hook. |
| 3 | +Damage vs "has not acted this round" | Rampart Wood Elf (Forest Ambush), Dungeon Infernal Troglodyte (Ambush) | **Dungeon**: timing is its faction verb | Rampart Wood Elf: **Wind Reader** (P). "Ranged attacks deal +25% Damage to flying creatures." Native `outDmgModsByTargetTags` on the flyer tag. Also rename Stronghold Goblin alt "Ambush" to **Surprise Attack**, because two cards named Ambush is a name clash. |
| 4 | Flank (target next to another of my stacks) | Stronghold Wolf line (Pack Hunt x3), Inferno Imp alt (Gang Up) | **Stronghold**: line identity on 3 rows | Inferno Imp alt: **Cinder Skin** (P). "Whenever this creature takes Damage, adjacent enemies are set Burning until the end of the next round." Existing `when_damaged_adjacent_debuff` + `h3_kit_inferno_burning_lesser_effect`. |
| 5 | Isolated target | Rampart Centaur / Captain (Hunter's Eye), Fortress Gnoll Marauder (Pick Off) | **Rampart** (2 rows) | Fortress Gnoll Marauder: **Raider** (P). "Deals +30% Damage to creatures that can shoot." Native `outDmgModsByTargetTags` on the shooter tag. |
| 6 | More Damage per adjacent enemy | Castle Royal Griffin (Flock Fighter), Inferno Magog alt (Hellfire Burst `crowd_nova`) | **Inferno**: an active nova is the stronger, clearer use | Castle Royal Griffin: **drop** Flock Fighter. Unlimited Retaliation + Talon Riposte already make it want to be surrounded. Body +5%. |
| 7 | Push on hit | Castle Champion alt (Scatter the Ranks), Cove Stormbird line (Gust x3, Gale Guard), plus Dungeon Bull Rush (vanilla minotaur) and Stronghold Buffeting Wings | **Cove** keeps push on hit. **Dungeon** keeps the push strike (vanilla). **Stronghold** keeps the area burst (no damage, free; a different shape). | Castle Champion alt: **drop** Scatter the Ranks (kit stays at 3). Body +6%. |
| 8 | Pull (`giant_frog` Sticky Tongue clone) | Tower Golem alt (Lodestone Pull), Cove Seaman (Grappling Hook), Cove Serpent alt (Whirlpool area pull) | **Cove** | Tower Golem alt: **Lodestone Draw** (A 1/2, free). "Moves every negative effect on friendly creatures within 2 hexes onto this creature." Native `transfer_buffs`. It pairs with Spell Damage Reduction. |
| 9 | Free teleport anywhere | Castle Angel (Descend), Stronghold Behemoth alt (Phase Step) | **Stronghold** (Opener acts in place; a spectral behemoth) | Castle Angel: **Shield of Faith** (A 2/3, free). "A friendly creature within 4 hexes is immune to negative effects until the end of the next round." Cast with a buff cloned from an `effect_immunity` row. |
| 10 | Swap with an enemy | Tower Naga Queen (Serpent Dance), Inferno Arch Devil (Hellish Exchange) | **Inferno**: devils teleport in HoMM3 | Tower Naga Queen: **Relentless Blades** (P). "Each attack on the same enemy stack as its previous attack deals +15% more Damage, up to +45%. Attacking another stack resets it." New plugin `same_target_streak`. |
| 11 | Counter strikes extra hexes | Castle Royal Griffin (Talon Riposte, counter swipe), Conflux Air alt (Whirling Gale, counter whirlwind) | **Castle**: the swipe is Castle's Cleave identity and the griffin's retaliation fame | Conflux Air alt: **Opening Gust** (P). "Its first attack or counterattack each round deals +25% Damage." The `first_hit` rule from #1, used on the attacker side. |
| 12 | Hits the hex behind the target (`attack_reach_x1_x100_x50` on basic attacks) | Castle Archangel alt (Flaming Sword), Bulwark Mammoth line (Trample x3) | **Bulwark** (3 rows, mammoth identity) | Castle Archangel alt: **drop** Flaming Sword (kit stays at 5). Body +5%. |
| 13 | Burn DoT scaled to the caster's Damage | Rampart Gold Dragon (Dragonfire, `scaled_dot`), Conflux Fire upg (Ignite, `scale_by_caster`) | **Conflux** | Rampart Gold Dragon: **drop** Dragonfire (kit stays at 4: Breath, SI IV, No Retaliation, Fearless). Merge the two rewrites into one, `scale_by_caster`. |
| 14 | "Fly to a hex and hit everyone around it" (`landing`) | Rampart Wardancer (Leaf Storm), Conflux Firebird upg (Sunfall). Dungeon's Black Dragon already ships `landing` (Dragonflight). | **Dungeon** (existing, vanilla donor) | Conflux Firebird upg: **drop** Sunfall (kit 3 vs base 2), +2 Attack. Rampart Wardancer: **Sap the Strength** (P). "Each strike gives the target -2 Attack until the end of the next round (does not stack)." `on_hit_buff` + `hydra_debuff` clone. |
| 15 | Ability cooldown on the target (`force_unit_cd`) | Stronghold Ogre line (Clobber x3), Cove Sorceress (Becalm) | **Stronghold** (line identity) | Cove Sorceress: **Siren Song** (A 2/3). "An enemy creature within 6 hexes can attack only this creature until the end of its next turn." An `ent_taunt_buff` clone cast on one enemy. It lures stacks into the gun line. |
| 16 | Shot that leaves the target with no counterattack this round | Stronghold Orc Chieftain (Pinning Volley 60%), Necropolis Skeleton alt (Bone Pin 80%) | **Stronghold**: it sets up its own Pulverize | Necropolis Skeleton alt: **Bone Rattle** (A 1/1). "Performs a Ranged attack that deals 80% Damage. The target has -2 Morale until the end of the next round." `shot` + a `hydra_debuff` clone (moral -2). |
| 17 | Strike + lifesteal (`drain_strike`) | Fortress Hydra alt (Devour), Factory Olgoi (Gorge) | **Fortress** | Factory Olgoi: **drop** Gorge. It already has Devour Corpses for sustain, and its kit stays at 4. +1 Attack. |
| 18 | Remove a positive effect on hit | Rampart Gold Pegasus (Dispelling Hooves), Cove Corsair (Plunder, steal) | **Cove** (the pirate steal is flavour) | Rampart Gold Pegasus: **drop**. Kit is Magic Damper + No Retaliation (2 vs base 1). Body +8%. Also rename Corsair's card **Pilfer**: "Plunder" is already a shipped faction ability. |
| 19 | Root on a melee strike (`ent_root` clone) | Fortress Gorgon alt (Lock Horns), Cove Haspid (Crushing Coils), plus Rampart Binding (identity) and Necropolis Bone Cage (ranged hex) | **Rampart** (identity), **Necropolis** (ranged cast), **Cove** (coil + counter disable; Run Aground reads it) | Fortress Gorgon alt: **Gore** (A 2/2). "Performs a Melee attack. Deals +40% Damage if the target is Corroded." `melee_strike` + `damage_vs_buff` {40, corroded buff, abilityOnly}. It cashes in its own Corrosive Breath. |

### Smaller clashes, settled without a full swap

- **Pile On (Stronghold Hobgoblin) vs Swarm Fire (Tower Master Gremlin).** Both reward "target already hit this round". Tower keeps Swarm Fire, which scales with stack count and suits shooters. Hobgoblin gets **Opportunist** (P): "Deals +30% Damage to stacks that have Waited this round." Plugin `turn_state` (wait stamp).
- **Focus gifts: Bulwark Spirit Gift vs Factory Bell Toll.** Focus economy is Bulwark's axis, so Bulwark keeps it. Factory Bellwether gets **Rally Bell** (A 1/2, free): "Removes every slowing and movement-preventing effect from adjacent friendly creatures." `kw_rally` envelope + `dispel` filtered by the movementNegative tag.
- **Ally swap: Bulwark Kobold Foreman Shift Change vs Rampart Carry Off.** Carry Off is an existing Rampart signature, so the Foreman **drops** Shift Change and keeps Small Target + Foreman Cadence. Body +5%.
- **Enemy cast → payoff: Rampart Silver Pegasus Spell Sentinel vs Inferno Familiar Magic Channel.** Magic Channel is the Familiar's HoMM3 identity, so Inferno keeps it. Silver Pegasus gets **Shepherd** (P): "A friendly creature moved by Carry Off gains 1 Focus." `add_energy` on the swap's second pick.
- **Damage cap: Conflux Earth line Stone Body vs Rampart Diamond Scales.** Both are `hit_cap`, and Earth alt even used Diamond Scales' 20%. Rampart keeps it. The Earth line gets **Bedrock** (P): "Takes -30% Damage from flying creatures" (Earth alt -40%). Native `inDmgModsByCasterTags`. Fusions inherit it through the tag-merged `inDmgMods`, which removes the Conflux draft's top fusion risk.
- **Adjacent-ally ward at 5/15: Necropolis Skeleton Bone Wall.** It is the same rule with the same numbers as Stronghold's Goblin Safety in Numbers. Its card text ("adjacent friendly stacks take less") also does not match the `adjacent_ally_ward` build. The Skeleton line gets **Reassemble** (P): "At the end of each round, restores Health equal to 10% of the stack's full Health, raising fallen Skeletons" (alt: 15%). An `end_round` self passive with `heal_percent` (layout from `h3_walking_dead_upg`).
- **Enemy ends its move next to me: Inferno Efreeti alt Scorched Earth vs Fortress Greater Basilisk Lingering Gaze.** Burning is Inferno's verb, so Inferno keeps it. Greater Basilisk gets the draft's own fallback, **Basilisk Stare** (P): "Adjacent enemy creatures have -2 Initiative." Native `stat_aura`.
- **Reaction strike on enemy movement: Dungeon Vigilant Eye vs Cove Harpoon Watch.** Both stay, because the shapes differ: ranged, radius 3, once per round, versus melee, adjacent, unlimited. Rename Dungeon's plugin rule to `zone_shot`, because the Cove draft's native keyword is already called `overwatch`.
- **Hex blockers: Factory Engineer Field Fortification vs Dungeon Troglodyte alt Cave-In.** Terrain is Dungeon's, so Dungeon keeps it. The Engineer gets **Spotting Scope**; see the Factory list.
- **Min-damage zones: Tower Lodestone Field vs Rampart Living Cover.** Both stay. One makes adjacent enemies deal minimum Damage; the other makes adjacent allies take it.

### Within-faction removal check

The drafts mostly removed what they listed. These listed duplicates were left implicit or missed, and each needs a line in the build:

- **Castle:** Marksman **Aimed Shot** (+30% shot) is listed as a duplicate, but the Marksman row never removes it. Remove it.
- **Rampart:** these removals appear only in the duplicates table or the power notes, never in a kit row: Dwarf and Battlerager **Sturdy**, Grand Elf and Pegasus **Evasive**, Dendroid Guard **Bark Skin**, base Unicorn **Impale** (gallop), Silver Pegasus **Rivulet Retreat**, Diamond Dragon **Adamant Hide** and **Alert**. State all of them explicitly.
- **Tower:** Gremlin alt **Ball and Chain** is removed only by implication ("kept (base only)"). State it.
- **Necropolis:** base Vampire **Mist Form** and Ghost Dragon alt **Hollow Frame** are not stated as removed.
- **Fortress, Bulwark, Stronghold:** they keep generic resists as "line identity": Iron Hide x3, Leathery Wings x3, Small Target x3, Thick Hide x3 and Wing Buffet x3. None of these is a HoMM3 identity. See open question 3.
- **Inferno:** Hellfire Burst is still an "every adjacent enemy" nova. It is now crowd-scaled, which is acceptable once #6 settles it.

---

## 2. Residual repeats

Counts are kit rows. "Before" is from the current `custom_factions/unit_designs/homm3_*.json`. "After" applies the drafts plus this review's overrides. A "plain strike" is a `melee_strike` / `castle_strike` / `breath_strike` / `shot` row with only a multiplier, a counter flag or a return, and no rider.

| Pattern | Before | After | What is left |
|---|---|---|---|
| `resist`, physical (melee / ranged / basic) | 100 | 15 | Bulwark 6 (Small Target, Thick Hide), Fortress 6 (Iron Hide, Leathery Wings), Stronghold 3 (Wing Buffet) |
| `resist`, magic | 27 | 12 | Born of Flame x3, Rampart Magic Resistance x3, Golem Spell Damage Reduction x3 (all identity), Bulwark Spirit Ward x3 |
| New conditional damage cuts | 0 | 4 | Stubborn Fleece (first hit), Bedrock x3 (vs flyers) |
| `gallop` (per-hex) | 54 | 3 | Castle Jousting x3 (HoMM3 identity, 5/10/5%) |
| Alert (`counters` 2) | 33 | 2 | Castle Griffin, Griffin alt (identity) |
| Unlimited counters | 8 | 2 | Royal Griffin, Chaos Hydra (identity) |
| Plain strike actives | 32 | 1 | Conflux Sprite Flit (strike-and-return; text trimmed) |
| `reach_strike` (Long Thrust family) | 8 | 0 | Basic-attack pierce stays on the Mammoth line (Trample x3) and the Factory Mechanic. Sea Dog has a pierce shot. |
| Plain whirlwinds (`swirl_strike`, swirl `castle_strike`) | 10 | 1 | Halberdier Reaping Arc (fixed by owner) |
| `castle_cleave` swipes | 5 | 1 | Talon Riposte (counterattacks only) |
| `dive` | 6 | 3 | Castle Battle Dive, Stronghold Stoop (both kept, range 99); Cove Swing Aboard (range 4, mult 1.0) |

Two new monocultures to watch. The pass trades the old repeats for these:

- **Conditional "+x% Damage when …" cards: about 30 new rows.** The condition differs on each one, which is the brief's minimum bar. But most are invisible plugin math that the AI and the forecast cannot see. See open question 2.
- **Initiative debuffs replace Speed debuffs.** There are 4 new ones: War Unicorn Radiant Horn -2, Medusa Queen Stiffening Glare -2, Wraith alt Wail -4, Greater Basilisk Stare -2. Fortress and Bulwark Speed riders fell from 8 to 3. See open question 5.

---

## 3. Changed cards, per faction

One line per changed card. Kept cards are left out. Format: unit, card, P or A Focus/cooldown, gist.

### Castle (Cleave vs Lance)

- Archer, **Stand Ground**, P: +25% Ranged Damage if it did not move on its previous turn.
- Marksman: **Aimed Shot removed** (missed by the draft).
- Royal Griffin, **Talon Riposte**, P: counterattacks also hit the two enemies beside the attacker for 50%.
- Royal Griffin: Flock Fighter **dropped (R)**.
- Griffin alt, **Pinning Talons**, P: basic attacks and counterattacks remove 1 of the target's counterattacks this round.
- Swordsman, **Shield Brother (R)**, P: once per round, strikes an enemy that attacks an adjacent ally in Melee, for 50%.
- Crusader, **Challenge**, A 2/2: Melee attack. Until the end of the next round, the target deals -50% Damage to anyone but this stack.
- Swordsman alt, **Shield Brother (R)**, P: as Swordsman, twice per round.
- Swordsman alt, **Follow Through**, P: destroying a stack lets it act again, once per round.
- Monk, **Retribution**, P: +25% Damage to enemies that damaged a friendly stack this round.
- Zealot, **Retribution**, P: as Monk (line identity).
- Zealot, **Brand of Faith**, A 2/2: Ranged attack. Until the end of the next round, attack Damage on the target splashes 25% to its neighbours.
- Monk alt, **Humble the Mighty**, P: +25% Damage to stacks with more creatures than this one.
- Champion, **Unhorse**, P: after moving 4+ hexes, the Melee target cannot counterattack.
- Champion, **Cavalry Press**, A 2/2: the Cavalier's charge, copied to the Champion.
- Champion alt: Scatter the Ranks **dropped (R)**.
- Angel, **Shield of Faith (R)**, A 2/3, free: an ally within 4 hexes is immune to negative effects until the end of the next round.
- Archangel, **Vengeance of Heaven**, P: +4 Attack for the rest of the battle each time a friendly stack dies.
- Archangel alt: Flaming Sword **dropped (R)**.
- Archangel alt, **Wrathful Chalice**, A 3/3: steals all positive effects from enemies in a 1-hex radius.

### Rampart (Striker vs Ward)

- Centaur, **Hunter's Eye**, P: +20% Damage to an enemy with no ally next to it.
- Centaur Captain, **Hunter's Eye**, P: as Centaur, +30%.
- Dwarf, Battlerager: **Sturdy removed** (make it explicit).
- Wood Elf, **Wind Reader (R)**, P: +25% Ranged Damage to flying creatures.
- Grand Elf, Pegasus: **Evasive removed** (make it explicit).
- Wardancer, **Sap the Strength (R)**, P: each strike gives -2 Attack until the end of the next round.
- Silver Pegasus, **Shepherd (R)**, P: the ally moved by Carry Off gains 1 Focus.
- Silver Pegasus: Rivulet Retreat and Wing Shelter removed.
- Gold Pegasus: Swoop and Dive removed; Dispelling Hooves **dropped (R)**.
- Dendroid Guard: **Bark Skin removed** (make it explicit).
- Dendroid Soldier, **Overgrowth**, A 2/2, free: roots every adjacent enemy until the end of the next round.
- Dendroid Shaman, **Living Cover**, P (aura): adjacent allies always take minimum Damage.
- Unicorn: **Impale removed** (make it explicit).
- War Unicorn, **Radiant Horn**, P: basic attacks and counterattacks give -2 Initiative.
- Pristine Unicorn: Alert removed.
- Green Dragon: Dragon Scales removed.
- Gold Dragon: Dragon Scales and Fury of the Wood removed; Dragonfire **dropped (R)**.
- Diamond Dragon: Adamant Hide and Alert removed.

### Tower (Chassis vs Specialist)

- Master Gremlin, **Swarm Fire**, P: +10% Damage per other friendly stack that hit the target this round, up to +30%.
- Gremlin alt: Ball and Chain removed (make it explicit).
- Gargoyle, **Perch**, P: after Waiting or Defending, +30% Damage until the end of its next turn.
- Obsidian Gargoyle, **Perch**, P: as Gargoyle, +40%.
- Gargoyle alt, **Perch**, P: as Gargoyle, +30%.
- Gargoyle alt, **Granite Riposte**, P: counterattacks make the attacker deal -25% Damage for the round.
- Iron Golem, **Gathering Momentum**, P: +2 Attack every round, up to +10.
- Golem alt, **Lodestone Field**, P (aura): adjacent enemies always deal minimum Damage.
- Golem alt, **Lodestone Draw (R)**, A 1/2, free: pulls negative effects off allies within 2 hexes onto itself.
- Arch Mage, **Arcane Volley**, P: when your hero casts on an enemy, also shoots it for 50%, once per round.
- Genie line: Spirit Form removed (x3).
- Naga Queen, **Relentless Blades (R)**, P: +15% per repeat attack on the same stack, up to +45%.
- Titan, Giant, Giant alt: Colossal removed (x3). Titan also loses Thunderbolt; Giant alt also loses Alert and Earthshaker.

### Stronghold (Opener vs Finisher)

- Hobgoblin, **Opportunist (R)**, P: +30% Damage to stacks that Waited this round.
- Goblin alt, **Surprise Attack (R, renamed from Ambush)**, P: first round, +30% Damage and no counterattacks.
- Wolf Rider, Wolf Raider, Boar alt, **Pack Hunt**, P: +20% Damage to an enemy next to another friendly stack.
- Boar alt, **Gore**, A 1/1: Melee attack, +15% per ally that already acted this round, up to +60%.
- Orc Chieftain, **Pinning Volley**, A 2/2: 60% shot; the target cannot counterattack this round.
- Orc alt, **Prey on the Weak**, P: +25% Damage to enemies under any negative effect.
- Ogre, Ogre Mage, Ogre alt, **Clobber**, A 2/2: Melee attack; the target's abilities go on cooldown.
- Ogre Mage, **Bloodlust**, A 2/2: now free (does not end the turn).
- Ogre Mage, **War Drums**, P: at battle start, allies within 2 hexes gain +1 Speed for round 1.
- Ogre alt, **Pulverize**, A 2/2: Melee attack, +50% if the target has no counterattack left.
- Roc, Thunderbird, Roc alt, **Buffeting Wings**, A 2/2, free: pushes every adjacent enemy 1 hex.
- Thunderbird, **Lightning Strike**, A 2/2: Melee attack dealt as Magic Damage (ignores Defence).
- Roc alt: Double Strike removed.
- Cyclops, **Rockslide**, A 2/2: shot, full Damage plus 50% to the target's neighbours (moved down from the King).
- Cyclops King, **Siege Breaker**, P: +30% Damage to Defending or buffed enemies.
- Cyclops alt: Heavy Boulders removed (Baleful Gaze kept).
- Ancient Behemoth, **Overrun (R)**, P: leftover Damage from a kill carries to one adjacent enemy.
- Behemoth alt, **Phase Step**, A 3/3, free: moves to any free hex.

### Fortress (Hunter vs Warden)

- Gnoll, Gnoll Marauder, Gnoll alt, **Scavenge**, A 1/2: eats an adjacent corpse and heals 50% of one creature.
- Gnoll Marauder, **Raider (R)**, P: +30% Damage to creatures that can shoot.
- Lizardman, **Venom Shot**, A 1/1: shot + poison for 2 rounds (moved down from the alt).
- Lizard alt, **Giant Slayer**, P: +5% Damage per tier the target is above it.
- Dragon Fly, **Droning Wings**, P (aura): adjacent enemies gain no Focus.
- Serpent Fly alt, **First Sting**, P: +30% Damage to a stack that has lost no creatures this battle.
- Greater Basilisk, **Basilisk Stare (R)**, P (aura): adjacent enemies -2 Initiative.
- Basilisk alt, **Stone Gaze**, A 2/3: the petrify, copied from the base row.
- Basilisk alt, **Shatter**, P: +50% Damage to petrified enemies.
- Mighty Gorgon, **Withering Gaze**, P: counterattacks also kill 1 creature.
- Gorgon alt, **Gore (R)**, A 2/2: Melee attack, +40% vs a Corroded target.
- Wyvern, **Tail Sting**, A 2/2: Melee attack + a weaker Wyvern poison.
- Wyvern Monarch, **Toxic Cloud**, A 2/3, free: poisons every adjacent enemy.
- Wyvern alt, **Quarry**, A 1/1, free: marks one enemy; +35% Damage to it until it dies or the mark moves.
- Hydra alt, **Devour**, A 3/3: single-target bite at +50% that heals for half the Damage; it now takes a counterattack.

### Bulwark (Tempo vs Bastion)

- Kobold Foreman: Alert removed; Shift Change **dropped (R)**.
- Mountain Ram, Argali, Ram alt, **Sure-Footed**, P: moves over obstacles.
- Ram alt, **Stubborn Fleece**, P: the first attack each round deals -50%.
- Yeti Runemaster, **Runic Feedback**, P: +1 extra Focus when hit.
- Yeti Runemaster, **Glacial Rune**, A 2/3, free: this round's Damage is held back and lands at round end.
- Yeti alt: Storm Reflexes (unlimited counters) removed.
- Great Shaman, **Spirit Anchor**, P (aura): adjacent stacks cannot fall below half their start-of-round count.
- Shaman alt, **Wind Shear**, P: +1 Focus every round.
- Shaman alt, **Spirit Gift**, A 1/1, free: an ally within 4 hexes gains 2 Focus.
- Mammoth, War Mammoth, Mammoth alt, **Trample**, P: basic attacks also hit the creature behind for 50% (replaces the gallop).
- War Mammoth, **Pent-up Fury**, P: each attack taken adds +10% to its next attack, up to +50%.
- Mammoth alt: Alert and Tusk Sweep removed (Run Them Down kept).
- Jotunn Warlord, **Warlord's Command**, A 3/3, free: another ally gets one more turn this round.
- Steel Elf, Jotunn alt: Steel Mail and Glacial Hide removed.

### Inferno (Breacher vs Holder; the verb is "punish movement")

- Imp, **Heckle**, P: basic attacks and counterattacks give -1 Morale.
- Familiar, **Magic Channel**, P: each enemy spell gives your hero 2 mana.
- Imp alt, **Cinder Skin (R)**, P: when hit, adjacent enemies are set Burning.
- Gog, **Fire Bolt**, A 1/1: +15% shot that sets the target Burning (Damage each time it moves).
- Magog, **Brimstone**, P: every enemy hit by its Ranged attack is set Burning.
- Magog alt, **Hellfire Burst**, A 1/2: nova at 40% per adjacent enemy, up to 160%.
- Hell Hound line, **Run Down**, P: +20 / 25 / 15% Damage to stacks that moved this round.
- Demon line, **Soul Tithe**, P: your hero gains 3 mana when this stack dies.
- Horned Demon, **Infernal Bargain**, A 1/3, free: loses no creatures this round, then takes 80% of the Damage at round end.
- Demon alt, **Bloodied Fury**, P: +40% Damage once it has lost a full stack's worth of creatures.
- Pit Fiend line, **Crack the Whip**, A 1/2, free: an ally gets +3 Attack and +2 Initiative for the round.
- Pit Lord, **Raise Demons**, A 2/3, 2 charges: raises Demons from a corpse, sized by the HP the corpse stack lost.
- Pit Fiend alt, **Flay**, A 2/2: Melee attack that first strips all positive effects.
- Efreeti, **Fan the Flames**, P: +25% Damage to Burning creatures.
- Efreet Sultan, **Fire Shield**, P: now permanent (Melee attackers take 12 per creature).
- Efreeti alt, **Scorched Earth**, P: enemies ending their move next to it are set Burning.
- Arch Devil, **Hellish Exchange**, A 3/3: swaps with an enemy within 6 hexes, which loses its counterattack.
- Devil alt: Alert removed.

### Necropolis (Reaper vs Gravekeeper; the verb is "the weak die faster")

- Skeleton line, **Reassemble (R)**, P: 10% heal-and-raise at each round end (alt 15%).
- Skeleton alt, **Bone Rattle (R)**, A 1/1: 80% shot, -2 Morale.
- Zombie upg, **Disease into Plague**, P: a second hit turns Disease into Plague (-4/-4, no healing).
- Zombie alt, **Contagious Disease**, P: Disease spreads to the bearer's neighbours each turn.
- Wraith, **Mana Drain**, P: takes 2 enemy mana per turn.
- Wraith alt, **Wail**, A 2/2, free: adjacent enemies -4 Initiative.
- Vampire Lord, **Life Drain**, P: overflow raises become temporary creatures.
- Vampire Lord, **Exsanguinate**, A 2/2: Melee attack, +50% vs a stack below half Health.
- Vampire: **Mist Form removed** (make it explicit).
- Lich line, **Death Cloud**, P: the cloud hits friend and foe at 60%; undead, constructs and elementals are spared.
- Power Lich alt, **Bone Cage**, A 2/2: an enemy within 5 hexes cannot move.
- Dread Knight, **Death Blow**, A 2/2: double Damage vs a Cursed target.
- Black Knight alt, **Mark of Death**, A 2/2: the target dies outright at 25% of its starting count.
- Ghost Dragon, **Chill of the Grave**, P (aura): adjacent enemies -2 Speed.
- Ghost Dragon alt, **Deathly Plunge (R)**, A 3/3: Melee attack; a kill refunds the Focus and resets the cooldown.
- Ghost Dragon alt: Hollow Frame removed (make it explicit).

### Dungeon (Reckless vs Sustained; the verb is timing)

- Infernal Troglodyte, **Ambush**, P: +30% Damage to stacks that have not acted; takes +15% from basic attacks.
- Troglodyte alt, **Cave-In**, A 2/3: rubble blocks a hex for 2 rounds.
- Harpy Hag, **Carrion Wings**, P: +30% Damage to stacks that already counterattacked this round.
- Evil Eye, **Ray Barrage**, A 2/2: 50% rays at up to 3 enemies.
- Beholder alt, **Vigilant Eye**, P: shoots the first enemy that ends its move within 3 hexes for 60%, once per round.
- Medusa Queen, **Stiffening Glare**, P: counterattacks give -2 Speed and -2 Initiative.
- Medusa alt: Lunge removed.
- Minotaur, **Bull Rush**, A 2/2: Melee attack + push 1 hex.
- Minotaur King, **Wall Slam**, A 2/2: Bull Rush; +50% if the push is blocked.
- Minotaur King, **Headlong**, P: +15% Melee Damage, +15% taken.
- Minotaur alt, **Immovable**, P: cannot be pushed, pulled, swapped or rooted.
- Manticore line: Pounce and Chitin removed.
- Manticore alt, **Venom Burst**, A 2/2: Melee attack, then every damage-over-time effect on the target fires now.
- Black Dragon: Black Scales and Ancient Vigor removed.
- Red alt: Shadow Rage, Swoop and Shadow Flame removed.

### Conflux (Host vs Donor; fusions follow open question 1)

- Pixie line, **Flutter Away**, P: after surviving a Melee hit, flies 1 hex (alt: 2) away from the attacker.
- Sprite: Flit text trimmed.
- Air line, **Body of Air**, P: the Ranged resist part removed; the lightning weakness stays.
- Air alt, **Opening Gust (R)**, P: its first attack or counterattack each round deals +25%.
- Water alt, **Frostbite**, P: a second application Freezes the target, which also takes +25% Damage while Frozen.
- Water alt: Frozen Heart removed.
- Fire upg, **Ignite**, A 2/2, free: burns a target within 6 hexes for 2 turns at 40% of this stack's Damage.
- Fire alt, **Static Build-up**, P: +1 extra Focus when hit.
- Earth line, **Bedrock (R)**, P: -30% Damage from flying creatures (alt -40%).
- Earth upg: Eruption removed.
- Psychic upg, **Psychic Feedback**, P: an enemy using an ability within 3 hexes takes 30% Magic Damage.
- Psychic alt, **Mind Fray**, P: on hit, the target gains no Focus for 2 rounds.
- Firebird upg: Sunfall **dropped (R)**; Firestorm Pass and Blazing Flight removed.
- Firebird alt, **Renewing Flame**, P: each round start, adjacent allies heal and raise 10%.

### Cove (Boarding vs Broadside)

- Oceanid, **Riptide**, A 1/2, free: moves an ally to a free hex within 3.
- Nymph alt: Water Jet removed.
- Crew line, **Scrappers**, P: if the target counterattacks, attacks it again afterwards.
- Seaman, **Grappling Hook**, A 1/2, free: pulls an enemy up to 3 hexes into contact.
- Corsair, **Pilfer (R, renamed)**, P: Melee attacks steal one positive effect.
- Corsair, **Swing Aboard**, A 1/2: leaps up to 4 hexes and attacks.
- Sea Dog, **Raking Shot**, A 2/2: shot that also hits the creature behind for 50%.
- Stormbird line, **Gust**, P: basic attacks push 1 hex.
- Stormbird alt, **Gale Guard**, P: counterattacks push the attacker 1 hex.
- Sea Witch line: Duelist removed (Pirate line only).
- Sorceress, **Siren Song (R)**, A 2/3: an enemy can attack only her until the end of its next turn.
- Nix: Abyssal Hook removed.
- Nix Warrior, **Harpoon Watch**, P: unlimited overwatch strikes on enemies moving next to it.
- Nix alt: Tidal Charge removed.
- Sea Serpent: Slick Scales removed.
- Haspid, **Crushing Coils**, A 3/2: Melee attack + root; the target cannot counterattack anyone.
- Serpent alt, **Whirlpool**, A 3/3: pulls everything within 2 hexes of a hex inward, then damages the enemies pulled.

### Factory (Crewed vs Automated)

- Engineer: Field Drive replaced. The draft's Field Fortification collides with Dungeon's Cave-In (both block a hex for 2 rounds), so the Engineer gets **Spotting Scope (R)**, A 1/2, free: "A friendly creature within 4 hexes deals full Ranged Damage at any range until the end of the round." `factory_cast_buff` with a clone of the Steady Aim range buff.
- Mechanic alt, **Dragonbreath Strike**, P: the reach basic attack replaces Long Reach.
- Armadillo, Bellwether, Armadillo alt, **Huddle**, P: on Defend, adjacent allies gain +3 Defence for the round (Bellwether +5).
- Bellwether, **Rally Bell (R)**, A 1/2, free: clears slow and root effects from adjacent allies.
- Armadillo alt: Alert removed.
- Sentinel, **Guardian Protocol**, P: takes 30% of the Damage dealt to adjacent allies.
- Automaton alt: Brass Casing removed.
- Sandworm line, **Burrow**, P: on Wait, untargetable until it acts or takes Damage.
- Olgoi: Swallow removed; Gorge **dropped (R)**.
- Bounty Hunter, **Bounty**, P: +30% Damage to the enemy stack with the most total Health.
- Gunslinger alt: Alert removed.
- Couatl line, **Radiant Plumage**, P (aura): adjacent enemies -2 Attack (Crimson -4).
- Crimson Couatl: Skyfall removed.
- Couatl alt: Jade Scales and Soothing Coil removed.
- Dreadnought, Juggernaut: Iron Hull removed.
- Dreadnought alt, **Sealed Hull**, P: negative effects last at most 1 round.

---

## 4. New mechanics, deduplicated

Risk tags:

- **P**: proven donor. Clones a shipped row or an existing runtime rule unchanged.
- **U**: native data, or an existing plugin hook, used in a combination nobody has seen in game.
- **H**: needs a plugin hook that does not exist yet.

Size: **S** is under a day, **M** is 1-3 days, **L** is more than 3 days.

### 4.1 Plugin rule kinds (merged)

| Rule kind | Merges | Cards | Risk | Size |
|---|---|---|---|---|
| `turn_state` {fact} | stood_ground, unacted_target / target_not_acted, moved_target, waited_target, allies_acted. One per-unit stamp table (acted, waited, moved) fed by the action, wait, skip and end-move dispatchers. | Stand Ground, Ambush, Run Down x3, Opportunist, Gore (boar) | U | M (the shared stamp), then S each |
| `counter_state` {used, left0} | spent_counter, no_counter_left | Carrion Wings, Pulverize | U (reading live counters through interop is unverified) | S |
| `adjacency` {mode flank / isolated} | flank, flanked, isolated, isolated_target | Pack Hunt x3, Hunter's Eye x2 | U (`adjacent_ally_ward` scan) | S |
| `crowd` {per adjacent enemy, abilityOnly} | crowd_fury, crowd_nova | Hellfire Burst | U | S |
| `hit_this_round` {any / count} | struck_this_round, focus_fire | Swarm Fire (Pile On cut) | U (`grudge` bookkeeping) | S |
| `first_hit` {side: defender / attacker} | first_hit_ward + "first attack" | Stubborn Fleece, Opening Gust | U | S |
| `vs_buff_tag` {tag or Defend} | vs_debuffed, vs_buffed (generalises `damage_vs_buff`) | Prey on the Weak, Siege Breaker | U | S |
| `damage_vs_buff` + `abilityOnly` flag | extends the existing rule | Death Blow, Shatter, Gorgon alt Gore, Fan the Flames | P | S |
| `damage_vs_hp` | | Exsanguinate | U | S |
| `unhurt` | | First Sting | U (`loss_fury` tracker) | S |
| `outnumbered` | | Humble the Mighty | U | S |
| `bounty` | | Bounty | U | S |
| `retribution` | | Monk, Zealot | U (`grudge`) | S |
| `same_target_streak` | | Relentless Blades | U | S |
| `stored_fury` | | Pent-up Fury | U | S |
| `duel_mark` + marker buff | | Challenge | U (buff-add hook) | M |
| `quarry` + mark cast | | Quarry | U (commit hook) | M |
| `wall_slam` | | Wall Slam | U (must read the push destination before the push) | M |
| `arrival_buff` | | Scorched Earth | U (end-move dispatcher) | M |
| `zone_shot` (was Dungeon `overwatch`) | | Vigilant Eye | U (attack queue + end-move) | M |
| `guard_strike` | | Shield Brother x2 | U (attack queue + "ally attacked" trigger) | M |
| `ability_feedback` | | Psychic Feedback | U (commit hook + queue; must run after the ability resolves) | M |
| `brand_splash` | | Brand of Faith | U (damage from inside the damage step; needs a re-entrancy guard) | M |
| `kill_refund` | the Necropolis `kill_extra_action` rule, re-scoped | Deathly Plunge | U (commit hook) | S |
| `charge_no_counter` | | Unhorse | **H** (suppressing the counter at commit) | M |
| `scatter` | | Flutter Away x3 | **H** (a self-move after being hit) | L |
| `bodyguard` | | Guardian Protocol | **H** (a damage redirect) | L |
| `overkill_carry` | | Overrun | **H** (spill damage after a kill) | M |
| `spell_echo` | | Arcane Volley | **H** (the hero-cast target is not exposed) | L |
| `raise_by_hp` | | Raise Demons | **H** (overriding the summon count) | M |
| `scale_by_caster` (buff-add rewrite) | scaled_dot, scale_by_caster | Ignite | U (next to `rotate` / `escalate`) | S |

The drafts proposed 41 rule kinds. Merged and after cuts, 31 remain: 6 **H**, 24 **U**, 1 **P**.

### 4.2 New keywords (native data)

| Keyword | Cards | Donor | Risk | Size |
|---|---|---|---|---|
| `extra_turn_on_kill` (shared, from `bulwark_extra_turn`) | Follow Through | `godslayer_upg_alt`, already ships | P | S |
| `push_on_hit` {counter} | Gust x3, Gale Guard | `minos` ability 0 | P on attacks, U on counterattacks | S |
| `push_burst` | Buffeting Wings x3 | minos rumble + push, free | U | S |
| `pull` | Grappling Hook | `giant_frog` ability 1 | P | S |
| `whirlpool` | Whirlpool | `aqualotl_upg` ability 2 | P | S |
| `bull_rush` | Bull Rush, Wall Slam | `minos_l` ability 0 | P | S |
| `cooldown_strike` | Clobber x3 | jaw `force_unit_cd` | P | S |
| `swap_enemy` | Hellish Exchange | `arbitrator_upg_alt`, enemy second pick | U | S |
| `phase_step` | Phase Step | `h3_jotunn` teleport, free | U | S |
| `reposition` | Riptide | `arbitrator` Command: Reposition | P | S |
| `scrappers` | Crew x3 | `locust` sequenceEffect | P | S |
| `steal_on_hit` | Pilfer | `angel_upg` steal_buffs (limit 1 unverified) | U | S |
| `steal_area` | Wrathful Chalice | `angel_upg` ability 3 | P | S |
| `reduce_counters` on hit | Pinning Talons | `unfrozen_cultist_upg` | U (on counterattacks) | S |
| `shot` / `melee_strike` param `mech` | Pinning Volley, Devour (vampirism), Flay (dispel) | h3_nix, `magic_fatal_decay` | U | S |
| `magic_strike` | Lightning Strike | magic_pure dealer (`hive_queen`) | U (the formula may go flat) | S |
| `opening_buff` / `opening_rally` | Surprise Attack, War Drums | qilin start_battle, finite duration | U | S |
| `on_wait_buff` | Perch x3 | `skill_formation_1_unit_bonus` | P (trigger), U (on a unit) | S |
| `round_ramp` | Gathering Momentum | `assassin_upg_alt` start_round + `escalate` | U | S |
| `defend_pulse` | Huddle x3 | `unit_skip` + kw_rally shape | U | S |
| `round_pulse` / end-round self heal | Renewing Flame, Reassemble x3 | `h3_walking_dead_upg` heal_percent | U | S |
| `wait_burrow` | Burrow x3 | `magic_shade_cloak_effect_0` | U | S |
| `anchor_aura` | Spirit Anchor | `magic_arinas_chosen_effect_0` | U (baseline resets on refresh) | M |
| `grant_turn` | Warlord's Command | trickster `add_action_points` | U | S |
| `focus_gift` / `focus_stat` / `focus_on_damage` | Spirit Gift, Wind Shear, Runic Feedback, Static Build-up | godslayer_upg `add_energy`; native unit stats | P | S |
| `pierce_attack` / `pierce_shot` / `counter_shape` | Trample x3, Raking Shot (counter_shape now unused) | `attack_reach_x1_x100_x50` | U on shots | S |
| `area_debuff_self` | Overgrowth | `sunlight_cavalry_upg` envelope | U | S |
| `glare` (now a plain `stat_aura`) | Basilisk Stare | existing `stat_aura` | P | S |
| `counter_kill` | Withering Gaze | Death Stare `kill_stacks` on a counterattack | U (the biggest native unknown) | S |
| `scavenge` | Scavenge x3 | olgoi `destroy_corpse_and_heal` | P | S |
| `petrify_gaze`, Champion `keep_ability from` | Stone Gaze copy, Cavalry Press | own rows | P | S |
| `giant_slayer` | Giant Slayer | `damagePerDeltaLevel` (trick_demon) | P | S |
| `dot_cast` | Ignite | `phoenix_ignition` | U | S |
| `ray_barrage` | Ray Barrage | `bonus_magic_pure_bolt` multicast on a physical shot | U | S |
| `cave_in` | Cave-In | `cave_in_obstacle` (hero spell) | U | S |
| `venom_burst` (Dungeon) and `toxic_cloud` (Fortress) | Venom Burst, Toxic Cloud | `activate_all_buff_actions`; kw_rally at enemies | P / U | S |
| Inferno `mana_echo`, `death_mana`, `drive`, `raise_demons` | Magic Channel, Soul Tithe, Crack the Whip, Raise Demons | `sub_skill_tactics_3`, peasant, graverobber, lich_upg_alt | U | S / S / S / M |
| `necropolis_mana_drain`, contagion buff, vampirism overflow | Mana Drain, Contagious Disease, Life Drain | hydra_upg start_turn; disease | U (ally side relative to the bearer; overflow value may not exist) | S / M / M |
| `ally_death_buff` | Vengeance of Heaven | unit_died allegiance ally + `escalate` | U | S |
| `free_teleport` (now unused: Descend cut) | n/a | n/a | n/a | n/a |
| Review additions (R) | Shield of Faith (effect-immunity cast), Lodestone Draw (`transfer_buffs`), Siren Song (`ent_taunt_buff` single cast), Rally Bell (tag dispel), Shepherd (add_energy on swap), tag damage mods (Wind Reader, Raider, Bedrock) | the named native rows | U, except tag mods = P | S each |

### 4.3 New buffs

There are about 40 new buff rows. All are clones of verified rows: `hydra_debuff`, `ent_root`, `medusa_stone`, `frog_poison`, `magic_nairas_kiss_effect_1`, `magic_reality_distortion_effect_0/1`, `succubus_debuff_3`, `sunlightCavalry_buff_1`, `qilin_wisp_buff_1` and `magic_shade_cloak_effect_0`. Buffs are risk P apart from the stats noted above.

The two Burning buffs and the Burning tag are the only new cross-faction vocabulary. They must stay untagged `overTime_effect`, so that Dungeon's Venom Burst does not detonate them.

Counts by risk across 4.1 and 4.2 (keywords about 48): **H 6, U about 52, P about 20.**

---

## 5. Open design questions

1. **Conflux fusions: how loose?** You said the rules will have to loosen for 142 fusions. The choices:
   - **(A) Native only.** Fusions inherit only native-data cards: buffs, passives, tag damage mods, riders. Per-unit plugin rules are dropped on fusions, and the build prints a disclosure list (today: Flutter Away and Psychic Feedback). Duplicates among fusions are fine.
   - **(B) Generic inheritance.** Plugin rules are keyed by the parent element SID, and every fusion takes its host's and guest's rules merged by kind (host value wins). Duplicates are fine. This needs the `build_unit_kit_runtime_table.py` change.
   - **(C) Host only.** Fusions take only the host's plugin rules, and the guest contributes native cards only.
   
   Recommendation: **A**. Bedrock moved the earth line's defence to native data, so A now loses only two plugin cards.
2. **Hidden plugin math.** About 30 new "+x% when …" cards are invisible to the AI and the forecast. The choices:
   - **(A)** Accept them as drafted.
   - **(B)** Cap each faction at 2 hidden damage conditionals and convert the rest to visible native riders. Stronghold has 6 and would be hit hardest.
3. **Generic resists kept as "line identity".** These are Iron Hide, Leathery Wings, Small Target, Thick Hide and Wing Buffet: 15 rows. The choices:
   - **(A)** Keep them.
   - **(B)** Cut all 15. Each line gets a body bump instead.
4. **Where "kill → act again" lives.** The choices:
   - **(A)** Castle Swordsman alt (this review), with Overrun on the Ancient Behemoth.
   - **(B)** Stronghold Ancient Behemoth Rampage (the Stronghold draft), with Castle Swordsman alt keeping only Shield Brother and a body bump.
5. **Initiative debuffs.** These are the new "Speed debuffs". The choices:
   - **(A)** Allow the 4 new ones.
   - **(B)** At most one per faction. That turns War Unicorn Radiant Horn into a different rider, because Rampart has no other.

---

## 6. Build order

Each wave ships only after the one before it holds in game. Use the quick test tier (compile + crash guards), not the full validators.

**Wave 0: prove the unknowns first.** Use one test unit per item in a scratch Core.

- New hooks (**H**): `charge_no_counter` (counter suppression at commit), `scatter`, `bodyguard`, `overkill_carry`, `raise_by_hp`, `spell_echo`.
- Native unknowns:
  - `kill_stacks` on a counterattack (Withering Gaze);
  - `swap_units` with an enemy pick;
  - `accumulateDamage` on a unit buff (Glacial Rune, Infernal Bargain);
  - `add_action_points` on a non-active ally;
  - `untargetable` granted on Wait;
  - push on a counterattack;
  - `steal_buffs` and `dispel` limited to 1;
  - `healthLimitMinPercent` refreshed by an aura;
  - an ally-relative `castTarget` on a buff action (Contagion);
  - a reach pattern on a shot.

Any item that fails gets the card's own fallback from its draft before Wave 3.

**Wave 1: shared plugin infrastructure.**

- The `turn_state` stamp table.
- `counter_state`, `first_hit`, `adjacency`, `hit_this_round` and `vs_buff_tag`.
- The `abilityOnly` flag and the attack-queue triggers (`guard_strike`, `zone_shot`, `arrival_buff`).

That gives one generator change and one C# enum batch, and it unlocks most damage-step cards at once.

**Wave 2: shared native keywords and buffs.**

- `push_on_hit`, `pull`, `bull_rush`, `cooldown_strike`, `scrappers`, `extra_turn_on_kill`, `pierce_attack`, `on_wait_buff`, `round_ramp`, `defend_pulse`, the focus keywords and the tag damage mods.
- The Burning buffs.

**Wave 3: factions, lowest risk first.**

- Cove (all native)
- Bulwark
- Dungeon
- Fortress
- Factory
- Tower
- Castle
- Rampart
- Necropolis
- Stronghold
- Inferno (Raise Demons last)
- Conflux last, with the fusion rule from question 1

Each faction then gets one `unit_design_lab.py check` and its body re-pricing (from the draft power notes, plus the +5-8% bumps on the "drop" rows above), before the next faction starts.

**Wave 4: in-game pass and AI/forecast review.** Watch these stacks:

- Living Cover with Shield Wall;
- Mark of Death, Bone Cage and Wail;
- Glacial Rune with Regeneration;
- Lodestone Field with Lodestone Draw;
- Talon Riposte with Unlimited Retaliation.

---

## 7. Owner decisions (2026-11-21)

These override sections 1-6 where they differ.

1. **Fusions: option A.** Fusions inherit native-data cards only. The build prints the plugin cards it drops (Flutter Away, Psychic Feedback). Duplicates among fusions are fine.
2. **Hidden damage conditionals: option B.** At most 2 per faction. The rest become visible native riders; see `HIDDEN_CAP.md`. Already settled: Stronghold keeps Pack Hunt and Pulverize, Castle keeps Stand Ground and Retribution.
   - Hobgoblin, **Gang Mark**, P: "Basic attacks give the target -2 Defence until the end of the round. Does not stack." Replaces Opportunist.
   - Boar alt, **Gore**, A 1/1: "Performs a Melee attack. The target takes +15% Damage from all sources until the end of the next round." Replaces the allies-acted Gore.
   - Orc alt, **Cripple**, P: "Ranged attacks give the target -1 Speed until the end of the next round, stacking up to -3." Replaces Prey on the Weak. It is named Cripple because the Orc line already has an active called Hamstring.
   - Cyclops King, **Siege Breaker**, P: "Ranged attacks end the target's Defend stance and remove its positive Defence effects before the Damage." Replaces the +30% version.
   - Monk alt, **Smite**, P: "Deals +30% Damage to undead and demons." Native `outDmgModsByTargetTags`. Replaces Humble the Mighty.
   - `HIDDEN_CAP.md` converts the remaining conditionals in the other factions. Two of them land in factions settled above:
     - Castle's Challenge becomes a buff with a tag damage mod.
     - Stronghold's Goblin Safety in Numbers, which the first count missed, becomes **Expendable**.
   - Most conversions move "+X% against a target that has buff B" onto buff B as a tag-keyed damage mod. The pattern is proven by `homm3_tower_graft_716` and `homm3_tower_graft_60`.
   - **Build requirement:** h3 units carry no undead, demon, shooter or flyer tags. The builder must stamp `h3_kit_*` tags for Smite, Raider, Wind Reader and Bedrock, or those cards hit nothing.
   - **Added to Wave 0:**
     - Expendable: a dying stack casting from its own hex.
     - Challenge: whether damage mods add or multiply.
     - Shatter: power check, since it stacks on vanilla petrify's +100%.
3. **Generic resists: neither kept nor folded into bodies.** Each one becomes a conditional card that suits its unit (table below).
4. **Kill → act again: keep all three**, made distinct by trigger and limit. Collision #2 is withdrawn, and Overrun (`overkill_carry`) leaves the H list.
   - Castle Swordsman alt, **Follow Through**, P: "When this creature's attack destroys an enemy stack during its turn, it can act again. Once per round."
   - Stronghold Ancient Behemoth, **Rampage**, P: "When this creature destroys an enemy stack during its turn, it immediately takes another turn. Once per battle." It is once per battle because it sits on a tier 7 with 50% Armor Rend; the draft itself called it the faction's strongest card.
   - Necropolis Ghost Dragon alt, **Deathly Plunge**, A 3/3: "Performs a Melee attack. If it destroys the target stack, this creature can act again this round." Only the active triggers it (the draft's version, not the refund).
5. **Initiative debuffs: option A.** All 4 stay.

### Resist replacements

The cards are visible native data unless marked U, where a filter or trigger combination is unproven. None reads a faction skill.

| Unit | Was | New card | Text | Build |
|---|---|---|---|---|
| Kobold | Small Target | **Scurry**, P | "After a Ranged attack hits it, gains +2 Speed until the end of its next turn." | `unit_took_damage` self, filtered to shots, then a self buff (Speed). U: the shot filter (`allegiance_receiving_tags`). Fallback: any damage. |
| Kobold Foreman | Small Target | **Scurry**, P | "After a Ranged attack hits it, gains +2 Speed and +2 Initiative until the end of its next turn." | As Kobold, with a bigger buff (Tempo). |
| Kobold alt | Small Target | **Duck Behind Shields**, P | "After the first Ranged attack that hits it each round, takes -50% Ranged Damage until the end of the round." | Same trigger. The buff carries shoot `inDmgMods` -0.5 with duration 1 and does not stack (Bastion: the first volley lands, the rest do not). |
| Mammoth | Thick Hide | **Momentum Hide**, P | "After it moves, takes -25% Ranged Damage until its next turn." | `unit_end_move` self, then a buff with shoot `inDmgMods`. It pays off Trample: walk in, then shrug off the return volley. |
| War Mammoth | Thick Hide | **Shrug Off**, P | "Whenever it takes Damage, its negative effect with the shortest duration ends." | `unit_took_damage` self, then `dispel` count 1 on negative tags. U: the Wave 0 dispel-limited-to-1 item. A Bastion payoff for being hit. |
| Mammoth alt | Thick Hide | **Momentum Hide**, P | "After it moves, takes -35% Ranged Damage until its next turn." | As Mammoth, at -35% (Tempo moves more). |
| Gorgon | Iron Hide | **Corroding Hide**, P | "Creatures that attack it in Melee are Corroded: -3 Defence until the end of the round." | A `when_damaged` attacker debuff, melee filter. It reuses `h3_kit_fortress_corroded_effect` at duration 1. |
| Mighty Gorgon | Iron Hide | **Corroding Hide**, P | "Creatures that attack it in Melee are Corroded: -3 Defence until the end of the next round." | As Gorgon, duration 2 (Warden). It sets up the line's Corroded payoffs. |
| Gorgon alt | Iron Hide | **Iron Rush**, P | "In the first round, has +2 Speed and takes -30% Melee Damage." | A `start_battle` self buff with duration 1 (the Surprise Attack / War Drums layout): the Hunter crosses the field armoured. |
| Wyvern | Leathery Wings | **Updraft**, P | "When it Waits, it takes -40% Ranged Damage until its next turn." | `on_wait_buff` with shoot `inDmgMods`. Tower's Perch is Wait → Damage, a different stat and faction. |
| Wyvern Monarch | Leathery Wings | **Wing Shield**, P (aura) | "Adjacent friendly creatures take -20% Ranged Damage." | `stat_aura` radius 1, ally, shoot `inDmgMods`. U: inDmgMods through an aura. The Warden protects others rather than itself. |
| Wyvern alt | Leathery Wings | **Climb Away**, P | "After it uses Thunder Dive, takes -40% Ranged Damage until its next turn." | `unit_cast_ability` self (`ability_and_allegiance`), then a buff. The Hunter dives in, then climbs out of bow range. |
| Roc | Wing Buffet | **Tailwind**, P | "When it Defends, gains +2 Speed until the end of its next turn." | `unit_skip` self buff (the formation_5 layout). |
| Thunderbird | Wing Buffet | **Gathering Storm**, P | "At the start of each round, gains +10% Damage, up to +30%. Using Lightning Strike resets it." | A `start_round` grant with `escalate`, and a `unit_cast_ability` self dispel. The Finisher hits hardest late. |
| Roc alt | Wing Buffet | **Tailwind**, P | "When it Defends, gains +3 Speed and +2 Initiative until the end of its next turn." | As Roc, with a bigger buff (Opener). |

Physical `resist` rows after the pass: **0**. The magic identity resists (Born of Flame, Magic Resistance, Spell Damage Reduction, Spirit Ward) are unchanged.
