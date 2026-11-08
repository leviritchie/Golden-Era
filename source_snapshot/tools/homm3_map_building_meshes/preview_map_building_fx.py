"""Unity-editor preview of the vanilla-style map-building effects (lane vanilla_style_effect).

    python tools/homm3_map_building_meshes/preview_map_building_fx.py recipes            # static read of the install
    python tools/homm3_map_building_meshes/preview_map_building_fx.py render [--only S]  # memgate + unitylock + Unity
    python tools/homm3_map_building_meshes/preview_map_building_fx.py compose [--only S]

``recipes`` extracts every preset's subtree as a lab ParticleSystem recipe (tools/homm3_vfx/vanilla_ps_recipe.py).
``render`` builds one lab panel per effect row of the runtime anim catalog: the shipped Meshy mesh, posed as the
runtime poses it (glTF X mirror, then the 180-degree billboard front yaw), its baked effect anchors as bones, and on
each anchor the preset recipe with the catalog's keep nodes, world scale, rate and recolour, under a map-pitch
orthographic camera. It reuses the vanilla-style lab (tools/homm3_vfx/unity/Homm3VanillaStyleVfxLab.cs, body kind
``native``), which rebuilds the systems through the public ParticleSystem API with a VfxUber replica shader.
``compose`` writes per row a motion sheet (t = 0 s and t = 1 s after a warm-up, their difference, and an 8-frame
strip) and an animated GIF.

Everything heavy goes to F:/homm3_map_fx (renders, bins, recipes). Unity assets are staged under the managed
folder Assets/Homm3VfxLab/map_building_fx (marker file).

Proof level: Unity-editor replica render, not in-game.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
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
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
import map_building_anim as MBA  # noqa: E402

PROJECT = ROOT / "oldenera_factions"
UNITY = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe")
WORK = Path("F:/homm3_map_fx")
REC = WORK / "recipes"
LAB = WORK / "lab"
OUT = WORK / "preview"
ASSET_ROOT = "Assets/Homm3VfxLab/map_building_fx"
MARKER = "HOMM3_VFX_LAB_GENERATED"
FPS = 24
FRAMES = 48          # 2 s
WARMUP_S = 4.0       # longest kept lifetime (smoke 3.5 s) reaches steady state
PITCH_DEG = 50.0     # map-like camera pitch (camera on -Z looking +Z at the building front)
SUN = [-0.35, -0.8, 0.5]
GROUND = (0.20, 0.22, 0.16)
TEX_MAX = 1024


def recipe_file(preset: dict) -> Path:
    key = f"{preset['resPath']}:{preset['childPath']}".replace("/", "__").replace(":", "__")
    return REC / f"{key}.json"


def cmd_recipes() -> None:
    presets = MBA.load_fx_presets()
    specs = sorted({f"{p['resPath']}:{p['childPath']}" for p in presets.values()})
    REC.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / "tools/homm3_vfx/vanilla_ps_recipe.py"), str(REC), *specs], check=True,
                   timeout=1800)


def node_paths(recipe: dict) -> list[str]:
    nodes = recipe["nodes"]
    out = []
    for n in nodes:
        parts = []
        cur = n
        while cur["parent"] != -1:
            parts.append(cur["name"])
            cur = nodes[cur["parent"]]
        out.append("/".join(reversed(parts)))
    return out


def stage_common() -> Path:
    dest = PROJECT / ASSET_ROOT
    marker = dest / "HOMM3_VFX_LAB_GENERATED.txt"
    if dest.exists() and not marker.exists() and any(dest.iterdir()):
        raise SystemExit(f"refusing to write into unmanaged {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    marker.write_text("managed by tools/homm3_map_building_meshes/preview_map_building_fx.py\n")
    src_lab = ROOT / "tools/homm3_vfx/unity"
    for rel_dst, src in (("Assets/Editor/Homm3VfxLab/Homm3VanillaStyleVfxLab.cs", src_lab / "Homm3VanillaStyleVfxLab.cs"),
                         ("Assets/Homm3VfxLab/Shaders/Homm3VfxUberReplica.shader", src_lab / "Homm3VfxUberReplica.shader"),
                         ("Assets/Homm3VfxLab/Shaders/Homm3VfxHexLitEmissionReplica.shader",
                          src_lab / "Homm3VfxHexLitEmissionReplica.shader")):
        dst = PROJECT / rel_dst
        if dst.exists() and dst.read_bytes() == src.read_bytes():
            continue
        if dst.exists() and MARKER not in dst.read_text(encoding="utf-8", errors="replace"):
            raise SystemExit(f"refusing to overwrite unmanaged {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    lib = json.loads((REC / "materials.json").read_text(encoding="utf-8"))
    for t in lib["textures"].values():
        _copy(REC / t["file"], dest / t["file"])
    for m in lib["meshes"].values():
        _copy(REC / m["file"], dest / (m["file"] + ".txt"))
    out = {"materials": lib["materials"],
           "textures": [{"name": k, "file": v["file"], "sRGB": v["sRGB"], "mips": v["mips"], "wrapU": v["wrapU"],
                         "wrapV": v["wrapV"]} for k, v in lib["textures"].items()],
           "meshes": [{"name": k, "file": v["file"] + ".txt"} for k, v in lib["meshes"].items()]}
    LAB.mkdir(parents=True, exist_ok=True)
    p = LAB / "lab_materials.json"
    p.write_text(json.dumps(out), encoding="utf-8")
    return p


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return
    shutil.copy2(src, dst)


def q_to_m(q) -> np.ndarray:
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def to_world(v: np.ndarray) -> np.ndarray:
    """glTF model -> Unity world as the runtime poses it: X mirror (glTFast), then yaw 180 => (x, y, -z)."""
    return np.stack([v[..., 0], v[..., 1], -v[..., 2]], -1)


def body_panel(entry: dict, presets: dict) -> dict:
    rel = entry["relativePng"]
    inv = {e["relativePng"]: e for e in json.loads(MBA.MESH_INVENTORY.read_text(encoding="utf-8"))["entries"]}
    mesh_dir = MBA.MESHES_ROOT / inv[rel]["dir"]
    mesh = MBA.MeshData(mesh_dir / "model.glb")
    side = json.loads((mesh_dir / "map_anim.json").read_text(encoding="utf-8"))
    stem = entry["stem"]
    # Stripped faces: the anim GLB drops them; rebuild the kept face set from its body primitive.
    anim = MBA.Glb(mesh_dir / "model_anim.glb")
    faces = [anim.accessor(p["indices"]).astype(np.int64).reshape(-1, 3)
             for m in anim.json["meshes"] for p in m["primitives"]]
    F = np.concatenate(faces)
    V = to_world(mesh.V)
    N = np.zeros_like(V)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    N = -N  # winding is reversed below (mirror), so the geometric normal flips back outward
    UV = np.stack([mesh.UV[:, 0], 1.0 - mesh.UV[:, 1]], 1)
    tri = F[:, [0, 2, 1]]
    binp = LAB / f"{stem}.bin"
    with open(binp, "wb") as fh:
        fh.write(struct.pack("<ii", len(V), 1))
        fh.write(V.astype("<f4").tobytes())
        fh.write(N.astype("<f4").tobytes())
        fh.write(UV.astype("<f4").tobytes())
        idx = tri.reshape(-1).astype("<i4")
        fh.write(struct.pack("<i", len(idx)))
        fh.write(idx.tobytes())
    tex = Image.fromarray(mesh.tex).convert("RGB")
    tex.thumbnail((TEX_MAX, TEX_MAX))
    tex_rel = f"body_{stem}.png"
    tpath = PROJECT / ASSET_ROOT / tex_rel
    tex.save(tpath)
    bones, effects = [], []
    anchors = {a["id"]: a for a in side["anchors"]}
    pts = [V]
    for fx in entry["effects"]:
        p = presets[fx["preset"]]
        a = anchors[fx["id"]]
        pos = to_world(np.asarray(a["position"], float))
        rw = q_to_m(p["nativeWorldRotation"])  # world rotation after the front yaw (the runtime pose)
        m = np.eye(4)
        m[:3, :3] = rw
        m[:3, 3] = pos
        bones.append({"name": fx["anchor"], "m": [float(x) for x in m.reshape(-1)]})
        recipe = json.loads(recipe_file(p).read_text(encoding="utf-8"))
        paths = node_paths(recipe)
        keep = [paths.index(k) for k in p["keepNodes"]]
        anchor_idx = paths.index(p["anchorNode"]) if p.get("anchorNode") else -1
        effects.append({"id": fx["id"], "recipeFile": str(recipe_file(p)), "bone": fx["anchor"], "pos": [0, 0, 0],
                        "rot": [0, 0, 0, 1], "rootWorldRot": [], "recolor": fx.get("recolor") or [],
                        "scale": fx["scale"], "rateMul": fx["rateMul"], "keepRecipeRoot": False, "loopAll": True,
                        "alwaysOn": True, "emitUp": False, "zeroChildPos": False, "anchorNode": anchor_idx,
                        "keepPS": keep, "triggers": [], "stops": []})
        pts.append(pos[None, :] + np.array([[0, fx["scale"] * (3.0 if fx["preset"] == "smoke" else 0.6), 0]]))
    allp = np.concatenate(pts)
    lo, hi = allp.min(0), allp.max(0)
    pitch = math.radians(PITCH_DEG)
    fwd = np.array([0.0, -math.sin(pitch), math.cos(pitch)])
    up = np.array([0.0, math.cos(pitch), math.sin(pitch)])
    right = np.array([1.0, 0.0, 0.0])
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    cu, cr = corners @ up, corners @ right
    centre = (lo + hi) / 2
    half = max((cu.max() - cu.min()) / 2, (cr.max() - cr.min()) / 2) * 1.08
    cu_mid = (cu.max() + cu.min()) / 2
    cr_mid = (cr.max() + cr.min()) / 2
    cc = centre + up * (cu_mid - centre @ up) + right * (cr_mid - centre @ right)
    body = {"kind": "native", "nativeMeshFile": str(binp), "bodyYawDeg": 0.0, "bones": bones,
            "nativeMats": [{"albedo": tex_rel, "emission": "", "emissionColor": [0, 0, 0], "emissionMin": 1.0,
                            "blinkSpeed": 0.0, "blinkPower": 0.0, "cutoff": 0.0}]}
    return {"id": stem, "body": body, "effects": effects, "flipbooks": [], "oldLights": [],
            "clips": [{"name": "loop", "keys": 0, "frames": FRAMES, "frameStep": 1.0 / FPS, "boilCells": [],
                       "loop": True}],
            "camRight": right.tolist(), "camUp": up.tolist(), "camForward": fwd.tolist(), "camCentre": cc.tolist(),
            "orthoSize": float(half), "width": 512, "height": 512, "warmupS": WARMUP_S, "sunTravelUnity": SUN}


def fx_entries(only: str | None) -> list[dict]:
    cat = json.loads(MBA.STAGE_CATALOG.read_text(encoding="utf-8"))
    rows = [e for e in cat["entries"] if e.get("effects")]
    if only:
        keys = {s.strip().lower() for s in only.split(",")}
        rows = [e for e in rows if e["stem"] in keys or any(k in e["relativePng"].lower() for k in keys)]
    return rows


def cmd_render(only: str | None, timeout: int) -> int:
    presets = MBA.load_fx_presets()
    lib = stage_common()
    panels = [body_panel(e, presets) for e in fx_entries(only)]
    OUT.mkdir(parents=True, exist_ok=True)
    job = {"schema": "homm3_vanilla_style_lab.v1", "assetRoot": ASSET_ROOT, "materialLib": str(lib),
           "outDir": str(OUT / "renders"), "panels": panels}
    (OUT / "renders").mkdir(parents=True, exist_ok=True)
    sp = LAB / "lab_spec.json"
    sp.write_text(json.dumps(job, indent=1), encoding="utf-8")
    gate = subprocess.run([sys.executable, str(ROOT / "tools/homm3_def_retarget/memgate.py")], capture_output=True,
                          text=True, timeout=900)
    print("memgate", gate.returncode, gate.stdout.strip()[-200:])
    if gate.returncode:
        return gate.returncode
    log = LAB / "unity_lab.log"
    cmd = [str(UNITY), "-batchmode", "-quit", "-projectPath", str(PROJECT), "-homm3VanillaStyleSpec", str(sp),
           "-executeMethod", "OldenEra.Homm3Vfx.Homm3VanillaStyleVfxLab.RunFromCommandLine", "-logFile", str(log)]
    done = UQ.run_cmd(cmd, kind="map_building_fx_preview", timeout_s=timeout, direct=UNITY_DIRECT)
    print(done.stdout[-800:], done.stderr[-800:])
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    for line in text.splitlines():
        if "error CS" in line or "Exception" in line or ("HOMM3_VSTYLE" in line and "frames" not in line):
            print(line[:300])
    ok = done.returncode == 0 and "HOMM3_VSTYLE_LAB_OK" in text
    print("exit", done.returncode, "OK" if ok else "FAILED", log)
    (OUT / "panels.json").write_text(json.dumps([{"id": p["id"], "width": p["width"], "height": p["height"],
                                                   "frames": FRAMES} for p in panels], indent=1))
    return 0 if ok else 1


# ------------------------------------------------------------------ compose (the lab's PPv2-like finish)
def read_bin(p: Path, w, h):
    return np.frombuffer(p.read_bytes(), np.float16).astype(np.float32).reshape(h, w, 4)[::-1]


def finish(raw):
    import vanilla_style_lab as L
    bg = L.srgb_to_lin(GROUND).astype(np.float32)
    rgb = raw[..., :3] + bg * (1 - np.clip(raw[..., 3:4], 0, 1))
    return L.to_srgb8(L.bloom(rgb))


def label(im: Image.Image, text: str) -> Image.Image:
    out = Image.new("RGB", (im.width, im.height + 16), (30, 30, 30))
    out.paste(im, (0, 16))
    ImageDraw.Draw(out).text((3, 2), text, fill=(235, 235, 235))
    return out


def cmd_compose(only: str | None) -> None:
    panels = json.loads((OUT / "panels.json").read_text())
    keys = {s.strip().lower() for s in only.split(",")} if only else None
    for p in panels:
        if keys and p["id"] not in keys:
            continue
        d = OUT / "renders" / p["id"]
        fr = [finish(read_bin(d / f"loop_{i:03d}.bin", p["width"], p["height"])) for i in range(p["frames"])]
        t0, t1 = fr[0], fr[FPS]
        diff = np.abs(t1.astype(np.int16) - t0.astype(np.int16)).max(-1)
        dimg = np.clip(diff * 4, 0, 255).astype(np.uint8)
        moved = float((diff > 12).mean())
        top = Image.new("RGB", (512 * 3, 528), (30, 30, 30))
        top.paste(label(Image.fromarray(t0), f"{p['id']}  t=0.00 s (after {WARMUP_S:.0f} s warm-up)"), (0, 0))
        top.paste(label(Image.fromarray(t1), "t=1.00 s"), (512, 0))
        top.paste(label(Image.fromarray(dimg).convert("RGB"), f"|t1 - t0| x4   moved px {moved:.2%}"), (1024, 0))
        strip = Image.new("RGB", (192 * 8, 208), (30, 30, 30))
        for j, i in enumerate(np.linspace(0, p["frames"] - 1, 8).round().astype(int)):
            im = Image.fromarray(fr[i]).resize((192, 192), Image.LANCZOS)
            strip.paste(label(im, f"t={i / FPS:.2f}s"), (j * 192, 0))
        sheet = Image.new("RGB", (max(top.width, strip.width), top.height + strip.height), (30, 30, 30))
        sheet.paste(top, (0, 0))
        sheet.paste(strip, (0, top.height))
        sheet.save(OUT / f"{p['id']}_motion.png")
        gif = [Image.fromarray(f).resize((320, 320), Image.LANCZOS) for f in fr]
        gif[0].save(OUT / f"{p['id']}.gif", save_all=True, append_images=gif[1:], duration=int(1000 / FPS), loop=0)
        print(f"{p['id']}: moved {moved:.2%} -> {OUT / (p['id'] + '_motion.png')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("recipes", "render", "compose"))
    ap.add_argument("--only")
    ap.add_argument("--timeout", type=int, default=2400)
    a = ap.parse_args()
    if a.command == "recipes":
        cmd_recipes()
        return 0
    if a.command == "render":
        return cmd_render(a.only, a.timeout)
    cmd_compose(a.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
