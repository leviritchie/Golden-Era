"""Unity-editor preview of a unit's `volumetricFire` layer (tools/homm3_unit_look/volfire.py), next to its DEF.

    python tools/homm3_vfx/volfire_unity_lab.py <unit> [--clips Unit_Idle,Unit_AttackFront] [--turntable 48]
                                                [--pitch 35] [--compose-only] [--timeout 1800]

Inputs: the unit-look vfx stage's outputs (artifacts/homm3_unit_look/<unit>/vfx/: vfx_manifest.json, the fire
sheets and emitter mask, the uvAtlas if any) and the look base colour. Stages copies of those, the def_retarget
GLB and Homm3VolumetricFireLab.cs into oldenera_factions (Assets/Homm3VfxLab/<unit>_volfire/,
Assets/Editor/Homm3VfxLab/), runs Unity batch through tools/homm3_vfx/unitylock.py (lock + memgate), then
composes review sheets and videos into artifacts/homm3_vfx_experiments/volfire/<unit>/:
  sheet_<clip>.png     DEF | look (no fire) | look + volumetric fire, one column per DEF key (2x)
  <clip>.mp4 / .gif    the same three panels at 12 fps
  turntable.mp4/.gif   look | look + fire, camera orbiting the idle loop (DEF idle loop beside it for reference)
  turntable_sheet.png  8 yaws
Proof tier: Unity-editor render (lab Hex/Lit replica for the body; native ParticleSystem + Sprites/Default for the
fire). Not in game.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Unity jobs go through the Unity queue (docs/unity_queue_runner.md): agents submit, not launch. --unity-direct is the
# explicit, loudly logged opt-out.
import importlib.util as _uq_ilu  # noqa: E402
_uq_spec = _uq_ilu.spec_from_file_location("unity_queue", Path(__file__).resolve().parents[1] / "unity_queue" / "unity_queue.py")
UQ = _uq_ilu.module_from_spec(_uq_spec)
_uq_spec.loader.exec_module(UQ)
UNITY_DIRECT = UQ.take_direct_flag()

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
import spec as S  # noqa: E402
import h3def  # noqa: E402

PROJECT = ROOT / "oldenera_factions"
UNITY = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe")
SRC = Path(__file__).parent / "unity"
MARKER = "HOMM3_VFX_LAB_GENERATED"


def srgb_to_lin(c):
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def stage(src: Path, dst: Path, managed_text=False):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if managed_text and dst.exists() and MARKER not in dst.read_text(encoding="utf-8", errors="replace"):
        raise FileExistsError(f"refusing to overwrite unmanaged {dst}")
    shutil.copy2(src, dst)


def sun_travel_unity(unit, cond="sand"):
    vm = json.loads((S.out_dir(unit) / "work/views/views_meta.json").read_text())
    f = next(iter(vm["views"].values()))["sunFrom"][cond]
    return [f[0], -f[2], f[1]]  # travel = -from; Blender (x,y,z) -> Unity (-x,z,-y)


def fire_layer(spec, man):
    ids = [ly["id"] for ly in spec["vfx"]["layers"] if ly["type"] == "volumetricFire"]
    if not ids:
        raise SystemExit(f"{spec['unit']}: no volumetricFire layer in the spec")
    if ids[0] not in man["layers"]:
        raise SystemExit(f"{spec['unit']}: layer {ids[0]} is not in vfx_manifest.json; run look.py --stages vfx")
    return ids[0], man["layers"][ids[0]]


def transfer_manifest(unit, src_unit, out: Path):
    """--fire-from: build src_unit's volumetricFire layer against this unit's GLB (bone-name emitter + DEF source,
    nothing from src_unit's geometry) into out/vfx; returns (spec with that layer, manifest, vfx dir)."""
    import volfire
    sys.path.insert(0, str(ROOT / "tools/homm3_prebake"))
    src = S.load(src_unit)
    ly = next(l for l in src["vfx"]["layers"] if l["type"] == "volumetricFire")
    if "region" in ly.get("emitter", {}) or "maskPath" in ly.get("emitter", {}):
        raise SystemExit(f"{src_unit}: a UV-mask emitter does not transfer to another mesh; use emitter.bones / excludeBones")
    cam = json.loads((S.RETARGET / unit / f"{unit}_def_retarget.blend.spritecam.json").read_text())
    vdir = out / "vfx"
    vdir.mkdir(parents=True, exist_ok=True)
    entry = volfire.build(ly, src, unit, cam["pxPerUnit"], vdir, S.clip_segments(unit))
    own = S.load(unit)
    spec = {**own, "vfx": {"layers": [l for l in own["vfx"]["layers"] if l["type"] != "volumetricFire"] + [ly]}}
    return spec, {"layers": {ly["id"]: entry}}, vdir


def run_unity(unit, a, out: Path) -> int:
    if a.fire_from:
        spec, man, vdir = transfer_manifest(unit, a.fire_from, out)
        own = S.out_dir(unit) / "vfx/vfx_manifest.json"
        if own.exists():                        # this unit's own uvAtlas, if any
            for k, v in json.loads(own.read_text())["layers"].items():
                if v.get("type") == "uvAtlas":
                    man["layers"][k] = v
                    shutil.copy2(S.out_dir(unit) / "vfx" / v["atlas"], vdir / v["atlas"])
    else:
        spec = S.load(unit)
        vdir = S.out_dir(unit) / "vfx"
        man = json.loads((vdir / "vfx_manifest.json").read_text())
    lid, fl = fire_layer(spec, man)
    cam = json.loads((S.RETARGET / unit / f"{unit}_def_retarget.blend.spritecam.json").read_text())
    asset_root = f"Assets/Homm3VfxLab/{unit}_volfire"
    dest = PROJECT / asset_root
    marker = dest / "HOMM3_VFX_LAB_GENERATED.txt"
    if dest.exists() and not marker.exists() and any(dest.iterdir()):
        raise FileExistsError(f"refusing to write into unmanaged {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    marker.write_text("managed by tools/homm3_vfx/volfire_unity_lab.py\n")
    if not (PROJECT / "Assets/Homm3VfxLab/Shaders/Homm3VfxHexLitReplicaPoint.shader").exists():
        stage(SRC / "Homm3VfxHexLitReplicaPoint.shader", PROJECT / "Assets/Homm3VfxLab/Shaders/Homm3VfxHexLitReplicaPoint.shader", True)
    stage(S.glb_path(unit), dest / f"{unit}_volfire.glb")
    stage(S.out_dir(unit) / "basecolor.png", dest / "basecolor.png")
    atlas = next((v for v in man["layers"].values() if v.get("type") == "uvAtlas"), None)
    if atlas:
        stage(vdir / atlas["atlas"], dest / atlas["atlas"])
    for s in fl["systems"].values():
        stage(vdir / s["sheet"], dest / s["sheet"])
    if not fl["emitter"]["mask"]:
        Image.new("L", (4, 4), 255).save(dest / "emitter_all.png")
    else:
        stage(vdir / fl["emitter"]["mask"], dest / fl["emitter"]["mask"])
    stage(SRC / "Homm3VolumetricFireLab.cs", PROJECT / "Assets/Editor/Homm3VfxLab/Homm3VolumetricFireLab.cs", True)

    light_ly = next((ly for ly in spec["vfx"]["layers"] if ly["type"] == "effectLight" and ly.get("carrier") == lid), None)
    if light_ly is None and a.fire_from:        # the source unit's fire light (e.g. the phoenix body_fire floor)
        light_ly = next((ly for ly in S.load(a.fire_from)["vfx"]["layers"] if ly["type"] == "effectLight" and ly.get("carrier") == lid), None)
    clips_seg = S.clip_segments(unit)
    clips = []
    for cn, mult in fl["clips"].items():
        floor = 0.0
        if light_ly:
            f = light_ly.get("floor", 0.0)
            floor = float(f.get(cn, 0.0)) if isinstance(f, dict) else float(f)
        cells = [c["cell"] for c in atlas["clips"][cn]] if atlas and cn in atlas["clips"] else []
        clips.append({"name": cn, "keys": len(clips_seg[cn]["defFrames"]), "boilCells": cells, "mult": mult,
                      "lightFloor": floor, "clearAtKey": fl.get("clearAtKey", {}).get(cn, -1)})
    systems = []
    for name, s in fl["systems"].items():
        systems.append({"name": name, "sheet": s["sheet"], "tilesX": s["tilesX"], "tilesY": s["tilesY"],
                        "sizeX": s["sizeWorld"][0], "sizeY": s["sizeWorld"][1], "sizeJitter": s["sizeJitter"],
                        "lifeMin": s["lifetimeS"][0], "lifeMax": s["lifetimeS"][1], "rate": s["ratePerSecond"],
                        "rise": s["riseWorldPerS"], "spread": s.get("spreadWorldPerS", 0.0),
                        "normalOffset": s["normalOffsetWorld"], "hLo": s["emitterFilter"]["heightRange"][0],
                        "hHi": s["emitterFilter"]["heightRange"][1], "minUp": s["emitterFilter"]["minUp"],
                        "expectTriangles": s["emitterTriangles"]})
    rgb = light_ly["rgb"] if light_ly else [1, 0.72, 0.36]
    lab = {
        "schema": "homm3_volfire_lab.v1", "assetRoot": asset_root, "glbAssetPath": f"{asset_root}/{unit}_volfire.glb",
        "basecolor": "basecolor.png", "boilAtlas": atlas["atlas"] if atlas else "",
        "cellST": [x for st in (atlas["cellST"] if atlas else []) for x in st],
        "emitterMask": fl["emitter"]["mask"] or "emitter_all.png", "emitterThreshold": fl["emitter"]["threshold"],
        "restYRange": fl["emitter"]["restCentroidYRange"],
        "emitterBones": fl["emitter"].get("bones") or [], "emitterExcludeBones": fl["emitter"].get("excludeBones") or [],
        "anchorBone": fl["anchor"]["bone"],
        "lightBone": (light_ly or {}).get("anchor", {}).get("bone", fl["anchor"]["bone"]),
        "lightTowardCamera": (light_ly or {}).get("anchor", {}).get("towardCameraU", 0.45),
        "lightRange": (light_ly or {}).get("range", 3.0), "lightRgbLinear": [float(x) for x in srgb_to_lin(rgb)],
        "clips": clips, "systems": systems, "warmupS": 1.0,
        "camRight": cam["right"], "camUp": cam["up"], "camForward": cam["forward"], "pxPerUnit": cam["pxPerUnit"],
        "offset": cam["offset"], "size": cam["size"], "scale": 2, "sunTravelUnity": sun_travel_unity(unit if (S.out_dir(unit) / "work/views/views_meta.json").exists() or not a.fire_from else a.fire_from),
        "turntableClip": "Unit_Idle", "turntableFrames": a.turntable, "turntableDegPerFrame": 360.0 / max(a.turntable, 1),
        "turntablePitchDeg": a.pitch, "variants": ["look", "fire"], "renderClips": a.clips.split(","),
        "outDir": str(out / "renders"),
    }
    (out / "renders").mkdir(parents=True, exist_ok=True)
    sp = out / "unity_lab_spec.json"
    sp.write_text(json.dumps(lab, indent=1))
    log = out / "unity_lab.log"
    cmd = [str(UNITY), "-batchmode", "-quit", "-projectPath", str(PROJECT), "-homm3VolfireSpec", str(sp),
           "-executeMethod", "OldenEra.Homm3Vfx.Homm3VolumetricFireLab.RunFromCommandLine", "-logFile", str(log)]
    done = UQ.run_cmd(cmd, kind="vfx_volfire_lab", timeout_s=a.timeout, direct=UNITY_DIRECT)
    print(done.stdout[-1500:], done.stderr[-1500:])
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    for line in text.splitlines():
        if "HOMM3_VOLFIRE" in line or "error CS" in line or "Exception" in line:
            print(line[:400])
    ok = done.returncode == 0 and "HOMM3_VOLFIRE_LAB_OK" in text
    print("exit", done.returncode, "OK" if ok else "FAILED", log)
    return 0 if ok else 1


# ------------------------------------------------------------------ compose
def def_rgba(unit, clip):
    import volfire
    name = volfire.unit_frame_source(unit)          # the game DEF, or the extracted .dir the retarget used
    d = None if name.lower().endswith(".dir") else h3def.read_def(name.lower())
    return [volfire.read_frame(name, g, f, d) for g, f in S.clip_segments(unit)[clip]["defFrames"]]


def on_bg(rgba, bg=(48, 48, 48)):
    im = Image.new("RGBA", (rgba.shape[1], rgba.shape[0]), bg + (255,))
    im.alpha_composite(Image.fromarray(rgba))
    return im.convert("RGB")


def bbox(imgs, pad=10):
    a = np.zeros(imgs[0].shape[:2], bool)
    for im in imgs:
        a |= im[..., 3] > 0
    ys, xs = np.nonzero(a)
    return max(xs.min() - pad, 0), max(ys.min() - pad, 0), min(xs.max() + pad, a.shape[1]), min(ys.max() + pad, a.shape[0])


def label(im, text):
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, im.width, 14), fill=(20, 20, 20))
    d.text((3, 1), text, fill=(235, 235, 235))
    return im


def write_video(frames, path: Path, fps=12):
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    w, h = frames[0].size
    w2, h2 = w + (w & 1), h + (h & 1)
    p = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w2}x{h2}",
                          "-r", str(fps), "-i", "-", "-vf", "scale=iw:ih:flags=neighbor", "-pix_fmt", "yuv420p",
                          "-crf", "16", str(path)], stdin=subprocess.PIPE)
    for f in frames:
        c = Image.new("RGB", (w2, h2))
        c.paste(f, (0, 0))
        p.stdin.write(c.tobytes())
    p.stdin.close()
    p.wait()
    frames[0].save(path.with_suffix(".gif"), save_all=True, append_images=frames[1:], duration=int(1000 / fps), loop=0)


def _fire_stats(rgba, rule):
    """(fire px / silhouette px, top/mid/bottom share of the fire) with the layer's own fireMask rule."""
    import volfire
    x = np.array(rgba)
    sil = x[..., 3] >= 128
    x[..., 3] = np.where(sil, 255, 0)
    fire = volfire.fire_mask(x, rule)
    ys = np.nonzero(sil.any(1))[0]
    if not len(ys):
        return 0.0, [0.0, 0.0, 0.0]
    y0, h = ys.min(), ys.max() - ys.min() + 1
    b = [float(fire[y0 + k * h // 3:y0 + (k + 1) * h // 3].sum()) for k in range(3)]
    return float(fire.sum() / max(1, sil.sum())), [v / (sum(b) or 1.0) for v in b]


def calibrate(unit, spec_layer_rule, out: Path):
    """How pronounced the fire is, against the unit's own DEF (volumetricFire per-unit calibration).

    defFire       idle DEF keys: fireMask px / opaque px (the share of the sprite that is flame)
    lookFire      lab render without particles: the same rule on the lit body alone
    renderedFire  lab render with particles, the DEF's camera: the same rule (target: close to defFire)
    particleCover lab render: px the particles change (|dRGB| > 30 or new coverage) / silhouette px
    turntableFire renderedFire averaged over the turntable yaws (view independence)
    bands         top / middle / bottom thirds' share of the fire (where it is)
    Proof tier: Unity-editor lab render."""
    r = out / "renders"
    defs = def_rgba(unit, "Unit_Idle")
    n = len(defs)
    look = [np.asarray(Image.open(r / "look" / f"Unit_Idle_{i:02d}.png").convert("RGBA")) for i in range(n)]
    fire = [np.asarray(Image.open(r / "fire" / f"Unit_Idle_{i:02d}.png").convert("RGBA")) for i in range(n)]
    d = [_fire_stats(np.where((x[..., 3] == 255)[..., None], x, 0), spec_layer_rule) for x in defs]
    lk = [_fire_stats(x, spec_layer_rule) for x in look]
    fi = [_fire_stats(x, spec_layer_rule) for x in fire]
    cov = []
    for l, f in zip(look, fire):
        sil = f[..., 3] >= 128
        ch = (np.abs(l[..., :3].astype(int) - f[..., :3].astype(int)).sum(-1) > 30) | ((l[..., 3] < 128) & sil)
        cov.append(float((ch & sil).sum() / max(1, sil.sum())))
    tt = sorted((r / "turntable_fire").glob("tt_*.png"))
    ttf = [_fire_stats(np.asarray(Image.open(p).convert("RGBA")), spec_layer_rule)[0] for p in tt]
    mean = lambda xs: round(float(np.mean(xs)), 3)
    band = lambda st: [round(float(np.mean([b[k] for _, b in st])), 2) for k in range(3)]
    res = {"schema": "homm3_volfire_calibration.v1", "unit": unit, "fireMask": spec_layer_rule,
           "defFire": mean([x for x, _ in d]), "defBands": band(d),
           "lookFire": mean([x for x, _ in lk]), "renderedFire": mean([x for x, _ in fi]), "renderedBands": band(fi),
           "particleCover": mean(cov), "turntableFire": mean(ttf) if ttf else None,
           "proofTier": "Unity-editor lab render (not in game)"}
    res["renderedOverDef"] = round(res["renderedFire"] / max(res["defFire"], 1e-6), 2)
    (out / "calibration.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("calibration", json.dumps(res))
    return res


def compose(unit, a, out: Path):
    r = out / "renders"
    for clip in a.clips.split(","):
        defs = def_rgba(unit, clip)
        n = len(defs)
        look = [np.asarray(Image.open(r / "look" / f"{clip}_{i:02d}.png").convert("RGBA")) for i in range(n)]
        fire = [np.asarray(Image.open(r / "fire" / f"{clip}_{i:02d}.png").convert("RGBA")) for i in range(n)]
        defs2 = [np.asarray(Image.fromarray(d).resize((d.shape[1] * 2, d.shape[0] * 2), Image.NEAREST)) for d in defs]
        x0, y0, x1, y1 = bbox(defs2 + fire)
        rows = {"DEF": defs2, "look (no fire)": look, "look + volumetricFire": fire}
        cw, ch = x1 - x0, y1 - y0
        sheet = Image.new("RGB", (cw * n, (ch + 14) * 3), (30, 30, 30))
        vids = []
        for ri, (name, ims) in enumerate(rows.items()):
            for i, im in enumerate(ims):
                tile = label(on_bg(im[y0:y1, x0:x1]), f"{name} k{i}" if i == 0 else f"k{i}")
                sheet.paste(tile, (i * cw, ri * (ch + 14)))
        sheet.save(out / f"sheet_{clip}.png")
        for i in range(n):
            f = Image.new("RGB", (cw * 3, ch + 14), (30, 30, 30))
            for ri, (name, ims) in enumerate(rows.items()):
                f.paste(label(on_bg(ims[i][y0:y1, x0:x1]), f"{name}  {clip} k{i}"), (ri * cw, 0))
            vids.append(f)
        loops = 3 if clip in ("Unit_Idle", "Unit_Move") else 1
        write_video(vids * loops, out / f"{clip}.mp4")
    tt = sorted((r / "turntable_fire").glob("tt_*.png"))
    if tt:
        defs = def_rgba(unit, "Unit_Idle")
        defs2 = [np.asarray(Image.fromarray(d).resize((d.shape[1] * 2, d.shape[0] * 2), Image.NEAREST)) for d in defs]
        look = [np.asarray(Image.open(r / "turntable_look" / p.name).convert("RGBA")) for p in tt]
        fire = [np.asarray(Image.open(p).convert("RGBA")) for p in tt]
        x0, y0, x1, y1 = bbox(look + fire + defs2)
        cw, ch = x1 - x0, y1 - y0
        deg = 360.0 / len(tt)
        frames = []
        for i in range(len(tt)):
            f = Image.new("RGB", (cw * 3, ch + 14), (30, 30, 30))
            f.paste(label(on_bg(defs2[i % len(defs2)][y0:y1, x0:x1]), "DEF idle (one view only)"), (0, 0))
            f.paste(label(on_bg(look[i][y0:y1, x0:x1]), f"look, yaw {i * deg:.0f}"), (cw, 0))
            f.paste(label(on_bg(fire[i][y0:y1, x0:x1]), f"look + volumetricFire, yaw {i * deg:.0f}"), (2 * cw, 0))
            frames.append(f)
        write_video(frames, out / "turntable.mp4")
        step = max(1, len(tt) // 8)
        pick = list(range(0, len(tt), step))[:8]
        sh = Image.new("RGB", (cw * len(pick), (ch + 14) * 2), (30, 30, 30))
        for j, i in enumerate(pick):
            sh.paste(label(on_bg(look[i][y0:y1, x0:x1]), f"look yaw {i * deg:.0f}"), (j * cw, 0))
            sh.paste(label(on_bg(fire[i][y0:y1, x0:x1]), f"+fire yaw {i * deg:.0f}"), (j * cw, ch + 14))
        sh.save(out / "turntable_sheet.png")
    if not a.fire_from and "Unit_Idle" in a.clips.split(","):
        ly = next(l for l in S.load(unit)["vfx"]["layers"] if l["type"] == "volumetricFire")
        calibrate(unit, ly["source"].get("fireMask", {}), out)
    print("composed", out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("--clips", default="Unit_Idle,Unit_AttackFront,Unit_Death")
    ap.add_argument("--turntable", type=int, default=48)
    ap.add_argument("--pitch", type=float, default=35.0)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--compose-only", action="store_true")
    ap.add_argument("--fire-from", help="render another unit's volumetricFire layer on this unit's mesh (transfer test)")
    a = ap.parse_args()
    out = ROOT / "artifacts/homm3_vfx_experiments/volfire" / (a.unit + (f"__fire_from_{a.fire_from}" if a.fire_from else ""))
    out.mkdir(parents=True, exist_ok=True)
    if not a.compose_only:
        rc = run_unity(a.unit, a, out)
        if rc:
            return rc
    compose(a.unit, a, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
