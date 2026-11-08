"""Byte-preserving world-space motion-style pilot (preview only)."""
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_skeleton import _accessor, read_glb, load_bind_skeleton

SCHEMA = "homm3_oe_motion_style_pilot_v2"

def _n(q): return q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)
def _conj(q):
    out = np.asarray(q, float).copy(); out[..., :3] *= -1; return out
def _mul(a, b):
    ax, ay, az, aw = np.moveaxis(a, -1, 0); bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack((aw*bx+ax*bw+ay*bz-az*by, aw*by-ax*bz+ay*bw+az*bx,
                     aw*bz+ax*by-ay*bx+az*bw, aw*bw-ax*bx-ay*by-az*bz), -1)
def _slerp_identity(q, amount):
    q = _n(q); q *= np.where(q[..., 3:4] < 0, -1., 1.)
    theta = np.arccos(np.clip(q[..., 3:4], -1., 1.)); s = np.sin(theta)
    linear = np.zeros_like(q); linear[..., 3] = 1.; linear += amount * (q-linear)
    spherical = (np.sin((1-amount)*theta)/np.maximum(np.abs(s), 1e-8))*np.eye(4)[3] + (np.sin(amount*theta)/np.maximum(np.abs(s), 1e-8))*q
    return _n(np.where(np.abs(s) < 1e-6, linear, spherical))

def _world(local, parents):
    out = np.zeros_like(local)
    for joint, parent in enumerate(parents): out[:, joint] = local[:, joint] if parent < 0 else _mul(out[:, parent], local[:, joint])
    return _n(out)

MAX_GAIN = 2.2


def style_rotations(rotations, parents, times, *, mode="attack", gain=1.45):
    if mode not in {"attack", "move"}: raise ValueError("mode must be attack or move")
    if not np.isfinite(gain) or not 1.0 <= gain <= MAX_GAIN:
        raise ValueError(f"gain must be in [1,{MAX_GAIN:g}]")
    raw = np.asarray(rotations, float)
    if raw.ndim != 3 or not np.isfinite(raw).all() or np.any(np.linalg.norm(raw, axis=-1) < 1e-8): raise ValueError("rotation quaternions must be finite and nonzero")
    local = _n(raw); worlds = _world(local, parents)
    roots = [i for i, p in enumerate(parents) if p < 0]
    leaves = {i for i in range(len(parents)) if i not in parents}
    ref = worlds[0].copy()
    if mode == "move":
        signs = np.where(np.sum(worlds * worlds[0:1], axis=-1, keepdims=True) < 0, -1., 1.)
        ref = _n(np.sum(worlds * signs, axis=0))
    delta = _mul(np.broadcast_to(_conj(ref), worlds.shape), worlds)
    phase = (times-times[0]) / max(float(times[-1]-times[0]), 1e-12)
    envelope = np.sin(np.pi*np.clip(phase, 0, 1)) if mode == "attack" else np.ones(len(times))
    if mode == "move" and len(envelope) > 1:
        envelope[[0, -1]] = 0.
        if len(envelope) > 2: envelope[1] = min(envelope[1], .5); envelope[-2] = min(envelope[-2], .5)
    # Slerp amount 1 is the original delta; gain=1 must be identity.
    amount = 1. + (gain-1.) * envelope[:, None, None]
    styled_world = _mul(np.broadcast_to(ref, worlds.shape), _slerp_identity(delta, amount))
    styled_world[:, roots] = worlds[:, roots]
    styled_world[:, list(leaves)] = worlds[:, list(leaves)]
    styled = np.zeros_like(local)
    for joint, parent in enumerate(parents): styled[:, joint] = styled_world[:, joint] if parent < 0 else _mul(_conj(styled_world[:, parent]), styled_world[:, joint])
    styled = _n(styled); styled[:, roots] = local[:, roots]; styled[:, list(leaves)] = local[:, list(leaves)]
    return styled.astype(np.float32)

def _animation(doc, blob, skeleton):
    animations = doc["json"].get("animations") or []
    if len(animations) != 1: raise ValueError("expected exactly one animation")
    animation, node_to_joint = animations[0], {int(node): i for i, node in enumerate(skeleton.node_indices)}
    samplers = animation.get("samplers") or []; channels = animation.get("channels") or []
    times = None; rotations = None; outputs = []; rotation_seen = set()
    for channel in channels:
        target = channel.get("target") or {}; joint = node_to_joint.get(int(target.get("node", -1)))
        if joint is None or target.get("path") not in {"rotation", "translation"}: raise ValueError("unsupported animation channel")
        sampler = samplers[int(channel["sampler"])]
        if sampler.get("interpolation", "LINEAR") != "LINEAR": raise ValueError("unsupported animation interpolation")
        inputs = _accessor(doc, blob, int(sampler["input"])).astype(float).reshape(-1)
        if not np.isfinite(inputs).all() or len(inputs) == 0 or (len(inputs) > 1 and np.any(np.diff(inputs) <= 0)): raise ValueError("animation key times are not finite/increasing")
        if times is None: times = inputs
        elif not np.array_equal(times, inputs): raise ValueError("channel key times differ")
        values = _accessor(doc, blob, int(sampler["output"]))
        if target["path"] == "rotation":
            if values.dtype != np.float32 or values.size != len(times) * 4: raise ValueError("rotation accessor is not float VEC4")
            if rotations is None: rotations = np.zeros((len(times), len(skeleton.names), 4)); rotations[..., 3] = 1
            values = values.reshape(len(times), 4)
            if not np.isfinite(values).all(): raise ValueError("rotation accessor is non-finite")
            rotations[:, joint] = values; outputs.append((channel, joint, sampler["output"])); rotation_seen.add(joint)
        elif not np.isfinite(values).all() or values.size != len(times) * 3:
            raise ValueError("translation accessor is invalid")
    if times is None or rotations is None or len(rotation_seen) != len(skeleton.names) or len(outputs) != len(skeleton.names): raise ValueError("every joint must have exactly one rotation channel")
    return animation, times, rotations, outputs

def _patch_glb(source, destination, *, mode, gain):
    raw = bytearray(source.read_bytes()); parsed = read_glb(source); skeleton = load_bind_skeleton(source)
    animation, times, rotations, outputs = _animation(parsed, parsed["bin"], skeleton)
    styled = style_rotations(rotations, skeleton.parents, times, mode=mode, gain=gain)
    json_len = struct.unpack_from("<I", raw, 12)[0]; cursor = 20 + json_len; bin_start = cursor + 8
    for channel, joint, accessor_index in outputs:
        accessor = parsed["json"]["accessors"][accessor_index]; view = parsed["json"]["bufferViews"][accessor["bufferView"]]
        if accessor.get("componentType") != 5126 or accessor.get("type") != "VEC4" or "sparse" in accessor: raise ValueError("unsupported rotation accessor")
        start = bin_start + int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0)); values = np.asarray(styled[:, joint], dtype="<f4").tobytes()
        stride = int(view.get("byteStride", 16));
        if stride == 16: raw[start:start+len(values)] = values
        else: raise ValueError("strided rotation accessor unsupported")
    destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(raw)
    candidate = load_bind_skeleton(destination)
    for name in ("vertices", "triangles", "uvs", "vertex_joints", "vertex_weights", "inverse_bind", "rest_world", "rest_local_rotation", "rest_local_translation"):
        if not np.array_equal(getattr(candidate, name), getattr(skeleton, name)): raise ValueError("byte patch changed " + name)
    if candidate.names != skeleton.names or candidate.parents != skeleton.parents: raise ValueError("byte patch changed skeleton identity")
    return {"source": str(source), "output": str(destination), "gain": gain, "mode": mode, "bytePatchOnly": True, "noIkContacts": True, "restMeshUnchanged": True, "rotationNormError": float(np.max(np.abs(np.linalg.norm(styled, axis=-1)-1.0))), "deformationStrainCheck": "not_run_offline_pose_only"}

def run(manifest_path, output, unit_sids, group_ids, gain=1.45):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")); rows=[]; requested={(unit, group) for unit in unit_sids for group in group_ids}; found=set()
    output.mkdir(parents=True, exist_ok=True)
    for unit in manifest.get("units", []):
        if unit.get("gameSid") not in unit_sids: continue
        for group in unit.get("groups", []):
            if group.get("groupId") not in group_ids: continue
            source = Path(group["glb"]); source = source if source.is_absolute() else manifest_path.parent/source
            mode = "move" if group["groupId"] == "g00_move" else "attack"
            found.add((unit["gameSid"], group["groupId"])); dest = output/unit["gameSid"]/source.name; rows.append({"gameSid":unit["gameSid"], "groupId":group["groupId"], "result":_patch_glb(source,dest,mode=mode,gain=gain)})
    if found != requested: raise ValueError("requested unit/group set is incomplete")
    report={"schema":SCHEMA,"accepted":False,"disposition":"preview_only","units":rows,"limits":["no IK","no contact constraints","no runtime proof","leaf rotations preserved","no automatic damping or strain-based rejection"]}
    (output/"report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8"); return report

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--manifest",type=Path,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--units",nargs="+",required=True); p.add_argument("--groups",nargs="+",default=["g00_move","g12_attack_front"]); p.add_argument("--gain",type=float,default=1.45); a=p.parse_args(); run(a.manifest,a.output,a.units,a.groups,a.gain)
