import json
import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_owned_skinned_attack_remap as planner
from plan_owned_skinned_attack_remap import asset_file, desired_slots


class AttackSlotRemapPlanTests(unittest.TestCase):
    @contextmanager
    def fixture_root(self):
        base = planner.ROOT / "artifacts/homm3_attack_slot_remap_tests"
        root = base / ("case_" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        try:
            yield root
        finally:
            if root.resolve().parent != base.resolve() or not root.name.startswith("case_"):
                raise RuntimeError("refusing to remove an unscoped test fixture")
            shutil.rmtree(root)

    def fixture(self, root: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
        project = root / "unity"
        asset_root = project / "Assets/CustomUnits/homm3_lab/h3_mage/OwnedSkinned"
        (asset_root / "Animations").mkdir(parents=True)
        for name in ("owned_skinned.prefab", "owned_skinned.overrideController",
                     "Animations/Unit_AttackFront.anim", "Animations/Unit_ShootFront.anim",
                     "Source/master.glb"):
            path = asset_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode("ascii"))
        prefab = "Assets/CustomUnits/homm3_lab/h3_mage/OwnedSkinned/owned_skinned.prefab"
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"units": [{"unitSid": "h3_mage", "bundleName": "custom_units_h3_mage",
                                                  "battlePrefabAsset": prefab}]}), encoding="utf-8")
        import_table = root / "import.json"
        import_table.write_text(json.dumps({"entries": [{"bundleName": "custom_units_h3_mage",
                                                      "battlePrefabAssetPath": prefab,
                                                      "gameUnitSids": ["h3_mage"]}]}), encoding="utf-8")
        core = root / "Core.zip"
        with ZipFile(core, "w") as archive:
            archive.writestr("DB/units/units_views/h3_mage_v.json", json.dumps({"array": [{
                "id": "h3_mage",
                "defaultAttacks": [{"animationIndex": 1, "projectile": "bolt"}],
                "alternativeAttacks": [{"animationIndex": 0}],
            }]}))
        pilot = root / "artifacts/homm3_attack_slot_remap_pilot"
        return project, manifest, import_table, core, pilot / "h3_mage_plan.json", pilot / "h3_mage_report.json"

    def test_projectile_shot_and_melee_get_distinct_slots(self):
        views = {"h3_mage": {
            "id": "h3_mage",
            "defaultAttacks": [{"animationIndex": 1, "projectile": "bolt"}],
            "alternativeAttacks": [{"animationIndex": 0}],
            "counterAttacks": [{"animationIndex": 0}],
        }}
        self.assertEqual(desired_slots(views, ["h3_mage"]), [
            {"slot": "14.Attack", "clip": "Unit_AttackFront"},
            {"slot": "15.Skill_1", "clip": "Unit_ShootFront"},
        ])

    def test_nonprojectile_ability_uses_melee_even_if_a_shoot_clip_exists(self):
        views = {"h3_vampire_upg_alt": {
            "id": "h3_vampire_upg_alt",
            "defaultAttacks": [{"animationIndex": 0}],
            "abilities": [{"animationIndex": 1}],
        }}
        self.assertEqual(desired_slots(views, ["h3_vampire_upg_alt"]), [
            {"slot": "14.Attack", "clip": "Unit_AttackFront"},
            {"slot": "15.Skill_1", "clip": "Unit_AttackFront"},
        ])

    def test_conflicting_shot_and_ability_refuse_same_slot(self):
        views = {"h3_bad": {
            "id": "h3_bad",
            "defaultAttacks": [{"animationIndex": 1, "projectile": "bolt"}],
            "abilities": [{"animationIndex": 1}],
        }}
        with self.assertRaisesRegex(ValueError, "contract failed"):
            desired_slots(views, ["h3_bad"])

    def test_missing_view_and_escaping_asset_path_refuse(self):
        with self.assertRaisesRegex(ValueError, "no units_views row"):
            desired_slots({}, ["h3_missing"])
        with self.assertRaisesRegex(ValueError, "not a Unity Assets path"):
            asset_file(Path("V:/homm3_unity_work"), "Assets/../outside.anim")


if __name__ == "__main__":
    unittest.main()
