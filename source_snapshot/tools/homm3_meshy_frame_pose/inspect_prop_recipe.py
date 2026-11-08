"""Textured prop isolation and visible-surface pixel picking for attachment recipes.

Pixels refer to the individual full-resolution view PNG, not a resized contact sheet.
Run --mesh M --out D first; then --pick yaw:x:y to print actual visible surface points.
Add --recipe R to inspect each selected prop and the remaining body before attachment.
Use --panel-scale 4 when a small prop or thin bridge needs a readable diagnostic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "artifacts/homm3_owned_bind"))
from owned_rerig.glb_io import load_render_surface
from owned_rerig.prop_attachment import extract_prop_face_ids, extract_prop_faces, extract_prop_vertex_range
import exp_tpose as render


def inspection_view(yaw, positions):
    view = render.camera(yaw, positions)
    xy = np.column_stack((positions @ view["right"], positions @ view["down"]))
    view["off"] = np.array(render.PANEL) * .5 - view["k"] * (xy.min(axis=0) + xy.max(axis=0)) * .5
    return view


def pick_surface(positions, indices, view, pixel):
    """Pick a PNG pixel center using the renderer's smallest-depth rule."""
    positions = np.asarray(positions)
    triangles = np.asarray(indices).reshape(-1, 3)
    xy = np.column_stack((positions @ view["right"], positions @ view["down"]))
    xy = xy * view["k"] + view["off"]
    a, b, c = (xy[triangles[:, i]] for i in range(3))
    ab, ac, ap = b - a, c - a, np.asarray(pixel) + .5 - a
    cross = lambda u, v: u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]
    den = cross(ab, ac)
    valid = np.abs(den) > 1e-12
    u = np.divide(cross(ap, ac), den, out=np.zeros_like(den), where=valid)
    v = np.divide(cross(ab, ap), den, out=np.zeros_like(den), where=valid)
    inside = valid & (u >= -1e-8) & (v >= -1e-8) & (u + v <= 1 + 1e-8)
    ids = np.flatnonzero(inside)
    if not len(ids):
        raise ValueError(f"pixel {pixel} hits no surface; pick inside the textured object")
    bary = np.column_stack((1 - u[ids] - v[ids], u[ids], v[ids]))
    points = np.einsum("ni,nij->nj", bary, positions[triangles[ids]])
    front = np.argmin(points @ view["forward"])
    return {"face": int(ids[front]), "point": points[front].tolist(),
            "barycentric": bary[front].tolist()}


def save_view(path, surface, indices, view, title, panel_scale):
    panel = render.textured(view, deformed=surface["positions"], normals=surface["normals"],
                            surface=surface, indices=np.asarray(indices).reshape(-1))
    im = Image.fromarray(np.clip(panel, 0, 255).astype("uint8"))
    draw = ImageDraw.Draw(im)
    unit = int(panel_scale)
    draw.rectangle((0, 0, 600 * unit, 22 * unit), fill=(15, 15, 15))
    draw.text((5 * unit, 5 * unit), title, fill="white")
    for x in range(50, 600, 50):
        draw.line((x * unit, 25 * unit, x * unit, 32 * unit), fill="gray", width=unit)
        draw.text((x * unit + 2 * unit, 33 * unit), str(x), fill="gray")
    for y in range(100, 700, 50):
        draw.line((0, y * unit, 7 * unit, y * unit), fill="gray", width=unit)
        draw.text((9 * unit, y * unit), str(y), fill="gray")
    im.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--yaw", nargs="+", type=float, default=[0, 90, 180, 270])
    parser.add_argument("--pick", nargs="+", help="yaw:x:y in the individual full-resolution PNG")
    parser.add_argument("--panel-scale", type=int, default=1,
                        help="integer multiplier for the 600x700 diagnostic panel")
    args = parser.parse_args()
    if args.panel_scale < 1:
        parser.error("--panel-scale must be at least 1")
    if args.pick:
        return inspect(args)
    invalidate_inspection(args.out, {"status": "running", "mesh": str(args.mesh), "props": []})
    try:
        return inspect(args)
    except Exception as error:
        invalidate_inspection(args.out, {"status": "error", "mesh": str(args.mesh),
                                         "error": str(error), "props": []})
        raise


def invalidate_inspection(out, report):
    """An edited recipe must never leave its predecessor's isolation images as evidence."""
    out.mkdir(parents=True, exist_ok=True)
    for pattern in ("source_yaw*.png", "prop[0-9]*_yaw*.png", "body_yaw*.png"):
        for path in out.glob(pattern):
            path.unlink()
    (out / "inspection.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def inspect(args):
    surface = load_render_surface(args.mesh)
    render.PANEL, render.PITCH = (600 * args.panel_scale, 700 * args.panel_scale), 0
    positions, faces = surface["positions"], surface["indices"].reshape(-1, 3)
    if args.pick:
        for value in args.pick:
            yaw, x, y = map(float, value.split(":"))
            hit = pick_surface(positions, faces, inspection_view(yaw, positions), [x, y])
            print(json.dumps({"pick": value, **hit}))
        return
    args.out.mkdir(parents=True, exist_ok=True)
    views = {yaw: inspection_view(yaw, positions) for yaw in args.yaw}
    for yaw, view in views.items():
        save_view(args.out / f"source_yaw{yaw:g}.png", surface, faces, view,
                  f"Source | yaw {yaw:g}", args.panel_scale)
    report = {"status": "complete", "mesh": str(args.mesh.resolve()), "sourceMeshSha256": surface["sourceSha256"],
              "bounds": [positions.min(axis=0).tolist(), positions.max(axis=0).tolist()], "props": []}
    if args.recipe:
        config = json.loads(args.recipe.read_text(encoding="utf-8"))
        if config["sourceMeshSha256"] != surface["sourceSha256"]:
            raise ValueError("recipe belongs to a different source mesh")
        selected = np.zeros(len(faces), dtype=bool)
        for number, prop in enumerate(config["props"]):
            if sum(key in prop for key in ("sourceFaceIds", "sourceVertexRange", "region")) != 1:
                raise ValueError("prop requires exactly one source face selector")
            if "sourceFaceIds" in prop:
                ids, stats = extract_prop_face_ids(positions, faces, prop["sourceFaceIds"])
            elif "sourceVertexRange" in prop:
                ids, stats = extract_prop_vertex_range(positions, faces, prop["sourceVertexRange"])
            else:
                ids, stats = extract_prop_faces(positions, faces, prop["region"])
            if selected[ids].any():
                raise ValueError("prop recipes overlap")
            selected[ids] = True
            points = positions[np.unique(faces[ids])]
            report["props"].append({"name": prop["name"], **stats,
                                    "bounds": [points.min(axis=0).tolist(), points.max(axis=0).tolist()]})
            for yaw, view in views.items():
                save_view(args.out / f"prop{number}_yaw{yaw:g}.png", surface, faces[ids], view,
                          f"{prop['name']} only | yaw {yaw:g}", args.panel_scale)
        for yaw, view in views.items():
            save_view(args.out / f"body_yaw{yaw:g}.png", surface, faces[~selected], view,
                      f"Body without selected props | yaw {yaw:g}", args.panel_scale)
    (args.out / "inspection.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
