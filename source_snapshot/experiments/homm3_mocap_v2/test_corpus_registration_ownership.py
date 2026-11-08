"""Regression tests for registration-owned calibration paths."""
import inspect
import unittest

import register_skin_corpus_asset
import run_skin_mesh_pilot


class RegistrationOwnershipTests(unittest.TestCase):
    def test_registration_calibration_is_output_owned(self):
        source = inspect.getsource(register_skin_corpus_asset.register)
        self.assertIn('calibration_path = output / "idle_reference.json"', source)
        self.assertNotIn('preparationDir', source)

    def test_mesh_runner_requires_explicit_calibration_path(self):
        source = inspect.getsource(run_skin_mesh_pilot.run)
        self.assertIn("inputs'].get('calibrationPath')", source)
        self.assertIn("baseline lacks explicit calibration ownership", source)
        self.assertIn("calibration_path = Path(previous['inputs']['calibrationPath'])", source)


if __name__ == "__main__":
    unittest.main()
