"""Depth billboard: pixels in 3D from VDA maps, no character mesh."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
POSE_FIT = ROOT / "tools" / "homm3_silhouette_pose_fit"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(POSE_FIT))

from geometry import BillboardPoints, billboard_points_from_frame, build_connected_depth_volume, load_depth01
from render import render_billboard_points
from run_depth_billboard import load_vda_clip, render_clip
from run_vda_movement_depth import (
    PIPELINE_MANIFEST_NAME,
    VDA_MODEL_ID,
    _sha256,
)
from extract_ccrusd_move import (
    NATIVE_GROUP0_COUNT,
    RIFE_GROUP0_COUNT,
    native_group0_texture_names,
    union_opaque_bbox,
)
from fill import prepare_billboard_frame, correct_depth_edge_bias
from synthetic_crusader import FRAME_COUNT, synthetic_crusader_move_frame, synthetic_crusader_move_frames


def _assert_front_reconstructs(rgba: np.ndarray, depth01: np.ndarray) -> None:
    points = billboard_points_from_frame(
        rgba,
        depth01,
        depth_scale=0.35,
        gap_close_radius=0,
        depth_smooth_radius=0,
    )
    rendered = render_billboard_points(
        points,
        yaw_deg=0.0,
        perspective=False,
        background=(0, 0, 0, 0),
        solid_front=False,
    )
    src_alpha = rgba[..., 3] > 20
    dst_alpha = rendered[..., 3] > 20
    if not np.array_equal(src_alpha, dst_alpha):
        miss = int(np.count_nonzero(src_alpha != dst_alpha))
        raise AssertionError(f"front view occupancy mismatch: {miss} pixels")
    if not np.array_equal(rendered[src_alpha], rgba[src_alpha]):
        raise AssertionError("front view color mismatch on opaque pixels")


def test_front_view_is_the_original_billboard() -> None:
    rgba, depth = synthetic_crusader_move_frame(0)
    _assert_front_reconstructs(rgba, depth)


def test_near_pixels_leave_the_billboard_plane() -> None:
    rgba = np.zeros((8, 8, 4), dtype=np.uint8)
    depth = np.zeros((8, 8), dtype=np.float32)
    rgba[3:5, 1:3] = (10, 20, 200, 255)
    depth[3:5, 1:3] = 0.1
    rgba[3:5, 5:7] = (200, 20, 10, 255)
    depth[3:5, 5:7] = 0.9
    points = billboard_points_from_frame(
        rgba, depth, depth_scale=0.5, gap_close_radius=0, depth_smooth_radius=0
    )
    if points.count != 8:
        raise AssertionError(f"expected 8 opaque pixels, got {points.count}")
    far_z = float(points.z[np.all(points.rgba[:, :3] == (10, 20, 200), axis=1)].mean())
    near_z = float(points.z[np.all(points.rgba[:, :3] == (200, 20, 10), axis=1)].mean())
    if not near_z > far_z + 0.2:
        raise AssertionError(f"near z {near_z} must sit in front of far z {far_z}")


def test_profile_view_separates_near_and_far() -> None:
    rgba = np.zeros((16, 16, 4), dtype=np.uint8)
    depth = np.full((16, 16), 0.0, dtype=np.float32)
    rgba[6:10, 6:10] = (30, 80, 200, 255)
    depth[6:10, 6:10] = 0.15
    rgba[6:10, 10:14] = (200, 40, 30, 255)
    depth[6:10, 10:14] = 0.95
    points = billboard_points_from_frame(
        rgba, depth, depth_scale=0.8, gap_close_radius=0, depth_smooth_radius=0
    )
    profile = render_billboard_points(
        points,
        yaw_deg=90.0,
        perspective=False,
        background=(0, 0, 0, 0),
    )
    opaque = profile[..., 3] > 20
    if int(opaque.sum()) < 4:
        raise AssertionError("profile view lost the billboard pixels")
    cols = np.nonzero(opaque.any(axis=0))[0]
    if cols.size < 2:
        raise AssertionError("profile view must spread pixels along depth")
    left = profile[:, cols[0]]
    right = profile[:, cols[-1]]
    left_red = left[left[:, 3] > 20][:, 0].mean() if (left[:, 3] > 20).any() else 0
    right_blue = right[right[:, 3] > 20][:, 2].mean() if (right[:, 3] > 20).any() else 0
    if left_red < 100 or right_blue < 100:
        raise AssertionError(
            f"profile should put near-red left and far-blue right, got left_r={left_red} right_b={right_blue}"
        )


def test_connected_volume_culls_double_shell_at_profile() -> None:
    rgba = np.zeros((16, 16, 4), dtype=np.uint8)
    depth = np.full((16, 16), 0.5, dtype=np.float32)
    rgba[4:12, 4:12] = (40, 80, 200, 255)
    depth[4:12, 4:12] = 0.2
    rgba[4:12, 10:14] = (200, 40, 30, 255)
    depth[4:12, 10:14] = 0.85
    volume = build_connected_depth_volume(
        rgba, depth, depth_scale=0.5, gap_close_radius=0, depth_smooth_radius=0
    )
    counts: list[int] = []
    for yaw in (0.0, 70.0, 86.0, 90.0):
        rendered = render_billboard_points(
            volume,
            yaw_deg=yaw,
            perspective=False,
            background=(0, 0, 0, 0),
            solid_front=False,
        )
        counts.append(int((rendered[..., 3] > 20).sum()))
    if min(counts) < 4:
        raise AssertionError(f"connected volume vanished at some yaw: {counts}")
    if max(counts) > 3 * min(counts):
        raise AssertionError(
            f"connected volume point visibility jumped too much across yaws: {counts}"
        )


def test_connected_volume_front_and_back_views() -> None:
    rgba = np.zeros((12, 12, 4), dtype=np.uint8)
    depth = np.full((12, 12), 0.5, dtype=np.float32)
    rgba[3:9, 3:9] = (100, 120, 200, 255)
    depth[3:9, 3:9] = 0.75
    volume = build_connected_depth_volume(
        rgba, depth, depth_scale=0.4, gap_close_radius=0, depth_smooth_radius=0
    )
    front = render_billboard_points(
        volume, yaw_deg=0.0, perspective=False, background=(0, 0, 0, 0), solid_front=False
    )
    back = render_billboard_points(
        volume, yaw_deg=180.0, perspective=False, background=(0, 0, 0, 0), solid_front=False
    )
    if int((front[..., 3] > 20).sum()) < 4:
        raise AssertionError("front view lost connected volume")
    if int((back[..., 3] > 20).sum()) < 4:
        raise AssertionError("back view lost connected volume")


def test_anchored_fill_keeps_thin_near_feature_on_near_side() -> None:
    rgba = np.zeros((32, 32, 4), dtype=np.uint8)
    depth = np.full((32, 32), 0.5, dtype=np.float32)
    # Wide torso-like block at mid depth.
    rgba[8:24, 4:20] = (40, 80, 200, 255)
    depth[8:24, 4:20] = 0.5
    # Thin sword-like strip, nearest to camera.
    rgba[8:24, 26:28] = (200, 40, 30, 255)
    depth[8:24, 26:28] = 0.95
    volume = build_connected_depth_volume(
        rgba, depth, depth_scale=0.5, gap_close_radius=0, depth_smooth_radius=0
    )
    sword = volume.xy[:, 0] > 0.55  # strip lives on the right of the sprite
    torso = volume.xy[:, 0] < 0.2
    if not sword.any() or not torso.any():
        raise AssertionError("test fixture failed to produce both regions")
    sword_z = volume.z[sword]
    torso_z = volume.z[torso]
    # The sword must stay anchored at its near VDA depth, not re-centered on the
    # billboard plane: its whole column sits nearer than the torso's front.
    if sword_z.min() <= torso_z.max():
        raise AssertionError(
            f"thin near feature was pushed back into the body: sword_min={sword_z.min()} torso_max={torso_z.max()}"
        )
    sword_thickness = float(sword_z.max() - sword_z.min())
    torso_thickness = float(torso_z.max() - torso_z.min())
    if sword_thickness >= torso_thickness:
        raise AssertionError(
            f"thin feature should extrude less than wide feature: sword={sword_thickness} torso={torso_thickness}"
        )


def test_depth_bow_correction_flattens_vertical_profile() -> None:
    from fill import correct_depth_bowing

    rgba = np.zeros((32, 16, 4), dtype=np.uint8)
    depth = np.zeros((32, 16), dtype=np.float32)
    rgba[4:28, 3:13] = (100, 120, 200, 255)
    depth[4:28, 3:13] = 0.6
    depth[4:8, 3:13] = 0.2
    depth[24:28, 3:13] = 0.2
    mask = rgba[..., 3] > 20

    def _interior_row_corr(values: np.ndarray) -> float:
        from scipy.ndimage import distance_transform_edt

        interior = mask & (distance_transform_edt(mask) >= 3)
        rows: list[int] = []
        medians: list[float] = []
        for row in range(values.shape[0]):
            row_mask = interior[row]
            if row_mask.any():
                rows.append(row)
                medians.append(float(values[row, row_mask].mean()))
        if len(rows) < 3:
            raise AssertionError("fixture did not produce enough interior rows")
        return float(np.corrcoef(rows, medians)[0, 1])

    before = _interior_row_corr(depth)
    after = _interior_row_corr(
        correct_depth_bowing(
            depth,
            mask,
            vertical_strength=0.85,
            edge_strength=0.85,
            local_radius=5,
        )
    )
    if abs(after) >= abs(before) - 0.15:
        raise AssertionError(
            f"bow correction did not flatten interior profile: before={before} after={after}"
        )


def test_depth_edge_correction_lifts_silhouette_extremities() -> None:
    rgba = np.zeros((20, 12, 4), dtype=np.uint8)
    depth = np.zeros((20, 12), dtype=np.float32)
    rgba[2:18, 2:10] = (80, 120, 200, 255)
    depth[2:18, 2:10] = 0.7
  # Bowed extremities: edges darker than interior column peaks.
    depth[2:6, 2:10] = 0.25
    depth[14:18, 2:10] = 0.25
    mask = rgba[..., 3] > 20
    corrected = correct_depth_edge_bias(depth, mask, strength=1.0, falloff_pixels=3.0)
    top = corrected[3, 4:9].mean()
    mid = corrected[10, 4:9].mean()
    bot = corrected[16, 4:9].mean()
    if top <= depth[3, 4:9].mean() + 0.05:
        raise AssertionError(f"top edge was not lifted: {top}")
    if bot <= depth[16, 4:9].mean() + 0.05:
        raise AssertionError(f"bottom edge was not lifted: {bot}")
    if abs(top - mid) > 0.2 or abs(bot - mid) > 0.2:
        raise AssertionError(
            f"edge correction did not flatten bow enough: top={top} mid={mid} bot={bot}"
        )


def test_front_shell_mesh_has_more_detail_than_voxel_fixture() -> None:
    rgba = np.zeros((24, 24, 4), dtype=np.uint8)
    depth = np.full((24, 24), 0.5, dtype=np.float32)
    rgba[4:20, 4:20] = (80, 120, 200, 255)
    depth[4:20, 4:20] = 0.75
    rgba[4:20, 18:22] = (200, 40, 30, 255)
    depth[4:20, 18:22] = 0.9
    from volume_mesh import extract_depth_mesh, mesh_summary

    shell = extract_depth_mesh(
        rgba,
        depth,
        style="front_shell",
        depth_scale=0.4,
        gap_close_radius=0,
        depth_smooth_radius=0,
        depth_edge_strength=0.0,
        grid_stride=1,
    )
    voxel = extract_depth_mesh(
        rgba,
        depth,
        style="voxel",
        depth_scale=0.4,
        gap_close_radius=0,
        depth_smooth_radius=0,
        depth_edge_strength=0.0,
        cell_stride=2,
        z_layers_max=16,
    )
    shell_stats = mesh_summary(shell)
    voxel_stats = mesh_summary(voxel)
    if shell_stats["triangleCount"] <= voxel_stats["triangleCount"]:
        raise AssertionError(
            f"front shell should beat voxel detail: shell={shell_stats} voxel={voxel_stats}"
        )


def test_volume_mesh_extracts_triangles_from_synthetic_fixture() -> None:
    rgba = np.zeros((24, 24, 4), dtype=np.uint8)
    depth = np.full((24, 24), 0.5, dtype=np.float32)
    rgba[4:20, 4:20] = (80, 120, 200, 255)
    depth[4:20, 4:20] = 0.75
    rgba[4:20, 18:22] = (200, 40, 30, 255)
    depth[4:20, 18:22] = 0.9
    from volume_mesh import extract_depth_mesh, mesh_summary

    mesh = extract_depth_mesh(
        rgba,
        depth,
        style="voxel",
        depth_scale=0.4,
        gap_close_radius=0,
        depth_smooth_radius=0,
        depth_edge_strength=0.0,
        cell_stride=2,
        z_layers_max=16,
    )
    stats = mesh_summary(mesh)
    if stats["triangleCount"] < 8:
        raise AssertionError(f"expected a non-trivial mesh, got {stats}")
    if mesh.normals.shape != mesh.vertices.shape:
        raise AssertionError("vertex normals must match vertex count")
    if mesh.uvs.shape != mesh.vertices.shape:
        raise AssertionError("uvs must match vertex count")


def test_nearer_pixel_wins_when_splats_overlap() -> None:
    points = BillboardPoints(
        xy=np.array([[0.0, 0.0], [0.0, 0.0]], dtype=np.float32),
        z=np.array([0.25, -0.25], dtype=np.float32),
        rgba=np.array([[200, 20, 10, 255], [10, 20, 200, 255]], dtype=np.uint8),
        width=16,
        height=16,
        depth_scale=0.5,
        pivot=0.5,
    )
    rendered = render_billboard_points(
        points,
        yaw_deg=0.0,
        perspective=False,
        background=(0, 0, 0, 0),
    )
    pixel = rendered[8, 8]
    if tuple(pixel.tolist()) != (200, 20, 10, 255):
        raise AssertionError(f"near red must occlude far blue, got {pixel.tolist()}")
    persp = render_billboard_points(
        points,
        yaw_deg=0.0,
        perspective=True,
        background=(0, 0, 0, 0),
    )
    persp_pixel = persp[8, 8]
    if tuple(persp_pixel.tolist()) != (200, 20, 10, 255):
        raise AssertionError(f"perspective near red must occlude far blue, got {persp_pixel.tolist()}")


def test_no_triangle_mesh_is_stored() -> None:
    rgba, depth = synthetic_crusader_move_frame(3)
    points = billboard_points_from_frame(
        rgba, depth, gap_close_radius=0, depth_smooth_radius=0
    )
    if hasattr(points, "faces") or hasattr(points, "triangles"):
        raise AssertionError("depth billboard must not carry mesh faces")
    BillboardPoints(
        xy=points.xy,
        z=points.z,
        rgba=points.rgba,
        width=points.width,
        height=points.height,
        depth_scale=points.depth_scale,
        pivot=points.pivot,
    )


def test_size_mismatch_is_refused() -> None:
    rgba, depth = synthetic_crusader_move_frame(0)
    try:
        billboard_points_from_frame(rgba, depth[:10], depth_scale=0.3)
    except ValueError as exc:
        if "does not match" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("mismatched depth must be refused")


def test_empty_sprite_is_refused() -> None:
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    depth = np.ones((4, 4), dtype=np.float32)
    try:
        billboard_points_from_frame(rgba, depth)
    except ValueError as exc:
        if "no opaque pixels" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("empty sprite must be refused")


def test_vda_cache_is_required_for_real_clips() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        sprites = root / "sprites"
        depths = root / "depths"
        sprites.mkdir()
        depths.mkdir()
        rgba, depth = synthetic_crusader_move_frame(0)
        Image.fromarray(rgba, "RGBA").save(sprites / "0.png")
        Image.fromarray(
            np.clip(np.rint(depth * 65535.0), 0, 65535).astype(np.uint16)
        ).save(depths / "0.png")
        try:
            load_vda_clip(sprites, depths)
        except RuntimeError as exc:
            if "no Video Depth Anything manifest" not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError("unlabelled depth must be refused")


def test_vda_named_cache_loads() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        sprites = root / "sprites"
        depths = root / "depths"
        sprites.mkdir()
        depths.mkdir()
        names = []
        for index in range(2):
            rgba, depth = synthetic_crusader_move_frame(index)
            name = f"{index}.png"
            names.append(name)
            Image.fromarray(rgba, "RGBA").save(sprites / name)
            Image.fromarray(
                np.clip(np.rint(depth * 65535.0), 0, 65535).astype(np.uint16)
            ).save(depths / name)
        checkpoint = root / "video_depth_anything_vits.pth"
        checkpoint.write_bytes(b"fake-vda")
        (depths / PIPELINE_MANIFEST_NAME).write_text(
            json.dumps(
                {
                    "version": 1,
                    "model": VDA_MODEL_ID,
                    "checkpointSha256": _sha256(checkpoint),
                    "sourceSignature": "unused-here",
                    "frameNames": names,
                    "inputSize": 518,
                    "requestedFps": 12.0,
                }
            ),
            encoding="utf-8",
        )
        loaded_sprites, loaded_depths, manifest = load_vda_clip(sprites, depths)
        if manifest["model"] != VDA_MODEL_ID:
            raise AssertionError(manifest)
        if len(loaded_sprites) != 2 or len(loaded_depths) != 2:
            raise AssertionError("clip length")
        loaded = load_depth01(depths / "0.png")
        if loaded.shape != loaded_sprites[0].shape[:2]:
            raise AssertionError(loaded.shape)


def test_cli_synthetic_writes_orbit_proof() -> None:
    with tempfile.TemporaryDirectory() as raw:
        out = Path(raw) / "out"
        clip = synthetic_crusader_move_frames(FRAME_COUNT)
        manifest = render_clip(
            clip.sprites,
            clip.depths,
            out,
            depth_scale=0.4,
            fps=8.0,
            source="synthetic_geometry_fixture",
            vda_manifest=None,
            preview_scale=2,
        )
        if manifest["source"] != "synthetic_geometry_fixture":
            raise AssertionError(manifest)
        if manifest["frameCount"] != FRAME_COUNT:
            raise AssertionError(manifest)
        if not (out / "front.gif").is_file():
            raise AssertionError("missing front.gif")
        if not (out / "orbit.gif").is_file():
            raise AssertionError("missing orbit.gif")
        if not (out / "compare.gif").is_file():
            raise AssertionError("missing compare.gif")
        try:
            render_clip(
                clip.sprites,
                clip.depths,
                out,
                depth_scale=0.4,
                fps=8.0,
                source="synthetic_geometry_fixture",
                vda_manifest=None,
                preview_scale=2,
            )
        except FileExistsError:
            pass
        else:
            raise AssertionError("non-empty out dir must be refused")


def test_native_ccrusd_group0_is_every_fifth_rife_plate() -> None:
    names = [f"00_{index:04d}" for index in range(RIFE_GROUP0_COUNT)]
    native = native_group0_texture_names(names)
    if native != [f"00_{index:04d}" for index in range(0, RIFE_GROUP0_COUNT, 5)]:
        raise AssertionError(native)
    if len(native) != NATIVE_GROUP0_COUNT:
        raise AssertionError(len(native))
    try:
        native_group0_texture_names(["00_0000", "00_0001"])
    except ValueError as exc:
        if "RIFE frames" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("short group 0 list must be refused")


def test_crop_box_covers_every_opaque_pixel() -> None:
    frames = []
    for index in range(2):
        rgba = np.zeros((32, 40, 4), dtype=np.uint8)
        rgba[10 + index : 14 + index, 12 + index : 18 + index] = (200, 40, 40, 255)
        frames.append(rgba)
    x0, y0, x1, y1 = union_opaque_bbox(frames, pad=2)
    # union cols 12..18 exclusive 19, rows 10..15 exclusive 15, then pad 2
    if (x0, y0, x1, y1) != (10, 8, 21, 17):
        raise AssertionError((x0, y0, x1, y1))


def test_gap_close_fills_pinhole() -> None:
    rgba = np.zeros((8, 8, 4), dtype=np.uint8)
    depth = np.full((8, 8), 0.5, dtype=np.float32)
    rgba[3, 3] = (120, 20, 20, 255)
    rgba[3, 5] = (120, 20, 20, 255)
    rgba[5, 3] = (120, 20, 20, 255)
    rgba[5, 5] = (120, 20, 20, 255)
    filled_rgba, _, stats = prepare_billboard_frame(rgba, depth, gap_close_radius=1)
    if stats["gapFilled"] < 1:
        raise AssertionError(stats)
    if filled_rgba[4, 4, 3] < 20:
        raise AssertionError("diagonal pinhole was not filled")


def test_solid_front_composites_filled_sprite() -> None:
    rgba = np.zeros((8, 8, 4), dtype=np.uint8)
    depth = np.full((8, 8), 0.5, dtype=np.float32)
    rgba[3, 3] = (120, 20, 20, 255)
    rgba[3, 5] = (120, 20, 20, 255)
    rgba[5, 3] = (120, 20, 20, 255)
    rgba[5, 5] = (120, 20, 20, 255)
    points = billboard_points_from_frame(rgba, depth, gap_close_radius=1)
    rendered = render_billboard_points(points, yaw_deg=0.0, perspective=False, solid_front=True)
    if not np.array_equal(rendered, points.source_rgba):
        raise AssertionError("solid front must return the filled source sprite")


def test_bilateral_wing_lateral_splits_depth() -> None:
    from fill import correct_depth_bilateral_wing_lateral

    mask = np.zeros((40, 60), dtype=bool)
    mask[5:15, 10:25] = True
    mask[5:15, 35:50] = True
    mask[20:38, 20:40] = True
    depth = np.full((40, 60), 0.5, dtype=np.float32)
    out = correct_depth_bilateral_wing_lateral(
        depth,
        mask,
        strength=0.4,
        upper_row_fraction=0.5,
        body_lower_fraction=0.5,
    )
    left = out[10, 15]
    right = out[10, 45]
    assert right > left + 0.1


def run() -> dict[str, bool]:
    test_front_view_is_the_original_billboard()
    test_near_pixels_leave_the_billboard_plane()
    test_profile_view_separates_near_and_far()
    test_connected_volume_culls_double_shell_at_profile()
    test_connected_volume_front_and_back_views()
    test_nearer_pixel_wins_when_splats_overlap()
    test_no_triangle_mesh_is_stored()
    test_size_mismatch_is_refused()
    test_empty_sprite_is_refused()
    test_vda_cache_is_required_for_real_clips()
    test_vda_named_cache_loads()
    test_cli_synthetic_writes_orbit_proof()
    test_native_ccrusd_group0_is_every_fifth_rife_plate()
    test_crop_box_covers_every_opaque_pixel()
    test_gap_close_fills_pinhole()
    test_bilateral_wing_lateral_splits_depth()
    test_solid_front_composites_filled_sprite()
    return {"ok": True}


if __name__ == "__main__":
    print(run())
