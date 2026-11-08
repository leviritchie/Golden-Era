// Unity-editor batch preview for the Conflux 3D town prototype.
// Staged into oldenera_factions/Assets/Editor by tools/homm3_town_scene_meshes/build_conflux_town3d_preview.py
// and run via tools/homm3_vfx/unitylock.py (-executeMethod Homm3ConfluxTown3dPreview.Run).
// Renders, from the native cityHuman2 camera pose:
//   stock_cityHuman2.png        stock Olden Era city geometry through the Hex/Lit replica (+ native fog)
//   conflux3d_meshes_only.png   HoMM3 Conflux backdrop depth surface + registered Meshy meshes (3D) only
//   conflux3d_default.png       same + depth-projected 2D layers and skirts (the full construction)
//   mask_<mesh>.png             each mesh alone, white unlit on black (alignment IoU vs the sprite alpha)
//   conflux3d_<state>.png       every other town state (lower-level towns): its meshes, skirts and 2D layers
//   orbit_###.png               small lateral/dolly camera move over the full construction (parallax proof)
// Proof tier: Unity-editor render of a preview replica shader; not in-game.
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

public static class Homm3ConfluxTown3dPreview
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

    const string Lab = "Assets/Homm3TownLab";

    [Serializable] class Cam { public float[] pos; public float[] fwd; public float[] up; public float fov; }
    [Serializable] class Fog { public float[] color; public float start; public float end; }
    [Serializable] class Backdrop { public string mesh; public string texture; }
    [Serializable] class MeshEntry
    {
        public string name; public string layer; public string glb; public string baseColor; public string rawBaseColor;
        public string[] states; // town states the instance is shown in (absent = "full")
        public float[] rootPosition; public float yaw; public float scale; public float stretchY = 1f;
        public float kneeY; public float kneeScale; // kneeScale 0 = no spire surgery
    }
    [Serializable] class Projected { public string name; public string role; public string layer; public string mesh; public string texture; public string[] states; }
    [Serializable] class Rig { public string name; public float[] sunColor; public float[] ambSky; public float[] ambEq; public float[] ambGround; }
    [Serializable] class Orbit { public int frames; public float lateral; public float dolly; }
    [Serializable] class Fill { public float[] dir; public float[] color; }
    [Serializable] class Spec
    {
        public int[] frame; public Cam camera; public float[] sunDir; public float[] stockSunDir; public Fill fill; public Rig rig; public Rig[] stockRigs; public Fog fog; public Backdrop backdrop;
        public MeshEntry[] meshes; public Projected[] projected; public string stockScene; public string outDir; public Orbit orbit;
        public string[] states;
    }

    static bool InState(string[] states, string state) =>
        states == null || states.Length == 0 ? state == "full" : Array.IndexOf(states, state) >= 0;
    [Serializable] class StockMat { public string tex; public bool clip; public string name; public string shader; }
    [Serializable] class StockInst { public string path; public string mesh; public bool skinned; public float[] m; public StockMat[] mats; public bool recalcNormals; }
    [Serializable] class StockLight { public string name; public int type; public float intensity; public float[] color; public float[] m; public bool active; }
    [Serializable] class StockScene { public StockInst[] instances; public StockLight[] lights; public Fog fog; }

    static Shader _hexLit, _unlit;
    static readonly Dictionary<string, Texture2D> Tex = new Dictionary<string, Texture2D>();

    public static void Run()
    {
        try { RunInner(); }
        catch (Exception e) { Debug.LogError("HOMM3_TOWN3D_FAILED " + e); UnityQueueExit(1); }
    }

    static void RunInner()
    {
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
        var spec = JsonUtility.FromJson<Spec>(File.ReadAllText(Lab + "/data/spec.json"));
        _hexLit = Shader.Find("Hidden/Homm3TownLab/HexLit");
        _unlit = Shader.Find("Hidden/Homm3TownLab/Unlit");
        if (_hexLit == null || _unlit == null) throw new InvalidOperationException("town lab shaders missing");
        Directory.CreateDirectory(spec.outDir);
        var report = new List<string>();

        // 1. Stock cityHuman2.
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var stock = JsonUtility.FromJson<StockScene>(File.ReadAllText(Lab + "/" + spec.stockScene));
        var stockRoot = new GameObject("stock");
        int built = 0;
        foreach (var inst in stock.instances)
            if (BuildStockInstance(inst, stockRoot.transform, spec, fogOn: true)) built++;
        report.Add("stock instances built " + built + "/" + stock.instances.Length);
        Render(spec, V(spec.camera.pos), V(spec.camera.fwd), V(spec.camera.up), Path.Combine(spec.outDir, "stock_cityHuman2.png"),
            new Color(0.59f, 0.77f, 0.77f));
        if (spec.stockRigs != null)
            foreach (var sr in spec.stockRigs)
            {
                foreach (var r in stockRoot.GetComponentsInChildren<Renderer>(true))
                    foreach (var m in r.sharedMaterials) ApplyRig(m, sr);
                Render(spec, V(spec.camera.pos), V(spec.camera.fwd), V(spec.camera.up), Path.Combine(spec.outDir, "stock_cityHuman2_" + sr.name + ".png"),
                    new Color(0.59f, 0.77f, 0.77f));
            }
        UnityEngine.Object.DestroyImmediate(stockRoot);

        // 2. Conflux: backdrop surface + registered meshes, then depth-projected layers and skirts.
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var backdrop = MeshObject("conflux_backdrop", LoadBin(Lab + "/data/" + spec.backdrop.mesh), null);
        backdrop.GetComponent<MeshRenderer>().sharedMaterial = UnlitMat(LoadTex(Lab + "/data/" + spec.backdrop.texture, clamp: true), 0f);
        var meshGos = new List<(MeshEntry e, GameObject go, Material[][] mats)>();
        var rawMats = new List<Material>();
        foreach (var b in spec.meshes)
        {
            var go = LoadGlb(Lab + "/data/" + b.glb, b.name);
            var mat = HexLitMat(LoadTex(Lab + "/data/" + b.baseColor, clamp: false), spec, clip: false, fog: false);
            rawMats.Add(string.IsNullOrEmpty(b.rawBaseColor) ? mat
                : HexLitMat(LoadTex(Lab + "/data/" + b.rawBaseColor, clamp: false), spec, clip: false, fog: false));
            var rs = go.GetComponentsInChildren<Renderer>(true);
            var saved = new Material[rs.Length][];
            for (int k = 0; k < rs.Length; k++)
            {
                var mats = new Material[rs[k].sharedMaterials.Length];
                for (int i = 0; i < mats.Length; i++) mats[i] = mat;
                rs[k].sharedMaterials = mats;
                saved[k] = mats;
            }
            if (b.kneeScale > 0f && b.kneeScale < 1f) KneeRemap(go, b.kneeY, b.kneeScale);
            // Registered transform from fit_mesh_to_sprite (world = root + R * (scale * v)).
            go.transform.SetPositionAndRotation(V(b.rootPosition), Quaternion.Euler(0f, b.yaw, 0f));
            go.transform.localScale = new Vector3(b.scale, b.scale * (b.stretchY > 0f ? b.stretchY : 1f), b.scale);
            meshGos.Add((b, go, saved));
            var bounds = Bounds(go);
            report.Add($"mesh {b.name} yaw={b.yaw:0.0} scale={b.scale:0.000} bounds={bounds.size}");
        }
        var sky = new Color(0.45f, 0.55f, 0.75f);
        foreach (var m in meshGos) m.go.SetActive(InState(m.e.states, "full"));
        Render(spec, V(spec.camera.pos), V(spec.camera.fwd), V(spec.camera.up), Path.Combine(spec.outDir, "conflux3d_meshes_only.png"), sky);
        var proj = new GameObject("projected");
        var projGos = new List<(Projected p, GameObject go)>();
        foreach (var p in spec.projected)
        {
            var go = MeshObject(p.role + "_" + p.name, LoadBin(Lab + "/data/" + p.mesh), proj.transform);
            go.GetComponent<MeshRenderer>().sharedMaterial = UnlitMat(LoadTex(Lab + "/data/" + p.texture, clamp: true), 0.5f);
            go.SetActive(InState(p.states, "full"));
            projGos.Add((p, go));
        }
        report.Add("projected layers+skirts " + spec.projected.Length);
        Render(spec, V(spec.camera.pos), V(spec.camera.fwd), V(spec.camera.up), Path.Combine(spec.outDir, "conflux3d_default.png"), sky);
        // Lower-level town states, then back to the full town for the comparison renders below.
        if (spec.states != null)
            foreach (var st in spec.states)
            {
                if (st == "full") continue;
                foreach (var m in meshGos) m.go.SetActive(InState(m.e.states, st));
                foreach (var pg in projGos) pg.go.SetActive(InState(pg.p.states, st));
                Render(spec, V(spec.camera.pos), V(spec.camera.fwd), V(spec.camera.up), Path.Combine(spec.outDir, "conflux3d_" + st + ".png"), sky);
                report.Add("state " + st + " rendered");
            }
        foreach (var m in meshGos) m.go.SetActive(InState(m.e.states, "full"));
        foreach (var pg in projGos) pg.go.SetActive(InState(pg.p.states, "full"));
        // Same scene with the raw Meshy base colour (before the material pass), for comparison.
        for (int k = 0; k < meshGos.Count; k++)
            foreach (var r in meshGos[k].go.GetComponentsInChildren<Renderer>(true))
            { var w = new Material[r.sharedMaterials.Length]; for (int i = 0; i < w.Length; i++) w[i] = rawMats[k]; r.sharedMaterials = w; }
        Render(spec, V(spec.camera.pos), V(spec.camera.fwd), V(spec.camera.up), Path.Combine(spec.outDir, "conflux3d_default_raw.png"), sky);
        foreach (var m in meshGos)
        {
            var rs = m.go.GetComponentsInChildren<Renderer>(true);
            for (int k = 0; k < rs.Length; k++) rs[k].sharedMaterials = m.mats[k];
        }

        // 3. Alignment masks: each mesh alone, white unlit on black, default pose.
        var white = UnlitMat(SolidTex(Color.white), 0f);
        backdrop.SetActive(false); proj.SetActive(false);
        foreach (var m in meshGos) m.go.SetActive(false);
        foreach (var m in meshGos)
        {
            m.go.SetActive(true);
            var rs = m.go.GetComponentsInChildren<Renderer>(true);
            foreach (var r in rs) { var w = new Material[r.sharedMaterials.Length]; for (int i = 0; i < w.Length; i++) w[i] = white; r.sharedMaterials = w; }
            Render(spec, V(spec.camera.pos), V(spec.camera.fwd), V(spec.camera.up), Path.Combine(spec.outDir, "mask_" + m.e.name + ".png"), Color.black);
            for (int k = 0; k < rs.Length; k++) rs[k].sharedMaterials = m.mats[k];
            m.go.SetActive(false);
        }
        backdrop.SetActive(true); proj.SetActive(true);
        foreach (var m in meshGos) m.go.SetActive(InState(m.e.states, "full"));

        // 4. Camera move (parallax): lateral sway + dolly in, same look direction as the pilot video.
        var fwd = V(spec.camera.fwd); var up = V(spec.camera.up); var right = Vector3.Cross(up, fwd).normalized;
        for (int f = 0; f < spec.orbit.frames; f++)
        {
            float t = f / (float)(spec.orbit.frames - 1);
            var pos = V(spec.camera.pos) + right * (Mathf.Sin(t * Mathf.PI * 2f) * spec.orbit.lateral)
                      + fwd * (Mathf.Sin(t * Mathf.PI) * spec.orbit.dolly);
            var look = Quaternion.AngleAxis(Mathf.Sin(t * Mathf.PI * 2f) * -4f, Vector3.up) * fwd;
            Render(spec, pos, look, up, Path.Combine(spec.outDir, $"orbit_{f:000}.png"), sky, 960, 540);
        }
        File.WriteAllLines(Path.Combine(spec.outDir, "unity_report.txt"), report);
        Debug.Log("HOMM3_TOWN3D_DONE " + string.Join(" | ", report));
    }

    static Vector3 V(float[] a) => new Vector3(a[0], a[1], a[2]);

    // Spire surgery (fit_mesh_to_sprite.knee_remap): in the root's local frame, heights above kneeY are
    // compressed by kneeScale. Runs before the root transform is set, on per-instance mesh copies.
    static void KneeRemap(GameObject root, float kneeY, float kneeScale)
    {
        foreach (var mf in root.GetComponentsInChildren<MeshFilter>(true))
        {
            var mesh = UnityEngine.Object.Instantiate(mf.sharedMesh);
            var toRoot = root.transform.worldToLocalMatrix * mf.transform.localToWorldMatrix;
            var fromRoot = toRoot.inverse;
            var vs = mesh.vertices;
            for (int i = 0; i < vs.Length; i++)
            {
                var q = toRoot.MultiplyPoint3x4(vs[i]);
                if (q.y > kneeY) q.y = kneeY + (q.y - kneeY) * kneeScale;
                vs[i] = fromRoot.MultiplyPoint3x4(q);
            }
            mesh.vertices = vs;
            mesh.RecalculateBounds();
            mf.sharedMesh = mesh;
        }
    }

    static Bounds Bounds(GameObject go)
    {
        var rs = go.GetComponentsInChildren<Renderer>(true);
        var b = rs[0].bounds;
        foreach (var r in rs) b.Encapsulate(r.bounds);
        return b;
    }

    static GameObject LoadGlb(string path, string name)
    {
        // The GLBs sit under Assets/, so glTFast's ScriptedImporter has already imported them.
        // Instantiate the imported prefab: awaiting GltfImport.Load synchronously deadlocks in batchmode.
        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
        if (prefab == null) throw new InvalidOperationException("glTFast importer produced no GameObject for " + path);
        var go = UnityEngine.Object.Instantiate(prefab);
        go.name = name;
        return go;
    }

    static bool BuildStockInstance(StockInst inst, Transform parent, Spec spec, bool fogOn)
    {
        var mesh = LoadBin(Lab + "/stock/" + inst.mesh);
        var m = new Matrix4x4();
        for (int c = 0; c < 4; c++) for (int r = 0; r < 4; r++) m[r, c] = inst.m[c * 4 + r];
        // Bake the world matrix (handles the scene's mirrored scales exactly).
        var v = mesh.vertices; var n = mesh.normals;
        var nm = m.inverse.transpose;
        for (int i = 0; i < v.Length; i++) { v[i] = m.MultiplyPoint3x4(v[i]); n[i] = nm.MultiplyVector(n[i]).normalized; }
        mesh.vertices = v; mesh.normals = n;
        if (m.determinant < 0)
            for (int s = 0; s < mesh.subMeshCount; s++) { var tri = mesh.GetTriangles(s); Array.Reverse(tri); mesh.SetTriangles(tri, s); }
        if (inst.recalcNormals) mesh.RecalculateNormals();
        mesh.RecalculateBounds();
        var mats = new Material[mesh.subMeshCount];
        for (int s = 0; s < mats.Length; s++)
        {
            var sm = inst.mats != null && inst.mats.Length > 0 ? inst.mats[Mathf.Min(s, inst.mats.Length - 1)] : null;
            Texture2D tex = sm != null && !string.IsNullOrEmpty(sm.tex) ? LoadTex(Lab + "/stock/" + sm.tex, clamp: false) : Texture2D.grayTexture;
            if (sm != null && sm.shader == "Hex/Sea") tex = SolidTex(new Color(0.25f, 0.42f, 0.5f));
            mats[s] = HexLitMat(tex, spec, sm != null && sm.clip, fogOn);
            if (spec.stockSunDir != null && spec.stockSunDir.Length == 3)
                mats[s].SetVector("_SunDir", new Vector4(spec.stockSunDir[0], spec.stockSunDir[1], spec.stockSunDir[2], 0));
        }
        var go = MeshObject(inst.path, mesh, parent);
        go.GetComponent<MeshRenderer>().sharedMaterials = mats;
        return true;
    }

    static GameObject MeshObject(string name, Mesh mesh, Transform parent)
    {
        var go = new GameObject(name);
        if (parent != null) go.transform.SetParent(parent, false);
        go.AddComponent<MeshFilter>().sharedMesh = mesh;
        go.AddComponent<MeshRenderer>().shadowCastingMode = ShadowCastingMode.Off;
        return go;
    }

    static Material HexLitMat(Texture2D tex, Spec spec, bool clip, bool fog)
    {
        var mat = new Material(_hexLit);
        mat.SetTexture("_MainTex", tex);
        mat.SetVector("_SunDir", new Vector4(spec.sunDir[0], spec.sunDir[1], spec.sunDir[2], 0));
        ApplyRig(mat, spec.rig);
        if (spec.fill != null && spec.fill.color != null && spec.fill.color.Length == 3)
        {
            mat.SetVector("_FillDir", new Vector4(spec.fill.dir[0], spec.fill.dir[1], spec.fill.dir[2], 0));
            mat.SetVector("_FillColor", new Vector4(spec.fill.color[0], spec.fill.color[1], spec.fill.color[2], 0));
        }
        var fc = new Color(spec.fog.color[0], spec.fog.color[1], spec.fog.color[2]).linear;
        mat.SetVector("_FogColor", new Vector4(fc.r, fc.g, fc.b, 0));
        mat.SetVector("_FogRange", new Vector4(spec.fog.start, spec.fog.end, fog ? 1 : 0, 0));
        mat.SetFloat("_Clip", clip ? 1 : 0);
        return mat;
    }

    static void ApplyRig(Material mat, Rig rig)
    {
        if (rig == null || rig.sunColor == null) return;
        Vector4 V4(float[] a) => new Vector4(a[0], a[1], a[2], 0);
        mat.SetVector("_SunColor", V4(rig.sunColor));
        mat.SetVector("_AmbSky", V4(rig.ambSky)); mat.SetVector("_AmbEq", V4(rig.ambEq)); mat.SetVector("_AmbGround", V4(rig.ambGround));
    }

    static Material UnlitMat(Texture2D tex, float cutoff)
    {
        var mat = new Material(_unlit);
        mat.SetTexture("_MainTex", tex);
        mat.SetFloat("_Cutoff", cutoff);
        return mat;
    }

    static Texture2D SolidTex(Color c)
    {
        var t = new Texture2D(2, 2); t.SetPixels(new[] { c, c, c, c }); t.Apply(); return t;
    }

    static Texture2D LoadTex(string path, bool clamp)
    {
        if (Tex.TryGetValue(path, out var cached)) return cached;
        var t = new Texture2D(2, 2, TextureFormat.RGBA32, true);
        if (!t.LoadImage(File.ReadAllBytes(path))) throw new InvalidOperationException("texture load failed " + path);
        t.wrapMode = clamp ? TextureWrapMode.Clamp : TextureWrapMode.Repeat;
        t.anisoLevel = 4;
        Tex[path] = t;
        return t;
    }

    static Mesh LoadBin(string path)
    {
        using var br = new BinaryReader(File.OpenRead(path));
        int nv = br.ReadInt32(), ns = br.ReadInt32();
        var v = new Vector3[nv]; var n = new Vector3[nv]; var uv = new Vector2[nv];
        for (int i = 0; i < nv; i++) v[i] = new Vector3(br.ReadSingle(), br.ReadSingle(), br.ReadSingle());
        for (int i = 0; i < nv; i++) n[i] = new Vector3(br.ReadSingle(), br.ReadSingle(), br.ReadSingle());
        for (int i = 0; i < nv; i++) uv[i] = new Vector2(br.ReadSingle(), br.ReadSingle());
        var mesh = new Mesh { indexFormat = IndexFormat.UInt32 };
        mesh.vertices = v; mesh.normals = n; mesh.uv = uv;
        mesh.subMeshCount = ns;
        for (int s = 0; s < ns; s++)
        {
            int c = br.ReadInt32(); var idx = new int[c];
            for (int i = 0; i < c; i++) idx[i] = br.ReadInt32();
            mesh.SetTriangles(idx, s, false);
        }
        mesh.RecalculateBounds();
        return mesh;
    }

    static void Render(Spec spec, Vector3 pos, Vector3 fwd, Vector3 up, string outPath, Color clear, int w = 0, int h = 0)
    {
        w = w > 0 ? w : spec.frame[0]; h = h > 0 ? h : spec.frame[1];
        var camGo = new GameObject("PreviewCam");
        var cam = camGo.AddComponent<Camera>();
        cam.fieldOfView = spec.camera.fov; cam.nearClipPlane = 0.05f; cam.farClipPlane = 1000f;
        cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = clear;
        camGo.transform.SetPositionAndRotation(pos, Quaternion.LookRotation(fwd, up));
        var rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB) { antiAliasing = 8 };
        cam.targetTexture = rt; cam.aspect = w / (float)h;
        cam.Render();
        RenderTexture.active = rt;
        var read = new Texture2D(w, h, TextureFormat.RGB24, false);
        read.ReadPixels(new Rect(0, 0, w, h), 0, 0); read.Apply();
        RenderTexture.active = null;
        File.WriteAllBytes(outPath, read.EncodeToPNG());
        cam.targetTexture = null;
        UnityEngine.Object.DestroyImmediate(rt); UnityEngine.Object.DestroyImmediate(read); UnityEngine.Object.DestroyImmediate(camGo);
    }
}
