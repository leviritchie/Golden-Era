# Mono-to-Deobf Unit Tooltip, Preview, and Hire Ability UI Evidence

Status: source-prepared/static-only. This document records Mono demo versus current Golden Era static evidence. It is not runtime proof.

## Scope

This slice covers UI surfaces adjacent to selected unit HUD and battle/town unit displays:

- `Hex.UI.BhTooltipUnit`
- `Hex.UI.BhTooltipUnitCountLosses`
- `Hex.UI.BhUnitPreview`
- `Hex.BhUnitPreviews`
- `Hex.Session.City.BhHireUnitAbilityView`
- `Hex.Session.City.BhHireUnitAbilityItemView`

The goal is to replace old defensive/probe-style UI handling with exact native binding contracts where possible.

## Evidence artifacts

- Broad map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_deobf_semantic_map.json`
- Mono decompile: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_priority_unit_tooltip_preview_decompiled.cs`
- Current method dossiers:
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/unit_tooltip_BhTooltipUnit_Show_dossier.md`
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/unit_tooltip_BhTooltipUnit_tdp_dossier.md`
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/unit_tooltip_BhTooltipUnitCountLosses_tea_dossier.md`
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/unit_hire_BhHireUnitAbilityView_bann_dossier.md`
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/unit_hire_BhHireUnitAbilityView_bano_dossier.md`
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/unit_hire_BhHireUnitAbilityItemView_banl_dossier.md`
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/unit_hire_BhHireUnitAbilityItemView_banm_dossier.md`
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/unit_preview_BhUnitPreviews_htv_dossier.md`

## Type survival

The broad map gives exact type-name matches for all target classes in this slice. That means these are good candidates for native-friendly hooks: the hard part is method/body mapping, not type discovery.

| Mono type | Current deobf type | Static status |
|---|---|---|
| `Hex.UI.BhTooltipUnit` | `Hex.UI.BhTooltipUnit` | strong static type match |
| `Hex.UI.BhTooltipUnitCountLosses` | `Hex.UI.BhTooltipUnitCountLosses` | strong static type match |
| `Hex.UI.BhUnitPreview` | `Hex.UI.BhUnitPreview` | strong static type match |
| `Hex.BhUnitPreviews` | `Hex.BhUnitPreviews` | strong static type match |
| `Hex.Session.City.BhHireUnitAbilityView` | `Hex.Session.City.BhHireUnitAbilityView` | strong static type match |
| `Hex.Session.City.BhHireUnitAbilityItemView` | `Hex.Session.City.BhHireUnitAbilityItemView` | strong static type match |

## Mono source shape

### `BhTooltipUnit`

Mono responsibilities:

- `OnShow(string sid)` activates portrait and loads `IconManager.me.BySid(sid)`.
- `OffPortrait()` hides portrait and army count.
- `Show(string sid, int count, bool withSecret)` calls `OnShow`, activates count UI, and writes either a secret-range string or exact count.
- `Show(string sid, string min, string max)` calls `OnShow` and writes either one value or `min-max`.
- `SetupArmyCount(string count)` toggles count frame/backing and writes text.
- `Hide()` disables count/backing/portrait.
- Loss/fight helpers animate skull/loss UI and reset animations.

### `BhTooltipUnitCountLosses`

Mono is nested under `BhTooltipUnit` and has two simple visual modes:

- add-unit style: add-unit icon, green text/color.
- skull/loss style: skull icon, red text/color.

### `BhHireUnitAbilityItemView`

Mono responsibilities:

- `Init(string sid)` loads a plain icon by SID.
- `Set(Context, AbilityViewConfig)` stores active ability context/config and uses `IconManager.me.BySid(viewConfig.name)`.
- `SetPassive(Context, AbilityViewConfig)` stores passive context/config and uses the same icon route.
- `OnHover()` dispatches to ability or passive tooltip depending on active/passive mode.
- Show/hide only animate alpha/move.

### `BhHireUnitAbilityView`

Mono responsibilities mirror `BhHireUnitAbilityItemView` but include label/localization refresh:

- active ability binding stores context/config, activates icon, loads sprite by `viewConfig.name`, refreshes label.
- passive ability binding stores context/config, activates icon, loads sprite by `viewConfig.name`, refreshes label.
- hover dispatches to active ability tooltip or passive tooltip.

### `BhUnitPreviews`

Mono responsibilities:

- owns pooled preview cameras/platforms.
- gets and returns `BhUnitPreview` instances.
- loads/caches unit model previews by unit view config, SID, path, and scale.

## Current deobf method map

### `BhTooltipUnit`

| Current method | Static claim | Evidence |
|---|---|---|
| `Show(string, int, bool)` | Exact current overload for portrait plus numeric/secret count display. | Calls `BhTooltipUnit.tdp`, activates `armyCount`/`armyCountBack`, uses `Int32.ToString`, and calls secret/count helper paths. |
| `Show(string, string, string)` | Exact current overload for portrait plus min/max range display. | Calls `BhTooltipUnit.tdp`, compares strings, calls `String.Concat`, then `BhTooltipUnit.tdr`. |
| `tdp(string)` | Current `OnShow` equivalent: portrait activation and icon load. | Touches `portrait`, calls `GameObject.SetActive`, calls `cko.sfo` sprite lookup, then `Image.set_sprite`. |
| `tdr(string)` | Current `SetupArmyCount` equivalent candidate. | Type-level evidence shows count fields `armyCount`, `armyCountBack`, `armyCountFrame`; full body dossier not yet generated in this slice. |
| `Hide()` / `tdq()` | Current hide/off-portrait candidates. | Field usage splits `portrait`, `armyCount`, backing fields. Need per-method body audit before implementation. |
| `tdt(float,float,float)` / `tdu(int,int,float)` / `tdv()` / `tdx()` / `tdy()` / `tdz()` | Loss/fight/skull animation cluster. | High body complexity, repeated touches of `skullLoss`, `skull`, `lossCount`, `countLosses`, LeanTween-like calls. Do not use as data truth without a focused dossier. |

### `BhTooltipUnitCountLosses`

| Current method | Static claim | Evidence |
|---|---|---|
| `tea()` | Add-unit/positive visual mode candidate. | Calls `Image.set_sprite`, touches `skull`, `text`, `green`, `iconAddUnit`. Mono has a corresponding add-unit visual mode. |
| `teb()` | Skull/loss/negative visual mode candidate. | Type-level mirror of `tea`; touches `skull`, `text`, `red`, `iconSkull`. Generate focused dossier before patching. |

### `BhHireUnitAbilityView`

| Current method | Static claim | Evidence |
|---|---|---|
| `bann(bzd, AbilityViewConfig)` | Active ability bind candidate. | Activates object/icon, writes `cegi` context and `cegh` config, sets `cegj`, calls `cko.sfo`, `Image.set_sprite`, and `hmh`. Matches Mono active bind shape. |
| `bano(AbilityViewConfig, bzd)` | Passive ability bind candidate. | Checks `String.IsNullOrEmpty`, activates object/icon, writes same context/config fields, calls `cko.sfo`, `Image.set_sprite`, and `hmh`. Matches Mono passive bind shape. |
| `OnHover()` / `OnPointerEnter()` | Tooltip dispatch candidates. | Field usage reads `cegh`, `cegi`, `cegj`, `cegk`, and `rect`; Mono dispatches active/passive tooltip based on stored state. Runtime-facing tooltip changes should prefer bind-time icon/text fixes over hover-time fallback. |

### `BhHireUnitAbilityItemView`

| Current method | Static claim | Evidence |
|---|---|---|
| `banl(bzd, AbilityViewConfig)` | Active ability item bind candidate. | Activates object/icon, writes `cegf` context and `cege` config, sets `cegg = true`, calls `cko.sfo`, and `Image.set_sprite`. Matches Mono active bind shape. |
| `banm(bzd, AbilityViewConfig)` | Passive ability item bind candidate. | Similar to `banl`, but writes `cegg = false`; calls `cko.sfo` and `Image.set_sprite`. Matches Mono passive bind shape. |
| `Init(string)` | Plain SID icon initializer candidate. | Current method exists and type-level evidence touches `pic`; generate focused dossier if we need plain icon replacement here. |
| `OnHover()` / `OnPointerEnter()` | Tooltip dispatch candidates. | Field usage reads `cege`, `cegf`, `cegg`, and `rect`; Mono dispatches active/passive tooltip based on stored state. |

### `BhUnitPreviews`

| Current method | Static claim | Evidence |
|---|---|---|
| `htv(string, float, out clt)` | Model-preview load/cache/get candidate. | Calls dictionary `TryGetValue`, queue `Dequeue`, `BhUnitPreviews.htz`, object equality, transform rotation, and `UnitPreviewRotation.kxg`; matches Mono preview model load/reuse shape. |
| `htx()` | Preview camera get candidate. | Type-level evidence shows queue/pool access; generate focused dossier if replacing pool behavior. |
| `hty(BhUnitPreview)` | Preview camera return candidate. | Type-level evidence shows queue/pool access; generate focused dossier if replacing pool behavior. |
| `htz(UnitViewConfig)` | Model/platform creation candidate. | High-complexity type-level evidence and called from `htv`; inspect only if unit preview model creation is still a hotspot. |
| `hua(string)` | Texture lookup/cache candidate. | Type-level evidence shows texture dictionary/cache field `bpst` and fallback texture `bpsu`. |

## Current mod risk surface

`Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/BattleTooltipProbe.cs` is a stale probe-style file. It references old candidate names:

- `BhTooltipUnit.tbw`
- `BhTooltipUnit.tbx`
- `BhTooltipUnit.tby`
- `BhTooltipUnit.tca`
- `BhTooltipUnit.tcb`
- `BhTooltipUnitCountLosses.tch`
- `BhTooltipUnitCountLosses.tar`

Current deobf exposes `BhTooltipUnit` methods `Show`, `Hide`, `tdp`, `tdq`, `tdr`, `tds`, `tdt`, `tdu`, `tdv`, `tdw`, `tdx`, `tdy`, `tdz`, and `BhTooltipUnitCountLosses` methods `tea`, `teb`. The probe file should not be treated as authoritative for current builds. It should either be retired or rewritten against the exact current surfaces above, depending on whether this debug feature is still needed.

## Practical modding conclusions

- For custom unit portrait/count tooltip display, patch or adapt `BhTooltipUnit.tdp` and the two public `Show` overloads. Do not hook generic tooltip hover routes for portrait replacement.
- For loss/add-unit notification visuals, use `BhTooltipUnitCountLosses.tea/teb` only after a focused `teb` dossier. Do not infer positive/negative semantics solely from method names.
- For hire screen ability icons, use bind surfaces `BhHireUnitAbilityView.bann/bano` and `BhHireUnitAbilityItemView.banl/banm`. These are better than dictionary guards because they receive both context and `AbilityViewConfig` before icon assignment.
- For hire screen tooltip text, prefer fixing stored context/config at bind time. Hover methods should remain dispatch-only unless runtime proof shows bind-time state cannot be corrected.
- For unit model preview performance or custom model display, `BhUnitPreviews.htv` is the first current hook candidate because it is the cache/load boundary. Do not patch `BhUnitPreview` itself until the pool path is proven insufficient.

## Static gaps

- `BhTooltipUnit.tdr`, `tdq`, `tds`, `tdt`, `tdu`, `tdv`, `tdx`, `tdy`, and `tdz` need focused dossiers before any tooltip animation/loss behavior is changed.
- `BhTooltipUnitCountLosses.teb` needs a focused dossier to confirm negative/loss visual mode.
- `BhHireUnitAbilityView.OnHover` and `BhHireUnitAbilityItemView.OnHover` are only semantically inferred from Mono plus field usage; no current hover dossier was generated in this slice.
- No runtime order is proven. This document says where to hook, not when those hooks fire in a live UI.

## Next static work

1. Generate focused dossiers for `BhTooltipUnit.tdr`, `BhTooltipUnit.tdu`, and `BhTooltipUnitCountLosses.teb` if tooltip loss/add-unit behavior matters.
2. Generate focused dossiers for `BhHireUnitAbilityView.OnHover` and `BhHireUnitAbilityItemView.OnHover` only if bind-time icon/context repair is insufficient.
3. Audit current code for hooks that patch tooltip/hire ability UI outside these bind surfaces and classify them as keep, replace, or retire.
4. If runtime testing is requested later, test only the exact bind surfaces first; avoid reintroducing broad tooltip probes.
