"""Per-keyframe combined-score repair over deployed Stronghold clips.

Inputs (all on disk, verified):
- Deployed clips: ``artifacts/homm3_mocap_v2/stronghold_oe_approved_v1/units/<labSid>/Unit_*.glb``
  (each embeds the full rest mesh + rotation-only animation; frame counts match
  the DEF group 1:1, e.g. goblin Move 9/9, Idle 8/8).
- Source plates: install-side lab
  ``<install>/BepInEx/plugins/OfflineUnlockMod/homm3_lab/<labSid>/extracted_battle_source_12fps/<DEF>.dir/GG_FF.png``
  plus ``<DEF>.json`` sequences; clip frame *i* <-> group plate *i*.
- Skin sidecar: ``.../units/<labSid>/skin_weights.json`` (flat 10528x8 for
  goblin; joint order == GLB nodes 0..24).

What this experiment changes (and does NOT change):
- Motion (joint worlds / local rotations / times) is FROZEN. The deployed
  animation is replayed exactly via ``glb_skeleton.load_bind_skeleton`` +
  ``verify_calibrated_export._serialized_local_rotations`` +
  ``eagle_glb.gltf_world_matrices`` + ``mesh_preview.skin_vertices``.
- The shared rest mesh and shared skin weights are repaired by one
  ``TopologyWeightField`` (+ optional ``MeshField`` rest offsets) fitted
  against EVERY keyframe with a per-keyframe combined score:
  ``score = (silhouetteIoU + chromaQuality + dinoQuality) / 3``
  (same definition as ``preview_per_frame_mesh_selection.frame_metrics``;
  DINOv2 ``facebook/dinov2-large`` via ``hybrid_dinov2.DinoEncoder`` on CUDA).
- No per-frame topology surgery, no joint/bind edits, no retiming, no new
  keys. Per-keyframe correctives are diagnostic-only and never exported.
- Proof label is ``generated-artifact``. This is NOT delivery input: the
  pipeline contract forbids image scores from redefining motion or bind.

Camera: one frozen orthographic camera per unit, registered once from the
idle bind rest mesh against the idle plate (alpha primary, chroma tie-break),
exactly like ``skin_camera_registration.register_camera``. The repair renders
with ``skin_image_objective.SkinImageRenderer`` (CUDA nvdiffrast).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# __file__ is the module file: parents[0]=module dir, [1]=homm3_mocap_v2,
# [2]=experiments, [3]=repo root.
REPO = Path(__file__).resolve().parents[3]
EXPERIMENT = Path(__file__).resolve().parent

APPROVED = REPO / "artifacts" / "homm3_mocap_v2" / "stronghold_oe_approved_v1" / "units"

# Deployed clip file -> DEF group. Matches delivery_manifest.json rawSourceGlb
# suffixes (g<GG>_<name>.glb) for every Stronghold unit.
CLIP_TO_GROUP = {
    "Unit_Move": 0,
    "Unit_Mouseover": 1,
    "Unit_Idle": 2,
    "Unit_Hitted": 3,
    "Unit_Defence": 4,
    "Unit_Death": 5,
    "Unit_AttackFront": 12,
    "Unit_MoveStart": 20,
    "Unit_MoveEnd": 21,
}

# Groups with no OE native clip contract (kept as source-only evidence).
SOURCE_ONLY_GROUPS = (7, 8, 9, 10, 11, 13)

SCHEMA = "homm3.keyframe-combined-repair.v1"
DINO_MODEL = "facebook/dinov2-large"


@dataclass(frozen=True)
class KeyframeSample:
    """One deployed keyframe with its source plate."""

    clip: str
    group: int
    frame_index: int
    joint_world: np.ndarray  # [J,4,4]
    source_plate: Path


def combined_score(*, silhouette: float, chroma_quality: float, dino_quality: float) -> float:
    """Equal-mean combined score (preview_per_frame_mesh_selection.frame_metrics)."""
    return float((float(silhouette) + float(chroma_quality) + float(dino_quality)) / 3.0)


def frame_metrics(
    source: np.ndarray,
    mesh: np.ndarray,
    source_embedding: np.ndarray,
    mesh_embedding: np.ndarray,
) -> dict[str, float]:
    """Per-keyframe silhouette + luma-normalized chroma + DINOv2 cosine.

    ``source``/``mesh`` are RGBA uint8; embeddings are DINOv2 subject vectors.
    Mirrors ``preview_per_frame_mesh_selection.frame_metrics`` without the
    shape/anatomy/deformation gates (those are evaluated separately).
    """
    from hybrid_dinov2 import cosine_quality

    sa = source[..., 3].astype(np.float64) / 255.0
    ma = mesh[..., 3].astype(np.float64) / 255.0
    inter = float((sa * ma).sum())
    union = float((sa + ma - sa * ma).sum())
    silhouette = inter / max(union, 1e-9)
    sr = source[..., :3].astype(np.float64) / 255.0
    mr = mesh[..., :3].astype(np.float64) / 255.0
    sl = (sr * np.asarray((0.299, 0.587, 0.114))).sum(-1, keepdims=True)
    ml = (mr * np.asarray((0.299, 0.587, 0.114))).sum(-1, keepdims=True)
    chroma_delta = np.abs(sr / np.maximum(sl, 1e-3) - mr / np.maximum(ml, 1e-3))
    overlap = sa * ma + 0.05 * sa
    chroma = float((chroma_delta * overlap[..., None]).sum() / max(overlap.sum() * 3.0, 1e-9))
    chroma_quality = float(np.clip(1.0 - chroma, 0.0, 1.0))
    dino = float(cosine_quality(source_embedding, mesh_embedding))
    return {
        "silhouette": float(silhouette),
        "chroma": chroma_quality,
        "normalizedDinoV2": dino,
        "score": combined_score(
            silhouette=silhouette, chroma_quality=chroma_quality, dino_quality=dino
        ),
    }


def resolve_plate_lookup(lab_root: Path, lab_sid: str) -> dict[str, Any]:
    """Resolve ``<DEF>.dir/GG_FF.png`` plates + ``<DEF>.json`` sequences.

    Returns ``{"defDir": ..., "defJson": ..., "groups": {group: [plates]}}``.
    JSON frame paths are lowercase (``cgobli.dir\\\\00_00.png``) while the
    on-disk dir is uppercase; resolution is relative to
    ``extracted_battle_source_12fps/`` and case-normalized.
    """
    import json

    unit_dir = lab_root / lab_sid / "extracted_battle_source_12fps"
    if not unit_dir.is_dir():
        raise FileNotFoundError(f"lab plates missing for {lab_sid}: {unit_dir}")
    jsons = sorted(unit_dir.glob("*.json"))
    if not jsons:
        raise FileNotFoundError(f"no DEF json for {lab_sid} under {unit_dir}")
    if len(jsons) != 1:
        raise ValueError(f"ambiguous DEF json for {lab_sid}: {[p.name for p in jsons]}")
    def_json = jsons[0]
    payload = json.loads(def_json.read_text(encoding="utf-8"))
    groups: dict[int, list[Path]] = {}
    # Case mismatch: JSON frame paths are lowercase (``cgobli.dir\\00_00.png``)
    # while the on-disk DEF dir is uppercase (``CGOBLI.dir/``). Windows resolves
    # this, but case-sensitive filesystems (and rglob-lowered matches) can land
    # on a phantom lowercase path. Normalize every plate through a
    # case-insensitive directory walk so the returned path is always on disk.
    disk_files = {
        str(p.relative_to(unit_dir)).lower(): p
        for p in unit_dir.rglob("*")
        if p.is_file()
    }
    for seq in payload.get("sequences", ()):
        group = int(seq["group"])
        plates: list[Path] = []
        for rel in seq["frames"]:
            lowered = str(rel).lower()
            if lowered not in disk_files:
                raise FileNotFoundError(
                    f"plate not found: {rel} (under {unit_dir})"
                )
            plates.append(disk_files[lowered])
        if group in groups:
            raise ValueError(f"duplicate DEF group {group} in {def_json}")
        groups[group] = plates
    def_dirs = sorted({p.parent for plates in groups.values() for p in plates})
    if len(def_dirs) != 1:
        raise ValueError(f"plates span multiple DEF dirs for {lab_sid}: {def_dirs}")
    return {"defDir": def_dirs[0], "defJson": def_json, "groups": groups}


def deployed_clips(unit_dir: Path) -> list[Path]:
    """Deployed ``Unit_*.glb`` clips in group order (Move..MoveEnd)."""
    order = [
        "Unit_Move",
        "Unit_Mouseover",
        "Unit_Idle",
        "Unit_Hitted",
        "Unit_Defence",
        "Unit_Death",
        "Unit_AttackFront",
        "Unit_MoveStart",
        "Unit_MoveEnd",
    ]
    clips = []
    for name in order:
        path = unit_dir / f"{name}.glb"
        if path.is_file():
            clips.append(path)
    if not clips:
        raise FileNotFoundError(f"no deployed Unit_*.glb under {unit_dir}")
    return clips


__all__ = [
    "APPROVED",
    "CLIP_TO_GROUP",
    "SOURCE_ONLY_GROUPS",
    "SCHEMA",
    "DINO_MODEL",
    "KeyframeSample",
    "combined_score",
    "frame_metrics",
    "resolve_plate_lookup",
    "deployed_clips",
]
