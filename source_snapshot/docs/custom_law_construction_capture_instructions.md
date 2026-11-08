# Custom Law Construction Capture Instructions

Status: diagnostic surface registration proven; construction packet gameplay remains unproven.

Use this when capturing evidence for the `construction` packet.

## Required flags

Apply the `construction` profile before game startup:

```powershell
python tools/release_port/custom_law_diag_flags.py apply --plugin-root "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod" --profile construction
```

This enables:

- `homm3_custom_faction_law_diag.flag`
- `homm3_custom_construction_law_diag.flag`
- `homm3_custom_faction_economy_diag.flag`

## Current startup proof

June 17 Golden Era startup proved:

- `Homm3CustomFactionLawRuntime` packet gate and handler slots log at startup.
- `Homm3CustomConstructionLawDiagnostics` registers 7 exact trace patches.
- `Homm3CustomFactionEconomyLawDiagnostics` registers 2 exact trace patches.
- Gameplay mutation remains disabled.

## Live bridge preflight

Before asking for construction evidence, confirm the bridge is live:

```powershell
python tools/release_port/live_probe_request.py status
```

Confirm whether a town UI is actually active:

```powershell
python tools/release_port/live_probe_request.py town_ui_state
```

For construction packet evidence, `town_ui_state` should show a city scene, a current custom faction, and a cached town wrapper. If it reports `mainMenuDecor`, `startMenu`, no current faction, or no cached wrapper, construction diagnostics cannot yet prove town-build behavior.

Use the combined preflight when deciding whether a capture attempt is worthwhile:

```powershell
python tools/release_port/preflight_construction_law_capture.py
```

This preflight is read-only. It fails until the bridge is ready in `OfficialDeobf`, the active scene is a city scene, the current faction is a `homm3_*` faction, and the live town wrapper/city data are present. A passing preflight does not prove construction gameplay; it only means the user can perform the player scenario below and expect diagnostics to have the necessary town context.

To leave the preflight running while navigating into a town:

```powershell
python tools/release_port/preflight_construction_law_capture.py --wait-seconds 120
```

To monitor the whole construction proof window, use:

```powershell
python tools/release_port/monitor_construction_law_capture.py --wait-preflight-seconds 300 --wait-evidence-seconds 300
```

This first waits for the live town context required by preflight, then watches `BepInEx\LogOutput.log` for the mechanical construction/economy checklist. It is read-only and still does not replace human review or packet promotion.

## Player scenario

1. Start or load a game with a custom faction town.
2. Open the town construction/building screen.
3. Select an unbuilt legal building.
4. Note the visible displayed cost and building name.
5. Build the selected building.
6. Note the visible resource change and final constructed state.
7. If possible, repeat once with a town/hero/side that has an active rank in a construction law at law index `28`.

## Evidence required before packet promotion

The packet remains unproven unless the captured logs show, in one coherent interaction:

- `building-view-bind-candidate` identifies selected building context.
- `building-session-select-candidate` correlates to the same selected/build context.
- `building-session-cost-candidate` correlates to the visible displayed cost.
- `buildings-manager-state-candidate` and `buildings-manager-refresh-candidate` bracket or follow the committed build.
- Economy diagnostics show the charged resource mutation or enough resource context to match visible cost.
- A final building view/update line shows constructed-state agreement.
- `activeKnownCustomLawsFromThisObject` proves active custom law/rank from the same construction context, or the capture is explicitly marked insufficient for gameplay promotion.

Do not promote `construction` from a UI-only sequence, a resource-only sequence, or any sequence where active law/rank is `none-or-unresolved` in every construction context.

## Capture bundle command

After the scenario, collect logs:

```powershell
python tools/release_port/collect_custom_law_capture.py --game-root "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era" --scenario construction-town-build --profile construction --notes "Town build interaction for construction packet proof review."
```

The bundle is raw evidence only. Review it against this checklist before promoting packet proof state.

## Mechanical analyzer

Run this against either the live log or the collected capture directory:

```powershell
python tools/release_port/analyze_construction_law_capture.py --log "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\LogOutput.log"
```

or:

```powershell
python tools/release_port/analyze_construction_law_capture.py --log "artifacts\custom_law_captures\<capture_dir>"
```

The analyzer intentionally exits non-zero until the checklist is mechanically satisfied. A passing analyzer result is still not enough to promote the packet by itself; human review must confirm that the visible town action matches the logged sequence.
