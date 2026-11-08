#!/usr/bin/env python3
"""Map motion parts/hinges onto the mesh surface and pose via part/hinge DOFs.

Topology-free: vertex groups named part_XX; hinges are surface anchors; DOFs are
rotations around camera-facing hinge axes (plus optional root camera-plane translate).
Does not use UniRig humanoid bone role names.

  blender -b --python blender_map_articulation_parts.py -- \\
    --job job.resolved.json --articulation articulation_report.json --out-dir DIR
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

_POSE_FIT = Path(__file__).resolve().parents[1] / "homm3_silhouette_pose_fit"
if str(_POSE_FIT) not in sys.path:
    sys.path.insert(0, str(_POSE_FIT))
from homm3_pose_camera import setup_pose_camera  # noqa: E402

PART_COLORS = [
    (1.0, 0.31, 0.31),
    (0.31, 0.78, 1.0),
    (1.0, 0.78, 0.16),
    (0.78, 0.31, 1.0),
    (0.31, 1.0, 0.47),
    (1.0, 0.55, 0.16),
    (0.55, 0.55, 1.0),
    (1.0, 0.4, 0.7),
]


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {
        "job": None,
        "articulation": None,
        "out_dir": None,
        "max_assign_px": 18.0,
        "min_assign_frac": 0.55,
        "hinge_search_px": 28.0,
        "angle_samples": 72,
    }
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--job" and i + 1 < len(args):
            out["job"] = Path(args[i + 1])
            i += 2
        elif a == "--articulation" and i + 1 < len(args):
            out["articulation"] = Path(args[i + 1])
            i += 2
        elif a == "--out-dir" and i + 1 < len(args):
            out["out_dir"] = Path(args[i + 1])
            i += 2
        elif a == "--max-assign-px" and i + 1 < len(args):
            out["max_assign_px"] = float(args[i + 1])
            i += 2
        elif a == "--min-assign-frac" and i + 1 < len(args):
            out["min_assign_frac"] = float(args[i + 1])
            i += 2
        elif a == "--hinge-search-px" and i + 1 < len(args):
            out["hinge_search_px"] = float(args[i + 1])
            i += 2
        elif a == "--angle-samples" and i + 1 < len(args):
            out["angle_samples"] = int(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["job"] or not out["articulation"] or not out["out_dir"]:
        raise SystemExit("need --job --articulation --out-dir")
    return out


def _weld(mesh_obj) -> int:
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(mesh_obj.data)
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-4)
    removed = before - len(bm.verts)
    bm.to_mesh(mesh_obj.data)
    bm.free()
    mesh_obj.data.update()
    return removed


def _setup_lights() -> None:
    key = bpy.data.lights.new(name="Key", type="SUN")
    key.energy = 2.5
    key_o = bpy.data.objects.new(name="Key", object_data=key)
    bpy.context.collection.objects.link(key_o)
    key_o.rotation_euler = Euler((math.radians(40), math.radians(15), math.radians(30)), "XYZ")
    fill = bpy.data.lights.new(name="Fill", type="SUN")
    fill.energy = 0.8
    fill_o = bpy.data.objects.new(name="Fill", object_data=fill)
    bpy.context.collection.objects.link(fill_o)
    fill_o.rotation_euler = Euler((math.radians(60), math.radians(-40), math.radians(-20)), "XYZ")


def _project_world_px(world: Vector, cam, scene, sw: float, sh: float) -> tuple[float, float, float]:
    from bpy_extras.object_utils import world_to_camera_view

    co = world_to_camera_view(scene, cam, world)
    return float(co.x) * sw, float(1.0 - co.y) * sh, float(co.z)


def _cam_axes(cam) -> tuple[Vector, Vector, Vector]:
    mw = cam.matrix_world
    right = mw.to_quaternion() @ Vector((1, 0, 0))
    up = mw.to_quaternion() @ Vector((0, 1, 0))
    forward = mw.to_quaternion() @ Vector((0, 0, -1))
    return right.normalized(), up.normalized(), forward.normalized()


def _screen_angle(cx: float, cy: float, hx: float, hy: float) -> float:
    return math.atan2(cy - hy, cx - hx)


def _blur_part_weights(part_of: np.ndarray, bind_world: np.ndarray, n_parts: int, sigma: float) -> np.ndarray:
    """Soft weights from 3D distance to each part's bind centroid (stops hard-cut rips)."""
    n = len(part_of)
    cents = np.zeros((n_parts, 3), dtype=np.float64)
    for pid in range(n_parts):
        m = part_of == pid
        if not np.any(m):
            raise RuntimeError(f"fail-closed: empty part_{pid:02d} for weight blur")
        cents[pid] = bind_world[m].mean(axis=0)
    w = np.zeros((n, n_parts), dtype=np.float64)
    inv_s = 1.0 / max(sigma, 1e-6)
    for vi in range(n):
        d = np.linalg.norm(cents - bind_world[vi], axis=1)
        logits = -d * inv_s
        logits -= logits.max()
        e = np.exp(logits)
        w[vi] = e / e.sum()
    return w


def _build_parent_tree(
    parts: list[dict],
    hinges: list[dict],
    *,
    part_vert_counts: list[int] | None = None,
) -> tuple[int, dict[int, int], dict[tuple[int, int], dict]]:
    """Root = largest mesh-assigned part (body mass). Parent links from hinge BFS."""
    n = len(parts)
    if part_vert_counts is not None and len(part_vert_counts) == n:
        root = max(range(n), key=lambda i: int(part_vert_counts[i]))
    else:
        root = max(range(n), key=lambda i: int(parts[i]["trackCount"]))
    adj: dict[int, list[tuple[int, dict]]] = {i: [] for i in range(n)}
    hinge_by_pair: dict[tuple[int, int], dict] = {}
    for h in hinges:
        a = int(h["partA"].split("_")[1])
        b = int(h["partB"].split("_")[1])
        adj[a].append((b, h))
        adj[b].append((a, h))
        hinge_by_pair[(min(a, b), max(a, b))] = h
    parent: dict[int, int] = {}
    q = [root]
    seen = {root}
    while q:
        u = q.pop(0)
        for v, _h in adj[u]:
            if v in seen:
                continue
            seen.add(v)
            parent[v] = u
            q.append(v)
    for i in range(n):
        if i != root and i not in parent:
            parent[i] = root
    return root, parent, hinge_by_pair


def _subtree(part: int, children: dict[int, list[int]]) -> list[int]:
    out = [part]
    stack = list(children.get(part, []))
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(children.get(c, []))
    return out


def _rotate_points(points: np.ndarray, hinge: Vector, axis: Vector, theta: float) -> np.ndarray:
    if abs(theta) < 1e-9:
        return points.copy()
    R = np.array(Matrix.Rotation(theta, 3, axis), dtype=np.float64)
    h = np.array([hinge.x, hinge.y, hinge.z], dtype=np.float64)
    return (points - h) @ R.T + h


def _proj_centroid_err(
    points: np.ndarray,
    cam,
    scene,
    sw: float,
    sh: float,
    target_xy: np.ndarray,
) -> float:
    if len(points) == 0:
        return 1e9
    # Subsample for speed
    step = max(1, len(points) // 80)
    acc = np.zeros(2, dtype=np.float64)
    n = 0
    for p in points[::step]:
        px, py, z = _project_world_px(Vector((float(p[0]), float(p[1]), float(p[2]))), cam, scene, sw, sh)
        if z <= 0:
            continue
        acc += (px, py)
        n += 1
    if n == 0:
        return 1e9
    c = acc / n
    return float(np.linalg.norm(c - target_xy))


def _solve_hinge_angle(
    points: np.ndarray,
    hinge: Vector,
    axis: Vector,
    cam,
    scene,
    sw: float,
    sh: float,
    target_xy: np.ndarray,
    samples: int,
) -> tuple[float, float]:
    best_th = 0.0
    best_err = _proj_centroid_err(points, cam, scene, sw, sh, target_xy)
    for i in range(samples):
        th = -math.pi + (2.0 * math.pi) * i / samples
        moved = _rotate_points(points, hinge, axis, th)
        err = _proj_centroid_err(moved, cam, scene, sw, sh, target_xy)
        if err < best_err:
            best_err = err
            best_th = th
    # Local refine
    span = (2.0 * math.pi) / samples
    for j in range(8):
        step = span / (2 ** (j + 1))
        improved = False
        for dth in (-step, step):
            th = best_th + dth
            moved = _rotate_points(points, hinge, axis, th)
            err = _proj_centroid_err(moved, cam, scene, sw, sh, target_xy)
            if err < best_err:
                best_err = err
                best_th = th
                improved = True
        if not improved and j > 2:
            break
    return float(best_th), float(best_err)


def run(opts: dict) -> dict:
    from PIL import Image, ImageDraw

    job = json.loads(Path(opts["job"]).read_text(encoding="utf-8"))
    art = json.loads(Path(opts["articulation"]).read_text(encoding="utf-8"))
    out_dir = Path(opts["out_dir"]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    tracks_path = Path(art["tracks"])
    if not tracks_path.is_file():
        raise RuntimeError(f"missing tracks.npz: {tracks_path}")
    tracks = np.load(tracks_path)
    xy0 = tracks["xy0"]
    labels = tracks["labels"]
    centroids = art["partCentroidsPerFrame"]
    parts = art["parts"]
    hinges = art["hinges"]
    n_parts = len(parts)
    sprite_paths = [Path(f["path"]) for f in job["frames"]]
    sprite0 = Image.open(sprite_paths[0]).convert("RGBA")
    sw, sh = sprite0.size

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    removed = _weld(mesh)
    if removed:
        print(f"[part-map] weld-on-load removed {removed}", flush=True)
    if arm.animation_data:
        arm.animation_data_clear()
    # Our DOFs edit mesh coords directly; armature skinning would override the render.
    for mod in list(mesh.modifiers):
        if mod.type == "ARMATURE":
            mesh.modifiers.remove(mod)
            print("[part-map] removed Armature modifier (part-hinge DOFs own deformation)", flush=True)
    if mesh.data.shape_keys is not None:
        mesh.shape_key_clear()
        print("[part-map] cleared shape keys (direct vertex DOFs)", flush=True)

    world = bpy.data.worlds.new("PartMapWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.08, 0.09, 0.12, 1)
    bg.inputs["Strength"].default_value = 0.4

    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    _setup_lights()
    scene = bpy.context.scene
    scene.render.resolution_x = int(sw)
    scene.render.resolution_y = int(sh)
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    bpy.context.view_layer.update()


    def _use_eevee_texture() -> None:
        scene.render.engine = "BLENDER_EEVEE"
        scene.eevee.taa_render_samples = 8

    def _use_workbench_vcol() -> None:
        scene.render.engine = "BLENDER_WORKBENCH"
        shading = scene.display.shading
        shading.light = "FLAT"
        shading.color_type = "VERTEX"
        shading.show_cavity = False

    right, up, forward = _cam_axes(cam)
    mw = mesh.matrix_world.copy()
    n_verts = len(mesh.data.vertices)
    bind_world = np.zeros((n_verts, 3), dtype=np.float64)
    proj = np.zeros((n_verts, 3), dtype=np.float64)  # px, py, z
    for vi, v in enumerate(mesh.data.vertices):
        w = mw @ v.co
        bind_world[vi] = (w.x, w.y, w.z)
        px, py, z = _project_world_px(w, cam, scene, sw, sh)
        proj[vi] = (px, py, z)

    # Assign verts → nearest motion track label (screen space).
    max_px = float(opts["max_assign_px"])
    part_of = np.full(n_verts, -1, dtype=np.int32)
    sprite_a = np.array(sprite0.split()[-1], dtype=np.uint8)
    on_sprite = np.zeros(n_verts, dtype=np.bool_)
    primary = 0
    for vi in range(n_verts):
        px, py, z = proj[vi]
        if z <= 0:
            continue
        ix, iy = int(round(px)), int(round(py))
        if ix < 0 or iy < 0 or ix >= sw or iy >= sh:
            continue
        if sprite_a[iy, ix] < 8:
            y0, y1 = max(0, iy - 3), min(sh, iy + 4)
            x0, x1 = max(0, ix - 3), min(sw, ix + 4)
            if int(sprite_a[y0:y1, x0:x1].max()) < 8:
                continue
        on_sprite[vi] = True
        d = np.linalg.norm(xy0 - np.array([px, py]), axis=1)
        j = int(np.argmin(d))
        if float(d[j]) > max_px:
            continue
        part_of[vi] = int(labels[j])
        primary += 1

    # Fill remaining verts from nearest already-labeled bind vert (covers backfaces).
    labeled = np.where(part_of >= 0)[0]
    if len(labeled) == 0:
        raise RuntimeError("fail-closed: no verts matched motion tracks")
    labeled_co = bind_world[labeled]
    labeled_part = part_of[labeled]
    fill = 0
    for vi in range(n_verts):
        if part_of[vi] >= 0:
            continue
        d2 = np.sum((labeled_co - bind_world[vi]) ** 2, axis=1)
        j = int(np.argmin(d2))
        part_of[vi] = int(labeled_part[j])
        fill += 1

    on_sprite_n = int(on_sprite.sum())
    on_sprite_labeled = int(np.sum((part_of >= 0) & on_sprite))
    # Primary screen-match rate among silhouette-projected verts (fail-closed gate).
    primary_frac = primary / max(1, on_sprite_n)
    assign_frac = on_sprite_labeled / max(1, on_sprite_n)
    if primary_frac < float(opts["min_assign_frac"]):
        raise RuntimeError(
            f"fail-closed: primary screen-assign frac {primary_frac:.1%} "
            f"of on-sprite verts < {opts['min_assign_frac']} "
            f"(primary={primary}, on_sprite={on_sprite_n})"
        )
    for pid in range(n_parts):
        if int(np.sum(part_of == pid)) < 8:
            raise RuntimeError(f"fail-closed: part_{pid:02d} has too few mesh verts")
    assignable = int(np.sum(part_of >= 0))
    print(
        f"[part-map] primary={primary}/{on_sprite_n} ({primary_frac:.1%}) "
        f"fill={fill} totalLabeled={assignable}",
        flush=True,
    )

    # Vertex groups + colors
    while mesh.vertex_groups:
        mesh.vertex_groups.remove(mesh.vertex_groups[0])
    for pid in range(n_parts):
        mesh.vertex_groups.new(name=f"part_{pid:02d}")
    if not mesh.data.vertex_colors:
        mesh.data.vertex_colors.new(name="Col")
    vcol = mesh.data.vertex_colors.active
    # Paint loops
    vert_color = {}
    for pid in range(n_parts):
        c = PART_COLORS[pid % len(PART_COLORS)]
        for vi in np.where(part_of == pid)[0]:
            vert_color[int(vi)] = (*c, 1.0)
            mesh.vertex_groups[f"part_{pid:02d}"].add([int(vi)], 1.0, "REPLACE")
    for poly in mesh.data.polygons:
        for li in poly.loop_indices:
            vi = mesh.data.loops[li].vertex_index
            vcol.data[li].color = vert_color.get(vi, (0.2, 0.2, 0.2, 1.0))

    # Hinge surface anchors — nearest on-sprite labeled vert; fail if too far.
    hinge_search = float(opts["hinge_search_px"])
    hinge_surf = []
    for h in hinges:
        hx, hy = float(h["x"]), float(h["y"])
        best_vi = None
        best_d = 1e18
        for vi in range(n_verts):
            if part_of[vi] < 0 or not on_sprite[vi]:
                continue
            px, py, z = proj[vi]
            if z <= 0:
                continue
            d = math.hypot(px - hx, py - hy)
            if d < best_d:
                best_d = d
                best_vi = vi
        if best_vi is None or best_d > max(hinge_search, 64.0):
            raise RuntimeError(
                f"fail-closed: hinge {h.get('id')} at ({hx:.0f},{hy:.0f}) "
                f"missed mesh surface (nearestDistPx={best_d if best_vi is not None else None})"
            )
        hinge_surf.append(
            {
                **h,
                "vertIndex": int(best_vi),
                "world": [float(x) for x in bind_world[best_vi]],
                "screenDistPx": float(best_d),
            }
        )

    root, parent, hinge_by_pair = _build_parent_tree(
        parts,
        hinges,
        part_vert_counts=[int(np.sum(part_of == pid)) for pid in range(n_parts)],
    )
    children: dict[int, list[int]] = {i: [] for i in range(n_parts)}
    for c, p in parent.items():
        children[p].append(c)

    # Synthetic hinge world for orphans / missing pair entry: midpoint of part centroids unprojected via nearest verts
    def hinge_world_for(child: int, par: int) -> Vector:
        key = (min(child, par), max(child, par))
        for hs in hinge_surf:
            a = int(hs["partA"].split("_")[1])
            b = int(hs["partB"].split("_")[1])
            if {a, b} == {child, par}:
                return Vector(hs["world"])
        # Fallback: nearest vert on boundary between child and parent labels
        best_vi = None
        best_d = 1e18
        c0 = np.array(parts[child]["centroidF0"], dtype=np.float64)
        p0 = np.array(parts[par]["centroidF0"], dtype=np.float64)
        mid = 0.5 * (c0 + p0)
        for vi in range(n_verts):
            if part_of[vi] not in (child, par):
                continue
            d = float(np.linalg.norm(proj[vi, :2] - mid))
            if d < best_d:
                best_d = d
                best_vi = vi
        if best_vi is None:
            raise RuntimeError(f"fail-closed: no hinge surface for part_{child:02d}->part_{par:02d}")
        return Vector(bind_world[best_vi])

    # Topo order root-first
    order = []
    q = [root]
    while q:
        u = q.pop(0)
        order.append(u)
        q.extend(sorted(children[u]))

    # Frame 0 colored overlay render (vertex colors = motion parts)
    _use_workbench_vcol()
    scene.render.filepath = str(frames_dir / "mesh_parts_00.png")
    bpy.ops.render.render(write_still=True)
    _use_eevee_texture()

    # Soft skin weights (blurred part labels) — hard cuts rip triangles at boundaries.
    # Keep sigma small so high-motion extremities are not diluted into the body root.
    weights = _blur_part_weights(part_of, bind_world, n_parts, sigma=0.025)

    # Bind-space hinge anchors per child part.
    hinge_bind: dict[int, Vector] = {}
    hinge_xy: dict[int, tuple[float, float]] = {}
    for pid in order:
        if pid == root:
            continue
        par = parent[pid]
        hw = hinge_world_for(pid, par)
        hinge_bind[pid] = Vector(hw)
        hx, hy, _hz = _project_world_px(hinge_bind[pid], cam, scene, sw, sh)
        hinge_xy[pid] = (hx, hy)

    c0_root = centroids[0][root]
    if c0_root is None:
        raise RuntimeError("fail-closed: missing root centroid on frame 0")

    # Pose each frame via RELATIVE sprite motion (f0 = identity mesh).
    frame_reports = []
    ortho = float(cam.data.ortho_scale)
    world_per_px_x = ortho / float(sw)
    world_per_px_y = ortho / float(sh)
    for fi, sp in enumerate(sprite_paths):
        dofs = []
        root_t = centroids[fi][root]
        if root_t is None:
            raise RuntimeError(f"fail-closed: missing root centroid frame {fi}")
        dpx = float(root_t[0] - c0_root[0])
        dpy = float(root_t[1] - c0_root[1])
        delta = right * (dpx * world_per_px_x) + up * (-dpy * world_per_px_y)
        T = [Matrix.Identity(4) for _ in range(n_parts)]
        T[root] = Matrix.Translation(delta)
        dofs.append(
            {
                "part": f"part_{root:02d}",
                "kind": "root_translate_cam_plane_relative_f0",
                "deltaPx": [dpx, dpy],
                "deltaWorld": [float(delta.x), float(delta.y), float(delta.z)],
            }
        )

        for pid in order:
            if pid == root:
                continue
            par = parent[pid]
            c0 = centroids[0][pid]
            ct = centroids[fi][pid]
            if c0 is None or ct is None:
                T[pid] = T[par].copy()
                dofs.append({"part": f"part_{pid:02d}", "kind": "hold_missing_centroid"})
                continue
            hx, hy = hinge_xy[pid]
            th = _screen_angle(ct[0], ct[1], hx, hy) - _screen_angle(c0[0], c0[1], hx, hy)
            # Wrap to [-pi, pi]
            th = (th + math.pi) % (2 * math.pi) - math.pi
            h = hinge_bind[pid]
            rloc = Matrix.Translation(h) @ Matrix.Rotation(th, 4, forward) @ Matrix.Translation(-h)
            T[pid] = T[par] @ rloc
            dofs.append(
                {
                    "part": f"part_{pid:02d}",
                    "parent": f"part_{par:02d}",
                    "kind": "hinge_rotate_cam_axis_relative_f0",
                    "thetaRad": float(th),
                    "thetaDeg": float(math.degrees(th)),
                    "hingeWorldBind": [float(h.x), float(h.y), float(h.z)],
                    "hingeScreen": [hx, hy],
                }
            )

        # LBS: v' = sum_p w[p] * T[p] * v_bind
        posed = np.zeros_like(bind_world)
        for vi in range(n_verts):
            acc = Vector((0.0, 0.0, 0.0))
            bw = Vector(bind_world[vi])
            for pid in range(n_parts):
                wp = float(weights[vi, pid])
                if wp < 1e-5:
                    continue
                acc += wp * (T[pid] @ bw)
            posed[vi] = (acc.x, acc.y, acc.z)

        # Diagnostic: projected part-centroid drift vs sprite (relative target = bind + sprite delta).
        part_errs = []
        for pid in range(n_parts):
            ct = centroids[fi][pid]
            c0 = centroids[0][pid]
            if ct is None or c0 is None:
                continue
            # Expected screen motion of this part vs f0.
            exp_dx = float(ct[0] - c0[0])
            exp_dy = float(ct[1] - c0[1])
            idxs = np.where(part_of == pid)[0]
            # bind vs posed projected centroids
            acc0 = np.zeros(2, dtype=np.float64)
            acc1 = np.zeros(2, dtype=np.float64)
            n = 0
            step = max(1, len(idxs) // 60)
            for vi in idxs[::step]:
                p0x, p0y, z0 = _project_world_px(Vector(bind_world[vi]), cam, scene, sw, sh)
                p1x, p1y, z1 = _project_world_px(Vector(posed[vi]), cam, scene, sw, sh)
                if z0 <= 0 or z1 <= 0:
                    continue
                acc0 += (p0x, p0y)
                acc1 += (p1x, p1y)
                n += 1
            if n == 0:
                continue
            got = (acc1 - acc0) / n
            err = float(math.hypot(got[0] - exp_dx, got[1] - exp_dy))
            part_errs.append(err)
            for d in dofs:
                if d.get("part") == f"part_{pid:02d}" and "thetaRad" in d:
                    d["travelErrPx"] = err

        # Write posed coords into mesh (object space).
        inv = mw.inverted()
        for vi, v in enumerate(mesh.data.vertices):
            v.co = inv @ Vector(posed[vi])
        mesh.data.update()
        # Force evaluated mesh rebuild (parented meshes can otherwise stale-cache).
        mesh.data.update()
        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        deps.update()
        # Sanity: how far did verts move this frame?
        move = float(np.linalg.norm(posed - bind_world, axis=1).max())
        print(f"[part-map] frame {fi:02d} maxVertMove={move:.4f}", flush=True)

        mesh_path = frames_dir / f"mesh_{fi:02d}.png"
        scene.render.filepath = str(mesh_path)
        bpy.ops.render.render(write_still=True)

        sprite = Image.open(sp).convert("RGBA").resize((sw, sh))
        mesh_im = Image.open(mesh_path).convert("RGBA")
        side = Image.new("RGBA", (sw * 2, sh), (0, 0, 0, 255))
        side.paste(sprite, (0, 0))
        side.paste(mesh_im, (sw, 0))
        draw = ImageDraw.Draw(side)
        draw.rectangle([0, 0, sw * 2, 28], fill=(0, 0, 0, 180))
        draw.text((8, 6), f"frame {fi:02d}  sprite | part-hinge posed mesh (rel f0)", fill=(255, 255, 255, 255))
        side_path = frames_dir / f"side_{fi:02d}.png"
        for hs in hinge_surf:
            vi = int(hs["vertIndex"])
            px, py, _z = _project_world_px(Vector(posed[vi]), cam, scene, sw, sh)
            x = sw + px
            y = py
            r = 5
            draw.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255, 255), width=2)
        side.save(side_path)

        mean_err = float(np.mean(part_errs) if part_errs else 0.0)
        frame_reports.append(
            {
                "frame": fi,
                "mesh": str(mesh_path.resolve()),
                "side": str(side_path.resolve()),
                "meanPartTravelErrPx": mean_err,
                "dofs": dofs,
            }
        )
        print(f"[part-map] frame {fi:02d} meanPartTravelErrPx={mean_err:.2f}", flush=True)

    # Export posed last-frame mesh + bind-colored groups via glTF
    glb_out = out_dir / "articulation_parts_posed.glb"
    # Restore last frame already in mesh; export selected
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(filepath=str(glb_out), export_format="GLB", use_selection=True)

    # f0 parts-on-mesh overlay using vertex-color render already at mesh_parts_00; composite labels
    parts_overlay = Image.open(frames_dir / "mesh_parts_00.png").convert("RGBA")
    draw = ImageDraw.Draw(parts_overlay)
    for hs in hinge_surf:
        vi = int(hs["vertIndex"])
        px, py, _z = _project_world_px(Vector(bind_world[vi]), cam, scene, sw, sh)
        r = 6
        draw.ellipse([px - r, py - r, px + r, py + r], outline=(255, 255, 255, 255), width=2)
        draw.line([(px - r - 2, py), (px + r + 2, py)], fill=(255, 255, 255, 255), width=1)
        draw.line([(px, py - r - 2), (px, py + r + 2)], fill=(255, 255, 255, 255), width=1)
    for pid, p in enumerate(parts):
        c = p["centroidF0"]
        draw.text((c[0] + 4, c[1] - 4), f"p{pid:02d}", fill=(255, 255, 255, 255))
    parts_overlay_path = out_dir / "mesh_parts_hinges_f00.png"
    parts_overlay.save(parts_overlay_path)

    report = {
        "ok": True,
        "method": "motion_parts_to_mesh_surface_relative_hinge_dofs_lbs",
        "masterGlb": str(Path(job["masterGlb"]).resolve()),
        "articulation": str(Path(opts["articulation"]).resolve()),
        "weldRemoved": int(removed),
        "vertCount": int(n_verts),
        "assignedVertCount": int(assignable),
        "assignedFrac": float(assign_frac),
        "primaryScreenAssignCount": int(primary),
        "primaryScreenAssignFrac": float(primary_frac),
        "onSpriteVertCount": int(on_sprite_n),
        "fillAssignCount": int(fill),
        "rootPart": f"part_{root:02d}",
        "parent": {f"part_{c:02d}": f"part_{p:02d}" for c, p in parent.items()},
        "partVertCounts": {f"part_{pid:02d}": int(np.sum(part_of == pid)) for pid in range(n_parts)},
        "hingesOnSurface": hinge_surf,
        "frames": frame_reports,
        "glb": str(glb_out.resolve()),
        "partsOverlay": str(parts_overlay_path.resolve()),
        "notes": (
            "Mesh verts labeled from sprite motion tracks under visual-match camera. "
            "Pose DOFs = relative-to-f0 root cam-plane translate + hinge rotations about camera axis, "
            "applied with soft part weights (LBS) so boundaries do not rip. "
            "Not UniRig humanoid roles. Absolute chroma match unproven."
        ),
        "proof": "generated artifact validated — part/hinge mesh map + relative DOF pilot; not attack-read / OE runtime proven",
    }
    report_path = out_dir / "mesh_articulation_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report_path), "overlay": str(parts_overlay_path)}, indent=2), flush=True)
    return report


def main() -> int:
    try:
        run(_parse())
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
