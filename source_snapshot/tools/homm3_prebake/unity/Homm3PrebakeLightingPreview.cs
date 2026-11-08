// Unity-editor lighting preview for the HoMM3 prebaked-lighting experiment (tools/homm3_prebake).
//
// Copied into V:/homm3_unity_work/Assets/Editor/ by tools/homm3_prebake/unity_preview.py and run with
//   Unity.exe -batchmode -projectPath V:/homm3_unity_work -executeMethod Homm3PrebakeLightingPreview.Run
//
// The lab project's Hex/Lit is an exporter stub (unlit: _MainTex * _Color). The installed game's
// Hex/Lit Lit pass computes albedo * (sun * saturate(N.L) * shadow + SH ambient) with no normal map
// and no specular (static bytecode read, docs/homm3_prebaked_lighting.md). This preview therefore
// renders each candidate texture twice:
//   * "hexLitReplica" - Homm3PrebakeHexLitReplica.shader: that formula evaluated directly with the
//     sand-arena MainLight colour/direction and flat ambient read from the installed scenes
//     (pipeline-independent; URP Simple Lit rendered magenta in this batch setup). No shadows;
//   * "labStubHexLit" - the lab's own Hex/Lit stub (what an editor preview of the bundle shows).
// Proof tier: Unity-editor-rendered. It is NOT the game's compiled shader and NOT in-game.
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

public static class Homm3PrebakeLightingPreview
{
    const string AssetDir = "Assets/Homm3PrebakePreview";

    public static void Run()
    {
        var outDir = Environment.GetEnvironmentVariable("HOMM3_PREBAKE_OUT");
        if (string.IsNullOrEmpty(outDir))
            throw new InvalidOperationException("HOMM3_PREBAKE_OUT not set");
        Directory.CreateDirectory(outDir);
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var meshGo = AssetDatabase.LoadAssetAtPath<GameObject>(AssetDir + "/behemoth_f001.obj");
        if (meshGo == null)
            throw new InvalidOperationException("OBJ not imported");

        // Sand arena MainLight: colour (1, .957, .839), intensity 1, local forward (0.624, -0.4035, 0.6692)
        var lightGo = new GameObject("MainLight");
        var light = lightGo.AddComponent<Light>();
        light.type = LightType.Directional;
        light.color = new Color(1f, 0.9569f, 0.8392f);
        light.intensity = 1f;
        light.shadows = LightShadows.Hard;
        lightGo.transform.rotation = Quaternion.LookRotation(new Vector3(0.624f, -0.4035f, 0.6692f));

        var ambient = new Color(0.6235f, 0.6784f, 0.7922f);
        RenderSettings.ambientMode = AmbientMode.Flat;
        RenderSettings.ambientLight = ambient;
        var sh = new SphericalHarmonicsL2();
        sh.AddAmbientLight(ambient.linear);
        RenderSettings.ambientProbe = sh;
        RenderSettings.ambientIntensity = 1f;

        var camGo = new GameObject("Cam");
        var cam = camGo.AddComponent<Camera>();
        cam.orthographic = true;
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0.18f, 0.18f, 0.18f, 1f);
        camGo.transform.rotation = Quaternion.Euler(40f, 0f, 0f);

        var textures = new List<string>();
        foreach (var p in Directory.GetFiles(AssetDir, "*.png"))
            textures.Add(p.Replace('\\', '/'));
        textures.Sort();

        var replica = Shader.Find("Hidden/Homm3Prebake/HexLitReplica");
        var stub = Shader.Find("Hex/Lit");
        var report = new List<string>();
        var yaws = new (string name, float yaw)[] { ("faces_right", -60f), ("faces_left", 60f), ("faces_camera", 0f), ("faces_away", 180f) };
        const int size = 512;
        var rt = new RenderTexture(size, size, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB) { antiAliasing = 4 };
        cam.targetTexture = rt;
        var read = new Texture2D(size, size, TextureFormat.RGB24, false);

        foreach (var texPath in textures)
        {
            var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(texPath);
            foreach (var (shaderTag, shader) in new[] { ("hexLitReplica", replica), ("labStubHexLit", stub) })
            {
                if (shader == null)
                {
                    report.Add($"missing shader {shaderTag}");
                    continue;
                }
                var mat = new Material(shader);
                if (mat.HasProperty("_BaseMap")) mat.SetTexture("_BaseMap", tex);
                if (mat.HasProperty("_MainTex")) mat.SetTexture("_MainTex", tex);
                if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", Color.white);
                if (mat.HasProperty("_Color")) mat.SetColor("_Color", Color.white);
                if (mat.HasProperty("_SunDir"))
                {
                    mat.SetVector("_SunDir", new Vector4(0.624f, -0.4035f, 0.6692f, 0f));
                    var sc = new Color(1f, 0.9569f, 0.8392f).linear;
                    mat.SetVector("_SunColor", new Vector4(sc.r, sc.g, sc.b, 0f));
                    var am = ambient.linear;
                    mat.SetVector("_Ambient", new Vector4(am.r, am.g, am.b, 0f));
                }
                if (mat.HasProperty("_SpecularHighlights")) mat.SetFloat("_SpecularHighlights", 0f);
                mat.DisableKeyword("_SPECULAR_COLOR");
                mat.DisableKeyword("_SPECGLOSSMAP");
                if (mat.HasProperty("_SpecColor")) mat.SetColor("_SpecColor", Color.black);
                if (mat.HasProperty("_Smoothness")) mat.SetFloat("_Smoothness", 0f);

                foreach (var (facing, yaw) in yaws)
                {
                    var inst = (GameObject)UnityEngine.Object.Instantiate(meshGo);
                    // OBJ export (forward -Z) puts the unit's front at +Z in Unity, i.e. away from this
                    // camera; +180 makes the facing labels match the Blender battle views.
                    inst.transform.rotation = Quaternion.Euler(0f, yaw + 180f, 0f);
                    var renderers = inst.GetComponentsInChildren<MeshRenderer>();
                    var bounds = new Bounds(inst.transform.position, Vector3.zero);
                    foreach (var r in renderers)
                    {
                        r.sharedMaterial = mat;
                        r.shadowCastingMode = ShadowCastingMode.On;
                        bounds.Encapsulate(r.bounds);
                    }
                    var ext = bounds.size.magnitude;
                    cam.orthographicSize = ext * 0.5f;
                    camGo.transform.position = bounds.center - camGo.transform.forward * ext * 3f;
                    cam.nearClipPlane = 0.01f;
                    cam.farClipPlane = ext * 10f;
                    cam.Render();
                    RenderTexture.active = rt;
                    read.ReadPixels(new Rect(0, 0, size, size), 0, 0);
                    read.Apply();
                    RenderTexture.active = null;
                    var name = $"{Path.GetFileNameWithoutExtension(texPath)}__{shaderTag}__{facing}.png";
                    File.WriteAllBytes(Path.Combine(outDir, name), read.EncodeToPNG());
                    report.Add(name);
                    UnityEngine.Object.DestroyImmediate(inst);
                }
            }
        }
        File.WriteAllLines(Path.Combine(outDir, "unity_preview_report.txt"), report);
        Debug.Log("HOMM3_PREBAKE_PREVIEW_DONE " + report.Count);
    }
}
