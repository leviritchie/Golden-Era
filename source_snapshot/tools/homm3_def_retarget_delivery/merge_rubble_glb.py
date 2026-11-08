"""Merge a death shatter's ``<unit>_Rubble`` mesh into the body primitive, so the delivery ships it on the body SMR.

    python tools/homm3_def_retarget_delivery/merge_rubble_glb.py merge SRC DST NODE [NODE ...]
    python tools/homm3_def_retarget_delivery/merge_rubble_glb.py verify GLB
    python tools/homm3_def_retarget_delivery/merge_rubble_glb.py rows SLICE.json LABSID [LABSID ...] [--write]

build_unit.py ``shatter`` cuts a copy of the body into chunks (``<unit>_Rubble``), skinned at weight 1 to Chunk_NN
bones under RubbleRoot on the body's own skin, drawn with the body's material, and held at 1e-4 scale outside the
death's live window. The owned-skinned lane builds exactly one body SkinnedMeshRenderer, and the runtime's uvAtlas
snap, Hex/Lit rebind and displacement overlay all take that one SMR, so a second SMR would need plugin changes.
Appending the rubble's vertices and triangles to the body primitive instead keeps one SMR with one material: the
Chunk bones are already in the body's bone list, and the rubble gets zero offsets for every corrective morph target.

merge (ship_def_retarget_slice.py prepare, selection row ``mergeMeshes``) refuses unless: the body is the one other
skinned mesh node; body and each merged mesh have exactly one triangle primitive with indices; the merged node is on
the body's skin, uses the body's material, carries the body's attribute set (same component types), no morph targets,
no node weights and no weight animation; the merged mesh is used by no other node. The body's sparse morph targets
keep their indices (rubble vertices come after the body's) and only grow their count; a dense target gets zero
offsets appended. Indices widen to uint32 when the merged vertex count needs it. The merged node keeps its place in
the node tree (no node index moves, so every animation channel stays valid) but loses its mesh and skin; its mesh is
removed from ``meshes``. The source's other bytes stay in the BIN chunk (orphaned views are valid glTF).
The output carries a stamp in asset.extras (``STAMP``) that ``verify`` re-proves from the file itself.

rows: the coordinator's migration of a slice row from ``deferMeshes`` to ``mergeMeshes`` for its ``*_Rubble`` node
(dry run unless --write). It changes no frozen pin; prepare, lab, bundles and probe must run again.

Proof tier: generated artifact. Unity import (one SMR, vertex count), the bundle (ProbeDefRetargetDeliveryBundles
rubble range checks) and the in-game death are separate tiers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
from glbpatch import Glb  # noqa: E402

STAMP = "homm3DefRetargetMeshMerge"
RUBBLE_SUFFIX = "_Rubble"
MERGE_REASON = ("the death shatter's rubble mesh (build_unit.py shatter) is merged into the body primitive at prepare "
                "(merge_rubble_glb.py): one SkinnedMeshRenderer, the Chunk bones already in its bone list, zero offsets "
                "for every corrective morph, so the death breaks into falling chunks in game instead of vanishing")
_COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class MergeError(Exception):
    pass


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def _dense(g: Glb, ai: int) -> np.ndarray:
    """A non-sparse accessor's elements, packed (count, ncomp)."""
    a = g.json["accessors"][ai]
    if "sparse" in a or "bufferView" not in a:
        raise MergeError(f"accessor {ai} is sparse or has no bufferView; a vertex attribute or index list must be dense")
    return _raw(g, ai)


def _raw(g: Glb, ai: int) -> np.ndarray:
    """The bufferView-backed elements of an accessor (before any sparse substitution), packed (count, ncomp)."""
    a = g.json["accessors"][ai]
    bv = g.json["bufferViews"][a["bufferView"]]
    dt, nc = np.dtype(_COMP[a["componentType"]]), _NCOMP[a["type"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride", 0) or dt.itemsize * nc
    width = dt.itemsize * nc
    end = start + stride * (a["count"] - 1) + width if a["count"] else start
    if end > len(g.bin):
        raise MergeError(f"accessor {ai} runs past the BIN chunk")
    # a copied slice, never a view: g.bin is a bytearray that later appends resize
    raw = np.frombuffer(bytes(g.bin[start:end]), np.uint8)
    rows = np.lib.stride_tricks.as_strided(raw, shape=(a["count"], width), strides=(stride, 1))
    return rows.copy().view(dt).reshape(a["count"], nc)


def read_accessor(g: Glb, ai: int) -> np.ndarray:
    """Any accessor's elements (count, ncomp), sparse substitution included."""
    a = g.json["accessors"][ai]
    nc = _NCOMP[a["type"]]
    dt = np.dtype(_COMP[a["componentType"]])
    if "bufferView" in a:
        out = _raw(g, ai)
    else:
        out = np.zeros((a["count"], nc), dt)
    sp = a.get("sparse")
    if sp:
        def view(part, d, n):
            bv = g.json["bufferViews"][part["bufferView"]]
            s = bv.get("byteOffset", 0) + part.get("byteOffset", 0)
            return np.frombuffer(bytes(g.bin[s:s + d.itemsize * n]), d)
        idx = view(sp["indices"], np.dtype(_COMP[sp["indices"]["componentType"]]), sp["count"]).astype(np.int64)
        out = out.copy()
        out[idx] = view(sp["values"], dt, sp["count"] * nc).reshape(sp["count"], nc)
    return out


def _append(g: Glb, arr: np.ndarray, like: dict, target: int | None, minmax: bool) -> int:
    """Append ``arr`` as a new tightly packed view + accessor shaped like ``like``; return the accessor index."""
    g.bin += b"\0" * (-len(g.bin) % 4)
    view = {"buffer": 0, "byteOffset": len(g.bin), "byteLength": int(arr.nbytes)}
    if target is not None:
        view["target"] = target
    g.bin += arr.tobytes()
    g.json["bufferViews"].append(view)
    acc = {"bufferView": len(g.json["bufferViews"]) - 1, "componentType": like["componentType"], "count": int(len(arr)),
           "type": like["type"]}
    if like.get("normalized"):
        acc["normalized"] = True
    if minmax:
        acc["min"] = [float(x) for x in arr.min(0)]
        acc["max"] = [float(x) for x in arr.max(0)]
    g.json["accessors"].append(acc)
    return len(g.json["accessors"]) - 1


def _one_prim(js: dict, mi: int, what: str) -> dict:
    prims = js["meshes"][mi]["primitives"]
    if len(prims) != 1 or prims[0].get("mode", 4) != 4 or "indices" not in prims[0]:
        raise MergeError(f"{what} mesh {mi} must have exactly one indexed triangle primitive")
    return prims[0]


def merge(src: Path, dst: Path, node_names: list[str]) -> dict:
    """Write ``dst`` = ``src`` with each named node's mesh appended to the body primitive; return the record."""
    if not node_names or len(set(node_names)) != len(node_names):
        raise MergeError(f"merge needs distinct node names, got {node_names}")
    if any(not n.endswith(RUBBLE_SUFFIX) for n in node_names):
        raise MergeError(f"only a death shatter's *{RUBBLE_SUFFIX} mesh merges into the body: {node_names}")
    g = Glb.load(src)
    js = g.json
    if len(js.get("buffers", [])) != 1 or "uri" in js["buffers"][0]:
        raise MergeError("expected one embedded GLB buffer")
    if STAMP in js.get("asset", {}).get("extras", {}):
        raise MergeError(f"{src.name} is already a merged GLB")
    nodes = js["nodes"]
    by_name = {}
    for i, n in enumerate(nodes):
        by_name.setdefault(n.get("name"), []).append(i)
    merged = []
    for name in node_names:
        idx = by_name.get(name, [])
        if len(idx) != 1 or "mesh" not in nodes[idx[0]] or "skin" not in nodes[idx[0]]:
            raise MergeError(f"{name}: not exactly one skinned mesh node in {src.name}")
        merged.append(idx[0])
    body = [i for i, n in enumerate(nodes) if "mesh" in n and "skin" in n and i not in merged]
    if len(body) != 1:
        raise MergeError(f"expected one body skinned mesh node besides {node_names}, found {[nodes[i].get('name') for i in body]}")
    bi = body[0]
    bmi = nodes[bi]["mesh"]
    bp = _one_prim(js, bmi, "body")
    attrs = sorted(bp["attributes"])
    for k in attrs:
        if k != "POSITION" and k != "NORMAL" and not k.startswith(("TEXCOORD_", "JOINTS_", "WEIGHTS_", "COLOR_", "TANGENT")):
            raise MergeError(f"body attribute {k} is not one this merge knows")
    channels = [(c["target"].get("node"), c["target"]["path"]) for a in js.get("animations", []) for c in a["channels"]]
    for ni in merged:
        n, mi = nodes[ni], nodes[ni]["mesh"]
        name = n.get("name")
        if mi == bmi or sum(1 for o in nodes if o.get("mesh") == mi) != 1:
            raise MergeError(f"{name}: its mesh is shared with another node")
        if n["skin"] != nodes[bi]["skin"]:
            raise MergeError(f"{name}: not on the body's skin")
        if "weights" in n or (ni, "weights") in channels:
            raise MergeError(f"{name}: carries morph weights")
        p = _one_prim(js, mi, name)
        if p.get("material") != bp.get("material"):
            raise MergeError(f"{name}: material {p.get('material')} is not the body's {bp.get('material')}")
        if p.get("targets"):
            raise MergeError(f"{name}: carries morph targets")
        if sorted(p["attributes"]) != attrs:
            raise MergeError(f"{name}: attributes {sorted(p['attributes'])} != the body's {attrs}")
        for k in attrs:
            a, b = js["accessors"][p["attributes"][k]], js["accessors"][bp["attributes"][k]]
            if (a["componentType"], a["type"], bool(a.get("normalized"))) != (b["componentType"], b["type"], bool(b.get("normalized"))):
                raise MergeError(f"{name}: {k} format differs from the body's")

    nb = js["accessors"][bp["attributes"]["POSITION"]]["count"]
    parts = []
    first = nb
    for ni in merged:
        p = js["meshes"][nodes[ni]["mesh"]]["primitives"][0]
        nv = js["accessors"][p["attributes"]["POSITION"]]["count"]
        parts.append({"node": nodes[ni].get("name"), "sourceMesh": nodes[ni]["mesh"], "firstVertex": first, "vertices": nv,
                      "triangles": js["accessors"][p["indices"]]["count"] // 3})
        first += nv
    total = first
    prims = [bp] + [js["meshes"][nodes[ni]["mesh"]]["primitives"][0] for ni in merged]
    new_attrs = {}
    for k in attrs:
        arr = np.concatenate([_dense(g, p["attributes"][k]) for p in prims])
        new_attrs[k] = _append(g, arr, js["accessors"][bp["attributes"][k]], 34962, k == "POSITION")
    idx = [_dense(g, bp["indices"]).reshape(-1).astype(np.int64)]
    for part, p in zip(parts, prims[1:]):
        idx.append(_dense(g, p["indices"]).reshape(-1).astype(np.int64) + part["firstVertex"])
    idx = np.concatenate(idx)
    if idx.min() < 0 or idx.max() >= total:
        raise MergeError("merged index out of range")
    ict = 5123 if total < 65535 else 5125
    new_idx = _append(g, idx.astype(_COMP[ict]).reshape(-1, 1), {"componentType": ict, "type": "SCALAR"}, 34963, False)
    new_targets = []
    for t in bp.get("targets", []):
        nt = {}
        for k, ai in t.items():
            a = dict(js["accessors"][ai])
            if a["count"] != nb:
                raise MergeError(f"morph target {k} accessor {ai} count {a['count']} != body vertices {nb}")
            if "bufferView" in a:
                if "sparse" in a:
                    raise MergeError(f"morph target accessor {ai} is sparse over a bufferView; not supported")
                base = _dense(g, ai)
                arr = np.concatenate([base, np.zeros((total - nb, base.shape[1]), base.dtype)])
                nt[k] = _append(g, arr, a, None, "min" in a or k == "POSITION")
                continue
            # sparse over zeros: rubble vertices sit after the body's, so the sparse indices hold; only count grows
            a["count"] = total
            if "min" in a and "max" in a:
                a["min"] = [min(float(x), 0.0) for x in a["min"]]
                a["max"] = [max(float(x), 0.0) for x in a["max"]]
            js["accessors"].append(a)
            nt[k] = len(js["accessors"]) - 1
        new_targets.append(nt)
    prim = {k: v for k, v in bp.items() if k not in ("attributes", "indices", "targets")}
    prim.update({"attributes": new_attrs, "indices": new_idx})
    if new_targets:
        prim["targets"] = new_targets
    js["meshes"][bmi]["primitives"] = [prim]
    for ni in merged:
        del nodes[ni]["mesh"]
        del nodes[ni]["skin"]
    gone = sorted(p["sourceMesh"] for p in parts)
    remap = {old: new for new, old in enumerate(mi for mi in range(len(js["meshes"])) if mi not in gone)}
    js["meshes"] = [m for mi, m in enumerate(js["meshes"]) if mi not in gone]
    for n in nodes:
        if "mesh" in n:
            n["mesh"] = remap[n["mesh"]]
    compact(g)
    record = {"sourceGlbSha256": sha(src), "bodyNode": nodes[bi].get("name"), "bodySourceMesh": bmi, "bodyMesh": remap[bmi],
              "bodyVertices": nb, "totalVertices": total, "indexComponentType": ict, "morphTargets": len(new_targets),
              "merged": parts}
    js.setdefault("asset", {}).setdefault("extras", {})[STAMP] = record
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(g.to_bytes())
    back = verify(dst)
    if back != record:
        raise MergeError("merged GLB stamp readback differs")
    check_equivalent(src, dst)
    return {**record, "glb": str(dst.resolve()), "sha256": sha(dst)}


def compact(g: Glb) -> None:
    """Drop the accessors and bufferViews nothing references any more (the replaced body primitive and the merged
    mesh) and rewrite the BIN chunk with only the kept views, each 4-byte aligned."""
    js = g.json
    if js.get("extensionsUsed"):
        raise MergeError(f"extensions {js['extensionsUsed']} may reference accessors; compaction refuses")
    used_acc = set()
    for m in js.get("meshes", []):
        for p in m["primitives"]:
            used_acc.update(p["attributes"].values())
            if "indices" in p:
                used_acc.add(p["indices"])
            for t in p.get("targets", []):
                used_acc.update(t.values())
    for s in js.get("skins", []):
        if "inverseBindMatrices" in s:
            used_acc.add(s["inverseBindMatrices"])
    for a in js.get("animations", []):
        for s in a["samplers"]:
            used_acc.update((s["input"], s["output"]))
    acc_map = {old: new for new, old in enumerate(sorted(used_acc))}
    accessors = [js["accessors"][i] for i in sorted(used_acc)]
    used_view = {im["bufferView"] for im in js.get("images", []) if "bufferView" in im}
    for a in accessors:
        if "bufferView" in a:
            used_view.add(a["bufferView"])
        sp = a.get("sparse")
        if sp:
            used_view.update((sp["indices"]["bufferView"], sp["values"]["bufferView"]))
    view_map = {old: new for new, old in enumerate(sorted(used_view))}
    out = bytearray()
    views = []
    for old in sorted(used_view):
        bv = dict(js["bufferViews"][old])
        s = bv.get("byteOffset", 0)
        out += b"\0" * (-len(out) % 4)
        chunk = g.bin[s:s + bv["byteLength"]]
        bv["byteOffset"] = len(out)
        out += chunk
        views.append(bv)
    for a in accessors:
        if "bufferView" in a:
            a["bufferView"] = view_map[a["bufferView"]]
        sp = a.get("sparse")
        if sp:
            sp["indices"]["bufferView"] = view_map[sp["indices"]["bufferView"]]
            sp["values"]["bufferView"] = view_map[sp["values"]["bufferView"]]
    for im in js.get("images", []):
        if "bufferView" in im:
            im["bufferView"] = view_map[im["bufferView"]]
    for m in js.get("meshes", []):
        for p in m["primitives"]:
            p["attributes"] = {k: acc_map[v] for k, v in p["attributes"].items()}
            if "indices" in p:
                p["indices"] = acc_map[p["indices"]]
            if "targets" in p:
                p["targets"] = [{k: acc_map[v] for k, v in t.items()} for t in p["targets"]]
    for s in js.get("skins", []):
        if "inverseBindMatrices" in s:
            s["inverseBindMatrices"] = acc_map[s["inverseBindMatrices"]]
    for a in js.get("animations", []):
        for s in a["samplers"]:
            s["input"], s["output"] = acc_map[s["input"]], acc_map[s["output"]]
    js["accessors"], js["bufferViews"] = accessors, views
    out += b"\0" * (-len(out) % 4)
    g.bin = out
    js["buffers"][0]["byteLength"] = len(out)


def check_equivalent(src: Path, dst: Path) -> None:
    """The merged GLB draws exactly what the source drew: body rows then each merged mesh's rows per attribute,
    their triangles (offset), body morph offsets then zeros, and identical skins, animations and images."""
    a, b = Glb.load(src), Glb.load(dst)
    st = b.json["asset"]["extras"][STAMP]
    ja, jb = a.json, b.json
    bp_a = ja["meshes"][st["bodySourceMesh"]]["primitives"][0]
    bp_b = jb["meshes"][st["bodyMesh"]]["primitives"][0]
    src_prims = [bp_a] + [ja["meshes"][m["sourceMesh"]]["primitives"][0] for m in st["merged"]]
    for k, ai in bp_b["attributes"].items():
        want = np.concatenate([read_accessor(a, p["attributes"][k]) for p in src_prims])
        if not np.array_equal(read_accessor(b, ai), want):
            raise MergeError(f"merged {k} differs from the source rows")
    want = [read_accessor(a, bp_a["indices"]).reshape(-1).astype(np.int64)]
    want += [read_accessor(a, p["indices"]).reshape(-1).astype(np.int64) + m["firstVertex"]
             for p, m in zip(src_prims[1:], st["merged"])]
    if not np.array_equal(read_accessor(b, bp_b["indices"]).reshape(-1).astype(np.int64), np.concatenate(want)):
        raise MergeError("merged indices differ from the source triangles")
    ta, tb = bp_a.get("targets", []), bp_b.get("targets", [])
    if len(ta) != len(tb):
        raise MergeError("morph target count changed")
    nb = st["bodyVertices"]
    for t0, t1 in zip(ta, tb):
        if sorted(t0) != sorted(t1):
            raise MergeError("morph target attributes changed")
        for k in t0:
            got = read_accessor(b, t1[k])
            if not np.array_equal(got[:nb], read_accessor(a, t0[k])) or np.any(got[nb:]):
                raise MergeError(f"merged morph target {k} is not the body's offsets then zeros")
    if len(ja.get("skins", [])) != len(jb.get("skins", [])) or len(ja.get("animations", [])) != len(jb.get("animations", [])):
        raise MergeError("skins or animations changed")
    for s0, s1 in zip(ja.get("skins", []), jb.get("skins", [])):
        if s0["joints"] != s1["joints"] or ("inverseBindMatrices" in s0) != ("inverseBindMatrices" in s1) or (
                "inverseBindMatrices" in s0 and not np.array_equal(read_accessor(a, s0["inverseBindMatrices"]),
                                                                   read_accessor(b, s1["inverseBindMatrices"]))):
            raise MergeError("skin changed")
    for an0, an1 in zip(ja.get("animations", []), jb.get("animations", [])):
        if an0.get("name") != an1.get("name") or an0["channels"] != an1["channels"] or len(an0["samplers"]) != len(an1["samplers"]):
            raise MergeError(f"animation {an0.get('name')} changed")
        for s0, s1 in zip(an0["samplers"], an1["samplers"]):
            if s0.get("interpolation") != s1.get("interpolation") or not np.array_equal(
                    read_accessor(a, s0["input"]), read_accessor(b, s1["input"])) or not np.array_equal(
                    read_accessor(a, s0["output"]), read_accessor(b, s1["output"])):
                raise MergeError(f"animation {an0.get('name')} sampler data changed")
    for i0, i1 in zip(ja.get("images", []), jb.get("images", [])):
        if "bufferView" in i0 and Glb.view_bytes(a, i0["bufferView"]) != Glb.view_bytes(b, i1["bufferView"]):
            raise MergeError("an embedded image changed")


def verify(path: Path) -> dict:
    """Re-prove a merged GLB from its own bytes: the stamp, one body skinned node, its primitive's vertex count, the
    merged nodes meshless and skinless. Returns the stamp."""
    g = Glb.load(path)
    js = g.json
    st = js.get("asset", {}).get("extras", {}).get(STAMP)
    if not st:
        raise MergeError(f"{Path(path).name}: no {STAMP} stamp")
    nodes = js["nodes"]
    skinned = [n for n in nodes if "mesh" in n and "skin" in n]
    if len(skinned) != 1 or skinned[0].get("name") != st["bodyNode"] or skinned[0]["mesh"] != st["bodyMesh"]:
        raise MergeError(f"{Path(path).name}: expected only the body {st['bodyNode']} as a skinned mesh node")
    p = _one_prim(js, st["bodyMesh"], "body")
    if js["accessors"][p["attributes"]["POSITION"]]["count"] != st["totalVertices"]:
        raise MergeError(f"{Path(path).name}: body vertex count is not the stamp's {st['totalVertices']}")
    if st["bodyVertices"] + sum(m["vertices"] for m in st["merged"]) != st["totalVertices"]:
        raise MergeError(f"{Path(path).name}: stamp vertex ranges do not add up")
    for t in p.get("targets", []):
        if any(js["accessors"][ai]["count"] != st["totalVertices"] for ai in t.values()):
            raise MergeError(f"{Path(path).name}: a morph target does not cover the merged vertices")
    names = {n.get("name"): n for n in nodes}
    for m in st["merged"]:
        n = names.get(m["node"])
        if n is None or "mesh" in n or "skin" in n:
            raise MergeError(f"{Path(path).name}: merged node {m['node']} is missing or still carries a mesh")
    return st


def migrate_rows(doc: dict, labs: list[str]) -> list[str]:
    """Move each named row's ``*_Rubble`` deferMeshes entry to mergeMeshes (MERGE_REASON); return what changed."""
    changed = []
    rows = {r.get("labSid"): r for r in doc.get("units", [])}
    for lab in labs:
        row = rows.get(lab)
        if row is None:
            raise MergeError(f"{lab}: no such row")
        dm = dict(row.get("deferMeshes") or {})
        rub = [n for n in dm if n.endswith(RUBBLE_SUFFIX)]
        if not rub:
            if any(n.endswith(RUBBLE_SUFFIX) for n in (row.get("mergeMeshes") or {})):
                continue
            raise MergeError(f"{lab}: no *{RUBBLE_SUFFIX} entry in deferMeshes to move")
        mm = dict(row.get("mergeMeshes") or {})
        for n in rub:
            dm.pop(n)
            mm[n] = MERGE_REASON
        new = {}
        for k, v in row.items():          # keep the row's key order; mergeMeshes takes deferMeshes' place
            if k == "deferMeshes":
                if dm:
                    new[k] = dm
                new["mergeMeshes"] = mm
            elif k != "mergeMeshes":
                new[k] = v
        row.clear()
        row.update(new)
        changed += [f"{lab}: {n}" for n in rub]
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("src", type=Path)
    m.add_argument("dst", type=Path)
    m.add_argument("nodes", nargs="+")
    v = sub.add_parser("verify")
    v.add_argument("glb", type=Path)
    r = sub.add_parser("rows")
    r.add_argument("selection", type=Path)
    r.add_argument("labs", nargs="+")
    r.add_argument("--write", action="store_true")
    a = ap.parse_args()
    try:
        if a.cmd == "merge":
            print(json.dumps(merge(a.src, a.dst, a.nodes), indent=1))
        elif a.cmd == "verify":
            print(json.dumps(verify(a.glb), indent=1))
        else:
            doc = json.loads(a.selection.read_text(encoding="utf-8"))
            changed = migrate_rows(doc, a.labs)
            print("\n".join(changed) or "nothing to move")
            if a.write and changed:
                a.selection.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
                print(f"wrote {a.selection}")
            elif changed:
                print("dry run; --write to apply")
    except MergeError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
