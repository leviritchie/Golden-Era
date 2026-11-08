"""Export the explicitly selected current-mocap groups without refitting.

This is a raw adapter for the in-game test lane.  It copies existing baseline
GLBs and serializes only the already-read-back saved skin refits.  It does not
alter geometry, motion, or weights, and its output remains test-only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eagle_glb import matrices_to_xyzw, write_skinned_glb
from glb_skeleton import load_bind_skeleton
from run_attachment_skin_refit import load_refit
from run_skin_mesh_pilot import SOURCE_FRAME_MS, sha256_file
from verify_calibrated_export import verify_calibrated_export, _serialized_local_rotations


SCHEMA = "stronghold-current-mocap-raw-export-v1"
DISPOSITION = "user_requested_ingame_test"


def _resolve(path: str | Path, root: Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else root / value


def _validate_selection(selection: dict[str, Any]) -> None:
    if selection.get("schema") != "stronghold-current-mocap-ingame-test-selection-v1":
        raise ValueError("unsupported current-mocap selection schema")
    if selection.get("accepted") is not False or selection.get("disposition") != DISPOSITION:
        raise ValueError("raw export requires an unaccepted user-requested test selection")
    units = selection.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("selection has no units")
    seen = set()
    for unit in units:
        if not isinstance(unit, dict):
            raise ValueError("selection unit is not an object")
        sid = unit.get("gameSid")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError("selection has duplicate or invalid gameSid")
        seen.add(sid)
        if unit.get("disposition") != DISPOSITION:
            raise ValueError(f"unit {sid} has an invalid disposition")
        if unit.get("kind") not in {"baseline_glb", "saved_skin_refit"}:
            raise ValueError(f"unit {sid} has an unsupported export kind")
        for key in ("labSid", "bundleName", "assetId", "fitReport", "sourceReport", "sourceReportSha256"):
            if not isinstance(unit.get(key), str) or not unit[key]:
                raise ValueError(f"unit {sid} lacks {key}")


def _validate_raw_glb(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    skeleton = load_bind_skeleton(path)
    times, _, _, channel_info = _serialized_local_rotations(path)
    if len(times) < 1 or not np.isfinite(times).all():
        raise ValueError(f"GLB has invalid animation timing: {path}")
    if skeleton.vertices is None or skeleton.triangles is None:
        raise ValueError(f"GLB has no skinned mesh: {path}")
    return {
        "ok": True,
        "proof": "serialized-structure-check",
        "frameCount": int(len(times)),
        "jointCount": int(len(skeleton.names)),
        "vertexCount": int(len(skeleton.vertices)),
        "triangleCount": int(len(skeleton.triangles)),
        "channelInfo": channel_info,
    }


def _deform(vertices: np.ndarray, weights: np.ndarray, worlds: np.ndarray, inverse_bind: np.ndarray) -> np.ndarray:
    transforms = worlds @ inverse_bind[None]
    blended = np.einsum("vj,tjkl->tvkl", weights, transforms[:, :, :3, :], optimize=True)
    homogeneous = np.concatenate((vertices, np.ones((len(vertices), 1), dtype=vertices.dtype)), axis=1)
    return np.einsum("tvkl,vl->tvk", blended, homogeneous, optimize=True)


def _export_saved_refit(unit: dict[str, Any], root: Path, output: Path) -> list[dict[str, Any]]:
    fit_dir = _resolve(unit["fitReport"], root).parent
    source_report = _resolve(unit["sourceReport"], root)
    if sha256_file(source_report).lower() != unit["sourceReportSha256"].lower():
        raise ValueError(f"source report hash drift for {unit['gameSid']}")
    report, _repair, original, candidate, motions = load_refit(source_report, unit["assetId"], fit_dir)
    if not np.array_equal(candidate["vertices"], original["vertices"]):
        raise ValueError("saved refit changed rest vertices")
    if not np.array_equal(candidate["triangles"], original["triangles"]):
        raise ValueError("saved refit changed topology")
    rows = []
    group_dir = output / unit["gameSid"]
    group_dir.mkdir(parents=True, exist_ok=False)
    for case, motion in motions.items():
        rotations = np.asarray(motion["localRotation"])
        worlds = np.asarray(motion["jointWorld"])
        if rotations.ndim != 4 or worlds.ndim != 4 or len(rotations) != len(worlds):
            raise ValueError(f"invalid saved motion for {unit['gameSid']}:{case}")
        times = np.arange(len(rotations), dtype=np.float32) * (SOURCE_FRAME_MS / 1000.0)
        expected = _deform(candidate["vertices"], candidate["weights"], worlds, candidate["inverseBind"])
        path = group_dir / f"{case}.glb"
        write_skinned_glb(path, names=list(candidate["names"]), parents=candidate["parents"],
                          rest_local_rotation=np.repeat(np.eye(3)[None], len(candidate["names"]), axis=0),
                          rest_local_translation=candidate["offsets"], inverse_bind=candidate["inverseBind"],
                          vertices=candidate["vertices"], triangles=candidate["triangles"], uvs=candidate["uvs"],
                          albedo=candidate["albedo"], weights=candidate["weights"],
                          animation={"name": "fixed_motion_saved_refit", "times": times,
                                     "rotations": matrices_to_xyzw(rotations)})
        parity = verify_calibrated_export(path, expected_meshes=expected, expected_times=times,
                                          idle_frame=0 if motion.get("clipFrame0IsBind") else None)
        rows.append({"groupId": case, "glb": path.relative_to(output).as_posix(),
                     "sourceReportSha256": unit["sourceReportSha256"], "structuralCheck": parity})
    return rows


def _export_baseline(unit: dict[str, Any], root: Path, output: Path) -> list[dict[str, Any]]:
    source_report = _resolve(unit["sourceReport"], root)
    if sha256_file(source_report).lower() != unit["sourceReportSha256"].lower():
        raise ValueError(f"source report hash drift for {unit['gameSid']}")
    report = json.loads(source_report.read_text(encoding="utf-8"))
    cases = report.get("cases")
    if not isinstance(cases, dict) or not cases:
        raise ValueError(f"baseline report has no cases: {source_report}")
    group_dir = output / unit["gameSid"]
    group_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for case, data in cases.items():
        source = Path(data.get("exportParity", {}).get("glb", ""))
        if not source.is_absolute():
            source = _resolve(source, root)
        check = _validate_raw_glb(source)
        destination = group_dir / f"{case}.glb"
        shutil.copy2(source, destination)
        rows.append({"groupId": case, "glb": destination.relative_to(output).as_posix(),
                     "sourceGlbSha256": sha256_file(source),
                     "sourceReportSha256": unit["sourceReportSha256"], "structuralCheck": check})
    return rows


def export_selection(selection_path: Path, output: Path, *, repo_root: Path | None = None) -> dict[str, Any]:
    """Export the selection to a fresh raw test directory and return its manifest."""
    started = time.perf_counter()
    selection_path = Path(selection_path).resolve()
    root = Path(repo_root or selection_path.parents[2]).resolve()
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    _validate_selection(selection)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    units = []
    for unit in selection["units"]:
        rows = (_export_saved_refit if unit["kind"] == "saved_skin_refit" else _export_baseline)(unit, root, output)
        units.append({"gameSid": unit["gameSid"], "labSid": unit["labSid"], "bundleName": unit["bundleName"],
                      "assetId": unit["assetId"], "kind": unit["kind"], "sourceReport": unit["sourceReport"],
                      "sourceReportSha256": unit["sourceReportSha256"], "qualityWarnings": unit.get("qualityWarnings", []),
                      "disposition": DISPOSITION, "groups": rows})
    result = {"schema": SCHEMA, "selection": str(selection_path),
              "selectionSha256": sha256_file(selection_path), "disposition": DISPOSITION,
              "accepted": False, "units": units,
              "elapsedSeconds": time.perf_counter() - started}
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_selection(args.selection, args.output), indent=2))
