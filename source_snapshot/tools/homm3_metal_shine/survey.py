#!/usr/bin/env python3
"""Survey slice units for the dynamic metal shine (docs/homm3_metal_shine.md).

For every row of the given delivery slices: read the FROZEN look_delivered.glb + basecolor.png (sha-checked against
the slice row), build the metal mask exactly as build_masks.py does (metal.py texture_mask on the Meshy
metallicRoughness map, B = metallic), and measure
  * share  - fraction of UV-covered texels with mask > 0.5;
  * clump  - fraction of those texels that survive a 3x3 binary opening (speckle / noise scores low);
and draw a per-slice board: each unit as a cheap numpy point-splat of its bind-pose mesh from front and back,
albedo on the left half of the tile, albedo with the metal mask in orange on the right half. Read it by eye: the
orange must sit on armour, blades, helmets, buckles, not on cloth or skin.

numpy/PIL only (no Blender, no Unity); one unit in memory at a time (~0.7 GB peak for the 4096^2 MR map).

  python tools/homm3_metal_shine/survey.py castle_slice_v1 [rampart_slice_v1 ...]
      -> V:/olden_port_work/metal_shine/survey/<slice>.json + boards/<slice>_mask_board.png
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_unit_look"))
import metal  # noqa: E402
from glbpatch import Glb  # noqa: E402

DELIVERY = ROOT / "tools" / "homm3_def_retarget_delivery"
SCRATCH = Path("V:/olden_port_work/metal_shine")
MASK = {"source": "meshyMetallic", "metallic": [0.45, 0.8], "blur": 1.5}
SIZE = 1024
TILE = 224
_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_accessor(glb: Glb, ai: int) -> np.ndarray:
    a = glb.json["accessors"][ai]
    bv = glb.json["bufferViews"][a["bufferView"]]
    dt = np.dtype(_CT[a["componentType"]])
    nc = _NC[a["type"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or dt.itemsize * nc
    raw = np.frombuffer(bytes(glb.bin), np.uint8, count=stride * (a["count"] - 1) + dt.itemsize * nc, offset=off)
    out = np.lib.stride_tricks.as_strided(raw, (a["count"], dt.itemsize * nc), (stride, 1)).copy()
    v = out.view(dt).reshape(a["count"], nc).astype(np.float32)
    if a.get("normalized"):
        v /= np.iinfo(dt).max
    return v


def body_geometry(glb: Glb):
    mesh = glb.json["meshes"][glb.body_mesh_index()]
    P, U, I = [], [], []
    base = 0
    for prim in mesh["primitives"]:
        p = read_accessor(glb, prim["attributes"]["POSITION"])
        u = read_accessor(glb, prim["attributes"]["TEXCOORD_0"])
        i = read_accessor(glb, prim["indices"]).astype(np.int64).reshape(-1, 3) if "indices" in prim \
            else np.arange(len(p)).reshape(-1, 3)
        P.append(p), U.append(u), I.append(i + base)
        base += len(p)
    return np.concatenate(P), np.concatenate(U), np.concatenate(I)


def splat(P, U, I, tex: np.ndarray, yaw_deg: float, size: int) -> np.ndarray:
    """Orthographic point-splat render (z-buffered) of the mesh, sampling ``tex`` (HxWx3) through the UVs."""
    rng = np.random.default_rng(0)
    n = max(1, min(24, 400000 // max(1, len(I))))
    w = rng.dirichlet((1, 1, 1), size=(len(I), n)).astype(np.float32)            # (T, n, 3)
    pts = np.einsum("tnk,tkc->tnc", w, P[I]).reshape(-1, 3)
    uvs = np.einsum("tnk,tkc->tnc", w, U[I]).reshape(-1, 2)
    t = np.radians(yaw_deg)
    x = pts[:, 0] * np.cos(t) + pts[:, 2] * np.sin(t)
    z = -pts[:, 0] * np.sin(t) + pts[:, 2] * np.cos(t)
    y = pts[:, 1]
    lo = np.array([x.min(), y.min()]); span = max(x.max() - x.min(), y.max() - y.min()) * 1.05 + 1e-6
    cx = (x.min() + x.max()) / 2; cy = (y.min() + y.max()) / 2
    px = ((x - cx) / span + 0.5) * (size - 1)
    py = (0.5 - (y - cy) / span) * (size - 1)
    ix = np.clip(px.astype(np.int64), 0, size - 1); iy = np.clip(py.astype(np.int64), 0, size - 1)
    h, wd = tex.shape[:2]
    tu = np.clip((uvs[:, 0] % 1.0) * (wd - 1), 0, wd - 1).astype(np.int64)
    tv = np.clip((uvs[:, 1] % 1.0) * (h - 1), 0, h - 1).astype(np.int64)    # glTF uv origin is top-left
    col = tex[tv, tu]
    order = np.argsort(z)                                   # far first (camera at +z), near overwrites
    img = np.zeros((size, size, 3), np.float32) + np.array([0.16, 0.15, 0.14], np.float32)
    img[iy[order], ix[order]] = col[order]
    del lo
    return img


def unit_stats(row: dict, inputs: Path) -> dict:
    if not (inputs / "look_delivered.glb").is_file() or not (inputs / "basecolor.png").is_file():
        return {"status": "noInputs"}
    glb_b = (inputs / "look_delivered.glb").read_bytes()
    bc_b = (inputs / "basecolor.png").read_bytes()
    fz = row["frozen"]
    if hashlib.sha256(glb_b).hexdigest() != fz["lookDeliveredGlbSha256"] \
            or hashlib.sha256(bc_b).hexdigest() != fz["basecolorSha256"]:
        return {"status": "inputsDrift"}
    glb = Glb(glb_b)
    try:
        mask = metal.texture_mask({"mask": MASK}, glb, SIZE, None)
    except ValueError as e:
        return {"status": "noMetallicMap", "detail": str(e)}
    bc = np.asarray(Image.open(io.BytesIO(bc_b)).convert("RGB").resize((SIZE, SIZE), Image.BOX), np.float32) / 255
    covered = bc.max(-1) > 0.02
    hard = mask > 0.5
    share = float(hard[covered].mean()) if covered.any() else 0.0
    opened = ndimage.binary_opening(hard, np.ones((3, 3), bool))
    clump = float(opened.sum() / hard.sum()) if hard.any() else 0.0
    P, U, I = body_geometry(glb)
    ov = bc * 0.5 + np.stack([mask, mask * 0.55, mask * 0.0], -1) * 0.5
    ov = np.where(hard[..., None], ov, bc * 0.55)
    half = TILE // 2
    views = []
    for yaw in (0.0, 180.0):
        views.append(np.concatenate([splat(P, U, I, bc, yaw, half), splat(P, U, I, ov, yaw, half)], 1))
    tile = np.concatenate(views, 0)
    return {"status": "ok", "share": round(share, 4), "clump": round(clump, 3), "texels": int(hard.sum()),
            "tile": tile}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slices", nargs="+")
    a = ap.parse_args()
    (SCRATCH / "survey").mkdir(parents=True, exist_ok=True)
    (SCRATCH / "boards").mkdir(parents=True, exist_ok=True)
    for sl in a.slices:
        sel = json.loads((DELIVERY / f"{sl}.json").read_text(encoding="utf-8"))
        res, tiles = {}, []
        for row in sel["units"]:
            sid = row["labSid"]
            st = unit_stats(row, ROOT / sel["out"] / sid / "inputs")
            tile = st.pop("tile", None)
            res[sid] = st
            print(sl, sid, st, flush=True)
            if tile is not None:
                im = Image.fromarray((np.clip(tile, 0, 1) * 255).astype(np.uint8))
                d = ImageDraw.Draw(im)
                d.rectangle([0, 0, TILE, 12], fill=(0, 0, 0))
                d.text((2, 0), f"{sid} {st['share']:.1%} c{st['clump']:.2f}", fill=(255, 255, 255))
                tiles.append(np.asarray(im))
        (SCRATCH / "survey" / f"{sl}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        if tiles:
            cols = 6
            while len(tiles) % cols:
                tiles.append(np.zeros_like(tiles[0]))
            rows = [np.concatenate(tiles[i:i + cols], 1) for i in range(0, len(tiles), cols)]
            Image.fromarray(np.concatenate(rows, 0)).save(SCRATCH / "boards" / f"{sl}_mask_board.png")
            print("board ->", SCRATCH / "boards" / f"{sl}_mask_board.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
