"""town_plan_view.py <faction> <bundle dir> [--out <png>] [--json <path>]: check an installed 3D town against a
practical layout model, read straight from the built asset bundle (meshes are baked in world space).

The model of a painted HoMM3 town seen in 3D:
  - ground: one terrain surface rising gently away from the camera (Mesh_Terrain*);
  - buildings stand ON that ground: the base of each building body meets the terrain under its footprint;
  - buildings are solid volumes: their depth is comparable to their width, with no long tails pulled away from
    the camera (rubber sheets);
  - buildings do not occupy the same ground: robust footprints do not overlap;
  - painted env houses/objects (Mesh_Back_Layer_Objects/Huts/Houses) are thin upright clusters, not sheets reaching
    back; background (Massif/Far/Ridge) lies behind the buildings in front of it.
Each check is reported in metres (scene units) per object, and drawn: painting-view render with labels, a plan view
(top-down, camera at the bottom) and a side elevation, all labelled with the same ids."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import UnityPy
from PIL import Image, ImageDraw, ImageFont
from UnityPy.helpers.MeshHelper import MeshHandler

fac, bdir = sys.argv[1], Path(sys.argv[2])
args = sys.argv[3:]
out = Path(args[args.index("--out") + 1]) if "--out" in args else bdir.parent / "plan_view.png"
jout = Path(args[args.index("--json") + 1]) if "--json" in args else out.with_suffix(".json")
cat = json.loads((bdir / "catalog.json").read_text(encoding="utf-8"))

# --- meshes (world space) ---
meshes = {}
for o in UnityPy.load(str(bdir / cat["bundle"])).objects:
    if o.type.name != "Mesh":
        continue
    m = o.read()
    h = MeshHandler(m)
    h.process()
    v = np.asarray(h.m_Vertices, np.float32).reshape(-1, 3)
    if len(v):
        meshes[m.m_Name] = v

# --- camera (rest pose * aim, pivot at the origin) ---
rc = cat["referenceCamera"]
fr = rc.get("framing", {})


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]], np.float64)


# Homm3TownScene3d.PlaceRoot: root.position = the rest camera, root.rotation = pivot * restPose * aim. Mesh coordinates
# are therefore camera-relative (camera at the origin looking +z); rotate them by the root rotation into a world-up
# frame (yaw removed) for the plan/side views, and project them directly for the painting view.
piv = [0, 0, 0, 1]
try:
    vp = json.loads((Path(__file__).parent / "vanilla_city_camera_pan.json").read_text(encoding="utf-8"))
    src = rc["restPose"].get("sourceScene", "cityHuman2")
    piv = next(c["lookAt"]["worldRot"] for c in vp["cities"] if c["scene"] == src)
except (OSError, StopIteration, KeyError):
    pass
Rroot = qmat(qmul(qmul(piv, rc["restPose"]["localRotation"]), fr.get("aimRotation", [0, 0, 0, 1])))
fw = Rroot[:, 2]
yaw0 = math.atan2(fw[0], fw[2])
Ryaw = np.array([[math.cos(-yaw0), 0, math.sin(-yaw0)], [0, 1, 0], [-math.sin(-yaw0), 0, math.cos(-yaw0)]])
Rw = Ryaw @ Rroot  # mesh -> world-up frame, camera looking along +z in plan
vfov = math.radians(fr.get("fov", rc["fov"]))
aspect = rc.get("aspect", 16 / 9)


def project(p, W, H):
    c = np.asarray(p, np.float64)  # mesh space = camera space
    t = math.tan(vfov / 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        u = (c[..., 0] / c[..., 2] / (t * aspect) * 0.5 + 0.5) * W
        v = (0.5 - c[..., 1] / c[..., 2] / t * 0.5) * H
    return u, v, c[..., 2]


raw = meshes
meshes = {n: (v.astype(np.float64) @ Rw.T).astype(np.float32) for n, v in raw.items()}
cpos = np.zeros(3)
crot = np.eye(3)

# --- ground heightmap from the terrain pieces (median y per 1 m cell) ---
terr = np.concatenate([v for n, v in meshes.items() if n.startswith("Mesh_Terrain") or n.startswith("Mesh_Back_Terrain")]
                      or [np.zeros((1, 3), np.float32)])
CELL = 1.0
gx0, gz0 = terr[:, 0].min(), terr[:, 2].min()
ix = ((terr[:, 0] - gx0) / CELL).astype(int)
iz = ((terr[:, 2] - gz0) / CELL).astype(int)
gw, gh = ix.max() + 1, iz.max() + 1
gsum = np.zeros((gh, gw))
gcnt = np.zeros((gh, gw))
np.add.at(gsum, (iz, ix), terr[:, 1])
np.add.at(gcnt, (iz, ix), 1)
ground = np.where(gcnt > 0, gsum / np.maximum(gcnt, 1), np.nan)


def ground_at(x, z, r=1.5):
    i0, i1 = int((x - r - gx0) / CELL), int((x + r - gx0) / CELL) + 1
    j0, j1 = int((z - r - gz0) / CELL), int((z + r - gz0) / CELL) + 1
    win = ground[max(j0, 0):max(j1, 0), max(i0, 0):max(i1, 0)]
    return float(np.nanmedian(win)) if win.size and np.isfinite(win).any() else float("nan")


# support surfaces: everything a building can stand on (terrain, hills/massif/ridges/cliffs, outer world); not the
# painted objects layer, props, near clutter or the sky
OBJ_KEYS = ("Objects", "Huts", "Houses")
# (SSR water planes count: fortress/cove buildings stand in the water; near foliage layers do not carry buildings)
sup = np.concatenate([v for n, v in meshes.items() if (n.startswith("Mesh_Terrain") or n.startswith("Mesh_Back_")
                       or n.startswith("Mesh_Outer") or n.startswith("Fx_SsrWater")) and not any(k in n for k in OBJ_KEYS)
                      and "boulders" not in n and "Layer_Near" not in n])


def support_at(fp, base, ht):
    m = (sup[:, 0] >= fp[0]) & (sup[:, 0] <= fp[2]) & (sup[:, 2] >= fp[1]) & (sup[:, 2] <= fp[3])
    y = sup[m, 1]
    y = y[y <= base + 0.25 * max(ht, 1.0)]
    return float(np.percentile(y, 90)) if len(y) > 10 else float("nan")


from scipy.spatial import cKDTree  # noqa: E402

sup_tree = cKDTree(sup[:, [0, 2]])
# only buildings painted flying (cloud/air dwellings) may hang in the air; everything else rests on something
FLYING = {"castle": ("tbcsdw_6",), "tower": ("tbtwholy",)}


def base_contact(vr, v, dist):
    """walk the painted base line (lowest screen px per column of the building) and test, in 3D, whether each base
    point rests on a support surface below it; returns (fraction in contact, fraction hanging, fraction sunk)"""
    su, sv, _ = project(vr, 1920, 1080)
    ok = np.isfinite(su) & np.isfinite(sv)
    if ok.sum() < 50:
        return None
    lo_u, hi_u = np.percentile(su[ok], 3), np.percentile(su[ok], 97)
    nb = 24
    b = np.clip(((su - lo_u) / max(hi_u - lo_u, 1e-6) * nb).astype(int), 0, nb - 1)
    tol = max(0.3, 0.012 * dist)
    res = []
    for k in range(nb):
        m = ok & (b == k) & (su >= lo_u) & (su <= hi_u)
        if m.sum() < 5:
            continue
        idx = np.nonzero(m)[0]
        i = idx[np.argsort(sv[idx])[-max(1, len(idx) // 50):]]  # lowest 2% on screen in this column
        pnt = np.median(v[i], 0)
        nn = sup_tree.query_ball_point([pnt[0], pnt[2]], r=max(0.5, 0.01 * dist))
        ys = sup[nn, 1] if nn else np.empty(0)
        below = ys[ys <= pnt[1] + 2 * tol]
        if not len(below):
            res.append("hang")
            continue
        top = below.max()
        d = pnt[1] - top
        res.append("ok" if abs(d) <= tol else ("hang" if d > 0 else "sunk"))
    if not res:
        return None
    n = len(res)
    return res.count("ok") / n, res.count("hang") / n, res.count("sunk") / n


# --- buildings ---
rows = []
for L in cat["layers"]:
    lid = L["layerId"]
    body = [meshes[p] for p in L["pieces"] if p in meshes and (p.startswith("Mesh_Body") and "Rest" not in p)]
    if not body:
        continue
    v = np.concatenate(body)
    vr = np.concatenate([raw[p] for p in L["pieces"] if p in raw and (p.startswith("Mesh_Body") and "Rest" not in p)])
    su, sv, _ = project(vr, 1920, 1080)
    sbox = [float(np.percentile(su, 5)), float(np.percentile(sv, 5)), float(np.percentile(su, 95)), float(np.percentile(sv, 95))]
    lo, hi = np.percentile(v, 5, 0), np.percentile(v, 95, 0)
    full_lo, full_hi = v.min(0), v.max(0)
    w, dpt, ht = hi[0] - lo[0], hi[2] - lo[2], hi[1] - lo[1]
    cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
    base = float(np.percentile(v[:, 1], 2))
    g = support_at([lo[0], lo[2], hi[0], hi[2]], base, ht)
    dist = float(math.hypot(cx - cpos[0], cz - cpos[2]))
    r = dict(id=lid, x=round(float(cx), 2), z=round(float(cz), 2), dist=round(dist, 1), width=round(float(w), 2),
             depth=round(float(dpt), 2), height=round(float(ht), 2), base=round(base, 2), ground=round(g, 2),
             gap=round(base - g, 2) if math.isfinite(g) else None,
             tail=round(float((full_hi[2] - full_lo[2]) - dpt), 2),
             fp=[float(lo[0]), float(lo[2]), float(hi[0]), float(hi[2])], top=float(hi[1]), sbox=sbox)
    issues = []
    r["sky"] = any(lid.startswith(k) for k in FLYING.get(fac, ()))
    bc = base_contact(vr, v, dist)
    r["contact"] = [round(x, 2) for x in bc] if bc else None
    if r["sky"]:
        pass
    elif r["gap"] is None:
        issues.append("no ground under it")
    elif r["gap"] > max(ht, 3.0):
        issues.append(f"hangs in the air {r['gap']:.1f} m above anything")
    elif abs(r["gap"]) > max(0.3, 0.08 * ht):
        issues.append(f"floating {r['gap']:.1f} m" if r["gap"] > 0 else f"buried {-r['gap']:.1f} m")
    if not r["sky"] and bc and bc[0] < 0.6:
        issues.append(f"base line on ground {bc[0]:.0%} (hangs {bc[1]:.0%}, sunk {bc[2]:.0%})")
    if dpt > 1.5 * max(w, 0.5) and dpt > 3:
        issues.append("deep")
    if w > 1.0 and dpt < 0.3 * w:
        issues.append(f"flat card (depth {dpt:.1f} m vs width {w:.1f} m)")
    if r["tail"] > max(3.0, dpt):
        issues.append("tail")
    r["issues"] = issues
    rows.append(r)
for a in rows:
    for b in rows:
        if a is b or a["id"] >= b["id"] or a.get("sky") or b.get("sky"):
            continue
        ix0, iz0 = max(a["fp"][0], b["fp"][0]), max(a["fp"][1], b["fp"][1])
        ix1, iz1 = min(a["fp"][2], b["fp"][2]), min(a["fp"][3], b["fp"][3])
        inter = max(0, ix1 - ix0) * max(0, iz1 - iz0)
        sa = (a["fp"][2] - a["fp"][0]) * (a["fp"][3] - a["fp"][1])
        sb = (b["fp"][2] - b["fp"][0]) * (b["fp"][3] - b["fp"][1])
        # buildings painted in the same place (upgrade tiers, grouped parts) share ground by design; only buildings
        # painted apart must not stand on the same ground
        sx = max(0, min(a["sbox"][2], b["sbox"][2]) - max(a["sbox"][0], b["sbox"][0])) *             max(0, min(a["sbox"][3], b["sbox"][3]) - max(a["sbox"][1], b["sbox"][1]))
        ssa = (a["sbox"][2] - a["sbox"][0]) * (a["sbox"][3] - a["sbox"][1])
        ssb = (b["sbox"][2] - b["sbox"][0]) * (b["sbox"][3] - b["sbox"][1])
        if inter > 0.3 * min(sa, sb) and sx < 0.5 * min(ssa, ssb):
            a["issues"].append(f"overlaps {b['id']}")
            b["issues"].append(f"overlaps {a['id']}")

# --- env pieces: distance range; objects layers: depth thickness along each camera ray (1 deg sectors) ---
env = {}
for n in cat["environment"]["pieces"]:
    if n not in meshes or n.startswith("Sky_"):
        continue
    v = meshes[n]
    d = np.hypot(v[:, 0] - cpos[0], v[:, 2] - cpos[2])
    e = dict(n=int(len(v)), distP5P50P95=[round(float(x), 1) for x in np.percentile(d, [5, 50, 95])])
    if any(k in n for k in ("Objects", "Huts", "Houses")):
        az = np.degrees(np.arctan2(v[:, 0] - cpos[0], v[:, 2] - cpos[2]))
        th = []
        for a0 in range(int(az.min()), int(az.max()) + 1):
            s = d[(az >= a0) & (az < a0 + 1)]
            if len(s) > 50:
                th.append(float(np.percentile(s, 90) - np.percentile(s, 10)))
        e["rayThicknessP50P90Max"] = [round(float(x), 1) for x in np.percentile(th, [50, 90, 100])] if th else None
    env[n] = e
bfar = {r["id"]: r["dist"] + r["depth"] / 2 for r in rows}
for n, e in env.items():
    if any(k in n for k in ("Massif", "Far", "Ridge")):
        v = meshes[n]
        az = np.degrees(np.arctan2(v[:, 0] - cpos[0], v[:, 2] - cpos[2]))
        d = np.hypot(v[:, 0] - cpos[0], v[:, 2] - cpos[2])
        el = np.degrees(np.arctan2(v[:, 1] - cpos[1], d))
        front = []
        for r in rows:
            a0 = math.degrees(math.atan2(r["fp"][0] - cpos[0], r["fp"][3] - cpos[2]))
            a1 = math.degrees(math.atan2(r["fp"][2] - cpos[0], r["fp"][1] - cpos[2]))
            etop = math.degrees(math.atan2(r["top"] - cpos[1], r["dist"]))
            ebase = math.degrees(math.atan2(r["base"] - cpos[1], r["dist"]))
            sel = (az >= min(a0, a1)) & (az <= max(a0, a1)) & (el <= etop) & (el >= ebase)
            if sel.sum() > 30 and np.percentile(d[sel], 10) < r["dist"] - r["depth"] / 2:
                front.append(r["id"])
        e["inFrontOfBuildings"] = front

# --- figure: painting-view render | plan | side ---
W, H = 1920, 1080
rend = bdir.parent / "renders" / "full3d_full.png"
pv = Image.open(rend).convert("RGB").resize((W, H)) if rend.is_file() else Image.new("RGB", (W, H), (40, 40, 40))
d0 = ImageDraw.Draw(pv)
try:
    font = ImageFont.truetype("arial.ttf", 18)
    fsm = ImageFont.truetype("arial.ttf", 14)
except OSError:
    font = fsm = ImageFont.load_default()
for i, r in enumerate(rows):
    u, v, z = project(Rw.T @ np.array([r["x"], r["base"] + r["height"] / 2, r["z"]]), W, H)
    if z > 0:
        col = (255, 60, 60) if r["issues"] else (255, 255, 255)
        d0.text((float(u) - 8, float(v) - 9), str(i), fill=col, font=font, stroke_width=2, stroke_fill=(0, 0, 0))

PW, PH = 1920, 1400
plan = Image.new("RGB", (PW, PH), (24, 26, 30))
dp = ImageDraw.Draw(plan)
xs = [r["fp"][0] for r in rows] + [r["fp"][2] for r in rows] + [cpos[0]]
zs = [r["fp"][1] for r in rows] + [r["fp"][3] for r in rows] + [cpos[2]]
x0, x1 = min(xs) - 25, max(xs) + 25
z0, z1 = min(zs) - 10, max(zs) + 40
sc = min(PW / (x1 - x0), PH / (z1 - z0))


def P(x, z):
    return ((x - x0) * sc, PH - (z - z0) * sc)


# ground height as shading, with 1 m contours
gy = ground.copy()
lo_, hi_ = np.nanpercentile(gy, 2), np.nanpercentile(gy, 98)
for j in range(gh):
    for i in range(gw):
        y = gy[j, i]
        if not math.isfinite(y):
            continue
        xa, za = gx0 + i * CELL, gz0 + j * CELL
        if not (x0 <= xa <= x1 and z0 <= za <= z1):
            continue
        t = (y - lo_) / max(hi_ - lo_, 1e-6)
        c = int(50 + 120 * min(max(t, 0), 1))
        if abs(y - round(y)) < 0.06:
            c += 40
        a, b = P(xa, za + CELL)
        dp.rectangle((a, b, a + CELL * sc + 1, b + CELL * sc + 1), fill=(c // 2, c, c // 2))
# env objects layer points
for n, v in meshes.items():
    if n in env and any(k in n for k in ("Objects", "Huts", "Houses")):
        s = v[:: max(1, len(v) // 40000)]
        for x, _, z in s:
            if x0 <= x <= x1 and z0 <= z <= z1:
                a, b = P(x, z)
                dp.point((a, b), fill=(230, 170, 60))
# camera + frustum
ca, cb = P(cpos[0], cpos[2])
yaw = 0.0
hf = math.atan(math.tan(vfov / 2) * aspect)
for s in (-1, 1):
    ex, ez = cpos[0] + 400 * math.sin(yaw + s * hf), cpos[2] + 400 * math.cos(yaw + s * hf)
    dp.line((ca, cb, *P(ex, ez)), fill=(120, 160, 255), width=2)
dp.ellipse((ca - 6, cb - 6, ca + 6, cb + 6), fill=(120, 160, 255))
for i, r in enumerate(rows):
    a, b = P(r["fp"][0], r["fp"][3])
    c_, d_ = P(r["fp"][2], r["fp"][1])
    col = (255, 70, 70) if r["issues"] else (240, 240, 240)
    dp.rectangle((a, b, c_, d_), outline=col, width=2)
    dp.text((a + 2, b + 1), str(i), fill=col, font=fsm)
dp.text((10, 10), f"{fac} plan view (camera at bottom, blue = view frustum; green = ground height, bright lines = 1 m contours; "
                  f"orange = env objects layer; boxes = building footprints p5-p95, red = fails the layout model)", fill=(255, 255, 255), font=fsm)

SW, SH = 1920, 520
side = Image.new("RGB", (SW, SH), (24, 26, 30))
ds = ImageDraw.Draw(side)
ys = [r["base"] for r in rows] + [r["top"] for r in rows] + [cpos[1]]
y0, y1 = min(ys) - 3, max(ys) + 3
ss = min(SW / (z1 - z0), SH / (y1 - y0))


def S(z, y):
    return ((z - z0) * ss, SH - (y - y0) * ss)


# ground profile: median terrain y per z column within the frustum
for j in range(gh):
    za = gz0 + j * CELL
    if not (z0 <= za <= z1):
        continue
    row = ground[j]
    if np.isfinite(row).any():
        yv = float(np.nanmedian(row))
        a, b = S(za, yv)
        ds.rectangle((a, min(max(b, 0), SH), a + CELL * ss + 1, SH), fill=(40, 80, 40))
for i, r in enumerate(rows):
    a, b = S(r["fp"][1], r["top"])
    c_, d_ = S(r["fp"][3], r["base"])
    col = (255, 70, 70) if r["issues"] else (240, 240, 240)
    ds.rectangle((a, b, c_, d_), outline=col, width=2)
    gpx = S(r["z"], r["ground"])[1] if r["gap"] is not None else None
    if gpx is not None:
        ds.line(((a + c_) / 2 - 6, gpx, (a + c_) / 2 + 6, gpx), fill=(120, 255, 120), width=2)
    ds.text((a + 2, b - 16), str(i), fill=col, font=fsm)
a, b = S(cpos[2], cpos[1])
ds.ellipse((a - 6, b - 6, a + 6, b + 6), fill=(120, 160, 255))
ds.text((10, 10), "side elevation (camera at left): boxes = buildings (base to top), green tick = terrain under the footprint, "
                  "dark green = median ground profile", fill=(255, 255, 255), font=fsm)

TW = 1920
lines = [f"{i:>2} {r['id']:<22} dist {r['dist']:>6.1f}  w {r['width']:>5.1f} d {r['depth']:>5.1f} h {r['height']:>5.1f}  "
         f"gap {r['gap'] if r['gap'] is not None else 'n/a':>6}  tail {r['tail']:>5.1f}  {'(sky object) ' if r.get('sky') else ''}{', '.join(r['issues'])}"
         for i, r in enumerate(rows)]
for n, e in env.items():
    lines.append(f"   env {n:<28} dist p5/p50/p95 {e['distP5P50P95']}"
                 + (f"  ray thickness p50/p90/max {e['rayThicknessP50P90Max']}" if e.get("rayThicknessP50P90Max") else "")
                 + (f"  IN FRONT OF {e['inFrontOfBuildings']}" if e.get("inFrontOfBuildings") else ""))
TH = 22 + 17 * len(lines)
tab = Image.new("RGB", (TW, TH), (16, 16, 18))
dt = ImageDraw.Draw(tab)
try:
    mono = ImageFont.truetype("consola.ttf", 14)
except OSError:
    mono = fsm
bad = [bool(r["issues"]) for r in rows] + [bool(e.get("inFrontOfBuildings")) for e in env.values()]
for k, ln in enumerate(lines):
    dt.text((10, 8 + 17 * k), ln, fill=(255, 110, 110) if bad[k] else (220, 220, 220), font=mono)

# flagged-building gallery: the render around where the building is painted + its own side profile vs support
flag = [(i, r) for i, r in enumerate(rows) if r["issues"]]
GW, GH = 480, 300
gal = Image.new("RGB", (W, GH * ((len(flag) + 3) // 4) if flag else 1), (10, 10, 12))
dg = ImageDraw.Draw(gal)
for k, (i, r) in enumerate(flag):
    gx, gy = (k % 4) * GW, (k // 4) * GH
    b = r["sbox"]
    pad = max(b[2] - b[0], b[3] - b[1]) * 0.6 + 30
    crop = pv.crop((int(b[0] - pad), int(b[1] - pad), int(b[2] + pad), int(b[3] + pad)))
    crop.thumbnail((GW - 150, GH - 40))
    gal.paste(crop, (gx + 4, gy + 30))
    # mini side profile: support surface under the footprint (green) and the body (box), same scale
    fp = r["fp"]
    m = (sup[:, 0] >= fp[0]) & (sup[:, 0] <= fp[2]) & (sup[:, 2] >= fp[1] - 3) & (sup[:, 2] <= fp[3] + 3)
    zz, yy = sup[m, 2], sup[m, 1]
    zlo, zhi = fp[1] - 3, fp[3] + 3
    ylo = min(r["base"], float(np.min(yy)) if len(yy) else r["base"]) - 1
    yhi = r["top"] + 1
    k2 = min(140 / max(zhi - zlo, 1), (GH - 50) / max(yhi - ylo, 1))
    ox, oy = gx + GW - 145, gy + GH - 10
    for z_, y_ in zip(zz[:: max(1, len(zz) // 3000)], yy[:: max(1, len(yy) // 3000)]):
        dg.point((ox + (z_ - zlo) * k2, oy - (y_ - ylo) * k2), fill=(80, 200, 80))
    dg.rectangle((ox + (fp[1] - zlo) * k2, oy - (r["top"] - ylo) * k2, ox + (fp[3] - zlo) * k2, oy - (r["base"] - ylo) * k2),
                 outline=(255, 90, 90), width=2)
    dg.text((gx + 4, gy + 6), f"{i} {r['id']}: {', '.join(r['issues'])}", fill=(255, 200, 120), font=fsm)
    dg.text((ox, gy + 30), "side: camera left", fill=(150, 150, 150), font=fsm)

S_ = Image.new("RGB", (W, H + PH + SH + TH + gal.size[1]), (0, 0, 0))
S_.paste(gal, (0, H + PH + SH + TH))
S_.paste(pv, (0, 0))
S_.paste(plan, (0, H))
S_.paste(side, (0, H + PH))
S_.paste(tab, (0, H + PH + SH))
out.parent.mkdir(parents=True, exist_ok=True)
S_.save(out, quality=88) if out.suffix.lower() in (".jpg", ".jpeg") else S_.save(out)
for r in rows:
    r.pop("fp"); r.pop("sbox")
json.dump({"faction": fac, "bundle": str(bdir), "camera": cpos.tolist(), "buildings": rows, "env": env,
           "failing": [r["id"] for r in rows if r["issues"]]}, open(jout, "w"), indent=1)
print(json.dumps({"faction": fac, "buildings": len(rows), "failing": {r["id"]: r["issues"] for r in rows if r["issues"]},
                  "envInFront": {n: e["inFrontOfBuildings"] for n, e in env.items() if e.get("inFrontOfBuildings")},
                  "out": str(out)}))
