#!/usr/bin/env python3
"""Export keep-matching chosen-clip GLBs without taking the GPU lock.

Does not rewrite fit_plan.json. Does not install into Golden Era.
Idle-only exports stay in artifacts until the single complete deploy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = ROOT / "artifacts/homm3_smartrig_skinned_rollout"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_delivery import (  # noqa: E402
    CHOSEN_DEF_GROUPS,
    clip_result_matches_current_keep,
    contract_name_for_group,
    extract_glb_hexlit_pbr_maps,
    select_unit_delivery_choices,
    write_oriented_master_glb,
)
from inventory_smartrig_skinned_rollout import build_status  # noqa: E402
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _clip_result_path,
    _load_clip_result,
)
from run_gpu_cascade_animation_set import (  # noqa: E402
    _is_idle_choice,
    _json_dump,
    export_choice_clips,
)
import roc_semantic_hybrid_widgets as widgets  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--idle-only",
        action="store_true",
        help="export idle-only keep-matching results (default: every keep-matching chosen clip)",
    )
    args = parser.parse_args()
    out_dir = args.out.resolve()
    status = build_status()
    all_choices = widgets.discover_asset_choices(ROOT)
    exported_units = 0
    exported_clips = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    for row in status["units"]:
        if row.get("meshRole") != "own_glb":
            continue
        sid = row["labSid"]
        try:
            choices = select_unit_delivery_choices(all_choices, sid)
        except RuntimeError as exc:
            errors.append({"labSid": sid, "error": str(exc)})
            continue
        mesh = Path(row["glb"]).resolve()
        if not mesh.is_file():
            errors.append({"labSid": sid, "error": f"missing GLB {mesh}"})
            continue
        prefix = "Crusader" if sid == "h3_crusader" else "Unit"
        out_root = out_dir / "units" / sid
        clip_dir = out_root / "clips"
        unit_clips: list[dict[str, Any]] = []
        for choice in choices:
            if args.idle_only and not _is_idle_choice(choice):
                continue
            result_path = _clip_result_path(choice)
            if not result_path.is_file():
                skipped += 1
                continue
            payload = _load_clip_result(result_path)
            if not clip_result_matches_current_keep(payload):
                skipped += 1
                continue
            unit_clips.extend(
                export_choice_clips(choice, payload, mesh=mesh, clip_dir=clip_dir, prefix=prefix)
            )
        if not unit_clips:
            continue
        master = write_oriented_master_glb(
            mesh,
            out_root / f"{sid}_smartrig_master.glb",
            allow_missing_pbr_maps=True,
        )
        pbr = extract_glb_hexlit_pbr_maps(
            mesh, out_root, allow_missing_pbr_maps=True
        )
        report = {
            "labSid": sid,
            "mesh": str(mesh),
            "master": master,
            "pbr": pbr,
            "clips": unit_clips,
            "scale": row.get("scale"),
            "idleOnly": args.idle_only or all(
                item.get("defGroup") == 2 for item in unit_clips
            ),
            "proofTier": "generated-artifact",
        }
        _json_dump(out_root / "delivery_manifest.json", report)
        exported_units += 1
        exported_clips += len(unit_clips)
        print(f"exported {sid} clips={len(unit_clips)}", flush=True)
    summary = {
        "ok": not errors,
        "exportedUnits": exported_units,
        "exportedClips": exported_clips,
        "skippedMissingOrStale": skipped,
        "errors": errors,
    }
    _json_dump(out_dir / "keep_matching_export_report.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
