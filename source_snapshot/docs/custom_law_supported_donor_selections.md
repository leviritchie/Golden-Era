# Custom law supported donor selections

Generated: 2026-06-15

This pass removes unsupported/runtime-only suggestions from the rethink list and applies the most fun remaining supported donor/native substitute as law overrides.

## Selection rule

- Supported means the bonus type and parameter shape exists in the law editor schema and/or in shipped Core law rows.
- Runtime-only proposals such as Avenger mark reads, corpse consumption, Gating identity, Warcry execution, reward commit hooks, terrain predicates, and construction category validation were excluded from this donor pass.
- Some selected rows are explicit design compromises: they preserve faction flavor with supported passive/native effects but lose event filters or conditional triggers.
- Resource Riches remains untouched.

## High-flavor supported selections

| Faction | Best supported donor choices applied |
|---|---|
| Castle | support-duration blessing rhythm for Liturgical Rhythm, while exact spell cooldown filtering remains runtime debt. |
| Cove | extra counterattack boarding, ranged/melee gunline pressure, morale, gold income, extra build, battle Focus readiness. |
| Dungeon | Squad/enemy info reveal, enemy vulnerability, enemy speed/initiative suppression, terror morale suppression, ore excavation, spell supported tempo substitute. |
| Fortress | Damage reduction, extra counters, enemy slow/initiative pressure, debuff-duration resistance, daily gold, enemy spell cooldown increase. |
| Rampart | Critical chance hunter flavor, counterattack reprisal, melee/ranged hunter rows, gold income, supported tempo substitute. |
| Tower | Hero Spell Power creature scaling, counterattack wards, initiative synchronization, market extra-charge removal, extra-action chance, supported tempo substitute. |
| Conflux | Static elemental family aspect buffs, owned-object planar sight, counterattack/ranged/melee rows, rare-resource income, supported tempo substitute. |
| Inferno | Summon scaling, hellgate sight, all-damage assault, enemy vulnerability, daily gold, frenzy action chance, extra build, supported tempo substitute. |
| Necropolis | Intelligence, counterattack death grip, death-march morale/speed pressure, over-time vulnerability, daily gold, extra build, enemy cooldown pressure. |
| Stronghold | Speed, counterattack damage, all-damage crush, enemy vulnerability, gold income, action chance rage, enemy cooldown pressure. |

## Excluded as not donor-supported

| Mechanic class | Reason |
|---|---|
| Avenger mark laws | Need real Avenger state; no safe donor row can target marked units. |
| Corpse economy | Needs logical corpse count/spend state; static mana/gold/vampirism are only compromises. |
| Gating-only Inferno buffs | Need temporary/gated unit identity; summon scaling is the supported substitute. |
| Warcry laws | Need real Warcry execution/cooldown; enemy cooldown pressure is the supported substitute. |
| Plunder/reward/capture economy | Needs reward/capture commit hooks; gold rows are supported substitutes. |
| Building category discounts | Need construction validation/cost hooks; broad extra-build/discount rows are substitutes only. |
| Terrain/road/swamp predicates | Need map tile reads; sight/slow rows are substitutes only. |

## Audit correction

A follow-up audit rejected unsupported or weakly-proven rows: `unitStat energyPerRound`, `unitStat vampirismHealMultiplier`, and friendly `heroStat magicCdBonus -1`. Those rows were removed and replaced with supported alternatives: `numCounters`, counterattack damage modifiers, `startEnergyLevelsBonus`, `maxEnergyLevelsBonus`, `inComingBuffDuration`, and enemy `heroStatBattle magicCdBonus +1`.
