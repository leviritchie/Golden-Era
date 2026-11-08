import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bind_meshy71_candidate import load_pose
from owned_rerig.smartrig_biped import _horizontal_body_frame, extract_smartrig_biped_heads


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs"


def _reference_heads(sid: str) -> tuple[np.ndarray, list[str]]:
    pose = load_pose(RUN_ROOT / sid, "g02_idle")
    names = [str(name).rsplit(":", 1)[-1] for name in pose.joint_names]
    return pose.capture_positions[pose.bind_index()], names


class SmartRigBipedTests(unittest.TestCase):
    def test_provisional_body_frame_is_scale_invariant(self):
        small = _horizontal_body_frame(np.array([0.4, 0.0, 0.7]))
        large = _horizontal_body_frame(np.array([40.0, 0.0, 70.0]))
        np.testing.assert_allclose(small, large)

    def test_arm_shape_rejects_lateral_accessory_branch(self):
        # The guardsman export contains a long positive-side accessory branch
        # that used to win the max-separation heuristic over the real arm.
        reference, names = _reference_heads("h3_guardsman")
        result = extract_smartrig_biped_heads(
            ROOT / "artifacts/meshy_downloads/h3_guardsman_smartrigged.glb",
            reference,
            names,
        )
        self.assertEqual(
            result["armNodes"]["Left"],
            ["Bone_021", "Bone_020", "Bone_019", "Bone_018"],
        )
        self.assertEqual(
            result["armNodes"]["Right"],
            ["Bone_026", "Bone_025", "Bone_024", "Bone_023"],
        )

    def test_different_smartrig_joint_counts_share_the_adapter(self):
        for sid in ("h3_dwarf", "h3_battle_dwarf", "h3_crusader"):
            with self.subTest(sid=sid):
                reference, names = _reference_heads(sid)
                mesh = ROOT / f"artifacts/meshy_downloads/{sid}_smartrigged.glb"
                result = extract_smartrig_biped_heads(mesh, reference, names)
                self.assertEqual(result["heads"].shape, (25, 3))
                self.assertTrue(np.isfinite(result["heads"]).all())
                self.assertEqual(result["schema"], "smartrig_biped_adapter.v1")
                self.assertEqual(len(result["trunkNodes"]), 7)
                self.assertEqual(len(result["armNodes"]["Left"]), 4)
                self.assertEqual(len(result["armNodes"]["Right"]), 4)

    def test_trunk_shape_wins_over_high_arm_root(self):
        # Marksman's exporter places both arm roots above the neck.  The
        # registered trunk path must win over a height-only child heuristic.
        reference, names = _reference_heads("h3_marksman")
        result = extract_smartrig_biped_heads(
            ROOT / "artifacts/meshy_downloads/h3_marksman_smartrigged.glb",
            reference,
            names,
        )
        self.assertEqual(result["trunkNodes"], [
            "Bone_001", "Bone_003", "Bone_002", "Bone_022", "Bone_021", "Bone_020",
            "synthetic:HeadTop_End",
        ])
        self.assertEqual(result["syntheticTrunk"], ["HeadTop_End"])
        self.assertEqual(len(result["armNodes"]["Left"]), 4)
        self.assertEqual(len(result["armNodes"]["Right"]), 4)

    def test_downward_leg_filter_does_not_promote_torso_branch(self):
        # The minotaur export has a very deep torso branch above Hips and two
        # shorter downward leg branches.  Depth alone selects the torso.
        reference, names = _reference_heads("h3_minotaur_taskmaster")
        result = extract_smartrig_biped_heads(
            ROOT / "artifacts/meshy_downloads/h3_minotaur_taskmaster_smartrigged.glb",
            reference,
            names,
        )
        self.assertEqual(result["legNodes"]["Left"], [
            "Bone_010", "Bone_009", "Bone_008", "Bone_007", "Bone_006",
        ])
        self.assertEqual(result["legNodes"]["Right"], [
            "Bone_015", "Bone_014", "Bone_013", "Bone_012", "Bone_011",
        ])

    def test_nested_pelvis_helpers_select_bilateral_legs(self):
        # These exports place a pelvis helper below the skin root, and one
        # candidate trunk junction also has two long downward accessory paths.
        # The adapter must choose the candidate whose trunk shape is plausible
        # and whose leg spread is bilateral, rather than swapping a global
        # side or accepting the first root child.
        expected = {
            "h3_walking_dead": ("Bone_001", "Bone_011", "Bone_016"),
            "h3_power_lich": ("Bone_002", "Bone_016", "Bone_021"),
            "h3_snow_elf_upg_alt": ("Bone_001", "Bone_010", "Bone_015"),
        }
        for sid, (trunk_root, right_leg, left_leg) in expected.items():
            with self.subTest(sid=sid):
                reference, names = _reference_heads(sid)
                result = extract_smartrig_biped_heads(
                    ROOT / f"artifacts/meshy_downloads/{sid}_smartrigged.glb",
                    reference,
                    names,
                )
                self.assertEqual(result["trunkNodes"][0], trunk_root)
                self.assertEqual(result["legNodes"]["Right"][0], right_leg)
                self.assertEqual(result["legNodes"]["Left"][0], left_leg)

    def test_reversed_trunk_segment_uses_skin_graph(self):
        # Dwarf Battlerager keeps the leg branches under the pelvis, but its
        # torso crosses parent links before continuing into the upper body.
        # A children-only trunk walk chooses the helper branch and loses one
        # arm side; the graph walk must recover the actual body path.
        reference, names = _reference_heads("h3_dwarf_battlerager")
        result = extract_smartrig_biped_heads(
            ROOT / "artifacts/meshy_downloads/h3_dwarf_battlerager_smartrigged.glb",
            reference,
            names,
        )
        self.assertEqual(result["trunkNodes"][:6], [
            "Bone_002", "Bone_003", "Bone_001", "Bone_006", "Bone_005", "Bone_004",
        ])
        self.assertEqual(result["armNodes"]["Left"][:3], ["Bone_029", "Bone_028", "Bone_027"])
        self.assertEqual(result["armNodes"]["Right"][:3], ["Bone_032", "Bone_031", "Bone_030"])

    def test_arm_laterality_uses_path_endpoint_when_roots_are_centered(self):
        # Skeleton's shoulder helpers are nearly coincident at the torso, but
        # the arm chains fan out in opposite directions.  Root-side filtering
        # rejects one chain; the path endpoint preserves the local laterality.
        reference, names = _reference_heads("h3_skeleton")
        result = extract_smartrig_biped_heads(
            ROOT / "artifacts/meshy_downloads/h3_skeleton_smartrigged.glb",
            reference,
            names,
        )
        self.assertEqual(result["armNodes"]["Left"], [
            "Bone_024", "Bone_023", "Bone_022", "Bone_021",
        ])
        self.assertEqual(result["armNodes"]["Right"], [
            "Bone_029", "Bone_028", "Bone_027", "Bone_026",
        ])


if __name__ == "__main__":
    unittest.main()
