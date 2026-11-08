using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	public static class Homm3DumpBundleAssetNames
	{
		public static void Run()
		{
			string bundlePath = null;
			string outPath = null;
			var args = Environment.GetCommandLineArgs();
			for (var i = 0; i < args.Length - 1; i++)
			{
				if (args[i] == "-bundlePath")
					bundlePath = args[i + 1];
				if (args[i] == "-dumpPath")
					outPath = args[i + 1];
			}
			if (string.IsNullOrEmpty(bundlePath) || !File.Exists(bundlePath))
				throw new InvalidOperationException("Homm3DumpBundleAssetNames: -bundlePath missing: " + bundlePath);
			if (string.IsNullOrEmpty(outPath))
				throw new InvalidOperationException("Homm3DumpBundleAssetNames: -dumpPath required");

			var bundle = AssetBundle.LoadFromFile(bundlePath);
			if (bundle == null)
				throw new InvalidOperationException("bundle load failed: " + bundlePath);
			try
			{
				var names = bundle.GetAllAssetNames();
				Directory.CreateDirectory(Path.GetDirectoryName(outPath));
				File.WriteAllLines(outPath, names);
				Debug.Log("Homm3DumpBundleAssetNames wrote " + names.Length + " names to " + outPath);
			}
			finally
			{
				bundle.Unload(false);
			}
		}
	}
}
