#!/usr/bin/env python3
"""Inferno town scene: Meshy T2 textured building meshes in the full-3D lane (brief:
artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md; doc: docs/homm3_inferno_t2_town_buildings.md).

    prep     per planned layer: the Meshy input (the building's own mask over white, LANCZOS to 1024 px long side)
    concept  image-to-image (nano-banana-2, 6 cr) for the layers whose sprite the frame cuts (PLAN "concept")
    create   image-to-3d meshy-t2 smart-topology textured (15 cr), at most MAX_ACTIVE tasks at once; each billed call
             is appended to the shared ledger right after create, and the faction's ledger sum is checked against
             townCaps before every call (stop hard at the cap)
    poll     download model.glb / thumb.png of finished tasks
    fit      register each mesh to its sprite under the native rest camera (fit_mesh_to_sprite.Fitter: yaw, scale,
             contact pixel on the painted terrain, F-beta 0.5 against the sprite alpha; optional vertical stretch)
    stage    (TOWN_FULL3D_CANDIDATE=<c>, seeded from the installed candidate) replace Mesh_Body_<layer> of each meshed
             layer by the fitted Meshy mesh: the triangles the rest camera sees take the painting's own texels by
             rest-camera projection (de-lit by the Hex/Lit irradiance of their normals, so the rest pose reproduces
             the painting), every other triangle takes Meshy's own texture. Sprite pixels the mesh does not cover
             at rest keep the seed's depth-solid triangles there as Mesh_Body_<layer>_skirt (painted ground skirts:
             the lava river, gold floor, pit rims), so the rest frame still shows every painted pixel.
    sheet    review sheet: painting | before (installed fix_v2) | after, rest + sweeps, building zooms

Proof tier: generated artifact (offline previews / editor renders). Nothing here installs anything.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TOWN_FULL3D_FACTION", "inferno")
if os.environ["TOWN_FULL3D_FACTION"] != "inferno":
    raise SystemExit("inferno_t2_buildings.py is the Inferno lane; TOWN_FULL3D_FACTION must be inferno")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "homm3_meshy_frame_pose"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import stronghold_full3d_common as SC  # noqa: E402

ROOT = SC.ROOT
FACTION = "homm3_inferno"
MESHY = ROOT / "artifacts" / "meshy_town_scene_meshes"
OUTD = MESHY / FACTION
LEDGER = MESHY / "_ledger.jsonl"
BUDGET = MESHY / "_budget_t2_20260929.json"
MAX_ACTIVE = 8
PRICE = {"image-to-3d": 15, "image-to-image": 6}
SEED_CANDIDATE = "fix_v2"      # the installed Inferno candidate (8d7afff347): the "before"

# ------------------------------------------------------------------------------------------------ plan
# mesh: own = its own Meshy call; reuse:<lid> = the other layer's mesh fitted to this layer's sprite (same massing,
# the painting's texels still come from this layer); skip = keep the depth solid (why says why).
CONCEPT_PROMPT = ("Show this exact building complete and whole as one isolated 3D game asset on a plain white "
                  "background: the left part is cut off by the picture edge, so continue the building to the left "
                  "with the same stepped red-carpet terraces, walls, arches and materials, mirrored to a symmetric "
                  "whole. Keep the same viewing angle, colours and painted style. No ground, no scenery, no text.")
PLAN = {
    "tbinhall":   {"mesh": "own", "concept": True, "why": "village hall: long stepped terrace, frame cuts its left end"},
    "tbinhall_2": {"mesh": "reuse:tbinhall_3", "why": "town hall: same massing as city hall (shape differs by 144 px)"},
    "tbinhall_3": {"mesh": "own", "concept": True, "why": "city hall: grand stairs, frame cuts its left end"},
    "tbincstl":   {"mesh": "own", "why": "fort: the tall keep, the largest reachable building"},
    "tbincstl_2": {"mesh": "reuse:tbincstl", "why": "citadel: fort silhouette +342/-290 px, same massing"},
    "tbincstl_3": {"mesh": "own", "why": "castle: adds the two corner towers (+2642 px)"},
    "tbintvrn":   {"mesh": "own", "why": "tavern"},
    "tbinblak":   {"mesh": "own", "why": "blacksmith"},
    "tbinmark":   {"mesh": "own", "why": "marketplace (open timber sheds)"},
    "tbinsilo":   {"mesh": "own", "why": "resource silo (three bins)"},
    "tbinmage":   {"mesh": "own", "why": "mage guild 1"},
    "tbinmage_2": {"mesh": "own", "why": "mage guild 2 (one tier more)"},
    "tbinmage_3": {"mesh": "own", "why": "mage guild 3 (one tier more)"},
    "tbinmage_4": {"mesh": "own", "why": "mage guild 4 (one tier more)"},
    "tbinext1":   {"mesh": "own", "why": "brimstone pyre: horned cone"},
    "tbinext2":   {"mesh": "own", "why": "artifact market: pentagram wheel on spikes"},
    "tbindw_0":   {"mesh": "own", "why": "imp crucible"},
    "tbindw_0_2": {"mesh": "own", "why": "imp crucible upgrade: adds the gate towers (+1251 px)"},
    "tbindw_1":   {"mesh": "own", "why": "hall of sins with its lava stream"},
    "tbindw_1_2": {"mesh": "own", "why": "hall of sins upgrade: adds the tower (+1664 px)"},
    "tbindw_2":   {"mesh": "own", "why": "kennels: low walled pen"},
    "tbindw_2_2": {"mesh": "own", "why": "kennels upgrade: adds the gate tower"},
    "tbinhrd4":   {"mesh": "own", "why": "resource depot 2: kennels upgrade plus a second building (+1279 px)"},
    "tbindw_3":   {"mesh": "own", "why": "demon gate: two horned huts"},
    "tbindw_3_2": {"mesh": "own", "why": "demon gate upgrade: huge curved horns (+1333 px)"},
    "tbindw_4":   {"mesh": "skip", "why": "hell hole level 1 is a pit in the lava floor (a ground decal, 192x56, no "
                                            "standing structure): the depth solid follows the ground"},
    "tbindw_4_2": {"mesh": "own", "why": "hell hole upgrade: the pentagram gate over the pit"},
    "tbindw_5":   {"mesh": "skip", "why": "fire lake level 1 is the gold lava floor only (280x24, a ground decal)"},
    "tbindw_5_2": {"mesh": "own", "why": "fire lake upgrade: the two onion domes"},
    "tbindw_6":   {"mesh": "own", "why": "forsaken palace: walled hill fortress"},
    "tbindw_6_2": {"mesh": "own", "why": "forsaken palace upgrade: the horned dome (+5232 px)"},
    "tbinholy":   {"mesh": "skip", "why": "grail: a glowing demon apparition in the sky (no structure to model)"},
}
UNREACHABLE_NOTE = ("not reachable by any native level (building_layer_map nativeLevels), so not built: tbinhall_4, "
                    "tbinmage_5, tbinext0, tbifext5, tbinhrd1-3, tbinhrd2_2, tbinhrd2_4 and every tbindw_*_3")


def own_layers() -> list[str]:
    return [l for l, p in PLAN.items() if p["mesh"] == "own"]


def mesh_source(lid: str) -> str | None:
    p = PLAN[lid]["mesh"]
    return lid if p == "own" else p.split(":", 1)[1] if p.startswith("reuse:") else None


# ------------------------------------------------------------------------------------------------ ledger
def ledger_rows() -> list[dict]:
    if not LEDGER.is_file():
        return []
    out = []
    for ln in LEDGER.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))
    return out


def spent() -> dict:
    rows = [r for r in ledger_rows() if r.get("faction") == FACTION]
    return {"town": sum(int(r["credits"]) for r in rows if r.get("kind") != "claim" and not r.get("contingency")),
            "contingencySpent": sum(int(r["credits"]) for r in rows if r.get("kind") != "claim" and r.get("contingency")),
            "claimed": sum(int(r["credits"]) for r in rows if r.get("kind") == "claim")}


def cap() -> int:
    return int(json.loads(BUDGET.read_text(encoding="utf-8"))["townCaps"][FACTION])


def guard(kind: str, contingency: bool) -> None:
    s = spent()
    price = PRICE[kind]
    if contingency:
        if s["contingencySpent"] + price > s["claimed"]:
            raise SystemExit(f"contingency: spent {s['contingencySpent']} + {price} > claimed {s['claimed']}")
    elif s["town"] + price > cap():
        raise SystemExit(f"town cap: spent {s['town']} + {price} > cap {cap()} (stop)")


def append_ledger(layer: str, kind: str, credits: int, task_id: str, purpose: str, contingency: bool) -> None:
    row = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "faction": FACTION, "layer": layer,
           "kind": kind, "credits": credits, "taskId": task_id, "purpose": purpose}
    if contingency:
        row["contingency"] = True
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ------------------------------------------------------------------------------------------------ prep
# hand-set (native sprite px): a block of painted sky the sprite carries round its animated fire, dropped from the
# Meshy input where it is within 35 (max RGB) of the painting under it (the forge's chimney-top block measures
# 0-30 there; the flames 40-255 stay)
INPUT_SKY_BOX = {"tbinblak": (55, 0, 116, 26)}


def layer_rgba(lid: str) -> Image.Image:
    """The sprite with alpha = its own alpha minus the shadow / magenta leftovers and minus LARGE regions identical to
    the painting under them (>= 200 native px, max RGB diff <= 10) and INPUT_SKY_BOX (the sky block cut round the
    forge's chimney), cropped, with the keep's dithered specks closed (below). The lane's native_mask drops every bg-identical px, which on white crumbles the
    keep's dark tower tops."""
    L = SC.layers()[lid]
    spr = np.asarray(SC.sprite(L)).copy()
    r, g, b = (spr[..., i].astype(np.int32) for i in range(3))
    magenta = (r > 120) & (b > 120) & (g < 0.62 * np.minimum(r, b))
    m = (spr[..., 3] > 128) & ~magenta
    bg = np.asarray(SC.background_rgb()).astype(np.int32)
    x, y = L["x"], L["y"]
    h, w = spr.shape[:2]
    under = np.zeros((h, w, 3), np.int32) - 999
    hh, ww = min(h, bg.shape[0] - y), min(w, bg.shape[1] - x)
    under[:hh, :ww] = bg[y:y + hh, x:x + ww]
    diff = np.abs(spr[..., :3].astype(np.int32) - under).max(-1)
    same = (diff <= 10) & m
    n, lab, st, _ = cv2.connectedComponentsWithStats(same.astype(np.uint8), connectivity=8)
    m &= ~np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 200])
    box = INPUT_SKY_BOX.get(lid)
    if box:
        x0, y0, x1, y1 = box
        sky = np.zeros_like(m)
        sky[y0:y1, x0:x1] = diff[y0:y1, x0:x1] <= 35
        m &= ~sky
    # the keep's sprite is dithered with 1-3 px transparent specks inside its walls: close them (3x3) and fill
    # enclosed holes under 60 px, colours inpainted, so Meshy does not model them as holes
    mc = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0
    inv = (~mc).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    border = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]]).tolist())
    holes = np.isin(lab, [i for i in range(1, n) if i not in border and st[i, cv2.CC_STAT_AREA] < 60])
    mf = mc | holes
    fill = mf & ~m
    rgb = cv2.inpaint(np.ascontiguousarray(spr[..., :3]), fill.astype(np.uint8), 3, cv2.INPAINT_TELEA)
    spr[..., :3] = rgb
    m = mf
    spr[..., 3] = np.where(m, 255, 0).astype(np.uint8)
    ys, xs = np.nonzero(m)
    return Image.fromarray(spr[ys.min():ys.max() + 1, xs.min():xs.max() + 1])


def on_white(rgba: Image.Image, long_side: int = 1024, pad: float = 0.04) -> Image.Image:
    w, h = rgba.size
    k = long_side * (1 - 2 * pad) / max(w, h)
    s = rgba.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
    cw, ch = (long_side, round(h * k / (1 - 2 * pad))) if w >= h else (round(w * k / (1 - 2 * pad)), long_side)
    canvas = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))
    canvas.alpha_composite(s, ((cw - s.width) // 2, (ch - s.height) // 2))
    return canvas.convert("RGB")


def prep() -> None:
    for lid in own_layers():
        d = OUTD / lid
        d.mkdir(parents=True, exist_ok=True)
        on_white(layer_rgba(lid)).save(d / "input.png")
    print(json.dumps({"prepared": own_layers()}))


# ------------------------------------------------------------------------------------------------ meshy
def _key() -> str:
    import meshy_client as MC
    return MC.load_api_key()


def concept(layers: list[str], contingency: bool) -> None:
    import meshy_client as MC
    key = _key()
    for lid in layers:
        d = OUTD / lid / "concept"
        tf = d / "task.json"
        if tf.is_file():
            print(lid, "concept exists", json.loads(tf.read_text())["taskId"])
            continue
        guard("image-to-image", contingency)
        d.mkdir(parents=True, exist_ok=True)
        tid = MC.create_image_to_image(key, prompt=CONCEPT_PROMPT, reference_paths=[OUTD / lid / "input.png"],
                                       ai_model="nano-banana-2")
        append_ledger(lid, "image-to-image nano-banana-2", 6, tid, "concept: complete the frame-cut hall",
                      contingency)
        tf.write_text(json.dumps({"taskId": tid, "kind": "image-to-image", "prompt": CONCEPT_PROMPT,
                                  "created": time.time()}, indent=1), encoding="utf-8")
        print(lid, "concept", tid)


def task_dir(lid: str, tag: str) -> Path:
    return OUTD / lid / tag


def active_tasks(key) -> list:
    import meshy_client as MC
    act = []
    for tf in OUTD.glob("*/*/task.json"):
        t = json.loads(tf.read_text(encoding="utf-8"))
        if t.get("status") in ("SUCCEEDED", "FAILED", "CANCELED"):
            continue
        st = MC.get_task(key, t["kind"], t["taskId"])
        t["status"] = st.get("status")
        tf.write_text(json.dumps(t, indent=1), encoding="utf-8")
        if t["status"] not in ("SUCCEEDED", "FAILED", "CANCELED"):
            act.append(tf)
    return act


def create(layers: list[str], tag: str, contingency: bool, purpose: str) -> None:
    import meshy_client as MC
    key = _key()
    for lid in layers:
        d = task_dir(lid, tag)
        tf = d / "task.json"
        if tf.is_file():
            print(lid, tag, "exists", json.loads(tf.read_text())["taskId"])
            continue
        src = OUTD / lid / "concept" / "concept.png"
        if not PLAN[lid].get("concept"):
            src = OUTD / lid / "input.png"
        elif not src.is_file():
            raise SystemExit(f"{lid}: concept.png missing (run concept + poll first)")
        while len(active_tasks(key)) >= MAX_ACTIVE:
            time.sleep(20)
        guard("image-to-3d", contingency)
        d.mkdir(parents=True, exist_ok=True)
        tid = MC.create_image_to_3d(key, image_path=src, should_texture=True, model_type="smart-topology",
                                    ai_model="meshy-t2")
        append_ledger(lid, "image-to-3d meshy-t2 textured", 15, tid, f"{lid}: {purpose}", contingency)
        tf.write_text(json.dumps({"taskId": tid, "kind": "image-to-3d", "input": str(src.relative_to(ROOT)),
                                  "created": time.time(), "status": "PENDING"}, indent=1), encoding="utf-8")
        print(lid, tag, tid, spent(), flush=True)


def poll(wait: bool) -> None:
    import meshy_client as MC
    key = _key()
    while True:
        pending = 0
        for tf in sorted(OUTD.glob("*/*/task.json")):
            t = json.loads(tf.read_text(encoding="utf-8"))
            d = tf.parent
            done = (d / ("concept.png" if t["kind"] == "image-to-image" else "model.glb")).is_file()
            if done or t.get("status") in ("FAILED", "CANCELED"):
                continue
            st = MC.get_task(key, t["kind"], t["taskId"])
            t["status"] = st.get("status")
            if t["status"] == "SUCCEEDED":
                if t["kind"] == "image-to-image":
                    MC.download_url(st["image_urls"][0], d / "concept.png")
                else:
                    MC.download_url(st["model_urls"]["glb"], d / "model.glb")
                    if st.get("thumbnail_url"):
                        MC.download_url(st["thumbnail_url"], d / "thumb.png")
                t["finished"] = time.time()
                print(tf.parent.relative_to(OUTD), "SUCCEEDED", flush=True)
            elif t["status"] in ("FAILED", "CANCELED"):
                t["error"] = MC.task_error_message(st)
                print(tf.parent.relative_to(OUTD), t["status"], t["error"], flush=True)
            else:
                pending += 1
            tf.write_text(json.dumps(t, indent=1), encoding="utf-8")
        if not wait or pending == 0:
            print(json.dumps({"pending": pending, **spent()}))
            return
        time.sleep(20)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "prep", "concept", "create", "poll", "fit", "stage", "review", "select", "sheet", "spent",
                                    "mark-meshy"])
    ap.add_argument("--layers", default="")
    ap.add_argument("--tag", default="t2")
    ap.add_argument("--contingency", action="store_true", help="bill against this faction's contingency claims")
    ap.add_argument("--purpose", default="town building mesh (first pass)")
    ap.add_argument("--wait", action="store_true")
    args = ap.parse_args()
    layers = [x for x in args.layers.split(",") if x]
    if args.cmd == "plan":
        print(json.dumps({"plan": PLAN, "own": own_layers(), "credits": 15 * len(own_layers()) + 6 * sum(
            1 for p in PLAN.values() if p.get("concept")), "cap": cap(), **spent()}, indent=1))
    elif args.cmd == "spent":
        print(json.dumps({"cap": cap(), **spent()}))
    elif args.cmd == "prep":
        prep()
    elif args.cmd == "concept":
        concept(layers or [l for l, p in PLAN.items() if p.get("concept")], args.contingency)
    elif args.cmd == "create":
        create(layers or own_layers(), args.tag, args.contingency, args.purpose)
    elif args.cmd == "poll":
        poll(args.wait)
    elif args.cmd == "fit":
        import inferno_t2_integrate as IG
        IG.fit_all(layers or [l for l in PLAN if mesh_source(l)], args.tag)
    elif args.cmd == "stage":
        import inferno_t2_integrate as IG
        IG.stage(layers or [l for l in PLAN if mesh_source(l)], args.tag)
    elif args.cmd == "review":
        import inferno_t2_integrate as IG
        IG.layer_review(layers or [l for l in PLAN if mesh_source(l)])
    elif args.cmd == "select":
        import inferno_t2_integrate as IG
        IG.select(layers or [l for l in PLAN if mesh_source(l)])
    elif args.cmd == "sheet":
        import inferno_t2_integrate as IG
        IG.sheet()
    elif args.cmd == "mark-meshy":
        import inferno_t2_integrate as IG
        IG.mark_meshy([x for x in args.layers.split(",") if x] or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
