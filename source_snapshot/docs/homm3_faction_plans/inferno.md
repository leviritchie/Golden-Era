# HoMM3 Inferno Release-Quality Port Plan

Status: release-quality faction spec draft for future manifest generation and implementation audit.

Inferno should port as a HotA-faithful faction target. Any mechanic that cannot be represented with existing Olden Era data should be recorded as static-trace/design debt with the exact HoMM3 behavior preserved as the acceptance target.

## Source URLs

- Inferno overview, native terrain, buildings, creature table, and HotA creature values: https://heroes.thelazy.net/index.php/Inferno
- Imp and Familiar stats and Magic Channel: https://heroes.thelazy.net/index.php/Imp_and_Familiar
- Gog and Magog stats and HotA Fireball Attack behavior: https://heroes.thelazy.net/index.php/Gog_and_Magog
- Hell Hound and Cerberus stats and 3-headed/no-retaliation behavior: https://heroes.thelazy.net/index.php/Hell_Hound_and_Cerberus
- Demon and Horned Demon stats: https://heroes.thelazy.net/index.php/Demon_and_Horned_Demon
- Pit Fiend and Pit Lord stats: https://heroes.thelazy.net/index.php/Pit_Fiend_and_Pit_Lord
- Pit Lord Summon Demons formula: https://heroes.thelazy.net/index.php/Summon_demons
- Efreeti and Efreet Sultan stats, fire immunity, hate, and natural Fire Shield: https://heroes.thelazy.net/index.php/Efreeti_and_Efreet_Sultan
- Fire Shield spell and natural Efreet Sultan Fire Shield details: https://heroes.thelazy.net/index.php/Fire_Shield
- Devil and Arch Devil stats, teleport, no-retaliation, luck reduction, and hate: https://heroes.thelazy.net/index.php/Devil_and_Arch_Devil
- Hate mechanic reference: https://heroes.thelazy.net/index.php/Hate

## Faction Defaults

| Field | Spec |
| --- | --- |
| Faction SID | `homm3_inferno` |
| City SID | `homm3_inferno_city` |
| Primary donor faction | `demons` |
| Primary donor city | `demon_city` |
| HoMM3 classes | Demoniac, Heretic |
| OE class labels | Demoniac, Heretic |
| Native terrain | Lava |
| Mage Guild cap | Level 5 |
| Risk | High; Magic Channel, HotA Magog targeting, Pit Lord demon resurrection, Efreet fire immunity/shield, Devil teleport/no-retaliation, and global enemy Luck reduction need native behavior tracing. |

Identity pillars:

- Aggressive fire and demon army with high mobility and first-strike pressure.
- Inferno macro strength comes from Castle Gate logistics and Pit Lord demon farming, not generic economy smoothing.
- Inferno has only one shooter line; Magog area fire is important and must preserve friendly-fire and HotA targeting semantics.
- Late-game power is concentrated in Efreeti/Efreet Sultans and Devils/Arch Devils.

## HotA Unit Stats And Abilities

All stats below are HotA targets. `Shots` is blank for non-ranged units. `Cost` includes extra resources where applicable.

| Tier | Creature | SID | Atk | Def | Dmg | HP | Speed | Move | Size | Growth | Shots | AI Value | Fight Value | Cost | HotA abilities |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | Imp | `h3_imp` | 2 | 3 | 1-2 | 4 | 5 | Ground | 1 | 15, +8 with Birthing Pool |  | 50 | 50 | 50 gold | None. |
| 1+ | Familiar | `h3_familiar` | 4 | 4 | 1-2 | 4 | 7 | Ground | 1 | 15, +8 with Birthing Pool |  | 60 | 60 | 60 gold | Magic Channel: while at least one Familiar stack is alive, the owning hero gains spell points equal to 20% of enemy hero spell point cost, rounded down. Does not stack across multiple Familiar stacks. |
| 2 | Gog | `h3_gog` | 6 | 4 | 2-4 | 13 | 4 | Ground | 1 | 8 | 12 | 159 | 145 | 125 gold | Shooter. |
| 2+ | Magog | `h3_magog` | 7 | 4 | 2-4 | 13 | 6 | Ground | 1 | 8 | 24 | 240 | 210 | 175 gold | Shooter with Fireball Attack. HotA allows targeting any battlefield hex except its own and adjacent hexes unless Bow of the Sharpshooter changes adjacency rules. Area damage hits the target hex and surrounding hexes, includes friendly fire, and fire-immune creatures are damaged only if they occupy the central target hex. |
| 3 | Hell Hound | `h3_hell_hound` | 10 | 6 | 2-7 | 25 | 7 | Ground | 2 | 5, +3 with Cages |  | 357 | 275 | 200 gold | None. |
| 3+ | Cerberus | `h3_cerberus` | 10 | 8 | 2-7 | 25 | 8 | Ground | 2 | 5, +3 with Cages |  | 392 | 308 | 250 gold | 3-headed attack and no enemy retaliation. Attack affects the target hex plus the left and right adjacent hexes relative to attack direction. Two-hex creatures do not take double damage from the multi-hex attack. Lucky/Unlucky Strike affects only the directly attacked creature. |
| 4 | Demon | `h3_demon` | 10 | 10 | 7-9 | 35 | 5 | Ground | 1 | 4 |  | 445 | 445 | 250 gold | None. Can also be created by Pit Lord Summon Demons. |
| 4+ | Horned Demon | `h3_horned_demon` | 10 | 10 | 7-9 | 40 | 6 | Ground | 1 | 4 |  | 480 | 480 | 270 gold | None. |
| 5 | Pit Fiend | `h3_pit_fiend` | 13 | 13 | 13-17 | 45 | 6 | Ground | 1 | 3 |  | 765 | 765 | 500 gold | None. |
| 5+ | Pit Lord | `h3_pit_lord` | 13 | 13 | 13-17 | 45 | 7 | Ground | 1 | 3 |  | 1224 | 1071 | 700 gold | Summon Demons from a dead allied living stack, once per combat action source. Capacity is 50 HP per Pit Lord. Result count is `min(floor(min(dead_count * dead_single_health, pit_lord_count * 50) / 35), dead_count)`. The dead stack must have at least 35 total HP. Non-living creatures cannot be summoned as Demons. Cursed Ground prevents the ability. |
| 6 | Efreeti | `h3_efreeti` | 16 | 12 | 16-24 | 90 | 9 | Flying | 1 | 2 |  | 1670 | 1413 | 900 gold | Flying, immune to Fire Magic, hates Genies and deals 150% damage to Genies. |
| 6+ | Efreet Sultan | `h3_efreet_sultan` | 16 | 14 | 16-24 | 90 | 13 | Flying | 1 | 2 |  | 2343 | 1802 | 1100 gold | Flying, immune to Fire Magic, hates Genies and deals 150% damage to Genies, natural Basic Fire Shield. Natural Fire Shield returns 20% of hand-to-hand damage inflicted on the Sultan to melee attackers, using Fire Shield rules; if a stronger Fire Shield is active, only the stronger shield applies. |
| 7 | Devil | `h3_devil` | 19 | 21 | 30-40 | 160 | 11 | Teleporting | 1 | 1 |  | 5101 | 3759 | 2700 gold + 1 mercury | Teleports to any battlefield hex, no enemy retaliation, applies -1 enemy Luck while present, hates Angels and deals 150% damage to Angels. |
| 7+ | Arch Devil | `h3_arch_devil` | 26 | 28 | 30-40 | 200 | 17 | Teleporting | 1 | 1 |  | 7115 | 5243 | 4500 gold + 2 mercury | Teleports to any battlefield hex, no enemy retaliation, applies -2 enemy Luck in HotA, hates Angels and deals 150% damage to Angels. |

## Unit Implementation Expectations

| Tier | HoMM3 line | Target SID family | Proposed donor | Required behavior | Debt |
| --- | --- | --- | --- | --- | --- |
| 1 | Imp -> Familiar | `h3_imp`, `h3_familiar` | `trick_demon` | Imp is a fragile ground melee unit with no ability. Familiar must preserve Magic Channel as enemy spell-cost mana refund, rounded down, non-cumulative across Familiar stacks. | Trace battle spell-cast event, enemy caster ownership, and hero mana write path. |
| 2 | Gog -> Magog | `h3_gog`, `h3_magog` | `locust` | Gog is a 12-shot ranged unit. Magog is a 24-shot ranged unit with HotA Fireball Attack, explicit target-hex selection, surrounding-hex area damage, friendly fire, and central-hex exception for fire-immune units. | Trace ranged target selection, empty-hex targeting support, area damage, fire immunity filters, and Bow of the Sharpshooter adjacency override. |
| 3 | Hell Hound -> Cerberus | `h3_hell_hound`, `h3_cerberus` | `jaw` | Hell Hound is a size-2 fast melee unit. Cerberus is size-2, no enemy retaliation, and damages the target plus left/right adjacent hexes by attack direction without double-damaging size-2 targets. | Trace multi-target melee hit construction and no-retaliation flags. |
| 4 | Demon -> Horned Demon | `h3_demon`, `h3_horned_demon` | `olgoi` | Ground melee bruiser line with no innate special ability. Demon must be spawnable by Pit Lord resurrection. Horned Demon is not the Pit Lord summon result in HoMM3. | Trace whether summoned stacks can use a separate unit SID from the caster faction unit line. |
| 5 | Pit Fiend -> Pit Lord | `h3_pit_fiend`, `h3_pit_lord` | `hive_queen` | Pit Fiend has no ability. Pit Lord must implement Summon Demons using exact HotA formula and target restrictions. | Trace dead-stack records, living/non-living classification, per-combat use accounting, Cursed Ground, Clone/multiple-stack behavior, and Demon stack creation/merging. |
| 6 | Efreeti -> Efreet Sultan | `h3_efreeti`, `h3_efreet_sultan` | `eldritch_flyer` or fire visual shell | Both fly, are immune to Fire Magic, and hate Genies. Efreet Sultan has natural Basic Fire Shield with spell-stacking rule. | Trace fire school immunity, hate damage modifier, melee damage reflection, fire shield stacking priority, and spell-damage mitigation hooks. |
| 7 | Devil -> Arch Devil | `h3_devil`, `h3_arch_devil` | `godslayer` | Teleporting size-1 elite striker. Both ignore enemy retaliation and hate Angels. Devil applies -1 enemy Luck; Arch Devil applies -2 enemy Luck in HotA. | Trace teleport movement, no-retaliation flags, global enemy Luck modifier lifecycle, hate damage modifier, and battle UI stat display. |

## City And Economy

| HoMM3 element | Release target | Debt |
| --- | --- | --- |
| Castle Gate | Native Inferno town-to-town creature transfer between owned Inferno towns. UI text must not claim it works until the session behavior is implemented. | Trace town network, garrison transfer, town ownership, and multiplayer/session save handling. |
| Birthing Pools | +8 weekly Imp/Familiar growth. | Exact data implementation. |
| Cages | +3 weekly Hell Hound/Cerberus growth. | Exact data implementation. |
| Brimstone Stormclouds | Inferno unique building; define exact HoMM3 behavior from source before implementation. | Source and trace building effect. |
| Order of Fire | Inferno unique building; define exact HoMM3 behavior from source before implementation. | Source and trace building effect. |
| Resource Silo | Inferno resource silo should produce sulfur if matching HoMM3; verify against game data before writing manifest. | Source and trace resource ids. |
| Mage Guild | Level 5. | Exact data implementation. |

Economy note: keep Inferno rare-resource pressure for Pit Fiends, Efreeti, Devils, and town buildout. Castle Gate and Pit Lord demon farming are faction-defining systems and should be represented as implementation debts until exact behavior is supported.

## Laws And Faction Skill

Faction skill proposal: `Gating`.

`Gating` is not a HoMM3 Inferno creature ability; it is a faction-skill design bridge for Olden Era. Its release spec must be written independently from creature fidelity and must not replace Pit Lord Summon Demons, Familiar Magic Channel, Magog Fireball Attack, Efreet Fire Shield, or Devil teleport/no-retaliation.

Law themes should reinforce exact Inferno unit identity:

- Imp swarms: T1 growth or survivability tied to Imp/Familiar line.
- Hellfire volleys: Gog/Magog ranged or fireball-area support.
- Hound packs: Hell Hound/Cerberus speed, no-retaliation, or multi-target melee support.
- Demon herding: Pit Lord summon support or Demon line durability.
- Efreet flame: Fire immunity, Fire Shield, or hate-vs-Genies interactions.
- Devil bargains: Devil/Arch Devil teleport-strike, enemy Luck pressure, or high-tier cost/initiative.

## Heroes

- Clone Demon hero/subclass scaffolding only as a data shell; visible class labels are Demoniac and Heretic.
- Unit specialists map to exact Inferno SIDs: `h3_imp`, `h3_gog`, `h3_hell_hound`, `h3_demon`, `h3_pit_fiend`, `h3_efreeti`, and `h3_devil` families as appropriate.
- Gating, demon-raising, fire specialty, spell specialties, war-machine heroes, and economy heroes require OE spell/ability mapping before final text.
- Hero text must distinguish implemented mechanics from static-trace debts.

## Town Art

- Inferno town requires fire/lava scene review, with animated flame/lava assets tracked as placement and animation work.
- Castle Gate visuals must not imply functional town teleport until the mechanic is implemented.
- Native terrain and town presentation should reinforce Lava as the Inferno biome.

## Asset Deployment

- The source plugin already has Inferno unit import rows, custom unit bundles, static unit portraits, preview manifests, lab sidecars, faction icon/card art, and city/dwelling map-object reference frames. Do not keep stale "no bundles/import payload" release blocks unless validation regresses.
- Inferno release hardening still needs `homm3_hero_portraits/`, town layers, build-tree icons, release UI registry/selector exposure, verified town backdrop/layer sources, and mechanics validation. Core.zip data alone is still not enough for visible faction UI or release readiness.
- Verify the actual HoMM3 Inferno town backdrop source and animated flame/lava layer sources by eye. Do not use hall/build-tree UI plates or donor Demon assets as the faction card/backdrop.
- Add Inferno to the release custom-game/banner/icon sprite registry explicitly; do not rely on custom Core.zip icon keys to load arbitrary plugin PNGs.

## Tears Of Ashan Alternate Upgrades

These `_upg_alt` and extra branch rows are additive Olden Era design targets sourced from `docs/homm3_tears_of_ashan_creature_specs.md` (`tears-of-ashan` manifest `1.5.5`). They do not replace the HoMM3/HotA base and upgraded rows above. Preserve the exact HoMM3/HotA stats and abilities for base/upgraded units, and add these as alternate upgrade or extra-branch units only where the manifest explicitly supports the row.

ToA demonic common package: units with `DEMONIC` keep the demonic classification, take 25% more damage from `holyWord`, and usually have 25% Fire spell damage reduction unless the row upgrades that to Fire Magic immunity or a different fire-damage rule. Do not collapse these into generic fire flavor text; each unit row below states the exact fire rule.

| Tier | ToA creature | Target SID | Upgrade relationship | Atk | Def | Dmg | HP | Speed | Move | Growth | Shots | Cost | ToA-derived abilities and OE port target |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: | --- | --- |
| 1 alt | Vermin | `h3_imp_upg_alt` | Alternate upgrade of Familiar line (`core:familiar`) | 3 | 3 | 1-2 | 4 | 7 | Flying | 15 |  | 65 gold | Demonic; 25% Fire spell damage reduction; 25% Holy Word vulnerability; flying; blocks retaliation; strike-and-return. |
| 2 alt | Amalek | `h3_gog_upg_alt` | Alternate upgrade of Magog line (`core:magog`) | 6 | 6 | 2-4 | 18 | 6 | Ground | 8 | 24 | 175 gold | Demonic; 25% Fire spell damage reduction; 25% Holy Word vulnerability; shooter; casts Basic Inferno at 30% power, 3 casts. Port as an explicit creature spell/focus action, not as an implied Magog Fireball shortcut. |
| 3 alt | Fire Hound | `h3_hell_hound_upg_alt` | Alternate upgrade of Cerberus line (`core:cerberus`) | 10 | 8 | 2-7 | 25 | 7 | Ground | 5 |  | 250 gold | Demonic; 25% Fire spell damage reduction; 25% Holy Word vulnerability; three-headed attack; two-hex fire-breath attack. Keep separate from Cerberus no-retaliation unless added by implementation design later. |
| 4 alt | Gore Demon | `h3_demon_upg_alt` | Alternate upgrade of Horned Demon line (`core:hornedDemon`) | 12 | 10 | 7-9 | 35 | 8 | Ground | 4 |  | 350 gold | Demonic; 25% Fire spell damage reduction; 25% Holy Word vulnerability; jousting bonus of 3 per traveled hex. |
| 5 alt | Pit Spawn | `h3_pit_fiend_upg_alt` | Alternate upgrade of Pit Lord line (`core:pitLord`) | 14 | 12 | 13-17 | 45 | 8 | Ground | 3 |  | 700 gold | Demonic; 25% Fire spell damage reduction; 25% Holy Word vulnerability; casts Basic Meteor Shower at 75% power, 2 casts. This does not replace Pit Lord Summon Demons. |
| 6 alt | Efreet Sufi | `h3_efreeti_upg_alt` | Alternate upgrade of Efreet Sultan line (`core:efreetSultan`) | 18 | 12 | 16-24 | 90 | 14 | Flying | 2 |  | 1200 gold | Demonic; 25% Holy Word vulnerability; flying; Fire Magic immunity; natural Fire Shield 20%; hates Genies, Master Genies, and Genie Viziers for 150% damage; 3 casts of a random Advanced negative spell at 6 enchant power: Disrupting Ray, Slow, Sorrow, Curse, Misfortune, or Weakness each weighted 15%, Blind weighted 10%. Port as an explicit active spell action with clear target rules; do not hide the random spell selection behind an on-hit proc. |
| 6 branch base | Hell Steed | `h3_hell_steed` | Extra level-6 Inferno branch; upgrades to Nightmare or Hell Stallion | 15 | 15 | 18-22 | 100 | 7 | Ground | 2 |  | 1100 gold | Demonic; 25% Holy Word vulnerability; 50% Fire spell damage reduction; natural Fire Shield 15%. |
| 6 branch upg | Nightmare | `h3_nightmare` | Upgrade of Hell Steed; cross-upgrades with Hell Stallion | 19 | 15 | 22-26 | 110 | 9 | Ground | 2 |  | 1500 gold | Demonic; 25% Holy Word vulnerability; 50% Fire spell damage reduction; death stare strength 10; fear-related source text has 10% Fear chance and Fear immunity. In OE, implement chance-on-hit/fear proc as a guaranteed focus-point active that applies the same Fear target/effect as practical; keep Fear immunity passive. |
| 6 branch upg alt | Hell Stallion | `h3_hell_stallion` | Alternate upgrade of Hell Steed; cross-upgrades with Nightmare | 17 | 17 | 20-24 | 120 | 9 | Ground | 2 |  | 1500 gold | Demonic; 25% Holy Word vulnerability; Fire Magic immunity; natural Fire Shield 20%; two-hex fire-breath attack; aura causing enemy units to take 25% more damage from Fire Wall, Fireball, Land Mine, Armageddon, and Inferno. |
| 7 alt | Arch Demon | `h3_devil_upg_alt` | Alternate upgrade of Arch Devil line (`core:archDevil`) | 20 | 30 | 30-50 | 250 | 16 | Teleporting | 1 |  | 5000 gold + 2 mercury | Demonic; 25% Fire spell damage reduction; 25% Holy Word vulnerability; teleports; blocks retaliation; enemy Luck -1 battle-wide; king value 2; hates Angels, Archangels, and Seraphim for 150% damage; casts Advanced Gate Demons at 200% power, 1 cast. This is a creature spell and must not replace the separate Inferno faction-skill `Gating` proposal or Pit Lord Summon Demons. |

### Alternate-Upgrade Implementation Rules

- Target unit SIDs follow the normal faction-plan convention for direct alternates (`*_upg_alt`) where the ToA row is an alternate of a HoMM3 upgraded line. The Hell Steed/Nightmare/Hell Stallion rows are a distinct extra level-6 branch because ToA provides `lvl6Alt2Base`, `lvl6Alt2Upg1`, and `lvl6Alt2Upg2` rows instead of a simple Efreet alternate.
- Any percentage-based chance to proc on hit from HoMM3, HotA, or ToA must be converted to a guaranteed focus-point-costing active ability in Olden Era while preserving the source target and effect strength as closely as practical. Do not ship hidden random on-hit versions as shortcuts.
- Spellcaster rows with explicit cast counts should become explicit creature spell/focus actions with honest UI text. If OE cannot express the target, power, or cast accounting in data, mark the row `static_trace_required` instead of weakening the behavior.
- Fire rules are row-specific: Fire spell damage reduction, Fire Magic immunity, Fire Shield reflection, two-hex fire breath, and Fire-vulnerability aura are separate mechanics and should not be implemented through one generic "fire unit" shortcut.
- Hate targets must include the ToA alternate enemy rows where listed: Efreet Sufi hates `genieVizierAU`, and Arch Demon hates `seraphAU`.

## Unique Faction Mechanics

- `Gating`: Olden Era faction skill candidate, modeled after a native summon flow only after static trace confirms target hex, duration, scaling, ownership, stack construction, and AI behavior.
- `Pit Lord Summon Demons`: HoMM3 creature mechanic and separate from faction Gating. It must produce Demons from dead allied living stacks using the exact formula.
- `Castle Gate`: HoMM3 town mechanic and separate from combat summons. Keep as static-trace debt until actual town-to-town transfer is implemented.
- Chance, hidden proc, and vague fire/drain effects should be specified into deterministic data or explicit trace debt before manifest generation.

## Static Trace And Design Debts

- Familiar Magic Channel: enemy spell-cast event, spell point cost, rounding down, non-cumulative stack rule, living Familiar check, hero mana cap/write behavior.
- Magog Fireball Attack: HotA empty-hex targeting, own/adjacent hex restriction, Bow of the Sharpshooter exception, surrounding-hex area damage, friendly fire, fire immunity central-hex exception, Preemptive Shots interaction if relevant.
- Cerberus 3-headed attack: target-left-right hex selection by attack direction, no double damage to size-2 creatures, no enemy retaliation, Lucky/Unlucky Strike direct-target-only behavior.
- Pit Lord Summon Demons: dead allied living stack targeting, 50 HP per Pit Lord capacity, Demon HP divisor 35, result capped by original dead count, Cursed Ground block, Clone and multiple Pit Lord stack interactions.
- Efreet/Efreet Sultan: Fire Magic immunity, natural Basic Fire Shield, Fire Shield stacking priority, hate-vs-Genies damage.
- Devil/Arch Devil: teleport movement to any battlefield hex, no enemy retaliation, HotA enemy Luck reduction amount and lifecycle, hate-vs-Angels damage.
- Castle Gate: owned Inferno town discovery, garrison transfer, upgrade logistics, session persistence, multiplayer safety.
- Brimstone Stormclouds and Order of Fire: source exact HoMM3 behavior and map to native building effects before implementation.
