import hashlib
import unittest
from pathlib import Path

from experiments.homm3_mocap_v2.asset_profile_ghost_behemoth import get_profile
from experiments.homm3_mocap_v2.glb_skeleton import load_bind_skeleton
from experiments.homm3_mocap_v2.target_asset import load_target_asset

class GhostBehemothProfileTests(unittest.TestCase):
    def test_identity_and_complete_coverage(self):
        p = get_profile(); mesh = Path(p["mesh"]); self.assertTrue(mesh.is_file())
        self.assertEqual(hashlib.sha256(mesh.read_bytes()).hexdigest(), p["expectedMeshSha256"])
        s = load_bind_skeleton(mesh); bones = [b for r in p["regionBones"].values() for b in r]
        self.assertEqual((len(s.names), len(s.vertices), len(s.triangles)), (49, 7398, 9265))
        self.assertEqual(len(bones), len(set(bones))); self.assertEqual(set(bones), set(s.names)); self.assertEqual(set(p["sourceJointMap"]), set(s.names))
        self.assertEqual({p["sourceJointMap"][n] for n in ("Bone_000", "Bone_001")}, {"mixamorig:Hips"})
        self.assertEqual(p["sourceJointMap"]["Bone_004"], "mixamorig:Spine")
        self.assertEqual(p["sourceJointMap"]["Bone_003"], "mixamorig:Spine1")
        self.assertEqual(p["sourceJointMap"]["Bone_002"], "mixamorig:Spine2")

    def test_actual_consumer_loader_and_source_contract(self):
        p = get_profile(); a = load_target_asset(p)
        self.assertEqual(a["vertices"].shape, (7398, 3)); self.assertEqual(a["triangles"].shape, (9265, 3))
        self.assertTrue(Path(p["sourceIdleDir"]).is_dir()); self.assertEqual((p["sourceIdleGroup"], p["sourceIdleFrameCount"]), (2, 8))
        self.assertEqual(p["leftRightPairs"][1]["evidence"], ("Bone_010", "Bone_006"))

if __name__ == "__main__": unittest.main()
