# Custom faction law proposals: vanilla effect match pass

Generated: 2026-06-13

Inputs:
- `docs/olden_era_vanilla_effect_text_reference.md`
- local generated law-divergence matrix output from the same analysis pass (not committed; generated artifact)

Scope: compare the proposed custom-faction law concepts against vanilla English effect text only. This is not a technical feasibility pass and does not judge balance. It asks whether the proposed gameplay meaning already has a vanilla effect, can be assembled from vanilla effect building blocks, or needs a custom hook/mechanic.

Read note: the vanilla reference is large enough that raw terminal output truncates, so it was consumed with a local parser over the full file. No web or broader mechanics notes were used for this pass.

## Status legend

- `Direct`: a vanilla effect or law already expresses substantially the same gameplay kind.
- `Composite`: vanilla has the relevant building blocks, but the exact trigger, filter, scaling, or target set is new law glue.
- `Custom`: no close vanilla effect text match was found in the reference; expect a new hook or a clearer rewrite.
- `Keep`: current/baseline Castle behavior or an intentionally unchanged law.

## Frequently useful vanilla anchors

| Anchor | Vanilla text precedent |
|---|---|
| `fraction_law_human_2` / Training: Scouting | Heroes gain Sight radius. |
| `fraction_law_nature_7` / Children of the Wild | Heroes gain sight radius and Movement points. |
| `day_17_magic_clear_view` / From a Bird's Eye | Reveals area borders, then enemy heroes, then cities. |
| `day_18_magic_farsight` / Clear Fog | Reveals selected global-map squares. |
| `night_17_magic_read_minds` / Read Minds | Reveals precise number and intentions of neutral squads, later enemy hero/city info. |
| `primal_17_magic_groundsight` / Groundsight | Reveals neutral squads, then resources, then artifacts on the global map. |
| `fraction_law_dungeon_15` / Spy Network | External buildings and structures under your control gain sight radius. |
| `Build_Spy_Network` | Completely removes fog of war. |
| `fraction_law_human_13` / Vengeful Strike | Friendly counterattacks deal more Damage. |
| `day_11_magic_masterful_parry` / Riposte | Counterattack before enemy attacks, add counterattack Damage, add counterattack charges. |
| `space_7_magic_shackles` / Shackles | Target enemies cannot counterattack. |
| `day_6_magic_cleansing_ray` / Weakening Ray | Removes enemy counterattack charges. |
| `fraction_law_human_31` / Focus is the Key | Temple creatures generate Focus at the beginning of their turn. |
| `day_7_magic_inner_light` effect text | Can generate Focus when attacking or when attacking and taking Damage. |
| `night_10_magic_silence` / Silence | Prevents abilities and Focus generation. |
| `fraction_law_human_21` / Coinage Reform | Sources of Gold produce more Gold. |
| `fraction_law_human_28` / Architect's Mastery | Can construct additional buildings daily. |
| `fraction_law_human_34`, `fraction_law_nature_30`, `fraction_law_dungeon_33`, `fraction_law_unfrozen_35` | Produce Astrology points daily. |
| `fraction_law_human_22` / Heroes of Tales | Heroes gain Morale. |
| `fraction_law_human_25` / Encouragement | Morale trigger chance increases per Morale point. |
| `avatar_of_war_passive_1` / Dreadful Presence | Reduces enemy Morale. |
| `base_class_construct`, `base_class_undead` | Construct and Undead morale behavior is neutral/limited. |
| `minos_passive_2`, `minos_passive_3` | Taking Damage increases Morale; Morale triggers give Speed/Attack/Defense. |
| `day_2_magic_sharp_edge` / Blessing | Basic attacks deal more Damage. |
| `day_4_magic_favorable_wind` / Favorable Wind | Ranged and Long Reach attacks deal more Damage. |
| `night_11_magic_vulnerability` / Vulnerability | Target takes more Damage from all sources. |
| `day_3_magic_haste` / Haste | Adds Speed. |
| `space_14_magic_doreaths_tide` / Doreath's Tide | Friendly Speed/Initiative up, enemy Speed/Initiative down. |
| `day_1_magic_healing_water` / Healing Water | Restores HP, with mass and repeat variants. |
| `primal_10_magic_primordial_purity` / Anti-Magic | Immunity to spells of a tier and lower. |
| `neutral_magic_pocket_dimension` / Pocket Dimension | Creates a temporary Remote Foothold entrance. |
| `neutral_magic_dimension_door` / Dimension Door | Teleports hero within target radius. |
| `space_17_magic_reinforcements` / Reinforcements | Interact with controlled external dwellings in range. |
| `change_use_necromancy` / Necromancer Will | Toggles raising Undead vs restoring Necromantic Energy. |
| `lich_passive_1` / Unlife, Undeath | Attacks restore a percentage of Damage dealt as HP. |
| `lich_ability_1` / Rewind Death | Restores HP and can revive fallen units. |
| `lich_dragon_passive_1` / Bone Absorption | Absorbs corpses for ability Damage and HP-restored bonuses. |
| `vampire_ability_2` / Corpse Explosion | Uses a corpse for area Damage and friendly HP restore. |
| `base_passive_blink`, `space_6_magic_blink` | Teleport/blink movement. |
| `phoenix_ability_1`, `ent_ability_1`, `qilin_ability_1`, `aqualotl_ability_1` / elemental Awaken effects | Fire/Air/Earth/Water-flavored stat and immunity precedents exist, but not faction-wide army-composition laws. |

## By proposed law row

### Hero sight radius

| Faction | Proposal | Status | Vanilla match finding |
|---|---|---:|---|
| Castle | Road Wardens | Composite | Generic sight is direct via `fraction_law_human_2`; road-only sight is new map-state glue. |
| Cove | Sea Charts | Composite | `primal_17_magic_groundsight` covers neutral/resources/artifacts and `night_17_magic_read_minds` covers neutral intentions. Treasure caches, pirate hideouts, high-value camp filters, and proximity to Cove structures are custom. |
| Dungeon | Deep Scouts | Direct | This is essentially `night_17_magic_read_minds`: precise number and intentions of neutral squads. |
| Fortress | Marsh Sense | Composite | Owned-structure sight radius matches `fraction_law_dungeon_15`; enemy hero reveal matches `day_17_magic_clear_view`. Start-of-turn reveal near Fortress/swamp structures is custom glue. |
| Rampart | Avenger's Trail | Custom | Enemy hero reveal exists, but marked/favored-enemy tracking and last-known-location behavior do not appear in vanilla effect text. |
| Tower | Observatory Network | Composite | Artifact/resource reveal matches `primal_17_magic_groundsight`; local reveal matches `day_18_magic_farsight`. Owned Tower/observatory network targeting is custom. |
| Conflux | Planar Attunement | Custom | Elemental sites and dominant elemental family are not vanilla law concepts in the reference. Use `space_17_magic_reinforcements` for external dwelling interaction only as a partial anchor. |
| Inferno | Hellgate Omens | Composite | `neutral_magic_pocket_dimension`, `neutral_magic_dimension_door`, and `space_17_magic_reinforcements` cover footholds, teleportation, and dwellings. Revealing known hellgate/summoning-network objects is custom. |
| Necropolis | Gravesight | Composite | Corpse and death mechanics exist in combat text, but graveyards, recent battle sites, and corpse-rich map-location reveal need custom map-object logic. |
| Stronghold | War Scouts | Composite | `night_17_magic_read_minds` and `primal_17_magic_groundsight` reveal neutrals. Filtering by Easy/Very Easy strength and current area is custom. |

### Hero primary-stat training replacements

| Faction | Proposal | Status | Vanilla match finding |
|---|---|---:|---|
| Castle | Officer Corps | Composite | Morale and morale-trigger laws exist (`fraction_law_human_22`, `fraction_law_human_25`), and Damage buffs exist (`day_2_magic_sharp_edge`). Damage per Morale point is custom. |
| Cove | Burning Ash | Composite | Defense reduction per attack is close to `blade_dancer_passive_1` and Vulnerability-style debuffs; gunpowder attacker filtering is custom. |
| Dungeon | Predator's Instruction | Composite | `night_11_magic_vulnerability` covers increased Damage taken. The isolated/not-adjacent-to-ally condition is custom. |
| Fortress | Hidebound Drill | Composite | Negative effects are common; Damage reduction has many precedents. Reducing enemy outgoing Damage only while they have any negative status is custom. |
| Rampart | Avenger's Tutelage | Composite | Vulnerability/marked effects exist (`night_11_magic_vulnerability`, `night_14_magic_nairas_kiss`), but Avenger-specific marking and scaling are custom. |
| Tower | Arcane Calibration | Composite | Temporary Attack/Defense buffs exist (`lightweaver_buff_1`, `locust_selfbuff`, `fraction_law_human_26`). Triggering and stacking them from each hero spell cast is custom. |
| Conflux | Elemental Aspect | Composite | Individual elemental creature precedents exist: Fire max Damage, Earth durability/counterattack, Air Speed/Swift Strike, Water HP/ranged freedom. Applying family-wide stat rules by elemental family is custom. |
| Inferno | Infernal Ascension | Composite | Damage buffs are direct via Blessing-style effects; summoned/temporary stack mechanics exist. Gated-unit identity and entry-time buff are custom. |
| Necropolis | Corpse Wisdom | Composite | Corpse mechanics and mana restoration both exist, but temporary mana per battlefield corpse per round is custom. |
| Stronghold | Berserker Charge | Composite | Speed buffs exist (`day_3_magic_haste`), and damage-taken triggers exist (`minos_passive_2`). Checking below-max-health on friendly units is custom. |

### Counterattack doctrine

| Faction | Proposal | Status | Vanilla match finding |
|---|---|---:|---|
| Castle | Shield Wall | Keep | Current counterattack-damage doctrine is directly covered by `fraction_law_human_13` and `day_11_magic_masterful_parry`. |
| Cove | Boarding Hooks | Composite | Focus generation exists from turn, attack, damage, death, and kill triggers. Counterattack-specific Focus generation is not a vanilla text match. |
| Dungeon | Outnumber | Custom | Counterattack Damage exists, but comparing unit counts between stacks was not found in vanilla effect text. |
| Fortress | Thorned Hides | Composite | Attack reduction/steal by attacks exists (`avatar_of_war_passive_2`). Applying it only from counterattacks is custom. |
| Rampart | Avenger's Reprisal | Composite | Counterattack Damage and Vulnerability are direct; Avenger mark filtering is custom. |
| Tower | Reactive Wards | Composite | `fraction_law_human_26` converts hero Spell Power/Knowledge into Attack/Defense-style creature stats. Using Spell Power as Attack only for counterattacks is custom. |
| Conflux | Elemental Backlash | Composite | Damage when attacked and extra attack/counterattack Damage exist (`black_dragon_ability_2`, `frostworm_rider_passive_3`). Elemental magic scaling by stack strength is custom. |
| Inferno | Hellfire Reprisal | Direct | Additional counterattack charges are directly covered by `day_11_magic_masterful_parry`, `base_passive_aware_1` / Alert I, `base_passive_aware_2` / Alert II, and `base_passive_double_counterattack`. |
| Necropolis | Death Grip | Composite | Damage-to-HP restoration and revive effects exist (`lich_passive_1`, `lich_ability_1`). Counterattack-only drain and cap-to-original-stack require custom glue. |
| Stronghold | Blood Feud | Composite | Stacking combat buffs exist in several unit effects, and counterattack triggers exist. Applying a stacking Damage bonus after successful counterattacks is custom. |

### Melee and ranged formations

| Faction | Proposal | Status | Vanilla match finding |
|---|---|---:|---|
| Castle | Line Doctrine | Keep | The vanilla-style melee/ranged formation scaffold already has direct law precedents. |
| Cove | Boarding Parties / Gun Decks | Composite | Shooter bonuses match `day_4_magic_favorable_wind`, Double Shot, Countershot, and Piercing Shot. Cannon/gunpowder and first-volley/adjoining-pirate logic are custom. |
| Dungeon | Kill Corridors | Composite | Boxed/disabled/unable-to-retaliate play can use Shackles, Weakening Ray, Vulnerability, and control spells. Flanking/boxed-state checks are custom. |
| Fortress | Bog Line | Composite | Slows, poison, counterattack, and defensive buffs exist. Being attacked/surrounded/fighting slowed enemies as a formation package is custom. |
| Rampart | Hunter Pairs | Composite | Loyal Protector covers adjacent protection, and ranged buffs exist. Shooter exploitation of marked/favored enemies is custom. |
| Tower | Battle Automata | Composite | Construct class behavior exists, as do spell-triggered buffs and ranged buffs. Intercept, overcharge, reload, and prime-unit machinery are custom. |
| Conflux | Elemental Conjunction | Custom | Mixed elemental composition is not represented by vanilla effect text, though individual elemental effects exist. |
| Inferno | Hellpack Assault | Composite | Summons, teleport/blink, fire/burning, and ranged marks exist. Gating/teleport adjacency as the formation trigger is custom. |
| Necropolis | Death March | Composite | Undead morale, curses, corpse interactions, and HP restoration exist. Slow aura pressure/death-cloud formation behavior is custom. |
| Stronghold | Warband Crush | Composite | Movement, kills, Defense reduction, and Vulnerability effects exist. Forward-movement/kills as formation-state triggers are custom. |

### Gold income percent replacements

| Faction | Proposal | Status | Vanilla match finding |
|---|---|---:|---|
| Castle | Prosperous Holdings | Keep | Directly covered by `fraction_law_human_21`: sources of Gold produce more Gold. |
| Cove | Prize Shares | Composite | Gold-source scaling exists; rewards from plunder, treasure objects, creature banks, and defeated neutral stacks need custom reward-event hooks. |
| Dungeon | Subjugated Mines | Composite | Mine/resource production exists generally, but raising mine income after defeating guards or conquering underground sites is custom. |
| Fortress | Marsh Rights | Custom | Defensive-win income, native-terrain control income, and swamp-structure income were not found as vanilla text effects. |
| Rampart | Preservation Tithe | Custom | Low-loss victory income and marked-enemy kill income were not found. |
| Tower | Transmutation Ledger | Composite | Marketplace/resource trading and build discounts exist; automatic rare-resource-to-gold or discount conversion is custom. |
| Conflux | Elemental Market | Custom | Economy based on elemental-family mix is not a vanilla text match. |
| Inferno | Soul Contract | Composite | Death/summon/sacrifice concepts exist, but converting sacrifices, summoned losses, or fire kills into economy is custom. |
| Necropolis | Mortuary Accounting | Composite | Casualty/corpse concepts exist, but Gold from casualties or corpse-site economy is custom. |
| Stronghold | Spoils Ledger | Custom | Aggression/clearing/conquest momentum income was not found in vanilla effect text. |

### Morale and morale triggers

| Faction | Proposal | Status | Vanilla match finding |
|---|---|---:|---|
| Castle | Righteous Zeal | Keep | Directly covered by hero Morale and morale-trigger laws. |
| Cove | Crew Nerve | Composite | Kill and damage-taken morale-style triggers exist (`godslayer_passive_3`, `minos_passive_2`). Plunder/cannon/ranged-survival triggers are custom. |
| Dungeon | Terror Exploitation | Composite | Enemy morale/luck suppression and debuffs exist (`magic_despair_effect_1`, `night_4_magic_despair`, `night_11_magic_vulnerability`). Triggering bonuses from enemy morale failure is custom. |
| Fortress | Cold-Blooded Endurance | Composite | Construct/Undead neutral morale establishes non-cheering behavior; damage-taken and slow effects exist. The exact endurance trigger package is custom. |
| Rampart | Defender's Grace | Composite | Morale buffs and protector behavior exist. Preserving units/favored-enemy kills as morale triggers are custom. |
| Tower | Synchronization | Composite | Construct neutral morale and spell-triggered buffs exist. Mechanical-readiness replacing morale is custom. |
| Conflux | Elemental Harmony | Custom | Mixed-element resonance has no direct vanilla text match. |
| Inferno | Frenzy | Composite | Friendly death and kill triggers exist, and Focus on death exists. Sacrifice/gated-loss momentum is custom. |
| Necropolis | Dread | Composite | Undead morale neutrality and enemy Morale reduction (`avatar_of_war_passive_1`) are direct. Corpse value remains custom. |
| Stronghold | Rage | Composite | Damage-taken morale and kill tempo precedents exist. A general Rage resource/tempo replacement is custom. |

### Spell school access

| Faction | Proposal | Status | Vanilla match finding |
|---|---|---:|---|
| Castle | Daylight Liturgy | Keep | Daylight spell-level access is directly represented by Temple law text. |
| Cove | Storm Charts | Composite | Ranged, movement-control, and Focus mechanics exist (`day_4_magic_favorable_wind`, `space_14_magic_doreaths_tide`, Focus effects). Cannon reload interaction is custom. |
| Dungeon | Night Dominion | Direct | Night spells already cover curses, disables, Vulnerability, Despair, Silence, and finishing effects. |
| Fortress | Bog Witchcraft | Composite | Poison, slow, armor, and regeneration exist across unit/spell effects. Terrain punishment is custom. |
| Rampart | Druidic Oath | Composite | Resistance, cleanse, and regeneration have direct spell/effect anchors. Favored-enemy support is custom. |
| Tower | Prepared Artifice | Composite | Spellbook re-use exists (`druid_ability_4`), and world-map spells can have per-day use counts. Cooldown banking/prepared battle-spell charges are custom. |
| Conflux | Elemental Wheel | Custom | Dynamic school access/power by dominant elemental unit family is not represented in vanilla text. |
| Inferno | Hellfire Gatecraft | Composite | Fire, teleport, and summon spells exist. Strengthening them after sacrifice is custom. |
| Necropolis | Death Rite | Composite | Raise/drain/curse/anti-living anchors exist (`change_use_necromancy`, `lich_passive_1`, `lich_ability_1`, `lich_dragon_passive_1`, Night curses). Packaging them as school access is mostly direct; corpse gating is custom. |
| Stronghold | Warcries | Custom | Anti-Magic exists, but replacing spell access with martial command/warcry mechanics is custom. |

### Extra construction

| Faction | Proposal | Status | Vanilla match finding |
|---|---|---:|---|
| Castle | Civic Engineers | Keep | Directly covered by `fraction_law_human_28`: construct additional buildings daily. |
| Cove | Harbor Rush | Composite | Additional construction and construction discounts are vanilla law shapes. Limiting acceleration to market/tavern/cannon-yard/pirate infrastructure is custom. |
| Dungeon | Excavation Crews | Custom | Accelerating dwellings after conquering mines/caves was not found as vanilla effect text. |
| Fortress | Mudworks | Composite | Fortification buildings and construction discounts exist. Cheap moat/defensive-upgrade targeting is custom. |
| Rampart | Living Groves | Custom | Growth and dwellings exist, but dwellings maturing over days or from unit preservation is custom. |
| Tower | Grand Workshop | Composite | Extra construction exists; expensive secondary build queue for magical/construct buildings is custom. |
| Conflux | Planar Alignment | Custom | Build discount/extra builds based on elemental-family presence is not a vanilla match. |
| Inferno | Blood Mortar | Custom | Sacrificing creatures/population/resources to rush construction was not found as vanilla effect text. |
| Necropolis | Reanimated Masonry | Custom | Creature conversion exists (`Build_Skeleton_Converter`), but rebuilding ruined structures or converting captured dwellings is not a text match. |
| Stronghold | Warcamp Raising | Composite | Construction discount/list targeting is a vanilla-compatible shape; military-vs-civic acceleration is custom. |

### Astrology / calendar income

| Faction | Proposal | Status | Vanilla match finding |
|---|---|---:|---|
| Castle | Chapel Calendar | Composite | Daily Astrology point laws are direct, and Daylight/blessing spell support exists. Generating astrology progress from rituals or support-magic filtering is custom glue. |
| Cove | Storm Omens | Composite | Astrology points, Focus, ranged bonuses, and movement bonuses exist. Cannon bonuses and Focus-spent/generated omen triggers are custom. |
| Dungeon | Deep Portents | Composite | Night spell bonuses exist. Night-cycle/ambush timing is custom. |
| Fortress | Witch Signs | Composite | Poison, slow, and regeneration effects exist. Swamp omen cycle is custom. |
| Rampart | Druidic Calendar | Composite | Resistance/cleanse/regeneration effects exist. Calendar cycling them is custom. |
| Tower | Celestial Calculus | Composite | Vanilla Astrology points are direct. Prepared-spell/artifice tie-ins are custom. |
| Conflux | Planar Calendar | Custom | Elemental-family mix determining calendar bonuses is not a vanilla text match. |
| Inferno | Infernal Signs | Composite | Fire and summon/gating ingredients exist. Calendar cycling them is custom. |
| Necropolis | Death Moon | Composite | Corpse, raise, and dread ingredients exist. Calendar cycling corpse yield/raise/dread is custom. |
| Stronghold | War Festival | Custom | Rage/war-drum event cycles are not vanilla text matches. |

### Spell cooldown modifier

| Faction | Proposal | Status | Vanilla match finding |
|---|---|---:|---|
| Castle | Liturgical Rhythm | Composite | Generic spell cooldown modifier laws exist in the source matrix baseline, and support/blessing spells are direct. Restricting cooldown reduction to support/blessing spells is custom filtering. |
| Cove | Reload Drills | Composite | Focus, movement-control spells, and generic cooldown modification exist. Cannon reload and Focus-cooldown coupling are custom. |
| Dungeon | Cruel Momentum | Custom | Kills, debuffs, and disables exist; cooldown refresh after killing disabled/debuffed enemies was not found. |
| Fortress | Bog Hex | Custom | Slow/poison effects and ability/spell prevention exist, but increasing enemy cooldowns while slowed/poisoned/mired is custom. |
| Rampart | Avenger's Patience | Custom | Cleanse/resist/mark ingredients exist, but cooldown improvement from those triggers is custom. |
| Tower | Overclocked Spellworks | Composite | Spellbook re-use exists, world-map spells can have per-day use counts, and generic cooldown modifiers are close. Banked charges/prepared battle spells/cooldown conversion are custom. |
| Conflux | Aspect Cooldowns | Custom | Matching spells to dominant elemental family for cooldown/cost changes is not a vanilla match. |
| Inferno | Sacrificial Casting | Custom | Sacrifice/summon/death ingredients exist, but refreshing Fire/gating spells from those events is custom. |
| Necropolis | Corpse Fuel | Custom | Corpse and raise/drain/curse ingredients exist, but corpse-spent cooldown refresh is custom. |
| Stronghold | Spellbreaker Chants | Composite | Anti-Magic, Silence, and spellbook prevention exist. Warcry cooldown system is custom. |

## Main conclusions

- Most combat laws are `Composite`, not `Custom`: the vanilla text corpus already supports Focus, counterattacks, counterattack charges, morale triggers, negative statuses, Damage modifiers, Speed/Initiative modifiers, corpse use, HP restoration, revive, summons, spell immunity, and map teleportation.
- The biggest custom-hook burden is map-object filtering and faction-state logic: owned-structure networks, last-known enemy tracking, elemental-family composition, high-value camp detection, low-loss victory economy, conquest momentum, and calendar cycles.
- Cove, Tower, Conflux, Inferno, and Necropolis proposals lean hardest on custom glue because their identities are event- or state-driven rather than flat stat modifiers.
- Dungeon has several unusually good direct matches because `Read Minds`, Night curses, Silence, Vulnerability, and counterattack denial already express much of the proposed play pattern.
- Fortress proposals mostly have vanilla ingredients but few exact vanilla triggers; they should be implemented as coherent status/terrain/endurance hooks rather than as renamed flat Defense laws.

## Suggested implementation triage

| Tier | Meaning | Candidate proposals |
|---|---|---|
| Low-risk reuse | Mostly vanilla law/effect semantics | Dungeon Deep Scouts, Inferno Hellfire Reprisal, Necropolis Dread, Castle baseline laws, broad Astrology point laws. |
| Medium custom glue | Vanilla ingredients exist, exact trigger is custom | Cove Boarding Hooks, Fortress Thorned Hides, Tower Arcane Calibration, Necropolis Death Grip, Cove Storm Omens, Tower Overclocked Spellworks. |
| High custom hook | Needs map-state, army-composition, calendar, or campaign-event logic | Rampart Avenger's Trail, Conflux Planar Attunement/Calendar/Aspect Cooldowns, Stronghold Spoils Ledger, Fortress Marsh Rights, Inferno Sacrificial Casting, Necropolis Corpse Fuel. |
