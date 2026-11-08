#!/usr/bin/env python3
"""Angel move: does the wing chain's motion drive the legs/hem off the rails?

The angel's two wing chains own ~40% of the skinned vertices and sweep a
large, fast-changing part of the sprite silhouette. The suspicion under
test is the same failure class as a swung weapon: pixels that belong to
the high-motion appendage stay unexplained, the solver pays any bone that
covers them, and the cheapest such bones are the legs and the hem — which
is why the feet wander and the skirt webs.

Each trial answers one question about that hypothesis by controlling
**who may move** (``search_bones``, so unsearched bones hold their bind
pose) or **how far each chain may move** (``bone_limit_scale_overrides``,
per-bone multipliers on ``joint_limit_deg``).

Shared baseline is the previous grid's winner (SA off, full discrete
walk + polish), so this grid varies wing/body freedom only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
DEFAULT_OUT = (
    ROOT
    / "artifacts/pose_picker_runs/h3_angel/idle_start_move_end/wing_dominance_compare"
)

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from run_angel_bone_order_compare import (  # noqa: E402
    ANGEL_MESH,
    NOTEBOOK,
    _filter_fit_kwargs,
    _notebook_gpu_kwargs,
    _release_gpu,
    _select_angel_move,
)
from run_crusader_full_animation_set import _literal_config_kwargs, _notebook_config  # noqa: E402
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _choice_overrides,
    prepare_gpu_targets,
)

# Chains of h3_angel_smartrigged_rigidized.glb, authored from the bind
# skeleton and re-verified against the GLB on every run (see
# verify_bone_groups). The rig is a Meshy smartrig with generated names,
# so nothing in the file itself says "wing"; these names are only valid
# for this mesh.
BONE_GROUPS: dict[str, tuple[str, ...]] = {
    "spine": ("Bone_000", "Bone_001", "Bone_004", "Bone_003", "Bone_002"),
    "head": ("Bone_019", "Bone_018", "Bone_017"),
    "wing_left": ("Bone_024", "Bone_023", "Bone_022", "Bone_021", "Bone_020"),
    "wing_right": ("Bone_029", "Bone_028", "Bone_027", "Bone_026", "Bone_025"),
    "leg_left": ("Bone_012", "Bone_011", "Bone_010", "Bone_009"),
    "leg_right": ("Bone_016", "Bone_015", "Bone_014", "Bone_013"),
    "hem": ("Bone_008", "Bone_007", "Bone_006", "Bone_005"),
}

# Parent of each chain's first bone. Every other bone in a chain must be
# parented to the previous entry, which is what makes these lists chains
# rather than arbitrary name sets.
CHAIN_ROOT_PARENT: dict[str, str | None] = {
    "spine": None,
    "head": "Bone_002",
    "wing_left": "Bone_002",
    "wing_right": "Bone_002",
    "leg_left": "Bone_001",
    "leg_right": "Bone_001",
    "hem": "Bone_001",
}

WINGS = BONE_GROUPS["wing_left"] + BONE_GROUPS["wing_right"]
LEGS = BONE_GROUPS["leg_left"] + BONE_GROUPS["leg_right"]
BODY = tuple(
    name
    for group, names in BONE_GROUPS.items()
    if not group.startswith("wing_")
    for name in names
)
NOT_LEGS = tuple(
    name
    for group, names in BONE_GROUPS.items()
    if not group.startswith("leg_")
    for name in names
)
LEGS_AND_HEM = LEGS + BONE_GROUPS["hem"]
ALL_BONES = tuple(name for names in BONE_GROUPS.values() for name in names)

# 150° joint_limit_deg, so 0.30 -> 45°, 0.20 -> 30°, 0.40 -> 60°.
LEG_CAP = 0.20
WING_CAP = 0.30
BODY_CAP = 0.25
GLOBAL_CAP = 0.40

# Previous grid's winner. SA with collision weight 0 was proposing pretzels
# that the discrete walk then inherited.
SHARED_OVERRIDES: dict[str, Any] = {
    "sa_enabled": False,
    "base_pose_enabled": True,
    "mid_pose_enabled": True,
    "branch_rescue_enabled": True,
    "fine_iterations": 2,
    "sa_seed": 0,
    "live_preview": False,
    "physics_smooth_enabled": True,
}


def _scales(names: Sequence[str], scale: float) -> tuple[tuple[str, float], ...]:
    return tuple((str(name), float(scale)) for name in names)


TRIALS: tuple[dict[str, Any], ...] = (
    {
        "id": "control",
        "label": "control",
        "reason": (
            "Baseline: previous winner (SA off, full discrete walk + polish), "
            "every bone free. Everything else is measured against this."
        ),
        "overrides": {},
    },
    {
        "id": "wings_bind",
        "label": "wings_bind",
        "reason": (
            "Wings never searched, so they hold the bind pose all clip. If the "
            "legs and hem settle down, the wings were the disturbance."
        ),
        "overrides": {
            "search_bones": BODY,
            "include_unlisted_search_bones": False,
        },
    },
    {
        "id": "legs_bind",
        "label": "legs_bind",
        "reason": (
            "Legs never searched. If the score barely drops, the legs were not "
            "explaining leg pixels; they were filling in for the wings."
        ),
        "overrides": {
            "search_bones": NOT_LEGS,
            "include_unlisted_search_bones": False,
        },
    },
    {
        "id": "wings_only",
        "label": "wings_only",
        "reason": (
            "Only the wings may move. Shows how much of the frame-to-frame "
            "silhouette change the wings alone actually account for."
        ),
        "overrides": {
            "search_bones": WINGS,
            "include_unlisted_search_bones": False,
        },
    },
    {
        "id": "leg_cap",
        "label": "leg_cap",
        "reason": (
            "Legs and hem capped at 30°, wings free. Directly forbids the "
            "splay that produces wandering feet and skirt webbing without "
            "giving up any wing range."
        ),
        "overrides": {"bone_limit_scale_overrides": _scales(LEGS_AND_HEM, LEG_CAP)},
    },
    {
        "id": "wing_cap",
        "label": "wing_cap",
        "reason": (
            "Wings capped at 45°, body free. The mirror test: restrain the "
            "high-motion element instead of its victims."
        ),
        "overrides": {"bone_limit_scale_overrides": _scales(WINGS, WING_CAP)},
    },
    {
        "id": "body_cap",
        "label": "body_cap",
        "reason": (
            "Everything except the wings capped at 37.5°. The wings carry the "
            "motion; nothing else can contort far enough to substitute for them."
        ),
        "overrides": {"bone_limit_scale_overrides": _scales(BODY, BODY_CAP)},
    },
    {
        "id": "tight_all",
        "label": "tight_all",
        "reason": (
            "Every bone capped at 60°. Control for the caps above: if this "
            "looks as good, the fix is just less rotation everywhere, not "
            "wing-vs-body ownership."
        ),
        "overrides": {"bone_limit_scale_overrides": _scales(ALL_BONES, GLOBAL_CAP)},
    },
)


def verify_bone_groups(mesh: Path) -> dict[str, Any]:
    """Fail closed unless BONE_GROUPS still describes this GLB.

    Meshy names carry no anatomy, so an agent reading this file later has
    no way to tell a stale name list from a correct one. This re-derives
    the parent chains and the wing vertex share from the mesh and refuses
    to run when they disagree.
    """
    import numpy as np

    from roc_geometric_proxy import load_asset

    asset = load_asset(mesh)
    by_index = {node.index: node for node in asset.nodes}
    parent_name = {
        node.name: (None if node.parent is None else by_index[int(node.parent)].name)
        for node in asset.nodes
    }
    skinned = {by_index[int(joint)].name for skin in asset.skins for joint in skin.joints}

    listed = [name for names in BONE_GROUPS.values() for name in names]
    duplicates = sorted({name for name in listed if listed.count(name) > 1})
    if duplicates:
        raise RuntimeError(f"bone groups list the same bone twice: {duplicates}")
    missing = sorted(skinned - set(listed))
    extra = sorted(set(listed) - skinned)
    if missing or extra:
        raise RuntimeError(
            "bone groups no longer partition the skinned joints of "
            f"{mesh.name}: missing={missing} unexpected={extra}"
        )
    for group, names in BONE_GROUPS.items():
        expected_root_parent = CHAIN_ROOT_PARENT[group]
        actual_root_parent = parent_name[names[0]]
        if expected_root_parent is not None and actual_root_parent != expected_root_parent:
            raise RuntimeError(
                f"bone group {group} starts at {names[0]} whose parent is "
                f"{actual_root_parent}, expected {expected_root_parent}"
            )
        for parent, child in zip(names, names[1:]):
            if parent_name[child] != parent:
                raise RuntimeError(
                    f"bone group {group} is not a chain: {child} is parented to "
                    f"{parent_name[child]}, expected {parent}"
                )

    primitive = asset.primitives[0]
    skin = asset.skins[0]
    joints = np.asarray(skin.joints)
    positions = np.asarray(primitive.positions)
    joint_ids = np.asarray(primitive.joints).reshape(len(positions), -1)
    weights = np.asarray(primitive.weights).reshape(len(positions), -1)
    dominant = joints[joint_ids[np.arange(len(positions)), weights.argmax(axis=1)]]
    index_by_name = {node.name: node.index for node in asset.nodes}
    share = {
        group: float(
            np.isin(dominant, [index_by_name[name] for name in names]).sum()
        )
        / float(len(positions))
        for group, names in BONE_GROUPS.items()
    }
    wing_share = share["wing_left"] + share["wing_right"]
    if wing_share < 0.25:
        raise RuntimeError(
            f"wing groups own only {wing_share:.1%} of the mesh; this grid is "
            "built on the wings dominating the silhouette, so the name mapping "
            "is probably wrong"
        )
    return {
        "mesh": str(mesh).replace("\\", "/"),
        "skinnedBones": len(skinned),
        "vertexShareByGroup": {group: round(value, 4) for group, value in share.items()},
        "wingVertexShare": round(wing_share, 4),
    }


def _trial_dir(out_root: Path, trial_id: str) -> Path:
    return Path(out_root) / str(trial_id)


def _merged_overrides(trial: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(SHARED_OVERRIDES)
    merged.update(dict(trial["overrides"]))
    return merged


def _as_json_value(value: Any) -> Any:
    """Normalize tuples to lists so a config compares equal after JSON."""
    if isinstance(value, (tuple, list)):
        return [_as_json_value(item) for item in value]
    return value


def _config_mismatches(
    recorded: Mapping[str, Any], expected: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    mismatches: dict[str, dict[str, Any]] = {}
    for key, value in expected.items():
        if key == "live_preview":
            continue
        got = recorded.get(key)
        if _as_json_value(got) != _as_json_value(value):
            mismatches[key] = {"expected": _as_json_value(value), "recorded": _as_json_value(got)}
    return mismatches


def _result_complete(out_dir: Path, trial: Mapping[str, Any]) -> bool:
    clip = out_dir / "gpu_clip_result.json"
    rgb = out_dir / "solved_rgb" / "00.png"
    stamp = out_dir / "wing_trial.json"
    if not clip.is_file() or not rgb.is_file() or not stamp.is_file():
        return False
    stamp_payload = json.loads(stamp.read_text(encoding="utf-8"))
    if str(stamp_payload.get("id") or "") != str(trial["id"]):
        return False
    payload = json.loads(clip.read_text(encoding="utf-8"))
    config = payload.get("config")
    if not isinstance(config, Mapping):
        return False
    return not _config_mismatches(config, _merged_overrides(trial))


def compose_compare_gif(*, out_root: Path, sprite_dir: Path, frame_count: int) -> Path:
    from compose_method_compare_gif import main as compose_main

    gif = Path(out_root) / "angel_move_wing_dominance_compare.gif"
    argv = [
        "--out",
        str(gif),
        "--cols",
        "3",
        "--cell-w",
        "260",
        "--cell-h",
        "300",
        "--hold",
        "2",
        "--frame-count",
        str(int(frame_count)),
        "--panel",
        "sprite",
        str(sprite_dir),
    ]
    for trial in TRIALS:
        argv.extend(
            ["--panel", str(trial["label"]), str(_trial_dir(out_root, trial["id"]) / "solved_rgb")]
        )
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError("compare GIF compose failed")
    return gif


def _main_locked() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--mesh", type=Path, default=ANGEL_MESH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--compose-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mesh = Path(args.mesh).resolve()
    if mesh != ANGEL_MESH.resolve():
        raise RuntimeError(f"angel compare is locked to {ANGEL_MESH}")
    if not mesh.is_file():
        raise FileNotFoundError(mesh)

    import roc_semantic_hybrid_widgets as widgets
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from roc_semantic_hybrid_experiment import RocHybridConfig

    rig = verify_bone_groups(mesh)
    choice = _select_angel_move(widgets)
    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    notebook_kwargs = _literal_config_kwargs(args.notebook, require_dino=False)
    gpu_base = _filter_fit_kwargs(_notebook_gpu_kwargs(args.notebook))

    plan = {
        "unit": choice.unit_sid,
        "animation": choice.animation_name,
        "groups": list(choice.def_lab_groups),
        "counts": list(choice.def_expected_counts),
        "frames": len(choice.frame_indices),
        "rig": rig,
        "boneGroups": {group: list(names) for group, names in BONE_GROUPS.items()},
        "sharedOverrides": SHARED_OVERRIDES,
        "trials": [
            {
                "id": trial["id"],
                "label": trial["label"],
                "reason": trial["reason"],
                "overrides": _as_json_value(_merged_overrides(trial)),
            }
            for trial in TRIALS
        ],
        "mesh": str(mesh).replace("\\", "/"),
        "out": str(out_root).replace("\\", "/"),
        "proof": (
            "generated artifact validated — wing-dominance preview GIF; "
            "not OE runtime proven"
        ),
    }
    (out_root / "compare_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(plan, indent=2), flush=True)
    if args.dry_run:
        return 0

    sprite_dir = Path(choice.pilot_dir) / f"frames_def12_nn_{choice.animation_name}_shadow_culled"
    if args.compose_only:
        gif = compose_compare_gif(
            out_root=out_root,
            sprite_dir=sprite_dir,
            frame_count=sum(int(count) for count in choice.def_expected_counts),
        )
        print(f"composed {gif}", flush=True)
        return 0

    config = _notebook_config(RocHybridConfig, notebook_kwargs, notebook=args.notebook)
    overrides = _choice_overrides(choice, mesh)
    report_path = overrides.get("meshy_rigidization_report")
    if report_path is not None:
        report_payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
        report_output = Path(str(report_payload.get("output") or "")).resolve()
        if report_output != mesh:
            overrides["meshy_rigidization_report"] = None
            overrides["require_meshy_rigidization"] = False
    config = replace(config, **overrides)
    config = prepare_gpu_targets(config)
    expected_frames = sum(int(count) for count in choice.def_expected_counts)
    if len(config.frame_indices) != expected_frames:
        raise RuntimeError(
            f"angel move materialized {len(config.frame_indices)} frames, "
            f"expected {expected_frames}"
        )

    for trial in TRIALS:
        dest = _trial_dir(out_root, trial["id"])
        merged = _merged_overrides(trial)
        if args.skip_existing and _result_complete(dest, trial):
            print(f"reuse {trial['id']}: {dest}", flush=True)
            continue
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "wing_trial.json").write_text(
            json.dumps(
                {
                    "id": trial["id"],
                    "label": trial["label"],
                    "reason": trial["reason"],
                    "overrides": _as_json_value(merged),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        started = time.perf_counter()
        print(f"fit {trial['id']} frames={len(config.frame_indices)} out={dest}", flush=True)
        try:
            solved = run_gpu_depth_fit_from_hybrid_config(
                config,
                output_dir=dest,
                **{**gpu_base, **merged},
            )
            payload = json.loads(Path(solved.pose_result["clipResultPath"]).read_text(encoding="utf-8"))
            recorded = payload.get("config")
            if not isinstance(recorded, Mapping):
                raise RuntimeError(f"{dest} clip result is missing config")
            mismatches = _config_mismatches(recorded, merged)
            if mismatches:
                raise RuntimeError(
                    f"{dest} recorded config mismatches {trial['id']}: {mismatches}"
                )
            print(
                f"fitted {trial['id']} score={payload.get('score')} "
                f"elapsed={time.perf_counter() - started:.1f}s",
                flush=True,
            )
        finally:
            _release_gpu()

    gif = compose_compare_gif(
        out_root=out_root,
        sprite_dir=sprite_dir,
        frame_count=len(config.frame_indices),
    )
    print(f"composed {gif}", flush=True)
    return 0


def main() -> int:
    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    try:
        return _main_locked()
    finally:
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
