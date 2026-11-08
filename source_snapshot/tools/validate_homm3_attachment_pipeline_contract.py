"""Cheap source/build contract for shared attachment and motion-completion stages."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "experiments" / "homm3_mocap_v2"


def _calls(tree, name):
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == name]


def validate_source(source):
    tree = ast.parse(source)
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    gates = _calls(run, "attachment_quality")
    exports = _calls(run, "write_skinned_glb")
    completion = _calls(run, "apply_motion_completion")
    if len(gates) != 1 or not exports or gates[0].lineno >= min(node.lineno for node in exports):
        raise ValueError("shared attachment gate must run before GLB export")
    if len(completion) != 1 or completion[0].lineno >= gates[0].lineno:
        raise ValueError("explicit motion completion must precede skin fitting/gating")
    assignments = {ast.unparse(node.targets[0]): node.value for node in ast.walk(run)
                   if isinstance(node, ast.Assign) and len(node.targets) == 1}
    candidate = assignments.get("report['candidateValidForExport']", ast.Constant(None))
    expected = ast.parse("bool(report['restContract']['ok'] and report['attachmentGate']['passed'])", mode="eval").body
    if ast.dump(candidate) != ast.dump(expected):
        raise ValueError("export eligibility must require rest and attachment gates")
    rejects = [node for node in ast.walk(run) if isinstance(node, ast.If)
               and ast.unparse(node.test) == "not report['candidateValidForExport']"
               and any(isinstance(child, ast.Continue) for child in ast.walk(node))]
    if not rejects or not any(node.lineno < min(e.lineno for e in exports) for node in rejects):
        raise ValueError("failed candidates must skip GLB export")
    enabled = [node for node in ast.walk(run) if isinstance(node, ast.If)
               and ast.unparse(node.test) == "motion_completion_report is not None"
               and _calls(node, "apply_motion_completion")]
    if not enabled:
        raise ValueError("motion completion must remain explicitly selected")
    if "_frozen_ownership_vertices" not in source or "frozen_vertices=_frozen_ownership_vertices(skin)" not in source:
        raise ValueError("ownership seam vertices must stay frozen during shared weight training")
    if "triangles[incident]" not in source:
        raise ValueError("ownership interface-face vertices must stay frozen during shared weight training")
    quality = (PIPELINE / "attachment_quality.py").read_text(encoding="utf-8")
    if "geometry ownership requires physical_boundary" not in quality:
        raise ValueError("owned attachments must use physical_boundary interfaces")
    return {"attachmentBeforeExport": True, "explicitMotionCompletion": True}


def validate_static_registration_consumption(bind_source, skin_source):
    """Pin accepted-placement ownership without importing the GPU toolchain."""
    tree = ast.parse(bind_source)
    binder = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "prepare_move_bind_capture_bind")
    assignments = {ast.unparse(node.targets[0]): node.value for node in ast.walk(binder)
                   if isinstance(node, ast.Assign) and len(node.targets) == 1}
    for variable, call in (("registration", "require_accepted_static_registration"),
                           ("aligned", "accepted_mesh_alignment")):
        value = assignments.get(variable)
        if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Name) or value.func.id != call:
            raise ValueError(f"bind must retain {call} as {variable}")
    if ast.unparse(assignments["aligned"]) != "accepted_mesh_alignment(registration)":
        raise ValueError("bind alignment must consume the accepted registration")
    if _calls(binder, "semantic_axis_rotation") or _calls(binder, "align_surface_to_rest"):
        raise ValueError("bind must not recompute axes or bbox alignment after acceptance")
    vertex_assignments = [node.value for node in ast.walk(binder) if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == "vertices" for target in node.targets)]
    vertices = vertex_assignments[0] if vertex_assignments else None
    if vertices is None or not {"rotation", "scale", "translation"}.issubset(
            {node.value for node in ast.walk(vertices) if isinstance(node, ast.Constant) and isinstance(node.value, str)}):
        raise ValueError("bind vertices must use the complete accepted similarity")
    if ast.unparse(assignments.get("vertices", ast.Constant(None))) != "vertices.astype(np.float32).astype(np.float64)":
        raise ValueError("bind initializer must use exact exported float32 positions")
    initializers = _calls(binder, "build_initializer_weights")
    if len(initializers) != 1 or not any(arg.arg == "weld_policy" and isinstance(arg.value, ast.Constant)
                                        and arg.value.value == "export_position" for arg in initializers[0].keywords):
        raise ValueError("bind initializer must explicitly share the exported-position weld policy")
    geodesic = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "geodesic_bone_distances")
    welds = [node for node in ast.walk(geodesic) if isinstance(node, ast.If)
             and ast.unparse(node.test) == "weld_policy == 'export_position'"
             and "geodesic[members] = geodesic[members].min(axis=0)" in ast.unparse(node)]
    if len(welds) != 1:
        raise ValueError("export-position geodesic distances must agree before weights and support")
    exports = _calls(binder, "write_skinned_glb")
    if not exports or assignments["aligned"].lineno >= exports[0].lineno:
        raise ValueError("accepted alignment must precede bind export")
    skin = ast.parse(skin_source)
    run = next(node for node in skin.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    gates = _calls(run, "require_bind_registration")
    loads = _calls(run, "load_skin_bundle")
    if len(gates) != 1 or not loads or gates[0].lineno >= loads[0].lineno:
        raise ValueError("skin fitting must verify cached bind registration before loading")
    return {"acceptedStaticPlacementConsumed": True}


def validate_pose_refine_objective(source):
    """Keep rejection constraints in the objective, not just in post-search scoring."""
    tree = ast.parse(source)
    objective = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef) and node.name == "objective")
    for name in ("continuity_hinge_losses", "per_frame_iou_regression_hinge"):
        if len(_calls(objective, name)) != 1:
            raise ValueError(f"pose objective must optimize shared {name}")
    total = next(node.value for node in ast.walk(objective) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "total" for target in node.targets))
    terms = {node.id for node in ast.walk(total) if isinstance(node, ast.Name)}
    if not {"continuity", "frame_regression"}.issubset(terms):
        raise ValueError("pose objective total must include continuity and per-frame regression")
    return {"poseRefineGateAlignedObjective": True}


def validate_sprite_exception_source(source):
    """Explicit diagnostic selection cannot become an automatic delivery fallback."""
    tree = ast.parse(source)
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    detection, field = _calls(run, "detect_conflicts"), _calls(run, "SpriteSurfaceResidual")
    if len(detection) != 1 or len(field) != 1 or detection[0].lineno >= field[0].lineno:
        raise ValueError("surface correction must follow explicit conflict detection")
    required = {"candidate_visible_face_error", "visible_face_coverage", "candidate_visible_face_coverage"}
    if not required.issubset({arg.arg for arg in detection[0].keywords}):
        raise ValueError("exception detector must receive same-face error and visibility provenance")
    if not _calls(run, "fk_world") or not _calls(run, "skin_lbs"):
        raise ValueError("pose conflict trials must reconstruct frozen-skin geometry")
    if _calls(tree, "write_skinned_glb"):
        raise ValueError("surface exception diagnostic cannot export skeletal animation")
    result = next(node.value for node in ast.walk(run) if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == "result" for target in node.targets))
    fields = {key.value: value for key, value in zip(result.keys, result.values) if isinstance(key, ast.Constant)}
    for key in ("accepted", "runtimeExportAvailable", "transitionsValidated"):
        if not isinstance(fields.get(key), ast.Constant) or fields[key].value is not False:
            raise ValueError(f"exception pilot cannot claim {key}")
    return {"explicitSpriteExceptionDiagnostic": True}


def validate_registration_branch_coverage(source):
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    evaluator = functions["evaluate_rigid_compatibility"]
    if len(_calls(evaluator, "evaluate_declared_branch_compatibility")) != 1:
        raise ValueError("rigid registration must screen every declared branch")
    if not _calls(evaluator, "wing_span"):
        raise ValueError("rigid registration must retain actual wing-pair checks")
    conditions = [ast.unparse(node.test) for node in ast.walk(evaluator) if isinstance(node, ast.If)]
    if "wings and (not body)" not in conditions or "not body" in conditions:
        raise ValueError("named body groups must be required only for actual wing checks")
    screen = ast.unparse(functions["evaluate_declared_branch_compatibility"])
    if "groups.items()" not in screen or "failedBranches" not in screen:
        raise ValueError("branch registration screen must enumerate profile groups and report failures")
    return {"registrationDeclaredBranchCoverage": True}


def validate_registration_similarity(source, runner_source):
    """Pin global extent and branch-balanced ranking without importing SciPy."""
    tree = ast.parse(source)
    fit = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == "fit_skeleton_similarity")
    if any(isinstance(node, ast.If) and ast.unparse(node.test) == "not body_idx" for node in ast.walk(fit)):
        raise ValueError("whole-branch similarity must not require legacy body group names")
    body_fields = [value for node in ast.walk(fit) if isinstance(node, ast.Dict)
                   for key, value in zip(node.keys, node.values)
                   if isinstance(key, ast.Constant) and key.value == "bodySurfaceMean"]
    if len(body_fields) != 1 or ast.unparse(body_fields[0]) != "float(distances[body_idx].mean()) if body_idx else None":
        raise ValueError("body-only diagnostic must be explicitly null when not applicable")
    assignments = {ast.unparse(node.targets[0]): ast.unparse(node.value)
                   for node in ast.walk(fit) if isinstance(node, ast.Assign) and len(node.targets) == 1}
    expected = {
        "rotated": "joints @ rotation.T",
        "skeleton_center": "(rotated.max(axis=0) + rotated.min(axis=0)) * 0.5",
        "base_scale": "mesh_span / float(np.linalg.norm(np.ptp(rotated, axis=0)))",
        "extent_bounds": "(0.75, 1.25)",
        "branch_means": "{name: float(distances[members].mean()) for name, members in branches.items()}",
        "score": "float(np.mean(list(branch_means.values())))",
    }
    for name, expression in expected.items():
        if assignments.get(name) != expression:
            raise ValueError(f"registration similarity must retain whole-extent/all-branch {name}")
    conditions = [ast.unparse(node.test) for node in ast.walk(fit) if isinstance(node, ast.If)]
    if "best is None or score < best['branchBalancedSurfaceMean']" not in conditions:
        raise ValueError("registration similarity must rank the branch-balanced score")
    if "not extent_bounds[0] - 1e-09 <= extent_ratio <= extent_bounds[1] + 1e-09" not in conditions:
        raise ValueError("registration similarity must enforce its full-skeleton extent band")
    runner = ast.parse(runner_source)
    run = next(node for node in runner.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    validations = _calls(run, "require_mesh_space_rest_report")
    preserved = _calls(run, "mesh_space_rest_similarity")
    if len(validations) != 1 or len(preserved) != 1 or validations[0].lineno >= preserved[0].lineno:
        raise ValueError("mesh-space rest must verify input provenance before preserving placement")
    branches = [node for node in ast.walk(run) if isinstance(node, ast.If)
                and ast.unparse(node.test) == "rest_provenance is not None"]
    if len(branches) != 1 or not _calls(ast.Module(body=branches[0].body, type_ignores=[]), "mesh_space_rest_similarity") or not _calls(ast.Module(body=branches[0].orelse, type_ignores=[]), "fit_skeleton_similarity"):
        raise ValueError("verified mesh-space rest must select preservation instead of refitting")
    helpers = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name in ("mesh_space_rest_similarity", "fit_skeleton_similarity"):
        if len(_calls(helpers[name], "_complete_joint_branches")) != 1:
            raise ValueError("both registration paths must verify complete unique joint ownership")
    preserve = ast.unparse(helpers["mesh_space_rest_similarity"])
    if "placed = joints @ rotation.T" not in preserve or "'scale': 1.0" not in preserve or "'translation': np.zeros(3)" not in preserve:
        raise ValueError("mesh-space rest must use the mesh rotation without scale/translation refit")
    provenance = ast.unparse(helpers["require_mesh_space_rest_report"])
    for field in ("meshSha256", "captureSha256", "unit", "referenceFrame", "restCoordinateSpace"):
        if repr(field) not in provenance:
            raise ValueError(f"mesh-space rest provenance must verify {field}")
    required = {"branchBalancedSurfaceMean", "branchSurfaceMeans", "skeletonToMeshExtentRatio", "extentRatioBounds", "policy"}
    records = [value for node in ast.walk(runner) if isinstance(node, ast.Dict)
               for key, value in zip(node.keys, node.values)
               if isinstance(key, ast.Constant) and key.value == "skeletonSimilarity" and isinstance(value, ast.Dict)]
    if len(records) != 1:
        raise ValueError("registration must serialize one skeleton similarity record")
    fields = {key.value: ast.unparse(value) for key, value in zip(records[0].keys, records[0].values)
              if isinstance(key, ast.Constant)}
    if any(fields.get(key) != f"similarity[{key!r}]" for key in required):
        raise ValueError("registration must serialize the actual fit policy and objective evidence")
    return {"registrationWholeExtentBranchBalancedFit": True}


def validate():
    fitter_source = (PIPELINE / "run_skin_mesh_pilot.py").read_text(encoding="utf-8")
    result = validate_source(fitter_source)
    result.update(validate_registration_branch_coverage(
        (PIPELINE / "static_bind_registration.py").read_text(encoding="utf-8")))
    result.update(validate_registration_similarity(
        (PIPELINE / "static_bind_registration.py").read_text(encoding="utf-8"),
        (PIPELINE / "run_roc_idle_static_bind.py").read_text(encoding="utf-8")))
    result.update(validate_pose_refine_objective(
        (PIPELINE / "run_roc_wing_pose_refine.py").read_text(encoding="utf-8")))
    result.update(validate_sprite_exception_source(
        (PIPELINE / "run_sprite_exception_pilot.py").read_text(encoding="utf-8")))
    result.update(validate_static_registration_consumption(
        (PIPELINE / "prepare_move_bind_capture_bind.py").read_text(encoding="utf-8"),
        (PIPELINE / "run_move_bind_t2_mocap_skin_fit.py").read_text(encoding="utf-8"),
    ))
    validate_repair_dispatch(fitter_source)
    validate_repair_source((PIPELINE / "run_attachment_repair.py").read_text(encoding="utf-8"))
    validate_skin_refit_source((PIPELINE / "run_attachment_skin_refit.py").read_text(encoding="utf-8"))
    validate_anatomical_source((PIPELINE / "anatomical_chain_skin.py").read_text(encoding="utf-8"))
    validate_joint_anchor_audit_source((PIPELINE / "run_skin_joint_anchor_audit.py").read_text(encoding="utf-8"))
    validate_owned_skinned_lab_source(
        (ROOT / "tools" / "homm3_import" / "unity_editor" / "Homm3OwnedSkinnedLabBuild.cs").read_text(encoding="utf-8")
    )
    validate_runtime_skin_quality_source(
        (ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3ImportVisuals.cs").read_text(encoding="utf-8")
    )
    for name in ("attachment_quality.py", "motion_completion.py", "attachment_repair.py", "attachment_mask_refinement.py", "run_attachment_repair.py",
                 "run_attachment_skin_refit.py", "repair_skin_domain.py", "topology_weight_field.py", "anatomical_chain_skin.py"):
        tree = ast.parse((PIPELINE / name).read_text(encoding="utf-8"))
        unit_literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                         and isinstance(node.value, str) and node.value.startswith(("h3_", "toa_"))]
        if unit_literals:
            raise ValueError(f"shared stage contains unit-specific literals: {name}")
    for name in ("run_surface_loss_attribution.py", "preview_skin_mesh_corpus.py"):
        tree = ast.parse((PIPELINE / name).read_text(encoding="utf-8"))
        if len(_calls(tree, "restore_motion_completion")) != 1:
            raise ValueError(f"fit consumer must restore its explicit completion: {name}")
    project = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "OfflineUnlockMod.csproj"
    root = ET.parse(project).getroot()
    targets = [node for node in root.iter() if node.tag.split('}')[-1] == "Target"
               and node.get("Name") == "ValidateHomm3AttachmentPipelineContract"]
    if len(targets) != 1 or targets[0].get("BeforeTargets") != "BeforeBuild":
        raise ValueError("attachment pipeline contract must run during normal build")
    if not any("validate_homm3_attachment_pipeline_contract.py" in node.get("Command", "") for node in targets[0]):
        raise ValueError("build target does not invoke attachment pipeline validator")
    return {"ok": True, **result, "scope": "source contract; no GPU, generation, or runtime proof"}




def validate_owned_skinned_lab_source(source):
    """Keep fixed current-mocap clips local-TRS faithful in the Unity importer."""
    required = (
        "public string motionAuthority;",
        'bool fixedMocap = spec.motionAuthority == "current_mocap_v2";',
        "fixedMocap || IsLocalRotationProperty(b.propertyName)",
        "if (!fixedMocap)\n                FlattenRotationTangents(copy);",
        "m_LocalPosition.",
        "m_LocalScale.",
        "masterRoot.Find(path)",
    )
    missing = [text for text in required if text not in source]
    if missing:
        raise ValueError("owned skinned lab must preserve fixed mocap local TRS: " + ", ".join(missing))
    if source.index("bool fixedMocap") > source.index("RebaseClipPaths"):
        raise ValueError("fixed mocap mode must be selected before clip rebasing")
    return {"fixedMocapLocalTrs": True}


def validate_runtime_skin_quality_source(source):
    """Pin the explicit capability marker and native global skin-weight cap."""
    required = (
        'SkinWeightsUnlimitedMarkerName = "__homm3_skin_weights_unlimited__"',
        "instance.transform.Find(SkinWeightsUnlimitedMarkerName)",
        "QualitySettings.skinWeights = SkinWeights.Unlimited",
        "skins[i].quality = SkinQuality.Auto",
        "QualitySettings.skinWeights != SkinWeights.Unlimited",
    )
    missing = [text for text in required if text not in source]
    if missing:
        raise ValueError("runtime skin-quality capability marker path is incomplete: " + ", ".join(missing))
    marker_idx = source.index("instance.transform.Find(SkinWeightsUnlimitedMarkerName)")
    cap_idx = source.index("QualitySettings.skinWeights = SkinWeights.Unlimited")
    if cap_idx < marker_idx:
        raise ValueError("global unlimited skin cap must be gated by explicit capability marker")
    return {"explicitSkinWeightCapability": True}


def validate_repair_dispatch(source):
    """Pin explicit post-fit repair dispatch and pre-repair export suppression."""
    tree = ast.parse(source)
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    if not any(arg.arg == "attachment_repair_recipe" for arg in run.args.args + run.args.kwonlyargs):
        raise ValueError("fitter must expose explicit attachment repair dispatch")
    dispatch = [node for node in _calls(run, "run_attachment_repair")]
    if len(dispatch) != 1:
        raise ValueError("fitter must dispatch repair exactly once")
    skin_dispatch = _calls(run, "run_attachment_skin_refit")
    if len(skin_dispatch) != 1 or skin_dispatch[0].lineno <= dispatch[0].lineno:
        raise ValueError("skin refit must dispatch exactly once after topology repair")
    if not any(kw.arg == "anatomical_chain_regions" and isinstance(kw.value, ast.Name)
               and kw.value.id == "anatomical_chain_regions" for kw in skin_dispatch[0].keywords):
        raise ValueError("fitter must forward explicit anatomical chain selection")
    if not any(kw.arg == "joint_anchor_weight" and isinstance(kw.value, ast.Name)
               and kw.value.id == "joint_anchor_weight" for kw in skin_dispatch[0].keywords):
        raise ValueError("fitter must forward explicit joint anchor weight")
    if not any(isinstance(node, ast.If) and ast.unparse(node.test) == "attachment_skin_refit_seconds > 0"
               and _calls(node, "run_attachment_skin_refit") for node in ast.walk(run)):
        raise ValueError("post-split skin refit must remain explicitly enabled")
    exports = _calls(run, "write_skinned_glb")
    skips = [node for node in ast.walk(run) if isinstance(node, ast.If)
             and ast.unparse(node.test) == "attachment_repair_recipe is not None"
             and any(isinstance(child, ast.Continue) for child in ast.walk(node))]
    if not skips or not exports or not any(skip.lineno < export.lineno for skip in skips for export in exports):
        raise ValueError("repair recipe must suppress every pre-repair GLB export")


def validate_repair_source(source):
    tree = ast.parse(source)
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    if not _calls(run, "split_attachment") or not _calls(run, "consolidate_redundant_owner"):
        raise ValueError("repair must use shared topology and ownership stages")
    body_test = ast.parse("body_error > 1e-5", mode="eval").body
    if not any(isinstance(node, ast.If) and ast.dump(node.test) == ast.dump(body_test)
               and any(isinstance(child, ast.Raise) for child in node.body) for node in ast.walk(run)):
        raise ValueError("body motion parity must be enforced unconditionally")
    if _calls(tree, "write_skinned_glb"):
        raise ValueError("unvalidated attachment closure cannot export GLBs")
    assignments = {ast.unparse(node.targets[0]): node.value for node in ast.walk(run)
                   if isinstance(node, ast.Assign) and len(node.targets) == 1}
    if ast.dump(assignments.get("result['candidateValidForExport']", ast.Constant(None))) != ast.dump(ast.Constant(False)):
        raise ValueError("repair export must remain blocked until closure validation exists")
    loader = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "load_repair")
    if not _calls(loader, "split_attachment") or not _calls(loader, "sha256_file"):
        raise ValueError("saved repair must be identity checked and independently reconstructed")
    preview = ast.parse((PIPELINE / "preview_skin_mesh_corpus.py").read_text(encoding="utf-8"))
    if len(_calls(preview, "preview_repair")) != 1:
        raise ValueError("standard corpus preview must consume explicit saved repairs")


def validate_anatomical_source(source):
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    if "_require_body_label_adjacency" not in functions:
        raise ValueError("anatomical routing must define its topology validation helper")
    initializer = ast.unparse(functions["initialize_chain_weights"])
    for check in ("starts = joints[chain[:-1]]", "ends = joints[chain[1:]]",
                  "np.concatenate((chain[:-1], chain[-1:]))",
                  "parent[chain[1:]] != chain[:-1]"):
        if check not in initializer:
            raise ValueError("anatomical initialization must preserve parent-outgoing segment ownership")
    profile = ast.unparse(functions["initialize_profile_chains"])
    if "np.array_equal(weights[prop], skin['weights'][prop])" not in profile:
        raise ValueError("anatomical initialization must preserve frozen attachment weights")
    schema_guards = [node for node in ast.walk(functions["initialize_profile_chains"])
                     if isinstance(node, ast.If) and ast.unparse(node.test) ==
                     "schema not in ('profile-chain-initialization-v1', 'profile-chain-initialization-v2')"]
    if len(schema_guards) != 1 or not any(isinstance(child, ast.Raise) for child in ast.walk(schema_guards[0])):
        raise ValueError("anatomical initializer must admit only v1/v2 schemas")
    if "report['bodyRegionRouting'] = routing" not in profile or "'regions': list(regions)" not in profile:
        raise ValueError("schema2 anatomical report must expose routing without rewriting regions")
    routed_call = [node for node in ast.walk(functions["initialize_profile_chains"])
                   if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name)
                   and node.func.id == "initialize_chain_weights"]
    routing_checks = [node for node in ast.walk(functions["initialize_profile_chains"])
                      if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name)
                      and node.func.id == "_require_body_label_adjacency"]
    last_routed_line = max((node.lineno for node in routed_call), default=-1)
    if not routing_checks or not any(check.lineno < last_routed_line for check in routing_checks):
        raise ValueError("routed anatomical initialization must validate body-region topology first")
    region_writes = [node for node in ast.walk(functions["initialize_profile_chains"])
                     if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
                     for target in ([node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else node.targets)
                     if ast.unparse(target).startswith("skin['regions']")]
    if region_writes:
        raise ValueError("anatomical initialization must not write skin regions")


def validate_joint_anchor_audit_source(source):
    """Pin the saved-skin CPU audit entry points and non-acceptance report."""
    tree = ast.parse(source)
    run = next((node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "run"), None)
    if run is None:
        raise ValueError("joint anchor audit must define run")
    loaders = _calls(run, "load_refit")
    builders = _calls(run, "build_anchors")
    evaluators = _calls(run, "evaluate_anchors")
    if len(loaders) != 1 or len(builders) != 1 or len(evaluators) != 1:
        raise ValueError("joint anchor audit must load refit, build anchors, and evaluate exactly once")
    if not loaders[0].lineno < builders[0].lineno < evaluators[0].lineno:
        raise ValueError("joint anchor audit entry points must run in load/build/evaluate order")
    result_dicts = [node.value for node in ast.walk(run)
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "result"
                            for target in node.targets)]
    if len(result_dicts) != 1 or not isinstance(result_dicts[0], ast.Dict):
        raise ValueError("joint anchor audit must declare a result contract")
    values = {key.value: value for key, value in zip(result_dicts[0].keys, result_dicts[0].values)
              if isinstance(key, ast.Constant)}
    if not isinstance(values.get("accepted"), ast.Constant) or values["accepted"].value is not False:
        raise ValueError("joint anchor audit must remain non-accepting")
    proof = values.get("proof")
    if not isinstance(proof, ast.Constant) or proof.value != "saved-candidate CPU diagnostic; no acceptance or export":
        raise ValueError("joint anchor audit proof must state CPU diagnostic and no acceptance/export")


def validate_skin_refit_source(source):
    """Keep post-split skin repair separate from pose and geometry optimization."""
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    run, loader = functions["run"], functions["load_refit"]
    for name in ("load_repair", "condition_body_welds", "make_repair_domain", "validate_candidate", "initialize_profile_chains"):
        if not _calls(run, name) or not _calls(loader, name):
            raise ValueError(f"skin refit and readback must verify shared {name}")
    run_initializers = [call for call in _calls(run, "initialize_profile_chains")
                        if any(kw.arg == "schema" and isinstance(kw.value, ast.Constant)
                               and kw.value.value == "profile-chain-initialization-v2" for kw in call.keywords)]
    if len(run_initializers) != 1:
        raise ValueError("new skin refits must select profile-chain-initialization-v2 literally")
    loader_initializers = _calls(loader, "initialize_profile_chains")
    if len(loader_initializers) != 1 or not any(
            kw.arg == "schema" and isinstance(kw.value, ast.Subscript)
            and ast.unparse(kw.value) == "report['anatomicalInitialization']['schema']"
            for kw in loader_initializers[0].keywords):
        raise ValueError("skin refit readback must use the stored anatomical initialization schema")
    domain_source = ast.parse((PIPELINE / "repair_skin_domain.py").read_text(encoding="utf-8"))
    domain_builder = next(node for node in domain_source.body
                          if isinstance(node, ast.FunctionDef) and node.name == "make_repair_domain")
    if not _calls(domain_builder, "restore_source_owner_support"):
        raise ValueError("skin domain must reserve source owner evidence before optional neighbors")
    if not any(any(kw.arg == "source_weights_mapped" for kw in call.keywords)
               for call in _calls(run, "make_repair_domain")):
        raise ValueError("new refits must provide original source owner evidence")
    fits = _calls(run, "optimize")
    if len(fits) != 1 or not any(kw.arg == "allow_mesh" and isinstance(kw.value, ast.Constant)
                                 and kw.value.value is False for kw in fits[0].keywords):
        raise ValueError("post-split skin refit must keep rest geometry fixed")
    if len(_calls(run, "RepairWeightField")) != 1 or not _calls(run, "load_refit"):
        raise ValueError("skin repair must use ownership-aware weights and saved readback")
    anchor_builder = next((node for node in functions.values()
                           if isinstance(node, ast.FunctionDef) and node.name == "_anchor_spec"), None)
    if anchor_builder is None or len(_calls(anchor_builder, "build_anchors")) != 1:
        raise ValueError("skin refit anchor helper must reconstruct build_anchors")
    reports = [node for node in ast.walk(anchor_builder) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and node.func.attr == "report"]
    if len(_calls(anchor_builder, "FixedJointAnchorObjective")) != 1 or len(reports) != 1:
        raise ValueError("skin refit anchor helper must validate supported anchors")
    if len(_calls(run, "_anchor_spec")) != 1 or len(_calls(loader, "_anchor_spec")) != 1:
        raise ValueError("skin refit run and readback must share the anchor specification")
    fits = _calls(run, "optimize")
    if len(fits) != 1 or not any(kw.arg == "joint_anchor" for kw in fits[0].keywords) \
            or not any(kw.arg == "joint_anchor_weight" for kw in fits[0].keywords):
        raise ValueError("skin refit optimizer must receive the fixed anchor object and weight")
    if _calls(tree, "write_skinned_glb") or _calls(tree, "apply_motion_completion"):
        raise ValueError("skin repair cannot alter captured motion or export unvalidated surfaces")
    report_dicts = [node.value for node in ast.walk(run) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "report" for target in node.targets)]
    if len(report_dicts) != 1 or not isinstance(report_dicts[0], ast.Dict):
        raise ValueError("skin refit must declare its result contract")
    values = {key.value: value for key, value in zip(report_dicts[0].keys, report_dicts[0].values)
              if isinstance(key, ast.Constant)}
    for key in ("accepted", "candidateValidForExport"):
        if not isinstance(values.get(key), ast.Constant) or values[key].value is not False:
            raise ValueError("skin refit cannot imply surface acceptance")
    validator = ast.unparse(functions["validate_candidate"])
    for check in ("key != 'weights'", "weights[~domain['allowedSupport']] != 0",
                  "np.array_equal(weights[frozen], original['weights'][frozen])",
                  "np.array_equal(weights[vertex], weights[groups[key]])"):
        if check not in validator:
            raise ValueError("skin refit must enforce immutable rest data, support, and frozen ownership")
    preview = ast.parse((PIPELINE / "preview_skin_mesh_corpus.py").read_text(encoding="utf-8"))
    if len(_calls(preview, "preview_skin_refit")) != 1:
        raise ValueError("standard preview must consume the saved skin-refit candidate")


if __name__ == "__main__":
    print(json.dumps(validate()))
