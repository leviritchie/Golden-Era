# HoMM3 Conflux Release Spec

Status: release-quality future-porting specification.

## Source References

- Conflux town, creature table, HotA native terrain, unique buildings: https://homm.fandom.com/wiki/Conflux
- Pixie and Sprite stats/abilities: https://heroes.thelazy.net/index.php/Pixie_and_Sprite
- Air Elemental and Storm Elemental stats/abilities: https://heroes.thelazy.net/index.php/Air_Elemental_and_Storm_Elemental
- Water Elemental and Ice Elemental stats/abilities: https://heroes.thelazy.net/index.php/Water_Elemental_and_Ice_Elemental
- Fire Elemental and Energy Elemental stats/abilities: https://heroes.thelazy.net/index.php/Fire_Elemental_and_Energy_Elemental
- Earth Elemental and Magma Elemental stats/abilities: https://heroes.thelazy.net/index.php/Earth_Elemental_and_Magma_Elemental
- Psychic Elemental and Magic Elemental stats/abilities: https://heroes.thelazy.net/index.php/Psychic_Elemental_and_Magic_Elemental
- Firebird and Phoenix stats, HotA costs, Rebirth formula: https://heroes.thelazy.net/index.php/Firebird_and_Phoenix
- Morale immunity reference: https://heroes.thelazy.net/index.php/Morale
- Resurrection immunity reference: https://heroes.thelazy.net/index.php/Resurrection

## Faction Defaults

| Field | Requirement |
| --- | --- |
| Faction SID | `homm3_conflux` |
| City SID | `homm3_conflux_city` |
| Primary donor faction | `nature` with mixed elemental donors only where the donor behavior matches the explicit requirements below |
| Primary donor city | `nature_city` |
| HoMM3 classes | Planeswalker, Elementalist |
| OE class labels | Planeswalker, Elementalist |
| Native terrain | Highlands for HotA alignment |
| Mage Guild cap | Level 5 |
| Risk | High; elemental immunities, morale rules, spellcaster units, Magic University, Aurora Borealis, all-adjacent attacks, and Phoenix rebirth all need native behavior support or scoped custom hooks. |

Identity pillars:

- elemental army with exact elemental immunities, vulnerabilities, and morale behavior
- fast fragile early game into Phoenix initiative/rebirth finish
- magic-school access and broad spell infrastructure
- distinct elemental laws rather than conventional creature culture

## HotA Unit Stats And Abilities

All rows are HotA targets. `Cost` uses HotA values where the wiki distinguishes HotA from Shadow of Death. `Growth bonus` is the named town structure that changes weekly growth.

| Tier | Creature | SID | Atk | Def | Dmg | HP | Spd | Move | Size | Growth | Cost | Shots | Growth bonus | Exact ability requirements |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | --- | --- |
| 1 | Pixie | `h3_pixie` | 2 | 2 | 1-2 | 3 | 7 | Flying | 1 | 20 | 25g | - | Garden of Life +10 | Flying. No no-retaliation on base Pixie. Living/non-elemental for morale/resurrection unless native HoMM3 data proves otherwise. |
| 1+ | Sprite | `h3_sprite` | 2 | 2 | 1-3 | 3 | 9 | Flying | 1 | 20 | 30g | - | Garden of Life +10 | Flying. No enemy retaliation on attacks. Living/non-elemental for morale/resurrection unless native HoMM3 data proves otherwise. |
| 2 | Air Elemental | `h3_air_elemental` | 9 | 9 | 2-8 | 25 | 7 | Ground | 1 | 6 | 250g | - | Elemental Conflux +1 to basic elementals | Elemental. Immune to Meteor Shower. Vulnerable to Armageddon, Lightning Bolt, Chain Lightning, and Titan's Lightning Bolt. Deals 200% base damage to Earth Elementals and Magma Elementals. No ranged attack. |
| 2+ | Storm Elemental | `h3_storm_elemental` | 9 | 9 | 2-8 | 25 | 8 | Ground | 1 | 6 | 275g | 24 | Elemental Conflux +1 to basic elementals | Elemental. Ranged shooter with normal shooter melee penalty. Immune/vulnerable/double-damage rules match Air Elemental. Can cast Protection from Air at advanced level, 6 power, 3 times per battle. |
| 3 | Water Elemental | `h3_water_elemental` | 8 | 10 | 3-7 | 30 | 5 | Ground | 2 | 6 | 300g | - | Elemental Conflux +1 to basic elementals | Elemental. Immune to Ice Bolt, Frost Ring, and Freezing Shot. Vulnerable to Armageddon, Fireball, and Inferno. Not vulnerable to Fire Wall, Land Mine, or Fire Shield. Deals 200% base damage to Fire Elementals and Energy Elementals. No ranged attack. |
| 3+ | Ice Elemental | `h3_ice_elemental` | 8 | 10 | 3-7 | 30 | 6 | Ground | 2 | 6 | 375g | 24 | Elemental Conflux +1 to basic elementals | Elemental. Ranged shooter with normal shooter melee penalty. Immune/vulnerable/double-damage rules match Water Elemental. Can cast Protection from Water at advanced level, 6 power, 3 times per battle. |
| 4 | Fire Elemental | `h3_fire_elemental` | 10 | 8 | 4-6 | 35 | 6 | Ground | 1 | 5 | 350g | - | Elemental Conflux +1 to basic elementals | Elemental. Immune to Fire Magic spells. Vulnerable to Ice Bolt and Frost Ring. Fire-based creature attacks still damage it; in HotA it is vulnerable only to the central hex of Magog's attack. Deals 200% base damage to Water Elementals and Ice Elementals. No flying. |
| 4+ | Energy Elemental | `h3_energy_elemental` | 12 | 8 | 4-6 | 35 | 8 | Flying | 1 | 5 | 400g | - | Elemental Conflux +1 to basic elementals | Elemental. Flying. Fire immunity/vulnerability/double-damage rules match Fire Elemental. Can cast Protection from Fire at advanced level, 6 power, 3 times per battle. |
| 5 | Earth Elemental | `h3_earth_elemental` | 10 | 10 | 4-8 | 40 | 4 | Ground | 1 | 4 | 400g | - | Elemental Conflux +1 to basic elementals | Elemental. Immune to Armageddon, Lightning Bolt, Chain Lightning, and Titan's Lightning Bolt. Vulnerable to Meteor Shower. Deals 200% base damage to Air Elementals and Storm Elementals. |
| 5+ | Magma Elemental | `h3_magma_elemental` | 11 | 11 | 6-10 | 40 | 6 | Ground | 1 | 4 | 500g | - | Elemental Conflux +1 to basic elementals | Elemental. Immune/vulnerable/double-damage rules match Earth Elemental. Can cast Protection from Earth at advanced level, 6 power, 3 times per battle. |
| 6 | Psychic Elemental | `h3_psychic_elemental` | 15 | 13 | 10-20 | 75 | 7 | Ground | 1 | 2 | 750g | - | None | Elemental. No enemy retaliation. Attacks all adjacent enemy stacks. Deals 50% damage to creatures with mind spell immunity. Mind spell immunity is covered by the Elemental rule. |
| 6+ | Magic Elemental | `h3_magic_elemental` | 15 | 13 | 15-25 | 80 | 9 | Ground | 1 | 2 | 800g | - | None | Elemental. No enemy retaliation. Attacks all adjacent enemy stacks. Source immunity has known exceptions, but OE design direction is to use Black Dragon-style full spell immunity. Deals 50% damage to creatures with total spell immunity. |
| 7 | Firebird | `h3_firebird` | 18 | 18 | 30-40 | 150 | 15 | Flying | 2 | 2 | 1500g | - | Vault of Ashes +1 | Flying. Breath attack damages the target hex and the hex behind it. Source HotA has 50% Fire Magic damage reduction, but OE design direction is immunity to a specific spell list instead of implementing partial school reduction. |
| 7+ | Phoenix | `h3_phoenix` | 21 | 18 | 30-40 | 200 | 21 | Flying | 2 | 2 | 2000g + 1 mercury | - | Vault of Ashes +1 | Flying. Breath attack. Fire Magic immunity. Source Rebirth is once per combat per stack after total stack death; OE design direction is to reuse Olden Era Grove Phoenix resurrection mechanics. |

## Shared Elemental Rules

The elemental creature type applies to Air, Storm, Water, Ice, Fire, Energy, Earth, Magma, Psychic, and Magic Elementals.

- Morale is fixed at 0 for elementals; they must not receive positive morale extra turns or negative morale freezes.
- Elementals are immune to Mind spells.
- Elementals are immune to Resurrection and Sacrifice and should not be valid permanent resurrection targets.
- Elemental mirror-match damage rules are pair-specific and must use base damage before attack/defense and other modifiers if the native formula exposes that distinction.
- Spell vulnerability means 200% spell damage from the named spells, not a generic elemental damage multiplier.

## Unit Behavior Requirements

| Line | Required gameplay behavior | Implementation notes/debts |
| --- | --- | --- |
| Pixie/Sprite | Pixie is a fragile flying melee stack. Sprite is the same line with higher damage/speed and no enemy retaliation. | Verify donor no-retaliation can be data-authored; otherwise implement a focused hook for retaliation suppression. Do not give no-retaliation to Pixie. |
| Air/Storm Elemental | Air is fast ground melee. Storm is a 24-shot ground shooter with a normal melee penalty and Protection from Air casts. | Needs explicit shooter/melee-penalty data validation; the old AB text saying no melee penalty is false in HotA. |
| Water/Ice Elemental | Water is large ground melee. Ice is a 24-shot large ground shooter with normal melee penalty and Protection from Water casts. | Must distinguish Fireball/Inferno/Armageddon vulnerability from non-vulnerability to Fire Wall, Land Mine, and Fire Shield. |
| Fire/Energy Elemental | Fire is ground melee. Energy is flying melee and casts Protection from Fire. Both are Fire Magic immune while still taking fire-based creature attack damage. | Needs trace of spell-school immunity versus creature attack damage. HotA Magog central-hex exception should be explicit if Magog-like splash exists in OE. |
| Earth/Magma Elemental | Slow durable ground melee, with Earth/Magma resisting Armageddon and lightning spells and suffering Meteor Shower vulnerability. Magma casts Protection from Earth. | Needs spell-vulnerability hook if native data only supports immunity/resistance, because Meteor Shower vulnerability is not generic earth damage weakness. |
| Psychic/Magic Elemental | Adjacent-enemy area melee with no retaliation. Psychic does half damage to mind-immune targets. Magic does half damage to fully spell-immune targets and is spell immune itself. | All-adjacent enemy selection and half-damage categories require static tracing before implementation. Do not replace with a cone or single-target attack in release data. |
| Firebird/Phoenix | Two-hex flying breath attack line. Firebird should use a specific spell-immunity list in OE instead of partial Fire Magic reduction. Phoenix should use the Olden Era Grove Phoenix resurrection mechanic per user direction. | Verify Grove `phoenix_upg_l.json` death-spawn of `phoenix_heart` and obstacle `spawn_revived_phoenix` behavior before reuse; keep any mismatch as explicit design debt rather than approximating silently. |

## City And Economy

| HoMM3 element | Release requirement | Implementation notes/debts |
| --- | --- | --- |
| Magic University | Source behavior teaches Air, Earth, Fire, and Water Magic for 2000 gold each. OE design direction is +500 Astrology points daily instead. | Use existing `astrologyExp` reward/stat rows as the first candidate, including 500-point faction-law examples, but trace daily town-building timing before enabling text or behavior. |
| Aurora Borealis | Grail structure: +5000 gold/day, +50% creature growth, adds all spells to the Mage Guild. | Start from the external `celestial_sphere` path: `DB/objects_logic/event_banks/celestial_sphere.json` grants `LearnRemotelySideMagics`. Do not represent as all-spells behavior until the town/Grail spell-list path is verified. |
| Garden of Life | Horde building: +10 Pixie/Sprite growth per week. | Data-authored growth bonus if supported. |
| Vault of Ashes | HotA unique horde building: +1 Firebird/Phoenix growth per week. | Required for HotA alignment. |
| Elemental Conflux | External dwelling behavior: increases growth of all four basic elementals by 1 in HotA. | Treat as a dwelling/map-object and town-growth data requirement, not flavor text. |
| Resource Silo | Conflux resource silo behavior needs exact HotA confirmation before implementation. | Static/wiki verification debt. |
| Mage Guild | Level 5. | Exact. |

Economy note: Conflux balance is defined by HotA costs and growth above. Do not reduce costs because several creatures are elementals.

## Laws And Faction Skill

Faction skill proposal: `Elemental Conjury` (shipped name; formerly designed as Summon Elementals).

Current shipped behavior (not a summon button):

- Rank grants start Focus and scales elemental-line Focus abilities from hero Attack and Spell Power.
- Subskill SIDs use `sub_skill_faction_homm3_conflux_elemental_conjury_*`.
- Do not reintroduce `summon_elementals` SID tokens except as overlay stale-removal quarantine entries.

Potential law/subskill themes remain design candidates until the skill is specified:

- Air attunement: speed/initiative for Air and Storm Elementals.
- Water attunement: defense or spell mitigation for Water and Ice Elementals.
- Fire attunement: offense/fire spell interaction for Fire, Energy, Firebird, and Phoenix.
- Earth attunement: HP/defense for Earth and Magma Elementals.
- Elemental convergence: bonuses that require mixed elemental lineups.
- Phoenix cycle: Phoenix rebirth/growth interaction only if exact rebirth hooks are available.

## Heroes

- Clone Nature magic-heavy scaffolding only as an initial data shell; final skill rolls and specialties must be Conflux-specific.
- Class labels: Planeswalker and Elementalist.
- Elemental unit specialists map directly to their HoMM3 line and must use the exact HotA creature stats above.
- Magic-school specialists need exact OE spell-school IDs and text that identifies the real supported spell schools.
- Planar/elemental immunity specialties are static-trace debts until the immunity system is validated.

## Town Art

- Conflux town is animation-heavy. Generate town layers for elemental planes, clouds, portals, Pyre, Garden of Life, Vault of Ashes, Elemental Conflux, Magic University, and Aurora Borealis separately.
- Aurora Borealis visuals must not imply the all-spells Grail behavior is implemented unless the Mage Guild spell-list behavior is implemented too.

## Asset Deployment

- The source plugin already has Conflux unit import rows, custom unit bundles, static unit portraits, preview manifests, lab sidecars, faction icon/card art, and city/dwelling map-object reference frames. Do not keep stale "no bundles/import payload" release blocks unless validation regresses.
- Conflux release hardening still needs `homm3_hero_portraits/`, town layers, build-tree icons, release UI registry/selector exposure, Highlands terrain handling, and mechanics validation. Core.zip data alone is still not enough for visible faction UI or release readiness.
- Verify the actual HoMM3 Conflux town backdrop source and elemental animation/layer sources by eye. Do not use hall/build-tree UI plates or donor assets as the faction card/backdrop.
- Add Conflux to the release custom-game/banner/icon sprite registry explicitly; do not rely on custom Core.zip icon keys to load arbitrary plugin PNGs.

## Tears Of Ashan Alternate Upgrade Targets

Use `docs/homm3_tears_of_ashan_creature_specs.md` as the source for these `_upg_alt` rows. They are not replacements for the HotA base/upgraded rows above. Percentage on-hit effects become guaranteed focus-point abilities in Olden Era while preserving source targets, durations, immunity/resist lists, and effect strength.

| Tier | ToA creature | Target SID | Stats | Cost | Source abilities | OE conversion notes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 alt | Faerie | `h3_pixie_upg_alt` | A2/D3, 1-3 dmg, 6 HP, speed 8, growth 14 | 90 gold | Flying, no retaliation, attacks all adjacent, 20% Mana Channeling. | User direction is to use the Grove Hoplet Leeching Hop mana steal instead of source Mana Channeling. Candidate rows are `twinkle_l.json` and `twinkle_upg_alt_l.json` with `targetMechanics` `change_mana` transfer values. Adjacent attack must use valid enemy-adjacent targeting, not a cone substitute. |
| 2 alt | Hurricane Elemental | `h3_air_elemental_upg_alt` | A7/D7, 2-8 dmg, 15 HP, speed 9, growth 8 | 230 gold | Flying, non-living, mind immunity, Air immunity, receptive air buff, 50% extra damage from Meteor Shower and Implosion. | Composite rule; do your best without breaking things. Preserve named-spell vulnerability where safely traceable and leave unresolved pieces as mechanics debt. |
| 3 alt | Frost Elemental | `h3_water_elemental_upg_alt` | A10/D10, 3-7 dmg, 25 HP, speed 7, growth 6, 24 shots | 350 gold | No ToA ability keys beyond shooter stats in the mined row. | Keep shooter/ammo role explicit and preserve base elemental immunity/vulnerability rules if inherited in implementation. |
| 4 alt | Plasma Elemental | `h3_fire_elemental_upg_alt` | A12/D12, 6-12 dmg, 35 HP, speed 9, growth 5 | 425 gold | Flying, non-living, mind immunity, Fire immunity, receptive fire buff, 50% vulnerability to Ice Bolt/Frost Ring, Fire Shield 25%. | Composite rule; do your best without breaking things. Fire Shield is deterministic retaliation damage; preserve spell-vulnerability ordering where safely traceable. |
| 5 alt | Lava Elemental | `h3_earth_elemental_upg_alt` | A12/D15, 10-18 dmg, 50 HP, speed 6, growth 4 | 650 gold | Non-living, mind immunity, 75% earth/fire spell reduction, 50% vulnerability to lightning/Chain Lightning/Titan Bolt/Ice Bolt/Frost Ring/Deep Freeze, ignores 20% enemy Attack and Defense. | Composite rule; do your best without breaking things. Keep named-spell vulnerability lists explicit and leave unsafe attack/defense-ignore work as mechanics debt. |
| 6 alt | Astral Elemental | `h3_psychic_elemental_upg_alt` | A16/D16, 10-30 dmg, 75 HP, speed 8, growth 2 | 1450 gold | Non-living, mind immunity, attacks all adjacent, no retaliation, level 3 spell immunity, receptive magic buff. | Composite rule; do your best without breaking things. All-adjacent enemy targeting and spell immunity exceptions need static tracing before shipping. |
| 7 alt | Sacred Phoenix | `h3_firebird_upg_alt` | A24/D18, 30-50 dmg, 250 HP, speed 16, growth 1 | 4000 gold, 2 mercury | Flying, breath attack, one Rebirth cast, 25% Rebirth, Fire immunity, King value 0, Fire Shield 30%. | Composite rule; do your best without breaking things. Preserve Phoenix/Grove resurrection behavior separately; Fire Shield is deterministic if safely traceable. |

## Unique Faction Mechanics

- `Elemental Conjury`: shipped as start-Focus and elemental Focus ability Attack/Spell Power scaling under `skill_faction_homm3_conflux` with `elemental_conjury` subskill SIDs. Do not describe a summon button. A Hive/Gating-style true summon remains a separate future design if pursued.
- Elemental immunities, vulnerabilities, morale immunity, and resurrection immunity are core faction mechanics, not optional polish.
- Magic University and Aurora Borealis are core Conflux identity buildings and remain explicit static-trace debts until implemented exactly.

## Static Trace Debts

- Elemental type flags: mind immunity, morale immunity, Resurrection/Sacrifice invalid targets, and interaction with OE living/undead/nonliving tags.
- Spell vulnerability and immunity ordering, including named-spell 200% vulnerabilities and Fire Magic immunity versus fire-based creature attacks.
- Shooter melee penalty for Storm and Ice Elementals.
- Upgraded elemental spellcaster behavior: three casts per battle, advanced-level spell effect, 6 spell power.
- Protection from Air/Water/Fire/Earth exact spell IDs, duration, damage-reduction values, and HotA reductions.
- Psychic/Magic Elemental all-adjacent enemy targeting and half-damage target categories.
- Breath attack geometry for Firebird/Phoenix.
- Grove Phoenix resurrection mechanics (`phoenix_upg`, `phoenix_heart`, `spawn_revived_phoenix`) as the OE basis for Phoenix Rebirth, including gate, permanence, and interaction with battle cleanup.
- Magic University replacement path for daily +500 Astrology points via `astrologyExp` reward/stat rows and town-building timing.
- Aurora Borealis all-spells behavior via the external `celestial_sphere` / `LearnRemotelySideMagics` path.
- Faerie Mana Channeling replacement via Grove Hoplet `change_mana` / Leeching Hop rows.
- Resource Silo exact HotA output.
