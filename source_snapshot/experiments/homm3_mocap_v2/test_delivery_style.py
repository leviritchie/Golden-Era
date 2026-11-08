import hashlib
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from experiments.homm3_mocap_v2 import delivery_style as style
from experiments.homm3_mocap_v2.glb_skeleton import _accessor, read_glb
from experiments.homm3_mocap_v2.assemble_ingame_delivery import _write_glb


class DeliveryStyleTests(unittest.TestCase):
    def setUp(self):
        root = Path("artifacts/homm3_mocap_v2/style_unit_tests")
        root.mkdir(parents=True, exist_ok=True)
        self.root = (root / self._testMethodName).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.root)
        self.source = self.root / "raw.glb"
        times = np.array([0, 1 / 12, 2 / 12], dtype="<f4")
        q = np.zeros((3, 3, 4), dtype="<f4")
        q[..., 3] = 1
        q[1, 1] = [0, 0, np.sin(.2), np.cos(.2)]
        arrays = [times, q[:, 0], q[:, 1], q[:, 2], np.zeros((3, 3), dtype="<f4")]
        blob = bytearray()
        accessors, views = [], []
        for i, values in enumerate(arrays):
            views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": values.nbytes})
            blob.extend(values.tobytes())
            accessors.append({"bufferView": i, "componentType": 5126, "count": 3,
                              "type": "SCALAR" if i == 0 else "VEC3" if i == 4 else "VEC4"})
        doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(blob)}],
               "nodes": [{"name": "root", "children": [1]}, {"name": "joint", "children": [2]}, {"name": "leaf"}],
               "scenes": [{"nodes": [0]}], "scene": 0,
               "bufferViews": views, "accessors": accessors,
               "animations": [{"samplers": [{"input": 0, "output": i} for i in range(1, 5)],
                               "channels": [{"sampler": i, "target": {"node": i if i < 3 else 0,
                                            "path": "rotation" if i < 3 else "translation"}} for i in range(4)]}]}
        _write_glb(self.source, doc, bytes(blob))
        skeleton = SimpleNamespace(names=["root", "joint", "leaf"], parents=[-1, 0, 1], node_indices=[0, 1, 2])
        p = patch.object(style, "load_bind_skeleton", return_value=skeleton)
        p.start()
        self.addCleanup(p.stop)

    def test_idle_retimes_only_inputs_and_pins_authority(self):
        record = style.derive(self.source, self.root / "idle.glb", "Unit_Idle")
        original, derived = read_glb(self.source), read_glb(Path(record["derivedSourceGlb"]))
        np.testing.assert_allclose(_accessor(derived, derived["bin"], 0),
                                   _accessor(original, original["bin"], 0) * 2.5)
        for i in range(1, 5):
            np.testing.assert_array_equal(_accessor(derived, derived["bin"], i), _accessor(original, original["bin"], i))
        self.assertEqual(style.validate_derived(self.source, "Unit_Idle", record), self.root / "idle.glb")

    def test_motion_increases_articulation_preserves_root_leaf_endpoints_translation(self):
        record = style.derive(self.source, self.root / "attack.glb", "Unit_AttackFront")
        original, derived = read_glb(self.source), read_glb(Path(record["derivedSourceGlb"]))
        for i in (0, 1, 3, 4):
            np.testing.assert_array_equal(_accessor(derived, derived["bin"], i), _accessor(original, original["bin"], i))
        q = _accessor(derived, derived["bin"], 2).reshape(3, 4)
        self.assertAlmostEqual(2 * np.arctan2(q[1, 2], q[1, 3]), .4 * style.MOTION_GAIN, places=5)
        self.assertEqual(style.policy("Unit_Move")["gain"], 2.20)
        np.testing.assert_array_equal(q[[0, -1]], _accessor(original, original["bin"], 2).reshape(3, 4)[[0, -1]])

    def test_policy_covers_current_native_contracts_and_mouseover_is_not_idle(self):
        from gpu_cascade_delivery import CONTRACT_SUFFIX_BY_GROUP
        self.assertEqual(set(style.POLICY), set(CONTRACT_SUFFIX_BY_GROUP.values()))
        self.assertEqual(style.policy("Unit_Mouseover")["durationMultiplier"], 1.0)
        for name in ("Death", "MoveStart", "MoveEnd", "Mouseover", "Defence", "Hitted"):
            self.assertEqual(style.styled_bytes(self.source, "Unit_" + name), self.source.read_bytes())
        with self.assertRaisesRegex(ValueError, "unclassified"):
            style.policy("Unit_IdleUnknown")

    def test_tampered_derived_payload_rejected_even_with_updated_hash(self):
        record = style.derive(self.source, self.root / "idle.glb", "Unit_Idle")
        target = Path(record["derivedSourceGlb"])
        target.write_bytes(self.source.read_bytes())
        record["derivedSourceGlbSha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "raw-to-style"):
            style.validate_derived(self.source, "Unit_Idle", record)

    def test_policy_drift_and_raw_overwrite_rejected(self):
        record = style.derive(self.source, self.root / "idle.glb", "Unit_Idle")
        record["durationMultiplier"] = 1.0
        with self.assertRaisesRegex(ValueError, "policy drift"):
            style.validate_derived(self.source, "Unit_Idle", record)
        with self.assertRaisesRegex(ValueError, "overwrite raw"):
            style.derive(self.source, self.source, "Unit_Idle")

    def test_baseline_parity_still_rejects_styled_motion(self):
        from tools.validate_homm3_mocap_delivery_contract import _validate_raw_parity
        record = style.derive(self.source, self.root / "idle.glb", "Unit_Idle")
        derived = Path(record["derivedSourceGlb"])
        errors = []
        _validate_raw_parity(self.source, derived, errors)
        self.assertTrue(errors)
        errors = []
        _validate_raw_parity(derived, derived, errors)
        self.assertFalse(errors)


if __name__ == "__main__":
    unittest.main()
