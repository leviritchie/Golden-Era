"""Exact-reference owned bind: the solver must reproduce ground truth, and refuse lies.

The fixture is a synthetic unit that is *exactly* known: a closed two-box body, a six
joint skeleton, a reference capture stated in different units from the mesh, and per-frame
plates rasterised from the true rigid deformation of the swinging arm.  Because the truth is
constructed rather than estimated, every assertion here is a measurement against a known
answer:

* the extent identity recovers the reference scale exactly, and refuses a capture that
  cannot span the mesh;
* the replay driver is the identity at the bind pose and rigid under motion;
* a consistent reference is accepted;
* a corrupted reference, a drifted bone length, a joint moved out of the flesh, a
  reference that is not single-valued, and a rejected registration are all refused.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from owned_rerig.exact_bind import (  # noqa: E402
    ExactBindParams,
    ReferenceInconsistentError,
    articulation_neighbourhoods,
    audit_exact_bind,
    bind_from_exact_reference,
    bone_names_from_capture,
    fit_reference_scale,
    mesh_components,
    nearby_vertex_pairs,
    position_groups,
    replay_deformed_vertices,
    rescale_to_extent,
    skin_by_position_field,
)
from owned_rerig.pose_source import (  # noqa: E402
    AuthoredFrame,
    CaptureToWorld,
    PoseSource,
    SpriteCameraFit,
    load_capture_similarity,
    load_registered_pose_source,
    load_registration_camera_fit,
    yaw_pitch_basis_rows,
)

# --- fixture geometry ------------------------------------------------------- #

# Mesh thickness is chosen to be representative of a real limb radius (well under the
# flesh-clearance budget), so a joint at the body's core is comfortably inside the surface.
BODY = ((-0.30, 0.00, -0.10), (0.30, 1.00, 0.10))
LIMB = ((0.30, 0.82, -0.04), (0.70, 0.88, 0.04))

# mesh-space truth at the bind frame
TRUE_REST = np.array(
    [
        [0.00, 0.50, 0.0],  # Hips  (root)
        [0.00, 0.85, 0.0],  # Spine
        [0.00, 1.00, 0.0],  # Head
        [0.00, 0.00, 0.0],  # LegL
        [0.30, 0.85, 0.0],  # Shoulder
        [0.70, 0.85, 0.0],  # Hand
    ]
)
PARENTS: list[int | None] = [None, 0, 1, 0, 1, 4]
JOINT_NAMES = [
    "mixamorig:Hips",
    "mixamorig:Spine",
    "mixamorig:Head",
    "mixamorig:LeftUpLeg",
    "mixamorig:LeftShoulder",
    "mixamorig:LeftHand",
]
CAPTURE_SCALE = 2.0  # the reference is stated in units twice the mesh's
# The registration is deliberately slightly wrong, the way a real one is; the extent
# identity must recover the true scale exactly from it.
REGISTERED_SCALE = 1.9
SWING_JOINTS = (4, 5)  # Shoulder, Hand follow the arm
PIVOT = TRUE_REST[1].copy()  # the arm swings about the shoulder joint, rigidly
SPRITE_SIZE = (64, 64)
PX_PER_WORLD = 48.0
OFFSET = np.array([17.4, 56.0])


def _box(low, high) -> tuple[np.ndarray, np.ndarray]:
    lo = np.asarray(low, dtype=np.float64)
    hi = np.asarray(high, dtype=np.float64)
    corners = np.array(
        [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    )
    faces = [
        (0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
        (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3),
    ]
    triangles = []
    for a, b, c, d in faces:
        triangles += [(a, b, c), (a, c, d)]
    return corners, np.asarray(triangles, dtype=np.int64).reshape(-1)


def _mesh() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    body_v, body_t = _box(*BODY)
    limb_v, limb_t = _box(*LIMB)
    vertices = np.vstack([body_v, limb_v])
    indices = np.concatenate([body_t, limb_t + len(body_v)])
    limb_rows = np.arange(len(body_v), len(vertices))
    return vertices, indices, limb_rows


def _rot_z(deg: float) -> np.ndarray:
    rad = np.deg2rad(float(deg))
    c, s = np.cos(rad), np.sin(rad)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _true_deform(vertices: np.ndarray, limb_rows: np.ndarray, deg: float) -> np.ndarray:
    out = vertices.copy()
    out[limb_rows] = (vertices[limb_rows] - PIVOT) @ _rot_z(deg).T + PIVOT
    return out


def _true_joints(deg: float) -> np.ndarray:
    out = TRUE_REST.copy()
    rotation = _rot_z(deg)
    for joint in SWING_JOINTS:
        out[joint] = rotation @ (TRUE_REST[joint] - PIVOT) + PIVOT
    return out


def _raster(indices: np.ndarray, vertices: np.ndarray, camera: SpriteCameraFit) -> np.ndarray:
    """Boolean coverage of the projected triangles - the synthetic DEF plate."""
    height, width = camera.sprite_size[1], camera.sprite_size[0]
    px = camera.project(vertices)
    mask = np.zeros((height, width), dtype=bool)
    for triangle in indices.reshape(-1, 3):
        x = px[triangle, 0]
        y = px[triangle, 1]
        x_lo = max(0, int(np.floor(x.min())))
        x_hi = min(width - 1, int(np.ceil(x.max())))
        y_lo = max(0, int(np.floor(y.min())))
        y_hi = min(height - 1, int(np.ceil(y.max())))
        if x_lo > x_hi or y_lo > y_hi:
            continue
        xs = np.arange(x_lo, x_hi + 1) + 0.5
        ys = np.arange(y_lo, y_hi + 1) + 0.5
        grid_x, grid_y = np.meshgrid(xs, ys)
        area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
        if abs(area) < 1e-9:
            continue
        w0 = ((x[1] - grid_x) * (y[2] - grid_y) - (x[2] - grid_x) * (y[1] - grid_y)) / area
        w1 = ((x[2] - grid_x) * (y[0] - grid_y) - (x[0] - grid_x) * (y[2] - grid_y)) / area
        w2 = 1.0 - w0 - w1
        mask[y_lo:y_hi + 1, x_lo:x_hi + 1] |= (
            (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        )
    return mask


def _camera() -> SpriteCameraFit:
    return SpriteCameraFit(
        right=np.array([1.0, 0.0, 0.0]),
        down=np.array([0.0, -1.0, 0.0]),
        px_per_world=PX_PER_WORLD,
        offset_px=OFFSET.copy(),
        sprite_size=SPRITE_SIZE,
        camera_policy="synthetic_source_view",
        source="synthetic",
        world_frame="y_up_gltf",
    )


def _registered_similarity() -> CaptureToWorld:
    return CaptureToWorld(
        rotation=np.eye(3),
        scale=REGISTERED_SCALE,
        translation=np.zeros(3),
        policy="synthetic_registration",
        source="synthetic",
    )


def _true_hand(angle: float) -> np.ndarray:
    return _rot_z(angle) @ (TRUE_REST[5] - PIVOT) + PIVOT


def _pose_source(
    *,
    angles: list[float],
    mesh: tuple[np.ndarray, np.ndarray, np.ndarray],
    corrupt_hand_mirror: bool = False,
) -> PoseSource:
    """Reference whose plates are the true deformation, in units of ``CAPTURE_SCALE``."""
    vertices, indices, limb_rows = mesh
    camera = _camera()
    frames_joints = np.stack([_true_joints(angle) for angle in angles], axis=0)
    if corrupt_hand_mirror:
        for index, angle in enumerate(angles):
            if index == 0:
                continue
            frames_joints[index, 5] = TRUE_REST[5] - (_true_hand(angle) - TRUE_REST[5])
    capture_positions = frames_joints / CAPTURE_SCALE
    plates = np.stack(
        [
            (_raster(indices, _true_deform(vertices, limb_rows, angle), camera) * 255).astype(
                np.uint8
            )
            for angle in angles
        ],
        axis=0,
    )
    return PoseSource(
        source_capture="synthetic",
        source_registration="synthetic",
        joint_names=list(JOINT_NAMES),
        parents=list(PARENTS),
        capture_positions=capture_positions,
        capture_indices=np.arange(len(angles), dtype=np.int64),
        frames=[
            AuthoredFrame(
                index=index,
                def_group=2,
                clip_key="synthetic_idle",
                local_index=index,
                role="cycle",
                source_png=f"synthetic/frame_{index:02d}.png",
            )
            for index in range(len(angles))
        ],
        camera=camera,
        alpha=plates,
        similarity=_registered_similarity(),
        bind_frame=0,
        bind_alpha=plates[0],
        extra={"unit": "synthetic"},
    )


class ExactReferenceBindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mesh = _mesh()

    # --- contract conventions ------------------------------------------------

    def test_yaw_pitch_basis_rows_pins_axis_convention(self) -> None:
        basis = yaw_pitch_basis_rows(0.0, 0.0)
        # Screen y grows downward, so row 1 is -Y: mislabelling it "up" flips the image.
        np.testing.assert_allclose(basis[0], [1.0, 0.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(basis[1], [0.0, -1.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(basis[2], [0.0, 0.0, -1.0], atol=1e-12)
        np.testing.assert_allclose(basis @ basis.T, np.eye(3), atol=1e-12)

    def test_bone_names_from_capture_strips_prefix_and_uniquifies(self) -> None:
        names = bone_names_from_capture(["mixamorig:Hips", "Hips", "", "mixamorig:Hips"])
        self.assertEqual(names, ["Hips", "Hips_1", "Joint_02", "Hips_2"])
        self.assertEqual(len(set(names)), len(names))

    # --- scale identity ------------------------------------------------------

    def test_rescale_to_extent_recovers_known_scale(self) -> None:
        vertices, _indices, _limb = self.mesh
        capture_rest = TRUE_REST / CAPTURE_SCALE
        fitted = rescale_to_extent(
            _registered_similarity(),
            capture_rest,
            axis=1,
            target_min=float(vertices[:, 1].min()),
            target_max=float(vertices[:, 1].max()),
        )
        self.assertAlmostEqual(fitted.scale, CAPTURE_SCALE, places=12)
        mapped = fitted.apply(capture_rest)
        np.testing.assert_allclose(mapped, TRUE_REST, atol=1e-9)

    def test_rescale_to_extent_refuses_non_upright_pose(self) -> None:
        pose = _pose_source(angles=[0.0], mesh=self.mesh)
        # Lay the reference down: the vertical extent is no longer dominant.
        pose.capture_positions = pose.capture_positions.copy()
        pose.capture_positions[:, :, 1] = 0.0
        with self.assertRaises(ReferenceInconsistentError):
            bind_from_exact_reference(
                pose=pose,
                mesh_positions=self.mesh[0],
                mesh_indices=self.mesh[1],
            )

    def test_scale_fit_refuses_capture_that_cannot_span_the_mesh(self) -> None:
        pose = _pose_source(angles=[0.0], mesh=self.mesh)
        # Shrink the capture tenfold: no in-band scale can span the mesh.
        pose.capture_positions = pose.capture_positions / 10.0
        with self.assertRaises(ReferenceInconsistentError):
            bind_from_exact_reference(
                pose=pose,
                mesh_positions=self.mesh[0],
                mesh_indices=self.mesh[1],
            )

    def test_registered_scale_source_is_explicit_verbatim_and_caveated(self) -> None:
        """The extent identity is biped-shaped; a quadruped takes the registered scale by name.

        A quadruped mesh is legitimately longer than it is tall, so the extent identity cannot
        choose a scale for its bind pose and refuses.  The second option must therefore exist, but
        only explicitly: it fits nothing, keeps the registration's scale to the digit, and carries
        the extents it did not use so the caveat travels with the report.
        """
        pose = _pose_source(angles=[0.0], mesh=self.mesh)
        # Squash the stance vertically so the reference is no longer upright, the way a quadruped's
        # bind pose is not - but not to zero, which the no-vertical-extent guard would catch first.
        pose.capture_positions = pose.capture_positions * np.array([1.0, 0.1, 1.0])
        vertices, indices, _limb = self.mesh

        # The default still refuses the very same pose: the second source is not a fallback.
        with self.assertRaises(ReferenceInconsistentError):
            fit_reference_scale(
                pose=pose,
                mesh_positions=vertices,
                mesh_indices=indices,
                params=ExactBindParams(),
            )

        params = ExactBindParams()
        params.scale_source = "registered"
        similarity, fit = fit_reference_scale(
            pose=pose, mesh_positions=vertices, mesh_indices=indices, params=params
        )
        self.assertEqual(fit["scaleSource"], "registered")
        self.assertEqual(fit["criterion"], "registration_scale_taken_verbatim")
        self.assertAlmostEqual(float(fit["fittedScale"]), REGISTERED_SCALE, places=12)
        self.assertAlmostEqual(float(similarity.scale), REGISTERED_SCALE, places=12)
        self.assertAlmostEqual(float(fit["correctionFactor"]), 1.0, places=12)
        self.assertIsNone(fit["anchorAxis"])
        # Nothing is refitted, so before and after are the same mapping and the same distance.
        self.assertAlmostEqual(
            float(fit["meanDistanceBefore"]), float(fit["meanDistanceAfter"]), places=12
        )
        # The extents the identity would have used are reported with the mismatch they carry.
        self.assertGreater(float(fit["extentRatios"]["y"]), 1.0)
        self.assertIn("not upright", str(fit["scaleCaveat"]))

        # An unknown source is refused rather than quietly treated as one of the two.
        params.scale_source = "guess"
        with self.assertRaises(ValueError):
            fit_reference_scale(
                pose=pose, mesh_positions=vertices, mesh_indices=indices, params=params
            )

    # --- replay driver -------------------------------------------------------

    def test_replay_is_identity_at_bind_and_rigid_under_motion(self) -> None:
        vertices, indices, limb_rows = self.mesh
        pose = _pose_source(angles=[0.0, 25.0], mesh=self.mesh)
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=vertices, mesh_indices=indices
        )
        heads = result["heads"]
        joints = result["joints"]
        weights = result["weights"]
        # The reference must be read through the *fitted* similarity, the same one the bind was
        # solved with: the registered one is 5% off and would show up as a 5% driver error.
        fitted = rescale_to_extent(
            _registered_similarity(),
            pose.capture_positions[0],
            axis=1,
            target_min=float(vertices[:, 1].min()),
            target_max=float(vertices[:, 1].max()),
        )
        pose_frames = fitted.apply(pose.capture_positions[pose.capture_indices])
        np.testing.assert_allclose(pose_frames[0], heads, atol=1e-9)

        rest = replay_deformed_vertices(
            positions=vertices,
            heads=heads,
            parents=PARENTS,
            joints=joints,
            weights=weights,
            frame_joints=heads.copy(),
        )
        np.testing.assert_allclose(rest, vertices, atol=1e-9)

        # A pure swing about Z moves the arm rigidly, so a vertex the arm fully owns must follow the
        # truth exactly.  The ownership is stated here rather than read off the solved skin: the
        # field deliberately blends across every joint, so "fully owned" is a property of this
        # driver test, not of a good bind.  What is under test is that the driver's transform is the
        # rigid one, not how sharply the field splits a vertex between bones.
        rigid_joints = np.zeros((len(vertices), 4), dtype=np.int32)
        rigid_weights = np.zeros((len(vertices), 4), dtype=np.float64)
        rigid_weights[:, 0] = 1.0
        rigid_joints[limb_rows, 0] = SWING_JOINTS[-1]  # the hand, which follows the arm
        moved = replay_deformed_vertices(
            positions=vertices,
            heads=heads,
            parents=PARENTS,
            joints=rigid_joints,
            weights=rigid_weights,
            frame_joints=pose_frames[1],
        )
        truth = _true_deform(vertices, limb_rows, 25.0)
        # Float64 composition of a re-derived rotation, not an algebraic identity: the rest case
        # above is exact because its rotation is the identity, this one is exact to rounding.
        self.assertLess(float(np.abs(moved[limb_rows] - truth[limb_rows]).max()), 1e-5)
        # Vertices the arm does not influence at all must not have been dragged by it.  Which body
        # vertices the shoulder claims or shares is an ownership decision the audit judges, not a
        # driver property.
        touched = (
            np.isin(joints[:, :4], SWING_JOINTS) & (weights[:, :4] > 0.0)
        ).any(axis=1)
        body_rows = np.setdiff1d(np.arange(len(vertices)), limb_rows)
        still = body_rows[~touched[body_rows]]
        self.assertGreater(still.size, 0)
        self.assertLess(float(np.abs(moved[still] - vertices[still]).max()), 1e-9)

    # --- acceptance ----------------------------------------------------------

    def test_audit_passes_on_consistent_reference(self) -> None:
        vertices, indices, _limb = self.mesh
        pose = _pose_source(angles=[0.0, 1.5, 3.0, 4.0], mesh=self.mesh)
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=vertices, mesh_indices=indices
        )
        audit = result["audit"]
        self.assertEqual(audit["issues"], [])
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["containmentProof"], "closed_mesh_ray_parity_available")
        self.assertEqual(audit["boundaryEdges"], 0)
        self.assertAlmostEqual(result["scaleFit"]["fittedScale"], CAPTURE_SCALE, places=12)
        self.assertLessEqual(result["restIdentityMaxError"], 1e-9)
        self.assertLessEqual(audit["maxBoneLengthDrift"], 1e-9)
        self.assertLessEqual(audit["maxOutsideExcess"], audit["outsideExcessBudget"])
        self.assertEqual(len(result["boneNames"]), len(JOINT_NAMES))

    def test_audit_passes_on_large_pose_excursion(self) -> None:
        vertices, indices, _limb = self.mesh
        pose = _pose_source(angles=[0.0, 10.0, 20.0, 30.0], mesh=self.mesh)
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=vertices, mesh_indices=indices
        )
        audit = result["audit"]
        self.assertLess(float(audit["referenceRigidity"]["medianLengthExcursion"]), 1e-9)
        self.assertLess(float(audit["referenceRigidity"]["maxLengthExcursion"]), 1e-9)
        self.assertEqual(audit["issues"], [])
        self.assertLess(float(audit["maxOutsideExcess"]), 0.02)

    def test_audit_fails_closed_on_corrupted_motion(self) -> None:
        vertices, indices, _limb = self.mesh
        pose = _pose_source(angles=[0.0, 10.0, 20.0, 30.0], mesh=self.mesh, corrupt_hand_mirror=True)
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=vertices, mesh_indices=indices
        )
        audit = result["audit"]
        self.assertFalse(audit["ok"])
        self.assertTrue(audit["issues"])
        joined = " ".join(audit["issues"])
        self.assertIn("Hand", joined)

    def test_audit_fails_closed_on_bone_length_drift(self) -> None:
        vertices, indices, _limb = self.mesh
        pose = _pose_source(angles=[0.0, 1.0], mesh=self.mesh)
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=vertices, mesh_indices=indices
        )
        heads = result["heads"].copy()
        heads[5] = heads[5] + np.array([0.25, 0.0, 0.0])  # stretch Shoulder->Hand
        audit = audit_exact_bind(
            pose=pose,
            similarity=rescale_to_extent(
                _registered_similarity(),
                pose.capture_positions[0],
                axis=1,
                target_min=float(vertices[:, 1].min()),
                target_max=float(vertices[:, 1].max()),
            ),
            mesh_positions=vertices,
            mesh_indices=indices,
            parents=list(PARENTS),
            bone_names=bone_names_from_capture(JOINT_NAMES),
            heads=heads,
            joints=result["joints"],
            weights=result["weights"],
            scale_fit=result["scaleFit"],
            params=ExactBindParams(),
        )
        self.assertFalse(audit["ok"])
        self.assertTrue(any("drifts" in issue for issue in audit["issues"]), audit["issues"])

    def test_audit_fails_closed_when_joint_leaves_the_flesh(self) -> None:
        vertices, indices, _limb = self.mesh
        pose = _pose_source(angles=[0.0, 1.0], mesh=self.mesh)
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=vertices, mesh_indices=indices
        )
        heads = result["heads"].copy()
        heads[5] = heads[5] + np.array([0.0, 0.0, 1.20])  # far outside the thin arm
        audit = audit_exact_bind(
            pose=pose,
            similarity=rescale_to_extent(
                _registered_similarity(),
                pose.capture_positions[0],
                axis=1,
                target_min=float(vertices[:, 1].min()),
                target_max=float(vertices[:, 1].max()),
            ),
            mesh_positions=vertices,
            mesh_indices=indices,
            parents=list(PARENTS),
            bone_names=bone_names_from_capture(JOINT_NAMES),
            heads=heads,
            joints=result["joints"],
            weights=result["weights"],
            scale_fit=result["scaleFit"],
            params=ExactBindParams(),
        )
        self.assertFalse(audit["ok"])
        self.assertTrue(any("flesh pivot" in issue for issue in audit["issues"]), audit["issues"])

    # --- reference contract --------------------------------------------------

    def _write_reference(self, tmp: Path, *, accepted: bool, frames: list[dict]) -> tuple[Path, Path, Path]:
        from PIL import Image

        plate = tmp / "plate.png"
        Image.fromarray(np.full((32, 32, 4), 255, dtype=np.uint8)).save(plate)
        other = tmp / "plate_b.png"
        Image.fromarray(np.full((32, 32, 4), 255, dtype=np.uint8)).save(other)
        capture = tmp / "raw_capture.npz"
        np.savez_compressed(
            capture,
            pred_position=np.zeros((len(frames), 3, 3), dtype=np.float64),
            joint_names=np.asarray(["mixamorig:Hips", "mixamorig:Spine", "mixamorig:Head"]),
            parents=np.asarray([-1, 0, 1]),
        )
        master = tmp / "master_sequence.json"
        master.write_text(
            json.dumps(
                {
                    "schema": "homm3.linked-master-sequence.v2",
                    "unit": "synthetic",
                    "bindGlobalIndex": 0,
                    "segments": [
                        {
                            "segmentIndex": 0,
                            "clipKey": "synthetic_idle",
                            "globalStart": 0,
                            "globalEnd": len(frames),
                            "role": "cycle",
                        }
                    ],
                    "frames": frames,
                }
            ),
            encoding="utf-8",
        )
        registration = tmp / "idle0_registration.json"
        registration.write_text(
            json.dumps(
                {
                    "schema": "homm3.static-bind-registration.v1",
                    "unit": "synthetic",
                    "bindFrame": 0,
                    "mesh": "synthetic.glb",
                    "acceptance": {"status": "accepted", "accepted": accepted},
                    "views": {
                        "candidates": [
                            {
                                "camera": {
                                    "yawDeg": 0.0,
                                    "pitchDeg": 0.0,
                                    "scale": 4.0,
                                    "offset": [16.0, 16.0],
                                },
                                "skeletonSimilarity": {
                                    "rotation": np.eye(3).tolist(),
                                    "scale": 1.0,
                                    "translation": [0.0, 0.0, 0.0],
                                    "policy": "synthetic",
                                },
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        return capture, registration, master

    def test_loader_refuses_a_reference_that_is_not_single_valued(self) -> None:
        def row(index: int, png: Path) -> dict:
            return {
                "globalIndex": index,
                "segmentIndex": 0,
                "clipKey": "synthetic_idle",
                "defGroup": 2,
                "role": "cycle",
                "localIndex": index,
                "sourcePng": str(png).replace("\\", "/"),
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from PIL import Image

            first = root / "a.png"
            Image.fromarray(np.zeros((32, 32, 4), dtype=np.uint8)).save(first)
            capture, registration, master = self._write_reference(
                root, accepted=True, frames=[row(0, first), row(1, first)]
            )
            with self.assertRaises(ReferenceInconsistentError) as caught:
                load_registered_pose_source(
                    capture=capture, registration=registration, master_sequence=master
                )
            self.assertIn("not single-valued", str(caught.exception))

    def test_loader_accepts_distinct_plates(self) -> None:
        def row(index: int, png: Path) -> dict:
            return {
                "globalIndex": index,
                "segmentIndex": 0,
                "clipKey": "synthetic_idle",
                "defGroup": 2,
                "role": "cycle",
                "localIndex": index,
                "sourcePng": str(png).replace("\\", "/"),
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from PIL import Image

            first = root / "a.png"
            second = root / "b.png"
            Image.fromarray(np.zeros((32, 32, 4), dtype=np.uint8)).save(first)
            Image.fromarray(np.zeros((32, 32, 4), dtype=np.uint8)).save(second)
            capture, registration, master = self._write_reference(
                root, accepted=True, frames=[row(0, first), row(1, second)]
            )
            pose = load_registered_pose_source(
                capture=capture, registration=registration, master_sequence=master
            )
            self.assertEqual(pose.frame_count, 2)
            self.assertEqual(pose.sprite_size, (32, 32))
            self.assertIsNotNone(pose.bind_alpha)

    def test_loader_applies_explicit_unit_local_source_view_yaw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            camera_path = root / "registration.json"
            camera_path.write_text(
                json.dumps(
                    {
                        "schema": "homm3.static-bind-registration.v1",
                        "acceptance": {"accepted": True, "status": "accepted"},
                        "views": {
                            "candidates": [
                                {
                                    "camera": {
                                        "yawDeg": 0.0,
                                        "pitchDeg": 0.0,
                                        "scale": 4.0,
                                        "offset": [16.0, 16.0],
                                    }
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            camera = load_registration_camera_fit(
                camera_path,
                sprite_size=(32, 32),
                source_view_yaw_offset_deg=45.0,
            )
            np.testing.assert_allclose(
                camera.right,
                yaw_pitch_basis_rows(45.0, 0.0)[0],
            )
            self.assertIn("yawOffset45", camera.camera_policy)

    def test_loader_refuses_a_rejected_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from PIL import Image

            plate = root / "a.png"
            Image.fromarray(np.zeros((32, 32, 4), dtype=np.uint8)).save(plate)
            _capture, registration, _master = self._write_reference(
                root,
                accepted=False,
                frames=[
                    {
                        "globalIndex": 0,
                        "segmentIndex": 0,
                        "clipKey": "synthetic_idle",
                        "defGroup": 2,
                        "role": "cycle",
                        "localIndex": 0,
                        "sourcePng": str(plate).replace("\\", "/"),
                    }
                ],
            )
            with self.assertRaises(ValueError):
                load_capture_similarity(registration)

    # --- weights are a function of position ----------------------------------

    def test_components_are_topological_not_proximity(self) -> None:
        # The fixture's two boxes touch nothing, so they are two components even where they are
        # close: closeness is exactly what a card-soup mesh cannot be trusted to mean.  Components
        # are reported and used to count the split, never to decide a vertex's weights.
        vertices, indices, _limb_rows = self.mesh
        components = mesh_components(indices, len(vertices))
        self.assertEqual(len(np.unique(components)), 2)
        self.assertEqual(len(components), len(vertices))

    def test_articulation_neighbourhoods_follow_the_tree(self) -> None:
        # 0 root; children 1 and 3; 2 and 4 children of 1; 5 a child of 4.
        parents = [None, 0, 1, 0, 1, 4]
        neighbourhoods = articulation_neighbourhoods(parents)
        self.assertEqual(neighbourhoods[0], {0, 1, 3})
        self.assertEqual(neighbourhoods[1], {0, 1, 2, 4})
        self.assertEqual(neighbourhoods[2], {1, 2})
        # 2 (deep in one chain) and 5 (deep in the other) share no articulating bone.  This is
        # reported rather than enforced: enforcing it was measured to trade tearing for holes.
        self.assertEqual(neighbourhoods[2] & neighbourhoods[5], set())
        # A parent and its child do: that link is exactly what the animation articulates.
        self.assertTrue(neighbourhoods[4] & neighbourhoods[5])

    def test_position_groups_collapse_the_exporter_split_exactly(self) -> None:
        positions = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [1.0, 1.0, 0.0],
                [0.0, 0.0, 0.0],
                [1.0, 1.0, 0.0],
            ]
        )
        group, representative = position_groups(positions)
        self.assertEqual(len(np.unique(group)), 3)
        self.assertEqual(int(group[0]), int(group[3]))
        self.assertEqual(int(group[2]), int(group[4]))
        self.assertEqual(len(representative), len(positions))
        for index in range(len(positions)):
            self.assertEqual(int(representative[index]), int(np.flatnonzero(group == group[index])[0]))
        # A near-duplicate is not a duplicate: the grouping is exact, so it has no tolerance to tune.
        nudged = positions.copy()
        nudged[3, 0] = 1e-7
        self.assertEqual(len(np.unique(position_groups(nudged)[0])), 4)

    def _split_quad(self) -> tuple[np.ndarray, np.ndarray]:
        """One sheet of flesh delivered as two patches that share no index.

        Triangle A is (0,1,2) and triangle B is (3,4,5); vertices 3 and 4 are bit-identical copies
        of 1 and 2, which is what an exporter does at a UV seam or a hard edge.
        """
        positions = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [1.0, 1.0, 0.0],
                [1.0, 0.0, 0.0],
                [1.0, 1.0, 0.0],
                [0.0, 1.0, 0.0],
            ]
        )
        indices = np.array([0, 1, 2, 3, 4, 5], dtype=np.int64)
        return positions, indices

    def test_a_vertex_split_off_by_the_exporter_keeps_the_same_weights(self) -> None:
        # The whole point of keying on position: the two copies of a vertex are at the same point, so
        # they must be driven by the same transform.  Any rule keyed on patch identity drives them
        # apart and opens the seam into a hole when the animation moves the limb.
        positions, indices = self._split_quad()
        self.assertEqual(len(np.unique(mesh_components(indices, len(positions)))), 2)
        heads = np.array([[0.0, 0.0, 0.0], [0.6, 0.0, 0.0]])
        skin = skin_by_position_field(
            positions=positions,
            mesh_indices=indices,
            heads=heads,
            tails=heads + np.array([0.2, 0.0, 0.0]),
            parents=[None, 0],
            bone_names=["mixamorig:Hips", "mixamorig:LeftHand"],
            params=ExactBindParams(),
        )
        for left, right in ((1, 3), (2, 4)):
            np.testing.assert_array_equal(skin["joints"][left], skin["joints"][right])
            np.testing.assert_array_equal(skin["weights"][left], skin["weights"][right])
        field = skin["positionField"]
        self.assertEqual(field["schema"], "position_field_weights.v1")
        self.assertEqual(field["rule"], "inverse_distance_to_flesh_bones_strongest_four")
        self.assertEqual(field["candidateBones"], 2)
        self.assertEqual(field["markerBonesExcluded"], [])
        self.assertEqual(field["coincidentWeightMismatch"], 0.0)
        self.assertEqual(field["verticesInCoincidentGroups"], 4)
        self.assertEqual(field["largestCoincidentGroup"], 2)
        self.assertEqual(field["meshPatches"], 2)
        self.assertEqual(field["maxInfluencesPerVertex"], 2)
        # Four columns even though the reference has two bones: JOINTS_0/WEIGHTS_0 are VEC4.
        self.assertEqual(skin["joints"].shape, (len(positions), 4))
        for row in range(len(positions)):
            self.assertAlmostEqual(float(skin["weights"][row].sum()), 1.0, places=12)

    def test_a_marker_bone_is_not_a_candidate_for_flesh(self) -> None:
        # A Mixamo terminal marker is extrapolated by the capture past the surface, so its track
        # carries the lift's error.  Flesh driven by one is dragged by that error while the flesh
        # beside it is not - which is what tore this unit's toes at 15x their edge length when the
        # ownership repair handed a vertex to RightToe_End.
        positions, indices = self._split_quad()
        heads = np.array([[0.0, 0.0, 0.0], [0.6, 0.0, 0.0]])
        skin = skin_by_position_field(
            positions=positions,
            mesh_indices=indices,
            heads=heads,
            tails=heads + np.array([0.2, 0.0, 0.0]),
            parents=[None, 0],
            bone_names=["mixamorig:Hips", "mixamorig:LeftToe_End"],
            params=ExactBindParams(),
        )
        field = skin["positionField"]
        self.assertEqual(field["markerBonesExcluded"], ["mixamorig:LeftToe_End"])
        self.assertEqual(field["candidateBones"], 1)
        # The marker owns no flesh, and no vertex is driven by it.
        self.assertNotIn(1, set(int(v) for v in skin["joints"].reshape(-1).tolist()))
        self.assertEqual(skin["forcedOwnership"], [])
        for row in range(len(positions)):
            self.assertEqual(int(skin["joints"][row, 0]), 0)
            self.assertAlmostEqual(float(skin["weights"][row, 0]), 1.0, places=12)

    def test_the_field_reports_the_blend_the_strict_relation_forbids(self) -> None:
        # The trade is reported, not hidden: this field does blend bones outside the articulation
        # relation, and the count of vertices that do so is part of the bind evidence.
        positions, indices = self._split_quad()
        heads = np.array([[0.0, 0.0, 0.0], [0.6, 0.0, 0.0]])
        parents: list[int | None] = [None, 0]
        skin = skin_by_position_field(
            positions=positions,
            mesh_indices=indices,
            heads=heads,
            tails=heads + np.array([0.2, 0.0, 0.0]),
            parents=parents,
            bone_names=["mixamorig:Hips", "mixamorig:LeftHand"],
            params=ExactBindParams(),
        )
        # A single link: every neighbourhood intersects, so there is nothing to report.
        self.assertEqual(skin["positionField"]["groupsBlendingUnarticulatedBones"], 0)
        # And the reported number must equal the definition applied to the delivered weights.
        neighbourhoods = articulation_neighbourhoods(parents)
        group, representative = position_groups(positions)
        expected = 0
        weighted = 0
        sizes = np.bincount(group)
        for row in np.unique(representative):
            strongest = int(skin["joints"][row, 0])
            second = int(skin["joints"][row, 1])
            if skin["weights"][row, 1] <= 0.0:
                second = strongest
            if not (neighbourhoods[strongest] & neighbourhoods[second]):
                expected += 1
                weighted += int(sizes[group[row]])
        self.assertEqual(
            skin["positionField"]["groupsBlendingUnarticulatedBones"], expected
        )
        self.assertEqual(
            skin["positionField"]["verticesBlendingUnarticulatedBones"], weighted
        )
        self.assertEqual(skin["positionField"]["coincidentWeightMismatch"], 0.0)

    def test_nearby_vertex_pairs_are_found_by_distance_not_by_index(self) -> None:
        positions, _indices = self._split_quad()
        # The two coincident pairs are found because they are at the same point, not because they
        # are adjacent in the index buffer.
        found = {tuple(sorted(pair.tolist())) for pair in nearby_vertex_pairs(positions, 0.25)}
        self.assertEqual(found, {(1, 3), (2, 4)})
        # Widening the radius picks up the vertices that are merely close, and every pair it returns
        # is inside the radius by construction.
        wide = nearby_vertex_pairs(positions, 1.5)
        wide_found = {tuple(sorted(pair.tolist())) for pair in wide}
        self.assertIn((0, 5), wide_found)
        self.assertIn((1, 2), wide_found)
        self.assertIn((0, 3), wide_found)
        for left, right in wide:
            self.assertLessEqual(
                float(np.linalg.norm(positions[left] - positions[right])), 1.5 + 1e-12
            )
        with self.assertRaises(ValueError):
            nearby_vertex_pairs(positions, 0.0)

    def test_the_audit_reports_tearing_and_cohesion_separately_from_containment(self) -> None:
        # Containment says the silhouette is right; it says nothing about a surface being stretched or
        # pulled apart.  Both distortion measures must be present, because either one alone can be
        # improved by making the other worse: freezing a patch onto one bone lowers its edge stretch
        # and opens a hole at the seam instead.
        vertices, indices, _limb = self.mesh
        pose = _pose_source(angles=[0.0, 1.5, 3.0, 4.0], mesh=self.mesh)
        params = ExactBindParams(cohesion_radius_frac=0.1)
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=vertices, mesh_indices=indices, params=params
        )
        audit = result["audit"]
        self.assertTrue(audit["ok"], audit["issues"])
        tearing = audit["tearing"]
        self.assertEqual(tearing["schema"], "edge_stretch.v1")
        self.assertTrue(tearing["edges"] > 0)
        # A rigid bind on a rigid reference keeps every edge inside the review limit; a vertex
        # blended between bones the animation moves apart tears at tens of times that.
        self.assertEqual(tearing["edgesPastReviewLimit"], 0)
        self.assertEqual(tearing["edgesPastTenTimesReviewLimit"], 0)
        self.assertLess(float(tearing["max"]), float(tearing["reviewLimit"]))
        cohesion = audit["cohesion"]
        self.assertEqual(cohesion["schema"], "surface_cohesion.v1")
        self.assertAlmostEqual(
            float(cohesion["radius"]), 0.1 * float(audit["subjectHeight"]), places=12
        )
        self.assertTrue(cohesion["pairs"] > 0)
        self.assertEqual(cohesion["pairsOpenedPastRadius"], 0)
        self.assertLess(float(cohesion["worstGap"]), float(cohesion["radius"]))
        self.assertEqual(result["skin"]["positionField"]["schema"], "position_field_weights.v1")

    def test_the_audit_names_a_region_attached_to_the_wrong_part(self) -> None:
        # A prop fused to the wrong limb is a small region of geometry that leaves the frame's own
        # plate while the body stays inside.  One global escape fraction cannot say which geometry it
        # is, so the audit has to group the escaping vertices and name what drives them.
        vertices, indices, _limb = self.mesh
        pose = _pose_source(angles=[0.0, 25.0, 30.0, 35.0], mesh=self.mesh)
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=vertices, mesh_indices=indices
        )
        escaping = result["audit"]["escaping"]
        self.assertEqual(escaping["schema"], "escape_regions.v1")
        self.assertEqual(escaping["regions"], [], "a clean bind leaves nothing outside its plates")

        # Now leave the arm behind: give the limb box to the root, which never moves.  Those vertices
        # must leave the plates, and the audit must point at them and at the bone that held them.
        joints = result["joints"].copy()
        weights = result["weights"].copy()
        limb_rows = self.mesh[2]
        self.assertGreater(limb_rows.size, 0)
        joints[limb_rows, :] = 0
        weights[limb_rows, :] = 0.0
        joints[limb_rows, 0] = 0
        weights[limb_rows, 0] = 1.0
        audit = audit_exact_bind(
            pose=pose,
            similarity=rescale_to_extent(
                _registered_similarity(),
                pose.capture_positions[0],
                axis=1,
                target_min=float(vertices[:, 1].min()),
                target_max=float(vertices[:, 1].max()),
            ),
            mesh_positions=vertices,
            mesh_indices=indices,
            parents=PARENTS,
            bone_names=JOINT_NAMES,
            heads=result["heads"],
            joints=joints,
            weights=weights,
            scale_fit=result["scaleFit"],
            # The fixture's boxes are sampled at 6-8 cm spacing, so the grouping radius is set to this
            # fixture's sampling rather than to the shipped fraction of a real subject's height.  The
            # radius only groups the report; it never decides what counts as an escape.
            params=ExactBindParams(escape_region_radius_frac=0.2),
        )
        escaping = audit["escaping"]
        self.assertEqual(escaping["schema"], "escape_regions.v1")
        self.assertGreater(escaping["verticesEscapingAtLeastOnce"], 0)
        self.assertTrue(escaping["regions"])
        # The list is the population, not a preview of it: a truncation would hide the largest region
        # behind the one that merely reaches furthest outside the plate.
        self.assertEqual(escaping["regionCount"], len(escaping["regions"]))
        largest = escaping["regions"][0]
        self.assertIn("mixamorig:Hips", largest["drivingBones"])
        self.assertGreaterEqual(largest["framesEscaped"], 1)
        self.assertGreaterEqual(largest["vertices"], 3)
        # The region is reported in the plate's own pixels, so a reader can point at it.
        self.assertEqual(len(largest["centroidPlatePixel"]), 2)
        self.assertGreater(largest["maxDistanceOutsidePlatePx"], 0.0)

    def test_every_reported_vertex_is_owned_by_the_bone_that_drives_it(self) -> None:
        # Every bone must own at least one vertex or the audit refuses the bind, and with a field the
        # ownership repair has to act on a whole position group rather than on one vertex of it.
        vertices, indices, _limb = self.mesh
        pose = _pose_source(angles=[0.0, 1.5, 3.0, 4.0], mesh=self.mesh)
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=vertices, mesh_indices=indices
        )
        audit = result["audit"]
        self.assertTrue(audit["ok"], audit["issues"])
        owners = {row["bone"] for row in audit["ownership"] if row["ownedVertices"] > 0}
        self.assertEqual(len(owners), len(result["boneNames"]))
        joints = result["joints"]
        weights = result["weights"]
        for joint, name in enumerate(result["boneNames"]):
            rows = np.flatnonzero(np.any((joints == joint) & (weights > 0.05), axis=1))
            self.assertTrue(rows.size, f"{name} owns no vertex")


if __name__ == "__main__":
    unittest.main()
