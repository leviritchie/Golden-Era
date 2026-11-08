// Diagnostic source-guided five-chain pose pilot. Never samples the rejected humanoid clip.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using GLTFast;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace OldenEra.Homm3Import
{
    public static class BeholderAttackContourV14
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

        private const int PreviewLayer = 30;

        [Serializable] private sealed class Tip { public float x, y; }
        [Serializable] private sealed class ChainSpec { public string[] bones; }
        [Serializable] private sealed class ContourKnot
        {
            public int jointIndex;
            public Tip point;
            public bool sourceVisible;
        }
        [Serializable] private sealed class ContourTarget
        {
            public string root;
            public ContourKnot[] knots;
        }
        [Serializable] private sealed class FrameSpec
        {
            public string name, sourcePath, sourceSha256, cropPath, cropSha256;
            public int x0, y0, x1, y1, corePixels, forwardEffectPixels;
            public bool hasLightOrigin;
            public Tip lightOrigin;
            public float lightScale;
            public ContourTarget[] targets;
            public string emitterChainRoot;
            public int emitterJointIndex;
            public Tip emitterSource;
        }
        [Serializable] private sealed class Spec
        {
            public string schema, status, glbPath, glbSha256, frontChainRoot;
            public string authoredSpecPath, authoredSpecSha256, runnerPath, runnerSha256;
            public string editorScriptPath, editorScriptSha256;
            public float yawDegrees, sourceBodyX, sourceGroundY, pixelsPerUnit;
            public float pointLightIntensity, pointLightRange, cardDepthTowardCamera;
            public int renderSize, gifFrameDurationMs;
            public ChainSpec[] chains;
            public FrameSpec[] frames;
        }
        [Serializable] private sealed class ChainResult
        {
            public string root;
            public bool sourceConstrained, distalNotTargeted;
            public float targetX, targetY, actualX, actualY, tipResidualPixels;
            public float midpointTargetX, midpointTargetY, midpointActualX, midpointActualY, midpointResidualPixels;
            public float bakedMaxDisplacementVsHoldingThisChainAtRest;
            public Tip[] jointXY;
            public float observedContourMeanResidualPixels, observedContourMaxResidualPixels;
            public int observedContourKnotCount, inferredContourKnotCount;
        }
        [Serializable] private sealed class FrameResult
        {
            public string name, sourceSha256, cropSha256;
            public int meshMaskPixels, magentaFailurePixels, coreVisiblePixels, meshLightingChangedPixels, meshBrightenedPixels;
            public int forwardEffectPixels, sourceElectricityCells;
            public float bakedMeshMaxVertexDelta, pointLightIntensity, lightOriginX, lightOriginY, electricitySurfaceDepthSpan;
            public float emitterProjectionResidualPixels;
            public string emitterJointName;
            public ChainResult[] chains;
        }
        [Serializable] private sealed class Report
        {
            public string schema = "beholder_attack_contour_v14_report";
            public string proof = "unity-editor-gltfast-render";
            public string glbPath, glbSha256, status, clipUnityAssetPath, clipArtifactPath, clipSha256;
            public string authoredSpecSha256, runnerSha256, editorScriptSha256;
            public float clipSampleMaxAngleDegrees;
            public float clipBetweenKeyMaxAngleDegrees;
            public int clipBetweenKeySamples;
            public float clipSampleMaxEmitterPositionDelta;
            public float clipSampleMaxLightIntensityError;
            public float clipMaxActiveEffectPositionDelta, clipMaxActiveEffectRotationDelta;
            public int clipActiveEffectPoseSamples;
            public int clipPhaseActivationKeyErrors, clipEffectPhaseCount;
            public float yawDegrees;
            public int rendererCount, skinnedRendererCount, skinBoneCount, vertexCount, triangleCount, frameCount;
            public bool rejectedHumanoidClipUsed = false;
            public string lightingPass = "Selected forward-discharge source pixels keep their exact front-view mask on folded 3D cells; depth is reconstructed, and a timed Point Light follows sprite contact";
            public List<FrameResult> frames = new List<FrameResult>();
        }

        public static void RenderFromBatch()
        {
            string specPath = Argument("-beholderAttackRepairSpec");
            string output = Argument("-beholderAttackRepairOut");
            if (string.IsNullOrEmpty(specPath) || string.IsNullOrEmpty(output))
                throw new InvalidOperationException("Missing Beholder attack repair spec/output arguments");
            File.WriteAllText(Path.Combine(output, "entered_execute_method.txt"), DateTime.UtcNow.ToString("O"));
            Debug.Log("BeholderAttackRepairSolV1 entered executeMethod");
            Debug.Log("BeholderAttackRepairSolV1 render pipeline: "
                + (GraphicsSettings.currentRenderPipeline == null ? "Built-in" : GraphicsSettings.currentRenderPipeline.name));
            Spec spec = JsonUtility.FromJson<Spec>(File.ReadAllText(specPath));
            if (spec == null || spec.schema != "beholder_attack_contour_v14" || spec.frames == null
                || spec.frames.Length != 7 || spec.chains == null || spec.chains.Length != 5)
                throw new InvalidOperationException("Invalid Beholder repair runtime spec");
            if (spec.gifFrameDurationMs != 220)
                throw new InvalidOperationException("Unity clip timing drift from synchronized source GIF");
            if (Sha256File(spec.glbPath) != spec.glbSha256
                || Sha256File(spec.authoredSpecPath) != spec.authoredSpecSha256
                || Sha256File(spec.runnerPath) != spec.runnerSha256
                || Sha256File(spec.editorScriptPath) != spec.editorScriptSha256)
                throw new InvalidOperationException("Frozen GLB or source runner/spec hash drift before Unity render");
            if (spec.chains.Count(chain => chain.bones[0] == spec.frontChainRoot) != 1)
                throw new InvalidOperationException("Front Beholder chain root absent or ambiguous");
            GameObject root = null, cameraObject = null, card = null, lightObject = null, fillLightObject = null;
            RenderTexture target = null;
            Texture2D readback = null;
            var owned = new List<UnityEngine.Object>();
            var effectPhases = new List<GameObject>();
            var effectPhaseFrames = new List<int>();
            var sampledEffectWorldPositions = new List<Vector3>();
            var sampledEffectWorldRotations = new List<Quaternion>();
            var sampledLightLocalPositions = new List<Vector3>();
            var sampledLightIntensities = new List<float>();
            var sampledLightEnabled = new List<bool>();
            try
            {
                root = new GameObject("FrozenBeholderFiveChainOnly");
                var importer = new GltfImport(deferAgent: new UninterruptedDeferAgent());
                Debug.Log("BeholderAttackRepairSolV1 loading frozen GLB with GLTFast");
                if (!RunGltfTask(() => importer.Load(File.ReadAllBytes(spec.glbPath)))
                    || !RunGltfTask(() => importer.InstantiateMainSceneAsync(root.transform)))
                    throw new InvalidOperationException("GLTFast failed to instantiate frozen five-chain GLB");
                Debug.Log("BeholderAttackRepairSolV1 GLB instantiated");
                foreach (Animator animator in root.GetComponentsInChildren<Animator>(true)) animator.enabled = false;
                SetLayer(root.transform);
                Renderer[] renderers = root.GetComponentsInChildren<Renderer>(true).Where(r => r.enabled).ToArray();
                if (renderers.Length == 0) throw new InvalidOperationException("GLTFast created no visible renderer");
                SkinnedMeshRenderer[] skinnedRenderers = renderers.OfType<SkinnedMeshRenderer>().ToArray();
                if (skinnedRenderers.Length != 1 || skinnedRenderers[0].bones.Length != 34)
                    throw new InvalidOperationException("GLTFast did not bind the frozen 34-bone skinned mesh");
                SkinnedMeshRenderer skin = skinnedRenderers[0];
                skin.updateWhenOffscreen = true;
                skin.forceMatrixRecalculationPerRender = true;
                Debug.Log($"BeholderAttackRepairSolV1 skin renderer={skin.name}, bones={skin.bones.Length}, material={skin.sharedMaterial?.shader?.name}");
                int vertices = 0, triangles = 0;
                foreach (Renderer renderer in renderers)
                {
                    Mesh mesh = renderer is SkinnedMeshRenderer skinned ? skinned.sharedMesh :
                        renderer.GetComponent<MeshFilter>()?.sharedMesh;
                    if (mesh == null) throw new InvalidOperationException("Missing mesh on " + renderer.name);
                    vertices += mesh.vertexCount;
                    for (int i = 0; i < mesh.subMeshCount; i++) triangles += (int)mesh.GetIndexCount(i) / 3;
                }
                if (vertices != 8405 || triangles != 9023)
                    throw new InvalidOperationException($"Frozen GLB topology drift: {vertices} vertices, {triangles} triangles");
                ApplyLitMaterials(renderers, owned);
                Material[][] litMaterials = renderers.Select(r => r.sharedMaterials).ToArray();
                Material maskMaterial = new Material(RequiredShader("Unlit/Color"))
                    { name = "BeholderSilhouetteOnly" };
                maskMaterial.color = Color.white;
                owned.Add(maskMaterial);
                Material[][] maskMaterials = renderers.Select(r => r.sharedMaterials.Select(_ => maskMaterial).ToArray()).ToArray();

                root.transform.rotation = Quaternion.Euler(0f, spec.yawDegrees, 0f);
                Bounds bounds = renderers[0].bounds;
                for (int i = 1; i < renderers.Length; i++) bounds.Encapsulate(renderers[i].bounds);
                root.transform.position = new Vector3(-bounds.center.x, -bounds.min.y, -bounds.center.z);

                Vector3 towardCamera = new Vector3(-0.573576f, 0f, 0.819152f).normalized;
                cameraObject = new GameObject("BeholderSourceFacingCamera");
                Camera camera = cameraObject.AddComponent<Camera>();
                camera.enabled = false;
                camera.cullingMask = 1 << PreviewLayer;
                camera.orthographic = true;
                camera.orthographicSize = 2f;
                camera.clearFlags = CameraClearFlags.SolidColor;
                camera.backgroundColor = new Color(0.08f, 0.10f, 0.13f, 1f);
                camera.nearClipPlane = 0.01f;
                camera.farClipPlane = 50f;
                camera.allowHDR = false;
                camera.allowMSAA = false;
                Vector3 right = new Vector3(-0.819152f, 0f, -0.573576f).normalized;
                Vector3 focus = right * ((200f - spec.sourceBodyX) / spec.pixelsPerUnit)
                    + Vector3.up * ((spec.sourceGroundY - 220f) / spec.pixelsPerUnit);
                camera.transform.position = focus + towardCamera * 7f;
                camera.transform.rotation = Quaternion.LookRotation(focus - camera.transform.position, Vector3.up);
                target = new RenderTexture(spec.renderSize, spec.renderSize, 24, RenderTextureFormat.ARGB32)
                    { antiAliasing = 1 };
                target.Create();
                camera.targetTexture = target;
                readback = new Texture2D(spec.renderSize, spec.renderSize, TextureFormat.RGBA32, false);

                card = new GameObject("ExactSourcePixelsFoldedSurface");
                card.layer = PreviewLayer;
                card.transform.rotation = camera.transform.rotation;
                MeshFilter cardFilter = card.AddComponent<MeshFilter>();
                MeshRenderer cardRenderer = card.AddComponent<MeshRenderer>();
                cardRenderer.shadowCastingMode = ShadowCastingMode.Off;
                cardRenderer.receiveShadows = false;
                Mesh effectMesh = new Mesh { name = "EmitterAnchoredSourcePixelSurface" };
                effectMesh.indexFormat = IndexFormat.UInt32;
                cardFilter.sharedMesh = effectMesh;
                owned.Add(effectMesh);
                Material cardMaterial = new Material(RequiredShader("Unlit/Transparent Cutout"))
                    { name = "ExactSourcePixelElectricity" };
                cardMaterial.SetFloat("_Cutoff", 0.5f);
                cardMaterial.renderQueue = (int)RenderQueue.AlphaTest;
                cardRenderer.sharedMaterial = cardMaterial;
                owned.Add(cardMaterial);

                fillLightObject = new GameObject("BeholderConstantMeshFill");
                Light fill = fillLightObject.AddComponent<Light>();
                fill.type = LightType.Directional;
                fill.color = new Color(1f, 0.95f, 0.88f);
                fill.intensity = 0.7f;
                fill.cullingMask = 1 << PreviewLayer;
                fillLightObject.transform.rotation = Quaternion.LookRotation(-towardCamera + Vector3.down * 0.2f);

                lightObject = new GameObject("BeholderActualPointLight");
                Light point = lightObject.AddComponent<Light>();
                point.type = LightType.Point;
                point.cullingMask = 1 << PreviewLayer;
                point.color = new Color(0.72f, 0.87f, 1f);
                point.intensity = spec.pointLightIntensity;
                point.range = spec.pointLightRange;
                point.shadows = LightShadows.None;
                Transform[][] chains = spec.chains.Select(chain => chain.bones.Select(name => FindUnique(root, name)).ToArray()).ToArray();
                Transform[] bones = chains.SelectMany(x => x).Distinct().ToArray();
                if (bones.Length != 32) throw new InvalidOperationException("Expected 32 articulated chain joints");
                var restLocalRotations = bones.ToDictionary(b => b, b => b.localRotation);
                var sampledRotations = bones.ToDictionary(b => b, b => new List<Quaternion>());
                lightObject.transform.SetParent(root.transform, true);
                foreach (Transform[] chain in chains)
                    if (!skin.bones.Contains(chain[0]) || !skin.bones.Contains(chain[chain.Length - 1]))
                        throw new InvalidOperationException("Source-listed chain is not bound to the skinned renderer: " + chain[0].name);
                // Frame 00 is the frozen bind pose; each later slot starts from the prior solved pose.
                // This chooses one continuous IK branch instead of re-solving every slot from rest.
                Report report = new Report { glbPath = spec.glbPath, glbSha256 = spec.glbSha256,
                    authoredSpecSha256 = spec.authoredSpecSha256, runnerSha256 = spec.runnerSha256,
                    editorScriptSha256 = spec.editorScriptSha256, status = spec.status,
                    yawDegrees = spec.yawDegrees, rendererCount = renderers.Length,
                    skinnedRendererCount = skinnedRenderers.Length, skinBoneCount = skin.bones.Length,
                    vertexCount = vertices, triangleCount = triangles, frameCount = spec.frames.Length };
                Mesh baked = new Mesh { name = "BeholderSkinMovementAudit" };
                Mesh counterfactualBaked = new Mesh { name = "BeholderChainHeldRestAudit" };
                owned.Add(baked);
                owned.Add(counterfactualBaked);
                Vector3[] restBaked = null;
                foreach (string lane in new[] { "baseline", "lit_mesh", "effect", "electricity_front", "clip_effect", "mesh_mask", "oblique" })
                    Directory.CreateDirectory(Path.Combine(output, lane));

                for (int frameIndex = 0; frameIndex < spec.frames.Length; frameIndex++)
                {
                    FrameSpec frame = spec.frames[frameIndex];
                    foreach (GameObject phase in effectPhases) phase.SetActive(false);
                    if (Sha256File(frame.sourcePath) != frame.sourceSha256
                        || Sha256File(frame.cropPath) != frame.cropSha256)
                        throw new InvalidOperationException("Source sprite/effect crop changed during Unity proof: " + frame.name);
                    if (frame.targets == null || frame.targets.Length != chains.Length)
                        throw new InvalidOperationException("Missing five contour targets: " + frame.name);
                    ChainResult[] chainResults = new ChainResult[chains.Length];
                    for (int c = 0; c < chains.Length; c++)
                    {
                        Transform[] chain = chains[c];
                        ContourTarget contour = frame.targets[c];
                        if (contour.root != chain[0].name || contour.knots == null || contour.knots.Length < 2)
                            throw new InvalidOperationException("Contour target chain identity drift: " + frame.name);
                        ChainResult result = new ChainResult { root = chain[0].name };
                        SolveContour(chain, contour.knots, spec, right, towardCamera);
                        int middle = chain.Length / 2;
                        result.sourceConstrained = contour.knots.Any(k => k.sourceVisible);
                        result.distalNotTargeted = !contour.knots.Any(k => k.sourceVisible && k.jointIndex == chain.Length - 1);
                        float residualSum = 0f;
                        foreach (ContourKnot knot in contour.knots)
                        {
                            if (!knot.sourceVisible) { result.inferredContourKnotCount++; continue; }
                            Vector2 actualKnot = ProjectSource(chain[knot.jointIndex].position, spec, right);
                            float residual = Vector2.Distance(actualKnot, new Vector2(knot.point.x, knot.point.y));
                            residualSum += residual;
                            result.observedContourMaxResidualPixels = Mathf.Max(result.observedContourMaxResidualPixels, residual);
                            result.observedContourKnotCount++;
                        }
                        if (result.observedContourKnotCount > 0)
                            result.observedContourMeanResidualPixels = residualSum / result.observedContourKnotCount;
                        Vector3 actualMidpoint = chain[middle].position;
                        result.midpointActualX = spec.sourceBodyX + Vector3.Dot(actualMidpoint, right) * spec.pixelsPerUnit;
                        result.midpointActualY = spec.sourceGroundY - actualMidpoint.y * spec.pixelsPerUnit;
                        Vector3 actual = chain[chain.Length - 1].position;
                        result.actualX = spec.sourceBodyX + Vector3.Dot(actual, right) * spec.pixelsPerUnit;
                        result.actualY = spec.sourceGroundY - actual.y * spec.pixelsPerUnit;
                        result.jointXY = chain.Select(b => new Tip {
                            x = spec.sourceBodyX + Vector3.Dot(b.position, right) * spec.pixelsPerUnit,
                            y = spec.sourceGroundY - b.position.y * spec.pixelsPerUnit
                        }).ToArray();
                        chainResults[c] = result;
                    }
                    foreach (Transform bone in bones) sampledRotations[bone].Add(bone.localRotation);
                    skin.BakeMesh(baked);
                    Vector3[] posedVertices = baked.vertices;
                    if (restBaked == null) restBaked = posedVertices;
                    float bakedDelta = 0f;
                    for (int i = 0; i < posedVertices.Length; i++)
                        bakedDelta = Mathf.Max(bakedDelta, Vector3.Distance(restBaked[i], posedVertices[i]));
                    for (int c = 0; c < chains.Length; c++)
                    {
                        Transform[] chain = chains[c];
                        Quaternion[] pose = chain.Select(b => b.localRotation).ToArray();
                        foreach (Transform bone in chain) bone.localRotation = restLocalRotations[bone];
                        skin.BakeMesh(counterfactualBaked);
                        Vector3[] heldVertices = counterfactualBaked.vertices;
                        float contribution = 0f;
                        for (int i = 0; i < posedVertices.Length; i++)
                            contribution = Mathf.Max(contribution, Vector3.Distance(posedVertices[i], heldVertices[i]));
                        chainResults[c].bakedMaxDisplacementVsHoldingThisChainAtRest = contribution;
                        for (int i = 0; i < chain.Length; i++) chain[i].localRotation = pose[i];
                    }
                    cardRenderer.enabled = false;
                    point.enabled = false;
                    Color32[] baseline = Capture(camera, target, readback, Path.Combine(output, "baseline", frame.name + ".png"));
                    SwapMaterials(renderers, maskMaterials);
                    Color oldBackground = camera.backgroundColor;
                    camera.backgroundColor = Color.black;
                    Color32[] mask = Capture(camera, target, readback, Path.Combine(output, "mesh_mask", frame.name + ".png"));
                    camera.backgroundColor = oldBackground;
                    SwapMaterials(renderers, litMaterials);
                    if (frame.hasLightOrigin != (frame.forwardEffectPixels > 0)
                        || frame.lightScale < 0f || frame.lightScale > 1f)
                        throw new InvalidOperationException("Invalid source-derived discharge light: " + frame.name);
                    int emitterIndex = Array.FindIndex(chains, chain => chain[0].name == frame.emitterChainRoot);
                    if (emitterIndex < 0 || frame.emitterSource == null
                        || frame.emitterJointIndex < 0 || frame.emitterJointIndex >= chains[emitterIndex].Length)
                        throw new InvalidOperationException("Missing posed-chain emitter: " + frame.name);
                    Transform emitterBone = chains[emitterIndex][frame.emitterJointIndex];
                    Vector3 emitter = emitterBone.position;
                    Vector3 sourceContact = SourcePoint(frame.emitterSource, emitter, spec, right, towardCamera);
                    float emitterResidual = Vector2.Distance(ProjectSource(emitter, spec, right),
                        new Vector2(frame.emitterSource.x, frame.emitterSource.y));
                    point.intensity = spec.pointLightIntensity * frame.lightScale;
                    point.enabled = frame.hasLightOrigin && point.intensity > 0f;
                    lightObject.transform.position = sourceContact + towardCamera * 0.08f;
                    sampledLightLocalPositions.Add(lightObject.transform.localPosition);
                    sampledLightIntensities.Add(point.intensity);
                    Color32[] lit = Capture(camera, target, readback, Path.Combine(output, "lit_mesh", frame.name + ".png"));
                    bool discharge = frame.forwardEffectPixels > 0;
                    if (discharge)
                    {
                        Texture2D crop = new Texture2D(2, 2, TextureFormat.RGBA32, false);
                        if (!crop.LoadImage(File.ReadAllBytes(frame.cropPath), false))
                            throw new InvalidOperationException("Could not load forward-effect crop: " + frame.cropPath);
                        crop.filterMode = FilterMode.Point;
                        crop.wrapMode = TextureWrapMode.Clamp;
                        cardMaterial.mainTexture = crop;
                        BuildEmitterSurface(effectMesh, frame, spec, crop.GetPixels32(), crop.width, crop.height);
                        card.transform.position = sourceContact + towardCamera * spec.cardDepthTowardCamera;
                        cardRenderer.enabled = true;
                        Color32[] effect = Capture(camera, target, readback, Path.Combine(output, "effect", frame.name + ".png"));
                        GameObject phaseObject = new GameObject("Electricity_" + frame.name);
                        phaseObject.layer = PreviewLayer;
                        MeshFilter phaseFilter = phaseObject.AddComponent<MeshFilter>();
                        MeshRenderer phaseRenderer = phaseObject.AddComponent<MeshRenderer>();
                        Mesh phaseMesh = UnityEngine.Object.Instantiate(effectMesh);
                        Texture2D phaseTexture = UnityEngine.Object.Instantiate(crop);
                        Material phaseMaterial = UnityEngine.Object.Instantiate(cardMaterial);
                        phaseMaterial.mainTexture = phaseTexture;
                        phaseFilter.sharedMesh = phaseMesh;
                        phaseRenderer.sharedMaterial = phaseMaterial;
                        phaseRenderer.shadowCastingMode = ShadowCastingMode.Off;
                        phaseRenderer.receiveShadows = false;
                        phaseObject.transform.SetParent(emitterBone, true);
                        phaseObject.transform.SetPositionAndRotation(card.transform.position, card.transform.rotation);
                        sampledEffectWorldPositions.Add(phaseObject.transform.position);
                        sampledEffectWorldRotations.Add(phaseObject.transform.rotation);
                        phaseObject.SetActive(false);
                        effectPhases.Add(phaseObject);
                        effectPhaseFrames.Add(frameIndex);
                        owned.Add(phaseMesh); owned.Add(phaseTexture); owned.Add(phaseMaterial);
                        cardRenderer.enabled = false;
                        owned.Add(crop);
                        report.frames.Add(Measure(frame, chainResults, baseline, mask, lit, effect));
                    }
                    else
                    {
                        File.Copy(Path.Combine(output, "lit_mesh", frame.name + ".png"),
                            Path.Combine(output, "effect", frame.name + ".png"));
                        report.frames.Add(Measure(frame, chainResults, baseline, mask, lit, lit));
                    }
                    report.frames[report.frames.Count - 1].bakedMeshMaxVertexDelta = bakedDelta;
                    report.frames[report.frames.Count - 1].pointLightIntensity = point.intensity;
                    report.frames[report.frames.Count - 1].forwardEffectPixels = frame.forwardEffectPixels;
                    report.frames[report.frames.Count - 1].sourceElectricityCells = frame.forwardEffectPixels;
                    report.frames[report.frames.Count - 1].electricitySurfaceDepthSpan = frame.forwardEffectPixels > 0
                        ? effectMesh.bounds.size.z : 0f;
                    report.frames[report.frames.Count - 1].lightOriginX = frame.lightOrigin.x;
                    report.frames[report.frames.Count - 1].lightOriginY = frame.lightOrigin.y;
                    report.frames[report.frames.Count - 1].emitterProjectionResidualPixels = emitterResidual;
                    report.frames[report.frames.Count - 1].emitterJointName = emitterBone.name + "@" + frame.emitterJointIndex;
                    sampledLightEnabled.Add(point.enabled);
                    point.enabled = false;
                }
                WriteDiagnosticClip(root, bones, sampledRotations, lightObject.transform, sampledLightLocalPositions,
                    point, sampledLightIntensities, sampledLightEnabled, effectPhases, effectPhaseFrames,
                    sampledEffectWorldPositions, sampledEffectWorldRotations, camera, target, readback, renderers,
                    focus, towardCamera, spec, output, report);
                File.WriteAllText(Path.Combine(output, "preview_report.json"), JsonUtility.ToJson(report, true));
                Debug.Log($"Beholder source-guided diagnostic rendered {report.frameCount} frames and an unaccepted Unity clip; no humanoid clip used");
            }
            finally
            {
                if (target != null) { target.Release(); UnityEngine.Object.DestroyImmediate(target); }
                if (readback != null) UnityEngine.Object.DestroyImmediate(readback);
                if (root != null) UnityEngine.Object.DestroyImmediate(root);
                if (cameraObject != null) UnityEngine.Object.DestroyImmediate(cameraObject);
                if (card != null) UnityEngine.Object.DestroyImmediate(card);
                if (lightObject != null) UnityEngine.Object.DestroyImmediate(lightObject);
                if (fillLightObject != null) UnityEngine.Object.DestroyImmediate(fillLightObject);
                foreach (UnityEngine.Object item in owned) if (item != null) UnityEngine.Object.DestroyImmediate(item);
            }
        }

        private static string Sha256File(string path)
        {
            using (var sha = SHA256.Create())
            using (var input = File.OpenRead(path))
                return BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
        }

        private static void WriteDiagnosticClip(GameObject root, Transform[] bones,
            Dictionary<Transform, List<Quaternion>> samples, Transform lightTransform,
            List<Vector3> lightPositions, Light point, List<float> lightIntensities,
            List<bool> lightEnabled, List<GameObject> effectPhases, List<int> effectPhaseFrames,
            List<Vector3> effectWorldPositions, List<Quaternion> effectWorldRotations,
            Camera camera, RenderTexture target, Texture2D readback, Renderer[] renderers,
            Vector3 focus, Vector3 towardCamera, Spec spec, string output, Report report)
        {
            var clip = new AnimationClip { name = "BeholderAttackContourV14",
                frameRate = 1000f / spec.gifFrameDurationMs, legacy = true, wrapMode = WrapMode.Once };
            float secondsPerFrame = spec.gifFrameDurationMs / 1000f;
            if (lightPositions.Count != spec.frames.Length || lightIntensities.Count != spec.frames.Length
                || lightEnabled.Count != spec.frames.Length || effectPhases.Count != effectPhaseFrames.Count
                || effectPhases.Count != effectWorldPositions.Count || effectPhases.Count != effectWorldRotations.Count
                || camera == null || target == null || readback == null || renderers == null)
                throw new InvalidOperationException("Incomplete emitter/light/effect clip samples");
            report.clipEffectPhaseCount = effectPhases.Count;
            foreach (Transform bone in bones)
            {
                string path = AnimationUtility.CalculateTransformPath(bone, root.transform);
                List<Quaternion> poses = samples[bone];
                if (poses.Count != spec.frames.Length)
                    throw new InvalidOperationException("Incomplete Unity clip samples: " + bone.name);
                for (int component = 0; component < 4; component++)
                {
                    string property = new[] { "m_LocalRotation.x", "m_LocalRotation.y",
                        "m_LocalRotation.z", "m_LocalRotation.w" }[component];
                    var keys = new Keyframe[poses.Count + 1];
                    for (int i = 0; i < poses.Count; i++)
                    {
                        Quaternion q = poses[i];
                        float value = component == 0 ? q.x : component == 1 ? q.y : component == 2 ? q.z : q.w;
                        keys[i] = new Keyframe(i * secondsPerFrame, value);
                    }
                    Quaternion lastPose = poses[poses.Count - 1];
                    float lastValue = component == 0 ? lastPose.x : component == 1 ? lastPose.y
                        : component == 2 ? lastPose.z : lastPose.w;
                    keys[keys.Length - 1] = new Keyframe(spec.frames.Length * secondsPerFrame, lastValue);
                    var curve = new AnimationCurve(keys);
                    for (int i = 0; i < keys.Length; i++)
                    {
                        AnimationUtility.SetKeyLeftTangentMode(curve, i, AnimationUtility.TangentMode.Linear);
                        AnimationUtility.SetKeyRightTangentMode(curve, i, AnimationUtility.TangentMode.Linear);
                    }
                    AnimationUtility.SetEditorCurve(clip,
                        EditorCurveBinding.FloatCurve(path, typeof(Transform), property), curve);
                }
            }
            string lightPath = AnimationUtility.CalculateTransformPath(lightTransform, root.transform);
            string lightEnabledPath = AnimationUtility.CalculateTransformPath(point.transform, root.transform);
            SetFloatCurve(clip, lightPath, typeof(Transform), "m_LocalPosition.x",
                lightPositions.Select(position => position.x).ToList(), secondsPerFrame, false);
            SetFloatCurve(clip, lightPath, typeof(Transform), "m_LocalPosition.y",
                lightPositions.Select(position => position.y).ToList(), secondsPerFrame, false);
            SetFloatCurve(clip, lightPath, typeof(Transform), "m_LocalPosition.z",
                lightPositions.Select(position => position.z).ToList(), secondsPerFrame, false);
            SetFloatCurve(clip, lightPath, typeof(Light), "m_Intensity", lightIntensities, secondsPerFrame, false);
            SetFloatCurve(clip, lightEnabledPath, typeof(Light), "m_Enabled",
                lightEnabled.Select(enabled => enabled ? 1f : 0f).ToList(), secondsPerFrame, true);
            for (int phaseIndex = 0; phaseIndex < effectPhases.Count; phaseIndex++)
            {
                GameObject phase = effectPhases[phaseIndex];
                string path = AnimationUtility.CalculateTransformPath(phase.transform, root.transform);
                var active = Enumerable.Range(0, spec.frames.Length)
                    .Select(frameIndex => effectPhaseFrames[phaseIndex] == frameIndex ? 1f : 0f).ToList();
                SetFloatCurve(clip, path, typeof(GameObject), "m_IsActive", active, secondsPerFrame, true);
            }
            const string folder = "Assets/Editor/BeholderAttackContourV14Generated";
            if (!AssetDatabase.IsValidFolder(folder))
                AssetDatabase.CreateFolder("Assets/Editor", "BeholderAttackContourV14Generated");
            string assetPath = folder + "/" + Path.GetFileName(output) + ".anim";
            if (AssetDatabase.LoadAssetAtPath<AnimationClip>(assetPath) != null)
                throw new IOException("Diagnostic clip asset already exists: " + assetPath);
            AssetDatabase.CreateAsset(clip, assetPath);
            AssetDatabase.SaveAssets();
            AnimationClip persisted = AssetDatabase.LoadAssetAtPath<AnimationClip>(assetPath);
            if (persisted == null)
                throw new IOException("Unity could not read back diagnostic clip: " + assetPath);
            float maxSampleAngle = 0f;
            for (int frame = 0; frame < spec.frames.Length; frame++)
            {
                persisted.SampleAnimation(root, frame * secondsPerFrame);
                foreach (Transform bone in bones)
                    maxSampleAngle = Mathf.Max(maxSampleAngle,
                        Quaternion.Angle(bone.localRotation, samples[bone][frame]));
                report.clipSampleMaxEmitterPositionDelta = Mathf.Max(report.clipSampleMaxEmitterPositionDelta,
                    Vector3.Distance(lightTransform.localPosition, lightPositions[frame]));
                report.clipSampleMaxLightIntensityError = Mathf.Max(report.clipSampleMaxLightIntensityError,
                    Mathf.Abs(point.intensity - lightIntensities[frame]));
                if (point.enabled != lightEnabled[frame])
                    report.clipPhaseActivationKeyErrors++;
                for (int phaseIndex = 0; phaseIndex < effectPhases.Count; phaseIndex++)
                {
                    bool active = effectPhaseFrames[phaseIndex] == frame;
                    GameObject phase = effectPhases[phaseIndex];
                    if (phase.activeSelf != active)
                        report.clipPhaseActivationKeyErrors++;
                    if (active)
                    {
                        report.clipActiveEffectPoseSamples++;
                        report.clipMaxActiveEffectPositionDelta = Mathf.Max(report.clipMaxActiveEffectPositionDelta,
                            Vector3.Distance(phase.transform.position, effectWorldPositions[phaseIndex]));
                        report.clipMaxActiveEffectRotationDelta = Mathf.Max(report.clipMaxActiveEffectRotationDelta,
                            Quaternion.Angle(phase.transform.rotation, effectWorldRotations[phaseIndex]));
                    }
                }
                Vector3 originalCameraPosition = camera.transform.position;
                Quaternion originalCameraRotation = camera.transform.rotation;
                bool[] rendererStates = renderers.Select(renderer => renderer.enabled).ToArray();
                try
                {
                    Capture(camera, target, readback, Path.Combine(output, "clip_effect", spec.frames[frame].name + ".png"));
                    foreach (Renderer renderer in renderers) renderer.enabled = false;
                    Capture(camera, target, readback, Path.Combine(output, "electricity_front", spec.frames[frame].name + ".png"));
                    for (int i = 0; i < renderers.Length; i++) renderers[i].enabled = rendererStates[i];
                    Vector3 obliqueDirection = Quaternion.AngleAxis(40f, Vector3.up) * towardCamera;
                    camera.transform.position = focus + obliqueDirection * 7f;
                    camera.transform.rotation = Quaternion.LookRotation(focus - camera.transform.position, Vector3.up);
                    Capture(camera, target, readback, Path.Combine(output, "oblique", spec.frames[frame].name + ".png"));
                }
                finally
                {
                    camera.transform.position = originalCameraPosition;
                    camera.transform.rotation = originalCameraRotation;
                    for (int i = 0; i < renderers.Length; i++) renderers[i].enabled = rendererStates[i];
                }
            }
            if (maxSampleAngle > 0.5f)
                throw new InvalidOperationException($"Persisted Unity clip differs from rendered poses by {maxSampleAngle:F3} degrees");
            report.clipSampleMaxAngleDegrees = maxSampleAngle;
            for (int frame = 0; frame < spec.frames.Length - 1; frame++)
            {
                persisted.SampleAnimation(root, (frame + 0.5f) * secondsPerFrame);
                report.clipBetweenKeySamples++;
                foreach (Transform bone in bones)
                {
                    float a = Quaternion.Angle(bone.localRotation, samples[bone][frame]);
                    float b = Quaternion.Angle(bone.localRotation, samples[bone][frame + 1]);
                    report.clipBetweenKeyMaxAngleDegrees = Mathf.Max(report.clipBetweenKeyMaxAngleDegrees,
                        Mathf.Max(a, b));
                    if (float.IsNaN(a) || float.IsNaN(b) || Mathf.Max(a, b) > 90f)
                        throw new InvalidOperationException("Unity clip has invalid between-key rotation: " + bone.name);
                }
                bool expectedLightEnabled = lightEnabled[frame];
                if (point.enabled != expectedLightEnabled)
                    report.clipPhaseActivationKeyErrors++;
                for (int phaseIndex = 0; phaseIndex < effectPhases.Count; phaseIndex++)
                    if (effectPhases[phaseIndex].activeSelf != (effectPhaseFrames[phaseIndex] == frame))
                        report.clipPhaseActivationKeyErrors++;
            }
            if (report.clipSampleMaxEmitterPositionDelta > 0.001f
                || report.clipSampleMaxLightIntensityError > 0.001f || report.clipPhaseActivationKeyErrors != 0
                || report.clipActiveEffectPoseSamples != effectPhases.Count
                || report.clipMaxActiveEffectPositionDelta > 0.001f
                || report.clipMaxActiveEffectRotationDelta > 0.5f)
                throw new InvalidOperationException("Persisted Unity clip failed emitter, light, or effect-phase round trip");
            string sourceFile = Path.Combine(Application.dataPath, "Editor", "BeholderAttackContourV14Generated",
                Path.GetFileName(output) + ".anim");
            string copyFile = Path.Combine(output, "beholder_v14.anim");
            File.Copy(sourceFile, copyFile, false);
            using (var sha = SHA256.Create())
                report.clipSha256 = BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(copyFile)))
                    .Replace("-", "").ToLowerInvariant();
            report.clipUnityAssetPath = assetPath;
            report.clipArtifactPath = copyFile;
        }

        private static void SetFloatCurve(AnimationClip clip, string path, Type type, string property,
            List<float> values, float secondsPerFrame, bool step)
        {
            if (values == null || values.Count == 0)
                throw new InvalidOperationException("Missing Unity clip values: " + property);
            var keys = new Keyframe[values.Count + 1];
            for (int i = 0; i < values.Count; i++) keys[i] = new Keyframe(i * secondsPerFrame, values[i]);
            keys[keys.Length - 1] = new Keyframe(values.Count * secondsPerFrame, values[values.Count - 1]);
            var curve = new AnimationCurve(keys);
            for (int i = 0; i < keys.Length; i++)
            {
                AnimationUtility.SetKeyLeftTangentMode(curve, i,
                    step ? AnimationUtility.TangentMode.Constant : AnimationUtility.TangentMode.Linear);
                AnimationUtility.SetKeyRightTangentMode(curve, i,
                    step ? AnimationUtility.TangentMode.Constant : AnimationUtility.TangentMode.Linear);
            }
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, type, property), curve);
        }

        private static FrameResult Measure(FrameSpec frame, ChainResult[] chains, Color32[] baseline,
            Color32[] mask, Color32[] lit, Color32[] effect)
        {
            FrameResult result = new FrameResult { name = frame.name, sourceSha256 = frame.sourceSha256,
                cropSha256 = frame.cropSha256, chains = chains };
            for (int i = 0; i < baseline.Length; i++)
            {
                if (baseline[i].r > 240 && baseline[i].g < 24 && baseline[i].b > 240)
                    result.magentaFailurePixels++;
                bool onMesh = mask[i].r > 190 && mask[i].g > 190 && mask[i].b > 190;
                if (onMesh)
                {
                    result.meshMaskPixels++;
                    int delta = Math.Abs(lit[i].r - baseline[i].r) + Math.Abs(lit[i].g - baseline[i].g)
                        + Math.Abs(lit[i].b - baseline[i].b);
                    if (delta > 12) result.meshLightingChangedPixels++;
                    int baseLum = 54 * baseline[i].r + 183 * baseline[i].g + 19 * baseline[i].b;
                    int litLum = 54 * lit[i].r + 183 * lit[i].g + 19 * lit[i].b;
                    if (litLum > baseLum + 12 * 256) result.meshBrightenedPixels++;
                }
                if (effect[i].r > lit[i].r + 30 && effect[i].g > lit[i].g + 30
                    && effect[i].b > lit[i].b + 30) result.coreVisiblePixels++;
            }
            return result;
        }

        private static Vector2 ProjectSource(Vector3 position, Spec spec, Vector3 right)
        {
            return new Vector2(spec.sourceBodyX + Vector3.Dot(position, right) * spec.pixelsPerUnit,
                spec.sourceGroundY - position.y * spec.pixelsPerUnit);
        }

        private static void SolveContour(Transform[] chain, ContourKnot[] knots, Spec spec,
            Vector3 right, Vector3 towardCamera)
        {
            int count = chain.Length;
            if (knots[0].jointIndex != 0 || knots[knots.Length - 1].jointIndex != count - 1)
                throw new InvalidOperationException("Contour does not span the full chain: " + chain[0].name);
            Vector3[] p = chain.Select(b => b.position).ToArray();
            Vector3[] original = (Vector3[])p.Clone();
            float[] lengths = new float[count - 1];
            for (int i = 0; i < lengths.Length; i++) lengths[i] = Vector3.Distance(p[i], p[i + 1]);
            Vector3[] goals = new Vector3[count];
            float[] weights = new float[count];
            for (int segment = 0; segment < knots.Length - 1; segment++)
            {
                ContourKnot a = knots[segment], b = knots[segment + 1];
                if (b.jointIndex <= a.jointIndex)
                    throw new InvalidOperationException("Contour joint indices are not increasing: " + chain[0].name);
                for (int i = a.jointIndex; i <= b.jointIndex; i++)
                {
                    float t = (i - a.jointIndex) / (float)(b.jointIndex - a.jointIndex);
                    Tip interpolated = new Tip { x = Mathf.Lerp(a.point.x, b.point.x, t),
                        y = Mathf.Lerp(a.point.y, b.point.y, t) };
                    goals[i] = SourcePoint(interpolated, original[i], spec, right, towardCamera);
                    weights[i] = i == a.jointIndex && a.sourceVisible || i == b.jointIndex && b.sourceVisible
                        ? 0.42f : 0.18f;
                }
            }
            Vector3 basePosition = p[0];
            for (int iteration = 0; iteration < 96; iteration++)
            {
                for (int i = 1; i < count; i++) p[i] = Vector3.Lerp(p[i], goals[i], weights[i]);
                for (int i = count - 2; i >= 1; i--)
                {
                    Vector3 delta = p[i] - p[i + 1];
                    if (delta.sqrMagnitude > 1e-8f) p[i] = p[i + 1] + delta.normalized * lengths[i];
                }
                p[0] = basePosition;
                for (int i = 1; i < count; i++)
                {
                    Vector3 delta = p[i] - p[i - 1];
                    if (delta.sqrMagnitude > 1e-8f) p[i] = p[i - 1] + delta.normalized * lengths[i - 1];
                    float depth = Vector3.Dot(p[i] - original[i], towardCamera);
                    p[i] -= towardCamera * Mathf.Clamp(depth, -0.45f, 0.45f) * 0.04f;
                }
            }
            for (int i = 0; i < count - 1; i++)
            {
                Vector3 current = chain[i + 1].position - chain[i].position;
                Vector3 wanted = p[i + 1] - p[i];
                if (current.sqrMagnitude > 1e-8f && wanted.sqrMagnitude > 1e-8f)
                    chain[i].rotation = Quaternion.FromToRotation(current, wanted) * chain[i].rotation;
            }
        }

        private static void BuildEmitterSurface(Mesh mesh, FrameSpec frame, Spec spec,
            Color32[] sourcePixels, int width, int height)
        {
            var vertices = new List<Vector3>();
            var uv = new List<Vector2>();
            var triangles = new List<int>();
            float halfPixel = 0.5f / spec.pixelsPerUnit;
            const float halfThickness = 0.014f;
            for (int y = 0; y < height; y++)
            for (int x = 0; x < width; x++)
            {
                Color32 pixel = sourcePixels[(height - 1 - y) * width + x];
                if (pixel.a < 128) continue;
                float nx = (x + 0.5f) / Mathf.Max(1, width - 1);
                float ny = (y + 0.5f) / Mathf.Max(1, height - 1);
                float phase = 2f * Mathf.PI * ny + 1.3f * nx;
                float foldedDepth = 0.07f * Mathf.Sin(Mathf.PI * nx)
                    + 0.035f * Mathf.Sin(phase) + 0.02f * Mathf.Sin(3f * Mathf.PI * nx - 2f * ny);
                float centerX = (frame.x0 + x + 0.5f - frame.emitterSource.x) / spec.pixelsPerUnit;
                float centerY = (frame.emitterSource.y - frame.y0 - y - 0.5f) / spec.pixelsPerUnit;
                float left = centerX - halfPixel, right = centerX + halfPixel;
                float bottom = centerY - halfPixel, top = centerY + halfPixel;
                float front = -foldedDepth - halfThickness;
                float back = -foldedDepth + halfThickness;
                Vector2 uvBL = new Vector2(x / (float)width, 1f - (y + 1) / (float)height);
                Vector2 uvBR = new Vector2((x + 1) / (float)width, uvBL.y);
                Vector2 uvTR = new Vector2(uvBR.x, 1f - y / (float)height);
                Vector2 uvTL = new Vector2(uvBL.x, uvTR.y);
                Vector3 bl = new Vector3(left, bottom, front);
                Vector3 br = new Vector3(right, bottom, front);
                Vector3 tr = new Vector3(right, top, front);
                Vector3 tl = new Vector3(left, top, front);
                AddPixelFace(vertices, uv, triangles, bl, br, tr, tl, uvBL, uvBR, uvTR, uvTL, true);
                bl.z = br.z = tr.z = tl.z = back;
                AddPixelFace(vertices, uv, triangles, bl, br, tr, tl, uvBL, uvBR, uvTR, uvTL, false);
                Vector3 fbl = new Vector3(left, bottom, front), fbr = new Vector3(right, bottom, front);
                Vector3 ftr = new Vector3(right, top, front), ftl = new Vector3(left, top, front);
                Vector3 bbl = new Vector3(left, bottom, back), bbr = new Vector3(right, bottom, back);
                Vector3 btr = new Vector3(right, top, back), btl = new Vector3(left, top, back);
                AddPixelFace(vertices, uv, triangles, fbl, fbr, bbr, bbl, uvBL, uvBR, uvBR, uvBL, false);
                AddPixelFace(vertices, uv, triangles, fbr, ftr, btr, bbr, uvBR, uvTR, uvTR, uvBR, false);
                AddPixelFace(vertices, uv, triangles, ftr, ftl, btl, btr, uvTR, uvTL, uvTL, uvTR, false);
                AddPixelFace(vertices, uv, triangles, ftl, fbl, bbl, btl, uvTL, uvBL, uvBL, uvTL, false);
            }
            mesh.Clear();
            mesh.SetVertices(vertices);
            mesh.SetUVs(0, uv);
            mesh.SetTriangles(triangles, 0, true);
            mesh.RecalculateNormals();
        }

        private static void AddPixelFace(List<Vector3> vertices, List<Vector2> uv, List<int> triangles,
            Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector2 ua, Vector2 ub, Vector2 uc, Vector2 ud,
            bool frontWinding)
        {
            int first = vertices.Count;
            vertices.Add(a); vertices.Add(b); vertices.Add(c); vertices.Add(d);
            uv.Add(ua); uv.Add(ub); uv.Add(uc); uv.Add(ud);
            if (frontWinding)
            {
                triangles.Add(first); triangles.Add(first + 2); triangles.Add(first + 1);
                triangles.Add(first); triangles.Add(first + 3); triangles.Add(first + 2);
            }
            else
            {
                triangles.Add(first); triangles.Add(first + 1); triangles.Add(first + 2);
                triangles.Add(first); triangles.Add(first + 2); triangles.Add(first + 3);
            }
        }

        // GLTFast can await jobs even with UninterruptedDeferAgent. Blocking GetResult
        // on the Editor main thread deadlocks those captured continuations in batch mode.
        private sealed class GltfMainThreadPump : SynchronizationContext
        {
            private readonly Queue<Action> pending = new Queue<Action>();
            private readonly int mainThreadId = Thread.CurrentThread.ManagedThreadId;

            public override void Post(SendOrPostCallback callback, object state)
            {
                lock (pending) pending.Enqueue(() => callback(state));
            }

            public override void Send(SendOrPostCallback callback, object state)
            {
                if (Thread.CurrentThread.ManagedThreadId != mainThreadId)
                    throw new InvalidOperationException("GLTFast attempted cross-thread Unity API dispatch");
                callback(state);
            }

            public void DrainUntil(Task task)
            {
                var timer = System.Diagnostics.Stopwatch.StartNew();
                while (!task.IsCompleted)
                {
                    if (timer.Elapsed.TotalSeconds > 120)
                        throw new TimeoutException("GLTFast main-thread continuation pump exceeded 120 seconds");
                    Action next = null;
                    lock (pending) if (pending.Count > 0) next = pending.Dequeue();
                    if (next != null) next();
                    else Thread.Sleep(1);
                }
            }
        }

        private static bool RunGltfTask(Func<Task<bool>> work)
        {
            SynchronizationContext previous = SynchronizationContext.Current;
            var pump = new GltfMainThreadPump();
            try
            {
                SynchronizationContext.SetSynchronizationContext(pump);
                Task<bool> task = work();
                pump.DrainUntil(task);
                return task.GetAwaiter().GetResult();
            }
            finally { SynchronizationContext.SetSynchronizationContext(previous); }
        }

        private static Vector3 SourcePoint(Tip point, Vector3 depthReference, Spec spec,
            Vector3 right, Vector3 towardCamera)
        {
            return right * ((point.x - spec.sourceBodyX) / spec.pixelsPerUnit)
                + Vector3.up * ((spec.sourceGroundY - point.y) / spec.pixelsPerUnit)
                + towardCamera * Vector3.Dot(depthReference, towardCamera);
        }

        private static void ApplyLitMaterials(Renderer[] renderers, List<UnityEngine.Object> owned)
        {
            Shader shader = RequiredShader("Standard");
            foreach (Renderer renderer in renderers)
            {
                Material[] materials = renderer.sharedMaterials;
                for (int i = 0; i < materials.Length; i++)
                {
                    Material source = materials[i];
                    if (source == null) throw new InvalidOperationException("GLTFast material missing");
                    Material replacement = new Material(shader) { name = source.name + " (Beholder diagnostic lit)" };
                    Texture texture = source.HasProperty("_BaseMap") ? source.GetTexture("_BaseMap") : source.mainTexture;
                    if (texture != null) replacement.mainTexture = texture;
                    replacement.color = source.HasProperty("_BaseColor")
                        ? source.GetColor("_BaseColor") : Color.white;
                    replacement.SetFloat("_Metallic", 0f);
                    replacement.SetFloat("_Glossiness", 0.12f);
                    materials[i] = replacement;
                    owned.Add(replacement);
                }
                renderer.sharedMaterials = materials;
            }
        }

        private static void SwapMaterials(Renderer[] renderers, Material[][] materials)
        {
            for (int i = 0; i < renderers.Length; i++) renderers[i].sharedMaterials = materials[i];
        }

        private static Color32[] Capture(Camera camera, RenderTexture target, Texture2D readback, string path)
        {
            camera.Render();
            RenderTexture previous = RenderTexture.active;
            try
            {
                RenderTexture.active = target;
                readback.ReadPixels(new Rect(0, 0, target.width, target.height), 0, 0, false);
                readback.Apply(false, false);
                File.WriteAllBytes(path, readback.EncodeToPNG());
                return readback.GetPixels32();
            }
            finally { RenderTexture.active = previous; }
        }

        private static Transform FindUnique(GameObject root, string name)
        {
            Transform[] matches = root.GetComponentsInChildren<Transform>(true).Where(t => t.name == name).ToArray();
            if (matches.Length != 1) throw new InvalidOperationException("Expected exactly one GLB joint " + name);
            return matches[0];
        }

        private static Shader RequiredShader(string name)
        {
            Shader shader = Shader.Find(name);
            if (shader == null || !shader.isSupported)
                throw new InvalidOperationException("Required preview shader unavailable/unsupported: " + name);
            Debug.Log("BeholderAttackRepairSolV1 shader supported: " + name);
            return shader;
        }

        private static void SetLayer(Transform node)
        {
            node.gameObject.layer = PreviewLayer;
            foreach (Transform child in node) SetLayer(child);
        }

        private static string Argument(string name)
        {
            string[] args = UnityQueueArgs();
            for (int i = 0; i + 1 < args.Length; i++) if (args[i] == name) return args[i + 1];
            return null;
        }
    }
}
