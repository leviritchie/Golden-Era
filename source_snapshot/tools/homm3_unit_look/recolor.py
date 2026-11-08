"""Region palette recolor: re-skin a frozen unit's GLB with another HoMM3 unit's palette.

    python tools/homm3_unit_look/recolor.py <lab_sid> [--device cuda|cpu] [--out <dir>] [--glb]

Used when a unit is a palette swap of another in HoMM3 (2026-10-08 user: royal and battle griffin are
recolors of h3_griffin): the target ships the source's frozen mesh, rig and clips unchanged and only the
body base colour is rebuilt. Spec: tools/homm3_unit_look/recolor/<lab_sid>.json (homm3_unit_recolor.v1).

1. DEF pairs. Every frame of the source DEF is aligned to the same frame of the target DEF (2D
   similarity, mask IoU over target points); aligned opaque pixels give (source colour, target colour).
2. Classes. Source and target pixels are classed by the spec's ordered CIE Lab/LCh rules (first match
   wins); a target class can be re-labelled near another class (beak = tan/red near the eye).
3. Texture regions. The source GLB's skin weights (spec boneGroups) and rest positions are rasterised
   into UV space; region weights combine bone groups, a texel golden-ness weight, a forward-z beak ramp
   and texel colour classes (spec regions).
4. Transfer per region, from the paired DEF subset (source classes x target classes): L by quantile
   map, a/b by mean/std matching (z clamped). Regions blend by weight; dark low-chroma texels (claws,
   pupils, seams) keep the source colour. Uncovered texels take their nearest covered texel's weights.

Only the base colour carries the palette: the normal map and metallic-roughness image are not colour and
are carried unchanged (reported). Torch on CUDA by default; --device cpu is the reference
(test_recolor.py checks parity). Output: <out>/basecolor.png, <out>/recolor_report.json and, with --glb,
<out>/recolored.glb (the source look_delivered.glb with the body image swapped; debug/board use only -
the delivery freeze builds its own).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_unit_look"))
sys.path.insert(0, str(ROOT / "tools" / "homm3_prebake"))
from glbpatch import Glb, sha256_bytes, sha256_file  # noqa: E402
from regions import accessor  # noqa: E402

SCHEMA = "homm3_unit_recolor.v1"
SPEC_DIR = ROOT / "tools" / "homm3_unit_look" / "recolor"
SELECTION_DIR = ROOT / "tools" / "homm3_def_retarget_delivery"
DELIVERY_DIR = ROOT / "artifacts" / "homm3_def_retarget_delivery"
DEFAULT_OUT = ROOT / "artifacts" / "homm3_unit_look_recolor"
LAB_ROOT = Path("V:/homm3_unity_work/Assets/CustomUnits/homm3_lab")


# ---------------------------------------------------------------- colour (torch, sRGB D65 <-> CIE Lab)
_M = torch.tensor([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750],
                   [0.0193339, 0.1191920, 0.9503041]], dtype=torch.float64)
_WHITE = torch.tensor([0.95047, 1.0, 1.08883], dtype=torch.float64)


def rgb2lab(rgb: torch.Tensor) -> torch.Tensor:
    """rgb in [0,1], (..., 3) -> Lab (..., 3), float64."""
    c = rgb.double()
    lin = torch.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = lin @ _M.to(c.device).T / _WHITE.to(c.device)
    f = torch.where(xyz > (6 / 29) ** 3, xyz.clamp_min(1e-12) ** (1 / 3), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return torch.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab2rgb(lab: torch.Tensor) -> torch.Tensor:
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    f = torch.stack([fx, fy, fz], -1)
    xyz = torch.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * _WHITE.to(lab.device)
    lin = (xyz @ torch.linalg.inv(_M).to(lab.device).T).clamp(0, 1)
    return torch.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin.clamp_min(1e-12) ** (1 / 2.4) - 0.055).clamp(0, 1)


def classify(lab: torch.Tensor, rules: list[dict], default: str) -> np.ndarray:
    """Ordered rules (first match wins); each rule: {"class": name, <key>_lt / <key>_ge ...} over L, a, b, C, h."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    ch = {"L": L, "a": a, "b": b, "C": torch.hypot(a, b), "h": torch.rad2deg(torch.atan2(b, a))}
    names = [default] + [r["class"] for r in rules]
    idx = torch.zeros(L.shape, dtype=torch.long, device=lab.device)
    done = torch.zeros(L.shape, dtype=torch.bool, device=lab.device)
    for ri, r in enumerate(rules):
        m = torch.ones_like(done)
        for k, v in r.items():
            if k == "class":
                continue
            ch_k, op = k.rsplit("_", 1)
            m &= (ch[ch_k] < v) if op == "lt" else (ch[ch_k] >= v)
        m &= ~done
        idx[m] = ri + 1
        done |= m
    return np.array(names, dtype=object)[idx.cpu().numpy()]


# ---------------------------------------------------------------- DEF pairs
def def_frames(d: Path) -> list[str]:
    return sorted(p.name for p in d.glob("*.png"))


def align(ma: torch.Tensor, mb: torch.Tensor) -> tuple[float, float, float, float]:
    """Similarity mapping target px -> source px (x_s = ox + s * x_t) maximising mask IoU over target points."""
    dev = ma.device
    ya, xa = torch.nonzero(ma, as_tuple=True)
    yb, xb = torch.nonzero(mb, as_tuple=True)
    H, W = ma.shape
    s0 = float(np.sqrt(len(xa) / len(xb)))
    ss = torch.tensor(s0 * np.linspace(0.90, 1.10, 21), device=dev, dtype=torch.float64)
    dd = torch.arange(-8, 9, device=dev, dtype=torch.float64)
    S_, DX, DY = [t.reshape(-1) for t in torch.meshgrid(ss, dd, dd, indexing="ij")]
    cxa, cya = xa.double().mean(), ya.double().mean()
    cxb, cyb = xb.double().mean(), yb.double().mean()
    X, Y = xb.double(), yb.double()
    best = (-1.0, 0)
    for c0 in range(0, len(S_), 512):
        sl = slice(c0, c0 + 512)
        sx = torch.round(cxa + S_[sl, None] * (X[None] - cxb) + DX[sl, None]).long()
        sy = torch.round(cya + S_[sl, None] * (Y[None] - cyb) + DY[sl, None]).long()
        ok = (sx >= 0) & (sx < W) & (sy >= 0) & (sy < H)
        hit = torch.zeros_like(ok)
        hit[ok] = ma[sy[ok], sx[ok]]
        inter = hit.sum(1).double()
        iou = inter / (len(xa) / S_[sl] ** 2 + len(xb) - inter)
        k = int(iou.argmax())
        if float(iou[k]) > best[0]:
            best = (float(iou[k]), c0 + k)
    k = best[1]
    s = float(S_[k])
    return s, float(cxa - s * cxb + DX[k]), float(cya - s * cyb + DY[k]), best[0]


def erode(m: torch.Tensor) -> torch.Tensor:
    f = torch.nn.functional.max_pool2d((~m)[None, None].float(), 3, 1, 1)[0, 0]
    return m & (f < 0.5)


def def_pairs(src_dir: Path, tgt_dir: Path, dev: str) -> tuple[np.ndarray, dict]:
    """Rows: src rgb, tgt rgb, y, x, frame index (int32). Alignment uses the opaque masks (alpha >= 200)."""
    names = def_frames(src_dir)
    if names != def_frames(tgt_dir):
        raise SystemExit(f"DEF frame lists differ: {src_dir} vs {tgt_dir}")
    rows, ious = [], []
    for fi, n in enumerate(names):
        g = torch.tensor(np.asarray(Image.open(src_dir / n).convert("RGBA")), device=dev)
        t = torch.tensor(np.asarray(Image.open(tgt_dir / n).convert("RGBA")), device=dev)
        ma, mb = g[..., 3] >= 200, t[..., 3] >= 200
        if int(ma.sum()) < 50 or int(mb.sum()) < 50:
            continue
        s, ox, oy, iou = align(ma, mb)
        ious.append(iou)
        H, W = ma.shape
        yb, xb = torch.nonzero(mb, as_tuple=True)
        sx = torch.round(ox + s * xb.double()).long()
        sy = torch.round(oy + s * yb.double()).long()
        ok = (sx >= 0) & (sx < W) & (sy >= 0) & (sy < H)
        sx, sy, yb, xb = sx[ok], sy[ok], yb[ok], xb[ok]
        keep = erode(ma)[sy, sx] & erode(mb)[yb, xb]
        sx, sy, yb, xb = sx[keep], sy[keep], yb[keep], xb[keep]
        rows.append(torch.cat([g[sy, sx, :3].long(), t[yb, xb, :3].long(),
                               torch.stack([yb, xb, torch.full_like(yb, fi)], 1)], 1).cpu().numpy())
    P = np.concatenate(rows).astype(np.int32)
    return P, {"frames": len(ious), "pairs": int(len(P)),
               "iou_p5_p50_p95": [round(float(v), 3) for v in np.percentile(ious, [5, 50, 95])]}


def relabel_near(cls: np.ndarray, P: np.ndarray, rule: dict, chroma: np.ndarray) -> np.ndarray:
    """Target pixels of rule["from"] classes (chroma >= rule["C_ge"]) within radiusPx of the frame's rule["near"]
    centroid -> rule["class"]."""
    out = cls.copy()
    fid, yy, xx = P[:, 8], P[:, 6].astype(float), P[:, 7].astype(float)
    frm = np.isin(cls, rule["from"]) & (chroma >= rule.get("C_ge", 0))
    for f in np.unique(fid):
        m = fid == f
        e = m & (cls == rule["near"])
        if e.sum() < 2:
            continue
        out[m & frm & (np.hypot(yy - yy[e].mean(), xx - xx[e].mean()) < rule["radiusPx"])] = rule["class"]
    return out


# ---------------------------------------------------------------- texture raster
def raster(uv: np.ndarray, tris: np.ndarray, vals: np.ndarray, size: int, dev: str, chunk: int = 2048):
    """Barycentric UV raster (highest triangle index wins) of per-vertex values; returns (size, size, k) and coverage."""
    uvp = torch.tensor(uv * size - 0.5, dtype=torch.float64, device=dev)
    v = torch.tensor(vals, dtype=torch.float64, device=dev)
    out = torch.zeros((size, size, v.shape[1]), dtype=torch.float64, device=dev)
    cov = torch.zeros((size, size), dtype=torch.bool, device=dev)
    T = torch.tensor(tris, device=dev)
    for c0 in range(0, len(T), chunk):
        t = T[c0:c0 + chunk]
        a, b, c = uvp[t[:, 0]], uvp[t[:, 1]], uvp[t[:, 2]]
        mn = torch.floor(torch.minimum(torch.minimum(a, b), c)).clamp(0, size - 1).long()
        mx = torch.ceil(torch.maximum(torch.maximum(a, b), c)).clamp(0, size - 1).long()
        wh = mx - mn + 1
        n = wh[:, 0] * wh[:, 1]
        ti = torch.repeat_interleave(torch.arange(len(t), device=dev), n)
        off = torch.arange(int(n.sum()), device=dev) - torch.repeat_interleave(torch.cumsum(n, 0) - n, n)
        gx = mn[ti, 0] + off % wh[ti, 0]
        gy = mn[ti, 1] + off // wh[ti, 0]
        x0, y0, x1, y1, x2, y2 = a[ti, 0], a[ti, 1], b[ti, 0], b[ti, 1], c[ti, 0], c[ti, 1]
        d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        okd = d.abs() > 1e-12
        d = torch.where(okd, d, torch.ones_like(d))
        l0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / d
        l1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / d
        l2 = 1 - l0 - l1
        ins = okd & (l0 >= -0.02) & (l1 >= -0.02) & (l2 >= -0.02)
        # deterministic last writer: at a texel covered twice the higher triangle index wins (CPU == CUDA)
        lin = gy * size + gx
        win = torch.full((size * size,), -1, dtype=torch.long, device=dev)
        win.scatter_reduce_(0, lin[ins], ti[ins], reduce="amax")
        ins &= win[lin] == ti
        tt = t[ti[ins]]
        val = l0[ins, None] * v[tt[:, 0]] + l1[ins, None] * v[tt[:, 1]] + l2[ins, None] * v[tt[:, 2]]
        out[gy[ins], gx[ins]] = val
        cov[gy[ins], gx[ins]] = True
    return out, cov


def nearest_fill(x: torch.Tensor, cov: torch.Tensor) -> torch.Tensor:
    """Uncovered texels take the nearest covered texel's value (jump flooding, GPU-friendly)."""
    H, W = cov.shape
    dev = x.device
    yy, xx = torch.meshgrid(torch.arange(H, device=dev), torch.arange(W, device=dev), indexing="ij")
    sy = torch.where(cov, yy, torch.full_like(yy, -1))
    sx = torch.where(cov, xx, torch.full_like(xx, -1))
    step = 1 << int(np.ceil(np.log2(max(H, W))))
    while step >= 1:
        for dy in (-step, 0, step):
            for dx in (-step, 0, step):
                if dy == 0 and dx == 0:
                    continue
                ny = (yy + dy).clamp(0, H - 1)
                nx = (xx + dx).clamp(0, W - 1)
                cy, cx = sy[ny, nx], sx[ny, nx]
                valid = cy >= 0
                dn = torch.where(valid, (cy - yy) ** 2 + (cx - xx) ** 2, torch.full_like(yy, 1 << 40))
                do = torch.where(sy >= 0, (sy - yy) ** 2 + (sx - xx) ** 2, torch.full_like(yy, 1 << 40))
                better = dn < do
                sy = torch.where(better, cy, sy)
                sx = torch.where(better, cx, sx)
        step //= 2
    return x[sy.clamp_min(0), sx.clamp_min(0)]


# ---------------------------------------------------------------- spec / source
def load_spec(lab_sid: str) -> dict:
    p = SPEC_DIR / f"{lab_sid}.json"
    spec = json.loads(p.read_text(encoding="utf-8"))
    if spec.get("schema") != SCHEMA or spec.get("unit") != lab_sid:
        raise SystemExit(f"{p}: schema/unit mismatch")
    return spec


def source_row(spec: dict) -> tuple[dict, Path]:
    sel = json.loads((SELECTION_DIR / f"{spec['source']['selection']}.json").read_text(encoding="utf-8"))
    row = next((r for r in sel["units"] if r.get("labSid") == spec["source"]["labSid"]), None)
    if row is None:
        raise SystemExit(f"source {spec['source']} not in selection")
    d = DELIVERY_DIR / spec["source"]["selection"] / spec["source"]["labSid"]
    return row, d


def def_dir(lab_sid: str, def_name: str) -> Path:
    return LAB_ROOT / lab_sid / "extracted_battle" / f"{def_name}.dir"


def spec_sha(spec: dict) -> str:
    return sha256_bytes(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode())


# ---------------------------------------------------------------- recolor
def recolor(spec: dict, dev: str) -> tuple[np.ndarray, dict, Glb]:
    row, sdir = source_row(spec)
    glb_path = sdir / "inputs" / "look_delivered.glb"
    if sha256_file(glb_path) != row["frozen"]["lookDeliveredGlbSha256"]:
        raise SystemExit(f"{glb_path} does not match the source row frozen.lookDeliveredGlbSha256")
    g = Glb.load(glb_path)
    ii = g.body_base_color_image()
    base = np.asarray(Image.open(io.BytesIO(g.image_bytes(ii))).convert("RGB"))
    S = base.shape[0]

    # 1-2 DEF pairs + classes
    d = spec["def"]
    # def.sourceUnit: pair against another unit's DEF when the target DEF is a palette swap of that one, not of the
    # source row's own DEF (h3_sacred_phoenix: lvl7Alt is CPHX's frame list pixel for pixel; CFBIRD's differs)
    P, prep = def_pairs(def_dir(d.get("sourceUnit", spec["source"]["labSid"]), d["source"]),
                        def_dir(spec["unit"], d["target"]), dev)
    ls = rgb2lab(torch.tensor(P[:, 0:3] / 255.0, device=dev))
    lt = rgb2lab(torch.tensor(P[:, 3:6] / 255.0, device=dev))
    cs = classify(ls, spec["sourceClasses"]["rules"], spec["sourceClasses"]["default"])
    ct = classify(lt, spec["targetClasses"]["rules"], spec["targetClasses"]["default"])
    for rule in spec.get("targetRelabel", []):
        ct = relabel_near(ct, P, rule, torch.hypot(lt[:, 1], lt[:, 2]).cpu().numpy())

    # 3 texture regions
    mi = g.body_mesh_index()
    prim = g.json["meshes"][mi]["primitives"]
    if len(prim) != 1:
        raise SystemExit("recolor expects a single body primitive")
    p = prim[0]
    pos = accessor(g, p["attributes"]["POSITION"]).astype(np.float64)
    uv = accessor(g, p["attributes"]["TEXCOORD_0"]).astype(np.float64)
    tris = accessor(g, p["indices"]).reshape(-1, 3).astype(np.int64)
    J = accessor(g, p["attributes"]["JOINTS_0"]).astype(np.int64)
    Wt = accessor(g, p["attributes"]["WEIGHTS_0"]).astype(np.float64)
    node = next(n for n in g.json["nodes"] if n.get("mesh") == mi)
    jn = [g.json["nodes"][j].get("name", "") for j in g.json["skins"][node["skin"]]["joints"]]
    gnames = list(spec["boneGroups"])
    G = np.zeros((len(pos), len(gnames) + 1))
    for gi, k in enumerate(gnames):
        sel = np.array([n in spec["boneGroups"][k] for n in jn])
        G[:, gi] = (Wt * sel[J]).sum(1)
    G[:, -1] = np.clip(1 - G[:, :-1].sum(1), 0, 1)
    gnames.append(spec["restGroup"])
    img, cov = raster(uv, tris, np.concatenate([G, pos], 1), S, dev)
    img = nearest_fill(img, cov)
    grp = {k: img[..., i] for i, k in enumerate(gnames)}
    z = img[..., len(gnames) + 2]

    tex = rgb2lab(torch.tensor(base / 255.0, device=dev))
    L, a, b = tex[..., 0], tex[..., 1], tex[..., 2]
    C = torch.hypot(a, b)
    h = torch.rad2deg(torch.atan2(b, a))
    R = spec["regions"]
    ramp = lambda x, lo, hi: ((x - lo) / (hi - lo)).clamp(0, 1)  # noqa: E731
    gold = ramp(C, *R["golden"]["C"]) * ramp(h, *R["golden"]["h"])
    eye = ((b < R["eye"]["b_lt"]) & (C > R["eye"]["C_gt"])).double()
    eye = torch.nn.functional.avg_pool2d(eye[None, None], 3, 1, 1)[0, 0].clamp(0, 1)
    eye = eye * sum(grp[k] for k in R["eye"]["groups"]).clamp(0, 1)
    beak = sum(grp[k] for k in R["beak"]["groups"]).clamp(0, 1) * ramp(z, *R["beak"]["z"]) * (1 - eye)
    rest = (1 - eye - beak).clamp_min(0)
    W = {"eye": eye, "beak": beak}
    for r in R["body"]:
        name = r["region"]
        w = sum(grp[k] for k in r["groups"]).clamp(0, 1)
        if r.get("golden") == "only":
            w = w * gold
        elif r.get("golden") == "not":
            w = w * (1 - gold)
        W[name] = W.get(name, 0) + w * rest

    # 4 transfer
    qs = torch.linspace(0, 1, 101, device=dev, dtype=torch.float64)
    out = torch.zeros_like(tex)
    wsum = torch.zeros_like(L)
    rep = {}
    for name, (sc, tc) in spec["transfer"].items():
        mt = np.isin(ct, tc)
        ms = mt & np.isin(cs, sc)
        paired = int(ms.sum()) >= spec.get("minPairs", 200)
        if paired:
            s, t = ls[torch.tensor(ms, device=dev)], lt[torch.tensor(ms, device=dev)]
        else:  # too few aligned pairs (small features such as the eye): unpaired class statistics
            s, t = ls[torch.tensor(np.isin(cs, sc), device=dev)], lt[torch.tensor(mt, device=dev)]
        texture_stats = spec.get("sourceStats", "texture") == "texture"
        if texture_stats:  # region texel statistics (the 3D texture is not the DEF's pixel population)
            s = tex[W[name] > 0.5]
        Lq_s, Lq_t = torch.quantile(s[:, 0], qs), torch.quantile(t[:, 0], qs)
        Ln = torch.from_numpy(np.interp(L.cpu().numpy(), Lq_s.cpu().numpy(), Lq_t.cpu().numpy())).to(dev)
        zc = spec.get("zClamp", 2.5)
        ab = [((tex[..., k] - s[:, k].mean()) / s[:, k].std().clamp_min(1)).clamp(-zc, zc) * t[:, k].std() + t[:, k].mean()
              for k in (1, 2)]
        res = torch.stack([Ln, *ab], -1)
        w = W[name]
        out += w[..., None] * res
        wsum += w
        rep[name] = {"sourceClasses": sc, "targetClasses": tc, "paired": paired, "sourceStats": "texture" if texture_stats else "def", "n": int(ms.sum()) if paired else [len(s), len(t)],
                     "sourceMeanLab": [round(float(v), 2) for v in s.mean(0)], "targetMeanLab": [round(float(v), 2) for v in t.mean(0)],
                     "texelWeight": round(float(w.sum()) / (S * S), 4)}
    o = torch.where((wsum > 1e-3)[..., None], out / wsum.clamp_min(1e-6)[..., None], tex)
    k = spec["keepDark"]
    dark = ramp(-L, -k["L"][1], -k["L"][0]) * ramp(-C, -k["C"][1], -k["C"][0])
    o = o * (1 - dark[..., None]) + tex * dark[..., None]
    rgb = (lab2rgb(o) * 255 + 0.5).clamp(0, 255).to(torch.uint8).cpu().numpy()

    other = [{"image": i, "name": im.get("name"), "carried": "unchanged (not a colour image)"}
             for i, im in enumerate(g.json["images"]) if i != ii]
    report = {"schema": "homm3_unit_recolor_report.v1", "unit": spec["unit"], "specSha256": spec_sha(spec),
              "source": {**spec["source"], "lookDeliveredSha256": row["frozen"]["lookDeliveredGlbSha256"],
                         "sourceBasecolorSha256": sha256_bytes(g.image_bytes(ii))},
              "defPairs": prep, "transfer": rep, "bodyImage": ii, "otherImages": other, "size": S}
    return rgb, report, g


def png_bytes(rgb: np.ndarray) -> bytes:
    bio = io.BytesIO()
    Image.fromarray(rgb).save(bio, format="PNG", optimize=False, compress_level=6)
    return bio.getvalue()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("unit")
    ap.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    ap.add_argument("--out")
    ap.add_argument("--glb", action="store_true", help="also write recolored.glb (debug/board)")
    a = ap.parse_args(argv)
    if a.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable; pass --device cpu explicitly")
    spec = load_spec(a.unit)
    out = Path(a.out) if a.out else DEFAULT_OUT / a.unit
    out.mkdir(parents=True, exist_ok=True)
    with torch.no_grad():
        rgb, report, g = recolor(spec, a.device)
    pb = png_bytes(rgb)
    (out / "basecolor.png").write_bytes(pb)
    report["basecolorSha256"] = sha256_bytes(pb)
    report["device"] = a.device
    if a.glb:
        g.replace_image(report["bodyImage"], pb)
        (out / "recolored.glb").write_bytes(g.to_bytes())
    (out / "recolor_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("unit", "basecolorSha256", "defPairs")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
