"""DEF effect ripper: cut a unit's own effect pixels out of its DEF frames as `defFlipbook` layers.

Emits layers in the unit-look spec format (docs/homm3_unit_look_pipeline.md, schema homm3_unit_look.v1),
plus the per-frame effect masks the layer points at and a CPU preview against the retarget's mesh renders.

Usage
  python tools/homm3_vfx/def_effect_ripper.py <unit> --auto [--merge-spec] [--no-preview]
      one layer per ripper candidate in artifacts/homm3_vfx_experiments/_roster/inventory.json
      (retarget clips only; pose-paint suspects and on-body tints are skipped: they are lighting, not flipbooks)
  python tools/homm3_vfx/def_effect_ripper.py <unit> --layer "id=breath,clip=Unit_AttackFront,frames=3-5,classes=fire,bone=Head" ...
      explicit layers; keys: id, clip, frames (a-b or a;b;c), classes (electric;fire;magic;water;smoke;detached),
      bone (anchor; default = Head when the effect touches the head, else the bone nearest the pixels where the
      effect touches the body), mesh (1 = subtractMeshSilhouette), minpx (drop effect clusters smaller than this, default 40),
      dilate (px, default 1), light (dynamic light id)

Effect pixels (def_effects.frame_effects): colours absent from the unit's idle frames that fall in an effect
colour class, plus detached opaque components; `classes` narrows the layer to what the event is.
Body mask: `subtractMeshSilhouette` is set for held/steady effects (the Titan double-bolt lesson) and left off
for emissions (breath, sparks, missiles) that the sprite draws in front of the body.

Outputs (all regenerable, under artifacts/homm3_unit_look/<unit>/, never in git):
  vfx_masks/<layer>/g<GG>_<FF>.png   1-bit effect mask per DEF frame (DEF canvas, 1 px = 1 DEF px)
  rip/ripped_layers.json             the layers, ready for the spec's vfx.layers
  rip/<layer>_cells.png              flipbook cells centred on the anchor bone head (preview of what vfx builds)
  rip/<layer>_preview.png / .gif     DEF | mesh render | mesh + ripped effect (anchored, body mask applied)
--merge-spec replaces same-id layers in tools/homm3_unit_look/units/<unit>.json (spec must exist).

Proof: generated artifact. The preview is a 2D composite over the def_retarget's own SpriteCam renders
(renders/sprite_NNN.png); not Unity, not in game.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(__file__))
import def_effects as D  # noqa: E402

ROOT = D.ROOT
INV = os.path.join(ROOT, "artifacts/homm3_vfx_experiments/_roster/inventory.json")
CLIP_GROUP = {"Unit_Move": 0, "Unit_Mouseover": 1, "Unit_Idle": 2, "Unit_Hitted": 3, "Unit_Defence": 4, "Unit_Death": 5,
              "Unit_AttackFront": 12, "Unit_ShootFront": 15, "Unit_MoveStart": 20, "Unit_MoveEnd": 21}
GROUP_CLIP = {v: k for k, v in CLIP_GROUP.items()}
CLASS_IDX = {c: k for k, c in enumerate(D.EFFECT_CLASSES, start=1)}
BG = (72, 88, 64)


def parse_frames(s):
    out = []
    for part in s.replace(";", " ").split():
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def auto_layers(unit):
    inv = json.load(open(INV))["units"].get(unit)
    if not inv or "error" in inv:
        raise SystemExit(f"{unit}: not in the roster inventory (run roster_vfx_inventory.py {unit})")
    out = []
    for g, gd in sorted(inv["groups"].items(), key=lambda kv: int(kv[0])):
        g = int(g)
        if not gd["inRetarget"] or g not in GROUP_CLIP:
            continue
        for k, e in enumerate(gd["events"]):
            if e.get("posePaintSuspect") or e["kind"].startswith("on-body tint"):
                continue
            bones = e.get("boneCandidatesAtOrigin") or e.get("boneCandidatesAtPeak") or []
            classes = sorted(c for c, v in e["classPx"].items() if v >= 0.1 * max(e["classPx"].values()))
            held = e["kind"].startswith("held") or (e["motion"] == "in_place" and e["heldShare"] >= 0.8)
            out.append({"id": f"g{g:02d}_{e['class']}_{k}", "clip": GROUP_CLIP[g], "group": g, "frames": e["frames"],
                        "classes": classes or [e["class"]], "bone": bones[0]["bone"] if bones else None,
                        "mesh": held, "dilate": 1, "minpx": 40, "kind": e["kind"]})
    return out


def explicit_layer(s):
    kv = dict(p.split("=", 1) for p in s.split(","))
    clip = kv["clip"]
    return {"id": kv["id"], "clip": clip, "group": CLIP_GROUP[clip], "frames": parse_frames(kv["frames"]),
            "classes": kv.get("classes", "electric;fire;magic;water;smoke;detached").split(";"),
            "bone": kv.get("bone"), "mesh": kv.get("mesh", "0") == "1", "dilate": int(kv.get("dilate", 1)),
            "minpx": int(kv.get("minpx", 40)),
            "light": kv.get("light"), "kind": "explicit"}


def mesh_render(unit, m):
    p = os.path.join(D.ART, unit, "renders", f"sprite_{m + 1:03d}.png")  # renders are 1-based: sprite_001 = master 0
    return np.asarray(Image.open(p).convert("RGBA")) if os.path.exists(p) else None


def rip(unit, layers, out_root, preview=True, mask_format="defEffects"):
    us = D.load_unit(unit)
    base = D.baseline(us)
    bones = D.BoneProjector(unit)
    rip_dir = os.path.join(out_root, "rip")
    os.makedirs(rip_dir, exist_ok=True)
    spec_layers, report = [], []
    for L in layers:
        g = L["group"]
        frames = us.group_rgba(g)
        nfr = len(frames)
        L["frames"] = [i for i in L["frames"] if 0 <= i < nfr]
        mdir = os.path.join(out_root, "vfx_masks", L["id"])
        os.makedirs(mdir, exist_ok=True)
        masks, anchors, meshes = {}, {}, {}
        # anchor bone: explicit, else nearest projected bone to the effect's first-frame origin
        for i in range(nfr):
            fe = D.frame_effects(frames[i], base, classes=[c for c in L["classes"] if c != "detached"],
                                 include_detached="detached" in L["classes"], min_component_px=L.get("minpx", 1))
            m = fe["layer"] if i in L["frames"] else np.zeros_like(fe["fx"])
            masks[i] = m
            Image.fromarray((m * 255).astype(np.uint8)).save(os.path.join(mdir, f"g{g:02d}_{i:02d}.png"))
            mi = us.master_index(g, i)
            anchors[i] = bones.pixels(mi) if mi is not None else None
            meshes[i] = mesh_render(unit, mi) if mi is not None else None
        if not L.get("bone"):
            f0 = next((i for i in L["frames"] if masks[i].any()), None)
            if f0 is not None and anchors[f0]:
                # root of the effect = its pixels touching the sprite body (the mouth of a breath, the fist of
                # an arc); the centroid of an emission sits far out and picks whatever limb is nearby
                fe0 = D.frame_effects(frames[f0], base)
                body = fe0["opaque"] & ~fe0["fx"]
                touch = masks[f0] & ndi.binary_dilation(body, iterations=3)
                yy, xx = np.nonzero(touch if touch.any() else masks[f0])
                px = anchors[f0]
                heads = [b for b in px if b in ("Head", "Neck") or b.startswith(("Head", "Jaw"))]
                by = np.nonzero(frames[f0][..., 3] == 255)[0]
                hdist = min((float(np.min(np.hypot(xx - px[b][0], yy - px[b][1]))) for b in heads), default=1e9)
                if hdist <= max(6.0, 0.08 * (by.max() - by.min())):
                    L["bone"] = "Head" if "Head" in px else heads[0]
                else:
                    L["bone"] = D.bone_candidates(px, (float(xx.mean()), float(yy.mean())), k=1)[0]["bone"]
        bone = L["bone"]
        lit = [i for i in L["frames"] if masks[i].any()]
        # body mask as the vfx stage will apply it: mesh silhouette of the same master frame, dilated
        cut = {}
        for i in lit:
            m = masks[i]
            if L["mesh"] and meshes[i] is not None:
                sil = ndi.binary_dilation(meshes[i][..., 3] > 0, iterations=L["dilate"])
                m = m & ~sil
            cut[i] = m
        kept = {i: int(cut[i].sum()) for i in lit}
        layer = {"id": L["id"], "type": "defFlipbook", "def": us.def_name.upper() + ".DEF",
                 "clips": {L["clip"]: {"defGroup": g, "frames": lit}},
                 "effectMask": ({"method": "file", "path": os.path.relpath(mdir, ROOT).replace("\\", "/")}
                                if mask_format == "file" else
                                {"method": "defEffects", "classes": [c for c in L["classes"] if c != "detached"],
                                 "includeDetached": "detached" in L["classes"], "minComponentPx": L.get("minpx", 1)}),
                 "bodyMask": {"subtractMeshSilhouette": bool(L["mesh"]), "dilatePx": L["dilate"]},
                 "anchor": {"bone": bone, "point": "head"}, "texelsPerDefPx": 1}
        if L.get("light"):
            layer["light"] = L["light"]
        if mask_format == "defEffects":
            layer["provenance"] = f"def_effect_ripper: {L['kind']} (g{g} frames {lit[0] if lit else '-'}-{lit[-1] if lit else '-'})"
        spec_layers.append(layer)
        rep = {"id": L["id"], "kind": L["kind"], "clip": L["clip"], "group": g, "classes": L["classes"], "bone": bone,
               "framesLit": lit, "pxPerFrame": {i: int(masks[i].sum()) for i in lit}, "pxAfterBodyMask": kept,
               "holds": [i for i in lit[1:] if i - 1 in masks and np.array_equal(masks[i], masks[i - 1])]}
        if lit and anchors[lit[0]] and bone in anchors[lit[0]]:
            offs = []
            for i in lit:
                ax, ay = anchors[i][bone]
                yy, xx = np.nonzero(cut[i]) if cut[i].any() else np.nonzero(masks[i])
                offs.append([round(float(xx.mean() - ax), 1), round(float(yy.mean() - ay), 1)])
            rep["effectCentroidFromAnchorPx"] = offs
        if preview and lit:
            rep.update(write_preview(unit, L, frames, masks, cut, anchors, meshes, rip_dir))
        report.append(rep)
    json.dump({"schema": "homm3_unit_look.v1 vfx.layers fragment (defFlipbook)", "unit": unit,
               "proof": "generated artifact (DEF measurement + 2D composite over the retarget's SpriteCam renders)",
               "layers": spec_layers, "report": report}, open(os.path.join(rip_dir, "ripped_layers.json"), "w"), indent=1)
    return spec_layers, report


def write_preview(unit, L, frames, masks, cut, anchors, meshes, rip_dir):
    g, bone = L["group"], L["bone"]
    nfr = len(frames)
    # crop box: union of DEF opaque, mesh opaque and effect
    acc = np.zeros(frames[0].shape[:2], bool)
    for i in range(nfr):
        acc |= frames[i][..., 3] > 0
        if meshes[i] is not None and meshes[i].shape[:2] == acc.shape:
            acc |= meshes[i][..., 3] > 0
    ys, xs = np.nonzero(acc)
    x0, y0, x1, y1 = max(0, xs.min() - 6), max(0, ys.min() - 6), min(acc.shape[1], xs.max() + 7), min(acc.shape[0], ys.max() + 7)
    S = 2

    def comp(rgba):
        bg = Image.new("RGBA", (rgba.shape[1], rgba.shape[0]), BG + (255,))
        return Image.alpha_composite(bg, Image.fromarray(rgba, "RGBA")).convert("RGB")

    tiles, gif = [], []
    for i in range(nfr):
        d = frames[i]
        mesh = meshes[i] if meshes[i] is not None else np.zeros_like(d)
        fx = d.copy()
        m = cut.get(i, np.zeros(d.shape[:2], bool))
        fx[~m] = 0
        over = np.asarray(Image.alpha_composite(Image.fromarray(mesh, "RGBA"), Image.fromarray(fx, "RGBA")))
        row = [np.asarray(comp(x))[y0:y1, x0:x1].copy() for x in (d, mesh, over)]
        if anchors[i] and bone in anchors[i]:
            ax, ay = anchors[i][bone]
            for t in row[1:]:
                cx, cy = int(round(ax)) - x0, int(round(ay)) - y0
                if 0 <= cx < t.shape[1] and 0 <= cy < t.shape[0]:
                    t[max(0, cy - 2):cy + 3, cx] = (255, 0, 255)
                    t[cy, max(0, cx - 2):cx + 3] = (255, 0, 255)
        strip = np.concatenate(row, 1)
        tiles.append(strip)
        gif.append(Image.fromarray(strip).resize((strip.shape[1] * S, strip.shape[0] * S), Image.NEAREST))
    th, tw = tiles[0].shape[:2]
    sheet = Image.new("RGB", (tw * S, (th * S + 12) * nfr + 14), (20, 20, 20))
    dr = ImageDraw.Draw(sheet)
    dr.text((2, 1), f"{unit} {L['id']} ({L['clip']} g{g}) | DEF | mesh render | mesh + ripped effect (anchor {bone} = magenta)",
            fill=(230, 230, 230))
    for i, t in enumerate(tiles):
        y = 14 + i * (th * S + 12)
        sheet.paste(Image.fromarray(t).resize((tw * S, th * S), Image.NEAREST), (0, y))
        lit = "lit" if i in cut else "-"
        dr.text((2, y + th * S), f"f{i} {lit}", fill=(200, 200, 200))
    sp = os.path.join(rip_dir, f"{L['id']}_preview.png")
    sheet.save(sp)
    gp = os.path.join(rip_dir, f"{L['id']}_preview.gif")
    gif[0].save(gp, save_all=True, append_images=gif[1:], duration=1000 // 12 * 2, loop=0)  # half speed for review
    try:  # mp4 at the DEF's 12 fps (review video); skipped when ffmpeg is absent
        import subprocess
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", gp, "-vf", "fps=6,scale=trunc(iw/2)*2:trunc(ih/2)*2",
                        "-pix_fmt", "yuv420p", gp[:-4] + ".mp4"], check=False, timeout=120)
    except (OSError, subprocess.SubprocessError):
        pass
    # flipbook cells centred on the anchor bone head (what the vfx stage cuts)
    cells = []
    lit = [i for i in sorted(cut) if cut[i].any()]
    if lit and all(anchors[i] and bone in anchors[i] for i in lit):
        hw = hh = 8
        for i in lit:
            yy, xx = np.nonzero(cut[i])
            ax, ay = anchors[i][bone]
            hw = max(hw, int(np.abs(xx - ax).max()) + 4)
            hh = max(hh, int(np.abs(yy - ay).max()) + 4)
        for i in lit:
            ax, ay = anchors[i][bone]
            fx = frames[i].copy()
            fx[~cut[i]] = 0
            big = np.zeros((2 * hh, 2 * hw, 4), np.uint8)
            X0, Y0 = int(round(ax)) - hw, int(round(ay)) - hh
            sx0, sy0, sx1, sy1 = max(0, X0), max(0, Y0), min(fx.shape[1], X0 + 2 * hw), min(fx.shape[0], Y0 + 2 * hh)
            big[sy0 - Y0:sy1 - Y0, sx0 - X0:sx1 - X0] = fx[sy0:sy1, sx0:sx1]
            cells.append(big)
        Image.fromarray(np.concatenate(cells, 1)).save(os.path.join(rip_dir, f"{L['id']}_cells.png"))
    return {"preview": os.path.relpath(sp, ROOT).replace("\\", "/"), "gif": os.path.relpath(gp, ROOT).replace("\\", "/"),
            "cellHalfSizePx": [hw, hh] if cells else None}


def merge_spec(unit, layers):
    p = os.path.join(ROOT, "tools/homm3_unit_look/units", f"{unit}.json")
    if not os.path.exists(p):
        raise SystemExit(f"--merge-spec: {p} does not exist (create the unit's spec first)")
    spec = json.load(open(p))
    ids = {l["id"] for l in layers}
    spec.setdefault("vfx", {}).setdefault("layers", [])
    spec["vfx"]["layers"] = [l for l in spec["vfx"]["layers"] if l.get("id") not in ids] + layers
    json.dump(spec, open(p, "w"), indent=2)
    print("merged", len(layers), "layers into", p)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("unit")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--layer", action="append", default=[])
    ap.add_argument("--merge-spec", action="store_true")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--mask-format", choices=("file", "defEffects"), default="defEffects",
                    help="defEffects once homm3_unit_look.v1 carries it (approved; schema owner adds it); file = stopgap mask PNGs")
    a = ap.parse_args()
    layers = (auto_layers(a.unit) if a.auto else []) + [explicit_layer(s) for s in a.layer]
    if not layers:
        raise SystemExit("no layers: pass --auto or --layer")
    out_root = os.path.join(ROOT, "artifacts/homm3_unit_look", a.unit)
    spec_layers, report = rip(a.unit, layers, out_root, preview=not a.no_preview, mask_format=a.mask_format)
    for r in report:
        print(f"{r['id']:28s} {r['clip']:18s} bone {r['bone']:14s} frames {r['framesLit']} px {list(r['pxPerFrame'].values())} "
              f"-> {list(r['pxAfterBodyMask'].values())}  {r['kind']}")
    print("wrote", os.path.join(out_root, "rip", "ripped_layers.json"))
    if a.merge_spec:
        merge_spec(a.unit, spec_layers)


if __name__ == "__main__":
    main()
