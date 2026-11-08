"""Source-mesh provenance: which Meshy file a def_retarget build was rigged from.

build_unit.py hashes the mesh it imports (run_unit.sh passes artifacts/meshy_downloads/<unit>_smartrigged.glb) and
keeps the stamp on the .blend's scene (SCENE_PROP), so every later export of that build -- run_unit.sh RENDER_ONLY,
bake_cs, emphasis deliver's work copy -- carries it. export_glb.py writes it into the GLB's asset.extras[STAMP]; the
delivery stages (deyaw, stride, low-pass, densify, prop floor, ground) and look.py patch asset.extras in place and
keep it. freeze_slice.py / ship_def_retarget_slice.py check it against the identity review
(tools/homm3_def_retarget_delivery/source_mesh_identity.py). Stdlib only: this module also runs inside Blender.
"""
import hashlib
import json
import os
import struct

STAMP = "homm3DefRetargetSourceMesh"
SCHEMA = "homm3_def_retarget.source_mesh.v1"
SCENE_PROP = STAMP
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def stamp_for(mesh_path):
    """The stamp for a mesh file; its path is repo-relative (a mesh outside the repo is refused)."""
    rel = os.path.relpath(os.path.abspath(mesh_path), ROOT).replace("\\", "/")
    if rel.startswith("../") or os.path.isabs(rel):
        raise ValueError(f"source mesh {mesh_path} is outside the repo {ROOT}")
    return {"schema": SCHEMA, "path": rel, "sha256": file_sha256(mesh_path)}


def stamp_errors(stamp):
    if not isinstance(stamp, dict) or stamp.get("schema") != SCHEMA:
        return [f"{STAMP} is not {SCHEMA}: {stamp!r}"[:300]]
    errs = []
    if not (isinstance(stamp.get("sha256"), str) and len(stamp["sha256"]) == 64):
        errs.append(f"{STAMP} has no sha256")
    if not isinstance(stamp.get("path"), str) or not stamp["path"]:
        errs.append(f"{STAMP} has no path")
    return errs


def write_glb_stamp(glb_path, stamp):
    """Put stamp into asset.extras[STAMP] of a GLB in place (atomic replace); the BIN chunk is copied untouched."""
    bad = stamp_errors(stamp)
    if bad:
        raise ValueError("; ".join(bad))
    write_glb_extras(glb_path, STAMP, stamp)


def write_glb_extras(glb_path, key, value):
    """Put value into asset.extras[key] of a GLB in place (atomic replace); the BIN chunk is copied untouched."""
    with open(glb_path, "rb") as f:
        b = f.read()
    magic, version, _ = struct.unpack_from("<III", b, 0)
    jl, jt = struct.unpack_from("<II", b, 12)
    if magic != 0x46546C67 or version != 2 or jt != 0x4E4F534A:
        raise ValueError(f"{glb_path} is not a glTF 2 binary with a JSON first chunk")
    js = json.loads(b[20:20 + jl])
    js.setdefault("asset", {}).setdefault("extras", {})[key] = value
    new = json.dumps(js, separators=(",", ":")).encode("utf-8")
    new += b" " * (-len(new) % 4)
    rest = b[20 + jl:]
    out = bytearray(b[:12]) + struct.pack("<II", len(new), 0x4E4F534A) + new + rest
    struct.pack_into("<I", out, 8, len(out))
    tmp = glb_path + ".srcmesh.tmp"
    with open(tmp, "wb") as f:
        f.write(out)
    os.replace(tmp, glb_path)


def glb_stamp(js):
    """The stamp in a parsed GLB JSON, or None."""
    return (js.get("asset", {}).get("extras") or {}).get(STAMP)
