# Castle (homm3_castle): faction law draft, 2026-11-21

Draft only. Nothing is built.

## 1. Identity and levers

The HoMM3 Castle is the knights' kingdom: Stables for long marches, the Brotherhood of the Sword, the Griffin Bastion, Clerics of the Day school and Angels against Devils. Gems are the tier-7 pressure (Angel line). The unit trade axis is **Cleave (striker) vs Lance (ward)**. Halberdier, Marksman, Crusader, Zealot and Champion lean striker. Glaivier, Royal Griffin, Archangel and the `_upg_alt` wards lean ward.

The faction skill is **Elite Strategem**. A Castle hero toggles one of three free world-magic orders (Spread Out at Basic, Compress at Advanced, Ambush at Expert). The order rearranges the enemy army at the start of the hero's **next neutral battle**, then it is used up. The laws should make a Castle player feel like a general who plans the field before the fight, and should read like the HoMM3 town.

Levers. Paths are under `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/` unless they say otherwise.

| Lever | Where | Current value |
|---|---|---|
| Mode per hero | `Homm3CastleEliteStrategemRuntime.cs:54` `ModesByHeroId`; set on cast in `PrefixNecromancyWorldMagicCast` `:170-216` | one mode per hero id |
| Neutral-only gate | `Homm3CastleEliteStrategemRuntime.cs:261-273`: `side.typeInWorld != TransferSide.EType.Type_Squad \|\| side.hero != null` → log "opponent is not a neutral army", return (token kept) | neutral squads only |
| One-shot consumption | `Homm3CastleEliteStrategemRuntime.cs:280` `ModesByHeroId.Remove(ownerHeroId)` | used up by the first neutral battle |
| Placement | `TryApplyEnemyPlacementMode` (~`:359`); Spread → `BuildSpreadUnits(LinearSlots)` `:657`; Compress → `BuildCompressedUnits(CenterSlots)` `:630` | `MaxBattleStacks = 7` (`:41`), `LinearSlots {0..6}` (`:42`), `CenterSlots {3,2,4,1,5,0,6}` (`:43`) |
| Ambush | owner repositioned to `LinearSlots` (`:297-308`); arena and side order swapped in `TryApplyAmbushArenaLayout` `:386`; `AmbushArenaLogicSid = "battleArena_homm3_castle_elite_strategem_ambush"` (`:40`) | Expert only |
| Mode spells | `tools/release_port/apply_release_core_overlay.py:7476-7500`, built by `make_homm3_castle_elite_strategem_magic_rows` `:16853` | `manaCost [0,0,0,0]` |
| Ambush arena | same overlay `:16893` | `tacticsPlacementSid battlePlacement_standart`, `blockTacticsPhase False` |
| Subskills | overlay `:7524-7534`, `:16906` | L2 Forward Scouts (enemy hero info + scouting 1.5), Signal Drills (start Focus +1), Valley Advantage (native ±10%); L3 Shield Wall, Rapid Redeployment (+1 Initiative), Coordinated Volley |
| Law reader | `Homm3CustomFactionLawRuntime.cs:319` `TryResolveActiveKnownCustomLaw`; indices limited by `KnownRuntimeLawIndices` `:51` | family indices only |

Every (S) law below hooks one of three points: the cast (`:170-216`), the gate (`:261-273`) or the application (`:280` to `:386`). "A Strategem took effect" means the application step ran (the gate passed and a placement was written).

## 2. Tree

Receivers: "line" = base, `_upg` and `_upg_alt` (for example `h3_pikeman, h3_pikeman_upg, h3_pikeman_upg_alt`). "All Castle" = all 21 Castle SIDs.

| Rank | Col | # | Name | Text (player-facing) | Levels (cost: value) | Build | Anchor |
|---|---|---|---|---|---|---|---|
| r0 | K | 3 | Resource Riches I | Provides 2500 Gold, 5 Wood and 5 Ore when enacted. | 1: once | A scaffold | scaffold |
| r0 | K | 2 | Royal Scouts | Your heroes gain +1 Sight radius. | 2: +1 | A `heroStat viewRadius 1` | vanilla Sight r0, 2, +1 (was +2/+4) |
| r0 | K | 33 | Chapel Calendar | Produces 250/500 Astrology points daily. | 2: 250 / 2: 500 | A `astrologyExp 250/500` | Human astrology r0, 2. Third level (750) cut. |
| r0 | K | 5 | Standing Orders **(S)** | Your heroes' Elite Strategem order is no longer used up by battle. It stays until you give a new order. | 2: on | D: skip `ModesByHeroId.Remove` (`:280`) when the law is owned | r0 hero utility for 2 (Sight +1). Saves a recast; no new power. |
| r0 | A | 4 | Elite Pikemen | Pikeman growth +4/+8. Pikemen counterattack twice per round. | 3: +4 / 2: +4 | A `cityUnitsIncrement h3_pikeman 4`; `unitStat numCounters 1` (line) | T1 qualitative rider (counterattacks twice). Set Pikes and Braced Pikes fire on every counter. |
| r0 | A | 10 | Elite Archers | Archer growth +4/+8. Archers always deal maximum Damage. | 3 / 2 | A `cityUnitsIncrement h3_archer 4`; `unitBoolStat alwaysMaxDmg true` (line) | Elite Twinkles rider (Nature T1) |
| r0 | A | 34 | Liturgical Rhythm | Positive effects on friendly Castle creatures last 1 additional round. | 3: +1 | A `unitStat inComingBuffDuration 1` (all Castle) | Cold Touch r2 4/level covers both directions; one direction at 3. Second level (+2) cut. |
| r1 | K | 1 | Tax Collectors | Produces 250/500 Gold daily. | 2 / 2 | A scaffold | scaffold |
| r1 | K | 14 | Mining: Gems | Produces 1/2 Gems daily. | 2 / 2 | A `sideRes gemstones 1/2` | scaffold (Angel line costs Gems) |
| r1 | K | 6 | Knightly Training | Your heroes gain +1/+2/+3 Attack. | 2 / 2 / 2 | A `heroStat offence 1/2/3` | r1 primary stat, 2/level. Also the plugin's native-law seed (index 6, rank 1). |
| r1 | K | 22 | Brotherhood of the Sword **(I)** | Friendly creatures gain +1 Morale. | 3: +1 | A `heroStat moral 1` | vanilla Morale r1, 3, +1 (was +1/+2). HoMM3 Castle building. |
| r1 | A | 11 | Elite Griffins | Griffin growth +2/+4. Griffins gain +2 Initiative. | 3 / 2 | A `cityUnitsIncrement h3_griffin 2`; `unitStat initiative 2` (line) | T3-4 rider +2 Initiative (Elite Undead Pets). Lets Alert and Talon Riposte griffins strike before the enemy closes. |
| r1 | A | 17 | Elite Swordsmen | Swordsman growth +2/+4. They gain +3/+6 Attack and Defence. | 3 / 2 | A `cityUnitsIncrement h3_swordsman 2`; `unitStat offence 3/6`, `defence 3/6` (line) | T3-4 rider (Elite Qilins). Shield Brother and Double Strike are hits, so the stat feeds the kit. |
| r2 | K | 16 | Resource Riches II | Provides 5000 Gold, 10 Wood and 10 Ore when enacted. | 2: once | A scaffold | scaffold |
| r2 | K | 21 | Prosperous Holdings | Your sources of Gold produce +10%/+15%/+20% Gold. | 4 / 2 / 2 | A `sideStat resPercentIncrementSet gold 0.10/0.15/0.20` | Coinage Reform r2 4/2/2 (unchanged) |
| r2 | K | 15 | Daylight Liturgy **(I)** | Your heroes gain +1 level in the Daylight school. | 3: +1 | A `heroStat magicSchoolSet day 0 1` (data unchanged) | vanilla one school +1 level, r2, 3. **Text fixed:** the old text said "learn tier 1 Day spells"; the data was already +1 level. |
| r2 | K | 26 | Stables **(I)** | Your heroes gain +10/+20 movement points. | 5 / 5 | A `heroStat movementBonus 10/20` | vanilla Movement r2, 5/5 (was +200 for 4 at r4). HoMM3 Castle building. |
| r2 | A | 23 | Elite Monks | Monk growth +1/+2. Using their abilities does not end their turn. | 3 / 2 | A `cityUnitsIncrement h3_monk 1`; `unitBoolStat ignoreAbilityActionCost true` (line) | Elite Mancers (T5 rider). Brand of Faith and Benediction become cast-then-shoot. |
| r2 | A | 20 | Drilled Deployment **(S)** | In battles where your Elite Strategem took effect, your creatures deal +10%/+20% Damage in round 1. | 3 / 3 | D + B: on application, add `h3_law_castle_drilled_effect` (`cloneOf` a 1-round damage buff, `set outAllDmgMod 0.10/0.20`, duration 1) to each own stack | +10% all damage is r0-1 at full time; one round and only after a Strategem, so r2 at 3/level |
| r3 | K | 7 | War College **(S)** | Your heroes gain +15%/+30% experience from battles where their Elite Strategem took effect. | 3 / 3 | D: on application, add a hidden hero buff `h3_law_castle_war_college` with `expPerBonus 0.15/0.30`, removed when the battle ends | Unfrozen hero experience 0.10/0.20 at 4/4; neutral battles with a Strategem only |
| r3 | K | 9 | Crown Contracts | Castle creatures cost -10%/-15%/-20% Gold. | 4 / 3 / 3 | A creature cost discount, Castle receivers (vanilla Creature cost shape) | vanilla Creature cost r3, 4/3/3 |
| r3 | K | 28 | Mason's Charter | Buildings cost 20%/40% less Ore. | 3 / 3 | A `constructionDiscount ore -0.20/-0.40` | Construction discount r2, 3 (unchanged; moved r2 → r3) |
| r3 | A | 24 | Elite Cavaliers | Cavalier growth +1/+2. They gain +3/+6 Attack and Defence and +1 Speed. | 3 / 2 | A `cityUnitsIncrement h3_cavalier 1`; `unitStat offence 3/6`, `defence 3/6`, `speed 1` (line) | T5-7 rider (Elite Cave Dragons). +1 Speed is one more Jousting hex. |
| r3 | A | 8 | Ambush Doctrine **(S)** | When your Ambush takes effect, enemy creatures lose 2/4 Initiative and 2/4 Defence until the end of round 1. | 4 / 3 | D + B: after `TryApplyAmbushArenaLayout` (`:386`) succeeds, add `h3_law_castle_ambushed_effect` (`cloneOf` a slow debuff, `set initiative -2/-4`, `defence -2/-4`, duration 1) to each enemy stack | Tactical Advantage (enemies -1 Initiative, r2, 6, whole battle); Expert-only, one round |
| r3 | A | 32 | Defend the Realm | When battling in an area you control, friendly creatures gain +1/+2/+3 Attack and Defence. | 2 / 2 / 2 | A same shape as Veiled by the Trees (Nature, own-area condition) | vanilla conditional A/D, 2/level |
| r4 | K | 29 | Resource Riches III | Provides 7500 Gold, 15 Wood and 15 Ore when enacted. | 3: once | A scaffold | scaffold |
| r4 | K | 27 | High Daylight | Your heroes can learn Daylight spells of every tier. | 3: on | A `heroStat magicSchoolSet day 5 0` | Power of Faith (r4, 3). One school, Castle's Cleric school. |
| r4 | K | 31 | Grand Strategem **(S)** | Your heroes' Spread Out and Compress also work against armies led by enemy heroes on the adventure map (not in towns or garrisons). At the second level, Ambush works against them too. | 5: Spread/Compress / 4: + Ambush | D: widen the gate (`:261-273`) to `Type_Hero` sides; keep sieges and garrisons blocked; L1 still blocks Ambush against heroes (token kept) | Terra Mortis (r3, 6) and Live Roots (5): rule-changing single levels |
| r4 | A | 30 | Elite Angels | Angel growth +1/+2. The cooldowns of their abilities are reduced by 1/2 rounds. | 3 / 2 | A `cityUnitsIncrement h3_angel 1`; `unitStat abilityCdBonus -1/-2` (line) | Elite Scorpions rider. Shield of Faith, Resurrection and Wrathful Chalice are 3/3. Resurrection stays once per battle. |
| r4 | A | 12 | Holy Crusade **(I)** | Castle creatures deal +5%/+10% Damage to undead and demons. | 3 / 3 | B: the native modifier behind Smite (`custom_factions/unit_designs/homm3_castle.json:670`, +30% vs undead and demons), at 0.05/0.10, all Castle | faction-scoped ±5% swing (r4, 5). Two enemy classes only, so 3/level. HoMM3 Angels vs Devils. |

## 3. Removed or changed

| Old # | Old name | Fate |
|---|---|---|
| 1 | Tax Collectors | kept |
| 2 | Road Wardens (sight +2/+4) | changed: **Royal Scouts**, +1 at 2 (band fix) |
| 3 | Resource Riches I | kept |
| 4 | Pikeman Muster | changed: **Elite Pikemen**, rider +1/+2 max Damage → counterattacks twice |
| 5 | (dormant) | now **Standing Orders (S)** |
| 6 | Battle Readiness (start Focus +1, 4, r3) | replaced by **Knightly Training**. The old law duplicated the Signal Drills subskill. |
| 7 | Defensive Drills | replaced by **War College (S)** (Human clone removed) |
| 8 | Arcane Exercises | replaced by **Ambush Doctrine (S)** (Human clone removed) |
| 9 | Quartermaster Ledgers | replaced by **Crown Contracts** (Human clone removed) |
| 10 | Archer Muster | changed: **Elite Archers**, always max Damage |
| 11 | Griffin Muster | changed: **Elite Griffins**, +2 Initiative |
| 12 | Swift Reflexes | replaced by **Holy Crusade** (Human clone removed) |
| 13 | Royal Retaliation (+1 counterattack, 4) | dormant (counterattack doctrine clone) |
| 14 | Mining: Gems | kept |
| 15 | Daylight Liturgy | text fixed (+1 Daylight level); data unchanged |
| 16 | Resource Riches II | kept |
| 17 | Swordsman Muster | changed: **Elite Swordsmen**, +3/+6 A/D |
| 18 | Line Doctrine | dormant (formation clone) |
| 19 | Volley Doctrine | dormant (formation clone) |
| 20 | (dormant) | now **Drilled Deployment (S)** |
| 21 | Prosperous Holdings | kept |
| 22 | Righteous Zeal (Morale +1/+2) | changed: **Brotherhood of the Sword**, +1 at 3 (band fix) |
| 23 | Monk Muster | changed: **Elite Monks**, abilities do not end the turn |
| 24 | Cavalier Muster | changed: **Elite Cavaliers**, T5-7 rider |
| 25 | Encouragement | dormant (Human clone) |
| 26 | Cavalry Logistics (movement +200, r4) | changed: **Stables**, +10/+20 at 5/5, moved r4 → r2 (band fix) |
| 27 | High Daylight (cost 4) | cost 4 → 3 (vanilla capstone price) |
| 28 | Mason's Charter | moved r2 → r3 |
| 29 | Resource Riches III | kept |
| 30 | Angel Muster (+5/+10% damage) | changed: **Elite Angels**, ability cooldown -1/-2 |
| 31 | (dormant) | now **Grand Strategem (S)** |
| 32 | Native Mastery | replaced by **Defend the Realm** (Human clone removed) |
| 33 | Chapel Calendar | third level cut |
| 34 | Liturgical Rhythm | second level cut; moved to the army column |

Dormant after this pass: 13, 18, 19, 25.

## 4. Power check

| Rank | Kingdom / army | Total cost | Band | OK |
|---|---|---|---|---|
| r0 | 4 / 3 | 1+2+4+2 + 5+5+3 = **22** | 19-30 | yes |
| r1 | 4 / 2 | 4+4+6+3 + 5+5 = **27** | 25-33 | yes |
| r2 | 4 / 2 | 2+8+3+10 + 5+6 = **34** | 25-42 | yes |
| r3 | 3 / 3 | 6+10+6 + 5+7+6 = **40** | 22-47 | yes |
| r4 | 3 / 2 | 3+3+9 + 5+6 = **26** | 21-44 | yes (old r4 was 20) |

- **Totals:** 30 laws, total cost 149.
- **(S) laws:** 5. Standing Orders r0, Drilled Deployment r2, War College r3, Ambush Doctrine r3, Grand Strategem r4.
- **(I) laws:** 4. Brotherhood of the Sword, Daylight Liturgy, Stables, Holy Crusade.
- **Hero primary-stat laws:** 1 (Attack). **Learn laws:** 1 (High Daylight, one school).
- Out-of-band fixes: sight +2/+4 → +1; Morale +2 → +1; movement +200 → +10/+20.

## 5. Plugin asks

**Generic D reader.** Same ask as every faction: `TryGetCustomLawLevel(object sideOrHero, string factionSid, int index, out int level)` beside `TryResolveActiveKnownCustomLaw` (`:319`), which today accepts only `KnownRuntimeLawIndices` (`:51`). Strategem resolves the owner hero at cast time and at `BattleLogic.Init`; the reader must use that hero's owner side.

| # | Law | File / line | Change | Hook |
|---|---|---|---|---|
| 5 | Standing Orders | `Homm3CastleEliteStrategemRuntime.cs:280` | if level ≥ 1, do not remove the mode; log "kept (Standing Orders)" | existing. Recasting the same mode must stay a no-op toggle-off as today, so the player can still clear an order. Check `:170-216` toggle logic. |
| 20 | Drilled Deployment | after the placement write in `TryApplyEnemyPlacementMode` (~`:359`) and after `:386` for Ambush | add the 1-round damage buff to every owner stack | **new:** needs the owner's battle stacks at Init; if they do not exist yet, defer to the first `RoundStarted`. Buff via `Homm3BuffDebuffNativeAdapter`. |
| 7 | War College | same application point | add the hidden hero exp buff for this battle; clear on battle end | **new:** confirm `expPerBonus` is read at the battle-result exp award, not cached at map load. Fallback: multiply the awarded exp in a battle-result postfix. |
| 8 | Ambush Doctrine | after `TryApplyAmbushArenaLayout` (`:386`) returns true | add the 1-round debuff to every enemy stack | same deferral as #20 |
| 31 | Grand Strategem | gate `:261-273` | L1: accept `Type_Hero` sides with a hero for Spread/Compress; L2: also Ambush. Keep `Type_City`/garrison sides blocked. | existing gate. Ambush against a hero must also check the arena swap does not break the enemy hero's tactics phase (`blockTacticsPhase False` at overlay `:16893`). |

**B (new buffs):** `h3_law_castle_drilled_effect`, `h3_law_castle_ambushed_effect`, `h3_law_castle_war_college` (hidden). **C:** none.

**Index families (build note).** 2 (sight), 6 (primary stat), 15 (school low), 21 (gold %), 22 (morale), 27 (school high) and 33 (astrology) keep laws of their own family. 28 (extra construction) keeps Mason's Charter and 34 (spell cooldown) keeps Liturgical Rhythm, as today; the build must confirm no family consumer acts on those two rows. The native-law seed constant (`Homm3CustomFactionLawRuntime.cs:21-23`, castle index 6 rank 1) now matches the tree (Knightly Training is rank 1); today's row 6 is rank 3.

**Verify before build:** the Smite modifier name for Holy Crusade; the creature cost-discount bonus name for Crown Contracts (copy the vanilla row); `heroStat moral` vs a unit-side morale bonus (copy the current row 22 shape).

## 6. Open questions

1. **Ambush against heroes.** Grand Strategem L2 lets Ambush (arena swap, owner repositioned) hit enemy hero armies. **Recommend keeping L2** but proving one hero battle with tactics in the port copy first. If the swap misbehaves, ship L1 only (cost 5) and r4 drops to 22, still in band.
2. **Standing Orders value.** Orders are free to cast (`manaCost 0`), so the law is mostly convenience. **Recommend keeping it at r0 for 2:** it is the r0 skill law and costs no power. The stronger alternative (one free extra Strategem charge for a second hero) needs per-player mode state and is not worth it.
3. **High Daylight scope.** One school (Daylight) at the vanilla price 3, or every school like Power of Faith? **Recommend Daylight only.** Tower is the spell town; Castle's Clerics fit the Day school, and the cross-faction review should keep "every school" rare.
4. **Brotherhood of the Sword as a siege law.** HoMM3's building gave +2 Morale in town defence. A siege-only condition has no confirmed native lever. **Recommend the flat +1** now; revisit if an own-town condition is found.
