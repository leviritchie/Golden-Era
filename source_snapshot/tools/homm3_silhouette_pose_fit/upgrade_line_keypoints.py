#!/usr/bin/env python3
"""Upgrade-line authored keypoint donors when skeletons match.

When units in the same recruitment tier share an identical skin joint
topology, authored sprite sticks from a sibling unit's fit tree may seed IK
for the target unit. Fail-closed when joint names or parent indices differ.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Sequence

_TOOL = Path(__file__).resolve().parent
_MESHY_TOOL = _TOOL.parent / "homm3_meshy_frame_pose"
if str(_TOOL) not in sys.path:
    sys.path.insert(0, str(_TOOL))
if str(_MESHY_TOOL) not in sys.path:
    sys.path.insert(0, str(_MESHY_TOOL))

from inventory_smartrig_skinned_rollout import (
    catalog_lab_sids,
    family_for_game_sid,
    game_sid_to_lab,
    lab_to_import,
    upgrade_families,
)
from owned_rerig.glb_io import read_glb


def lab_sid_from_unit_name(unit_name: str) -> str:
    unit = str(unit_name or "").strip()
    if not unit:
        raise ValueError("unit_name is required")
    if unit.startswith("h3_"):
        return unit
    return f"h3_{unit}"


def unit_name_from_lab_sid(lab_sid: str) -> str:
    sid = str(lab_sid or "").strip()
    if sid.startswith("h3_"):
        return sid[3:]
    return sid


def lab_sid_family_peers(lab_sid: str, *, catalog: Sequence[str] | None = None) -> list[str]:
    """Lab SIDs in the same upgrade line, base tier first."""
    catalog_set = set(catalog if catalog is not None else catalog_lab_sids())
    families = upgrade_families()
    game_to_lab = game_sid_to_lab()
    import_row = lab_to_import().get(lab_sid) or {}
    game_sids = import_row.get("gameUnitSids") or [lab_sid]
    primary_game = str(game_sids[0]) if game_sids else lab_sid
    _base, family_game_sids = family_for_game_sid(primary_game, families)
    peers: list[str] = []
    for game_sid in family_game_sids:
        mapped = game_to_lab.get(game_sid)
        if mapped and mapped in catalog_set:
            peers.append(mapped)
        if game_sid in catalog_set:
            peers.append(game_sid)
        if str(game_sid).startswith("h3_"):
            rest = str(game_sid)[3:]
            for prefix in ("hota_cove_", "hota_factory_", "hota_bulwark_", "hota_"):
                alt = prefix + rest
                if alt in catalog_set:
                    peers.append(alt)
    ordered = list(dict.fromkeys(peers))
    if lab_sid in ordered:
        ordered.remove(lab_sid)
        ordered.insert(0, lab_sid)
    elif lab_sid not in catalog_set:
        ordered.insert(0, lab_sid)
    return ordered


def skeleton_skin_signature(glb_path: Path) -> tuple[tuple[str, ...], tuple[int, ...]]:
    """Named skin joints and parent indices (-1 for root) in skin order."""
    path = Path(glb_path).resolve()
    doc = read_glb(path)["json"]
    nodes = doc.get("nodes") or []
    skins = doc.get("skins") or []
    if not skins:
        return (), ()
    joint_nodes = [int(i) for i in skins[0].get("joints") or []]
    if not joint_nodes:
        return (), ()
    parent_of: dict[int, int | None] = {i: None for i in range(len(nodes))}
    for index, node in enumerate(nodes):
        for child in node.get("children") or []:
            parent_of[int(child)] = int(index)
    node_to_skin = {node: skin for skin, node in enumerate(joint_nodes)}
    names: list[str] = []
    parents: list[int] = []
    for node_idx in joint_nodes:
        node = nodes[node_idx]
        names.append(str(node.get("name") or f"node{node_idx}"))
        parent_node = parent_of.get(node_idx)
        if parent_node is None:
            parents.append(-1)
        else:
            parents.append(int(node_to_skin.get(parent_node, -1)))
    return tuple(names), tuple(parents)


def skeleton_signatures_match(left: Path, right: Path) -> bool:
    return skeleton_skin_signature(left) == skeleton_skin_signature(right)


def default_smartrig_glb(lab_sid: str, root: Path) -> Path | None:
    meshy = Path(root) / "artifacts" / "meshy_downloads"
    for suffix in ("_smartrigged_rigidized.glb", "_smartrigged.glb"):
        path = meshy / f"{lab_sid}{suffix}"
        if path.is_file():
            return path.resolve()
    return None


def load_pose_seed_from_clip(path: Path) -> dict[int, dict[str, Any]] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    poses = payload.get("poses") or {}
    if not isinstance(poses, dict) or not poses:
        return None
    out: dict[int, dict[str, Any]] = {}
    for key, value in poses.items():
        if isinstance(value, dict) and value:
            out[int(key)] = dict(value)
    return out or None


def upgrade_line_pose_seed(
    *,
    root: Path,
    lab_sid: str,
    animation_name: str,
    target_mesh: Path,
    run_names: Sequence[str] = ("fused_push_v24_pipeline", "gpu_cascade_delivery"),
) -> dict[int, dict[str, Any]] | None:
    """Seed from a sibling unit's solved clip when skin topology matches."""
    target_mesh = Path(target_mesh).resolve()
    for peer_sid in lab_sid_family_peers(lab_sid):
        if peer_sid == lab_sid:
            continue
        donor_glb = default_smartrig_glb(peer_sid, root)
        if donor_glb is None or not skeleton_signatures_match(donor_glb, target_mesh):
            continue
        peer_pilot = Path(root) / "artifacts" / "pose_picker_runs" / peer_sid / str(animation_name)
        for run_name in run_names:
            clip = peer_pilot / str(run_name) / "gpu_clip_result.json"
            seeded = load_pose_seed_from_clip(clip)
            if seeded is not None:
                print(
                    f"upgrade-line pose seed: {peer_sid} -> {lab_sid} "
                    f"animation={animation_name!r} donor={clip}",
                    flush=True,
                )
                return seeded
    return None


def _borrowed_keypoints_out(
    *,
    root: Path,
    unit: str,
    animation: str,
) -> Path:
    return (
        Path(root)
        / "artifacts"
        / f"{unit}_pose_pipeline"
        / "out_fit"
        / "_cascade_ik_borrowed"
        / f"{animation}_keypoints.json"
    )


def write_borrowed_keypoints(
    *,
    root: Path,
    unit: str,
    animation: str,
    donor_path: Path,
    donor_lab_sid: str,
    target_glb: Path,
) -> Path:
    payload = json.loads(Path(donor_path).read_text(encoding="utf-8"))
    if payload.get("method") != "human_eye_landmark_authoring":
        raise ValueError(
            f"upgrade-line keypoint borrow refuses non-authored donor {donor_path} "
            f"(method={payload.get('method')!r})"
        )
    out = _borrowed_keypoints_out(root=root, unit=unit, animation=animation)
    out.parent.mkdir(parents=True, exist_ok=True)
    borrowed = copy.deepcopy(payload)
    borrowed["borrowedFrom"] = {
        "labSid": donor_lab_sid,
        "path": str(Path(donor_path).resolve()),
        "targetGlb": str(Path(target_glb).resolve()),
        "skeletonSignature": {
            "jointNames": list(skeleton_skin_signature(target_glb)[0]),
        },
    }
    borrowed["proof"] = (
        "upgrade-line authored keypoints borrowed after identical skin-joint "
        "topology check; not a substitute for per-unit sprite authorship when "
        "sprites diverge materially"
    )
    out.write_text(json.dumps(borrowed, indent=2) + "\n", encoding="utf-8")
    return out.resolve()
