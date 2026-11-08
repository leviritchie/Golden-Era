"""CPU contract tests for mounted composition; no model or CUDA is involved."""
import gc
import hashlib, json
from pathlib import Path
import numpy as np
import unittest
import sys
import shutil
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mesh_preview import fk_world_matrices
from compose_mounted_corpus import _check_alignment, compose_mounted


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _corpus(path: Path, *, frames=None, indices=None, capture=None, digest=None):
    row = {"key": "idle", "frames": frames or ["f0.png"], "contextBefore": ["f0.png"], "contextAfter": [], "sourceIndices": indices or [0], "capture": str(capture or path.with_name("capture.npz")), "captureSha256": digest or "0" * 64}
    value = {"schema": "homm3.skin-corpus.v1", "unit": "h3_wolf_rider_mount", "manifest": "m", "manifestSha256": "m", "sourceFrames": {}, "captures": [row]}
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


class MountedCompositionTests(unittest.TestCase):
 def setUp(self):
    self.tmp_path = Path("artifacts/test_tmp") / ("compose_tests_" + uuid.uuid4().hex)
    self.tmp_path.mkdir(parents=True)

 def tearDown(self):
    root = Path("artifacts/test_tmp").resolve()
    target = self.tmp_path.resolve()
    if root in target.parents:
        gc.collect()
        shutil.rmtree(target)

 def test_fk_identity_and_seat_rotation_follows_mount(self):
    parents = np.array([-1, 0, 1], dtype=np.int64)
    offsets = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    local = np.repeat(np.eye(3)[None], 3, axis=0)
    first = fk_world_matrices(local_rotation=local, local_translation=offsets, parents=parents, root_world=np.zeros(3))
    assert np.allclose(first[:, :3, 3], [[0, 0, 0], [1, 0, 0], [1, 1, 0]])
    turn = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)
    local[0] = turn
    second = fk_world_matrices(local_rotation=local, local_translation=offsets, parents=parents, root_world=np.zeros(3))
    assert np.allclose(second[2, :3, 3], [ -1, 1, 0])


 def test_held_leg_local_rotation_is_identity_in_fk(self):
    parents = np.array([-1, 0, 1], dtype=np.int64)
    offsets = np.array([[0, 0, 0], [1, 0, 0], [0, -1, 0]], dtype=float)
    local = np.repeat(np.eye(3)[None], 3, axis=0)
    local[2] = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], dtype=float)
    held = np.eye(3)
    local[2] = held
    world = fk_world_matrices(local_rotation=local, local_translation=offsets, parents=parents, root_world=np.zeros(3))
    assert np.array_equal(local[2], np.eye(3))
    assert np.allclose(world[2, :3, 3], [1, -1, 0])


 def test_timeline_mismatch_rejected(self):
    a = {"captures": [{"key": "x", "frames": ["a"], "sourceIndices": [0]}]}
    b = {"captures": [{"key": "x", "frames": ["b"], "sourceIndices": [0]}]}
    with self.assertRaisesRegex(ValueError, "source frame mapping"):
        _check_alignment(a, b)


 def test_hash_mismatch_rejected_before_fk(self):
    tmp_path = self.tmp_path
    mount_path, rider_path = tmp_path / "mount.json", tmp_path / "rider.json"
    capture = tmp_path / "capture.npz"
    np.savez(capture, pred_position=np.zeros((1, 1, 3)))
    _corpus(mount_path, capture=capture)
    _corpus(rider_path, capture=capture)
    # Deliberately retain the wrong row hash in both inputs.
    prep = tmp_path / "prep.npz"
    np.savez(prep, mount_names=np.array(["m"]), mount_parents=np.array([-1]), mount_capture_reference=np.zeros((1, 3)), mount_capture_offsets=np.zeros((1, 3)), mount_fitted_offsets=np.zeros((1, 3)), rider_names=np.array(["r"]), rider_parents=np.array([-1]), rider_capture_reference=np.zeros((1, 3)), rider_capture_offsets=np.zeros((1, 3)), rider_fitted_offsets=np.zeros((1, 3)), combined_names=np.array(["m", "r"]), combined_parents=np.array([-1, 0]), combined_offsets=np.zeros((2, 3)), mount_hubs=np.array(["m"]), rider_hubs=np.array(["r"]), rider_held_indices=np.array([0]), rider_held_rest=np.zeros((1, 3)), seat_parent=np.array([0]), seat_offset=np.zeros(3))
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"unit": "h3_wolf_rider", "clips": [{"key": "idle", "frames": ["f0.png"]}]}))
    with self.assertRaisesRegex(ValueError, "hash mismatch"):
        compose_mounted(mount_path, rider_path, prep, tmp_path / "out", source)


 def test_names_parent_dimension_mismatch_rejected(self):
    tmp_path = self.tmp_path
    prep = tmp_path / "bad.npz"
    np.savez(prep, mount_names=np.array(["m"]), mount_parents=np.array([-1]), mount_capture_reference=np.zeros((1, 3)), mount_capture_offsets=np.zeros((1, 3)), mount_fitted_offsets=np.zeros((2, 3)))
    # The public composer checks this before any reconstruction; use a tiny
    # corpus pair only to reach preparation validation.
    m, r = tmp_path / "m.json", tmp_path / "r.json"
    _corpus(m); _corpus(r)
    with self.assertRaisesRegex(ValueError, "preparation"):
        source = tmp_path / "source.json"
        source.write_text(json.dumps({"unit": "h3_wolf_rider", "clips": [{"key": "idle", "frames": ["f0.png"]}]}))
        compose_mounted(m, r, prep, tmp_path / "out_bad", source)

 def _end_to_end_fixture(self, held_offset):
    base = self.tmp_path / "e2e"
    mount_dir, rider_dir = base / "mount" / "idle", base / "rider" / "idle"
    for directory in (mount_dir, rider_dir):
        (directory / "capture").mkdir(parents=True)
        (directory / "frames").mkdir()
        (directory / "frames" / "000000.png").write_bytes(b"frame")
    mcap = mount_dir / "capture" / "raw.npz"
    rcap = rider_dir / "capture" / "raw.npz"
    names_m, names_r = np.array(["m0", "m1"]), np.array(["r0", "r1"])
    parents = np.array([-1, 0], dtype=np.int64)
    offsets = np.array([[0., 0., 0.], [1., 0., 0.]])
    positions = np.array([[[0., 0., 0.], [1., 0., 0.]]])
    for path, names in ((mcap, names_m), (rcap, names_r)):
        np.savez(path, pred_position=positions, local_rotation=np.repeat(np.eye(3)[None, None], 2, axis=1),
                 joint_names=names, parents=parents, offsets=offsets)
    digest = _sha256(mcap)
    row_m = {"key": "idle", "frames": [str(mount_dir / "frames" / "000000.png")], "contextBefore": [],
             "contextAfter": [], "sourceIndices": [0], "capture": str(mcap), "captureSha256": digest,
             "referenceIndex": 0, "contextBeforeCount": 0, "contextAfterCount": 0}
    row_r = dict(row_m, capture=str(rcap), captureSha256=_sha256(rcap))
    for path, unit, row in ((base / "mount.json", "h3_wolf_rider_mount", row_m), (base / "rider.json", "h3_wolf_rider_rider", row_r)):
        path.write_text(json.dumps({"schema": "homm3.skin-corpus.v1", "unit": unit, "manifest": "m",
                                    "manifestSha256": "m", "sourceFrames": {}, "captures": [row]}), encoding="utf-8")
    prep = base / "prep.npz"
    combined = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [1., 0., 0.]], dtype=float)
    np.savez(prep, mount_names=names_m, mount_parents=parents, mount_capture_reference=positions[0],
             mount_capture_offsets=offsets, mount_fitted_offsets=offsets, mount_hubs=np.array(["m0", "m1"]),
             rider_names=names_r, rider_parents=parents, rider_capture_reference=positions[0],
             rider_capture_offsets=offsets, rider_fitted_offsets=offsets, rider_hubs=np.array(["r0", "r1"]),
             combined_names=np.array(["m0", "m1", "r0", "r1"]), combined_parents=np.array([-1, 0, 1, 2]),
             combined_offsets=combined, rider_held_indices=np.array([1]), rider_held_rest=np.array([[0., 0., 0.], held_offset]),
             seat_parent=np.array([1]), seat_offset=np.array([0., 1., 0.]))
    source = base / "source.json"
    source.write_text(json.dumps({"clips": [{"key": "idle", "frames": row_m["frames"]}]}), encoding="utf-8")
    return base, prep, source

 def test_floating_canonical_offsets_are_preserved_end_to_end(self):
    base, prep, source = self._end_to_end_fixture(np.array([1., 0., 0.]))
    out = base / "out"
    result = compose_mounted(base / "mount.json", base / "rider.json", prep, out, source)
    self.assertEqual(result["clipCount"], 1)
    with np.load(out / "idle" / "capture" / "composed_positions.npz") as z:
        self.assertTrue(np.array_equal(z["offsets"], np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [1., 0., 0.]])))

 def test_held_offset_mismatch_rejected(self):
    base, prep, source = self._end_to_end_fixture(np.array([1.0000001, 0., 0.]))
    with self.assertRaisesRegex(ValueError, "held rider rest"):
        compose_mounted(base / "mount.json", base / "rider.json", prep, base / "out_bad", source)

 def test_seat_offset_mismatch_rejected_without_output(self):
    base, prep, source = self._end_to_end_fixture(np.array([1., 0., 0.]))
    with np.load(prep, allow_pickle=False) as z:
        values = {key: z[key].copy() for key in z.files}
    values["seat_offset"] = np.array([0., 1.0000001, 0.])
    np.savez(prep, **values)
    with self.assertRaisesRegex(ValueError, "seat offset"):
        compose_mounted(base / "mount.json", base / "rider.json", prep, base / "out_bad", source)
    self.assertFalse((base / "out_bad" / "corpus.json").exists())


if __name__ == "__main__":
 unittest.main()
