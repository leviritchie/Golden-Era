"""Stronghold quadruped: hang the procedural wolf/boar/horse body from Hips so a whole-body turn carries it.

stronghold_quadruped builds its body chain (WolfBody, and through it the neck, head, tail and legs) under Root.
castle_yaw turns every posed bone about the origin for the DEF fit, and deyaw_glb takes that turn back out of the
delivered GLB by counter-rotating the Hips keys only, so every turned bone must descend from Hips. With the body
under Root the delivered GLB would keep the fit's turn on the mount while the rider faces +Z. This extension
re-parents the body chain's root bones from Root to Hips (as castle_mount does for the horse chains).

List it after stronghold_quadruped and before castle_yaw:
  "extensions": [..., "stronghold_quadruped", "stronghold_quadruped_hips_parent", "castle_yaw"]
Hooks:
  after_skin  edit-bone parent of each Root-parented body bone -> Hips (the exported rest hierarchy)
  after_pose  parent_of again, because stronghold_quadruped.after_pose rewrites it from its config
World poses are untouched; every body bone is a free (location-keyed) bone, so local keys follow the new parent.
Refuses (fail closed): a unit without the "quadruped" config, or no Root-parented body bone to move.
Proof tier: source; generated artifact once a unit is rebuilt with it.
"""


def _roots(g):
    q = g["cfg"].get("quadruped")
    if not q:
        raise SystemExit("stronghold_quadruped_hips_parent: unit has no 'quadruped' config")
    roots = [n for n, v in q["bones"].items() if v[2] == "Root"]
    if not roots:
        raise SystemExit("stronghold_quadruped_hips_parent: no quadruped bone is parented to Root")
    return roots


def after_skin(g):
    bpy, rig = g["bpy"], g["rig"]
    roots = _roots(g)
    prev = bpy.context.view_layer.objects.active
    mode = prev.mode if prev else 'OBJECT'
    if prev and mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for n in roots:
        eb[n].parent = eb["Hips"]
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = prev
    for n in roots:
        g["parent_of"][n] = "Hips"
    print("QUADRUPED body parented to Hips:", roots)


def after_pose(g):
    roots = _roots(g)
    for n in roots:
        if g["rig"].data.bones[n].parent.name != "Hips":
            raise SystemExit(f"stronghold_quadruped_hips_parent: {n} is not parented to Hips in the rig")
        g["parent_of"][n] = "Hips"
