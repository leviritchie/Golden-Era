// Unity-editor preview of the adventure-map building animation pilots
// (tools/homm3_map_building_meshes/preview_map_building_anim.py stages and drives this).
//
// Per job: instantiate the built prefab from Assets/Homm3MapBuildingMeshes, sample the prefab's own
// rotor clip (the clip the bundle ships), put camera-facing flipbook quads on the baked anchors the
// same way Homm3MapBuildingAnim.AttachFlipbooks does at runtime (bottom-centre pivot, quadSize, root
// rotation locked to the camera), swap frames at frameMs, and write one PNG per sample.
// Billboard jobs render the composite frames on a single camera-facing quad.
//
// Proof level: Unity-editor render with a plain CG preview shader (albedo x lambert for the body,
// alpha clip for quads), not the in-game Hex/Lit shader and not in-game playback.
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3MapAnim
{
    public static class Homm3MapBuildingAnimPreview
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
        class Spec
        {
            public string outDir;
            public int width;
            public int height;
            public Job[] jobs;
        }

        [Serializable]
        class Job
        {
            public string name;
            public string prefabPath;       // empty for billboard jobs
            public string clipPath;         // rotor clip, optional
            public float frameMs;
            public int samples;
            public float pitch;
            public Flip[] flips;
            public string[] billboardFrames; // absolute PNG paths, billboard jobs only
        }

        [Serializable]
        class Flip
        {
            public string anchor;
            public float quadW;
            public float quadH;
            public string[] frames;         // absolute PNG paths
        }

        public static void RenderFromCommandLine()
        {
            string specPath = null;
            var args = UnityQueueArgs();
            for (var i = 0; i < args.Length - 1; i++)
                if (args[i] == "-homm3MapAnimPreviewSpec")
                    specPath = args[i + 1];
            if (string.IsNullOrEmpty(specPath))
                throw new InvalidOperationException("-homm3MapAnimPreviewSpec <file> is required");
            var spec = JsonUtility.FromJson<Spec>(File.ReadAllText(specPath));
            // URP shaders render magenta in this batch run; the preview uses its own plain CG shader
            // (no LightMode tag, drawn through SRPDefaultUnlit), like the VFX light lab.
            var unlit = Shader.Find("Hidden/Homm3MapAnimPreview/Simple");
            if (unlit == null)
                throw new InvalidOperationException("Hidden/Homm3MapAnimPreview/Simple not found (stage the .shader)");

            var camGo = new GameObject("MapAnimPreviewCam");
            var cam = camGo.AddComponent<Camera>();
            cam.orthographic = true;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.36f, 0.45f, 0.30f, 1f);
            cam.nearClipPlane = 0.01f;
            cam.farClipPlane = 100f;
            var lightGo = new GameObject("MapAnimPreviewSun");
            var sun = lightGo.AddComponent<Light>();
            sun.type = LightType.Directional;
            sun.intensity = 1.2f;
            lightGo.transform.rotation = Quaternion.Euler(50f, 150f, 0f);
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.45f, 0.45f, 0.45f);

            var rt = new RenderTexture(spec.width, spec.height, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB) { antiAliasing = 4 };
            rt.Create();
            cam.targetTexture = rt;
            var read = new Texture2D(spec.width, spec.height, TextureFormat.RGBA32, false);

            foreach (var job in spec.jobs)
            {
                var jobDir = Path.Combine(spec.outDir, job.name);
                Directory.CreateDirectory(jobDir);
                // The in-game map camera looks toward +Z (south); the mesh is posed like the runtime does.
                cam.transform.rotation = Quaternion.Euler(job.pitch, 0f, 0f);
                GameObject root;
                AnimationClip clip = null;
                var quads = new List<KeyValuePair<Transform, KeyValuePair<Material, Texture2D[]>>>();
                if (!string.IsNullOrEmpty(job.prefabPath))
                {
                    var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(job.prefabPath);
                    if (prefab == null)
                        throw new InvalidOperationException("prefab not found: " + job.prefabPath);
                    root = (GameObject)UnityEngine.Object.Instantiate(prefab);
                    root.transform.position = Vector3.zero;
                    ReplicaRuntimePose(root.transform);
                    // The prefab's shipping material targets the game's Hex/Lit and renders magenta in this
                    // URP editor; preview with the plain CG shader on the prefab's own baked albedo.
                    var albedo = AssetDatabase.LoadAssetAtPath<Texture2D>(job.prefabPath.Replace(".prefab", "_albedo.png"));
                    if (albedo == null)
                        throw new InvalidOperationException(job.name + ": albedo not found next to " + job.prefabPath);
                    var lit = new Material(unlit);
                    lit.SetTexture("_MainTex", albedo);
                    lit.SetFloat("_Lit", 1f);
                    lit.SetFloat("_Cutoff", -1f);
                    foreach (var r in root.GetComponentsInChildren<Renderer>(true))
                    {
                        var mats = r.sharedMaterials;
                        for (var mi = 0; mi < mats.Length; mi++)
                            mats[mi] = lit;
                        r.sharedMaterials = mats;
                    }
                    if (!string.IsNullOrEmpty(job.clipPath))
                    {
                        clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(job.clipPath);
                        if (clip == null)
                            throw new InvalidOperationException("clip not found: " + job.clipPath);
                        if (root.GetComponent<Animator>() == null)
                            throw new InvalidOperationException(job.name + ": rotor prefab has no Animator");
                    }
                    foreach (var f in job.flips ?? new Flip[0])
                    {
                        var anchor = FindDeep(root.transform, f.anchor);
                        if (anchor == null)
                            throw new InvalidOperationException(job.name + ": anchor missing " + f.anchor);
                        var flipRoot = new GameObject("flip").transform;
                        flipRoot.SetParent(anchor, false);
                        var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
                        UnityEngine.Object.DestroyImmediate(quad.GetComponent<Collider>());
                        quad.transform.SetParent(flipRoot, false);
                        quad.transform.localPosition = new Vector3(0f, f.quadH * 0.5f, 0f);
                        quad.transform.localScale = new Vector3(f.quadW, f.quadH, 1f);
                        var frames = LoadFrames(f.frames);
                        var mat = CutoutMaterial(unlit, frames[0]);
                        quad.GetComponent<MeshRenderer>().sharedMaterial = mat;
                        quads.Add(new KeyValuePair<Transform, KeyValuePair<Material, Texture2D[]>>(flipRoot, new KeyValuePair<Material, Texture2D[]>(mat, frames)));
                    }
                }
                else
                {
                    root = new GameObject("billboard");
                    var frames = LoadFrames(job.billboardFrames);
                    var flipRoot = new GameObject("flip").transform;
                    flipRoot.SetParent(root.transform, false);
                    var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
                    UnityEngine.Object.DestroyImmediate(quad.GetComponent<Collider>());
                    quad.transform.SetParent(flipRoot, false);
                    var aspect = frames[0].width / (float)frames[0].height;
                    quad.transform.localPosition = new Vector3(0f, 0.5f, 0f);
                    quad.transform.localScale = new Vector3(aspect, 1f, 1f);
                    var mat = CutoutMaterial(unlit, frames[0]);
                    quad.GetComponent<MeshRenderer>().sharedMaterial = mat;
                    quads.Add(new KeyValuePair<Transform, KeyValuePair<Material, Texture2D[]>>(flipRoot, new KeyValuePair<Material, Texture2D[]>(mat, frames)));
                }

                // Frame the whole object (including quads) once at t=0.
                if (clip != null)
                    clip.SampleAnimation(root, 0f);
                foreach (var q in quads)
                    q.Key.rotation = cam.transform.rotation;
                var bounds = new Bounds(Vector3.zero, Vector3.zero);
                var first = true;
                foreach (var r in root.GetComponentsInChildren<Renderer>())
                {
                    if (first) { bounds = r.bounds; first = false; }
                    else bounds.Encapsulate(r.bounds);
                }
                cam.transform.position = bounds.center - cam.transform.forward * 20f;
                var local = new Vector3(
                    Vector3.Dot(bounds.extents, Abs(cam.transform.right)),
                    Vector3.Dot(bounds.extents, Abs(cam.transform.up)), 0f);
                cam.orthographicSize = Mathf.Max(local.y, local.x * spec.height / spec.width) * 1.08f;

                for (var s = 0; s < job.samples; s++)
                {
                    var t = s * job.frameMs / 1000f;
                    if (clip != null)
                        clip.SampleAnimation(root, t);
                    foreach (var q in quads)
                    {
                        q.Key.rotation = cam.transform.rotation; // Homm3BattleBillboardCameraFacing: root world rotation = camera
                        var frames = q.Value.Value;
                        q.Value.Key.SetTexture("_MainTex", frames[s % frames.Length]);
                    }
                    cam.Render();
                    var prev = RenderTexture.active;
                    RenderTexture.active = rt;
                    read.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0, false);
                    read.Apply();
                    RenderTexture.active = prev;
                    File.WriteAllBytes(Path.Combine(jobDir, "f" + s.ToString("000") + ".png"), read.EncodeToPNG());
                }
                UnityEngine.Object.DestroyImmediate(root);
                Debug.Log("HOMM3_MAP_ANIM_PREVIEW job " + job.name + " samples=" + job.samples + " flips=" + quads.Count + " rotorClip=" + (clip != null));
            }
            Debug.Log("HOMM3_MAP_ANIM_PREVIEW_OK");
        }

        // Replica of Homm3MapBuildingMeshBundle.OrientToBillboardArtAndSeat (mapFacing 0, catalog artYaw 0):
        // the runtime overwrites the prefab root rotation with Euler(0, 180 + artYaw, 0) * upright, where
        // upright is only non-identity when the bounds look flat, and artYaw is picked by a bounds score.
        static void ReplicaRuntimePose(Transform root)
        {
            const float frontYaw = 180f;
            var upright = Quaternion.identity;
            var size = MeshBounds(root).size;
            if (size.y < size.x * 0.85f && size.y < size.z * 0.85f)
            {
                var candidates = new[] { Quaternion.identity, Quaternion.Euler(-90f, 0f, 0f), Quaternion.Euler(90f, 0f, 0f), Quaternion.Euler(0f, 0f, -90f), Quaternion.Euler(0f, 0f, 90f) };
                var bestHeight = -1f;
                foreach (var c in candidates)
                {
                    root.localRotation = c;
                    var h = MeshBounds(root).size.y;
                    if (h <= bestHeight)
                        continue;
                    bestHeight = h;
                    upright = c;
                }
            }
            var bestYaw = 0f;
            var bestScore = float.NegativeInfinity;
            foreach (var yaw in new[] { -25f, -15f, 0f, 15f, 25f })
            {
                root.localRotation = Quaternion.Euler(0f, frontYaw + yaw, 0f) * upright;
                var sz = MeshBounds(root).size;
                var score = sz.y * 0.5f + sz.x * 0.45f - sz.z * 0.45f;
                if (score <= bestScore)
                    continue;
                bestScore = score;
                bestYaw = yaw;
            }
            root.localRotation = Quaternion.Euler(0f, frontYaw + bestYaw, 0f) * upright;
            Debug.Log("HOMM3_MAP_ANIM_PREVIEW pose " + root.name + " upright=" + upright.eulerAngles + " artYaw=" + bestYaw);
        }

        static Bounds MeshBounds(Transform root)
        {
            var rs = root.GetComponentsInChildren<MeshRenderer>(true);
            var b = rs[0].bounds;
            for (var i = 1; i < rs.Length; i++)
                b.Encapsulate(rs[i].bounds);
            return b;
        }

        static Vector3 Abs(Vector3 v) => new Vector3(Mathf.Abs(v.x), Mathf.Abs(v.y), Mathf.Abs(v.z));

        static Material CutoutMaterial(Shader unlit, Texture2D tex)
        {
            var m = new Material(unlit);
            m.SetTexture("_MainTex", tex);
            m.SetFloat("_Lit", 0f);
            m.SetFloat("_Cutoff", 0.5f);
            return m;
        }

        static Texture2D[] LoadFrames(string[] paths)
        {
            if (paths == null || paths.Length == 0)
                throw new InvalidOperationException("no frames");
            var list = new Texture2D[paths.Length];
            for (var i = 0; i < paths.Length; i++)
            {
                var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
                if (!tex.LoadImage(File.ReadAllBytes(paths[i])))
                    throw new InvalidOperationException("bad png " + paths[i]);
                tex.wrapMode = TextureWrapMode.Clamp;
                tex.filterMode = FilterMode.Bilinear;
                list[i] = tex;
            }
            return list;
        }

        static Transform FindDeep(Transform t, string name)
        {
            if (t.name == name)
                return t;
            for (var i = 0; i < t.childCount; i++)
            {
                var hit = FindDeep(t.GetChild(i), name);
                if (hit != null)
                    return hit;
            }
            return null;
        }
    }
}
