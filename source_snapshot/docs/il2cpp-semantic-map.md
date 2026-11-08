# Olden Era IL2CPP Semantic Map

Purpose: build a project-local translation layer for obfuscated IL2CPP symbols. Treat this as a working map, not official source. Every inferred name should carry evidence and confidence so future agents can continue the translation instead of rediscovering the same methods from scratch.

Use this document when an issue depends on native battle/UI behavior rather than only JSON data. The current priority area is hero and unit battle ability controls, especially Stronghold Warcries.

## Confidence Levels

| Level | Meaning | Promotion rule |
| --- | --- | --- |
| Known | Exposed by interop name, enum, JSON field, log SID, or direct method signature. | Does not require behavioral inference, but must still be re-anchored after game updates. |
| Strong inference | Static disassembly and runtime behavior agree across at least one meaningful scenario. | Promote only after call flow, field value, and visible behavior all match. |
| Tentative | Plausible from disassembly, field offset, call order, or a single runtime observation. | Use for diagnostics and comments, not broad fixes. |
| Rejected | A prior inference or fix path was disproven. | Keep the entry with the failure symptom and date. |

## Evidence Fields

For each symbol, record:

| Field | Use |
| --- | --- |
| Symbol | Current interop/native name, such as `ecf.baak` or `BhHeroAbilitiesView.ryy`. |
| Address | RVA when known, such as `0x2A6F900`. Version-specific. |
| Inferred name | Human-readable role, such as `HeroAbilityView.Bind`. |
| Confidence | Known, strong inference, tentative, or rejected. |
| Evidence | Static and runtime facts supporting the name. |
| Callers/callees | Nearby known methods that anchor the role. |
| Warnings | Crash risks, false leads, or update hazards. |

## Current Battle Ability Map

| Symbol | Address | Inferred name | Confidence | Evidence | Warnings |
| --- | --- | --- | --- | --- | --- |
| `ecf` | n/a | hero battle ability runtime instance | Known | Constructed from hero ability SIDs; exposes `sid`, `cd`, `charges`, `configEnergyLevel`; cast from `dyu` for hero ability rows. | Field names are interop-generated and can move after update. |
| `ecf.baak()` | `0x1ECA6E0` | hero ability availability gate | Strong inference | Called by `BhHeroAbilitiesView.ryt/ryu` before `ekn` wrapper creation; checks cooldown/charges and effective Focus cost. Warcry prefix can return usable while preserving cooldown guard. | Do not assume this is the final UI enabled state; later controller refresh can grey a button after this returns true. |
| `ecf.bcdm()` | `0x1ECA8F0` | displayed hero ability energy/Fokus pip count | Strong inference | `BhHeroAbilitiyView.rzt` calls it while binding the visual. Patching it to zero changes Warcry displayed cost path. | Do not broad-patch all `ecf` no-arg integer aliases. |
| `ecf.mgn()` | unknown | alternate hero ability energy getter | Tentative | Current hook treats it as a representative energy getter for Warcries. | Needs native body mapping before promotion. |
| native side energy resolver | `0x1FB8270` | effective side Focus cost resolver | Strong inference | Disassembly returns `0` immediately when `ecf.configEnergyLevel` at `+0x6C` is zero; otherwise indexes side energy thresholds. | Address is version-specific and has no interop method name yet. |
| `ekn` | n/a | ability view wrapper | Known | Constructed as `ekn(dyu ability, bool enabled, bool selected)` for both hero and unit ability buttons. Exposes `cgch` wrapped ability and `cgci` enabled flag. | Helper casts such as `bdzg/hwt` can miss Warcries; prefer `cgch` first. |
| `ekn.cgci` | wrapper `+0x18` | wrapper enabled/available flag | Strong inference | `BhHeroAbilitiyView.rzt` branches on it; false calls disabled visual path. Unit button bind also consumes this flag. | A true value at bind does not guarantee later controller interactability. |
| `BhHeroAbilitiesView.ryt` | `0x2A6F0A0` | build non-separate hero ability buttons | Strong inference | Calls `ecf.baak()`, creates `ekn`, then binds `BhHeroAbilitiyView.rzt`. Handles abilities not marked `showSeparately`. | It is an initial build path, not necessarily every repaint. |
| `BhHeroAbilitiesView.ryu` | `0x2A6F320` | build separate hero ability buttons | Strong inference | Same shape as `ryt`, but for `showSeparately` rows. | Same limitation as `ryt`. |
| `BhHeroAbilitiyView.rzt` | `0x2AA3B50` | bind hero ability button view | Strong inference | Stores `bys` at view `+0x38`, stores `ekn` at `+0x40`, calls `ecf.bcdm()`, branches on `ekn.cgci`, and calls enabled/disabled visual helpers. | Do not call `BhHeroAbilitiyView.rzu(true)` from an `rzt` postfix; that caused recursive `rzt -> rzu -> rzt` crash after tactics. |
| `BhHeroAbilitiyView.rzu(bool)` | `0x2AA3D90` | native `+0x4A` gate setter and rebind | Strong inference | Writes the bool argument to view byte `+0x4A`, clears wrapper selected state, then calls back into `rzt`. | Do not invoke from Warcry Harmony patches; direct byte writes are safer because `rzu(true)` re-entered `rzt` recursively in a prior build. |
| `BhHeroAbilitiyView` private bytes | `+0x48..+0x4B` | hero ability button local gates | Strong inference | Disassembled click callback checks `+0x49 == false`, `+0x4A == true`, and `+0x4B == true` before invoking the hero ability view callback. Current diagnostics log these as `nativeBools=bxgb@48,bxgc@49,bxgd@4A,bxge@4B`. | `wrapperEnabled=True` is not enough; if these bytes disagree, the button can appear/click as disabled after turn/controller refresh. |
| `BhHeroAbilitiyView.viewBase.pics` | view `+0x28` -> base `+0x58` | hero battle button icon images | Strong inference | May 4, 2026 Warcry logs showed `wrapperEnabled=True` while `pics` still contained grey `WIP` sprites, so the grey visual was icon fallback/art, not the availability flag. | Apply donor sprites to `pics` after `rzt`/refresh for custom hero abilities whose icon key does not flow through native sprite resolution. |
| `BhAbilityViewBase.tuf()` | `0x2B21330` | apply disabled visual state | Strong inference | Called by `rzt` when `ekn.cgci` is false; visible symptom is greyed button. | Late controller paths may call equivalent visual methods too. |
| `BhAbilityViewBase.tub()` | `0x2B20BF0` | apply selected/enabled visual state | Tentative | Called by `rzt` in the true/selected branch. | Need runtime snapshots of selected ring/glow before promotion. |
| `BhHeroAbilitiesView.rzi(bool)` | `0x2A70990` | set hero/siege ability controller flag | Tentative | Disassembly loops normal, siege, and separate hero ability views and writes the bool into per-view fields (`+0x4B` or siege `+0x33`). | Do not patch until the flag meaning is named by runtime probes. |
| `BhHeroAbilitiesView.ryy(object, BattleEventArgs)` | `0x2A6F900` | battle-event hero ability refresh/selection handler | Tentative | Disassembly compares a current-side-looking pointer chain from `this +0x58` to an ability/view-side-looking pointer chain, then calls controller methods. User observed enemy retaliation re-greys Warcries, making event refresh a likely divergence point. | Need compare traces for Triumvirate and Warcries before behavior fixes. |
| `BhHeroAbilitiesView.ryw(BhHeroAbilitiyView)` | `0x2A6F800` | hero ability click/select entry | Tentative | Calls `crg.tun` if a global/controller state says allowed. | Might be click routing, not availability. |
| `crg` | n/a | battle ability selection/controller object | Tentative | `BhHeroAbilitiesView` calls `crg.tuq/tun`; methods store selected views and clear selection. | Do not assume field names from dump are semantically accurate. |
| `crg.tuq` | `0x2B371F0` | set selected ability view or clear selected ability | Tentative | Calls clear method then stores a view in a `crg` field. | Need distinguish hero vs unit selected view fields. |
| `crg.tun` | `0x2B38560` | handle ability view activation request | Tentative | Called from `BhHeroAbilitiesView.ryw`; calls internal methods around selection/cast flow. | Patching here can affect all battle abilities. Guard by ability SID if ever used. |
| `crg.tur` | `0x2B38900` | clear selected ability state | Tentative | Called before `crg.tuq` stores a selected view. | Confirm by logging selected glow changes. |
| `crg.tuz/tva/tvb/tvc/tux` | various | selection/enable/visual subroutines | Tentative | Current diagnostic hook names these for logging around Warcry/Triumvirate snapshots. | Treat as probes only until branch purpose is mapped. |
| `BhUnitControlsView.bdqo(dwr[], dwr selected, bool)` | n/a | playtest selected-unit action-bar bind | Rejected for release | Release decompile does not match this route; `dwr` is now a Shrine of Rebirth building wrapper. | Do not port release ability work through `dwr`, `dwq`, `ekn`, or `bdqo`. |
| `dwr.baak()` | n/a | playtest unit ability availability gate | Rejected for release | Release `dwr : dvw` stores `BuildingShrineOfRebirth`, not ability data. | Trace `dxs` boolean methods such as `baop/baon` from native bodies before changing release availability. |
| `dwq` / `unit.celq` | n/a | playtest unit ability manager | Rejected for release | Release selected-unit controls point at `dxr`/`dxs`, not `dwq`/`dwr`. | Keep old names as playtest-only docs. |

## Release Ability Symbol Map

| Symbol | Semantic meaning | Confidence | Evidence | Warning |
|--------|------------------|------------|----------|---------|
| `dxr` | release unit ability manager | Strong inference | `ecx.cfhn` returns `dxr`; `dxr.cebp` is `Dictionary<EAbilityType, Il2CppReferenceArray<dxs>>`; `dxr.bama(EAbilityType)` returns ability buckets. | Port probes first and leave behavior disabled until availability semantics are mapped. |
| `dxs` | release unit ability wrapper | Strong inference | `dxs.Init(AbilityLogicConfig, AbilityViewConfig, AbilityID)` / `kdr(...)`; fields include `AbilityLogicConfig ceci` and `AbilityViewConfig cecj`. | Reject old `dwr.cdgt/cdgu/baak` for release. |
| `BhUnitControlsView.begy(Unit)` / `begu(Il2CppReferenceArray<dxs>, dxs, bool)` | release selected-unit/action-bar bind | Strong inference | Release controls store `cgul dxs[]`, selected UI, and `Dictionary<dxs, els>`. | Guard by unit/faction and avoid reentrant rebinding until native flow is traced. |
| `BhUnitAbilityView.begf(els,bool)` | release per-button bind | Strong inference | Per-button view stores `els cgua` and `dxs cgub`; `cntr` / `begd` returns current `dxs`. | Icon-only fixes are not enough for ability behavior. |

## Release Hero UI Symbol Map

| Symbol | Semantic meaning | Confidence | Evidence | Warning |
|--------|------------------|------------|----------|---------|
| `Hex.Session.Logic.Hero.cbyf` / `xlt()` | runtime hero -> `Hex.Session.Data.Hero` | Strong inference | Released decompile shows the property returns the data hero object; release portrait/class UI receives `Logic.Hero`, not the old playtest wrappers. | Old `ivd`/`ipk`/`get_heroConfig` accessors are gone in the retail build and should not be used as the only path. |
| `Hex.Session.Data.Hero.configSid` | stable hero config SID such as `homm3_stronghold_hero_N` | Confirmed by decompile shape | Data hero exposes public string `configSid`; this is the direct key needed by portrait/class resolvers. | Prefer this over UI text scanning for released Custom Game and hero profile surfaces. |
| `Hex.Session.Data.Hero.chpd` / `cnva` | data hero -> `Hex.Configs.HeroConfig` | Strong inference | Released data hero exposes both properties returning `HeroConfig`. | Use as secondary traversal; `configSid` is simpler and less dependent on config object aliases. |
| `Hex.Configs.HeroConfig.cmyj` | config id string getter | Strong inference | Released `HeroConfig` inherited/config-id getter returns a string and matches the SID resolver role. | Treat as a fallback alias; verify after Steam updates. |
| `BhHeroSelectButton.hpf`, `BhTooltipHeroItemView.tal/tam/tan`, `BhHeroPortraitView.ztr/ztu`, `BhTavernHeroView.zbw` | released hero portrait/profile UI bind surfaces | Confirmed by release logs | `0.1.156` registered these surfaces in release-safe mode, while playtest names were missing. | Do not dump all method candidates during normal release-safe startup; it makes logs noisy without adding signal. |
| `Hex.GameHub.Lobby.UI.BhHero.qoc(string,bool,bool,Action<string>)` | released Custom Game hero tile bind | Confirmed by May 5 live interop log | Current release method has four parameters and owns the hero tile binding. `qod` is no longer this binder in the May 5 interop. | Patch by `string,bool,bool,Action<T>` shape first; treat exact names as fallback documentation only. |
| `Hex.Session.Hud.BhUnitUI.cmko` / `Hex.Session.Hud.BhUnitSlots.cmlb` | old army-strip data accessors | Rejected for release | `0.1.160` release logs showed repeated `MissingMethodException` for compiled getters `BhUnitUI.vkd()` and `BhUnitSlots.vrl()` when postfixes touched `cmko`/`cmlb`. | Do not use these as the primary release path. |
| `Hex.Pick.BhUnitSlot.lvv(BhUnitSlot.Mode,string,int,int)` | released picker/summary unit slot binder | Confirmed by static dump, live interop mismatch | Release dump shows old `lrt` replaced by `lvv` on the same `Hex.Pick.BhUnitSlot` shape; live `0.1.163` startup still did not expose this method through generated interop. | Patch by runtime type/name/arity when possible; if it still misses, anchor through `BhSummaryCard.lvq/lvr` or a fresh live interop dump. |
| `Hex.Pick.BhSummaryCard.lvq(HeroConfig,string)` / `lvr(int,string)` | released Custom Game summary card refresh | Confirmed by static dump | Summary card owns `unitSlots`, hero portrait/class/faction image, and unit slot refresh. | Use as a fallback anchor for picker/summary portraits when `BhUnitSlot.lvv` is absent in live interop. |
| `Hex.Session.Hud.BhUnitSlots.cngz` / `wcq()` | released active army-strip UI list | Confirmed by May 5, 2026 Steam static dump | Current release dump shows `cngz` returns `List<BhUnitUI>` via getter `wcq()`, with backing field `cbap`. Older `cnfi/wbv` was an earlier release mapping. | Use guarded reflection and keep `cnfi/wbv` only as fallback. |
| `Hex.Session.Hud.BhUnitUI.cngm` / `vvf()` | released army-strip unit data accessor | Confirmed by May 5, 2026 Steam static dump | Current release dump shows `cngm` returns `Hex.Session.Data.Unit` via getter `vvf()`, with backing field `cavr`; `Unit.sid` is the custom unit SID. Older `cnev/vuk` was an earlier release mapping. | Use this for release army-strip and city-garrison portraits; old `cmko` is unsafe. |
| `Hex.Session.Hud.BhUnitUI.Init(Unit,int,dsq,Action<int,int>,Action<int,int>,Action<int,int,bool>)` | released per-slot army UI binder | Confirmed by static dump | Release dump shows `Init` receives the unit object directly before populating the slot. | Prefer this over `Start()` for release-safe army strip replacement; `Start()` can run before or outside later slot population. |
| `Hex.Session.Battle.BhTurnView.cgti` / `BhTurnView.UpdateView(Unit,TurnState,bool)` | release battle timeline cached unit and bind method | Confirmed by May 5 deployed interop metadata and live patch registration | Live Steam interop places cached `Unit` on `BhTurnView.cgti`; older static dumps showed `cgru`. `UpdateView(Unit,TurnState,bool)` still exists, but user logs after `0.1.254` showed its patches alone did not cover visible custom turn-order portraits. | Keep finalizer-safe replacement on `unitPic`, but also patch the owning `elq` turn item. Treat `cgru` as an older-dump fallback only. |
| `Hex.Session.Battle.Unit.chdi/chdj/chdk` plus `beti/betk/betm` | release battle unit transfer, logic config, and view config | Confirmed by May 5 deployed interop metadata | Live Steam interop exposes backing fields `chdi/chdj/chdk` and getters `beti/betk/betm`; earlier dumps showed equivalent `chbu/chbv/chbw` and `beso/besq/bess`. `TransferUnit.configSid` is the direct `h3_*` battle unit key, while logic/view configs expose `id`. | Resolve by shape and include both alias families. Old playtest aliases `cggz`/`cgha` can remain fallbacks only. |
| `elq.cgyh` / `elq.cgyj` / `elq.cgyk` | current release battle timeline item: unit, `BhTurnView`, and turn state | Confirmed by May 5 deployed interop metadata (`BepInEx/interop/Hex.dll`) | The live interop class `elq` has constructor `(TurnState, Func<BhTurnView>, Unit)`, `Unit cgyh`, `BhTurnView cgyj`, and `TurnState cgyk`. User logs after `0.1.254` showed `BhTurnView` patches registered but no turn-order apply/miss logs, so the queue item path must be patched too. | This supersedes the `cgru`-only assumption for the deployed Steam build. If `tools/il2cpp_out_new/dump.cs` shows `elm.cgwt/cgwv` or `BhTurnView.cgru`, verify whether the dump is stale before editing timeline code. |
| `Hex.Session.Hud.BhCityUIElement.vyf(int)` / `vyg()` | released city HUD refresh binders | Confirmed by static dump | Release dump shows `Init(fbe)`, `vyf(int)`, and `vyg()` on the city HUD element with stored `fbe cawv` and `Image cityIcon`. | Patch `vyf` and `vyg`; key aliases must include object-style Stronghold city SIDs. |
| `Hex.UI.City.BhCityUISession.bzdm` | released current city session wrapper | Confirmed by static dump | Release dump shows `private fbe bzdm` on `BhCityUISession`; `fbe.ciyy` is `ObjCityConfig` and `fbe.ciyz` is `ObjCity`. | Replace playtest-only `bynh.cidk/cidl` town backdrop/layer lookups with this path. |
| `Hex.UI.City.BhCityUISession.gik/gil/hrf/tv*` | released city-screen lifecycle/refresh methods | Static dump plus release-safe slice | Release dump shows no old `ghj/ghk` city-open names; release-safe `0.1.165` patches several city-session no-arg refresh methods and `twj(1)` with a guarded once-per-frame backdrop sync. | Keep these patches city-screen-only; do not use broad CanvasScaler town sync in release-safe mode. |
| `Hex.UI.City.BhUIBuildingSession.Init(fbi)` / `tqf` / `tqg` / `tqh` / `tqj(bfh)` | released building-screen sync triggers | Confirmed in live Steam interop | Release `BhUIBuildingSession` stores current city wrapper in `bzac : fbi`; old `gik/tpm/tpn/tpq/ghj/tgy/tgz/hjd` are absent from current interop. | Capture `fbi` directly and keep old wrapper-shaped paths only as fallback. Do not move building view transforms. |
| `Hex.UI.City.BhBuildingView.tnv(fbi,dvw,int)` / `UpdateView()` / `byzb` | released individual building view refresh and building model | Confirmed in May 5 live Steam interop | Current release bind is `tnv(fbi,dvw,int)`. `tnw` is now `tnw(int,int)`, so refresh hooks must read cached `byzb`/`cncz` for the `dvw`. `dvw.cnou` is building key, `dvw.cnov` is level, and `dvw.cdtb` is `BuildingData`. | Use as a sync/icon anchor only; do not use stale `dvw.cdtc` as building data. |

## Warcries Divergence Hypothesis

Current evidence says Warcries pass the initial hero ability bind path:

- `ecf.baak()` is forced usable only for the three Warcry SIDs while preserving native cooldown/charges.
- `ekn.cgci` is true during `BhHeroAbilitiyView.rzt`.
- Runtime logs can show `wrapperEnabled=True` while the visible button is still grey.

Therefore the remaining divergence is probably after bind, in `BhHeroAbilitiesView` / `crg` controller refresh. This is consistent with the observed behavior that a friendly unit attack temporarily un-greys Warcry buttons, then enemy action or retaliation re-greys them. Do not treat this as a Focus-cost problem unless new logs show `ecf.baak()` or `ekn.cgci` becoming false.

The open question is whether the controller divergence is caused by:

- missing data/registry membership compared with Dungeon/Triumvirate;
- a cached hero-side or ability-side object identity mismatch;
- a hardcoded native assumption around Dungeon/Triumvirate signature ability SIDs;
- or a different selected/current/local side pointer after enemy-side events.

## Diagnostic Workflow

1. Start from a known vanilla donor, preferably Dungeon/Triumvirate's Strength.
2. Capture the same lifecycle for donor and custom ability:
   - battle/tactics start;
   - initial `BhHeroAbilitiesView.ryt/ryu`;
   - `BhHeroAbilitiyView.rzt`;
   - `BhHeroAbilitiesView.rzi/ryy/...` event refresh;
   - `crg.tuq/tun/tur/...`;
   - click/cast result;
   - retaliation/enemy action repaint.
3. Log only stable identifiers and small snapshots:
   - ability SID;
   - wrapper `cgci` and selected bool;
   - key view bool fields (`+0x48` through `+0x4B` when exposed);
   - limited child `CanvasGroup` alpha/interactable/blockRaycasts;
   - side/caster/current object pointer identity if safely accessible.
4. Promote semantic names only when donor/custom comparison explains a visible behavior.
5. Prefer data/registry fixes when the donor enters a dictionary that the custom SID misses.
6. Use Harmony controller patches only when the native path is confirmed to have a hardcoded or unrecoverable assumption.

## Patch Safety Rules

- Never patch by short obfuscated name alone after a game update. Re-anchor by signature, call site, stack trace, disassembly, or runtime log.
- Do not call view state methods from bind postfixes unless the method's body is understood. The known `rzt -> rzu -> rzt` recursion crash came from this mistake.
- Avoid broad reflection across IL2CPP Unity objects. Log exact fields and exact methods.
- Keep diagnostics gated or bounded. Battle UI refresh methods can fire many times per turn.
- If a patch is only correcting cosmetics, say so. For ability bugs, prefer changing the data or native wrapper inputs before changing final `CanvasGroup` state.

## Update Checklist

When a new symbol is decoded:

1. Add or update its row in this document.
2. Add a short stable summary to `docs/AGENT_REFERENCE.md`.
3. If broadly useful, add/update a companion `docs/rag_chunks/` file.
4. Record rejected theories with the visible symptom and date.
5. If code comments or helper names use the inferred meaning, keep confidence in mind and avoid overstating tentative names.
