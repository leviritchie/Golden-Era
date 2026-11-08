# Steam Hotfix — Orphaned Patches

These patches were disabled (via `// FIXME(steam):` or `#if false` blocks) because the
target methods or types were removed/renamed in the Steam release compared to the
May 6 playtest build. Each needs investigation and re-mapping.

## 1. BattleTooltipProbe.cs — 7 patches

The methods `tbw`, `tbx`, `tby`, `tca`, `tcb` on `BhTooltipUnit` and `tch`, `tar` on
`BhTooltipUnitCountLosses` no longer exist. These were the first obfuscated method in
their respective named types after filtering; positional shift is likely.

| Line | Old Patch Target |
|------|-----------------|
| 67   | `[HarmonyPatch(typeof(BhTooltipUnit), nameof(BhTooltipUnit.tbw))]` |
| 100  | `[HarmonyPatch(typeof(BhTooltipUnit), nameof(BhTooltipUnit.tbx))]` |
| 115  | `[HarmonyPatch(typeof(BhTooltipUnit), nameof(BhTooltipUnit.tby))]` |
| 130  | `[HarmonyPatch(typeof(BhTooltipUnit), nameof(BhTooltipUnit.tca))]` |
| 145  | `[HarmonyPatch(typeof(BhTooltipUnit), nameof(BhTooltipUnit.tcb))]` |
| 160  | `[HarmonyPatch(typeof(BhTooltipUnitCountLosses), nameof(BhTooltipUnitCountLosses.tch))]` |
| 175  | `[HarmonyPatch(typeof(BhTooltipUnitCountLosses), nameof(BhTooltipUnitCountLosses.tar))]` |

**Action**: Search the live dump.cs for each named type's new first obfuscated method.

## 2. Homm3StrongholdCityMusic.cs — 8 patches (entire registry-group block)

The methods `mok`, `czu`, `blzt`, `lle` on type `fvh` and `nev`, `blzo`, `fih`, `kfb`
on type `fvf` were all removed/renamed. These types were obfuscated sound-registry
types. The fingerprint matcher found a near-identical type `fvi`/`fvg` but the methods
didn't carry over.

| Line(s) | Old Type | Methods |
|---------|----------|---------|
| 34-37 | `fvh` | `mok`, `czu`, `blzt`, `lle` |
| 39-42 | `fvf` | `nev`, `blzo`, `fih`, `kfb` |

**Action**: Determine if `fvi`/`fvg` replaced `fvh`/`fvf` entirely, or if these methods
moved to other types. Look at the live dump.cs for methods on `fvi`/`fvg` with matching
signatures (should be near-identical structural fingerprints).

## 3. Homm3StrongholdTownLayers.cs — 2 patches

| Line | Old Patch Target |
|------|-----------------|
| 1490 | `[HarmonyPatch(typeof(BhCityUISession), nameof(BhCityUISession.tvw))]` |
| 1535 | `[HarmonyPatch(typeof(Hex.Session.City.BhBuildingsManager), nameof(Hex.Session.City.BhBuildingsManager.baeq))]` |

**Status (May 11 follow-up)**: Fixed the release-safe dynamic hook list in `Plugin.cs`.
Do not treat the two commented static attributes as direct rename targets:
`BhCityUISession.tvw` is not present on `BhCityUISession` in either the May 6 or live
dump, and `baeq` belongs to `Hex.Session.City.BhBuilding`, not `BhBuildingsManager`.
The live Steam `BhCityUISession` methods used for refresh coverage are
`giq`, `gir`, `hrn`, `txm` through `tyc`; the live `BhBuildingsManager` refresh
methods are `bagh`, `bagi`, `bagj`, `bagk`, and `bagl`.
The release-safe profile still skips the older legacy city-open hook; that log line is
not a failure of the dynamic town-layer slice.

### Map town billboard type shapes

`Homm3StrongholdTownMapBillboard` and `Homm3StrongholdDwellingMapBillboard` use the
same map-object surfaces. In the May 6 and May 10/11 live dumps, `bvc` is the live
placed map object and `bve` is map-object metadata. The older typed code also refers
to `buv` as `MapObjectMeta`, but in these dumps `buv` is an overlay/highlight renderer
shape, not the town/dwelling metadata shape; do not use its no-arg methods as a release
metadata replacement.

- `bvc` kept the placed-object init shape `void (Map, bve, int, byte, float)`, but the
  alias set changed from 7 methods on May 6 (`osr`, `omb`, `Init`, `bwn`, `kay`, `lwp`,
  `fub`) to 7 live methods (`ddo`, `nhq`, `omq`, `dnp`, `nzv`, `edg`, `Init`). The
  rename map says old `bvc.Init` maps to live `omq`, while live `Init` maps from old
  `bvc.omr`; treat literal `Init` matching as suspicious until behavior is confirmed.
- `bve` kept the metadata init shape `void (ObjectConfig)`, but shrank from 4 methods
  on May 6 (`mpk`, `dmf`, `Init`, `tr`) to 3 live methods (`Init`, `iqi`, `ojc`).
  The release code currently avoids patching `bve.Init(ObjectConfig)` because early
  reflective reads of `ObjectConfig.id` have caused native access violations.
- `ObjectConfig` shape is stable at 30 fields, 5 derived string/bool properties, and
  7 methods; only the obfuscated property/method names drifted (`cmql`-`cmqp` to
  `cmsc`-`cmsg`, `ooq`-`oov` to `opf`-`opk`).
- Release member fallbacks must include the live names: `bvc` meta moved from
  `bvkd` / `<bvkd>k__BackingField` to `bvlr` / `<bvlr>k__BackingField`; live root
  fields moved from `bvkp`/`bvks` and `bvkq`/`bvkt` to `bvmd`/`bvmg` and
  `bvme`/`bvmh`; `bve` config moved from `bvll` to `bvmz`; `bve` prefab array moved
  from `bvlm` to `bvna`; combined-geometry flag moved from `bvlp` to `bvnd`.
  The town/dwelling billboard code now patches all live `bvc` methods with exact
  `void(Map,bve,int,byte,float)` shape and keeps `bve(ObjectConfig)` metadata hooks
  avoided in release-safe mode.
- Packaged HoMM3 map-object frame folders use `.dir` (`avcstrc0.dir`, `avgwolf0.dir`,
  etc.), not `.dlv`. If billboard hooks register and the logs say `missing image`,
  check this path suffix before adding runtime probes.

## 4. Plugin.cs — 3 patches

| Line | Old Patch Target |
|------|-----------------|
| 4721 | `[HarmonyPatch(typeof(BhDemoIconTxtUI), nameof(BhDemoIconTxtUI.ypb))]` |
| 4730 | `[HarmonyPatch(typeof(BhDemoIconTxtUI), nameof(BhDemoIconTxtUI.ypc))]` |
| 4925 | `[HarmonyPatch(typeof(Hex.Session.Loader), nameof(Hex.Session.Loader.vdk))]` |

**Action**: Search live dump.cs for each type's `ypb`/`ypc`/`vdk` replacements.

## 5. RetaliationForecastFix.cs — 1 patch

| Line | Issue |
|------|-------|
| 96   | Type `ekx` entirely removed from Steam build. `[HarmonyPatch(typeof(BhHealDamageForecastPanel), nameof(BhHealDamageForecastPanel.Show), new[] { typeof(ekx) })]` disabled. |

**Action**: Check if `BhHealDamageForecastPanel.Show` changed signature. The `ekx`
parameter may have been replaced by a different obfuscated type.

## 6. Homm3WarcryWrapperProbe.cs — entire elo-section disabled

| Area | Issue |
|------|-------|
| eloCtor patch | Type `dzs` removed from Steam build. `AccessTools.Constructor(typeof(elo), typeof(dzs), ...)` orphaned. |
| PrefixBefk, DumpEloProperties, TryExtractAbility, TryExtractAbilitySid | Multiple elo fields (`cgxc`, `cgxd`, `hza`, `gbk`, `khv`, `cgxb`) renamed/removed. |

**Action**: The entire probe section for the warcry-wrapper `elo` type needs to be
re-mapped against the live dump. Look up the new field names via the rename map's
field entries starting with `elo.`.
