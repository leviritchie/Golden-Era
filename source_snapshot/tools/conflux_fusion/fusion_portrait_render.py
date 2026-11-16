"""Elemental Fusion unit portraits: plain lab renders of each fused unit, framed as a vanilla Olden Era close-up.

    python tools/conflux_fusion/fusion_portrait_render.py stage1 [--only SID,..] [--batch 35]
    python tools/conflux_fusion/fusion_portrait_render.py stage2 [--only SID,..]   # needs READY_FOR_PORTRAITS.txt
    python tools/conflux_fusion/fusion_portrait_render.py sheets                  # contact sheets + manifest only
    python tools/conflux_fusion/fusion_portrait_render.py setup                   # (re)create the private Unity project

What a portrait shows is what the unit is in battle, through the runtime's own route (the fusion composite lab,
V:/olden_port_work/elemental_fusion/v4/fusion_v4_shared_lab.py): the HOST's shipped AssetBundle (mesh, skeleton,
Unit_Idle clip) posed at a fixed idle frame, the fused crest bundle under Head, the battle_emission row (body + crest
emission maps, colour, blink), the battle_body_overlay row (stock VfxUber material, its _Mask and tint from the
catalog, crest copy) and the always-on vanilla-style particle layers (host idle rows, guest L3, reaction L4) after
a 2 s warm-up. Shaders are the lab replicas (Homm3Vfx*Replica); bloom is the lab's PPv2-like pass.

Camera: orthographic, 12 deg down, turned 35 deg off the battle view toward the face (the vanilla hex_portraits
3/4 view), whole body rendered at 2048 px; Python then crops a square around the head (Head bone, crest box and
silhouette top from the projection sidecar), scales it to 512x512 RGBA with transparent background and draws the
vanilla black silhouette outline. No generative model, no repaint: every pixel is the render, a resample, or the
outline.

Inputs are read-only: bundles and homm3_mesh_fx from the installed GE plugin folder (copied to scratch first; the
game process is never touched), pair specs from v4/ship, recipes from v3/recipes + artifacts/vanilla_vfx_style.
Outputs: V:/olden_port_work/elemental_fusion/portraits_render/<sid>.png, contact_sheet_stage{1,2}.png,
portraits_manifest.json. The private Unity project is portraits_render/unity_project (never the shared lab).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[2]
EF = Path("V:/olden_port_work/elemental_fusion")
OUT = EF / "portraits_render"
PROJECT = OUT / "unity_project"
STAGE = OUT / "stage"
WORK = OUT / "work"
GE = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/BepInEx/plugins/OfflineUnlockMod")
READY = EF / "stage2/visuals/READY_FOR_PORTRAITS.txt"
S2REC = EF / "stage2/visuals/recipes"   # stage-2 recipes (read-only), keyed by the full childPath
CONFIG = REPO / "custom_factions/conflux_fusion/fusion_config.json"
UNITY = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe")
AROOT = "Assets/Homm3PortraitLab/data"
DEST = PROJECT / AROOT
CS_SRC = REPO / "tools/conflux_fusion/unity/Homm3FusionPortraitLab.cs"
SHADERS = ["Homm3VfxUberReplica", "Homm3VfxHexLitEmissionReplica", "Homm3VfxDisappearanceReplica",
           "Homm3VfxWaterFireStylizedReplica", "Homm3VfxFresnelReplica", "Homm3VfxHexLitReplicaPoint", "Homm3VfxDepthOnly"]

RES = 2048            # full-body render; the head crop is resampled down to SIZE
SIZE = 512            # = existing homm3_portraits/h3_fusion_*.png
FPS = 24
PICK = 9              # Unit_Idle frame index saved (t = 10/24 s), after WARMUP
WARMUP = 2.0
ELEV = 12.0
YAW = 35.0
PROJ_BONES = ["Head", "Neck", "Spine2", "Spine1", "Spine", "Hips"]
# Portraits show the unit the way vanilla portraits do: body, crest, emission/overlay and the host/guest idle VFX.
# Reaction (rx_) and stage-2 themed (s2_) particle rows stay in battle but are left out here: in a head close-up they
# cover the face (water spray, black-hole spike, meteor trail).
PORTRAIT_SKIP_PREFIXES = ("rx_", "s2_")
# Cloud-bodied air hosts have no distinct head; a head crop is a pale blob, so frame them wider.
WIDE_CROP = {"h3_fusion_air_": 2.0}

sys.path.insert(0, str(REPO / "tools/homm3_vfx"))
sys.path.insert(0, str(EF / "v4"))


def _mods():
    """The lab helper modules (read-only use): fusion_fx (pairs, names), vanilla_style_lab (recipes, bloom),
    fusion_v3 (fusion recipe lookup, lab_effects) and fusion_v4_lab (lab_layers)."""
    import fusion_v4_lab as L  # noqa: E402  (imports fusion_v3 and fusion_fx)
    return L, L.V3M, L.FX, L.VL


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def stage_file(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.stat().st_size != src.stat().st_size or dst.stat().st_mtime < src.stat().st_mtime:
        shutil.copy2(src, dst)


# ------------------------------------------------------------------ project
def setup_project():
    src = REPO / "oldenera_factions"
    (PROJECT / "Packages").mkdir(parents=True, exist_ok=True)
    for f in ("manifest.json", "packages-lock.json"):
        if not (PROJECT / "Packages" / f).exists():
            shutil.copy2(src / "Packages" / f, PROJECT / "Packages" / f)
    if not (PROJECT / "ProjectSettings").exists():
        shutil.copytree(src / "ProjectSettings", PROJECT / "ProjectSettings")
    for s in SHADERS:
        stage_file(REPO / f"tools/homm3_vfx/unity/{s}.shader", PROJECT / f"Assets/Homm3VfxLab/Shaders/{s}.shader")
    stage_file(CS_SRC, PROJECT / "Assets/Editor/Homm3PortraitLab/Homm3FusionPortraitLab.cs")


def stage_material_lib():
    """Union of the fusion recipe lib (v3/recipes) and the vanilla-style lib (artifacts/vanilla_vfx_style/recipes)."""
    L, V3M, FX, VL = _mods()
    libs = [(V3M.REC, json.loads((V3M.REC / "materials.json").read_text(encoding="utf-8"))),
            (VL.REC, json.loads((VL.REC / "materials.json").read_text(encoding="utf-8")))]
    if (S2REC / "materials.json").exists():
        libs.append((S2REC, json.loads((S2REC / "materials.json").read_text(encoding="utf-8"))))
    mats, texs, meshes = {}, {}, {}
    for rec, lib in libs:
        for m in lib["materials"]:
            mats.setdefault(m["name"], m)
        for k, t in lib["textures"].items():
            if k not in texs:
                texs[k] = t
                stage_file(rec / t["file"], DEST / t["file"])
        for k, m in lib["meshes"].items():
            if k not in meshes:
                meshes[k] = m
                stage_file(rec / m["file"], DEST / (m["file"] + ".txt"))
    out = {"materials": list(mats.values()),
           "textures": [{"name": k, "file": v["file"], "sRGB": v["sRGB"], "mips": v["mips"], "wrapU": v["wrapU"],
                         "wrapV": v["wrapV"]} for k, v in texs.items()],
           "meshes": [{"name": k, "file": v["file"] + ".txt"} for k, v in meshes.items()]}
    WORK.mkdir(parents=True, exist_ok=True)
    p = WORK / "lab_materials.json"
    p.write_text(json.dumps(out), encoding="utf-8")
    return p


# ------------------------------------------------------------------ unit facts
_CAT = None


def catalog_rows(sid):
    global _CAT
    if _CAT is None:
        _CAT = {}
        for e in json.loads((GE / "homm3_mesh_fx/catalog.json").read_text(encoding="utf-8"))["entries"]:
            o = e.get("origin", "")
            if o.startswith("elemental_fusion:"):
                _CAT.setdefault(o.split(":", 1)[1], []).append(e)
    return _CAT.get(sid, [])


def names():
    c = json.loads(CONFIG.read_text(encoding="utf-8"))
    out = {p["fused"]: p["name"] for p in c["pairs"]}
    out.update({r["fused"]: r["name"] for r in c["recipes"]})
    return out, [p["fused"] for p in c["pairs"]], [r["fused"] for r in c["recipes"]]


def layer_effects(layers, unit_for_reach, yaw, prefix, notes):
    """Lab effects for vanilla-style layers: the fusion recipe route first (orient body handled), else the
    vanilla-style route; a layer with no recipe is skipped and noted (never faked)."""
    L, V3M, FX, VL = _mods()
    out = []
    for l in layers:
        if l.get("type", "vanillaParticles") != "vanillaParticles":
            continue
        try:
            out += V3M.lab_effects(L.lab_layers([l]), yaw, prefix)
            continue
        except (SystemExit, KeyError, ValueError, FileNotFoundError, IndexError):
            pass
        try:
            for e in VL.spec_layer_effects(unit_for_reach, {"layers": [l]}):
                e["id"] = prefix + e["id"]
                out.append(e)
        except (SystemExit, KeyError, ValueError, FileNotFoundError, IndexError) as ex:
            try:
                out += s2_effects(l, prefix)
                continue
            except (SystemExit, KeyError, ValueError, FileNotFoundError, IndexError) as ex2:
                ex = ex2
            notes.append(f"{prefix}{l.get('id')}: no lab recipe ({str(ex)[:80]})")
    return out


def s2_effects(l, prefix):
    """The stage-2 recipe dir (full-childPath keys), same effect fields as vanilla_style_lab.spec_layer_effects."""
    L, V3M, FX, VL = _mods()
    from vanilla_ps_recipe import recipe_key
    src = l["source"]
    rp = S2REC / (recipe_key(f"{src['resPath']}:{src['childPath']}") + ".json")
    if not rp.is_file():
        raise SystemExit(f"no recipe {rp.name}")
    rec = json.loads(rp.read_text(encoding="utf-8"))
    pre = "Transform/" if src["childPath"].split("/")[-1] == "Transform" else ""
    keep = [VL.node_index_in(rec, (pre + k) if k else pre.rstrip("/")) for k in src["keepNodes"]]
    return [{"id": f"{prefix}{l['id']}_{b}", "recipeFile": str(rp), "bone": b, "pos": [0, 0, 0], "rot": [0, 0, 0, 1],
             "rootWorldRot": [], "recolor": list(l.get("recolor") or []), "recolorMultiply": False,
             "scale": float(l["scale"]), "rateMul": float(l.get("rateMul", 1.0)), "keepRecipeRoot": False,
             "loopAll": bool(l.get("loop")), "alwaysOn": True, "emitUp": l.get("orient") == "emitUp",
             "zeroChildPos": bool(l.get("zeroChildPositions")),
             "anchorNode": VL.node_index_in(rec, pre + l["anchorNode"]) if l.get("anchorNode") else -1,
             "detachOnTrigger": False, "keepPS": keep, "triggers": [], "stops": []} for b in l["bones"]]


def overlay_from_row(row, sid):
    L, V3M, FX, VL = _mods()
    src = row["source"]
    rp, _ = V3M.recipe_for({"resPath": src["nativeResPath"], "childPath": src["rendererPath"]})
    mm = json.loads(rp.read_text(encoding="utf-8"))["nodes"][0]["meshMaterials"]
    return {"id": "fusion_overlay", "material": mm[src["materialIndex"]], "clip": "", "start": 0.0, "end": 0.0,
            "always": row.get("trigger", {}).get("mode", "always") == "always",
            "colors": [{"name": c["property"], "rgba": c["rgba"]} for c in src.get("colors", [])],
            "textures": [{"prop": t["property"], "file": f"{sid}/{Path(t['file']).name}"} for t in src.get("textures", [])],
            "crestTextures": [{"prop": t["property"], "file": f"{sid}/{Path(t['file']).name}"} for t in src.get("crestTextures", [])]}


def row_layer(row):
    """A catalog battle_skinned vanillaStyle row back to the vanilla-style layer the lab reads. Idle-window rows
    count as on (the portrait is the idle look); other windows (attack, hit, move) are left out. Per-node recolour
    gradients (recolorNodes) are not modelled by the lab; the row-level recolor is."""
    t = row.get("trigger", {})
    if t.get("mode") == "always":
        pass
    elif t.get("mode") == "animator_window" and any("Idle" in st for st in t.get("states", [])):
        pass
    else:
        return None
    short = row["id"].split(f"_{row['origin'].split(':', 1)[1]}_", 1)[-1]
    if short.startswith(PORTRAIT_SKIP_PREFIXES):
        return None
    vs = row["vanillaStyle"]
    return {"id": short, "type": "vanillaParticles",
            "source": {"resPath": row["source"]["nativeResPath"], "childPath": vs["childPath"], "keepNodes": vs["keepNodes"]},
            "loop": bool(vs.get("loop")), "zeroChildPositions": bool(vs.get("zeroChildPositions")),
            "orient": vs.get("orient", "bone"), "bones": list(row["socket"]["names"]), "triggers": [{"mode": "always"}],
            "scale": float(vs["worldScale"]), "rateMul": float(vs.get("rateMul", 1.0)),
            "recolor": vs.get("recolor") or [], "anchorNode": vs.get("anchorNode") or ""}


def unit_inputs(sid, stage2=None):
    """(host unit, host bundle, crest bundle, catalog rows, mesh-fx PNG root) for one fused sid. Stage 1 reads the
    installed GE plugin; stage 2 reads READY_FOR_PORTRAITS.txt (crestBundle, hostMeshBundle, vfxCatalog rows by id,
    meshFxPngRoot)."""
    L, V3M, FX, VL = _mods()
    if stage2:
        hb = Path(stage2["hostMeshBundle"])
        cb = Path(stage2["crestBundle"])
        if stage2.get("sha256") and sha256(cb).upper() != stage2["sha256"].upper():
            raise SystemExit(f"{sid}: crest bundle sha256 differs from READY_FOR_PORTRAITS.txt")
        ids = set(stage2["vfxEntryIds"].split(","))
        cat = json.loads(Path(stage2["vfxCatalog"]).read_text(encoding="utf-8"))["entries"]
        rows = [e for e in cat if e["id"] in ids]
        missing = ids - {e["id"] for e in rows}
        if missing:
            raise SystemExit(f"{sid}: vfx entries missing from catalog: {sorted(missing)[:4]}")
        host = hb.name.replace("custom_units_conflux_", "")
        return host, hb, cb, rows, Path(stage2["meshFxPngRoot"])
    h, g = FX.pair_by_sid()[sid]
    return (h, GE / "homm3_bundles" / FX.bundle_name(h), GE / "homm3_bundles" / FX.bundle_name(sid), catalog_rows(sid),
            GE / "homm3_mesh_fx")


def panel_for(sid, notes, stage2=None):
    L, V3M, FX, VL = _mods()
    host, hb, cb, rows, fx = unit_inputs(sid, stage2)
    d = DEST / sid
    sb = STAGE / "bundles"
    stage_file(hb, sb / hb.name)
    stage_file(cb, sb / f"{sid}__crest")
    em = next((r for r in rows if r["lane"] == "battle_emission"), None)
    ov = next((r for r in rows if r["lane"] == "battle_body_overlay"), None)
    if em is None or ov is None:
        raise SystemExit(f"{sid}: catalog has no emission/overlay row")
    e = em["emission"]
    stage_file(fx / e["texture"], d / "body_emission.png")
    if e.get("crestTexture"):
        stage_file(fx / e["crestTexture"], d / "crest_emission.png")
    for t in ov["source"].get("textures", []) + ov["source"].get("crestTextures", []):
        stage_file(fx / t["file"], d / Path(t["file"]).name)
    camf = VL.cam_frame("h3_water_elemental")
    yaw_face = VL.face_yaw(camf)
    layers = [l for l in (row_layer(r) for r in rows if r["lane"] == "battle_skinned") if l]
    eff = layer_effects(layers, host, yaw_face, "", notes)
    if any(r.get("vanillaStyle", {}).get("recolorNodes") for r in rows if r["lane"] == "battle_skinned"):
        notes.append("per-node recolour gradients not modelled (row recolor only)")
    body = {"kind": "composite", "bundlePath": str((sb / f"{sid}__crest").resolve()),
            "hostBundlePath": str((sb / hb.name).resolve()), "attachBone": "Head",
            "emissionTex": f"{sid}/body_emission.png",
            "crestEmissionTex": f"{sid}/crest_emission.png" if e.get("crestTexture") else "",
            "whiteVertexColor": True, "emissionColor": [float(c) for c in e["color"]],
            "emissionMin": float(e["minPower"]), "blinkSpeed": float(e["blinkSpeed"]), "blinkPower": float(e["blinkPower"]),
            "cellST": [], "overlays": [overlay_from_row(ov, sid)]}
    try:
        keys = len(VL.S.clip_segments(host)["Unit_Idle"]["defFrames"])
    except Exception:  # noqa: BLE001  (stage-2 hosts have no DEF segments; keys only feed the unused boil path)
        keys = 12
    clips = [{"name": "Unit_Idle", "keys": keys, "frames": PICK + 1, "frameStep": 1.0 / FPS, "boilCells": [], "loop": True}]
    a = math.radians(YAW)    # the sun turns with the camera so the lit side stays the battle view's lit side
    sx, sy, sz = V3M.SUN
    sun = [sx * math.cos(a) + sz * math.sin(a), sy, -sx * math.sin(a) + sz * math.cos(a)]
    return {"id": sid, "body": body, "clips": clips, "effects": eff, "flipbooks": [], "oldLights": [],
            "sunTravelUnity": sun, "warmupS": WARMUP, "camRight": camf["camRight"], "camUp": camf["camUp"],
            "camForward": camf["camForward"], "camCentre": camf["camCentre"], "orthoSize": 1.0, "width": RES,
            "height": RES, "autoCam": f"portrait|{sid}", "elevDeg": ELEV, "yawDeg": YAW, "saveFrames": [PICK],
            "projBones": PROJ_BONES}


def run_unity(spec: Path, tag: str, timeout=7200) -> int:
    log = WORK / tag / "unity.log"
    cmd = [str(UNITY), "-batchmode", "-quit", "-projectPath", str(PROJECT), "-homm3FusionPortraitSpec", str(spec),
           "-executeMethod", "OldenEra.Homm3Vfx.Homm3FusionPortraitLab.RunFromCommandLine", "-logFile", str(log)]
    t0 = time.time()
    done = subprocess.run(cmd, timeout=timeout)
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    for ln in [x for x in text.splitlines() if "error CS" in x or "PORTRAIT_PANEL_FAILED" in x][:20]:
        print("  ", ln[:300])
    ok = done.returncode == 0 and "HOMM3_FUSION_PORTRAIT_OK" in text
    print(tag, "unity exit", done.returncode, "OK" if ok else "FAILED", f"{time.time() - t0:.0f}s")
    return 0 if ok else 1


# ------------------------------------------------------------------ compose
def _dev():
    try:
        import torch
        return torch, ("cuda" if torch.cuda.is_available() else "cpu")
    except ImportError:
        return None, None


def finish_rgba(raw):
    """Linear premultiplied HDR (lab buffer) -> straight sRGB RGBA: lab bloom, alpha = max(coverage, glow)."""
    L, V3M, FX, VL = _mods()
    rgb = VL.bloom(raw[..., :3].astype(np.float32))
    cov = np.clip(raw[..., 3], 0, 1)
    glow = np.clip(rgb.max(-1), 0, 1)
    a = np.maximum(cov, glow)
    straight = rgb / np.maximum(a, 1e-4)[..., None]
    s = VL.to_srgb8(straight)
    return np.dstack([s, (a * 255 + 0.5).astype(np.uint8)]), cov


def crop_box(proj, cov, res):
    """Square crop (pixels, y down) around the head: the Head bone, the crest box and the silhouette top."""
    def px(v):
        return v[0] * res, (1 - v[1]) * res
    b = proj["bones"]
    hx, hy = px(b["Head"])
    low = next((k for k in ("Spine2", "Spine1", "Neck", "Spine") if k in b), None)
    lx, ly = px(b[low]) if low else (hx, hy + 0.15 * res)
    neck = max(math.hypot(lx - hx, ly - hy), 0.02 * res)
    top = hy - 0.6 * neck
    cols = slice(int(max(hx - 1.2 * neck, 0)), int(min(hx + 1.2 * neck, res)))
    rows_any = np.nonzero((cov[:, cols] > 0.5).sum(1) > 3)[0]
    if len(rows_any):
        top = min(top, max(rows_any.min(), hy - 2.2 * neck))   # silhouette (head + crest) top, bounded
    size = max(2.7 * neck, (hy - top) * 2.0)
    y0 = top - 0.05 * size
    x0 = hx - 0.5 * size
    return x0, y0, size


def portrait(sid, tag):
    rd = WORK / tag / "renders" / sid
    binp = rd / f"Unit_Idle_{PICK:03d}.bin"
    proj = json.loads((rd / f"Unit_Idle_{PICK:03d}.proj.json").read_text(encoding="utf-8"))
    raw = np.frombuffer(binp.read_bytes(), np.float16).astype(np.float32).reshape(RES, RES, 4)[::-1]
    rgba, _ = finish_rgba(raw)
    bodyp = rd / f"Unit_Idle_{PICK:03d}.body.bin"   # particles culled: the mesh coverage (crop + outline)
    cov = np.clip(np.frombuffer(bodyp.read_bytes(), np.float16).astype(np.float32).reshape(RES, RES, 4)[::-1][..., 3], 0, 1)
    x0, y0, size = crop_box(proj, cov, RES)
    widen = next((f for pre, f in WIDE_CROP.items() if sid.startswith(pre)), 1.0)
    if widen != 1.0:
        cx = x0 + 0.5 * size
        x0, y0, size = cx - 0.5 * size * widen, y0 - 0.05 * size, size * widen
    im = Image.fromarray(rgba, "RGBA")
    pad = int(size) + 8
    canvas = Image.new("RGBA", (RES + 2 * pad, RES + 2 * pad), (0, 0, 0, 0))
    canvas.paste(im, (pad, pad))
    box = (int(round(x0 + pad)), int(round(y0 + pad)), int(round(x0 + pad + size)), int(round(y0 + pad + size)))
    crop = canvas.crop(box)
    covim = Image.new("L", canvas.size, 0)
    covim.paste(Image.fromarray((cov * 255).astype(np.uint8)), (pad, pad))
    # premultiplied resample so transparent edges carry no dark fringe
    arr = np.asarray(crop).astype(np.float32) / 255
    pm = np.dstack([arr[..., :3] * arr[..., 3:], arr[..., 3]])
    chans = [Image.fromarray(pm[..., i]).resize((SIZE, SIZE), Image.LANCZOS) for i in range(4)]
    pm = np.clip(np.dstack([np.asarray(c) for c in chans]), 0, 1)
    solid = np.asarray(covim.crop(box).resize((SIZE, SIZE), Image.LANCZOS)).astype(np.float32) / 255
    out = outline(pm, solid)
    return out, proj, (x0, y0, size)


def outline(pm, solid, r=4.5):
    """The vanilla hex_portraits treatment: a black band around the solid silhouette (not around glow)."""
    torch, dev = _dev()
    m = (solid > 0.5).astype(np.float32)
    k = int(math.ceil(r))
    yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
    disk = ((xx ** 2 + yy ** 2) <= r * r).astype(np.float32)
    if torch is not None:
        t = torch.from_numpy(m)[None, None].to(dev)
        w = torch.from_numpy(disk)[None, None].to(dev)
        dil = (torch.nn.functional.conv2d(t, w, padding=k) > 0).float()
        soft = torch.nn.functional.avg_pool2d(dil, 3, 1, 1)[0, 0].cpu().numpy()
    else:
        from scipy.ndimage import binary_dilation, uniform_filter
        soft = uniform_filter(binary_dilation(m > 0, disk > 0).astype(np.float32), 3)
    a_ol = soft
    rgb = pm[..., :3]
    a = pm[..., 3]
    out_a = a + a_ol * (1 - a)
    out_rgb = rgb  # black outline contributes no colour (premultiplied)
    straight = out_rgb / np.maximum(out_a, 1e-4)[..., None]
    return np.dstack([np.clip(straight, 0, 1) * 255 + 0.5, out_a * 255 + 0.5]).astype(np.uint8)


# ------------------------------------------------------------------ sheets / manifest
def contact_sheet(sids, title, path, nm):
    cs, lh, cols = 192, 30, 10
    rows = (len(sids) + cols - 1) // cols
    sheet = Image.new("RGB", (cs * cols, (cs + lh) * rows + 40), (40, 40, 44))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except OSError:
        font = ImageFont.load_default()
    for i, sid in enumerate(sids):
        x, y = (i % cols) * cs, (i // cols) * (cs + lh)
        p = OUT / f"{sid}.png"
        cell = Image.new("RGBA", (cs, cs), (64, 64, 70, 255))
        if p.exists():
            cell.alpha_composite(Image.open(p).convert("RGBA").resize((cs, cs), Image.LANCZOS))
        else:
            ImageDraw.Draw(cell).text((8, 80), "missing", fill=(255, 120, 120), font=font)
        sheet.paste(cell.convert("RGB"), (x, y))
        d.text((x + 3, y + cs + 1), nm.get(sid, sid), fill=(235, 235, 235), font=font)
        d.text((x + 3, y + cs + 15), sid.replace("h3_fusion_", ""), fill=(150, 150, 160), font=font)
    d.text((6, sheet.height - 34), title, fill=(235, 235, 235), font=font)
    d.text((6, sheet.height - 18), "LAB RENDER (replica shaders, shipped bundles + mesh-fx rows), Unit_Idle frame "
           f"{PICK}, not in game.", fill=(255, 210, 120), font=font)
    sheet.save(path)
    return path


def write_manifest(meta):
    p = OUT / "portraits_manifest.json"
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"units": {}}
    old["units"].update(meta)
    old.update({"schema": "homm3_fusion_portraits.v1", "size": [SIZE, SIZE], "renderRes": RES,
                "camera": {"projection": "orthographic", "elevDeg": ELEV, "yawFromBattleDeg": YAW},
                "proof": "lab render (replica shaders), not in game; not installed",
                "script": "tools/conflux_fusion/fusion_portrait_render.py"})
    p.write_text(json.dumps(old, indent=1), encoding="utf-8")
    return p


def sheets():
    nm, s1, s2 = names()
    a = contact_sheet(s1, f"Elemental Fusion stage 1 portraits ({sum((OUT / f'{s}.png').exists() for s in s1)}/{len(s1)})",
                      OUT / "contact_sheet_stage1.png", nm)
    print("sheet", a)
    if any((OUT / f"{s}.png").exists() for s in s2):
        b = contact_sheet(s2, f"Elemental Fusion stage 2 portraits ({sum((OUT / f'{s}.png').exists() for s in s2)}/{len(s2)})",
                          OUT / "contact_sheet_stage2.png", nm)
        print("sheet", b)


# ------------------------------------------------------------------ driver
def render(sids, tag, batch, stage2_info=None, keep=False):
    setup_project()
    lib = stage_material_lib()
    meta, failed = {}, []
    for bi in range(0, len(sids), batch):
        chunk = sids[bi:bi + batch]
        btag = f"{tag}_{bi // batch:02d}"
        notes = {}
        panels = []
        for sid in chunk:
            notes[sid] = []
            try:
                panels.append(panel_for(sid, notes[sid], (stage2_info or {}).get(sid)))
            except (SystemExit, KeyError, FileNotFoundError, StopIteration) as ex:
                print("skip", sid, ex)
                failed.append((sid, f"spec: {ex}"))
        job = {"schema": "homm3_vanilla_style_lab.v1", "assetRoot": AROOT, "materialLib": str(lib),
               "outDir": str(WORK / btag / "renders"), "requireCompleteEffects": False, "panels": panels}
        (WORK / btag).mkdir(parents=True, exist_ok=True)
        spec = WORK / btag / "lab_spec.json"
        spec.write_text(json.dumps(job, indent=1), encoding="utf-8")
        rc = run_unity(spec, btag)
        rep_p = WORK / btag / "renders" / "lab_report.json"
        rep = rep_p.read_text(encoding="utf-8", errors="replace") if rep_p.exists() else ""
        for p in panels:
            sid = p["id"]
            try:
                im, proj, box = portrait(sid, btag)
            except (FileNotFoundError, KeyError) as ex:
                failed.append((sid, f"render: {ex}" + (" (unity rc %d)" % rc if rc else "")))
                continue
            dst = OUT / f"{sid}.png"
            Image.fromarray(im, "RGBA").save(dst, optimize=True)
            meta[sid] = {"file": dst.name, "sha256": sha256(dst),
                         "sourceFrame": {"clip": "Unit_Idle", "frame": PICK, "t": round((PICK + 1) / FPS, 4),
                                         "warmupS": WARMUP, "renderRes": RES,
                                         "cropPx": [round(box[0], 1), round(box[1], 1), round(box[2], 1)]},
                         "host": p["body"]["hostBundlePath"].split("\\")[-1].split("/")[-1],
                         "effects": len(p["effects"]), "notes": notes[sid]}
            if f"{sid}_error" in rep:
                meta[sid]["notes"].append("lab panel error logged")
        if not keep:
            shutil.rmtree(WORK / btag / "renders", ignore_errors=True)
        write_manifest(meta)
        print(btag, "done", len(meta), "failed", len(failed))
    return meta, failed


def stage2_info():
    """READY_FOR_PORTRAITS.txt: one line per stage-2 sid, tab-separated key=value fields (crestBundle, sha256,
    hostMeshBundle, vfxCatalog, vfxEntryIds, meshFxPngRoot, battleHeightHexes)."""
    if not READY.exists():
        raise SystemExit(f"{READY} missing: stage-2 visuals are not ready")
    out = {}
    for ln in READY.read_text(encoding="utf-8").splitlines():
        parts = [x for x in ln.strip().split("	") if x]
        if not parts or not parts[0].startswith("h3_fusion_ii_"):
            continue
        out[parts[0]] = dict(x.split("=", 1) for x in parts[1:] if "=" in x)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("stage1", "stage2", "sheets", "setup"))
    ap.add_argument("--only", default="")
    ap.add_argument("--batch", type=int, default=35)
    ap.add_argument("--keep", action="store_true", help="keep the raw 2048 px lab buffers")
    ap.add_argument("--recrop", action="store_true", help="re-crop kept buffers only (no Unity)")
    a = ap.parse_args()
    nm, s1, s2 = names()
    only = [s for s in a.only.split(",") if s]
    if a.cmd == "setup":
        setup_project()
        return 0
    if a.cmd == "sheets":
        sheets()
        return 0
    if a.cmd == "stage1":
        sids = only or s1
        meta, failed = render(sids, "s1", a.batch, keep=a.keep)
    else:
        info = stage2_info()
        sids = only or [s for s in s2 if s in info]
        for s in s2:
            if s not in info:
                print("not in READY_FOR_PORTRAITS.txt:", s)
        meta, failed = render(sids, "s2", a.batch, info, keep=a.keep)
    for sid, why in failed:
        print("FAILED", sid, why)
    sheets()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
