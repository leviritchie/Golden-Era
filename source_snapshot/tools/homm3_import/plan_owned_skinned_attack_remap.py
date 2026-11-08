#!/usr/bin/env python3
"""Desired stock attack slots for an owned skinned unit, derived from the candidate Core view.

The only semantic owner is validate_homm3_owned_skinned_attack_clip_contract.required_slots: slot choice comes from
the view (projectile -> Unit_ShootFront, melee/counter or projectile-less ability -> Unit_AttackFront), never from
which clips a unit happens to have. Consumed by remap_owned_attack_slots.py (the override-only remap driver).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from validate_homm3_owned_attack_animation_slots import row_errors  # noqa: E402
from validate_homm3_owned_skinned_attack_clip_contract import (  # noqa: E402
    load_views,
    required_slots,
)

SLOTS = ("14.Attack", "15.Skill_1")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def desired_slots(views: dict, game_sids: list[str]) -> list[dict[str, str]]:
    errors: list[str] = []
    desired: dict[str, str] = {}
    for sid in game_sids:
        view = views.get(sid)
        if view is None:
            errors.append(f"{sid}: no units_views row")
            continue
        errors.extend(row_errors(view))
        for slot, (clip, _where) in required_slots(sid, view, errors).items():
            if slot not in SLOTS:
                continue
            prior = desired.get(slot)
            if prior is not None and prior != clip:
                errors.append(f"{sid}: {slot} conflicts across game SIDs: {prior} vs {clip}")
            desired[slot] = clip
    if errors:
        raise ValueError("attack-slot view contract failed:\n" + "\n".join(errors))
    if not desired:
        raise ValueError("no attack or ability uses stock slots 14.Attack or 15.Skill_1")
    return [{"slot": slot, "clip": desired[slot]} for slot in SLOTS if slot in desired]


def asset_file(project: Path, asset_path: str) -> Path:
    parts = Path(asset_path.replace("\\", "/")).parts
    if not parts or parts[0] != "Assets" or ".." in parts:
        raise ValueError(f"not a Unity Assets path: {asset_path}")
    path = project.joinpath(*parts)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path
