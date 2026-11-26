"""Generalized GPU multi-view UV projector, PBR synthesizer & Hex/Lit Full-PBR baker.

Produces per unit under <work-dir>/<unit>/out/:
  - basecolor_albedo.png     : pure multi-view delighted PBR albedo (2048x2048, 24px gutter dilated)
  - normal.png               : clean tangent-space PBR normal (eroded inner micro-bump + raw normal, 24px dilated)
  - metallicgloss.png        : RGBA metallic+smoothness map tailored to archetype
  - basecolor_hexlit_pbr.png : yaw-invariant Full-PBR baked into diffuse _MainTex for Olden Era Hex/Lit

Usage:
  python tools/homm3_retexture_pbr/project_unit.py --unit h3_basilisk --work-dir <dir> --device cuda --parity-check
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree

DEFAULT_REBUILD_ROOT = Path("V:/scratch_claude/unit_rebuild")

PRIMARY_VIEWS = ["right", "left", "front", "top"]
SECONDARY_VIEWS = ["front_right_34", "rear_34", "bottom", "head_closeup"]
ALL_VIEWS = PRIMARY_VIEWS + SECONDARY_VIEWS
# Opt-in 3rd sheet (render_guides_unit.py --tertiary, paint-api --sheet tertiary, project --extra-views): four low
# (~-22 deg) views around the body, for robes/cloaks whose hem undersides and leg-side folds the 8 default views miss.
TERTIARY_VIEWS = ["low_front", "low_back", "low_front_left_34", "low_rear_right_34"]


def sheet_views(sheet: str) -> list[str]:
    return {"primary": PRIMARY_VIEWS, "secondary": SECONDARY_VIEWS, "tertiary": TERTIARY_VIEWS}[sheet]

CANONICAL_ARCHETYPES = (
    "generic_creature",
    "reptile_green",
    "armored_metal",
    "chitin_insect",
    "leather_cloth",
    "bone_stone",
    "ethereal_glow",
)

ARCHETYPE_ALIASES = {
    "reptile": "reptile_green",
    "gnoll_metal": "armored_metal",
    "gorgon_armor": "armored_metal",
    "fly_insect": "chitin_insect",
    "lizard_archer": "leather_cloth",
    "wyvern": "leather_cloth",
    "hydra": "leather_cloth",
}

DEFAULT_UNIT_ARCHETYPE = {
    "h3_basilisk": "reptile_green",
    "h3_greater_basilisk": "reptile_green",
    "h3_basilisk_flamespitter": "reptile_green",
    "h3_gnoll": "armored_metal",
    "h3_gnoll_marauder": "armored_metal",
    "h3_gnoll_shaman": "armored_metal",
    "h3_lizardman": "leather_cloth",
    "h3_lizard_warrior": "leather_cloth",
    "h3_lizard_assassin": "leather_cloth",
    "h3_serpent_fly": "chitin_insect",
    "h3_dragon_fly": "chitin_insect",
    "h3_damsel_fly": "chitin_insect",
    "h3_gorgon": "armored_metal",
    "h3_mighty_gorgon": "armored_metal",
    "h3_corrosive_gorgon": "armored_metal",
    "h3_wyvern": "leather_cloth",
    "h3_wyvern_monarch": "leather_cloth",
    "h3_paokai": "leather_cloth",
    "h3_hydra": "leather_cloth",
    "h3_chaos_hydra": "leather_cloth",
    "h3_ruinous_hydra": "leather_cloth",
}


def resolve_archetype(name: str, unit: str) -> str:
    raw = (name or "").strip() or DEFAULT_UNIT_ARCHETYPE.get(unit, "generic_creature")
    canon = ARCHETYPE_ALIASES.get(raw, raw)
    if canon not in CANONICAL_ARCHETYPES:
        raise ValueError(f"Unknown archetype {raw!r}; expected one of {CANONICAL_ARCHETYPES} (or legacy alias)")
    return canon


def resolve_device(name: str) -> torch.device:
    if name == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA requested (--device cuda) but torch.cuda.is_available() is False")
        return torch.device("cuda")
    if name == "cpu":
        return torch.device("cpu")
    raise ValueError(f"Unsupported device: {name}")


def srgb_to_linear_t(x: torch.Tensor) -> torch.Tensor:
    return torch.where(x <= 0.04045, x / 12.92, ((x.clamp_min(0.0) + 0.055) / 1.055) ** 2.4)


def linear_to_srgb_t(x: torch.Tensor) -> torch.Tensor:
    x = x.clamp(0.0, 1.0)
    return torch.where(x <= 0.0031308, x * 12.92, 1.055 * x.clamp_min(1e-12) ** (1.0 / 2.4) - 0.055)


def rasterize_uv_buffers(
    eval_npz: Path, uv_res: int, dev: torch.device
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Deterministic CUDA/CPU UV rasterizer returning (pos, nrm, tan, bitan, mask) with giant-seam outlier filter."""
    d = np.load(eval_npz)
    verts = torch.from_numpy(d["verts"]).to(dev)
    tris = torch.from_numpy(d["tris"]).to(dev).long()
    uvs = torch.from_numpy(d["uvs"]).to(dev)
    lnorms = torch.from_numpy(d["lnorms"]).to(dev)

    vpos = verts[tris]  # (F, 3, 3)
    svol = float((vpos[:, 0] * torch.cross(vpos[:, 1], vpos[:, 2], dim=-1)).sum().item() / 6.0)
    if svol < 0.0:
        print(f"  NOTE: negative signed mesh volume ({svol:.4f}); flipping inward loop normals")
        lnorms = -lnorms
    px = torch.stack([uvs[..., 0] * uv_res - 0.5, (1.0 - uvs[..., 1]) * uv_res - 0.5], dim=-1)

    x0, y0 = px[:, 0, 0], px[:, 0, 1]
    x1, y1 = px[:, 1, 0], px[:, 1, 1]
    x2, y2 = px[:, 2, 0], px[:, 2, 1]
    area_px = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)

    du1 = uvs[:, 1] - uvs[:, 0]
    du2 = uvs[:, 2] - uvs[:, 0]
    uv_area = 0.5 * torch.abs(du1[:, 0] * du2[:, 1] - du1[:, 1] * du2[:, 0])
    e1 = vpos[:, 1] - vpos[:, 0]
    e2 = vpos[:, 2] - vpos[:, 0]
    area_3d = 0.5 * torch.linalg.norm(torch.cross(e1, e2, dim=-1), dim=-1).clamp_min(1e-10)
    valid_a = uv_area > 1e-10
    med_ratio = torch.median(uv_area[valid_a] / area_3d[valid_a]) if valid_a.any() else torch.tensor(1.0, device=dev)
    e_uv = torch.linalg.norm(uvs[:, [1, 2, 0]] - uvs, dim=-1).max(dim=-1).values
    is_giant = ((uv_area > 0.0004) & (uv_area > 20.0 * med_ratio * area_3d)) | (e_uv > 0.14)

    denom = du1[:, 0] * du2[:, 1] - du2[:, 0] * du1[:, 1]
    inv_d = torch.where(denom.abs() > 1e-12, 1.0 / denom, torch.zeros_like(denom))
    tri_t = F.normalize((du2[:, 1:2] * e1 - du1[:, 1:2] * e2) * inv_d[:, None], dim=-1, eps=1e-8)
    tri_b = F.normalize((-du2[:, 0:1] * e1 + du1[:, 0:1] * e2) * inv_d[:, None], dim=-1, eps=1e-8)

    valid_tri = (area_px.abs() > 1e-6) & (~is_giant)
    cmin = torch.floor(px[valid_tri, :, 0].min(dim=1).values).long().clamp(0, uv_res - 1)
    cmax = torch.ceil(px[valid_tri, :, 0].max(dim=1).values).long().clamp(0, uv_res - 1)
    rmin = torch.floor(px[valid_tri, :, 1].min(dim=1).values).long().clamp(0, uv_res - 1)
    rmax = torch.ceil(px[valid_tri, :, 1].max(dim=1).values).long().clamp(0, uv_res - 1)
    tri_ids = torch.nonzero(valid_tri, as_tuple=False).squeeze(1)

    uv_pos = torch.zeros((uv_res * uv_res, 3), dtype=torch.float32, device=dev)
    uv_nrm = torch.zeros((uv_res * uv_res, 3), dtype=torch.float32, device=dev)
    uv_tan = torch.zeros((uv_res * uv_res, 3), dtype=torch.float32, device=dev)
    uv_bit = torch.zeros((uv_res * uv_res, 3), dtype=torch.float32, device=dev)
    uv_mask = torch.zeros((uv_res * uv_res,), dtype=torch.bool, device=dev)
    best_score = torch.full((uv_res * uv_res,), -10.0, dtype=torch.float32, device=dev)

    w_box = (cmax - cmin + 1).clamp_min(1)
    h_box = (rmax - rmin + 1).clamp_min(1)
    n_pix = w_box * h_box
    total_tris = len(tris)

    cand_records = []
    chunk_tris = 4096
    for s in range(0, len(tri_ids), chunk_tris):
        e = min(s + chunk_tris, len(tri_ids))
        ti = tri_ids[s:e]
        wb = w_box[s:e]
        npix_c = n_pix[s:e]
        t_rep = torch.repeat_interleave(ti, npix_c)
        offs_base = torch.cumsum(npix_c, dim=0) - npix_c
        local_idx = torch.arange(int(npix_c.sum().item()), device=dev) - torch.repeat_interleave(offs_base, npix_c)
        wb_rep = torch.repeat_interleave(wb, npix_c)
        rr = torch.repeat_interleave(rmin[s:e], npix_c) + torch.div(local_idx, wb_rep, rounding_mode="floor")
        cc = torch.repeat_interleave(cmin[s:e], npix_c) + (local_idx % wb_rep)

        fc = cc.float()
        fr = rr.float()
        tx0, ty0 = x0[t_rep], y0[t_rep]
        tx1, ty1 = x1[t_rep], y1[t_rep]
        tx2, ty2 = x2[t_rep], y2[t_rep]
        inv_a = 1.0 / area_px[t_rep]

        w0 = ((tx1 - fc) * (ty2 - fr) - (tx2 - fc) * (ty1 - fr)) * inv_a
        w1 = ((tx2 - fc) * (ty0 - fr) - (tx0 - fc) * (ty2 - fr)) * inv_a
        w2 = 1.0 - w0 - w1

        inside = (w0 >= -2e-4) & (w1 >= -2e-4) & (w2 >= -2e-4)
        if not inside.any():
            continue

        t_in = t_rep[inside]
        lin = rr[inside] * uv_res + cc[inside]
        bw = torch.stack([w0[inside], w1[inside], w2[inside]], dim=1)
        min_b = bw.min(dim=1).values
        score = torch.round(min_b * 1000.0) + (t_in.float() + 1.0) / float(total_tris + 2)
        best_score.scatter_reduce_(0, lin, score, reduce="amax", include_self=True)

        bw_c = bw.clamp(0.0, 1.0)
        bw_c = bw_c / bw_c.sum(dim=1, keepdim=True).clamp_min(1e-8)
        cand_records.append((lin, t_in, bw_c, score))

    for lin, t_in, bw_c, score in cand_records:
        win = score >= best_score[lin] - 1e-7
        if not win.any():
            continue
        lin_w = lin[win]
        t_w = t_in[win]
        bw_w = bw_c[win]
        nrm_v = F.normalize((bw_w.unsqueeze(-1) * lnorms[t_w]).sum(dim=1), dim=-1, eps=1e-8)
        t_proj = tri_t[t_w] - (tri_t[t_w] * nrm_v).sum(dim=-1, keepdim=True) * nrm_v
        t_orth = F.normalize(t_proj, dim=-1, eps=1e-8)
        b_proj = tri_b[t_w] - (tri_b[t_w] * nrm_v).sum(dim=-1, keepdim=True) * nrm_v
        b_orth = F.normalize(b_proj, dim=-1, eps=1e-8)
        uv_pos[lin_w] = (bw_w.unsqueeze(-1) * vpos[t_w]).sum(dim=1)
        uv_nrm[lin_w] = nrm_v
        uv_tan[lin_w] = t_orth
        uv_bit[lin_w] = b_orth
        uv_mask[lin_w] = True

    return (
        uv_pos.view(uv_res, uv_res, 3),
        uv_nrm.view(uv_res, uv_res, 3),
        uv_tan.view(uv_res, uv_res, 3),
        uv_bit.view(uv_res, uv_res, 3),
        uv_mask.view(uv_res, uv_res),
    )


def extract_panels(sheet_path: Path, view_names: list[str], view_res: int) -> dict[str, np.ndarray]:
    im = Image.open(sheet_path).convert("RGB")
    target = (view_res * 2, view_res * 2)
    if im.size != target:
        im = im.resize(target, Image.Resampling.LANCZOS)
    arr = np.array(im, dtype=np.uint8)
    out = {}
    for i, vn in enumerate(view_names):
        r0 = (i // 2) * view_res
        c0 = (i % 2) * view_res
        out[vn] = arr[r0:r0 + view_res, c0:c0 + view_res].copy()
    return out


def _fill_solid_interior_holes(mask: np.ndarray, ref_bin: np.ndarray) -> np.ndarray:
    """Fill tiny interior paint specks without filling real background gaps enclosed by limbs/tentacles."""
    filled = ndimage.binary_fill_holes(mask > 0)
    holes = filled & ~(mask > 0)
    out = (mask > 0).copy()
    if holes.any():
        num_labels, labels = cv2.connectedComponents(holes.astype(np.uint8))
        for lbl in range(1, num_labels):
            comp = labels == lbl
            if int((comp & (ref_bin > 0)).sum()) >= 0.70 * int(comp.sum()):
                out |= comp
    return out.astype(np.uint8)


def register_panel_to_alpha(panel_rgb: np.ndarray, alpha_ref: np.ndarray, view_name: str) -> tuple[np.ndarray, np.ndarray, dict]:
    h, w = alpha_ref.shape
    ref_bin = (alpha_ref > 0.5).astype(np.uint8)
    border = np.concatenate([
        panel_rgb[:12, :].reshape(-1, 3),
        panel_rgb[-12:, :].reshape(-1, 3),
        panel_rgb[:, :12].reshape(-1, 3),
        panel_rgb[:, -12:].reshape(-1, 3),
    ], axis=0)
    bg_rgb = np.median(border.astype(np.float32), axis=0)

    diff = np.linalg.norm(panel_rgb.astype(np.float32) - bg_rgb[None, None, :], axis=-1)
    search_zone = cv2.dilate(ref_bin, np.ones((85, 85), np.uint8)) > 0
    fg = ((diff > 10.0) & search_zone).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    fg = _fill_solid_interior_holes(fg, ref_bin)

    iou_pre = float((fg & ref_bin).sum()) / float(max(1, (fg | ref_bin).sum()))
    if iou_pre >= 0.995:
        dist = cv2.distanceTransform(ref_bin, cv2.DIST_L2, 5)
        ramp = np.clip((dist - 1.5) / 5.5, 0.0, 1.0).astype(np.float32)
        return panel_rgb, ramp, {"iouPre": iou_pre, "iouPost": iou_pre, "method": "exact"}

    ys_g, xs_g = np.where(fg > 0)
    ys_r, xs_r = np.where(ref_bin > 0)
    if len(xs_g) < 100:
        raise RuntimeError(f"{view_name}: extracted foreground mask too small ({len(xs_g)} px)")

    gx0, gx1 = xs_g.min(), xs_g.max()
    gy0, gy1 = ys_g.min(), ys_g.max()
    rx0, rx1 = xs_r.min(), xs_r.max()
    ry0, ry1 = ys_r.min(), ys_r.max()
    gcx, gcy = 0.5 * (gx0 + gx1), 0.5 * (gy0 + gy1)
    rcx, rcy = 0.5 * (rx0 + rx1), 0.5 * (ry0 + ry1)
    sx = (rx1 - rx0 + 1) / max(1.0, (gx1 - gx0 + 1))
    sy = (ry1 - ry0 + 1) / max(1.0, (gy1 - gy0 + 1))
    s = 0.5 * (sx + sy)
    M0 = np.array([[s, 0.0, rcx - s * gcx], [0.0, s, rcy - s * gcy]], dtype=np.float32)
    M_inv = cv2.invertAffineTransform(M0)

    ref_blur = cv2.GaussianBlur(ref_bin.astype(np.float32), (9, 9), 2.5)
    fg_blur = cv2.GaussianBlur(fg.astype(np.float32), (9, 9), 2.5)
    try:
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 150, 1e-5)
        _, M_ecc_inv = cv2.findTransformECC(ref_blur, fg_blur, M_inv, cv2.MOTION_AFFINE, criteria)
        M_final = cv2.invertAffineTransform(M_ecc_inv)
        method = "bbox+ecc"
    except cv2.error:
        M_final = M0
        method = "bbox"

    warped_rgb = cv2.warpAffine(
        panel_rgb, M_final, (w, h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT,
        borderValue=tuple(int(x) for x in bg_rgb)
    )
    warped_fg = cv2.warpAffine(fg, M_final, (w, h), flags=cv2.INTER_NEAREST, borderValue=0) > 0
    warped_fg = _fill_solid_interior_holes(warped_fg, ref_bin) > 0
    iou_post = float((warped_fg & (ref_bin > 0)).sum()) / float(max(1, (warped_fg | (ref_bin > 0)).sum()))

    comb_mask = (ref_bin > 0) & warped_fg
    if comb_mask.sum() < 0.70 * ref_bin.sum():
        comb_mask = ref_bin > 0
    dist = cv2.distanceTransform(comb_mask.astype(np.uint8), cv2.DIST_L2, 5)
    ramp = np.clip((dist - 1.8) / 5.2, 0.0, 1.0).astype(np.float32)
    return warped_rgb, ramp, {"iouPre": round(iou_pre, 4), "iouPost": round(iou_post, 4), "method": method}


def gentle_delight_view(rgb_u8: np.ndarray, nrm: np.ndarray, alpha_ref: np.ndarray) -> np.ndarray:
    rgb = rgb_u8.astype(np.float32) / 255.0
    dirs = np.array([[0.51, -0.51, 0.70], [-0.61, 0.54, 0.54], [0.09, -0.28, -0.95]], dtype=np.float32)
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    weights = np.array([1.35, 1.15, 1.10], dtype=np.float32)
    irr = np.full(alpha_ref.shape, 0.85, dtype=np.float32)
    for d, wt in zip(dirs, weights):
        irr += wt * (0.45 * np.clip((nrm * d[None, None, :]).sum(axis=-1), 0.0, 1.0) + 0.15)
    fg = alpha_ref > 0.5
    med_irr = float(np.median(irr[fg])) if fg.any() else 1.0
    rel = np.clip(irr / max(med_irr, 1e-4), 0.72, 1.35)
    gain = np.where(fg, 1.0 / (1.0 + 0.42 * (rel - 1.0)), 1.0)
    gain = np.clip(gain, 0.80, 1.24)[..., None]
    return (np.clip(rgb * gain, 0.0, 1.0) * 255.0).round().astype(np.uint8)


def _fib_sphere_dirs(n: int) -> np.ndarray:
    i = np.arange(n, dtype=np.float64) + 0.5
    z = 1.0 - 2.0 * i / n
    r = np.sqrt(np.clip(1.0 - z * z, 0.0, 1.0))
    th = np.pi * (1.0 + 5.0 ** 0.5) * i
    return np.stack([r * np.cos(th), r * np.sin(th), z], -1).astype(np.float32)


def _ortho_zbuffer(img_xyz: torch.Tensor, tris: torch.Tensor, res: int) -> torch.Tensor:
    """Nearest-depth buffer of a triangle mesh already in image space (x px, y px, depth; smaller = nearer)."""
    dev = img_xyz.device
    p = img_xyz[tris]
    x0, y0, x1, y1, x2, y2 = p[:, 0, 0], p[:, 0, 1], p[:, 1, 0], p[:, 1, 1], p[:, 2, 0], p[:, 2, 1]
    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    cmin = torch.floor(p[:, :, 0].min(1).values).long().clamp(0, res - 1)
    cmax = torch.ceil(p[:, :, 0].max(1).values).long().clamp(0, res - 1)
    rmin = torch.floor(p[:, :, 1].min(1).values).long().clamp(0, res - 1)
    rmax = torch.ceil(p[:, :, 1].max(1).values).long().clamp(0, res - 1)
    ids = torch.nonzero(area.abs() > 1e-9).squeeze(1)
    zb = torch.full((res * res,), 1e6, dtype=torch.float32, device=dev)
    for s in range(0, len(ids), 8192):
        ti = ids[s:s + 8192]
        wb = (cmax[ti] - cmin[ti] + 1).clamp_min(1)
        n = wb * (rmax[ti] - rmin[ti] + 1).clamp_min(1)
        t = torch.repeat_interleave(ti, n)
        li = torch.arange(int(n.sum().item()), device=dev) - torch.repeat_interleave(torch.cumsum(n, 0) - n, n)
        wr = torch.repeat_interleave(wb, n)
        rr = torch.repeat_interleave(rmin[ti], n) + torch.div(li, wr, rounding_mode="floor")
        cc = torch.repeat_interleave(cmin[ti], n) + li % wr
        fc, fr = cc.float() + 0.5, rr.float() + 0.5
        ia = 1.0 / area[t]
        w0 = ((x1[t] - fc) * (y2[t] - fr) - (x2[t] - fc) * (y1[t] - fr)) * ia
        w1 = ((x2[t] - fc) * (y0[t] - fr) - (x0[t] - fc) * (y2[t] - fr)) * ia
        w2 = 1.0 - w0 - w1
        ins = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not ins.any():
            continue
        t = t[ins]
        z = w0[ins] * p[t, 0, 2] + w1[ins] * p[t, 1, 2] + w2[ins] * p[t, 2, 2]
        zb.scatter_reduce_(0, rr[ins] * res + cc[ins], z, reduce="amin", include_self=True)
    return zb.view(res, res)


def visible_surface_mask(
    eval_npz: Path, pos_v: torch.Tensor, nrm_v: torch.Tensor, n_dirs: int = 96, min_dirs: int = 3,
    res: int = 1024, tol: float = 0.055, fix: "ProjFix | None" = None,
) -> torch.Tensor:
    """Opt-in (--coverage-over-visible): texels whose surface point is seen from at least ``min_dirs`` of ``n_dirs``
    outside directions (Fibonacci sphere, orthographic z-buffer of the eval mesh with back faces culled as in game,
    same 0.055 depth tolerance as the projection). Texels no direction sees are interior / enclosed surfaces (robe
    insides, densify leftovers, faces buried behind other geometry); texels seen from only 1-2 of 96 directions are
    slot/pinhole surfaces between cloth strips. Neither can carry projected paint from any sane guide set, and the
    KNN fill below colours them from their projected neighbours, so they should not count against coverage."""
    dev = pos_v.device
    d = np.load(eval_npz)
    verts = torch.from_numpy(d["verts"]).to(dev)
    tris = torch.from_numpy(d["tris"]).to(dev).long()
    vmin, vmax = verts.min(0).values, verts.max(0).values
    center = 0.5 * (vmin + vmax)
    ext = float((vmax - vmin).max().item())
    oscale = ext * 1.16
    vp = verts[tris]
    face_n = torch.cross(vp[:, 1] - vp[:, 0], vp[:, 2] - vp[:, 0], dim=-1)
    seen = torch.zeros(len(pos_v), dtype=torch.int32, device=dev)
    for dv in _fib_sphere_dirs(n_dirs):
        zax = dv / np.linalg.norm(dv)
        up = np.array([0.0, 0.0, 1.0], np.float32) if abs(zax[2]) < 0.95 else np.array([0.0, 1.0, 0.0], np.float32)
        xax = np.cross(up, zax)
        xax /= np.linalg.norm(xax)
        rot = torch.from_numpy(np.stack([xax, np.cross(zax, xax), zax]).astype(np.float32)).to(dev)

        def to_img(pts: torch.Tensor) -> torch.Tensor:
            pc = (pts - center) @ rot.T
            return torch.stack([(pc[:, 0] / oscale + 0.5) * res, (0.5 - pc[:, 1] / oscale) * res, -pc[:, 2]], -1)

        zb = _ortho_zbuffer(to_img(verts), tris[(face_n @ rot[2]) > 0], res)
        zmin3 = -F.max_pool2d(-zb[None, None], 3, 1, 1)[0, 0]
        tc = to_img(pos_v)
        zs = zmin3[tc[:, 1].long().clamp(0, res - 1), tc[:, 0].long().clamp(0, res - 1)]
        ndv = nrm_v @ rot[2]
        tol_v = tol
        if fix is not None:  # same slope-aware, pixel-scaled tolerance as the --proj-fix projection
            tol_v = (oscale / res * (fix.tol_px + fix.nbr_slope * _tan_from_ndotv(ndv))).clamp_max(fix.tol_cap)
        seen += ((ndv > 0.05) & (tc[:, 2] <= zs + tol_v)).int()
    return seen >= min_dirs


@dataclass(frozen=True)
class ProjFix:
    """Opt-in (--proj-fix) visibility/weighting fix for the two projection defects seen on h3_marksman:

    * occlusion bleed: the absolute 0.055 depth tolerance is ~28 px at a 1024 view of a 1.7-unit-tall mesh, so thin
      parts (visors, straps, quivers, shields, wings) in front of other parts took the occluded surface's paint and
      vice versa. The tolerance is now a per-view, per-texel slope-aware bound in that view's pixel size
      px = orthoScale / viewRes:  tol = px * (tol_px + tol_slope * tan(theta))  (tan from n.v, never looser than
      0.055); the 3x3 z_min test uses px * (tol_px + nbr_slope * tan) (neighbour pixels sit up to ~1.5 px away);
      and texels near interior depth discontinuities (jump > edge_jump_px * px between adjacent pixels) are
      down-weighted by a ramp (floor edge_floor), like the existing silhouette ramp, so a clean view wins there.
    * grazing streaks: a texel whose BEST visible view has n.v < graze_lo keeps no projected colour (counted as
      uncovered; the KNN fill colours it from texels whose best n.v >= graze_hi); between graze_lo and graze_hi the
      projected colour is blended toward that fill. Per-view facing cut raised from 0.14 to facing_min.
    """
    tol_px: float = 1.5
    tol_slope: float = 1.0
    nbr_slope: float = 2.2
    tol_cap: float = 0.055
    facing_min: float = 0.18
    edge_jump_px: float = 6.0
    edge_ramp_px: float = 2.5
    edge_floor: float = 0.08
    graze_lo: float = 0.25
    graze_hi: float = 0.40
    # coverage gate under --proj-fix (owner 2026-11-25): strict-visible surface >= 65% (+ a visual check of the
    # after board); the rejected texels are genuinely occluded / grazing-only and take the KNN fill
    min_visible_coverage: float = 65.0


DIAG_GRAZE = 0.35        # "grazing-only": covered texel whose best visible view has n.v below this
DIAG_EDGE_PX = 1.0       # "near an occlusion edge": within this many view pixels of an interior depth jump
DIAG_DISAGREE = 60.0     # sRGB (0-255) distance between the top-2 views' colours that counts as a seam/disagreement


def _tan_from_ndotv(ndotv: torch.Tensor) -> torch.Tensor:
    c = ndotv.clamp(0.12, 1.0)
    return torch.sqrt((1.0 - c * c).clamp_min(0.0)) / c


def occlusion_edge_dist(depth: np.ndarray, px: float, jump_px: float) -> np.ndarray:
    """Distance (view px) to the nearest interior depth discontinuity: adjacent valid pixels whose depth differs by
    more than jump_px * px (both sides are marked). Silhouette edges against the background are left to the
    registration ramp."""
    h, w = depth.shape
    thr = jump_px * px
    edge = np.zeros((h, w), bool)
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        y1, x0, x1 = h - dy, max(0, -dx), w - max(0, dx)
        a = depth[0:y1, x0:x1]
        b = depth[dy:y1 + dy, x0 + dx:x1 + dx]
        e = (a > 0) & (b > 0) & (np.abs(a - b) > thr)
        edge[0:y1, x0:x1] |= e
        edge[dy:y1 + dy, x0 + dx:x1 + dx] |= e
    if not edge.any():
        return np.full(depth.shape, 1e3, np.float32)
    return cv2.distanceTransform((~edge).astype(np.uint8), cv2.DIST_L2, 5).astype(np.float32)


def project_views_to_uv(
    uv_pos: torch.Tensor,
    uv_nrm: torch.Tensor,
    uv_mask: torch.Tensor,
    views_data: dict[str, dict],
    meta: dict,
    dev: torch.device,
    visible_eval_npz: Path | None = None,
    min_coverage: float = 75.0,
    fix: ProjFix | None = None,
    diag: dict | None = None,
    gate: bool = True,
    gate_visible: bool = True,
) -> tuple[torch.Tensor, torch.Tensor]:
    uv_res = uv_mask.shape[0]
    valid_idx = torch.nonzero(uv_mask, as_tuple=False)
    pos_v = uv_pos[valid_idx[:, 0], valid_idx[:, 1]]
    nrm_v = uv_nrm[valid_idx[:, 0], valid_idx[:, 1]]

    hc = torch.tensor(meta.get("headCenter", [0.0, -0.5, 1.2]), dtype=torch.float32, device=dev)
    h_rad = max(float(meta.get("headScale", 1.2)) * 0.65, 0.55)
    dist_head = torch.linalg.norm(pos_v - hc[None, :], dim=-1)
    head_zone = torch.clamp((h_rad - dist_head) / (0.35 * h_rad), 0.0, 1.0)

    fx = fix or ProjFix()
    want_edges = fix is not None or diag is not None
    per_view_samples = {}
    view_ndotv = {}
    diag_views = []
    for vn, vd in views_data.items():
        vm = meta["views"][vn]
        m_inv = torch.tensor(vm["worldToCam"], dtype=torch.float32, device=dev)
        cam_dir = torch.tensor(vm["camDir"], dtype=torch.float32, device=dev)
        view_vec = -cam_dir
        oscale = float(vm["orthoScale"])

        p_cam = (m_inv[:3, :3] @ pos_v.T).T + m_inv[:3, 3]
        z_uv = -p_cam[:, 2]
        u_img = p_cam[:, 0] / oscale + 0.5
        v_img = 0.5 - p_cam[:, 1] / oscale

        in_frame = (u_img > 0.01) & (u_img < 0.99) & (v_img > 0.01) & (v_img < 0.99) & (z_uv > 0.1)
        ndotv = (nrm_v * view_vec[None, :]).sum(dim=-1)
        facing = ndotv > 0.14

        depth_t = torch.from_numpy(vd["depth"]).to(dev).unsqueeze(0).unsqueeze(0)
        ramp_t = torch.from_numpy(vd["ramp"]).to(dev).unsqueeze(0).unsqueeze(0)
        rgb_srgb = torch.from_numpy(vd["rgb"].astype(np.float32) / 255.0).to(dev).permute(2, 0, 1).unsqueeze(0)
        rgb_lin_img = srgb_to_linear_t(rgb_srgb)

        grid = torch.stack([u_img * 2.0 - 1.0, v_img * 2.0 - 1.0], dim=-1).view(1, -1, 1, 2)
        z_buf = F.grid_sample(depth_t, grid, mode="nearest", padding_mode="border", align_corners=False).view(-1)
        z_valid = torch.where(depth_t > 0, depth_t, torch.full_like(depth_t, 1e6))
        z_min3 = -F.max_pool2d(-z_valid, kernel_size=3, stride=1, padding=1)
        z_min3_s = F.grid_sample(z_min3, grid, mode="nearest", padding_mode="border", align_corners=False).view(-1)
        ramp_s = F.grid_sample(ramp_t, grid, mode="bilinear", padding_mode="border", align_corners=False).view(-1)
        col_lin_s = F.grid_sample(rgb_lin_img, grid, mode="bilinear", padding_mode="border", align_corners=False)[0, :, :, 0].T

        visible = in_frame & facing & (z_buf > 0.0) & (torch.abs(z_uv - z_buf) <= 0.055) & (z_uv <= z_min3_s + 0.055) & (ramp_s > 0.02)

        # slope-aware depth tolerance in this view's pixel size (applied by --proj-fix; --diag uses it to flag bleed)
        px = oscale / float(vd["depth"].shape[0])
        tan_t = _tan_from_ndotv(ndotv)
        margin = torch.abs(z_uv - z_buf)
        tol_s = (px * (fx.tol_px + fx.tol_slope * tan_t)).clamp_max(fx.tol_cap)
        tol_n = (px * (fx.tol_px + fx.nbr_slope * tan_t)).clamp_max(fx.tol_cap)
        strict_ok = (margin <= tol_s) & (z_uv <= z_min3_s + tol_n)
        edge_mult = torch.ones_like(ndotv)
        edge_s = torch.full_like(ndotv, 1e3)
        if want_edges:
            if "edge_dist" not in vd:
                vd["edge_dist"] = occlusion_edge_dist(vd["depth"], px, fx.edge_jump_px)
            edge_t = torch.from_numpy(vd["edge_dist"]).to(dev).unsqueeze(0).unsqueeze(0)
            edge_s = F.grid_sample(edge_t, grid, mode="bilinear", padding_mode="border", align_corners=False).view(-1)
        if fix is not None:
            visible = in_frame & (ndotv > fx.facing_min) & (z_buf > 0.0) & strict_ok & (ramp_s > 0.02)
            edge_mult = fx.edge_floor + (1.0 - fx.edge_floor) * torch.clamp((edge_s - 0.5) / fx.edge_ramp_px, 0.0, 1.0)

        v_mult = torch.ones_like(ndotv)
        if vn == "head_closeup":
            v_mult = 0.25 + 2.75 * head_zone
        elif vn in ("front_right_34", "right", "left", "top"):
            v_mult = torch.full_like(ndotv, 1.15)

        wt = torch.where(visible, (ndotv.clamp_min(0.0) ** 4.0) * ramp_s * v_mult * edge_mult, torch.zeros_like(ndotv))
        per_view_samples[vn] = (col_lin_s, wt)
        view_ndotv[vn] = ndotv
        if diag is not None:
            # low-pass colour for the seam/disagreement metric (chainmail-scale texture would otherwise dominate)
            blur = F.avg_pool2d(rgb_lin_img, kernel_size=9, stride=1, padding=4, count_include_pad=False)
            col_blur = F.grid_sample(blur, grid, mode="bilinear", padding_mode="border", align_corners=False)[0, :, :, 0].T
            diag_views.append((vn, ndotv, strict_ok, edge_s < DIAG_EDGE_PX, margin / px, col_blur))

    anchor_num = torch.zeros((len(pos_v), 3), dtype=torch.float32, device=dev)
    anchor_den = torch.zeros((len(pos_v),), dtype=torch.float32, device=dev)
    for an in ("right", "front_right_34", "left", "top"):
        if an in per_view_samples:
            c, w = per_view_samples[an]
            anchor_num += c * w.unsqueeze(-1)
            anchor_den += w
    anchor_col = anchor_num / anchor_den.clamp_min(1e-8).unsqueeze(-1)
    has_anchor = anchor_den > 0.08
    for vn, (col, wt) in list(per_view_samples.items()):
        if vn in ("right", "front_right_34"):
            continue
        ov = has_anchor & (wt > 0.05) & (col.mean(dim=-1) > 0.02) & (anchor_col.mean(dim=-1) > 0.02)
        if int(ov.sum().item()) > 400:
            ratio = (anchor_col[ov].mean(dim=0) / col[ov].mean(dim=0).clamp_min(1e-4)).clamp(0.84, 1.18)
            per_view_samples[vn] = ((col * ratio[None, :]).clamp(0.0, 1.0), wt)

    accum_lin = torch.zeros((len(pos_v), 3), dtype=torch.float32, device=dev)
    accum_w = torch.zeros((len(pos_v),), dtype=torch.float32, device=dev)
    best_nv = torch.zeros((len(pos_v),), dtype=torch.float32, device=dev)
    for vn, (col, wt) in per_view_samples.items():
        accum_lin += col * wt.unsqueeze(-1)
        accum_w += wt
        best_nv = torch.maximum(best_nv, torch.where(wt > 0, view_ndotv[vn], torch.zeros_like(wt)))

    projected_any = accum_w > 1e-6
    projected = projected_any
    s_graze = projected_any.float()  # 1 = keep projected colour, 0 = KNN fill (repo behaviour without --proj-fix)
    if fix is not None:
        # grazing-only texels keep no projected colour: they count as uncovered and take the KNN fill below
        projected = projected_any & (best_nv >= fx.graze_lo)
        tg = torch.clamp((best_nv - fx.graze_lo) / max(fx.graze_hi - fx.graze_lo, 1e-6), 0.0, 1.0)
        s_graze = torch.where(projected, tg * tg * (3.0 - 2.0 * tg), torch.zeros_like(tg))
    cov = float(projected.float().mean().item()) * 100.0
    cov_any = float(projected_any.float().mean().item()) * 100.0
    if fix is not None:
        print(f"  Multi-view projected coverage: {cov:.2f}% ({int(projected.sum())}/{len(pos_v)}) "
              f"[--proj-fix; {cov_any:.2f}% before rejecting grazing-only texels, best n.v < {fx.graze_lo}]")
    else:
        print(f"  Multi-view projected coverage: {cov:.2f}% ({int(projected.sum())}/{len(pos_v)})")

    vis = None
    cov_vis = None
    vis_strict = None
    if visible_eval_npz is not None:
        vis = visible_surface_mask(visible_eval_npz, pos_v, nrm_v, fix=fix)
        if diag is not None:  # --diag rates bleed on the truly visible surface (strict tolerance) in both modes
            vis_strict = vis if fix is not None else visible_surface_mask(visible_eval_npz, pos_v, nrm_v, fix=fx)
        n_vis = max(int(vis.sum().item()), 1)
        cov_vis = 100.0 * float((projected & vis).sum().item()) / n_vis
        print(f"  Visible-surface coverage: {cov_vis:.2f}% ({int((projected & vis).sum())}/{n_vis}); "
              f"never-visible texels {100.0 * (1.0 - n_vis / len(pos_v)):.2f}% (--coverage-over-visible)")

    if diag is not None:
        _fill_diag(diag, diag_views, per_view_samples, projected_any, projected, best_nv, vis_strict, valid_idx, uv_res,
                   cov, cov_any, cov_vis, fix)

    if gate and fix is not None:
        assert cov_vis is not None, "--proj-fix gates on the strict-visible surface (needs the visible-surface mask)"
        assert cov_vis >= fx.min_visible_coverage, (
            f"Strict-visible coverage too low: {cov_vis:.2f}% < {fx.min_visible_coverage:.1f}% (--proj-fix)")
    elif gate:
        if cov_vis is not None and gate_visible:
            assert cov_vis >= min_coverage, f"Visible-surface coverage too low: {cov_vis:.2f}% < {min_coverage:.1f}%"
        else:
            assert cov >= min_coverage, f"Multi-view projected coverage too low: {cov:.2f}% < {min_coverage:.1f}%"

    res_lin = accum_lin / accum_w.clamp_min(1e-8).unsqueeze(-1)
    need_fill = (~projected) | (s_graze < 1.0)
    if bool(need_fill.any()):
        src_mask = projected
        if fix is not None:
            strong = projected & (best_nv >= fx.graze_hi)
            if int(strong.sum().item()) >= 1000:
                src_mask = strong
        miss_mask = need_fill
        pts_src = pos_v[src_mask].detach().cpu().numpy()
        nrm_src = nrm_v[src_mask].detach().cpu().numpy()
        col_src = res_lin[src_mask].detach().cpu().numpy()
        pts_q = pos_v[miss_mask].detach().cpu().numpy()
        nrm_q = nrm_v[miss_mask].detach().cpu().numpy()
        tree = cKDTree(pts_src)
        dists, idxs = tree.query(pts_q, k=12, workers=-1)
        dot_n = np.clip(0.5 + 0.5 * (nrm_q[:, None, :] * nrm_src[idxs]).sum(axis=-1), 0.05, 1.0) ** 2
        w_knn = dot_n / np.maximum(dists, 1e-4) ** 2
        w_knn /= w_knn.sum(axis=1, keepdims=True)
        fill_col = torch.from_numpy((w_knn[..., None] * col_src[idxs]).sum(axis=1).astype(np.float32)).to(dev)
        s_m = s_graze[miss_mask].unsqueeze(-1)
        res_lin[miss_mask] = torch.where(s_m > 0.0, s_m * res_lin[miss_mask] + (1.0 - s_m) * fill_col, fill_col)

    uv_lin = torch.zeros((uv_res, uv_res, 3), dtype=torch.float32, device=dev)
    uv_proj_mask = torch.zeros((uv_res, uv_res), dtype=torch.bool, device=dev)
    uv_lin[valid_idx[:, 0], valid_idx[:, 1]] = res_lin
    uv_proj_mask[valid_idx[:, 0], valid_idx[:, 1]] = projected
    return uv_lin, uv_proj_mask


def _fill_diag(diag, diag_views, per_view_samples, projected_any, projected, best_nv, vis, valid_idx, uv_res,
               cov, cov_any, cov_vis, fix) -> None:
    """--diag: per-texel maps (UV images) + per-unit summary. Percentages are of covered texels (any accepted view
    weight), so repo and --proj-fix runs compare on the same footing."""
    names = [d[0] for d in diag_views]
    W = torch.stack([per_view_samples[n][1] for n in names])                  # (V, N)
    SOK = torch.stack([d[2] for d in diag_views])
    NE = torch.stack([d[3] for d in diag_views])
    MG = torch.stack([d[4] for d in diag_views])
    wsum = W.sum(0)
    wmax, widx = W.max(0)
    n_contrib = ((W > 0) & (W >= 0.1 * wmax.unsqueeze(0))).sum(0)
    ar = torch.arange(W.shape[1], device=W.device)
    win_margin = MG[widx, ar]
    share_bad = (W * ((~SOK) | NE).float()).sum(0) / wsum.clamp_min(1e-12)
    cov_m = projected_any
    bleed = cov_m & (share_bad > 0.5)
    occl = cov_m & ((W * (~SOK).float()).sum(0) / wsum.clamp_min(1e-12) > 0.5)
    grazing = cov_m & (best_nv < DIAG_GRAZE)
    if W.shape[0] >= 2:
        top_v, top_i = W.topk(2, dim=0)
        c0 = torch.zeros((W.shape[1], 3), device=W.device)
        c1 = torch.zeros((W.shape[1], 3), device=W.device)
        for i, n in enumerate(names):
            col = diag_views[i][5]
            c0 = torch.where((top_i[0] == i).unsqueeze(-1), col, c0)
            c1 = torch.where((top_i[1] == i).unsqueeze(-1), col, c1)
        dcol = torch.linalg.norm(linear_to_srgb_t(c0) * 255.0 - linear_to_srgb_t(c1) * 255.0, dim=-1)
        two = cov_m & (top_v[1] > 0) & (top_v[1] >= 0.25 * top_v[0])
        disagree = two & (dcol > DIAG_DISAGREE)
    else:
        dcol = torch.zeros_like(wsum)
        two = torch.zeros_like(cov_m)
        disagree = two
    n_cov = max(int(cov_m.sum().item()), 1)

    def pct(m):
        return round(100.0 * float(m.sum().item()) / n_cov, 3)

    summ = {
        "mode": "proj_fix" if fix is not None else "repo",
        "projFix": asdict(fix) if fix is not None else None,
        "texels": int(W.shape[1]),
        "coveragePct": round(cov, 3),
        "coverageAnyViewPct": round(cov_any, 3),
        "visibleCoveragePct": None if cov_vis is None else round(cov_vis, 3),
        "grazingOnlyPct": pct(grazing),
        "grazingOnlyThreshold": DIAG_GRAZE,
        "bleedRiskPct": pct(bleed),
        "occlusionOnlyPct": pct(occl),
        "disagreePct": pct(disagree),
        "multiViewPct": pct(two),
        "medianBestNdotV": round(float(best_nv[cov_m].median().item()), 4) if bool(cov_m.any()) else None,
        "winViewShare": {n: round(100.0 * float(((widx == i) & cov_m).sum().item()) / n_cov, 2) for i, n in enumerate(names)},
    }
    if vis is not None:  # vis = strict-tolerance outside-visible surface (seen from >= 3 of 96 directions)
        summ["visibleTexelsPct"] = round(100.0 * float(vis.float().mean().item()), 3)
        # same (strict) denominator in both modes, so repo vs --proj-fix coverage compares honestly
        summ["visibleCoverageStrictPct"] = round(100.0 * float((projected & vis).sum().item())
                                                 / max(int(vis.sum().item()), 1), 3)
        vm = vis & cov_m
        n_vm = max(int(vm.sum().item()), 1)
        summ["grazingOnlyVisiblePct"] = round(100.0 * float((grazing & vis).sum().item()) / n_vm, 3)
        summ["bleedRiskVisiblePct"] = round(100.0 * float((bleed & vis).sum().item()) / n_vm, 3)
    diag["summary"] = summ

    def to_uv(vals, fill, dtype):
        img = torch.full((uv_res, uv_res), fill, dtype=dtype, device=vals.device)
        img[valid_idx[:, 0], valid_idx[:, 1]] = vals.to(dtype)
        return img.cpu().numpy()

    diag["maps"] = {
        "best_ndotv": to_uv(torch.where(cov_m, best_nv, torch.full_like(best_nv, -1.0)), -2.0, torch.float32),
        "n_contrib": to_uv(n_contrib, 0, torch.uint8),
        "win_view": to_uv(torch.where(cov_m, widx, torch.full_like(widx, 255)), 255, torch.uint8),
        "win_margin_px": to_uv(torch.where(cov_m, win_margin, torch.full_like(win_margin, -1.0)), -2.0, torch.float32),
        "bleed": to_uv(bleed, False, torch.bool),
        "occlusion": to_uv(occl, False, torch.bool),
        "grazing": to_uv(grazing, False, torch.bool),
        "disagree": to_uv(torch.where(two, dcol, torch.zeros_like(dcol)), 0.0, torch.float32),
        "projected": to_uv(projected, False, torch.bool),
    }
    diag["view_names"] = names


def dilate_uv_gutter(img: torch.Tensor, mask: torch.Tensor, radius_px: int = 24) -> torch.Tensor:
    x = img.permute(2, 0, 1).unsqueeze(0).contiguous()
    m = mask.float().unsqueeze(0).unsqueeze(0)
    for _ in range(radius_px):
        if m.all():
            break
        x_sum = F.avg_pool2d(x * m, kernel_size=3, stride=1, padding=1) * 9.0
        m_sum = F.avg_pool2d(m, kernel_size=3, stride=1, padding=1) * 9.0
        fill = (m < 0.5) & (m_sum > 0.5)
        new_x = x_sum / m_sum.clamp_min(1.0)
        x = torch.where(fill, new_x, x)
        m = torch.where(fill, torch.ones_like(m), m)
    return x[0].permute(1, 2, 0).contiguous()


def synthesize_pbr_and_hexlit(
    unit: str,
    archetype: str,
    rebuild_root: Path,
    uv_lin: torch.Tensor,
    uv_pos: torch.Tensor,
    uv_nrm: torch.Tensor,
    uv_tan: torch.Tensor,
    uv_bit: torch.Tensor,
    uv_mask: torch.Tensor,
    uv_ao_np: np.ndarray,
    meta: dict,
    dev: torch.device,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Produce 24px-dilated (albedo, normal, metallicgloss, basecolor_hexlit_pbr)."""
    uv_res = uv_mask.shape[0]
    if uv_ao_np.shape != (uv_res, uv_res):
        uv_ao_np = cv2.resize(uv_ao_np.astype(np.float32), (uv_res, uv_res), interpolation=cv2.INTER_LINEAR)

    ao_t = torch.from_numpy(uv_ao_np).to(dev).clamp(0.0, 1.0)
    ao_mean = float(ao_t[uv_mask].mean().item())
    assert ao_mean >= 0.30, f"{unit}: masked uv_ao mean too dark ({ao_mean:.3f} < 0.30; inside-out normals?)"
    ao_mult = (0.76 + 0.24 * (ao_t ** 1.32)).unsqueeze(-1)
    albedo_lin = dilate_uv_gutter((uv_lin * ao_mult).clamp(0.0, 1.0), uv_mask, radius_px=24)
    albedo_srgb = (linear_to_srgb_t(albedo_lin) * 255.0).round().clamp(0, 255).to(torch.uint8).cpu().numpy()

    pos_dil = dilate_uv_gutter(uv_pos, uv_mask, radius_px=24).cpu().numpy()
    pos_z = pos_dil[..., 2]
    mask_cpu = uv_mask.cpu().numpy()
    z_floor, z_top = float(pos_z[mask_cpu].min()), float(pos_z[mask_cpu].max())
    rel_z = (pos_z - z_floor) / max(z_top - z_floor, 1e-4)

    hc = np.array(meta.get("headCenter", [0.0, -0.5, 1.2]), dtype=np.float32)
    h_rad = max(float(meta.get("headScale", 1.2)) * 0.65, 0.55)
    dist_head = np.linalg.norm(pos_dil - hc[None, None, :], axis=-1)

    hsv = cv2.cvtColor(albedo_srgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    h_deg, s_hsv, v_hsv = hsv[..., 0] * 2.0, hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
    lab = cv2.cvtColor(albedo_srgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]

    is_eye_gold = (h_deg >= 20.0) & (h_deg <= 60.0) & (s_hsv > 0.45) & (v_hsv > 0.40) & (dist_head < h_rad * 1.15)
    is_eye_red = ((h_deg <= 16.0) | (h_deg >= 340.0)) & (s_hsv > 0.55) & (v_hsv > 0.40) & (dist_head < h_rad * 1.15)
    is_eye = is_eye_gold | is_eye_red
    is_fang = (s_hsv < 0.25) & (v_hsv > 0.58) & (dist_head < h_rad * 1.15)

    raw_metal_p = rebuild_root / unit / "tex/metallic.png"
    raw_metal = np.zeros(h_deg.shape, dtype=np.float32)
    if raw_metal_p.is_file():
        rm = np.array(Image.open(raw_metal_p).convert("L").resize((uv_res, uv_res), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
        raw_metal = cv2.GaussianBlur(rm, (5, 5), 1.0)

    is_cool_steel = (s_hsv < 0.22) & (v_hsv > 0.30) & (v_hsv < 0.85) & (~is_fang)
    is_gold_bronze = (h_deg >= 24.0) & (h_deg <= 52.0) & (s_hsv >= 0.28) & (s_hsv <= 0.72) & (v_hsv > 0.38) & (~is_eye)

    if archetype == "reptile_green":
        is_green = (h_deg >= 72.0) & (h_deg <= 145.0) & (s_hsv > 0.16)
        is_cyan_halo = (h_deg > 145.0) & (h_deg <= 200.0) & (s_hsv > 0.20) & (s_hsv < 0.38)
        m_gr = cv2.GaussianBlur(is_green.astype(np.float32), (5, 5), 1.0)
        L = L * (1.0 - m_gr) + np.clip(L * 0.92 - 3.0 * np.clip(1.0 - L / 145.0, 0.0, 1.0), 0.0, 255.0) * m_gr
        B = B * (1.0 - m_gr) + np.clip(B + 4.0, 0.0, 255.0) * m_gr
        m_halo = cv2.GaussianBlur(is_cyan_halo.astype(np.float32), (5, 5), 1.0)
        A = A - 3.5 * m_halo
        B = B + 7.0 * m_halo

    m_eye = cv2.GaussianBlur(is_eye.astype(np.float32), (5, 5), 1.0)
    L = np.clip(L + 8.0 * m_eye, 0.0, 255.0)
    B = np.clip(B + 8.0 * m_eye, 0.0, 255.0)
    m_fang = cv2.GaussianBlur(is_fang.astype(np.float32), (3, 3), 0.7)
    L = np.clip(L + 7.0 * m_fang, 0.0, 255.0)

    albedo_srgb = cv2.cvtColor(np.stack([L, A, B], axis=-1).clip(0, 255).round().astype(np.uint8), cv2.COLOR_LAB2RGB)
    alb_f = albedo_srgb.astype(np.float32) / 255.0
    lum = 0.2126 * alb_f[..., 0] + 0.7152 * alb_f[..., 1] + 0.0722 * alb_f[..., 2]

    metal = np.zeros(h_deg.shape, dtype=np.float32)
    smooth = np.full(h_deg.shape, 0.24, dtype=np.float32)
    m_hi = np.clip(raw_metal * 1.4, 0.0, 1.0)

    if archetype == "armored_metal":
        smooth[:] = 0.18
        m_mask = np.maximum(m_hi, np.where((is_cool_steel | is_gold_bronze) & (rel_z > 0.18), 0.80, 0.0))
        m_mask = np.where(is_eye | is_fang, 0.0, m_mask)
        metal = cv2.GaussianBlur(m_mask.astype(np.float32), (5, 5), 1.0)
        smooth = np.where(rel_z < 0.16, 0.12, smooth)
        smooth = smooth * (1.0 - metal) + 0.64 * metal
    elif archetype == "chitin_insect":
        smooth[:] = 0.44
        is_blue = (h_deg >= 170.0) & (h_deg <= 250.0) & (s_hsv > 0.25)
        smooth = np.where(is_blue, 0.58, smooth)
    elif archetype == "reptile_green":
        is_tan = (h_deg >= 12.0) & (h_deg <= 68.0) & (~is_eye) & (s_hsv > 0.12)
        smooth = np.where(is_tan | (rel_z < 0.18), 0.11, 0.22)
    elif archetype == "bone_stone":
        smooth[:] = 0.16
        metal = cv2.GaussianBlur(np.where(is_eye | is_fang, 0.0, m_hi).astype(np.float32), (5, 5), 1.0)
        smooth = smooth * (1.0 - metal) + 0.58 * metal
    elif archetype == "ethereal_glow":
        smooth[:] = 0.42
        is_bright = (v_hsv > 0.55) & (s_hsv > 0.30)
        smooth = np.where(is_bright, 0.58, smooth)
    else:  # generic_creature & leather_cloth
        smooth = np.where(rel_z < 0.18, 0.12, 0.24)
        if np.any(m_hi > 0.25):
            metal = cv2.GaussianBlur(np.where(is_eye | is_fang, 0.0, m_hi).astype(np.float32), (5, 5), 1.0)
            smooth = smooth * (1.0 - metal) + 0.60 * metal

    eye_smooth = 0.86 if archetype in ("bone_stone", "ethereal_glow") else 0.82
    smooth = np.where(is_fang, 0.44, smooth)
    smooth = np.where(is_eye, eye_smooth, smooth)
    smooth = np.clip(cv2.GaussianBlur(smooth, (5, 5), 1.0), 0.08, 0.88)

    mg = np.zeros((uv_res, uv_res, 4), dtype=np.float32)
    mg[..., 0] = metal
    mg[..., 1] = metal
    mg[..., 2] = metal
    mg[..., 3] = smooth
    mg_dil = dilate_uv_gutter(torch.from_numpy(mg).to(dev), uv_mask, radius_px=24).cpu().numpy()
    mg_u8 = np.clip(mg_dil * 255.0, 0, 255).round().astype(np.uint8)

    raw_nrm_p = rebuild_root / unit / "tex/normal.png"
    if raw_nrm_p.is_file():
        n_base = np.array(
            Image.open(raw_nrm_p).convert("RGB").resize((uv_res, uv_res), Image.Resampling.LANCZOS),
            dtype=np.float32,
        )
        n_vec = (n_base / 127.5) - 1.0
    else:
        n_vec = np.zeros_like(alb_f)
        n_vec[..., 2] = 1.0

    n_vec[..., 2] = np.maximum(n_vec[..., 2], 0.42)
    mask_inner = cv2.erode(mask_cpu.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    lum_clean = cv2.GaussianBlur(lum, (3, 3), 0.7)
    gx = cv2.Scharr(lum_clean, cv2.CV_32F, 1, 0) / 16.0
    gy = cv2.Scharr(lum_clean, cv2.CV_32F, 0, 1) / 16.0
    bm = mask_inner.astype(np.float32)
    n_vec[..., 0] -= 0.42 * gx * bm
    n_vec[..., 1] += 0.42 * gy * bm
    n_vec[..., 2] = np.maximum(n_vec[..., 2], 0.42)
    n_vec = n_vec / np.linalg.norm(n_vec, axis=-1, keepdims=True).clip(1e-6)
    n_dil = dilate_uv_gutter(torch.from_numpy(n_vec).to(dev), uv_mask, radius_px=24)
    n_dil = F.normalize(n_dil, dim=-1, eps=1e-8)
    nrm_u8 = np.clip((n_dil.cpu().numpy() * 0.5 + 0.5) * 255.0, 0, 255).round().astype(np.uint8)

    # Yaw-invariant Full-PBR bake into diffuse _MainTex for Olden Era Hex/Lit
    alb_lin_final = srgb_to_linear_t(torch.from_numpy(alb_f).to(dev))
    n_world_pbr = F.normalize(
        n_dil[..., 0:1] * uv_tan + n_dil[..., 1:2] * uv_bit + n_dil[..., 2:3] * uv_nrm,
        dim=-1, eps=1e-8
    )
    hemi_pbr = 0.55 + 0.45 * n_world_pbr[..., 2]
    hemi_vert = 0.55 + 0.45 * uv_nrm[..., 2]
    relief_gain = torch.clamp(hemi_pbr / torch.clamp(hemi_vert, min=0.25), 0.72, 1.38)
    relief_mix = torch.where(uv_mask, 1.0 + 0.65 * (relief_gain - 1.0), torch.ones_like(relief_gain)).unsqueeze(-1)

    sm_t = torch.from_numpy(mg_dil[..., 3]).to(dev)
    mt_t = torch.from_numpy(mg_dil[..., 0]).to(dev)
    ndotup = torch.clamp(n_world_pbr[..., 2], 0.0, 1.0)
    spec_pow = torch.clamp(4.0 + 38.0 * (sm_t ** 2.2), 4.0, 42.0)
    spec_lobe = (ndotup ** spec_pow) * (0.04 + 0.24 * (sm_t ** 1.6))
    diff_keep = 1.0 - 0.35 * mt_t
    spec_tint = torch.lerp(torch.ones_like(alb_lin_final), alb_lin_final * 1.4, mt_t.unsqueeze(-1))
    hexlit_lin = (alb_lin_final * diff_keep.unsqueeze(-1) * relief_mix + spec_lobe.unsqueeze(-1) * spec_tint).clamp(0.0, 1.0)
    hexlit_lin = dilate_uv_gutter(hexlit_lin, uv_mask, radius_px=24)
    hexlit_srgb = (linear_to_srgb_t(hexlit_lin) * 255.0).round().clamp(0, 255).to(torch.uint8).cpu().numpy()

    return albedo_srgb, nrm_u8, mg_u8, hexlit_srgb


def run_parity_check_npz(eval_npz: Path, uv_res: int = 256) -> dict[str, float | int]:
    dev_cpu = resolve_device("cpu")
    dev_gpu = resolve_device("cuda")
    p_c, n_c, t_c, _, m_c = rasterize_uv_buffers(eval_npz, uv_res, dev_cpu)
    p_g, n_g, t_g, _, m_g = rasterize_uv_buffers(eval_npz, uv_res, dev_gpu)
    pos_diff = float((p_g.cpu() - p_c).abs().max().item())
    nrm_diff = float((n_g.cpu() - n_c).abs().max().item())
    tan_diff = float((t_g.cpu() - t_c).abs().max().item())
    mask_diff = int((m_g.cpu() != m_c).sum().item())
    dil_c = dilate_uv_gutter(p_c, m_c, radius_px=8)
    dil_g = dilate_uv_gutter(p_g, m_g, radius_px=8).cpu()
    dil_diff = float((dil_g - dil_c).abs().max().item())
    print(f"  Parity @{uv_res}x{uv_res}: pos={pos_diff:.2e} nrm={nrm_diff:.2e} tan={tan_diff:.2e} mask_diff={mask_diff} dil={dil_diff:.2e}")
    assert pos_diff < 1e-4 and nrm_diff < 1e-4 and tan_diff < 1e-4 and mask_diff == 0 and dil_diff < 1e-4
    return {
        "posDiff": pos_diff,
        "nrmDiff": nrm_diff,
        "tanDiff": tan_diff,
        "maskDiff": mask_diff,
        "dilDiff": dil_diff,
    }


def _diag_color_maps(maps: dict, uv_mask: torch.Tensor, dev: torch.device, out_res: int) -> dict[str, np.ndarray]:
    """Heatmap PNGs (UV space, gutter-dilated so mesh renders show no seams)."""
    m = uv_mask
    bn = maps["best_ndotv"]
    cov = bn > -1.5
    proj = bn >= 0.0

    def turbo(x01: np.ndarray) -> np.ndarray:
        u8 = (np.clip(x01, 0, 1) * 255).round().astype(np.uint8)
        return cv2.cvtColor(cv2.applyColorMap(u8, cv2.COLORMAP_TURBO), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0

    out = {}
    # best visible n.v: red = grazing-only, blue = face-on; dark grey = no view sees it (KNN-filled)
    img = turbo(1.0 - np.clip(bn, 0.0, 1.0))
    img[cov & ~proj] = (0.25, 0.25, 0.25)
    out["best_ndotv"] = img
    nc = maps["n_contrib"].astype(np.float32)
    img = turbo(nc / 6.0)
    img[nc == 0] = (0.25, 0.25, 0.25)
    out["n_contrib"] = img
    mg = maps["win_margin_px"]
    img = turbo(np.log2(1.0 + np.clip(mg, 0, None)) / np.log2(1.0 + 32.0))
    img[mg < -0.5] = (0.25, 0.25, 0.25)
    out["win_margin_px"] = img
    risk = np.full(bn.shape + (3,), 0.55, np.float32)
    risk[cov & ~proj] = (0.30, 0.30, 0.30)
    risk[maps["disagree"] > DIAG_DISAGREE] = (0.20, 0.75, 0.85)
    risk[maps["grazing"]] = (1.0, 0.62, 0.10)
    risk[maps["bleed"]] = (0.90, 0.15, 0.85)
    risk[maps["grazing"] & maps["bleed"]] = (0.95, 0.10, 0.10)
    out["risk"] = risk
    res = {}
    for k, v in out.items():
        t = torch.from_numpy(v).to(dev)
        t = dilate_uv_gutter(t, m, radius_px=24).cpu().numpy()
        u8 = (np.clip(t, 0, 1) * 255).round().astype(np.uint8)
        if out_res != u8.shape[0]:
            u8 = cv2.resize(u8, (out_res, out_res), interpolation=cv2.INTER_AREA)
        res[k] = u8
    return res


def load_view_passes(in_root: Path, vn: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    vdir = in_root / "views"
    paths = [vdir / f"{vn}_{k}.npy" for k in ("alpha", "depth", "nrm")]
    if not all(p.is_file() for p in paths):
        raise FileNotFoundError(f"{paths[0]} missing (pruned?); re-render guides (render_guides_unit.py) into "
                                f"--inputs-root")
    return tuple(np.load(p) for p in paths)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--unit", required=True)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--rebuild-root", type=Path, default=DEFAULT_REBUILD_ROOT)
    ap.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    ap.add_argument("--archetype", default="")
    ap.add_argument("--parity-check", action="store_true")
    ap.add_argument(
        "--coverage-over-visible", action="store_true",
        help="opt-in: gate the 75%% coverage on the outside-visible surface (texels seen from >=3 of 96 sphere "
             "directions; excludes interior / enclosed / slot-only texels, see visible_surface_mask); default gates "
             "on all UV texels",
    )
    ap.add_argument(
        "--extra-views", action="store_true",
        help="opt-in: also project the 4 low TERTIARY_VIEWS from out/repaint_tertiary.png (needs prep --tertiary)",
    )
    ap.add_argument("--proj-fix", action="store_true",
                    help="opt-in: slope-aware pixel-scaled depth tolerance, occlusion-edge ramp and grazing-only "
                         "rejection (see ProjFix); gates on the strict-visible surface at 65%% instead of 75%%")
    ap.add_argument("--diag", action="store_true",
                    help="opt-in: write <out-dir>/diag/ per-texel maps (best visible n.v, contributing views, winning "
                         "view depth margin, bleed / grazing / disagreement masks) + diag_summary.json")
    ap.add_argument("--diag-only", action="store_true",
                    help="with --diag: stop after the diagnostics (no fill, no PBR synthesis, no texture writes, no "
                         "coverage gate)")
    ap.add_argument("--diag-res", type=int, default=2048, help="resolution of the diag heatmap PNGs")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="where outputs go (default <work-dir>/<unit>/out); sheets are still read from out/")
    ap.add_argument("--inputs-root", type=Path, default=None,
                    help="work dir holding <unit>/views/*.npy and <unit>/proj/ when the unit's own were pruned "
                         "(default: <work-dir>); views/meta.json and the sheets always come from <work-dir>/<unit>")
    args = ap.parse_args()
    if args.diag_only:
        args.diag = True

    unit = args.unit
    archetype = resolve_archetype(args.archetype, unit)
    u_root = args.work_dir / unit
    in_root = (args.inputs_root / unit) if args.inputs_root else u_root
    out_dir = args.out_dir or (u_root / "out")
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.parity_check:
        run_parity_check_npz(in_root / "proj/eval_mesh.npz", uv_res=256)

    t0 = time.perf_counter()
    dev = resolve_device(args.device)
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats(dev)

    meta = json.loads((u_root / "views/meta.json").read_text(encoding="utf-8"))
    uv_res = int(meta["uvRes"])
    view_res = int(meta["viewRes"])
    uv_pos, uv_nrm, uv_tan, uv_bit, uv_mask = rasterize_uv_buffers(in_root / "proj/eval_mesh.npz", uv_res, dev)

    panels = {}
    panels.update(extract_panels(u_root / "out/repaint_primary.png", PRIMARY_VIEWS, view_res))
    panels.update(extract_panels(u_root / "out/repaint_secondary.png", SECONDARY_VIEWS, view_res))
    use_views = list(ALL_VIEWS)
    if args.extra_views:
        missing = [vn for vn in TERTIARY_VIEWS if vn not in meta["views"]]
        if missing or not (u_root / "out/repaint_tertiary.png").is_file():
            raise SystemExit(f"{unit}: --extra-views needs prep --tertiary views {missing} and out/repaint_tertiary.png")
        panels.update(extract_panels(u_root / "out/repaint_tertiary.png", TERTIARY_VIEWS, view_res))
        use_views += TERTIARY_VIEWS

    views_data = {}
    reg_report = {}
    for vn in use_views:
        alpha, depth, nrm = load_view_passes(in_root, vn)
        warped_rgb, ramp, stats = register_panel_to_alpha(panels[vn], alpha, f"{unit}/{vn}")
        clean_rgb = gentle_delight_view(warped_rgb, nrm, alpha)
        views_data[vn] = {"rgb": clean_rgb, "alpha": alpha, "depth": depth, "nrm": nrm, "ramp": ramp}
        reg_report[vn] = stats

    ious = [f"{vn[:5]}={reg_report[vn]['iouPost']:.3f}" for vn in use_views]
    print(f"{unit} ({archetype}) IoU: {' '.join(ious)}")
    (out_dir / "registration_report.json").write_text(json.dumps(reg_report, indent=2), encoding="utf-8")

    fix = ProjFix() if args.proj_fix else None
    diag = {} if args.diag else None
    want_vis = args.coverage_over_visible or args.diag or args.proj_fix
    uv_lin, _ = project_views_to_uv(
        uv_pos, uv_nrm, uv_mask, views_data, meta, dev,
        visible_eval_npz=(in_root / "proj/eval_mesh.npz") if want_vis else None,
        fix=fix, diag=diag, gate=not args.diag_only, gate_visible=args.coverage_over_visible,
    )
    if diag is not None:
        ddir = out_dir / "diag"
        ddir.mkdir(parents=True, exist_ok=True)
        summ = dict(diag["summary"], unit=unit, minIoU=round(min(r["iouPost"] for r in reg_report.values()), 4))
        (ddir / "diag_summary.json").write_text(json.dumps(summ, indent=2), encoding="utf-8")
        for k, im in _diag_color_maps(diag["maps"], uv_mask, dev, args.diag_res).items():
            Image.fromarray(im, "RGB").save(ddir / f"{k}.png")
        print(f"  diag: grazing-only {summ['grazingOnlyPct']:.2f}%  bleed-risk {summ['bleedRiskPct']:.2f}%  "
              f"disagree {summ['disagreePct']:.2f}%  coverage {summ['coveragePct']:.2f}% -> {ddir}")
        if args.diag_only:
            return 0

    uv_ao = np.load(in_root / "proj/uv_ao.npy")
    alb_u8, nrm_u8, mg_u8, hex_u8 = synthesize_pbr_and_hexlit(
        unit, archetype, args.rebuild_root, uv_lin, uv_pos, uv_nrm, uv_tan, uv_bit, uv_mask, uv_ao, meta, dev
    )

    Image.fromarray(alb_u8, "RGB").save(out_dir / "basecolor_albedo.png")
    Image.fromarray(nrm_u8, "RGB").save(out_dir / "normal.png")
    Image.fromarray(mg_u8, "RGBA").save(out_dir / "metallicgloss.png")
    Image.fromarray(hex_u8, "RGB").save(out_dir / "basecolor_hexlit_pbr.png")

    peak_mb = torch.cuda.max_memory_allocated(dev) / (1024 ** 2) if dev.type == "cuda" else 0.0
    print(f"  Wrote {out_dir} ({time.perf_counter() - t0:.2f}s, peakVRAM={peak_mb:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
