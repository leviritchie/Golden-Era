#!/usr/bin/env python3
"""Draw tracked joint overlays for all frames."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

TOOL = Path(__file__).resolve().parent
import sys

sys.path.insert(0, str(TOOL))
from seed_overlay import draw_joints  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_sprite_motion_track_g11"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keypoints", type=Path, default=OUT / "track" / "keypoints.json")
    ap.add_argument("--out-dir", type=Path, default=OUT / "preview")
    args = ap.parse_args()
    kpt = json.loads(args.keypoints.read_text(encoding="utf-8"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for fr in kpt["frames"]:
        fi = int(fr["frameIndex"])
        im = Image.open(fr["path"])
        # only draw visible
        joints = {k: v for k, v in fr["joints"].items() if v.get("visible", True)}
        out = draw_joints(im, joints, label=True)
        dest = args.out_dir / f"track_overlay_{fi:02d}.png"
        out.save(dest)
        print("wrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
