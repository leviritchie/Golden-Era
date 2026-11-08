// Canonical copy for git. Deploy to: <UnityProject>/Assets/Editor/Homm3BattleSoundPrefabsBuild.cs
// Batch: -executeMethod OldenEra.Homm3Import.Homm3BattleSoundPrefabsBuild.RebuildFromBatch -homm3UnitSid <sid>
// Run after stage_homm3_unit_audio.py (WAVs under homm3_lab/<sid>/sounds/) and before BuildCustomUnitBundles.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	public static class Homm3BattleSoundPrefabsBuild
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

		[Serializable]
		class Homm3UnitBundleManifestJson
		{
			public Homm3UnitBundleEntryJson[] units;
		}

		[Serializable]
		class Homm3UnitBundleEntryJson
		{
			public string unitSid;
		}

		static string ResolveUnitSidFromCommandLine()
		{
			var args = UnityQueueArgs();
			for (var i = 0; i < args.Length - 1; i++)
			{
				if (args[i] == "-homm3UnitSid")
					return args[i + 1];
			}

			return null;
		}

		public static void RebuildFromBatch()
		{
			var sid = ResolveUnitSidFromCommandLine();
			if (string.IsNullOrEmpty(sid))
				throw new InvalidOperationException("Homm3BattleSoundPrefabsBuild: requires -homm3UnitSid");
			RebuildCore(sid);
		}

		public static void RebuildAllFromManifest()
		{
			try
			{
				var args = UnityQueueArgs();
				string manifestFs = null;
				string unitListFs = null;
				for (var i = 0; i < args.Length - 1; i++)
				{
					if (args[i] == "-manifestPath")
						manifestFs = args[i + 1];
					if (args[i] == "-homm3UnitListPath")
						unitListFs = args[i + 1];
				}

				if (string.IsNullOrWhiteSpace(manifestFs))
					throw new InvalidOperationException("Homm3BattleSoundPrefabsBuild: pass -manifestPath for RebuildAllFromManifest.");

				var manifestPath = Path.GetFullPath(manifestFs);
				var manifest = JsonUtility.FromJson<Homm3UnitBundleManifestJson>(File.ReadAllText(manifestPath));
				if (manifest?.units == null || manifest.units.Length == 0)
					throw new InvalidOperationException("Homm3BattleSoundPrefabsBuild: manifest has no units: " + manifestPath);

				HashSet<string> unitFilter = null;
				if (!string.IsNullOrWhiteSpace(unitListFs))
				{
					unitFilter = new HashSet<string>(
						File.ReadAllLines(Path.GetFullPath(unitListFs))
							.Select(x => x.Trim())
							.Where(x => x.Length > 0 && !x.StartsWith("#", StringComparison.Ordinal)),
						StringComparer.OrdinalIgnoreCase);
				}

				var processed = 0;
				foreach (var entry in manifest.units)
				{
					var sid = entry?.unitSid?.Trim();
					if (string.IsNullOrEmpty(sid))
						continue;
					if (unitFilter != null && !unitFilter.Contains(sid))
						continue;
					RebuildCore(sid);
					processed++;
				}

				if (processed == 0)
					throw new InvalidOperationException("Homm3BattleSoundPrefabsBuild: processed zero units from manifest.");
				Debug.Log("Homm3BattleSoundPrefabsBuild: RebuildAllFromManifest completed for " + processed + " unit(s).");
			}
			catch (Exception ex)
			{
				Debug.LogError("Homm3BattleSoundPrefabsBuild failed: " + ex);
				UnityQueueExit(1);
				throw;
			}
		}

		static void RebuildCore(string unitSid)
		{
			var soundsFolder = "Assets/CustomUnits/homm3_lab/" + unitSid + "/sounds";
			if (!AssetDatabase.IsValidFolder(soundsFolder))
			{
				Debug.Log("Homm3BattleSoundPrefabsBuild: no folder " + soundsFolder + " — skip.");
				return;
			}

			AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

			var guids = AssetDatabase.FindAssets("", new[] { soundsFolder });
			var n = 0;
			foreach (var guid in guids)
			{
				var path = AssetDatabase.GUIDToAssetPath(guid);
				if (!path.EndsWith(".wav", StringComparison.OrdinalIgnoreCase)
				    && !path.EndsWith(".ogg", StringComparison.OrdinalIgnoreCase))
					continue;

				var clip = AssetDatabase.LoadAssetAtPath<AudioClip>(path);
				if (clip == null)
				{
					Debug.LogWarning("Homm3BattleSoundPrefabsBuild: could not load AudioClip at " + path);
					continue;
				}

				var stem = Path.GetFileNameWithoutExtension(path);
				if (string.IsNullOrEmpty(stem)
				    || !stem.StartsWith("HOMM3_", StringComparison.OrdinalIgnoreCase))
					continue;

				var prefabPath = soundsFolder + "/" + stem + ".prefab";
				var go = new GameObject(stem);
				try
				{
					var src = go.AddComponent<AudioSource>();
					src.playOnAwake = false;
					src.loop = false;
					src.clip = clip;
					src.spatialBlend = 1f;
					src.rolloffMode = AudioRolloffMode.Logarithmic;
					src.minDistance = 1f;
					src.maxDistance = 500f;

					PrefabUtility.SaveAsPrefabAsset(go, prefabPath);
					n++;
				}
				finally
				{
					UnityEngine.Object.DestroyImmediate(go);
				}
			}

			AssetDatabase.SaveAssets();
			AssetDatabase.Refresh();
			Debug.Log("Homm3BattleSoundPrefabsBuild: wrote " + n + " sound prefab(s) under " + soundsFolder + ".");
		}
	}
}
