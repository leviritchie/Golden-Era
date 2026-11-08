# HoMM3 HotA Cove Release Port Spec

Status: release-quality future-porting spec.

Source assumption: Cove is a Horn of the Abyss faction, not a HoMM3 Complete faction. Creature stats and mechanics below target HotA behavior. Asset extraction must use a HotA-capable source lane; HoMM3 Complete LOD-only extraction is insufficient for Cove sprites, town art, Cannon art, and audio.

Current local source lane: `vcmi/Mods/hota/mods/cove/Content/...` is the primary source for HotA Cove config, creatures, town, map objects, heroes, sounds, and Accurate Shot. Cannon-specific config, sprites, and sounds live in `vcmi/Mods/hota/mods/cannon/Content/...`. Start Cove release work from `custom_factions/homm3_cove.json` and `tools/deploy_homm3_cove_assets.py`; do not substitute donor Human/Nature/Dungeon art or HoMM3 Complete LOD assets when HotA Cove source files are required.

Primary sources checked on 2026-05-12:

- Heroes 3 wiki, Cove: https://heroes.thelazy.net/index.php/Cove
- Heroes 3 wiki, Nymph and Oceanid: https://heroes.thelazy.net/index.php/Nymph_and_Oceanid
- Heroes 3 wiki, Crew Mate and Seaman: https://heroes.thelazy.net/index.php/Crew_Mate_and_Seaman
- Heroes 3 wiki, Pirate, Corsair, and Sea Dog: https://heroes.thelazy.net/index.php/Pirate,_Corsair,_and_Sea_Dog
- Heroes 3 wiki, Stormbird and Ayssid: https://heroes.thelazy.net/index.php/Stormbird_and_Ayssid
- Heroes 3 wiki, Sea Witch and Sorceress: https://heroes.thelazy.net/index.php/Sea_Witch_and_Sorceress
- Heroes 3 wiki, Nix and Nix Warrior: https://heroes.thelazy.net/index.php/Nix_and_Nix_Warrior
- Heroes 3 wiki, Sea Serpent and Haspid: https://heroes.thelazy.net/index.php/Sea_Serpent_and_Haspid
- Heroes 3 wiki, Poisonous: https://heroes.thelazy.net/index.php/Poisonous
- Heroes 3 wiki, Weakness: https://heroes.thelazy.net/index.php/Weakness
- Heroes 3 wiki, Disrupting Ray: https://heroes.thelazy.net/index.php/Disrupting_Ray
- HotA documentation, Cove and Cannon entries: https://h3hota.com/en/documentation

## Faction Defaults

| Field | Requirement |
| --- | --- |
| Faction SID | `homm3_cove` |
| City SID | `homm3_cove_city` |
| Primary donor faction | `humans` for pirate/shooter UI; monster donors selected per creature behavior after static trace. |
| Primary donor city | Choose after city graph review; Cove must not inherit non-Cove town behavior text. |
| HoMM3 classes | Captain, Navigator |
| OE class labels | Captain, Navigator |
| Mage Guild cap | Level 4 |
| Native terrain | Swamp. After Lodestar, Cove creatures move on any terrain without penalty and gain +1 attack, defense, and speed; they also see/ignore mines and see quicksand. Cove siege combat remains swamp. |
| Risk | High; HotA asset lane, Cannon, Accurate Shot, after-shot spells, Poisonous, Revenge, and water/shipyard systems need implementation-grade tracing. |

Identity pillars:

- Pirate ranged pressure and firearm identity.
- Ocean monsters and water-magic debuffs.
- High attack, lower defense.
- Cannon as the faction-defining war machine / faction skill surface.
- Cove-specific mechanics implemented as concrete behavior, not flavor text.

## HotA Unit Stats And Abilities

All rows are HotA creature stats. `Shots` is `0` for non-shooters. `Cost` omits resource text when gold-only.

| Tier | Creature | Atk | Def | Dmg | HP | Spd | Move | Size | Growth | Shots | Cost | AI | Fight | HotA abilities |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | Nymph | 5 | 2 | 1-2 | 4 | 6 | Teleporting | 1 | 16 | 0 | 35 gold | 57 | 52 | Teleportation. Immune to Ice Bolt, Frost Ring, and Freezing Shot. |
| 1+ | Oceanid | 6 | 2 | 1-3 | 4 | 8 | Teleporting | 1 | 16 | 0 | 45 gold | 75 | 60 | Teleportation. Immune to Ice Bolt, Frost Ring, and Freezing Shot. |
| 2 | Crew Mate | 7 | 4 | 2-4 | 15 | 5 | Ground | 1 | 9 (+4 Pub) | 0 | 110 gold | 155 | 155 | No special combat ability. |
| 2+ | Seaman | 8 | 6 | 3-4 | 15 | 6 | Ground | 1 | 9 (+4 Pub) | 0 | 140 gold | 174 | 174 | No special combat ability. |
| 3 | Pirate | 8 | 6 | 3-7 | 15 | 6 | Ground | 1 | 7 | 4 | 225 gold | 312 | 208 | Shooter. No melee penalty. |
| 3+ | Corsair | 10 | 8 | 3-7 | 15 | 7 | Ground | 1 | 7 | 4 | 275 gold | 407 | 311 | Shooter. No melee penalty. No enemy retaliation. |
| 3++ | Sea Dog | 12 | 11 | 3-7 | 15 | 8 | Ground | 1 | 7 | 12 | 375 gold | 602 | 376 | Shooter. No melee penalty. No enemy retaliation. Accurate Shot. |
| 4 | Stormbird | 10 | 8 | 6-9 | 30 | 9 | Flying | 2 | 4 (+3 Roost) | 0 | 275 gold | 502 | 386 | Flying. |
| 4+ | Ayssid | 11 | 8 | 6-10 | 30 | 11 | Flying | 2 | 4 (+3 Roost) | 0 | 325 gold | 645 | 478 | Flying. Ferocity. |
| 5 | Sea Witch | 12 | 7 | 10-14 | 35 | 6 | Ground | 1 | 3 | 12 | 515 gold | 790 | 608 | Shooter. Spellcaster after shot at Basic level: Weakness or Disrupting Ray. |
| 5+ | Sorceress | 12 | 9 | 10-16 | 35 | 7 | Ground | 1 | 3 | 12 | 565 gold | 852 | 655 | Shooter. Spellcaster after shot at Advanced level: Weakness or Disrupting Ray. |
| 6 | Nix | 13 | 16 | 18-22 | 80 | 6 | Ground | 1 | 2 | 0 | 1000 gold | 1415 | 1415 | Ignores 30% of enemy Attack skill. |
| 6+ | Nix Warrior | 14 | 17 | 18-22 | 90 | 7 | Ground | 1 | 2 | 0 | 1300 gold | 2116 | 1763 | Ignores 60% of enemy Attack skill. |
| 7 | Sea Serpent | 22 | 16 | 30-55 | 180 | 9 | Ground | 2 | 1 | 0 | 2200 gold + 1 sulfur | 3953 | 3162 | Poisonous. Slayer treats Sea Serpent as a valid target. Skeleton Transformer converts to Bone Dragon. |
| 7+ | Haspid | 29 | 20 | 30-55 | 300 | 12 | Ground | 2 | 1 | 0 | 4000 gold + 2 sulfur | 7220 | 5554 | Poisonous. Revenge. Slayer treats Haspid as a valid target. Skeleton Transformer converts to Bone Dragon. |

## Creature Ability Definitions

| Ability | HotA definition | Porting requirement |
| --- | --- | --- |
| Teleportation | Nymph and Oceanid move by teleporting. | Must ignore normal path blocking for movement while still obeying legal destination, occupancy, and combat-grid constraints. |
| Ice spell immunity | Nymph and Oceanid are immune to Ice Bolt, Frost Ring, and Freezing Shot. | Implement exact spell/effect immunity list or mark blocked until spell-id mapping is traced. Do not replace with generic water resistance text. |
| Shooter | Pirate/Corsair/Sea Dog and Sea Witch/Sorceress perform ranged attacks with listed shot counts. | Base Pirates are ranged from the start. Implement shot depletion, range penalty, obstacle penalty, and melee blocking consistently with OE shooter rules unless a traced hook needs adjustment. |
| No melee penalty | Pirates, Corsairs, and Sea Dogs do not suffer the standard 50% shooter melee damage penalty. | Melee attacks by this shooter line must use full damage when adjacent/blocked. |
| No enemy retaliation | Corsairs and Sea Dogs prevent retaliation from melee targets. | Their melee attack must not consume or trigger the defender's retaliation for that combat round. |
| Accurate Shot | Sea Dogs trigger after a shot. Each Sea Dog has a source chance to kill creatures in the target stack; chance multiplier is 3% per Sea Dog when shooting without range penalty and 2% per Sea Dog when shooting with range penalty. Total kills cannot exceed `ceil(attacking Sea Dog count * X / 100)`. HotA documentation says the ability does not work when shooting creatures behind walls; Heroes 3 wiki also notes a war-machine exclusion. Kills the topmost unit(s), so survivors retain full top-unit health. | OE target is a guaranteed focus-point shot ability using the Guillotine effect base (`space_11_magic_decimate`, including rank-4 `assasinate`) per user direction, while preserving the same range-penalty multiplier, blocked cases, and kill cap where safely traceable. Guillotine is only a partial match because it is percent max-unit magic damage rather than Sea Dog top-unit budgeting. If OE lacks top-unit health exposure, static-trace stack-health internals before shipping. |
| Flying | Stormbirds and Ayssids fly. | Must use flying movement/pathing and legal landing checks. |
| Ferocity | If an Ayssid's attack kills at least one creature, it immediately inflicts a second blow. It is a situational double attack and does not apply on retaliation. | User direction is that this is difficult but should be implemented authentically. Trigger only from an Ayssid attack that kills at least one unit, and prevent retaliation-triggered Ferocity unless HotA static trace proves otherwise. |
| Spellcaster after shot | Sea Witches/Sorceresses apply a spell effect after ranged damage. They cast Weakness for 3 rounds on the attacked stack; if Weakness is already applied, they instead cast Disrupting Ray. Sea Witch casts at Basic level; Sorceress casts at Advanced level. | Apply after damage resolution. Weakness: Basic reduces attack by 3; Advanced reduces attack by 6. Disrupting Ray: Basic reduces defense by 3; Advanced reduces defense by 4, stacks cumulatively, lasts until combat end, and is not removed by dispel/cure. |
| Nix attack ignore | Nix ignores 30% of enemy Attack skill; Nix Warrior ignores 60%. | This modifies the defender's effective attack contribution when damage against the Nix stack is calculated. Implement as attack-stat reduction in the damage formula, not as generic armor or flat mitigation. |
| Poisonous | Source behavior is 30% chance after Sea Serpent/Haspid attack or retaliation. Poison decreases target stack maximum health by 10% immediately and by 10% each combat round for three rounds, calculated from the creature stack's statistical maximum health. Reapplication can reduce max health up to 50%. Poison does not kill by itself, can only be removed by Cure, and can affect the same stack once per round. | OE target is a guaranteed focus-point poison attack with the same timing, cap, max-HP reduction, current-HP reduction on application, Cure interaction, and immunity list. Static-trace OE max-health mutation before shipping. |
| Revenge | Before a Haspid attacks, increase its Damage parameter by `sqrt((((initial Haspid count + 1) * one Haspid health) / (current total Haspid health + one Haspid health)) - 1) * 100%`. The effect makes an injured Haspid stack fight harder as stack health/count is lost. | Implement as a pre-attack damage-parameter increase for Haspids only. Store initial stack count at battle start. Use current total Haspid health, including wounded top creature health. Verify rounding against HotA before release. |

## Unit Port Requirements

| Tier | HotA line | Target SID family | Donor direction | Release behavior requirement | Debts |
| --- | --- | --- | --- | --- | --- |
| 1 | Nymph -> Oceanid | `h3_nymph`, `h3_oceanid` | Teleporter/flyer donor only if movement can be made exact. | Teleporting movement plus exact ice spell immunity. | Spell-id immunity mapping; teleport legality. |
| 2 | Crew Mate -> Seaman | `h3_crew_mate`, `h3_seaman` | Human melee shell. | Plain one-hex ground melee with exact stats/growth. | None beyond standard asset/audio extraction. |
| 3 | Pirate -> Corsair -> Sea Dog | `h3_pirate`, `h3_corsair`, `h3_sea_dog` | Shooter shell with no-melee-penalty support. | Pirate is ranged with 4 shots and no melee penalty; Corsair adds no retaliation; Sea Dog has 12 shots, no retaliation, and Accurate Shot via Guillotine-effect direction. | Accurate Shot stack-health/top-unit kill implementation. |
| 4 | Stormbird -> Ayssid | `h3_stormbird`, `h3_ayssid` | Flyer shell. | Two-hex flyer; Ayssid gets authentic Ferocity only after killing at least one unit with its own attack. | Double-attack sequencing and no-retaliation interaction audit. |
| 5 | Sea Witch -> Sorceress | `h3_sea_witch`, `h3_sorceress` | Shooter + after-shot spell hook. | Ranged spellcaster with 12 shots; applies Weakness after shot, then Disrupting Ray if Weakness already exists, at correct spell level. | Spell-state detection; after-damage timing; cumulative Disrupting Ray. |
| 6 | Nix -> Nix Warrior | `h3_nix`, `h3_nix_warrior` | Durable melee shell. | One-hex ground melee that reduces enemy Attack contribution by 30%/60% in damage against it. | Damage formula hook location. |
| 7 | Sea Serpent -> Haspid | `h3_sea_serpent`, `h3_haspid` | Large monster shell. | Two-hex ground monster; Poisonous on attack/retaliation; Haspid adds Revenge. | Poison max-health mutation; Revenge formula/rounding verification. |

## City And Economy

| HotA element | Release requirement | Debts |
| --- | --- | --- |
| Shipyard | Implement only if OE map/water economy supports ship creation and water traversal. If not implemented, text must state exactly what exists and must not claim HotA ship behavior. | Shipyard/water movement static trace. |
| Gunpowder Warehouse | Required for Sea Dog recruitment together with Upgraded Frigate. | City build graph must support a second prerequisite for the 3++ upgrade. |
| Pub | Increases Crew Mate/Seaman growth by +4 per week. | Growth-building mapping. |
| Roost | Increases Stormbird/Ayssid growth by +3 per week. | Growth-building mapping. |
| Nix Fort | Dwelling for Nix/Nix Warrior. | Art and growth table extraction. |
| Maelstrom | Dwelling for Sea Serpent/Haspid; Haspid upgrade costs 4000 gold + 2 sulfur. | Art and upgrade-cost table extraction. |
| Resource Silo | HotA Cove resource income must be verified from HotA data before implementation. | HotA economy table source. |
| Mage Guild | Cap at level 4. | Exact spell probabilities can be pulled from HotA if OE exposes per-town probabilities. |

Economy note: Cove is attack-heavy, has expensive high-impact upgrades, and has a unique Sea Dog double-upgrade prerequisite. Balance work should start from HotA costs/growth, then adjust only through explicit OE balance notes.

## Laws And Faction Skill

Law themes should derive from Cove mechanics:

- Press gangs: Crew Mate/Seaman growth.
- Powder stores: Pirate/Corsair/Sea Dog ranged damage, shot economy, or Accurate Shot support.
- Storm roost: Stormbird/Ayssid speed, initiative, or Ferocity support.
- Witch coven: Sea Witch/Sorceress after-shot debuff accuracy/duration.
- Nix bulwark: Nix attack-ignore identity.
- Maelstrom tithe: Sea Serpent/Haspid growth/cost/poison support.

Faction skill: `Treasure Hunting` (current; supersedes Cannoneering).

- Current design grants Cove-owned 0-mana native Groundsight variants at Basic/Advanced/Expert (`skill_faction_homm3_cove`), per `custom_factions/source_mechanics/homm3_cove.json` (`cove.treasure_hunting`, status substituted). The Cannon support stack proved unstable and is abandoned; player text must not promise Cannoneering, Deploy Cannon, cannon splash, projectile skins, or a war machine shop.
- Combat-side Cove flavor lives in static-only law profiles (gunpowder/pirate ranged + Focus/reload, Burning Ash dealer), still awaiting runtime proof — not in the faction skill.
- Cannon is a HotA battle machine in the Ballista slot, bought in Cove blacksmith/Cannon Yard for 3000 gold, with level 6, Attack 20, Defense 10, Damage `(4-7) * (hero Attack + 1)`, Health 250, Speed 0, Shots 8, two-hex size, and can fire at fortifications.
- (Removed: Heroic Strike replacement instruction belonged to the abandoned Cannon design.)
- Superseded HotA reference (not the OE design): the Cannon stats above are kept for canon context only. Do not revive the Cannoneering requirement, Cannon-specialist text, or splash-scaling design without re-proven war-machine paths.

## Heroes

- Clone Human or Nature hero scaffolding only after checking which tables best support Captain/Navigator skill rolls.
- Class labels: Captain and Navigator.
- Unit specialists map to Cove unit families.
- (Removed: Cannon-specialist text belonged to the abandoned Cannoneering design.)
- Navigation specialists must not claim water-map bonuses unless those bonuses are implemented.

## Town Art

- Requires HotA Cove town asset extraction, not HoMM3 Complete LOD extraction.
- Shipyard, Frigate, Nix Fort, Maelstrom, and waterline layers need manual placement review.
- HotA Cannon config/sprite/audio payloads are retained for reference only; they gate nothing since Cannoneering was abandoned.

## Asset Deployment

- Core.zip data alone is not enough for visible faction UI, unit portraits, imported unit visuals, town art, Cannon art, audio, or map-object art.
- `tools/deploy_homm3_cove_assets.py` audits the local HotA Cove/Cannon source lane and validates the expected plugin payload paths from `homm3_import.json` gameUnitSids, bundle names, and HotA lab SIDs. It is not a Unity bundle builder; a source audit by itself is not a release deployment.
- The production-ready worktree currently has Cove `homm3_import.json` rows, HotA-named Unity bundles, static unit portraits, preview manifests, hero portraits, faction icon/card art, town backdrop/layers/build-tree icons, city/dwelling map-object reference frames, Cannon config/sprite/audio payloads, and `extracted_battle` lab sidecars. Do not call the plugin payload complete unless `python tools\deploy_homm3_cove_assets.py --plugin-root "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod"` passes.
- Cove registry/Core/basic presentation may be enabled once faction-owned payloads validate through plugin payload validation, release Core generation, runtime registry mirroring, and Steam Core validation. That basic enablement is not release-complete promotion; Accurate Shot, Treasure Hunting skill text/rows, source mechanics, runtime donor-alias behavior, and HotA/VCMI stats/cost sourcing remain explicit user-guided hardening gates (Cannon/Cannoneering removed: abandoned design).
- Cove must use a HotA-capable asset-source lane. HoMM3 Complete LOD extraction is insufficient for Cove town, creature, Cannon, and audio assets.
- Add Cove to the release custom-game/banner/icon sprite registry explicitly when basic presentation is validation-gated and intentional; do not rely on custom Core.zip icon keys to load arbitrary plugin PNGs.

## Tears Of Ashan Alternate Upgrade Targets

Use `docs/homm3_tears_of_ashan_creature_specs.md` as the source for these `_upg_alt` rows. They are not replacements for the HotA base/upgraded rows above. Percentage on-hit effects become guaranteed focus-point abilities in Olden Era while preserving source targets, durations, immunity/resist lists, and effect strength.

| Tier | ToA creature | Target SID | Stats | Cost | Source abilities | OE conversion notes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 alt | Nereid | `h3_nymph_upg_alt` | A5/D3, 1-2 dmg, 6 HP, speed 7, growth 16 | 45 gold | Teleporting; immune to Ice Bolt, Frost Ring, and Freezing Shot; casts Advanced Mirth at 6 power, 2 casts. | Keep the ice immunity list exact; Mirth needs a spell-id and buff-duration trace before implementation. |
| 2 alt | Swashbuckler | `h3_crew_mate_upg_alt` | A7/D7, 2-4 dmg, 18 HP, speed 6, growth 9 | 150 gold | Generates 15 gold per unit per day while in a hero army. | Requires economy/session trace for per-unit daily resource generation. Do not fake this as static town income. |
| 4 alt | Halcyon | `h3_stormbird_upg_alt` | A10/D10, 6-10 dmg, 45 HP, speed 10, growth 4 | 350 gold | Flying; Thunderbolt after attack at 30%, strength 10 per unit. | Convert Thunderbolt to a guaranteed focus-point active attack rider. Preserve target, damage-per-unit scaling, and spell/electric resist rules. |
| 5 alt | Tidecaller | `h3_sea_witch_upg_alt` | A14/D8, 10-14 dmg, 35 HP, speed 8, growth 3, 24 shots | 575 gold | Shooter; always applies Basic Weakness or Basic Disrupting Ray after attack; can cast Summon Fangarms at 50% power, 1 cast. | The 100% after-shot debuffs are deterministic. Preserve the Sea Witch/Sorceress Weakness-then-Disrupting Ray ordering rules unless ToA row explicitly overrides them. Summon Fangarms needs a summon trace. |
| 6 alt | Nix Praetorian | `h3_nix_upg_alt` | A16/D16, 20-24 dmg, 100 HP, speed 8, growth 2 | 1300 gold | Reduces enemy Attack by 30%; Bind after attack at 50%. | Convert Bind to a guaranteed focus-point melee root/bind ability. Enemy Attack reduction belongs in the damage formula, not a generic armor buff. |
| 7 alt | Abyss Serpent | `h3_sea_serpent_upg_alt` | A25/D25, 30-55 dmg, 250 HP, speed 12, growth 1 | 4000 gold, 2 sulfur | Poison after attack at 30%; Curse after attack at 30%; Fearsome 10%; Fearless; King value 0; Skeleton Transformer target. | Convert Poison, Curse, and Fearsome chance effects into guaranteed focus-point abilities. Preserve Poison max-health cap/timing/Cure rules from the HotA Cove table and keep Fearless as deterministic immunity. |

## Static Trace And Design Debts

- HotA source detection and local presentation payload validation are scaffolded in `custom_factions/homm3_cove.json` and `tools/deploy_homm3_cove_assets.py`; basic Core generation/runtime registry presentation is allowed, while Steam plugin deployment verification and mechanics remain open.
- Accurate Shot Guillotine-effect implementation (`space_11_magic_decimate`, `assasinate`), target-stack top-creature health, deterministic focus kill budget, kill cap, wall/war-machine exclusions, and range-penalty multiplier.
- Authentic Ayssid Ferocity kill-trigger sequencing without retaliation-triggered extra attacks.
- Sea Witch/Sorceress after-shot hook, Weakness-state detection, and Disrupting Ray cumulative defense reduction.
- Nix/Nix Warrior enemy-Attack ignore inside OE damage calculation.
- Poisonous max-health/current-health mutation, once-per-round application, Cure removal, immunity list, and 50% cap.
- Haspid Revenge storage of initial stack count, current total health reads, formula rounding, and attack-only timing.
- Cannoneering/Cannon war-machine or Heroic Strike replacement path.
- Gunpowder Warehouse as an extra Sea Dog recruitment prerequisite.
- Shipyard and water-map behavior.
