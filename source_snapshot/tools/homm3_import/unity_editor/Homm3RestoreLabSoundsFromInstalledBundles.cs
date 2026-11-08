using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	/// <summary>
	/// Restore homm3_lab/&lt;sid&gt;/sounds prefabs + clips from installed Golden Era
	/// bundles. The Unity CustomUnits tree was missing; sounds still exist as root
	/// assets in the live billboard bundles.
	/// Batch: -executeMethod OldenEra.Homm3Import.Homm3RestoreLabSoundsFromInstalledBundles.Run
	///   -installedBundleRoot &lt;dir&gt; -skinnedManifest &lt;json&gt; -soundRestoreReport &lt;json&gt;
	/// </summary>
	public static class Homm3RestoreLabSoundsFromInstalledBundles
	{
		[Serializable]
		class ManifestUnit
		{
			public string unitSid;
			public string bundleName;
		}

		[Serializable]
		class Manifest
		{
			public ManifestUnit[] units;
		}

		public static void Run()
		{
			string bundleRoot = null;
			string manifestPath = null;
			string reportPath = null;
			var args = Environment.GetCommandLineArgs();
			for (var i = 0; i < args.Length - 1; i++)
			{
				if (args[i] == "-installedBundleRoot")
					bundleRoot = args[i + 1];
				if (args[i] == "-skinnedManifest")
					manifestPath = args[i + 1];
				if (args[i] == "-soundRestoreReport")
					reportPath = args[i + 1];
			}
			if (string.IsNullOrEmpty(bundleRoot) || !Directory.Exists(bundleRoot))
				throw new InvalidOperationException("missing -installedBundleRoot: " + bundleRoot);
			if (string.IsNullOrEmpty(manifestPath) || !File.Exists(manifestPath))
				throw new InvalidOperationException("missing -skinnedManifest: " + manifestPath);

			var manifest = JsonUtility.FromJson<Manifest>(File.ReadAllText(manifestPath));
			if (manifest == null || manifest.units == null || manifest.units.Length == 0)
				throw new InvalidOperationException("skinned manifest has no units[]");

			var report = new StringBuilder();
			report.AppendLine("{");
			report.AppendLine("  \"units\": [");
			for (var u = 0; u < manifest.units.Length; u++)
			{
				var unit = manifest.units[u];
				var row = RestoreOne(bundleRoot, unit.unitSid, unit.bundleName);
				report.Append("    ").Append(row);
				if (u + 1 < manifest.units.Length)
					report.Append(',');
				report.AppendLine();
			}
			report.AppendLine("  ]");
			report.AppendLine("}");
			if (!string.IsNullOrEmpty(reportPath))
			{
				Directory.CreateDirectory(Path.GetDirectoryName(reportPath));
				File.WriteAllText(reportPath, report.ToString());
			}
			AssetDatabase.SaveAssets();
			AssetDatabase.Refresh();
			Debug.Log("Homm3RestoreLabSoundsFromInstalledBundles finished " + manifest.units.Length + " unit(s).");
		}

		static string RestoreOne(string bundleRoot, string unitSid, string bundleName)
		{
			if (string.IsNullOrEmpty(unitSid) || string.IsNullOrEmpty(bundleName))
				return JsonRow(unitSid, bundleName, 0, "missing sid or bundleName");
			var bundlePath = Path.Combine(bundleRoot, bundleName);
			if (!File.Exists(bundlePath))
				return JsonRow(unitSid, bundleName, 0, "installed bundle missing");

			var bundle = AssetBundle.LoadFromFile(bundlePath);
			if (bundle == null)
				return JsonRow(unitSid, bundleName, 0, "bundle load failed");
			try
			{
				var folder = "Assets/CustomUnits/homm3_lab/" + unitSid + "/sounds";
				EnsureFolder(folder);
				var saved = 0;
				foreach (var assetName in bundle.GetAllAssetNames())
				{
					if (assetName.IndexOf("/sounds/", StringComparison.OrdinalIgnoreCase) < 0)
						continue;
					if (!assetName.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
						continue;
					var prefab = bundle.LoadAsset<GameObject>(assetName);
					if (prefab == null)
						throw new InvalidOperationException(unitSid + " failed to load sound prefab " + assetName);
					saved += SaveSoundPrefab(prefab, folder, Path.GetFileName(assetName));
				}
				if (saved == 0)
					return JsonRow(unitSid, bundleName, 0, "bundle has no sounds/*.prefab roots");
				Debug.Log("Restored " + saved + " sound prefabs for " + unitSid);
				return JsonRow(unitSid, bundleName, saved, null);
			}
			finally
			{
				bundle.Unload(true);
			}
		}

		static int SaveSoundPrefab(GameObject prefab, string folder, string fileName)
		{
			var instance = UnityEngine.Object.Instantiate(prefab);
			instance.name = Path.GetFileNameWithoutExtension(fileName);
			var sources = instance.GetComponentsInChildren<AudioSource>(true);
			if (sources.Length == 0)
			{
				UnityEngine.Object.DestroyImmediate(instance);
				throw new InvalidOperationException(folder + "/" + fileName + " has no AudioSource");
			}
			foreach (var source in sources)
			{
				if (source.clip == null)
					throw new InvalidOperationException(folder + "/" + fileName + " AudioSource.clip is null");
				var clipName = Sanitize(source.clip.name);
				var wavPath = folder + "/" + clipName + ".wav";
				WriteWav(ToAbsolute(wavPath), source.clip);
				AssetDatabase.ImportAsset(wavPath, ImportAssetOptions.ForceSynchronousImport);
				var imported = AssetDatabase.LoadAssetAtPath<AudioClip>(wavPath);
				if (imported == null)
					throw new InvalidOperationException("imported clip missing: " + wavPath);
				source.clip = imported;
			}
			var prefabPath = folder + "/" + fileName;
			if (AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath) != null)
				AssetDatabase.DeleteAsset(prefabPath);
			bool ok;
			PrefabUtility.SaveAsPrefabAsset(instance, prefabPath, out ok);
			UnityEngine.Object.DestroyImmediate(instance);
			if (!ok)
				throw new InvalidOperationException("failed to save " + prefabPath);
			return 1;
		}

		static void WriteWav(string absolutePath, AudioClip clip)
		{
			var samples = new float[clip.samples * clip.channels];
			if (!clip.GetData(samples, 0))
				throw new InvalidOperationException("AudioClip.GetData failed for " + clip.name);
			Directory.CreateDirectory(Path.GetDirectoryName(absolutePath));
			using (var stream = new FileStream(absolutePath, FileMode.Create, FileAccess.Write))
			using (var writer = new BinaryWriter(stream))
			{
				const int headerSize = 36;
				var dataLength = samples.Length * 2;
				writer.Write(Encoding.ASCII.GetBytes("RIFF"));
				writer.Write(headerSize + dataLength);
				writer.Write(Encoding.ASCII.GetBytes("WAVE"));
				writer.Write(Encoding.ASCII.GetBytes("fmt "));
				writer.Write(16);
				writer.Write((short)1);
				writer.Write((short)clip.channels);
				writer.Write(clip.frequency);
				writer.Write(clip.frequency * clip.channels * 2);
				writer.Write((short)(clip.channels * 2));
				writer.Write((short)16);
				writer.Write(Encoding.ASCII.GetBytes("data"));
				writer.Write(dataLength);
				for (var i = 0; i < samples.Length; i++)
				{
					var clamped = Mathf.Clamp(samples[i], -1f, 1f);
					writer.Write((short)Mathf.RoundToInt(clamped * short.MaxValue));
				}
			}
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

		static string ToAbsolute(string assetPath)
		{
			return Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), assetPath));
		}

		static string Sanitize(string name)
		{
			var chars = Path.GetInvalidFileNameChars();
			var builder = new StringBuilder(name.Length);
			foreach (var ch in name)
				builder.Append(Array.IndexOf(chars, ch) >= 0 ? '_' : ch);
			return builder.Length == 0 ? "clip" : builder.ToString();
		}

		static string JsonRow(string sid, string bundle, int count, string error)
		{
			var escapedError = error == null ? "null" : "\"" + error.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
			return "{\"labSid\":\"" + sid + "\",\"bundleName\":\"" + bundle + "\",\"soundPrefabs\":" + count + ",\"error\":" + escapedError + "}";
		}
	}
}
