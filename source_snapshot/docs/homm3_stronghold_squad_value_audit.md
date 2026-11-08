# HoMM3 Stronghold Squad Value Audit

Date: 2026-05-06

Source: `Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data/StreamingAssets/Core.zip`.

Scope: static audit of live Core unit logic and squad config. This does not run battles and does not simulate tactical AI. It compares `squadValue`, raw stat alignment, and how map squad `v` budgets translate into approximate creature counts.

## Finding

The Stronghold squad templates are not obviously under-budgeted versus vanilla: same-tier one-unit templates use the same base budgets as vanilla, and mixed templates are broadly in the same budget family. The larger issue is unit power calibration versus `squadValue`.

For Stronghold as the player's army, the likely auto-battle pain point is high-tier overvaluation: Cyclops and Behemoth variants consume roughly vanilla high-tier squad value while their raw stat profile is below the vanilla tier band. That gives the auto-battle system fewer bodies for the displayed/encounter value unless their special mechanics fully compensate. This matches the symptom "my auto-battle loses more than expected" better than a map-squad underbudget theory.

For Stronghold as neutral/enemy guards, the low and mid tiers do not look like hidden under-valued monsters. Tier 2 Wolf Rider variants are strong, but their `squadValue` is also high. Rocs and Ogres have high `squadValue` for their tier, so the map generator usually buys fewer of them, not more.

## Unit Calibration

| Tier | Variant | Unit | SquadValue | Raw stat alignment | SquadValue vs vanilla avg | Read |
|---:|---|---|---:|---:|---:|---|
| 1 | base | `h3_goblin` | 60 | -0.02 | 1.13x | near expected |
| 1 | upg | `h3_goblin_upg` | 90 | 1.09 | 1.29x | expensive for tier |
| 1 | alt | `h3_goblin_upg_alt` | 85 | 0.26 | 1.22x | near expected |
| 2 | base | `h3_wolf_rider` | 130 | 0.50 | 1.14x | near expected |
| 2 | upg | `h3_wolf_rider_upg` | 203 | 0.64 | 1.32x | expensive for tier |
| 2 | alt | `h3_wolf_rider_upg_alt` | 203 | 0.86 | 1.32x | expensive for tier |
| 3 | base | `h3_orc` | 192 | -0.68 | 1.14x | near expected |
| 3 | upg | `h3_orc_upg` | 240 | -0.91 | 1.01x | overvalued for raw stats |
| 3 | alt | `h3_orc_upg_alt` | 300 | 0.18 | 1.27x | expensive for tier |
| 4 | base | `h3_ogre` | 416 | -0.86 | 1.15x | overvalued for raw stats |
| 4 | upg | `h3_ogre_upg` | 672 | 0.31 | 1.28x | expensive for tier |
| 4 | alt | `h3_ogre_upg_alt` | 700 | 0.47 | 1.33x | expensive for tier |
| 5 | base | `h3_roc` | 1027 | 0.67 | 1.88x | expensive for tier |
| 5 | upg | `h3_roc_upg` | 1106 | 0.09 | 1.36x | expensive for tier |
| 5 | alt | `h3_roc_upg_alt` | 1150 | 0.42 | 1.41x | expensive for tier |
| 6 | base | `h3_cyclops` | 1266 | -1.86 | 0.93x | overvalued for raw stats |
| 6 | upg | `h3_cyclops_upg` | 1443 | -1.44 | 0.67x | near expected |
| 6 | alt | `h3_cyclops_upg_alt` | 1544 | -2.20 | 0.71x | near expected |
| 7 | base | `h3_behemoth` | 3162 | -1.72 | 0.86x | overvalued for raw stats |
| 7 | upg | `h3_behemoth_upg` | 6168 | -0.86 | 0.96x | overvalued for raw stats |
| 7 | alt | `h3_behemoth_upg_alt` | 6250 | -0.66 | 0.98x | near expected |

Most suspicious over-valued units by raw stats versus `squadValue`: `h3_roc`, `h3_ogre`, `h3_cyclops`, `h3_roc_upg`, `h3_behemoth`, `h3_orc`. These are the units where the displayed/engine value most risks promising more battlefield output than raw stats deliver.

No broad under-valued Stronghold pattern appears in the static stat data. The closest under-valued candidates are the low-tier fast attackers, especially the Wolf Rider line, but their `squadValue` is already at or above vanilla tier averages.

## Squad Template Pressure

`Budget` is the sum of `baseSquad.units[].v`. `Equivalent units` divides those budgets by each unit's `squadValue`; lower values mean the same encounter budget buys fewer creatures.

Tier-1 squad rows are included for completeness but should not drive balance conclusions: their `v` budgets are tiny special values in the source data, so equivalent-unit ratios are not meaningful there.

| Tier | Unit slots | Stronghold squads | SH budget avg | Vanilla budget avg | SH equivalent units | Vanilla equivalent units | SH/vanilla units |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 3 | 1 | 1 | 0.01 | 0.02 | 0.71x |
| 1 | 2 | 3 | 2 | 2 | 0.03 | 0.03 | 0.80x |
| 1 | 3 | 1 | 3 | 3 | 0.04 | 0.06 | 0.71x |
| 2 | 1 | 3 | 2502 | 2502 | 14.63 | 18.79 | 0.78x |
| 2 | 2 | 12 | 3144 | 3600 | 25.33 | 38.24 | 0.66x |
| 2 | 3 | 1 | 7506 | 7506 | 43.90 | 56.37 | 0.78x |
| 3 | 1 | 3 | 5003 | 5003 | 21.19 | 25.79 | 0.82x |
| 3 | 2 | 21 | 6809 | 6941 | 41.08 | 53.31 | 0.77x |
| 3 | 3 | 31 | 8564 | 8010 | 57.99 | 78.30 | 0.74x |
| 3 | 4 | 6 | 21044 | 20321 | 106.80 | 161.65 | 0.66x |
| 4 | 1 | 3 | 10004 | 10004 | 17.74 | 22.83 | 0.78x |
| 4 | 2 | 30 | 11026 | 11285 | 39.41 | 51.97 | 0.76x |
| 4 | 3 | 82 | 12162 | 12602 | 61.59 | 83.98 | 0.73x |
| 4 | 4 | 5 | 20012 | 20012 | 67.13 | 155.88 | 0.43x |
| 5 | 1 | 3 | 15005 | 15005 | 13.74 | 23.23 | 0.59x |
| 5 | 2 | 35 | 18525 | 17950 | 39.09 | 47.44 | 0.82x |
| 5 | 3 | 109 | 17312 | 17521 | 50.42 | 68.44 | 0.74x |
| 5 | 4 | 3 | 20012 | 20012 | 174.27 | 266.89 | 0.65x |
| 6 | 1 | 3 | 20006 | 20006 | 14.21 | 11.51 | 1.23x |
| 6 | 2 | 30 | 26389 | 28786 | 31.15 | 35.02 | 0.89x |
| 6 | 3 | 109 | 26659 | 26832 | 42.73 | 51.50 | 0.83x |
| 7 | 1 | 3 | 25007 | 25007 | 5.32 | 5.56 | 0.96x |
| 7 | 2 | 40 | 43291 | 38785 | 21.09 | 21.54 | 0.98x |
| 7 | 3 | 109 | 34647 | 34647 | 26.22 | 32.78 | 0.80x |

## Interpretation

- If Stronghold auto-battle is losing as the player's faction, first suspect high-tier unit `squadValue` being optimistic relative to actual battlefield output, especially Cyclops and Behemoth lines.
- If fights against Stronghold are estimated too easy, the current static data does not support a broad squad-template underbudget theory. The better suspects are specific ability semantics that are stronger in practice than their `squadValue`, or auto-battle AI mishandling the opposing army composition.
- Do not rebalance by changing only squad templates unless the map generator is the target. Unit `squadValue` changes are the lever that affects how many creatures a value budget buys and how armies compare in value-driven systems.
- Keep ability compensation explicit. This audit treats the raw stat gap as a warning, not final proof, because Cyclops ranged/AoE behavior, Behemoth armor penetration, Thunderbird lightning, and cloned donor passives can change real auto-battle output.
- Auto-battle is not just a squad-value formula: the release dump has `DataSquad.isAutobattle`, side `useMagicInAutoBattle`/`simulateBattle`, `UnitLogicConfig.saj/sak(EAbilityType)`, the `dxr` unit ability manager, and `BattleAiParams.topAbilityCasts`/mech evaluation fields. Native passives, auras, default attacks, counterattacks, and alternative attacks should therefore participate when the battle is simulated. Active `abilities[]` are less certain: they need AI scoring/targeting support and may be ignored or undervalued if the ability is only a custom approximation, UI-facing hook, or unsupported mechanic.
- Current release `DB/ai_battle/battle_ai_normal.json` and `battle_ai_hard.json` set `topAbilityCasts=1`. Their explicit `mechValues` cover heal, dispel, revive, substitute-by-hp, destroy stack/summon/temp stacks, assassinate, add energy, and global buff. Generic damage/debuff active abilities can often ride existing damage/buff scoring. Trap-placement abilities are riskier: the same config has `trapHexValue=-300`, so trap usefulness may need native AI scoring or a data redesign rather than just adding a new active button.
- Re-run this audit after any Core overlay change; Steam patches can replace `Core.zip`, and stale overlays will make squad and unit values disagree with the source tree.
