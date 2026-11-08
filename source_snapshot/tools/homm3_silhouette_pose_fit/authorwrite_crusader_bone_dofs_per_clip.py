#!/usr/bin/env python3
"""Author per-clip crusader DOFs from visual inspection of DEF groups.

Policy (2026-08 LWrist + legs pass):
- Legs are unlocked for every clip (plant via groundAnchor, not lockedBones).
- Hinge axes (x) on UpLeg/Leg/Foot for stance / weight-shift / stride.
- Walk adds modest hip yaw; avoid UpLeg z abduct (kicks skyward).
- Hips never get roll (z) except death.
"""
from __future__ import annotations

import json
from pathlib import Path

TOOL = Path(__file__).resolve().parent

TORSO_ARMS = [
    "Hips",
    "Spine02",
    "Spine01",
    "Spine",
    "neck",
    "Head",
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "LeftShoulder",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
]
LEGS = [
    "RightUpLeg",
    "RightLeg",
    "RightFoot",
    "LeftUpLeg",
    "LeftLeg",
    "LeftFoot",
]

# Default hinge stance — used unless a clip overrides.
LEG_HINGE = {
    "RightUpLeg": ["x"],
    "RightLeg": ["x"],
    "RightFoot": ["x"],
    "LeftUpLeg": ["x"],
    "LeftLeg": ["x"],
    "LeftFoot": ["x"],
}


def _bones(spec: dict[str, list[str]]) -> dict:
    out = {}
    for name in TORSO_ARMS + LEGS:
        axes = list(spec.get(name, []))
        if name in LEGS:
            why = "leg hinge" if axes == ["x"] else ("walk leg" if axes else "locked leg")
        else:
            why = "locked" if not axes else "authored for this clip"
        out[name] = {"axes": axes, "why": why}
    return out


def _with_legs(axes: dict[str, list[str]], leg: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    out = dict(axes)
    out.update(LEG_HINGE if leg is None else leg)
    return out


# Per-clip axes. Legs always present (hinge unless noted).
CLIPS: dict[str, dict] = {
    "idle_g2": {
        "notes": "Near-static idle bob; light leg hinge for weight settle + plant.",
        "axes": _with_legs(
            {
                "Hips": ["x"],
                "Spine": ["x"],
                "RightForeArm": ["x"],
                "RightHand": ["x", "z"],
                "LeftShoulder": ["x"],
            }
        ),
    },
    "mouseover_g1": {
        "notes": "Sword raise; light knee ease so legs are not frozen mannequin.",
        "axes": _with_legs(
            {
                "Hips": ["x"],
                "Spine": ["x"],
                "RightShoulder": ["x", "z"],
                "RightArm": ["x", "z"],
                "RightForeArm": ["x"],
                "RightHand": ["x", "z"],
                "LeftShoulder": ["x"],
                "LeftArm": ["x"],
            }
        ),
    },
    "unused_a_g9": {
        "notes": "Near-static; keep leg hinge available for seed mismatch.",
        "axes": _with_legs(
            {
                "RightForeArm": ["x"],
                "RightHand": ["x", "z"],
            }
        ),
    },
    "unused_b_g10": {
        "notes": "Near-static; keep leg hinge available for seed mismatch.",
        "axes": _with_legs(
            {
                "RightForeArm": ["x"],
                "RightHand": ["x", "z"],
            }
        ),
    },
    "turn_left_g7": {
        "notes": "Turn: yaw + tip; leg hinge for foot plant during twist.",
        "axes": _with_legs(
            {
                "Hips": ["y"],
                "Spine02": ["y"],
                "Spine01": ["y"],
                "Spine": ["x", "y"],
                "neck": ["y"],
                "RightShoulder": ["x", "z"],
                "RightArm": ["x", "z"],
                "RightForeArm": ["x"],
                "RightHand": ["x", "z"],
                "LeftShoulder": ["x"],
                "LeftArm": ["x"],
            }
        ),
    },
    "turn_right_g8": {
        "notes": "Turn right: yaw + tip; leg hinge for plant.",
        "axes": _with_legs(
            {
                "Hips": ["y"],
                "Spine02": ["y"],
                "Spine01": ["y"],
                "Spine": ["x", "y"],
                "neck": ["y"],
                "RightShoulder": ["x", "z"],
                "RightArm": ["x", "z"],
                "RightForeArm": ["x"],
                "RightHand": ["x", "z"],
                "LeftShoulder": ["x"],
                "LeftArm": ["x"],
            }
        ),
    },
    "move_g0": {
        "notes": "Walk: hinge stride; open arms enough for sword/shield silhouette (prior pass froze upper body on x-only).",
        "axes": _with_legs(
            {
                "Hips": ["x", "y"],
                "Spine02": ["x"],
                "Spine": ["x", "y"],
                "RightShoulder": ["x", "z"],
                "RightArm": ["x", "y", "z"],
                "RightForeArm": ["x"],
                "RightHand": ["x", "z"],
                "LeftShoulder": ["x", "z"],
                "LeftArm": ["x", "y", "z"],
                "LeftForeArm": ["x"],
                "LeftHand": ["x", "z"],
            }
        ),
    },
    "defence_g4": {
        "notes": "Defence brace with knee bend / weight shift; hips+legs free on hinge; shield arm primary.",
        "axes": _with_legs(
            {
                "Hips": ["x"],
                "Spine02": ["x"],
                "Spine01": ["x"],
                "Spine": ["x", "y"],
                "neck": ["x"],
                "RightShoulder": ["x"],
                "RightArm": ["x"],
                "RightForeArm": ["x"],
                "RightHand": ["x", "z"],
                "LeftShoulder": ["x", "y", "z"],
                "LeftArm": ["x", "y", "z"],
                "LeftForeArm": ["x", "y"],
                "LeftHand": ["x", "z"],
            }
        ),
    },
    "move_start_g20": {
        "notes": "Walk start: stride + hip yaw; no UpLeg z.",
        "axes": _with_legs(
            {
                "Hips": ["x", "y"],
                "Spine": ["x"],
                "RightArm": ["x", "z"],
                "RightForeArm": ["x"],
                "RightHand": ["x", "z"],
                "LeftArm": ["x", "z"],
                "LeftForeArm": ["x"],
            }
        ),
    },
    "move_end_g21": {
        "notes": "Walk end: stride + hip yaw; no UpLeg z.",
        "axes": _with_legs(
            {
                "Hips": ["x", "y"],
                "Spine": ["x"],
                "RightArm": ["x", "z"],
                "RightForeArm": ["x"],
                "RightHand": ["x", "z"],
                "LeftArm": ["x", "z"],
                "LeftForeArm": ["x"],
            }
        ),
    },
    "hitted_g3": {
        "notes": "Hit flinch: planted knees can buckle; torso recoil; arms jar.",
        "axes": _with_legs(
            {
                "Hips": ["x"],
                "Spine02": ["x", "y"],
                "Spine01": ["x", "y"],
                "Spine": ["x", "y"],
                "neck": ["x", "y"],
                "Head": ["x"],
                "RightShoulder": ["x", "z"],
                "RightArm": ["x", "z"],
                "RightForeArm": ["x"],
                "RightHand": ["x", "z"],
                "LeftShoulder": ["x", "z"],
                "LeftArm": ["x", "z"],
                "LeftForeArm": ["x"],
            }
        ),
    },
    "death_g5": {
        "notes": "Death fall: legs collapse with torso; plant off in IK profile.",
        "axes": _with_legs(
            {
                "Hips": ["x", "y"],
                "Spine02": ["x", "y", "z"],
                "Spine01": ["x", "y", "z"],
                "Spine": ["x", "y", "z"],
                "neck": ["x", "y"],
                "Head": ["x"],
                "RightShoulder": ["x", "z"],
                "RightArm": ["x", "y", "z"],
                "RightForeArm": ["x", "y"],
                "RightHand": ["x", "y", "z"],
                "LeftShoulder": ["x", "z"],
                "LeftArm": ["x", "z"],
                "LeftForeArm": ["x"],
                "LeftHand": ["x", "z"],
            },
            leg={
                "RightUpLeg": ["x", "y"],
                "RightLeg": ["x"],
                "RightFoot": ["x"],
                "LeftUpLeg": ["x", "y"],
                "LeftLeg": ["x"],
                "LeftFoot": ["x"],
            },
        ),
    },
    "attack_front_g12": {
        "notes": "Front slash: strike arm full; hip crouch + knee hinge for weight into swing.",
        "axes": _with_legs(
            {
                "Hips": ["x"],
                "Spine02": ["x", "y"],
                "Spine01": ["x", "y"],
                "Spine": ["x", "y"],
                "neck": ["x", "y"],
                "Head": ["x"],
                "RightShoulder": ["x", "z"],
                "RightArm": ["x", "y", "z"],
                "RightForeArm": ["x", "y"],
                "RightHand": ["x", "y", "z"],
                "LeftShoulder": ["x", "z"],
                "LeftArm": ["x", "z"],
                "LeftForeArm": ["x"],
                "LeftHand": ["x", "z"],
            }
        ),
    },
    "attack_up_g11": {
        "notes": "Attack up: strike + knee hinge / hip crouch into windup.",
        "axes": _with_legs(
            {
                "Hips": ["x"],
                "Spine02": ["x", "y"],
                "Spine01": ["x", "y"],
                "Spine": ["x", "y"],
                "neck": ["x", "y"],
                "Head": ["x"],
                "RightShoulder": ["x", "y", "z"],
                "RightArm": ["x", "y", "z"],
                "RightForeArm": ["x", "y"],
                "RightHand": ["x", "y", "z"],
                "LeftShoulder": ["x", "z"],
                "LeftArm": ["x", "z"],
                "LeftForeArm": ["x"],
                "LeftHand": ["x", "z"],
            }
        ),
    },
    "attack_down_g13": {
        "notes": "Attack down: crouch slash needs free knees + hips.",
        "axes": _with_legs(
            {
                "Hips": ["x"],
                "Spine02": ["x", "y"],
                "Spine01": ["x", "y"],
                "Spine": ["x", "y"],
                "neck": ["x"],
                "Head": ["x"],
                "RightShoulder": ["x", "z"],
                "RightArm": ["x", "y", "z"],
                "RightForeArm": ["x", "y"],
                "RightHand": ["x", "y", "z"],
                "LeftShoulder": ["x", "y", "z"],
                "LeftArm": ["x", "y", "z"],
                "LeftForeArm": ["x", "y"],
                "LeftHand": ["x", "z"],
            }
        ),
    },
}


def main() -> int:
    for clip_id, meta in CLIPS.items():
        path = TOOL / f"bone_dofs_crusader_{clip_id}.json"
        doc = {
            "unitSid": "h3_crusader",
            "clipId": clip_id,
            "rigFamily": "meshy_autorig_mixamo",
            "axesConvention": "Blender pose-bone rotation_euler XYZ indices (x=0,y=1,z=2) as used by marker IK poseVectors.",
            "proof": "authored per-clip after visual side-by-side inspection; not OE runtime proven.",
            "notes": meta["notes"],
            "bones": _bones(meta["axes"]),
        }
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        free = sum(len(b["axes"]) for b in doc["bones"].values())
        leg_free = sum(len(doc["bones"][n]["axes"]) for n in LEGS)
        print(f"{clip_id}: freeAxes={free} legAxes={leg_free} -> {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
