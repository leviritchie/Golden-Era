import shutil
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from assemble_ingame_delivery import ORIENTATION, _read_glb, _rename_single_animation, _wrap_orientation, _write_glb, native_contract_for_raw_group, SOURCE_ONLY_GROUPS


class AssemblyHelpersTests(unittest.TestCase):
    def test_all_raw_groups_have_explicit_native_or_source_only_disposition(self):
        native = {0, 1, 2, 3, 4, 5, 12, 15, 20, 21}
        self.assertEqual(native | SOURCE_ONLY_GROUPS, set(range(22)))
        self.assertFalse(native & SOURCE_ONLY_GROUPS)
        for number in range(22):
            result = native_contract_for_raw_group(f"g{number:02d}_source")
            self.assertEqual(result is not None, number in native)
        for invalid in ("g22_unknown", "g99_unknown", "g123_bad", "x00_bad"):
            with self.assertRaises(ValueError):
                native_contract_for_raw_group(invalid)

    def _fixture(self, root: Path) -> Path:
        path = root / "raw.glb"
        doc = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0, 1]}],
            "nodes": [{"name": "Hips", "children": [2]}, {"name": "MeshRoot"}, {"name": "Spine"}],
            "animations": [{"name": "source", "channels": [], "samplers": []}],
            "buffers": [{"byteLength": 0}],
        }
        _write_glb(path, doc, b"")
        return path

    def test_wrapper_contains_all_scene_roots_and_preserves_animation(self):
        tmp = Path(__file__).with_name(".assembly_test_tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        try:
            path = self._fixture(tmp)
            _wrap_orientation(path)
            doc, _ = _read_glb(path)
            outer = doc["nodes"][doc["scenes"][0]["nodes"][0]]
            orientation = doc["nodes"][outer["children"][0]]
            self.assertEqual(outer["name"], "MocapDeliveryRoot")
            self.assertEqual(orientation["name"], "Orientation")
            self.assertEqual(tuple(orientation["rotation"]), ORIENTATION)
            self.assertEqual(orientation["children"], [0, 1])
            self.assertEqual(doc["animations"][0]["name"], "source")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_rename_does_not_add_cycle_key_or_animation(self):
        tmp = Path(__file__).with_name(".assembly_test_tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        try:
            path = self._fixture(tmp)
            _rename_single_animation(path, "Unit_Idle")
            doc, _ = _read_glb(path)
            self.assertEqual(len(doc["animations"]), 1)
            self.assertEqual(doc["animations"][0]["name"], "Unit_Idle")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_static_master_removes_only_animation_list(self):
        tmp = Path(__file__).with_name(".assembly_test_tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        try:
            path = self._fixture(tmp)
            _rename_single_animation(path, "Unit_Idle", static=True)
            doc, _ = _read_glb(path)
            self.assertEqual(doc["animations"], [])
            self.assertEqual(len(doc["nodes"]), 3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
