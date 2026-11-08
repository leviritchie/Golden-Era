using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	/// <summary>
	/// Builds <c>homm3_tower_city_map_mesh</c> AssetBundle from a Meshy FBX + PBR textures.
	/// Prefab asset name: <c>tower_city_map_mesh</c>. Target authored height is ~5.15 world units
	/// (Tower cityMapBillboardHeight / ~3x3 adventure-map footprint).
	/// </summary>
	public static class Homm3TowerCityMapMeshBundleBuild
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

		const string BundleName = "homm3_tower_city_map_mesh";
		const string AssetRoot = "Assets/Homm3TowerCityMapMesh";
		const string PrefabAssetName = "tower_city_map_mesh";
		const string ManifestSchema = "homm3_ui_bundle_asset_manifest.v1";
		const float TargetWorldHeight = 5.15f;

		[Serializable]
		class AssetManifest
		{
			public string schema;
			public string bundle;
			public int assetCount;
			public List<string> assets;
		}

		public static void BuildFromBatch()
		{
			var sourceDir = ResolveArg("-sourceDir", null);
			var outputPath = ResolveArg("-outputPath", Path.Combine("tools", "homm3_import", "build_out"));
			if (string.IsNullOrWhiteSpace(sourceDir) || !Directory.Exists(sourceDir))
				throw new InvalidOperationException(
					"Homm3TowerCityMapMeshBundleBuild requires -sourceDir pointing at the extracted Meshy FBX folder.");
			Build(sourceDir, outputPath);
		}

		static void Build(string sourceDir, string outputPath)
		{
			EnsureFolder(AssetRoot);
			CleanStaleAssets();

			var absSource = Path.GetFullPath(sourceDir);
			var fbxName = FindRequiredFile(absSource, "*.fbx");
			var albedoName = FindRequiredFile(absSource, "*_texture.png");
			var normalName = FindOptionalFile(absSource, "*_texture_normal.png");
			var metallicName = FindOptionalFile(absSource, "*_texture_metallic.png");
			var roughnessName = FindOptionalFile(absSource, "*_texture_roughness.png");

			var fbxAsset = AssetRoot + "/tower_city.fbx";
			var albedoAsset = AssetRoot + "/tower_city_albedo.png";
			var normalAsset = AssetRoot + "/tower_city_normal.png";
			var metallicAsset = AssetRoot + "/tower_city_metallic.png";
			var roughnessAsset = AssetRoot + "/tower_city_roughness.png";

			CopyAsset(Path.Combine(absSource, fbxName), fbxAsset);
			CopyAsset(Path.Combine(absSource, albedoName), albedoAsset);
			if (normalName != null)
				CopyAsset(Path.Combine(absSource, normalName), normalAsset);
			if (metallicName != null)
				CopyAsset(Path.Combine(absSource, metallicName), metallicAsset);
			if (roughnessName != null)
				CopyAsset(Path.Combine(absSource, roughnessName), roughnessAsset);

			AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);

			ConfigureTexture(albedoAsset, sRGB: true, normalMap: false);
			if (File.Exists(Path.GetFullPath(normalAsset)))
				ConfigureTexture(normalAsset, sRGB: false, normalMap: true);
			if (File.Exists(Path.GetFullPath(metallicAsset)))
				ConfigureTexture(metallicAsset, sRGB: false, normalMap: false);
			if (File.Exists(Path.GetFullPath(roughnessAsset)))
				ConfigureTexture(roughnessAsset, sRGB: false, normalMap: false);
			ConfigureModel(fbxAsset);

			AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);

			var modelRoot = AssetDatabase.LoadAssetAtPath<GameObject>(fbxAsset);
			if (modelRoot == null)
				throw new InvalidOperationException("Failed to load FBX model at " + fbxAsset);

			var material = CreateAuthoredMaterial(
				AssetDatabase.LoadAssetAtPath<Texture2D>(albedoAsset),
				File.Exists(Path.GetFullPath(normalAsset))
					? AssetDatabase.LoadAssetAtPath<Texture2D>(normalAsset)
					: null,
				File.Exists(Path.GetFullPath(metallicAsset))
					? AssetDatabase.LoadAssetAtPath<Texture2D>(metallicAsset)
					: null,
				File.Exists(Path.GetFullPath(roughnessAsset))
					? AssetDatabase.LoadAssetAtPath<Texture2D>(roughnessAsset)
					: null);
			var materialPath = AssetRoot + "/tower_city_map_mesh.mat";
			AssetDatabase.CreateAsset(material, materialPath);

			var prefabPath = AssetRoot + "/" + PrefabAssetName + ".prefab";
			var prefabRoot = BuildPrefab(modelRoot, material);
			PrefabUtility.SaveAsPrefabAsset(prefabRoot, prefabPath);
			UnityEngine.Object.DestroyImmediate(prefabRoot);

			AssetDatabase.SaveAssets();

			var absoluteOutput = Path.GetFullPath(outputPath);
			Directory.CreateDirectory(absoluteOutput);

			var assetNames = new[] { prefabPath };
			var buildMap = new[]
			{
				new AssetBundleBuild
				{
					assetBundleName = BundleName,
					assetNames = assetNames
				}
			};
			var manifest = BuildPipeline.BuildAssetBundles(
				absoluteOutput,
				buildMap,
				BuildAssetBundleOptions.ChunkBasedCompression,
				BuildTarget.StandaloneWindows64);
			if (manifest == null)
				throw new InvalidOperationException(
					"BuildPipeline.BuildAssetBundles returned null for " + BundleName);

			var bundlePath = Path.Combine(absoluteOutput, BundleName);
			if (!File.Exists(bundlePath))
				throw new InvalidOperationException(
					"Expected Tower city map mesh bundle was not produced: " + bundlePath);

			WriteAssetManifest(absoluteOutput);

			Debug.Log(
				"Homm3TowerCityMapMeshBundleBuild: built "
				+ bundlePath
				+ " prefab="
				+ PrefabAssetName
				+ " targetHeight="
				+ TargetWorldHeight.ToString("0.###"));
		}

		static GameObject BuildPrefab(GameObject modelRoot, Material material)
		{
			var instance = PrefabUtility.InstantiatePrefab(modelRoot) as GameObject;
			if (instance == null)
				instance = UnityEngine.Object.Instantiate(modelRoot);
			instance.name = PrefabAssetName;

			var renderers = instance.GetComponentsInChildren<Renderer>(true);
			if (renderers == null || renderers.Length == 0)
				throw new InvalidOperationException("Meshy Tower FBX has no Renderer components.");

			foreach (var renderer in renderers)
			{
				var mats = new Material[renderer.sharedMaterials != null && renderer.sharedMaterials.Length > 0
					? renderer.sharedMaterials.Length
					: 1];
				for (var i = 0; i < mats.Length; i++)
					mats[i] = material;
				renderer.sharedMaterials = mats;
				renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.On;
				renderer.receiveShadows = true;
			}

			NormalizeToTargetHeight(instance.transform);
			return instance;
		}

		static void NormalizeToTargetHeight(Transform root)
		{
			root.localPosition = Vector3.zero;
			root.localRotation = Quaternion.identity;
			root.localScale = Vector3.one;

			// Meshy FBX is typically Z-up; Unity adventure-map space is Y-up. Pick the
			// orientation whose world AABB is tallest before baking scale.
			OrientUprightByMaxHeight(root);

			var renderers = root.GetComponentsInChildren<Renderer>(true);
			var bounds = renderers[0].bounds;
			for (var i = 1; i < renderers.Length; i++)
				bounds.Encapsulate(renderers[i].bounds);

			var height = bounds.size.y;
			if (height <= 0.0001f)
				throw new InvalidOperationException("Meshy Tower FBX bounds height is zero after upright orient.");

			var scale = TargetWorldHeight / height;
			root.localScale = Vector3.one * scale;

			renderers = root.GetComponentsInChildren<Renderer>(true);
			bounds = renderers[0].bounds;
			for (var i = 1; i < renderers.Length; i++)
				bounds.Encapsulate(renderers[i].bounds);

			// Pivot the prefab so the mesh sits on y=0 with XZ centered on local origin.
			var worldBottomCenter = new Vector3(bounds.center.x, bounds.min.y, bounds.center.z);
			var localBottomCenter = root.InverseTransformPoint(worldBottomCenter);
			foreach (Transform child in root)
				child.localPosition -= localBottomCenter;
		}

		static void OrientUprightByMaxHeight(Transform root)
		{
			var candidates = new[]
			{
				Quaternion.identity,
				Quaternion.Euler(-90f, 0f, 0f),
				Quaternion.Euler(90f, 0f, 0f),
				Quaternion.Euler(0f, 0f, -90f),
				Quaternion.Euler(0f, 0f, 90f)
			};
			var renderers = root.GetComponentsInChildren<Renderer>(true);
			if (renderers == null || renderers.Length == 0)
				return;

			var best = Quaternion.identity;
			var bestHeight = -1f;
			foreach (var rot in candidates)
			{
				root.localRotation = rot;
				var bounds = renderers[0].bounds;
				for (var i = 1; i < renderers.Length; i++)
					bounds.Encapsulate(renderers[i].bounds);
				if (bounds.size.y > bestHeight)
				{
					bestHeight = bounds.size.y;
					best = rot;
				}
			}
			root.localRotation = best;
			Debug.Log(
				"Homm3TowerCityMapMeshBundleBuild: upright orient euler="
				+ best.eulerAngles.ToString("0.#")
				+ " height="
				+ bestHeight.ToString("0.###")
				+ " (runtime applies Meshy +180 yaw face correction)");
		}

		static Material CreateAuthoredMaterial(
			Texture2D albedo,
			Texture2D normal,
			Texture2D metallic,
			Texture2D roughness)
		{
			if (albedo == null)
				throw new InvalidOperationException("Meshy Tower albedo texture failed to import.");

			var shader = Shader.Find("Universal Render Pipeline/Lit")
			             ?? Shader.Find("HDRP/Lit")
			             ?? Shader.Find("Standard");
			if (shader == null)
				throw new InvalidOperationException(
					"No authoring Lit/Standard shader found for Tower city map mesh material.");

			var mat = new Material(shader)
			{
				name = "tower_city_map_mesh"
			};

			if (mat.HasProperty("_BaseMap"))
				mat.SetTexture("_BaseMap", albedo);
			if (mat.HasProperty("_MainTex"))
				mat.SetTexture("_MainTex", albedo);
			mat.mainTexture = albedo;

			if (normal != null)
			{
				if (mat.HasProperty("_BumpMap"))
					mat.SetTexture("_BumpMap", normal);
				if (mat.HasProperty("_NormalMap"))
					mat.SetTexture("_NormalMap", normal);
				if (mat.HasProperty("_BumpScale"))
					mat.SetFloat("_BumpScale", 1f);
				mat.EnableKeyword("_NORMALMAP");
			}

			if (metallic != null && mat.HasProperty("_MetallicGlossMap"))
			{
				mat.SetTexture("_MetallicGlossMap", metallic);
				mat.EnableKeyword("_METALLICGLOSSMAP");
			}
			else if (metallic != null && mat.HasProperty("_MetallicMap"))
			{
				mat.SetTexture("_MetallicMap", metallic);
			}

			if (roughness != null && mat.HasProperty("_Smoothness"))
			{
				// Roughness texture is authored separately; use a mid smoothness so the model is not plastic.
				mat.SetFloat("_Smoothness", 0.35f);
			}
			else if (mat.HasProperty("_Glossiness"))
			{
				mat.SetFloat("_Glossiness", 0.35f);
			}

			return mat;
		}

		static void ConfigureModel(string assetPath)
		{
			var importer = AssetImporter.GetAtPath(assetPath) as ModelImporter;
			if (importer == null)
				throw new InvalidOperationException("Missing ModelImporter for " + assetPath);
			importer.meshCompression = ModelImporterMeshCompression.Off;
			importer.isReadable = false;
			importer.materialImportMode = ModelImporterMaterialImportMode.None;
			importer.animationType = ModelImporterAnimationType.None;
			importer.importAnimation = false;
			importer.importBlendShapes = false;
			importer.importVisibility = false;
			importer.importCameras = false;
			importer.importLights = false;
			importer.SaveAndReimport();
		}

		static void ConfigureTexture(string assetPath, bool sRGB, bool normalMap)
		{
			var importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
			if (importer == null)
				throw new InvalidOperationException("Missing TextureImporter for " + assetPath);
			importer.textureType = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
			importer.sRGBTexture = sRGB;
			importer.mipmapEnabled = true;
			importer.maxTextureSize = 2048;
			importer.textureCompression = TextureImporterCompression.Compressed;
			importer.filterMode = FilterMode.Bilinear;
			importer.wrapMode = TextureWrapMode.Repeat;
			importer.SaveAndReimport();
		}

		static void CopyAsset(string sourceAbsolute, string destRelative)
		{
			var destAbsolute = Path.GetFullPath(destRelative);
			Directory.CreateDirectory(Path.GetDirectoryName(destAbsolute) ?? ".");
			File.Copy(sourceAbsolute, destAbsolute, overwrite: true);
		}

		static string FindRequiredFile(string dir, string pattern)
		{
			var matches = Directory.GetFiles(dir, pattern);
			if (matches == null || matches.Length == 0)
				throw new InvalidOperationException(
					"Required Meshy Tower asset missing under " + dir + " matching " + pattern);
			return Path.GetFileName(matches[0]);
		}

		static string FindOptionalFile(string dir, string pattern)
		{
			var matches = Directory.GetFiles(dir, pattern);
			if (matches == null || matches.Length == 0)
				return null;
			return Path.GetFileName(matches[0]);
		}

		static void CleanStaleAssets()
		{
			var absoluteRoot = Path.GetFullPath(AssetRoot);
			if (!Directory.Exists(absoluteRoot))
				return;
			foreach (var stale in Directory.GetFiles(absoluteRoot, "*", SearchOption.AllDirectories))
			{
				if (stale.EndsWith(".meta", StringComparison.OrdinalIgnoreCase))
					continue;
				File.Delete(stale);
				var meta = stale + ".meta";
				if (File.Exists(meta))
					File.Delete(meta);
			}
			AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);
		}

		static void WriteAssetManifest(string absoluteOutput)
		{
			var assetManifest = new AssetManifest
			{
				schema = ManifestSchema,
				bundle = BundleName,
				assetCount = 1,
				assets = new List<string> { PrefabAssetName }
			};
			var manifestPath = Path.Combine(absoluteOutput, BundleName + ".asset_manifest.json");
			File.WriteAllText(manifestPath, JsonUtility.ToJson(assetManifest, prettyPrint: true));
			Debug.Log("Homm3TowerCityMapMeshBundleBuild: wrote asset manifest " + manifestPath);
		}

		static void EnsureFolder(string assetFolder)
		{
			if (AssetDatabase.IsValidFolder(assetFolder))
				return;
			var parts = assetFolder.Split('/');
			var current = parts[0];
			for (var i = 1; i < parts.Length; i++)
			{
				var next = current + "/" + parts[i];
				if (!AssetDatabase.IsValidFolder(next))
					AssetDatabase.CreateFolder(current, parts[i]);
				current = next;
			}
		}

		static string ResolveArg(string name, string fallback)
		{
			var args = UnityQueueArgs();
			for (var i = 0; i + 1 < args.Length; i++)
			{
				if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase))
					return args[i + 1];
			}
			return fallback;
		}
	}
}
