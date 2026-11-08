#!/usr/bin/env python3
"""Validate the source-owned Roc notebook control surface.

The experiment implementation now lives in
``roc_semantic_hybrid_experiment.py``. This module intentionally does not
regenerate notebook JSON, because regenerating an executed notebook can erase
live-preview outputs and obscure the tunable experiment settings.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
RUNTIME = TOOL / "roc_semantic_hybrid_experiment.py"
WIDGETS = TOOL / "roc_semantic_hybrid_widgets.py"


def main() -> None:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    source_files = [
        RUNTIME,
        WIDGETS,
        TOOL / "roc_chroma_match_worker.py",
        TOOL / "roc_rotation_search.py",
        TOOL / "roc_semantic_hybrid_setup.py",
        TOOL / "roc_semantic_hybrid_solver_body.py",
        TOOL / "roc_semantic_hybrid_delivery.py",
        TOOL / "roc_semantic_hybrid_report.py",
        TOOL / "meshy_rigidization_notebook.py",
    ]
    for source_path in source_files:
        ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    for index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") == "code":
            ast.parse("".join(cell.get("source", [])), filename=f"{NOTEBOOK}:cell-{index}")
    cells = notebook.get("cells", [])
    if len(cells) not in (5, 6, 7, 8) or (len(cells) in (6, 7, 8) and "".join(cells[-1].get("source", []))):
        raise ValueError("Roc notebook should remain a compact control surface, with at most one trailing empty cell")
    required = (
        "RocHybridConfig",
        "initialize",
        "run_frame0_pilot",
        "run_full_animation",
        "make_asset_picker",
    )
    sources = ["".join(cell.get("source", [])) for cell in cells if cell.get("cell_type") == "code"]
    selector_source = next((source for source in sources if "make_asset_picker" in source), "")
    config_source = next((source for source in sources if "RocHybridConfig" in source), "")
    missing = [name for name in required if name not in config_source and name != "make_asset_picker"]
    if missing:
        raise ValueError(f"notebook is missing runtime imports: {missing}")
    if "make_asset_picker" not in selector_source or "ASSET_PICKER" not in selector_source:
        raise ValueError("notebook is missing the first-cell asset selector")
    required_config = (
        "meshy_rigidization_report",
        "require_meshy_rigidization",
        "rotation_vector_search_enabled",
        "directional_continuation_enabled",
        "bone_twist_policy",
        "semantic_global_batch_size",
        "semantic_dense_batch_size",
        "semantic_branch_bound_enabled",
        "semantic_branch_bound_margin",
        "semantic_candidate_cache_enabled",
        "semantic_candidate_cache_max_entries",
        "clip_sensitivity_enabled",
        "clip_sensitivity_score_epsilon",
        "clip_polish_include_neighbors",
        "CASCADE_JOINT_TEMPORAL_CONSENSUS_BIDIRECTIONAL",
        "CASCADE_JOINT_TEMPORAL_CONSENSUS_IDLE_END",
        "CASCADE_JOINT_TEMPORAL_CONSENSUS_INDEPENDENT_PASSES",
        "CASCADE_JOINT_TEMPORAL_CONSENSUS_WHOLE_POSE",
        "SIMPLE_DEPTH_ROOT_ROTATION_CAMERA_UP_LIMIT_DEG",
        "SIMPLE_DEPTH_ROOT_ROTATION_DEFER_CAMERA_UP",
        "CASCADE_BONE_ORDER_MODE",
    )
    missing_config = [name for name in required_config if name not in config_source]
    if missing_config:
        raise ValueError(f"notebook is missing Meshy rigidization controls: {missing_config}")
    rigidization_source = next(
        (source for source in sources if "RUN_MESHY_RIGIDIZATION" in source),
        "",
    )
    if "run_meshy_rigidization" not in rigidization_source:
        raise ValueError("notebook is missing the separate Meshy rigidization cell")
    print(f"validated {NOTEBOOK.name}: {len(notebook['cells'])} cells; runtime={RUNTIME.name}")


if __name__ == "__main__":
    main()
