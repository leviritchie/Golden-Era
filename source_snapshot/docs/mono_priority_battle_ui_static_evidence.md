# Mono Priority Battle UI Static Evidence

Status: static-only, runtime-unvalidated.

Inputs:

- Mono demo decompile: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_priority_battle_ui_decompiled.cs`
- Current map JSON: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_deobf_semantic_map.json`
- Current deobf shells: `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/Battle/*.cs`
- Current selected-HUD surface map: `docs/selected_unit_hud_battle_ui_surface_map.md`

## High-value Mono semantics

| Mono owner/member | Mono behavior observed statically | Current deobf candidate | Evidence strength |
|---|---|---|---|
| `BhSelectedUnitHud.SetUnit(object, BattleEventArgs)` | Pulls `Unit` from `BattleEventArgs.target` or from `CastAbilityEventArgs.caster`, computes controllability, then updates selected-unit HUD children. | `BhSelectedUnitHud.bejn(object, BattleEventArgs)` for event route; `BhSelectedUnitHud.bejo(bool, Unit)` for direct bind route. | Owner/type strong-static; method semantic candidate. Current deobf call/body evidence still required before changing hook logic. |
| `BhSelectedUnitHud.OnUnitStartTurn(object, BattleEventArgs)` | Updates `currentTurnSideId_` from `_e.target.GetSide().index`. | Current neighboring `BattleEventArgs` selected-HUD handlers `bejp`/`bejq` are candidates for turn/wait side tracking. | Candidate only. Do not use ordinal matching as proof. |
| `BhUnitAbilityView.SetView(UIAbility,bool)` | Extracts underlying unit `Ability`, stores UI wrapper/control state, activates the button, sets icon/cooldown/charges/clickability. | `BhUnitAbilityView.beky(emb,bool)`. | Candidate-static plus current deobf wrapper evidence (`emb` view wrapper, `dxy` action wrapper). |
| `BhUnitAbilityView.OnClicked()` | If not blocked and clickable, calls `controlsView.OnSkillClicked(this)`. | Current exact `BhUnitAbilityView.OnClicked()` calling controls click path `BhUnitControlsView.belo(BhUnitAbilityView)`. | Strong-static for click entry; downstream target supported by current deobf evidence. |
| `BhUnitControlsView.SetSkills(Ability[], Ability, bool)` | Stores current ability array/control flag, resets selected ability, then either creates UI ability buttons or updates existing buttons. | `BhUnitControlsView.beln(dxy[], dxy, bool)`. | Strong owner/type, candidate semantic mapping. Good target for action-bar bind/recovery. |
| `BhUnitControlsView.OnSkillClicked(BhUnitAbilityView)` | If controllable and view belongs to ability list, toggles selected view: deselects if already selected, otherwise sends select command. | `BhUnitControlsView.belo(BhUnitAbilityView)`. | Candidate-static plus current deobf click evidence. |
| `BhUnitControlsView.SelectAbility(Ability)` | Finds the matching ability view, updates selected visual state, resets previous selected view, then stores selected view. | `BhUnitControlsView.belt(dxy)` as current selected action-wrapper sync path. | Candidate-static plus current deobf evidence. This supports the semantic name but does not replace current deobf proof. |
| `BhUnitControlsView.SetAbilitiesClickable(bool)` | Iterates ability views and calls `SetClickable` on each. | `BhUnitControlsView.belz(bool)`. | Candidate-static plus current deobf evidence. |
| `BhUnitControlsView.OnHotkeyClickAbility(object, HotkeyAbilityArgs)` | Checks `abilities.Count > idButton` and `CanUseHotKey()`, then calls `OnSkillClicked(abilities[idButton])`. | `BhUnitControlsView.beme(object, HotkeyAbilityArgs)`. | Candidate-static plus exact `HotkeyAbilityArgs` type preservation. Runtime notes about one-based vs zero-based index remain current-build evidence, not Mono proof. |

## Current deobf dossier comparison

These rows compare the old Mono bodies against current Golden Era Cpp2IL/ISIL dossiers. This upgrades several mappings from name/ordinal hypotheses to static body/xref evidence, but it still does not prove runtime hook safety.

| Surface | Current deobf evidence | Static confidence | Notes and gaps |
|---|---|---|---|
| Ability button click entry | `BhUnitAbilityView.OnClicked()` directly calls `BhUnitControlsView.belo(this)` after local blocked/clickable checks. Dossier: `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_ui_BhUnitAbilityView_OnClicked_dossier.md`. | proven-static current body | Matches Mono `BhUnitAbilityView.OnClicked -> controlsView.OnSkillClicked(this)`. Runtime click ordering and UI object lifecycle remain unproven. |
| Controls click handler | `BhUnitControlsView.belo(BhUnitAbilityView)` checks the ability-view list, compares against field `chao`, and follows the selected/deselected command path. Dossier: `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_ui_BhUnitControlsView_belo_dossier.md`. | strong static candidate | Matches Mono `OnSkillClicked` shape. Some command-send callees remain unresolved native addresses, so exact command object semantics are not fully named. |
| Selected ability sync | `BhUnitControlsView.belt(dxy)` enumerates ability views, calls selected/unselected visual methods on `BhAbilityViewBase`, compares against field `chao`, calls `BhUnitControlsView.bely`, and writes `chao`. Dossier: `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_ui_BhUnitControlsView_belt_dossier.md`. | proven-static current body | Matches Mono `SelectAbility(Ability)`: find matching view, update selected visual state, reset previous selection, store selected view. |
| Skill/action bar bind | `BhUnitControlsView.beln(dxy[], dxy, bool)` stores `chap`, stores `chas`, builds/reuses `emb` wrappers, calls `BhUnitAbilityView.beky(emb,bool)`, disables unused views, and ends by calling `BhUnitControlsView.belt(b)`. Dossier: `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_ui_BhUnitControlsView_beln_dossier.md`. | proven-static current body | Matches Mono `SetSkills(Ability[], Ability, bool)`. This is the current best native binding point for selected-unit action-bar repair/adaptation. |
| Hotkey ability route | `BhUnitControlsView.beme(object, HotkeyAbilityArgs)` checks `HotkeyAbilityArgs.idButton`, indexes `abilities`, checks a per-view field at offset `0x30`, then calls `BhUnitControlsView.belo(view)`. Dossier: `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_ui_BhUnitControlsView_beme_dossier.md`. | proven-static current body with index caveat | Matches Mono hotkey route. Mono body uses zero-based `idButton`; current runtime notes about one-based selected-unit action slots remain authoritative until current-build runtime metadata/body evidence resolves that discrepancy. |
| Clickability toggle | `BhUnitControlsView.belz(bool)` reads `abilities`, indexes ability view `0`, and writes the incoming bool to the ability-view field at offset `0x43`. Dossier: `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_ui_BhUnitControlsView_belz_dossier.md`. | partial/static drift | This does not fully match Mono `SetAbilitiesClickable(bool)`, which iterated every ability view. Treat `belz` as current-build partial clickability surface until neighboring handlers explain the per-button or batched update path. |
| Event-based selected unit bind | `BhSelectedUnitHud.bejn(object, BattleEventArgs)` initializes CastAbilityEventArgs metadata, reads `BattleEventArgs.target`, checks `Unit.beyw`, toggles not-your-turn animation, calls `BhSelectedUnitHud.bejo(bool, Unit)`, builds action arrays, and calls `BhUnitControlsView.beln(...)`, plus unit command/basic command bind paths. Dossier: `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_ui_BhSelectedUnitHud_bejn_dossier.md`. | proven-static current body | Matches Mono `SetUnit(object, BattleEventArgs)` event route. Current direct caster extraction from `CastAbilityEventArgs` is indicated by metadata setup but still needs closer body slicing if we plan to hook caster-specific branches. |
| Direct selected unit bind | `BhSelectedUnitHud.bejo(bool, Unit)` body is much smaller and mostly iterates/constructs `emc` observers; it does not perform the full child-view bind seen in `bejn`. Dossier: `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_ui_BhSelectedUnitHud_bejo_dossier.md`. | candidate-static only | Contrary to the original hypothesis, `bejo` appears to be a helper inside selected-unit binding, not a complete direct replacement for Mono `SetUnit(bool, Unit)`. Prefer `bejn` or downstream child bind methods for HUD repair until `bejo` is better named. |
## Important conclusions

- The old Mono structure supports the current architectural split: selected HUD owns unit binding, controls view owns action selection/clickability/hotkeys, ability view owns per-button UI and forwards clicks to controls.
- This supports retiring broad selected-HUD probes in favor of exact owner/method contracts.
- The current dossiers now provide strong static evidence for `bejn`, `beln`, `belo`, `belt`, and `beme`, plus exact click forwarding from `BhUnitAbilityView.OnClicked`.
- `belz` and `bejo` are the two mismatches: both remain useful candidates, but the current bodies do not cleanly match the old Mono whole-method semantics.
- Ordinal matching is useful only as a weak hypothesis because constructors, property getters, nested compiler helpers, and patch drift shift method order.

## Next static improvement layer

For each high-risk hook surface, build or refresh a current deobf method dossier and compare its call graph to the Mono semantic body:

- `BhUnitAbilityView.OnClicked` should call the controls click route.
- `BhUnitControlsView.belo` should perform the Mono `OnSkillClicked` role or call into the selected-wrapper path.
- `BhUnitControlsView.belt` should perform the Mono `SelectAbility` role: selected view state mutation and selected field update.
- `BhUnitControlsView.belz` should iterate or delegate clickability changes to ability views.
- `BhUnitControlsView.beme` should read `HotkeyAbilityArgs.idButton` and route to click/select behavior.
- `BhSelectedUnitHud.bejn` should resolve the event unit and update child views; `bejo` should be the explicit unit route.

