# Custom Unit Ability Static Audit (2026-11-12)

## Scope and evidence

**Status:** static and read-only. Nothing was edited, built, installed or launched.

**Scope:** 272 custom units (12 HoMM3 factions plus 17 custom neutrals) and about 805 cards.

**Primary evidence:** the installed Golden Era `Core.zip`. Its file and entry dates are 2026-10-22 07:09, which is the v0.1.325 build. For each unit the audit read:
- the logic and view rows
- the resolved English card text
- the referenced buff rows, followed transitively

**Secondary evidence:**
- `custom_factions/ability_overrides/*`
- `tools/release_port/apply_release_core_overlay.py`
- the plugin source
- the native donor rows
- the native `DB/info` formula scripts
- `il2cpp_data/Metadata/global-metadata.dat`

**Installed data is older than source.** Two commits on 2026-11-10, `3e785c8ec9` and `76ef786af5`, changed ability source after the installed build. Findings that current source already fixes are tagged **[fixed in source, needs Core rebuild]**. Every other finding is still present in current source.

**No item is runtime-proven.** Items marked *uncertain* depend on native engine defaults that the data alone cannot settle.

## Fix status (source, 2026-11-12, follow-up pass)

Fixed in `tools/release_port/apply_release_core_overlay.py` and the Factory/Bulwark override JSON. The changes are source-only and not installed: they need the next Core rebuild. They were checked with an in-memory candidate build on the installed Core (HEAD plus these changes only) and per-unit dumps. `validate_homm3_active_ability_localization_contract`, `validate_homm3_unit_ability_redesign_contract`, `validate_custom_faction_manifests` and both Bulwark ability contracts pass.

**Systemic:**
- **S1/S2:** the new pass `normalize_custom_unit_ability_card_consistency` makes the turn and Awaken info lines follow the logic:
  - No "does not end the turn" line without `actionCost 0`.
  - Free abilities that lacked the line gain it.
  - No Awaken line without the `wisp_silence` gate.
  - `dontUseEnergy` is dropped where `energyLevel > 0` (Rivulet Retreat).
- **S4:** the shot counts are gone from the Mage, Arch Mage and Titan text. Master Gremlin's "8 shots in the Heroes III baseline" lives in `quality_pass_homm3_tower_overlay.py` and is left as lore.
- **S5/S6:**
  - The strip table now covers every listed upgrade and alternate upgrade.
  - `numCounters` is reset to 1 instead of popped.
  - Only the leaked `shoot_attack` entry is removed, so the Glaivier keeps its -10% basic entry.
  - Donor drains are removed from Vampire, Wight ×3 and Lich Master, and Vampire Lord/Prince keep a single 40% drain. The installed 50% + 40% stack is gone.
  - The Pit Fiend line loses Hive Queen `unique_fractions_buff`.
  - `moralMin 0` and the base morale/luck leaks are **not** changed.
- **S7:**
  - Repair no longer carries `construct_immunities`.
  - Animate Dead uses the native `avatar_immunities` (Lich Master, Pit Lord/Spawn).
  - Old installed rows are replaced in place, so there are no duplicate actives.
  - Gremlin Mechanic's stale second Repair is removed.
- **S8:**
  - Melee-only units lose their ranged and Duelist cards (Medusa Warrior).
  - Shooters with no falloff (`ignoreShootDmgBuff`, or a shoot dealer with `shootDmgBuff 0`) lose the "-X% per hex" card and get Sharpshooter unless a card already says so.
  - The duplicate generic Ranged cards are removed.
  - Correction to S8: the Mage line's "No Melee or Obstacle Penalty" is accurate (`shootDmgBuff 0.0`). The falloff card was the false one.
- **S9:** reach-2 units get a "two hexes behind" card (`h3_common_passive_strike_reach_2_description`) instead of the one-hex card. Naga Rani's text is corrected. The geometry is unchanged.
- **S10:** the 50% alternate melee card now says "Deals 50% damage". The whirlwind alternates (Hydra ×3, Psychic ×2, Juggernaut) say "Strikes all adjacent enemies for 50% damage".

**Per unit:**
- Taunting Plate, Wind-Up and Boiler Rampage now apply `magic_taunt_effect_0` / `magic_hksmillas_rampage_effect_0` for 1 round.
- Tidecaller spawns 1 Fangarm per 2 Tidecallers (`0/2/1`), and its text says so.
- Death Stare now reads "kill 1 additional creature".
- Fearsome now says 2 rounds.
- Archangel Rewind Life now says once per battle.
- Ruinous Hydra Regeneration now reads "25% of one creature's maximum health".
- Wolf Raider Ferocity is described as a double strike.
- The Dendroid Binding release clause is removed.
- Jotun Avalanche text describes the radius-1 AoE with friendly fire and push.
- Gargoyle ×3 get the construct profile, which backs Bloodless. Elemental Gargoyle and Genie Vizier get a Flying card.
- Orc Berserker fallback `targetTags` is now a list.

**Second pass (same day).** Evidence for this pass is installed Golden Era Core data plus generator source only. The Ghidra project (build 25672315) was not used.
- **Giants ×3 Mind Spell Immunity:** a passive immunity to the buff tags `sleep_effect` (Sleep, Unicorn Blind) and `silenceEffect`, plus a new `homm3_mind_berserk_effect` tag stamped on every native `magic_berserker_effect*` row, plus the `berserk` mechanic. The data contract is the native `magic_sleep_ignore` effect immunity. The card now names Sleep, Silence and Berserk.
- **Fangarm:** `energyPerTakeDamage` 0 → 1 (the native default), so the 2-Focus Hypnotic Strike can be cast.
- **Blood-Eyed Cyclops:** `ignoreShootDmgBuff: true` backs the Siege Thrower and "at any range" cards. The card pass then adds Sharpshooter.
- **Magnetic Slow / Weakening Shot:** the text now says "for the rest of the battle". Both buffs are `infinite` + `addition: data`, the same as the native Naira's Kiss slow, which is applied with duration 1.
- **Marshal Suppressing Fire:** the text discloses that the `attack_rumble_x1` trap hits every creature on and next to the hex, allies included.
- **S11:** clones `h3_stunned_effect` (gorilla_stun), `h3_shield_set_effect` (Dwarf only), `h3_runic_guard_effect` (Battle Dwarf only) and `h3_misfortune_effect` (Naira's Kiss old row, with its own description). Custom unit logic is retargeted before and after the strong-vanilla pass, so installed rows don't duplicate. Their Lang rows go in unitsBuff/magic_buff, where the multilingual scrub keeps them. `inquisitor_buff` (law status taxonomy) keeps its id and gets the English name "Blessed". Execute's `magic_decimate_effect` and Dendroid `ent_root` stay native because runtime logic is keyed to them.

**Still open:**
- The S3 rebuild/install.
- The morale-range leaks (left unchanged: balance).
- The remaining low-confidence text rows in section 3.

---

## 1. Systemic issues (generator-wide)

### S1. "Does not end the turn" on abilities that end the turn (16 cards)

**Where:** `apply_release_core_overlay.py:13310-13316` (also around `:13850`). When an override sets `turnBehavior: "ends"`, the generator pops the logic `actionCost`. It keeps the donor view's `infoDescription` (`ability_no_turn` or `ability_no_start_no_turn`). Every native row that uses those info strings also sets `actionCost: 0`.

**Affected cards:**
- Castle: Fine Bolts (h3_archer_upg_alt); Command: Fear (h3_cavalier_upg_alt)
- Rampart: Rivulet Retreat (h3_silver_pegasus)
- Dungeon: Slither Away (h3_medusa_upg_alt); Unyielding Will (h3_minotaur_upg); Earthshatter (h3_minotaur_upg_alt)
- Stronghold: Command: Fear (h3_cyclops_upg_alt); Brutal Rush (h3_ogre_upg_alt; hardcoded at `:11089`)
- Fortress: Inner Flame (h3_gorgon_upg_alt)
- Tower: Command: Reposition (h3_genie); Command: Switch Places (h3_genie_upg_alt)
- Factory: Shoulder Check (h3_bellwether_armadillo); Devour Corpses (h3_olgoi_khorkhoi)
- Bulwark: Clan Warp (h3_jotunn, h3_jotunn_warlord); Rune Surge (h3_yeti_runemaster)

**Fix:** decide per ability whether it is free. When the behavior is "ends", strip `ability_no_turn*` from the view.

### S2. Abilities carrying the Awaken requirement on units with no Awaken

The donor `ability_no_start*` info string ("Can only be used after 'Awaken'") was copied onto three abilities:
- Rivulet Retreat (Silver Pegasus)
- Earthshatter (Minotaur Taskmaster)
- Whirlpool (Abyss Serpent)

None of these units has the Awaken / `wisp_silence` start-of-battle mechanic. It is *uncertain* whether the native gate is enforced. If it is, these abilities may be unusable; if not, only the card text is wrong.

### S3. Stack-scaled durations on cards that state a flat duration (14 actives) [fixed in source, needs Core rebuild]

The buffs carry `durationPerStack`, so `units.script current_unit_ability_buff_duration` adds 1 round per N creatures.

**Affected:** Reality Distortion, Radiant Armor, Haste, Jumpstart, Shorten Shadow (Gnoll Shaman), Hksmilla's Rampage, Gate Anchor, Vengeance, Vulnerability, Naira's Kiss, Carapace, Web, and Silence (Mage, Battle Mage).

Commit `76ef786af5` strips the scaling keys when `effectDuration` is set, and all 14 abilities set it.

### S4. The engine has no shot-count field

`global-metadata.dat` contains 0 occurrences of `ammo` / `Ammo`. By comparison, `shootRedCount` and `durationPerStack` each appear once. The plugin has no ammo consumer either. So every `stats.ammo` the generator writes is dead data (`:3991-3995`, `:10105-10109`), and shooters have unlimited shots.

**False cards:** "24 shots" on Mage, Arch Mage and Titan; "8 shots" on Master Gremlin.

**Fix:** remove the shot claims, or implement ammo.

### S5. Hidden donor stats with no card

`CUSTOM_UNIT_HIDDEN_STAT_STRIP_BY_SID` (around `:15089-15097`) strips donor stats on some base units but misses most upgrades and many lines. Effects that leaked with no card:

| Stat | Effect | Units |
| --- | --- | --- |
| `numCounters` 999 | unlimited retaliation | Scorpicore (h3_manticore_upg), Bellwether Armadillo |
| `numCounters` 2 | 2 counterattacks per round | Chimera, Chthonian, Goblin Trapper (h3_goblin_upg_alt), Elf Wardancer, Armadillo, Plated Armadillo |
| `inDmgMods shoot_attack -0.3` | 30% less ranged damage taken | Pikeman ×3, Halfling ×3, Crew Mate ×3, Gnoll Marauder (h3_gnoll_upg) |
| `stats.crit 1.0` | +100% damage on lucky strikes | Harpy Hag, Fury, Wolf Raider ×2 |
| `additionalActionChanceModifier 0.05` | 5% extra-action chance | Minotaur King / Taskmaster, Ogre Mage / Brute, Mighty / Corrosive Gorgon, Naga Queen / Rani |
| `energyPerRound 2` | +2 Focus per round | War Mammoth, Magma Elemental, Basilisk Flamespitter (h3_basilisk_upg) |
| `damagePerHex` | jousting bonus | Sandworm line |
| `damagePerDeltaLevel` | Topple the Strong | Familiar, Vermin |
| `damagePerDeltaLevelLower` | Squash the Weak | Pit Lord, Pit Spawn |
| `outDamageIfLevelAbove` | Apex Predator | Arch Devil, Arch Demon; Arch Devil also has `overkillProtection` |
| `moralMin 0` | morale floor of 0 | Nix ×3, Ogre line, Gorgon line |
| base morale/luck 2 | | Glassworm, Kobold Foreman, Runebearer, Mammoth line, Shaman line |

**Hidden life drain from donors:**
- Base Vampire: 50% drain, can revive.
- Wight / Wraith / Banshee: 20% / 30% / 20% drain, creates temporary stacks.
- Lich Master: 20% drain that heals allies.

**Hidden conditional passive:** the Pit Fiend line has Hive Queen `unique_fractions_buff`, which grants bonuses per enemy faction. `strip_stale_inferno_donor_conditional_passives` (`:11842-11860`) strips only `unique_units_count`.

**Fix:** extend the strip table to upgrades and alternate upgrades, or add the matching cards.

### S6. The strip deletes `numCounters` instead of normalizing it

Four units have no `numCounters` key: h3_manticore, h3_stormbird, h3_ayssid and h3_stormbird_upg_alt. They are the only 4 of 424 installed rows without it.

*Uncertain:* if the engine default is 0, these units never retaliate.

**Fix:** write `numCounters: 1`.

### S7. Repair cannot target constructs

The generator's `repair` spec (`:10649`) tags the dealer with `construct_immunities`. Every construct carries a cast immunity to that tag; this is the same convention that stops `undead_immunities` heals from working on undead. So Stone Golem and Iron Golem Repair (and Gremlin Mechanic's Repair) probably heal anything except golems and the other constructs. The Golem cards promise "an allied construct stack".

Lich Master's Animate Dead has the same problem with `undead_immunities` (`:10664`): it probably cannot revive any Necropolis stack. The native donor `lich_upg_alt` uses `avatar_immunities`. Dendroid Shaman's Animate Dead carries the same tag.

**Fix:** drop the self-defeating immunity tag from these specs.

### S8. Ranged-card contradictions

**Distance penalty claimed where there is none.** The `base_passive_ranged_attack_no_close` card says "Targets 3+ hexes away take –10% per hex". It appears on units that have no falloff:
- `ignoreShootDmgBuff: true`: Sea Dog, Medusa, Medusa Queen, Fargazer
- `shootDmgBuff: 0.0`: Titan, Mage, Arch Mage, Battle Mage, Enchanter

**Duplicate Ranged Attack cards:** Sea Dog, Medusa, Medusa Queen, Enchanter, Pirate, Corsair, Sea Witch, Sorceress, and the Snow Elf line.

**Missing Sharpshooter card** (has `ignoreShootDmgBuff`): Grand Elf, Lizard Assassin.

**Card with no data behind it:** Blood-Eyed Cyclops shows "Siege Thrower: ignores distance penalties" but has no `ignoreShootDmgBuff`.

**Mage contradiction:** the Mage "No Melee or Obstacle Penalty" card says there is no range falloff, but the unit's data has falloff.

**Melee unit with ranged cards:** Medusa Warrior is melee only but shows Ranged Attack and Duelist cards.

### S9. Reach-2 attack pattern described as reach-1

`attack_reach_x2_x100_x100_x100_with_delay` hits the target and the two hexes behind it, allies included. The "hex directly behind" Dragonbreath text is wrong on Chimera, Cerberus and Fire Hound. Naga Rani's "three adjacent targets" text is also wrong.

### S10. Generic alternate-attack card hides the 50% multiplier

About 58 units share "Can only attack adjacent enemies." / "Performs an alternative Melee attack." About 37 of them are actually at `statDmgMult 0.5`. Some are whirlwind patterns that hit all adjacent hexes:
- Hydra ×3
- Juggernaut
- Psychic Elemental and Magic Elemental

### S11. Donor buff tooltips with wrong names or text

The status tooltip shown on the target comes from the donor buff:
- Misfortune shows the Naira's Kiss "Marked: takes Magic Damage…" description (Pegasus ×3, Astral Elemental).
- Halberd Hook shows "Big Rock, Rrr!".
- Shield Set shows "Valiant Cry".
- Runic Guard shows "Unyielding Will".
- Execute shows "Guillotine".
- Blessing shows `inquisitor_buff`, which has no English name.
- Dendroid `ent_root` shows "Crystal Thorns" and has no description.

---

## 2. Abilities that do nothing or probably don't work

| Unit | Ability | Problem | Confidence |
| --- | --- | --- | --- |
| h3_armadillo_upg_alt Plated Armadillo | Taunting Plate | Dealer has `buffTarget_ self` but no buff and no mechanic, so it spends 2 Focus for nothing. Missing `magic_taunt_effect_0` (overrides `homm3_factory.json:408-430`). | high |
| h3_automaton_upg_alt Clockwork Automaton | Wind-Up | Same problem; missing `magic_hksmillas_rampage_effect_0` (overrides `:536`). | high |
| h3_juggernaut Juggernaut | Boiler Rampage | Same problem (ally target, no buff; overrides `:1001-1023`). | high |
| h3_lich_upg_alt Lich Master | Animate Dead | `undead_immunities` tag (S7). | high |
| h3_golem / h3_golem_upg, h3_gremlin_upg_alt | Repair | `construct_immunities` tag (S7). | medium-high |
| h3_giant ×3 | Mind Spell Immunity | Card only. There are no immunities; the units lack even the Embodiment `embodiment_immunities` passive. | high |
| h3_gargoyle / h3_gargoyle_upg | Bloodless | Card only. `logic.passives` is empty, with no vampirism/poison/revive disablers. | high |
| h3_silver_pegasus | Rivulet Retreat | `dontUseEnergy: true` alongside `energyLevel 1`, so the Focus is probably never spent. It ends the turn despite "Does not end the turn", and requires an Awaken the unit doesn't have (S1, S2). Still open from the 2026-10-04 audit. | high |
| h3_fangarm (neutral / Cove summon) | Hypnotic Strike | `energyPerTakeDamage 0` (the only such unit in Core) and no other Focus income, so the 2-Focus active is probably never castable. Its dealer is a copy of the default attack, which already applies Berserk for free. | medium |
| Dendroid ×3 | Binding | "ends if the Dendroid moves or dies" has no backing: `ent_root` is only speed=0. Still open from 2026-10-04. | high |
| h3_mage_upg Arch Mage | Silence | Missing from the installed build. **[fixed in source, needs Core rebuild]** | high |
| h3_orc_upg_alt Orc Berserker | Crude Chop alternate attack | `targetTags` is the string `"unit attackable_object"`, not a list; this is the only such row in Core (`fallback_melee_attack`, `:4040/4046`). | medium, *uncertain* |
| h3_gunslinger_upg_alt Marshal | Suppressing Fire | The trap row deals 1 damage unless `Homm3MarshalSuppressingFireTrapBridge` stamps 150% (it is registered, `Plugin.cs:1098`). Its rumble pattern hits allies too, which the card doesn't disclose. | medium |
| h3_peasant | Taxpayer | No data row; probably engine code keyed to the native `peasant` id. | low, *uncertain* |

---

## 3. Wrong numbers, scope or side effects in the text

| Unit | Ability | Card text | Data | Confidence |
| --- | --- | --- | --- | --- |
| h3_vampire_upg / _upg_alt | Vampirism | 50% | Two drain mechanics, 0.5 + 0.4, about 90%. `STRONG_VANILLA_LIFE_DRAIN_SIDS` appends instead of replacing (`:12200`). The Vampire Prince balance note says to remove drain. | high |
| h3_gorgon_upg Mighty Gorgon (also shared `h3_common_ability_death_stare_description`) | Death Stare | "kill 1-7 additional creatures" | `kill_stacks ["1","7"]` means +1 kill on targets up to tier 7 (native `avatar_of_war_passive_3`). | high |
| h3_sea_witch_upg_alt Tidecaller | Summon Fangarms | "at 50% Power" | `spawn_object ["unit","h3_fangarm","0","1","2"]` = 0 + floor(stacks × 2 / 1), i.e. **2 Fangarms per Tidecaller** (same formula as Graverobber). `:11395`. | high |
| h3_azure_dragon | Fearsome | 1 round | buff duration 2 (`:10506` vs text `:11213`) | high |
| h3_jotunn_upg_alt Jotun Frostlord | Avalanche | "strike the battlefield with Circle of Winter" | Radius-1 circle around the target, damages allies, pushes. The name and description also disagree. | high |
| h3_wolf_rider_upg Wolf Raider | Ferocity | "after this unit counterattacks… one extra attack" | `add_attack_after_counter_melee` is the native Double Strike (attacks twice). Shahrokh labels the same effect Double Strike. | high |
| h3_manticore_upg_alt Chimera | Dragonbreath Strike | 1 hex behind | Reach-2, allies hit (S9) | high |
| h3_angel_upg Archangel | Rewind Life | not stated | `charges 1, cd -1`: once per battle. The revive amount is a fixed HP pool (also Dendroid Shaman). | high |
| h3_hydra_upg_alt Ruinous Hydra | Regeneration | 25% of stack health | `heal_percent max_unit 0.25` = 25% of one creature | medium |
| h3_imp_upg Familiar | Energize | "an allied stack" | `untargetedCast`, simultaneous: probably every ally | medium, *uncertain* |
| h3_enchanter | Magnetic Slow | no duration | `magic_nairas_kiss_slow_effect` is `infinite`, `addition: data`: probably permanent and stacking | medium |
| h3_enchanter | Blessing | "an allied stack" | `allynoself` (cannot target itself) | low |
| h3_jotunn line | Frostbound Skies | "while this stack is present", no magnitude | Runtime applies an infinite -1 / -2 Speed buff at Unit.Init that persists after the Jotunn dies | medium |
| h3_sea_witch / h3_sorceress / Tidecaller | Weakening Shot | "stacks" | The Disrupting Ray rewrite buffs are `infinite` (they last all battle) | low |
| Medusa ×2, Basilisk ×2 | Stone Gaze | "petrify 1 round" | Melee-only. Target takes double basic damage and is immune to magic damage; dragons and embodiments are immune. | medium |
| Thunderbird Lightning Strike, Ice Elemental Blinding Strike, Lizard Assassin Poison Shot, the Necropolis curse family | | melee range not stated | `attackType_ melee` on actives (Poison Shot is "shot" by name but is melee and provokes retaliation) | low-medium |
| Magma Elemental Fireball, Plasma Elemental Chain Lightning, Lava Elemental Firewall | | no friendly-fire disclosure | `damageTarget_ all` / trap hits all units | medium |
| Sea Dog | Guillotine Shot | | Same undisclosed stacking `magic_decimate_effect` as Castle Execute had | medium |
| Seraph | Reality Distortion | | Delayed damage returns as Pure, and 20% is avoided; neither is stated | low |
| Cavalier Cavalry Press, Gore Demon Sapping Strike, Dragon Fly Weakening Dispel | | -3 / "initially" | `magic_shorten_shadow_effect_1` adds another -3/-3 each round | low |
| Halberdier | Halberd Hook | "stagger" | Nothing backs "stagger"; the damage is undisclosed pure magic | low |
| Dwarf | Shield Set | name implies defense | +5 Attack / +1 Initiative (text is accurate, name isn't) | low |
| Shadow Dragon Poison Sting, Haspid Venom, Sea Serpent Venomous Decay | | | Fatal Decay also blocks healing and revive; not stated | low |
| Factory Bombardier Mark, Ember Canister, Argali Frost Fracture | | not stated | free actions (`actionCost 0`); free-action text partly added in source | medium |

## 4. Missing or contradictory cards (not covered above)

**Missing Flying card** (`moveType fly`): Elemental Gargoyle, Genie Vizier. Both have empty passive lists.

**Missing Magic Channeler card:** Battle Mage (has the `manaCostBonus -2` side modifier).

**Missing no-retaliation card** (`triggerCounter false` with the card disabled in overrides): Faerie, Juggernaut.

**Contradictory or duplicate Melee Attack cards:**
- Gold Pegasus has a plain Melee Attack card, a "no counter" Melee Attack card, and Swift Strike.
- The same trio appears on Sentinel, Clockwork Automaton, Sprite, Psychic ×3, Corsair and Sea Dog.

**Design notes the installed data doesn't follow:**
- Lich Master still has Area Strike.
- Vermin still has Swift Strike.
- Medusa Warrior still has ranged cards.

**Stale `xHomm3ImplementationAudit.implementedMechanics`** (internal metadata only) on about 25 units across all factions. It describes donor kits instead of the installed ability.

## 5. Prior audit (2026-10-04) status

**Closed in the installed build:**
- Mummy Curse, Magnetic Slow cost and numbers, Faerie Dragon Blink, Fangarm keys
- Cavalier / Shambling Grasp / Zombie Clutch -3 text
- Radiant Armor 25%, Weakening Shot magnitudes, Armor Rend, Alert I (Hobgoblin)
- Earthshatter radius, Execute recast, Dragonflight friendly fire (vanilla behavior, disclosed)
- Fortress Mode, generic Melee / Ranged cards, Tower legacy passive promises (except Bloodless and Mind Spell Immunity)
- Harpy Hag / Fury keys

**Still open:**
- Rivulet Retreat
- Dendroid Binding release clause
- Bloodless and Mind Spell Immunity
- The 24-shot question, now resolved: the engine has no ammo (S4)
- Wolf Raider wording, now resolved as Double Strike

## 6. Could not determine statically

- The engine default for a missing `numCounters` (S6) and for a missing `actionCost` (S1). S1 assumes "ends the turn", because every native free row sets 0.
- Whether the `ability_no_start` Awaken gate is enforced on custom units (S2).
- Whether two vampirism selfMechanics stack additively.
- Whether `untargetedCast` Energize hits every ally.
- Whether an `infinite` buff overrides the ability's passed duration (Magnetic Slow).
- The `crit`, `additionalActionChanceModifier` and `outLevelAboveThreshold` semantics.
- Whether `unique_fractions_buff` matches custom HoMM3 factions.
- Whether the Marshal trap stamp writes a per-instance or a shared TrapConfig.

Per-faction agent notes (scratch, not tracked) are under the session scratchpad: `audit_nd/`, `sf_audit/`, `aud_neutral/`.
