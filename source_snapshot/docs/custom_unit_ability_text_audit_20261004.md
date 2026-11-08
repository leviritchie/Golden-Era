# Custom Unit Ability Text Audit

Date: 2026-10-04. Status: audit followed by source fixes and in-memory generated-candidate validation; not installed-fix, runtime, or user-visible gameplay proof. The initial audit changed no ability data. The follow-up below changes authoring and generation, but leaves the installed payload unchanged.

The custom-unit descriptions do not consistently match their configured effects. The strongest findings concern wrong effects or numerical values, omitted friendly-fire/range limitations, unsupported behavior promises, and missing English localization. This report separates those findings from cases that still require a native consumer trace or combat test.

## Fix follow-up

The user authorized fixes that can be made without a runtime. Existing native effects remain authoritative; no combat hook, speculative Focus consumer, movement lock, or unimplemented Tower spell kit was added. The table records the initial fix pass; the subsequent Dragon Fly balance change is recorded separately below.

| Area | Source and generated-data resolution |
| --- | --- |
| Curse | Removed the conflicting later localization provider. The shared description now matches 1 Focus, 20% reduced normal damage, minimum damage, and the configured 2 rounds. |
| Magnetic Slow | Corrected to 1 Focus and -1 Speed/-1 Initiative. No duration is promised while the selected buff's `infinite` flag and requested duration remain a native-consumer question. |
| Initial Attack/Defense penalty | Base Cavalier, Shambling Grasp, and Zombie Clutch say initially -3 to both stats, retaining their configured costs and durations. No cumulative round-by-round progression is asserted. |
| Radiant Armor | Corrected 30% to the selected buff's 25% incoming-damage reduction. |
| Weakening Shot | Per-unit descriptions distinguish 15% from 20%, with the configured 3 rounds. They also describe the existing hook's already-weakened-target rewrite to stacking -3/-4 Defense. The rewrite remains source-prepared, not combat-proven; no expiry promise is added for that secondary effect. |
| Dragonflight / Earthshatter | Disclosed allied landing-area damage and the 2-hex enemy-taunt radius respectively. Native target/damage execution remains untested. |
| Alert I | Configured Goblin's `stats.numCounters` to 2 at its existing Stronghold mechanic owner, matching its card. This is the only intentional combat-value change in this pass. |
| Armor Rend | Corrected Behemoth variants' 40%/80%/60% pierce descriptions to name Defense, not Attack. |
| Fortress Mode | Describes the configured one-round Carapace barrier, not an unimplemented stationary bunker. Updated the matching source notes/debt wording. |
| Execute | Disclosed increased same-target recast damage without inventing a numeric progression. |
| Unsupported display cards | Removed the identified Tower legacy passive promises in a final card-only pass. The original early Tower mesh normalization and implemented stats/actives are preserved. Faerie Dragon's exact unit rule replaces Blink with Flying without changing its already-configured flight. |
| Missing action text | Supplied Fangarm active text and retained the generated Harpy Hag/Fury alternate-attack text. Fury uses the stable `hit_and_run` authoring ID, not a timestamp-specific token exception. |
| Generic attack cards | Removed unconditional retaliation and reduced-melee claims that some units override. Specific exception cards remain responsible for those traits. |
| Stale authoring | Corrected Cave Bash and Fury damage/return copy; cleared Rotting Ray's unused poison selector/payload while retaining its native Defense-reduction action. |

The missing-key problem had a shared ownership cause: multilingual cleanup classified unfamiliar ability SIDs as unit-title text and deleted their pending `unitsAbility.json` rows. The classifier now derives ability ownership from pending custom unit-view card references, including neutrals and alternate/default/counter attacks. Sync, its audit, and its standalone validator use that same invocation-local reference set. Wrong-file rows are still scrubbed; there is no seven-key whitelist or late re-emission fallback.

The extended `validate_homm3_active_ability_localization_contract.py` checks all 272 generated unit views and 805 active/passive/alternate card rows. It pins the selected corrected effect data, costs, scopes, and removed cards, and rejects conflicting shared localization definitions before dictionary merging. In-memory fixtures cover conflicting providers, unresolved keys, wrong numeric claims, reversed modifier direction, missing taunt radius, and arbitrary view-consumed SID ownership/wrong-file scrubbing. These checks are deliberately static/configuration contracts, not a general proof of native combat semantics.

Measured candidate invocation before the final direction assertions: 25.90 seconds, 141.2 MiB sampled peak process RSS/working set (psutil, 100 ms sampling; not an OS-certified maximum), no GPU work or VRAM use. JSON/ZIP I/O and serialization stay on the CPU. The existing full overlay owner runs once in memory per validator invocation; no candidate ZIP, biome asset pack, or new expensive delivery stage is created.

Source manifest validation passed for 12 manifests / 255 faction units in 1.340 seconds, with 57 existing donor-context warnings. The final isolated `ValidateHomm3ActiveAbilityLocalizationContract` full-tier target passed with the active Golden Era Core and fixtures in 27.683 seconds; the isolated quick-tier invocation skipped it and returned successfully in 2.415 seconds. This proves the owning target and generated data, not a full plugin compile or a full-tree release validation.

The broader unit-ability redesign validator initially rejected the Air Elemental's explicit custom Thunderbolt icon because its generic name-only inference chose a vanilla icon. A read-only check reproduced the same single conflict against the unchanged installed baseline. The validator now gives an already-satisfied exact `CUSTOM_ICON_TARGETS` contract precedence over that name-only heuristic; exact name-and-description checks and wrong-icon failures remain intact. No game icon was changed. Its in-memory acceptance/rejection fixtures passed, and the final generated-candidate check passed in 24.484 seconds: 32 redesigned, 2 preserved, 12 custom-active-icon, 9 passive-icon, and 255 common-icon unit packages. This is validator/generated-data proof, not an installed icon change.

Independent source review found no remaining blocker after the scoped amendments. The unresolved Rivulet Retreat Focus-cost question remains outside the proven fixes.

The installed Core SHA-256 at the close of the initial fix pass remained `87D1C9E35598AC41E0A1F031BF81283B7C46BF7285D4F69D1630E4A6BDC4365D`. No DLL, Core ZIP, asset, catalog, or running game was changed. There was therefore no newly installed change to add to the in-game check queue. The catalog must be refreshed from the matching payload during a later delivery, not relabeled from this in-memory candidate.

## Dragon Fly balance follow-up

The user reports that Dragon Fly's historical turn-ending discrepancy has been repaired, and requested a balance reduction for its Weakening Dispel hit from 100% to 50% normal damage. This follow-up changes only the standard Dragon Fly's per-unit native damage multiplier and its corresponding text providers. Focus cost, cooldown, turn settings, dispel, weakening, basic attacks, and the base/alternate Fly variants are preserved. It does not re-test the reported turn-behavior repair.

The existing full-tier ability localization contract now pins the generated Dragon Fly multiplier to 0.5, damage type to normal, and final tooltip to 50% normal damage. A narrow in-memory comparison against the pre-change generator passed in approximately 3.6 seconds and found exactly one ability-row change: `damageDealer.statDmgMult`, from 1.0 to 0.5. The owning full-tier target passed with fixtures and all 272 unit views / 805 cards in 33.892 seconds, with zero warnings or errors. This reuses the existing validator; no new stage, full plugin build, or persisted candidate ZIP was added. Peak memory was not remeasured for this six-line contract extension; the earlier owning-validator sample is recorded above.

Proof is source/static and generated candidate only. Installed Core readback still has the same SHA-256 recorded above; this follow-up did not install anything or exercise combat. No new in-game check queue entry is required until delivery.

All audit findings and line references below describe the pre-fix source/installed snapshot. They are retained as evidence, not as statements that these source defects remain open.

## Scope and method

The pass covered the active Golden Era `HeroesOldenEra_Data/StreamingAssets/Core.zip`, the current faction overrides and neutral catalog, the overlay generator, referenced buff and native donor rows, and relevant plugin source. Current worktree HEAD was `2ec88d05f6`; existing unrelated worktree changes were preserved.

The installed census was read directly from unit view entries, not from the older checked-in ability catalog. A separate in-memory catalog collection took 0.234 seconds and wrote no outputs. No new gate, pipeline stage, build, deploy, or GPU workload was introduced. The neutral contract validator passed against this Core using `--neutral-band-target steam_25672315`; that pass does not establish description/effect equivalence.

| Installed family | Units | Active slots | Passive cards | Alternate attacks |
| --- | ---: | ---: | ---: | ---: |
| Castle | 21 | 11 | 44 | 6 |
| Rampart | 21 | 11 | 41 | 3 |
| Tower | 21 | 14 | 54 | 5 |
| Inferno | 21 | 11 | 40 | 4 |
| Necropolis | 21 | 13 | 46 | 4 |
| Dungeon | 21 | 12 | 54 | 7 |
| Stronghold | 21 | 8 | 35 | 6 |
| Fortress | 21 | 13 | 31 | 6 |
| Conflux | 21 | 10 | 49 | 5 |
| Cove | 21 | 11 | 54 | 6 |
| Factory | 24 | 17 | 53 | 8 |
| Bulwark | 21 | 16 | 36 | 6 |
| Custom neutrals | 17 | 11 | 48 | 4 |
| Total | 272 | 158 | 585 | 70 |

Fangarm belongs to the neutral set and is also a Cove summon; it is not counted twice. There is no installed custom Cannon unit row. Default attacks, stats, movement types, and native donor mechanics were checked alongside passive cards: absence from `logic.passives` alone was not treated as a missing implementation.

## Material effect and text mismatches

Each item below is supported by current source or installed Core data. Configured round counts and target scopes are not claims that expiry or friendly fire was exercised in battle.

### Mummy Curse

The English description promises 2 Focus, +30% incoming damage, and 1 round. Installed `neutral/h3_mummy_l.json` instead costs 1 Focus and applies `magic_unnatural_calm_effect_1_special` with duration 2. That buff reduces outgoing normal damage by 20% and forces minimum damage.

This has a concrete shared-localization root cause: `tools/release_port/apply_release_core_overlay.py:10876` defines the correct Curse description, but a later duplicate for the same token at line 13752 replaces it with the unrelated incoming-damage description. The active spec at lines 10152-10158 still selects the normal-damage/minimum-damage debuff. Evidence: `DB/units/units_logics/neutral/h3_mummy_l.json`, its paired view, `DB/buffs/buffs_night_magics.json`, and `Lang/english/texts/unitsAbility.json`.

### Enchanter Magnetic Slow

The English description promises 2 Focus, -2 Speed, and 1 round. Installed `neutral/h3_enchanter_l.json` costs 1 Focus and applies `magic_nairas_kiss_slow_effect` with duration 2. The buff data changes Speed by -1 and Initiative by -1. The source spec at `apply_release_core_overlay.py:10168-10175` matches that installed configuration; its omitted Focus field uses the maker's default of 1. Evidence: the paired neutral unit logic/view entries and `DB/buffs/buffs_night_magics.json`.

### Fortress Dragonflight

The alternate Wyvern upgrade (`h3_wyvern_upg_alt`) describes damage to enemies in the landing area. Its copied native dealer instead uses `affectTargetParams.castTarget_ = noself` and `damageTarget_ = all`; the native donor describes damage and push to all adjacent creatures. The description should not promise enemy-only safety. Evidence: `custom_factions/ability_overrides/homm3_fortress.json:281`, installed `DB/units/units_logics/homm3_fortress/h3_wyvern_upg_alt_l.json`, and the matching `dungeon/black_dragon_upg_alt` donor view. Actual allied damage remains a focused combat check.

### Factory Fortress Mode

Ironclad (`h3_dreadnought_upg_alt`) promises a stationary bunker while braced. Its installed active only applies the one-round self Core Carapace buff, described by its English buff text as a one-hit barrier; no corresponding movement lock was found in the unit configuration or relevant plugin source. The manifest explicitly records the immobility lock as runtime debt at `custom_factions/homm3_factory.json:583`, while the player-facing promise remains at `custom_factions/ability_overrides/homm3_factory.json:1045`. The native barrier envelope is configured; neither barrier behavior nor stationary behavior was exercised in battle. Evidence: installed `DB/units/units_logics/homm3_factory/h3_dreadnought_upg_alt_l.json` and its referenced Carapace buff.

### Attack and Defense debuffs

Base Cavalier, Zombie Clutch, and Shambling Grasp promise -2 Attack and -2 Defense, but all select `magic_shorten_shadow_effect_1`, whose installed initial buff data sets offense and defense to -3 each. That buff also contains native start-round bonus actions, so it is not simply a constant -2/-2 effect; followup timing was not tested. This is one shared numerical mismatch, not three independent mechanic defects. Cavalier upgrade variants select different redesign mechanics and are not included in this finding. Evidence: `DB/units/units_logics/homm3_castle/h3_cavalier_l.json`, `DB/units/units_logics/homm3_necropolis/h3_walking_dead_l.json`, `h3_walking_dead_upg_l.json`, their English view descriptions, and `DB/buffs/buffs_day_magics.json`.

### Rampart Radiant Armor

Pristine Unicorn's alternate upgrade (`h3_pristine_unicorn_upg_alt`) promises 30% incoming-damage reduction for 1 round. The selected level-2 effect is `magic_radiant_armor_effect_1`, whose buff has `inAllDmgMod: -0.25`: a configured 25% reduction. No ability-specific magnitude transform was found. Evidence: `custom_factions/ability_overrides/homm3_rampart.json:220`, the installed unit logic, and `DB/buffs/buffs_day_magics.json`.

### Cove Weakening Shot

The shared description promises 20% reduced normal damage for 1 round. Sea Witch and its alternate upgrade apply `magic_unnatural_calm_effect_0`, which is 15%, with duration 3. Sorceress applies the 20% `_effect_1`, also with duration 3. The after-shot hook's repeated-application rewrite does not reconcile the initial strength or duration. Evidence: installed Cove logic/view rows for `h3_sea_witch`, `h3_sea_witch_upg_alt`, and `h3_sorceress`; `DB/buffs/buffs_night_magics.json`; `Homm3CoveAfterShotHook.cs:56-65,267-277` in the plugin source. The shared text is authored at `apply_release_core_overlay.py:10880`.

### Stronghold Alert I

The standard Goblin upgrade (`h3_goblin_upg`) promises up to two counterattacks per round, but installed `stats.numCounters` is 1 with no intrinsic passive extension. Native Alert I controls and other custom units encode 2. Evidence: installed Stronghold logic/view entries for this unit; native `trogl_upg_alt`, `griffin`, and custom `h3_swordsman_upg_alt` controls. The override has no existing-special replacement at `custom_factions/ability_overrides/homm3_stronghold.json:19`.

### Stronghold Armor Rend

All three Behemoth variants say they ignore 40%, 80%, or 60% of enemy Attack. Their corresponding passive stat is `armorPen` at 0.4, 0.8, or 0.6. The matching native-stat control on Factory's Halfling Grenadier describes this as ignoring Defense. The tooltip names the wrong stat. Evidence: installed Stronghold logic/view rows for `h3_behemoth`, `h3_behemoth_upg`, and `h3_behemoth_upg_alt`, plus the Factory `h3_halfling_grenadier` control.

### Dungeon Earthshatter

Minotaur Taskmaster's description says enemies must target it until round end without a range boundary. The installed `ent_taunt_buff` has `tauntRadius: 2`; the native donor's own tooltip specifies a 2-hex radius. The custom wording overstates scope. Evidence: `custom_factions/ability_overrides/homm3_dungeon.json:456`, installed `h3_minotaur_upg_alt_l.json`, `DB/buffs/units_buffs_nature.json`, and the native `nature/ent_upg_alt` view.

### Faerie Dragon Blink

The retained donor card says the Faerie Dragon teleports directly to its destination. Installed movement is `stats.moveType: fly`, not teleport, and no corresponding blink mechanic appears in its complete Core logic. The neutral source simultaneously sets flight and retains donor passive cards at `tools/homm3_import/faction_concepts/homm3_neutral.json:537-565`; the generator copies those cards at `apply_release_core_overlay.py:14090-14138`. Evidence: paired installed `neutral/h3_faerie_dragon` logic/view entries. The Blink description is unsupported by the inspected Core movement configuration; runtime movement and trap interactions were not tested.

### Castle Execute

Execute advertises a 30%-of-maximum-HP hit with a stack-size cap, but does not disclose increasing same-target recast damage. Its dealer applies `magic_decimate_effect`; the installed buff has an incoming `decimate_damage` modifier of +1.0, and the native donor's spell description explicitly describes increased damage on repeated casts. Evidence: `custom_factions/ability_overrides/homm3_castle.json:92`, installed `h3_pikeman_upg_alt_l.json`, `DB/buffs/buffs_space_magics.json`, `DB/magics/battle_space_magics.json`, and `Lang/english/texts/magic.json`. Exact damage progression and commit order are not runtime-proven.

## Localization and shared generic cards

Three installed action rows have missing English name/description keys:

- Fangarm active: `h3_fangarm_hypnotic_strike_name` and `_description`. Its passive's similarly named pair is present, but does not satisfy these references. The view emits the active keys at `apply_release_core_overlay.py:14685-14687`; the Cove language rows at 17815-17820 emit only passive keys.
- Harpy Hag alternate attack: `h3_harpy_upg_alternativeAttacks_0_name` and `_description`.
- Fury alternate attack: `h3_harpy_upg_alt_h3_harpy_upg_alt_copied_unit_special_1779150600692_name` and `_description`.

Evidence: paired unit view entries for `neutral/h3_fangarm`, `homm3_dungeon/h3_harpy_upg`, and `h3_harpy_upg_alt`, and the installed English text tables. Exact visible handling of unresolved keys was not tested. Fury's authoring copy also omits the copied attack's 50% damage multiplier.

Two generic card descriptions make unconditional claims contradicted by the corresponding unit's configured attack. These are shared tooltip defects; the specific exception cards are generally correct.

- Generic Melee Attack says it provokes counterattacks, but 18 custom units have a default melee attack with `triggerCounter: false`: `h3_pixie_upg_alt`, `h3_pixie_upg`, all three Psychic Elemental variants, `h3_automaton_upg_alt`, `h3_juggernaut`, `h3_sentinel_automaton`, all three Devil variants, `h3_hell_hound_upg`, `h3_imp_upg_alt`, all three Vampire variants, `h3_gold_pegasus_upg_alt`, and `h3_rogue`.
- Generic Ranged Attack says adjacent melee attacks deal reduced damage, but 15 custom units have a melee alternative at `statDmgMult: 1.0`: all three Snow Elf variants, `h3_monk_upg`, `h3_corsair`, `h3_pirate`, `h3_sea_dog`, `h3_sea_witch`, `h3_sorceress`, all three Beholder variants, `h3_medusa`, `h3_medusa_upg`, and `h3_enchanter`.

The parent audit independently enumerated these lists from the installed default/alternate attacks and the actual English strings. Evidence: `h3_common_melee_attack_description`, `h3_common_ranged_attack_description`, and the matching installed unit logic/view entries.

## Implementation and runtime questions

### Tower legacy passive promises

Several Tower descriptions are not supported by their complete installed Core configuration or the current plugin's registered implementation paths:

- `h3_gargoyle_upg_alt`: Elemental Carapace resistance and Stone Gaze immunity; its Core has no matching passives or damage modifiers. The source law-family table does classify it as a construct, so that classification is not being reported as absent.
- `h3_genie` and `h3_genie_upg`: Efreet Hate; the upgraded unit also promises three beneficial Spellcaster casts without a matching cast/charge configuration.
- `h3_genie_upg_alt`: Efreet damage bonus, Air resistance, and a 1-Focus Misfortune active; its actual Core active is 2-Focus Switch Places.
- `h3_giant_upg`: Black Dragon Hate without a corresponding Core damage modifier.
- `h3_giant_upg_alt`: 40% post-attack Thunderbolt chance at 25 damage per creature without a corresponding Core passive/attack action.
- `h3_mage_upg_alt`: three bolt spells per battle; its Core exposes Silence and the side mana-cost modifier, not that spell/charge kit.

The followup runtime-owner search checked the registered unit, faction-specific, damage, event, and adapter owners. `Homm3UnitAbilityNativeHook.cs:5-17` is a quarantined wrapper, also skipped in the release-safe path at `Plugin.cs:1201-1208`. The SID matches in `Homm3UnitLawClassifier.cs` and `Homm3UnitLawFamilyRegistry.cs` classify units for laws; they do not execute these abilities. No current source implementation path was found for the listed Tower effects. This strengthens the source/installed-payload finding, but does not prove live absence because the loaded plugin identity and gameplay were not tested.

Likewise, 24-shot claims on Mage variants and the upgraded Giant cannot be rejected solely because `stats.ammo` is absent: the native default-ammunition semantics were not established.

### Other unresolved behavior

- Silver Pegasus Rivulet Retreat says Spend 1 Focus, but its copied donor retains `dontUseEnergy: true` alongside `energyLevel: 1`. The shared envelope authoring code updates the numeric cost without clearing that donor flag (`apply_release_core_overlay.py:12359-12389`). This is a concrete configuration risk. A bounded native-consumer check did not prove whether the native menu/commit path charges Focus, so this report does not call the move free in gameplay.
- Wolf Raider's counterattack wording versus native `add_attack_after_counter_melee` needs a native consumer or combat test. The enum name alone was not treated as proof of its trigger.
- Dendroid's claim that root ends when the caster moves or dies was not established by the buff row alone.
- Factory Suppressing Fire damage stamping and Bulwark Frostbound Skies have source-prepared runtime owners; observed combat effects remain unproven.

No game process was running. The saved bridge status was stale, not live proof. Installed override/diagnostic tables matching source does not establish the identity or behavior of the loaded plugin. The diagnostic runtime-mechanics table is gated and is not an implementation inventory for every native product ability.

## Stale authoring metadata

Cave Bash's override still describes a one-round stun, while the installed mechanic and English text correctly describe 50% normal damage plus suppression of one retaliation. Rotting Ray's effect selector/payload still names poison, while installed logic and text correctly describe permanent -1 Defense with no turn-end. These are source-authoring inconsistencies, not current deployed tooltip/function mismatches. The normal overlay's later localization passes must be considered before predicting rebuild behavior. The older checked-in faction catalog was not used as current installed evidence.

## Remaining followthrough

The source/data resolutions are listed above. Delivery through the normal Core overlay path, matching catalog readback, and installed-payload validation have not been performed. Do not use the normal broad overlay installer as an ability-only deployment: it also regenerates/deploys other surfaces.

The owning localization contract now runs in the full-validation build tier, selecting the active game Core for OfficialDeobf builds rather than a stale default artifact; it stays out of the quick tier. Rivulet Focus spending, Wolf Raider trigger semantics, Dendroid release conditions, ammunition defaults, native expiry/sequence semantics, Dragonflight friendly fire, and runtime-owned statuses still require focused native-consumer or combat proof. Any subsequently installed change needing visual verification belongs in `docs/ingame_check_queue.md`, not in a second audit-specific queue.
