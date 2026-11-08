"""Unity-editor preview of the map-building animation pilots.

  python tools/homm3_vfx/unitylock.py run --wait 60 -- python tools/homm3_map_building_meshes/preview_map_building_anim.py render
  python tools/homm3_map_building_meshes/preview_map_building_anim.py compose

render: stages unity/Homm3MapBuildingAnimPreview.cs into oldenera_factions, writes a spec from the runtime
anim catalog (homm3_map_building_meshes/anim/catalog.json) and runs one Unity batch (with graphics;
memgate-gated). Needs the prefabs built by build_homm3_map_building_meshes_bundle.py.
compose: per job an animated GIF plus a contact sheet under artifacts/map_building_anim/preview/.

Proof level: Unity-editor render (plain CG preview shader on the prefab albedo and the quads), not in-game.
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

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROJECT = ROOT / "oldenera_factions"
UNITY = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe")
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
ANIM_DIR = PLUGIN / "homm3_map_building_meshes" / "anim"
ASSET_ROOT = "Assets/Homm3MapBuildingMeshes"
OUT = ROOT / "artifacts" / "map_building_anim" / "preview"
RAW = OUT / "raw"


def jobs_from_catalog() -> list[dict]:
    cat = json.loads((ANIM_DIR / "catalog.json").read_text(encoding="utf-8"))
    jobs = []
    for e in cat["entries"]:
        stem = e["relativePng"].split("/")[-2].replace(".dir", "").lower()
        base = {"frameMs": e["frameMs"], "flips": [], "billboardFrames": [], "clipPath": "", "prefabPath": ""}
        if e["lane"] == "billboard_frames":
            jobs.append({**base, "name": f"{stem}_billboard", "pitch": 0.0, "samples": 2 * len(e["frames"]),
                         "billboardFrames": [str(ANIM_DIR / f) for f in e["frames"]]})
            continue
        prefab = f"{ASSET_ROOT}/{e['prefabKey']}.prefab"
        base["defDir"] = e["relativePng"].split("map_object_refs/")[1].rsplit("/", 1)[0]
        if e["lane"] in ("pendulum", "articulated_rigid"):
            clip = f"{ASSET_ROOT}/{e['prefabKey']}_parts_loop.anim"
            loop = e["parts"][0]["loopSeconds"]
            samples = int(round(loop * 1000 / e["frameMs"]))  # one sample per DEF frame
            for view, pitch in (("front", 0.0), ("map", 35.0)):
                jobs.append({**base, "name": f"{stem}_{view}", "prefabPath": prefab, "clipPath": clip,
                             "pitch": pitch, "samples": samples})
        elif e["lane"] == "rotor":
            clip = f"{ASSET_ROOT}/{e['prefabKey']}_rotor_loop.anim"
            period = max(r["periodSeconds"] for r in e["rotors"])
            samples = int(round(period * 1000 / e["frameMs"]))  # exactly one revolution
            for view, pitch in (("front", 0.0), ("map", 35.0)):
                jobs.append({**base, "name": f"{stem}_{view}", "prefabPath": prefab, "clipPath": clip,
                             "pitch": pitch, "samples": samples})
        else:
            flips = [{"anchor": fb["anchor"], "quadW": fb["quadSize"][0], "quadH": fb["quadSize"][1],
                      "frames": [str(ANIM_DIR / f) for f in fb["frames"]]} for fb in e["flipbooks"]]
            n = len(e["flipbooks"][0]["frames"])
            for view, pitch in (("front", 0.0), ("map", 35.0)):
                jobs.append({**base, "name": f"{stem}_{view}", "prefabPath": prefab, "pitch": pitch,
                             "samples": 2 * n, "flips": flips})
    return jobs


def render(timeout: int = 1500) -> int:
    dest = PROJECT / "Assets/Editor/Homm3MapAnimPreview/Homm3MapBuildingAnimPreview.cs"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / "unity" / "Homm3MapBuildingAnimPreview.cs", dest)
    shader = PROJECT / "Assets/Homm3MapAnimPreview/Shaders/Homm3MapAnimPreview.shader"
    shader.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / "unity" / "Homm3MapAnimPreview.shader", shader)
    RAW.mkdir(parents=True, exist_ok=True)
    spec = {"outDir": str(RAW), "width": 640, "height": 640, "jobs": jobs_from_catalog()}
    spec_path = OUT / "preview_spec.json"
    spec_path.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    gate = subprocess.run([sys.executable, str(ROOT / "tools/homm3_def_retarget/memgate.py")], capture_output=True, text=True)
    print(gate.stdout.strip())
    if gate.returncode != 0:
        raise SystemExit("memgate not OK; not starting Unity")
    log = OUT / "preview_unity.log"
    cmd = [str(UNITY), "-batchmode", "-quit", "-projectPath", str(PROJECT), "-homm3MapAnimPreviewSpec", str(spec_path),
           "-executeMethod", "OldenEra.Homm3MapAnim.Homm3MapBuildingAnimPreview.RenderFromCommandLine", "-logFile", str(log)]
    done = UQ.run_cmd(cmd, kind="map_building_anim_preview", timeout_s=timeout, direct=UNITY_DIRECT)
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    ok = done.returncode == 0 and "HOMM3_MAP_ANIM_PREVIEW_OK" in text
    for line in text.splitlines():
        if "HOMM3_MAP_ANIM_PREVIEW" in line or "error CS" in line or "Exception" in line:
            print(line)
    print("exit", done.returncode, "OK" if ok else "FAILED", log)
    return 0 if ok else 1


def compose() -> int:
    spec = json.loads((OUT / "preview_spec.json").read_text(encoding="utf-8"))
    for job in spec["jobs"]:
        frames = [Image.open(RAW / job["name"] / f"f{i:03d}.png").convert("RGB") for i in range(job["samples"])]
        gif = OUT / f"{job['name']}.gif"
        frames[0].save(gif, save_all=True, append_images=frames[1:], duration=int(job["frameMs"]), loop=0)
        cols = min(8, len(frames))
        rows = -(-len(frames) // cols)
        tw = 200
        sheet = Image.new("RGB", (cols * tw, rows * tw), (20, 20, 20))
        for i, f in enumerate(frames):
            t = f.resize((tw, tw), Image.LANCZOS)
            ImageDraw.Draw(t).text((4, 4), f"{i * job['frameMs'] / 1000:.2f}s", fill=(255, 255, 255))
            sheet.paste(t, ((i % cols) * tw, (i // cols) * tw))
        sheet.save(OUT / f"{job['name']}_sheet.png")
        if job.get("defDir"):
            compare_with_def(job, frames)
        print("wrote", gif)
    return 0


def compare_with_def(job: dict, frames: list) -> None:
    """Side-by-side strip: HoMM3 DEF frame (top) and the render sampled at the same time (bottom)."""
    sys.path.insert(0, str(HERE))
    import map_building_anim as mba  # noqa: E402
    _label, pal, defs = mba.def_frames(job["defDir"])
    n = len(defs)
    tw = 160
    step = max(1, len(frames) // 12)
    picks = list(range(0, len(frames), step))[:12]
    sheet = Image.new("RGB", (len(picks) * tw, 2 * tw + 16), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    for k, i in enumerate(picks):
        rgba = Image.fromarray(mba.index_to_rgba(defs[i % n], pal))
        scale = tw / max(rgba.size)
        rgba = rgba.resize((max(1, int(rgba.width * scale)), max(1, int(rgba.height * scale))), Image.NEAREST)
        cell = Image.new("RGB", (tw, tw), (90, 110, 90))
        cell.paste(rgba, ((tw - rgba.width) // 2, (tw - rgba.height) // 2), rgba)
        sheet.paste(cell, (k * tw, 16))
        sheet.paste(frames[i].resize((tw, tw), Image.LANCZOS), (k * tw, 16 + tw))
        d.text((k * tw + 4, 2), f"DEF f{i % n} / t={i * job['frameMs'] / 1000:.2f}s", fill=(255, 255, 0))
    sheet.save(OUT / f"{job['name']}_vs_def.png")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "render":
        raise SystemExit(render())
    if cmd == "compose":
        raise SystemExit(compose())
    raise SystemExit(__doc__)
