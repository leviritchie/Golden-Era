# HoMM3 Fortress Release-Quality Porting Spec

Status: release-quality specification draft for future manifest generation and implementation audit.

## Source URLs

Primary creature/stat sources:

- Fortress overview and native terrain: https://homm.fandom.com/wiki/Fortress
- Gnoll and Gnoll Marauder: https://heroes.thelazy.net/index.php/Gnoll_and_gnoll_marauder
- Lizardman and Lizard Warrior: https://heroes.thelazy.net/index.php/Lizardman_and_Lizard_Warrior
- Serpent Fly and Dragon Fly: https://heroes.thelazy.net/index.php/Serpent_Fly_and_Dragon_Fly
- Basilisk and Greater Basilisk: https://heroes.thelazy.net/index.php/Basilisk_and_Greater_Basilisk
- Gorgon and Mighty Gorgon: https://heroes.thelazy.net/index.php/Gorgon_and_Mighty_Gorgon
- Wyvern and Wyvern Monarch: https://heroes.thelazy.net/index.php/Wyvern_and_Wyvern_Monarch
- Hydra and Chaos Hydra: https://heroes.thelazy.net/index.php/Hydra_and_Chaos_Hydra

Ability definition sources:

- Petrifying attack / Stone Gaze: https://heroes.thelazy.net/index.php/Petrifying_attack
- Poisonous: https://heroes.thelazy.net/index.php/Poisonous
- Weakness: https://heroes.thelazy.net/index.php/Weakness

## Faction Defaults

| Field | Requirement |
| --- | --- |
| Faction SID | `homm3_fortress` |
| City SID | `homm3_fortress_city` |
| Native terrain | Swamp |
| Primary donor faction | `nature` for city/rural scaffolding, with unit donors chosen per exact behavior needs |
| Primary donor city | `nature_city` |
| HoMM3 classes | Beastmaster, Witch |
| OE class labels | Beastmaster, Witch |
| Mage Guild cap | Level 3 |
| Risk | Medium-high; exact mechanics include beneficial-spell dispel, advanced Weakness, petrify, death stare, poison, no-retaliation, and all-adjacent Hydra attacks. |

Identity pillars:

- Swamp defense and attrition.
- Durable beasts with disruptive status effects.
- One shooter line only.
- Low magic cap with high creature survivability.
- Hydra late-game melee control through no-retaliation and all-adjacent attacks.

## HotA Unit Stats And Abilities

These rows are the target data for Fortress units. If Olden Era cannot represent a listed field or mechanic directly, the port must record that as a static-trace/design debt and avoid claiming equivalence in UI text.

| Tier | Unit | Upgrade | Atk | Def | Dmg | HP | Spd | Move | Size | Growth | Shots | AI Value | Fight Value | Cost | HotA ability definition |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| 1 | Gnoll | Base | 3 | 5 | 2-3 | 6 | 4 | Ground | 1 | 12 (+6 with Captain's Quarters) | - | 56 | 70 | 50 gold | None. Melee ground creature. |
| 1 | Gnoll Marauder | Upgraded | 4 | 6 | 2-3 | 6 | 5 | Ground | 1 | 12 (+6 with Captain's Quarters) | - | 90 | 90 | 70 gold | None. Melee ground creature. |
| 2 | Lizardman | Base | 5 | 6 | 2-3 | 14 | 4 | Ground | 1 | 9 | 12 | 151 | 137 | 110 gold | Shooter with 12 shots; uses melee hand-to-hand behavior when adjacent/blocked by normal HoMM3 ranged rules. |
| 2 | Lizard Warrior | Upgraded | 6 | 8 | 2-5 | 15 | 5 | Ground | 1 | 9 | 24 | 209 | 174 | 140 gold | Shooter with 24 shots; uses melee hand-to-hand behavior when adjacent/blocked by normal HoMM3 ranged rules. |
| 3 | Serpent Fly | Base | 7 | 9 | 2-5 | 20 | 9 | Flying | 1 | 8 | - | 268 | 215 | 220 gold | Flying. After every attack, casts advanced Dispel on the target, removing only beneficial spells. This cannot be resisted and has no immune creatures listed by the source. |
| 3 | Dragon Fly | Upgraded | 8 | 10 | 2-5 | 20 | 13 | Flying | 1 | 8 | - | 312 | 250 | 240 gold | Flying. After every attack, casts advanced Dispel on beneficial target spells and advanced Weakness for 3 rounds. Advanced Weakness reduces Attack by 6. |
| 4 | Basilisk | Base | 11 | 11 | 6-10 | 35 | 5 | Ground | 2 | 4 | - | 552 | 506 | 325 gold | Stone Gaze / Petrifying attack: 20% chance after attack or retaliation. If it triggers on attack, the target does not retaliate. Lasts 3 combat rounds or until the petrified stack is attacked. Cure or Dispel removes it. Attacks against petrified troops deal half damage; the petrified troop retaliates at full strength when struck. |
| 4 | Greater Basilisk | Upgraded | 12 | 12 | 6-10 | 40 | 7 | Ground | 2 | 4 | - | 714 | 561 | 400 gold | Same Stone Gaze / Petrifying attack behavior as Basilisk. |
| 5 | Gorgon | Base | 10 | 14 | 12-16 | 70 | 5 | Ground | 2 | 3 | - | 890 | 890 | 525 gold | None. Melee ground creature. |
| 5 | Mighty Gorgon | Upgraded | 11 | 16 | 12-16 | 70 | 6 | Ground | 2 | 3 | - | 1028 | 1028 | 600 gold | Death Stare after attack or retaliation against living units. Each Mighty Gorgon contributes a 10% non-cumulative chance roll; maximum killed units equals 10% of the Mighty Gorgon stack size, rounded up. Death Stare kills topmost units outright and leaves the next surviving top unit at full health. |
| 6 | Wyvern | Base | 14 | 14 | 14-18 | 70 | 7 | Flying | 2 | 2 | - | 1350 | 1050 | 800 gold | Flying. |
| 6 | Wyvern Monarch | Upgraded | 14 | 14 | 18-22 | 70 | 11 | Flying | 2 | 2 | - | 1518 | 1518 | 1100 gold | Flying. Poisonous: 30% chance after attack or retaliation, before target retaliation. Cure only removes poison. Target max health drops by 10% per combat round for 3 rounds, calculated from statistical max health, cumulative to 30% per poison application and capped at 50% total max-health loss. Poison cannot kill by itself. Each stack can be applied once per round. |
| 7 | Hydra | Base | 16 | 18 | 25-45 | 175 | 5 | Ground | 2 | 1 | - | 4120 | 4120 | 2200 gold | Attacks all adjacent enemy stacks and receives no enemy retaliation. |
| 7 | Chaos Hydra | Upgraded | 18 | 20 | 25-45 | 250 | 7 | Ground | 2 | 1 | - | 5931 | 5272 | 3500 gold + 1 sulfur | Attacks all adjacent enemy stacks and receives no enemy retaliation. |

## Unit Decisions

| Tier | HoMM3 line | Target SID family | Donor direction | Required behavior | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | Gnoll -> Gnoll Marauder | `h3_gnoll` | Low-tier melee donor with one-hex ground body | Exact HotA stats, one-hex melee, no special abilities. | data_ready |
| 2 | Lizardman -> Lizard Warrior | `h3_lizardman` | Shooter donor | Exact HotA stats, shots, and ranged/melee transition rules. Lizardman has 12 shots; Lizard Warrior has 24. | data_ready |
| 3 | Serpent Fly -> Dragon Fly | `h3_serpent_fly` | Fast flyer donor with on-hit effect hooks | Flying. Serpent Fly must dispel beneficial target spells after every attack. Dragon Fly must also apply advanced Weakness for 3 rounds after every attack. | static_trace_required |
| 4 | Basilisk -> Greater Basilisk | `h3_basilisk` | Two-hex melee beast donor | Exact Stone Gaze semantics: 20% on attack/retaliation, retaliation suppression on successful attack petrify, 3-round duration, half damage while petrified, Cure/Dispel removal, immunity handling. | static_trace_required |
| 5 | Gorgon -> Mighty Gorgon | `h3_gorgon` | Two-hex tank/bruiser donor | Gorgon has no special. Mighty Gorgon's source Death Stare is a percentage on-hit proc; the OE port must expose it as a guaranteed focus-point active that preserves the living-target restriction and source kill cap, with UI text naming the deterministic focus cost. | static_trace_required |
| 6 | Wyvern -> Wyvern Monarch | `h3_wyvern` | Two-hex flyer donor | Wyvern is flying only. Wyvern Monarch source poison is a 30% on-hit proc; OE must expose it as a guaranteed focus-point active with max-health reduction, Cure-only removal, 50% total cap, and once-per-stack-per-round application. | static_trace_required |
| 7 | Hydra -> Chaos Hydra | `h3_hydra` | Hydra/no-retaliation donor if available | Exact no-retaliation plus all-adjacent enemy attack from a two-hex ground creature. | static_trace_required |

## Ability Implementation Requirements

- Serpent/Dragon Fly dispel must remove only beneficial target spells, after every attack. It must not remove negative spells from enemies.
- Dragon Fly Weakness must be advanced-level Weakness for 3 rounds; the effective attack reduction is -6 unless OE spell data proves a different internal stat mapping is required.
- HoMM3/HotA/ToA percentage on-hit or on-attack procs must not ship as hidden random passives in Olden Era. Translate them into guaranteed focus-point-costing active abilities that preserve the source legal target, duration, resist/immunity rules, and effect strength as much as practical.
- Petrifying attack source behavior is a 20% proc after attack or retaliation. OE should implement it as a focus active that applies the same 3-round petrify, retaliation suppression on the initiating strike, half-damage-while-petrified rule, and Cure/Dispel removal. UI must describe the focus action honestly, not imply a passive random proc.
- Death Stare source behavior is an after-attack/after-retaliation instant-kill proc against living units. OE should implement it as a focus active against a living target, killing up to the source cap of 10% of the acting Mighty Gorgon stack size rounded up, while preserving the full-health top-survivor rule and immunity categories.
- Poison source behavior is a 30% after-attack/after-retaliation proc. OE should implement it as a focus active that applies the same max-health reduction, Cure-only removal, 50% total cap, poison-cannot-kill rule, and once-per-stack-per-round application. If OE cannot lower max health safely, the unit is mechanically incomplete until a verified equivalent exists.
- Hydra attacks must hit all adjacent enemy stacks, not a selected cone, splash, or single-target cleave. No-retaliation applies to its attack.

## City And Economy

| HoMM3 element | Requirement | Status |
| --- | --- | --- |
| Native terrain | Swamp. | exact |
| Cage of Warlords | Visiting hero receives the Fortress-specific defense bonus if OE supports a visit structure stat grant; otherwise static-trace exact town-building bonus semantics before implementing text. | static_trace_required |
| Captain's Quarters | Gnoll and Gnoll Marauder growth +6 per week. | exact |
| Glyphs of Fear | Siege morale penalty behavior must be static-traced before implementation. | static_trace_required |
| Blood Obelisk | Exact HoMM3/HotA building effect must be confirmed before using the name or text. | design_debt |
| Resource Silo | Confirm Fortress silo yield in target source before manifest generation; do not infer from donor faction. | static_trace_required |
| Mage Guild | Cap to level 3. | exact |

Economy note: Fortress should remain wood/ore and growth oriented, with lower rare-resource pressure than Tower or Dungeon. Exact building costs should be copied from HotA building data when the city manifest is generated.

## Laws And Faction Skill

Faction skill: `Hunting Grounds` (`skill_faction_homm3_fortress`). It replaced the Swamp Tactics candidate on 2026-10-12, by user decision.

- Each battle won adds a Trophy. Lost sieges and retreats do not count.
- The cap is 8/7/6 at Basic/Advanced/Expert. Reaching it restocks, once per week, the weekly event banks (`visitorsResetType: OnStartWeek`) the hero visited this week, by calling each bank's native `OnStartWeek`. The meter then stays capped until the week turns.
- The enemy penalty creeps up with the Trophy count, battle-wide:
  - Basic: -1 Initiative at 3, -1 Speed at 6.
  - Advanced: -1 Initiative at 2, -1 Speed at 5.
  - Expert: -1 Initiative at 2, -1 Speed at 4, -2 Initiative at 6.
- The penalty is carried by the 21 Core hero buffs `homm3_fortress_trophies_{rank}_{n}`: `unitStat` with `receiverAllegiance: enemy`, duration `UntilNextWeek`, `isDispellable`. The skill ranks carry only the runtime-owned load shape (`ignoreFractionsCount`) and the subskills.
- Creature dwellings are excluded. They use the weekly growth model, not visitor lists.
- Owner: `Homm3FortressHuntingGroundsHook`. Battle wins come through the shared battle-result prefix. Visits and the week turn bind `GameSymbols.FortressHuntingGrounds`.
- Open runtime proof:
  - enemy-allegiance `unitStat` on hero buffs;
  - `UntilNextWeek` expiry;
  - bank restock visuals.

Potential law/subskill themes, all requiring concrete design before implementation:

- Gnoll muster: growth or cost pressure for Gnoll/Gnoll Marauder.
- Lizard patrols: shooter durability or ammunition support.
- Fly swarm: Serpent/Dragon Fly initiative or dispel support.
- Basilisk pens: Stone Gaze duration/effect support only if the petrify hook exists and the base creature focus action is already honest.
- Gorgon herd: defensive scaling for Gorgon/Mighty Gorgon.
- Wyvern venom: poison support only if max-health poison exists.
- Hydra marsh: Hydra growth, placement, or multi-target support only if it does not change the base HotA behavior contract.

## Heroes

- Clone Nature or Dungeon hero scaffolding only as scaffolding. Normalize class labels, portraits, specialties, starting armies, and faction-skill references to Fortress IDs.
- Every generated Fortress hero `specialization` id must have a matching row in `DB/heroes_specializations/specializations_homm3_fortress.json`. The session loader resolves specialization configs during `Hex.Session.Logic.Hero`; missing rows such as `homm3_fortress_hero_1_specialization` abort map/session load before UI fallback text can help.
- Beastmaster heroes should skew Might/Defense and unit specialties.
- Witch heroes should use existing OE spell SIDs while respecting Mage Guild level 3.
- Unit specialists should map to actual Fortress unit families: Drakon (Gnolls), Wystan (Lizardmen), Korbac (Serpent/Dragon Flies), Bron (Basilisks, including starting Basilisks), Alkin (Gorgons), Broghild (Wyverns).

## Town Art

- Fortress town is high placement workload because of swamp waterline, depth layering, and low building silhouettes.
- Generate layers from source assets, then manually review every dwelling, fortification, waterline, and animation origin.
- Visual swamp layers are presentation only; native terrain and movement behavior must come from faction/map data.

## Asset Deployment

- Fortress release asset deployment is required in addition to Core.zip overlay work. The source plugin already has Fortress unit import rows, custom unit bundles including ToA alternates, static unit portraits, preview manifests, lab sidecars, faction icon/card art, town reference assets, and city/dwelling map-object reference frames.
- `tools/deploy_homm3_fortress_assets.py` is the current Fortress deployment lane. Keep using it to validate and deploy the payload, but do not describe unit bundles/import rows/static portraits as the current blocker unless validation regresses. Remaining hardening is hero portraits when available, town/build-tree release quality, UI registry/selector exposure, and mechanics validation.
- The Fortress town card/backdrop source is HoMM3 `H3bitmap.lod` member `tbfrback.pcx` decoded as the custom 800x374 BGR town-scene payload. Do not use VCMI/third-upgrades `fortressHallBg.png`; that is the hall/build-tree plate.
- Add Fortress to the release custom-game/banner/icon sprite registry explicitly and verify the Steam plugin payload after build/deploy.

## Tears Of Ashan Alternate Upgrades

These `_upg_alt` rows use `docs/homm3_tears_of_ashan_creature_specs.md` as the canonical source. They are additional Fortress upgrade branches and must not replace or weaken the HotA base/upgraded creature rows above.

| Tier | Target SID | ToA name | Upgrades from | Atk | Def | Dmg | HP | Spd | Move | Growth | Shots | Cost | OE ability requirements |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: | --- | --- |
| 1 | `h3_gnoll_upg_alt` | Gnoll Shaman | `h3_gnoll` / `core:gnollMarauder` | 3 | 7 | 2-3 | 6 | 5 | Ground | 12 | - | 70 gold | Two casts total. Active spell choice between Advanced Curse and Advanced Weakness at 6 power; ToA source gives each a 50% cast choice, but OE must expose deterministic selectable focus/spell actions or an explicitly described deterministic choice flow. |
| 2 | `h3_lizardman_upg_alt` | Lizard Assassin | `h3_lizardman` / `core:lizardWarrior` | 8 | 6 | 3-5 | 15 | 8 | Teleporting shooter | 9 | 24 | 170 gold | Shooter with limited range 10, teleport movement, and poison after attack in source. OE poison must be a guaranteed focus active preserving ToA Poison target/effect instead of a hidden on-hit proc. |
| 3 | `h3_serpent_fly_upg_alt` | Damsel Fly | `h3_serpent_fly` / `core:fireDragonFly` | 9 | 9 | 2-5 | 20 | 11 | Flying | 8 | - | 240 gold | Flying, strike-and-return, and guaranteed beneficial-only Dispel after attack. Does not inherit Dragon Fly's Weakness unless separately implemented from source data. |
| 4 | `h3_basilisk_upg_alt` | Basilisk Flamespitter | `h3_basilisk` / `core:greaterBasilisk` | 14 | 10 | 6-10 | 40 | 7 | Ground | 4 | - | 400 gold | Two-hex breath attack and 50% fire spell damage reduction. Source has 20% Stone Gaze after attack; OE must make this a guaranteed focus active with Fortress petrify rules rather than a random passive. |
| 5 | `h3_gorgon_upg_alt` | Corrosive Gorgon | `h3_gorgon` / `core:mightyGorgon` | 14 | 14 | 12-16 | 70 | 7 | Ground | 3 | - | 600 gold | Two-hex breath attack plus Acid Breath source effect: after attack applies acid-breath handling with 6 source value and 30 additional value. Any chance component must be converted to a guaranteed focus active preserving acid target/effect strength as much as practical. Does not replace Mighty Gorgon's Death Stare branch. |
| 6 | `h3_wyvern_upg_alt` | Paokai | `h3_wyvern` / `core:wyvernMonarch` | 14 | 14 | 14-18 | 80 | 10 | Flying | 2 | - | 1300 gold | Flying, 40 HP regeneration, and Lightning Breath after attack hitting up to 3 enemy targets at 100% creature spell power. ToA temporary Lightning Breath immunity is explicitly marked temporary and must not be ported as permanent faction/hero immunity without a separate design decision. |
| 7 | `h3_hydra_upg_alt` | Ruinous Hydra | `h3_hydra` / `core:chaosHydra` | 18 | 24 | 25-45 | 220 | 10 | Ground | 1 | - | 4000 gold + 2 sulfur | Attacks all adjacent enemies, blocks retaliation, regenerates 55 HP, and has one additional attack. Preserve Hydra all-adjacent targeting; do not downgrade this to cone, splash, or single-target cleave. |

## Static Trace Debts

- OE representation for after-attack beneficial-only Dispel.
- OE representation for Dragon Fly advanced Weakness with fixed 3-round duration.
- Focus-active petrify based on the source Stone Gaze effect, including retaliation suppression and half-damage while petrified.
- Focus-active Mighty Gorgon Death Stare against living units, including immunity categories and kill cap.
- Focus-active Wyvern Monarch poison as max-health reduction, Cure-only removal, 50% cap, and once-per-round stack application.
- Hydra all-adjacent enemy targeting and no-retaliation behavior.
- Cage of Warlords exact visit bonus path.
- Glyphs of Fear siege morale behavior.
- Blood Obelisk exact building effect.
- Fortress Resource Silo output from a HotA building source.
