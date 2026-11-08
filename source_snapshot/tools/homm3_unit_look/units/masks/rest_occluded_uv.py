"""UV mask of a chest-panel surgery's freed sleeves and rebuilt chest: the rest-occluded texels that the rest-pose light
bake turns black once the arms move (h3_zealot chest_c3, h3_monk chest_c1). Feeds a baked `rest_occlusion_fill` bakedGlow.
Usage: python rest_occluded_uv.py <unit> <surgery.glb> <out.png>
Run against the pre-look canonical GLB (fleet_rebuild output) so texel luminance is the unlit albedo."""
import sys, io, json, numpy as np
R = "V:/games/olden era playtest tweak/"
sys.path.insert(0, R + "tools/homm3_glb_patch"); sys.path.insert(0, R + "tools/homm3_def_retarget_delivery")
import patch_glb as P
from stride_match_glb import Glb as G
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree
U, SRG, OUT = sys.argv[1:4]
g = P.Glb(open(R + f"artifacts/homm3_def_retarget/{U}/{U}_def_retarget.glb", "rb").read()); b = P.Body(g); js = g.json; pr = b.prim
mat = js["materials"][pr.get("material", 0)]; img = js["images"][js["textures"][mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]]["source"]]
bv = js["bufferViews"][img["bufferView"]]; T = np.asarray(Image.open(io.BytesIO(bytes(g.bin[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]))).convert("RGB"), float) / 255
UV = g.read(pr["attributes"]["TEXCOORD_0"]).astype(float); F = b.F; h, w = T.shape[:2]
m = G.load(R + SRG); sp = m.json["meshes"][0]["primitives"][0]
V = m.read(sp["attributes"]["POSITION"]).astype(float); SF = m.read(sp["indices"]).astype(int).reshape(-1, 3)
rec = json.load(open(R + SRG + ".surgery.json"))
kind = np.zeros(len(SF), int); kind[rec["armFaceIdx"]] = 1; kind[rec["panelFaceIdx"]] = 2
d, i = cKDTree(V[SF].mean(1)).query(b.V[F].mean(1)); k = kind[i]
armv = V[np.unique(SF[rec["armFaceIdx"]].ravel())]
C = b.V[F].mean(1); near = cKDTree(armv).query(C)[0] < 0.06
tgt = (k > 0) | ((k == 0) & near & (C[:, 1] > 0.95) & (C[:, 1] < 1.40))
lin = np.where(T <= 0.04045, T / 12.92, ((T + 0.055) / 1.055) ** 2.4); L = lin.mean(2)
# the lit cloth colour: median of the arm block's texels brighter than the 60th percentile
uvc = UV[F].mean(1) % 1; px = np.minimum((uvc[:, 0] * w).astype(int), w - 1); py = np.minimum((uvc[:, 1] * h).astype(int), h - 1)
fl = L[py, px]; armf = k == 1
lit = armf & (fl > np.percentile(fl[armf], 60))
rgb_lin = np.median(lin[py[lit], px[lit]], 0); Lt = rgb_lin.mean()
reg = Image.new("L", (w, h), 0); dr = ImageDraw.Draw(reg)
for f in np.nonzero(tgt)[0]:
    dr.polygon([(float(u % 1 * w), float(v % 1 * h)) for u, v in UV[F[f]]], fill=255, outline=255)
reg = np.asarray(reg) > 0
wt = np.where(reg, np.clip((Lt - L) / Lt, 0, 1), 0)
Image.fromarray((wt * 255).round().astype(np.uint8)).save(OUT)
srgb = np.where(rgb_lin <= 0.0031308, rgb_lin * 12.92, 1.055 * rgb_lin ** (1 / 2.4) - 0.055)
print("target faces", int(tgt.sum()), "texels", int(reg.sum()), "lifted >0.5", int((wt > 0.5).sum()), "rgb srgb", srgb.round(3).tolist())
