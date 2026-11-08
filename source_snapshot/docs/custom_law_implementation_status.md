# Custom Faction Law Implementation Status

Generated from `custom_factions/custom_law_runtime_completion_classification.json` after the June 21 native-data replacement pass. This is source/build status documentation, not runtime proof.

## Summary

| Classification | Count | Meaning |
|---|---:|---|
| `native-data-implemented` | 130 | Implemented through concrete Core-native law bonus rows; no custom law gameplay mutator is active for this pass. |

Current policy: all active custom law rows are native-data replacements. Speculative custom-law runtime hooks, including Rampart Avenger marker/Reprisal/Tutelage paths, are disabled until individually revalidated and explicitly promoted. Castle Elite Strategem is not a custom-law row and is intentionally documented outside this generated law-status table: it remains a runtime-backed Castle faction skill with mutually exclusive spellbook placement toggles, and that separate line was user-accepted on June 21 after mechanical and icon validation.

Validation on June 21: `python tools/release_port/validate_custom_law_auxiliary_handoffs.py` passed after normalizing the localization handoff to 130 current native-data rows and adding a stale Castle overlay-generator marker guard; `python tools/release_port/check_custom_law_no_compromise_static.py` includes that auxiliary gate and passed; `python tools/validate_custom_faction_manifests.py` passed with the known donor-collision warnings inside the overlay dry-run; Core overlay `--dry-run --validate-no-compromise-law-core-metadata --require-no-compromise-law-static` prepared 7266 member updates for custom-law rows, passed custom-law Core metadata validation, and passed candidate validation; and `dotnet build ... --no-restore -v:q` passed with 47 warnings/0 errors. This generated custom-law status does not supersede the later deployed Castle Elite Strategem faction-skill runtime and spellbook toggle work.

## Law Rows

### castle

| Law | SID | Name | Native-data effect | Source note |
|---:|---|---|---|---|
| 2 | `fraction_law_homm3_castle_2` | Road Wardens | Your hero gains increased sight range. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 6 | `fraction_law_homm3_castle_6` | Officer Corps | Friendly units deal increased damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 13 | `fraction_law_homm3_castle_13` | Shield Wall | Friendly units deal increased counterattack damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 15 | `fraction_law_homm3_castle_15` | Daylight Liturgy | Your heroes gain access to the faction's lower spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 18 | `fraction_law_homm3_castle_18` | Line Doctrine | Friendly units deal more melee damage and take less melee damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 19 | `fraction_law_homm3_castle_19` | Line Doctrine | Friendly units deal more ranged damage and take less ranged damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 21 | `fraction_law_homm3_castle_21` | Prosperous Holdings | Gold income is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 22 | `fraction_law_homm3_castle_22` | Righteous Zeal | Your hero gains Morale. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 25 | `fraction_law_homm3_castle_25` | Encouragement | Friendly units gain additional-action chance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 27 | `fraction_law_homm3_castle_27` | Daylight Liturgy | Your heroes gain access to the faction's higher spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 28 | `fraction_law_homm3_castle_28` | Civic Engineers | Your towns gain an additional daily construction allowance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 33 | `fraction_law_homm3_castle_33` | Chapel Calendar | Astrology progress is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 34 | `fraction_law_homm3_castle_34` | Liturgical Rhythm | Positive effects on friendly units last longer. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |

### conflux

| Law | SID | Name | Native-data effect | Source note |
|---:|---|---|---|---|
| 2 | `fraction_law_homm3_conflux_2` | Planar Attunement | Your hero gains increased sight range. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 6 | `fraction_law_homm3_conflux_6` | Elemental Aspect | Friendly units deal increased damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 13 | `fraction_law_homm3_conflux_13` | Elemental Backlash | Friendly units deal increased counterattack damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 15 | `fraction_law_homm3_conflux_15` | Elemental Wheel | Your heroes gain access to the faction's lower spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 18 | `fraction_law_homm3_conflux_18` | Elemental Conjunction | Friendly units deal more melee damage and take less melee damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 19 | `fraction_law_homm3_conflux_19` | Elemental Conjunction | Friendly units deal more ranged damage and take less ranged damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 21 | `fraction_law_homm3_conflux_21` | Elemental Market | Gold income is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 22 | `fraction_law_homm3_conflux_22` | Elemental Harmony | Your hero gains Morale. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 25 | `fraction_law_homm3_conflux_25` | Elemental Harmony | Friendly units gain additional-action chance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 27 | `fraction_law_homm3_conflux_27` | Elemental Wheel | Your heroes gain access to the faction's higher spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 28 | `fraction_law_homm3_conflux_28` | Planar Alignment | Your towns gain an additional daily construction allowance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 33 | `fraction_law_homm3_conflux_33` | Planar Calendar | Astrology progress is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 34 | `fraction_law_homm3_conflux_34` | Aspect Cooldowns | Positive effects on friendly units last longer. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |

### cove

| Law | SID | Name | Native-data effect | Source note |
|---:|---|---|---|---|
| 2 | `fraction_law_homm3_cove_2` | Sea Charts | Your hero gains increased sight range. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 6 | `fraction_law_homm3_cove_6` | Burning Ash | Friendly units deal increased damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 13 | `fraction_law_homm3_cove_13` | Boarding Hooks | Friendly units deal increased counterattack damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 15 | `fraction_law_homm3_cove_15` | Storm Charts | Your heroes gain access to the faction's lower spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 18 | `fraction_law_homm3_cove_18` | Boarding Parties | Friendly units deal more melee damage and take less melee damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 19 | `fraction_law_homm3_cove_19` | Gun Decks | Friendly units deal more ranged damage and take less ranged damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 21 | `fraction_law_homm3_cove_21` | Prize Shares | Gold income is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 22 | `fraction_law_homm3_cove_22` | Crew Nerve | Your hero gains Morale. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 25 | `fraction_law_homm3_cove_25` | Crew Nerve | Friendly units gain additional-action chance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 27 | `fraction_law_homm3_cove_27` | Storm Charts | Your heroes gain access to the faction's higher spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 28 | `fraction_law_homm3_cove_28` | Harbor Rush | Your towns gain an additional daily construction allowance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 33 | `fraction_law_homm3_cove_33` | Storm Omens | Astrology progress is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 34 | `fraction_law_homm3_cove_34` | Reload Drills | Positive effects on friendly units last longer. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |

### dungeon

| Law | SID | Name | Native-data effect | Source note |
|---:|---|---|---|---|
| 2 | `fraction_law_homm3_dungeon_2` | Deep Scouts | Your hero gains increased sight range. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 6 | `fraction_law_homm3_dungeon_6` | Predator's Instruction | Friendly units deal increased damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 13 | `fraction_law_homm3_dungeon_13` | Outnumber | Friendly units deal increased counterattack damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 15 | `fraction_law_homm3_dungeon_15` | Night Dominion | Your heroes gain access to the faction's lower spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 18 | `fraction_law_homm3_dungeon_18` | Kill Corridors | Friendly units deal more melee damage and take less melee damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 19 | `fraction_law_homm3_dungeon_19` | Kill Corridors | Friendly units deal more ranged damage and take less ranged damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 21 | `fraction_law_homm3_dungeon_21` | Subjugated Mines | Gold income is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 22 | `fraction_law_homm3_dungeon_22` | Terror Exploitation | Your hero gains Morale. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 25 | `fraction_law_homm3_dungeon_25` | Terror Exploitation | Friendly units gain additional-action chance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 27 | `fraction_law_homm3_dungeon_27` | Night Dominion | Your heroes gain access to the faction's higher spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 28 | `fraction_law_homm3_dungeon_28` | Excavation Crews | Your towns gain an additional daily construction allowance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 33 | `fraction_law_homm3_dungeon_33` | Deep Portents | Astrology progress is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 34 | `fraction_law_homm3_dungeon_34` | Cruel Momentum | Positive effects on friendly units last longer. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |

### fortress

| Law | SID | Name | Native-data effect | Source note |
|---:|---|---|---|---|
| 2 | `fraction_law_homm3_fortress_2` | Marsh Sense | Your hero gains increased sight range. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 6 | `fraction_law_homm3_fortress_6` | Hidebound Drill | Friendly units deal increased damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 13 | `fraction_law_homm3_fortress_13` | Thorned Hides | Friendly units deal increased counterattack damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 15 | `fraction_law_homm3_fortress_15` | Bog Witchcraft | Your heroes gain access to the faction's lower spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 18 | `fraction_law_homm3_fortress_18` | Bog Line | Friendly units deal more melee damage and take less melee damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 19 | `fraction_law_homm3_fortress_19` | Bog Line | Friendly units deal more ranged damage and take less ranged damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 21 | `fraction_law_homm3_fortress_21` | Marsh Rights | Gold income is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 22 | `fraction_law_homm3_fortress_22` | Cold-Blooded Endurance | Your hero gains Morale. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 25 | `fraction_law_homm3_fortress_25` | Cold-Blooded Endurance | Friendly units gain additional-action chance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 27 | `fraction_law_homm3_fortress_27` | Bog Witchcraft | Your heroes gain access to the faction's higher spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 28 | `fraction_law_homm3_fortress_28` | Mudworks | Your towns gain an additional daily construction allowance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 33 | `fraction_law_homm3_fortress_33` | Witch Signs | Astrology progress is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 34 | `fraction_law_homm3_fortress_34` | Bog Hex | Positive effects on friendly units last longer. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |

### inferno

| Law | SID | Name | Native-data effect | Source note |
|---:|---|---|---|---|
| 2 | `fraction_law_homm3_inferno_2` | Hellgate Omens | Your hero gains increased sight range. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 6 | `fraction_law_homm3_inferno_6` | Infernal Ascension | Friendly units deal increased damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 13 | `fraction_law_homm3_inferno_13` | Hellfire Reprisal | Friendly units deal increased counterattack damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 15 | `fraction_law_homm3_inferno_15` | Hellfire Gatecraft | Your heroes gain access to the faction's lower spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 18 | `fraction_law_homm3_inferno_18` | Hellpack Assault | Friendly units deal more melee damage and take less melee damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 19 | `fraction_law_homm3_inferno_19` | Hellpack Assault | Friendly units deal more ranged damage and take less ranged damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 21 | `fraction_law_homm3_inferno_21` | Soul Contract | Gold income is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 22 | `fraction_law_homm3_inferno_22` | Frenzy | Your hero gains Morale. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 25 | `fraction_law_homm3_inferno_25` | Frenzy | Friendly units gain additional-action chance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 27 | `fraction_law_homm3_inferno_27` | Hellfire Gatecraft | Your heroes gain access to the faction's higher spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 28 | `fraction_law_homm3_inferno_28` | Blood Mortar | Your towns gain an additional daily construction allowance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 33 | `fraction_law_homm3_inferno_33` | Infernal Signs | Astrology progress is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 34 | `fraction_law_homm3_inferno_34` | Sacrificial Casting | Positive effects on friendly units last longer. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |

### necropolis

| Law | SID | Name | Native-data effect | Source note |
|---:|---|---|---|---|
| 2 | `fraction_law_homm3_necropolis_2` | Gravesight | Your hero gains increased sight range. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 6 | `fraction_law_homm3_necropolis_6` | Corpse Wisdom | Friendly units deal increased damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 13 | `fraction_law_homm3_necropolis_13` | Death Grip | Friendly units deal increased counterattack damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 15 | `fraction_law_homm3_necropolis_15` | Death Rite | Your heroes gain access to the faction's lower spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 18 | `fraction_law_homm3_necropolis_18` | Death March | Friendly units deal more melee damage and take less melee damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 19 | `fraction_law_homm3_necropolis_19` | Death March | Friendly units deal more ranged damage and take less ranged damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 21 | `fraction_law_homm3_necropolis_21` | Mortuary Accounting | Gold income is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 22 | `fraction_law_homm3_necropolis_22` | Dread | Your hero gains Morale. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 25 | `fraction_law_homm3_necropolis_25` | Dread | Friendly units gain additional-action chance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 27 | `fraction_law_homm3_necropolis_27` | Death Rite | Your heroes gain access to the faction's higher spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 28 | `fraction_law_homm3_necropolis_28` | Reanimated Masonry | Your towns gain an additional daily construction allowance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 33 | `fraction_law_homm3_necropolis_33` | Death Moon | Astrology progress is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 34 | `fraction_law_homm3_necropolis_34` | Corpse Fuel | Positive effects on friendly units last longer. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |

### rampart

| Law | SID | Name | Native-data effect | Source note |
|---:|---|---|---|---|
| 2 | `fraction_law_homm3_rampart_2` | Avenger's Trail | Your hero gains increased sight range. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 6 | `fraction_law_homm3_rampart_6` | Avenger's Tutelage | Friendly units deal increased damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 13 | `fraction_law_homm3_rampart_13` | Avenger's Reprisal | Friendly units deal increased counterattack damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 15 | `fraction_law_homm3_rampart_15` | Druidic Oath | Your heroes gain access to the faction's lower spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 18 | `fraction_law_homm3_rampart_18` | Hunter Pairs | Friendly units deal more melee damage and take less melee damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 19 | `fraction_law_homm3_rampart_19` | Hunter Pairs | Friendly units deal more ranged damage and take less ranged damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 21 | `fraction_law_homm3_rampart_21` | Preservation Tithe | Gold income is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 22 | `fraction_law_homm3_rampart_22` | Defender's Grace | Your hero gains Morale. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 25 | `fraction_law_homm3_rampart_25` | Defender's Grace | Friendly units gain additional-action chance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 27 | `fraction_law_homm3_rampart_27` | Druidic Oath | Your heroes gain access to the faction's higher spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 28 | `fraction_law_homm3_rampart_28` | Living Groves | Your towns gain an additional daily construction allowance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 33 | `fraction_law_homm3_rampart_33` | Druidic Calendar | Astrology progress is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 34 | `fraction_law_homm3_rampart_34` | Avenger's Patience | Positive effects on friendly units last longer. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |

### stronghold

| Law | SID | Name | Native-data effect | Source note |
|---:|---|---|---|---|
| 2 | `fraction_law_homm3_stronghold_2` | War Scouts | Your hero gains increased sight range. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 6 | `fraction_law_homm3_stronghold_6` | Berserker Charge | Friendly units deal increased damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 13 | `fraction_law_homm3_stronghold_13` | Blood Feud | Friendly units deal increased counterattack damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 15 | `fraction_law_homm3_stronghold_15` | Warcries | Your heroes gain access to the faction's lower spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 18 | `fraction_law_homm3_stronghold_18` | Warband Crush | Friendly units deal more melee damage and take less melee damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 19 | `fraction_law_homm3_stronghold_19` | Warband Crush | Friendly units deal more ranged damage and take less ranged damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 21 | `fraction_law_homm3_stronghold_21` | Spoils Ledger | Gold income is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 22 | `fraction_law_homm3_stronghold_22` | Rage | Your hero gains Morale. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 25 | `fraction_law_homm3_stronghold_25` | Rage | Friendly units gain additional-action chance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 27 | `fraction_law_homm3_stronghold_27` | Warcries | Your heroes gain access to the faction's higher spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 28 | `fraction_law_homm3_stronghold_28` | Warcamp Raising | Your towns gain an additional daily construction allowance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 33 | `fraction_law_homm3_stronghold_33` | War Festival | Astrology progress is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 34 | `fraction_law_homm3_stronghold_34` | Spellbreaker Chants | Positive effects on friendly units last longer. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |

### tower

| Law | SID | Name | Native-data effect | Source note |
|---:|---|---|---|---|
| 2 | `fraction_law_homm3_tower_2` | Observatory Network | Your hero gains increased sight range. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 6 | `fraction_law_homm3_tower_6` | Arcane Calibration | Friendly units deal increased damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 13 | `fraction_law_homm3_tower_13` | Reactive Wards | Friendly units deal increased counterattack damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 15 | `fraction_law_homm3_tower_15` | Prepared Artifice | Your heroes gain access to the faction's lower spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 18 | `fraction_law_homm3_tower_18` | Battle Automata | Friendly units deal more melee damage and take less melee damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 19 | `fraction_law_homm3_tower_19` | Battle Automata | Friendly units deal more ranged damage and take less ranged damage. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 21 | `fraction_law_homm3_tower_21` | Transmutation Ledger | Gold income is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 22 | `fraction_law_homm3_tower_22` | Synchronization | Your hero gains Morale. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 25 | `fraction_law_homm3_tower_25` | Synchronization | Friendly units gain additional-action chance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 27 | `fraction_law_homm3_tower_27` | Prepared Artifice | Your heroes gain access to the faction's higher spell school package. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 28 | `fraction_law_homm3_tower_28` | Grand Workshop | Your towns gain an additional daily construction allowance. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 33 | `fraction_law_homm3_tower_33` | Celestial Calculus | Astrology progress is increased. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |
| 34 | `fraction_law_homm3_tower_34` | Overclocked Spellworks | Positive effects on friendly units last longer. | Native-data replacement 2026-06-21: active law row uses concrete Core-native bonuses only; speculative runtime mutators are disabled until individually revalidated. |

