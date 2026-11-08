using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	/// <summary>
	/// Builds <c>homm3_map_billboards</c> AssetBundle with Sprites named
	/// <c>map_billboard_&lt;relative key&gt;</c> from the main billboard frames
	/// (<c>homm3_runtime_assets/map_object_refs/**/00_00.png</c>; flipbook 00_01+ frames are
	/// intentionally excluded). The relative key is deterministic from the map_object_refs
	/// relative directory: strip a trailing .dir from the leaf component, join components with
	/// "__", lowercase, and replace non [a-z0-9_] with "_" (e.g.
	/// homm3_castle_city/capitol.dir/00_00.png → map_billboard_homm3_castle_city__capitol).
	/// Also writes <c>&lt;bundle&gt;.asset_manifest.json</c> next to the bundle so runtime and
	/// validators can check asset membership without a LoadAllAssets decode.
	/// </summary>
	public static class Homm3MapBillboardBundleBuild
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

		const string BundleName = "homm3_map_billboards";
		const string AssetRoot = "Assets/Homm3MapBillboards";
		const string AssetPrefix = "map_billboard_";
		const string ManifestSchema = "homm3_ui_bundle_asset_manifest.v1";
		static readonly Regex KeySanitizeRegex = new Regex(
			"[^a-z0-9_]",
			RegexOptions.CultureInvariant);

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
			var mapObjectRefsDir = ResolveArg("-mapObjectRefsDir", null);
			var outputPath = ResolveArg("-outputPath", Path.Combine("tools", "homm3_import", "build_out"));
			if (string.IsNullOrWhiteSpace(mapObjectRefsDir) || !Directory.Exists(mapObjectRefsDir))
				throw new InvalidOperationException(
					"Homm3MapBillboardBundleBuild requires -mapObjectRefsDir pointing at homm3_runtime_assets/map_object_refs.");
			Build(mapObjectRefsDir, outputPath);
		}

		static void Build(string mapObjectRefsDir, string outputPath)
		{
			EnsureFolder(AssetRoot);
			CleanStaleAssets();

			var assetPaths = new List<string>();
			var sourceByAssetName = new Dictionary<string, string>(StringComparer.Ordinal);
			var refsRoot = Path.GetFullPath(mapObjectRefsDir);
			foreach (var pngPath in Directory.GetFiles(refsRoot, "00_00.png", SearchOption.AllDirectories))
			{
				var key = DeriveBillboardKey(refsRoot, pngPath);
				var spriteName = AssetPrefix + key;
				if (sourceByAssetName.ContainsKey(spriteName))
					throw new InvalidOperationException(
						"Asset name collision for " + spriteName + ": " + sourceByAssetName[spriteName]
						+ " vs " + pngPath);

				var destRelative = AssetRoot + "/" + spriteName + ".png";
				var destAbsolute = Path.GetFullPath(destRelative);
				Directory.CreateDirectory(Path.GetDirectoryName(destAbsolute) ?? ".");
				File.Copy(pngPath, destAbsolute, overwrite: true);
				assetPaths.Add(destRelative);
				sourceByAssetName.Add(spriteName, pngPath);
			}

			if (assetPaths.Count == 0)
				throw new InvalidOperationException(
					"No **/00_00.png billboard frames found under " + mapObjectRefsDir);

			AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);

			foreach (var assetPath in assetPaths)
			{
				var importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
				if (importer == null)
					throw new InvalidOperationException("Missing TextureImporter for " + assetPath);

				importer.textureType = TextureImporterType.Sprite;
				importer.spriteImportMode = SpriteImportMode.Single;
				importer.mipmapEnabled = false;
				importer.alphaIsTransparency = true;
				importer.npotScale = TextureImporterNPOTScale.None;
				importer.maxTextureSize = 512;
				importer.sRGBTexture = true;
				importer.filterMode = FilterMode.Point;
				importer.textureCompression = TextureImporterCompression.Compressed;
				importer.assetBundleName = BundleName;
				importer.SaveAndReimport();

				var sprite = AssetDatabase.LoadAssetAtPath<Sprite>(assetPath);
				if (sprite == null)
					throw new InvalidOperationException("Failed to import Sprite at " + assetPath);
			}

			AssetDatabase.SaveAssets();

			var absoluteOutput = Path.GetFullPath(outputPath);
			Directory.CreateDirectory(absoluteOutput);

			// Build only this bundle — BuildAssetBundles(outputPath) without a map rebuilds
			// every AssetBundleName in the huge oldenera_factions project.
			var buildMap = new[]
			{
				new AssetBundleBuild
				{
					assetBundleName = BundleName,
					assetNames = assetPaths.ToArray()
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
				throw new InvalidOperationException("Expected map billboard bundle was not produced: " + bundlePath);

			WriteAssetManifest(absoluteOutput, sourceByAssetName);

			Debug.Log(
				"Homm3MapBillboardBundleBuild: built "
				+ bundlePath
				+ " with "
				+ assetPaths.Count
				+ " sprite(s).");
		}

		static string DeriveBillboardKey(string refsRoot, string pngPath)
		{
			var parent = Path.GetDirectoryName(pngPath);
			if (string.IsNullOrWhiteSpace(parent))
				throw new InvalidOperationException("Billboard frame has no parent directory: " + pngPath);
			var relative = Path.GetRelativePath(refsRoot, parent).Replace('\\', '/');
			var parts = relative.Split('/');
			var last = parts[parts.Length - 1];
			if (last.EndsWith(".dir", StringComparison.OrdinalIgnoreCase))
				last = last.Substring(0, last.Length - ".dir".Length);
			parts[parts.Length - 1] = last;

			foreach (var part in parts)
			{
				if (string.IsNullOrWhiteSpace(part) || part == ".")
					throw new InvalidOperationException(
						"Billboard frame is not under a named map_object_refs subdirectory: " + pngPath);
			}

			var joined = string.Join("__", parts).ToLowerInvariant();
			return KeySanitizeRegex.Replace(joined, "_");
		}

		static void CleanStaleAssets()
		{
			var absoluteRoot = Path.GetFullPath(AssetRoot);
			if (!Directory.Exists(absoluteRoot))
				return;
			foreach (var stale in Directory.GetFiles(absoluteRoot, AssetPrefix + "*.png"))
			{
				File.Delete(stale);
				var meta = stale + ".meta";
				if (File.Exists(meta))
					File.Delete(meta);
			}
			AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);
		}

		static void WriteAssetManifest(string absoluteOutput, Dictionary<string, string> sourceByAssetName)
		{
			var names = new List<string>(sourceByAssetName.Keys);
			names.Sort(StringComparer.Ordinal);
			var assetManifest = new AssetManifest
			{
				schema = ManifestSchema,
				bundle = BundleName,
				assetCount = names.Count,
				assets = names
			};
			var manifestPath = Path.Combine(absoluteOutput, BundleName + ".asset_manifest.json");
			File.WriteAllText(manifestPath, JsonUtility.ToJson(assetManifest, prettyPrint: true));
			Debug.Log("Homm3MapBillboardBundleBuild: wrote asset manifest " + manifestPath);
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
