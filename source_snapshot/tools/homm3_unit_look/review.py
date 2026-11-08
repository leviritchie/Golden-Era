"""Review stage (CPU, the default): the unit's look with its effects on, against the DEF.

Per review view (sprite camera, DEF frame): DEF | raw Meshy base colour | look | look + VFX, all under
the Hex/Lit relight (arena sun + ambient; look + VFX adds the dynamic point lights of that key and
composites the flipbook cells at their projected anchors). Metrics compare body-only (look vs the DEF
body with effect pixels removed) and with effects (look + VFX vs the whole DEF frame).
Proof tier: generated artifact (numpy relight of Blender passes + 2D effect composite).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import prebake_lab as pl
import vfx as vx

BATTLE = ["battle_faces_right", "battle_faces_left", "battle_faces_camera", "battle_faces_away"]
SINK_SPREAD_PX = 3.0  # every bone head within this many px of the others: the rig is scaled to ~0 (a "sink")


class ReviewError(Exception):
    pass


def bones_collapsed(vmv) -> bool:
    """The retarget scaled the rig to ~0 on this key (e.g. Hips 0.001 at the end of Death / MoveStart)."""
    px = np.array([b["headPx"] for b in vmv.get("bones", {}).values() if b.get("headPx") is not None], float)
    return len(px) > 0 and float(np.ptp(px, axis=0).max()) <= SINK_SPREAD_PX


def stats(rgb_lin, mask, ref_lab_L):
    lab = pl.lin_to_lab(rgb_lin)
    s = pl.image_stats(pl.lin_to_srgb(rgb_lin), mask)
    return {"Lp5_50_95": [s["Lpercentiles_5_25_50_75_95"][i] for i in (0, 2, 4)],
            "hueSpreadDeg": s["hueSpreadDeg"], "localContrast": s["localContrast"],
            "chromaP10_50_90": s["chromaP10_50_90"],
            "LhistDistanceToDEF": round(pl.hist_distance(lab[..., 0][mask], ref_lab_L), 2)}


def frame_for_view(ctx, vn):
    """(clip, key index) that owns this master frame, if a clip keys it."""
    t = ctx["vmeta"]["views"][vn]["frame"] - 1
    for clip, c in ctx["clips"].items():
        if t in c["masterFrames"]:
            return clip, c["masterFrames"].index(t)
    return None, None


def atlas_tex(manifest, vres, clip, ki):
    """The uvAtlas cell texture shown on this key (None when no atlas layer keys the clip)."""
    for lid, L in manifest["layers"].items():
        if L.get("type") == "uvAtlas" and clip in L.get("clips", {}) and ki < len(L["clips"][clip]):
            return vres["atlasCells"][lid][L["clips"][clip][ki]["cell"]].astype(np.float32), lid
    return None, None


def mesh_hidden(manifest, ctx, clip, ki):
    """True when a hideMesh (all renderers) is in force on this key; a renderer subset is noted, not drawn."""
    if clip is None:
        return False, None
    keys = [f for _, f in ctx["clips"][clip]["defFrames"]]
    state, note = False, None
    evs = []
    for L in manifest["layers"].values():
        if L.get("type") == "event" and L.get("clip") == clip and L.get("action") in ("hideMesh", "showMesh")                 and L.get("defFrame") in keys:
            evs.append((keys.index(L["defFrame"]), L))
    for k, L in sorted(evs, key=lambda x: x[0]):
        if k > ki:
            break
        if L.get("renderers"):
            note = f"{L['action']} {L['renderers']} (subset: not drawn in the CPU review)"
            continue
        state = L["action"] == "hideMesh"
    return state, note


def run(spec, ctx, outd: Path, tex_lin, vfx_res) -> dict:
    cond = ctx["cond"]
    raw = ctx["maps"]["albedo"]
    manifest = vfx_res["manifest"] if vfx_res else {"layers": {}}
    vdir = outd / "vfx"
    cache = {}
    rows, per, warnings = [], {}, []
    for vn in ctx["reviewViews"]:
        view = ctx["views"][vn]
        vmv = ctx["vmeta"]["views"][vn]
        rec = ctx["def"][vn]
        clip, ki = frame_for_view(ctx, vn)
        def_lab = pl.lin_to_lab(pl.srgb_to_lin(rec["rgba"][..., :3]))
        col_raw, a = vx.lit_render(raw, view, vmv, cond)
        cell_tex, atlas_id = atlas_tex(manifest, vfx_res, clip, ki) if clip else (None, None)
        look_tex = cell_tex if cell_tex is not None else tex_lin
        hidden, hide_note = mesh_hidden(manifest, ctx, clip, ki)
        # dynamic lights of this key
        extra = None
        lights_on = []
        for lid, L in manifest["layers"].items():
            if L.get("type") != "effectLight" or clip not in L.get("clips", {}):
                continue
            row = L["clips"][clip][ki]
            if row["intensity"] > 0 and row.get("positionWorld") is not None:
                term = vx.point_term(view, np.array(row["positionWorld"]), pl.srgb_to_lin(np.array(L["rgb"], np.float32)),
                                     row["intensity"], L["range"])
                extra = term if extra is None else extra + term
                lights_on.append(f"{lid}={row['intensity']:.2f}")
        col_fx, _ = vx.lit_render(look_tex, view, vmv, cond, extra)
        col_look = col_fx          # "look" = prebaked base colour (or this key's atlas cell) + dynamic lights, no flipbook
        a_fx = np.zeros_like(a) if hidden else a
        srgb_fx = pl.lin_to_srgb(col_fx) * a_fx[..., None]
        cov_fx = np.zeros(a.shape, bool)
        for lid, L in manifest["layers"].items():
            if L.get("type") != "defFlipbook" or clip not in L.get("clips", {}):
                continue
            fb = L["clips"][clip]
            if fb.get("render") in ("unitPlane", "trail"):      # opt-in depth-aware parts (vfx_depth.py)
                import vfx_depth
                for part in vfx_depth.review_parts(fb, ki, vmv, srgb_fx.shape[:2], vdir, cache, ctx):
                    srgb_fx, cov_fx = vfx_depth.over(srgb_fx, cov_fx, part)
            if not fb.get("sheet"):
                continue
            bone = vmv["bones"][fb["anchorBone"]]
            anc = bone["tailPx"] if fb.get("anchorPoint") == "tail" else bone["headPx"]
            srgb_fx, cov = vx.paste_cells(srgb_fx, fb, fb["keys"][ki], anc, vdir, cache)
            cov_fx |= cov
        mesh = a > 0.9
        mesh_fx = a_fx > 0.9
        body_ref = def_lab[..., 0][rec["bodyNoFx"]]
        full_ref = def_lab[..., 0][rec["body"]]
        fx_mask = mesh_fx | cov_fx
        fx_lin = pl.srgb_to_lin(np.clip(srgb_fx, 0, 1))
        # Explicit empty states, never a silent skip: the mesh can legitimately be gone on a key (the retarget's
        # sink scales the rig to ~0, or hideMesh) and the DEF body can be all effect (hideMesh + DEF remains).
        mesh_empty, body_empty = not mesh.any(), body_ref.size == 0
        rv = {"clip": clip, "key": ki, "defSource": Path(rec["src"]).name, "lightsOn": lights_on,
              "atlas": atlas_id, "meshHidden": hidden, **({"hideNote": hide_note} if hide_note else {}),
              "def": stats(pl.srgb_to_lin(rec["rgba"][..., :3]), rec["body"], full_ref) if full_ref.size else None,
              "effectPixels": {"def": int(rec["fx"].sum()), "composite": int(cov_fx.sum())}}
        if mesh_empty:
            rv["meshEmpty"] = True
            rv["meshEmptyCause"] = "hideMesh" if hidden else "rigCollapsed" if bones_collapsed(vmv) else "unexplained"
            if rv["meshEmptyCause"] == "unexplained":
                warnings.append(f"{vn}: the mesh renders empty with no hideMesh event and no collapsed rig (suspicious)")
        if body_empty:
            rv["bodyEmpty"] = True
        if mesh_empty or body_empty:
            rv["raw"] = rv["look"] = None
            rv["excludedFromBody"] = [r for r, f in (("meshEmpty", mesh_empty), ("bodyEmpty", body_empty)) if f]
        else:
            rv["raw"], rv["look"] = stats(col_raw, mesh, body_ref), stats(col_look, mesh, body_ref)
        if fx_mask.any() and full_ref.size:
            rv["lookWithEffects"] = stats(fx_lin, fx_mask, full_ref)
        else:
            rv["lookWithEffects"] = None
            rv["effectsEmpty"] = [r for r, f in (("noMeshNoEffectPixels", not fx_mask.any()),
                                                 ("defFrameEmpty", not full_ref.size)) if f]
        per[vn] = rv
        rows.append((vn, rec, [(pl.lin_to_srgb(col_raw), a, "raw"), (pl.lin_to_srgb(col_look), a, "look+light" if lights_on else "look"),
                               (srgb_fx / np.maximum(np.maximum(a_fx, cov_fx)[..., None], 1e-6),
                                np.maximum(a_fx, cov_fx.astype(np.float32)), "look+VFX" + (" " + ",".join(lights_on) if lights_on else ""))]))
    # yaw spread on the battle facings
    yaw = {}
    for c in ("sand", "grass"):
        if all(b in ctx["views"] for b in BATTLE) and all(f"sun_{c}" in ctx["views"][b] for b in BATTLE):
            means = {}
            for b in BATTLE:
                col, al = vx.lit_render(tex_lin, ctx["views"][b], ctx["vmeta"]["views"][b], c)
                means[b] = round(float(pl.lin_to_lab(col)[..., 0][al > 0.9].mean()), 1)
            yaw[c] = {"meanL": means, "facingSpreadL": round(max(means.values()) - min(means.values()), 1)}
    sheet(outd / "review_sheet.png", rows, spec["unit"])
    summary = summarise(per, yaw, warnings)
    sheet(outd / "review_worst_row.png", [r for r in rows if r[0] == summary["worstView"]], spec["unit"], scale=1)
    return {"summary": summary, "views": per, "battle": yaw}


def summarise(per: dict, yaw: dict, warnings: list) -> dict:
    """Means over the keys that have the metric; keys excluded for an empty mesh / DEF body are listed, and a
    unit where EVERY key is excluded fails closed (no body metric at all is a real fault)."""
    body = {k: v for k, v in per.items() if v["look"] is not None}
    withfx = {k: v for k, v in per.items() if v["lookWithEffects"] is not None}
    if not body:
        raise ReviewError("every review key has an empty mesh or DEF body reference "
                          f"({ {k: v['excludedFromBody'] for k, v in per.items()} }); no body metric exists, "
                          "which is a real fault (framing, rig or segmentation)")
    if not withfx:
        raise ReviewError("no review key has any mesh or effect pixels to compare with the DEF")
    summary = {
        "meanLhistBodyLook": round(float(np.mean([r["look"]["LhistDistanceToDEF"] for r in body.values()])), 2),
        "meanLhistBodyRaw": round(float(np.mean([r["raw"]["LhistDistanceToDEF"] for r in body.values()])), 2),
        "meanLhistWithEffects": round(float(np.mean([r["lookWithEffects"]["LhistDistanceToDEF"] for r in withfx.values()])), 2),
        "worstView": max(withfx, key=lambda k: withfx[k]["lookWithEffects"]["LhistDistanceToDEF"]),
        "yawSpreadL": {c: v["facingSpreadL"] for c, v in yaw.items()},
        "bodyViews": len(body), "reviewViews": len(per),
    }
    excluded = {k: v["excludedFromBody"] for k, v in per.items() if v["look"] is None}
    if excluded:
        summary["excludedFromBody"] = excluded
    nofx = {k: v["effectsEmpty"] for k, v in per.items() if v["lookWithEffects"] is None}
    if nofx:
        summary["excludedFromEffects"] = nofx
    if warnings:
        summary["warnings"] = warnings
    return summary


def sheet(path: Path, rows, unit, scale=2, bg=(46, 46, 46)):
    cells_all = []
    for vn, rec, cells in rows:
        cl = [(rec["rgba"][..., :3], rec["rgba"][..., 3] * rec["body"], f"DEF {Path(rec['src']).stem}")] + cells
        cells_all.append((vn, cl))
    union = np.zeros(rows[0][1]["rgba"].shape[:2], bool)
    for _, cl in cells_all:
        for _, a, _ in cl:
            union |= a > 0.05
    ys, xs = np.nonzero(union)
    x0, y0, x1, y1 = max(0, xs.min() - 6), max(0, ys.min() - 6), xs.max() + 7, ys.max() + 7
    cw, ch = (x1 - x0) * scale, (y1 - y0) * scale
    ncol = max(len(cl) for _, cl in cells_all)
    img = Image.new("RGB", (ncol * cw, len(cells_all) * (ch + 14) + 16), bg)
    d = ImageDraw.Draw(img)
    d.text((4, 2), f"{unit}: DEF | raw | look | look+VFX  (Hex/Lit relight, sprite camera; generated artifact)", fill=(230, 230, 230))
    for r, (vn, cl) in enumerate(cells_all):
        for c, (rgb, a, lab) in enumerate(cl):
            im = np.clip(rgb[y0:y1, x0:x1], 0, 1) * a[y0:y1, x0:x1, None] + np.array(bg) / 255 * (1 - a[y0:y1, x0:x1, None])
            tile = Image.fromarray((im * 255 + 0.5).astype(np.uint8)).resize((cw, ch), Image.NEAREST)
            yy = 16 + r * (ch + 14)
            img.paste(tile, (c * cw, yy + 14))
            d.text((c * cw + 3, yy + 1), f"{vn[7:]} {lab}"[:max(8, cw // 6)], fill=(220, 220, 220))
    img.save(path)
