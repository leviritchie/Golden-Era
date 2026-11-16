"""Elemental Fusion stage 2 (h3_fusion_ii_*) shared-mesh crest bundles: each stage-2 unit rides its host parent's host
bundle (mesh, skeleton, clips, audio) exactly as stage 1 does, and ships one small bundle with a new two-tier crest
built from both stage-1 parents' crests, the host parent's body albedo and a crest albedo atlas (host parent | guest
parent).

    python tools/homm3_def_retarget_delivery/fusion_stage2_bundles.py assets   [--units SID,..]
    python tools/homm3_def_retarget_delivery/fusion_stage2_bundles.py build    [--units SID,..]
    python tools/homm3_def_retarget_delivery/fusion_stage2_bundles.py hexes

assets: crest geometry (Head bind-local, Y up; read from the installed stage-1 crest bundles' meshes), textures, the
        crest emission / overlay-mask atlases and the body emission / mask copies (host parent's, same host UVs).
build:  Unity (lab project, queue runner) writes custom_units_conflux_h3_fusion_ii_* into <out>/build_out.
hexes:  battleHeightHexes = host parent's hexes x 1.2 x (H2 / H1), H = bind-pose height of body + crest, because the
        runtime fit (FitSkinnedBattleMesh, TryGetRenderableWorldBounds) scales body + crest together.

Inputs: V:/olden_port_work/elemental_fusion/stage2/recipes_preview.json (units), the stage-1 ship / shared outputs of
fusion_fx.py + fusion_shared_bundles.py under V:/olden_port_work/elemental_fusion/v4, crests.npz (dump of the installed
stage-1 crest meshes). Proof tier: generated bundles + Unity editor lab; not installed, not run in game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
import fusion_fx as FX  # noqa: E402
from glb_io import Glb  # noqa: E402

STAGE2 = Path("V:/olden_port_work/elemental_fusion/stage2")
RECIPES = STAGE2 / "recipes_preview.json"
V4 = Path("V:/olden_port_work/elemental_fusion/v4")
SHIP = V4 / "ship"
SHARED_MFX = V4 / "shared/homm3_mesh_fx"
OUT = STAGE2 / "visuals/build"
CRESTS = STAGE2 / "visuals/crests.npz"
LAB_PROJECT = ROOT / "oldenera_factions"
CS_SRC = HERE / "unity/Homm3FusionStage2CrestBundles.cs"
CS_DEST = LAB_PROJECT / "Assets/Editor/Homm3VfxLab/Homm3FusionStage2CrestBundles.cs"
BODY, CREST = 1024, 512
SIZE_STEP = 1.2
# two-tier crest: host parent's crest enlarged in place, guest parent's crest smaller, turned and lifted on top of it
A_SCALE, B_SCALE, B_LIFT, B_TURN_DEG, B_BACK = 1.12, 0.88, 0.55, 45.0, 0.01


class Stage2Error(Exception):
    pass


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def units(only=None) -> list[dict]:
    rs = json.loads(RECIPES.read_text(encoding="utf-8"))
    return [r for r in rs if not only or r["fused"] in only]


def import_entries() -> dict:
    imp = json.loads((ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json")
                     .read_text(encoding="utf-8"))
    return {e["gameUnitSids"][0]: e for e in imp["entries"] if e.get("gameUnitSids")}


def crest(sid: str) -> dict:
    z = np.load(CRESTS)
    return {k: z[f"{sid}|{k}"].astype(np.float64 if k != "t" else np.int64) for k in ("v", "n", "uv", "t")}


def combine(a: dict, b: dict) -> dict:
    """A: scaled about the Head origin. B: scaled about its own base centre, turned about Y, set on A's centre line with
    its base at B_LIFT of A's height. UVs: A -> left half, B -> right half of the crest atlas."""
    va = a["v"] * A_SCALE
    na = a["n"]
    vb = b["v"].copy()
    base = np.array([vb[:, 0].mean(), vb[:, 1].min(), vb[:, 2].mean()])
    vb = (vb - base) * B_SCALE
    th = np.radians(B_TURN_DEG)
    c, s = np.cos(th), np.sin(th)
    rot = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    vb = vb @ rot.T
    nb = b["n"] @ rot.T
    ya0, ya1 = va[:, 1].min(), va[:, 1].max()
    vb += np.array([va[:, 0].mean(), ya0 + B_LIFT * (ya1 - ya0), va[:, 2].mean() - B_BACK])
    uva = a["uv"] * [0.5, 1.0]
    uvb = b["uv"] * [0.5, 1.0] + [0.5, 0.0]
    return {"v": np.vstack([va, vb]), "n": np.vstack([na, nb]), "uv": np.vstack([uva, uvb]),
            "t": np.vstack([a["t"], b["t"] + len(va)])}


def halves(p: Path, body: int, crest_px: int, mode: str):
    im = Image.open(p).convert(mode)
    w, h = im.size
    if w != 2 * h:
        raise Stage2Error(f"{p}: not a 2:1 atlas")
    rs = lambda x, s: x if x.size == (s, s) else x.resize((s, s), Image.LANCZOS)  # noqa: E731
    return rs(im.crop((0, 0, h, h)), body), rs(im.crop((h, 0, w, h)), crest_px)


def pair_atlas(left: Image.Image, right: Image.Image) -> Image.Image:
    w, h = left.size
    out = Image.new(left.mode, (2 * w, h))
    out.paste(left, (0, 0))
    out.paste(right.resize((w, h), Image.LANCZOS) if right.size != (w, h) else right, (w, 0))
    return out


def cmd_assets(only) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    meta_all = {}
    for r in units(only):
        sid, a, b = r["fused"], r["host"], r["guest"]
        d = OUT / sid
        d.mkdir(parents=True, exist_ok=True)
        m = combine(crest(a), crest(b))
        (d / "crest_mesh.json").write_text(json.dumps({
            "v": [round(float(x), 6) for x in m["v"].ravel()], "n": [round(float(x), 6) for x in m["n"].ravel()],
            "uv": [round(float(x), 6) for x in m["uv"].ravel()], "t": [int(x) for x in m["t"].ravel()]}), encoding="utf-8")
        body_a, crest_a = halves(SHIP / "units" / a / "fused_basecolor.png", BODY, CREST, "RGB")
        _, crest_b = halves(SHIP / "units" / b / "fused_basecolor.png", BODY, CREST, "RGB")
        body_a.save(d / "owned_skinned_basecolor.png", optimize=True)
        pair_atlas(crest_a, crest_b).save(d / "fusion_crest_basecolor.png", optimize=True)
        mfx = d / "homm3_mesh_fx"
        (mfx / "emission").mkdir(parents=True, exist_ok=True)
        (mfx / "fusion").mkdir(parents=True, exist_ok=True)
        shutil.copy2(SHARED_MFX / f"emission/{a}__body_emission.png", mfx / f"emission/{sid}__body_emission.png")
        shutil.copy2(SHARED_MFX / f"fusion/{a}__body_mask.png", mfx / f"fusion/{sid}__body_mask.png")
        pair_atlas(Image.open(SHARED_MFX / f"emission/{a}__crest_emission.png").convert("RGB"),
                   Image.open(SHARED_MFX / f"emission/{b}__crest_emission.png").convert("RGB")
                   ).save(mfx / f"emission/{sid}__crest_emission.png", optimize=True)
        pair_atlas(Image.open(SHARED_MFX / f"fusion/{a}__crest_mask.png").convert("L"),
                   Image.open(SHARED_MFX / f"fusion/{b}__crest_mask.png").convert("L")
                   ).save(mfx / f"fusion/{sid}__crest_mask.png", optimize=True)
        meta_all[sid] = {"host": a, "guest": b, "crestVerts": int(len(m["v"])), "crestTris": int(len(m["t"])),
                         "min": [round(float(x), 4) for x in m["v"].min(0)], "max": [round(float(x), 4) for x in m["v"].max(0)]}
        print(f"assets: {sid} crest {len(m['v'])}v {len(m['t'])}t")
    p = OUT / "assets_meta.json"
    prev = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    prev.update(meta_all)
    p.write_text(json.dumps(prev, indent=1), encoding="utf-8")


def cmd_build(only, chunk: int = 37) -> None:
    import vanilla_style_lab as VL
    bo = OUT / "build_out"
    bo.mkdir(parents=True, exist_ok=True)
    rec_p = OUT / "stage2_bundles.json"
    rec = json.loads(rec_p.read_text(encoding="utf-8")) if rec_p.exists() else {"units": {}}
    CS_DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CS_SRC, CS_DEST)
    sids = [r["fused"] for r in units(only)]
    try:
        for ci in range(0, len(sids), chunk):
            part = sids[ci:ci + chunk]
            spec_units = [{"sid": s, "bundleName": FX.bundle_name(s), "meshJson": str(OUT / s / "crest_mesh.json"),
                           "bodyPng": str(OUT / s / "owned_skinned_basecolor.png"),
                           "crestPng": str(OUT / s / "fusion_crest_basecolor.png"), "bodyMaxSize": BODY,
                           "crestMaxSize": 2 * CREST} for s in part]
            tag = f"s2c{ci // chunk:02d}"
            logs = OUT / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            spec, report, log = logs / f"spec_{tag}.json", logs / f"report_{tag}.json", logs / f"unity_{tag}.log"
            spec.write_text(json.dumps({"units": spec_units, "outDir": str(bo), "report": str(report)}, indent=1),
                            encoding="utf-8")
            gate = subprocess.run([sys.executable, str(ROOT / "tools/homm3_def_retarget/launch_guard.py")],
                                  capture_output=True, text=True, timeout=900)
            if gate.returncode:
                raise Stage2Error(f"launch_guard refused: {gate.stdout[-300:]} {gate.stderr[-300:]}")
            cmd = [str(VL.UNITY), "-batchmode", "-quit", "-projectPath", str(LAB_PROJECT), "-fusionStage2Spec", str(spec),
                   "-executeMethod", "OldenEra.Homm3Vfx.Homm3FusionStage2CrestBundles.BuildFromCommandLine",
                   "-logFile", str(log)]
            t0 = time.time()
            done = VL.UQ.run_cmd(cmd, kind="vfx_fusion_stage2_crest_bundles", timeout_s=3600, direct=VL.UNITY_DIRECT)
            text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
            if done.returncode != 0 or "HOMM3_FUSION_STAGE2_CREST_OK" not in text:
                errs = [ln[:300] for ln in text.splitlines() if "error CS" in ln or "Exception" in ln][:12]
                raise Stage2Error(f"stage-2 crest job {tag} failed (exit {done.returncode}): {errs}; see {log}")
            geo = json.loads(report.read_text(encoding="utf-8"))
            for s in part:
                b = bo / FX.bundle_name(s)
                rec["units"][s] = {"bundle": b.name, "bytes": b.stat().st_size, "sha256": sha(b).upper(), "crest": geo[s]}
            print(f"build {tag}: {len(part)} bundles in {time.time() - t0:.0f}s")
            rec_p.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    finally:
        CS_DEST.unlink(missing_ok=True)
        CS_DEST.with_suffix(".cs.meta").unlink(missing_ok=True)
    for p in bo.glob("*.manifest"):
        p.unlink()
    (bo / "build_out").unlink(missing_ok=True)


def body_and_head(h: str):
    """Bind-pose body vertices (glTF space) and the Head joint's bind matrix of the host's delivered GLB."""
    g = Glb(FX.host_df(h)["glb"])
    pos = [g.accessor(p["attributes"]["POSITION"]) for m in g.json["meshes"] for p in m["primitives"]]
    skin = g.json["skins"][0]
    names = [g.json["nodes"][j].get("name") for j in skin["joints"]]
    ibm = g.accessor(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    return np.vstack(pos).astype(np.float64), np.linalg.inv(ibm[names.index("Head")])


def height(body: np.ndarray, head_bind: np.ndarray, crest_local: np.ndarray) -> float:
    cl = crest_local * [-1.0, 1.0, 1.0]           # Unity bind-local -> glTF (x mirrored)
    cw = (head_bind @ np.c_[cl, np.ones(len(cl))].T).T[:, :3]
    y = np.concatenate([body[:, 1], cw[:, 1]])
    return float(y.max() - y.min())


def cmd_hexes() -> None:
    ent = import_entries()
    pb = FX.pair_by_sid()
    out = {}
    cache = {}
    for r in units():
        sid, a, b = r["fused"], r["host"], r["guest"]
        h = pb[a][0]
        if h not in cache:
            cache[h] = body_and_head(h)
        body, hb = cache[h]
        ca, cb = crest(a), crest(b)
        h1 = height(body, hb, ca["v"])
        h2 = height(body, hb, combine(ca, cb)["v"])
        hx1 = float(ent[a]["battleHeightHexes"])
        out[sid] = {"hostParent": a, "hostMesh": h, "hexesStage1": hx1, "h1": round(h1, 4), "h2": round(h2, 4),
                    "battleHeightHexes": round(hx1 * SIZE_STEP * h2 / h1, 3)}
        print(f"hexes: {sid} {hx1} -> {out[sid]['battleHeightHexes']} (crest growth x{h2 / h1:.3f})")
    (OUT / "hexes.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("assets", "build", "hexes"))
    ap.add_argument("--units", default="")
    a = ap.parse_args()
    only = {s for s in a.units.split(",") if s} or None
    {"assets": lambda: cmd_assets(only), "build": lambda: cmd_build(only), "hexes": cmd_hexes}[a.cmd]()
