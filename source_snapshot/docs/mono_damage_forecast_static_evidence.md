# Mono-to-Deobf Battle Damage Forecast and Kill Mapping Evidence

Status: source-prepared/static-only. This document is not runtime proof.

## Why this exists

The damage histogram, retaliation forecast, and kill distribution code predate the current Mono-vs-deobf mapping. Several paths still mix real current surfaces with stale helper names and defensive reflection. This document separates the native-friendly surfaces from historical or stale assumptions.

## Mono reference shape

Focused Mono extract: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_priority_damage_forecast_decompiled.cs`.

Mono `DamageCalculatorUtility.GetKilledStacks(int unitDmg, Unit target)` computes kills from:

- `target.data.hpLastUnit`
- `target.stats.hp`
- `target.data.allStacks`

The algorithm is straightforward:

- if damage reaches the partial last unit HP, one creature dies;
- remaining damage is divided by per-creature HP;
- result is capped by current alive stack count.

Mono `UnitData` exposes the key semantic fields/properties:

- `fullStacks`
- `tempFullStacks`
- `hpLastUnit`
- `startBattleFullStacks`
- `visualStacks => fullStacks + 1`
- `allStacks => fullStacks + tempFullStacks + (hpLastUnit > 0 ? 1 : 0)`
- `sumHp => unit.stats.hp * (fullStacks + tempFullStacks) + hpLastUnit`

This is a strong semantic reference for the mod-side kill distribution math.

## Current deobf shape

Current named types survive:

- `Hex.Session.Battle.DamageUiParams`
- `Hex.Session.Battle.BhHealDamageForecastPanel`
- `Hex.Session.Battle.BhBattleUnitInfoView`
- `Hex.Session.Battle.BhBattleFieldObjectInfo`
- `Hex.Session.Battle.Unit`
- `Hex.Session.Battle.UnitData`

Current `DamageUiParams` is still a struct with:

- `eab caster`
- `eac castSource`
- `eaf target`
- `float dmgMult`
- `ESideCastType sideCastType`
- `int pathLength`

Current forecast panel call sites are statically pinned in ISIL:

- `BhBattleUnitInfoView.bddf(elk)` calls `BhHealDamageForecastPanel.Show(elk)`.
- `BhBattleUnitInfoView.bddg()` calls `BhHealDamageForecastPanel.Hide()`.
- `BhBattleFieldObjectInfo.bddf(elk)` calls `BhHealDamageForecastPanel.Show(elk)`.
- `BhBattleFieldObjectInfo.bddg()` calls `BhHealDamageForecastPanel.Hide()`.

Current `BhHealDamageForecastPanel.Show` dossier exists at:

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/damage_forecast_BhHealDamageForecastPanel_Show_dossier.md`

Current `UnitData.cs` exposes the important current storage:

- `public Unit unit` at offset `0x10`
- `public int fullStacks` at offset `0x34`
- `public int startBattleFullStacks` at offset `0x3C`
- related integer/float fields around offsets `0x1C..0x54`
- `public int bfda()`
- `public bool bfdf()`

Native UI call evidence shows `BhBattleUnitInfoView` and `BhTurnView` calling `UnitData.bfda()`, and `BhBattleUnitInfoView` calling `UnitData.bfdf()`.

## Current stale or weak assumptions

`GameSymbols.DamageKill.KilledStackGetter` still contains `bbfj`/`bbel`, but current `Hex.Session.Battle.Unit.cs` does not expose `bbfj`. Treat those names as stale unless a later current-build dossier proves a new equivalent helper.

The current dossier tool cannot resolve `Hex.Session.Battle.UnitData` to an ISIL file by public type name even though DiffableCs and caller ISIL clearly reference the type. This is a tooling/name-map gap, not evidence that the type is absent.

## Native-friendly implications

The preferred current route for kill/stack math is:

1. Use current forecast DTO fields from `DamageUiParams`/forecast object where available.
2. Read current `Unit.chjr` / `Unit.beyi()` to reach `UnitData`.
3. Use current `UnitData` fields/accessors for alive stack count and partial last-unit HP semantics.
4. Use Mono `DamageCalculatorUtility.GetKilledStacks` only as semantic algorithm evidence, not as a current method identity.

Do not chase stale `Unit.bbfj(int)` as the primary route unless a refreshed current dossier identifies a true equivalent method.

For forecast UI anchoring, patching panel `Show`/`Hide` is a valid UI surface. For computing forecast input, the cleaner native boundary is the caller pair `BhBattleUnitInfoView.bddf/bddg` and `BhBattleFieldObjectInfo.bddf/bddg`, because those are where current UI owners pass the forecast object into the panel.

## Existing mod implications

`DamageKillMapping.cs` is directionally correct in using `UnitData` semantics as a fallback, but it should stop presenting stale killed-stack helper names as equally authoritative. The reflection cache should prefer current `UnitData` field/accessor evidence and only use a helper method if current static/runtime metadata proves it.

`BattleForecastProbe.cs` should be treated as a diagnostic-era artifact. The current map gives specific caller/panel methods, so future fixes should replace broad probe logging with targeted, fail-closed mappings.

`RetaliationForecastFix.cs` currently has a disabled `BhHealDamageForecastPanel.Show(ekx)` patch with a note that `ekx` was removed. Current evidence says the active Show payload type is `elk`, not `ekx`.

## Gaps before implementation changes

- Refresh `GameSymbols.DamageKill` to remove or demote stale `bbfj`/`bbel` unless a current exact method is found.
- Build a current symbol-map row for `UnitData.bfda()` and `UnitData.bfdf()` despite the dossier public-type lookup gap.
- If histogram correctness changes are made, add an explicit unit-data reader contract rather than broad reflection over many old names.

## Evidence boundary

Static evidence proves the current type shape, the panel Show/Hide call sites, and the Mono kill algorithm. It does not prove that a particular Harmony patch timing is safe, nor does it prove forecast DTO lifetime or pooled panel reuse behavior at runtime.
