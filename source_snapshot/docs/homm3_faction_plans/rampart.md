# HoMM3 Rampart Release-Quality Port Plan

Status: faction spec for future manifest generation and implementation audits.

This document is a contract for a Rampart port, not a scaffold for temporary behavior. Donor factions and OE-native mechanics may be used for plumbing, but the resulting creature stats, targeting profile, and special abilities must be checked against the HotA reference below. Any mechanic that cannot yet be represented in data or hooks is a static-trace/design debt.

## Source URLs

Primary creature sources:

- Rampart overview and creature table: https://heroes.thelazy.net/index.php/Rampart
- Tears of Ashan alternate-upgrade source rows: `docs/homm3_tears_of_ashan_creature_specs.md` (canonical for `_upg_alt` stats; this plan's alt rows are mined from it)
- Centaur and Centaur Captain: https://heroes.thelazy.net/index.php/Centaur_Captain
- Dwarf and Battle Dwarf: https://heroes.thelazy.net/index.php/Dwarf_and_Battle_Dwarf
- Wood Elf and Grand Elf: https://heroes.thelazy.net/index.php/Wood_and_grand_elf
- Pegasus and Silver Pegasus: https://heroes.thelazy.net/index.php/Pegasus
- Dendroid Guard and Dendroid Soldier: https://heroes.thelazy.net/index.php/Dendroid_Guard_and_Dendroid_Soldier
- Unicorn and War Unicorn: https://heroes.thelazy.net/index.php/Unicorn_and_War_Unicorn
- Green Dragon and Gold Dragon: https://heroes.thelazy.net/index.php/Green_Dragon_and_Gold_Dragon

Ability/detail sources:

- Spell points and Pegasus magic damper relation: https://heroes.thelazy.net/index.php/Spell_Point
- Breath attack behavior: https://heroes.thelazy.net/index.php/Breath_attack

## Faction Defaults

| Field | Requirement |
| --- | --- |
| Faction SID | `homm3_rampart` |
| City SID | `homm3_rampart_city` |
| Primary donor faction | `nature` |
| Primary donor city | `nature_city` |
| HoMM3 classes | Ranger, Druid |
| OE class labels | Ranger, Druid |
| Native terrain | Grass |
| Mage Guild cap | Level 5 |
| Release risk | Medium/high until resistance, bind, blind, aura, dragon immunity, breath attack, Treasury, and Mystic Pond are represented or explicitly blocked. |

Identity pillars:

- resilient woodland army
- luck, resistance, and anti-magic pressure
- one precise low-tier shooter line protected by durable bodies
- fast Pegasus/dragon tempo with slow Dwarf/Dendroid anchors
- defensive economy through Treasury and growth buildings

## HotA Unit Stats And Abilities

All rows are HotA/RoE Rampart creature definitions. `Growth` includes parenthetical horde-building increments when the relevant Rampart horde building exists.

| Tier | Unit | Target SID | Atk | Def | Dmg | HP | Spd | Move | Size | Growth | Shots | AI Value | Cost | HotA abilities |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | --- | ---: | ---: | --- | --- |
| 1 | Centaur | `h3_centaur` | 5 | 3 | 2-3 | 8 | 6 | Ground | 2 | 14 | - | 100 | 70 gold | None. Melee two-hex ground unit. |
| 1+ | Centaur Captain | `h3_centaur_captain` | 6 | 3 | 2-3 | 10 | 8 | Ground | 2 | 14 | - | 138 | 90 gold | None. Melee two-hex ground unit. |
| 2 | Dwarf | `h3_dwarf` | 6 | 7 | 2-4 | 20 | 3 | Ground | 1 | 8 (+4) | - | 138 | 120 gold | 20% chance to resist hostile spell effects. |
| 2+ | Battle Dwarf | `h3_battle_dwarf` | 7 | 7 | 2-4 | 20 | 5 | Ground | 1 | 8 (+4) | - | 209 | 150 gold | 40% chance to resist hostile spell effects. |
| 3 | Wood Elf | `h3_wood_elf` | 9 | 5 | 3-5 | 15 | 6 | Ground | 1 | 7 | 24 | 234 | 200 gold | Shooter. |
| 3+ | Grand Elf | `h3_grand_elf` | 9 | 5 | 3-5 x2 | 15 | 7 | Ground | 1 | 7 | 24 | 331 | 225 gold | Shooter; shoots twice per ranged attack. |
| 4 | Pegasus | `h3_pegasus` | 9 | 8 | 5-9 | 30 | 8 | Flying | 2 | 5 | - | 518 | 250 gold | Flying; Magic Damper: enemy hero spells cost 2 extra spell points if Pegasi were present at combat start. Effect persists for the battle even if the Pegasi die. |
| 4+ | Silver Pegasus | `h3_silver_pegasus` | 9 | 10 | 5-9 | 30 | 12 | Flying | 2 | 5 | - | 532 | 275 gold | Flying; same Magic Damper definition as Pegasus. |
| 5 | Dendroid Guard | `h3_dendroid_guard` | 9 | 12 | 10-14 | 55 | 3 | Ground | 1 | 3 (+2) | - | 517 | 350 gold | Binding: attacks bind the target stack to the ground until the Dendroid stack moves or dies; Dispel or Teleport can remove the effect; Anti-Magic does not prevent binding. |
| 5+ | Dendroid Soldier | `h3_dendroid_soldier` | 9 | 12 | 10-14 | 65 | 4 | Ground | 1 | 3 (+2) | - | 803 | 425 gold | Same Binding definition as Dendroid Guard. |
| 6 | Unicorn | `h3_unicorn` | 15 | 14 | 18-22 | 90 | 7 | Ground | 2 | 2 | - | 1806 | 850 gold | Blinding Attack: 20% chance to blind target for 3 rounds at Advanced Blind strength. Aura of Magic Resistance: adjacent friendly units, not the Unicorn itself, gain 20% chance to resist hostile magic; multiple Unicorn auras do not stack. |
| 6+ | War Unicorn | `h3_war_unicorn` | 15 | 14 | 18-22 | 110 | 9 | Ground | 2 | 2 | - | 2030 | 950 gold | Same Blinding Attack and Aura of Magic Resistance definitions as Unicorn. |
| 7 | Green Dragon | `h3_green_dragon` | 18 | 18 | 40-50 | 180 | 10 | Flying | 2 | 1 | - | 4872 | 2400 gold + 1 gem | Dragon; flying; breath attack; immune to spell levels 1-3. Affected by Dispel and can take Fire Shield damage after attacking. |
| 7+ | Gold Dragon | `h3_gold_dragon` | 27 | 27 | 40-50 | 250 | 16 | Flying | 2 | 1 | - | 8613 | 4000 gold + 2 gems | Dragon; flying; breath attack; immune to spell levels 1-4. Affected by Dispel and can take Fire Shield damage after attacking. |

Breath attack requirement: when a Green or Gold Dragon attacks from a primary hex side, the attack also damages the hex directly behind the target in the attack direction. The second hex can contain an allied stack, and damage to each affected stack is calculated separately. Two-hex units must not receive double damage from one breath attack.

## Unit Behavior Expectations

| Line | Required behavior | Implementation debt if unsupported |
| --- | --- | --- |
| Centaur | Fast, two-hex melee ground opener. No ranged attack, no special retaliation rule, no hidden ability. | Static trace OE two-hex cavalry/spear donor behavior only for footprint and animation safety. |
| Dwarf | One-hex slow durable melee with exact 20% hostile-spell resistance. Battle Dwarf upgrades attack and speed, with exact 40% resistance. | Find or hook a unit/stack spell-resist gate. If unavailable, mark resistance unimplemented in generated audit output instead of replacing it with defense. |
| Wood Elf | One-hex shooter with 24 shots. | Verify native ranged ammunition fields and range penalty behavior. |
| Grand Elf | One-hex shooter with 24 shots and two ranged attacks per attack action. Both shots must consume/observe the correct attack, ammo, target, retaliation, and combat-log semantics. | Static trace native multi-shot support. If no safe native path exists, implement a battle hook; do not collapse it into a generic focus attack in the spec. |
| Pegasus | Two-hex flyer. Magic Damper applies +2 enemy spell point cost if any Pegasus/Silver Pegasus stack was present at combat start, and remains for the battle after that stack dies. | Static trace hero spell-cost calculation and battle-start stack scan. |
| Dendroid | One-hex ground melee. Binding applies on attack and prevents movement until the Dendroid stack moves or dies; Dispel/Teleport remove it; Anti-Magic does not block it. | Static trace movement validators, status storage, Dispel/Teleport cleanup, and Dendroid-stack lifecycle cleanup. |
| Unicorn | Two-hex ground melee. Source Blinding Attack is 20% chance for 3 rounds at Advanced Blind strength; in Olden Era this must be exposed as a guaranteed focus-point-costing active ability that applies the same Blind target/effect strength, not as a hidden random on-hit passive. Aura affects adjacent friendly units only, grants 20% hostile-magic resistance, does not affect the Unicorn itself, and does not stack. | Static trace Blind spell/status application, deterministic focus ability execution, adjacent aura evaluation, and non-stacking resistance. |
| Dragon | Two-hex flyer with dragon classification, breath attack, and spell-level immunity. Green Dragon ignores levels 1-3; Gold Dragon ignores levels 1-4. | Static trace spell immunity checks by spell level, breath targeting/friendly-fire rules, Dispel exception, and Fire Shield post-attack damage. |

## City And Economy

| HoMM3 element | Requirement | Implementation debt if unsupported |
| --- | --- | --- |
| Mystic Pond | Produces 1-4 of a random non-gold resource at the start of each week. | Static trace weekly economy ticks and random-resource grant hooks. |
| Fountain of Fortune | Gives a garrisoned hero +2 Luck while defending in siege combat. | Static trace siege/garrison hero combat modifiers. |
| Treasury | Produces 10% of the player's gold, based on gold owned at the end of the prior week, at the start of each week. Multiple Treasuries are cumulative. | Static trace weekly income ordering and player-wide owned-town iteration. |
| Miners' Guild | +4 Dwarf and Battle Dwarf growth per week. | Data-only growth bonus if `cityUnitsIncrement` supports multiple receiver SIDs. |
| Dendroid Saplings | +2 Dendroid Guard and Dendroid Soldier growth per week. | Data-only growth bonus if `cityUnitsIncrement` supports multiple receiver SIDs. |
| Resource Silo | Rampart resource silo income should match the HotA town economy expectation once the project's faction-economy model is chosen. | Verify exact resource output from HotA data before manifest generation. |
| Mage Guild | Level 5. | Exact. |

Economy note: Rampart should preserve its defensive gold stability and wood/ore/green-resource pressure. Gold Dragon cost and prerequisite pressure should remain meaningful.

## Laws And Faction Skill

Faction skill proposal: `Harmony`.

Design target: Harmony should express Rampart creatures protecting and amplifying each other, not a Grass/native-terrain identity. Prefer explicit army luck, spell-resistance, and creature-line synergy over terrain traversal or terrain-conditioned stats.

Acceptance requirements before implementation:

- The skill must have a concrete rules table with rank-by-rank numeric effects.
- It must not reuse donor subskills unless those subskills are renamed, de-duplicated, localized, and behaviorally appropriate.
- If it grants luck, resistance, creature-line bonuses, or growth, the affected SIDs and formulas must be explicit.
- If it interacts with Dwarf/Unicorn resistance, the stack-resistance composition rules must be specified before implementation.
- Do not make Harmony revolve around native terrain. Terrain text is acceptable only as world flavor, not as the mechanical center of the skill.

Target rank structure:

| Rank | Harmony target behavior | Implementation cautions |
| --- | --- | --- |
| Basic | Rampart army gains +1 Luck. Dwarf-line units gain a small explicit hostile-spell resistance bonus if the resistance path is traced. | Use explicit `h3_dwarf`, `h3_dwarf_upg`, and `h3_dwarf_upg_alt` receivers; do not silently stack past the source Dwarf/Battle Dwarf resistance rules. |
| Advanced | Basic effects, plus Unicorn-line units project or strengthen a non-stacking adjacent friendly resistance aura. | Reuse the traced Unicorn aura path only after adjacency, self-exclusion, and non-stacking behavior are verified. |
| Expert | Advanced effects, plus Dragon-line units gain a small explicit defensive or spell-immunity-synergy bonus that does not alter their source spell-level immunity. | Receiver SIDs must be `h3_green_dragon`, `h3_gold_dragon`, and `h3_diamond_dragon_upg_alt` where present; do not broaden this to all flyers or all Nature donor units. |

Law themes to formalize:

- Centaur outriders: speed/initiative for `h3_centaur*`.
- Dwarven resolve: HP/defense and/or exact magic-resistance support if the engine path exists.
- Elven volleys: ranged damage or ammo/range support for `h3_wood_elf` and `h3_grand_elf`.
- Pegasus winds: battle-start enemy spell-cost pressure only if tied to the real Magic Damper path.
- Unicorn blessing: luck or resistance aura support with explicit adjacency/scope rules.
- Dragon groves: high-tier growth, defense, or spell-immunity synergy with exact receiver SIDs.

## Heroes

- Clone Nature hero/subclass scaffolding only as a technical base.
- Class labels: Ranger and Druid.
- Unit specialists must map to exact Rampart SIDs: `h3_centaur*`, `h3_dwarf*`, `h3_wood_elf*`, `h3_pegasus*`, `h3_dendroid*`, `h3_unicorn*`, and `h3_green_dragon*`/`h3_gold_dragon`.
- Resistance, Archery, Luck, Logistics, Armorer, Diplomacy, and economy specialties translate only after the target OE secondary-skill or bonus IDs are verified.
- Specialty text must not claim HoMM3 scaling until matching bonuses are implemented and audited.

## Town Art

- Rampart town has dense tree/building occlusion. Generate layers, then manually verify ordering and placement against the HoMM3 town scene.
- Dendroid and dragon dwelling layers likely need independent upgrade positions.
- Treasury/Mystic Pond behavior must be solved through economy hooks/data, not through building layer names.

## Asset Deployment

- The source plugin already has Rampart unit import rows, custom unit bundles, static unit portraits, preview manifests, lab sidecars, faction icon/card art, and city/dwelling map-object reference frames. Do not keep stale "no bundles/import payload" release blocks unless validation regresses.
- Rampart release hardening still needs `homm3_hero_portraits/`, town layers, build-tree icons, release UI registry/selector exposure, and mechanics validation. Core.zip data alone is still not enough for visible faction UI or release readiness.
- Verify the actual HoMM3 Rampart town backdrop source and building-layer source by eye. Do not use hall/build-tree UI plates or donor Nature assets as the faction card/backdrop.
- Add Rampart to the release custom-game/banner/icon sprite registry explicitly; do not rely on custom Core.zip icon keys to load arbitrary plugin PNGs.

## Tears Of Ashan Alternate Upgrades

`_upg_alt` rows should use the mined Tears of Ashan data below where present. These rows are alternate upgrades beside the normal HotA upgraded units, not replacements for the base/upgraded HotA stats above.

Do not invent shortcut alternate upgrades for Rampart. If a source ability is hard to express in data, keep the exact target behavior here and carry it as static-trace/design debt. Probability-based on-hit effects from HoMM3, HotA, or ToA must become guaranteed Olden Era focus-point-costing active abilities, preserving the source target and effect strength as closely as practical.

| Tier | ToA unit | Target SID | Atk | Def | Dmg | HP | Spd | Move | Size | Growth | Shots | Cost | ToA source abilities | Olden Era port requirement |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- | --- |
| 1 alt | Centaur Ranger | `h3_centaur_ranger_upg_alt` | 5 | 3 | 2-3 | 8 | 7 | Ground | 2 | 14 | 12 | 90 gold | Shooter. Upgrades from Centaur Captain line in ToA data. | Two-hex ranged unit with 12 shots. Preserve Centaur footprint; verify ranged two-hex targeting and melee fallback instead of downgrading to a normal one-hex archer. |
| 2 alt | Dwarf Battlerager | `h3_dwarf_battlerager_upg_alt` | 6 | 8 | 3-5 | 20 | 5 | Ground | 1 | 8 | - | 150 gold | Can cast Advanced Bloodlust on self without skipping a turn; 3 Power; 2 casts. | Implement as self-target friendly buff ability with 2 charges and no turn skip if OE supports it. If no safe no-turn-skip path exists, document the missing execution model; do not replace it with passive Attack. |
| 3 alt | Elf Wardancer | `h3_elf_wardancer_upg_alt` | 9 | 7 | 3-5 | 20 | 9 | Ground | 1 | 7 | - | 225 gold | Additional Attack +1. | Melee unit that attacks twice per attack action. Preserve target/retaliation/combat-log semantics; do not model it as a raw damage multiplier. |
| 4 alt | Gold Pegasus | `h3_gold_pegasus_upg_alt` | 12 | 8 | 5-9 | 30 | 12 | Flying | 2 | 5 | - | 350 gold | Flying; blocks retaliation. | Two-hex flyer with no-retaliation attacks. This is separate from HotA Pegasus/Silver Pegasus Magic Damper and must not erase the baseline damper requirement for those units. |
| 5 alt | Dendroid Shaman | `h3_dendroid_shaman_upg_alt` | 9 | 15 | 10-14 | 65 | 4 | Ground | 1 | 3 | - | 550 gold | Binding on attack; can cast Expert Resurrection on Rampart units at 30% Power; 2 casts. | Preserve Binding. Add a resurrection ability limited to friendly Rampart units, 30% Power, 2 casts. If faction-limited target filters are unavailable, keep this as design debt rather than allowing all factions. |
| 6 alt | Pristine Unicorn | `h3_pristine_unicorn_upg_alt` | 15 | 18 | 18-22 | 110 | 9 | Ground | 2 | 2 | - | 1050 gold | Spell Resistance Aura 50%; 20% Blind after attack. | Aura grants adjacent friendly units 50% hostile-magic resistance, non-stacking and not self-applied unless static tracing proves ToA semantics differ. Convert the 20% on-hit Blind into a guaranteed FP-costing active ability that applies Blind to the chosen attack target with the source effect strength; do not ship it as a random passive. |
| 7 alt | Diamond Dragon | `h3_diamond_dragon_upg_alt` | 32 | 22 | 40-50 | 225 | 16 | Flying | 2 | 1 | - | 4000 gold + 2 crystal | Dragon; flying; breath attack; spell immunity through level 3; skeleton transformer target Bone Dragon; KING additive value 0. | Two-hex dragon flyer with breath attack and level 1-3 spell immunity. Keep Diamond Dragon immunity at ToA level 3 even though Gold Dragon remains HotA level 4 immunity. |

## Static Trace Debts

- Dwarf/Battle Dwarf hostile-spell resistance implementation path.
- Unicorn adjacent aura resistance path and interaction with Dwarf resistance.
- Unicorn/Pristine Unicorn Blind as a deterministic focus-point active that applies Advanced-strength Blind for the source duration/effect, replacing the source random on-hit proc.
- Pegasus Magic Damper battle-start detection and spell-point-cost calculation.
- Dendroid Binding status, movement validator, cleanup, and Dispel/Teleport removal.
- Dragon breath attack targeting, friendly-fire, and per-stack damage calculation.
- Dragon spell-level immunity with Dispel and Fire Shield exceptions.
- Treasury weekly 10% cumulative gold interest.
- Mystic Pond weekly random non-gold resource output.
- Fountain of Fortune siege-only +2 Luck for the garrisoned defending hero.

## Release Audit Checklist

- Every unit row in generated Rampart data matches the HotA stats table.
- No base Rampart creature receives an upgraded-only ability.
- No upgraded Rampart creature loses a base ability that should carry forward.
- Ranged units have exact shot counts and ranged/melee behavior.
- Two-hex creature footprints are correct for Centaurs, Pegasi, Unicorns, and Dragons.
- All implemented special abilities have either a data source, a static-traced hook, or an explicit missing-mechanic audit entry.
- No percentage-based on-hit proc ships as a hidden random passive; these are represented as guaranteed FP-costing active abilities.
- Localization names/descriptions state implemented behavior only.
- Donor faction IDs, subskills, laws, and unit abilities are removed or renamed before release manifest generation.
