using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEngine;

/// <summary>
/// Builds the Crusader skinned-mesh lab lane without replacing the existing
/// billboard prefab. Master and clips come from the GPU cascade smartrig
/// delivery tree. This is intentionally fail-closed: an imported mesh without
/// skinning or a clip without an AnimationClip asset is not promoted.
/// </summary>
public static class CrusaderOwnedSkinnedLabBuild
{
    private const string AssetRoot = "Assets/CustomUnits/homm3_lab/h3_crusader/OwnedSkinned";
    private const string SourceRoot = AssetRoot + "/Source";
    private const string AnimationRoot = AssetRoot + "/Animations";
    private const string TempRoot = AssetRoot + "/Temp";
    private const string PrefabPath = AssetRoot + "/crusader_owned_skinned.prefab";
    private const string OverridePath = AssetRoot + "/crusader_owned_skinned.overrideController";
    private const string MaterialPath = AssetRoot + "/crusader_owned_skinned.mat";
    private const string AlbedoTexturePath = AssetRoot + "/crusader_owned_skinned_basecolor.jpg";
    private const string NormalTexturePath = AssetRoot + "/crusader_owned_skinned_normal.png";
    private const string MetallicGlossTexturePath = AssetRoot + "/crusader_owned_skinned_metallicgloss.png";
    private const string DeliveryAlbedoSource = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\crusader_owned_skinned_basecolor.jpg";
    private const string DeliveryNormalSource = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\crusader_owned_skinned_normal.png";
    private const string DeliveryMetallicGlossSource = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\crusader_owned_skinned_metallicgloss.png";
    private const float HexLitSmoothness = 0.35f;
    private const string AuditPath = AssetRoot + "/crusader_owned_skinned_audit.json";
    private const string SkinnedLaneMarkerName = "__homm3_skinned_battle_lane__";
    private const string RuntimeShaderGuid = "78014d7ab89888f49b8c173e150ffc71";

    private const string MasterSource = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\crusader_smartrig_master.glb";

    private sealed class ClipSpec
    {
        public string ContractName;
        public string SourcePath;
    }

    /// <summary>
    /// Loop states: Idle/Mouseover, Walk/Move, Stance/Defence. The authored DEF-derived
    /// clips are single open cycles (f0..fN with an fN->f0 jump-cut, matching the source
    /// DEF billboard loop); with loopTime off the Animator plays each state once and then
    /// holds the final pose, which is the observed "does not loop/flow" failure.
    /// </summary>
    private static readonly Dictionary<string, bool> LoopByContract = new Dictionary<string, bool>(StringComparer.Ordinal)
    {
        { "Crusader_Move", true },
        { "Crusader_Idle", true },
        { "Crusader_Mouseover", true },
        { "Crusader_Defence", true },
    };

    /// <summary>
    /// Target durations (seconds) per contract, taken from the stock Esquire etalon clips each
    /// contract overrides (measured from the lab's <c>Reference/etalon/*.anim</c> files). The
    /// stock controller states all run at speed 1.0, so the vanilla playback cadence is defined
    /// by these clip lengths. Without the rescale, the short DEF-derived cycles (0.34-0.47s)
    /// play several times faster than vanilla units at every battle speed setting (idle 0.68s vs
    /// stock 22.Idle 5.33s, walk 0.68s vs stock 01.Walk 1.167s, attack ~0.9s vs stock 2.0s).
    /// </summary>
    private static readonly Dictionary<string, float> TargetSecondsByContract = new Dictionary<string, float>(StringComparer.Ordinal)
    {
        { "Crusader_Move", 1.1666667f },     // 01.Walk
        { "Crusader_Idle", 5.3333335f },      // 22.Idle
        { "Crusader_Mouseover", 2f },         // 15.Skill_1 (skills reuse mouseover)
        { "Crusader_Hitted", 1.1666667f },    // 20.Damage
        { "Crusader_Defence", 1.2f },         // 25.Stance (27.Victory is 2.0s; stance is the visible defence state)
        { "Crusader_Death", 0.8333334f },     // 21.Death
        { "Crusader_AttackFront", 2f },       // 14.Attack
        { "Crusader_MoveStart", 0.6666667f }, // 05.Fly_Start / 24.Stance_In
        { "Crusader_MoveEnd", 0.5f },         // 06.Fly_End / 26.Stance_Out
    };

    private sealed class MasterPrefabResult
    {
        public string AssetPath;
        public int SkinCount;
    }

    private static readonly ClipSpec[] Clips =
    {
        new ClipSpec { ContractName = "Crusader_Move", SourcePath = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\clips\Crusader_Move.glb" },
        new ClipSpec { ContractName = "Crusader_Idle", SourcePath = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\clips\Crusader_Idle.glb" },
        new ClipSpec { ContractName = "Crusader_Mouseover", SourcePath = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\clips\Crusader_Mouseover.glb" },
        new ClipSpec { ContractName = "Crusader_Hitted", SourcePath = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\clips\Crusader_Hitted.glb" },
        new ClipSpec { ContractName = "Crusader_Defence", SourcePath = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\clips\Crusader_Defence.glb" },
        new ClipSpec { ContractName = "Crusader_Death", SourcePath = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\clips\Crusader_Death.glb" },
        new ClipSpec { ContractName = "Crusader_AttackFront", SourcePath = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\clips\Crusader_AttackFront.glb" },
        new ClipSpec { ContractName = "Crusader_MoveStart", SourcePath = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\clips\Crusader_MoveStart.glb" },
        new ClipSpec { ContractName = "Crusader_MoveEnd", SourcePath = @"V:\Games\Olden Era Playtest Tweak\artifacts\crusader_pose_pipeline\gpu_cascade_skinned\clips\Crusader_MoveEnd.glb" },
    };

    [MenuItem("Tools/Crusader/Build Owned Skinned Lab")]
    public static void Build()
    {
        try
        {
            BuildInternal();
            Debug.Log("Crusader owned skinned lab build passed.");
        }
        catch (Exception ex)
        {
            Debug.LogError("Crusader owned skinned lab build failed: " + ex);
            throw;
        }
    }

    public static void BuildMaterialAndPrefab()
    {
        try
        {
            BuildMasterPrefab();
            ApplyExistingOverrideController();
            AssetDatabase.SaveAssets();
            Debug.Log("Crusader owned skinned material/prefab build passed.");
        }
        catch (Exception ex)
        {
            Debug.LogError("Crusader owned skinned material/prefab build failed: " + ex);
            throw;
        }
    }

    private static void BuildInternal()
    {
        RequireFile(MasterSource);
        foreach (ClipSpec spec in Clips)
            RequireFile(spec.SourcePath);

        MasterPrefabResult master = BuildMasterPrefab();

        List<AnimationClip> importedClips = new List<AnimationClip>();
        foreach (ClipSpec spec in Clips)
        {

            string tempFileName = Path.GetFileNameWithoutExtension(spec.SourcePath) + ".glb";
            string tempAssetPath = TempRoot + "/" + tempFileName;
            File.Copy(spec.SourcePath, ToAbsolute(tempAssetPath), true);
            AssetDatabase.ImportAsset(tempAssetPath, ImportAssetOptions.ForceSynchronousImport);

            UnityEngine.Object[] imported = AssetDatabase.LoadAllAssetsAtPath(tempAssetPath);
            AnimationClip[] clips = imported.OfType<AnimationClip>().ToArray();
            Debug.Log("Crusader clip import " + spec.ContractName + " from " + tempAssetPath + ": " + string.Join(", ", clips.Select(c => c.name).ToArray()));
            if (clips.Length != 1)
                throw new InvalidOperationException("Expected exactly one AnimationClip from " + tempAssetPath + ", found " + clips.Length);

            AnimationClip sourceClip = clips[0];
            string outputPath = AnimationRoot + "/" + spec.ContractName + ".anim";
            if (AssetDatabase.LoadAssetAtPath<AnimationClip>(outputPath) != null)
                AssetDatabase.DeleteAsset(outputPath);
            AnimationClip copy = new AnimationClip();
            copy.name = spec.ContractName;
            copy.frameRate = sourceClip.frameRate;
            RebaseClipPaths(copy, sourceClip);
            FlattenRotationTangents(copy);
            copy.EnsureQuaternionContinuity();
            if (TargetSecondsByContract.TryGetValue(spec.ContractName, out float targetSeconds))
                RescaleClipToDuration(copy, targetSeconds);
            FlattenRotationTangents(copy);
            copy.EnsureQuaternionContinuity();
            ApplyLoopSetting(copy, LoopByContract.TryGetValue(spec.ContractName, out bool loops) && loops);
            AssetDatabase.CreateAsset(copy, outputPath);
            importedClips.Add(AssetDatabase.LoadAssetAtPath<AnimationClip>(outputPath));

            AssetDatabase.DeleteAsset(tempAssetPath);
        }
        DeleteUncontractedAnimationClips();
        AssetDatabase.Refresh();

        RuntimeAnimatorController donor = AssetDatabase.LoadAssetAtPath<RuntimeAnimatorController>(
            "Assets/CustomUnits/homm3_lab/h3_crusader/Reference/StockEsquireBattle.controller");
        if (donor == null)
            throw new InvalidOperationException("Stock Esquire controller is missing.");
        Debug.Log("Crusader donor controller clips: " + string.Join(", ", donor.animationClips.Select(c => c.name).ToArray()));

        if (AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(OverridePath) != null)
            AssetDatabase.DeleteAsset(OverridePath);
        AnimatorOverrideController overrides = new AnimatorOverrideController(donor);
        overrides.name = "crusader_owned_skinned";
        AssetDatabase.CreateAsset(overrides, OverridePath);

        string[] appliedMappings = ApplyStockContractOverrides(overrides, importedClips);
        GameObject prefabContents = PrefabUtility.LoadPrefabContents(PrefabPath);
        try
        {
            Animator prefabAnimator = prefabContents.GetComponent<Animator>();
            if (prefabAnimator == null)
                prefabAnimator = prefabContents.AddComponent<Animator>();
            if (prefabAnimator == null)
                throw new InvalidOperationException("Unity did not create an Animator on the owned skinned prefab.");
            prefabAnimator.applyRootMotion = false;
            prefabAnimator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            prefabAnimator.runtimeAnimatorController = overrides;
            if (PrefabUtility.SaveAsPrefabAsset(prefabContents, PrefabPath) == null)
                throw new InvalidOperationException("Unity did not save the prefab with the override controller.");
        }
        finally
        {
            PrefabUtility.UnloadPrefabContents(prefabContents);
        }
        WriteAudit(master.AssetPath, PrefabPath, importedClips, donor, master.SkinCount, appliedMappings);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
    }

    private static MasterPrefabResult BuildMasterPrefab()
    {
        RequireFile(MasterSource);
        RequireFile(DeliveryAlbedoSource);
        RequireFile(DeliveryNormalSource);
        RequireFile(DeliveryMetallicGlossSource);
        EnsureDirectory(AssetRoot);
        EnsureDirectory(SourceRoot);
        EnsureDirectory(AnimationRoot);
        EnsureDirectory(TempRoot);
        ClearTempAssets();
        File.Copy(DeliveryAlbedoSource, ToAbsolute(AlbedoTexturePath), true);
        File.Copy(DeliveryNormalSource, ToAbsolute(NormalTexturePath), true);
        File.Copy(DeliveryMetallicGlossSource, ToAbsolute(MetallicGlossTexturePath), true);
        AssetDatabase.ImportAsset(AlbedoTexturePath, ImportAssetOptions.ForceSynchronousImport);
        AssetDatabase.ImportAsset(NormalTexturePath, ImportAssetOptions.ForceSynchronousImport);
        AssetDatabase.ImportAsset(MetallicGlossTexturePath, ImportAssetOptions.ForceSynchronousImport);
        ConfigureDeliveryTexture(AlbedoTexturePath, sRGB: true, normalMap: false);
        ConfigureDeliveryTexture(NormalTexturePath, sRGB: false, normalMap: true);
        ConfigureDeliveryTexture(MetallicGlossTexturePath, sRGB: false, normalMap: false);

        string masterAssetPath = SourceRoot + "/crusader_master_rigid_components.glb";
        File.Copy(MasterSource, ToAbsolute(masterAssetPath), true);
        AssetDatabase.ImportAsset(masterAssetPath, ImportAssetOptions.ForceSynchronousImport);

        GameObject masterAsset = AssetDatabase.LoadAssetAtPath<GameObject>(masterAssetPath);
        if (masterAsset == null)
            throw new InvalidOperationException("Master GLB did not import a root GameObject: " + masterAssetPath);

        SkinnedMeshRenderer[] skin = masterAsset.GetComponentsInChildren<SkinnedMeshRenderer>(true);
        if (skin.Length == 0)
            throw new InvalidOperationException("Master GLB imported without a SkinnedMeshRenderer.");
        if (skin.Any(s => s.sharedMesh == null || s.bones == null || s.bones.Length == 0))
            throw new InvalidOperationException("Master GLB contains an incomplete SkinnedMeshRenderer.");

        Material battleMaterial = BuildRuntimeCompatibleMaterial(skin[0].sharedMaterial);
        if (battleMaterial == null)
            throw new InvalidOperationException("Runtime-compatible Crusader material was not created.");

        if (AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath) != null)
            AssetDatabase.DeleteAsset(PrefabPath);
        GameObject masterInstance = UnityEngine.Object.Instantiate(masterAsset);
        masterInstance.name = "crusader_owned_skinned";
        foreach (SkinnedMeshRenderer renderer in masterInstance.GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            Material[] materials = renderer.sharedMaterials;
            for (int i = 0; i < materials.Length; i++)
                materials[i] = battleMaterial;
            renderer.sharedMaterials = materials;
        }
        Animator animator = masterInstance.GetComponent<Animator>();
        if (animator == null)
            animator = masterInstance.AddComponent<Animator>();
        if (animator == null)
            throw new InvalidOperationException("Unity did not create an Animator on the owned skinned instance.");
        animator.applyRootMotion = false;
        animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
        		Transform existingMarker = masterInstance.transform.Find(SkinnedLaneMarkerName);
        		if (existingMarker == null)
        		{
        			GameObject marker = new GameObject(SkinnedLaneMarkerName);
        			marker.transform.SetParent(masterInstance.transform, false);
        			// The mesh content carries the vanilla ecz +90 yaw bake (Orientation group in the
        			// master GLB); the marker encodes the same forward so target-facing stays consistent.
        			marker.transform.localRotation = Quaternion.Euler(0f, 90f, 0f);
        		}
        		else
        		{
        			existingMarker.localRotation = Quaternion.Euler(0f, 90f, 0f);
        		}
        bool prefabSaved;
        PrefabUtility.SaveAsPrefabAsset(masterInstance, PrefabPath, out prefabSaved);
        UnityEngine.Object.DestroyImmediate(masterInstance);
        if (!prefabSaved)
            throw new InvalidOperationException("Unity did not save the owned skinned prefab.");

        return new MasterPrefabResult { AssetPath = masterAssetPath, SkinCount = skin.Length };
    }

    private static void ApplyExistingOverrideController()
    {
        AnimatorOverrideController overrides = AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(OverridePath);
        if (overrides == null)
            throw new InvalidOperationException("Existing Crusader override controller is missing: " + OverridePath);

        GameObject prefabContents = PrefabUtility.LoadPrefabContents(PrefabPath);
        try
        {
            Animator animator = prefabContents.GetComponent<Animator>();
            if (animator == null)
                throw new InvalidOperationException("Owned skinned prefab has no Animator: " + PrefabPath);
            animator.applyRootMotion = false;
            animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            animator.runtimeAnimatorController = overrides;
            if (PrefabUtility.SaveAsPrefabAsset(prefabContents, PrefabPath) == null)
                throw new InvalidOperationException("Unity did not save the prefab with the existing override controller.");
        }
        finally
        {
            PrefabUtility.UnloadPrefabContents(prefabContents);
        }
    }

    private static void ClearTempAssets()
    {
        if (!Directory.Exists(ToAbsolute(TempRoot)))
            return;

        foreach (string file in Directory.GetFiles(ToAbsolute(TempRoot), "*.glb", SearchOption.TopDirectoryOnly))
        {
            string assetPath = file.Replace('\\', '/');
            int assetsIndex = assetPath.IndexOf("/Assets/", StringComparison.OrdinalIgnoreCase);
            if (assetsIndex >= 0)
                assetPath = assetPath.Substring(assetsIndex + 1);
            AssetDatabase.DeleteAsset(assetPath);
        }
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
    }

    private static void DeleteUncontractedAnimationClips()
    {
        if (!Directory.Exists(ToAbsolute(AnimationRoot)))
            return;

        HashSet<string> keep = new HashSet<string>(
            Clips.Select(spec => spec.ContractName + ".anim"),
            StringComparer.Ordinal);
        foreach (string file in Directory.GetFiles(ToAbsolute(AnimationRoot), "*.anim", SearchOption.TopDirectoryOnly))
        {
            string fileName = Path.GetFileName(file);
            if (keep.Contains(fileName))
                continue;
            string assetPath = AnimationRoot + "/" + fileName;
            AssetDatabase.DeleteAsset(assetPath);
            Debug.Log("Crusader lab deleted uncontracted clip " + assetPath);
        }
    }

    private static Material BuildRuntimeCompatibleMaterial(Material sourceMaterial)
    {
        Material stock = AssetDatabase.LoadAssetAtPath<Material>(
            "Assets/CustomUnits/esquire/Reference/etalon/Etalon_mt.mat");
        if (stock == null || stock.shader == null)
            throw new InvalidOperationException("Stock runtime-compatible Etalon material/shader is missing.");

        if (AssetDatabase.LoadAssetAtPath<Material>(MaterialPath) != null)
            AssetDatabase.DeleteAsset(MaterialPath);
        Material material = new Material(stock)
        {
            name = "crusader_owned_skinned"
        };

        Texture albedo = AssetDatabase.LoadAssetAtPath<Texture>(AlbedoTexturePath);
        Texture normal = AssetDatabase.LoadAssetAtPath<Texture>(NormalTexturePath);
        Texture metallicGloss = AssetDatabase.LoadAssetAtPath<Texture>(MetallicGlossTexturePath);
        if (albedo == null)
            throw new InvalidOperationException("Crusader albedo is missing: " + AlbedoTexturePath);
        if (normal == null)
            throw new InvalidOperationException("Crusader normal is missing: " + NormalTexturePath);
        if (metallicGloss == null)
            throw new InvalidOperationException("Crusader metallic-gloss is missing: " + MetallicGlossTexturePath);
        if (material.HasProperty("_MainTex"))
            material.SetTexture("_MainTex", albedo);
        if (material.HasProperty("_BaseMap"))
            material.SetTexture("_BaseMap", albedo);
        BindNormalMap(material, normal);
        BindMetallicGlossMap(material, metallicGloss);
        if (sourceMaterial != null)
        {
            if (sourceMaterial.HasProperty("_BaseColor") && material.HasProperty("_Color"))
                material.SetColor("_Color", sourceMaterial.GetColor("_BaseColor"));
            else if (sourceMaterial.HasProperty("_Color") && material.HasProperty("_Color"))
                material.SetColor("_Color", sourceMaterial.GetColor("_Color"));
        }
        if (material.HasProperty("_Cull"))
            material.SetFloat("_Cull", 0f);
        if (material.HasProperty("_AlphaClipEnabled"))
            material.SetFloat("_AlphaClipEnabled", 0f);

        AssetDatabase.CreateAsset(material, MaterialPath);
        AssetDatabase.SaveAssets();
        NormalizeRuntimeMaterialYaml();
        AssetDatabase.ImportAsset(MaterialPath, ImportAssetOptions.ForceSynchronousImport);
        return AssetDatabase.LoadAssetAtPath<Material>(MaterialPath);
    }

    private static void NormalizeRuntimeMaterialYaml()
    {
        string absolutePath = ToAbsolute(MaterialPath);
        string yaml = File.ReadAllText(absolutePath);
        yaml = yaml.Replace("m_Shader: {fileID: 0}", "m_Shader: {fileID: 4800000, guid: " + RuntimeShaderGuid + ", type: 3}");
        yaml = yaml.Replace("_AlphaClipEnabled: 1", "_AlphaClipEnabled: 0");
        yaml = BindSerializedTexture(yaml, "_MainTex", AlbedoTexturePath, required: true);
        yaml = BindSerializedTexture(yaml, "_BumpMap", NormalTexturePath, required: false);
        yaml = BindSerializedTexture(yaml, "_MetallicGlossMap", MetallicGlossTexturePath, required: false);
        File.WriteAllText(absolutePath, yaml);
    }

    private static string BindSerializedTexture(string yaml, string propertyName, string assetPath, bool required)
    {
        string guid = AssetDatabase.AssetPathToGUID(assetPath);
        if (string.IsNullOrEmpty(guid))
            throw new InvalidOperationException("Missing GUID for " + assetPath);
        string[] lines = yaml.Split(new[] { "\r\n", "\n" }, StringSplitOptions.None);
        bool inProperty = false;
        bool bound = false;
        for (int i = 0; i < lines.Length; i++)
        {
            if (lines[i].Trim() == "- " + propertyName + ":")
            {
                inProperty = true;
                continue;
            }
            if (inProperty && lines[i].TrimStart().StartsWith("m_Texture: ", StringComparison.Ordinal))
            {
                lines[i] = "        m_Texture: {fileID: 2800000, guid: " + guid + ", type: 3}";
                inProperty = false;
                bound = true;
            }
        }
        if (!bound && required)
            throw new InvalidOperationException("Etalon material YAML has no " + propertyName + " slot to bind " + assetPath);
        return string.Join("\n", lines);
    }

    private static void ConfigureDeliveryTexture(string assetPath, bool sRGB, bool normalMap)
    {
        TextureImporter importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
        if (importer == null)
            throw new InvalidOperationException("Missing TextureImporter for " + assetPath);
        importer.textureType = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
        importer.sRGBTexture = sRGB;
        importer.mipmapEnabled = true;
        importer.maxTextureSize = 4096;
        importer.textureCompression = TextureImporterCompression.Compressed;
        importer.filterMode = FilterMode.Bilinear;
        importer.wrapMode = TextureWrapMode.Clamp;
        importer.SaveAndReimport();
    }

    private static void BindNormalMap(Material material, Texture normal)
    {
        // The lab cannot execute Hex/Lit. Assign slots when the ripped Etalon sheet
        // exposes them; runtime ApplyOwnedSkinnedHexLitPbr is the fail-closed bind.
        if (material.HasProperty("_BumpMap"))
        {
            material.SetTexture("_BumpMap", normal);
            material.EnableKeyword("_NORMALMAP");
        }
        if (material.HasProperty("_NormalMap"))
        {
            material.SetTexture("_NormalMap", normal);
            material.EnableKeyword("_NORMALMAP");
        }
    }

    private static void BindMetallicGlossMap(Material material, Texture metallicGloss)
    {
        if (material.HasProperty("_MetallicGlossMap"))
        {
            material.SetTexture("_MetallicGlossMap", metallicGloss);
            material.EnableKeyword("_METALLICGLOSSMAP");
        }
        if (material.HasProperty("_Metallic"))
            material.SetFloat("_Metallic", 1f);
        if (material.HasProperty("_Smoothness"))
            material.SetFloat("_Smoothness", HexLitSmoothness);
        else if (material.HasProperty("_Glossiness"))
            material.SetFloat("_Glossiness", HexLitSmoothness);
    }

    /// <summary>
    /// Unity resolves clip curve paths relative to the Animator's root transform, but the
    /// authored delivery GLBs animate scene-relative paths rooted at the armature node
    /// (e.g. "OwnedCrusader/Hips/..."). The prefab root carries the Animator and its children
    /// start at "Hips", so every unrebased binding misses and the unit stays in bind pose.
    /// Strip the shared leading scene-root segment so the curves bind to the prefab hierarchy.
    /// Copy localRotation only: euler editor curves plus unscaled cubic tangents melt the skin.
    /// </summary>
    private static bool IsLocalRotationProperty(string propertyName)
    {
        if (string.IsNullOrEmpty(propertyName))
            return false;
        if (propertyName.IndexOf("Euler", StringComparison.OrdinalIgnoreCase) >= 0)
            return false;
        return propertyName.StartsWith("m_LocalRotation", StringComparison.Ordinal)
            || propertyName.StartsWith("localRotation", StringComparison.Ordinal);
    }

    private static void RebaseClipPaths(AnimationClip target, AnimationClip source)
    {
        EditorCurveBinding[] bindings = AnimationUtility.GetCurveBindings(source)
            .Where(b => IsLocalRotationProperty(b.propertyName))
            .ToArray();
        if (bindings.Length == 0)
            throw new InvalidOperationException("Crusader clip has no localRotation curves; refusing to promote an empty clip: " + source.name);

        string sharedRoot = FindSharedRootSegment(bindings.Select(b => b.path).ToArray());
        if (string.IsNullOrEmpty(sharedRoot))
            throw new InvalidOperationException("Crusader clip bindings do not share a leading scene-root segment; cannot rebase paths safely: " + source.name);

        foreach (EditorCurveBinding b in bindings)
        {
            AnimationCurve curve = AnimationUtility.GetEditorCurve(source, b);
            string newPath = RebasePath(b.path, sharedRoot);
            AnimationUtility.SetEditorCurve(target, newPath, b.type, b.propertyName, curve);
        }
    }

    private static void FlattenRotationTangents(AnimationClip clip)
    {
        foreach (EditorCurveBinding binding in AnimationUtility.GetCurveBindings(clip))
        {
            if (!IsLocalRotationProperty(binding.propertyName))
                continue;
            AnimationCurve curve = AnimationUtility.GetEditorCurve(clip, binding);
            if (curve == null)
                continue;
            Keyframe[] keys = curve.keys;
            for (int i = 0; i < keys.Length; i++)
            {
                Keyframe key = keys[i];
                key.inTangent = 0f;
                key.outTangent = 0f;
                key.inWeight = 0f;
                key.outWeight = 0f;
                keys[i] = key;
            }
            curve.keys = keys;
            for (int i = 0; i < curve.length; i++)
            {
                AnimationUtility.SetKeyLeftTangentMode(curve, i, AnimationUtility.TangentMode.Linear);
                AnimationUtility.SetKeyRightTangentMode(curve, i, AnimationUtility.TangentMode.Linear);
            }
            AnimationUtility.SetEditorCurve(clip, binding, curve);
        }
    }

    private static string RebasePath(string path, string sharedRoot)
    {
        if (string.IsNullOrEmpty(path))
            return path;
        if (path == sharedRoot)
            return string.Empty;
        if (path.StartsWith(sharedRoot + "/", StringComparison.Ordinal))
            return path.Substring(sharedRoot.Length + 1);
        throw new InvalidOperationException("Crusader clip binding path is not under the shared scene root '" + sharedRoot + "': " + path);
    }

    /// <summary>
    /// Rescales every curve so the clip's total length equals the target duration (the stock
    /// etalon length for the contract it overrides). The clips are rotation-only on bones, so
    /// time-scaling preserves the authored poses and just changes the playback cadence.
    /// </summary>
    private static void RescaleClipToDuration(AnimationClip clip, float targetSeconds)
    {
        if (targetSeconds <= 0f)
            throw new InvalidOperationException("Invalid target duration for crusader clip " + clip.name + ": " + targetSeconds);
        float current = clip.length;
        if (current <= 0f)
            throw new InvalidOperationException("Crusader clip has zero length; cannot rescale: " + clip.name);
        float factor = targetSeconds / current;
        if (Mathf.Abs(factor - 1f) < 0.001f)
            return;
        EditorCurveBinding[] bindings = AnimationUtility.GetCurveBindings(clip);
        foreach (EditorCurveBinding binding in bindings)
        {
            AnimationCurve curve = AnimationUtility.GetEditorCurve(clip, binding);
            Keyframe[] keys = curve.keys;
            for (var i = 0; i < keys.Length; i++)
            {
                Keyframe key = keys[i];
                key.time = key.time * factor;
                key.inTangent /= factor;
                key.outTangent /= factor;
                keys[i] = key;
            }
            curve.keys = keys;
            AnimationUtility.SetEditorCurve(clip, binding, curve);
        }
        Debug.Log("Crusader clip rescale " + clip.name + ": " + current.ToString("0.####") + "s -> " + clip.length.ToString("0.####") + "s (target " + targetSeconds.ToString("0.####") + "s).");
    }

    private static void ApplyLoopSetting(AnimationClip clip, bool loop)
    {
        AnimationClipSettings settings = AnimationUtility.GetAnimationClipSettings(clip);
        settings.loopTime = loop;
        AnimationUtility.SetAnimationClipSettings(clip, settings);
    }

    private static string FindSharedRootSegment(string[] paths)
    {
        string[] nonEmpty = paths.Where(p => !string.IsNullOrEmpty(p)).ToArray();
        if (nonEmpty.Length == 0)
            return null;
        string first = nonEmpty[0];
        int slash = first.IndexOf('/');
        string candidate = slash < 0 ? first : first.Substring(0, slash);
        foreach (string p in nonEmpty)
        {
            if (p != candidate && !p.StartsWith(candidate + "/", StringComparison.Ordinal))
                return null;
        }
        return candidate;
    }

    private static string[] ApplyStockContractOverrides(AnimatorOverrideController overrides, List<AnimationClip> importedClips)
    {
        Dictionary<string, AnimationClip> replacements = importedClips.ToDictionary(c => c.name, StringComparer.Ordinal);
        Dictionary<string, string> stockToOwned = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "01.Walk", "Crusader_Move" },
            { "02.Walk_ability", "Crusader_MoveStart" },
            { "03.Walk_ability_Attack", "Crusader_AttackFront" },
            { "04.Fly", "Crusader_Move" },
            { "05.Fly_Start", "Crusader_MoveStart" },
            { "06.Fly_End", "Crusader_MoveEnd" },
            { "07.Fly_Ability", "Crusader_Move" },
            { "08.Fly_Ability_Start", "Crusader_MoveStart" },
            { "09.Fly_Ability_End", "Crusader_MoveEnd" },
            { "10.Tp_Start", "Crusader_MoveStart" },
            { "11.Tp_End", "Crusader_MoveEnd" },
            { "12.Tp_Ability_Start", "Crusader_MoveStart" },
            { "13.Tp_Ability_End", "Crusader_MoveEnd" },
            { "14.Attack", "Crusader_AttackFront" },
            { "15.Skill_1", "Crusader_Mouseover" },
            { "16.Skill_2", "Crusader_Mouseover" },
            { "17.Skill_3", "Crusader_Mouseover" },
            { "18.Skill_4", "Crusader_Mouseover" },
            { "19.Skill_5", "Crusader_Mouseover" },
            { "20.Damage", "Crusader_Hitted" },
            { "21.Death", "Crusader_Death" },
            { "22.Idle", "Crusader_Idle" },
            { "23.Idle_Rare", "Crusader_Idle" },
            { "24.Stance_In", "Crusader_MoveStart" },
            { "25.Stance", "Crusader_Defence" },
            { "26.Stance_Out", "Crusader_MoveEnd" },
            { "27.Victory", "Crusader_Defence" },
        };

        List<KeyValuePair<AnimationClip, AnimationClip>> pairs = new List<KeyValuePair<AnimationClip, AnimationClip>>();
        overrides.GetOverrides(pairs);
        List<string> applied = new List<string>();
        for (int i = 0; i < pairs.Count; i++)
        {
            KeyValuePair<AnimationClip, AnimationClip> pair = pairs[i];
            if (pair.Key == null || !stockToOwned.TryGetValue(pair.Key.name, out string ownedName))
                throw new InvalidOperationException("Stock controller contains an unmapped clip: " + (pair.Key == null ? "<null>" : pair.Key.name));
            if (!replacements.TryGetValue(ownedName, out AnimationClip replacement))
                throw new InvalidOperationException("Owned clip required for stock contract is missing: " + ownedName);
            pairs[i] = new KeyValuePair<AnimationClip, AnimationClip>(pair.Key, replacement);
            applied.Add(pair.Key.name + " -> " + replacement.name);
        }

        string[] missing = stockToOwned.Keys.Where(name => !applied.Any(entry => entry.StartsWith(name + " -> ", StringComparison.Ordinal))).ToArray();
        if (missing.Length != 0)
            throw new InvalidOperationException("Stock controller contract clips were not found: " + string.Join(", ", missing));
        overrides.ApplyOverrides(pairs);
        return applied.ToArray();
    }

    private static void WriteAudit(string masterAssetPath, string prefabPath, List<AnimationClip> clips, RuntimeAnimatorController donor, int skinCount, string[] appliedMappings)
    {
        string json = "{\n" +
            "  \"masterAsset\": \"" + masterAssetPath + "\",\n" +
            "  \"prefab\": \"" + prefabPath + "\",\n" +
            "  \"skinnedMeshRendererCount\": " + skinCount + ",\n" +
            "  \"animationClipCount\": " + clips.Count + ",\n" +
            "  \"animationClips\": [" + string.Join(", ", clips.Select(c => "\"" + c.name + "\"").ToArray()) + "],\n" +
            "  \"donorController\": \"" + donor.name + "\",\n" +
            "  \"overrideMappingsApplied\": true,\n" +
            "  \"overrideMappings\": [" + string.Join(", ", appliedMappings.Select(m => "\"" + m + "\"").ToArray()) + "],\n" +
            "  \"proof\": \"Unity-imported lab artifact; runtime replacement not yet proven.\"\n" +
            "}\n";
        File.WriteAllText(ToAbsolute(AuditPath), json, Encoding.UTF8);
        AssetDatabase.ImportAsset(AuditPath, ImportAssetOptions.ForceSynchronousImport);
    }

    private static void EnsureDirectory(string assetPath)
    {
        string absolute = ToAbsolute(assetPath);
        if (!Directory.Exists(absolute))
            Directory.CreateDirectory(absolute);
    }

    private static string ToAbsolute(string assetPath)
    {
        string projectRoot = Directory.GetParent(Application.dataPath).FullName;
        return Path.Combine(projectRoot, assetPath.Replace('/', Path.DirectorySeparatorChar));
    }

    private static void RequireFile(string path)
    {
        if (!File.Exists(path))
            throw new FileNotFoundException("Required Crusader delivery input is missing.", path);
    }
}
