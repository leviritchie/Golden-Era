# Source-owned setup sections. Executed by roc_semantic_hybrid_experiment.initialize; do not run directly.

from pathlib import Path
import concurrent.futures
import hashlib
import json, math, subprocess, time, os, sys, tempfile
import numpy as np
from PIL import Image

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
sys.path.insert(0, str(TOOL))
import importlib
import pose_fit_auto

importlib.reload(pose_fit_auto)
from pose_fit_auto import (
    branch_walk_order,
    build_dependency_order,
    build_range_table,
    filter_search_bones,
)
from roc_geometric_proxy import load_asset as load_geometric_proxy_asset, validate_bind_pose
from pose_fit_blender import resolve_pose_fit_blender
from alpha_shadow_cull import (
    ALPHA_SHADOW_CULL_VERSION as _ALPHA_SHADOW_CULL_VERSION,
    alpha_cull_signature as _alpha_cull_signature,
    cull_alpha_shadows,
)

# --- This test's inputs (swap per unit; not solver logic) ---
PILOT = ROOT / "artifacts/roc_pose_pipeline/smart_rig_move_pilot"
SRC_GLB = Path(r"C:/Users/<user>/Downloads/griffon_smart_rigged.glb")
RAW_ANIMATION_TARGET_FRAMES = PILOT / "frames_ground_truth"
ANIMATION_TARGET_FRAMES = PILOT / "frames_ground_truth_shadow_culled"
TARGET_FRAMES = ANIMATION_TARGET_FRAMES
TARGET_DEPTH = PILOT / "frames_ground_truth_depth_vda"  # Video Depth Anything, near=bright
def configured_path(value, default_name):
    path = Path(value if value is not None else default_name)
    return path if path.is_absolute() else PILOT / path

REVERSE_RAW_TARGET_FRAMES = configured_path(
    globals().get("REVERSE_RAW_TARGET_FRAMES"), "frames_src_reverse_profile"
)
REVERSE_TARGET_FRAMES = configured_path(
    globals().get("REVERSE_TARGET_FRAMES"), "frames_src_reverse_profile_shadow_culled"
)
REVERSE_TARGET_DEPTH = configured_path(
    globals().get("REVERSE_TARGET_DEPTH"), "frames_src_depth_vda_reverse"
)
CAMERA_FIT = PILOT / "roc_sprite_camera_fit.json"
WORKER = TOOL / "roc_chroma_match_worker.py"
BLENDER = resolve_pose_fit_blender()
WIDTH, HEIGHT = 768, 683

# Semantic-enabled pilot: the worker renders true RGB candidates for the
# encoder while its configured geometry objective remains part of the score.
SCORE_MODE = "chroma"
DEPTH_MAX_DIST = 0.99         # soft depth agreement falloff in [0,1]
COLOR_MAX_DIST = 0.30         # only used if SCORE_MODE == "chroma"
# Blue = pred-only spill. 1.0 = normal IoU; >1 penalizes mesh outside sprite more.
PRED_ONLY_PENALTY = 2.5
# Red = target-only miss. 1.0 preserves the previous implicit red-zone weight.
TARGET_ONLY_PENALTY = 1.0
# Extra multiplier applied only at the target silhouette rim; 0 preserves the current edge weighting.
SILHOUETTE_EDGE_BONUS = 0.0
# 0.5 is symmetric. 1.0 makes the primary/right-view score own the image-right half
# and the reverse/left-view score own the image-left half.
PROFILE_HALF_BIAS = 0.5
# Compound = simultaneous local Euler on SEARCH_AXES. Sparse joint proposals + CD refine.
# Blender bones aim along +Y (shaft). Skipping Y in SEARCH_AXES is not enough: X+Z still
# induces roll — worker strips twist about the bone shaft when EXCLUDE_BONE_ROLL is set.
# Alternatives: "cascade" / "probe_one" / "full" (single-axis only winners).
EXCLUDE_BONE_ROLL = True
ROLL_AXIS = "y"  # bone-length axis in Blender
# Search all local axes. Twist removal uses each bone's actual rest-space shaft;
# a global Y exclusion is not valid for arbitrary imported rigs.
SEARCH_AXES = ("x", "y", "z")
MULTI_AXIS_MODE = "compound"
AXIS_PROBE_FIRST = True
COARSE_STEP_DEG = 16.0
REFINE_STEP_DEG = 4.0
CASCADE_SECONDARY_FRAC = 0.45
COMPOUND_PAIR_STEP_MULT = 1.0   # pair/triple grid uses coarse_step * this
COMPOUND_CD_ROUNDS = 2          # coordinate-descent refine rounds after joint proposals
SKIP_TINY_BONES = True
assert SRC_GLB.exists() and CAMERA_FIT.exists() and RAW_ANIMATION_TARGET_FRAMES.exists()
print("raw targets:", len(list(RAW_ANIMATION_TARGET_FRAMES.glob("*.png"))), "multiAxis:", MULTI_AXIS_MODE)


# Predicted depth cache

from alpha_shadow_cull import (
    ALPHA_SHADOW_CULL_VERSION as _ALPHA_SHADOW_CULL_VERSION,
    alpha_cull_signature as _alpha_cull_signature,
    cull_alpha_shadows,
)

assert SRC_GLB.exists() and CAMERA_FIT.exists() and RAW_ANIMATION_TARGET_FRAMES.exists()

# Optional target-driven IK. This section runs after RocHybridConfig has been
# injected into the shared namespace. Explicit IK_TARGETS always win;
# otherwise use the authored per-frame bone joints as automatic destinations.
IK_AUTO_TARGETS = bool(globals().get("IK_AUTO_TARGETS", True))
IK_TARGET_SOURCE = globals().get("IK_TARGET_SOURCE")
IK_TARGETS = dict(globals().get("IK_TARGETS", {}) or {})

def _resolve_setup_path(value):
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else PILOT / path

def _load_keypoint_ik_targets(path):
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"unable to read automatic IK target source: {path}") from exc
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if not isinstance(frames, list):
        raise RuntimeError(f"automatic IK target source has no frames list: {path}")
    targets_by_frame = {}
    for fallback_index, frame in enumerate(frames):
        if not isinstance(frame, dict) or not isinstance(frame.get("joints"), dict):
            continue
        frame_index = int(frame.get("frame", fallback_index))
        dimension_source = _resolve_setup_path(frame.get("nn"))
        if dimension_source is None or not dimension_source.is_file():
            dimension_source = RAW_ANIMATION_TARGET_FRAMES / f"{frame_index:02d}.png"
        if not dimension_source.is_file():
            continue
        with Image.open(dimension_source) as image:
            width, height = float(image.width), float(image.height)
        if width <= 0.0 or height <= 0.0:
            continue
        frame_targets = {}
        for bone_name, joint in frame["joints"].items():
            if not isinstance(joint, dict) or "x" not in joint or "y" not in joint:
                continue
            x = float(joint["x"]) / width
            y = float(joint["y"]) / height
            if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
                frame_targets[str(bone_name)] = {"x": x, "y": y}
        if frame_targets:
            targets_by_frame[frame_index] = frame_targets
    return targets_by_frame

if (
    IK_AUTO_TARGETS
    and bool(globals().get("IK_ENABLED", False))
    and str(globals().get("IK_MODE", "off")).lower() != "off"
    and not IK_TARGETS
):
    target_candidates = []
    explicit_source = _resolve_setup_path(IK_TARGET_SOURCE)
    if explicit_source is not None:
        target_candidates.append(explicit_source)
    target_candidates.append(PILOT / "keypoints.json")
    target_candidates.extend(sorted(PILOT.glob("keypoints*.json")))
    for candidate in target_candidates:
        if candidate.is_file():
            IK_TARGETS = _load_keypoint_ik_targets(candidate)
            if IK_TARGETS:
                IK_TARGET_SOURCE = candidate
                break
    if not IK_TARGETS:
        raise RuntimeError(
            f"IK_MODE={globals().get('IK_MODE')} has no explicit targets and automatic target inference found no usable keypoints; "
            f"expected {PILOT / 'keypoints.json'} or set ik_target_source"
        )
    requested_frames = tuple(globals().get("FRAME_INDICES", ()))
    missing_frames = [frame for frame in requested_frames if frame not in IK_TARGETS]
    if missing_frames:
        preview = ", ".join(str(frame) for frame in missing_frames[:8])
        suffix = "..." if len(missing_frames) > 8 else ""
        raise RuntimeError(f"automatic IK targets are missing requested frame(s): {preview}{suffix}")
    print("automatic IK targets:", len(IK_TARGETS), "frames from", IK_TARGET_SOURCE)


raw_sources, culled_targets = cull_alpha_shadows(RAW_ANIMATION_TARGET_FRAMES, ANIMATION_TARGET_FRAMES)
TARGET_FRAMES = ANIMATION_TARGET_FRAMES
print("alpha-shadow-culled targets:", len(culled_targets), "target lane:", TARGET_FRAMES)

if bool(globals().get("REVERSE_PROFILE_ENABLED", False)):
    if not REVERSE_RAW_TARGET_FRAMES.exists():
        REVERSE_RAW_TARGET_FRAMES.mkdir(parents=True, exist_ok=True)
        for source in RAW_ANIMATION_TARGET_FRAMES.glob("*.png"):
            mirrored = Image.open(source).convert("RGBA").transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            mirrored.save(REVERSE_RAW_TARGET_FRAMES / source.name, format="PNG")
        print("reverse profile source frames derived from primary frames:", len(list(REVERSE_RAW_TARGET_FRAMES.glob("*.png"))))
    _, reverse_culled_targets = cull_alpha_shadows(REVERSE_RAW_TARGET_FRAMES, REVERSE_TARGET_FRAMES)
    print("reverse profile targets:", len(reverse_culled_targets))

from run_vda_movement_depth import (
    PIPELINE_CACHE_VERSION,
    VDA_MODEL_ID,
    assert_vda_pipeline_cache,
    comparison_vda_run_dir,
    ensure_vda_pipeline_cache,
)

sources = sorted(ANIMATION_TARGET_FRAMES.glob("*.png"))
assert sources, f"no target frames in {TARGET_FRAMES}"
depth_signature = _alpha_cull_signature(ANIMATION_TARGET_FRAMES, sources)
unit_name = str(globals().get("UNIT_NAME") or "")
animation_name = str(globals().get("ANIMATION_NAME") or "")
comparison_run = (
    comparison_vda_run_dir(ROOT, unit_name, animation_name)
    if unit_name and animation_name and globals().get("RIFE_LAB_FRAME_DIR") is None
    else None
)
if comparison_run is not None and not comparison_run.is_dir():
    comparison_run = None
vda_fps = float(globals().get("DEPTH_VIDEO_FPS", 12.0))
vda_cache = ensure_vda_pipeline_cache(
    ANIMATION_TARGET_FRAMES,
    TARGET_DEPTH,
    import_run_dir=comparison_run,
    fps=vda_fps,
)
print(
    f"Video Depth Anything cache {vda_cache['status']}: {TARGET_DEPTH} "
    f"({vda_cache['frame_count']} frames)"
)
print("frames:", len(sources), "depth maps:", len(list(TARGET_DEPTH.glob("*.png"))))
assert_vda_pipeline_cache(TARGET_DEPTH)

if bool(globals().get("REVERSE_PROFILE_ENABLED", False)):
    reverse_sources = sorted(REVERSE_TARGET_FRAMES.glob("*.png"))
    assert reverse_sources, f"no reverse profile target frames in {REVERSE_TARGET_FRAMES}"
    REVERSE_TARGET_DEPTH.mkdir(parents=True, exist_ok=True)
    reverse_signature = hashlib.sha256(
        json.dumps(
            {
                "primary": depth_signature,
                "reverse": _alpha_cull_signature(REVERSE_TARGET_FRAMES, reverse_sources),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    reverse_manifest_path = REVERSE_TARGET_DEPTH / ".reverse_depth_cache_manifest.json"
    try:
        reverse_manifest = json.loads(reverse_manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reverse_manifest = None
    reverse_manifest_matches = (
        isinstance(reverse_manifest, dict)
        and reverse_manifest.get("version") == PIPELINE_CACHE_VERSION
        and reverse_manifest.get("model") == VDA_MODEL_ID
        and reverse_manifest.get("derivedFrom") == "horizontal_flip_of_primary_vda"
        and reverse_manifest.get("sourceSignature") == reverse_signature
        and {path.name for path in REVERSE_TARGET_DEPTH.glob("*.png")} >= {
            source.name for source in reverse_sources
        }
    )
    reverse_need = (
        [p for p in reverse_sources if not (REVERSE_TARGET_DEPTH / p.name).is_file()]
        if reverse_manifest_matches
        else list(reverse_sources)
    )
    if not reverse_manifest_matches:
        expected_reverse_names = {source.name for source in reverse_sources}
        for stale in REVERSE_TARGET_DEPTH.glob("*.png"):
            if stale.name not in expected_reverse_names:
                stale.unlink(missing_ok=True)
    for source in reverse_need:
        primary_depth = TARGET_DEPTH / source.name
        if not primary_depth.is_file():
            raise RuntimeError(f"primary depth missing before reverse flip: {primary_depth}")
        depth = np.asarray(Image.open(primary_depth)).copy()
        depth = np.fliplr(depth)
        Image.fromarray(depth).save(REVERSE_TARGET_DEPTH / source.name, format="PNG")
    if len(list(REVERSE_TARGET_DEPTH.glob("*.png"))) != len(reverse_sources):
        raise RuntimeError("reverse profile depth cache is incomplete")
    reverse_manifest_path.write_text(
        json.dumps(
            {
                "version": PIPELINE_CACHE_VERSION,
                "model": VDA_MODEL_ID,
                "derivedFrom": "horizontal_flip_of_primary_vda",
                "sourceSignature": reverse_signature,
                "frameNames": [source.name for source in reverse_sources],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("reverse VDA depth maps:", len(list(REVERSE_TARGET_DEPTH.glob("*.png"))))


# Bone range placeholders

# Populated by the worker init cell.
order = []
RANGE_BY_BONE = {}
order_groups = {}

def range_for(name):
    return RANGE_BY_BONE.get(name, (-90.0, 90.0))

def bone_side(name):
    if name in order_groups.get("near", []):
        return "near"
    if name in order_groups.get("far", []):
        return "far"
    return "center"

print("run the worker init cell to populate order / ranges")


# Persistent Blender worker and hierarchy init

class BlenderWorker:
    def __init__(self):
        self._stderr_path = Path(tempfile.mkstemp(prefix="roc_blender_", suffix=".stderr.log")[1])
        self._stderr = self._stderr_path.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [str(BLENDER), "-b", "--python", str(WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            bufsize=1,
        )

    def request(self, command):
        if self.proc.poll() is not None:
            details = self._stderr_path.read_text(encoding="utf-8", errors="replace")[-8000:]
            raise RuntimeError({"ok": False, "error": "Blender worker exited before request", "returncode": self.proc.returncode, "stderr": details})
        self.proc.stdin.write(json.dumps(command) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                self._stderr.flush()
                details = self._stderr_path.read_text(encoding="utf-8", errors="replace")[-8000:]
                raise RuntimeError({"ok": False, "error": "Blender worker exited", "returncode": self.proc.poll(), "command": command.get("cmd"), "stderr": details})
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    def close(self):
        try:
            if self.proc.poll() is None:
                self.request({"cmd": "quit"})
                self.proc.wait(timeout=10)
        finally:
            self._stderr.close()

class BlenderWorkerPool:
    """Persistent Blender processes for independent candidate renders."""

    def __init__(self, first_worker, init_command, count, first_init_result=None):
        self.workers = [first_worker]
        self._executor = None
        self.last_init_results = []
        if first_init_result is not None:
            self.last_init_results.append(first_init_result)
        requested = max(1, int(count))
        for _ in range(1, requested):
            worker = BlenderWorker()
            result = worker.request(dict(init_command))
            if not result.get("ok"):
                worker.close()
                self.close()
                raise RuntimeError({"ok": False, "error": "worker pool init failed", "result": result})
            self.workers.append(worker)
            self.last_init_results.append(result)
        if len(self.workers) > 1:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=len(self.workers),
                thread_name_prefix="roc-blender",
            )

    def request_batch(self, commands):
        commands = list(commands)
        if not commands:
            return []
        if len(self.workers) == 1:
            return [self.workers[0].request(command) for command in commands]
        # Keep one request outstanding per Blender stdin pipe, but refill a
        # worker as soon as it finishes. Fixed waves leave fast workers idle
        # behind the slowest render in each wave.
        results = [None] * len(commands)
        active = {}
        next_index = 0
        for worker_index, worker in enumerate(self.workers):
            if next_index >= len(commands):
                break
            future = self._executor.submit(worker.request, commands[next_index])
            active[future] = (worker_index, next_index)
            next_index += 1
        try:
            while active:
                done, _ = concurrent.futures.wait(
                    tuple(active),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    worker_index, command_index = active.pop(future)
                    results[command_index] = future.result()
                    if next_index < len(commands):
                        worker = self.workers[worker_index]
                        replacement = self._executor.submit(worker.request, commands[next_index])
                        active[replacement] = (worker_index, next_index)
                        next_index += 1
        except BaseException:
            # A failed worker request must not leave queued replacements alive.
            # Running requests cannot be force-cancelled by Future.cancel(), so
            # the owning experiment's close() remains responsible for process
            # teardown after the error is surfaced.
            for future in active:
                future.cancel()
            raise
        return results

    def reinitialize(self, init_command):
        """Apply a new clip setup while keeping an unchanged mesh resident.

        The worker still receives the authoritative ``init`` contract, but
        marks it as ``reuseAsset``. Blender then resets clip-owned camera,
        compositor, and pose state without reimporting the GLB. A changed
        mesh path or content hash fails closed in the worker so the caller can
        recycle the pool instead of silently fitting the wrong asset.
        """

        if not self.workers:
            raise RuntimeError("cannot reinitialize an empty Blender worker pool")
        commands = []
        for _ in self.workers:
            command = dict(init_command)
            command["reuseAsset"] = True
            commands.append(command)
        try:
            results = self.request_batch(commands)
        except BaseException:
            self.close()
            raise
        failures = [result for result in results if not result.get("ok")]
        if failures:
            self.close()
            raise RuntimeError({"ok": False, "error": "worker reinit failed", "results": results})
        self.last_init_results = results
        return results

    def close(self):
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None
        for worker in reversed(self.workers):
            worker.close()
        self.workers = []

init_command = {
        "cmd": "init",
        "src": str(SRC_GLB),
        "fit": str(CAMERA_FIT),
    "autoFrame0Fit": bool(globals().get("AUTO_FRAME0_CAMERA_FIT", True)),
    "frame0Target": str(
        (
            ANIMATION_TARGET_FRAMES
            if (ANIMATION_TARGET_FRAMES / "00.png").is_file()
            else RAW_ANIMATION_TARGET_FRAMES
        )
        / "00.png"
    ),
    "frame0AlphaThreshold": int(globals().get("FRAME0_FIT_ALPHA_THRESHOLD", 8)),
    "frame0FitMargin": float(globals().get("FRAME0_FIT_MARGIN", 1.04)),
    "frame0FitPasses": int(globals().get("FRAME0_FIT_PASSES", 2)),
        "width": WIDTH,
        "height": HEIGHT,
        "searchScale": float(globals().get("SEARCH_BUFFER_SCALE", 0.35)),
        "meshScale": float(globals().get("SEARCH_SCALE", 1.0)),
        "semanticMultiview": bool(globals().get("SEMANTIC_MULTIVIEW", True)),
        "semanticViewAnglesDeg": list(globals().get("SEMANTIC_VIEW_ANGLES_DEG", (0.0, 180.0, 90.0))),
        "semanticViewElevationsDeg": list(globals().get("SEMANTIC_VIEW_ELEVATIONS_DEG", (0.0, 0.0, 12.0))),
        "semanticViewWeights": list(globals().get("SEMANTIC_VIEW_WEIGHTS", (1.0, 1.0, 1.0))),
        "searchEngine": (
            "BLENDER_EEVEE"
            if str(globals().get("RENDER_LIGHTING_MODE", "flat_emission")).lower() == "sun_above"
            else "BLENDER_WORKBENCH"
        ),
        "searchTaaSamples": 1,
        "proofEngine": "BLENDER_EEVEE",
        "proofTaaSamples": 8,
        "lightingMode": str(globals().get("RENDER_LIGHTING_MODE", "flat_emission")),
        "sunEnergy": float(globals().get("RENDER_SUN_ENERGY", 2.0)),
        "sunAzimuthDeg": float(globals().get("RENDER_SUN_AZIMUTH_DEG", -35.0)),
        "sunElevationDeg": float(globals().get("RENDER_SUN_ELEVATION_DEG", 55.0)),
        "sunAngleDeg": float(globals().get("RENDER_SUN_ANGLE_DEG", 5.0)),
        "scoreMode": SCORE_MODE,
        "renderDepth": (
            bool(globals().get("RENDER_DEPTH_FOR_SCORING"))
            if globals().get("RENDER_DEPTH_FOR_SCORING") is not None
            else bool(
                (
                    globals().get("HYBRID_GEOMETRY_ENABLED", True)
                    and float(globals().get("HYBRID_GEOMETRY_WEIGHT", 0.0) or 0.0) > 0.0
                )
                or globals().get("REVERSE_PROFILE_ENABLED", False)
                or (
                    (
                        globals().get("ANATOMICAL_BOXES_ENABLED", False)
                        or globals().get("SHOW_ANATOMICAL_BOXES", False)
                    )
                    and globals().get("ANATOMICAL_LATERALITY_ENABLED", True)
                    and globals().get("ANATOMICAL_LATERALITY_SOURCE", "depth") == "depth"
                )
            )
        ),
        "renderResultInMemory": bool(globals().get("RENDER_RESULT_IN_MEMORY", False)),
        "renderPngCompression": int(globals().get("RENDER_PNG_COMPRESSION", 0)),
        "incrementalPoseApplication": bool(globals().get("INCREMENTAL_POSE_APPLICATION", True)),
        "depthMaxDist": DEPTH_MAX_DIST,
        "colorMaxDist": COLOR_MAX_DIST,
        "predOnlyPenalty": float(globals().get("BLUE_ZONE_PENALTY", globals().get("PRED_ONLY_PENALTY", 2.5))),
        "targetOnlyPenalty": float(globals().get("RED_ZONE_PENALTY", globals().get("TARGET_ONLY_PENALTY", 1.0))),
        "targetEdgeSigmaPx": float(globals().get("TARGET_EDGE_SIGMA_PX", 4.0)),
        "targetEdgeFloor": float(globals().get("TARGET_EDGE_FLOOR", 0.25)),
        "targetEdgeBonus": float(globals().get("SILHOUETTE_EDGE_BONUS", 0.0)),
        "silhouetteDepthWeight": float(globals().get("SILHOUETTE_DEPTH_WEIGHT", 1.0)),
        "reverseProfileEnabled": bool(globals().get("REVERSE_PROFILE_ENABLED", False)),
        "reverseProfileWeight": float(globals().get("REVERSE_PROFILE_WEIGHT", 0.5)),
        "profileHalfBias": float(globals().get("PROFILE_HALF_BIAS", 0.5)),
        "ikEnabled": bool(globals().get("IK_ENABLED", False)),
        "ikMode": str(globals().get("IK_MODE", "off")),
        "ikBones": list(globals().get("IK_BONES", ())),
        "ikTargets": dict(globals().get("IK_TARGETS", {})),
        "ikChainLength": int(globals().get("IK_CHAIN_LENGTH", 1)),
        "ikIterations": int(globals().get("IK_ITERATIONS", 8)),
        "ikStrength": float(globals().get("IK_STRENGTH", 1.0)),
        "ikDepth": float(globals().get("IK_DEPTH", 6.0)),
        "detectProfile": bool(globals().get("DETECT_PROFILE_ENABLED", True)),
        "meshOrientationMode": str(globals().get("MESH_ORIENTATION_MODE", "none")),
        "profileSamples": int(globals().get("PROFILE_SAMPLES", 72)),
        # Whole-model motion is applied by the worker's dedicated parent above
        # the armature. Values searched in the solver are body-length units.
        "motionRootEnabled": bool(globals().get("MOTION_ROOT_ENABLED", False)),
        "motionRootAxes": list(globals().get("MOTION_ROOT_AXES", ("forward",))),
        "motionRootForwardRadiusBodyLengths": float(
            globals().get("MOTION_ROOT_FORWARD_RADIUS_BODY_LENGTHS", 0.20)
        ),
        "motionRootLateralRadiusBodyLengths": float(
            globals().get("MOTION_ROOT_LATERAL_RADIUS_BODY_LENGTHS", 0.05)
        ),
        "motionRootVerticalRadiusBodyLengths": float(
            globals().get("MOTION_ROOT_VERTICAL_RADIUS_BODY_LENGTHS", 0.0)
        ),
        "motionRootRotationEnabled": bool(
            globals().get("MOTION_ROOT_ROTATION_ENABLED", False)
        ),
        "motionRootRotationBasis": str(
            globals().get("MOTION_ROOT_ROTATION_BASIS", "camera")
        ),
        "motionRootRotationAxes": list(
            globals().get(
                "MOTION_ROOT_ROTATION_AXES",
                ("camera_forward",),
            )
        ),
        "motionRootRotationLimitDeg": float(
            globals().get("MOTION_ROOT_ROTATION_LIMIT_DEG", 180.0)
        ),
        # Strip twist about bone shaft after each delta (X+Z Euler still induces roll).
        "stripBoneRoll": (
            False
            if str(globals().get("BONE_TWIST_POLICY", "adaptive")).lower() == "include"
            else True
            if str(globals().get("BONE_TWIST_POLICY", "adaptive")).lower() == "exclude"
            else bool(globals().get("EXCLUDE_BONE_ROLL", True))
        ),
        "stripBoneRollByBone": dict(globals().get("BONE_TWIST_OVERRIDES", {}) or {}),
    }
persistent_worker_pool = globals().get("PERSISTENT_WORKER_POOL")
if persistent_worker_pool is None:
    worker = BlenderWorker()
    init_result = worker.request(init_command)
    assert init_result["ok"], init_result
    worker_pool_owned = True
else:
    worker_pool = persistent_worker_pool
    init_results = worker_pool.reinitialize(init_command)
    init_result = init_results[0]
    worker = worker_pool.workers[0]
    worker_pool_owned = False


def _close_init_workers():
    """Close every worker when setup fails before an experiment owns them."""

    if persistent_worker_pool is not None:
        persistent_worker_pool.close()
    else:
        worker.close()


expected_mesh = Path(SRC_GLB).expanduser().resolve()
reported_mesh = Path(str(init_result.get("sourceMesh", ""))).expanduser().resolve()
if reported_mesh != expected_mesh:
    _close_init_workers()
    raise RuntimeError(
        "Blender initialized a different mesh than the picker selected: "
        f"selected={expected_mesh} reported={reported_mesh}"
    )
mesh_digest = hashlib.sha256()
with expected_mesh.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        mesh_digest.update(chunk)
expected_mesh_sha256 = mesh_digest.hexdigest()
if init_result.get("sourceMeshSha256") != expected_mesh_sha256:
    _close_init_workers()
    raise RuntimeError(
        "Blender mesh identity hash mismatch: "
        f"selected={expected_mesh_sha256} reported={init_result.get('sourceMeshSha256')}"
    )
print("Blender selected mesh:", str(expected_mesh), "sha256:", expected_mesh_sha256)

# The geometric proxy is intentionally initialized only after Blender has
# completed frame-00 camera fitting.  That makes its orthographic projection
# use the same fitted camera as the authoritative worker render, while the
# candidate path itself remains Blender-free.
geometric_proxy_asset = None
geometric_proxy_camera = None
geometric_proxy_root_context = None
geometric_proxy_bind_report = None
geometric_proxy_width = geometric_proxy_height = 0
gpu_pose_advisor = None
gpu_pose_advisor_report = None
if bool(
    globals().get("PROXY_ENABLED", False)
    or globals().get("GPU_POSE_ADVISOR_ENABLED", False)
):
    from roc_geometric_proxy import evaluate_batch as evaluate_geometric_proxy_batch

    geometric_proxy_asset = load_geometric_proxy_asset(expected_mesh)
    geometric_proxy_bind_report = validate_bind_pose(
        geometric_proxy_asset,
        level=1,
        tolerance=1e-4,
    )
    if not geometric_proxy_bind_report.get("ok"):
        _close_init_workers()
        raise RuntimeError(
            "geometric proxy bind validation failed; refusing to use an unverified "
            f"candidate prefilter: {geometric_proxy_bind_report}"
        )
    proxy_width, proxy_height = tuple(
        int(value) for value in globals().get("PROXY_RESOLUTION", (96, 86))
    )
    actual_search_width = int(init_result.get("searchWidth", WIDTH))
    actual_search_height = int(init_result.get("searchHeight", HEIGHT))
    ortho_scale = float(init_result.get("cameraOrthoScale", 0.0))
    camera_location = np.asarray(init_result.get("cameraLocation", ()), dtype=np.float64)
    camera_right = np.asarray(init_result.get("right", ()), dtype=np.float64)
    camera_up = np.asarray(init_result.get("up", ()), dtype=np.float64)
    camera_forward = np.asarray(init_result.get("view", ()), dtype=np.float64)
    if (
        ortho_scale <= 0.0
        or camera_location.shape != (3,)
        or camera_right.shape != (3,)
        or camera_up.shape != (3,)
        or camera_forward.shape != (3,)
    ):
        _close_init_workers()
        raise RuntimeError(
            "geometric proxy requires the fitted worker camera contract "
            "(cameraLocation, cameraOrthoScale, right, up, view)"
        )
    # Worker ``up`` is screen-up.  The proxy uses image-down coordinates so
    # projected y values line up with PIL alpha masks without a second flip.
    camera_down = -camera_up / max(np.linalg.norm(camera_up), 1e-12)
    camera_right = camera_right / max(np.linalg.norm(camera_right), 1e-12)
    camera_forward = camera_forward / max(np.linalg.norm(camera_forward), 1e-12)
    pixels_per_world = actual_search_height / ortho_scale
    proxy_pixels_per_world = pixels_per_world * proxy_height / max(actual_search_height, 1)
    geometric_proxy_camera = {
        "right": camera_right.tolist(),
        "up": camera_down.tolist(),
        "forward": camera_forward.tolist(),
        "pxPerWorld": float(proxy_pixels_per_world),
        "screenOffset": [
            float(proxy_width / 2.0 - np.dot(camera_location, camera_right) * proxy_pixels_per_world),
            float(proxy_height / 2.0 - np.dot(camera_location, camera_down) * proxy_pixels_per_world),
        ],
    }
    motion_root_info = init_result.get("motionRoot") or {}
    motion_root_rotation = motion_root_info.get("rotation") or {}
    geometric_proxy_root_context = {
        "basis": dict(motion_root_info.get("basis") or {}),
        "referenceLengthWorld": float(
            motion_root_info.get("referenceLengthWorld", 1.0)
        ),
        "rotation": {
            "basisVectors": dict(motion_root_rotation.get("basisVectors") or {}),
            "pivot": list(motion_root_rotation.get("pivot") or (0.0, 0.0, 0.0)),
        },
    }
    geometric_proxy_width = proxy_width
    geometric_proxy_height = proxy_height
    print(
        "geometric proxy:",
        {
            "backend": globals().get("PROXY_DEVICE", "auto"),
            "resolution": (proxy_width, proxy_height),
            "minCandidates": int(globals().get("PROXY_MIN_CANDIDATES", 8)),
            "protectedStages": tuple(globals().get("PROXY_PROTECTED_STAGES", ()) or ()),
            "audit": {
                "enabled": bool(globals().get("PROXY_AUDIT_ENABLED", False)),
                "fraction": float(globals().get("PROXY_AUDIT_FRACTION", 0.10)),
                "maxCandidates": int(globals().get("PROXY_AUDIT_MAX_CANDIDATES", 4)),
            },
            "gpuTensorCache": bool(globals().get("PROXY_GPU_TENSOR_CACHE_ENABLED", True)),
            "vertices": sum(len(primitive.positions) for primitive in geometric_proxy_asset.primitives),
            "bind": geometric_proxy_bind_report,
            "meshScale": float(globals().get("SEARCH_SCALE", 1.0)),
            "orthoScale": ortho_scale,
        },
    )
if bool(globals().get("GPU_POSE_ADVISOR_ENABLED", False)):
    if geometric_proxy_camera is None or geometric_proxy_root_context is None:
        _close_init_workers()
        raise RuntimeError(
            "GPU pose advisor requires the fitted worker camera and motion-root contract"
        )
    from roc_gpu_pose_advisor import GpuPoseAdvisor

    try:
        gpu_pose_advisor = GpuPoseAdvisor.from_runtime(
            expected_mesh,
            ANIMATION_TARGET_FRAMES,
            camera=geometric_proxy_camera,
            root_context=geometric_proxy_root_context,
            mesh_scale=float(globals().get("SEARCH_SCALE", 1.0)),
            device=str(globals().get("GPU_POSE_ADVISOR_DEVICE", "cuda")),
            resolution=(geometric_proxy_width, geometric_proxy_height),
            max_points=int(globals().get("GPU_POSE_ADVISOR_MAX_POINTS", 6000)),
            sdf_weight=float(globals().get("GPU_POSE_ADVISOR_SDF_WEIGHT", 1.0)),
            centroid_weight=float(globals().get("GPU_POSE_ADVISOR_CENTROID_WEIGHT", 0.35)),
            extent_weight=float(globals().get("GPU_POSE_ADVISOR_EXTENT_WEIGHT", 0.25)),
            min_gradient_norm=float(globals().get("GPU_POSE_ADVISOR_MIN_GRADIENT_NORM", 1e-5)),
            medium_sensitivity_ratio=float(
                globals().get("GPU_POSE_ADVISOR_MEDIUM_SENSITIVITY_RATIO", 0.08)
            ),
            high_sensitivity_ratio=float(
                globals().get("GPU_POSE_ADVISOR_HIGH_SENSITIVITY_RATIO", 0.35)
            ),
            orthogonal_count=int(globals().get("GPU_POSE_ADVISOR_ORTHOGONAL_COUNT", 1)),
            root_hypothesis_count=int(globals().get("GPU_POSE_ADVISOR_ROOT_HYPOTHESIS_COUNT", 256)),
            root_keep=int(globals().get("GPU_POSE_ADVISOR_ROOT_KEEP", 8)),
            seed=int(globals().get("GPU_POSE_ADVISOR_SEED", 17)),
            rigidization_report=globals().get("MESHY_RIGIDIZATION_REPORT"),
            frame_indices=tuple(globals().get("FRAME_INDICES", ())),
        )
    except Exception:
        _close_init_workers()
        raise
    gpu_pose_advisor_report = gpu_pose_advisor.summary()
    print("GPU pose advisor:", gpu_pose_advisor_report)
if persistent_worker_pool is None:
    worker_pool = BlenderWorkerPool(
        worker,
        init_command,
        int(globals().get("RENDER_WORKER_COUNT", 1))
        if bool(globals().get("PARALLEL_CANDIDATE_RENDERING", True))
        else 1,
        first_init_result=init_result,
    )
worker_identity_results = list(
    getattr(worker_pool, "last_init_results", ()) or (init_result,)
)
for worker_index, worker_result in enumerate(worker_identity_results):
    reported_worker_mesh = Path(str(worker_result.get("sourceMesh", ""))).expanduser().resolve()
    if reported_worker_mesh != expected_mesh:
        worker_pool.close()
        raise RuntimeError(
            "Blender worker initialized a different mesh than the picker selected: "
            f"worker={worker_index} selected={expected_mesh} reported={reported_worker_mesh}"
        )
    if worker_result.get("sourceMeshSha256") != expected_mesh_sha256:
        worker_pool.close()
        raise RuntimeError(
            "Blender worker mesh identity hash mismatch: "
            f"worker={worker_index} selected={expected_mesh_sha256} "
            f"reported={worker_result.get('sourceMeshSha256')}"
        )
print("Blender render workers:", len(worker_pool.workers))
print(
    "Blender asset lifecycle:",
    "resident mesh reused" if init_result.get("assetReused") else "fresh GLB import",
)

print(
    "score controls:",
    {
        "blueZonePenalty": init_result.get("predOnlyPenalty"),
        "redZonePenalty": init_result.get("targetOnlyPenalty"),
        "edgeBonus": init_result.get("targetEdgeBonus"),
        "profileHalfBias": init_result.get("profileHalfBias"),
        "renderDepthDefault": init_result.get("renderDepthDefault"),
        "compositorMode": init_result.get("compositorMode"),
        "renderPngCompression": init_result.get("renderPngCompression"),
        "lightingMode": init_result.get("lightingMode"),
        "sunEnergy": init_result.get("sunEnergy"),
        "sunElevationDeg": init_result.get("sunElevationDeg"),
    },
)
print(
    "camera/profile:",
    init_result.get("profileDetection") or "fit basis",
    "mesh orientation:",
    init_result.get("meshOrientation") or "not reported",
)
print("frame-00 camera fit:", init_result.get("frame0Fit") or "disabled/not provisional")
print(
    "motion root:",
    init_result.get("motionRoot") or "disabled/not reported",
)
if (
    bool(globals().get("IK_ENABLED", False))
    and str(globals().get("IK_MODE", "off")).lower() == "replace_all"
):
    print(
        "warning: IK replace_all disables rotation search; "
        "zone penalties can change the reported score but cannot change the selected pose "
        "unless the IK target/pose changes."
    )

bones = init_result["bones"]
BONE_VECTORS = {
    str(name): tuple(float(part) for part in vector)
    for name, vector in dict(init_result.get("boneVectors", {}) or {}).items()
}
missing_bone_vectors = [name for name in bones if name not in BONE_VECTORS]
if missing_bone_vectors:
    raise RuntimeError(
        "Blender worker did not return rest-space vectors for bones: "
        f"{missing_bone_vectors[:8]}"
    )
order, order_groups = build_dependency_order(
    bones,
    parents=init_result["parents"],
    heads=init_result["boneHeads"],
    view=init_result["view"],
    right=init_result["right"],
)

# Keep dependency ordering as the safe default, but let the notebook choose a
# reproducible explicit order for pilots and ablation tests.
_bone_order_mode = str(globals().get("BONE_ORDER_MODE", "dependency")).lower()
_explicit_bone_order = [str(name) for name in globals().get("BONE_ORDER", ())]
_requested_search_bones = [str(name) for name in globals().get("SEARCH_BONES", ())]
if _bone_order_mode == "alphabetical":
    order = sorted(order)
elif _bone_order_mode == "reverse_dependency":
    order = list(reversed(order))
elif _bone_order_mode == "explicit":
    unknown = [name for name in _explicit_bone_order if name not in bones]
    if unknown:
        raise ValueError(f"BONE_ORDER contains unknown bones: {unknown}")
    remainder = [name for name in order if name not in _explicit_bone_order]
    order = _explicit_bone_order + remainder
elif _bone_order_mode == "branch_walk":
    _branch_camera_bias = str(
        globals().get("BRANCH_WALK_CAMERA_BIAS", "none")
    ).strip().lower()
    if _branch_camera_bias not in {"none", "default_camera"}:
        raise ValueError(
            "BRANCH_WALK_CAMERA_BIAS must be none or default_camera"
        )
    order, _branch_order_details = branch_walk_order(
        order,
        parents=init_result["parents"],
        heads=init_result["boneHeads"],
        view=init_result["view"],
        camera_bias=_branch_camera_bias,
    )
    order_groups.update(_branch_order_details)
elif _bone_order_mode != "dependency":
    raise ValueError(
        "BONE_ORDER_MODE must be dependency, reverse_dependency, alphabetical, explicit, or branch_walk"
    )
if _requested_search_bones:
    unknown = [name for name in _requested_search_bones if name not in bones]
    if unknown:
        raise ValueError(f"SEARCH_BONES contains unknown bones: {unknown}")
    selected = set(_requested_search_bones)
    if bool(globals().get("INCLUDE_UNLISTED_SEARCH_BONES", True)):
        order = [name for name in order if name in selected] + [name for name in order if name not in selected]
    else:
        order = [name for name in order if name in selected]
CHILDREN_BY_BONE = {name: [] for name in bones}
for child, parent in init_result["parents"].items():
    if child in CHILDREN_BY_BONE and parent in CHILDREN_BY_BONE:
        CHILDREN_BY_BONE[parent].append(child)
RANGE_BY_BONE = build_range_table(
    bones,
    parents=init_result["parents"],
    heads=init_result["boneHeads"],
    # locked=order_groups["locked"],
    locked=[],
    unrestricted=True,
    # Keep the broad search range configurable for motion-range diagnostics;
    # the experiment config owns the value so this remains unit-agnostic.
    free_deg=float(globals().get("JOINT_FREE_DEG", 90.0)),
)

def range_for(name):
    return RANGE_BY_BONE.get(name, (-90.0, 90.0))

def bone_side(name):
    if name in order_groups.get("near", []):
        return "near"
    if name in order_groups.get("far", []):
        return "far"
    return "center"

print(
    "bones:", len(bones),
    "scoreMode:", init_result.get("scoreMode"),
    "locked:", order_groups["locked"],
    "hubCut:", order_groups.get("hubDescendantCut"),
    "orderMode:", order_groups.get("orderMode"),
    "branches:", order_groups.get("branchCount", "n/a"),
    "branchBias:", order_groups.get("branchCameraBias", "none"),
    "inside-out:", order[:10],
    "leaves-last:", order[-6:],
    "search:", init_result["searchWidth"], "x", init_result["searchHeight"],
)
desc = order_groups.get("descendantCount") or {}
heavy = sorted(
    [b for b in order if abs(range_for(b)[1]) > 1e-6],
    key=lambda b: (-desc.get(b, 0), b),
)[:8]
print(
    "heaviest unlocked:",
    [(b, desc.get(b), range_for(b)) for b in heavy],
)


# Optional anatomical detector

# LOCAL_GPU_ANATOMICAL_BOX_STAGE
# The notebook executes this setup source repeatedly in one kernel.  Reload
# the source-owned helper so a newly added scorer is not shadowed by a stale
# module object left in sys.modules from an earlier initialize() call.
import importlib
import roc_anatomical_boxes as _roc_anatomical_boxes
_roc_anatomical_boxes = importlib.reload(_roc_anatomical_boxes)
from roc_anatomical_boxes import (
    PartBox,
    RocAnatomicalBoxDetector,
    FIXED_PART_LIBRARY,
    anatomical_feature_alignment,
    draw_boxes,
    draw_feature_dot_preview,
    select_prominent_features,
    write_boxes,
)
PART_BOX_MODEL_ID = 'IDEA-Research/grounding-dino-tiny'
ANATOMICAL_BOXES_ENABLED = bool(globals().get("ANATOMICAL_BOXES_ENABLED", False))
ANATOMICAL_PART_WEIGHT = float(globals().get("ANATOMICAL_PART_WEIGHT", 0.20))
HYBRID_ANATOMICAL_WEIGHT = float(globals().get("HYBRID_ANATOMICAL_WEIGHT", 0.0))
ANATOMICAL_MAX_FEATURES = int(globals().get("ANATOMICAL_MAX_FEATURES", 8))
ANATOMICAL_MIN_AREA_FRAC = float(globals().get("ANATOMICAL_MIN_AREA_FRAC", 0.001))
ANATOMICAL_CENTER_WEIGHT = float(globals().get("ANATOMICAL_CENTER_WEIGHT", 0.70))
ANATOMICAL_EXTENT_WEIGHT = float(globals().get("ANATOMICAL_EXTENT_WEIGHT", 0.30))
ANATOMICAL_LATERALITY_ENABLED = bool(globals().get("ANATOMICAL_LATERALITY_ENABLED", True))
# Biological side is derived from the profile-camera depth ordering. The
# current authored Roc profile is bird-right, so its camera-near side is R.
ANATOMICAL_LATERALITY_SOURCE = str(globals().get("ANATOMICAL_LATERALITY_SOURCE", "depth")).lower().strip()
ANATOMICAL_LATERALITY_NEAR_SIDE = str(
    globals().get("ANATOMICAL_LATERALITY_NEAR_SIDE", "R")
).upper().strip()
ANATOMICAL_LATERALITY_DEPTH_MARGIN = float(
    globals().get("ANATOMICAL_LATERALITY_DEPTH_MARGIN", 0.04)
)
ANATOMICAL_LATERALITY_CENTER_MARGIN_FRAC = float(
    globals().get("ANATOMICAL_LATERALITY_CENTER_MARGIN_FRAC", 0.025)
)
PART_BOX_OUT = PILOT / 'roc_anatomical_boxes'
PART_BOX_OUT.mkdir(parents=True, exist_ok=True)
ANATOMICAL_CANDIDATE_OUT = PART_BOX_OUT / 'candidate_render.png'
ANATOMICAL_CANDIDATE_DEPTH_OUT = PART_BOX_OUT / 'candidate_depth.png'
ANATOMICAL_PREVIEW_OUT = PART_BOX_OUT / 'live_feature_dots.png'
# If anatomical identification is enabled, the live pilot should expose the
# evidence that it is actually running.  Keep the explicit flag for preview
# only when detection is disabled, but do not silently hide identified parts.
SHOW_ANATOMICAL_BOXES = bool(
    globals().get("SHOW_ANATOMICAL_BOXES", False)
    or ANATOMICAL_BOXES_ENABLED
)
# Detection is controlled independently from preview drawing. This lets the
# optimizer score anatomy while keeping the live panels uncluttered.
detector = RocAnatomicalBoxDetector(model_id=PART_BOX_MODEL_ID) if (ANATOMICAL_BOXES_ENABLED or SHOW_ANATOMICAL_BOXES) else None  # CUDA only
PART_BOXES_BY_FRAME = {}
def normalized_boxes(boxes, width, height):
    return [
        {
            'part': b.part,
            'side': b.side,
            'box': (b.box[0]/width, b.box[1]/height, b.box[2]/width, b.box[3]/height),
            'score': b.score,
        }
        for b in boxes
    ]
def detect_target_boxes(frame_index):
    source = ANIMATION_TARGET_FRAMES / f'{frame_index:02d}.png'
    image = Image.open(source).convert('RGBA')
    depth_path = TARGET_DEPTH / f'{frame_index:02d}.png'
    laterality_depth = None
    if ANATOMICAL_LATERALITY_ENABLED and ANATOMICAL_LATERALITY_SOURCE == 'depth':
        if not depth_path.is_file():
            raise FileNotFoundError(f'anatomical laterality depth is missing: {depth_path}')
        laterality_depth = Image.open(depth_path).copy()
    boxes = select_prominent_features(
        detector.detect(
            image,
            laterality_enabled=ANATOMICAL_LATERALITY_ENABLED,
            laterality_depth=laterality_depth,
            laterality_near_side=ANATOMICAL_LATERALITY_NEAR_SIDE,
            laterality_depth_margin=ANATOMICAL_LATERALITY_DEPTH_MARGIN,
            laterality_center_margin_frac=ANATOMICAL_LATERALITY_CENTER_MARGIN_FRAC,
        ),
        width=image.width,
        height=image.height,
        max_features=ANATOMICAL_MAX_FEATURES,
        min_area_frac=ANATOMICAL_MIN_AREA_FRAC,
    )
    PART_BOXES_BY_FRAME[frame_index] = normalized_boxes(boxes, image.width, image.height)
    draw_boxes(image, boxes, PART_BOX_OUT / f'sprite_{frame_index:02d}_boxes.png', f'sprite frame {frame_index:02d} selected features')
    write_boxes(PART_BOX_OUT / f'sprite_{frame_index:02d}_boxes.json', boxes, image=source, device='cuda:0', model_id=PART_BOX_MODEL_ID)
if ANATOMICAL_BOXES_ENABLED or SHOW_ANATOMICAL_BOXES:
    for frame_index in tuple(globals().get("FRAME_INDICES", ())):
        detect_target_boxes(frame_index)
    print(
        'detected target box frames:', len(PART_BOXES_BY_FRAME),
        'scoring:', ANATOMICAL_BOXES_ENABLED,
        'preview:', SHOW_ANATOMICAL_BOXES,
        'library:', FIXED_PART_LIBRARY,
    )
else:
    print('anatomical box detector disabled')
