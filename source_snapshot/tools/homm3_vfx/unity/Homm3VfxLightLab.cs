// HOMM3_VFX_LAB_GENERATED: managed by tools/homm3_vfx/titan_light_lab.py. Editor-only lab renderer.
// Renders the lab prefab (Homm3VfxLabBuild output) through a sprite-registered orthographic camera with the
// Hex/Lit replica + point-light shader, one pass per term, to linear half-float buffers:
//   base_<tex>  : albedo * (ambient + sun * N.L)                         (no point light)
//   plight_<tex>: albedo * pointLight(unit colour) only                    (ambient = sun = 0)
//   fxk / fxw   : flipbook particles over black / white, body depth-only  (recovers premultiplied FX + alpha)
// Python (titan_light_lab.py) fits the per-frame light intensity and composites. Unity-editor render, not in-game.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace OldenEra.Homm3Vfx
{
    public static class Homm3VfxLightLab
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

        private const int Layer = 30;

        [Serializable] private sealed class TexEntry { public string name; public string path; public bool lightPass; }

        [Serializable]
        private sealed class Job
        {
            public string name;
            public string clip;
            public string effectPrefab;
            public string anchor;
            public float[] times;
            public float[] particleElapsed;
            public float[] lightOffsets;   // per frame: camera right, camera up, toward camera (world units)
            public float[] lightColor;     // linear, unit intensity
            public float lightRange;
        }

        [Serializable]
        private sealed class Facing { public string name; public float[] camFwd; public float[] camUp; public float[] sunTravel; public float orthoSize; }

        [Serializable]
        private sealed class Spec
        {
            public string schema;
            public string prefabPath;
            public string outDir;
            public int width;
            public int height;
            public float orthoSize;
            public float[] camPos;
            public float[] camFwd;
            public float[] camUp;
            public float[] sunTravel;
            public float[] sunColor;
            public float[] ambient;
            public TexEntry[] textures;
            public Job[] jobs;
            public Facing[] facings;
            public string idleClip;
            public float idleTime;
        }

        private static Vector3 V(float[] a) => new Vector3(a[0], a[1], a[2]);

        public static void RenderFromCommandLine()
        {
            string[] args = UnityQueueArgs();
            string specPath = null;
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == "-homm3VfxLightLabSpec")
                    specPath = args[i + 1];
            if (string.IsNullOrEmpty(specPath) || !File.Exists(specPath))
                throw new InvalidOperationException("-homm3VfxLightLabSpec <file> is required");
            Spec spec = JsonUtility.FromJson<Spec>(File.ReadAllText(specPath));
            if (spec.schema != "homm3_vfx_light_lab.v1")
                throw new InvalidOperationException("unexpected schema " + spec.schema);
            Run(spec);
            Debug.Log("HOMM3_VFX_LIGHT_LAB_OK");
        }

        private static void Run(Spec spec)
        {
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            Shader replica = Shader.Find("Hidden/Homm3Vfx/HexLitReplicaPoint");
            Shader depthOnly = Shader.Find("Hidden/Homm3Vfx/DepthOnly");
            if (replica == null || depthOnly == null)
                throw new InvalidOperationException("lab shaders missing (HexLitReplicaPoint / DepthOnly)");

            var materials = new Dictionary<string, Material>();
            foreach (TexEntry t in spec.textures)
            {
                var importer = AssetImporter.GetAtPath(t.path) as TextureImporter;
                if (importer == null)
                    throw new InvalidOperationException("texture did not import: " + t.path);
                if (!importer.sRGBTexture || importer.textureCompression != TextureImporterCompression.Uncompressed
                    || importer.maxTextureSize < 2048)
                {
                    importer.sRGBTexture = true;
                    importer.textureCompression = TextureImporterCompression.Uncompressed;
                    importer.maxTextureSize = 4096;
                    importer.mipmapEnabled = true;
                    importer.SaveAndReimport();
                }
                var m = new Material(replica) { name = t.name };
                m.SetTexture("_MainTex", AssetDatabase.LoadAssetAtPath<Texture2D>(t.path));
                m.SetVectorArray("_PLPos", new Vector4[4]);
                m.SetVectorArray("_PLCol", new Vector4[4]);
                m.SetFloatArray("_PLInvRange2", new float[4]);
                m.SetFloat("_PLCount", 0f);
                materials[t.name] = m;
            }
            var depthMat = new Material(depthOnly);

            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(spec.prefabPath);
            if (prefab == null)
                throw new InvalidOperationException("prefab missing: " + spec.prefabPath);
            GameObject unit = UnityEngine.Object.Instantiate(prefab);
            SetLayer(unit.transform);
            SkinnedMeshRenderer[] skins = unit.GetComponentsInChildren<SkinnedMeshRenderer>(true);
            foreach (var s in skins)
            {
                s.forceMatrixRecalculationPerRender = true;
                s.updateWhenOffscreen = true;
                s.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            }

            var camGo = new GameObject("LightLabCam");
            Camera cam = camGo.AddComponent<Camera>();
            cam.orthographic = true;
            cam.cullingMask = 1 << Layer;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.allowHDR = true;
            cam.allowMSAA = false;
            cam.nearClipPlane = 0.05f;
            cam.farClipPlane = 60f;
            var rt = new RenderTexture(spec.width, spec.height, 24, RenderTextureFormat.ARGBHalf, RenderTextureReadWrite.Linear)
                { antiAliasing = 1, hideFlags = HideFlags.HideAndDontSave };
            cam.targetTexture = rt;
            var read = new Texture2D(spec.width, spec.height, TextureFormat.RGBAHalf, false, true);

            var log = new List<string>();
            Directory.CreateDirectory(spec.outDir);

            // sprite-registered camera
            Vector3 fwd = V(spec.camFwd).normalized, up = V(spec.camUp).normalized;
            camGo.transform.SetPositionAndRotation(V(spec.camPos), Quaternion.LookRotation(fwd, up));
            cam.orthographicSize = spec.orthoSize;
            log.Add($"camRight {Fmt(camGo.transform.right)} camUp {Fmt(camGo.transform.up)} camFwd {Fmt(camGo.transform.forward)}");

            foreach (Job job in spec.jobs)
            {
                AnimationClip clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(job.clip);
                if (clip == null)
                    throw new InvalidOperationException("clip missing: " + job.clip);
                Transform anchor = unit.GetComponentsInChildren<Transform>(true).Single(x => x.name == job.anchor);
                GameObject fxPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(job.effectPrefab);
                if (fxPrefab == null)
                    throw new InvalidOperationException("effect prefab missing: " + job.effectPrefab);
                GameObject fx = UnityEngine.Object.Instantiate(fxPrefab, anchor, false);
                fx.transform.localPosition = Vector3.zero;
                fx.transform.localRotation = Quaternion.identity;
                SetLayer(fx.transform);
                ParticleSystem[] systems = fx.GetComponentsInChildren<ParticleSystem>(true);
                string dir = Path.Combine(spec.outDir, job.name);
                Directory.CreateDirectory(dir);
                Color lc = new Color(job.lightColor[0], job.lightColor[1], job.lightColor[2]);

                for (int i = 0; i < job.times.Length; i++)
                {
                    clip.SampleAnimation(unit, job.times[i]);
                    Vector3 lightPos = anchor.position
                        + camGo.transform.right * job.lightOffsets[3 * i]
                        + camGo.transform.up * job.lightOffsets[3 * i + 1]
                        - camGo.transform.forward * job.lightOffsets[3 * i + 2];
                    Vector3 ap = cam.WorldToScreenPoint(anchor.position), lp = cam.WorldToScreenPoint(lightPos);
                    log.Add($"{job.name} f{i} t={job.times[i]:F4} anchorPx {ap.x:F1} {spec.height - ap.y:F1} lightPx {lp.x:F1} {spec.height - lp.y:F1} lightWorld {Fmt(lightPos)}");

                    fx.SetActive(false);
                    foreach (TexEntry t in spec.textures)
                    {
                        Material m = materials[t.name];
                        SetLighting(m, spec, V(spec.sunTravel), true);
                        m.SetFloat("_PLCount", 0f);
                        foreach (var s in skins) s.sharedMaterial = m;
                        Render(cam, rt, read, Color.clear, Path.Combine(dir, $"f{i}_base_{t.name}.bin"));
                        if (!t.lightPass)
                            continue;
                        SetLighting(m, spec, V(spec.sunTravel), false);
                        m.SetVectorArray("_PLPos", new[] { (Vector4)lightPos, Vector4.zero, Vector4.zero, Vector4.zero });
                        m.SetVectorArray("_PLCol", new[] { (Vector4)lc, Vector4.zero, Vector4.zero, Vector4.zero });
                        m.SetFloatArray("_PLInvRange2", new[] { 1f / (job.lightRange * job.lightRange), 0f, 0f, 0f });
                        m.SetFloat("_PLCount", 1f);
                        Render(cam, rt, read, Color.clear, Path.Combine(dir, $"f{i}_plight_{t.name}.bin"));
                        m.SetFloat("_PLCount", 0f);
                    }

                    foreach (var s in skins) s.sharedMaterial = depthMat;
                    fx.SetActive(true);
                    for (int k = 0; k < systems.Length; k++)
                    {
                        systems[k].useAutoRandomSeed = false;
                        systems[k].randomSeed = (uint)(11 + k);
                        systems[k].Simulate(job.particleElapsed[i], false, true, true);
                    }
                    Render(cam, rt, read, Color.clear, Path.Combine(dir, $"f{i}_fxk.bin"));
                    Render(cam, rt, read, Color.white, Path.Combine(dir, $"f{i}_fxw.bin"));
                    fx.SetActive(false);
                }
                UnityEngine.Object.DestroyImmediate(fx);
            }

            // idle facings: camera orbits the unit (sun camera-relative, like the prebake battle views)
            if (spec.facings != null && spec.facings.Length > 0)
            {
                AnimationClip idle = AssetDatabase.LoadAssetAtPath<AnimationClip>(spec.idleClip);
                if (idle == null)
                    throw new InvalidOperationException("idle clip missing: " + spec.idleClip);
                idle.SampleAnimation(unit, spec.idleTime);
                Bounds b = skins[0].bounds;
                foreach (var s in skins) b.Encapsulate(s.bounds);
                string dir = Path.Combine(spec.outDir, "idle_facings");
                Directory.CreateDirectory(dir);
                foreach (Facing f in spec.facings)
                {
                    Vector3 ff = V(f.camFwd).normalized;
                    camGo.transform.SetPositionAndRotation(b.center - ff * 20f, Quaternion.LookRotation(ff, V(f.camUp)));
                    cam.orthographicSize = f.orthoSize;
                    foreach (TexEntry t in spec.textures)
                    {
                        Material m = materials[t.name];
                        SetLighting(m, spec, V(f.sunTravel), true);
                        m.SetFloat("_PLCount", 0f);
                        foreach (var s in skins) s.sharedMaterial = m;
                        Render(cam, rt, read, Color.clear, Path.Combine(dir, $"{f.name}_base_{t.name}.bin"));
                    }
                    log.Add($"facing {f.name} camRight {Fmt(camGo.transform.right)} centre {Fmt(b.center)}");
                }
            }
            File.WriteAllLines(Path.Combine(spec.outDir, "light_lab_log.txt"), log);
            UnityEngine.Object.DestroyImmediate(unit);
            UnityEngine.Object.DestroyImmediate(camGo);
            rt.Release();
        }

        private static void SetLighting(Material m, Spec spec, Vector3 sunTravel, bool on)
        {
            m.SetVector("_SunDir", (Vector4)sunTravel.normalized);
            m.SetVector("_SunColor", on ? new Vector4(spec.sunColor[0], spec.sunColor[1], spec.sunColor[2], 0) : Vector4.zero);
            m.SetVector("_Ambient", on ? new Vector4(spec.ambient[0], spec.ambient[1], spec.ambient[2], 0) : Vector4.zero);
        }

        private static void Render(Camera cam, RenderTexture rt, Texture2D read, Color clear, string path)
        {
            cam.backgroundColor = clear;
            cam.Render();
            RenderTexture prev = RenderTexture.active;
            RenderTexture.active = rt;
            read.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0, false);
            read.Apply(false);
            RenderTexture.active = prev;
            File.WriteAllBytes(path, read.GetRawTextureData());
        }

        private static void SetLayer(Transform t)
        {
            t.gameObject.layer = Layer;
            foreach (Transform c in t)
                SetLayer(c);
        }

        private static string Fmt(Vector3 v) => $"{v.x:F4} {v.y:F4} {v.z:F4}";
    }
}
