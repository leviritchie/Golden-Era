#!/usr/bin/env python3
"""Cove (HotA) town buildings as Meshy T2 textured meshes in the full-3D lane (docs/homm3_cove_t2_town_buildings.md).

Brief: artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md (budget, ledger, look bar). Faction-scoped on purpose: 11
agents rebuild their towns in parallel, so the shared stronghold_full3d_* modules are only imported, never edited.

    python tools/homm3_town_scene_meshes/cove_t2_buildings.py prep                 # Meshy inputs (sprite on white)
    python tools/homm3_town_scene_meshes/cove_t2_buildings.py generate [--only a,b] [--retry]   # BILLED (15 cr / layer)
    python tools/homm3_town_scene_meshes/cove_t2_buildings.py status

Generation: one `image-to-3d` call per layer, ai_model meshy-t2, model_type smart-topology, should_texture True, no
texture prompt / image (15 credits, measured by the Castle price check). The input is the layer's own mask (the lane's
native_mask: alpha minus the HoMM3 shadow leftovers and the pixels identical to the painting under the sprite) over
white, scaled LANCZOS to fit 1024 px. Every billed call is appended to the shared ledger right after create, and the
cove spend is re-summed from the ledger before every call (hard stop at townCaps + this faction's contingency claims).
Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("TOWN_FULL3D_FACTION", "cove")
if os.environ["TOWN_FULL3D_FACTION"] != "cove":
    raise SystemExit("cove_t2_buildings: TOWN_FULL3D_FACTION must be cove")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

FACTION = "homm3_cove"
MESHY = ROOT / "artifacts" / "meshy_town_scene_meshes"
OUTD = MESHY / FACTION
LEDGER = MESHY / "_ledger.jsonl"
BUDGET = MESHY / "_budget_t2_20260929.json"
PRICE = 15
MAX_PARALLEL = 4           # coordinator 2026-09-29: at most 4 Meshy tasks at once
POLYCOUNT = 12000
INPUT_PX = 1024
MARGIN = 0.06

# What is meshed, in priority order (brief: large reachable buildings that stretch at the sweeps, then each upgrade
# sprite that looks different). Measured upgrade differences (changed-pixel share over the union alpha, bottom
# aligned): hall->hal2 0.215, hal2->hal3 0.623, cstl->cas2 0.081, cas2->cas3 0.26, say1->say2 0.074 (say2 is 32 px
# taller), say2->sa2p 0.287, sor1->sor2 0.237. Every one is meshed on its own (the budget allows it and each mesh is
# registered to its own sprite; the projection carries each sprite's own texels regardless).
MESH_LAYERS = [
    "tbcvtave", "tbcvhall", "tbcvhal2", "tbcvhal3", "tbcvsmth", "tbcvmark", "tbcvcstl", "tbcvcas2", "tbcvcas3",
    "tbcvsay1", "tbcvsay2", "tbcvsa2p", "tbcvthgd", "tbcvdock", "tbcvpir1", "tbcvpir2", "tbcvnix1", "tbcvnix2",
    "tbcvgmg1", "tbcvgmg2", "tbcvgmg3", "tbcvgmg4", "tbcvsor1", "tbcvsor2", "tbcvass1", "tbcvass2",
]
# Reachable layers left to the lane's depth solid, with the reason (brief item 3).
SKIP = {
    "tbcvgral": "the Grail is the star-sky panorama painted across the whole top of the screen (800x200): sky, not a "
                "structure",
    "tbcvnmp1": "the waterfall pouring down the painted cliff (an Fx water effect over the cliff's own rock); no "
                "standalone structure",
    "tbcvnmp2": "the same waterfall with a small mermaid statue at its lip; the structure is a few px of statue on "
                "painted cliff",
    "tbcvwhr1": "the whirlpool is a flat water disc on the lagoon (246x37) animated as an Fx water effect",
    "tbcvwhr2": "the upgraded whirlpool: the same flat disc with a rock rim (271x75), an Fx water effect",
    "tbcvsmrk": "the resource silo is three 21 px chests at the bottom edge (decal scale)",
}


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


def spend() -> dict:
    rows = [r for r in ledger_rows() if r.get("faction") == FACTION]
    spent = sum(int(r["credits"]) for r in rows if r.get("kind") != "claim")
    claimed = sum(int(r["credits"]) for r in rows if r.get("kind") == "claim")
    cap = int(json.loads(BUDGET.read_text(encoding="utf-8"))["townCaps"][FACTION])
    return {"spent": spent, "claimed": claimed, "cap": cap, "limit": cap + claimed, "calls": len(rows)}


def ledger_append(row: dict) -> None:
    line = json.dumps(row) + "\n"
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


# ------------------------------------------------------------------------------------------------ prep
def sprite_mask(L: dict) -> np.ndarray:
    """The sprite's own opaque pixels: alpha > 128 minus the HoMM3 magenta shadow leftovers, specks < 25 px dropped.
    Not the lane's native_mask: that also drops sprite pixels identical to the painting under them, and the Cove
    painting repeats most of the stilts, the hall's rock footing and the wreck's shore (native_mask keeps 98x49 of
    the 212x98 wreck), which would leave Meshy a floating roof."""
    import cv2
    import stronghold_full3d_common as SC
    spr = np.asarray(SC.sprite(L).convert("RGBA")).astype(np.int32)
    r, g, b = spr[..., 0], spr[..., 1], spr[..., 2]
    magenta = (r > 120) & (b > 120) & (g < 0.62 * np.minimum(r, b))
    m = ((spr[..., 3] > 128) & ~magenta).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 25
    return keep[lab]


MAIN_BLOB_ONLY = {"tbcvnix1", "tbcvnix2"}
# Retry 1 (2026-09-29): with the gaps between the thin stilts closed and filled from the dark painting under them, the
# first T2 pass read the dwellings' stilt rows as two solid walls; these take the plain opaque pixels instead.
NO_CLOSE = {"tbcvsay1", "tbcvsay2"}   # the pool-rim fragment below the gate is a separate piece of painted rock


def input_mask(lid: str, L: dict) -> np.ndarray:
    """Meshy's view of the sprite: the opaque pixels closed over the dither holes (5x5), small enclosed holes filled; for
    MAIN_BLOB_ONLY the largest closed component only. Holes of 300 native px or more stay open (the sky\n    framed by tbcvcas3's rope arc)."""
    import cv2
    m = sprite_mask(L).astype(np.uint8)
    if lid in NO_CLOSE:
        return m.astype(bool)
    c = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    inv = (1 - c).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    border = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]]).tolist())
    c = c.astype(bool) | np.isin(lab, [i for i in range(1, n) if i not in border and st[i, cv2.CC_STAT_AREA] < 300])
    if lid in MAIN_BLOB_ONLY:
        n, lab, st, _ = cv2.connectedComponentsWithStats(c.astype(np.uint8), connectivity=8)
        c = lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    return c


def composite_under(L: dict) -> np.ndarray:
    """The sprite over the painting under it (native px, float RGB): the dither holes show the painting, as in game."""
    import stronghold_full3d_common as SC
    spr = SC.sprite(L).convert("RGBA")
    bg = SC.background_rgba().convert("RGBA")
    crop = bg.crop((L["x"], L["y"], L["x"] + spr.width, L["y"] + spr.height))
    crop.alpha_composite(spr)
    return np.asarray(crop.convert("RGB")).astype(np.float32)


def prep(only=None) -> None:
    import stronghold_full3d_common as SC
    lays = SC.layers()
    reach = set(SC.reachable_layers())
    for lid in MESH_LAYERS:
        if only and lid not in only:
            continue
        if lid not in reach:
            raise SystemExit(f"{lid}: not a reachable layer")
        L = lays[lid]
        m = input_mask(lid, L)
        comp = composite_under(L)
        ys, xs = np.nonzero(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        rgb = np.where(m[..., None], comp, 255.0)[y0:y1, x0:x1]
        h, w = rgb.shape[:2]
        s = INPUT_PX * (1 - 2 * MARGIN) / max(h, w)
        big = Image.fromarray(rgb.astype(np.uint8)).resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
        can = Image.new("RGB", (INPUT_PX, INPUT_PX), (255, 255, 255))
        can.paste(big, ((INPUT_PX - big.width) // 2, (INPUT_PX - big.height) // 2))
        d = OUTD / lid
        d.mkdir(parents=True, exist_ok=True)
        can.save(d / "input.png")
        (d / "input.json").write_text(json.dumps({"layer": lid, "sprite": L["sprite"], "maskPx": int(m.sum()),
                                                  "cropNative": [int(x0), int(y0), int(x1), int(y1)],
                                                  "scale": round(s, 3), "canvas": INPUT_PX, "bg": "white",
                                                  "resample": "LANCZOS", "mask": "input_mask (sprite_mask closed 5x5, holes filled) over the painting-composited sprite"},
                                                 indent=1), encoding="utf-8")
        print(lid, (w, h), "x", round(s, 2))


def contact_sheet(name: str, files: list[tuple[str, Path]], cell=256) -> Path:
    from PIL import ImageDraw
    cols = 7
    rows = (len(files) + cols - 1) // cols
    out = Image.new("RGB", (cols * cell, rows * (cell + 16)), (255, 255, 255))
    d = ImageDraw.Draw(out)
    for i, (lab, p) in enumerate(files):
        x, y = (i % cols) * cell, (i // cols) * (cell + 16)
        if p.is_file():
            im = Image.open(p).convert("RGB")
            im.thumbnail((cell, cell))
            out.paste(im, (x, y + 16))
        d.text((x + 3, y + 2), lab, fill=(0, 0, 0))
    dest = OUTD / name
    out.save(dest)
    return dest


# ------------------------------------------------------------------------------------------------ generate
def generate(only=None, retry=False) -> None:
    import meshy_client as MC
    key = MC.load_api_key(ROOT / ".env")
    todo = []
    for lid in MESH_LAYERS:
        if only and lid not in only:
            continue
        d = OUTD / lid
        if not (d / "input.png").is_file():
            raise SystemExit(f"{lid}: no input.png (run prep)")
        if (d / "model.glb").is_file() and not retry:
            continue
        todo.append(lid)
    running: dict[str, str] = {}
    done = []
    while todo or running:
        while todo and len(running) < MAX_PARALLEL:
            sp = spend()
            if sp["spent"] + PRICE > sp["limit"]:
                print(json.dumps({"stop": "cap", **sp, "left": todo}))
                todo = []
                break
            lid = todo.pop(0)
            d = OUTD / lid
            if retry and (d / "model.glb").is_file():
                k = 1
                while (d / f"attempt{k}").exists():
                    k += 1
                (d / f"attempt{k}").mkdir()
                for f in ("model.glb", "thumb.png", "task.json"):
                    if (d / f).is_file():
                        (d / f).rename(d / f"attempt{k}" / f)
            tid = MC.create_image_to_3d(key, image_path=d / "input.png", should_texture=True,
                                        target_polycount=POLYCOUNT, model_type="smart-topology", ai_model="meshy-t2")
            ledger_append({"ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "faction": FACTION, "layer": lid,
                           "kind": "image-to-3d meshy-t2 textured", "credits": PRICE, "taskId": tid,
                           "purpose": ("retry: " if retry else "") + "town building mesh"})
            (d / "task.json").write_text(json.dumps({"taskId": tid, "created": time.time(), "polycount": POLYCOUNT,
                                                     "aiModel": "meshy-t2", "modelType": "smart-topology",
                                                     "shouldTexture": True}, indent=1), encoding="utf-8")
            running[lid] = tid
            print("created", lid, tid, flush=True)
        time.sleep(15)
        for lid, tid in list(running.items()):
            t = MC.get_task(key, "image-to-3d", tid)
            st = t.get("status")
            if st in ("SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"):
                d = OUTD / lid
                meta = json.loads((d / "task.json").read_text(encoding="utf-8"))
                meta.update({"status": st, "finished": time.time(), "error": MC.task_error_message(t) if st != "SUCCEEDED" else None})
                if st == "SUCCEEDED":
                    MC.download_url(t["model_urls"]["glb"], d / "model.glb")
                    if t.get("thumbnail_url"):
                        MC.download_url(t["thumbnail_url"], d / "thumb.png")
                (d / "task.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
                print(lid, st, flush=True)
                del running[lid]
                done.append(lid)
    print(json.dumps(spend()))


def status() -> None:
    rows = []
    for lid in MESH_LAYERS:
        d = OUTD / lid
        t = json.loads((d / "task.json").read_text(encoding="utf-8")) if (d / "task.json").is_file() else {}
        rows.append((lid, t.get("status", "-"), (d / "model.glb").is_file()))
    for r in rows:
        print(*r)
    print(json.dumps(spend()))
    contact_sheet("thumbs_sheet.png", [(lid, OUTD / lid / "thumb.png") for lid in MESH_LAYERS])
    contact_sheet("inputs_sheet.png", [(lid, OUTD / lid / "input.png") for lid in MESH_LAYERS])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "generate", "status"])
    ap.add_argument("--only", default="")
    ap.add_argument("--retry", action="store_true")
    a = ap.parse_args()
    only = [x for x in a.only.split(",") if x] or None
    if a.cmd == "prep":
        prep(only)
        contact_sheet("inputs_sheet.png", [(lid, OUTD / lid / "input.png") for lid in MESH_LAYERS])
    elif a.cmd == "generate":
        generate(only, a.retry)
    else:
        status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
