#!/usr/bin/env python3
"""Full-3D T2 towns: are the building effects visible, or buried inside the Meshy bodies? (audit + snap).

    TOWN_FULL3D_FACTION=castle TOWN_FULL3D_CANDIDATE=<cand> python town_t2_fx_occlusion.py audit
    TOWN_FULL3D_FACTION=castle TOWN_FULL3D_CANDIDATE=<cand> python town_t2_fx_occlusion.py snap [--layers a,b]

The seed relief carried every effect (profile FX_LAYERS -> town_full3d_fx) at the relief's own depth. A T2 body
(Meshy geometry, painted front) sits at other depths, so an effect staged on the relief can end up behind the body's
front surface and never be drawn: the building "does not animate" although its effect is in the bundle.

audit  rasterises every Mesh_* bin of the build state "full" (all prefabs of STATES["full"] + the environment) from
       the rest camera and, per effect (particle group or Fx_ bin), compares the effect's camera depth with the nearest
       surface over the effect's own frame rect (catalog effectsReport rect, sprite px -> frame px). occludedShare =
       the share of that rect whose front surface is nearer than the effect by more than OCC_EPS of its depth.
       Writes <candidate>/work/fx_occlusion.json.
--state / --swap-in / --swap-out: the z-buffer (and the default layer set) is the environment plus that state's
       prefabs, with layers swapped in / out (an upgrade level no state lists, in place of the level it replaces).
snap   every particle group of the named layers (default: every group with occludedShare > SNAP_MIN) slides along its
       rest camera ray to OCC_FRONT of the rect's median front surface (prefab origin = camera, so the slide is a
       scale of the local position and of the group's scale: the rest frame is unchanged). Fx_ mesh bins (water
       curtains) are slid the same way: every vertex and the row's pos scaled by the slide (a
       uniform scale commutes with the row's rot and with a swing about the holder: rest projection unchanged).
Proof tier of its output: generated artifact (offline rasterisation of staged bins, not the Unity render).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import town_full3d_t2_paint as TP  # noqa: E402

OCC_EPS = 0.01      # a surface nearer than the effect by more than this share of its depth hides it
OCC_FRONT = 0.99    # snapped groups sit at this share of the front surface's depth
SNAP_MIN = 0.5      # default snap: groups whose rect is more than half hidden
SUP = TP.SUPER


def state_layers(state: str = "full", swap_in: list[str] | None = None) -> list[str]:
    """The layers of a build state plus any --swap-in layers (a level no state lists, e.g. an upgrade that replaces
    one of the state's own layers: give that layer in --swap-out)."""
    return list(SC.FP.STATES[state]) + [l for l in (swap_in or []) if l not in SC.FP.STATES[state]]


def full_zbuffer(sc, rows: dict, layers: list[str] | None = None) -> np.ndarray:
    keys = [S.PREFIX + "environment"] + [S.PREFIX + l for l in (layers or SC.FP.STATES["full"])]
    to_world = lambda v: sc.cpos + (np.asarray(v, np.float64) / sc.scale) @ sc.C.T
    Ps, Fs, off = [], [], 0
    for k in keys:
        for b in rows.get(k, {}).get("bins", []):
            if not b["name"].startswith("Mesh_") or b.get("pos") or b.get("rot"):
                continue
            v, _, _, subs = S.read_bin(S.STAGE / k / f"{b['name']}.bytes")
            Fs.append(np.concatenate(subs).reshape(-1, 3) + off)
            Ps.append(to_world(v))
            off += len(v)
    zb, _ = TP.zbuffer(sc.cam, np.concatenate(Ps), np.concatenate(Fs))
    return zb


def bin_centre(v, b: dict) -> np.ndarray:
    """Prefab-local centre of an Fx_ bin: its vertices through the row's rot (Unity quaternion x, y, z, w) and pos."""
    c = np.asarray(v, np.float64).mean(0)
    if b.get("rot"):
        x, y, z, w = [float(q) for q in b["rot"]]
        R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        c = R @ c
    return c + np.asarray(b.get("pos") or [0, 0, 0], np.float64)


def fx_rects(catalog: dict) -> dict:
    """effect name -> frame rect (x0, y0, x1, y1) in frame px."""
    lay = SC.layers()
    out = {}
    for lid, rep in (catalog.get("effectsReport") or {}).items():
        L = lay.get(lid)
        if L is None:
            continue
        for key, items in rep.items():
            if key == "placements" or not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict) or "rect" not in it or "name" not in it:
                    continue   # e.g. a spin row (rect, hub, radius) names no effect: measured without a rect
                x0, y0, x1, y1 = it["rect"]
                out[it["name"]] = [(L["x"] + x0) * SC.SCALE, (L["y"] + y0) * SC.SCALE,
                                   (L["x"] + x1) * SC.SCALE, (L["y"] + y1) * SC.SCALE]
                if isinstance(it.get("front"), dict):
                    out[it["front"]["name"]] = out[it["name"]]
    return out


def measure(sc, zb, name: str, local_pos, rect) -> dict:
    wp = sc.cpos + (np.asarray(local_pos, np.float64) / sc.scale) @ sc.C.T
    px, py, z = T.project(sc.cam, wp[None])
    z = float(z[0])
    if rect is None:
        r = 6
        rect = [px[0] - r, py[0] - r, px[0] + r, py[0] + r]
    x0, y0, x1, y1 = [int(round(c * SUP)) for c in rect]
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(max(x1, x0 + 1), zb.shape[1]), min(max(y1, y0 + 1), zb.shape[0])
    win = zb[y0:y1, x0:x1]
    fin = np.isfinite(win) & (win < 1e8)
    occ = fin & (win < z * (1 - OCC_EPS))
    front = float(np.median(win[fin])) if fin.any() else float("nan")
    return {"name": name, "fxDepth": round(z, 2), "frontMedian": round(front, 2),
            "occludedShare": round(float(occ.sum() / max(win.size, 1)), 3),
            "screen": [round(float(px[0]), 1), round(float(py[0]), 1)], "rectFrame": [round(c, 1) for c in rect]}


def audit(write: bool = True, layers: list[str] | None = None) -> dict:
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    cat = json.loads((S.OUT / "catalog.json").read_text(encoding="utf-8"))
    rects = fx_rects(cat)
    lays = layers or list(SC.FP.STATES["full"])
    zb = full_zbuffer(sc, rows, lays)
    out = {"faction": SC.FP.FRACTION, "candidate": S.CANDIDATE, "occEps": OCC_EPS, "zbufferLayers": lays, "layers": {}}
    for lid in lays:
        pk = S.PREFIX + lid
        items = []
        for q in rows.get(pk, {}).get("particles", []):
            items.append({**measure(sc, zb, q["name"], q["pos"], rects.get(q["name"])), "type": "particles"})
        for b in rows.get(pk, {}).get("bins", []):
            if b["name"].startswith("Fx_"):
                v, _, _, _ = S.read_bin(S.STAGE / pk / f"{b['name']}.bytes")
                c = bin_centre(v, b)
                items.append({**measure(sc, zb, b["name"], c, rects.get(b["name"])), "type": b.get("kind")})
        if items:
            out["layers"][lid] = items
    if write:
        (S.WORK / "fx_occlusion.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for lid, items in out["layers"].items():
        for it in items:
            flag = "HIDDEN" if it["occludedShare"] > SNAP_MIN else ("part" if it["occludedShare"] > 0.1 else "ok")
            print(f"{lid:14s} {it['name']:34s} {it['type']:10s} z={it['fxDepth']:7.2f} front={it['frontMedian']:7.2f} "
                  f"occ={it['occludedShare']:.2f} {flag}")
    return out


def snap(layers: list[str] | None, zlayers: list[str] | None = None) -> int:
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    cat = json.loads((S.OUT / "catalog.json").read_text(encoding="utf-8"))
    rects = fx_rects(cat)
    zlays = zlayers or list(SC.FP.STATES["full"])
    zb = full_zbuffer(sc, rows, zlays)
    rep = []
    for lid in zlays if layers is None else layers:
        pk = S.PREFIX + lid
        for q in rows.get(pk, {}).get("particles", []):
            m = measure(sc, zb, q["name"], q["pos"], rects.get(q["name"]))
            if layers is None and m["occludedShare"] <= SNAP_MIN:
                continue
            if not np.isfinite(m["frontMedian"]) or m["frontMedian"] >= m["fxDepth"]:
                continue
            r = m["frontMedian"] * OCC_FRONT / m["fxDepth"]
            q["pos"] = [float(x) * r for x in q["pos"]]
            q["scale"] = float(q["scale"]) * r
            rep.append({"layer": lid, "name": q["name"], "slide": round(r, 4), "was": m["occludedShare"]})
        for b in rows.get(pk, {}).get("bins", []):
            if not b["name"].startswith("Fx_"):
                continue
            path = S.STAGE / pk / f"{b['name']}.bytes"
            v, n, uv, subs = S.read_bin(path)
            c = bin_centre(v, b)
            m = measure(sc, zb, b["name"], c, rects.get(b["name"]))
            if layers is None and m["occludedShare"] <= SNAP_MIN:
                continue
            if not np.isfinite(m["frontMedian"]) or m["frontMedian"] >= m["fxDepth"]:
                continue
            r = m["frontMedian"] * OCC_FRONT / m["fxDepth"]
            S.write_bin(path, np.asarray(v, np.float64) * r, n, uv, subs)
            if b.get("pos"):
                b["pos"] = [float(x) * r for x in b["pos"]]
            rep.append({"layer": lid, "name": b["name"], "slide": round(r, 4), "was": m["occludedShare"], "bin": True})
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (S.WORK / "fx_snap_t2.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    for r in rep:
        print(json.dumps(r))
    print(f"snapped {len(rep)} group(s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["audit", "snap"])
    ap.add_argument("--layers", default="", help="snap: only these layers (default: every hidden group of the state)")
    ap.add_argument("--state", default="full", help="the build state whose prefabs form the z-buffer (default full)")
    ap.add_argument("--swap-in", default="", help="layers added to the state's z-buffer (a level no state lists)")
    ap.add_argument("--swap-out", default="", help="layers of the state dropped from the z-buffer (the one swapped in "
                                                  "replaces it)")
    a = ap.parse_args()
    if not S.CANDIDATE:
        raise SystemExit("set TOWN_FULL3D_CANDIDATE")
    split = lambda v: [x for x in v.split(",") if x]
    out = set(split(a.swap_out))
    zl = [l for l in state_layers(a.state, split(a.swap_in)) if l not in out]
    if a.cmd == "audit":
        audit(layers=zl)
        return 0
    return snap(split(a.layers) or None, zl)


if __name__ == "__main__":
    raise SystemExit(main())
