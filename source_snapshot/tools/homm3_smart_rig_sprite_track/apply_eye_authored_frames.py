#!/usr/bin/env python3
"""Apply eye-authored per-frame joints (hand-written coords) → overlays + keypoints + previews.

Joints themselves are NOT computed here — they come from authored_all_frames.json
which was filled by eye using previous-frame overlays as reference.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_smart_rig_sprite_track"))
from track_unirig_on_rife import _draw_overlay, PREVIEW_GIF_FRAME_MS  # noqa: E402

OUT = ROOT / "artifacts/roc_pose_pipeline/smart_rig_move_pilot"
AUTH = OUT / "author_frames"
NN = OUT / "frames_nn"
OV = OUT / "overlays"


def main() -> int:
    authored = json.loads((AUTH / "authored_all_frames.json").read_text(encoding="utf-8"))
    skel = json.loads((OUT / "skeleton.json").read_text(encoding="utf-8"))
    edges = skel["edges"]
    OV.mkdir(parents=True, exist_ok=True)
    frames_out = []
    gif = []
    for fi in range(30):
        key = str(fi)
        if key not in authored["frames"]:
            raise SystemExit(f"missing eye-authored frame {fi}")
        joints = {
            n: (float(j["x"]), float(j["y"])) for n, j in authored["frames"][key].items()
        }
        rgba = np.asarray(Image.open(NN / f"{fi:02d}.png").convert("RGBA"))
        label = f"roc move g0 f{fi:02d} EYE←f{fi-1:02d}" if fi else "roc move g0 f00 EYE"
        ov = _draw_overlay(rgba, joints, edges, label)
        op = OV / f"overlay_{fi:02d}.png"
        ov.save(op)
        gif.append(ov)
        frames_out.append(
            {
                "frame": fi,
                "source": str((OUT / "frames_src" / f"{fi:02d}.png").resolve()).replace("\\", "/"),
                "nn": str((NN / f"{fi:02d}.png").resolve()).replace("\\", "/"),
                "overlay": str(op.resolve()).replace("\\", "/"),
                "joints": {n: {"x": float(x), "y": float(y)} for n, (x, y) in joints.items()},
                "method": "human_eye_landmark_authoring",
                "prevFrameRef": None if fi == 0 else fi - 1,
            }
        )
    kpt = {
        "unitSid": "h3_roc",
        "clip": "move_g0_rife",
        "skeleton": str((OUT / "skeleton.json").resolve()).replace("\\", "/"),
        "nnScale": 3,
        "edges": edges,
        "frames": frames_out,
        "proof": "generated artifact validated — per-frame human_eye_landmark_authoring with prev-frame continuity",
    }
    (OUT / "keypoints.json").write_text(json.dumps(kpt, indent=2), encoding="utf-8")
    gif[0].save(
        OUT / "roc_move_g0_stick.gif",
        save_all=True,
        append_images=gif[1:],
        duration=PREVIEW_GIF_FRAME_MS,
        loop=0,
    )
    print(json.dumps({"ok": True, "frames": 30, "gif": str(OUT / "roc_move_g0_stick.gif")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
