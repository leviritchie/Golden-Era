"""Whole-clip, multi-hypothesis V2 optimizer."""
from __future__ import annotations

import copy
import json
import math
import time
from dataclasses import replace
from typing import Any, Callable, Mapping

import torch

from .contracts import ExperimentResult, ObjectiveBreakdown, PoseHypothesis, PoseState
from .objectives import ObjectiveRegistry
from .renderer import ExactCudaRenderer
from .session import ExperimentSession


class V2Solver:
    def __init__(self, session: ExperimentSession, *, progress_callback: Callable[[Mapping[str, Any]], None] | None = None):
        self.session = session
        self.config = session.config
        self.renderer = ExactCudaRenderer(session.rig, session.camera, antialias=self.config.raster_antialias)
        self.front_renderer = (
            ExactCudaRenderer(session.rig, session.front_camera, antialias=self.config.raster_antialias)
            if self.config.front_view_enabled and session.front_camera is not None
            else None
        )
        self.objectives = ObjectiveRegistry(
            session.clip,
            session.rig,
            session.camera,
            self.config,
            session.front_camera,
        )
        self.device = torch.device(self.config.device)
        self.frames = len(session.clip.frame_indices)
        self.nodes = len(session.rig.node_names)
        self.skeleton_mask = torch.zeros(self.nodes, dtype=torch.float32, device=self.device)
        if session.rig.skeleton_indices:
            self.skeleton_mask[
                torch.as_tensor(session.rig.skeleton_indices, dtype=torch.long, device=self.device)
            ] = 1.0
        self.history: list[dict[str, Any]] = []
        self.progress_callback = progress_callback

    def _write_checkpoint(self, label: str, hypotheses: tuple[PoseHypothesis, ...]) -> str | None:
        if not self.config.checkpoint_every_stage:
            return None

        def jsonable(value: Any) -> Any:
            if hasattr(value, "detach"):
                return value.detach().cpu().tolist()
            if isinstance(value, Mapping):
                return {str(key): jsonable(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [jsonable(item) for item in value]
            if hasattr(value, "item"):
                return value.item()
            return value

        path = self.session.artifact_dir / f"gpu_pose_v2_{label}_checkpoint.json"
        payload = {
            "schemaVersion": 2,
            "stage": label,
            "backend": "nvdiffrast_cuda_triangle",
            "rigFingerprint": self.session.rig.fingerprint,
            "clipFingerprint": self.session.clip.fingerprint,
            "hypotheses": [
                {
                    "stage": value.stage,
                    "lineage": list(value.lineage),
                    "pose": {
                        "registration": jsonable(value.pose.registration),
                        "motionTranslation": jsonable(value.pose.motion_translation),
                        "motionRotation": jsonable(value.pose.motion_rotation),
                        "boneRotation": jsonable(value.pose.bone_rotation),
                        "frameIndices": list(value.pose.frame_indices),
                    },
                    "objective": {
                        "total": jsonable(value.objective.total),
                        "perFrame": jsonable(value.objective.per_frame),
                        "diagnostics": jsonable(value.objective.diagnostics),
                        "observability": jsonable(value.objective.observability),
                        "gradients": jsonable(value.objective.gradients),
                    },
                }
                for value in hypotheses
            ],
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return str(path)

    def _raw_pose(self, raw_registration: torch.Tensor, raw_translation: torch.Tensor, raw_motion_rotation: torch.Tensor, raw_bones: torch.Tensor, *, bone_mask: torch.Tensor | None = None) -> PoseState:
        cfg = self.config
        reg = raw_registration.clone()
        reg_angles = torch.tanh(reg[..., :3]) * math.radians(float(cfg.registration_rotation_limit_deg))
        reg_translation = torch.tanh(reg[..., 3:6]) * float(cfg.registration_translation_body_lengths)
        reg_scale = reg[..., 6].clamp(-float(cfg.registration_scale_log_limit), float(cfg.registration_scale_log_limit))
        registration = torch.cat((reg_angles, reg_translation, reg_scale.unsqueeze(-1)), dim=-1)
        motion_translation = torch.tanh(raw_translation) * float(cfg.motion_translation_body_lengths)
        motion_rotation = torch.tanh(raw_motion_rotation) * math.radians(float(cfg.motion_rotation_limit_deg))
        bones = torch.tanh(raw_bones) * math.radians(float(cfg.joint_limit_deg))
        # Keep the canonical tensor scene-node-shaped for serialization, but
        # remove rotations for non-skin nodes before any objective sees them.
        bones = bones * self.skeleton_mask.view(1, 1, self.nodes, 1)
        if bone_mask is not None:
            bones = bones * bone_mask.view(1, 1, self.nodes, 1)
        return PoseState(registration, motion_translation, motion_rotation, bones, tuple(self.session.clip.frame_indices))

    def _zero_parameters(self, count: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        return (
            torch.zeros((count, 7), dtype=torch.float32, device=self.device, requires_grad=True),
            torch.zeros((count, self.frames, 3), dtype=torch.float32, device=self.device, requires_grad=True),
            torch.zeros((count, self.frames, 3), dtype=torch.float32, device=self.device, requires_grad=True),
            torch.zeros((count, self.frames, self.nodes, 3), dtype=torch.float32, device=self.device, requires_grad=True),
        )

    def _proximal_mask(self, enabled: bool) -> torch.Tensor | None:
        if not enabled:
            return None
        values = [
            1.0 if self.skeleton_mask[index] > 0.0 and depth <= int(self.config.proximal_depth) else 0.0
            for index, depth in enumerate(self.session.rig.node_depths)
        ]
        return torch.as_tensor(values, dtype=torch.float32, device=self.device)

    def _initial_registration_hypotheses(self) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        count = int(self.config.registration_hypotheses)
        registration, translation, motion_rotation, bones = self._zero_parameters(count)
        engine = torch.quasirandom.SobolEngine(7, scramble=True, seed=17)
        samples = engine.draw(count).to(self.device) * 2.0 - 1.0
        # Keep registration and animation root separate. This broad search is
        # static camera/model alignment, not a per-frame action rotation.
        registration.data[:, :3] = torch.atanh(torch.clamp(samples[:, :3] * 0.95, -0.999, 0.999))
        registration.data[:, 3:6] = torch.atanh(torch.clamp(samples[:, 3:6] * 0.80, -0.999, 0.999))
        registration.data[:, 6] = samples[:, 6] * float(self.config.registration_scale_log_limit)
        return registration, translation, motion_rotation, bones

    def _seed_motion_root_hypotheses(
        self,
        raw: tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor],
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Duplicate registration winners with bounded root-orientation seeds.

        A gradient started at zero cannot reliably cross the rasterizer's
        occlusion basin when the imported bind pose is far from the action
        profile. Keep a zero seed for continuity, then add a small Sobol bank
        of common whole-body rotations. These are generic motion-root
        hypotheses; articulated bones remain zero until the root stage has
        selected and refined a basin.
        """
        seed_count = int(self.config.motion_root_hypotheses)
        if seed_count <= 1:
            return raw
        registration, translation, motion_rotation, bones = raw
        parent_count = int(registration.shape[0])
        engine = torch.quasirandom.SobolEngine(3, scramble=True, seed=29)
        samples = engine.draw(seed_count - 1).to(self.device) * 2.0 - 1.0
        samples = torch.cat(
            (torch.zeros((1, 3), dtype=samples.dtype, device=self.device), samples),
            dim=0,
        )
        # Stay inside a bounded trust region while still covering large legal
        # action rotations. The zero row is deliberately retained above.
        root_seeds = torch.atanh(torch.clamp(samples * 0.90, -0.999, 0.999))
        registration = (
            registration[:, None, :]
            .expand(parent_count, seed_count, -1)
            .reshape(parent_count * seed_count, -1)
            .clone()
        )
        translation = (
            translation[:, None, :, :]
            .expand(parent_count, seed_count, -1, -1)
            .reshape(parent_count * seed_count, self.frames, 3)
            .clone()
        )
        motion_rotation = (
            motion_rotation[:, None, :, :]
            .expand(parent_count, seed_count, -1, -1)
            .reshape(parent_count * seed_count, self.frames, 3)
            .clone()
        )
        bones = (
            bones[:, None, :, :, :]
            .expand(parent_count, seed_count, -1, -1, -1)
            .reshape(parent_count * seed_count, self.frames, self.nodes, 3)
            .clone()
        )
        motion_rotation += (
            root_seeds[None, :, None, :]
            .expand(parent_count, seed_count, self.frames, 3)
            .reshape(parent_count * seed_count, self.frames, 3)
        )
        return tuple(
            value.detach().clone().requires_grad_(True)
            for value in (registration, translation, motion_rotation, bones)
        )

    def _measure(
        self,
        raw: tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor],
        *,
        bone_mask: torch.Tensor | None,
        registration_only: bool = False,
    ) -> tuple[torch.Tensor, ObjectiveBreakdown, PoseState]:
        pose = self._raw_pose(*raw, bone_mask=bone_mask)
        buffers = self.renderer.render(pose)
        auxiliary_buffers = self.front_renderer.render(pose) if self.front_renderer is not None else None
        if registration_only:
            position = min(int(self.config.registration_frame_position), self.frames - 1)
            objective = self.objectives.score(
                buffers,
                pose,
                frame_positions=(position,),
                include_temporal=False,
                auxiliary_buffers=auxiliary_buffers,
            )
        else:
            objective = self.objectives.score(buffers, pose, auxiliary_buffers=auxiliary_buffers)
        return objective.total, objective, pose

    def _run_stage(
        self,
        label: str,
        raw: tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor],
        *,
        iterations: int,
        learning_rate: float,
        bone_mask: torch.Tensor | None,
        active: tuple[bool, bool, bool, bool],
    ) -> tuple[tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor], ObjectiveBreakdown, PoseState]:
        if int(iterations) <= 0:
            total, objective, pose = self._measure(raw, bone_mask=bone_mask)
            return raw, objective, pose
        parameters = [value for value, enabled in zip(raw, active) if enabled and value.requires_grad]
        if not parameters:
            raise ValueError(f"V2 stage {label!r} has no active optimization variables")
        optimizer = torch.optim.Adam(parameters, lr=float(learning_rate))
        best_raw = tuple(value.detach().clone() for value in raw)
        registration_only = label == "registration"
        with torch.no_grad():
            best_total, best_objective, best_pose = self._measure(
                raw,
                bone_mask=bone_mask,
                registration_only=registration_only,
            )
            best_value = best_total.detach().clone()
        step_scale = 1.0
        rejects = 0
        started = time.perf_counter()

        def merge_value(previous: Any, candidate: Any, mask: torch.Tensor) -> Any:
            if not hasattr(candidate, "shape") or not hasattr(previous, "shape"):
                return candidate
            if candidate.ndim == 0 or int(candidate.shape[0]) != int(mask.shape[0]):
                return candidate
            view = mask.reshape(-1, *([1] * (candidate.ndim - 1)))
            return torch.where(view, candidate, previous)

        def merge_objective(previous: ObjectiveBreakdown, candidate: ObjectiveBreakdown, mask: torch.Tensor) -> ObjectiveBreakdown:
            return ObjectiveBreakdown(
                total=merge_value(previous.total, candidate.total, mask),
                per_frame={
                    name: merge_value(previous.per_frame[name], value, mask)
                    for name, value in candidate.per_frame.items()
                },
                diagnostics={
                    name: merge_value(previous.diagnostics.get(name), value, mask)
                    for name, value in candidate.diagnostics.items()
                },
                rejection_reasons=tuple(candidate.rejection_reasons),
                observability=candidate.observability,
                gradients=candidate.gradients,
            )

        def merge_pose(previous: PoseState, candidate: PoseState, mask: torch.Tensor) -> PoseState:
            return PoseState(
                registration=merge_value(previous.registration, candidate.registration, mask),
                motion_translation=merge_value(previous.motion_translation, candidate.motion_translation, mask),
                motion_rotation=merge_value(previous.motion_rotation, candidate.motion_rotation, mask),
                bone_rotation=merge_value(previous.bone_rotation, candidate.bone_rotation, mask),
                frame_indices=previous.frame_indices,
            )

        for iteration in range(int(iterations)):
            optimizer.zero_grad(set_to_none=True)
            total, objective, _ = self._measure(raw, bone_mask=bone_mask, registration_only=registration_only)
            total.mean().backward()
            gradient_norms = {
                name: float(value.grad.detach().norm().item())
                for name, value, enabled in zip(
                    ("registration", "motionTranslation", "motionRotation", "boneRotation"),
                    raw,
                    active,
                )
                if enabled and value.grad is not None
            }
            state_before = copy.deepcopy(optimizer.state_dict())
            optimizer.step()
            with torch.no_grad():
                candidate_total, candidate_objective, candidate_pose = self._measure(
                    raw,
                    bone_mask=bone_mask,
                    registration_only=registration_only,
                )
                improved = candidate_total < best_value
                accepted = bool(improved.any().item())
                escape_accepted = False
                if accepted:
                    # Keep each hypothesis on its own best state, not the
                    # global mean. This prevents one easy frame from hiding a
                    # bad alternative during registration.
                    for tensor, old, mask in zip(raw, best_raw, improved):
                        tensor.data[mask] = tensor.detach()[mask]
                        tensor.data[~mask] = old[~mask]
                    best_value = torch.where(improved, candidate_total.detach(), best_value)
                    best_raw = tuple(value.detach().clone() for value in raw)
                    best_objective = merge_objective(best_objective, candidate_objective, improved)
                    best_pose = merge_pose(best_pose, candidate_pose, improved)
                    rejects = 0
                    step_scale = min(1.0, step_scale * 1.15)
                    for group in optimizer.param_groups:
                        group["lr"] = float(learning_rate) * step_scale
                else:
                    for tensor, old in zip(raw, best_raw):
                        tensor.copy_(old)
                    optimizer.load_state_dict(state_before)
                    rejects += 1
                    step_scale = max(0.08, step_scale * 0.55)
                    for group in optimizer.param_groups:
                        group["lr"] = float(learning_rate) * step_scale
                    if rejects >= 4:
                        # A bounded escape proposal is the only deliberate
                        # non-gradient move. It is evaluated immediately and
                        # retained only if it improves the same complete
                        # objective. This prevents a stale, unmeasured random
                        # pose from leaking into the next stage.
                        generator = torch.Generator(device=self.device).manual_seed(1000 + iteration)
                        for tensor, old, enabled in zip(raw, best_raw, active):
                            if enabled:
                                tensor.copy_(old + torch.randn(tensor.shape, generator=generator, device=self.device) * 0.025)
                        escape_total, escape_objective, escape_pose = self._measure(
                            raw,
                            bone_mask=bone_mask,
                            registration_only=registration_only,
                        )
                        escape_mask = escape_total < best_value
                        escape_accepted = bool(escape_mask.any().item())
                        if escape_accepted:
                            for tensor, old, mask in zip(raw, best_raw, escape_mask):
                                tensor.data[mask] = tensor.detach()[mask]
                                tensor.data[~mask] = old[~mask]
                            best_value = torch.where(escape_mask, escape_total.detach(), best_value)
                            best_raw = tuple(value.detach().clone() for value in raw)
                            best_objective = merge_objective(best_objective, escape_objective, escape_mask)
                            best_pose = merge_pose(best_pose, escape_pose, escape_mask)
                            step_scale = min(1.0, step_scale * 1.10)
                            for group in optimizer.param_groups:
                                group["lr"] = float(learning_rate) * step_scale
                        else:
                            for tensor, old in zip(raw, best_raw):
                                tensor.copy_(old)
                        rejects = 0
                iou_values = best_objective.diagnostics.get("iou")
                if hasattr(iou_values, "ndim") and int(iou_values.ndim) >= 2:
                    mean_iou_by_frame = iou_values.mean(dim=0)
                    worst_frame = int(torch.argmin(mean_iou_by_frame).item())
                else:
                    worst_frame = None
                component_means = {
                    name: float(value.mean().item())
                    for name, value in best_objective.per_frame.items()
                    if hasattr(value, "mean")
                }
                vram = {}
                if torch.cuda.is_available():
                    vram = {
                        "allocatedGiB": round(torch.cuda.memory_allocated(self.device) / (1024**3), 3),
                        "reservedGiB": round(torch.cuda.memory_reserved(self.device) / (1024**3), 3),
                    }
                bone_angles_deg = torch.linalg.vector_norm(best_pose.bone_rotation, dim=-1) * (180.0 / math.pi)
                motion_angles_deg = torch.linalg.vector_norm(best_pose.motion_rotation, dim=-1) * (180.0 / math.pi)
                registration_angles_deg = torch.linalg.vector_norm(best_pose.registration[..., :3], dim=-1) * (180.0 / math.pi)
                row = {
                    "stage": label,
                    "iteration": iteration + 1,
                    "iterations": int(iterations),
                    "hypotheses": int(raw[0].shape[0]),
                    "bestLoss": float(best_value.mean().item()),
                    "bestIoU": float(best_objective.diagnostics["iou"].mean().item()),
                    "accepted": accepted,
                    "acceptedHypotheses": int(improved.sum().item()) if accepted else 0,
                    "rejectedHypotheses": int((~improved).sum().item()),
                    "escapeAccepted": escape_accepted,
                    "stepScale": step_scale,
                    "rejects": rejects,
                    "elapsed": time.perf_counter() - started,
                    "iterationRate": (iteration + 1) / max(time.perf_counter() - started, 1e-6),
                    "worstFrame": worst_frame,
                    "objectiveComponents": component_means,
                    "gradientNorms": gradient_norms,
                    "activeBoneCount": int(
                        (self.skeleton_mask * bone_mask).sum().item()
                        if bone_mask is not None
                        else self.skeleton_mask.sum().item()
                    ),
                    "boneRotationMeanDeg": float(bone_angles_deg.mean().item()),
                    "boneRotationMaxDeg": float(bone_angles_deg.max().item()),
                    "motionRotationMeanDeg": float(motion_angles_deg.mean().item()),
                    "motionRotationMaxDeg": float(motion_angles_deg.max().item()),
                    "registrationRotationMeanDeg": float(registration_angles_deg.mean().item()),
                    "registrationRotationMaxDeg": float(registration_angles_deg.max().item()),
                    "vram": vram,
                }
                self.history.append(row)
                if self.progress_callback is not None:
                    self.progress_callback(row)
                elif iteration == 0 or (iteration + 1) % max(1, int(self.config.progress_every)) == 0 or iteration + 1 == int(iterations):
                    print(
                        f"v2 {label} {iteration + 1}/{iterations} "
                        f"loss={row['bestLoss']:.5f} iou={row['bestIoU']:.4f} "
                        f"accepted={accepted} step={step_scale:.3f}"
                    )
        return best_raw, best_objective, best_pose

    def _retain(self, raw: tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor], objective: ObjectiveBreakdown, pose: PoseState, count: int, stage: str) -> tuple[tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor], tuple[PoseHypothesis, ...]]:
        losses = objective.total.detach().cpu().tolist()
        order = sorted(range(len(losses)), key=lambda index: float(losses[index]))
        selected: list[int] = []

        def signature(index: int) -> torch.Tensor:
            """Compare complete pose hypotheses, not just shared registration."""
            values = (
                pose.registration[index].reshape(-1),
                pose.motion_translation[index].reshape(-1),
                pose.motion_rotation[index].reshape(-1),
                pose.bone_rotation[index].reshape(-1),
            )
            return torch.cat(values)

        for index in order:
            if len(selected) >= int(count):
                break
            candidate = signature(index)
            if any(torch.linalg.vector_norm(candidate - signature(other)).item() < 0.035 for other in selected):
                continue
            selected.append(index)
        if not selected:
            selected = order[: int(count)]
        tensors = tuple(value.detach()[selected].clone().requires_grad_(True) for value in raw)
        hypotheses = tuple(
            PoseHypothesis(
                pose=PoseState(
                    registration=pose.registration[index : index + 1].detach().clone(),
                    motion_translation=pose.motion_translation[index : index + 1].detach().clone(),
                    motion_rotation=pose.motion_rotation[index : index + 1].detach().clone(),
                    bone_rotation=pose.bone_rotation[index : index + 1].detach().clone(),
                    frame_indices=pose.frame_indices,
                ),
                objective=ObjectiveBreakdown(
                    total=objective.total[index : index + 1].detach().clone(),
                    per_frame={name: value[index : index + 1].detach().clone() for name, value in objective.per_frame.items()},
                    diagnostics={name: value[index : index + 1].detach().clone() if hasattr(value, "__getitem__") else value for name, value in objective.diagnostics.items()},
                    observability={name: value[index : index + 1].detach().clone() if hasattr(value, "__getitem__") else value for name, value in objective.observability.items()},
                    gradients={name: value[index : index + 1].detach().clone() if hasattr(value, "__getitem__") else value for name, value in objective.gradients.items()},
                ),
                stage=stage,
                lineage=(index,),
            )
            for index in selected
        )
        return tensors, hypotheses

    def run(self) -> ExperimentResult:
        started = time.perf_counter()
        checkpoint_paths: dict[str, str] = {}
        stage_timings: dict[str, float] = {}

        # The large Sobol set is a coarse hypothesis generator, not an
        # optimization population.  Optimizing all 256 registrations for all
        # registration iterations made the first stage dominate runtime by
        # more than an order of magnitude.  Score the exact renderer once,
        # retain the diverse winners, and only then run differentiable
        # registration on that small set.
        raw = self._initial_registration_hypotheses()
        zero_mask = torch.zeros(self.nodes, dtype=torch.float32, device=self.device)
        seed_started = time.perf_counter()
        with torch.no_grad():
            _, seed_objective, seed_pose = self._measure(
                raw,
                bone_mask=zero_mask,
                registration_only=True,
            )
        stage_timings["registrationSeed"] = time.perf_counter() - seed_started
        raw, _ = self._retain(
            raw,
            seed_objective,
            seed_pose,
            self.config.registration_keep,
            "registration_seed",
        )
        stage_started = time.perf_counter()
        raw, objective, pose = self._run_stage(
            "registration",
            raw,
            iterations=self.config.registration_iterations,
            learning_rate=self.config.registration_learning_rate,
            bone_mask=torch.zeros(self.nodes, dtype=torch.float32, device=self.device),
            active=(True, False, False, False),
        )
        stage_timings["registration"] = time.perf_counter() - stage_started
        raw, retained = self._retain(raw, objective, pose, self.config.registration_keep, "registration")
        checkpoint = self._write_checkpoint("registration", retained)
        if checkpoint:
            checkpoint_paths["registration"] = checkpoint
        raw = self._seed_motion_root_hypotheses(raw)
        stage_started = time.perf_counter()
        raw, objective, pose = self._run_stage(
            "motion_root",
            raw,
            iterations=self.config.motion_root_iterations,
            learning_rate=self.config.articulated_learning_rate,
            bone_mask=torch.zeros(self.nodes, dtype=torch.float32, device=self.device),
            active=(False, True, True, False),
        )
        stage_timings["motion_root"] = time.perf_counter() - stage_started
        raw, retained = self._retain(raw, objective, pose, self.config.articulated_keep, "motion_root")
        checkpoint = self._write_checkpoint("motion_root", retained)
        if checkpoint:
            checkpoint_paths["motion_root"] = checkpoint
        stage_started = time.perf_counter()
        raw, objective, pose = self._run_stage(
            "proximal",
            raw,
            iterations=self.config.proximal_iterations,
            learning_rate=self.config.articulated_learning_rate,
            bone_mask=self._proximal_mask(True),
            active=(False, False, False, True),
        )
        stage_timings["proximal"] = time.perf_counter() - stage_started
        raw, retained = self._retain(raw, objective, pose, self.config.articulated_keep, "proximal")
        checkpoint = self._write_checkpoint("proximal", retained)
        if checkpoint:
            checkpoint_paths["proximal"] = checkpoint
        stage_started = time.perf_counter()
        raw, objective, pose = self._run_stage(
            "articulated",
            raw,
            iterations=self.config.articulated_iterations,
            learning_rate=self.config.articulated_learning_rate,
            bone_mask=self._proximal_mask(False),
            active=(False, False, False, True),
        )
        stage_timings["articulated"] = time.perf_counter() - stage_started
        raw, retained = self._retain(raw, objective, pose, self.config.articulated_keep, "articulated")
        checkpoint = self._write_checkpoint("articulated", retained)
        if checkpoint:
            checkpoint_paths["articulated"] = checkpoint
        stage_started = time.perf_counter()
        raw, objective, pose = self._run_stage(
            "fine",
            raw,
            iterations=self.config.fine_iterations,
            learning_rate=self.config.fine_learning_rate,
            bone_mask=self._proximal_mask(False),
            active=(False, False, False, True),
        )
        stage_timings["fine"] = time.perf_counter() - stage_started
        raw, final_hypotheses = self._retain(raw, objective, pose, self.config.articulated_keep, "geometry")
        checkpoint = self._write_checkpoint("geometry", final_hypotheses)
        if checkpoint:
            checkpoint_paths["geometry"] = checkpoint
        selected = min(final_hypotheses, key=lambda hypothesis: float(hypothesis.objective.total.mean().item()))
        provenance = {
            "schemaVersion": 2,
            "backend": "nvdiffrast_cuda_triangle",
            "rendererBackend": "nvdiffrast_cuda_triangle",
            "mesh": str(self.session.rig.path),
            "rigFingerprint": self.session.rig.fingerprint,
            "sceneNodeCount": self.nodes,
            "skeletonNodeIndices": list(self.session.rig.skeleton_indices),
            "skeletonNodeNames": [
                self.session.rig.node_names[index]
                for index in self.session.rig.skeleton_indices
            ],
            "clipFingerprint": self.session.clip.fingerprint,
            "frameIndices": list(self.session.clip.frame_indices),
            "sourceKind": self.config.source_kind,
            "sourceDir": str(self.session.clip.source_dir),
            "frameDurations": list(self.session.clip.frame_durations),
            "shadowCullReport": dict(self.session.clip.shadow_cull_report),
            "camera": {
                "width": int(self.session.camera.width),
                "height": int(self.session.camera.height),
                "right": list(self.session.camera.right),
                "down": list(self.session.camera.down),
                "forward": list(self.session.camera.forward),
                "offset": list(self.session.camera.offset),
                "pxPerWorld": list(self.session.camera.px_per_world),
            },
            "frontCamera": None if self.session.front_camera is None else {
                "width": int(self.session.front_camera.width),
                "height": int(self.session.front_camera.height),
                "right": list(self.session.front_camera.right),
                "down": list(self.session.front_camera.down),
                "forward": list(self.session.front_camera.forward),
                "offset": list(self.session.front_camera.offset),
                "pxPerWorld": list(self.session.front_camera.px_per_world),
            },
            "frontView": self.session.clip.front_provenance,
            "config": self.config.to_jsonable(),
        }
        result = ExperimentResult(
            selected=selected,
            alternatives=tuple(final_hypotheses),
            history=tuple(self.history),
            artifacts={"session": str(self.session.artifact_dir / "v2_session.json"), **checkpoint_paths},
            provenance=provenance,
            timings={"total": time.perf_counter() - started, **stage_timings},
        )
        if self.config.semantic_enabled or self.config.dense_semantic_enabled:
            from .semantic import semantic_rerank

            result = semantic_rerank(self.session, result)
        checkpoint = self.session.artifact_dir / "gpu_pose_v2_geometry_checkpoint.json"
        checkpoint.write_text(json.dumps(result.to_jsonable(), indent=2, default=str) + "\n", encoding="utf-8")
        return result


def solve_clip(session: ExperimentSession, *, progress_callback: Any | None = None) -> ExperimentResult:
    """Solve the complete authentic clip using the exact CUDA renderer."""
    return V2Solver(session, progress_callback=progress_callback).run()


def registration_preview(session: ExperimentSession, *, count: int | None = None) -> list[dict[str, Any]]:
    """Score broad static registrations without moving bones or action roots."""
    solver = V2Solver(session)
    raw = solver._initial_registration_hypotheses()
    zero_mask = torch.zeros(solver.nodes, dtype=torch.float32, device=solver.device)
    with torch.no_grad():
        _, objective, pose = solver._measure(raw, bone_mask=zero_mask, registration_only=True)
    order = torch.argsort(objective.total).detach().cpu().tolist()
    limit = int(count or session.config.registration_keep)
    rows = []
    for rank, index in enumerate(order[:limit], start=1):
        rows.append({
            "rank": rank,
            "hypothesis": int(index),
            "loss": float(objective.total[index].item()),
            "iou": float(objective.diagnostics["iou"][index].mean().item()),
            "registration": pose.registration[index].detach().cpu().tolist(),
            "note": "static registration only; bones and motion root are zero",
        })
    return rows
