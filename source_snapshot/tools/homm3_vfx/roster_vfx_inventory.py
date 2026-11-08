"""Roster VFX inventory: what effects each DEF-retarget unit's own sprite draws, per clip.

Usage:
  python tools/homm3_vfx/roster_vfx_inventory.py [unit ...] [--no-sheets] [--no-bones]
Default: every artifacts/homm3_def_retarget/<unit>/ with a frames.json.

Outputs (artifacts/homm3_vfx_experiments/_roster/):
  inventory.json            per unit: DEF, faction, idle self-effect, translucency, per-group events,
                            shooter/projectile status, tier (effect_heavy | attack_accents | none)
  inventory_summary.md      ranked roster
  factions/<faction>.json / .md   the same, one file per custom faction (for the faction agents)
  sheets/<unit>.png         per-group contact sheet: effect pixels in colour over the dimmed body
                            (regenerable, not in git)

Measurement rules live in def_effects.py.  Everything here is generated-artifact evidence from the
extracted DEF PNGs the retarget consumed; nothing is rendered or seen in game.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import traceback

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(__file__))
import def_effects as D  # noqa: E402

ROOT = D.ROOT
OUT = os.path.join(ROOT, "artifacts/homm3_vfx_experiments/_roster")
EXCLUDED = {"h3_giant_upg": "Titan: owned by the lighting agent (first combined unit-look case)",
            "hota_cove_oceanid": "Oceanid: owned by a separate agent",
            "h3_sacred_phoenix": "Phoenix: owned by a separate agent", "h3_phoenix": "Phoenix: owned by a separate agent",
            "h3_firebird": "Phoenix line (firebird): check with the phoenix owner",
            "hota_cove_seaman": "Seaman: deferred"}
CLASS_KIND = {"electric": "lightning/bolt (white-blue)", "fire": "fire/flame", "magic": "magic glow/aura",
              "water": "water/ice", "smoke": "smoke/dust", "detached": "detached particles"}
PALETTE = {"electric": (120, 200, 255), "fire": (255, 140, 30), "magic": (60, 255, 120), "water": (40, 90, 255),
           "smoke": (200, 200, 200), "detached": (255, 60, 220)}


# ----------------------------------------------------------------------------- faction mapping (roster_status rules)
def faction_map() -> dict[str, list[tuple[str, int, str, str]]]:
    """unit id -> [(faction, tier, variant, name)], using roster_status.py's candidate rules (copied, read-only)."""
    snake = lambda s: re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    known = set(os.listdir(D.ART))
    variants = ["", "_upg", "_upg_alt"]
    out: dict[str, list] = {}
    for fp in sorted(glob.glob(os.path.join(ROOT, "custom_factions", "homm3_*.json"))):
        fac = os.path.basename(fp)[6:-5]
        for line in json.load(open(fp)).get("unitLines", []):
            base = line["baseSid"]
            first = snake(line["names"][0])
            prefix = base[: -len(first)] if base.endswith(first) else base.rsplit("_", 1)[0] + "_"
            for v, name in enumerate(line["names"]):
                sn = snake(name)
                cands = [prefix + sn] + sorted(k for k in known if re.fullmatch(r"(hota_[a-z]+|toa|temple)_" + re.escape(sn), k))
                cands += [base + variants[v]]
                if prefix != "h3_":
                    cands.append("h3_" + snake(line["names"][0]) + variants[v])
                hit = next((c for c in dict.fromkeys(cands) if c in known), None)
                if hit:
                    out.setdefault(hit, []).append((fac, line["tier"], variants[v] or "base", name))
    return out


def projectile_specs() -> dict[str, dict]:
    """The native-substitute projectile table the release overlay writes (read by regex, not imported)."""
    src = open(os.path.join(ROOT, "tools/release_port/apply_release_core_overlay.py"), encoding="utf-8").read()
    body = src.split("VANILLA_PROJECTILE_SPECS_BY_UNIT_SID", 1)[1].split("\n}\n", 1)[0]
    return {m.group(1): {"projectile": m.group(2), "trajectory": m.group(3)}
            for m in re.finditer(r'"([a-z0-9_]+)":\s*\{"projectile":\s*"([^"]+)".*?"trajectory":\s*"([^"]+)"', body)}


# ----------------------------------------------------------------------------- per-unit measurement
def idle_self_effect(us: D.UnitSprite) -> dict:
    """Effect-class paint that is present in idle (so not 'novel'): share of the body and its flicker."""
    frames = us.group_rgba(2)
    if not frames:
        return {}
    shares, flick, other_flick = {c: [] for c in D.EFFECT_CLASSES}, {c: [] for c in D.EFFECT_CLASSES}, []
    prev = None
    for a in frames:
        op = a[..., 3] == 255
        cls = D.colour_class(a[..., :3])
        cls[~op] = 255
        n = max(1, int(op.sum()))
        for k, c in enumerate(D.EFFECT_CLASSES, start=1):
            shares[c].append(float((cls == k).sum()) / n)
        if prev is not None:
            pc, pop = prev
            both = op & pop
            for k, c in enumerate(D.EFFECT_CLASSES, start=1):
                m, pm = cls == k, pc == k
                u = int((m | pm).sum())
                if u >= 10:
                    flick[c].append(float((m ^ pm).sum()) / u)
            other = both & (cls == 0) & (pc == 0)
            ch = both & ((a[..., :3].astype(int) - prev_rgb.astype(int)) != 0).any(-1)
            other_flick.append(float((ch & other).sum()) / max(1, int(other.sum())))
        prev = (cls, op)
        prev_rgb = a[..., :3]
    base_change = float(np.mean(other_flick)) if other_flick else 0.0
    out = {"bodyChangeRate": round(base_change, 3), "classes": {}}
    for c in D.EFFECT_CLASSES:
        sh = float(np.mean(shares[c]))
        if sh < 0.03 or c == "smoke":
            continue
        fl = float(np.mean(flick[c])) if flick[c] else 0.0
        out["classes"][c] = {"bodyShare": round(sh, 3), "flicker": round(fl, 3),
                             "animated": bool(fl >= 0.35 and c in ("fire", "electric", "magic")),
                             "steadyGlowCandidate": bool(fl < 0.2 and c in ("fire", "electric", "magic") and sh >= 0.05)}
    det = []
    for a in frames:
        _, n, main, sizes = D.components(a[..., 3] == 255)
        det.append(int(sizes.sum() - sizes[main]) if n else 0)
    out["idleDetachedPx"] = int(np.median(det)) if det else 0
    return out


def event_kind(ev, g, head_origin):
    cls = ev["class"]
    attacky = g in (11, 12, 13, 14, 15, 16, 17, 18, 19)
    if ev.get("posePaintSuspect"):
        return f"pose paint? ({CLASS_KIND[cls]}; steady in every frame, likely body colour absent from idle)"
    if ev.get("onBodyShareAtPeak", 0) >= 0.6 and ev["motion"] == "in_place" and cls != "detached":
        return f"on-body tint/rim ({CLASS_KIND[cls]}; painted over the body: effect light or texture, not a flipbook)"
    if head_origin and attacky and ev["motion"] in ("extends", "travels") and cls in ("fire", "magic", "water", "smoke"):
        return f"breath/spit ({CLASS_KIND[cls]}, from the head)"
    if ev["motion"] == "travels" and attacky:
        return "thrown/missile-like (detached, travels)" if cls in ("detached", "smoke") else f"thrown {CLASS_KIND[cls]}"
    if ev.get("heldShare", 0) >= 0.8 and ev["motion"] == "in_place":
        return f"held/steady {CLASS_KIND[cls]}"
    return CLASS_KIND[cls]

def analyse(us: D.UnitSprite, bones: D.BoneProjector | None) -> dict:
    base = D.baseline(us)
    idle0 = (us.group_rgba(2) or us.group_rgba(0))[0]
    idle_body = int((idle0[..., 3] == 255).sum())
    thr = max(12, int(0.006 * idle_body))
    groups = {}
    sheet_rows = []
    for g in sorted(us.groups):
        frames = us.group_rgba(g)
        rows, masks = [], []
        l0 = None
        for i, a in enumerate(frames):
            fe = D.frame_effects(a, base)
            fx, cls, body = fe["fx"], fe["cls"], fe["body"]
            bodyonly = fe["opaque"] & ~fx
            lm = float(D.luma(a[..., :3][bodyonly]).mean()) if bodyonly.any() else 0.0
            l0 = lm if l0 is None else l0
            n = int(fx.sum())
            byc = {c: int((fx & (cls == k)).sum()) for k, c in enumerate(D.EFFECT_CLASSES, start=1)}
            byc["detached"] = int((fx & fe["detached"] & (cls == 0)).sum())
            r = {"i": i, "fxPx": n, "byClass": {k: v for k, v in byc.items() if v}, "bodyLumaRise": round(lm - l0, 1)}
            if n:
                ys, xs = np.nonzero(fx)
                r["bbox"] = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                r["centroid"] = [round(float(xs.mean()), 1), round(float(ys.mean()), 1)]
                by, bx = np.nonzero(body)
                if len(bx):
                    r["bodyBbox"] = [int(bx.min()), int(by.min()), int(bx.max()) + 1, int(by.max()) + 1]
                near = fx & ndi.binary_dilation(body, iterations=3)
                if near.any():
                    yy, xx = np.nonzero(near)
                    r["attach"] = [round(float(xx.mean()), 1), round(float(yy.mean()), 1)]
                r["detachedComponents"] = int(ndi.label(fe["detached"], structure=np.ones((3, 3)))[1])
                bodyfrac = ndi.uniform_filter((fe["opaque"] & ~fx).astype(np.float32), size=5, mode="constant")
                r["onBodyShare"] = round(float((bodyfrac[fx] >= 0.4).mean()), 2)
            rows.append(r)
            masks.append(fx)
        # frame holds (whole frame identical to the previous one)
        holds = [i for i in range(1, len(frames)) if np.array_equal(frames[i], frames[i - 1])]
        # events: runs of frames with fx >= thr
        events, cur = [], []
        for r in rows + [{"i": -1, "fxPx": 0}]:
            if r["fxPx"] >= thr:
                cur.append(r)
            elif cur:
                events.append(cur)
                cur = []
        evs = []
        for run in events:
            tot = {}
            for r in run:
                for k, v in r["byClass"].items():
                    tot[k] = tot.get(k, 0) + v
            cls = max(tot, key=tot.get) if tot else "detached"
            peak = max(run, key=lambda r: r["fxPx"])
            cents = [r["centroid"] for r in run]
            steps = [float(np.hypot(b[0] - a[0], b[1] - a[1])) for a, b in zip(cents, cents[1:])]
            bb = peak.get("bodyBbox", peak["bbox"])
            # distance of the effect's far edge from the body's front (sprites face right)
            front = max(r["bbox"][2] - r.get("bodyBbox", r["bbox"])[2] for r in run)
            travel = float(np.hypot(cents[-1][0] - cents[0][0], cents[-1][1] - cents[0][1])) if len(cents) > 1 else 0.0
            det_share = float(np.mean([r["byClass"].get("detached", 0) / max(1, r["fxPx"]) for r in run]))
            areas = [(r["bbox"][2] - r["bbox"][0]) * (r["bbox"][3] - r["bbox"][1]) for r in run]
            if len(run) >= 2 and travel >= 20 and np.median(steps) >= 6 and (det_share >= 0.4 or max(areas) < 3 * max(1, min(areas))):
                motion = "travels"
            elif len(run) >= 2 and max(areas) >= 2.5 * max(1, areas[0]) and front >= 10:
                motion = "extends"
            else:
                motion = "in_place"
            fx_holds = [run[k]["i"] for k in range(1, len(run)) if np.array_equal(masks[run[k]["i"]], masks[run[k - 1]["i"]])]
            first = run[0]
            ev = {"frames": [r["i"] for r in run], "class": cls, "classPx": tot,
                  "peakFrame": peak["i"], "peakPx": peak["fxPx"], "peakShareOfBody": round(peak["fxPx"] / max(1, idle_body), 3),
                  "bboxAtPeak": peak["bbox"],
                  "originFrame": first["i"], "originPoint": first.get("attach") or first["centroid"],
                  "regionAtOrigin": region_label(first.get("attach") or first["centroid"], first.get("bodyBbox", first["bbox"])),
                  "regionAtPeak": region_label(peak.get("attach") or peak["centroid"], bb),
                  "motion": motion, "travelPx": round(travel, 1),
                  "medianStepPx": round(float(np.median(steps)), 1) if steps else 0.0,
                  "extendsFrontPx": int(front), "detachedShare": round(det_share, 2), "fxHolds": fx_holds,
                  "heldShare": round(len(run) / max(1, len(frames)), 2), "onBodyShareAtPeak": peak.get("onBodyShare", 0.0),
                  "detachedComponentsAtPeak": peak.get("detachedComponents", 0)}
            head_origin = ev["regionAtOrigin"] in ("top-front", "top-centre", "above-front", "top-ahead")
            if bones is not None:
                for key, fr_, pt in (("boneCandidatesAtOrigin", first["i"], ev["originPoint"]),
                                     ("boneCandidatesAtPeak", peak["i"], peak.get("attach") or peak["centroid"])):
                    m = us.master_index(g, fr_)
                    if m is not None:
                        ev[key] = D.bone_candidates(bones.pixels(m), tuple(pt), k=3)
                        ev["boneFrom"] = "GLB *_DEF_Master action, SpriteCam projection"
                m0 = us.master_index(g, first["i"])
                if m0 is not None:
                    px = bones.pixels(m0)
                    hb = [px[b] for b in px if b in ("Head", "Neck") or b.startswith(("Head", "Jaw"))]
                    if hb:
                        yy, xx = np.nonzero(masks[first["i"]])
                        dmin = min(float(np.min(np.hypot(xx - hx, yy - hy))) for hx, hy in hb)
                        ev["headDistPxAtOrigin"] = round(dmin, 1)
                        head_origin = dmin <= max(6.0, 0.08 * (bb[3] - bb[1]))
            cnt = [r["fxPx"] for r in run]
            ev["posePaintSuspect"] = bool(len(run) == len(frames) and len(frames) >= 3 and motion == "in_place"
                                          and float(np.std(cnt)) <= 0.3 * float(np.mean(cnt)))
            ev["kind"] = event_kind(ev, g, head_origin)
            evs.append(ev)
        glow = max((r["bodyLumaRise"] for r in rows), default=0.0)
        groups[g] = {"name": D.GROUP_NAMES.get(g, f"g{g}"), "frames": len(frames),
                     "inRetarget": any(int(s[0][1:3]) == g for s in us.segments),
                     "holds": holds, "events": evs, "peakBodyLumaRise": glow,
                     "perFrameFxPx": [r["fxPx"] for r in rows]}
        sheet_rows.append((g, frames, masks, [D.colour_class(a[..., :3]) for a in frames]))
    # groups the retarget did not build have no bones: label them by analogy with a measured breath
    breath = {e["class"] for gd in groups.values() for e in gd["events"] if e["kind"].startswith("breath")}
    for g, gd in groups.items():
        if gd["inRetarget"]:
            continue
        for e in gd["events"]:
            if e["class"] in breath and g in (11, 13, 14, 16, 17, 18, 19) and e["peakPx"] >= 5 * thr and not e.get("posePaintSuspect"):
                e["kind"] = f"breath/spit ({CLASS_KIND[e['class']]}; by analogy with a measured breath clip)"
    return {"threshPx": thr, "idleBodyPx": idle_body, "groups": groups}, sheet_rows


def region_label(pt, bb):
    x0, y0, x1, y1 = bb
    u = (pt[0] - x0) / max(1, x1 - x0)
    v = (pt[1] - y0) / max(1, y1 - y0)
    vert = "top" if v < 0.3 else ("mid" if v < 0.7 else "low")
    horiz = "front" if u > 0.66 else ("back" if u < 0.33 else "centre")
    if u > 1.05:
        horiz = "ahead"
    if v < -0.05:
        vert = "above"
    return f"{vert}-{horiz}"


def draw_sheet(unit, rows, path):
    tiles = []
    for g, frames, masks, clss in rows:
        if not any(m.any() for m in masks):
            continue
        tiles.append((g, frames, masks, clss))
    if not tiles:
        return False
    allop = np.zeros_like(tiles[0][1][0][..., 3], bool)
    for _, frames, _, _ in tiles:
        for a in frames:
            allop |= a[..., 3] > 0
    ys, xs = np.nonzero(allop)
    x0, y0, x1, y1 = max(0, xs.min() - 4), max(0, ys.min() - 4), xs.max() + 5, ys.max() + 5
    cw, ch = x1 - x0, y1 - y0
    cols = max(len(t[1]) for t in tiles)
    im = Image.new("RGB", (cols * cw + 40, len(tiles) * (ch + 2) + 14), (24, 24, 24))
    dr = ImageDraw.Draw(im)
    dr.text((2, 1), f"{unit}: effect pixels (colour = class) over dimmed body", fill=(230, 230, 230))
    for r, (g, frames, masks, clss) in enumerate(tiles):
        y = 14 + r * (ch + 2)
        dr.text((2, y + 2), f"g{g:02d}", fill=(220, 220, 220))
        for i, (a, m, c) in enumerate(zip(frames, masks, clss)):
            rgb = a[..., :3].astype(np.float32) * 0.35
            bg = np.full_like(rgb, 40)
            op = a[..., 3] == 255
            out = np.where(op[..., None], rgb, bg)
            for k, name in enumerate(("detached",) + D.EFFECT_CLASSES):
                out[m & (c == k)] = PALETTE[name]
            im.paste(Image.fromarray(out[y0:y1, x0:x1].astype(np.uint8)), (40 + i * cw, y))
    im.save(path)
    return True


def tier_of(rec) -> tuple[str, float]:
    ise = rec.get("idleSelfEffect", {}).get("classes", {})
    animated = [c for c, v in ise.items() if v["animated"] and v["bodyShare"] >= 0.05]
    evs = [(g, e) for g, gd in rec["groups"].items() for e in gd["events"] if not e.get("posePaintSuspect")]
    score = sum(e["peakShareOfBody"] * len(e["frames"]) for _, e in evs)
    fam = lambda g: {11: "attack", 12: "attack", 13: "attack", 14: "shoot", 15: "shoot", 16: "shoot",
                     17: "cast", 18: "cast", 19: "cast"}.get(int(g), str(g))
    clips_with = {fam(g) for g, e in evs if e["peakShareOfBody"] >= 0.03}
    big = any(e["peakShareOfBody"] >= 0.12 and e["class"] != "detached" and not e["kind"].startswith("on-body") for _, e in evs)
    non_attack = {g for g in clips_with if g not in ("attack", "shoot", "cast")}
    score += 2.0 * sum(ise[c]["bodyShare"] for c in animated)
    if animated or big or len(clips_with) >= 3 or (non_attack and len(clips_with) >= 2):
        return "effect_heavy", round(score, 3)
    if evs:
        return "attack_accents", round(score, 3)
    return "none", round(score, 3)


def one_unit(u, fmap, proj, no_bones=False, no_sheets=False):
    """Measure one unit; returns (unit, record).  Errors are recorded, not raised."""
    try:
        us = D.load_unit(u)
        bones, bone_err = None, None
        if not no_bones:
            try:
                bones = D.BoneProjector(u)
            except Exception as e:  # noqa: BLE001 - recorded, not hidden
                bone_err = f"{type(e).__name__}: {e}"
        rec, rows = analyse(us, bones)
        rec = {"def": us.def_name, "defSource": os.path.dirname(us.groups[2][0]) if 2 in us.groups else None,
               "factions": [{"faction": f, "tier": t, "variant": v, "name": n} for f, t, v, n in fmap.get(u, [])],
               "excluded": EXCLUDED.get(u), "retargetClips": sorted({s[0] for s in us.segments}), **rec}
        if bone_err:
            rec["boneError"] = bone_err
        rec["idleSelfEffect"] = idle_self_effect(us)
        tr = [D.translucency(x) for x in us.group_rgba(2)]
        rec["translucency"] = {"ditherMax": max((t["dither"] for t in tr), default=0),
                               "semiOnBodyMax": max((t["semiOnBody"] for t in tr), default=0)}
        rec["translucency"]["ghostly"] = bool(rec["translucency"]["ditherMax"] >= 0.04 or rec["translucency"]["semiOnBodyMax"] >= 0.08)
        shoots = [g for g in (14, 15, 16) if g in us.groups]
        rec["shooter"] = bool(shoots)
        if shoots:
            alias = re.sub(r"^(hota_[a-z]+|toa|temple)_", "h3_", u)
            p = proj.get(u) or proj.get(alias)
            rec["projectile"] = {"shootGroups": shoots, "overlayNativeSubstitute": p,
                                 "lookedUp": sorted({u, alias}),
                                 "status": "native substitute mapped by overlay SID" if p else "no overlay mapping under this unit id"}
        rec["tier"], rec["score"] = tier_of(rec)
        if not no_sheets and draw_sheet(u, rows, os.path.join(OUT, "sheets", f"{u}.png")):
            rec["sheet"] = f"artifacts/homm3_vfx_experiments/_roster/sheets/{u}.png"
        return u, json.loads(json.dumps(rec, default=int))
    except Exception as e:  # noqa: BLE001
        return u, {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units", nargs="*")
    ap.add_argument("--no-sheets", action="store_true")
    ap.add_argument("--no-bones", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    os.makedirs(os.path.join(OUT, "sheets"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "factions"), exist_ok=True)
    # roster units only: the frames.json must carry the folder's own name (OUT_TAG experiment folders do not)
    units = a.units or sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(D.ART, "*", "*_def_retarget.blend.frames.json"))
                              if os.path.basename(p) == os.path.basename(os.path.dirname(p)) + "_def_retarget.blend.frames.json")
    fmap = faction_map()
    proj = projectile_specs()
    inv_path = os.path.join(OUT, "inventory.json")
    inv = json.load(open(inv_path)) if (a.units and os.path.exists(inv_path)) else {"units": {}}
    from concurrent.futures import ProcessPoolExecutor, as_completed
    with ProcessPoolExecutor(max_workers=max(1, a.workers)) as ex:
        futs = [ex.submit(one_unit, u, fmap, proj, a.no_bones, a.no_sheets) for u in units]
        for k, f in enumerate(as_completed(futs)):
            u, rec = f.result()
            inv["units"][u] = rec
            print(f"[{k + 1}/{len(units)}] {u:36s} " + (f"{rec['def']:10s} {rec['tier']:15s} {rec['score']}" if "error" not in rec else "ERROR " + rec["error"]), flush=True)
    inv["units"] = dict(sorted(inv["units"].items()))
    inv["schema"] = "homm3_vfx_roster_inventory.v1"
    inv["proof"] = "generated artifact: measured from the extracted DEF PNGs the def_retarget consumed; not rendered, not in game"
    json.dump(inv, open(inv_path + ".tmp", "w"), indent=1, default=int)
    os.replace(inv_path + ".tmp", inv_path)
    import roster_vfx_summary
    roster_vfx_summary.write(inv, OUT)


if __name__ == "__main__":
    main()