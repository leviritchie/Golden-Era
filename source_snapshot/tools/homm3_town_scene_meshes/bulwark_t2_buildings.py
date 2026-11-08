#!/usr/bin/env python3
"""Bulwark town scene: Meshy T2 building meshes in the full-3D lane (docs/homm3_bulwark_t2_town_buildings.md).

Brief: artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md (2026-09-29). One module, faction-scoped paths only:

  prep      per layer: the sprite as the player sees it (composited over the painting under it), cut by the lane's
            own building mask (stronghold_full3d_buildings.native_mask, speckle-closed), optional hand crop (TRIM),
            on white at 1024 px (LANCZOS)                     -> artifacts/meshy_town_scene_meshes/homm3_bulwark/<id>/input.png
  generate  one Meshy image-to-3d call per layer (meshy-t2, smart-topology, should_texture, no texture prompt/image;
            15 credits measured). Ledger line appended right after create; the faction's ledger sum is checked
            against townCaps before every call (hard stop). At most MAX_PARALLEL tasks in flight.
  fit / stage / sheet: see the functions below.

Nothing here installs anything. Proof tier: generated artifact until a bundle is built and rendered.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TOWN_FULL3D_FACTION", "bulwark")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# the installed Bulwark candidates were staged with this extension canvas (town_all/bulwark/stage_v3.sh); the terrain
# the fit rests buildings on is the same one only with it
os.environ.setdefault("TOWN_FULL3D_EXTSRC", str(ROOT / "artifacts" / "claude_takeover_20260927" / "town_all" / "bulwark"
                                                / "tex_v2" / "extsrc_bridge_blend"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

FACTION = "homm3_bulwark"
MESHY = ROOT / "artifacts" / "meshy_town_scene_meshes"
OUTD = MESHY / FACTION
LEDGER = MESHY / "_ledger.jsonl"
BUDGET = MESHY / "_budget_t2_20260929.json"
PRICE = 15
MAX_PARALLEL = 8
POLYCOUNT = 15000          # smart-topology face cap (tools/homm3_town_scene_meshes/README.md: 100..15000)

# Layers meshed (each gets its own T2 call), and why the rest are not. Order = priority (reach and stretch first).
MESH_LAYERS = [
    "tbbha301", "tbbha201", "tbbuha01",              # town hall levels (the big stave hall at the right)
    "tbbucstl", "tbbucas2", "tbbucas3",              # fort / citadel / castle (different tower sets)
    "tbbud201", "tbbuu201",                          # Tier 3 longhouse with shields (front right, largest stretch)
    "tbbutv01", "tbbuma01", "tbbubl01",              # tavern, market, blacksmith
    "tbbud301", "tbbuu301",                          # Tier 4 mammoth-rib hut and its upgrade
    "tbbud501", "tbbuu501",                          # Tier 6 cave front (left edge) and its upgrade
    "tbbum101", "tbbum201", "tbbum301", "tbbum401",  # mage guild: every level is a new storey + a new roof
    "tbbudw_6", "tbbuup_6",                          # Tier 7 stone temple and its upgrade
    "tbbud001", "tbbuu001",                          # Tier 1 cave hut (left edge) and its upgrade tower
    "tbbudw_1", "tbbuu101",                          # Tier 2 rock spire / crystal spire
    "tbbudw_4", "tbbuup_4",                          # Tier 5 standing-stone ruin and its upgrade
    "tbbus201", "tbbusilo",                          # rune stones (artifact market), resource depot platform
]
REUSE = {"tbbuhu01": "tbbuu501"}   # Resource_Depot_level_2 is tbbuu501 plus a few painted pieces (1921 of 17784 px differ)
SKIP = {
    "tbbuho01": "grail: a translucent spirit painted over the sky, not a standing structure (stays the lane's relief)",
    "tbbumr01": "bonfire figure: mostly animated fire (effects module); first pass keeps the relief, contingency candidate",
}
# Hand crops in native sprite px (x0, y0, x1, y1), applied to the Meshy input only: the castle levels carry a long
# painted snow trail below their wall base that T2 would build as a slab.
TRIM = {"tbbucstl": (0, 0, 215, 190), "tbbucas2": (0, 0, 215, 219), "tbbucas3": (0, 0, 215, 219)}


# ------------------------------------------------------------------------------------------------ ledger
def ledger_rows() -> list[dict]:
    if not LEDGER.is_file():
        return []
    return [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]


def spent(faction: str = FACTION) -> int:
    return sum(int(r.get("credits", 0)) for r in ledger_rows() if r.get("faction") == faction and r.get("kind") != "claim")


def claimed(faction: str = FACTION) -> int:
    return sum(int(r.get("credits", 0)) for r in ledger_rows() if r.get("faction") == faction and r.get("kind") == "claim")


def cap() -> int:
    b = json.loads(BUDGET.read_text(encoding="utf-8"))
    return int(b["townCaps"][FACTION]) + claimed()


def ledger_append(row: dict) -> None:
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ------------------------------------------------------------------------------------------------ prep
def prep(ids: list[str]) -> None:
    import stronghold_full3d_buildings as BL
    import stronghold_full3d_common as SC
    lays = SC.layers()
    bg = SC.background_rgba()
    for lid in ids:
        L = lays[lid]
        spr = SC.sprite(L)
        comp = Image.new("RGBA", spr.size)
        comp.paste(bg.crop((L["x"], L["y"], L["x"] + spr.width, L["y"] + spr.height)), (0, 0))
        comp.alpha_composite(spr)
        m = BL.native_mask(L).astype(np.uint8)
        # close the HoMM3 shadow / transparency speckle inside the building (outline kept)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0
        if lid in TRIM:
            x0, y0, x1, y1 = TRIM[lid]
            keep = np.zeros_like(m)
            keep[y0:y1, x0:x1] = True
            m &= keep
        rgb = np.asarray(comp.convert("RGB")).copy()
        rgb[~m] = 255
        ys, xs = np.nonzero(m)
        crop = Image.fromarray(rgb[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
        s = 880 / max(crop.size)
        crop = crop.resize((round(crop.width * s), round(crop.height * s)), Image.LANCZOS)
        out = Image.new("RGB", (1024, 1024), (255, 255, 255))
        out.paste(crop, ((1024 - crop.width) // 2, (1024 - crop.height) // 2))
        d = OUTD / lid
        d.mkdir(parents=True, exist_ok=True)
        out.save(d / "input.png")
        print(lid, crop.size)


def prep_sheet(ids: list[str]) -> None:
    cell = 256
    cols = 8
    rows = -(-len(ids) // cols)
    S = Image.new("RGB", (cols * cell, rows * cell), (128, 128, 128))
    for i, lid in enumerate(ids):
        im = Image.open(OUTD / lid / "input.png").resize((cell - 4, cell - 4), Image.LANCZOS)
        S.paste(im, ((i % cols) * cell + 2, (i // cols) * cell + 2))
    S.save(OUTD / "_work" / "inputs_sheet.png")


# ------------------------------------------------------------------------------------------------ generate
def generate(ids: list[str]) -> None:
    from meshy_client import create_image_to_3d, download_url, load_api_key, poll_task, task_error_message
    key = load_api_key()
    pending: dict[str, str] = {}
    todo = [l for l in ids if not (OUTD / l / "model.glb").is_file()]
    for lid in list(todo):
        meta_p = OUTD / lid / "meshy.json"
        if meta_p.is_file():       # created earlier (billed): resume polling, never re-create
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            if meta.get("status") != "FAILED":
                pending[lid] = meta["taskId"]
                todo.remove(lid)
    while todo or pending:
        while todo and len(pending) < MAX_PARALLEL:
            lid = todo[0]
            if spent() + PRICE > cap():
                print(f"STOP: spent {spent()} + {PRICE} > cap {cap()}; {len(todo)} not generated: {todo}")
                todo = []
                break
            todo.pop(0)
            tid = create_image_to_3d(key, image_path=OUTD / lid / "input.png", should_texture=True,
                                     target_polycount=POLYCOUNT, model_type="smart-topology", ai_model="meshy-t2")
            ts = dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            ledger_append({"ts": ts, "faction": FACTION, "layer": lid, "kind": "image-to-3d meshy-t2 textured",
                           "credits": PRICE, "taskId": tid, "purpose": f"{lid}: town building mesh (first pass)"})
            (OUTD / lid / "meshy.json").write_text(json.dumps({"taskId": tid, "created": ts, "credits": PRICE,
                                                               "input": "input.png", "polycount": POLYCOUNT,
                                                               "aiModel": "meshy-t2", "modelType": "smart-topology",
                                                               "shouldTexture": True}, indent=1), encoding="utf-8")
            pending[lid] = tid
            print("created", lid, tid, "spent", spent())
        done = []
        for lid, tid in pending.items():
            from meshy_client import get_task
            t = get_task(key, "image-to-3d", tid)
            st = t.get("status")
            if st in ("SUCCEEDED", "FAILED", "CANCELED"):
                meta_p = OUTD / lid / "meshy.json"
                meta = json.loads(meta_p.read_text(encoding="utf-8"))
                meta["status"] = st
                if st == "SUCCEEDED":
                    download_url(t["model_urls"]["glb"], OUTD / lid / "model.glb")
                    if t.get("thumbnail_url"):
                        download_url(t["thumbnail_url"], OUTD / lid / "thumb.png")
                else:
                    meta["error"] = task_error_message(t)
                meta_p.write_text(json.dumps(meta, indent=1), encoding="utf-8")
                print(lid, st)
                done.append(lid)
        for lid in done:
            pending.pop(lid)
        if pending:
            time.sleep(15)
    print("spent", spent(), "cap", cap())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "generate", "spent", "fit", "stage", "sheet"])
    ap.add_argument("--only", default="")
    ap.add_argument("--candidate", default="t2_v1")
    a = ap.parse_args()
    ids = [x for x in a.only.split(",") if x] or MESH_LAYERS
    if a.cmd == "prep":
        prep(ids)
        prep_sheet(ids)
    elif a.cmd == "generate":
        generate(ids)
    elif a.cmd == "spent":
        print(json.dumps({"spent": spent(), "claimed": claimed(), "cap": cap()}))
    else:
        if a.cmd in ("fit", "stage") and not a.only:
            ids = MESH_LAYERS + list(REUSE)
        os.environ["TOWN_FULL3D_CANDIDATE"] = a.candidate
        import bulwark_t2_stage as ST
        return ST.run(a.cmd, ids, a.candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
