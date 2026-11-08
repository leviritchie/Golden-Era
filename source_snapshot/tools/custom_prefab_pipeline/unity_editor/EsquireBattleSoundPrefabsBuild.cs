// Canonical copy for git. Deploy to: <UnityProject>/Assets/Editor/EsquireBattleSoundPrefabsBuild.cs
// Batch: -executeMethod OldenEra.CustomUnitBuilder.EsquireBattleSoundPrefabsBuild.RebuildFromBatch
// Run after stage_esquire_homm3_audio.py (or any WAVs under sounds/) and before BuildCustomUnitBundles.

using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace OldenEra.CustomUnitBuilder
{
	public static class EsquireBattleSoundPrefabsBuild
	{
		const string SoundsFolder = "Assets/CustomUnits/esquire/sounds";

		[MenuItem("Olden Era/Custom Units/Rebuild Esquire Battle Sound Prefabs (from WAVs)")]
		public static void RebuildFromMenu()
		{
			RebuildCore();
		}

		/// <summary>Headless: one <c>GameObject</c> + <c>AudioSource</c> per <c>ESQUIRE_*.wav</c> (or <c>.ogg</c>), named like the clip stem.</summary>
		public static void RebuildFromBatch()
		{
			RebuildCore();
		}

		static void RebuildCore()
		{
			if (!AssetDatabase.IsValidFolder(SoundsFolder))
			{
				Debug.Log("EsquireBattleSoundPrefabsBuild: no folder " + SoundsFolder + " — skip.");
				return;
			}

			AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

			var guids = AssetDatabase.FindAssets("", new[] { SoundsFolder });
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
					Debug.LogWarning("EsquireBattleSoundPrefabsBuild: could not load AudioClip at " + path);
					continue;
				}

				var stem = Path.GetFileNameWithoutExtension(path);
				if (string.IsNullOrEmpty(stem)
				    || !stem.StartsWith("ESQUIRE_", StringComparison.OrdinalIgnoreCase))
					continue;

				var prefabPath = SoundsFolder + "/" + stem + ".prefab";
				var go = new GameObject(stem);
				try
				{
					var src = go.AddComponent<AudioSource>();
					src.playOnAwake = false;
					src.loop = false;
					src.clip = clip;
					// Match typical world SFX; tune in Unity if a reference mixer/preset is added later.
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
			Debug.Log("EsquireBattleSoundPrefabsBuild: wrote " + n + " sound prefab(s) under " + SoundsFolder + ".");
		}
	}
}
