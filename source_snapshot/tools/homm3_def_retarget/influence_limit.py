"""The glTF exporter's skin-influence limit, applied to the .blend before bake_cs.py so the bake skins what ships.

Blender 5.2's glTF exporter (io_scene_gltf2 blender/exp/primitive_extract.py __get_bone_data and
primitive_attributes.py, export_glb.py's default 4 influences) takes per vertex the groups named after a skin joint
with weight > 1e-4, stable-sorts them by weight (descending, ties in v.groups order), keeps the first 4 and
normalises them. build_unit.py limits the bone-heat weights to 4 (vertex_group_limit_total), but after_skin hooks
that write weights later (rampart_pegasus, wing_chain, rampart_quadruped, ...) can leave 5+. bake_cs.py baked those
with every group while the GLB ships 4: h3_pegasus vertices 6984 / 7520 / 14069 / 14071 kept a 0.016-0.058 shoulder
or arm weight in the bake and lost it in the export, a 0.006-0.018 H patch-lane parity residual (2026-10-09).

limit() is a no-op (returns None) for a vertex with 4 or fewer such influences, so it leaves those vertices'
groups byte-identical. Pure Python: bake_cs.py calls it inside Blender, test_influence_limit.py offline.
Proof tier: source/static (unit tests); the pegasus rebuild proves it on the export.
"""
from __future__ import annotations

LIMIT = 4                 # export_glb.py exports the glTF default: one joint set (export_influence_nb 4)
MIN_INFLUENCE = 0.0001    # the exporter skips groups with weight <= this


def limit(groups, joints, n: int = LIMIT, min_influence: float = MIN_INFLUENCE):
    """groups: [(group name, weight)] in the vertex's v.groups order; joints: the skin's joint (bone) names.
    None when the exporter keeps every influence (<= n). Otherwise (kept, dropped): kept = [(name, weight
    normalised over the kept)] in the exporter's order, dropped = the other joint-named group names of the vertex
    (including those at or below min_influence). Groups not named after a joint are never touched."""
    js = set(joints)
    inf = [(nm, w) for nm, w in groups if nm in js and w > min_influence]
    if len(inf) <= n:
        return None
    inf.sort(key=lambda x: x[1], reverse=True)      # stable, like the exporter's list.sort
    keep = inf[:n]
    tot = sum(w for _, w in keep)
    kept_names = {nm for nm, _ in keep}
    dropped = [nm for nm, _ in groups if nm in js and nm not in kept_names]
    return [(nm, w / tot) for nm, w in keep], dropped


def apply_to_mesh(ob, joints, n: int = LIMIT) -> int:
    """Limit ob's vertex groups (bpy mesh object) in place; returns the number of vertices changed."""
    gname = {g.index: g.name for g in ob.vertex_groups}
    edits = []
    for v in ob.data.vertices:
        r = limit([(gname[g.group], g.weight) for g in v.groups], joints, n)
        if r is not None:
            edits.append((v.index, r))
    vg = ob.vertex_groups
    for vi, (kept, dropped) in edits:
        for nm in dropped:
            vg[nm].remove([vi])
        for nm, w in kept:
            vg[nm].add([vi], w, 'REPLACE')
    return len(edits)
