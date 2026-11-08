using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Security.Cryptography;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using Unity.Collections;

/// <summary>
/// Generic Meshy SmartRig skinned-mesh lab builder. Reads a JSON batch spec
/// written by prepare_smartrig_skinned_import.py. Crusader keeps its dedicated
/// builder; this path uses Unit_* clip names except when clipPrefix is Crusader.
/// </summary>
public static partial class Homm3OwnedSkinnedLabBuild
{
    // Unity queue shim (tools/unity_queue, docs/unity_queue_runner.md): under UnityQueueDispatcher a job reads its
    // own arguments and records its exit code instead of quitting the shared batch; a direct launch reads the command
    // line and exits as before. The dispatcher refuses a class without this pair.
    static string[] UnityQueueArgs() => AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") as string[] ?? Environment.GetCommandLineArgs();
    static void UnityQueueExit(int code)
    {
        if (AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") == null) { EditorApplication.Exit(code); return; }
        if (!(AppDomain.CurrentDomain.GetData("UnityQueue.ExitCode") is int prev && prev != 0)) AppDomain.CurrentDomain.SetData("UnityQueue.ExitCode", code);
    }

    private const string SkinnedLaneMarkerName = "__homm3_skinned_battle_lane__";
    private const string UnlimitedSkinMarkerName = "__homm3_skin_weights_unlimited__";
    private const string RuntimeShaderGuid = "78014d7ab89888f49b8c173e150ffc71";
    private const string StockController = "Assets/CustomUnits/homm3_lab/h3_crusader/Reference/StockEsquireBattle.controller";
    private const string EtalonMaterial = "Assets/CustomUnits/esquire/Reference/etalon/Etalon_mt.mat";

    [Serializable]
    private class ClipSpec
    {
        public string contractName;
        public string sourcePath;
        public string lifecycleRole;
        public float fps;
        // def_retarget: the animation's name inside masterGlb (clips are not separate GLBs)
        public string sourceAnimation;
    }

    [Serializable]
    private class UnitSpec
    {
        public string labSid;
        public string clipPrefix;
        public string masterGlb;
        public string albedo;
        public string normal;
        public string metallicGloss;
        public string motionAuthority;
        public string skinWeights;
        public string skinWeightsSha256;
        public bool placeholderIdleOnly;
        public ClipSpec[] clips;
        // def_retarget: the unit-look VFX plan written by ship_def_retarget_slice.py prepare
        public string vfxPlan;
    }

    [Serializable]
    private class BatchSpec
    {
        public UnitSpec[] units;
    }

    // Lifecycle roles own loopTime. Suffix lookup is not authority.
    private static readonly Dictionary<string, bool> LoopBySuffix = new Dictionary<string, bool>(StringComparer.Ordinal)
    {
        { "Move", true },
        { "Idle", true },
        { "Mouseover", true },
        { "Defence", true },
    };

    [MenuItem("Tools/HoMM3/Build Owned Skinned Lab Batch")]
    public static void BuildFromMenu()
    {
        BuildFromSpecPath(@"V:\Games\Olden Era Playtest Tweak\artifacts\homm3_smartrig_skinned_rollout\unity_lab_batch.json");
    }

    public static void BuildFromCommandLine()
    {
        string specPath = null;
        var args = UnityQueueArgs();
        for (var i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == "-skinnedLabSpec")
                specPath = args[i + 1];
        }
        if (string.IsNullOrEmpty(specPath))
            throw new InvalidOperationException("Homm3OwnedSkinnedLabBuild requires -skinnedLabSpec");
        BuildFromSpecPath(specPath);
    }

    public static void BuildFromSpecPath(string specPath)
    {
        if (!File.Exists(specPath))
            throw new FileNotFoundException("skinned lab spec missing", specPath);
        var batch = JsonUtility.FromJson<BatchSpec>(File.ReadAllText(specPath));
        if (batch == null || batch.units == null || batch.units.Length == 0)
            throw new InvalidOperationException("skinned lab spec has no units[]: " + specPath);
        foreach (var spec in batch.units)
        {
            BuildOne(spec);
            EditorUtility.UnloadUnusedAssetsImmediate(true);
            GC.Collect();
        }
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        Debug.Log("Homm3 owned skinned lab batch passed: " + batch.units.Length + " unit(s).");
    }

    private static void BuildOne(UnitSpec spec)
    {
        if (spec == null || string.IsNullOrEmpty(spec.labSid))
            throw new InvalidOperationException("skinned lab unit spec is missing labSid");
        if (spec.clips == null || spec.clips.Length == 0)
            throw new InvalidOperationException(spec.labSid + " has no clips");
        if (spec.motionAuthority == "def_retarget")
        {
            // Homm3OwnedSkinnedLabBuild.DefRetarget.cs: one master GLB carries every clip, and the
            // clips keep Transform + blendShape curves plus the baked unit-look VFX curves.
            BuildDefRetarget(spec);
            return;
        }
        RequireFile(spec.masterGlb);
        RequireFile(spec.albedo);
        RequireFile(spec.normal);
        RequireFile(spec.metallicGloss);
        foreach (var clip in spec.clips)
            RequireFile(clip.sourcePath);

        string prefix = string.IsNullOrEmpty(spec.clipPrefix) ? "Unit" : spec.clipPrefix;
        string assetRoot = "Assets/CustomUnits/homm3_lab/" + spec.labSid + "/OwnedSkinned";
        string sourceRoot = assetRoot + "/Source";
        string animationRoot = assetRoot + "/Animations";
        string tempRoot = assetRoot + "/Temp";
        string prefabPath = assetRoot + "/owned_skinned.prefab";
        string overridePath = assetRoot + "/owned_skinned.overrideController";
        string materialPath = assetRoot + "/owned_skinned.mat";
        string albedoPath = assetRoot + "/owned_skinned_basecolor.jpg";
        string normalPath = assetRoot + "/owned_skinned_normal.png";
        string metallicPath = assetRoot + "/owned_skinned_metallicgloss.png";
        if (string.Equals(spec.labSid, "h3_crusader", StringComparison.Ordinal))
        {
            prefabPath = assetRoot + "/crusader_owned_skinned.prefab";
            overridePath = assetRoot + "/crusader_owned_skinned.overrideController";
            materialPath = assetRoot + "/crusader_owned_skinned.mat";
            albedoPath = assetRoot + "/crusader_owned_skinned_basecolor.jpg";
            normalPath = assetRoot + "/crusader_owned_skinned_normal.png";
            metallicPath = assetRoot + "/crusader_owned_skinned_metallicgloss.png";
        }

        EnsureDirectory(assetRoot);
        EnsureDirectory(sourceRoot);
        EnsureDirectory(animationRoot);
        EnsureDirectory(tempRoot);
        EnsureDirectory(assetRoot + "/Reference");
        ClearTempAssets(tempRoot);
        string unitController = assetRoot + "/Reference/StockEsquireBattle.controller";
        File.Copy(ToAbsolute(StockController), ToAbsolute(unitController), true);
        AssetDatabase.ImportAsset(unitController, ImportAssetOptions.ForceSynchronousImport);
        if (AssetDatabase.LoadAssetAtPath<RuntimeAnimatorController>(unitController) == null)
            throw new InvalidOperationException(spec.labSid + " per-unit StockEsquireBattle.controller did not import");

        CopyExactFile(spec.albedo, ToAbsolute(albedoPath));
        CopyExactFile(spec.normal, ToAbsolute(normalPath));
        CopyExactFile(spec.metallicGloss, ToAbsolute(metallicPath));
        AssetDatabase.ImportAsset(albedoPath, ImportAssetOptions.ForceSynchronousImport);
        AssetDatabase.ImportAsset(normalPath, ImportAssetOptions.ForceSynchronousImport);
        AssetDatabase.ImportAsset(metallicPath, ImportAssetOptions.ForceSynchronousImport);
        ConfigureDeliveryTexture(albedoPath, sRGB: true, normalMap: false);
        ConfigureDeliveryTexture(normalPath, sRGB: false, normalMap: true);
        ConfigureDeliveryTexture(metallicPath, sRGB: false, normalMap: false);

        string masterAssetPath = sourceRoot + "/master.glb";
        CopyExactFile(spec.masterGlb, ToAbsolute(masterAssetPath));
        AssetDatabase.ImportAsset(masterAssetPath, ImportAssetOptions.ForceSynchronousImport);
        GameObject masterAsset = AssetDatabase.LoadAssetAtPath<GameObject>(masterAssetPath);
        if (masterAsset == null)
            throw new InvalidOperationException(spec.labSid + " master GLB did not import: " + masterAssetPath);
        SkinnedMeshRenderer[] skins = masterAsset.GetComponentsInChildren<SkinnedMeshRenderer>(true);
        if (skins.Length == 0)
            throw new InvalidOperationException(spec.labSid + " master GLB has no SkinnedMeshRenderer");
        if (skins.Any(s => s.sharedMesh == null || s.bones == null || s.bones.Length == 0))
            throw new InvalidOperationException(spec.labSid + " master GLB has an incomplete SkinnedMeshRenderer");

        Material battleMaterial = BuildRuntimeCompatibleMaterial(skins[0].sharedMaterial, materialPath, albedoPath, normalPath, metallicPath);
        if (AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath) != null)
            AssetDatabase.DeleteAsset(prefabPath);
        GameObject masterInstance = UnityEngine.Object.Instantiate(masterAsset);
        masterInstance.name = "owned_skinned";
        if (spec.motionAuthority == "current_mocap_v2")
            RestoreMocapSkinWeights(masterInstance, spec, assetRoot);
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
        animator.applyRootMotion = false;
        animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
        Transform existingMarker = masterInstance.transform.Find(SkinnedLaneMarkerName);
        if (existingMarker == null)
        {
            GameObject marker = new GameObject(SkinnedLaneMarkerName);
            marker.transform.SetParent(masterInstance.transform, false);
            marker.transform.localRotation = Quaternion.Euler(0f, 90f, 0f);
        }
        else
            existingMarker.localRotation = Quaternion.Euler(0f, 90f, 0f);
        bool prefabSaved;
        PrefabUtility.SaveAsPrefabAsset(masterInstance, prefabPath, out prefabSaved);
        UnityEngine.Object.DestroyImmediate(masterInstance);
        if (!prefabSaved)
            throw new InvalidOperationException(spec.labSid + " prefab did not save");

        List<AnimationClip> importedClips = new List<AnimationClip>();
        foreach (var clipSpec in spec.clips)
        {
            string tempAssetPath = tempRoot + "/" + Path.GetFileName(clipSpec.sourcePath);
            File.Copy(clipSpec.sourcePath, ToAbsolute(tempAssetPath), true);
            AssetDatabase.ImportAsset(tempAssetPath, ImportAssetOptions.ForceSynchronousImport);
            AnimationClip[] clips = AssetDatabase.LoadAllAssetsAtPath(tempAssetPath).OfType<AnimationClip>().ToArray();
            if (clips.Length != 1)
                throw new InvalidOperationException(spec.labSid + " expected one AnimationClip from " + tempAssetPath + ", found " + clips.Length);
            string outputPath = animationRoot + "/" + clipSpec.contractName + ".anim";
            if (AssetDatabase.LoadAssetAtPath<AnimationClip>(outputPath) != null)
                AssetDatabase.DeleteAsset(outputPath);
            AnimationClip copy = new AnimationClip { name = clipSpec.contractName, frameRate = clips[0].frameRate };
            bool fixedMocap = spec.motionAuthority == "current_mocap_v2";
            bool authoredFps = fixedMocap
                || spec.motionAuthority == "idle0_bind_first"
                || spec.motionAuthority == "smartrig_gpu_cascade";
            if (authoredFps)
            {
                if (clipSpec.fps <= 0f || float.IsNaN(clipSpec.fps) || float.IsInfinity(clipSpec.fps))
                    throw new InvalidOperationException(spec.labSid + " clip is missing source FPS: " + clipSpec.contractName);
                copy.frameRate = clipSpec.fps;
            }
            RebaseClipPaths(copy, clips[0], spec.labSid, fixedMocap, masterAsset.transform);
            EnsureClipHasPositiveLength(copy, spec.labSid);
            if (!fixedMocap)
                FlattenRotationTangents(copy);
            copy.EnsureQuaternionContinuity();
            // Keep authored 12 fps duration. Fused-push Idle is ~8 frames / 0.58s;
            // stretching to Esquire 5.33s melted the mesh between GIF frames.
            // Loop from the lifecycle row, not a suffix table. loopBlend must stay off.
            if (string.IsNullOrEmpty(clipSpec.lifecycleRole))
                throw new InvalidOperationException(spec.labSid + " clip " + clipSpec.contractName + " is missing lifecycleRole");
            if (clipSpec.lifecycleRole != "cycle" && clipSpec.lifecycleRole != "entry" && clipSpec.lifecycleRole != "exit" && clipSpec.lifecycleRole != "one_shot" && clipSpec.lifecycleRole != "terminal")
                throw new InvalidOperationException(spec.labSid + " clip " + clipSpec.contractName + " has unclassified lifecycleRole " + clipSpec.lifecycleRole);
            ApplyLoopSetting(copy, clipSpec.lifecycleRole == "cycle");
            AssetDatabase.CreateAsset(copy, outputPath);
            importedClips.Add(AssetDatabase.LoadAssetAtPath<AnimationClip>(outputPath));
            AssetDatabase.DeleteAsset(tempAssetPath);
        }
        AssetDatabase.Refresh();

        RuntimeAnimatorController donor = AssetDatabase.LoadAssetAtPath<RuntimeAnimatorController>(StockController);
        if (donor == null)
            throw new InvalidOperationException("Stock Esquire controller is missing: " + StockController);
        if (AssetDatabase.LoadAssetAtPath<AnimatorOverrideController>(overridePath) != null)
            AssetDatabase.DeleteAsset(overridePath);
        AnimatorOverrideController overrides = new AnimatorOverrideController(donor) { name = "owned_skinned" };
        AssetDatabase.CreateAsset(overrides, overridePath);
        ApplyStockContractOverrides(overrides, importedClips, prefix, spec.placeholderIdleOnly, spec.labSid);

        GameObject prefabContents = PrefabUtility.LoadPrefabContents(prefabPath);
        try
        {
            Animator prefabAnimator = prefabContents.GetComponent<Animator>();
            if (prefabAnimator == null)
                prefabAnimator = prefabContents.AddComponent<Animator>();
            prefabAnimator.applyRootMotion = false;
            prefabAnimator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            prefabAnimator.runtimeAnimatorController = overrides;
            if (PrefabUtility.SaveAsPrefabAsset(prefabContents, prefabPath) == null)
                throw new InvalidOperationException(spec.labSid + " prefab controller save failed");
        }
        finally
        {
            PrefabUtility.UnloadPrefabContents(prefabContents);
        }
        File.WriteAllText(
            ToAbsolute(assetRoot + "/owned_skinned_audit.json"),
            "{\n  \"labSid\": \"" + spec.labSid + "\",\n  \"prefab\": \"" + prefabPath + "\",\n  \"placeholderIdleOnly\": " + (spec.placeholderIdleOnly ? "true" : "false") + ",\n  \"proof\": \"Unity-imported lab artifact; OE runtime not claimed.\"\n}\n",
            Encoding.UTF8);
        AssetDatabase.ImportAsset(assetRoot + "/owned_skinned_audit.json", ImportAssetOptions.ForceSynchronousImport);
        Debug.Log("Homm3 owned skinned lab built " + spec.labSid);
    }

    [Serializable]
    private class SkinWeightSpec
    {
        public string schema;
        public int vertexCount;
        public int influenceSlots;
        public float[] vertices;
        public float[] uvs;
        public int[] triangles;
        public string[] jointNames;
        public int[] jointIndices;
        public float[] weights;
    }

    private static void RestoreMocapSkinWeights(GameObject instance, UnitSpec spec, string assetRoot)
    {
        RequireFile(spec.skinWeights);
        using (var digest = SHA256.Create())
        using (var stream = File.OpenRead(spec.skinWeights))
        {
            string actualHash = BitConverter.ToString(digest.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
            if (actualHash != spec.skinWeightsSha256)
                throw new InvalidOperationException(spec.labSid + " source skin sidecar changed after preparation");
        }
        SkinWeightSpec data = JsonUtility.FromJson<SkinWeightSpec>(File.ReadAllText(spec.skinWeights));
        var renderers = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true);
        if (data == null || data.schema != "stronghold-current-mocap-skin-sidecar-v1" || data.influenceSlots != 8 || renderers.Length != 1)
            throw new InvalidOperationException(spec.labSid + " requires one mesh with explicit eight-slot source skin");
        SkinnedMeshRenderer renderer = renderers[0];
        Mesh source = renderer.sharedMesh;
        int n = source.vertexCount;
        if (n != data.vertexCount || data.vertices.Length != n * 3 || data.uvs.Length != n * 2
            || data.weights.Length != n * 8 || data.jointIndices.Length != n * 8
            || renderer.bones.Length != data.jointNames.Length)
            throw new InvalidOperationException(spec.labSid + " imported mesh differs from source skin dimensions");
        for (int j = 0; j < renderer.bones.Length; j++)
            if (renderer.bones[j].name != data.jointNames[j])
                throw new InvalidOperationException(spec.labSid + " imported joint ordering differs at " + j);
        Vector3[] vertices = source.vertices;
        Vector2[] uvs = source.uv;
        int[] triangles = source.triangles;
        if (triangles.Length != data.triangles.Length)
            throw new InvalidOperationException(spec.labSid + " imported triangle count differs");
        for (int t = 0; t < triangles.Length; t += 3)
        {
            var actual = new[] { triangles[t], triangles[t + 1], triangles[t + 2] };
            var expectedTriangle = new[] { data.triangles[t], data.triangles[t + 1], data.triangles[t + 2] };
            Array.Sort(actual);
            Array.Sort(expectedTriangle);
            if (!actual.SequenceEqual(expectedTriangle))
                throw new InvalidOperationException(spec.labSid + " imported triangle ownership differs at " + t / 3);
        }
        var counts = new byte[n];
        var weights = new List<BoneWeight1>(n * 8);
        for (int v = 0; v < n; v++)
        {
            // glTFast reflects X and flips texture V when importing into Unity.
            Vector3 expected = new Vector3(-data.vertices[3 * v], data.vertices[3 * v + 1], data.vertices[3 * v + 2]);
            Vector2 expectedUv = new Vector2(data.uvs[2 * v], 1f - data.uvs[2 * v + 1]);
            if ((vertices[v] - expected).sqrMagnitude > 1e-10f || (uvs[v] - expectedUv).sqrMagnitude > 1e-10f)
                throw new InvalidOperationException(spec.labSid + " imported vertex/UV order differs at " + v);
            float sum = 0f;
            float previous = float.PositiveInfinity;
            for (int k = 0; k < 8; k++)
            {
                float w = data.weights[8 * v + k];
                int joint = data.jointIndices[8 * v + k];
                if (float.IsNaN(w) || float.IsInfinity(w) || w < 0f || w > previous || joint < 0 || joint >= renderer.bones.Length)
                    throw new InvalidOperationException(spec.labSid + " invalid source influence at " + v);
                previous = w;
                sum += w;
                if (w == 0f)
                    continue;
                counts[v]++;
                weights.Add(new BoneWeight1 { boneIndex = joint, weight = w });
            }
            if (Mathf.Abs(sum - 1f) > 1e-5f)
                throw new InvalidOperationException(spec.labSid + " source weights are not normalized at " + v);
        }
        // glTFast can import skin attributes in a packed vertex format that
        // rejects Mesh.SetBoneWeights on a cloned mesh. Rebuild the mesh through
        // Unity's public channel APIs so the skin stream has a compatible layout,
        // while retaining every non-skin channel, submesh, bindpose and blendshape.
        Mesh owned = RebuildMeshWithCompatibleSkinLayout(source);
        owned.name = "owned_mocap_mesh";
        using (var nativeCounts = new NativeArray<byte>(counts, Allocator.Temp))
        using (var nativeWeights = new NativeArray<BoneWeight1>(weights.ToArray(), Allocator.Temp))
            owned.SetBoneWeights(nativeCounts, nativeWeights);
        using (var actualCounts = owned.GetBonesPerVertex())
        using (var actualWeights = owned.GetAllBoneWeights())
        {
            if (actualCounts.Length != n)
                throw new InvalidOperationException(spec.labSid + " Unity returned an invalid per-vertex skin stream");
            int actualTotal = 0;
            for (int i = 0; i < actualCounts.Length; i++) actualTotal += actualCounts[i];
            if (actualTotal != actualWeights.Length)
                throw new InvalidOperationException(spec.labSid + " Unity returned inconsistent skin stream lengths");
            float maxWeightError = 0f, maxLostMass = 0f, maxL1Error = 0f, worstAllowedL1Error = 0f;
            int droppedCount = 0, unexpectedJointCount = 0;
            int expectedOffset = 0, actualOffset = 0;
            const float quantizationStep = 1f / 65535f;
            int violatingVertex = -1;
            for (int vertex = 0; vertex < n; vertex++)
            {
                int expectedEnd = expectedOffset + counts[vertex];
                int actualEnd = actualOffset + actualCounts[vertex];
                float expectedMass = 0f, actualMass = 0f, l1Error = 0f;
                for (int i = expectedOffset; i < expectedEnd; i++) expectedMass += weights[i].weight;
                for (int i = actualOffset; i < actualEnd; i++)
                {
                    BoneWeight1 actual = actualWeights[i];
                    if (float.IsNaN(actual.weight) || float.IsInfinity(actual.weight) || actual.weight < 0f
                        || actual.boneIndex < 0 || actual.boneIndex >= renderer.bones.Length)
                        throw new InvalidOperationException(spec.labSid + " Unity returned an invalid influence at " + vertex);
                    actualMass += actual.weight;
                }
                maxLostMass = Mathf.Max(maxLostMass, Mathf.Max(0f, expectedMass - actualMass));
                // Bound the whole vector's quantization/normalization error.
                // Unity redistributes rounding between slots, so a separate
                // per-slot rounding model is not an API guarantee.
                float delta = counts[vertex] * quantizationStep + Mathf.Abs(expectedMass - 1f);
                float denominator = 1f - delta;
                float allowedL1Error = 2f * delta / denominator;
                worstAllowedL1Error = Mathf.Max(worstAllowedL1Error, allowedL1Error);
                for (int i = expectedOffset; i < expectedEnd; i++)
                {
                    BoneWeight1 expected = weights[i];
                    float observed = 0f;
                    for (int j = actualOffset; j < actualEnd; j++)
                        if (actualWeights[j].boneIndex == expected.boneIndex) observed += actualWeights[j].weight;
                    float error = Mathf.Abs(observed - expected.weight);
                    maxWeightError = Mathf.Max(maxWeightError, error);
                    l1Error += error;
                    if (observed == 0f) droppedCount++;
                }
                maxL1Error = Mathf.Max(maxL1Error, l1Error);
                if (l1Error > allowedL1Error) violatingVertex = vertex;
                for (int j = actualOffset; j < actualEnd; j++)
                {
                    bool expectedJoint = false;
                    for (int i = expectedOffset; i < expectedEnd; i++)
                        if (weights[i].boneIndex == actualWeights[j].boneIndex) { expectedJoint = true; break; }
                    if (!expectedJoint) unexpectedJointCount++;
                }
                expectedOffset = expectedEnd; actualOffset = actualEnd;
            }
            Debug.Log("MOCAP_SKIN_READBACK_METRICS " + spec.labSid + " maxWeightError=" + maxWeightError.ToString("G9") + " maxLostMass=" + maxLostMass.ToString("G9") + " maxL1Error=" + maxL1Error.ToString("G9") + " worstAllowedL1Error=" + worstAllowedL1Error.ToString("G9") + " dropped=" + droppedCount + " unexpectedJoints=" + unexpectedJointCount);
            if (violatingVertex >= 0 || unexpectedJointCount != 0)
                throw new InvalidOperationException(spec.labSid + " Unity materially changed source skin influences at vertex " + violatingVertex + "; maxWeightError=" + maxWeightError.ToString("G9") + " maxLostMass=" + maxLostMass.ToString("G9") + " maxL1Error=" + maxL1Error.ToString("G9") + " dropped=" + droppedCount + " unexpectedJoints=" + unexpectedJointCount);
        }
        string path = assetRoot + "/owned_mocap_mesh.asset";
        if (AssetDatabase.LoadAssetAtPath<Mesh>(path) != null)
            AssetDatabase.DeleteAsset(path);
        AssetDatabase.CreateAsset(owned, path);
        renderer.sharedMesh = owned;
        renderer.quality = SkinQuality.Auto;
        var marker = new GameObject(UnlimitedSkinMarkerName);
        marker.transform.SetParent(instance.transform, false);
        Debug.Log("MOCAP_SKIN_READBACK " + spec.labSid + " vertices=" + n + " influences=" + weights.Count + " max=" + counts.Max());
    }

    private static Mesh RebuildMeshWithCompatibleSkinLayout(Mesh source)
    {
        Mesh copy = new Mesh { name = source.name + "_compatible_skin" };
        copy.indexFormat = source.indexFormat;
        copy.vertices = source.vertices;
        if (source.normals.Length == source.vertexCount) copy.normals = source.normals;
        if (source.tangents.Length == source.vertexCount) copy.tangents = source.tangents;
        if (source.HasVertexAttribute(VertexAttribute.Color))
        {
            if (source.GetVertexAttributeFormat(VertexAttribute.Color) == VertexAttributeFormat.UNorm8)
                copy.colors32 = source.colors32;
            else
                copy.colors = source.colors;
        }
        for (int channel = 0; channel < 8; channel++)
        {
            var values = new List<Vector4>();
            source.GetUVs(channel, values);
            if (values.Count == source.vertexCount) copy.SetUVs(channel, values);
        }
        copy.subMeshCount = source.subMeshCount;
        for (int submesh = 0; submesh < source.subMeshCount; submesh++)
        {
            SubMeshDescriptor descriptor = source.GetSubMesh(submesh);
            copy.SetIndices(source.GetIndices(submesh, false), descriptor.topology, submesh, false, descriptor.baseVertex);
        }
        copy.bindposes = source.bindposes;
        copy.bounds = source.bounds;
        Vector3[] deltaVertices = new Vector3[source.vertexCount];
        Vector3[] deltaNormals = new Vector3[source.vertexCount];
        Vector3[] deltaTangents = new Vector3[source.vertexCount];
        for (int shape = 0; shape < source.blendShapeCount; shape++)
        {
            string shapeName = source.GetBlendShapeName(shape);
            for (int frame = 0; frame < source.GetBlendShapeFrameCount(shape); frame++)
            {
                float weight = source.GetBlendShapeFrameWeight(shape, frame);
                source.GetBlendShapeFrameVertices(shape, frame, deltaVertices, deltaNormals, deltaTangents);
                copy.AddBlendShapeFrame(shapeName, weight, deltaVertices, deltaNormals, deltaTangents);
            }
        }
        return copy;
    }

    private static string ContractSuffix(string contractName, string prefix)
    {
        string head = prefix + "_";
        if (contractName.StartsWith(head, StringComparison.Ordinal))
            return contractName.Substring(head.Length);
        int idx = contractName.IndexOf('_');
        return idx < 0 ? contractName : contractName.Substring(idx + 1);
    }

    private static Dictionary<string, string> StockMap(string prefix, bool idleOnly, HashSet<string> present)
    {
        string idle = prefix + "_Idle";
        string Named(string suffix)
        {
            string name = prefix + "_" + suffix;
            if (idleOnly)
                return idle;
            if (present.Contains(name))
                return name;
            if (suffix == "AttackFront" && present.Contains(prefix + "_ShootFront"))
                return prefix + "_ShootFront";
            if ((suffix == "MoveStart" || suffix == "MoveEnd") && present.Contains(prefix + "_Move"))
                return prefix + "_Move";
            if (suffix == "Mouseover" && present.Contains(idle))
                return idle;
            if (!present.Contains(name) && present.Contains(idle))
                throw new InvalidOperationException("missing required clip " + name);
            return name;
        }
        return new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "01.Walk", Named("Move") },
            { "02.Walk_ability", Named("MoveStart") },
            { "03.Walk_ability_Attack", Named("AttackFront") },
            { "04.Fly", Named("Move") },
            { "05.Fly_Start", Named("MoveStart") },
            { "06.Fly_End", Named("MoveEnd") },
            { "07.Fly_Ability", Named("Move") },
            { "08.Fly_Ability_Start", Named("MoveStart") },
            { "09.Fly_Ability_End", Named("MoveEnd") },
            { "10.Tp_Start", Named("MoveStart") },
            { "11.Tp_End", Named("MoveEnd") },
            { "12.Tp_Ability_Start", Named("MoveStart") },
            { "13.Tp_Ability_End", Named("MoveEnd") },
            // Native UnitDrawer.OnStartAttack sets attackVariant = {0,.2,.4,.6,.8,1}[animationIndex] on
            // "Attack Tree 2" (14.Attack, 15.Skill_1..19.Skill_5). Owned views follow the vanilla shooter
            // convention (crossbowman, lightweaver, aqualotl): melee/counter on index 0, the shot on index 1.
            // A unit without a shot clip gets its swing on 1 so an index-1 ability never plays Mouseover;
            // validate_homm3_owned_skinned_attack_clip_contract.py fails a projectile slot that lands on a swing.
            { "14.Attack", Named("AttackFront") },
            { "15.Skill_1", present.Contains(prefix + "_ShootFront") && !idleOnly ? prefix + "_ShootFront" : Named("AttackFront") },
            { "16.Skill_2", Named("Mouseover") },
            { "17.Skill_3", Named("Mouseover") },
            { "18.Skill_4", Named("Mouseover") },
            { "19.Skill_5", Named("Mouseover") },
            { "20.Damage", Named("Hitted") },
            { "21.Death", Named("Death") },
            { "22.Idle", Named("Idle") },
            { "23.Idle_Rare", Named("Idle") },
            { "24.Stance_In", Named("MoveStart") },
            { "25.Stance", Named("Defence") },
            { "26.Stance_Out", Named("MoveEnd") },
            { "27.Victory", Named("Defence") },
        };
    }

    private static void ApplyStockContractOverrides(
        AnimatorOverrideController overrides,
        List<AnimationClip> importedClips,
        string prefix,
        bool idleOnly,
        string labSid)
    {
        var replacements = importedClips.ToDictionary(c => c.name, StringComparer.Ordinal);
        var stockToOwned = StockMap(prefix, idleOnly, new HashSet<string>(replacements.Keys, StringComparer.Ordinal));
        var pairs = new List<KeyValuePair<AnimationClip, AnimationClip>>();
        overrides.GetOverrides(pairs);
        var applied = new List<string>();
        for (int i = 0; i < pairs.Count; i++)
        {
            var pair = pairs[i];
            if (pair.Key == null || !stockToOwned.TryGetValue(pair.Key.name, out string ownedName))
                throw new InvalidOperationException(labSid + " unmapped stock clip: " + (pair.Key == null ? "<null>" : pair.Key.name));
            if (!replacements.TryGetValue(ownedName, out AnimationClip replacement))
                throw new InvalidOperationException(labSid + " missing owned clip " + ownedName);
            pairs[i] = new KeyValuePair<AnimationClip, AnimationClip>(pair.Key, replacement);
            applied.Add(pair.Key.name + " -> " + replacement.name);
        }
        overrides.ApplyOverrides(pairs);
    }

    private static Material BuildRuntimeCompatibleMaterial(
        Material sourceMaterial,
        string materialPath,
        string albedoPath,
        string normalPath,
        string metallicPath)
    {
        Material stock = AssetDatabase.LoadAssetAtPath<Material>(EtalonMaterial);
        if (stock == null || stock.shader == null)
            throw new InvalidOperationException("Stock Etalon material/shader is missing.");
        if (AssetDatabase.LoadAssetAtPath<Material>(materialPath) != null)
            AssetDatabase.DeleteAsset(materialPath);
        Material material = new Material(stock) { name = "owned_skinned" };
        Texture albedo = AssetDatabase.LoadAssetAtPath<Texture>(albedoPath);
        Texture normal = AssetDatabase.LoadAssetAtPath<Texture>(normalPath);
        Texture metallicGloss = AssetDatabase.LoadAssetAtPath<Texture>(metallicPath);
        if (albedo == null || normal == null || metallicGloss == null)
            throw new InvalidOperationException("skinned PBR textures failed to import");
        // This material is a carrier, not the final material. The stock Etalon shader exposes
        // no _BumpMap/_MetallicGlossMap/_Smoothness slots, so setting them here silently
        // no-ops (observed: normal/metallic maps never bound, metallic=1/smoothness=0 shipped
        // and rendered as dull clay). Albedo is bound here; the runtime owned-skinned Hex/Lit
        // rebind (Homm3ImportVisuals.ApplyOwnedSkinnedHexLitPbr) owns the normal and
        // metallic-gloss stamp, loading the textures by path from the bundle, where they ride
        // as explicit root assets (BuildCustomUnitBundles.AddSkinnedBattleAssets).
        if (material.HasProperty("_MainTex"))
            material.SetTexture("_MainTex", albedo);
        if (material.HasProperty("_BaseMap"))
            material.SetTexture("_BaseMap", albedo);
        if (material.HasProperty("_Cull"))
            material.SetFloat("_Cull", 0f);
        if (material.HasProperty("_AlphaClipEnabled"))
            material.SetFloat("_AlphaClipEnabled", 0f);
        if (sourceMaterial != null && sourceMaterial.HasProperty("_Color") && material.HasProperty("_Color"))
            material.SetColor("_Color", sourceMaterial.GetColor("_Color"));
        AssetDatabase.CreateAsset(material, materialPath);
        AssetDatabase.SaveAssets();
        string yaml = File.ReadAllText(ToAbsolute(materialPath));
        string rewritten = yaml.Replace("m_Shader: {fileID: 0}", "m_Shader: {fileID: 4800000, guid: " + RuntimeShaderGuid + ", type: 3}");
        if (!rewritten.Contains(RuntimeShaderGuid))
            throw new InvalidOperationException(materialPath + ": shader GUID rewrite found no 'm_Shader: {fileID: 0}' anchor.");
        yaml = rewritten;
        yaml = BindSerializedTexture(yaml, "_MainTex", albedoPath);
        File.WriteAllText(ToAbsolute(materialPath), yaml);
        AssetDatabase.ImportAsset(materialPath, ImportAssetOptions.ForceSynchronousImport);
        return AssetDatabase.LoadAssetAtPath<Material>(materialPath);
    }

    private static string BindSerializedTexture(string yaml, string propertyName, string assetPath)
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
                break;
            }
        }
        if (!bound)
            throw new InvalidOperationException("material YAML has no " + propertyName + " texture slot to bind " + assetPath);
        return string.Join("\n", lines);
    }

    private static void ConfigureDeliveryTexture(string assetPath, bool sRGB, bool normalMap)
    {
        TextureImporter importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
        if (importer == null)
            throw new InvalidOperationException("Missing TextureImporter for " + assetPath);
        TextureImporterType type = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
        if (importer.textureType == type && importer.sRGBTexture == sRGB && importer.mipmapEnabled
            && importer.maxTextureSize == 4096 && importer.textureCompression == TextureImporterCompression.Compressed
            && importer.filterMode == FilterMode.Bilinear && importer.wrapMode == TextureWrapMode.Clamp)
            return; // already imported with the delivery settings: SaveAndReimport would import it a second time
        importer.textureType = type;
        importer.sRGBTexture = sRGB;
        importer.mipmapEnabled = true;
        importer.maxTextureSize = 4096;
        importer.textureCompression = TextureImporterCompression.Compressed;
        importer.filterMode = FilterMode.Bilinear;
        importer.wrapMode = TextureWrapMode.Clamp;
        importer.SaveAndReimport();
    }

    private static bool IsLocalRotationProperty(string propertyName)
    {
        if (string.IsNullOrEmpty(propertyName))
            return false;
        if (propertyName.IndexOf("Euler", StringComparison.OrdinalIgnoreCase) >= 0)
            return false;
        return propertyName.StartsWith("m_LocalRotation", StringComparison.Ordinal)
            || propertyName.StartsWith("localRotation", StringComparison.Ordinal);
    }

    private static void RebaseClipPaths(AnimationClip target, AnimationClip source, string labSid, bool fixedMocap, Transform masterRoot)
    {
        EditorCurveBinding[] allBindings = AnimationUtility.GetCurveBindings(source);
        // Mocap owns local translations as well as rotations. Silently dropping them
        // changes calibrated motion; legacy cascade exports remain rotation-only.
        if (fixedMocap && allBindings.Any(b => !IsLocalTransformProperty(b.propertyName)))
            throw new InvalidOperationException(labSid + " mocap clip contains unsupported curve properties: " + source.name);
        EditorCurveBinding[] bindings = allBindings
            .Where(b => fixedMocap || IsLocalRotationProperty(b.propertyName)).ToArray();
        if (bindings.Length == 0)
            throw new InvalidOperationException(labSid + " clip has no localRotation curves: " + source.name);
        string sharedRoot = FindSharedRootSegment(bindings.Select(b => b.path).ToArray());
        if (string.IsNullOrEmpty(sharedRoot))
            throw new InvalidOperationException(labSid + " clip bindings do not share a leading root: " + source.name);
        foreach (EditorCurveBinding b in bindings)
        {
            AnimationCurve curve = AnimationUtility.GetEditorCurve(source, b);
            string path = fixedMocap ? RebasePath(b.path, sharedRoot) : ResolveExistingBindingPath(b.path, masterRoot);
            if (b.type != typeof(Transform) || string.IsNullOrEmpty(path) || masterRoot.Find(path) == null)
                throw new InvalidOperationException(labSid + " clip binding does not resolve to a child transform: " + path);
            AnimationUtility.SetEditorCurve(target, path, b.type, b.propertyName, curve);
        }
    }

    private static bool IsLocalTransformProperty(string name)
    {
        return IsLocalRotationProperty(name) || name.StartsWith("m_LocalPosition.", StringComparison.Ordinal)
            || name.StartsWith("localPosition.", StringComparison.Ordinal)
            || name.StartsWith("m_LocalScale.", StringComparison.Ordinal)
            || name.StartsWith("localScale.", StringComparison.Ordinal);
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
        throw new InvalidOperationException("clip binding path is not under '" + sharedRoot + "': " + path);
    }

    private static string ResolveExistingBindingPath(string path, Transform masterRoot)
    {
        if (string.IsNullOrEmpty(path))
            throw new InvalidOperationException("clip binding path is empty");
        if (masterRoot.Find(path) != null)
            return path;
        string current = path;
        while (true)
        {
            int slash = current.IndexOf('/');
            if (slash < 0)
                break;
            current = current.Substring(slash + 1);
            if (masterRoot.Find(current) != null)
                return current;
        }
        string nested = FindNestedBindingPath(path, masterRoot);
        if (!string.IsNullOrEmpty(nested))
            return nested;
        throw new InvalidOperationException("clip binding does not resolve under the owned prefab: " + path);
    }

    private static string FindNestedBindingPath(string path, Transform masterRoot)
    {
        // Remaining-idle0 masters wrap the bind under MocapDeliveryRoot/Orientation.
        // Clip GLBs stay unwrapped, so Unity bindings are still "mixamorig:Hips".
        string found = null;
        foreach (Transform child in masterRoot.GetComponentsInChildren<Transform>(true))
        {
            if (child == masterRoot)
                continue;
            string relative = RelativeTransformPath(masterRoot, child);
            if (relative != path && !relative.EndsWith("/" + path, StringComparison.Ordinal))
                continue;
            if (found != null && found != relative)
                throw new InvalidOperationException("clip binding matches more than one nested transform: " + path);
            found = relative;
        }
        return found;
    }

    private static string RelativeTransformPath(Transform root, Transform child)
    {
        var parts = new List<string>();
        Transform current = child;
        while (current != null && current != root)
        {
            parts.Add(current.name);
            current = current.parent;
        }
        if (current != root)
            throw new InvalidOperationException("transform is not under master root: " + child.name);
        parts.Reverse();
        return string.Join("/", parts);
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

    private static void EnsureClipHasPositiveLength(AnimationClip clip, string labSid)
    {
        if (clip.length > 0f)
            return;
        float frame = 1f / Mathf.Max(clip.frameRate, 1f);
        bool any = false;
        foreach (EditorCurveBinding binding in AnimationUtility.GetCurveBindings(clip))
        {
            AnimationCurve curve = AnimationUtility.GetEditorCurve(clip, binding);
            if (curve == null || curve.length < 1)
                continue;
            any = true;
            Keyframe[] keys = curve.keys;
            if (keys[keys.Length - 1].time <= 0f)
            {
                Keyframe last = keys[keys.Length - 1];
                last.time = frame;
                keys[keys.Length - 1] = last;
                curve.keys = keys;
                AnimationUtility.SetEditorCurve(clip, binding, curve);
            }
        }
        if (!any || clip.length <= 0f)
            throw new InvalidOperationException(labSid + " zero-length clip " + clip.name);
    }

    private static void ApplyLoopSetting(AnimationClip clip, bool loop)
    {
        AnimationClipSettings settings = AnimationUtility.GetAnimationClipSettings(clip);
        settings.loopTime = loop;
        AnimationUtility.SetAnimationClipSettings(clip, settings);
    }

    private static void ClearTempAssets(string tempRoot)
    {
        if (!Directory.Exists(ToAbsolute(tempRoot)))
            return;
        foreach (string file in Directory.GetFiles(ToAbsolute(tempRoot), "*.glb", SearchOption.TopDirectoryOnly))
        {
            string assetPath = file.Replace('\\', '/');
            int assetsIndex = assetPath.IndexOf("/Assets/", StringComparison.OrdinalIgnoreCase);
            if (assetsIndex >= 0)
                assetPath = assetPath.Substring(assetsIndex + 1);
            AssetDatabase.DeleteAsset(assetPath);
        }
    }

    private static void CopyExactFile(string source, string destination)
    {
        if (!File.Exists(source))
            throw new FileNotFoundException("Required skinned delivery input is missing.", source);
        long expected = new FileInfo(source).Length;
        if (File.Exists(destination))
            File.Delete(destination);
        File.Copy(source, destination, true);
        long actual = new FileInfo(destination).Length;
        if (actual != expected)
            throw new InvalidOperationException(
                "copied file size mismatch: " + destination + " wrote " + actual + " expected " + expected);
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
        if (string.IsNullOrEmpty(path) || !File.Exists(path))
            throw new FileNotFoundException("Required skinned delivery input is missing.", path);
    }
}
