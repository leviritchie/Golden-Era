"""ipywidgets asset picker for the semantic/depth hybrid pose experiment.

The picker lists authentic 12 fps lab DEFs first. Ship sequences are
idle-leading (idle first, and trailing idle except death). Each of those
also has a motion-only diagnostic counterpart with idle stripped; that
choice writes a separate folder and starts from bind. Only groups that
exist on that unit's ``extracted_battle_source_12fps`` directory are
selectable. Empty alt DEFs and RIFE interpolated plates stay unlisted.
Pipeline inventories remain as leftovers for units that have no authentic
12 fps lab DEF.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any, Sequence

from materialize_rife_source_frames import (
    IDLE_GROUP,
    def_sequence_animation_name,
    def_sequence_choice_id,
    def_group_name,
    ensure_def_nn_upscale_meta,
    idle_leading_def_sequences,
    inventory_authentic_def_groups,
    load_nn_upscale_contract,
    motion_only_def_sequences,
    resolve_nn_upscale_meta_for_source,
    pose_sequence_kind,
)


_FRAME_NAME = re.compile(r"^(?:frame_)?(\d+)\.png$", re.IGNORECASE)
_GROUP_FRAME_NAME = re.compile(r"^(\d{2})_(\d{2})\.png$", re.IGNORECASE)
_ANIMATION_SOURCE_DIR = re.compile(r"^nn_upscale_g\d{2}(?:_|$)", re.IGNORECASE)
_GROUP_SOURCE_DIR = re.compile(r"^group_\d+$", re.IGNORECASE)
_AGGREGATE_SOURCE_DIRS = frozenset({"native", "nn_upscale", "nn_upscale_seq"})
_SKIP_MESH_PARTS = {
    "out_fit",
    "out_attack",
    "out_articulation_motion_g11",
    "out_frame0_method_sweep",
    "out_dense_skeleton_g11",
    "out_meshy_t2_per_frame_g11",
    "out_sprite_motion_track_g11",
    "out_full_animation",
    "renders",
    "review",
    "preview",
    "pose_picker_runs",
    "_scratch",
    "pseudo_rig",
    "redownload_verify",
}


@dataclass(frozen=True)
class RocAssetChoice:
    unit_name: str
    unit_sid: str
    animation_name: str
    choice_id: str
    pilot_dir: Path
    camera_fit: Path
    frame_indices: tuple[int, ...]
    default_mesh: Path | None
    source_frames: tuple[Path, ...] = ()
    camera_metadata: dict[str, Any] | None = None
    source_label: str = ""
    provisional_camera: bool = False
    source_kind: str = "pipeline"
    def_lab_frame_dir: Path | None = None
    def_lab_groups: tuple[int, ...] = ()
    def_expected_counts: tuple[int, ...] = ()
    present_groups: tuple[int, ...] = ()
    sequence_kind: str = "pipeline"

    @property
    def label(self) -> str:
        if self.source_kind == "authentic_def":
            names = " → ".join(def_group_name(group) for group in self.def_lab_groups)
            if self.sequence_kind == "motion_only":
                return (
                    f"{names} ({len(self.frame_indices)} authentic 12 fps frames; "
                    "motion-only diagnostic, starts from bind)"
                )
            return f"{names} ({len(self.frame_indices)} authentic 12 fps frames; idle first)"
        camera_note = "; provisional camera" if self.provisional_camera else ""
        return f"{self.animation_name} ({len(self.frame_indices)} source frames{camera_note})"


_MESHY_RIGIDIZATION_REPORT_NAME = "meshy_rigidization_report.json"


def meshy_rigidization_report_for(mesh: Path) -> Path | None:
    """Return the adjacent Meshy audit report, if one exists.

    Rigidization emits a fixed report name beside the audited GLB. Resolving
    this from the selected mesh keeps the notebook independent of unit names
    and prevents a documentation placeholder such as ``<unit>`` from being
    treated as a literal directory.
    """
    mesh_path = Path(mesh).expanduser().resolve()
    report = mesh_path.parent / _MESHY_RIGIDIZATION_REPORT_NAME
    return report if report.is_file() else None


def meshy_rigidization_status(mesh: Path) -> tuple[str, Path | None]:
    """Return a lightweight picker status for the selected Meshy GLB."""
    mesh_path = Path(mesh).expanduser().resolve()
    report = meshy_rigidization_report_for(mesh_path)
    if report is None:
        return "missing", None
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid", report
    if payload.get("status") != "pass":
        return str(payload.get("status") or "not-passing"), report
    output_value = payload.get("output")
    if not output_value:
        return "missing-output", report
    output_path = Path(str(output_value))
    if not output_path.is_absolute():
        output_path = report.parent / output_path
    if output_path.resolve() != mesh_path:
        return "wrong-output", report
    return "pass", report


def _frame_index(path: Path) -> int | None:
    match = _FRAME_NAME.match(path.name)
    return int(match.group(1)) if match else None


def _source_frame_paths(directory: Path) -> tuple[Path, ...]:
    """Return numbered source frames while ignoring contact sheets and GIFs."""
    if not directory.is_dir():
        return ()
    indexed: dict[int, Path] = {}
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        index = _frame_index(path)
        if index is not None:
            indexed.setdefault(index, path)
    return tuple(indexed[index] for index in sorted(indexed))


def _frame_indices(directory: Path) -> tuple[int, ...]:
    return tuple(range(len(_source_frame_paths(directory))))


def _aggregate_source_frames(directory: Path) -> tuple[tuple[int, tuple[Path, ...]], ...]:
    """Split an aggregate DEF export such as ``00_00.png`` by group/frame.

    Some units are stored as one original-frame directory rather than one
    directory per animation. The first number is the HoMM3 animation group;
    the second is the frame within that group. This is still the original
    source lane, not an interpolation lane.
    """
    groups: dict[int, dict[int, Path]] = {}
    if not directory.is_dir():
        return ()
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        match = _GROUP_FRAME_NAME.match(path.name)
        if not match:
            continue
        group_index, frame_index = (int(value) for value in match.groups())
        groups.setdefault(group_index, {}).setdefault(frame_index, path)
    return tuple(
        (group_index, tuple(frames[index] for index in sorted(frames)))
        for group_index, frames in sorted(groups.items())
        if frames
    )


def _unit_name(unit_sid: str, directory_name: str) -> str:
    value = str(unit_sid or "").strip()
    if value.lower() in {"h3_roc", "roc"}:
        return "roc"
    if value.lower().startswith("h3_"):
        return value[3:]
    if value:
        return value
    value = directory_name.removesuffix("_pose_pipeline")
    return value or directory_name


def _animation_name(clip: str, directory_name: str) -> str:
    value = str(clip or directory_name).strip()
    value = re.sub(r"_rife$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"_(?:fixed_length|authored|minimal|ground_truth)$", "", value, flags=re.IGNORECASE)
    match = re.fullmatch(r"g(\d+)(?:_(.+))?", value, flags=re.IGNORECASE)
    if match:
        suffix = match.group(2)
        return f"{suffix}_g{int(match.group(1))}" if suffix else f"g{int(match.group(1))}"
    return value


def _animation_from_source_dir(directory_name: str) -> str:
    value = directory_name.lower()
    if _GROUP_SOURCE_DIR.fullmatch(value):
        return f"attack_g{int(value.split('_', 1)[1])}"
    match = re.search(r"_g(\d{2})(?:_(.+))?$", value)
    if match:
        suffix = match.group(2)
        return f"{suffix}_g{int(match.group(1))}" if suffix else f"g{int(match.group(1))}"
    if value.startswith("nn_upscale_"):
        return value.removeprefix("nn_upscale_")
    return directory_name


def _animation_from_group_index(group_index: int) -> str:
    name = def_group_name(int(group_index))
    if name.startswith("group_"):
        return f"g{int(group_index)}"
    return f"{name}_g{int(group_index)}"


def _group_index_from_animation(animation_name: str) -> int | None:
    match = re.search(r"_g(\d+)$", str(animation_name), flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.fullmatch(r"g(\d+)", str(animation_name), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _groups_from_choice_id(choice_id: str) -> tuple[int, ...] | None:
    animation = str(choice_id).split(":", 1)[-1]
    if re.fullmatch(r"(?:g\d+)(?:-g\d+)+", animation, flags=re.IGNORECASE):
        return tuple(int(part[1:]) for part in animation.split("-"))
    group = _group_index_from_animation(animation)
    return (group,) if group is not None else None


def remap_isolated_choice_id_to_idle_leading(
    choice_id: str,
    available_ids: Sequence[str],
) -> str:
    """Map leftover isolated clip ids onto idle-leading sequences.

    Isolated walk or attack clips start from bind. The idle-leading dropdown
    already concatenates idle in front; restoring an old ``move_g0`` or
    ``attack_down_g13`` selection has to land on that concatenated sequence,
    not silently keep the isolated folder.
    """
    requested = str(choice_id)
    available = tuple(str(value) for value in available_ids)
    if requested in available:
        return requested
    groups = _groups_from_choice_id(requested)
    unit_sid = requested.split(":", 1)[0]
    target_group = None if groups is None else int(groups[-1])
    if target_group is None:
        return requested
    candidates: list[tuple[tuple[int, ...], str]] = []
    for value in available:
        if not value.startswith(f"{unit_sid}:"):
            continue
        sequence = _groups_from_choice_id(value)
        if sequence is None or sequence[0] != IDLE_GROUP or len(sequence) < 2:
            continue
        candidates.append((sequence, value))
    if target_group in {0, 1, 2, 20}:
        for sequence, value in candidates:
            if 0 in sequence or 1 in sequence:
                return value
    exact = (IDLE_GROUP, target_group)
    exact_return = exact + (IDLE_GROUP,)
    for sequence, value in candidates:
        if sequence == exact or sequence == exact_return:
            return value
    for sequence, value in candidates:
        if target_group in sequence:
            return value
    if target_group in {11, 13}:
        for sequence, value in candidates:
            if 12 in sequence:
                return value
    return requested


def _is_animation_source_dir(path: Path) -> bool:
    name = path.name
    lower = name.lower()
    if "rife" in lower or "canonical" in lower:
        return False
    return bool(
        _ANIMATION_SOURCE_DIR.match(name)
        or _GROUP_SOURCE_DIR.fullmatch(name)
        or lower == "nn_upscale_idle_attack"
        or lower in _AGGREGATE_SOURCE_DIRS
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _resolve_path(value: str | Path, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def _job_paths(pipeline_root: Path) -> tuple[Path, ...]:
    roots = [pipeline_root / "out_fit", pipeline_root / "out_attack_g11"]
    paths: list[Path] = []
    for root in roots:
        if root.is_dir():
            paths.extend(root.rglob("job.resolved.json"))
    return tuple(sorted(paths, key=lambda path: str(path).lower()))


def _job_source_map(pipeline_root: Path) -> tuple[dict[Path, dict[str, Any]], dict[str, Any] | None]:
    """Map source-frame directories to the least-derived usable job metadata."""
    source_map: dict[Path, dict[str, Any]] = {}
    representative: dict[str, Any] | None = None
    scores: dict[Path, int] = {}
    representative_score = 10_000
    for job_path in _job_paths(pipeline_root):
        job = _read_json(job_path)
        if not job or not job.get("unitSid") or not isinstance(job.get("frames"), list):
            continue
        frames = job["frames"]
        if not frames or not isinstance(frames[0], dict) or not frames[0].get("path"):
            continue
        source_path = _resolve_path(str(frames[0]["path"]), pipeline_root)
        source_dir = source_path.parent
        master = _resolve_path(str(job.get("masterGlb", "")), pipeline_root) if job.get("masterGlb") else None
        metadata = {
            "unitSid": str(job["unitSid"]),
            "camera": dict(job.get("camera") or {}),
            "masterGlb": master,
            "jobPath": job_path,
        }
        job_name = job_path.parent.name.lower()
        score = 0
        for marker in ("_fixed_length", "_authored", "_minimal", "_ground_truth", "_chroma", "_silhouette", "_motionbert", "_dwpose"):
            if marker in job_name:
                score += 10
        if "job.resolved.json" in str(job_path).lower():
            score += len(job_path.parts) // 100
        if source_dir.is_dir() and score < scores.get(source_dir, 10_000):
            source_map[source_dir.resolve()] = metadata
            scores[source_dir.resolve()] = score
        if score < representative_score and (master is None or master.is_file()):
            representative = metadata
            representative_score = score
    return source_map, representative


def _mesh_candidates(pipeline_root: Path) -> list[Path]:
    candidates: set[Path] = set()
    preferred_dirs = (
        pipeline_root / "master",
        pipeline_root / "owned_bind",
        pipeline_root / "out_meshy_t2_idle_f0" / "rigged",
        pipeline_root / "out_meshy_t2_idle_f0" / "meshes",
    )
    for directory in preferred_dirs:
        if directory.is_dir():
            candidates.update(path for path in directory.glob("*.glb") if path.is_file())
    for path in pipeline_root.glob("*.glb"):
        if path.is_file():
            candidates.add(path)
    return sorted(candidates, key=lambda path: str(path).lower())


def _default_mesh(pipeline_root: Path, metadata: dict[str, Any] | None) -> Path | None:
    if metadata:
        master = metadata.get("masterGlb")
        if isinstance(master, Path) and master.is_file():
            return master
    candidates = _mesh_candidates(pipeline_root)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda path: (
            0 if "owned_bind" in str(path).lower() else 1,
            0 if "bridgefix" in path.name.lower() else 1,
            0 if "rigged" in path.name.lower() else 1,
            str(path).lower(),
        ),
    )[0]


def _runtime_paths(root: Path, unit_sid: str, animation_name: str) -> tuple[Path, Path]:
    def slug(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._") or "asset"

    runtime_dir = root / "artifacts" / "pose_picker_runs" / slug(unit_sid) / slug(animation_name)
    return runtime_dir, runtime_dir / "roc_sprite_camera_fit.json"


def homm3_lab_roots(root: Path) -> tuple[Path, ...]:
    """Return lab trees that can hold authentic 12 fps DEF extracts.

    The C# plugin source tree is first. The playtest BepInEx plugin copy is
    second: that is where ``extracted_battle_source_12fps`` actually lives after
    the source-tree ``homm3_lab`` folder was removed. Do not invent a third
    selector, and do not treat a Generated-only tree as an inventory.
    """
    playtest = Path(root) / "Heroes of Might & Magic Olden Era Playtest"
    return (
        playtest / "OfflineUnlockMod" / "homm3_lab",
        playtest / "BepInEx" / "plugins" / "OfflineUnlockMod" / "homm3_lab",
    )


def _lab_has_authentic_12fps(lab: Path) -> bool:
    if not lab.is_dir():
        return False
    try:
        for unit_dir in lab.iterdir():
            if not unit_dir.is_dir():
                continue
            if (unit_dir / "extracted_battle_source_12fps").is_dir():
                return True
    except OSError:
        return False
    return False


def homm3_lab_root(root: Path) -> Path:
    """Return the lab tree that still has authentic 12 fps DEF extracts.

    Prefer ``OfflineUnlockMod/homm3_lab`` when that tree exists. If it is
    missing or only has ``Generated`` sidecars, use the playtest BepInEx
    plugin lab. Callers that check ``is_dir()`` still see the canonical
    source-tree path when neither inventory is present.
    """
    candidates = homm3_lab_roots(root)
    for lab in candidates:
        if _lab_has_authentic_12fps(lab):
            return lab
    return candidates[0]


def _lab_discovery_roots(root: Path) -> tuple[Path, ...]:
    """Return authoritative lab trees, including freshly extracted sources.

    The picker historically consumed the curated ``extracted_battle_source_12fps``
    tree under the playtest project.  Full-set source extraction writes the same
    original DEF plates under the ignored Unity working tree instead.  Treat that
    tree as an explicit third source, after the curated trees, rather than copying
    1+ GB of PNGs or silently promoting a generated/RIFE directory.
    """
    roots = list(homm3_lab_roots(root))
    extracted = (
        Path(root)
        / "oldenera_factions"
        / "Assets"
        / "CustomUnits"
        / "homm3_lab"
    )
    if extracted not in roots:
        roots.append(extracted)
    return tuple(roots)


def _select_lab_def_directory(unit_dir: Path) -> Path | None:
    # Curated 12 fps materializations win.  Only use the raw extractor output
    # when a curated source directory does not exist at all; an invalid curated
    # tree must remain blocked instead of being hidden by a fallback.
    curated_root = unit_dir / "extracted_battle_source_12fps"
    source_root = curated_root if curated_root.is_dir() else unit_dir / "extracted_battle"
    if not source_root.is_dir():
        return None
    candidates: list[tuple[int, Path]] = []
    for path in source_root.iterdir():
        if not path.is_dir() or path.suffix.lower() != ".dir":
            continue
        try:
            inventory = inventory_authentic_def_groups(path)
        except (OSError, RuntimeError, ValueError):
            continue
        if IDLE_GROUP not in inventory:
            continue
        candidates.append((sum(len(frames) for frames in inventory.values()), path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1].name.lower()))
    return candidates[0][1]


def _discover_lab_def_choices(root: Path) -> list[RocAssetChoice]:
    """List idle-leading ship sequences and motion-only diagnostic counterparts."""
    choices: list[RocAssetChoice] = []
    covered_units: set[str] = set()
    for lab in _lab_discovery_roots(root):
        if not lab.is_dir():
            continue
        for unit_dir in sorted(lab.iterdir(), key=lambda path: path.name.lower()):
            if not unit_dir.is_dir() or unit_dir.name.lower() in covered_units:
                continue
            def_dir = _select_lab_def_directory(unit_dir)
            if def_dir is None:
                continue
            try:
                inventory = inventory_authentic_def_groups(def_dir)
            except (OSError, RuntimeError, ValueError):
                continue
            counts = {group: len(frames) for group, frames in inventory.items()}
            sequences = tuple(idle_leading_def_sequences(counts)) + tuple(
                motion_only_def_sequences(counts)
            )
            if not sequences:
                continue
            unit_sid = unit_dir.name
            unit = _unit_name(unit_sid, unit_dir.name)
            present = tuple(sorted(counts))
            for groups in sequences:
                frames: list[Path] = []
                expected: list[int] = []
                for group in groups:
                    group_frames = inventory[int(group)]
                    frames.extend(group_frames)
                    expected.append(len(group_frames))
                animation = def_sequence_animation_name(groups)
                choice_id = def_sequence_choice_id(unit_sid, groups)
                runtime_dir, camera_fit = _runtime_paths(root, unit_sid, animation)
                choices.append(
                    RocAssetChoice(
                        unit_name=unit,
                        unit_sid=unit_sid,
                        animation_name=animation,
                        choice_id=choice_id,
                        pilot_dir=runtime_dir,
                        camera_fit=camera_fit,
                        frame_indices=tuple(range(len(frames))),
                        default_mesh=None,
                        source_frames=tuple(frames),
                        camera_metadata=None,
                        source_label=str(def_dir),
                        provisional_camera=True,
                        source_kind="authentic_def",
                        def_lab_frame_dir=def_dir,
                        def_lab_groups=tuple(int(group) for group in groups),
                        def_expected_counts=tuple(expected),
                        present_groups=present,
                        sequence_kind=pose_sequence_kind(groups),
                    )
                )
            covered_units.add(unit_dir.name.lower())
    return choices


def _discover_roc_choices(root: Path) -> list[RocAssetChoice]:
    pipeline_root = root / "artifacts" / "roc_pose_pipeline"
    choices: list[RocAssetChoice] = []
    if not pipeline_root.is_dir():
        return choices
    for pilot_dir in sorted(pipeline_root.iterdir(), key=lambda path: path.name.lower()):
        if not pilot_dir.is_dir():
            continue
        # Prefer the extracted DEF/VCMI source lane. ``frames_src`` is the
        # legacy presentation lane and may contain RIFE output.
        source_dir = pilot_dir / "frames_ground_truth"
        if not source_dir.is_dir():
            # Do not silently promote the legacy frames_src/RIFE lane into an
            # original animation choice. It must be extracted/materialized
            # into frames_ground_truth first.
            continue
        frames = _source_frame_paths(source_dir)
        camera_fit = pilot_dir / "roc_sprite_camera_fit.json"
        if not frames or not camera_fit.is_file():
            continue
        metadata = _read_json(camera_fit)
        if metadata is None:
            raise ValueError(f"invalid camera fit metadata: {camera_fit}")
        unit_sid = str(metadata.get("unitSid", "h3_roc"))
        unit = _unit_name(unit_sid, pilot_dir.name)
        animation = _animation_name(str(metadata.get("clip", "")), pilot_dir.name)
        bundled_mesh = pilot_dir / "griffon_smart_rigged.glb"
        choices.append(
            RocAssetChoice(
                unit_name=unit,
                unit_sid=unit_sid,
                animation_name=animation,
                choice_id=f"{unit_sid}:{pilot_dir.name}",
                pilot_dir=pilot_dir,
                camera_fit=camera_fit,
                frame_indices=tuple(range(len(frames))),
                default_mesh=bundled_mesh if bundled_mesh.is_file() else None,
                source_frames=frames,
                camera_metadata=metadata,
                source_label=str(source_dir),
            )
        )
    return choices


def _discover_generic_choices(root: Path) -> list[RocAssetChoice]:
    artifacts = root / "artifacts"
    if not artifacts.is_dir():
        return []
    choices: list[RocAssetChoice] = []
    seen: set[str] = set()
    for pipeline_root in sorted(artifacts.glob("*_pose_pipeline"), key=lambda path: path.name.lower()):
        if pipeline_root.name.lower() == "roc_pose_pipeline":
            continue
        source_map, representative = _job_source_map(pipeline_root)
        representative = representative or {
            "unitSid": f"h3_{pipeline_root.name.removesuffix('_pose_pipeline')}",
            "camera": {"axis": "iso", "isoAzimuthDeg": 40.0, "isoElevationDeg": 30.0, "distance": 3.0, "orthoScale": 3.0},
            "masterGlb": None,
        }
        unit_sid = str(representative.get("unitSid") or f"h3_{pipeline_root.name.removesuffix('_pose_pipeline')}")
        unit = _unit_name(unit_sid, pipeline_root.name)
        source_roots = (pipeline_root / "source_frames", pipeline_root / "source_attack_frames")
        fallback_mesh = _default_mesh(pipeline_root, representative)
        for source_root in source_roots:
            if not source_root.is_dir():
                continue
            source_dirs = sorted(source_root.iterdir(), key=lambda path: path.name.lower())
            # Prefer explicit per-animation directories. Aggregate exports are
            # processed afterward so they fill missing groups without
            # replacing a more authoritative named source directory.
            source_dirs = sorted(
                source_dirs,
                key=lambda path: (
                    path.name.lower() in _AGGREGATE_SOURCE_DIRS,
                    path.name.lower(),
                ),
            )
            seen_group_ids: set[int] = set()
            for source_dir in source_dirs:
                if not source_dir.is_dir() or not _is_animation_source_dir(source_dir):
                    continue
                if source_dir.name.lower() in _AGGREGATE_SOURCE_DIRS:
                    for group_index, frames in _aggregate_source_frames(source_dir):
                        if not frames or group_index in seen_group_ids:
                            continue
                        animation = _animation_from_group_index(group_index)
                        choice_id = f"{unit_sid}:{animation}"
                        if choice_id in seen:
                            seen_group_ids.add(group_index)
                            continue
                        mesh = fallback_mesh
                        if mesh is None:
                            continue
                        runtime_dir, camera_fit = _runtime_paths(root, unit_sid, animation)
                        choices.append(
                            RocAssetChoice(
                                unit_name=unit,
                                unit_sid=unit_sid,
                                animation_name=animation,
                                choice_id=choice_id,
                                pilot_dir=runtime_dir,
                                camera_fit=camera_fit,
                                frame_indices=tuple(range(len(frames))),
                                default_mesh=mesh,
                                source_frames=frames,
                                camera_metadata=representative,
                                source_label=str(source_dir),
                                provisional_camera=True,
                            )
                        )
                        seen.add(choice_id)
                        seen_group_ids.add(group_index)
                    continue
                frames = _source_frame_paths(source_dir)
                if not frames:
                    continue
                animation = _animation_from_source_dir(source_dir.name)
                choice_id = f"{unit_sid}:{animation}"
                if choice_id in seen:
                    continue
                metadata = source_map.get(source_dir.resolve(), representative)
                mesh = _default_mesh(pipeline_root, metadata) or fallback_mesh
                if mesh is None:
                    continue
                runtime_dir, camera_fit = _runtime_paths(root, unit_sid, animation)
                choices.append(
                    RocAssetChoice(
                        unit_name=unit,
                        unit_sid=unit_sid,
                        animation_name=animation,
                        choice_id=choice_id,
                        pilot_dir=runtime_dir,
                        camera_fit=camera_fit,
                        frame_indices=tuple(range(len(frames))),
                        default_mesh=mesh,
                        source_frames=frames,
                        camera_metadata=metadata,
                        source_label=str(source_dir),
                        provisional_camera=True,
                    )
                )
                seen.add(choice_id)
                group_index = _group_index_from_animation(animation)
                if group_index is not None:
                    seen_group_ids.add(group_index)
    return choices


def discover_asset_choices(root: Path) -> tuple[RocAssetChoice, ...]:
    """Discover authentic lab DEF sequences, then leftover pipeline inventories."""
    root = Path(root)
    lab_choices = _discover_lab_def_choices(root)
    covered = {choice.unit_sid.lower() for choice in lab_choices}
    covered.update({choice.unit_name.lower() for choice in lab_choices})
    leftovers: list[RocAssetChoice] = []
    for choice in (*_discover_roc_choices(root), *_discover_generic_choices(root)):
        if choice.unit_sid.lower() in covered or choice.unit_name.lower() in covered:
            continue
        leftovers.append(choice)
    return tuple(
        sorted(
            (*lab_choices, *leftovers),
            key=lambda choice: (
                0 if choice.unit_name == "crusader" else 1,
                0 if choice.unit_name == "roc" else 1,
                choice.unit_name.lower(),
                0 if choice.source_kind == "authentic_def" else 1,
                0 if choice.sequence_kind != "motion_only" else 1,
                0 if (
                    choice.source_kind == "authentic_def"
                    and choice.sequence_kind != "motion_only"
                    and choice.def_lab_groups[:1] == (2,)
                    and 0 in choice.def_lab_groups
                ) else 1,
                choice.def_lab_groups,
                choice.animation_name.lower(),
            ),
        )
    )


def discover_meshes(root: Path) -> tuple[Path, ...]:
    """Return meshes from Downloads, Meshy downloads, and pipeline mesh roots."""
    candidates: set[Path] = set()
    downloads = Path.home() / "Downloads"
    artifacts = Path(root) / "artifacts"
    mesh_source_dirs = (downloads, artifacts / "meshy_downloads")
    for directory in mesh_source_dirs:
        if directory.is_dir():
            candidates.update(path for path in directory.glob("*.glb") if path.is_file())
    if artifacts.is_dir():
        for pipeline_root in artifacts.glob("*_pose_pipeline"):
            if not pipeline_root.is_dir():
                continue
            for path in pipeline_root.rglob("*.glb"):
                if not path.is_file():
                    continue
                parts = {part.lower() for part in path.parts}
                if any(part in _SKIP_MESH_PARTS for part in parts):
                    continue
                if any(
                    part.startswith(("unity_", "out_fit", "out_attack", "out_sprite_motion", "out_frame0", "out_dense"))
                    for part in parts
                ):
                    continue
                if "assets" in parts or "homm3mapbuildingmeshes" in parts:
                    continue
                relative = path.relative_to(pipeline_root)
                relative_parts = {part.lower() for part in relative.parts}
                is_source_mesh = (
                    "out_meshy_t2_idle_f0" in relative_parts
                    or path.parent.name.lower() in {"owned_bind", "master"}
                    or relative.parent == Path(".")
                )
                if not is_source_mesh:
                    continue
                candidates.add(path)
    return tuple(sorted(candidates, key=lambda path: str(path).lower()))


def _vector_normalized(values: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(value * value for value in values))
    if length <= 1e-8:
        raise ValueError(f"cannot normalize zero vector: {values!r}")
    return tuple(value / length for value in values)


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _camera_basis(camera: dict[str, Any]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    axis = str(camera.get("axis", "iso")).lower()
    distance = float(camera.get("distance", 3.0))
    if axis == "iso":
        azimuth = math.radians(float(camera.get("isoAzimuthDeg", 40.0)))
        elevation = math.radians(float(camera.get("isoElevationDeg", 30.0)))
        radius = distance * math.cos(elevation)
        camera_position = (
            -radius * math.sin(azimuth),
            -radius * math.cos(azimuth),
            distance * math.sin(elevation) + float(camera.get("isoZOffset", 0.35)),
        )
        target = (0.0, 0.0, float(camera.get("lookAtZ", 0.75)))
    elif axis == "-x":
        camera_position, target = (-distance, 0.0, float(camera.get("height", 0.85))), (0.0, 0.0, 0.0)
    elif axis == "+x":
        camera_position, target = (distance, 0.0, float(camera.get("height", 0.85))), (0.0, 0.0, 0.0)
    elif axis == "-y":
        camera_position, target = (0.0, -distance, float(camera.get("height", 0.85))), (0.0, 0.0, 0.0)
    elif axis == "+y":
        camera_position, target = (0.0, distance, float(camera.get("height", 0.85))), (0.0, 0.0, 0.0)
    else:
        raise ValueError(f"unsupported job camera axis: {axis!r}")
    forward = _vector_normalized(tuple(target[index] - camera_position[index] for index in range(3)))
    right = _vector_normalized(_cross(forward, (0.0, 0.0, 1.0)))
    up = _vector_normalized(_cross(right, forward))
    # The worker contract stores image-right and image-down rows.
    return right, tuple(-value for value in up)


def _image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - notebook environment dependency
        raise RuntimeError("Pillow is required to materialize a selected asset") from exc
    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _write_nn_canvas_camera_fit(
    choice: RocAssetChoice,
    camera_fit: Path,
    out_size: tuple[int, int],
) -> None:
    width, height = (int(out_size[0]), int(out_size[1]))
    if width < 16 or height < 16:
        raise ValueError(f"nn canvas is too small for a pose-fit camera: {out_size}")
    camera = dict(choice.camera_metadata or {}).get("camera") or choice.camera_metadata or {}
    try:
        right, image_down = _camera_basis(camera if isinstance(camera, dict) else {})
    except ValueError:
        right, image_down = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    ortho_scale = float(camera.get("orthoScale", 3.0)) if isinstance(camera, dict) else 3.0
    payload = {
        "unitSid": choice.unit_sid,
        "clip": choice.animation_name,
        "sourceFrame": 0,
        "sourceResolution": [width, height],
        "basisScreenRows": [list(right), list(image_down)],
        "pxPerWorld": max(width, height) / ortho_scale,
        "screenOffsetPx": [width / 2.0, height / 2.0],
        "cameraPolicy": "provisional_job_camera",
        "profileMetrics": {
            "source": "nn-upscale canvas from authentic DEF idle-leading sequence"
        },
    }
    camera_fit.parent.mkdir(parents=True, exist_ok=True)
    camera_fit.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _materialize_def_choice(root: Path, choice: RocAssetChoice) -> tuple[Path, Path, Path]:
    if choice.def_lab_frame_dir is None or not choice.def_lab_groups:
        raise RuntimeError(f"authentic DEF choice is missing lab groups: {choice.choice_id}")
    meta_path = resolve_nn_upscale_meta_for_source(
        root,
        choice.unit_sid,
        choice.def_lab_frame_dir,
        source_frames=choice.source_frames,
    )
    meta = ensure_def_nn_upscale_meta(choice.def_lab_frame_dir, meta_path)
    contract = load_nn_upscale_contract(meta)
    camera_fit = choice.camera_fit
    if camera_fit.is_file():
        payload = _read_json(camera_fit)
        source = None if payload is None else payload.get("sourceResolution")
        if (
            isinstance(source, list)
            and len(source) == 2
            and (int(source[0]), int(source[1])) == contract.out_size
        ):
            return choice.pilot_dir, camera_fit, meta
    _write_nn_canvas_camera_fit(choice, camera_fit, contract.out_size)
    return choice.pilot_dir, camera_fit, meta


def _write_provisional_camera_fit(choice: RocAssetChoice, camera_fit: Path) -> None:
    width, height = _image_size(choice.source_frames[0])
    camera = dict(choice.camera_metadata or {}).get("camera") or choice.camera_metadata or {}
    right, image_down = _camera_basis(camera)
    ortho_scale = float(camera.get("orthoScale", 3.0))
    payload = {
        "unitSid": choice.unit_sid,
        "clip": choice.animation_name,
        "sourceFrame": 0,
        "sourceResolution": [width, height],
        "basisScreenRows": [list(right), list(image_down)],
        "pxPerWorld": max(width, height) / ortho_scale,
        "screenOffsetPx": [width / 2.0, height / 2.0],
        "cameraPolicy": "provisional_job_camera",
        "profileMetrics": {"source": "job.resolved.json camera metadata; geometry detection remains enabled"},
    }
    camera_fit.parent.mkdir(parents=True, exist_ok=True)
    camera_fit.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _materialize_choice(choice: RocAssetChoice) -> tuple[Path, Path]:
    if choice.source_kind == "authentic_def":
        raise RuntimeError("authentic DEF choices must use _materialize_def_choice")
    if not choice.provisional_camera:
        return choice.pilot_dir, choice.camera_fit
    if not choice.source_frames:
        raise RuntimeError(f"selected choice has no source frames: {choice.choice_id}")
    runtime_dir = choice.pilot_dir
    # Every materialized choice receives the same explicit source lane. The
    # resolver and setup code never have to guess whether ``frames_src`` is
    # original or interpolated.
    frames_dir = runtime_dir / "frames_ground_truth"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stale in frames_dir.glob("*.png"):
        stale.unlink()
    for index, source in enumerate(choice.source_frames):
        if not source.is_file():
            raise FileNotFoundError(f"source frame disappeared: {source}")
        shutil.copy2(source, frames_dir / f"{index:02d}.png")
    manifest = {
        "unit": choice.unit_name,
        "unitSid": choice.unit_sid,
        "animation": choice.animation_name,
        "frameDir": str(frames_dir),
        "frameCount": len(choice.source_frames),
        "frameIndices": list(range(len(choice.source_frames))),
        "sourceKind": "vcmi_def",
        "provenance": f"source inventory selected from {choice.source_label}; no RIFE interpolation",
    }
    (frames_dir / "original_frames.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_provisional_camera_fit(choice, choice.camera_fit)
    return runtime_dir, choice.camera_fit


class RocAssetPicker:
    """Mesh, unit, and animation selectors for the reusable pose pipeline."""

    def __init__(
        self,
        root: Path,
        *,
        default_unit: str = "crusader",
        default_animation: str | None = None,
        default_mesh: str | Path | None = None,
    ):
        try:
            import ipywidgets as widgets
        except ImportError as exc:  # pragma: no cover - exercised in notebooks
            raise RuntimeError("ipywidgets is required for the Roc asset picker") from exc

        self.root = Path(root)
        self.choices = discover_asset_choices(self.root)
        if not self.choices:
            raise RuntimeError(f"No source-frame inventories found under {self.root / 'artifacts'}")
        meshes = list(discover_meshes(self.root))
        for choice in self.choices:
            if choice.default_mesh is not None and choice.default_mesh not in meshes:
                meshes.append(choice.default_mesh)
        meshes = sorted(set(meshes), key=lambda path: str(path).lower())
        downloads_dir = Path.home() / "Downloads"
        preferred_mesh = (
            Path(default_mesh).expanduser()
            if default_mesh is not None
            else Path(r"C:/Users/<user>/Downloads/griffon_smart_rigged.glb")
        )
        default_mesh = next(
            (path for path in meshes if path.resolve() == preferred_mesh.resolve()),
            next(
                (
                    choice.default_mesh
                    for choice in self.choices
                    if choice.unit_name == str(default_unit)
                    and choice.default_mesh in meshes
                ),
                meshes[0] if meshes else None,
            ),
        )
        if default_mesh is None:
            raise RuntimeError(
                "No local .glb mesh was found in Downloads, artifacts/meshy_downloads, "
                "or the unit pipeline artifacts"
            )

        mesh_options = []
        for path in meshes:
            try:
                label = str(path.relative_to(self.root))
            except ValueError:
                label = path.name if path.parent == downloads_dir else f"{path.parent.name}/{path.name}"
            mesh_options.append((label, str(path)))

        units = sorted(
            {choice.unit_name for choice in self.choices},
            key=lambda value: (value != "crusader", value != "roc", value.lower()),
        )
        self.mesh = widgets.Dropdown(options=mesh_options, value=str(default_mesh), description="Mesh", layout=widgets.Layout(width="640px"))
        selected_unit = str(default_unit) if str(default_unit) in units else units[0]
        self.unit = widgets.Dropdown(options=units, value=selected_unit, description="Unit", layout=widgets.Layout(width="260px"))
        self.animation = widgets.Dropdown(options=(), description="Animation", layout=widgets.Layout(width="480px"))
        self.status = widgets.HTML()
        self.mesh.observe(self._mesh_changed, names="value")
        self.unit.observe(self._unit_changed, names="value")
        self._refresh_animations()
        if default_animation is not None:
            animation_values = [value for _, value in self.animation.options]
            requested = remap_isolated_choice_id_to_idle_leading(
                str(default_animation),
                animation_values,
            )
            if requested in animation_values:
                self.animation.value = requested
        self.widget = widgets.VBox([widgets.HBox([self.mesh]), widgets.HBox([self.unit, self.animation]), self.status])
        self._update_status()

    def _unit_choices(self) -> list[RocAssetChoice]:
        return [choice for choice in self.choices if choice.unit_name == self.unit.value]

    def _refresh_animations(self) -> None:
        choices = self._unit_choices()
        options = [(choice.label, choice.choice_id) for choice in choices]
        previous = self.animation.value
        self.animation.options = options
        values = [value for _, value in options]
        self.animation.value = previous if previous in values else values[0]
        self._update_status()

    def _unit_changed(self, _change: dict[str, Any]) -> None:
        self._refresh_animations()
        # Mesh and unit are independent selectors.  Do not replace an
        # explicitly selected mesh when the user changes the unit or its
        # animation; doing so made the widget appear to accept a mesh while
        # silently restoring the unit's default before config_overrides().
        self._update_status()

    def _mesh_changed(self, _change: dict[str, Any]) -> None:
        self._update_status()

    def _selected_choice(self) -> RocAssetChoice:
        for choice in self._unit_choices():
            if choice.choice_id == self.animation.value:
                return choice
        raise RuntimeError("The selected unit/animation is not a runnable source-frame choice")

    def _update_status(self) -> None:
        if not hasattr(self, "status") or not self.animation.value:
            return
        choice = self._selected_choice()
        audit_status, audit_report = meshy_rigidization_status(Path(self.mesh.value))
        audit_note = (
            f"Meshy audit: {audit_status} ({audit_report.name})"
            if audit_report is not None
            else "Meshy audit: missing beside selected mesh"
        )
        camera_note = (
            "nn-upscale canvas; motion-only diagnostic starts from bind, not ship"
            if choice.source_kind == "authentic_def" and choice.sequence_kind == "motion_only"
            else (
                "nn-upscale canvas; profile init still registers yaw from idle"
                if choice.source_kind == "authentic_def"
                else (
                    "provisional job-camera seed; profile override bypassed for generic mesh"
                    if choice.provisional_camera
                    else "authoritative fitted camera"
                )
            )
        )
        selected_mesh = Path(self.mesh.value).expanduser().resolve()
        present = ",".join(f"{group:02d}" for group in choice.present_groups) or "pipeline"
        self.status.value = (
            f"<b>{choice.unit_name} [{choice.unit_sid}] / {choice.animation_name}</b> &nbsp; "
            f"<code>{len(choice.frame_indices)} frames</code> &nbsp; "
            f"<code>mesh={selected_mesh.name}</code> &nbsp; "
            f"<code>{camera_note}</code> &nbsp; "
            f"<code>{audit_note}</code> &nbsp; "
            f"<code>defGroups={present}</code> &nbsp; "
            f"<code>source={choice.source_label}</code>"
        )

    def config_overrides(self) -> dict[str, Any]:
        choice = self._selected_choice()
        selected_mesh = Path(self.mesh.value).expanduser().resolve()
        if not selected_mesh.is_file():
            raise FileNotFoundError(f"selected mesh is missing: {selected_mesh}")
        if choice.source_kind == "authentic_def":
            pilot_dir, camera_fit, meta = _materialize_def_choice(self.root, choice)
            frame_dir = f"frames_def12_nn_{choice.animation_name}"
            return {
                "src_glb": selected_mesh,
                "meshy_rigidization_report": meshy_rigidization_report_for(selected_mesh),
                "unit_name": choice.unit_name,
                "unit_sid": choice.unit_sid,
                "animation_name": choice.animation_name,
                "pilot_dir": pilot_dir,
                "camera_fit_path": camera_fit,
                "frame_indices": (),
                "target_frame_dir": frame_dir,
                "shadow_culled_frame_dir": f"{frame_dir}_shadow_culled",
                "target_depth_dir": f"{frame_dir}_depth_vda",
                "def_lab_frame_dir": choice.def_lab_frame_dir,
                "def_lab_group": choice.def_lab_groups,
                "def_expected_count": choice.def_expected_counts,
                "def_nn_upscale_meta": meta,
                "source_frame_paths": tuple(str(path) for path in choice.source_frames),
            }
        pilot_dir, camera_fit = _materialize_choice(choice)
        return {
            "src_glb": selected_mesh,
            "meshy_rigidization_report": meshy_rigidization_report_for(selected_mesh),
            "unit_name": choice.unit_name,
            "unit_sid": choice.unit_sid,
            "animation_name": choice.animation_name,
            "pilot_dir": pilot_dir,
            "camera_fit_path": camera_fit,
            "frame_indices": choice.frame_indices,
            # Keep the original DEF stems available to auxiliary-view loaders.
            # The materialized notebook frames are intentionally renamed to
            # 00.png, 01.png, ... and cannot identify their source .dir alone.
            "source_frame_paths": tuple(str(path) for path in choice.source_frames),
        }

    def selection_summary(self) -> dict[str, Any]:
        choice = self._selected_choice()
        selected_mesh = Path(self.mesh.value).expanduser().resolve()
        return {
            "mesh": str(selected_mesh),
            "meshName": selected_mesh.name,
            "unit": choice.unit_name,
            "unitSid": choice.unit_sid,
            "animation": choice.animation_name,
            "choiceId": choice.choice_id,
            "frames": len(choice.frame_indices),
            "pilot": str(choice.pilot_dir),
        }

    def restore_selection(self, summary: dict[str, Any] | None) -> None:
        """Restore a prior widget selection when the notebook cell reruns."""
        if not summary:
            return
        mesh = str(summary.get("mesh", ""))
        if any(value == mesh for _, value in self.mesh.options):
            self.mesh.value = mesh
        unit = str(summary.get("unit", ""))
        if unit in self.unit.options:
            self.unit.value = unit
        choice_id = str(summary.get("choiceId", ""))
        pilot = str(summary.get("pilot", ""))
        values = [value for _, value in self.animation.options]
        choice_id = remap_isolated_choice_id_to_idle_leading(choice_id, values)
        if choice_id in values:
            self.animation.value = choice_id
        else:
            for choice in self._unit_choices():
                if str(choice.pilot_dir) == pilot:
                    self.animation.value = choice.choice_id
                    break
            else:
                locomotion = next(
                    (
                        choice.choice_id
                        for choice in self._unit_choices()
                        if choice.source_kind == "authentic_def"
                        and choice.sequence_kind != "motion_only"
                        and choice.def_lab_groups[:1] == (2,)
                        and (0 in choice.def_lab_groups or 1 in choice.def_lab_groups)
                    ),
                    None,
                )
                if locomotion is not None:
                    self.animation.value = locomotion
        self._update_status()


def make_asset_picker(
    root: Path,
    previous_selection: dict[str, Any] | None = None,
    *,
    default_unit: str = "crusader",
    default_animation: str | None = "h3_crusader:g02-g20-g00",
    default_mesh: str | Path | None = None,
) -> RocAssetPicker:
    picker = RocAssetPicker(
        Path(root),
        default_unit=default_unit,
        default_animation=default_animation,
        default_mesh=default_mesh,
    )
    picker.restore_selection(previous_selection)
    return picker


def gpu_pose_v2_selection(picker: RocAssetPicker) -> dict[str, Any]:
    """Build the V2 selection contract from the picker's current widget values.

    The widget values are deliberately read at call time.  A notebook must not
    retain the first ``config_overrides()`` result as an implicit asset choice,
    because users can change the dropdowns without rerunning the picker cell.
    """
    values = picker.config_overrides()
    target = Path(values.get("target_frame_dir") or "frames_ground_truth")
    if not target.is_absolute():
        target = Path(values["pilot_dir"]) / target
    return {
        "mesh_path": values["src_glb"],
        "target_frame_dir": target,
        "camera_fit_path": values["camera_fit_path"],
        "rigidization_report": values.get("meshy_rigidization_report"),
        "frame_indices": tuple(values["frame_indices"]),
        "source_fps": float(values.get("source_fps") or 12.0),
        "frame_durations": values.get("frame_durations"),
        "artifact_dir": Path(values["pilot_dir"]) / "gpu_pose_v2",
        "unit_name": values.get("unit_name"),
        "animation_name": values.get("animation_name"),
        "unit_sid": values.get("unit_sid"),
        "source_frame_paths": tuple(values.get("source_frame_paths") or ()),
        "front_perspective_root": picker.root / "artifacts" / "sprite_profile_to_front" / "out",
    }
