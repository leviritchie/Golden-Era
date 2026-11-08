"""Explicit new Boar surface and two-actor donor facts; animation unvalidated."""
from paths import REPO

MOUNT_REF = 'Coyote#Coyote-Attack1/y0'
RIDER_REF = '00160523-f3b6-5765-931a-351e339862d7#00160523-f3b6-5765-931a-351e339862d7/y0'
MESH = REPO / 'artifacts/homm3_mocap_v2/stronghold_takeover_review_v1/boar_rider_t2/generated.glb'
MESH_SHA256 = 'a1cba0e28c78e5f023def7f5f5f9d11cdcb9d3d56abce7a9fcc42dc80d3cb95c'


def get_profile():
    from asset_profiles import MIXAMO_REGION_JOINTS
    mount = {
        'torso': ('Hips', 'Bip01_Pelvis', 'Bip01_Spine', 'Bip01_Spine1', 'Bip01_Spine2', 'Bip01_Neck'),
        'head': ('Bip01_Neck1', 'Bip01_Head', 'BN_Mouth_01', 'BN_Ear_L_01', 'BN_Ear_R_01'),
        'tail': ('BN_Tail_01', 'BN_Tail_02', 'BN_Tail_03'),
    }
    for side, label in (('L', 'left'), ('R', 'right')):
        mount['hind_' + label] = tuple(f'Bip01_{side}_{part}' for part in ('Thigh', 'Calf', 'HorseLink', 'Foot', 'Toe0'))
        mount['front_' + label] = tuple(f'Bip01_{side}_{part}' for part in ('Clavicle', 'UpperArm', 'Forearm', 'Hand', 'Finger0', 'Finger01'))
    regions = {'mount_' + key: tuple('mount:' + name for name in names) for key, names in mount.items()}
    regions.update({'rider_' + key: tuple('rider:' + name for name in names)
                    for key, names in MIXAMO_REGION_JOINTS.items()})
    return {
        'assetId': 'h3_boar_rider', 'displayName': 'Boar Rider',
        'sourceAssetId': 'toa_boar_rider', 'runtimeSid': 'h3_wolf_rider_upg_alt',
        'mesh': MESH, 'expectedMeshSha256': MESH_SHA256,
        'regionJoints': regions, 'rigidAttachments': (),
        'captureActors': ({'role': 'mount', 'kind': 'zoo', 'refSeq': MOUNT_REF},
                          {'role': 'rider', 'kind': 'obj', 'refSeq': RIDER_REF}),
        'capturePolicy': 'two_actor_same_authentic_linked_reel_no_inherited_motion',
        'captureBind': {'headJoint': 'mount:Bip01_Head',
                        'leftJoint': 'mount:Bip01_L_Thigh',
                        'rightJoint': 'mount:Bip01_R_Thigh',
                        'meshBodyAxis': (0.0, 0.0, 1.0),
                        'meshSecondAxis': (0.0, 1.0, 0.0),
                        'skinFrozenRegions': ()},
        'proof': 'donor topology and source mesh pinned; Boar bind and animation not validated',
    }
