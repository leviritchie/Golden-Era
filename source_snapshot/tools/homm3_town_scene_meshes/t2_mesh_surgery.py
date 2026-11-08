#!/usr/bin/env python3
"""Per-layer Meshy T2 mesh surgery shared by the T2 town lanes (Stronghold, Cove).

A layer names rules (spec "cut"); each rule selects faces of the model in model space and the selected faces are
dropped from the placed mesh (same vertex / face order). Whole connected parts (face adjacency) are the unit of every
rule except fountainJets. A rule gets (g, lab, area, col, spec, ctx):

  g     {"v", "f", "uv" (glTF top-origin), "tex" (H x W x 3 uint8)}, model space
  ctx   optional per-layer data a rule needs from the placed layer: {"inside": per-face bool, the face's rest-camera
        centroid lies on the layer's sprite mask (dilated); "insideAll": all three corners do}

Rules (each is recorded with its dropped triangle count in the stage report):
  groundPlate   a flat part in the model's lower half spanning >= 80% of its footprint on both axes
  fountainJets  solid fountain water columns above a basin's water surface
  loneSheets    parts of one or two triangles with an edge longer than 30% of the model
  offSprite     parts with less than half of their area on the sprite at rest: geometry the painting does not show
                (a dock, beach or deck Meshy invented around the building)
  offSpriteFaces  every face with a corner off the (dilated) sprite at rest, for a part that is one piece with the
                building (a deck the building stands on): the cut edge follows the painted silhouette. Corners, not
                the centroid: a Meshy deck triangle can be 100 frame px long and its centroid on the sprite
"""
from __future__ import annotations

import numpy as np

OFF_SPRITE_MIN_INSIDE = 0.5    # offSprite: a part is kept when at least this share of its area is on the sprite
OFF_SPRITE_DILATE = 8          # frame px the sprite mask is grown before the inside test (the fit is not exact)


def _parts(g: dict):
    """Connected parts (face adjacency) of the model, per-face area and Meshy texel colour (sRGB 0-255)."""
    import trimesh
    v, f = g["v"], g["f"]
    m = trimesh.Trimesh(v, f, process=False)
    lab = trimesh.graph.connected_component_labels(m.face_adjacency, node_count=len(f))
    tex = g["tex"]
    th, tw = tex.shape[:2]
    uc = g["uv"][f].mean(1)          # glTF top-origin (load_glb)
    col = tex[np.clip((uc[:, 1] * th).astype(int), 0, th - 1), np.clip((uc[:, 0] * tw).astype(int), 0, tw - 1)]
    return lab, m.area_faces, col.astype(np.float64)


def rule_ground_plate(g, lab, area, col, spec, ctx):
    """A flat part in the model's lower half spanning >= 80% of its footprint on both axes: the ground sheet Meshy puts
    under a building (the painting's own terrain is there; at the sweeps it read as a pale slab). Flat is 3% of the
    model's height, or of a fifth of its largest extent for a low, wide model (the Cove tavern's deck)."""
    v, f = g["v"], g["f"]
    lo, hi = v.min(0), v.max(0)
    ext = hi - lo
    drop = np.zeros(len(f), bool)
    for k in np.unique(lab):
        s = lab == k
        q = v[f[s]].reshape(-1, 3)
        e = q.max(0) - q.min(0)
        if (e[1] < 0.03 * max(ext[1], 0.2 * ext.max()) and q[:, 1].max() < lo[1] + 0.5 * ext[1]
                and e[0] > 0.8 * ext[0] and e[2] > 0.8 * ext[2]):
            drop |= s
    return drop


def rule_fountain_jets(g, lab, area, col, spec, ctx):
    """Solid fountain jets: Meshy modelled each fountain's water column as a solid (white domes / spikes, grey
    cylinders). The water is the seed's Fx_Basin effect, so every face above a basin's water surface, within the
    basin's radius, is dropped. Water surfaces are the flat, blue parts (>= 0.3% of the area); a layer whose basins
    are not blue names them in spec "basins" ([x, z, r, water y] in model space, read off its parts)."""
    v, f = g["v"], g["f"]
    ext = v.max(0) - v.min(0)
    c = v[f].mean(1)
    drop = np.zeros(len(f), bool)
    for bx, bz, r, wy in spec.get("basins") or []:
        drop |= (np.hypot(c[:, 0] - bx, c[:, 2] - bz) < r) & (c[:, 1] > wy + 0.01 * ext[1])
    if spec.get("basins"):
        return drop
    tot = area.sum()
    for k in np.unique(lab):
        s = lab == k
        if area[s].sum() < 0.003 * tot:
            continue
        q = v[f[s]].reshape(-1, 3)
        e = q.max(0) - q.min(0)
        mc = (col[s] * area[s, None]).sum(0) / area[s].sum()
        if e[1] > 0.02 * ext[1] or mc[2] < mc[0] + 25:
            continue
        ctr = (q.min(0) + q.max(0)) / 2
        r = 0.85 * 0.5 * max(e[0], e[2])   # inside the water edge: the basin rim above the water stays
        near = np.hypot(c[:, 0] - ctr[0], c[:, 2] - ctr[2]) < r
        drop |= near & (c[:, 1] > q[:, 1].max() + 0.01 * ext[1])
    return drop


def rule_lone_sheets(g, lab, area, col, spec, ctx):
    """Parts of one or two triangles with an edge longer than 30% of the model: a stray cloth sheet (the market's
    awning wedge), not a modelled surface."""
    v, f = g["v"], g["f"]
    ext = float((v.max(0) - v.min(0)).max())
    e = np.linalg.norm(v[f] - v[np.roll(f, 1, 1)], axis=-1).max(1)
    cnt = np.bincount(lab)
    return (cnt[lab] <= 2) & (e > 0.3 * ext)


def rule_off_sprite(g, lab, area, col, spec, ctx):
    """Parts with less than OFF_SPRITE_MIN_INSIDE of their area on the (dilated) sprite at rest (ctx "inside")."""
    ins = np.asarray(ctx["inside"], bool)
    at = np.bincount(lab, area)
    ain = np.bincount(lab, area * ins, minlength=len(at))
    share = ain / np.maximum(at, 1e-12)
    return share[lab] < OFF_SPRITE_MIN_INSIDE


def rule_off_sprite_faces(g, lab, area, col, spec, ctx):
    """Faces with a corner off the (dilated) sprite at rest (ctx "insideAll"), whatever part they belong to."""
    return ~np.asarray(ctx["insideAll"], bool)


PARTS_RULES = {"groundPlate": rule_ground_plate, "fountainJets": rule_fountain_jets, "loneSheets": rule_lone_sheets,
               "offSprite": rule_off_sprite, "offSpriteFaces": rule_off_sprite_faces}


def cut_parts(P, N, uv, F, g: dict, spec: dict, ctx: dict | None = None):
    """Per-layer mesh surgery from review (spec "cut": PARTS_RULES names). Faces are selected in model space (g),
    then dropped from the placed mesh (same vertex order). Each rule's count is recorded."""
    rules = spec.get("cut") or []
    if not rules:
        return P, N, uv, F, None
    lab, area, col = _parts(g)
    drop = np.zeros(len(F), bool)
    rep = []
    for r in rules:
        sel = PARTS_RULES[r](g, lab, area, col, spec, ctx or {})
        rep.append({"rule": r, "droppedTris": int((sel & ~drop).sum())})
        drop |= sel
    keep = ~drop
    used = np.unique(F[keep])
    remap = np.full(len(P), -1, np.int64)
    remap[used] = np.arange(len(used))
    return P[used], N[used], uv[used], remap[F[keep]], rep
