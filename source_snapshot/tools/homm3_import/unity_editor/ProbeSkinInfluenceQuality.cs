// Temporary diagnostic. Deploy to <UnityProject>/Assets/Editor and run with:
// -executeMethod ProbeSkinInfluenceQuality.Run -skinQualityProbeOut <json>
// It uses only a synthetic mesh and restores QualitySettings.skinWeights.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Unity.Collections;
using UnityEditor;
using UnityEngine;

public static class ProbeSkinInfluenceQuality
{
    [Serializable]
    private class CaseResult
    {
        public string name;
        public int globalSkinWeights;
        public int rendererQuality;
        public int serializedQuality;
        public int bonesPerVertex;
        public float[] bakedVertices;
        public bool differsFromBone4;
    }

    [Serializable]
    private class Report
    {
        public string proof = "synthetic Unity editor BakeMesh diagnostic; no game/global setting persisted";
        public int originalGlobalSkinWeights;
        public int restoredGlobalSkinWeights;
        public int vertexCount;
        public int influenceCountPerVertex;
        public List<CaseResult> cases = new List<CaseResult>();
    }

    public static void Run()
    {
        string output = null;
        var args = Environment.GetCommandLineArgs();
        for (int i = 0; i + 1 < args.Length; i++)
            if (args[i] == "-skinQualityProbeOut") output = args[i + 1];
        if (string.IsNullOrEmpty(output))
            throw new InvalidOperationException("ProbeSkinInfluenceQuality requires -skinQualityProbeOut");

        int original = (int)QualitySettings.skinWeights;
        var report = new Report { originalGlobalSkinWeights = original, vertexCount = 3, influenceCountPerVertex = 8 };
        GameObject root = null;
        try
        {
            root = new GameObject("__skin_quality_probe_root__");
            var rendererObject = new GameObject("__skin_quality_probe_renderer__");
            rendererObject.transform.SetParent(root.transform, false);
            var renderer = rendererObject.AddComponent<SkinnedMeshRenderer>();
            var mesh = BuildMesh(root.transform, out Transform[] bones);
            renderer.sharedMesh = mesh;
            renderer.bones = bones;
            renderer.rootBone = root.transform;

            var cases = new[]
            {
                new object[] { "global4_renderer4", (SkinQuality)4, (SkinQuality)4 },
                new object[] { "global4_rendererAuto", (SkinQuality)4, SkinQuality.Auto },
                new object[] { "global4_renderer255", (SkinQuality)4, (SkinQuality)255 },
                new object[] { "global255_renderer255", (SkinQuality)255, (SkinQuality)255 },
                new object[] { "global255_renderer4", (SkinQuality)255, (SkinQuality)4 },
            };
            var bakedByName = new Dictionary<string, float[]>();
            foreach (object[] item in cases)
            {
                string name = (string)item[0];
                QualitySettings.skinWeights = (SkinWeights)(int)(SkinQuality)item[1];
                renderer.quality = (SkinQuality)item[2];
                var baked = new Mesh { name = name + "_baked" };
                renderer.BakeMesh(baked, false);
                var vertices = baked.vertices.SelectMany(v => new[] { v.x, v.y, v.z }).ToArray();
                var bonesPerVertexValues = mesh.GetBonesPerVertex();
                int bonesPerVertex = bonesPerVertexValues.Length > 0 ? bonesPerVertexValues[0] : 0;
                bonesPerVertexValues.Dispose();
                int serializedQuality = (int)renderer.quality;
                var serialized = EditorJsonUtility.ToJson(renderer);
                var qualityMatch = Regex.Match(serialized, "\\\"m_Quality\\\"\\s*:\\s*(\\d+)");
                if (qualityMatch.Success)
                    serializedQuality = int.Parse(qualityMatch.Groups[1].Value);
                var result = new CaseResult
                {
                    name = name,
                    globalSkinWeights = (int)QualitySettings.skinWeights,
                    rendererQuality = (int)renderer.quality,
                    serializedQuality = serializedQuality,
                    bonesPerVertex = bonesPerVertex,
                    bakedVertices = vertices,
                };
                report.cases.Add(result);
                bakedByName[name] = vertices;
                UnityEngine.Object.DestroyImmediate(baked);
            }
            var baseline = bakedByName["global4_renderer4"];
            foreach (var result in report.cases)
                result.differsFromBone4 = !Same(result.bakedVertices, baseline);
            report.restoredGlobalSkinWeights = original;
            var json = JsonUtility.ToJson(report, true);
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output)));
            File.WriteAllText(output, json + "\n");
            Debug.Log("ProbeSkinInfluenceQuality wrote " + output);
        }
        finally
        {
            QualitySettings.skinWeights = (SkinWeights)original;
            if (root != null) UnityEngine.Object.DestroyImmediate(root);
        }
    }

    private static Mesh BuildMesh(Transform root, out Transform[] bones)
    {
        var mesh = new Mesh { name = "__skin_quality_probe_mesh__" };
        mesh.vertices = new[] { Vector3.zero, Vector3.zero, Vector3.zero };
        mesh.triangles = new[] { 0, 1, 2 };
        bones = new Transform[8];
        var bindposes = new Matrix4x4[8];
        var counts = new NativeArray<byte>(3, Allocator.Temp);
        var weights = new NativeArray<BoneWeight1>(24, Allocator.Temp);
        for (int vertex = 0; vertex < 3; vertex++)
        {
            counts[vertex] = 8;
            for (int bone = 0; bone < 8; bone++)
                weights[vertex * 8 + bone] = new BoneWeight1 { boneIndex = bone, weight = 1f / 8f };
        }
        for (int bone = 0; bone < 8; bone++)
        {
            var child = new GameObject("ProbeBone_" + bone).transform;
            child.SetParent(root, false);
            child.localPosition = new Vector3(bone * 0.25f, 0f, 0f);
            bindposes[bone] = child.worldToLocalMatrix;
            child.localPosition = new Vector3(bone * 0.25f, 0.1f * (bone + 1), 0f);
            bones[bone] = child;
        }
        mesh.bindposes = bindposes;
        mesh.SetBoneWeights(counts, weights);
        counts.Dispose();
        weights.Dispose();
        return mesh;
    }

    private static bool Same(float[] left, float[] right)
    {
        if (left == null || right == null || left.Length != right.Length) return false;
        for (int i = 0; i < left.Length; i++)
            if (Mathf.Abs(left[i] - right[i]) > 1e-5f) return false;
        return true;
    }
}
