// Metal-shine Unity jobs (docs/homm3_metal_shine.md). Staged into <project>/Assets/Editor/Homm3MetalShine/ by
// tools/homm3_metal_shine/unity_jobs.py and run through the shared Unity queue.
//
//   BuildShaderBundle  -metalShineOut <dir>            one-asset bundle homm3_metal_shine_shader (StandaloneWindows64,
//                                                        ChunkBasedCompression, like the battle BillboardArray shader),
//                                                        then a load-back probe that writes shader_probe.json.
//   RenderLab          -metalShineLabSpec <json>       offline turn/animation renders: Hex/Lit replica body, with and
//                                                        without the appended shine material, PNG tiles + frames.json.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3MetalShine
{
	public static class Homm3MetalShineBuild
	{
		const string ShaderAsset = "Assets/Homm3MetalShine/Shaders/Homm3MetalShine.shader";
		const string ReplicaAsset = "Assets/Homm3MetalShine/Shaders/Homm3PrebakeHexLitReplica.shader";
		const string ShaderName = "OldenEra/Homm3/MetalShine";
		const string BundleName = "homm3_metal_shine_shader";

		static string[] UnityQueueArgs() => AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") as string[] ?? Environment.GetCommandLineArgs();
		static void UnityQueueExit(int code)
		{
			if (AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") == null) { EditorApplication.Exit(code); return; }
			if (!(AppDomain.CurrentDomain.GetData("UnityQueue.ExitCode") is int prev && prev != 0)) AppDomain.CurrentDomain.SetData("UnityQueue.ExitCode", code);
		}

		static string OptArg(string name)
		{
			var a = UnityQueueArgs();
			for (int i = 0; i + 1 < a.Length; i++)
				if (string.Equals(a[i], name, StringComparison.OrdinalIgnoreCase)) return a[i + 1];
			return null;
		}

		static string Arg(string name) => OptArg(name) ?? throw new InvalidOperationException("missing job arg " + name);

		/// <summary>One queue job for both steps (one editor launch): the bundle when -metalShineOut is given, then the
		/// lab when -metalShineLabSpec is given.</summary>
		public static void RunAll()
		{
			if (OptArg("-metalShineOut") == null && OptArg("-metalShineLabSpec") == null)
				throw new InvalidOperationException("RunAll needs -metalShineOut and/or -metalShineLabSpec");
			if (OptArg("-metalShineOut") != null) BuildShaderBundleCore();
			if (OptArg("-metalShineLabSpec") != null) RenderLabCore();
			UnityQueueExit(0);
		}

		static string F(float v) => v.ToString("0.######", CultureInfo.InvariantCulture);

		// ------------------------------------------------------------------ shader bundle
		public static void BuildShaderBundle() { BuildShaderBundleCore(); UnityQueueExit(0); }

		static void BuildShaderBundleCore()
		{
			string outDir = Path.GetFullPath(Arg("-metalShineOut"));
			Directory.CreateDirectory(outDir);
			AssetDatabase.ImportAsset(ShaderAsset, ImportAssetOptions.ForceUpdate);
			var shader = AssetDatabase.LoadAssetAtPath<Shader>(ShaderAsset);
			if (shader == null || shader.name != ShaderName)
				throw new InvalidOperationException("shader " + ShaderName + " did not import from " + ShaderAsset);
			var msgs = ShaderUtil.GetShaderMessages(shader);
			var errors = msgs.Where(m => m.severity == UnityEditor.Rendering.ShaderCompilerMessageSeverity.Error).ToArray();
			foreach (var m in msgs) Debug.Log("Homm3MetalShine shader message: " + m.severity + " " + m.message + " (" + m.platform + ")");
			if (ShaderUtil.ShaderHasError(shader) || errors.Length > 0)
				throw new InvalidOperationException("shader compile errors: " + string.Join("; ", errors.Select(e => e.message)));

			var build = new[] { new AssetBundleBuild { assetBundleName = BundleName, assetNames = new[] { ShaderAsset } } };
			var manifest = BuildPipeline.BuildAssetBundles(outDir, build, BuildAssetBundleOptions.ChunkBasedCompression,
				BuildTarget.StandaloneWindows64);
			string bundlePath = Path.Combine(outDir, BundleName);
			if (manifest == null || !File.Exists(bundlePath))
				throw new InvalidOperationException("bundle was not produced: " + bundlePath);

			// Load-back probe: what the plugin does (LoadFromFile + LoadAsset<Shader> by asset name).
			AssetBundle.UnloadAllAssetBundles(true);
			var b = AssetBundle.LoadFromFile(bundlePath);
			if (b == null) throw new InvalidOperationException("LoadFromFile returned null: " + bundlePath);
			string names = string.Join(",", b.GetAllAssetNames());
			var loaded = b.LoadAsset<Shader>(ShaderAsset.ToLowerInvariant());
			bool ok = loaded != null && loaded.name == ShaderName;
			string probe = "{\n  \"bundle\": \"" + BundleName + "\",\n  \"bytes\": " + new FileInfo(bundlePath).Length
				+ ",\n  \"assetNames\": \"" + names + "\",\n  \"shaderName\": \"" + (loaded != null ? loaded.name : "") + "\""
				+ ",\n  \"isSupportedEditor\": " + (loaded != null && loaded.isSupported ? "true" : "false")
				+ ",\n  \"passCount\": " + (loaded != null ? loaded.passCount : 0)
				+ ",\n  \"renderQueue\": " + (loaded != null ? loaded.renderQueue : 0)
				+ ",\n  \"compilerMessages\": " + msgs.Length
				+ ",\n  \"unity\": \"" + Application.unityVersion + "\",\n  \"target\": \"StandaloneWindows64\"\n}\n";
			b.Unload(true);
			File.WriteAllText(Path.Combine(outDir, "shader_probe.json"), probe);
			Debug.Log("Homm3MetalShine: built " + bundlePath + " probe ok=" + ok);
			if (!ok) throw new InvalidOperationException("load-back probe failed: " + probe);
		}

		// ------------------------------------------------------------------ offline render lab
		[Serializable] public sealed class Shine { public float intensity, gloss, sheen, tint; }
		[Serializable] public sealed class UnitSpec
		{
			public string sid, prefab, basecolor, mask, idleClip, attackClip;
			public Shine shine;
		}
		[Serializable] public sealed class LabSpec
		{
			public string outDir;
			public float[] sunDir, sunColor, ambient;
			public float camPitch, camYaw, fill;
			public int tile, idleFrames, attackFrames;
			public float[] yaws;
			public float unitYaw;
			public UnitSpec[] units;
		}

		static Texture2D ImportTex(string path, bool srgb)
		{
			var imp = AssetImporter.GetAtPath(path) as TextureImporter;
			if (imp == null) throw new InvalidOperationException("texture did not import: " + path);
			imp.textureType = TextureImporterType.Default; imp.sRGBTexture = srgb; imp.mipmapEnabled = true;
			imp.wrapMode = TextureWrapMode.Clamp; imp.maxTextureSize = 4096; imp.alphaSource = TextureImporterAlphaSource.FromInput;
			imp.textureCompression = TextureImporterCompression.Uncompressed;
			imp.SaveAndReimport();
			return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
		}

		static Vector3 V(float[] a) => new Vector3(a[0], a[1], a[2]);

		public static void RenderLab() { RenderLabCore(); UnityQueueExit(0); }

		static void RenderLabCore()
		{
			var spec = JsonUtility.FromJson<LabSpec>(File.ReadAllText(Arg("-metalShineLabSpec")));
			AssetDatabase.ImportAsset(ShaderAsset, ImportAssetOptions.ForceUpdate);
			AssetDatabase.ImportAsset(ReplicaAsset, ImportAssetOptions.ForceUpdate);
			var shineSh = AssetDatabase.LoadAssetAtPath<Shader>(ShaderAsset);
			var repSh = AssetDatabase.LoadAssetAtPath<Shader>(ReplicaAsset);
			if (shineSh == null || repSh == null) throw new InvalidOperationException("lab shaders missing");
			Directory.CreateDirectory(spec.outDir);
			var log = new List<string>();
			Vector3 sun = V(spec.sunDir).normalized;
			Color sunCol = new Color(spec.sunColor[0], spec.sunColor[1], spec.sunColor[2], 1);

			foreach (var u in spec.units)
			{
				var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(u.prefab);
				if (prefab == null) throw new InvalidOperationException(u.sid + ": prefab missing " + u.prefab);
				var go = (GameObject)UnityEngine.Object.Instantiate(prefab);
				go.transform.position = Vector3.zero;
				foreach (var anim in go.GetComponentsInChildren<Animator>(true)) anim.enabled = false;
				foreach (var r in go.GetComponentsInChildren<Renderer>(true))
					if (!(r is SkinnedMeshRenderer)) r.enabled = false;   // vfx quads, particles: not under test
				var skins = go.GetComponentsInChildren<SkinnedMeshRenderer>(true);
				var body = skins.Where(s => s.sharedMesh != null && !s.name.EndsWith("_Rubble"))
					.OrderByDescending(s => s.sharedMesh.vertexCount).First();
				foreach (var s in skins) if (s != body) s.enabled = false;
				body.updateWhenOffscreen = true; body.forceMatrixRecalculationPerRender = true;
				int subs = body.sharedMesh.subMeshCount;

				var albedo = ImportTex(u.basecolor, true);
				var mask = ImportTex(u.mask, true);
				var baseMat = new Material(repSh) { mainTexture = albedo };
				baseMat.SetVector("_SunDir", sun);
				baseMat.SetVector("_SunColor", new Vector4(spec.sunColor[0], spec.sunColor[1], spec.sunColor[2], 0));
				baseMat.SetVector("_Ambient", new Vector4(spec.ambient[0], spec.ambient[1], spec.ambient[2], 0));
				var shineMat = new Material(shineSh) { name = "HOMM3_metal_shine_" + u.sid };
				shineMat.SetTexture("_ShineMask", mask);
				shineMat.SetFloat("_ShineIntensity", u.shine.intensity);
				shineMat.SetFloat("_ShineGloss", u.shine.gloss);
				shineMat.SetFloat("_SheenStrength", u.shine.sheen);
				shineMat.SetFloat("_TintAmount", u.shine.tint);
				shineMat.SetVector("_ShineSunDir", sun);
				shineMat.SetColor("_ShineSunColor", sunCol);
				// shine only (on black): the same pass over a depth-only body, so occlusion matches
				var blackMat = new Material(repSh) { mainTexture = Texture2D.blackTexture };
				blackMat.SetVector("_SunDir", sun); blackMat.SetVector("_SunColor", Vector4.zero); blackMat.SetVector("_Ambient", Vector4.zero);

				var idle = AssetDatabase.LoadAssetAtPath<AnimationClip>(u.idleClip);
				var attack = AssetDatabase.LoadAssetAtPath<AnimationClip>(u.attackClip);
				if (idle == null || attack == null) throw new InvalidOperationException(u.sid + ": clips missing");

				// frame the camera on the idle rest pose bounds
				idle.SampleAnimation(go, 0f);
				body.transform.root.rotation = Quaternion.identity;
				var bounds = body.bounds;
				float h = bounds.size.y;
				Vector3 centre = bounds.center;
				var camGo = new GameObject("metal_shine_cam");
				var cam = camGo.AddComponent<Camera>();
				cam.orthographic = true;
				cam.orthographicSize = h / (2f * spec.fill);
				cam.nearClipPlane = 0.01f; cam.farClipPlane = 200f;
				cam.clearFlags = CameraClearFlags.SolidColor;
				cam.backgroundColor = new Color(0.16f, 0.15f, 0.13f, 1);
				cam.allowMSAA = false; cam.allowHDR = false;
				var camRot = Quaternion.Euler(spec.camPitch, spec.camYaw, 0);
				cam.transform.SetPositionAndRotation(centre - camRot * Vector3.forward * (h * 10f), camRot);
				var rt = new RenderTexture(spec.tile, spec.tile, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
				cam.targetTexture = rt;
				var read = new Texture2D(spec.tile, spec.tile, TextureFormat.RGBA32, false, false);
				string dir = Path.Combine(spec.outDir, u.sid);
				Directory.CreateDirectory(dir);

				var bg = cam.backgroundColor;
				void Shot(string name, Material[] mats)
				{
					body.sharedMaterials = mats;
					cam.backgroundColor = name.EndsWith("_only") ? Color.black : bg;
					cam.Render();
					RenderTexture.active = rt;
					read.ReadPixels(new Rect(0, 0, spec.tile, spec.tile), 0, 0);
					read.Apply();
					RenderTexture.active = null;
					File.WriteAllBytes(Path.Combine(dir, name + ".png"), read.EncodeToPNG());
				}
				Material[] baseOnly = Enumerable.Repeat(baseMat, subs).ToArray();
				Material[] withShine = baseOnly.Concat(new[] { shineMat }).ToArray();
				Material[] shineOnly = Enumerable.Repeat(blackMat, subs).Concat(new[] { shineMat }).ToArray();

				void Three(string tag)
				{
					Shot(tag + "_base", baseOnly);
					Shot(tag + "_shine", withShine);
					Shot(tag + "_only", shineOnly);
				}

				// turn: rest pose of the idle clip, unit yaw sweep (the camera and sun stay put)
				for (int i = 0; i < spec.yaws.Length; i++)
				{
					idle.SampleAnimation(go, 0f);
					go.transform.rotation = Quaternion.Euler(0, spec.yaws[i], 0);
					Three("turn_" + i.ToString("00"));
				}
				// animation: idle and attack at the battle-facing yaw
				go.transform.rotation = Quaternion.Euler(0, spec.unitYaw, 0);
				for (int i = 0; i < spec.idleFrames; i++)
				{
					idle.SampleAnimation(go, idle.length * i / spec.idleFrames);
					Three("idle_" + i.ToString("00"));
				}
				for (int i = 0; i < spec.attackFrames; i++)
				{
					attack.SampleAnimation(go, attack.length * i / Mathf.Max(1, spec.attackFrames - 1));
					Three("attack_" + i.ToString("00"));
				}
				log.Add("{\"sid\": \"" + u.sid + "\", \"subMeshes\": " + subs + ", \"vertices\": " + body.sharedMesh.vertexCount
					+ ", \"height\": " + F(h) + ", \"idleLen\": " + F(idle.length) + ", \"attackLen\": " + F(attack.length)
					+ ", \"body\": \"" + body.name + "\"}");
				UnityEngine.Object.DestroyImmediate(camGo);
				UnityEngine.Object.DestroyImmediate(go);
				rt.Release();
			}
			File.WriteAllText(Path.Combine(spec.outDir, "frames.json"), "[\n " + string.Join(",\n ", log) + "\n]\n");
			Debug.Log("Homm3MetalShine: lab rendered " + spec.units.Length + " units into " + spec.outDir);
		}
	}
}
