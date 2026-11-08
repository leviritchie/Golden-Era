#!/usr/bin/env python3
"""Wire AB/SoD carry policies with missionClipKeys + dedicated selectionIcon crops."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS = (
    ROOT
    / "experiments"
    / "campaign_port_poc"
    / "ab_sod_video_prologue_transcripts.v1.json"
)
CROPS = ROOT / "scenarios" / "ab_sod_campaigns" / "selection_icon_crops.v1.json"
HUB_INDEX = ROOT / "scenarios" / "ab_sod_campaigns" / "hub_index.v1.json"


def fail(msg: str) -> None:
    raise SystemExit(f"wire ab/sod video policies failed: {msg}")


def main() -> int:
    if not TRANSCRIPTS.is_file():
        fail(f"missing {TRANSCRIPTS}")
    if not CROPS.is_file():
        fail(f"missing {CROPS}")
    transcripts = json.loads(TRANSCRIPTS.read_text(encoding="utf-8"))
    crops = json.loads(CROPS.read_text(encoding="utf-8"))
    hub_index = json.loads(HUB_INDEX.read_text(encoding="utf-8"))
    mission_clip_keys = transcripts.get("missionClipKeys")
    if not isinstance(mission_clip_keys, dict) or not mission_clip_keys:
        fail("transcripts missing missionClipKeys")
    crop_rows = crops.get("crops")
    if not isinstance(crop_rows, dict) or not crop_rows:
        fail("crops catalog empty")

    for hub_row in hub_index["hubs"]:
        hub = hub_row["hub"]
        missions = list(hub_row["missions"])
        policy_path = (
            ROOT / "scenarios" / "ab_sod_campaigns" / f"continuity_carry_policy_{hub}.v1.json"
        )
        if not policy_path.is_file():
            fail(f"missing policy {policy_path}")
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        clip_map = {}
        for mission_id in missions:
            clip = mission_clip_keys.get(mission_id)
            if not clip:
                fail(f"{hub}: missing clip for mission {mission_id}")
            clip_map[mission_id] = clip
        crop = crop_rows.get(hub)
        if not isinstance(crop, dict):
            fail(f"missing crop for hub {hub}")
        still = crop.get("stillArtifact")
        if not isinstance(still, str) or not still:
            fail(f"{hub}: crop missing stillArtifact")
        hub_sid = hub_row["hubSid"]
        # Drop deferred-video non-goals; keep MapImage deferral.
        non_goals = [
            g
            for g in (policy.get("nonGoalsForThisMilestone") or [])
            if "PlayVideo" not in str(g) and "video" not in str(g).lower()
        ]
        if "Dedicated AB/SoD MapImage bake" not in non_goals:
            non_goals.append("Dedicated AB/SoD MapImage bake")
        policy["nonGoalsForThisMilestone"] = non_goals
        if "campaign" in policy and isinstance(policy["campaign"], dict):
            note = policy["campaign"].get("hubSidNote")
            if isinstance(note, str) and "video" in note.lower():
                policy["campaign"]["hubSidNote"] = (
                    "AB/SoD StoryHub: dedicated selection stills from hub strips; "
                    "MapImage may still reuse RoE BG stand-ins."
                )
        policy["videoContract"] = {
            "status": "mission_clips_wired_hub_still_only",
            "hubFirstShowPlayVideo": False,
            "hubFirstShowClipKey": None,
            "hubFirstShowOmitReason": (
                "RoE parity: hub hover strip is selection-still only; "
                "mission pins PlayVideo when composed MP4 meets contract."
            ),
            "requireComposedAudio": True,
            "subtitleMode": "softsub_sidecar_and_lockit",
            "minAcceptWidth": 1280,
            "minAcceptHeight": 720,
            "targetCanvas": "2560x1080",
            "requiredMp4RelativeToStreamingAssets": None,
            "selectionIcon": {
                "storyHubField": "mainIconSid",
                "iconSid": "main_icon",
                "coreMember": f"campaigns/{hub_sid}/icons/main_icon.png",
                "nativeSize": [378, 693],
                "stillArtifact": still,
                "composePolicy": crops.get(
                    "composePolicy", "letterbox_trim_then_vertical_focus"
                ),
                "focusX": float(crop["focusX"]),
                "focusY": float(crop["focusY"]),
                "cropReason": crop.get("reason") or f"Curated {hub} hub-strip crop",
                "cropsCatalog": "scenarios/ab_sod_campaigns/selection_icon_crops.v1.json",
            },
            "clipsInfoMember": "DB/clips_info.json",
            "missionClipKeys": clip_map,
            "actionOrder": (
                "PlayVideo (when composed MP4 ready) then OpenMissionsPrologue "
                "on each mission pin; hub firstShowActions stay empty"
            ),
            "failClosed": (
                f"{hub} hub firstShowActions must stay empty "
                "(hubFirstShowPlayVideo=false). Mission PlayVideo requires "
                "StreamingAssets/video/{{clip}}.mp4 + softsub sidecar meeting "
                "compose contract; otherwise omit PlayVideo and keep prologue."
            ),
        }
        policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
        print(f"wired {policy_path.name}: {len(clip_map)} clips, still={still}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
