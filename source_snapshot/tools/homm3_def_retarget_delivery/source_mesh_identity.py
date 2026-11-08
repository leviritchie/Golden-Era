"""Mesh identity at freeze and ship: a delivered GLB must be built from the unit's reviewed source mesh.

attest(unit, glb) -> {"sourceMeshSha256", "identityReview"} or IdentityError. The source mesh is read from the GLB's
source-mesh stamp (tools/homm3_def_retarget/source_mesh.py, written by build_unit.py + export_glb.py). The rule:
  - the unit has an identity review (artifacts/homm3_mesh_repair_fleet_v1/identity_reviews.json, verified_correct):
    the source sha must be the review's defRetargetMesh.sha256 when it has one (meshSha256 pins the mesh-repair lane's
    coverage mesh, which for a few units is not the file run_unit.sh builds from), else its meshSha256;
    identityReview = that sha;
  - no review: the source must be the unit's own current artifacts/meshy_downloads/<unit>_smartrigged.glb (same sha
    on disk now); identityReview = "none";
  - a stamped source under meshy_downloads/_superseded_do_not_use/ is refused.
Transition: a GLB without the stamp (its .blend was built before the stamp landed) passes only through
source_mesh_legacy.json, whose per-unit entry pins the body's UV set (identical across re-bakes and re-exports of one
build, different for any other Meshy mesh) and the source sha that build was attested to at landing. The list only
shrinks (test_source_mesh_identity.py checks it against its first commit); a full run_unit.sh build stamps the unit
and its entry can go. Anything else refuses and needs that rebuild. Proof tier: generated artifact.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget"))
import source_mesh  # noqa: E402

REVIEWS = ROOT / "artifacts/homm3_mesh_repair_fleet_v1/identity_reviews.json"
LEGACY = ROOT / "tools/homm3_def_retarget/source_mesh_legacy.json"   # not beside the slices: every *.json there is a selection
LEGACY_SCHEMA = "homm3_def_retarget.source_mesh_legacy.v1"
MESHY = "artifacts/meshy_downloads"
SUPERSEDED = "_superseded_do_not_use"
REBUILD = "rebuild it (tools/homm3_def_retarget/run_unit.sh <unit>, a full build, then fleet_rebuild.py) on the right mesh"


class IdentityError(Exception):
    pass


def own_mesh(unit: str) -> str:
    return f"{MESHY}/{unit}_smartrigged.glb"


def read_glb(path: Path) -> tuple[dict, bytes]:
    b = Path(path).read_bytes()
    jl = struct.unpack_from("<I", b, 12)[0]
    js = json.loads(b[20:20 + jl])
    bl = struct.unpack_from("<I", b, 20 + jl)[0]
    return js, b[28 + jl:28 + jl + bl]


def uv_set_sha256(js: dict, binb: bytes) -> str:
    """sha256 of the body mesh's TEXCOORD_0 set (unique, quantised to 1/4096, sorted). The body is the skinned mesh
    with the most vertices that is not <unit>_Rubble."""
    best = None
    for n in js.get("nodes", []):
        if "mesh" not in n or n.get("name", "").endswith("_Rubble"):
            continue
        m = js["meshes"][n["mesh"]]
        nv = sum(js["accessors"][p["attributes"]["POSITION"]]["count"] for p in m["primitives"])
        if best is None or nv > best[0]:
            best = (nv, m)
    if best is None:
        raise IdentityError("GLB has no mesh")
    uvs = []
    for p in best[1]["primitives"]:
        i = p["attributes"].get("TEXCOORD_0")
        if i is None:
            raise IdentityError("body mesh primitive has no TEXCOORD_0")
        a = js["accessors"][i]
        bv = js["bufferViews"][a["bufferView"]]
        if a["componentType"] != 5126 or a["type"] != "VEC2" or bv.get("byteStride", 8) != 8:
            raise IdentityError("body TEXCOORD_0 is not a tightly packed float VEC2")
        uvs.append(np.frombuffer(binb, "<f4", a["count"] * 2, bv.get("byteOffset", 0) + a.get("byteOffset", 0)))
    q = np.unique(np.round(np.concatenate(uvs).reshape(-1, 2).astype(np.float64) * 4096).astype("<i8"), axis=0)
    return hashlib.sha256(q.tobytes()).hexdigest()


def load_reviews() -> dict:
    return json.loads(REVIEWS.read_text(encoding="utf-8"))["reviews"]


def load_legacy() -> dict:
    d = json.loads(LEGACY.read_text(encoding="utf-8"))
    if d.get("schema") != LEGACY_SCHEMA:
        raise IdentityError(f"{LEGACY.name} is not {LEGACY_SCHEMA}")
    return d["units"]


def expected(unit: str, reviews: dict) -> tuple[str, str]:
    """(the source sha this unit must be built from, identityReview)"""
    r = reviews.get(unit)
    if r is not None:
        # meshSha256 pins the coverage-selected mesh (mesh-repair/mocap lane); where def_retarget builds from a different
        # file, the review carries that file's own verdict as defRetargetMesh
        r = r.get("defRetargetMesh", r)
        if r.get("status") != "verified_correct":
            raise IdentityError(f"identity review status {r.get('status')!r} is not verified_correct")
        want = r.get("sha256", r.get("meshSha256"))
        if not (isinstance(want, str) and len(want) == 64):
            raise IdentityError("identity review has no mesh sha256")
        return want, want
    p = ROOT / own_mesh(unit)
    if not p.is_file():
        raise IdentityError(f"no identity review and no {own_mesh(unit)}")
    return source_mesh.file_sha256(p), "none"


def attest(unit: str, glb: Path, reviews: dict | None = None, legacy: dict | None = None) -> dict:
    reviews = load_reviews() if reviews is None else reviews
    js, binb = read_glb(glb)
    st = source_mesh.glb_stamp(js)
    if st is not None:
        bad = source_mesh.stamp_errors(st)
        if bad:
            raise IdentityError("; ".join(bad))
        if SUPERSEDED in Path(st["path"]).parts:
            raise IdentityError(f"built from a superseded mesh {st['path']}; {REBUILD}")
        if reviews.get(unit) is None and st["path"] != own_mesh(unit):
            raise IdentityError(f"no identity review and built from {st['path']}, not {own_mesh(unit)}; {REBUILD}")
        src, how = st["sha256"], f"stamped source {st['path']}"
    else:
        e = (load_legacy() if legacy is None else legacy).get(unit)
        if e is None:
            raise IdentityError(f"GLB has no {source_mesh.STAMP} stamp and the unit is not in {LEGACY.name}; {REBUILD}")
        uv = uv_set_sha256(js, binb)
        if uv != e["uvSetSha256"]:
            raise IdentityError(f"unstamped GLB's body UV set {uv[:12]} is not the attested pre-stamp build's "
                                f"{e['uvSetSha256'][:12]} ({LEGACY.name}): a different mesh; {REBUILD}")
        src, how = e["sourceMeshSha256"], f"pre-stamp build attested in {LEGACY.name}"
    want, review = expected(unit, reviews)
    if src != want:
        what = f"the identity review's meshSha256 {want[:12]}" if review != "none" else \
            f"the current {own_mesh(unit)} {want[:12]} (no identity review)"
        raise IdentityError(f"source mesh {src[:12]} ({how}) is not {what}; {REBUILD}")
    return {"sourceMeshSha256": src, "identityReview": review}
