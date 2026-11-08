"""GLB helpers for the unit-look delivery: hashes and an in-place base-colour image swap.

No Blender. The swap rewrites the BIN chunk so the old image bytes are gone (no un-prebaked
base colour survives inside the delivered file) and shifts every later bufferView by the size
change, keeping 4-byte alignment. Nothing else in the file changes.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def _pad4(n: int) -> int:
    return (n + 3) & ~3


class Glb:
    def __init__(self, data: bytes):
        magic, ver, total = struct.unpack("<III", data[:12])
        if magic != GLB_MAGIC or ver != 2:
            raise ValueError("not a glTF 2 binary")
        jl, jt = struct.unpack("<II", data[12:20])
        if jt != CHUNK_JSON:
            raise ValueError("first chunk is not JSON")
        self.json = json.loads(data[20:20 + jl])
        off = 20 + jl
        bl, bt = struct.unpack("<II", data[off:off + 8])
        if bt != CHUNK_BIN:
            raise ValueError("second chunk is not BIN")
        self.bin = bytearray(data[off + 8:off + 8 + bl])

    @classmethod
    def load(cls, p: Path) -> "Glb":
        return cls(Path(p).read_bytes())

    def to_bytes(self) -> bytes:
        js = json.dumps(self.json, separators=(",", ":")).encode("utf-8")
        js += b" " * (_pad4(len(js)) - len(js))
        bn = bytes(self.bin) + b"\0" * (_pad4(len(self.bin)) - len(self.bin))
        total = 12 + 8 + len(js) + 8 + len(bn)
        return (struct.pack("<III", GLB_MAGIC, 2, total) + struct.pack("<II", len(js), CHUNK_JSON) + js
                + struct.pack("<II", len(bn), CHUNK_BIN) + bn)

    # ------------------------------------------------------------------ reads
    def view_bytes(self, vi: int) -> bytes:
        bv = self.json["bufferViews"][vi]
        s = bv.get("byteOffset", 0)
        return bytes(self.bin[s:s + bv["byteLength"]])

    def accessor_bytes(self, ai: int) -> bytes:
        a = self.json["accessors"][ai]
        return self.view_bytes(a["bufferView"]) + json.dumps(
            {k: a.get(k) for k in ("byteOffset", "componentType", "count", "type")}).encode()

    def body_mesh_index(self) -> int:
        """The body mesh: the largest mesh (by vertices) not carried by a ``*_Rubble`` node. The death
        rubble is cut from the body and can have more vertices than it, so size alone picks the rubble."""
        def nverts(mi):
            return sum(self.json["accessors"][p["attributes"]["POSITION"]]["count"]
                       for p in self.json["meshes"][mi]["primitives"])
        rubble = {n["mesh"] for n in self.json.get("nodes", []) if "mesh" in n and n.get("name", "").endswith("_Rubble")}
        cand = [mi for mi in range(len(self.json["meshes"])) if mi not in rubble] or list(range(len(self.json["meshes"])))
        return max(cand, key=nverts)

    def base_color_image_indices(self) -> list[int]:
        """Every image used as a baseColorTexture by any material (normally one)."""
        out = []
        for m in self.json.get("materials", []):
            t = m.get("pbrMetallicRoughness", {}).get("baseColorTexture")
            if t is not None:
                src = self.json["textures"][t["index"]]["source"]
                if src not in out:
                    out.append(src)
        return out

    def body_base_color_image(self) -> int:
        mesh = self.json["meshes"][self.body_mesh_index()]
        mats = {p.get("material") for p in mesh["primitives"]} - {None}
        imgs = []
        for mi in sorted(mats):
            t = self.json["materials"][mi].get("pbrMetallicRoughness", {}).get("baseColorTexture")
            if t is not None:
                imgs.append(self.json["textures"][t["index"]]["source"])
        imgs = sorted(set(imgs))
        if len(imgs) != 1:
            raise ValueError(f"body mesh must use exactly one base-colour image, found {imgs}")
        return imgs[0]

    def image_bytes(self, ii: int) -> bytes:
        im = self.json["images"][ii]
        if "bufferView" not in im:
            raise ValueError("image is not embedded")
        return self.view_bytes(im["bufferView"])

    def geometry_sha256(self) -> str:
        """Body mesh rest geometry: POSITION, TEXCOORD_0 and indices of every primitive."""
        h = hashlib.sha256()
        for p in self.json["meshes"][self.body_mesh_index()]["primitives"]:
            for key in ("POSITION", "TEXCOORD_0"):
                if key not in p["attributes"]:
                    raise ValueError(f"body primitive has no {key}")
                h.update(self.accessor_bytes(p["attributes"][key]))
            if "indices" in p:
                h.update(self.accessor_bytes(p["indices"]))
        return h.hexdigest()

    def animation_names(self) -> list[str]:
        return [a.get("name", "") for a in self.json.get("animations", [])]

    def joint_names(self) -> set[str]:
        out = set()
        for sk in self.json.get("skins", []):
            for j in sk["joints"]:
                out.add(self.json["nodes"][j].get("name", ""))
        return out

    # ------------------------------------------------------------------ write
    def replace_image(self, ii: int, png: bytes) -> None:
        im = self.json["images"][ii]
        vi = im["bufferView"]
        views = self.json["bufferViews"]
        bv = views[vi]
        if bv.get("buffer", 0) != 0:
            raise ValueError("image bufferView is not in the GLB BIN buffer")
        s = bv.get("byteOffset", 0)
        old_end = s + _pad4(bv["byteLength"])
        for j, o in enumerate(views):
            if j != vi and o.get("byteOffset", 0) >= s and o.get("byteOffset", 0) < old_end:
                raise ValueError("another bufferView starts inside the image's padded range")
        new = png + b"\0" * (_pad4(len(png)) - len(png))
        delta = len(new) - (old_end - s)
        self.bin = self.bin[:s] + bytearray(new) + self.bin[old_end:]
        for j, o in enumerate(views):
            if j != vi and o.get("byteOffset", 0) >= old_end:
                o["byteOffset"] = o.get("byteOffset", 0) + delta
        bv["byteLength"] = len(png)
        im["mimeType"] = "image/png"
        self.json["buffers"][0]["byteLength"] = len(self.bin)
