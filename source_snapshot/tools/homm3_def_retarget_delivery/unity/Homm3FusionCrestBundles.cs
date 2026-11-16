// Elemental Fusion shared-mesh bundles (tools/homm3_def_retarget_delivery/fusion_shared_bundles.py): one small
// AssetBundle per fused unit holding only what differs from its host -- the crest (a one-bone SkinnedMeshRenderer whose
// mesh is in the host Head bone's bind-local space, so it rides the host's Head with an identity local transform), the
// body albedo in the host's own UV space and the crest albedo. The body mesh, skeleton, blend shapes, clips and
// Animator controller stay in the host's already-shipped bundle (plugin: Entry.meshBundleName).
//
// Input per unit: the previously built full fused bundle (source of the crest geometry: vertex range
// [crestInsertAt, crestInsertAt + crestVerts) of the body SkinnedMeshRenderer, rigid on Head, UVs on the atlas' right
// half) and the two PNGs. Lab assets are written under Assets/CustomUnits/homm3_lab/<sid>/ and deleted after the build.
// Not installed; the runner never touches the game.
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Vfx
{
    public static class Homm3FusionCrestBundles
    {
        [Serializable] public sealed class UnitDef { public string sid, bundleName, sourceBundle, bodyPng, crestPng, attachBone; public int crestInsertAt, crestVerts, crestTris, bodyMaxSize, crestMaxSize; }
        [Serializable] public sealed class Spec { public UnitDef[] units; public string outDir, report; }

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
            int i = Array.IndexOf(args, "-fusionCrestSpec");
            if (i < 0 || i + 1 >= args.Length) throw new InvalidOperationException("-fusionCrestSpec <json> required");
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
                    if (!u.sid.StartsWith("h3_fusion_", StringComparison.Ordinal)) throw new InvalidOperationException("refusing sid " + u.sid);
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

                    foreach (AssetBundle open in AssetBundle.GetAllLoadedAssetBundles().ToArray()) open.Unload(true);
                    AssetBundle src = AssetBundle.LoadFromFile(u.sourceBundle);
                    if (src == null) throw new InvalidOperationException(u.sid + ": source bundle did not load: " + u.sourceBundle);
                    Mesh crest;
                    try { crest = ExtractCrest(u, src); }
                    finally { src.Unload(true); }
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
                Debug.Log("HOMM3_FUSION_CREST_OK " + builds.Count);
            }
            catch (Exception ex)
            {
                Debug.LogError("HOMM3_FUSION_CREST_FAILED " + ex);
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

        /// <summary>Crest vertices in Head bind-local space: Head.localToWorld * v reproduces the fused mesh's
        /// skinning (Head.localToWorld * bindpose[Head] * v) exactly, so an identity child of Head needs no bindpose.</summary>
        static Mesh ExtractCrest(UnitDef u, AssetBundle src)
        {
            GameObject prefab = src.LoadAllAssets<GameObject>().FirstOrDefault(g => g.GetComponentInChildren<SkinnedMeshRenderer>(true) != null);
            if (prefab == null) throw new InvalidOperationException(u.sid + ": source bundle has no skinned prefab");
            SkinnedMeshRenderer body = prefab.GetComponentsInChildren<SkinnedMeshRenderer>(true)
                .Where(s => !s.name.EndsWith("_Rubble", StringComparison.Ordinal)).OrderByDescending(s => s.sharedMesh.vertexCount).First();
            Mesh m = body.sharedMesh;
            string boneName = string.IsNullOrEmpty(u.attachBone) ? "Head" : u.attachBone;
            int head = Array.FindIndex(body.bones, b => b != null && b.name == boneName);
            if (head < 0) throw new InvalidOperationException(u.sid + ": body has no bone " + boneName);
            Matrix4x4 bind = m.bindposes[head];
            Vector3[] v = m.vertices, n = m.normals;
            Vector2[] uv = m.uv;
            BoneWeight[] bw = m.boneWeights;
            int k = u.crestInsertAt, c = u.crestVerts;
            if (k < 0 || k + c > v.Length) throw new InvalidOperationException(u.sid + ": crest range outside the mesh");
            var pv = new Vector3[c]; var pn = new Vector3[c]; var pu = new Vector2[c];
            for (int j = 0; j < c; j++)
            {
                int s = k + j;
                if (uv[s].x < 0.5f - 1e-4f) throw new InvalidOperationException(u.sid + ": vertex " + s + " is not on the crest half of the atlas");
                if (bw[s].boneIndex0 != head || bw[s].weight0 < 0.999f) throw new InvalidOperationException(u.sid + ": vertex " + s + " is not rigid on " + boneName);
                pv[j] = bind.MultiplyPoint3x4(v[s]);
                pn[j] = bind.MultiplyVector(n[s]).normalized;
                pu[j] = new Vector2((uv[s].x - 0.5f) * 2f, uv[s].y);
            }
            var tris = new List<int>();
            for (int sm = 0; sm < m.subMeshCount; sm++)
            {
                int[] t = m.GetTriangles(sm);
                for (int j = 0; j < t.Length; j += 3)
                {
                    bool a = t[j] >= k && t[j] < k + c, b = t[j + 1] >= k && t[j + 1] < k + c, d = t[j + 2] >= k && t[j + 2] < k + c;
                    if (a != b || b != d) throw new InvalidOperationException(u.sid + ": a triangle straddles the crest range");
                    if (a) { tris.Add(t[j] - k); tris.Add(t[j + 1] - k); tris.Add(t[j + 2] - k); }
                }
            }
            if (u.crestTris > 0 && tris.Count / 3 != u.crestTris)
                throw new InvalidOperationException(u.sid + ": " + (tris.Count / 3) + " crest triangles, build_meta says " + u.crestTris);
            var mesh = new Mesh { name = "fusion_crest" };
            mesh.vertices = pv; mesh.normals = pn; mesh.uv = pu;
            mesh.SetTriangles(tris, 0);
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
