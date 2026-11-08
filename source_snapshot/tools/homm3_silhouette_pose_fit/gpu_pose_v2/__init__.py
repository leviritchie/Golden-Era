"""HoMM3 GPU pose solver V2.

The V2 lane deliberately does not import the legacy notebook runtime.  Its
public surface is small enough for a notebook to orchestrate without knowing
about glTF, Blender worker commands, or pose-basis conversions.
"""

from .contracts import (
    CameraSpec,
    ExperimentResult,
    ObjectiveBreakdown,
    PoseHypothesis,
    PoseState,
    PreparedClip,
    PreparedRig,
    RenderBuffers,
    V2Config,
    preset_config,
)
from .preflight import ensure_huggingface_auth, preflight
from .session import ExperimentSession, export, prepare_experiment, preview
from .solver import registration_preview, solve_clip
from .blender_export import export_blender_60fps, require_blender_parity
from .bridge import compare_preview_frames

__all__ = [
    "CameraSpec",
    "ExperimentResult",
    "ExperimentSession",
    "ObjectiveBreakdown",
    "PoseHypothesis",
    "PoseState",
    "PreparedClip",
    "PreparedRig",
    "RenderBuffers",
    "V2Config",
    "ensure_huggingface_auth",
    "preflight",
    "preset_config",
    "prepare_experiment",
    "preview",
    "export",
    "compare_preview_frames",
    "solve_clip",
    "registration_preview",
    "export_blender_60fps",
    "require_blender_parity",
]
