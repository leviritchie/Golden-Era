"""Build Titan (h3_giant_upg / CGTITA.DEF) VFX flipbook textures + a Unity build spec.

Approaches (per DEF frame, same 12 fps as the def_retarget clips):
  A  literal: the DEF's own lightning pixels (bolt + crackle), 1 DEF px = 1 texel, point filtered.
  B  readable: the DEF frame's lightning skeletonised (same branching and silhouette) and
     redrawn at 2 texels per DEF px with a ~4-texel white core and a 1-texel pale-blue
     rim (isolated specks under 4 px dropped) (colours measured from CGTITA), hard edges, no bloom.
  missile: CPRGTIX frame chosen by angle (level shot = frame 4), literal.

Each flipbook cell is centred on the anchor bone projected into sprite space by the Blender
render (work/mesh2x/bones.json), so a billboard placed at that bone reproduces the DEF layout
when seen from the sprite camera. Output: artifacts/homm3_vfx_experiments/titan/work/unity_payload/
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_dilation

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import h3def  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORK = ROOT / "artifacts/homm3_vfx_experiments/titan/work"
OUT = WORK / "unity_payload"
SPRITECAM = ROOT / "artifacts/homm3_def_retarget/h3_giant_upg/h3_giant_upg_def_retarget.blend.spritecam.json"
FPS = 12.0
WHITE = (255, 255, 255, 255)
RIM = [(178, 219, 245, 255), (194, 239, 255, 255), (154, 203, 255, 255)]  # measured CGTITA bolt edge colours
CLIPS = {
    # clip: (DEF group, first master frame, anchor bone)
    "attack": (12, 46, "RightHand"),
    "shoot": (15, 54, "LeftHand"),
}


def lightning_mask(f, pal):
    c = pal.astype(float)[f.idx]
    lum = c @ np.array([0.299, 0.587, 0.114])
    return (f.idx > 7) & (lum >= 170) & (c[..., 2] >= c[..., 0] - 5)


def cell_box(masks, anchors, pad=6):
    dx0 = dy0 = 10 ** 6
    dx1 = dy1 = -10 ** 6
    for m, (ax, ay) in zip(masks, anchors):
        ys, xs = np.nonzero(m)
        if len(xs):
            dx0, dx1 = min(dx0, xs.min() - ax), max(dx1, xs.max() - ax)
            dy0, dy1 = min(dy0, ys.min() - ay), max(dy1, ys.max() - ay)
    half_w = int(max(abs(dx0), abs(dx1)) + pad)
    half_h = int(max(abs(dy0), abs(dy1)) + pad)
    return half_w, half_h


def crop_centered(arr, ax, ay, hw, hh):
    h, w = arr.shape[:2]
    out = np.zeros((2 * hh, 2 * hw) + arr.shape[2:], arr.dtype)
    x0, y0 = int(round(ax)) - hw, int(round(ay)) - hh
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(w, x0 + 2 * hw), min(h, y0 + 2 * hh)
    out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = arr[sy0:sy1, sx0:sx1]
    return out


def procedural_frame(rng, region, scale=2):
    """Readable redraw of a DEF lightning frame: skeletonise the DEF lightning pixels
    (keeps its branching and silhouette), then draw each skeleton pixel at `scale` texels per
    DEF px with a ~4-texel white core and a 1-texel pale-blue rim; specks under 4 px are dropped. Hard edges, no bloom."""
    from skimage.morphology import skeletonize
    h, w = region.shape
    arr = np.zeros((h * scale, w * scale, 4), np.uint8)
    if not region.any():
        return arr
    sk = skeletonize(region)
    # drop isolated spark specks (skeleton pieces under 4 px): redrawn they read as round beads
    from scipy.ndimage import label
    lab, n = label(sk, structure=np.ones((3, 3)))
    if n:
        sizes = np.bincount(lab.ravel())
        sk = sk & (sizes[lab] >= 4)
    # nearest upscale keeps 8-connectivity; a 3x3 dilation then gives a ~4-texel white core
    big = sk.repeat(scale, 0).repeat(scale, 1)
    core = binary_dilation(big, structure=np.ones((3, 3)), iterations=1)
    rim = binary_dilation(core, iterations=1) & ~core  # 1-texel rim: ~3 DEF px total width
    rim_cols = np.array(RIM, np.uint8)
    arr[rim] = rim_cols[rng.integers(0, len(RIM), size=int(rim.sum()))]
    arr[core] = WHITE
    return arr


def sheet(cells):
    n = len(cells)
    tx = int(math.ceil(math.sqrt(n)))
    ty = int(math.ceil(n / tx))
    ch, cw = cells[0].shape[:2]
    out = np.zeros((ty * ch, tx * cw, 4), np.uint8)
    for i, c in enumerate(cells):
        # Unity texture-sheet rows run top to bottom in the image
        r, q = divmod(i, tx)
        out[r * ch:(r + 1) * ch, q * cw:(q + 1) * cw] = c
    return out, tx, ty


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = h3def.read_def("cgtita.def")
    pal = d.palette
    bones = json.load(open(WORK / "mesh2x/bones.json"))
    cam = json.load(open(SPRITECAM))
    ppu = cam["pxPerUnit"]
    rng = np.random.default_rng(11)
    systems = []
    for clip, (g, m0, bone) in CLIPS.items():
        frames = d.groups[g]
        # the Unity bone transform sits at the bone head
        anchors = [bones["frames"][str(m0 + i + 1)][bone]["head"][:2] for i in range(len(frames))]
        masks = [lightning_mask(f, pal) for f in frames]
        hw, hh = cell_box(masks, anchors)
        cells_a, cells_b = [], []
        for f, m, (ax, ay) in zip(frames, masks, anchors):
            rgba = h3def.to_rgba(f, pal)
            rgba[~m] = 0
            cells_a.append(crop_centered(rgba, ax, ay, hw, hh))
            region = crop_centered(binary_dilation(m, iterations=1), ax, ay, hw, hh)
            cells_b.append(procedural_frame(rng, region))
        for tag, cells, texel in (("A", cells_a, 1), ("B", cells_b, 2)):
            arr, tx, ty = sheet(cells)
            name = f"titan_{clip}_{tag}.png"
            Image.fromarray(arr).save(OUT / name)
            systems.append({"name": f"titan_{clip}_{tag}", "texture": name, "tilesX": tx, "tilesY": ty,
                            "frames": len(cells), "fps": FPS, "startDelay": 0.0,
                            "sizeUnits": [2 * hw / ppu, 2 * hh / ppu], "texelsPerDefPixel": texel,
                            "simulationSpace": "Local", "velocityWorld": [0, 0, 0], "anchor": bone})
    # missile: level shot to screen-right -> CPRGTIX frame 4 (angle 0). Launch at CRANIM
    # attackClimaxFrame 6 of the 7-frame shoot clip.
    mis = h3def.read_def("cprgtix.def")
    fr = mis.groups[0][4]
    rgba = h3def.to_rgba(fr, mis.palette)
    ys, xs = np.nonzero(rgba[..., 3])
    rgba = rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    Image.fromarray(rgba).save(OUT / "titan_missile_f4.png")
    right_b = np.array(cam["right"])  # Blender sprite-camera right
    right_u = [-right_b[0], right_b[2], -right_b[1]]  # Blender -> glTF -> Unity (glTFast mirrors X)
    speed = 1250.0 / ppu * (FPS / 10.0)  # VCMI 1250 DEF px/s at base speed, scaled to the 12 fps clip
    systems.append({"name": "titan_missile", "texture": "titan_missile_f4.png", "tilesX": 1, "tilesY": 1,
                    "frames": 1, "fps": FPS, "startDelay": 6 / FPS, "lifetime": 0.6,
                    "sizeUnits": [rgba.shape[1] / ppu, rgba.shape[0] / ppu], "texelsPerDefPixel": 1,
                    "simulationSpace": "World", "velocityWorld": [v * speed for v in right_u], "anchor": "LeftHand"})
    spec = {"schema": "homm3_vfx_lab.v1", "unitSid": "h3_giant_upg",
            "glb": "artifacts/homm3_def_retarget/h3_giant_upg/h3_giant_upg_def_retarget.glb",
            "pxPerUnit": ppu, "cameraRightUnity": right_u,
            "prefabs": {"titan_attack_A": ["titan_attack_A"], "titan_attack_B": ["titan_attack_B"],
                        "titan_shoot_A_missile": ["titan_shoot_A", "titan_missile"],
                        "titan_shoot_B_missile": ["titan_shoot_B", "titan_missile"]},
            "systems": systems}
    (OUT / "vfx_lab_spec.json").write_text(json.dumps(spec, indent=1))
    for s in systems:
        print(s["name"], s["tilesX"], s["tilesY"], [round(v, 2) for v in s["sizeUnits"]])


if __name__ == "__main__":
    main()
