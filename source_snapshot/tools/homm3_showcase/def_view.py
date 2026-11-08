"""DEF-view camera per unit for the final showcase reel: the board's SpriteCam, turned about world up so the mesh
faces the way the HoMM3 DEF does.

The build_unit.py SpriteCam is one generic camera and does not see every rig from the DEF's side (README "DEF view
(--view-yaw)": the griffin line needs about -40 deg; the archer's board sprite row stands front-on while the DEF is
turned three-quarters to the right). This fits that view yaw per unit, in the board's --view-yaw convention
(spritecam.view_yawed), on a handful of DEF frames across clips:

    score(yaw) = mean over frames of [ IoU(DEF body, render) - 0.5 * colour MAE on the overlap ]

each frame after the board's own 2D similarity fit (area + centroid, board.similarity_fit). The yaw is searched within
+-90 deg of the SpriteCam (5 deg grid, then 1 deg refine), which keeps the front of the body toward the viewer like
every HoMM3 battle sprite (a back view can mirror a front silhouette). The DEF pixel <-> world mapping is the
similarity fit of Idle frame 0 at the chosen yaw (board --align idle), so DEF and mesh match in size and placement.

    python tools/homm3_showcase/def_view.py <lab> [<lab> ...] [--sheet <png>] [--refit]

Cache: V:/olden_port_work/showcase/final_reel/views/<lab>.json (keyed by the GLB sha256 + sprite camera).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_authenticity"))
from sources import def_reference, shipped_glb, unit_ids  # noqa: E402
from spritecam import sprite_camera, view_yawed  # noqa: E402

VIEWS = Path("V:/olden_port_work/showcase/final_reel/views")
DEF_ALPHA_BODY = 200
SCHEMA = "homm3_showcase_def_view.v1"
FRONT_WINDOW = (5.0, 75.0)        # body front vs screen-right, degrees toward the viewer


def _mask_stats(m):
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    return {"area": len(xs), "c": (float(xs.mean()) + 0.5, float(ys.mean()) + 0.5)}


class Fitter:
    def __init__(self, lab: str):
        import torch
        import raster as R
        from gltf_scene import Scene
        self.R, self.torch = R, torch
        self.lab, self.src = unit_ids(lab)
        self.sel = shipped_glb(self.lab, self.src)
        if self.sel["mode"] != "shipped":
            raise RuntimeError(f"{lab}: no pinned shipped GLB ({self.sel['notes']})")
        self.ref = def_reference(self.src)
        row = self.sel.get("row") or {}
        self.scene = Scene(self.sel["path"], body_name=self.src, skip_meshes=tuple(row.get("deferMeshes") or {}))
        im = Image.open(self.sel["albedo"]).convert("RGBA")
        if max(im.size) > 1024:
            s = 1024 / max(im.size)
            im = im.resize((round(im.size[0] * s), round(im.size[1] * s)), Image.LANCZOS)
        self.dev = R.resolve_device("cuda")
        self.mesh = R.DeviceMesh(self.scene, self.dev, np.asarray(im, np.float32) / 255.0)
        self.deyaw = (self.scene.extras.get("homm3DefRetargetDeliveryDeyaw") or {}).get("yawDeg")
        self.sc0 = sprite_camera(self.ref["spritecam"], self.deyaw)
        self.defs = {c["clip"]: c for c in self.ref["clips"] if c["clip"] in self.scene.anims}
        self.samples = self._samples()

    def key(self) -> str:
        h = hashlib.sha256(json.dumps(self.ref["spritecam"], sort_keys=True).encode()).hexdigest()[:16]
        return f"{self.sel['sha256']}:{h}:{self.deyaw}"

    def _time(self, clip: str, i: int) -> float:
        """board.py timing(): DEF frame i at start + i * duration / ((n - 1) + loop transition keys)."""
        c = self.defs[clip]
        rng = self.scene.clip_range(clip)
        n = len(c["frames"])
        tk = int((c.get("loop") or {}).get("transitionKeys", 0))
        m = (n - 1) + ((1 + tk) if c.get("loop") else 0)
        return rng["start"] + i * (rng["duration"] / m if m > 0 else 1 / 12)

    def _samples(self):
        out = []
        want = [("Unit_Idle", 0.0), ("Unit_Move", 0.5), ("Unit_AttackFront", 0.5), ("Unit_Defence", 0.5),
                ("Unit_Mouseover", 0.5)]
        for clip, f in want:
            if clip not in self.defs:
                continue
            n = len(self.defs[clip]["frames"])
            i = min(n - 1, int(round(f * (n - 1))))
            im = np.asarray(Image.open(self.defs[clip]["frames"][i]).convert("RGBA"))
            Jm, mw = self.scene.pose(clip, np.array([self._time(clip, i)]))
            P, N = self.mesh.skin(Jm, mw)
            h2, w2 = im.shape[0] // 2, im.shape[1] // 2
            im2 = im[:h2 * 2:2, :w2 * 2:2]
            out.append({"clip": clip, "i": i, "def": im, "body": im[..., 3] >= DEF_ALPHA_BODY, "P": P, "N": N,
                        "def2": im2, "body2": im2[..., 3] >= DEF_ALPHA_BODY})
        if not out:
            first = next(iter(self.defs))
            raise RuntimeError(f"{self.lab}: no Idle/Move/Attack/Defence DEF clip in the GLB (first: {first})")
        return out

    def cam(self, yaw: float) -> dict:
        return view_yawed(self.sc0, yaw) if yaw else self.sc0

    def render(self, cam, s):
        return self.R.render(self.mesh, cam, s["P"], s["N"], ss=1).cpu().numpy()

    def fit_frame(self, cam, s, half=False):
        """board.similarity_fit (area + centroid) of the render onto the DEF body; returns the fitted camera."""
        rm = self.render(cam, s)[..., 3] >= 0.5
        a, b = _mask_stats(s["body2" if half else "body"]), _mask_stats(rm)
        if not a or not b:
            return None
        k = math.sqrt(a["area"] / b["area"])
        t = [a["c"][j] - k * b["c"][j] for j in range(2)]
        return dict(cam, cx=k * cam["cx"] + t[0], cy=k * cam["cy"] + t[1], scale=cam["scale"] * k)

    def score(self, yaw: float) -> float:
        """Scored at half the DEF canvas resolution (the yaw search renders ~50 yaws x 5 frames x 2)."""
        tot = []
        c = self.cam(yaw)
        c = dict(c, cx=c["cx"] / 2, cy=c["cy"] / 2, scale=c["scale"] / 2, W=c["W"] // 2, H=c["H"] // 2)
        for s in self.samples:
            fc = self.fit_frame(c, s, half=True)
            if fc is None:
                tot.append(0.0)
                continue
            img = self.render(fc, s)
            rm = img[..., 3] >= 0.5
            u = np.logical_or(rm, s["body2"]).sum()
            inter = np.logical_and(rm, s["body2"])
            iou = float(inter.sum() / u) if u else 0.0
            if inter.any():
                rgb = img[..., :3][inter] / np.maximum(img[..., 3:4][inter], 1e-4)
                mae = float(np.abs(rgb - s["def2"][..., :3][inter] / 255.0).mean())
            else:
                mae = 1.0
            tot.append(iou - 0.5 * mae)
        return float(np.mean(tot))

    def front_deg(self, yaw: float) -> float:
        """Angle of the body's front (glTF +Z, the delivery facing) toward the viewer: 0 = pure profile facing screen
        right, +90 = facing the camera, negative = turned away."""
        c = self.cam(yaw)
        z = np.array([0.0, 0.0, 1.0])
        return math.degrees(math.atan2(float(np.dot(z, -np.asarray(c["fwd"]))), float(np.dot(z, np.asarray(c["right"])))))

    def fit(self) -> dict:
        # HoMM3 battle sprites face screen right and turn toward the viewer; outside FRONT_WINDOW the silhouette fit
        # picked mirror/back views (medusa queen, vampire prince) or front-on ones (mummy) on 2026-10-12's sweep
        ok = lambda y: FRONT_WINDOW[0] <= self.front_deg(y) <= FRONT_WINDOW[1]  # noqa: E731
        grid = {y: self.score(y) for y in range(-180, 180, 5) if ok(y)}
        if not grid:
            raise RuntimeError(f"{self.lab}: no view yaw puts the body front inside {FRONT_WINDOW}")
        y0 = max(grid, key=grid.get)
        fine = {y: self.score(y) for y in range(y0 - 4, y0 + 5) if ok(y)}
        yaw = float(max(fine, key=fine.get))
        cam = self.cam(yaw)
        s0 = self.samples[0]
        fc = self.fit_frame(cam, s0)
        return {"schema": SCHEMA, "lab": self.lab, "key": self.key(), "viewYawDeg": yaw, "deyawDeg": self.deyaw,
                "score": round(max(fine.values()), 4), "scoreAtSpriteCam": round(self.score(0), 4),
                "frontDeg": round(self.front_deg(yaw), 1), "frontWindow": list(FRONT_WINDOW),
                "grid": {str(k): round(v, 4) for k, v in grid.items()},
                "frames": [f"{s['clip']}#{s['i']}" for s in self.samples],
                "right": np.asarray(cam["right"]).tolist(), "up": np.asarray(cam["up"]).tolist(),
                "fwd": np.asarray(cam["fwd"]).tolist(),
                "defMap": {"cx": float(fc["cx"]), "cy": float(fc["cy"]), "s": float(fc["scale"])},
                "defMapNote": f"similarity fit (area + centroid) of {s0['clip']} DEF frame {s0['i']} at view yaw {yaw:g}"}

    def pair(self, view: dict, h: int = 300) -> Image.Image:
        """Idle frame 0: DEF | render through the fitted camera, cropped to the union box."""
        s = self.samples[0]
        cam = dict(self.cam(view["viewYawDeg"]), cx=view["defMap"]["cx"], cy=view["defMap"]["cy"],
                   scale=view["defMap"]["s"])
        img = self.render(cam, s)
        rgb = img[..., :3] + (1 - img[..., 3:4]) * 0.16
        ren = Image.fromarray((rgb.clip(0, 1) * 255).astype(np.uint8))
        d = Image.fromarray(s["def"])
        dd = Image.new("RGB", d.size, (41, 41, 41))
        dd.paste(d, (0, 0), d)
        m = np.logical_or(s["def"][..., 3] > 0, img[..., 3] > 0.05)
        ys, xs = np.nonzero(m)
        box = (max(0, xs.min() - 10), max(0, ys.min() - 10), xs.max() + 10, ys.max() + 10)
        a, b = dd.crop(box), ren.crop(box)
        k = h / a.height
        a, b = (x.resize((max(1, round(x.width * k)), h), Image.LANCZOS) for x in (a, b))
        out = Image.new("RGB", (a.width * 2 + 8, h), (255, 255, 255))
        out.paste(a, (0, 0))
        out.paste(b, (a.width + 8, 0))
        return out


def view_for(lab: str, refit: bool = False, fitter: Fitter | None = None) -> dict:
    p = VIEWS / f"{lab}.json"
    f = fitter
    if p.is_file() and not refit:
        v = json.loads(p.read_text(encoding="utf-8"))
        f = f or Fitter(lab)
        if v.get("schema") == SCHEMA and v.get("key") == f.key():
            return v
    f = f or Fitter(lab)
    v = f.fit()
    VIEWS.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, indent=1), encoding="utf-8")
    return v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labs", nargs="+")
    ap.add_argument("--sheet")
    ap.add_argument("--refit", action="store_true")
    a = ap.parse_args(argv)
    tiles = []
    for lab in a.labs:
        try:
            f = Fitter(lab)
            v = view_for(lab, a.refit, f)
        except (RuntimeError, SystemExit, KeyError, FileNotFoundError, ValueError) as e:
            print(f"FAILED {lab}: {e}", flush=True)
            continue
        print(f"{lab}: view yaw {v['viewYawDeg']:+g} deg (score {v['score']} vs {v['scoreAtSpriteCam']} at the "
              f"SpriteCam; deyaw {v['deyawDeg']}; frames {', '.join(v['frames'])})", flush=True)
        if a.sheet:
            t = f.pair(v)
            hdr = Image.new("RGB", (max(t.width, 260), t.height + 26), (255, 255, 255))
            ImageDraw.Draw(hdr).text((4, 4), f"{lab}  yaw {v['viewYawDeg']:+g}  (DEF | mesh, Idle f0)", fill=(0, 0, 0))
            hdr.paste(t, (0, 26))
            tiles.append(hdr)
        del f
    if a.sheet and tiles:
        cols = min(4, len(tiles))
        rows = math.ceil(len(tiles) / cols)
        cw, ch = max(t.width for t in tiles), max(t.height for t in tiles)
        sheet = Image.new("RGB", (cols * (cw + 10), rows * (ch + 10)), (255, 255, 255))
        for i, t in enumerate(tiles):
            sheet.paste(t, ((i % cols) * (cw + 10), (i // cols) * (ch + 10)))
        sheet.save(a.sheet)
        print("sheet", a.sheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
