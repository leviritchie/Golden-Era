"""Meshy T2 building meshes for the Tower full-3D town (brief: artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md).

prep:     each planned layer's sprite, minus the pixels identical to the painting under it (the lane's BG_EQUAL rule:
          HoMM3 sprites carry painted sky / ground cut from the background), composited on white and scaled LANCZOS to
          fit 1024 px with a margin (the Castle price-check recipe; no concept step).
generate: image-to-3d, ai_model meshy-t2, smart-topology, should_texture, no texture prompt / image (15 cr, measured).
          Before every create the faction's ledger lines are summed and the call refused past the cap (townCaps plus
          this faction's contingency claims); one ledger line is appended immediately after each create. At most 8
          tasks in flight.
Outputs: artifacts/meshy_town_scene_meshes/homm3_tower/<layer>/<tag>/{input.png,model.glb,thumb.png,task.json}.
Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))
FACTION = "homm3_tower"
REFS = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_runtime_assets/town_scene_refs/homm3_tower"
MESHY = ROOT / "artifacts/meshy_town_scene_meshes"
OUT = MESHY / FACTION
LEDGER = MESHY / "_ledger.jsonl"
BUDGET = MESHY / "_budget_t2_20260929.json"
PRICE = 15
MAX_INFLIGHT = 8
BG_EQUAL = 10

# First pass (28 calls = the 420 cap). Reused (not meshed): tbtwcstl_3 <- tbtwcstl_2 (+893 px piece),
# tbtwhall_4 <- tbtwhall_3 (+1553 px piece), tbtwdw_2_2 <- tbtwdw_2 (same box, animated chimneys / steam).
# Skipped: tbtwhall (village hall): the building is painted into Tower-in-background.png (sprite == painting within
# BG_EQUAL), so the lane mask is a roof strip and the terrain owns the hall; a mesh would double it.
PLAN = ["tbtwhall_3", "tbtwcstl_2", "tbtwmage_4", "tbtwdw_6_2", "tbtwdw_6", "tbtwhall_2", "tbtwblak", "tbtwdw_2",
        "tbtwmage_3", "tbtwmage_2", "tbtwmage", "tbtwcstl", "tbtwdw_5_2", "tbtwdw_5", "tbtwdw_4_2", "tbtwdw_4",
        "tbtwtvrn", "tbtwmark", "tbtwsilo", "tbtwdw_3_2", "tbtwdw_3", "tbtwdw_1_2", "tbtwdw_1", "tbtwdw_0_2",
        "tbtwdw_0", "tbtwspec", "tbtwholy", "tbtwext2"]


def layers() -> dict:
    return {l["id"]: l for l in json.loads((REFS / "layers/positions.json").read_text(encoding="utf-8"))["layers"]}


def sprite_mask(L: dict) -> tuple[np.ndarray, np.ndarray]:
    """The lane's own building mask (stronghold_full3d_buildings.native_mask: alpha minus HoMM3 shadow magenta minus
    the painting's own px, fringe dropped, holes filled), then only the components of at least 3% of the largest one
    (the painted snow / dirt skirts break into specks that Meshy would model as rubble)."""
    import os
    import cv2
    os.environ.setdefault("TOWN_FULL3D_FACTION", "tower")
    sys.path.insert(0, str(ROOT / "tools" / "homm3_town_scene_meshes"))
    import stronghold_full3d_buildings as BL
    if BL.SC.FACTION != "tower":
        raise SystemExit(f"lane faction is {BL.SC.FACTION!r}, not tower")
    m = BL.native_mask(L).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        raise SystemExit(f"{L['id']}: empty mask")
    big = st[1:, cv2.CC_STAT_AREA].max()
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 0.03 * big
    rgb = np.asarray(Image.open(REFS / "layers" / L["sprite"]).convert("RGB"))
    return rgb, keep[lab]


def prep(lid: str, L: dict, tag: str = "t2") -> Path:
    rgb, m = sprite_mask(L)
    ys, xs = np.nonzero(m)
    rgb, m = rgb[ys.min():ys.max() + 1, xs.min():xs.max() + 1], m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    img = np.where(m[..., None], rgb, 255).astype(np.uint8)
    h, w = m.shape
    s = 900.0 / max(h, w)
    im = Image.fromarray(img).resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    can = Image.new("RGB", (1024, 1024), (255, 255, 255))
    can.paste(im, ((1024 - im.width) // 2, (1024 - im.height) // 2))
    d = OUT / lid / tag
    d.mkdir(parents=True, exist_ok=True)
    p = d / "input.png"
    can.save(p)
    return p


def _rows() -> list[dict]:
    return [json.loads(x) for x in LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()]


def spent() -> int:
    return sum(int(r["credits"]) for r in _rows() if r.get("faction") == FACTION and r.get("kind") != "claim")


def claimed() -> int:
    return sum(int(r["credits"]) for r in _rows() if r.get("faction") == FACTION and r.get("kind") == "claim")


def cap() -> int:
    return int(json.loads(BUDGET.read_text(encoding="utf-8"))["townCaps"][FACTION]) + claimed()


def ledger_append(lid: str, task: str, purpose: str) -> None:
    row = {"ts": dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "faction": FACTION, "layer": lid,
           "kind": "image-to-3d meshy-t2 textured", "credits": PRICE, "taskId": task, "purpose": purpose}
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def generate(lids: list[str], purpose: str, tag: str) -> None:
    import meshy_client as MC
    key = MC.load_api_key()
    lays = layers()
    queue = list(lids)
    live: dict[str, str] = {}
    while queue or live:
        while queue and len(live) < MAX_INFLIGHT:
            lid = queue.pop(0)
            d = OUT / lid / tag
            if (d / "model.glb").is_file():
                print("have", lid, flush=True)
                continue
            if spent() + PRICE > cap():
                raise SystemExit(f"cap: spent {spent()} + {PRICE} > {cap()}; refusing {lid}")
            inp = d / "input.png" if (d / "input.png").is_file() else prep(lid, lays[lid], tag)
            task = MC.create_image_to_3d(key, image_path=inp, should_texture=True, target_polycount=15000,
                                         model_type="smart-topology", ai_model="meshy-t2")
            ledger_append(lid, task, purpose)
            (d / "task.json").write_text(json.dumps({"taskId": task, "created": time.time()}), encoding="utf-8")
            live[lid] = task
            print("created", lid, task, "spent", spent(), flush=True)
        time.sleep(15)
        for lid, task in list(live.items()):
            t = MC.get_task(key, "image-to-3d", task)
            st = t.get("status")
            if st in ("SUCCEEDED", "FAILED", "CANCELED"):
                d = OUT / lid / tag
                (d / "task.json").write_text(json.dumps({k: t.get(k) for k in (
                    "id", "status", "model_urls", "thumbnail_url", "task_error", "created_at", "finished_at")},
                    indent=1), encoding="utf-8")
                if st == "SUCCEEDED":
                    MC.download_url(t["model_urls"]["glb"], d / "model.glb")
                    if t.get("thumbnail_url"):
                        MC.download_url(t["thumbnail_url"], d / "thumb.png")
                print(st, lid, flush=True)
                del live[lid]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "generate", "spent"])
    ap.add_argument("--only", default="")
    ap.add_argument("--tag", default="t2")
    ap.add_argument("--purpose", default="first pass building mesh")
    a = ap.parse_args()
    lids = [x for x in a.only.split(",") if x] or PLAN
    if a.cmd == "spent":
        print(json.dumps({"spent": spent(), "cap": cap(), "claimed": claimed()}))
    elif a.cmd == "prep":
        lays = layers()
        for lid in lids:
            print(prep(lid, lays[lid], a.tag))
    else:
        generate(lids, a.purpose, a.tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
