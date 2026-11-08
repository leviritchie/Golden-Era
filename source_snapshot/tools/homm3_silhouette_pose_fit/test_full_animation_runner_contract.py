"""Contract tests for sparse-fit artifacts and resume fingerprints."""
from __future__ import annotations

import json
import shutil
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_crusader_full_animation_set as runner
import run_creature_animation_set as generic_runner
from roc_semantic_hybrid_experiment import RocHybridConfig


class FullAnimationRunnerContractTests(unittest.TestCase):
    def test_authentic_def_choice_uses_dedicated_materializer(self):
        class FakeWidgets:
            def _materialize_def_choice(self, root, choice):
                self.called = (root, choice)
                return Path("pilot"), Path("camera.json"), Path("upscale_meta.json")

            def _materialize_choice(self, choice):  # pragma: no cover - guard against wrong lane
                raise AssertionError("authentic DEF choices must not use the legacy materializer")

        choice = SimpleNamespace(source_kind="authentic_def")
        widgets = FakeWidgets()
        runtime, camera, source = runner._materialize_choice_for_run(widgets, choice)
        self.assertEqual((runtime, camera, source), (Path("pilot"), Path("camera.json"), Path("upscale_meta.json")))
        self.assertIs(widgets.called[1], choice)

    def test_mesh_audit_does_not_promote_suffix_only_custom_rig(self):
        class FakeWidgets:
            @staticmethod
            def meshy_rigidization_status(mesh):
                return "fail", None

        canonical = generic_runner.ROOT / "artifacts/meshy_downloads/h3_air_elemental_smartrigged.glb"
        status, report, payload = generic_runner._mesh_audit(FakeWidgets(), canonical, allow_unverified=False)
        self.assertEqual(status, "meshy_smart_rig")
        self.assertIsNone(report)
        self.assertIsNone(payload)
        custom = generic_runner.ROOT / "artifacts/homm3_mocap_v2/_contract_custom_smartrigged.glb"
        with self.assertRaises(RuntimeError):
            generic_runner._mesh_audit(FakeWidgets(), custom, allow_unverified=False)

    def test_legacy_choice_keeps_frame_manifest_source(self):
        class FakeWidgets:
            def _materialize_choice(self, choice):
                root = runner.TOOL / "_contract_test_tmp" / "legacy"
                manifest = root / "frames_ground_truth" / "original_frames.json"
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text("{}", encoding="utf-8")
                return root, root / "camera.json"

        root = runner.TOOL / "_contract_test_tmp" / "legacy"
        try:
            runtime, camera, source = runner._materialize_choice_for_run(
                FakeWidgets(), SimpleNamespace(source_kind="pipeline", source_label="")
            )
            self.assertEqual(runtime, root)
            self.assertEqual(camera, root / "camera.json")
            self.assertEqual(source, root / "frames_ground_truth" / "original_frames.json")
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_sparse_artifact_preserves_source_frame_ids(self):
        root = runner.TOOL / "_contract_test_tmp" / "sparse"
        path = root / "clip_poses_sparse.json"
        root.mkdir(parents=True, exist_ok=True)
        try:
            metadata = {"sourceFrameIndices": [0, 2], "sourceFps": 12}
            runner._write_sparse_pose_artifact(
                path,
                [{"Bone": {"x": 1.0}}, {"Bone": {"x": 2.0}}],
                source_metadata=metadata,
                fps=12,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(payload["interpolationApplied"])
            self.assertEqual(payload["sourceFrameIndices"], [0, 2])
            self.assertEqual(sorted(payload["poses"]), ["0", "2"])
            review = runner._load_sparse_pose_result(path)
            self.assertEqual(tuple(review["config"]["frameIndices"]), (0, 2))
            self.assertEqual(sorted(review["poses"]), [0, 2])
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_resume_fingerprint_changes_when_source_pixels_change(self):
        root = runner.TOOL / "_contract_test_tmp" / "fingerprint"
        root.mkdir(parents=True, exist_ok=True)
        try:
            pilot = root / "pilot"
            (pilot / "frames_ground_truth").mkdir(parents=True)
            (pilot / "frames_ground_truth_shadow_culled").mkdir(parents=True)
            (pilot / "frames_ground_truth" / "original_frames.json").write_text("{}", encoding="utf-8")
            source = pilot / "frames_ground_truth" / "00.png"
            shadow = pilot / "frames_ground_truth_shadow_culled" / "00.png"
            source.write_bytes(b"source-a")
            shadow.write_bytes(b"shadow-a")
            mesh = root / "mesh.glb"
            camera = root / "camera.json"
            mesh.write_bytes(b"mesh")
            camera.write_bytes(b"camera")

            first = runner._clip_input_fingerprint(
                unit_name="unit",
                animation_name="move_g0",
                mesh=mesh,
                pilot_dir=pilot,
                camera_fit=camera,
                config=RocHybridConfig(),
            )
            shadow.write_bytes(b"shadow-b")
            second = runner._clip_input_fingerprint(
                unit_name="unit",
                animation_name="move_g0",
                mesh=mesh,
                pilot_dir=pilot,
                camera_fit=camera,
                config=RocHybridConfig(),
            )
            self.assertNotEqual(first["shadowCulledFrames"], second["shadowCulledFrames"])
        finally:
            shutil.rmtree(root.parent, ignore_errors=True)

    def test_proxy_economic_and_audit_controls_are_exposed(self):
        config = RocHybridConfig(
            proxy_enabled=True,
            proxy_min_candidates=8,
            proxy_protected_stages=("rotation_vector", "keypoint_probe"),
            proxy_audit_enabled=True,
            proxy_audit_fraction=0.10,
            proxy_audit_max_candidates=4,
        )
        namespace = config.namespace()
        self.assertEqual(namespace["PROXY_MIN_CANDIDATES"], 8)
        self.assertEqual(namespace["PROXY_PROTECTED_STAGES"], ("rotation_vector", "keypoint_probe"))
        self.assertEqual(namespace["PROXY_AUDIT_MAX_CANDIDATES"], 4)

    def test_proxy_audit_fraction_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            RocHybridConfig(proxy_audit_fraction=1.1)
        with self.assertRaises(ValueError):
            RocHybridConfig(proxy_min_candidates=0)


if __name__ == "__main__":
    unittest.main()
