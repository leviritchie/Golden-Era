// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/volfire_unity_lab.py. Editor-only lab; NOT a delivery path.
// Volumetric fire preview (unit-look layer `volumetricFire`, tools/homm3_unit_look/volfire.py): the def_retarget GLB
// under the lab Hex/Lit replica (look base colour or the uvAtlas boil, stepped per key, + the floor point light),
// plus one native ParticleSystem per fire system, configured from the layer's manifest entry:
//   shape      SkinnedMeshRenderer over an emitter-only skinned submesh (the body triangles whose UV centroid lies
//              in the emitter mask), forceRenderingOff, sharing the body's bones
//   renderer   Billboard, alignment View, sortMode Distance, Sprites/Default (unlit, alpha blend), point filter
//   sheet      Grid, SingleRow, random row, timeMode FPS 12, random start frame
//   emission   rateOverTime x the clip's per-key multiplier; World simulation space
// Clips are simulated continuously at 60 Hz (the skinned pose sampled every step, so emission follows the motion)
// and rendered through the unit's SpriteCam at the DEF key times (i+1)/12; a turntable orbits the camera around
// the idle loop. Variants: "look" (no particles) and "fire".
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace OldenEra.Homm3Vfx
{
    public static class Homm3VolumetricFireLab
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

        [Serializable] private sealed class Clip { public string name; public int keys; public int[] boilCells; public float[] mult; public float lightFloor; public int clearAtKey = -1; }
        [Serializable]
        private sealed class Sys
        {
            public string name, sheet;
            public int tilesX, tilesY;
            public float sizeX, sizeY, sizeJitter, lifeMin, lifeMax, rate, rise, spread, normalOffset, hLo, hHi, minUp;
            public int expectTriangles;
        }
        [Serializable]
        private sealed class Spec
        {
            public string schema, assetRoot, glbAssetPath, basecolor, boilAtlas, emitterMask, anchorBone, lightBone, outDir;
            public float[] cellST;
            public Clip[] clips;
            public Sys[] systems;
            public float emitterThreshold, lightTowardCamera, lightRange, warmupS;
            public float[] restYRange;
            public string[] emitterBones, emitterExcludeBones;
            public float[] lightRgbLinear;
            public float[] camRight, camUp, camForward, offset, sunTravelUnity;
            public int[] size;
            public float pxPerUnit;
            public int scale;
            public string turntableClip;
            public int turntableFrames;
            public float turntableDegPerFrame, turntablePitchDeg;
            public string[] variants, renderClips;
        }

        private static readonly StringBuilder Report = new StringBuilder();

        public static void RunFromCommandLine()
        {
            string[] args = UnityQueueArgs();
            string specPath = null;
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == "-homm3VolfireSpec") specPath = args[i + 1];
            if (string.IsNullOrEmpty(specPath) || !File.Exists(specPath))
                throw new InvalidOperationException("-homm3VolfireSpec <file> is required");
            Spec spec = JsonUtility.FromJson<Spec>(File.ReadAllText(specPath));
            if (spec.schema != "homm3_volfire_lab.v1") throw new InvalidOperationException("schema " + spec.schema);
            Run(spec);
            Debug.Log("HOMM3_VOLFIRE_LAB_OK");
        }

        private static void Log(string key, string json)
        {
            Report.Append(Report.Length == 0 ? "{\n" : ",\n").Append(" \"").Append(key).Append("\": ").Append(json);
            Debug.Log("HOMM3_VOLFIRE " + key + " " + (json.Length > 400 ? json.Substring(0, 400) + "..." : json));
        }

        private static Vector3 B2U(float[] b) => new Vector3(-b[0], b[2], -b[1]);

        private static void Run(Spec spec)
        {
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            string R(string n) => spec.assetRoot + "/" + n;
            Shader bodyShader = AssetDatabase.LoadAssetAtPath<Shader>("Assets/Homm3VfxLab/Shaders/Homm3VfxHexLitReplicaPoint.shader");   // staged by titan_light_lab.py
            if (bodyShader == null) throw new InvalidOperationException("lab body shader missing");
            Texture2D basecolor = ImportTexture(R(spec.basecolor), true, false);
            Texture2D boil = string.IsNullOrEmpty(spec.boilAtlas) ? null : ImportTexture(R(spec.boilAtlas), true, false);
            GameObject glb = AssetDatabase.LoadAssetAtPath<GameObject>(spec.glbAssetPath);
            if (glb == null) throw new InvalidOperationException("GLB did not import: " + spec.glbAssetPath);
            AnimationClip[] glbClips = AssetDatabase.LoadAllAssetsAtPath(spec.glbAssetPath).OfType<AnimationClip>().ToArray();

            GameObject go = UnityEngine.Object.Instantiate(glb);
            go.name = "unit";
            foreach (Animation legacy in go.GetComponentsInChildren<Animation>(true)) UnityEngine.Object.DestroyImmediate(legacy);
            SkinnedMeshRenderer[] skins = go.GetComponentsInChildren<SkinnedMeshRenderer>(true);
            SkinnedMeshRenderer body = skins.Where(s => !s.name.EndsWith("_Rubble")).OrderByDescending(s => s.sharedMesh.vertexCount).First();
            var sun = new Vector4(spec.sunTravelUnity[0], spec.sunTravelUnity[1], spec.sunTravelUnity[2], 0);
            var mats = new List<Material>();
            foreach (SkinnedMeshRenderer s in skins)
            {
                s.forceMatrixRecalculationPerRender = true;
                s.updateWhenOffscreen = true;
                var m = new Material(bodyShader) { mainTexture = s == body && boil != null ? boil : basecolor };
                m.SetVector("_SunDir", sun);
                s.sharedMaterial = m;
                mats.Add(m);
            }
            Material bodyMat = body.sharedMaterial;
            Log("renderers", "[" + string.Join(", ", skins.Select(s => "\"" + s.name + "\"")) + "]");

            // animator with generic copies of the GLB clips
            Animator animator = go.GetComponent<Animator>() ?? go.AddComponent<Animator>();
            animator.applyRootMotion = false;
            animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            string clipRoot = spec.assetRoot + "/clips";
            if (!AssetDatabase.IsValidFolder(clipRoot)) AssetDatabase.CreateFolder(spec.assetRoot, "clips");
            string ctrlPath = clipRoot + "/volfire.controller";
            AssetDatabase.DeleteAsset(ctrlPath);
            AnimatorController ctrl = AnimatorController.CreateAnimatorControllerAtPath(ctrlPath);
            var lengths = new Dictionary<string, float>();
            foreach (Clip c in spec.clips)
            {
                AnimationClip src = glbClips.FirstOrDefault(x => x.name == c.name || x.name.EndsWith(c.name, StringComparison.Ordinal));
                if (src == null) throw new InvalidOperationException("clip " + c.name + " missing; found " + string.Join(",", glbClips.Select(x => x.name)));
                var copy = new AnimationClip { name = "vf_" + c.name, frameRate = src.frameRate, legacy = false };
                foreach (EditorCurveBinding b in AnimationUtility.GetCurveBindings(src))
                    AnimationUtility.SetEditorCurve(copy, b, AnimationUtility.GetEditorCurve(src, b));
                copy.EnsureQuaternionContinuity();
                string cp = clipRoot + "/" + copy.name + ".anim";
                AssetDatabase.DeleteAsset(cp);
                AssetDatabase.CreateAsset(copy, cp);
                AnimatorState st = ctrl.AddMotion(copy);
                st.name = c.name;
                lengths[c.name] = copy.length;
            }
            AssetDatabase.SaveAssets();
            animator.runtimeAnimatorController = ctrl;
            animator.Rebind();

            // emitter-only skinned submeshes, one per system: triangles whose UV centroid's nearest mask texel >= threshold,
            // then the system's height range (centroid y over the rest centroid-y range) and min normal-up (volfire.py rule)
            var maskTex = new Texture2D(2, 2);
            if (!maskTex.LoadImage(File.ReadAllBytes(Path.Combine(Application.dataPath, "..", R(spec.emitterMask)))))
                throw new InvalidOperationException("emitter mask did not load");
            Mesh src0 = body.sharedMesh;
            Vector2[] uv = src0.uv;
            Vector3[] vtx = src0.vertices, nrm = src0.normals;
            float y0 = spec.restYRange[0], y1 = spec.restYRange[1];
            // bones emitter: per-vertex (weight on joints matching emitterBones - weight on emitterExcludeBones), clipped
            float[] vw = null;
            bool useBones = (spec.emitterBones != null && spec.emitterBones.Length > 0) || (spec.emitterExcludeBones != null && spec.emitterExcludeBones.Length > 0);
            if (useBones)
            {
                System.Text.RegularExpressions.Regex G(string[] globs) => new System.Text.RegularExpressions.Regex("^(" + string.Join("|",
                    globs.Select(g => System.Text.RegularExpressions.Regex.Escape(g).Replace(@"\*", ".*").Replace(@"\?", "."))) + ")$");
                var inc = G(spec.emitterBones != null && spec.emitterBones.Length > 0 ? spec.emitterBones : new[] { "*" });
                var exc = spec.emitterExcludeBones != null && spec.emitterExcludeBones.Length > 0 ? G(spec.emitterExcludeBones) : null;
                float[] bsel = body.bones.Select(b => b != null && inc.IsMatch(b.name) ? 1f : 0f).ToArray();
                float[] bexc = body.bones.Select(b => b != null && exc != null && exc.IsMatch(b.name) ? 1f : 0f).ToArray();
                BoneWeight[] bw = src0.boneWeights;
                vw = new float[bw.Length];
                for (int v = 0; v < bw.Length; v++)
                {
                    BoneWeight w = bw[v];
                    float a = w.weight0 * bsel[w.boneIndex0] + w.weight1 * bsel[w.boneIndex1] + w.weight2 * bsel[w.boneIndex2] + w.weight3 * bsel[w.boneIndex3];
                    float e = w.weight0 * bexc[w.boneIndex0] + w.weight1 * bexc[w.boneIndex1] + w.weight2 * bexc[w.boneIndex2] + w.weight3 * bexc[w.boneIndex3];
                    vw[v] = Mathf.Clamp01(a - e);
                }
            }
            SkinnedMeshRenderer Emitter(Sys s)
            {
                Mesh em = UnityEngine.Object.Instantiate(src0);
                em.name = src0.name + "_emit_" + s.name;
                var tris = new List<int>();
                for (int sub = 0; sub < src0.subMeshCount; sub++)
                {
                    int[] t = src0.GetTriangles(sub);
                    for (int i = 0; i < t.Length; i += 3)
                    {
                        if (vw != null)
                        {
                            if ((vw[t[i]] + vw[t[i + 1]] + vw[t[i + 2]]) / 3f < spec.emitterThreshold) continue;
                        }
                        else
                        {
                            Vector2 c = (uv[t[i]] + uv[t[i + 1]] + uv[t[i + 2]]) / 3f;
                            int px = Mathf.Clamp((int)(c.x * maskTex.width), 0, maskTex.width - 1);
                            int py = Mathf.Clamp(maskTex.height - 1 - (int)((1f - c.y) * maskTex.height), 0, maskTex.height - 1);
                            if (maskTex.GetPixel(px, py).r < spec.emitterThreshold - 1e-3f) continue;
                        }
                        float h = ((vtx[t[i]].y + vtx[t[i + 1]].y + vtx[t[i + 2]].y) / 3f - y0) / Mathf.Max(y1 - y0, 1e-6f);
                        if (h < s.hLo || h > s.hHi) continue;
                        Vector3 n = nrm[t[i]] + nrm[t[i + 1]] + nrm[t[i + 2]];
                        if (n.normalized.y < s.minUp) continue;
                        tris.Add(t[i]); tris.Add(t[i + 1]); tris.Add(t[i + 2]);
                    }
                }
                em.subMeshCount = 1;
                em.SetTriangles(tris, 0);
                int got = tris.Count / 3;
                Log("emitter_" + s.name, "{\"triangles\": " + got + ", \"expected\": " + s.expectTriangles + "}");
                if (Mathf.Abs(got - s.expectTriangles) > 0.03f * Mathf.Max(s.expectTriangles, 1))
                    throw new InvalidOperationException("emitter " + s.name + " selects " + got + " triangles; volfire.py selected " + s.expectTriangles);
                var emGo = new GameObject("fire_emitter_" + s.name);
                emGo.transform.SetParent(body.transform.parent, false);
                emGo.transform.localPosition = body.transform.localPosition;
                emGo.transform.localRotation = body.transform.localRotation;
                emGo.transform.localScale = body.transform.localScale;
                var emSkin = emGo.AddComponent<SkinnedMeshRenderer>();
                emSkin.sharedMesh = em;
                emSkin.bones = body.bones;
                emSkin.rootBone = body.rootBone;
                emSkin.updateWhenOffscreen = true;
                emSkin.forceMatrixRecalculationPerRender = true;
                emSkin.sharedMaterial = bodyMat;
                emSkin.forceRenderingOff = true;
                return emSkin;
            }

            Transform anchor = go.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == spec.anchorBone);
            Transform lightBone = go.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == spec.lightBone);
            if (anchor == null || lightBone == null) throw new InvalidOperationException("anchor / light bone missing");
            var systems = new List<(Sys s, ParticleSystem ps)>();
            int seed = 101;
            foreach (Sys s in spec.systems)
            {
                var child = new GameObject("fire_" + s.name);
                child.transform.SetParent(anchor, false);
                var ps = child.AddComponent<ParticleSystem>();
                Configure(ps, child.GetComponent<ParticleSystemRenderer>(), s, SheetMaterial(R(s.sheet), s.name), Emitter(s), seed++);
                systems.Add((s, ps));
            }

            // cameras
            float ppu = spec.pxPerUnit;
            Vector3 right = B2U(spec.camRight), up = B2U(spec.camUp), fwd = B2U(spec.camForward);
            int W = spec.size[0] * spec.scale, H = spec.size[1] * spec.scale;
            Vector3 centre = right * ((spec.size[0] * 0.5f - spec.offset[0]) / ppu) + up * ((spec.offset[1] - spec.size[1] * 0.5f) / ppu);
            Camera cam = new GameObject("SpriteCam").AddComponent<Camera>();
            cam.orthographic = true;
            cam.orthographicSize = (spec.size[1] * 0.5f) / ppu;
            cam.nearClipPlane = 0.1f; cam.farClipPlane = 60f;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0, 0, 0, 0);
            cam.allowMSAA = false;
            var rt = new RenderTexture(W, H, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB) { antiAliasing = 1 };
            cam.targetTexture = rt;
            var read = new Texture2D(W, H, TextureFormat.RGBA32, false);
            void SetSpriteCam() => cam.transform.SetPositionAndRotation(centre - fwd * 20f, Quaternion.LookRotation(fwd, up));

            var counts = new List<string>();
            void Pose(Clip c, float tau)
            {
                float len = Mathf.Max(lengths[c.name], 1e-4f);
                float t = c.name == spec.turntableClip ? Mathf.Repeat(tau, len) : Mathf.Clamp(tau, 0f, len);
                animator.Play(c.name, 0, t / len);
                animator.Update(0f);
                int key = Mathf.Clamp(Mathf.FloorToInt(Mathf.Max(tau, 0f) * 12f - 0.5f), 0, c.keys - 1);
                if (boil != null && c.boilCells != null && c.boilCells.Length > 0)
                {
                    int cell = c.boilCells[Mathf.Clamp(key, 0, c.boilCells.Length - 1)];
                    bodyMat.SetVector("_MainTex_ST", new Vector4(spec.cellST[cell * 4], spec.cellST[cell * 4 + 1], spec.cellST[cell * 4 + 2], spec.cellST[cell * 4 + 3]));
                }
                foreach (var (s, ps) in systems)
                {
                    var e = ps.emission;
                    e.rateOverTimeMultiplier = s.rate * c.mult[Mathf.Clamp(key, 0, c.mult.Length - 1)];
                }
            }
            void Light(Clip c)
            {
                Vector3 p = lightBone.position - cam.transform.forward * spec.lightTowardCamera;
                var col = new Vector4(spec.lightRgbLinear[0], spec.lightRgbLinear[1], spec.lightRgbLinear[2], 0) * c.lightFloor;
                foreach (Material m in mats)
                {
                    m.SetFloat("_PLCount", c.lightFloor > 0 ? 1 : 0);
                    m.SetVectorArray("_PLPos", new[] { (Vector4)p, Vector4.zero, Vector4.zero, Vector4.zero });
                    m.SetVectorArray("_PLCol", new[] { col, Vector4.zero, Vector4.zero, Vector4.zero });
                    m.SetFloatArray("_PLInvRange2", new[] { 1f / (spec.lightRange * spec.lightRange), 0, 0, 0 });
                }
            }
            void Shoot(string dir, string file, bool fire)
            {
                foreach (var (s, ps) in systems) ps.GetComponent<ParticleSystemRenderer>().enabled = fire;
                cam.Render();
                RenderTexture.active = rt;
                read.ReadPixels(new Rect(0, 0, W, H), 0, 0);
                read.Apply();
                RenderTexture.active = null;
                string d = Path.Combine(spec.outDir, dir);
                Directory.CreateDirectory(d);
                File.WriteAllBytes(Path.Combine(d, file), read.EncodeToPNG());
            }
            void Restart()
            {
                foreach (var (s, ps) in systems) { ps.Clear(true); ps.Simulate(0f, false, true, false); }
            }
            void Step(float dt)
            {
                foreach (var (s, ps) in systems) ps.Simulate(dt, false, false, false);
            }
            const float DT = 1f / 60f;
            bool wantLook = spec.variants.Contains("look"), wantFire = spec.variants.Contains("fire");
            int renders = 0;

            foreach (string cn in spec.renderClips)
            {
                Clip c = spec.clips.First(x => x.name == cn);
                SetSpriteCam();
                Restart();
                bool cleared = false;
                float tau = -spec.warmupS;
                for (int i = 0; i < c.keys; i++)
                {
                    float tk = (i + 1) / 12f;
                    while (tau < tk - 1e-5f)
                    {
                        Pose(c, tau); Step(DT); tau += DT;
                        if (c.clearAtKey >= 0 && !cleared && tau >= (c.clearAtKey + 0.5f) / 12f)
                        { foreach (var (s2, ps2) in systems) ps2.Clear(false); cleared = true; }
                    }
                    Pose(c, tk);
                    Light(c);
                    string file = c.name + "_" + i.ToString("00") + ".png";
                    if (wantLook) { Shoot("look", file, false); renders++; }
                    if (wantFire) { Shoot("fire", file, true); renders++; }
                    counts.Add("{\"clip\": \"" + c.name + "\", \"key\": " + i + ", \"live\": [" + string.Join(", ", systems.Select(x => x.ps.particleCount)) + "]}");
                }
            }

            // turntable: the camera orbits the unit (SpriteCam pitch) while the idle loop plays
            if (spec.turntableFrames > 0)
            {
                Clip c = spec.clips.First(x => x.name == spec.turntableClip);
                Vector3 pivot = go.transform.position + Vector3.up * 0.6f;
                float pitch = spec.turntablePitchDeg;
                Restart();
                float tau = -spec.warmupS;
                for (int f = 0; f < spec.turntableFrames; f++)
                {
                    float tk = (f + 1) / 12f;
                    while (tau < tk - 1e-5f) { Pose(c, tau); Step(DT); tau += DT; }
                    Pose(c, tk);
                    Quaternion rot = Quaternion.Euler(pitch, f * spec.turntableDegPerFrame, 0f);
                    cam.transform.SetPositionAndRotation(pivot - rot * Vector3.forward * 20f, rot);
                    Light(c);
                    string file = "tt_" + f.ToString("000") + ".png";
                    if (wantLook) { Shoot("turntable_look", file, false); renders++; }
                    if (wantFire) { Shoot("turntable_fire", file, true); renders++; }
                }
            }
            Log("live", "[\n  " + string.Join(",\n  ", counts) + "\n ]");
            Log("renders", renders.ToString());
            File.WriteAllText(Path.Combine(spec.outDir, "lab_report.json"), Report.ToString() + "\n}\n");
        }

        private static void Configure(ParticleSystem ps, ParticleSystemRenderer r, Sys s, Material mat, SkinnedMeshRenderer emitter, int seed)
        {
            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            ps.useAutoRandomSeed = false;
            ps.randomSeed = (uint)seed;
            var main = ps.main;
            main.duration = 1f;
            main.loop = true;
            main.playOnAwake = false;
            main.startLifetime = new ParticleSystem.MinMaxCurve(s.lifeMin, s.lifeMax);
            main.startSpeed = 0f;
            main.startSize3D = true;
            main.startSizeX = new ParticleSystem.MinMaxCurve(s.sizeX * (1 - s.sizeJitter), s.sizeX * (1 + s.sizeJitter));
            main.startSizeY = new ParticleSystem.MinMaxCurve(s.sizeY * (1 - s.sizeJitter), s.sizeY * (1 + s.sizeJitter));
            main.startSizeZ = 1f;
            main.startRotation = 0f;
            main.startColor = Color.white;
            main.gravityModifier = 0f;
            main.maxParticles = 2000;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.scalingMode = ParticleSystemScalingMode.Hierarchy;

            var emission = ps.emission;
            emission.enabled = true;
            emission.rateOverTime = s.rate;

            var shape = ps.shape;
            shape.enabled = true;
            shape.shapeType = ParticleSystemShapeType.SkinnedMeshRenderer;
            shape.skinnedMeshRenderer = emitter;
            shape.meshShapeType = ParticleSystemMeshShapeType.Triangle;
            shape.normalOffset = s.normalOffset;
            shape.alignToDirection = false;

            var vel = ps.velocityOverLifetime;
            vel.enabled = true;
            vel.space = ParticleSystemSimulationSpace.World;
            // all three axes in one mode (TwoConstants), as Unity requires
            vel.x = new ParticleSystem.MinMaxCurve(-s.spread, s.spread);
            vel.y = new ParticleSystem.MinMaxCurve(s.rise, s.rise);
            vel.z = new ParticleSystem.MinMaxCurve(-s.spread, s.spread);

            var sheet = ps.textureSheetAnimation;
            sheet.enabled = true;
            sheet.mode = ParticleSystemAnimationMode.Grid;
            sheet.numTilesX = s.tilesX;
            sheet.numTilesY = s.tilesY;
            sheet.animation = ParticleSystemAnimationType.SingleRow;
            sheet.rowMode = ParticleSystemAnimationRowMode.Random;
            sheet.timeMode = ParticleSystemAnimationTimeMode.FPS;
            sheet.fps = 12f;
            sheet.startFrame = new ParticleSystem.MinMaxCurve(0f, Mathf.Max(0, s.tilesX - 1) + 0.999f);

            r.renderMode = ParticleSystemRenderMode.Billboard;
            r.alignment = ParticleSystemRenderSpace.View;
            r.sortMode = ParticleSystemSortMode.Distance;
            r.sharedMaterial = mat;
            r.minParticleSize = 0f;
            r.maxParticleSize = 10f;
            r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            r.receiveShadows = false;
        }

        private static Material SheetMaterial(string texPath, string name)
        {
            var imp = AssetImporter.GetAtPath(texPath) as TextureImporter;
            if (imp == null) throw new InvalidOperationException("texture did not import: " + texPath);
            imp.textureType = TextureImporterType.Default;
            imp.filterMode = FilterMode.Point;
            imp.mipmapEnabled = false;
            imp.textureCompression = TextureImporterCompression.Uncompressed;
            imp.alphaIsTransparency = true;
            imp.wrapMode = TextureWrapMode.Clamp;
            imp.npotScale = TextureImporterNPOTScale.None;
            imp.sRGBTexture = true;
            imp.maxTextureSize = 8192;
            imp.SaveAndReimport();
            Shader sh = Shader.Find("Sprites/Default");
            if (sh == null) throw new InvalidOperationException("Sprites/Default shader not found");
            return new Material(sh) { mainTexture = AssetDatabase.LoadAssetAtPath<Texture2D>(texPath), name = name };
        }

        private static Texture2D ImportTexture(string path, bool mips, bool point)
        {
            var imp = AssetImporter.GetAtPath(path) as TextureImporter;
            if (imp == null) throw new InvalidOperationException("texture did not import: " + path);
            imp.textureType = TextureImporterType.Default;
            imp.mipmapEnabled = mips;
            imp.filterMode = point ? FilterMode.Point : FilterMode.Bilinear;
            imp.wrapMode = TextureWrapMode.Clamp;
            imp.npotScale = TextureImporterNPOTScale.None;
            imp.maxTextureSize = 8192;
            imp.textureCompression = TextureImporterCompression.Uncompressed;
            imp.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }
    }
}
