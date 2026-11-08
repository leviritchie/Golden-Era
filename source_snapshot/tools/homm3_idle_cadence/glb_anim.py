"""Minimal GLB reader/writer for animation timing work (numpy only, no Blender).

read_glb(path) -> (json_dict, bin_bytes); write_glb(path, json_dict, bin_bytes).
accessor(gltf, bin, i) -> numpy array (float accessors, no sparse).
sample_rotations(gltf, bin, anim_name, hz) -> ({node name: (T,4) xyzw}, length).
"""
from __future__ import annotations

import json
import struct

import numpy as np

COMP = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8, 5122: np.int16, 5120: np.int8}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path: str):
    with open(path, "rb") as f:
        return parse_glb(f.read(), path)


def parse_glb(data: bytes, path: str = "<bytes>"):
    magic, ver, total = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or ver != 2:
        raise ValueError(f"{path}: not a glTF 2 binary")
    pos, js, bn = 12, None, b""
    while pos < total:
        ln, typ = struct.unpack_from("<I4s", data, pos); pos += 8
        chunk = data[pos:pos + ln]; pos += ln
        if typ == b"JSON":
            js = json.loads(chunk.decode("utf-8"))
        elif typ == b"BIN\x00":
            bn = chunk
    return js, bn


def write_glb(path: str, js: dict, bn: bytes):
    jb = json.dumps(js, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    bn = bytes(bn) + b"\x00" * ((4 - len(bn) % 4) % 4)
    total = 12 + 8 + len(jb) + 8 + len(bn)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(jb), b"JSON")); f.write(jb)
        f.write(struct.pack("<I4s", len(bn), b"BIN\x00")); f.write(bn)


def raw_accessor(js: dict, bn: bytes, i: int) -> bytes:
    """The accessor's packed element bytes (tightly packed views only)."""
    a = js["accessors"][i]
    bv = js["bufferViews"][a["bufferView"]]
    size = np.dtype(COMP[a["componentType"]]).itemsize * NCOMP[a["type"]]
    if "sparse" in a or (bv.get("byteStride", 0) or size) != size:
        raise ValueError(f"accessor {i}: sparse or interleaved accessors are not supported")
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    return bytes(bn[off:off + a["count"] * size])


def accessor(js: dict, bn: bytes, i: int) -> np.ndarray:
    a = js["accessors"][i]
    if "sparse" in a:
        raise ValueError(f"accessor {i}: sparse accessors are not supported")
    bv = js["bufferViews"][a["bufferView"]]
    dt = np.dtype(COMP[a["componentType"]])
    n = NCOMP[a["type"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride", 0) or dt.itemsize * n
    if stride != dt.itemsize * n:
        raise ValueError(f"accessor {i}: interleaved buffer views are not supported")
    arr = np.frombuffer(bn, dtype=dt, count=a["count"] * n, offset=off).reshape(a["count"], n)
    if a.get("normalized"):
        arr = arr.astype(np.float64) / np.iinfo(dt).max
    return arr.astype(np.float64)


def animation(js: dict, name: str) -> dict:
    hits = [a for a in js.get("animations", []) if a.get("name") == name]
    if len(hits) != 1:
        raise KeyError(f"animation {name!r}: found {len(hits)}")
    return hits[0]


def _slerp(q0, q1, u):
    d = float(np.dot(q0, q1))
    if d < 0:
        q1, d = -q1, -d
    if d > 0.9995:
        q = q0 + u * (q1 - q0)
        return q / np.linalg.norm(q)
    th = np.arccos(d)
    return (np.sin((1 - u) * th) * q0 + np.sin(u * th) * q1) / np.sin(th)


def sample_quat(times: np.ndarray, vals: np.ndarray, t: np.ndarray, interp: str) -> np.ndarray:
    if interp == "CUBICSPLINE":
        vals = vals[1::3]
    out = np.empty((len(t), 4))
    for k, tt in enumerate(t):
        j = int(np.searchsorted(times, tt, side="right")) - 1
        if j < 0:
            out[k] = vals[0]
        elif j >= len(times) - 1:
            out[k] = vals[-1]
        elif interp == "STEP":
            out[k] = vals[j]
        else:
            u = (tt - times[j]) / max(times[j + 1] - times[j], 1e-9)
            out[k] = _slerp(vals[j], vals[j + 1], u)
    return out


def sample_rotations(js: dict, bn: bytes, anim_name: str, hz: float = 60.0):
    an = animation(js, anim_name)
    chans = [c for c in an["channels"] if c["target"].get("path") == "rotation"]
    t0 = min(accessor(js, bn, an["samplers"][c["sampler"]]["input"]).min() for c in an["channels"])
    t1 = max(accessor(js, bn, an["samplers"][c["sampler"]]["input"]).max() for c in an["channels"])
    length = float(t1 - t0)
    t = np.linspace(t0, t1, int(round(length * hz)) + 1)
    out = {}
    for c in chans:
        s = an["samplers"][c["sampler"]]
        times = accessor(js, bn, s["input"])[:, 0]
        vals = accessor(js, bn, s["output"])
        node = js["nodes"][c["target"]["node"]].get("name", str(c["target"]["node"]))
        out[node] = sample_quat(times, vals, t, s.get("interpolation", "LINEAR"))
    return out, length
