import json
import shutil
import uuid
import unittest
from pathlib import Path

from experiments.homm3_mocap_v2.validate_stronghold_animation_status import validate


class StrongholdStatusTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[2]
    status = root / "experiments/homm3_mocap_v2/stronghold_animation_status.json"
    faction = root / "custom_factions/homm3_stronghold.json"

    def test_current_roster_is_complete(self):
        self.assertEqual(validate(self.status, self.faction)["unitCount"], 21)

    def test_duplicate_row_fails(self):
        work = self.root / (".status_test_" + uuid.uuid4().hex); work.mkdir()
        try:
            data = json.loads(self.status.read_text())
            data["units"].append(dict(data["units"][0]))
            path = work / "status.json"; path.write_text(json.dumps(data))
            with self.assertRaises(ValueError): validate(path, self.faction)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_wrong_asset_fit_fails(self):
        path = self.status.parent / (".status_test_" + uuid.uuid4().hex + ".json")
        try:
            data = json.loads(self.status.read_text())
            data["units"][0]["fit"] = data["units"][1]["fit"]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "does not match evidenceAsset"):
                validate(path, self.faction)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__": unittest.main()
