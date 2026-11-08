# Selected-unit action-bar hotkey — static analysis

Status: **source/static** (Cpp2IL / DiffableCs / ISIL dossiers). Not runtime-proven.
Date: 2026-07-31.
Purpose: pin what vanilla number keys require before choosing a custom-unit fix.

## Player verb

Press `1`–`5` while a battle unit is selected → select the matching action-bar ability (same as clicking the button).

## Ownership chain (static)

```text
Hotkey system
  → HotkeyAbilityArgs { idButton @0x20, isEsc @0x24, isReturnDeselect @0x25 }
  → BhUnitControlsView.beme(object, HotkeyAbilityArgs)   // ControlsHotkey
       gates on abilities list + idButton + view.chae (emb @0x30)
       → BhUnitControlsView.belo(BhUnitAbilityView)       // same as mouse click
```

Selected-unit bar construction (identity-bearing):

```text
BhSelectedUnitHud.bejn(object, BattleEventArgs)   // HudEventBind (release also beet/begr…)
  → builds ability wrappers
  → BhUnitControlsView.beln(dxy[], dxy, bool)     // ControlsBind
       stores chap = ability array
       builds emb wrappers into chan
       BhUnitAbilityView.beky(emb, bool)          // sets chae / click state
       BhUnitControlsView.belt(dxy)               // selected sync
```

Evidence dossiers (repo):

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_ui_BhUnitControlsView_beme_dossier.md`
- `…/battle_ui_BhUnitControlsView_beln_dossier.md`
- `…/battle_ui_BhUnitAbilityView_OnClicked_dossier.md`
- `…/battle_ui_BhSelectedUnitHud_bejn_dossier.md`
- `tmp/cpp2il_experiment/readable_notes/BhUnitControlsView_beln_selected_unit_hud_alias_audit.md`

## Native hotkey gate (critical)

ISIL/disasm outline of `beme` (`source/static`):

1. Bail if `abilities` is null.
2. Bail if `HotkeyAbilityArgs` is null.
3. Bail if `abilities.Count <= idButton` (list index; base is **not** proven here — Mono body used zero-based; release notes claim one-based for selected-unit slots).
4. `view = abilities[idButton]`; bail if null.
5. Bail if `view+0x30` is null/empty (`cmp qword ptr [rax+30h],0` / `jbe`).
6. Call `belo(this, view)`.

DiffableCs field at ability-view `0x30`:

| Offset | Field | Type | Role |
| --- | --- | --- | --- |
| `0x20` | `controlsView` | `BhUnitControlsView` | owner |
| `0x28` | `viewBase` | `BhAbilityViewBase` | visuals |
| **`0x30`** | **`chae`** | **`emb`** | **UI/view wrapper — native hotkey gate** |
| `0x38` | `chaf` | `dxy` | action wrapper |
| `0x40`–`0x43` | `chag`…`chaj` | `bool` | click/block/enable family |

**Claim (`source/static`):** native number keys require a non-null `emb` (`chae`) on the indexed `BhUnitAbilityView`. Visible icons alone are insufficient.

Mouse `OnClicked` has a separate clickable/blocked gate before calling `belo`. Those bools matter for clicks; hotkey’s first hard gate in current ISIL is `chae`.

## Current mod path (source)

`Homm3ImportBhSelectedUnitHudFix`:

- Preserves custom SID through selected-HUD bind (donor identity alias disabled; contract-enforced).
- On miss / after bind: `RecoverUnitControlsRelease` → `DirectBindUnitControlsRelease` (`Clear` + controls bind + click-enable).
- Harmony prefix on controls hotkey: if recovered custom context, map `idButton` (try `idButton-1` then raw) and `InvokeReleaseControlsClick`.

Implication (`hypothesis` until probed):

- If recovery binds views without `chae`, **native** `beme` will no-op even when mouse recovery works.
- If mod hotkey prefix context misses (`_lastBoundReleaseControlsView` / sid cache), keys fall through to native and still fail.
- Index base (`idButton` 0 vs 1) remains an open runtime question.

## Preferred fix direction (not implemented here)

One ownership path:

1. Custom SID completes native `beln` with full `emb`/`dxy` readiness, **or**
2. Early exclusive `DirectBind` that leaves the same readiness native hotkeys expect.

Then retire hotkey Harmony as the normal path.

Forbidden: donor SID rewrite before identity-bearing bind (`validate_homm3_no_donor_identity_rewrite_contract.py`).

## Runtime questions this probe must answer

| ID | Question | How |
| --- | --- | --- |
| Q1 | Does selected-HUD bind throw `KeyNotFoundException` for custom SID? | HUD event/direct bind finalizer |
| Q2 | After bind/recovery, does each slot have `chae` (emb)? | controls bind postfix + slot dump |
| Q3 | What `idButton` values arrive for keys `1`–`5`? | hotkey prefix |
| Q4 | Does native `beme` pass the `Count` / `chae` gates for that `idButton`? | hotkey prefix prediction |
| Q5 | Does native `belo` run, or only mod intercept / neither? | hotkey postfix vs click postfix |
| Q6 | Vanilla unit: same dump shows emb present and hotkey → belo | control comparison |

## Probe enablement (local only)

- Flag file: `homm3_selected_unit_hud_hotkey_probe.flag` next to the deployed plugin (not committed; deploy deletes it).
- Optional MSBuild: `/p:EnableSelectedUnitHudHotkeyProbe=true` (default off so normal/public builds omit the type).
- Release candidate builds always exclude the probe source.
- Grep key: `HOMM3_SUH_HOTKEY_PROBE`
