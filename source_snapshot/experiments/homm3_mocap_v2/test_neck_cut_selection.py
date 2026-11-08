"""Contract tests for texture-guided neck-cut selection (no GLB I/O)."""
from __future__ import annotations

import numpy as np

import neck_cut_selection as neck


def _checker_texture():
    tex = np.zeros((64, 64, 3), dtype=np.uint8)
    tex[:, 32:] = 255
    return tex


def _hinge_mesh(white_prop=False, same_uv=False):
    """Two quads sharing an edge position; prop side has duplicate vertex ids.

    Quad A (body, joint 0): verts 0..3.  Quad B (prop, joint 1): verts 4..7
    with 4 == pos(1), 7 == pos(2).  Edge verts carry 50/50 blended slot
    weights so a hinge rotation strains the edge-adjacent triangles.
    """
    rest = np.array([
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
        [1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 1.0, 0.0], [1.0, 1.0, 0.0],
    ])
    tris = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], dtype=np.int64)
    uvs = np.array([
        [0.10, 0.10], [0.20, 0.10], [0.20, 0.20], [0.10, 0.20],
        [0.205, 0.10] if same_uv else ([0.70, 0.10] if white_prop else [0.10, 0.10]),
        [0.80, 0.10], [0.80, 0.20],
        [0.205, 0.20] if same_uv else ([0.70, 0.20] if white_prop else [0.10, 0.20]),
    ])
    ids = np.array([[0, 0], [0, 1], [0, 1], [0, 0],
                    [0, 1], [1, 1], [1, 1], [0, 1]], dtype=np.int64)
    wts = np.array([[1.0, 0.0], [0.5, 0.5], [0.5, 0.5], [1.0, 0.0],
                    [0.5, 0.5], [0.0, 1.0], [0.0, 1.0], [0.5, 0.5]])
    # Cold padding: static black-UV quads far away, so percentile gates behave
    # like on real meshes (mostly cold) instead of knife-edging on four faces.
    pad_rest, pad_tris, pad_uvs, pad_ids, pad_wts = [], [], [], [], []
    base = len(rest)
    for q in range(4):
        ox = 10.0 + q * 3.0
        quad = [[ox, 0.0, 0.0], [ox + 1.0, 0.0, 0.0],
                [ox + 1.0, 1.0, 0.0], [ox, 1.0, 0.0]]
        pad_rest.extend(quad)
        pad_tris.append([base, base + 1, base + 2])
        pad_tris.append([base, base + 2, base + 3])
        pad_uvs.extend([[0.05, 0.05]] * 4)
        pad_ids.extend([[0, 0]] * 4)
        pad_wts.extend([[1.0, 0.0]] * 4)
        base += 4
    rest = np.concatenate([rest, np.asarray(pad_rest)])
    tris = np.concatenate([tris, np.asarray(pad_tris, dtype=np.int64)])
    uvs = np.concatenate([uvs, np.asarray(pad_uvs)])
    ids = np.concatenate([ids, np.asarray(pad_ids, dtype=np.int64)])
    wts = np.concatenate([wts, np.asarray(pad_wts)])
    return rest, tris, uvs, ids, wts


def _posed_hinge(rest, ids, wts):
    """Rotate joint 1 by 90 deg about Y (origin); joint 0 static."""
    rest = np.asarray(rest, dtype=np.float64)
    angle = np.pi / 2.0
    rot = np.array([[np.cos(angle), 0.0, np.sin(angle)], [0.0, 1.0, 0.0],
                    [-np.sin(angle), 0.0, np.cos(angle)]])
    posed = np.zeros_like(rest)
    for v in range(len(rest)):
        point = np.zeros(3)
        for s in range(ids.shape[1]):
            joint = int(ids[v, s])
            moved = rest[v] if joint == 0 else rot @ rest[v]
            point = point + wts[v, s] * moved
        posed[v] = point
    return posed


def _tri_stretch(posed, rest, tris):
    """Max principal stretch + min compression per triangle (numpy)."""
    out_max, out_min = [], []
    for tri in tris:
        e0 = np.stack([rest[tri[1]] - rest[tri[0]], rest[tri[2]] - rest[tri[0]]], axis=1)
        e1 = np.stack([posed[tri[1]] - posed[tri[0]], posed[tri[2]] - posed[tri[0]]], axis=1)
        fmat = e1 @ np.linalg.pinv(e0)
        vals = np.linalg.svd(fmat, compute_uv=False)
        # F is 3x3 of rank 2 for planar triangles; the trailing singular
        # value is structurally zero, so compression is the middle value.
        out_max.append(float(vals[0]))
        out_min.append(float(vals[1]))
    return np.array(out_max), np.array(out_min)


def test_continuous_skin_suggests_geometric_neck_with_flag():
    """Same-skin webbing can still be the right cut: suggest, but flag it."""
    rest, tris, uvs, ids, wts = _hinge_mesh(same_uv=True)
    posed = _posed_hinge(rest, ids, wts)
    smax, smin = _tri_stretch(posed, rest, tris)
    assert smax.max() > 1.5, "fixture must actually warp"
    report = neck.select_neck_cut(
        rest_vertices=rest, triangles=tris, uvs=uvs, albedo=_checker_texture(),
        face_stretch_max=smax, face_compress_min=smin,
        joint_names=["root", "hinge"], vertex_joint_ids=ids, vertex_joint_weights=wts)
    assert sorted(report["selectedFaces"]) == [2, 3]
    assert report["owner"] == "hinge"
    assert report["textureAgrees"] is False
    assert "geometric neck" in report["reason"]


def test_texture_seam_proposes_cut_with_owner():
    rest, tris, uvs, ids, wts = _hinge_mesh(white_prop=True)
    posed = _posed_hinge(rest, ids, wts)
    smax, smin = _tri_stretch(posed, rest, tris)
    report = neck.select_neck_cut(
        rest_vertices=rest, triangles=tris, uvs=uvs, albedo=_checker_texture(),
        face_stretch_max=smax, face_compress_min=smin,
        joint_names=["root", "hinge"], vertex_joint_ids=ids, vertex_joint_weights=wts)
    assert sorted(report["selectedFaces"]) == [2, 3]
    assert report["owner"] == "hinge"
    assert report["textureAgrees"] is True
    assert report["metrics"]["seamFraction"] >= 0.5


def test_uv_distance_seam_without_color_difference():
    rest, tris, uvs, ids, wts = _hinge_mesh(white_prop=True)
    white_tex = np.full((64, 64, 3), 255, dtype=np.uint8)
    posed = _posed_hinge(rest, ids, wts)
    smax, smin = _tri_stretch(posed, rest, tris)
    report = neck.select_neck_cut(
        rest_vertices=rest, triangles=tris, uvs=uvs, albedo=white_tex,
        face_stretch_max=smax, face_compress_min=smin,
        joint_names=["root", "hinge"], vertex_joint_ids=ids, vertex_joint_weights=wts)
    assert sorted(report["selectedFaces"]) == [2, 3], "far-apart UVs are a texture seam"


def test_quiet_mesh_proposes_no_cut():
    rest, tris, uvs, ids, wts = _hinge_mesh(white_prop=True)
    report = neck.select_neck_cut(
        rest_vertices=rest, triangles=tris, uvs=uvs, albedo=_checker_texture(),
        face_stretch_max=np.ones(len(tris)), face_compress_min=np.ones(len(tris)),
        joint_names=["root", "hinge"], vertex_joint_ids=ids, vertex_joint_weights=wts)
    assert report["selectedFaces"] == []
    assert "no faces exceed" in report["reason"]


def test_malformed_inputs_raise():
    rest, tris, uvs, ids, wts = _hinge_mesh(white_prop=True)
    posed = _posed_hinge(rest, ids, wts)
    smax, smin = _tri_stretch(posed, rest, tris)
    good = dict(rest_vertices=rest, triangles=tris, uvs=uvs, albedo=_checker_texture(),
                face_stretch_max=smax, face_compress_min=smin,
                joint_names=["root", "hinge"], vertex_joint_ids=ids, vertex_joint_weights=wts)
    # The baseline itself must succeed, so each variant below fails on its own
    # defect rather than a shared shape error.
    assert sorted(neck.select_neck_cut(**good)["selectedFaces"]) == [2, 3]
    bad_variants = [
        dict(good, rest_vertices=np.full_like(rest, np.nan)),
        dict(good, triangles=np.array([[0, 1, 99]])),
        dict(good, face_stretch_max=np.ones(3)),
        dict(good, vertex_joint_ids=np.array([[0, 5]] * 8)),
        dict(good, joint_names=["root", "root"]),
        dict(good, albedo=np.zeros((0, 4, 3), dtype=np.uint8)),
    ]
    for variant in bad_variants:
        try:
            neck.select_neck_cut(**variant)
        except (ValueError, TypeError):
            continue
        raise AssertionError(f"variant accepted malformed input: {variant.keys()}")


def test_cut_releases_warp_and_preserves_rest():
    """End to end on the hinge: selector -> reviewed cutter -> strain fixed."""
    from attachment_repair import split_attachment
    rest, tris, uvs, ids, wts = _hinge_mesh(white_prop=True)
    posed = _posed_hinge(rest, ids, wts)
    smax, smin = _tri_stretch(posed, rest, tris)
    assert smax[2:].max() > 1.5
    report = neck.select_neck_cut(
        rest_vertices=rest, triangles=tris, uvs=uvs, albedo=_checker_texture(),
        face_stretch_max=smax, face_compress_min=smin,
        joint_names=["root", "hinge"], vertex_joint_ids=ids, vertex_joint_weights=wts)
    dense = np.zeros((len(rest), 2))
    for v in range(len(rest)):
        for s in range(ids.shape[1]):
            dense[v, int(ids[v, s])] += wts[v, s]
    skin = {"vertices": rest, "triangles": tris, "weights": dense,
            "names": np.array(["root", "hinge"]), "uvs": uvs}
    out, cut_report = split_attachment(skin, np.asarray(report["selectedFaces"]), report["owner"])
    assert cut_report["invariants"]["restPositionsPreserved"]
    assert cut_report["invariants"]["uvCornersPreserved"]
    new_tris = np.asarray(out["triangles"])
    new_w = np.asarray(out["weights"])
    new_posed = _posed_hinge(np.asarray(out["vertices"]),
                             np.argmax(new_w, axis=1).reshape(-1, 1),
                             np.ones((len(new_w), 1)))
    fixed_max, _ = _tri_stretch(new_posed, np.asarray(out["vertices"]), new_tris)
    assert fixed_max.max() < 1.01, f"warp survives the cut: {fixed_max.max()}"
    # Duplicate-id seams share no vertex ids, so the cutter reports no id
    # boundary; the real separation is positional.  Weld pairs by rest
    # position and require the animation to open a gap there.
    new_rest = np.asarray(out["vertices"])
    seen: dict[tuple[float, float, float], int] = {}
    gap = 0.0
    for i, point in enumerate(new_rest):
        key = (float(point[0]), float(point[1]), float(point[2]))
        if key in seen:
            gap = max(gap, float(np.linalg.norm(new_posed[i] - new_posed[seen[key]])))
        else:
            seen[key] = i
    assert gap > 0.0, "separated sides must open a gap in animation"


def test_large_texture_selection_stays_fast():
    """Regression pin for per-call 100MB texture copies (hung 30+ min on wood elf).

    A 50x50 grid over a 1024px texture must finish in well under the bound;
    without hoisted float conversion the per-edge copies churn hundreds of GB.
    """
    import time

    n = 50
    xs = np.linspace(0.0, 1.0, n + 1)
    gx, gy = np.meshgrid(xs, xs)
    rest = np.stack([gx.ravel(), gy.ravel(), np.zeros((n + 1) ** 2)], axis=1)
    tris = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            tris.append([a, a + 1, a + n + 1])
            tris.append([a + 1, a + n + 2, a + n + 1])
    tris = np.asarray(tris, dtype=np.int64)
    uvs = rest[:, :2].copy()
    tex = np.zeros((1024, 1024, 3), dtype=np.uint8)
    tex[:, 512:] = 255
    ids = np.zeros((len(rest), 1), dtype=np.int64)
    wts = np.ones((len(rest), 1))
    started = time.perf_counter()
    report = neck.select_neck_cut(
        rest_vertices=rest, triangles=tris, uvs=uvs, albedo=tex,
        face_stretch_max=np.full(len(tris), 2.0),
        face_compress_min=np.ones(len(tris)),
        joint_names=["root"], vertex_joint_ids=ids, vertex_joint_weights=wts)
    elapsed = time.perf_counter() - started
    # Whole grid is hot, so it forms one component with no outside boundary:
    # a global warp is not a neck, hence no cut.
    assert report["selectedFaces"] == []
    assert elapsed < 120.0, f"selection took {elapsed:.1f}s (per-call texture copies?)"


def test_crush_only_warp_counts_toward_mass():
    rest, tris, uvs, ids, wts = _hinge_mesh(white_prop=True)
    smax = np.ones(len(tris))
    smin = np.ones(len(tris))
    smin[2:4] = 0.5
    report = neck.select_neck_cut(
        rest_vertices=rest, triangles=tris, uvs=uvs, albedo=_checker_texture(),
        face_stretch_max=smax, face_compress_min=smin,
        joint_names=["root", "hinge"], vertex_joint_ids=ids, vertex_joint_weights=wts)
    assert sorted(report["selectedFaces"]) == [2, 3]
    assert report["textureAgrees"] is True


def _hinge_shared_ids():
    """Hinge with truly shared edge vertices (single UV each): geometric path."""
    rest = np.array([
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
        [2.0, 0.0, 0.0], [2.0, 1.0, 0.0],
    ])
    tris = np.array([[0, 1, 2], [0, 2, 3], [1, 4, 5], [1, 5, 2]], dtype=np.int64)
    uvs = np.array([[0.10, 0.10], [0.20, 0.10], [0.20, 0.20],
                    [0.10, 0.20], [0.30, 0.10], [0.30, 0.20]])
    ids = np.array([[0, 0], [0, 1], [0, 1], [0, 0], [1, 1], [1, 1]], dtype=np.int64)
    wts = np.array([[1.0, 0.0], [0.5, 0.5], [0.5, 0.5], [1.0, 0.0],
                    [0.0, 1.0], [0.0, 1.0]])
    # Cold padding (same reason as _hinge_mesh): keeps the percentile gate off
    # knife-edge ties.  Four quads put the tied hot pair safely below the
    # closest-observation rank, exactly like the padded duplicate-id hinge.
    pad_rest, pad_tris, pad_uvs, pad_ids, pad_wts = [], [], [], [], []
    base = len(rest)
    for q in range(4):
        ox = 10.0 + q * 3.0
        pad_rest.extend([[ox, 0.0, 0.0], [ox + 1.0, 0.0, 0.0],
                         [ox + 1.0, 1.0, 0.0], [ox, 1.0, 0.0]])
        pad_tris.append([base, base + 1, base + 2])
        pad_tris.append([base, base + 2, base + 3])
        pad_uvs.extend([[0.05, 0.05]] * 4)
        pad_ids.extend([[0, 0]] * 4)
        pad_wts.extend([[1.0, 0.0]] * 4)
        base += 4
    rest = np.concatenate([rest, np.asarray(pad_rest)])
    tris = np.concatenate([tris, np.asarray(pad_tris, dtype=np.int64)])
    uvs = np.concatenate([uvs, np.asarray(pad_uvs)])
    ids = np.concatenate([ids, np.asarray(pad_ids, dtype=np.int64)])
    wts = np.concatenate([wts, np.asarray(pad_wts)])
    return rest, tris, uvs, ids, wts


def test_shared_id_seam_cuts_topologically_and_releases_warp():
    """Shared vertex ids force the cutter's boundary-duplication path."""
    from attachment_repair import split_attachment
    rest, tris, uvs, ids, wts = _hinge_shared_ids()
    posed = _posed_hinge(rest, ids, wts)
    smax, smin = _tri_stretch(posed, rest, tris)
    assert smax[2:].max() > 1.5
    report = neck.select_neck_cut(
        rest_vertices=rest, triangles=tris, uvs=uvs, albedo=_checker_texture(),
        face_stretch_max=smax, face_compress_min=smin,
        joint_names=["root", "hinge"], vertex_joint_ids=ids, vertex_joint_weights=wts)
    assert sorted(report["selectedFaces"]) == [2, 3]
    assert report["textureAgrees"] is False
    dense = np.zeros((len(rest), 2))
    for v in range(len(rest)):
        for s in range(ids.shape[1]):
            dense[v, int(ids[v, s])] += wts[v, s]
    skin = {"vertices": rest, "triangles": tris, "weights": dense,
            "names": np.array(["root", "hinge"]), "uvs": uvs}
    out, cut_report = split_attachment(skin, np.asarray(report["selectedFaces"]), report["owner"])
    assert cut_report["sharedBoundaryCount"] == 2, "duplication path must engage"
    assert cut_report["invariants"]["restPositionsPreserved"]
    assert cut_report["invariants"]["uvCornersPreserved"]
    new_tris = np.asarray(out["triangles"])
    new_w = np.asarray(out["weights"])
    new_posed = _posed_hinge(np.asarray(out["vertices"]),
                             np.argmax(new_w, axis=1).reshape(-1, 1),
                             np.ones((len(new_w), 1)))
    fixed_max, _ = _tri_stretch(new_posed, np.asarray(out["vertices"]), new_tris)
    assert fixed_max.max() < 1.01
    dupe = [len(rest), len(rest) + 1]
    gaps = np.linalg.norm(new_posed[[1, 2]] - new_posed[dupe], axis=1)
    assert gaps.min() > 0.0, "duplicated boundary must separate in animation"


def test_sampler_matches_preview_convention():
    try:
        from mesh_preview import sample_albedo_uv
    except ImportError:
        print("SKIP sampler parity (mesh_preview not importable here)")
        return
    rng = np.random.default_rng(7)
    tex = (rng.random((48, 40, 3)) * 255).astype(np.uint8)
    u = rng.random(25)
    v = rng.random(25)
    assert np.allclose(neck.sample_texel(tex, u, v), sample_albedo_uv(tex, u, v))
