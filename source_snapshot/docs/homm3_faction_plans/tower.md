# HoMM3 Tower Release-Quality Porting Spec

Status: release-quality faction specification for manifest generation and QA.

This document defines the expected Tower behavior for future porting work. Donor data is implementation scaffolding only; any donor behavior that conflicts with the HotA source data below is a bug or an explicit static-trace/design debt.

## Faction Defaults

| Field | Target |
| --- | --- |
| Faction SID | `homm3_tower` |
| City SID | `homm3_tower_city` |
| Primary donor faction | `humans` for city scaffolding, mixed unit donors for release-safe prefab fallbacks |
| Primary donor city | `human_city` |
| HoMM3 classes | Alchemist, Wizard |
| OE class labels | Alchemist, Wizard |
| Native terrain | Tundra, cloned from Snow presentation |
| Mage Guild cap | Level 5 |
| Risk | High; Tower relies on ranged units, spell-cost modification, spellcasting creatures, construct/unliving rules, and high-cost late game balance. |

Identity pillars:

- expensive arcane and construct army
- ranged superiority
- magic schools, artifacts, and spell access
- slow durable bodies protecting fragile casters
- late-game Titan/Naga power with high gold and gem pressure

## Sources

- Heroes 3 Wiki, Tower creature table and Tower town data: https://heroes.thelazy.net/index.php/Tower
- Heroes 3 Wiki, Gremlin and Master Gremlin: https://heroes.thelazy.net/index.php/Gremlin_and_Master_Gremlin
- Heroes 3 Wiki, Stone Gargoyle and Obsidian Gargoyle: https://heroes.thelazy.net/index.php/Stone_Gargoyle_and_Obsidian_Gargoyle
- Heroes 3 Wiki, Non-living / Bloodless rules: https://heroes.thelazy.net/index.php/Non-living
- Heroes 3 Wiki, Stone Golem and Iron Golem: https://heroes.thelazy.net/index.php/Stone_Golem_and_Iron_Golem
- Heroes 3 Wiki, Spell damage reduction: https://heroes.thelazy.net/index.php/Spell_damage_reduction
- Heroes 3 Wiki, Mage and Arch Mage: https://heroes.thelazy.net/index.php/Mage_and_Arch_Mage
- Heroes 3 Wiki, Genie and Master Genie: https://heroes.thelazy.net/index.php/Genie_and_Master_Genie
- Heroes 3 Wiki, Spellcaster: https://heroes.thelazy.net/index.php/Spellcaster
- Heroes 3 Wiki, Naga and Naga Queen: https://heroes.thelazy.net/index.php/Naga_and_Naga_Queen
- Heroes 3 Wiki, Giant and Titan: https://heroes.thelazy.net/index.php/Giant_and_Titan
- Heroes 3 Wiki, Mind spell: https://heroes.thelazy.net/index.php/Mind_spell

## HotA Unit Stats And Abilities

Stats are copied from the Heroes 3 Wiki Tower creature data. Use these as the acceptance target for Tower units unless OE balance intentionally overrides a value in a separate balance note.

| Tier | Unit | Target SID | Atk | Def | Dmg | HP | Spd | Move | Size | Growth | Shots | Cost | AI Value | Fight Value | HotA abilities and exact behavior |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |
| 1 | Gremlin | `h3_gremlin` | 3 | 3 | 1-2 | 4 | 4 | Ground | 1 | 16 | - | 30 gold | 44 | 55 | Melee only. No ranged attack. |
| 1+ | Master Gremlin | `h3_gremlin_up` | 4 | 4 | 1-2 | 4 | 5 | Ground | 1 | 16 | 8 | 40 gold | 66 | 55 | Ranged shooter with 8 shots. This upgrade is the first Tower shooter; base Gremlin must not inherit ranged donor behavior. |
| 2 | Stone Gargoyle | `h3_gargoyle` | 6 | 6 | 2-3 | 16 | 6 | Flying | 1 | 9, plus Sculptor's Wings growth if implemented | - | 130 gold | 165 | 150 | Flying. Bloodless in HotA: treated as non-living for resurrection/life-drain/poison/disease/death-cloud style restrictions, but still affected by morale and mind spells. |
| 2+ | Obsidian Gargoyle | `h3_gargoyle_up` | 7 | 7 | 2-3 | 16 | 9 | Flying | 1 | 9, plus Sculptor's Wings growth if implemented | - | 160 gold | 201 | 155 | Flying. Same Bloodless behavior as Stone Gargoyle. |
| 3 | Stone Golem | `h3_golem` | 7 | 10 | 4-5 | 30 | 3 | Ground | 1 | 6 | - | 150 gold | 250 | 339 | Golem/unliving. Damage from spells reduced by 50%. Neutral morale and immune to mind spells and living-only creature effects. |
| 3+ | Iron Golem | `h3_golem_up` | 9 | 10 | 4-5 | 35 | 5 | Ground | 1 | 6 | - | 200 gold | 412 | 412 | Golem/unliving. Damage from spells reduced by 75%. Neutral morale and immune to mind spells and living-only creature effects. |
| 4 | Mage | `h3_mage` | 11 | 8 | 7-9 | 25 | 5 | Ground | 1 | 4 | 24 | 350 gold | 570 | 418 | Ranged shooter with 24 shots. No melee penalty. No obstacle/barrier penalty. Magic Channeler: hero combat spells cost 2 less spell points if a Mage or Arch Mage was present at battle start; the discount persists for the battle even if the stack dies and does not affect adventure-map spells. |
| 4+ | Arch Mage | `h3_mage_up` | 12 | 9 | 7-9 | 30 | 7 | Ground | 1 | 4 | 24 | 450 gold | 680 | 467 | Same as Mage: ranged shooter, no melee penalty, no obstacle/barrier penalty, Magic Channeler. |
| 5 | Genie | `h3_genie` | 12 | 12 | 13-16 | 40 | 7 | Flying | 1 | 3 | - | 550 gold | 884 | 680 | Flying. Hates Efreet and Efreet Sultans, dealing 150% damage to those targets. No spellcasting on the base unit. |
| 5+ | Master Genie | `h3_genie_up` | 12 | 12 | 13-16 | 40 | 11 | Flying | 1 | 3 | - | 600 gold | 942 | 748 | Flying. Hates Efreet and Efreet Sultans. Spellcaster: can spend its action up to 3 times per battle to cast a random beneficial spell on an allied troop at Advanced-school level with spell power 6. Stack size does not change spell strength. It must not choose spells that the target is immune to or that have no effect. |
| 6 | Naga | `h3_naga` | 16 | 13 | 20 | 110 | 5 | Ground | 2 | 2 | - | 1100 gold | 2016 | 2016 | Fixed damage. No enemy retaliation on attacks. |
| 6+ | Naga Queen | `h3_naga_up` | 16 | 13 | 30 | 110 | 7 | Ground | 2 | 2 | - | 1600 gold | 2840 | 2840 | Fixed damage. No enemy retaliation on attacks. |
| 7 | Giant | `h3_giant` | 19 | 16 | 40-60 | 150 | 7 | Ground | 1 | 1 | - | 2000 gold + 1 gem | 3718 | 3146 | Mind spell immunity. Melee unit; no ranged attack and no Black Dragon hate on the base unit. |
| 7+ | Titan | `h3_giant_up` | 24 | 24 | 40-60 | 300 | 11 | Ground | 1 | 1 | 24 | 5000 gold + 2 gems | 7500 | 5000 | Ranged shooter with 24 shots. No melee penalty. Mind spell immunity. Hates Black Dragons, dealing 150% damage to Black Dragons only. |

Master Genie spell list:

| Spell | Level | School |
| --- | ---: | --- |
| Bless | 1 | Water |
| Bloodlust | 1 | Fire |
| Cure | 1 | Water |
| Haste | 1 | Air |
| Protection from Fire | 1 | Fire |
| Protection from Water | 1 | Water |
| Shield | 1 | Earth |
| Stone Skin | 1 | Earth |
| Fortune | 2 | Air |
| Precision | 2 | Air |
| Protection from Air | 2 | Air |
| Air Shield | 3 | Air |
| Anti-Magic | 3 | Earth |
| Protection from Earth | 3 | Earth |
| Mirth | 3 | Water |
| Counterstrike | 4 | Air |
| Fire Shield | 4 | Fire |
| Frenzy | 4 | Fire |
| Prayer | 4 | Water |
| Slayer | 4 | Fire |
| Magic Mirror | 5 | Air |

## Unit Decisions

| Tier | HoMM3 line | Target SID family | Release-safe donor | Required release behavior | Debt |
| --- | --- | --- | --- | --- | --- |
| 1 | Gremlin -> Master Gremlin | `h3_gremlin` | `crossbowman` only if attack mode is corrected | Base Gremlin is melee only; Master Gremlin is a ranged shooter with 8 shots. | Verify donor attack mode does not leak ranged behavior to `h3_gremlin`. |
| 2 | Stone Gargoyle -> Obsidian Gargoyle | `h3_gargoyle` | `wasp` or `griffin` shell | Flying Bloodless unit with HotA stats. Bloodless must block living-only effects while preserving morale and mind-spell vulnerability. | Static-trace OE effect flags for resurrection, poison, death cloud, life drain, morale, and mind spells. |
| 3 | Stone Golem -> Iron Golem | `h3_golem` | `ent` downscaled | Slow durable melee unit with 50% / 75% spell damage reduction and golem/unliving immunity profile. | Static-trace native spell-damage-reduction and mind-immunity paths; do not substitute plain defense/HP for resistance. |
| 4 | Mage -> Arch Mage | `h3_mage` | `lightweaver` | Ranged shooter with 24 shots, no melee penalty, no obstacle penalty, and Magic Channeler combat-spell cost reduction. | Static-trace ranged obstacle and combat-spell-cost hooks. |
| 5 | Genie -> Master Genie | `h3_genie` | `succubus` or `arbitrator` | Genie is flying melee with Efreet hate. Master Genie adds the exact 3-use random beneficial spellcaster behavior. | Static-trace creature spellcasting action path and target/spell validation. A deterministic focus boon is only an OE alternate mechanic after HotA behavior is accounted for. |
| 6 | Naga -> Naga Queen | `h3_naga` | `minos` | Two-hex melee unit with fixed damage and no enemy retaliation. | Static-trace no-retaliation flags; no-retaliation must not be downgraded to a focus-only effect. |
| 7 | Giant -> Titan | `h3_giant` | `angel` shell with corrected attack mode | Giant is melee and mind-spell immune. Titan is ranged with 24 shots, no melee penalty, mind-spell immunity, and Black Dragon hate. | Static-trace shooter/no-melee/mind-immunity/hate flags. Base Giant must not inherit Titan ranged behavior. |

## City And Economy

| HoMM3 element | Release target | Debt |
| --- | --- | --- |
| Library | Adds one extra spell of each level to Tower Mage Guild spell offerings. | Static-trace city/mage-guild schema before implementing. |
| Artifact Merchants | Functional artifact marketplace, not flavor text only. | Map to existing OE artifact market category or implement a Tower-specific city action. |
| Lookout Tower | Tower-specific scouting/vision city effect. | Static-trace OE map vision/scouting modifiers. |
| Wall of Knowledge | Visiting hero gains +1 Knowledge once per hero, matching HoMM3 structure identity if OE supports visit-once city effects. | Static-trace visit reward state. |
| Sculptor's Wings | Increases Gargoyle growth by +4 per week. | Implement growth modifier and verify both Stone and Obsidian Gargoyle recruit pools. |
| Resource Silo | Daily gem income if OE resource mapping supports gems. | Confirm OE resource SID and income schema. |
| Mage Guild | Level 5 Mage Guild with Tower/Library spell identity. | Exact. |

Economy note: Tower must remain expensive. Do not reduce rare-resource pressure without a separate balance decision that accounts for Titan, Mage Guild, Library, and Artifact Merchant costs.

## Laws And Faction Skill

Law themes should support Tower's expensive arcane economy and construct army without replacing HotA unit behavior:

- Workshop contracts: Gremlin/Gargoyle growth or recruitment efficiency.
- Golem foundry: Golem durability or spell-resistance support.
- Arcane focus: Mage/Arch Mage ranged or spell-channel identity.
- Naga discipline: melee damage or no-retaliation synergy.
- Titan forge: rare-resource income or Titan cost pressure.
- Spell archive: Mage Guild/Library spell access, hero Knowledge, or mana.

Faction skill: `Arcane Battery`.

Spend 2/1/0 Focus once per round (Basic/Advanced/Expert) to refresh spellbook use this round. Native ability carries `refresh_spell_book` only. Per-spell cooldowns are intentionally not cleared — a full wipe would be overtuned, and the former `Homm3TowerArcaneBatteryRuntime` path was removed. Advanced/Expert scholar subskills keep curriculum, Chronomancy, Mana Well Aegis, remote library, spell economies, and start Focus.

Release target:

- Artifice is the Tower unique faction skill for construct enhancement. It is an OE port mechanic, not a HotA creature ability.
- Core rank effect: eligible Tower constructs gain Attack from the hero's Spell Power and Defense from the hero's Knowledge at 20% / 40% / 60% effectiveness by rank.
- Eligible construct set: Gremlin, Master Gremlin, Stone Gargoyle, Obsidian Gargoyle, Stone Golem, Iron Golem. Do not include Mage, Arch Mage, Genie, Master Genie, Naga, Naga Queen, Giant, or Titan unless a later design note explicitly expands the construct set.
- The effect must use Tower-specific skill/bonus IDs and must not reuse Human donor subskills or global `sub_skill_faction_humans_*` IDs.
- Artifice must have Tower-specific subskills before release. The current no-subskill implementation is incomplete, not an accepted final state.

Required Artifice subskill design debt:

| Subskill slot | Required design shape | Constraints |
| --- | --- | --- |
| Construct offense | Improves construct attack output through Spell Power scaling, focus generation, or a construct-only attack modifier. | Must affect only the explicit construct set and must stack predictably with the core rank effect. |
| Construct defense | Improves construct survival through Knowledge scaling, spell-damage reduction, shield, or repair-like mitigation. | Must not make Gargoyles/Golems lose their distinct Bloodless/Golem immunity profiles. |
| Arcane workshop | Provides an economy, recruitment, or pre-battle preparation effect tied to Tower constructs. | Must use Tower-specific IDs and localized text; no donor faction text or Human subskills. |

## Heroes

- Clone Human or Unfrozen magic-heavy hero scaffolding only after checking which donor tables produce better Wizard skill rolls.
- Class labels: Alchemist and Wizard.
- Unit specialists map directly where possible.
- Tower hero start armies must respect HotA unit roles: base Gremlin melee, Master Gremlin ranged, Giant melee, Titan ranged.
- Genie spell specialties, specialty artifacts, and spell-school bonuses need explicit OE spell SID mapping.
- Hero names, biographies, specialties, portraits, and class text must be Tower-localized rows, not Human donor leftovers.

## Town Art

- Tower has many tall vertical structures. Generate layers against the verified Tower backdrop and require manual z-order/occlusion review.
- Titan/Cloud Temple and Mage Guild variants need per-level placement review.
- Artifacts, Library, Lookout Tower, Wall of Knowledge, and other unique structures must not claim behavior unless implemented in city JSON and UI text.

## Asset Deployment

- Tower release asset deployment is required in addition to Core.zip overlay work. Core.zip data alone is not enough for visible faction UI, unit portraits, imported unit visuals, town art, or map-object art.
- The deployment lane must populate the Steam plugin payload for `homm3_tower`: `homm3_bundles/custom_units_h3_*`, `homm3_import.json` rows for every Tower `h3_*` unit SID, `homm3_portraits/`, `bundle-backed recruitment idle clips`, `homm3_hero_portraits/`, `homm3_runtime_assets/faction_icons/homm3_tower/`, `homm3_runtime_assets/town_scene_refs/homm3_tower/`, and Tower city/dwelling map-object reference frames.
- The Tower town backdrop source is HoMM3 `H3bitmap.lod` member `tbtwback.pcx` decoded as the custom town-scene payload. Do not use `TpThBkTw` or `TowerHallBg.png`; those are hall/build-tree UI plates, not the snowy town scene.
- Add Tower to the release custom-game/banner/icon sprite registry explicitly and verify the Steam plugin payload after build/deploy.

## Unit Focus And Tears Of Ashan Alternate Upgrades

These are OE extension rows for `_upg_alt` units. They do not replace the HotA base/upgraded stats and abilities above. Exact stats and source abilities come from `docs/homm3_tears_of_ashan_creature_specs.md` Tears of Ashan manifest version `1.5.5`.

Do not use vague placeholder alternates for Tower where these ToA rows exist. Percentage-based chance-to-proc effects from ToA must be specified as guaranteed focus-point-costing active abilities in OE, preserving the source target and effect strength as closely as practical. This applies even when the ToA chance is 100%, because Olden Era should expose the effect as a deliberate active ability instead of a hidden attack proc.

| Tier | ToA unit | Target SID | Stats | Growth/Shots/Cost | Source ToA abilities | OE port target |
| --- | --- | --- | --- | --- | --- | --- |
| 1+ alt | Gremlin Mechanic | `h3_gremlin_upg_alt` | A/D 3/3, dmg 1-2, HP 6, Spd 5 | Growth 16, melee, 40 gold | Casts Advanced Repair twice per battle at 10% power. Source `gremlinRepair`: target allied Siege Weapon or Golem/Gargoyle/Giant troop with dead creatures; Advanced repairs `50 + power x 30` HP permanently. | Active `Repair`: focus-costing support action with 2 battle charges, targeting allied Siege Weapon, Golem, Gargoyle, or Giant-family stacks with casualties. Preserve ToA 10% power and Advanced repair strength. |
| 2+ alt | Elemental Gargoyle | `h3_gargoyle_upg_alt` | A/D 6/8, dmg 2-3, HP 20, Spd 7 | Growth 9, melee, 160 gold | Gargoyle, Flying, 50% spell-damage reduction from Air/Earth/Fire/Water, Stone Gaze immunity. | Flying Bloodless Gargoyle alternate with deterministic 50% elemental spell-damage reduction and Stone Gaze immunity. Do not collapse this into generic magic resistance if OE can distinguish schools. |
| 3+ alt | Magnetic Golem | `h3_golem_upg_alt` | A/D 7/12, dmg 4-5, HP 35, Spd 5 | Growth 6, melee, 200 gold | Non-living. Immune to Disrupting Ray, Slow, Curse, Misfortune, Weakness, and Stone Gaze. ToA attacks cast Basic Slow after attack at 2 power. | Passive non-living/golem immunity profile plus an active `Magnetic Slow`: guaranteed focus-costing attack/action that applies Basic Slow at 2 power to the attacked/targeted enemy. Do not implement the source hit effect as an automatic proc. |
| 4+ alt | Battle Mage | `h3_mage_upg_alt` | A/D 14/8, dmg 8-10, HP 30, Spd 6 | Growth 4, 24 shots, 500 gold | Shooter, no wall penalty, reduces allied spell costs by 2, 3 casts, 40% creature spell power. ToA spellcaster chances: Advanced Magic Arrow at 40% power, Advanced Ice Bolt at 40% power, Advanced Lightning Bolt at 30% power. | Ranged caster alternate with Magic Channeler. Replace random spell chances with explicit focus-costing active spell choices: `Magic Arrow` at Advanced/40% power, `Ice Bolt` at Advanced/40% power, and `Lightning Bolt` at Advanced/30% power, sharing the ToA 3-cast battle limit. |
| 5+ alt | Genie Vizier | `h3_genie_upg_alt` | A/D 14/12, dmg 13-16, HP 50, Spd 10 | Growth 3, melee, 650 gold | Flying. Hates Efreet, Efreet Sultans, and Efreet Sufis for 150% damage. 50% Air spell-damage reduction. ToA attacks cast Advanced Misfortune after attack at 3 power. | Flying melee Genie alternate with Efreet-line hate and 50% Air spell-damage reduction. Replace the Misfortune hit proc with active `Vizier's Misfortune`: guaranteed focus-costing debuff applying Advanced Misfortune at 3 power to a target enemy. |
| 6+ alt | Naga Rani | `h3_naga_upg_alt` | A/D 16/14, dmg 25-25, HP 110, Spd 8 | Growth 2, melee, 1600 gold | Blocks retaliation and attacks three adjacent heads/targets. | Two-hex fixed-damage melee alternate with baseline no-retaliation and deterministic three-headed attack. No focus conversion needed because no percentage proc is involved. |
| 7+ alt | Colossus | `h3_giant_upg_alt` | A/D 26/22, dmg 40-60, HP 330, Spd 12 | Growth 1, melee, 5000 gold + 2 gems | King value 3, mind immunity, hates Red Dragons, Black Dragons, and Shadow Dragons for 150% damage. ToA attacks have a 40% chance to cast Thunderbolt for 25 damage per Colossus. | Mind-immune Giant-family alternate with Dungeon dragon hate expanded exactly to Red Dragon, Black Dragon, and Shadow Dragon. Replace random Thunderbolt with active `Thunderbolt`: guaranteed focus-costing single-target strike dealing 25 damage per Colossus. |

## Static Trace And Design Debts

- Base Gremlin must be melee; Master Gremlin must be ranged with 8 shots. Audit donor SIDs and any inherited shooter flags.
- Base Giant must be melee; Titan must be ranged with 24 shots and no melee penalty. Audit donor SIDs and inherited attack modes.
- Gargoyle Bloodless rules: verify OE flags for non-living restrictions while preserving morale and mind-spell vulnerability.
- Golem spell damage reduction: implement true spell damage reduction, not only increased defense or HP.
- Golem/unliving profile: verify neutral morale, mind immunity, resurrection/animate-dead restrictions, life drain, poison, disease, death cloud, aging, death stare, fear, and demon-summon interactions.
- Mage and Arch Mage no melee penalty, no obstacle/barrier penalty, and Magic Channeler combat-spell cost reduction.
- Master Genie spellcaster action: 3 casts per battle, advanced-school level, spell power 6, stack-size independent, effect/immune target filtering, and exact spell list.
- Naga and Naga Queen no-retaliation as a baseline attack flag.
- Giant/Titan mind-spell immunity.
- Titan Black Dragon hate at 150% damage, and no hate on base Giant.
- Library spell-list expansion.
- Artifice subskills with Tower-specific IDs, localization, and non-donor effects.
- Tower unique building behavior must be implemented or text must mark it as unavailable; no city text may imply a feature that does not work.
