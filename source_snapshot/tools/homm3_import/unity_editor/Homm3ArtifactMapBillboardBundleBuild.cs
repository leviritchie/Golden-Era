using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	/// <summary>
	/// Builds <c>homm3_artifact_map_billboards</c> AssetBundle with Sprites named
	/// <c>artifact_map_billboard_&lt;sid&gt;</c> from cropped AVA map frames under
	/// <c>homm3_runtime_assets/artifacts/map/homm3_artifact_*/00_00.png</c>.
	/// Also writes <c>&lt;bundle&gt;.asset_manifest.json</c> next to the bundle so runtime and
	/// validators can check asset membership without a LoadAllAssets decode.
	/// </summary>
	public static class Homm3ArtifactMapBillboardBundleBuild
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

		const string BundleName = "homm3_artifact_map_billboards";
		const string AssetRoot = "Assets/Homm3ArtifactMapBillboards";
		const string AssetPrefix = "artifact_map_billboard_";
		const string ManifestSchema = "homm3_ui_bundle_asset_manifest.v1";
		static readonly Regex SidSanitizeRegex = new Regex(
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
			var artifactMapDir = ResolveArg("-artifactMapDir", null);
			var outputPath = ResolveArg("-outputPath", Path.Combine("tools", "homm3_import", "build_out"));
			if (string.IsNullOrWhiteSpace(artifactMapDir) || !Directory.Exists(artifactMapDir))
				throw new InvalidOperationException(
					"Homm3ArtifactMapBillboardBundleBuild requires -artifactMapDir pointing at "
					+ "homm3_runtime_assets/artifacts/map.");
			Build(artifactMapDir, outputPath);
		}

		static void Build(string artifactMapDir, string outputPath)
		{
			EnsureFolder(AssetRoot);
			CleanStaleAssets();

			var assetPaths = new List<string>();
			var sourceByAssetName = new Dictionary<string, string>(StringComparer.Ordinal);
			var mapRoot = Path.GetFullPath(artifactMapDir);
			foreach (var sidDir in Directory.GetDirectories(mapRoot, "homm3_artifact_*"))
			{
				var pngPath = Path.Combine(sidDir, "00_00.png");
				if (!File.Exists(pngPath))
					continue;

				var sid = Path.GetFileName(sidDir);
				var spriteName = AssetPrefix + SanitizeSid(sid);
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
					"No homm3_artifact_*/00_00.png frames found under " + artifactMapDir);

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
				throw new InvalidOperationException(
					"Expected artifact map billboard bundle was not produced: " + bundlePath);

			WriteAssetManifest(absoluteOutput, sourceByAssetName);

			Debug.Log(
				"Homm3ArtifactMapBillboardBundleBuild: built "
				+ bundlePath
				+ " with "
				+ assetPaths.Count
				+ " sprite(s).");
		}

		static string SanitizeSid(string sid)
		{
			if (string.IsNullOrWhiteSpace(sid))
				throw new InvalidOperationException("Artifact map frame SID is empty.");
			var sanitized = SidSanitizeRegex.Replace(sid.Trim().ToLowerInvariant(), "_");
			if (string.IsNullOrWhiteSpace(sanitized))
				throw new InvalidOperationException("Artifact map frame SID sanitized empty: " + sid);
			return sanitized;
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
			Debug.Log("Homm3ArtifactMapBillboardBundleBuild: wrote asset manifest " + manifestPath);
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
