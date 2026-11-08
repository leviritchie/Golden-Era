using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
    // Generated-bundle proof only (editor load of the built AssetBundle); never game-runtime proof.
    // Spec: tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py probe.
    public static class ProbeDefRetargetDeliveryBundles
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

        [Serializable] private class Spec { public string schema; public Unit[] units; }
        [Serializable] private class Unit
        {
            public string labSid, bundlePath, prefabAssetPath; public string[] clipNames; public float idleLength;
            public string[] quadNames; public string[] lightNames; public int uvAtlasCells; public Check[] checks;
            // mergeMeshes (a death shatter's rubble on the body SMR): the SMR's vertex count and the body's own
            // leading range (rest height for "meshRange"); 0 = the unit merges nothing
            public int meshVertices; public int bodyVertices;
        }
        [Serializable] private class Check { public string clip; public float t; public string kind; public string path; public float[] values; }
        [Serializable] private class Report { public string schema = "homm3_def_retarget_bundle_probe.v1"; public string proof = "generated-asset-only (editor-loaded bundle)"; public List<Result> units = new List<Result>(); }
        [Serializable] private class Result
        {
            public string labSid; public bool ok; public int blendShapeCount; public float blendShapeFrameWeight; public int checksPassed;
            public int quadNodes; public int lightNodes; public int uvAtlasCells; public bool orientationNode; public bool laneMarker;
            public int meshVertexCount; public int meshRangeChecks;
            public List<string> clips = new List<string>(); public List<string> errors = new List<string>();
        }

        public static void Run()
        {
            string specPath = Arg("-defRetargetProbeSpec"), output = Arg("-defRetargetProbeOut");
            if (string.IsNullOrEmpty(specPath) || string.IsNullOrEmpty(output))
                throw new InvalidOperationException("ProbeDefRetargetDeliveryBundles requires -defRetargetProbeSpec and -defRetargetProbeOut");
            var spec = JsonUtility.FromJson<Spec>(File.ReadAllText(specPath));
            if (spec == null || spec.schema != "homm3_def_retarget_bundle_probe_spec.v1" || spec.units == null || spec.units.Length == 0)
                throw new InvalidOperationException("probe spec schema/units invalid");
            var report = new Report();
            foreach (var unit in spec.units)
                report.units.Add(Probe(unit));
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output)));
            File.WriteAllText(output, JsonUtility.ToJson(report, true) + "\n");
            Debug.Log("ProbeDefRetargetDeliveryBundles wrote " + output);
            if (report.units.Any(u => !u.ok))
                throw new InvalidOperationException("one or more def_retarget bundle probes failed");
        }

        private static Result Probe(Unit unit)
        {
            var r = new Result { labSid = unit.labSid };
            AssetBundle bundle = null; GameObject instance = null;
            try
            {
                bundle = AssetBundle.LoadFromFile(unit.bundlePath);
                if (bundle == null) throw new InvalidOperationException("bundle load failed");
                string[] names = bundle.GetAllAssetNames();
                string prefabName = Exact(names, unit.prefabAssetPath);
                if (prefabName == null) throw new InvalidOperationException("prefab not addressable");
                instance = UnityEngine.Object.Instantiate(bundle.LoadAsset<GameObject>(prefabName));
                var all = instance.GetComponentsInChildren<Transform>(true);
                r.orientationNode = all.Any(t => t.name == "Orientation" && t.parent == instance.transform);
                r.laneMarker = all.Any(t => t.name == "__homm3_skinned_battle_lane__");
                if (!r.orientationNode) r.errors.Add("no Orientation child under the prefab root");
                if (!r.laneMarker) r.errors.Add("skinned lane marker missing");
                var skins = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true);
                if (skins.Length != 1) throw new InvalidOperationException("expected one SkinnedMeshRenderer, found " + skins.Length);
                var body = skins[0];
                r.blendShapeCount = body.sharedMesh.blendShapeCount;
                r.blendShapeFrameWeight = r.blendShapeCount > 0 ? body.sharedMesh.GetBlendShapeFrameWeight(0, body.sharedMesh.GetBlendShapeFrameCount(0) - 1) : 0f;
                if (r.blendShapeCount == 0) r.errors.Add("mesh has no blend shapes in the bundle");
                r.meshVertexCount = body.sharedMesh.vertexCount;
                if (unit.meshVertices > 0 && r.meshVertexCount != unit.meshVertices)
                    r.errors.Add("body mesh has " + r.meshVertexCount + " vertices, the merged master " + unit.meshVertices + " (merged rubble lost)");
                var animator = instance.GetComponent<Animator>();
                if (animator == null || !(animator.runtimeAnimatorController is AnimatorOverrideController))
                    r.errors.Add("prefab Animator has no override controller");
                else
                    animator.enabled = false;
                foreach (string q in unit.quadNames ?? new string[0])
                    if (all.Count(t => t.name == q) == 1) r.quadNodes++; else r.errors.Add("quad holder missing: " + q);
                foreach (string l in unit.lightNames ?? new string[0])
                {
                    var t = all.FirstOrDefault(x => x.name == l);
                    if (t != null && t.GetComponent<Light>() != null) r.lightNodes++; else r.errors.Add("light missing: " + l);
                }
                var atlas = all.FirstOrDefault(t => t.name == "__homm3_vfx_uvatlas__");
                r.uvAtlasCells = atlas != null ? atlas.childCount : 0;
                if (r.uvAtlasCells != unit.uvAtlasCells) r.errors.Add("uvAtlas cells " + r.uvAtlasCells + " != " + unit.uvAtlasCells);

                string root = unit.prefabAssetPath.Substring(0, unit.prefabAssetPath.LastIndexOf('/'));
                var clips = new Dictionary<string, AnimationClip>(StringComparer.Ordinal);
                foreach (string clipName in unit.clipNames)
                {
                    string asset = Exact(names, root + "/Animations/" + clipName + ".anim");
                    var clip = asset != null ? bundle.LoadAsset<AnimationClip>(asset) : null;
                    if (clip == null) { r.errors.Add("clip not addressable: " + clipName); continue; }
                    clips[clipName] = clip;
                    r.clips.Add(clipName + " length=" + clip.length.ToString("0.####") + " loop=" + clip.isLooping);
                }
                if (clips.TryGetValue("Unit_Idle", out AnimationClip idle) && Mathf.Abs(idle.length - unit.idleLength) > 1e-3f)
                    r.errors.Add("Unit_Idle length " + idle.length + " != retimed " + unit.idleLength);

                var mpb = new MaterialPropertyBlock();
                Mesh baked = null; float restHeight = -1f;
                foreach (Check c in unit.checks ?? new Check[0])
                {
                    if (!clips.TryGetValue(c.clip, out AnimationClip clip)) { r.errors.Add("check clip missing: " + c.clip); continue; }
                    clip.SampleAnimation(instance, c.t);
                    string fail = null;
                    if (c.kind == "blendOneHot")
                    {
                        float max = 0f;
                        for (int i = 0; i < r.blendShapeCount; i++) max = Mathf.Max(max, body.GetBlendShapeWeight(i));
                        if (max < 0.99f * r.blendShapeFrameWeight || max > 1.001f * r.blendShapeFrameWeight)
                            fail = "max blend weight " + max + " vs frame weight " + r.blendShapeFrameWeight;
                    }
                    else if (c.kind == "blendNone")
                    {
                        // a frame bake_cs gave no corrective shape: every shape must be off
                        float max = 0f;
                        for (int i = 0; i < r.blendShapeCount; i++) max = Mathf.Max(max, body.GetBlendShapeWeight(i));
                        if (max > 0.01f * r.blendShapeFrameWeight)
                            fail = "blend weight " + max + " on a frame with no corrective shape";
                    }
                    else if (c.kind == "st")
                    {
                        body.GetPropertyBlock(mpb);
                        Vector4 st = mpb.GetVector("_MainTex_ST");
                        for (int i = 0; i < 4 && fail == null; i++)
                            if (Mathf.Abs(st[i] - c.values[i]) > 1e-4f) fail = "ST " + st + " != cell";
                    }
                    else if (c.kind == "enabled")
                    {
                        var holder = all.FirstOrDefault(t => t.name == c.path);
                        if (holder == null) fail = "holder missing";
                        else
                        {
                            int want = Mathf.RoundToInt(c.values[0]);
                            foreach (Transform child in holder)
                            {
                                bool on = child.GetComponent<MeshRenderer>().enabled;
                                if (on != (child.name == "c" + want)) { fail = child.name + " enabled=" + on + " want cell " + want; break; }
                            }
                        }
                    }
                    else if (c.kind == "light")
                    {
                        var t = all.FirstOrDefault(x => x.name == c.path);
                        var light = t != null ? t.GetComponent<Light>() : null;
                        if (light == null) fail = "light missing";
                        else if (Mathf.Abs(light.intensity - c.values[0]) > 1e-4f || light.enabled != (c.values[0] > 0f))
                            fail = "light intensity " + light.intensity + " enabled " + light.enabled + " want " + c.values[0];
                    }
                    else if (c.kind == "meshRange")
                    {
                        // a merged vertex range [values0, +values1): its baked-skin bbox diagonal over the body's rest
                        // height must lie in [values2, values3] (rubble collapsed before the break, spread after it)
                        Mesh shared = body.sharedMesh;
                        int first = Mathf.RoundToInt(c.values[0]), count = Mathf.RoundToInt(c.values[1]);
                        if (!shared.isReadable) fail = "body mesh is not readable; cannot bake the range";
                        else if (first < 0 || count <= 0 || first + count > shared.vertexCount) fail = "range outside the mesh";
                        else
                        {
                            if (restHeight < 0f)
                            {
                                Vector3[] rest = shared.vertices;
                                int n = unit.bodyVertices > 0 ? unit.bodyVertices : rest.Length;
                                float lo = float.MaxValue, hi = float.MinValue;
                                for (int i = 0; i < n; i++) { lo = Mathf.Min(lo, rest[i].y); hi = Mathf.Max(hi, rest[i].y); }
                                restHeight = hi - lo;
                            }
                            if (baked == null) baked = new Mesh();
                            body.BakeMesh(baked);
                            Vector3[] v = baked.vertices;
                            var bounds = new Bounds(v[first], Vector3.zero);
                            for (int i = first + 1; i < first + count; i++) bounds.Encapsulate(v[i]);
                            float ratio = restHeight > 0f ? bounds.size.magnitude / restHeight : float.NaN;
                            if (!(ratio >= c.values[2] && ratio <= c.values[3]))
                                fail = "range extent / rest height " + ratio + " not in [" + c.values[2] + ", " + c.values[3] + "]";
                            else r.meshRangeChecks++;
                        }
                    }
                    else fail = "unknown check kind " + c.kind;
                    if (fail != null) r.errors.Add(c.clip + "@" + c.t.ToString("0.###") + " " + c.kind + " " + c.path + ": " + fail);
                    else r.checksPassed++;
                }
                if (baked != null) UnityEngine.Object.DestroyImmediate(baked);
                r.ok = r.errors.Count == 0;
            }
            catch (Exception ex) { r.errors.Add(ex.GetType().Name + ": " + ex.Message); r.ok = false; }
            finally
            {
                if (instance != null) UnityEngine.Object.DestroyImmediate(instance);
                if (bundle != null) bundle.Unload(true);
            }
            return r;
        }

        private static string Arg(string name) { var a = UnityQueueArgs(); for (int i = 0; i + 1 < a.Length; i++) if (a[i] == name) return a[i + 1]; return null; }
        private static string Exact(string[] names, string wanted) { return names.FirstOrDefault(x => string.Equals(x, wanted, StringComparison.OrdinalIgnoreCase)); }
    }
}
