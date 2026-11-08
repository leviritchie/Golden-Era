// Builds the camera-registered 3D town-scene bundle (Conflux first) for the plugin lane
// Homm3TownScene3d. Driven by tools/homm3_town_scene_meshes/build_town_scene3d_bundle.py, which writes
// Assets/Homm3TownScene3d/<fraction>/build_spec.json and stages the inputs next to it.
//
// One prefab per HotA layer. The prefab root IS the reference camera frame (x right, y up, z forward,
// world units, unscaled camera axes): legacy catalogs follow the live camera; full-3D v2 catalogs seat the root
// at the authored rest pose and keep it fixed while the town camera pans. Runtime aspect/FOV scaling still applies.
// Children:
//   Mesh_<name>    registered Meshy mesh; the fitted vertical stretch and the spire knee are baked into the
//                  vertices (normals by the inverse transpose), so the piece carries only a uniform scale.
//                  Material = baked Hex/Lit albedo; the runtime rebinds it to the city's Hex/Lit donor.
//   Sprite_<name>  painted sprite pixels the mesh does not represent (skirts), as camera-projected grids.
//                  Unlit; the runtime gives them the compositor's Sprites/Default presentation material.
//   Anim_<name>    mechanical parts with an Animator loop (portal disc spin), as the stock city does it.
// Full-3D scenes (build_conflux_full3d_scene.py; optional spec fields, older specs build unchanged):
//   bins           grid meshes in the prefab frame: kind "lit" (Mesh_*, Hex/Lit after the runtime rebind),
//                  "sky" (Sky_*, unlit opaque) or "fx" (Fx_*, unlit alpha; optional Animator spin about the
//                  holder's local y with period spinPeriod, or swing about it: swingAmpDeg * sin(2 pi t /
//                  swingPeriod + swingPhaseDeg) - swingZeroDeg, the texture drawn at the swingZeroDeg pose, or keyed
//                  poses: keyPose = [x, z, deg] per key, holder units / degrees about the holder's local y, keys evenly
//                  spaced over keyPeriod, played linearly and looping back to the first).
//   scatters       one shared model-space mesh + texture, one child per instance (pos3 quat4 scale1 each), under a
//                  Mesh_* group: vegetation and rocks are stored once in the bundle.
//   bins kind "fxmesh"  Fx_* grid mesh drawn by a bone-less SkinnedMeshRenderer with its own bundle material (spec
//                  `material`: shader asset path + textures/floats/colors) and an optional second UV set (`uv2`: raw
//                  float32 pairs). The runtime re-materials only MeshRenderers, so the animated shader (river flow,
//                  lava, aurora, portal) survives.
//   bins `colors` (lit Mesh_Cloth_* only): raw float32 RGBA per vertex set as mesh.colors (COLOR.r = the Hex/Lit FLAG
//                  wave weight, town_full3d_cloth.py) and `boundsPad`: the mesh bounds grown by the wave's reach.
//   bins kind "skyshader"  Sky_* mesh on a MeshRenderer with its own bundle material (spec `material`, as fxmesh;
//                  a texture's optional `maxSize` overrides the importer's 4096): the continuous sky panorama
//                  (town_full3d_sky_continuous.py). The runtime keeps it only for the piece catalog skyLook declares.
//   particles      Fx_* groups of ParticleSystems (prewarmed, looping, play on awake, local space, hierarchy scaling)
//                  with bundle materials; the runtime does not re-material ParticleSystemRenderers.
// Generated-artifact tooling only: nothing here is loaded by the game until the plugin lane is deployed.
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;
using UnityEngine.Rendering;

public static class Homm3TownScene3dBundleBuild
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

    [Serializable] class Piece
    {
        public string name; public string glb; public string texture;
        public float[] pos; public float[] rot; public float scale;
        public float stretchY = 1f; public float kneeY; public float kneeScale; // kneeScale 0 = none
    }
    [Serializable] class SpritePiece { public string name; public string mesh; public string texture; }
    [Serializable] class Disc
    {
        public string name; public string texture; public float[] center; public float radius;
        public float periodSec; public int segments;
    }
    [Serializable] class BinPiece
    {
        public string name; public string mesh; public string texture; public string kind; public int maxSize;
        public float mipBias; public int aniso;  // optional sampler settings, serialized with the texture (0 = importer default)
        public float[] pos; public float[] rot; public float spinPeriod;
        public float swingPeriod; public float swingAmpDeg; public float swingPhaseDeg; public float swingZeroDeg;
        public float keyPeriod; public float[] keyPose;
        public MatSpec material; public string uv2;
        public string colors; public float boundsPad;   // lit cloth pieces (town_full3d_cloth.py): vertex RGBA, bounds slack
    }
    [Serializable] class TexSpec { public string prop; public string path; public float[] st; public bool clamp; public bool srgb; public int maxSize; }  // maxSize 0 = 4096
    [Serializable] class FSpec { public string name; public float value; }
    [Serializable] class CSpec { public string name; public float[] rgba; }
    [Serializable] class MatSpec { public string shader; public TexSpec[] textures; public FSpec[] floats; public CSpec[] colors; public int queue; }
    [Serializable] class PSys
    {
        public string name; public MatSpec material; public int maxParticles; public float[] lifetime; public float[] speed;
        public float[] size; public float[] sizeY; public float[] rotation; public float[] color; public float[] color2;
        public float gravity; public float rate; public string shape; public float radius; public float radiusThickness;
        public float angle; public float arc; public float[] shapePos; public float[] shapeRot; public float[] shapeScale;
        public float[] velX; public float[] velY; public float[] velZ; public float[] orbitalX; public float[] orbitalY;
        public float[] orbitalZ; public float[] radial; public float[] colorKeys; public float[] alphaKeys;
        public float[] sizeKeys; public float[] sizeYKeys; public float[] rotSpeed; public float noise; public float noiseFreq;
        public float noiseScroll; public float drag; public int renderMode; public float lengthScale; public float velocityScale;
        public float[] pivot; public float sortingFudge; public bool customUV; public float[] pos; public float[] rot; public int seed;
    }
    [Serializable] class FxGroup { public string name; public float[] pos; public float[] rot; public float scale; public PSys[] systems; }
    [Serializable] class ScatterGroup { public string name; public string mesh; public string texture; public float[] xforms; }
    [Serializable] class PrefabSpec
    {
        public string key; public string layerId; public Piece[] pieces; public SpritePiece[] sprites; public Disc[] discs;
        public BinPiece[] bins; public ScatterGroup[] scatters; public FxGroup[] particles;
    }
    [Serializable] class BuildSpec { public string bundleName; public string assetRoot; public string outputPath; public PrefabSpec[] prefabs; }

    public static void Run()
    {
        try { RunInner(); }
        catch (Exception e) { Debug.LogError("HOMM3_TOWN_SCENE3D_BUNDLE_FAILED " + e); UnityQueueExit(1); }
    }

    static string Arg(string name)
    {
        var args = UnityQueueArgs();
        for (int i = 0; i < args.Length - 1; i++) if (args[i] == name) return args[i + 1];
        throw new InvalidOperationException("missing command-line argument " + name);
    }

    static void RunInner()
    {
        var specPath = Arg("-scene3dSpec");
        PlayerSettings.colorSpace = ColorSpace.Linear; // the game renders linear (the V: project already is)
        // Bundle shaders must carry every API the game may run on (it ships a D3D12 runtime beside D3D11).
        PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.StandaloneWindows64, false);
        PlayerSettings.SetGraphicsAPIs(BuildTarget.StandaloneWindows64,
            new[] { GraphicsDeviceType.Direct3D11, GraphicsDeviceType.Direct3D12 });
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
        var spec = JsonUtility.FromJson<BuildSpec>(File.ReadAllText(specPath));
        if (spec.prefabs == null || spec.prefabs.Length == 0) throw new InvalidOperationException("spec has no prefabs");
        var gen = spec.assetRoot + "/generated";
        if (AssetDatabase.IsValidFolder(gen)) AssetDatabase.DeleteAsset(gen);
        AssetDatabase.CreateFolder(spec.assetRoot, "generated");

        var unlit = Shader.Find("Unlit/Texture") ?? throw new InvalidOperationException("Unlit/Texture missing");
        var unlitT = Shader.Find("Unlit/Transparent") ?? throw new InvalidOperationException("Unlit/Transparent missing");
        var assetNames = new List<string>();
        var report = new List<string>();
        foreach (var p in spec.prefabs)
        {
            var root = new GameObject(p.key);
            foreach (var piece in p.pieces ?? new Piece[0])
            {
                var go = BuildPiece(piece, gen, unlit);
                go.transform.SetParent(root.transform, false);
                go.transform.localPosition = V3(piece.pos);
                go.transform.localRotation = new Quaternion(piece.rot[0], piece.rot[1], piece.rot[2], piece.rot[3]);
                go.transform.localScale = Vector3.one * piece.scale;
            }
            foreach (var s in p.sprites ?? new SpritePiece[0])
            {
                var mesh = LoadBin(s.mesh);
                mesh.name = "Sprite_" + s.name;
                AssetDatabase.CreateAsset(mesh, gen + "/" + mesh.name + ".asset");
                var mat = new Material(unlitT) { name = mesh.name };
                mat.mainTexture = Tex(s.texture, clamp: true);
                AssetDatabase.CreateAsset(mat, gen + "/" + mesh.name + ".mat");
                var go = Holder(mesh.name, root.transform, mesh, mat);
            }
            foreach (var d in p.discs ?? new Disc[0])
            {
                var go = BuildDisc(d, gen, unlitT);
                go.transform.SetParent(root.transform, false);
                go.transform.localPosition = V3(d.center);
            }
            foreach (var b in p.bins ?? new BinPiece[0])
                BuildBin(b, gen, unlit, unlitT).transform.SetParent(root.transform, false);
            foreach (var sc in p.scatters ?? new ScatterGroup[0])
                BuildScatter(sc, gen, unlit).transform.SetParent(root.transform, false);
            foreach (var fg in p.particles ?? new FxGroup[0])
                BuildParticles(fg, gen).transform.SetParent(root.transform, false);
            var path = gen + "/" + p.key + ".prefab";
            PrefabUtility.SaveAsPrefabAsset(root, path);
            UnityEngine.Object.DestroyImmediate(root);
            AssetImporter.GetAtPath(path).assetBundleName = spec.bundleName;
            assetNames.Add(path);
            report.Add(p.key + " pieces=" + (p.pieces?.Length ?? 0) + " sprites=" + (p.sprites?.Length ?? 0) + " discs=" + (p.discs?.Length ?? 0)
                       + " bins=" + (p.bins?.Length ?? 0) + " scatters=" + (p.scatters?.Length ?? 0)
                       + " particles=" + (p.particles?.Length ?? 0));
        }
        AssetDatabase.SaveAssets();
        Directory.CreateDirectory(spec.outputPath);
        var build = new AssetBundleBuild { assetBundleName = spec.bundleName, assetNames = assetNames.ToArray() };
        var manifest = BuildPipeline.BuildAssetBundles(spec.outputPath, new[] { build },
            BuildAssetBundleOptions.ChunkBasedCompression | BuildAssetBundleOptions.StrictMode, BuildTarget.StandaloneWindows64);
        if (manifest == null) throw new InvalidOperationException("BuildAssetBundles returned null");
        foreach (var n in assetNames) AssetImporter.GetAtPath(n).assetBundleName = null;
        File.WriteAllLines(Path.Combine(spec.outputPath, spec.bundleName + ".build_report.txt"), report);
        Debug.Log("HOMM3_TOWN_SCENE3D_BUNDLE_DONE " + string.Join(" | ", report));
        UnityQueueExit(0);
    }

    // Readback: load the STAGED bundle, seat every prefab exactly as Homm3TownScene3d.PlaceRoot does (root at the
    // camera pose, scale (kx, ky, 1) = 1 at the reference FOV/aspect), and render each layer's Mesh_ body as a
    // white mask plus one albedo composite. build_town_scene3d_bundle.py --verify compares the masks with the
    // preview's registered masks. Editor render, not the game.
    [Serializable] class VerifyCam { public float[] pos; public float[] fwd; public float[] up; public float fov; public int w; public int h; }
    public static void Verify()
    {
        try
        {
            var bundle = AssetBundle.LoadFromFile(Arg("-scene3dBundle")) ?? throw new InvalidOperationException("bundle load failed");
            var cam = JsonUtility.FromJson<VerifyCam>(File.ReadAllText(Arg("-scene3dCam")));
            var outDir = Arg("-scene3dOut");
            Directory.CreateDirectory(outDir);
            var camGo = new GameObject("VerifyCam");
            var c = camGo.AddComponent<Camera>();
            c.transform.SetPositionAndRotation(V3(cam.pos), Quaternion.LookRotation(V3(cam.fwd), V3(cam.up)));
            c.fieldOfView = cam.fov; c.nearClipPlane = 0.05f; c.farClipPlane = 1000f;
            c.clearFlags = CameraClearFlags.SolidColor; c.backgroundColor = Color.black;
            var root = new GameObject("OfflineUnlockTownScene3D");
            root.transform.SetPositionAndRotation(c.transform.position, Quaternion.LookRotation(c.transform.forward, c.transform.up));
            root.transform.localScale = Vector3.one;
            var white = new Material(Shader.Find("Unlit/Color")) { color = Color.white };
            var insts = new List<GameObject>();
            foreach (var prefab in bundle.LoadAllAssets<GameObject>())
            {
                var inst = UnityEngine.Object.Instantiate(prefab, root.transform, false);
                inst.name = prefab.name;
                insts.Add(inst);
            }
            var report = new List<string>();
            foreach (var inst in insts) inst.SetActive(false);
            foreach (var inst in insts)
            {
                inst.SetActive(true);
                var saved = new Dictionary<Renderer, Material[]>();
                foreach (var r in inst.GetComponentsInChildren<Renderer>(true))
                {
                    saved[r] = r.sharedMaterials;
                    bool body = r.transform.parent != null && r.transform.parent.name.StartsWith("Mesh_");
                    r.enabled = body;
                    var w = new Material[r.sharedMaterials.Length];
                    for (int i = 0; i < w.Length; i++) w[i] = white;
                    r.sharedMaterials = w;
                }
                Shot(c, cam.w, cam.h, Path.Combine(outDir, "mask_" + inst.name + ".png"));
                foreach (var kv in saved) { kv.Key.sharedMaterials = kv.Value; kv.Key.enabled = true; }
                inst.SetActive(false);
                report.Add(inst.name + " renderers=" + saved.Count);
            }
            foreach (var inst in insts) inst.SetActive(true);
            c.backgroundColor = new Color(0.2f, 0.2f, 0.25f);
            Shot(c, cam.w, cam.h, Path.Combine(outDir, "albedo_composite.png"));
            File.WriteAllLines(Path.Combine(outDir, "verify_report.txt"), report);
            bundle.Unload(true);
            Debug.Log("HOMM3_TOWN_SCENE3D_VERIFY_DONE " + string.Join(" | ", report));
            UnityQueueExit(0);
        }
        catch (Exception e) { Debug.LogError("HOMM3_TOWN_SCENE3D_VERIFY_FAILED " + e); UnityQueueExit(1); }
    }

    // Grid mesh in the prefab frame (full-3D terrain / water / sky / effects).
    static GameObject BuildBin(BinPiece b, string gen, Shader unlit, Shader unlitT)
    {
        if (b.kind == "fxmesh") return BuildFxMesh(b, gen);
        if (b.kind == "skyshader") return BuildSkyShader(b, gen);
        bool fx = b.kind == "fx";
        if (!(b.kind == "lit" || b.kind == "sky" || fx)) throw new InvalidOperationException("bin kind " + b.kind);
        string want = b.kind == "lit" ? "Mesh_" : b.kind == "sky" ? "Sky_" : "Fx_";
        if (!b.name.StartsWith(want)) throw new InvalidOperationException(b.name + ": a " + b.kind + " bin must be named " + want + "*");
        var mesh = LoadBin(b.mesh);
        mesh.name = b.name;
        if (!string.IsNullOrEmpty(b.colors))
        {
            // Mesh_Cloth_* (town_full3d_cloth.py): raw float32 RGBA per vertex; COLOR.r is the Hex/Lit FLAG wave weight
            if (b.kind != "lit" || !b.name.StartsWith("Mesh_Cloth_"))
                throw new InvalidOperationException(b.name + ": vertex colors ship only on lit Mesh_Cloth_* bins");
            var raw = File.ReadAllBytes(b.colors);
            if (raw.Length != mesh.vertexCount * 16)
                throw new InvalidOperationException(b.name + ": colors has " + raw.Length / 16 + " RGBA for " + mesh.vertexCount + " vertices");
            var col = new Color[mesh.vertexCount];
            for (int i = 0; i < col.Length; i++)
                col[i] = new Color(BitConverter.ToSingle(raw, i * 16), BitConverter.ToSingle(raw, i * 16 + 4),
                                   BitConverter.ToSingle(raw, i * 16 + 8), BitConverter.ToSingle(raw, i * 16 + 12));
            mesh.colors = col;
        }
        if (b.boundsPad > 0f)
        {
            // the vertex wave moves the cloth up to boundsPad prefab units: renderer culling must not clip it
            var bb = mesh.bounds;
            bb.Expand(2f * b.boundsPad);
            mesh.bounds = bb;
        }
        AssetDatabase.CreateAsset(mesh, gen + "/" + b.name + ".asset");
        var mat = new Material(fx ? unlitT : unlit) { name = b.name };
        // Terrain, water and sky albedo are frame / dome space: clamp. Effects: clamp (alpha edges).
        mat.mainTexture = Tex(b.texture, clamp: true, maxSize: b.maxSize > 0 ? b.maxSize : 2048, mipBias: b.mipBias, aniso: b.aniso);
        AssetDatabase.CreateAsset(mat, gen + "/" + b.name + ".mat");
        var holder = new GameObject(b.name);
        if (b.pos != null && b.pos.Length == 3) holder.transform.localPosition = V3(b.pos);
        if (b.rot != null && b.rot.Length == 4) holder.transform.localRotation = new Quaternion(b.rot[0], b.rot[1], b.rot[2], b.rot[3]);
        var go = Holder(b.name + "_mesh", holder.transform, mesh, mat);
        if (b.spinPeriod > 0.1f && b.swingPeriod > 0.1f)
            throw new InvalidOperationException(b.name + ": a bin cannot both spin and swing");
        if (b.keyPeriod > 0f && (b.spinPeriod > 0.1f || b.swingPeriod > 0.1f))
            throw new InvalidOperationException(b.name + ": a bin with keyed poses cannot also spin or swing");
        if (b.spinPeriod > 0.1f)
        {
            var clip = new AnimationClip { name = b.name + "_spin", frameRate = 30f };
            void Curve(string prop, AnimationCurve c) =>
                AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Transform), prop), c);
            Curve("localEulerAnglesRaw.x", AnimationCurve.Constant(0f, b.spinPeriod, 0f));
            Curve("localEulerAnglesRaw.y", AnimationCurve.Linear(0f, 0f, b.spinPeriod, 360f));
            Curve("localEulerAnglesRaw.z", AnimationCurve.Constant(0f, b.spinPeriod, 0f));
            LoopAnimator(go, clip, b.name, gen);
        }
        else if (b.swingPeriod > 0.1f)
        {
            var clip = new AnimationClip { name = b.name + "_swing", frameRate = 30f };
            void Curve(string prop, AnimationCurve c) =>
                AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Transform), prop), c);
            const int n = 48;                       // keys per period, tangents = the sine's own slope
            var keys = new Keyframe[n + 1];
            double w = 2.0 * Math.PI / b.swingPeriod, ph = b.swingPhaseDeg * Math.PI / 180.0;
            for (int i = 0; i <= n; i++)
            {
                double t = b.swingPeriod * i / n;
                float v = (float)(b.swingAmpDeg * Math.Sin(w * t + ph) - b.swingZeroDeg);
                float d = (float)(b.swingAmpDeg * w * Math.Cos(w * t + ph));
                keys[i] = new Keyframe((float)t, v, d, d);
            }
            Curve("localEulerAnglesRaw.x", AnimationCurve.Constant(0f, b.swingPeriod, 0f));
            Curve("localEulerAnglesRaw.y", new AnimationCurve(keys));
            Curve("localEulerAnglesRaw.z", AnimationCurve.Constant(0f, b.swingPeriod, 0f));
            LoopAnimator(go, clip, b.name, gen);
        }
        else if (b.keyPeriod > 0f)
        {
            if (b.keyPeriod < 0.1f || b.keyPose == null || b.keyPose.Length < 6 || b.keyPose.Length % 3 != 0)
                throw new InvalidOperationException(b.name + ": keyed poses need keyPeriod >= 0.1 and [x, z, deg] x >= 2");
            var clip = new AnimationClip { name = b.name + "_keys", frameRate = 30f };
            void Curve(string prop, AnimationCurve c) =>
                AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Transform), prop), c);
            int n = b.keyPose.Length / 3;
            AnimationCurve Keyed(int c)
            {
                var ks = new Keyframe[n + 1];
                for (int i = 0; i <= n; i++)       // the last key repeats the first: the loop closes
                    ks[i] = new Keyframe(b.keyPeriod * i / n, b.keyPose[(i % n) * 3 + c]);
                var cv = new AnimationCurve(ks);
                for (int i = 0; i <= n; i++)
                {
                    AnimationUtility.SetKeyLeftTangentMode(cv, i, AnimationUtility.TangentMode.Linear);
                    AnimationUtility.SetKeyRightTangentMode(cv, i, AnimationUtility.TangentMode.Linear);
                }
                return cv;
            }
            Curve("localPosition.x", Keyed(0));
            Curve("localPosition.y", AnimationCurve.Constant(0f, b.keyPeriod, 0f));
            Curve("localPosition.z", Keyed(1));
            Curve("localEulerAnglesRaw.x", AnimationCurve.Constant(0f, b.keyPeriod, 0f));
            Curve("localEulerAnglesRaw.y", Keyed(2));
            Curve("localEulerAnglesRaw.z", AnimationCurve.Constant(0f, b.keyPeriod, 0f));
            LoopAnimator(go, clip, b.name, gen);
        }
        return holder;
    }

    // Looping clip on the piece's _mesh child through its own Animator controller (spin / swing / keyed poses).
    static void LoopAnimator(GameObject go, AnimationClip clip, string name, string gen)
    {
        var settings = AnimationUtility.GetAnimationClipSettings(clip);
        settings.loopTime = true;
        AnimationUtility.SetAnimationClipSettings(clip, settings);
        AssetDatabase.CreateAsset(clip, gen + "/" + clip.name + ".anim");
        var ctrl = AnimatorController.CreateAnimatorControllerAtPathWithClip(gen + "/" + name + ".controller", clip);
        var anim = go.AddComponent<Animator>();
        anim.runtimeAnimatorController = ctrl;
        anim.cullingMode = AnimatorCullingMode.AlwaysAnimate;
        anim.applyRootMotion = false;
    }

    // Fx_ mesh with its own shader, drawn by a bone-less SkinnedMeshRenderer (see header).
    static GameObject BuildFxMesh(BinPiece b, string gen)
    {
        if (!b.name.StartsWith("Fx_")) throw new InvalidOperationException(b.name + ": an fxmesh bin must be named Fx_*");
        if (b.material == null || string.IsNullOrEmpty(b.material.shader)) throw new InvalidOperationException(b.name + ": fxmesh needs a material");
        var mesh = LoadBin(b.mesh);
        mesh.name = b.name;
        if (!string.IsNullOrEmpty(b.uv2))
        {
            var raw = File.ReadAllBytes(b.uv2);
            if (raw.Length != mesh.vertexCount * 8)
                throw new InvalidOperationException(b.name + ": uv2 has " + raw.Length / 8 + " pairs for " + mesh.vertexCount + " vertices");
            var uv2 = new Vector2[mesh.vertexCount];
            for (int i = 0; i < uv2.Length; i++) uv2[i] = new Vector2(BitConverter.ToSingle(raw, i * 8), BitConverter.ToSingle(raw, i * 8 + 4));
            mesh.uv2 = uv2;
        }
        mesh.RecalculateBounds();
        AssetDatabase.CreateAsset(mesh, gen + "/" + b.name + ".asset");
        var mat = BuildMaterial(b.material, b.name, gen);
        var holder = new GameObject(b.name);
        if (b.pos != null && b.pos.Length == 3) holder.transform.localPosition = V3(b.pos);
        if (b.rot != null && b.rot.Length == 4) holder.transform.localRotation = new Quaternion(b.rot[0], b.rot[1], b.rot[2], b.rot[3]);
        var go = new GameObject(b.name + "_mesh");
        go.transform.SetParent(holder.transform, false);
        var r = go.AddComponent<SkinnedMeshRenderer>();
        r.sharedMesh = mesh;
        r.sharedMaterial = mat;
        r.localBounds = mesh.bounds;
        r.updateWhenOffscreen = false;
        r.shadowCastingMode = ShadowCastingMode.Off;
        r.receiveShadows = false;
        r.skinnedMotionVectors = false;
        return holder;
    }

    // Sky_ piece with its own shader (the continuous sky panorama, Homm3Town/SkyPanorama): a MeshRenderer whose
    // material the town runtime keeps only when catalog skyLook declares this piece and shader (fail closed otherwise).
    static GameObject BuildSkyShader(BinPiece b, string gen)
    {
        if (!b.name.StartsWith("Sky_")) throw new InvalidOperationException(b.name + ": a skyshader bin must be named Sky_*");
        if (b.material == null || string.IsNullOrEmpty(b.material.shader)) throw new InvalidOperationException(b.name + ": skyshader needs a material");
        var mesh = LoadBin(b.mesh);
        mesh.name = b.name;
        mesh.RecalculateBounds();
        AssetDatabase.CreateAsset(mesh, gen + "/" + b.name + ".asset");
        var mat = BuildMaterial(b.material, b.name, gen);
        var holder = new GameObject(b.name);
        if (b.pos != null && b.pos.Length == 3) holder.transform.localPosition = V3(b.pos);
        if (b.rot != null && b.rot.Length == 4) holder.transform.localRotation = new Quaternion(b.rot[0], b.rot[1], b.rot[2], b.rot[3]);
        var go = Holder(b.name + "_mesh", holder.transform, mesh, mat);
        var r = go.GetComponent<MeshRenderer>();
        r.shadowCastingMode = ShadowCastingMode.Off;
        r.receiveShadows = false;
        return holder;
    }

    static Material BuildMaterial(MatSpec ms, string name, string gen)
    {
        var sh = AssetDatabase.LoadAssetAtPath<Shader>(ms.shader) ?? throw new InvalidOperationException(name + ": shader " + ms.shader + " missing");
        var mat = new Material(sh) { name = name };
        foreach (var t in ms.textures ?? new TexSpec[0])
        {
            if (!mat.HasProperty(t.prop)) throw new InvalidOperationException(name + ": shader has no " + t.prop);
            mat.SetTexture(t.prop, FxTex(t.path, t.clamp, t.srgb, t.maxSize > 0 ? t.maxSize : 4096));
            if (t.st != null && t.st.Length == 4)
            {
                mat.SetTextureScale(t.prop, new Vector2(t.st[0], t.st[1]));
                mat.SetTextureOffset(t.prop, new Vector2(t.st[2], t.st[3]));
            }
        }
        foreach (var f in ms.floats ?? new FSpec[0])
        {
            if (!mat.HasProperty(f.name)) throw new InvalidOperationException(name + ": shader has no " + f.name);
            mat.SetFloat(f.name, f.value);
        }
        foreach (var c in ms.colors ?? new CSpec[0])
        {
            if (!mat.HasProperty(c.name)) throw new InvalidOperationException(name + ": shader has no " + c.name);
            mat.SetColor(c.name, new Color(c.rgba[0], c.rgba[1], c.rgba[2], c.rgba[3]));
        }
        if (ms.queue > 0) mat.renderQueue = ms.queue;
        AssetDatabase.CreateAsset(mat, gen + "/" + name + ".mat");
        return mat;
    }

    static readonly Dictionary<string, Texture2D> FxTexCache = new Dictionary<string, Texture2D>();
    static Texture2D FxTex(string path, bool clamp, bool srgb, int maxSize)
    {
        if (FxTexCache.TryGetValue(path, out var cached)) return cached;
        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
        var ti = (TextureImporter)AssetImporter.GetAtPath(path) ?? throw new InvalidOperationException("no importer " + path);
        ti.textureType = TextureImporterType.Default;
        ti.sRGBTexture = srgb;
        ti.alphaIsTransparency = false;
        ti.wrapMode = clamp ? TextureWrapMode.Clamp : TextureWrapMode.Repeat;
        ti.mipmapEnabled = true;
        ti.isReadable = false;
        ti.npotScale = TextureImporterNPOTScale.None;
        ti.maxTextureSize = maxSize;
        ti.textureCompression = TextureImporterCompression.CompressedHQ;
        ti.SaveAndReimport();
        var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(path) ?? throw new InvalidOperationException("texture load " + path);
        FxTexCache[path] = tex;
        return tex;
    }

    static ParticleSystem.MinMaxCurve MM(float[] a, float mul = 1f)
    {
        if (a == null || a.Length == 0) return new ParticleSystem.MinMaxCurve(0f);
        if (a.Length == 1) return new ParticleSystem.MinMaxCurve(a[0] * mul);
        return new ParticleSystem.MinMaxCurve(a[0] * mul, a[1] * mul);
    }
    static ParticleSystem.MinMaxCurve[] MMSame(params float[][] axes)
    {
        bool two = false;
        foreach (var a in axes) two |= a != null && a.Length >= 2;
        var r = new ParticleSystem.MinMaxCurve[axes.Length];
        for (int i = 0; i < axes.Length; i++)
        {
            var a = axes[i];
            float lo = a == null || a.Length == 0 ? 0f : a[0], hi = a != null && a.Length >= 2 ? a[1] : lo;
            r[i] = two ? new ParticleSystem.MinMaxCurve(lo, hi) : new ParticleSystem.MinMaxCurve(lo);
        }
        return r;
    }
    static AnimationCurve Keys(float[] k)
    {
        var c = new AnimationCurve();
        for (int i = 0; k != null && i + 1 < k.Length; i += 2) c.AddKey(new Keyframe(k[i], k[i + 1]));
        for (int i = 0; i < c.length; i++) c.SmoothTangents(i, 0f);
        return c;
    }
    // JsonUtility turns a missing array into an empty one, never null: "present" means non-empty.
    static bool Has(float[] a) => a != null && a.Length > 0;
    static Color Col4(float[] c) => c == null || c.Length < 4 ? Color.white : new Color(c[0], c[1], c[2], c[3]);

    // A group of ParticleSystems under one Fx_ holder (see header). Sizes and speeds are world metres: the holder
    // carries the prefab frame's depth scale and hierarchy scaling applies it to every system.
    static GameObject BuildParticles(FxGroup g, string gen)
    {
        if (!g.name.StartsWith("Fx_")) throw new InvalidOperationException(g.name + ": particle groups are Fx_*");
        if (g.systems == null || g.systems.Length == 0) throw new InvalidOperationException(g.name + ": no systems");
        var holder = new GameObject(g.name);
        holder.transform.localPosition = V3(g.pos);
        holder.transform.localRotation = g.rot != null && g.rot.Length == 4 ? new Quaternion(g.rot[0], g.rot[1], g.rot[2], g.rot[3]) : Quaternion.identity;
        holder.transform.localScale = Vector3.one * (g.scale > 0 ? g.scale : 1f);
        foreach (var d in g.systems)
        {
            var go = new GameObject(g.name + "_" + d.name);
            go.transform.SetParent(holder.transform, false);
            go.transform.localPosition = d.pos != null && d.pos.Length == 3 ? V3(d.pos) : Vector3.zero;
            go.transform.localRotation = d.rot != null && d.rot.Length == 4 ? new Quaternion(d.rot[0], d.rot[1], d.rot[2], d.rot[3]) : Quaternion.identity;
            var ps = go.AddComponent<ParticleSystem>();
            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            ps.useAutoRandomSeed = false;
            ps.randomSeed = (uint)Mathf.Max(1, d.seed);
            var main = ps.main;
            // prewarm simulates one cycle, so the cycle spans the longest lifetime: a 29 s bird or 14 s mist wisp is
            // at its steady count when the town opens (emission is a constant rate, so the cycle length changes nothing else)
            float maxLife = d.lifetime == null || d.lifetime.Length == 0 ? 0f : Mathf.Max(d.lifetime);
            main.duration = Mathf.Max(5f, maxLife); main.loop = true; main.prewarm = true; main.playOnAwake = true;
            main.simulationSpace = ParticleSystemSimulationSpace.Local;
            main.scalingMode = ParticleSystemScalingMode.Hierarchy;
            main.startLifetime = MM(d.lifetime); main.startSpeed = MM(d.speed);
            if (Has(d.sizeY))
            {
                main.startSize3D = true; main.startSizeX = MM(d.size); main.startSizeY = MM(d.sizeY); main.startSizeZ = MM(d.size);
            }
            else main.startSize = MM(d.size);
            main.startRotation = MM(d.rotation, Mathf.Deg2Rad);
            main.startColor = Has(d.color2)
                ? new ParticleSystem.MinMaxGradient(Col4(d.color), Col4(d.color2)) : new ParticleSystem.MinMaxGradient(Col4(d.color));
            main.gravityModifier = d.gravity;
            main.maxParticles = Mathf.Max(1, d.maxParticles);
            var em = ps.emission; em.enabled = true; em.rateOverTime = d.rate;
            var sh = ps.shape; sh.enabled = true;
            switch (d.shape)
            {
                case "cone": sh.shapeType = ParticleSystemShapeType.Cone; break;
                case "sphere": sh.shapeType = ParticleSystemShapeType.Sphere; break;
                case "hemisphere": sh.shapeType = ParticleSystemShapeType.Hemisphere; break;
                case "circle": sh.shapeType = ParticleSystemShapeType.Circle; break;
                case "box": sh.shapeType = ParticleSystemShapeType.Box; break;
                default: throw new InvalidOperationException(g.name + "/" + d.name + ": shape " + d.shape);
            }
            sh.radius = Mathf.Max(0.0001f, d.radius); sh.radiusThickness = d.radiusThickness; sh.angle = d.angle;
            sh.arc = d.arc > 0 ? d.arc : 360f;
            sh.position = d.shapePos != null && d.shapePos.Length == 3 ? V3(d.shapePos) : Vector3.zero;
            sh.rotation = d.shapeRot != null && d.shapeRot.Length == 3 ? V3(d.shapeRot) : Vector3.zero;
            sh.scale = d.shapeScale != null && d.shapeScale.Length == 3 ? V3(d.shapeScale) : Vector3.one;
            bool anyVel = Has(d.velX) || Has(d.velY) || Has(d.velZ) || Has(d.orbitalX) || Has(d.orbitalY) || Has(d.orbitalZ) || Has(d.radial);
            var vel = ps.velocityOverLifetime; vel.enabled = anyVel;
            if (anyVel)
            {
                vel.space = ParticleSystemSimulationSpace.Local;
                // Unity refuses to simulate (and logs per frame) velocity / orbital curves in mixed modes: a group
                // that randomises one axis gets every axis of that set as a two-constant range
                var v3 = MMSame(d.velX, d.velY, d.velZ);
                vel.x = v3[0]; vel.y = v3[1]; vel.z = v3[2];
                var o4 = MMSame(d.orbitalX, d.orbitalY, d.orbitalZ, d.radial);
                vel.orbitalX = o4[0]; vel.orbitalY = o4[1]; vel.orbitalZ = o4[2]; vel.radial = o4[3];
            }
            if (d.drag > 0)
            {
                var lim = ps.limitVelocityOverLifetime; lim.enabled = true; lim.limit = 1000f; lim.drag = d.drag;
            }
            if (Has(d.colorKeys) || Has(d.alphaKeys))
            {
                var gr = new Gradient();
                var ck = new List<GradientColorKey>(); var ak = new List<GradientAlphaKey>();
                for (int i = 0; d.colorKeys != null && i + 3 < d.colorKeys.Length; i += 4)
                    ck.Add(new GradientColorKey(new Color(d.colorKeys[i + 1], d.colorKeys[i + 2], d.colorKeys[i + 3]), d.colorKeys[i]));
                for (int i = 0; d.alphaKeys != null && i + 1 < d.alphaKeys.Length; i += 2) ak.Add(new GradientAlphaKey(d.alphaKeys[i + 1], d.alphaKeys[i]));
                if (ck.Count == 0) ck.Add(new GradientColorKey(Color.white, 0));
                if (ak.Count == 0) ak.Add(new GradientAlphaKey(1, 0));
                gr.SetKeys(ck.ToArray(), ak.ToArray());
                var col = ps.colorOverLifetime; col.enabled = true; col.color = new ParticleSystem.MinMaxGradient(gr);
            }
            if (Has(d.sizeKeys))
            {
                var so = ps.sizeOverLifetime; so.enabled = true;
                if (Has(d.sizeYKeys))
                {
                    so.separateAxes = true;
                    so.x = new ParticleSystem.MinMaxCurve(1f, Keys(d.sizeKeys));
                    so.y = new ParticleSystem.MinMaxCurve(1f, Keys(d.sizeYKeys));
                    so.z = new ParticleSystem.MinMaxCurve(1f, Keys(d.sizeKeys));
                }
                else so.size = new ParticleSystem.MinMaxCurve(1f, Keys(d.sizeKeys));
            }
            if (Has(d.rotSpeed))
            {
                var ro = ps.rotationOverLifetime; ro.enabled = true; ro.z = MM(d.rotSpeed, Mathf.Deg2Rad);
            }
            if (d.noise > 0)
            {
                var no = ps.noise; no.enabled = true; no.strength = d.noise; no.frequency = d.noiseFreq > 0 ? d.noiseFreq : 0.5f;
                no.scrollSpeed = d.noiseScroll; no.damping = true; no.quality = ParticleSystemNoiseQuality.Medium;
            }
            if (d.customUV)
            {
                var cd = ps.customData; cd.enabled = true;
                cd.SetMode(ParticleSystemCustomData.Custom1, ParticleSystemCustomDataMode.Vector);
                cd.SetVectorComponentCount(ParticleSystemCustomData.Custom1, 4);
                for (int i = 0; i < 4; i++) cd.SetVector(ParticleSystemCustomData.Custom1, i, new ParticleSystem.MinMaxCurve(0f, 1f));
            }
            var r = go.GetComponent<ParticleSystemRenderer>();
            r.renderMode = d.renderMode == 1 ? ParticleSystemRenderMode.Stretch : ParticleSystemRenderMode.Billboard;
            r.lengthScale = d.lengthScale > 0 ? d.lengthScale : 1f; r.velocityScale = d.velocityScale;
            r.pivot = d.pivot != null && d.pivot.Length == 3 ? V3(d.pivot) : Vector3.zero;
            r.sortingFudge = d.sortingFudge;
            r.sortMode = ParticleSystemSortMode.Distance;
            r.maxParticleSize = 5f;
            r.alignment = ParticleSystemRenderSpace.View;
            r.shadowCastingMode = ShadowCastingMode.Off; r.receiveShadows = false;
            r.sharedMaterial = BuildMaterial(d.material, g.name + "_" + d.name, gen);
            r.SetActiveVertexStreams(new List<ParticleSystemVertexStream> {
                ParticleSystemVertexStream.Position, ParticleSystemVertexStream.Color, ParticleSystemVertexStream.UV,
                ParticleSystemVertexStream.UV2, ParticleSystemVertexStream.Custom1XYZW, ParticleSystemVertexStream.Custom2XYZW });
        }
        return holder;
    }

    // Shared model-space mesh, one child per instance.
    static GameObject BuildScatter(ScatterGroup sc, string gen, Shader unlit)
    {
        if (!sc.name.StartsWith("Mesh_")) throw new InvalidOperationException(sc.name + ": scatter groups are Mesh_* (lit)");
        if (sc.xforms == null || sc.xforms.Length == 0 || sc.xforms.Length % 8 != 0)
            throw new InvalidOperationException(sc.name + ": xforms must be 8 floats per instance");
        var meshPath = gen + "/" + Path.GetFileNameWithoutExtension(sc.mesh) + ".asset";
        var mesh = AssetDatabase.LoadAssetAtPath<Mesh>(meshPath);
        if (mesh == null)
        {
            mesh = LoadBin(sc.mesh);
            mesh.name = Path.GetFileNameWithoutExtension(sc.mesh);
            AssetDatabase.CreateAsset(mesh, meshPath);
        }
        var matPath = gen + "/" + Path.GetFileNameWithoutExtension(sc.texture) + ".mat";
        var mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
        if (mat == null)
        {
            mat = new Material(unlit) { name = Path.GetFileNameWithoutExtension(sc.texture) };
            mat.mainTexture = Tex(sc.texture, clamp: false, maxSize: 1024);
            AssetDatabase.CreateAsset(mat, matPath);
        }
        var group = new GameObject(sc.name);
        var x = sc.xforms;
        for (int i = 0; i < x.Length / 8; i++)
        {
            int o = i * 8;
            var go = Holder(sc.name + "_" + i.ToString("000"), group.transform, mesh, mat);
            go.transform.localPosition = new Vector3(x[o], x[o + 1], x[o + 2]);
            go.transform.localRotation = new Quaternion(x[o + 3], x[o + 4], x[o + 5], x[o + 6]);
            go.transform.localScale = Vector3.one * x[o + 7];
        }
        return group;
    }

    // Offline state renders of a BUILT bundle, seated as the runtime seats it (root = camera pose, scale 1 at the
    // reference FOV/aspect). Every renderer under a Mesh_* child of a prefab gets the Hex/Lit replica
    // (Hidden/Homm3TownLab/HexLit) with its own albedo, the catalog key + fill light and the city trilight; Sky_
    // and Fx_ keep their bundle materials (unlit). Background is magenta so any hole in the scene shows.
    // Editor render, not the game.
    [Serializable] class RigSpec { public float[] sunColor; public float[] ambSky; public float[] ambEq; public float[] ambGround; }
    [Serializable] class FillSpec { public float[] dir; public float[] color; }
    [Serializable] class StateSpec { public string name; public string[] prefabs; public bool timed; }
    [Serializable] class SwaySpec { public float lateral; public int frames; }
    // Phase 5: extra renders of named states at a display resolution (the user plays at 4096x2160; 3840x2160 keeps
    // the reference 16:9), written full3d_<state>_<suffix>.png, plus the sway frames at that size when sway is set.
    [Serializable] class HiresSpec { public int w; public int h; public string suffix; public string[] states; public bool sway; }
    // Phase 6: selected default/cursor/sweep poses in the fixed rest-root frame, including the runtime aspect scale.
    [Serializable] class PanPoseSpec { public string name; public string state; public float[] pos; public float[] fwd; public float[] up; public int w; public int h; public float scaleX; public float scaleY; }
    // Cloth (town_full3d_cloth.py): each Mesh_Cloth_* piece's Hex/Lit FLAG wave in the PREFAB frame; converted to world
    // space before every shot exactly as the runtime does (power by localToWorld, direction by its inverse transpose),
    // and `seqs`: frame sequences of one state at the rest pose or a named pan pose over `times` (s).
    [Serializable] class ClothPieceSpec { public string prefab; public string piece; public float[] power; public float[] direction; public float speed; }
    [Serializable] class ClothSeqSpec { public string name; public string state; public string pose; public float[] times; }
    [Serializable] class ClothSpec { public ClothPieceSpec[] pieces; public ClothSeqSpec[] seqs; }
    [Serializable] class RenderSpec
    {
        public VerifyCam cam; public float[] sunDir; public RigSpec rig; public FillSpec fill; public StateSpec[] states;
        public SwaySpec sway; public string outDir; public float[] timeFrames; public HiresSpec hires; public PanPoseSpec[] panPoses;
        public ClothSpec cloth;
    }
    static Action BeforeShot;   // RenderStates: re-derives the cloth's world-space wave vectors for the current root pose

    // Deterministic effect time for editor renders: particle systems are simulated to PrewarmS + t (fixed seeds), and
    // every material with _TimeOffset gets t with _TimeScale 0 (the batch editor's _Time is wall clock). The game never
    // touches these properties (defaults _TimeScale 1, _TimeOffset 0) and plays particles live.
    const float PrewarmS = 6f;
    static void SetFxTime(IEnumerable<GameObject> roots, float t)
    {
        Shader.SetGlobalFloat("_LabTime", t);
        foreach (var root in roots)
        {
            if (!root.activeSelf) continue;
            foreach (var ps in root.GetComponentsInChildren<ParticleSystem>(false))
                ps.Simulate(Mathf.Max(PrewarmS, ps.main.duration + 1f) + t, false, true, false);
            foreach (var r in root.GetComponentsInChildren<Renderer>(false))
                foreach (var m in r.sharedMaterials)
                {
                    if (m == null || !m.HasProperty("_TimeOffset")) continue;
                    m.SetFloat("_TimeOffset", t);
                    if (m.HasProperty("_TimeScale")) m.SetFloat("_TimeScale", 0f);
                }
        }
    }
    public static void RenderStates()
    {
        try
        {
            PlayerSettings.colorSpace = ColorSpace.Linear;
            var spec = JsonUtility.FromJson<RenderSpec>(File.ReadAllText(Arg("-scene3dRender")));
            var bundle = AssetBundle.LoadFromFile(Arg("-scene3dBundle")) ?? throw new InvalidOperationException("bundle load failed");
            var hex = Shader.Find("Hidden/Homm3TownLab/HexLit") ?? throw new InvalidOperationException("HexLit replica shader missing");
            Directory.CreateDirectory(spec.outDir);
            var camGo = new GameObject("RenderCam");
            var c = camGo.AddComponent<Camera>();
            var basePos = V3(spec.cam.pos); var fwd = V3(spec.cam.fwd); var up = V3(spec.cam.up);
            c.transform.SetPositionAndRotation(basePos, Quaternion.LookRotation(fwd, up));
            c.fieldOfView = spec.cam.fov; c.nearClipPlane = 0.05f; c.farClipPlane = 1000f;
            c.clearFlags = CameraClearFlags.SolidColor; c.backgroundColor = Color.magenta;
            var root = new GameObject("OfflineUnlockTownScene3D");
            root.transform.SetPositionAndRotation(basePos, Quaternion.LookRotation(fwd, up));
            var byKey = new Dictionary<string, GameObject>();
            var report = new List<string>();
            Vector4 V4(float[] a) => new Vector4(a[0], a[1], a[2], 0);
            var clothSpec = new Dictionary<string, ClothPieceSpec>();
            if (spec.cloth != null && spec.cloth.pieces != null)
                foreach (var cp in spec.cloth.pieces) clothSpec[cp.prefab + "/" + cp.piece] = cp;
            var clothMats = new List<(Renderer r, Material m, ClothPieceSpec cp)>();
            foreach (var prefab in bundle.LoadAllAssets<GameObject>())
            {
                var inst = UnityEngine.Object.Instantiate(prefab, root.transform, false);
                inst.name = prefab.name;
                int lit = 0, other = 0;
                foreach (Transform child in inst.transform)
                {
                    bool isMesh = child.name.StartsWith("Mesh_");
                    foreach (var r in child.GetComponentsInChildren<Renderer>(true))
                    {
                        if (!isMesh) { other++; continue; }
                        var mats = r.sharedMaterials;
                        for (int i = 0; i < mats.Length; i++)
                        {
                            var m = new Material(hex);
                            m.SetTexture("_MainTex", mats[i].mainTexture);
                            m.SetVector("_SunDir", V4(spec.sunDir));
                            m.SetVector("_SunColor", V4(spec.rig.sunColor));
                            m.SetVector("_AmbSky", V4(spec.rig.ambSky)); m.SetVector("_AmbEq", V4(spec.rig.ambEq));
                            m.SetVector("_AmbGround", V4(spec.rig.ambGround));
                            m.SetVector("_FillDir", V4(spec.fill.dir)); m.SetVector("_FillColor", V4(spec.fill.color));
                            m.SetVector("_FogRange", new Vector4(0, 1, 0, 0));
                            m.SetFloat("_Clip", 0);
                            if (clothSpec.TryGetValue(prefab.name + "/" + child.name, out var cps))
                            {
                                m.SetFloat("_UseFlag", 1f); m.SetFloat("_FlagSpeed", cps.speed);
                                clothMats.Add((r, m, cps));
                            }
                            else if (child.name.StartsWith("Mesh_Cloth_"))
                                throw new InvalidOperationException(prefab.name + "/" + child.name + ": cloth piece missing from the render spec");
                            mats[i] = m;
                        }
                        r.sharedMaterials = mats;
                        lit++;
                    }
                }
                byKey[prefab.name] = inst;
                report.Add(prefab.name + " lit=" + lit + " unlit=" + other);
            }
            if (clothSpec.Count != clothMats.Count)
                throw new InvalidOperationException("render spec names " + clothSpec.Count + " cloth pieces, bundle has " + clothMats.Count);
            BeforeShot = () =>
            {
                foreach (var (r, m, cp) in clothMats)
                {
                    var tr = r.transform;
                    var pw = tr.TransformVector(V3(cp.power));
                    var dw = tr.worldToLocalMatrix.transpose.MultiplyVector(V3(cp.direction));
                    m.SetVector("_FlagPower", new Vector4(pw.x, pw.y, pw.z, 0));
                    m.SetVector("_FlagDirection", new Vector4(dw.x, dw.y, dw.z, 0));
                }
            };
            if (clothMats.Count > 0) report.Add("cloth pieces=" + clothMats.Count);
            // Opt-in SSR water (Homm3Town/SsrWater): the shader reads _CameraDepthTexture and _CameraColorTexture. In the
            // editor's built-in renderer the camera makes the depth texture only on request (the lab HexLit's
            // ShadowCaster pass fills it) and nothing names an opaque colour copy, so one is blitted before the
            // transparents. Scenes without an SSR material render exactly as before.
            bool ssr = false;
            foreach (var inst in byKey.Values)
                foreach (var r in inst.GetComponentsInChildren<Renderer>(true))
                    foreach (var m in r.sharedMaterials)
                        if (m != null && m.shader != null && m.shader.name == "Homm3Town/SsrWater") ssr = true;
            if (ssr)
            {
                c.depthTextureMode |= DepthTextureMode.Depth;
                var cb = new CommandBuffer { name = "Homm3TownSsrColorCopy" };
                int colorId = Shader.PropertyToID("_CameraColorTexture");
                cb.GetTemporaryRT(colorId, -1, -1, 0, FilterMode.Bilinear, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
                cb.Blit(BuiltinRenderTextureType.CurrentActive, colorId);
                cb.SetGlobalTexture("_CameraColorTexture", colorId);
                c.AddCommandBuffer(CameraEvent.BeforeForwardAlpha, cb);
                report.Add("ssr water: depthTextureMode=" + c.depthTextureMode + " colour copy at BeforeForwardAlpha");
            }
            foreach (var st in spec.states)
            {
                foreach (var k in st.prefabs)
                    if (!byKey.ContainsKey(k)) throw new InvalidOperationException("state " + st.name + ": prefab " + k + " not in bundle");
                foreach (var kv in byKey) kv.Value.SetActive(Array.IndexOf(st.prefabs, kv.Key) >= 0);
                c.transform.SetPositionAndRotation(basePos, Quaternion.LookRotation(fwd, up));
                SetFxTime(byKey.Values, 0f);
                ShotAA(c, spec.cam.w, spec.cam.h, Path.Combine(spec.outDir, "full3d_" + st.name + ".png"));
                if (st.timed && spec.timeFrames != null)
                    for (int f = 0; f < spec.timeFrames.Length; f++)
                    {
                        SetFxTime(byKey.Values, spec.timeFrames[f]);
                        ShotAA(c, spec.cam.w, spec.cam.h, Path.Combine(spec.outDir, "full3d_" + st.name + "_t" + f + ".png"));
                    }
                SetFxTime(byKey.Values, 0f);
                if (st.name == "full" && spec.sway != null && spec.sway.frames > 1)
                {
                    var right = Vector3.Cross(up, fwd).normalized;
                    for (int f = 0; f < spec.sway.frames; f++)
                    {
                        float t = f / (float)(spec.sway.frames - 1) * 2f - 1f;
                        c.transform.SetPositionAndRotation(basePos + right * (t * spec.sway.lateral),
                            Quaternion.AngleAxis(-t * 3f, Vector3.up) * Quaternion.LookRotation(fwd, up));
                        ShotAA(c, spec.cam.w, spec.cam.h, Path.Combine(spec.outDir, "full3d_full_sway_" + f + ".png"));
                        if (spec.hires != null && spec.hires.w > 0 && spec.hires.sway)
                            ShotAA(c, spec.hires.w, spec.hires.h, Path.Combine(spec.outDir, "full3d_full_sway_" + f + "_" + spec.hires.suffix + ".png"));
                    }
                    c.transform.SetPositionAndRotation(basePos, Quaternion.LookRotation(fwd, up));
                }
                if (spec.hires != null && spec.hires.w > 0 && spec.hires.states != null && Array.IndexOf(spec.hires.states, st.name) >= 0)
                    ShotAA(c, spec.hires.w, spec.hires.h, Path.Combine(spec.outDir, "full3d_" + st.name + "_" + spec.hires.suffix + ".png"));
                report.Add("state " + st.name + " prefabs=" + st.prefabs.Length);
            }
            if (spec.panPoses != null)
                foreach (var pp in spec.panPoses)
                {
                    var st = Array.Find(spec.states, x => x.name == pp.state) ?? throw new InvalidOperationException("pan pose " + pp.name + ": no state " + pp.state);
                    if (pp.scaleX <= 0f || pp.scaleY <= 0f) throw new InvalidOperationException("pan pose " + pp.name + ": invalid root scale");
                    foreach (var kv in byKey) kv.Value.SetActive(Array.IndexOf(st.prefabs, kv.Key) >= 0);
                    SetFxTime(byKey.Values, 0f);
                    root.transform.localScale = new Vector3(pp.scaleX, pp.scaleY, 1f);
                    c.transform.SetPositionAndRotation(root.transform.position + root.transform.rotation * V3(pp.pos),  // camera offset: world metres, not root-scaled
                        Quaternion.LookRotation(root.transform.TransformDirection(V3(pp.fwd)), root.transform.TransformDirection(V3(pp.up))));
                    ShotAA(c, pp.w, pp.h, Path.Combine(spec.outDir, "pan_" + pp.name + ".png"));
                    report.Add("pan " + pp.name + " state=" + pp.state);
                }
            root.transform.localScale = Vector3.one;
            if (spec.cloth != null && spec.cloth.seqs != null)
                foreach (var sq in spec.cloth.seqs)
                {
                    var st = Array.Find(spec.states, x => x.name == sq.state) ?? throw new InvalidOperationException("cloth seq " + sq.name + ": no state " + sq.state);
                    foreach (var kv in byKey) kv.Value.SetActive(Array.IndexOf(st.prefabs, kv.Key) >= 0);
                    int w = spec.cam.w, h = spec.cam.h;
                    if (string.IsNullOrEmpty(sq.pose))
                    {
                        root.transform.localScale = Vector3.one;
                        c.transform.SetPositionAndRotation(basePos, Quaternion.LookRotation(fwd, up));
                    }
                    else
                    {
                        var pp = Array.Find(spec.panPoses ?? new PanPoseSpec[0], x => x.name == sq.pose) ?? throw new InvalidOperationException("cloth seq " + sq.name + ": no pan pose " + sq.pose);
                        root.transform.localScale = new Vector3(pp.scaleX, pp.scaleY, 1f);
                        c.transform.SetPositionAndRotation(root.transform.position + root.transform.rotation * V3(pp.pos),
                            Quaternion.LookRotation(root.transform.TransformDirection(V3(pp.fwd)), root.transform.TransformDirection(V3(pp.up))));
                        w = pp.w; h = pp.h;
                    }
                    for (int f = 0; f < sq.times.Length; f++)
                    {
                        SetFxTime(byKey.Values, sq.times[f]);
                        ShotAA(c, w, h, Path.Combine(spec.outDir, "cloth_" + sq.name + "_" + f.ToString("00") + ".png"));
                    }
                    SetFxTime(byKey.Values, 0f);
                    report.Add("cloth seq " + sq.name + " frames=" + sq.times.Length);
                }
            root.transform.localScale = Vector3.one;
            BeforeShot = null;
            c.transform.SetPositionAndRotation(basePos, Quaternion.LookRotation(fwd, up));
            File.WriteAllLines(Path.Combine(spec.outDir, "render_report.txt"), report);
            bundle.Unload(true);
            Debug.Log("HOMM3_TOWN_SCENE3D_RENDER_DONE " + string.Join(" | ", report));
            UnityQueueExit(0);
        }
        catch (Exception e) { Debug.LogError("HOMM3_TOWN_SCENE3D_RENDER_FAILED " + e); UnityQueueExit(1); }
    }

    static void ShotAA(Camera c, int w, int h, string path)
    {
        BeforeShot?.Invoke();
        var rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB) { antiAliasing = 8 };
        c.targetTexture = rt; c.aspect = w / (float)h;
        c.Render();
        RenderTexture.active = rt;
        var tex = new Texture2D(w, h, TextureFormat.RGB24, false);
        tex.ReadPixels(new Rect(0, 0, w, h), 0, 0); tex.Apply();
        File.WriteAllBytes(path, tex.EncodeToPNG());
        RenderTexture.active = null; c.targetTexture = null;
        UnityEngine.Object.DestroyImmediate(rt); UnityEngine.Object.DestroyImmediate(tex);
    }

    static void Shot(Camera c, int w, int h, string path)
    {
        var rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32) { antiAliasing = 1 };
        c.targetTexture = rt; c.aspect = w / (float)h;
        c.Render();
        RenderTexture.active = rt;
        var tex = new Texture2D(w, h, TextureFormat.RGB24, false);
        tex.ReadPixels(new Rect(0, 0, w, h), 0, 0); tex.Apply();
        File.WriteAllBytes(path, tex.EncodeToPNG());
        RenderTexture.active = null; c.targetTexture = null;
        UnityEngine.Object.DestroyImmediate(rt); UnityEngine.Object.DestroyImmediate(tex);
    }

    static Vector3 V3(float[] a) => new Vector3(a[0], a[1], a[2]);

    static GameObject Holder(string name, Transform parent, Mesh mesh, Material mat)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        go.AddComponent<MeshFilter>().sharedMesh = mesh;
        var r = go.AddComponent<MeshRenderer>();
        r.sharedMaterial = mat;
        r.shadowCastingMode = ShadowCastingMode.Off;
        r.receiveShadows = false;
        return go;
    }

    // Registered Meshy mesh with the fit's vertical stretch and spire knee baked into the vertices, in the
    // glTF root's frame, exactly as the preview applies them (preview: KneeRemap in root space, then
    // localScale (s, s*k, s)). Normals follow the inverse transpose of each deformation.
    static GameObject BuildPiece(Piece piece, string gen, Shader unlit)
    {
        AssetDatabase.ImportAsset(piece.glb, ImportAssetOptions.ForceSynchronousImport);
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(piece.glb)
                     ?? throw new InvalidOperationException("glTFast produced no GameObject for " + piece.glb);
        var src = UnityEngine.Object.Instantiate(prefab);
        var go = new GameObject("Mesh_" + piece.name);
        var mat = new Material(unlit) { name = "Mesh_" + piece.name };
        mat.mainTexture = Tex(piece.texture, clamp: false, maxSize: 1024);
        AssetDatabase.CreateAsset(mat, gen + "/Mesh_" + piece.name + ".mat");
        float k = piece.stretchY > 0f ? piece.stretchY : 1f;
        bool knee = piece.kneeScale > 0f && piece.kneeScale < 1f;
        int part = 0;
        foreach (var mf in src.GetComponentsInChildren<MeshFilter>(true))
        {
            var toRoot = src.transform.worldToLocalMatrix * mf.transform.localToWorldMatrix;
            var m = mf.sharedMesh;
            var vs = m.vertices; var ns = m.normals;
            for (int i = 0; i < vs.Length; i++)
            {
                var q = toRoot.MultiplyPoint3x4(vs[i]);
                var n = ns.Length == vs.Length ? toRoot.inverse.transpose.MultiplyVector(ns[i]) : Vector3.up;
                if (knee && q.y > piece.kneeY)
                {
                    q.y = piece.kneeY + (q.y - piece.kneeY) * piece.kneeScale;
                    n.y /= piece.kneeScale;
                }
                q.y *= k;
                n.y /= k;
                vs[i] = q;
                if (ns.Length == vs.Length) ns[i] = n.normalized;
            }
            var baked = new Mesh { indexFormat = m.indexFormat, name = "Mesh_" + piece.name + "_" + part };
            baked.vertices = vs;
            if (ns.Length == vs.Length) baked.normals = ns;
            baked.uv = m.uv;
            baked.subMeshCount = m.subMeshCount;
            for (int s = 0; s < m.subMeshCount; s++) baked.SetTriangles(m.GetTriangles(s), s, false);
            baked.RecalculateBounds();
            AssetDatabase.CreateAsset(baked, gen + "/" + baked.name + ".asset");
            var mats = new Material[Mathf.Max(1, m.subMeshCount)];
            for (int s = 0; s < mats.Length; s++) mats[s] = mat;
            var h = Holder(baked.name, go.transform, baked, mat);
            h.GetComponent<MeshRenderer>().sharedMaterials = mats;
            part++;
        }
        UnityEngine.Object.DestroyImmediate(src);
        if (part == 0) throw new InvalidOperationException("no MeshFilter in " + piece.glb);
        return go;
    }

    // Camera-facing disc (local XY plane) textured with the painted portal surface, spun about its own
    // axis by an Animator loop.
    static GameObject BuildDisc(Disc d, string gen, Shader unlitT)
    {
        int seg = Mathf.Max(12, d.segments);
        var v = new Vector3[seg + 1]; var uv = new Vector2[seg + 1]; var n = new Vector3[seg + 1];
        var tris = new int[seg * 3];
        v[0] = Vector3.zero; uv[0] = new Vector2(0.5f, 0.5f); n[0] = Vector3.back;
        for (int i = 0; i < seg; i++)
        {
            float a = i * Mathf.PI * 2f / seg;
            v[i + 1] = new Vector3(Mathf.Cos(a), Mathf.Sin(a), 0f) * d.radius;
            uv[i + 1] = new Vector2(0.5f + 0.5f * Mathf.Cos(a), 0.5f + 0.5f * Mathf.Sin(a));
            n[i + 1] = Vector3.back;
            tris[i * 3] = 0; tris[i * 3 + 1] = 1 + (i + 1) % seg; tris[i * 3 + 2] = 1 + i; // front faces the camera (-z)
        }
        var mesh = new Mesh { name = "Anim_" + d.name, vertices = v, uv = uv, normals = n, triangles = tris };
        mesh.RecalculateBounds();
        AssetDatabase.CreateAsset(mesh, gen + "/" + mesh.name + ".asset");
        var mat = new Material(unlitT) { name = mesh.name, mainTexture = Tex(d.texture, clamp: true) };
        AssetDatabase.CreateAsset(mat, gen + "/" + mesh.name + ".mat");
        var go = new GameObject(mesh.name);
        go.AddComponent<MeshFilter>().sharedMesh = mesh;
        var r = go.AddComponent<MeshRenderer>();
        r.sharedMaterial = mat; r.shadowCastingMode = ShadowCastingMode.Off; r.receiveShadows = false;

        var clip = new AnimationClip { name = mesh.name + "_spin", frameRate = 30f };
        float period = d.periodSec > 0.1f ? d.periodSec : 12f;
        void Curve(string prop, AnimationCurve c) =>
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Transform), prop), c);
        Curve("localEulerAnglesRaw.x", AnimationCurve.Constant(0f, period, 0f));
        Curve("localEulerAnglesRaw.y", AnimationCurve.Constant(0f, period, 0f));
        Curve("localEulerAnglesRaw.z", AnimationCurve.Linear(0f, 0f, period, -360f));
        var settings = AnimationUtility.GetAnimationClipSettings(clip);
        settings.loopTime = true;
        AnimationUtility.SetAnimationClipSettings(clip, settings);
        AssetDatabase.CreateAsset(clip, gen + "/" + clip.name + ".anim");
        var ctrl = AnimatorController.CreateAnimatorControllerAtPathWithClip(gen + "/" + mesh.name + ".controller", clip);
        var anim = go.AddComponent<Animator>();
        anim.runtimeAnimatorController = ctrl;
        anim.cullingMode = AnimatorCullingMode.AlwaysAnimate;
        anim.applyRootMotion = false;
        return go;
    }

    // Buildings span at most ~300 px of a 1080p town screen: 1024 texels keep >3x oversampling.
    // mipBias / aniso travel with the Texture2D asset into the bundle, so they survive the runtime's re-materialing
    // of Mesh_ renderers (which keeps mainTexture). Frame-space terrain: negative bias keeps the near field's detail.
    static Texture2D Tex(string path, bool clamp, int maxSize = 2048, float mipBias = 0f, int aniso = 0)
    {
        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
        var ti = (TextureImporter)AssetImporter.GetAtPath(path) ?? throw new InvalidOperationException("no importer " + path);
        ti.sRGBTexture = true;
        ti.alphaIsTransparency = clamp;
        ti.wrapMode = clamp ? TextureWrapMode.Clamp : TextureWrapMode.Repeat;
        ti.mipmapEnabled = true;
        ti.isReadable = false;
        ti.maxTextureSize = maxSize;
        ti.textureCompression = TextureImporterCompression.CompressedHQ;
        ti.mipMapBias = mipBias;
        if (aniso > 0) ti.anisoLevel = aniso;
        ti.SaveAndReimport();
        return AssetDatabase.LoadAssetAtPath<Texture2D>(path) ?? throw new InvalidOperationException("texture load " + path);
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
}
