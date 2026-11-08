import copy
import json
import unittest
from unittest.mock import patch

from prepare_mapped_skin_asset import _profile_hash
import run_shape_preserved as shared


class MappedProvenanceTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("structured_profiles.current_profile_pin", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fit_and_weight_inputs_change_profile_fingerprint(self):
        profile = {key: {"a": "b"} for key in
                   ("sourceJointMap", "regionJoints", "regionBones", "hubs", "chains", "rigidAttachments")}
        original = _profile_hash(profile)
        for key in profile:
            changed = copy.deepcopy(profile)
            changed[key]["a"] = "changed"
            self.assertNotEqual(original, _profile_hash(changed), key)

    def test_mapped_loader_rejects_missing_profile_pin(self):
        freeze = {"skinInitialization": "source_joint_map", "researchSkin": "not-opened.npz",
                  "inputHashes": {"originalMesh": "source"}}
        with patch.object(shared.Path, "is_file", return_value=True), \
             patch.object(shared.Path, "read_text", return_value=json.dumps(freeze)), \
             patch.object(shared, "verify_original_untouched"), \
             patch.object(shared, "get_profile", return_value={}):
            with self.assertRaisesRegex(ValueError, "profile changed"):
                shared._load_frozen_prep("h3_test")

    def test_mapped_loader_rejects_skin_drift(self):
        freeze = {"skinInitialization": "source_joint_map", "researchSkin": "not-opened.npz",
                  "inputHashes": {"originalMesh": "source", "profile": _profile_hash({}), "researchSkin": "old"}}
        with patch.object(shared.Path, "is_file", return_value=True), \
             patch.object(shared.Path, "read_text", return_value=json.dumps(freeze)), \
             patch.object(shared, "verify_original_untouched"), \
             patch.object(shared, "get_profile", return_value={}), \
             patch.object(shared, "sha256_file", return_value="changed"):
            with self.assertRaisesRegex(ValueError, "skin changed"):
                shared._load_frozen_prep("h3_test")


if __name__ == "__main__":
    unittest.main()
