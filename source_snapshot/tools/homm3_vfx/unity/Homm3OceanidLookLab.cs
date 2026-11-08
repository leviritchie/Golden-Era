// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/oceanid_unity_lab.py (--v2). Editor-only lab; NOT a delivery path.
// Oceanid look lab v2: foam-toned lighting + flowing water + DEF-ripped accents, rendered through the SpriteCam
// at DEF frame times. Inputs come from tools/homm3_vfx/oceanid_look_lab.py (artifacts/.../oceanid/look/).
//   current       - the mesh as delivered today (source base colour)
//   L             - lighting only: look_static.png (region-graded v7c body + DEF-palette water), no motion
//   B2L           - one renderer, stepped boil atlas (DEF's in-place boil), same lighting
//   F2            - F with coarse travelling features (bands 8 px, speckle 3-5 px, highlights 4 px)
//   F             - one renderer, stepped FLOW atlas: bands/speckle travel 2 DEF px per 12 fps frame (no plugin change)
//   A2            - body = B2L stepped atlas; column split to its own SkinnedMeshRenderer with a tile atlas:
//                   stepped ST.z (re-rolled boil share) + linear ST.w scroll (1 tile per idle loop) (no plugin change;
//                   needs a builder split + <stem> textures for the restamp)
//   A             - body = B2L; split column with tile0 + native Hex/Lit _UvScroll (plugin change: keep _UvScroll)
//   FX            - F + accent flipbooks (the candidate delivery, judged with effects on)
//   accents_only  - skinned renderers hidden, accents only (IoU vs the DEF effect masks)
//   mask          - vertex colour (COLOR_0 r = water, g = foam) for region metrics
// Stepped variants swap in a fresh material with _MainTex_ST reset AFTER the Animator binds (the plugin's restamp).
// Accents: Sprites/Default ParticleSystem flipbooks (point filter, view billboard, 1 particle burst) parented to the
// static Root bone; frame i shows over [(i+0.5)/12, (i+1.5)/12). Particle renderers are not restamped by the plugin.
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
    public static class Homm3OceanidLookLab
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

        [Serializable] private sealed class ClipCells { public string name; public int[] cells; public int[] flow; } // flow: monotonic i % 8 (a ping-pong would run the water backwards)
        [Serializable]
        private sealed class Accent
        {
            public string id, clip, sheet;
            public int frameCount;
            public int[] cellPx;
            public float[] centreOffsetPx;
        }
        [Serializable]
        private sealed class Spec
        {
            public string schema, assetRoot, glbAssetPath;
            public string staticTex, boilAtlas, flowAtlas, flow2Atlas, tileAtlas, tile0;
            public float[] cellST;
            public ClipCells[] clips;
            public float tileCellScaleX, tileWorldHeight, tileScrollPerSecond;
            public float[] tileCellOffsetX;
            public Accent[] accents;
            public string outDir;
            public float[] camRight, camUp, camForward;
            public float pxPerUnit;
            public float[] offset;
            public int[] size;
            public int scale;
            public float accentTowardCamera;
            public float[] sunTravelUnity;  // arena MainLight travel dir, camera-relative as in tools/homm3_prebake/render_passes.py
            public string[] variants, subsampleVariants;
            public string subsampleClip;
            public int subsamplePerFrame;
        }

        private static readonly StringBuilder Report = new StringBuilder();
        private static Shader _shader;
        private static Vector4 _sunDir;

        public static void RunFromCommandLine()
        {
            string[] args = UnityQueueArgs();
            string specPath = null;
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == "-homm3OceanidLookSpec") specPath = args[i + 1];
            if (string.IsNullOrEmpty(specPath) || !File.Exists(specPath))
                throw new InvalidOperationException("-homm3OceanidLookSpec <file> is required");
            Spec spec = JsonUtility.FromJson<Spec>(File.ReadAllText(specPath));
            if (spec.schema != "homm3_oceanid_look_lab.v2") throw new InvalidOperationException("schema " + spec.schema);
            Run(spec);
            Debug.Log("HOMM3_OCEANID_LOOK_OK");
        }

        private static void Log(string key, string json)
        {
            Report.Append(Report.Length == 0 ? "{\n" : ",\n").Append(" \"").Append(key).Append("\": ").Append(json);
            Debug.Log("HOMM3_OCEANID_LOOK " + key + " " + (json.Length > 300 ? json.Substring(0, 300) + "..." : json));
        }

        private sealed class Inst
        {
            public GameObject go;
            public Animator animator;
            public SkinnedMeshRenderer body, water;
            public List<(Accent a, ParticleSystem ps)> accents = new List<(Accent, ParticleSystem)>();
        }

        private static void Run(Spec spec)
        {
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            _shader = AssetDatabase.LoadAssetAtPath<Shader>(spec.assetRoot + "/Homm3OceanidHexLitLab.shader");
            if (_shader == null) throw new InvalidOperationException("lab shader missing");
            _sunDir = new Vector4(spec.sunTravelUnity[0], spec.sunTravelUnity[1], spec.sunTravelUnity[2], 0);
            string R(string n) => spec.assetRoot + "/" + n;
            Texture2D stat = ImportTexture(R(spec.staticTex), TextureWrapMode.Clamp, true);
            Texture2D boil = ImportTexture(R(spec.boilAtlas), TextureWrapMode.Clamp, true);
            Texture2D flow = ImportTexture(R(spec.flowAtlas), TextureWrapMode.Clamp, true);
            Texture2D flow2 = ImportTexture(R(spec.flow2Atlas), TextureWrapMode.Clamp, true);
            Texture2D tileAtlas = ImportTexture(R(spec.tileAtlas), TextureWrapMode.Repeat, false);
            Texture2D tile0 = ImportTexture(R(spec.tile0), TextureWrapMode.Repeat, true);

            GameObject glb = AssetDatabase.LoadAssetAtPath<GameObject>(spec.glbAssetPath);
            if (glb == null) throw new InvalidOperationException("GLB did not import: " + spec.glbAssetPath);
            SkinnedMeshRenderer srcSkin = glb.GetComponentsInChildren<SkinnedMeshRenderer>(true).Single();
            Mesh srcMesh = srcSkin.sharedMesh;
            Texture albedo = srcSkin.sharedMaterial.mainTexture;
            if (albedo == null)
                foreach (string n in srcSkin.sharedMaterial.GetTexturePropertyNames())
                    if (srcSkin.sharedMaterial.GetTexture(n) != null && n.ToLowerInvariant().Contains("base")) albedo = srcSkin.sharedMaterial.GetTexture(n);
            if (srcMesh.colors.Length != srcMesh.vertexCount) throw new InvalidOperationException("COLOR_0 missing after import");
            AnimationClip[] glbClips = AssetDatabase.LoadAllAssetsAtPath(spec.glbAssetPath).OfType<AnimationClip>().ToArray();

            Mesh bodyNoColumn = SubsetMesh(srcMesh, false, "body_nocolumn");
            Mesh column = SubsetMesh(srcMesh, true, "column");
            column.uv = TileUv(column, spec.tileWorldHeight);
            Log("split", "{\"columnTriangles\": " + column.triangles.Length / 3 + ", \"bodyTriangles\": " + bodyNoColumn.triangles.Length / 3 + "}");

            var accentMats = new Dictionary<string, Material>();
            foreach (Accent a in spec.accents) accentMats[a.id] = AccentMaterial(R(a.sheet), a.id);

            string clipRoot = spec.assetRoot + "/clips_v2";
            if (!AssetDatabase.IsValidFolder(clipRoot)) AssetDatabase.CreateFolder(spec.assetRoot, "clips_v2");
            float ppu = spec.pxPerUnit;
            Vector3 right = B2U(spec.camRight), up = B2U(spec.camUp), fwd = B2U(spec.camForward);

            var insts = new Dictionary<string, Inst>();
            foreach (string variant in spec.variants)
            {
                var inst = new Inst { go = UnityEngine.Object.Instantiate(glb) };
                GameObject go = inst.go;
                go.name = variant;
                foreach (Animation legacy in go.GetComponentsInChildren<Animation>(true)) UnityEngine.Object.DestroyImmediate(legacy);
                SkinnedMeshRenderer skin = go.GetComponentsInChildren<SkinnedMeshRenderer>(true).Single();
                skin.forceMatrixRecalculationPerRender = true;
                skin.updateWhenOffscreen = true;
                inst.body = skin;
                Texture bodyTex = variant == "current" ? albedo : variant == "L" || variant == "accents_only" || variant == "mask" ? stat
                    : variant == "F" || variant == "FX" ? flow : variant == "F2" ? flow2 : boil;
                bool bodyStepped = variant == "B2L" || variant == "F" || variant == "F2" || variant == "FX" || variant == "A2" || variant == "A";
                skin.sharedMaterial = NewMat(bodyTex);
                if (variant == "mask") skin.sharedMaterial.SetFloat("_MaskMode", 1f);
                if (variant == "A2" || variant == "A")
                {
                    skin.sharedMesh = bodyNoColumn;
                    inst.water = AddSkinnedChild(skin, column, NewMat(variant == "A2" ? tileAtlas : tile0), "water_column");
                    if (variant == "A") inst.water.sharedMaterial.SetVector("_UvScroll", new Vector4(0, spec.tileScrollPerSecond, 0, 0));
                }
                if (variant == "FX" || variant == "accents_only")
                {
                    Transform root = go.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == "Root");
                    if (root == null) throw new InvalidOperationException("Root bone not found");
                    foreach (Accent a in spec.accents)
                    {
                        var child = new GameObject("fx_" + a.id);
                        child.transform.SetParent(root, false);
                        child.transform.position = root.position + right * (a.centreOffsetPx[0] / ppu) - up * (a.centreOffsetPx[1] / ppu)
                            - fwd * spec.accentTowardCamera;
                        child.transform.rotation = Quaternion.identity;
                        child.transform.localScale = Vector3.one;
                        var ps = child.AddComponent<ParticleSystem>();
                        ConfigureAccent(ps, child.GetComponent<ParticleSystemRenderer>(), a, accentMats[a.id], ppu);
                        inst.accents.Add((a, ps));
                    }
                }
                if (variant == "accents_only") skin.enabled = false;

                Animator animator = go.GetComponent<Animator>();
                if (animator == null) animator = go.AddComponent<Animator>();
                animator.applyRootMotion = false;
                animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
                string bodyPath = AnimationUtility.CalculateTransformPath(skin.transform, go.transform);
                string waterPath = variant == "A2" ? AnimationUtility.CalculateTransformPath(inst.water.transform, go.transform) : null;
                string ctrlPath = clipRoot + "/" + variant + ".controller";
                AssetDatabase.DeleteAsset(ctrlPath);
                AnimatorController ctrl = AnimatorController.CreateAnimatorControllerAtPath(ctrlPath);
                foreach (ClipCells cc in spec.clips)
                {
                    AnimationClip src = glbClips.First(c => c.name == cc.name || c.name.EndsWith(cc.name, StringComparison.Ordinal));
                    AnimationClip copy = new AnimationClip { name = variant + "_" + cc.name, frameRate = src.frameRate, legacy = false };
                    foreach (EditorCurveBinding b in AnimationUtility.GetCurveBindings(src))
                        AnimationUtility.SetEditorCurve(copy, b, AnimationUtility.GetEditorCurve(src, b));
                    if (bodyStepped) AddSteppedST(copy, bodyPath, variant == "F" || variant == "FX" || variant == "F2" ? cc.flow : cc.cells, spec.cellST);
                    if (waterPath != null) AddTileST(copy, waterPath, cc.flow, spec, src.length);
                    copy.EnsureQuaternionContinuity();
                    string cp = clipRoot + "/" + copy.name + ".anim";
                    AssetDatabase.DeleteAsset(cp);
                    AssetDatabase.CreateAsset(copy, cp);
                    AnimatorState st = ctrl.AddMotion(copy);
                    st.name = cc.name;
                    st.writeDefaultValues = true;
                }
                AssetDatabase.SaveAssets();
                animator.runtimeAnimatorController = ctrl;
                animator.Rebind();
                animator.Play(spec.clips[0].name, 0, 0f);
                animator.Update(0f);
                // plugin restamp: fresh Hex/Lit clone per skinned renderer, _MainTex_ST reset, after the Animator bound
                if (bodyStepped) skin.sharedMaterial = Restamp(bodyTex);
                if (variant == "A2") inst.water.sharedMaterial = Restamp(tileAtlas);
                if (variant == "A") { var m = Restamp(tile0); m.SetVector("_UvScroll", new Vector4(0, spec.tileScrollPerSecond, 0, 0)); inst.water.sharedMaterial = m; }
                inst.animator = animator;
                go.SetActive(false);
                insts[variant] = inst;
            }

            int s = spec.scale, W = spec.size[0] * s, H = spec.size[1] * s;
            Vector3 center = right * ((spec.size[0] * 0.5f - spec.offset[0]) / ppu) + up * ((spec.offset[1] - spec.size[1] * 0.5f) / ppu);
            Camera cam = new GameObject("SpriteCam").AddComponent<Camera>();
            cam.orthographic = true;
            cam.orthographicSize = (spec.size[1] * 0.5f) / ppu;
            cam.transform.SetPositionAndRotation(center - fwd * 20f, Quaternion.LookRotation(fwd, up));
            cam.nearClipPlane = 0.1f; cam.farClipPlane = 60f;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0, 0, 0, 0);
            cam.allowMSAA = false;
            var rt = new RenderTexture(W, H, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB) { antiAliasing = 1 };
            cam.targetTexture = rt;
            var read = new Texture2D(W, H, TextureFormat.RGBA32, false);

            var stLog = new List<string>();
            var mpb = new MaterialPropertyBlock();
            int renders = 0;
            void Shoot(string variant, ClipCells cc, float t, string file, int frame)
            {
                Inst inst = insts[variant];
                inst.go.SetActive(true);
                Shader.SetGlobalFloat("_LabTime", t);
                AnimationClip playing = inst.animator.runtimeAnimatorController.animationClips.First(c => c.name.EndsWith("_" + cc.name));
                inst.animator.Play(cc.name, 0, Mathf.Clamp01(t / Mathf.Max(playing.length, 1e-4f)));
                inst.animator.Update(0f);
                foreach (Renderer r in inst.go.GetComponentsInChildren<SkinnedMeshRenderer>()) r.sharedMaterial.SetFloat("_LabTime", t);
                foreach (var (a, ps) in inst.accents)
                {
                    float age = t - 0.5f / 12f;
                    bool on = a.clip == cc.name && age >= 0f;
                    ps.GetComponent<ParticleSystemRenderer>().enabled = on;
                    ps.Clear(true);
                    if (on) ps.Simulate(age, true, true, false);
                }
                if (frame >= 0 && (variant == "A2" || variant == "F"))
                {
                    Renderer target = variant == "A2" ? inst.water : inst.body;
                    target.GetPropertyBlock(mpb);
                    Vector4 v = mpb.GetVector("_MainTex_ST");
                    stLog.Add("{\"variant\": \"" + variant + "\", \"clip\": \"" + cc.name + "\", \"frame\": " + frame + ", \"t\": " + t.ToString("R")
                        + ", \"mpbST\": [" + v.x.ToString("R") + ", " + v.y.ToString("R") + ", " + v.z.ToString("R") + ", " + v.w.ToString("R") + "]}");
                }
                cam.Render();
                RenderTexture.active = rt;
                read.ReadPixels(new Rect(0, 0, W, H), 0, 0);
                read.Apply();
                RenderTexture.active = null;
                string dir = Path.Combine(spec.outDir, variant);
                Directory.CreateDirectory(dir);
                File.WriteAllBytes(Path.Combine(dir, file), read.EncodeToPNG());
                inst.go.SetActive(false);
                renders++;
            }

            foreach (ClipCells cc in spec.clips)
                for (int i = 0; i < cc.cells.Length; i++)
                    foreach (string variant in spec.variants)
                        Shoot(variant, cc, (i + 1) / 12f, cc.name + "_" + i.ToString("00") + ".png", i);
            ClipCells sub = spec.clips.First(c => c.name == spec.subsampleClip);
            int k = spec.subsamplePerFrame;
            for (int j = 0; j <= k * (sub.cells.Length - 1); j++)
                foreach (string variant in spec.subsampleVariants)
                    Shoot(variant, sub, 1f / 12f + j / (12f * k), "sub" + (12 * k) + "_" + j.ToString("000") + ".png", -1);

            Log("animatorST", "[\n  " + string.Join(",\n  ", stLog) + "\n ]");
            Log("renders", renders.ToString());
            Log("variants", "[" + string.Join(", ", spec.variants.Select(v => "\"" + v + "\"")) + "]");
            File.WriteAllText(Path.Combine(spec.outDir, "lab_report.json"), Report.ToString() + "\n}\n");
        }

        private static Material Restamp(Texture tex)
        {
            Material m = NewMat(tex);
            m.name = "restamp_runtime_native";
            m.SetVector("_MainTex_ST", new Vector4(1, 1, 0, 0));
            return m;
        }

        private static void Stepped(AnimationClip clip, string path, string prop, int n, Func<int, float> value)
        {
            var keys = new List<Keyframe>();
            for (int i = 0; i < n; i++)
                keys.Add(new Keyframe(i == 0 ? 0f : (i + 0.5f) / 12f, value(i)) { inTangent = float.PositiveInfinity, outTangent = float.PositiveInfinity });
            var curve = new AnimationCurve(keys.ToArray());
            for (int i = 0; i < curve.length; i++)
            {
                AnimationUtility.SetKeyLeftTangentMode(curve, i, AnimationUtility.TangentMode.Constant);
                AnimationUtility.SetKeyRightTangentMode(curve, i, AnimationUtility.TangentMode.Constant);
            }
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(SkinnedMeshRenderer), prop), curve);
        }

        private static void AddSteppedST(AnimationClip clip, string path, int[] cells, float[] cellST)
        {
            string[] comp = { "x", "y", "z", "w" };
            for (int c = 0; c < 4; c++)
                Stepped(clip, path, "material._MainTex_ST." + comp[c], cells.Length, i => cellST[cells[i] * 4 + c]);
        }

        // A2: tile atlas cell stepped on ST.z; ST.w a linear scroll (tiles/s) across the clip
        private static void AddTileST(AnimationClip clip, string path, int[] cells, Spec spec, float length)
        {
            Stepped(clip, path, "material._MainTex_ST.x", 1, i => spec.tileCellScaleX);
            Stepped(clip, path, "material._MainTex_ST.y", 1, i => 1f);
            Stepped(clip, path, "material._MainTex_ST.z", cells.Length, i => spec.tileCellOffsetX[cells[i] % spec.tileCellOffsetX.Length]);
            float end = Mathf.Max(length, cells.Length / 12f);
            var w = AnimationCurve.Linear(0f, 0f, end, spec.tileScrollPerSecond * end);
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(SkinnedMeshRenderer), "material._MainTex_ST.w"), w);
        }

        private static void ConfigureAccent(ParticleSystem ps, ParticleSystemRenderer renderer, Accent a, Material material, float ppu)
        {
            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            float life = a.frameCount / 12f;
            var main = ps.main;
            main.duration = life;
            main.loop = false;
            main.playOnAwake = false;
            main.startDelay = 0f;
            main.startLifetime = life;
            main.startSpeed = 0f;
            main.startSize3D = true;
            main.startSizeX = a.cellPx[0] / ppu;
            main.startSizeY = a.cellPx[1] / ppu;
            main.startSizeZ = 1f;
            main.startRotation = 0f;
            main.startColor = Color.white;
            main.gravityModifier = 0f;
            main.maxParticles = 1;
            main.scalingMode = ParticleSystemScalingMode.Local;
            main.simulationSpace = ParticleSystemSimulationSpace.Local;
            ps.useAutoRandomSeed = false;
            ps.randomSeed = 11;
            var emission = ps.emission;
            emission.rateOverTime = 0f;
            emission.SetBursts(new[] { new ParticleSystem.Burst(0f, 1) });
            var shape = ps.shape;
            shape.enabled = false;
            var sheet = ps.textureSheetAnimation;
            sheet.enabled = true;
            sheet.mode = ParticleSystemAnimationMode.Grid;
            sheet.numTilesX = a.frameCount;
            sheet.numTilesY = 1;
            sheet.animation = ParticleSystemAnimationType.WholeSheet;
            sheet.cycleCount = 1;
            sheet.frameOverTime = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0f, 0f, 1f, 1f));
            renderer.renderMode = ParticleSystemRenderMode.Billboard;
            renderer.alignment = ParticleSystemRenderSpace.View;
            renderer.sharedMaterial = material;
            renderer.minParticleSize = 0f;
            renderer.maxParticleSize = 10f;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            renderer.receiveShadows = false;
        }

        private static Material AccentMaterial(string texPath, string name)
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
            imp.SaveAndReimport();
            Shader sh = Shader.Find("Sprites/Default");
            if (sh == null) throw new InvalidOperationException("Sprites/Default shader not found");
            return new Material(sh) { mainTexture = AssetDatabase.LoadAssetAtPath<Texture2D>(texPath), name = name };
        }

        private static SkinnedMeshRenderer AddSkinnedChild(SkinnedMeshRenderer skin, Mesh mesh, Material mat, string name)
        {
            var child = new GameObject(name);
            child.transform.SetParent(skin.transform.parent, false);
            child.transform.localPosition = skin.transform.localPosition;
            child.transform.localRotation = skin.transform.localRotation;
            child.transform.localScale = skin.transform.localScale;
            var r = child.AddComponent<SkinnedMeshRenderer>();
            r.sharedMesh = mesh;
            r.bones = skin.bones;
            r.rootBone = skin.rootBone;
            r.sharedMaterial = mat;
            r.updateWhenOffscreen = true;
            r.forceMatrixRecalculationPerRender = true;
            return r;
        }

        // column = triangles whose three vertices are water (COLOR.r) and not foam (COLOR.g)
        private static Mesh SubsetMesh(Mesh src, bool column, string name)
        {
            Mesh m = UnityEngine.Object.Instantiate(src);
            m.name = src.name + "_" + name;
            Color[] col = src.colors;
            bool IsCol(int v) => col[v].r > 0.5f && col[v].g < 0.5f;
            var tris = new List<int>();
            for (int sub = 0; sub < src.subMeshCount; sub++)
            {
                int[] t = src.GetTriangles(sub);
                for (int i = 0; i < t.Length; i += 3)
                    if ((IsCol(t[i]) && IsCol(t[i + 1]) && IsCol(t[i + 2])) == column) { tris.Add(t[i]); tris.Add(t[i + 1]); tris.Add(t[i + 2]); }
            }
            m.subMeshCount = 1;
            m.SetTriangles(tris, 0);
            return m;
        }

        // same parameterisation as oceanid_look_lab.py's tile: theta = atan2(x_gltf, z_gltf), x_gltf = -x_unity; v = y / tile height
        private static Vector2[] TileUv(Mesh m, float tileHeight)
        {
            Vector3[] v = m.vertices;
            var uv = new Vector2[v.Length];
            for (int i = 0; i < v.Length; i++)
                uv[i] = new Vector2(Mathf.Atan2(-v[i].x, v[i].z) / (2 * Mathf.PI) + 0.5f, v[i].y / tileHeight);
            return uv;
        }

        private static Material NewMat(Texture tex)
        {
            var m = new Material(_shader) { mainTexture = tex };
            m.SetFloat("_Cull", 2f);
            m.SetVector("_SunDir", _sunDir);
            return m;
        }

        private static Texture2D ImportTexture(string path, TextureWrapMode wrap, bool mips)
        {
            var imp = AssetImporter.GetAtPath(path) as TextureImporter;
            if (imp == null) throw new InvalidOperationException("texture did not import: " + path);
            imp.textureType = TextureImporterType.Default;
            imp.mipmapEnabled = mips;
            imp.wrapMode = wrap;
            imp.npotScale = TextureImporterNPOTScale.None;
            imp.maxTextureSize = 8192;
            imp.textureCompression = TextureImporterCompression.Uncompressed;
            imp.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }

        private static Vector3 B2U(float[] b) => new Vector3(-b[0], b[2], -b[1]);
    }
}
