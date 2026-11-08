// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/oceanid_unity_lab.py. Editor-only lab; NOT a delivery path.
// Imports a COPY of the oceanid def_retarget GLB (plus a COLOR_0 water mask), builds the flowing-water
// candidates as separate instances and renders them through the SpriteCam at DEF frame times:
//   current      - the mesh as delivered today (one renderer, base colour only)
//   A_uvscroll   - water split to its own renderer, cylindrical UV, tileable tile, Hex/Lit _UvScroll
//   B_flipbook   - one renderer, boil atlas, clip-animated material._MainTex_ST stepped at the DEF's 12 fps;
//                  the material is swapped AFTER the Animator binds, as the plugin's Hex/Lit restamp does
//   B2_defpalette - B with the water texels rank-mapped onto the DEF idle water palette (same cells/keys)
//   C_shell      - current body + inflated translucent water shell with the stepped sparkle atlas
//   D_flag       - current + Hex/Lit HEX_VERTEX_DISPLACEMENT_FLAG formula masked by COLOR.r
// Plus a mask pass (vertex colour) for region metrics. Writes PNGs and lab_report.json.
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
    public static class Homm3OceanidWaterLab
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

        [Serializable] private sealed class ClipCells { public string name; public int[] cells; }
        [Serializable]
        private sealed class Spec
        {
            public string schema;
            public string assetRoot;
            public string glbAssetPath;
            public string boilAtlas, boilAtlasDefPalette, sparkleAtlas, scrollTile;
            public float[] cellST;          // 8 x 4
            public ClipCells[] clips;
            public string outDir;
            public float[] camRight, camUp, camForward; // Blender coords
            public float pxPerUnit;
            public float[] offset;          // DEF px of the world origin
            public int[] size;              // DEF canvas px
            public int scale;
            public float[] uvScroll;        // A: (u, v) per second
            public float[] flagDirection, flagPower;
            public float flagSpeed;
            public float shellOffset;
            public string[] variants;
        }

        private static readonly StringBuilder Report = new StringBuilder();
        private static Shader _shader;

        public static void RunFromCommandLine()
        {
            string[] args = UnityQueueArgs();
            string specPath = null;
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == "-homm3OceanidLabSpec") specPath = args[i + 1];
            if (string.IsNullOrEmpty(specPath) || !File.Exists(specPath))
                throw new InvalidOperationException("-homm3OceanidLabSpec <file> is required");
            Spec spec = JsonUtility.FromJson<Spec>(File.ReadAllText(specPath));
            if (spec.schema != "homm3_oceanid_unity_lab.v1") throw new InvalidOperationException("schema " + spec.schema);
            Run(spec);
            Debug.Log("HOMM3_OCEANID_LAB_OK");
        }

        private static void Log(string key, string json)
        {
            Report.Append(Report.Length == 0 ? "{\n" : ",\n").Append(" \"").Append(key).Append("\": ").Append(json);
            Debug.Log("HOMM3_OCEANID_LAB " + key + " " + json);
        }

        private static void Run(Spec spec)
        {
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            _shader = AssetDatabase.LoadAssetAtPath<Shader>(spec.assetRoot + "/Homm3OceanidHexLitLab.shader");
            if (_shader == null) throw new InvalidOperationException("lab shader missing");
            Texture2D boil = ImportTexture(spec.assetRoot + "/" + spec.boilAtlas, TextureWrapMode.Clamp);
            Texture2D boilDef = ImportTexture(spec.assetRoot + "/" + spec.boilAtlasDefPalette, TextureWrapMode.Clamp);
            Texture2D sparkle = ImportTexture(spec.assetRoot + "/" + spec.sparkleAtlas, TextureWrapMode.Clamp);
            Texture2D tile = ImportTexture(spec.assetRoot + "/" + spec.scrollTile, TextureWrapMode.Repeat);

            GameObject glb = AssetDatabase.LoadAssetAtPath<GameObject>(spec.glbAssetPath);
            if (glb == null) throw new InvalidOperationException("GLB did not import: " + spec.glbAssetPath);
            SkinnedMeshRenderer srcSkin = glb.GetComponentsInChildren<SkinnedMeshRenderer>(true).Single();
            Mesh srcMesh = srcSkin.sharedMesh;
            Color[] colors = srcMesh.colors;
            int waterVerts = colors.Count(c => c.r > 0.5f);
            Texture albedo = srcSkin.sharedMaterial != null ? srcSkin.sharedMaterial.mainTexture : null;
            if (albedo == null)
                foreach (string n in srcSkin.sharedMaterial.GetTexturePropertyNames())
                    if (srcSkin.sharedMaterial.GetTexture(n) != null && n.ToLowerInvariant().Contains("base")) albedo = srcSkin.sharedMaterial.GetTexture(n);
            Log("import", "{\"vertices\": " + srcMesh.vertexCount + ", \"colorsPresent\": " + (colors.Length == srcMesh.vertexCount ? "true" : "false")
                + ", \"waterVerticesFromCOLOR_0\": " + waterVerts + ", \"blendShapes\": " + srcMesh.blendShapeCount
                + ", \"subMeshes\": " + srcMesh.subMeshCount + ", \"albedo\": \"" + (albedo ? albedo.name + " " + albedo.width + "x" + albedo.height : "none")
                + "\", \"sourceShader\": \"" + (srcSkin.sharedMaterial ? srcSkin.sharedMaterial.shader.name : "none") + "\"}");
            if (colors.Length != srcMesh.vertexCount || waterVerts == 0)
                throw new InvalidOperationException("COLOR_0 water mask did not survive the glTF import");

            // clips: generic copies of every curve (bones + corrective blend shapes) as in Homm3VfxLabBuild
            AnimationClip[] glbClips = AssetDatabase.LoadAllAssetsAtPath(spec.glbAssetPath).OfType<AnimationClip>().ToArray();
            var curveTypes = new SortedDictionary<string, int>();
            foreach (var b in AnimationUtility.GetCurveBindings(glbClips.First(c => c.name.EndsWith("Unit_Idle"))))
            {
                string k = b.type.Name + ":" + (b.propertyName.StartsWith("blendShape.") ? "blendShape.*" : b.propertyName.Split('.')[0]);
                curveTypes[k] = curveTypes.TryGetValue(k, out int v) ? v + 1 : 1;
            }
            Log("importedIdleCurveKinds", "{" + string.Join(", ", curveTypes.Select(kv => "\"" + kv.Key + "\": " + kv.Value)) + "}");

            var variants = new Dictionary<string, GameObject>();
            var animators = new Dictionary<string, Animator>();
            string clipRoot = spec.assetRoot + "/clips";
            if (!AssetDatabase.IsValidFolder(clipRoot)) AssetDatabase.CreateFolder(spec.assetRoot, "clips");

            foreach (string variant in spec.variants.Concat(new[] { "mask" }))
            {
                GameObject go = UnityEngine.Object.Instantiate(glb);
                go.name = variant;
                foreach (Animation legacy in go.GetComponentsInChildren<Animation>(true)) UnityEngine.Object.DestroyImmediate(legacy);
                SkinnedMeshRenderer skin = go.GetComponentsInChildren<SkinnedMeshRenderer>(true).Single();
                skin.forceMatrixRecalculationPerRender = true;
                skin.updateWhenOffscreen = true;
                string extraPath = null;
                Material mat = NewMat(albedo);
                skin.sharedMaterial = mat;
                if (variant == "A_uvscroll")
                {
                    Mesh body = SubsetMesh(srcMesh, false, "body");
                    Mesh water = SubsetMesh(srcMesh, true, "water");
                    water.uv = CylindricalUv(water, spec);
                    skin.sharedMesh = body;
                    Material wm = NewMat(tile);
                    wm.SetVector("_UvScroll", new Vector4(spec.uvScroll[0], spec.uvScroll[1], 0, 0));
                    extraPath = AddSkinnedChild(skin, water, wm, "water_uvscroll").name;
                }
                else if (variant == "B_flipbook" || variant == "B2_defpalette")
                {
                    skin.sharedMaterial = NewMat(variant == "B_flipbook" ? boil : boilDef);
                }
                else if (variant == "C_shell")
                {
                    Mesh shell = SubsetMesh(srcMesh, true, "shell");
                    Vector3[] v = shell.vertices, n = shell.normals;
                    for (int i = 0; i < v.Length; i++) v[i] += n[i] * spec.shellOffset;
                    shell.vertices = v;
                    shell.RecalculateBounds();
                    Material sm = NewMat(sparkle);
                    sm.SetFloat("_SrcBlend", 5f); sm.SetFloat("_DstBlend", 10f); sm.SetFloat("_ZWrite", 0f);
                    sm.renderQueue = 3000;
                    extraPath = AddSkinnedChild(skin, shell, sm, "water_shell").name;
                }
                else if (variant == "D_flag")
                {
                    mat.SetFloat("_FlagEnabled", 1f);
                    mat.SetVector("_FlagDirection", ToV4(spec.flagDirection));
                    mat.SetVector("_FlagPower", ToV4(spec.flagPower));
                    mat.SetFloat("_FlagSpeed", spec.flagSpeed);
                }
                else if (variant == "mask")
                {
                    mat.SetFloat("_MaskMode", 1f);
                }

                // Animator + controller with one state per clip; B/C add stepped _MainTex_ST curves
                Animator animator = go.GetComponent<Animator>();
                if (animator == null) animator = go.AddComponent<Animator>();
                animator.applyRootMotion = false;
                animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
                bool stepped = variant == "B_flipbook" || variant == "B2_defpalette";
                string stPath = stepped ? AnimationUtility.CalculateTransformPath(skin.transform, go.transform)
                    : variant == "C_shell" ? PathTo(skin.transform, go.transform, extraPath)
                    : null;
                string ctrlPath = spec.assetRoot + "/clips/" + variant + ".controller";
                AssetDatabase.DeleteAsset(ctrlPath);
                AnimatorController ctrl = AnimatorController.CreateAnimatorControllerAtPath(ctrlPath);
                foreach (ClipCells cc in spec.clips)
                {
                    AnimationClip src = glbClips.First(c => c.name == cc.name || c.name.EndsWith(cc.name, StringComparison.Ordinal));
                    AnimationClip copy = new AnimationClip { name = variant + "_" + cc.name, frameRate = src.frameRate, legacy = false };
                    foreach (EditorCurveBinding b in AnimationUtility.GetCurveBindings(src))
                        AnimationUtility.SetEditorCurve(copy, b, AnimationUtility.GetEditorCurve(src, b));
                    if (stPath != null) AddSteppedST(copy, stPath, cc.cells, spec.cellST);
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
                if (stepped)
                {
                    // plugin restamp order: Animator already bound, then the skinned material is replaced by a fresh
                    // Hex/Lit clone whose _MainTex_ST is reset to (1,1,0,0) (SanitizeMapMaterialForOpaqueMesh)
                    Material restamp = NewMat(variant == "B_flipbook" ? boil : boilDef);
                    restamp.name = "restamp_runtime_native";
                    restamp.SetVector("_MainTex_ST", new Vector4(1, 1, 0, 0));
                    skin.sharedMaterial = restamp;
                }
                go.SetActive(false);
                variants[variant] = go;
                animators[variant] = animator;
            }

            // camera through the calibrated SpriteCam
            float ppu = spec.pxPerUnit;
            int s = spec.scale, W = spec.size[0] * s, H = spec.size[1] * s;
            Vector3 right = B2U(spec.camRight), up = B2U(spec.camUp), fwd = B2U(spec.camForward);
            Vector3 center = right * ((spec.size[0] * 0.5f - spec.offset[0]) / ppu) + up * ((spec.offset[1] - spec.size[1] * 0.5f) / ppu);
            GameObject camGo = new GameObject("SpriteCam");
            Camera cam = camGo.AddComponent<Camera>();
            cam.orthographic = true;
            cam.orthographicSize = (spec.size[1] * 0.5f) / ppu;
            cam.transform.SetPositionAndRotation(center - fwd * 20f, Quaternion.LookRotation(fwd, up));
            cam.nearClipPlane = 0.1f; cam.farClipPlane = 60f;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0, 0, 0, 0);
            cam.allowMSAA = false;
            RenderTexture rt = new RenderTexture(W, H, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB) { antiAliasing = 1 };
            cam.targetTexture = rt;
            Texture2D read = new Texture2D(W, H, TextureFormat.RGBA32, false);
            Directory.CreateDirectory(spec.outDir);

            var mpbLog = new List<string>();
            var mpb = new MaterialPropertyBlock();
            foreach (ClipCells cc in spec.clips)
            {
                for (int i = 0; i < cc.cells.Length; i++)
                {
                    float t = (i + 1) / 12f; // the GLB keys DEF frame i at (i+1)/12 s
                    Shader.SetGlobalFloat("_LabTime", t);
                    foreach (var kv in variants)
                    {
                        GameObject go = kv.Value;
                        go.SetActive(true);
                        Animator an = animators[kv.Key];
                        AnimationClip playing = an.runtimeAnimatorController.animationClips.First(c => c.name.EndsWith("_" + cc.name));
                        an.Play(cc.name, 0, Mathf.Clamp01(t / Mathf.Max(playing.length, 1e-4f)));
                        an.Update(0f);
                        foreach (Renderer r in go.GetComponentsInChildren<Renderer>())
                            r.sharedMaterial.SetFloat("_LabTime", t);
                        if (kv.Key == "B_flipbook" || kv.Key == "B2_defpalette" || kv.Key == "C_shell")
                        {
                            Renderer target = kv.Key != "C_shell" ? go.GetComponentsInChildren<SkinnedMeshRenderer>().First(r => r.name != "water_shell")
                                : go.GetComponentsInChildren<SkinnedMeshRenderer>().First(r => r.name == "water_shell");
                            target.GetPropertyBlock(mpb);
                            Vector4 v = mpb.GetVector("_MainTex_ST");
                            float[] e = spec.cellST.Skip(cc.cells[i] * 4).Take(4).ToArray();
                            bool ok = Mathf.Abs(v.x - e[0]) < 1e-4f && Mathf.Abs(v.y - e[1]) < 1e-4f && Mathf.Abs(v.z - e[2]) < 1e-4f && Mathf.Abs(v.w - e[3]) < 1e-4f;
                            mpbLog.Add("{\"variant\": \"" + kv.Key + "\", \"clip\": \"" + cc.name + "\", \"frame\": " + i + ", \"cell\": " + cc.cells[i]
                                + ", \"mpbST\": [" + v.x.ToString("R") + ", " + v.y.ToString("R") + ", " + v.z.ToString("R") + ", " + v.w.ToString("R") + "], \"matches\": " + (ok ? "true" : "false")
                                + ", \"materialST\": \"" + target.sharedMaterial.GetVector("_MainTex_ST") + "\", \"material\": \"" + target.sharedMaterial.name + "\"}");
                        }
                        cam.Render();
                        RenderTexture.active = rt;
                        read.ReadPixels(new Rect(0, 0, W, H), 0, 0);
                        read.Apply();
                        RenderTexture.active = null;
                        string dir = Path.Combine(spec.outDir, kv.Key);
                        Directory.CreateDirectory(dir);
                        File.WriteAllBytes(Path.Combine(dir, cc.name + "_" + i.ToString("00") + ".png"), read.EncodeToPNG());
                        go.SetActive(false);
                    }
                }
            }
            Log("animatorMaterialST", "[\n  " + string.Join(",\n  ", mpbLog) + "\n ]");
            Log("variants", "[" + string.Join(", ", variants.Keys.Select(k => "\"" + k + "\"")) + "]");
            File.WriteAllText(Path.Combine(spec.outDir, "lab_report.json"), Report.ToString() + "\n}\n");
        }

        private static string PathTo(Transform skin, Transform root, string childName)
        {
            return AnimationUtility.CalculateTransformPath(skin.parent.Find(childName), root);
        }

        private static void AddSteppedST(AnimationClip clip, string path, int[] cells, float[] cellST)
        {
            string[] comp = { "x", "y", "z", "w" };
            for (int c = 0; c < 4; c++)
            {
                var keys = new List<Keyframe>();
                for (int i = 0; i < cells.Length; i++)
                {
                    float t = i == 0 ? 0f : (i + 0.5f) / 12f; // DEF frame i is sampled at (i+1)/12
                    var k = new Keyframe(t, cellST[cells[i] * 4 + c]) { inTangent = float.PositiveInfinity, outTangent = float.PositiveInfinity };
                    keys.Add(k);
                }
                var curve = new AnimationCurve(keys.ToArray());
                for (int i = 0; i < curve.length; i++)
                {
                    AnimationUtility.SetKeyLeftTangentMode(curve, i, AnimationUtility.TangentMode.Constant);
                    AnimationUtility.SetKeyRightTangentMode(curve, i, AnimationUtility.TangentMode.Constant);
                }
                AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(SkinnedMeshRenderer), "material._MainTex_ST." + comp[c]), curve);
            }
        }

        private static Transform AddSkinnedChild(SkinnedMeshRenderer skin, Mesh mesh, Material mat, string name)
        {
            GameObject child = new GameObject(name);
            child.transform.SetParent(skin.transform.parent, false);
            child.transform.localPosition = skin.transform.localPosition;
            child.transform.localRotation = skin.transform.localRotation;
            child.transform.localScale = skin.transform.localScale;
            SkinnedMeshRenderer r = child.AddComponent<SkinnedMeshRenderer>();
            r.sharedMesh = mesh;
            r.bones = skin.bones;
            r.rootBone = skin.rootBone;
            r.sharedMaterial = mat;
            r.updateWhenOffscreen = true;
            r.forceMatrixRecalculationPerRender = true;
            return child.transform;
        }

        private static Mesh SubsetMesh(Mesh src, bool water, string name)
        {
            Mesh m = UnityEngine.Object.Instantiate(src);
            m.name = src.name + "_" + name;
            Color[] col = src.colors;
            var tris = new List<int>();
            for (int sub = 0; sub < src.subMeshCount; sub++)
            {
                int[] t = src.GetTriangles(sub);
                for (int i = 0; i < t.Length; i += 3)
                {
                    bool w = col[t[i]].r > 0.5f && col[t[i + 1]].r > 0.5f && col[t[i + 2]].r > 0.5f;
                    if (w == water) { tris.Add(t[i]); tris.Add(t[i + 1]); tris.Add(t[i + 2]); }
                }
            }
            m.subMeshCount = 1;
            m.SetTriangles(tris, 0);
            return m;
        }

        private static Vector2[] CylindricalUv(Mesh m, Spec spec)
        {
            Vector3[] v = m.vertices;
            Color[] col = m.colors;
            Vector3 fwd = B2U(spec.camForward);
            float seam = Mathf.Atan2(-fwd.z, -fwd.x);
            // one tile spans the column's circumference (C ~= 1.9 units); v runs down the column and out along the foam
            float r0 = 0.3f, C = 1.9f;
            var uv = new Vector2[v.Length];
            for (int i = 0; i < v.Length; i++)
            {
                float a = Mathf.Atan2(v[i].z, v[i].x) - seam;
                a = Mathf.Repeat(a + Mathf.PI, 2 * Mathf.PI) - Mathf.PI;
                float r = new Vector2(v[i].x, v[i].z).magnitude;
                float along = v[i].y - Mathf.Max(0f, r - r0);
                uv[i] = new Vector2(a / (2 * Mathf.PI) + 0.5f, along / C);
            }
            return uv;
        }

        private static Material NewMat(Texture tex)
        {
            Material m = new Material(_shader) { mainTexture = tex };
            m.SetFloat("_Cull", 2f);
            return m;
        }

        private static Texture2D ImportTexture(string path, TextureWrapMode wrap)
        {
            TextureImporter imp = AssetImporter.GetAtPath(path) as TextureImporter;
            if (imp == null) throw new InvalidOperationException("texture did not import: " + path);
            imp.textureType = TextureImporterType.Default;
            imp.mipmapEnabled = true;
            imp.wrapMode = wrap;
            imp.npotScale = TextureImporterNPOTScale.None;
            imp.maxTextureSize = 8192;
            imp.textureCompression = TextureImporterCompression.Uncompressed;
            imp.alphaIsTransparency = true;
            imp.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }

        private static Vector4 ToV4(float[] a) => new Vector4(a[0], a[1], a[2], a.Length > 3 ? a[3] : 0);
        private static Vector3 B2U(float[] b) => new Vector3(-b[0], b[2], -b[1]);
    }
}
