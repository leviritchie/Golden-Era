# Source-owned full-frame delivery loop. Executed by run_full_animation; do not run directly.

MATCH_OUT = Path(globals().get("MATCH_OUT", PILOT / "roc_hybrid_match_v1"))
MATCH_OUT.mkdir(parents=True, exist_ok=True)

# Same refreshing preview as the pilot cell (target | render | IoU).
LIVE_PREVIEW = bool(globals().get("LIVE_PREVIEW", True))
all_history = []
previous = globals().get("pose0") if SEED_FROM_PREVIOUS else None
clip_result = None
clip_poses = {}
if CLIP_OPTIMIZATION_ENABLED:
    # Warm starts are initialization only. The final acceptance decision is
    # always made by the complete clip objective in run_clip_optimization.
    clip_result = run_clip_optimization(
        frame_indices=FRAME_INDICES,
        bones=pilot_bones,
        progress=True,
        live_preview=LIVE_PREVIEW,
    )
    clip_poses = clip_result["poses"]
    print(
        "global clip fit complete:",
        f"objective={clip_result['objective']:.6f}",
        f"evaluations={clip_result['evaluations']}",
        f"accepted={clip_result['accepted']}",
        f"elapsed={clip_result['elapsed']:.2f}s",
    )

# Full original movement sequence; SEMANTIC_ONLY selects the image score, not
# the frame count. With global clip fitting enabled, this loop only renders the
# committed joint solution produced above.
for frame_index in FRAME_INDICES:
    print(f"=== starting frame {frame_index:02d}/{len(FRAME_INDICES) - 1:02d} ===")
    if CLIP_OPTIMIZATION_ENABLED:
        pose = clip_poses[int(frame_index)]
        frame_result = clip_result.get("frameResults", {}).get(int(frame_index), {})
        history = [{
            "kind": "global_clip_frame",
            "frame": int(frame_index),
            "objective": clip_result.get("objective"),
            "objectiveDetails": clip_result.get("objectiveDetails"),
            "imageScore": clip_result.get("frameScores", {}).get(int(frame_index)),
        }]
        seconds = float(frame_result.get("elapsed", 0.0)) if isinstance(frame_result, dict) else 0.0
        _timings = clip_result.get("timings", [])
    else:
        pose, history, seconds, _timings = (optimize_frame_semantic if SEMANTIC_ONLY and SEMANTIC_OPTIMIZER else optimize_frame)(
            frame_index,
            initial=previous if SEED_FROM_PREVIOUS else None,
            bones=pilot_bones,
            progress=True,
            live_preview=LIVE_PREVIEW,
        )
        previous = pose if SEED_FROM_PREVIOUS else None
    out = MATCH_OUT / f"frame_{frame_index:02d}.png"
    worker.request({"cmd": "set_pose", "angles": pose})
    # Proof still at full-res Eevee; preview panel stays on last search composite.
    worker.request({"cmd": "save_render", "out": str(out)})
    if SHOW_ANATOMICAL_BOXES:
        mesh_boxes = detector.detect(Image.open(out))
        draw_boxes(Image.open(out), mesh_boxes, PART_BOX_OUT / f'mesh_{frame_index:02d}_boxes.png', f'mesh frame {frame_index:02d} local CUDA boxes')
        write_boxes(PART_BOX_OUT / f'mesh_{frame_index:02d}_boxes.json', mesh_boxes, image=out, device='cuda:0', model_id=PART_BOX_MODEL_ID)
    else:
        mesh_boxes = []
    mesh_part_boxes = [b.as_dict() for b in mesh_boxes]
    def _pose_public(p):
        out = {}
        for k, v in p.items():
            if isinstance(v, dict):
                if "axis" in v:
                    out[k] = {"axis": v["axis"], "angle": float(v["angle"])}
                elif any(axis in v for axis in ("forward", "lateral", "vertical")):
                    out[k] = {
                        axis: float(v.get(axis, 0.0))
                        for axis in ("forward", "lateral", "vertical")
                    }
                elif any(
                    axis in v
                    for axis in ("camera_forward", "camera_right", "camera_up")
                ):
                    out[k] = {
                        axis: float(v.get(axis, 0.0))
                        for axis in ("camera_forward", "camera_right", "camera_up")
                    }
                else:
                    out[k] = {
                        "x": float(v.get("x", 0.0)),
                        "y": float(v.get("y", 0.0)),
                        "z": float(v.get("z", 0.0)),
                    }
            else:
                out[k] = {"axis": "z", "angle": float(v)}
        return out

    all_history.append({
        "frame": frame_index,
        "seconds": seconds,
        "history": history,
        "pose": _pose_public(pose),
        "ikTargets": _frame_ik_targets(frame_index) if IK_TARGET_SEARCH_ENABLED else None,
        "meshPartBoxes": mesh_part_boxes,
        "clipOptimization": clip_result.get("config") if clip_result else None,
        "clipObjective": clip_result.get("objective") if clip_result else None,
        "clipObjectiveDetails": clip_result.get("objectiveDetails") if clip_result else None,
    })
    if LIVE_PREVIEW:
        if PREVIEW_PATH.exists():
            update_live_preview_image()
        print(
            f"frame {frame_index:02d} done in {seconds:.1f}s  "
            f"wrote {out.name}  trials={sum(int(h.get('trials', 0)) for h in history)}"
        )

(MATCH_OUT / "report.json").write_text(
    json.dumps(
        {
            "frames": all_history,
            "scoreMode": SCORE_MODE,
            "depthMaxDist": DEPTH_MAX_DIST,
            "score": "hybrid_enabled_components",
            "semanticModel": SEMANTIC_MODEL_ID,
            "semanticDenseEnabled": SEMANTIC_DENSE_ENABLED,
            "semanticDenseModel": str(SEMANTIC_DENSE_MODEL_ID),
            "semanticDenseLayers": list(SEMANTIC_DENSE_EMBEDDING_LAYERS),
            "semanticDenseWeight": SEMANTIC_DENSE_WEIGHT,
            "semanticDenseLocalRadius": SEMANTIC_DENSE_LOCAL_RADIUS,
            "semanticDensePositionWeight": SEMANTIC_DENSE_POSITION_WEIGHT,
            "semanticEmbeddingLayers": list(SEMANTIC_EMBEDDING_LAYERS),
            "semanticEncoderLayers": list(SEMANTIC_ENCODER_LAYERS),
            "semanticWeight": HYBRID_SEMANTIC_WEIGHT,
            "depthWeight": HYBRID_DEPTH_WEIGHT,
            "geometryWeight": HYBRID_GEOMETRY_WEIGHT,
            "geometryEnabled": HYBRID_GEOMETRY_ENABLED,
            "motionRootEnabled": MOTION_ROOT_ENABLED,
            "motionRootAxes": list(MOTION_ROOT_AXES),
            "motionRootForwardRadiusBodyLengths": MOTION_ROOT_FORWARD_RADIUS_BODY_LENGTHS,
            "motionRootLateralRadiusBodyLengths": MOTION_ROOT_LATERAL_RADIUS_BODY_LENGTHS,
            "motionRootVerticalRadiusBodyLengths": MOTION_ROOT_VERTICAL_RADIUS_BODY_LENGTHS,
            "motionRootCoarseStepBodyLengths": MOTION_ROOT_COARSE_STEP_BODY_LENGTHS,
            "motionRootRefineStepBodyLengths": MOTION_ROOT_REFINE_STEP_BODY_LENGTHS,
            "motionRootMagnitudeWeight": MOTION_ROOT_MAGNITUDE_WEIGHT,
            "motionRootVelocityWeight": MOTION_ROOT_VELOCITY_WEIGHT,
            "motionRootAccelerationWeight": MOTION_ROOT_ACCELERATION_WEIGHT,
            "motionRootLoopWeight": MOTION_ROOT_LOOP_WEIGHT,
            "motionRootLoopVelocityWeight": MOTION_ROOT_LOOP_VELOCITY_WEIGHT,
            "motionRootRotationEnabled": MOTION_ROOT_ROTATION_ENABLED,
            "motionRootRotationBasis": MOTION_ROOT_ROTATION_BASIS,
            "motionRootRotationAxes": list(MOTION_ROOT_ROTATION_AXES),
            "motionRootRotationLimitDeg": MOTION_ROOT_ROTATION_LIMIT_DEG,
            "motionRootRotationCoarseStepDeg": MOTION_ROOT_ROTATION_COARSE_STEP_DEG,
            "motionRootRotationRefineStepDeg": MOTION_ROOT_ROTATION_REFINE_STEP_DEG,
            "motionRootRotationEscapeEnabled": MOTION_ROOT_ROTATION_ESCAPE_ENABLED,
            "motionRootRotationEscapeAxes": list(MOTION_ROOT_ROTATION_ESCAPE_AXES),
            "motionRootRotationEscapeAnglesDeg": list(MOTION_ROOT_ROTATION_ESCAPE_ANGLES_DEG),
             "motionRootRotationEscapeTopK": MOTION_ROOT_ROTATION_ESCAPE_TOP_K,
             "motionRootCoupledBlocksEnabled": MOTION_ROOT_COUPLED_BLOCKS_ENABLED,
             "motionRootRotationCoupledBlocksEnabled": MOTION_ROOT_ROTATION_COUPLED_BLOCKS_ENABLED,
             "motionRootRotationEscapeRelaxEnabled": MOTION_ROOT_ROTATION_ESCAPE_RELAX_ENABLED,
             "motionRootRotationEscapeRelaxBoneCount": MOTION_ROOT_ROTATION_ESCAPE_RELAX_BONE_COUNT,
             "motionRootRotationEscapeRelaxRounds": MOTION_ROOT_ROTATION_ESCAPE_RELAX_ROUNDS,
             "motionRootRotationEscapeRelaxStepDeg": MOTION_ROOT_ROTATION_ESCAPE_RELAX_STEP_DEG,
             "motionRootRotationEscapeRelaxRefineStepDeg": MOTION_ROOT_ROTATION_ESCAPE_RELAX_REFINE_STEP_DEG,
             "motionRootRotationMagnitudeWeight": MOTION_ROOT_ROTATION_MAGNITUDE_WEIGHT,
            "motionRootRotationVelocityWeight": MOTION_ROOT_ROTATION_VELOCITY_WEIGHT,
            "motionRootRotationAccelerationWeight": MOTION_ROOT_ROTATION_ACCELERATION_WEIGHT,
            "motionRootRotationLoopWeight": MOTION_ROOT_ROTATION_LOOP_WEIGHT,
            "motionRootRotationLoopVelocityWeight": MOTION_ROOT_ROTATION_LOOP_VELOCITY_WEIGHT,
            "actionCameraAngleDeg": ACTION_CAMERA_ANGLE_DEG,
            "actionCameraElevationDeg": ACTION_CAMERA_ELEVATION_DEG,
            "detectProfileEnabled": DETECT_PROFILE_ENABLED,
            "textEnabled": SEMANTIC_TEXT_ENABLED,
            "textPrompt": SEMANTIC_TEXT_PROMPT,
            "textWeight": HYBRID_TEXT_WEIGHT,
            "negativeTextEnabled": SEMANTIC_NEGATIVE_TEXT_ENABLED,
            "negativeTextPrompt": SEMANTIC_NEGATIVE_TEXT_PROMPT,
            "negativeTextWeight": HYBRID_NEGATIVE_TEXT_WEIGHT,
            "anatomicalPartWeight": ANATOMICAL_PART_WEIGHT,
            "ikTargetSearchEnabled": IK_TARGET_SEARCH_ENABLED,
            "ikTargetSearchOnly": IK_TARGET_SEARCH_ONLY,
            "ikTargetSearchBones": list(IK_TARGET_SEARCH_BONES),
            "ikTargetCoarseStepPx": IK_TARGET_COARSE_STEP_PX,
            "ikTargetRefineStepPx": IK_TARGET_REFINE_STEP_PX,
            "ikTargetSearchRadiusPx": IK_TARGET_SEARCH_RADIUS_PX,
            "ikTargetMinImprovement": IK_TARGET_MIN_IMPROVEMENT,
            "clipOptimizationEnabled": CLIP_OPTIMIZATION_ENABLED,
            "clipWarmStart": CLIP_WARM_START,
            "clipResult": clip_result,
            "proof": "generated enabled-feature hybrid SigLIP2 plus worker geometry pilot; original frames only",
        },
        indent=2,
    )
)
worker.close()
print("wrote", MATCH_OUT)
