using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace OldenEra.Homm3Import
{
    // Generated-bundle proof only (editor load of the built AssetBundle); never game-runtime proof.
    // Spec: tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py probe (displacementMaskGlb rows only).
    // Hex/Lit FLAG displacement (Homm3MeshFx battle_body_displacement) reads the body mesh's COLOR.r; this reads the
    // colour stream back out of the built bundle so the ship step can compare it with the bake stamp.
    public static class ProbeDisplacementMaskBundles
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
        [Serializable] private class Unit { public string labSid, bundlePath, prefabAssetPath; }
        [Serializable] private class Report
        {
            public string schema = "homm3_displacement_mask_bundle_probe.v1";
            public string proof = "generated-asset-only (editor-loaded bundle)";
            public List<Result> units = new List<Result>();
        }
        [Serializable] private class Result
        {
            public string labSid; public bool ok; public bool vertexColors; public string colorFormat;
            public int vertexCount; public float maskMean; public float maskMax; public float fractionAboveHalf;
            public List<string> errors = new List<string>();
        }

        public static void Run()
        {
            string specPath = Arg("-displacementProbeSpec"), output = Arg("-displacementProbeOut");
            if (string.IsNullOrEmpty(specPath) || string.IsNullOrEmpty(output))
                throw new InvalidOperationException("ProbeDisplacementMaskBundles requires -displacementProbeSpec and -displacementProbeOut");
            var spec = JsonUtility.FromJson<Spec>(File.ReadAllText(specPath));
            if (spec == null || spec.schema != "homm3_displacement_mask_bundle_probe_spec.v1" || spec.units == null || spec.units.Length == 0)
                throw new InvalidOperationException("displacement probe spec schema/units invalid");
            var report = new Report();
            foreach (var unit in spec.units)
                report.units.Add(Probe(unit));
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output)));
            File.WriteAllText(output, JsonUtility.ToJson(report, true) + "\n");
            Debug.Log("ProbeDisplacementMaskBundles wrote " + output);
            if (report.units.Any(u => !u.ok))
                throw new InvalidOperationException("one or more displacement mask bundle probes failed");
        }

        private static Result Probe(Unit unit)
        {
            var r = new Result { labSid = unit.labSid };
            AssetBundle bundle = null; GameObject instance = null;
            try
            {
                bundle = AssetBundle.LoadFromFile(unit.bundlePath);
                if (bundle == null) throw new InvalidOperationException("bundle load failed");
                string prefabName = bundle.GetAllAssetNames().FirstOrDefault(n => string.Equals(n, unit.prefabAssetPath, StringComparison.OrdinalIgnoreCase));
                if (prefabName == null) throw new InvalidOperationException("prefab not addressable");
                instance = UnityEngine.Object.Instantiate(bundle.LoadAsset<GameObject>(prefabName));
                var skins = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true);
                if (skins.Length != 1 || skins[0].sharedMesh == null)
                    throw new InvalidOperationException("expected one SkinnedMeshRenderer with a mesh, found " + skins.Length);
                Mesh mesh = skins[0].sharedMesh;
                r.vertexCount = mesh.vertexCount;
                r.vertexColors = mesh.HasVertexAttribute(VertexAttribute.Color);
                if (!r.vertexColors)
                    r.errors.Add("body mesh has no vertex colour stream in the bundle (the runtime would refuse the displacement row)");
                else
                {
                    r.colorFormat = mesh.GetVertexAttributeFormat(VertexAttribute.Color).ToString();
                    if (!mesh.isReadable)
                        r.errors.Add("body mesh is not readable; cannot read the mask back");
                    else
                    {
                        Color[] colors = mesh.colors;
                        if (colors.Length != mesh.vertexCount) r.errors.Add("colour count " + colors.Length + " != vertices " + mesh.vertexCount);
                        else if (colors.Length > 0)
                        {
                            double sum = 0; float max = 0; int above = 0;
                            foreach (Color c in colors) { sum += c.r; if (c.r > max) max = c.r; if (c.r > 0.5f) above++; }
                            r.maskMean = (float)(sum / colors.Length);
                            r.maskMax = max;
                            r.fractionAboveHalf = (float)above / colors.Length;
                            if (max <= 0f) r.errors.Add("mask is all zero in the bundle; nothing would move");
                        }
                    }
                }
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

        private static string Arg(string name)
        {
            string[] args = UnityQueueArgs();
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == name) return args[i + 1];
            return null;
        }
    }
}
