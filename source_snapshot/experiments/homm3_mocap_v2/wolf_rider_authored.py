"""Versioned mounted anatomy estimates, separate from immutable per-clip mocap."""
from pathlib import Path
import argparse
import json
import numpy as np
from asset_profiles import MIXAMO_REF_SEQ, MIXAMO_REGION_JOINTS
from glb_skeleton import load_bind_skeleton
from pin import sha256_file
from target_asset import dense_weights
from vendor_reference import load_complete_package

ROOT = Path(__file__).resolve().parents[2]
WOLF_MESH = ROOT / "artifacts/meshy_downloads/h3_wolf_raider_smartrigged.glb"  # b15de4cf: the RAIDER mesh (basenames swapped 2026-09-27)
MESH_SHA = "b15de4cfcd0ae93eebee224dae779ef9d8913f34cadfa86a65d86966a985916f"
COYOTE_REF_SEQ = "Coyote#Coyote-Attack1/y0"
SOURCE_GROUPS = {
    "mount_torso": (0,1,3,2,22,21,20), "mount_head": (34,33,32,52,51,54,53,56,55),
    "mount_tail": (7,6,5,4), "mount_hind_left": (19,18,17,16,15,14),
    "mount_hind_right": (13,12,11,10,9,8), "mount_front_left": (50,49,48,47,46,45),
    "mount_front_right": (44,43,42,41,40,39), "rider_arm_left": (31,30,29),
    "rider_arm_right": (38,37,36), "weapon": (35,), "rider_leg_left": (25,24,23), "rider_leg_right": (28,27,26),
}
MOUNT_MAP = {"Hips":1,"Bip01_Pelvis":1,"BN_Tail_01":7,"BN_Tail_02":5,"BN_Tail_03":4,
    "Bip01_Spine":3,"Bip01_Spine1":22,"Bip01_Spine2":21,"Bip01_Neck":20,"Bip01_Neck1":34,
    "Bip01_Head":32,"BN_Mouth_01":51,"BN_Ear_L_01":54,"BN_Ear_R_01":56}
for side,hind,front in (("L",(19,18,17,16,15),(50,49,48,47,46,45)),("R",(13,12,11,10,9),(44,43,42,41,40,39))):
    MOUNT_MAP.update({f"Bip01_{side}_{part}":bone for part,bone in zip(("Thigh","Calf","HorseLink","Foot","Toe0"),hind)})
    MOUNT_MAP.update({f"Bip01_{side}_{part}":bone for part,bone in zip(("Clavicle","UpperArm","Forearm","Hand","Finger0","Finger01"),front)})
# These landmarks do not exist in the source rig and are explicitly authored.
RIDER_POINTS = {"Hips":(.015,1.,-.12),"Spine":(.02,1.10,-.14),"Spine1":(.02,1.20,-.16),
    "Spine2":(.025,1.32,-.19),"Neck":(.015,1.40,-.18),"Head":(.015,1.50,-.15),"HeadTop_End":(.015,1.65,-.15),
    "LeftShoulder":(.10,1.33,-.16),"RightShoulder":(-.06,1.34,-.175),"LeftUpLeg":(.14,.96,-.18),
    "RightUpLeg":(-.12,.96,-.18),"LeftToe_End":(.36,.50,0),"RightToe_End":(-.34,.50,0)}
RIDER_MAP = {"LeftArm":31,"LeftForeArm":30,"LeftHand":29,"RightArm":38,"RightForeArm":37,"RightHand":36,
    "LeftLeg":25,"LeftFoot":24,"LeftToeBase":23,"RightLeg":28,"RightFoot":27,"RightToeBase":26}

def region_joints():
    groups = {"mount_torso":("Hips","Bip01_Pelvis","Bip01_Spine","Bip01_Spine1","Bip01_Spine2","Bip01_Neck"),
        "mount_head":("Bip01_Neck1","Bip01_Head","BN_Mouth_01","BN_Ear_L_01","BN_Ear_R_01"),
        "mount_tail":("BN_Tail_01","BN_Tail_02","BN_Tail_03")}
    for side,label in (("L","left"),("R","right")):
        groups[f"mount_hind_{label}"] = tuple(f"Bip01_{side}_{p}" for p in ("Thigh","Calf","HorseLink","Foot","Toe0"))
        groups[f"mount_front_{label}"] = tuple(f"Bip01_{side}_{p}" for p in ("Clavicle","UpperArm","Forearm","Hand","Finger0","Finger01"))
    result = {k:tuple("mount:"+n for n in v) for k,v in groups.items()}
    result.update({"rider_"+k:tuple("rider:"+n for n in v) for k,v in MIXAMO_REGION_JOINTS.items()})
    result["weapon"] = ("rider:mixamorig:RightHand",)
    return result

def get_profile():
    from mounted_asset_identity import validate_profile_identity
    profile = {"assetId":"h3_wolf_rider","displayName":"Wolf Rider","mesh":WOLF_MESH,"expectedMeshSha256":MESH_SHA,
        "requireCompleteRegionCoverage":True,"regionBones":{k:tuple(f"Bone_{n:03d}" for n in ids) for k,ids in SOURCE_GROUPS.items()},
        "regionJoints":region_joints(),"wholeBodyHubs":("mount:Hips","mount:Bip01_Neck","mount:Bip01_L_Thigh","mount:Bip01_R_Thigh"),
        "rigidAttachments":({"region":"weapon","donorJoints":("rider:mixamorig:RightHand",),"reason":"rigid sword grip"},)}
    # Legacy numerical anatomy belongs to the upgraded mesh. Preserve it for
    # historical diagnostics, but never emit a newly mislabeled preparation.
    validate_profile_identity(profile)
    return profile

def build_authoring(output, mount_corpus, rider_corpus):
    if output.exists(): raise FileExistsError(output)
    get_profile()
    if sha256_file(WOLF_MESH)!=MESH_SHA: raise ValueError("original mesh changed")
    bind=load_bind_skeleton(WOLF_MESH)
    anchors=dict(zip(bind.names,bind.rest_world))
    mount=load_complete_package("zoo",COYOTE_REF_SEQ); rider=load_complete_package("obj",MIXAMO_REF_SEQ)
    mn,rn=list(mount["jointNames"]),list(rider["jointNames"])
    mp,rp=np.asarray(mount["parents"]),np.asarray(rider["parents"])
    mr=np.array([anchors[f"Bone_{MOUNT_MAP[n]:03d}"] for n in mn])
    rr=np.array([anchors[f"Bone_{RIDER_MAP[n.split(':')[-1]]:03d}"] if n.split(':')[-1] in RIDER_MAP else RIDER_POINTS[n.split(':')[-1]] for n in rn])
    def offsets(rest,parents):
        out=rest.copy()
        for j,p in enumerate(parents):
            if p>=0: out[j]-=rest[p]
        return out
    seat=mn.index("Bip01_Spine1")
    names=["mount:"+n for n in mn]+["rider:"+n for n in rn]
    parents=np.concatenate([mp,np.where(rp<0,seat,rp+len(mn))]); rest=np.concatenate([mr,rr]); co=offsets(rest,parents)
    mapping={f"Bone_{n:03d}":k for k,ids in SOURCE_GROUPS.items() for n in ids}
    if set(mapping)!=set(bind.names) or sum(map(len,SOURCE_GROUPS.values()))!=len(bind.names): raise ValueError("source ownership incomplete")
    regions=np.array([mapping[bind.names[i]] for i in dense_weights(bind).argmax(axis=1)],dtype="U64")
    xyz=bind.vertices
    central=(xyz[:,1]>1.0)&(xyz[:,2]<.15)&(abs(xyz[:,0])<.18)&(regions!="weapon")
    regions[central]="rider_torso"; regions[central&(xyz[:,1]>1.35)]="rider_neck_head"
    def reference(path):
        corpus=json.loads(path.read_text()); row=next(r for r in corpus["captures"] if r["key"]=="g02_idle"); capture=Path(row["capture"])
        if sha256_file(capture)!=row["captureSha256"]: raise ValueError("actor idle changed")
        with np.load(capture) as raw: return raw["pred_position"][row["referenceIndex"]].copy()
    output.mkdir(parents=True)
    manifest={"assetId":"h3_wolf_rider","originalMesh":str(WOLF_MESH),"expectedMeshSha256":MESH_SHA,"jointNames":names,
        "parents":parents.tolist(),"restAnchors":rest.tolist(),"vertexRegions":regions.tolist(),"allowedRegionJoints":region_joints(),
        "rigidAttachments":{"weapon":"rider:mixamorig:RightHand"},"authorProfile":str(Path(__file__).resolve()),"authorProfileHash":sha256_file(Path(__file__)),
        "authoringPolicy":"source appendages; estimated rider torso landmarks and central ownership; fixed seated legs","visualAcceptance":"unreviewed",
        "regionCounts":{str(k):int(v) for k,v in zip(*np.unique(regions,return_counts=True))}}
    (output/"authoring.json").write_text(json.dumps(manifest,indent=2))
    np.savez(output/"composition_preparation.npz",mount_names=mn,mount_parents=mp,mount_capture_reference=reference(mount_corpus),
        mount_capture_offsets=mount["offsets"],mount_fitted_offsets=offsets(mr,mp),mount_hubs=["Hips","Bip01_Neck","Bip01_L_Thigh","Bip01_R_Thigh"],
        rider_names=rn,rider_parents=rp,rider_capture_reference=reference(rider_corpus),rider_capture_offsets=rider["offsets"],rider_fitted_offsets=offsets(rr,rp),
        rider_hubs=["mixamorig:Hips","mixamorig:Spine2","mixamorig:LeftArm","mixamorig:RightArm"],combined_names=names,combined_parents=parents,combined_offsets=co,
        rider_held_indices=[i for i,n in enumerate(rn) if any(part in n for part in ("UpLeg","Leg","Foot","Toe"))],
        rider_held_rest=rr-rr[0],seat_parent=seat,seat_offset=co[len(mn)])
    print(json.dumps({"authoring":str(output/"authoring.json"),"regionCounts":manifest["regionCounts"]},indent=2))

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);p.add_argument("--mount-corpus",type=Path,required=True);p.add_argument("--rider-corpus",type=Path,required=True)
    a=p.parse_args();build_authoring(a.output,a.mount_corpus,a.rider_corpus)
