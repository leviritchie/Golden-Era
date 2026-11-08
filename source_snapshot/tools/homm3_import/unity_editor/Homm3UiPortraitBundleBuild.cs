using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	/// <summary>
	/// Builds <c>homm3_ui_portraits</c> AssetBundle with Sprites named <c>ui_portrait_&lt;sid&gt;</c>
	/// for both unit SIDs (<c>h3_*</c>, from homm3_portraits) and hero keys
	/// (<c>homm3_*_hero_*</c>, from homm3_hero_portraits_upscaled). Hero masters are 1254x1254;
	/// the importer caps them at maxTextureSize 512 so the bundle carries runtime-size textures.
	/// Also writes <c>&lt;bundle&gt;.asset_manifest.json</c> next to the bundle so runtime and
	/// validators can check asset membership without a LoadAllAssets decode.
	/// </summary>
	public static class Homm3UiPortraitBundleBuild
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

		const string BundleName = "homm3_ui_portraits";
		const string AssetRoot = "Assets/Homm3UiPortraits";
		const string AssetPrefix = "ui_portrait_";
		const string ManifestSchema = "homm3_ui_bundle_asset_manifest.v1";
		static readonly Regex UnitPortraitFileRegex = new Regex(
			@"^h3_[a-z0-9_]+\.png$",
			RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
		static readonly Regex HeroPortraitFileRegex = new Regex(
			@"^homm3_.+_hero_\d+\.png$",
			RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

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
			var unitPortraitDir = ResolveArg("-unitPortraitDir", null);
			var heroPortraitDir = ResolveArg("-heroPortraitDir", null);
			var outputPath = ResolveArg("-outputPath", Path.Combine("tools", "homm3_import", "build_out"));
			if (string.IsNullOrWhiteSpace(unitPortraitDir) || !Directory.Exists(unitPortraitDir))
				throw new InvalidOperationException(
					"Homm3UiPortraitBundleBuild requires -unitPortraitDir pointing at homm3_portraits unit PNGs.");
			if (string.IsNullOrWhiteSpace(heroPortraitDir) || !Directory.Exists(heroPortraitDir))
				throw new InvalidOperationException(
					"Homm3UiPortraitBundleBuild requires -heroPortraitDir pointing at homm3_hero_portraits_upscaled PNGs.");
			Build(unitPortraitDir, heroPortraitDir, outputPath);
		}

		static void Build(string unitPortraitDir, string heroPortraitDir, string outputPath)
		{
			EnsureFolder(AssetRoot);
			CleanStaleAssets();

			var assetPaths = new List<string>();
			var sourceByAssetName = new Dictionary<string, string>(StringComparer.Ordinal);
			var unitCount = CollectPortraits(unitPortraitDir, UnitPortraitFileRegex, assetPaths, sourceByAssetName);
			var heroCount = CollectPortraits(heroPortraitDir, HeroPortraitFileRegex, assetPaths, sourceByAssetName);

			if (unitCount == 0)
				throw new InvalidOperationException(
					"No h3_*.png unit portraits found under " + unitPortraitDir);
			if (heroCount == 0)
				throw new InvalidOperationException(
					"No homm3_*_hero_*.png hero portraits found under " + heroPortraitDir);

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
				importer.filterMode = FilterMode.Bilinear;
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
				throw new InvalidOperationException("Expected UI portrait bundle was not produced: " + bundlePath);

			WriteAssetManifest(absoluteOutput, sourceByAssetName);

			Debug.Log(
				"Homm3UiPortraitBundleBuild: built "
				+ bundlePath
				+ " with "
				+ assetPaths.Count
				+ " sprite(s) (unit="
				+ unitCount
				+ ", hero="
				+ heroCount
				+ ").");
		}

		static int CollectPortraits(
			string sourceDir,
			Regex fileRegex,
			List<string> assetPaths,
			Dictionary<string, string> sourceByAssetName)
		{
			var count = 0;
			foreach (var pngPath in Directory.GetFiles(sourceDir, "*.png"))
			{
				var fileName = Path.GetFileName(pngPath);
				if (!fileRegex.IsMatch(fileName))
					throw new InvalidOperationException(
						"Unexpected PNG file name under " + sourceDir + ": " + fileName
						+ " (expected pattern " + fileRegex + "). Refusing to bundle unscoped art.");

				var spriteName = AssetPrefix + Path.GetFileNameWithoutExtension(fileName).ToLowerInvariant();
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
				count++;
			}
			return count;
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
			Debug.Log("Homm3UiPortraitBundleBuild: wrote asset manifest " + manifestPath);
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
