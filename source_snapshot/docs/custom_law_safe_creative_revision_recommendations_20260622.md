# Custom Law Safe Creative Revision Recommendations

Generated: 2026-06-22
Updated: 2026-06-22 manual no-duplicate pass

Status: source-implemented and candidate-Core-readback proven as of 2026-06-22. The accepted recommendations have been applied to `custom_factions/law_overrides/homm3_*.json`; a dry-run Core overlay generated all 40 rows with matching English text. This has not been deployed to the installed game, launched, or runtime-validated.

## Implementation Status

- Source rows updated: `custom_factions/law_overrides/homm3_*.json`.
- Target text updated for rows already covered by the legacy `custom_law_targets.json` no-compromise matrix.
- Candidate Core dry-run/readback proved all 40 accepted recommendation rows have nonempty generated `parametersPerLevel` payloads and matching English `factionLaws` text.
- Not yet proven: installed Core deploy, law-tree UI smoke, economy charged/displayed-cost parity, battle behavior, native-terrain behavior, and runtime gameplay side effects.
## Review Rules

- Baseline source of truth: `custom_factions/law_overrides/homm3_*.json`.
- Background sources: `docs/custom_law_supported_donor_selections.md`, `docs/custom_law_vanilla_effect_match_pass.md`, `docs/custom_law_donor_effect_application_pass.md`, `docs/current_custom_law_readable_descriptions.csv`, and shipped Core faction-law tables.
- The earlier subagent-generated slate is superseded by this manual pass. No subagents were used for this revision.
- Primary goal: no recommended special faction law should be functionally identical to another recommended special faction law. This includes the same effect applied to a different faction, line, resource, spell school, or creature set.
- Safety bar: prefer shipped vanilla donor rows and native Core law bonus shapes. Formerly discarded custom rows are allowed only when the unsafe trigger is removed, or when the exact shipped/static row shape can be copied without inventing a new contract.
- Explicitly excluded: Avenger mark laws, corpse spend/count laws, Gating identity laws, plunder/reward hooks, swamp/terrain predicates, dynamic elemental-family counting, Warcry execution, cannon reload logic, friendly cooldown reduction, and conditional kill/debuff/isolation triggers.
- Any recommendation marked medium risk needs a validator before implementation. This is especially true for exact shipped donor rows whose current validation status is weaker than plain stat rows.

## No-Duplicate Donor Shape Policy

The following donor shapes are intentionally used at most once in the recommendation slate: extra counterattack charges, structure sight, hero sight, start Focus, maximum Focus, positive-effect duration, negative-effect duration, enemy spell cooldown pressure, crit chance, enemy morale suppression, construction discount, extra daily construction, gold income, rare-resource income, vampirism healing, enemy spell-school suppression, hero magic-to-creature scaling, hero spell-cost reduction, magic upgrade discount, enemy hero information, neutral squad count information, no enemy escape, native-terrain battle, extra magic guild access, all-dwelling growth, unit hiring discount, item-to-dust economy, always-maximum damage, hero magic attack scaling, city experience scaling, hero Defense, and hero movement.

## Castle

1. `fraction_law_homm3_castle_13` - **Royal Retaliation**
   - Suggested English: "Castle creatures gain 1 additional counterattack charge."
   - Recommended shape: copy exact `unitStat numCounters 1` from `fraction_law_undead_30`, scoped to Castle creatures.
   - Why: Castle gets the one retaliation-charge law because organized formation discipline is central to the faction.
   - Duplicate check: no other recommended faction law uses extra counterattack charges.
   - Risk: low. Exact native donor exists, but combat pacing should be watched.

2. `fraction_law_homm3_castle_6` - **Battle Readiness**
   - Suggested English: "Your heroes start each battle with 1 additional Focus Charge."
   - Recommended shape: copy exact `heroStat startEnergyLevelsBonus 1` from shipped Focus-start rows.
   - Why: Officer Corps becomes command readiness instead of generic damage or morale-scaling damage.
   - Duplicate check: no other recommended faction law grants starting Focus.
   - Risk: low-medium. Supported native Focus-start shape; validate candidate Core.

3. `fraction_law_homm3_castle_34` - **Liturgical Rhythm**
   - Suggested English: "Positive effects on Castle creatures last +1/+2 additional round(s) by rank."
   - Recommended shape: copy exact `unitStat inComingBuffDuration 1/2` from `fraction_law_human_5`, scoped to Castle creatures.
   - Why: Castle keeps the durable blessing identity and avoids cooldown filters.
   - Duplicate check: no other recommended faction law extends positive-effect duration.
   - Risk: low.

4. `fraction_law_homm3_castle_28` - **Mason's Charter**
   - Suggested English: "Buildings cost 20%/40% less Ore."
   - Recommended shape: copy exact resource-wide `constructionDiscount ore -0.20/-0.40` from `fraction_law_dungeon_7`.
   - Why: Castle civic engineering becomes a quarry/masonry economy, not a second build-queue duplicate.
   - Duplicate check: no other recommended faction law discounts construction costs.
   - Risk: medium. Displayed-cost and charged-cost parity must be checked.

## Rampart

1. `fraction_law_homm3_rampart_6` - **Hunter Precision**
   - Suggested English: "Centaur, Wood Elf, and Pegasus lines gain +1%/+2%/+3% critical chance."
   - Recommended shape: copy exact `unitStat critChanceModifier 0.01/0.02/0.03` from `fraction_law_nature_24`, scoped to the hunter lines.
   - Why: This preserves Avenger-like precision without depending on Avenger mark state.
   - Duplicate check: no other recommended faction law grants critical chance.
   - Risk: low-medium. Copy the donor shape exactly; avoid any mark predicate.

2. `fraction_law_homm3_rampart_15` - **Druidic Ward**
   - Suggested English: "Negative effects on Rampart creatures last 1 fewer round."
   - Recommended shape: copy exact `unitStat inComingDebuffDuration -1` from `fraction_law_nature_12`, scoped to Rampart creatures.
   - Why: Rampart gets protective druidic cleansing without event-triggered cleanse logic.
   - Duplicate check: no other recommended faction law reduces negative-effect duration.
   - Risk: low-medium. Validate sign semantics in generated Core before calling it proven.

3. `fraction_law_homm3_rampart_33` - **Living Groves**
   - Suggested English: "Creature growth in Rampart dwellings increases by 10%/20%."
   - Recommended shape: use the shipped all-dwelling growth percentage shape `barrackUnitsIncrementPer all`, tuned down to `0.10/0.20` and scoped to Rampart.
   - Why: This keeps the living-grove identity without the 50%/100% growth spike being absurdly overpowered.
   - Duplicate check: no other recommended faction law increases all-dwelling growth by percent.
   - Risk: medium. Needs generated Core readback and balance review because the values intentionally differ from the donor row.

4. `fraction_law_homm3_rampart_27` - **Avenger's Trail**
   - Suggested English: "Enemy hero information is revealed."
   - Recommended shape: copy exact `heroStat enableEnemyHeroInfo true` shape from `fraction_law_demon_25`, scoped to Rampart if the schema requires faction scoping.
   - Why: This is a better elf/Rampart scouting law than a magic-guild infrastructure effect, and it avoids Avenger mark tracking.
   - Duplicate check: no other recommended faction law reveals enemy hero details.
   - Risk: medium. Validate the exact information shown and avoid broad fog-reveal promises.

## Tower

1. `fraction_law_homm3_tower_6` - **Arcane Conduits**
   - Suggested English: "Tower creatures gain Attack based on their hero's Spell Power and Defense based on their hero's Knowledge."
   - Recommended shape: copy exact `unitStat heroSpellPowerModifier 0.25` plus `heroIntelligenceModifier 0.25` from `fraction_law_human_26`, scoped to Tower creatures.
   - Why: Tower gets the one hero-magic-to-creature-stat law because it best fits academy calibration.
   - Duplicate check: no other recommended faction law converts hero Spell Power or Knowledge into creature stats.
   - Risk: low.

2. `fraction_law_homm3_tower_15` - **Formula Mastery**
   - Suggested English: "Your heroes' spells cost 1/2/3 less Mana by rank."
   - Recommended shape: copy exact `heroStat manaCostBonus -1/-2/-3` from `fraction_law_demon_9`.
   - Why: Tower gets spell efficiency without cooldown banking or prepared-spell state.
   - Duplicate check: no other recommended faction law reduces spell Mana costs.
   - Risk: medium. Validate negative value semantics and UI text.

3. `fraction_law_homm3_tower_28` - **Grand Workshop**
   - Suggested English: "Magic upgrades cost 20%/30%/40% less."
   - Recommended shape: copy exact `sideStat magicUpgradeCostPerBonus -0.20/-0.30/-0.40` from `fraction_law_undead_14`.
   - Why: The workshop identity becomes cheaper arcane upgrading, not another construction law.
   - Duplicate check: no other recommended faction law discounts magic upgrades.
   - Risk: medium. Needs displayed-cost and charged-cost validation.

4. `fraction_law_homm3_tower_2` - **Observatory Network**
   - Suggested English: "Tower magic guilds offer additional spell levels and open more spells for learning."
   - Recommended shape: copy exact `magicGuildIncrement` plus `magicGuildLearnAdditionMagicAllOpenLevel` shape from `fraction_law_nature_14`, scoped to Tower.
   - Why: The magic-guild infrastructure effect belongs naturally on Tower's academy/observatory identity.
   - Duplicate check: no other recommended faction law expands magic guild access.
   - Risk: medium. Must validate text and guild behavior in generated Core.

## Inferno

1. `fraction_law_homm3_inferno_25` - **Frenzy**
   - Suggested English: "Inferno creatures gain +1%/+2%/+3% additional-action chance and critical chance."
   - Recommended shape: copy exact paired `additionalActionChanceModifier` plus `critChanceModifier` shape from `fraction_law_demon_29`, scoped to Inferno creatures.
   - Why: Inferno keeps reckless tempo as a paired frenzy profile, not Gating placement logic.
   - Duplicate check: no other recommended faction law combines additional-action chance with critical chance.
   - Risk: low-medium. Balance should be watched.

2. `fraction_law_homm3_inferno_26` - **Hellfire Brands**
   - Suggested English: "Enemy creatures take more damage from damage-over-time effects."
   - Recommended shape: use only the existing static damage-over-time vulnerability row shape if it validates exactly; do not re-author the parameter name.
   - Why: This is the safest flavorful survivor from the discarded custom set.
   - Duplicate check: no other recommended faction law modifies damage-over-time damage.
   - Risk: medium. Skip if the exact existing row cannot be validated.

3. `fraction_law_homm3_inferno_21` - **Soul Furnace**
   - Suggested English: "Destroying artifacts yields additional Alchemical Dust."
   - Recommended shape: copy exact `sideStat percentDustForDestroyItem 0.10/0.20/0.30` from `fraction_law_unfrozen_23`.
   - Why: Inferno gets a furnace economy without sacrifice, death-event, or reward hooks.
   - Duplicate check: no other recommended faction law modifies artifact destruction yield.
   - Risk: medium. Validate the artifact-destroy UI path before calling it proven.

4. `fraction_law_homm3_inferno_15` - **Hellfire Rites**
   - Suggested English: "Your heroes' damaging magic is 10%/20%/30% stronger."
   - Recommended shape: copy exact `heroStat magicAttackPerBonus 0.10/0.20/0.30` from `fraction_law_demon_22`.
   - Why: This keeps Inferno's destructive-magic identity without relying on the Unfrozen portal building that Inferno does not have.
   - Duplicate check: no other recommended faction law improves hero magic attack scaling.
   - Risk: medium. Validate how the stat affects spell damage and UI text.

## Necropolis

1. `fraction_law_homm3_necropolis_2` - **Tomb Archives**
   - Suggested English: "Necropolis towns gain 20%/40%/60% more experience."
   - Recommended shape: copy exact `sideStat cityExpCoef 0.2/0.4/0.6` from `fraction_law_undead_8`, scoped to Necropolis.
   - Why: Donor `necromancyPerBonus` likely does not drive HoMM3 Skeletal Necromancy, which uses a separate reward/ability path; town experience is a safer undead infrastructure payoff.
   - Duplicate check: no other recommended faction law modifies city experience gain.
   - Risk: medium. Validate the town-experience behavior and player text before implementation.

2. `fraction_law_homm3_necropolis_17` - **Vampiric Nobility**
   - Candidate English after donor validation: "Life-draining Necropolis creatures restore more Health from the damage they deal."
   - Recommended shape: copy exact `unitStat vampirismHealMultiplier 0.50/1.00` from `fraction_law_undead_17`, scoped to valid life-draining Necropolis receivers only.
   - Why: This is a direct Undead donor row and avoids corpse-spend or counterattack-drain hooks.
   - Duplicate check: no other recommended faction law modifies vampirism healing.
   - Risk: medium. Prior audit rejected invented vampirism rows; use only exact donor semantics.

3. `fraction_law_homm3_necropolis_22` - **Legion Without Banner**
   - Suggested English: "Your army ignores faction-mixing penalties."
   - Recommended shape: copy exact `unitBoolStat ignoreFractionsCount true` from `fraction_law_undead_9`.
   - Why: Necropolis can command mixed dead and living auxiliaries without relying on morale-trigger logic.
   - Duplicate check: no other recommended faction law ignores faction-count penalties.
   - Risk: medium. Validate how the stat presents in the UI and whether it affects intended army composition only.

4. `fraction_law_homm3_necropolis_34` - **Deathly Silence**
   - Suggested English: "Enemy heroes lose access to low-tier battle spells from every school."
   - Recommended shape: copy exact enemy `magicSchoolSet day/night/space/primal 0 -1` pattern from `fraction_law_undead_34`.
   - Why: Necropolis gets spell suppression without corpse fuel or cooldown refresh.
   - Duplicate check: no other recommended faction law suppresses enemy spell-school access.
   - Risk: medium. Validate enemy targeting and player text carefully.

## Dungeon

1. `fraction_law_homm3_dungeon_6` - **Predator's Instruction**
   - Suggested English: "Friendly creatures deal 5%/10% more damage and take 5%/10% less damage; enemy creatures deal 5%/10% less damage and take 5%/10% more damage."
   - Recommended shape: copy exact `fraction_law_undead_31` pattern: faction-scoped ally damage/defense entries plus matching enemy vulnerability entries.
   - Why: Dungeon gets predator/prey pressure without isolated-target checks.
   - Duplicate check: no other recommended faction law uses the paired ally-pressure/enemy-vulnerability pattern.
   - Risk: medium. Preserve the donor structure exactly and validate every faction/receiver entry.

2. `fraction_law_homm3_dungeon_2` - **Deep Scouts**
   - Suggested English: "Your heroes can see exact neutral squad counts."
   - Recommended shape: copy exact `heroStat enableSquadCounts true` shape from `fraction_law_demon_8`, scoped to Dungeon if needed.
   - Why: Dungeon scouting becomes information warfare, not generic vision.
   - Duplicate check: no other recommended faction law reveals neutral squad counts.
   - Risk: medium. Validate that this does not imply broader intent or reward information.

3. `fraction_law_homm3_dungeon_34` - **No Escape Below**
   - Suggested English: "Enemy heroes cannot flee from battle."
   - Recommended shape: copy exact enemy `heroStatBattle enableBattleEscapeBan true` from `fraction_law_nature_21`.
   - Why: Dungeon gets shackles-style battlefield control without kill/debuff cooldown triggers.
   - Duplicate check: no other recommended faction law prevents escape.
   - Risk: medium. Needs battle UI and retreat/surrender validation.

4. `fraction_law_homm3_dungeon_21` - **Deep Tutors**
   - Suggested English: "Your heroes gain 10%/20% more experience."
   - Recommended shape: copy exact `heroStat sideExpPerBonus 0.10/0.20` from shipped side-experience rows.
   - Why: Dungeon knowledge economy becomes training and subjugated instruction, not mine reward hooks.
   - Duplicate check: no other recommended faction law modifies hero experience gain.
   - Risk: low-medium. Validate whether the stat applies to all heroes or side-wide heroes as intended.

## Stronghold

1. `fraction_law_homm3_stronghold_2` - **War Beacons**
   - Suggested English: "External buildings and structures you control reveal a wider area."
   - Recommended shape: copy exact `sideObjectViewRadius 2/4/6` from `fraction_law_dungeon_15`.
   - Why: Stronghold gets the one structure-sight law as war-camp beacon coverage.
   - Duplicate check: no other recommended faction law uses structure sight.
   - Risk: low-medium. Validate law-tree/readback behavior.

2. `fraction_law_homm3_stronghold_6` - **Berserker Charge**
   - Suggested English: "Stronghold creatures gain +1 Speed."
   - Recommended shape: use native `unitStat speed 1`, scoped to Stronghold creatures.
   - Why: A full-roster Speed and Initiative boost is too strong; +1 Speed preserves charge identity without stacking as hard.
   - Duplicate check: no other recommended faction law grants friendly Speed.
   - Risk: low implementation risk, moderate balance risk.

3. `fraction_law_homm3_stronghold_31` - **Goblin Mob Rule**
   - Suggested English: "Goblin line creatures always deal their maximum damage."
   - Recommended shape: copy exact `unitBoolStat alwaysMaxDmg true` from `fraction_law_nature_6`, scoped only to Goblin line creatures; place this near the end of the law tree with cost 4.
   - Why: Whole-faction maximum damage is absurdly strong; a late Goblin-line payoff is flavorful and bounded.
   - Duplicate check: no other recommended faction law forces maximum damage rolls.
   - Risk: medium. Validate receiver scoping, late-tree placement, and cost 4 in generated Core.

4. `fraction_law_homm3_stronghold_34` - **Spellbreaker Chants**
   - Suggested English: "Enemy heroes have longer spell cooldowns in battle."
   - Recommended shape: copy exact enemy `heroStatBattle magicCdBonus 1` from `fraction_law_unfrozen_36`.
   - Why: Stronghold gets the one enemy cooldown-pressure law as anti-caster chanting, without Warcry execution.
   - Duplicate check: no other recommended faction law increases enemy cooldowns.
   - Risk: low-medium. Avoid ally/default cooldown rows.

## Fortress

1. `fraction_law_homm3_fortress_18` - **Hidebound Drill**
   - Suggested English: "Your heroes gain +1/+2/+3 Defense."
   - Recommended shape: copy exact `heroStat defence 1/2/3` from `fraction_law_undead_6`.
   - Why: Enemy Speed or Initiative pressure stacks too well with the Fortress unique ability; hero Defense is a safer endurance identity.
   - Duplicate check: no other recommended faction law grants hero Defense.
   - Risk: low.

2. `fraction_law_homm3_fortress_21` - **Marsh Levies**
   - Suggested English: "Fortress creatures cost 10%/15%/20% less to hire."
   - Recommended shape: copy exact `unitHiringDiscount -0.10/-0.15/-0.20` from `fraction_law_undead_22`, scoped to Fortress.
   - Why: Fortress gets marsh levy logistics instead of defensive-win income hooks.
   - Duplicate check: no other recommended faction law discounts unit hiring.
   - Risk: medium. Needs recruitment UI and charged-cost validation.

3. `fraction_law_homm3_fortress_33` - **Witch Signs**
   - Suggested English: "Your heroes gain +1/+2/+3 Spell Power."
   - Recommended shape: copy exact `heroStat spellPower 1/2/3` from `fraction_law_unfrozen_7`.
   - Why: The previous temporary-spell-power recommendation had no clear Fortress source effect; plain Spell Power is safer and visible.
   - Duplicate check: no other recommended faction law grants hero Spell Power directly.
   - Risk: low.

4. `fraction_law_homm3_fortress_32` - **Native Marsh Doctrine**
   - Suggested English: "Your Fortress heroes always battle on their Native Terrain."
   - Recommended shape: copy exact `heroStat enableBattleOnNativeBiome true` from `fraction_law_undead_20`, only if it validates without custom terrain predicates.
   - Why: This uses the vanilla-style native-terrain wording instead of implying manual battle selection or custom conditions.
   - Duplicate check: no other recommended faction law enables native-biome battle selection.
   - Risk: high for this slate. It is native-shaped but must be proven before implementation.

## Conflux

1. `fraction_law_homm3_conflux_18` - **Opposed Elements**
   - Suggested English: "Fire, Earth, and Firebird lines deal more melee damage; Water, Air, and Pixie lines take less melee damage."
   - Recommended shape: fixed receiver lists with native melee outgoing and incoming damage modifiers.
   - Why: Conflux gets fixed elemental contrast without dynamic elemental-family counting.
   - Duplicate check: no other recommended faction law splits offense and defense by elemental line groups.
   - Risk: low.

2. `fraction_law_homm3_conflux_21` - **Elemental Market**
   - Suggested English: "Produces +1/+2 Crystal daily by rank."
   - Recommended shape: copy exact `sideRes crystals 1/2` from `fraction_law_demon_13`.
   - Why: Conflux gets the one rare-resource economy law as crystalline elemental output.
   - Duplicate check: no other recommended faction law produces a rare resource daily.
   - Risk: low implementation risk, moderate balance risk.

3. `fraction_law_homm3_conflux_27` - **Celestial Wheel**
   - Suggested English: "Your heroes can store 1 additional Focus Charge."
   - Recommended shape: copy exact `heroStat maxEnergyLevelsBonus 1` from shipped Focus-capacity rows.
   - Why: Conflux gets channeling capacity without dynamic spell scaling or aspect matching.
   - Duplicate check: no other recommended faction law increases maximum Focus capacity.
   - Risk: low-medium. Validate UI text.

4. `fraction_law_homm3_conflux_32` - **Leyline Currents**
   - Suggested English: "Your heroes gain +10/+20 Movement points."
   - Recommended shape: copy exact `heroStat movementBonus 10/20` from `fraction_law_dungeon_8`.
   - Why: Planar Grounding duplicated Fortress native-terrain behavior, and Prismatic Screen already exists as a separate Conflux magic-resistance law. Movement gives Conflux a planar-map payoff without duplicating native terrain or magic resistance.
   - Duplicate check: no other recommended faction law grants hero Movement points.
   - Risk: low-medium. Validate the exact Movement display and map movement behavior in generated Core.

## Cove

1. `fraction_law_homm3_cove_2` - **Sea Charts**
   - Suggested English: "Your heroes gain +1/+2 Sight radius."
   - Recommended shape: copy exact `heroStat viewRadius 1/2` shape from `fraction_law_human_2`.
   - Why: Cove gets the one hero-sight law as chartmaking and navigation, distinct from Stronghold structure beacons.
   - Duplicate check: no other recommended faction law grants hero sight radius.
   - Risk: low.

2. `fraction_law_homm3_cove_21` - **Prize Shares**
   - Suggested English: "Sources of Gold produce 10%/20% more Gold."
   - Recommended shape: copy exact `sideStat resPercentIncrementSet gold 0.10/0.20` from `fraction_law_human_21`.
   - Why: Cove gets the one gold-income law as prize shares without plunder/reward hooks.
   - Duplicate check: no other recommended faction law increases Gold source output.
   - Risk: low.

3. `fraction_law_homm3_cove_28` - **Harbor Rush**
   - Suggested English: "You can construct 1 additional building daily."
   - Recommended shape: copy exact `constructionDailyLimit 1` from `fraction_law_human_28`.
   - Why: Cove gets the one extra-build law as dockyard acceleration, distinct from Castle ore discounts.
   - Duplicate check: no other recommended faction law grants extra daily construction.
   - Risk: low-medium. Build-limit UI should be checked.

4. `fraction_law_homm3_cove_15` - **Powder Charts**
   - Suggested English: "Space spells of your heroes gain 1 level."
   - Recommended shape: keep the existing native `heroStat magicSchoolSet space 0 1` low-tier Space access shape.
   - Why: Cove keeps storm/navigation spell flavor without cannon reload, gunpowder-hit Focus, or a duplicate Focus-capacity law.
   - Duplicate check: no other recommended faction law improves low-tier Space spell access.
   - Risk: low. Existing native-data shape; validate text/readback.

## Duplicate Audit

- Current fully unique set: Castle 4, Rampart 4, Tower 4, Inferno 4, Necropolis 4, Dungeon 4, Stronghold 4, Fortress 4, Conflux 4, Cove 4.
- The previous repeated structure-sight, counterattack-charge, enemy-cooldown, positive-duration, start-Focus, maximum-Focus, native-terrain, and enemy-speed-pressure recommendations have been reduced to one faction each or removed.
- User review corrections applied: Rampart growth toned down to 10%/20%; Rampart/Tower scouting-vs-magic-guild effects swapped; Inferno portal-summoning removed; Necropolis donor Necromancy removed because HoMM3 Skeletal Necromancy follows a separate path; Stronghold Speed/Initiative reduced to Speed only; Stronghold maximum damage limited to late-tree Goblin line at cost 4; Fortress enemy tempo pressure and temporary spell-power recommendations replaced; Conflux native-terrain duplicate removed and not replaced with existing Prismatic Screen duplicate.

## Implementation Guardrails

- Add or extend a validator before implementing any new recommendation category that is not already covered by current strict native-data validators.
- Copy exact shipped donor row shapes for medium-risk rows. Do not infer parameter names from readable descriptions.
- Candidate Core validation should prove every recommended row has nonempty `parametersPerLevel`, expected bonus types, expected receiver/fraction scoping, exact resource keys, expected player text, and no duplicate functional effect across the special-faction recommendation slate.
- For construction and hiring discounts, validation must compare displayed cost and charged cost before the law is called proven.
- For enemy battle effects, validation must prove `receiverAllegiance=enemy` is present where intended and that no ally/default row was copied accidentally.
- For any formerly discarded custom-origin row, document whether it is "exact shipped donor copied" or "unsafe trigger stripped"; if neither is true, reject it.
