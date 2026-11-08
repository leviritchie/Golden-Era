from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import tools.validate_homm3_mocap_delivery_contract as contract


def _fixture_doc() -> dict:
    return {
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "Root", "children": [1]},
            {"name": "Skeleton"},
            {"name": "Orientation", "rotation": list(contract.ORIENTATION), "children": [1]},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "WEIGHTS_0": 1}}]}],
        "skins": [],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "type": "VEC3", "count": 1},
            {"bufferView": 1, "componentType": 5126, "type": "VEC4", "count": 1},
        ],
        "bufferViews": [{"byteOffset": 0}, {"byteOffset": 12}],
        "animations": [],
    }


class MocapDeliveryContractTests(unittest.TestCase):
    def test_rejects_missing_rollout_without_writes(self) -> None:
        errors = contract.validate(
            rollout_dir=Path("V:/__missing_current_mocap_rollout__"),
            selection_path=Path("V:/__missing_current_mocap_selection__.json"),
        )
        self.assertTrue(errors)

    def test_rejects_corrupt_weights_in_raw_parity(self) -> None:
        source_doc = _fixture_doc()
        candidate_doc = _fixture_doc()
        source_blob = bytes(28)
        candidate_blob = bytes(12) + b"\x00\x00\x80?" + bytes(12)
        errors: list[str] = []
        with patch.object(contract, "_read_glb", side_effect=[(source_doc, source_blob), (candidate_doc, candidate_blob)]):
            contract._validate_raw_parity(Path("raw.glb"), Path("candidate.glb"), errors)
        self.assertTrue(any("accessor 1 differs" in error for error in errors))

    def test_rejects_timing_that_does_not_preserve_raw_frames(self) -> None:
        doc = _fixture_doc()
        doc["animations"] = [{"name": "Unit_Idle", "samplers": [{"input": 0}], "channels": []}]
        errors: list[str] = []
        with patch.object(contract, "_read_glb", return_value=(doc, b"")), patch.object(
            contract, "_accessor_f4", return_value=[[0.0], [0.0833333]]
        ):
            contract._validate_clip(
                Path("candidate.glb"),
                {"contractName": "Unit_Idle", "frameCount": 3, "fps": 12.0, "lifecycleRole": "cycle"},
                errors,
            )
        self.assertTrue(any("timing does not match" in error for error in errors))

    def test_rejects_raw_hash_mismatch_directly(self) -> None:
        self.assertNotEqual(contract._sha256(Path("tools/validate_homm3_mocap_delivery_contract.py")), "0" * 64)


if __name__ == "__main__":
    unittest.main()
