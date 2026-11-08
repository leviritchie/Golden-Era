#!/usr/bin/env python3
"""Factory (HotA) town-scene buildings as Meshy T2 textured meshes (brief: artifacts/meshy_town_scene_meshes/
_BRIEF_t2_towns.md; doc: docs/homm3_factory_t2_town_buildings.md).

    python tools/homm3_town_scene_meshes/factory_t2_meshy.py prep   [--layer L ...]
    python tools/homm3_town_scene_meshes/factory_t2_meshy.py start  [--layer L ...] [--attempt N]
    python tools/homm3_town_scene_meshes/factory_t2_meshy.py poll   [--layer L ...] [--attempt N]
    python tools/homm3_town_scene_meshes/factory_t2_meshy.py spend

prep   (free) the building sprite -> input.png: the layer's building pixels (native_mask: alpha minus painted-in
       background, minus the DEF's moving smoke / sails where the profile animates them) on white, long side 1024
       (LANCZOS). The committed ref is a painted upscale for 29 of 41 Factory layers; it is used where it exists at
       1024 (its mask is the native mask upscaled), else the native DEF frame is upscaled.
start  one image-to-3d per layer: ai_model meshy-t2, model_type smart-topology, should_texture, no texture prompt or
       image (15 credits, measured by the Castle price check). The ledger line is appended right after create; the
       faction's ledger sum is checked against townCaps before every call (hard stop), at most MAX_INFLIGHT tasks run.
poll   download model.glb (+ thumbnail) of finished tasks.
A queued attempt is never re-created (task.json exists), so re-running start is never billed twice.
Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TOWN_FULL3D_FACTION", "factory")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

FACTION = "homm3_factory"
MESHY = ROOT / "artifacts" / "meshy_town_scene_meshes"
OUT = MESHY / FACTION / "t2"
LEDGER = MESHY / "_ledger.jsonl"
BUDGET = MESHY / "_budget_t2_20260929.json"
PRICE = 15
MAX_INFLIGHT = 8

# Layers meshed (one Meshy call each) and why the rest are not (brief "What to mesh"). REUSE: a level whose sprite is
# the same building as another meshed level (the upgrade adds only an animated part) takes that level's mesh, fitted to
# its own sprite.
MESH_LAYERS = ["tbfacas3", "tbfacstl", "tbfahal3", "tbfahal2", "tbfahall", "tbfamag4", "tbfamag3", "tbfamag2",
               "tbfamage", "tbfaholy", "tbfatvrn", "tbfablak", "tbfamark", "tbfamrch", "tbfaspc1", "tbfadw_0",
               "tbfaup_0", "tbfadw_1", "tbfaup_1", "tbfadw_3", "tbfaup_3", "tbfadw_5", "tbfaup_5", "tbfadw_6",
               "tbfaup_6", "tbfaup_4", "tbfaup_2", "tbfasilo", "tbfadw_4"]
REUSE = {"tbfacas2": "tbfacas3", "tbfahrd2": "tbfaup_2"}
SKIP = {"tbfadw_2": "a 181x31 strip of crates and fence lying on the canyon floor (a ground decal, no standalone "
                    "structure); it keeps its relief shell"}


def ledger_rows() -> list[dict]:
    if not LEDGER.is_file():
        return []
    return [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]


def faction_spend() -> int:
    return sum(int(r["credits"]) for r in ledger_rows() if r.get("faction") == FACTION and r.get("kind") != "claim")


def faction_claims() -> int:
    return sum(int(r["credits"]) for r in ledger_rows() if r.get("faction") == FACTION and r.get("kind") == "claim")


def cap() -> int:
    b = json.loads(BUDGET.read_text(encoding="utf-8"))
    return int(b["townCaps"][FACTION]) + faction_claims()


def append_ledger(row: dict) -> None:
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ------------------------------------------------------------------------------------------------ prep
def building_mask(lid: str) -> np.ndarray:
    """Native-px building mask: native_mask, minus the DEF's changed px of a smoke / spin layer (the plume is an
    effect, not geometry), largest parts kept."""
    import cv2
    import stronghold_full3d_common as SC
    import stronghold_full3d_buildings as BL
    L = SC.layers()[lid]
    m = BL.native_mask(L)
    row = (getattr(SC.FP, "FX_LAYERS", None) or {}).get(lid)
    if row and any(e.get("kind") == "smoke" for e in row.get("effects") or []):
        import town_full3d_fx as FX
        meta = FX.layer_meta(SC.anim_frames())
        F = FX.def_frames(meta, lid)
        dx, dy = FX.check_registration(meta, lid, L, F)
        ch = FX.changed_count(F) > 0
        rects = [r for e in row["effects"] if e.get("kind") == "smoke" for r in (e.get("rects") or [])]
        if rects:
            # only the plume's own rect: the Upgrade's flywheel and rods move too but are geometry
            box = np.zeros_like(ch)
            for x0, y0, x1, y1 in rects:
                box[y0:y1, x0:x1] = True
            ch &= box
        ch = cv2.dilate(ch.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        full = np.zeros_like(m)
        h, w = ch.shape
        ys, xs = np.nonzero(ch)
        ys, xs = ys - dy, xs - dx
        ok = (ys >= 0) & (xs >= 0) & (ys < m.shape[0]) & (xs < m.shape[1])
        full[ys[ok], xs[ok]] = True
        m = m & ~full
        # a smoke plume's painted sky backing (sprite px over the plume) goes too: keep what connects to the base
    n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    if n > 2:
        big = st[1:, cv2.CC_STAT_AREA].max()
        keep = np.zeros(n, bool)
        keep[1:] = st[1:, cv2.CC_STAT_AREA] >= max(25, 0.02 * big)
        m = keep[lab]
    return m


def prep(lid: str) -> dict:
    import stronghold_full3d_common as SC
    L = SC.layers()[lid]
    m = building_mask(lid)
    plate = SC.static_plate(L)                        # native DEF frame 0 (spin parts replaced by the frame median)
    ref = SC.REFS / "layers" / f"{lid}.png"
    spins = any(e.get("kind") in ("spin", "wheel", "track") for e in
                ((getattr(SC.FP, "FX_LAYERS", None) or {}).get(lid) or {}).get("effects", []))
    src = "native"
    rgba = np.asarray(plate.convert("RGBA")).copy()
    ys, xs = np.nonzero(m)
    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    s = 1024 / max(x1 - x0, y1 - y0)
    size = (max(1, round((x1 - x0) * s)), max(1, round((y1 - y0) * s)))
    if ref.is_file() and not spins:
        r = Image.open(ref).convert("RGBA")
        if max(r.size) == 1024 and r.size != plate.size:
            k = r.width / plate.width
            big = r.crop((round(x0 * k), round(y0 * k), round(x1 * k), round(y1 * k))).resize(size, Image.LANCZOS)
            src = "committed painted upscale"
    if src == "native":
        big = Image.fromarray(rgba).crop((x0, y0, x1, y1)).resize(size, Image.LANCZOS)
    mk = Image.fromarray((m[y0:y1, x0:x1] * 255).astype(np.uint8)).resize(size, Image.BILINEAR)
    a = (np.asarray(mk).astype(np.float32) / 255) * (np.asarray(big)[..., 3].astype(np.float32) / 255)
    rgb = np.asarray(big)[..., :3].astype(np.float32)
    out = rgb * a[..., None] + 255 * (1 - a[..., None])
    d = OUT / lid
    d.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out.round().astype(np.uint8)).save(d / "input.png")
    info = {"layer": lid, "source": src, "size": list(size), "maskPx": int(m.sum()), "box": [int(x0), int(y0),
                                                                                          int(x1), int(y1)]}
    (d / "prep.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


# ------------------------------------------------------------------------------------------------ meshy
def task_file(lid: str, attempt: int) -> Path:
    return OUT / lid / f"mesh_a{attempt}" / "task.json"


def inflight() -> list[Path]:
    out = []
    for tf in OUT.glob("*/mesh_a*/task.json"):
        if not (tf.parent / "task_result.json").is_file():
            out.append(tf)
    return out


def start(key: str, lid: str, attempt: int) -> dict:
    from meshy_client import create_image_to_3d
    tf = task_file(lid, attempt)
    if tf.is_file():
        return {"layer": lid, "status": "already_queued", "taskId": json.loads(tf.read_text())["taskId"]}
    src = OUT / lid / "input.png"
    if not src.is_file():
        raise SystemExit(f"{lid}: run prep first")
    spent, c = faction_spend(), cap()
    if spent + PRICE > c:
        raise SystemExit(f"budget: {FACTION} ledger {spent} + {PRICE} > cap {c}; hard stop")
    if len(inflight()) >= MAX_INFLIGHT:
        return {"layer": lid, "status": "deferred (8 tasks in flight)"}
    tid = create_image_to_3d(key, image_path=src, should_texture=True, model_type="smart-topology",
                             ai_model="meshy-t2")
    append_ledger({"ts": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "faction": FACTION, "layer": lid,
                   "kind": "image-to-3d meshy-t2 textured", "credits": PRICE, "taskId": tid,
                   "purpose": f"town building mesh (attempt {attempt})"})
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(json.dumps({"taskId": tid, "kind": "image-to-3d", "source": src.as_posix(),
                              "policy": "meshy-t2 smart-topology textured, no texture prompt/image"}, indent=1),
                  encoding="utf-8")
    return {"layer": lid, "status": "queued", "taskId": tid, "factionSpend": spent + PRICE, "cap": c}


def poll(key: str, lid: str, attempt: int, wait: bool) -> dict:
    from meshy_client import download_url, get_task, poll_task, task_error_message
    tf = task_file(lid, attempt)
    if not tf.is_file():
        return {"layer": lid, "status": "not_queued"}
    meta = json.loads(tf.read_text(encoding="utf-8"))
    task = (poll_task(key, "image-to-3d", meta["taskId"], timeout_s=3600, interval_s=15) if wait
            else get_task(key, "image-to-3d", meta["taskId"]))
    st = task.get("status")
    res = {"layer": lid, "status": st, "progress": task.get("progress")}
    if st in ("SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"):
        (tf.parent / "task_result.json").write_text(json.dumps(task, indent=1), encoding="utf-8")
    if st == "SUCCEEDED":
        urls = task.get("model_urls") or {}
        download_url(str(urls["glb"]), tf.parent / "model.glb")
        if task.get("thumbnail_url"):
            download_url(str(task["thumbnail_url"]), tf.parent / "thumb.png")
        res["glb"] = (tf.parent / "model.glb").as_posix()
    elif st in ("FAILED", "CANCELED", "EXPIRED"):
        res["error"] = task_error_message(task)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["prep", "start", "poll", "spend"])
    ap.add_argument("--layer", action="append", default=[])
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--wait", action="store_true")
    a = ap.parse_args()
    layers = a.layer or MESH_LAYERS
    if a.cmd == "spend":
        print(json.dumps({"spent": faction_spend(), "cap": cap(), "inflight": len(inflight())}))
        return 0
    if a.cmd == "prep":
        for lid in layers:
            print(json.dumps(prep(lid)), flush=True)
        return 0
    from meshy_client import load_api_key
    key = load_api_key()
    for lid in layers:
        r = start(key, lid, a.attempt) if a.cmd == "start" else poll(key, lid, a.attempt, a.wait)
        print(json.dumps(r), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
