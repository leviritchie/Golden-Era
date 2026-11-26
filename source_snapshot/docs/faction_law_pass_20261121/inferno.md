# Inferno (homm3_inferno): faction law draft, 2026-11-21

Draft only. Nothing is built.

## 1. Identity and levers

The HoMM3 Inferno is the demon city: the Castle Gate between Inferno towns, the Order of Fire, Brimstone Stormclouds over the grail, Pit Lords raising Demons, and Mercury as the tier-7 pressure. The unit trade axis is **Breacher vs Holder**. The faction verb is **Burning**: a burning creature takes Magic Damage each time it moves (`h3_kit_inferno_burning_effect`, `_lesser_effect`, `h3_kit_inferno_scorched_effect`; see `docs/unit_ability_pass_20261121/inferno.md:5`). Enemies must choose between holding still and taking damage.

The faction skill is **Gating** (reserved-slot design, owner 2026-11-13; always open since 2026-11-14). The hero reserves army slots; those stacks are held out of deployment and arrive through a gate during the battle. The old Core text about summoning Imps and Gogs is retired. The laws should make the gate wider, earlier, more dangerous where it opens, and should tie arrivals to Burning.

Levers. Paths are under `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/` unless they say otherwise.

| Lever | Where | Current value |
|---|---|---|
| Entry round | `Homm3InfernoGatingRuntime.cs:63` `EntryRound` | 2 |
| Reserved slots | `ResolveAllowedSlots` `Homm3InfernoGatingRuntime.cs:301-311` (callers `:349`, `:440`, `:468`) | base 1, +1 Wider Gate, +1 Efficient Gate (max 3 of 7) |
| Skill rank | `ResolveRank` `:299` | 1-3 |
| Subskill flags | `:497-499` Rapid, Shielded, OpenGate | per hero |
| Entry timing | `:781-793`: Basic/Advanced enter at the start of round 2; Expert in round 2 only if faster than the current unit (`:792`), else at its own initiative slot | |
| Entry hex | `CollectEntryHexes(hexes, side.Rank >= 2 ? side.HomeSign : 0, side.Rank >= 2)` `:953`; random pick `:964` | enemy half from Advanced; random |
| On-entry buffs | `:993-996`: Shielded → `BarrierBuffSid` (`:60`, `homm3_inferno_gating_barrier_bonus`, 1 charge); Rapid → `HasteBuffSid` (`:61`, `magic_haste_effect_1`) | |
| Open Gate ability | `skill_faction_homm3_inferno_ability_open_gate` (~`:854-904`); `tools/release_port/homm3_inferno_gating_core_overlay.py:39` `OPEN_GATE_FOCUS_COST`; row `energyLevel`, `cd 0` (~`:209-211`) | 2 Focus, needs the Open Gate subskill |
| Subskills | overlay `SUBSKILLS_BY_LEVEL` | L2 Wider Gate, Rapid Gate, Lava Advantage; L3 Efficient Gate, Open Gate, Shielded Arrival |
| Reserved state | hidden hero buff bits `homm3_inferno_gating_slot_*` | |
| Law reader | `Homm3CustomFactionLawRuntime.cs:319`; indices limited at `:51` | family indices only |

## 2. Tree

Receivers: "line" = base, `_upg` and `_upg_alt`. "All Inferno" = all 21 Inferno SIDs. "Gated stack" = a stack that arrived through the Gate this battle.

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 3 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A scaffold | scaffold |
| r0 | K | 2 | Hellgate Omens | Your heroes gain +1 Sight radius. | 2: +1 | A `heroStat viewRadius 1` | vanilla Sight r0, 2 (was +2/+4/+6) |
| r0 | K | 5 | Gate Sigils **(S)** | Gated stacks arrive in the enemy half of the battlefield from Basic Gating. At the second level, they arrive next to an enemy stack when a hex is free. | 2: enemy half / 2: next to an enemy | D: L1 pass `HomeSign` and `true` to `CollectEntryHexes` (`:953`) at any rank; L2 filter the hex list to hexes adjacent to an enemy stack before the pick (`:964`), falling back to the full list | r0 hero utility 2/level (Sight +1). Positioning only. |
| r0 | A | 4 | Elite Imps | Imp growth +4/+8. Imps gain +1 Initiative. | 3: +4 / 2: +4 | A `cityUnitsIncrement h3_imp 4`; `unitStat initiative 1` (line) | T1-2 rider +1 Initiative. Heckle and Magic Channel act sooner. |
| r0 | A | 10 | Elite Gogs | Gog growth +4/+8. They gain +3/+6 Attack. | 3 / 2 | A `cityUnitsIncrement h3_gog 4`; `unitStat offence 3/6` (line) | T1-2 rider +3/+6 Attack |
| r0 | A | 26 | Hellfire Brands **(I)** | Damage over time dealt to enemy creatures increases by 25%/50%. | 2 / 2 | A vanilla DoT-taken bonus on enemies (same row as today, second level added) | vanilla DoT +25/+50%, r0, 2/level (was r3, one level at 4). Burning is Inferno's verb. |
| r1 | K | 1 | Tax Collectors | Produces 250/500 Gold daily. | 2 / 2 | A scaffold | scaffold |
| r1 | K | 14 | Mining: Mercury | Produces 1/2 Mercury daily. | 2 / 2 | A `sideRes mercury 1/2` | scaffold; moved r2 → r1 |
| r1 | K | 6 | Order of Fire **(I)** | Your heroes gain +1/+2/+3 Spell Power. | 2 / 2 / 2 | A `heroStat spellPower 1/2/3` | r1 primary stat, 2/level. HoMM3 Order of Fire (+Power). |
| r1 | A | 8 | Infernal Arrival **(S)** | When a stack arrives through the Gate, adjacent enemy stacks are set Burning until the end of the next round. | 3: on | D + B: in the entry step (`:993-996`) add `h3_kit_inferno_burning_lesser_effect` (caster = the gated stack) to each adjacent enemy stack | Hellfire Brands r0 2/level; a free Burning splash on a once-per-stack event |
| r1 | A | 11 | Elite Hell Hounds | Hell Hound growth +2/+4. They gain +2 Initiative. | 3 / 2 | A `cityUnitsIncrement h3_hell_hound 2`; `unitStat initiative 2` (line) | T3-4 rider +2 Initiative. Fast hounds reach the stacks that just moved (Run Down) before those stacks act again. |
| r1 | A | 17 | Elite Demons | Demon growth +2/+4. The cooldowns of their abilities are reduced by 1/2 rounds. | 3 / 2 | A `cityUnitsIncrement h3_demon 2`; `unitStat abilityCdBonus -1/-2` (line) | Elite Scorpions (T4). Infernal Bargain is 1/3, Gore and Bloodied Fury are active. |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A scaffold | scaffold |
| r2 | K | 15 | Brimstone Rites **(I)** | Your heroes gain +1 level in the Primal school. | 3: +1 | A `heroStat magicSchoolSet primal 0 1` | vanilla one school +1 level, r2, 3 (Demon row, dump `:1419`) |
| r2 | K | 7 | Legion Gate **(S)** | Your heroes' Gating holds 1 more reserved stack. | 5: +1 | D: `ResolveAllowedSlots` (`:301-311`) returns base + subskills + 1 | Twin Grafts / Live Roots (rule-changing single level, 5). Expert with both subskills: 4 of 7 slots. |
| r2 | K | 21 | Soul Furnace | Destroyed artifacts give your heroes Alchemical Dust. | 2 / 2 / 2 | unchanged row | unchanged (custom, no vanilla twin) |
| r2 | A | 23 | Elite Pit Fiends | Pit Fiend growth +1/+2. Using their abilities does not end their turn. | 3 / 2 | A `cityUnitsIncrement h3_pit_fiend 1`; `unitBoolStat ignoreAbilityActionCost true` (line) | Elite Mancers (T5). Crack the Whip, Raise Demons and Flay become act-then-strike. |
| r2 | A | 24 | Elite Efreeti | Efreeti growth +1/+2. Their attacks ignore 10%/20% of the target's Defence. | 3 / 2 | A `cityUnitsIncrement h3_efreeti 1`; `unitStat armorPen 0.10/0.20` (line) | T5-7 rider (armour pen) |
| r2 | A | 22 | Frenzy | Friendly creatures gain +1 Morale. | 3: +1 | A `heroStat moral 1` | vanilla Morale r1, 3, +1 (was +1/+2) |
| r3 | K | 9 | Open Gate Rites **(S)** | Your heroes can use Open Gate from Basic Gating. At the second level, Open Gate costs 1 Focus Charge. | 3: granted / 3: cost 1 | D: L1 treat the OpenGate flag (`:499`) as set; L2 Focus cost 2 → 1 (overlay `:39` today; needs a runtime read, see section 5) | Focus laws r4 2-4; an active granted early |
| r3 | K | 20 | Hellfire Rites | Your heroes' spells deal +10%/+20% Damage. | 3 / 3 | A vanilla magic damage bonus (today's row, third level cut) | Demon magic damage +10/20/30%, r4, 3/level; earlier, so two levels (was r2 with three) |
| r3 | K | 28 | Blood Mortar | You can build one additional building per day in your cities. | 3: on | A extra building per day | vanilla r2, 3 (was 6 at r4) |
| r3 | A | 12 | Lingering Brimstone **(I)** | Negative effects on enemy creatures last 1 additional round. | 3: +1 | A `unitStat inComingDebuffDuration 1` on enemies (Cold Touch enemy half) | Cold Touch r2 4/level both directions; one direction at 3. Burning lasts a round longer. |
| r3 | A | 32 | Hellforged **(I)** | Inferno creatures deal +10% Damage to Burning enemies. | 5: on | C: `damage_vs_buff` percent 10, buffs `[h3_kit_inferno_burning_effect, h3_kit_inferno_burning_lesser_effect, h3_kit_inferno_scorched_effect]`, all Inferno | faction-scoped ±5% swing (r4, 5); conditional on Burning |
| r4 | K | 29 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A scaffold | scaffold |
| r4 | K | 27 | Grand Gatecraft | Your heroes can learn Primal spells of every tier. | 3: on | A `heroStat magicSchoolSet primal 5 0` | Power of Faith (r4, 3); was r3 at 4 |
| r4 | K | 34 | Brimstone Stormclouds **(I)** | Enemy heroes lose 1 Focus Charge at the start of each round. | 4: -1 | A vanilla enemy-Focus drain row | vanilla enemy -1 Focus per round, r4, 4. HoMM3 grail name. |
| r4 | K | 33 | Soul Bargain | Inferno creatures cost -10%/-15%/-20% Gold. | 4 / 3 / 3 | A creature cost discount, Inferno receivers | vanilla Creature cost r3, 4/3/3 |
| r4 | A | 30 | Elite Devils | Devil growth +1/+2. Devils always deal maximum Damage. | 3 / 2 | A `cityUnitsIncrement h3_devil 1`; `unitBoolStat alwaysMaxDmg true` (line) | qualitative rider (Elite Hoplets/Twinkles). Blink strikes land at full weight. |
| r4 | A | 31 | Brimstone Vanguard **(S)** | Stacks that arrive through the Gate deal +15%/+30% Damage until the end of the round they arrive. | 3 / 3 | D + B: in the entry step (`:993-996`) add `h3_law_inferno_vanguard_effect` (`cloneOf` a 1-round damage buff, `set outAllDmgMod 0.15/0.30`) to the gated stack | +1/+2 Damage to all creatures (r4, 4/level); gated stacks only, one round |

## 3. Removed or changed

| Old # | Old name | Fate |
|---|---|---|
| 1 | Tax Collectors | kept |
| 2 | Hellgate Omens (sight +2/+4/+6) | +1 at 2 (band fix) |
| 3 | Resource Riches I | kept |
| 4 | Imp Muster | changed: **Elite Imps**, +1 Initiative |
| 5 | Gating Circles (start Focus +1, 3) | replaced by **Gate Sigils (S)** (generic Focus law; vanilla price is 4) |
| 6 | Infernal Ascension (+10% all damage, r0) | replaced by **Order of Fire** (out of band) |
| 7 | Defensive Drills | replaced by **Legion Gate (S)** (Human clone removed) |
| 8 | Arcane Exercises | replaced by **Infernal Arrival (S)** (Human clone removed) |
| 9 | Quartermaster Ledgers | replaced by **Open Gate Rites (S)** (Human clone removed) |
| 10 | Gog Muster | changed: **Elite Gogs** |
| 11 | Hell Hound Muster | changed: **Elite Hell Hounds** |
| 12 | Swift Reflexes | replaced by **Lingering Brimstone** (Human clone removed) |
| 13 | Hellfire Reprisal (counter damage +50%) | dormant (counterattack doctrine clone) |
| 14 | Mining: Mercury | moved r2 → r1 |
| 15 | Hellfire Rites (magic damage, r2) | moved to #20 at r3, two levels; #15 is now **Brimstone Rites** |
| 16 | Resource Riches II | kept |
| 17 | Demon Muster | changed: **Elite Demons**, ability cooldown rider |
| 18 | Hellpack Assault | dormant (formation clone) |
| 19 | Hellpack Volley | dormant (formation clone) |
| 20 | Brimstone Whips (melee +10%, 4) | replaced by **Hellfire Rites** (half of the formation clone) |
| 21 | Soul Furnace | kept |
| 22 | Frenzy (Morale +1/+2) | +1 at 3 (band fix), moved r3 → r2 |
| 23 | Pit Fiend Muster | changed: **Elite Pit Fiends**, moved r3 → r2 |
| 24 | Efreeti Muster | changed: **Elite Efreeti**, moved r3 → r2 |
| 25 | Frenzy (morale and crit chance) | dormant (duplicate name; Encouragement clone) |
| 26 | Hellfire Brands | moved r3 → r0, 2/2 |
| 27 | Grand Gatecraft (r3, 4) | moved to r4, cost 3 |
| 28 | Blood Mortar (6, r4) | cost 3, moved r4 → r3 |
| 29 | Resource Riches III | kept |
| 30 | Devil Muster (+5/+10% damage) | changed: **Elite Devils**, always max Damage |
| 31 | (dormant) | now **Brimstone Vanguard (S)** |
| 32 | (dormant) | now **Hellforged** |
| 33 | (dormant) | now **Soul Bargain** |
| 34 | (dormant) | now **Brimstone Stormclouds** |

Dormant after this pass: 13, 18, 19, 25.

## 4. Power check

| Rank | Kingdom / army | Total cost | Band | OK |
|---|---|---|---|---|
| r0 | 3 / 3 | 1+2+4 + 5+5+4 = **21** | 19-30 | yes |
| r1 | 3 / 3 | 4+4+6 + 3+5+5 = **27** | 25-33 | yes |
| r2 | 4 / 3 | 2+3+5+6 + 5+5+3 = **29** | 25-42 | yes |
| r3 | 3 / 2 | 6+6+3 + 3+5 = **23** | 22-47 | yes |
| r4 | 4 / 2 | 3+3+4+10 + 5+6 = **31** | 21-44 | yes (old r4 was 18) |

- **Totals:** 30 laws, total cost 131.
- **(S) laws:** 5. Gate Sigils r0, Infernal Arrival r1, Legion Gate r2, Open Gate Rites r3, Brimstone Vanguard r4.
- **(I) laws:** 6. Hellfire Brands, Order of Fire, Brimstone Rites, Lingering Brimstone, Hellforged, Brimstone Stormclouds.
- **Hero primary-stat laws:** 1 (Spell Power). **Learn laws:** 1 (Grand Gatecraft).
- Out-of-band fixes: sight +6 → +1; +10% all damage at r0 removed; Morale +2 → +1; extra building 6 → 3.

## 5. Plugin asks

**Generic D reader.** `TryGetCustomLawLevel(object sideOrHero, string factionSid, int index, out int level)` beside `TryResolveActiveKnownCustomLaw` (`:319`). Gating already resolves `DataHero` for slots and the battle side for entry; the reader must work from both (hero → owner side).

| # | Law | File / line | Change | Hook |
|---|---|---|---|---|
| 5 | Gate Sigils | `Homm3InfernoGatingRuntime.cs:953`, `:964` | L1: enemy-half args at rank 1; L2: prefer hexes adjacent to an enemy stack | existing entry step; keep the random pick inside the filtered list |
| 8 | Infernal Arrival | `:993-996` | add the lesser Burning buff to adjacent enemies, cast by the gated stack | existing; **verify** the lesser buff's tick damage scales with the caster stack (Brimstone: "2 per Magog"). If it reads a Magog-only count, clone it as `h3_law_inferno_arrival_burning` with a fixed per-creature value. |
| 7 | Legion Gate | `ResolveAllowedSlots` `:301-311` | +1 when owned | existing; the reserve UI (`:349`, `:440`, `:468`) already reads the same function. Losing the law cannot happen in normal flow; if slots exceed the cap, keep the lowest bits as Gating already does on a rank drop. |
| 9 | Open Gate Rites | flag `:499`; Focus cost overlay `:39` | L1: OpenGate flag true; L2: cost 1 | **new for L2:** Focus cost is baked into the ability row by the overlay. Either add a second ability row (`..._open_gate_rites`, cost 1) and swap which one the hero holds, or have the plugin refund 1 Focus after the cast. Recommend the refund (no Core change). |
| 31 | Brimstone Vanguard | `:993-996` | add the 1-round damage buff to the gated stack | existing step |

**B (new buffs):** `h3_law_inferno_vanguard_effect` (and the optional arrival Burning clone). **C:** Hellforged needs the kit-runtime table to grant a `damage_vs_buff` rule to all Inferno SIDs while the law is owned. That is a law-gated runtime rule, which `build_unit_kit_runtime_table.py` does not have today: ask for a `lawGate {faction, index}` field on a runtime entry (one ask shared with Necropolis Culling and Death's Toll).

**Effect profile:** `Homm3CustomLawEffectProfiles.cs` has an Inferno "Frenzy" profile (`death-sacrifice-gated-loss`). Confirm which index it keys on. It belonged to the morale-trigger Frenzy (#25, now dormant); #22 Frenzy is a plain native Morale row and must not pick it up.

**Index families (build note).** 2, 6, 15, 22 and 27 hold laws of their own family. 21 (gold %) keeps Soul Furnace as today, 28 holds Blood Mortar (its own family), and 33 (astrology) and 34 (spell cooldown) now hold Soul Bargain and Brimstone Stormclouds. The build must confirm no family consumer acts on Inferno rows 21, 33 and 34.

## 6. Open questions

1. **Legion Gate at r2.** Four of seven stacks held back is a big swing: most of the army arrives in round 2, safe from round-1 shots. **Recommend r2 at 5.** Held stacks also miss round 1 entirely, so the law trades tempo for safety; if testers find it too strong, move it to r3 (r2 → 24 would drop below band, so swap it with Blood Mortar).
2. **Gate Sigils L2 (arrive next to an enemy).** This lets a Basic Inferno hero drop a stack into melee at the start of round 2. **Recommend keeping it** at r0 L2: the stack still waits a full round, and Gating's Advanced rule already opens the enemy half.
3. **Castle Gate (town teleport).** HoMM3's signature Inferno building has no native law lever. **Recommend leaving it out** of the tree; it belongs to a town-building pass, not to laws.
4. **Soul Furnace kept as is.** It was not reviewed for band (2/2/2, dust per destroyed artifact). **Recommend keeping** it until dust income is measured in a playtest.
