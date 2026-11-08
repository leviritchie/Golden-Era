# Source-owned solver. Executed by roc_semantic_hybrid_experiment.initialize; do not run directly.

from tqdm import tqdm
import copy
import itertools
import json
import math
import re
import time
import hashlib
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from IPython.display import display, update_display, Image as IPImage
from roc_temporal_clip_optimizer import (
    ClipProgress,
    TemporalClipConfig,
    _root_rotation_escape_hypotheses,
    optimize_clip as _optimize_clip_state,
)
from roc_rotation_search import (
    continuation_proposal,
    pose_value_to_quaternion,
    quaternion_pose_entry,
    quaternion_to_euler_xyz,
    rotation_vector_proposals,
)

MOTION_ROOT_KEY = "__motion_root__"
LEGACY_BODY_TRANSLATION_KEY = "__body_translation_px__"
BODY_TRANSLATION_KEY = MOTION_ROOT_KEY
MOTION_ROOT_ROTATION_KEY = "__motion_root_rotation__"

# Live watch: each semantic candidate writes target RGB | render RGB and refreshes this output.
LIVE_PREVIEW = bool(globals().get("LIVE_PREVIEW", True))
PREVIEW_EVERY = int(globals().get("PREVIEW_EVERY", 1))  # set to 2/3/... to refresh less often (faster)
PREVIEW_PATH = PILOT / "tmp" / "live_chroma_preview.png"
PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
_LIVE_DISPLAY_ID = 'roc_pose_live_preview'
_LIVE_DISPLAY_STARTED = False
_ANATOMICAL_DISPLAY_ID = 'roc_anatomical_feature_preview'
_ANATOMICAL_DISPLAY_STARTED = False
def update_live_preview_image():
    global _LIVE_DISPLAY_STARTED
    if not PREVIEW_PATH.exists():
        return
    image = IPImage(filename=str(PREVIEW_PATH))
    if _LIVE_DISPLAY_STARTED:
        update_display(image, display_id=_LIVE_DISPLAY_ID)
    else:
        display(image, display_id=_LIVE_DISPLAY_ID)
        _LIVE_DISPLAY_STARTED = True

def update_anatomical_feature_preview():
    global _ANATOMICAL_DISPLAY_STARTED
    if not SHOW_ANATOMICAL_BOXES or not ANATOMICAL_PREVIEW_OUT.exists():
        return
    image = IPImage(filename=str(ANATOMICAL_PREVIEW_OUT))
    if _ANATOMICAL_DISPLAY_STARTED:
        update_display(image, display_id=_ANATOMICAL_DISPLAY_ID)
    else:
        display(image, display_id=_ANATOMICAL_DISPLAY_ID)
        _ANATOMICAL_DISPLAY_STARTED = True
_preview_state = {"n": 0, "best_score": -1.0, "best_label": ""}
_PERFORMANCE_STATS = {
    "scoreCacheHits": 0,
    "scoreCacheMisses": 0,
    "scoreCacheEntries": 0,
    "semanticEmbeddingCacheHits": 0,
    "semanticEmbeddingCacheMisses": 0,
    "semanticImageCacheHits": 0,
    "semanticImageCacheMisses": 0,
    "denseGridCacheHits": 0,
    "denseGridCacheMisses": 0,
    "semanticGlobalSeconds": 0.0,
    "semanticDenseSeconds": 0.0,
    "semanticDenseCompareSeconds": 0.0,
    "semanticBranchBoundPrunes": 0,
    "semanticCandidates": 0,
    "semanticSurvivors": 0,
    "workerBatchCandidates": 0,
    "workerBatchSeconds": 0.0,
    "workerRenderSeconds": 0.0,
    "workerReadSeconds": 0.0,
    "workerRenderCount": 0,
    "workerArtifactCopySeconds": 0.0,
    "proxyCandidates": 0,
    "proxyLevel0Seconds": 0.0,
    "proxyLevel1Seconds": 0.0,
    "proxyRejected": 0,
    "proxyLevel0Rejected": 0,
    "proxyLevel1Rejected": 0,
    "proxyBackend": None,
    "proxyBypassWaves": 0,
    "proxyLevel0Skipped": 0,
    "proxyLevel1Skipped": 0,
    "proxyAuditWaves": 0,
    "proxyAuditCandidates": 0,
    "proxyAuditInvalidWaves": 0,
    "proxyAuditFallbackCandidates": 0,
}
_SCORE_RESULT_CACHE = OrderedDict()
_FILE_DIGEST_CACHE = OrderedDict()
_SEMANTIC_VECTOR_CACHE = OrderedDict()
_DENSE_GRID_CACHE = OrderedDict()
_SEMANTIC_IMAGE_CACHE = OrderedDict()
_PROXY_AUDIT_DISABLED_STAGES = set()
_PROXY_AUDIT_HISTORY = []


def _lru_get(cache, key):
    value = cache.get(key)
    if value is not None:
        cache.move_to_end(key)
    return value


def _lru_put(cache, key, value, limit):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > int(limit):
        cache.popitem(last=False)


def performance_snapshot():
    snapshot = dict(_PERFORMANCE_STATS)
    snapshot["scoreCacheEntries"] = len(_SCORE_RESULT_CACHE)
    snapshot["semanticImageCacheEntries"] = len(_SEMANTIC_IMAGE_CACHE)
    snapshot["denseGridCacheEntries"] = len(_DENSE_GRID_CACHE)
    snapshot["proxyAuditDisabledStages"] = sorted(_PROXY_AUDIT_DISABLED_STAGES)
    snapshot["proxyAuditHistory"] = list(_PROXY_AUDIT_HISTORY[-16:])
    service = globals().get("semantic_service")
    if service is not None:
        snapshot["semanticService"] = service.snapshot()
    return snapshot


def _record_worker_timing(result):
    timing = (result or {}).get("timings") or {}
    renders = timing.get("renders") or []
    _PERFORMANCE_STATS["workerRenderSeconds"] += sum(
        float(item.get("renderSeconds", 0.0)) for item in renders
    )
    _PERFORMANCE_STATS["workerReadSeconds"] += sum(
        float(item.get("readSeconds", 0.0)) for item in renders
    )
    _PERFORMANCE_STATS["workerRenderCount"] += sum(
        int(item.get("renderCount", 1))
        for item in renders
        if item.get("mode") != "rgb_reuse"
    )
    _PERFORMANCE_STATS["workerArtifactCopySeconds"] += float(
        timing.get("semanticCandidateCopySeconds", 0.0)
    )


def _pose_cache_key(frame_index, pose, ik_targets_override=None, ik_bones_override=None):
    # This cache is intentionally run-scoped, but the key still includes the
    # effective render/scoring contract. That keeps an in-process notebook
    # reconfiguration from reusing a result produced by a different camera,
    # mesh scale, lighting, crop, or weighting policy.
    render_contract_names = (
        "SRC_GLB",
        "CAMERA_FIT",
        "SEARCH_SCALE",
        "SEARCH_BUFFER_SCALE",
        "RENDER_WIDTH",
        "RENDER_HEIGHT",
        "RENDER_LIGHTING_MODE",
        "RENDER_SUN_ENERGY",
        "RENDER_SUN_AZIMUTH_DEG",
        "RENDER_SUN_ELEVATION_DEG",
        "RENDER_SUN_ANGLE_DEG",
        "ACTION_CAMERA_ANGLE_DEG",
        "ACTION_CAMERA_ELEVATION_DEG",
        "SEMANTIC_SUBJECT_CROP",
        "SEMANTIC_SUBJECT_PADDING_FRAC",
        "SEMANTIC_ENABLED",
        "SEMANTIC_DENSE_ENABLED",
        "SEMANTIC_DENSE_MODEL_ID",
        "SEMANTIC_DENSE_LOCAL_RADIUS",
        "SEMANTIC_DENSE_POSITION_WEIGHT",
        "SEMANTIC_DENSE_VIEW_INDEX",
        "SEMANTIC_TEXT_ENABLED",
        "SEMANTIC_TEXT_PROMPT",
        "SEMANTIC_NEGATIVE_TEXT_ENABLED",
        "SEMANTIC_NEGATIVE_TEXT_PROMPT",
        "SEMANTIC_MULTIVIEW",
        "SEMANTIC_VIEW_ANGLES_DEG",
        "SEMANTIC_VIEW_ELEVATIONS_DEG",
        "SEMANTIC_VIEW_WEIGHTS",
        "TRIAGE_ENABLED",
        "TRIAGE_SILHOUETTE_ENABLED",
        "TRIAGE_SILHOUETTE_HEURISTIC_ENABLED",
        "TRIAGE_SILHOUETTE_FLOOR",
        "TRIAGE_SILHOUETTE_KEEP_FRACTION",
        "TRIAGE_SILHOUETTE_MIN_CANDIDATES",
        "TRIAGE_SILHOUETTE_MAX_CANDIDATES",
        "SILHOUETTE_DEPTH_WEIGHT",
        "BLUE_ZONE_PENALTY",
        "RED_ZONE_PENALTY",
        "SILHOUETTE_EDGE_BONUS",
        "REVERSE_PROFILE_ENABLED",
        "REVERSE_PROFILE_WEIGHT",
        "PROFILE_HALF_BIAS",
        "DEPTH_MAX_DIST",
        "COLOR_MAX_DIST",
        "PROXY_ENABLED",
        "PROXY_DEVICE",
        "PROXY_MIN_CANDIDATES",
        "PROXY_PROTECTED_STAGES",
        "PROXY_AUDIT_ENABLED",
        "PROXY_AUDIT_FRACTION",
        "PROXY_AUDIT_MAX_CANDIDATES",
        "PROXY_AUDIT_REGRET_TOLERANCE",
        "PROXY_RESOLUTION",
        "PROXY_LEVEL0_ENABLED",
        "PROXY_LEVEL0_POINTS_PER_BONE",
        "PROXY_LEVEL0_KEEP_FRACTION",
        "PROXY_LEVEL0_MIN_CANDIDATES",
        "PROXY_LEVEL0_MAX_CANDIDATES",
        "PROXY_LEVEL1_ENABLED",
        "PROXY_LEVEL1_MAX_VERTICES",
        "PROXY_LEVEL1_KEEP_FRACTION",
        "PROXY_LEVEL1_MIN_CANDIDATES",
        "PROXY_LEVEL1_MAX_CANDIDATES",
        "PROXY_POINT_RADIUS",
        "PROXY_TARGET_ALPHA_THRESHOLD",
        "PROXY_CENTROID_WEIGHT",
        "PROXY_OCCUPANCY_WEIGHT",
        "MOTION_ROOT_ENABLED",
        "MOTION_ROOT_AXES",
        "MOTION_ROOT_FORWARD_RADIUS_BODY_LENGTHS",
        "MOTION_ROOT_LATERAL_RADIUS_BODY_LENGTHS",
        "MOTION_ROOT_VERTICAL_RADIUS_BODY_LENGTHS",
        "MOTION_ROOT_ROTATION_ENABLED",
        "MOTION_ROOT_ROTATION_BASIS",
        "MOTION_ROOT_ROTATION_AXES",
        "MOTION_ROOT_ROTATION_LIMIT_DEG",
    )
    payload = {
        "frame": int(frame_index),
        "pose": pose,
        "ikTargets": ik_targets_override or {},
        "ikBones": list(ik_bones_override or ()),
        "scoreMode": SCORE_MODE,
        "target": str(globals().get("ANIMATION_TARGET_FRAMES", "")),
        "targetDepth": str(globals().get("TARGET_DEPTH", "")),
        "semantic": bool(SEMANTIC_ONLY),
        "semanticModel": SEMANTIC_MODEL_ID,
        "embeddingLayers": list(globals().get("SEMANTIC_EMBEDDING_LAYERS", ())),
        "denseLayers": list(globals().get("SEMANTIC_DENSE_EMBEDDING_LAYERS", ())),
        "weights": [
            HYBRID_SEMANTIC_WEIGHT,
            HYBRID_GEOMETRY_WEIGHT,
            SEMANTIC_DENSE_WEIGHT,
            HYBRID_TEXT_WEIGHT,
            HYBRID_NEGATIVE_TEXT_WEIGHT,
            HYBRID_ANATOMICAL_WEIGHT,
        ],
        "renderContract": {
            name: globals().get(name)
            for name in render_contract_names
            if name in globals()
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cache_score_result(key, value):
    if not SEMANTIC_CANDIDATE_CACHE_ENABLED:
        return
    _lru_put(
        _SCORE_RESULT_CACHE,
        key,
        (float(value[0]), copy.deepcopy(value[1]), float(value[2])),
        SEMANTIC_CANDIDATE_CACHE_MAX_ENTRIES,
    )


def _file_digest(path):
    path = Path(path)
    stat = path.stat()
    cache_key = (str(path.resolve()), int(stat.st_size), int(stat.st_mtime_ns))
    cached = _lru_get(_FILE_DIGEST_CACHE, cache_key)
    if cached is not None:
        return cached
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    _lru_put(_FILE_DIGEST_CACHE, cache_key, digest, SEMANTIC_CANDIDATE_CACHE_MAX_ENTRIES)
    return digest
HYBRID_SEMANTIC_WEIGHT = float(globals().get("HYBRID_SEMANTIC_WEIGHT", 0.70))
HYBRID_DEPTH_WEIGHT = float(globals().get("HYBRID_DEPTH_WEIGHT", 0.30))  # legacy alias
HYBRID_GEOMETRY_WEIGHT = float(
    globals().get("HYBRID_GEOMETRY_WEIGHT", HYBRID_DEPTH_WEIGHT)
)
HYBRID_GEOMETRY_ENABLED = bool(globals().get("HYBRID_GEOMETRY_ENABLED", True))
ANATOMICAL_BOXES_ENABLED = bool(globals().get("ANATOMICAL_BOXES_ENABLED", False))
ANATOMICAL_PART_WEIGHT = float(globals().get("ANATOMICAL_PART_WEIGHT", 0.20))
HYBRID_ANATOMICAL_WEIGHT = float(globals().get("HYBRID_ANATOMICAL_WEIGHT", 0.0))
ANATOMICAL_CENTER_WEIGHT = float(globals().get("ANATOMICAL_CENTER_WEIGHT", 0.70))
ANATOMICAL_EXTENT_WEIGHT = float(globals().get("ANATOMICAL_EXTENT_WEIGHT", 0.30))
SEMANTIC_ENABLED = bool(
    globals().get("SEMANTIC_ENABLED", globals().get("SEMANTIC_ONLY", True))
)
SEMANTIC_TEXT_ENABLED = bool(globals().get("SEMANTIC_TEXT_ENABLED", False))
SEMANTIC_TEXT_PROMPT = str(globals().get("SEMANTIC_TEXT_PROMPT", "a roc flying in side profile"))
HYBRID_TEXT_WEIGHT = float(globals().get("HYBRID_TEXT_WEIGHT", 0.0))
SEMANTIC_NEGATIVE_TEXT_ENABLED = bool(globals().get("SEMANTIC_NEGATIVE_TEXT_ENABLED", False))
SEMANTIC_NEGATIVE_TEXT_PROMPT = str(globals().get("SEMANTIC_NEGATIVE_TEXT_PROMPT", ""))
HYBRID_NEGATIVE_TEXT_WEIGHT = float(globals().get("HYBRID_NEGATIVE_TEXT_WEIGHT", 0.0))
SILHOUETTE_DEPTH_WEIGHT = float(globals().get("SILHOUETTE_DEPTH_WEIGHT", 1.0))
BLUE_ZONE_PENALTY = float(globals().get("BLUE_ZONE_PENALTY", 2.5))
RED_ZONE_PENALTY = float(globals().get("RED_ZONE_PENALTY", 1.0))
SILHOUETTE_EDGE_BONUS = float(globals().get("SILHOUETTE_EDGE_BONUS", 0.0))
REVERSE_PROFILE_ENABLED = bool(globals().get("REVERSE_PROFILE_ENABLED", False))
REVERSE_PROFILE_WEIGHT = float(globals().get("REVERSE_PROFILE_WEIGHT", 0.5))
PROFILE_HALF_BIAS = float(globals().get("PROFILE_HALF_BIAS", 0.5))
IK_ENABLED = bool(globals().get("IK_ENABLED", False))
IK_MODE = str(globals().get("IK_MODE", "off"))
IK_BONES = tuple(globals().get("IK_BONES", ()))
IK_TARGETS = dict(globals().get("IK_TARGETS", {}))
IK_TARGET_SEARCH_ENABLED = bool(globals().get("IK_TARGET_SEARCH_ENABLED", False))
IK_TARGET_SEARCH_ONLY = bool(globals().get("IK_TARGET_SEARCH_ONLY", False))
IK_TARGET_SEARCH_BONES = tuple(globals().get("IK_TARGET_SEARCH_BONES", ()))
IK_TARGET_COARSE_STEP_PX = float(globals().get("IK_TARGET_COARSE_STEP_PX", 24.0))
IK_TARGET_REFINE_STEP_PX = float(globals().get("IK_TARGET_REFINE_STEP_PX", 6.0))
IK_TARGET_SEARCH_RADIUS_PX = float(globals().get("IK_TARGET_SEARCH_RADIUS_PX", 48.0))
IK_TARGET_MIN_IMPROVEMENT = float(globals().get("IK_TARGET_MIN_IMPROVEMENT", 0.0))
IK_CHAIN_LENGTH = int(globals().get("IK_CHAIN_LENGTH", 1))
IK_ITERATIONS = int(globals().get("IK_ITERATIONS", 8))
IK_STRENGTH = float(globals().get("IK_STRENGTH", 1.0))
IK_DEPTH = float(globals().get("IK_DEPTH", 6.0))
_raw_motion_root_axes = globals().get("MOTION_ROOT_AXES", ("forward",))
if isinstance(_raw_motion_root_axes, str):
    _raw_motion_root_axes = tuple(
        part.strip() for part in _raw_motion_root_axes.split(",") if part.strip()
    )
MOTION_ROOT_AXES = tuple(
    str(axis).strip().lower()
    for axis in _raw_motion_root_axes
    if str(axis).strip().lower() in {"forward", "lateral", "vertical"}
)
MOTION_ROOT_ENABLED = bool(
    globals().get("MOTION_ROOT_ENABLED", globals().get("BODY_TRANSLATION_ENABLED", False))
)
MOTION_ROOT_FORWARD_RADIUS_BODY_LENGTHS = float(
    globals().get("MOTION_ROOT_FORWARD_RADIUS_BODY_LENGTHS", 0.20)
)
MOTION_ROOT_LATERAL_RADIUS_BODY_LENGTHS = float(
    globals().get("MOTION_ROOT_LATERAL_RADIUS_BODY_LENGTHS", 0.05)
)
MOTION_ROOT_VERTICAL_RADIUS_BODY_LENGTHS = float(
    globals().get("MOTION_ROOT_VERTICAL_RADIUS_BODY_LENGTHS", 0.0)
)
MOTION_ROOT_COARSE_STEP_BODY_LENGTHS = float(
    globals().get("MOTION_ROOT_COARSE_STEP_BODY_LENGTHS", 0.05)
)
MOTION_ROOT_REFINE_STEP_BODY_LENGTHS = float(
    globals().get("MOTION_ROOT_REFINE_STEP_BODY_LENGTHS", 0.0125)
)
MOTION_ROOT_MAGNITUDE_WEIGHT = float(
    globals().get("MOTION_ROOT_MAGNITUDE_WEIGHT", 0.01)
)
MOTION_ROOT_VELOCITY_WEIGHT = float(
    globals().get("MOTION_ROOT_VELOCITY_WEIGHT", 0.02)
)
MOTION_ROOT_ACCELERATION_WEIGHT = float(
    globals().get("MOTION_ROOT_ACCELERATION_WEIGHT", 0.01)
)
MOTION_ROOT_LOOP_WEIGHT = float(globals().get("MOTION_ROOT_LOOP_WEIGHT", 0.0))
MOTION_ROOT_LOOP_VELOCITY_WEIGHT = float(
    globals().get("MOTION_ROOT_LOOP_VELOCITY_WEIGHT", 0.0)
)
MOTION_ROOT_COUPLED_BLOCKS_ENABLED = bool(
    globals().get("MOTION_ROOT_COUPLED_BLOCKS_ENABLED", True)
)
MOTION_ROOT_ROTATION_ENABLED = bool(
    globals().get("MOTION_ROOT_ROTATION_ENABLED", False)
)
MOTION_ROOT_ROTATION_BASIS = str(
    globals().get("MOTION_ROOT_ROTATION_BASIS", "camera")
).strip().lower()
_raw_motion_root_rotation_axes = globals().get(
    "MOTION_ROOT_ROTATION_AXES",
    ("camera_forward",),
)
if isinstance(_raw_motion_root_rotation_axes, str):
    _raw_motion_root_rotation_axes = tuple(
        part.strip()
        for part in _raw_motion_root_rotation_axes.split(",")
        if part.strip()
    )
MOTION_ROOT_ROTATION_AXES = tuple(
    str(axis).strip().lower()
    for axis in _raw_motion_root_rotation_axes
    if str(axis).strip().lower()
    in {"camera_forward", "camera_right", "camera_up"}
)
MOTION_ROOT_ROTATION_LIMIT_DEG = float(
    globals().get("MOTION_ROOT_ROTATION_LIMIT_DEG", 180.0)
)
MOTION_ROOT_ROTATION_COARSE_STEP_DEG = float(
    globals().get("MOTION_ROOT_ROTATION_COARSE_STEP_DEG", 30.0)
)
MOTION_ROOT_ROTATION_REFINE_STEP_DEG = float(
    globals().get("MOTION_ROOT_ROTATION_REFINE_STEP_DEG", 10.0)
)
MOTION_ROOT_ROTATION_ESCAPE_ENABLED = bool(
    globals().get("MOTION_ROOT_ROTATION_ESCAPE_ENABLED", True)
)
_raw_motion_root_rotation_escape_axes = globals().get(
    "MOTION_ROOT_ROTATION_ESCAPE_AXES",
    ("camera_forward",),
)
if isinstance(_raw_motion_root_rotation_escape_axes, str):
    _raw_motion_root_rotation_escape_axes = tuple(
        part.strip()
        for part in _raw_motion_root_rotation_escape_axes.split(",")
        if part.strip()
    )
MOTION_ROOT_ROTATION_ESCAPE_AXES = tuple(
    str(axis).strip().lower()
    for axis in _raw_motion_root_rotation_escape_axes
    if str(axis).strip().lower() in MOTION_ROOT_ROTATION_AXES
)
MOTION_ROOT_ROTATION_ESCAPE_ANGLES_DEG = tuple(
    float(angle)
    for angle in globals().get(
        "MOTION_ROOT_ROTATION_ESCAPE_ANGLES_DEG",
        (-180.0, -150.0, -120.0, -90.0, -60.0, -30.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0),
    )
)
MOTION_ROOT_ROTATION_ESCAPE_TOP_K = int(
    globals().get("MOTION_ROOT_ROTATION_ESCAPE_TOP_K", 4)
)
MOTION_ROOT_ROTATION_ESCAPE_FORCE_IMAGE_BEST = bool(
    globals().get("MOTION_ROOT_ROTATION_ESCAPE_FORCE_IMAGE_BEST", True)
)
MOTION_ROOT_ROTATION_ESCAPE_MIN_IMAGE_IMPROVEMENT = float(
    globals().get("MOTION_ROOT_ROTATION_ESCAPE_MIN_IMAGE_IMPROVEMENT", 0.0)
)
MOTION_ROOT_ROTATION_ESCAPE_RELAX_ENABLED = bool(
    globals().get("MOTION_ROOT_ROTATION_ESCAPE_RELAX_ENABLED", True)
)
MOTION_ROOT_ROTATION_ESCAPE_RELAX_BONE_COUNT = int(
    globals().get("MOTION_ROOT_ROTATION_ESCAPE_RELAX_BONE_COUNT", 3)
)
MOTION_ROOT_ROTATION_ESCAPE_RELAX_ROUNDS = int(
    globals().get("MOTION_ROOT_ROTATION_ESCAPE_RELAX_ROUNDS", 1)
)
MOTION_ROOT_ROTATION_ESCAPE_RELAX_STEP_DEG = float(
    globals().get("MOTION_ROOT_ROTATION_ESCAPE_RELAX_STEP_DEG", 12.0)
)
MOTION_ROOT_ROTATION_ESCAPE_RELAX_REFINE_STEP_DEG = float(
    globals().get("MOTION_ROOT_ROTATION_ESCAPE_RELAX_REFINE_STEP_DEG", 4.0)
)
MOTION_ROOT_ROTATION_MAGNITUDE_WEIGHT = float(
    globals().get("MOTION_ROOT_ROTATION_MAGNITUDE_WEIGHT", 0.0)
)
MOTION_ROOT_ROTATION_VELOCITY_WEIGHT = float(
    globals().get("MOTION_ROOT_ROTATION_VELOCITY_WEIGHT", 0.02)
)
MOTION_ROOT_ROTATION_ACCELERATION_WEIGHT = float(
    globals().get("MOTION_ROOT_ROTATION_ACCELERATION_WEIGHT", 0.01)
)
MOTION_ROOT_ROTATION_LOOP_WEIGHT = float(
    globals().get("MOTION_ROOT_ROTATION_LOOP_WEIGHT", 0.0)
)
MOTION_ROOT_ROTATION_LOOP_VELOCITY_WEIGHT = float(
    globals().get("MOTION_ROOT_ROTATION_LOOP_VELOCITY_WEIGHT", 0.0)
)
MOTION_ROOT_ROTATION_COUPLED_BLOCKS_ENABLED = bool(
    globals().get("MOTION_ROOT_ROTATION_COUPLED_BLOCKS_ENABLED", True)
)
# Deprecated diagnostic aliases. The search itself uses normalized body
# lengths and no longer proposes image-space pixel offsets.
BODY_TRANSLATION_ENABLED = MOTION_ROOT_ENABLED
BODY_TRANSLATION_RADIUS_PX = float(globals().get("BODY_TRANSLATION_RADIUS_PX", 48.0))
BODY_TRANSLATION_COARSE_STEP_PX = float(globals().get("BODY_TRANSLATION_COARSE_STEP_PX", 12.0))
BODY_TRANSLATION_REFINE_STEP_PX = float(globals().get("BODY_TRANSLATION_REFINE_STEP_PX", 3.0))
TRIAGE_ENABLED = bool(globals().get("TRIAGE_ENABLED", True))
TRIAGE_SILHOUETTE_ENABLED = bool(
    globals().get("TRIAGE_SILHOUETTE_ENABLED", True)
)
TRIAGE_SILHOUETTE_HEURISTIC_ENABLED = bool(
    globals().get("TRIAGE_SILHOUETTE_HEURISTIC_ENABLED", False)
)
TRIAGE_SILHOUETTE_FLOOR = float(
    globals().get("TRIAGE_SILHOUETTE_FLOOR", 0.02)
)
TRIAGE_SILHOUETTE_KEEP_FRACTION = float(
    globals().get("TRIAGE_SILHOUETTE_KEEP_FRACTION", 0.50)
)
TRIAGE_SILHOUETTE_MIN_CANDIDATES = int(
    globals().get("TRIAGE_SILHOUETTE_MIN_CANDIDATES", 3)
)
SEMANTIC_BRANCH_BOUND_ENABLED = bool(
    globals().get("SEMANTIC_BRANCH_BOUND_ENABLED", True)
)
SEMANTIC_BRANCH_BOUND_MARGIN = float(
    globals().get("SEMANTIC_BRANCH_BOUND_MARGIN", 0.0)
)
SEMANTIC_CANDIDATE_CACHE_ENABLED = bool(
    globals().get("SEMANTIC_CANDIDATE_CACHE_ENABLED", True)
)
SEMANTIC_CANDIDATE_CACHE_MAX_ENTRIES = int(
    globals().get("SEMANTIC_CANDIDATE_CACHE_MAX_ENTRIES", 4096)
)
SEMANTIC_IMAGE_CACHE_MAX_ENTRIES = int(
    globals().get("SEMANTIC_IMAGE_CACHE_MAX_ENTRIES", 256)
)
SEMANTIC_DENSE_GRID_CACHE_MAX_ENTRIES = int(
    globals().get("SEMANTIC_DENSE_GRID_CACHE_MAX_ENTRIES", 128)
)
SEMANTIC_SERVICE_ENABLED = bool(globals().get("SEMANTIC_SERVICE_ENABLED", True))
SEMANTIC_SERVICE_CACHE_GENERATION = str(
    globals().get("SEMANTIC_SERVICE_CACHE_GENERATION", "v1")
).strip()
SEMANTIC_SERVICE_ENCODER_CACHE_MAX_ENTRIES = int(
    globals().get("SEMANTIC_SERVICE_ENCODER_CACHE_MAX_ENTRIES", 2)
)
SEMANTIC_SERVICE_TARGET_CACHE_MAX_ENTRIES = int(
    globals().get("SEMANTIC_SERVICE_TARGET_CACHE_MAX_ENTRIES", 512)
)
SEMANTIC_SERVICE_DENSE_TARGET_CACHE_MAX_ENTRIES = int(
    globals().get("SEMANTIC_SERVICE_DENSE_TARGET_CACHE_MAX_ENTRIES", 128)
)
if not math.isfinite(TRIAGE_SILHOUETTE_FLOOR) or not 0.0 <= TRIAGE_SILHOUETTE_FLOOR <= 1.0:
    raise ValueError("TRIAGE_SILHOUETTE_FLOOR must be between 0 and 1")
if not math.isfinite(TRIAGE_SILHOUETTE_KEEP_FRACTION) or not 0.0 < TRIAGE_SILHOUETTE_KEEP_FRACTION <= 1.0:
    raise ValueError("TRIAGE_SILHOUETTE_KEEP_FRACTION must be in (0, 1]")
if TRIAGE_SILHOUETTE_MIN_CANDIDATES < 1:
    raise ValueError("TRIAGE_SILHOUETTE_MIN_CANDIDATES must be at least 1")
if not math.isfinite(SEMANTIC_BRANCH_BOUND_MARGIN) or SEMANTIC_BRANCH_BOUND_MARGIN < 0.0:
    raise ValueError("SEMANTIC_BRANCH_BOUND_MARGIN must be finite and non-negative")
if SEMANTIC_CANDIDATE_CACHE_MAX_ENTRIES < 1:
    raise ValueError("SEMANTIC_CANDIDATE_CACHE_MAX_ENTRIES must be positive")
if SEMANTIC_IMAGE_CACHE_MAX_ENTRIES < 1:
    raise ValueError("SEMANTIC_IMAGE_CACHE_MAX_ENTRIES must be positive")
if SEMANTIC_DENSE_GRID_CACHE_MAX_ENTRIES < 1:
    raise ValueError("SEMANTIC_DENSE_GRID_CACHE_MAX_ENTRIES must be positive")
if SEMANTIC_SERVICE_ENCODER_CACHE_MAX_ENTRIES < 1:
    raise ValueError("SEMANTIC_SERVICE_ENCODER_CACHE_MAX_ENTRIES must be positive")
if not SEMANTIC_SERVICE_CACHE_GENERATION:
    raise ValueError("SEMANTIC_SERVICE_CACHE_GENERATION must be non-empty")
if SEMANTIC_SERVICE_TARGET_CACHE_MAX_ENTRIES < 1:
    raise ValueError("SEMANTIC_SERVICE_TARGET_CACHE_MAX_ENTRIES must be positive")
if SEMANTIC_SERVICE_DENSE_TARGET_CACHE_MAX_ENTRIES < 1:
    raise ValueError(
        "SEMANTIC_SERVICE_DENSE_TARGET_CACHE_MAX_ENTRIES must be positive"
    )
for _weight_name, _weight_value in (
    ("HYBRID_SEMANTIC_WEIGHT", HYBRID_SEMANTIC_WEIGHT),
    ("HYBRID_GEOMETRY_WEIGHT", HYBRID_GEOMETRY_WEIGHT),
    ("HYBRID_TEXT_WEIGHT", HYBRID_TEXT_WEIGHT),
    ("HYBRID_NEGATIVE_TEXT_WEIGHT", HYBRID_NEGATIVE_TEXT_WEIGHT),
    ("HYBRID_ANATOMICAL_WEIGHT", HYBRID_ANATOMICAL_WEIGHT),
    ("SEMANTIC_DENSE_WEIGHT", SEMANTIC_DENSE_WEIGHT),
):
    if not math.isfinite(_weight_value) or _weight_value < 0.0:
        raise ValueError(f"{_weight_name} must be finite and non-negative")
if not 0.0 <= ANATOMICAL_PART_WEIGHT <= 1.0:
    raise ValueError("ANATOMICAL_PART_WEIGHT must be between 0 and 1")
if ANATOMICAL_CENTER_WEIGHT < 0.0 or ANATOMICAL_EXTENT_WEIGHT < 0.0:
    raise ValueError("anatomical center/extent weights must be non-negative")
if ANATOMICAL_CENTER_WEIGHT + ANATOMICAL_EXTENT_WEIGHT <= 0.0:
    raise ValueError("anatomical center/extent weights must have a positive sum")
ANATOMICAL_MAX_FEATURES = int(globals().get("ANATOMICAL_MAX_FEATURES", 8))
ANATOMICAL_MIN_AREA_FRAC = float(globals().get("ANATOMICAL_MIN_AREA_FRAC", 0.001))
if ANATOMICAL_MAX_FEATURES < 1:
    raise ValueError("ANATOMICAL_MAX_FEATURES must be at least 1")
if not 0.0 <= ANATOMICAL_MIN_AREA_FRAC <= 1.0:
    raise ValueError("ANATOMICAL_MIN_AREA_FRAC must be between 0 and 1")
if HYBRID_ANATOMICAL_WEIGHT > 0.0 and not ANATOMICAL_BOXES_ENABLED:
    raise ValueError("HYBRID_ANATOMICAL_WEIGHT requires ANATOMICAL_BOXES_ENABLED=True")
if SEMANTIC_TEXT_ENABLED and not SEMANTIC_TEXT_PROMPT.strip():
    raise ValueError("SEMANTIC_TEXT_PROMPT must be non-empty when SEMANTIC_TEXT_ENABLED=True")
if SEMANTIC_NEGATIVE_TEXT_ENABLED and not SEMANTIC_NEGATIVE_TEXT_PROMPT.strip():
    raise ValueError(
        "SEMANTIC_NEGATIVE_TEXT_PROMPT must be non-empty when SEMANTIC_NEGATIVE_TEXT_ENABLED=True"
    )
if HYBRID_NEGATIVE_TEXT_WEIGHT > 0.0 and not SEMANTIC_NEGATIVE_TEXT_ENABLED:
    raise ValueError(
        "HYBRID_NEGATIVE_TEXT_WEIGHT requires SEMANTIC_NEGATIVE_TEXT_ENABLED=True"
    )
def _cosine_to_quality(value):
    return float((float(np.clip(value, -1.0, 1.0)) + 1.0) * 0.5)


def _worker_feature_summary(result):
    """Describe the active worker-side objective without double-counting it.

    The Blender worker owns the geometric score. Its ``iou`` already includes
    the currently enabled depth/silhouette or chroma term, asymmetric blue/red
    zones, edge emphasis, reverse profile, and anatomical boxes. Keep that as
    one normalized geometry component and expose its subfeatures for audit.
    """
    result = result or {}
    subfeatures = {
        "scoreMode": result.get("scoreMode"),
        "depthUsed": bool(result.get("depthUsed", False)),
        "silhouetteDepthWeight": result.get("silhouetteDepthWeight"),
        "primarySilhouetteIoU": result.get("primarySilhouetteIoU"),
        "reverseProfileEnabled": bool(result.get("reverseProfileEnabled", False)),
        "reverseProfileIoU": result.get("reverseProfileIoU"),
        "reverseProfileWeight": result.get("reverseProfileWeight"),
        "profileHalfBias": result.get("profileHalfBias"),
        "anatomicalPartIoU": result.get("anatomicalPartIoU"),
        "anatomicalFeatureDistance": result.get("anatomicalFeatureDistance"),
        "anatomicalPartWeight": result.get("anatomicalPartWeight"),
        "anatomicalBoxesEnabled": result.get("anatomicalBoxesEnabled"),
        "anatomicalTargetCount": result.get("anatomicalTargetCount"),
        "anatomicalCandidateCount": result.get("anatomicalCandidateCount"),
        "predOnlyPenalty": result.get("predOnlyPenalty"),
        "targetOnlyPenalty": result.get("targetOnlyPenalty"),
        "targetEdgeBonus": result.get("targetEdgeBonus"),
        "zoneDiagnostics": result.get("zoneDiagnostics"),
    }
    enabled = []
    anatomical_boxes_used = bool(result.get("anatomicalBoxesEnabled", False))
    reverse_profile_used = bool(result.get("reverseProfileEnabled")) and (
        result.get("reverseProfileIoU") is not None
    )
    if str(result.get("scoreMode", "")).lower() == "chroma":
        enabled.append("chroma")
    elif bool(result.get("depthUsed", False)):
        enabled.append("depth")
    if result.get("primarySilhouetteIoU") is not None:
        enabled.append("silhouette")
    if reverse_profile_used:
        enabled.append("reverse_profile")
    if anatomical_boxes_used:
        enabled.append("anatomical_parts")
    if result.get("predOnlyPenalty", 0.0) or result.get("targetOnlyPenalty", 0.0):
        enabled.append("zone_penalties")
    if result.get("targetEdgeBonus", 0.0):
        enabled.append("silhouette_edge")
    return {
        "enabled": enabled,
        "details": subfeatures,
        "reverseProfileUsed": reverse_profile_used,
        "anatomicalBoxesUsed": anatomical_boxes_used,
    }


def _triage_silhouette_score(result):
    """Return the cheap primary silhouette score from a worker response."""
    result = result or {}
    for key in ("primarySilhouetteIoU", "silhouetteIoU", "workerIoU", "iou"):
        value = result.get(key)
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return float(np.clip(value, 0.0, 1.0))
    return 0.0


def _triage_reject(result):
    """Mark a candidate rejected before semantic work, without hiding worker data."""
    silhouette = _triage_silhouette_score(result)
    enabled = bool(
        TRIAGE_ENABLED
        and TRIAGE_SILHOUETTE_ENABLED
        and TRIAGE_SILHOUETTE_HEURISTIC_ENABLED
        and SEMANTIC_ONLY
    )
    rejected = enabled and silhouette < TRIAGE_SILHOUETTE_FLOOR
    result["triageEnabled"] = enabled
    result["triageSilhouette"] = silhouette
    result["triageRejected"] = bool(rejected)
    result["triageReason"] = "silhouette_floor" if rejected else None
    if rejected:
        result["workerIoU"] = result.get("workerIoU", result.get("iou"))
        result["iou"] = -1.0
        result["hybridScore"] = -1.0
    return bool(rejected)


def _triage_batch_indices(results):
    """Choose semantic survivors after one parallel Blender render wave."""
    total = len(results)
    if not (
        TRIAGE_ENABLED
        and TRIAGE_SILHOUETTE_ENABLED
        and TRIAGE_SILHOUETTE_HEURISTIC_ENABLED
        and SEMANTIC_ONLY
    ):
        return set(range(total)), {
            "enabled": False,
            "total": total,
            "survivors": total,
            "rejected": 0,
            "floor": TRIAGE_SILHOUETTE_FLOOR,
            "keepFraction": TRIAGE_SILHOUETTE_KEEP_FRACTION,
        }
    scores = [_triage_silhouette_score(result) for result in results]
    floor_indices = [
        index for index, score in enumerate(scores) if score >= TRIAGE_SILHOUETTE_FLOOR
    ]
    keep_count = min(
        total,
        max(
            int(TRIAGE_SILHOUETTE_MIN_CANDIDATES),
            int(math.ceil(total * TRIAGE_SILHOUETTE_KEEP_FRACTION)),
        ),
    )
    max_candidates = int(globals().get("TRIAGE_SILHOUETTE_MAX_CANDIDATES", 0))
    if max_candidates > 0:
        keep_count = min(keep_count, max_candidates)
    ranked = sorted(range(total), key=lambda index: scores[index], reverse=True)
    survivors = set(index for index in ranked[:keep_count] if index in floor_indices)
    if not survivors and floor_indices:
        survivors.add(max(floor_indices, key=lambda index: scores[index]))
    diagnostics = {
        "enabled": True,
        "total": total,
        "survivors": len(survivors),
        "rejected": total - len(survivors),
        "floor": TRIAGE_SILHOUETTE_FLOOR,
        "keepFraction": TRIAGE_SILHOUETTE_KEEP_FRACTION,
        "minCandidates": TRIAGE_SILHOUETTE_MIN_CANDIDATES,
        "maxCandidates": max_candidates,
        "silhouetteScores": scores,
    }
    return survivors, diagnostics


_PROXY_TARGET_CACHE = OrderedDict()


def _proxy_target_alpha(frame_index):
    """Load one downsampled target alpha mask; never asks Blender to render it."""
    width = int(globals().get("geometric_proxy_width", 0))
    height = int(globals().get("geometric_proxy_height", 0))
    threshold = int(globals().get("PROXY_TARGET_ALPHA_THRESHOLD", 8))
    path = Path(ANIMATION_TARGET_FRAMES) / f"{int(frame_index):02d}.png"
    if width <= 0 or height <= 0 or not path.is_file():
        raise RuntimeError(f"geometric proxy target is unavailable: {path}")
    stat = path.stat()
    key = (str(path.resolve()), int(stat.st_size), int(stat.st_mtime_ns), width, height, threshold)
    cached = _lru_get(_PROXY_TARGET_CACHE, key)
    if cached is not None:
        return cached
    with Image.open(path) as source:
        alpha = np.asarray(source.convert("RGBA"), dtype=np.uint8)[:, :, 3]
    # Threshold before the resize so transparent shadow pixels cannot become
    # valid subject pixels through interpolation.
    binary = (alpha >= threshold).astype(np.uint8) * 255
    resized = Image.fromarray(binary, mode="L").resize(
        (width, height),
        resample=Image.Resampling.LANCZOS,
    )
    mask = np.asarray(resized, dtype=np.uint8) >= 128
    _lru_put(_PROXY_TARGET_CACHE, key, mask, 64)
    return mask


def _proxy_keep_count(total, fraction, minimum, maximum):
    count = min(
        int(total),
        max(int(minimum), int(math.ceil(float(total) * float(fraction)))),
    )
    if int(maximum) > 0:
        count = min(count, int(maximum))
    return max(1, count) if total else 0


def _proxy_rank_score(score):
    score = score or {}
    width = max(1, int(globals().get("geometric_proxy_width", 1)))
    height = max(1, int(globals().get("geometric_proxy_height", 1)))
    diagonal = math.hypot(width, height)
    return float(score.get("iou", 0.0)) - float(
        globals().get("PROXY_CENTROID_WEIGHT", 0.10)
    ) * float(score.get("centroidDistancePx", diagonal)) / diagonal - float(
        globals().get("PROXY_OCCUPANCY_WEIGHT", 0.05)
    ) * float(score.get("occupancyError", 1.0))


def _proxy_stage_name(stage):
    return str(stage or "default")


def _proxy_bypass_diagnostics(total, reason, *, stage=None):
    return {
        "enabled": False,
        "bypassed": True,
        "bypassReason": str(reason),
        "stage": _proxy_stage_name(stage),
        "total": int(total),
        "survivors": int(total),
        "rejected": 0,
    }


def _proxy_audit_indices(rejected, metadata, *, stage=None):
    """Choose a deterministic shadow sample from proxy-rejected candidates."""
    if not bool(globals().get("PROXY_AUDIT_ENABLED", False)) or not rejected:
        return set()
    if _proxy_stage_name(stage) in _PROXY_AUDIT_DISABLED_STAGES:
        return set()
    fraction = float(globals().get("PROXY_AUDIT_FRACTION", 0.10))
    if fraction <= 0.0:
        return set()
    maximum = int(globals().get("PROXY_AUDIT_MAX_CANDIDATES", 4))
    count = max(1, int(math.ceil(len(rejected) * fraction)))
    if maximum > 0:
        count = min(count, maximum)
    ranked = sorted(
        rejected,
        key=lambda index: float(
            (metadata.get(index) or {}).get(
                "level1Score",
                (metadata.get(index) or {}).get("level0Score", -1.0),
            )
        ),
        reverse=True,
    )
    if count >= len(ranked):
        return set(ranked)
    # Always audit the closest-to-cutoff rejected candidate, then spread the
    # remaining samples across the rejected rank range.
    selected = [ranked[0]]
    if count > 1:
        positions = np.linspace(1, len(ranked) - 1, count - 1, dtype=int)
        selected.extend(ranked[int(position)] for position in positions)
    return set(selected[:count])


def _proxy_rank(values):
    order = sorted(range(len(values)), key=lambda index: float(values[index]))
    ranks = [0.0] * len(values)
    for rank, index in enumerate(order):
        ranks[index] = float(rank)
    return np.asarray(ranks, dtype=np.float64)


def _proxy_audit_metrics(rows):
    """Compare exact scores for survivors and the sampled rejected set."""
    valid = [row for row in rows if row.get("fullScore") is not None]
    if not valid:
        return {
            "sampledCandidateCount": 0,
            "survivorCount": 0,
            "rejectedCount": 0,
            "winner_recall": None,
            "top4_recall": None,
            "proxy_full_rank_correlation": None,
            "regret": None,
            "invalid": False,
        }
    full_sorted = sorted(valid, key=lambda row: float(row["fullScore"]), reverse=True)
    top4 = full_sorted[: min(4, len(full_sorted))]
    survivor_ids = {row["index"] for row in valid if row.get("survived")}
    winner_recall = bool(full_sorted[0]["index"] in survivor_ids)
    top4_recall = float(sum(row["index"] in survivor_ids for row in top4) / max(1, len(top4)))
    proxy_values = [float(row["proxyScore"]) for row in valid]
    full_values = [float(row["fullScore"]) for row in valid]
    proxy_ranks = _proxy_rank(proxy_values)
    full_ranks = _proxy_rank(full_values)
    if len(valid) < 2 or float(np.std(proxy_ranks)) <= 1e-12 or float(np.std(full_ranks)) <= 1e-12:
        correlation = None
    else:
        correlation = float(np.corrcoef(proxy_ranks, full_ranks)[0, 1])
    rejected_scores = [float(row["fullScore"]) for row in valid if not row.get("survived")]
    survivor_scores = [float(row["fullScore"]) for row in valid if row.get("survived")]
    regret = (
        float(max(rejected_scores) - max(survivor_scores))
        if rejected_scores and survivor_scores
        else None
    )
    tolerance = float(globals().get("PROXY_AUDIT_REGRET_TOLERANCE", 0.0))
    return {
        "sampledCandidateCount": len(valid),
        "survivorCount": len(survivor_scores),
        "rejectedCount": len(rejected_scores),
        "winner_recall": winner_recall,
        "top4_recall": top4_recall,
        "proxy_full_rank_correlation": correlation,
        "maxRejectedFullScore": max(rejected_scores) if rejected_scores else None,
        "maxSurvivedFullScore": max(survivor_scores) if survivor_scores else None,
        "regret": regret,
        "regretTolerance": tolerance,
        "invalid": bool(regret is not None and regret > tolerance),
    }


def _proxy_filter_entries(frame_index, entries, *, stage=None, enabled_override=None):
    """Run Level 0 and Level 1 proxy ranking over a candidate wave.

    The returned indices are local to ``entries``.  A caller can therefore
    remove rejected poses before building any Blender request while retaining
    the original output order and labels.
    """
    asset = globals().get("geometric_proxy_asset")
    evaluate = globals().get("evaluate_geometric_proxy_batch")
    enabled = bool(globals().get("PROXY_ENABLED", False)) if enabled_override is None else bool(enabled_override)
    stage_name = _proxy_stage_name(stage)
    if not enabled or asset is None or evaluate is None or not entries:
        return list(range(len(entries))), {}, {
            "enabled": False,
            "total": len(entries),
            "survivors": len(entries),
            "rejected": 0,
        }
    protected_stages = {
        str(value).strip()
        for value in (globals().get("PROXY_PROTECTED_STAGES", ()) or ())
        if str(value).strip()
    }
    if stage_name in protected_stages:
        return list(range(len(entries))), {}, _proxy_bypass_diagnostics(
            len(entries), "protected_exploration_stage", stage=stage_name
        )
    if stage_name in _PROXY_AUDIT_DISABLED_STAGES:
        return list(range(len(entries))), {}, _proxy_bypass_diagnostics(
            len(entries), "audit_invalid_stage_disabled", stage=stage_name
        )
    economic_minimum = int(globals().get("PROXY_MIN_CANDIDATES", 8))
    if len(entries) <= economic_minimum:
        _PERFORMANCE_STATS["proxyBypassWaves"] += 1
        return list(range(len(entries))), {}, _proxy_bypass_diagnostics(
            len(entries), "candidate_count_at_or_below_economic_minimum", stage=stage_name
        )
    poses = [pose for pose, _label, _live in entries]
    camera = globals().get("geometric_proxy_camera")
    width = int(globals().get("geometric_proxy_width"))
    height = int(globals().get("geometric_proxy_height"))
    root_context = globals().get("geometric_proxy_root_context")
    world_scale = float(globals().get("SEARCH_SCALE", 1.0))
    device = str(globals().get("PROXY_DEVICE", "auto"))
    point_radius = int(globals().get("PROXY_POINT_RADIUS", 1))
    metadata = {}
    survivors = list(range(len(entries)))
    timings = {}
    rejected_by_level = {"level0": 0, "level1": 0}
    skipped_levels = {}
    prepared = None
    total_points = sum(len(primitive.positions) for primitive in asset.primitives)
    bone_count = max(1, sum(len(skin.joints) for skin in asset.skins))
    level0_enabled = bool(globals().get("PROXY_LEVEL0_ENABLED", True))
    level1_enabled = bool(globals().get("PROXY_LEVEL1_ENABLED", True))
    level0_keep_count = (
        _proxy_keep_count(
            len(entries),
            globals().get("PROXY_LEVEL0_KEEP_FRACTION", 0.50),
            globals().get("PROXY_LEVEL0_MIN_CANDIDATES", 4),
            globals().get("PROXY_LEVEL0_MAX_CANDIDATES", 0),
        )
        if level0_enabled
        else len(entries)
    )
    level1_input_count = level0_keep_count if level0_enabled else len(entries)
    level1_keep_count = (
        _proxy_keep_count(
            level1_input_count,
            globals().get("PROXY_LEVEL1_KEEP_FRACTION", 0.50),
            globals().get("PROXY_LEVEL1_MIN_CANDIDATES", 4),
            globals().get("PROXY_LEVEL1_MAX_CANDIDATES", 0),
        )
        if level1_enabled
        else level1_input_count
    )
    if (
        (not level0_enabled or level0_keep_count >= len(entries))
        and (not level1_enabled or level1_keep_count >= level1_input_count)
    ):
        _PERFORMANCE_STATS["proxyBypassWaves"] += 1
        return list(range(len(entries))), {}, {
            **_proxy_bypass_diagnostics(len(entries), "no_level_can_eliminate", stage=stage_name),
            "levelPlan": {
                "level0Input": len(entries),
                "level0KeepCount": level0_keep_count,
                "level1Input": level1_input_count,
                "level1KeepCount": level1_keep_count,
            },
        }
    target_alpha = _proxy_target_alpha(frame_index)

    def run_level(level, candidates, max_points, fraction, minimum, maximum):
        nonlocal prepared
        if not candidates:
            return []
        keep_count = _proxy_keep_count(len(candidates), fraction, minimum, maximum)
        if keep_count >= len(candidates):
            skipped_levels[f"level{level}"] = {
                "reason": "keep_count_equals_input",
                "input": len(candidates),
                "keepCount": keep_count,
            }
            _PERFORMANCE_STATS[f"proxyLevel{level}Skipped"] += 1
            return list(candidates)
        started = time.perf_counter()
        result_kwargs = {
            "width": width,
            "height": height,
            "level": level,
            "point_radius": point_radius,
            "max_points": max_points,
            "world_scale": world_scale,
            "device": device,
            "root_context": root_context,
            "target_alpha": target_alpha,
            "gpu_asset_cache_max_entries": int(
                globals().get("PROXY_GPU_ASSET_CACHE_MAX_ENTRIES", 2)
            ),
            "gpu_asset_cache_enabled": bool(
                globals().get("PROXY_GPU_TENSOR_CACHE_ENABLED", True)
            ),
        }
        if prepared is not None:
            result_kwargs.update({"prepared": prepared, "pose_indices": candidates})
        elif bool(globals().get("PROXY_GPU_TENSOR_CACHE_ENABLED", True)):
            from roc_geometric_proxy import prepare_batch as prepare_geometric_proxy_batch

            prepared = prepare_geometric_proxy_batch(
                asset,
                poses,
                device=device,
                world_scale=world_scale,
                root_context=root_context,
                gpu_asset_cache_max_entries=int(
                    globals().get("PROXY_GPU_ASSET_CACHE_MAX_ENTRIES", 2)
                ),
                gpu_asset_cache_enabled=bool(
                    globals().get("PROXY_GPU_TENSOR_CACHE_ENABLED", True)
                ),
            )
            result_kwargs.update({"prepared": prepared, "pose_indices": candidates})
        result = evaluate(asset, [poses[index] for index in candidates], camera, **result_kwargs)
        elapsed = time.perf_counter() - started
        timings[f"level{level}"] = elapsed
        scores = result.get("scores") or []
        ranked = sorted(
            range(len(candidates)),
            key=lambda local: _proxy_rank_score(scores[local]),
            reverse=True,
        )
        keep_count = _proxy_keep_count(len(candidates), fraction, minimum, maximum)
        kept_local = set(ranked[:keep_count])
        for local, candidate_index in enumerate(candidates):
            score = dict(scores[local] or {})
            metadata.setdefault(candidate_index, {})[f"level{level}"] = score
            metadata[candidate_index][f"level{level}Score"] = _proxy_rank_score(score)
        rejected_by_level[f"level{level}"] = len(candidates) - len(kept_local)
        return [candidates[local] for local in ranked if local in kept_local]

    if level0_enabled:
        survivors = run_level(
            0,
            survivors,
            min(total_points, int(globals().get("PROXY_LEVEL0_POINTS_PER_BONE", 48)) * bone_count),
            globals().get("PROXY_LEVEL0_KEEP_FRACTION", 0.50),
            globals().get("PROXY_LEVEL0_MIN_CANDIDATES", 4),
            globals().get("PROXY_LEVEL0_MAX_CANDIDATES", 0),
        )
    if level1_enabled:
        survivors = run_level(
            1,
            survivors,
            min(total_points, int(globals().get("PROXY_LEVEL1_MAX_VERTICES", 6000))),
            globals().get("PROXY_LEVEL1_KEEP_FRACTION", 0.50),
            globals().get("PROXY_LEVEL1_MIN_CANDIDATES", 4),
            globals().get("PROXY_LEVEL1_MAX_CANDIDATES", 0),
        )
    survivor_set = set(survivors)
    for candidate_index in range(len(entries)):
        metadata.setdefault(candidate_index, {})["proxySurvived"] = candidate_index in survivor_set
    total_elapsed = sum(timings.values())
    if "result" in locals():
        _PERFORMANCE_STATS["proxyBackend"] = result.get("backend")
    _PERFORMANCE_STATS["proxyCandidates"] += len(entries)
    _PERFORMANCE_STATS["proxyLevel0Seconds"] += float(timings.get("level0", 0.0))
    _PERFORMANCE_STATS["proxyLevel1Seconds"] += float(timings.get("level1", 0.0))
    _PERFORMANCE_STATS["proxyRejected"] += len(entries) - len(survivors)
    _PERFORMANCE_STATS["proxyLevel0Rejected"] += rejected_by_level["level0"]
    _PERFORMANCE_STATS["proxyLevel1Rejected"] += rejected_by_level["level1"]
    diagnostics = {
        "enabled": True,
        "stage": stage_name,
        "backend": (result or {}).get("backend") if "result" in locals() else None,
        "total": len(entries),
        "survivors": len(survivors),
        "rejected": len(entries) - len(survivors),
        "level0Rejected": rejected_by_level["level0"],
        "level1Rejected": rejected_by_level["level1"],
        "timings": timings,
        "elapsed": total_elapsed,
        "resolution": (width, height),
        "levelSkipped": skipped_levels,
        "gpuTensorCache": bool(prepared is not None),
        "rasterizer": (result or {}).get("rasterizer") if "result" in locals() else None,
    }
    return survivors, metadata, diagnostics


def hybrid_score_details(
    semantic_cosine,
    geometry_score,
    text_cosine=None,
    negative_text_cosine=None,
    dense_distance=None,
    worker_result=None,
):
    """Return the normalized score and an active-component ledger.

    The optimizer does not select a special semantic-only objective anymore.
    It builds this ledger for every candidate and renormalizes over the terms
    that are actually enabled. The geometry term is the complete worker score,
    so worker-side weighting methods remain part of convergence.
    """
    components = []
    if SEMANTIC_ENABLED and HYBRID_SEMANTIC_WEIGHT > 0.0:
        if semantic_cosine is None:
            raise ValueError("semantic cosine is required when semantic scoring is enabled")
        components.append({
            "name": "semantic_image",
            "weight": float(HYBRID_SEMANTIC_WEIGHT),
            "score": _cosine_to_quality(semantic_cosine),
            "raw": float(semantic_cosine),
        })
    if SEMANTIC_ENABLED and SEMANTIC_DENSE_ENABLED and SEMANTIC_DENSE_WEIGHT > 0.0:
        if dense_distance is None:
            raise ValueError(
                "dense semantic distance is required when SEMANTIC_DENSE_WEIGHT is enabled"
            )
        dense_quality = float(np.clip(1.0 - float(dense_distance), 0.0, 1.0))
        components.append({
            "name": "semantic_dense",
            "weight": float(SEMANTIC_DENSE_WEIGHT),
            "score": dense_quality,
            "raw": float(dense_distance),
        })
    if HYBRID_GEOMETRY_ENABLED and HYBRID_GEOMETRY_WEIGHT > 0.0:
        components.append({
            "name": "worker_geometry",
            "weight": float(HYBRID_GEOMETRY_WEIGHT),
            "score": float(np.clip(geometry_score, 0.0, 1.0)),
            "raw": float(geometry_score),
            "features": _worker_feature_summary(worker_result),
        })
    if (
        ANATOMICAL_BOXES_ENABLED
        and HYBRID_ANATOMICAL_WEIGHT > 0.0
        and worker_result is not None
        and int(worker_result.get("anatomicalTargetCount", 0)) > 0
    ):
        if worker_result.get("anatomicalPartIoU") is None:
            raise ValueError(
                "anatomicalPartIoU is required when HYBRID_ANATOMICAL_WEIGHT is enabled"
            )
        components.append({
            "name": "anatomical_parts",
            "weight": float(HYBRID_ANATOMICAL_WEIGHT),
            "score": float(np.clip(worker_result["anatomicalPartIoU"], 0.0, 1.0)),
            "raw": float(worker_result["anatomicalPartIoU"]),
        })
    if SEMANTIC_ENABLED and SEMANTIC_TEXT_ENABLED and HYBRID_TEXT_WEIGHT > 0.0:
        if text_cosine is None:
            raise ValueError("text cosine is required when SEMANTIC_TEXT_ENABLED=True")
        components.append({
            "name": "positive_text",
            "weight": float(HYBRID_TEXT_WEIGHT),
            "score": _cosine_to_quality(text_cosine),
            "raw": float(text_cosine),
        })
    if SEMANTIC_ENABLED and SEMANTIC_NEGATIVE_TEXT_ENABLED and HYBRID_NEGATIVE_TEXT_WEIGHT > 0.0:
        if negative_text_cosine is None:
            raise ValueError(
                "negative text cosine is required when SEMANTIC_NEGATIVE_TEXT_ENABLED=True"
            )
        negative_quality = _cosine_to_quality(negative_text_cosine)
        components.append({
            "name": "negative_text_avoidance",
            "weight": float(HYBRID_NEGATIVE_TEXT_WEIGHT),
            "score": float(1.0 - negative_quality),
            "raw": float(negative_text_cosine),
        })
    weight_sum = float(sum(item["weight"] for item in components))
    if weight_sum <= 0.0:
        raise ValueError(
            "no hybrid scoring components are active; enable semantic scoring, "
            "worker geometry, or a positive text weight"
        )
    score = float(sum(item["weight"] * item["score"] for item in components) / weight_sum)
    return score, {
        "components": components,
        "activeMethods": [item["name"] for item in components],
        "activeWeightSum": weight_sum,
        "workerFeatures": _worker_feature_summary(worker_result),
    }


def hybrid_score_upper_bound(
    worker_result,
    *,
    dense_distance=None,
):
    """Return the exact best possible hybrid score after worker geometry.

    Every semantic/text quality term is normalized to ``[0, 1]`` by the
    ledger.  Geometry and anatomy are already known after the Blender worker
    returns, so replacing the unknown terms with one gives a mathematically
    safe branch-and-bound value.  This is deliberately a bound, not a
    heuristic silhouette cutoff.
    """
    result = worker_result or {}
    known = 0.0
    unknown = 0.0
    total = 0.0

    def add(weight, score=None):
        nonlocal known, unknown, total
        weight = float(weight)
        if weight <= 0.0:
            return
        total += weight
        if score is None:
            unknown += weight
        else:
            known += weight * float(np.clip(score, 0.0, 1.0))

    if SEMANTIC_ENABLED and HYBRID_SEMANTIC_WEIGHT > 0.0:
        add(HYBRID_SEMANTIC_WEIGHT)
    if SEMANTIC_ENABLED and SEMANTIC_DENSE_ENABLED and SEMANTIC_DENSE_WEIGHT > 0.0:
        if dense_distance is None:
            add(SEMANTIC_DENSE_WEIGHT)
        else:
            add(
                SEMANTIC_DENSE_WEIGHT,
                1.0 - float(np.clip(float(dense_distance), 0.0, 1.0)),
            )
    if HYBRID_GEOMETRY_ENABLED and HYBRID_GEOMETRY_WEIGHT > 0.0:
        add(HYBRID_GEOMETRY_WEIGHT, result.get("iou", result.get("workerIoU", 0.0)))
    if (
        ANATOMICAL_BOXES_ENABLED
        and HYBRID_ANATOMICAL_WEIGHT > 0.0
        and int(result.get("anatomicalTargetCount", 0)) > 0
    ):
        add(HYBRID_ANATOMICAL_WEIGHT, result.get("anatomicalPartIoU", 0.0))
    if SEMANTIC_ENABLED and SEMANTIC_TEXT_ENABLED and HYBRID_TEXT_WEIGHT > 0.0:
        add(HYBRID_TEXT_WEIGHT)
    if (
        SEMANTIC_ENABLED
        and SEMANTIC_NEGATIVE_TEXT_ENABLED
        and HYBRID_NEGATIVE_TEXT_WEIGHT > 0.0
    ):
        add(HYBRID_NEGATIVE_TEXT_WEIGHT)
    return float((known + unknown) / max(total, 1e-8))


def _semantic_bound_threshold(incumbent_score, required_image_scores, index):
    if required_image_scores is not None:
        if isinstance(required_image_scores, Mapping):
            value = required_image_scores.get(index)
        else:
            values = list(required_image_scores)
            value = values[index] if 0 <= int(index) < len(values) else None
        if value is not None:
            return float(value)
    return incumbent_score


def _semantic_bound_reject(
    result,
    incumbent_score,
    *,
    dense_distance=None,
):
    if not (
        SEMANTIC_ONLY
        and SEMANTIC_BRANCH_BOUND_ENABLED
        and incumbent_score is not None
    ):
        return False
    # Anatomy is detected after the worker response in the parent process.
    # Do not claim a bound until that optional component is known; otherwise
    # the normalized denominator could be underestimated.
    if (
        ANATOMICAL_BOXES_ENABLED
        and HYBRID_ANATOMICAL_WEIGHT > 0.0
        and "anatomicalTargetCount" not in result
    ):
        return False
    upper = hybrid_score_upper_bound(result, dense_distance=dense_distance)
    result["semanticUpperBound"] = upper
    result["semanticBoundIncumbent"] = float(incumbent_score)
    rejected = upper <= float(incumbent_score) + SEMANTIC_BRANCH_BOUND_MARGIN
    result["semanticBranchBoundRejected"] = bool(rejected)
    if rejected:
        _PERFORMANCE_STATS["semanticBranchBoundPrunes"] += 1
        result["workerIoU"] = result.get("workerIoU", result.get("iou"))
        result["iou"] = -1.0
        result["hybridScore"] = -1.0
    return bool(rejected)


def hybrid_score(
    semantic_cosine,
    depth_iou,
    text_cosine=None,
    negative_text_cosine=None,
    dense_distance=None,
    worker_result=None,
):
    """Backward-compatible scalar wrapper around :func:`hybrid_score_details`."""
    return hybrid_score_details(
        semantic_cosine,
        depth_iou,
        text_cosine,
        negative_text_cosine,
        dense_distance=dense_distance,
        worker_result=worker_result,
    )[0]


def apply_hybrid_score(
    result,
    semantic_cosine,
    text_cosine=None,
    negative_text_cosine=None,
    semantic_layer_scores=None,
    dense_distance=None,
    dense_layer_distances=None,
):
    """Preserve the worker score, then replace only the public optimizer score."""
    worker_score = float(result.get("iou", result.get("workerIoU", 0.0)))
    result["workerIoU"] = worker_score
    result["geometryScore"] = worker_score
    result["depthIoU"] = worker_score  # legacy report field; geometry is broader than depth
    result["semanticCosine"] = semantic_cosine
    result["semanticLayerCosines"] = semantic_layer_scores
    result["textCosine"] = text_cosine
    result["negativeTextCosine"] = negative_text_cosine
    result["denseSemanticDistance"] = dense_distance
    result["denseSemanticLayerDistances"] = dense_layer_distances
    result["negativeTextAvoidance"] = (
        None if negative_text_cosine is None else 1.0 - _cosine_to_quality(negative_text_cosine)
    )
    score, details = hybrid_score_details(
        semantic_cosine,
        worker_score,
        text_cosine,
        negative_text_cosine,
        dense_distance=dense_distance,
        worker_result=result,
    )
    result["hybridComponents"] = details
    result["hybridScore"] = score
    result["iou"] = score
    return score


def apply_nonsemantic_hybrid_score(result):
    """Apply independent worker-side hybrid terms when image semantics are off."""
    worker_score = float(result.get("iou", result.get("workerIoU", 0.0)))
    result["workerIoU"] = worker_score
    if not (ANATOMICAL_BOXES_ENABLED and HYBRID_ANATOMICAL_WEIGHT > 0.0):
        return worker_score
    score, details = hybrid_score_details(
        None,
        worker_score,
        worker_result=result,
    )
    result["hybridComponents"] = details
    result["hybridScore"] = score
    result["iou"] = score
    return score


def _frame_ik_targets(frame_index):
    """Return a detached flat bone->target map for one frame."""
    if not isinstance(IK_TARGETS, dict):
        return {}
    # Automatic keypoint files are frame-indexed; explicit notebook targets
    # are commonly a flat bone->target map. Keep those two shapes distinct so
    # searching frame 0 does not turn a reusable flat map into a bad frame map.
    nested = any(
        isinstance(key, int) or (isinstance(key, str) and key.isdigit())
        for key in IK_TARGETS
    )
    if not nested:
        return copy.deepcopy(IK_TARGETS)
    value = IK_TARGETS.get(frame_index, IK_TARGETS.get(str(frame_index)))
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _set_frame_ik_targets(frame_index, targets):
    """Persist the selected targets so callers can inspect/reuse the result."""
    if not isinstance(IK_TARGETS, dict):
        return
    nested = any(
        isinstance(key, int) or (isinstance(key, str) and key.isdigit())
        for key in IK_TARGETS
    )
    if not nested:
        IK_TARGETS.clear()
        IK_TARGETS.update(copy.deepcopy(targets))
    elif frame_index in IK_TARGETS or str(frame_index) in IK_TARGETS:
        key = frame_index if frame_index in IK_TARGETS else str(frame_index)
        IK_TARGETS[key] = copy.deepcopy(targets)
    else:
        IK_TARGETS[frame_index] = copy.deepcopy(targets)


def configure_score_request(
    req,
    frame_index,
    ik_targets_override=None,
    ik_bones_override=None,
):
    """Apply score/pose toggles consistently to every worker evaluation."""
    depth_override = globals().get("RENDER_DEPTH_FOR_SCORING")
    if depth_override is None:
        geometry_weight = float(HYBRID_GEOMETRY_WEIGHT or 0.0)
        depth_required = bool(
            (HYBRID_GEOMETRY_ENABLED and geometry_weight > 0.0)
            or REVERSE_PROFILE_ENABLED
            or (
                (ANATOMICAL_BOXES_ENABLED or SHOW_ANATOMICAL_BOXES)
                and ANATOMICAL_LATERALITY_ENABLED
                and ANATOMICAL_LATERALITY_SOURCE == "depth"
            )
        )
    else:
        depth_required = bool(depth_override)
    # This is deliberately sent on every request so pooled Blender workers do
    # not infer a stale render plan from their initialization command.
    req["renderDepth"] = depth_required
    req["triageEnabled"] = bool(TRIAGE_ENABLED)
    req["triageSilhouetteEnabled"] = bool(TRIAGE_SILHOUETTE_ENABLED)
    req["triageSilhouetteHeuristicEnabled"] = bool(
        TRIAGE_SILHOUETTE_HEURISTIC_ENABLED
    )
    req["triageSilhouetteFloor"] = float(TRIAGE_SILHOUETTE_FLOOR)
    req["predOnlyPenalty"] = BLUE_ZONE_PENALTY
    req["targetOnlyPenalty"] = RED_ZONE_PENALTY
    req["targetEdgeBonus"] = SILHOUETTE_EDGE_BONUS
    req["silhouetteDepthWeight"] = SILHOUETTE_DEPTH_WEIGHT
    req["reverseProfileEnabled"] = REVERSE_PROFILE_ENABLED
    req["reverseProfileWeight"] = REVERSE_PROFILE_WEIGHT
    req["profileHalfBias"] = PROFILE_HALF_BIAS
    req["targetPartBoxes"] = (
        PART_BOXES_BY_FRAME.get(frame_index, [])
        if ANATOMICAL_BOXES_ENABLED or SHOW_ANATOMICAL_BOXES
        else []
    )
    req["anatomicalBoxesEnabled"] = ANATOMICAL_BOXES_ENABLED
    req["anatomicalPartWeight"] = ANATOMICAL_PART_WEIGHT if ANATOMICAL_BOXES_ENABLED else 0.0
    req["showAnatomicalBoxes"] = SHOW_ANATOMICAL_BOXES
    if ANATOMICAL_BOXES_ENABLED or SHOW_ANATOMICAL_BOXES:
        req["anatomicalCandidateOut"] = str(ANATOMICAL_CANDIDATE_OUT)
        if ANATOMICAL_LATERALITY_ENABLED and ANATOMICAL_LATERALITY_SOURCE == "depth":
            req["anatomicalCandidateDepthOut"] = str(ANATOMICAL_CANDIDATE_DEPTH_OUT)
    req["ikEnabled"] = IK_ENABLED
    req["ikMode"] = IK_MODE
    req["ikBones"] = list(IK_BONES if ik_bones_override is None else ik_bones_override)
    if ik_targets_override is not None:
        req["ikTargets"] = copy.deepcopy(ik_targets_override)
    elif isinstance(IK_TARGETS, dict):
        req["ikTargets"] = _frame_ik_targets(frame_index)
    else:
        req["ikTargets"] = {}
    req["ikChainLength"] = IK_CHAIN_LENGTH
    req["ikIterations"] = IK_ITERATIONS
    req["ikStrength"] = IK_STRENGTH
    req["ikDepth"] = IK_DEPTH
    req["stripBoneRoll"] = (
        False
        if BONE_TWIST_POLICY == "include"
        else True
        if BONE_TWIST_POLICY == "exclude"
        else bool(EXCLUDE_BONE_ROLL)
    )
    req["stripBoneRollByBone"] = dict(BONE_TWIST_OVERRIDES)
    if REVERSE_PROFILE_ENABLED:
        reverse_target = REVERSE_TARGET_FRAMES / f"{frame_index:02d}.png"
        reverse_depth = REVERSE_TARGET_DEPTH / f"{frame_index:02d}.png"
        if not reverse_target.is_file() or not reverse_depth.is_file():
            raise FileNotFoundError(
                f"reverse profile inputs missing for frame {frame_index}: "
                f"{reverse_target}, {reverse_depth}"
            )
        req["reverseProfileTarget"] = str(reverse_target)
        req["reverseProfileDepth"] = str(reverse_depth)
    return req


def _target_anatomical_features(frame_index, width, height):
    features = []
    for item in PART_BOXES_BY_FRAME.get(frame_index, []):
        box = item.get("box")
        if not box or len(box) != 4:
            continue
        features.append(
            PartBox(
                str(item.get("part", "")),
                (
                    float(box[0]) * float(width),
                    float(box[1]) * float(height),
                    float(box[2]) * float(width),
                    float(box[3]) * float(height),
                ),
                float(item.get("score", 1.0)),
                str(item.get("side")) if item.get("side") in {"L", "R"} else None,
            )
        )
    return [item for item in features if item.part]


def apply_anatomical_candidate_features(result, frame_index, request):
    """Detect the candidate's selected sprite features in its actual RGB render."""
    if not (ANATOMICAL_BOXES_ENABLED or SHOW_ANATOMICAL_BOXES):
        return result
    candidate_path = Path(request.get("anatomicalCandidateOut", ANATOMICAL_CANDIDATE_OUT))
    if not candidate_path.is_file() or candidate_path.stat().st_size <= 0:
        raise RuntimeError(f"anatomical candidate render was not written: {candidate_path}")
    with Image.open(candidate_path) as candidate_image:
        candidate_image = candidate_image.convert("RGBA")
        candidate_depth = None
        depth_path = request.get("anatomicalCandidateDepthOut")
        if ANATOMICAL_LATERALITY_ENABLED and ANATOMICAL_LATERALITY_SOURCE == "depth":
            if not depth_path or not Path(depth_path).is_file():
                raise RuntimeError(
                    f"anatomical candidate depth was not written: {depth_path}"
                )
            with Image.open(depth_path) as depth_image:
                candidate_depth = depth_image.copy()
        target_features = _target_anatomical_features(
            frame_index,
            candidate_image.width,
            candidate_image.height,
        )
        allowed_parts = list(dict.fromkeys(item.part for item in target_features))
        candidate_features = detector.detect(
            candidate_image,
            allowed_parts=allowed_parts,
            laterality_enabled=ANATOMICAL_LATERALITY_ENABLED,
            laterality_depth=candidate_depth,
            laterality_near_side=ANATOMICAL_LATERALITY_NEAR_SIDE,
            laterality_depth_margin=ANATOMICAL_LATERALITY_DEPTH_MARGIN,
            laterality_center_margin_frac=ANATOMICAL_LATERALITY_CENTER_MARGIN_FRAC,
        )
        alignment = anatomical_feature_alignment(
            target_features,
            candidate_features,
            width=candidate_image.width,
            height=candidate_image.height,
            center_weight=ANATOMICAL_CENTER_WEIGHT,
            extent_weight=ANATOMICAL_EXTENT_WEIGHT,
        )
        result["anatomicalBoxesEnabled"] = ANATOMICAL_BOXES_ENABLED
        result["anatomicalPartIoU"] = alignment["score"]
        result["anatomicalFeatureDistance"] = alignment["distance"]
        result["anatomicalParts"] = alignment["parts"]
        result["anatomicalTargetCount"] = alignment["targetCount"]
        result["anatomicalCandidateCount"] = alignment["candidateCount"]
        worker_score = float(result.get("iou", result.get("workerIoU", 0.0)))
        if ANATOMICAL_BOXES_ENABLED and alignment["used"]:
            result["iou"] = float(
                (1.0 - ANATOMICAL_PART_WEIGHT) * worker_score
                + ANATOMICAL_PART_WEIGHT * alignment["score"]
            )
        if SHOW_ANATOMICAL_BOXES:
            target_path = ANIMATION_TARGET_FRAMES / f"{frame_index:02d}.png"
            with Image.open(target_path) as target_image:
                target_image = target_image.convert("RGBA")
                target_features_full = _target_anatomical_features(
                    frame_index,
                    target_image.width,
                    target_image.height,
                )
                draw_feature_dot_preview(
                    target_image,
                    candidate_image,
                    target_features_full,
                    candidate_features,
                    ANATOMICAL_PREVIEW_OUT,
                    title=f"frame {frame_index:02d} anatomical features",
                )
    return result

# Semantic encoder toggle. When true, semantic image/text terms are added to
# the active worker geometry objective rather than replacing it.
SEMANTIC_ONLY = bool(globals().get("SEMANTIC_ONLY", True))
SEMANTIC_MODEL_ID = str(globals().get("SEMANTIC_MODEL_ID", "google/siglip2-base-patch16-512"))
SEMANTIC_EMBEDDING_LAYER = str(globals().get("SEMANTIC_EMBEDDING_LAYER", "projected"))
_configured_embedding_layers = globals().get("SEMANTIC_EMBEDDING_LAYERS", None)
if _configured_embedding_layers is None:
    SEMANTIC_EMBEDDING_LAYERS = (SEMANTIC_EMBEDDING_LAYER,)
elif isinstance(_configured_embedding_layers, str):
    SEMANTIC_EMBEDDING_LAYERS = tuple(
        part.strip() for part in _configured_embedding_layers.split(",") if part.strip()
    )
else:
    SEMANTIC_EMBEDDING_LAYERS = tuple(str(layer).strip() for layer in _configured_embedding_layers if str(layer).strip())
if not SEMANTIC_EMBEDDING_LAYERS:
    raise ValueError("SEMANTIC_EMBEDDING_LAYERS must contain at least one layer")
SEMANTIC_POOLING = str(globals().get("SEMANTIC_POOLING", "model"))
SEMANTIC_SUBJECT_CROP = bool(globals().get("SEMANTIC_SUBJECT_CROP", False))
SEMANTIC_SUBJECT_PADDING_FRAC = float(globals().get("SEMANTIC_SUBJECT_PADDING_FRAC", 0.18))
SEMANTIC_DENSE_ENABLED = bool(globals().get("SEMANTIC_DENSE_ENABLED", False))
SEMANTIC_DENSE_MODEL_ID = globals().get("SEMANTIC_DENSE_MODEL_ID") or SEMANTIC_MODEL_ID
SEMANTIC_DENSE_EMBEDDING_LAYERS = globals().get(
    "SEMANTIC_DENSE_EMBEDDING_LAYERS", ("last",)
)
if isinstance(SEMANTIC_DENSE_EMBEDDING_LAYERS, str):
    SEMANTIC_DENSE_EMBEDDING_LAYERS = tuple(
        part.strip() for part in SEMANTIC_DENSE_EMBEDDING_LAYERS.split(",") if part.strip()
    )
else:
    SEMANTIC_DENSE_EMBEDDING_LAYERS = tuple(
        str(layer).strip()
        for layer in SEMANTIC_DENSE_EMBEDDING_LAYERS
        if str(layer).strip()
    )
SEMANTIC_DENSE_WEIGHT = float(globals().get("SEMANTIC_DENSE_WEIGHT", 0.0))
SEMANTIC_DENSE_LOCAL_RADIUS = int(globals().get("SEMANTIC_DENSE_LOCAL_RADIUS", 1))
SEMANTIC_DENSE_POSITION_WEIGHT = float(
    globals().get("SEMANTIC_DENSE_POSITION_WEIGHT", 0.15)
)
SEMANTIC_DENSE_VIEW_INDEX = int(globals().get("SEMANTIC_DENSE_VIEW_INDEX", 0))
if SEMANTIC_DENSE_ENABLED and not SEMANTIC_ENABLED:
    raise ValueError("SEMANTIC_DENSE_ENABLED requires SEMANTIC_ENABLED=True")
if not SEMANTIC_DENSE_EMBEDDING_LAYERS:
    raise ValueError("SEMANTIC_DENSE_EMBEDDING_LAYERS must contain at least one layer")
if SEMANTIC_DENSE_LOCAL_RADIUS < 0:
    raise ValueError("SEMANTIC_DENSE_LOCAL_RADIUS must be non-negative")
if not math.isfinite(SEMANTIC_DENSE_POSITION_WEIGHT) or SEMANTIC_DENSE_POSITION_WEIGHT < 0.0:
    raise ValueError("SEMANTIC_DENSE_POSITION_WEIGHT must be finite and non-negative")
if SEMANTIC_DENSE_VIEW_INDEX < 0:
    raise ValueError("SEMANTIC_DENSE_VIEW_INDEX must be non-negative")
SEMANTIC_MULTIVIEW = bool(globals().get("SEMANTIC_MULTIVIEW", True))
SEMANTIC_BATCH_SIZE = int(globals().get("SEMANTIC_BATCH_SIZE", 1))
if SEMANTIC_BATCH_SIZE < 1:
    raise ValueError("SEMANTIC_BATCH_SIZE must be positive")
SEMANTIC_GLOBAL_BATCH_SIZE = int(
    globals().get("SEMANTIC_GLOBAL_BATCH_SIZE", SEMANTIC_BATCH_SIZE)
)
SEMANTIC_DENSE_BATCH_SIZE = int(
    globals().get("SEMANTIC_DENSE_BATCH_SIZE", SEMANTIC_BATCH_SIZE)
)
if SEMANTIC_GLOBAL_BATCH_SIZE < 1 or SEMANTIC_DENSE_BATCH_SIZE < 1:
    raise ValueError("semantic encoder batch sizes must be positive")
SEMANTIC_VIEW_ANGLES_DEG = tuple(globals().get("SEMANTIC_VIEW_ANGLES_DEG", (0.0, 180.0, 90.0)))
SEMANTIC_VIEW_ELEVATIONS_DEG = tuple(globals().get("SEMANTIC_VIEW_ELEVATIONS_DEG", (0.0, 0.0, 12.0)))
SEMANTIC_VIEW_WEIGHTS = tuple(globals().get("SEMANTIC_VIEW_WEIGHTS", (1.0, 1.0, 1.0)))
if not (len(SEMANTIC_VIEW_ANGLES_DEG) == len(SEMANTIC_VIEW_ELEVATIONS_DEG) == len(SEMANTIC_VIEW_WEIGHTS) == 3):
    raise ValueError("semantic multiview angles, elevations, and weights must each contain 3 values")
if SEMANTIC_ONLY:
    from roc_semantic_embedding_match import RocSemanticEmbedder, normalize_embedding_layers
    from roc_semantic_services import get_semantic_service
    # Text/image comparison must use the paired projected image space. Keep
    # that auxiliary vector out of the image-layer average when the user has
    # selected only hidden states for the image objective.
    SEMANTIC_EMBEDDING_LAYERS = normalize_embedding_layers(
        SEMANTIC_EMBEDDING_LAYER,
        SEMANTIC_EMBEDDING_LAYERS,
    )
    _semantic_encoder_layers = list(SEMANTIC_EMBEDDING_LAYERS)
    if (SEMANTIC_TEXT_ENABLED or SEMANTIC_NEGATIVE_TEXT_ENABLED) and "projected" not in _semantic_encoder_layers:
        _semantic_encoder_layers.append("projected")
    SEMANTIC_ENCODER_LAYERS = tuple(_semantic_encoder_layers)
    semantic_service = get_semantic_service()
    semantic_service.configure(
        enabled=SEMANTIC_SERVICE_ENABLED,
        encoder_cache_max_entries=SEMANTIC_SERVICE_ENCODER_CACHE_MAX_ENTRIES,
        target_vector_cache_max_entries=SEMANTIC_SERVICE_TARGET_CACHE_MAX_ENTRIES,
        dense_target_cache_max_entries=SEMANTIC_SERVICE_DENSE_TARGET_CACHE_MAX_ENTRIES,
    )
    _global_encoder_key = (
        "siglip-global",
        SEMANTIC_SERVICE_CACHE_GENERATION,
        str(SEMANTIC_MODEL_ID),
        tuple(SEMANTIC_ENCODER_LAYERS),
        str(SEMANTIC_POOLING),
        bool(SEMANTIC_SUBJECT_CROP),
        float(SEMANTIC_SUBJECT_PADDING_FRAC),
        "cuda:0",
    )
    semantic_encoder = semantic_service.get_global_encoder(
        _global_encoder_key,
        lambda: RocSemanticEmbedder(
            model_id=SEMANTIC_MODEL_ID,
            embedding_layer=SEMANTIC_EMBEDDING_LAYER,
            embedding_layers=SEMANTIC_ENCODER_LAYERS,
            pooling=SEMANTIC_POOLING,
            subject_crop=SEMANTIC_SUBJECT_CROP,
            subject_padding_frac=SEMANTIC_SUBJECT_PADDING_FRAC,
        ),
    )  # asserts CUDA
    _semantic_target_vectors = {}
    _semantic_text_vector = None
    _semantic_negative_text_vector = None
    _semantic_candidate_dir = PILOT / 'tmp' / 'semantic_candidates'
    _semantic_candidate_dir.mkdir(parents=True, exist_ok=True)
    dense_semantic_encoder = None
    _semantic_dense_target_grids = {}
    if SEMANTIC_DENSE_ENABLED and SEMANTIC_DENSE_WEIGHT > 0.0:
        from dense_semantic_features import DenseFeatureScorer

        _dense_encoder_key = (
            "dense",
            SEMANTIC_SERVICE_CACHE_GENERATION,
            str(SEMANTIC_DENSE_MODEL_ID),
            tuple(SEMANTIC_DENSE_EMBEDDING_LAYERS),
            "cuda:0",
        )
        dense_semantic_encoder = semantic_service.get_dense_encoder(
            _dense_encoder_key,
            lambda: DenseFeatureScorer(
                model_id=str(SEMANTIC_DENSE_MODEL_ID),
                feature_layers=SEMANTIC_DENSE_EMBEDDING_LAYERS,
            ),
        )

    def _semantic_image(path):
        """Decode and crop one RGB file once for both semantic lanes."""
        path = Path(path)
        stat = path.stat()
        key = (
            str(path.resolve()),
            int(stat.st_size),
            int(stat.st_mtime_ns),
            bool(SEMANTIC_SUBJECT_CROP),
            float(SEMANTIC_SUBJECT_PADDING_FRAC),
        )
        cached = _lru_get(_SEMANTIC_IMAGE_CACHE, key)
        if cached is not None:
            _PERFORMANCE_STATS["semanticImageCacheHits"] += 1
            return cached
        _PERFORMANCE_STATS["semanticImageCacheMisses"] += 1
        image = semantic_encoder.load_image(path)
        if SEMANTIC_SUBJECT_CROP:
            image = semantic_encoder.load_subject_image_from_image(
                image,
                SEMANTIC_SUBJECT_PADDING_FRAC,
            )
        _lru_put(_SEMANTIC_IMAGE_CACHE, key, image, SEMANTIC_IMAGE_CACHE_MAX_ENTRIES)
        return image

    def _semantic_target_cache_key(frame_index, lane):
        """Build a content-addressed key shared by sequential clip runs."""

        target_path = ANIMATION_TARGET_FRAMES / f'{int(frame_index):02d}.png'
        common = (
            _file_digest(target_path),
            bool(SEMANTIC_SUBJECT_CROP),
            float(SEMANTIC_SUBJECT_PADDING_FRAC),
        )
        if lane == "global":
            return (
                lane,
                common,
                SEMANTIC_SERVICE_CACHE_GENERATION,
                str(SEMANTIC_MODEL_ID),
                tuple(SEMANTIC_ENCODER_LAYERS),
                str(SEMANTIC_POOLING),
            )
        if lane == "dense":
            return (
                lane,
                common,
                SEMANTIC_SERVICE_CACHE_GENERATION,
                str(SEMANTIC_DENSE_MODEL_ID),
                tuple(SEMANTIC_DENSE_EMBEDDING_LAYERS),
            )
        raise ValueError(f"unknown semantic target cache lane: {lane!r}")

    def semantic_dense_distance_batch(frame_index, candidate_path_groups):
        """Score many candidate renders after one or more dense GPU batches."""
        if (
            not SEMANTIC_DENSE_ENABLED
            or SEMANTIC_DENSE_WEIGHT <= 0.0
            or dense_semantic_encoder is None
        ):
            return [(None, {}) for _ in candidate_path_groups]
        groups = [list(group) for group in candidate_path_groups]
        if not groups:
            return []
        for group in groups:
            if SEMANTIC_DENSE_VIEW_INDEX >= len(group):
                raise ValueError(
                    f"SEMANTIC_DENSE_VIEW_INDEX={SEMANTIC_DENSE_VIEW_INDEX} is outside "
                    f"the {len(group)} candidate semantic view(s)"
                )
        if frame_index not in _semantic_dense_target_grids:
            target_key = _semantic_target_cache_key(frame_index, "dense")
            cached_target = semantic_service.get_dense_target(target_key)
            if cached_target is None:
                target_image = _semantic_image(
                    ANIMATION_TARGET_FRAMES / f'{frame_index:02d}.png'
                )
                # Keep the freshly extracted GPU value for this experiment;
                # the service stores a CPU copy for subsequent animations.
                target_grids = dense_semantic_encoder.extract_layers([target_image])
                semantic_service.put_dense_target(target_key, target_grids)
            else:
                target_grids = {
                    layer: features.to(
                        dense_semantic_encoder.device,
                        non_blocking=False,
                    )
                    for layer, features in cached_target.items()
                }
            _semantic_dense_target_grids[frame_index] = target_grids
        scored = [None] * len(groups)
        candidate_grid_entries = [None] * len(groups)
        missing = []
        for index, group in enumerate(groups):
            # Cache the candidate feature grid, not the candidate-vs-target
            # distance. A rendered pose can be compared to more than one
            # target frame, while the local-window distance is target-specific.
            grid_key = (
                _file_digest(group[SEMANTIC_DENSE_VIEW_INDEX]),
                str(SEMANTIC_DENSE_MODEL_ID),
                tuple(SEMANTIC_DENSE_EMBEDDING_LAYERS),
                bool(SEMANTIC_SUBJECT_CROP),
                float(SEMANTIC_SUBJECT_PADDING_FRAC),
            )
            cached = _lru_get(_DENSE_GRID_CACHE, grid_key)
            if cached is not None:
                _PERFORMANCE_STATS["denseGridCacheHits"] += 1
                candidate_grid_entries[index] = cached
            else:
                _PERFORMANCE_STATS["denseGridCacheMisses"] += 1
                missing.append((index, group, grid_key))
        for start in range(0, len(missing), SEMANTIC_DENSE_BATCH_SIZE):
            batch_items = missing[start : start + SEMANTIC_DENSE_BATCH_SIZE]
            batch_groups = [item[1] for item in batch_items]
            encode_started = time.perf_counter()
            candidate_images = [
                _semantic_image(group[SEMANTIC_DENSE_VIEW_INDEX])
                for group in batch_groups
            ]
            candidate_grids = dense_semantic_encoder.extract_layers(candidate_images)
            _PERFORMANCE_STATS["semanticDenseSeconds"] += time.perf_counter() - encode_started
            for batch_index, (index, _group, grid_key) in enumerate(batch_items):
                value = {
                    layer: candidate_grids[layer][batch_index : batch_index + 1]
                    .detach()
                    .to("cpu", dtype=dense_semantic_encoder.torch.float32)
                    .contiguous()
                    for layer in dense_semantic_encoder.feature_layers
                }
                _lru_put(
                    _DENSE_GRID_CACHE,
                    grid_key,
                    value,
                    SEMANTIC_DENSE_GRID_CACHE_MAX_ENTRIES,
                )
                candidate_grid_entries[index] = value
        candidate_grids = {
            layer: dense_semantic_encoder.torch.cat(
                [
                    candidate_grid_entries[index][layer].to(
                        dense_semantic_encoder.device,
                        non_blocking=False,
                    )
                    for index in range(len(groups))
                ],
                dim=0,
            )
            for layer in dense_semantic_encoder.feature_layers
        }
        compare_started = time.perf_counter()
        batch_scores = dense_semantic_encoder.score_grid_layers_batch_mean(
            _semantic_dense_target_grids[frame_index],
            candidate_grids,
            window_radius=SEMANTIC_DENSE_LOCAL_RADIUS,
            position_weight=SEMANTIC_DENSE_POSITION_WEIGHT,
        )
        _PERFORMANCE_STATS["semanticDenseCompareSeconds"] += (
            time.perf_counter() - compare_started
        )
        for index, (distance, layer_distances) in enumerate(batch_scores):
            scored[index] = (
                float(distance),
                {str(layer): float(value) for layer, value in layer_distances.items()},
            )
        return [value for value in scored]

    def semantic_dense_distance(frame_index, candidate_paths):
        """Return spatial dense distance and per-layer diagnostics for one candidate."""
        return semantic_dense_distance_batch(frame_index, [candidate_paths])[0]

    def average_semantic_vectors(paths):
        return average_semantic_vectors_batch([paths])[0]

    def average_semantic_vectors_batch(path_groups):
        """Embed several candidate view sets with bounded GPU batches."""
        groups = [list(group) for group in path_groups]
        output = [None] * len(groups)
        missing = []
        for index, group in enumerate(groups):
            if not group:
                raise ValueError("semantic candidate view groups must not be empty")
            group_key = (
                "global",
                tuple(_file_digest(path) for path in group),
                tuple(float(value) for value in SEMANTIC_VIEW_WEIGHTS[: len(group)]),
                str(SEMANTIC_MODEL_ID),
                tuple(SEMANTIC_ENCODER_LAYERS),
                str(SEMANTIC_POOLING),
                bool(SEMANTIC_SUBJECT_CROP),
                float(SEMANTIC_SUBJECT_PADDING_FRAC),
            )
            cached = _lru_get(_SEMANTIC_VECTOR_CACHE, group_key)
            if cached is not None:
                _PERFORMANCE_STATS["semanticEmbeddingCacheHits"] += 1
                output[index] = cached
            else:
                _PERFORMANCE_STATS["semanticEmbeddingCacheMisses"] += 1
                missing.append((index, group, group_key))
        for start in range(0, len(missing), SEMANTIC_GLOBAL_BATCH_SIZE):
            batch_items = missing[start : start + SEMANTIC_GLOBAL_BATCH_SIZE]
            batch_groups = [item[1] for item in batch_items]
            encode_started = time.perf_counter()
            images = [
                _semantic_image(path)
                for group in batch_groups
                for path in group
            ]
            layer_vectors = semantic_encoder.embed_layers(images)
            _PERFORMANCE_STATS["semanticGlobalSeconds"] += time.perf_counter() - encode_started
            offsets = []
            cursor = 0
            for group in batch_groups:
                offsets.append((cursor, cursor + len(group)))
                cursor += len(group)
            for group_index, (lo, hi) in enumerate(offsets):
                count = hi - lo
                if count == 1:
                    view_weights = np.ones(1, dtype=np.float32)
                else:
                    view_weights = np.asarray(SEMANTIC_VIEW_WEIGHTS, dtype=np.float32)
                    if len(view_weights) != count:
                        raise RuntimeError(
                            f"semantic view weight count {len(view_weights)} does not match "
                            f"render count {count}"
                        )
                weight_sum = max(float(view_weights.sum()), 1e-8)
                averaged = {}
                for layer, vectors in layer_vectors.items():
                    subset = vectors[lo:hi]
                    average = (subset * view_weights[:, None]).sum(axis=0) / weight_sum
                    averaged[layer] = average / max(float(np.linalg.norm(average)), 1e-8)
                original_index, _group, group_key = batch_items[group_index]
                _lru_put(
                    _SEMANTIC_VECTOR_CACHE,
                    group_key,
                    averaged,
                    SEMANTIC_CANDIDATE_CACHE_MAX_ENTRIES,
                )
                output[original_index] = averaged
        return output
    def semantic_paths(frame_index, label):
        return [_semantic_candidate_dir / f'f{frame_index:02d}_{label}_view{i}.png' for i in range(3)]
    def semantic_target_vector(frame_index):
        if frame_index not in _semantic_target_vectors:
            target_key = _semantic_target_cache_key(frame_index, "global")
            cached_target = semantic_service.get_target_vector(target_key)
            if cached_target is None:
                image = _semantic_image(
                    ANIMATION_TARGET_FRAMES / f'{frame_index:02d}.png'
                )
                layer_vectors = semantic_encoder.embed_layers([image])
                target_vectors = {
                    layer: vectors[0] for layer, vectors in layer_vectors.items()
                }
                semantic_service.put_target_vector(target_key, target_vectors)
            else:
                target_vectors = dict(cached_target)
            _semantic_target_vectors[frame_index] = target_vectors
        return _semantic_target_vectors[frame_index]

    def semantic_image_score(target_vectors, candidate_vectors):
        """Average image-image cosine scores across the selected layers."""
        layer_scores = {}
        for layer in SEMANTIC_EMBEDDING_LAYERS:
            if layer not in target_vectors or layer not in candidate_vectors:
                raise RuntimeError(f"missing semantic embedding layer {layer!r}")
            target = target_vectors[layer]
            candidate = candidate_vectors[layer]
            if target.shape != candidate.shape:
                raise RuntimeError(
                    f"semantic layer {layer!r} shape mismatch: {target.shape} vs {candidate.shape}"
                )
            layer_scores[layer] = float(np.dot(target, candidate))
        return float(np.mean(list(layer_scores.values()))), layer_scores

    def semantic_text_image_vector(candidate_vectors):
        """Return the projected image vector used by the paired text tower."""
        if "projected" not in candidate_vectors:
            raise ValueError(
                "text semantic scoring requires the projected image embedding"
            )
        return candidate_vectors["projected"]
    if SEMANTIC_TEXT_ENABLED:
        _semantic_text_vector = semantic_encoder.embed_text([SEMANTIC_TEXT_PROMPT])[0]
    if SEMANTIC_NEGATIVE_TEXT_ENABLED:
        _semantic_negative_text_vector = semantic_encoder.embed_text([SEMANTIC_NEGATIVE_TEXT_PROMPT])[0]

    def semantic_text_scores(candidate_vectors):
        """Return positive and negative prompt cosines for one image view set."""
        text_score = None
        negative_text_score = None
        if SEMANTIC_TEXT_ENABLED or SEMANTIC_NEGATIVE_TEXT_ENABLED:
            candidate_vector = semantic_text_image_vector(candidate_vectors)
            if SEMANTIC_TEXT_ENABLED:
                text_score = float(np.dot(_semantic_text_vector, candidate_vector))
            if SEMANTIC_NEGATIVE_TEXT_ENABLED:
                negative_text_score = float(np.dot(_semantic_negative_text_vector, candidate_vector))
        return text_score, negative_text_score

    def score_semantic_candidate(frame_index, candidate_paths, result, incumbent_score=None):
        """Score one RGB candidate with the cheap dense lane before global CLIP.

        Dense features are already the less expensive semantic lane in this
        configuration.  Run them first, apply an exact bound with their known
        contribution, and only then pay for the global/text embedding.  The
        helper is shared by single-candidate and batched search so the staged
        scoring contract cannot drift between optimizer paths.
        """
        dense_distance, dense_layer_distances = semantic_dense_distance(
            frame_index,
            candidate_paths,
        )
        if _semantic_bound_reject(
            result,
            incumbent_score,
            dense_distance=dense_distance,
        ):
            result["semanticBoundStage"] = "after_dense"
            result["workerIoU"] = result.get("workerIoU", result.get("iou"))
            result["iou"] = -1.0
            result["hybridScore"] = -1.0
            result["triageRejected"] = True
            result["triageReason"] = "semantic_branch_bound_after_dense"
            return False
        candidate_vectors = average_semantic_vectors(candidate_paths)
        semantic_score, semantic_layer_scores = semantic_image_score(
            semantic_target_vector(frame_index), candidate_vectors
        )
        text_score, negative_text_score = semantic_text_scores(candidate_vectors)
        apply_hybrid_score(
            result,
            semantic_score,
            text_score,
            negative_text_score,
            semantic_layer_scores,
            dense_distance,
            dense_layer_distances,
        )
        result["semanticBoundStage"] = "after_global"
        return True

# Local bind axes / multi-axis policy from imports cell. The worker removes
# twist by projecting onto each bone's actual rest-space shaft. Do not filter a
# global Euler axis here: imported rigs are not required to align their shafts
# to the same world/local coordinate axis.
EXCLUDE_BONE_ROLL = bool(globals().get("EXCLUDE_BONE_ROLL", True))
ROLL_AXIS = str(globals().get("ROLL_AXIS", "y")).lower()
ROTATION_VECTOR_SEARCH_ENABLED = bool(
    globals().get("ROTATION_VECTOR_SEARCH_ENABLED", False)
)
ROTATION_VECTOR_PROBE_COUNT = int(globals().get("ROTATION_VECTOR_PROBE_COUNT", 8))
ROTATION_VECTOR_PROBE_STEP_DEG = float(
    globals().get("ROTATION_VECTOR_PROBE_STEP_DEG", COARSE_STEP_DEG if "COARSE_STEP_DEG" in globals() else 16.0)
)
GPU_POSE_ADVISOR_ENABLED = bool(globals().get("GPU_POSE_ADVISOR_ENABLED", False))
GPU_POSE_ADVISOR_DIRECTION_ENABLED = bool(
    globals().get("GPU_POSE_ADVISOR_DIRECTION_ENABLED", True)
)
GPU_POSE_ADVISOR_ROOT_ENABLED = bool(
    globals().get("GPU_POSE_ADVISOR_ROOT_ENABLED", True)
)
GPU_POSE_ADVISOR_FALLBACK_ROTATION_VECTORS = bool(
    globals().get("GPU_POSE_ADVISOR_FALLBACK_ROTATION_VECTORS", True)
)
DIRECTIONAL_CONTINUATION_ENABLED = bool(
    globals().get("DIRECTIONAL_CONTINUATION_ENABLED", False)
)
DIRECTIONAL_MAX_STEPS = int(globals().get("DIRECTIONAL_MAX_STEPS", 4))
DIRECTIONAL_STEP_MULTIPLIER = float(
    globals().get("DIRECTIONAL_STEP_MULTIPLIER", 2.0)
)
DIRECTIONAL_TOP_K = int(globals().get("DIRECTIONAL_TOP_K", 2))
DIRECTIONAL_MIN_IMPROVEMENT = float(
    globals().get("DIRECTIONAL_MIN_IMPROVEMENT", 0.0)
)
BONE_TWIST_POLICY = str(globals().get("BONE_TWIST_POLICY", "adaptive")).lower()
BONE_TWIST_OVERRIDES = {
    str(name): str(policy).lower()
    for name, policy in dict(globals().get("BONE_TWIST_OVERRIDES", {}) or {}).items()
}
_default_axes = ("x", "y", "z")
SEARCH_AXES = tuple(
    a for a in globals().get("SEARCH_AXES", _default_axes)
    if str(a).lower() in {"x", "y", "z"}
)
if not SEARCH_AXES:
    SEARCH_AXES = _default_axes
MULTI_AXIS_MODE = str(globals().get("MULTI_AXIS_MODE", "compound"))
AXIS_PROBE_FIRST = bool(globals().get("AXIS_PROBE_FIRST", True))
COARSE_STEP_DEG = float(globals().get("COARSE_STEP_DEG", 16.0))
REFINE_STEP_DEG = float(globals().get("REFINE_STEP_DEG", 4.0))
NEAR_BONE_REFINEMENT_ENABLED = bool(globals().get("NEAR_BONE_REFINEMENT_ENABLED", False))
NEAR_BONE_REFINEMENT_STEP_DEG = float(
    globals().get("NEAR_BONE_REFINEMENT_STEP_DEG", min(1.0, REFINE_STEP_DEG))
)
if REFINE_STEP_DEG <= 0.0 or NEAR_BONE_REFINEMENT_STEP_DEG <= 0.0:
    raise ValueError("refine steps must be positive")
if NEAR_BONE_REFINEMENT_STEP_DEG > REFINE_STEP_DEG:
    raise ValueError("NEAR_BONE_REFINEMENT_STEP_DEG must not exceed REFINE_STEP_DEG")
CASCADE_SECONDARY_FRAC = float(globals().get("CASCADE_SECONDARY_FRAC", 0.45))
COMPOUND_PAIR_STEP_MULT = float(globals().get("COMPOUND_PAIR_STEP_MULT", 1.0))
COMPOUND_CD_ROUNDS = int(globals().get("COMPOUND_CD_ROUNDS", 2))
SKIP_TINY_BONES = bool(globals().get("SKIP_TINY_BONES", True))
MULTI_BONE_MODE = str(globals().get("MULTI_BONE_MODE", "single")).lower()
MULTI_BONE_GROUPING = str(globals().get("MULTI_BONE_GROUPING", "window")).lower()
MULTI_BONE_BLOCK_SIZE = int(globals().get("MULTI_BONE_BLOCK_SIZE", 2))
MULTI_BONE_ROUNDS = int(globals().get("MULTI_BONE_ROUNDS", 1))
MULTI_BONE_STEP_DEG = float(globals().get("MULTI_BONE_STEP_DEG", REFINE_STEP_DEG))
MULTI_BONE_CANDIDATE_PATTERN = str(
    globals().get("MULTI_BONE_CANDIDATE_PATTERN", "star")
).lower()
MULTI_BONE_BEAM_WIDTH = int(globals().get("MULTI_BONE_BEAM_WIDTH", 2))
MULTI_BONE_PROBE_ENABLED = bool(globals().get("MULTI_BONE_PROBE_ENABLED", True))
MULTI_BONE_PROBE_STEP_DEG = float(globals().get("MULTI_BONE_PROBE_STEP_DEG", 30.0))
MULTI_BONE_PROBE_TOP_K = int(globals().get("MULTI_BONE_PROBE_TOP_K", 12))
MULTI_BONE_PROBE_MIN_IMPROVEMENT = float(
    globals().get("MULTI_BONE_PROBE_MIN_IMPROVEMENT", -0.005)
)
MULTI_BONE_ADAPTIVE_BLOCKS_ENABLED = bool(
    globals().get("MULTI_BONE_ADAPTIVE_BLOCKS_ENABLED", True)
)
MULTI_BONE_INTERMEDIATE_STEP_DEG = float(
    globals().get("MULTI_BONE_INTERMEDIATE_STEP_DEG", 10.0)
)
MULTI_BONE_INTERMEDIATE_ROUNDS = int(
    globals().get("MULTI_BONE_INTERMEDIATE_ROUNDS", 1)
)
MULTI_BONE_POLISH_ENABLED = bool(globals().get("MULTI_BONE_POLISH_ENABLED", True))
MULTI_BONE_POLISH_ROUNDS = int(globals().get("MULTI_BONE_POLISH_ROUNDS", 1))
MULTI_BONE_POLISH_STEP_DEG = float(globals().get("MULTI_BONE_POLISH_STEP_DEG", 2.0))
if MULTI_BONE_MODE not in {"single", "block_coordinate", "joint_beam"}:
    raise ValueError("MULTI_BONE_MODE must be single, block_coordinate, or joint_beam")
if MULTI_BONE_GROUPING not in {"window", "branch"}:
    raise ValueError("MULTI_BONE_GROUPING must be window or branch")
if MULTI_BONE_BLOCK_SIZE < 2:
    raise ValueError("MULTI_BONE_BLOCK_SIZE must be at least 2")
if MULTI_BONE_ROUNDS < 1 or MULTI_BONE_STEP_DEG <= 0.0 or MULTI_BONE_BEAM_WIDTH < 1:
    raise ValueError("multi-bone rounds, step, and beam width must be positive")
if MULTI_BONE_CANDIDATE_PATTERN not in {"star", "cube"}:
    raise ValueError("MULTI_BONE_CANDIDATE_PATTERN must be star or cube")
if MULTI_BONE_PROBE_STEP_DEG <= 0.0 or MULTI_BONE_PROBE_TOP_K < 1:
    raise ValueError("multi-bone probe step and top-k must be positive")
if not math.isfinite(MULTI_BONE_PROBE_MIN_IMPROVEMENT):
    raise ValueError("MULTI_BONE_PROBE_MIN_IMPROVEMENT must be finite")
if MULTI_BONE_INTERMEDIATE_STEP_DEG <= 0.0 or MULTI_BONE_POLISH_STEP_DEG <= 0.0:
    raise ValueError("multi-bone intermediate and polish steps must be positive")
if MULTI_BONE_INTERMEDIATE_ROUNDS < 1 or MULTI_BONE_POLISH_ROUNDS < 1:
    raise ValueError("multi-bone intermediate/polish rounds must be at least 1")
if MULTI_BONE_INTERMEDIATE_STEP_DEG > MULTI_BONE_PROBE_STEP_DEG:
    raise ValueError("MULTI_BONE_INTERMEDIATE_STEP_DEG must not exceed probe step")
if MULTI_BONE_POLISH_STEP_DEG > MULTI_BONE_INTERMEDIATE_STEP_DEG:
    raise ValueError("MULTI_BONE_POLISH_STEP_DEG must not exceed intermediate step")
CLIP_OPTIMIZATION_ENABLED = bool(globals().get("CLIP_OPTIMIZATION_ENABLED", False))
CLIP_WARM_START = str(globals().get("CLIP_WARM_START", "previous")).lower()
CLIP_ROUNDS = int(globals().get("CLIP_ROUNDS", 1))
CLIP_REFINE_ROUNDS = int(globals().get("CLIP_REFINE_ROUNDS", 1))
CLIP_VELOCITY_WEIGHT = float(globals().get("CLIP_VELOCITY_WEIGHT", 0.08))
CLIP_ACCELERATION_WEIGHT = float(globals().get("CLIP_ACCELERATION_WEIGHT", 0.04))
CLIP_CONTACT_WEIGHT = float(globals().get("CLIP_CONTACT_WEIGHT", 0.0))
CLIP_LOOP_WEIGHT = float(globals().get("CLIP_LOOP_WEIGHT", 0.0))
CLIP_LOOP_VELOCITY_WEIGHT = float(globals().get("CLIP_LOOP_VELOCITY_WEIGHT", 0.0))
CLIP_LOOP_ENABLED = bool(globals().get("CLIP_LOOP_ENABLED", False))
CLIP_MOTION_ROOT_MAGNITUDE_WEIGHT = float(
    globals().get("CLIP_MOTION_ROOT_MAGNITUDE_WEIGHT", MOTION_ROOT_MAGNITUDE_WEIGHT)
)
CLIP_MOTION_ROOT_VELOCITY_WEIGHT = float(
    globals().get(
        "CLIP_MOTION_ROOT_VELOCITY_WEIGHT",
        globals().get("CLIP_BODY_TRANSLATION_VELOCITY_WEIGHT", MOTION_ROOT_VELOCITY_WEIGHT),
    )
)
CLIP_MOTION_ROOT_ACCELERATION_WEIGHT = float(
    globals().get(
        "CLIP_MOTION_ROOT_ACCELERATION_WEIGHT",
        globals().get("CLIP_BODY_TRANSLATION_ACCELERATION_WEIGHT", MOTION_ROOT_ACCELERATION_WEIGHT),
    )
)
CLIP_MOTION_ROOT_LOOP_WEIGHT = float(
    globals().get("CLIP_MOTION_ROOT_LOOP_WEIGHT", MOTION_ROOT_LOOP_WEIGHT)
)
CLIP_MOTION_ROOT_LOOP_VELOCITY_WEIGHT = float(
    globals().get(
        "CLIP_MOTION_ROOT_LOOP_VELOCITY_WEIGHT",
        MOTION_ROOT_LOOP_VELOCITY_WEIGHT,
    )
)
# Compatibility names retained for printed diagnostics and older callers.
CLIP_BODY_TRANSLATION_VELOCITY_WEIGHT = CLIP_MOTION_ROOT_VELOCITY_WEIGHT
CLIP_BODY_TRANSLATION_ACCELERATION_WEIGHT = CLIP_MOTION_ROOT_ACCELERATION_WEIGHT
CLIP_PROBE_ENABLED = bool(globals().get("CLIP_PROBE_ENABLED", True))
CLIP_PROBE_STEP_DEG = float(globals().get("CLIP_PROBE_STEP_DEG", 30.0))
CLIP_PROBE_TOP_K = int(globals().get("CLIP_PROBE_TOP_K", 12))
CLIP_PROBE_MIN_IMPROVEMENT = float(globals().get("CLIP_PROBE_MIN_IMPROVEMENT", -0.005))
CLIP_ADAPTIVE_BLOCKS_ENABLED = bool(
    globals().get("CLIP_ADAPTIVE_BLOCKS_ENABLED", True)
)
CLIP_ADAPTIVE_BLOCK_SIZE = int(globals().get("CLIP_ADAPTIVE_BLOCK_SIZE", 3))
CLIP_ADAPTIVE_ROUNDS = int(globals().get("CLIP_ADAPTIVE_ROUNDS", 1))
CLIP_ADAPTIVE_STEP_DEG = float(globals().get("CLIP_ADAPTIVE_STEP_DEG", 10.0))
CLIP_ADAPTIVE_BEAM_WIDTH = int(globals().get("CLIP_ADAPTIVE_BEAM_WIDTH", 4))
CLIP_POLISH_ENABLED = bool(globals().get("CLIP_POLISH_ENABLED", True))
CLIP_POLISH_ROUNDS = int(globals().get("CLIP_POLISH_ROUNDS", 1))
CLIP_POLISH_STEP_DEG = float(globals().get("CLIP_POLISH_STEP_DEG", 2.0))
CLIP_CONTACT_BONES = tuple(str(bone) for bone in globals().get("CLIP_CONTACT_BONES", ()))
CLIP_ROBUST_SCALE_DEG = float(globals().get("CLIP_ROBUST_SCALE_DEG", 16.0))
CLIP_COARSE_STEP_DEG = float(globals().get("CLIP_COARSE_STEP_DEG", 16.0))
CLIP_REFINE_STEP_DEG = float(globals().get("CLIP_REFINE_STEP_DEG", 4.0))
CLIP_MAX_EVALUATIONS_PER_AXIS = int(globals().get("CLIP_MAX_EVALUATIONS_PER_AXIS", 24))
CLIP_CANDIDATE_MODE = str(
    globals().get("CLIP_CANDIDATE_MODE", "range_extremes")
).lower()
CLIP_ACCEPTANCE_MARGIN = float(
    globals().get("CLIP_ACCEPTANCE_MARGIN", 0.001)
)
CLIP_ACCEPTANCE_RELATIVE_MARGIN = float(
    globals().get("CLIP_ACCEPTANCE_RELATIVE_MARGIN", 0.0)
)
if CLIP_WARM_START not in {"bind", "previous", "frame0"}:
    raise ValueError("CLIP_WARM_START must be bind, previous, or frame0")
if CLIP_ROUNDS < 1 or CLIP_REFINE_ROUNDS < 1:
    raise ValueError("CLIP_ROUNDS and CLIP_REFINE_ROUNDS must be at least 1")
if CLIP_COARSE_STEP_DEG <= 0.0 or CLIP_REFINE_STEP_DEG <= 0.0:
    raise ValueError("clip proposal steps must be positive")
if CLIP_REFINE_STEP_DEG > CLIP_COARSE_STEP_DEG:
    raise ValueError("CLIP_REFINE_STEP_DEG must not exceed CLIP_COARSE_STEP_DEG")
if CLIP_MAX_EVALUATIONS_PER_AXIS < 1:
    raise ValueError("CLIP_MAX_EVALUATIONS_PER_AXIS must be positive")
if CLIP_CANDIDATE_MODE not in {"local", "range_extremes"}:
    raise ValueError("CLIP_CANDIDATE_MODE must be local or range_extremes")
if not math.isfinite(CLIP_ACCEPTANCE_MARGIN) or CLIP_ACCEPTANCE_MARGIN < 0.0:
    raise ValueError("CLIP_ACCEPTANCE_MARGIN must be finite and non-negative")
if not math.isfinite(CLIP_ACCEPTANCE_RELATIVE_MARGIN) or CLIP_ACCEPTANCE_RELATIVE_MARGIN < 0.0:
    raise ValueError("CLIP_ACCEPTANCE_RELATIVE_MARGIN must be finite and non-negative")
if CLIP_ROBUST_SCALE_DEG <= 0.0:
    raise ValueError("CLIP_ROBUST_SCALE_DEG must be positive")
for _name, _value in (
    ("MOTION_ROOT_MAGNITUDE_WEIGHT", MOTION_ROOT_MAGNITUDE_WEIGHT),
    ("MOTION_ROOT_VELOCITY_WEIGHT", MOTION_ROOT_VELOCITY_WEIGHT),
    ("MOTION_ROOT_ACCELERATION_WEIGHT", MOTION_ROOT_ACCELERATION_WEIGHT),
    ("MOTION_ROOT_LOOP_WEIGHT", MOTION_ROOT_LOOP_WEIGHT),
    ("MOTION_ROOT_LOOP_VELOCITY_WEIGHT", MOTION_ROOT_LOOP_VELOCITY_WEIGHT),
    ("CLIP_MOTION_ROOT_LOOP_WEIGHT", CLIP_MOTION_ROOT_LOOP_WEIGHT),
    ("CLIP_MOTION_ROOT_LOOP_VELOCITY_WEIGHT", CLIP_MOTION_ROOT_LOOP_VELOCITY_WEIGHT),
    ("CLIP_BODY_TRANSLATION_VELOCITY_WEIGHT", CLIP_BODY_TRANSLATION_VELOCITY_WEIGHT),
    ("CLIP_BODY_TRANSLATION_ACCELERATION_WEIGHT", CLIP_BODY_TRANSLATION_ACCELERATION_WEIGHT),
):
    if not math.isfinite(_value) or _value < 0.0:
        raise ValueError(f"{_name} must be finite and non-negative")
if CLIP_PROBE_STEP_DEG <= 0.0 or CLIP_PROBE_TOP_K < 1:
    raise ValueError("clip probe step and top-k must be positive")
if not math.isfinite(CLIP_PROBE_MIN_IMPROVEMENT):
    raise ValueError("CLIP_PROBE_MIN_IMPROVEMENT must be finite")
if CLIP_ADAPTIVE_BLOCK_SIZE < 2 or CLIP_ADAPTIVE_ROUNDS < 1:
    raise ValueError("clip adaptive block size/rounds are invalid")
if CLIP_ADAPTIVE_STEP_DEG <= 0.0 or CLIP_POLISH_STEP_DEG <= 0.0:
    raise ValueError("clip adaptive and polish steps must be positive")
if CLIP_POLISH_ROUNDS < 1:
    raise ValueError("clip polish rounds must be at least 1")
if CLIP_ADAPTIVE_STEP_DEG > CLIP_PROBE_STEP_DEG:
    raise ValueError("CLIP_ADAPTIVE_STEP_DEG must not exceed probe step")
if CLIP_POLISH_STEP_DEG > CLIP_ADAPTIVE_STEP_DEG:
    raise ValueError("CLIP_POLISH_STEP_DEG must not exceed adaptive step")
print("SEARCH_AXES", SEARCH_AXES, "(roll excluded)" if EXCLUDE_BONE_ROLL else "(roll included)")
print(
    "near-bone refinement",
    "enabled" if NEAR_BONE_REFINEMENT_ENABLED else "disabled",
    f"step={NEAR_BONE_REFINEMENT_STEP_DEG:g}deg",
)
print(
    "multi-bone search",
    MULTI_BONE_MODE,
    f"grouping={MULTI_BONE_GROUPING}",
    f"block={MULTI_BONE_BLOCK_SIZE}",
    f"rounds={MULTI_BONE_ROUNDS}",
    f"step={MULTI_BONE_STEP_DEG:g}deg",
    f"pattern={MULTI_BONE_CANDIDATE_PATTERN}",
    f"beam={MULTI_BONE_BEAM_WIDTH}",
)
print(
    "global clip optimization",
    "enabled" if CLIP_OPTIMIZATION_ENABLED else "disabled",
    f"warmStart={CLIP_WARM_START}",
    f"velocity={CLIP_VELOCITY_WEIGHT:g}",
    f"acceleration={CLIP_ACCELERATION_WEIGHT:g}",
    f"loop={'on' if CLIP_LOOP_ENABLED else 'off'}",
)
print(
    "motion root",
    "enabled" if MOTION_ROOT_ENABLED else "disabled",
    f"axes={MOTION_ROOT_AXES}",
    f"limits={_motion_root_limits() if '_motion_root_limits' in globals() else 'configured'}",
    "units=body_lengths",
)

def show_live_preview(
    label,
    score,
    semantic_cosine=None,
    depth_iou=None,
    text_cosine=None,
    negative_text_cosine=None,
    score_details=None,
):
    """Refresh the 3-panel preview. Uses raw PNG bytes to avoid PIL vs IPython Image clashes."""
    if not LIVE_PREVIEW:
        return
    _preview_state["n"] += 1
    if score >= _preview_state["best_score"]:
        _preview_state["best_score"] = float(score)
        _preview_state["best_label"] = label
    if PREVIEW_EVERY > 1 and (_preview_state["n"] % PREVIEW_EVERY) != 0:
        return
    if not PREVIEW_PATH.exists():
        return
    print(
        f"{label}   hybrid={score:.4f}   best={_preview_state['best_score']:.4f} "
        f"({_preview_state['best_label']})   trial #{_preview_state['n']}"
    )
    if semantic_cosine is not None and depth_iou is not None:
        text_part = ""
        if text_cosine is not None:
            text_part = f" text cosine={text_cosine:.4f} weight={HYBRID_TEXT_WEIGHT:.2f}"
        negative_text_part = ""
        if negative_text_cosine is not None:
            negative_avoidance = 1.0 - ((float(np.clip(negative_text_cosine, -1.0, 1.0)) + 1.0) * 0.5)
            negative_text_part = (
                f" negative cosine={negative_text_cosine:.4f}"
                f" avoidance={negative_avoidance:.4f} weight={HYBRID_NEGATIVE_TEXT_WEIGHT:.2f}"
            )
        print(
            f"components: semantic cosine={semantic_cosine:.4f} geometry={depth_iou:.4f}"
            f"{text_part}{negative_text_part} "
            f"weights=semantic:{HYBRID_SEMANTIC_WEIGHT:.2f} geometry:{HYBRID_GEOMETRY_WEIGHT:.2f}"
        )
    if score_details:
        ledger = score_details.get("hybridComponents") or {}
        if ledger:
            names = ", ".join(
                f"{item['name']}={float(item['score']):.4f}*{float(item['weight']):.2f}"
                for item in ledger.get("components", [])
            )
            print(f"active hybrid methods: {names} / sum={float(ledger.get('activeWeightSum', 0.0)):.2f}")
        zones = score_details.get("zoneDiagnostics") or {}
        primary = zones.get("primary") or {}
        print(
            "zones: "
            f"primary blue={int(primary.get('predOnlyPixels', 0))} "
            f"bluePenalty={float(primary.get('predOnlyPenaltyApplied', 0.0)):.3f} "
            f"red={int(primary.get('targetOnlyPixels', 0))} "
            f"redPenalty={float(primary.get('targetOnlyPenaltyApplied', 0.0)):.3f}"
        )
        reverse = zones.get("reverse")
        if reverse:
            print(
                "zones: "
                f"reverse blue={int(reverse.get('predOnlyPixels', 0))} "
                f"bluePenalty={float(reverse.get('predOnlyPenaltyApplied', 0.0)):.3f} "
                f"red={int(reverse.get('targetOnlyPixels', 0))} "
                f"redPenalty={float(reverse.get('targetOnlyPenaltyApplied', 0.0)):.3f}"
            )
        if score_details.get("anatomicalBoxesEnabled"):
            print(
                "anatomical features: "
                f"target={int(score_details.get('anatomicalTargetCount', 0))} "
                f"candidate={int(score_details.get('anatomicalCandidateCount', 0))} "
                f"distance={float(score_details.get('anatomicalFeatureDistance', 1.0)):.4f}"
            )
        if score_details.get("denseSemanticDistance") is not None:
            layers = score_details.get("denseSemanticLayerDistances") or {}
            print(
                "dense semantic: "
                f"distance={float(score_details['denseSemanticDistance']):.4f} "
                f"layers={layers} "
                f"radius={SEMANTIC_DENSE_LOCAL_RADIUS} "
                f"positionWeight={SEMANTIC_DENSE_POSITION_WEIGHT:g}"
            )
    print("panels: target RGB | candidate RGB | depth diagnostic")
    update_live_preview_image()
    update_anatomical_feature_preview()


_MULTI_BONE_EVAL_SERIAL = 0


def _motion_root_pose_entry(pose):
    value = pose.get(MOTION_ROOT_KEY)
    return value if isinstance(value, dict) else {}


def _motion_root_rotation_pose_entry(pose):
    value = pose.get(MOTION_ROOT_ROTATION_KEY)
    return value if isinstance(value, dict) else {}


def _motion_root_limits():
    return {
        "forward": float(MOTION_ROOT_FORWARD_RADIUS_BODY_LENGTHS),
        "lateral": float(MOTION_ROOT_LATERAL_RADIUS_BODY_LENGTHS),
        "vertical": float(MOTION_ROOT_VERTICAL_RADIUS_BODY_LENGTHS),
    }


def _attach_motion_root_request(req, pose):
    """Send translation and rigid-root rotation explicitly."""
    if MOTION_ROOT_ENABLED:
        entry = _motion_root_pose_entry(pose)
        limits = _motion_root_limits()
        req["motionRoot"] = {
            axis: (
                min(limits[axis], max(-limits[axis], float(entry.get(axis, 0.0))))
                if axis in MOTION_ROOT_AXES
                else 0.0
            )
            for axis in ("forward", "lateral", "vertical")
        }
    if MOTION_ROOT_ROTATION_ENABLED:
        entry = _motion_root_rotation_pose_entry(pose)
        req["motionRootRotation"] = {
            axis: (
                min(
                    MOTION_ROOT_ROTATION_LIMIT_DEG,
                    max(
                        -MOTION_ROOT_ROTATION_LIMIT_DEG,
                        float(entry.get(axis, 0.0)),
                    ),
                )
                if axis in MOTION_ROOT_ROTATION_AXES
                else 0.0
            )
            for axis in ("camera_forward", "camera_right", "camera_up")
        }


def _score_multibone_pose(
    frame_index,
    pose,
    label,
    live,
    ik_targets_override=None,
    ik_bones_override=None,
    incumbent_score=None,
    proxy_stage=None,
    proxy_enabled_override=None,
):
    """Score a complete pose for a joint multi-bone candidate.

    This deliberately follows the same worker, hybrid ledger, semantic
    multiview, and live-preview path as the established single-bone scanner.
    A joint search must not accidentally fall back to worker IoU or to a
    different image representation.
    """
    global _MULTI_BONE_EVAL_SERIAL
    proxy_enabled = (
        bool(globals().get("PROXY_ENABLED", False))
        if proxy_enabled_override is None
        else bool(proxy_enabled_override)
    )
    if proxy_enabled:
        proxy_survivors, proxy_metadata, proxy_batch = _proxy_filter_entries(
            frame_index,
            [(pose, label, live)],
            stage=proxy_stage,
            enabled_override=proxy_enabled_override,
        )
        if not proxy_survivors:
            metadata = dict(proxy_metadata.get(0, {}))
            metadata["proxyRejected"] = True
            metadata["proxyReason"] = (
                "level0_rank" if metadata.get("level1") is None else "level1_rank"
            )
            result = {
                "ok": True,
                "iou": -1.0,
                "hybridScore": -1.0,
                "proxyRejected": True,
                "proxyReason": metadata["proxyReason"],
                "proxyScore": float(metadata.get("level1Score", metadata.get("level0Score", -1.0))),
                "proxyDiagnostics": metadata,
                "proxyBatch": proxy_batch,
                "triageRejected": True,
                "triageReason": "geometric_proxy",
            }
            return -1.0, result, float(proxy_batch.get("elapsed", 0.0))
    _MULTI_BONE_EVAL_SERIAL += 1
    cache_key = _pose_cache_key(
        frame_index,
        pose,
        ik_targets_override=ik_targets_override,
        ik_bones_override=ik_bones_override,
    )
    cached_entry = (
        _lru_get(_SCORE_RESULT_CACHE, cache_key)
        if SEMANTIC_CANDIDATE_CACHE_ENABLED and not live
        else None
    )
    if cached_entry is not None:
        _PERFORMANCE_STATS["scoreCacheHits"] += 1
        cached_score, cached_result, cached_elapsed = cached_entry
        return float(cached_score), copy.deepcopy(cached_result), float(cached_elapsed)
    if SEMANTIC_CANDIDATE_CACHE_ENABLED and not live:
        _PERFORMANCE_STATS["scoreCacheMisses"] += 1
    serial = _MULTI_BONE_EVAL_SERIAL
    target = ANIMATION_TARGET_FRAMES / f"{frame_index:02d}.png"
    target_depth = TARGET_DEPTH / f"{frame_index:02d}.png"
    req = {
        "cmd": "score",
        "target": str(target),
        "targetDepth": str(target_depth),
        "angles": dict(pose),
        "scoreMode": SCORE_MODE,
        "depthMaxDist": DEPTH_MAX_DIST,
        "colorMaxDist": COLOR_MAX_DIST,
        "targetPartBoxes": PART_BOXES_BY_FRAME.get(frame_index, []),
        "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,
        "showAnatomicalBoxes": SHOW_ANATOMICAL_BOXES,
        "threshold": 0.08,
    }
    _attach_motion_root_request(req, pose)
    translation = pose.get(BODY_TRANSLATION_KEY)
    if not MOTION_ROOT_ENABLED and isinstance(translation, dict):
        req["bodyTranslationPx"] = [
            float(translation.get("x", 0.0)),
            float(translation.get("y", 0.0)),
        ]
    configure_score_request(
        req,
        frame_index,
        ik_targets_override=ik_targets_override,
        ik_bones_override=ik_bones_override,
    )
    if live:
        req["previewOut"] = str(PREVIEW_PATH)
        req["previewRgb"] = True
        req["previewCaption"] = label
    semantic_candidate = None
    view_paths = []
    if SEMANTIC_ONLY:
        safe_label = re.sub(r"[^A-Za-z0-9_.+-]+", "_", str(label))[:80]
        semantic_candidate = _semantic_candidate_dir / (
            f"multibone_f{frame_index:02d}_{serial:06d}_{safe_label}.png"
        )
        view_paths = semantic_paths(frame_index, f"multibone_{serial:06d}")
        semantic_candidate.unlink(missing_ok=True)
        for path in view_paths:
            path.unlink(missing_ok=True)
        req.update(
            {
                "scoreMode": SCORE_MODE,
                "semanticOnly": True,
                "semanticModel": SEMANTIC_MODEL_ID,
                "previewRgb": True,
                "semanticCandidateOut": str(semantic_candidate),
                "semanticMultiview": bool(SEMANTIC_MULTIVIEW),
                "semanticViewAnglesDeg": list(SEMANTIC_VIEW_ANGLES_DEG),
                "semanticViewElevationsDeg": list(SEMANTIC_VIEW_ELEVATIONS_DEG),
                "semanticViewOuts": [str(path) for path in view_paths],
            }
        )
    started = time.perf_counter()
    result = worker.request(req)
    _record_worker_timing(result)
    if not result.get("ok"):
        raise RuntimeError(result)
    triage_rejected = _triage_reject(result) if SEMANTIC_ONLY else False
    # Silhouette triage is a heuristic gate, not an exact score. Do not spend
    # anatomy/encoder work on a candidate it has already rejected, and never
    # put this rejected result in the exact pose cache below.
    if not triage_rejected and SEMANTIC_ONLY:
        apply_anatomical_candidate_features(result, frame_index, req)
        bound_rejected = _semantic_bound_reject(result, incumbent_score)
        if bound_rejected:
            result["workerIoU"] = result.get("workerIoU", result.get("iou"))
            result["iou"] = -1.0
            result["hybridScore"] = -1.0
            result["triageRejected"] = True
            result["triageReason"] = "semantic_branch_bound"
        else:
            if not semantic_candidate.is_file() or semantic_candidate.stat().st_size <= 0:
                raise RuntimeError(
                    f"semantic candidate render was not written: {semantic_candidate}"
                )
            candidate_paths = view_paths if SEMANTIC_MULTIVIEW else [semantic_candidate]
            if any(not path.is_file() for path in candidate_paths):
                raise RuntimeError(
                    f"semantic multiview render set was not written: {candidate_paths}"
                )
            score_semantic_candidate(
                frame_index,
                candidate_paths,
                result,
                incumbent_score,
            )
    elif triage_rejected:
        result["workerIoU"] = result.get("workerIoU", result.get("iou"))
        result["iou"] = -1.0
        result["hybridScore"] = -1.0
        result["triageRejected"] = True
        result["triageReason"] = "silhouette_rank_or_floor"
    elif not SEMANTIC_ONLY:
        apply_anatomical_candidate_features(result, frame_index, req)
        apply_nonsemantic_hybrid_score(result)
    score = float(result["iou"])
    elapsed = time.perf_counter() - started
    if live:
        show_live_preview(
            label,
            score,
            result.get("semanticCosine"),
            result.get("depthIoU"),
            result.get("textCosine"),
            result.get("negativeTextCosine"),
            result,
        )
    if (
        SEMANTIC_CANDIDATE_CACHE_ENABLED
        and not live
        and not triage_rejected
        and not result.get("semanticBranchBoundRejected")
    ):
        _cache_score_result(cache_key, (score, result, elapsed))
    return score, result, elapsed


def _score_multibone_pose_batch(
    frame_index,
    entries,
    ik_targets_override=None,
    ik_bones_override=None,
    incumbent_score=None,
    required_image_scores=None,
    proxy_stage=None,
    proxy_enabled_override=None,
    force_full=False,
):
    """Render independent clip proposals concurrently, then score in order.

    Blender work is the expensive part of a proposal. The vision encoder and
    hybrid ledger stay in the parent process and are evaluated sequentially so
    GPU memory use and result ordering remain deterministic.
    """
    global _MULTI_BONE_EVAL_SERIAL
    all_entries = list(entries)
    if not all_entries:
        return []
    cached_outputs = {}
    pending_entries = []
    pending_indices = []
    for index, (pose, label, live) in enumerate(all_entries):
        cache_key = _pose_cache_key(
            frame_index,
            pose,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
        cached_entry = (
            _lru_get(_SCORE_RESULT_CACHE, cache_key)
            if SEMANTIC_CANDIDATE_CACHE_ENABLED and not live
            else None
        )
        if cached_entry is not None:
            _PERFORMANCE_STATS["scoreCacheHits"] += 1
            cached_score, cached_result, cached_elapsed = cached_entry
            cached_outputs[index] = (
                float(cached_score),
                copy.deepcopy(cached_result),
                float(cached_elapsed),
            )
        else:
            if SEMANTIC_CANDIDATE_CACHE_ENABLED and not live:
                _PERFORMANCE_STATS["scoreCacheMisses"] += 1
            pending_indices.append(index)
            pending_entries.append((pose, label, live))
    if not pending_entries:
        return [cached_outputs[index] for index in range(len(all_entries))]
    proxy_input_entries = list(pending_entries)
    proxy_input_indices = list(pending_indices)
    proxy_survivors, proxy_metadata, proxy_diagnostics = _proxy_filter_entries(
        frame_index,
        proxy_input_entries,
        stage=proxy_stage,
        enabled_override=proxy_enabled_override,
    )
    proxy_rejected = set(range(len(proxy_input_entries))) - set(proxy_survivors)
    proxy_audit_indices = _proxy_audit_indices(
        proxy_rejected,
        proxy_metadata,
        stage=proxy_stage,
    ) if proxy_diagnostics.get("enabled") else set()
    if proxy_audit_indices:
        _PERFORMANCE_STATS["proxyAuditWaves"] += 1
        _PERFORMANCE_STATS["proxyAuditCandidates"] += len(proxy_audit_indices)
    bound_incumbent = None if (proxy_audit_indices or force_full) else incumbent_score
    bound_required_image_scores = None if (proxy_audit_indices or force_full) else required_image_scores
    proxy_full_indices = sorted(set(proxy_survivors) | set(proxy_audit_indices))
    proxy_non_audit_rejected = proxy_rejected - proxy_audit_indices
    proxy_elapsed_per_candidate = float(proxy_diagnostics.get("elapsed", 0.0)) / max(
        1,
        len(proxy_input_entries),
    )
    for local_index in sorted(proxy_non_audit_rejected):
        original_index = proxy_input_indices[local_index]
        metadata = dict(proxy_metadata.get(local_index, {}))
        metadata["proxyRejected"] = True
        metadata["proxyReason"] = (
            "level0_rank" if metadata.get("level1") is None else "level1_rank"
        )
        last_score = metadata.get("level1Score", metadata.get("level0Score", -1.0))
        cached_outputs[original_index] = (
            -1.0,
            {
                "ok": True,
                "iou": -1.0,
                "hybridScore": -1.0,
                "proxyRejected": True,
                "proxyReason": metadata["proxyReason"],
                "proxyScore": float(last_score),
                "proxyDiagnostics": metadata,
                "proxyBatch": proxy_diagnostics,
                "triageRejected": True,
                "triageReason": "geometric_proxy",
            },
            proxy_elapsed_per_candidate,
        )
    if proxy_rejected:
        pending_entries = [proxy_input_entries[index] for index in proxy_full_indices]
        pending_indices = [proxy_input_indices[index] for index in proxy_full_indices]
    if not pending_entries:
        return [cached_outputs[index] for index in range(len(all_entries))]
    entries = pending_entries
    proxy_metadata_for_entries = [
        proxy_metadata.get(index, {}) for index in proxy_full_indices
    ]
    proxy_audit_positions = {
        position
        for position, local_index in enumerate(proxy_full_indices)
        if local_index in proxy_audit_indices
    }
    target = ANIMATION_TARGET_FRAMES / f"{frame_index:02d}.png"
    target_depth = TARGET_DEPTH / f"{frame_index:02d}.png"
    requests = []
    artifacts = []
    for pose, label, _live in entries:
        _MULTI_BONE_EVAL_SERIAL += 1
        serial = _MULTI_BONE_EVAL_SERIAL
        semantic_candidate = None
        view_paths = []
        req = {
            "cmd": "score",
            "target": str(target),
            "targetDepth": str(target_depth),
            "angles": dict(pose),
            "scoreMode": SCORE_MODE,
            "depthMaxDist": DEPTH_MAX_DIST,
            "colorMaxDist": COLOR_MAX_DIST,
            "targetPartBoxes": PART_BOXES_BY_FRAME.get(frame_index, []),
            "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,
            "showAnatomicalBoxes": SHOW_ANATOMICAL_BOXES,
            "threshold": 0.08,
        }
        _attach_motion_root_request(req, pose)
        translation = pose.get(BODY_TRANSLATION_KEY)
        if not MOTION_ROOT_ENABLED and isinstance(translation, dict):
            req["bodyTranslationPx"] = [
                float(translation.get("x", 0.0)),
                float(translation.get("y", 0.0)),
            ]
        configure_score_request(
            req,
            frame_index,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
        if SEMANTIC_ONLY:
            semantic_candidate = _semantic_candidate_dir / (
                f"multibone_batch_f{frame_index:02d}_{serial:06d}.png"
            )
            view_paths = semantic_paths(frame_index, f"multibone_batch_{serial:06d}")
            semantic_candidate.unlink(missing_ok=True)
            for path in view_paths:
                path.unlink(missing_ok=True)
            req.update({
                "scoreMode": SCORE_MODE,
                "semanticOnly": True,
                "semanticModel": SEMANTIC_MODEL_ID,
                "previewRgb": True,
                "semanticCandidateOut": str(semantic_candidate),
                "semanticMultiview": bool(SEMANTIC_MULTIVIEW),
                "semanticViewAnglesDeg": list(SEMANTIC_VIEW_ANGLES_DEG),
                "semanticViewElevationsDeg": list(SEMANTIC_VIEW_ELEVATIONS_DEG),
                "semanticViewOuts": [str(path) for path in view_paths],
            })
        requests.append(req)
        artifacts.append((semantic_candidate, view_paths))

    started = time.perf_counter()
    pool = globals().get("worker_pool")
    if pool is not None:
        results = pool.request_batch(requests)
    else:
        results = [worker.request(req) for req in requests]
    for worker_result in results:
        _record_worker_timing(worker_result)
    batch_elapsed = time.perf_counter() - started
    _PERFORMANCE_STATS["workerBatchCandidates"] += len(entries)
    _PERFORMANCE_STATS["workerBatchSeconds"] += float(batch_elapsed)
    candidate_vectors_batch = None
    triage_indices = set(range(len(results)))
    triage_diagnostics = {
        "enabled": False,
        "total": len(results),
        "survivors": len(results),
        "rejected": 0,
    }
    if proxy_diagnostics.get("enabled"):
        triage_diagnostics["geometricProxy"] = proxy_diagnostics
    if SEMANTIC_ONLY:
        _PERFORMANCE_STATS["semanticCandidates"] += len(results)
        if force_full:
            triage_indices = set(range(len(results)))
            triage_diagnostics = {
                "enabled": False,
                "bypassed": True,
                "bypassReason": "proxy_audit_full_fallback",
                "total": len(results),
                "survivors": len(results),
                "rejected": 0,
            }
        else:
            triage_indices, triage_diagnostics = _triage_batch_indices(results)
        # Shadow candidates must reach the complete semantic ledger even if a
        # cheaper worker-side silhouette gate would otherwise reject them.
        if proxy_audit_indices:
            # The rank/correlation comparison needs exact scores for the
            # proxy survivors as well as the sampled rejects.
            triage_indices.update(range(len(results)))
        else:
            triage_indices.update(proxy_audit_positions)
        if proxy_audit_positions:
            triage_diagnostics["proxyAuditForcedFull"] = sorted(proxy_audit_positions)
        for candidate_index, ((semantic_candidate, view_paths), result) in enumerate(zip(artifacts, results)):
            if not result.get("ok"):
                raise RuntimeError(result)
            proxy_audit_candidate = candidate_index in proxy_audit_positions
            result["proxyAuditCandidate"] = proxy_audit_candidate
            result["triageEnabled"] = bool(triage_diagnostics.get("enabled", False))
            result["triageSilhouette"] = _triage_silhouette_score(result)
            if candidate_index not in triage_indices and not proxy_audit_candidate:
                # Triage is intentionally a heuristic and therefore cannot be
                # retained in the exact pose/result cache below.
                result["triageRejected"] = True
                result["triageReason"] = "silhouette_rank_or_floor"
                result["workerIoU"] = result.get("workerIoU", result.get("iou"))
                result["iou"] = -1.0
                result["hybridScore"] = -1.0
                continue
            # Anatomy is a second-stage detector. Run it only for silhouette
            # survivors, then include it in the bound if it contributes to the
            # active hybrid objective.
            apply_anatomical_candidate_features(result, frame_index, requests[candidate_index])
            bound_rejected = False if (proxy_audit_candidate or force_full) else _semantic_bound_reject(
                result,
                _semantic_bound_threshold(
                    bound_incumbent,
                    bound_required_image_scores,
                    candidate_index,
                ),
            )
            if bound_rejected:
                triage_indices.discard(candidate_index)
                result["triageRejected"] = True
                result["triageReason"] = "semantic_branch_bound"
                result["workerIoU"] = result.get("workerIoU", result.get("iou"))
                result["iou"] = -1.0
                result["hybridScore"] = -1.0
                continue
            result["triageRejected"] = False
            result["triageReason"] = None
            if not semantic_candidate.is_file() or semantic_candidate.stat().st_size <= 0:
                raise RuntimeError(
                    f"semantic candidate render was not written: {semantic_candidate}"
                )
            candidate_paths = view_paths if SEMANTIC_MULTIVIEW else [semantic_candidate]
            if any(not path.is_file() for path in candidate_paths):
                raise RuntimeError(
                    f"semantic multiview render set was not written: {candidate_paths}"
                )
        # Dense features are the cheaper semantic lane in the current
        # configuration.  Use them before global CLIP and perform a second
        # exact bound with the dense contribution known.
        dense_scores = [(None, {}) for _ in results]
        if (
            SEMANTIC_ONLY
            and SEMANTIC_DENSE_ENABLED
            and SEMANTIC_DENSE_WEIGHT > 0.0
            and triage_indices
        ):
            dense_indices = sorted(triage_indices)
            dense_groups = [
                (
                    artifacts[candidate_index][1]
                    if SEMANTIC_MULTIVIEW
                    else [artifacts[candidate_index][0]]
                )
                for candidate_index in dense_indices
            ]
            dense_batch_scores = semantic_dense_distance_batch(frame_index, dense_groups)
            for candidate_index, dense_score in zip(dense_indices, dense_batch_scores):
                dense_scores[candidate_index] = dense_score
            for candidate_index in list(sorted(triage_indices)):
                dense_distance, _dense_layers = dense_scores[candidate_index]
                if candidate_index not in proxy_audit_positions and _semantic_bound_reject(
                    results[candidate_index],
                    _semantic_bound_threshold(
                        bound_incumbent,
                        bound_required_image_scores,
                        candidate_index,
                    ),
                    dense_distance=dense_distance,
                ):
                    triage_indices.discard(candidate_index)
                    results[candidate_index]["triageRejected"] = True
                    results[candidate_index]["triageReason"] = "semantic_branch_bound_after_dense"
                    results[candidate_index]["workerIoU"] = results[candidate_index].get(
                        "workerIoU", results[candidate_index].get("iou")
                    )
                    results[candidate_index]["iou"] = -1.0
                    results[candidate_index]["hybridScore"] = -1.0
            triage_diagnostics["survivorsAfterDense"] = len(triage_indices)
            triage_diagnostics["denseBoundRejected"] = sum(
                1
                for candidate_index, worker_result in enumerate(results)
                if worker_result.get("triageReason") == "semantic_branch_bound_after_dense"
            )
        candidate_vectors_batch = {
            candidate_index: vectors
            for candidate_index, vectors in zip(
                sorted(triage_indices),
                average_semantic_vectors_batch([
                    artifacts[candidate_index][1]
                    if SEMANTIC_MULTIVIEW
                    else [artifacts[candidate_index][0]]
                    for candidate_index in sorted(triage_indices)
                ]),
            )
        }
        _PERFORMANCE_STATS["semanticSurvivors"] += len(triage_indices)

    output = []
    for candidate_index, ((pose, label, _live), req, (semantic_candidate, view_paths), result) in enumerate(zip(
        entries, requests, artifacts, results
    )):
        if not result.get("ok"):
            raise RuntimeError(result)
        if SEMANTIC_ONLY and candidate_index in triage_indices:
            candidate_paths = view_paths if SEMANTIC_MULTIVIEW else [semantic_candidate]
            candidate_vectors = candidate_vectors_batch[candidate_index]
            semantic_score, semantic_layer_scores = semantic_image_score(
                semantic_target_vector(frame_index), candidate_vectors
            )
            text_score, negative_text_score = semantic_text_scores(candidate_vectors)
            dense_distance, dense_layer_distances = dense_scores[candidate_index]
            apply_hybrid_score(
                result,
                semantic_score,
                text_score,
                negative_text_score,
                semantic_layer_scores,
                dense_distance,
                dense_layer_distances,
            )
        else:
            if not SEMANTIC_ONLY:
                apply_anatomical_candidate_features(result, frame_index, req)
                apply_nonsemantic_hybrid_score(result)
        score = float(result["iou"])
        elapsed = float(result.get("elapsed", batch_elapsed / max(1, len(entries))))
        result["triageBatch"] = triage_diagnostics
        if proxy_diagnostics.get("enabled"):
            result["proxyDiagnostics"] = proxy_metadata_for_entries[candidate_index]
            result["proxyBatch"] = proxy_diagnostics
        output.append((score, result, elapsed))

    if proxy_audit_indices and proxy_diagnostics.get("enabled"):
        audit_rows = []
        for position, local_index in enumerate(proxy_full_indices):
            score, result, _elapsed = output[position]
            metadata = proxy_metadata.get(local_index, {})
            audit_rows.append(
                {
                    "index": int(local_index),
                    "survived": bool(local_index in proxy_survivors),
                    "proxyScore": float(
                        metadata.get(
                            "level1Score",
                            metadata.get("level0Score", -1.0),
                        )
                    ),
                    "fullScore": None
                    if result.get("triageRejected")
                    else float(score),
                }
            )
        audit_metrics = _proxy_audit_metrics(audit_rows)
        audit_metrics["stage"] = _proxy_stage_name(proxy_stage)
        audit_metrics["sampledRejectedIndices"] = sorted(proxy_audit_indices)
        proxy_diagnostics["audit"] = audit_metrics
        for row in audit_rows:
            if row["index"] in proxy_audit_indices:
                proxy_metadata.setdefault(row["index"], {})["proxyAudit"] = row
        _PROXY_AUDIT_HISTORY.append(dict(audit_metrics))
        del _PROXY_AUDIT_HISTORY[:-64]
        if audit_metrics.get("invalid"):
            _PROXY_AUDIT_DISABLED_STAGES.add(_proxy_stage_name(proxy_stage))
            _PERFORMANCE_STATS["proxyAuditInvalidWaves"] += 1
            remaining_rejected = sorted(proxy_non_audit_rejected)
            proxy_diagnostics["fallbackToFull"] = True
            proxy_diagnostics["fallbackReason"] = "positive_sampled_regret"
            proxy_diagnostics["fallbackCount"] = len(remaining_rejected)
            _PERFORMANCE_STATS["proxyAuditFallbackCandidates"] += len(remaining_rejected)
            full_by_local = {
                local_index: value
                for local_index, value in zip(proxy_full_indices, output)
            }
            for local_index in remaining_rejected:
                cached_outputs.pop(proxy_input_indices[local_index], None)
            if remaining_rejected:
                fallback_values = _score_multibone_pose_batch(
                    frame_index,
                    [proxy_input_entries[index] for index in remaining_rejected],
                    ik_targets_override=ik_targets_override,
                    ik_bones_override=ik_bones_override,
                    incumbent_score=incumbent_score,
                    required_image_scores=required_image_scores,
                    proxy_stage=proxy_stage,
                    proxy_enabled_override=False,
                    force_full=True,
                )
                full_by_local.update(
                    zip(remaining_rejected, fallback_values)
                )
            output = [full_by_local[index] for index in range(len(proxy_input_entries))]
            pending_indices = list(proxy_input_indices)
    pending_output = {}
    for pending_index, value in zip(pending_indices, output):
        pending_output[pending_index] = value
        pose, _label, live = all_entries[pending_index]
        if (
            SEMANTIC_CANDIDATE_CACHE_ENABLED
            and not live
            and not value[1].get("triageRejected")
            and not value[1].get("semanticBranchBoundRejected")
        ):
            cache_key = _pose_cache_key(
                frame_index,
                pose,
                ik_targets_override=ik_targets_override,
                ik_bones_override=ik_bones_override,
            )
            _cache_score_result(cache_key, value)
    return [
        cached_outputs[index] if index in cached_outputs else pending_output[index]
        for index in range(len(all_entries))
    ]


def _multi_bone_blocks(nodes):
    """Partition the requested order without using anatomical names."""
    nodes = list(nodes)
    size = int(MULTI_BONE_BLOCK_SIZE)
    if MULTI_BONE_GROUPING == "window":
        return [nodes[start : start + size] for start in range(0, len(nodes), size)]

    selected = set(nodes)
    parent_map = {}
    for parent, child_names in globals().get("CHILDREN_BY_BONE", {}).items():
        for child in child_names:
            parent_map[child] = parent
    children = {name: [] for name in nodes}
    for child, parent in parent_map.items():
        if child in selected and parent in selected:
            children[parent].append(child)
    order_index = {name: index for index, name in enumerate(nodes)}
    for values in children.values():
        values.sort(key=lambda name: order_index[name])
    roots = [name for name in nodes if parent_map.get(name) not in selected]
    roots.sort(key=lambda name: order_index[name])
    visited = set()
    branches = []

    def walk(root):
        branch = []
        stack = [root]
        while stack:
            name = stack.pop()
            if name in visited:
                continue
            visited.add(name)
            branch.append(name)
            stack.extend(reversed(children.get(name, [])))
        return branch

    for root in roots:
        branch = walk(root)
        if branch:
            branches.append(branch)
    # Preserve every requested bone even if an imported armature has malformed
    # or cyclic parent metadata.
    for name in nodes:
        if name not in visited:
            branch = walk(name)
            if branch:
                branches.append(branch)
    return [
        branch[start : start + size]
        for branch in branches
        for start in range(0, len(branch), size)
    ]


def _adaptive_multi_bone_blocks(nodes, probe_rows):
    """Choose dependency-local blocks from a batched signed probe."""
    rotation_nodes = [node for node in nodes if node != MOTION_ROOT_KEY]
    fallback = _multi_bone_blocks(rotation_nodes)
    if not MULTI_BONE_ADAPTIVE_BLOCKS_ENABLED or not probe_rows:
        return _couple_motion_root_blocks(fallback)
    ranked = sorted(
        [row for row in probe_rows if float(row.get("improvement", 0.0)) >= MULTI_BONE_PROBE_MIN_IMPROVEMENT],
        key=lambda row: float(row.get("improvement", 0.0)),
        reverse=True,
    )
    seeds = []
    for row in ranked:
        bone = str(row.get("bone", ""))
        if bone in rotation_nodes and bone not in seeds:
            seeds.append(bone)
        if len(seeds) >= MULTI_BONE_PROBE_TOP_K:
            break
    blocks = []
    seen = set()
    for seed in seeds:
        block = next((list(group) for group in fallback if seed in group), [seed])
        block = tuple(block[:MULTI_BONE_BLOCK_SIZE])
        if block and block not in seen:
            seen.add(block)
            blocks.append(list(block))
    return _couple_motion_root_blocks(blocks or fallback)


def _couple_motion_root_blocks(blocks):
    """Add bounded rigid-root controls to dependency-local search blocks."""
    enabled_controls = []
    if MOTION_ROOT_ENABLED and MOTION_ROOT_COUPLED_BLOCKS_ENABLED:
        enabled_controls.append(MOTION_ROOT_KEY)
    if MOTION_ROOT_ROTATION_ENABLED and MOTION_ROOT_ROTATION_COUPLED_BLOCKS_ENABLED:
        enabled_controls.append(MOTION_ROOT_ROTATION_KEY)
    if not enabled_controls:
        return [list(block) for block in blocks]
    coupled = []
    limit = max(2, int(MULTI_BONE_BLOCK_SIZE))
    seen = set()
    for block in blocks:
        members = [name for name in block if name not in enabled_controls]
        controls = enabled_controls[: max(1, limit - len(members))]
        members = [*controls, *members[: max(0, limit - len(controls))]]
        key = tuple(members)
        if key and key not in seen:
            seen.add(key)
            coupled.append(members)
    if not coupled:
        coupled.append(enabled_controls[:1])
    return coupled


def _multi_bone_euler_deg(pose, bone):
    entry = pose.get(bone, {})
    if isinstance(entry, dict) and entry.get("axis"):
        euler = {"x": 0.0, "y": 0.0, "z": 0.0}
        euler[str(entry["axis"])] = math.degrees(float(entry.get("angle", 0.0)))
        return euler
    if isinstance(entry, dict):
        return {
            axis: math.degrees(float(entry.get(axis, 0.0)))
            for axis in ("x", "y", "z")
        }
    return {"x": 0.0, "y": 0.0, "z": 0.0}


def _multi_bone_pose_with_euler(pose, bone, euler):
    candidate = dict(pose)
    candidate[bone] = {
        axis: math.radians(float(euler.get(axis, 0.0)))
        for axis in ("x", "y", "z")
    }
    return candidate


def _multi_bone_candidates(bone, center, axes, step, pattern):
    """Return a small local lattice around one bone's current pose."""
    lo, hi = range_for(bone)
    axes = tuple(axis for axis in axes if axis in {"x", "y", "z"})
    if pattern == "cube":
        offsets = itertools.product((-float(step), 0.0, float(step)), repeat=len(axes))
    else:
        offsets = [(0.0,) * len(axes)]
        for index in range(len(axes)):
            for direction in (-1.0, 1.0):
                item = [0.0] * len(axes)
                item[index] = direction * float(step)
                offsets.append(tuple(item))
    result = []
    seen = set()
    for offset in offsets:
        euler = dict(center)
        for axis, delta in zip(axes, offset):
            euler[axis] = min(hi, max(lo, float(euler[axis]) + float(delta)))
        key = tuple(round(float(euler[axis]), 6) for axis in ("x", "y", "z"))
        if key not in seen:
            seen.add(key)
            result.append(euler)
    return result


def _batch_probe_multi_bone_variables(
    frame_index,
    pose,
    bones,
    live,
    ik_targets_override=None,
    ik_bones_override=None,
):
    """Probe every requested bone/axis in one renderer/encoder batch."""
    entries = []
    metadata = []
    root_limits = _motion_root_limits()
    for bone in bones:
        if bone == MOTION_ROOT_KEY:
            axes = MOTION_ROOT_AXES
        else:
            axes = SEARCH_AXES
        center = _multi_bone_euler_deg(pose, bone)
        for axis in axes:
            current = (
                float(_motion_root_pose_entry(pose).get(axis, 0.0))
                if bone == MOTION_ROOT_KEY
                else float(center.get(axis, 0.0))
            )
            if bone == MOTION_ROOT_KEY:
                lo, hi = -root_limits[axis], root_limits[axis]
                step = MOTION_ROOT_COARSE_STEP_BODY_LENGTHS
            else:
                lo, hi = map(float, range_for(bone))
                step = MULTI_BONE_PROBE_STEP_DEG
            probe_values = [
                current - step,
                current + step,
                lo,
                hi,
            ]
            seen_values = set()
            for raw_value in probe_values:
                value = min(hi, max(lo, raw_value))
                if abs(value - current) <= 1e-8:
                    continue
                value_key = round(float(value), 8)
                if value_key in seen_values:
                    continue
                seen_values.add(value_key)
                candidate = copy.deepcopy(pose)
                if bone == MOTION_ROOT_KEY:
                    candidate.setdefault(
                        MOTION_ROOT_KEY,
                        {root_axis: 0.0 for root_axis in ("forward", "lateral", "vertical")},
                    )[axis] = float(value)
                else:
                    candidate = _multi_bone_pose_with_euler(
                        candidate,
                        bone,
                        {**center, axis: float(value)},
                    )
                entries.append(
                    (
                        candidate,
                        f"f{frame_index:02d} batch probe {bone} {axis} {value:+.3f}"
                        if bone == MOTION_ROOT_KEY
                        else f"f{frame_index:02d} batch probe {bone} {axis} {value:+.1f}",
                        False,
                    )
                )
                metadata.append((bone, axis, float(value), candidate))
    if not entries:
        return [], []
    results = _score_multibone_pose_batch(
        frame_index,
        entries,
        ik_targets_override=ik_targets_override,
        ik_bones_override=ik_bones_override,
        proxy_stage="multi_bone_probe",
    )
    base_score, _base_result, _base_dt = _score_multibone_pose(
        frame_index,
        pose,
        f"f{frame_index:02d} batch probe baseline",
        live,
        ik_targets_override=ik_targets_override,
        ik_bones_override=ik_bones_override,
    )
    rows = []
    for (bone, axis, value, candidate), (score, result, elapsed) in zip(metadata, results):
        rows.append(
            {
                "bone": bone,
                "axis": axis,
                "value": value,
                "score": float(score),
                "improvement": float(score - base_score),
                "elapsed": float(elapsed),
                "pose": candidate,
                "result": result,
            }
        )
    rows.sort(key=lambda row: float(row["improvement"]), reverse=True)
    return rows, metadata


def optimize_frame_multibone(
    frame_index,
    initial=None,
    bones=None,
    progress=None,
    live_preview=None,
    ik_targets_override=None,
    ik_bones_override=None,
):
    """Run the staged batched multi-bone search.

    The stages deliberately avoid a Cartesian product over the whole rig:
    signed probes discover useful variables, dependency-local blocks restrict
    interaction search, a small beam retains alternatives, and a final small
    step polish cleans up the accepted pose.  Every non-live candidate in a
    stage is sent through the batch scorer so Blender and the vision encoder
    can work in waves.
    """
    live = LIVE_PREVIEW if live_preview is None else bool(live_preview)
    pose = copy.deepcopy(initial or {})
    current_bones = [
        MOTION_ROOT_KEY if str(bone) == LEGACY_BODY_TRANSLATION_KEY else str(bone)
        for bone in (pilot_bones if bones is None else bones)
    ]
    root_controls = []
    if MOTION_ROOT_ENABLED:
        root_controls.append(MOTION_ROOT_KEY)
    if MOTION_ROOT_ROTATION_ENABLED:
        root_controls.append(MOTION_ROOT_ROTATION_KEY)
    current_bones = root_controls + [
        bone for bone in current_bones if bone not in set(root_controls)
    ]
    history = []
    timings = []
    started = time.perf_counter()

    coupled_rigid_root = (
        MOTION_ROOT_KEY in current_bones
        and MOTION_ROOT_ROTATION_KEY in current_bones
        and MOTION_ROOT_COUPLED_BLOCKS_ENABLED
        and MOTION_ROOT_ROTATION_COUPLED_BLOCKS_ENABLED
    )
    if coupled_rigid_root:
        root_start = time.perf_counter()
        (
            root_delta,
            root_rotation_delta,
            root_score,
            root_trials,
            root_timings,
        ) = scan_motion_root_rigid(
            frame_index,
            pose,
            progress_desc="coupled rigid motion root",
            live_preview=live,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
        pose[MOTION_ROOT_KEY] = root_delta
        pose[MOTION_ROOT_ROTATION_KEY] = root_rotation_delta
        root_elapsed = time.perf_counter() - root_start
        history.append(
            {
                "bone": f"{MOTION_ROOT_KEY}+{MOTION_ROOT_ROTATION_KEY}",
                "axis": "motion_root_rigid",
                "root": dict(root_delta),
                "angleDeg": dict(root_rotation_delta),
                "hybridScore": float(root_score),
                "trials": len(root_trials),
                "timings": root_timings,
                "elapsed": root_elapsed,
            }
        )
        timings.append(
            {
                "bone": f"{MOTION_ROOT_KEY}+{MOTION_ROOT_ROTATION_KEY}",
                **root_timings,
                "elapsed_total": root_elapsed,
            }
        )
        current_bones = [
            bone
            for bone in current_bones
            if bone not in {MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY}
        ]

    if not coupled_rigid_root and MOTION_ROOT_KEY in current_bones:
        root_start = time.perf_counter()
        root_delta, root_score, root_trials, root_timings = scan_motion_root(
            frame_index,
            pose,
            progress_desc="motion root translation",
            live_preview=live,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
        pose[MOTION_ROOT_KEY] = root_delta
        root_elapsed = time.perf_counter() - root_start
        history.append(
            {
                "bone": MOTION_ROOT_KEY,
                "axis": "motion_root",
                "units": "body_lengths",
                "root": dict(root_delta),
                "hybridScore": float(root_score),
                "trials": len(root_trials),
                "timings": root_timings,
                "elapsed": root_elapsed,
            }
        )
        timings.append(
            {
                "bone": MOTION_ROOT_KEY,
                **root_timings,
                "elapsed_total": root_elapsed,
            }
        )
        current_bones = [bone for bone in current_bones if bone != MOTION_ROOT_KEY]

    if not coupled_rigid_root and MOTION_ROOT_ROTATION_KEY in current_bones:
        root_start = time.perf_counter()
        root_delta, root_score, root_trials, root_timings = scan_motion_root_rotation(
            frame_index,
            pose,
            progress_desc="motion root rotation",
            live_preview=live,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
            relax_bones=current_bones,
        )
        pose[MOTION_ROOT_ROTATION_KEY] = root_delta
        root_elapsed = time.perf_counter() - root_start
        history.append(
            {
                "bone": MOTION_ROOT_ROTATION_KEY,
                "axis": "motion_root_rotation",
                "angleDeg": dict(root_delta),
                "hybridScore": float(root_score),
                "trials": len(root_trials),
                "timings": root_timings,
                "elapsed": root_elapsed,
            }
        )
        timings.append(
            {
                "bone": MOTION_ROOT_ROTATION_KEY,
                **root_timings,
                "elapsed_total": root_elapsed,
            }
        )
        current_bones = [
            bone for bone in current_bones if bone != MOTION_ROOT_ROTATION_KEY
        ]

    if ROTATION_VECTOR_SEARCH_ENABLED:
        vector_stage_started = time.perf_counter()
        vector_bone_rows = []
        for bone in current_bones:
            if bone == MOTION_ROOT_KEY:
                continue
            vector_start = time.perf_counter()
            vector_entry, vector_score, vector_trials, vector_timing = scan_bone_rotation_vector(
                frame_index,
                bone,
                pose,
                progress_desc=f"Vector [{bone}]",
                live_preview=live,
                ik_targets_override=ik_targets_override,
                ik_bones_override=ik_bones_override,
            )
            pose[bone] = vector_entry
            vector_elapsed = time.perf_counter() - vector_start
            vector_bone_rows.append(
                {
                    "bone": bone,
                    "hybridScore": float(vector_score),
                    "trials": len(vector_trials),
                    "timings": vector_timing,
                    "elapsed": float(vector_elapsed),
                }
            )
        history.append(
            {
                "kind": "multi_bone_rotation_vector",
                "bones": [row["bone"] for row in vector_bone_rows],
                "rows": vector_bone_rows,
                "elapsed": time.perf_counter() - vector_stage_started,
            }
        )
        timings.append(
            {
                "kind": "multi_bone_rotation_vector",
                "bones": [row["bone"] for row in vector_bone_rows],
                "evaluations": sum(row["trials"] for row in vector_bone_rows),
                "elapsed_total": time.perf_counter() - vector_stage_started,
            }
        )

    probe_rows = []
    if MULTI_BONE_PROBE_ENABLED:
        probe_started = time.perf_counter()
        probe_rows, _ = _batch_probe_multi_bone_variables(
            frame_index,
            pose,
            current_bones,
            False,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
        history.append({
            "kind": "multi_bone_batch_probe",
            "frame": int(frame_index),
            "rows": [
                {
                    key: row[key]
                    for key in ("bone", "axis", "value", "score", "improvement", "elapsed")
                }
                for row in probe_rows
            ],
            "stepDeg": float(MULTI_BONE_PROBE_STEP_DEG),
            "topK": int(MULTI_BONE_PROBE_TOP_K),
            "elapsed": time.perf_counter() - probe_started,
        })
        timings.append({
            "kind": "multi_bone_batch_probe",
            "frame": int(frame_index),
            "evaluations": len(probe_rows),
            "stepDeg": float(MULTI_BONE_PROBE_STEP_DEG),
            "elapsed_total": time.perf_counter() - probe_started,
        })

    blocks = _adaptive_multi_bone_blocks(current_bones, probe_rows)

    def candidate_records(state_pose, bone, step):
        """Build a sparse star around one state without renderer calls."""
        if bone == MOTION_ROOT_KEY:
            center = {
                axis: float(_motion_root_pose_entry(state_pose).get(axis, 0.0))
                for axis in ("forward", "lateral", "vertical")
            }
            records = [{
                "pose": copy.deepcopy(state_pose),
                "same": True,
                "value": dict(center),
            }]
            for axis in MOTION_ROOT_AXES:
                for direction in (-1.0, 1.0):
                    value = min(
                        float(_motion_root_limits()[axis]),
                        max(
                            -float(_motion_root_limits()[axis]),
                            center[axis] + direction * float(step),
                        ),
                    )
                    if abs(value - center[axis]) <= 1e-8:
                        continue
                    candidate = copy.deepcopy(state_pose)
                    candidate.setdefault(
                        MOTION_ROOT_KEY,
                        {root_axis: 0.0 for root_axis in ("forward", "lateral", "vertical")},
                    )[axis] = value
                    records.append({
                        "pose": candidate,
                        "same": False,
                        "value": {**center, axis: value},
                    })
            return records

        center = _multi_bone_euler_deg(state_pose, bone)
        eulers = _multi_bone_candidates(
            bone,
            center,
            SEARCH_AXES,
            float(step),
            MULTI_BONE_CANDIDATE_PATTERN,
        )
        records = []
        for euler in eulers:
            candidate = _multi_bone_pose_with_euler(state_pose, bone, euler)
            same = all(
                abs(float(euler[axis]) - float(center[axis])) <= 1e-8
                for axis in ("x", "y", "z")
            )
            records.append({"pose": candidate, "same": same, "value": dict(euler)})
        return records

    def run_stage(stage_name, round_count, step, beam_width):
        nonlocal pose
        for round_index in range(int(round_count)):
            for block_index, block in enumerate(blocks):
                if not block:
                    continue
                block_started = time.perf_counter()
                baseline_score, _baseline_result, baseline_dt = _score_multibone_pose(
                    frame_index,
                    pose,
                    f"f{frame_index:02d} {stage_name} block {block_index + 1} baseline",
                    False,
                    ik_targets_override=ik_targets_override,
                    ik_bones_override=ik_bones_override,
                )
                states = [{"pose": copy.deepcopy(pose), "score": float(baseline_score)}]
                trial_rows = [{
                    "stage": stage_name,
                    "round": int(round_index + 1),
                    "label": "baseline",
                    "score": float(baseline_score),
                    "dt_score": float(baseline_dt),
                    "evaluated": True,
                }]
                for bone in block:
                    expanded = []
                    entries = []
                    metadata = []
                    for state_index, state in enumerate(states):
                        candidate_step = (
                            MOTION_ROOT_COARSE_STEP_BODY_LENGTHS
                            if stage_name == "coarse"
                            else MOTION_ROOT_REFINE_STEP_BODY_LENGTHS
                        ) if bone == MOTION_ROOT_KEY else step
                        records = candidate_records(state["pose"], bone, candidate_step)
                        for candidate_index, record in enumerate(records):
                            if record["same"]:
                                expanded.append({
                                    "pose": record["pose"],
                                    "score": float(state["score"]),
                                })
                                trial_rows.append({
                                    "stage": stage_name,
                                    "round": int(round_index + 1),
                                    "bone": bone,
                                    "candidate": int(candidate_index),
                                    "state": int(state_index),
                                    "value": record["value"],
                                    "score": float(state["score"]),
                                    "dt_score": 0.0,
                                    "evaluated": False,
                                })
                                continue
                            entries.append((
                                record["pose"],
                                (
                                    f"f{frame_index:02d} {stage_name} block {block_index + 1} "
                                    f"round {round_index + 1} {bone} candidate {candidate_index + 1}"
                                ),
                                False,
                            ))
                            metadata.append((state_index, bone, candidate_index, record))
                    batch_results = _score_multibone_pose_batch(
                        frame_index,
                        entries,
                        ik_targets_override=ik_targets_override,
                        ik_bones_override=ik_bones_override,
                        incumbent_score=max(
                            float(baseline_score),
                            *(float(state["score"]) for state in states),
                        ),
                        proxy_stage=f"multi_bone_{stage_name}",
                    )
                    for (state_index, bone, candidate_index, record), (score, _result, dt) in zip(
                        metadata,
                        batch_results,
                    ):
                        expanded.append({"pose": record["pose"], "score": float(score)})
                        trial_rows.append({
                            "stage": stage_name,
                            "round": int(round_index + 1),
                            "bone": bone,
                            "candidate": int(candidate_index),
                            "state": int(state_index),
                            "value": record["value"],
                            "score": float(score),
                            "dt_score": float(dt),
                            "evaluated": True,
                        })
                    expanded.sort(key=lambda state: float(state["score"]), reverse=True)
                    states = expanded[: max(1, int(beam_width))]
                if not states:
                    continue
                best_state = max(states, key=lambda state: float(state["score"]))
                pose = copy.deepcopy(best_state["pose"])
                display_score = float(best_state["score"])
                if live:
                    display_score, _display_result, _display_dt = _score_multibone_pose(
                        frame_index,
                        pose,
                        f"f{frame_index:02d} {stage_name} block {block_index + 1} accepted",
                        True,
                        ik_targets_override=ik_targets_override,
                        ik_bones_override=ik_bones_override,
                    )
                evaluations = sum(1 for row in trial_rows if row.get("evaluated"))
                kind = (
                    "multi_bone_block_coordinate"
                    if MULTI_BONE_MODE == "block_coordinate"
                    else "multi_bone_joint_beam"
                )
                history.append({
                    "bone": ",".join(block),
                    "bones": list(block),
                    "kind": kind,
                    "stage": stage_name,
                    "block": list(block),
                    "round": int(round_index + 1),
                    "hybridScore": display_score,
                    "trials": evaluations,
                    "candidateCount": len(trial_rows),
                    "beamWidth": int(beam_width),
                    "candidatePattern": MULTI_BONE_CANDIDATE_PATTERN,
                    "stepDeg": float(step),
                    "trialsDetail": trial_rows,
                })
                timings.append({
                    "kind": kind,
                    "stage": stage_name,
                    "block": list(block),
                    "round": int(round_index + 1),
                    "beamWidth": int(beam_width),
                    "candidatePattern": MULTI_BONE_CANDIDATE_PATTERN,
                    "stepDeg": float(step),
                    "evaluations": evaluations,
                    "candidateCount": len(trial_rows),
                    "bestScore": display_score,
                    "elapsed_total": time.perf_counter() - block_started,
                    "trials": trial_rows,
                })
                print(
                    f"f{frame_index:02d} multi {stage_name} block {block_index + 1}: "
                    f"bones={block} round={round_index + 1} "
                    f"best={display_score:.6f} evals={evaluations} "
                    f"batch={len(entries)} elapsed={time.perf_counter() - block_started:.2f}s"
                )

    run_stage(
        "coarse",
        MULTI_BONE_ROUNDS,
        MULTI_BONE_STEP_DEG,
        MULTI_BONE_BEAM_WIDTH if MULTI_BONE_MODE == "joint_beam" else 1,
    )
    if MULTI_BONE_ADAPTIVE_BLOCKS_ENABLED:
        run_stage(
            "intermediate",
            MULTI_BONE_INTERMEDIATE_ROUNDS,
            MULTI_BONE_INTERMEDIATE_STEP_DEG,
            MULTI_BONE_BEAM_WIDTH if MULTI_BONE_MODE == "joint_beam" else 1,
        )
    if MULTI_BONE_POLISH_ENABLED:
        run_stage(
            "polish",
            MULTI_BONE_POLISH_ROUNDS,
            MULTI_BONE_POLISH_STEP_DEG,
            MULTI_BONE_BEAM_WIDTH if MULTI_BONE_MODE == "joint_beam" else 1,
        )

    elapsed = time.perf_counter() - started
    print(
        f"Frame {frame_index}: multi-bone total elapsed {elapsed:.2f}s "
        f"(mode={MULTI_BONE_MODE}, blocks={len(blocks)}, probe={len(probe_rows)})"
    )
    return pose, history, elapsed, timings

def scan_bone_axis(
    frame_index,
    bone,
    accumulated,
    axis,
    coarse_step=None,
    refine_step=None,
    progress_desc=None,
    live_preview=None,
    ik_targets_override=None,
    ik_bones_override=None,
):
    """Coarse-to-fine sweep on one local axis. Returns (angle_rad, iou, trials, timings)."""
    live = LIVE_PREVIEW if live_preview is None else live_preview
    coarse_step = float(COARSE_STEP_DEG if coarse_step is None else coarse_step)
    refine_step = float(REFINE_STEP_DEG if refine_step is None else refine_step)
    lo, hi = range_for(bone)
    target = ANIMATION_TARGET_FRAMES / f"{frame_index:02d}.png"
    target_depth = TARGET_DEPTH / f"{frame_index:02d}.png"
    trials = []
    timings = {
        "axis": axis,
        "coarse_total": 0.0,
        "coarse_all_evals": [],
        "coarse_maxangle": None,
        "refine_total": 0.0,
        "refine_all_evals": [],
        "angle_evaluations": [],
    }
    bound_incumbent = None
    _preview_state["best_score"] = -1.0
    _preview_state["best_label"] = ""

    def evaluate(angle_deg, region):
        nonlocal bound_incumbent
        pose = dict(accumulated)
        pose[bone] = {"axis": axis, "angle": math.radians(angle_deg)}
        t0 = time.perf_counter()
        caption = (
            f"f{frame_index:02d} {progress_desc or bone}  "
            f"{axis.upper()} {region}  {angle_deg:.1f}deg"
        )
        req = {
            "cmd": "score",
            "target": str(target),
            "targetDepth": str(target_depth),
            "angles": pose,
            "scoreMode": SCORE_MODE,
            "semanticOnly": bool(SEMANTIC_ONLY),
            "semanticModel": SEMANTIC_MODEL_ID if SEMANTIC_ONLY else None,
            "depthMaxDist": DEPTH_MAX_DIST,
            "colorMaxDist": COLOR_MAX_DIST,
            "targetPartBoxes": PART_BOXES_BY_FRAME.get(frame_index, []),
            "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,
            "showAnatomicalBoxes": SHOW_ANATOMICAL_BOXES,
        }
        _attach_motion_root_request(req, pose)
        configure_score_request(
            req,
            frame_index,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
        view_paths = semantic_paths(frame_index, f"{bone}_{axis}_{region}_{angle_deg:+07.2f}")
        if live:
            req["previewOut"] = str(PREVIEW_PATH)
            req["previewRgb"] = True
            req["previewCaption"] = caption
            req["previewProfileDepth"] = bool(req.get("renderDepth", False))
            req["previewActionCamera"] = True
            req["actionCameraAngleDeg"] = float(globals().get("ACTION_CAMERA_ANGLE_DEG", -45.0))
            req["actionCameraElevationDeg"] = float(globals().get("ACTION_CAMERA_ELEVATION_DEG", 18.0))
        if SEMANTIC_ONLY:
            req['scoreMode'] = SCORE_MODE
            req['previewRgb'] = True
            req['semanticCandidateOut'] = str(_semantic_candidate_dir / f'f{frame_index:02d}_{bone}_{axis}_{region}_{angle_deg:+07.2f}.png')
            req['semanticMultiview'] = bool(SEMANTIC_MULTIVIEW)
            req['semanticViewAnglesDeg'] = list(SEMANTIC_VIEW_ANGLES_DEG)
            req['semanticViewElevationsDeg'] = list(SEMANTIC_VIEW_ELEVATIONS_DEG)
            req['semanticViewOuts'] = [str(path) for path in view_paths]
            Path(req['semanticCandidateOut']).unlink(missing_ok=True)
            for path in view_paths:
                path.unlink(missing_ok=True)
        result = worker.request(req)
        if not result.get('ok'):
            raise RuntimeError(result)
        triage_rejected = _triage_reject(result) if SEMANTIC_ONLY else False
        if not triage_rejected and SEMANTIC_ONLY:
            apply_anatomical_candidate_features(result, frame_index, req)
            bound_rejected = _semantic_bound_reject(result, bound_incumbent)
            if not bound_rejected:
                candidate_path = Path(req['semanticCandidateOut'])
                if not candidate_path.is_file() or candidate_path.stat().st_size <= 0:
                    raise RuntimeError(f"semantic candidate render was not written: {candidate_path}")
                candidate_paths = view_paths if SEMANTIC_MULTIVIEW else [candidate_path]
                if any(not path.is_file() for path in candidate_paths):
                    raise RuntimeError(f"semantic multiview render set was not written: {candidate_paths}")
                score_semantic_candidate(
                    frame_index,
                    candidate_paths,
                    result,
                    bound_incumbent,
                )
        elif not SEMANTIC_ONLY:
            apply_anatomical_candidate_features(result, frame_index, req)
            apply_nonsemantic_hybrid_score(result)
        dt = time.perf_counter() - t0
        if not result.get("ok"):
            raise RuntimeError(result)
        iou = float(result["iou"])
        if bound_incumbent is None or iou > float(bound_incumbent):
            bound_incumbent = iou
        if live:
            show_live_preview(
                caption,
                iou,
                result.get("semanticCosine"),
                result.get("depthIoU"),
                result.get("textCosine"),
                result.get("negativeTextCosine"),
                result,
            )
        eval_info = {
            "axis": axis,
            "angle": float(angle_deg),
            "iou": iou,
            "region": region,
            "semanticCosine": result.get("semanticCosine"),
            "semanticLayerCosines": result.get("semanticLayerCosines"),
            "depthIoU": result.get("depthIoU"),
            "textCosine": result.get("textCosine"),
            "negativeTextCosine": result.get("negativeTextCosine"),
            "negativeTextAvoidance": result.get("negativeTextAvoidance"),
            "workerIoU": result.get("workerIoU"),
            "anatomicalPartIoU": result.get("anatomicalPartIoU"),
            "anatomicalFeatureDistance": result.get("anatomicalFeatureDistance"),
            "hybridComponents": result.get("hybridComponents"),
            "zoneDiagnostics": result.get("zoneDiagnostics"),
            "dt_score": dt,
        }
        timings["angle_evaluations"].append(eval_info)
        if region == "coarse":
            timings["coarse_all_evals"].append(eval_info)
        else:
            timings["refine_all_evals"].append(eval_info)
        trials.append((axis, float(angle_deg), iou))
        return iou

    if lo == hi:
        # Locked bone: score bind (0) once.
        score = evaluate(float(lo), "coarse")
        timings["coarse_total"] = 0.0
        timings["coarse_maxangle"] = float(lo)
        return math.radians(float(lo)), float(score), trials, timings

    coarse_step_eff = float(coarse_step)
    span = float(hi) - float(lo)
    if span > 1e-9:
        # Keep several samples inside tight hub/limb caps (e.g. ±6° with default step 8).
        coarse_step_eff = min(coarse_step_eff, max(float(refine_step), span / 4.0))
    coarse = np.arange(lo, hi + coarse_step_eff * 0.5, coarse_step_eff)
    base_entry = accumulated.get(bone, {})
    if isinstance(base_entry, dict) and base_entry.get("axis") == axis:
        base_angle = math.degrees(float(base_entry.get("angle", 0.0)))
    elif isinstance(base_entry, dict):
        base_angle = math.degrees(float(base_entry.get(axis, 0.0)))
    else:
        base_angle = 0.0
    base_angle = float(min(hi, max(lo, base_angle)))
    if not np.any(np.isclose(coarse, base_angle)):
        coarse = np.unique(np.append(coarse.astype(float), base_angle))
    if lo <= 0.0 <= hi and not np.any(np.isclose(coarse, 0.0)):
        coarse = np.unique(np.append(coarse.astype(float), 0.0))
    t0 = time.perf_counter()
    coarse_results = []
    coarse_iter = coarse if live else tqdm(coarse, desc=f"{progress_desc} {axis} coarse", leave=False)
    for a in coarse_iter:
        coarse_results.append((float(a), evaluate(float(a), "coarse")))
    timings["coarse_total"] = time.perf_counter() - t0
    best_angle, best_score = max(coarse_results, key=lambda x: x[1])
    timings["coarse_maxangle"] = best_angle

    fine = np.arange(
        max(lo, best_angle - coarse_step),
        min(hi, best_angle + coarse_step) + refine_step * 0.5,
        refine_step,
    )
    t0 = time.perf_counter()
    fine_iter = fine if live else tqdm(fine, desc=f"{progress_desc} {axis} refine", leave=False)
    for angle in fine_iter:
        score = evaluate(float(angle), "refine")
        if score > best_score:
            best_angle, best_score = float(angle), score
    timings["refine_total"] = time.perf_counter() - t0

    return math.radians(best_angle), float(best_score), trials, timings


def scan_motion_root(
    frame_index,
    accumulated,
    progress_desc=None,
    live_preview=None,
    ik_targets_override=None,
    ik_bones_override=None,
    refinement_only=False,
):
    """Search one whole-model root variable in normalized body-length units."""
    live = LIVE_PREVIEW if live_preview is None else bool(live_preview)
    limits = _motion_root_limits()
    axes = tuple(MOTION_ROOT_AXES)
    if not MOTION_ROOT_ENABLED or not axes:
        raise RuntimeError("motion root scan requested while motion root is disabled")
    base_entry = _motion_root_pose_entry(accumulated)
    best_root = {
        axis: (
            min(limits[axis], max(-limits[axis], float(base_entry.get(axis, 0.0))))
            if axis in axes
            else 0.0
        )
        for axis in ("forward", "lateral", "vertical")
    }
    timings = {
        "mode": "motion_root",
        "units": "body_lengths",
        "axesTried": list(axes),
        "coarseStepBodyLengths": float(MOTION_ROOT_COARSE_STEP_BODY_LENGTHS),
        "refineStepBodyLengths": float(MOTION_ROOT_REFINE_STEP_BODY_LENGTHS),
        "angle_evaluations": [],
    }
    all_trials = []

    def _pose(root_values):
        candidate = dict(accumulated)
        candidate[MOTION_ROOT_KEY] = dict(root_values)
        return candidate

    baseline_pose = _pose(best_root)
    best_score, _baseline_result, baseline_dt = _score_multibone_pose(
        frame_index,
        baseline_pose,
        f"f{frame_index:02d} {progress_desc or 'motion root'} baseline",
        False,
        ik_targets_override=ik_targets_override,
        ik_bones_override=ik_bones_override,
    )
    all_trials.append({"region": "baseline", "root": dict(best_root), "score": float(best_score)})

    def _evaluate(values, region):
        nonlocal best_root, best_score
        entries = []
        metadata = []
        for axis in axes:
            current = float(values[axis])
            if region == "coarse":
                step = float(MOTION_ROOT_COARSE_STEP_BODY_LENGTHS)
                raw_values = (current - step, current + step, -limits[axis], limits[axis])
            else:
                step = float(MOTION_ROOT_REFINE_STEP_BODY_LENGTHS)
                raw_values = (current - step, current + step)
            seen = set()
            for raw in raw_values:
                value = min(limits[axis], max(-limits[axis], float(raw)))
                key = round(value, 8)
                if abs(value - current) <= 1e-9 or key in seen:
                    continue
                seen.add(key)
                candidate_root = dict(values)
                candidate_root[axis] = value
                entries.append(
                    (
                        _pose(candidate_root),
                        f"f{frame_index:02d} {progress_desc or 'motion root'} "
                        f"{region} {axis} {value:+.4f}",
                        False,
                    )
                )
                metadata.append((axis, value, candidate_root))
        if not entries:
            return
        scored = _score_multibone_pose_batch(
            frame_index,
            entries,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
            incumbent_score=best_score,
            proxy_stage="motion_root",
        )
        for (axis, value, candidate_root), (score, _result, elapsed) in zip(metadata, scored):
            row = {
                "region": region,
                "axis": axis,
                "value": float(value),
                "root": dict(candidate_root),
                "score": float(score),
                "improvement": float(score - best_score),
                "dt_score": float(elapsed),
            }
            all_trials.append(row)
            timings["angle_evaluations"].append(row)
            if float(score) > float(best_score) + 1e-9:
                best_score = float(score)
                best_root = dict(candidate_root)

    if not refinement_only:
        _evaluate(best_root, "coarse")
    _evaluate(best_root, "refine")
    if live:
        _score_multibone_pose(
            frame_index,
            _pose(best_root),
            f"f{frame_index:02d} {progress_desc or 'motion root'} best preview",
            True,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
    timings["chosenRoot"] = dict(best_root)
    timings["bestScore"] = float(best_score)
    timings["baselineSeconds"] = float(baseline_dt)
    return dict(best_root), float(best_score), all_trials, timings


def scan_motion_root_rotation(
    frame_index,
    accumulated,
    progress_desc=None,
    live_preview=None,
    ik_targets_override=None,
    ik_bones_override=None,
    refinement_only=False,
    relax_bones=None,
):
    """Search rigid-body attitude in the fitted camera basis.

    The escape stage deliberately evaluates distant orientations instead of
    assuming that a local +/- step can reach a knockdown. Local coarse/fine
    refinement then starts from the best discovered rigid orientation.
    """
    live = LIVE_PREVIEW if live_preview is None else bool(live_preview)
    if not MOTION_ROOT_ROTATION_ENABLED or not MOTION_ROOT_ROTATION_AXES:
        raise RuntimeError(
            "motion root rotation scan requested while rigid root rotation is disabled"
        )
    if MOTION_ROOT_ROTATION_ESCAPE_RELAX_ENABLED and relax_bones is None:
        raise ValueError(
            "motion root rotation escape relaxation requires an explicit relax_bones order"
        )
    limits = {
        axis: float(MOTION_ROOT_ROTATION_LIMIT_DEG)
        for axis in ("camera_forward", "camera_right", "camera_up")
    }
    axes = tuple(MOTION_ROOT_ROTATION_AXES)
    escape_axes = tuple(MOTION_ROOT_ROTATION_ESCAPE_AXES)
    base_entry = _motion_root_rotation_pose_entry(accumulated)
    best_root = {
        axis: (
            min(limits[axis], max(-limits[axis], float(base_entry.get(axis, 0.0))))
            if axis in axes
            else 0.0
        )
        for axis in ("camera_forward", "camera_right", "camera_up")
    }
    timings = {
        "mode": "motion_root_rotation",
        "units": "degrees",
        "basis": MOTION_ROOT_ROTATION_BASIS,
        "axesTried": list(axes),
        "escapeAxes": list(escape_axes),
        "escapeAnglesDeg": list(MOTION_ROOT_ROTATION_ESCAPE_ANGLES_DEG),
        "hypothesisCount": len(escape_axes) and len(
            _root_rotation_escape_hypotheses(
                TemporalClipConfig(
                    motion_root_rotation_enabled=True,
                    motion_root_rotation_axes=axes,
                    motion_root_rotation_escape_axes=escape_axes,
                    motion_root_rotation_limit_deg=MOTION_ROOT_ROTATION_LIMIT_DEG,
                    motion_root_rotation_escape_angles_deg=MOTION_ROOT_ROTATION_ESCAPE_ANGLES_DEG,
                )
            )
        ),
        "coarseStepDeg": float(MOTION_ROOT_ROTATION_COARSE_STEP_DEG),
        "refineStepDeg": float(MOTION_ROOT_ROTATION_REFINE_STEP_DEG),
        "angle_evaluations": [],
    }
    all_trials = []

    def _pose(root_values):
        candidate = dict(accumulated)
        candidate[MOTION_ROOT_ROTATION_KEY] = dict(root_values)
        return candidate

    baseline_pose = _pose(best_root)
    best_score, _baseline_result, baseline_dt = _score_multibone_pose(
        frame_index,
        baseline_pose,
        f"f{frame_index:02d} {progress_desc or 'motion root rotation'} baseline",
        False,
        ik_targets_override=ik_targets_override,
        ik_bones_override=ik_bones_override,
    )
    all_trials.append(
        {
            "region": "baseline",
            "rootRotation": dict(best_root),
            "score": float(best_score),
        }
    )

    def _evaluate_values(values, region, candidate_values):
        nonlocal best_root, best_score
        entries = []
        metadata = []
        for axis, value in candidate_values:
            candidate_root = dict(values)
            if axis == "combined":
                candidate_root.update(
                    {
                        root_axis: float(
                            min(
                                limits[root_axis],
                                max(-limits[root_axis], float(root_value)),
                            )
                        )
                        for root_axis, root_value in dict(value).items()
                        if root_axis in limits
                    }
                )
                label_value = dict(candidate_root)
            else:
                candidate_root[axis] = float(
                    min(limits[axis], max(-limits[axis], float(value)))
                )
                label_value = f"{candidate_root[axis]:+.1f}deg"
            entries.append(
                (
                    _pose(candidate_root),
                    f"f{frame_index:02d} {progress_desc or 'motion root rotation'} "
                    f"{region} {axis} {label_value}",
                    False,
                )
            )
            metadata.append((axis, value, candidate_root))
        if not entries:
            return
        scored = _score_multibone_pose_batch(
            frame_index,
            entries,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
            incumbent_score=best_score,
            proxy_stage="root_rotation",
        )
        for (axis, value, candidate_root), (score, _result, elapsed) in zip(
            metadata,
            scored,
        ):
            row = {
                "region": region,
                "axis": axis,
                "valueDeg": None if axis == "combined" else float(value),
                "valuesDeg": dict(value) if axis == "combined" else None,
                "rootRotation": dict(candidate_root),
                "score": float(score),
                "improvement": float(score - best_score),
                "dt_score": float(elapsed),
            }
            all_trials.append(row)
            timings["angle_evaluations"].append(row)
            if float(score) > float(best_score) + 1e-9:
                best_score = float(score)
                best_root = dict(candidate_root)

    # The advisor supplies a bounded, diverse global shortlist. These are
    # still sent through the exact worker scorer; its cheap SDF is never used
    # as an acceptance authority.
    if GPU_POSE_ADVISOR_ENABLED and GPU_POSE_ADVISOR_ROOT_ENABLED and not refinement_only:
        advisor = globals().get("gpu_pose_advisor")
        if advisor is None:
            raise RuntimeError(
                "GPU_POSE_ADVISOR_ENABLED is true, but the persistent advisor was not initialized"
            )
        advisor_hypotheses = advisor.root_hypotheses(
            frame_index,
            accumulated,
            translation_limits={"forward": 0.0, "lateral": 0.0, "vertical": 0.0},
            translation_axes=(),
            rotation_limit_deg=MOTION_ROOT_ROTATION_LIMIT_DEG,
            rotation_axes=axes,
        )
        _evaluate_values(
            best_root,
            "gpu_advisor_root_hypotheses",
            [("combined", row["rotation"]) for row in advisor_hypotheses],
        )
        timings["gpuAdvisorRootHypothesisCount"] = len(advisor_hypotheses)

    if not refinement_only and MOTION_ROOT_ROTATION_ESCAPE_ENABLED:
        escape_values = []
        base_root = dict(best_root)
        for hypothesis in _root_rotation_escape_hypotheses(
            TemporalClipConfig(
                motion_root_rotation_enabled=True,
                motion_root_rotation_axes=axes,
                motion_root_rotation_escape_axes=escape_axes,
                motion_root_rotation_limit_deg=MOTION_ROOT_ROTATION_LIMIT_DEG,
                motion_root_rotation_escape_angles_deg=MOTION_ROOT_ROTATION_ESCAPE_ANGLES_DEG,
            )
        ):
            candidate_root = dict(base_root)
            for axis in escape_axes:
                candidate_root[axis] = float(
                    min(
                        limits[axis],
                        max(
                            -limits[axis],
                            base_root[axis] + hypothesis.get(axis, 0.0),
                        ),
                    )
                )
            escape_values.append(("combined", candidate_root))

        # First rank rigid attitudes without changing local bones. Then give
        # only the best few hypotheses a short, order-driven local relaxation.
        # This prevents the standing bind pose from vetoing a correct lying
        # orientation while keeping the escape wave bounded for custom rigs.
        escape_entries = [
            (
                _pose(candidate_root),
                f"f{frame_index:02d} {progress_desc or 'motion root rotation'} escape",
                False,
            )
            for _axis, candidate_root in escape_values
        ]
        escape_scored = _score_multibone_pose_batch(
            frame_index,
            escape_entries,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
            incumbent_score=best_score,
            proxy_stage="root_hypothesis",
        )
        escape_rows = []
        for (_axis, candidate_root), (score, _result, elapsed) in zip(
            escape_values,
            escape_scored,
        ):
            row = {
                "region": "escape",
                "axis": "combined",
                "valueDeg": None,
                "valuesDeg": dict(candidate_root),
                "rootRotation": dict(candidate_root),
                "score": float(score),
                "improvement": float(score - best_score),
                "dt_score": float(elapsed),
                "candidate": _pose(candidate_root),
            }
            escape_rows.append(row)
            all_trials.append({key: value for key, value in row.items() if key != "candidate"})
            timings["angle_evaluations"].append(
                {key: value for key, value in row.items() if key != "candidate"}
            )
        escape_rows.sort(key=lambda row: float(row["score"]), reverse=True)
        escape_top_rows = escape_rows[:MOTION_ROOT_ROTATION_ESCAPE_TOP_K]
        relaxation_rows = []
        if MOTION_ROOT_ROTATION_ESCAPE_RELAX_ENABLED:
            ordered_relax_bones = list(relax_bones or ())
            ordered_relax_bones = [
                str(bone)
                for bone in ordered_relax_bones
                if str(bone)
                not in {
                    MOTION_ROOT_KEY,
                    LEGACY_BODY_TRANSLATION_KEY,
                    MOTION_ROOT_ROTATION_KEY,
                }
            ][: max(0, MOTION_ROOT_ROTATION_ESCAPE_RELAX_BONE_COUNT)]
            relax_axes = tuple(axis for axis in SEARCH_AXES if axis in {"x", "y", "z"})
            for seed_index, seed_row in enumerate(escape_top_rows):
                relaxed_pose = copy.deepcopy(seed_row["candidate"])
                relaxed_score = float(seed_row["score"])
                accepted = []
                relax_trials = 0
                for relax_round in range(MOTION_ROOT_ROTATION_ESCAPE_RELAX_ROUNDS):
                    step = (
                        MOTION_ROOT_ROTATION_ESCAPE_RELAX_STEP_DEG
                        if relax_round == 0
                        else MOTION_ROOT_ROTATION_ESCAPE_RELAX_REFINE_STEP_DEG
                    )
                    for bone in ordered_relax_bones:
                        center = _multi_bone_euler_deg(relaxed_pose, bone)
                        lo, hi = range_for(bone)
                        candidates = []
                        metadata = []
                        for axis in relax_axes:
                            for direction in (-1.0, 1.0):
                                value = float(
                                    min(
                                        hi,
                                        max(
                                            lo,
                                            float(center[axis]) + direction * step,
                                        ),
                                    )
                                )
                                if abs(value - float(center[axis])) <= 1e-8:
                                    continue
                                euler = dict(center)
                                euler[axis] = value
                                candidate = _multi_bone_pose_with_euler(
                                    relaxed_pose,
                                    bone,
                                    euler,
                                )
                                candidates.append(
                                    (
                                        candidate,
                                        f"f{frame_index:02d} root escape relax "
                                        f"seed {seed_index} {bone} {axis} {value:+.1f}",
                                        False,
                                    )
                                )
                                metadata.append((axis, value, candidate))
                        if not candidates:
                            continue
                        scored = _score_multibone_pose_batch(
                            frame_index,
                            candidates,
                            ik_targets_override=ik_targets_override,
                            ik_bones_override=ik_bones_override,
                            incumbent_score=relaxed_score,
                            proxy_stage="root_relaxation",
                        )
                        relax_trials += len(scored)
                        best_local = None
                        for (axis, value, candidate), (score, _result, elapsed) in zip(
                            metadata,
                            scored,
                        ):
                            row = {
                                "region": "escape_relax",
                                "axis": axis,
                                "bone": bone,
                                "seed": int(seed_index),
                                "valueDeg": float(value),
                                "score": float(score),
                                "improvement": float(score - relaxed_score),
                                "dt_score": float(elapsed),
                            }
                            all_trials.append(row)
                            timings["angle_evaluations"].append(row)
                            if float(score) > float(relaxed_score) + 1e-9:
                                if best_local is None or float(score) > float(best_local["score"]):
                                    best_local = {
                                        "axis": axis,
                                        "value": float(value),
                                        "score": float(score),
                                        "candidate": candidate,
                                    }
                        if best_local is not None:
                            relaxed_pose = copy.deepcopy(best_local["candidate"])
                            relaxed_score = float(best_local["score"])
                            accepted.append(
                                {
                                    "bone": bone,
                                    "axis": best_local["axis"],
                                    "valueDeg": best_local["value"],
                                }
                            )
                rotation_entry = _motion_root_rotation_pose_entry(relaxed_pose)
                relaxation_rows.append(
                    {
                        **seed_row,
                        "candidate": relaxed_pose,
                        "rootRotation": dict(rotation_entry),
                        "score": float(relaxed_score),
                        "improvement": float(relaxed_score - best_score),
                        "relaxSeed": int(seed_index),
                        "relaxBones": list(ordered_relax_bones),
                        "relaxTrials": int(relax_trials),
                        "relaxAccepted": accepted,
                    }
                )
        ranked_escape_rows = relaxation_rows or escape_top_rows
        best_escape = max(ranked_escape_rows, key=lambda row: float(row["score"]), default=None)
        if best_escape is not None:
            best_score = float(best_escape["score"])
            best_root = dict(best_escape["rootRotation"])
        timings["escapeTopK"] = [
            {
                key: value
                for key, value in row.items()
                if key != "candidate"
            }
            for row in ranked_escape_rows
        ]

    for region, step in (
        ("coarse", MOTION_ROOT_ROTATION_COARSE_STEP_DEG),
        ("refine", MOTION_ROOT_ROTATION_REFINE_STEP_DEG),
    ):
        if region == "refine" or not refinement_only:
            for axis in axes:
                current = float(best_root[axis])
                values = [
                    (axis, current - float(step)),
                    (axis, current + float(step)),
                ]
                if region == "coarse":
                    values.extend(
                        (
                            (axis, -limits[axis]),
                            (axis, limits[axis]),
                        )
                    )
                _evaluate_values(best_root, region, values)
    if live:
        _score_multibone_pose(
            frame_index,
            _pose(best_root),
            f"f{frame_index:02d} {progress_desc or 'motion root rotation'} best preview",
            True,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
    timings["chosenRootRotation"] = dict(best_root)
    timings["bestScore"] = float(best_score)
    timings["baselineSeconds"] = float(baseline_dt)
    return dict(best_root), float(best_score), all_trials, timings


def scan_motion_root_rigid(
    frame_index,
    accumulated,
    progress_desc=None,
    live_preview=None,
    ik_targets_override=None,
    ik_bones_override=None,
    refinement_only=False,
):
    """Search translation and camera-relative attitude as one rigid state.

    Translation and rotation are still represented by separate pose keys for
    compatibility with the worker, but this search never accepts one without
    scoring the other in the same candidate. A small translation beam is
    crossed with the broad rotation escape library before local refinement.
    This is the important distinction from merely running two coordinate
    scans one after the other: a lying/rolled body can keep the translation
    that made the attitude useful instead of having it discarded by the next
    root pass.
    """
    live = LIVE_PREVIEW if live_preview is None else bool(live_preview)
    if not MOTION_ROOT_ENABLED or not MOTION_ROOT_AXES:
        raise RuntimeError("rigid root scan requires motion root translation")
    if not MOTION_ROOT_ROTATION_ENABLED or not MOTION_ROOT_ROTATION_AXES:
        raise RuntimeError("rigid root scan requires motion root rotation")

    translation_axes = tuple(MOTION_ROOT_AXES)
    rotation_axes = tuple(MOTION_ROOT_ROTATION_AXES)
    rotation_escape_axes = tuple(MOTION_ROOT_ROTATION_ESCAPE_AXES)
    translation_limits = _motion_root_limits()
    rotation_limits = {
        axis: float(MOTION_ROOT_ROTATION_LIMIT_DEG)
        for axis in ("camera_forward", "camera_right", "camera_up")
    }
    base_translation = _motion_root_pose_entry(accumulated)
    base_rotation = _motion_root_rotation_pose_entry(accumulated)
    best_translation = {
        axis: float(
            min(translation_limits[axis], max(-translation_limits[axis], base_translation.get(axis, 0.0)))
        )
        if axis in translation_axes
        else 0.0
        for axis in ("forward", "lateral", "vertical")
    }
    best_rotation = {
        axis: float(
            min(rotation_limits[axis], max(-rotation_limits[axis], base_rotation.get(axis, 0.0)))
        )
        if axis in rotation_axes
        else 0.0
        for axis in ("camera_forward", "camera_right", "camera_up")
    }
    all_trials = []
    timings = {
        "mode": "motion_root_rigid",
        "translationAxes": list(translation_axes),
        "rotationAxes": list(rotation_axes),
        "rotationEscapeAxes": list(rotation_escape_axes),
        "angle_evaluations": [],
    }

    def make_pose(translation, rotation):
        candidate = copy.deepcopy(accumulated)
        candidate[MOTION_ROOT_KEY] = dict(translation)
        candidate[MOTION_ROOT_ROTATION_KEY] = dict(rotation)
        return candidate

    def dedupe_pairs(pairs):
        result = []
        seen = set()
        for translation, rotation in pairs:
            key = (
                tuple((axis, round(float(translation.get(axis, 0.0)), 8)) for axis in ("forward", "lateral", "vertical")),
                tuple((axis, round(float(rotation.get(axis, 0.0)), 6)) for axis in ("camera_forward", "camera_right", "camera_up")),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append((dict(translation), dict(rotation)))
        return result

    def score_pairs(pairs, region):
        pairs = dedupe_pairs(pairs)
        entries = [
            (
                make_pose(translation, rotation),
                f"f{frame_index:02d} {progress_desc or 'rigid root'} {region}",
                False,
            )
            for translation, rotation in pairs
        ]
        if not entries:
            return []
        scored = _score_multibone_pose_batch(
            frame_index,
            entries,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
            proxy_stage="rigid_root",
        )
        rows = []
        for (translation, rotation), (score, _result, elapsed) in zip(pairs, scored):
            row = {
                "region": region,
                "translation": dict(translation),
                "rotation": dict(rotation),
                "score": float(score),
                "dt_score": float(elapsed),
            }
            rows.append(row)
            all_trials.append(row)
            timings["angle_evaluations"].append(row)
        return rows

    baseline_start = time.perf_counter()
    baseline_rows = score_pairs([(best_translation, best_rotation)], "baseline")
    if not baseline_rows:
        raise RuntimeError("rigid root scan produced no baseline candidate")
    best_score = float(baseline_rows[0]["score"])
    best_pair = (dict(best_translation), dict(best_rotation))
    timings["baselineSeconds"] = time.perf_counter() - baseline_start

    advisor_rows = []
    if GPU_POSE_ADVISOR_ENABLED and GPU_POSE_ADVISOR_ROOT_ENABLED and not refinement_only:
        advisor = globals().get("gpu_pose_advisor")
        if advisor is None:
            raise RuntimeError(
                "GPU_POSE_ADVISOR_ENABLED is true, but the persistent advisor was not initialized"
            )
        advisor_hypotheses = advisor.root_hypotheses(
            frame_index,
            accumulated,
            translation_limits=translation_limits,
            translation_axes=translation_axes,
            rotation_limit_deg=MOTION_ROOT_ROTATION_LIMIT_DEG,
            rotation_axes=rotation_axes,
        )
        advisor_rows = score_pairs(
            [
                (row["translation"], row["rotation"])
                for row in advisor_hypotheses
            ],
            "gpu_advisor_root_hypotheses",
        )
        timings["gpuAdvisorRootHypothesisCount"] = len(advisor_hypotheses)
        for row in advisor_rows:
            if float(row["score"]) > best_score + 1e-9:
                best_score = float(row["score"])
                best_translation = dict(row["translation"])
                best_rotation = dict(row["rotation"])
                best_pair = (dict(best_translation), dict(best_rotation))

    translation_pairs = [(best_translation, best_rotation)]
    translation_pairs.extend(
        (row["translation"], row["rotation"])
        for row in sorted(advisor_rows, key=lambda item: float(item["score"]), reverse=True)
    )
    if not refinement_only:
        for axis in translation_axes:
            step = float(MOTION_ROOT_COARSE_STEP_BODY_LENGTHS)
            for raw in (
                best_translation[axis] - step,
                best_translation[axis] + step,
                -translation_limits[axis],
                translation_limits[axis],
            ):
                candidate = dict(best_translation)
                candidate[axis] = float(
                    min(translation_limits[axis], max(-translation_limits[axis], raw))
                )
                translation_pairs.append((candidate, best_rotation))
    translation_rows = score_pairs(translation_pairs, "translation_beam")
    translation_rows.sort(key=lambda row: float(row["score"]), reverse=True)
    translation_top_k = max(2, int(MOTION_ROOT_ROTATION_ESCAPE_TOP_K))
    translation_rows = translation_rows[:translation_top_k]
    timings["translationBeamTopK"] = translation_top_k

    translation_beam = [
        (row["translation"], row["rotation"])
        for row in translation_rows
    ] or [(best_translation, best_rotation)]
    best_translation = dict(translation_beam[0][0])
    best_rotation = dict(translation_beam[0][1])
    best_score = float(translation_rows[0]["score"]) if translation_rows else best_score

    rotation_pairs = [(best_translation, best_rotation)]
    if not refinement_only:
        for axis in rotation_axes:
            step = float(MOTION_ROOT_ROTATION_COARSE_STEP_DEG)
            for raw in (
                best_rotation[axis] - step,
                best_rotation[axis] + step,
                -rotation_limits[axis],
                rotation_limits[axis],
            ):
                candidate = dict(best_rotation)
                candidate[axis] = float(
                    min(rotation_limits[axis], max(-rotation_limits[axis], raw))
                )
                rotation_pairs.append((best_translation, candidate))
        if MOTION_ROOT_ROTATION_ESCAPE_ENABLED and rotation_escape_axes:
            escape_config = TemporalClipConfig(
                motion_root_rotation_enabled=True,
                motion_root_rotation_axes=rotation_axes,
                motion_root_rotation_escape_axes=rotation_escape_axes,
                motion_root_rotation_limit_deg=MOTION_ROOT_ROTATION_LIMIT_DEG,
                motion_root_rotation_escape_angles_deg=MOTION_ROOT_ROTATION_ESCAPE_ANGLES_DEG,
            )
            for hypothesis in _root_rotation_escape_hypotheses(escape_config):
                candidate = dict(best_rotation)
                for axis in rotation_escape_axes:
                    candidate[axis] = float(
                        min(
                            rotation_limits[axis],
                            max(
                                -rotation_limits[axis],
                                best_rotation.get(axis, 0.0) + hypothesis.get(axis, 0.0),
                            ),
                        )
                    )
                rotation_pairs.append((best_translation, candidate))
    rotation_rows = score_pairs(rotation_pairs, "rotation_beam")
    rotation_rows.sort(key=lambda row: float(row["score"]), reverse=True)
    rotation_rows = rotation_rows[: max(2, int(MOTION_ROOT_ROTATION_ESCAPE_TOP_K))]
    timings["rotationBeamTopK"] = len(rotation_rows)

    coupled_pairs = [
        (translation, rotation)
        for translation_row in translation_rows
        for rotation_row in rotation_rows
        for translation, rotation in [
            (translation_row["translation"], rotation_row["rotation"])
        ]
    ]
    coupled_rows = score_pairs(coupled_pairs, "coupled_beam")
    if coupled_rows:
        best_row = max(coupled_rows, key=lambda row: float(row["score"]))
        if float(best_row["score"]) > best_score + 1e-9:
            best_score = float(best_row["score"])
            best_translation = dict(best_row["translation"])
            best_rotation = dict(best_row["rotation"])
    timings["coupledCandidateCount"] = len(coupled_rows)

    local_stages = (
        (
            "coarse_refine",
            float(MOTION_ROOT_COARSE_STEP_BODY_LENGTHS),
            float(MOTION_ROOT_ROTATION_COARSE_STEP_DEG),
        ),
        (
            "refine",
            float(MOTION_ROOT_REFINE_STEP_BODY_LENGTHS),
            float(MOTION_ROOT_ROTATION_REFINE_STEP_DEG),
        ),
    ) if not refinement_only else (
        (
            "refine",
            float(MOTION_ROOT_REFINE_STEP_BODY_LENGTHS),
            float(MOTION_ROOT_ROTATION_REFINE_STEP_DEG),
        ),
    )
    for region, translation_step, rotation_step in local_stages:
        local_pairs = []
        for axis in translation_axes:
            for direction in (-1.0, 1.0):
                candidate = dict(best_translation)
                candidate[axis] = float(
                    min(
                        translation_limits[axis],
                        max(-translation_limits[axis], candidate[axis] + direction * translation_step),
                    )
                )
                local_pairs.append((candidate, best_rotation))
        for axis in rotation_axes:
            for direction in (-1.0, 1.0):
                candidate = dict(best_rotation)
                candidate[axis] = float(
                    min(
                        rotation_limits[axis],
                        max(-rotation_limits[axis], candidate[axis] + direction * rotation_step),
                    )
                )
                local_pairs.append((best_translation, candidate))
        local_rows = score_pairs(local_pairs, region)
        best_local = max(local_rows, key=lambda row: float(row["score"]), default=None)
        if best_local is not None and float(best_local["score"]) > best_score + 1e-9:
            best_score = float(best_local["score"])
            best_translation = dict(best_local["translation"])
            best_rotation = dict(best_local["rotation"])

    timings["chosenTranslation"] = dict(best_translation)
    timings["chosenRotation"] = dict(best_rotation)
    timings["bestScore"] = float(best_score)
    if live:
        _score_multibone_pose(
            frame_index,
            make_pose(best_translation, best_rotation),
            f"f{frame_index:02d} {progress_desc or 'rigid root'} best preview",
            True,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
    return (
        dict(best_translation),
        dict(best_rotation),
        float(best_score),
        all_trials,
        timings,
    )


def _bone_twist_policy(bone):
    policy = str(BONE_TWIST_OVERRIDES.get(str(bone), BONE_TWIST_POLICY)).lower()
    if policy not in {"adaptive", "include", "exclude"}:
        raise ValueError(f"unsupported bone twist policy for {bone!r}: {policy!r}")
    return policy


def scan_bone_rotation_vector(
    frame_index,
    bone,
    accumulated,
    *,
    step_deg=None,
    progress_desc=None,
    live_preview=None,
    ik_targets_override=None,
    ik_bones_override=None,
):
    """Search a rest-space swing/twist shell and continue its best directions."""
    live = LIVE_PREVIEW if live_preview is None else bool(live_preview)
    vector = BONE_VECTORS.get(str(bone))
    if vector is None:
        raise ValueError(f"rest-space bone vector is missing for {bone!r}")
    lo, hi = map(float, range_for(bone))
    step = float(
        ROTATION_VECTOR_PROBE_STEP_DEG if step_deg is None else step_deg
    )
    policy = _bone_twist_policy(bone)
    base_quaternion = pose_value_to_quaternion(accumulated.get(bone, {}))
    max_abs_deg = max(abs(lo), abs(hi))
    baseline_score, _baseline_result, baseline_dt = _score_multibone_pose(
        frame_index,
        dict(accumulated),
        f"f{frame_index:02d} {progress_desc or bone} vector baseline",
        False,
        ik_targets_override=ik_targets_override,
        ik_bones_override=ik_bones_override,
        proxy_stage="rotation_vector",
    )
    all_trials = []
    timings = {
        "mode": "rotation_vector",
        "probeCount": int(ROTATION_VECTOR_PROBE_COUNT),
        "probeStepDeg": float(step),
        "directionalContinuation": bool(DIRECTIONAL_CONTINUATION_ENABLED),
        "angle_evaluations": [],
        "baselineScore": float(baseline_score),
        "baselineSeconds": float(baseline_dt),
        "boundaryLimited": False,
    }
    advisor_info = {"used": False, "reason": "disabled"}
    shell = []
    advisor = globals().get("gpu_pose_advisor")
    if GPU_POSE_ADVISOR_ENABLED and GPU_POSE_ADVISOR_DIRECTION_ENABLED:
        if advisor is None:
            raise RuntimeError(
                "GPU_POSE_ADVISOR_ENABLED is true, but the persistent advisor was not initialized"
            )
        shell, advisor_info = advisor.rotation_proposals(
            frame_index,
            accumulated,
            str(bone),
            base_quaternion,
            step_deg=step,
            max_abs_deg=max_abs_deg,
            bone_vector=vector,
            twist_policy=policy,
        )
    if not shell:
        if advisor_info.get("mode") == "skip_coarse":
            # A visually unsupported bone should not be kicked by an
            # arbitrary coarse shell.  It remains available to the existing
            # multi-bone probe and near-refinement stages later in this pass.
            timings["coarseSkipped"] = True
            timings["skipReason"] = advisor_info.get("reason")
            return (
                quaternion_pose_entry(base_quaternion, twist_policy=policy),
                float(baseline_score),
                all_trials,
                timings,
            )
        if GPU_POSE_ADVISOR_ENABLED and not GPU_POSE_ADVISOR_FALLBACK_ROTATION_VECTORS:
            timings["advisor"] = advisor_info
            timings["boundaryLimited"] = True
            return (
                quaternion_pose_entry(base_quaternion, twist_policy="exclude"),
                float(baseline_score),
                all_trials,
                timings,
            )
        shell = rotation_vector_proposals(
            base_quaternion,
            vector,
            step,
            ROTATION_VECTOR_PROBE_COUNT,
            max_abs_deg,
            include_twist=policy != "exclude",
            twist_policy=policy,
        )
    timings["advisor"] = advisor_info
    if not shell:
        timings["boundaryLimited"] = True
        return (
            quaternion_pose_entry(base_quaternion, twist_policy="exclude"),
            float(baseline_score),
            all_trials,
            timings,
        )

    def score_proposals(proposals, region):
        entries = []
        for proposal in proposals:
            candidate_pose = dict(accumulated)
            candidate_pose[bone] = quaternion_pose_entry(
                proposal["quaternion"],
                twist_policy=proposal["twistPolicy"],
            )
            entries.append(
                (
                    candidate_pose,
                    f"f{frame_index:02d} {progress_desc or bone} vector "
                    f"{region} {proposal['kind']} {proposal['angleDeg']:+.1f}",
                    False,
                )
            )
        scored = _score_multibone_pose_batch(
            frame_index,
            entries,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
            incumbent_score=baseline_score,
            proxy_stage="rotation_vector",
        )
        rows = []
        for proposal, (score, result, elapsed) in zip(proposals, scored):
            row = {
                "region": str(region),
                "kind": str(proposal["kind"]),
                "direction": int(proposal["direction"]),
                "axis": list(proposal["axis"]),
                "angleDeg": float(proposal["angleDeg"]),
                "twistPolicy": str(proposal["twistPolicy"]),
                "hybridScore": float(score),
                "improvement": float(score - baseline_score),
                "dt_score": float(elapsed),
                "semanticCosine": result.get("semanticCosine"),
                "depthIoU": result.get("depthIoU"),
                "hybridComponents": result.get("hybridComponents"),
            }
            rows.append((float(score), proposal, row))
            all_trials.append(row)
            timings["angle_evaluations"].append(row)
        return rows

    scored_shell = score_proposals(shell, "shell")
    best_score = float(baseline_score)
    best_proposal = None
    for score, proposal, _row in scored_shell:
        if score > best_score + 1e-9:
            best_score = score
            best_proposal = proposal

    # Continue the best few directions even when their first sample is weak;
    # this bounded valley-crossing probe is the point of the new search stage.
    if DIRECTIONAL_CONTINUATION_ENABLED and scored_shell:
        ranked = sorted(scored_shell, key=lambda item: item[0], reverse=True)
        chosen_directions = []
        seen = set()
        for score, proposal, _row in ranked:
            key = int(proposal["direction"])
            if key in seen:
                continue
            if (
                score - baseline_score < DIRECTIONAL_MIN_IMPROVEMENT
                and chosen_directions
            ):
                continue
            seen.add(key)
            chosen_directions.append(proposal)
            if len(chosen_directions) >= DIRECTIONAL_TOP_K:
                break
        if not chosen_directions:
            chosen_directions = [ranked[0][1]]
        for direction_proposal in chosen_directions:
            for continuation_index in range(1, DIRECTIONAL_MAX_STEPS):
                continuation_angle = step * (
                    DIRECTIONAL_STEP_MULTIPLIER ** continuation_index
                )
                proposal = continuation_proposal(
                    base_quaternion,
                    direction_proposal["axis"],
                    continuation_angle,
                    max_abs_deg,
                    kind=direction_proposal["kind"],
                    direction=direction_proposal["direction"],
                    twist_policy=direction_proposal["twistPolicy"],
                )
                if proposal is None:
                    timings["boundaryLimited"] = True
                    break
                scored = score_proposals([proposal], f"continue_{continuation_index}")
                if scored and scored[0][0] > best_score + 1e-9:
                    best_score = scored[0][0]
                    best_proposal = proposal

    if best_proposal is None:
        best_entry = quaternion_pose_entry(base_quaternion, twist_policy="exclude")
    else:
        best_entry = quaternion_pose_entry(
            best_proposal["quaternion"],
            twist_policy=best_proposal["twistPolicy"],
        )
    if live:
        preview_pose = dict(accumulated)
        preview_pose[bone] = best_entry
        _score_multibone_pose(
            frame_index,
            preview_pose,
            f"f{frame_index:02d} {progress_desc or bone} vector best preview",
            True,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
            proxy_stage="rotation_vector",
        )
    timings["chosenKind"] = None if best_proposal is None else best_proposal["kind"]
    timings["chosenAngleDeg"] = (
        None if best_proposal is None else float(best_proposal["angleDeg"])
    )
    timings["bestScore"] = float(best_score)
    return best_entry, float(best_score), all_trials, timings


def scan_bone(
    frame_index,
    bone,
    accumulated,
    coarse_step=None,
    refine_step=None,
    progress_desc=None,
    live_preview=None,
    axes=None,
    ik_targets_override=None,
    ik_bones_override=None,
    refinement_only=False,
    relax_bones=None,
):
    """Search bone rotation. Default compound = simultaneous local Euler x+y+z."""
    if bone == MOTION_ROOT_ROTATION_KEY:
        return scan_motion_root_rotation(
            frame_index,
            accumulated,
            progress_desc=progress_desc,
            live_preview=live_preview,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
            refinement_only=refinement_only,
            relax_bones=relax_bones,
        )
    if bone in {MOTION_ROOT_KEY, LEGACY_BODY_TRANSLATION_KEY}:
        return scan_motion_root(
            frame_index,
            accumulated,
            progress_desc=progress_desc,
            live_preview=live_preview,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
            refinement_only=refinement_only,
        )
    live = LIVE_PREVIEW if live_preview is None else live_preview
    coarse_step = float(COARSE_STEP_DEG if coarse_step is None else coarse_step)
    refine_step = float(REFINE_STEP_DEG if refine_step is None else refine_step)
    axes = [a.lower() for a in (axes or SEARCH_AXES)]
    mode = str(MULTI_AXIS_MODE).lower()
    lo, hi = range_for(bone)
    target = ANIMATION_TARGET_FRAMES / f"{frame_index:02d}.png"
    target_depth = TARGET_DEPTH / f"{frame_index:02d}.png"
    all_trials = []
    timings = {"mode": mode, "angle_evaluations": [], "axesTried": list(axes)}

    if (
        ROTATION_VECTOR_SEARCH_ENABLED
        and not refinement_only
        and not (IK_ENABLED and IK_MODE.lower() == "replace_all")
    ):
        return scan_bone_rotation_vector(
            frame_index,
            bone,
            accumulated,
            step_deg=coarse_step,
            progress_desc=progress_desc,
            live_preview=live,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )

    def _clip(deg):
        return float(min(hi, max(lo, deg)))

    def _score_euler_deg(euler_deg, region, incumbent_score=None):
        pose = dict(accumulated)
        pose[bone] = {
            "x": math.radians(float(euler_deg.get("x", 0.0))),
            "y": math.radians(float(euler_deg.get("y", 0.0))),
            "z": math.radians(float(euler_deg.get("z", 0.0))),
        }
        caption = (
            f"f{frame_index:02d} {progress_desc or bone}  "
            f"XYZ {region}  "
            f"({euler_deg.get('x', 0):.0f},{euler_deg.get('y', 0):.0f},{euler_deg.get('z', 0):.0f})"
        )
        req = {
            "cmd": "score",
            "target": str(target),
            "targetDepth": str(target_depth),
            "angles": pose,
            "scoreMode": SCORE_MODE,
            "depthMaxDist": DEPTH_MAX_DIST,
            "colorMaxDist": COLOR_MAX_DIST,
            "targetPartBoxes": PART_BOXES_BY_FRAME.get(frame_index, []),
            "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,
            "threshold": 0.08,
        }
        _attach_motion_root_request(req, pose)
        configure_score_request(
            req,
            frame_index,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
        if live:
            req["previewOut"] = str(PREVIEW_PATH)
            req["previewRgb"] = True
            req["previewCaption"] = caption
        if SEMANTIC_ONLY:
            req["scoreMode"] = SCORE_MODE
            req["semanticOnly"] = True
            req["semanticModel"] = SEMANTIC_MODEL_ID
            req["previewRgb"] = True
            req["semanticCandidateOut"] = str(_semantic_candidate_dir / (
                f"f{frame_index:02d}_{bone}_{region}_"
                f"x{euler_deg.get('x', 0.0):+.1f}_z{euler_deg.get('z', 0.0):+.1f}.png"
            ))
            view_paths = semantic_paths(frame_index, f"{bone}_{region}_x{euler_deg.get('x', 0.0):+.1f}_z{euler_deg.get('z', 0.0):+.1f}")
            req["semanticMultiview"] = bool(SEMANTIC_MULTIVIEW)
            req["semanticViewAnglesDeg"] = list(SEMANTIC_VIEW_ANGLES_DEG)
            req["semanticViewElevationsDeg"] = list(SEMANTIC_VIEW_ELEVATIONS_DEG)
            req["semanticViewOuts"] = [str(path) for path in view_paths]
            Path(req["semanticCandidateOut"]).unlink(missing_ok=True)
            for path in view_paths:
                path.unlink(missing_ok=True)
        t0 = time.perf_counter()
        result = worker.request(req)
        dt = time.perf_counter() - t0
        if not result.get("ok"):
            raise RuntimeError(result)
        triage_rejected = _triage_reject(result) if SEMANTIC_ONLY else False
        if triage_rejected:
            hybrid = float(result["iou"])
        elif SEMANTIC_ONLY:
            apply_anatomical_candidate_features(result, frame_index, req)
            bound_rejected = _semantic_bound_reject(result, incumbent_score)
            if bound_rejected:
                hybrid = float(result["iou"])
            else:
                candidate_path = Path(req["semanticCandidateOut"])
                if not candidate_path.is_file() or candidate_path.stat().st_size <= 0:
                    raise RuntimeError(f"semantic candidate render was not written: {candidate_path}")
                candidate_paths = view_paths if SEMANTIC_MULTIVIEW else [candidate_path]
                if any(not path.is_file() for path in candidate_paths):
                    raise RuntimeError(f"semantic multiview render set was not written: {candidate_paths}")
                score_semantic_candidate(
                    frame_index,
                    candidate_paths,
                    result,
                    incumbent_score,
                )
                hybrid = float(result["iou"])
        else:
            apply_anatomical_candidate_features(result, frame_index, req)
            hybrid = apply_nonsemantic_hybrid_score(result)
        hybrid = float(result["iou"])
        if live:
            show_live_preview(
                caption,
                hybrid,
                result.get("semanticCosine"),
                result.get("depthIoU"),
                result.get("textCosine"),
                result.get("negativeTextCosine"),
                result,
            )
        all_trials.append(("xyz", dict(euler_deg), hybrid))
        timings["angle_evaluations"].append(
            {
                "eulerDeg": dict(euler_deg),
                "hybridScore": hybrid,
                "semanticCosine": result.get("semanticCosine"),
                "semanticLayerCosines": result.get("semanticLayerCosines"),
                "depthIoU": result.get("depthIoU"),
                "textCosine": result.get("textCosine"),
                "negativeTextCosine": result.get("negativeTextCosine"),
                 "negativeTextAvoidance": result.get("negativeTextAvoidance"),
                 "workerIoU": result.get("workerIoU"),
                 "anatomicalPartIoU": result.get("anatomicalPartIoU"),
                 "anatomicalFeatureDistance": result.get("anatomicalFeatureDistance"),
                 "hybridComponents": result.get("hybridComponents"),
                 "zoneDiagnostics": result.get("zoneDiagnostics"),
                "region": region,
                "dt_score": dt,
            }
        )
        return hybrid

    def _score_euler_batch(eulers, region):
        """Batch independent Euler proposals through the persistent workers."""
        entries = []
        for euler_deg in eulers:
            pose = dict(accumulated)
            pose[bone] = {
                "x": math.radians(float(euler_deg.get("x", 0.0))),
                "y": math.radians(float(euler_deg.get("y", 0.0))),
                "z": math.radians(float(euler_deg.get("z", 0.0))),
            }
            caption = (
                f"f{frame_index:02d} {progress_desc or bone}  XYZ {region} "
                f"({euler_deg.get('x', 0):.0f},{euler_deg.get('y', 0):.0f},{euler_deg.get('z', 0):.0f})"
            )
            entries.append((pose, caption, False))
        scored = _score_multibone_pose_batch(
            frame_index,
            entries,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
            incumbent_score=best_score,
            proxy_stage="xyz_scan",
        )
        values = []
        for euler_deg, (hybrid, result, dt) in zip(eulers, scored):
            all_trials.append(("xyz", dict(euler_deg), float(hybrid)))
            timings["angle_evaluations"].append({
                "eulerDeg": dict(euler_deg),
                "hybridScore": float(hybrid),
                "semanticCosine": result.get("semanticCosine"),
                "semanticLayerCosines": result.get("semanticLayerCosines"),
                "depthIoU": result.get("depthIoU"),
                "workerIoU": result.get("workerIoU"),
                "hybridComponents": result.get("hybridComponents"),
                "zoneDiagnostics": result.get("zoneDiagnostics"),
                "region": region,
                "dt_score": float(dt),
                "batched": True,
            })
            values.append((float(hybrid), dict(euler_deg), result))
        return values

    if refinement_only:
        base_entry = accumulated.get(bone, {})
        if isinstance(base_entry, dict) and base_entry.get("axis"):
            euler = {"x": 0.0, "y": 0.0, "z": 0.0}
            euler[str(base_entry["axis"])] = math.degrees(float(base_entry.get("angle", 0.0)))
        elif isinstance(base_entry, dict) and base_entry.get("quaternion"):
            euler = {
                axis: math.degrees(value)
                for axis, value in zip(
                    ("x", "y", "z"),
                    quaternion_to_euler_xyz(pose_value_to_quaternion(base_entry)),
                )
            }
        elif isinstance(base_entry, dict):
            euler = {
                axis: math.degrees(float(base_entry.get(axis, 0.0)))
                for axis in ("x", "y", "z")
            }
        else:
            euler = {"x": 0.0, "y": 0.0, "z": 0.0}
        euler = {axis: _clip(value) for axis, value in euler.items()}
        step = float(NEAR_BONE_REFINEMENT_STEP_DEG if refine_step is None else refine_step)
        best_euler = dict(euler)
        best_score = _score_euler_deg(best_euler, "near_refine_center")
        timings["refinementOnly"] = True
        timings["refinementStepDeg"] = step
        for axis in axes:
            for delta in (-step, step):
                candidate = dict(best_euler)
                candidate[axis] = _clip(candidate[axis] + delta)
                if abs(candidate[axis] - best_euler[axis]) < 1e-9:
                    continue
                score = _score_euler_deg(
                    candidate,
                    "near_refine",
                    incumbent_score=best_score,
                )
                if score > best_score:
                    best_score, best_euler = float(score), candidate
        timings["chosenEulerDeg"] = dict(best_euler)
        timings["chosenAxis"] = "near_refine"
        return (
            {
                "x": math.radians(float(best_euler["x"])),
                "y": math.radians(float(best_euler["y"])),
                "z": math.radians(float(best_euler["z"])),
            },
            float(best_score),
            all_trials,
            timings,
        )

    if IK_ENABLED and IK_MODE.lower() == "replace_all":
        # Every rotation candidate is ignored by the worker in this mode.
        # Score the bind rotation once so the target-driven IK pose is rendered
        # without paying for a sweep of identical candidates.
        zero = {"x": 0.0, "y": 0.0, "z": 0.0}
        score = _score_euler_deg(zero, "ik-only")
        timings["ikOnly"] = True
        timings["chosenEulerDeg"] = dict(zero)
        timings["chosenAxis"] = "ik"
        return zero, float(score), all_trials, timings

    def _mags(step):
        vals = [0.0]
        m = float(step)
        lim = max(abs(lo), abs(hi))
        while m <= lim + 1e-9:
            if m <= hi + 1e-9:
                vals.append(m)
            if -m >= lo - 1e-9:
                vals.append(-m)
            m += float(step)
        return sorted(set(_clip(v) for v in vals))

    def _run_single_axis_modes():
        """Legacy: independent axis sweeps; return single-axis pose dict."""
        run_axes = list(axes)
        axis_timings = []
        local_trials = []

        def _run_axis(axis, *, step_coarse, step_refine):
            angle_rad, score, trials, t = scan_bone_axis(
                frame_index,
                bone,
                accumulated,
                axis,
                coarse_step=step_coarse,
                refine_step=step_refine,
                progress_desc=progress_desc,
                live_preview=live,
                ik_targets_override=ik_targets_override,
            )
            local_trials.extend(trials)
            axis_timings.append(t)
            return score, axis, angle_rad, trials, t

        if mode == "probe_one" and AXIS_PROBE_FIRST and len(run_axes) > 1:
            probe = float(min(coarse_step, max(abs(lo), abs(hi), 1.0)))
            probe_angles = [0.0]
            if lo < -1e-6:
                probe_angles.append(_clip(-probe))
            if hi > 1e-6:
                probe_angles.append(_clip(probe))
            best_probe = None
            for axis in run_axes:
                for a in probe_angles:
                    pose = dict(accumulated)
                    pose[bone] = {"axis": axis, "angle": math.radians(float(a))}
                    probe_req = {
                            "cmd": "score",
                            "target": str(target),
                            "targetDepth": str(target_depth),
                            "angles": pose,
                            "scoreMode": SCORE_MODE,
                            "depthMaxDist": DEPTH_MAX_DIST,
                            "colorMaxDist": COLOR_MAX_DIST,
                            "targetPartBoxes": PART_BOXES_BY_FRAME.get(frame_index, []),
            "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,
                            "threshold": 0.08,
                    }
                    _attach_motion_root_request(probe_req, pose)
                    configure_score_request(
                        probe_req,
                        frame_index,
                        ik_targets_override=ik_targets_override,
                        ik_bones_override=ik_bones_override,
                    )
                    probe_out = None
                    probe_views = []
                    if SEMANTIC_ONLY:
                        safe_axis = re.sub(r"[^A-Za-z0-9_.+-]+", "_", str(axis))
                        safe_angle = f"{float(a):+.1f}".replace("+", "p").replace("-", "m")
                        probe_out = _semantic_candidate_dir / (
                            f"f{frame_index:02d}_probe_{safe_axis}_{safe_angle}.png"
                        )
                        probe_views = semantic_paths(frame_index, f"probe_{safe_axis}_{safe_angle}")
                        probe_req.update({
                            "semanticOnly": True,
                            "semanticModel": SEMANTIC_MODEL_ID,
                            "previewRgb": True,
                            "semanticCandidateOut": str(probe_out),
                            "semanticMultiview": bool(SEMANTIC_MULTIVIEW),
                            "semanticViewAnglesDeg": list(SEMANTIC_VIEW_ANGLES_DEG),
                            "semanticViewElevationsDeg": list(SEMANTIC_VIEW_ELEVATIONS_DEG),
                            "semanticViewOuts": [str(path) for path in probe_views],
                        })
                        probe_out.unlink(missing_ok=True)
                        for path in probe_views:
                            path.unlink(missing_ok=True)
                    result = worker.request(probe_req)
                    if not result.get("ok"):
                        raise RuntimeError(result)
                    apply_anatomical_candidate_features(result, frame_index, probe_req)
                    if SEMANTIC_ONLY:
                        if not probe_out.is_file() or any(not path.is_file() for path in probe_views):
                            raise RuntimeError(f"semantic probe render set was not written: {probe_out}, {probe_views}")
                        probe_paths = probe_views if SEMANTIC_MULTIVIEW else [probe_out]
                        score_semantic_candidate(frame_index, probe_paths, result, None)
                        score = float(result["iou"])
                    else:
                        score = apply_nonsemantic_hybrid_score(result)
                    local_trials.append((axis, float(a), score))
                    cand = (score, axis)
                    if best_probe is None or cand[0] > best_probe[0]:
                        best_probe = cand
            run_axes = [best_probe[1]]

        best = None
        for axis in run_axes:
            cand = _run_axis(axis, step_coarse=coarse_step, step_refine=refine_step)
            if best is None or cand[0] > best[0]:
                best = cand
        score, axis, angle_rad, _tr, t = best
        timings.update(
            {
                "chosenAxis": axis,
                "perAxis": axis_timings,
                "axesTried": list(run_axes),
            }
        )
        all_trials.extend(local_trials)
        return {"axis": axis, "angle": float(angle_rad)}, float(score), all_trials, timings

    if mode != "compound":
        return _run_single_axis_modes()

    # --- Simultaneous compound Euler (x+y+z) ---
    base_entry = accumulated.get(bone, {})
    if isinstance(base_entry, dict) and base_entry.get("axis"):
        best_euler = {"x": 0.0, "y": 0.0, "z": 0.0}
        best_euler[str(base_entry["axis"])] = math.degrees(float(base_entry.get("angle", 0.0)))
    elif isinstance(base_entry, dict):
        best_euler = {
            axis: float(math.degrees(float(base_entry.get(axis, 0.0))))
            for axis in ("x", "y", "z")
        }
    else:
        best_euler = {"x": 0.0, "y": 0.0, "z": 0.0}
    best_euler = {axis: _clip(value) for axis, value in best_euler.items()}
    best_score = _score_euler_deg(best_euler, "bind")

    candidates = [best_euler.copy()]
    # 1D stars
    for ax in axes:
        for m in _mags(coarse_step):
            if abs(m) < 1e-9:
                continue
            e = {"x": 0.0, "y": 0.0, "z": 0.0}
            e[ax] = m
            candidates.append(e)
    # 2D simultaneous pairs (coarser / shorter mag list)
    pair_step = max(refine_step, coarse_step * float(COMPOUND_PAIR_STEP_MULT))
    mags2 = [m for m in _mags(pair_step) if abs(m) <= 2.0 * pair_step + 1e-9]
    for i, a1 in enumerate(axes):
        for a2 in axes[i + 1 :]:
            for m1 in mags2:
                for m2 in mags2:
                    if abs(m1) < 1e-9 and abs(m2) < 1e-9:
                        continue
                    e = {"x": 0.0, "y": 0.0, "z": 0.0}
                    e[a1], e[a2] = m1, m2
                    candidates.append(e)
    # 3D simultaneous sign patterns at 1× and 2× pair_step
    for s in (pair_step, 2.0 * pair_step):
        if s > max(abs(lo), abs(hi)) + 1e-9:
            continue
        for sx in (-1, 0, 1):
            for sy in (-1, 0, 1):
                for sz in (-1, 0, 1):
                    if sx == sy == sz == 0:
                        continue
                    e = {
                        "x": _clip(sx * s) if "x" in axes else 0.0,
                        "y": _clip(sy * s) if "y" in axes else 0.0,
                        "z": _clip(sz * s) if "z" in axes else 0.0,
                    }
                    candidates.append(e)

    # Dedupe
    uniq = {}
    for e in candidates:
        key = (
            round(float(e.get("x", 0.0)), 4),
            round(float(e.get("y", 0.0)), 4),
            round(float(e.get("z", 0.0)), 4),
        )
        uniq[key] = {
            "x": float(e.get("x", 0.0)),
            "y": float(e.get("y", 0.0)),
            "z": float(e.get("z", 0.0)),
        }
    candidates = list(uniq.values())
    timings["compoundCandidates"] = len(candidates)

    joint_candidates = [
        e for e in candidates
        if not (e["x"] == 0.0 and e["y"] == 0.0 and e["z"] == 0.0)
    ]
    for score, e, _result in _score_euler_batch(joint_candidates, "joint"):
        if score > best_score:
            best_score, best_euler = score, dict(e)

    # Coordinate-descent refine: move one axis at a time, keep others fixed (stays simultaneous).
    for _round in range(max(1, int(COMPOUND_CD_ROUNDS))):
        for ax in axes:
            center = float(best_euler.get(ax, 0.0))
            window = max(2.0 * refine_step, coarse_step)
            samples = np.arange(
                _clip(center - window),
                _clip(center + window) + refine_step * 0.5,
                refine_step,
            )
            if not np.any(np.isclose(samples, center)):
                samples = np.unique(np.append(samples.astype(float), center))
            refine_candidates = []
            for a in samples:
                trial = dict(best_euler)
                trial[ax] = float(a)
                refine_candidates.append(trial)
            for score, trial, _result in _score_euler_batch(
                refine_candidates, f"cd{_round}_{ax}"
            ):
                if score > best_score:
                    best_score, best_euler = score, dict(trial)

    # Candidate renders are batched without preview output. Refresh one
    # committed-looking best candidate so live mode remains useful without
    # serializing every rejected proposal.
    if live:
        preview_pose = dict(accumulated)
        preview_pose[bone] = {
            "x": math.radians(float(best_euler.get("x", 0.0))),
            "y": math.radians(float(best_euler.get("y", 0.0))),
            "z": math.radians(float(best_euler.get("z", 0.0))),
        }
        _score_multibone_pose(
            frame_index,
            preview_pose,
            f"f{frame_index:02d} {progress_desc or bone} best preview",
            True,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )

    delta = {
        "x": math.radians(float(best_euler.get("x", 0.0))),
        "y": math.radians(float(best_euler.get("y", 0.0))),
        "z": math.radians(float(best_euler.get("z", 0.0))),
    }
    timings["chosenEulerDeg"] = dict(best_euler)
    timings["chosenAxis"] = "xyz"
    return delta, float(best_score), all_trials, timings


_IK_TARGET_IMAGE_SIZES = {}


def _target_entry(value):
    """Normalize tuple/list/dict target forms while preserving optional depth."""
    if isinstance(value, dict):
        if "x" not in value or "y" not in value:
            raise ValueError(f"IK target must contain x and y: {value!r}")
        entry = dict(value)
    else:
        if len(value) < 2:
            raise ValueError(f"IK target must contain x and y: {value!r}")
        entry = {"x": value[0], "y": value[1]}
        if len(value) > 2:
            entry["depth"] = value[2]
    entry["x"] = float(entry["x"])
    entry["y"] = float(entry["y"])
    if not (0.0 <= entry["x"] <= 1.0 and 0.0 <= entry["y"] <= 1.0):
        raise ValueError(f"IK target must be normalized to [0,1]: {entry!r}")
    return entry


def _target_image_size(path):
    path = Path(path)
    key = str(path.resolve())
    if key not in _IK_TARGET_IMAGE_SIZES:
        with Image.open(path) as image:
            _IK_TARGET_IMAGE_SIZES[key] = (int(image.width), int(image.height))
    return _IK_TARGET_IMAGE_SIZES[key]


def _score_ik_target_candidate(
    frame_index,
    accumulated,
    target_map,
    active_ik_bones,
    label,
    target_path,
    target_depth_path,
    live,
):
    """Render/score one candidate using only the accumulated IK bones.

    The target map may contain untouched authored points for reference, but
    ``active_ik_bones`` is the experiment state: current bone plus targets
    selected in earlier steps. This is what prevents the first preview from
    applying the entire inferred skeleton at once.
    """
    if not isinstance(target_map, dict):
        raise ValueError("IK target search requires a flat bone->target map")
    safe_label = re.sub(r"[^A-Za-z0-9_.+-]+", "_", str(label))
    out = _semantic_candidate_dir / f"ik_target_f{frame_index:02d}_{safe_label}.png" if SEMANTIC_ONLY else None
    view_paths = semantic_paths(frame_index, f"ik_target_{safe_label}") if SEMANTIC_ONLY else []
    if out is not None:
        out.unlink(missing_ok=True)
        for path in view_paths:
            path.unlink(missing_ok=True)
    req = {
        "cmd": "score",
        "target": str(target_path),
        "targetDepth": str(target_depth_path),
        "angles": dict(accumulated),
        "scoreMode": SCORE_MODE,
        "depthMaxDist": DEPTH_MAX_DIST,
        "colorMaxDist": COLOR_MAX_DIST,
        "targetPartBoxes": PART_BOXES_BY_FRAME.get(frame_index, []),
        "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,
        "threshold": 0.08,
    }
    _attach_motion_root_request(req, accumulated)
    configure_score_request(
        req,
        frame_index,
        ik_targets_override=target_map,
        ik_bones_override=active_ik_bones,
    )
    if live:
        req["previewOut"] = str(PREVIEW_PATH)
        req["previewRgb"] = True
        req["previewCaption"] = label
        req["previewProfileDepth"] = bool(req.get("renderDepth", False))
        req["previewActionCamera"] = True
        req["actionCameraAngleDeg"] = float(globals().get("ACTION_CAMERA_ANGLE_DEG", -45.0))
        req["actionCameraElevationDeg"] = float(globals().get("ACTION_CAMERA_ELEVATION_DEG", 18.0))
    if SEMANTIC_ONLY:
        req["scoreMode"] = SCORE_MODE
        req["semanticOnly"] = True
        req["semanticModel"] = SEMANTIC_MODEL_ID
        req["previewRgb"] = True
        req["semanticCandidateOut"] = str(out)
        req["semanticMultiview"] = bool(SEMANTIC_MULTIVIEW)
        req["semanticViewAnglesDeg"] = list(SEMANTIC_VIEW_ANGLES_DEG)
        req["semanticViewElevationsDeg"] = list(SEMANTIC_VIEW_ELEVATIONS_DEG)
        req["semanticViewOuts"] = [str(path) for path in view_paths]
    t0 = time.perf_counter()
    result = worker.request(req)
    dt = time.perf_counter() - t0
    if not result.get("ok"):
        raise RuntimeError(result)
    apply_anatomical_candidate_features(result, frame_index, req)
    if SEMANTIC_ONLY and not _triage_reject(result):
        if not out.is_file() or out.stat().st_size <= 0:
            raise RuntimeError(f"semantic candidate render was not written: {out}")
        candidate_paths = view_paths if SEMANTIC_MULTIVIEW else [out]
        if any(not path.is_file() for path in candidate_paths):
            raise RuntimeError(f"semantic multiview render set was not written: {candidate_paths}")
        score_semantic_candidate(frame_index, candidate_paths, result, None)
    if not SEMANTIC_ONLY:
        apply_nonsemantic_hybrid_score(result)
    score = float(result["iou"])
    if live:
        show_live_preview(
            label,
            score,
            result.get("semanticCosine"),
            result.get("depthIoU"),
            result.get("textCosine"),
            result.get("negativeTextCosine"),
            result,
        )
    return score, result, dt


def scan_ik_target_axis(
    frame_index,
    bone,
    accumulated,
    target_map,
    axis,
    active_ik_bones,
    coarse_step_px=None,
    refine_step_px=None,
    search_radius_px=None,
    progress_desc=None,
    live_preview=None,
):
    """Coarse/fine search for one bone's normalized image-space IK coordinate."""
    live = LIVE_PREVIEW if live_preview is None else live_preview
    if bone not in target_map:
        raise KeyError(f"IK target search bone is missing from target map: {bone}")
    axis = str(axis).lower()
    if axis not in {"x", "y"}:
        raise ValueError(f"IK target search axis must be x or y, got {axis!r}")
    target_path = ANIMATION_TARGET_FRAMES / f"{frame_index:02d}.png"
    target_depth_path = TARGET_DEPTH / f"{frame_index:02d}.png"
    width, height = _target_image_size(target_path)
    pixels = float(width if axis == "x" else height)
    coarse_px = float(IK_TARGET_COARSE_STEP_PX if coarse_step_px is None else coarse_step_px)
    refine_px = float(IK_TARGET_REFINE_STEP_PX if refine_step_px is None else refine_step_px)
    radius_px = float(IK_TARGET_SEARCH_RADIUS_PX if search_radius_px is None else search_radius_px)
    if coarse_px <= 0.0 or refine_px <= 0.0 or radius_px <= 0.0:
        raise ValueError("IK target search step and radius values must be positive")
    base_target = _target_entry(target_map[bone])
    current = float(base_target[axis])
    lower = max(0.0, current - radius_px / pixels)
    upper = min(1.0, current + radius_px / pixels)
    coarse_step = coarse_px / pixels
    refine_step = refine_px / pixels
    evaluations = []
    trials = []
    timings = {
        "targetAxis": axis,
        "targetBone": bone,
        "targetImageSize": [width, height],
        "coarseStepPx": coarse_px,
        "refineStepPx": refine_px,
        "searchRadiusPx": radius_px,
        "coarseAllEvals": [],
        "refineAllEvals": [],
        "targetEvaluations": evaluations,
    }
    counter = 0

    def evaluate(value, region):
        nonlocal counter
        counter += 1
        candidate_map = copy.deepcopy(target_map)
        candidate = dict(base_target)
        candidate[axis] = float(min(upper, max(lower, value)))
        candidate_map[bone] = candidate
        norm = candidate[axis]
        px = norm * pixels
        label = (
            f"f{frame_index:02d} {progress_desc or bone} IK {axis.upper()} {region} "
            f"{px:.1f}px ({norm:.4f})"
        )
        score, result, dt = _score_ik_target_candidate(
            frame_index,
            accumulated,
            candidate_map,
            active_ik_bones,
            label,
            target_path,
            target_depth_path,
            live,
        )
        row = {
            "bone": bone,
            "axis": axis,
            "region": region,
            "valuePx": float(px),
            "valueNorm": float(norm),
            "target": dict(candidate),
            "activeIkBones": list(active_ik_bones),
            "hybridScore": score,
            "semanticCosine": result.get("semanticCosine"),
            "semanticLayerCosines": result.get("semanticLayerCosines"),
            "depthIoU": result.get("depthIoU"),
            "textCosine": result.get("textCosine"),
            "negativeTextCosine": result.get("negativeTextCosine"),
            "negativeTextAvoidance": result.get("negativeTextAvoidance"),
            "workerIoU": result.get("workerIoU"),
            "anatomicalPartIoU": result.get("anatomicalPartIoU"),
            "anatomicalFeatureDistance": result.get("anatomicalFeatureDistance"),
            "hybridComponents": result.get("hybridComponents"),
            "zoneDiagnostics": result.get("zoneDiagnostics"),
            "dt_score": dt,
            "evaluation": counter,
        }
        evaluations.append(row)
        timings["coarseAllEvals" if region == "coarse" else "refineAllEvals"].append(row)
        trials.append((axis, float(norm), score))
        return score, norm

    center_score, center = evaluate(current, "center")
    best_score, best_value = center_score, center
    coarse = np.arange(lower, upper + coarse_step * 0.5, coarse_step)
    if not np.any(np.isclose(coarse, current)):
        coarse = np.unique(np.append(coarse.astype(float), current))
    t0 = time.perf_counter()
    coarse_results = []
    for value in coarse:
        if abs(float(value) - current) < 1e-9:
            continue
        score, norm = evaluate(float(value), "coarse")
        coarse_results.append((score, norm))
    timings["coarseTotal"] = time.perf_counter() - t0
    if coarse_results:
        candidate_score, candidate_value = max(coarse_results, key=lambda item: item[0])
        if candidate_score > best_score:
            best_score, best_value = candidate_score, candidate_value
    timings["coarseBestNorm"] = float(best_value)
    fine = np.arange(
        max(lower, best_value - coarse_step),
        min(upper, best_value + coarse_step) + refine_step * 0.5,
        refine_step,
    )
    t0 = time.perf_counter()
    for value in fine:
        if abs(float(value) - best_value) < 1e-9:
            continue
        score, norm = evaluate(float(value), "refine")
        if score > best_score:
            best_score, best_value = score, norm
    timings["refineTotal"] = time.perf_counter() - t0
    if best_score <= center_score + IK_TARGET_MIN_IMPROVEMENT:
        best_score, best_value = center_score, current
    selected = dict(base_target)
    selected[axis] = float(best_value)
    timings["chosenValuePx"] = float(best_value * pixels)
    timings["chosenValueNorm"] = float(best_value)
    timings["chosenScore"] = float(best_score)
    timings["evaluations"] = len(evaluations)
    return selected, float(best_score), trials, timings


def _ordered_ik_target_search_bones(frame_targets, current_bones):
    explicit = list(IK_TARGET_SEARCH_BONES)
    if explicit:
        missing = [name for name in explicit if name not in frame_targets]
        if missing:
            preview = ", ".join(missing[:8])
            suffix = "..." if len(missing) > 8 else ""
            raise RuntimeError(f"IK target search requested bones without targets: {preview}{suffix}")
        return explicit

    # Auto-authored keypoint files can be partial for a custom unit. Search
    # every available target in dependency order, then retain any extra named
    # points from the file instead of failing on unrelated rig bones.
    base = list(IK_BONES) if IK_BONES else list(order)
    if current_bones:
        base = list(current_bones) + [name for name in base if name not in current_bones]
    requested = [name for name in base if name in frame_targets]
    requested.extend(name for name in frame_targets if name not in requested)
    if not requested:
        raise RuntimeError("IK target search has no target bones after applying the rig order")
    return requested


def _run_ik_target_search(frame_index, pose, current_bones, live):
    """Search keypoints one bone at a time while accumulating selected moves."""
    if not IK_ENABLED or IK_MODE.lower() == "off":
        raise RuntimeError("IK target search requires IK_ENABLED=True and IK_MODE other than 'off'")
    frame_targets = _frame_ik_targets(frame_index)
    if not frame_targets:
        raise RuntimeError(f"IK target search has no targets for frame {frame_index}")
    target_bones = _ordered_ik_target_search_bones(frame_targets, current_bones)
    target_history = []
    target_timings = []
    active_ik_bones = []
    for bone in target_bones:
        bone_start = time.perf_counter()
        selected = _target_entry(frame_targets[bone])
        bone_trials = []
        axes = []
        score = None
        active_for_bone = [*active_ik_bones, bone]
        for axis in ("x", "y"):
            selected, score, trials, timings = scan_ik_target_axis(
                frame_index,
                bone,
                pose,
                frame_targets,
                axis,
                active_for_bone,
                progress_desc=f"IK target [{bone}]",
                live_preview=live,
            )
            frame_targets[bone] = selected
            bone_trials.extend(trials)
            axes.append(timings)
        target_history.append({
            "bone": bone,
            "kind": "ik_target",
            "target": dict(selected),
            "activeIkBones": list(active_for_bone),
            "hybridScore": float(score),
            "trials": len(bone_trials),
            "timings": {"axes": axes, "targetEvaluations": sum(len(item["targetEvaluations"]) for item in axes)},
            "elapsed": time.perf_counter() - bone_start,
        })
        target_timings.append({
            "bone": bone,
            "kind": "ik_target",
            "activeIkBones": list(active_for_bone),
            "axes": axes,
            "elapsed_total": time.perf_counter() - bone_start,
        })
        print(
            f"f{frame_index:02d} IK target {bone}: "
            f"({selected['x']:.4f},{selected['y']:.4f}) "
            f"hybrid={float(score):.6f} evals={len(bone_trials)} "
            f"elapsed={time.perf_counter() - bone_start:.2f}s"
        )
        active_ik_bones.append(bone)
    _set_frame_ik_targets(frame_index, frame_targets)
    return frame_targets, target_history, target_timings, active_ik_bones

# Disabled by default: coarse/fine search remains the active solver.
SEMANTIC_OPTIMIZER = bool(globals().get("SEMANTIC_OPTIMIZER", False))
SEMANTIC_INITIAL_STEP_DEG = 24.0
SEMANTIC_MIN_STEP_DEG = 2.0
SEMANTIC_MAX_EVALS_PER_AXIS = 9
SEMANTIC_MIN_IMPROVEMENT = 0.002

def optimize_frame_semantic(frame_index, initial=None, bones=None, progress=None, live_preview=None):
    """Adaptive coordinate descent using CLIP cosine similarity.

    Each bone/axis probes the current angle and both signed directions. It
    keeps a winning move, expands no further than the anatomical range, and
    halves the step when neither direction improves. This replaces the
    exhaustive coarse/refine grid for the semantic pilot only.
    """
    if not SEMANTIC_ONLY:
        raise RuntimeError("semantic optimizer requires SEMANTIC_ONLY=True")
    if ROTATION_VECTOR_SEARCH_ENABLED:
        # The arbitrary-axis stage belongs to the canonical scorer so it also
        # shares batch rendering, twist policy, and boundary diagnostics.
        return optimize_frame(
            frame_index,
            initial=initial,
            bones=bones,
            progress=progress,
            live_preview=live_preview,
        )
    if MULTI_BONE_MODE != "single":
        # The multi-bone modes use the canonical coarse/fine entry point so
        # they can score complete poses while still applying semantic-only or
        # hybrid weighting through the normal worker contract.
        return optimize_frame(
            frame_index,
            initial=initial,
            bones=bones,
            progress=progress,
            live_preview=live_preview,
        )
    if IK_TARGET_SEARCH_ENABLED or (IK_ENABLED and IK_MODE.lower() == "replace_all"):
        # Target search and replace_all are owned by the canonical coarse/fine
        # path. Delegating keeps the keypoint trials, target overrides, and
        # live preview behavior identical when the semantic optimizer toggle
        # is also enabled.
        return optimize_frame(
            frame_index,
            initial=initial,
            bones=[],
            progress=progress,
            live_preview=live_preview,
        )
    live = LIVE_PREVIEW if live_preview is None else live_preview
    target = ANIMATION_TARGET_FRAMES / f"{frame_index:02d}.png"
    target_depth = TARGET_DEPTH / f"{frame_index:02d}.png"
    pose = dict(initial or {})
    history, timings = [], []
    evaluation_details = []
    total_start = time.perf_counter()
    target_vec = semantic_target_vector(frame_index)
    eval_count = 0

    def score_pose(candidate, label):
        nonlocal eval_count
        eval_count += 1
        out = _semantic_candidate_dir / f"opt_f{frame_index:02d}_{eval_count:04d}.png"
        view_paths = semantic_paths(frame_index, f"opt_{eval_count:04d}")
        # Never allow a failed/partial Blender write to masquerade as the
        # previous candidate. The encoder must see the render produced by this
        # exact pose evaluation.
        out.unlink(missing_ok=True)
        for path in view_paths:
            path.unlink(missing_ok=True)
        req = {
            "cmd": "score", "target": str(target),
            "targetDepth": str(target_depth), "angles": candidate,
            "scoreMode": SCORE_MODE, "previewRgb": True,
            "semanticCandidateOut": str(out),
            "semanticMultiview": bool(SEMANTIC_MULTIVIEW),
            "semanticViewAnglesDeg": list(SEMANTIC_VIEW_ANGLES_DEG),
            "semanticViewElevationsDeg": list(SEMANTIC_VIEW_ELEVATIONS_DEG),
            "semanticViewOuts": [str(path) for path in view_paths],
            "targetPartBoxes": PART_BOXES_BY_FRAME.get(frame_index, []),
            "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,
            "showAnatomicalBoxes": SHOW_ANATOMICAL_BOXES,
        }
        _attach_motion_root_request(req, candidate)
        configure_score_request(req, frame_index)
        if live:
            req["previewOut"] = str(PREVIEW_PATH)
            req["previewCaption"] = f"f{frame_index:02d} semantic {label}"
            req["previewProfileDepth"] = bool(req.get("renderDepth", False))
            req["previewActionCamera"] = True
            req["actionCameraAngleDeg"] = float(globals().get("ACTION_CAMERA_ANGLE_DEG", -45.0))
            req["actionCameraElevationDeg"] = float(globals().get("ACTION_CAMERA_ELEVATION_DEG", 18.0))
        t0 = time.perf_counter()
        result = worker.request(req)
        if not result.get("ok"):
            raise RuntimeError(result)
        apply_anatomical_candidate_features(result, frame_index, req)
        triage_rejected = _triage_reject(result)
        if not triage_rejected and (
            not out.is_file() or out.stat().st_size <= 0
        ):
            raise RuntimeError(f"semantic candidate render was not written: {out}")
        if not triage_rejected:
            candidate_paths = view_paths if SEMANTIC_MULTIVIEW else [out]
            if any(not path.is_file() for path in candidate_paths):
                raise RuntimeError(f"semantic multiview render set was not written: {candidate_paths}")
            score_semantic_candidate(frame_index, candidate_paths, result, None)
            semantic_cosine = result.get("semanticCosine")
            semantic_layer_scores = result.get("semanticLayerCosines")
            text_cosine = result.get("textCosine")
            negative_text_cosine = result.get("negativeTextCosine")
            dense_distance = result.get("denseSemanticDistance")
            dense_layer_distances = result.get("denseSemanticLayerDistances")
            similarity = float(result["iou"])
        else:
            similarity = float(result["iou"])
        evaluation_details.append({
            "label": label,
            "candidate": str(out),
            "candidateBytes": int(out.stat().st_size),
            "candidateSha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            "semanticCosine": semantic_cosine,
            "semanticLayerCosines": semantic_layer_scores,
            "denseSemanticDistance": dense_distance,
            "denseSemanticLayerDistances": dense_layer_distances,
            "depthIoU": result.get("depthIoU"),
            "workerIoU": result.get("workerIoU"),
            "textCosine": text_cosine,
            "negativeTextCosine": negative_text_cosine,
            "negativeTextAvoidance": (
                None if negative_text_cosine is None
                else 1.0 - ((float(np.clip(negative_text_cosine, -1.0, 1.0)) + 1.0) * 0.5)
            ),
            "hybridScore": similarity,
            "hybridComponents": result.get("hybridComponents"),
            "zoneDiagnostics": result.get("zoneDiagnostics"),
        })
        if live:
            update_live_preview_image()
        timings.append({
            "label": label,
            "seconds": time.perf_counter() - t0,
            "score": similarity,
            "semanticCosine": semantic_cosine,
            "semanticLayerCosines": semantic_layer_scores,
            "depthIoU": result.get("depthIoU"),
            "workerIoU": result.get("workerIoU"),
            "textCosine": text_cosine,
            "negativeTextCosine": negative_text_cosine,
            "negativeTextAvoidance": (
                None if negative_text_cosine is None
                else 1.0 - ((float(np.clip(negative_text_cosine, -1.0, 1.0)) + 1.0) * 0.5)
            ),
            "anatomicalPartIoU": result.get("anatomicalPartIoU"),
            "anatomicalFeatureDistance": result.get("anatomicalFeatureDistance"),
            "hybridComponents": result.get("hybridComponents"),
            "zoneDiagnostics": result.get("zoneDiagnostics"),
        })
        return similarity

    semantic_bones = [
        MOTION_ROOT_KEY if str(bone) == LEGACY_BODY_TRANSLATION_KEY else str(bone)
        for bone in (bones or pilot_bones)
    ]
    semantic_root_controls = []
    if MOTION_ROOT_ENABLED:
        semantic_root_controls.append(MOTION_ROOT_KEY)
    if MOTION_ROOT_ROTATION_ENABLED:
        semantic_root_controls.append(MOTION_ROOT_ROTATION_KEY)
    semantic_bones = semantic_root_controls + [
        bone for bone in semantic_bones if bone not in set(semantic_root_controls)
    ]
    semantic_processed_bones = set()
    semantic_order_index = {name: index for index, name in enumerate(semantic_bones)}
    for bone in semantic_bones:
        bone_start = time.perf_counter()
        bone_record = {"bone": bone, "axes": {}, "evaluations": 0}
        if bone == MOTION_ROOT_KEY:
            delta, score, trials, root_timings = scan_motion_root(
                frame_index,
                pose,
                progress_desc="semantic motion root",
                live_preview=live,
            )
            pose[bone] = delta
            bone_record.update(
                {
                    "axis": "motion_root",
                    "units": "body_lengths",
                    "root": dict(delta),
                    "hybridScore": float(score),
                    "evaluations": len(trials),
                    "timings": root_timings,
                    "elapsed": time.perf_counter() - bone_start,
                }
            )
            history.append(bone_record)
            timings.append({
                "bone": bone,
                "kind": "motion_root",
                **root_timings,
                "elapsed_total": bone_record["elapsed"],
            })
            print(
                f"f{frame_index:02d} motion root: hybrid={float(score):.6f} "
                f"root={delta} evals={len(trials)} "
                f"elapsed={bone_record['elapsed']:.2f}s"
            )
            continue
        if bone == MOTION_ROOT_ROTATION_KEY:
            delta, score, trials, root_timings = scan_motion_root_rotation(
                frame_index,
                pose,
                progress_desc="semantic motion root rotation",
                live_preview=live,
                relax_bones=semantic_bones,
            )
            pose[bone] = delta
            bone_record.update(
                {
                    "axis": "motion_root_rotation",
                    "units": "degrees",
                    "rootRotation": dict(delta),
                    "hybridScore": float(score),
                    "evaluations": len(trials),
                    "timings": root_timings,
                    "elapsed": time.perf_counter() - bone_start,
                }
            )
            history.append(bone_record)
            timings.append({
                "bone": bone,
                "kind": "motion_root_rotation",
                **root_timings,
                "elapsed_total": bone_record["elapsed"],
            })
            print(
                f"f{frame_index:02d} motion root rotation: hybrid={float(score):.6f} "
                f"root={delta} evals={len(trials)} "
                f"elapsed={bone_record['elapsed']:.2f}s"
            )
            continue
        base = pose.get(bone, {})
        if base.get("axis"):
            euler = {"x": 0.0, "y": 0.0, "z": 0.0}
            euler[base["axis"]] = math.degrees(float(base.get("angle", 0.0)))
        else:
            euler = {a: math.degrees(float(base.get(a, 0.0))) for a in ("x", "y", "z")}
        for axis in SEARCH_AXES:
            lo, hi = range_for(bone)
            current = float(euler.get(axis, 0.0))
            current = min(max(current, lo), hi)
            candidate_entry = dict(euler); candidate_entry[axis] = current
            best = score_pose({**pose, bone: candidate_entry}, f"{bone} {axis} center")
            step = min(SEMANTIC_INITIAL_STEP_DEG, max(SEMANTIC_MIN_STEP_DEG, hi - lo))
            axis_evals = 1
            while step >= SEMANTIC_MIN_STEP_DEG and axis_evals + 2 <= SEMANTIC_MAX_EVALS_PER_AXIS:
                candidates = [min(hi, current + step), max(lo, current - step)]
                scored = [(score_pose({**pose, bone: {**euler, axis: a}}, f"{bone} {axis} {a:+.1f}"), a) for a in candidates if abs(a - current) > 1e-6]
                axis_evals += len(scored)
                if scored:
                    trial_score, trial_angle = max(scored, key=lambda item: item[0])
                else:
                    trial_score, trial_angle = best, current
                if trial_score > best + SEMANTIC_MIN_IMPROVEMENT:
                    best, current = trial_score, trial_angle
                    euler[axis] = current
                    pose[bone] = dict(euler)
                else:
                    step *= 0.5
            best_axis_details = max(
                (item for item in evaluation_details if item["label"].startswith(f"{bone} {axis}")),
                key=lambda item: item["hybridScore"],
                default=None,
            )
            bone_record["axes"][axis] = {
                "angleDeg": current,
                "score": best,
                "evaluations": axis_evals,
                "semanticCosine": None if best_axis_details is None else best_axis_details["semanticCosine"],
                "semanticLayerCosines": None if best_axis_details is None else best_axis_details.get("semanticLayerCosines"),
                "depthIoU": None if best_axis_details is None else best_axis_details["depthIoU"],
            }
            bone_record["evaluations"] += axis_evals
        near_rows = []
        if NEAR_BONE_REFINEMENT_ENABLED:
            semantic_processed_bones.add(bone)
            near_children = sorted(
                (
                    child
                    for child in CHILDREN_BY_BONE.get(bone, [])
                    if child in semantic_order_index and child not in semantic_processed_bones
                ),
                key=lambda child: semantic_order_index[child],
            )
            for near_bone in near_children:
                base_near = pose.get(near_bone, {})
                if isinstance(base_near, dict) and base_near.get("axis"):
                    near_euler = {"x": 0.0, "y": 0.0, "z": 0.0}
                    near_euler[str(base_near["axis"])] = math.degrees(
                        float(base_near.get("angle", 0.0))
                    )
                elif isinstance(base_near, dict):
                    near_euler = {
                        axis: math.degrees(float(base_near.get(axis, 0.0)))
                        for axis in ("x", "y", "z")
                    }
                else:
                    near_euler = {"x": 0.0, "y": 0.0, "z": 0.0}
                near_lo, near_hi = range_for(near_bone)
                near_euler = {
                    axis: min(near_hi, max(near_lo, value))
                    for axis, value in near_euler.items()
                }
                near_step = float(NEAR_BONE_REFINEMENT_STEP_DEG)
                near_score = score_pose(
                    {
                        **pose,
                        near_bone: {
                            axis: math.radians(value)
                            for axis, value in near_euler.items()
                        },
                    },
                    f"near {bone}->{near_bone} center",
                )
                near_evals = 1
                for axis in SEARCH_AXES:
                    for delta in (-near_step, near_step):
                        candidate = dict(near_euler)
                        candidate[axis] = min(
                            near_hi,
                            max(near_lo, candidate[axis] + delta),
                        )
                        if abs(candidate[axis] - near_euler[axis]) < 1e-9:
                            continue
                        candidate_score = score_pose(
                            {
                                **pose,
                                near_bone: {
                                    key: math.radians(value)
                                    for key, value in candidate.items()
                                },
                            },
                            f"near {bone}->{near_bone} {axis} {candidate[axis]:+.1f}",
                        )
                        near_evals += 1
                        if candidate_score > near_score:
                            near_score, near_euler = candidate_score, candidate
                pose[near_bone] = {
                    axis: math.radians(value) for axis, value in near_euler.items()
                }
                near_rows.append(
                    {
                        "bone": near_bone,
                        "connector": bone,
                        "stepDeg": near_step,
                        "score": near_score,
                        "evaluations": near_evals,
                        "angleDeg": dict(near_euler),
                    }
                )
        bone_record["nearRefinements"] = near_rows
        bone_record["evaluations"] += sum(row["evaluations"] for row in near_rows)
        bone_record["elapsed"] = time.perf_counter() - bone_start
        history.append(bone_record)
        best_axis = max(bone_record["axes"].values(), key=lambda item: item["score"])
        print(
            f"f{frame_index:02d} {bone}: hybrid={best_axis['score']:.6f} "
            f"semantic={best_axis['semanticCosine']:.6f} "
            f"geometry={best_axis['depthIoU']:.6f} "
            f"evals={bone_record['evaluations']} elapsed={bone_record['elapsed']:.2f}s"
        )
        semantic_processed_bones.add(bone)
    timings.append({
        "kind": "semantic_evaluations",
        "count": len(evaluation_details),
        "rows": evaluation_details,
    })
    return pose, history, time.perf_counter() - total_start, timings

def optimize_frame(frame_index, initial=None, bones=None, progress=None, live_preview=None):
    live = LIVE_PREVIEW if live_preview is None else live_preview
    pose, history = dict(initial or {}), []
    overall_start = time.perf_counter()
    current_bones = [
        MOTION_ROOT_KEY if str(bone) == LEGACY_BODY_TRANSLATION_KEY else str(bone)
        for bone in (order if bones is None else bones)
    ]
    root_controls = []
    if MOTION_ROOT_ENABLED:
        root_controls.append(MOTION_ROOT_KEY)
    if MOTION_ROOT_ROTATION_ENABLED:
        root_controls.append(MOTION_ROOT_ROTATION_KEY)
    current_bones = root_controls + [
        bone for bone in current_bones if bone not in set(root_controls)
    ]
    ik_targets_override = None
    ik_bones_override = None
    if IK_TARGET_SEARCH_ENABLED:
        (
            ik_targets_override,
            target_history,
            target_timings,
            ik_bones_override,
        ) = _run_ik_target_search(
            frame_index,
            pose,
            current_bones,
            live,
        )
        history.extend(target_history)
        if IK_MODE.lower() == "replace_all" or IK_TARGET_SEARCH_ONLY:
            elapsed = time.perf_counter() - overall_start
            print(
                f"Frame {frame_index}: IK target search total elapsed {elapsed:.2f}s "
                f"(bones={len(target_history)}, target-only=True)"
            )
            return pose, history, elapsed, target_timings
    if MOTION_ROOT_ENABLED and MOTION_ROOT_KEY not in current_bones:
        current_bones.append(MOTION_ROOT_KEY)
    if (
        MOTION_ROOT_ROTATION_ENABLED
        and MOTION_ROOT_ROTATION_KEY not in current_bones
    ):
        current_bones.append(MOTION_ROOT_ROTATION_KEY)
    if IK_ENABLED and IK_MODE.lower() == "replace_all":
        probe_bone = next(
            (
                candidate
                for candidate in current_bones
                if candidate
                not in {
                    MOTION_ROOT_KEY,
                    LEGACY_BODY_TRANSLATION_KEY,
                    MOTION_ROOT_ROTATION_KEY,
                }
            ),
            next(
                (
                    candidate
                    for candidate in order
                    if candidate
                    not in {
                        MOTION_ROOT_KEY,
                        LEGACY_BODY_TRANSLATION_KEY,
                        MOTION_ROOT_ROTATION_KEY,
                    }
                ),
                None,
            ),
        )
        if probe_bone is None:
            raise RuntimeError("IK replace_all cannot run because the armature has no pose bones")
        bone_start = time.perf_counter()
        delta, score, trials, timings = scan_bone(
            frame_index,
            probe_bone,
            pose,
            progress_desc="IK [all bones]",
            live_preview=live,
        )
        elapsed = time.perf_counter() - bone_start
        history.append({
            "bone": "<all pose bones>",
            "axis": "ik",
            "angleDeg": {},
            "hybridScore": score,
            "trials": len(trials),
            "timings": {**timings, "ikOnly": True},
            "elapsed": elapsed,
        })
        print(
            f"f{frame_index:02d} IK [all bones]: hybrid={score:.6f} "
            f"(one evaluation, elapsed {elapsed:.2f}s, mode=replace_all)"
        )
        return pose, history, time.perf_counter() - overall_start, [
            {"bone": "<all pose bones>", **timings, "ikOnly": True, "elapsed_total": elapsed}
        ]
    if progress is None or live:
        it = enumerate(current_bones)
    else:
        it = tqdm(enumerate(current_bones), desc=f"Frame {frame_index}", total=len(current_bones))
    frame_timings = list(target_timings) if IK_TARGET_SEARCH_ENABLED else []
    if MULTI_BONE_MODE != "single":
        # Multi-bone local lattices operate on armature Euler axes. Solve the
        # synthetic whole-body controls first, then leave them in the pose
        # while the ordinary block search relaxes local bones around them.
        coupled_rigid_root = (
            MOTION_ROOT_KEY in current_bones
            and MOTION_ROOT_ROTATION_KEY in current_bones
            and MOTION_ROOT_COUPLED_BLOCKS_ENABLED
            and MOTION_ROOT_ROTATION_COUPLED_BLOCKS_ENABLED
        )
        if coupled_rigid_root:
            root_start = time.perf_counter()
            (
                root_delta,
                root_rotation_delta,
                root_score,
                root_trials,
                root_timings,
            ) = scan_motion_root_rigid(
                frame_index,
                pose,
                progress_desc="coupled rigid motion root",
                live_preview=live,
                ik_targets_override=ik_targets_override,
                ik_bones_override=ik_bones_override,
            )
            pose[MOTION_ROOT_KEY] = root_delta
            pose[MOTION_ROOT_ROTATION_KEY] = root_rotation_delta
            root_elapsed = time.perf_counter() - root_start
            history.append(
                {
                    "bone": f"{MOTION_ROOT_KEY}+{MOTION_ROOT_ROTATION_KEY}",
                    "axis": "motion_root_rigid",
                    "root": dict(root_delta),
                    "angleDeg": dict(root_rotation_delta),
                    "hybridScore": float(root_score),
                    "trials": len(root_trials),
                    "timings": root_timings,
                    "elapsed": root_elapsed,
                }
            )
            frame_timings.append(
                {
                    "bone": f"{MOTION_ROOT_KEY}+{MOTION_ROOT_ROTATION_KEY}",
                    **root_timings,
                    "elapsed_total": root_elapsed,
                }
            )
            current_bones = [
                bone
                for bone in current_bones
                if bone not in {MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY}
            ]
        if not coupled_rigid_root and MOTION_ROOT_KEY in current_bones:
            root_start = time.perf_counter()
            root_delta, root_score, root_trials, root_timings = scan_motion_root(
                frame_index,
                pose,
                progress_desc="motion root translation",
                live_preview=live,
                ik_targets_override=ik_targets_override,
                ik_bones_override=ik_bones_override,
            )
            pose[MOTION_ROOT_KEY] = root_delta
            root_elapsed = time.perf_counter() - root_start
            history.append(
                {
                    "bone": MOTION_ROOT_KEY,
                    "axis": "motion_root",
                    "units": "body_lengths",
                    "root": dict(root_delta),
                    "hybridScore": root_score,
                    "trials": len(root_trials),
                    "timings": root_timings,
                    "elapsed": root_elapsed,
                }
            )
            frame_timings.append(
                {
                    "bone": MOTION_ROOT_KEY,
                    **root_timings,
                    "elapsed_total": root_elapsed,
                }
            )
            current_bones = [bone for bone in current_bones if bone != MOTION_ROOT_KEY]
        if not coupled_rigid_root and MOTION_ROOT_ROTATION_KEY in current_bones:
            root_start = time.perf_counter()
            root_delta, root_score, root_trials, root_timings = scan_motion_root_rotation(
                frame_index,
                pose,
                progress_desc="motion root rotation",
                live_preview=live,
                ik_targets_override=ik_targets_override,
                ik_bones_override=ik_bones_override,
                relax_bones=current_bones,
            )
            pose[MOTION_ROOT_ROTATION_KEY] = root_delta
            root_elapsed = time.perf_counter() - root_start
            history.append(
                {
                    "bone": MOTION_ROOT_ROTATION_KEY,
                    "axis": "motion_root_rotation",
                    "angleDeg": dict(root_delta),
                    "hybridScore": root_score,
                    "trials": len(root_trials),
                    "timings": root_timings,
                    "elapsed": root_elapsed,
                }
            )
            frame_timings.append(
                {
                    "bone": MOTION_ROOT_ROTATION_KEY,
                    **root_timings,
                    "elapsed_total": root_elapsed,
                }
            )
            current_bones = [
                bone for bone in current_bones if bone != MOTION_ROOT_ROTATION_KEY
            ]
        multi_pose, multi_history, multi_elapsed, multi_timings = optimize_frame_multibone(
            frame_index,
            initial=pose,
            bones=current_bones,
            progress=progress,
            live_preview=live,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
        history.extend(multi_history)
        frame_timings.extend(multi_timings)
        return multi_pose, history, time.perf_counter() - overall_start, frame_timings
    single_coupled_rigid_root = (
        MOTION_ROOT_KEY in current_bones
        and MOTION_ROOT_ROTATION_KEY in current_bones
        and MOTION_ROOT_COUPLED_BLOCKS_ENABLED
        and MOTION_ROOT_ROTATION_COUPLED_BLOCKS_ENABLED
    )
    if single_coupled_rigid_root:
        root_start = time.perf_counter()
        (
            root_delta,
            root_rotation_delta,
            root_score,
            root_trials,
            root_timings,
        ) = scan_motion_root_rigid(
            frame_index,
            pose,
            progress_desc="coupled rigid motion root",
            live_preview=live,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
        )
        pose[MOTION_ROOT_KEY] = root_delta
        pose[MOTION_ROOT_ROTATION_KEY] = root_rotation_delta
        root_elapsed = time.perf_counter() - root_start
        history.append(
            {
                "bone": f"{MOTION_ROOT_KEY}+{MOTION_ROOT_ROTATION_KEY}",
                "axis": "motion_root_rigid",
                "root": dict(root_delta),
                "angleDeg": dict(root_rotation_delta),
                "hybridScore": float(root_score),
                "trials": len(root_trials),
                "timings": root_timings,
                "elapsed": root_elapsed,
            }
        )
        frame_timings.append(
            {
                "bone": f"{MOTION_ROOT_KEY}+{MOTION_ROOT_ROTATION_KEY}",
                **root_timings,
                "elapsed_total": root_elapsed,
            }
        )
        current_bones = [
            bone
            for bone in current_bones
            if bone not in {MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY}
        ]
        if progress is None or live:
            it = enumerate(current_bones)
        else:
            it = tqdm(
                enumerate(current_bones),
                desc=f"Frame {frame_index}",
                total=len(current_bones),
            )
    processed_bones = set()
    current_order_index = {name: index for index, name in enumerate(current_bones)}
    for i, bone in it:
        progress_desc = f"Bone [{bone}]"
        bone_start = time.perf_counter()
        delta, score, trials, timings = scan_bone(
            frame_index,
            bone,
            pose,
            progress_desc=progress_desc,
            live_preview=live,
            ik_targets_override=ik_targets_override,
            ik_bones_override=ik_bones_override,
            relax_bones=current_bones,
        )
        bone_elapsed = time.perf_counter() - bone_start
        pose[bone] = delta
        processed_bones.add(bone)
        if NEAR_BONE_REFINEMENT_ENABLED:
            near_children = sorted(
                (
                    child
                    for child in CHILDREN_BY_BONE.get(bone, [])
                    if child in current_order_index and child not in processed_bones
                ),
                key=lambda child: current_order_index[child],
            )
            for near_bone in near_children:
                near_start = time.perf_counter()
                near_delta, near_score, near_trials, near_timings = scan_bone(
                    frame_index,
                    near_bone,
                    pose,
                    coarse_step=NEAR_BONE_REFINEMENT_STEP_DEG,
                    refine_step=NEAR_BONE_REFINEMENT_STEP_DEG,
                    progress_desc=f"Near [{bone}->{near_bone}]",
                    live_preview=live,
                    ik_targets_override=ik_targets_override,
                    ik_bones_override=ik_bones_override,
                    refinement_only=True,
                )
                pose[near_bone] = near_delta
                near_elapsed = time.perf_counter() - near_start
                history.append(
                    {
                        "bone": near_bone,
                        "connector": bone,
                        "kind": "near_bone_refinement",
                        "axis": "xyz",
                        "angleDeg": {
                            axis: round(math.degrees(float(near_delta.get(axis, 0.0))), 3)
                            for axis in ("x", "y", "z")
                        },
                        "hybridScore": near_score,
                        "trials": len(near_trials),
                        "timings": near_timings,
                        "elapsed": near_elapsed,
                    }
                )
                frame_timings.append(
                    {
                        "bone": near_bone,
                        "connector": bone,
                        "kind": "near_bone_refinement",
                        **near_timings,
                        "elapsed_total": near_elapsed,
                    }
                )
                if live:
                    print(
                        f"f{frame_index:02d} near {bone}->{near_bone}: "
                        f"hybrid={near_score:.6f} evals={len(near_trials)} "
                        f"elapsed={near_elapsed:.2f}s"
                    )
        if bone in {MOTION_ROOT_KEY, LEGACY_BODY_TRANSLATION_KEY}:
            hist_axis = "motion_root"
            hist_deg = {
                axis: round(float(delta.get(axis, 0.0)), 5)
                for axis in ("forward", "lateral", "vertical")
            }
            hist_label = (
                "root "
                f"F={hist_deg['forward']:+.4f} "
                f"L={hist_deg['lateral']:+.4f} "
                f"V={hist_deg['vertical']:+.4f} body lengths"
            )
        elif bone == MOTION_ROOT_ROTATION_KEY:
            hist_axis = "motion_root_rotation"
            hist_deg = {
                axis: round(float(delta.get(axis, 0.0)), 2)
                for axis in (
                    "camera_forward",
                    "camera_right",
                    "camera_up",
                )
            }
            hist_label = (
                "root rotation "
                f"F={hist_deg['camera_forward']:+.1f} "
                f"R={hist_deg['camera_right']:+.1f} "
                f"U={hist_deg['camera_up']:+.1f} deg"
            )
        elif isinstance(delta, dict) and "axis" in delta:
            hist_axis = delta["axis"]
            hist_deg = math.degrees(delta["angle"])
            hist_label = f"{hist_axis.upper()} {hist_deg:.1f} deg"
        elif isinstance(delta, dict) and "quaternion" in delta:
            hist_axis = "rotation_vector"
            hist_deg = {
                "kind": timings.get("chosenKind"),
                "angle": timings.get("chosenAngleDeg"),
                "twistPolicy": delta.get("twistPolicy", "exclude"),
            }
            hist_label = (
                f"{hist_deg['kind'] or 'shell'} "
                f"{float(hist_deg['angle'] or 0.0):+.1f} deg"
            )
        else:
            hist_axis = "xyz"
            hist_deg = {
                k: round(math.degrees(float(delta.get(k, 0.0))), 2)
                for k in ("x", "y", "z")
            }
            hist_label = (
                f"XYZ ({hist_deg['x']:.1f},{hist_deg['y']:.1f},{hist_deg['z']:.1f}) deg"
            )
        history.append({
            "bone": bone,
            "axis": hist_axis,
            "angleDeg": hist_deg,
            "hybridScore": score,
            "trials": len(trials),
            "timings": timings,
            "elapsed": bone_elapsed,
        })
        frame_timings.append({"bone": bone, **timings, "elapsed_total": bone_elapsed})
        # Surface the raw components for the default frame-0 coarse/compound
        # pilot as well as for the optional semantic optimizer. The compound
        # path keeps these on angle_evaluations; the legacy single-axis path
        # keeps them inside perAxis timing records.
        angle_rows = list(timings.get("angle_evaluations", []))
        for axis_timing in timings.get("perAxis", []):
            angle_rows.extend(axis_timing.get("angle_evaluations", []))
        component_row = max(
            (row for row in angle_rows if row.get("semanticCosine") is not None),
            key=lambda row: float(row.get("hybridScore", row.get("iou", -1.0))),
            default=None,
        )
        line = (
            f"f{frame_index:02d} {bone}: {hist_label} hybrid={score:.6f} "
            f"(bone elapsed {bone_elapsed:.2f}s, mode={timings.get('mode')})"
        )
        if component_row is not None:
            line += (
                f" semantic={float(component_row['semanticCosine']):.6f}"
                f" depth={float(component_row['depthIoU']):.6f}"
            )
        if live:
            if PREVIEW_PATH.exists():
                update_live_preview_image()
            print(line)
        else:
            print(line)

    total_time = time.perf_counter() - overall_start
    print(f"Frame {frame_index}: total elapsed {total_time:.2f}s")
    return pose, history, total_time, frame_timings



def optimize_clip(
    frame_indices=None,
    initial_poses=None,
    bones=None,
    progress=None,
    live_preview=None,
):
    """Fit a complete clip against image and temporal objectives.

    This is intentionally a wrapper around the injected Blender scorer. The
    black-box optimizer changes one frame/bone/axis coordinate at a time, but
    acceptance is based on the full clip objective rather than that frame's
    image score alone.
    """
    frames = list(FRAME_INDICES if frame_indices is None else frame_indices)
    selected_bones = [
        MOTION_ROOT_KEY if str(bone) == LEGACY_BODY_TRANSLATION_KEY else str(bone)
        for bone in (pilot_bones if bones is None else bones)
    ]
    if MOTION_ROOT_ENABLED and MOTION_ROOT_KEY not in selected_bones:
        selected_bones.append(MOTION_ROOT_KEY)
    if (
        MOTION_ROOT_ROTATION_ENABLED
        and MOTION_ROOT_ROTATION_KEY not in selected_bones
    ):
        selected_bones.append(MOTION_ROOT_ROTATION_KEY)
    live = LIVE_PREVIEW if live_preview is None else bool(live_preview)
    config = TemporalClipConfig(
        rounds=CLIP_ROUNDS,
        refine_rounds=CLIP_REFINE_ROUNDS,
        refine_accepted_only=bool(globals().get("CLIP_REFINE_ACCEPTED_ONLY", True)),
        velocity_weight=CLIP_VELOCITY_WEIGHT,
        acceleration_weight=CLIP_ACCELERATION_WEIGHT,
        contact_weight=CLIP_CONTACT_WEIGHT,
        loop_weight=CLIP_LOOP_WEIGHT,
        loop_velocity_weight=CLIP_LOOP_VELOCITY_WEIGHT,
        robust_scale_deg=CLIP_ROBUST_SCALE_DEG,
        coarse_step_deg=CLIP_COARSE_STEP_DEG,
        refine_step_deg=CLIP_REFINE_STEP_DEG,
        max_evaluations_per_axis=CLIP_MAX_EVALUATIONS_PER_AXIS,
        candidate_mode=CLIP_CANDIDATE_MODE,
        acceptance_margin=CLIP_ACCEPTANCE_MARGIN,
        acceptance_relative_margin=CLIP_ACCEPTANCE_RELATIVE_MARGIN,
        preview_candidates=bool(globals().get("CLIP_PREVIEW_CANDIDATES", False)),
        batch_candidates=bool(globals().get("CLIP_BATCH_CANDIDATES", True)),
        axes=tuple(SEARCH_AXES),
        contact_bones=CLIP_CONTACT_BONES,
        loop_enabled=CLIP_LOOP_ENABLED,
        motion_root_enabled=MOTION_ROOT_ENABLED,
        motion_root_axes=MOTION_ROOT_AXES,
        motion_root_forward_radius_body_lengths=MOTION_ROOT_FORWARD_RADIUS_BODY_LENGTHS,
        motion_root_lateral_radius_body_lengths=MOTION_ROOT_LATERAL_RADIUS_BODY_LENGTHS,
        motion_root_vertical_radius_body_lengths=MOTION_ROOT_VERTICAL_RADIUS_BODY_LENGTHS,
        motion_root_coarse_step_body_lengths=MOTION_ROOT_COARSE_STEP_BODY_LENGTHS,
        motion_root_refine_step_body_lengths=MOTION_ROOT_REFINE_STEP_BODY_LENGTHS,
        motion_root_magnitude_weight=CLIP_MOTION_ROOT_MAGNITUDE_WEIGHT,
        motion_root_velocity_weight=CLIP_MOTION_ROOT_VELOCITY_WEIGHT,
        motion_root_acceleration_weight=CLIP_MOTION_ROOT_ACCELERATION_WEIGHT,
        motion_root_loop_weight=CLIP_MOTION_ROOT_LOOP_WEIGHT,
        motion_root_loop_velocity_weight=CLIP_MOTION_ROOT_LOOP_VELOCITY_WEIGHT,
        motion_root_rotation_enabled=MOTION_ROOT_ROTATION_ENABLED,
        motion_root_rotation_basis=MOTION_ROOT_ROTATION_BASIS,
        motion_root_rotation_axes=MOTION_ROOT_ROTATION_AXES,
        motion_root_rotation_limit_deg=MOTION_ROOT_ROTATION_LIMIT_DEG,
        motion_root_rotation_coarse_step_deg=MOTION_ROOT_ROTATION_COARSE_STEP_DEG,
        motion_root_rotation_refine_step_deg=MOTION_ROOT_ROTATION_REFINE_STEP_DEG,
        motion_root_rotation_escape_enabled=MOTION_ROOT_ROTATION_ESCAPE_ENABLED,
        motion_root_rotation_escape_axes=MOTION_ROOT_ROTATION_ESCAPE_AXES,
        motion_root_rotation_escape_angles_deg=MOTION_ROOT_ROTATION_ESCAPE_ANGLES_DEG,
        motion_root_rotation_escape_top_k=MOTION_ROOT_ROTATION_ESCAPE_TOP_K,
        motion_root_rotation_escape_force_image_best=MOTION_ROOT_ROTATION_ESCAPE_FORCE_IMAGE_BEST,
        motion_root_rotation_escape_min_image_improvement=MOTION_ROOT_ROTATION_ESCAPE_MIN_IMAGE_IMPROVEMENT,
        motion_root_rotation_escape_relax_enabled=MOTION_ROOT_ROTATION_ESCAPE_RELAX_ENABLED,
        motion_root_rotation_escape_relax_bone_count=MOTION_ROOT_ROTATION_ESCAPE_RELAX_BONE_COUNT,
        motion_root_rotation_escape_relax_rounds=MOTION_ROOT_ROTATION_ESCAPE_RELAX_ROUNDS,
        motion_root_rotation_escape_relax_step_deg=MOTION_ROOT_ROTATION_ESCAPE_RELAX_STEP_DEG,
        motion_root_rotation_escape_relax_refine_step_deg=MOTION_ROOT_ROTATION_ESCAPE_RELAX_REFINE_STEP_DEG,
        motion_root_rotation_magnitude_weight=MOTION_ROOT_ROTATION_MAGNITUDE_WEIGHT,
        motion_root_rotation_velocity_weight=MOTION_ROOT_ROTATION_VELOCITY_WEIGHT,
        motion_root_rotation_acceleration_weight=MOTION_ROOT_ROTATION_ACCELERATION_WEIGHT,
        motion_root_rotation_loop_weight=MOTION_ROOT_ROTATION_LOOP_WEIGHT,
        motion_root_rotation_loop_velocity_weight=MOTION_ROOT_ROTATION_LOOP_VELOCITY_WEIGHT,
        motion_root_coupled_blocks_enabled=MOTION_ROOT_COUPLED_BLOCKS_ENABLED,
        motion_root_rotation_coupled_blocks_enabled=MOTION_ROOT_ROTATION_COUPLED_BLOCKS_ENABLED,
        probe_enabled=CLIP_PROBE_ENABLED,
        probe_step_deg=CLIP_PROBE_STEP_DEG,
        probe_top_k=CLIP_PROBE_TOP_K,
        probe_min_improvement=CLIP_PROBE_MIN_IMPROVEMENT,
        adaptive_blocks_enabled=CLIP_ADAPTIVE_BLOCKS_ENABLED,
        adaptive_block_size=CLIP_ADAPTIVE_BLOCK_SIZE,
        adaptive_rounds=CLIP_ADAPTIVE_ROUNDS,
        adaptive_step_deg=CLIP_ADAPTIVE_STEP_DEG,
        adaptive_beam_width=CLIP_ADAPTIVE_BEAM_WIDTH,
        polish_enabled=CLIP_POLISH_ENABLED,
        polish_rounds=CLIP_POLISH_ROUNDS,
        polish_step_deg=CLIP_POLISH_STEP_DEG,
        sensitivity_enabled=bool(globals().get("CLIP_SENSITIVITY_ENABLED", True)),
        sensitivity_score_epsilon=float(
            globals().get("CLIP_SENSITIVITY_SCORE_EPSILON", 0.002)
        ),
        polish_include_neighbors=bool(
            globals().get("CLIP_POLISH_INCLUDE_NEIGHBORS", True)
        ),
        rotation_vector_search_enabled=ROTATION_VECTOR_SEARCH_ENABLED,
        rotation_vector_probe_count=ROTATION_VECTOR_PROBE_COUNT,
        rotation_vector_probe_step_deg=ROTATION_VECTOR_PROBE_STEP_DEG,
        directional_continuation_enabled=DIRECTIONAL_CONTINUATION_ENABLED,
        directional_max_steps=DIRECTIONAL_MAX_STEPS,
        directional_step_multiplier=DIRECTIONAL_STEP_MULTIPLIER,
        directional_top_k=DIRECTIONAL_TOP_K,
        directional_min_improvement=DIRECTIONAL_MIN_IMPROVEMENT,
        bone_twist_policy=BONE_TWIST_POLICY,
        bone_twist_overrides=dict(BONE_TWIST_OVERRIDES),
        bone_vectors=dict(BONE_VECTORS),
        adaptive_groups=tuple(
            tuple(group)
            for group in _couple_motion_root_blocks(
                _multi_bone_blocks(
                    [
                        bone
                        for bone in selected_bones
                        if bone not in {MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY}
                    ]
                )
            )
            if group
        ),
    )

    def score_frame(frame, pose, label, live_for_score):
        return _score_multibone_pose(
            int(frame),
            pose,
            label,
            live_for_score,
        )

    def score_frame_batch(
        frame,
        entries,
        *,
        incumbent_score=None,
        required_image_scores=None,
    ):
        return _score_multibone_pose_batch(
            int(frame),
            entries,
            incumbent_score=incumbent_score,
            required_image_scores=required_image_scores,
            proxy_stage="clip_batch",
        )

    result = _optimize_clip_state(
        frames,
        selected_bones,
        initial_poses,
        score_frame,
        range_for,
        config,
        score_frame_batch=score_frame_batch,
        # Preserve the shared sink so warm-start and global evaluations use
        # one notebook bar instead of creating a second, disconnected bar.
        progress=progress,
        live_preview=live,
    )
    result["performance"] = performance_snapshot()
    print(
        "clip performance: "
        f"scoreCache={result['performance']['scoreCacheHits']} hits/"
        f"{result['performance']['scoreCacheMisses']} misses, "
        f"semanticCache={result['performance']['semanticEmbeddingCacheHits']} hits/"
        f"{result['performance']['semanticEmbeddingCacheMisses']} misses, "
        f"denseGridCache={result['performance']['denseGridCacheHits']} hits/"
        f"{result['performance']['denseGridCacheMisses']} misses, "
        f"globalEncode={result['performance']['semanticGlobalSeconds']:.2f}s, "
        f"denseEncode={result['performance']['semanticDenseSeconds']:.2f}s, "
        f"denseCompare={result['performance']['semanticDenseCompareSeconds']:.2f}s, "
        f"workerRender={result['performance']['workerRenderSeconds']:.2f}s/"
        f"{result['performance']['workerRenderCount']} renders, "
        f"workerRead={result['performance']['workerReadSeconds']:.2f}s, "
        f"artifactCopy={result['performance']['workerArtifactCopySeconds']:.2f}s, "
        f"imageCache={result['performance']['semanticImageCacheHits']} hits/"
        f"{result['performance']['semanticImageCacheMisses']} misses, "
        f"boundPrunes={result['performance']['semanticBranchBoundPrunes']}"
    )
    return result


def _emit_clip_progress(progress, event):
    """Forward warm-start work to the same sink used by the global solver."""
    if progress is None or progress is False:
        return
    if isinstance(progress, ClipProgress):
        progress.emit(event)
    elif callable(progress):
        progress(event)
    elif hasattr(progress, "update"):
        progress.update(1)


def prepare_clip_initial_poses(
    frame_indices=None,
    initial_poses=None,
    bones=None,
    *,
    progress=None,
):
    """Build only the initial state for global fitting.

    ``previous`` is deliberately an optional warm start, not a temporal
    objective.  The global solver still scores every accepted proposal against
    the complete clip objective.  ``bind`` is useful for a clean ablation.
    """

    if initial_poses is not None:
        return copy.deepcopy(initial_poses)
    frames = list(FRAME_INDICES if frame_indices is None else frame_indices)
    selected_bones = list(pilot_bones if bones is None else bones)
    if CLIP_WARM_START == "bind":
        return {}
    seed_pose = globals().get("pose0")
    if CLIP_WARM_START == "frame0":
        if not seed_pose:
            raise RuntimeError(
                "CLIP_WARM_START='frame0' requires run_frame0_pilot before clip fitting"
            )
        return {int(frame): copy.deepcopy(seed_pose) for frame in frames}

    warm_fn = (
        optimize_frame_semantic
        if SEMANTIC_ONLY and SEMANTIC_OPTIMIZER
        else optimize_frame
    )
    warm_poses = {}
    warm_previous = copy.deepcopy(seed_pose) if (SEED_FROM_PREVIOUS and seed_pose) else None
    for frame in frames:
        frame = int(frame)
        if frame == 0 and seed_pose:
            warm_pose = copy.deepcopy(seed_pose)
        else:
            warm_pose, _history, _seconds, _timings = warm_fn(
                frame,
                initial=warm_previous if SEED_FROM_PREVIOUS else None,
                bones=selected_bones,
                # The clip-level bar owns warm-start progress. Nested bone bars
                # corrupt the notebook output and make the clip look stalled.
                progress=False,
                live_preview=False,
            )
            _emit_clip_progress(
                progress,
                {
                    "kind": "warm_start",
                    "stage": "warm start",
                    "frame": frame,
                    "label": f"warm start f{frame:02d}",
                },
            )
        warm_poses[frame] = copy.deepcopy(warm_pose)
        warm_previous = copy.deepcopy(warm_pose) if SEED_FROM_PREVIOUS else None
    return warm_poses


def run_clip_optimization(
    frame_indices=None,
    initial_poses=None,
    bones=None,
    progress=None,
    live_preview=None,
):
    """Prepare a warm start and execute the global clip objective once."""

    frames = list(FRAME_INDICES if frame_indices is None else frame_indices)
    progress_owner = None
    progress_sink = progress
    if progress is True or progress is None:
        progress_owner = ClipProgress(progress, description="Clip pilot")
        progress_sink = progress_owner
    try:
        warm_poses = prepare_clip_initial_poses(
            frames,
            initial_poses,
            bones=bones,
            progress=progress_sink,
        )
        result = optimize_clip(
            frame_indices=frames,
            initial_poses=warm_poses,
            bones=bones,
            progress=progress_sink,
            live_preview=live_preview,
        )
        globals()["clip_result"] = result
        globals()["clip_poses"] = result["poses"]
        if 0 in result["poses"]:
            globals()["pose0"] = result["poses"][0]
        return result
    finally:
        if progress_owner is not None:
            progress_owner.close()


# Search-bone preparation

# Pilot only: expand to `order` after reviewing timing and deformation.
# Set LIVE_PREVIEW=False above for headless speed.
pilot_bones = filter_search_bones(
    order,
    descendant_count=order_groups.get("descendantCount") or {},
    bone_length=order_groups.get("boneLength") or {},
    skip_tiny=SKIP_TINY_BONES,
)
print(
    f"search bones: {len(pilot_bones)}/{len(order)} "
    f"(skip_tiny={SKIP_TINY_BONES}, axes={SEARCH_AXES}, "
    f"coarse={COARSE_STEP_DEG}, refine={REFINE_STEP_DEG})"
)
