#!/usr/bin/env python3
"""Source contract for the Unity queue runner (docs/unity_queue_runner.md). Agents must submit, not launch.

Checks:
  * every switched caller launches Unity only through tools/unity_queue (no unitylock / Unity.exe command of its own),
    and keeps --unity-direct as the only, explicit opt-out;
  * every command-line caller (it still builds a `Unity.exe -batchmode ...` list) hands that list to run_cmd() and
    never launches it, or a unitylock wrapper, itself;
  * no other tools/ script builds a -batchmode command line: a new one must be switched, or listed in
    LEGACY_UNSWITCHED with its reason (the list may only shrink);
  * every queue-compatible builder carries the UnityQueueArgs()/UnityQueueExit() shim and no raw
    Environment.GetCommandLineArgs() / EditorApplication.Exit( outside it (either would read the dispatcher's command
    line or quit the whole batch);
  * the dispatcher refuses shim-less classes, records one result line per job and continues past a failed job;
  * the runner fails closed (no direct-launch fallback), takes the shared unitylock lock and runs the preflight.
Source/static only: it does not launch Unity.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALLERS = {
    "tools/homm3_town_scene_meshes/stronghold_full3d_scene.py": "def unity(",
    "tools/homm3_town_scene_meshes/build_conflux_full3d_scene.py": "def unity(",
    "tools/homm3_town_scene_meshes/build_town_scene3d_bundle.py": "def unity_job(",
    "tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py": "def unity(",
}
# Callers that keep their Unity command line and hand it to run_cmd(); value = the marker of that hand-off.
CMD_CALLERS = {
    "tools/homm3_import/build_homm2_shade_object_class_shader_bundle.py": "UQ.run_cmd(",
    "tools/homm3_import/build_homm3_artifact_map_billboard_bundle.py": "UQ.run_cmd(",
    "tools/homm3_import/build_homm3_artifact_meshes_bundle.py": "UQ.run_cmd(",
    "tools/homm3_import/build_homm3_billboard_bundle.py": "UQ.run_cmd(",
    "tools/homm3_import/build_homm3_dialog_portrait_bundle.py": "UQ.run_cmd(",
    "tools/homm3_import/build_homm3_map_building_meshes_bundle.py": "UQ.run_cmd(",
    "tools/homm3_import/build_homm3_tower_city_map_mesh_bundle.py": "UQ.run_cmd(",
    "tools/homm3_import/build_homm3_ui_portrait_bundle.py": "UQ.run_cmd(",
    "tools/homm3_import/build_homm3_town_scene_meshes_bundle.py": "UQ.run_cmd(",
    "tools/homm3_import/owned_skinned_facing_proof.py": "UQ.run_cmd(",
    "tools/homm3_vfx/build_vfx_lab.py": "UQ.run_cmd(",
    "tools/homm3_vfx/titan_light_lab.py": "UQ.run_cmd(",
    "tools/homm3_vfx/volfire_unity_lab.py": "UQ.run_cmd(",
    "tools/homm3_vfx/oceanid_unity_lab.py": "UQ.run_cmd(",
    "tools/homm3_vfx/vanilla_style_lab.py": "UQ.run_cmd(",
    "tools/homm3_map_building_meshes/preview_map_building_anim.py": "UQ.run_cmd(",
    "tools/homm3_map_building_meshes/preview_map_building_fx.py": "UQ.run_cmd(",
    "tools/homm3_town_scene_meshes/build_conflux_town3d_preview.py": "UQ.run_cmd(",
    "tools/homm3_import/preview_unit_vfx.py": "_unity_queue().run_cmd(",
    "tools/homm3_import/run_beholder_attack_contour_v14.py": "_unity_queue().run_cmd(",
    "tools/homm3_silhouette_pose_fit/run_stronghold_prebaked_install_overnight.py": "uq.run_cmd(",
    "tools/homm3_import/build_homm3_units.sh": 'unity_queue.py" submit --wait',
}
# Callers that call launch() with a method + args (no command line of their own).
LAUNCH_CALLERS_EXTRA = {
    "tools/homm3_import/remap_owned_attack_slots.py": "def unity(",
}
# Still launch Unity themselves. Reason per entry; switch one and delete its line. Never add a line to pass.
LEGACY_UNSWITCHED = {
    "tools/build_homm3_town_prefabs.ps1": "2026-07 legacy town-prefab driver, superseded by the 3D town lane",
    "tools/custom_prefab_pipeline/build_esquire_bundle.cmd": "2026-07 legacy esquire pilot",
    "tools/custom_prefab_pipeline/build_esquire_bundle.sh": "2026-07 legacy esquire pilot",
    "tools/homm3_import/build_homm3_array_prototype.cmd": "2026-07 legacy Lane B .cmd driver",
    "tools/homm3_import/build_homm3_array_timing_test.cmd": "2026-07 legacy Lane B .cmd driver",
    "tools/homm3_import/build_homm3_array_upscale_shader_bundle.cmd": "2026-07 legacy Lane B .cmd driver",
    "tools/homm3_import/build_homm3_map_rife_pilot.cmd": "2026-07 legacy Lane B .cmd driver",
    "tools/homm3_import/build_homm3_skeleton_idle_tail_lead.cmd": "2026-07 legacy Lane B .cmd driver",
    "tools/homm3_import/build_homm3_units.cmd": "2026-07 legacy Lane B .cmd twin of build_homm3_units.sh (switched)",
    "tools/homm3_import/build_remaining_faction_bundles.cmd": "2026-07 legacy Lane B .cmd driver",
    "tools/homm3_import/run_homm3_array_timing_bundle_batches.cmd": "2026-07 legacy Lane B .cmd driver",
    "tools/homm3_import/run_homm3_rife_production.cmd": "2026-07 legacy Lane B .cmd driver",
    "tools/homm3_town_prefabs/build_homm3_town_prefabs.cmd": "2026-07 legacy town-prefab driver",
    "tools/homm3_import/preview_beholder_exact_core_unity.py": "another agent's untracked work in progress",
    "tools/homm3_import/run_beholder_attack_repair_sol_v1.py": "another agent's untracked work in progress",
}
SCAN_SUFFIXES = (".py", ".sh", ".cmd", ".bat", ".ps1")
SCAN_SKIP_DIRS = {"__pycache__", "_nfix_head", "external", "vendor", "third_party", "AssetRipper", "AssetStudioCLI",
                  "build_out", "node_modules", "bin", "obj", "extracted", "reference", "unity_exports"}
BUILDERS = [
    "tools/homm3_town_scene_meshes/unity/Homm3TownScene3dBundleBuild.cs",
    "tools/custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs",
    "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.cs",
    "tools/homm3_import/unity_editor/ProbeDefRetargetDeliveryBundles.cs",
    "tools/homm3_import/unity_editor/ProbeDisplacementMaskBundles.cs",
    "tools/homm3_import/unity_editor/Homm3BattleSoundPrefabsBuild.cs",
    "tools/homm3_import/unity_editor/Homm3BillboardAnimatorBuild.cs",
    "tools/homm3_import/unity_editor/Homm2ShadeObjectClassShaderBundleBuild.cs",
    "tools/homm3_import/unity_editor/Homm3ArtifactMapBillboardBundleBuild.cs",
    "tools/homm3_import/unity_editor/Homm3ArtifactMeshesBundleBuild.cs",
    "tools/homm3_import/unity_editor/Homm3MapBillboardBundleBuild.cs",
    "tools/homm3_import/unity_editor/Homm3DialogPortraitBundleBuild.cs",
    "tools/homm3_import/unity_editor/Homm3MapBuildingMeshesBundleBuild.cs",
    "tools/homm3_import/unity_editor/Homm3TowerCityMapMeshBundleBuild.cs",
    "tools/homm3_import/unity_editor/Homm3UiPortraitBundleBuild.cs",
    "tools/homm3_import/unity_editor/Homm3TownSceneMeshesBundleBuild.cs",
    "tools/homm3_import/unity_editor/UnitVfxPreview.cs",
    "tools/homm3_import/unity_editor/BeholderAttackContourV14.cs",
    "tools/homm3_import/unity_editor/Homm3FacingProofRig.cs",
    "tools/homm3_import/unity_editor/Homm3OwnedSkinnedAttackSlotRemap.cs",
    "tools/homm3_map_building_meshes/unity/Homm3MapBuildingAnimPreview.cs",
    "tools/homm3_vfx/unity/Homm3VanillaStyleVfxLab.cs",
    "tools/homm3_vfx/unity/Homm3OceanidLookLab.cs",
    "tools/homm3_vfx/unity/Homm3OceanidWaterLab.cs",
    "tools/homm3_vfx/unity/Homm3VfxLabBuild.cs",
    "tools/homm3_vfx/unity/Homm3VfxLightLab.cs",
    "tools/homm3_vfx/unity/Homm3VolumetricFireLab.cs",
    "tools/homm3_town_scene_meshes/unity/Homm3ConfluxTown3dPreview.cs",
]
UNITYLOCK_RUN = re.compile(r"unitylock\.py\"?\)?,\s*\"run\"|UNITYLOCK\)?,\s*\"run\"")
DIRECT_LAUNCH = re.compile(r"subprocess\.(?:run|Popen|call|check_call|check_output)\(\s*(?:cmd|command)\b")


def scan_batchmode_scripts() -> list[str]:
    """Every tools/ script whose text builds a -batchmode command line (repo-relative, forward slashes)."""
    hits = []
    for dirpath, dirnames, filenames in os.walk(ROOT / "tools"):
        dirnames[:] = [d for d in dirnames if d not in SCAN_SKIP_DIRS and not d.startswith(("_tmp", "tmp_", "."))]
        for name in filenames:
            if not name.endswith(SCAN_SUFFIXES):
                continue
            path = Path(dirpath) / name
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "-batchmode" in text:
                hits.append(path.relative_to(ROOT).as_posix())
    return sorted(hits)
DISPATCHER = "tools/unity_queue/unity/UnityQueueDispatcher.cs"
RUNNER = "tools/unity_queue/unity_queue.py"
DOC = "docs/unity_queue_runner.md"
SHIM_ARGS = 'static string[] UnityQueueArgs() => AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") as string[] ?? Environment.GetCommandLineArgs();'
SHIM_EXIT = 'if (AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") == null) { EditorApplication.Exit(code); return; }'


def read(rel: str, errors: list[str]) -> str:
    p = ROOT / rel
    if not p.is_file():
        errors.append(f"missing {rel}")
        return ""
    return p.read_text(encoding="utf-8-sig")


def main() -> int:
    errors: list[str] = []
    for rel, helper in {**CALLERS, **LAUNCH_CALLERS_EXTRA}.items():
        t = read(rel, errors)
        if not t:
            continue
        if "tools/unity_queue/unity_queue.py" not in t or ".launch(" not in t:
            errors.append(f"{rel}: does not submit through tools/unity_queue launch()")
        if helper not in t:
            errors.append(f"{rel}: its launch helper {helper!r} is gone")
        if UNITYLOCK_RUN.search(t):
            errors.append(f"{rel}: launches through unitylock itself (agents must submit, not launch)")
        if re.search(r"[\"']-batchmode[\"']", t):
            errors.append(f"{rel}: builds its own -batchmode command line")
        if "--unity-direct" not in t or "direct=UNITY_DIRECT" not in t:
            errors.append(f"{rel}: the explicit --unity-direct opt-out is not wired to launch(direct=...)")
    for rel, marker in CMD_CALLERS.items():
        t = read(rel, errors)
        if not t:
            continue
        if "unity_queue" not in t or marker not in t:
            errors.append(f"{rel}: does not hand its Unity command line to the queue ({marker!r} missing)")
        if rel.endswith(".py"):
            if UNITYLOCK_RUN.search(t) or "UNITYLOCK" in t:
                errors.append(f"{rel}: launches through unitylock itself (agents must submit, not launch)")
            if DIRECT_LAUNCH.search(t) and "-batchmode" in t:
                errors.append(f"{rel}: runs a cmd/command list with subprocess itself (hand it to run_cmd())")
            if not ("take_direct_flag()" in t and "direct=UNITY_DIRECT" in t) and not (
                    '"--unity-direct"' in t and "direct=" in t):
                errors.append(f"{rel}: the explicit --unity-direct opt-out is not wired to run_cmd(direct=...)")
        elif "--unity-direct" not in t or "UNITY_QUEUE BYPASS" not in t:
            errors.append(f"{rel}: the explicit --unity-direct opt-out is missing or not logged")
    known = set(CALLERS) | set(CMD_CALLERS) | set(LAUNCH_CALLERS_EXTRA) | set(LEGACY_UNSWITCHED)
    known |= {RUNNER, "tools/validate_unity_queue_contract.py"}
    for rel in scan_batchmode_scripts():
        if rel not in known:
            errors.append(f"{rel}: builds a -batchmode Unity command outside the queue; switch it to tools/unity_queue "
                          f"(docs/unity_queue_runner.md) - agents must submit, not launch")
    for rel in BUILDERS:
        t = read(rel, errors)
        if not t:
            continue
        if SHIM_ARGS not in t or SHIM_EXIT not in t:
            errors.append(f"{rel}: no UnityQueueArgs()/UnityQueueExit() shim")
            continue
        body = t.replace(SHIM_ARGS, "").replace(SHIM_EXIT, "")
        if "Environment.GetCommandLineArgs()" in body:
            errors.append(f"{rel}: reads Environment.GetCommandLineArgs() outside the shim (use UnityQueueArgs())")
        if "EditorApplication.Exit(" in body:
            errors.append(f"{rel}: calls EditorApplication.Exit outside the shim (use UnityQueueExit())")
    d = read(DISPATCHER, errors)
    for needle, why in (('GetMethod("UnityQueueArgs"', "refuse a class without the shim"),
                        ("File.AppendAllText(batch.resultsPath", "append one result line per finished job"),
                        ("catch (Exception e)", "catch a job's exception and continue the batch"),
                        ("AssetBundle.UnloadAllAssetBundles(true)", "reset loaded bundles between jobs")):
        if d and needle not in d:
            errors.append(f"{DISPATCHER}: must {why} ({needle!r} missing)")
    r = read(RUNNER, errors)
    for needle, why in (("unitylock.LOCK", "take the shared unitylock lock directory"),
                        ("LAUNCH_GUARD", "run the launch guard preflight"),
                        ("MEMGATE", "run memgate before a launch"),
                        ("unity_on_project(", "refuse a project another editor has open"),
                        ("library_refusal(", "refuse a cold/incomplete Library except the warm-up job"),
                        ("watch_disk(", "watch free space while Unity runs (warn + flag, never kill)"),
                        ("before this job reported a result", "fail unreported jobs after a crash"),
                        ("UNITY_QUEUE BYPASS", "log the --unity-direct opt-out loudly")):
        if r and needle not in r:
            errors.append(f"{RUNNER}: must {why} ({needle!r} missing)")
    doc = read(DOC, errors)
    if doc and "Agents must submit, not launch" not in doc:
        errors.append(f"{DOC}: lost the 'Agents must submit, not launch' rule")
    agents = read("AGENTS.md", errors)
    if agents and DOC not in agents:
        errors.append("AGENTS.md: no pointer to docs/unity_queue_runner.md")
    print(json.dumps({"schema": "unity_queue_contract.v1", "ok": not errors, "errors": errors,
                      "proof": "source/static; does not launch Unity"}, indent=1))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
