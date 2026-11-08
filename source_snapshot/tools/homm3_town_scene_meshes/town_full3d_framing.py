"""Town framing: how much of the visible (non-HUD) viewport is the painting, at the rest view and the pan poses.

The owned town scene is seated at the native cityHuman2 MainCamera rest pose (Homm3TownScene3d.PlaceRoot). The
painting fills only the top-left 1440x673 of the 1920x1080 rest frame, so at 100% the extension (and its seams)
takes the right quarter and the bottom third, and the HUD covers the bottom ~23% and right ~10%. A profile
FRAMING = {"zoom": Z, "aim": "fit", "panScale": s, "reason": ...} narrows the native camera's field of view by Z
(tan(fov/2) / Z), turns the scene about the rest camera so the painting sits in the middle of the visible region
(a rigid rotation of the root, not a post-scale), and scales the native pan (the SoCityCameraSettings sweep nodes
about the rest camera, and the cursor look angles) by s.

    python town_full3d_framing.py --faction stronghold measure [--zooms 1.0 1.1 1.2] [--pan-scales 1 0.5]
    python town_full3d_framing.py --faction stronghold render --out DIR     (before / after at the profile framing)
    python town_full3d_framing.py --faction stronghold apply --catalog <candidate>/bundle/catalog.json

Classification, per rendered pixel (prefab frame, camera at the origin): its surface point projected into the rest
frame is painting iff it lands inside the painted rect and is not farther than what the rest camera saw there (a
disoccluded surface behind a building is back fill, not painting). Everything else is extension. The HUD region
(HUD_*) is excluded from the denominator. Buildings: every staged building prefab's mesh bounds must lie fully in
the visible region at the rest view (the click target is the body bounds). Proof tier: generated artifact (offline
preview geometry), not an in-game capture.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

LANE = Path(__file__).resolve().parent
sys.path.insert(0, str(LANE))
import stronghold_full3d_common as SC  # noqa: E402  (reads --faction)

# Visible region of the town screen at 16:9 (measured on the user's 2560x1440 capture, 2026-09-28): the right
# building column starts at x 0.9016 (2308 px), the bottom hero / garrison panels at y 0.764 (1100 px); the top frame
# ornament is taken as 0.03 (the capture's dark bar is the transient screenshot notice).
HUD_RIGHT, HUD_BOTTOM, HUD_TOP = 0.90, 0.764, 0.03
REST_FOV = 47.6          # the native MainCamera vertical fov (factory_town_scene_graph_ledger Batch E)
ASPECT = 16 / 9
RW, RH = 960, 540        # measurement raster


def visible_mask(w=RW, h=RH) -> np.ndarray:
    xs = (np.arange(w) + 0.5) / w
    ys = (np.arange(h) + 0.5) / h
    return (xs[None, :] < HUD_RIGHT) & (ys[:, None] >= HUD_TOP) & (ys[:, None] < HUD_BOTTOM)


def load_geometry():
    """Every staged bin in the prefab frame: (prefab, name, v, tris)."""
    import json
    import stronghold_full3d_scene as S
    import town_t2_fx_occlusion as OC
    rows = json.loads(S.ROWS.read_text(encoding="utf-8")) if S.ROWS.is_file() else {}
    posed = {(k, b["name"]): b for k, r in rows.items() for b in r.get("bins", []) if b.get("pos") or b.get("rot")}
    out = []
    for pdir in sorted(S.STAGE.iterdir()):
        if not pdir.is_dir():
            continue
        for mb in sorted(pdir.glob("*.bytes")):
            if not mb.with_name(mb.stem + "_albedo.png").is_file():
                continue          # the preview loader's rule: a bin is a mesh with its albedo (fx data is not)
            v, n, uv, subs = S.read_bin(mb)
            if mb.stem == "Sky_Drift":
                import town_full3d_sky as SKY
                v, n = SKY.holder_to_prefab(v, n, pdir.name)
            elif (pdir.name, mb.stem) in posed:
                # a posed bin (swing card, keyed-pose body) stores holder-local vertices: rot then pos -> prefab frame
                b = posed[(pdir.name, mb.stem)]
                v = np.asarray(v, np.float64)
                c0 = OC.bin_centre(np.zeros((1, 3)), b)            # = pos
                R = np.stack([OC.bin_centre(np.eye(3)[i:i + 1], b) - c0 for i in range(3)], 1)
                v = v @ R.T + c0
            out.append((pdir.name, mb.stem, np.asarray(v, np.float32), np.concatenate(subs).astype(np.int32)))
    return out


class PosRenderer:
    """Prefab-frame surface positions per pixel (moderngl, float32, depth tested)."""
    VS = """#version 330
uniform mat4 mvp; in vec3 in_pos; out vec3 v_p;
void main(){ gl_Position = mvp * vec4(in_pos, 1.0); v_p = in_pos; }"""
    FS = """#version 330
in vec3 v_p; out vec4 o; void main(){ o = vec4(v_p, 1.0); }"""

    def __init__(self, geo, w=RW, h=RH):
        import moderngl
        self.ctx = moderngl.create_standalone_context()
        self.prog = self.ctx.program(vertex_shader=self.VS, fragment_shader=self.FS)
        self.w, self.h = w, h
        self.fbo = self.ctx.framebuffer(color_attachments=[self.ctx.texture((w, h), 4, dtype="f4")],
                                        depth_attachment=self.ctx.depth_renderbuffer((w, h)))
        self.vaos = []
        for prefab, name, v, t in geo:
            vbo = self.ctx.buffer(v.tobytes())
            ibo = self.ctx.buffer(t.tobytes())
            self.vaos.append((prefab, name, self.ctx.vertex_array(self.prog, [(vbo, "3f", "in_pos")], ibo)))

    def render(self, cam: dict) -> np.ndarray:
        import moderngl
        import stronghold_full3d_preview as PV
        mvp = PV.perspective(cam["fov"], self.w / self.h, 0.05, 5000.0) @ PV.view(cam["pos"], cam["fwd"], cam["up"],
                                                                                  cam["right"])
        self.fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0, 0.0)
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.CULL_FACE)
        self.prog["mvp"].write(mvp.T.astype(np.float32).tobytes())
        for _, _, vao in self.vaos:
            vao.render()
        a = np.frombuffer(self.fbo.color_attachments[0].read(), np.float32).reshape(self.h, self.w, 4)
        return a[::-1].copy()


def rest_cam(zoom=1.0) -> dict:
    return {"pos": np.zeros(3), "fwd": np.array([0.0, 0.0, 1.0]), "up": np.array([0.0, 1.0, 0.0]),
            "right": np.array([1.0, 0.0, 0.0]), "fov": zoomed_fov(zoom)}


def zoomed_fov(zoom: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(REST_FOV) / 2) / zoom))


def project_rest(P: np.ndarray):
    """Prefab-frame points -> rest-frame pixel (1920x1080 frame px) and depth along +z."""
    ty = math.tan(math.radians(REST_FOV) / 2)
    tx = ty * ASPECT
    z = P[..., 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        px = (0.5 + 0.5 * P[..., 0] / (z * tx)) * SC.W
        py = (0.5 - 0.5 * P[..., 1] / (z * ty)) * SC.H
    return px, py, z


def aim_fit(zoom: float) -> np.ndarray:
    """Root-local rotation Delta putting the painted rect's centre at the visible region's centre (Delta = B^T, B the
    aimed camera's axes in the rest frame)."""
    TW, TH = SC.TW, SC.TH
    pc = np.array([TW / 2 / SC.W, TH / 2 / SC.H])
    vc = np.array([HUD_RIGHT / 2, (HUD_TOP + HUD_BOTTOM) / 2])
    s0 = pc + (np.array([0.5, 0.5]) - vc) / zoom
    ty = math.tan(math.radians(REST_FOV) / 2)
    d = np.array([(2 * s0[0] - 1) * ty * ASPECT, (1 - 2 * s0[1]) * ty, 1.0])
    f = d / np.linalg.norm(d)
    r = np.cross([0.0, 1.0, 0.0], f)   # Unity (left-handed): right = up x forward
    r /= np.linalg.norm(r)
    u = np.cross(f, r)
    B = np.stack([r, u, f], 1)
    return B.T


def aim_buildings(zoom: float, pts: np.ndarray, iters: int = 6) -> np.ndarray:
    """Delta centring the union of the building bounds (exact projection) in the visible region."""
    delta = aim_fit(zoom)
    vc = np.array([HUD_RIGHT / 2, (HUD_TOP + HUD_BOTTOM) / 2])
    ty = math.tan(math.radians(zoomed_fov(zoom)) / 2)
    for _ in range(iters):
        cam = {**rest_cam(zoom)}
        Di = delta.T
        cam.update(fwd=Di @ [0, 0, 1.0], up=Di @ [0, 1.0, 0], right=Di @ [1.0, 0, 0])
        b = box_in_view(pts, cam)["box"]
        mid = np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])
        err = mid - vc                     # screen fraction; turn the camera toward the error
        yaw = math.atan(2 * err[0] * ty * ASPECT)
        pitch = -math.atan(2 * err[1] * ty)   # content low (err > 0): look down
        ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
        rx = np.array([[1, 0, 0], [0, math.cos(pitch), math.sin(pitch)], [0, -math.sin(pitch), math.cos(pitch)]])
        B = delta.T @ ry @ rx
        f = B[:, 2] / np.linalg.norm(B[:, 2])
        r = np.cross([0.0, 1.0, 0.0], f)
        r /= np.linalg.norm(r)
        B = np.stack([r, np.cross(f, r), f], 1)
        delta = B.T
    return delta


def mat_to_quat(M: np.ndarray) -> list[float]:
    from scipy.spatial.transform import Rotation
    x, y, z, w = Rotation.from_matrix(M).as_quat()
    if w < 0:
        x, y, z, w = -x, -y, -z, -w
    return [float(x), float(y), float(z), float(w)]


def framed_poses(zoom: float, delta: np.ndarray, pan_scale: float) -> dict:
    """The proof poses (rest, cursor extremes, sweep extremes / high) under the framing, in the prefab frame."""
    import copy
    import conflux_town_camera_pan as PAN
    c = copy.deepcopy(PAN.load())
    s = c["settings"]
    rest = np.asarray(c["camera"]["worldPos"], np.float64)
    s["deltaHorizontalAngle"] *= pan_scale
    s["deltaVerticalAngle"] *= pan_scale
    s["positionNodes"] = (rest + pan_scale * (np.asarray(s["positionNodes"]) - rest)).tolist()
    Di = delta.T
    out = {}
    for p in PAN.proof_poses(c):
        f, u = Di @ np.asarray(p["fwd"]), Di @ np.asarray(p["up"])
        r = np.cross(u, f)
        out[p["name"]] = {"pos": Di @ np.asarray(p["pos"]), "fwd": f, "up": u, "right": r / np.linalg.norm(r),
                          "fov": zoomed_fov(zoom)}
    return out


def classify(Pimg: np.ndarray, rest_img: np.ndarray) -> np.ndarray:
    """Per pixel: 1 painting, 0 extension, -1 nothing drawn."""
    hit = Pimg[..., 3] > 0.5
    P = Pimg[..., :3]
    px, py, z = project_rest(P)
    inside = hit & (z > 0) & (px >= 0) & (px < SC.TW) & (py >= 0) & (py < SC.TH)
    # disocclusion: the rest camera's own surface along the same ray
    rx = np.clip((px / SC.W * rest_img.shape[1]).astype(int), 0, rest_img.shape[1] - 1)
    ry = np.clip((py / SC.H * rest_img.shape[0]).astype(int), 0, rest_img.shape[0] - 1)
    seen = rest_img[ry, rx, :3]
    d_seen = np.linalg.norm(seen, axis=-1)
    d_here = np.linalg.norm(P, axis=-1)
    unoccluded = d_here <= d_seen * 1.03 + 0.3
    out = np.where(hit, 0, -1)
    out[inside & unoccluded] = 1
    return out


def building_boxes(geo) -> dict:
    env = SC.FP.PREFIX + "environment"
    pts: dict = {}
    for prefab, name, v, _ in geo:
        if prefab == env or not name.startswith("Mesh_"):
            continue
        pts.setdefault(prefab, []).append(v)
    return {k: np.concatenate(v) for k, v in pts.items()}


def box_in_view(P: np.ndarray, cam: dict) -> dict:
    """Screen-space bounds (0..1) of points under cam, and whether they lie in the visible region."""
    R = np.stack([cam["right"], cam["up"], cam["fwd"]], 0)
    q = (P - cam["pos"]) @ R.T
    ty = math.tan(math.radians(cam["fov"]) / 2)
    q = q[q[:, 2] > 0.1]
    x = 0.5 + 0.5 * q[:, 0] / (q[:, 2] * ty * ASPECT)
    y = 0.5 - 0.5 * q[:, 1] / (q[:, 2] * ty)
    b = [float(x.min()), float(y.min()), float(x.max()), float(y.max())]
    ok = b[0] >= 0 and b[2] <= HUD_RIGHT and b[1] >= HUD_TOP and b[3] <= HUD_BOTTOM
    return {"box": [round(v, 4) for v in b], "inVisible": bool(ok)}


def measure(zooms, pan_scales, aim: str = "fit") -> dict:
    geo = load_geometry()
    R = PosRenderer(geo)
    rest_img = R.render(rest_cam(1.0))
    vis = visible_mask()
    boxes = building_boxes(geo)
    rows = []
    allpts = np.concatenate(list(boxes.values()))
    for z in zooms:
        delta = {"fit": lambda: aim_fit(z), "buildings": lambda: aim_buildings(z, allpts),
                 "none": lambda: np.eye(3)}[aim]()
        for s in pan_scales:
            poses = framed_poses(z, delta, s)
            row = {"zoom": z, "panScale": s, "aim": aim, "aimQuat": mat_to_quat(delta), "poses": {}}
            for name, cam in poses.items():
                cl = classify(R.render(cam), rest_img)
                v = vis & (cl >= 0)
                row["poses"][name] = {"paintingShare": round(float((cl[v] == 1).mean()), 4),
                                      "extensionShare": round(float((cl[v] == 0).mean()), 4),
                                      "emptyShare": round(float(((cl < 0) & vis).sum() / vis.sum()), 4)}
            rc = poses["default"]
            bb = {k: box_in_view(P, rc) for k, P in boxes.items()}
            row["buildingsOutAtRest"] = sorted(k for k, b in bb.items() if not b["inVisible"])
            reach = {k: any(box_in_view(P, c)["inVisible"] for c in poses.values()) for k, P in boxes.items()}
            row["buildingsUnreachable"] = sorted(k for k, ok in reach.items() if not ok)
            rows.append(row)
            print(json.dumps({"zoom": z, "panScale": s, **{k: v["paintingShare"] for k, v in row["poses"].items()},
                              "outAtRest": len(row["buildingsOutAtRest"]),
                              "unreachable": len(row["buildingsUnreachable"])}), flush=True)
    return {"schema": "town_full3d_framing.v1", "faction": SC.FACTION, "hud": [HUD_RIGHT, HUD_BOTTOM, HUD_TOP],
            "restFov": REST_FOV, "rows": rows, "buildings": sorted(boxes)}


def profile_framing() -> dict | None:
    f = getattr(SC.FP, "FRAMING", None)
    if f is None:
        return None
    if not isinstance(f, dict) or not f.get("reason") or f.get("aim") not in ("buildings", "fit", "none"):
        raise SystemExit(f"town_full3d_framing: profile FRAMING {f!r} needs aim buildings / fit / none and a reason")
    if not (1.0 <= float(f["zoom"]) <= 1.6) or not (0.0 < float(f["panScale"]) <= 1.0):
        raise SystemExit("town_full3d_framing: FRAMING zoom must be in [1, 1.6] and panScale in (0, 1]")
    return f


def catalog_block(measured: bool = True) -> dict | None:
    """referenceCamera.framing for the catalog, from the profile and the staged buildings (None: no framing)."""
    f = profile_framing()
    if f is None:
        return None
    z, s = float(f["zoom"]), float(f["panScale"])
    geo = load_geometry()
    boxes = building_boxes(geo)
    # every building vertex (not a [::7] subsample): the aim is a function of the projected bounds only, so a
    # depth-only change (contact_v1 redepth scales about the camera) cannot move it (rampart rx_layer_card_dfix:
    # the subsample moved tbrmspec 0.0004 below the HUD edge at an identical rest projection)
    pts = np.concatenate(list(boxes.values()))
    delta = {"buildings": lambda: aim_buildings(z, pts), "fit": lambda: aim_fit(z), "none": lambda: np.eye(3)}[f["aim"]]()
    blk = {"schema": "town_full3d_framing.v1", "zoom": z, "fov": round(zoomed_fov(z), 4),
           "aimRotation": mat_to_quat(delta), "panScale": s, "aim": f["aim"], "reason": f["reason"],
           "hud": {"right": HUD_RIGHT, "bottom": HUD_BOTTOM, "top": HUD_TOP},
           "runtime": "Homm3TownScene3d: MainCamera.fieldOfView = 2 atan(tan(native/2) / zoom); root rotation = "
                      "pivot * restPose * aimRotation; SoCityCameraSettings clone with sweep nodes about the rest "
                      "camera and cursor angles scaled by panScale"}
    if measured:
        R = PosRenderer(geo)
        rest_img = R.render(rest_cam(1.0))
        vis = visible_mask()
        rep = {}
        for tag, (zz, dd, ss) in {"before": (1.0, np.eye(3), 1.0), "after": (z, delta, s)}.items():
            poses = framed_poses(zz, dd, ss)
            rep[tag] = {}
            for name, cam in poses.items():
                cl = classify(R.render(cam), rest_img)
                v = vis & (cl >= 0)
                rep[tag][name] = {"painting": round(float((cl[v] == 1).mean()), 4),
                                  "empty": round(float(((cl < 0) & vis).sum() / vis.sum()), 4)}
            rep[tag]["buildingsOutAtRest"] = sorted(k for k, P in boxes.items()
                                                    if not box_in_view(P, poses["default"])["inVisible"])
        blk["measured"] = rep
        if rep["after"]["buildingsOutAtRest"]:
            raise SystemExit(f"town_full3d_framing: buildings out of the visible region at rest: "
                             f"{rep['after']['buildingsOutAtRest']}")
    return blk


def render_sheet(out: Path) -> dict:
    """Before / after at the rest view and both pan extremes, 16:9, HUD region shaded (offline preview)."""
    from PIL import Image, ImageDraw
    import stronghold_full3d_scene as S
    f = profile_framing()
    blk = catalog_block(measured=False)
    sc = S.Scene()
    S.load_staged_preview(sc)
    delta = np.asarray(__import__("scipy.spatial.transform", fromlist=["Rotation"]).Rotation
                       .from_quat(blk["aimRotation"]).as_matrix())
    out.mkdir(parents=True, exist_ok=True)
    tiles = []
    for tag, (zz, dd, ss) in {"before": (1.0, np.eye(3), 1.0), "after": (float(f["zoom"]), delta,
                                                                          float(f["panScale"]))}.items():
        poses = framed_poses(zz, dd, ss)
        cams = {}
        for name in ("sweep_left", "default", "sweep_right"):
            c = poses[name]
            cams[name] = {**sc.cam, "pos": sc.cpos + (c["pos"] / sc.scale) @ sc.C.T, "fwd": c["fwd"] @ sc.C.T,
                          "up": c["up"] @ sc.C.T, "right": c["right"] @ sc.C.T, "fov": c["fov"]}
        shots = S.preview(sc, out / tag, cams)
        row = []
        for name in ("sweep_left", "default", "sweep_right"):
            im = Image.open(shots[name]).convert("RGB")
            d = ImageDraw.Draw(im, "RGBA")
            w, h = im.size
            for box in ((HUD_RIGHT * w, 0, w, h), (0, HUD_BOTTOM * h, HUD_RIGHT * w, h), (0, 0, HUD_RIGHT * w, HUD_TOP * h)):
                d.rectangle(box, fill=(10, 20, 40, 170))
            d.text((12, 40), f"{tag} {name}", fill=(255, 255, 0, 255))
            row.append(np.asarray(im.resize((640, 360))))
        tiles.append(np.concatenate(row, 1))
    sheet = out / "framing_before_after.png"
    Image.fromarray(np.concatenate(tiles, 0)).save(sheet)
    return {"sheet": str(sheet)}


def apply_catalog(path: Path) -> dict:
    """Write the profile's framing into an existing catalog (the delta applied on top of any candidate)."""
    cat = json.loads(path.read_text(encoding="utf-8"))
    if cat.get("fraction") != SC.FP.FRACTION:
        raise SystemExit(f"{path}: catalog is {cat.get('fraction')!r}, not {SC.FP.FRACTION!r}")
    blk = catalog_block()
    if blk is None:
        cat["referenceCamera"].pop("framing", None)
    else:
        cat["referenceCamera"]["framing"] = blk
    path.write_text(json.dumps(cat, indent=1), encoding="utf-8")
    return blk or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faction", default=SC.FACTION)
    ap.add_argument("cmd", choices=["measure", "apply", "render"])
    ap.add_argument("--catalog", default="", help="apply: catalog.json to write referenceCamera.framing into")
    ap.add_argument("--zooms", type=float, nargs="*", default=[1.0, 1.05, 1.1, 1.15, 1.2, 1.25])
    ap.add_argument("--pan-scales", type=float, nargs="*", default=[1.0])
    ap.add_argument("--aim", choices=["fit", "buildings", "none"], default="buildings")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.cmd == "apply":
        print(json.dumps(apply_catalog(Path(a.catalog)), indent=1))
        return 0
    if a.cmd == "render":
        print(json.dumps(render_sheet(Path(a.out))))
        return 0
    rep = measure(a.zooms, a.pan_scales, a.aim)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
