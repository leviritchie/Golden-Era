#!/usr/bin/env python3
"""Stronghold Meshy T2 town buildings: image-to-3d calls under the shared T2 budget (docs/homm3_stronghold_t2_town_buildings.md).

Brief: artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md. One call = ai_model meshy-t2, smart-topology,
should_texture True, no texture prompt/image (15 credits, measured by the Castle price check). Before every call the
faction's ledger lines are summed and the call is refused if it would pass the cap (townCaps + this faction's claims).
The ledger line is appended immediately after create. At most MAX_CONCURRENT tasks run at once.

    python tools/homm3_town_scene_meshes/stronghold_t2_meshy.py run --layers a,b,c [--tag t2_a1]
    python tools/homm3_town_scene_meshes/stronghold_t2_meshy.py spend

Input per layer: artifacts/meshy_town_scene_meshes/homm3_stronghold/<layer>/input.png (the native mask on white, long
side 1024 LANCZOS; prep in _work/prep_inputs.py). Output: <layer>/<tag>/{model.glb, thumb.png, task.json}.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))
from meshy_client import (create_image_to_3d, download_url, get_task, load_api_key,  # noqa: E402
                          task_error_message)

MESHY = ROOT / "artifacts" / "meshy_town_scene_meshes"
BUDGET = MESHY / "_budget_t2_20260929.json"
LEDGER = MESHY / "_ledger.jsonl"
FACTION = "homm3_stronghold"
OUT = MESHY / FACTION
PRICE = 15
MAX_CONCURRENT = 4   # coordinator: at most 4 Meshy tasks at once
POLYCOUNT = 15000   # meshy-t2 maximum (the API refuses more)


def ledger_rows() -> list[dict]:
    if not LEDGER.is_file():
        return []
    return [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]


def spend() -> dict:
    rows = [r for r in ledger_rows() if r.get("faction") == FACTION]
    cap = json.loads(BUDGET.read_text(encoding="utf-8"))["townCaps"][FACTION]
    claims = sum(r["credits"] for r in rows if r.get("kind") == "claim")
    spent = sum(r["credits"] for r in rows if r.get("kind") != "claim")
    return {"cap": cap, "claims": claims, "limit": cap + claims, "spent": spent, "left": cap + claims - spent,
            "calls": sum(1 for r in rows if r.get("kind") != "claim")}


def run_one(key: str, lid: str, tag: str, purpose: str) -> dict:
    d = OUT / lid / tag
    if (d / "model.glb").is_file():
        return {"layer": lid, "skipped": "exists"}
    img = OUT / lid / "input.png"
    if not img.is_file():
        raise SystemExit(f"{lid}: no input.png")
    s = spend()
    if s["spent"] + PRICE > s["limit"]:
        raise SystemExit(f"budget: {s} - a {PRICE} cr call on {lid} would pass the limit")
    tid = create_image_to_3d(key, image_path=img, should_texture=True, target_polycount=POLYCOUNT,
                             model_type="smart-topology", ai_model="meshy-t2")
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": dt.datetime.now().isoformat(timespec="seconds"), "faction": FACTION, "layer": lid,
                            "kind": "image-to-3d meshy-t2 textured", "credits": PRICE, "taskId": tid,
                            "purpose": purpose}) + "\n")
    d.mkdir(parents=True, exist_ok=True)
    (d / "task_id.txt").write_text(tid, encoding="utf-8")
    t0 = time.time()
    while True:
        t = get_task(key, "image-to-3d", tid)
        st = t.get("status")
        if st in ("SUCCEEDED", "FAILED", "CANCELED"):
            break
        if time.time() - t0 > 1800:
            raise TimeoutError(f"{lid} {tid}")
        time.sleep(10)
    (d / "task.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    if st != "SUCCEEDED":
        return {"layer": lid, "taskId": tid, "status": st, "error": task_error_message(t)}
    download_url(t["model_urls"]["glb"], d / "model.glb")
    if t.get("thumbnail_url"):
        download_url(t["thumbnail_url"], d / "thumb.png")
    print(lid, "done", round(time.time() - t0), "s", flush=True)
    return {"layer": lid, "taskId": tid, "status": st}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "spend"])
    ap.add_argument("--layers", default="")
    ap.add_argument("--tag", default="t2_a1")
    ap.add_argument("--purpose", default="town building mesh (first pass)")
    a = ap.parse_args()
    if a.cmd == "spend":
        print(json.dumps(spend()))
        return 0
    lids = [x for x in a.layers.split(",") if x]
    s = spend()
    if s["spent"] + PRICE * len(lids) > s["limit"]:
        raise SystemExit(f"budget: {s} cannot cover {len(lids)} calls")
    key = load_api_key()
    with ThreadPoolExecutor(MAX_CONCURRENT) as ex:
        futs = [ex.submit(run_one, key, lid, a.tag, a.purpose) for lid in lids]
        res = []
        for f in futs:
            try:
                res.append(f.result())
            except Exception as e:  # report every layer, then fail
                res.append({"error": repr(e)})
    print(json.dumps(res, indent=1))
    print(json.dumps(spend()))
    return 0 if all(r.get("status") == "SUCCEEDED" or r.get("skipped") for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
