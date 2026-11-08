"""Semantic identity pins for mounted assets with misleading download names.

User-confirmed and visually inspected 2026-09-06. The wolf basenames were swapped on disk on 2026-09-27 so each file now names its own
unit; the sha256 pin, not the basename, still owns identity.
"""
from pathlib import Path
from pin import sha256_file

ROOT = Path(__file__).resolve().parents[2]
IDENTITIES = {
    'h3_wolf_rider': {
        'mesh': ROOT/'artifacts/meshy_downloads/h3_wolf_rider_smartrigged.glb',
        'sha256': '2fb1bb0700827cc1de2d8e67a68fc31d7816ccd0e76e7666e72ea0619a0fd00a',
        'appearance': 'unhelmeted rider on gray wolf',
    },
    'h3_wolf_raider': {
        'mesh': ROOT/'artifacts/meshy_downloads/h3_wolf_raider_smartrigged.glb',
        'sha256': 'b15de4cfcd0ae93eebee224dae779ef9d8913f34cadfa86a65d86966a985916f',
        'appearance': 'helmeted rider on dark wolf',
    },
    'h3_cavalier': {
        'mesh': ROOT/'artifacts/meshy_downloads/h3_cavalier_smartrigged.glb',
        'sha256': 'b85ef5ffa1835def0eeb3eb583bbfd89ecd19de549335a369969ba2c0d31208c',
        'appearance': 'castle knight on a horse',
    },
    'h3_champion': {
        'mesh': ROOT/'artifacts/meshy_downloads/h3_champion_smartrigged.glb',
        'sha256': '1146b15ff90f3bb3686ce0647918553a54ea73e677b593376e02deb340b8a7bc',
        'appearance': 'upgraded castle knight on a horse',
    },
    'h3_justiciar': {
        'mesh': ROOT/'artifacts/meshy_downloads/h3_justiciar_smartrigged.glb',
        'sha256': '25c9b9e6e470ebf1c9603f76e2f0380d725ea727670e28683e745a7d05d9fed4',
        'appearance': 'castle justiciar on a horse',
    },
    'h3_black_knight': {
        'mesh': ROOT/'artifacts/meshy_downloads/h3_black_knight_smartrigged.glb',
        'sha256': '2ef974912b4095f22a2a1721e2dd54b873bcde3854df9e741258b8f8fa8a4404',
        'appearance': 'necropolis knight on a horse',
    },
    'h3_dread_knight': {
        'mesh': ROOT/'artifacts/meshy_downloads/h3_dread_knight_smartrigged.glb',
        'sha256': '491737bb55d65bde612191fec762ff0234d519595902e448936330705fb30d8b',
        'appearance': 'upgraded necropolis knight on a horse',
    },
}


def validate_profile_identity(profile):
    unit = profile['assetId']
    if unit not in IDENTITIES:
        return
    identity = IDENTITIES[unit]
    if Path(profile['mesh']).resolve() != identity['mesh'].resolve() or profile.get('expectedMeshSha256') != identity['sha256']:
        raise ValueError(f'{unit}: mounted mesh identity mismatch. Correct source is {identity["mesh"].name}; '
                         'the legacy Wolf Rider/Raider filenames are swapped. Rebuild anatomy and preparation, not just the path.')


def validate_files():
    for unit, identity in IDENTITIES.items():
        if sha256_file(identity['mesh']) != identity['sha256']:
            raise ValueError(f'{unit}: pinned mounted mesh bytes changed')
    return {'identityFilesValid': True, 'unitCount': len(IDENTITIES), 'preparationValidated': False}


if __name__ == '__main__':
    import json
    print(json.dumps(validate_files(),indent=2))
