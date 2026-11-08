# Custom Faction Building Debt Audit - 2026-05-22

Scope: live `Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data/StreamingAssets/Core.zip`, `DB/objects_logic/cities/homm3_*_city.json`, and `Lang/english/texts/cities.json`.

Follow-up fix pass: `tools/release_port/apply_release_core_overlay.py` now owns the corrected mechanics/text, with Tower's loose language overlay normalized in `experiments/homm3_tower/generated_core_overlay/Lang/english/texts/cities.json`.

Localization verification:

- Checked 10 custom faction city files.
- Checked 199 `Build_*` city-building rows.
- Checked 1032 `names` / `descriptions` / `narrativeDescriptions` token references.
- Missing city-building localization tokens: 0.
- Post-fix unsupported wording scan for `when implemented`, `does nothing`, ship/boat purchase text, `water maps`, and coastal/water-route claims: 0 hits in custom building text.

Important caveat: city buildings are not one generic JSON shape. Rows without a `bonuses` array can still be functional through their section-specific fields, such as `viewRadius`, `trainingStats`, `sideBonuses`, `cityBonuses`, `conversionPairs`, `resArr`, `levelStep`, `extraChargePurchase`, `extraChargeSell`, and `itemsCountPerRarity`. Do not classify a building as broken until those fields and the section name are checked.

## Fixed Or Reclassified In This Pass

These rows were either genuinely missing behavior or had misleading text. The packed `Core.zip` now has a concrete native payload or text that matches the existing native section behavior.

| Faction | Building SID | Current name | Current behavior/text |
| --- | --- | --- | --- |
| Castle | `Build_Intelligence_Academy` | Watchtower Academy | `intelligences` row with `viewRadius`; text says it increases town sight radius |
| Castle | `Build_Training_Range` | Training Grounds | `trainingRanges` row with `trainingStats`; text says heroes train primary stats for Gold |
| Castle | `Build_Golden_Calf` | Colossus | `graals` row with `sideBonuses` and `cityBonuses`; text says grail resources/growth |
| Conflux | `Build_Bank` | Magic University | `heroStat spellPower +1`; text no longer claims unimplemented magic-school purchase UI |
| Cove | `Build_Artifact_Market` | Quartermaster's Wharf | `artifactMarkets` row with artifact market pricing/count fields; text no longer claims ship purchase |
| Cove | `Build_Bank` | Thieves' Guild | `sideRes gold +1000`; text says it produces Gold through informants |
| Cove | `Build_Intelligence_Academy` | Smuggler's Lookout | `intelligences` row with `viewRadius`; text says it increases town sight radius |
| Cove | `Build_Training_Range` | Boarding Yard | `trainingRanges` row with `trainingStats`; text says heroes train primary stats for Gold |
| Cove | `Build_Golden_Calf` | Lodestar Vault | `graals` row with `sideBonuses` and `cityBonuses`; text says grail resources/growth |
| Dungeon | `Build_Gymnasium` | Gymnasium | Native `heroExp` row; text says it grants experience |
| Dungeon | `Build_Lyceum` | Lyceum | Native artifact-changing row; text says it allows supported artifact-changing actions |
| Dungeon | `Build_Spy_Network` | Guardian of Earth | `graals` row with reveal/growth behavior; text says grail reveal/growth |
| Fortress | `Build_Artifact_Market` | Dockside Arsenal | `artifactMarkets` row; text says artifact purchase from marsh quartermasters, not ships |
| Fortress | `Build_Bank` | Cage of Warlords | `heroStat defence +1`; generator marks source/debt metadata |
| Fortress | `Build_Treasury` | Field Infirmary | `heroStat intelligence +1`; generator marks no-war-machine substitution metadata |
| Fortress | `Build_Mother_Nature` | Glyphs of Fear | `heroStat moral +1`; generator marks source/debt metadata |
| Fortress | `Build_Mycelium_Roots` | Hydra Marsh | `cityUnitsIncrement h3_hydra +1`, `h3_hydra_upg +1`; generator marks source/debt metadata |
| Inferno | `Build_Bank` | Castle Gate | `sideRes gold +1000`; text says gate tolls, not teleport/travel behavior |
| Inferno | `Build_Beelzebubs_Hand` | Beelzebub's Hand | `heroStat offence +2`; text says visiting heroes gain +2 Attack |
| Inferno | `Build_Rebirth_Of_Shrine` | Rebirth Shrine | Native row with `resArr` and `levelStep`; text says supported Rebirth Shrine actions |
| Inferno | `Build_Eternal_Flame` | Eternal Flame | `graals` row with attack/growth bonuses; text says attack/growth |
| Necropolis | `Build_Well_Of_Souls` | Well of Souls | Native `manaFountains` row; text says native soul well city action |
| Necropolis | `Build_Skeleton_Converter` | Skeleton Converter | Native `unitsConverters` row with `conversionPairs`; text says supported conversion |
| Necropolis | `Build_Gaping_Maw` | Soul Prison | `graals` row with defense/growth bonuses; text says defense/growth |
| Rampart | `Build_Artifact_Market` | Treasury | `artifactMarkets` row; text says artifact purchase from Rampart merchants |
| Rampart | `Build_Bank` | Mystic Pond | `sideRes gold +1000`; text says enchanted spring rites, not random resources |
| Rampart | `Build_Mother_Nature` | Fountain of Fortune | `heroStat spellPower +2`; text says visiting heroes gain +2 Spell Power |
| Tower | `Build_Bank` | Capitol Vault | `sideRes gold +1000`; Tower overlay text now states the actual income effect |
| Tower | `Build_Intelligence_Academy` | Library | `intelligences` row with `viewRadius`; Tower overlay text now states sight radius |
| Tower | `Build_Training_Range` | Workshop Yard | `trainingRanges` row with `trainingStats`; Tower overlay text now states stat training |
| Tower | `Build_Golden_Calf` | Skyship Beacon | `graals` row with `sideBonuses` and `cityBonuses`; text says grail resources/growth |

## Creative Substitutions Made

Olden Era currently has no water gameplay path, and several HoMM3 buildings depend on ships, coastal maps, war-machine purchase UI, or custom school-purchase behavior. Instead of leaving placeholders or fallbacks, these were changed to modest native effects that work now.

| Source concept | Replacement | Reason |
| --- | --- | --- |
| Cove Shipyard | `Quartermaster's Wharf`, artifact market access | Keeps Cove flavor without claiming ship creation or water traversal |
| Fortress Shipyard/Dock text | `Dockside Arsenal`, artifact market access | Keeps the dock/marsh visual compatible with artifact-market behavior |
| Castle Lighthouse wording | `Signal Beacon` | Avoids coastal/water claims for a non-water game state |
| Fortress First Aid Tent/war-machine Blacksmith slot | `Field Infirmary`, `heroStat intelligence +1` | Uses a small native hero-stat bonus until a real war-machine purchase path is traced |
| Fortress Blood Obelisk/garrison lore | `Hydra Marsh`, Hydra-line growth +1 | Gives Fortress a visible, faction-relevant growth bonus without overpowering tier 7 production |
| Fortress Glyphs of Fear | `heroStat moral +1` | Small native morale reward instead of vague garrison-strengthening text |
| Conflux Magic University school learning | `heroStat spellPower +1` | Keeps a magic-training identity without custom school-purchase UI |
| Inferno Castle Gate teleport/travel | `sideRes gold +1000` gate tolls | Avoids unimplemented travel behavior while preserving a useful economy building |
| Rampart Mystic Pond random resources | `sideRes gold +1000` spring rites | Uses proven bank behavior instead of unsupported random resource behavior |
| Rampart Fountain of Fortune siege/luck flavor | `heroStat spellPower +2` | Modest, visible hero benefit using a proven native stat path |
| Tower Library spell expansion | `viewRadius` scholarship | Matches the existing `intelligences` section without claiming spell-list expansion |
| Tower Lookout/scouting text | `Workshop Yard`, stat training | Matches the existing `trainingRanges` section and avoids vague scouting claims |

## Remaining Building Debt

These are still intentionally tracked as debt or hook territory.

- Stronghold Escape Tunnel / Freelancer's Guild: **not** unfinished placeholder rows. As of the source_mechanics contract they are `substituted` (`Build_Spy_Network` and `Build_Bank`) with forbidden HotA player text. Exact siege escape and creature-for-resource sale remain unmatched HotA identity if someone later wants true parity hooks.
- Stronghold Ballista Yard / OE war-machine purchase: no proven city war-machine purchase path; Stronghold has no Ballista Yard `source_mechanics` row. Treat authentic purchase as still open.
- Several implemented custom rows still carry generator-side debt metadata for costs, prerequisites, build-tree slots, or exact source semantics that remain donor-shaped pending deeper town-construction generation. Final player Core must stay clean under `--no-design-debt`.

## Agent Notes

- Do not "fix" a misleading building by only renaming it or remapping art. Behavior follows the city section and payload fields; visual layer mappings and localization are not behavior.
- Do not scan only for `bonuses`. Check section-specific fields before declaring a row inert.
- Do not reintroduce water/ship text while Olden Era has no water gameplay. Use generator-owned, land-safe substitutions and document the design choice.
