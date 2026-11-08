import unittest
from mounted_asset_identity import IDENTITIES, validate_profile_identity


class MountedIdentityTests(unittest.TestCase):
    def test_correct_semantic_mapping(self):
        for unit, row in IDENTITIES.items():
            validate_profile_identity(dict(assetId=unit,mesh=row['mesh'],expectedMeshSha256=row['sha256']))

    def test_wrong_variant_and_stale_hash_fail(self):
        rider=IDENTITIES['h3_wolf_rider'];raider=IDENTITIES['h3_wolf_raider']
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            validate_profile_identity(dict(assetId='h3_wolf_rider',mesh=raider['mesh'],expectedMeshSha256=raider['sha256']))
        with self.assertRaises(ValueError):
            validate_profile_identity(dict(assetId='h3_wolf_rider',mesh=rider['mesh'],expectedMeshSha256='stale'))

    def test_legacy_profile_is_not_current_wolf_rider(self):
        from wolf_rider_authored import get_profile
        with self.assertRaisesRegex(ValueError,'Rebuild anatomy'):
            get_profile()

    def test_current_profile_uses_correct_mesh(self):
        from asset_profiles import get_profile
        profile=get_profile('h3_wolf_rider')
        validate_profile_identity(profile)
        self.assertEqual(profile['mesh'],IDENTITIES['h3_wolf_rider']['mesh'])


if __name__=='__main__':
    unittest.main()
