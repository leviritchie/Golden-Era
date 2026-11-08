// Canonical copy for git. Deploy to: <UnityProject>/Assets/Editor/BuildHomm3TownPrefabs.cs
// Batch: -executeMethod OldenEra.Homm3TownPrefabs.BuildHomm3TownPrefabs.BuildFromRuntimeAssets
//        -sourceRoot <OfflineUnlockMod/homm3_runtime_assets/town_scene_refs> -outputPath <path> [-fraction <sid>]

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.UI;

namespace OldenEra.Homm3TownPrefabs
{
	public static class BuildHomm3TownPrefabs
	{
		const string GeneratedRoot = "Assets/Generated/Homm3TownPrefabs";
		const string BundleName = "homm3_town_prefabs";

		[Serializable]
		class PositionsFile
		{
			public LayerEntry[] layers;
		}

		[Serializable]
		class LayerEntry
		{
			public string id;
			public int x;
			public int y;
			public int z;
			public int order;
			public string sprite;
			public bool hidden;
		}

		public static void BuildFromRuntimeAssets()
		{
			string sourceRoot = null;
			string outputPath = null;
			string fraction = null;
			var args = Environment.GetCommandLineArgs();
			for (var i = 0; i < args.Length - 1; i++)
			{
				if (args[i] == "-sourceRoot")
					sourceRoot = args[i + 1];
				if (args[i] == "-outputPath")
					outputPath = args[i + 1];
				if (args[i] == "-fraction")
					fraction = args[i + 1];
			}

			if (string.IsNullOrWhiteSpace(sourceRoot) || string.IsNullOrWhiteSpace(outputPath))
				throw new InvalidOperationException("BuildHomm3TownPrefabs requires -sourceRoot and -outputPath.");

			sourceRoot = Path.GetFullPath(sourceRoot);
			outputPath = Path.GetFullPath(outputPath);
			if (!Directory.Exists(sourceRoot))
				throw new InvalidOperationException("Town scene runtime asset root not found: " + sourceRoot);

			Directory.CreateDirectory(outputPath);
			EnsureFolder("Assets", "Generated");
			EnsureFolder("Assets/Generated", "Homm3TownPrefabs");

			var builtPrefabs = new List<string>();
			var factionDirs = Directory.GetDirectories(sourceRoot, "homm3_*", SearchOption.TopDirectoryOnly)
				.OrderBy(x => x, StringComparer.OrdinalIgnoreCase)
				.ToArray();
			foreach (var factionDir in factionDirs)
			{
				var factionSid = Path.GetFileName(factionDir);
				if (!string.IsNullOrWhiteSpace(fraction) && !string.Equals(factionSid, fraction, StringComparison.OrdinalIgnoreCase))
					continue;

				var prefabPath = BuildFactionPrefab(factionDir, factionSid);
				if (!string.IsNullOrEmpty(prefabPath))
					builtPrefabs.Add(prefabPath);
			}

			if (builtPrefabs.Count == 0)
				throw new InvalidOperationException("BuildHomm3TownPrefabs: no prefabs built from " + sourceRoot);

			var build = new AssetBundleBuild
			{
				assetBundleName = BundleName,
				assetNames = builtPrefabs.ToArray()
			};

			AssetDatabase.SaveAssets();
			AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
			var manifest = BuildPipeline.BuildAssetBundles(
				outputPath,
				new[] { build },
				BuildAssetBundleOptions.ChunkBasedCompression,
				EditorUserBuildSettings.activeBuildTarget);
			if (manifest == null)
				throw new InvalidOperationException("BuildHomm3TownPrefabs: BuildPipeline.BuildAssetBundles returned null.");

			Debug.Log("BuildHomm3TownPrefabs: wrote " + builtPrefabs.Count + " prefab(s) to " + outputPath);
		}

		static string BuildFactionPrefab(string factionDir, string factionSid)
		{
			var layersDir = Path.Combine(factionDir, "layers");
			var positionsPath = Path.Combine(layersDir, "positions.json");
			if (!File.Exists(positionsPath))
			{
				Debug.LogWarning("BuildHomm3TownPrefabs: missing positions.json for " + factionSid);
				return null;
			}

			var positions = JsonUtility.FromJson<PositionsFile>(File.ReadAllText(positionsPath));
			if (positions?.layers == null || positions.layers.Length == 0)
			{
				Debug.LogWarning("BuildHomm3TownPrefabs: no layers for " + factionSid);
				return null;
			}

			var factionAssetFolder = GeneratedRoot + "/" + factionSid;
			EnsureFolder(GeneratedRoot, factionSid);
			EnsureFolder(factionAssetFolder, "Textures");

			var root = new GameObject(factionSid + "_town");
			root.AddComponent<RectTransform>();
			try
			{
				foreach (var layer in positions.layers.OrderBy(x => x.z).ThenBy(x => x.order))
				{
					if (layer == null || string.IsNullOrWhiteSpace(layer.id))
						continue;

					var sourcePng = ResolveLayerPng(layersDir, layer);
					if (sourcePng == null)
					{
						Debug.LogWarning("BuildHomm3TownPrefabs: missing PNG for " + factionSid + "/" + layer.id);
						continue;
					}

					var textureAsset = ImportLayerTexture(factionAssetFolder, sourcePng);
					var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(textureAsset);
					if (texture == null)
						throw new InvalidOperationException("Imported texture did not load: " + textureAsset);

					foreach (var level in CandidateLevels(layer.id))
					{
						var child = new GameObject(BuildLayerObjectName(layer.id, level));
						var rect = child.AddComponent<RectTransform>();
						rect.SetParent(root.transform, false);
						rect.anchorMin = new Vector2(0f, 1f);
						rect.anchorMax = new Vector2(0f, 1f);
						rect.pivot = new Vector2(0f, 1f);
						rect.anchoredPosition = new Vector2(layer.x, -layer.y);
						rect.sizeDelta = new Vector2(texture.width, texture.height);
						var image = child.AddComponent<RawImage>();
						image.texture = texture;
						image.raycastTarget = false;
						image.maskable = false;
						child.SetActive(false);
					}
				}

				var prefabPath = factionAssetFolder + "/" + factionSid + "_town.prefab";
				PrefabUtility.SaveAsPrefabAsset(root, prefabPath);
				var importer = AssetImporter.GetAtPath(prefabPath);
				if (importer != null)
					importer.assetBundleName = BundleName;
				return prefabPath;
			}
			finally
			{
				UnityEngine.Object.DestroyImmediate(root);
			}
		}

		static string ResolveLayerPng(string layersDir, LayerEntry layer)
		{
			if (!string.IsNullOrWhiteSpace(layer.sprite))
			{
				var bySprite = Path.Combine(layersDir, layer.sprite);
				if (File.Exists(bySprite))
					return bySprite;
			}

			var candidates = new[]
			{
				Path.Combine(layersDir, layer.id + ".png"),
				Path.Combine(layersDir, "layer_" + layer.id + ".png")
			};
			return candidates.FirstOrDefault(File.Exists);
		}

		static string ImportLayerTexture(string factionAssetFolder, string sourcePng)
		{
			var dest = factionAssetFolder + "/Textures/" + Path.GetFileName(sourcePng);
			if (File.Exists(dest))
				File.Delete(dest);
			FileUtil.CopyFileOrDirectory(sourcePng, dest);
			AssetDatabase.ImportAsset(dest, ImportAssetOptions.ForceSynchronousImport);
			var importer = AssetImporter.GetAtPath(dest) as TextureImporter;
			if (importer != null)
			{
				importer.textureType = TextureImporterType.Default;
				importer.alphaIsTransparency = true;
				importer.mipmapEnabled = false;
				importer.wrapMode = TextureWrapMode.Clamp;
				importer.filterMode = FilterMode.Bilinear;
				importer.SaveAndReimport();
			}
			return dest;
		}

		static void EnsureFolder(string parent, string name)
		{
			var full = parent + "/" + name;
			if (!AssetDatabase.IsValidFolder(full))
				AssetDatabase.CreateFolder(parent, name);
		}

		static string BuildLayerObjectName(string sid, int level)
		{
			return "OfflineUnlockStrongholdTownLayer_" + SanitizeLayerId(sid) + "_" + level;
		}

		static string SanitizeLayerId(string sid)
		{
			if (string.IsNullOrEmpty(sid))
				return "unknown";
			return new string(sid.Select(ch => char.IsLetterOrDigit(ch) ? ch : '_').ToArray());
		}

		static int ExtractLevel(string id)
		{
			if (string.IsNullOrEmpty(id))
				return 1;
			var i = id.Length - 1;
			while (i >= 0 && char.IsDigit(id[i]))
				i--;
			if (i == id.Length - 1)
				return 1;
			return int.TryParse(id.Substring(i + 1), out var level) && level > 0 ? level : 1;
		}

		static IEnumerable<int> CandidateLevels(string id)
		{
			var seen = new HashSet<int>();
			var parsed = ExtractLevel(id);
			if (seen.Add(parsed))
				yield return parsed;
			for (var level = 1; level <= 4; level++)
				if (seen.Add(level))
					yield return level;
		}
	}
}
