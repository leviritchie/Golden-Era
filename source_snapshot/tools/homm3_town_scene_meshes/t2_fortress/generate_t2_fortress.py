#!/usr/bin/env python3
"""Meshy T2 town-scene buildings for HoMM3 Fortress (artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md).

    python generate_t2_fortress.py run --layers a,b,c [--concept a,b] [--attempt t2]

Per layer: the HoMM3 sprite scaled (LANCZOS) so its long side is 1024 px, flattened on white (the Castle price check's
input), optionally an image-to-image concept step (6 cr) for a sprite the frame truncates, then image-to-3d with
ai_model meshy-t2, model_type smart-topology, should_texture True and no texture prompt / image (15 cr).

Budget (hard, fail closed): before every billed call the Fortress lines of _ledger.jsonl are summed and the call is
refused if it would pass townCaps['homm3_fortress'] plus this faction's contingency claims. Every billed call appends
one ledger line immediately after the create returns its task id. At most MAX_PARALLEL tasks run at once.
Outputs: artifacts/meshy_town_scene_meshes/homm3_fortress/<layer>/<attempt>/ (input.png, [concept.png], model.glb,
thumb.png, task.json, task_result.json).
Proof tier: generated artifact (Meshy outputs downloaded; nothing is installed).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))
import meshy_client as MC  # noqa: E402

FACTION = "homm3_fortress"
MESHY = ROOT / "artifacts" / "meshy_town_scene_meshes"
OUT = MESHY / FACTION
LEDGER = MESHY / "_ledger.jsonl"
BUDGET = MESHY / "_budget_t2_20260929.json"
LAYERS = (ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_runtime_assets"
          / "town_scene_refs" / FACTION / "layers")
PRICE_MESH, PRICE_CONCEPT = 15, 6
MAX_PARALLEL = 4
POLYCOUNT = 8000
_lock = threading.Lock()

# What each building is (for the concept prompt only; hand-written from the sprite sheet).
DESCRIBE = {
    "tbfrmage": "a swamp mage guild: a tall steep A-frame hut of woven reed thatch with a purple triangle emblem, log "
                "beams, a raised log platform and two green-flamed torch posts at the door",
    "tbfrmage_2": "a swamp mage guild: a tall steep A-frame hut of woven reed thatch with two stacked purple triangle "
                  "emblems, log beams, a raised log platform and two green-flamed torch posts at the door",
    "tbfrmage_3": "a swamp mage guild: a very tall steep A-frame hut of woven reed thatch with three stacked purple "
                  "triangle emblems and a horned wooden crest on top, log beams, a raised log platform and two "
                  "blue-flamed torch posts at the door",
    "tbfrtvrn": "a swamp tavern: a low wooden hut with a big shaggy thatched roof on stilts over dark water, a bright "
                "orange hearth fire glowing in its open front",
    "tbfrdw_4": "a basilisk pit: a sunken rectangular pit with pink stone walls and stairs down, on a stone rim",
    "tbfrdw_4_2": "a basilisk pit: a sunken rectangular pit with pink stone walls and stairs down, on a stone rim with "
                  "two tall pink stone posts topped with red glowing lamps",
    "tbfrdw_5": "a wyvern nest: a huge round nest of woven dark branches and twigs with a dark hollow opening",
    "tbfrdw_5_2": "a wyvern nest: a huge round nest of woven dark branches and twigs with hanging moss and green leaves "
                  "and a dark hollow opening",
    "tbfrdw_6": "a hydra pond: an oval swamp pond of dark green water with white lily flowers, rimmed by mossy boulders "
                "and a big fern",
    "tbfrdw_6_2": "a hydra pond: an oval swamp pond of dark green water with white lily flowers, rimmed by mossy "
                  "boulders, a big fern and a fallen mossy log",
    "tbfrdock": "a swamp shipyard dock: a wooden plank pier on posts with a log ladder and a mossy wooden hull frame",
    "tbfrholy": "a swamp grail shrine: a giant red carnivorous flower bulb with a toothed red blossom on top, sitting on "
                "a mat of tangled roots and tentacle vines on a mossy mound",
}


def prompt_for(lid: str) -> str:
    return ("Recreate the object in the reference image as a single clean high-detail 3D model render. It is "
            f"{DESCRIBE[lid]}. The reference is cut off by the picture frame: complete the missing part in the same "
            "style so the whole object is shown. Keep exactly the same design, silhouette, proportions, materials and "
            "colours as the reference (it comes from a classic 1999 fantasy strategy game town screen). Show the whole "
            "object, centred, three-quarter front view from slightly above, soft even studio lighting, plain pure white "
            "background, no surrounding landscape, no other buildings, no text.")


def budget_state() -> tuple[int, int]:
    """(spent, allowance) for this faction from the ledger: billed credits vs townCap + contingency claims."""
    cap = int(json.loads(BUDGET.read_text(encoding="utf-8"))["townCaps"][FACTION])
    spent = claims = 0
    for ln in LEDGER.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("faction") != FACTION:
            continue
        if r.get("kind") == "claim":
            claims += int(r["credits"])
        else:
            spent += int(r["credits"])
    return spent, cap + claims


def ledger_append(row: dict) -> None:
    with open(LEDGER, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row) + "\n")


def billed_create(price: int, kind: str, layer: str, purpose: str, create) -> str:
    """Check the budget, create, append the ledger line: serialised so parallel workers cannot overshoot the cap."""
    with _lock:
        spent, allow = budget_state()
        if spent + price > allow:
            raise SystemExit(f"budget: {FACTION} spent {spent} + {price} > allowance {allow}; refusing {layer} {kind}")
        tid = create()
        ledger_append({"ts": dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "faction": FACTION, "layer": layer,
                       "kind": kind, "credits": price, "taskId": tid, "purpose": purpose})
        print(f"[bill] {layer} {kind} {price} cr task {tid} (faction total {spent + price}/{allow})", flush=True)
        return tid


def prep_input(lid: str, dest: Path) -> Path:
    im = Image.open(LAYERS / f"{lid}.png").convert("RGBA")
    s = 1024 / max(im.size)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    dest.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(dest)
    return dest


def run_layer(key: str, lid: str, concept: bool, attempt: str) -> dict:
    d = OUT / lid / attempt
    if (d / "model.glb").is_file():
        return {"layer": lid, "skipped": "model.glb exists"}
    src = prep_input(lid, d / "input.png")
    rec = {"layer": lid, "attempt": attempt, "input": str(src.relative_to(ROOT)).replace("\\", "/")}
    if concept:
        cp = d / "concept.png"
        if not cp.is_file():
            prompt = prompt_for(lid)
            tid = billed_create(PRICE_CONCEPT, "image-to-image nano-banana-2", lid, "concept: sprite truncated by the frame",
                                lambda: MC.create_image_to_image(key, prompt=prompt, reference_paths=[src]))
            rec["concept"] = {"taskId": tid, "prompt": prompt}
            res = MC.poll_task(key, "image-to-image", tid, timeout_s=900, interval_s=10)
            (d / "concept_result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
            if res.get("status") != "SUCCEEDED" or not res.get("image_urls"):
                return {**rec, "error": f"concept {res.get('status')}: {MC.task_error_message(res)}"}
            MC.download_url(res["image_urls"][0], cp)
        src = cp
    tid = billed_create(PRICE_MESH, "image-to-3d meshy-t2 textured", lid, f"town building {lid} ({attempt})",
                        lambda: MC.create_image_to_3d(key, image_path=src, should_texture=True, target_polycount=POLYCOUNT,
                                                      model_type="smart-topology", ai_model="meshy-t2"))
    rec["mesh"] = {"taskId": tid, "source": str(src.relative_to(ROOT)).replace("\\", "/"),
                   "params": {"ai_model": "meshy-t2", "model_type": "smart-topology", "should_texture": True,
                              "target_polycount": POLYCOUNT}}
    (d / "task.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    res = MC.poll_task(key, "image-to-3d", tid, timeout_s=1800, interval_s=15)
    (d / "task_result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if res.get("status") != "SUCCEEDED":
        return {**rec, "error": f"mesh {res.get('status')}: {MC.task_error_message(res)}"}
    url = (res.get("model_urls") or {}).get("glb") or res.get("model_url")
    MC.download_url(url, d / "model.glb")
    if res.get("thumbnail_url"):
        MC.download_url(res["thumbnail_url"], d / "thumb.png")
    rec["consumed"] = res.get("consumed_credits")
    (d / "task.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "budget"])
    ap.add_argument("--layers", default="")
    ap.add_argument("--concept", default="", help="layers that get the image-to-image concept step first")
    ap.add_argument("--attempt", default="t2")
    a = ap.parse_args()
    if a.cmd == "budget":
        print(json.dumps(dict(zip(("spent", "allowance"), budget_state()))))
        return 0
    key = MC.load_api_key()
    lids = [x for x in a.layers.split(",") if x]
    conc = {x for x in a.concept.split(",") if x}
    unknown = [x for x in conc if x not in lids or x not in DESCRIBE]
    if unknown:
        raise SystemExit(f"--concept layers not in --layers or without a DESCRIBE row: {unknown}")
    with ThreadPoolExecutor(MAX_PARALLEL) as ex:
        futs = [ex.submit(run_layer, key, l, l in conc, a.attempt) for l in lids]
        out = []
        for f in futs:
            try:
                out.append(f.result())
            except BaseException as e:  # a refused budget or HTTP error names the layer in its message
                out.append({"error": repr(e)})
    print(json.dumps(out, indent=1))
    return 1 if any("error" in r for r in out) else 0


if __name__ == "__main__":
    raise SystemExit(main())
