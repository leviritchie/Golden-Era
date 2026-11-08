using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	public static class Homm3ArrayUpscaleShaderBundleBuild
	{
		const string ShaderPath = "Assets/Shaders/Homm3BillboardArrayUpscale.shader";
		const string MaterialPath = "Assets/Shaders/Homm3BillboardArrayUpscale.mat";
		const string ShaderName = "OldenEra/Homm3/BillboardArrayUpscale";
		const string BundleName = "homm3_array_upscale_shader";

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

			var material = AssetDatabase.LoadAssetAtPath<Material>(MaterialPath);
			if (material == null)
			{
				material = new Material(shader)
				{
					name = "homm3_array_upscale_material"
				};
				material.SetFloat("_ArraySliceSize", 2048f);
				material.SetFloat("_Homm3UpscaleStrength", 0.65f);
				material.SetVector("_Homm3UpscaleSourceTexelSize", new Vector4(1f / 512f, 1f / 512f, 512f, 512f));
				AssetDatabase.CreateAsset(material, MaterialPath);
			}
			else
			{
				material.shader = shader;
				material.SetFloat("_Homm3UpscaleStrength", 0.65f);
			}

			AssetImporter.GetAtPath(ShaderPath).assetBundleName = BundleName;
			AssetImporter.GetAtPath(MaterialPath).assetBundleName = BundleName;
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
			Debug.Log("Homm3ArrayUpscaleShaderBundleBuild: built " + bundlePath);
		}

		static string ResolveArg(string name, string fallback)
		{
			var args = Environment.GetCommandLineArgs();
			for (var i = 0; i + 1 < args.Length; i++)
			{
				if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase))
					return args[i + 1];
			}
			return fallback;
		}
	}
}
