"""Factory/Bulwark hook: map a quadruped capture with its spine horizontal.

build_unit.py maps the capture so its idle-frame-0 spine (Hips -> Spine2) points up (+Z), which is
right for bipeds. On quadruped DEFs (armadillos, argali, mammoths) the capture's own spine lies
horizontal, its arms are the front legs and its legs the hind legs. Mapping that spine to +Z turns
the capture's "up" into the model's forward axis, so yaws become rolls and grounding (lowest point
along +Z) measures the rearmost point instead of the lowest. This after_pose hook re-maps the capture
so its spine points forward (-Y, the direction the model faces), its left (hip + shoulder line)
to +X and its up to +Z, then rebuilds every frame's pose with the unchanged retarget code.

Config: "extensions": ["factory_quadruped"] (no options). Joint layout for a quadruped: Hips at the
pelvis, Spine..Neck running forward, arms = front legs (Shoulder at the withers, Arm at the top
of the leg, ForeArm knee, Hand fetlock, Hand_End hoof), legs = hind legs.
"""
from mathutils import Matrix


def after_pose(g):
    P, ix, V = g["P"], g["ix"], g["V"]
    p0 = P[0]
    s = V(p0[ix["Spine2"]] - p0[ix["Hips"]]).normalized()
    l = V(p0[ix["LeftUpLeg"]] - p0[ix["RightUpLeg"]]) + V(p0[ix["LeftArm"]] - p0[ix["RightArm"]])
    l = (l - s * s.dot(l)).normalized()
    u = s.cross(l)
    # capture coords -> (along spine, left, up) -> world (-Y forward, +X left, +Z up)
    M = Matrix((l, -s, u))
    g["W"] = [[M @ V(P[t, j]) for j in range(P.shape[1])] for t in range(P.shape[0])]
    g["posed_world"][:] = [g["pose_frame"](t) for t in range(g["T"])]
    W = g["W"]
    fwd = (W[0][ix["Head"]] - W[0][ix["Hips"]]).normalized()
    print("QUADRUPED remap: capture head direction from hips", tuple(round(x, 2) for x in fwd))
