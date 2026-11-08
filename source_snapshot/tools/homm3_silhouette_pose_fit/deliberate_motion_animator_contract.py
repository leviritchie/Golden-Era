"""Native Animator ground-locomotion contract. No runtime Play/CrossFade."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "owned_ground_locomotion_controller.v1"
CONTRACT_PATH = (
    Path(__file__).resolve().parents[1] / "homm3_import" / "owned_ground_locomotion_controller.json"
)

# Required owned graph. Stock Esquire Idle<->Move bypass is forbidden here.
REQUIRED_STATES = (
    "22.Idle",
    "ground.MoveStart",
    "01.Walk",
    "ground.MoveEnd",
)

REQUIRED_TRANSITIONS = (
    {"from": "22.Idle", "to": "ground.MoveStart", "param": "move", "equals": True, "hasExitTime": False},
    {"from": "ground.MoveStart", "to": "01.Walk", "param": None, "equals": None, "hasExitTime": True},
    {"from": "01.Walk", "to": "ground.MoveEnd", "param": "move", "equals": False, "hasExitTime": False},
    {"from": "ground.MoveEnd", "to": "22.Idle", "param": None, "equals": None, "hasExitTime": True},
    {
        "from": "ground.MoveStart",
        "to": "ground.MoveEnd",
        "param": "move",
        "equals": False,
        "hasExitTime": False,
        "interrupt": True,
    },
    {
        "from": "ground.MoveEnd",
        "to": "ground.MoveStart",
        "param": "move",
        "equals": True,
        "hasExitTime": False,
        "interrupt": True,
    },
)

FORBIDDEN_TRANSITIONS = (
    {"from": "22.Idle", "to": "01.Walk"},
    {"from": "01.Walk", "to": "22.Idle"},
)

CLIP_ROLE_BY_STATE = {
    "22.Idle": "Idle",
    "ground.MoveStart": "MoveStart",
    "01.Walk": "Move",
    "ground.MoveEnd": "MoveEnd",
}


def owned_ground_controller_contract() -> dict[str, Any]:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"{CONTRACT_PATH} schema {payload.get('schema')!r} != {SCHEMA}")
    return payload


def _edge_key(src: str, dest: str) -> tuple[str, str]:
    return (str(src), str(dest))


def validate_controller_graph(graph: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if graph.get("schema") != SCHEMA:
        errors.append(f"controller schema {graph.get('schema')!r} != {SCHEMA}")
    if graph.get("runtimePlayOrCrossFade") or graph.get("updatePoller"):
        errors.append("runtime Animator.Play/CrossFade and Update pollers are forbidden")
    if graph.get("applyRootMotion"):
        errors.append("applyRootMotion must be false")
    states = {str(item.get("name")) for item in (graph.get("states") or [])}
    for name in REQUIRED_STATES:
        if name not in states:
            errors.append(f"missing required state {name}")
    present_edges = {
        _edge_key(item.get("from"), item.get("to")) for item in (graph.get("transitions") or [])
    }
    for item in REQUIRED_TRANSITIONS:
        key = _edge_key(item["from"], item["to"])
        if key not in present_edges:
            errors.append(f"missing required transition {key[0]} -> {key[1]}")
    for item in FORBIDDEN_TRANSITIONS:
        key = _edge_key(item["from"], item["to"])
        if key in present_edges:
            errors.append(f"forbidden stock bypass present: {key[0]} -> {key[1]}")
    return errors


def simulate_ground_chain(
    *,
    move_asserted_frames: Sequence[bool],
    move_start_length: int,
    move_length: int,
    move_end_length: int,
) -> list[str]:
    """Sample the declared graph. Lengths are source poses, not Unity CrossFade."""
    if min(move_start_length, move_length, move_end_length) < 1:
        raise ValueError("simulated clips must have at least one pose")
    flags = [bool(item) for item in move_asserted_frames]
    state = "22.Idle"
    start_left = 0
    end_left = 0
    move_phase = 0
    sequence = [state]
    for asserted in flags:
        if state == "22.Idle" and asserted:
            state = "ground.MoveStart"
            start_left = int(move_start_length)
            sequence.append(state)
        elif state == "ground.MoveStart":
            start_left -= 1
            if not asserted:
                state = "ground.MoveEnd"
                end_left = int(move_end_length)
                sequence.append(state)
            elif start_left <= 0:
                state = "01.Walk"
                move_phase = 0
                sequence.append(state)
        elif state == "01.Walk":
            move_phase = (move_phase + 1) % int(move_length)
            if not asserted:
                # Finish only to the next phase anchor (phase 0), then MoveEnd.
                if move_phase == 0:
                    state = "ground.MoveEnd"
                    end_left = int(move_end_length)
                    sequence.append(state)
        elif state == "ground.MoveEnd":
            end_left -= 1
            if asserted:
                state = "ground.MoveStart"
                start_left = int(move_start_length)
                sequence.append(state)
            elif end_left <= 0:
                state = "22.Idle"
                sequence.append(state)
    return sequence
