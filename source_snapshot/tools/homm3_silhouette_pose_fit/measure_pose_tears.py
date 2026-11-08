#!/usr/bin/env python3
"""Quantify welded-surface tearing: bind pose vs. an animation clip's frame-0 pose.

Unlike measure_rigid_gaps.py (nearest DIFFERENT-owner vertex — large for rigid
patches even when the weld stays closed), this measures the nearest vertex
regardless of owner. On a welded mesh a large positive delta means the surface
actually tore open at a seam; rigid plates that move as blocks keep their
geometric NN distances small.

Usage:
  py -3 measure_pose_tears.py --master <master.glb> --clip <clip.glb> --frame 0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from inspect_glb_skinning import _read_glb
from measure_rigid_gaps import _clip_frame_rotations, _skin


def _geo_nn(pos: np.ndarray) -> np.ndarray:
    n = len(pos)
    best = np.full(n, np.inf)
    for i in range(n):
        d = np.linalg.norm(pos - pos[i], axis=1)
        d[i] = np.inf
        best[i] = d.min()
    return best


def measure(master_path: Path, clip_path: Path | None, frame: float | None) -> dict:
    doc = _read_glb(master_path)
    rest_pos, rest_skin, _ = _skin(doc, doc["bin"], {})
    rest_nn = _geo_nn(rest_skin)
    pose_skin = rest_skin
    pose_rotations = {}
    if clip_path is not None:
        cdoc = _read_glb(clip_path)
        pose_rotations = _clip_frame_rotations(cdoc, cdoc["bin"], frame if frame is not None else 0.0)
        _, pose_skin, _ = _skin(doc, doc["bin"], pose_rotations)
    pose_nn = _geo_nn(pose_skin)
    delta = pose_nn - rest_nn
    return {
        "rest": {
            "nnP99": round(float(np.percentile(rest_nn, 99)), 4),
            "nnMax": round(float(rest_nn.max()), 4),
        },
        "pose": {
            "nnP99": round(float(np.percentile(pose_nn, 99)), 4),
            "nnMax": round(float(pose_nn.max()), 4),
        },
        "tearDeltaP99": round(float(np.percentile(delta, 99)), 4),
        "tearDeltaMax": round(float(delta.max()), 4),
        "vertsTearOver2cm": int((delta > 0.02).sum()),
        "vertsTearOver5cm": int((delta > 0.05).sum()),
        "poseRotationCount": len(pose_rotations),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", required=True, type=Path)
    parser.add_argument("--clip", type=Path)
    parser.add_argument("--frame", type=float)
    args = parser.parse_args()
    report = measure(args.master.resolve(), args.clip.resolve() if args.clip else None, args.frame)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
