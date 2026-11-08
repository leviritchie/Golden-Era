"""Build one continuous DEF sprite timeline with per-frame clip provenance, for any unit.

The reel is derived, not authored: every clip in the unit's corpus manifest
whose DEF group has an OE-native clip contract (`CONTRACT_SUFFIX_BY_GROUP` in
tools/homm3_silhouette_pose_fit/gpu_cascade_delivery.py) is included exactly
once as a full cycle; everything else (turns, vertical attacks, unused groups)
is recorded under `skippedClips` and never captured, as is a shoot group the unit
config's "skipDefGroups" names (tools/homm3_def_retarget/skip_def_groups.py). Between action clips a
short idle bookend (default one frame) gives the mocap model a return-to-rest
anchor so clips do not bleed into each other.

Reel order: idle (full cycle) -> move start -> move -> move end -> idle bookend
-> [each remaining native action in DEF-group order, idle bookend before each]
-> death last. Idle's full cycle is placed first because the capture model
anchors on the opening pose.

Capacity: the vendor mocap model can only produce as many frames as the donor
package's pose dummy holds, and its truncation step drops one frame, so the
whole reel must fit `effective_capture_capacity(package)`. A reel that does not
fit fails closed; capture is never chunked or stitched.

Each output frame records which in-game clip (gXX_name), DEF group, local frame
index, and segment role it came from, plus the global index used by mocap,
skinning, and per-clip export.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from paths import REPO
from pin import sha256_file

_TOOL = REPO / "tools" / "homm3_silhouette_pose_fit"
if str(_TOOL) not in sys.path:
    sys.path.insert(0, str(_TOOL))
from gpu_cascade_delivery import CONTRACT_SUFFIX_BY_GROUP, SKIPPED_DEF_GROUPS  # noqa: E402

_RETARGET = REPO / "tools" / "homm3_def_retarget"
if str(_RETARGET) not in sys.path:
    sys.path.insert(0, str(_RETARGET))
import skip_def_groups  # noqa: E402

SCHEMA = "homm3.linked-master-sequence.v2"
CAPTURE_SCHEMA = "homm3.linked-master-capture.v2"
IDLE_GROUP = 2
MOVE_GROUP = 0
MOVE_START_GROUP = 20
MOVE_END_GROUP = 21
DEATH_GROUP = 5
# Groups every mobile unit must ship; a manifest without them cannot build a reel.
REQUIRED_GROUPS = frozenset({IDLE_GROUP, MOVE_GROUP})
# Observed vendor behaviour: `[Truncate] position_seq N -> N-1` when the reel
# fills the donor pose dummy exactly, so one frame of capacity is unusable.
POSE_CAPACITY_TRUNCATION = 1
ROLE_CYCLE = "cycle"
ROLE_BOOKEND = "bookend"
UNIT_SID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    unit = payload.get("unit")
    if not isinstance(unit, str) or not UNIT_SID_RE.fullmatch(unit):
        raise ValueError(f"manifest unit must be a unit sid, got {unit!r}")
    clips = payload.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError("manifest has no clips")
    seen: set[str] = set()
    for clip in clips:
        key = clip.get("key")
        group = clip.get("group")
        frames = clip.get("frames")
        if not isinstance(key, str) or key in seen:
            raise ValueError(f"manifest clip key {key!r} is missing or duplicated")
        if not isinstance(group, int):
            raise ValueError(f"manifest clip {key} has no integer DEF group")
        if not isinstance(frames, list) or not frames:
            raise ValueError(f"manifest clip {key} has no frames")
        seen.add(key)
    return payload


def effective_capture_capacity(package: dict[str, Any]) -> int:
    """Frames one vendor capture can return for this unit's frozen donor package."""
    import numpy as np

    pose_len = int(np.asarray(package["posePosition"]).shape[0])
    capacity = pose_len - POSE_CAPACITY_TRUNCATION
    if capacity < 2:
        raise ValueError(f"donor pose dummy holds {pose_len} frames; too short for a reel")
    return capacity


def native_reel(
    manifest: dict[str, Any],
    *,
    idle_bookend_frames: int,
    allow_missing_move: bool = False,
    unit_skips: dict[int, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Derive (reel, skipped) from the manifest's DEF groups and the native clip contract.

    `unit_skips` ({DEF group: reason}) defaults to the unit config's "skipDefGroups" (skip_def_groups.for_unit):
    a shoot group the unit never plays is recorded under skipped with its reason and never captured."""
    if unit_skips is None:
        unit_skips = skip_def_groups.for_unit(str(manifest["unit"]))
    if int(idle_bookend_frames) < 1:
        raise ValueError("idle_bookend_frames must be at least 1")
    by_group: dict[int, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    for clip in manifest["clips"]:
        group = int(clip["group"])
        if group in unit_skips:
            skipped.append({"clipKey": clip["key"], "defGroup": group, "reason": "unit_skip_def_group",
                            "unitReason": unit_skips[group]})
            continue
        if group not in CONTRACT_SUFFIX_BY_GROUP:
            reason = "skipped_def_group" if group in SKIPPED_DEF_GROUPS else "no_native_clip_contract"
            skipped.append({"clipKey": clip["key"], "defGroup": group, "reason": reason})
            continue
        if group in by_group:
            raise ValueError(f"manifest has two clips for DEF group {group}: {by_group[group]['key']} and {clip['key']}")
        by_group[group] = clip
    missing = sorted(REQUIRED_GROUPS - set(by_group))
    if missing == [MOVE_GROUP] and allow_missing_move and IDLE_GROUP in by_group:
        by_group[MOVE_GROUP] = dict(by_group[IDLE_GROUP])
        skipped.append(
            {
                "clipKey": by_group[IDLE_GROUP]["key"],
                "defGroup": MOVE_GROUP,
                "reason": "copied_idle_into_missing_move_group",
            }
        )
        missing = []
    if missing:
        raise ValueError(f"manifest {manifest['unit']} lacks required native groups {missing}")

    def entry(group: int, role: str) -> dict[str, Any]:
        clip = by_group[group]
        limit = int(idle_bookend_frames) if role == ROLE_BOOKEND else None
        return {
            "clipKey": clip["key"],
            "defGroup": group,
            "contractSuffix": CONTRACT_SUFFIX_BY_GROUP[group],
            "role": role,
            "frameLimit": limit,
        }

    reel: list[dict[str, Any]] = [entry(IDLE_GROUP, ROLE_CYCLE)]
    for group in (MOVE_START_GROUP, MOVE_GROUP, MOVE_END_GROUP):
        if group in by_group:
            reel.append(entry(group, ROLE_CYCLE))
    chain_groups = {IDLE_GROUP, MOVE_START_GROUP, MOVE_GROUP, MOVE_END_GROUP, DEATH_GROUP}
    for group in sorted(g for g in by_group if g not in chain_groups):
        reel.append(entry(IDLE_GROUP, ROLE_BOOKEND))
        reel.append(entry(group, ROLE_CYCLE))
    if DEATH_GROUP in by_group:
        reel.append(entry(IDLE_GROUP, ROLE_BOOKEND))
        reel.append(entry(DEATH_GROUP, ROLE_CYCLE))
    return reel, sorted(skipped, key=lambda row: row["defGroup"])


def reel_frame_count(reel: list[dict[str, Any]], manifest: dict[str, Any]) -> int:
    by_key = {str(clip["key"]): clip for clip in manifest["clips"]}
    total = 0
    for row in reel:
        count = len(by_key[row["clipKey"]]["frames"])
        if row["frameLimit"] is not None:
            count = min(count, int(row["frameLimit"]))
        total += count
    return total


def build_master_sequence(
    manifest_path: Path,
    output_dir: Path,
    *,
    pose_capacity: int,
    idle_bookend_frames: int = 1,
    bind_group: int = MOVE_GROUP,
    bind_local_frame: int = 0,
    overwrite: bool = False,
    allow_missing_move: bool = False,
) -> dict[str, Any]:
    """Materialize numbered PNGs and a master manifest with clip segment ranges."""
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"refusing to overwrite {output_dir} (pass overwrite=True)")
        shutil.rmtree(output_dir)
    manifest = load_manifest(manifest_path)
    unit = str(manifest["unit"])
    reel, skipped = native_reel(
        manifest,
        idle_bookend_frames=idle_bookend_frames,
        allow_missing_move=allow_missing_move,
    )
    expected_frames = reel_frame_count(reel, manifest)
    if expected_frames > int(pose_capacity):
        raise ValueError(
            f"{unit} native reel has {expected_frames} frames but one capture can return {pose_capacity}; "
            "capture is never chunked - reduce idle bookends or drop optional native clips explicitly"
        )
    by_key = {str(clip["key"]): clip for clip in manifest["clips"]}
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True)
    global_frames: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    global_index = 0
    bind_global_index: int | None = None
    for segment_index, row in enumerate(reel):
        clip = by_key[row["clipKey"]]
        paths = [Path(p) for p in clip["frames"]]
        if row["frameLimit"] is not None:
            paths = paths[: int(row["frameLimit"])]
        start = global_index
        for local_index, src in enumerate(paths):
            if not src.is_file():
                raise FileNotFoundError(src)
            dest = frames_dir / f"{global_index:06d}.png"
            shutil.copy2(src, dest)
            global_frames.append(
                {
                    "globalIndex": global_index,
                    "segmentIndex": segment_index,
                    "clipKey": row["clipKey"],
                    "defGroup": row["defGroup"],
                    "role": row["role"],
                    "localIndex": local_index,
                    "sourcePng": str(src).replace("\\", "/"),
                    "sourceSha256": sha256_file(src),
                    "numberedPng": str(dest).replace("\\", "/"),
                }
            )
            if (
                bind_global_index is None
                and row["role"] == ROLE_CYCLE
                and row["defGroup"] == int(bind_group)
                and local_index == int(bind_local_frame)
            ):
                bind_global_index = global_index
            global_index += 1
        segments.append(
            {
                **row,
                "segmentIndex": segment_index,
                "globalStart": start,
                "globalEnd": global_index,
                "frameCount": global_index - start,
                "sourceClipFrameCount": len(clip["frames"]),
                "exportsClip": row["role"] == ROLE_CYCLE,
            }
        )
    if bind_global_index is None:
        raise RuntimeError(f"bind group {bind_group} local frame {bind_local_frame} is not a cycle frame of the reel")
    if global_index != expected_frames:
        raise RuntimeError(f"built {global_index} frames, expected {expected_frames}")
    exported = [s["defGroup"] for s in segments if s["exportsClip"]]
    if len(exported) != len(set(exported)):
        raise RuntimeError("a native clip would be exported twice")
    result = {
        "schema": SCHEMA,
        "reelPolicy": "native_contract_groups_once_each_with_idle_bookends",
        "idleBookendFrames": int(idle_bookend_frames),
        "poseCapacity": int(pose_capacity),
        "unit": unit,
        "manifest": str(manifest_path.resolve()).replace("\\", "/"),
        "manifestSha256": sha256_file(manifest_path),
        "frameCount": global_index,
        "bindGroup": int(bind_group),
        "bindLocalFrame": int(bind_local_frame),
        "bindGlobalIndex": bind_global_index,
        "skippedClips": skipped,
        "reel": reel,
        "segments": segments,
        "frames": global_frames,
        "framesDir": str(frames_dir.resolve()).replace("\\", "/"),
        "sourceFrameMs": float(manifest.get("sourceFrameMs", 1000 / 12)),
    }
    _write_json(output_dir / "master_sequence.json", result)
    return result


def load_master_sequence(master_dir: Path) -> dict[str, Any]:
    master_path = master_dir / "master_sequence.json"
    if not master_path.is_file():
        raise FileNotFoundError(f"missing {master_path}")
    master = json.loads(master_path.read_text(encoding="utf-8"))
    if master.get("schema") != SCHEMA:
        raise ValueError(f"{master_path} has schema {master.get('schema')!r}, expected {SCHEMA}")
    return master


def all_sequence_indices(master: dict[str, Any]) -> list[int]:
    """Every master frame is a simultaneous skin-objective sample after bind."""
    frames = [int(row["globalIndex"]) for row in master["frames"]]
    if not frames:
        raise ValueError("master sequence produced zero frames")
    if frames != list(range(len(frames))):
        raise ValueError("master frames must be contiguous global indices from 0")
    return frames


def export_segments(master: dict[str, Any]) -> list[dict[str, Any]]:
    """Segments that become per-clip GLBs (full cycles), in reel order."""
    return [segment for segment in master["segments"] if segment["exportsClip"]]


def capture_master_sequence(
    master_dir: Path,
    output_dir: Path,
    *,
    device: str = "cuda",
    overwrite: bool = False,
    package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one vendor capture over the full linked master reel (no chunk stitching)."""
    import numpy as np
    import torch

    from capture_candidates import require_frozen_package
    from intermediate_capture import encode_sprite_vendor, run_capture
    from model_runner import load_model
    from paths import MAX_SEQ_LEN
    from run_mocap_baseline import _gpu_lock_waiting

    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"refusing to overwrite {output_dir} (pass overwrite=True)")
        shutil.rmtree(output_dir)
    master = load_master_sequence(master_dir)
    unit = str(master["unit"])
    frames_dir = Path(master["framesDir"])
    numbered = sorted(frames_dir.glob("*.png"))
    frame_count = len(numbered)
    if frame_count != int(master["frameCount"]):
        raise ValueError(f"expected {master['frameCount']} numbered frames, found {frame_count}")
    if frame_count > MAX_SEQ_LEN:
        raise ValueError(f"master has {frame_count} frames; vendor cap is {MAX_SEQ_LEN}")
    if package is None:
        package = require_frozen_package(unit, role="primary")
    capacity = effective_capture_capacity(package)
    if frame_count > capacity:
        raise ValueError(f"master has {frame_count} frames; {unit} donor capture capacity is {capacity}")
    if int(master["poseCapacity"]) != capacity:
        raise ValueError(
            f"master was built for capacity {master['poseCapacity']} but the frozen {unit} package gives {capacity}"
        )
    output_dir.mkdir(parents=True)
    started_total = time.perf_counter()
    with _gpu_lock_waiting(REPO):
        encode_started = time.perf_counter()
        embeds, preprocess = encode_sprite_vendor(
            numbered, device=device, encoder_input_dir=output_dir / "encoder_cache"
        )
        encode_seconds = time.perf_counter() - encode_started
        model_started = time.perf_counter()
        model = load_model(torch.device(device))[0]
        model_load_seconds = time.perf_counter() - model_started
        capture_started = time.perf_counter()
        capture_report = run_capture(
            package=package,
            frames_dir=frames_dir,
            out_dir=output_dir / "capture",
            image_embed=embeds,
            preprocess_meta=preprocess,
            model=model,
            source_kind="authored_source_frame",
            title=f"{unit}_linked_master",
            compare_gt=False,
        )
        capture_seconds = time.perf_counter() - capture_started
    capture_path = (output_dir / "capture" / "raw_capture.npz").resolve()
    with np.load(capture_path, allow_pickle=False) as raw:
        captured_frames = int(np.asarray(raw["pred_position"]).shape[0])
    if captured_frames != frame_count:
        raise RuntimeError(f"capture returned {captured_frames} frames for a {frame_count}-frame reel")
    result = {
        "schema": CAPTURE_SCHEMA,
        "unit": unit,
        "masterSequence": str((master_dir / "master_sequence.json").resolve()).replace("\\", "/"),
        "masterSequenceSha256": sha256_file(master_dir / "master_sequence.json"),
        "frameCount": frame_count,
        "bindGlobalIndex": int(master["bindGlobalIndex"]),
        "poseCapacity": capacity,
        "capturePolicy": "single_window_no_stitch",
        "capture": str(capture_path).replace("\\", "/"),
        "captureSha256": sha256_file(capture_path),
        "package": {
            "kind": package["kind"],
            "refSeq": package["refSeq"],
            "candidateRole": package.get("candidateRole"),
        },
        "preprocess": preprocess,
        "captureReport": capture_report,
        "timings": {
            "encodeSeconds": encode_seconds,
            "modelLoadSeconds": model_load_seconds,
            "captureSeconds": capture_seconds,
            "elapsedTotalSeconds": time.perf_counter() - started_total,
        },
    }
    _write_json(output_dir / "capture_report.json", result)
    return result
