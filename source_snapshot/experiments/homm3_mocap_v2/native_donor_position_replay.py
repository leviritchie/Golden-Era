"""Replay raw same-actor positions on a native donor bind skeleton."""
from __future__ import annotations

import numpy as np

from direction_retarget import reconstruct_frame_locals
from donor_eagle import compute_rest_joints, skin_dense
from mesh_preview import fk_world_matrices


def replay_native_donor(*, captured_positions, donor_offsets, parents, names,
                        vertices=None, weights=None, inverse_bind=None):
    capture = np.asarray(captured_positions, dtype=np.float64)
    offsets = np.asarray(donor_offsets, dtype=np.float64)
    raw_parent = np.asarray(parents)
    if raw_parent.ndim != 1 or raw_parent.dtype.kind not in "iu":
        raise ValueError("parents must be an integer [J] array")
    parent = raw_parent.astype(np.int64, copy=False)
    labels = [str(name) for name in names]
    if capture.ndim != 3 or not len(capture) or capture.shape[-1] != 3 or not np.isfinite(capture).all():
        raise ValueError("captured_positions must be nonempty finite [F,J,3]")
    joints = capture.shape[1]
    if joints < 1:
        raise ValueError("captured_positions must contain at least one joint")
    if offsets.shape != (joints, 3) or not np.isfinite(offsets).all():
        raise ValueError("donor_offsets must be finite [J,3]")
    if parent.shape != (joints,) or parent[0] != -1 or any(int(p) < 0 or int(p) >= i for i, p in enumerate(parent[1:], 1)):
        raise ValueError("parents must be root-first ordered")
    if len(labels) != joints or len(set(labels)) != joints:
        raise ValueError("names must be unique and match joints")
    rest = compute_rest_joints(offsets, parent)
    structural = np.linalg.norm(offsets, axis=1) <= 1e-8
    structural[0] = False
    captured_lengths = np.linalg.norm(capture - capture[:, parent.clip(0)], axis=-1)
    if np.any(captured_lengths[:, structural] > 1e-8):
        raise ValueError("structurally coincident donor edge is separated in capture")
    observable = (parent >= 0) & ~structural
    if np.any(captured_lengths[:, observable] <= 1e-8):
        raise ValueError("captured observable donor edge collapsed")
    if vertices is not None or weights is not None or inverse_bind is not None:
        if vertices is None or weights is None or inverse_bind is None:
            raise ValueError("vertices, weights, and inverse_bind must be supplied together")
        verts = np.asarray(vertices, dtype=np.float64); skin = np.asarray(weights, dtype=np.float64); ibm = np.asarray(inverse_bind, dtype=np.float64)
        if verts.ndim != 2 or verts.shape[1] != 3 or not np.isfinite(verts).all() or skin.shape != (len(verts), joints) or not np.isfinite(skin).all() or np.any(skin < 0) or not np.allclose(skin.sum(1), 1., atol=1e-8) or ibm.shape != (joints,4,4) or not np.isfinite(ibm).all():
            raise ValueError("invalid donor mesh skin inputs")
    else:
        verts = skin = ibm = None
    worlds=[]; locals_out=[]; endpoint=[]; raw_errors=[]; direction_errors=[]
    rest_local=np.repeat(np.eye(3)[None], joints, axis=0)
    for frame in capture:
        desired=np.zeros((joints,3), dtype=np.float64)
        for index in range(1,joints):
            if structural[index]: continue
            desired[index]=(frame[index]-frame[parent[index]])/np.linalg.norm(frame[index]-frame[parent[index]])
        local=reconstruct_frame_locals(desired=desired, rest_local=rest_local, rest_off=offsets,
            parents=parent, root_world=frame[0])
        world=fk_world_matrices(local_rotation=local, local_translation=offsets,
            parents=parent, root_world=frame[0])
        pred=world[:,:3,3]
        worlds.append(world); locals_out.append(local)
        endpoint.append(float(np.linalg.norm(pred-frame, axis=-1).max()))
        raw_errors.append(float(np.abs(captured_lengths[len(worlds)-1, observable]-np.linalg.norm(offsets[observable],axis=-1)).max(initial=0.)))
        actual = pred[observable] - pred[parent[observable]]
        actual /= np.linalg.norm(actual, axis=-1, keepdims=True)
        cosine = np.sum(actual * desired[observable], axis=-1)
        direction_errors.append(float(np.degrees(np.arccos(np.clip(cosine,-1.,1.))).max(initial=0.)))
    result={"jointWorld":np.stack(worlds),"positions":np.stack([w[:,:3,3] for w in worlds]),"localRotation":np.stack(locals_out),
            "endpointResidualMax":endpoint,"rawLengthErrorMax":raw_errors,"fittedRest":rest,"structuralEdges":[labels[i] for i in np.flatnonzero(structural)],
            "directionErrorMaxDeg":direction_errors,
            "motionOwner":"native_donor_position_replay","twistPolicy":"single_child_axial_and_leaf_rotation_underdetermined_per_frame_rest_prior","exactReplay":bool(max(endpoint,default=0.)<1e-8)}
    if verts is not None:
        result["meshes"]=np.stack([skin_dense(verts,skin,w,ibm) for w in result["jointWorld"]])
    return result


__all__=["replay_native_donor"]
