using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockModTools
{
	public static class Homm3TownPrefabBundleBuilder
	{
		private const string BundleName = "homm3_town_prefabs";
		private const string PrefabRoot = "Assets/Generated/Homm3TownPrefabs";
		private const string ManifestPath = "Assets/Generated/Homm3TownPrefabBuildManifest.tsv";

		private sealed class Entry
		{
			public string Fraction;
			public string ObjectName;
			public string TextureAssetPath;
		}

		public static void Build()
		{
			var outputDir = GetArg("-homm3TownPrefabOutput");
			if (string.IsNullOrWhiteSpace(outputDir))
				throw new InvalidOperationException("Missing -homm3TownPrefabOutput argument.");

			if (!File.Exists(ManifestPath))
				throw new FileNotFoundException("Town prefab build manifest is missing.", ManifestPath);

			var entries = ReadManifest(ManifestPath);
			if (entries.Count == 0)
				throw new InvalidOperationException("Town prefab build manifest has no entries.");

			Directory.CreateDirectory(outputDir);
			Directory.CreateDirectory(PrefabRoot);

			var prefabPaths = new List<string>();
			foreach (var group in entries.GroupBy(entry => entry.Fraction, StringComparer.OrdinalIgnoreCase))
			{
				var fraction = group.Key;
				var prefabDir = $"{PrefabRoot}/{fraction}";
				Directory.CreateDirectory(prefabDir);
				var prefabPath = $"{prefabDir}/{fraction}_town.prefab";

				var root = new GameObject($"{fraction}_town", typeof(RectTransform));
				var rootRect = root.GetComponent<RectTransform>();
				rootRect.anchorMin = Vector2.zero;
				rootRect.anchorMax = Vector2.one;
				rootRect.pivot = new Vector2(0.5f, 0.5f);
				rootRect.anchoredPosition = Vector2.zero;
				rootRect.sizeDelta = Vector2.zero;

				foreach (var entry in group.OrderBy(entry => entry.ObjectName, StringComparer.OrdinalIgnoreCase))
				{
					var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(entry.TextureAssetPath);
					if (texture == null)
						throw new InvalidOperationException($"Missing imported texture asset: {entry.TextureAssetPath}");

					var child = new GameObject(entry.ObjectName, typeof(RectTransform), typeof(RawImage));
					child.transform.SetParent(root.transform, false);
					child.SetActive(false);
					var rect = child.GetComponent<RectTransform>();
					rect.anchorMin = Vector2.zero;
					rect.anchorMax = Vector2.zero;
					rect.pivot = Vector2.zero;
					rect.anchoredPosition = Vector2.zero;
					rect.sizeDelta = new Vector2(texture.width, texture.height);

					var image = child.GetComponent<RawImage>();
					image.texture = texture;
					image.color = Color.white;
					image.raycastTarget = false;
					image.maskable = false;
				}

				PrefabUtility.SaveAsPrefabAsset(root, prefabPath);
				UnityEngine.Object.DestroyImmediate(root);
				prefabPaths.Add(prefabPath);
			}

			AssetDatabase.SaveAssets();
			AssetDatabase.Refresh();

			foreach (var path in prefabPaths)
			{
				var importer = AssetImporter.GetAtPath(path);
				if (importer == null)
					throw new InvalidOperationException($"Missing importer for generated prefab: {path}");
				importer.assetBundleName = BundleName;
			}

			AssetDatabase.RemoveUnusedAssetBundleNames();
			AssetDatabase.SaveAssets();

			var manifest = BuildPipeline.BuildAssetBundles(
				outputDir,
				BuildAssetBundleOptions.ChunkBasedCompression,
				BuildTarget.StandaloneWindows64);

			if (manifest == null)
				throw new InvalidOperationException("BuildPipeline.BuildAssetBundles returned null.");

			var bundlePath = Path.Combine(outputDir, BundleName);
			if (!File.Exists(bundlePath))
				throw new FileNotFoundException("Expected town prefab bundle was not generated.", bundlePath);

			Debug.Log($"Generated {BundleName} with {prefabPaths.Count} prefabs and {entries.Count} layer image entries at {bundlePath}");
		}

		private static List<Entry> ReadManifest(string path)
		{
			var result = new List<Entry>();
			var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
			foreach (var rawLine in File.ReadAllLines(path))
			{
				var line = rawLine.Trim();
				if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal))
					continue;

				var parts = line.Split('\t');
				if (parts.Length != 3)
					throw new InvalidOperationException($"Invalid manifest row: {rawLine}");

				var entry = new Entry
				{
					Fraction = parts[0],
					ObjectName = parts[1],
					TextureAssetPath = parts[2].Replace('\\', '/')
				};
				var key = entry.Fraction + "\t" + entry.ObjectName;
				if (seen.Add(key))
					result.Add(entry);
			}

			return result;
		}

		private static string GetArg(string name)
		{
			var args = Environment.GetCommandLineArgs();
			for (var i = 0; i < args.Length - 1; i++)
			{
				if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase))
					return args[i + 1];
			}

			return null;
		}
	}
}
