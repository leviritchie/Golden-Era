#!/usr/bin/env python3
"""Prop-only sprite landmark authoring (sword, shield, other carried items).

Subset of crusader_author_common: no full-body stick required. Partial joints
per frame are valid; load_ik_keypoints already skips missing / invisible entries.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw

# Crusader humanoid defaults — extend per unit in the coords JSON ``joints`` list.
CRUSADER_SWORD_SHIELD_JOINTS = ("WeaponTip", "RWrist", "ShieldCenter", "LWrist")

PROP_EDGES: dict[str, list[tuple[str, str]]] = {
    "crusader_sword_shield": [
        ("RWrist", "WeaponTip"),
        ("LWrist", "ShieldCenter"),
    ],
    "behemoth_quadruped_sprite_skeleton": [
        ("HeadTip", "PawTipA"),
        ("HeadTip", "PawTipB"),
        ("TailTip", "HeadTip"),
    ],
    "humanoid_weapon_sprite_skeleton": [
        ("RWrist", "WeaponTip"),
    ],
    "quadruped_sprite_skeleton": [
        ("HeadTip", "PawTipA"),
        ("HeadTip", "PawTipB"),
        ("TailTip", "HeadTip"),
    ],
    "flyer_sprite_skeleton": [
        ("HeadTip", "WingTipA"),
        ("HeadTip", "WingTipB"),
        ("TailTip", "HeadTip"),
    ],
    "hobgoblin_mace_sprite_skeleton": [
        ("RWrist", "WeaponTip"),
    ],
    "roc_flyer_sprite_skeleton": [
        ("HeadTip", "WingTipA"),
        ("HeadTip", "WingTipB"),
        ("TailTip", "HeadTip"),
    ],
}

PROP_COLORS: dict[str, tuple[int, int, int]] = {
    "WeaponTip": (255, 40, 255),
    "RWrist": (80, 200, 255),
    "ShieldCenter": (255, 220, 60),
    "LWrist": (220, 180, 255),
}


def validate_joint_names(joints: Sequence[str]) -> tuple[str, ...]:
    names = tuple(str(name) for name in joints)
    if not names:
        raise ValueError("prop joint list is empty")
    dupes = [name for name in names if names.count(name) > 1]
    if dupes:
        raise ValueError(f"duplicate prop joints: {sorted(set(dupes))}")
    return names


def list_sprite_frames(frames_dir: Path) -> list[Path]:
    """``frame_*.png`` (NN upscale) or numbered ``00.png`` … (shadow-culled DEF)."""
    frames_dir = Path(frames_dir)
    if not frames_dir.is_dir():
        raise FileNotFoundError(f"frames dir not found: {frames_dir}")
    frame_glob = sorted(frames_dir.glob("frame_*.png"))
    if frame_glob:
        return frame_glob
    numbered = [p for p in frames_dir.glob("*.png") if p.stem.isdigit()]
    if not numbered:
        raise FileNotFoundError(f"no sprite PNGs in {frames_dir}")
    return sorted(numbered, key=lambda p: int(p.stem))


def joint_dict(xy: dict[str, tuple[int, int]], joint_names: Sequence[str]) -> dict:
    names = validate_joint_names(joint_names)
    missing = [name for name in names if name not in xy]
    if missing:
        raise ValueError(f"missing prop joints in frame: {missing}")
    extra = [name for name in xy if name not in names]
    if extra:
        raise ValueError(f"unknown prop joints in frame: {extra}")
    return {
        name: {
            "x": float(xy[name][0]),
            "y": float(xy[name][1]),
            "visible": True,
            "score": 1.0,
            "source": "human_eye",
        }
        for name in names
    }


def draw_prop_overlay(
    sprite: Path,
    joints: dict[str, tuple[int, int]],
    *,
    label: str,
    joint_names: Sequence[str],
    edge_set: str = "crusader_sword_shield",
) -> Image.Image:
    names = validate_joint_names(joint_names)
    edges = PROP_EDGES.get(edge_set, [])
    sp = Image.open(sprite).convert("RGBA")
    pad = 24
    canvas = Image.new("RGBA", (sp.width + pad * 2, sp.height + pad * 2), (0, 0, 0, 255))
    canvas.paste(sp, (pad, pad), sp)
    draw = ImageDraw.Draw(canvas)

    def pt(name: str) -> tuple[int, int]:
        x, y = joints[name]
        return int(x + pad), int(y + pad)

    for a, b in edges:
        if a not in joints or b not in joints:
            continue
        pa, pb = pt(a), pt(b)
        draw.line([pa, pb], fill=(0, 0, 0), width=5)
        draw.line([pa, pb], fill=(0, 255, 90), width=3)
    for name in names:
        x, y = joints[name]
        p = (int(x + pad), int(y + pad))
        rgb = PROP_COLORS.get(name, (255, 255, 255))
        radius = 8 if name in {"WeaponTip", "ShieldCenter"} else 6
        draw.ellipse(
            [p[0] - radius - 1, p[1] - radius - 1, p[0] + radius + 1, p[1] + radius + 1],
            fill=(0, 0, 0),
        )
        draw.ellipse(
            [p[0] - radius, p[1] - radius, p[0] + radius, p[1] + radius],
            fill=rgb,
        )
        draw.text((p[0] + radius + 2, p[1] - 6), name, fill=rgb)
    draw.text((8, 8), label, fill=(255, 255, 0))
    draw.text((8, 24), "human eye-authored prop landmarks", fill=(220, 220, 80))
    return canvas.convert("RGB")


def write_prop_authored_clip(
    *,
    clip_id: str,
    unit_sid: str,
    frames_dir: Path,
    out_dir: Path,
    frames_xy: list[dict[str, tuple[int, int]]],
    joint_names: Sequence[str],
    notes: str,
    edge_set: str = "crusader_sword_shield",
    frame_indices: Sequence[int] | None = None,
) -> dict:
    sprites = list_sprite_frames(frames_dir)
    if frame_indices is not None:
        if len(frame_indices) != len(frames_xy):
            raise RuntimeError(
                f"{clip_id}: frame_indices length {len(frame_indices)} != authored {len(frames_xy)}"
            )
        sprite_by_index = {int(p.stem) if p.stem.isdigit() else i: p for i, p in enumerate(sprites)}
        # numbered DEF plates: stem is frame index
        if all(p.stem.isdigit() for p in sprites):
            sprite_by_index = {int(p.stem): p for p in sprites}
            sprites_ordered = [sprite_by_index[int(i)] for i in frame_indices]
        else:
            sprites_ordered = [sprites[int(i)] for i in frame_indices]
    else:
        sprites_ordered = sprites
        frame_indices = list(range(len(sprites_ordered)))

    if len(sprites_ordered) != len(frames_xy):
        raise RuntimeError(
            f"{clip_id}: frame count mismatch sprites={len(sprites_ordered)} authored={len(frames_xy)}"
        )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    overlays_dir = out_dir / "overlays"
    overlays_dir.mkdir(parents=True, exist_ok=True)
    landmarks_dir = out_dir / "sprite_landmarks"
    landmarks_dir.mkdir(parents=True, exist_ok=True)

    names = validate_joint_names(joint_names)
    frames_out = []
    gif_frames = []
    for seq, (sprite, xy, frame_index) in enumerate(zip(sprites_ordered, frames_xy, frame_indices)):
        im = Image.open(sprite)
        w, h = im.size
        frames_out.append(
            {
                "frameIndex": int(frame_index),
                "ok": True,
                "path": str(sprite).replace("\\", "/"),
                "transform": {"srcWidth": int(w), "srcHeight": int(h), "pad": 0},
                "joints": joint_dict(xy, names),
            }
        )
        overlay = draw_prop_overlay(
            sprite,
            xy,
            label=f"{clip_id} props f{int(frame_index):02d}",
            joint_names=names,
            edge_set=edge_set,
        )
        overlay.save(overlays_dir / f"props_{int(frame_index):02d}.png")
        gif_frames.append(overlay)

    gif_path = out_dir / f"{clip_id}_props_authored.gif"
    gif_frames[0].save(
        gif_path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=180,
        loop=0,
        optimize=False,
    )
    doc = {
        "ok": True,
        "unitSid": str(unit_sid),
        "clipId": str(clip_id),
        "method": "human_eye_landmark_authoring",
        "authoringScope": "props_only",
        "propJoints": list(names),
        "proof": (
            f"prop-only landmarks authored by inspecting sprites for {clip_id}; "
            "not OE runtime; not mesh projection"
        ),
        "notes": notes,
        "errors": [],
        "frames": frames_out,
    }
    keypoints_path = landmarks_dir / "keypoints.json"
    keypoints_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "clipId": clip_id,
        "keypoints": str(keypoints_path).replace("\\", "/"),
        "gif": str(gif_path).replace("\\", "/"),
        "overlays": str(overlays_dir).replace("\\", "/"),
        "frames": len(frames_out),
        "joints": list(names),
    }
