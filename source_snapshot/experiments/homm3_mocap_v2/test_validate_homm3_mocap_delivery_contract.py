import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from tools.validate_homm3_mocap_delivery_contract import _validate_skin_weights, _validate_source_groups

FIXTURE = Path("artifacts/homm3_mocap_v2/unittest_delivery_sidecar")


class _Skeleton:
    names = ("root",)
    vertices = __import__("numpy").array([[0.0, 0.0, 0.0]])
    uvs = __import__("numpy").array([[0.0, 0.0]])
    triangles = __import__("numpy").array([[0, 0, 0]])
    vertex_joints = __import__("numpy").zeros((1, 8), dtype=int)
    vertex_weights = __import__("numpy").array([[1.0, 0, 0, 0, 0, 0, 0, 0]])


def _sidecar(path, raw_manifest, source_glb, source_hash, report_hash="b" * 64):
    value = {
        "schema": "stronghold-current-mocap-skin-sidecar-v1",
        "rawManifest": str(raw_manifest),
        "rawManifestSha256": hashlib.sha256(raw_manifest.read_bytes()).hexdigest(),
        "sourceGlb": str(source_glb),
        "sourceGlbSha256": source_hash,
        "sourceReportSha256": report_hash,
        "vertexCount": 1,
        "influenceSlots": 8,
        "jointNames": ["root"], "vertices": [0, 0, 0], "uvs": [0, 0], "triangles": [0, 0, 0], "jointIndices": [0] * 8,
        "weights": [1, 0, 0, 0, 0, 0, 0, 0],
    }
    path.write_text(json.dumps(value), encoding="utf-8")


class DeliverySidecarTests(unittest.TestCase):
    def test_source_only_partition_matches_raw_and_rejects_omissions(self):
        from experiments.homm3_mocap_v2.assemble_ingame_delivery import SOURCE_ONLY_REASON
        root = (FIXTURE / "source_groups").resolve()
        root.mkdir(parents=True, exist_ok=True)
        raw = root / "g09_unused_a.glb"
        raw.write_bytes(b"preserved raw")
        raw_manifest = root / "raw_manifest.json"
        raw_manifest.write_text(json.dumps({"units": [{"gameSid": "game", "groups": [
            {"groupId": "g09_unused_a", "glb": raw.name}, {"groupId": "g02_idle", "glb": "idle.glb"}]}]}), encoding="utf-8")
        manifest = {"rawManifest": str(raw_manifest),
                    "rawManifestSha256": hashlib.sha256(raw_manifest.read_bytes()).hexdigest(),
                    "clips": [{"contractName": "Unit_Idle"}],
                    "sourceOnlyGroups": [{"groupId": "g09_unused_a", "reason": SOURCE_ONLY_REASON,
                                          "rawSourceGlb": str(raw), "rawSourceGlbSha256": hashlib.sha256(raw.read_bytes()).hexdigest()}]}
        selected = {"gameSid": "game", "labSid": "lab"}
        errors = []
        _validate_source_groups(manifest, selected, root, errors)
        self.assertEqual(errors, [])
        manifest["sourceOnlyGroups"] = []
        _validate_source_groups(manifest, selected, root, errors)
        self.assertTrue(any("source-only" in error for error in errors))

    def test_skin_weights_checks_raw_idle_hash_and_dimensions(self):
        tmp_path = FIXTURE / "valid"
        tmp_path.mkdir(parents=True, exist_ok=True)
        raw = tmp_path / "idle.glb"; raw.write_bytes(b"raw-idle")
        raw_manifest = tmp_path / "raw.json"; raw_manifest.write_text("{}", encoding="utf-8")
        raw_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
        sidecar = tmp_path / "skin_weights.json"; _sidecar(sidecar, raw_manifest.resolve(), raw.resolve(), raw_hash)
        manifest = {"skinWeights": {"path": "skin_weights.json", "sha256": hashlib.sha256(sidecar.read_bytes()).hexdigest()}}
        selected = {"labSid": "h3_test", "sourceReportSha256": "b" * 64}
        clips = [{"contractName": "h3_test_Idle", "lifecycleRole": "Idle", "rawSourceGlb": "idle.glb"}]
        errors = []
        with patch("tools.validate_homm3_mocap_delivery_contract.load_bind_skeleton", return_value=_Skeleton()):
            _validate_skin_weights(manifest, selected, tmp_path, clips, errors)
        self.assertEqual(errors, [])


    def test_skin_weights_rejects_source_or_shape_drift(self):
        tmp_path = FIXTURE / "drift"
        tmp_path.mkdir(parents=True, exist_ok=True)
        raw = tmp_path / "idle.glb"; raw.write_bytes(b"raw-idle")
        raw_manifest = tmp_path / "raw.json"; raw_manifest.write_text("{}", encoding="utf-8")
        sidecar = tmp_path / "skin_weights.json"; _sidecar(sidecar, raw_manifest.resolve(), raw.resolve(), "d" * 64)
        manifest = {"skinWeights": {"path": "skin_weights.json", "sha256": hashlib.sha256(sidecar.read_bytes()).hexdigest()}}
        selected = {"labSid": "h3_test", "sourceReportSha256": "b" * 64}
        clips = [{"contractName": "h3_test_Idle", "lifecycleRole": "Idle", "rawSourceGlb": "idle.glb"}]
        errors = []
        _validate_skin_weights(manifest, selected, tmp_path, clips, errors)
        self.assertTrue(any("source GLB" in error for error in errors))

    def test_skin_weights_rejects_mutated_payload_even_with_updated_file_hash(self):
        tmp_path = FIXTURE / "mutations"
        tmp_path.mkdir(parents=True, exist_ok=True)
        raw = tmp_path / "idle.glb"; raw.write_bytes(b"raw-idle")
        raw_manifest = tmp_path / "raw.json"; raw_manifest.write_text("{}", encoding="utf-8")
        selected = {"labSid": "h3_test", "sourceReportSha256": "b" * 64}
        clips = [{"contractName": "h3_test_Idle", "lifecycleRole": "Idle", "rawSourceGlb": "idle.glb"}]
        for field, value in (("weights", [0, 1, 0, 0, 0, 0, 0, 0]),
                             ("jointIndices", [1, 0, 0, 0, 0, 0, 0, 0]),
                             ("uvs", [0.25, 0]), ("vertices", [1, 0, 0])):
            sidecar = tmp_path / (field + ".json")
            _sidecar(sidecar, raw_manifest.resolve(), raw.resolve(), hashlib.sha256(raw.read_bytes()).hexdigest())
            payload = json.loads(sidecar.read_text(encoding="utf-8")); payload[field] = value
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
            manifest = {"skinWeights": {"path": sidecar.name, "sha256": hashlib.sha256(sidecar.read_bytes()).hexdigest()}}
            errors = []
            with patch("tools.validate_homm3_mocap_delivery_contract.load_bind_skeleton", return_value=_Skeleton()):
                _validate_skin_weights(manifest, selected, tmp_path, clips, errors)
            self.assertTrue(errors, field)
        sidecar = tmp_path / "malformed.json"
        _sidecar(sidecar, raw_manifest.resolve(), raw.resolve(), hashlib.sha256(raw.read_bytes()).hexdigest())
        payload = json.loads(sidecar.read_text(encoding="utf-8")); payload["weights"] = [1]
        sidecar.write_text(json.dumps(payload), encoding="utf-8")
        errors = []
        _validate_skin_weights({"skinWeights": {"path": sidecar.name, "sha256": hashlib.sha256(sidecar.read_bytes()).hexdigest()}}, selected, tmp_path, clips, errors)
        self.assertTrue(any("dimensions" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
