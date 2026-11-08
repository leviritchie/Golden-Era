# HoMM3 Custom Unit Identity Encapsulation Audit - 2026-06-25

Status: source-validated, runtime-unvalidated diagnostic audit.

This is a hand-scored identity pass over the current HoMM3 custom unit set. It compares each current Olden Era custom unit identity against locally available Horn of the Abyss and Tears of Ashan identity evidence. Extra Olden Era features do not reduce a score; missing source identity features do.

Proof boundary:
- Current editable Olden Era source: `custom_factions/homm3_*.json` and `custom_factions/ability_overrides/homm3_*.json`.
- Current generated/baseline identity evidence: `artifacts/ability_audit_inventory/unit_ability_inventory.json` plus current override JSON for newer active rows.
- HotA local evidence: Cove creature configs under `vcmi/Mods/hota/mods/cove/Content/config/hota/cove/creatures/` and HotA creature balance JSONC under `vcmi/Mods/hota/mods/gameBalance/mods/creatures/content.zip`.
- ToA local evidence: `vcmi/Mods/tears-of-ashan/content.zip` creature configs; the subagent also cross-referenced `docs/homm3_tears_of_ashan_creature_specs.md`.
- No Core rebuild, deploy, live bridge inspection, or battle/recruitment runtime proof was run for this audit.

Score scale:
- 5: Source identity is fully represented, or the source unit has no meaningful missing special.
- 4: Main identity is present, but a minor source detail, target filter, quantity, aura, or validation gap remains.
- 3: Recognizable partial port; at least one important source feature is missing.
- 2: Mostly divergent; only a weak or adjacent feature remains.
- 1: Signature identity is effectively absent.

## Castle - average 4.57

- T1 Pikeman 5 / Halberdier 5 / Glaivier 2. OE covers base/standard with stun actives, but Glaivier misses ToA charge immunity and instead has Execute.
- T2 Archer 5 / Marksman 5 / Crossbowman 4. Ranged and double shot are covered; Crossbowman has no-range style and debuff coverage, but not the exact ToA no-wall plus defense-reduction package.
- T3 Griffin 5 / Royal Griffin 5 / Battle Griffin 5. Flying, extra/unlimited retaliation, and Battle Griffin double strike/ferocity identity are represented.
- T4 Swordsman 5 / Crusader 5 / Guardsman 5. Crusader double strike and Guardsman extra-retaliation identity are represented.
- T5 Monk 5 / Zealot 5 / Priest 5. Ranged/no-melee identity is represented, and Priest has Bless-style casting.
- T6 Cavalier 5 / Champion 5 / Justiciar 5. Jousting/charge identity is represented; Justiciar also has an attack/defense opening and forced-move extra.
- T7 Angel 3 / Archangel 4 / Seraph 3. Flying and resurrection-style identity exist, but ToA morale/hate/Prayer/King-style Seraph identity is only partially represented.

## Rampart - average 4.48

- T1 Centaur 5 / Centaur Captain 5 / Centaur Ranger 5. Centaur Ranger shooter identity is represented; base/standard have no missing special.
- T2 Dwarf 3 / Battle Dwarf 3 / Dwarf Battlerager 1. Dwarf/Battle Dwarf get defensive actives, but classic magic-resistance flavor is not clearly represented; Battlerager misses ToA self-Bloodlust.
- T3 Wood Elf 5 / Grand Elf 5 / Elf Wardancer 5. Shooter, double shot, and Wardancer extra attack are represented.
- T4 Pegasus 4 / Silver Pegasus 4 / Gold Pegasus 5. Flying is represented, and Gold Pegasus has no-retaliation plus Hourglass; the base/standard anti-magic aura identity is only partial.
- T5 Dendroid Guard 5 / Dendroid Soldier 5 / Dendroid Shaman 5. Binding is represented, and Shaman also carries a resurrection-style action.
- T6 Unicorn 5 / War Unicorn 5 / Pristine Unicorn 4. Blind is represented; Pristine Unicorn has Radiant Armor but not the exact ToA spell-resistance aura.
- T7 Green Dragon 5 / Gold Dragon 5 / Diamond Dragon 5. Flying, breath attack, and spell-immunity identities are represented.

## Tower - average 4.52

- T1 Gremlin 5 / Master Gremlin 5 / Gremlin Mechanic 4. Shooter and Repair identity are present; Mechanic target filtering is still documented as needing validation.
- T2 Stone Gargoyle 4 / Obsidian Gargoyle 4 / Elemental Gargoyle 3. Flying/bloodless identity is present, but Elemental Gargoyle's exact elemental resistances and petrify immunity are not fully proven in current behavior.
- T3 Stone Golem 5 / Iron Golem 5 / Magnetic Golem 4. Golem construct and spell-damage-reduction identities are present; Magnetic Golem has slow/Web identity but exact immunity filters remain a gap.
- T4 Mage 5 / Arch Mage 5 / Battle Mage 4. Shooter/no-penalty/spell-cost identity is represented; Battle Mage has bolt/spell actions, but the exact shared cast pool remains unvalidated.
- T5 Genie 4 / Master Genie 5 / Genie Vizier 4. Flight, beneficial-spell, and repositioning identities are represented; Efreet-hate and exact air-resistance traces remain partial for Genie/Vizier.
- T6 Naga 5 / Naga Queen 5 / Naga Rani 5. No-retaliation/fixed-damage identity is represented, and Naga Rani adds the multi-headed attack shape.
- T7 Giant 5 / Titan 5 / Colossus 4. Mind immunity, Titan shooter identity, and dragon-hate are represented; Colossus has Thunderbolt/Judgement, but ToA after-attack Thunderbolt is not exact.

## Inferno - average 2.67

- T1 Imp 1 / Familiar 2 / Vermin 3. Familiar/Vermin have mana or mobility features, but the ToA demonic/fire/Holy Word identity is mostly missing.
- T2 Gog 3 / Magog 3 / Amalek 2. Shooter identity is present; Amalek misses ToA Inferno casting, and all three miss demonic/fire identity.
- T3 Hell Hound 2 / Cerberus 4 / Fire Hound 3. Cerberus has no-retaliation and multi-target breath shape; Fire Hound has breath; demonic/fire identity is missing.
- T4 Demon 2 / Horned Demon 1 / Gore Demon 2. Gore Demon has an attack/defense debuff, but ToA jousting and demonic/fire identity are not represented.
- T5 Pit Fiend 2 / Pit Lord 4 / Pit Spawn 2. Pit Lord has an animate/summon-adjacent row, but Pit Spawn misses ToA Meteor Shower and demonic/fire identity.
- T6 Efreeti 3 / Efreet Sultan 3 / Efreet Sufi 3. Flying and fire-flavored actions are present; fire shield/immunity, Genie hate, and random negative spellcasting are partial or missing.
- T7 Devil 4 / Arch Devil 4 / Arch Demon 3. Teleport/no-retaliation identity is represented; luck aura, Angel hate, demonic/fire identity, and Arch Demon gating are missing or partial.

## Necropolis - average 3.95

- T1 Skeleton 3 / Skeleton Warrior 3 / Skeleton Archer 4. Skeleton Archer shooter identity is represented; undead identity is not clearly surfaced across the line.
- T2 Walking Dead 4 / Zombie 4 / Rot Zombie 4. Debuff/rotting identities are represented; undead identity remains implicit or unsurfaced.
- T3 Wight 4 / Wraith 3 / Banshee 3. Regeneration and mana/scream actions are present, but Wraith life drain and Banshee death-ripple/mana-drain details are partial.
- T4 Vampire 5 / Vampire Lord 5 / Vampire Prince 5. Flight/no-retaliation and Vampire Lord/Prince drain identities are represented; Prince also has blind.
- T5 Lich 5 / Power Lich 5 / Lich Master 5. Shooter/area strike identity is represented; Lich Master adds animate-dead style casting.
- T6 Black Knight 4 / Dread Knight 3 / Dreadtaur 4. Curse/debuff identity is present, but Dread Knight double-damage/death-blow identity is not clearly represented.
- T7 Bone Dragon 3 / Ghost Dragon 3 / Spectral Dragon 4. Flying and curse/morale-adjacent rows exist; Spectral Dragon has death-stare style identity, but skeleton-transformer and morale aura details are partial.

## Dungeon - average 4.29

- T1 Troglodyte 3 / Infernal Troglodyte 3 / Chthonian 3. Stun/teleport actives are present, but blind/petrify immunity identity is missing or not surfaced.
- T2 Harpy 5 / Harpy Hag 5 / Fury 5. Flying, strike-and-return, no-retaliation, and extra-attack identity are represented.
- T3 Beholder 5 / Evil Eye 5 / Fargazer 3. Shooter/no-penalty identity is represented; Fargazer misses ToA Visions hero-map utility.
- T4 Medusa 5 / Medusa Queen 5 / Medusa Warrior 5. Stone gaze is represented, and Warrior adds Slither Away.
- T5 Minotaur 4 / Minotaur King 4 / Minotaur Taskmaster 3. Morale/blessing flavor is present, but Taskmaster's ToA morale aura/floor is only partial.
- T6 Manticore 5 / Scorpicore 5 / Chimera 3. Manticore/Scorpicore paralyze identity is represented; Chimera misses ToA paralyze and exact three-headed shape.
- T7 Red Dragon 5 / Black Dragon 5 / Shadow Dragon 4. Flying, breath, and spell immunity are represented; Shadow Dragon has poison/acid-adjacent identity but not the full ToA acid/hate package.

## Stronghold - average 4.33

- T1 Goblin 4 / Hobgoblin 3 / Goblin Trapper 3. Baseline is mostly fine, but ToA battlecry and Hobgoblin Bloodlust/Goblin Trapper Land Mine are not fully represented.
- T2 Wolf Rider 5 / Wolf Raider 5 / Boar Rider 4. Wolf Raider ferocity is represented; Boar Rider has charge identity but not exact ToA jousting.
- T3 Orc 5 / Orc Chieftain 3 / Orc Berserker 2. Shooter identity is represented; Chieftain misses ToA extra attack, and Berserker misses Berserk-after-attack/return.
- T4 Ogre 5 / Ogre Mage 5 / Ogre Brute 2. Ogre Mage Bloodlust is represented; Ogre Brute's ToA Frenzy-before-attack identity is replaced by a mobility strike.
- T5 Roc 5 / Thunderbird 5 / Shahrokh 5. Flying, Thunderbird lightning, and Shahrokh ferocity/double-strike identity are represented.
- T6 Cyclops 5 / Cyclops King 5 / Blood-Eyed Cyclops 5. Shooter and siege/no-range identities are represented.
- T7 Behemoth 5 / Ancient Behemoth 5 / Ghost Behemoth 5. Armor-rend identity is represented across the line, with Ghost Behemoth also flying.

## Fortress - average 4.19

- T1 Gnoll 5 / Gnoll Marauder 5 / Gnoll Shaman 4. Gnoll Shaman has curse/weakening identity but not the exact ToA two-cast Curse/Weakness caster package.
- T2 Lizardman 5 / Lizard Warrior 3 / Lizard Assassin 3. Shooter identity is represented; Lizard Warrior poison and Assassin teleport/limited-range poison package are partial.
- T3 Serpent Fly 5 / Dragon Fly 5 / Damsel Fly 4. Flying and dispel/weakening identity are represented; Damsel Fly misses ToA strike-and-return.
- T4 Basilisk 5 / Greater Basilisk 5 / Basilisk Flamespitter 3. Stone gaze is represented; Flamespitter misses exact breath/fire-resistance identity.
- T5 Gorgon 5 / Mighty Gorgon 5 / Corrosive Gorgon 4. Mighty Gorgon death stare is represented; Corrosive Gorgon has acid/poison-adjacent identity but not exact acid breath.
- T6 Wyvern 3 / Wyvern Monarch 4 / Paokai 3. Flight and poison/lightning-adjacent actions exist, but regeneration and exact Paokai lightning breath are partial.
- T7 Hydra 4 / Chaos Hydra 4 / Ruinous Hydra 4. No-retaliation and area/sweeping attack identity are represented, but exact all-adjacent plus regeneration/extra-attack values are not fully matched.

## Conflux - average 3.67

- T1 Pixie 5 / Sprite 5 / Faerie 5. Flying, no-retaliation, multi-target, and mana-channel flavor are represented.
- T2 Air Elemental 2 / Storm Elemental 4 / Hurricane Elemental 3. Storm Elemental shooter/Thunderbolt identity is represented; elemental non-living, immunity, and vulnerability rules are weak or missing.
- T3 Water Elemental 3 / Ice Elemental 4 / Frost Elemental 5. Ice shooter/blind identity is represented; Water Elemental's elemental status is partial, while Frost has no major missing reference special.
- T4 Fire Elemental 2 / Energy Elemental 3 / Plasma Elemental 4. Fire/chain-lightning actions exist, but ToA fire immunity, shield, and vulnerability rules are partial.
- T5 Earth Elemental 2 / Magma Elemental 3 / Lava Elemental 3. Fireball/Firewall actions exist, but ToA non-living, mind immunity, resistances, vulnerabilities, and attack/defense reduction are mostly missing.
- T6 Psychic Elemental 4 / Magic Elemental 4 / Astral Elemental 3. No-retaliation/sweeping identity is represented; non-living/mind immunity and exact spell-immunity/all-adjacent behavior are partial.
- T7 Firebird 4 / Phoenix 5 / Sacred Phoenix 4. Flying, breath, and rebirth are represented; Fire Shield/King/fire-immunity details are partial for Firebird/Sacred Phoenix.

## Cove - average 4.14

- T1 Nymph 5 / Oceanid 5 / Nereid 4. Blink and ice immunity are represented; Nereid has healing and Mirth but not every ToA immunity detail.
- T2 Crew Mate 2 / Seaman 2 / Swashbuckler 5. HotA base/standard have no unit special, but ToA gold generation is missing for Crew Mate/Seaman; Swashbuckler gold generation is represented.
- T3 Pirate 4 / Corsair 5 / Sea Dog 4. Shooter/no-melee identity is represented; Corsair no-retaliation is represented; Sea Dog has an Accurate-Shot substitute but not exact passive death-stare behavior.
- T4 Stormbird 5 / Ayssid 3 / Halcyon 3. Stormbird flying is represented; Ayssid misses ferocity, and Halcyon has storm flavor but not exact ToA Thunderbolt-after-attack.
- T5 Sea Witch 4 / Sorceress 4 / Tidecaller 4. Shooter/Weakness identity is represented; Disrupting Ray is missing or partial; Tidecaller has Summon Fangarms.
- T6 Nix 5 / Nix Warrior 5 / Nix Praetorian 5. Attack-reduction shield identity is represented, and Praetorian adds bind.
- T7 Sea Serpent 5 / Haspid 3 / Abyss Serpent 5. Sea Serpent poison and Abyss Serpent poison/curse/fear identity are represented; Haspid misses Revenge.

## Highest-Priority Identity Gaps

1. Inferno: demonic/fire/Holy Word identity is mostly absent across the faction, and several ToA caster/aura identities are missing.
2. Conflux: elemental non-living, mind immunity, school immunities/resistances, and vulnerability rules are weakly represented compared with ToA.
3. Cove: Haspid Revenge, Ayssid ferocity, Sea Witch/Sorceress Disrupting Ray, and Crew Mate/Seaman gold generation are the largest missing source identities.
4. Rampart: Dwarf magic resistance/Battlerager Bloodlust and Pristine Unicorn exact spell-resistance aura are the main holes.
5. Necropolis: undead/morale/skeleton-transformer identity is not consistently surfaced, and Dread Knight double-damage is not clearly represented.

## Recommended Next Pass

Do not patch individual rows ad hoc. The professional path is a small source contract for identity preservation: per custom unit, list source-required identity tokens, mark which are intentionally substituted, and validate generated Core rows for those tokens. That gives future agents a build/deploy gate before they can accidentally remove or silently replace HoMM3 identity features.