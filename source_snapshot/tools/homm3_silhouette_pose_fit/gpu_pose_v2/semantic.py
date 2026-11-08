"""Late semantic arbitration for a small exact-geometry finalist set."""
from __future__ import annotations

import random
import math
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from .contracts import ExperimentResult, ObjectiveBreakdown, PoseHypothesis, PoseState
from .objectives import ObjectiveRegistry
from .renderer import ExactCudaRenderer
from .session import ExperimentSession


def _image(rgb: np.ndarray, alpha: np.ndarray | None = None) -> Image.Image:
    color = (np.asarray(rgb).clip(0.0, 1.0) * 255.0).astype(np.uint8)
    if alpha is None:
        alpha = np.ones(color.shape[:2], dtype=np.float32)
    rgba = np.concatenate((color, (np.asarray(alpha).clip(0.0, 1.0)[..., None] * 255.0).astype(np.uint8)), axis=-1)
    background = Image.new("RGBA", (color.shape[1], color.shape[0]), (32, 32, 32, 255))
    background.alpha_composite(Image.fromarray(rgba, mode="RGBA"))
    return background.convert("RGB")


class SemanticFinalistScorer:
    def __init__(self, session: ExperimentSession):
        from roc_semantic_embedding_match import RocSemanticEmbedder
        from dense_semantic_features import DenseFeatureScorer

        self.session = session
        self.renderer = ExactCudaRenderer(session.rig, session.camera, antialias=session.config.raster_antialias)
        self.front_renderer = (
            ExactCudaRenderer(session.rig, session.front_camera, antialias=session.config.raster_antialias)
            if session.config.front_view_enabled and session.front_camera is not None
            else None
        )
        self.objectives = ObjectiveRegistry(
            session.clip,
            session.rig,
            session.camera,
            session.config,
            session.front_camera,
        )
        cfg = session.config
        self.global_encoder = RocSemanticEmbedder(
            model_id=cfg.semantic_model_id,
            embedding_layers=cfg.semantic_layers,
            subject_crop=False,
        ) if cfg.semantic_enabled else None
        self.dense_encoder = DenseFeatureScorer(
            model_id=cfg.dense_model_id,
            family=cfg.dense_model_family,
            feature_layers=cfg.dense_layers,
            device=cfg.device,
            revision=cfg.dense_model_revision,
            trust_remote_code=cfg.dense_trust_remote_code,
            local_files_only=cfg.dense_local_files_only,
        ) if cfg.dense_semantic_enabled else None
        targets = self._target_images()
        self._target_global_layers = self.global_encoder.embed_layers(targets) if self.global_encoder is not None else None
        self._target_dense_layers = self.dense_encoder.extract_layers(targets) if self.dense_encoder is not None else None
        front_targets = self._front_target_images()
        self.front_target_images = front_targets
        self._target_front_global_layers = (
            self.global_encoder.embed_layers(front_targets)
            if self.global_encoder is not None and front_targets
            else None
        )
        self._target_front_dense_layers = (
            self.dense_encoder.extract_layers(front_targets)
            if self.dense_encoder is not None and front_targets
            else None
        )
        self.surface_descriptor = self._prepare_surface_descriptors()

    def _surface_descriptor_key(self) -> str:
        camera = self.session.camera
        payload = {
            "rig": self.session.rig.fingerprint,
            "camera": {
                "width": camera.width,
                "height": camera.height,
                "right": camera.right,
                "down": camera.down,
                "forward": camera.forward,
                "offset": camera.offset,
                "pxPerWorld": camera.px_per_world,
            },
            "global": None if self.global_encoder is None else {
                "model": self.session.config.semantic_model_id,
                "layers": list(self.session.config.semantic_layers),
            },
            "dense": None if self.dense_encoder is None else {
                "model": self.session.config.dense_model_id,
                "family": self.session.config.dense_model_family,
                "layers": list(self.session.config.dense_layers),
                "revision": self.session.config.dense_model_revision,
                "trustRemoteCode": self.session.config.dense_trust_remote_code,
                "localFilesOnly": self.session.config.dense_local_files_only,
            },
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def _prepare_surface_descriptors(self) -> dict[str, Any]:
        """Cache real view-conditioned bind-surface descriptors once per rig.

        These descriptors are a semantic surface reference, not another pose
        objective. They make the model/camera/texture provenance explicit and
        avoid repeatedly re-encoding the same bind view when a notebook user
        reruns semantic arbitration with different geometric weights.
        """
        key = self._surface_descriptor_key()
        directory = self.session.artifact_dir / "semantic_surface_descriptors"
        directory.mkdir(parents=True, exist_ok=True)
        array_path = directory / f"{key}.npz"
        manifest_path = directory / f"{key}.json"
        if array_path.is_file() and manifest_path.is_file():
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        nodes = len(self.session.rig.node_names)
        device = self.session.device
        zero_pose = PoseState(
            registration=torch.zeros((1, 7), dtype=torch.float32, device=device),
            motion_translation=torch.zeros((1, 1, 3), dtype=torch.float32, device=device),
            motion_rotation=torch.zeros((1, 1, 3), dtype=torch.float32, device=device),
            bone_rotation=torch.zeros((1, 1, nodes, 3), dtype=torch.float32, device=device),
            frame_indices=(self.session.clip.frame_indices[0],),
        )
        buffers = self.renderer.render_single(zero_pose)
        bind_image = _image(
            buffers.rgb[0, 0].detach().cpu().numpy(),
            buffers.alpha[0, 0].detach().cpu().numpy(),
        )
        arrays: dict[str, np.ndarray] = {}
        layers: dict[str, list[str]] = {"global": [], "dense": []}
        if self.global_encoder is not None:
            for index, (layer, value) in enumerate(self.global_encoder.embed_layers([bind_image]).items()):
                name = f"global_{index}"
                arrays[name] = np.asarray(value[0], dtype=np.float32)
                layers["global"].append(str(layer))
        if self.dense_encoder is not None:
            for index, (layer, value) in enumerate(self.dense_encoder.extract_layers([bind_image]).items()):
                name = f"dense_{index}"
                arrays[name] = value[0].detach().cpu().numpy().astype(np.float32)
                layers["dense"].append(str(layer))
        if not arrays:
            return {"schemaVersion": 1, "viewConditioned": False, "reason": "semantic encoders disabled"}
        np.savez_compressed(array_path, **arrays)
        manifest = {
            "schemaVersion": 1,
            "viewConditioned": True,
            "key": key,
            "mesh": str(self.session.rig.path),
            "rigFingerprint": self.session.rig.fingerprint,
            "camera": self.session.camera.__dict__,
            "layers": layers,
            "path": str(array_path),
            "source": "exact CUDA bind-pose triangle render",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
        return manifest

    def _target_images(self) -> list[Image.Image]:
        return [
            _image(self.session.clip.rgb[index], self.session.clip.masks[index])
            for index in range(len(self.session.clip.frame_indices))
        ]

    def _front_target_images(self) -> list[Image.Image]:
        if self.session.clip.front_rgb is None or self.session.clip.front_masks is None:
            return []
        return [
            _image(self.session.clip.front_rgb[index], self.session.clip.front_masks[index])
            for index in range(len(self.session.clip.frame_indices))
        ]

    @staticmethod
    def _masked_dense_distance(
        target_grid: torch.Tensor,
        candidate_grid: torch.Tensor,
        target_masks: np.ndarray,
        candidate_masks: np.ndarray,
    ) -> torch.Tensor:
        """Compare dense features only where both views contain a subject.

        Generated front art has a black background and the exact renderer has
        transparent background.  Without this gate, dense features can spend
        much of their score matching empty canvas instead of wing/body parts.
        """
        if target_grid.ndim == 3:
            target_grid = target_grid.unsqueeze(0)
        if candidate_grid.ndim == 3:
            candidate_grid = candidate_grid.unsqueeze(0)
        if target_grid.shape[0] == 1 and candidate_grid.shape[0] > 1:
            target_grid = target_grid.expand(candidate_grid.shape[0], -1, -1, -1)
        target_grid = F.normalize(target_grid, dim=-1)
        candidate_grid = F.normalize(candidate_grid, dim=-1)
        size = (int(target_grid.shape[1]), int(target_grid.shape[2]))
        target_mask = torch.as_tensor(target_masks, dtype=target_grid.dtype, device=target_grid.device)
        candidate_mask = torch.as_tensor(candidate_masks, dtype=target_grid.dtype, device=target_grid.device)
        if target_mask.ndim == 2:
            target_mask = target_mask.unsqueeze(0)
        if candidate_mask.ndim == 2:
            candidate_mask = candidate_mask.unsqueeze(0)
        target_mask = F.interpolate(target_mask.unsqueeze(1), size=size, mode="area").squeeze(1)
        candidate_mask = F.interpolate(candidate_mask.unsqueeze(1), size=size, mode="area").squeeze(1)
        valid = target_mask * candidate_mask
        cosine_distance = 1.0 - (target_grid * candidate_grid).sum(dim=-1)
        feature_value = (cosine_distance * valid).sum(dim=(1, 2)) / valid.sum(dim=(1, 2)).clamp_min(1.0)
        coverage_value = (target_mask - candidate_mask).abs().mean(dim=(1, 2))
        return 0.8 * feature_value + 0.2 * coverage_value

    def _score_images(
        self,
        candidate_images: list[Image.Image],
        *,
        target_global_layers: dict[Any, Any] | None,
        target_dense_layers: dict[Any, Any] | None,
        target_masks: np.ndarray,
        candidate_masks: np.ndarray,
        prefix: str = "",
    ) -> dict[str, Any]:
        # Finalists are evaluated in small batches.  This keeps the vision
        # towers resident on CUDA while bounding peak memory on a 16 GB card;
        # the old per-frame call pattern paid processor and kernel-launch cost
        # once for every image.
        global_scores: list[float] = []
        global_layers: dict[str, list[float]] = {}
        dense_scores: list[float] = []
        dense_layers: dict[str, list[float]] = {}
        batch_size = max(1, int(self.session.config.semantic_microbatch))
        for start in range(0, len(candidate_images), batch_size):
            batch = candidate_images[start : start + batch_size]
            if self.global_encoder is not None and target_global_layers is not None:
                candidate_values = self.global_encoder.embed_layers(batch)
                for offset in range(len(batch)):
                    index = start + offset
                    layer_scores: list[float] = []
                    for layer, vectors in candidate_values.items():
                        score = float(np.dot(target_global_layers[layer][index], vectors[offset]))
                        global_layers.setdefault(str(layer), []).append(score)
                        layer_scores.append(score)
                    global_scores.append(float(np.mean(layer_scores)))
            if self.dense_encoder is not None and target_dense_layers is not None:
                candidate_grid = self.dense_encoder.extract_layers(batch)
                layer_distances = {
                    layer: self._masked_dense_distance(
                        values[start : start + len(batch)],
                        candidate_grid[layer],
                        target_masks[start : start + len(batch)],
                        candidate_masks[start : start + len(batch)],
                    )
                    for layer, values in target_dense_layers.items()
                }
                for offset in range(len(batch)):
                    per_layer = []
                    for layer, distances in layer_distances.items():
                        value = float(distances[offset].detach().cpu().item())
                        dense_layers.setdefault(str(layer), []).append(value)
                        per_layer.append(value)
                    dense_scores.append(float(np.mean(per_layer)))
        label = str(prefix)
        global_key = f"{label}GlobalCosine" if label else "globalCosine"
        global_layers_key = f"{label}GlobalLayerCosines" if label else "globalLayerCosines"
        dense_key = f"{label}DenseDistance" if label else "denseDistance"
        dense_layers_key = f"{label}DenseLayerDistances" if label else "denseLayerDistances"
        return {
            global_key: float(np.mean(global_scores)) if global_scores else None,
            global_layers_key: {key: float(np.mean(values)) for key, values in global_layers.items()},
            dense_key: float(np.mean(dense_scores)) if dense_scores else None,
            dense_layers_key: {key: float(np.mean(values)) for key, values in dense_layers.items()},
        }

    def score_hypothesis(self, hypothesis: PoseHypothesis) -> tuple[PoseHypothesis, dict[str, Any]]:
        buffers = self.renderer.render_single(hypothesis.pose)
        candidate_images = [
            _image(
                buffers.rgb[0, index].detach().cpu().numpy(),
                buffers.alpha[0, index].detach().cpu().numpy(),
            )
            for index in range(len(self.session.clip.frame_indices))
        ]
        candidate_masks = buffers.alpha[0].detach().cpu().numpy()
        scores = self._score_images(
            candidate_images,
            target_global_layers=self._target_global_layers,
            target_dense_layers=self._target_dense_layers,
            target_masks=np.asarray(self.session.clip.masks),
            candidate_masks=candidate_masks,
        )
        if self.front_renderer is not None and self.front_target_images:
            front_buffers = self.front_renderer.render_single(hypothesis.pose)
            front_image_values: list[Image.Image] = []
            front_mask_values: list[np.ndarray] = []
            for index in range(len(self.session.clip.frame_indices)):
                candidate_rgb = front_buffers.rgb[0, index].detach().cpu().numpy()
                candidate_mask = front_buffers.alpha[0, index].detach().cpu().numpy()
                # Generated targets were normalized once and the auxiliary
                # camera was fitted once from bind pose.  Keep semantic
                # inputs in that fixed coordinate system; per-candidate
                # recentering would make a twisted pose look deceptively good.
                front_image_values.append(_image(candidate_rgb, candidate_mask))
                front_mask_values.append(candidate_mask)
            front_images = front_image_values
            front_scores = self._score_images(
                front_images,
                target_global_layers=self._target_front_global_layers,
                target_dense_layers=self._target_front_dense_layers,
                target_masks=np.asarray(self.session.clip.front_masks),
                candidate_masks=np.stack(front_mask_values),
                prefix="front",
            )
            scores.update(front_scores)
        global_loss = 0.0 if scores["globalCosine"] is None else 1.0 - float(scores["globalCosine"])
        dense_loss = 0.0 if scores["denseDistance"] is None else float(scores["denseDistance"])
        front_global_loss = 0.0 if scores.get("frontGlobalCosine") is None else 1.0 - float(scores["frontGlobalCosine"])
        front_dense_loss = 0.0 if scores.get("frontDenseDistance") is None else float(scores["frontDenseDistance"])
        combined = (
            float(hypothesis.objective.total.mean().item())
            + float(self.session.config.global_semantic_weight) * global_loss
            + float(self.session.config.dense_semantic_weight) * dense_loss
            + float(self.session.config.front_view_global_semantic_weight) * front_global_loss
            + float(self.session.config.front_view_dense_semantic_weight) * front_dense_loss
        )
        return replace(hypothesis, semantic={**scores, "combinedLoss": combined}), scores

    def _rescue(self, hypothesis: PoseHypothesis, seed: int) -> PoseHypothesis:
        """Use geometry proposals with periodic semantic refreshes.

        Vision encoders are intentionally not differentiated through. A short
        trust-region walk lets the exact geometry objective move a finalist,
        while refreshing semantics only every few proposals keeps this stage
        bounded on a 16 GB card.
        """
        cfg = self.session.config
        best, _ = self.score_hypothesis(hypothesis)
        best_loss = float(best.semantic.get("combinedLoss", float("inf")) if best.semantic else float("inf"))
        generator = torch.Generator(device=self.session.device).manual_seed(int(seed))
        for iteration in range(int(cfg.semantic_rescue_iterations)):
            pose = best.pose
            registration = pose.registration.clone()
            motion_translation = pose.motion_translation.clone()
            motion_rotation = pose.motion_rotation.clone()
            bones = pose.bone_rotation.clone()
            scale = 0.025 * max(0.25, 1.0 - iteration / max(int(cfg.semantic_rescue_iterations), 1))
            registration[..., :3] += torch.randn(registration[..., :3].shape, generator=generator, device=registration.device) * scale
            registration[..., 3:6] += torch.randn(registration[..., 3:6].shape, generator=generator, device=registration.device) * (scale * 0.5)
            motion_rotation += torch.randn(motion_rotation.shape, generator=generator, device=motion_rotation.device) * scale
            bones += torch.randn(bones.shape, generator=generator, device=bones.device) * scale
            candidate_pose = PoseState(registration, motion_translation, motion_rotation, bones, pose.frame_indices)
            buffers = self.renderer.render_single(candidate_pose)
            front_buffers = self.front_renderer.render_single(candidate_pose) if self.front_renderer is not None else None
            objective = self.objectives.score(buffers, candidate_pose, auxiliary_buffers=front_buffers)
            candidate = replace(hypothesis, pose=candidate_pose, objective=objective, stage="semantic_rescue")
            if iteration % 8 == 0 or iteration + 1 == int(cfg.semantic_rescue_iterations):
                candidate, _ = self.score_hypothesis(candidate)
            else:
                # Keep the most recent semantic value while testing cheap
                # geometry proposals between encoder refreshes.
                geometry_loss = float(objective.total.mean().item())
                stale_semantic = best.semantic or {}
                combined = (
                    geometry_loss
                    + float(cfg.global_semantic_weight) * (1.0 - float(stale_semantic.get("globalCosine") or 0.0))
                    + float(cfg.dense_semantic_weight) * float(stale_semantic.get("denseDistance") or 0.0)
                    + float(cfg.front_view_global_semantic_weight) * (1.0 - float(stale_semantic.get("frontGlobalCosine") or 0.0))
                    + float(cfg.front_view_dense_semantic_weight) * float(stale_semantic.get("frontDenseDistance") or 0.0)
                )
                candidate = replace(candidate, semantic={**stale_semantic, "combinedLoss": combined})
            candidate_loss = float(candidate.semantic.get("combinedLoss", float("inf")) if candidate.semantic else float("inf"))
            if math.isfinite(candidate_loss) and candidate_loss < best_loss:
                best, best_loss = candidate, candidate_loss
        return best

    def rerank(self, result: ExperimentResult) -> ExperimentResult:
        geometry_winner = min(
            result.alternatives,
            key=lambda value: float(value.objective.total.mean().item()),
        )
        scored = [self.score_hypothesis(hypothesis)[0] for hypothesis in result.alternatives]
        rescue_count = min(int(self.session.config.semantic_keep), len(scored))
        rescued = [self._rescue(value, seed=7000 + index) for index, value in enumerate(scored[:rescue_count])]
        scored = rescued + scored[rescue_count:]
        scored.sort(key=lambda value: float(value.semantic.get("combinedLoss", float("inf")) if value.semantic else float("inf")))
        selected = scored[0]
        # Keep the geometry winner available even when semantic arbitration
        # chooses a different pose.  The user can therefore inspect the exact
        # tradeoff instead of losing the strongest non-semantic hypothesis.
        selected_semantic = replace(selected, semantic={**(selected.semantic or {}), "winner": "semantic"})
        preserved = [selected_semantic]
        for value in scored[1:]:
            if len(preserved) >= int(self.session.config.semantic_keep):
                break
            preserved.append(value)
        geometry_key = tuple(geometry_winner.lineage), geometry_winner.stage
        if all((tuple(value.lineage), value.stage) != geometry_key for value in preserved):
            preserved.append(replace(geometry_winner, semantic={**(geometry_winner.semantic or {}), "winner": "geometry"}))
        provenance = {
            **result.provenance,
            "semanticArbitration": {
                "geometryWinnerLineage": list(geometry_winner.lineage),
                "semanticWinnerLineage": list(selected.lineage),
                "geometryWinnerPreserved": any(
                    (tuple(value.lineage), value.stage) == geometry_key for value in preserved
                ),
                "surfaceDescriptorCache": self.surface_descriptor.get("path"),
            },
        }
        return replace(
            result,
            selected=selected_semantic,
            alternatives=tuple(preserved),
            artifacts={
                **result.artifacts,
                **({"surfaceDescriptors": str(self.surface_descriptor["path"])} if self.surface_descriptor.get("path") else {}),
            },
            provenance=provenance,
            timings={**result.timings, "semanticFinalists": float(len(scored))},
        )


def semantic_rerank(session: ExperimentSession, result: ExperimentResult) -> ExperimentResult:
    """Rerank exact-geometry finalists; models never run in the gradient loop."""
    if not session.config.semantic_enabled and not session.config.dense_semantic_enabled:
        return result
    scorer = SemanticFinalistScorer(session)
    return scorer.rerank(result)
