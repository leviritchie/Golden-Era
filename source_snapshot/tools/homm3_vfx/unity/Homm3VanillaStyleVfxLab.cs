// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/vanilla_style_lab.py. Editor-only lab; NOT a delivery path.
// Vanilla-style VFX preview. One run renders several panels, each a body + effects under its own orthographic camera,
// to linear half-float buffers (Python adds the PPv2-like bloom and composes the sheets and videos):
//   old      the def_retarget GLB under the Hex/Lit replica with the current unit-look layers: uvAtlas body cell per
//            DEF key, defFlipbook quads (Sprites/Default, point filter, view billboard at the anchor bone) and the
//            effectLight point light (floor / fitted per key).
//   new      the same GLB and clip under the Hex/Lit + emission replica, with vanilla-recipe ParticleSystems
//            (tools/homm3_vfx/vanilla_ps_recipe.py) parented to bones and triggered at DEF-key times; particle
//            Lights-module flashes light the body through the replica's point-light loop.
//   vanilla  a vanilla unit's posed mesh (tools/homm3_style_compare/extract_native.py) with its own emission and its
//            own vanilla effect recipes on its own bones.
// ParticleSystems are rebuilt through the public API from the recipe (MinMaxCurves / gradients / modules as
// serialized in the game) and stepped with Simulate at 60 Hz. Particle materials use lab-only, source-pinned
// replicas. Unsupported shaders are logged for legacy pages; the water template requires every selected system
// and material to render and fails closed on any omission. Sub-emitters are not wired (logged).
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace OldenEra.Homm3Vfx
{
    public static class Homm3VanillaStyleVfxLab
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

        // ------------------------------------------------------------------ recipe classes
        [Serializable] public sealed class MMC { public int mode; public float scalar, minScalar; public float[] maxKeys, minKeys; }
        [Serializable] public sealed class MMG { public int mode, gradMode; public float[] maxColor, minColor, maxC, maxA, minC, minA; }
        [Serializable] public sealed class Burst { public float time; public MMC count; public int cycles; public float interval, probability; }
        [Serializable] public sealed class EmissionM { public bool enabled; public MMC rate, rateDist; public Burst[] bursts; }
        [Serializable] public sealed class ShapeM
        {
            public bool enabled, alignToDirection; public int type, arcMode, meshSpawnMode;
            public float angle, length, radius, radiusThickness, arc, donutRadius, randomDirection, sphericalDirection, randomPosition;
            public float[] boxThickness, position, rotation, scale; public string mesh;
        }
        [Serializable] public sealed class ColorM { public bool enabled; public MMG gradient; }
        [Serializable] public sealed class Axes3 { public bool enabled, separate; public MMC x, y, z; }
        [Serializable] public sealed class VelM { public bool enabled, world; public MMC x, y, z, orbitalX, orbitalY, orbitalZ, radial, speedModifier; }
        [Serializable] public sealed class ForceM { public bool enabled, world; public MMC x, y, z; }
        [Serializable] public sealed class LimitM { public bool enabled, separate, dragBySize, dragByVelocity, world; public MMC x, y, z, magnitude, drag; public float dampen; }
        [Serializable] public sealed class NoiseM
        {
            public bool enabled, separate, damping; public MMC x, y, z, scrollSpeed, positionAmount, rotationAmount, sizeAmount;
            public float frequency, octaveMultiplier, octaveScale; public int octaves, quality;
        }
        [Serializable] public sealed class UVM { public bool enabled; public int mode, timeMode, tilesX, tilesY, animationType, rowIndex, rowMode; public float fps, cycles; public MMC frameOverTime, startFrame; }
        [Serializable] public sealed class TrailM
        {
            public bool enabled, world, dieWithParticles, sizeAffectsWidth, sizeAffectsLifetime, inheritParticleColor;
            public int mode, textureMode, ribbonCount; public float ratio, minVertexDistance; public MMC lifetime, widthOverTrail; public MMG colorOverLifetime, colorOverTrail;
        }
        [Serializable] public sealed class LightTmpl { public int type; public float[] color; public float intensity, range; }
        [Serializable] public sealed class LightsM { public bool enabled, random, useColor, useRange, useIntensity, sizeAffectsRange, alphaAffectsIntensity; public float ratio; public int maxLights; public MMC rangeCurve, intensityCurve; public LightTmpl template; }
        [Serializable] public sealed class CustomM { public bool enabled; public int mode0, count0, mode1, count1; public MMC[] v0, v1; public MMG color0, color1; }
        [Serializable] public sealed class SubEmit { public int node; }
        [Serializable] public sealed class SubM { public bool enabled; public SubEmit[] emitters; }
        [Serializable]
        public sealed class PSDef
        {
            public float duration, simulationSpeed, flipRotation; public bool looping, prewarm, size3D, rotation3D;
            public int simSpace, scalingMode, maxParticles;
            public MMC startDelay, lifetime, speed, sizeX, sizeY, sizeZ, rotX, rotY, rotZ, gravity; public MMG startColor;
            public EmissionM emission; public ShapeM shape; public ColorM color; public Axes3 size, rotation; public VelM velocity; public ForceM force;
            public LimitM limit; public NoiseM noise; public UVM uv; public TrailM trail; public LightsM lights; public CustomM custom; public SubM sub;
        }
        [Serializable]
        public sealed class RendDef
        {
            public bool enabled, allowRoll; public int renderMode, sortMode, sortingOrder, alignment; public string material, trailMaterial, mesh;
            public float lengthScale, velocityScale, cameraVelocityScale, sortingFudge, minParticleSize, maxParticleSize, normalDirection;
            public float[] pivot, flip;
        }
        [Serializable] public sealed class NodeDef { public string name; public int parent; public float[] pos, rot, scale; public bool hasPS; public PSDef ps; public RendDef renderer; }
        [Serializable] public sealed class RecipeDef { public string source, parentName; public NodeDef[] nodes; }

        [Serializable] public sealed class TexProp { public string prop, tex; public float[] scale, offset; }
        [Serializable] public sealed class FProp { public string name; public float value; }
        [Serializable] public sealed class CProp { public string name; public float[] rgba; }
        [Serializable] public sealed class MatDef { public string name, shader; public string[] keywords; public TexProp[] textures; public FProp[] floats; public CProp[] colors; }
        [Serializable] public sealed class TexDef { public string name, file; public bool sRGB, mips; public int wrapU, wrapV; }
        [Serializable] public sealed class MeshDef { public string name, file; }
        [Serializable] public sealed class MatLib { public MatDef[] materials; public TexDef[] textures; public MeshDef[] meshes; }

        // ------------------------------------------------------------------ job classes
        [Serializable] public sealed class Trigger { public string clip; public float time; }
        [Serializable]
        public sealed class EffectDef
        {
            public string id, recipeFile, bone; public float[] pos, rot, rootWorldRot, recolor; public float scale = 1f, rateMul = 1f;
            public bool keepRecipeRoot, loopAll, alwaysOn, emitUp, zeroChildPos, recolorMultiply, detachOnTrigger; public int anchorNode = -1; public int[] keepPS;
            public Trigger[] triggers, stops;
        }
        [Serializable] public sealed class FlipKey { public int cell; }
        [Serializable] public sealed class FlipDef { public string clip, bone, sheet; public int tilesX, tilesY; public float sizeX, sizeY; public int[] cells; }
        [Serializable] public sealed class OldLightDef { public string clip, bone; public float towardCamera, range; public float[] rgbLinear, intensity; }
        [Serializable] public sealed class NativeMat { public string albedo, emission; public float[] emissionColor; public float emissionMin, blinkSpeed, blinkPower, cutoff; }
        [Serializable] public sealed class BoneDef { public string name; public float[] m; }
        [Serializable]
        public sealed class BodyDef
        {
            public string kind, glbAssetPath, texture, emissionTex, nativeMeshFile; public float[] emissionColor, cellST;
            public float emissionMin = 1f, blinkSpeed, blinkPower, bodyYawDeg; public NativeMat[] nativeMats; public BoneDef[] bones;
            public float[] flagDirection, flagPower; public float flagSpeed;
            public OverlayDef[] overlays;
        }
        // bodyOverlay: a probed vanilla mesh-renderer material appended to every body SMR (the plugin's
        // battle_body_overlay), shown always or over [start, end) seconds of one clip.
        [Serializable] public sealed class OverlayDef { public string id, material, clip; public float start, end; public bool always; public CProp[] colors; }
        [Serializable] public sealed class ClipDef { public string name; public int keys, frames; public float frameStep; public int[] boilCells; public bool loop; }
        [Serializable]
        public sealed class PanelDef
        {
            public string id; public BodyDef body; public ClipDef[] clips; public EffectDef[] effects; public FlipDef[] flipbooks; public OldLightDef[] oldLights;
            public float[] camRight, camUp, camForward, camCentre, sunTravelUnity; public float orthoSize; public int width, height; public float warmupS;
        }
        [Serializable] public sealed class JobDef { public string schema, assetRoot, materialLib, outDir; public PanelDef[] panels; public bool requireCompleteEffects; }

        private static readonly StringBuilder Report = new StringBuilder();
        private static void Log(string key, string json)
        {
            Report.Append(Report.Length == 0 ? "{\n" : ",\n").Append(" \"").Append(key).Append("\": ").Append(json);
            Debug.Log("HOMM3_VSTYLE " + key + " " + (json.Length > 400 ? json.Substring(0, 400) + "..." : json));
        }

        public static void RunFromCommandLine()
        {
            string[] args = UnityQueueArgs();
            string specPath = null;
            for (int i = 0; i < args.Length - 1; i++) if (args[i] == "-homm3VanillaStyleSpec") specPath = args[i + 1];
            if (string.IsNullOrEmpty(specPath) || !File.Exists(specPath)) throw new InvalidOperationException("-homm3VanillaStyleSpec <file> is required");
            JobDef job = JsonUtility.FromJson<JobDef>(File.ReadAllText(specPath));
            if (job.schema != "homm3_vanilla_style_lab.v1") throw new InvalidOperationException("schema " + job.schema);
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            var lib = JsonUtility.FromJson<MatLib>(File.ReadAllText(job.materialLib));
            var mats = new MaterialCache(job.assetRoot, lib);
            foreach (PanelDef p in job.panels) RunPanel(job, p, mats);
            if (job.requireCompleteEffects && mats.Unsupported.Count != 0)
                throw new InvalidOperationException("selected native effects are unsupported: " + string.Join(", ", mats.Unsupported));
            Log("unsupported", "[" + string.Join(", ", mats.Unsupported.Select(s => "\"" + s + "\"")) + "]");
            File.WriteAllText(Path.Combine(job.outDir, "lab_report.json"), Report.ToString() + "\n}\n");
            Debug.Log("HOMM3_VSTYLE_LAB_OK");
        }

        // ------------------------------------------------------------------ materials / textures / meshes
        private sealed class MaterialCache
        {
            private readonly string root; private readonly MatLib lib;
            private readonly Dictionary<string, Material> mats = new Dictionary<string, Material>();
            private readonly Dictionary<string, Texture2D> texs = new Dictionary<string, Texture2D>();
            private readonly Dictionary<string, Mesh> meshes = new Dictionary<string, Mesh>();
            public readonly HashSet<string> Unsupported = new HashSet<string>();
            public readonly List<Material> All = new List<Material>();
            public MaterialCache(string root, MatLib lib) { this.root = root; this.lib = lib; }

            private static void RequireWaterDonor(MatDef d)
            {
                bool water04 = d.name == "Water_aqualotl_04_vfx";
                bool water06 = d.name == "Naiad_water_06_vfx";
                if (!water04 && !water06) throw new InvalidOperationException("unreplicated Water_fire_stylized material: " + d.name);
                if (d.keywords.Length != 0) throw new InvalidOperationException(d.name + ": water shader keywords changed");
                string[] props = { "_Texture1", "_TextureSample0", "_maskmove2", "_mask" };
                string[] names = { "Water_02_vfx", "TileNoise_07_vfx", "TileNoise_07_vfx", water04 ? "Water_03_vfx" : "Water_04_vfx" };
                if (d.textures.Length != props.Length) throw new InvalidOperationException(d.name + ": water texture set changed");
                for (int i = 0; i < props.Length; i++)
                {
                    TexProp t = d.textures.FirstOrDefault(x => x.prop == props[i]);
                    if (t == null || t.tex != names[i] || t.scale.Length != 2 || t.offset.Length != 2 ||
                        Mathf.Abs(t.scale[0] - 1f) > 1e-4f || Mathf.Abs(t.scale[1] - 1f) > 1e-4f ||
                        Mathf.Abs(t.offset[0]) > 1e-4f || Mathf.Abs(t.offset[1]) > 1e-4f)
                        throw new InvalidOperationException(d.name + ": water texture binding changed at " + props[i]);
                }
                void F(string key, float value)
                {
                    FProp p = d.floats.FirstOrDefault(x => x.name == key);
                    if (p == null || float.IsNaN(p.value) || float.IsInfinity(p.value) || Mathf.Abs(p.value - value) > 1e-3f)
                        throw new InvalidOperationException(d.name + ": water branch property changed at " + key);
                }
                void V(string key, float x, float y, float z, float w)
                {
                    CProp p = d.colors.FirstOrDefault(c => c.name == key);
                    if (p == null || p.rgba.Length != 4 || p.rgba.Any(v => float.IsNaN(v) || float.IsInfinity(v)) ||
                        Mathf.Abs(p.rgba[0] - x) > 1e-3f ||
                        Mathf.Abs(p.rgba[1] - y) > 1e-3f || Mathf.Abs(p.rgba[2] - z) > 1e-3f ||
                        Mathf.Abs(p.rgba[3] - w) > 1e-3f)
                        throw new InvalidOperationException(d.name + ": water vector property changed at " + key);
                }
                F("_lerpmaskmove", 0f); F("_ToggleSwitch104", 1f); F("_Maskonoff", 0f);
                F("_Maskssmoothemin", 0f); F("_Multiplymasks", 1f); F("_maskmultiply", 1f);
                F("_Dissolvefloatcustom", 0f); F("_Dissolvefloat", 2f); F("_Dissolvedivide", 3f);
                F("_Dissolveclampmin", 0f); F("_Dissolveclampmax", 1f);
                F("_Emissionlerpstexture", 1f); F("_minsmoothetexture", 0f); F("_maxsmoothetexture", 1f);
                F("_multiplytexture", 1f); F("_Dissolvelerpoffon", 0f); F("_ToggleSwitch5", 0f);
                F("_Opacitystandartworld", 0f); F("_Opacitytextureworld", 0f); F("_Opacitylerpstexture", 0f);
                F("_Dissolveopacityoffon", 0f); F("_Timemask", 0f); F("_opacity", 1f);
                F("_Smotheopacityrgbaa", 0f); F("_minsmootheopacity", 0f); F("_maxsmootheopacity", 1f);
                F("_Dissolvecoloroffon", water04 ? 0f : 1f);
                F("_Opacitystandartworld2", water04 ? 1f : 0f);
                F("_Worldmultiply", 5f); F("_float1", 1f);
                F("_smotheminmaskmovelerp", water04 ? 0.151336f : 0.35f);
                F("_smoothemaxmaskmovelerp", water04 ? 0.2f : 0.047363f);
                F("_Maskssmoothemax", water04 ? 0.5f : 0.505882f);
                V("_Tilingtexture1", 1f, 1f, 0f, 0f); V("_maskmove2tiling", 1f, 1f, 0f, 0f);
                V("_Dissolvetiling", 1f, 1f, 0f, 0f); V("_Dissolveoffset", 0f, 1f, 0f, 0f);
                V("_Speedmaskmove", 0f, -0.27f, 0f, 0f); V("_Tilingmask", 1f, 1f, 0f, 0f);
                if (water06) V("_Dissolvecolor", 0f, 0.296912f, 1.308703f, 1f);
            }

            public Texture2D Tex(string name)
            {
                if (texs.TryGetValue(name, out var t)) return t;
                TexDef d = lib.textures.First(x => x.name == name);
                string path = root + "/" + d.file;
                var imp = AssetImporter.GetAtPath(path) as TextureImporter;
                if (imp == null) throw new InvalidOperationException("texture did not import: " + path);
                imp.textureType = TextureImporterType.Default;
                imp.sRGBTexture = d.sRGB;
                imp.mipmapEnabled = d.mips;
                imp.filterMode = FilterMode.Bilinear;
                imp.wrapModeU = (TextureWrapMode)d.wrapU;
                imp.wrapModeV = (TextureWrapMode)d.wrapV;
                imp.textureCompression = TextureImporterCompression.Uncompressed;
                imp.npotScale = TextureImporterNPOTScale.None;
                imp.alphaIsTransparency = false;
                imp.SaveAndReimport();
                t = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
                texs[name] = t;
                return t;
            }

            public Material Get(string name)
            {
                if (string.IsNullOrEmpty(name)) return null;
                if (mats.TryGetValue(name, out var m)) return m;
                MatDef d = lib.materials.First(x => x.name == name);
                // Only pinned shader/material pairs have lab replicas. Unknown Water_fire_stylized variants fail
                // rather than drawing a plausible but wrong water sheet.
                int dissolve = d.shader.StartsWith("magic/test/Disappearance_0") ? d.shader[d.shader.Length - 1] - '0' : 0;
                bool water = d.shader == "magic/Water_fire_stylized";
                bool fresnel = d.shader == "magic/Fresnel";
                if (water) RequireWaterDonor(d);
                if (!water && !fresnel && d.shader != "magic/VfxUber" && (dissolve < 1 || dissolve > 3))
                { Unsupported.Add(name + " (" + d.shader + ")"); mats[name] = null; return null; }
                string shPath = fresnel ? "Assets/Homm3VfxLab/Shaders/Homm3VfxFresnelReplica.shader"
                              : water ? "Assets/Homm3VfxLab/Shaders/Homm3VfxWaterFireStylizedReplica.shader"
                                      : dissolve > 0 ? "Assets/Homm3VfxLab/Shaders/Homm3VfxDisappearanceReplica.shader"
                                                     : "Assets/Homm3VfxLab/Shaders/Homm3VfxUberReplica.shader";
                Shader sh = AssetDatabase.LoadAssetAtPath<Shader>(shPath);
                if (sh == null) throw new InvalidOperationException("replica shader missing: " + shPath);
                m = new Material(sh) { name = name };
                if (dissolve > 0) m.SetFloat("_Variant", dissolve);
                if (fresnel)
                {
                    // t1 (slide mask) is only read when _SlideMask != 0; its property name is not pinned, so a material
                    // that needs it must list exactly one texture besides _MainTex.
                    FProp slide = d.floats.FirstOrDefault(f => f.name == "_SlideMask");
                    var others = d.textures.Where(t => t.prop != "_MainTex").ToArray();
                    if (slide != null && slide.value != 0)
                    {
                        if (others.Length != 1) throw new InvalidOperationException(d.name + ": _SlideMask on but " + others.Length + " candidate slide textures");
                        m.SetTexture("_SlideTex", Tex(others[0].tex));
                    }
                }
                foreach (TexProp t in d.textures)
                {
                    if (!m.HasProperty(t.prop))
                    {
                        if (water) throw new InvalidOperationException(d.name + ": water replica lacks " + t.prop);
                        continue;
                    }
                    m.SetTexture(t.prop, Tex(t.tex));
                    m.SetTextureScale(t.prop, new Vector2(t.scale[0], t.scale[1]));
                    m.SetTextureOffset(t.prop, new Vector2(t.offset[0], t.offset[1]));
                }
                foreach (FProp f in d.floats) if (m.HasProperty(f.name)) m.SetFloat(f.name, f.value);
                foreach (CProp c in d.colors) if (m.HasProperty(c.name)) m.SetColor(c.name, new Color(c.rgba[0], c.rgba[1], c.rgba[2], c.rgba[3]));
                m.SetFloat("_UseTwo", d.keywords.Contains("_TWO_TEXTURES") ? 1 : 0);
                m.SetFloat("_UseCamOffset", d.keywords.Contains("_ACTIVE_CAMERA_OFFSET_ON") ? 1 : 0);
                mats[name] = m;
                All.Add(m);
                return m;
            }

            public Mesh MeshByName(string name)
            {
                if (string.IsNullOrEmpty(name)) return null;
                if (meshes.TryGetValue(name, out var mesh)) return mesh;
                MeshDef d = lib.meshes.FirstOrDefault(x => x.name == name);
                if (d == null) { Unsupported.Add("mesh " + name); return null; }
                mesh = ParseObj(Path.Combine(Application.dataPath, "..", root, d.file), name);
                meshes[name] = mesh;
                return mesh;
            }
        }

        // UnityPy exports OBJ with x negated (right-handed); negate back to Unity space.
        private static Mesh ParseObj(string path, string name)
        {
            var v = new List<Vector3>(); var vt = new List<Vector2>(); var vn = new List<Vector3>();
            var outV = new List<Vector3>(); var outUv = new List<Vector2>(); var outN = new List<Vector3>(); var tris = new List<int>();
            var map = new Dictionary<string, int>();
            foreach (string raw in File.ReadAllLines(path))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line[0] == '#') continue;
                string[] p = line.Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
                float F(int i) => float.Parse(p[i], CultureInfo.InvariantCulture);
                if (p[0] == "v") v.Add(new Vector3(-F(1), F(2), F(3)));
                else if (p[0] == "vt") vt.Add(new Vector2(F(1), F(2)));
                else if (p[0] == "vn") vn.Add(new Vector3(-F(1), F(2), F(3)));
                else if (p[0] == "f")
                {
                    var idx = new List<int>();
                    for (int i = 1; i < p.Length; i++)
                    {
                        if (!map.TryGetValue(p[i], out int k))
                        {
                            string[] q = p[i].Split('/');
                            int vi = int.Parse(q[0]) - 1;
                            outV.Add(v[vi]);
                            outUv.Add(q.Length > 1 && q[1].Length > 0 ? vt[int.Parse(q[1]) - 1] : Vector2.zero);
                            outN.Add(q.Length > 2 && q[2].Length > 0 ? vn[int.Parse(q[2]) - 1] : Vector3.up);
                            k = outV.Count - 1;
                            map[p[i]] = k;
                        }
                        idx.Add(k);
                    }
                    for (int i = 1; i + 1 < idx.Count; i++) { tris.Add(idx[0]); tris.Add(idx[i + 1]); tris.Add(idx[i]); }
                }
            }
            var mesh = new Mesh { name = name, indexFormat = outV.Count > 65535 ? UnityEngine.Rendering.IndexFormat.UInt32 : UnityEngine.Rendering.IndexFormat.UInt16 };
            mesh.SetVertices(outV); mesh.SetUVs(0, outUv); mesh.SetNormals(outN); mesh.SetTriangles(tris, 0);
            mesh.RecalculateBounds();
            return mesh;
        }

        // ------------------------------------------------------------------ curve helpers
        private static AnimationCurve Curve(float[] k)
        {
            var c = new AnimationCurve();
            if (k == null) return c;
            for (int i = 0; i + 3 < k.Length; i += 4) c.AddKey(new Keyframe(k[i], k[i + 1], k[i + 2], k[i + 3]));
            return c;
        }
        private static ParticleSystem.MinMaxCurve C(MMC m, float mul = 1f)
        {
            if (m == null) return new ParticleSystem.MinMaxCurve(0f);
            switch (m.mode)
            {
                case 1: return new ParticleSystem.MinMaxCurve(m.scalar * mul, Curve(m.maxKeys));
                case 2: return new ParticleSystem.MinMaxCurve(m.scalar * mul, Curve(m.minKeys), Curve(m.maxKeys));
                case 3: return new ParticleSystem.MinMaxCurve(m.minScalar * mul, m.scalar * mul);
                default: return new ParticleSystem.MinMaxCurve(m.scalar * mul);
            }
        }
        private static float Eval(MMC m, float t)
        {
            if (m == null) return 0f;
            switch (m.mode)
            {
                case 1: return m.scalar * Curve(m.maxKeys).Evaluate(t);
                case 2: return m.scalar * 0.5f * (Curve(m.minKeys).Evaluate(t) + Curve(m.maxKeys).Evaluate(t));
                case 3: return 0.5f * (m.minScalar + m.scalar);
                default: return m.scalar;
            }
        }
        private static Gradient Grad(float[] c, float[] a, int mode)
        {
            var g = new Gradient();
            var ck = new List<GradientColorKey>(); var ak = new List<GradientAlphaKey>();
            for (int i = 0; c != null && i + 3 < c.Length; i += 4) ck.Add(new GradientColorKey(new Color(c[i + 1], c[i + 2], c[i + 3]), c[i]));
            for (int i = 0; a != null && i + 1 < a.Length; i += 2) ak.Add(new GradientAlphaKey(a[i + 1], a[i]));
            if (ck.Count == 0) ck.Add(new GradientColorKey(Color.white, 0));
            if (ak.Count == 0) ak.Add(new GradientAlphaKey(1, 0));
            g.SetKeys(ck.ToArray(), ak.ToArray());
            g.mode = (GradientMode)mode;
            return g;
        }
        private static Color Col(float[] c) => c == null ? Color.white : new Color(c[0], c[1], c[2], c[3]);
        private static ParticleSystem.MinMaxGradient G(MMG m)
        {
            if (m == null) return new ParticleSystem.MinMaxGradient(Color.white);
            switch (m.mode)
            {
                case 1: return new ParticleSystem.MinMaxGradient(Grad(m.maxC, m.maxA, m.gradMode));
                case 2: return new ParticleSystem.MinMaxGradient(Col(m.minColor), Col(m.maxColor));
                case 3: return new ParticleSystem.MinMaxGradient(Grad(m.minC, m.minA, m.gradMode), Grad(m.maxC, m.maxA, m.gradMode));
                case 4: return new ParticleSystem.MinMaxGradient(Grad(m.maxC, m.maxA, m.gradMode)) { mode = ParticleSystemGradientMode.RandomColor };
                default: return new ParticleSystem.MinMaxGradient(Col(m.maxColor));
            }
        }
        // recolorMode multiply: every colour key times the target (the compiler requires target <= 1).
        private static MMG MultiplyKeys(MMG m, float[] target)
        {
            if (m == null || target == null || target.Length < 3) return m;
            float[] Keys(float[] c)
            {
                if (c == null) return null; var o = (float[])c.Clone();
                for (int i = 0; i + 3 < c.Length; i += 4) for (int k = 0; k < 3; k++) o[i + 1 + k] = c[i + 1 + k] * target[k];
                return o;
            }
            float[] Rgba(float[] c)
            {
                if (c == null) return null; var o = (float[])c.Clone();
                for (int k = 0; k < 3; k++) o[k] = c[k] * target[k]; return o;
            }
            return new MMG { mode = m.mode, gradMode = m.gradMode, maxColor = Rgba(m.maxColor), minColor = Rgba(m.minColor), maxC = Keys(m.maxC), minC = Keys(m.minC), maxA = m.maxA, minA = m.minA };
        }
        // Hue swap that keeps each colour key's luminance (Rec.709) and alpha: rgb' = lum(rgb) * target / lum(target).
        private static MMG Recolor(MMG m, float[] target)
        {
            if (m == null || target == null || target.Length < 3) return m;
            float tl = Mathf.Max(1e-4f, 0.2126f * target[0] + 0.7152f * target[1] + 0.0722f * target[2]);
            float[] Rgba(float[] c)
            {
                if (c == null) return null; var o = (float[])c.Clone();
                float l = 0.2126f * c[0] + 0.7152f * c[1] + 0.0722f * c[2];
                for (int k = 0; k < 3; k++) o[k] = l * target[k] / tl; return o;
            }
            float[] Keys(float[] c)
            {
                if (c == null) return null; var o = (float[])c.Clone();
                for (int i = 0; i + 3 < c.Length; i += 4)
                {
                    float l = 0.2126f * c[i + 1] + 0.7152f * c[i + 2] + 0.0722f * c[i + 3];
                    for (int k = 0; k < 3; k++) o[i + 1 + k] = l * target[k] / tl;
                }
                return o;
            }
            return new MMG { mode = m.mode, gradMode = m.gradMode, maxColor = Rgba(m.maxColor), minColor = Rgba(m.minColor), maxC = Keys(m.maxC), minC = Keys(m.minC), maxA = m.maxA, minA = m.minA };
        }
        private static Vector3 V3(float[] a, Vector3 d) => a == null || a.Length < 3 ? d : new Vector3(a[0], a[1], a[2]);
        // follow=release (runtime Homm3MeshFx detach): back under its bone with the build-time local pose.
        private static void Reattach(Fx fx)
        {
            if (!fx.detached) return;
            fx.root.SetParent(fx.bone, false);
            fx.root.localPosition = fx.homePos; fx.root.localRotation = fx.homeRot; fx.root.localScale = fx.homeScale;
            fx.detached = false;
        }

        // ------------------------------------------------------------------ build a recipe
        private sealed class Fx
        {
            public EffectDef def; public Transform root, bone, anchor; public List<ParticleSystem> systems = new List<ParticleSystem>();
            public List<(ParticleSystem ps, LightsM lm)> lights = new List<(ParticleSystem, LightsM)>();
            public bool playing, detached; public int fired;
            public Vector3 homePos, homeScale; public Quaternion homeRot;
        }

        private static Fx BuildEffect(EffectDef e, Transform bone, MaterialCache mats)
        {
            RecipeDef r = JsonUtility.FromJson<RecipeDef>(File.ReadAllText(e.recipeFile));
            var fx = new Fx { def = e, bone = bone };
            var gos = new Transform[r.nodes.Length];
            for (int i = 0; i < r.nodes.Length; i++)
            {
                NodeDef n = r.nodes[i];
                var go = new GameObject(e.id + ":" + n.name);
                gos[i] = go.transform;
                go.transform.SetParent(i == 0 ? bone : gos[n.parent], false);
                go.transform.localPosition = V3(n.pos, Vector3.zero);
                go.transform.localRotation = n.rot != null && n.rot.Length == 4 ? new Quaternion(n.rot[0], n.rot[1], n.rot[2], n.rot[3]) : Quaternion.identity;
                go.transform.localScale = V3(n.scale, Vector3.one);
                if (i > 0 && e.zeroChildPos) go.transform.localPosition = Vector3.zero;
                if (i == e.anchorNode) fx.anchor = go.transform;
                if (!n.hasPS) continue;
                if (e.keepPS != null && e.keepPS.Length > 0 && Array.IndexOf(e.keepPS, i) < 0) continue;
                var ps = go.AddComponent<ParticleSystem>();
                Configure(ps, go.GetComponent<ParticleSystemRenderer>(), n, mats, e);
                fx.systems.Add(ps);
                if (n.ps.lights != null && n.ps.lights.enabled) fx.lights.Add((ps, n.ps.lights));
            }
            fx.root = gos[0];
            if (!e.keepRecipeRoot)
            {
                fx.root.localPosition = V3(e.pos, Vector3.zero);
                fx.root.localRotation = e.rot != null && e.rot.Length == 4 ? new Quaternion(e.rot[0], e.rot[1], e.rot[2], e.rot[3]) : Quaternion.identity;
                Vector3 ls = bone.lossyScale;
                float s = e.scale / Mathf.Max(1e-6f, (Mathf.Abs(ls.x) + Mathf.Abs(ls.y) + Mathf.Abs(ls.z)) / 3f);
                fx.root.localScale = Vector3.one * s;
                foreach (ParticleSystem ps in fx.systems) { var main = ps.main; main.scalingMode = ParticleSystemScalingMode.Hierarchy; }
            }
            fx.homePos = fx.root.localPosition; fx.homeRot = fx.root.localRotation; fx.homeScale = fx.root.localScale;
            return fx;
        }

        private static void Configure(ParticleSystem ps, ParticleSystemRenderer r, NodeDef n, MaterialCache mats, EffectDef e)
        {
            PSDef d = n.ps;
            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            ps.useAutoRandomSeed = false;
            ps.randomSeed = (uint)(n.name.GetHashCode() & 0x7fffffff) ^ (uint)e.id.GetHashCode();
            var main = ps.main;
            main.duration = Mathf.Max(0.05f, d.duration);
            main.loop = d.looping || e.loopAll;
            main.prewarm = false;
            main.playOnAwake = false;
            main.startDelay = C(d.startDelay);
            main.simulationSpeed = d.simulationSpeed <= 0 ? 1 : d.simulationSpeed;
            main.simulationSpace = (ParticleSystemSimulationSpace)Mathf.Clamp(d.simSpace, 0, 1);
            main.scalingMode = (ParticleSystemScalingMode)d.scalingMode;
            main.startLifetime = C(d.lifetime);
            main.startSpeed = C(d.speed);
            main.startSize3D = d.size3D;
            if (d.size3D) { main.startSizeX = C(d.sizeX); main.startSizeY = C(d.sizeY); main.startSizeZ = C(d.sizeZ); }
            else main.startSize = C(d.sizeX);
            main.startRotation3D = d.rotation3D;
            if (d.rotation3D) { main.startRotationX = C(d.rotX); main.startRotationY = C(d.rotY); main.startRotationZ = C(d.rotZ); }
            else main.startRotation = C(d.rotZ);
            main.flipRotation = d.flipRotation;
            // recolorMode multiply (materials without _Color): only the gradient is multiplied, as the plugin does
            main.startColor = G(e.recolorMultiply ? d.startColor : Recolor(d.startColor, e.recolor));
            main.gravityModifier = C(d.gravity);
            main.maxParticles = Mathf.Max(1, d.maxParticles);

            var em = ps.emission;
            em.enabled = d.emission.enabled;
            em.rateOverTime = C(d.emission.rate, e.rateMul);
            em.rateOverDistance = C(d.emission.rateDist);
            em.SetBursts((d.emission.bursts ?? new Burst[0]).Select(b => new ParticleSystem.Burst(b.time, C(b.count), Mathf.Max(1, b.cycles), Mathf.Max(0.0001f, b.interval)) { probability = b.probability }).ToArray());

            var sh = ps.shape;
            ShapeM s = d.shape;
            sh.enabled = s.enabled;
            int type = s.type; float rt = s.radiusThickness;
            if (type == 1) { type = 0; rt = 0; } else if (type == 3) { type = 2; rt = 0; } else if (type == 7) { type = 4; rt = 0; } else if (type == 9) { type = 8; rt = 0; }
            if (type == 13 || type == 14 || type == 19 || type == 20) type = 0;
            if (type == 6)
            {
                Mesh m = mats.MeshByName(s.mesh);
                if (m == null) type = 0; else sh.mesh = m;
            }
            sh.shapeType = (ParticleSystemShapeType)type;
            sh.angle = s.angle; sh.length = s.length; sh.radius = s.radius; sh.radiusThickness = rt; sh.arc = s.arc;
            sh.arcMode = (ParticleSystemShapeMultiModeValue)s.arcMode;
            sh.boxThickness = V3(s.boxThickness, Vector3.zero);
            sh.position = V3(s.position, Vector3.zero); sh.rotation = V3(s.rotation, Vector3.zero); sh.scale = V3(s.scale, Vector3.one);
            sh.donutRadius = s.donutRadius; sh.randomDirectionAmount = s.randomDirection; sh.sphericalDirectionAmount = s.sphericalDirection;
            sh.randomPositionAmount = s.randomPosition; sh.alignToDirection = s.alignToDirection;

            var col = ps.colorOverLifetime; col.enabled = d.color.enabled; if (d.color.enabled) col.color = G(e.recolorMultiply ? MultiplyKeys(d.color.gradient, e.recolor) : Recolor(d.color.gradient, e.recolor));
            var size = ps.sizeOverLifetime; size.enabled = d.size.enabled;
            if (d.size.enabled) { size.separateAxes = d.size.separate; if (d.size.separate) { size.x = C(d.size.x); size.y = C(d.size.y); size.z = C(d.size.z); } else size.size = C(d.size.x); }
            var rot = ps.rotationOverLifetime; rot.enabled = d.rotation.enabled;
            if (d.rotation.enabled) { rot.separateAxes = d.rotation.separate; if (d.rotation.separate) { rot.x = C(d.rotation.x); rot.y = C(d.rotation.y); } rot.z = C(d.rotation.z); }
            var vel = ps.velocityOverLifetime; vel.enabled = d.velocity.enabled;
            if (d.velocity.enabled)
            {
                vel.space = d.velocity.world ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
                vel.x = C(d.velocity.x); vel.y = C(d.velocity.y); vel.z = C(d.velocity.z);
                vel.orbitalX = C(d.velocity.orbitalX); vel.orbitalY = C(d.velocity.orbitalY); vel.orbitalZ = C(d.velocity.orbitalZ);
                vel.radial = C(d.velocity.radial); vel.speedModifier = C(d.velocity.speedModifier);
            }
            var force = ps.forceOverLifetime; force.enabled = d.force.enabled;
            if (d.force.enabled) { force.space = d.force.world ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local; force.x = C(d.force.x); force.y = C(d.force.y); force.z = C(d.force.z); }
            var lim = ps.limitVelocityOverLifetime; lim.enabled = d.limit.enabled;
            if (d.limit.enabled)
            {
                lim.separateAxes = d.limit.separate;
                if (d.limit.separate) { lim.limitX = C(d.limit.x); lim.limitY = C(d.limit.y); lim.limitZ = C(d.limit.z); } else lim.limit = C(d.limit.magnitude);
                lim.dampen = d.limit.dampen; lim.drag = C(d.limit.drag);
                lim.multiplyDragByParticleSize = d.limit.dragBySize; lim.multiplyDragByParticleVelocity = d.limit.dragByVelocity;
                lim.space = d.limit.world ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
            }
            var no = ps.noise; no.enabled = d.noise.enabled;
            if (d.noise.enabled)
            {
                no.separateAxes = d.noise.separate;
                if (d.noise.separate) { no.strengthX = C(d.noise.x); no.strengthY = C(d.noise.y); no.strengthZ = C(d.noise.z); } else no.strength = C(d.noise.x);
                no.frequency = d.noise.frequency; no.damping = d.noise.damping; no.octaveCount = Mathf.Max(1, d.noise.octaves);
                no.octaveMultiplier = d.noise.octaveMultiplier; no.octaveScale = d.noise.octaveScale; no.quality = (ParticleSystemNoiseQuality)d.noise.quality;
                no.scrollSpeed = C(d.noise.scrollSpeed); no.positionAmount = C(d.noise.positionAmount); no.rotationAmount = C(d.noise.rotationAmount); no.sizeAmount = C(d.noise.sizeAmount);
            }
            var uv = ps.textureSheetAnimation; uv.enabled = d.uv.enabled && d.uv.mode == 0;
            if (uv.enabled)
            {
                uv.mode = ParticleSystemAnimationMode.Grid;
                uv.numTilesX = Mathf.Max(1, d.uv.tilesX); uv.numTilesY = Mathf.Max(1, d.uv.tilesY);
                uv.animation = (ParticleSystemAnimationType)d.uv.animationType;
                uv.rowMode = (ParticleSystemAnimationRowMode)d.uv.rowMode; uv.rowIndex = d.uv.rowIndex;
                uv.timeMode = (ParticleSystemAnimationTimeMode)d.uv.timeMode; uv.fps = d.uv.fps;
                uv.frameOverTime = C(d.uv.frameOverTime);
                int frames = d.uv.animationType == 1 ? uv.numTilesX : uv.numTilesX * uv.numTilesY;
                uv.startFrame = C(d.uv.startFrame, frames);
                uv.cycleCount = Mathf.Max(1, Mathf.RoundToInt(d.uv.cycles));
            }
            var tr = ps.trails; tr.enabled = d.trail.enabled;
            if (d.trail.enabled)
            {
                tr.mode = (ParticleSystemTrailMode)d.trail.mode; tr.ratio = d.trail.ratio; tr.lifetime = C(d.trail.lifetime);
                tr.minVertexDistance = d.trail.minVertexDistance; tr.textureMode = (ParticleSystemTrailTextureMode)d.trail.textureMode;
                tr.worldSpace = d.trail.world; tr.dieWithParticles = d.trail.dieWithParticles; tr.sizeAffectsWidth = d.trail.sizeAffectsWidth;
                tr.sizeAffectsLifetime = d.trail.sizeAffectsLifetime; tr.inheritParticleColor = d.trail.inheritParticleColor;
                tr.colorOverLifetime = G(Recolor(d.trail.colorOverLifetime, e.recolor)); tr.widthOverTrail = C(d.trail.widthOverTrail); tr.colorOverTrail = G(Recolor(d.trail.colorOverTrail, e.recolor));
                tr.ribbonCount = Mathf.Max(1, d.trail.ribbonCount);
            }
            var cd = ps.customData; cd.enabled = d.custom != null && d.custom.enabled;
            if (cd.enabled)
            {
                void Stream(ParticleSystemCustomData s2, int mode, int count, MMC[] v, MMG c)
                {
                    cd.SetMode(s2, (ParticleSystemCustomDataMode)mode);
                    if (mode == 1) { cd.SetVectorComponentCount(s2, count); for (int i = 0; i < Mathf.Min(count, v.Length); i++) cd.SetVector(s2, i, C(v[i])); }
                    else if (mode == 2) cd.SetColor(s2, G(c));
                }
                Stream(ParticleSystemCustomData.Custom1, d.custom.mode0, d.custom.count0, d.custom.v0, d.custom.color0);
                Stream(ParticleSystemCustomData.Custom2, d.custom.mode1, d.custom.count1, d.custom.v1, d.custom.color1);
            }
            if (d.sub != null && d.sub.enabled && d.sub.emitters != null && d.sub.emitters.Length > 0) mats.Unsupported.Add("subEmitters on " + n.name);

            RendDef rd = n.renderer;
            Material mat = rd == null ? null : mats.Get(rd.material);
            Material tmat = rd == null ? null : mats.Get(rd.trailMaterial);
            r.enabled = rd != null && rd.enabled && (mat != null || (rd.renderMode == 5 && tmat != null));
            if (rd == null) return;
            r.renderMode = (ParticleSystemRenderMode)rd.renderMode;
            if (rd.renderMode == 4)
            {
                Mesh m = mats.MeshByName(rd.mesh);
                if (m != null) r.mesh = m; else r.enabled = false;
            }
            r.sharedMaterial = mat;
            r.trailMaterial = tmat;
            r.lengthScale = rd.lengthScale; r.velocityScale = rd.velocityScale; r.cameraVelocityScale = rd.cameraVelocityScale;
            r.sortingFudge = rd.sortingFudge; r.sortMode = (ParticleSystemSortMode)rd.sortMode; r.sortingOrder = rd.sortingOrder;
            r.minParticleSize = rd.minParticleSize; r.maxParticleSize = rd.maxParticleSize;
            r.alignment = (ParticleSystemRenderSpace)rd.alignment; r.pivot = V3(rd.pivot, Vector3.zero); r.flip = V3(rd.flip, Vector3.zero);
            r.allowRoll = rd.allowRoll; r.normalDirection = rd.normalDirection;
            r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off; r.receiveShadows = false;
            r.SetActiveVertexStreams(new List<ParticleSystemVertexStream> {
                ParticleSystemVertexStream.Position, ParticleSystemVertexStream.Color, ParticleSystemVertexStream.UV,
                ParticleSystemVertexStream.UV2, ParticleSystemVertexStream.Custom1XYZW, ParticleSystemVertexStream.Custom2XYZW });
        }

        // ------------------------------------------------------------------ bodies
        private static Texture2D ImportTex(string path, bool srgb, bool point)
        {
            var imp = AssetImporter.GetAtPath(path) as TextureImporter;
            if (imp == null) throw new InvalidOperationException("texture did not import: " + path);
            imp.textureType = TextureImporterType.Default;
            imp.sRGBTexture = srgb; imp.mipmapEnabled = !point; imp.filterMode = point ? FilterMode.Point : FilterMode.Bilinear;
            imp.wrapMode = TextureWrapMode.Clamp; imp.npotScale = TextureImporterNPOTScale.None; imp.maxTextureSize = 8192;
            imp.textureCompression = TextureImporterCompression.Uncompressed; imp.alphaIsTransparency = point;
            imp.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }

        private sealed class Body
        {
            public GameObject go; public Animator animator; public Dictionary<string, float> lengths = new Dictionary<string, float>();
            public List<Material> mats = new List<Material>(); public Material boilMat; public Dictionary<string, Transform> bones = new Dictionary<string, Transform>();
            public List<Renderer> skins = new List<Renderer>();   // body renderers an overlay is appended to
        }

        private static Material BodyMat(Shader sh, Vector4 sun, Texture2D albedo, Texture2D emi, float[] emiCol, float emin, float bspeed, float bpower, float cutoff)
        {
            var m = new Material(sh) { mainTexture = albedo };
            m.SetVector("_SunDir", sun);
            if (emi != null) m.SetTexture("_EmissionTex", emi);
            m.SetColor("_EmissionColor", emi != null && emiCol != null ? new Color(emiCol[0], emiCol[1], emiCol[2], 1) : Color.black);
            m.SetFloat("_EmissionMinPower", emin); m.SetFloat("_EmissionBlinkSpeed", bspeed); m.SetFloat("_EmissionBlinkPower", bpower);
            m.SetFloat("_Cutoff", cutoff);
            return m;
        }

        private static Body BuildBody(JobDef job, PanelDef p, Vector4 sun)
        {
            var b = new Body();
            Shader sh = AssetDatabase.LoadAssetAtPath<Shader>("Assets/Homm3VfxLab/Shaders/Homm3VfxHexLitEmissionReplica.shader");
            if (sh == null) throw new InvalidOperationException("emission replica shader missing");
            string R(string n) => job.assetRoot + "/" + n;
            BodyDef bd = p.body;
            if (bd.kind == "glb")
            {
                GameObject glb = AssetDatabase.LoadAssetAtPath<GameObject>(bd.glbAssetPath);
                if (glb == null) throw new InvalidOperationException("GLB did not import: " + bd.glbAssetPath);
                AnimationClip[] glbClips = AssetDatabase.LoadAllAssetsAtPath(bd.glbAssetPath).OfType<AnimationClip>().ToArray();
                b.go = UnityEngine.Object.Instantiate(glb);
                b.go.name = p.id + "_unit";
                foreach (Animation legacy in b.go.GetComponentsInChildren<Animation>(true)) UnityEngine.Object.DestroyImmediate(legacy);
                Texture2D tex = ImportTex(R(bd.texture), true, false);
                Texture2D emi = string.IsNullOrEmpty(bd.emissionTex) ? null : ImportTex(R(bd.emissionTex), true, false);
                SkinnedMeshRenderer[] skins = b.go.GetComponentsInChildren<SkinnedMeshRenderer>(true);
                SkinnedMeshRenderer body = skins.Where(s => !s.name.EndsWith("_Rubble")).OrderByDescending(s => s.sharedMesh.vertexCount).First();
                foreach (SkinnedMeshRenderer s in skins)
                {
                    if (s.name.EndsWith("_Rubble")) { s.enabled = false; continue; }
                    s.forceMatrixRecalculationPerRender = true; s.updateWhenOffscreen = true;
                    var m = BodyMat(sh, sun, tex, emi, bd.emissionColor, bd.emissionMin, bd.blinkSpeed, bd.blinkPower, 0f);
                    if (bd.flagPower != null && bd.flagPower.Length == 3)
                    {
                        if (bd.flagDirection == null || bd.flagDirection.Length != 3 ||
                            !s.sharedMesh.HasVertexAttribute(UnityEngine.Rendering.VertexAttribute.Color))
                            throw new InvalidOperationException(p.id + ": FLAG lab body requires a COLOR_0-baked mesh and direction");
                        m.SetFloat("_UseFlag", 1f);
                        m.SetVector("_FlagDirection", new Vector4(bd.flagDirection[0], bd.flagDirection[1], bd.flagDirection[2], 0f));
                        m.SetVector("_FlagPower", new Vector4(bd.flagPower[0], bd.flagPower[1], bd.flagPower[2], 0f));
                        m.SetFloat("_FlagSpeed", bd.flagSpeed);
                    }
                    s.sharedMaterial = m; b.mats.Add(m);
                    if (s == body) b.boilMat = m;
                    b.skins.Add(s);
                }
                b.animator = b.go.GetComponent<Animator>() ?? b.go.AddComponent<Animator>();
                b.animator.applyRootMotion = false; b.animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
                string clipRoot = job.assetRoot + "/clips_" + p.id;
                if (!AssetDatabase.IsValidFolder(clipRoot)) AssetDatabase.CreateFolder(job.assetRoot, "clips_" + p.id);
                string ctrlPath = clipRoot + "/lab.controller";
                AssetDatabase.DeleteAsset(ctrlPath);
                AnimatorController ctrl = AnimatorController.CreateAnimatorControllerAtPath(ctrlPath);
                foreach (ClipDef c in p.clips)
                {
                    AnimationClip src = glbClips.FirstOrDefault(x => x.name == c.name || x.name.EndsWith(c.name, StringComparison.Ordinal));
                    if (src == null) throw new InvalidOperationException("clip " + c.name + " missing");
                    var copy = new AnimationClip { name = "vs_" + c.name, frameRate = src.frameRate, legacy = false };
                    foreach (EditorCurveBinding eb in AnimationUtility.GetCurveBindings(src)) AnimationUtility.SetEditorCurve(copy, eb, AnimationUtility.GetEditorCurve(src, eb));
                    copy.EnsureQuaternionContinuity();
                    string cp = clipRoot + "/" + copy.name + ".anim";
                    AssetDatabase.DeleteAsset(cp); AssetDatabase.CreateAsset(copy, cp);
                    AnimatorState st = ctrl.AddMotion(copy); st.name = c.name;
                    b.lengths[c.name] = copy.length;
                }
                AssetDatabase.SaveAssets();
                b.animator.runtimeAnimatorController = ctrl; b.animator.Rebind();
                foreach (Transform t in b.go.GetComponentsInChildren<Transform>(true)) if (!b.bones.ContainsKey(t.name)) b.bones[t.name] = t;
            }
            else
            {
                b.go = new GameObject(p.id + "_native");
                byte[] raw = File.ReadAllBytes(bd.nativeMeshFile);
                using (var br = new BinaryReader(new MemoryStream(raw)))
                {
                    int nv = br.ReadInt32(), nsub = br.ReadInt32();
                    var pos = new Vector3[nv]; var nrm = new Vector3[nv]; var uv = new Vector2[nv];
                    for (int i = 0; i < nv; i++) pos[i] = new Vector3(br.ReadSingle(), br.ReadSingle(), br.ReadSingle());
                    for (int i = 0; i < nv; i++) nrm[i] = new Vector3(br.ReadSingle(), br.ReadSingle(), br.ReadSingle());
                    for (int i = 0; i < nv; i++) uv[i] = new Vector2(br.ReadSingle(), br.ReadSingle());
                    var mesh = new Mesh { indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
                    mesh.vertices = pos; mesh.normals = nrm; mesh.uv = uv; mesh.subMeshCount = nsub;
                    for (int s = 0; s < nsub; s++)
                    {
                        int n = br.ReadInt32(); var tri = new int[n];
                        for (int i = 0; i < n; i++) tri[i] = br.ReadInt32();
                        mesh.SetTriangles(tri, s);
                    }
                    mesh.RecalculateBounds();
                    b.go.AddComponent<MeshFilter>().sharedMesh = mesh;
                    var mr = b.go.AddComponent<MeshRenderer>();
                    var ms = new Material[nsub];
                    for (int s = 0; s < nsub; s++)
                    {
                        NativeMat nm = bd.nativeMats[s];
                        Texture2D a = ImportTex(R(nm.albedo), true, false);
                        Texture2D e = string.IsNullOrEmpty(nm.emission) ? null : ImportTex(R(nm.emission), true, false);
                        ms[s] = BodyMat(sh, sun, a, e, nm.emissionColor, nm.emissionMin, nm.blinkSpeed, nm.blinkPower, nm.cutoff);
                        b.mats.Add(ms[s]);
                    }
                    mr.sharedMaterials = ms;
                    b.skins.Add(mr);
                }
                foreach (BoneDef bone in bd.bones)
                {
                    var m = new Matrix4x4();
                    for (int i = 0; i < 16; i++) m[i / 4, i % 4] = bone.m[i];
                    var t = new GameObject("bone:" + bone.name).transform;
                    t.SetParent(b.go.transform, false);
                    t.position = m.GetColumn(3);
                    Vector3 f = m.GetColumn(2), u = m.GetColumn(1);
                    t.rotation = Quaternion.LookRotation(f, u);
                    t.localScale = new Vector3(((Vector3)m.GetColumn(0)).magnitude, u.magnitude, f.magnitude);
                    b.bones[bone.name] = t;
                }
                b.go.transform.rotation = Quaternion.Euler(0f, bd.bodyYawDeg, 0f);
            }
            b.bones["__body"] = b.go.transform;
            return b;
        }

        // ------------------------------------------------------------------ panel loop
        private static void RunPanel(JobDef job, PanelDef p, MaterialCache mats)
        {
            var sun = new Vector4(p.sunTravelUnity[0], p.sunTravelUnity[1], p.sunTravelUnity[2], 0);
            Body body = BuildBody(job, p, sun);
            var overlays = new List<(OverlayDef d, Material m)>();
            foreach (OverlayDef od in p.body.overlays ?? new OverlayDef[0])
            {
                Material om = mats.Get(od.material);
                if (om == null) throw new InvalidOperationException(p.id + ": overlay " + od.id + " material " + od.material + " has no lab replica");
                if (od.colors != null && od.colors.Length > 0)
                {
                    // per-unit tint (the plugin's source.colors): a private copy with absolute colours, fail closed
                    om = new Material(om) { name = om.name + "_" + od.id };
                    foreach (CProp c in od.colors)
                    {
                        if (!om.HasProperty(c.name)) throw new InvalidOperationException(p.id + ": overlay " + od.id + " tint property " + c.name + " missing");
                        om.SetColor(c.name, new Color(c.rgba[0], c.rgba[1], c.rgba[2], c.rgba[3]));
                    }
                    mats.All.Add(om);
                }
                if (body.skins.Count == 0) throw new InvalidOperationException(p.id + ": overlay " + od.id + " needs a body renderer");
                overlays.Add((od, om));
            }
            Material[][] baseMats = body.skins.Select(s => s.sharedMaterials).ToArray();
            var fxs = new List<Fx>();
            foreach (EffectDef e in p.effects ?? new EffectDef[0])
            {
                if (!body.bones.TryGetValue(e.bone, out Transform bone)) throw new InvalidOperationException(p.id + ": bone " + e.bone + " missing for " + e.id);
                Fx fx = BuildEffect(e, bone, mats);
                if (job.requireCompleteEffects)
                {
                    if (fx.systems.Count == 0 || (e.keepPS != null && e.keepPS.Length > 0 && fx.systems.Count != e.keepPS.Length))
                        throw new InvalidOperationException(p.id + "/" + e.id + ": selected ParticleSystem count differs from the recipe");
                    foreach (ParticleSystem ps in fx.systems)
                    {
                        var renderer = ps.GetComponent<ParticleSystemRenderer>();
                        if (renderer == null || !renderer.enabled || (renderer.sharedMaterial == null && renderer.trailMaterial == null))
                            throw new InvalidOperationException(p.id + "/" + e.id + ": a selected ParticleSystem has no supported renderer/material");
                    }
                }
                fxs.Add(fx);
            }
            // old flipbooks
            var quads = new List<(FlipDef f, Transform q, Material m)>();
            foreach (FlipDef f in p.flipbooks ?? new FlipDef[0])
            {
                var q = GameObject.CreatePrimitive(PrimitiveType.Quad);
                UnityEngine.Object.DestroyImmediate(q.GetComponent<Collider>());
                var m = new Material(Shader.Find("Sprites/Default")) { mainTexture = ImportTex(job.assetRoot + "/" + f.sheet, true, true) };
                m.mainTextureScale = new Vector2(1f / f.tilesX, 1f / f.tilesY);
                q.GetComponent<MeshRenderer>().sharedMaterial = m;
                q.SetActive(false);
                quads.Add((f, q.transform, m));
            }

            Vector3 right = V3(p.camRight, Vector3.right), up = V3(p.camUp, Vector3.up), fwd = V3(p.camForward, Vector3.forward);
            Camera cam = new GameObject(p.id + "_cam").AddComponent<Camera>();
            cam.orthographic = true; cam.orthographicSize = p.orthoSize; cam.nearClipPlane = 0.1f; cam.farClipPlane = 80f;
            cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(0, 0, 0, 0); cam.allowMSAA = false; cam.allowHDR = true;
            cam.transform.SetPositionAndRotation(V3(p.camCentre, Vector3.zero) - fwd * 30f, Quaternion.LookRotation(fwd, up));
            var rt = new RenderTexture(p.width, p.height, 24, RenderTextureFormat.ARGBHalf, RenderTextureReadWrite.Linear) { antiAliasing = 1 };
            cam.targetTexture = rt;
            var read = new Texture2D(p.width, p.height, TextureFormat.RGBAHalf, false, true);
            string dir = Path.Combine(job.outDir, p.id);
            Directory.CreateDirectory(dir);
            var frameLog = new List<string>();
            const float DT = 1f / 60f;

            foreach (ClipDef c in p.clips)
            {
                foreach (Fx fx in fxs) { foreach (ParticleSystem ps in fx.systems) ps.Clear(false); fx.playing = false; fx.fired = 0; Reattach(fx); }
                float len = body.lengths.TryGetValue(c.name, out float L) ? Mathf.Max(L, 1e-4f) : 1f;
                void Pose(float tau)
                {
                    if (overlays.Count > 0)
                    {
                        var on = overlays.Where(o => o.d.always || (o.d.clip == c.name && tau >= o.d.start && tau < o.d.end)).Select(o => o.m).ToArray();
                        for (int k = 0; k < body.skins.Count; k++) body.skins[k].sharedMaterials = baseMats[k].Concat(on).ToArray();
                    }
                    if (body.animator != null)
                    {
                        float t = c.loop ? Mathf.Repeat(tau, len) : Mathf.Clamp(tau, 0f, len);
                        body.animator.Play(c.name, 0, t / len); body.animator.Update(0f);
                    }
                    if (body.boilMat != null && p.body.cellST != null && p.body.cellST.Length > 0 && c.boilCells != null && c.boilCells.Length > 0)
                    {
                        float tk = c.loop ? Mathf.Repeat(tau, c.keys / 12f) : tau;
                        int key = Mathf.Clamp(Mathf.FloorToInt(Mathf.Max(tk, 0f) * 12f - 0.5f), 0, c.boilCells.Length - 1);
                        int cell = c.boilCells[key];
                        body.boilMat.SetVector("_MainTex_ST", new Vector4(p.body.cellST[cell * 4], p.body.cellST[cell * 4 + 1], p.body.cellST[cell * 4 + 2], p.body.cellST[cell * 4 + 3]));
                    }
                }
                void Restart(Fx fx) { foreach (ParticleSystem ps in fx.systems) ps.Simulate(0f, false, true, false); fx.playing = true; }
                void Orient(Fx fx)
                {
                    if (fx.detached) return;   // follow=release: stays where the trigger left it
                    float[] q = fx.def.rootWorldRot;
                    if (q != null && q.Length == 4) fx.root.rotation = new Quaternion(q[0], q[1], q[2], q[3]);
                    if (fx.def.emitUp)   // cone axis (+Z) straight up, roll facing the camera
                        foreach (ParticleSystem ps in fx.systems) if (ps.shape.enabled) ps.transform.rotation = Quaternion.LookRotation(Vector3.up, -cam.transform.forward);
                    if (fx.anchor != null) fx.root.position += fx.bone.TransformPoint(V3(fx.def.pos, Vector3.zero)) - fx.anchor.position;
                }
                // warmup and always-on effects
                float tau = -p.warmupS;
                float labTime = tau; // phase restarts with the particle simulation for each clip
                foreach (Fx fx in fxs) if (fx.def.alwaysOn) { Orient(fx); Restart(fx); }
                int frame = 0;
                float end = c.frames * c.frameStep;
                while (frame < c.frames)
                {
                    float tNext = (frame + 1) * c.frameStep;
                    while (tau < tNext - 1e-5f)
                    {
                        Pose(tau);
                        foreach (Fx fx in fxs)
                        {
                            Orient(fx);
                            foreach (Trigger tr in fx.def.triggers ?? new Trigger[0])
                                if (tr.clip == c.name && tau < tr.time && tau + DT >= tr.time) { Reattach(fx); Orient(fx); Restart(fx); fx.fired++; if (fx.def.detachOnTrigger) { fx.root.SetParent(body.go.transform, true); fx.detached = true; } }
                            foreach (Trigger tr in fx.def.stops ?? new Trigger[0])
                                if (tr.clip == c.name && tau < tr.time && tau + DT >= tr.time) foreach (ParticleSystem ps in fx.systems) ps.Stop(false, ParticleSystemStopBehavior.StopEmitting);
                            if (fx.playing) foreach (ParticleSystem ps in fx.systems) ps.Simulate(DT, false, false, false);
                        }
                        tau += DT; labTime += DT;
                    }
                    Pose(tNext);
                    foreach (Material m in mats.All) m.SetFloat("_LabTime", labTime);
                    foreach (Material m in body.mats) m.SetFloat("_LabTime", labTime);
                    // lights: old per-key point light, new/vanilla particle-Lights flashes
                    var L4 = new List<(Vector3 pos, Vector3 col, float invR2, float mag)>();
                    foreach (OldLightDef ol in p.oldLights ?? new OldLightDef[0])
                    {
                        if (ol.clip != c.name || !body.bones.TryGetValue(ol.bone, out Transform lb)) continue;
                        float tk = c.loop ? Mathf.Repeat(tNext, c.keys / 12f) : tNext;
                        int key = Mathf.Clamp(Mathf.FloorToInt(tk * 12f - 0.5f), 0, ol.intensity.Length - 1);
                        float I = ol.intensity[key];
                        if (I <= 0) continue;
                        L4.Add((lb.position - cam.transform.forward * ol.towardCamera, new Vector3(ol.rgbLinear[0], ol.rgbLinear[1], ol.rgbLinear[2]) * I, 1f / (ol.range * ol.range), I));
                    }
                    var parts = new ParticleSystem.Particle[64];
                    foreach (Fx fx in fxs)
                        foreach (var (ps, lm) in fx.lights)
                        {
                            int n = ps.GetParticles(parts);
                            for (int i = 0; i < Mathf.Min(n, Mathf.Max(1, lm.maxLights)); i++)
                            {
                                var pt = parts[i];
                                float age = 1f - pt.remainingLifetime / Mathf.Max(pt.startLifetime, 1e-4f);
                                Color pc = pt.GetCurrentColor(ps);
                                float I = lm.template.intensity * Eval(lm.intensityCurve, age) * (lm.alphaAffectsIntensity ? pc.a : 1f);
                                float R = lm.template.range * Eval(lm.rangeCurve, age) * (lm.sizeAffectsRange ? pt.GetCurrentSize(ps) : 1f);
                                if (I <= 1e-3f || R <= 1e-3f) continue;
                                Color tc = Col(lm.template.color).linear;
                                Color lc = lm.useColor ? pc.linear : Color.white;
                                Vector3 wp = ps.main.simulationSpace == ParticleSystemSimulationSpace.World ? pt.position : ps.transform.TransformPoint(pt.position);
                                L4.Add((wp, new Vector3(tc.r * lc.r, tc.g * lc.g, tc.b * lc.b) * I, 1f / (R * R), I));
                            }
                        }
                    L4 = L4.OrderByDescending(x => x.mag).Take(4).ToList();
                    foreach (Material m in body.mats)
                    {
                        m.SetFloat("_PLCount", L4.Count);
                        var pp = new Vector4[4]; var cc = new Vector4[4]; var ir = new float[4];
                        for (int i = 0; i < L4.Count; i++) { pp[i] = L4[i].pos; cc[i] = L4[i].col; ir[i] = L4[i].invR2; }
                        m.SetVectorArray("_PLPos", pp); m.SetVectorArray("_PLCol", cc); m.SetFloatArray("_PLInvRange2", ir);
                    }
                    // flipbook quads
                    foreach (var (f, q, m) in quads)
                    {
                        bool on = false;
                        if (f.clip == c.name && body.bones.TryGetValue(f.bone, out Transform fb))
                        {
                            int key = Mathf.FloorToInt(tNext * 12f - 0.5f);
                            if (key >= 0 && key < f.cells.Length && f.cells[key] >= 0)
                            {
                                int cell = f.cells[key], cx = cell % f.tilesX, cy = cell / f.tilesX;
                                m.mainTextureOffset = new Vector2((float)cx / f.tilesX, 1f - (float)(cy + 1) / f.tilesY);
                                q.SetPositionAndRotation(fb.position, cam.transform.rotation);
                                q.localScale = new Vector3(f.sizeX, f.sizeY, 1);
                                on = true;
                            }
                        }
                        q.gameObject.SetActive(on);
                    }
                    cam.Render();
                    RenderTexture.active = rt;
                    read.ReadPixels(new Rect(0, 0, p.width, p.height), 0, 0);
                    read.Apply();
                    RenderTexture.active = null;
                    File.WriteAllBytes(Path.Combine(dir, c.name + "_" + frame.ToString("000") + ".bin"), read.GetRawTextureData());
                    frameLog.Add("{\"clip\": \"" + c.name + "\", \"frame\": " + frame + ", \"t\": " + tNext.ToString("0.####", CultureInfo.InvariantCulture)
                        + ", \"lights\": " + L4.Count + ", \"lightMax\": " + (L4.Count > 0 ? L4[0].mag : 0f).ToString("0.###", CultureInfo.InvariantCulture)
                        + ", \"particles\": " + fxs.Sum(x => x.systems.Sum(s => s.particleCount)) + "}");
                    frame++;
                }
                foreach (Fx fx in fxs) Log(p.id + "_" + c.name + "_" + fx.def.id + "_fired", fx.fired.ToString());
            }
            Log(p.id + "_frames", "[\n  " + string.Join(",\n  ", frameLog) + "\n ]");
            UnityEngine.Object.DestroyImmediate(cam.gameObject);
            UnityEngine.Object.DestroyImmediate(body.go);
            foreach (var (f, q, m) in quads) UnityEngine.Object.DestroyImmediate(q.gameObject);
            foreach (Fx fx in fxs) if (fx.root != null) UnityEngine.Object.DestroyImmediate(fx.root.gameObject);
        }
    }
}
