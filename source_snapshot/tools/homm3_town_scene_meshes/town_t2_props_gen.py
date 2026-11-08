#!/usr/bin/env python3
"""Full-3D T2 towns, props pass (2026-09-30, group A): Meshy props drawn from the HoMM3 town painting.

    python town_t2_props_gen.py prep    [--towns castle,...]      # painting crops -> <prop>/input.png (free)
    python town_t2_props_gen.py concept [--towns ...] [--props a,b]  # image-to-image nano-banana-2 (6 cr each)
    python town_t2_props_gen.py mesh    [--towns ...] [--props a,b]  # image-to-3d meshy-t2 smart-topology (15 cr)
    python town_t2_props_gen.py spend                                # this pass's ledger sum

Why: the T2 town scenes streak / warp at the vanilla camera's sweep poses where a painting-projected surface (carved
terrain behind the Meshy buildings, the outpainted side mountains, the extension foreground) is seen at a grazing
angle (town_t2_streak_map.py measures it). Props of the painting's own kind (its trees, rocks, spires, shrubs) placed
where those surfaces are seen cover them; placement / staging: town_t2_props.py.

Source rule: every input is a crop of the HoMM3 town painting (the background + the full-state building sprites,
stronghold_full3d_scene.homm3_reference), never the old blurred 2D backdrop. The crop is the object's painted look;
the concept step (image-to-image) isolates it as one complete prop on white, since a painted crop is tiny, cut by
its neighbours and has no hidden side. The prop's painted height in frame px (PROPS[..]["px"]) sets its world size.

Budget: artifacts/meshy_town_scene_meshes/_budget_props_20260930_group<G>.json (group A: cap 900 for its six towns). The pass's
spend is summed from _ledger.jsonl ("pass" == PASS) before every billed call; one ledger line is appended right
after each create. At most 8 tasks in flight. Outputs: artifacts/meshy_town_scene_meshes/homm3_<town>/props_20260930/.
Proof tier: generated artifact (Meshy outputs).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))
BRIEF = ROOT / "artifacts" / "meshy_town_scene_meshes"
LEDGER = BRIEF / "_ledger.jsonl"
# TOWN_T2_PROPS_GROUP (default A): which group's budget file (pass tag, cap) this process bills against. A group
# other than A adds its own towns' PROPS (and anim-pass RECIPES) from town_t2_props_specs_group<G>.py, which that
# group owns; group A's rows below are never overridden by it.
GROUP = os.environ.get("TOWN_T2_PROPS_GROUP", "A").strip() or "A"
BUDGET = json.loads((BRIEF / f"_budget_props_20260930_group{GROUP}.json").read_text(encoding="utf-8"))
PASS = BUDGET["pass"]
CAP = int(BUDGET["cap"])
PRICE = {"image-to-3d": 15, "image-to-image": 6}
LOCK = threading.Lock()

# town -> prop -> crop (frame px of the painted 1440x673 rect: x0, y0, x1, y1), painted height px, description.
PROPS = {
    "castle": {
        "pine": ([0, 212, 50, 305], 80, "a tall dark green conifer pine tree with a straight brown trunk"),
        "spire": ([288, 172, 352, 312], 120, "a tall weathered tan sandstone rock pinnacle, eroded into rounded "
                                              "stacked lumps, with small tufts of green grass at its foot"),
        "shrub": ([996, 328, 1100, 392], 40, "a rounded clump of dense green leafy bushes and grass"),
        "boulder": ([352, 298, 412, 372], 50, "a pair of rounded tan sandstone boulders with grass tufts"),
    },
    "rampart": {
        "fir": ([1085, 185, 1185, 300], 95, "a tall dark green fir tree with dense drooping branches"),
        "oak": ([145, 265, 315, 470], 190, "an ancient gnarled oak tree with a thick twisted trunk, spreading "
                                            "twisted roots and a light green leafy crown"),
        "boulder": ([1095, 565, 1165, 625], 50, "a mossy grey granite boulder with ferns"),
    },
    "tower": {
        "boulder": ([145, 585, 265, 662], 50, "a cluster of pale grey granite boulders dusted with snow"),
        "slab": ([275, 585, 470, 655], 40, "a low pile of flat broken pale grey stone slabs with snow"),
        "crag": ([495, 478, 725, 585], 90, "a snow-covered grey rock outcrop, a mound of rocks under deep snow"),
        "spire": ([745, 180, 905, 425], 240, "a tall jagged grey granite mountain crag streaked with snow"),
    },
    "inferno": {
        "spikes": ([738, 528, 902, 602], 60, "a cluster of jagged crimson volcanic rock spikes"),
        "crag": ([1295, 398, 1440, 502], 90, "a craggy dark red volcanic rock ridge"),
        "mound": ([0, 448, 122, 562], 100, "a rugged dark red and black volcanic rock mound"),
    },
    "necropolis": {
        "crag": ([1135, 25, 1300, 322], 290, "a tall jagged dark grey-brown rock cliff crag"),
        "deadtree": ([952, 398, 1004, 472], 70, "a leafless dead black tree with bare twisted branches"),
        "ruin": ([1198, 283, 1302, 337], 50, "a low ruined grey stone wall with scattered bones and skulls"),
        "mound": ([640, 258, 842, 382], 120, "a rocky dark brown earth and stone mound"),
    },
    "dungeon": {
        "pillar": ([468, 88, 548, 362], 270, "a tall natural cave rock column, a stalactite fused with a "
                                             "stalagmite, rough brown limestone"),
        "stalagmite": ([28, 378, 98, 442], 60, "a cluster of pointed pale brown cave stalagmites"),
        "mushrooms": ([148, 588, 228, 642], 50, "a cluster of glowing yellow-green giant cave mushrooms"),
        "rock": ([778, 378, 902, 472], 90, "a rough dark brown cave boulder"),
    },
}
EXTRA_RECIPES: dict = {}
if GROUP != "A":
    import importlib
    sys.path.insert(0, str(HERE))
    _g = importlib.import_module(f"town_t2_props_specs_group{GROUP}")
    for _t, _p in getattr(_g, "PROPS", {}).items():
        if _t in PROPS:
            raise SystemExit(f"group {GROUP} specs name town {_t}, which group A owns")
        PROPS[_t] = _p
    EXTRA_RECIPES = dict(getattr(_g, "RECIPES", {}))
CONCEPT_PROMPT = ("Redraw the object in this crop of a fantasy town painting as one isolated, complete 3D game prop "
                  "on a plain pure white background: {d}. Keep the painting's colours, materials and style. Show the "
                  "whole object, uncut, from a three-quarter view slightly from above, centred. No ground plane, no "
                  "other objects, no buildings, no shadow, no text.")


def out_dir(town: str, prop: str) -> Path:
    return BRIEF / f"homm3_{town}" / "props_20260930" / prop


def painting(town: str) -> Image.Image:
    os.environ["TOWN_FULL3D_FACTION"] = town
    sys.path.insert(0, str(HERE))
    import importlib
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    if SC.FACTION != town:
        raise SystemExit(f"painting: modules already loaded for {SC.FACTION}; run one town per process")
    return S.homm3_reference(SC.FP.STATES["full"])


def prep(town: str) -> list[dict]:
    img = painting(town)
    rep = []
    for prop, (rect, px, desc) in PROPS[town].items():
        d = out_dir(town, prop)
        d.mkdir(parents=True, exist_ok=True)
        crop = img.crop(tuple(rect))
        s = 1024 / max(crop.size)
        crop.resize((round(crop.width * s), round(crop.height * s)), Image.LANCZOS).save(d / "input.png")
        spec = {"town": town, "prop": prop, "rectFrame": rect, "paintedPx": px, "description": desc,
                "source": "HoMM3 town painting (background + full-state sprites, x1.8 frame), crop"}
        (d / "spec.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
        rep.append(spec)
    return rep


def spent() -> int:
    tot = 0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("pass") == PASS:
                tot += int(r.get("credits", 0))
    return tot


def billed_create(kind: str, town: str, prop: str, purpose: str, fn) -> str:
    with LOCK:
        cost = PRICE[kind]
        s = spent()
        if s + cost > CAP:
            raise SystemExit(f"cap: {s} + {cost} > {CAP} (pass {PASS}); stop and report")
        tid = fn()
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "faction": f"homm3_{town}", "layer": f"prop:{prop}",
               "kind": kind + (" meshy-t2 textured" if kind == "image-to-3d" else " nano-banana-2"),
               "credits": cost, "taskId": tid, "purpose": purpose, "pass": PASS}
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(f"billed {town}/{prop} {kind} {tid} (pass total {s + cost}/{CAP})", flush=True)
        return tid


def run_concept(key: str, town: str, prop: str) -> dict:
    from meshy_client import create_image_to_image, download_url, poll_task, task_error_message
    d = out_dir(town, prop)
    if (d / "concept.png").is_file():
        return {"prop": f"{town}/{prop}", "status": "have concept"}
    tf = d / "concept_task.json"
    if tf.is_file():
        tid = json.loads(tf.read_text())["taskId"]
    else:
        prompt = CONCEPT_PROMPT.format(d=PROPS[town][prop][2])
        tid = billed_create("image-to-image", town, prop, "props pass: isolate the painted prop",
                            lambda: create_image_to_image(key, prompt=prompt, reference_paths=[d / "input.png"],
                                                          ai_model="nano-banana-2"))
        tf.write_text(json.dumps({"taskId": tid, "prompt": prompt}, indent=2))
    t = poll_task(key, "image-to-image", tid, timeout_s=1800, interval_s=10)
    (d / "concept_result.json").write_text(json.dumps(t, indent=2))
    if t.get("status") != "SUCCEEDED":
        return {"prop": f"{town}/{prop}", "status": t.get("status"), "error": task_error_message(t)}
    download_url(str((t.get("image_urls") or [])[0]), d / "concept.png")
    return {"prop": f"{town}/{prop}", "status": "SUCCEEDED"}


def run_mesh(key: str, town: str, prop: str) -> dict:
    from meshy_client import create_image_to_3d, download_url, poll_task, task_error_message
    d = out_dir(town, prop)
    if (d / "model.glb").is_file():
        return {"prop": f"{town}/{prop}", "status": "have model"}
    if not (d / "concept.png").is_file():
        return {"prop": f"{town}/{prop}", "status": "no concept"}
    tf = d / "mesh_task.json"
    if tf.is_file():
        tid = json.loads(tf.read_text())["taskId"]
    else:
        tid = billed_create("image-to-3d", town, prop, "props pass: prop mesh (concept.png)",
                            lambda: create_image_to_3d(key, image_path=d / "concept.png", should_texture=True,
                                                       model_type="smart-topology", ai_model="meshy-t2"))
        tf.write_text(json.dumps({"taskId": tid, "source": "concept.png",
                                  "policy": "meshy-t2 smart-topology should_texture target_polycount 4000"}, indent=2))
    t = poll_task(key, "image-to-3d", tid, timeout_s=3600, interval_s=15)
    (d / "mesh_result.json").write_text(json.dumps(t, indent=2))
    if t.get("status") != "SUCCEEDED":
        return {"prop": f"{town}/{prop}", "status": t.get("status"), "error": task_error_message(t)}
    download_url(str(t["model_urls"]["glb"]), d / "model.glb")
    if t.get("thumbnail_url"):
        download_url(str(t["thumbnail_url"]), d / "thumb.png")
    return {"prop": f"{town}/{prop}", "status": "SUCCEEDED", "consumed": t.get("consumed_credits")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "concept", "mesh", "spend"])
    ap.add_argument("--towns", default=",".join(PROPS))
    ap.add_argument("--props", default="")
    a = ap.parse_args()
    if a.cmd == "spend":
        print(json.dumps({"pass": PASS, "spent": spent(), "cap": CAP}))
        return 0
    towns = [t for t in a.towns.split(",") if t]
    if a.cmd == "prep":
        if len(towns) != 1:
            raise SystemExit("prep: one town per process (the painting modules are per faction)")
        print(json.dumps(prep(towns[0]), indent=1))
        return 0
    from meshy_client import load_api_key
    key = load_api_key()
    want = set(p for p in a.props.split(",") if p)
    jobs = [(t, p) for t in towns for p in PROPS[t] if not want or p in want or f"{t}/{p}" in want]
    fn = run_concept if a.cmd == "concept" else run_mesh
    with ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(lambda tp: fn(key, *tp), jobs):
            print(json.dumps(r), flush=True)
    print(json.dumps({"pass": PASS, "spent": spent(), "cap": CAP}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
