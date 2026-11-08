#!/usr/bin/env python3
"""Static contract for the Meshy SmartRig skinned-mesh rollout."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
STATUS = ROOT / "artifacts/homm3_smartrig_skinned_rollout/status.json"


def main() -> int:
    errors: list[str] = []
    required_files = [
        ROOT / "tools/homm3_silhouette_pose_fit/run_gpu_cascade_animation_set.py",
        ROOT / "tools/homm3_silhouette_pose_fit/inventory_smartrig_skinned_rollout.py",
        ROOT / "tools/homm3_silhouette_pose_fit/prepare_smartrig_skinned_import.py",
        ROOT / "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.cs",
        ROOT / "tools/custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs",
        PLUGIN / "Homm3ImportVisuals.cs",
        PLUGIN / "Homm3ImportPreviewSyntheticMeshHook.cs",
        PLUGIN / "Homm3PreviewFineTune.cs",
        PLUGIN / "config.json",
        ROOT / "docs/surfaces/custom_unit_skinned_mesh.md",
    ]
    for path in required_files:
        if not path.is_file():
            errors.append(f"missing {path}")
    overlay = (ROOT / "tools/release_port/apply_release_core_overlay.py").read_text(encoding="utf-8", errors="replace")
    for text in (
        "normalize_custom_unit_view_skinned_preview_meshes",
        "load_homm3_import_skinned_preview_meshes",
        "OwnedSkinned",
    ):
        if text not in overlay:
            errors.append(f"overlay missing {text}")
    prepare = (ROOT / "tools/homm3_silhouette_pose_fit/prepare_smartrig_skinned_import.py").read_text(
        encoding="utf-8", errors="replace"
    )
    if "without --lab-sids" not in prepare:
        errors.append("prepare_smartrig_skinned_import.py must refuse write-import without --lab-sids")
    visuals = (PLUGIN / "Homm3ImportVisuals.cs").read_text(encoding="utf-8", errors="replace")
    for text in (
        "PrepareOwnedSkinnedIdleInstance",
        "ApplySkinnedAdventureMapVisualScale",
        "EnsureSkinnedAdventureMapIdle",
        "IsOwnedSkinnedPrefabPath",
        "IsOwnedSkinnedBattleEntry",
        "native-shell.create.skinned-idle-return",
    ):
        if text not in visuals:
            errors.append(f"Homm3ImportVisuals missing {text}")
    preview = (PLUGIN / "Homm3ImportPreviewSyntheticMeshHook.cs").read_text(encoding="utf-8", errors="replace")
    if "PrepareOwnedSkinnedIdleInstance" not in preview:
        errors.append("preview synthetic mesh must Hex/Lit-bind and loop Idle on owned skinned instances")
    preview_model = (PLUGIN / "Homm3ImportUnitPreviewModelHook.cs").read_text(encoding="utf-8", errors="replace")
    if "skinnedLane" not in preview_model:
        errors.append("preview model hook must skip billboard overlay materials on owned skinned instances")
    if "ShouldKeepNativeDetailPreviewMesh" not in preview_model:
        errors.append("preview model hook must keep Idle mesh instead of covering it with a portrait overlay")
    icon_hook = (PLUGIN / "Homm3CustomUiIconHook.cs").read_text(encoding="utf-8", errors="replace")
    prefix_idx = icon_hook.find("void PrefixRecruitmentIncrementItemSprite")
    if prefix_idx < 0:
        errors.append("Homm3CustomUiIconHook missing PrefixRecruitmentIncrementItemSprite")
    else:
        prefix_owned = icon_hook.find("IsOwnedSkinnedUnitSid", prefix_idx, prefix_idx + 1200)
        prefix_keep = icon_hook.find("prefix-keep-mesh", prefix_idx, prefix_idx + 1200)
        if prefix_owned < 0 or prefix_keep < 0:
            errors.append(
                "PrefixRecruitmentIncrementItemSprite must skip homm3_static_portrait replacement for owned-skinned SIDs"
            )
    if "UNIT PREVIEW SMALL" not in (ROOT / "docs/surfaces/custom_unit_skinned_mesh.md").read_text(
        encoding="utf-8", errors="replace"
    ):
        errors.append("skinned-mesh surface card must pin town increment-card portrait overlay as a pitfall")
    if "DonorSidToPreviewCatalogId" not in preview_model:
        errors.append("preview factory must rewrite Show.bewc UnitViewConfig.id to the dungeon donor catalog id")
    if "return NormalizeDungeonDonorLeaf(donorSid)" in preview_model:
        errors.append("DonorSidToPreviewCatalogId must use DonorBaseSid as-is (trogl), not the Dungeon prefab leaf (troglodyte)")
    if "Homm3OwnedSkinnedPreviewFraming.TryFrame(" not in preview_model:
        errors.append("preview model hook must frame owned skinned meshes by the battle-size rule (Homm3OwnedSkinnedPreviewFraming), not the leftover billboard/background slot")
    if "PlaceOwnedSkinnedPreviewAtVanillaMeshPose" in preview_model:
        errors.append("preview model hook must not size owned skinned previews from the donor (retired PlaceOwnedSkinnedPreviewAtVanillaMeshPose)")
    if "FitSkinnedMeshToPreviewBackground" in preview_model:
        errors.append("preview model hook must not AABB-fit owned skinned meshes to the preview background")
    if "FitSkinnedMeshToDonorWorldHeight" not in visuals:
        errors.append("Homm3ImportVisuals missing FitSkinnedMeshToDonorWorldHeight")
    if "vanilla.transform.GetChild(0).localScale" in visuals:
        errors.append("adventure-map skinned scale must not copy the donor child's localScale")
    if "return !UseStaticPreviewPortraits()" in preview_model:
        errors.append("ShouldKeepNativeDetailPreviewMesh must not keep 3D mesh for every unit when portraits are off")
    if "Homm3ImportPreviewSyntheticMeshHook.TryRegister" not in preview_model:
        errors.append("detail-preview required slice must register the synthetic mesh loader")
    if "TryPrepareOwnedSkinnedPreview" not in preview_model:
        errors.append("preview model hook must Hex/Lit-bind and loop Idle when replacing the detail model")
    lab_builder = (ROOT / "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.cs").read_text(
        encoding="utf-8", errors="replace"
    )
    if "EnsureQuaternionContinuity" not in lab_builder:
        errors.append("Homm3OwnedSkinnedLabBuild must call EnsureQuaternionContinuity after copying rotation curves")
    if "FlattenRotationTangents" not in lab_builder:
        errors.append("Homm3OwnedSkinnedLabBuild must flatten quaternion tangents to linear")
    if "IsLocalRotationProperty" not in lab_builder:
        errors.append("Homm3OwnedSkinnedLabBuild must copy localRotation curves only")
    if "RescaleClipToDuration" in lab_builder:
        errors.append("Homm3OwnedSkinnedLabBuild must not time-stretch fused-push clips to Esquire durations")
    if "stretching to Esquire 5.33s melted" not in lab_builder:
        errors.append("Homm3OwnedSkinnedLabBuild must record why fused-push clips keep authored duration")
    if "clipSpec.lifecycleRole" not in lab_builder:
        errors.append("Homm3OwnedSkinnedLabBuild must set loopTime from lifecycleRole, not a suffix table")
    if "ApplyLoopSetting(copy, LoopBySuffix" in lab_builder:
        errors.append("Homm3OwnedSkinnedLabBuild must not apply loopTime from LoopBySuffix")
    goblin_idle = (
        ROOT
        / "oldenera_factions/Assets/CustomUnits/homm3_lab/h3_goblin/OwnedSkinned/Animations/Unit_Idle.anim"
    )
    live_idle_sidecar = (
        ROOT / "artifacts/fused_push_skinned_rollout/units/h3_goblin/clips/Unit_Idle.json"
    )
    cycle_closed = False
    if live_idle_sidecar.is_file():
        sidecar = json.loads(live_idle_sidecar.read_text(encoding="utf-8"))
        source_count = int(sidecar.get("sourceFrameCount") or sidecar.get("frameCount") or 0)
        cycle_closed = int(sidecar.get("keyCount") or 0) == source_count + 1
    if goblin_idle.is_file():
        idle_text = goblin_idle.read_text(encoding="utf-8", errors="replace")
        if "time: 5.3333335" in idle_text:
            errors.append("h3_goblin Unit_Idle.anim must keep authored 12fps duration, not Esquire 5.33s")
        if cycle_closed and "time: 0.666" not in idle_text:
            errors.append(
                "h3_goblin Unit_Idle.anim must close the 8-pose cycle at 8/12s after cycle-close export"
            )
        if not cycle_closed and "time: 0.5833333" not in idle_text:
            errors.append("h3_goblin Unit_Idle.anim must keep the current 8-frame open period (~0.58s) until cycle-close export")
    fine_tune = (PLUGIN / "Homm3PreviewFineTune.cs").read_text(encoding="utf-8", errors="replace")
    if "keeping Hex/Lit on owned skinned mesh" not in fine_tune:
        errors.append("Homm3PreviewFineTuneRegistry.SetTarget must keep Hex/Lit on owned skinned meshes")
    if "overlay material modes are forbidden on owned skinned meshes" not in fine_tune:
        errors.append("Homm3PreviewFineTuneRegistry must refuse overlay material cycles on owned skinned meshes")
    apply_idx = fine_tune.find("private static void ApplyCurrentMaterialMode()")
    skinned_guard_idx = fine_tune.find("IsHomm3SkinnedBattleInstance(Target)", apply_idx if apply_idx >= 0 else 0)
    if apply_idx < 0 or skinned_guard_idx < 0 or skinned_guard_idx < apply_idx:
        errors.append("ApplyCurrentMaterialMode must refuse overlay stamps on owned skinned meshes")
    if "BhUnitPreviews" not in preview:
        errors.append("synthetic mesh must treat BhUnitPreviews shared cache as recruitment/placeholder")
    if "TryResolveSyntheticPreviewEntry" not in preview:
        errors.append("synthetic mesh must resolve unit SIDs as well as units/homm3_import paths")
    pool = (PLUGIN / "Homm3ImportBattlePoolHook.cs").read_text(encoding="utf-8", errors="replace")
    if "PrefixBathTwoArg" not in pool:
        errors.append("battle pool must synthesize 2-arg loaders, not only 3-arg metadata baths")
    if "TryGetCachedBattlePresentationTemplate" not in pool:
        errors.append("battle pool Init synthesize must use cache-only presentation donor")
    if "LoadBundleGameObject" not in visuals:
        errors.append("Homm3ImportVisuals must load bundle prefabs by exact path, not a different prefab")
    if "visual prefabs=" not in visuals:
        errors.append("Homm3ImportVisuals must log bundle prefab names when battle/map LoadAsset misses")
    cfg = json.loads((PLUGIN / "config.json").read_text(encoding="utf-8-sig"))
    if cfg.get("homm3ImportPreviewHooks") is not True:
        errors.append("config.json homm3ImportPreviewHooks must be true for synthetic skinned previews")
    if cfg.get("homm3PreviewUseStaticPortraits") is not False:
        errors.append("config.json homm3PreviewUseStaticPortraits must be false so previews loop idle meshes")
    bundle = (ROOT / "tools/custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs").read_text(
        encoding="utf-8", errors="replace"
    )
    if "IsSkinnedMapPrefab" not in bundle:
        errors.append("BuildCustomUnitBundles missing IsSkinnedMapPrefab")
    if "owned_skinned.mat" not in bundle:
        errors.append("BuildCustomUnitBundles missing generic owned_skinned.mat")
    runner = (ROOT / "tools/homm3_silhouette_pose_fit/run_gpu_cascade_animation_set.py").read_text(
        encoding="utf-8", errors="replace"
    )
    if "apply_current_cascade_keep" not in runner:
        errors.append("run_gpu_cascade_animation_set.py must force CURRENT_CASCADE_KEEP over leftover notebook cells")
    delivery = (ROOT / "tools/homm3_silhouette_pose_fit/gpu_cascade_delivery.py").read_text(
        encoding="utf-8", errors="replace"
    )
    if "def apply_current_cascade_keep" not in delivery:
        errors.append("gpu_cascade_delivery.py missing apply_current_cascade_keep")
    if STATUS.is_file():
        status = json.loads(STATUS.read_text(encoding="utf-8"))
        unfilled = status.get("unfilledLabSids") or status.get("counts", {}).get("unfilled")
        if unfilled in (None, []):
            # inventory stores unfilled count; family holes must still be listed on units
            holes = [row["labSid"] for row in status.get("units", []) if row.get("meshRole") == "unfilled"]
            if not holes:
                errors.append("status.json has no fail-closed unfilled family record")
    else:
        errors.append(f"missing inventory status {STATUS}")
    result = {"ok": not errors, "schema": "smartrig_skinned_rollout_contract.v1", "errors": errors}
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
