// CODEX_GENERATED_UNIT_VFX_PREVIEW: managed by preview_unit_vfx.py.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace OldenEra.Homm3Import
{
    public static class UnitVfxPreview
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

        private const int PreviewLayer = 31;

        [Serializable]
        private sealed class PreviewSpec
        {
            public string schema;
            public string unitSid;
            public string prefabAssetPath;
            public string clipAssetPath;
            public string anchorName;
            public string effectKind;
            public string effectPrefabAssetPath;
            public string candidateStatus;
            public string effectSourceNote;
            public float durationSeconds;
            public float effectDurationSeconds;
            public float[] eventTimesSeconds;
            public float[] anchorLocalOffset;
            public float[] anchorViewOffsetRelativeToHeight;
            public bool loopClip;
            public bool requireSkinnedMeshDeformation;
            public float effectBoundsMarginRelativeToHeight;
            public float meshDeformationThresholdRelativeToHeight;
            public float minimumShapeRmsRelativeToHeight;
            public float arcLengthRelativeToHeight;
            public float arcWidthRelativeToHeight;
            public float arcLightIntensity;
            public float arcLightRangeRelativeToHeight;
            public int branchCount;
            public int seed;
            public int fps;
            public int width;
            public int height;
            public float[] cameraDirection;
            public float orthographicPadding;
        }

        [Serializable]
        private sealed class PreviewReport
        {
            public string schema = "unit_vfx_preview_report.v1";
            public string proof = "unity-editor-camera-render";
            public bool gameRuntimeUsed;
            public bool loopClip;
            public string unitSid;
            public string prefabAssetPath;
            public string clipAssetPath;
            public string effectKind;
            public string effectAnchor;
            public float effectBoundsMarginRelativeToHeight;
            public string candidateStatus;
            public string effectSourceNote;
            public float clipLengthSeconds;
            public float durationSeconds;
            public int fps;
            public int frameCount;
            public string[] eventTimesSeconds;
            public int[] eventVisibilityChangedPixels;
            public int[] eventMeshLightingChangedPixels;
            public int[] eventMeshBrightenedPixels;
            public int[] eventMeshSurfacePixels;
            public string meshLightingPass;
            public string meshDeformationPass;
            public int skinnedVertexCount;
            public int activeSkinnedRendererCount;
            public string[] activeSkinnedRendererPaths;
            public int meshDistanceProbeCount;
            public float meshModelHeight;
            public string meshDeformationNormalization;
            public float meshDeformationThreshold;
            public float meshMinimumShapeRms;
            public List<FrameReport> frames = new List<FrameReport>();
        }

        [Serializable]
        private sealed class FrameReport
        {
            public int index;
            public float timeSeconds;
            public bool effectActive;
            public int baselineVisiblePixels;
            public int effectVisiblePixels;
            public int effectChangedPixels;
            public int meshShapeChangedVerticesFromStart;
            public int meshShapeChangedVerticesFromPrevious;
            public float meshRmsDistanceSignatureDeltaFromStart;
            public float meshRmsDistanceSignatureDeltaFromPrevious;
            public float meshMaxPerVertexDistanceSignatureDeltaFromStart;
            public float meshMaxPerVertexDistanceSignatureDeltaFromPrevious;
        }

        private sealed class ArcEvent
        {
            public float start;
            public float end;
            public Transform anchor;
            public LineRenderer glow;
            public LineRenderer core;
            public LineRenderer[] branches;
            public Light emissionLight;
            public float lightIntensity;
            public Vector3 lightCameraOffset;
            public Vector3 startLocalOffset;
            public Vector3 startViewWorldOffset;
            public Vector3[][] mainViewPoses;
            public Vector3[][][] branchViewPoses;
        }

        private sealed class ParticleEvent
        {
            public float start;
            public float end;
            public GameObject instance;
            public ParticleSystem[] systems;
            public ParticleSystem[] roots;
            public uint seed;
        }

        public static void RenderFromBatch()
        {
            string specPath = Argument("-unitVfxPreviewSpec");
            string outputDirectory = Argument("-unitVfxPreviewOut");
            if (string.IsNullOrWhiteSpace(specPath) || string.IsNullOrWhiteSpace(outputDirectory))
                throw new InvalidOperationException("UnitVfxPreview requires -unitVfxPreviewSpec and -unitVfxPreviewOut");

            PreviewSpec spec = JsonUtility.FromJson<PreviewSpec>(File.ReadAllText(specPath));
            Validate(spec);
            ValidateShapeMotionHelpers();
            string outDir = Path.GetFullPath(outputDirectory);
            if (File.Exists(Path.Combine(outDir, "preview_report.json"))
                || Directory.Exists(Path.Combine(outDir, "baseline"))
                || Directory.Exists(Path.Combine(outDir, "effect")))
                throw new InvalidOperationException("Preview output already contains rendered results: " + outDir);
            Directory.CreateDirectory(outDir);

            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(spec.prefabAssetPath);
            AnimationClip clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(spec.clipAssetPath);
            if (prefab == null)
                throw new InvalidOperationException("Unit prefab did not load: " + spec.prefabAssetPath);
            if (clip == null || clip.length <= 0f)
                throw new InvalidOperationException("Animation clip did not load or has no duration: " + spec.clipAssetPath);

            GameObject instance = null;
            GameObject cameraObject = null;
            RenderTexture renderTarget = null;
            Texture2D readback = null;
            Material arcMaterial = null;
            List<Material> previewMaterials = new List<Material>();
            Mesh[] bakedMeshes = null;
            RenderTexture previousTarget = RenderTexture.active;
            try
            {
                instance = UnityEngine.Object.Instantiate(prefab);
                instance.name = "UnitVfxPreview_" + spec.unitSid;
                instance.transform.position = Vector3.zero;
                instance.transform.rotation = Quaternion.identity;
                instance.SetActive(true);
                SetLayerRecursively(instance.transform, PreviewLayer);
                foreach (Animator animator in instance.GetComponentsInChildren<Animator>(true))
                    animator.enabled = false;

                Renderer[] renderers = instance.GetComponentsInChildren<Renderer>(true)
                    .Where(IsActiveRenderer).ToArray();
                if (renderers.Length == 0)
                    throw new InvalidOperationException("Unit prefab has no enabled renderers");
                SkinnedMeshRenderer[] skinnedRenderers = spec.requireSkinnedMeshDeformation
                    ? renderers.OfType<SkinnedMeshRenderer>()
                        .Where(x => x.sharedMesh != null && x.sharedMesh.vertexCount >= 4).ToArray()
                    : new SkinnedMeshRenderer[0];
                if (spec.requireSkinnedMeshDeformation && skinnedRenderers.Length == 0)
                    throw new InvalidOperationException("Skinned mesh deformation was required, but the unit has no enabled SkinnedMeshRenderer");
                bakedMeshes = skinnedRenderers.Select(_ => new Mesh { hideFlags = HideFlags.HideAndDontSave }).ToArray();
                if (spec.effectKind == "electricArc")
                    previewMaterials = ApplyLitPreviewMaterials(renderers);

                Transform anchor = FindUniqueTransform(instance.transform, spec.anchorName);
                GameObject particlePrefab = null;
                if (spec.effectKind == "particlePrefab")
                {
                    particlePrefab = AssetDatabase.LoadAssetAtPath<GameObject>(spec.effectPrefabAssetPath);
                    if (particlePrefab == null)
                        throw new InvalidOperationException("Effect prefab did not load: " + spec.effectPrefabAssetPath);
                }
                else if (spec.effectKind != "electricArc")
                {
                    throw new InvalidOperationException("Unsupported effectKind: " + spec.effectKind);
                }

                clip.SampleAnimation(instance, 0f);
                int frameCount = Mathf.CeilToInt(spec.durationSeconds * spec.fps);
                Bounds animationBounds = CombinedBounds(renderers);
                for (int i = 1; i < frameCount; i++)
                {
                    clip.SampleAnimation(instance, ClipTime((float)i / spec.fps, spec, clip));
                    animationBounds.Encapsulate(CombinedBounds(renderers));
                }
                clip.SampleAnimation(instance, 0f);
                float modelHeight = Mathf.Max(animationBounds.size.y, 0.01f);
                Bounds cameraBounds = animationBounds;
                if (spec.effectKind == "particlePrefab")
                    cameraBounds.Expand(modelHeight * spec.effectBoundsMarginRelativeToHeight * 2f);
                Vector3 cameraDirection = Vector(spec.cameraDirection, Vector3.forward).normalized;
                if (cameraDirection.sqrMagnitude < 0.99f)
                    throw new InvalidOperationException("cameraDirection must be a non-zero 3D vector");

                cameraObject = new GameObject("UnitVfxPreviewCamera");
                Camera camera = cameraObject.AddComponent<Camera>();
                camera.enabled = false;
                camera.cullingMask = 1 << PreviewLayer;
                camera.orthographic = true;
                camera.clearFlags = CameraClearFlags.SolidColor;
                camera.backgroundColor = new Color(0f, 0f, 0f, 0f);
                camera.nearClipPlane = 0.01f;
                camera.farClipPlane = 100f;
                camera.allowHDR = true;
                camera.allowMSAA = true;
                float aspect = (float)spec.width / spec.height;
                float cameraDistance = Mathf.Max(modelHeight * 3f, cameraBounds.extents.magnitude * 2.5f);
                camera.transform.position = cameraBounds.center + cameraDirection * cameraDistance;
                camera.transform.rotation = Quaternion.LookRotation(
                    cameraBounds.center - camera.transform.position, Vector3.up);
                camera.orthographicSize = Mathf.Max(
                    ProjectedHalfExtent(cameraBounds, camera.transform.up),
                    ProjectedHalfExtent(cameraBounds, camera.transform.right) / aspect)
                    * spec.orthographicPadding;

                renderTarget = new RenderTexture(spec.width, spec.height, 24, RenderTextureFormat.ARGB32,
                    RenderTextureReadWrite.Default) { antiAliasing = 1, hideFlags = HideFlags.HideAndDontSave };
                renderTarget.Create();
                camera.targetTexture = renderTarget;
                readback = new Texture2D(spec.width, spec.height, TextureFormat.RGBA32, false)
                { hideFlags = HideFlags.HideAndDontSave };

                List<ArcEvent> arcs = new List<ArcEvent>();
                if (spec.effectKind == "electricArc")
                {
                    arcMaterial = CreateArcMaterial();
                    arcs = CreateArcs(spec, anchor, instance.transform, camera.transform, modelHeight, arcMaterial);
                    Bounds presentationBounds = animationBounds;
                    for (int i = 0; i < frameCount; i++)
                    {
                        float time = (float)i / spec.fps;
                        clip.SampleAnimation(instance, ClipTime(time, spec, clip));
                        foreach (ArcEvent arc in arcs)
                            if (time >= arc.start && time < arc.end)
                                presentationBounds = IncludeArcBounds(presentationBounds, arc);
                    }
                    clip.SampleAnimation(instance, 0f);
                    presentationBounds.Expand(modelHeight * spec.arcWidthRelativeToHeight * 2f);
                    camera.transform.position = presentationBounds.center + cameraDirection * cameraDistance;
                    camera.transform.rotation = Quaternion.LookRotation(
                        presentationBounds.center - camera.transform.position, Vector3.up);
                    camera.orthographicSize = Mathf.Max(
                        ProjectedHalfExtent(presentationBounds, camera.transform.up),
                        ProjectedHalfExtent(presentationBounds, camera.transform.right) / aspect)
                        * spec.orthographicPadding;
                }

                List<ParticleEvent> particles = new List<ParticleEvent>();
                if (spec.effectKind == "particlePrefab")
                    particles = CreateParticleEvents(spec, particlePrefab, anchor);

                PreviewReport report = new PreviewReport
                {
                    gameRuntimeUsed = false,
                    loopClip = spec.loopClip,
                    unitSid = spec.unitSid,
                    prefabAssetPath = spec.prefabAssetPath,
                    clipAssetPath = spec.clipAssetPath,
                    effectKind = spec.effectKind,
                    effectAnchor = spec.anchorName,
                    effectBoundsMarginRelativeToHeight = spec.effectBoundsMarginRelativeToHeight,
                    candidateStatus = spec.candidateStatus,
                    effectSourceNote = spec.effectSourceNote,
                    meshLightingPass = spec.effectKind == "electricArc"
                        ? "Unity Point Light on Standard preview materials; arc geometry hidden during measurement"
                        : "not applicable",
                    meshDeformationPass = spec.requireSkinnedMeshDeformation
                        ? "Active SkinnedMeshRenderer.BakeMesh(useScale:true); per-renderer renderer-local normalized pairwise-distance signatures; rigid and transform-scale motion excluded"
                        : "not requested",
                    meshDeformationNormalization = spec.requireSkinnedMeshDeformation
                        ? "each renderer's initial baked local height"
                        : "not requested",
                    activeSkinnedRendererCount = skinnedRenderers.Length,
                    activeSkinnedRendererPaths = skinnedRenderers.Select(x =>
                        AnimationUtility.CalculateTransformPath(x.transform, instance.transform)).ToArray(),
                    clipLengthSeconds = clip.length,
                    durationSeconds = spec.durationSeconds,
                    fps = spec.fps,
                    frameCount = Mathf.CeilToInt(spec.durationSeconds * spec.fps),
                    eventTimesSeconds = spec.eventTimesSeconds.Select(x => x.ToString("F6", System.Globalization.CultureInfo.InvariantCulture)).ToArray()
                };

                string baselineDir = Path.Combine(outDir, "baseline");
                string effectDir = Path.Combine(outDir, "effect");
                Directory.CreateDirectory(baselineDir);
                Directory.CreateDirectory(effectDir);
                int[] eventVisiblePixels = new int[spec.eventTimesSeconds.Length];
                int[] eventMeshLightingPixels = new int[spec.eventTimesSeconds.Length];
                int[] eventMeshBrightenedPixels = new int[spec.eventTimesSeconds.Length];
                int[] eventMeshSurfacePixels = new int[spec.eventTimesSeconds.Length];
                HashSet<int>[] eventVerificationFrames = BuildEventVerificationFrames(spec);
                Vector3[][] firstVertices = null;
                float[][] firstSignature = null;
                float[][] previousSignature = null;
                int[][] distanceProbes = null;
                float[] rendererReferenceHeights = null;
                float meshDeformationThreshold = spec.meshDeformationThresholdRelativeToHeight;
                float minimumShapeRms = spec.minimumShapeRmsRelativeToHeight;
                report.meshModelHeight = modelHeight;
                report.meshDeformationThreshold = meshDeformationThreshold;
                report.meshMinimumShapeRms = minimumShapeRms;
                for (int i = 0; i < frameCount; i++)
                {
                    float time = (float)i / spec.fps;
                    clip.SampleAnimation(instance, ClipTime(time, spec, clip));
                    int fromStart = 0;
                    float rmsFromStart = 0f;
                    float maxFromStart = 0f;
                    int fromPrevious = 0;
                    float rmsFromPrevious = 0f;
                    float maxFromPrevious = 0f;
                    if (spec.requireSkinnedMeshDeformation)
                    {
                        Vector3[][] currentVertices = CaptureSkinnedVertices(skinnedRenderers, bakedMeshes);
                        if (i == 0)
                        {
                            firstVertices = currentVertices;
                            report.skinnedVertexCount = currentVertices.Sum(x => x.Length);
                            if (report.skinnedVertexCount == 0)
                                throw new InvalidOperationException("Skinned mesh deformation was required, but BakeMesh returned no vertices");
                            distanceProbes = firstVertices.Select(x => SelectDistanceProbes(x, 64)).ToArray();
                            rendererReferenceHeights = firstVertices.Select(MeasureRendererLocalHeight).ToArray();
                            report.meshDistanceProbeCount = distanceProbes.Sum(x => x.Length);
                            firstSignature = firstVertices.Select((vertices, index) =>
                                NormalizeDistanceSignature(
                                    BuildDistanceSignature(vertices, distanceProbes[index]),
                                    rendererReferenceHeights[index])).ToArray();
                        }
                        float[][] currentSignature = currentVertices.Select((vertices, index) =>
                            NormalizeDistanceSignature(
                                BuildDistanceSignature(vertices, distanceProbes[index]),
                                rendererReferenceHeights[index])).ToArray();
                        int[] rendererVertexCounts = currentVertices.Select(x => x.Length).ToArray();
                        int[] rendererProbeCounts = distanceProbes.Select(x => x.Length).ToArray();
                        MeasureShapeMotion(firstSignature, currentSignature, rendererVertexCounts,
                            rendererProbeCounts, meshDeformationThreshold,
                            out fromStart, out rmsFromStart, out maxFromStart);
                        MeasureShapeMotion(previousSignature ?? currentSignature, currentSignature,
                            rendererVertexCounts, rendererProbeCounts, meshDeformationThreshold,
                            out fromPrevious, out rmsFromPrevious, out maxFromPrevious);
                        previousSignature = currentSignature;
                    }
                    string file = "frame_" + i.ToString("D4") + ".png";
                    foreach (ArcEvent arc in arcs) SetArcInactive(arc);
                    foreach (ParticleEvent particle in particles) particle.instance.SetActive(false);
                    int baselinePixels = RenderFrame(camera, renderTarget, readback, Path.Combine(baselineDir, file));
                    Color32[] baselineImage = readback.GetPixels32();

                    for (int eventIndex = 0; eventIndex < eventVisiblePixels.Length; eventIndex++)
                    {
                        if ((eventVisiblePixels[eventIndex] >= 4
                                && (spec.effectKind != "electricArc"
                                    || eventMeshBrightenedPixels[eventIndex]
                                        >= MeshLightingRequiredPixels(eventMeshSurfacePixels[eventIndex])))
                            || !eventVerificationFrames[eventIndex].Contains(i))
                            continue;
                        foreach (ArcEvent arc in arcs) SetArcInactive(arc);
                        foreach (ParticleEvent particle in particles) particle.instance.SetActive(false);
                        if (spec.effectKind == "electricArc")
                        {
                            if (eventVisiblePixels[eventIndex] < 4)
                            {
                                SetArcGeometryAtTime(arcs[eventIndex], time);
                                RenderFrame(camera, renderTarget, readback, null);
                                eventVisiblePixels[eventIndex] = Mathf.Max(eventVisiblePixels[eventIndex],
                                    CountChangedPixels(baselineImage, readback.GetPixels32()));
                            }
                            if (eventMeshBrightenedPixels[eventIndex]
                                < MeshLightingRequiredPixels(eventMeshSurfacePixels[eventIndex]))
                            {
                                SetArcGeometryInactive(arcs[eventIndex]);
                                SetArcLightAtTime(arcs[eventIndex], time);
                                RenderFrame(camera, renderTarget, readback, null);
                                int brightened;
                                eventMeshSurfacePixels[eventIndex] = Mathf.Max(
                                    eventMeshSurfacePixels[eventIndex], baselinePixels);
                                eventMeshLightingPixels[eventIndex] = Mathf.Max(eventMeshLightingPixels[eventIndex],
                                    CountMeshLightingChanges(baselineImage, readback.GetPixels32(), out brightened));
                                eventMeshBrightenedPixels[eventIndex] = Mathf.Max(
                                    eventMeshBrightenedPixels[eventIndex], brightened);
                            }
                        }
                        else
                        {
                            SimulateParticleAtTime(particles[eventIndex], time);
                            RenderFrame(camera, renderTarget, readback, null);
                            eventVisiblePixels[eventIndex] = Mathf.Max(eventVisiblePixels[eventIndex],
                                CountChangedPixels(baselineImage, readback.GetPixels32()));
                        }
                    }

                    foreach (ArcEvent arc in arcs) SetArcInactive(arc);
                    foreach (ParticleEvent particle in particles) particle.instance.SetActive(false);
                    foreach (ArcEvent arc in arcs)
                        SetArcAtTime(arc, time);
                    foreach (ParticleEvent particle in particles)
                        SimulateParticleAtTime(particle, time);
                    int effectPixels = RenderFrame(camera, renderTarget, readback, Path.Combine(effectDir, file));
                    int changedPixels = CountChangedPixels(baselineImage, readback.GetPixels32());
                    bool effectActive = IsEffectActive(spec, time);
                    report.frames.Add(new FrameReport
                    {
                        index = i,
                        timeSeconds = time,
                        effectActive = effectActive,
                        baselineVisiblePixels = baselinePixels,
                        effectVisiblePixels = effectPixels,
                        effectChangedPixels = changedPixels,
                        meshShapeChangedVerticesFromStart = fromStart,
                        meshShapeChangedVerticesFromPrevious = fromPrevious,
                        meshRmsDistanceSignatureDeltaFromStart = rmsFromStart,
                        meshRmsDistanceSignatureDeltaFromPrevious = rmsFromPrevious,
                        meshMaxPerVertexDistanceSignatureDeltaFromStart = maxFromStart,
                        meshMaxPerVertexDistanceSignatureDeltaFromPrevious = maxFromPrevious
                    });
                }

                if (spec.requireSkinnedMeshDeformation)
                {
                    int requiredVertices = Mathf.Max(16, Mathf.CeilToInt(report.skinnedVertexCount * 0.05f));
                    int animatedFrames = report.frames.Count(frame => frame.meshShapeChangedVerticesFromPrevious >= requiredVertices
                        && frame.meshRmsDistanceSignatureDeltaFromPrevious >= minimumShapeRms);
                    if (animatedFrames < 3)
                        throw new InvalidOperationException("Skinned Beholder mesh did not deform across at least three sampled attack transitions; "
                            + "required " + requiredVertices + " vertices above " + meshDeformationThreshold
                            + " per-vertex shape delta and RMS " + minimumShapeRms + ", observed "
                            + animatedFrames + " qualifying transitions");
                }

                for (int i = 0; i < eventVisiblePixels.Length; i++)
                {
                    if (eventVisiblePixels[i] < 4)
                        throw new InvalidOperationException("Scheduled effect produced no visible change for event " + i);
                    if (spec.effectKind == "electricArc" && eventMeshBrightenedPixels[i]
                        < MeshLightingRequiredPixels(eventMeshSurfacePixels[i]))
                        throw new InvalidOperationException("Scheduled electricity did not brighten the unit mesh for event " + i);
                }
                report.eventVisibilityChangedPixels = eventVisiblePixels;
                report.eventMeshLightingChangedPixels = eventMeshLightingPixels;
                report.eventMeshBrightenedPixels = eventMeshBrightenedPixels;
                report.eventMeshSurfacePixels = eventMeshSurfacePixels;

                File.WriteAllText(Path.Combine(outDir, "preview_report.json"), JsonUtility.ToJson(report, true) + "\n");
                Debug.Log("UNIT_VFX_PREVIEW_OK " + Path.Combine(outDir, "preview_report.json"));
            }
            catch (Exception ex)
            {
                File.WriteAllText(Path.Combine(outDir, "preview_error.txt"), ex.ToString());
                Debug.LogException(ex);
                throw;
            }
            finally
            {
                if (readback != null) UnityEngine.Object.DestroyImmediate(readback);
                if (renderTarget != null)
                {
                    renderTarget.Release();
                    UnityEngine.Object.DestroyImmediate(renderTarget);
                }
                RenderTexture.active = previousTarget;
                if (cameraObject != null) UnityEngine.Object.DestroyImmediate(cameraObject);
                if (instance != null) UnityEngine.Object.DestroyImmediate(instance);
                if (bakedMeshes != null)
                    foreach (Mesh mesh in bakedMeshes)
                        if (mesh != null) UnityEngine.Object.DestroyImmediate(mesh);
                foreach (Material material in previewMaterials)
                    if (material != null) UnityEngine.Object.DestroyImmediate(material);
                if (arcMaterial != null) UnityEngine.Object.DestroyImmediate(arcMaterial);
            }
        }

        private static void Validate(PreviewSpec spec)
        {
            if (spec == null || spec.schema != "unit_vfx_preview.v1")
                throw new InvalidOperationException("Expected unit_vfx_preview.v1 spec");
            if (string.IsNullOrWhiteSpace(spec.unitSid) || string.IsNullOrWhiteSpace(spec.prefabAssetPath)
                || string.IsNullOrWhiteSpace(spec.clipAssetPath) || string.IsNullOrWhiteSpace(spec.anchorName))
                throw new InvalidOperationException("Unit, prefab, clip, and anchor are required");
            if (spec.unitSid == "h3_beholder" && !spec.requireSkinnedMeshDeformation)
                throw new InvalidOperationException("Beholder preview requires baked skinned-mesh deformation proof");
            if (spec.effectKind != "electricArc" && spec.effectKind != "particlePrefab")
                throw new InvalidOperationException("effectKind must be electricArc or particlePrefab");
            if (spec.fps < 1 || spec.fps > 60 || spec.width < 128 || spec.width > 2048
                || spec.height < 128 || spec.height > 2048)
                throw new InvalidOperationException("Preview fps or dimensions are outside supported limits");
            if (spec.durationSeconds <= 0f || spec.durationSeconds > 20f
                || Mathf.CeilToInt(spec.durationSeconds * spec.fps) > 1200)
                throw new InvalidOperationException("Preview duration exceeds supported limits");
            if (spec.eventTimesSeconds == null || spec.eventTimesSeconds.Length == 0
                || spec.effectDurationSeconds <= 0f || spec.effectDurationSeconds > 5f)
                throw new InvalidOperationException("At least one bounded effect event is required");
            if (spec.eventTimesSeconds.Length > 32)
                throw new InvalidOperationException("A preview supports at most 32 scheduled effects");
            if (spec.requireSkinnedMeshDeformation
                && (float.IsNaN(spec.meshDeformationThresholdRelativeToHeight)
                    || float.IsInfinity(spec.meshDeformationThresholdRelativeToHeight)
                    || spec.meshDeformationThresholdRelativeToHeight < 0.005f
                    || spec.meshDeformationThresholdRelativeToHeight > 0.05f
                    || float.IsNaN(spec.minimumShapeRmsRelativeToHeight)
                    || float.IsInfinity(spec.minimumShapeRmsRelativeToHeight)
                    || spec.minimumShapeRmsRelativeToHeight < 0.002f
                    || spec.minimumShapeRmsRelativeToHeight > 0.02f))
                throw new InvalidOperationException("Skinned shape-motion thresholds are outside supported limits");
            float previousEvent = -1f;
            foreach (float eventTime in spec.eventTimesSeconds)
            {
                if (float.IsNaN(eventTime) || float.IsInfinity(eventTime)
                    || eventTime < previousEvent || eventTime < 0f
                    || eventTime + spec.effectDurationSeconds > spec.durationSeconds + 1e-5f)
                    throw new InvalidOperationException("Effect events must be finite, sorted, and inside the preview duration");
                previousEvent = eventTime;
                bool sampled = false;
                int frameCount = Mathf.CeilToInt(spec.durationSeconds * spec.fps);
                for (int i = 0; i < frameCount && !sampled; i++)
                {
                    float time = (float)i / spec.fps;
                    sampled = time >= eventTime && time < eventTime + spec.effectDurationSeconds;
                }
                if (!sampled)
                    throw new InvalidOperationException("Every effect event must overlap at least one rendered sample");
            }
            if (!(spec.orthographicPadding >= 1f && spec.orthographicPadding <= 3f))
                throw new InvalidOperationException("orthographicPadding must be between 1 and 3");
            if (spec.effectKind == "particlePrefab" && string.IsNullOrWhiteSpace(spec.effectPrefabAssetPath))
                throw new InvalidOperationException("particlePrefab effect requires effectPrefabAssetPath");
            if (spec.effectKind == "particlePrefab" && (float.IsNaN(spec.effectBoundsMarginRelativeToHeight)
                || float.IsInfinity(spec.effectBoundsMarginRelativeToHeight)
                || spec.effectBoundsMarginRelativeToHeight <= 0f
                || spec.effectBoundsMarginRelativeToHeight > 4f))
                throw new InvalidOperationException("particlePrefab requires an effect bounds margin in (0, 4]");
            if (string.IsNullOrWhiteSpace(spec.candidateStatus) || string.IsNullOrWhiteSpace(spec.effectSourceNote))
                throw new InvalidOperationException("candidateStatus and effectSourceNote are required provenance notes");
            if (spec.effectKind == "electricArc" && (float.IsNaN(spec.arcLengthRelativeToHeight)
                || float.IsInfinity(spec.arcLengthRelativeToHeight) || spec.arcLengthRelativeToHeight <= 0f
                || spec.arcLengthRelativeToHeight > 2f || float.IsNaN(spec.arcWidthRelativeToHeight)
                || float.IsInfinity(spec.arcWidthRelativeToHeight) || spec.arcWidthRelativeToHeight <= 0f
                || spec.arcWidthRelativeToHeight > 0.1f || float.IsNaN(spec.arcLightIntensity)
                || float.IsInfinity(spec.arcLightIntensity) || spec.arcLightIntensity <= 0f
                || spec.arcLightIntensity > 100f || float.IsNaN(spec.arcLightRangeRelativeToHeight)
                || float.IsInfinity(spec.arcLightRangeRelativeToHeight)
                || spec.arcLightRangeRelativeToHeight <= 0f || spec.arcLightRangeRelativeToHeight > 3f
                || spec.branchCount < 0 || spec.branchCount > 8))
                throw new InvalidOperationException("electricArc geometry or light settings are outside supported limits");
            if (spec.cameraDirection == null || spec.cameraDirection.Length != 3
                || spec.cameraDirection.Any(x => float.IsNaN(x) || float.IsInfinity(x))
                || (spec.anchorLocalOffset != null && (spec.anchorLocalOffset.Length != 3
                    || spec.anchorLocalOffset.Any(x => float.IsNaN(x) || float.IsInfinity(x))))
                || (spec.anchorViewOffsetRelativeToHeight != null
                    && (spec.anchorViewOffsetRelativeToHeight.Length != 3
                        || spec.anchorViewOffsetRelativeToHeight.Any(x => float.IsNaN(x) || float.IsInfinity(x)))))
                throw new InvalidOperationException("Camera direction and anchor offsets must be finite three-vectors");
            if (float.IsNaN(spec.durationSeconds) || float.IsInfinity(spec.durationSeconds)
                || float.IsNaN(spec.effectDurationSeconds) || float.IsInfinity(spec.effectDurationSeconds))
                throw new InvalidOperationException("Preview durations must be finite");
        }

        private static bool IsActiveRenderer(Renderer renderer)
        {
            return renderer != null && renderer.enabled && renderer.gameObject.activeInHierarchy
                && !renderer.forceRenderingOff;
        }

        private static void ValidateShapeMotionHelpers()
        {
            Vector3[] first = {
                new Vector3(-1f, 0f, 0f), new Vector3(1f, 0f, 0f),
                new Vector3(0f, 1f, 0f), new Vector3(0f, 0f, 1f)
            };
            Vector3[] second = {
                new Vector3(-0.5f, 0f, 0f), new Vector3(0.5f, 0f, 0f),
                new Vector3(0f, 0.5f, 0f), new Vector3(0f, 0f, 0.5f)
            };
            int[] firstProbes = SelectDistanceProbes(first, 64);
            int[] secondProbes = SelectDistanceProbes(second, 64);
            float[][] reference = {
                BuildDistanceSignature(first, firstProbes), BuildDistanceSignature(second, secondProbes)
            };
            Matrix4x4 rigidA = Matrix4x4.TRS(new Vector3(8f, -3f, 4f), Quaternion.Euler(17f, 89f, -23f), Vector3.one);
            Matrix4x4 rigidB = Matrix4x4.TRS(new Vector3(-11f, 5f, 2f), Quaternion.Euler(-32f, 12f, 71f), Vector3.one);
            Vector3[] movedA = first.Select(x => rigidA.MultiplyPoint3x4(x)).ToArray();
            Vector3[] movedB = second.Select(x => rigidB.MultiplyPoint3x4(x)).ToArray();
            float[][] independentlyMoved = {
                BuildDistanceSignature(movedA, firstProbes), BuildDistanceSignature(movedB, secondProbes)
            };
            MeasureShapeMotion(reference, independentlyMoved, new[] { first.Length, second.Length },
                new[] { firstProbes.Length, secondProbes.Length }, 0.005f,
                out int rigidChanged, out float rigidRms, out float rigidMaximum);
            if (rigidChanged != 0 || rigidRms > 1e-5f || rigidMaximum > 1e-5f)
                throw new InvalidOperationException("Rigid or cross-renderer movement was counted as skinned shape change");

            ValidateBakeMeshScaleInvariant();

            Vector3[] deformed = (Vector3[])first.Clone();
            deformed[3] += Vector3.forward * 0.25f;
            MeasureShapeMotion(reference.Take(1).ToArray(),
                new[] { BuildDistanceSignature(deformed, firstProbes) }, new[] { first.Length },
                new[] { firstProbes.Length }, 0.005f,
                out int deformedVertices, out float deformedRms, out float deformedMaximum);
            if (deformedVertices == 0 || deformedRms < 0.005f || deformedMaximum < 0.005f)
                throw new InvalidOperationException("Actual vertex deformation did not qualify as skinned shape change");

            GameObject active = new GameObject("UnitVfxShapeMotionActiveFilterSelfTest");
            try
            {
                Renderer renderer = active.AddComponent<MeshRenderer>();
                if (!IsActiveRenderer(renderer))
                    throw new InvalidOperationException("Active renderer failed shape-motion filter self-test");
                active.SetActive(false);
                if (IsActiveRenderer(renderer))
                    throw new InvalidOperationException("Inactive renderer passed shape-motion filter self-test");
                active.SetActive(true);
                renderer.forceRenderingOff = true;
                if (IsActiveRenderer(renderer))
                    throw new InvalidOperationException("Force-disabled renderer passed shape-motion filter self-test");
            }
            finally { UnityEngine.Object.DestroyImmediate(active); }
        }

        private static void ValidateBakeMeshScaleInvariant()
        {
            GameObject root = new GameObject("UnitVfxBakeMeshScaleSelfTest");
            Mesh source = new Mesh { hideFlags = HideFlags.HideAndDontSave };
            Mesh firstBake = new Mesh { hideFlags = HideFlags.HideAndDontSave };
            Mesh scaledBake = new Mesh { hideFlags = HideFlags.HideAndDontSave };
            try
            {
                GameObject rendererObject = new GameObject("skin");
                rendererObject.transform.SetParent(root.transform, false);
                GameObject boneObject = new GameObject("bone");
                boneObject.transform.SetParent(root.transform, false);
                SkinnedMeshRenderer renderer = rendererObject.AddComponent<SkinnedMeshRenderer>();

                source.vertices = new[] {
                    new Vector3(-1f, 0f, 0f), new Vector3(1f, 0f, 0f),
                    new Vector3(0f, 1f, 0f), new Vector3(0f, 0f, 1f)
                };
                source.triangles = new[] { 0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3 };
                source.boneWeights = Enumerable.Range(0, source.vertexCount)
                    .Select(_ => new BoneWeight { boneIndex0 = 0, weight0 = 1f }).ToArray();
                source.bindposes = new[] { boneObject.transform.worldToLocalMatrix
                    * rendererObject.transform.localToWorldMatrix };
                renderer.sharedMesh = source;
                renderer.rootBone = boneObject.transform;
                renderer.bones = new[] { boneObject.transform };

                renderer.BakeMesh(firstBake, true);
                int[] probes = SelectDistanceProbes(firstBake.vertices, 64);
                float referenceHeight = MeasureRendererLocalHeight(firstBake.vertices);
                float[] reference = NormalizeDistanceSignature(
                    BuildDistanceSignature(firstBake.vertices, probes), referenceHeight);

                root.transform.localScale = new Vector3(2f, 0.5f, 3f);
                renderer.BakeMesh(scaledBake, true);
                float[] scaled = NormalizeDistanceSignature(
                    BuildDistanceSignature(scaledBake.vertices, probes), referenceHeight);
                if (reference.Length != scaled.Length
                    || Enumerable.Range(0, reference.Length).Any(i => Mathf.Abs(reference[i] - scaled[i]) > 1e-5f))
                    throw new InvalidOperationException("Renderer transform scale was counted as skinned shape change");
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
                UnityEngine.Object.DestroyImmediate(source);
                UnityEngine.Object.DestroyImmediate(firstBake);
                UnityEngine.Object.DestroyImmediate(scaledBake);
            }
        }

        private static Vector3[][] CaptureSkinnedVertices(SkinnedMeshRenderer[] renderers, Mesh[] bakedMeshes)
        {
            if (renderers == null || bakedMeshes == null || renderers.Length != bakedMeshes.Length)
                throw new InvalidOperationException("Skinned renderer/bake mesh counts do not match");
            Vector3[][] result = new Vector3[renderers.Length][];
            for (int i = 0; i < renderers.Length; i++)
            {
                if (!IsActiveRenderer(renderers[i]) || renderers[i].sharedMesh == null)
                    throw new InvalidOperationException("Inactive or missing skinned renderer entered shape-motion proof");
                renderers[i].BakeMesh(bakedMeshes[i], true);
                Vector3[] vertices = bakedMeshes[i].vertices;
                if (vertices.Length != renderers[i].sharedMesh.vertexCount)
                    throw new InvalidOperationException("Baked skinned vertex count changed during animation sampling");
                for (int vertex = 0; vertex < vertices.Length; vertex++)
                {
                    Vector3 local = vertices[vertex];
                    if (float.IsNaN(local.x) || float.IsNaN(local.y) || float.IsNaN(local.z)
                        || float.IsInfinity(local.x) || float.IsInfinity(local.y) || float.IsInfinity(local.z))
                        throw new InvalidOperationException("Skinned mesh produced a non-finite renderer-local vertex");
                }
                result[i] = vertices;
            }
            return result;
        }

        private static int[] SelectDistanceProbes(Vector3[] vertices, int maximumProbeCount)
        {
            if (vertices == null || vertices.Length < 4 || maximumProbeCount < 4)
                throw new InvalidOperationException("Skinned shape-motion proof requires at least four vertices and probes");
            int probeCount = Mathf.Min(maximumProbeCount, vertices.Length);
            Vector3 centroid = Vector3.zero;
            foreach (Vector3 vertex in vertices)
                centroid += vertex;
            centroid /= vertices.Length;

            int firstProbe = 0;
            float farthestFromCenter = -1f;
            for (int i = 0; i < vertices.Length; i++)
            {
                float distance = (vertices[i] - centroid).sqrMagnitude;
                if (distance > farthestFromCenter)
                {
                    firstProbe = i;
                    farthestFromCenter = distance;
                }
            }

            int[] probes = new int[probeCount];
            bool[] selected = new bool[vertices.Length];
            float[] nearestDistanceSquared = Enumerable.Repeat(float.PositiveInfinity, vertices.Length).ToArray();
            int currentProbe = firstProbe;
            for (int probe = 0; probe < probeCount; probe++)
            {
                probes[probe] = currentProbe;
                selected[currentProbe] = true;
                int nextProbe = -1;
                float farthestFromProbes = -1f;
                for (int vertex = 0; vertex < vertices.Length; vertex++)
                {
                    float distance = (vertices[vertex] - vertices[currentProbe]).sqrMagnitude;
                    nearestDistanceSquared[vertex] = Mathf.Min(nearestDistanceSquared[vertex], distance);
                    if (!selected[vertex] && nearestDistanceSquared[vertex] > farthestFromProbes)
                    {
                        nextProbe = vertex;
                        farthestFromProbes = nearestDistanceSquared[vertex];
                    }
                }
                if (probe + 1 < probeCount)
                    currentProbe = nextProbe;
            }
            return probes;
        }

        private static float[] BuildDistanceSignature(Vector3[] vertices, int[] probes)
        {
            if (vertices == null || probes == null || probes.Length < 4)
                throw new InvalidOperationException("Invalid mesh-distance signature inputs");
            float[] signature = new float[vertices.Length * probes.Length];
            for (int vertex = 0; vertex < vertices.Length; vertex++)
            {
                int offset = vertex * probes.Length;
                for (int probe = 0; probe < probes.Length; probe++)
                    signature[offset + probe] = Vector3.Distance(vertices[vertex], vertices[probes[probe]]);
            }
            return signature;
        }

        private static float MeasureRendererLocalHeight(Vector3[] vertices)
        {
            if (vertices == null || vertices.Length < 4)
                throw new InvalidOperationException("Renderer-local shape normalization requires at least four vertices");
            Bounds bounds = new Bounds(vertices[0], Vector3.zero);
            foreach (Vector3 vertex in vertices)
                bounds.Encapsulate(vertex);
            float height = bounds.size.y;
            if (height <= 1e-5f)
                height = bounds.size.magnitude;
            if (float.IsNaN(height) || float.IsInfinity(height) || height <= 1e-5f)
                throw new InvalidOperationException("Skinned mesh has no finite renderer-local reference height");
            return height;
        }

        private static float[] NormalizeDistanceSignature(float[] signature, float referenceHeight)
        {
            if (signature == null || float.IsNaN(referenceHeight) || float.IsInfinity(referenceHeight)
                || referenceHeight <= 1e-5f)
                throw new InvalidOperationException("Invalid renderer-local shape normalization inputs");
            float[] normalized = new float[signature.Length];
            for (int i = 0; i < signature.Length; i++)
                normalized[i] = signature[i] / referenceHeight;
            return normalized;
        }

        private static void MeasureShapeMotion(float[][] reference, float[][] current,
            int[] vertexCounts, int[] probeCounts, float threshold,
            out int changedVertices, out float rmsDelta, out float maxPerVertexDelta)
        {
            if (reference == null || current == null || vertexCounts == null || probeCounts == null
                || reference.Length == 0 || reference.Length != current.Length
                || reference.Length != vertexCounts.Length || reference.Length != probeCounts.Length
                || vertexCounts.Any(x => x <= 0) || probeCounts.Any(x => x < 4))
                throw new InvalidOperationException("Skinned mesh shape signature dimensions changed during animation sampling");
            changedVertices = 0;
            double totalSquaredDelta = 0d;
            int totalVertices = 0;
            maxPerVertexDelta = 0f;
            for (int renderer = 0; renderer < reference.Length; renderer++)
            {
                int vertexCount = vertexCounts[renderer];
                int probeCount = probeCounts[renderer];
                int expectedLength = vertexCount * probeCount;
                if (reference[renderer] == null || current[renderer] == null
                    || reference[renderer].Length != expectedLength || current[renderer].Length != expectedLength)
                    throw new InvalidOperationException("Per-renderer shape signature dimensions changed during animation sampling");
                totalVertices += vertexCount;
                for (int vertex = 0; vertex < vertexCount; vertex++)
                {
                    int offset = vertex * probeCount;
                    double vertexSquaredDelta = 0d;
                    for (int probe = 0; probe < probeCount; probe++)
                    {
                        float delta = current[renderer][offset + probe] - reference[renderer][offset + probe];
                        vertexSquaredDelta += delta * delta;
                    }
                    float vertexRmsDelta = Mathf.Sqrt((float)(vertexSquaredDelta / probeCount));
                    if (vertexRmsDelta >= threshold)
                        changedVertices++;
                    totalSquaredDelta += vertexSquaredDelta / probeCount;
                    maxPerVertexDelta = Mathf.Max(maxPerVertexDelta, vertexRmsDelta);
                }
            }
            rmsDelta = totalVertices > 0 ? Mathf.Sqrt((float)(totalSquaredDelta / totalVertices)) : 0f;
        }

        private static List<ArcEvent> CreateArcs(PreviewSpec spec, Transform anchor, Transform root,
            Transform camera, float modelHeight, Material material)
        {
            List<ArcEvent> arcs = new List<ArcEvent>();
            Vector3 cameraRight = camera.right;
            Vector3 cameraUp = camera.up;
            Vector3 towardCamera = -camera.forward;
            Vector3 startOffset = Vector(spec.anchorLocalOffset, Vector3.zero);
            // Keep the arc camera-oriented; only its origin follows head animation.
            Vector3 viewOffset = Vector(spec.anchorViewOffsetRelativeToHeight, Vector3.zero) * modelHeight;
            Vector3 startViewWorldOffset = cameraRight * viewOffset.x + cameraUp * viewOffset.y
                + towardCamera * viewOffset.z;
            for (int i = 0; i < spec.eventTimesSeconds.Length; i++)
            {
                float length = modelHeight * spec.arcLengthRelativeToHeight;
                const int poseCount = 2;
                const int pointCount = 13;
                Vector3[][] mainViewPoses = new Vector3[poseCount][];
                Vector3[][][] branchViewPoses = new Vector3[poseCount][][];
                for (int pose = 0; pose < poseCount; pose++)
                {
                    System.Random random = new System.Random(unchecked(spec.seed + i * 7919 + pose * 104729));
                    Vector3[] main = new Vector3[pointCount];
                    for (int p = 0; p < pointCount; p++)
                    {
                        float u = (float)p / (pointCount - 1);
                        float taper = Mathf.Sin(u * Mathf.PI);
                        main[p] = cameraRight * (length * u)
                            + cameraUp * (length * (0.1f * u
                                + taper * ((float)random.NextDouble() - 0.5f) * 0.24f))
                            + towardCamera * (modelHeight * 0.015f * u);
                    }
                    mainViewPoses[pose] = main;
                    branchViewPoses[pose] = new Vector3[spec.branchCount][];
                    for (int b = 0; b < spec.branchCount; b++)
                    {
                        Vector3 from = main[3 + b * 2 % 8];
                        float direction = b % 2 == 0 ? 1f : -1f;
                        Vector3 end = from + cameraRight * (modelHeight * (0.12f + 0.03f * (b % 3)))
                            + cameraUp * (modelHeight * direction * (0.13f + 0.025f * (b % 2)));
                        branchViewPoses[pose][b] = new[]
                        {
                            from,
                            Vector3.Lerp(from, end, 0.48f)
                                + cameraUp * (modelHeight * direction * 0.055f),
                            end
                        };
                    }
                }

                LineRenderer glow = CreateLine(root, material, pointCount,
                    modelHeight * spec.arcWidthRelativeToHeight,
                    new Color(0.12f, 0.66f, 1f, 0.62f));
                LineRenderer core = CreateLine(root, material, pointCount,
                    modelHeight * spec.arcWidthRelativeToHeight * 0.34f,
                    new Color(1f, 1f, 1f, 1f));
                glow.sortingOrder = 0;
                core.sortingOrder = 2;
                LineRenderer[] branches = new LineRenderer[spec.branchCount];
                for (int b = 0; b < spec.branchCount; b++)
                {
                    branches[b] = CreateLine(root, material, 3,
                        modelHeight * spec.arcWidthRelativeToHeight * 0.28f,
                        new Color(0.9f, 0.97f, 1f, 1f));
                    branches[b].sortingOrder = 1;
                }

                GameObject lightObject = new GameObject("ElectricityEmissionLight_" + i);
                lightObject.transform.SetParent(root, false);
                lightObject.layer = PreviewLayer;
                Light emissionLight = lightObject.AddComponent<Light>();
                emissionLight.type = LightType.Point;
                emissionLight.color = new Color(0.15f, 0.72f, 1f);
                emissionLight.range = modelHeight * spec.arcLightRangeRelativeToHeight;
                emissionLight.intensity = 0f;
                emissionLight.shadows = LightShadows.None;
                emissionLight.cullingMask = 1 << PreviewLayer;
                emissionLight.enabled = false;

                arcs.Add(new ArcEvent
                {
                    start = spec.eventTimesSeconds[i],
                    end = spec.eventTimesSeconds[i] + spec.effectDurationSeconds,
                    anchor = anchor,
                    glow = glow,
                    core = core,
                    branches = branches,
                    emissionLight = emissionLight,
                    lightIntensity = spec.arcLightIntensity,
                    lightCameraOffset = towardCamera * modelHeight * 0.06f,
                    startLocalOffset = startOffset,
                    startViewWorldOffset = startViewWorldOffset,
                    mainViewPoses = mainViewPoses,
                    branchViewPoses = branchViewPoses
                });
            }
            return arcs;
        }

        private static LineRenderer CreateLine(Transform parent, Material material, int pointCount, float width, Color color)
        {
            GameObject lineObject = new GameObject("ElectricArcLine");
            lineObject.transform.SetParent(parent, false);
            lineObject.layer = PreviewLayer;
            LineRenderer line = lineObject.AddComponent<LineRenderer>();
            line.useWorldSpace = true;
            line.positionCount = pointCount;
            line.widthMultiplier = width;
            line.widthCurve = AnimationCurve.Linear(0f, 1f, 1f, 0.25f);
            line.numCornerVertices = 2;
            line.numCapVertices = 2;
            line.alignment = LineAlignment.View;
            line.shadowCastingMode = ShadowCastingMode.Off;
            line.receiveShadows = false;
            line.sharedMaterial = material;
            line.startColor = color;
            line.endColor = color;
            line.enabled = false;
            return line;
        }

        private static List<ParticleEvent> CreateParticleEvents(PreviewSpec spec, GameObject effectPrefab, Transform anchor)
        {
            List<ParticleEvent> result = new List<ParticleEvent>();
            Vector3 offset = Vector(spec.anchorLocalOffset, Vector3.zero);
            for (int i = 0; i < spec.eventTimesSeconds.Length; i++)
            {
                GameObject effect = UnityEngine.Object.Instantiate(effectPrefab, anchor, false);
                effect.name = "UnitVfxPreviewParticleEvent_" + i;
                SetLayerRecursively(effect.transform, PreviewLayer);
                effect.transform.localPosition = offset;
                effect.transform.localRotation = Quaternion.identity;
                ParticleSystem[] systems = effect.GetComponentsInChildren<ParticleSystem>(true);
                if (systems.Length == 0)
                    throw new InvalidOperationException("Effect prefab contains no ParticleSystem: " + spec.effectPrefabAssetPath);
                foreach (ParticleSystem system in systems)
                {
                    system.useAutoRandomSeed = false;
                    system.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
                }
                result.Add(new ParticleEvent
                {
                    start = spec.eventTimesSeconds[i],
                    end = spec.eventTimesSeconds[i] + spec.effectDurationSeconds,
                    instance = effect,
                    systems = systems,
                    roots = systems.Where(x => !HasParticleSystemAncestor(x.transform, effect.transform)).ToArray(),
                    seed = unchecked((uint)(spec.seed + i * 7919))
                });
            }
            return result;
        }

        private static bool HasParticleSystemAncestor(Transform node, Transform root)
        {
            for (Transform parent = node.parent; parent != null; parent = parent.parent)
            {
                if (parent.GetComponent<ParticleSystem>() != null)
                    return true;
                if (parent == root)
                    break;
            }
            return false;
        }

        private static void SimulateParticleAtTime(ParticleEvent effect, float time)
        {
            float elapsed = time - effect.start;
            if (elapsed < 0f || time >= effect.end)
            {
                effect.instance.SetActive(false);
                return;
            }
            effect.instance.SetActive(true);
            for (int i = 0; i < effect.systems.Length; i++)
            {
                effect.systems[i].useAutoRandomSeed = false;
                effect.systems[i].randomSeed = unchecked(effect.seed + (uint)i);
            }
            for (int i = 0; i < effect.roots.Length; i++)
            {
                ParticleSystem system = effect.roots[i];
                system.Simulate(elapsed, true, true, true);
            }
        }

        private static void SetArcAtTime(ArcEvent arc, float time)
        {
            SetArcGeometryAtTime(arc, time);
            SetArcLightAtTime(arc, time);
        }

        private static void SetArcGeometryAtTime(ArcEvent arc, float time)
        {
            bool active = time >= arc.start && time < arc.end;
            if (!active)
            {
                SetArcGeometryInactive(arc);
                return;
            }
            float progress = Mathf.Clamp01((time - arc.start) / Mathf.Max(arc.end - arc.start, 1e-5f));
            float reach = Mathf.Min(1f, 0.88f + progress * 0.8f, (1f - progress) * 2.9f);
            float pulse = ElectricPulse(progress);
            int pose = progress < 0.5f ? 0 : 1;
            arc.glow.startColor = arc.glow.endColor = new Color(0.12f, 0.66f, 1f, 0.62f * pulse);
            arc.core.startColor = arc.core.endColor = new Color(1f, 1f, 1f, pulse);
            Vector3 anchorPosition = arc.anchor.TransformPoint(arc.startLocalOffset) + arc.startViewWorldOffset;
            Vector3[] worldPoints = arc.mainViewPoses[pose]
                .Select(offset => anchorPosition + offset * reach).ToArray();
            arc.glow.SetPositions(worldPoints);
            arc.core.SetPositions(worldPoints);
            arc.glow.enabled = true;
            arc.core.enabled = true;
            for (int i = 0; i < arc.branches.Length; i++)
            {
                arc.branches[i].SetPositions(
                    arc.branchViewPoses[pose][i].Select(offset => anchorPosition + offset * reach).ToArray());
                arc.branches[i].enabled = progress <= 0.86f;
            }
        }

        private static void SetArcLightAtTime(ArcEvent arc, float time)
        {
            bool active = time >= arc.start && time < arc.end;
            arc.emissionLight.enabled = active;
            if (!active) return;
            float progress = Mathf.Clamp01((time - arc.start) / Mathf.Max(arc.end - arc.start, 1e-5f));
            float pulse = ElectricPulse(progress);
            Vector3 anchorPosition = arc.anchor.TransformPoint(arc.startLocalOffset) + arc.startViewWorldOffset;
            arc.emissionLight.transform.position = anchorPosition + arc.lightCameraOffset
                + arc.mainViewPoses[0][1] * 0.12f;
            arc.emissionLight.intensity = arc.lightIntensity * pulse;
        }

        private static float ElectricPulse(float progress)
        {
            return 0.55f + 0.45f * Mathf.Sin(progress * Mathf.PI);
        }

        private static void SetArcInactive(ArcEvent arc)
        {
            SetArcGeometryInactive(arc);
            arc.emissionLight.enabled = false;
        }

        private static void SetArcGeometryInactive(ArcEvent arc)
        {
            arc.glow.enabled = false;
            arc.core.enabled = false;
            foreach (LineRenderer branch in arc.branches) branch.enabled = false;
        }

        private static int RenderFrame(Camera camera, RenderTexture target, Texture2D readback, string path)
        {
            camera.Render();
            RenderTexture previous = RenderTexture.active;
            try
            {
                RenderTexture.active = target;
                readback.ReadPixels(new Rect(0, 0, target.width, target.height), 0, 0, false);
                readback.Apply(false, false);
                Color32[] pixels = readback.GetPixels32();
                int opaque = pixels.Count(x => x.a > 8 && (x.r > 4 || x.g > 4 || x.b > 4));
                if (opaque < 32)
                    throw new InvalidOperationException("Rendered frame is blank: " + path);
                if (!string.IsNullOrEmpty(path)) File.WriteAllBytes(path, readback.EncodeToPNG());
                return opaque;
            }
            finally
            {
                RenderTexture.active = previous;
            }
        }

        private static int CountChangedPixels(Color32[] a, Color32[] b)
        {
            if (a.Length != b.Length)
                throw new InvalidOperationException("Rendered passes have different pixel counts");
            int changed = 0;
            for (int i = 0; i < a.Length; i++)
            {
                if (Mathf.Abs(a[i].r - b[i].r) > 3 || Mathf.Abs(a[i].g - b[i].g) > 3
                    || Mathf.Abs(a[i].b - b[i].b) > 3 || Mathf.Abs(a[i].a - b[i].a) > 3)
                    changed++;
            }
            return changed;
        }

        private static int CountMeshLightingChanges(Color32[] baseline, Color32[] lit, out int brightened)
        {
            if (baseline.Length != lit.Length)
                throw new InvalidOperationException("Rendered passes have different pixel counts");
            int changed = 0;
            brightened = 0;
            for (int i = 0; i < baseline.Length; i++)
            {
                if (baseline[i].a <= 8 || lit[i].a <= 8) continue;
                int red = Mathf.Abs(baseline[i].r - lit[i].r);
                int green = Mathf.Abs(baseline[i].g - lit[i].g);
                int blue = Mathf.Abs(baseline[i].b - lit[i].b);
                if (red > 3 || green > 3 || blue > 3) changed++;
                int baselineLuma = 54 * baseline[i].r + 183 * baseline[i].g + 19 * baseline[i].b;
                int litLuma = 54 * lit[i].r + 183 * lit[i].g + 19 * lit[i].b;
                if (litLuma > baselineLuma + 12 * 256) brightened++;
            }
            return changed;
        }

        private static int MeshLightingRequiredPixels(int surfacePixels)
        {
            return Mathf.Max(16, Mathf.CeilToInt(surfacePixels * 0.01f));
        }

        private static List<Material> ApplyLitPreviewMaterials(Renderer[] renderers)
        {
            Shader shader = Shader.Find("Standard");
            if (shader == null)
                throw new InvalidOperationException("The Built-in Standard shader is required for point-light preview");
            List<Material> created = new List<Material>();
            foreach (Renderer renderer in renderers)
            {
                Material[] sourceMaterials = renderer.sharedMaterials;
                Material[] previewMaterials = new Material[sourceMaterials.Length];
                for (int i = 0; i < sourceMaterials.Length; i++)
                {
                    Material source = sourceMaterials[i];
                    if (source == null)
                        throw new InvalidOperationException("Unit renderer has a missing material: " + renderer.name);
                    Material preview = new Material(shader)
                    {
                        name = source.name + " (VFX Lit Preview)",
                        hideFlags = HideFlags.HideAndDontSave
                    };
                    preview.mainTexture = source.mainTexture;
                    preview.color = source.HasProperty("_Color") ? source.color : Color.white;
                    preview.SetFloat("_Metallic", 0f);
                    preview.SetFloat("_Glossiness", 0.12f);
                    created.Add(preview);
                    previewMaterials[i] = preview;
                }
                renderer.sharedMaterials = previewMaterials;
            }
            return created;
        }

        private static Material CreateArcMaterial()
        {
            Shader shader = Shader.Find("Sprites/Default") ?? Shader.Find("Unlit/Color");
            if (shader == null)
                throw new InvalidOperationException("No transparent preview shader found for electric arcs");
            return new Material(shader) { hideFlags = HideFlags.HideAndDontSave };
        }

        private static Transform FindUniqueTransform(Transform root, string name)
        {
            Transform[] matches = root.GetComponentsInChildren<Transform>(true).Where(x => x.name == name).ToArray();
            if (matches.Length != 1)
                throw new InvalidOperationException("Expected one transform named '" + name + "', found " + matches.Length);
            return matches[0];
        }

        private static Bounds CombinedBounds(Renderer[] renderers)
        {
            Bounds result = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++) result.Encapsulate(renderers[i].bounds);
            return result;
        }

        private static Bounds IncludeArcBounds(Bounds bounds, ArcEvent arc)
        {
            Vector3 anchorPosition = arc.anchor.TransformPoint(arc.startLocalOffset) + arc.startViewWorldOffset;
            foreach (Vector3[] pose in arc.mainViewPoses)
                foreach (Vector3 offset in pose)
                    bounds.Encapsulate(anchorPosition + offset);
            foreach (Vector3[][] pose in arc.branchViewPoses)
                foreach (Vector3[] branch in pose)
                    foreach (Vector3 point in branch)
                        bounds.Encapsulate(anchorPosition + point);
            return bounds;
        }

        private static void SetLayerRecursively(Transform root, int layer)
        {
            root.gameObject.layer = layer;
            foreach (Transform child in root) SetLayerRecursively(child, layer);
        }

        private static float ProjectedHalfExtent(Bounds bounds, Vector3 axis)
        {
            Vector3 extents = bounds.extents;
            return Mathf.Abs(axis.x) * extents.x + Mathf.Abs(axis.y) * extents.y + Mathf.Abs(axis.z) * extents.z;
        }

        private static float ClipTime(float time, PreviewSpec spec, AnimationClip clip)
        {
            return spec.loopClip ? Mathf.Repeat(time, clip.length) : Mathf.Min(time, clip.length);
        }

        private static Vector3 Vector(float[] values, Vector3 fallback)
        {
            return values != null && values.Length == 3 ? new Vector3(values[0], values[1], values[2]) : fallback;
        }

        private static bool IsEffectActive(PreviewSpec spec, float time)
        {
            return spec.eventTimesSeconds.Any(start => time >= start && time < start + spec.effectDurationSeconds);
        }

        private static HashSet<int>[] BuildEventVerificationFrames(PreviewSpec spec)
        {
            int frameCount = Mathf.CeilToInt(spec.durationSeconds * spec.fps);
            HashSet<int>[] result = new HashSet<int>[spec.eventTimesSeconds.Length];
            for (int eventIndex = 0; eventIndex < result.Length; eventIndex++)
            {
                float start = spec.eventTimesSeconds[eventIndex];
                List<int> activeFrames = new List<int>();
                for (int frame = 0; frame < frameCount; frame++)
                {
                    float time = (float)frame / spec.fps;
                    if (time >= start && time < start + spec.effectDurationSeconds)
                        activeFrames.Add(frame);
                }

                result[eventIndex] = new HashSet<int>();
                int checkCount = Mathf.Min(5, activeFrames.Count);
                for (int check = 0; check < checkCount; check++)
                {
                    float fraction = checkCount <= 1 ? 0f : (float)check / (checkCount - 1);
                    int selected = Mathf.RoundToInt(fraction * (activeFrames.Count - 1));
                    result[eventIndex].Add(activeFrames[selected]);
                }
            }
            return result;
        }

        private static string Argument(string name)
        {
            string[] args = UnityQueueArgs();
            for (int i = 0; i + 1 < args.Length; i++)
                if (args[i] == name) return args[i + 1];
            return null;
        }
    }
}
