"""Exact pose reference for owned binding: registered capture + DEF frames + camera.

Two independent lanes can describe an animation of an AI-generated mesh:

* a **2D-only** lane, which sees the DEF plates and everything that can be read off
  them (``reference_frames.py``), and
* an **exact** lane, which lifts the DEF plates into per-frame 3D joints with a
  mocap model (``experiments/homm3_mocap_v2``) and registers that capture onto the
  mesh under one global similarity.

When the exact lane exists, the animation is fully known: for every authored DEF
frame there is a 3D joint configuration and its 2D projection, and the DEF alpha is
the silhouette that configuration produced.  A bind can then be scored against
ground truth - a misplaced joint or a wrongly owned vertex is a measurable
millimetre or pixel, not a tolerance judgement and not a rendered-image score.

Three separate contracts are consumed here, each with its own provenance:

* capture - ``raw_capture.npz`` with ``pred_position`` (F, J, 3), ``joint_names``
  (J,) and ``parents`` (J,), the sanctioned motion interface of that lane;
* registration - the ``idle0_registration.json`` written by
  ``experiments/homm3_mocap_v2/static_bind_registration.py``, which states the
  capture -> mesh similarity and the source-view camera;
* framing - ``master_sequence.json``, which states which authored DEF plate each
  capture frame was observed from.

Nothing here is a rig.  The similarity and the camera are *reference* quantities;
the bone hierarchy, the joint placement and the skin weights are authored by the
bind solver and audited afterwards.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

SOURCE_SCHEMA = "pose_reference_source.v1"
REGISTRATION_SCHEMA = "homm3.static-bind-registration.v1"


class ReferenceInconsistentError(RuntimeError):
    """The capture, the mesh, the registration and the plates are not one subject.

    Raised wherever a reference could be read two ways at once.  An owned bind must not be
    authored from a reference that cannot state one pose per authored frame.
    """


def yaw_pitch_basis_rows(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    """``[right, down, forward]`` for an upright orthographic source view.

    Screen ``y`` grows downward, so the second basis row is deliberately the *down*
    direction; callers must not read it as "up".  This mirrors
    ``experiments/homm3_mocap_v2/skin_camera_registration.py::_basis_yup`` and
    ``tools/homm3_silhouette_pose_fit/homm3_pose_camera.py`` so a camera recorded by
    either lane lands in the same convention.
    """
    yaw = np.deg2rad(float(yaw_deg))
    pitch = np.deg2rad(float(pitch_deg))
    right = np.asarray((np.cos(yaw), 0.0, np.sin(yaw)), dtype=np.float64)
    down = np.asarray(
        (-np.sin(pitch) * np.sin(yaw), -np.cos(pitch), np.sin(pitch) * np.cos(yaw)),
        dtype=np.float64,
    )
    forward = np.cross(right, down)
    forward /= max(float(np.linalg.norm(forward)), 1e-12)
    return np.stack((right, down, forward), axis=0)


@dataclass(frozen=True)
class SpriteCameraFit:
    """Orthographic camera in the mesh frame: ``px = [p.right, p.down] * k + offset``.

    The projected pair is an *image* coordinate (``y`` grows downward), which is why
    the second axis is named ``down``.  ``forward`` points away from the viewer, so a
    point may be slid along ``-forward`` without changing its pixel - that is the only
    degree of freedom the plates leave open.
    """

    right: np.ndarray  # (3,)
    down: np.ndarray  # (3,)
    px_per_world: float
    offset_px: np.ndarray  # (2,)
    sprite_size: tuple[int, int]  # (width, height)
    camera_policy: str
    source: str
    world_frame: str = "y_up_gltf"
    mean_landmark_error_px: float | None = None

    @property
    def forward(self) -> np.ndarray:
        out = np.cross(self.right, self.down)
        return out / max(float(np.linalg.norm(out)), 1e-12)

    @property
    def basis_rows(self) -> np.ndarray:
        return np.stack((self.right, self.down), axis=0)

    def project(self, points: np.ndarray) -> np.ndarray:
        """``(..., 3)`` mesh points -> ``(..., 2)`` image pixels."""
        pts = np.asarray(points, dtype=np.float64)
        flat = pts.reshape(-1, 3)
        screen = (flat @ self.basis_rows.T) * self.px_per_world + self.offset_px
        return screen.reshape(pts.shape[:-1] + (2,))

    def depth(self, points: np.ndarray) -> np.ndarray:
        """Distance along ``forward``; larger is farther from the viewer."""
        pts = np.asarray(points, dtype=np.float64)
        return pts.reshape(-1, 3) @ self.forward

    def slide_along_view(self, points: np.ndarray, delta: np.ndarray) -> np.ndarray:
        """Move points by ``delta`` along ``-forward`` - a pure depth edit."""
        pts = np.asarray(points, dtype=np.float64)
        return pts - self.forward[None, :] * np.asarray(delta, dtype=np.float64).reshape(-1, 1)

    def world_per_px(self) -> float:
        if self.px_per_world <= 0.0:
            raise ValueError("sprite camera fit has non-positive pxPerWorld")
        return 1.0 / self.px_per_world

    def as_report(self) -> dict[str, Any]:
        return {
            "basisScreenRows": self.basis_rows.tolist(),
            "pxPerWorld": float(self.px_per_world),
            "screenOffsetPx": self.offset_px.tolist(),
            "sourceResolution": [int(self.sprite_size[0]), int(self.sprite_size[1])],
            "worldFrame": self.world_frame,
            "cameraPolicy": self.camera_policy,
            "source": self.source,
        }


def camera_fit_from_payload(
    payload: dict[str, Any],
    *,
    sprite_size: tuple[int, int],
    source: str,
    world_frame: str,
) -> SpriteCameraFit:
    """Build a camera from the shared ``basisScreenRows``/``pxPerWorld`` contract.

    ``world_frame`` is a required argument on purpose: the job-camera artifacts record
    a Z-up basis while a registration records a Y-up one, and guessing would silently
    reinterpret the axis.  The caller states the frame it knows the mesh is in.
    """
    rows = payload.get("basisScreenRows")
    if rows is None:
        raise ValueError("camera payload has no basisScreenRows")
    basis = np.asarray(rows, dtype=np.float64)
    if basis.shape != (2, 3) and basis.shape != (3, 3):
        raise ValueError(f"basisScreenRows must be 2x3 or 3x3; got {basis.shape}")
    if not np.isfinite(basis).all():
        raise ValueError("basisScreenRows must be finite")
    right = basis[0] / max(float(np.linalg.norm(basis[0])), 1e-12)
    down = basis[1] / max(float(np.linalg.norm(basis[1])), 1e-12)
    if abs(float(np.dot(right, down))) > 1e-4:
        raise ValueError("basisScreenRows rows must be orthogonal")
    scale = float(payload.get("pxPerWorld") or payload.get("scale") or 0.0)
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("camera payload needs a finite positive pxPerWorld")
    offset_raw = payload.get("screenOffsetPx")
    if offset_raw is None:
        offset_raw = payload.get("offset")
    if offset_raw is None:
        raise ValueError("camera payload has no screenOffsetPx")
    offset = np.asarray(offset_raw, dtype=np.float64).reshape(-1)
    if offset.shape != (2,) or not np.isfinite(offset).all():
        raise ValueError("screenOffsetPx must be a finite pair")
    declared = payload.get("sourceResolution")
    if declared is not None:
        declared_pair = (int(declared[0]), int(declared[1]))
        if declared_pair != (int(sprite_size[0]), int(sprite_size[1])):
            raise ValueError(
                f"camera sourceResolution {declared_pair} != frame size {tuple(sprite_size)}; "
                "the camera and the plates must come from the same canvas"
            )
    return SpriteCameraFit(
        right=right,
        down=down,
        px_per_world=scale,
        offset_px=offset,
        sprite_size=(int(sprite_size[0]), int(sprite_size[1])),
        camera_policy=str(payload.get("cameraPolicy") or payload.get("policy") or "unknown"),
        source=source,
        world_frame=world_frame,
        mean_landmark_error_px=(
            None
            if payload.get("meanLandmarkErrorPx") is None
            else float(payload["meanLandmarkErrorPx"])
        ),
    )


def load_sprite_camera_fit(
    path: Path,
    *,
    sprite_size: tuple[int, int],
    world_frame: str,
) -> SpriteCameraFit:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"sprite camera fit missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return camera_fit_from_payload(
        payload,
        sprite_size=sprite_size,
        source=str(path.resolve()).replace("\\", "/"),
        world_frame=world_frame,
    )


@dataclass(frozen=True)
class CaptureToWorld:
    """Uniform similarity placing capture joints in the mesh frame.

    ``world = scale * (capture @ rotation.T) + translation``, matching
    ``static_bind_registration.py::apply_similarity``.  The registration is reference
    data - it says where the animation's joints are, not how the mesh should be rigged.
    """

    rotation: np.ndarray  # (3, 3)
    scale: float
    translation: np.ndarray  # (3,)
    policy: str
    source: str

    @staticmethod
    def identity(source: str = "identity") -> "CaptureToWorld":
        return CaptureToWorld(
            rotation=np.eye(3),
            scale=1.0,
            translation=np.zeros(3),
            policy="identity",
            source=source,
        )

    def __post_init__(self) -> None:
        rotation = np.asarray(self.rotation, dtype=np.float64)
        translation = np.asarray(self.translation, dtype=np.float64).reshape(-1)
        if rotation.shape != (3, 3):
            raise ValueError(f"rotation must be 3x3; got {rotation.shape}")
        if abs(float(np.linalg.det(rotation)) - 1.0) > 1e-5:
            raise ValueError("capture similarity rotation must be a proper rotation")
        if not np.isfinite(rotation).all() or not np.isfinite(translation).all():
            raise ValueError("capture similarity must be finite")
        if translation.shape != (3,):
            raise ValueError("capture similarity translation must be a 3-vector")
        if not np.isfinite(self.scale) or float(self.scale) <= 0.0:
            raise ValueError("capture similarity scale must be finite and positive")

    def apply(self, points: np.ndarray) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float64)
        flat = pts.reshape(-1, 3)
        return (float(self.scale) * (flat @ self.rotation.T) + self.translation).reshape(pts.shape)

    def inverse_apply(self, points: np.ndarray) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float64)
        flat = pts.reshape(-1, 3)
        return (((flat - self.translation) / float(self.scale)) @ self.rotation).reshape(pts.shape)

    def scaled_about(self, pivot_world: np.ndarray, factor: float) -> "CaptureToWorld":
        """Rescale in world space about ``pivot_world`` - a uniform, exact correction."""
        factor = float(factor)
        if not np.isfinite(factor) or factor <= 0.0:
            raise ValueError("scale factor must be finite and positive")
        pivot = np.asarray(pivot_world, dtype=np.float64).reshape(3)
        translation = pivot + factor * (self.translation - pivot)
        return CaptureToWorld(
            rotation=self.rotation.copy(),
            scale=float(self.scale) * factor,
            translation=translation,
            policy=f"{self.policy}+rescaled_x{factor:.6f}",
            source=self.source,
        )

    def as_report(self) -> dict[str, Any]:
        return {
            "rotation": np.asarray(self.rotation).tolist(),
            "scale": float(self.scale),
            "translation": np.asarray(self.translation).tolist(),
            "policy": self.policy,
            "source": self.source,
        }


def load_capture_similarity(registration: Path) -> CaptureToWorld:
    """Capture -> mesh similarity from an accepted static bind registration."""
    path = Path(registration)
    if not path.is_file():
        raise FileNotFoundError(f"registration missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("schema")) != REGISTRATION_SCHEMA:
        raise ValueError(
            f"{path}: schema {payload.get('schema')!r} is not {REGISTRATION_SCHEMA!r}"
        )
    acceptance = payload.get("acceptance") or {}
    if not acceptance.get("accepted"):
        raise ValueError(
            f"{path}: registration was not accepted ({acceptance.get('status')!r}); "
            "an owned bind must not consume a rejected reference registration"
        )
    candidates = ((payload.get("views") or {}).get("candidates")) or []
    if not candidates:
        raise ValueError(f"{path}: registration has no view candidates")
    similarity = candidates[0].get("skeletonSimilarity")
    if not isinstance(similarity, dict):
        raise ValueError(f"{path}: candidate has no skeletonSimilarity")
    for key in ("rotation", "scale", "translation"):
        if key not in similarity:
            raise ValueError(f"{path}: skeletonSimilarity has no {key}")
    return CaptureToWorld(
        rotation=np.asarray(similarity["rotation"], dtype=np.float64),
        scale=float(similarity["scale"]),
        translation=np.asarray(similarity["translation"], dtype=np.float64),
        policy=str(similarity.get("policy") or "unknown"),
        source=str(path.resolve()).replace("\\", "/"),
    )


@dataclass(frozen=True)
class AuthoredFrame:
    """One authored DEF plate that the capture observed, in playback order."""

    index: int  # authored frame index == capture index in this lane
    def_group: int
    clip_key: str
    local_index: int
    role: str
    source_png: str


@dataclass
class PoseSource:
    """Exact per-authored-frame reference: 3D joints, their projection, and the alpha."""

    source_capture: str
    source_registration: str
    joint_names: list[str]
    parents: list[int | None]
    capture_positions: np.ndarray  # (Fcap, J, 3) capture space
    capture_indices: np.ndarray  # (F,)
    frames: list[AuthoredFrame]
    camera: SpriteCameraFit
    alpha: np.ndarray  # (F, H, W) uint8; DEF coverage per authored frame
    similarity: CaptureToWorld
    bind_frame: int
    bind_alpha: np.ndarray | None = None  # (H, W) uint8; coverage of the plate the mesh came from
    mesh_source: str | None = None
    mesh_sha256: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def joint_count(self) -> int:
        return len(self.joint_names)

    @property
    def frame_count(self) -> int:
        return int(self.capture_indices.shape[0])

    @property
    def sprite_size(self) -> tuple[int, int]:
        return self.camera.sprite_size

    def positions(self) -> np.ndarray:
        """``(F, J, 3)`` exact joints per authored frame, in the mesh frame."""
        return self.similarity.apply(self.capture_positions[self.capture_indices])

    def capture_space_positions(self) -> np.ndarray:
        return self.capture_positions[self.capture_indices]

    def projected_joints(self) -> np.ndarray:
        """``(F, J, 2)`` exact DEF pixels of every joint per authored frame."""
        return self.camera.project(self.positions())

    def bind_index(self) -> int:
        """Capture index of the pose the mesh was generated from (the bind frame)."""
        if not 0 <= self.bind_frame < self.capture_positions.shape[0]:
            raise ValueError(
                f"bind frame {self.bind_frame} is outside the capture "
                f"({self.capture_positions.shape[0]} frames)"
            )
        return int(self.bind_frame)

    def bind_positions(self) -> np.ndarray:
        """``(J, 3)`` exact joints of the bind frame, in the mesh frame.

        This is the pose the mesh was generated from, so it is the only reference
        placement the rest skeleton may be compared against.
        """
        return self.similarity.apply(self.capture_positions[self.bind_index()])

    def bind_coverage(self) -> np.ndarray:
        """Boolean coverage of the plate the mesh was generated from.

        Kept independently of the audited segment: the bind rest is that plate's pose, so the
        replay acceptance is defined against it even when a motion clip is being audited.
        """
        if self.bind_alpha is None:
            raise ValueError("pose source has no bind plate coverage")
        return self.bind_alpha > 0

    def group_of(self, authored_index: int) -> int:
        return int(self.frames[authored_index].def_group)

    def coverage(self, authored_index: int) -> np.ndarray:
        """Boolean DEF coverage mask for one authored frame."""
        return self.alpha[authored_index] > 0


def _normalize_parents(raw: np.ndarray, joint_count: int) -> list[int | None]:
    parents: list[int | None] = []
    values = np.asarray(raw).reshape(-1)
    for index in range(joint_count):
        value = values[index] if index < values.shape[0] else -1
        if isinstance(value, float) and np.isnan(value):
            parents.append(None)
            continue
        parent = int(value)
        parents.append(None if parent < 0 or parent == index else parent)
    for joint, parent in enumerate(parents):
        if parent is not None and not 0 <= parent < joint_count:
            raise ValueError(f"capture parent {parent} for joint {joint} is out of range")
    roots = [joint for joint, parent in enumerate(parents) if parent is None]
    if len(roots) != 1:
        raise ValueError(
            f"capture must have exactly one root joint; got {len(roots)} at {roots}"
        )
    for joint in range(joint_count):
        walk: int | None = joint
        chain: set[int] = set()
        while walk is not None:
            if walk in chain:
                raise ValueError(f"capture parent chain for joint {joint} is cyclic")
            chain.add(walk)
            walk = parents[walk]
    return parents


def load_capture(capture: Path) -> tuple[list[str], list[int | None], np.ndarray]:
    capture = Path(capture)
    if not capture.is_file():
        raise FileNotFoundError(f"mocap capture missing: {capture}")
    with np.load(capture, allow_pickle=False) as raw:
        required = {"pred_position", "joint_names", "parents"}
        missing = sorted(required - set(raw.files))
        if missing:
            raise ValueError(f"{capture}: capture is missing {missing}")
        positions = np.asarray(raw["pred_position"], dtype=np.float64)
        names = [str(name) for name in np.asarray(raw["joint_names"]).astype(str).tolist()]
        parent_values = np.asarray(raw["parents"]).reshape(-1)
    if positions.ndim != 3 or positions.shape[2] != 3:
        raise ValueError(f"{capture}: pred_position must be (F, J, 3); got {positions.shape}")
    if positions.shape[1] != len(names):
        raise ValueError(
            f"{capture}: pred_position joint count {positions.shape[1]} != joint_names {len(names)}"
        )
    if not np.isfinite(positions).all():
        raise ValueError(f"{capture}: pred_position contains non-finite values")
    return names, _normalize_parents(parent_values, len(names)), positions


def _load_alpha(paths: list[Path]) -> np.ndarray:
    """Load every authored plate's alpha and require one shared canvas."""
    from PIL import Image

    rows: list[np.ndarray] = []
    size: tuple[int, int] | None = None
    for path in paths:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"authored DEF frame missing: {path}")
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            if size is None:
                size = (int(rgba.width), int(rgba.height))
            elif rgba.size != size:
                raise ValueError(
                    f"{path}: size {rgba.size} != {size}; every authored plate in one clip "
                    "must share one canvas or the camera is not fixed"
                )
            rows.append(np.asarray(rgba.split()[-1], dtype=np.uint8))
    if not rows:
        raise ValueError("pose source needs at least one authored frame")
    return np.stack(rows, axis=0)


def load_registered_pose_source(
    *,
    capture: Path,
    registration: Path,
    master_sequence: Path,
    segment_index: int | None = None,
    clip_key: str | None = None,
    max_frames: int | None = None,
    source_view_yaw_offset_deg: float = 0.0,
) -> PoseSource:
    """Load the exact reference for one slide of one linked-master run.

    ``master_sequence.json`` is the framing authority: ``frames[i]`` names the authored DEF
    plate observed at capture index ``i``.  The two lists must agree in length, so a
    truncated or reordered capture fails closed instead of silently shifting poses.

    The scope is one **segment**, not a DEF group.  A linked-master reel repeats the idle
    plate as a bookend around every other clip, and the capture assigns those repeats
    different joint configurations (measured 7.2 px apart on identical pixels for the
    wood elf), so a group filter would hand the audit several mutually inconsistent
    references for one plate.  By default the segment containing the bind frame is used.
    """
    capture = Path(capture)
    registration = Path(registration)
    master = Path(master_sequence)
    if not master.is_file():
        raise FileNotFoundError(f"master sequence missing: {master}")
    payload = json.loads(master.read_text(encoding="utf-8"))
    rows = payload.get("frames")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{master}: master sequence has no frames")
    names, parents, positions = load_capture(capture)
    if len(rows) != positions.shape[0]:
        raise ValueError(
            f"{master}: {len(rows)} authored frames != {positions.shape[0]} capture frames; "
            "the sequence and the capture were not produced together"
        )
    reg_payload = json.loads(registration.read_text(encoding="utf-8"))
    bind_frame = int(reg_payload.get("bindFrame", payload.get("bindGlobalIndex", -1)))
    declared_bind = int(payload.get("bindGlobalIndex", bind_frame))
    if bind_frame != declared_bind:
        raise ValueError(
            f"bind frame disagrees: registration says {bind_frame}, master sequence says "
            f"{declared_bind}; the reference is inconsistent and must not be consumed"
        )

    all_frames: list[AuthoredFrame] = []
    for index, row in enumerate(rows):
        if int(row.get("globalIndex", -1)) != index:
            raise ValueError(
                f"{master}: frames[{index}].globalIndex is {row.get('globalIndex')!r}; "
                "the sequence must be in capture order"
            )
        all_frames.append(
            AuthoredFrame(
                index=index,
                def_group=int(row["defGroup"]),
                clip_key=str(row.get("clipKey") or ""),
                local_index=int(row.get("localIndex", 0)),
                role=str(row.get("role") or ""),
                source_png=str(row["sourcePng"]).replace("\\", "/"),
            )
        )

    segments = payload.get("segments") or []
    if not isinstance(segments, list) or not segments:
        raise ValueError(f"{master}: master sequence has no segments; the clip scope is unknown")
    selected = _select_segment(
        segments=segments,
        bind_frame=bind_frame,
        segment_index=segment_index,
        clip_key=clip_key,
        frame_count=len(all_frames),
    )
    if max_frames is not None:
        if int(max_frames) <= 0:
            raise ValueError("max_frames must be positive")
        selected = selected[: int(max_frames)]
    frames = [all_frames[index] for index in selected]

    seen: dict[str, int] = {}
    for frame in frames:
        if frame.source_png in seen:
            raise ReferenceInconsistentError(
                f"fail-closed: authored plates {seen[frame.source_png]} and {frame.index} are the "
                f"same plate ({frame.source_png}) with different captured poses; the reference is "
                "not single-valued over this scope, so no bind can be audited against it. Audit one "
                "clip segment (role=cycle) instead of a bookended group."
            )
        seen[frame.source_png] = frame.index

    alpha = _load_alpha([Path(frame.source_png) for frame in frames])
    bind_alpha = _load_alpha([Path(all_frames[bind_frame].source_png)])[0]
    if bind_alpha.shape != alpha.shape[1:]:
        raise ValueError(
            f"the bind plate {all_frames[bind_frame].source_png} is {bind_alpha.shape} but the "
            f"audited plates are {alpha.shape[1:]}; the camera is not fixed across them"
        )
    camera = load_registration_camera_fit(
        registration,
        sprite_size=(int(alpha.shape[2]), int(alpha.shape[1])),
        source_view_yaw_offset_deg=source_view_yaw_offset_deg,
    )
    similarity = load_capture_similarity(registration)
    return PoseSource(
        source_capture=str(capture.resolve()).replace("\\", "/"),
        source_registration=str(registration.resolve()).replace("\\", "/"),
        joint_names=names,
        parents=parents,
        capture_positions=positions,
        capture_indices=np.asarray(selected, dtype=np.int64),
        frames=frames,
        camera=camera,
        alpha=alpha,
        similarity=similarity,
        bind_frame=bind_frame,
        bind_alpha=bind_alpha,
        mesh_source=str(reg_payload.get("mesh") or "") or None,
        extra={
            "unit": payload.get("unit"),
            "masterSequence": str(master.resolve()).replace("\\", "/"),
            "masterSequenceSchema": payload.get("schema"),
            "masterSequencePolicy": payload.get("reelPolicy"),
            "registrationCandidatePolicy": similarity.policy,
            "registrationBindGroup": reg_payload.get("bindGroup"),
            "declaredFrameCount": int(payload.get("frameCount", len(rows))),
            "sourceFrameMs": payload.get("sourceFrameMs"),
            "sourceViewYawOffsetDeg": float(source_view_yaw_offset_deg),
        },
    )


def _select_segment(
    *,
    segments: list[dict[str, Any]],
    bind_frame: int,
    segment_index: int | None,
    clip_key: str | None,
    frame_count: int,
) -> list[int]:
    """Resolve one segment of a linked-master reel to authored frame indices."""
    def span(segment: dict[str, Any]) -> tuple[int, int]:
        try:
            start = int(segment["globalStart"])
            end = int(segment["globalEnd"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"segment {segment.get('segmentIndex')!r} has no usable range") from exc
        if not 0 <= start < end <= frame_count:
            raise ValueError(
                f"segment {segment.get('segmentIndex')!r} range [{start},{end}) is outside the "
                f"capture ({frame_count} frames)"
            )
        return start, end

    if segment_index is not None:
        matches = [s for s in segments if int(s.get("segmentIndex", -1)) == int(segment_index)]
        if len(matches) != 1:
            raise ValueError(f"segment index {segment_index} matches {len(matches)} segments")
        chosen = matches[0]
    elif clip_key is not None:
        matches = [
            s
            for s in segments
            if str(s.get("clipKey")) == str(clip_key) and str(s.get("role")) != "bookend"
        ]
        if len(matches) != 1:
            raise ValueError(
                f"clip {clip_key!r} matches {len(matches)} non-bookend segments; the scope is "
                "ambiguous"
            )
        chosen = matches[0]
    else:
        matches = [s for s in segments if span(s)[0] <= bind_frame < span(s)[1]]
        if len(matches) != 1:
            raise ValueError(
                f"bind frame {bind_frame} falls in {len(matches)} segments; the clip scope is "
                "ambiguous"
            )
        chosen = matches[0]
    start, end = span(chosen)
    return list(range(start, end))


def load_registration_camera_fit(
    registration: Path,
    *,
    sprite_size: tuple[int, int],
    source_view_yaw_offset_deg: float = 0.0,
) -> SpriteCameraFit:
    """Source-view camera recorded by the static bind registration.

    That artifact stores ``yawDeg``/``pitchDeg`` rather than basis rows, in the mesh
    frame the mesh was generated in (glTF Y-up).  The rows are re-derived here and the
    recorded scale/offset are consumed unchanged - they were fitted by matching the
    mesh's projected bounds to the DEF plate's subject bounds.
    """
    path = Path(registration)
    if not path.is_file():
        raise FileNotFoundError(f"registration missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("schema")) != REGISTRATION_SCHEMA:
        raise ValueError(
            f"{path}: schema {payload.get('schema')!r} is not {REGISTRATION_SCHEMA!r}"
        )
    candidates = ((payload.get("views") or {}).get("candidates")) or []
    if not candidates:
        raise ValueError(f"{path}: registration has no view candidates")
    camera = candidates[0].get("camera")
    if not isinstance(camera, dict):
        raise ValueError(f"{path}: candidate has no camera")
    for key in ("scale", "offset", "yawDeg", "pitchDeg"):
        if key not in camera:
            raise ValueError(f"{path}: camera has no {key}")
    offset = float(source_view_yaw_offset_deg)
    if not np.isfinite(offset):
        raise ValueError("source_view_yaw_offset_deg must be finite")
    base_yaw = float(camera["yawDeg"])
    effective_yaw = base_yaw + offset
    basis = yaw_pitch_basis_rows(effective_yaw, float(camera["pitchDeg"]))[:2]
    return camera_fit_from_payload(
        {
            "basisScreenRows": basis,
            "pxPerWorld": float(camera["scale"]),
            "screenOffsetPx": camera["offset"],
            "cameraPolicy": f"{camera.get('sourceViewPolicy') or 'registration_source_view'}"
            f"|yaw{base_yaw}|pitch{camera['pitchDeg']}|yawOffset{offset:g}",
        },
        sprite_size=sprite_size,
        source=str(path.resolve()).replace("\\", "/"),
        world_frame="y_up_gltf",
    )


load_capture = load_capture
load_registered_pose_source = load_registered_pose_source
load_capture_similarity = load_capture_similarity
load_registration_camera_fit = load_registration_camera_fit
camera_fit_from_payload = camera_fit_from_payload
yaw_pitch_basis_rows = yaw_pitch_basis_rows
load_sprite_camera_fit = load_sprite_camera_fit
