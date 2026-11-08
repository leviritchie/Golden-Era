"""Genie texture surgery (coordinator 2026-10-10, option a): h3_genie_upg smartrigged base colour re-graded to the
CGENIE palette. Classes on the source texture (CIE Lab); region by rasterised skin weights + rest height:
 skin (saturated blue, non-head-wrap)  -> CGENIE grey-blue skin
 turban + its hanging tail + hair (red behind/above the head, dark on the head) -> CGENIE dark-blue topknot
 vest (blue, torso band minus arms and open front) -> CGENIE red cloth
 gold trim                              -> CGENIE gold
 smoke tail (below the waist)           -> unchanged (pale blue in both DEFs)
L, a, b by mean shift with std min(src,tgt) (z clamp 2.5; no noise gain); dark low-chroma texels keep the source colour.
usage: genie_recolor.py <out_dir> <upper ramp json> <head ramp json> [<out.glb>]
2026-10-10 h3_genie transplant (coordinator-approved option a): <out.glb> is the source GLB with only its body base
colour image swapped for the re-graded one (geometry, UVs and every other byte unchanged); h3_genie builds from it.
Shipped grade: genie_recolor.py <dir> "[0.38,0.42]" "[0.83,0.85]" artifacts/homm3_mesh_surgery/h3_genie_from_genie_upg.glb"""
import sys, io, json, glob, hashlib
import numpy as np, torch
from pathlib import Path
from PIL import Image
R = Path("V:/games/olden era playtest tweak")
sys.path.insert(0, str(R / "tools/homm3_unit_look")); sys.path.insert(0, str(R / "tools/homm3_prebake"))
import recolor as rc
from glbpatch import Glb
from regions import accessor
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
SRC = R / "artifacts/meshy_downloads/h3_genie_upg_smartrigged.glb"
HEAD = json.loads(sys.argv[3]) if len(sys.argv) > 3 else (0.86, 0.88)
dev = "cuda" if torch.cuda.is_available() else "cpu"
LAB = "V:/homm3_unity_work/Assets/CustomUnits/homm3_lab"

def def_lab(u, d):
    px = []
    for f in sorted(glob.glob(f"{LAB}/{u}/extracted_battle/{d}.dir/02_*.png")):
        a = np.asarray(Image.open(f).convert("RGBA")); m = a[..., 3] > 200
        ys = np.nonzero(m)[0]; top, h = ys.min(), ys.max() - ys.min()
        px.append(a[m & (np.arange(a.shape[0])[:, None] < top + 0.45 * h)][:, :3])
    lab = rc.rgb2lab(torch.tensor(np.concatenate(px) / 255.0)).numpy()
    C = np.hypot(lab[:, 1], lab[:, 2]); h = np.degrees(np.arctan2(lab[:, 2], lab[:, 1]))
    return {"red": lab[(C > 25) & (h < 60) & (h > -30)], "gold": lab[(C > 20) & (h >= 60) & (h < 110)],
            "blue": lab[(C > 15) & ((h < -60) | (h > 200))], "grey": lab[C <= 15]}
T = def_lab("h3_genie", "CGENIE")

g = Glb.load(SRC); ii = g.body_base_color_image()
base = np.asarray(Image.open(io.BytesIO(g.image_bytes(ii))).convert("RGB")); S = base.shape[0]
mi = g.body_mesh_index(); p = g.json["meshes"][mi]["primitives"][0]
pos = accessor(g, p["attributes"]["POSITION"]).astype(np.float64)
uv = accessor(g, p["attributes"]["TEXCOORD_0"]).astype(np.float64)
tris = accessor(g, p["indices"]).reshape(-1, 3).astype(np.int64)
UP = int(np.argmax(np.ptp(pos, 0)))   # tallest axis = up
hgt = (pos[:, UP] - pos[:, UP].min()) / np.ptp(pos[:, UP])
headw = np.clip((hgt - HEAD[0]) / (HEAD[1] - HEAD[0]), 0, 1)
X, Z = pos[:, 0], pos[:, 2]
rmp = lambda x, lo, hi: np.clip((x - lo) / (hi - lo), 0, 1)
# vest: torso band minus the arms and the open front between the lapels (gold trim marks the real edge)
vestg = rmp(hgt, 0.635, 0.65) * rmp(-hgt, -0.815, -0.80) * rmp(-np.abs(X), -0.165, -0.15) * (1 - rmp(Z, 0.02, 0.04) * rmp(-np.abs(X), -0.095, -0.08))
# turban tail hanging behind the head
backg = np.maximum(headw, rmp(-Z, 0.03, 0.05) * rmp(-np.abs(X), -0.13, -0.11) * rmp(hgt, 0.64, 0.66))
img, cov = rc.raster(uv, tris, np.stack([headw, hgt, vestg, backg], 1), S, dev)
img = rc.nearest_fill(img, cov)
head, hgt_t, vestr, backr = img[..., 0].clamp(0, 1), img[..., 1], img[..., 2].clamp(0, 1), img[..., 3].clamp(0, 1)
tex = rc.rgb2lab(torch.tensor(base / 255.0, device=dev)); L, a, b = tex[..., 0], tex[..., 1], tex[..., 2]
C = torch.hypot(a, b); h = torch.rad2deg(torch.atan2(b, a))
ramp = lambda x, lo, hi: ((x - lo) / (hi - lo)).clamp(0, 1)
red = ramp(C, 18, 28) * ((h > -40) & (h < 55)).double()
gold = ramp(C, 14, 24) * ((h >= 55) & (h < 110)).double()
blue = ramp(C, 10, 20) * ((h < -70) | (h > 200)).double()
dark = ramp(-L, -22, -12) * ramp(-C, -14, -6)          # hair / pupils / seams
upper = ramp(hgt_t, *(json.loads(sys.argv[2]) if len(sys.argv) > 2 else (0.52, 0.56)))
wrap = ((red * backr + dark * head).clamp(0, 1))       # turban + its tail + hair
smoke = ramp(L, 48, 55) * (1 - gold)                     # pale smoke texels never take the skin grade
vest = blue * vestr * (1 - head)
skin = blue * (1 - vestr) * (1 - wrap) * (1 - smoke)
W = {"skin": skin * upper, "wrap": wrap * upper, "vest": vest * upper, "gold": gold * upper}
srcpop = {"skin": skin, "wrap": wrap, "vest": vest, "gold": gold}
tgt = {"skin": T["grey"], "wrap": T["blue"], "vest": T["red"], "gold": T["gold"]}
qs = torch.linspace(0, 1, 101, device=dev, dtype=torch.float64)
out = torch.zeros_like(tex); ws = torch.zeros_like(L); rep = {}
for k, w in W.items():
    s = tex[(srcpop[k] * upper) > 0.5]; t = torch.tensor(tgt[k], device=dev)
    Ln = ((L - s[:, 0].mean()) / s[:, 0].std().clamp_min(1)).clamp(-2.5, 2.5) * torch.minimum(t[:, 0].std(), 1.2 * s[:, 0].std()) + t[:, 0].mean()
    ab = [((tex[..., c] - s[:, c].mean()) / s[:, c].std().clamp_min(1)).clamp(-2.5, 2.5) * torch.minimum(t[:, c].std(), s[:, c].std()) + t[:, c].mean() for c in (1, 2)]
    out += w[..., None] * torch.stack([Ln, *ab], -1); ws += w
    rep[k] = {"texels": int(((srcpop[k] * upper) > 0.5).sum()), "src": s.mean(0).cpu().numpy().round(1).tolist(), "tgt": t.mean(0).cpu().numpy().round(1).tolist()}
wsc = ws.clamp(0, 1)
o = torch.where((ws > 1e-3)[..., None], out / ws.clamp_min(1e-6)[..., None], tex)
o = o * wsc[..., None] + tex * (1 - wsc[..., None])
keep = dark * (1 - head)
o = o * (1 - keep[..., None]) + tex * keep[..., None]
rgb = (rc.lab2rgb(o) * 255 + 0.5).clamp(0, 255).to(torch.uint8).cpu().numpy()
Image.fromarray(rgb).save(OUT / "basecolor.png")
Image.fromarray(np.concatenate([base, rgb], 1)).resize((2048, 1024)).save(OUT / "compare.png")
json.dump({"source": str(SRC), "sourceSha256": hashlib.sha256(SRC.read_bytes()).hexdigest(), "defTarget": "CGENIE g02 upper 45%", "regions": rep}, open(OUT / "report.json", "w"), indent=1)
print(json.dumps(rep))
if len(sys.argv) > 4:
    buf = io.BytesIO(); Image.fromarray(rgb).save(buf, format="PNG")
    g.replace_image(ii, buf.getvalue()); Path(sys.argv[4]).write_bytes(g.to_bytes())
    rec = {"schema": "homm3_mesh_surgery.texture_transplant.v1", "unit": "h3_genie", "input": str(SRC.relative_to(R)).replace("\\", "/"),
           "inputSha256": hashlib.sha256(SRC.read_bytes()).hexdigest(), "output": sys.argv[4],
           "outputSha256": hashlib.sha256(Path(sys.argv[4]).read_bytes()).hexdigest(),
           "tool": "tools/homm3_unit_look/genie_recolor.py", "args": sys.argv[2:4], "geometry": "unchanged (base colour image only)",
           "defTarget": "CGENIE g02 upper 45%", "regions": rep}
    json.dump(rec, open(sys.argv[4].replace(".glb", ".surgery.json"), "w"), indent=1)
    print("wrote", sys.argv[4])
