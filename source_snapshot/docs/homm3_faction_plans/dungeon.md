# HoMM3 Dungeon Release Port Spec

Status: release-quality specification draft for future manifest generation and implementation audit.

This document is an acceptance target, not a shortcut plan. Where HoMM3/Horn of the Abyss behavior does not map cleanly to Olden Era data, the row is marked as static-trace or design debt until the exact native implementation path is found.

## Source URLs

- Dungeon overview and creature table: https://heroes.thelazy.net/index.php/Dungeon
- Troglodyte and Infernal Troglodyte: https://heroes.thelazy.net/index.php/Troglodyte_and_Infernal_Troglodyte
- Harpy and Harpy Hag: https://heroes.thelazy.net/index.php/Harpy_and_Harpy_Hag
- Beholder and Evil Eye: https://heroes.thelazy.net/index.php/Beholder_and_Evil_Eye
- Medusa and Medusa Queen: https://heroes.thelazy.net/index.php/Medusa_and_Medusa_Queen
- Minotaur and Minotaur King: https://heroes.thelazy.net/index.php/Minotaur_and_Minotaur_King
- Manticore and Scorpicore: https://heroes.thelazy.net/index.php/Manticore_and_Scorpicore
- Red Dragon and Black Dragon: https://heroes.thelazy.net/index.php/Red_Dragon_and_Black_Dragon
- Hate ability details: https://heroes.thelazy.net/index.php/Hate

## Faction Defaults

| Field | Requirement |
| --- | --- |
| Faction SID | `homm3_dungeon` |
| City SID | `homm3_dungeon_city` |
| Primary donor faction | `dungeon` |
| Primary donor city | `dungeon_city` |
| HoMM3 classes | Overlord, Warlock |
| OE class labels | Overlord, Warlock |
| Native terrain | Subterranean |
| Mage Guild cap | Level 5 |
| Resource pressure | Sulfur-heavy economy for Dragon Cave, Black Dragons, and magic infrastructure. |
| Risk | Medium-high; Harpy return choice, Medusa Stone Gaze, Scorpicore Paralyzing Venom, dragon breath, dragon immunities, and Dungeon-native faction skill filters require trace/design work. |

Identity pillars:

- subterranean monsters and warlocks
- high damage and control
- strong magic economy
- black dragon late-game identity

Naming warning: do not use `dungeon` or `dungeon_raw` as the custom faction SID. Use `homm3_dungeon` to avoid colliding with OE Dungeon.

## HotA Unit Stats And Abilities

Use these HotA rows as the canonical stat and rules target for the Dungeon port. `Shots` is blank for melee-only units. Dragon costs include sulfur.

| Tier | Creature | Target SID | Atk | Def | Dmg | HP | Spd | Move | Size | Growth | Shots | AI Value | Fight Value | Cost | HotA ability requirements |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | Troglodyte | `h3_troglodyte` | 4 | 3 | 1-3 | 5 | 4 | Ground | 1 | 14 (+7 with Mushroom Rings) |  | 59 | 73 | 50 gold | Immune to Blind and Stone Gaze. This does not include Scorpicore paralysis immunity. |
| 1+ | Infernal Troglodyte | `h3_infernal_troglodyte` | 5 | 4 | 1-3 | 6 | 5 | Ground | 1 | 14 (+7 with Mushroom Rings) |  | 84 | 84 | 65 gold | Immune to Blind and Stone Gaze. This does not include Scorpicore paralysis immunity. |
| 2 | Harpy | `h3_harpy` | 6 | 5 | 1-4 | 14 | 6 | Flying | 1 | 8 |  | 154 | 140 | 130 gold | Flying. Strike and return: flies to the target, attacks, receives normal retaliation when applicable, then returns to the starting hex. In HotA, the player can choose not to return. |
| 2+ | Harpy Hag | `h3_harpy_hag` | 6 | 6 | 1-4 | 14 | 9 | Flying | 1 | 8 |  | 238 | 196 | 170 gold | Flying. Strike and return. No enemy retaliation from its attack. In HotA, the player can choose not to return. |
| 3 | Beholder | `h3_beholder` | 9 | 7 | 3-5 | 22 | 5 | Ground | 1 | 7 | 12 | 336 | 240 | 250 gold | Shooter. No melee penalty. Melee attack deals the same damage as ranged attack. |
| 3+ | Evil Eye | `h3_evil_eye` | 10 | 8 | 3-5 | 22 | 7 | Ground | 1 | 7 | 24 | 367 | 245 | 280 gold | Shooter. No melee penalty. Melee attack deals the same damage as ranged attack. |
| 4 | Medusa | `h3_medusa` | 9 | 9 | 6-8 | 25 | 5 | Ground | 2 | 4 | 4 | 517 | 379 | 300 gold | Shooter. No melee penalty. Melee Stone Gaze: 20% chance to petrify the target for 3 rounds after hand-to-hand attack. Petrified creatures cannot move, take 50% damage, and the effect is removed when attacked. |
| 4+ | Medusa Queen | `h3_medusa_queen` | 10 | 10 | 6-8 | 30 | 6 | Ground | 2 | 4 | 8 | 577 | 423 | 330 gold | Shooter. No melee penalty. Same melee Stone Gaze rules as Medusa. |
| 5 | Minotaur | `h3_minotaur` | 14 | 12 | 12-20 | 50 | 6 | Ground | 1 | 3 |  | 835 | 835 | 500 gold | Minimum Morale is +1. This minimum is not lowered by Sorrow, mixed-army morale penalties, Bone/Ghost Dragon morale effects, morale map objects, or HotA anti-morale artifacts; it can still be affected by Cursed Ground and Spirit of Oppression because those interact with the morale roll. |
| 5+ | Minotaur King | `h3_minotaur_king` | 15 | 15 | 12-20 | 50 | 8 | Ground | 1 | 3 |  | 1068 | 890 | 575 gold | Same Minimum Morale +1 rules as Minotaur. |
| 6 | Manticore | `h3_manticore` | 15 | 13 | 14-20 | 80 | 7 | Flying | 2 | 2 |  | 1547 | 1215 | 850 gold | Flying. No paralysis on the base creature. |
| 6+ | Scorpicore | `h3_scorpicore` | 16 | 14 | 14-20 | 80 | 11 | Flying | 2 | 2 |  | 1685 | 1248 | 1050 gold | Flying. Paralyzing Venom: surviving target has 20% chance to be paralyzed immediately after the Scorpicore attack. Paralyzed creatures forgo turns for the remainder of the current round and two following rounds unless attacked; they take full damage but retaliate at one-quarter strength. Cure and Dispel remove it. War Machines, Gold Dragons, Black Dragons, and Magic Elementals resist it. |
| 7 | Red Dragon | `h3_red_dragon` | 19 | 19 | 40-50 | 180 | 11 | Flying | 2 | 1 |  | 5003 | 3762 | 2500 gold, 1 sulfur | Dragon. Flying. Breath attack hits the target hex and the hex directly behind it, including allied stacks if positioned there. Immune to spells level 1-3. |
| 7+ | Black Dragon | `h3_black_dragon` | 25 | 25 | 40-50 | 300 | 15 | Flying | 2 | 1 |  | 8721 | 6783 | 4000 gold, 2 sulfur | Dragon. Flying. Breath attack. Immune to spells level 1-5. Hates Titans: deals +50% damage to Titans, including breath splash when Titans are behind the attacked stack. Red Dragons and Giants do not participate in this hate pair. |

## Unit Implementation Requirements

| Tier | Line | Donor starting point | Required behavior | Static-trace/design debt |
| --- | --- | --- | --- | --- |
| 1 | Troglodyte -> Infernal Troglodyte | `trogl` | Melee one-hex Dungeon infantry with exact stats and Blind/Stone Gaze immunity. | Identify Olden Era buff/immunity keys for Blind and petrification; verify Scorpicore paralysis stays separate. |
| 2 | Harpy -> Harpy Hag | `assassin` or any native return-attacker shell | Flying, one-hex strike-and-return unit. Harpy receives legal retaliation before returning; Harpy Hag prevents retaliation. HotA return-choice must be represented if Olden Era has a native action-choice path. | Trace whether any native ability supports post-attack return and optional non-return. If no data path exists, implement a custom command/ability rather than changing the spec. |
| 3 | Beholder -> Evil Eye | `medusa` or `lightweaver` shooter shell | One-hex shooter with 12/24 shots, no melee penalty, and matching ray/projectile presentation. | Verify Olden Era shooter ammo and no-melee-penalty fields. |
| 4 | Medusa -> Medusa Queen | `medusa` | Two-hex shooter with 4/8 shots, no melee penalty, and melee-only Stone Gaze. | Source Stone Gaze is chance-on-melee-hit; OE target is a guaranteed focus-point melee petrify ability with the same legal target, duration, damage-reduction, removal, and immunity rules. |
| 5 | Minotaur -> Minotaur King | `minos` | One-hex bruiser with exact stats and Minimum Morale +1. | Trace morale-floor semantics; do not replace with a generic morale buff unless it preserves the HotA exceptions. |
| 6 | Manticore -> Scorpicore | flyer shell, not Hydra movement | Two-hex flying bruiser. Base Manticore has no paralysis. Scorpicore source Paralyzing Venom has HotA duration, removal, retaliation, and resist rules. | OE target is a guaranteed focus-point melee disable ability; retaliation-strength modifiers and the full resist list must be represented or consciously deferred as debt. |
| 7 | Red Dragon -> Black Dragon | `black_dragon` | Two-hex flying dragon with exact breath line, spell immunity tiers, and Black Dragon Titan hate. | Trace breath splash ownership/friendly-fire, spell-level immunity filters, resurrection/beneficial-spell consequences, and hate damage hook. |

## City And Economy

| HoMM3 element | Requirement | Static-trace/design debt |
| --- | --- | --- |
| Mana Vortex | Dungeon town special that doubles the visiting hero's current spell points once per week in HoMM3. | Trace whether Olden Era town visit actions can mutate current mana and store weekly visit state. |
| Portal of Summoning | Dungeon special dwelling that adds weekly recruitment from an external flagged dwelling owned by the player. | Trace RMG/session ownership and external-dwelling recruitment APIs before implementing. |
| Battle Scholar Academy | Visiting hero can gain a one-time primary-stat bonus in HoMM3. | Trace one-time visit rewards and hero primary stat mutation. |
| Artifact Merchants | Use real artifact merchant behavior if the donor city supports it. | Verify shop category, unlock state, and city UI compatibility. |
| Resource Silo | Sulfur daily income. | Verify resource income row can target sulfur. |
| Mage Guild | Level 5. | Exact. |

Economy note: keep Dungeon rare-resource pressure high for dragons and magic buildings.

## Laws And Faction Skill

Current implementation (2026-10-12): the faction skill is **Captives** (replaced Draconic Dominion). Let fleeing squads go to bank their strength; tiers at 2,000/6,000/12,000/22,000/36,000 give +1..+5 Attack/Defense; Execute (55/82.5/110 XP per 1,000) and Ransom (200/300/400 Gold per 1,000) spend the captives. Subskills: Underworld Tribute, Interrogation, Imperial Menagerie, Terror Mandate, Slave Markets, Dungeon Cells. Runtime owner: `Homm3DungeonCaptivesRuntime.cs`; Core rows: Dungeon sections of `tools/release_port/apply_release_core_overlay.py`. The Triumvirate's Strength notes below are the original planning target and are superseded.

Faction skill target: a HoMM3 Dungeon `Triumvirate's Strength` clone (`skill_faction_homm3_dungeon`) unless native `skill_faction_dungeon` can be reused without carrying over Dungeon-terrain assumptions.

Requirements:

- Reusing native Dungeon's stance skill is allowed only after filters are proven to apply correctly to `homm3_dungeon` units and heroes.
- Native behavior grants once-per-round Minotaur/Dark Elf/Dragon stance buttons for Attack, Defense, or Spell Power, with rank scaling and Dungeon subskills.
- Do not reuse the native-terrain damage subskill for HoMM3 Dungeon. Replace it with an explicit creature-cadre bonus: Attack stance should favor Minotaur-line offense, Defense stance should favor Troglodyte/Medusa/Manticore-line durability, and Spell Power stance should favor Beholder/Evil Eye and Dragon-line magical pressure or damage. Exact receiver SIDs and values must be written before implementation.
- If native filters are hard-coded to OE Dungeon, build a custom `homm3_dungeon` skill row and subskill graph instead of cloning broken references.
- Mana Vortex and Portal of Summoning must not be described as faction-skill behavior unless implemented separately.

Law theme candidates remain design input, not implementation acceptance:

- Troglodyte warrens: T1 growth.
- Harpy nests: initiative/speed.
- Eye tyrants: ranged damage or enemy debuff if data-backed.
- Minotaur pride: morale/offense.
- Triumvirate stances: hero Attack, Defense, or Spell Power support, plus non-terrain creature-cadre bonuses for Minotaurs, cave monsters, eye tyrants, and dragons.
- Dragon caves: high-tier damage/cost.

## Heroes

- Clone Dungeon hero/subclass scaffolding but rename classes to Overlord and Warlock.
- Unit specialists map to H3 unit families and must use the exact unit SID families above.
- Spell power and mana specialists can translate to OE magic stats when the target stat key is confirmed.
- Portal, summoning, dragon immunity, and Mana Vortex specialists require static trace/design review before claims are made in text or data.

## Town Art

- Dungeon town can reuse some donor city assumptions, but H3 Dungeon art needs a separate layer map.
- Avoid using OE Dungeon labels to hide H3 building identity.
- Dragon Cave, Portal of Summoning, Mana Vortex, Battle Scholar Academy, and Artifact Merchants layers require visual and behavior review.

## Asset Deployment

- The source plugin already has HoMM3 Dungeon unit import rows, custom unit bundles, static unit portraits, preview manifests, lab sidecars, faction icon/card art, and city/dwelling map-object reference frames. Do not keep stale "no bundles/import payload" release blocks unless validation regresses.
- HoMM3 Dungeon registry/Core/basic presentation may be enabled once faction-owned payloads validate through Core/plugin gates, but release hardening still needs town layers, build-tree icons, source-exact SID/schema cleanup, mechanics validation, and HoMM3/VCMI stats/cost sourcing instead of donor rows. Core.zip data alone is still not enough for production readiness.
- Verify the actual HoMM3 Dungeon town backdrop and building-layer sources by eye. Do not use Olden Era Dungeon assets as a substitute for the HoMM3 faction card/backdrop.
- Add `homm3_dungeon` to the release custom-game/banner/icon sprite registry explicitly when basic presentation is validation-gated and intentional, and keep it separate from native `dungeon`; do not rely on custom Core.zip icon keys to load arbitrary plugin PNGs.

## Tears Of Ashan Alternate Upgrade Targets

Use `docs/homm3_tears_of_ashan_creature_specs.md` as the source for these `_upg_alt` rows. They are not replacements for the HotA base/upgraded rows above. Percentage on-hit effects become guaranteed focus-point abilities in Olden Era while preserving source targets, durations, immunity/resist lists, and effect strength.

| Tier | ToA creature | Target SID | Stats | Cost | Source abilities | OE conversion notes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 alt | Chthonian | `h3_troglodyte_upg_alt` | A6/D3, 2-3 dmg, 5 HP, speed 5, growth 14 | 75 gold | Blind immunity, Stone Gaze immunity, teleporting movement. | Keep the immunity list exact; teleporting movement is an alternate mobility identity, not a reason to remove Infernal Troglodyte's base immunity contract. |
| 2 alt | Fury | `h3_harpy_upg_alt` | A8/D5, 1-4 dmg, 15 HP, speed 7, growth 8 | 170 gold | Flying, strike-and-return, additional attack. | Additional attack is deterministic. Preserve the Harpy Hag return/no-retaliation distinction separately. |
| 3 alt | Fargazer | `h3_beholder_upg_alt` | A9/D9, 4-6 dmg, 25 HP, speed 8, growth 7, 24 shots | 300 gold | Shooter, no melee penalty, no wall penalty, Visions for monsters/heroes/towns. | Visions is an adventure-map information ability and needs a map/session trace before implementation. |
| 4 alt | Medusa Warrior | `h3_medusa_upg_alt` | A12/D12, 6-12 dmg, 35 HP, speed 8, growth 4 | 360 gold | Stone Gaze after attack at 40%. | Convert to a guaranteed focus-point melee petrify ability rather than an RNG passive. Preserve petrify duration, damage-reduction, removal, and immunity rules from the Medusa source behavior. |
| 5 alt | Minotaur Taskmaster | `h3_minotaur_upg_alt` | A15/D15, 12-20 dmg, 65 HP, speed 9, growth 3 | 700 gold | Minimum Morale +1; raises allied morale by +1. | Morale floor and morale aura are separate effects. Do not flatten the morale floor into a generic buff. |
| 6 alt | Chimera | `h3_manticore_upg_alt` | A20/D13, 15-20 dmg, 90 HP, speed 9, growth 2 | 1250 gold | Flying, three-headed attack, Paralyze after attack at 15%. | Convert Paralyze to a guaranteed focus-point melee disable ability. Preserve Scorpicore paralysis duration, removal, retaliation penalty, and resist list. |
| 7 alt | Shadow Dragon | `h3_red_dragon_upg_alt` | A28/D22, 40-50 dmg, 270 HP, speed 16, growth 1 | 4000 gold, 2 sulfur | Dragon, flying, breath attack, Acid Breath after attack, 25% Acid Breath chance/30 value, level 4 spell immunity, hates Giants/Titans/Colossi, Skeleton Transformer target. | Convert Acid Breath chance to a guaranteed focus-point attack rider. Spell immunity is level 1-4, distinct from Black Dragon's level 1-5 immunity. Hate remains a deterministic damage modifier. |

## Unique Faction Mechanics

- `Triumvirate's Strength`: reuse the vanilla Dungeon faction skill path only if native filters, subskills, localization, and UI all bind to `homm3_dungeon`; otherwise clone it under unique HoMM3 Dungeon IDs.
- Compatibility warning: HoMM3 Dungeon keeps custom faction SID `homm3_dungeon`; verify native Dungeon subskills and creature/faction filters before relying on stance or Dungeon-creature bonuses.
- Remove or replace the native-terrain damage subskill in any HoMM3 Dungeon clone. A flavorful target is a stance-linked creature-cadre bonus with explicit receivers rather than a Subterranean terrain condition.
- Medusa and Scorpicore probability effects are exact source behavior requirements, but the Olden Era port should expose them as guaranteed focus-point abilities rather than hidden RNG passives.
- HoMM3 Dungeon must use `homm3_dungeon` as custom SID; do not collide with OE `dungeon` or `dungeon_raw`.

## Static Trace Debts

- Harpy and Harpy Hag strike-return command, including HotA optional non-return.
- Medusa and Medusa Queen melee-only 20% Stone Gaze, 3-round petrification, 50% incoming-damage rule, and attack-removal rule.
- Scorpicore 20% Paralyzing Venom, duration, removal, retaliation quartering, and resist list.
- Black Dragon and Red Dragon breath line targeting, friendly-fire behavior, and animation/projectile presentation.
- Red Dragon level 1-3 spell immunity and Black Dragon level 1-5 spell immunity, including beneficial spell/resurrection consequences.
- Black Dragon +50% damage hate against Titans, including breath splash interactions.
- Minotaur morale floor and exceptions.
- Triumvirate's Strength faction/unit filter compatibility with `homm3_dungeon`, including replacement of any native-terrain subskill with explicit creature-line receivers.
- Portal of Summoning recruitment source and ownership state.
- Mana Vortex current-mana mutation and weekly visit state.
