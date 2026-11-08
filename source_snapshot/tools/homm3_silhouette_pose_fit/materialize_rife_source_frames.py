#!/usr/bin/env python3
"""Copy HoMM3 lab RIFE groups into numbered pose-fit source frames.

Lab battle interpolation stores ``GG_FFFF.png`` next to Unity ``.meta`` files.
Those files are native DEF plates (crusader: 450×400) with a small subject.
Pose-fit cameras are authored on the shared-union nearest-neighbor canvas
(crusader: 1098×876). This helper crops and integer-scales each RIFE frame
with the recorded ``upscale_meta.json`` contract so the 1098 camera still
matches. It never writes into ``frames_ground_truth`` and never rescales
``pxPerWorld`` by native-plate width.

A single group stays one clip. An explicit group list concatenates those
clips in order so later poses can seed from idle rather than from bind.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image


NN_UPSCALE_METHOD = "shared_union_crop_nearest_neighbor"
ALPHA_THRESHOLD = 8
DEF_GROUP_NAMES = {
    0: "move",
    1: "mouseover",
    2: "idle",
    3: "hitted",
    4: "defence",
    5: "death",
    7: "turn_left",
    8: "turn_right",
    9: "unused_a",
    10: "unused_b",
    11: "attack_up",
    12: "attack_front",
    13: "attack_down",
    14: "shoot_up",
    15: "shoot_front",
    16: "shoot_down",
    20: "move_start",
    21: "move_end",
}
IDLE_GROUP = 2
MOVE_GROUP = 0
MOUSEOVER_GROUP = 1
MOVE_START_GROUP = 20
MOVE_END_GROUP = 21
MOVE_START_MAX_FRAMES = 4
DEATH_DEF_GROUPS = frozenset({5, 6})
DEF_SEQUENCE_FRAME_CAP = 100
# Turn left/right and attack up/down are not fitted or shipped for OE skinned mesh.
UNSHIPPED_DEF_GROUPS = frozenset({7, 8, 11, 13, 14, 16})
_AUTHENTIC_DEF_FRAME_NAME = re.compile(r"^(\d{2})_(\d{2})\.png$", re.IGNORECASE)
_RIFE_DEF_FRAME_NAME = re.compile(r"^(\d{2})_(\d{4})\.png$", re.IGNORECASE)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _group_paths(
    source_dir: Path,
    group: int,
    *,
    frame_digits: int | None = None,
    source_label: str = "RIFE",
    missing_dir_label: str | None = None,
) -> list[Path]:
    source_dir = Path(source_dir)
    if frame_digits is None:
        pattern = re.compile(rf"^{int(group):02d}_(\d+)\.png$", re.IGNORECASE)
    else:
        pattern = re.compile(
            rf"^{int(group):02d}_(\d{{{int(frame_digits)}}})\.png$",
            re.IGNORECASE,
        )
    found: dict[int, Path] = {}
    dir_label = missing_dir_label or f"{source_label} lab frame directory"
    if not source_dir.is_dir():
        raise FileNotFoundError(f"{dir_label} is missing: {source_dir}")
    for path in source_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        match = pattern.fullmatch(path.name)
        if match is None:
            continue
        index = int(match.group(1))
        if index in found:
            raise RuntimeError(f"duplicate {source_label} frame index {index} in {source_dir}")
        found[index] = path
    if not found:
        raise FileNotFoundError(
            f"no {source_label} frames for group {int(group):02d} in {source_dir}"
        )
    expected = list(range(max(found) + 1))
    missing = [index for index in expected if index not in found]
    if missing:
        raise RuntimeError(f"{source_label} group {int(group):02d} has gaps: {missing[:12]}")
    return [found[index] for index in expected]


def _authentic_def_group_paths(source_dir: Path, group: int) -> list[Path]:
    """Return GG_FF.png DEF keyframes. Four-digit RIFE plates are not DEF."""
    source_dir = Path(source_dir)
    if source_dir.is_dir():
        rife_names = sorted(
            path.name
            for path in source_dir.iterdir()
            if path.is_file()
            and re.fullmatch(rf"^{int(group):02d}_\d{{4}}\.png$", path.name, re.IGNORECASE)
        )
        if rife_names:
            raise RuntimeError(
                f"group {int(group):02d} in {source_dir} has RIFE interpolated plates "
                f"({rife_names[0]}); authentic DEF uses GG_FF.png from the 12 fps extract, "
                "not the 60 fps lab"
            )
    return _group_paths(
        source_dir,
        group,
        frame_digits=2,
        source_label="authentic DEF",
        missing_dir_label="authentic DEF frame directory",
    )


def def_group_name(group: int) -> str:
    known = DEF_GROUP_NAMES.get(int(group))
    if known is None:
        return f"group_{int(group):02d}"
    return known


def inventory_authentic_def_groups(source_dir: Path) -> dict[int, list[Path]]:
    """Return 12 fps ``GG_FF.png`` groups. Four-digit RIFE plates are refused."""
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise FileNotFoundError(f"authentic DEF frame directory is missing: {source_dir}")
    groups: dict[int, dict[int, Path]] = {}
    rife_names: list[str] = []
    for path in source_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        if _RIFE_DEF_FRAME_NAME.fullmatch(path.name):
            rife_names.append(path.name)
            continue
        match = _AUTHENTIC_DEF_FRAME_NAME.fullmatch(path.name)
        if match is None:
            continue
        group_index, frame_index = (int(value) for value in match.groups())
        bucket = groups.setdefault(group_index, {})
        if frame_index in bucket:
            raise RuntimeError(
                f"duplicate authentic DEF frame {path.name} in {source_dir}"
            )
        bucket[frame_index] = path
    if rife_names and not groups:
        raise RuntimeError(
            f"{source_dir} has RIFE interpolated plates ({sorted(rife_names)[0]}) "
            "and no authentic GG_FF.png DEF frames"
        )
    inventory: dict[int, list[Path]] = {}
    for group_index, frames in groups.items():
        expected = list(range(max(frames) + 1))
        missing = [index for index in expected if index not in frames]
        if missing:
            raise RuntimeError(
                f"authentic DEF group {int(group_index):02d} has gaps: {missing[:12]}"
            )
        inventory[int(group_index)] = [frames[index] for index in expected]
    return dict(sorted(inventory.items()))


def pose_sequence_without_trailing_idle(groups: Sequence[int]) -> tuple[int, ...]:
    """Drop a trailing idle suffix used so reverse can start from rest."""
    sequence = tuple(int(group) for group in groups)
    while len(sequence) > 1 and sequence[-1] == IDLE_GROUP:
        sequence = sequence[:-1]
    return sequence


def _with_idle_return_chain(
    groups: Sequence[int],
    counts: Mapping[int, int],
    *,
    walking: bool,
) -> tuple[int, ...]:
    """Append move-end and trailing idle when this motion returns to rest.

    Death stays down, so it does not get a return-to-idle suffix. Walk loops
    still end in move-end then idle when those groups exist; the cascade
    reverse pass walks this same chain backward.
    """
    out = [int(group) for group in groups]
    if not out:
        return ()
    motion = pose_sequence_without_trailing_idle(out)
    if int(motion[-1]) in DEATH_DEF_GROUPS:
        return tuple(out)
    if (
        walking
        and MOVE_END_GROUP in counts
        and MOVE_END_GROUP not in out
    ):
        out.append(MOVE_END_GROUP)
    if out[-1] != IDLE_GROUP:
        out.append(IDLE_GROUP)
    return tuple(out)


def def_sequence_animation_name(groups: Sequence[int]) -> str:
    """Human clip name for an idle-leading sequence, e.g. idle_start_move."""
    parts: list[str] = []
    for group in pose_sequence_without_trailing_idle(groups):
        name = def_group_name(int(group))
        if name == "move_start":
            parts.append("start")
        elif name == "move_end":
            parts.append("end")
        else:
            parts.append(name)
    if not parts:
        raise ValueError("DEF sequence animation name requires at least one group")
    return "_".join(parts)


def def_sequence_choice_id(unit_sid: str, groups: Sequence[int]) -> str:
    encoded = "-".join(f"g{int(group):02d}" for group in groups)
    return f"{unit_sid}:{encoded}"


def motion_core_def_groups(groups: Sequence[int]) -> tuple[int, ...]:
    """Strip leading and trailing idle from an idle-leading sequence."""
    sequence = tuple(int(group) for group in groups)
    while sequence and sequence[0] == IDLE_GROUP:
        sequence = sequence[1:]
    while sequence and sequence[-1] == IDLE_GROUP:
        sequence = sequence[:-1]
    return sequence


def pose_sequence_kind(groups: Sequence[int]) -> str:
    """idle_only, idle_leading, or motion_only."""
    normalized = tuple(int(group) for group in groups)
    if not normalized:
        raise ValueError("DEF groups cannot be empty")
    if normalized == (IDLE_GROUP,):
        return "idle_only"
    if normalized[0] == IDLE_GROUP:
        if IDLE_GROUP in normalized[1:-1]:
            raise ValueError(f"idle DEF group {IDLE_GROUP} cannot sit inside a sequence: {list(normalized)}")
        return "idle_leading"
    if IDLE_GROUP in normalized:
        raise ValueError(
            f"motion-only sequences must omit idle DEF group {IDLE_GROUP}; got {list(normalized)}"
        )
    return "motion_only"


def require_motion_only_pose_groups(
    groups: Sequence[int],
    *,
    sequence_label: str = "pose-fit",
) -> tuple[int, ...]:
    """Allow a diagnostic action chain that omits idle and starts from bind.

    This is not a delivery sequence. Ship fits still use idle-leading groups
    so later motion seeds from rest.
    """
    normalized = tuple(int(group) for group in groups)
    if not normalized:
        raise ValueError(f"{sequence_label} DEF groups cannot be empty")
    if IDLE_GROUP in normalized:
        raise ValueError(
            f"{sequence_label} motion-only diagnostic must omit idle DEF group "
            f"{IDLE_GROUP}; use the idle-leading sequence to seed from rest. "
            f"got {list(normalized)}"
        )
    return normalized


def require_idle_leading_pose_groups(
    groups: Sequence[int],
    *,
    sequence_label: str = "pose-fit",
    allow_idle_only: bool = False,
) -> tuple[int, ...]:
    """Refuse isolated action clips unless they are an explicit motion-only diagnostic.

    Idle DEF group 2 is a temporal prefix for multi-group ship fits. Later
    motion has to seed from that rest pose. Idle-only sequences are allowed
    only when ``allow_idle_only`` is set for shipping the idle clip itself.
    """
    normalized = tuple(int(group) for group in groups)
    if not normalized:
        raise ValueError(f"{sequence_label} DEF groups cannot be empty")
    if normalized[0] != IDLE_GROUP:
        raise ValueError(
            f"{sequence_label} must start with idle DEF group {IDLE_GROUP} so later "
            f"motion seeds from rest rather than bind; got {list(normalized)}"
        )
    if len(normalized) < 2:
        if allow_idle_only and normalized == (IDLE_GROUP,):
            return normalized
        raise ValueError(
            f"{sequence_label} idle-only sequences are a camera prefix, not a motion "
            f"clip; concatenate idle with the action group. got {list(normalized)}"
        )
    return normalized


def require_authentic_def_pose_groups(
    groups: Sequence[int],
    *,
    sequence_label: str = "pose-fit",
    allow_idle_only: bool = False,
    allow_motion_only: bool = True,
) -> tuple[int, ...]:
    """Accept idle-leading ship sequences or listed motion-only diagnostics."""
    normalized = tuple(int(group) for group in groups)
    if not normalized:
        raise ValueError(f"{sequence_label} DEF groups cannot be empty")
    if normalized[0] == IDLE_GROUP:
        return require_idle_leading_pose_groups(
            normalized,
            sequence_label=sequence_label,
            allow_idle_only=allow_idle_only,
        )
    if not allow_motion_only:
        return require_idle_leading_pose_groups(
            normalized,
            sequence_label=sequence_label,
            allow_idle_only=allow_idle_only,
        )
    return require_motion_only_pose_groups(normalized, sequence_label=sequence_label)


def require_idle_leading_source_manifest(path: Path) -> tuple[int, ...]:
    """Read a materialized DEF sequence manifest and require idle first."""
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    groups = payload.get("sourceGroups")
    if not isinstance(groups, list) or not groups:
        raise ValueError(f"{manifest_path} has no sourceGroups")
    return require_idle_leading_pose_groups(
        [int(group) for group in groups],
        sequence_label=str(manifest_path),
    )


def idle_leading_def_sequences(
    group_counts: Mapping[int, int],
) -> tuple[tuple[int, ...], ...]:
    """Build selectable pose-fit sequences from groups that actually exist.

    Idle (group 2) is required and always first. Missing DEF groups are omitted
    rather than listed. A one-frame group 0 with a long group 20 is not treated
    as walk-plus-start; those 20-series clips are listed separately.

    Every sequence except death also ends on idle so reverse-time consensus
    can walk the same chain backward from rest. Walk includes move-end when
    that group exists: idle → start → walk → end → idle.
    """
    counts = {int(group): int(count) for group, count in group_counts.items()}
    if IDLE_GROUP not in counts or counts[IDLE_GROUP] < 1:
        return ()
    sequences: list[tuple[int, ...]] = []
    locomotion: list[int] = [IDLE_GROUP]
    walking = MOVE_GROUP in counts and counts[MOVE_GROUP] > 1
    if walking and MOVE_START_GROUP in counts and counts[MOVE_START_GROUP] <= MOVE_START_MAX_FRAMES:
        locomotion.append(MOVE_START_GROUP)
    if walking or MOVE_GROUP in counts:
        locomotion.append(MOVE_GROUP)
    elif MOUSEOVER_GROUP in counts:
        locomotion.append(MOUSEOVER_GROUP)
    covered: set[int] = set(locomotion)
    if len(locomotion) >= 2:
        chain = _with_idle_return_chain(locomotion, counts, walking=walking)
        sequences.append(chain)
        covered = set(chain)
    for group in sorted(counts):
        if group == IDLE_GROUP or group in covered or int(group) in UNSHIPPED_DEF_GROUPS:
            continue
        sequences.append(
            _with_idle_return_chain((IDLE_GROUP, int(group)), counts, walking=False)
        )
    bounded: list[tuple[int, ...]] = []
    for groups in sequences:
        total = sum(counts[group] for group in groups)
        if total < 2:
            continue
        if total > DEF_SEQUENCE_FRAME_CAP and MOVE_GROUP not in groups:
            continue
        bounded.append(groups)
    if counts.get(IDLE_GROUP, 0) >= 2:
        idle_only = (IDLE_GROUP,)
        if idle_only not in bounded:
            bounded.insert(0, idle_only)
    return tuple(bounded)


def motion_only_def_sequences(
    group_counts: Mapping[int, int],
) -> tuple[tuple[int, ...], ...]:
    """Action cores of idle-leading sequences, with idle prefix/suffix removed.

    Each result is a separate picker folder so a bind-start diagnostic does not
    overwrite the idle-leading ship fit. Delivery must not select these.
    """
    cores: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    for groups in idle_leading_def_sequences(group_counts):
        core = motion_core_def_groups(groups)
        if not core or core in seen:
            continue
        seen.add(core)
        cores.append(core)
    return tuple(cores)


def normalize_named_group_plan(
    group: int | Sequence[int] | None,
    expected_count: int | Sequence[int] | None,
    *,
    group_field: str,
    count_field: str,
    sequence_label: str,
) -> tuple[tuple[int, ...], tuple[int | None, ...]] | None:
    """Return (groups, counts) or None when that source is disabled."""
    if group is None:
        if expected_count is not None:
            raise ValueError(f"{count_field} requires {group_field}")
        return None
    if isinstance(group, (str, bytes)):
        raise TypeError(f"{group_field} must be an int or a sequence of ints")
    if isinstance(group, Sequence):
        groups = tuple(int(value) for value in group)
    else:
        groups = (int(group),)
    if not groups:
        raise ValueError(f"{group_field} must contain at least one group")
    if any(value < 0 for value in groups):
        raise ValueError(f"{group_field} values must be non-negative")
    if expected_count is None:
        if len(groups) != 1:
            raise ValueError(f"concatenated {sequence_label} groups require {count_field} for every group")
        return groups, (None,)
    if isinstance(expected_count, (str, bytes)):
        raise TypeError(f"{count_field} must be an int or a sequence of ints")
    if isinstance(expected_count, Sequence):
        counts = tuple(int(value) for value in expected_count)
    else:
        counts = (int(expected_count),)
    if len(counts) != len(groups):
        raise ValueError(
            f"{count_field} length must match {group_field}: "
            f"groups={list(groups)} counts={list(counts)}"
        )
    if any(value < 1 for value in counts):
        raise ValueError(f"{count_field} values must be positive")
    return groups, counts


def normalize_rife_group_plan(
    group: int | Sequence[int] | None,
    expected_count: int | Sequence[int] | None,
) -> tuple[tuple[int, ...], tuple[int | None, ...]] | None:
    """Return (groups, counts) or None when RIFE is disabled."""
    return normalize_named_group_plan(
        group,
        expected_count,
        group_field="rife_lab_group",
        count_field="rife_expected_count",
        sequence_label="RIFE",
    )


def normalize_def_group_plan(
    group: int | Sequence[int] | None,
    expected_count: int | Sequence[int] | None,
) -> tuple[tuple[int, ...], tuple[int | None, ...]] | None:
    """Return (groups, counts) or None when authentic DEF source is disabled."""
    return normalize_named_group_plan(
        group,
        expected_count,
        group_field="def_lab_group",
        count_field="def_expected_count",
        sequence_label="DEF",
    )


@dataclass(frozen=True)
class NnUpscaleContract:
    """Recorded shared-union integer nearest-neighbor pose-fit canvas."""

    meta_path: Path
    source_size: tuple[int, int]
    union_bbox: tuple[int, int, int, int]
    crop_size: tuple[int, int]
    scale: int
    out_size: tuple[int, int]
    method: str
    sha256: str

    def to_manifest(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "metaPath": str(self.meta_path.resolve()),
            "metaSha256": self.sha256,
            "sourceSize": list(self.source_size),
            "unionBBox": list(self.union_bbox),
            "cropSize": list(self.crop_size),
            "scale": self.scale,
            "outSize": list(self.out_size),
        }


def load_nn_upscale_contract(meta_path: Path) -> NnUpscaleContract:
    meta_path = Path(meta_path)
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    method = str(payload.get("method") or "")
    if method != NN_UPSCALE_METHOD:
        raise ValueError(
            f"nn upscale meta {meta_path} must use {NN_UPSCALE_METHOD}, got {method!r}"
        )
    source = payload.get("sourceSize")
    union = payload.get("unionBBox")
    crop = payload.get("cropSize")
    out = payload.get("outSize")
    scale = int(payload.get("scale") or 0)
    if not isinstance(source, list) or len(source) != 2:
        raise ValueError(f"nn upscale meta {meta_path} has no sourceSize")
    if not isinstance(union, list) or len(union) != 4:
        raise ValueError(f"nn upscale meta {meta_path} has no unionBBox")
    if not isinstance(out, list) or len(out) != 2:
        raise ValueError(f"nn upscale meta {meta_path} has no outSize")
    source_size = (int(source[0]), int(source[1]))
    union_bbox = (int(union[0]), int(union[1]), int(union[2]), int(union[3]))
    out_size = (int(out[0]), int(out[1]))
    if source_size[0] <= 0 or source_size[1] <= 0:
        raise ValueError(f"nn upscale meta {meta_path} has invalid sourceSize {source}")
    x0, y0, x1, y1 = union_bbox
    if x0 < 0 or y0 < 0 or x1 < x0 or y1 < y0:
        raise ValueError(f"nn upscale meta {meta_path} has invalid unionBBox {union}")
    if x1 >= source_size[0] or y1 >= source_size[1]:
        raise ValueError(
            f"nn upscale meta {meta_path} unionBBox {union} exceeds sourceSize {list(source_size)}"
        )
    crop_size = (x1 - x0 + 1, y1 - y0 + 1)
    if isinstance(crop, list) and len(crop) == 2:
        recorded = (int(crop[0]), int(crop[1]))
        if recorded != crop_size:
            raise ValueError(
                f"nn upscale meta {meta_path} cropSize {list(recorded)} does not match unionBBox {crop_size}"
            )
    if scale < 2:
        raise ValueError(f"nn upscale meta {meta_path} scale must be an integer >= 2, got {scale}")
    expected_out = (crop_size[0] * scale, crop_size[1] * scale)
    if out_size != expected_out:
        raise ValueError(
            f"nn upscale meta {meta_path} outSize {list(out_size)} does not equal "
            f"cropSize {list(crop_size)} * scale {scale} = {list(expected_out)}"
        )
    return NnUpscaleContract(
        meta_path=meta_path,
        source_size=source_size,
        union_bbox=union_bbox,
        crop_size=crop_size,
        scale=scale,
        out_size=out_size,
        method=method,
        sha256=_sha256(meta_path),
    )


def find_recorded_nn_upscale_meta(root: Path, unit_sid: str) -> Path | None:
    """Return a recorded unit canvas if one already exists."""
    root = Path(root)
    sid = str(unit_sid).strip()
    unit = sid[3:] if sid.lower().startswith("h3_") else sid
    artifacts = root / "artifacts"
    candidates = (
        artifacts / f"{unit}_pose_pipeline" / "source_frames" / "nn_upscale" / "upscale_meta.json",
        artifacts / "pose_picker_runs" / sid / "nn_upscale" / "upscale_meta.json",
        artifacts / "pose_picker_runs" / f"h3_{unit}" / "nn_upscale" / "upscale_meta.json",
    )
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def _nn_source_size(source_dir: Path, source_frames: Sequence[Path] | None = None) -> tuple[int, int]:
    """Read one current DEF plate size without trusting an old contract."""
    samples = list(source_frames or ())[:1]
    if not samples:
        inventory = inventory_authentic_def_groups(Path(source_dir))
        if IDLE_GROUP not in inventory:
            raise RuntimeError(f"DEF {source_dir} has no idle group for nn-upscale verification")
        samples = inventory[IDLE_GROUP][:1]
    if not samples:
        raise RuntimeError(f"DEF {source_dir} has no frames for nn-upscale verification")
    with Image.open(samples[0]) as image:
        return int(image.width), int(image.height)


def nn_upscale_meta_matches_source(
    meta_path: Path,
    source_dir: Path,
    *,
    source_frames: Sequence[Path] | None = None,
) -> bool:
    """Return whether a recorded canvas belongs to the current DEF source.

    ``ensure_def_nn_upscale_meta`` deliberately fails closed when a caller
    passes a stale contract.  Selectors need one extra step before calling it:
    a valid contract from a previous extraction is historical evidence, not a
    reason to reuse a canvas for a different source directory or plate size.
    Invalid contracts still raise from ``load_nn_upscale_contract`` rather than
    being silently replaced.
    """
    meta_path = Path(meta_path)
    source_dir = Path(source_dir)
    contract = load_nn_upscale_contract(meta_path)
    if contract.source_size != _nn_source_size(source_dir, source_frames):
        return False
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    recorded_dir = payload.get("sourceDir")
    if recorded_dir:
        recorded_path = Path(str(recorded_dir)).expanduser()
        if not recorded_path.is_absolute():
            recorded_path = meta_path.parent / recorded_path
        if recorded_path.resolve() != source_dir.resolve():
            return False
    return True


def resolve_nn_upscale_meta_for_source(
    root: Path,
    unit_sid: str,
    source_dir: Path,
    *,
    source_frames: Sequence[Path] | None = None,
) -> Path:
    """Choose a compatible recorded canvas or an isolated replacement path.

    Old contracts are never overwritten when the source extraction changes.
    A deterministic source-directory token keeps the replacement stable across
    clips while preserving the original contract for older experiments.
    """
    root = Path(root)
    source_dir = Path(source_dir)
    source_size = _nn_source_size(source_dir, source_frames)
    recorded = find_recorded_nn_upscale_meta(root, unit_sid)
    if recorded is not None and nn_upscale_meta_matches_source(
        recorded, source_dir, source_frames=source_frames
    ):
        return recorded
    artifacts = root / "artifacts" / "pose_picker_runs" / str(unit_sid)
    if recorded is None:
        return artifacts / "nn_upscale" / "upscale_meta.json"
    token = hashlib.sha256(
        f"{source_dir.resolve()}|{source_size[0]}x{source_size[1]}".encode("utf-8")
    ).hexdigest()[:12]
    return artifacts / "nn_upscale" / f"upscale_meta_{token}.json"


def ensure_def_nn_upscale_meta(
    source_dir: Path,
    meta_path: Path,
    *,
    source_frames: Sequence[Path] | None = None,
    pad: int = 8,
    target_edge: int = 1024,
) -> Path:
    """Reuse a recorded canvas, or write one shared-union contract for this DEF.

    The union covers every supplied authentic frame so later clips do not clip
    the bbox. Scale is an integer >= 2. The crusader 1098x876 canvas stays the
    recorded file when it already exists; this does not overwrite it.
    """
    meta_path = Path(meta_path)
    source_dir = Path(source_dir)
    if meta_path.is_file():
        contract = load_nn_upscale_contract(meta_path)
        sample = list(source_frames or ())[:1]
        if not sample:
            inventory = inventory_authentic_def_groups(source_dir)
            if IDLE_GROUP not in inventory:
                raise RuntimeError(f"DEF {source_dir} has no idle group for nn-upscale verification")
            sample = inventory[IDLE_GROUP][:1]
        with Image.open(sample[0]) as image:
            size = (int(image.width), int(image.height))
        if size != contract.source_size:
            raise ValueError(
                f"recorded nn-upscale canvas {meta_path} sourceSize {list(contract.source_size)} "
                f"does not match DEF plate {list(size)}"
            )
        return meta_path.resolve()
    frames = list(source_frames) if source_frames is not None else []
    if not frames:
        inventory = inventory_authentic_def_groups(source_dir)
        for group in sorted(inventory):
            frames.extend(inventory[group])
    if not frames:
        raise ValueError(f"cannot build nn-upscale canvas; DEF has no authentic frames: {source_dir}")
    boxes: list[tuple[int, int, int, int]] = []
    sizes: set[tuple[int, int]] = set()
    for path in frames:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            sizes.add((int(rgba.width), int(rgba.height)))
            alpha = np.asarray(rgba)[:, :, 3]
            ys, xs = np.where(alpha > ALPHA_THRESHOLD)
            if len(xs) == 0:
                raise RuntimeError(f"empty alpha — cannot crop nn-upscale union: {path}")
            boxes.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    if len(sizes) != 1:
        raise RuntimeError(f"mixed DEF plate sizes in {source_dir}: {sorted(sizes)}")
    source_width, source_height = next(iter(sizes))
    x0 = max(0, min(box[0] for box in boxes) - int(pad))
    y0 = max(0, min(box[1] for box in boxes) - int(pad))
    x1 = min(source_width - 1, max(box[2] for box in boxes) + int(pad))
    y1 = min(source_height - 1, max(box[3] for box in boxes) + int(pad))
    crop_w = x1 - x0 + 1
    crop_h = y1 - y0 + 1
    scale = max(2, int(round(float(target_edge) / float(max(crop_w, crop_h, 1)))))
    payload = {
        "ok": True,
        "method": NN_UPSCALE_METHOD,
        "generator": "def_selector_shared_union",
        "sourceDir": str(source_dir.resolve()).replace("\\", "/"),
        "sourceSize": [source_width, source_height],
        "unionBBox": [x0, y0, x1, y1],
        "cropSize": [crop_w, crop_h],
        "pad": int(pad),
        "scale": int(scale),
        "outSize": [crop_w * scale, crop_h * scale],
        "frameCount": len(frames),
        "proof": "generated artifact validated — temporally stable NN upscale; not GenAI",
    }
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return meta_path.resolve()


def nn_upscale_native_frame(
    image: Image.Image,
    contract: NnUpscaleContract,
    *,
    plate_kind: str = "frame",
) -> Image.Image:
    """Crop the recorded union bbox and enlarge with nearest-neighbor only."""
    rgba = image.convert("RGBA")
    if (rgba.width, rgba.height) != contract.source_size:
        raise ValueError(
            f"{plate_kind} is {rgba.width}x{rgba.height}, nn upscale contract sourceSize is "
            f"{contract.source_size[0]}x{contract.source_size[1]}"
        )
    alpha = np.asarray(rgba)[:, :, 3]
    ys, xs = np.where(alpha > ALPHA_THRESHOLD)
    if len(xs) == 0:
        raise RuntimeError(f"{plate_kind} has empty alpha; cannot place it on the pose-fit canvas")
    x0, y0, x1, y1 = contract.union_bbox
    overflow_x0 = int(xs.min()) < x0
    overflow_y0 = int(ys.min()) < y0
    overflow_x1 = int(xs.max()) > x1
    overflow_y1 = int(ys.max()) > y1
    if overflow_x0 or overflow_y0 or overflow_x1 or overflow_y1:
        raise RuntimeError(
            f"{plate_kind} subject exceeds the recorded nn-upscale union bbox "
            f"{list(contract.union_bbox)}; refusing to clip. "
            f"frame alpha bbox={[int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]}"
        )
    crop = rgba.crop((x0, y0, x1 + 1, y1 + 1))
    return crop.resize(contract.out_size, Image.Resampling.NEAREST)


def assert_pose_fit_camera_matches_nn_canvas(camera_fit: Path, contract: NnUpscaleContract) -> dict[str, Any]:
    """Pose-fit cameras stay on the nn canvas. Do not scale them to native plates."""
    payload = json.loads(Path(camera_fit).read_text(encoding="utf-8"))
    source = payload.get("sourceResolution")
    if not isinstance(source, list) or len(source) != 2:
        raise ValueError(f"camera fit has no sourceResolution: {camera_fit}")
    source_resolution = (int(source[0]), int(source[1]))
    if source_resolution != contract.out_size:
        raise ValueError(
            f"camera fit {camera_fit} sourceResolution {list(source_resolution)} does not match "
            f"nn-upscale canvas {list(contract.out_size)}. Keep the pose-fit camera; do not "
            "scale pxPerWorld by native RIFE plate width."
        )
    return payload


def materialize_rife_group_frames(
    source_dir: Path,
    output_dir: Path,
    *,
    group: int,
    nn_upscale_meta: Path,
    expected_count: int | None = None,
    target_fps: float = 60.0,
    source_fps: float = 12.0,
    rife_model: str = "rife-v4.6",
    camera_fit: Path | None = None,
) -> dict[str, Any]:
    """Place one lab RIFE group onto the pose-fit nn-upscale canvas."""
    contract = load_nn_upscale_contract(nn_upscale_meta)
    source_paths = _group_paths(source_dir, group)
    if expected_count is not None and len(source_paths) != int(expected_count):
        raise RuntimeError(
            f"RIFE group {int(group):02d} has {len(source_paths)} frames, "
            f"expected {int(expected_count)}"
        )
    if camera_fit is not None:
        assert_pose_fit_camera_matches_nn_canvas(Path(camera_fit), contract)
    output_dir = Path(output_dir)
    source_hashes = [_sha256(path) for path in source_paths]
    manifest_path = output_dir / "rife_frames.json"
    upscale_manifest = contract.to_manifest()
    if output_dir.is_dir() and manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        present = [output_dir / f"{index:02d}.png" for index in range(len(source_paths))]
        if (
            isinstance(existing, dict)
            and existing.get("sourceKind") == "lab_rife_nn_upscale"
            and existing.get("sourceGroup") == int(group)
            and existing.get("sourceDirectory") == str(Path(source_dir).resolve())
            and existing.get("sourceFrameSha256") == source_hashes
            and existing.get("nnUpscale") == upscale_manifest
            and existing.get("sourceResolution") == list(contract.out_size)
            and all(path.is_file() for path in present)
        ):
            with Image.open(present[0]) as image:
                if (int(image.width), int(image.height)) != contract.out_size:
                    raise RuntimeError(
                        f"cached RIFE frame {present[0]} is {image.width}x{image.height}, "
                        f"expected nn canvas {contract.out_size[0]}x{contract.out_size[1]}"
                    )
            return existing
        raise RuntimeError(
            f"refusing to mix a new RIFE copy into {output_dir}; "
            "delete that folder or choose a new target_frame_dir"
        )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"RIFE output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for index, source in enumerate(source_paths):
        dest = output_dir / f"{index:02d}.png"
        with Image.open(source) as image:
            nn_upscale_native_frame(image, contract).save(dest)
        outputs.append(dest.name)
    with Image.open(output_dir / "00.png") as image:
        resolution = [int(image.width), int(image.height)]
    if tuple(resolution) != contract.out_size:
        raise RuntimeError(
            f"wrote RIFE canvas {resolution}, expected nn outSize {list(contract.out_size)}"
        )
    manifest = {
        "schema_version": 1,
        "sourceKind": "lab_rife_nn_upscale",
        "sourceDirectory": str(Path(source_dir).resolve()),
        "sourceGroup": int(group),
        "sourceFrameCount": len(source_paths),
        "sourceFrameSha256": source_hashes,
        "frameDir": str(output_dir.resolve()),
        "frameCount": len(source_paths),
        "frameNames": outputs,
        "frameIndices": list(range(len(source_paths))),
        "sourceFps": float(source_fps),
        "targetFps": float(target_fps),
        "rifeModel": rife_model,
        "nativePlateResolution": list(contract.source_size),
        "sourceResolution": resolution,
        "nnUpscale": upscale_manifest,
        "cameraFit": None if camera_fit is None else str(Path(camera_fit).resolve()),
        "provenance": (
            f"nn-upscaled lab RIFE group {int(group):02d} ({len(source_paths)} frames @ "
            f"{float(target_fps):g} fps) onto pose-fit canvas {resolution[0]}x{resolution[1]} "
            f"via {NN_UPSCALE_METHOD} scale {contract.scale}; not authentic DEF keyframes"
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def materialize_rife_group_sequence(
    source_dir: Path,
    output_dir: Path,
    *,
    groups: Sequence[int],
    expected_counts: Sequence[int],
    nn_upscale_meta: Path,
    target_fps: float = 60.0,
    source_fps: float = 12.0,
    rife_model: str = "rife-v4.6",
    camera_fit: Path | None = None,
) -> dict[str, Any]:
    """Concatenate declared lab RIFE groups onto the pose-fit nn-upscale canvas."""
    plan = normalize_rife_group_plan(groups, expected_counts)
    if plan is None:
        raise ValueError("RIFE sequence requires at least one group")
    group_ids, counts = plan
    if any(count is None for count in counts):
        raise ValueError("concatenated RIFE groups require rife_expected_count for every group")
    if len(group_ids) < 2:
        raise ValueError("RIFE sequence requires at least two groups; use materialize_rife_group_frames for one clip")
    contract = load_nn_upscale_contract(nn_upscale_meta)
    if camera_fit is not None:
        assert_pose_fit_camera_matches_nn_canvas(Path(camera_fit), contract)
    clip_sources: list[tuple[int, str, list[Path]]] = []
    for group, expected in zip(group_ids, counts, strict=True):
        paths = _group_paths(source_dir, int(group))
        if len(paths) != int(expected):
            raise RuntimeError(
                f"RIFE group {int(group):02d} has {len(paths)} frames, expected {int(expected)}"
            )
        clip_sources.append((int(group), def_group_name(int(group)), paths))
    output_dir = Path(output_dir)
    source_hashes = [_sha256(path) for _group, _name, paths in clip_sources for path in paths]
    total = sum(len(paths) for _group, _name, paths in clip_sources)
    if total > 100:
        raise ValueError(
            f"RIFE sequence has {total} frames; numbered outputs use two digits and cap at 100"
        )
    manifest_path = output_dir / "rife_frames.json"
    upscale_manifest = contract.to_manifest()
    clip_plan = []
    cursor = 0
    for group, name, paths in clip_sources:
        clip_plan.append(
            {
                "group": int(group),
                "name": name,
                "startIndex": int(cursor),
                "frameCount": len(paths),
                "frameIndices": list(range(cursor, cursor + len(paths))),
            }
        )
        cursor += len(paths)
    if output_dir.is_dir() and manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        present = [output_dir / f"{index:02d}.png" for index in range(total)]
        if (
            isinstance(existing, dict)
            and existing.get("sourceKind") == "lab_rife_nn_upscale_sequence"
            and existing.get("sourceGroups") == [int(group) for group, _name, _paths in clip_sources]
            and existing.get("sourceDirectory") == str(Path(source_dir).resolve())
            and existing.get("sourceFrameSha256") == source_hashes
            and existing.get("nnUpscale") == upscale_manifest
            and existing.get("sourceResolution") == list(contract.out_size)
            and existing.get("clips") == clip_plan
            and all(path.is_file() for path in present)
        ):
            with Image.open(present[0]) as image:
                if (int(image.width), int(image.height)) != contract.out_size:
                    raise RuntimeError(
                        f"cached RIFE frame {present[0]} is {image.width}x{image.height}, "
                        f"expected nn canvas {contract.out_size[0]}x{contract.out_size[1]}"
                    )
            return existing
        raise RuntimeError(
            f"refusing to mix a new RIFE copy into {output_dir}; "
            "delete that folder or choose a new target_frame_dir"
        )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"RIFE output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    index = 0
    for _group, _name, paths in clip_sources:
        for source in paths:
            dest = output_dir / f"{index:02d}.png"
            with Image.open(source) as image:
                nn_upscale_native_frame(image, contract).save(dest)
            outputs.append(dest.name)
            index += 1
    with Image.open(output_dir / "00.png") as image:
        resolution = [int(image.width), int(image.height)]
    if tuple(resolution) != contract.out_size:
        raise RuntimeError(
            f"wrote RIFE canvas {resolution}, expected nn outSize {list(contract.out_size)}"
        )
    manifest = {
        "schema_version": 1,
        "sourceKind": "lab_rife_nn_upscale_sequence",
        "sourceDirectory": str(Path(source_dir).resolve()),
        "sourceGroups": [int(group) for group, _name, _paths in clip_sources],
        "sourceFrameCount": total,
        "sourceFrameSha256": source_hashes,
        "clips": clip_plan,
        "frameDir": str(output_dir.resolve()),
        "frameCount": total,
        "frameNames": outputs,
        "frameIndices": list(range(total)),
        "sourceFps": float(source_fps),
        "targetFps": float(target_fps),
        "rifeModel": rife_model,
        "nativePlateResolution": list(contract.source_size),
        "sourceResolution": resolution,
        "nnUpscale": upscale_manifest,
        "cameraFit": None if camera_fit is None else str(Path(camera_fit).resolve()),
        "provenance": (
            "nn-upscaled lab RIFE sequence "
            + ", ".join(
                f"{name} g{int(group):02d} ({len(paths)} frames)"
                for group, name, paths in clip_sources
            )
            + f" @ {float(target_fps):g} fps onto pose-fit canvas "
            f"{resolution[0]}x{resolution[1]} via {NN_UPSCALE_METHOD} scale {contract.scale}; "
            "not authentic DEF keyframes"
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def materialize_def_group_sequence(
    source_dir: Path,
    output_dir: Path,
    *,
    groups: Sequence[int],
    expected_counts: Sequence[int],
    nn_upscale_meta: Path,
    target_fps: float = 12.0,
    source_fps: float = 12.0,
    camera_fit: Path | None = None,
) -> dict[str, Any]:
    """Copy one or more authentic 12 fps DEF groups onto the pose-fit nn-upscale canvas.

    One group is a single clip (idle-only or a motion-only diagnostic such as
    attack-front). Several groups concatenate in order. RIFE interpolation can
    drop a prop on one frame and keep it gone. This lane copies the original
    DEF keyframes only.
    """
    plan = normalize_def_group_plan(groups, expected_counts)
    if plan is None:
        raise ValueError("DEF sequence requires at least one group")
    group_ids, counts = plan
    if any(count is None for count in counts):
        raise ValueError("concatenated DEF groups require def_expected_count for every group")
    output_dir = Path(output_dir)
    output_name = output_dir.name.lower()
    if output_name.startswith("frames_rife"):
        raise ValueError(f"authentic DEF sequence must not write into a RIFE folder: {output_dir}")
    if output_name == "frames_ground_truth":
        raise ValueError("DEF sequence must not overwrite frames_ground_truth")
    contract = load_nn_upscale_contract(nn_upscale_meta)
    if camera_fit is not None:
        assert_pose_fit_camera_matches_nn_canvas(Path(camera_fit), contract)
    clip_sources: list[tuple[int, str, list[Path]]] = []
    for group, expected in zip(group_ids, counts, strict=True):
        paths = _authentic_def_group_paths(source_dir, int(group))
        if len(paths) != int(expected):
            raise RuntimeError(
                f"authentic DEF group {int(group):02d} has {len(paths)} frames, "
                f"expected {int(expected)}"
            )
        clip_sources.append((int(group), def_group_name(int(group)), paths))
    source_hashes = [_sha256(path) for _group, _name, paths in clip_sources for path in paths]
    total = sum(len(paths) for _group, _name, paths in clip_sources)
    if total > 100:
        raise ValueError(
            f"DEF sequence has {total} frames; numbered outputs use two digits and cap at 100"
        )
    manifest_path = output_dir / "def_frames.json"
    upscale_manifest = contract.to_manifest()
    clip_plan = []
    cursor = 0
    for group, name, paths in clip_sources:
        clip_plan.append(
            {
                "group": int(group),
                "name": name,
                "startIndex": int(cursor),
                "frameCount": len(paths),
                "frameIndices": list(range(cursor, cursor + len(paths))),
            }
        )
        cursor += len(paths)
    if output_dir.is_dir() and (output_dir / "rife_frames.json").is_file():
        raise RuntimeError(
            f"refusing to mix authentic DEF frames into a RIFE folder: {output_dir}"
        )
    if output_dir.is_dir() and manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        present = [output_dir / f"{index:02d}.png" for index in range(total)]
        source_groups = [int(group) for group, _name, _paths in clip_sources]
        resolved_source = str(Path(source_dir).resolve())
        if (
            isinstance(existing, dict)
            and existing.get("sourceKind") == "authentic_def_nn_upscale_sequence"
            and existing.get("sourceGroups") == source_groups
            and existing.get("sourceFrameSha256") == source_hashes
            and existing.get("nnUpscale") == upscale_manifest
            and existing.get("sourceResolution") == list(contract.out_size)
            and existing.get("clips") == clip_plan
            and all(path.is_file() for path in present)
        ):
            with Image.open(present[0]) as image:
                if (int(image.width), int(image.height)) != contract.out_size:
                    raise RuntimeError(
                        f"cached DEF frame {present[0]} is {image.width}x{image.height}, "
                        f"expected nn canvas {contract.out_size[0]}x{contract.out_size[1]}"
                    )
            if existing.get("sourceDirectory") != resolved_source:
                # Lab trees move (source-tree vs BepInEx plugin copy). Frame
                # hashes already proved the plates are the same; keep the
                # cached PNGs and record the live path.
                existing = dict(existing)
                existing["sourceDirectory"] = resolved_source
                manifest_path.write_text(
                    json.dumps(existing, indent=2) + "\n",
                    encoding="utf-8",
                )
            return existing
        raise RuntimeError(
            f"refusing to mix a new authentic DEF copy into {output_dir}; "
            "delete that folder or choose a new target_frame_dir"
        )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"DEF output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    index = 0
    for _group, _name, paths in clip_sources:
        for source in paths:
            dest = output_dir / f"{index:02d}.png"
            with Image.open(source) as image:
                nn_upscale_native_frame(image, contract, plate_kind="authentic DEF frame").save(dest)
            outputs.append(dest.name)
            index += 1
    with Image.open(output_dir / "00.png") as image:
        resolution = [int(image.width), int(image.height)]
    if tuple(resolution) != contract.out_size:
        raise RuntimeError(
            f"wrote DEF canvas {resolution}, expected nn outSize {list(contract.out_size)}"
        )
    manifest = {
        "schema_version": 1,
        "sourceKind": "authentic_def_nn_upscale_sequence",
        "sourceDirectory": str(Path(source_dir).resolve()),
        "sourceGroups": [int(group) for group, _name, _paths in clip_sources],
        "sourceFrameCount": total,
        "sourceFrameSha256": source_hashes,
        "clips": clip_plan,
        "frameDir": str(output_dir.resolve()),
        "frameCount": total,
        "frameNames": outputs,
        "frameIndices": list(range(total)),
        "sourceFps": float(source_fps),
        "targetFps": float(target_fps),
        "nativePlateResolution": list(contract.source_size),
        "sourceResolution": resolution,
        "nnUpscale": upscale_manifest,
        "cameraFit": None if camera_fit is None else str(Path(camera_fit).resolve()),
        "provenance": (
            "nn-upscaled authentic DEF sequence "
            + ", ".join(
                f"{name} g{int(group):02d} ({len(paths)} frames)"
                for group, name, paths in clip_sources
            )
            + f" @ {float(target_fps):g} fps onto pose-fit canvas "
            f"{resolution[0]}x{resolution[1]} via {NN_UPSCALE_METHOD} scale {contract.scale}; "
            "not RIFE interpolation"
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def ensure_authentic_def_idle_profile_dir(
    *,
    idle_pilot: Path,
    lab_dir: Path,
    nn_upscale_meta: Path,
    target_fps: float = 12.0,
) -> Path:
    """Materialize lab idle (DEF group 2) for camera yaw on motion-only clips.

    Writes the picker ``idle`` folder so a later idle-only fit reuses the same
    plates. Does not copy the current clip's folder name under idle/.
    """
    from alpha_shadow_cull import cull_alpha_shadows

    idle_pilot = Path(idle_pilot)
    raw = idle_pilot / "frames_def12_nn_idle"
    culled = idle_pilot / "frames_def12_nn_idle_shadow_culled"
    if culled.is_dir() and (culled / "00.png").is_file():
        return culled.resolve()
    inventory = inventory_authentic_def_groups(Path(lab_dir))
    if IDLE_GROUP not in inventory:
        raise FileNotFoundError(
            f"lab has no idle DEF group {IDLE_GROUP:02d} for profile yaw: {lab_dir}"
        )
    idle_count = len(inventory[IDLE_GROUP])
    materialize_def_group_sequence(
        Path(lab_dir),
        raw,
        groups=(IDLE_GROUP,),
        expected_counts=(idle_count,),
        target_fps=float(target_fps),
        nn_upscale_meta=Path(nn_upscale_meta),
        camera_fit=None,
    )
    cull_alpha_shadows(raw, culled)
    if not (culled / "00.png").is_file():
        raise FileNotFoundError(f"idle profile plates were written without 00.png: {culled}")
    return culled.resolve()
