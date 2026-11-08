"""Minimal read-only GLB reader (numpy): JSON, accessors, embedded images. No Blender needed."""
from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import numpy as np

_COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class Glb:
    def __init__(self, path: str | Path):
        b = Path(path).read_bytes()
        n = struct.unpack("<I", b[12:16])[0]
        self.json = json.loads(b[20:20 + n])
        off = 20 + n
        bl = struct.unpack("<I", b[off:off + 4])[0]
        self.bin = b[off + 8:off + 8 + bl]

    def accessor(self, i: int) -> np.ndarray:
        a = self.json["accessors"][i]
        bv = self.json["bufferViews"][a["bufferView"]]
        dt = np.dtype(_COMP[a["componentType"]])
        nc = _NCOMP[a["type"]]
        start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride", 0) or dt.itemsize * nc
        count = a["count"]
        if stride == dt.itemsize * nc:
            arr = np.frombuffer(self.bin, dt, count * nc, start).reshape(count, nc)
        else:
            raw = np.frombuffer(self.bin, np.uint8, stride * (count - 1) + dt.itemsize * nc, start)
            arr = np.stack([np.frombuffer(raw[k * stride:k * stride + dt.itemsize * nc].tobytes(), dt) for k in range(count)])
        return arr.squeeze(-1) if nc == 1 else arr

    def image_bytes(self, i: int) -> bytes:
        im = self.json["images"][i]
        bv = self.json["bufferViews"][im["bufferView"]]
        s = bv.get("byteOffset", 0)
        return self.bin[s:s + bv["byteLength"]]

    def image(self, i: int):
        from PIL import Image
        return Image.open(io.BytesIO(self.image_bytes(i)))

    def base_color_image_index(self, material: int = 0) -> int:
        tex = self.json["materials"][material]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
        return self.json["textures"][tex]["source"]
