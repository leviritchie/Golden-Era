import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
try:
    from . import export_ingame_skin_sidecar as sidecar
except ImportError:
    import export_ingame_skin_sidecar as sidecar

FIXTURE = Path("artifacts/homm3_mocap_v2/unittest_skin_sidecar")


class _Skeleton:
    names = ("root", "hand")
    vertices = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
    uvs = np.array([[0.0, 0.0]], dtype=np.float64)
    triangles = np.array([[0, 0, 0]], dtype=np.int32)
    vertex_joints = np.array([[0, 1, 0, 0, 0, 0, 0, 0]], dtype=np.int32)
    vertex_weights = np.array([[0.5, 0.5, 0, 0, 0, 0, 0, 0]], dtype=np.float64)


class SidecarTests(unittest.TestCase):
    def test_sidecar_preserves_all_eight_slots_and_source_hash(self):
        old = sidecar.load_bind_skeleton
        sidecar.load_bind_skeleton = lambda _path: _Skeleton()
        try:
            FIXTURE.mkdir(parents=True, exist_ok=True)
            glb = FIXTURE / "idle.glb"
            glb.write_bytes(b"raw")
            result = sidecar._sidecar_from_glb(glb, {"sourceReportSha256": "a" * 64, "assetId": "h3_test", "gameSid": "h3_test"})
            self.assertEqual(result["influenceSlots"], 8)
            self.assertEqual(len(result["jointIndices"]), 8)
            self.assertEqual(len(result["weights"]), 8)
            self.assertEqual(result["sourceReportSha256"], "a" * 64)
        finally:
            sidecar.load_bind_skeleton = old


    def test_sidecar_rejects_truncated_or_unnormalized_raw_skin(self):
        class Bad(_Skeleton):
            vertex_joints = np.zeros((1, 4), dtype=np.int32)
            vertex_weights = np.ones((1, 4), dtype=np.float64)
        old = sidecar.load_bind_skeleton
        sidecar.load_bind_skeleton = lambda _path: Bad()
        try:
            FIXTURE.mkdir(parents=True, exist_ok=True)
            glb = FIXTURE / "idle_bad.glb"
            glb.write_bytes(b"raw")
            with self.assertRaisesRegex(ValueError, "eight skin slots"):
                sidecar._sidecar_from_glb(glb, {"sourceReportSha256": "a" * 64, "assetId": "x", "gameSid": "x"})
        finally:
            sidecar.load_bind_skeleton = old


if __name__ == "__main__":
    unittest.main()
