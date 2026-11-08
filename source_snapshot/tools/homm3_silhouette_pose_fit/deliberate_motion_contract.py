"""Fail-closed lifecycle / source-motion contract for skinned clips.

One unit contract names exactly one canonical Idle producer and, for mobile
units, exactly one canonical Move producer. Clip rows own lifecycle identity
(cycle / entry / exit / one_shot / terminal). Shared source poses may feed
separate Unity assets; one ``.anim`` may not carry two incompatible roles.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from preview_timing import PREVIEW_GIF_FRAME_MS

SCHEMA = "deliberate_motion_contract.v1"
LIFECYCLE_ROLES = ("cycle", "entry", "exit", "one_shot", "terminal")
# Authentic DEF plates in this lane are played at 12 fps. Preview GIFs use
# 180 ms/plate. Those are different owners and must not be inferred from a
# folder name or the solver job clock.
AUTHENTIC_DEF_FRAME_DURATION_SECONDS = 1.0 / 12.0
PREVIEW_FRAME_DURATION_SECONDS = float(PREVIEW_GIF_FRAME_MS) / 1000.0
IDLE_GROUP = 2
MOVE_GROUP = 0

ROLE_BY_SUFFIX = {
    "Idle": "cycle",
    "Move": "cycle",
    "Mouseover": "cycle",
    "Defence": "cycle",
    "MoveStart": "entry",
    "MoveEnd": "exit",
    "Hitted": "one_shot",
    "AttackFront": "one_shot",
    "ShootFront": "one_shot",
    "Death": "terminal",
}

CANONICAL_PRODUCER_BY_SUFFIX = {
    "Idle": "Idle",
    "Move": "Move",
}

STOCK_STATE_BY_SUFFIX = {
    "Idle": "22.Idle",
    "Move": "01.Walk",
    "MoveStart": "ground.MoveStart",
    "MoveEnd": "ground.MoveEnd",
    "Mouseover": "15.Skill_1",
    "Hitted": "20.Damage",
    "Death": "21.Death",
    "AttackFront": "14.Attack",
    "ShootFront": "14.Attack",
    "Defence": "25.Stance",
}

# Stock Esquire ground walk jumps Idle <-> Move. The owned controller must
# not keep that bypass once MoveStart/MoveEnd are declared.
STOCK_GROUND_BYPASS = (("22.Idle", "01.Walk"), ("01.Walk", "22.Idle"))


def contract_suffix(clip_name: str) -> str:
    name = str(clip_name or "")
    if not name:
        raise ValueError("clip name is empty")
    idx = name.find("_")
    if idx < 0 or idx == len(name) - 1:
        raise ValueError(f"clip name {name!r} has no contract suffix")
    return name[idx + 1 :]


def lifecycle_role_for_suffix(suffix: str) -> str:
    role = ROLE_BY_SUFFIX.get(str(suffix))
    if role is None:
        raise KeyError(f"unclassified lifecycle suffix: {suffix}")
    return role


def lifecycle_role_for_clip_name(clip_name: str) -> str:
    return lifecycle_role_for_suffix(contract_suffix(clip_name))


def loop_time_for_role(role: str) -> bool:
    if role not in LIFECYCLE_ROLES:
        raise KeyError(f"unknown lifecycle role: {role}")
    return role == "cycle"


def cycle_key_count(source_frame_count: int) -> int:
    count = int(source_frame_count)
    if count < 1:
        raise ValueError("source_frame_count must be positive")
    return count + 1


def cycle_duration_seconds(
    source_frame_count: int,
    *,
    frame_duration_seconds: float = AUTHENTIC_DEF_FRAME_DURATION_SECONDS,
) -> float:
    count = int(source_frame_count)
    dt = float(frame_duration_seconds)
    if count < 1:
        raise ValueError("source_frame_count must be positive")
    if not (dt > 0.0):
        raise ValueError("frame_duration_seconds must be positive")
    return count * dt


def sample_times_seconds(
    source_frame_count: int,
    *,
    role: str,
    frame_duration_seconds: float = AUTHENTIC_DEF_FRAME_DURATION_SECONDS,
) -> tuple[float, ...]:
    count = int(source_frame_count)
    dt = float(frame_duration_seconds)
    if count < 1:
        raise ValueError("source_frame_count must be positive")
    if not (dt > 0.0):
        raise ValueError("frame_duration_seconds must be positive")
    if role == "cycle":
        return tuple(index * dt for index in range(count + 1))
    return tuple(index * dt for index in range(count))


def clip_lifecycle_row(
    *,
    clip_name: str,
    def_group: int,
    source_frame_count: int,
    frame_duration_seconds: float = AUTHENTIC_DEF_FRAME_DURATION_SECONDS,
    predecessor: str | None = None,
    successor: str | None = None,
) -> dict[str, Any]:
    suffix = contract_suffix(clip_name)
    role = lifecycle_role_for_suffix(suffix)
    count = int(source_frame_count)
    if role in {"entry", "exit"} and count < 2:
        readiness = "blocked_one_pose_transition"
    elif role == "cycle" and count < 2:
        readiness = "blocked_one_pose_cycle"
    else:
        readiness = "classified"
    times = sample_times_seconds(
        count, role=role, frame_duration_seconds=frame_duration_seconds
    )
    return {
        "schema": SCHEMA,
        "contractName": str(clip_name),
        "suffix": suffix,
        "defGroup": int(def_group),
        "lifecycleRole": role,
        "canonicalProducer": CANONICAL_PRODUCER_BY_SUFFIX.get(suffix),
        "sourceFrameCount": count,
        "keyCount": len(times),
        "frameDurationSeconds": float(frame_duration_seconds),
        "timingOwner": "authentic_def_group_playback",
        "previewFrameDurationSeconds": PREVIEW_FRAME_DURATION_SECONDS,
        "previewTimingOwner": "pose_pipeline_stick_gif",
        "durationSeconds": float(times[-1]) if times else 0.0,
        "loopTime": loop_time_for_role(role),
        "loopBlend": False,
        "applyRootMotion": False,
        "serializeRegistrationRoot": False,
        "nativeAnimatorState": STOCK_STATE_BY_SUFFIX.get(suffix),
        "predecessor": predecessor,
        "successor": successor,
        "fullAnimationReadiness": readiness,
    }


def default_edges_for_suffix(suffix: str) -> tuple[str | None, str | None]:
    return {
        "Idle": (None, "MoveStart"),
        "MoveStart": ("Idle", "Move"),
        "Move": ("MoveStart", "MoveEnd"),
        "MoveEnd": ("Move", "Idle"),
        "Hitted": (None, "Idle"),
        "AttackFront": (None, "Idle"),
        "ShootFront": (None, "Idle"),
        "Death": (None, None),
        "Mouseover": (None, None),
        "Defence": (None, None),
    }.get(str(suffix), (None, None))


def build_unit_contract(
    lab_sid: str,
    clip_rows: Sequence[Mapping[str, Any]],
    *,
    mobile: bool = True,
) -> dict[str, Any]:
    sid = str(lab_sid)
    rows = [dict(row) for row in clip_rows]
    if not rows:
        raise ValueError(f"{sid}: unit contract has no clip rows")
    names = [str(row["contractName"]) for row in rows]
    if len(names) != len(set(names)):
        raise ValueError(f"{sid}: duplicate clip contract names {names}")
    by_suffix: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        suffix = str(row["suffix"])
        by_suffix.setdefault(suffix, []).append(row)
        role = str(row["lifecycleRole"])
        if role not in LIFECYCLE_ROLES:
            raise ValueError(f"{sid}: {row['contractName']} has unknown role {role}")
        if bool(row.get("loopBlend")):
            raise ValueError(f"{sid}: loopBlend is forbidden")
        if bool(row.get("applyRootMotion")):
            raise ValueError(f"{sid}: applyRootMotion must be false")
        if bool(row.get("serializeRegistrationRoot")):
            raise ValueError(f"{sid}: registration/camera root must not be serialized")
        if bool(row.get("loopTime")) != loop_time_for_role(role):
            raise ValueError(
                f"{sid}: {row['contractName']} loopTime {row.get('loopTime')!r} "
                f"does not match role {role}"
            )

    idle_rows = [row for row in rows if row.get("canonicalProducer") == "Idle"]
    move_rows = [row for row in rows if row.get("canonicalProducer") == "Move"]
    errors: list[str] = []
    if len(idle_rows) != 1:
        errors.append(f"{sid}: need exactly one canonical Idle producer, got {len(idle_rows)}")
    if mobile and len(move_rows) != 1:
        errors.append(f"{sid}: need exactly one canonical Move producer, got {len(move_rows)}")
    if not mobile and move_rows:
        errors.append(f"{sid}: immobile unit must not declare a Move producer")

    stance = by_suffix.get("Defence") or []
    victory = by_suffix.get("Victory") or []
    if stance and victory:
        stance_assets = {row["contractName"] for row in stance}
        victory_assets = {row["contractName"] for row in victory}
        if stance_assets & victory_assets:
            errors.append(
                f"{sid}: StanceLoop and Victory cannot share a Unity clip asset"
            )

    return {
        "schema": SCHEMA,
        "labSid": sid,
        "mobile": bool(mobile),
        "canonicalIdle": None if not idle_rows else str(idle_rows[0]["contractName"]),
        "canonicalMove": None if not move_rows else str(move_rows[0]["contractName"]),
        "maxStopLatencyMovePeriods": 1.0,
        "stopLatencyOwner": "canonical_move_phase_anchor",
        "clips": rows,
        "errors": errors,
        "classified": not errors,
    }


def load_unit_contract(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"{path} is not {SCHEMA}")
    rebuilt = build_unit_contract(
        str(payload["labSid"]),
        payload.get("clips") or [],
        mobile=bool(payload.get("mobile", True)),
    )
    return rebuilt


def unit_contract_from_clip_sidecars(
    lab_sid: str,
    sidecars: Sequence[Mapping[str, Any]],
    *,
    mobile: bool = True,
) -> dict[str, Any]:
    rows = []
    for sidecar in sidecars:
        name = str(sidecar.get("contractName") or sidecar.get("clipName") or "")
        suffix = contract_suffix(name)
        predecessor, successor = default_edges_for_suffix(suffix)
        count = int(sidecar.get("sourceFrameCount") or sidecar.get("frameCount") or 0)
        row = clip_lifecycle_row(
            clip_name=name,
            def_group=int(sidecar.get("defGroup") or -1),
            source_frame_count=count,
            predecessor=predecessor,
            successor=successor,
        )
        row["clipResultPath"] = sidecar.get("clipResultPath")
        row["output"] = sidecar.get("output") or sidecar.get("clipPath")
        rows.append(row)
    return build_unit_contract(lab_sid, rows, mobile=mobile)
