#!/usr/bin/env python3
"""Dungeon Meshy T2 town-building meshes (artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md).

    python tools/homm3_town_scene_meshes/dungeon_t2_generate.py prep            # inputs only, no spend
    python tools/homm3_town_scene_meshes/dungeon_t2_generate.py run [--only a,b] [--attempt a1]

Recipe = the Castle price check: the HoMM3 sprite scaled so its long side is 1024 px, on white (LANCZOS), sent
straight to image-to-3d meshy-t2 / smart-topology / should_texture, no texture prompt or image (15 cr, measured).
Every billed create is appended to the shared ledger immediately; the faction cap from _budget_t2_20260929.json is
checked against this faction's ledger sum before every create (fail closed). At most 8 tasks in flight.
Outputs: artifacts/meshy_town_scene_meshes/homm3_dungeon/<layer>/t2_<attempt>/{input.png,model.glb,thumb.png,task.json}
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

FACTION = "homm3_dungeon"
MESHY = ROOT / "artifacts" / "meshy_town_scene_meshes"
OUTROOT = MESHY / FACTION
LEDGER = MESHY / "_ledger.jsonl"
BUDGET = json.loads((MESHY / "_budget_t2_20260929.json").read_text(encoding="utf-8"))
CAP = int(BUDGET["townCaps"][FACTION])
PRICE = 15
LAYERS = ROOT / ("Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_runtime_assets/"
                 "town_scene_refs/homm3_dungeon/layers")

# Reachable layers (SC.reachable_layers(), 32) meshed in the first pass: every free-standing structure. Not meshed:
#   tbdnhrd2  - the warren upgrade's horde sprite (1205 of 10952 px differ from tbdndw_0_2: more mushrooms); reuses the
#               tbdndw_0_2 mesh with its own painting projected on it.
#   tbdndw_1 / _1_2 (harpy crags), tbdndw_3 / _3_2 (the carved evil-eye portal), tbdndw_5 / _5_2 (the manticore bone
#   field), tbdndw_6 / _6_2 (the dragon cave's wall and hoard) - painted pieces OF the cavern wall / floor, no
#   free-standing object: a mesh would be a slab; they keep the depth-relief solid.
#   tbdnext0  - the portal's sparkle ring, an effect overlay (34 px tall) carried by the fx lane.
MESH_LAYERS = [
    "tbdnhall", "tbdnhall_2", "tbdnhall_3", "tbdncstl", "tbdncstl_2", "tbdncstl_3",
    "tbdnmage", "tbdnmage_2", "tbdnmage_3", "tbdnmage_4", "tbdntvrn", "tbdnmark", "tbdnsilo", "tbdnblak",
    "tbdnspec", "tbdnholy", "tbdndw_0", "tbdndw_0_2", "tbdndw_2", "tbdndw_2_2", "tbdndw_4", "tbdndw_4_2",
]
_lock = threading.Lock()


def _mask(layer: str):
    """Object mask for the Meshy input: sprite alpha minus magenta leftovers and minus only the LARGE coherent regions
    identical to the painting under the sprite (the cave rock the mage guild / castle sprites carry). The lane's
    per-pixel native_mask is too ragged here (dark Dungeon art is within 10 RGB of the dark cave at many single
    pixels), so the 'same' mask is opened by a 7 px disc first; holes are filled and specks < 2% dropped."""
    import os
    import cv2
    import numpy as np
    os.environ.setdefault("TOWN_FULL3D_FACTION", "dungeon")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import stronghold_full3d_common as SC
    L = SC.layers()[layer]
    spr = np.asarray(SC.sprite(L).convert("RGBA")).astype(np.int32)
    bg = np.asarray(SC.background_rgb()).astype(np.int32)
    h, w = spr.shape[:2]
    x, y = L["x"], L["y"]
    sy, sx = max(0, -y), max(0, -x)
    under = np.zeros((h, w, 3), np.int32)
    u = bg[y + sy:y + h, x + sx:x + w]
    under[sy:sy + u.shape[0], sx:sx + u.shape[1]] = u
    a = spr[..., 3] > 128
    r, g, b = spr[..., 0], spr[..., 1], spr[..., 2]
    magenta = (r > 120) & (b > 120) & (g < 0.62 * np.minimum(r, b))
    same = (np.abs(spr[..., :3] - under).max(-1) <= 10) & a
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    same = cv2.morphologyEx(same.astype(np.uint8), cv2.MORPH_OPEN, k) > 0
    m = (a & ~magenta & ~same).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    big = st[1:, cv2.CC_STAT_AREA].max()
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 0.02 * big
    m = keep[lab]
    inv = (~m).astype(np.uint8)
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    border = set(np.unique(np.r_[lab2[0], lab2[-1], lab2[:, 0], lab2[:, -1]]).tolist())
    return m | np.isin(lab2, [i for i in range(1, n2) if i not in border])


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
    # the lane's own building mask: sprite alpha minus magenta leftovers and minus pixels identical to the painting
    # under it (the Dungeon sprites carry cave rock cut from the background, which Meshy would model as a slab)
    import numpy as np
    arr = np.asarray(im).copy()
    arr[..., 3] = np.where(_mask(layer), 255, 0).astype(np.uint8)
    im = Image.fromarray(arr, "RGBA")
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "run", "spent"])
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
    print(json.dumps({"spentBefore": spent(), "cap": CAP, "layers": len(layers)}), flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(lambda l: run_one(key, l, a.attempt, a.purpose), layers))
    print(json.dumps(res, indent=1))
    print(json.dumps({"spentAfter": spent(), "cap": CAP}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
