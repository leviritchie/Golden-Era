"""Check triangle winding vs. exported normals in a GLB mesh.

A mesh with correct outward-facing normals should have:
  dot(cross(v1-v0, v2-v0), n_face) > 0   (right-hand rule with CCW front faces)

If most faces have NEGATIVE dot, the winding is flipped and any back-face-culling
shader (Hex/Lit _CullMode=2) will cull the whole mesh -> invisible in combat
(while the double-sided FallbackError shader still shows it pink).
"""

import json
import struct
import sys


def read_glb(path):
    with open(path, "rb") as f:
        data = f.read()
    assert data[:4] == b"glTF", "not a GLB"
    assert struct.unpack("<I", data[4:8])[0] == 2, "GLB version != 2"
    # First chunk starts at offset 12: (chunkLength uint32, chunkType uint32, data)
    off = 12
    json_data = None
    bin_data = b""
    while off + 8 <= len(data):
        (chunk_len, chunk_type) = struct.unpack("<II", data[off:off + 8])
        off += 8
        chunk = data[off:off + chunk_len]
        if chunk_type == 0x4E4F534A:  # JSON
            json_data = chunk
        elif chunk_type == 0x004E4942:  # BIN
            bin_data = chunk
        off += chunk_len + (chunk_len % 4 and (4 - chunk_len % 4) or 0)
    if json_data is None:
        raise AssertionError("no JSON chunk")
    return json.loads(json_data.decode("utf-8")), bin_data


def read_accessor(gltf, bin_data, accessor_index):
    acc = gltf["accessors"][accessor_index]
    bv = gltf["bufferViews"][acc["bufferView"]]
    comp_type = acc["componentType"]  # 5126 float, 5123 ushort, 5125 uint
    fmt = {5126: "f", 5123: "H", 5125: "I"}[comp_type]
    stride = bv.get("byteStride", 0)
    count = acc["count"]
    num_comp = { "SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4 }[acc["type"]]
    out = []
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    for i in range(count):
        off = base + i * (stride if stride else num_comp * struct.calcsize(fmt))
        vals = struct.unpack_from("<" + fmt * num_comp, bin_data, off)
        out.append(vals if num_comp > 1 else vals[0])
    return out


def main():
    if len(sys.argv) < 2:
        print("usage: check_glb_winding.py <file.glb> [max_faces]")
        return
    path = sys.argv[1]
    max_faces = int(sys.argv[2]) if len(sys.argv) > 2 else 200000
    gltf, bin_data = read_glb(path)

    for mi, mesh in enumerate(gltf.get("meshes", [])):
        for pi, prim in enumerate(mesh.get("primitives", [])):
            attrs = prim.get("attributes", {})
            if "POSITION" not in attrs or "NORMAL" not in attrs:
                continue
            pos = read_accessor(gltf, bin_data, attrs["POSITION"])
            nrm = read_accessor(gltf, bin_data, attrs["NORMAL"])
            if len(pos) != len(nrm):
                print(f"mesh {mi} prim {pi}: pos({len(pos)}) != nrm({len(nrm)})")
                continue
            mins = [min(p[k] for p in pos) for k in range(3)]
            maxs = [max(p[k] for p in pos) for k in range(3)]
            print(
                f"mesh {mi} prim {pi}: verts={len(pos)} posBounds x=[{mins[0]:.3f},{maxs[0]:.3f}] "
                f"y=[{mins[1]:.3f},{maxs[1]:.3f}] z=[{mins[2]:.3f},{maxs[2]:.3f}]"
            )
            idx = None
            if "indices" in prim:
                idx = read_accessor(gltf, bin_data, prim["indices"])
            else:
                idx = list(range(len(pos)))

            good = 0
            bad = 0
            zero = 0
            sample_bad = []
            n_faces = min(len(idx) // 3, max_faces)
            for t in range(n_faces):
                i0, i1, i2 = idx[3 * t], idx[3 * t + 1], idx[3 * t + 2]
                p0, p1, p2 = pos[i0], pos[i1], pos[i2]
                u = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
                v = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
                gx = u[1] * v[2] - u[2] * v[1]
                gy = u[2] * v[0] - u[0] * v[2]
                gz = u[0] * v[1] - u[1] * v[0]
                glen = (gx * gx + gy * gy + gz * gz) ** 0.5
                if glen < 1e-12:
                    zero += 1
                    continue
                nf = (gx / glen, gy / glen, gz / glen)
                n0 = nrm[i0]
                d = nf[0] * n0[0] + nf[1] * n0[1] + nf[2] * n0[2]
                if d >= 0:
                    good += 1
                else:
                    bad += 1
                    if len(sample_bad) < 5:
                        sample_bad.append((t, round(d, 3)))
            total = good + bad
            pct_bad = 100.0 * bad / total if total else 0.0
            print(
                f"mesh {mi} prim {pi}: faces={n_faces} good={good} bad={bad} zero={zero} "
                f"bad%={pct_bad:.1f}"
            )
            if sample_bad:
                print("  sample bad:", sample_bad)
            if total and pct_bad > 50:
                print(f"  -> WINDING FLIPPED (hex/Lit _CullMode=2 would cull the whole mesh)")


if __name__ == "__main__":
    main()
