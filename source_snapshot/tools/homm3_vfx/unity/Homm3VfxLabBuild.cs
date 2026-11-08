// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/build_vfx_lab.py. Editor-only lab builder.
// Builds, under Assets/Homm3VfxLab/<unit>/, a preview prefab of a def_retarget GLB copy, extracted
// clips, and flipbook ParticleSystem prefabs described by vfx_lab_spec.json (homm3_vfx_lab.v1).
// Nothing here is a runtime or in-game delivery path.
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Vfx
{
    public static class Homm3VfxLabBuild
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

        [Serializable]
        private sealed class LabSystem
        {
            public string name;
            public string texture;
            public int tilesX;
            public int tilesY;
            public int frames;
            public float fps;
            public float startDelay;
            public float lifetime;
            public float[] sizeUnits;
            public string simulationSpace;
            public float[] velocityWorld;
        }

        [Serializable]
        private sealed class LabPrefab
        {
            public string name;
            public string[] systems;
        }

        [Serializable]
        private sealed class LabSpec
        {
            public string schema;
            public string unitSid;
            public string assetRoot;
            public string glbAssetPath;
            public string[] clips;
            public LabPrefab[] prefabList;
            public LabSystem[] systems;
        }

        public static void BuildFromCommandLine()
        {
            string[] args = UnityQueueArgs();
            string specPath = null;
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == "-homm3VfxLabSpec")
                    specPath = args[i + 1];
            if (string.IsNullOrEmpty(specPath) || !File.Exists(specPath))
                throw new InvalidOperationException("-homm3VfxLabSpec <file> is required");
            LabSpec spec = JsonUtility.FromJson<LabSpec>(File.ReadAllText(specPath));
            if (spec.schema != "homm3_vfx_lab.v1")
                throw new InvalidOperationException("unexpected schema " + spec.schema);
            Build(spec);
            Debug.Log("HOMM3_VFX_LAB_BUILD_OK " + spec.unitSid);
        }

        private static void Build(LabSpec spec)
        {
            string root = spec.assetRoot.TrimEnd('/');
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

            // unit preview prefab and clips
            GameObject glb = AssetDatabase.LoadAssetAtPath<GameObject>(spec.glbAssetPath);
            if (glb == null)
                throw new InvalidOperationException("GLB did not import: " + spec.glbAssetPath);
            if (glb.GetComponentsInChildren<SkinnedMeshRenderer>(true).Length == 0)
                throw new InvalidOperationException("GLB has no SkinnedMeshRenderer");
            GameObject unit = UnityEngine.Object.Instantiate(glb);
            unit.name = spec.unitSid + "_vfxlab";
            foreach (Animation legacy in unit.GetComponentsInChildren<Animation>(true))
                UnityEngine.Object.DestroyImmediate(legacy);
            // generic clips need an Animator on the root for AnimationClip.SampleAnimation to bind
            Animator animator = unit.GetComponent<Animator>() ?? unit.AddComponent<Animator>();
            animator.applyRootMotion = false;
            // the harness renders several poses per editor frame; without this the skinned mesh keeps its first pose
            if (unit.GetComponent<Homm3VfxLabSkinRefresh>() == null)
                unit.AddComponent<Homm3VfxLabSkinRefresh>();
            SavePrefab(unit, root + "/" + spec.unitSid + "_vfxlab.prefab");

            AnimationClip[] clips = AssetDatabase.LoadAllAssetsAtPath(spec.glbAssetPath).OfType<AnimationClip>().ToArray();
            foreach (string wanted in spec.clips)
            {
                AnimationClip src = clips.FirstOrDefault(c => c.name == wanted || c.name.EndsWith(wanted, StringComparison.Ordinal));
                if (src == null)
                    throw new InvalidOperationException("clip " + wanted + " missing from GLB; found: "
                        + string.Join(",", clips.Select(c => c.name)));
                // Rebuild as a generic clip through editor curves (bones + corrective blend shapes),
                // so SampleAnimation evaluates it; a serialized copy of the legacy clip samples nothing.
                AnimationClip copy = new AnimationClip { name = wanted, frameRate = src.frameRate, legacy = false };
                EditorCurveBinding[] bindings = AnimationUtility.GetCurveBindings(src);
                if (bindings.Length == 0)
                    throw new InvalidOperationException("clip " + wanted + " has no curve bindings");
                foreach (EditorCurveBinding b in bindings)
                    AnimationUtility.SetEditorCurve(copy, b, AnimationUtility.GetEditorCurve(src, b));
                copy.EnsureQuaternionContinuity();
                string clipPath = root + "/" + wanted + ".anim";
                AssetDatabase.DeleteAsset(clipPath);
                AssetDatabase.CreateAsset(copy, clipPath);
                Debug.Log("HOMM3_VFX_LAB clip " + wanted + " length " + copy.length + " rate " + copy.frameRate);
            }

            // flipbook materials and particle prefabs
            foreach (LabPrefab prefab in spec.prefabList)
            {
                GameObject effectRoot = new GameObject(prefab.name);
                foreach (string systemName in prefab.systems)
                {
                    LabSystem s = spec.systems.FirstOrDefault(x => x.name == systemName);
                    if (s == null)
                        throw new InvalidOperationException("system " + systemName + " not in spec");
                    Material material = BuildMaterial(root, s);
                    GameObject child = new GameObject(s.name);
                    child.transform.SetParent(effectRoot.transform, false);
                    ConfigureSystem(child.AddComponent<ParticleSystem>(), child.GetComponent<ParticleSystemRenderer>(), s, material);
                }
                SavePrefab(effectRoot, root + "/" + prefab.name + ".prefab");
            }
            AssetDatabase.SaveAssets();
        }

        private static Material BuildMaterial(string root, LabSystem s)
        {
            string texPath = root + "/" + s.texture;
            TextureImporter importer = AssetImporter.GetAtPath(texPath) as TextureImporter;
            if (importer == null)
                throw new InvalidOperationException("texture did not import: " + texPath);
            importer.textureType = TextureImporterType.Default;
            importer.filterMode = FilterMode.Point;
            importer.mipmapEnabled = false;
            importer.textureCompression = TextureImporterCompression.Uncompressed;
            importer.alphaIsTransparency = true;
            importer.wrapMode = TextureWrapMode.Clamp;
            importer.npotScale = TextureImporterNPOTScale.None;
            importer.sRGBTexture = true;
            importer.SaveAndReimport();
            Texture2D tex = AssetDatabase.LoadAssetAtPath<Texture2D>(texPath);
            Shader shader = Shader.Find("Sprites/Default");
            if (shader == null)
                throw new InvalidOperationException("Sprites/Default shader not found");
            Material material = new Material(shader) { mainTexture = tex, name = s.name };
            string matPath = root + "/" + s.name + ".mat";
            AssetDatabase.DeleteAsset(matPath);
            AssetDatabase.CreateAsset(material, matPath);
            return material;
        }

        private static void ConfigureSystem(ParticleSystem ps, ParticleSystemRenderer renderer, LabSystem s, Material material)
        {
            float life = s.lifetime > 0f ? s.lifetime : s.frames / s.fps;
            ParticleSystem.MainModule main = ps.main;
            main.duration = life;
            main.loop = false;
            main.playOnAwake = false;
            main.startDelay = s.startDelay;
            main.startLifetime = life;
            main.startSpeed = 0f;
            main.startSize3D = true;
            main.startSizeX = s.sizeUnits[0];
            main.startSizeY = s.sizeUnits[1];
            main.startSizeZ = 1f;
            main.startRotation = 0f;
            main.startColor = Color.white;
            main.gravityModifier = 0f;
            main.maxParticles = 1;
            main.scalingMode = ParticleSystemScalingMode.Local;
            main.simulationSpace = s.simulationSpace == "World"
                ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
            ps.useAutoRandomSeed = false;
            ps.randomSeed = 11;

            ParticleSystem.EmissionModule emission = ps.emission;
            emission.rateOverTime = 0f;
            emission.SetBursts(new[] { new ParticleSystem.Burst(0f, 1) });
            ParticleSystem.ShapeModule shape = ps.shape;
            shape.enabled = false;

            int tiles = s.tilesX * s.tilesY;
            if (tiles > 1)
            {
                ParticleSystem.TextureSheetAnimationModule sheet = ps.textureSheetAnimation;
                sheet.enabled = true;
                sheet.mode = ParticleSystemAnimationMode.Grid;
                sheet.numTilesX = s.tilesX;
                sheet.numTilesY = s.tilesY;
                sheet.animation = ParticleSystemAnimationType.WholeSheet;
                sheet.cycleCount = 1;
                // frame = floor(normalisedAge * frames): DEF frame i shows for [i/fps, (i+1)/fps)
                sheet.frameOverTime = new ParticleSystem.MinMaxCurve((float)s.frames / tiles, AnimationCurve.Linear(0f, 0f, 1f, 1f));
            }

            bool moving = s.velocityWorld != null && s.velocityWorld.Any(v => Mathf.Abs(v) > 1e-6f);
            if (moving)
            {
                ParticleSystem.VelocityOverLifetimeModule velocity = ps.velocityOverLifetime;
                velocity.enabled = true;
                velocity.space = ParticleSystemSimulationSpace.World;
                velocity.x = s.velocityWorld[0];
                velocity.y = s.velocityWorld[1];
                velocity.z = s.velocityWorld[2];
            }

            renderer.renderMode = ParticleSystemRenderMode.Billboard;
            renderer.alignment = ParticleSystemRenderSpace.View;
            renderer.sharedMaterial = material;
            renderer.minParticleSize = 0f;
            renderer.maxParticleSize = 10f;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            renderer.receiveShadows = false;
        }

        private static void SavePrefab(GameObject instance, string path)
        {
            AssetDatabase.DeleteAsset(path);
            bool saved;
            PrefabUtility.SaveAsPrefabAsset(instance, path, out saved);
            UnityEngine.Object.DestroyImmediate(instance);
            if (!saved)
                throw new InvalidOperationException("prefab did not save: " + path);
        }
    }
}
