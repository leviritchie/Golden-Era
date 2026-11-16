// Elemental Fusion stage-2 shared-mesh crest bundles (tools/homm3_def_retarget_delivery/fusion_stage2_bundles.py).
// Same bundle layout as Homm3FusionCrestBundles (stage 1): fusion_crest_anchor / fusion_crest, a one-bone
// SkinnedMeshRenderer whose mesh is in the host Head bone's bind-local space (identity bindpose, white vertex colours),
// material "fusion_crest" on the Hex/Lit stub, owned_skinned_basecolor.png (host parent's body albedo, host UVs) and
// fusion_crest_basecolor.png (crest atlas: host parent | guest parent). The crest geometry comes from a JSON written by
// the Python driver (both stage-1 parents' crests combined) instead of being cut from a full fused bundle.
// Lab assets live under Assets/CustomUnits/homm3_lab/<sid>/ and are deleted after the build. Not installed.
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Vfx
{
    public static class Homm3FusionStage2CrestBundles
    {
        [Serializable] public sealed class UnitDef { public string sid, bundleName, meshJson, bodyPng, crestPng; public int bodyMaxSize, crestMaxSize; }
        [Serializable] public sealed class Spec { public UnitDef[] units; public string outDir, report; }
        [Serializable] public sealed class MeshDef { public float[] v, n, uv; public int[] t; }

        const string LabRoot = "Assets/CustomUnits/homm3_lab/";

        // Unity queue shim (docs/unity_queue_runner.md)
        static string[] UnityQueueArgs() => AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") as string[] ?? Environment.GetCommandLineArgs();
        static void UnityQueueExit(int code)
        {
            if (AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") == null) { EditorApplication.Exit(code); return; }
            if (!(AppDomain.CurrentDomain.GetData("UnityQueue.ExitCode") is int prev && prev != 0)) AppDomain.CurrentDomain.SetData("UnityQueue.ExitCode", code);
        }

        public static void BuildFromCommandLine()
        {
            string[] args = UnityQueueArgs();
            int i = Array.IndexOf(args, "-fusionStage2Spec");
            if (i < 0 || i + 1 >= args.Length) throw new InvalidOperationException("-fusionStage2Spec <json> required");
            var spec = JsonUtility.FromJson<Spec>(File.ReadAllText(args[i + 1]));
            if (spec?.units == null || spec.units.Length == 0) throw new InvalidOperationException("spec has no units");
            if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.StandaloneWindows64)
                throw new InvalidOperationException("active build target is " + EditorUserBuildSettings.activeBuildTarget + ", not StandaloneWindows64");
            Shader stub = Shader.Find("Hex/Lit");
            if (stub == null) throw new InvalidOperationException("Hex/Lit stub shader missing from the lab project");
            var builds = new List<AssetBundleBuild>();
            var report = new List<string>();
            var made = new List<string>();
            try
            {
                foreach (UnitDef u in spec.units)
                {
                    if (!u.sid.StartsWith("h3_fusion_ii_", StringComparison.Ordinal)) throw new InvalidOperationException("refusing sid " + u.sid);
                    string unitDir = LabRoot + u.sid;
                    string root = unitDir + "/OwnedSkinned";
                    made.Add(unitDir);
                    Directory.CreateDirectory(root);
                    string bodyPath = root + "/owned_skinned_basecolor.png", crestTexPath = root + "/fusion_crest_basecolor.png";
                    File.Copy(u.bodyPng, bodyPath, true);
                    File.Copy(u.crestPng, crestTexPath, true);
                    AssetDatabase.ImportAsset(bodyPath, ImportAssetOptions.ForceSynchronousImport);
                    AssetDatabase.ImportAsset(crestTexPath, ImportAssetOptions.ForceSynchronousImport);
                    Albedo(bodyPath, u.bodyMaxSize, TextureWrapMode.Repeat);
                    Albedo(crestTexPath, u.crestMaxSize, TextureWrapMode.Clamp);
                    Texture2D crestTex = AssetDatabase.LoadAssetAtPath<Texture2D>(crestTexPath);

                    Mesh crest = BuildCrest(u, JsonUtility.FromJson<MeshDef>(File.ReadAllText(u.meshJson)));
                    AssetDatabase.CreateAsset(crest, root + "/fusion_crest_mesh.asset");

                    var mat = new Material(stub) { name = "fusion_crest", mainTexture = crestTex };
                    AssetDatabase.CreateAsset(mat, root + "/fusion_crest.mat");

                    var anchor = new GameObject("fusion_crest_anchor");
                    var go = new GameObject("fusion_crest");
                    go.transform.SetParent(anchor.transform, false);
                    var smr = go.AddComponent<SkinnedMeshRenderer>();
                    smr.sharedMesh = crest;
                    smr.bones = new[] { anchor.transform };
                    smr.rootBone = anchor.transform;
                    smr.sharedMaterial = mat;
                    smr.localBounds = crest.bounds;
                    smr.updateWhenOffscreen = true;
                    string prefabPath = root + "/fusion_crest.prefab";
                    PrefabUtility.SaveAsPrefabAsset(anchor, prefabPath);
                    UnityEngine.Object.DestroyImmediate(anchor);

                    builds.Add(new AssetBundleBuild
                    {
                        assetBundleName = u.bundleName,
                        assetNames = new[] { prefabPath, root + "/fusion_crest.mat", bodyPath, crestTexPath }
                    });
                    report.Add("\"" + u.sid + "\": {\"crestVerts\": " + crest.vertexCount + ", \"crestTris\": " + (crest.triangles.Length / 3)
                               + ", \"bounds\": \"" + crest.bounds.size.ToString("F4") + "\"}");
                }
                AssetDatabase.SaveAssets();
                Directory.CreateDirectory(spec.outDir);
                var manifest = BuildPipeline.BuildAssetBundles(spec.outDir, builds.ToArray(), BuildAssetBundleOptions.ChunkBasedCompression,
                    BuildTarget.StandaloneWindows64);
                if (manifest == null) throw new InvalidOperationException("BuildAssetBundles returned null");
                File.WriteAllText(spec.report, "{\n" + string.Join(",\n", report) + "\n}\n");
                Debug.Log("HOMM3_FUSION_STAGE2_CREST_OK " + builds.Count);
            }
            catch (Exception ex)
            {
                Debug.LogError("HOMM3_FUSION_STAGE2_CREST_FAILED " + ex);
                UnityQueueExit(1);
                throw;
            }
            finally
            {
                foreach (string d in made) AssetDatabase.DeleteAsset(d);
                AssetDatabase.Refresh();
            }
        }

        static void Albedo(string path, int maxSize, TextureWrapMode wrap)
        {
            var imp = (TextureImporter)AssetImporter.GetAtPath(path);
            imp.textureType = TextureImporterType.Default;
            imp.sRGBTexture = true;
            imp.mipmapEnabled = true;
            imp.alphaSource = TextureImporterAlphaSource.None;
            imp.wrapMode = wrap;
            imp.maxTextureSize = maxSize > 0 ? maxSize : 1024;
            imp.textureCompression = TextureImporterCompression.Compressed;
            imp.isReadable = false;
            imp.SaveAndReimport();
        }

        static Mesh BuildCrest(UnitDef u, MeshDef d)
        {
            if (d?.v == null || d.n == null || d.uv == null || d.t == null) throw new InvalidOperationException(u.sid + ": crest mesh json incomplete");
            int c = d.v.Length / 3;
            if (c < 12 || d.v.Length != 3 * c || d.n.Length != 3 * c || d.uv.Length != 2 * c || d.t.Length % 3 != 0)
                throw new InvalidOperationException(u.sid + ": crest mesh json array sizes disagree");
            var pv = new Vector3[c]; var pn = new Vector3[c]; var pu = new Vector2[c];
            for (int j = 0; j < c; j++)
            {
                pv[j] = new Vector3(d.v[3 * j], d.v[3 * j + 1], d.v[3 * j + 2]);
                pn[j] = new Vector3(d.n[3 * j], d.n[3 * j + 1], d.n[3 * j + 2]).normalized;
                pu[j] = new Vector2(d.uv[2 * j], d.uv[2 * j + 1]);
            }
            if (d.t.Any(x => x < 0 || x >= c)) throw new InvalidOperationException(u.sid + ": crest triangle index out of range");
            var mesh = new Mesh { name = "fusion_crest" };
            mesh.vertices = pv; mesh.normals = pn; mesh.uv = pu;
            mesh.SetTriangles(d.t, 0);
            var w = new BoneWeight[c];
            for (int j = 0; j < c; j++) w[j] = new BoneWeight { boneIndex0 = 0, weight0 = 1f };
            mesh.boneWeights = w;
            mesh.bindposes = new[] { Matrix4x4.identity };
            mesh.colors32 = Enumerable.Repeat(new Color32(255, 255, 255, 255), c).ToArray();
            mesh.RecalculateBounds();
            return mesh;
        }
    }
}
#endif
