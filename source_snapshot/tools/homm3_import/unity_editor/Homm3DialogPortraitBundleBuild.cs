using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	/// <summary>
	/// Builds <c>homm3_dialog_portraits</c> AssetBundle with Sprites named
	/// <c>dialogue_hero_homm3_&lt;faction&gt;_&lt;n&gt;</c> for cko dialog-icon injection.
	/// </summary>
	public static class Homm3DialogPortraitBundleBuild
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

		const string BundleName = "homm3_dialog_portraits";
		const string AssetRoot = "Assets/Homm3DialogPortraits";
		static readonly Regex PortraitFileRegex = new Regex(
			@"^homm3_(?<faction>.+)_hero_(?<n>\d+)\.png$",
			RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

		public static void BuildFromBatch()
		{
			var portraitDir = ResolveArg("-portraitDir", null);
			var outputPath = ResolveArg("-outputPath", Path.Combine("tools", "homm3_import", "build_out"));
			if (string.IsNullOrWhiteSpace(portraitDir) || !Directory.Exists(portraitDir))
				throw new InvalidOperationException(
					"Homm3DialogPortraitBundleBuild requires -portraitDir pointing at hero portrait PNGs.");
			Build(portraitDir, outputPath);
		}

		static void Build(string portraitDir, string outputPath)
		{
			EnsureFolder(AssetRoot);
			var assetPaths = new List<string>();
			foreach (var pngPath in Directory.GetFiles(portraitDir, "homm3_*_hero_*.png"))
			{
				var fileName = Path.GetFileName(pngPath);
				var match = PortraitFileRegex.Match(fileName);
				if (!match.Success)
					continue;

				var faction = match.Groups["faction"].Value.Trim().ToLowerInvariant();
				var number = match.Groups["n"].Value;
				var spriteName = "dialogue_hero_homm3_" + faction + "_" + number;
				var destRelative = AssetRoot + "/" + spriteName + ".png";
				var destAbsolute = Path.GetFullPath(destRelative);
				Directory.CreateDirectory(Path.GetDirectoryName(destAbsolute) ?? ".");
				File.Copy(pngPath, destAbsolute, overwrite: true);
				assetPaths.Add(destRelative);
			}

			if (assetPaths.Count == 0)
				throw new InvalidOperationException(
					"No homm3_*_hero_*.png portraits found under " + portraitDir);

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
				throw new InvalidOperationException("Expected dialog portrait bundle was not produced: " + bundlePath);

			Debug.Log(
				"Homm3DialogPortraitBundleBuild: built "
				+ bundlePath
				+ " with "
				+ assetPaths.Count
				+ " sprite(s).");
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
