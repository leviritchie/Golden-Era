"""Titan: prebaked albedo (v6 / v6m) + lightning flipbooks + a VFX point light, in a Unity light lab.

  python tools/homm3_vfx/titan_light_lab.py render    stage lab shaders/textures, one Unity batch run (memgate-gated)
  python tools/homm3_vfx/titan_light_lab.py compose   fit per-frame light intensity to the DEF glow, build sheets

The Unity pass is Homm3VfxLightLab.cs with Homm3VfxHexLitReplicaPoint.shader: the installed Hex/Lit Lit-pass
formula (static DXBC read) including its per-object point-light loop, evaluated in the Unity editor through a
camera registered to the def_retarget sprite camera (1 DEF px = 2 render px). Proof level: Unity-editor render of
a replica shader, not in-game. The runtime enabling of Hex/Lit's point-light loop is not proven here.
"""
from __future__ import annotations

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
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_prebake"))
sys.path.insert(0, str(Path(__file__).parent))
import prebake_lab as pl  # noqa: E402
import h3def  # noqa: E402
from titan_vfx_textures import lightning_mask, CLIPS as FX_CLIPS  # noqa: E402

UNITY = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe")
PROJECT = ROOT / "oldenera_factions"
HERE = Path(__file__).parent / "unity"
TITAN = ROOT / "artifacts/homm3_vfx_experiments/titan"
WORK = TITAN / "work"
RAW = WORK / "light_lab_raw"          # half-float buffers (large, not committed)
OUT = TITAN / "light_lab"
PREBAKE = ROOT / "artifacts/homm3_prebaked_lighting/titan"
SPRITECAM = ROOT / "artifacts/homm3_def_retarget/h3_giant_upg/h3_giant_upg_def_retarget.blend.spritecam.json"
LAB = "Assets/Homm3VfxLab/h3_giant_upg"
STAGE = f"{LAB}/lightlab"
MARKER = "HOMM3_VFX_LAB_GENERATED"
SCALE = 2                               # render px per DEF px
TEXTURES = {"raw": None, "v6": "v6_sprite_match_basecolor.png", "v6m": "v6m_material_grade_basecolor.png"}
LIGHT_TEX = "v6m"
LIGHT_COLOR_SRGB = (1.0, 0.96, 0.86)    # pale warm, as the DEF's glow shifts b* up (19.1 -> 22.6) and L up
LIGHT_RANGE = 3.0                       # world units; the Titan is ~2.6 units tall
TOWARD_CAMERA = 0.45                    # light sits in front of the hand, toward the viewer
CENTROID_PULL = 0.5                     # share of (bolt centroid - hand) the light follows
JOBS = {  # name: (clip, DEF group, effect prefab (A = literal DEF pixels), anchor)
    "attack": ("Unit_AttackFront", 12, "titan_attack_A", "RightHand"),
    "shoot": ("Unit_ShootFront", 15, "titan_shoot_A_missile", "LeftHand"),
}
M = np.array([[-1, 0, 0], [0, 0, 1], [0, -1, 0]], float)   # Blender (x,y,z) -> Unity (-x,z,-y)


def unity_running() -> bool:
    return "Unity.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq Unity.exe"], capture_output=True, text=True).stdout


def stage_file(src: Path, dest: Path, managed: bool):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if managed and dest.exists() and MARKER not in dest.read_text(encoding="utf-8"):
        raise FileExistsError(f"refusing to overwrite unmanaged {dest}")
    shutil.copy2(src, dest)


def light_offsets(job, ppu):
    """Per DEF frame: (right, up, toward camera) world offset of the light from the anchor bone, following
    the DEF bolt's centroid part way (the DEF glow sits on the hand and the sword side)."""
    _, g, _, bone = JOBS[job]
    _, m0, _ = FX_CLIPS[job]
    d = h3def.read_def("cgtita.def")
    bones = json.load(open(WORK / "mesh2x/bones.json"))
    out = []
    for i, f in enumerate(d.groups[g]):
        ax, ay = bones["frames"][str(m0 + i + 1)][bone]["head"][:2]
        ys, xs = np.nonzero(lightning_mask(f, d.palette))
        cx, cy = (xs.mean(), ys.mean()) if len(xs) else (ax, ay)
        out += [CENTROID_PULL * (cx - ax) / ppu, -CENTROID_PULL * (cy - ay) / ppu, TOWARD_CAMERA]
    return out


def render(timeout=1500) -> int:
    cam = json.load(open(SPRITECAM))
    s, (sw, sh), (ox, oy) = cam["pxPerUnit"], cam["size"], cam["offset"]
    r_b, u_b, f_b = (np.array(cam[k]) for k in ("right", "up", "forward"))
    pos_b = r_b * ((sw / 2 - ox) / s) + u_b * ((oy - sh / 2) / s) - f_b * 8
    vmeta = json.loads((PREBAKE / "views/views_meta.json").read_text())

    # stage shaders, editor script and texture copies (the raw GLB colour downsized to the bake size)
    stage_file(HERE / "Homm3VfxLightLab.cs", PROJECT / "Assets/Editor/Homm3VfxLab/Homm3VfxLightLab.cs", True)
    for sh_ in ("Homm3VfxHexLitReplicaPoint.shader", "Homm3VfxDepthOnly.shader"):
        stage_file(HERE / sh_, PROJECT / "Assets/Homm3VfxLab/Shaders" / sh_, True)
    tex_entries = []
    for name, src in TEXTURES.items():
        dest = PROJECT / STAGE / f"titan_{name}_basecolor.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src is None:
            Image.open(PREBAKE / "source_basecolor.png").convert("RGB").resize((2048, 2048), Image.BOX).save(dest)
        else:
            shutil.copy2(PREBAKE / "textures" / src, dest)
        tex_entries.append({"name": name, "path": f"{STAGE}/{dest.name}", "lightPass": name == LIGHT_TEX})

    lin = lambda c: [float(x) for x in pl.srgb_to_lin(np.array(c))]
    sprite_sun = np.array(vmeta["views"]["sprite_f001"]["sunFrom"]["sand"])
    facings = []
    for name, v in vmeta["views"].items():
        if not name.startswith("battle_"):
            continue
        fr, rt_ = np.array(v["camForward"]), np.array(v["camRight"])
        up = np.cross(rt_, fr)
        facings.append({"name": name[len("battle_"):], "camFwd": list(M @ fr), "camUp": list(M @ up),
                        "sunTravel": list(-(M @ np.array(v["sunFrom"]["sand"]))), "orthoSize": 1.75})
    jobs = []
    for job, (clip, g, prefab, anchor) in JOBS.items():
        n = 7
        jobs.append({"name": job, "clip": f"{LAB}/{clip}.anim", "effectPrefab": f"{LAB}/{prefab}.prefab", "anchor": anchor,
                     "times": [(i + 1) / 12 for i in range(n)],               # GLB keys DEF frame i at (i+1)/12
                     "particleElapsed": [i / 12 + 1 / 48 for i in range(n)],  # event at 1/12, mid-cell sampling
                     "lightOffsets": light_offsets(job, s), "lightColor": lin(LIGHT_COLOR_SRGB), "lightRange": LIGHT_RANGE})
    spec = {"schema": "homm3_vfx_light_lab.v1", "prefabPath": f"{LAB}/h3_giant_upg_vfxlab.prefab", "outDir": str(RAW),
            "width": sw * SCALE, "height": sh * SCALE, "orthoSize": sh / 2 / s,
            "camPos": list(M @ pos_b), "camFwd": list(M @ f_b), "camUp": list(M @ u_b),
            "sunTravel": list(-(M @ sprite_sun)), "sunColor": lin(pl.SUN_SRGB), "ambient": lin(pl.AMBIENT_SRGB),
            "textures": tex_entries, "jobs": jobs, "facings": facings,
            "idleClip": f"{LAB}/Unit_Idle.anim", "idleTime": 1 / 12}
    RAW.mkdir(parents=True, exist_ok=True)
    spec_path = WORK / "light_lab_spec.json"
    spec_path.write_text(json.dumps(spec, indent=1))

    gate = subprocess.run([sys.executable, str(ROOT / "tools/homm3_def_retarget/memgate.py")], capture_output=True, text=True)
    print(gate.stdout.strip())
    if gate.returncode != 0:
        raise SystemExit("memgate not OK; not starting Unity")
    log = WORK / "light_lab_unity.log"
    cmd = [str(UNITY), "-batchmode", "-quit", "-projectPath", str(PROJECT), "-homm3VfxLightLabSpec", str(spec_path),
           "-executeMethod", "OldenEra.Homm3Vfx.Homm3VfxLightLab.RenderFromCommandLine", "-logFile", str(log)]
    done = UQ.run_cmd(cmd, kind="vfx_light_lab", timeout_s=timeout, direct=UNITY_DIRECT)
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    ok = done.returncode == 0 and "HOMM3_VFX_LIGHT_LAB_OK" in text
    for line in text.splitlines():
        if "HOMM3_VFX_LIGHT_LAB" in line or "error CS" in line or "Exception" in line or "Shader error" in line:
            print(line)
    print("exit", done.returncode, "OK" if ok else "FAILED", log)
    return 0 if ok else 1


# ----------------------------------------------------------------------------- compose
def load(path: Path, w: int, h: int) -> np.ndarray:
    return np.frombuffer(path.read_bytes(), np.float16).astype(np.float32).reshape(h, w, 4)[::-1]


def to_srgb8(rgb):
    return (np.clip(pl.lin_to_srgb(np.clip(rgb, 0, 1)), 0, 1) * 255 + 0.5).astype(np.uint8)


def mean_l(rgb_lin, mask):
    return float(pl.lin_to_lab(np.clip(rgb_lin[mask], 0, 1))[..., 0].mean()) if mask.any() else float("nan")


def compose() -> int:
    spec = json.loads((WORK / "light_lab_spec.json").read_text())
    W, H = spec["width"], spec["height"]
    d = h3def.read_def("cgtita.def")
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("arial.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    bg = np.array(pl.srgb_to_lin(np.array([46, 46, 46]) / 255.0), np.float32)
    metrics = {"proof": "Unity-editor render, replica Hex/Lit + point light (lab shader), not in-game",
               "lightColorSrgb": LIGHT_COLOR_SRGB, "lightRange": LIGHT_RANGE, "towardCamera": TOWARD_CAMERA,
               "centroidPull": CENTROID_PULL, "jobs": {}}
    for job, (clip, g, _, _) in JOBS.items():
        frames = d.groups[g]
        jd = RAW / job
        rows, gif = [], []
        def_l, dl, mesh = [], [], []
        for i, f in enumerate(frames):
            rgba = h3def.to_rgba(f, d.palette)
            body = (rgba[..., 3] == 255) & ~lightning_mask(f, d.palette)
            def_l.append(mean_l(pl.srgb_to_lin(rgba[..., :3] / 255.0), body))
            b = {t: load(jd / f"f{i}_base_{t}.bin", W, H) for t in TEXTURES}
            pli = load(jd / f"f{i}_plight_{LIGHT_TEX}.bin", W, H)
            fk, fw = load(jd / f"f{i}_fxk.bin", W, H), load(jd / f"f{i}_fxw.bin", W, H)
            fa = np.clip(1 - (fw[..., :3] - fk[..., :3]).mean(-1), 0, 1)
            mesh.append((b, pli, fk[..., :3], fa, rgba))
        target = [x - def_l[0] for x in def_l]
        base_l0 = None
        intens = []
        for i, (b, pli, fx, fa, _) in enumerate(mesh):
            m = (b[LIGHT_TEX][..., 3] > 0.5) & (fa < 0.1)
            own = mean_l(b[LIGHT_TEX][..., :3], m)
            if base_l0 is None:
                base_l0 = own
            # glow = lit minus this frame's own unlit render: the DEF's idle is flat in L, so its rise over
            # frame 0 is read as light, while the mesh's pose-driven shading change is left alone
            f_l = lambda k: mean_l(b[LIGHT_TEX][..., :3] + k * pli[..., :3], m) - own
            lo, hi = 0.0, 64.0
            if f_l(0.0) >= target[i]:
                k = 0.0
            else:
                for _ in range(40):
                    mid = (lo + hi) / 2
                    lo, hi = (mid, hi) if f_l(mid) < target[i] else (lo, mid)
                k = (lo + hi) / 2
            intens.append(k)
            dl.append({"defDeltaL": round(target[i], 2), "meshPoseDeltaL": round(own - base_l0, 2), "fitIntensity": round(k, 3),
                       "meshLitDeltaL": round(f_l(k), 2)})
        metrics["jobs"][job] = {"defBodyMeanL": [round(x, 2) for x in def_l], "frames": dl}

        for i, (b, pli, fx, fa, rgba) in enumerate(mesh):
            def over(rgb, a):  # premultiplied layer over the flat background
                return rgb + (1 - a[..., None]) * bg
            panels = [("DEF g%d f%d" % (g, i), np.kron(rgba, np.ones((SCALE, SCALE, 1), np.uint8)))]
            for t in TEXTURES:
                panels.append((f"mesh {t}", b[t]))
            lit = b[LIGHT_TEX][..., :3] + intens[i] * pli[..., :3]
            fxonly = fx + (1 - fa[..., None]) * b[LIGHT_TEX][..., :3]
            fxlit = fx + (1 - fa[..., None]) * lit
            a_body = b[LIGHT_TEX][..., 3]
            a_all = np.maximum(a_body, fa)
            panels.append((f"{LIGHT_TEX} + VFX", np.dstack([fxonly, a_all])))
            panels.append((f"{LIGHT_TEX} + VFX + light x{intens[i]:.1f}", np.dstack([fxlit, a_all])))
            imgs = []
            for label, p in panels:
                if p.dtype == np.uint8:
                    a = p[..., 3:] / 255.0
                    rgb = (p[..., :3] / 255.0) * a + (to_srgb8(bg[None, None]) / 255.0) * (1 - a)
                    im = (rgb * 255 + 0.5).astype(np.uint8)
                else:
                    im = to_srgb8(over(p[..., :3], np.clip(p[..., 3], 0, 1)))
                imgs.append((label, im))
            rows.append(imgs)
        # crop to the union of content over the clip
        occ = np.zeros((H, W), bool)
        for i, (b, _, _, fa, rgba) in enumerate(mesh):
            occ |= (b["raw"][..., 3] > 0) | (fa > 0.02) | np.kron(rgba[..., 3] > 0, np.ones((SCALE, SCALE), bool))
        ys, xs = np.nonzero(occ)
        y0, y1, x0, x1 = max(0, ys.min() - 8), min(H, ys.max() + 8), max(0, xs.min() - 8), min(W, xs.max() + 8)
        pw, ph = x1 - x0, y1 - y0
        ncol = len(rows[0])
        sheet = Image.new("RGB", (pw * ncol, (ph + 22) * len(rows) + 26), (46, 46, 46))
        dr = ImageDraw.Draw(sheet)
        for r, imgs in enumerate(rows):
            fr = Image.new("RGB", (pw * ncol, ph + 22), (46, 46, 46))
            fdr = ImageDraw.Draw(fr)
            for c, (label, im) in enumerate(imgs):
                fr.paste(Image.fromarray(im[y0:y1, x0:x1]), (c * pw, 22))
                fdr.text((c * pw + 4, 3), label, font=font, fill=(255, 255, 0))
            sheet.paste(fr, (0, r * (ph + 22)))
            gif.append(fr)
        dr.text((4, sheet.height - 22), f"Titan {job}: 1 DEF px = {SCALE} px | Unity editor, replica Hex/Lit + point light "
                f"(lab shader), sand sun | light fitted to DEF body mean-L rise | not in-game", font=font, fill=(220, 220, 210))
        sheet.save(OUT / f"titan_{job}_prebake_vfx_light_sheet.png")
        gif[0].save(OUT / f"titan_{job}_prebake_vfx_light.gif", save_all=True, append_images=gif[1:], duration=1000 // 12 * 2, loop=0)
        print(job, "intensities", [round(k, 2) for k in intens], "target", [round(x, 1) for x in target])

    # idle, four facings
    fdir = RAW / "idle_facings"
    names = [f["name"] for f in spec["facings"]]
    idle = h3def.to_rgba(d.groups[2][0], d.palette)
    cells = []
    for t in TEXTURES:
        row = []
        for n in names:
            p = load(fdir / f"{n}_base_{t}.bin", W, H)
            row.append((f"{t} {n}", to_srgb8(p[..., :3] + (1 - np.clip(p[..., 3:], 0, 1)) * bg), p[..., 3] > 0))
        cells.append(row)
    occ = np.zeros((H, W), bool)
    for row in cells:
        for _, _, a in row:
            occ |= a
    ys, xs = np.nonzero(occ)
    y0, y1, x0, x1 = max(0, ys.min() - 6), min(H, ys.max() + 6), max(0, xs.min() - 6), min(W, xs.max() + 6)
    pw, ph = x1 - x0, y1 - y0
    dimg = Image.fromarray(idle).resize((idle.shape[1] * SCALE, idle.shape[0] * SCALE), Image.NEAREST)
    dimg = dimg.crop(dimg.getbbox())
    sheet = Image.new("RGB", (dimg.width + 16 + pw * len(names), (ph + 20) * len(cells) + 24), (46, 46, 46))
    sheet.paste(dimg, (4, 24), dimg)
    dr = ImageDraw.Draw(sheet)
    dr.text((4, 4), "DEF idle", font=font, fill=(255, 255, 0))
    for r, row in enumerate(cells):
        for c, (label, im, _) in enumerate(row):
            x, y = dimg.width + 16 + c * pw, r * (ph + 20)
            sheet.paste(Image.fromarray(im[y0:y1, x0:x1]), (x, y + 20))
            dr.text((x + 4, y + 2), label, font=font, fill=(255, 255, 0))
    dr.text((4, sheet.height - 20), "Titan idle, battle camera 40 deg down, sand sun camera-relative | Unity editor, replica Hex/Lit | not in-game",
            font=font, fill=(220, 220, 210))
    sheet.save(OUT / "titan_idle_facings_unity.png")
    (OUT / "light_lab_metrics.json").write_text(json.dumps(metrics, indent=1))
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(render() if sys.argv[1:] == ["render"] else compose())
