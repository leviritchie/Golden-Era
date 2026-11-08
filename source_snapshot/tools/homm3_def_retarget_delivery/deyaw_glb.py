"""Take the DEF-fit body turn (castle_yaw / necropolis_yaw) back out of a canonical DEF-retarget GLB for delivery.

    python tools/homm3_def_retarget_delivery/deyaw_glb.py <unit> [<unit> ...]

castle_yaw / necropolis_yaw (tools/homm3_def_retarget/ext) turn every posed bone except Root about Blender +Z by
the unit config's `yawDeg` in every frame, so a horse drawn in profile by the DEF is fitted under the shared
sprite camera. The fit (renders, castle_refine / propaim, emphasis stretch) needs that turn; the game does not:
the facing contract wants Unit_Idle frame 0 facing glTF +Z (tools/validate_homm3_owned_skinned_facing_contract.py)
and a turned body walks crabwise along its heading. The turn is rigid about the origin and every turned bone
descends from Hips (castle_mount / necropolis_horse re-parent the horse chains), so undoing it is one
counter-rotation of the Hips keys: Blender +Z is glTF +Y, so every Hips translation / rotation key in every
animation is premultiplied by Ry(-yawDeg). Rest mesh, bind pose, morphs and the other bones' local keys are
untouched.

Runs on artifacts/homm3_def_retarget/<u>/<u>_def_retarget.glb in place, after the emphasis deliver and before
look.py (fleet_rebuild.py sequences it), and stamps asset.extras.homm3DefRetargetDeliveryDeyaw
{yawDeg, sourceGlbSha256}. Refuses: a unit without a yaw extension, a GLB already de-yawed, Hips parents that are
not identity (the conjugation would be needed), a key accessor shared with a non-Hips target, strided or sparse, and a result whose
Unit_Idle frame 0 is not within the facing contract's tolerance.
Proof tier: generated artifact.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from validate_homm3_owned_skinned_facing_contract import GLB_FORWARD_TOL, glb_idle0_forward  # noqa: E402
sys.path.insert(0, str(HERE))
import stage_sidecar  # noqa: E402

YAW_EXTENSIONS = ("castle_yaw", "necropolis_yaw")
STAMP = "homm3DefRetargetDeliveryDeyaw"


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def canonical_glb(u: str) -> Path:
    return ROOT / "artifacts/homm3_def_retarget" / u / f"{u}_def_retarget.glb"


def deyaw_bytes(u: str, data: bytes, glb: Path):
    """The de-yaw stage on GLB bytes, in memory: a stage_sidecar.StageResult whose sidecar names `glb` (the GLB it
    replaces in place). Refuses (SystemExit) a unit without a yaw extension and every case in the module doc."""
    cfg = json.loads((ROOT / "tools/homm3_def_retarget/units" / f"{u}.json").read_text(encoding="utf-8"))
    yaw = cfg.get("yawDeg")
    if not yaw or not set(YAW_EXTENSIONS) & set(cfg.get("extensions", [])):
        raise SystemExit(f"{u}: no castle_yaw/necropolis_yaw body turn in the unit config")
    b = bytearray(data)
    src_sha = hashlib.sha256(b).hexdigest()
    jl = struct.unpack_from("<I", b, 12)[0]
    js = json.loads(b[20:20 + jl])
    if STAMP in js.get("asset", {}).get("extras", {}):
        raise SystemExit(f"{u}: already de-yawed ({js['asset']['extras'][STAMP]})")
    bin0 = 20 + jl + 8
    nodes = js["nodes"]
    names = [n.get("name") for n in nodes]
    hips = names.index("Hips")
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    p = parent.get(hips)
    while p is not None:
        n = nodes[p]
        if any(abs(v) > 1e-6 for v in n.get("translation", [0, 0, 0])) or n.get("rotation", [0, 0, 0, 1]) != [0, 0, 0, 1] \
                or n.get("scale", [1, 1, 1]) != [1, 1, 1] or "matrix" in n:
            raise SystemExit(f"{u}: Hips parent {n.get('name')} is not identity at rest")
        p = parent.get(p)
    parents = set()
    p = parent.get(hips)
    while p is not None:
        parents.add(p)
        p = parent.get(p)
    h = math.radians(-yaw) / 2
    qy = (0.0, math.sin(h), 0.0, math.cos(h))
    c, s = math.cos(math.radians(-yaw)), math.sin(math.radians(-yaw))
    # the exporter shares identical key arrays between clips: an accessor is transformed once, and only when
    # every channel reading it is a Hips channel of the same path
    users: dict[int, set] = {}
    for a in js.get("animations", []):
        for ch in a["channels"]:
            acc = a["samplers"][ch["sampler"]]["output"]
            users.setdefault(acc, set()).add((ch["target"]["node"], ch["target"]["path"]))
    done: set[int] = set()
    touched = 0
    for a in js.get("animations", []):
        for ch in a["channels"]:
            node, path = ch["target"]["node"], ch["target"]["path"]
            acc_i = a["samplers"][ch["sampler"]]["output"]
            acc = js["accessors"][acc_i]
            bv = js["bufferViews"][acc["bufferView"]]
            off = bin0 + bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            w = {"VEC3": 3, "VEC4": 4}.get(acc["type"])
            if node in parents and path in ("translation", "rotation", "scale"):
                ident = {"translation": (0, 0, 0), "rotation": (0, 0, 0, 1), "scale": (1, 1, 1)}[path]
                for k in range(acc["count"]):
                    v = struct.unpack_from("<" + "f" * w, b, off + 4 * w * k)
                    if any(abs(x - y) > 1e-5 for x, y in zip(v, ident)):
                        raise SystemExit(f"{u}: Hips parent {names[node]} animates {path} off identity in {a['name']}")
                continue
            if node != hips or path not in ("translation", "rotation"):
                continue
            if acc_i in done:
                touched += 1
                continue
            if users[acc_i] != {(hips, path)} or "sparse" in acc or bv.get("byteStride", 4 * w) != 4 * w or acc.get("componentType") != 5126:
                raise SystemExit(f"{u}: {a['name']} Hips {path} accessor is shared with another target, sparse, strided or not float")
            done.add(acc_i)
            for k in range(acc["count"]):
                o = off + 4 * w * k
                v = struct.unpack_from("<" + "f" * w, b, o)
                if path == "translation":
                    x, y, z = v
                    struct.pack_into("<3f", b, o, c * x + s * z, y, -s * x + c * z)
                else:
                    q = qmul(qy, v)
                    n = math.sqrt(sum(t * t for t in q))
                    struct.pack_into("<4f", b, o, *(t / n for t in q))
            touched += 1
    if not touched:
        raise SystemExit(f"{u}: no Hips keys found")
    js.setdefault("asset", {}).setdefault("extras", {})[STAMP] = {
        "yawDeg": yaw, "sourceGlbSha256": src_sha, "tool": "tools/homm3_def_retarget_delivery/deyaw_glb.py",
        "note": "Hips keys premultiplied by Ry(-yawDeg): the DEF-fit body turn is taken out for delivery"}
    new_js = json.dumps(js, separators=(",", ":")).encode("utf-8")
    new_js += b" " * ((4 - len(new_js) % 4) % 4)
    rest = bytes(b[20 + jl:])
    out = bytearray(b[:12]) + struct.pack("<II", len(new_js), 0x4E4F534A) + new_js + rest
    struct.pack_into("<I", out, 8, len(out))
    out = bytes(out)
    f = glb_idle0_forward(out)
    ang = None if f is None else math.degrees(math.atan2(f[0], f[2]))
    if ang is None or abs(ang) > GLB_FORWARD_TOL:
        raise SystemExit(f"{u}: de-yawed Unit_Idle frame 0 still faces glTF yaw {ang}")
    out_sha = hashlib.sha256(out).hexdigest()
    return stage_sidecar.result(
        out, data, "deyaw", stage_sidecar.record("homm3_def_retarget_delivery_deyaw.v1", u, glb, src_sha, out_sha),
        {"unit": u, "yawDeg": yaw, "hipsChannels": touched, "idle0Yaw": round(ang, 1), "sourceGlbSha256": src_sha,
         "glbSha256": out_sha})


def deyaw(u: str) -> dict:
    """The CLI: de-yaw the canonical GLB in place and write its sidecar."""
    glb = canonical_glb(u)
    r = deyaw_bytes(u, glb.read_bytes(), glb)
    stage_sidecar.commit(glb, r)
    return r.report


def main() -> int:
    for u in sys.argv[1:]:
        print(json.dumps(deyaw(u)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
