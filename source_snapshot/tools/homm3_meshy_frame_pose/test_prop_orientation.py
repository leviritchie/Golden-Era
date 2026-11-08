"""In-memory tests for source-evidenced outgoing prop-owner orientation."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owned_rerig import prop_orientation
from owned_rerig.pose_source import SpriteCameraFit
from test_rest_retarget import (
    rotation, fixture as body_fixture, NAMES as BODY_NAMES, PARENTS as BODY_PARENTS,
)


HASH = "a" * 64
NAMES = ["Hips", "RightForeArm", "RightHand"]
PARENTS = [None, 0, 1]
SCREEN = np.array([[1., 0, 0], [0, 1., 0]])


def fixture():
    heads = np.array([[0., 0, 0], [1., .5, -1], [2., .5, -1]])
    points = np.repeat(heads[None], 2, axis=0) + np.array([.1, .3, .2])
    rotations = np.tile(np.eye(3), (2, 3, 1, 1))
    rotations[0, 2] = rotation([0, 1, 0], -.64) @ rotation([1, 0, 0], .41)
    rotations[1, 2] = rotation([0, 1, 0], .44) @ rotation([0, 0, 1], .2)
    motion = {"frame_joints": points, "rotations": rotations,
              "offsets": points - np.einsum("fjab,jb->fja", rotations, heads),
              "skin_rotation_sources": np.array([0, 2, 2]),
              "metadata": {"motionSource": "pred_position"}}
    start = heads[2] + [.2, -.1, 0]
    config = {"schema": "prop_orientation.v1", "sourceMeshSha256": HASH,
              "policy": "preserve-depth-minimum-swing", "owner": "RightHand",
              "axisStart": start.tolist(), "axisEnd": (start + [1, 0, 0]).tolist(),
              "frames": [{"frame": 0, "status": "measured", "grip": [10, 20], "tip": [10, 40]},
                         {"frame": 1, "status": "measured", "grip": [10, 20], "tip": [30, 40]}]}
    return motion, heads, config


def evidence_fixture():
    registration = {"schema": "homm3.static-bind-registration.v1",
                    "acceptance": {"selectedCandidateId": "selected-view"},
                    "views": {"candidates": [{"id": "selected-view", "camera": {
                        "yawDeg": 0, "pitchDeg": 0, "scale": 25, "offset": [30, 45]}}]}}
    files = {"plate0.png": b"plate-zero", "plate1.png": b"plate-one",
             "registration.json": json.dumps(registration).encode()}
    source = [{"globalIndex": i, "clipKey": "g02_idle", "sourcePng": f"plate{i}.png",
               "sourceSha256": hashlib.sha256(files[f"plate{i}.png"]).hexdigest()} for i in range(2)]
    files["master.json"] = json.dumps({"frames": source}).encode()
    config = fixture()[2]
    config["masterSequenceSha256"] = hashlib.sha256(files["master.json"]).hexdigest()
    config["registrationSha256"] = hashlib.sha256(files["registration.json"]).hexdigest()
    for row, frame in zip(config["frames"], source):
        row.update({key: frame[key] for key in ("clipKey", "sourcePng", "sourceSha256")})
    return files, config


def camera_fixture():
    return SpriteCameraFit(right=SCREEN[0].copy(), down=SCREEN[1].copy(),
                           px_per_world=25., offset_px=np.array([30., 45.]),
                           sprite_size=(80, 100), camera_policy="synthetic", source="registration.json")


class PropOrientationTests(unittest.TestCase):
    def orient(self, motion, heads, config, screen=SCREEN, names=NAMES, parents=PARENTS):
        return prop_orientation.orient_prop_owner(motion, heads, parents, names, config, HASH, screen)

    def test_projection_depth_rigidity_anchor_nonowner_and_no_mutation(self):
        motion, heads, config = fixture()
        original, old_heads, old_config = deepcopy(motion), heads.copy(), deepcopy(config)
        result = self.orient(motion, heads, config)
        axis = np.array(config["axisEnd"]) - config["axisStart"]
        axis /= np.linalg.norm(axis)
        vertices = heads[2] + np.array([[0, 0, 0], [.3, .1, -.2], [.7, -.2, .1], [1, .05, .4]])
        rest_distances = np.linalg.norm(vertices[:, None] - vertices[None], axis=-1)
        for f, row in enumerate(config["frames"]):
            before = motion["rotations"][f, 2] @ axis
            after = result["rotations"][f, 2] @ axis
            direction = np.array(row["tip"], float) - row["grip"]
            direction /= np.linalg.norm(direction)
            projected = SCREEN @ after
            np.testing.assert_allclose(projected / np.linalg.norm(projected), direction, atol=1e-12)
            self.assertAlmostEqual(after[2], before[2], places=12)
            self.assertAlmostEqual(np.linalg.norm(projected), np.linalg.norm(SCREEN @ before), places=12)
            posed = vertices @ result["rotations"][f, 2].T + result["offsets"][f, 2]
            np.testing.assert_allclose(np.linalg.norm(posed[:, None] - posed[None], axis=-1),
                                       rest_distances, atol=1e-12)
            np.testing.assert_allclose(posed[0], motion["frame_joints"][f, 2], atol=1e-12)
            # Independent Rodrigues construction: carry the full old orientation, not just its axis.
            cross = np.cross(before, after)
            delta = rotation(cross, np.arctan2(np.linalg.norm(cross), before @ after))
            np.testing.assert_allclose(result["rotations"][f, 2], delta @ motion["rotations"][f, 2], atol=1e-12)
        rotations = result["rotations"]
        np.testing.assert_allclose(rotations @ rotations.swapaxes(-1, -2),
                                   np.broadcast_to(np.eye(3), rotations.shape), atol=1e-12)
        np.testing.assert_allclose(np.linalg.det(rotations), 1, atol=1e-12)
        for key in ("rotations", "offsets"):
            np.testing.assert_array_equal(result[key][:, :2], motion[key][:, :2])
            np.testing.assert_array_equal(motion[key], original[key])
        np.testing.assert_array_equal(result["frame_joints"], motion["frame_joints"])
        np.testing.assert_array_equal(heads, old_heads)
        self.assertEqual(config, old_config)
        result["metadata"]["motionSource"] = "changed"
        self.assertEqual(motion["metadata"], original["metadata"])
        self.assertFalse(result["propOrientationReport"]["accepted"])

    def test_rotated_camera_keeps_camera_depth_not_world_z(self):
        motion, heads, config = fixture()
        q = rotation([1, 2, 3], .7)
        screen = SCREEN @ q.T
        result = self.orient(motion, heads, config, screen)
        forward = np.cross(*screen)
        axis = np.array([1., 0, 0])
        for f, row in enumerate(config["frames"]):
            old_axis, new_axis = motion["rotations"][f, 2] @ axis, result["rotations"][f, 2] @ axis
            self.assertAlmostEqual(forward @ old_axis, forward @ new_axis, places=12)
            desired = np.array(row["tip"], float) - row["grip"]
            desired /= np.linalg.norm(desired)
            actual = screen @ new_axis
            np.testing.assert_allclose(actual / np.linalg.norm(actual), desired, atol=1e-12)

    def test_exact_half_turn_in_screen_plane_is_valid(self):
        motion, heads, config = fixture()
        motion["rotations"][:] = np.eye(3)
        motion["offsets"] = motion["frame_joints"] - heads
        for row in config["frames"]:
            row["grip"], row["tip"] = [20, 20], [0, 20]
        result = self.orient(motion, heads, config)
        np.testing.assert_allclose(result["rotations"][:, 2] @ np.array([1., 0, 0]),
                                   [[-1, 0, 0]] * 2, atol=1e-12)
        np.testing.assert_allclose(np.linalg.det(result["rotations"]), 1, atol=1e-12)

    def test_oblique_half_turn_retains_depth_with_rotated_authored_axes(self):
        axis = np.array([1., 2., 3.]); axis /= np.linalg.norm(axis)
        for angle in (0., .7):
            motion, heads, config = fixture()
            authored = rotation([2, -1, 3], angle)
            motion["rotations"][:, 2] = authored
            motion["offsets"] = motion["frame_joints"] - np.einsum("fjab,jb->fja", motion["rotations"], heads)
            config["axisStart"], config["axisEnd"] = heads[2].tolist(), (heads[2] + axis).tolist()
            screen = np.array([axis, np.array([0., 3., -2.]) / np.sqrt(13)]) @ authored.T
            for row in config["frames"]:
                row.update(grip=[20, 20], tip=[0, 20])
            with self.subTest(authored_angle=angle):
                result = self.orient(motion, heads, config, screen)
                old_axis = authored @ axis
                for f in range(2):
                    actual = result["rotations"][f, 2] @ axis
                    np.testing.assert_allclose(actual, -old_axis, atol=1e-12)
                    self.assertAlmostEqual(np.cross(*screen) @ actual, np.cross(*screen) @ old_axis, places=12)
                np.testing.assert_allclose(np.linalg.det(result["rotations"]), 1, atol=1e-12)
                np.testing.assert_allclose(result["rotations"] @ result["rotations"].swapaxes(-1, -2),
                                           np.broadcast_to(np.eye(3), result["rotations"].shape), atol=1e-12)

    def test_missing_reordered_duplicate_or_ambiguous_frame_evidence_rejected(self):
        for kind in ("missing", "reordered", "duplicate", "ambiguous", "missing-tip", "nan", "short"):
            motion, heads, config = fixture()
            if kind == "missing": config["frames"].pop()
            elif kind == "reordered": config["frames"].reverse()
            elif kind == "duplicate": config["frames"][1]["frame"] = 0
            elif kind == "ambiguous": config["frames"][0]["status"] = "ambiguous"
            elif kind == "missing-tip": del config["frames"][0]["tip"]
            elif kind == "nan": config["frames"][0]["tip"] = [np.nan, 2]
            else: config["frames"][0]["tip"] = [10, 21]
            with self.subTest(kind=kind), self.assertRaises((ValueError, KeyError)):
                self.orient(motion, heads, config)

    def test_unobservable_depth_and_nonleaf_or_wrong_stage_rejected(self):
        motion, heads, config = fixture()
        motion["rotations"][:, 2] = rotation([0, 1, 0], np.pi / 2)
        motion["offsets"] = motion["frame_joints"] - np.einsum("fjab,jb->fja", motion["rotations"], heads)
        with self.assertRaisesRegex(ValueError, "points into view"):
            self.orient(motion, heads, config)
        motion, heads, config = fixture()
        bad = deepcopy(config); bad["owner"] = "RightForeArm"
        with self.assertRaisesRegex(ValueError, "leaf"):
            self.orient(motion, heads, bad)
        without_marker = {k: v for k, v in motion.items() if k != "skin_rotation_sources"}
        with self.assertRaisesRegex(ValueError, "after outgoing"):
            self.orient(without_marker, heads, config)
        with self.assertRaisesRegex(ValueError, "once"):
            self.orient(self.orient(motion, heads, config), heads, config)

    def test_invalid_identity_policy_camera_or_axis_rejected(self):
        motion, heads, config = fixture()
        for key, value in (("sourceMeshSha256", "b"*64), ("schema", "wrong"),
                           ("policy", "infer-depth"), ("owner", "Missing"),
                           ("axisEnd", config["axisStart"]), ("axisEnd", [np.inf, 0, 0])):
            bad = deepcopy(config); bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.orient(motion, heads, bad)
        with self.assertRaisesRegex(ValueError, "orthonormal"):
            self.orient(motion, heads, config, SCREEN * 2)


class OrientationEvidenceTests(unittest.TestCase):
    def load(self, files, config):
        files = {**files, "evidence.json": json.dumps(config).encode()}
        image = MagicMock()
        image.__enter__.return_value.size = (80, 100)
        def read_bytes(path):
            if str(path) not in files:
                raise FileNotFoundError(str(path))
            return files[str(path)]
        with patch.object(Path, "read_bytes", read_bytes), \
             patch.object(Path, "read_text", lambda p, **kwargs: files[str(p)].decode()), \
             patch("PIL.Image.open", return_value=image):
            return prop_orientation.load_orientation_evidence("evidence.json", "master.json", "registration.json")

    def test_optional_upstream_evidence_hash_is_verified_when_declared(self):
        for relative in (True, False):
            files, config = evidence_fixture()
            path = Path(prop_orientation.__file__).resolve().parents[3] / "artifacts/landmarks.json"
            data = b'{"landmarks": "source measured"}'
            files[str(path)] = data
            config.update(landmarkEvidence="artifacts/landmarks.json" if relative else str(path),
                          landmarkEvidenceSha256=hashlib.sha256(data).hexdigest())
            with self.subTest(relative=relative):
                self.assertEqual(self.load(files, config)[0], config)
                files[str(path)] += b"mutation"
                with self.assertRaisesRegex(ValueError, "landmarkEvidenceSha256 mismatch"):
                    self.load(files, config)
                del files[str(path)]
                with self.assertRaises(FileNotFoundError):
                    self.load(files, config)

    def test_partial_or_empty_upstream_declaration_rejected_but_absent_allowed(self):
        files, config = evidence_fixture()
        self.load(files, config)
        declarations = ({"landmarkEvidence": "source.json"}, {"landmarkEvidenceSha256": "a"*64},
                        {"landmarkEvidence": None, "landmarkEvidenceSha256": None},
                        {"landmarkEvidence": "", "landmarkEvidenceSha256": "a"*64},
                        {"landmarkEvidence": "source.json", "landmarkEvidenceSha256": "not-a-hash"})
        for declaration in declarations:
            with self.subTest(declaration=declaration), self.assertRaisesRegex(ValueError, "requires a path and SHA256"):
                self.load(files, {**config, **declaration})

    def test_matching_evidence_loads_registered_camera(self):
        files, config = evidence_fixture()
        actual, camera = self.load(files, config)
        self.assertEqual(actual, config)
        self.assertIsInstance(camera, SpriteCameraFit)
        np.testing.assert_array_equal(camera.basis_rows, [[1, 0, 0], [0, -1, 0]])
        self.assertEqual(camera.px_per_world, 25)
        np.testing.assert_array_equal(camera.offset_px, [30, 45])
        self.assertEqual(camera.sprite_size, (80, 100))
        self.assertEqual(camera.world_frame, "y_up_gltf")
        self.assertEqual(camera.source, "registration.json")
        self.assertEqual(camera.camera_policy, "explicit_selected_static_registration")

    def test_two_candidates_use_selected_camera_not_first(self):
        files, config = evidence_fixture()
        registration = json.loads(files["registration.json"])
        registration["views"]["candidates"].append({"id": "second-view", "camera": {
            "yawDeg": 90, "pitchDeg": 30, "scale": 47, "offset": [12, 34]}})
        registration["acceptance"]["selectedCandidateId"] = "second-view"
        for reverse in (False, True):
            if reverse:
                registration["views"]["candidates"].reverse()
            files["registration.json"] = json.dumps(registration).encode()
            config["registrationSha256"] = hashlib.sha256(files["registration.json"]).hexdigest()
            with self.subTest(reversed_order=reverse):
                _, camera = self.load(files, config)
                np.testing.assert_allclose(camera.basis_rows,
                                           [[0, 0, 1], [-.5, -np.sqrt(3)/2, 0]], atol=1e-12)
                self.assertEqual(camera.px_per_world, 47)
                np.testing.assert_array_equal(camera.offset_px, [12, 34])
                np.testing.assert_allclose(camera.project(np.eye(3)),
                                           [[12, 10.5], [12, 34-47*np.sqrt(3)/2], [59, 34]], atol=1e-12)

    def test_missing_unknown_duplicate_selection_and_wrong_schema_rejected(self):
        for case in ("missing", "unknown", "duplicate", "schema"):
            files, config = evidence_fixture()
            registration = json.loads(files["registration.json"])
            if case == "missing":
                registration.pop("acceptance")
            elif case == "unknown":
                registration["acceptance"]["selectedCandidateId"] = "absent"
            elif case == "duplicate":
                registration["views"]["candidates"] *= 2
            else:
                registration["schema"] = "wrong.v1"
            files["registration.json"] = json.dumps(registration).encode()
            config["registrationSha256"] = hashlib.sha256(files["registration.json"]).hexdigest()
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, "explicitly selected"):
                self.load(files, config)

    def test_occluded_axis_needs_no_fabricated_grip_but_retains_visible_tip(self):
        files, config = evidence_fixture()
        config["frames"][1].update(status="occluded-axis-hold", grip=None,
                                    orientationReferenceFrame=0, mode="released")
        actual, _ = self.load(files, config)
        self.assertIsNone(actual["frames"][1]["grip"])
        config["frames"][1]["tip"] = [80, 30]
        with self.assertRaisesRegex(ValueError, "tip outside source plate"):
            self.load(files, config)

    def test_mutated_master_registration_or_source_plate_rejected(self):
        for path, message in (("master.json", "masterSequenceSha256"),
                              ("registration.json", "registrationSha256"), ("plate1.png", "source plate changed")):
            files, config = evidence_fixture()
            files[path] += b"mutation"
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, message):
                self.load(files, config)

    def test_frame_identity_path_clip_and_hash_must_match_master(self):
        for key, value in (("frame", 1), ("clipKey", "g05_death"),
                           ("sourcePng", "other.png"), ("sourceSha256", "b"*64)):
            files, config = evidence_fixture()
            config["frames"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "provenance"):
                self.load(files, config)
        files, config = evidence_fixture()
        config["frames"].pop()
        with self.assertRaisesRegex(ValueError, "count"):
            self.load(files, config)


class SourcePropMotionTests(unittest.TestCase):
    def setUp(self):
        self.names = list(BODY_NAMES)
        self.parents = list(BODY_PARENTS)
        self.heads = body_fixture(True)
        self.hand = self.names.index("RightHand")
        self.frames = 5
        points = np.repeat(self.heads[None], self.frames, axis=0)
        points += np.array([[0, 0, 0], [.1, .2, .2], [.2, .3, .6], [.3, .1, 1], [.4, .2, 1.3]])[:, None]
        rotations = np.tile(np.eye(3), (self.frames, 25, 1, 1))
        for f in range(self.frames):
            rotations[f, self.hand] = rotation([0, 1, 0], .35 + f * .03) @ rotation([1, 0, 0], .2)
        self.motion = {"frame_joints": points, "rotations": rotations,
                       "offsets": points - np.einsum("fjab,jb->fja", rotations, self.heads),
                       "skin_rotation_sources": np.arange(25)}
        self.joints = np.zeros((6, 4), dtype=np.uint16)
        self.joints[:, 0] = [0, self.hand, self.hand, self.hand, self.hand - 1, 10]
        self.owners = np.array([-1, 0, 0, -1, -1, 1])
        self.config = fixture()[2]
        start = self.heads[self.hand] + [.1, 0, 0]
        self.config.update({"axisStart": start.tolist(), "axisEnd": (start + [.7, 0, 0]).tolist(),
                            "propBone": "OwnedMace", "handPolicy": "rotate-while-held",
                            "releasePolicy": "first-release-depth-plane",
                            "frames": [{"frame": f, "status": "measured", "mode": mode, "clipKey": "g05_death",
                                        "grip": [28 + 2*f, 48 - 3*f], "tip": [35 + 2*f, 60 - 3*f]}
                                       for f, mode in enumerate(["held", "released", "released", "held", "released"])]})
        q = rotation([1, 2, 3], .3)
        self.camera = replace(camera_fixture(), right=q[:, 0], down=q[:, 1])

    def augment(self, config=None, owners=None):
        return prop_orientation.augment_source_prop_motion(
            self.motion, self.heads, self.parents, self.names, self.joints,
            self.owners if owners is None else owners, 0,
            self.config if config is None else config, HASH, self.camera)

    def test_only_owned_vertices_remapped_and_held_hand_and_prop_stay_together(self):
        original = deepcopy(self.motion)
        original_joints, original_heads = self.joints.copy(), self.heads.copy()
        original_config = deepcopy(self.config)
        motion, heads, parents, names, joints = self.augment()
        self.assertEqual(names, self.names + ["OwnedMace"])
        self.assertEqual(parents, self.parents + [0])
        self.assertEqual(motion["frame_joints"].shape, (5, 26, 3))
        self.assertEqual(motion["rotations"].shape, (5, 26, 3, 3))
        self.assertEqual(len(motion["skin_rotation_sources"]), 26)
        np.testing.assert_array_equal(heads[25], self.heads[self.hand])
        np.testing.assert_array_equal(joints[self.owners == 0], [[25, 0, 0, 0]] * 2)
        np.testing.assert_array_equal(joints[self.owners != 0], self.joints[self.owners != 0])
        body = [j for j in range(25) if j != self.hand]
        for key in ("rotations", "offsets", "frame_joints"):
            np.testing.assert_array_equal(motion[key][:, body], self.motion[key][:, body])
            np.testing.assert_array_equal(self.motion[key], original[key])
        np.testing.assert_array_equal(self.joints, original_joints)
        np.testing.assert_array_equal(self.heads, original_heads)
        self.assertEqual(self.config, original_config)
        for f in (0, 3):
            np.testing.assert_array_equal(motion["rotations"][f, 25], motion["rotations"][f, self.hand])
            np.testing.assert_array_equal(motion["offsets"][f, 25], motion["offsets"][f, self.hand])
            self.assertGreater(np.linalg.norm(motion["rotations"][f, self.hand] - self.motion["rotations"][f, self.hand]), .01)
            # Visible shaft-base pixels constrain direction, not the held hand's position.
            np.testing.assert_array_equal(motion["frame_joints"][f, self.hand], self.motion["frame_joints"][f, self.hand])
            tip = motion["rotations"][f, 25] @ np.array(self.config["axisEnd"]) + motion["offsets"][f, 25]
            self.assertGreater(np.linalg.norm(self.camera.project(tip) - self.config["frames"][f]["tip"]), .01)

    def test_released_hand_unchanged_head_projection_depth_and_26_anchors(self):
        motion, heads, _, _, _ = self.augment()
        core = prop_orientation.orient_prop_owner(self.motion, self.heads, self.parents, self.names,
                                                  self.config, HASH, self.camera.basis_rows)
        tip_rest = np.asarray(self.config["axisEnd"])
        depth_by_episode = {}
        for f in (1, 2, 4):
            for key in ("rotations", "offsets", "frame_joints"):
                np.testing.assert_array_equal(motion[key][f, self.hand], self.motion[key][f, self.hand])
            tip = motion["rotations"][f, 25] @ tip_rest + motion["offsets"][f, 25]
            np.testing.assert_allclose(self.camera.project(tip), self.config["frames"][f]["tip"], atol=1e-12)
            episode_start = 1 if f < 3 else 4
            unshifted = core["rotations"][episode_start, self.hand] @ tip_rest + core["offsets"][episode_start, self.hand]
            depth_by_episode[episode_start] = float(unshifted @ self.camera.forward)
            self.assertAlmostEqual(tip @ self.camera.forward, depth_by_episode[episode_start], places=12)
        self.assertGreater(abs(depth_by_episode[4] - depth_by_episode[1]), .1)
        np.testing.assert_allclose(np.einsum("fjab,jb->fja", motion["rotations"], heads) + motion["offsets"],
                                   motion["frame_joints"], atol=1e-12)
        np.testing.assert_allclose(np.linalg.det(motion["rotations"]), 1, atol=1e-12)
        # The new prop is rigid in every frame, regardless of hold/release mode.
        vertices = np.array([tip_rest, tip_rest + [.2, .1, -.1], tip_rest + [-.3, .2, .05]])
        expected = np.linalg.norm(vertices[:, None] - vertices[None], axis=-1)
        for f in range(self.frames):
            posed = vertices @ motion["rotations"][f, 25].T + motion["offsets"][f, 25]
            np.testing.assert_allclose(np.linalg.norm(posed[:, None] - posed[None], axis=-1), expected, atol=1e-12)
        report = motion["propOrientationReport"]
        self.assertEqual((report["heldFrames"], report["releasedFrames"]), (2, 3))
        self.assertFalse(report["accepted"])

    def test_explicit_modes_release_plane_and_prop_ownership_required(self):
        for key, value in (("releasePolicy", None), ("releasePolicy", "guess"),
                           ("handPolicy", None), ("propBone", "RightHand")):
            config = deepcopy(self.config); config[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.augment(config=config)
        config = deepcopy(self.config); config["frames"][1]["mode"] = "occluded"
        with self.assertRaisesRegex(ValueError, "held/released"):
            self.augment(config=config)
        with self.assertRaisesRegex(ValueError, "ownership"):
            self.augment(owners=np.full(6, -1))
        for clip in (None, "", 1):
            config = deepcopy(self.config); config["frames"][1]["clipKey"] = clip
            with self.subTest(clip=clip), self.assertRaisesRegex(ValueError, "clipKey"):
                self.augment(config=config)

    def test_first_release_plane_resets_at_clip_boundary_without_intervening_hold(self):
        config = deepcopy(self.config)
        config["frames"][2]["clipKey"] = "another-clip"
        motion, *_ = self.augment(config=config)
        core = prop_orientation.orient_prop_owner(self.motion, self.heads, self.parents, self.names,
                                                  config, HASH, self.camera.basis_rows)
        depths = []
        tip_rest = np.asarray(config["axisEnd"])
        for f in (1, 2):
            tip = motion["rotations"][f, 25] @ tip_rest + motion["offsets"][f, 25]
            expected = core["rotations"][f, self.hand] @ tip_rest + core["offsets"][f, self.hand]
            self.assertAlmostEqual(tip @ self.camera.forward, expected @ self.camera.forward, places=12)
            depths.append(tip @ self.camera.forward)
        self.assertGreater(abs(depths[1] - depths[0]), .1)

    def occluded_config(self):
        config = deepcopy(self.config)
        config.update(occlusionPolicy="explicit-last-observed-released-axis", maxOccludedFrames=2)
        for row in config["frames"]:
            row["clipKey"] = "g05_death"
            row["mode"] = "released"
        for f in (3, 4):
            config["frames"][f].update(status="occluded-axis-hold", orientationReferenceFrame=2)
            del config["frames"][f]["grip"]
        return config

    def test_two_occluded_axes_hold_observed_rotation_not_hand_or_head_position(self):
        config = self.occluded_config()
        original = deepcopy(config)
        motion, heads, _, _, _ = self.augment(config=config)
        for f in (3, 4):
            np.testing.assert_array_equal(motion["rotations"][f, 25], motion["rotations"][2, 25])
            tip = motion["rotations"][f, 25] @ np.asarray(config["axisEnd"]) + motion["offsets"][f, 25]
            np.testing.assert_allclose(self.camera.project(tip), config["frames"][f]["tip"], atol=1e-12)
            for key in ("rotations", "offsets", "frame_joints"):
                np.testing.assert_array_equal(motion[key][f, self.hand], self.motion[key][f, self.hand])
            report = motion["propOrientationReport"]["frames"][f]
            self.assertEqual(report["status"], "occluded-axis-hold")
            self.assertEqual(report["orientationReferenceFrame"], 2)
            self.assertIsNone(report["angleAfterDeg"])
        np.testing.assert_allclose(np.einsum("fjab,jb->fja", motion["rotations"], heads) + motion["offsets"],
                                   motion["frame_joints"], atol=1e-12)
        self.assertEqual(config, original)

    def test_occluded_hold_rejects_cross_clip_held_overlong_and_invalid_reference(self):
        cases = []
        for f, key, value in ((3, "clipKey", "g01_idle"), (2, "mode", "held"),
                               (3, "mode", "held"), (4, "mode", "held"),
                               (4, "orientationReferenceFrame", 3),
                               (3, "orientationReferenceFrame", 3),
                               (3, "orientationReferenceFrame", True)):
            config = self.occluded_config()
            config["frames"][f][key] = value
            cases.append((f"frame {f} {key}={value}", config))
        for key, value in (("maxOccludedFrames", 1), ("occlusionPolicy", None)):
            config = self.occluded_config(); config[key] = value
            cases.append((key, config))
        for label, config in cases:
            with self.subTest(case=label), self.assertRaisesRegex(ValueError, "invalid explicit released-axis hold"):
                self.augment(config=config)


class SourceVisibleDepthTests(unittest.TestCase):
    def setUp(self):
        self.motion, self.heads, self.config = fixture()
        self.motion["rotations"][:] = np.eye(3)
        self.motion["offsets"][:] = 0
        self.motion["offsets"][:, 0, 2] = [-.5, -1.]
        self.motion["frame_joints"] = self.heads[None] + self.motion["offsets"]
        self.config.update(propBone="SourceMace", handPolicy="rotate-while-held",
                           releasePolicy="source-visible-front-depth-plane",
                           visibilityMargin=.015, headRadius=.3,
                           axisStart=[0, 0, 0], axisEnd=[1, 0, 0])
        for row in self.config["frames"]:
            row.update(mode="released", clipKey="g05_death", grip=[30, 45], tip=[55, 45])
        self.positions = np.array([[-1., -2, 0], [3., -2, 0], [1., 2, 0],
                                   [1., 0, .1], [1.1, 0, -.1], [1., .1, 0]])
        self.indices = np.array([[0, 1, 2], [3, 4, 5]])
        self.joints = np.zeros((6, 4), dtype=np.uint16)
        self.joints[3:, 0] = 2
        self.weights = np.zeros((6, 4))
        self.weights[:, 0] = 1
        self.owners = np.array([-1, -1, -1, 0, 0, 0])
        self.camera = camera_fixture()

    def augment(self, **kwargs):
        return prop_orientation.augment_source_prop_motion(
            self.motion, self.heads, PARENTS, NAMES, self.joints, self.owners, 0,
            self.config, HASH, self.camera,
            **({"positions": self.positions, "weights": self.weights, "indices": self.indices} | kwargs))

    def test_front_plane_uses_tightest_phase_bound_without_changing_xy_or_body(self):
        original = deepcopy(self.motion)
        positions, weights = self.positions.copy(), self.weights.copy()
        motion, heads, _, _, _ = self.augment()
        self.assertEqual(motion["propOrientationReport"]["releasePolicy"], "source-visible-front-depth-plane")
        bounds = motion["propOrientationReport"]["visibilityDepthBounds"]
        np.testing.assert_allclose([bounds[0], bounds[1]], [-.615, -1.115], atol=1e-12)
        # The body triangle encloses the head, but no body corner enters its bounds.
        lower, upper = self.positions[3:, :2].min(axis=0) - .015, self.positions[3:, :2].max(axis=0) + .015
        self.assertFalse(np.any(np.all((self.positions[:3, :2] >= lower) & (self.positions[:3, :2] <= upper), axis=1)))
        for f in range(2):
            tip = motion["rotations"][f, 3] @ np.array([1., 0, 0]) + motion["offsets"][f, 3]
            self.assertAlmostEqual(tip @ self.camera.forward, -1.115, places=12)
            np.testing.assert_allclose(self.camera.project(tip), [55, 45], atol=1e-12)
            head = self.positions[3:] @ motion["rotations"][f, 3].T + motion["offsets"][f, 3]
            body = self.positions[0] + self.motion["offsets"][f, 0]
            self.assertLessEqual(float((head @ self.camera.forward).max()),
                                 float(body @ self.camera.forward) - .015 + 1e-12)
            np.testing.assert_allclose(self.camera.project(head), self.camera.project(self.positions[3:]), atol=1e-12)
        for key in ("frame_joints", "rotations", "offsets"):
            np.testing.assert_array_equal(motion[key][:, :3], original[key])
            np.testing.assert_array_equal(self.motion[key], original[key])
        np.testing.assert_array_equal(self.positions, positions)
        np.testing.assert_array_equal(self.weights, weights)
        np.testing.assert_allclose(np.einsum("fjab,jb->fja", motion["rotations"], heads) + motion["offsets"],
                                   motion["frame_joints"], atol=1e-12)
        self.config["releasePolicy"] = "first-release-depth-plane"
        inherited, *_ = self.augment(positions=None, weights=None)
        np.testing.assert_array_equal(inherited["offsets"][:, 3], np.zeros((2, 3)))

    def test_no_overlap_or_already_front_keeps_inherited_plane(self):
        for case in ("no-overlap", "already-front"):
            positions = self.positions.copy()
            if case == "no-overlap":
                positions[:3, :2] += [10, 10]
            else:
                positions[:3, 2] = 3
            with self.subTest(case=case):
                motion, *_ = self.augment(positions=positions)
                np.testing.assert_array_equal(motion["offsets"][:, 3], np.zeros((2, 3)))
                if case == "no-overlap":
                    self.assertEqual(motion["propOrientationReport"]["visibilityDepthBounds"], {})

    def test_missing_invalid_geometry_and_head_extent_rejected(self):
        nan_positions = self.positions.copy(); nan_positions[0, 0] = np.nan
        nan_weights = self.weights.copy(); nan_weights[0, 0] = np.nan
        for kwargs in ({"positions": None}, {"weights": None}, {"positions": self.positions[:2]},
                       {"weights": self.weights[:, :2]}, {"positions": nan_positions}, {"weights": nan_weights}):
            with self.subTest(inputs=list(kwargs)), self.assertRaisesRegex(ValueError, "needs geometry"):
                self.augment(**kwargs)
        for key, value in (("visibilityMargin", None), ("visibilityMargin", 0),
                           ("headRadius", None), ("headRadius", -1), ("headRadius", np.nan)):
            old = self.config[key]; self.config[key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "needs geometry"):
                self.augment()
            self.config[key] = old
        self.config["headRadius"] = .01
        with self.assertRaisesRegex(ValueError, "too few prop vertices"):
            self.augment()

    def test_visibility_phase_bounds_do_not_cross_clip_boundary(self):
        self.config["frames"][1]["clipKey"] = "another-clip"
        motion, *_ = self.augment()
        np.testing.assert_allclose(motion["offsets"][:, 3, 2], [-.615, -1.115], atol=1e-12)

    def test_missing_invalid_or_unseparated_topology_rejected(self):
        for indices in (None, [], [0, 1], [[0, 1, 9]], [[0, 1, -1]], [[0., 1., 2.]], [[0, 1, 2, 3]]):
            with self.subTest(indices=indices), self.assertRaisesRegex(ValueError, "triangle indices"):
                self.augment(indices=indices)
        with self.assertRaisesRegex(ValueError, "separated"):
            self.augment(indices=np.array([[0, 1, 3], [3, 4, 5]]))
        flat, *_ = self.augment(indices=self.indices.reshape(-1))
        matrix, *_ = self.augment()
        np.testing.assert_array_equal(flat["offsets"], matrix["offsets"])


class TriangleVisibilityTests(unittest.TestCase):
    def test_clipped_depth_interpolates_triangle_plane_not_outside_vertices(self):
        triangle = np.array([[[-2., -2, -6], [2, -2, -2], [0, 2, 4]]])
        for vertices in (triangle, triangle[:, ::-1]):
            nearest = prop_orientation._clipped_triangle_depth(vertices, np.array([-.25, -.25]), np.array([.25, .25]))
            self.assertAlmostEqual(nearest, -.75, places=12)

    def test_bbox_false_positive_rejected_and_edge_touch_included(self):
        outside = np.array([[[0., 2, -1], [2, 0, -1], [2, 2, -1]]])
        self.assertIsNone(prop_orientation._clipped_triangle_depth(outside, np.array([0., 0]), np.array([.5, .5])))
        touching = np.array([[[-1., -1, 2], [0, 0, 3], [-1, 1, 4]]])
        self.assertAlmostEqual(prop_orientation._clipped_triangle_depth(touching, np.array([0., 0]), np.array([1., 1])), 3.)
        self.assertIsNone(prop_orientation._clipped_triangle_depth(np.empty((0, 3, 3)), np.zeros(2), np.ones(2)))


if __name__ == "__main__":
    unittest.main()
