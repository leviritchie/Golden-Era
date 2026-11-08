using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// def_retarget authority for the owned-skinned lab builder (the native mocap delivery lane).
///
/// A def_retarget unit is one GLB: skin, 23 joints, dense POSITION morph targets and every
/// Unit_* clip. Unlike the mocap/cascade authorities the clips keep their blendShape curves
/// (the corrective-smooth one-hot weights) and every Transform curve untouched (mixed STEP /
/// LINEAR keys, so no tangent flattening). The unit-look VFX plan
/// (tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py prepare) is baked into the
/// prefab and the clips so the native Animator plays it:
///   - uvAtlas: stepped material._MainTex_ST curves on the body SkinnedMeshRenderer in every clip
///     (rest cell elsewhere); the cells ride as __homm3_vfx_uvatlas__/cellN (localPosition = ST.zw,
///     localScale = ST.xy) so the runtime can snap crossfade blends back onto a cell.
///   - defFlipbook (billboard / groundPlane): one holder per layer+clip under the anchor bone
///     (__homm3_vfx_billboard__ / __homm3_vfx_ground__), one child quad per used cell with its own
///     UV rect (Sprites/Default ignores _MainTex_ST), stepped m_Enabled curves in every clip.
///     Orientation (camera-facing / laid flat) is runtime work: Homm3UnitLookVfxRuntime.
///   - effectLight: a Point Light under the anchor bone (__homm3_vfx_light__), stepped m_Enabled /
///     m_Intensity / m_LocalPosition curves. Positions come from the manifest's Blender-world
///     positions, moved into bone space by sampling the clip at the key's pose time. Range and
///     intensity are in unscaled unit space; the runtime scales them with the unit. A clip without
///     a curve holds the light's floor (on when floor > 0, at the first key's position). The game's
///     Hex/Lit reads Unity point lights through the per-object light list (HexLighting
///     _PunctualLight* arrays, unity_LightIndices), so a plain Light is the native carrier.
/// The content is wrapped in an "Orientation" child so the plugin's side facing has its node.
/// Inside Orientation the bind is wrapped at DefRetargetBindFacingYaw (-60): the GLB faces +Z, and every
/// top-level GLB node is turned -60 about Y so the idle-0 mesh faces the fleet convention
/// (Homm3ImportVisuals.OwnedSkinnedBindFacingYaw), which the plugin's lanes compensate (battle 150 / -30 =
/// native +/-90; map / preview native scale_roll + 60). No clip may animate a top-level GLB node's position
/// or rotation (that would overwrite the wrap); it is refused. The saved prefab's Orientation carries yaw
/// +90 (DefRetargetOrientationYaw); every runtime lane overwrites it. The clip sampler stays at identity
/// and VFX nodes are built before the wrap (light keys are bone-local, so they do not depend on it).
/// tools/validate_homm3_owned_skinned_facing_contract.py.
/// </summary>
public static partial class Homm3OwnedSkinnedLabBuild
{
    private const string DefRetargetOrientationName = "Orientation";
    private const float DefRetargetOrientationYaw = 90f;
    private const float DefRetargetBindFacingYaw = -60f; // = Homm3ImportVisuals.OwnedSkinnedBindFacingYaw
    private const string VfxUvAtlasMarkerName = "__homm3_vfx_uvatlas__";
    private const string ParkedLabRoot = "V:/homm3_unity_work/LabParked";

    [Serializable] private class PlanIdleMap { public string clip; public float t0; public float factor; }
    [Serializable] private class PlanClipLength { public string clip; public float length; }
    [Serializable] private class PlanCellKey { public float t; public int cell; }
    [Serializable] private class PlanCell { public float[] st; }
    [Serializable] private class PlanAtlasClip { public string clip; public PlanCellKey[] keys; }
    [Serializable] private class PlanAtlas { public string id; public string atlas; public string atlasSha256; public PlanCell[] cells; public PlanAtlasClip[] clips; public int restCell; }
    [Serializable] private class PlanQuadCell { public int index; public float[] uvRect; }
    [Serializable] private class PlanQuad
    {
        public string name; public string layer; public string clip; public string render; public string anchorBone;
        public string sheet; public string sheetSha256; public int tilesX; public int tilesY; public float[] sizeUnits;
        public PlanQuadCell[] cells; public PlanCellKey[] keys;
    }
    [Serializable] private class PlanLightKey { public float t; public float tPose; public float intensity; public float[] rootPosition; }
    [Serializable] private class PlanLightClip { public string clip; public PlanLightKey[] keys; }
    [Serializable] private class PlanLight { public string name; public string id; public string anchorBone; public float[] rgb; public float range; public float floor; public PlanLightClip[] clips; }
    [Serializable] private class VfxPlan
    {
        public string schema; public string unit; public PlanIdleMap idleTimeMap; public PlanClipLength[] clipLengthList;
        public PlanAtlas uvAtlas; public PlanQuad[] quads; public PlanLight[] lights;
        public PlanDeferredMesh[] deferredMeshes;
        public PlanMergedMesh[] mergedMeshes; public PlanMergedMaster mergedMaster;
    }
    [Serializable] private class PlanDeferredMesh { public string node; public string reason; }
    // mergeMeshes (ship_def_retarget_slice.py prepare, merge_rubble_glb.py): a death shatter's rubble appended to the
    // body primitive; the master is the merged GLB and its one SMR carries totalVertices
    [Serializable] private class PlanMergedMesh { public string node; public string reason; public int firstVertex; public int vertices; }
    [Serializable] private class PlanMergedMaster { public string sha256; public int bodyVertices; public int totalVertices; }

    private sealed class BuiltVfx
    {
        public string bodyPath;
        public bool hasAtlas;
        public readonly Dictionary<string, string> quadPaths = new Dictionary<string, string>(StringComparer.Ordinal);
        public readonly Dictionary<string, string> lightPaths = new Dictionary<string, string>(StringComparer.Ordinal);
        public readonly List<string> report = new List<string>();
    }

    private static void BuildDefRetarget(UnitSpec spec)
    {
        RequireFile(spec.masterGlb);
        RequireFile(spec.albedo);
        RequireFile(spec.normal);
        RequireFile(spec.metallicGloss);
        RequireFile(spec.vfxPlan);
        VfxPlan plan = JsonUtility.FromJson<VfxPlan>(File.ReadAllText(spec.vfxPlan));
        if (plan == null || plan.schema != "homm3_def_retarget_vfx_plan.v1" || plan.unit != spec.labSid)
            throw new InvalidOperationException(spec.labSid + " vfx plan schema/unit mismatch: " + spec.vfxPlan);
        if (plan.quads == null) plan.quads = new PlanQuad[0];
        if (plan.lights == null) plan.lights = new PlanLight[0];
        bool hasAtlas = plan.uvAtlas != null && plan.uvAtlas.cells != null && plan.uvAtlas.cells.Length > 0;

        string assetRoot = "Assets/CustomUnits/homm3_lab/" + spec.labSid + "/OwnedSkinned";
        string albedoExt = Path.GetExtension(spec.albedo).ToLowerInvariant();
        if (albedoExt != ".png" && albedoExt != ".jpg")
            throw new InvalidOperationException(spec.labSid + " albedo must be .png or .jpg: " + spec.albedo);
        ParkPreviousOwnedSkinned(spec.labSid, assetRoot, albedoExt);
        string sourceRoot = assetRoot + "/Source";
        string animationRoot = assetRoot + "/Animations";
        string vfxRoot = assetRoot + "/Vfx";
        string prefabPath = assetRoot + "/owned_skinned.prefab";
        string overridePath = assetRoot + "/owned_skinned.overrideController";
        string materialPath = assetRoot + "/owned_skinned.mat";
        string albedoPath = assetRoot + "/owned_skinned_basecolor" + albedoExt;
        string normalPath = assetRoot + "/owned_skinned_normal.png";
        string metallicPath = assetRoot + "/owned_skinned_metallicgloss.png";
        foreach (string dir in new[] { assetRoot, sourceRoot, animationRoot, vfxRoot, assetRoot + "/Reference" })
            EnsureDirectory(dir);

        string unitController = assetRoot + "/Reference/StockEsquireBattle.controller";
        if (!SameFileBytes(ToAbsolute(StockController), ToAbsolute(unitController)))
        {
            File.Copy(ToAbsolute(StockController), ToAbsolute(unitController), true);
            AssetDatabase.ImportAsset(unitController, ImportAssetOptions.ForceSynchronousImport);
        }
        if (AssetDatabase.LoadAssetAtPath<RuntimeAnimatorController>(unitController) == null)
            throw new InvalidOperationException(spec.labSid + " per-unit StockEsquireBattle.controller did not import");

        DeliverTexture(spec.albedo, albedoPath, sRGB: true, normalMap: false);
        DeliverTexture(spec.normal, normalPath, sRGB: false, normalMap: true);
        DeliverTexture(spec.metallicGloss, metallicPath, sRGB: false, normalMap: false);

        // Not "master.glb": the bundle builder adds Source/master.glb as a root asset; this GLB is
        // only a dependency of the prefab (mesh) and of nothing else.
        string masterAssetPath = sourceRoot + "/def_retarget_master.glb";
        WriteGltfastMeta(ToAbsolute(masterAssetPath) + ".meta", spec.labSid);
        if (!SameFileBytes(spec.masterGlb, ToAbsolute(masterAssetPath)))
            CopyExactFile(spec.masterGlb, ToAbsolute(masterAssetPath));
        AssetDatabase.ImportAsset(masterAssetPath, ImportAssetOptions.ForceSynchronousImport);
        GameObject masterAsset = AssetDatabase.LoadAssetAtPath<GameObject>(masterAssetPath);
        if (masterAsset == null)
            throw new InvalidOperationException(spec.labSid + " master GLB did not import: " + masterAssetPath);
        // A skinned mesh the selection defers by node name (deferLayers-style, with a reason in the plan)
        // is left out of the prefab; every other extra skinned mesh still refuses.
        var deferredMeshes = new HashSet<string>((plan.deferredMeshes ?? new PlanDeferredMesh[0]).Select(d => d.node), StringComparer.Ordinal);
        SkinnedMeshRenderer[] allSkins = masterAsset.GetComponentsInChildren<SkinnedMeshRenderer>(true);
        foreach (string node in deferredMeshes)
            if (!allSkins.Any(sk => sk.gameObject.name == node))
                throw new InvalidOperationException(spec.labSid + " deferred skinned mesh " + node + " is not in the master");
        SkinnedMeshRenderer[] skins = allSkins.Where(sk => !deferredMeshes.Contains(sk.gameObject.name)).ToArray();
        if (skins.Length != 1 || skins[0].sharedMesh == null || skins[0].bones == null || skins[0].bones.Length == 0)
            throw new InvalidOperationException(spec.labSid + " def_retarget master must have exactly one complete SkinnedMeshRenderer, found " + skins.Length);
        Mesh mesh = skins[0].sharedMesh;
        if (mesh.blendShapeCount == 0)
            throw new InvalidOperationException(spec.labSid + " def_retarget mesh imported without blend shapes");
        string mergedReport = RequireMergedMaster(spec, plan, allSkins, mesh);
        var sourceClips = AssetDatabase.LoadAllAssetsAtPath(masterAssetPath).OfType<AnimationClip>()
            .Where(c => !c.name.StartsWith("__preview__", StringComparison.Ordinal))
            .ToDictionary(c => c.name, StringComparer.Ordinal);
        if (sourceClips.Values.Any(c => c.legacy))
            throw new InvalidOperationException(spec.labSid + " glTFast imported legacy clips; the Mecanim import setting did not apply");

        Material battleMaterial = BuildRuntimeCompatibleMaterial(skins[0].sharedMaterial, materialPath, albedoPath, normalPath, metallicPath);
        // Saved over the existing prefab: SaveAsPrefabAsset keeps its GUID and name-matched fileIDs.
        GameObject instance = InstantiateWrapped(masterAsset);
        BuiltVfx built;
        try
        {
            instance.name = "owned_skinned";
            foreach (SkinnedMeshRenderer dropped in instance.GetComponentsInChildren<SkinnedMeshRenderer>(true).Where(sk => deferredMeshes.Contains(sk.gameObject.name)).ToArray())
                UnityEngine.Object.DestroyImmediate(dropped.gameObject);
            var glbTopLevel = new List<Transform>();
            foreach (Transform child in instance.transform.Find(DefRetargetOrientationName))
                glbTopLevel.Add(child);
            SkinnedMeshRenderer body = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true).Single();
            Material[] materials = body.sharedMaterials;
            for (int i = 0; i < materials.Length; i++)
                materials[i] = battleMaterial;
            body.sharedMaterials = materials;
            Animator animator = instance.GetComponent<Animator>();
            if (animator == null)
                animator = instance.AddComponent<Animator>();
            animator.applyRootMotion = false;
            animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            GameObject marker = new GameObject(SkinnedLaneMarkerName);
            marker.transform.SetParent(instance.transform, false);
            marker.transform.localRotation = Quaternion.Euler(0f, 90f, 0f);
            built = BuildVfxNodes(instance, body, plan, hasAtlas, vfxRoot, spec.labSid);
            ApplyDefRetargetBindFacing(instance.transform.Find(DefRetargetOrientationName), glbTopLevel);
            instance.transform.Find(DefRetargetOrientationName).localRotation = Quaternion.Euler(0f, DefRetargetOrientationYaw, 0f);
            bool saved;
            PrefabUtility.SaveAsPrefabAsset(instance, prefabPath, out saved);
            if (!saved)
                throw new InvalidOperationException(spec.labSid + " prefab did not save");
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(instance);
        }

        var lengths = (plan.clipLengthList ?? new PlanClipLength[0]).ToDictionary(c => c.clip, c => c.length, StringComparer.Ordinal);
        var clipReports = new List<string>();
        var importedClips = new List<AnimationClip>();
        GameObject sampler = InstantiateWrapped(masterAsset);
        try
        {
            foreach (ClipSpec clipSpec in spec.clips)
            {
                if (string.IsNullOrEmpty(clipSpec.sourceAnimation) || !sourceClips.TryGetValue(clipSpec.sourceAnimation, out AnimationClip source))
                    throw new InvalidOperationException(spec.labSid + " master GLB has no animation '" + clipSpec.sourceAnimation + "'");
                string outputPath = animationRoot + "/" + clipSpec.contractName + ".anim";
                if (AssetDatabase.LoadAssetAtPath<AnimationClip>(outputPath) != null)
                    AssetDatabase.DeleteAsset(outputPath);
                var copy = new AnimationClip { name = clipSpec.contractName, frameRate = source.frameRate };
                var counts = CopyDefRetargetCurves(copy, source, sampler.transform, spec.labSid);
                if (!lengths.TryGetValue(clipSpec.contractName, out float planLength))
                    throw new InvalidOperationException(spec.labSid + " vfx plan has no length for " + clipSpec.contractName);
                if (Mathf.Abs(copy.length - planLength) > 1e-3f)
                    throw new InvalidOperationException(spec.labSid + " " + clipSpec.contractName + " imported length " + copy.length + " != GLB length " + planLength);
                int vfxCurves = BakeVfxCurves(copy, clipSpec.contractName, plan, built, sampler, spec.labSid);
                copy.EnsureQuaternionContinuity();
                if (clipSpec.lifecycleRole != "cycle" && clipSpec.lifecycleRole != "entry" && clipSpec.lifecycleRole != "exit"
                    && clipSpec.lifecycleRole != "one_shot" && clipSpec.lifecycleRole != "terminal")
                    throw new InvalidOperationException(spec.labSid + " clip " + clipSpec.contractName + " has unclassified lifecycleRole " + clipSpec.lifecycleRole);
                ApplyLoopSetting(copy, clipSpec.lifecycleRole == "cycle");
                AssetDatabase.CreateAsset(copy, outputPath);
                importedClips.Add(AssetDatabase.LoadAssetAtPath<AnimationClip>(outputPath));
                clipReports.Add("{\"clip\":\"" + clipSpec.contractName + "\",\"length\":" + F(copy.length)
                    + ",\"loop\":" + (clipSpec.lifecycleRole == "cycle" ? "true" : "false")
                    + ",\"transformCurves\":" + counts[0] + ",\"blendShapeCurves\":" + counts[1]
                    + ",\"blendShapeMax\":" + F(counts[2] / 1000f) + ",\"vfxCurves\":" + vfxCurves + "}");
            }
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(sampler);
        }
        AssetDatabase.Refresh();

        RuntimeAnimatorController donor = AssetDatabase.LoadAssetAtPath<RuntimeAnimatorController>(StockController);
        if (donor == null)
            throw new InvalidOperationException("Stock Esquire controller is missing: " + StockController);
        if (AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(overridePath) != null)
            AssetDatabase.DeleteAsset(overridePath);
        var overrides = new AnimatorOverrideController(donor) { name = "owned_skinned" };
        AssetDatabase.CreateAsset(overrides, overridePath);
        ApplyStockContractOverrides(overrides, importedClips, "Unit", false, spec.labSid);
        var pairs = new List<KeyValuePair<AnimationClip, AnimationClip>>();
        overrides.GetOverrides(pairs);
        string stockMap = string.Join(",", pairs.Select(p => "\"" + p.Key.name + "\":\"" + (p.Value != null ? p.Value.name : "") + "\""));

        GameObject contents = PrefabUtility.LoadPrefabContents(prefabPath);
        try
        {
            Animator a = contents.GetComponent<Animator>();
            if (a == null)
                a = contents.AddComponent<Animator>();
            a.applyRootMotion = false;
            a.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            a.runtimeAnimatorController = overrides;
            if (PrefabUtility.SaveAsPrefabAsset(contents, prefabPath) == null)
                throw new InvalidOperationException(spec.labSid + " prefab controller save failed");
        }
        finally
        {
            PrefabUtility.UnloadPrefabContents(contents);
        }

        float frameWeight = mesh.GetBlendShapeFrameCount(0) > 0 ? mesh.GetBlendShapeFrameWeight(0, mesh.GetBlendShapeFrameCount(0) - 1) : 0f;
        string report = "{\n"
            + "  \"schema\": \"homm3_def_retarget_lab_report.v1\",\n"
            + "  \"labSid\": \"" + spec.labSid + "\",\n"
            + "  \"motionAuthority\": \"def_retarget\",\n"
            + "  \"prefab\": \"" + prefabPath + "\",\n"
            + "  \"masterGlbSha256\": \"" + Sha256(spec.masterGlb) + "\",\n"
            + "  \"vfxPlanSha256\": \"" + Sha256(spec.vfxPlan) + "\",\n"
            + "  \"albedo\": \"" + albedoPath + "\",\n"
            + "  \"orientationNode\": \"" + DefRetargetOrientationName + "\",\n"
            + "  \"orientationYaw\": " + F(DefRetargetOrientationYaw) + ",\n"
            + "  \"bindFacingYaw\": " + F(DefRetargetBindFacingYaw) + ",\n"
            + "  \"mesh\": {\"vertexCount\": " + mesh.vertexCount + ", \"blendShapeCount\": " + mesh.blendShapeCount
            + ", \"blendShapeFrameWeight\": " + F(frameWeight) + ", \"bones\": " + skins[0].bones.Length + "},\n"
            + "  \"bodyPath\": \"" + built.bodyPath + "\",\n"
            + "  \"mergedMeshes\": [" + mergedReport + "],\n"
            + "  \"clips\": [\n    " + string.Join(",\n    ", clipReports) + "\n  ],\n"
            + "  \"stockMap\": {" + stockMap + "},\n"
            + "  \"vfxNodes\": [\n    " + string.Join(",\n    ", built.report) + "\n  ],\n"
            + "  \"proof\": \"Unity-imported lab artifact; OE runtime not claimed.\"\n}\n";
        string reportPath = assetRoot + "/owned_skinned_def_retarget_report.json";
        File.WriteAllText(ToAbsolute(reportPath), report, new UTF8Encoding(false));
        File.WriteAllText(ToAbsolute(assetRoot + "/owned_skinned_audit.json"),
            "{\n  \"labSid\": \"" + spec.labSid + "\",\n  \"prefab\": \"" + prefabPath + "\",\n  \"motionAuthority\": \"def_retarget\",\n  \"placeholderIdleOnly\": false,\n  \"proof\": \"Unity-imported lab artifact; OE runtime not claimed.\"\n}\n",
            new UTF8Encoding(false));
        AssetDatabase.ImportAsset(reportPath, ImportAssetOptions.ForceSynchronousImport);
        AssetDatabase.ImportAsset(assetRoot + "/owned_skinned_audit.json", ImportAssetOptions.ForceSynchronousImport);
        Debug.Log("Homm3 owned skinned def_retarget lab built " + spec.labSid + " clips=" + importedClips.Count
            + " blendShapes=" + mesh.blendShapeCount + " vfxNodes=" + built.report.Count);
    }

    // Park a previous (non def_retarget) OwnedSkinned lane's lane-specific assets outside Assets,
    // then delete them, so its master.glb / jpg albedo / clips cannot ride into this bundle.
    private static void ParkPreviousOwnedSkinned(string labSid, string assetRoot, string albedoExt)
    {
        string audit = ToAbsolute(assetRoot + "/owned_skinned_audit.json");
        if (!Directory.Exists(ToAbsolute(assetRoot)))
            return;
        bool ours = File.Exists(audit) && File.ReadAllText(audit).Contains("\"motionAuthority\": \"def_retarget\"");
        if (!ours)
        {
            string parked = ParkedLabRoot + "/" + labSid + "_OwnedSkinned_" + DateTime.Now.ToString("yyyyMMdd_HHmmss");
            CopyDirectory(ToAbsolute(assetRoot), parked);
            Debug.Log("Homm3 def_retarget: parked previous OwnedSkinned lane of " + labSid + " at " + parked);
        }
        // A previous def_retarget build keeps its master GLB, basecolor and prefab: they are overwritten in place so
        // their GUIDs and fileIDs (hence the bundle's object ids) stay put and unchanged inputs are not reimported.
        // Another lane's prefab is deleted as before (it was deleted just before the save).
        foreach (string stale in new[] { "/Source/master.glb", "/Source/def_retarget_master.glb", "/owned_skinned_basecolor.jpg",
                                         "/owned_skinned_basecolor.png", "/owned_skinned_mocap_mesh.asset", "/owned_mocap_mesh.asset",
                                         "/owned_skinned.prefab" })
        {
            if (ours && (stale == "/Source/def_retarget_master.glb" || stale == "/owned_skinned_basecolor" + albedoExt
                         || stale == "/owned_skinned.prefab"))
                continue;
            if (AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(assetRoot + stale) != null)
                AssetDatabase.DeleteAsset(assetRoot + stale);
        }
        foreach (string folder in new[] { assetRoot + "/Animations", assetRoot + "/Temp", assetRoot + "/Vfx" })
        {
            if (AssetDatabase.IsValidFolder(folder))
                AssetDatabase.DeleteAsset(folder);
        }
    }

    private static void CopyDirectory(string from, string to)
    {
        Directory.CreateDirectory(to);
        foreach (string file in Directory.GetFiles(from))
            File.Copy(file, Path.Combine(to, Path.GetFileName(file)), true);
        foreach (string dir in Directory.GetDirectories(from))
            CopyDirectory(dir, Path.Combine(to, Path.GetFileName(dir)));
    }

    // Mecanim clips (animationMethod 2) and the lane's node naming, pinned before the first import. The GUID is
    // derived from the lab sid (not Guid.NewGuid), so a rebuild of an unchanged unit gives the same asset ids and
    // byte-identical bundles; the file is rewritten only when its content changes (no spurious reimport).
    private static void WriteGltfastMeta(string metaPath, string labSid)
    {
        string guid;
        using (MD5 md5 = MD5.Create())
            guid = string.Concat(md5.ComputeHash(Encoding.UTF8.GetBytes("homm3_def_retarget_master_glb:" + labSid)).Select(b => b.ToString("x2")));
        string meta = "fileFormatVersion: 2\nguid: " + guid + "\nScriptedImporter:\n  internalIDToNameTable: []\n  externalObjects: {}\n"
            + "  serializedVersion: 2\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n"
            + "  script: {fileID: 11500000, guid: 715df9372183c47e389bb6e19fbc3b52, type: 3}\n"
            + "  editorImportSettings:\n    generateSecondaryUVSet: 0\n  importSettings:\n    nodeNameMethod: 1\n    animationMethod: 2\n"
            + "    generateMipMaps: 1\n    texturesReadable: 0\n    defaultMinFilterMode: 9729\n    defaultMagFilterMode: 9729\n"
            + "    anisotropicFilterLevel: 1\n  instantiationSettings:\n    mask: -1\n    layer: 0\n    skinUpdateWhenOffscreen: 1\n"
            + "    lightIntensityFactor: 1\n    sceneObjectCreation: 2\n  assetDependencies: []\n  reportItems: []\n";
        if (File.Exists(metaPath) && File.ReadAllText(metaPath) == meta)
            return;
        File.WriteAllText(metaPath, meta, new UTF8Encoding(false));
    }

    private static bool SameFileBytes(string a, string b)
    {
        if (!File.Exists(a) || !File.Exists(b) || new FileInfo(a).Length != new FileInfo(b).Length)
            return false;
        using (SHA256 sha = SHA256.Create())
        {
            byte[] ha, hb;
            using (FileStream sa = File.OpenRead(a))
                ha = sha.ComputeHash(sa);
            using (FileStream sb = File.OpenRead(b))
                hb = sha.ComputeHash(sb);
            return ha.SequenceEqual(hb);
        }
    }

    // One import per changed texture: identical bytes with the delivery settings already on the importer skip the
    // copy and the import; a changed file is imported once and only reconfigured when its settings differ.
    private static void DeliverTexture(string source, string assetPath, bool sRGB, bool normalMap)
    {
        if (!SameFileBytes(source, ToAbsolute(assetPath)))
        {
            CopyExactFile(source, ToAbsolute(assetPath));
            AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceSynchronousImport);
        }
        ConfigureDeliveryTexture(assetPath, sRGB, normalMap);
    }

    // Turns every top-level GLB node (captured before any VFX node was added) about Orientation's Y, so the
    // idle-0 bind faces DefRetargetBindFacingYaw inside Orientation. Bones and their clips are local to these.
    private static void ApplyDefRetargetBindFacing(Transform orientation, List<Transform> glbTopLevel)
    {
        if (orientation == null || glbTopLevel.Count == 0)
            throw new InvalidOperationException("def_retarget bind facing: no Orientation or no GLB content under it");
        Quaternion wrap = Quaternion.Euler(0f, DefRetargetBindFacingYaw, 0f);
        foreach (Transform t in glbTopLevel)
        {
            if (t == null || t.parent != orientation)
                throw new InvalidOperationException("def_retarget bind facing: a GLB top-level node left Orientation");
            t.localPosition = wrap * t.localPosition;
            t.localRotation = wrap * t.localRotation;
        }
    }

    private static GameObject InstantiateWrapped(GameObject masterAsset)
    {
        GameObject instance = UnityEngine.Object.Instantiate(masterAsset);
        instance.transform.position = Vector3.zero;
        instance.transform.rotation = Quaternion.identity;
        instance.transform.localScale = Vector3.one;
        var children = new List<Transform>();
        foreach (Transform child in instance.transform)
            children.Add(child);
        var orientation = new GameObject(DefRetargetOrientationName);
        orientation.transform.SetParent(instance.transform, false);
        foreach (Transform child in children)
            child.SetParent(orientation.transform, false);
        return instance;
    }

    // Returns {transformCurves, blendShapeCurves, max blendShape weight * 1000}.
    private static int[] CopyDefRetargetCurves(AnimationClip target, AnimationClip source, Transform root, string labSid)
    {
        if (AnimationUtility.GetObjectReferenceCurveBindings(source).Length != 0)
            throw new InvalidOperationException(labSid + " " + source.name + " has object-reference curves");
        int transforms = 0, shapes = 0;
        float maxWeight = 0f;
        foreach (EditorCurveBinding b in AnimationUtility.GetCurveBindings(source))
        {
            bool isTransform = b.type == typeof(Transform) && IsLocalTransformProperty(b.propertyName);
            bool isShape = b.type == typeof(SkinnedMeshRenderer) && b.propertyName.StartsWith("blendShape.", StringComparison.Ordinal);
            if (!isTransform && !isShape)
                throw new InvalidOperationException(labSid + " " + source.name + " has an unsupported curve " + b.type.Name + "." + b.propertyName + " at " + b.path);
            string path = string.IsNullOrEmpty(b.path) ? DefRetargetOrientationName : DefRetargetOrientationName + "/" + b.path;
            if (path == DefRetargetOrientationName && isTransform && IsLocalRotationProperty(b.propertyName))
                throw new InvalidOperationException(labSid + " " + source.name + " animates the GLB root rotation, which would overwrite the Orientation facing yaw");
            if (isTransform && !string.IsNullOrEmpty(b.path) && b.path.IndexOf('/') < 0 && !b.propertyName.Contains("Scale"))
                throw new InvalidOperationException(labSid + " " + source.name + " animates top-level GLB node " + b.path + " (" + b.propertyName + "), which would overwrite the bind facing wrap");
            if (root.Find(path) == null)
                throw new InvalidOperationException(labSid + " " + source.name + " binding does not resolve: " + path);
            AnimationCurve curve = AnimationUtility.GetEditorCurve(source, b);
            AnimationUtility.SetEditorCurve(target, EditorCurveBinding.FloatCurve(path, b.type, b.propertyName), curve);
            if (isShape)
            {
                shapes++;
                foreach (Keyframe k in curve.keys)
                    maxWeight = Mathf.Max(maxWeight, k.value);
            }
            else
                transforms++;
        }
        if (transforms == 0)
            throw new InvalidOperationException(labSid + " " + source.name + " has no Transform curves");
        return new[] { transforms, shapes, Mathf.RoundToInt(maxWeight * 1000f) };
    }

    private static BuiltVfx BuildVfxNodes(GameObject instance, SkinnedMeshRenderer body, VfxPlan plan, bool hasAtlas, string vfxRoot, string labSid)
    {
        var built = new BuiltVfx { bodyPath = RelativeTransformPath(instance.transform, body.transform), hasAtlas = hasAtlas };
        if (hasAtlas)
        {
            var marker = new GameObject(VfxUvAtlasMarkerName);
            marker.transform.SetParent(instance.transform, false);
            for (int i = 0; i < plan.uvAtlas.cells.Length; i++)
            {
                float[] st = plan.uvAtlas.cells[i].st;
                if (st == null || st.Length != 4)
                    throw new InvalidOperationException(labSid + " uvAtlas cell " + i + " is not a 4-vector");
                var cell = new GameObject("cell" + i);
                cell.transform.SetParent(marker.transform, false);
                cell.transform.localPosition = new Vector3(st[2], st[3], 0f);
                cell.transform.localScale = new Vector3(st[0], st[1], 1f);
            }
            built.report.Add("{\"kind\":\"uvAtlas\",\"cells\":" + plan.uvAtlas.cells.Length + ",\"body\":\"" + built.bodyPath + "\"}");
        }
        var bones = instance.GetComponentsInChildren<Transform>(true).GroupBy(t => t.name).ToDictionary(g => g.Key, g => g.ToList(), StringComparer.Ordinal);
        Transform Bone(string name)
        {
            if (!bones.TryGetValue(name, out List<Transform> found) || found.Count != 1)
                throw new InvalidOperationException(labSid + " anchor bone '" + name + "' is missing or not unique");
            return found[0];
        }
        Shader sprites = Shader.Find("Sprites/Default");
        if (sprites == null)
            throw new InvalidOperationException("Sprites/Default shader is not available in the editor");
        string meshAssetPath = vfxRoot + "/vfx_quads.asset";
        var meshes = new Dictionary<string, Mesh>(StringComparer.Ordinal);
        foreach (PlanQuad q in plan.quads)
        {
            if (q.render != "billboard" && q.render != "groundPlane")
                throw new InvalidOperationException(labSid + " " + q.name + " render " + q.render + " is not delivered by this lane");
            Transform bone = Bone(q.anchorBone);
            Vector3 lossy = bone.lossyScale;
            if (Mathf.Abs(lossy.x - lossy.y) > 1e-3f * Mathf.Abs(lossy.x) || Mathf.Abs(lossy.x - lossy.z) > 1e-3f * Mathf.Abs(lossy.x) || lossy.x <= 0f)
                throw new InvalidOperationException(labSid + " anchor bone " + q.anchorBone + " has non-uniform bind scale " + lossy);
            string sheetAsset = vfxRoot + "/" + Path.GetFileName(q.sheet);
            if (Sha256(q.sheet) != q.sheetSha256)
                throw new InvalidOperationException(labSid + " sheet changed after planning: " + q.sheet);
            if (AssetDatabase.LoadAssetAtPath<Texture2D>(sheetAsset) == null)
            {
                CopyExactFile(q.sheet, ToAbsolute(sheetAsset));
                AssetDatabase.ImportAsset(sheetAsset, ImportAssetOptions.ForceSynchronousImport);
                var importer = (TextureImporter)AssetImporter.GetAtPath(sheetAsset);
                importer.textureType = TextureImporterType.Default;
                importer.sRGBTexture = true;
                importer.alphaIsTransparency = true;
                importer.mipmapEnabled = false;
                importer.filterMode = FilterMode.Point;
                importer.wrapMode = TextureWrapMode.Clamp;
                importer.npotScale = TextureImporterNPOTScale.None;
                importer.textureCompression = TextureImporterCompression.Uncompressed;
                importer.maxTextureSize = 4096;
                importer.SaveAndReimport();
            }
            Texture2D sheet = AssetDatabase.LoadAssetAtPath<Texture2D>(sheetAsset);
            var material = new Material(sprites) { name = q.name, mainTexture = sheet };
            AssetDatabase.CreateAsset(material, vfxRoot + "/" + q.name + ".mat");

            var holder = new GameObject(q.name);
            holder.transform.SetParent(bone, false);
            holder.transform.localPosition = Vector3.zero;
            holder.transform.localRotation = Quaternion.identity;
            holder.transform.localScale = new Vector3(q.sizeUnits[0] / lossy.x, q.sizeUnits[1] / lossy.x, 1f);
            foreach (PlanQuadCell cell in q.cells)
            {
                string meshKey = "vfx_quad_" + q.tilesX + "x" + q.tilesY + "_c" + cell.index;
                if (!meshes.TryGetValue(meshKey, out Mesh quadMesh))
                {
                    quadMesh = CellQuad(meshKey, cell.uvRect);
                    if (meshes.Count == 0)
                        AssetDatabase.CreateAsset(quadMesh, meshAssetPath);
                    else
                        AssetDatabase.AddObjectToAsset(quadMesh, meshAssetPath);
                    meshes[meshKey] = quadMesh;
                }
                var child = new GameObject("c" + cell.index);
                child.transform.SetParent(holder.transform, false);
                child.AddComponent<MeshFilter>().sharedMesh = quadMesh;
                var renderer = child.AddComponent<MeshRenderer>();
                renderer.sharedMaterial = material;
                renderer.shadowCastingMode = ShadowCastingMode.Off;
                renderer.receiveShadows = false;
                renderer.lightProbeUsage = LightProbeUsage.Off;
                renderer.reflectionProbeUsage = ReflectionProbeUsage.Off;
                renderer.enabled = false;
            }
            built.quadPaths[q.name] = RelativeTransformPath(instance.transform, holder.transform);
            built.report.Add("{\"kind\":\"" + q.render + "\",\"name\":\"" + q.name + "\",\"clip\":\"" + q.clip + "\",\"bone\":\"" + q.anchorBone
                + "\",\"cells\":" + q.cells.Length + ",\"boneBindScale\":" + F(lossy.x) + ",\"sizeUnits\":[" + F(q.sizeUnits[0]) + "," + F(q.sizeUnits[1]) + "]}");
        }
        foreach (PlanLight l in plan.lights)
        {
            Transform bone = Bone(l.anchorBone);
            var go = new GameObject(l.name);
            go.transform.SetParent(bone, false);
            var light = go.AddComponent<Light>();
            light.type = LightType.Point;
            light.color = new Color(l.rgb[0], l.rgb[1], l.rgb[2], 1f);
            light.range = l.range;
            light.intensity = 0f;
            light.shadows = LightShadows.None;
            // Hex/Lit reads Unity's per-object light list (unity_LightData.y, up to 8, sorted by importance):
            // "Important" keeps a unit's own effect light ahead of the native particle lights (NotImportant).
            light.renderMode = LightRenderMode.ForcePixel;
            light.enabled = false;
            built.lightPaths[l.name] = RelativeTransformPath(instance.transform, go.transform);
            built.report.Add("{\"kind\":\"effectLight\",\"name\":\"" + l.name + "\",\"bone\":\"" + l.anchorBone + "\",\"range\":" + F(l.range) + "}");
        }
        AssetDatabase.SaveAssets();
        return built;
    }

    private static Mesh CellQuad(string name, float[] uvRect)
    {
        if (uvRect == null || uvRect.Length != 4)
            throw new InvalidOperationException("cell uvRect must be [sx, sy, ox, oy]");
        float u0 = uvRect[2], v0 = uvRect[3], u1 = uvRect[2] + uvRect[0], v1 = uvRect[3] + uvRect[1];
        var mesh = new Mesh { name = name };
        mesh.vertices = new[] { new Vector3(-0.5f, -0.5f, 0f), new Vector3(0.5f, -0.5f, 0f), new Vector3(0.5f, 0.5f, 0f), new Vector3(-0.5f, 0.5f, 0f) };
        mesh.uv = new[] { new Vector2(u0, v0), new Vector2(u1, v0), new Vector2(u1, v1), new Vector2(u0, v1) };
        mesh.normals = new[] { Vector3.back, Vector3.back, Vector3.back, Vector3.back };
        mesh.triangles = new[] { 0, 2, 1, 0, 3, 2 };
        mesh.RecalculateBounds();
        return mesh;
    }

    private static AnimationCurve StepCurve(IEnumerable<KeyValuePair<float, float>> keys)
    {
        var ordered = new SortedDictionary<float, float>();
        foreach (var k in keys)
            ordered[Mathf.Max(0f, k.Key)] = k.Value;       // a later key at the same time wins
        var curve = new AnimationCurve();
        foreach (var k in ordered)
            curve.AddKey(new Keyframe(k.Key, k.Value, float.PositiveInfinity, float.PositiveInfinity));
        for (int i = 0; i < curve.length; i++)
        {
            AnimationUtility.SetKeyLeftTangentMode(curve, i, AnimationUtility.TangentMode.Constant);
            AnimationUtility.SetKeyRightTangentMode(curve, i, AnimationUtility.TangentMode.Constant);
        }
        return curve;
    }

    private static AnimationCurve ConstCurve(float value)
    {
        return StepCurve(new[] { new KeyValuePair<float, float>(0f, value) });
    }

    private static int BakeVfxCurves(AnimationClip clip, string clipName, VfxPlan plan, BuiltVfx built, GameObject sampler, string labSid)
    {
        int curves = 0;
        void Set(string path, Type type, string property, AnimationCurve curve)
        {
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, type, property), curve);
            curves++;
        }
        if (built.hasAtlas)
        {
            PlanAtlasClip atlasClip = (plan.uvAtlas.clips ?? new PlanAtlasClip[0]).FirstOrDefault(c => c.clip == clipName);
            var keys = atlasClip != null ? atlasClip.keys : new[] { new PlanCellKey { t = 0f, cell = plan.uvAtlas.restCell } };
            string[] comps = { "x", "y", "z", "w" };
            for (int c = 0; c < 4; c++)
            {
                int comp = c;
                Set(built.bodyPath, typeof(SkinnedMeshRenderer), "material._MainTex_ST." + comps[c],
                    StepCurve(keys.Select(k => new KeyValuePair<float, float>(k.t, plan.uvAtlas.cells[k.cell].st[comp]))));
            }
        }
        foreach (PlanQuad q in plan.quads)
        {
            string holder = built.quadPaths[q.name];
            foreach (PlanQuadCell cell in q.cells)
            {
                AnimationCurve curve = q.clip == clipName
                    ? StepCurve(q.keys.Select(k => new KeyValuePair<float, float>(k.t, k.cell == cell.index ? 1f : 0f)))
                    : ConstCurve(0f);
                Set(holder + "/c" + cell.index, typeof(MeshRenderer), "m_Enabled", curve);
            }
        }
        foreach (PlanLight l in plan.lights)
        {
            string path = built.lightPaths[l.name];
            PlanLightClip lightClip = (l.clips ?? new PlanLightClip[0]).FirstOrDefault(c => c.clip == clipName);
            Transform bone = sampler.GetComponentsInChildren<Transform>(true).Single(t => t.name == l.anchorBone);
            if (lightClip == null)
            {
                // A clip without a curve holds the floor (docs "Floors"): on when floor > 0. The light sits where the
                // first curve's first key puts it, in this clip's own first pose (for a body-fire light that is the
                // authored offset toward the camera; at the bone origin it would sit inside the body, N.L < 0).
                Set(path, typeof(Light), "m_Enabled", ConstCurve(l.floor > 0f ? 1f : 0f));
                Set(path, typeof(Light), "m_Intensity", ConstCurve(l.floor));
                PlanLightKey hold = (l.clips ?? new PlanLightClip[0]).Where(c => c.keys != null && c.keys.Length > 0).Select(c => c.keys[0]).FirstOrDefault();
                if (l.floor > 0f && hold != null)
                {
                    clip.SampleAnimation(sampler, 0f);
                    Vector3 holdLocal = bone.InverseTransformPoint(sampler.transform.TransformPoint(new Vector3(hold.rootPosition[0], hold.rootPosition[1], hold.rootPosition[2])));
                    string[] holdAxes = { "x", "y", "z" };
                    for (int a = 0; a < 3; a++)
                        Set(path, typeof(Transform), "m_LocalPosition." + holdAxes[a], ConstCurve(holdLocal[a]));
                }
                continue;
            }
            var local = new List<Vector3>();
            foreach (PlanLightKey k in lightClip.keys)
            {
                clip.SampleAnimation(sampler, k.tPose);
                Vector3 rootPoint = new Vector3(k.rootPosition[0], k.rootPosition[1], k.rootPosition[2]);
                local.Add(bone.InverseTransformPoint(sampler.transform.TransformPoint(rootPoint)));
            }
            Set(path, typeof(Light), "m_Enabled", StepCurve(lightClip.keys.Select(k => new KeyValuePair<float, float>(k.t, k.intensity > 0f ? 1f : 0f))));
            Set(path, typeof(Light), "m_Intensity", StepCurve(lightClip.keys.Select(k => new KeyValuePair<float, float>(k.t, k.intensity))));
            string[] axes = { "x", "y", "z" };
            for (int a = 0; a < 3; a++)
            {
                int axis = a;
                Set(path, typeof(Transform), "m_LocalPosition." + axes[a],
                    StepCurve(lightClip.keys.Select((k, i) => new KeyValuePair<float, float>(k.t, local[i][axis]))));
            }
        }
        return curves;
    }

    // mergeMeshes: the master must be the plan's merged GLB, no merged node may still import as its own SMR, and the
    // body SMR must carry exactly the merged vertex count in one submesh (glTFast keeps one primitive's vertices 1:1).
    private static string RequireMergedMaster(UnitSpec spec, VfxPlan plan, SkinnedMeshRenderer[] allSkins, Mesh mesh)
    {
        PlanMergedMesh[] merged = plan.mergedMeshes ?? new PlanMergedMesh[0];
        if (merged.Length == 0)
            return "";
        PlanMergedMaster mm = plan.mergedMaster;
        if (mm == null || mm.totalVertices <= 0 || !string.Equals(Sha256(spec.masterGlb), mm.sha256, StringComparison.Ordinal))
            throw new InvalidOperationException(spec.labSid + " master GLB is not the plan's merged master; rerun prepare");
        int end = mm.bodyVertices;
        foreach (PlanMergedMesh m in merged.OrderBy(x => x.firstVertex))
        {
            if (allSkins.Any(sk => sk.gameObject.name == m.node))
                throw new InvalidOperationException(spec.labSid + " merged mesh " + m.node + " still imports as its own SkinnedMeshRenderer");
            if (m.firstVertex != end || m.vertices <= 0)
                throw new InvalidOperationException(spec.labSid + " merged mesh " + m.node + " range does not follow the body");
            end += m.vertices;
        }
        if (end != mm.totalVertices || mesh.vertexCount != mm.totalVertices || mesh.subMeshCount != 1)
            throw new InvalidOperationException(spec.labSid + " body mesh imported " + mesh.vertexCount + " vertices in "
                + mesh.subMeshCount + " submeshes; the merged master has " + mm.totalVertices + " in one");
        return string.Join(", ", merged.Select(m => "{\"node\":\"" + m.node + "\",\"firstVertex\":" + m.firstVertex
            + ",\"vertices\":" + m.vertices + "}"));
    }

    private static string Sha256(string path)
    {
        using (var digest = SHA256.Create())
        using (var stream = File.OpenRead(path))
            return BitConverter.ToString(digest.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }

    private static string F(float value)
    {
        return value.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
    }
}
