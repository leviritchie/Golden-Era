import json
import shutil
import uuid
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from experiments.homm3_mocap_v2.prepare_mounted_skin_asset import _sha, _weights, activate_candidate, prepare


class MountedSkinTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / (".mounted_test_" + uuid.uuid4().hex)
        self.root.mkdir()
        self.names = [f"j{i}" for i in range(61)]
        self.parents = np.full(61, -1, dtype=np.int64)
        self.parents[1:] = np.arange(60)
        self.rest = np.stack([np.array([float(i), 0, 0]) for i in range(61)])

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_capsule_weights_are_owned_and_rigid_attachment_is_exact(self):
        vertices = np.array([[0.5, 0, 0], [10, 0, 0]], dtype=float)
        weights = _weights(vertices, ["body", "sword"], self.names, self.parents, self.rest,
                           {"body": ["j0", "j1"]}, {"sword": ["j10"]})
        self.assertAlmostEqual(weights[0].sum(), 1.0)
        self.assertEqual(weights[1, 10], 1.0)
        self.assertEqual(np.count_nonzero(weights[1]), 1)

    def test_region_limit_and_missing_ownership_fail_closed(self):
        vertices = np.zeros((1, 3))
        with self.assertRaises(ValueError):
            _weights(vertices, ["body"], self.names, self.parents, self.rest,
                     {"body": self.names[:9]}, {})
        with self.assertRaises(ValueError):
            _weights(vertices, ["unknown"], self.names, self.parents, self.rest,
                     {"body": ["j0"]}, {})

    def test_prepare_writes_frozen_npz_and_refuses_existing_output(self):
        mesh = self.root / "wolf.glb"
        mesh.write_bytes(b"mesh-pinned")
        profile_file = self.root / "wolf_profile.json"
        profile_file.write_text('{"profile":"authored"}', encoding="utf-8")
        manifest_file = self.root / "manifest.json"
        manifest = {"assetId": "wolf_rider", "originalMesh": str(mesh), "expectedMeshSha256": _sha(mesh), "jointNames": self.names,
                    "parents": self.parents.tolist(), "restAnchors": self.rest.tolist(),
                    "vertexRegions": ["body", "sword"],
                    "allowedRegionJoints": {"body": ["j0", "j1"]},
                    "rigidAttachments": {"sword": "j10"},
                    "authorProfile": str(profile_file), "authorProfileHash": _sha(profile_file)}
        manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
        fake = mock.Mock(vertices=np.array([[0.5, 0, 0], [10, 0, 0]], dtype=float),
                         triangles=np.array([[0, 1, 1]], dtype=np.int64), uvs=np.zeros((2, 2)),
                         albedo=np.zeros((2, 2, 4), dtype=np.uint8))
        with mock.patch("experiments.homm3_mocap_v2.prepare_mounted_skin_asset.load_bind_skeleton", return_value=fake), \
             mock.patch("run_shape_preserved.prep_freeze_path", return_value=self.root / "central.json"):
            frozen = prepare(str(manifest_file), str(self.root / "out"))
        self.assertEqual(frozen["policy"], "mounted_capsule_owned")
        self.assertTrue((self.root / "out" / "research_skin.npz").is_file())
        self.assertTrue(frozen["restIdentityParity"])
        self.assertLessEqual(frozen["restIdentityMaxError"], 1e-8)
        self.assertEqual(frozen["inputHashes"]["researchSkin"], _sha(self.root / "out" / "research_skin.npz"))
        with np.load(self.root / "out" / "research_skin.npz", allow_pickle=False) as skin:
            for key in ("vertices", "triangles", "uvs", "albedo", "weights", "names", "parents", "inverseBind"):
                self.assertIn(key, skin.files)
            self.assertTrue(np.array_equal(skin["triangles"], fake.triangles))
            self.assertTrue(np.array_equal(skin["uvs"], fake.uvs))
        with mock.patch("experiments.homm3_mocap_v2.prepare_mounted_skin_asset.load_bind_skeleton", return_value=fake), \
             mock.patch("run_shape_preserved.prep_freeze_path", return_value=self.root / "central2.json"):
            with self.assertRaises(FileExistsError):
                prepare(str(manifest_file), str(self.root / "out"))

    def test_source_and_authored_profile_hashes_are_required(self):
        mesh = self.root / "mesh.glb"
        mesh.write_bytes(b"mesh")
        profile = self.root / "profile.json"
        profile.write_text("profile", encoding="utf-8")
        base = {"assetId": "x", "originalMesh": str(mesh), "expectedMeshSha256": _sha(mesh),
                "authorProfile": str(profile), "authorProfileHash": _sha(profile)}
        for key in ("expectedMeshSha256", "authorProfileHash"):
            manifest = dict(base)
            manifest.pop(key)
            path = self.root / (key + ".json")
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises((KeyError, ValueError)):
                prepare(str(path), str(self.root / (key + "-out")))

    def test_candidate_only_does_not_touch_central_and_activation_is_cas(self):
        mesh = self.root / "mesh.glb"
        mesh.write_bytes(b"mesh")
        profile = self.root / "profile.json"
        profile.write_text("profile", encoding="utf-8")
        manifest_file = self.root / "manifest.json"
        manifest = {"assetId": "x", "originalMesh": str(mesh), "expectedMeshSha256": _sha(mesh),
                    "jointNames": self.names, "parents": self.parents.tolist(), "restAnchors": self.rest.tolist(),
                    "vertexRegions": ["body", "sword"], "allowedRegionJoints": {"body": ["j0", "j1"]},
                    "rigidAttachments": {"sword": "j10"}, "authorProfile": str(profile),
                    "authorProfileHash": _sha(profile)}
        manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
        fake = mock.Mock(vertices=np.array([[0.5, 0, 0], [10, 0, 0]], dtype=float),
                         triangles=np.array([[0, 1, 1]], dtype=np.int64), uvs=np.zeros((2, 2)),
                         albedo=np.zeros((2, 2, 4), dtype=np.uint8))
        central = self.root / "central.json"
        with mock.patch("experiments.homm3_mocap_v2.prepare_mounted_skin_asset.load_bind_skeleton", return_value=fake), \
             mock.patch("run_shape_preserved.prep_freeze_path", return_value=central):
            frozen = prepare(str(manifest_file), str(self.root / "candidate"), publish=False)
        self.assertFalse(central.exists())
        candidate = self.root / "candidate" / "preparation_frozen.json"
        with mock.patch("run_shape_preserved.prep_freeze_path", return_value=central):
            result = activate_candidate(candidate, None)
        self.assertTrue(central.exists())
        self.assertIsNone(result["previous"])
        original = central.read_bytes()
        with mock.patch("run_shape_preserved.prep_freeze_path", return_value=central):
            with self.assertRaises(ValueError):
                activate_candidate(candidate, "wrong")
        self.assertEqual(central.read_bytes(), original)

    def test_publish_preflight_refuses_existing_central_before_destination(self):
        mesh = self.root / "mesh.glb"
        mesh.write_bytes(b"mesh")
        profile = self.root / "profile.json"
        profile.write_text("profile", encoding="utf-8")
        manifest_file = self.root / "manifest.json"
        manifest_file.write_text(json.dumps({"assetId": "x", "originalMesh": str(mesh),
            "expectedMeshSha256": _sha(mesh), "authorProfile": str(profile),
            "authorProfileHash": _sha(profile)}), encoding="utf-8")
        central = self.root / "central.json"
        central.write_text("existing", encoding="utf-8")
        destination = self.root / "not-created"
        with mock.patch("run_shape_preserved.prep_freeze_path", return_value=central):
            with self.assertRaises(FileExistsError):
                prepare(str(manifest_file), str(destination), publish=True)
        self.assertFalse(destination.exists())
        self.assertEqual(central.read_text(encoding="utf-8"), "existing")


if __name__ == "__main__":
    unittest.main()
