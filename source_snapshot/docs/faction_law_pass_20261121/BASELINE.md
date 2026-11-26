# Faction law pass: baseline (2026-11-21)

Measured from the installed GE Core (`V:/SteamLibrary/.../Golden Era/.../Core.zip`, Core b9029ce2), tables `DB/fractions_laws/fractions_laws_table_*.json` and trees `DB/fractions/*.json` (`fractionLawsLines`). The full per-law dump (every law, rank, column, level, cost and bonus) is `V:/olden_port_work/law_pass_20261121/law_dump.txt`; the scripts that made it are next to it (`dump_laws.py`, `baseline.py`, `band.py`).

**Rank** = line of the law tree. Lines unlock at 0 / 5 / 15 / 30 / 50 spent law points. Each line has a **kingdom** column (group 0: economy, hero, magic, map) and an **army** column (group 1: creatures).

## 1. Count per rank

Cell = kingdom/army laws placed, total levels (L), total cost of all levels (c).

| faction | laws | r0 | r1 | r2 | r3 | r4 |
|---|---|---|---|---|---|---|
| human | 31 | 3/3 L9 c19 | 3/3 L10 c29 | 4/3 L12 c37 | 4/3 L14 c41 | 3/2 L8 c24 |
| undead | 32 | 4/3 L13 c30 | 4/3 L14 c33 | 4/3 L11 c29 | 3/2 L8 c29 | 3/3 L7 c29 |
| dungeon | 34 | 3/3 L10 c26 | 4/4 L12 c28 | 4/4 L14 c42 | 4/3 L10 c33 | 3/2 L7 c21 |
| nature | 31 | 3/2 L11 c22 | 3/3 L12 c25 | 4/2 L10 c25 | 4/3 L16 c47 | 4/3 L10 c31 |
| demon | 30 | 4/3 L12 c28 | 3/3 L12 c28 | 3/4 L10 c28 | 2/2 L8 c22 | 3/3 L12 c44 |
| unfrozen | 35 | 3/3 L13 c29 | 4/4 L13 c32 | 4/3 L12 c32 | 4/4 L10 c32 | 3/3 L7 c25 |
| **vanilla band** | **30-35** | **3-4/2-3, c19-30** | **3-4/3-4, c25-33** | **3-4/2-4, c25-42** | **2-4/2-4, c22-47** | **3-4/2-3, c21-44** |
| bulwark | 31 | 3/2 L9 c19 | 3/4 L12 c26 | 4/2 L10 c29 | 3/3 L13 c36 | 4/3 L12 c32 |
| castle | 31 | 3/3 L12 c27 | 3/3 L11 c27 | 4/3 L13 c36 | 4/3 L13 c34 | 3/2 L6 c20 |
| conflux | 31 | 3/3 L11 c24 | 2/4 L10 c29 | 3/2 L7 c20 | 3/4 L11 c33 | 4/3 L10 c29 |
| cove | 31 | 3/3 L11 c26 | 3/3 L10 c26 | 4/3 L10 c30 | 3/4 L13 c32 | 2/3 L6 c19 |
| dungeon (H3) | 34 | 3/4 L12 c31 | 4/4 L13 c39 | 4/3 L10 c30 | 3/4 L10 c30 | 2/3 L7 c26 |
| factory | 32 | 4/2 L11 c26 | 3/4 L13 c33 | 4/3 L12 c36 | 4/3 L15 c38 | 2/3 L6 c22 |
| fortress | 31 | 3/3 L11 c24 | 2/3 L7 c20 | 3/3 L8 c25 | 3/4 L13 c35 | 4/3 L11 c32 |
| inferno | 30 | 4/2 L11 c27 | 3/4 L11 c32 | 4/3 L15 c38 | 2/4 L11 c31 | 2/2 L5 c18 |
| necropolis | 32 | 3/4 L12 c30 | 3/4 L12 c34 | 3/4 L10 c28 | 2/4 L8 c29 | 3/2 L5 c22 |
| rampart | 31 | 3/3 L12 c25 | 2/4 L9 c27 | 3/3 L10 c26 | 3/4 L9 c27 | 4/2 L10 c27 |
| stronghold | 34 | 4/4 L14 c34 | 4/4 L13 c37 | 4/4 L11 c33 | 3/3 L9 c21 | 2/2 L4 c17 |
| tower | 31 | 3/3 L11 c28 | 3/4 L12 c31 | 4/3 L14 c32 | 3/4 L14 c38 | 2/2 L5 c15 |

**Count is roughly right.** Every custom tree is 30-34 laws. Gaps against the band:

- **Rank 4 is thin** for stronghold (2/2, c17), tower (2/2, c15), inferno (2/2, c18), cove (2/3, c19) and castle (3/2, c20). Vanilla rank 4 is 6-7 laws worth c21-44: the capstones live there.
- **Rank 1 or 2 is thin** for fortress (r1 2/3 c20, r2 3/3 c25) and conflux (r2 3/2 c20).
- Every table has 34 rows, but 1-4 rows per faction are dormant (outside the tree). Seventeen of these are listed in `DORMANT_LAW_OVERRIDE_SIDS_OUTSIDE_LAW_LINES`.

## 2. Functional mix

Laws per category (script `baseline.py`, `cat()`; a growth law counts as unit-line).

| faction | economy | map | hero | magic | focus/faction | enemy-hex | army | unit-line |
|---|---|---|---|---|---|---|---|---|
| human | 8 | 1 | 4 | 4 | 0 | 0 | 7 | 7 |
| undead | 7 | 0 | 3 | 2 | 5 | 1 | 7 | 7 |
| dungeon | 10 | 3 | 1 | 3 | 1 | 0 | 2 | 14 |
| nature | 9 | 2 | 0 | 4 | 1 | 1 | 6 | 8 |
| demon | 9 | 2 | 0 | 3 | 1 | 0 | 5 | 10 |
| unfrozen | 9 | 0 | 3 | 3 | 1 | 2 | 3 | 14 |
| bulwark | 11 | 1 | 1 | 4 | 0 | 0 | 8 | 6 |
| castle | 8 | 2 | 2 | 4 | 1 | 0 | 7 | 7 |
| conflux | 7 | 1 | 2 | 3 | 2 | 0 | 11 | 5 |
| cove | 8 | 1 | 2 | 4 | 0 | 0 | 9 | 7 |
| dungeon (H3) | 7 | 1 | 3 | 4 | 0 | 1 | 10 | 8 |
| factory | 8 | 1 | 3 | 4 | 0 | 1 | 8 | 7 |
| fortress | 7 | 1 | 3 | 4 | 0 | 0 | 9 | 7 |
| inferno | 7 | 1 | 2 | 4 | 1 | 0 | 8 | 7 |
| necropolis | 8 | 0 | 1 | 4 | 0 | 1 | 10 | 8 |
| rampart | 8 | 2 | 2 | 2 | 0 | 1 | 7 | 9 |
| stronghold | 10 | 1 | 2 | 4 | 0 | 1 | 7 | 9 |
| tower | 7 | 0 | 2 | 6 | 0 | 0 | 8 | 8 |

The category totals look vanilla. What they hide:

### 2a. Shared scaffold (fine, vanilla does it too)

Every vanilla tree has Resource Riches I/II/III (kingdom column, ranks 0/2/4), Tax Collectors and one "Mining: <resource>" law at rank 1, and one "Elite <unit>" growth law per creature tier. All 12 custom trees copy this scaffold, which is correct.

### 2b. Generic laws cloned into every custom tree (the main problem)

| Law | In | Vanilla equivalent |
|---|---|---|
| Defensive Drills (hero Defence +2/+4) | all 12 | Human only ("Training: Defense") |
| Arcane Exercises (hero Spell Power +2/+4) | all 12 | Human only |
| Quartermaster Ledgers (hero Knowledge +2/+4) | all 12 | Human only |
| Swift Reflexes (all creatures +1 Initiative, cost 5) | all 12 | Human only |
| Native Mastery (+1 Speed and +1 Initiative on native terrain) | 7 | Undead "Return to the Soil" (+1 Speed only, cost 5) |
| Melee / ranged formation (+5/10% dealt, -5/10% taken) | most | Human only (and it is Human's identity law) |
| Counterattack doctrine (row 13, runtime per faction) | 10 | Human "Vengeful Strike" |
| Encouragement / morale trigger +1/2/3% per point | 3+ | Human, Demon (with Luck) |
| "Low/High <school> Lore" spell access | all 12 | Human / Undead / Demon / Unfrozen each own one school |

In vanilla, no two factions share a non-scaffold law. Here 8 non-scaffold laws (or their exact clones under new names) sit in every tree, so ~25% of each tree is the Human tree.

### 2c. Unique-skill interaction

Laws that read or boost the faction's own mechanic:

| Vanilla | Count | Examples |
|---|---|---|
| Undead | 5 | Animate Dead I-V (Necromantic Energy cap, Necromancy Power) |
| Dungeon | 7 | each Elite law multiplies that unit's Fighting Style damage |
| Demon | 4 | Hive Offsprings I-III (Fire Larvae), Mana Devour (Hive heroes) |
| Unfrozen | 3 | The Abyss Stares Back (Communion), Cold Shoulder (Involuntary Summons), Call of the Deep (summons) |
| Nature | 2 | Elite Mancers (abilities do not end turn), Sanctuary (ability Focus cost) |
| Human | 1-2 | Power of Faith, Focus is the Key (out of tree) |

**Custom: 0 in every faction.** Stronghold's "Warcry Lore" only grants Day spells, so Warcry appears in the name alone. Necropolis has no necromancy law, even though Necropolis is the faction where vanilla shows exactly how to write one.

### 2d. Identity

Apart from the unit-line growth laws and the clones, most custom laws are vanilla effects with a faction-flavoured name ("Spoils Ledger" = Coinage Reform, "Tomb Archives" = Laws of the Immortals). That is acceptable for scaffold rows, but no faction has the 3-6 signature laws a vanilla tree has (Undead: Death Equalizes All, Bloodthirst, Terra Mortis, Black Death, Death's Presence; Nature: Woodland Resistance, Live Roots, Fairy Tale).

## 3. Magnitude bands (vanilla, per law)

The lines below give the vanilla anchor for each kind of law: the rank it sits at, its cost per level, and its strength.

| Effect | Vanilla anchor (rank, cost/level, value) |
|---|---|
| Daily gold | r0-1, 2-3, 250/500/750 (Human 500/1000) |
| Daily rare resource | r1, 2, 1/2 |
| Gold income % | r2, 4/2/2, 10/15/20% |
| Construction resource discount | r2, 2-3, -20/-40% |
| Extra building per day | r2, 3, +1 |
| Creature cost | r3, 4/3/3, -10/-15/-20% (own faction only) |
| Astrology points daily | r0-1, 1-2, 250; r3 3/level 500/1000/1500; r0 6 for 500 |
| Hero sight radius | r0, 2, +1 (Grove heroes r4 +2/+4 with movement) |
| Hero movement | r2, 5/level, +10/+20; r4 Grove +15/+30 |
| Hero primary stat | r1 2/level +1/2/3 (one stat) or r3 3/level +2/+4; Triumvirate r3 +1/+2 to three stats |
| Hero Morale / Luck | r1 3 for +1 Morale; r0 3/level +1/+2 Luck |
| Spell school +1 level | r2, 3 |
| All schools +1/+2 levels | r4, 4/level |
| Learn any tier, all schools | r4, 3 (Temple heroes only) |
| Spell cooldown -1 (own) / +1 (enemy) | r3, 3-4 |
| Focus | start +1 r0 4; +1 per round r4 2; Focus cap +1 r4 3; enemy -1 per round r4 4 |
| All creatures +1 Initiative | r1, 6 |
| All enemies -1 Initiative | r2, 6 (with -1 Speed: r4, 5) |
| +1 Speed on native terrain | r3, 5 |
| +1/+2/+3 Attack and Defence conditional (own area / foreign area / native terrain) | r0-3, 2-3/level |
| Melee or ranged +5/+10% dealt and -5/+10% taken | r2, 4/level |
| Counterattack damage +50/+100% | r3, 3/level |
| +1 counterattack per round | r4, 4 |
| All creatures +1/+2 Damage | r4, 4/level |
| Morale trigger +1/2/3% per point | r3-4, 3/level |
| Lucky Strike damage +25/+50% | r1, 2/level |
| Damage over time taken by enemies +25/+50% | r0, 2/level |
| Magic damage taken -5/-10/-15% | r0, 2/level |
| Vampirism +50% | r2, 6 |
| Outgoing and incoming damage ±5% (a faction-scoped swing) | r4, 5 |
| Elite T1-2 line | 3+2; growth +4/+4 (Undead +4/+8); stat +2/+4 Defence, +1/+2 damage, +3/+6 Attack, +1 Initiative |
| Elite T3-4 line | 3+2; growth +2/+2; +3/+6 Attack and Defence, +5/+10 HP, +2 Initiative, or a qualitative rider |
| Elite T5-7 line | 3+2; growth +1/+1; +3/+6 Attack and Defence and +1 Speed; +15/+30 HP; 10/20% armour pen; +6-+20 max damage |
| Qualitative elite riders | Always max damage (T2, Nature), counterattacks twice (T1), abilities do not end the turn (T5), ability cooldown -1/-2 (T4) |

## 4. Custom values outside the band

The full list comes from `band.py`. These are the ones that matter:

- **Castle Cavalry Logistics:** hero movement +200. Vanilla gives +10/+20, so this is 10x.
- **Sight radius:** +2/+4/+6 at rank 0 (Conflux, Fortress, Inferno, Castle, Rampart). Vanilla gives +1 at rank 0.
- **outAllDmgMod +10% for all creatures at rank 0-1** (Conflux, Cove, Fortress, Inferno, Necropolis), and ±10/15% in Conflux, Dungeon, Fortress and Necropolis. Vanilla's only global ±% damage law is ±5% at rank 4, and it is conditional.
- **Hero Morale +2:** Castle, Conflux, Factory, Fortress, Inferno, Rampart, Stronghold, Tower. Vanilla has +1 Morale at most.
- **Law points +40/+60% (Necropolis):** vanilla caps at +30%.
- **Hero Spell Power / Knowledge to Attack / Defence 25%** (Factory, Tower). Vanilla caps at 20% over 3 levels.
- **Two extra buildings per day (Dungeon):** vanilla gives +1.
- **Learn any tier of one school:** in all 12 trees at rank 3-4, cost 3-4. Vanilla has this only for Temple heroes (every school).
- **Text and data disagree:** "Heroes can learn tier 1 Day spells" is backed by `magicSchoolSet day 0 1`, which vanilla uses for "+1 level to Daylight spells".

## 5. Summary

1. **Counts:** within the band. Strengthen rank 4 for stronghold, tower, inferno, cove and castle, and the thin r1/r2 lines for fortress and conflux.
2. **Function:** the scaffold is right. Eight clone laws, ~25% of each tree, are Human's tree copied 12 times. Replace them with faction laws.
3. **Unique skill:** custom trees have zero laws that touch it. Vanilla has 1-7 per faction (median 3).
4. **Power:** about a dozen values are above the vanilla band, most of them at low rank. Bring them back into the band.
