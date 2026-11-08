using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	public static class Homm2ShadeObjectClassShaderBundleBuild
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

		const string ShaderPath = "Assets/Shaders/Homm2ShadeObjectClass.shader";
		const string ShaderName = "OldenEra/Homm2/ShadeObjectClass";
		const string BundleName = "homm2_shade_object_class";

		public static void BuildFromBatch()
		{
			var outputPath = ResolveArg("-outputPath", Path.Combine("tools", "homm3_import", "build_out"));
			Build(outputPath);
		}

		static void Build(string outputPath)
		{
			var shader = Shader.Find(ShaderName);
			if (shader == null)
				throw new InvalidOperationException("Shader " + ShaderName + " missing at " + ShaderPath + ".");

			var importer = AssetImporter.GetAtPath(ShaderPath);
			if (importer == null)
				throw new InvalidOperationException("AssetImporter missing for " + ShaderPath + ".");
			importer.assetBundleName = BundleName;
			AssetDatabase.SaveAssets();

			var absoluteOutput = Path.GetFullPath(outputPath);
			Directory.CreateDirectory(absoluteOutput);
			BuildPipeline.BuildAssetBundles(
				absoluteOutput,
				BuildAssetBundleOptions.ChunkBasedCompression,
				BuildTarget.StandaloneWindows64);

			var bundlePath = Path.Combine(absoluteOutput, BundleName);
			if (!File.Exists(bundlePath))
				throw new InvalidOperationException("Expected shader bundle was not produced: " + bundlePath);
			Debug.Log("Homm2ShadeObjectClassShaderBundleBuild: built " + bundlePath);
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
