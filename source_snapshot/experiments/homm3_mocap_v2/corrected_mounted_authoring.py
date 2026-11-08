"""Build the corrected mounted anatomy without modifying historical inputs."""
import argparse
import importlib
import json
from pathlib import Path
import numpy as np
from asset_profiles import MIXAMO_REF_SEQ
from glb_skeleton import load_bind_skeleton
from mounted_asset_identity import IDENTITIES, validate_profile_identity
from pin import sha256_file
from target_asset import dense_weights
from vendor_reference import load_complete_package
from wolf_rider_authored import region_joints as coyote_region_joints


_ANATOMY_MODULES = {
    'h3_wolf_rider': 'wolf_rider_corrected_anatomy',
    'h3_wolf_raider': 'wolf_raider_anatomy',
    'h3_cavalier': 'h3_cavalier_anatomy',
    'h3_champion': 'h3_champion_anatomy',
    'h3_justiciar': 'h3_justiciar_anatomy',
    'h3_black_knight': 'h3_black_knight_anatomy',
    'h3_dread_knight': 'h3_dread_knight_anatomy',
}
_DISPLAY_NAMES = {
    'h3_wolf_rider': 'Wolf Rider',
    'h3_wolf_raider': 'Wolf Raider',
    'h3_cavalier': 'Cavalier',
    'h3_champion': 'Champion',
    'h3_justiciar': 'Justiciar',
    'h3_black_knight': 'Black Knight',
    'h3_dread_knight': 'Dread Knight',
}
MOUNT_REFS = {
    'h3_wolf_rider': 'Coyote#Coyote-Attack1/y0',
    'h3_wolf_raider': 'Coyote#Coyote-Attack1/y0',
    'h3_cavalier': 'Horse#HorseALL-Attack/y0',
    'h3_champion': 'Horse#HorseALL-Attack/y0',
    'h3_justiciar': 'Horse#HorseALL-Attack/y0',
    'h3_black_knight': 'Horse#HorseALL-Attack/y0',
    'h3_dread_knight': 'Horse#HorseALL-Attack/y0',
}


HORSE_REF = "Horse#HorseALL-Attack/y0"


def region_joints_for_ref(ref: str) -> dict[str, tuple[str, ...]]:
    """Composite skin ownership must name joints that exist on that mount."""
    if ref == HORSE_REF:
        from asset_profiles import MIXAMO_REGION_JOINTS

        groups = {
            "mount_torso": ("Hips", "Bip01_Pelvis", "Bip01_Spine", "Bip01_Spine1", "Bip01_Spine2", "Bip01_Neck"),
            "mount_head": ("Bip01_Neck1", "Bip01_Head", "Bip01_Jaw", "Bip01_R_Ear_01", "Bip01__L_Ear_01"),
            "mount_tail": ("BN_Tail_01", "BN_Tail_02", "BN_Tail_03", "BN_Tail_04", "BN_Tail_05"),
        }
        for side, label in (("L", "left"), ("R", "right")):
            groups[f"mount_hind_{label}"] = tuple(
                f"Bip01_{side}_{part}" for part in ("Thigh", "Calf", "HorseLink", "Foot", "Toe0")
            )
            groups[f"mount_front_{label}"] = tuple(
                f"Bip01_{side}_{part}" for part in ("Clavicle", "UpperArm", "Forearm", "Hand", "Finger0")
            )
        result = {key: tuple(f"mount:{name}" for name in names) for key, names in groups.items()}
        result.update({f"rider_{key}": tuple(f"rider:{name}" for name in names) for key, names in MIXAMO_REGION_JOINTS.items()})
        result["weapon"] = ("rider:mixamorig:RightHand",)
        return result
    if "Coyote" in ref:
        return coyote_region_joints()
    raise ValueError(f"unsupported mounted donor ref: {ref}")


def _load_anatomy(asset):
    if asset not in _ANATOMY_MODULES or asset not in IDENTITIES:
        raise ValueError(f'unsupported mounted asset: {asset!r}')
    module = importlib.import_module(_ANATOMY_MODULES[asset])
    if module.MESH_ASSET != asset or module.MESH_SHA256 != IDENTITIES[asset]['sha256']:
        raise ValueError(f'{asset}: anatomy identity does not match mounted asset identity')
    groups = [bone for bones in module.SOURCE_GROUPS.values() for bone in bones]
    if not hasattr(module, 'SOURCE_BONES'):
        raise ValueError(f'{asset}: anatomy must declare SOURCE_BONES')
    declared = set(module.SOURCE_BONES)
    if len(groups) != len(set(groups)) or set(groups) != declared:
        raise ValueError(f'{asset}: source groups must cover each source bone exactly once')
    anchors = [*module.MOUNT_MAP.values(), *module.RIDER_MAP.values()]
    if not set(anchors) <= set(module.SOURCE_BONES):
        raise ValueError(f'{asset}: donor map references an unknown source anchor')
    if set(module.MOUNT_MAP) & set(module.MOUNT_POINTS) or set(module.RIDER_MAP) & set(module.RIDER_POINTS):
        raise ValueError(f'{asset}: map and explicit anchors overlap')
    valid_regions = set(region_joints_for_ref(MOUNT_REFS[asset]))
    if not set(module.SOURCE_GROUPS) <= valid_regions or any(not name for name in module.SOURCE_GROUPS):
        raise ValueError(f'{asset}: source groups contain an unknown or empty region')
    for rule in module.REGION_VOLUMES:
        if rule['region'] not in valid_regions or not rule['sourcePrefix']:
            raise ValueError(f'{asset}: invalid region volume ownership')
        lo, hi = np.asarray(rule['min']), np.asarray(rule['max'])
        if lo.shape != (3,) or hi.shape != (3,) or not np.isfinite([lo, hi]).all() or np.any(lo > hi):
            raise ValueError(f'{asset}: invalid region volume bounds')
    return module


def get_profile(asset='h3_wolf_rider'):
    anatomy = _load_anatomy(asset)
    identity=IDENTITIES[asset]
    profile=dict(assetId=asset,displayName=_DISPLAY_NAMES[asset],mesh=identity['mesh'],
        expectedMeshSha256=anatomy.MESH_SHA256,requireCompleteRegionCoverage=True,
        regionBones=anatomy.SOURCE_GROUPS,regionJoints=region_joints_for_ref(MOUNT_REFS[asset]),
        wholeBodyHubs=('mount:Hips','mount:Bip01_Neck','mount:Bip01_L_Thigh','mount:Bip01_R_Thigh'),
        rigidAttachments=({'region':'weapon','donorJoints':('rider:mixamorig:RightHand',),'reason':'source blade-base grip'},),
        captureBind={'headJoint':'mount:Bip01_Head','leftJoint':'mount:Bip01_L_Thigh','rightJoint':'mount:Bip01_R_Thigh','meshBodyAxis':(0.0,0.0,1.0),'meshSecondAxis':(0.0,1.0,0.0),'skinFrozenRegions':()})
    validate_profile_identity(profile)
    return profile


def offsets(rest,parents):
    result=rest.copy()
    for i,p in enumerate(parents):
        if p>=0:result[i]-=rest[p]
    return result


def _rigid_attachments(profile):
    result = {}
    for attachment in profile['rigidAttachments']:
        if len(attachment['donorJoints']) != 1 or attachment['region'] in result:
            raise ValueError('rigid attachments require one unique owner per region')
        result[attachment['region']] = attachment['donorJoints'][0]
    return result


def build(output,mount_corpus,rider_corpus,asset='h3_wolf_rider'):
    if output.exists():raise FileExistsError(output)
    anatomy = _load_anatomy(asset)
    profile=get_profile(asset);mesh=profile['mesh']
    if sha256_file(mesh)!=profile['expectedMeshSha256']:raise ValueError('source mesh changed')
    bind=load_bind_skeleton(mesh);anchors=dict(zip(bind.names,bind.rest_world))
    mount=load_complete_package('zoo', MOUNT_REFS[asset])
    rider=load_complete_package('obj',MIXAMO_REF_SEQ)
    def rest(package,mapping,points):
        names=list(package['jointNames'])
        if set(mapping)&set(points) or set(mapping)|set(points)!=set(names):raise ValueError('donor anchors must have exact nonoverlapping coverage')
        return np.array([anchors[mapping[n]] if n in mapping else points[n] for n in names],dtype=float)
    mr=rest(mount,anatomy.MOUNT_MAP,anatomy.MOUNT_POINTS);rr=rest(rider,anatomy.RIDER_MAP,anatomy.RIDER_POINTS)
    mn,rn=list(mount['jointNames']),list(rider['jointNames']);mp,rp=np.array(mount['parents']),np.array(rider['parents'])
    seat=mn.index('Bip01_Spine1');names=['mount:'+n for n in mn]+['rider:'+n for n in rn]
    parents=np.concatenate([mp,np.where(rp<0,seat,rp+len(mn))]);combined=np.concatenate([mr,rr]);co=offsets(combined,parents)
    mapping={name:region for region,bones in anatomy.SOURCE_GROUPS.items() for name in bones}
    if set(mapping)!=set(bind.names):raise ValueError('source group coverage changed')
    regions=np.array([mapping[bind.names[i]] for i in dense_weights(bind).argmax(1)],dtype='U64')
    original_regions=regions.copy();volume_counts=[]
    for rule in anatomy.REGION_VOLUMES:
        mask=np.all((bind.vertices>=rule['min'])&(bind.vertices<=rule['max']),axis=1)&np.char.startswith(original_regions,rule['sourcePrefix'])
        regions[mask]=rule['region'];volume_counts.append(int(mask.sum()))
    def reference(path,actor_names):
        corpus=json.loads(path.read_text());row=next(r for r in corpus['captures'] if r['key']=='g02_idle')
        if sha256_file(Path(row['capture']))!=row['captureSha256']:raise ValueError('source capture changed')
        with np.load(row['capture']) as z:
            if list(z['joint_names'].astype(str))!=actor_names:raise ValueError('capture skeleton differs')
            return z['pred_position'][row['referenceIndex']].copy()
    mref=reference(mount_corpus,mn);rref=reference(rider_corpus,rn)
    output.mkdir(parents=True)
    author=Path(anatomy.__file__).resolve()
    manifest=dict(assetId=profile['assetId'],originalMesh=str(mesh),expectedMeshSha256=profile['expectedMeshSha256'],
        jointNames=names,parents=parents.tolist(),restAnchors=combined.tolist(),vertexRegions=regions.tolist(),
        allowedRegionJoints=region_joints_for_ref(MOUNT_REFS[asset]),rigidAttachments=_rigid_attachments(profile),
        authorProfile=str(author),authorProfileHash=sha256_file(author),builder=str(Path(__file__).resolve()),builderSha256=sha256_file(Path(__file__)),
        authoringPolicy=anatomy.AUTHORING_PROOF,visualAcceptance='candidate_not_animation_accepted',
        regionVolumeCounts=volume_counts,regionCounts={str(k):int(v) for k,v in zip(*np.unique(regions,return_counts=True))})
    (output/'authoring.json').write_text(json.dumps(manifest,indent=2))
    np.savez(output/'composition_preparation.npz',mount_names=mn,mount_parents=mp,mount_capture_reference=mref,
        mount_capture_offsets=mount['offsets'],mount_fitted_offsets=offsets(mr,mp),mount_hubs=['Hips','Bip01_Neck','Bip01_L_Thigh','Bip01_R_Thigh'],
        rider_names=rn,rider_parents=rp,rider_capture_reference=rref,rider_capture_offsets=rider['offsets'],rider_fitted_offsets=offsets(rr,rp),
        rider_hubs=['mixamorig:Hips','mixamorig:Spine2','mixamorig:LeftArm','mixamorig:RightArm'],combined_names=names,
        combined_parents=parents,combined_offsets=co,rider_held_indices=[i for i,n in enumerate(rn) if any(part in n for part in ('UpLeg','Leg','Foot','Toe'))],
        rider_held_rest=rr-rr[0],seat_parent=seat,seat_offset=co[len(mn)])
    print(json.dumps({'manifest':str(output/'authoring.json'),'sourceSha256':profile['expectedMeshSha256'],'regionCounts':manifest['regionCounts']},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('output','mount-corpus','rider-corpus'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--asset', choices=tuple(_ANATOMY_MODULES), default='h3_wolf_rider')
    a=p.parse_args();build(a.output,a.mount_corpus,a.rider_corpus,a.asset)
