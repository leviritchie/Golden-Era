#!/usr/bin/env python3
"""Build the camera-registered 3D town-scene bundle + catalog for the plugin lane Homm3TownScene3d (Conflux).

    python tools/homm3_town_scene_meshes/build_town_scene3d_bundle.py            # spec + Unity bundle + stage
    python tools/homm3_town_scene_meshes/build_town_scene3d_bundle.py --spec-only

Inputs are the registered preview state in the RUNTIME framing (build_conflux_town3d_preview.py stage, after
bake_town_materials.py): preview_spec.json (camera, fitted meshes, skirts/holes), materials/bake_report.json
(key + fill light), conflux_composite_z.npy (per-pixel depth for the HotA quads that stay 2D).

Everything is expressed in the reference camera's frame (cityHuman2 CityCamera/MainCamera, which is the camera
cityFactory uses: the registrar loads cityHuman2 additively). The runtime puts the prefab root at the live camera
and scales it by the frustum ratio, so meshes, skirts, 2D quads (layerDepths) and the backdrop stay registered.
A single uniform scale about the camera (depthScale) pulls the nearest-to-farthest range in front of the backdrop
quad at 80: a uniform scale about the camera centre does not change any projection.

Unity runs only as Unity-queue jobs (tools/unity_queue; its preflight runs memgate). Nothing is deployed. Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_conflux_town3d_preview as B  # noqa: E402

ROOT = B.ROOT
FRACTION = "homm3_conflux"
BUNDLE = "homm3_town_scene3d_conflux"
CATALOG_SCHEMA = "homm3_town_scene3d_catalog.v1"
ASSET_ROOT = "Assets/Homm3TownScene3d/conflux"
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
STAGE = PLUGIN / "homm3_town_scene_meshes" / "scene3d" / FRACTION
OUT = B.WORK / "scene3d_bundle"
MAX_DEPTH = 72.0          # farthest piece after depthScale; the backdrop quad sits at 80, HotA quads at 79.98
DISC_MESH = "tbeldw_5_frame"
DISC_PERIOD_S = 14.0


def cam_basis(cam: dict) -> tuple[np.ndarray, np.ndarray]:
    C = np.stack([cam["right"], cam["up"], cam["fwd"]], 1)  # world <- camera-local
    return C, np.asarray(cam["pos"], np.float64)


def mat_to_quat(m: np.ndarray) -> list[float]:
    """Rotation matrix -> Unity quaternion (x, y, z, w)."""
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        w, x, y, z = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w, x, y, z = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w, x, y, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w, x, y, z = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    q = np.array([x, y, z, w])
    return (q / np.linalg.norm(q)).tolist()


def read_grid(path: Path):
    b = path.read_bytes()
    nv, ns = struct.unpack_from("<ii", b, 0)
    o = 8
    v = np.frombuffer(b, np.float32, nv * 3, o).reshape(-1, 3); o += nv * 12
    n = np.frombuffer(b, np.float32, nv * 3, o).reshape(-1, 3); o += nv * 12
    uv = np.frombuffer(b, np.float32, nv * 2, o).reshape(-1, 2); o += nv * 8
    subs = []
    for _ in range(ns):
        (c,) = struct.unpack_from("<i", b, o); o += 4
        subs.append(np.frombuffer(b, np.int32, c, o)); o += c * 4
    return v.astype(np.float64), n, uv, subs


def write_grid(path: Path, v, n, uv, subs) -> None:
    with open(path, "wb") as f:
        f.write(struct.pack("<ii", len(v), len(subs)))
        f.write(np.asarray(v, np.float32).tobytes())
        f.write(np.asarray(n, np.float32).tobytes())
        f.write(np.asarray(uv, np.float32).tobytes())
        for s in subs:
            f.write(struct.pack("<i", len(s)))
            f.write(np.asarray(s, np.int32).tobytes())


def mesh_local_depths(row: dict, C, cpos) -> np.ndarray:
    """Camera-local z of every vertex of a registered mesh, as the preview places it."""
    verts, _ = B.load_glb_unity(B.MESHY / row.get("mesh", row["name"]) / B.MESH_ATTEMPT / "model.glb")
    if row.get("kneeScale"):
        verts = B.knee_remap(verts, row["kneeY"], row["kneeScale"])
    k = row.get("stretchY", 1.0)
    w = np.asarray(row["rootPosition"]) + (B.yaw_matrix(row["yaw"]) @ (verts * np.array([1, k, 1]) * row["scale"]).T).T
    return (w - cpos) @ C[:, 2]


def layer_depths(layers: dict, z: np.ndarray) -> dict[str, float]:
    """Median frame depth under each HotA layer's opaque pixels (runtime framing), for the quads that stay 2D."""
    out = {}
    for lid, L in layers.items():
        try:
            rgba = B.layer_frame(L)
        except Exception as e:  # noqa: BLE001 - a layer whose sprite cannot be framed is a hard failure below
            raise SystemExit(f"layer {lid}: cannot frame sprite ({e})")
        m = rgba[..., 3] > 127
        if m.sum() < 16:
            # Fully transparent placeholder sprites (e.g. Conflux tbelext4): the runtime still places the quad,
            # so it gets the depth under its placement rect (reference canvas px -> frame px).
            k = B.W / B.RUNTIME_CANVAS_W
            x0, y0 = int(L["reference_x"] * k), int(L["reference_y"] * k)
            x1, y1 = int((L["reference_x"] + L["reference_w"]) * k), int((L["reference_y"] + L["reference_h"]) * k)
            m = np.zeros_like(m)
            m[max(0, y0):min(B.H, max(y1, y0 + 1)), max(0, x0):min(B.W, max(x1, x0 + 1))] = True
        out[lid] = float(np.median(z[m]))
    return out


def disc_from_hole(hole_row: dict, C, cpos, cam: dict, lab_data: Path, out_dir: Path, scale: float,
                   inst: str = DISC_MESH) -> dict:
    """Portal disc: circle inscribed-ish in the painted portal surface, at the ring's depth, camera-facing."""
    from scipy.ndimage import distance_transform_edt

    tex = np.asarray(Image.open(lab_data / hole_row["texture"]).convert("RGBA"))
    x0, y0, _, _ = hole_row["rectPx"]
    m = tex[..., 3] > 127
    dt = distance_transform_edt(m)
    cy, cx = np.unravel_index(np.argmax(dt), dt.shape)
    r_in = float(dt.max())
    r_px = min(r_in * 1.15, float(np.sqrt(m.sum() / np.pi)))
    v, _, _, _ = read_grid(lab_data / hole_row["mesh"])
    zc = float(np.median((v - cpos) @ C[:, 2]))
    fx, fy = x0 + cx, y0 + cy
    t = np.tan(np.radians(cam["fov"]) / 2)
    center = np.array([((fx / B.W) * 2 - 1) * t * (B.W / B.H) * zc, (1 - (fy / B.H) * 2) * t * zc, zc])
    r_world = r_px * 2 * zc * t / B.H
    side = int(np.ceil(r_px * 2)) + 2
    crop = np.zeros((side, side, 4), np.uint8)
    sx0, sy0 = int(round(cx - side / 2)), int(round(cy - side / 2))
    for yy in range(side):
        for xx in range(side):
            ty, tx = sy0 + yy, sx0 + xx
            if 0 <= ty < tex.shape[0] and 0 <= tx < tex.shape[1]:
                crop[yy, xx] = tex[ty, tx]
    # Fill pixels outside the painted surface by nearest painted pixel so the spinning disc has no holes.
    from scipy.ndimage import distance_transform_edt as edt
    valid = crop[..., 3] > 127
    if valid.any():
        _, (iy, ix) = edt(~valid, return_indices=True)
        crop[..., :3] = crop[iy, ix, :3]
    yy, xx = np.mgrid[0:side, 0:side]
    rr = np.hypot(xx - side / 2 + 0.5, yy - side / 2 + 0.5)
    crop[..., 3] = np.clip((r_px - rr) / 1.5 + 0.5, 0, 1) * 255
    name = "disc_" + inst
    Image.fromarray(crop).save(out_dir / f"{name}.png")
    return {"name": "PortalDisc", "texture": f"{ASSET_ROOT}/{name}.png",
            "center": (center * scale).tolist(), "radius": float(r_world * scale),
            "periodSec": DISC_PERIOD_S, "segments": 64,
            "_meta": {"radiusPx": r_px, "inscribedPx": r_in, "depth": zc}}


def build_spec(args) -> dict:
    spec = json.loads((B.WORK / "preview_spec.json").read_text(encoding="utf-8"))
    bake = json.loads((B.WORK / "materials" / "bake_report.json").read_text(encoding="utf-8"))
    if not bake.get("fillLight"):
        raise SystemExit("bake_report has no fillLight: run bake_town_materials.py with --fill > 0 first")
    cam = B.camera()
    C, cpos = cam_basis(cam)
    lab_data = B.LAB / "data"
    layers = {l["id"]: l for l in json.loads((B.REFS / "layers" / "positions.json").read_text())["layers"]}
    z = np.load(B.WORK / "conflux_composite_z.npy")

    # Depth range -> one uniform scale about the camera (projection-invariant).
    far = 0.0
    for row in spec["meshes"]:
        far = max(far, float(mesh_local_depths(row, C, cpos).max()))
    depths = layer_depths(layers, z)
    mesh_layers = sorted({row["layer"] for row in spec["meshes"]})
    far = max(far, max(depths[l] for l in depths if l not in mesh_layers))
    scale = min(1.0, MAX_DEPTH / far)

    in_dir = B.PROJECT / ASSET_ROOT
    if in_dir.exists():
        shutil.rmtree(in_dir)
    in_dir.mkdir(parents=True)
    prefabs = {}
    # One prefab per HotA layer. A mesh shared by several instances (lower-level or upgrade layers that repeat
    # a building) is one GLB asset; a texture shared through bakeAs is one texture asset.
    for row in spec["meshes"]:
        name, layer, mesh = row["name"], row["layer"], row.get("mesh", row["name"])
        if not row["baseColor"].endswith("_hexlit_base.png"):
            raise SystemExit(f"{name}: no baked Hex/Lit texture ({row['baseColor']}); run bake_town_materials.py")
        p = prefabs.setdefault(layer, {"key": f"homm3_conflux3d_{layer}", "layerId": layer,
                                       "pieces": [], "sprites": [], "discs": []})
        shutil.copy2(lab_data / row["glb"], in_dir / f"{mesh}.glb")
        shutil.copy2(lab_data / row["baseColor"], in_dir / row["baseColor"])
        local_pos = C.T @ (np.asarray(row["rootPosition"]) - cpos) * scale
        rot = C.T @ B.yaw_matrix(row["yaw"])
        p["pieces"].append({"name": name, "glb": f"{ASSET_ROOT}/{mesh}.glb",
                            "texture": f"{ASSET_ROOT}/{row['baseColor']}",
                            "pos": local_pos.tolist(), "rot": mat_to_quat(rot), "scale": row["scale"] * scale,
                            "stretchY": row.get("stretchY", 1.0),
                            "kneeY": row.get("kneeY", 0.0), "kneeScale": row.get("kneeScale", 0.0)})
    disc_insts = {r["name"] for r in spec["meshes"] if r.get("mesh", r["name"]) == DISC_MESH}
    for pr in spec["projected"]:
        if pr["role"] not in ("skirt", "hole") or pr["layer"] not in prefabs:
            continue
        p = prefabs[pr["layer"]]
        inst = pr.get("instance", pr["name"].split("_", 1)[1])
        if pr["role"] == "hole" and inst in disc_insts:
            p["discs"].append(disc_from_hole(pr, C, cpos, cam, lab_data, in_dir, scale, inst))
            continue
        v, n, uv, subs = read_grid(lab_data / pr["mesh"])
        write_grid(in_dir / f"{pr['name']}.bytes", ((v - cpos) @ C) * scale, n, uv, subs)
        shutil.copy2(lab_data / pr["texture"], in_dir / f"{pr['name']}.png")
        p["sprites"].append({"name": pr["name"], "mesh": f"{ASSET_ROOT}/{pr['name']}.bytes",
                             "texture": f"{ASSET_ROOT}/{pr['name']}.png"})

    OUT.mkdir(parents=True, exist_ok=True)
    unity_spec = {"bundleName": BUNDLE, "assetRoot": ASSET_ROOT, "outputPath": str(OUT.resolve()).replace("\\", "/"),
                  "prefabs": [{k: v for k, v in p.items()} for p in prefabs.values()]}
    for p in unity_spec["prefabs"]:
        for d in p["discs"]:
            d.pop("_meta", None)
    (in_dir / "build_spec.json").write_text(json.dumps(unity_spec, indent=1), encoding="utf-8")

    key_local = (C.T @ np.asarray(bake["keyLight"]["sunDir"])).tolist()
    fill = bake["fillLight"]
    catalog = {
        "schema": CATALOG_SCHEMA,
        "fraction": FRACTION,
        "bundle": BUNDLE,
        "runtimeLayout": "conflux_4k_outpaint_v1",
        "proofTier": "generated artifact (bundle built, not deployed; runtime unproven)",
        "referenceCamera": {"fov": cam["fov"], "aspect": B.W / B.H, "source": "cityHuman2 CityCamera/MainCamera"},
        "depthScale": scale,
        # Directions are light TRAVEL directions in the camera frame (x right, y up, z forward).
        "keyLight": {"cameraLocalDir": key_local, "note": "rotates the scene's directional sun; colour/intensity unchanged"},
        "fillLight": {"cameraLocalDir": (C.T @ np.asarray(fill["dir"])).tolist(), "linearColor": fill["color"],
                      "shadows": False},
        "fog": "off",
        "layers": [{"layerId": p["layerId"], "prefabKey": p["key"],
                    "pieces": [x["name"] for x in p["pieces"]], "sprites": [x["name"] for x in p["sprites"]],
                    "animated": [x["name"] for x in p["discs"]]} for p in prefabs.values()],
        # Camera distance of every HotA layer that stays 2D (median depth under its opaque pixels).
        "layerDepths": [{"layerId": l, "distance": round(d * scale, 4)} for l, d in sorted(depths.items())
                        if l not in prefabs],
        "notAnimated": {"tbeldw_1": "air shrine stone orbit: tbeldw_1 has no mesh (projected 2D layer), nothing to orbit",
                        "tbeldw_0": "lantern sway: the lantern is fused into the dwelling mesh; no separable part"},
    }
    (OUT / "catalog.json").write_text(json.dumps(catalog, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"depthScale": scale, "farthestBeforeScale": far, "prefabs": len(prefabs),
                      "layerDepths": len(catalog["layerDepths"])}))
    return unity_spec


# --unity-direct (main) is the explicit, loudly logged opt-out of the Unity queue.
UNITY_DIRECT = False


def unity_job(method: str, extra: list[str], log: Path, output_dir: Path, graphics: bool,
              build_target: str | None) -> int:
    """One Unity batch job through the Unity queue (tools/unity_queue, docs/unity_queue_runner.md)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("unity_queue", ROOT / "tools/unity_queue/unity_queue.py")
    uq = importlib.util.module_from_spec(spec)
    sys.modules["unity_queue"] = uq  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(uq)
    res = uq.launch(kind="town_scene3d_conflux", method=method, args=[str(x) for x in extra], project=B.PROJECT,
                    log=log, inputs=[x for x in extra if Path(x).is_file()], output_dir=output_dir, graphics=graphics,
                    build_target=build_target, unity=B.UNITY, requester="build_town_scene3d_bundle",
                    direct=UNITY_DIRECT)
    return 0 if res["status"] == "ok" else (res.get("exitCode") or 1)


def run_unity() -> int:
    editor = B.PROJECT / "Assets" / "Editor"
    editor.mkdir(parents=True, exist_ok=True)
    shutil.copy2(B.UNITY_SRC / "Homm3TownScene3dBundleBuild.cs", editor / "Homm3TownScene3dBundleBuild.cs")
    log = OUT / "unity_bundle.log"
    rc = unity_job("Homm3TownScene3dBundleBuild.Run",
                   ["-scene3dSpec", str((B.PROJECT / ASSET_ROOT / "build_spec.json").resolve())], log, OUT,
                   graphics=False, build_target="StandaloneWindows64")
    print("unity rc", rc, "log", log)
    return rc


def stage() -> None:
    bundle = OUT / BUNDLE
    if not bundle.is_file() or bundle.stat().st_size < 1000:
        raise SystemExit(f"bundle missing: {bundle}")
    STAGE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle, STAGE / BUNDLE)
    cat = json.loads((OUT / "catalog.json").read_text(encoding="utf-8"))
    cat["bundleBytes"] = bundle.stat().st_size
    import hashlib
    cat["bundleSha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    (STAGE / "catalog.json").write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")
    print(f"staged {STAGE / BUNDLE} ({cat['bundleBytes']} bytes)")


def verify() -> dict:
    """Readback of the staged bundle: per-layer mask IoU against the preview's registered masks."""
    cam = B.camera()
    vdir = OUT / "verify"
    if vdir.exists():
        shutil.rmtree(vdir)
    vdir.mkdir(parents=True)
    cam_json = OUT / "verify_cam.json"
    cam_json.write_text(json.dumps({"pos": cam["pos"].tolist(), "fwd": cam["fwd"].tolist(), "up": cam["up"].tolist(),
                                    "fov": cam["fov"], "w": B.W, "h": B.H}), encoding="utf-8")
    editor = B.PROJECT / "Assets" / "Editor"
    shutil.copy2(B.UNITY_SRC / "Homm3TownScene3dBundleBuild.cs", editor / "Homm3TownScene3dBundleBuild.cs")
    if unity_job("Homm3TownScene3dBundleBuild.Verify",
                 ["-scene3dBundle", str((STAGE / BUNDLE).resolve()), "-scene3dCam", str(cam_json.resolve()),
                  "-scene3dOut", str(vdir.resolve())], OUT / "unity_verify.log", vdir,
                 graphics=True, build_target=None) != 0:
        raise SystemExit("bundle readback render failed; see unity_verify.log")
    spec = json.loads((B.WORK / "preview_spec.json").read_text(encoding="utf-8"))
    by_layer: dict[str, list[str]] = {}
    for row in spec["meshes"]:
        by_layer.setdefault(row["layer"], []).append(row["name"])
    rows = []
    for layer, names in sorted(by_layer.items()):
        got = np.asarray(Image.open(vdir / f"mask_homm3_conflux3d_{layer}.png").convert("L")) > 127
        ref = np.zeros_like(got)
        for n in names:
            ref |= np.asarray(Image.open(B.WORK / "unity_out" / f"mask_{n}.png").convert("L").resize(got.shape[::-1])) > 127
        iou = float((got & ref).sum() / max(1, (got | ref).sum()))
        rows.append({"layer": layer, "iouVsPreview": round(iou, 4), "pixels": int(got.sum()), "previewPixels": int(ref.sum())})
    rep = {"schema": "homm3_town_scene3d_bundle_readback.v1",
           "proof": "Unity-editor readback of the staged bundle seated as the runtime seats it; not in game",
           "minIoU": min(r["iouVsPreview"] for r in rows), "layers": rows}
    (OUT / "readback_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec-only", action="store_true")
    ap.add_argument("--verify", action="store_true", help="only run the readback check of the staged bundle")
    ap.add_argument("--unity-direct", action="store_true",
                    help="launch Unity directly instead of submitting to the Unity queue (explicit, logged opt-out; "
                         "docs/unity_queue_runner.md)")
    a = ap.parse_args()
    global UNITY_DIRECT
    UNITY_DIRECT = a.unity_direct
    if a.verify:
        verify()
        return 0
    build_spec(a)
    if a.spec_only:
        return 0
    rc = run_unity()
    if rc != 0:
        return rc
    stage()
    verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
