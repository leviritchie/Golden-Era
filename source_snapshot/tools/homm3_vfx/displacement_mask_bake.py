#!/usr/bin/env python3
"""Bake a Hex/Lit FLAG vertex-displacement mask into a delivered GLB's COLOR_0 (red channel), with a stamp.

Hex/Lit's FLAG variant moves every vertex by ``_FlagPower * sin(dot(posWS, _FlagDirection) + t * _FlagSpeed) * COLOR.r``
and reads nothing else from the vertex colour (the static read of all 2064 FLAG vertex programs declares COLOR with
component x only, and no pixel program sees it). HoMM3 delivered GLBs carry no COLOR_0, so without this bake the
runtime lane (Homm3MeshFx battle_body_displacement) refuses the unit rather than wave the whole body.

Rules (one per bake; the value lands in COLOR_0.r, G = B = A = 1):
  boneWeights  {"rule": "boneWeights", "bones": [...], "lo": 0.2, "hi": 0.8}
               smoothstep(lo, hi, summed skin weight of the listed joints) - e.g. wings, a tail, a cloak.
  heightBand   {"rule": "heightBand", "lo": 0.6, "hi": 1.0}
               smoothstep over bind-pose height normalised to the mesh's own Y extent (0 = lowest vertex, 1 = highest);
               lo > hi inverts the ramp (strong at the feet).
  region       {"rule": "region", "center": [u, v, w], "radius": 0.2, "falloff": 0.1}
               1 within ``radius`` of a point given in the mesh's normalised bind bounding box, fading to 0 over
               ``falloff`` (distances in units of the box's largest side).
Every rule also takes ``"gain"`` (default 1, clamps the mask to [0, gain]).

The output GLB is the input with one added COLOR_0 accessor per primitive (UNSIGNED_BYTE normalised VEC4); every other
byte of JSON and binary chunk is preserved. A primitive that already carries COLOR_0 is refused. The stamp
(``<out>.stamp.json``, schema homm3_displacement_mask_bake.v1) pins the input and output sha256, the rule, the tool's
own sha256 and per-primitive coverage, so a ship step can prove which mask it delivers.

Proof tier: generated artifact. Whether the owned-skinned import keeps COLOR_0 into Mesh.colors (glTFast does) and
how the wave looks in game are separate proofs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_io import Glb  # noqa: E402

STAMP_SCHEMA = "homm3_displacement_mask_bake.v1"
RULES = ("boneWeights", "heightBand", "region")
GLB_MAGIC, CHUNK_JSON, CHUNK_BIN = 0x46546C67, 0x4E4F534A, 0x004E4942


class BakeError(Exception):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def smoothstep(a: float, b: float, x):
    if a == b:
        raise BakeError(f"smoothstep lo == hi ({a})")
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def check_rule(rule: dict) -> None:
    if not isinstance(rule, dict):
        raise BakeError("mask rule must be an object")
    kind = rule.get("rule")
    if kind not in RULES:
        raise BakeError(f"rule {kind!r} not in {RULES}")
    allowed = {
        "boneWeights": {"rule", "gain", "bones", "lo", "hi"},
        "heightBand": {"rule", "gain", "lo", "hi"},
        "region": {"rule", "gain", "center", "radius", "falloff"},
    }[kind]
    extra = set(rule) - allowed
    if extra:
        raise BakeError(f"unknown {kind} rule keys {sorted(extra)}")
    def num(v):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return False
        try:
            return math.isfinite(v)
        except OverflowError:
            return False
    gain = rule.get("gain", 1.0)
    if not num(gain) or not 0 < gain <= 1:
        raise BakeError("gain must be in (0, 1]")
    if kind == "boneWeights":
        bones = rule.get("bones")
        if not isinstance(bones, list) or not bones or not all(isinstance(b, str) and b for b in bones):
            raise BakeError("boneWeights needs a non-empty bones list")
        if not (num(rule.get("lo")) and num(rule.get("hi")) and 0 <= rule["lo"] < rule["hi"] <= 1):
            raise BakeError("boneWeights needs 0 <= lo < hi <= 1")
    elif kind == "heightBand":
        if not (num(rule.get("lo")) and num(rule.get("hi")) and rule["lo"] != rule["hi"]):
            raise BakeError("heightBand needs numeric lo != hi")
    else:
        c = rule.get("center")
        if not (isinstance(c, list) and len(c) == 3 and all(num(v) for v in c)):
            raise BakeError("region needs center [u, v, w] in the normalised bind box")
        if not (num(rule.get("radius")) and rule["radius"] >= 0 and num(rule.get("falloff")) and rule["falloff"] > 0):
            raise BakeError("region needs radius >= 0 and falloff > 0")


def weights(g: Glb, at: dict, which: str) -> np.ndarray:
    acc = g.json["accessors"][at[which]]
    w = g.accessor(at[which]).astype(np.float64)
    if which.startswith("WEIGHTS") and acc["componentType"] != 5126:
        w /= 255.0 if acc["componentType"] == 5121 else 65535.0
    return w


def mask_for(g: Glb, prim: dict, rule: dict, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    at = prim["attributes"]
    pos = g.accessor(at["POSITION"]).astype(np.float64)
    kind = rule["rule"]
    if kind == "boneWeights":
        skin = g.json["skins"][0]
        names = [g.json["nodes"][j]["name"] for j in skin["joints"]]
        missing = [b for b in rule["bones"] if b not in names]
        if missing:
            raise BakeError(f"bones {missing} are not joints of the skin")
        idx = [names.index(b) for b in rule["bones"]]
        if "JOINTS_0" not in at:
            raise BakeError("boneWeights needs a skinned primitive (JOINTS_0/WEIGHTS_0)")
        total = np.zeros(len(pos))
        for k in (0, 1):
            if f"JOINTS_{k}" not in at:
                continue
            j = g.accessor(at[f"JOINTS_{k}"]).astype(np.int64)
            w = weights(g, at, f"WEIGHTS_{k}")
            total += np.where(np.isin(j, idx), w, 0.0).sum(1)
        m = smoothstep(rule["lo"], rule["hi"], total)
    elif kind == "heightBand":
        h = (pos[:, 1] - lo[1]) / max(hi[1] - lo[1], 1e-9)
        m = smoothstep(rule["lo"], rule["hi"], h)
    else:
        side = float(max(hi - lo))
        centre = lo + np.array(rule["center"], dtype=np.float64) * (hi - lo)
        d = np.linalg.norm(pos - centre, axis=1) / max(side, 1e-9)
        m = 1.0 - smoothstep(rule["radius"], rule["radius"] + rule["falloff"], d)
    return np.clip(m, 0.0, 1.0) * float(rule.get("gain", 1.0))


def write_glb(path: Path, gltf: dict, binary: bytes) -> None:
    js = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    js += b" " * (-len(js) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(struct.pack("<III", GLB_MAGIC, 2, total))
        f.write(struct.pack("<II", len(js), CHUNK_JSON) + js)
        f.write(struct.pack("<II", len(binary), CHUNK_BIN) + binary)


def bake(src: Path, out: Path, rule: dict) -> dict:
    check_rule(rule)
    g = Glb(src)
    gltf = json.loads(json.dumps(g.json))
    if len(gltf.get("buffers", [])) != 1 or "uri" in gltf["buffers"][0]:
        raise BakeError("expected one embedded GLB buffer")
    binary = bytearray(g.bin)
    all_pos = [g.accessor(p["attributes"]["POSITION"]).astype(np.float64)
               for m in gltf["meshes"] for p in m["primitives"]]
    stacked = np.concatenate(all_pos)
    lo, hi = stacked.min(0), stacked.max(0)
    prims = []
    for mi, mesh in enumerate(gltf["meshes"]):
        for pi, prim in enumerate(mesh["primitives"]):
            if "COLOR_0" in prim["attributes"]:
                raise BakeError(f"mesh {mi} primitive {pi} already has COLOR_0; refusing to overwrite it")
            m = mask_for(g, prim, rule, lo, hi)
            rgba = np.ones((len(m), 4), np.uint8) * 255
            rgba[:, 0] = np.round(m * 255).astype(np.uint8)
            binary += b"\0" * (-len(binary) % 4)
            view = {"buffer": 0, "byteOffset": len(binary), "byteLength": rgba.nbytes}
            binary += rgba.tobytes()
            gltf["bufferViews"].append(view)
            gltf["accessors"].append({"bufferView": len(gltf["bufferViews"]) - 1, "componentType": 5121,
                                      "normalized": True, "count": int(len(m)), "type": "VEC4"})
            prim["attributes"]["COLOR_0"] = len(gltf["accessors"]) - 1
            prims.append({"mesh": mi, "primitive": pi, "vertices": int(len(m)),
                          "maskMean": round(float(m.mean()), 5), "maskMax": round(float(m.max()), 5),
                          "fractionAboveHalf": round(float((m > 0.5).mean()), 5)})
    if not any(p["maskMax"] > 0 for p in prims):
        raise BakeError("the rule masks no vertex (all zero); nothing would move")
    binary += b"\0" * (-len(binary) % 4)
    gltf["buffers"][0]["byteLength"] = len(binary)
    write_glb(out, gltf, bytes(binary))
    back = Glb(out)
    for p in prims:
        prim = back.json["meshes"][p["mesh"]]["primitives"][p["primitive"]]
        col = back.accessor(prim["attributes"]["COLOR_0"])
        if col.shape != (p["vertices"], 4):
            raise BakeError("COLOR_0 readback shape mismatch")
    stamp = {"schema": STAMP_SCHEMA, "sourceGlb": src.as_posix(), "sourceGlbSha256": sha256(src),
             "outGlb": out.as_posix(), "outGlbSha256": sha256(out), "rule": rule,
             "toolSha256": sha256(Path(__file__)), "channel": "COLOR_0.r (G=B=A=1)", "primitives": prims,
             "proof": "generated artifact; import into Mesh.colors and in-game wave unproven"}
    Path(str(out) + ".stamp.json").write_text(json.dumps(stamp, indent=1) + "\n", encoding="utf-8", newline="\n")
    return stamp


def verify(out: Path) -> dict:
    """Re-prove a bake from its stamp: output sha, source sha, and the tool that made it."""
    stamp_path = Path(str(out) + ".stamp.json")
    if not stamp_path.is_file():
        raise BakeError(f"{out.name}: no stamp")
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    if stamp.get("schema") != STAMP_SCHEMA:
        raise BakeError(f"{stamp_path.name}: schema {stamp.get('schema')!r}")
    if sha256(out) != stamp["outGlbSha256"]:
        raise BakeError(f"{out.name}: sha differs from its stamp")
    src = Path(stamp["sourceGlb"])
    if not src.is_file() or sha256(src) != stamp["sourceGlbSha256"]:
        raise BakeError(f"{out.name}: source {src} missing or changed since the bake")
    return stamp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--glb", type=Path, required=True, help="source GLB (delivered idle-retimed master)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--rule", required=True, help="rule JSON, e.g. '{\"rule\":\"heightBand\",\"lo\":0.6,\"hi\":1}'")
    args = ap.parse_args()
    try:
        stamp = bake(args.glb, args.out, json.loads(args.rule))
    except BakeError as ex:
        print(f"displacement-mask-bake: {ex}", file=sys.stderr)
        return 1
    print(json.dumps({k: stamp[k] for k in ("outGlb", "outGlbSha256", "primitives")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
