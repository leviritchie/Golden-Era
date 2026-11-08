"""See-through pixels: building pixels the game drops because it culls back faces.

In game every Mesh_ piece is rebound to a clone of the city's Hex/Lit donor with `_CullMode` pinned to Back
(Homm3TownScene3d.RebindLitPieceOrThrow). A relief / solid depth step wound toward the rest camera shows its back to a
panned or orbited camera; with culling the step vanishes and whatever lies behind it (sky, terrain, a far building)
shows through a slit. This metric renders the full state's piece ids twice per pose - no culling and Unity back-face
culling - and counts the building (Mesh_Body_) pixels whose winner changes.

Handedness: Unity's front face is GL's back face in these moderngl renders (the lane builds meshes in Unity's frame),
so Unity `Cull Back` is GL `cull_face = "front"` here. Verified on the Cove hall step faces (2026-09-29).

Offline, generated-artifact metric only: it says what Cull Back does to these meshes at these poses, not what the
game draws (no lighting, no effects' blend state, no runtime camera beyond the proof poses).

The gate is no-worse-than-baseline per pose against town_full3d_cull_baseline.json (the installed candidates'
values, measured by `stronghold_full3d_scene.py cull`). A faction without a baseline row is report-only."""
from __future__ import annotations

import collections
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BASELINE = HERE / "town_full3d_cull_baseline.json"
BODY = "Mesh_Body_"

_FS = """
#version 330
uniform int pid; in vec3 v_n; in vec2 v_uv; out vec4 o;
void main(){ o = vec4(float(pid), v_uv.x * 1e-9 + v_n.x * 1e-9, 0, 1); }
"""


def see_through(pieces, cams: dict, w: int, h: int, near: float, far: float) -> dict:
    """pieces: (name, P, n, uv, tris) in the painting world; cams: {pose: cam dict}. Returns
    {pose: {"seeThroughPx": int, "top": [[piece, px], ...]}}."""
    import moderngl
    import stronghold_full3d_preview as PV
    ctx = moderngl.create_standalone_context()
    try:
        prog = ctx.program(vertex_shader=PV.VS, fragment_shader=_FS)
        fbo = ctx.simple_framebuffer((w, h), components=4, dtype="f4")
        vaos, names = [], ["-"]
        for name, P, n, uv, tris in pieces:
            vb = np.concatenate([np.asarray(P, np.float32), np.asarray(n, np.float32), np.asarray(uv, np.float32)], 1)
            vaos.append(ctx.vertex_array(prog, [(ctx.buffer(vb.tobytes()), "3f 3f 2f", "in_pos", "in_nrm", "in_uv")],
                                         ctx.buffer(np.asarray(tris, np.int32).tobytes())))
            names.append(name.split("/")[-1])
        body = np.array([False] + [BODY in nm for nm in names[1:]])

        def ids(cam, cull):
            mvp = PV.perspective(cam["fov"], w / h, near, far) @ PV.view(cam["pos"], cam["fwd"], cam["up"],
                                                                          cam["right"])
            fbo.use()
            ctx.clear(0, 0, 0, 0)
            ctx.enable(moderngl.DEPTH_TEST)
            if cull:
                ctx.enable(moderngl.CULL_FACE)
                ctx.cull_face = "front"     # = Unity Cull Back (handedness, module doc)
            else:
                ctx.disable(moderngl.CULL_FACE)
            prog["mvp"].write(mvp.T.astype(np.float32).tobytes())
            for i, vao in enumerate(vaos):
                prog["pid"].value = i + 1
                vao.render()
            return np.frombuffer(fbo.read(components=4, dtype="f4"), np.float32).reshape(h, w, 4)[::-1, :, 0].astype(int)

        out = {}
        for pose, cam in cams.items():
            lab, game = ids(cam, False), ids(cam, True)
            lost = body[lab] & (game != lab)
            per = collections.Counter(names[k].replace(BODY, "") for k in lab[lost])
            out[pose] = {"seeThroughPx": int(lost.sum()), "top": [list(t) for t in per.most_common(5)]}
        return out
    finally:
        ctx.release()


def baseline_row(faction: str) -> dict | None:
    if not BASELINE.is_file():
        return None
    return json.loads(BASELINE.read_text(encoding="utf-8")).get("factions", {}).get(faction)


def gate(faction: str, measured: dict) -> dict:
    """No-worse-than-baseline per pose. Returns {"mode", "baseline", "worse": {pose: [baseline, measured]}}; a pose
    the baseline has and the measurement lacks (or the reverse) is a failure, not a skip."""
    row = baseline_row(faction)
    if row is None:
        return {"mode": "report-only (no baseline row)", "baseline": None, "worse": {}}
    base = row["poses"]
    if set(base) != set(measured):
        raise SystemExit(f"see-through gate: pose set differs from the baseline ({sorted(set(base) ^ set(measured))})")
    worse = {p: [base[p], measured[p]["seeThroughPx"]] for p in base if measured[p]["seeThroughPx"] > base[p]}
    return {"mode": "no-worse-than-baseline", "baseline": row["candidate"], "worse": worse}
