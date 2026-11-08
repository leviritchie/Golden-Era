import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_homm3_stock_controller_identity import DONORS, check  # noqa: E402

ESQ, CRU = "d" * 32, "e" * 32
CLIP = "c" * 32


class StockControllerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=Path(__file__).resolve().parents[1] / "artifacts"))
        self.project = self.root / "unity"
        self.manifest = self.root / "manifest.json"
        units = []
        for sid, base in (("u_old", ESQ), ("u_new", CRU)):
            root = f"Assets/CustomUnits/homm3_lab/{sid}/OwnedSkinned"
            units.append({"unitSid": sid, "battlePrefabAsset": root + "/owned_skinned.prefab"})
            self.write(root + "/owned_skinned.prefab", "prefab")
            self.write(root + "/Animations/Unit_AttackFront.anim", "clip")
            self.write(root + "/Animations/Unit_AttackFront.anim.meta", f"guid: {CLIP}\n")
            self.write(root + "/owned_skinned.overrideController",
                       f"AnimatorOverrideController:\n  m_Controller: {{fileID: 9100000, guid: {base}, type: 2}}\n"
                       f"  - m_OriginalClip: {{fileID: 7400000, guid: {'a' * 32}, type: 2}}\n"
                       f"    m_OverrideClip: {{fileID: 7400000, guid: {CLIP}, type: 2}}\n")
        self.manifest.write_text(json.dumps({"units": units}), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, rel, text):
        path = self.project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def donors(self, esq, cru):
        for rel, guid in zip(DONORS, (esq, cru)):
            self.write(rel, "controller")
            self.write(rel + ".meta", f"fileFormatVersion: 2\nguid: {guid}\n")

    def test_unique_donors_resolve_both_cohorts(self):
        self.donors(ESQ, CRU)
        errors, summary = check(self.project, self.manifest)
        self.assertEqual(errors, [])
        self.assertEqual(summary["cohorts"], {DONORS[0]: 1, DONORS[1]: 1})

    def test_duplicated_donor_guid_fails_every_consumer(self):
        self.donors(ESQ, ESQ)
        errors, _ = check(self.project, self.manifest)
        self.assertTrue(any("declared by 2 .meta files" in e for e in errors))
        self.assertTrue(any(e.startswith("u_old:") for e in errors))
        self.assertTrue(any(e.startswith("u_new:") for e in errors))

    def test_override_clip_outside_unit_animations_fails(self):
        self.donors(ESQ, CRU)
        self.write("Assets/CustomUnits/homm3_lab/u_new/OwnedSkinned/Animations/Unit_AttackFront.anim.meta", f"guid: {'f' * 32}\n")
        errors, _ = check(self.project, self.manifest)
        self.assertEqual(len(errors), 1)
        self.assertIn("u_new: override clip", errors[0])


if __name__ == "__main__":
    unittest.main()
