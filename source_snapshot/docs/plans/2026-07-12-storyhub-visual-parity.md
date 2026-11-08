# RoE Castle StoryHub Visual And Video Parity

Status: source/static and generated-artifact support exists for campaign node placement, selection stills, clip registration, per-mission video actions, and a per-campaign MapImage background bridge. Campaign icons and MP4s have been observed in installed payloads, but the broader installed campaign readiness validators currently fail. Runtime background presentation, icon presentation, playback, subtitles, and mission-pin sequencing remain unvalidated.

## Capability Boundary

| Surface | Native data support | Current state |
| --- | --- | --- |
| Mission node positions | `storyHub.json` `posX`/`posY`/`posZ` | generated from HoMM3 campaign-region anchors |
| Campaign selection/save icons | `mainIconSid`/`hubIconSid` and campaign icon members | curated vertical-focus crops from HoMM3 `C*` stills into native 378×693 (`selection_icon_crops.v1.json`); generated and observed installed for Good1 |
| Hub canvas map (`NewMap`) | no StoryHub JSON field; scene `MapCanvas` / `MapImage` + `MapImage (1)` | runtime bridge: baked `G*_BG_1368x1600.png` (crop source black UI panel at x≥456, ×3, height crop) assigned per hub SID; **runtime visual proof pending** for the cropped revision |
| Per-mission node art | no node icon SID; native state assets | not implemented |
| Mission cutscene | node `interactionActions` serial queue | optional `PlayVideo` then `OpenMissionsPrologue` |

HoMM3 hub maps are static `{prefix}_BG` PCX images (e.g. `G1_BG`, `G2_BG` at 800×600), not `Cgood*` video strips and not `BhScrollImage` smoke overlays. Olden serializes a shared `NewMap` (3840×1600) into the StoryHub scene; replacement must be per-campaign at runtime.

Bake pipeline (`tools/bake_homm3_storyhub_map_backgrounds.py`): crop away the source right-hand black UI panel (x≥456) → nearest-neighbor ×3 → center-crop height → `homm3_storyhub_maps/G*_BG_1368x1600.png`. Runtime hook: `Homm3StoryHubMapBackgroundHook` after `BhStoryHub.Init` stretches that sprite into the native MapImage rect.

## Current Good1 Video Design

`Cgood1` is a hover/selection clip, not a full hub introduction. The Good1 policy therefore keeps `firstShowActions` empty and generates a native-size `main_icon.png` still instead of playing `Cgood1` on hub entry.

Each Good1 mission pin has its own clip key (`Good1a`, `Good1b`, `Good1c`). The generator queues `PlayVideo` before `OpenMissionsPrologue` only when the composed MP4 satisfies the native canvas, audio, duration, and sidecar checks. Good2 follows the same policy through its own carry configuration.

Missing, undersized, silent, or incomplete media fails closed by omitting `PlayVideo`; it is not reported as wired success.

## Assets And Ownership

- StoryHub layout and action generation: `experiments/campaign_port_poc/build_roe_castle_continuity_weave.py`
- Clip probing/composition: `campaign_video_clip.py`, `campaign_video_compose.py`, and `tools/bake_roe_castle_campaign_videos.py`
- Hub map bake: `experiments/campaign_port_poc/storyhub_map_background.py`, `tools/bake_homm3_storyhub_map_backgrounds.py`
- Campaign policies: `scenarios/roe_castle_campaign/continuity_carry_policy*.json`
- Extracted campaign visuals: `artifacts/campaign_port_poc/roe_castle_campaign/storyhub_visual/`
- Runtime clip registration/install: `tools/register_roe_castle_campaign_video_clip.py` and the continuity installer

## Remaining Runtime Proof

1. Open each campaign and inspect selection still size/crop.
2. Verify mission pin layout and state transitions.
3. Play every mission clip and verify audio, subtitles, aspect, completion callback, and skip behavior.
4. Confirm the mission prologue opens only after the video action completes.
5. Open Good1/Good2 StoryHub and confirm both MapImages show the baked `G*_BG` canvas; stock campaigns must keep `NewMap`.

Installed file presence is not runtime playback proof.
