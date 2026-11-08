# Selected-Unit HUD Donor Alias Audit - 2026-06-25

## Scope

Audit whether the selected-unit HUD pre-native donor alias is asset-only or identity-bearing.

This is a diagnostic audit only. It does not change runtime behavior.

## Current Mod Path

- `Homm3ImportBhSelectedUnitHudFix.PrefixBeetRelease` and `PrefixBegsRelease` run before native selected-unit HUD event/direct bind methods.
- For custom HoMM3 unit SIDs with a donor SID, both prefixes call `BeginReleaseNativeSidAlias(unit, sid, donorSid)`.
- `BeginReleaseNativeSidAlias` writes the donor SID onto the live `Unit` and aliases related config IDs before native code runs.
- Postfix/finalizer paths restore the original SID and call `RecoverUnitControlsRelease`, which rebonds action-bar controls from the custom SID.

Source evidence:

- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ImportBhSelectedUnitHudFix.cs`
  - `PrefixBeetRelease`
  - `PrefixBegsRelease`
  - `BeginReleaseNativeSidAlias`
  - `RecoverUnitControlsRelease`
  - `DirectBindUnitControlsRelease`

## Static Native Evidence

Generated dossiers:

- `tmp/cpp2il_experiment/readable_notes/BhSelectedUnitHud_bejn_selected_unit_hud_alias_audit.md`
- `tmp/cpp2il_experiment/readable_notes/BhSelectedUnitHud_bejo_selected_unit_hud_alias_audit.md`
- `tmp/cpp2il_experiment/readable_notes/BhUnitControlsView_beln_selected_unit_hud_alias_audit.md`

Key findings:

- `BhSelectedUnitHud.bejn(object, BattleEventArgs)` reads selected-unit event data, calls `dxx.baql`, and then calls `BhUnitControlsView.beln` with an ability array and selected ability.
- `BhUnitControlsView.beln(dxy[] a, dxy b, bool c)` stores and mutates action-bar state:
  - `chap` stores the passed `dxy[]` ability array.
  - `chan` stores/looks up `dxy -> emb` wrappers.
  - `abilities` stores/reuses `BhUnitAbilityView` rows.
  - `BhUnitAbilityView.beky` binds a row from the wrapper.
  - `BhUnitControlsView.belt` selects the current ability.
- Therefore the native selected-unit HUD path is identity-bearing. It constructs persistent action-bar controls, wrappers, selected ability state, and hotkey/click payload surfaces.

## Classification

The pre-native selected-unit HUD donor alias is not proven asset-only.

Static evidence classifies the alias window as identity-bearing because native code builds action-bar ability state while the alias is active.

The existing postfix recovery path may overwrite or repair this state, but that is a repair-after-native strategy, not an asset-only strategy.

## Runtime Evidence

Runtime proof was attempted through `tools/release_port/live_probe_request.py status`, then the user confirmed the game was closed.

Result:

- The bridge status file reported `state=ready`, `profile=OfficialDeobf`, `scene=cityHuman2`.
- The live request timed out and could not remove its stale inbox request due `WinError 5 Access is denied`; this is consistent with no active game process consuming bridge requests.
- No live selected-unit battle HUD runtime ordering proof was collected because the game was closed.

Runtime visibility remains unproven:

- Whether donor-built native action-bar state is visible for a frame.
- Whether donor-built wrappers, selected ability, hover payloads, or hotkey payloads survive after postfix recovery.
- Whether cached native state can be reused before `DirectBindUnitControlsRelease` replaces it.

## Production Implication

The selected-unit HUD pre-native alias should be treated as a known risk, not as a closed compatibility path.

Preferred next fix direction:

1. Stop presenting donor SID/config IDs to native selected-unit HUD bind methods when they can construct identity-bearing action controls.
2. Preserve custom SID through native-selected HUD identity paths.
3. Move donor use to clearly asset-only surfaces, such as portrait/sprite repaint, or replace native selected-unit action-bar construction with the existing custom-SID direct bind path before native identity work runs.
4. Extend `validate_homm3_no_donor_identity_rewrite_contract.py` to cover `PrefixBeetRelease`, `PrefixBegsRelease`, `BeginReleaseNativeSidAlias`, `WriteUnitSid`, and `AliasReleaseConfigIds` once the production path is changed.

## Evidence Boundary

Proven:

- Static Cpp2IL/ISIL evidence shows native selected-unit HUD event bind calls ability-manager/action-bar binding.
- Static Cpp2IL/ISIL evidence shows `BhUnitControlsView.beln` stores and binds ability wrappers/views.
- Current mod source writes donor SID/config IDs before those native paths run.

Not proven:

- Live runtime ordering in an active battle.
- Whether current postfix recovery always wins before user-visible frame, hover, click, hotkey, or cache reuse.
- A production-safe replacement path.
## Follow-Up Implementation - 2026-06-25

The production path has now been changed in source and validated by build, but remains runtime-unvalidated.

Implemented behavior:

- `PrefixBeetRelease` and `PrefixBegsRelease` now classify custom units with `Homm3CustomFactionRegistry.IsCustomUnitSid(sid)` and preserve the custom SID through native selected-HUD bind entry points.
- The release selected-HUD prefixes no longer resolve donor SIDs, seed custom SID dictionary entries from donor data, call `BeginReleaseNativeSidAlias`, call `WriteUnitSid`, or alias config IDs before native code runs.
- `SelectedUnitHudCustomSidState` carries only the custom SID into postfix/finalizer recovery.
- `FinalizerBeetRelease` and `FinalizerBegsRelease` now allow first-time custom-SID `KeyNotFoundException` recovery through `RecoverUnitControlsRelease` only when the missing key is the current custom SID or currently cached release SID; unrelated missing keys fail closed.
- `tools/validate_homm3_no_donor_identity_rewrite_contract.py` and `tools/validate_selected_unit_hud_actionbar_contract.py` now reject reintroducing the selected-HUD donor identity alias lane, release-path donor dictionary seeding, release-path donor lookup, and release-path `WriteUnitSid` calls.

Validation passed after the source change:

- `python tools\validate_selected_unit_hud_actionbar_contract.py`
- `python tools\validate_homm3_no_donor_identity_rewrite_contract.py --plugin-dir "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod"`
- `python -m py_compile tools\validate_selected_unit_hud_actionbar_contract.py tools\validate_homm3_no_donor_identity_rewrite_contract.py`
- Scoped `git diff --check` for the touched source and validators.
- Golden Era Release no-deploy build with `DeployPluginToGame=false` passed with 0 errors and 50 existing warning-class warnings.

Still not proven:

- Runtime selected-unit HUD behavior in an active battle after deployment/restart.
- Whether native selected-HUD custom-SID bind succeeds directly or relies on finalizer recovery for every custom unit case.
- User-visible hover/click/hotkey behavior after a live selected-unit transition.
