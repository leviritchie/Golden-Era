#!/usr/bin/env python3
"""Generate run_hybrid_method_quad.py from live module introspection."""

from __future__ import annotations

import importlib
import inspect
import sys
from dataclasses import fields
from pathlib import Path
from textwrap import dedent

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = TOOL / "run_hybrid_method_quad.py"

sys.path.insert(0, str(TOOL))

mat = importlib.import_module("materialize_rife_source_frames")
wid = importlib.import_module("roc_semantic_hybrid_widgets")
gpu = importlib.import_module("gpu_raster_depth_animation")
cmp = importlib.import_module("run_chain_space_surface_compare")
cru = importlib.import_module("run_crusader_gpu_cascade_animation_set")
lock = importlib.import_module("gpu_cascade_batch_lock")

field_names = {f.name for f in fields(wid.RocAssetChoice)}


def pick(*candidates: str) -> str:
    for name in candidates:
        if name in field_names:
            return name
    raise RuntimeError(f"none of {candidates} in {sorted(field_names)}")


F_SOURCE_KIND = pick("source_kind", "source_kind")
F_PRESENT = pick("present_groups", "present_groups")
F_LAB_DIR = pick("def_lab_frame_dir", "def_lab_frame_dir")
F_ANIM = pick("animation_name", "animation_name")
F_CHOICE = pick("choice_id", "choice_id")
F_PILOT = pick("pilot_dir", "pilot_dir")
F_CAMERA = pick("camera_fit", "camera_fit")
F_FRAMES = pick("frame_indices", "frame_indices")
F_SOURCE_FRAMES = pick("source_frames", "source_frames")
F_LAB_GROUPS = pick("def_lab_groups", "def_lab_groups")
F_COUNTS = pick("def_expected_counts", "def_expected_counts")
F_SEQ = pick("sequence_kind", "sequence_kind")

assert hasattr(mat, "def_sequence_animation_name")
assert hasattr(mat, "def_sequence_choice_id")
assert hasattr(mat, "inventory_authentic_def_groups")
assert hasattr(wid, "discover_asset_choices")
assert hasattr(wid, "_runtime_paths")
assert hasattr(gpu, "run_gpu_depth_fit_from_hybrid_config")
assert hasattr(cmp, "compose_clip_gif")
assert hasattr(cmp, "_prepare_choice_config")
assert hasattr(cmp, "_sprite_dir")
assert hasattr(cru, "notebook_gpu_fit_kwargs")
assert hasattr(cru, "_release_gpu_workspace")
assert hasattr(lock, "acquire_cascade_batch_lock")
assert (TOOL / "roc_chromatic_single_bone_match.ipynb").is_file()

fit_sig = set(inspect.signature(gpu.run_gpu_depth_fit_from_hybrid_config).parameters)

# Kwargs from working pyc + v2 flyer axes / profile basis.
KWARGS_TEMPLATE = {
    "score_mode": "'dinov3_dense'",
    "chain_space_enabled": "False",
    "gradient_ladder_enabled": "False",
    "ik_enabled": "False",
    "collision_enabled": "False",
    "collision_weight": "0.0",
    "depth_weight": "0.0",
    "silhouette_weight": "0.0",
    "chroma_weight": "0.0",
    "motion_weight": "0.0",
    "joint_unique_gain_weight": "0.0",
    "fine_unique_gain_weight": "0.0",
    "root_search_enabled": "True",
    "root_rotation_axes": "AXES",
    "root_rotation_camera_up_limit_deg": "120.0 if flyer else 45.0",
    "root_rotation_first_frame_limit_deg": "90.0 if flyer else 30.0",
    "root_rotation_per_frame_limit_deg": "45.0 if flyer else 30.0",
    "root_rotation_defer_camera_up": "True",
    "profile_init_enabled": "True",
    "profile_init_camera_basis_mode": "BASIS",
    "profile_init_yaw_step_deg": "10.0 if flyer else 15.0",
    "profile_init_roll_range_deg": "16.0 if flyer else 8.0",
    "profile_init_roll_step_deg": "8.0",
    "physics_smooth_enabled": "True",
    "physics_smooth_stiffness": "90.0",
    "physics_smooth_gravity": "0.81",
    "physics_smooth_gravity_weight": "0.3",
    "articulated_iterations": "1",
    "fine_iterations": "0",
    "base_pose_enabled": "False",
    "mid_pose_enabled": "False",
    "branch_rescue_enabled": "False",
}

missing = sorted(set(KWARGS_TEMPLATE) - fit_sig)
if missing:
    raise RuntimeError(f"kwargs not in fit signature: {missing}")

kwargs_body = ",\n        ".join(
    f'"{key}": {value}' for key, value in KWARGS_TEMPLATE.items()
).replace(
    '"root_rotation_axes": AXES',
    '"root_rotation_axes": (\n'
    '            ("camera_right", "camera_up")\n'
    '            if flyer\n'
    '            else ("camera_forward", "camera_right", "camera_up")\n'
    "        )",
).replace(
    '"profile_init_camera_basis_mode": BASIS',
    '"profile_init_camera_basis_mode": (\n'
    '            "geometry_broad_thin" if flyer else "upright_turntable"\n'
    "        )",
)

source = dedent(
    f'''\
    #!/usr/bin/env python3
    """Hybrid pose method trials for Roc Move, Crusader AttackFront, Behemoth Move, Medusa Hit.

    v2 compound (frugal, <=5 min/clip):
      - silhouette profile init + discrete root search
      - DINOv3-dense joint score (geometry terms zeroed; chain-space off)
      - one articulated round + light physics smooth
      - flyers: pitch+yaw root freedom WITHOUT camera_forward roll
        (v1 DINOv3 preferred ~71 deg roll and banked the roc into a dive)

    Does not overwrite idle keep. Does not apply CURRENT_CASCADE_KEEP (refuses dinov3).
    Same knobs for all four clips; only flyer rotation allowances differ by unit class.
    """

    from __future__ import annotations

    import argparse
    import json
    import os
    import sys
    import time
    from dataclasses import replace
    from pathlib import Path
    from typing import Any

    ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
    TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
    NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
    OUT_ROOT = ROOT / "artifacts/pose_picker_runs/hybrid_method_quad"
    BUDGET_SEC = 300.0
    METHOD_ID = "hybrid_v2_dinov3_flyer_pitch_yaw"

    if str(TOOL) not in sys.path:
        sys.path.insert(0, str(TOOL))

    from gpu_cascade_batch_lock import (  # noqa: E402
        acquire_cascade_batch_lock,
        global_cascade_batch_lock_path,
        release_cascade_batch_lock,
    )
    from run_chain_space_surface_compare import (  # noqa: E402
        _prepare_choice_config,
        _sprite_dir,
        compose_clip_gif,
    )
    from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
        _release_gpu_workspace,
        notebook_gpu_fit_kwargs,
    )

    CLIPS: dict[str, dict[str, Any]] = {{
        "roc_move": {{
            "unit_sid": "h3_roc",
            "def_groups": (0,),
            "mesh": ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb",
            "unit_class": "flyer",
            "title": "Roc Move (DEF 0)",
        }},
        "crusader_attack_front": {{
            "unit_sid": "h3_crusader",
            "def_groups": (12,),
            "mesh": ROOT / "artifacts/meshy_downloads/h3_crusader_smartrigged_rigidized.glb",
            "unit_class": "ground",
            "title": "Crusader AttackFront (DEF 12)",
        }},
        "behemoth_move": {{
            "unit_sid": "h3_behemoth",
            "def_groups": (0,),
            "mesh": ROOT / "artifacts/meshy_downloads/h3_behemoth_smartrigged.glb",
            "unit_class": "ground",
            "title": "Behemoth Move (DEF 0)",
        }},
        "medusa_hitted": {{
            "unit_sid": "h3_medusa",
            "def_groups": (3,),
            "mesh": ROOT / "artifacts/meshy_downloads/h3_medusa_smartrigged_rigidized.glb",
            "unit_class": "ground",
            "title": "Medusa Hit (DEF 3)",
        }},
    }}


    def _build_isolated_def_choice(widgets, *, unit_sid: str, def_groups: tuple[int, ...]):
        """Build a single-group authentic DEF choice with no idle prefix/postfix."""
        from materialize_rife_source_frames import (
            def_sequence_animation_name,
            def_sequence_choice_id,
            inventory_authentic_def_groups,
        )

        if not def_groups:
            raise ValueError("def_groups must be non-empty")
        need = int(def_groups[0])
        donors = [
            choice
            for choice in widgets.discover_asset_choices(ROOT)
            if choice.unit_sid == unit_sid
            and choice.{F_SOURCE_KIND} == "authentic_def"
            and need in (choice.{F_PRESENT} or ())
            and choice.{F_LAB_DIR} is not None
        ]
        if not donors:
            raise RuntimeError(f"{{unit_sid}}: no authentic DEF inventory contains group {{need}}")
        donor = donors[0]
        inventory = inventory_authentic_def_groups(Path(donor.{F_LAB_DIR}))
        frames: list[Any] = []
        counts: list[int] = []
        for group in def_groups:
            if int(group) not in inventory or not inventory[int(group)]:
                raise RuntimeError(
                    f"{{unit_sid}}: DEF group {{group}} missing from {{donor.{F_LAB_DIR}}}"
                )
            group_frames = tuple(inventory[int(group)])
            frames.extend(group_frames)
            counts.append(len(group_frames))
        animation = def_sequence_animation_name(tuple(int(g) for g in def_groups))
        runtime_dir, camera_fit = widgets._runtime_paths(ROOT, unit_sid, animation)
        return replace(
            donor,
            {F_ANIM}=animation,
            {F_CHOICE}=def_sequence_choice_id(unit_sid, tuple(int(g) for g in def_groups)),
            {F_PILOT}=runtime_dir,
            {F_CAMERA}=camera_fit,
            {F_FRAMES}=tuple(range(len(frames))),
            {F_SOURCE_FRAMES}=tuple(frames),
            {F_LAB_GROUPS}=tuple(int(g) for g in def_groups),
            {F_COUNTS}=tuple(counts),
            {F_SEQ}="isolated_def",
        )


    def hybrid_kwargs(*, unit_class: str) -> dict[str, Any]:
        """Shared hybrid knobs. Flyer class gets pitch/yaw freedom without dive-roll."""
        flyer = str(unit_class) == "flyer"
        return {{
            {kwargs_body}
        }}


    def fit_clip(label: str) -> dict[str, Any]:
        import roc_semantic_hybrid_widgets as widgets
        from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

        spec = CLIPS[label]
        mesh = Path(spec["mesh"])
        if not mesh.is_file():
            raise FileNotFoundError(mesh)
        out = OUT_ROOT / METHOD_ID / label
        arm_dir = out / METHOD_ID
        arm_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        choice = _build_isolated_def_choice(
            widgets,
            unit_sid=str(spec["unit_sid"]),
            def_groups=tuple(int(g) for g in spec["def_groups"]),
        )
        config = _prepare_choice_config(choice, mesh, NOTEBOOK)
        gpu_kwargs = notebook_gpu_fit_kwargs(NOTEBOOK)
        gpu_kwargs.update(hybrid_kwargs(unit_class=str(spec["unit_class"])))
        notes = {{
            "schema": "hybrid_method_quad.v2",
            "methodId": METHOD_ID,
            "label": label,
            "title": spec["title"],
            "unitClass": spec["unit_class"],
            "budgetSec": BUDGET_SEC,
            "knobs": hybrid_kwargs(unit_class=str(spec["unit_class"])),
            "not": "CURRENT_CASCADE_KEEP; idle keep untouched",
            "v1Failure": "dinov3 preferred ~71deg camera_forward roll -> dive bank",
        }}
        (out / "notes.json").write_text(json.dumps(notes, indent=2) + "\\n", encoding="utf-8")
        frame_count = len(config.frame_indices)
        print(f"fit {{label}} frames={{frame_count}} class={{spec['unit_class']}}", flush=True)
        solved = run_gpu_depth_fit_from_hybrid_config(config, output_dir=arm_dir, **gpu_kwargs)
        elapsed = time.perf_counter() - started
        result_path = Path(solved.pose_result["clipResultPath"])
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        config_out = payload.get("config") or {{}}
        if str(config_out.get("score_mode")) != "dinov3_dense":
            raise RuntimeError(f"{{label}}: expected dinov3_dense, got {{config_out.get('score_mode')}}")
        if not bool(config_out.get("physics_smooth_enabled")):
            raise RuntimeError(f"{{label}}: physics_smooth_enabled did not stay on")
        if bool(config_out.get("chain_space_enabled")):
            raise RuntimeError(f"{{label}}: chain_space must stay off for dinov3_dense")
        if not bool(config_out.get("root_search_enabled")):
            raise RuntimeError(f"{{label}}: root_search_enabled must stay on for hybrid")
        root_axes = tuple(config_out.get("root_rotation_axes") or ())
        if str(spec["unit_class"]) == "flyer" and "camera_forward" in root_axes:
            raise RuntimeError(
                f"{{label}}: flyer hybrid must exclude camera_forward roll, got {{root_axes}}"
            )
        gif = compose_clip_gif(
            clip_root=out,
            sprite_dir=_sprite_dir(choice),
            frame_count=frame_count,
            arms=({{"id": METHOD_ID}},),
        )
        root0 = (payload.get("poses") or {{}}).get("0", {{}}).get("__motion_root_rotation__") or {{}}
        report = {{
            "label": label,
            "title": spec["title"],
            "gif": str(gif).replace("\\\\", "/"),
            "clipResult": str(result_path).replace("\\\\", "/"),
            "score": payload.get("score"),
            "elapsedSec": round(elapsed, 1),
            "budgetSec": BUDGET_SEC,
            "withinBudget": elapsed <= BUDGET_SEC,
            "frameCount": frame_count,
            "unitClass": spec["unit_class"],
            "score_mode": config_out.get("score_mode"),
            "root_search_enabled": config_out.get("root_search_enabled"),
            "root_rotation_axes": list(root_axes),
            "root_rotation_camera_up_limit_deg": config_out.get(
                "root_rotation_camera_up_limit_deg"
            ),
            "root0": root0,
            "physics_smooth_enabled": config_out.get("physics_smooth_enabled"),
            "profile": payload.get("initialization") or payload.get("profile"),
            "proof": "generated-artifact; hybrid trial; not CURRENT_CASCADE_KEEP; not OE runtime",
        }}
        (out / "run_report.json").write_text(json.dumps(report, indent=2) + "\\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        if elapsed > BUDGET_SEC:
            raise RuntimeError(
                f"{{label}}: exceeded {{BUDGET_SEC:.0f}}s budget ({{elapsed:.1f}}s); "
                "hybrid knobs must get cheaper before retrying this clip"
            )
        return report


    def main() -> int:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument(
            "--clips",
            default="roc_move",
            help=f"comma-separated labels from {{sorted(CLIPS)}}",
        )
        args = parser.parse_args()
        wanted = [part.strip() for part in str(args.clips).split(",") if part.strip()]
        unknown = sorted(set(wanted) - set(CLIPS))
        if unknown:
            raise SystemExit(f"unknown clips: {{unknown}}; known={{sorted(CLIPS)}}")
        lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
        reports: list[dict[str, Any]] = []
        try:
            for label in wanted:
                reports.append(fit_clip(label))
                _release_gpu_workspace()
        finally:
            _release_gpu_workspace()
            release_cascade_batch_lock(lock, pid=os.getpid())
        summary = {{
            "methodId": METHOD_ID,
            "budgetSec": BUDGET_SEC,
            "reports": reports,
            "allWithinBudget": all(bool(row.get("withinBudget")) for row in reports),
        }}
        out_dir = OUT_ROOT / METHOD_ID
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\\n", encoding="utf-8"
        )
        print(json.dumps({{"summary": str(out_dir / "summary.json"), "n": len(reports)}}, indent=2))
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
    '''
)

OUT.write_text(source, encoding="utf-8", newline="\n")
print("wrote", OUT, "bytes", OUT.stat().st_size)
print("fields", sorted(field_names))
print(
    "attrs",
    F_SOURCE_KIND,
    F_PRESENT,
    F_LAB_DIR,
    F_ANIM,
    F_CHOICE,
    F_PILOT,
    F_CAMERA,
    F_FRAMES,
    F_SOURCE_FRAMES,
    F_LAB_GROUPS,
    F_COUNTS,
    F_SEQ,
)

# import smoke
spec = importlib.util.spec_from_file_location("hybrid_quad_gen_check", OUT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)
print("IMPORT_OK", mod.METHOD_ID)
for cls in ("flyer", "ground"):
    kw = mod.hybrid_kwargs(unit_class=cls)
    bad = sorted(set(kw) - fit_sig)
    print(cls, "axes", kw["root_rotation_axes"], "bad", bad)
