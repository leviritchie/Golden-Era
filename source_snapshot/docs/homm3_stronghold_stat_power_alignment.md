# HoMM3 Stronghold Stat Power Alignment

Date: 2026-05-02

Scope: stats only. This ignores abilities, passives, attack shape, growth, cost, faction laws, hero bonuses, and visuals.

Source of record: live `HeroesOE_Data/StreamingAssets/Core.zip` unit logic JSON, especially `DB/units/units_logics/homm3_stronghold/*.json`.

Comparison set: live Olden Era faction unit logic rows for `humans`, `dungeon`, `nature`, `undead`, `demons`, and `unfrozen`. Most tier/variant buckets have six OE comparator rows. Tier 4 base has seven because Demons also have base-only `lava_larva`.

Method: compare each Stronghold unit's `hp`, `offence`, `defence`, average damage, `initiative`, and `speed` against same-tier/same-variant OE units. The `Stat alignment` score is the mean z-score across those six raw stat categories. `squadValue` is listed as a useful engine-side sanity check, but it can reflect more than raw stats and should not be treated as the main stat-only answer.

## Overall Finding

The HoMM3/ToA Stronghold line is not evenly scaled to Olden Era.

- Tiers 1-2 are fast and attack-heavy, often above same-tier OE units despite poor HP and damage.
- Tiers 3, 6, and 7 are the main underpowered stat bands.
- Tiers 4-5 land closer to the OE tier band, but do it with lopsided profiles: high offence/speed, low defence/damage.
- The largest structural mismatch is that HoMM3 high-tier creatures have much lower offence, defence, and damage than OE's high-tier baselines. Abilities such as Behemoth defense reduction can hide that in practice, but they are out of scope for this stat-only pass.

## Tier Summary

| Variant | Tier | Stronghold unit | Stat alignment | SquadValue vs OE | Main stat shape |
|---|---:|---|---|---|---|
| base | 1 | `h3_goblin` | In tier band (-0.03) | 60 vs OE avg 56, range 29-84, rank 4/7 | high offence, initiative, speed; low hp, defence, avgDmg |
| base | 2 | `h3_wolf_rider` | In tier band (+0.55) | 130 vs OE avg 110, range 86-144, rank 3/7 | high offence, defence, initiative, speed; low hp, avgDmg |
| base | 3 | `h3_orc` | Below tier (-0.90) | 192 vs OE avg 187, range 110-233, rank 5/7 | high offence; low hp, defence, avgDmg |
| base | 4 | `h3_ogre` | In tier band (-0.01) | 416 vs OE avg 307, range 100-463, rank 2/8 | high offence; low defence |
| base | 5 | `h3_roc` | In tier band (-0.22) | 1027 vs OE avg 658, range 339-908, rank 1/7 | high speed; low defence, avgDmg |
| base | 6 | `h3_cyclops` | Below tier (-1.95) | 1266 vs OE avg 1332, range 952-1595, rank 5/7 | low hp, offence, defence, avgDmg, initiative |
| base | 7 | `h3_behemoth` | Below tier (-1.64) | 3162 vs OE avg 3610, range 1875-4620, rank 6/7 | low hp, offence, defence, avgDmg, initiative |
| upg | 1 | `h3_goblin_upg` | Above tier (+0.69) | 90 vs OE avg 74, range 38-111, rank 3/7 | high offence, initiative, speed; low hp, defence, avgDmg; carries Alert I/two counters |
| upg | 2 | `h3_wolf_rider_upg` | Above tier (+0.96) | 203 vs OE avg 148, range 115-191, rank 1/7 | high offence, initiative, speed; low hp, avgDmg |
| upg | 3 | `h3_orc_upg` | Below tier (-0.99) | 240 vs OE avg 262, range 156-326, rank 5/7 | low defence, avgDmg |
| upg | 4 | `h3_ogre_upg` | In tier band (-0.06) | 672 vs OE avg 496, range 370-671, rank 1/7 | high hp, offence; low defence, avgDmg |
| upg | 5 | `h3_roc_upg` | In tier band (-0.08) | 1106 vs OE avg 980, range 505-1366, rank 3/7 | high speed; low offence, defence, avgDmg |
| upg | 6 | `h3_cyclops_upg` | Below tier (-1.49) | 1443 vs OE avg 2126, range 1530-2527, rank 7/7 | low hp, offence, defence, avgDmg, initiative |
| upg | 7 | `h3_behemoth_upg` | Below tier (-0.90) | 6168 vs OE avg 6319, range 3259-8009, rank 5/7 | high speed; low offence, defence, avgDmg, initiative |
| alt | 1 | `h3_goblin_upg_alt` | In tier band (+0.19) | 85 vs OE avg 74, range 38-111, rank 3/7 | high initiative, speed; low hp, offence, avgDmg |
| alt | 2 | `h3_wolf_rider_upg_alt` | Above tier (+0.93) | 203 vs OE avg 148, range 115-191, rank 1/7 | high offence, defence, speed |
| alt | 3 | `h3_orc_upg_alt` | In tier band (-0.34) | 300 vs OE avg 262, range 156-326, rank 3/7 | high offence; low avgDmg |
| alt | 4 | `h3_ogre_upg_alt` | In tier band (+0.19) | 700 vs OE avg 496, range 370-671, rank 1/7 | high hp, offence, speed; low defence, avgDmg |
| alt | 5 | `h3_roc_upg_alt` | In tier band (+0.00) | 1150 vs OE avg 980, range 505-1366, rank 3/7 | high initiative, speed; low defence, avgDmg |
| alt | 6 | `h3_cyclops_upg_alt` | Below tier (-1.84) | 1544 vs OE avg 2126, range 1530-2527, rank 6/7 | low hp, offence, defence, avgDmg, initiative |
| alt | 7 | `h3_behemoth_upg_alt` | Below tier (-0.67) | 6250 vs OE avg 6319, range 3259-8009, rank 5/7 | high speed; low offence, defence, avgDmg |

## Balance Implications

Tier 1 is mostly acceptable as a glassy, fast low-tier line. Do not buff every visible low stat or it will stop feeling like HoMM3 Goblins; HP and average damage are intentionally low compared with OE.

Tier 2 is overtuned on raw stats for Olden Era. Wolf Rider variants are already among the highest same-tier entries by offence/speed and by `squadValue`; adding full ability parity without stat reductions would likely overshoot.

Tier 3 is weak on stat quality despite acceptable `squadValue`. The Orc line's HoMM3 shooter identity leaves it with very low defence and damage for OE tier 3.

Tier 4 is broadly usable. Ogre variants are carried by HP/offence/speed and dragged down by defence/damage. The upgraded and alternate Ogres have top-end `squadValue`, so avoid broad stat buffs unless abilities are reduced.

Tier 5 is broadly usable but skewed. Roc variants are fast flyers with low defence and damage. Their high `squadValue`, especially base Roc, means ability handling and mobility can matter more than raw stat averages.

Tier 6 is the biggest stat problem. All Cyclops variants are below OE tier 6 on almost every raw category except speed. If only stats are being balanced, this tier needs the most direct uplift.

Tier 7 is also under-statted versus OE, mostly in offence/defence/damage/initiative. Behemoth HP becomes acceptable only on the upgraded form; base and Ghost Behemoth are low for OE tier 7. Be careful interpreting this because defense-reduction passives are intentionally ignored here.

## Agent Notes

When revisiting this comparison, read from live `Core.zip` or regenerate it first. Do not compare only against the generator constants if the zip may be stale.

Do not use `squadValue` alone for a stat-only judgment. It is useful for spotting engine-side intent, but high values on Roc/Ogre and low values on Cyclops can conflict with the raw-stat z-score picture.

Do not mix abilities into this table. Wolf Raider double attack, Thunderbird lightning, Behemoth armor penetration, and Blood-Eyed Cyclops range behavior can materially change combat power, but they belong in the ability mapping docs instead.
