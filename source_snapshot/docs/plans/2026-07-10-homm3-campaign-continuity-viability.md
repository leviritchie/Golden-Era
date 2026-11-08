# HoMM3 Campaign Continuity Viability

Status: native StoryHub continuity architecture implemented for the campaign hubs configured by the current worktree. Generated and installed campaign files have been observed, but the installed payload is not currently readiness-validated: the continuity and map-load preflight contracts fail against the active Golden Era `Core.zip` on missing city-construction and localization rows. Runtime hero carry, difficulty effects, video presentation, and full mission handoff remain unvalidated.

## Decision

Use Olden's native StoryHub, mission variants, and CampaignInfo model. Do not build a parallel mission sequencer and do not mutate `Plugin.CreateHomecomingPlayableShellCampaignInfo`, which remains a separate single-map shell.

The current mission inventory is owned by:

- `scenarios/roe_castle_campaign/batch_manifest.json`
- `scenarios/roe_castle_campaign/continuity_carry_policy.v1.json`
- `scenarios/roe_castle_campaign/continuity_carry_policy_good2.v1.json`
- `tools/install_roe_castle_continuity_weave.py` `HUB_CONFIGS`

Do not duplicate a fixed mission count here. The current worktree configures Good1 and Good2 and uses `raw_translation` map SIDs for StoryHub delivery.

## Implemented Static Contract

`experiments/campaign_port_poc/build_roe_castle_continuity_weave.py` supports `--hub good1` and `--hub good2` and emits native-shaped campaign members under `campaigns/<hubSid>/`. Each StoryHub sets `transferHeroProgressFromSession: true`, exposes four HoMM3 difficulty choices, keeps Impossible locked, and uses one mission variant while starting bonuses remain fail-closed.

`tools/install_roe_castle_continuity_weave.py` installs configured maps only under `HeroesOldenEra_Data/StreamingAssets/maps/Story_maps/` and removes/rejects same-SID copies under `maps/`. It merges Core overlays and localization catalogs by identity rather than whole-file replacement.

These are source/static and installer contracts. They do not prove that Olden writes session heroes back into the hub save, selects the strongest N heroes with HoMM3 semantics, or applies all difficulty effects as intended.

## Video And Selection Art

The hub introduction and mission cutscenes are different surfaces:

- `Cgood1` is selection art input. Good1 intentionally keeps hub `firstShowActions` free of `PlayVideo` and uses a generated still as `main_icon.png`.
- Mission pins may queue `PlayVideo` before `OpenMissionsPrologue` when the corresponding composed MP4 passes the canvas, duration, audio, and sidecar contract.
- Good1 and Good2 clip keys and recipes live in the carry policies and video composition modules. Installed files and `clips_info` registration are payload evidence only; playback, aspect, subtitles, sequencing, and skip behavior remain runtime-unvalidated.

## Carry And Bonuses

The minimum intended carry contract is encoded in the campaign policies. `transferHeroProgressFromSession: true` is necessary but not sufficient proof of HoMM3 carry fidelity.

Starting-bonus selection remains intentionally unimplemented. `heroesArmies` replaces map armies rather than adding a bonus, and no validated StoryHub grant action exists for artifact or war-machine bonuses. Do not expose multiple mission variants until an additive, validated grant path exists.

## Proof Matrix

| Surface | Current proof |
| --- | --- |
| StoryHub/campaign JSON shape | source/static + generated artifact |
| Story_maps-only install policy | source/static + installer contract |
| Campaign/video files present in install | installed readback observed |
| Installed campaign readiness | currently failing validators; not proven |
| Session-to-hub hero writeback | runtime unvalidated |
| Strongest-N and cap semantics | runtime unvalidated |
| Difficulty selection/effects | runtime unvalidated |
| Video playback and presentation | runtime unvalidated |
| End-to-end mission completion/handoff | runtime unvalidated |

## Readiness Gates

```powershell
$env:PYTHONUTF8 = '1'
python tools/validate_map_load_preflight_contract.py --repo-root .
python tools/validate_roe_castle_campaign_continuity_contract.py --repo-root .
```

Both must pass against the same active install before this document may claim deployed-payload validation. After that, the remaining proof is an explicit StoryHub runtime pass covering mission entry, completion, hero carry, difficulty choice, and video presentation.
