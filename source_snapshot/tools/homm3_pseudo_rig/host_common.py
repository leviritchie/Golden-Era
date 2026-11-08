#!/usr/bin/env python3
"""
Host-side common utilities for pseudo-rig: GLB loading, deformation, projection, raster.
Designed to match Blender LBS + homm3_pose_camera iso ortho as closely as possible.
"""
from __future__ import annotations
import json
import struct
import math
from pathlib import Path
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]

def load_glb_mesh_and_skin(glb_path: Path):
    """
    Returns:
      verts_raw_glTF : (N,3) float32 in glTF Y-up (as stored)
      faces : (F,3) int32
      joints : (N,4) uint16 skin joint indices
      weights : (N,4) float32
      handle_rest_glTF : (H,3) glTF Y-up (from catalog)
      skin_joints : list[int] node indices for joints
      nodes_json, json_data, bin_data
    """
    data = glb_path.read_bytes()
    off = 12
    json_data = None
    bin_data = None
    import json as _json, struct as _st
    while off < len(data):
        l, t = _st.unpack('<I4s', data[off:off+8])
        ch = data[off+8:off+8+l]
        if t == b'JSON':
            json_data = _json.loads(ch.decode('utf-8'))
        elif t == b'BIN\x00':
            bin_data = ch
        off += 8 + l
    assert json_data is not None and bin_data is not None

    def read_acc(idx):
        acc = json_data['accessors'][idx]
        bv = json_data['bufferViews'][acc['bufferView']]
        byte_off = int(bv.get('byteOffset', 0) + acc.get('byteOffset', 0))
        count = int(acc['count'])
        ctype = acc['componentType']
        typ = acc['type']
        dtype_map = {5126: np.float32, 5121: np.uint8, 5123: np.uint16, 5120: np.int8}
        type_map = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
        dtype = dtype_map[ctype]
        nc = type_map[typ]
        arr = np.frombuffer(bin_data, dtype=dtype, count=count * nc, offset=byte_off)
        if nc > 1:
            arr = arr.reshape(count, nc)
        return arr, acc, bv

    prim = json_data['meshes'][0]['primitives'][0]
    verts_raw, _, _ = read_acc(prim['attributes']['POSITION'])
    faces, _, _ = read_acc(prim['indices'])
    joints, _, _ = read_acc(prim['attributes']['JOINTS_0'])
    weights, _, _ = read_acc(prim['attributes']['WEIGHTS_0'])
    # faces are uint16 maybe
    faces = faces.astype(np.int32).reshape(-1, 3)
    joints = joints.astype(np.int32)
    weights = weights.astype(np.float32)
    skin_joints = json_data['skins'][0]['joints']
    return {
        "verts_raw_glTF": verts_raw,
        "faces": faces,
        "joints": joints,
        "weights": weights,
        "skin_joints": skin_joints,
        "json_data": json_data,
        "bin_data": bin_data,
    }

def gltf_to_blender_pos(arr: np.ndarray) -> np.ndarray:
    """Convert glTF Y-up positions to Blender Z-up: [x,y,z]_glTF -> [x,-z,y]_bl"""
    # arr shape (...,3) last dim x,y,z
    out = np.empty_like(arr)
    out[..., 0] = arr[..., 0]
    out[..., 1] = -arr[..., 2]
    out[..., 2] = arr[..., 1]
    return out

def load_handle_catalog(cat_path: Path):
    cat = json.loads(cat_path.read_text(encoding='utf-8'))
    rest = np.array([h['restPosition'] for h in cat['handles']], dtype=np.float64)  # already Blender Z-up
    names = [h['name'] for h in cat['handles']]
    return cat, rest, names

def build_handle_index_map(skin_joints: list[int], joints: np.ndarray, num_handles: int = 48):
    """
    Map per-vert skin joint indices to handle ids.
    skin_joints[0]=48 ROOT, [1]=0 ... etc.
    Returns handle_indices (N,4) with -1 for ROOT, handle_weights.
    """
    # Build map skin_idx -> handle_id
    skin_to_handle = {}
    for skin_idx, node_idx in enumerate(skin_joints):
        if node_idx == 48:  # ROOT
            skin_to_handle[skin_idx] = -1
        else:
            # node 0..47 => handle 0..47
            skin_to_handle[skin_idx] = int(node_idx)
    N = joints.shape[0]
    handle_indices = np.full((N, 4), -1, dtype=np.int32)
    for i in range(N):
        for k in range(4):
            s = int(joints[i, k])
            handle_indices[i, k] = int(skin_to_handle.get(s, -1))
    return handle_indices

def camera_params_from_job(job: dict):
    cfg = job.get("camera") or {}
    az = math.radians(float(cfg.get("isoAzimuthDeg", 40.0)))
    el = math.radians(float(cfg.get("isoElevationDeg", 30.0)))
    dist = float(cfg.get("distance", 3.0))
    zoff = float(cfg.get("isoZOffset", 0.35))
    lookAtZ = float(cfg.get("lookAtZ", 0.75))
    ortho = float(cfg.get("orthoScale", 4.2))
    return {"az": az, "el": el, "dist": dist, "zoff": zoff, "lookAtZ": lookAtZ, "ortho": ortho}

def compute_camera_basis(job: dict):
    """
    Compute cam location, right, up, forward (world Z-up) exactly like homm3_pose_camera + _camera_basis_arm_space but without Blender.
    Arm at origin, no yaw.
    Returns cam_loc (3,), right (3,), up (3,), forward (3,) all unit, view matrix equivalent.
    """
    cfg = job.get("camera") or {}
    az = math.radians(float(cfg.get("isoAzimuthDeg", 40.0)))
    el = math.radians(float(cfg.get("isoElevationDeg", 30.0)))
    dist = float(cfg.get("distance", 3.0))
    zoff = float(cfg.get("isoZOffset", 0.35))
    lookAtZ = float(cfg.get("lookAtZ", 0.75))
    # same as homm3_pose_camera.setup_pose_camera iso case
    r = dist * math.cos(el)
    x = -r * math.sin(az)
    y = -r * math.cos(az)
    z = dist * math.sin(el) + zoff
    cam_loc = np.array([x, y, z], dtype=np.float64)
    target = np.array([0.0, 0.0, lookAtZ], dtype=np.float64)
    forward = target - cam_loc
    forward = forward / np.linalg.norm(forward)
    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    right = np.cross(forward, world_up)
    if np.linalg.norm(right) < 1e-8:
        right = np.array([1.0, 0.0, 0.0])
    else:
        right = right / np.linalg.norm(right)
    up = np.cross(right, forward)
    up = up / np.linalg.norm(up)
    # For iso, camera looks down -Z, so forward is -Z in camera space, as before
    # right/up/forward as computed are world vectors for camera local axes
    return {"cam_loc": cam_loc, "right": right, "up": up, "forward": forward}

def build_torch_buffers(glb_path: Path, cat_path: Path, device: str = "cuda"):
    data = load_glb_mesh_and_skin(glb_path)
    verts_raw = data["verts_raw_glTF"]
    verts_bl = gltf_to_blender_pos(verts_raw).astype(np.float32)
    faces = data["faces"]
    joints = data["joints"]
    weights = data["weights"]
    skin_joints = data["skin_joints"]
    cat, rest_handles, names = load_handle_catalog(cat_path)
    handle_indices = build_handle_index_map(skin_joints, joints, len(names))
    # Convert to torch
    dev = torch.device(device if torch.cuda.is_available() and device == "cuda" else "cpu")
    verts_t = torch.from_numpy(verts_bl).to(dev)  # N,3
    faces_t = torch.from_numpy(faces).to(dev)  # not needed on GPU for raster maybe
    rest_t = torch.from_numpy(rest_handles.astype(np.float32)).to(dev)  # H,3
    handle_idx_t = torch.from_numpy(handle_indices).to(dev)  # N,4
    weights_t = torch.from_numpy(weights).to(dev)  # N,4
    return {
        "verts": verts_t,
        "faces": faces,  # keep numpy for cv2
        "faces_t": faces_t,
        "rest_handles": rest_t,
        "handle_indices": handle_idx_t,
        "weights": weights_t,
        "names": names,
        "verts_np": verts_bl,
        "handle_indices_np": handle_indices,
        "weights_np": weights,
        "rest_handles_np": rest_handles,
        "device": dev,
        "cat": cat,
    }

def euler_xyz_to_matrix_torch(rx, ry, rz):
    # Use scipy-like? We'll implement via torch using same convention as Blender's Euler XYZ
    # Blender Euler XYZ order corresponds to rotation matrix = Rz * Ry * Rx (extrinsic XYZ or intrinsic ZYX?)
    # We'll approximate with torch's euler: R = Rz @ Ry @ Rx (each axis)
    # Compute individual matrices
    # Could also use formula: simpler to use rotation libraries.
    # For now implement via decompose:
    # Rx
    cx = torch.cos(rx); sx = torch.sin(rx)
    cy = torch.cos(ry); sy = torch.sin(ry)
    cz = torch.cos(rz); sz = torch.sin(rz)
    # Compute combined as in Blender: XYZ euler means rotate around X, then Y, then Z (in that order) with each local?
    # Common formula for Euler XYZ (intrinsic) -> matrix = Rz * Ry * Rx
    # Let's use that.
    # Rx
    # For batch, rx shape (H,)
    # Build 3x3 per handle
    # We'll handle vectorized
    H = rx.shape[0]
    R = torch.zeros((H, 3, 3), device=rx.device, dtype=rx.dtype)
    # Compute components
    # Use formula for ZYX? Let's derive ZYX for XYZ intrinsic
    # Matrix = Rz * Ry * Rx
    #  | cy*cz, -cy*sz, sy |
    # etc not trivial. Use sequential multiplication.
    # Build Rx, Ry, Rz
    Rx = torch.zeros((H, 3, 3), device=rx.device, dtype=rx.dtype)
    Rx[:, 0, 0] = 1
    Rx[:, 1, 1] = cx
    Rx[:, 1, 2] = -sx
    Rx[:, 2, 1] = sx
    Rx[:, 2, 2] = cx
    Ry = torch.zeros((H, 3, 3), device=rx.device, dtype=rx.dtype)
    Ry[:, 1, 1] = 1
    Ry[:, 0, 0] = cy
    Ry[:, 0, 2] = sy
    Ry[:, 2, 0] = -sy
    Ry[:, 2, 2] = cy
    Rz = torch.zeros((H, 3, 3), device=rx.device, dtype=rx.dtype)
    Rz[:, 2, 2] = 1
    Rz[:, 0, 0] = cz
    Rz[:, 0, 1] = -sz
    Rz[:, 1, 0] = sz
    Rz[:, 1, 1] = cz
    # Combine: R = Rz @ Ry @ Rx
    R = torch.bmm(torch.bmm(Rz, Ry), Rx)
    return R

def deform_torch(verts: torch.Tensor, rest_handles: torch.Tensor, handle_indices: torch.Tensor, weights: torch.Tensor, vec: torch.Tensor, basis: dict):
    """
    verts: N,3
    rest_handles: H,3
    handle_indices: N,4
    weights: N,4
    vec: (H*6,)  [u,v,d,rx,ry,rz] per handle along basis
    basis: dict with right,up,forward (3,) numpy
    Returns deformed verts N,3
    """
    H = rest_handles.shape[0]
    N = verts.shape[0]
    device = verts.device
    dtype = verts.dtype
    # Parse vec
    if isinstance(vec, np.ndarray):
        vec = torch.from_numpy(vec.astype(np.float32)).to(device)
    vec = vec.reshape(H, 6)
    u = vec[:, 0]; v = vec[:, 1]; d = vec[:, 2]
    rx = vec[:, 3]; ry = vec[:, 4]; rz = vec[:, 5]
    # Basis vectors
    right = torch.tensor(basis["right"], device=device, dtype=dtype)
    up = torch.tensor(basis["up"], device=device, dtype=dtype)
    forward = torch.tensor(basis["forward"], device=device, dtype=dtype)
    # Handle translations T = right*u + up*v + forward*d
    # shape H,3
    T = right[None, :] * u[:, None] + up[None, :] * v[:, None] + forward[None, :] * d[:, None]
    # Rotations
    R = euler_xyz_to_matrix_torch(rx, ry, rz)  # H,3,3
    # Compute diff = verts - p_handle for each influence
    # verts: N,3 ; rest_handles: H,3
    # Need to gather per influence
    # We can compute all combos: verts_exp N, H,3
    # But to save mem, do per-influence loops? N=6972 H=48 => 334k*3 ~1M, fine
    # Expand
    verts_exp = verts.unsqueeze(1)  # N,1,3
    rest_exp = rest_handles.unsqueeze(0)  # 1,H,3
    diff = verts_exp - rest_exp  # N,H,3
    # Rotate diff: diff_rot = diff @ R^T  (since R * (v-p) as column)
    # diff shape N,H,3, R H,3,3
    # Use einsum: diff_rot[n,h,j] = sum_k diff[n,h,k] * R[h,k,j]  (if R is row-major)
    # Need to verify: column vector multiplication: R * diff_col => (R @ diff)
    # If diff is row, then diff_rot = diff @ R^T
    # We'll use einsum with transpose
    diff_rot = torch.einsum('nhk,hkj->nhj', diff, R)  # R is hk j? Actually R[h,k,j] is row k col j? Our R is standard.
    # But we built R as matrix acting on column vectors: R_col = R @ diff_col. If diff is row, diff @ R.T = (R @ diff.T).T
    # So need R transpose: diff @ R^T
    # Our einsum 'nhk,hkj->nhj' does diff @ R (not transposed). We need 'nhk,hjk->nhj'
    # Let's adjust: we want diff_rot = diff @ R.T  => diff[k] * R^T[k,j] = diff[k]*R[j,k] => einsum 'nhk,hjk->nhj' where R[h,j,k] is R^T?
    # Simpler: we defined R as Rz @ Ry @ Rx (column). Using diff @ R.T:
    R_T = R.transpose(1, 2)
    diff_rot = torch.einsum('nhk,hkj->nhj', diff, R_T)
    vt = diff_rot + rest_exp + T.unsqueeze(0)  # N,H,3
    # Now blend using weights
    # Gather 4 handles per vert
    # handle_indices: N,4
    # We have vt: N,H,3
    # For each vert n, k in 0..3, hi = handle_indices[n,k], w=weights[n,k]
    N_idx = torch.arange(N, device=device).unsqueeze(1).expand(-1, 4)  # N,4
    # Need to clamp hi -1 (ROOT) -> zero weight? We'll zero contributions for -1
    hi_clamped = torch.clamp(handle_indices, min=0)
    # gathered: N,4,3
    gathered = vt[N_idx, hi_clamped]  # advanced indexing
    # Zero where handle_indices == -1
    mask = (handle_indices >= 0).float().unsqueeze(-1)  # N,4,1
    gathered = gathered * mask
    w = weights.unsqueeze(-1)  # N,4,1
    deformed = (gathered * w).sum(dim=1)  # N,3
    return deformed

def deform_numpy(verts_np: np.ndarray, rest_handles_np: np.ndarray, handle_indices_np: np.ndarray, weights_np: np.ndarray, vec_np: np.ndarray, basis: dict):
    # For validation, use numpy + scipy rotation
    from scipy.spatial.transform import Rotation as R
    H = rest_handles_np.shape[0]
    N = verts_np.shape[0]
    vec = vec_np.reshape(H, 6)
    right = np.array(basis["right"])
    up = np.array(basis["up"])
    forward = np.array(basis["forward"])
    T = right * vec[:, 0, None] + up * vec[:, 1, None] + forward * vec[:, 2, None]  # H,3
    # rotations
    R_mats = np.zeros((H, 3, 3))
    for i in range(H):
        rx, ry, rz = vec[i, 3], vec[i, 4], vec[i, 5]
        # Use same order as torch: Rz*Ry*Rx
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
        R_mats[i] = Rz @ Ry @ Rx
    deformed = np.zeros_like(verts_np)
    for vi in range(N):
        acc = np.zeros(3)
        v = verts_np[vi]
        for k in range(4):
            hi = int(handle_indices_np[vi, k])
            w = float(weights_np[vi, k])
            if hi < 0 or w == 0:
                continue
            p = rest_handles_np[hi]
            Rm = R_mats[hi]
            tt = T[hi]
            vt = Rm @ (v - p) + p + tt
            acc += w * vt
        deformed[vi] = acc
    return deformed

def project_ortho(verts: np.ndarray, cam: dict, W: int, H: int):
    """
    Ortho projection using right/up/forward basis.
    verts: N,3 world (Blender Z-up)
    cam: dict with cam_loc, right, up, forward, ortho
    Returns 2D points N,2 pixel coords (float)
    """
    cam_loc = cam["cam_loc"]
    right = cam["right"]
    up = cam["up"]
    # forward not needed for 2D
    ortho = cam["ortho"]
    rel = verts - cam_loc[None, :]
    xc = rel @ right
    yc = rel @ up
    aspect = H / float(W)
    px = (xc / ortho + 0.5) * W
    py = (-yc / (ortho * aspect) + 0.5) * H
    return np.stack([px, py], axis=1)

def project_ortho_torch(verts: torch.Tensor, cam: dict, W: int, H: int):
    cam_loc = torch.tensor(cam["cam_loc"], device=verts.device, dtype=verts.dtype)
    right = torch.tensor(cam["right"], device=verts.device, dtype=verts.dtype)
    up = torch.tensor(cam["up"], device=verts.device, dtype=verts.dtype)
    ortho = float(cam["ortho"])
    aspect = H / float(W)
    rel = verts - cam_loc[None, :]
    xc = rel @ right
    yc = rel @ up
    px = (xc / ortho + 0.5) * W
    py = (-yc / (ortho * aspect) + 0.5) * H
    pts = torch.stack([px, py], dim=1)
    return pts

def rasterize_cv2(points_2d: np.ndarray, faces: np.ndarray, H: int, W: int):
    import cv2
    mask = np.zeros((H, W), dtype=np.uint8)
    pts_i = np.round(points_2d).astype(np.int32)
    # cv2.fillPoly robust: filter degenerate tris that are empty
    tris = []
    for f in faces:
        tri = pts_i[f]
        if tri.shape[0] != 3:
            continue
        # skip if tri area zero or completely out of bounds? Let cv2 clip.
        tris.append(tri)
    if tris:
        cv2.fillPoly(mask, tris, 1)
    return mask.astype(np.float32)

def rasterize_cv2_batched(points_batch: np.ndarray, faces: np.ndarray, H: int, W: int):
    # points_batch: B,N,2
    import cv2
    B = points_batch.shape[0]
    masks = np.zeros((B, H, W), dtype=np.float32)
    for b in range(B):
        pts = np.round(points_batch[b]).astype(np.int32)
        mask = np.zeros((H, W), dtype=np.uint8)
        tris = [pts[f] for f in faces if pts[f].shape[0]==3]
        if tris:
            cv2.fillPoly(mask, tris, 1)
        masks[b] = mask.astype(np.float32)
    return masks

def alpha_loss(pred: np.ndarray, target: np.ndarray):
    inter = np.minimum(pred, target).sum()
    union = np.maximum(pred, target).sum() + 1e-6
    iou = float(inter / union)
    l2 = float(np.mean((pred - target) ** 2))
    return (1.0 - iou) + 0.25 * l2, iou

def sobel_edges(mask: np.ndarray):
    m = mask.astype(np.float32)
    try:
        from scipy.ndimage import sobel
        gx = sobel(m, axis=1)
        gy = sobel(m, axis=0)
    except Exception:
        kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
        ky = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)
        from numpy.lib.stride_tricks import sliding_window_view
        def conv2(img, k):
            p = np.pad(img, 1, mode="edge")
            win = sliding_window_view(p, (3, 3))
            return (win * k).sum(axis=(-2, -1))
        gx = conv2(m, kx)
        gy = conv2(m, ky)
    mag = np.sqrt(gx * gx + gy * gy)
    mx = float(mag.max())
    if mx > 1e-8:
        mag = mag / mx
    return mag.astype(np.float32)

def edge_loss(pred: np.ndarray, target_edge: np.ndarray):
    pe = sobel_edges(pred)
    return float(np.mean(np.abs(pe - target_edge)))

def dt_loss(pred: np.ndarray, target: np.ndarray, dt_target: np.ndarray | None = None):
    from scipy.ndimage import distance_transform_edt
    p = (pred > 0.5).astype(np.uint8)
    t = (target > 0.5).astype(np.uint8)
    if p.sum() == 0 or t.sum() == 0:
        return 1.0
    if dt_target is None:
        dt_t = distance_transform_edt(1 - t)
    else:
        dt_t = dt_target
    dt_p = distance_transform_edt(1 - p)
    a = float((dt_t * p).sum() / (p.sum() + 1e-6))
    b = float((dt_p * t).sum() / (t.sum() + 1e-6))
    diag = float(np.hypot(*pred.shape))
    return (a + b) / max(1.0, diag)

def precompute_dt_edges(targets: list[np.ndarray]):
    from scipy.ndimage import distance_transform_edt
    dts = []
    edges = []
    for t in targets:
        dt = distance_transform_edt(1 - (t > 0.5).astype(np.uint8))
        dts.append(dt.astype(np.float32))
        edges.append(sobel_edges(t))
    return dts, edges
