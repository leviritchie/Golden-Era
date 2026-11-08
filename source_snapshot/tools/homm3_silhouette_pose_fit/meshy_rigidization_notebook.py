"""Notebook preflight for the Meshy-preserving rigidization pass.

The notebook calls this module from a dedicated cell.  It derives generated
paths from the selected GLB, runs the existing host wrapper, and returns the
audited output so the following optimizer cell can consume it.  The Meshy
source is never overwritten.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from pose_fit_blender import resolve_pose_fit_blender


ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent
RIGIDIZATION_WRAPPER = TOOL_DIR / "run_meshy_rigidization.py"
DEFAULT_CONFIG = TOOL_DIR / "configs" / "meshy_rigidization_default.json"
REPORT_NAME = "meshy_rigidization_report.json"


def _resolve(path: Path, *, root: Path = ROOT) -> Path:
    candidate = Path(path).expanduser()
    return (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()


def _without_rigidized_suffix(path: Path) -> Path:
    suffix = "_rigidized"
    if path.stem.lower().endswith(suffix):
        return path.with_name(path.stem[: -len(suffix)] + path.suffix)
    return path


def rigidization_paths(selected_mesh: Path, config_path: Path | None = None) -> dict[str, Path]:
    """Derive source, output, report, and policy paths for a selected GLB."""
    selected = _resolve(selected_mesh)
    if not selected.is_file():
        raise FileNotFoundError(f"selected Meshy GLB is missing: {selected}")
    if selected.suffix.lower() != ".glb":
        raise ValueError(f"selected Meshy asset is not a GLB: {selected}")

    if selected.stem.lower().endswith("_rigidized"):
        source = _without_rigidized_suffix(selected)
        if not source.is_file():
            raise FileNotFoundError(
                "selected rigidized GLB has no adjacent raw Meshy source: "
                f"{source}"
            )
        output = selected
    else:
        source = selected
        output = selected.with_name(f"{selected.stem}_rigidized{selected.suffix}")

    policy = _resolve(config_path or DEFAULT_CONFIG)
    if not policy.is_file():
        raise FileNotFoundError(f"Meshy rigidization policy is missing: {policy}")
    return {
        "selected": selected,
        "source": source,
        "output": output,
        "report": selected.parent / REPORT_NAME,
        "config": policy,
    }


def _passing_report(paths: dict[str, Path]) -> dict[str, Any] | None:
    report_path = paths["report"]
    output_path = paths["output"]
    if not report_path.is_file() or not output_path.is_file():
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema") != "meshy_rigidization_report.v1":
        return None
    if payload.get("status") != "pass":
        return None
    reported_output = Path(str(payload.get("output", "")))
    if not reported_output.is_absolute():
        reported_output = report_path.parent / reported_output
    if reported_output.resolve() != output_path.resolve():
        return None
    return payload


def run_meshy_rigidization(
    selected_mesh: Path,
    *,
    config_path: Path | None = None,
    blender_path: Path | None = None,
    reuse_passing: bool = True,
    overwrite: bool = False,
    allow_ambiguous: bool = False,
) -> dict[str, Any]:
    """Run or reuse the audited rigidized artifact for a selected Meshy GLB."""
    paths = rigidization_paths(selected_mesh, config_path)
    existing = _passing_report(paths) if reuse_passing else None
    if existing is not None:
        return {
            "status": "reused",
            "ran": False,
            "source": str(paths["source"]),
            "output": str(paths["output"]),
            "report": str(paths["report"]),
            "config": str(paths["config"]),
            "payload": existing,
        }

    if paths["output"].exists() and not overwrite:
        raise FileExistsError(
            "rigidized output already exists but has no reusable passing report: "
            f"{paths['output']}. Set MESHY_RIGIDIZATION_OVERWRITE=True to replace the generated output."
        )

    blender = resolve_pose_fit_blender(blender_path)
    command = [
        sys.executable,
        str(RIGIDIZATION_WRAPPER),
        "--src",
        str(paths["source"]),
        "--out",
        str(paths["output"]),
        "--report",
        str(paths["report"]),
        "--config",
        str(paths["config"]),
        "--blender",
        str(blender),
    ]
    if overwrite:
        command.append("--overwrite")
    if allow_ambiguous:
        command.append("--allow-ambiguous")

    print("running Meshy rigidization:")
    print(" ".join(f'"{part}"' if " " in part else part for part in command))
    completed = subprocess.run(command, cwd=str(ROOT), check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            "Meshy rigidization failed with exit code "
            f"{completed.returncode}; inspect the Blender output above"
        )
    payload = _passing_report(paths)
    if payload is None:
        raise RuntimeError(
            "Meshy rigidization completed without a passing report for "
            f"{paths['output']}"
        )
    return {
        "status": "ran",
        "ran": True,
        "source": str(paths["source"]),
        "output": str(paths["output"]),
        "report": str(paths["report"]),
        "config": str(paths["config"]),
        "payload": payload,
    }
