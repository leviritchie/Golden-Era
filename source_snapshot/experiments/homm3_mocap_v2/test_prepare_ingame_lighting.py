"""Approved lighting provenance tests; these do not invoke Blender."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import prepare_ingame_lighting as lighting


class ApprovedLightingTests(unittest.TestCase):
    def fixture(self, root):
        raw = {"keyLight": {"strength": 10, "colorLinear": [1, .5, .25]},
               "floodLight": {"strength": 1, "colorLinear": [1, 1, 1]}}
        record = {"styleProfile": "approved-oe-v1", "approvedStyle": {}}
        for key in ("source", "bakedTexture", "engine"):
            path = root / key
            path.write_bytes(key.encode())
            if key == "engine":
                record["engineMaterial"] = {"output": str(path)}
                record["engineMaterialSha256"] = lighting.sha(path)
            else:
                record[key] = str(path)
                record[key + "Sha256"] = lighting.sha(path)
        paths = {k: root / k for k in ("sourceManifest", "rawSolution", "matteEngine", "styledSolution")}
        expected = lighting.redistribute_energy(raw, glb=paths["matteEngine"])
        for key, path in paths.items():
            value = raw if key == "rawSolution" else expected if key == "styledSolution" else {}
            path.write_text(json.dumps(value), encoding="utf-8")
            record["approvedStyle"].update({key: str(path), key + "Sha256": lighting.sha(path)})
        record["approvedStyle"]["parameters"] = expected["oeStyle"]
        baseline = {"sourceSha256": record["sourceSha256"],
                    "engineMaterialSha256": record["engineMaterialSha256"],
                    "freshSolve": {"solution": str(paths["rawSolution"]),
                                   "solutionSha256": lighting.sha(paths["rawSolution"])}}
        paths["sourceManifest"].write_text(json.dumps(baseline))
        record["approvedStyle"]["sourceManifestSha256"] = lighting.sha(paths["sourceManifest"])
        return record

    def test_valid_profile_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            lighting.validate_styled_lighting(self.fixture(Path(tmp)))

    def test_rejects_each_changed_dependency(self):
        for key in ("sourceManifest", "rawSolution", "matteEngine", "styledSolution"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                record = self.fixture(Path(tmp))
                Path(record["approvedStyle"][key]).write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    lighting.validate_styled_lighting(record)

    def test_rejects_rehashed_wrong_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = self.fixture(Path(tmp))
            evidence = record["approvedStyle"]
            path = Path(evidence["styledSolution"])
            data = json.loads(path.read_text())
            data["keyLight"]["strength"] = 9
            path.write_text(json.dumps(data))
            evidence["styledSolutionSha256"] = lighting.sha(path)
            with self.assertRaises(ValueError):
                lighting.validate_styled_lighting(record)

    def test_baseline_not_accepted_as_styled(self):
        with self.assertRaises(ValueError):
            lighting.validate_styled_lighting({"styleProfile": "baseline"})

    def test_unknown_profile_fails_before_work(self):
        with self.assertRaises(ValueError):
            lighting.prepare({}, Path("unused"), style_profile="unknown")

    def test_solve_only_rejects_incompatible_modes_before_work(self):
        for options in ({"style_profile": "approved-oe-v1"},
                        {"prepare_only": True}, {"reuse_prepared": True}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "solve-only"):
                lighting.prepare({}, Path("unused"), solve_only=True, **options)

    def test_fresh_solve_only_records_provenance_without_bake(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.glb"
            source.write_bytes(b"source")
            sprite = root / "sprite.png"
            sprite.write_bytes(b"sprite")
            report = root / "report.json"
            report.write_text("{}")
            corpus = root / "corpus.json"
            corpus.write_text(json.dumps({"sourceFrames": {str(sprite): {"sha256": lighting.sha(sprite)}}}))
            row = {"labSid": "test", "assetId": "test", "sourceReport": str(report),
                   "sourceReportSha256": lighting.sha(report), "corpus": str(corpus),
                   "corpusSha256": lighting.sha(corpus)}
            def material(src, dst):
                dst.write_bytes(b"engine")
                return {"output": str(dst)}
            def solve(command, **kwargs):
                path = Path(command[command.index("--out") + 1]) / "light_solution.json"
                path.write_text(json.dumps({"glb": command[command.index("--glb") + 1]}))
            with patch.object(lighting, "get_profile"), patch.object(lighting, "profile_mesh", return_value=source), \
                    patch.object(lighting, "write_engine_material_glb", side_effect=material), \
                    patch.object(lighting.subprocess, "run", side_effect=solve) as run, \
                    patch.object(lighting, "bake_lit_texture") as bake:
                result = lighting.prepare(row, root / "out", solve_only=True)
            run.assert_called_once()
            bake.assert_not_called()
            self.assertTrue(result["rawSolutionOnly"])
            self.assertNotIn("bakedTexture", result)
            self.assertIn("solutionSha256", result["freshSolve"])
            self.assertTrue((root / "out/units/test/lighting_manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
