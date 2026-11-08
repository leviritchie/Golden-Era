"""YouTube showcase video: the original HoMM3 DEF animation next to the shipped 3D animation (60 fps, with VFX).

    python tools/homm3_authenticity/showcase_video.py run --units h3_pikeman,h3_seraph --work <dir> --out <mp4>
    python tools/homm3_authenticity/showcase_video.py stage|render|assemble ...      (the same steps one at a time)
    python tools/homm3_authenticity/showcase_video.py full     (every Castle unit: one Unity job per unit, resumable,
                                                                waits for --min-free-gb on V: before each unit)

Per unit (render order = --units order):
  left   the DEF frames the authenticity board uses (sources.def_reference), held on the board's DEF grid
         (frame i at start + i * step of the GLB clip), nearest-neighbour scaled;
  right  the GLB the delivery selection pins (sources.shipped_glb: delivered_idle_retimed.glb + inputs/basecolor.png)
         rendered by the vanilla-style VFX lab (tools/homm3_vfx/unity/Homm3VanillaStyleVfxLab.cs, Hex/Lit replica,
         particles stepped at 60 Hz) through the Unity queue, one frame every 1/60 s of clip time (the Animator samples
         the clip continuously, so motion is interpolated, not held), under the board's battle camera (ortho,
         40 deg elevation, azimuth -60 from glTF +Z: the unit faces screen right). Units whose selection row is
         vfxAuthority vanilla_style get their compiled effect rows (trigger = compiled normalizedTime * clip length,
         boneLocalRot from the compiled record); the lab's PPv2-like bloom is applied on the GPU.
A streaming consumer turns each raw half-float frame into a panel PNG and deletes the raw file as Unity writes them,
so the raw renders never pile up on V:. Each unit becomes one H.264 (NVENC) segment; the segments are concatenated.

Proof tier: generated artifact (Unity editor lab render with replica shaders), not an in-game capture. Projectiles and
other engine-spawned battle effects are not part of the unit's own VFX and are not drawn.
"""
from __future__ import annotations

import argparse
import os
import json
import math
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sources import ROOT, def_reference, shipped_glb, unit_ids  # noqa: E402

sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
import vanilla_style_lab as VSL  # noqa: E402  (also loads the Unity queue module as VSL.UQ)

W, H, FPS = 1920, 1080, 60
PANEL_TOP = 80                    # header strip above the two panels
PANEL_W, PANEL_H = 960, H - PANEL_TOP
FIT_W, FIT_H = 900, 860           # the unit's whole-motion box fits in this
FEET_Y = 990                      # bottom of the fitted box, both panels
BG = (44, 46, 50)
FG = (226, 228, 232)
DIM = (150, 154, 160)
WORKERS = 6                       # consumer threads (PIL resize/PNG encode release the GIL)
SS = 1.25                         # Unity render density over the final panel px (the lab renders without MSAA; downsampled)
BATTLE = {"elevDeg": 40.0, "azimuthDeg": -60.0}   # board.py BATTLE
SHOOTERS = {"h3_archer", "h3_marksman", "h3_crossbowman", "h3_monk", "h3_zealot", "h3_priest"}  # ranged in battle
ORDER = ("Unit_Idle", "Unit_Move", "Unit_Mouseover", "Unit_AttackFront", "Unit_ShootFront", "Unit_Defence",
         "Unit_Hitted", "Unit_Death")
LABEL = {"Unit_Idle": "Idle", "Unit_Move": "Move", "Unit_Mouseover": "Mouse-over", "Unit_AttackFront": "Melee attack",
         "Unit_ShootFront": "Ranged attack", "Unit_Defence": "Defend", "Unit_Hitted": "Hit", "Unit_Death": "Death"}
ONE_SHOT_TAIL_S = 0.35            # rendered past a one-shot's end: the pose holds while particles finish
MIN_SHOW_S = 2.0                  # short clips repeat until they have shown this long (2-4 plays)
DEATH_HOLD_S = 0.6
TITLE_S = 2.2
INTRO_S = 4.0
NOTES_S = 4.5
STAGE_SUB = "showcase_castle"     # under the lab's marker-managed asset root
MAX_PENDING_FRAMES = 40           # Unity waits while this many raw frames (~9.6 MB each) are unconsumed
LAB_CLASS = "Homm3ShowcaseVfxLab"
LAB_SCRIPT = "Assets/Editor/Homm3Showcase/Homm3ShowcaseVfxLab.cs"
LAB_METHOD = f"OldenEra.Homm3Vfx.{LAB_CLASS}.RunFromCommandLine"

CASTLE = [  # (lab sid, display name, tier, line role)
    ("h3_pikeman", "Pikeman", 1, "Basic"), ("h3_halberdier", "Halberdier", 1, "Upgraded"),
    ("h3_glaivier", "Glaivier", 1, "Alternate upgrade"),
    ("h3_archer", "Archer", 2, "Basic"), ("h3_marksman", "Marksman", 2, "Upgraded"),
    ("h3_crossbowman", "Crossbowman", 2, "Alternate upgrade"),
    ("h3_griffin", "Griffin", 3, "Basic"), ("h3_royal_griffin", "Royal Griffin", 3, "Upgraded"),
    ("h3_battle_griffin", "Battle Griffin", 3, "Alternate upgrade"),
    ("h3_swordsman", "Swordsman", 4, "Basic"), ("h3_crusader", "Crusader", 4, "Upgraded"),
    ("h3_guardsman", "Guardsman", 4, "Alternate upgrade"),
    ("h3_monk", "Monk", 5, "Basic"), ("h3_zealot", "Zealot", 5, "Upgraded"), ("h3_priest", "Priest", 5, "Alternate upgrade"),
    ("h3_cavalier", "Cavalier", 6, "Basic"), ("h3_champion", "Champion", 6, "Upgraded"),
    ("h3_justiciar", "Justiciar", 6, "Alternate upgrade"),
    ("h3_angel", "Angel", 7, "Basic"), ("h3_archangel", "Archangel", 7, "Upgraded"), ("h3_seraph", "Seraph", 7, "Alternate upgrade"),
]
INFO = {u: (n, t, r) for u, n, t, r in CASTLE}


def font(size: int, bold=False):
    for f in (("C:/Windows/Fonts/segoeuib.ttf",) if bold else ()) + ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _n(v):
    v = np.asarray(v, np.float64)
    return v / np.linalg.norm(v)


def battle_dirs():
    a, e = math.radians(BATTLE["azimuthDeg"]), math.radians(BATTLE["elevDeg"])
    to_cam = (np.array([0, 0, 1.0]) * math.cos(a) + np.array([1.0, 0, 0]) * math.sin(a)) * math.cos(e) + np.array([0, 1.0, 0]) * math.sin(e)
    fwd = -_n(to_cam)
    right = _n(np.cross(fwd, [0, 1.0, 0]))
    return fwd, right, np.cross(right, fwd)


def g2u(v):
    """glTF -> Unity (glTFast mirrors X)."""
    return [-float(v[0]), float(v[1]), float(v[2])]


# ------------------------------------------------------------------ stage: plan + Unity job
def plan_unit(unit: str, work: Path) -> dict:
    import torch
    import raster as R
    from gltf_scene import Scene

    lab, src = unit_ids(unit)
    sel = shipped_glb(lab, src)
    if sel["mode"] != "shipped" or not sel.get("albedo"):
        raise SystemExit(f"{unit}: no pinned shipped GLB + basecolor ({sel['notes']})")
    row = sel["row"] or {}
    ref = def_reference(src)
    scene = Scene(sel["path"], body_name=src, skip_meshes=tuple((row.get("deferMeshes") or {})))
    defs = {c["clip"]: c for c in ref["clips"]}
    clips = []
    for name in ORDER:
        if name not in defs or name not in scene.anims:
            continue
        if name == "Unit_ShootFront" and lab not in SHOOTERS:
            continue   # melee units never play their shoot clip in battle
        c = defs[name]
        rng = scene.clip_range(name)
        n = len(c["frames"])
        loop = bool(c.get("loop"))
        tk = int((c.get("loop") or {}).get("transitionKeys", 0))
        m = (n - 1) + ((1 + tk) if loop else 0)
        step = rng["duration"] / m if m > 0 else 1 / 12
        length = rng["end"]                         # Unity clip length (keys from 0), what the Animator normalises by
        frames = int(round(length * FPS)) if loop else int(math.ceil((length + ONE_SHOT_TAIL_S) * FPS))
        shown = frames / FPS
        reps = 2 if name == "Unit_Idle" else max(2, min(4, math.ceil(MIN_SHOW_S / shown)))
        clips.append({"name": name, "n": n, "start": rng["start"], "step": step, "length": length, "loop": loop,
                      "frames": frames, "reps": reps, "defFrames": c["frames"],
                      "holdS": DEATH_HOLD_S if name == "Unit_Death" else 0.0})
    if not clips:
        raise SystemExit(f"{unit}: no clip in both the DEF reference and the GLB")

    # body box under the battle camera: every 60 Hz sample of every clip (GPU skinning)
    fwd, right, up = battle_dirs()
    dev = R.resolve_device("cuda")
    mesh = R.DeviceMesh(scene, dev, np.zeros((2, 2, 4), np.float32))
    rt, ut = (torch.as_tensor(x, dtype=torch.float32, device=dev) for x in (right, up))
    lo, hi = [1e9, 1e9], [-1e9, -1e9]
    for c in clips:
        t = np.minimum(np.arange(1, c["frames"] + 1) / FPS, c["length"])
        Jm, mw = scene.pose(c["name"], t)
        P, _ = mesh.skin(Jm, mw)
        u, v = (P @ rt), (P @ ut)
        lo = [min(lo[0], float(u.min())), min(lo[1], float(v.min()))]
        hi = [max(hi[0], float(u.max())), max(hi[1], float(v.max()))]
    del mesh
    torch.cuda.empty_cache()
    bw, bh = hi[0] - lo[0], hi[1] - lo[1]
    ppu = min(FIT_W / bw, FIT_H / bh)               # final px per world unit
    c_b = right * (lo[0] + hi[0]) / 2 + up * (lo[1] + hi[1]) / 2
    y_b = FEET_Y - bh * ppu / 2                      # body-box centre, final px (y down)
    dy = y_b - (PANEL_TOP + PANEL_H / 2)
    centre = c_b + up * (dy / ppu)
    from_dir = _n(-0.55 * right + 0.85 * up - 0.45 * fwd)   # key light from upper camera-left, toward the camera
    cam = {"camRight": g2u(right), "camUp": g2u(up), "camForward": g2u(fwd), "camCentre": g2u(centre),
           "orthoSize": PANEL_H / 2 / ppu, "width": int(round(PANEL_W * SS)), "height": int(round(PANEL_H * SS))}

    # DEF union box (alpha > 0, shadow included) over every frame shown
    dlo, dhi = [1e9, 1e9], [-1e9, -1e9]
    for c in clips:
        for p in c["defFrames"]:
            bb = Image.open(p).getchannel("A").getbbox()
            if bb:
                dlo = [min(dlo[0], bb[0]), min(dlo[1], bb[1])]
                dhi = [max(dhi[0], bb[2]), max(dhi[1], bb[3])]

    # effects: the compiled rows of a vanilla_style unit
    effects, fx_note = [], "no unit VFX in the shipped selection row"
    if row.get("vfxAuthority") == "vanilla_style":
        spec, tier = VSL.unit_spec(lab)
        if tier != "shipped":
            raise SystemExit(f"{unit}: selection row is vanilla_style but the spec is a {tier}")
        comp = json.loads((ROOT / "tools/homm3_vfx/vanilla_style/compiled" / f"{lab}.json").read_text(encoding="utf-8"))
        rows = {r["id"]: r for r in comp["rows"]}
        lengths = comp["clipLengths"]
        for e in VSL.spec_layer_effects(lab, spec):
            lid = next(l["id"] for l in spec["layers"] if e["id"].startswith(l["id"] + "_"))
            r = rows[f"vs_{lab}_{lid}"]
            layer = next(l for l in spec["layers"] if l["id"] == lid)
            clip = layer["triggers"][0]["clip"]
            nt = r["trigger"]["normalizedTime"]
            e["triggers"] = [{"clip": clip, "time": nt[0] * lengths[clip]}]
            e["stops"] = [] if nt[1] >= 1.0 else [{"clip": clip, "time": nt[1] * lengths[clip]}]
            if r["vanillaStyle"].get("boneLocalRot"):
                e["rot"] = r["vanillaStyle"]["boneLocalRot"]
            effects.append(e)
        fx_note = "compiled vanilla-style rows: " + ", ".join(sorted({e["id"] for e in effects}))
    plan = {"unit": unit, "lab": lab, "src": src, "glb": str(sel["path"]), "glbSha256": sel["sha256"],
            "selection": sel["selection"], "albedo": str(sel["albedo"]), "clips": clips, "cam": cam,
            "sunTravelUnity": g2u(-from_dir), "ppu": ppu, "bodyBox": [lo, hi], "defBox": [dlo, dhi],
            "effects": effects, "fxNote": fx_note}
    d = work / unit
    d.mkdir(parents=True, exist_ok=True)
    (d / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    return plan


def panel_id(unit):
    return f"sc_{unit}"


def stage_showcase_lab() -> None:
    """The vanilla-style lab with backpressure, generated from the one lab source (never edited by hand): a renamed copy
    whose frame loop waits while job.maxPendingFrames raw frames are unconsumed, so V: scratch stays bounded whatever
    the consumer's speed; a consumer stalled for 10 min fails the job instead of filling the disk. Particles step on a
    fixed 1/60 s, so waiting does not change a frame."""
    src = (VSL.SRC / "Homm3VanillaStyleVfxLab.cs").read_text(encoding="utf-8")
    subs = [("public static class Homm3VanillaStyleVfxLab", f"public static class {LAB_CLASS}"),
            ("public PanelDef[] panels; public bool requireCompleteEffects; }",
             "public PanelDef[] panels; public bool requireCompleteEffects; public int maxPendingFrames; }"),
            ('File.WriteAllBytes(Path.Combine(dir, c.name + "_" + frame.ToString("000") + ".bin"), read.GetRawTextureData());',
             'File.WriteAllBytes(Path.Combine(dir, c.name + "_" + frame.ToString("000") + ".bin"), read.GetRawTextureData());\n'
             '                    if (job.maxPendingFrames > 0)\n'
             '                    {\n'
             '                        var waitSw = System.Diagnostics.Stopwatch.StartNew();\n'
             '                        while (Directory.GetFiles(dir, "*.bin").Length > job.maxPendingFrames)\n'
             '                        {\n'
             '                            if (waitSw.Elapsed.TotalSeconds > 600) throw new InvalidOperationException("showcase frame consumer stalled for 600 s: " + dir);\n'
             '                            System.Threading.Thread.Sleep(50);\n'
             '                        }\n'
             '                    }')]
    for a, b in subs:
        if src.count(a) != 1:
            raise SystemExit(f"showcase lab: the lab source changed; {a[:60]!r} matched {src.count(a)} times")
        src = src.replace(a, b)
    dst = VSL.PROJECT / LAB_SCRIPT
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.is_file() or dst.read_text(encoding="utf-8") != src:
        dst.write_text(src, encoding="utf-8")


def stage(units, work: Path) -> Path:
    lib = VSL.stage_common()
    stage_showcase_lab()
    dest_root = VSL.PROJECT / VSL.ASSET_ROOT / STAGE_SUB
    panels = []
    for u in units:
        p = plan_unit(u, work)
        dest = dest_root / u
        dest.mkdir(parents=True, exist_ok=True)
        VSL.stage_file(Path(p["glb"]), dest / f"{u}_shipped.glb")
        VSL.stage_file(Path(p["albedo"]), dest / "basecolor.png")
        body = {"kind": "glb", "glbAssetPath": f"{VSL.ASSET_ROOT}/{STAGE_SUB}/{u}/{u}_shipped.glb",
                "texture": f"{STAGE_SUB}/{u}/basecolor.png", "emissionTex": "", "emissionColor": [0, 0, 0],
                "cellST": [], "emissionMin": 0, "blinkSpeed": 0, "blinkPower": 0, "overlays": []}
        clips = [{"name": c["name"], "keys": c["n"], "frames": c["frames"], "frameStep": 1.0 / FPS, "boilCells": [],
                  "loop": c["loop"]} for c in p["clips"]]
        panels.append({"id": panel_id(u), "body": body, "clips": clips, "effects": p["effects"], "flipbooks": [],
                       "oldLights": [], "sunTravelUnity": p["sunTravelUnity"], "warmupS": 1.0, **p["cam"]})
        print(f"staged {u}: {len(clips)} clips, {sum(c['frames'] for c in clips)} frames, {p['fxNote']}", flush=True)
    raw = work / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    job = {"schema": "homm3_vanilla_style_lab.v1", "assetRoot": VSL.ASSET_ROOT, "materialLib": str(lib),
           "outDir": str(raw), "requireCompleteEffects": False, "maxPendingFrames": MAX_PENDING_FRAMES, "panels": panels}
    sp = work / f"lab_job_{'_'.join(u.replace('h3_', '') for u in units)[:80]}.json"
    sp.write_text(json.dumps(job, indent=1), encoding="utf-8")
    return sp


# ------------------------------------------------------------------ render: Unity queue + streaming consumer
def _bloom_t(rgb, threshold=1.0, knee=0.107, intensity=2 ** 0.3 - 1, levels=3):
    """vanilla_style_lab.bloom on the GPU: (3, H, W) linear -> same."""
    import torch
    import torch.nn.functional as TF
    k = torch.tensor([1.0, 2.0, 1.0], device=rgb.device) / 4

    def blur(x):
        x = TF.pad(x[None], (1, 1, 1, 1), mode="replicate")[0]
        x = k[0] * x[:, :, :-2] + k[1] * x[:, :, 1:-1] + k[2] * x[:, :, 2:]
        return k[0] * x[:, :-2] + k[1] * x[:, 1:-1] + k[2] * x[:, 2:]

    def down(x):
        h, w = x.shape[1] // 2 * 2, x.shape[2] // 2 * 2
        return TF.avg_pool2d(x[None, :, :h, :w], 2)[0]

    def up(x, shape):
        y = x.repeat_interleave(2, 1).repeat_interleave(2, 2)
        y = TF.pad(y[None], (0, max(0, shape[2] - y.shape[2]), 0, max(0, shape[1] - y.shape[1])), mode="replicate")[0]
        return blur(y[:, :shape[1], :shape[2]])

    kn = threshold * knee + 1e-5
    br = rgb.max(0, keepdim=True).values
    rq = (br - (threshold - kn)).clamp(0, 2 * kn)
    rq = 0.25 / kn * rq * rq
    pre = rgb * torch.maximum(rq, br - threshold) / br.clamp_min(1e-4)
    mips = [blur(down(pre))]
    for _ in range(levels):
        mips.append(blur(down(mips[-1])))
    acc = mips[-1]
    for m in reversed(mips[:-1]):
        acc = m + up(acc, m.shape)
    return rgb + up(acc, rgb.shape) * intensity


def finish_frame(raw: np.ndarray, dev) -> Image.Image:
    import torch
    t = torch.as_tensor(raw, device=dev).float().flip(0)          # Unity rows are bottom-up
    bg = torch.tensor([(c / 255.0) for c in BG], device=dev)
    bg = torch.where(bg <= 0.04045, bg / 12.92, ((bg + 0.055) / 1.055) ** 2.4)
    rgb = t[..., :3] + bg * (1 - t[..., 3:4].clamp(0, 1))
    rgb = _bloom_t(rgb.permute(2, 0, 1)).permute(1, 2, 0).clamp(0, 1)
    s = torch.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * rgb.pow(1 / 2.4) - 0.055)
    im = Image.fromarray((s * 255 + 0.5).to(torch.uint8).cpu().numpy())
    return im.resize((PANEL_W, PANEL_H), Image.LANCZOS)


class Consumer(threading.Thread):
    """Turns raw/<panel>/<clip>_NNN.bin into <unit>/mesh/<clip>_NNN.png and deletes the .bin, as Unity writes them."""

    def __init__(self, work: Path, units):
        super().__init__(daemon=True)
        import torch
        self.dev = torch.device("cuda")
        if not torch.cuda.is_available():
            raise SystemExit("showcase: CUDA required for the frame consumer (GPU-first; no CPU fallback)")
        self.work, self.units = work, units
        self.todo = []
        for u in units:
            p = json.loads((work / u / "plan.json").read_text(encoding="utf-8"))
            (work / u / "mesh").mkdir(parents=True, exist_ok=True)
            for c in p["clips"]:
                for i in range(c["frames"]):
                    self.todo.append((u, p["cam"]["width"], p["cam"]["height"], c["name"], i))
        self.stop = threading.Event()
        self.done = 0
        self.error = None

    def _one(self, src: Path, out: Path, w: int, h: int):
        raw = np.fromfile(src, np.float16).reshape(h, w, 4)
        finish_frame(raw, self.dev).save(out, compress_level=1)
        src.unlink()

    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        try:
            pending = list(self.todo)
            inflight = []
            with ThreadPoolExecutor(WORKERS) as pool:
                while pending or inflight:
                    for f in [f for f in inflight if f.done()]:
                        f.result()
                        inflight.remove(f)
                        self.done += 1
                    if not pending or len(inflight) >= 2 * WORKERS:
                        time.sleep(0.02)
                        continue
                    u, w, h, clip, i = pending[0]
                    src = self.work / "raw" / panel_id(u) / f"{clip}_{i:03d}.bin"
                    out = self.work / u / "mesh" / f"{clip}_{i:03d}.png"
                    if out.is_file() and not src.exists():
                        pending.pop(0)
                        self.done += 1
                        continue
                    ready = src.is_file() and src.stat().st_size == w * h * 8 and (
                        self.stop.is_set() or time.time() - src.stat().st_mtime > 1.5 or self._next_exists(pending))
                    if not ready:
                        if self.stop.is_set() and not src.exists():
                            raise RuntimeError(f"Unity finished without {src}")
                        time.sleep(0.2)
                        continue
                    inflight.append(pool.submit(self._one, src, out, w, h))
                    pending.pop(0)
        except Exception as e:  # noqa: BLE001  reported by the caller
            self.error = e

    def _next_exists(self, pending):
        if len(pending) < 2:
            return False
        u, _, _, clip, i = pending[1]
        return (self.work / "raw" / panel_id(u) / f"{clip}_{i:03d}.bin").exists()


def render(units, work: Path, spec: Path, timeout_s: int) -> None:
    cons = Consumer(work, units)
    cons.start()
    t0 = time.time()
    res = VSL.UQ.launch(kind="castle_showcase_render", method=LAB_METHOD,
                        args=["-homm3VanillaStyleSpec", str(spec)], project=VSL.PROJECT, log=work / "unity_render.log",
                        inputs=[spec], graphics=True, requester="showcase_video.py castle", timeout_s=timeout_s,
                        direct=VSL.UNITY_DIRECT)
    cons.stop.set()
    print(f"unity {res.get('status')} after {time.time() - t0:.0f}s: {res.get('error')}", flush=True)
    cons.join()
    if res.get("status") != "ok":
        raise SystemExit(f"Unity render failed: {res.get('error')} (log {work / 'unity_render.log'})")
    if cons.error:
        raise SystemExit(f"frame consumer failed: {cons.error}")
    print(f"consumed {cons.done}/{len(cons.todo)} frames in {time.time() - t0:.0f}s", flush=True)


# ------------------------------------------------------------------ assemble
def text_c(d: ImageDraw.ImageDraw, xy, s, f, fill):
    b = d.textbbox((0, 0), s, font=f)
    d.text((xy[0] - (b[2] - b[0]) / 2 - b[0], xy[1]), s, font=f, fill=fill)


def card(lines) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    for y, s, size, bold, col in lines:
        text_c(d, (W / 2, y), s, font(size, bold), col)
    return im


def def_layer(plan) -> dict:
    """DEF frame path -> RGBA image scaled into the left panel, plus its paste offset."""
    (x0, y0), (x1, y1) = plan["defBox"]
    bw, bh = x1 - x0, y1 - y0
    s = min(FIT_W / bw, FIT_H / bh)
    ox = int(round(PANEL_W / 2 - bw * s / 2))
    oy = int(round(FEET_Y - bh * s))
    cache = {}
    for c in plan["clips"]:
        for p in c["defFrames"]:
            if p in cache:
                continue
            im = Image.open(p).convert("RGBA").crop((x0, y0, x1, y1))
            cache[p] = im.resize((max(1, round(bw * s)), max(1, round(bh * s))), Image.NEAREST)
    return {"frames": cache, "at": (ox, oy)}


def def_index(c, t):
    if c["loop"]:
        t = t % c["length"] if c["length"] > 0 else 0
    i = math.floor((t - c["start"]) / c["step"] + 1e-6)
    return min(max(i, 0), c["n"] - 1)


def unit_frames(plan, work: Path):
    """Yields the unit's 1920x1080 frames: title card, then every clip (repeated) DEF | mesh."""
    name, tier, role = INFO.get(plan["lab"], (plan["lab"], "?", ""))
    title = card([(430, name, 96, True, FG), (560, f"Castle  \u00b7  Tier {tier}  \u00b7  {role}", 40, False, DIM)])
    for _ in range(int(TITLE_S * FPS)):
        yield title
    dl = def_layer(plan)
    hdr = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(hdr)
    f_small, f_head = font(26), font(34, True)
    text_c(d, (PANEL_W / 2, 26), "Original HoMM3 sprite", f_small, DIM)
    text_c(d, (PANEL_W + PANEL_W / 2, 26), "New 3D animation  \u00b7  60 fps", f_small, DIM)
    mesh_dir = work / plan["unit"] / "mesh"
    for c in plan["clips"]:
        base = hdr.copy()
        bd = ImageDraw.Draw(base)
        text_c(bd, (W / 2, H - 58), f"{name}  \u2014  {LABEL[c['name']]}", f_head, FG)
        meshes = [Image.open(mesh_dir / f"{c['name']}_{i:03d}.png").convert("RGB") for i in range(c["frames"])]
        seq = list(range(c["frames"])) + [c["frames"] - 1] * int(round(c["holdS"] * FPS))
        for _ in range(c["reps"]):
            for k in seq:
                t = (k + 1) / FPS
                fr = base.copy()
                fr.paste(meshes[k], (PANEL_W, PANEL_TOP))
                df = dl["frames"][c["defFrames"][def_index(c, t)]]
                fr.paste(df, dl["at"], df)
                # the clip label band and the divider sit over the mesh panel's edges; redraw them on top
                dd = ImageDraw.Draw(fr)
                dd.rectangle([0, H - 66, W, H], fill=BG)
                dd.line([(PANEL_W, PANEL_TOP + 20), (PANEL_W, H - 80)], fill=(64, 67, 72), width=2)
                text_c(dd, (W / 2, H - 58), f"{name}  \u2014  {LABEL[c['name']]}", f_head, FG)
                yield fr


def encode(frames, out: Path):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq",
           "-rc", "vbr", "-cq", "18", "-b:v", "0", "-maxrate", "40M", "-bufsize", "80M", "-profile:v", "high",
           "-pix_fmt", "yuv420p", "-g", "120", "-bf", "2", "-r", str(FPS), str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = 0
    for fr in frames:
        p.stdin.write(fr.tobytes())
        n += 1
    p.stdin.close()
    if p.wait():
        raise SystemExit(f"ffmpeg failed on {out}")
    return n


def intro_frames():
    im = card([(380, "Heroes of Might and Magic III: Castle", 72, True, FG),
               (490, "Every Castle unit's animations rebuilt in 3D for Olden Era", 40, False, FG),
               (600, "Left: the original HoMM3 sprite at its own timing    Right: the new 3D animation at 60 fps", 30, False, DIM)])
    for _ in range(int(INTRO_S * FPS)):
        yield im


def unit_segment(u: str, work: Path, keep_frames: bool) -> Path:
    i = [c[0] for c in CASTLE].index(u) + 1 if u in [c[0] for c in CASTLE] else 99
    plan = json.loads((work / u / "plan.json").read_text(encoding="utf-8"))
    s = work / f"seg_{i:02d}_{u}.mp4"
    t0 = time.time()
    n = encode(unit_frames(plan, work), s)
    print(f"segment {u}: {n} frames ({n / FPS:.1f}s) in {time.time() - t0:.0f}s", flush=True)
    if not keep_frames:
        shutil.rmtree(work / u / "mesh", ignore_errors=True)
    return s


def concat(segs, work: Path, out: Path) -> None:
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in segs), encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
    print("wrote", out, flush=True)


def notes_frames():
    im = card([(400, "Download link in the description", 56, True, FG),
               (520, "Spot a problem? Point it out in the comments", 40, False, FG),
               (590, "so it can be fixed in a future update.", 40, False, FG)])
    for _ in range(int(NOTES_S * FPS)):
        yield im


def intro_segment(work: Path) -> list:
    out = []
    for name, gen in (("seg_00_intro.mp4", intro_frames), ("seg_00b_notes.mp4", notes_frames)):
        s = work / name
        if not s.exists():
            encode(gen(), s)
        out.append(s)
    return out


def assemble(units, work: Path, out: Path, intro: bool, keep_frames: bool):
    segs = intro_segment(work) if intro else []
    segs += [unit_segment(u, work, keep_frames) for u in units]
    concat(segs, work, out)


def free_gb(path: Path) -> float:
    return shutil.disk_usage(str(path.anchor or path)).free / 2 ** 30


def full(units, work: Path, out: Path, intro: bool, timeout_s: int, min_free_gb: float) -> None:
    """One unit at a time: wait for disk headroom, stage, render, encode its segment, delete its frames, unstage.
    Units whose segment already exists are skipped (resumable). Ends with the intro + concat of every segment."""
    segs = intro_segment(work) if intro else []
    for u in units:
        i = [c[0] for c in CASTLE].index(u) + 1 if u in [c[0] for c in CASTLE] else 99
        seg = work / f"seg_{i:02d}_{u}.mp4"
        if seg.exists() and seg.stat().st_size > 0:
            print(f"skip {u}: {seg.name} exists", flush=True)
            segs.append(seg)
            continue
        while free_gb(work) < min_free_gb:
            print(f"waiting: V: free {free_gb(work):.1f} GB < {min_free_gb} GB", flush=True)
            time.sleep(120)
        print(f"=== {u}  (V: free {free_gb(work):.1f} GB)", flush=True)
        spec = stage([u], work)
        try:
            render([u], work, spec, timeout_s)
            tmp = unit_segment(u, work, keep_frames=False)
        finally:
            shutil.rmtree(work / "raw", ignore_errors=True)
            cleanup_stage([u], lab_script=False)
        segs.append(tmp)
    concat(segs, work, out)


def cleanup_stage(units, lab_script=True):
    if lab_script:
        d = (VSL.PROJECT / LAB_SCRIPT).parent
        shutil.rmtree(d, ignore_errors=True)
        m = Path(str(d) + ".meta")
        if m.exists():
            m.unlink()
    dest_root = VSL.PROJECT / VSL.ASSET_ROOT
    for u in units:
        for p in (dest_root / STAGE_SUB / u, dest_root / f"clips_{panel_id(u)}"):
            shutil.rmtree(p, ignore_errors=True)
            m = Path(str(p) + ".meta")
            if m.exists():
                m.unlink()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=("run", "full", "stage", "render", "assemble", "cleanup"))
    ap.add_argument("--units", default=",".join(u for u, *_ in CASTLE))
    ap.add_argument("--work", default="V:/olden_port_work/showcase/castle_v0.1.321/work")
    ap.add_argument("--out", default="V:/olden_port_work/showcase/castle_v0.1.321/castle_animations_showcase.mp4")
    ap.add_argument("--spec", help="render: the staged lab job (default: stage now)")
    ap.add_argument("--no-intro", action="store_true")
    ap.add_argument("--keep-frames", action="store_true")
    ap.add_argument("--timeout", type=int, default=5400)
    ap.add_argument("--min-free-gb", type=float, default=22.0, help="full: wait until V: has this much free before each unit")
    a = ap.parse_args(argv)
    units = [u.strip() for u in a.units.split(",") if u.strip()]
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    if a.step == "cleanup":
        cleanup_stage(units)
        return 0
    if a.step == "full":
        lock = work / ".full.lock"     # one runner per work dir: two consumers on one raw dir stall the lab
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise SystemExit(f"another showcase runner holds {lock} (delete it if that runner is gone)")
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        try:
            full(units, work, Path(a.out), not a.no_intro, a.timeout, a.min_free_gb)
        finally:
            cleanup_stage(units)
            lock.unlink(missing_ok=True)
        return 0
    if a.step in ("run", "stage"):
        spec = stage(units, work)
        print("lab job", spec, flush=True)
        if a.step == "stage":
            return 0
    else:
        spec = Path(a.spec) if a.spec else None
    if a.step in ("run", "render"):
        if spec is None:
            spec = stage(units, work)
        render(units, work, spec, a.timeout)
    if a.step in ("run", "assemble"):
        assemble(units, work, Path(a.out), not a.no_intro, a.keep_frames)
    if a.step == "run":
        cleanup_stage(units)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
