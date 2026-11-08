using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Unity.Collections;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
    // Generated-bundle proof only. This never claims game-runtime or gameplay proof.
    public static class ProbeMocapDeliveryBundles
    {
        [Serializable] private class Spec { public string schema; public bool sourceMotionAnalyzed; public Unit[] units; }
        [Serializable] private class Unit { public string labSid, bundlePath, prefabAssetPath; public ClipSpec[] clips; }
        [Serializable] private class ClipSpec { public string name, assetPath; public bool expectedMotion; public float[] sampleTimes; }
        [Serializable] private class Report { public string schema = "homm3_mocap_bundle_probe.v1"; public string proof = "generated-asset-only"; public List<Result> units = new List<Result>(); }
        [Serializable] private class Result { public string labSid, bundlePath, prefabAssetPath; public bool ok, finiteRest, finiteBindposes, unlimitedMarker, animatorController; public int rendererCount, maxBonesPerVertex, highInfluenceVertices; public List<ClipResult> clips = new List<ClipResult>(); public string error; }
        [Serializable] private class ClipResult { public string name; public bool addressable, finite, nonBlank, expectedMotion, motionObserved; public float length; public int sampledFrames; }

        public static void Run()
        {
            string specPath = Arg("-mocapProbeSpec"); string output = Arg("-mocapProbeOut");
            if (string.IsNullOrEmpty(specPath) || string.IsNullOrEmpty(output)) throw new InvalidOperationException("ProbeMocapDeliveryBundles requires -mocapProbeSpec and -mocapProbeOut");
            var spec = JsonUtility.FromJson<Spec>(File.ReadAllText(specPath));
            if (spec == null || spec.units == null || spec.units.Length == 0) throw new InvalidOperationException("probe spec has no units");
            if (spec.schema != "homm3_mocap_bundle_probe_spec.v2" || !spec.sourceMotionAnalyzed)
                throw new InvalidOperationException("probe spec is not source-pinned v2 motion evidence");
            var report = new Report(); int original = (int)QualitySettings.skinWeights;
            try { QualitySettings.skinWeights = SkinWeights.Unlimited; foreach (var unit in spec.units) report.units.Add(Probe(unit));
                bool failed = report.units.Any(x => !x.ok);
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))); File.WriteAllText(output, JsonUtility.ToJson(report, true) + "\n"); Debug.Log("ProbeMocapDeliveryBundles wrote " + output);
                if (failed) throw new InvalidOperationException("one or more mocap bundle probes failed");
            } finally { QualitySettings.skinWeights = (SkinWeights)original; }
        }

        private static Result Probe(Unit unit)
        {
            var result = new Result { labSid = unit.labSid, bundlePath = unit.bundlePath, prefabAssetPath = unit.prefabAssetPath };
            AssetBundle bundle = null; GameObject instance = null;
            try
            {
                if (string.IsNullOrEmpty(unit.labSid) || string.IsNullOrEmpty(unit.bundlePath) || string.IsNullOrEmpty(unit.prefabAssetPath) || unit.clips == null || unit.clips.Length == 0) throw new InvalidOperationException("unit mapping/spec incomplete");
                bundle = AssetBundle.LoadFromFile(unit.bundlePath); if (bundle == null) throw new InvalidOperationException("bundle load failed");
                string prefabName = ExactAsset(bundle.GetAllAssetNames(), unit.prefabAssetPath); if (prefabName == null) throw new InvalidOperationException("owned prefab is not addressable");
                var prefab = bundle.LoadAsset<GameObject>(prefabName); if (prefab == null) throw new InvalidOperationException("owned prefab load failed");
                instance = UnityEngine.Object.Instantiate(prefab); instance.SetActive(true);
                result.unlimitedMarker = HasMarker(instance, "__homm3_skin_weights_unlimited__"); if (!result.unlimitedMarker) throw new InvalidOperationException("unlimited skin marker missing");
                var animator = instance.GetComponentInChildren<Animator>(true); result.animatorController = animator != null && animator.runtimeAnimatorController != null; if (!result.animatorController) throw new InvalidOperationException("Animator controller missing");
                var renderers = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true); if (renderers.Length == 0) throw new InvalidOperationException("no skinned renderer"); result.rendererCount = renderers.Length;
                bool anyEight = false; foreach (var renderer in renderers) { var mesh = renderer.sharedMesh; if (mesh == null || !Finite(mesh.vertices)) throw new InvalidOperationException("non-finite rest vertices"); if (!Finite(mesh.bindposes)) throw new InvalidOperationException("non-finite bindposes"); result.finiteRest = true; result.finiteBindposes = true; using (NativeArray<byte> counts = mesh.GetBonesPerVertex()) for (int i = 0; i < counts.Length; i++) { result.maxBonesPerVertex = Math.Max(result.maxBonesPerVertex, counts[i]); if (counts[i] > 4) { result.highInfluenceVertices++; anyEight = true; } } }
                if (!anyEight) throw new InvalidOperationException("no serialized vertex has more than four influences");
                animator.enabled = false; foreach (ClipSpec clip in unit.clips) ProbeClip(bundle, unit, clip, instance, renderers, result);
                result.ok = true;
            }
            catch (Exception ex) { result.error = ex.Message; }
            finally { if (instance != null) UnityEngine.Object.DestroyImmediate(instance); if (bundle != null) bundle.Unload(false); }
            return result;
        }

        private static void ProbeClip(AssetBundle bundle, Unit unit, ClipSpec expected, GameObject instance, SkinnedMeshRenderer[] renderers, Result result)
        {
            if (expected.sampleTimes == null || expected.sampleTimes.Length == 0)
                throw new InvalidOperationException("probe clip has no source-pinned sample times: " + expected.name);
            string assetName = ExactAsset(bundle.GetAllAssetNames(), expected.name);
            if (assetName == null) throw new InvalidOperationException("clip is not addressable: " + expected.name);
            var clip = bundle.LoadAsset<AnimationClip>(assetName);
            if (clip == null) throw new InvalidOperationException("clip load failed: " + expected.name);
            var clipResult = new ClipResult { name = expected.name, expectedMotion = expected.expectedMotion, addressable = true, length = clip.length };
            if (expected.sampleTimes.Any(time => float.IsNaN(time) || float.IsInfinity(time) || time < 0f))
                throw new InvalidOperationException("probe clip has invalid source-pinned sample times: " + expected.name);
            float expectedLength = expected.sampleTimes.Max();
            if (expectedLength <= 1e-5f) expectedLength = 1f / 12f;
            if (Mathf.Abs(clip.length - expectedLength) > 1e-3f)
                throw new InvalidOperationException("clip duration differs from raw source: " + expected.name);
            Vector3[] first = null; bool changed = false; bool finite = true, nonBlank = true;
            foreach (float t in expected.sampleTimes)
            {
                clip.SampleAnimation(instance, t);
                var all = new List<Vector3>();
                foreach (var renderer in renderers)
                {
                    var baked = new Mesh(); renderer.BakeMesh(baked, false);
                    var vertices = baked.vertices;
                    finite &= Finite(vertices); nonBlank &= vertices.Length > 0 && BoundsSize(vertices) > 1e-12f;
                    all.AddRange(vertices); UnityEngine.Object.DestroyImmediate(baked);
                }
                if (first == null) first = all.ToArray(); else changed |= !Same(first, all);
                clipResult.sampledFrames++;
            }
            clipResult.finite = finite; clipResult.nonBlank = nonBlank; clipResult.motionObserved = changed; result.clips.Add(clipResult);
            if (!finite || !nonBlank) throw new InvalidOperationException("clip baked non-finite or blank: " + expected.name);
            if (expected.expectedMotion && !changed) throw new InvalidOperationException("clip has source-varying motion but no observed mesh motion: " + expected.name);
        }

        private static string Arg(string name) { var a = Environment.GetCommandLineArgs(); for (int i = 0; i + 1 < a.Length; i++) if (a[i] == name) return a[i + 1]; return null; }
        private static string ExactAsset(string[] names, string wanted) { return names.FirstOrDefault(x => string.Equals(x, wanted, StringComparison.OrdinalIgnoreCase)); }
        private static bool HasMarker(GameObject root, string name) { return root.GetComponentsInChildren<Transform>(true).Any(x => x.name == name); }
        private static bool Finite(Vector3[] v) { return v != null && v.All(x => IsFinite(x.x) && IsFinite(x.y) && IsFinite(x.z)); }
        private static bool Finite(Matrix4x4[] m) { return m != null && m.All(x => Enumerable.Range(0, 16).All(i => IsFinite(x[i / 4, i % 4]))); }
        private static bool IsFinite(float x) { return !float.IsNaN(x) && !float.IsInfinity(x); }
        private static float BoundsSize(Vector3[] v) { var b = new Bounds(v[0], Vector3.zero); for (int i = 1; i < v.Length; i++) b.Encapsulate(v[i]); return b.size.sqrMagnitude; }
        private static bool Same(Vector3[] a, List<Vector3> b) { if (a.Length != b.Count) return false; for (int i = 0; i < a.Length; i++) if ((a[i] - b[i]).sqrMagnitude > 1e-10f) return false; return true; }
    }
}
