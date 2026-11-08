"""Explicit approved presentation derived from immutable current mocap exports."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import numpy as np

from .glb_skeleton import read_glb, load_bind_skeleton
from .oe_motion_style_v2 import MAX_GAIN, _animation, style_rotations

PROFILE = "approved-oe-v1"
# +120 user-requested Stronghold test: Move/Attack/Shoot world-space gain 2.20.
# Mouseover owns Skill states, not Idle_Rare. Both native idle states use Idle.
MOTION_GAIN = 2.20
POLICY = {
    "Move": ("move", 1.0), "AttackFront": ("attack", 1.0),
    "ShootFront": ("attack", 1.0), "Idle": ("preserve", 2.5),
    "Mouseover": ("preserve", 1.0), "Hitted": ("preserve", 1.0),
    "Defence": ("preserve", 1.0), "Death": ("preserve", 1.0),
    "MoveStart": ("preserve", 1.0), "MoveEnd": ("preserve", 1.0),
}
if not 1.0 <= MOTION_GAIN <= MAX_GAIN:
    raise ValueError(f"approved MOTION_GAIN {MOTION_GAIN} exceeds style cap {MAX_GAIN:g}")


def policy(name: str) -> dict:
    suffix = name.split("_", 1)[-1]
    if suffix not in POLICY:
        raise ValueError(f"unclassified approved style clip {name!r}")
    mode, duration = POLICY[suffix]
    return {"profile": PROFILE, "mode": mode,
            "gain": MOTION_GAIN if mode != "preserve" else 1.0,
            "durationMultiplier": duration, "timeOwner": "derived-glb-only"}


def styled_bytes(source: Path, name: str) -> bytes:
    """Replay the approved transform; all untouched buffer bytes remain identical."""
    rules = policy(name)
    if rules["mode"] == "preserve" and rules["durationMultiplier"] == 1.0:
        return source.read_bytes()
    parsed = read_glb(source)
    doc, blob = parsed["json"], bytearray(parsed["bin"])
    skeleton = load_bind_skeleton(source)
    animation, times, rotations, outputs = _animation(parsed, parsed["bin"], skeleton)

    def replace(index: int, values: np.ndarray, kind: str) -> None:
        accessor = doc["accessors"][index]
        view = doc["bufferViews"][accessor["bufferView"]]
        width = 16 if kind == "VEC4" else 4
        if (accessor["componentType"] != 5126 or accessor["type"] != kind
                or "sparse" in accessor or int(view.get("byteStride", width)) != width):
            raise ValueError("unsupported approved-style accessor layout")
        start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
        payload = np.asarray(values, dtype="<f4").tobytes()
        if len(payload) != int(accessor["count"]) * width:
            raise ValueError("approved-style accessor size mismatch")
        blob[start:start + len(payload)] = payload
        if kind == "SCALAR":
            accessor["min"], accessor["max"] = [float(values.min())], [float(values.max())]

    if rules["mode"] != "preserve":
        styled = style_rotations(rotations, skeleton.parents, times,
                                 mode=rules["mode"], gain=rules["gain"])
        # Preserve these bytes exactly, including the source quaternion signs.
        styled[[0, -1]] = rotations[[0, -1]]
        for joint, parent in enumerate(skeleton.parents):
            if parent < 0 or joint not in skeleton.parents:
                styled[:, joint] = rotations[:, joint]
        for _, joint, index in outputs:
            replace(index, styled[:, joint], "VEC4")
    if rules["durationMultiplier"] != 1.0:
        new_times = np.asarray(times * rules["durationMultiplier"], dtype="<f4")
        for index in {int(sampler["input"]) for sampler in animation["samplers"]}:
            replace(index, new_times, "SCALAR")
    encoded = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    blob += b"\0" * (-len(blob) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(blob))
            + struct.pack("<I4s", len(encoded), b"JSON") + encoded
            + struct.pack("<I4s", len(blob), b"BIN\0") + bytes(blob))


def derive(source: Path, destination: Path, name: str) -> dict:
    if source.resolve() == destination.resolve():
        raise ValueError("styled motion must not overwrite raw authority")
    payload = styled_bytes(source, name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != payload:
        raise ValueError(f"existing styled output differs: {destination}")
    destination.write_bytes(payload)
    return {**policy(name), "derivedSourceGlb": str(destination.resolve()),
            "derivedSourceGlbSha256": hashlib.sha256(payload).hexdigest()}


def validate_derived(raw: Path, name: str, record: dict) -> Path:
    if any(record.get(key) != value for key, value in policy(name).items()):
        raise ValueError("approved motion style policy drift")
    path = Path(record["derivedSourceGlb"])
    if not path.is_absolute() or path.resolve() == raw.resolve():
        raise ValueError("derived authority must be a separate absolute path")
    expected = hashlib.sha256(styled_bytes(raw, name)).hexdigest()
    if record.get("derivedSourceGlbSha256") != expected or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("derived motion does not match approved raw-to-style transform")
    return path
