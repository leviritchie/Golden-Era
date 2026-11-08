"""Goblin source-region data used by the profile; visual acceptance is unproven."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_skeleton import load_bind_skeleton

SOURCE_MESH = Path("artifacts/meshy_downloads/h3_goblin_smartrigged.glb")
SOURCE_SHA256 = "9210950c1990323c61af29cc112221853a902b89aa60ef90ab854acc22c41d49"
SOURCE_GROUPS = {
    "torso": tuple(f"Bone_{i:03d}" for i in (0, 1, 4, 3, 2)),
    "neck_head": tuple(f"Bone_{i:03d}" for i in (17, 16, 15, *range(28, 38))),
    "arm_left": tuple(f"Bone_{i:03d}" for i in (22, 21, 20, 19, 18, *range(38, 58))),
    "arm_right": tuple(f"Bone_{i:03d}" for i in (27, 26, 25, 24, 23, *range(58, 78))),
    "weapon": ("Bone_079", "Bone_078"),
    "leg_left": tuple(f"Bone_{i:03d}" for i in (14, 13, 12, 11, 10)),
    "leg_right": tuple(f"Bone_{i:03d}" for i in (9, 8, 7, 6, 5)),
}


def compute_source_sha256(mesh: Path = SOURCE_MESH) -> str:
    digest = hashlib.sha256()
    with mesh.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_candidate(mesh: Path = SOURCE_MESH) -> dict:
    mesh = Path(mesh).resolve()
    source_hash = compute_source_sha256(mesh)
    if source_hash != SOURCE_SHA256:
        raise ValueError("Goblin source mesh hash changed")
    skeleton = load_bind_skeleton(mesh)
    names = list(skeleton.names)
    parents = list(skeleton.parents)
    if len(names) != 80 or len(set(names)) != 80:
        raise ValueError("Goblin candidate expects 80 unique source bones")
    if any(parent >= index for index, parent in enumerate(parents) if parent >= 0):
        raise ValueError("source hierarchy is not ordered")
    by_bone = {bone: region for region, bones in SOURCE_GROUPS.items() for bone in bones}
    if set(by_bone) != set(names):
        raise ValueError("candidate seed groups do not cover every source bone exactly once")
    weapon_descendants = list(SOURCE_GROUPS["weapon"])
    return {"status": "candidate_unvalidated", "sourceMesh": str(mesh).replace("\\", "/"),
            "sourceSha256": source_hash,
            "jointCount": 80, "regions": SOURCE_GROUPS,
            "weaponCandidate": {"bone": "Bone_079", "descendants": weapon_descendants,
                                 "restAnchor": list(skeleton.rest_world[names.index("Bone_079")])}}


if __name__ == "__main__":
    import json
    print(json.dumps(build_candidate(), indent=2))
