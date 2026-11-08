#!/usr/bin/env python3
"""Rampart Meshy T2 town-building meshes (artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md).

    python tools/homm3_town_scene_meshes/rampart_t2_generate.py prep            # inputs only, no spend
    python tools/homm3_town_scene_meshes/rampart_t2_generate.py run [--only a,b] [--attempt a1]

Recipe = the Castle price check: the HoMM3 sprite scaled so its long side is 1024 px, on white (LANCZOS), sent
straight to image-to-3d meshy-t2 / smart-topology / should_texture, no texture prompt or image (15 cr, measured).
Every billed create is appended to the shared ledger immediately; the faction cap from _budget_t2_20260929.json is
checked against this faction's ledger sum before every create (fail closed). At most 8 tasks in flight.
Outputs: artifacts/meshy_town_scene_meshes/homm3_rampart/<layer>/t2_<attempt>/{input.png,model.glb,thumb.png,task.json}
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))
import meshy_client as MC  # noqa: E402

FACTION = "homm3_rampart"
MESHY = ROOT / "artifacts" / "meshy_town_scene_meshes"
OUTROOT = MESHY / FACTION
LEDGER = MESHY / "_ledger.jsonl"
BUDGET = json.loads((MESHY / "_budget_t2_20260929.json").read_text(encoding="utf-8"))
CAP = int(BUDGET["townCaps"][FACTION])
PRICE = 15
LAYERS = ROOT / ("Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_runtime_assets/"
                 "town_scene_refs/homm3_rampart/layers")

# Reachable layers (building_layer_map.json nativeLevels) meshed in the first pass. tbrmdw_5_2 is not meshed: it is
# tbrmdw_5 plus two small stone lanterns (337 of 14762 px differ), so it reuses the tbrmdw_5 mesh with its own
# painting projected on it.
MESH_LAYERS = [
    "tbrmhall", "tbrmhal2", "tbrmhal3", "tbrmcstl", "tbrmcas2", "tbrmcas3",
    "tbrmmage", "tbrmmag2", "tbrmmag3", "tbrmmag4", "tbrmtvrn", "tbrmmark", "tbrmsilo", "tbrmblak",
    "tbrmspec", "tbrmext0", "tbrmhrd1", "tbrmholy",
    "tbrmdw_0", "tbrmdw_0_2", "tbrmdw_1", "tbrmdw_1_2", "tbrmdw_2", "tbrmdw_2_2", "tbrmdw_3", "tbrmdw_3_2",
    "tbrmdw_4", "tbrmdw_4_2", "tbrmdw_5", "tbrmdw_6", "tbrmdw_6_2",
]
_lock = threading.Lock()


def spent() -> int:
    tot = 0
    if LEDGER.is_file():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("faction") == FACTION and r.get("kind") != "claim":
                    tot += int(r.get("credits", 0))
    return tot


def claimed() -> int:
    tot = 0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("faction") == FACTION and r.get("kind") == "claim":
                tot += int(r.get("credits", 0))
    return tot


def prep(layer: str, attempt: str) -> Path:
    out = OUTROOT / layer / f"t2_{attempt}"
    out.mkdir(parents=True, exist_ok=True)
    im = Image.open(LAYERS / f"{layer}.png").convert("RGBA")
    s = 1024 / max(im.size)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    bg.convert("RGB").save(out / "input.png")
    return out


def run_one(key: str, layer: str, attempt: str, purpose: str) -> dict:
    out = OUTROOT / layer / f"t2_{attempt}"
    if (out / "model.glb").is_file():
        return {"layer": layer, "status": "exists"}
    inp = prep(layer, attempt)
    with _lock:
        cap = CAP + claimed()
        if spent() + PRICE > cap:
            return {"layer": layer, "status": f"refused: cap {cap} reached ({spent()} spent)"}
        tid = MC.create_image_to_3d(key, image_path=inp / "input.png", should_texture=True, target_polycount=15000,
                                    model_type="smart-topology", ai_model="meshy-t2")
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "faction": FACTION, "layer": layer,
                                "kind": "image-to-3d meshy-t2 textured", "credits": PRICE, "taskId": tid,
                                "purpose": purpose}) + "\n")
    (inp / "task_id.txt").write_text(tid, encoding="utf-8")
    t = MC.poll_task(key, "image-to-3d", tid, timeout_s=1800, interval_s=15)
    (inp / "task.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    if t.get("status") != "SUCCEEDED":
        return {"layer": layer, "status": t.get("status"), "error": MC.task_error_message(t), "taskId": tid}
    MC.download_url(t["model_urls"]["glb"], inp / "model.glb")
    if t.get("thumbnail_url"):
        MC.download_url(t["thumbnail_url"], inp / "thumb.png")
    return {"layer": layer, "status": "SUCCEEDED", "taskId": tid}


CONCEPT_PRICE = 6
# concept step (image-to-image, 6 cr) only where the direct sprite recipe failed (review of the a1 thumbnails)
CONCEPTS = {
    "tbrmdw_6": ("Turn this painted rock into one solid, closed, free-standing 3D object: a single massive red-pink "
                 "sandstone crag with vertical cliff faces and a rounded top, seen from slightly above, whole object "
                 "visible, on a plain pure white background. Keep its painted colours, shape and proportions. "
                 "No fog, no mist, no trees, no ground plane, no text."),
    "tbrmdw_6_2": ("Turn this painted rock ridge into one solid, closed, free-standing 3D object: a long massive "
                   "red-pink sandstone crag with twin peaks and vertical cliff faces, seen from slightly above, whole "
                   "object visible, on a plain pure white background. Keep its painted colours, shape and proportions. "
                   "No fog, no mist, no trees, no ground plane, no text."),
}


def log_line(layer: str, kind: str, credits: int, tid: str, purpose: str) -> None:
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "faction": FACTION, "layer": layer,
                            "kind": kind, "credits": credits, "taskId": tid, "purpose": purpose}) + "\n")


def run_concept(key: str, layer: str, attempt: str, purpose: str) -> dict:
    """image-to-image concept from the sprite input, then image-to-3d on it (21 cr)."""
    out = OUTROOT / layer / f"t2_{attempt}"
    if (out / "model.glb").is_file():
        return {"layer": layer, "status": "exists"}
    inp = prep(layer, attempt)
    with _lock:
        cap = CAP + claimed()
        if spent() + CONCEPT_PRICE + PRICE > cap:
            return {"layer": layer, "status": f"refused: cap {cap} ({spent()} spent)"}
        tid = MC.create_image_to_image(key, prompt=CONCEPTS[layer], reference_paths=[inp / "input.png"])
        log_line(layer, "image-to-image concept", CONCEPT_PRICE, tid, purpose + " (concept)")
    t = MC.poll_task(key, "image-to-image", tid, timeout_s=900, interval_s=10)
    (out / "concept_task.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    if t.get("status") != "SUCCEEDED":
        return {"layer": layer, "status": t.get("status"), "error": MC.task_error_message(t)}
    urls = t.get("image_urls") or []
    MC.download_url(urls[0], out / "concept.png")
    with _lock:
        if spent() + PRICE > CAP + claimed():
            return {"layer": layer, "status": "refused after concept"}
        tid3 = MC.create_image_to_3d(key, image_path=out / "concept.png", should_texture=True,
                                     target_polycount=15000, model_type="smart-topology", ai_model="meshy-t2")
        log_line(layer, "image-to-3d meshy-t2 textured", PRICE, tid3, purpose)
    t = MC.poll_task(key, "image-to-3d", tid3, timeout_s=1800, interval_s=15)
    (out / "task.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    if t.get("status") != "SUCCEEDED":
        return {"layer": layer, "status": t.get("status"), "error": MC.task_error_message(t), "taskId": tid3}
    MC.download_url(t["model_urls"]["glb"], out / "model.glb")
    if t.get("thumbnail_url"):
        MC.download_url(t["thumbnail_url"], out / "thumb.png")
    return {"layer": layer, "status": "SUCCEEDED", "taskId": tid3}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "run", "concept", "spent"])
    ap.add_argument("--only", default="")
    ap.add_argument("--attempt", default="a1")
    ap.add_argument("--purpose", default="first pass: town-scene building mesh")
    a = ap.parse_args()
    layers = [x for x in a.only.split(",") if x] or MESH_LAYERS
    if a.cmd == "spent":
        print(json.dumps({"spent": spent(), "cap": CAP, "claimed": claimed()}))
        return 0
    if a.cmd == "prep":
        for l in layers:
            print(prep(l, a.attempt))
        return 0
    key = MC.load_api_key()
    if a.cmd == "concept":
        with ThreadPoolExecutor(max_workers=8) as ex:
            res = list(ex.map(lambda l: run_concept(key, l, a.attempt, a.purpose), layers))
        print(json.dumps(res, indent=1))
        print(json.dumps({"spentAfter": spent(), "cap": CAP}))
        return 0
    print(json.dumps({"spentBefore": spent(), "cap": CAP, "layers": len(layers)}), flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(lambda l: run_one(key, l, a.attempt, a.purpose), layers))
    print(json.dumps(res, indent=1))
    print(json.dumps({"spentAfter": spent(), "cap": CAP}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
