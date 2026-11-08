# Steam Hotfix UI Surface Diff - May 6 vs Live

Static comparison source:

```powershell
tools/il2cpp_out_20260506/dump.cs
Fresh Golden Era Il2CppDumper output (`tools/il2cpp_out_<YYYYMMDD>_golden_era/dump.cs`; see `tools/IL2CPP_DUMP.md`). Do not use removed `tools/il2cpp_out_live/`.
rename_map.json
```

This is an investigation snapshot for the May 2026 Steam hotfix where many UI surfaces stopped updating: hero portraits, building portraits/icons, battle portraits, unit abilities, warcries, and recruitment card portraits.

Status note, May 13, 2026: this document is a snapshot, not a live mapping table. Later hotfixes moved several names again (`BhTurnView.cgvu`, `dxs.ceev`, `els.beri(out dxs)`, `ecd.cfaj/cfaf/cfao`, `BuildingsData.cnyb/bgad/chsd`, `BhNavigationView.bzeg/slp/hlm`). Use this file for failure patterns and stale-name warnings, but accept current mappings only through the semantic registry and shape/xref review process documented in `AGENTS.md` and `OfflineUnlockMod/AGENT_REBUILD_AND_MAINTENANCE.md`.

## High-level finding

The named UI `MonoBehaviour` classes mostly still exist and often have the same field/method counts. The breakage is not that the UI layer disappeared. The problem is that nearly every private/public obfuscated member shifted, while several supporting controller/model types changed structure enough that index/order-based remapping is unsafe.

Do not patch these surfaces by guessing the next obfuscated name in sequence. Prefer signature-based lookup on the target type, and for the controller/model types below, verify semantics from method bodies or tightly scoped runtime logs before changing behavior.

## Stable type, unstable members

| Surface | May 6 shape | Live shape | Important drift |
| --- | ---: | ---: | --- |
| `Hex.Session.Hud.BhHeroHUDPanel` | 23 fields, 1 prop, 35 methods | 23 fields, 1 prop, 35 methods | `currentHero` is not present in either dump. The likely hero state field shifted `ess casp` -> `est caue`; `vpy(ess)`/`vpz(ess)` -> `vqx(est)`/`vqy(est)`. |
| `Hex.Session.Hud.BhHeroPortrait` | 4 fields, 3 methods | 4 fields, 3 methods | `vom(string, TypeResultHero)` -> `vpl`; `von(TypeResultHero)` -> `vpm`. |
| `Hex.Session.UI.HeroProfile.BhHeroPortraitView` | 8 fields, 12 methods | 8 fields, 12 methods | `ztr(Hero,bool,bool)` -> `zur`; `ztu(Hero)` -> `zuu`. |
| `Hex.Session.Battle.BhSelectedUnitHud` | 18 fields, 16 methods | 18 fields, 16 methods | `beet(object,BattleEventArgs)` -> `befv`; `beeu(bool,Unit)` -> `befw`; current source probing `behz` is not this method. |
| `Hex.Session.Battle.BhTurnView` | 23 fields, 2 props, 35 methods | 23 fields, 2 props, 35 methods | cached unit/view fields shifted `cgti/cgtj/cgtk...` -> `cgux/cguy/cguz...`; refresh `befs(Unit,TurnState)` -> `begu(Unit,TurnState)`. |
| `Hex.Session.Battle.BhBattleQueueView` | 9 fields, 16 methods | 9 fields, 16 methods | `bebg(List<elq>)` -> `bech(List<elq>)`; queue owner fields shifted `cgql..cgqp` -> `cgsa..cgse`. |
| `Hex.Session.Battle.BhUnitAbilityView` | 8 fields, 1 prop, 16 methods | 8 fields, 1 prop, 16 methods | ability getter `begc()` -> `behe()`; bind `bege(els,bool)` -> `behg(els,bool)`; ability field `cgua` -> `cgvp`, selected/native wrapper field `cgtz` -> `cgvo`. |
| `Hex.Session.Battle.BhUnitControlsView` | 7 fields, 22 methods | 7 fields, 22 methods | bind `begt(dxs[],dxs,bool)` -> `behv`; select/click `begz(dxs)` -> `beib`; unit bind `begx(Unit)` -> `behz`. Do not confuse live `behz(Unit)` with `BhSelectedUnitHud.beet`. |
| `Hex.UI.City.BhBuildingView` | 46 fields, 10 props, 50 methods | 46 fields, 10 props, 50 methods | bind `tnv(fbi,dvw,int)` -> `tot(fbj,dvw,int)` and `tnw(int,int)` -> `tou`; backing city type changed `fbi` -> `fbj`. |
| `Hex.UI.BhTooltipBuilding` | 33 fields, 20 methods | 33 fields, 20 methods | `syn(fbi,dvw,int)` -> `szk(fbj,dvw,int)`; `syo(BhBuildingView,dvw,int,Action)` -> `szl`. |
| `Hex.UI.Tooltips.BhTooltipUnitsView` | 1 field, 3 methods | 1 field, 3 methods | `tkx(dvw,int)` -> `tlu(dvw,int)`, but this mapping is missing from `rename_map.json`. |

## Recruitment and preview surfaces

| Surface | May 6 -> Live |
| --- | --- |
| `Hex.UI.City.BhHireUnitItemView` | `UpdateView(string)` is stable. Model-list hooks shifted `trs(IReadOnlyList<string>)` -> `tsp` and `try(IReadOnlyList<string>)` -> `tsv`. |
| `Hex.BhUnitPreviews` | Same 7 fields/9 methods, but every private method shifted: `hsy(string,float,out cls)` -> `hta`, `htc(UnitViewConfig)` -> `hte`, `htd(string)` -> `htf`. |
| `Hex.Session.Battle.BhUnitWindowPreview` | `Show(UnitViewConfig)` is stable. Factory `beri(string,Transform)` -> `besk`. |
| `Hex.UI.BhUnitPreview` | Accessors shifted `sos/sot/sou/sov` -> `spo/spp/spq/spr`. |
| `Hex.Pick.BhUnitSlot` | pick-row bind `lwc(Mode,string,int,int)` -> `lwm`. |
| `Hex.Session.Hud.BhUnitSlots` | `Init(dsu)` is stable, but private accessors/event hooks shifted `wcp..wdd` -> `wdo..wec`. |

## Warcry and ability danger zone

These types are not just simple member-name shifts:

| Type | May 6 shape | Live shape | Risk |
| --- | ---: | ---: | --- |
| `dxr` | 12 fields, 106 methods | 12 fields, 91 methods | Severe method-count and order change. Existing method names like `bama` cannot be trusted without signature/semantic checks. |
| `dxs` | 16 fields, 98 methods | 16 fields, 96 methods | Severe order/signature drift. Ability logic/view fields did shift cleanly by field position (`cech/ceci` -> `cedw/cedx`), but methods need body validation. |
| `ekn` | 4 fields, 57 methods | 4 fields, 56 methods | Constructor signature changed; current verifier flags `ekn..ctor`. Do not keep the old `ekn(dyu,bool,bool)` assumption. |
| `ecf` | 3 fields, 27 methods | 3 fields, 26 methods | Constructor/availability assumptions are stale. Current source references `lis`, but the live dump does not support that literal name. |
| `dwq` / `dwr` | ability/native hook code uses these names | live shape resembles city/building manager/shrine classes after rename pollution | Treat current `dwq`/`dwr` ability code as suspect; the automated rename pass appears to have mapped some ability hooks onto unrelated live types. |
| `elq` / `elm` | queue item/positioning support | live shape changed; `elq` gained methods | Timeline/queue hooks require fresh semantic tracing before another direct patch. |

Hero ability UI itself is a simple named UI shift:

- `Hex.UI.BhHeroAbilitiesView.shx(bzd,List<edg>)` -> `sit`
- `Hex.UI.BhHeroAbilitiesView.shy(bzd,List<edg>)` -> `siu`
- `Hex.UI.BhHeroAbilitiesView.sif(edg)` -> `sja`
- `Hex.UI.BhHeroAbilitiyView.siy(bzd,els)` -> `sjt`

The current release-safe warcry slice still references stale names (`siy`, `shx`, `shy`, `sif`), so it will miss live.

## Current-source red flags

These are static misses in the current source and should be fixed before runtime probing:

- `Homm3HeroPortraitHook.cs` probes `BhHeroHUDPanel.currentHero`; that property is absent in both May 6 and live dumps.
- `Homm3ImportBhSelectedUnitHudFix.cs` release path searches `BhSelectedUnitHud.behz` for the old `beet` event handler. Live `behz(Unit)` is on `BhUnitControlsView`; live selected-HUD event handler is `BhSelectedUnitHud.befv(object,BattleEventArgs)`.
- `Homm3CustomUiIconHook.cs` release slice uses May 6 names on building/tooltip surfaces: `BhBuildingView.tnv/tnw`, `BhTooltipBuilding.syn/syo`, `BhTooltipUnitsView.tkx`, `BhHireUnitItemView.trs/try`, and `BhUnitAbilityView.izd`.
- `Homm3WarcriesHeroAbilityHook.cs` release-safe icon slice uses May 6 hero ability names (`siy`, `shx`, `shy`, `sif`), live names are `sjt`, `sit`, `siu`, `sja`.
- Any code path using literal `dng`, `bejy`, `mxm`, `ohn`, `okm`, or `dze` for live `BhUnitControlsView` is stale; those names are absent in both May 6 and live dumps for that type.

## Recommended fix order

1. Patch exact static misses on stable UI `MonoBehaviour` classes using live signatures, not only names:
   - selected HUD portrait guard: `BhSelectedUnitHud.befv(object,BattleEventArgs)`
   - selected controls bind/select: `BhUnitControlsView.behv(dxs[],dxs,bool)` and `beib(dxs)`
   - battle ability view bind/getter: `BhUnitAbilityView.behg(els,bool)` and `behe()`
   - building/tooltip/recruitment surfaces listed above
   - hero ability UI button/container names listed above
2. Replace `currentHero` reads with field/signature based extraction from `BhHeroHUDPanel` (`est caue` live, `ess casp` May 6), or use an existing public path if one is found in decompilation.
3. Treat `dxr`/`dxs`/`ekn`/`ecf` as a separate semantic remap project. Verify constructors, availability gates, and ability arrays from bodies/disassembly before changing unit ability or warcry mechanics.
4. Only add runtime probes after these static misses are corrected; otherwise logs will mostly confirm hooks never registered.

## Fix pass - May 11

Commit work after this investigation corrected the stable live-name misses first:

- selected HUD guard now targets live `BhSelectedUnitHud.befv(object,BattleEventArgs)` with the old `beet` as fallback.
- selected unit controls now prefer live `BhUnitControlsView.behw(BhUnitAbilityView)`, `behv(dxs[],dxs,bool)`, and `beib(dxs)`.
- release ability view access now includes live fields `cgvp`/`cgvo`/`cgvy`/`cgvz` and live `dxs` config fields `cedw`/`cedx`.
- building/tooltip/recruitment hooks now prefer live `BhBuildingView.tot/tou`, `BhTooltipBuilding.szk/szl`, `BhTooltipUnitsView.tlu`, and `BhHireUnitItemView.tsp/tsv`.
- battle ability icon hook now targets live `BhUnitAbilityView.behg(els,bool)`.
- hero ability UI icon slice now targets live `BhHeroAbilitiyView.sjt` and `BhHeroAbilitiesView.sit/siu/sja`.
- army-pick unit slot hooks now prefer live `BhUnitSlot.lwm`.
- `BhHeroHUDPanel.currentHero` probing was removed; live hero SID resolution now scans the existing active `BhHeroHUDPanel.me` and includes `casp`/`caue` hero-state fields.
- the stale static `ekn(dyu,bool,bool)` verifier target was replaced by a guarded reflection helper; `ekn` remains a semantic remap task, not a trusted live wrapper.

After this pass, `verify_patch_surfaces.py --no-probes -r rename_map.json` reports only the unrelated pre-existing `DamageHistogramOverlay.cs:2726` orphan (`eky.ddu`).

## Follow-up UI mapping pass - May 11

The next log pass still did not justify broad runtime probing. Existing diagnostics identified exact stale live names:

- `BhUIBuildingSession` live current-view fields are `bzbr` (`List<BhBuildingView>`) and `bzbs` (`Dictionary<string,BhBuildingView>`). Old `bzad`/`bzae` lookups produce Il2CppInterop field-missing noise and must only be used as May 6 fallbacks.
- `dvw` live building model members shifted from `cdtb`/`cdtc`, `cnou`/`cnov`, and `zze`/`zzb`/`zzc` to `cduq`/`cdur`, `cnqm`/`cnqn`, and `baae`/`baab`/`baac`. Building icon probes that report `buildingType='dvw'` with all old members empty are mapping misses, not asset-cache failures.
- `BhBattleQueueView.bebg(List<elq>)` is live `bech(List<elq>)`; `BhTurnView.cgti` is live `cgux`; `elq.cgyh/cgyj` are live `cgzw/cgzy`. Turn-order probes showing `Homm3TurnViewPortraitRefresh` attached with `cachedSid=''` should check these fields before adding more probes.
- `BhHeroView.beee(Hero)` is live `befg(Hero)`. Battle hero HUD logs showing `HERO PORTRAIT` sprite `WIP` after `BhHeroView.Init` mean the init hook is firing before the hero bind is available; patch the live Hero bind method first.

## Remaining visual fix pass - May 11

Fresh logs after the turn-order fix showed:

- Tooltip building icons were replacing successfully. Missing "building icons" referred to the city `BhBuildingView` icon path, whose no-arg `UpdateView()` needed live model/level fallbacks: model `bzaq`/`cneq`/`tor()` and level-ish fields/getters `bzan`/`bzao`/`bzas`, `cnej`/`cnek`/`cnel`, `toj`/`tok`/`tol`.
- Town building layers failed before rendering because `building_layer_map.json` was parsed with generic `JsonConvert.DeserializeObject<Dictionary<string,string>>`, which hit an IL2CPP generic method initializer exception. Parse `JObject` through `IDictionary<string,JToken>` instead.
- `BuildingsData` live aggregate list is `cnxb` / backing field `chrg` / getter method `bfzh`, not only May 6 `cnvj/chpr`. Named category lists are `List<BuildingMain>` etc., so do not cast the list object to `List<BuildingData>`; enumerate and cast each item.
- Hero portrait UI live methods are `BhHeroSelectButton.hph`, `BhHeroPortraitView.zur/zuu`, `BhTavernHeroView.zcw`, and `BhHeroUIElement.wak/waq`. Session hero wrappers also need `est.ciaj` / `est.cnxy` traversal to reach the `HeroConfig.icon`.

## Follow-up icon pass - May 11

- `JObject` in the IL2CPP plugin context may bind through IL2CPP collection interfaces; avoid `IDictionary<string,JToken>` casts and generic Newtonsoft deserialization for town layer maps. The current parser uses a simple string-key/string-value regex over the `JObject` JSON payload.
- `BhFractionLawView.zce/zcg` live names are `zde(dtd,dqj)` and `zdg()`. Law icon resolution should walk live `dqj` fields/properties `cbzj`/`cnkk` and methods `xlu`, plus live `DataFractionLaw` `chqp`/`cnwn`/`bfsq`.
- Battle `BhHeroView` still may not expose a reachable Stronghold hero config while the portrait image is WIP. It is safe to reuse the last resolved Stronghold hero portrait key only when `BhHeroView.heroFace` still has a placeholder sprite, so enemy hero portraits with real vanilla art are not overwritten.

## Build-tree and adventure-map hero pass - May 11

- Live `BhBuildingView` still uses `tot(fbj,dvw,int)` and no-arg `UpdateView()` for initial city icon repair, but the build tree can overwrite icon lists later through the refresh/binder cluster `tpb`, `tpc`, `tpd`, `tpe`, `tpf`, `tpg`, `tph`, `tpi`, `tpq`, and `tpr`. Reapply the building icon fallback after those methods instead of only after `UpdateView()`.
- `BhHeroHUDPanel.vpw()` is live `vqv()`. If the selected/adventure army strip portrait misses while unit slots work, check this HUD-panel show/refresh hook before changing unit portrait caches.
- The adventure-map hero visual hook was looking at the wrong post-hotfix type. May 6 `erq`/`erv` hero drawer shapes are live `err`/`erw`; the concrete hero drawer with `HeroConfig` and `MountConfig` fields is live `erw`, with constructor `.ctor(Hero, Vector3, Quaternion, HeroConfig, MountConfig, Transform, float)`, `HeroConfig` field `chxh`, and root getters/properties such as `bgsn()`, `bgss()`, and `chwx`. Patch this constructor directly; do not depend on the old `eso` session-init assumption.

## Selected-unit ability pass - May 11

- Live battle `Unit` inherits the action-bar ability manager from `ecx`, not from the old direct `Unit.cfhm` path. The manager is `ecx.cfjb` / backing field `<cfjb>k__BackingField` / getter `bcqo()`. Logs that say `release unit ability manager is null` for `h3_orc` after `BhSelectedUnitHud.befv` mean the resolver is still using the stale `cfhm` name.
- Live `dxr` returns ability buckets from `bana(EAbilityType)`; May 6 `bama(EAbilityType)` is only a fallback. Do not use similarly named no-argument/int methods such as `baox()` for action-bar recovery.
