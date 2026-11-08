import sys
import types
import unittest
from unittest.mock import patch
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import corrected_mounted_authoring as builder


def anatomy(asset="h3_wolf_raider"):
    bones = ("Bone_000", "Bone_001", "Bone_002")
    return types.SimpleNamespace(
        MESH_ASSET=asset, MESH_SHA256="hash-" + asset,
        SOURCE_BONES=frozenset(bones), SOURCE_GROUPS={"mount_torso": bones},
        MOUNT_MAP={"Hips": "Bone_000"}, RIDER_MAP={"mixamorig:Hips": "Bone_001"},
        MOUNT_POINTS={"Spine": (0, 0, 0)}, RIDER_POINTS={"mixamorig:Head": (0, 1, 0)},
        REGION_VOLUMES=(), AUTHORING_PROOF="candidate",
    )


class CorrectedMountedAuthoringTests(unittest.TestCase):
    def test_serialized_rigid_owner_comes_from_profile(self):
        profile = {'rigidAttachments': ({'region': 'weapon', 'donorJoints': ('rider:mixamorig:LeftHand',)},)}
        self.assertEqual(builder._rigid_attachments(profile), {'weapon': 'rider:mixamorig:LeftHand'})
        profile['rigidAttachments'] *= 2
        with self.assertRaisesRegex(ValueError, 'unique owner'):
            builder._rigid_attachments(profile)

    def test_source_groups_cover_corrected_mesh_names_exactly(self):
        import wolf_rider_corrected_anatomy as anatomy
        names = {f"Bone_{index:03d}" for index in range(58)}
        self.assertEqual(anatomy.SOURCE_BONES, names)
        self.assertEqual(sum(len(group) for group in anatomy.SOURCE_GROUPS.values()), 58)

    def test_donor_anchor_maps_cover_offline_packages(self):
        import wolf_rider_corrected_anatomy as anatomy
        from vendor_reference import load_complete_package
        mount = load_complete_package("zoo", "Coyote#Coyote-Attack1/y0")
        rider = load_complete_package("obj", "00160523-f3b6-5765-931a-351e339862d7#00160523-f3b6-5765-931a-351e339862d7/y0")
        self.assertEqual(set(mount["jointNames"]) - set(anatomy.MOUNT_MAP) - set(anatomy.MOUNT_POINTS), set())
        self.assertEqual(set(rider["jointNames"]) - set(anatomy.RIDER_MAP) - set(anatomy.RIDER_POINTS), set())

    def test_profile_uses_correct_identity_and_rigid_grip(self):
        import wolf_rider_corrected_anatomy as anatomy
        profile = builder.get_profile()
        self.assertEqual(profile["assetId"], "h3_wolf_rider")
        self.assertEqual(profile["expectedMeshSha256"], anatomy.MESH_SHA256)
        self.assertEqual(profile["rigidAttachments"][0]["donorJoints"], ("rider:mixamorig:RightHand",))
        self.assertEqual(profile["captureBind"]["leftJoint"], "mount:Bip01_L_Thigh")
        self.assertIn("Bone_032", anatomy.SOURCE_GROUPS["weapon"])

    def test_horse_anatomy_covers_mesh_and_donor_packages(self):
        from vendor_reference import load_complete_package
        mount = load_complete_package("zoo", "Horse#HorseALL-Attack/y0")
        rider = load_complete_package("obj", "00160523-f3b6-5765-931a-351e339862d7#00160523-f3b6-5765-931a-351e339862d7/y0")
        for asset, module_name, count in (
            ("h3_cavalier", "h3_cavalier_anatomy", 52),
            ("h3_champion", "h3_champion_anatomy", 50),
            ("h3_justiciar", "h3_justiciar_anatomy", 67),
            ("h3_black_knight", "h3_black_knight_anatomy", 55),
            ("h3_dread_knight", "h3_dread_knight_anatomy", 57),
        ):
            anatomy = __import__(module_name)
            self.assertEqual(len(anatomy.SOURCE_BONES), count)
            self.assertEqual(sum(map(len, anatomy.SOURCE_GROUPS.values())), count)
            self.assertFalse(set(mount["jointNames"]) - set(anatomy.MOUNT_MAP) - set(anatomy.MOUNT_POINTS))
            self.assertFalse(set(rider["jointNames"]) - set(anatomy.RIDER_MAP) - set(anatomy.RIDER_POINTS))
            profile = builder.get_profile(asset)
            self.assertEqual(profile["assetId"], asset)
            self.assertEqual(profile["expectedMeshSha256"], anatomy.MESH_SHA256)
            self.assertEqual(profile["captureBind"]["headJoint"], "mount:Bip01_Head")
            self.assertEqual(profile["captureBind"]["leftJoint"], "mount:Bip01_L_Thigh")
            joints = {name for names in profile["regionJoints"].values() for name in names}
            composite = {f"mount:{name}" for name in mount["jointNames"]} | {
                f"rider:{name}" for name in rider["jointNames"]
            }
            self.assertTrue(joints <= composite)
            self.assertNotIn("mount:Bip01_L_Finger01", joints)

    def test_raider_anatomy_covers_mesh_and_donor_packages(self):
        import wolf_raider_anatomy as anatomy
        from vendor_reference import load_complete_package
        self.assertEqual(anatomy.SOURCE_BONES, {f"Bone_{i:03d}" for i in range(57)})
        self.assertEqual(sum(map(len, anatomy.SOURCE_GROUPS.values())), 57)
        mount = load_complete_package("zoo", "Coyote#Coyote-Attack1/y0")
        rider = load_complete_package("obj", "00160523-f3b6-5765-931a-351e339862d7#00160523-f3b6-5765-931a-351e339862d7/y0")
        self.assertFalse(set(mount["jointNames"]) - set(anatomy.MOUNT_MAP) - set(anatomy.MOUNT_POINTS))
        self.assertFalse(set(rider["jointNames"]) - set(anatomy.RIDER_MAP) - set(anatomy.RIDER_POINTS))

    def test_routes_explicit_asset_and_preserves_default(self):
        with patch.dict(builder.IDENTITIES, {
            "h3_wolf_rider": {"mesh": Path("rider.glb"), "sha256": "hash-h3_wolf_rider"},
            "h3_wolf_raider": {"mesh": Path("raider.glb"), "sha256": "hash-h3_wolf_raider"},
        }, clear=True), patch.object(builder.importlib, "import_module", side_effect=lambda name: anatomy(
            "h3_wolf_raider" if name == "wolf_raider_anatomy" else "h3_wolf_rider")):
            self.assertEqual(builder.get_profile()["assetId"], "h3_wolf_rider")
            self.assertEqual(builder.get_profile("h3_wolf_raider")["displayName"], "Wolf Raider")

    def test_rejects_duplicate_source_group_bones(self):
        bad = anatomy()
        bad.SOURCE_GROUPS = {"a": ("Bone_000", "Bone_001"), "b": ("Bone_001", "Bone_002")}
        with patch.dict(builder.IDENTITIES, {"h3_wolf_raider": {"mesh": Path("x"), "sha256": "hash-h3_wolf_raider"}}, clear=True), \
             patch.object(builder.importlib, "import_module", return_value=bad):
            with self.assertRaisesRegex(ValueError, "exactly once"):
                builder.get_profile("h3_wolf_raider")

    def test_rejects_unknown_map_anchor(self):
        bad = anatomy()
        bad.RIDER_MAP = {"mixamorig:Hips": "Bone_999"}
        with patch.dict(builder.IDENTITIES, {"h3_wolf_raider": {"mesh": Path("x"), "sha256": "hash-h3_wolf_raider"}}, clear=True), \
             patch.object(builder.importlib, "import_module", return_value=bad):
            with self.assertRaisesRegex(ValueError, "unknown source anchor"):
                builder.get_profile("h3_wolf_raider")

    def test_rejects_unknown_region(self):
        bad = anatomy()
        bad.SOURCE_GROUPS = {"not_a_region": ("Bone_000", "Bone_001", "Bone_002")}
        with patch.dict(builder.IDENTITIES, {"h3_wolf_raider": {"mesh": Path("x"), "sha256": "hash-h3_wolf_raider"}}, clear=True), \
             patch.object(builder.importlib, "import_module", return_value=bad):
            with self.assertRaisesRegex(ValueError, "unknown or empty region"):
                builder.get_profile("h3_wolf_raider")

    def test_rejects_missing_inventory_and_invalid_volume(self):
        bad = anatomy()
        with patch.dict(builder.IDENTITIES, {"h3_wolf_raider": {"mesh": Path("x"), "sha256": "hash-h3_wolf_raider"}}, clear=True), \
             patch.object(builder.importlib, "import_module", return_value=bad):
            del bad.SOURCE_BONES
            with self.assertRaisesRegex(ValueError, "declare SOURCE_BONES"):
                builder.get_profile("h3_wolf_raider")
            bad.SOURCE_BONES = frozenset(bad.SOURCE_GROUPS['mount_torso'])
            bad.REGION_VOLUMES = ({'region': 'missing', 'sourcePrefix': 'mount_', 'min': (0, 0, 0), 'max': (1, 1, 1)},)
            with self.assertRaisesRegex(ValueError, "volume ownership"):
                builder.get_profile("h3_wolf_raider")
            bad.REGION_VOLUMES[0]['region'] = 'rider_torso'
            bad.REGION_VOLUMES[0]['max'] = (-1, 1, 1)
            with self.assertRaisesRegex(ValueError, "volume bounds"):
                builder.get_profile("h3_wolf_raider")


if __name__ == "__main__":
    unittest.main()
