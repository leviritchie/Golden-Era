"""Per-unit, reasoned DEF shoot groups a unit never plays: unit config "skipDefGroups".

    "skipDefGroups": {"15": "<why this unit never shoots: its installed view has no projectile attack or ability>"}

Keys are the HoMM3 shoot groups only (14 up, 15 front, 16 down); every value is a non-empty reason. Anything else
fails closed. Of the three, only 15 has an OE clip (Unit_ShootFront, CONTRACT_SUFFIX_BY_GROUP in
tools/homm3_silhouette_pose_fit/gpu_cascade_delivery.py); 14/16 are skipped for every unit already, so naming
them records the reason and changes nothing else.

Why: a unit whose DEF carries shoot frames (e.g. a cast) but whose game view never shoots still shipped
Unit_ShootFront, and Homm3OwnedSkinnedLabBuild.StockMap plays 15.Skill_1 -> Unit_ShootFront whenever the clip
exists, so a projectile-less ability on animationIndex 1 played the cast instead of the melee swing
(2026-09-28, h3_vampire_prince Blind; validate_homm3_owned_skinned_attack_clip_contract).

Honoured where the clip set is formed:
  experiments/homm3_mocap_v2/linked_master_sequence.native_reel  (a new capture never takes the group; it is
      recorded under skippedClips with this reason)
  export_glb.py / verify_glb.py  (an existing capture keeps its frames in the master reel and <unit>_DEF_Master,
      but the Unit_ clip is not exported, and verify requires it absent)
Stdlib only: Blender's Python imports it.
"""
from __future__ import annotations

import json
from pathlib import Path

UNITS = Path(__file__).resolve().parent / "units"
SHOOT_GROUPS = frozenset({14, 15, 16})
# The shoot groups' OE clip (None: no OE clip; test_skip_def_groups pins this against CONTRACT_SUFFIX_BY_GROUP).
SHOOT_CLIP_BY_GROUP = {14: None, 15: "Unit_ShootFront", 16: None}


def parse(cfg: dict) -> dict[int, str]:
    """{DEF group: reason} from a unit config; {} when the key is absent."""
    raw = cfg.get("skipDefGroups")
    if raw is None:
        return {}
    unit = cfg.get("unit", "?")
    if not isinstance(raw, dict) or not raw:
        raise SystemExit(f"{unit}: skipDefGroups must be a non-empty {{\"<group>\": \"<reason>\"}} object")
    out = {}
    for k, why in raw.items():
        if not (isinstance(k, str) and k.isdigit() and int(k) in SHOOT_GROUPS):
            raise SystemExit(f"{unit}: skipDefGroups key {k!r} is not a shoot group {sorted(SHOOT_GROUPS)}")
        if not isinstance(why, str) or not why.strip():
            raise SystemExit(f"{unit}: skipDefGroups[{k}] needs a reason")
        out[int(k)] = why.strip()
    return out


def for_unit(unit: str) -> dict[int, str]:
    """parse() of units/<unit>.json; {} when the unit has no config (captures of units without a retarget config)."""
    p = UNITS / f"{unit}.json"
    return parse(json.loads(p.read_text(encoding="utf-8"))) if p.is_file() else {}


def skipped_clips(unit: str) -> dict[str, str]:
    """{Unit_ clip name: reason} the unit must not ship."""
    return {SHOOT_CLIP_BY_GROUP[g]: why for g, why in for_unit(unit).items() if SHOOT_CLIP_BY_GROUP[g]}


def unit_of_blend_actions(names) -> str:
    """The unit a built .blend belongs to: build_unit.py names its whole-reel action <unit>_DEF_Master."""
    units = sorted(n[: -len("_DEF_Master")] for n in names if n.endswith("_DEF_Master"))
    if len(units) != 1:
        raise SystemExit(f"expected exactly one <unit>_DEF_Master action, found {units}")
    return units[0]
