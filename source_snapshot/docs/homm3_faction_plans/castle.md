# HoMM3 Castle Release Port Spec

Status: release-quality source spec for future manifest generation and implementation audit.

## Source URLs

- Castle town and creature table: https://heroes.skywiki.org/wiki/Castle
- Tears of Ashan alternate-upgrade source rows: `docs/homm3_tears_of_ashan_creature_specs.md`
- Pikeman and Halberdier: https://homm.fandom.com/wiki/Pikeman_and_Halberdier
- Archer and Marksman: https://homm.fandom.com/wiki/Archer_and_Marksman
- Griffin and Royal Griffin: https://heroes.skywiki.org/wiki/Griffin_and_Royal_Griffin
- Swordsman and Crusader: https://homm.fandom.com/wiki/Swordsman_and_Crusader
- Monk and Zealot: https://homm.fandom.com/wiki/Monk_and_Zealot
- Cavalier and Champion: https://homm.fandom.com/wiki/Cavalier_and_Champion
- Angel and Archangel: https://homm.fandom.com/wiki/Angel_and_Archangel
- Double attack rules: https://homm.fandom.com/wiki/Double_attack
- Ranged attack rules: https://heroes.skywiki.org/wiki/Ranged_attack
- Melee penalty rules: https://homm.fandom.com/wiki/Melee_penalty
- Damage formula notes for jousting and hated-enemy modifiers: https://homm.fandom.com/wiki/Damage
- Morale rules: https://heroes.skywiki.org/wiki/Morale

## Faction Defaults

| Field | Requirement |
| --- | --- |
| Faction SID | `homm3_castle` |
| City SID | `homm3_castle_city` |
| Primary donor faction | `humans` |
| Primary donor city | `human_city` |
| HoMM3 classes | Knight, Cleric |
| OE class labels | Knight, Cleric |
| Native terrain | Grass |
| Mage Guild cap | Level 4 |
| Risk | Low-medium; resurrection, double attacks, jousting, retaliations, morale, and shooter rules require exact implementation or explicit static-trace debt. |

Identity pillars:

- disciplined human combined-arms army
- righteousness-triggered hero bonuses and morale support
- strong ranged line plus cavalry charge
- angelic late-game support

## HotA Unit Stats And Abilities

These values are the target Castle creature contract. Manifest generation and runtime hooks should treat deviations as bugs unless the deviation is documented under Static Trace Debts.

| Tier | Creature | Target SID | Atk | Def | Dmg | HP | Spd | Growth | Shots | Move | Size | AI Value | Fight Value | Cost | Required HotA abilities |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | --- |
| 1 | Pikeman | `h3_pikeman` | 4 | 5 | 1-3 | 10 | 4 | 14 | - | Ground | 1 | 80 | 100 | 60 gold | Immune to Cavalier/Champion jousting bonus. |
| 1+ | Halberdier | `h3_halberdier` | 6 | 5 | 2-3 | 10 | 5 | 14 | - | Ground | 1 | 115 | 115 | 75 gold | Immune to Cavalier/Champion jousting bonus. |
| 2 | Archer | `h3_archer` | 6 | 3 | 2-3 | 10 | 4 | 9 | 12 | Ground | 1 | 126 | 115 | 100 gold | Shooter; standard ranged and melee penalties. |
| 2+ | Marksman | `h3_marksman` | 6 | 3 | 2-3 | 10 | 6 | 9 | 24 | Ground | 1 | 184 | 115 | 150 gold | Shooter; shoots twice at range; standard melee penalty and only one melee strike when engaged. |
| 3 | Griffin | `h3_griffin` | 8 | 8 | 3-6 | 25 | 6 | 7 | - | Flying | 2 | 351 | 324 | 200 gold | Flying; retaliates against two attacks per round. |
| 3+ | Royal Griffin | `h3_royal_griffin` | 9 | 9 | 3-6 | 25 | 9 | 7 | - | Flying | 2 | 448 | 364 | 240 gold | Flying; unlimited retaliations. |
| 4 | Swordsman | `h3_swordsman` | 10 | 12 | 6-9 | 35 | 5 | 4 | - | Ground | 1 | 445 | 445 | 300 gold | No special ability. |
| 4+ | Crusader | `h3_crusader` | 12 | 12 | 7-10 | 35 | 6 | 4 | - | Ground | 1 | 588 | 588 | 400 gold | Strikes twice in melee attack. Second strike occurs after target retaliation and uses surviving attackers only. Retaliations do not double strike. |
| 5 | Monk | `h3_monk` | 12 | 7 | 10-12 | 30 | 5 | 3 | 12 | Ground | 1 | 582 | 485 | 400 gold | Shooter; standard ranged and melee penalties. |
| 5+ | Zealot | `h3_zealot` | 12 | 10 | 10-12 | 30 | 7 | 3 | 24 | Ground | 1 | 750 | 500 | 450 gold | Shooter; no melee penalty. In HotA, ranged units can choose ranged or melee attack mode. |
| 6 | Cavalier | `h3_cavalier` | 15 | 15 | 15-25 | 100 | 7 | 2 | - | Ground | 2 | 1946 | 1668 | 1000 gold | Jousting: +5% damage per hex traveled during the attacking move; no bonus on counterattack; Pikemen and Halberdiers ignore the bonus. |
| 6+ | Champion | `h3_champion` | 16 | 16 | 20-25 | 100 | 9 | 2 | - | Ground | 2 | 2100 | 1800 | 1200 gold | Jousting: +5% damage per hex traveled during the attacking move; no bonus on counterattack; Pikemen and Halberdiers ignore the bonus. |
| 7 | Angel | `h3_angel` | 20 | 20 | 50 | 200 | 12 | 1 | - | Flying | 1 | 5019 | 3585 | 3000 gold, 1 gem | Flying; hates Devils; grants non-cumulative +1 army morale through combat, retained even if the Angel stack dies. |
| 7+ | Archangel | `h3_archangel` | 30 | 30 | 50 | 250 | 18 | 1 | - | Flying | 2 | 8776 | 6033 | 5000 gold, 3 gems | Flying; hates Devils; grants non-cumulative +1 army morale through combat; once per combat resurrects allied living stack for 100 HP per Archangel, permanent, using Resurrection target restrictions. |

## Ability Semantics

- **Ranged attack:** shooters can attack from range while shots remain. Ranged attacks beyond 10 hexes use the standard range penalty unless a separate no-range-penalty effect is present. Adjacent enemies block ranged attacks and force melee unless the HotA attack-mode selector is implemented.
- **Melee penalty:** standard shooters deal half damage in melee. Zealots must not take this penalty. Marksmen still make only one melee strike while engaged.
- **Double attack:** Marksmen make two ranged attacks against the same target. Crusaders make two melee strikes when attacking; the target retaliates after the first strike, and the second strike uses only surviving Crusaders. Double attack does not apply to Crusader retaliation.
- **Retaliation count:** Griffins have two retaliations per round. Royal Griffins have unlimited retaliations. Retaliation capacity must be behaviorally implemented, not text-only.
- **Jousting:** Cavaliers and Champions add 5% damage for each hex traveled during the attack move, capped only by battlefield geometry. Counterattacks do not receive jousting. Pikemen and Halberdiers are immune to the bonus but still take normal base damage.
- **Hates Devils:** Angels and Archangels deal 150% damage when attacking Devils, and Devils deal 150% damage when attacking Angels/Archangels.
- **Angel morale:** Angel and Archangel morale bonus is +1, non-cumulative, army-wide for the battle, and persists after the Angel/Archangel stack dies.
- **Archangel resurrection:** source HoMM3 behavior is one use per combat per Archangel stack, with a revive budget of `100 * current Archangel count` HP and normal Resurrection target restrictions. OE design direction is to implement this as a 2-focus creature action using Rewind Life (`DB/magics/battle_space_magics.json` id `space_12_magic_rewind`, `targetMechanics` `revive`) instead of generic healing or an approximate revive.

## Unit Decisions

| Tier | HoMM3 line | Target SID family | Required donor shape | Release behavior requirement | Implementation status |
| --- | --- | --- | --- | --- | --- |
| 1 | Pikeman -> Halberdier | `h3_pikeman`, `h3_halberdier` | durable one-hex melee infantry | Use exact HotA stats and jousting-immunity behavior. | data_and_hook_required |
| 2 | Archer -> Marksman | `h3_archer`, `h3_marksman` | one-hex shooter | Archer is a 12-shot shooter. Marksman is a 24-shot shooter with true double ranged attack and standard one-strike melee behavior. | static_trace_required |
| 3 | Griffin -> Royal Griffin | `h3_griffin`, `h3_royal_griffin` | two-hex flyer | Griffin has exactly two retaliations; Royal Griffin has unlimited retaliations. | static_trace_required |
| 4 | Swordsman -> Crusader | `h3_swordsman`, `h3_crusader` | one-hex melee infantry | Swordsman has no special. Crusader has true HoMM3 double melee attack timing. | static_trace_required |
| 5 | Monk -> Zealot | `h3_monk`, `h3_zealot` | one-hex shooter | Monk is a 12-shot shooter with normal penalties. Zealot is a 24-shot shooter with no melee penalty and HotA attack-mode expectations if UI support exists. | static_trace_required |
| 6 | Cavalier -> Champion | `h3_cavalier`, `h3_champion` | two-hex ground cavalry | Jousting damage must use traveled hex count, not a flat charge buff. | static_trace_required |
| 7 | Angel -> Archangel | `h3_angel`, `h3_archangel` | flyer with morale/resurrection hooks | Angel morale and Devil hatred must match HotA semantics. Archangel resurrection should use a 2-focus Rewind Life action per user direction. | static_trace_required |

## City And Economy

| HoMM3 element | Release requirement | Status |
| --- | --- | --- |
| Stables | Visiting hero movement effect and free Cavalier-to-Champion upgrade require a traced OE path. Start from the external `stables` event-bank path: `DB/objects_logic/event_banks/buff_banks/stables.json` applies `HeroBuffReward stable_buff UntilNextWeek` plus `MovePointsPercentAdditionReward 0.3`; `DB/heroes_buffs/heroes_buffs.json` defines `stable_buff` with `heroStat movementPerBonus 0.20`. Free Cavalier upgrade remains a separate integration item. | static_trace_required |
| Griffin Bastion | `cityUnitsIncrement h3_griffin` growth bonus of +3 Griffins/Royal Griffins per week. | exact |
| Brotherhood of the Sword | Visiting hero morale bonus requires traced OE morale/modifier path. Start from the external Quix's Path morale path: `DB/objects_logic/event_banks/buff_banks/quixs_path.json` applies `HeroBuffReward quixs_path_buff UntilNextWeek`; `DB/heroes_buffs/heroes_buffs.json` defines `quixs_path_buff` with `heroStat moral 3`. Adapt scope/value to the Castle city visit. | static_trace_required |
| Lighthouse | Do not enable for the current OE target; user note says water does not exist yet in Olden Era. | blocked_current_release |
| Resource Silo | Castle Resource Silo produces wood and ore if OE resource rows support both. | data_required |
| Mage Guild | Cap to level 4. | exact |

Economy note: Castle costs should follow HotA/HoMM3 resource pressure, with wood and ore pressure early and gem pressure on Angels/Archangels.

## Laws And Faction Skill

Faction skill requirement: OE native `Righteousness` (`skill_faction_humans`) unless a Castle-specific skill is deliberately designed later.

- Native behavior must be described accurately in generated text.
- Castle laws should be concrete bonuses to the HotA creature contract, not substitutes for missing base creature mechanics.
- Candidate law themes: Pikeman defense/HP, Archer ranged damage, Griffin growth/retaliation support, Cavalier jousting support, Angel morale/resurrection support, Royal provisioning economy.

## Heroes

- Clone Human hero/subclass scaffolding only where Castle identity remains correct after normalization.
- Class labels: Knight and Cleric.
- Unit specialists must map to corresponding `h3_*` base and upgraded unit families.
- Ballista, First Aid Tent, and specialty war-machine heroes require OE-native attack/support specialties or explicit static-trace debt.
- Cleric spell specialists must use existing OE spell SIDs only. Do not localize non-existent spells.

## Town Art

- Generate Castle town layer map from HoMM3 town DEFs or trusted decoded source art.
- Mark all wall, stables, tower, griffin, and angel building layers as `placementReview: required` until visually verified in the release town UI.
- Keep click/hover behavior native; do not move building UI transforms unless the same transform contract is traced and tested.

## Asset Deployment

- The source plugin already has Castle unit import rows, custom unit bundles, static unit portraits, preview manifests, lab sidecars, faction icon/card art, and city/dwelling map-object reference frames. Do not keep stale "no bundles/import payload" release blocks unless validation regresses.
- Castle release hardening still needs `homm3_hero_portraits/`, town layers, build-tree icons, UI registry/selector exposure, and mechanics validation. Core.zip data alone is still not enough for visible faction UI or release readiness.
- Verify the actual HoMM3 Castle town backdrop source and building-layer source by eye. Do not use hall/build-tree UI plates or donor Human assets as the faction card/backdrop.
- Add Castle to the release custom-game/banner/icon sprite registry explicitly; do not rely on custom Core.zip icon keys to load arbitrary plugin PNGs.

## Tears Of Ashan Alternate Upgrades

These `_upg_alt` rows come from the mined Tears of Ashan Castle rows and replace older vague alternate-upgrade proposals. They are additive Castle alternates, not substitutes for the HotA base/upgraded creature contract above. Do not weaken, omit, or approximate HotA mechanics to make room for these rows.

Target SID convention: use the HoMM3 base creature family plus `_upg_alt`, while localizing the ToA creature name exactly.

| Tier | ToA creature | Target SID | Upgrades from | ToA VCMI id | Atk | Def | Dmg | HP | Spd | Growth | Shots | Cost | Required ToA abilities |
| --- | --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- |
| 1 alt+ | Glaivier | `h3_pikeman_upg_alt` | Pikeman | `glaivierAU` | 4 | 7 | 1-3 | 12 | 4 | 14 | - | 75 gold | Immune to Cavalier/Champion-style charge or jousting bonus. |
| 2 alt+ | Crossbowman | `h3_archer_upg_alt` | Archer | `crossbowmanAU` | 8 | 3 | 3-5 | 10 | 7 | 9 | 24 | 150 gold | Shooter; no range-distance penalty; no wall/obstacle penalty; attacks reduce enemy Defense by 20%. |
| 3 alt+ | Battle Griffin | `h3_griffin_upg_alt` | Griffin | `battleGriffinAU` | 10 | 8 | 3-6 | 25 | 7 | 7 | - | 240 gold | Flying; double attack/ferocity `val=1`. |
| 4 alt+ | Guardsman | `h3_swordsman_upg_alt` | Swordsman | `guardsmanAU` | 10 | 14 | 9-12 | 45 | 6 | 4 | - | 400 gold | One additional retaliation per round. |
| 5 alt+ | Priest | `h3_monk_upg_alt` | Monk | `priestAU` | 12 | 12 | 10-12 | 40 | 8 | 3 | 24 | 550 gold | Shooter; no melee penalty; 3 casts of Advanced Bless at enchant power 6. |
| 6 alt+ | Justiciar | `h3_cavalier_upg_alt` | Cavalier | `justiciarAU` | 15 | 17 | 15-25 | 110 | 7 | 2 | - | 1200 gold | Jousting at +5% damage per hex traveled; attacks reduce enemy Attack by 30%. |
| 7 alt+ | Seraph | `h3_angel_upg_alt` | Angel | `seraphAU` | 25 | 25 | 50 | 300 | 18 | 1 | - | 5000 gold, 3 gems | Flying; 1 cast of Expert Prayer at 100% power; grants +1 allied Morale; hates Devils, Arch Devils, and Arch Demons for +50% damage. |

Alternate-upgrade behavior notes:

- Glaivier charge immunity must use the same immunity concept as Pikeman/Halberdier jousting immunity. Do not implement it as a generic defense buff.
- Crossbowman Defense reduction is deterministic on its attack effect. If OE cannot express a persistent target debuff in data, mark it as static-trace debt; do not replace it with higher damage.
- Battle Griffin double attack is a true extra attack, not a focus-only attack. Trace whether it follows Marksman/Crusader-style timing or a ToA-specific ferocity path before implementation.
- Guardsman gets exactly one additional retaliation, not unlimited retaliation.
- Priest Bless is a creature spell action with 3 casts, Advanced Bless level, and enchant power 6. It must not silently become a hero spell, passive aura, or random proc.
- Justiciar Attack reduction is deterministic on its attack effect. Its jousting remains the same per-hex movement formula as Cavalier/Champion, including Pikeman/Halberdier/Glaivier immunity handling.
- Seraph Prayer is a creature spell action with 1 cast, Expert Prayer level, and 100% creature spell power. Seraph morale and hatred behavior should mirror the Angel/Archangel morale and hate semantics, extended to ToA Arch Demons.
- Castle ToA alternate rows currently have no percentage-based chance-to-proc-on-hit effects. If future Castle source rows add any percentage on-hit proc, convert it into a guaranteed Olden Era focus-point-costing active ability that preserves the source target, effect strength, duration, and restrictions as much as practical. Do not ship hidden random on-hit passives as a shortcut.

## Unique Faction Mechanics

- `Righteousness`: reuse the native Humans faction skill path for Castle's faction identity unless a future design pass creates a Castle-specific faction skill. User spreadsheet direction explicitly agrees with reusing Righteousness.
- Probability rule impact: Castle ToA alternate upgrades do not currently require chance-on-hit conversion. Morale remains probabilistic according to OE's existing morale system unless a separate Castle morale redesign is approved.
- HotA rule impact: use HotA creature stats, costs, shots, and abilities for Castle. Do not inherit Olden Era Human unit behavior where it contradicts the table above.

## Static Trace Debts

- Locate exact OE data or hook path for double ranged attack and double melee attack.
- Locate exact OE data or hook path for per-round retaliation capacity and unlimited retaliation.
- Locate exact OE data or hook path for jousting damage from traveled hex count, including Pikeman/Halberdier immunity.
- Locate exact OE data or hook path for no melee penalty and HotA-style shooter melee/ranged attack choice.
- Locate exact OE data or hook path for Angel/Archangel army-wide morale bonus persistence after the source stack dies.
- Locate exact OE data or hook path for hated-enemy damage modifiers.
- Locate exact OE data or hook path for a 2-focus Archangel Rewind Life creature action using `space_12_magic_rewind` as the revive base, including target validation, cost, charge/gating, and UI presentation.
- Locate exact OE data or hook path for ToA Crossbowman enemy Defense reduction and Justiciar enemy Attack reduction.
- Locate exact OE data or hook path for ToA Priest Bless and Seraph Prayer creature spell actions, including cast counts, spell level, power, targeting, and UI presentation.
- Locate exact OE data or hook path for ToA Battle Griffin double attack/ferocity timing.
- Locate exact OE data or hook path for ToA Seraph hatred against Arch Demons in addition to Devil and Arch Devil hatred.
- Verify Castle hero/class rows can reference `skill_faction_humans` cleanly without cloning stale Humans-only localization.
- Verify the external Stable building path (`stables`, `stable_buff`) for movement and define the separate Cavalier upgrade behavior.
- Verify the external Quix's Path morale path (`quixs_path`, `quixs_path_buff`) for Brotherhood of the Sword city-visit morale behavior.
- Keep Lighthouse blocked until OE water movement exists; do not ship Lighthouse text or gameplay that implies water support.
