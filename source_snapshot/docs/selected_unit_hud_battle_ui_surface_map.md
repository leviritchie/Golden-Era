# Selected Unit HUD and Battle UI Surface Map

Status: source-prepared/static-reviewed, runtime-unvalidated for this pass.

Purpose: constrain future selected-unit HUD and battle UI cleanup to exact native contracts. This document is not proof that a rewritten hook is runtime-safe; it records the current static evidence used to plan cautious changes.

## Current native contracts

### Selected unit HUD owner

Type: `Hex.Session.Battle.BhSelectedUnitHud`

Current Golden Era readable surfaces:

| Surface | Method/field | Static role |
|---|---|---|
| Event bind | `bejn(object, BattleEventArgs)` | Native selected-unit HUD refresh from battle event payload. |
| Direct bind | `bejo(bool, Unit)` | Native selected-unit HUD refresh from explicit unit argument. |
| Controls view | field `controlsView` at offset `0x30` | Owner of action bar controls. |
| Unit view | field `unitView` at offset `0x28` | Owner of selected unit portrait/details. |
| Queue view | field `queue` at offset `0x70` | Battle turn queue surface owned by the selected HUD. |

Current mod entry points:

| File | Current behavior |
|---|---|
| `Homm3ImportBhSelectedUnitHudFix.cs` | Required release-safe guard for custom unit SIDs reaching selected-HUD native dictionary code. |
| `Homm3ImportReleaseBattleUiHook.cs` | Separate portrait remap path for selected HUD, selected unit view, queue, hero views, and battle result views. |

Risk boundary:

The selected-HUD guard should only alias custom unit/config IDs around the native bind call and then restore them in postfix/finalizer. It should not become a generic battle UI image scanner.

### Unit controls owner

Type: `Hex.Session.Battle.BhUnitControlsView`

Current Golden Era readable surfaces:

| Surface | Method/field | Static role |
|---|---|---|
| Bind abilities | `beln(dxy[] a, dxy b, bool c)` | Native action-bar bind. Stores current action wrappers and selects the requested wrapper. |
| Click ability view | `belo(BhUnitAbilityView a)` | Public click path called by ability view buttons. |
| Sync ability view | `belq(BhUnitAbilityView a)` | View/config helper. Not the selected action-wrapper setter. |
| Select wrapper | `belt(dxy a)` | Native selected action-wrapper path. |
| Set click enabled | `belz(bool a)` | Enables/disables control clicking. |
| Hotkey | `beme(object a, HotkeyAbilityArgs b)` | Number-key path for selected-unit action slots. |
| Selected view field | `chao` | Currently selected `BhUnitAbilityView`. |
| Current ability array | `chap` | Current `dxy[]` action-wrapper array. |

Known important distinction:

`belt(dxy)` is the selected action-wrapper setter. `belq(BhUnitAbilityView)` is not. Shape-only matching is unsafe because current Golden Era has multiple `void(dxy)` and `void(BhUnitAbilityView)` style neighbors.

### Unit ability view owner

Type: `Hex.Session.Battle.BhUnitAbilityView`

Current Golden Era readable surfaces:

| Surface | Method/field | Static role |
|---|---|---|
| View bind | `beky(emb a, bool b)` | Binds the UI/view wrapper and visible/enabled state. |
| Click | `OnClicked()` | Calls `controlsView.belo(this)` when allowed. |
| Action wrapper getter | `coak` / `bekw()` | Exposes current `dxy` action wrapper. |
| UI wrapper field | `chae` | Current `emb` UI/view wrapper. |
| Action wrapper field | `chaf` | Current `dxy` action wrapper. |

Wrapper split:

| Wrapper | Current readable name | Role |
|---|---|---|
| Action-bar ability wrapper | `dxy` | Carries selected action/logic data used by controls bind/select. |
| UI/view wrapper | `emb` | Carries view/config data used by ability button binding. |

Do not conflate these. `dwr` has been rejected for the current release selected-HUD path in earlier notes and should not be accepted as a current Golden Era action-bar wrapper without fresh proof.

## Current fragility found

1. `Homm3ReleaseUnitControlsProbe.cs` was stale for current Golden Era and has been retired.

It probed old names:

- Event handlers: `beix`, `beiz`, `beja`, `bejc`, `bejh`, `beji`, `bejk`
- Select methods: `beiy`, `bejb`
- Hotkey: `bejj`
- Selected field comment: `cgwy`

Current readable names are:

- Event/neighbor handlers: `bels`, `belu`, `belv`, `belx`, `bemc`, `bemd`, `bemf`
- Select wrapper: `belt`
- Hotkey: `beme`
- Selected view field: `chao`

The file was unreferenced outside itself and was removed. Use current decomp evidence for this surface instead of reviving the old probe.

2. `GameSymbols.SelectedUnitHud.AbilityWrapperTypeNames` still includes `dwr`.

Current static docs say the release path should use `dxy` / generated `ObjectPublicObceInBoInceAbObELInUnique`. Keeping `dwr` as a compatibility hint may be intentional for older lanes, but current Golden Era cleanup should not let `dwr` win resolution for selected-unit controls.

3. Selected-HUD guard and battle portrait replacement are mixed in practice.

`Homm3ImportBhSelectedUnitHudFix.cs` now owns custom SID aliasing, action-bar recovery, click/hotkey recovery, selected portrait replacement, stale ability view cleanup, and several diagnostic/reflection helpers. `Homm3ImportReleaseBattleUiHook.cs` separately owns portrait/timeline/hero-view replacement. Future cleanup should keep these concerns separate:

- native dictionary alias guard,
- action-bar ability recovery,
- click/hotkey routing,
- selected-unit portrait replacement,
- turn-queue portrait replacement,
- hero/battle-result portrait replacement.

4. Registration can route through more than one path.

`Plugin.RegisterRequiredHomm3SelectedHudGuard()` requires `Homm3ImportBhSelectedUnitHudFix.RegisterReleaseRequired()` when `ReleaseSafeProfile && Homm3ImportEnabled`. `Homm3ImportVisuals.TryRegisterReleaseFullFeatureSlice()` can also attempt the selected-HUD softlock suppressor and release battle UI feature path. The `_patched` guards reduce duplicate patch risk, but the registration story is harder to reason about than necessary.

## Cautious cleanup sequence

1. Documentation-only pass.

This file is the first pass. No behavior is changed.

2. Stale-probe pass.

Completed source-side: `Homm3ReleaseUnitControlsProbe.cs` was removed because it was unreferenced and encoded stale method names. This removal has not been build-validated in this pass.

3. Symbol hygiene pass.

Separate current Golden Era symbols from old compatibility hints where practical. At minimum, ensure current exact names are always preferred and old rejected names cannot silently win current release resolution.

4. Responsibility split pass.

Move selected-HUD dictionary aliasing, action-bar recovery, click/hotkey handling, and portrait replacement into smaller helpers without changing behavior. This should make future crashes traceable to one owner.

5. Runtime proof pass.

After code cleanup, test:

- combat loads with custom units,
- selecting a custom unit does not throw selected-HUD dictionary errors,
- custom action-bar mouse click toggles through `BhUnitAbilityView.OnClicked -> BhUnitControlsView.belo`,
- number-key activation uses `beme`,
- selected action state synchronizes through `belt(dxy)`,
- selected-unit portrait is correct,
- turn queue portraits are correct,
- vanilla unit selected-HUD behavior remains native.

## Evidence references

- Current readable Cpp2IL:
  - `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/Battle/BhSelectedUnitHud.cs`
  - `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/Battle/BhUnitControlsView.cs`
  - `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/Battle/BhUnitAbilityView.cs`
- Current mod surfaces:
  - `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ImportBhSelectedUnitHudFix.cs`
  - `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ImportReleaseBattleUiHook.cs`
  - `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ReleaseUnitControlsProbe.cs`
  - `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/GameSymbols.cs`
- Prior notes:
  - `docs/deobf_static_pass_progress.md`
  - `docs/AGENT_REFERENCE.md`
