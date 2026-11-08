"""Closing walls at the rest pose: edge-on offline, and only on their own lines in the Unity rest render.

A closing wall (stronghold_full3d_buildings.closing_walls) lies in the plane of its near edge's two camera rays, so at
the rest camera it projects to the near edge's line and covers no area. Two checks hold that:

1. Offline, in the stage (`rest_area_or_exit`, called by stronghold_full3d_solids.build_solid): every wall triangle's
   projected area at the painting camera is below WALL_REST_AREA_MAX_PX2 frame px^2. Generated artifact.
2. Unity rest render (`check`, CLI below, run after `render`): a pixel that differs between a candidate and a twin
   whose buildings differ only in their closing walls (or only in the walls' texels) lies within PAD_PX of a wall's
   projected near edge at the framed rest camera. A wall does touch pixels there: the rasteriser leaves crack pixels
   along the step's projected edge between the near sheet and the sunk triangle, and the edge-on wall fills them
   (Cove cv_v8 -> cv_v9: 6460 px at 1080, all on step edges). Anything off those lines is a wall that is not edge-on
   at the game's rest camera. Unity editor render (generated artifact), not an in-game capture.

The stage writes each building's wall near edges in the prefab frame (camera at the origin) to
work/closing_walls.npz ({layer id: (k, 2, 3)}).

    python town_full3d_wall_rest.py --faction F --before <candidate> --after <candidate>
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

WALL_REST_AREA_MAX_PX2 = 1e-6
PAD_PX = 1
DIFF_LEVELS = 2          # a render diff above this many 8-bit levels counts (same-candidate re-render noise is 1)
RENDERS = {"full3d_full.png": (1920, 1080), "full3d_full_4k.png": (3840, 2160)}
ASPECT = 16 / 9


def rest_area_px2(Pw: np.ndarray, tris: np.ndarray, project) -> np.ndarray:
    """Projected area (frame px^2) of each wall triangle; project(P) -> (px, py, z) at the rest camera."""
    px, py, z = project(np.asarray(Pw, np.float64))
    if (np.asarray(z) <= 0).any():
        raise SystemExit("closing walls: a wall vertex is behind the rest camera")
    q = np.stack([px, py], 1)[np.asarray(tris)]
    d1, d2 = q[:, 1] - q[:, 0], q[:, 2] - q[:, 0]
    return 0.5 * np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0])


def rest_area_or_exit(lid: str, Pw: np.ndarray, tris: np.ndarray, project) -> float:
    a = rest_area_px2(Pw, tris, project)
    amax = float(a.max()) if len(a) else 0.0
    if amax >= WALL_REST_AREA_MAX_PX2:
        raise SystemExit(f"{lid}: a closing wall covers {amax:.3g} px^2 at the rest camera "
                         f"(max {WALL_REST_AREA_MAX_PX2}); walls must be edge-on at rest")
    return amax


def framed_rest(catalog: dict) -> dict:
    """The Unity rest camera in the prefab frame from the catalog's referenceCamera.framing (origin, aim rotation,
    zoomed fov); no framing = the native rest camera."""
    from scipy.spatial.transform import Rotation
    import town_full3d_framing as FR
    blk = (catalog.get("referenceCamera") or {}).get("framing")
    if blk:
        Di = Rotation.from_quat(blk["aimRotation"]).as_matrix().T
        fov = float(blk["fov"])
    else:
        Di, fov = np.eye(3), FR.REST_FOV
    return {"fwd": Di @ [0, 0, 1.0], "up": Di @ [0, 1.0, 0], "right": Di @ [1.0, 0, 0], "fov": fov}


def line_mask(edges: np.ndarray, cam: dict, w: int, h: int, pad: int = PAD_PX) -> np.ndarray:
    """Pixels within `pad` of any wall near edge (edges (k, 2, 3), prefab frame) projected at cam (origin)."""
    import cv2
    R = np.stack([cam["right"], cam["up"], cam["fwd"]], 0)
    q = np.asarray(edges, np.float64).reshape(-1, 3) @ R.T
    ty = math.tan(math.radians(cam["fov"]) / 2)
    x = (0.5 + 0.5 * q[:, 0] / (q[:, 2] * ty * ASPECT)) * w
    y = (0.5 - 0.5 * q[:, 1] / (q[:, 2] * ty)) * h
    m = np.zeros((h, w), np.uint8)
    sh = 4
    pts = np.round(np.stack([x, y], 1) * (1 << sh)).astype(np.int64).reshape(-1, 2, 2)
    ok = (q[:, 2].reshape(-1, 2) > 0).all(1)
    for a, b in pts[ok]:
        cv2.line(m, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), 1, 1, cv2.LINE_8, sh)
    if pad:
        m = cv2.dilate(m, np.ones((2 * pad + 1, 2 * pad + 1), np.uint8))
    return m.astype(bool)


def load_edges(cand: Path) -> np.ndarray:
    f = cand / "work" / "closing_walls.npz"
    if not f.is_file():
        raise SystemExit(f"{f}: missing (stage the candidate with the closing-wall export)")
    z = np.load(f)
    return np.concatenate([z[k] for k in z.files]) if z.files else np.zeros((0, 2, 3))


def check(before: Path, after: Path) -> dict:
    from PIL import Image
    cat = json.loads((after / "bundle" / "catalog.json").read_text(encoding="utf-8"))
    cam = framed_rest(cat)
    edges = [load_edges(after)]
    if (before / "work" / "closing_walls.npz").is_file():
        edges.append(load_edges(before))
    E = np.concatenate(edges)
    out = {"before": before.name, "after": after.name, "walls": int(len(E)), "padPx": PAD_PX,
           "diffLevels": DIFF_LEVELS, "renders": {}}
    for name, (w, h) in RENDERS.items():
        A = np.asarray(Image.open(before / "renders" / name).convert("RGB")).astype(np.int16)
        B = np.asarray(Image.open(after / "renders" / name).convert("RGB")).astype(np.int16)
        if A.shape != (h, w, 3) or B.shape != (h, w, 3):
            raise SystemExit(f"{name}: expected {w}x{h}, got {A.shape} / {B.shape}")
        d = np.abs(A - B).max(-1) > DIFF_LEVELS
        m = line_mask(E, cam, w, h)
        off = d & ~m
        ys, xs = np.nonzero(off)
        out["renders"][name] = {"diffPx": int(d.sum()), "onWallLines": int((d & m).sum()), "offWallLines": int(off.sum()),
                                "offSample": [[int(x), int(y)] for x, y in zip(xs[:10], ys[:10])]}
    out["ok"] = all(r["offWallLines"] == 0 for r in out["renders"].values())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faction", required=True)
    ap.add_argument("--before", required=True, help="candidate name: the twin without (or with other) wall texels")
    ap.add_argument("--after", required=True)
    a = ap.parse_args()
    import os
    os.environ["TOWN_FULL3D_FACTION"] = a.faction
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import stronghold_full3d_common as SC
    root = SC.DATA / "candidates"
    rep = check(root / a.before, root / a.after)
    print(json.dumps(rep))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
