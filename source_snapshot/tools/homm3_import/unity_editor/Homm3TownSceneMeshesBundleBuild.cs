using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	/// <summary>
	/// Builds <c>homm3_town_scene_meshes</c> AssetBundle from Meshy GLBs under
	/// artifacts/meshy_town_scene_meshes plus inventory.json. Writes catalog.json and
	/// asset manifest beside the bundle.
	/// </summary>
	public static class Homm3TownSceneMeshesBundleBuild
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

		const string BundleName = "homm3_town_scene_meshes";
		const string AssetRoot = "Assets/Homm3TownSceneMeshes";
		const string CatalogSchema = "homm3_town_scene_mesh_catalog.v1";
		const string ManifestSchema = "homm3_ui_bundle_asset_manifest.v1";

		[Serializable]
		class AssetManifest
		{
			public string schema;
			public string bundle;
			public int assetCount;
			public List<string> assets;
		}

		[Serializable]
		class CatalogFile
		{
			public string schema;
			public string bundle;
			public int entryCount;
			public List<CatalogEntryJson> entries;
		}

		[Serializable]
		class CatalogEntryJson
		{
			public string relativePng;
			public string prefabKey;
			public string kind;
			public float targetHeight;
		}

		public static void BuildFromBatch()
		{
			var inventoryPath = ResolveArg("-inventoryPath", null);
			var meshesRoot = ResolveArg("-meshesRoot", null);
			var outputPath = ResolveArg("-outputPath", Path.Combine("tools", "homm3_import", "build_out"));
			if (string.IsNullOrWhiteSpace(inventoryPath) || !File.Exists(inventoryPath))
				throw new InvalidOperationException("Requires -inventoryPath pointing at inventory.json");
			if (string.IsNullOrWhiteSpace(meshesRoot) || !Directory.Exists(meshesRoot))
				throw new InvalidOperationException("Requires -meshesRoot pointing at Meshy meshes folder");
			Build(inventoryPath, meshesRoot, outputPath);
		}

		static void Build(string inventoryPath, string meshesRoot, string outputPath)
		{
			EnsureFolder(AssetRoot);
			CleanStaleAssets();

			var inventoryJson = File.ReadAllText(inventoryPath);
			var entries = ParseInventoryEntries(inventoryJson);
			if (entries.Count == 0)
				throw new InvalidOperationException("inventory has no generate=true entries with meshes");

			var prefabPaths = new List<string>();
			var catalogEntries = new List<CatalogEntryJson>();

			foreach (var entry in entries)
			{
				var meshDir = Path.Combine(meshesRoot, entry.Dir.Replace('/', Path.DirectorySeparatorChar));
				var glb = Path.Combine(meshDir, "model.glb");
				var fbx = Path.Combine(meshDir, "model.fbx");
				string modelSource = null;
				if (File.Exists(glb))
					modelSource = glb;
				else if (File.Exists(fbx))
					modelSource = fbx;
				else
				{
					Debug.LogWarning("Skipping missing GLB/FBX for " + entry.RelativePng + " under " + meshDir);
					continue;
				}

				var safeKey = entry.PrefabKey;
				var modelExt = Path.GetExtension(modelSource);
				var modelAsset = AssetRoot + "/" + safeKey + modelExt;
				CopyAsset(modelSource, modelAsset);

				var albedoPath = FindTexture(meshDir, "base_color") ?? Path.Combine(meshDir, "source_00_00.png");
				var albedoAsset = AssetRoot + "/" + safeKey + "_albedo.png";
				if (File.Exists(albedoPath))
					CopyAsset(albedoPath, albedoAsset);
				else
					throw new InvalidOperationException("Missing albedo for " + entry.RelativePng);

				var normalSrc = FindTexture(meshDir, "normal");
				var metallicSrc = FindTexture(meshDir, "metallic");
				var roughnessSrc = FindTexture(meshDir, "roughness");
				string normalAsset = null;
				string metallicAsset = null;
				string roughnessAsset = null;
				if (normalSrc != null)
				{
					normalAsset = AssetRoot + "/" + safeKey + "_normal.png";
					CopyAsset(normalSrc, normalAsset);
				}
				if (metallicSrc != null)
				{
					metallicAsset = AssetRoot + "/" + safeKey + "_metallic.png";
					CopyAsset(metallicSrc, metallicAsset);
				}
				if (roughnessSrc != null)
				{
					roughnessAsset = AssetRoot + "/" + safeKey + "_roughness.png";
					CopyAsset(roughnessSrc, roughnessAsset);
				}

				AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);
				ConfigureTexture(albedoAsset, sRGB: true, normalMap: false);
				if (normalAsset != null)
					ConfigureTexture(normalAsset, sRGB: false, normalMap: true);
				if (metallicAsset != null)
					ConfigureTexture(metallicAsset, sRGB: false, normalMap: false);
				if (roughnessAsset != null)
					ConfigureTexture(roughnessAsset, sRGB: false, normalMap: false);
				ConfigureModel(modelAsset);
				AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);

				var modelRoot = AssetDatabase.LoadAssetAtPath<GameObject>(modelAsset);
				if (modelRoot == null)
					throw new InvalidOperationException("Failed to load GLB " + modelAsset);

				var material = CreateAuthoredMaterial(
					safeKey,
					AssetDatabase.LoadAssetAtPath<Texture2D>(albedoAsset),
					normalAsset != null ? AssetDatabase.LoadAssetAtPath<Texture2D>(normalAsset) : null,
					metallicAsset != null ? AssetDatabase.LoadAssetAtPath<Texture2D>(metallicAsset) : null,
					roughnessAsset != null ? AssetDatabase.LoadAssetAtPath<Texture2D>(roughnessAsset) : null);
				var materialPath = AssetRoot + "/" + safeKey + ".mat";
				AssetDatabase.CreateAsset(material, materialPath);

				var prefabPath = AssetRoot + "/" + safeKey + ".prefab";
				var prefabRoot = BuildPrefab(modelRoot, material, safeKey, entry.TargetHeight);
				PrefabUtility.SaveAsPrefabAsset(prefabRoot, prefabPath);
				UnityEngine.Object.DestroyImmediate(prefabRoot);

				prefabPaths.Add(prefabPath);
				catalogEntries.Add(new CatalogEntryJson
				{
					relativePng = entry.RelativePng,
					prefabKey = safeKey,
					kind = entry.Kind,
					targetHeight = entry.TargetHeight
				});
			}

			if (prefabPaths.Count == 0)
				throw new InvalidOperationException("No prefabs built — no Meshy GLBs found for inventory generate set.");

			AssetDatabase.SaveAssets();
			var absoluteOutput = Path.GetFullPath(outputPath);
			Directory.CreateDirectory(absoluteOutput);

			var buildMap = new[]
			{
				new AssetBundleBuild
				{
					assetBundleName = BundleName,
					assetNames = prefabPaths.ToArray()
				}
			};
			var manifest = BuildPipeline.BuildAssetBundles(
				absoluteOutput,
				buildMap,
				BuildAssetBundleOptions.ChunkBasedCompression,
				BuildTarget.StandaloneWindows64);
			if (manifest == null)
				throw new InvalidOperationException("BuildPipeline.BuildAssetBundles returned null for " + BundleName);

			var bundlePath = Path.Combine(absoluteOutput, BundleName);
			if (!File.Exists(bundlePath))
				throw new InvalidOperationException("Expected bundle missing: " + bundlePath);

			WriteAssetManifest(absoluteOutput, prefabPaths);
			WriteCatalog(absoluteOutput, catalogEntries);
			Debug.Log(
				"Homm3TownSceneMeshesBundleBuild: built "
				+ bundlePath
				+ " prefabs="
				+ prefabPaths.Count);
		}

		sealed class InventoryEntry
		{
			public string RelativePng;
			public string PrefabKey;
			public string Kind;
			public string Dir;
			public float TargetHeight;
			public bool Generate;
		}

		static List<InventoryEntry> ParseInventoryEntries(string json)
		{
			// Lightweight parse via MiniJSON-like regex-free scan using JsonUtility is awkward for
			// nested arrays; use Unity's JsonUtility on a wrapper after extracting with simple splits.
			var list = new List<InventoryEntry>();
			var idx = 0;
			while (true)
			{
				var relIdx = json.IndexOf("\"relativePng\"", idx, StringComparison.Ordinal);
				if (relIdx < 0)
					break;
				var relativePng = ReadString(json, relIdx);
				var prefabKey = ReadFieldString(json, relIdx, "prefabKey");
				var kind = ReadFieldString(json, relIdx, "kind") ?? "building";
				var dir = ReadFieldString(json, relIdx, "dir");
				var generate = ReadFieldBool(json, relIdx, "generate", false);
				var height = ReadFieldFloat(json, relIdx, "targetHeight", 2.25f);
				idx = relIdx + 12;
				if (!generate || string.IsNullOrEmpty(relativePng) || string.IsNullOrEmpty(prefabKey) || string.IsNullOrEmpty(dir))
					continue;
				list.Add(new InventoryEntry
				{
					RelativePng = relativePng.Replace('\\', '/'),
					PrefabKey = prefabKey,
					Kind = kind,
					Dir = dir.Replace('\\', '/'),
					TargetHeight = height > 0.01f ? height : 2.25f,
					Generate = true
				});
			}
			return list;
		}

		static string ReadFieldString(string json, int from, string field)
		{
			var idx = json.IndexOf("\"" + field + "\"", from, StringComparison.Ordinal);
			if (idx < 0 || idx > from + 1200)
				return null;
			return ReadString(json, idx);
		}

		static bool ReadFieldBool(string json, int from, string field, bool fallback)
		{
			var idx = json.IndexOf("\"" + field + "\"", from, StringComparison.Ordinal);
			if (idx < 0 || idx > from + 1200)
				return fallback;
			var colon = json.IndexOf(':', idx);
			if (colon < 0)
				return fallback;
			var slice = json.Substring(colon + 1, Math.Min(16, json.Length - colon - 1));
			if (slice.IndexOf("true", StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
			if (slice.IndexOf("false", StringComparison.OrdinalIgnoreCase) >= 0)
				return false;
			return fallback;
		}

		static float ReadFieldFloat(string json, int from, string field, float fallback)
		{
			var idx = json.IndexOf("\"" + field + "\"", from, StringComparison.Ordinal);
			if (idx < 0 || idx > from + 1200)
				return fallback;
			var colon = json.IndexOf(':', idx);
			if (colon < 0)
				return fallback;
			var end = colon + 1;
			while (end < json.Length && char.IsWhiteSpace(json[end]))
				end++;
			var start = end;
			while (end < json.Length && (char.IsDigit(json[end]) || json[end] == '.' || json[end] == '-'))
				end++;
			if (start >= end)
				return fallback;
			return float.TryParse(
				json.Substring(start, end - start),
				NumberStyles.Float,
				CultureInfo.InvariantCulture,
				out var v)
				? v
				: fallback;
		}

		static string ReadString(string json, int fieldNameIdx)
		{
			var colon = json.IndexOf(':', fieldNameIdx);
			if (colon < 0)
				return null;
			var firstQuote = json.IndexOf('"', colon + 1);
			if (firstQuote < 0)
				return null;
			var i = firstQuote + 1;
			var chars = new List<char>();
			while (i < json.Length)
			{
				var c = json[i++];
				if (c == '\\' && i < json.Length)
				{
					chars.Add(json[i++]);
					continue;
				}
				if (c == '"')
					break;
				chars.Add(c);
			}
			return new string(chars.ToArray());
		}

		static string FindTexture(string meshDir, string key)
		{
			var matches = Directory.GetFiles(meshDir, "texture_*_" + key + ".png");
			if (matches != null && matches.Length > 0)
				return matches[0];
			matches = Directory.GetFiles(meshDir, "*" + key + "*.png");
			if (matches != null && matches.Length > 0)
				return matches[0];
			return null;
		}

		static GameObject BuildPrefab(GameObject modelRoot, Material material, string prefabName, float targetHeight)
		{
			var instance = PrefabUtility.InstantiatePrefab(modelRoot) as GameObject;
			if (instance == null)
				instance = UnityEngine.Object.Instantiate(modelRoot);
			instance.name = prefabName;
			var renderers = instance.GetComponentsInChildren<Renderer>(true);
			if (renderers == null || renderers.Length == 0)
				throw new InvalidOperationException("Meshy GLB has no Renderer: " + prefabName);
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
			NormalizeToTargetHeight(instance.transform, targetHeight);
			return instance;
		}

		static void NormalizeToTargetHeight(Transform root, float targetHeight)
		{
			root.localPosition = Vector3.zero;
			root.localRotation = Quaternion.identity;
			root.localScale = Vector3.one;
			OrientUprightByMaxHeight(root);
			var renderers = root.GetComponentsInChildren<Renderer>(true);
			var bounds = renderers[0].bounds;
			for (var i = 1; i < renderers.Length; i++)
				bounds.Encapsulate(renderers[i].bounds);
			var height = bounds.size.y;
			if (height <= 0.0001f)
				throw new InvalidOperationException("Mesh bounds height is zero after upright orient.");
			root.localScale = Vector3.one * (targetHeight / height);
			renderers = root.GetComponentsInChildren<Renderer>(true);
			bounds = renderers[0].bounds;
			for (var i = 1; i < renderers.Length; i++)
				bounds.Encapsulate(renderers[i].bounds);
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
		}

		static Material CreateAuthoredMaterial(
			string name,
			Texture2D albedo,
			Texture2D normal,
			Texture2D metallic,
			Texture2D roughness)
		{
			if (albedo == null)
				throw new InvalidOperationException("Missing albedo for " + name);
			var shader = Shader.Find("Universal Render Pipeline/Lit")
			             ?? Shader.Find("HDRP/Lit")
			             ?? Shader.Find("Standard");
			if (shader == null)
				throw new InvalidOperationException("No Lit/Standard shader for town scene mesh material.");
			var mat = new Material(shader) { name = name };
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
				mat.EnableKeyword("_NORMALMAP");
			}
			if (metallic != null && mat.HasProperty("_MetallicGlossMap"))
			{
				mat.SetTexture("_MetallicGlossMap", metallic);
				mat.EnableKeyword("_METALLICGLOSSMAP");
			}
			if (mat.HasProperty("_Smoothness"))
				mat.SetFloat("_Smoothness", 0.35f);
			else if (mat.HasProperty("_Glossiness"))
				mat.SetFloat("_Glossiness", 0.35f);
			return mat;
		}

		static void ConfigureModel(string assetPath)
		{
			// .glb/.gltf use GLTFast ScriptedImporter — not ModelImporter.
			if (assetPath.EndsWith(".glb", StringComparison.OrdinalIgnoreCase)
			    || assetPath.EndsWith(".gltf", StringComparison.OrdinalIgnoreCase))
			{
				AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceUpdate);
				return;
			}
			var importer = AssetImporter.GetAtPath(assetPath) as ModelImporter;
			if (importer == null)
				throw new InvalidOperationException("Missing ModelImporter for " + assetPath);
			importer.meshCompression = ModelImporterMeshCompression.Off;
			importer.isReadable = false;
			importer.materialImportMode = ModelImporterMaterialImportMode.None;
			importer.animationType = ModelImporterAnimationType.None;
			importer.importAnimation = false;
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

		static void WriteAssetManifest(string absoluteOutput, List<string> prefabPaths)
		{
			var assets = new List<string>();
			foreach (var p in prefabPaths)
				assets.Add(Path.GetFileNameWithoutExtension(p));
			var assetManifest = new AssetManifest
			{
				schema = ManifestSchema,
				bundle = BundleName,
				assetCount = assets.Count,
				assets = assets
			};
			File.WriteAllText(
				Path.Combine(absoluteOutput, BundleName + ".asset_manifest.json"),
				JsonUtility.ToJson(assetManifest, true));
		}

		static void WriteCatalog(string absoluteOutput, List<CatalogEntryJson> entries)
		{
			var catalog = new CatalogFile
			{
				schema = CatalogSchema,
				bundle = BundleName,
				entryCount = entries.Count,
				entries = entries
			};
			File.WriteAllText(
				Path.Combine(absoluteOutput, "catalog.json"),
				JsonUtility.ToJson(catalog, true));
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
