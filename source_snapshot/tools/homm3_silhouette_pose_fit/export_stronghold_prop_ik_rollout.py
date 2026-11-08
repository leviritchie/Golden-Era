#!/usr/bin/env python3
"""Export Stronghold delivery GLBs from prop-IK-polished clip results.

Reads ``fused_push_v24_pipeline_prop_ik_polish_genai_perframe_sites`` lanes
when present, otherwise falls back to raw fused_push solves.

Proof tier: generated artifact until Golden Era install validators pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = ROOT / "artifacts/fused_push_skinned_rollout"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_delivery import require_pose_units_degrees, select_unit_delivery_choices  # noqa: E402
from inventory_smartrig_skinned_rollout import smartrig_glbs  # noqa: E402
from literature_polish_common import load_source_clip, unit_mesh  # noqa: E402
from run_fused_push_batch_all_units import (  # noqa: E402
    _clip_result_path as fused_clip_result_path,
    _discover_all_choices,
)
from run_gpu_cascade_animation_set import export_choice_clips  # noqa: E402
from stronghold_prop_rollout_registry import prop_lane_name, rollout_units  # noqa: E402


def _prop_clip_result_path(choice) -> Path | None:
    pilot = Path(choice.pilot_dir)
    lane = pilot / prop_lane_name()
    for candidate in (
        lane / "solve" / "gpu_clip_result.json",
        lane / "gpu_clip_result.json",
        lane / "preview" / "gpu_clip_result.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def _resolve_clip_payload(choice) -> tuple[Path, dict[str, Any]]:
    prop_path = _prop_clip_result_path(choice)
    if prop_path is not None:
        return prop_path, load_source_clip(prop_path)
    base = fused_clip_result_path(choice)
    return base, load_source_clip(base)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default=None)
    parser.add_argument("--out", type=Path, default=OUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    units_filter = rollout_units() if args.unit is None else [str(args.unit)]
    glbs = smartrig_glbs()
    all_choices, _note = _discover_all_choices(ROOT)
    reports: list[dict[str, Any]] = []
    for sid in units_filter:
        try:
            choices = select_unit_delivery_choices(all_choices, sid)
        except RuntimeError as exc:
            print(f"skip {sid}: {exc}", flush=True)
            continue
        mesh = glbs.get(sid) or unit_mesh(sid, "idle")
        if not mesh.is_file():
            raise FileNotFoundError(f"missing mesh for {sid}: {mesh}")
        for choice in choices:
            clip_path, payload = _resolve_clip_payload(choice)
            require_pose_units_degrees(payload, source=str(clip_path))
            prefix = "Unit"
            out_root = Path(args.out) / "units" / sid
            clip_dir = out_root / "clips"
            clip_dir.mkdir(parents=True, exist_ok=True)
            exported = export_choice_clips(
                choice,
                payload,
                mesh=mesh,
                clip_dir=clip_dir,
                prefix=prefix,
                clip_result_path=clip_path,
            )
            row = {
                "labSid": sid,
                "animation": str(choice.animation_name),
                "clipResultPath": str(clip_path),
                "propIk": prop_lane_name() in str(clip_path),
                "clips": exported,
            }
            reports.append(row)
            print(
                f"exported {sid}/{choice.animation_name}: {len(exported)} clips from {clip_path.name}",
                flush=True,
            )
    summary = {
        "proofTier": "generated-artifact",
        "units": sorted({row["labSid"] for row in reports}),
        "exportedAnimations": len(reports),
        "reports": reports,
    }
    out = Path(args.out) / "stronghold_prop_ik_export_report.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "exportedAnimations": len(reports)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
