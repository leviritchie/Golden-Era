#!/usr/bin/env python3
"""Fill short track-lost gaps in keypoints by linear interpolation (explicit).

Fail-closed if a joint has no visible anchors in the clip. Does not invent
motion beyond interpolating between known marks — LLM should still re-author
long gaps. Writes a sibling ``keypoints_gap_repaired.json`` + report.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _visible(spec: dict) -> bool:
    if spec.get("visible") is False:
        return False
    if float(spec.get("score", 1.0) or 0.0) <= 0.0 and spec.get("method") == "lost":
        return False
    return True


def repair(kpt: dict) -> tuple[dict, dict]:
    frames = sorted(kpt["frames"], key=lambda f: int(f["frameIndex"]))
    if not frames:
        raise RuntimeError("no frames")
    names = sorted(frames[0]["joints"].keys())
    repaired = 0
    per_joint: dict[str, int] = {n: 0 for n in names}

    # Collect series
    series: dict[str, list[dict | None]] = {n: [] for n in names}
    for fr in frames:
        for n in names:
            spec = fr["joints"].get(n)
            if spec is None or not _visible(spec):
                series[n].append(None)
            else:
                series[n].append(spec)

    for n in names:
        vals = series[n]
        known = [i for i, v in enumerate(vals) if v is not None]
        if not known:
            raise RuntimeError(f"fail-closed: joint {n} never visible in clip")
        for i, v in enumerate(vals):
            if v is not None:
                continue
            # nearest left/right
            left = max((k for k in known if k < i), default=None)
            right = min((k for k in known if k > i), default=None)
            if left is None:
                src = vals[right]
                assert src is not None and right is not None
                new = dict(src)
                new["method"] = "gap_hold_start"
            elif right is None:
                src = vals[left]
                assert src is not None
                new = dict(src)
                new["method"] = "gap_hold_end"
            else:
                a = vals[left]
                b = vals[right]
                assert a is not None and b is not None
                t = (i - left) / float(right - left)
                new = {
                    "x": float(a["x"]) * (1.0 - t) + float(b["x"]) * t,
                    "y": float(a["y"]) * (1.0 - t) + float(b["y"]) * t,
                    "score": 1.0,
                    "visible": True,
                    "dx": 0.0,
                    "dy": 0.0,
                    "method": "gap_interp",
                    "gapFrom": left,
                    "gapTo": right,
                }
            vals[i] = new
            repaired += 1
            per_joint[n] += 1

    out_frames = []
    for fi, fr in enumerate(frames):
        joints = {}
        for n in names:
            joints[n] = series[n][fi]
        nf = dict(fr)
        nf["joints"] = joints
        out_frames.append(nf)

    out = dict(kpt)
    out["frames"] = out_frames
    out["gapRepair"] = {
        "repairedSamples": repaired,
        "perJoint": {k: v for k, v in per_joint.items() if v},
        "proof": "generated — gap interp of track-lost landmarks; prefer LLM re-author for long gaps",
    }
    return out, out["gapRepair"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keypoints", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    kpt = json.loads(args.keypoints.read_text(encoding="utf-8"))
    fixed, report = repair(kpt)
    out = args.out or args.keypoints.with_name("keypoints_gap_repaired.json")
    out.write_text(json.dumps(fixed, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out).replace("\\", "/"), **report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
