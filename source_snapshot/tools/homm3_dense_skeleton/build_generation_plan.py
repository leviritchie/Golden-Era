#!/usr/bin/env python3
"""
Emit the ordered GenerateImage plan for dense overlays.

Each job attaches:
  1. NN-upscaled DEF sprite for this frame (pose/identity lock)
  2. Previous generated overlay (art + neon skeleton + joint labels), when one exists

Every prompt requires named joint labels (exact spellings from JOINT_ORDER).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from constants import JOINT_ORDER, MANIFEST, OUT, SRC_UPSCALED  # noqa: E402
from prompt_contract import build_overlay_prompt  # noqa: E402

ANGLE_ORDER = ["iso", "side", "front", "rear_q"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--sprite-dir", type=Path, default=SRC_UPSCALED)
    ap.add_argument("--overlays", type=Path, default=OUT / "overlays")
    ap.add_argument("--out", type=Path, default=OUT / "generation_plan.json")
    args = ap.parse_args()
    man = json.loads(args.manifest.read_text(encoding="utf-8"))
    frames = list(man.get("frames") or list(range(8)))
    angles = man["angles"]

    jobs = []
    prev_overlay: str | None = None
    for fi in frames:
        sprite = args.sprite_dir / f"frame_{int(fi):02d}.png"
        if not sprite.is_file():
            raise SystemExit(f"missing sprite ref {sprite} — run upscale_sprites_nn.py first")
        for angle in ANGLE_ORDER:
            n = int(angles[angle]["samplesFull"])
            cam = angles[angle]["promptCamera"]
            for s in range(n):
                dest = args.overlays / f"f{int(fi):02d}" / angle / f"sample_{s:02d}.png"
                refs = [str(sprite).replace("\\", "/")]
                if prev_overlay:
                    refs.append(prev_overlay)
                has_prev = prev_overlay is not None
                jobs.append(
                    {
                        "frameIndex": int(fi),
                        "angle": angle,
                        "sample": s,
                        "dest": str(dest).replace("\\", "/"),
                        "reference_image_paths": refs,
                        "promptCamera": cam,
                        "prompt": build_overlay_prompt(camera=cam, has_prev_overlay=has_prev),
                        "jointLabelsRequired": list(JOINT_ORDER),
                        "filenameHint": f"dense_f{int(fi):02d}_{angle}_s{s:02d}.png",
                        "chainIndex": len(jobs),
                        "hasPrevOverlay": has_prev,
                    }
                )
                prev_overlay = str(dest).replace("\\", "/")

    report = {
        "ok": True,
        "jobCount": len(jobs),
        "spriteDir": str(args.sprite_dir).replace("\\", "/"),
        "chainRule": (
            "each job refs NN-upscaled sprite + previous overlay "
            "(art + neon skeleton + joint name labels) when present"
        ),
        "jointLabelsRequired": list(JOINT_ORDER),
        "angleOrder": ANGLE_ORDER,
        "minSpriteEdgePx": 900,
        "jobs": jobs,
        "proof": "generated artifact validated — generation plan only; overlays not claimed until written",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "jobCount": len(jobs),
                "out": str(args.out),
                "jointLabelsRequired": list(JOINT_ORDER),
                "promptCharsJob0": len(jobs[0]["prompt"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
