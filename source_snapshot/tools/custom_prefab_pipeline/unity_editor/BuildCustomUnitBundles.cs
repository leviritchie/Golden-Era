// Canonical copy for git. Deploy to: <UnityProject>/Assets/Editor/BuildCustomUnitBundles.cs
// Batch: -executeMethod OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest
//         -manifestPath <path> -outputPath <path>

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace OldenEra.CustomUnitBuilder
{
	public static class BuildCustomUnitBundles
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
		class Manifest
		{
			public int formatVersion;
			public UnitEntry[] units;
		}

		[Serializable]
		class UnitEntry
		{
			public string unitSid;
			public string meshKey;
			public string mapMeshKey;
			public string battlePrefabAsset;
			public string mapPrefabAsset;
			public string battlePresentationLane;
			public string bundleName;
		}

		public static void BuildFromManifest()
		{
			string manifestPath = null;
			string outputPath = null;
			string unitListPath = null;
			var args = UnityQueueArgs();
			for (var i = 0; i < args.Length - 1; i++)
			{
				if (args[i] == "-manifestPath")
					manifestPath = args[i + 1];
				if (args[i] == "-outputPath")
					outputPath = args[i + 1];
				if (args[i] == "-homm3UnitListPath")
					unitListPath = args[i + 1];
			}

			if (string.IsNullOrEmpty(manifestPath) || string.IsNullOrEmpty(outputPath))
				throw new InvalidOperationException("BuildCustomUnitBundles: requires -manifestPath and -outputPath");

			var json = File.ReadAllText(manifestPath);
			var m = JsonUtility.FromJson<Manifest>(json);
			if (m?.units == null || m.units.Length == 0)
				throw new InvalidOperationException("BuildCustomUnitBundles: manifest has no units[]");

			HashSet<string> unitFilter = null;
			if (!string.IsNullOrWhiteSpace(unitListPath))
			{
				unitFilter = new HashSet<string>(
					File.ReadAllLines(Path.GetFullPath(unitListPath))
						.Select(x => x.Trim())
						.Where(x => x.Length > 0 && !x.StartsWith("#", StringComparison.Ordinal)),
					StringComparer.OrdinalIgnoreCase);
			}

			Directory.CreateDirectory(outputPath);
			AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

			var builds = new List<AssetBundleBuild>();
			foreach (var u in m.units)
			{
				if (unitFilter != null && !unitFilter.Contains(u.unitSid))
					continue;
				if (string.IsNullOrEmpty(u.bundleName))
					continue;

				var assetPaths = new List<string>();
				AddIfPresent(assetPaths, u.battlePrefabAsset);
				AddIfPresent(assetPaths, u.mapPrefabAsset);
				AddSoundsForUnit(assetPaths, u.unitSid);
				AddProjectilesForUnit(assetPaths, u.unitSid);
				var skinnedBattle = IsSkinnedBattleLane(u);
				var skinnedMap = IsSkinnedMapPrefab(u);
				if (skinnedBattle)
					AddSkinnedBattleAssets(assetPaths, u.battlePrefabAsset);
				var battleArray = skinnedBattle ? false : AddHomm3ArrayBattleAssets(assetPaths, u.unitSid);
				if (!skinnedMap)
					AddHomm3ArrayMapAssets(assetPaths, u.unitSid);
				// Battle Texture2DArray skips per-frame battle mats. Map Texture2DArray skips map_frame_*.
				// Do NOT skip map_frame_* merely because battle arrays or MapIdle controller/clips were
				// added — runtime CountMapFrameAssetNamesInBundle only sees explicit root asset names
				// (dependency-only materials are invisible and break adventure-map billboards).
				if (!skinnedBattle && !battleArray)
					AddGeneratedHomm3FrameMaterials(assetPaths, u.unitSid, includeBattle: true, includeMap: false);
				if (!skinnedMap && !HasMapArrayMaterial(assetPaths, u.unitSid))
					AddGeneratedHomm3FrameMaterials(assetPaths, u.unitSid, includeBattle: false, includeMap: true);
				if (!skinnedMap)
				{
					ValidateHomm3MapPrefabMaterial(u);
					ValidateHomm3MapFrameAssetsExplicit(assetPaths, u);
				}

				if (assetPaths.Count == 0)
				{
					Debug.LogWarning("BuildCustomUnitBundles: no assets for bundle " + u.bundleName);
					continue;
				}

				// No importer.assetBundleName labels: BuildAssetBundles below takes this explicit AssetBundleBuild map,
				// which ignores labels, so writing them only rewrote .meta files.
				builds.Add(new AssetBundleBuild
				{
					assetBundleName = u.bundleName,
					assetNames = assetPaths.ToArray()
				});
			}

			AssetDatabase.SaveAssets();
			AssetDatabase.RemoveUnusedAssetBundleNames();

			if (builds.Count == 0)
				throw new InvalidOperationException("BuildCustomUnitBundles: nothing to build");

			var bundleSw = System.Diagnostics.Stopwatch.StartNew();
			var manifestOut = BuildPipeline.BuildAssetBundles(
				outputPath,
				builds.ToArray(),
				BuildAssetBundleOptions.ChunkBasedCompression,
				EditorUserBuildSettings.activeBuildTarget);
			bundleSw.Stop();

			if (manifestOut == null)
				throw new InvalidOperationException("BuildCustomUnitBundles: BuildPipeline.BuildAssetBundles returned null");

			long totalBundleBytes = 0;
			foreach (var build in builds)
			{
				var bundlePath = Path.Combine(outputPath, build.assetBundleName);
				if (!File.Exists(bundlePath))
					continue;
				var bytes = new FileInfo(bundlePath).Length;
				totalBundleBytes += bytes;
				Debug.Log(
					"HOMM3_BUNDLE_BUILD_PROFILE"
					+ " bundle="
					+ build.assetBundleName
					+ " assets="
					+ build.assetNames.Length
					+ " bytes="
					+ bytes);
			}

			WriteReport(outputPath, m);
			Debug.Log(
				"HOMM3_BUNDLE_BUILD_PROFILE"
				+ " totalBundles="
				+ builds.Count
				+ " buildPipelineMs="
				+ bundleSw.ElapsedMilliseconds
				+ " totalBytes="
				+ totalBundleBytes);
			Debug.Log("BuildCustomUnitBundles: wrote " + builds.Count + " bundle(s) to " + outputPath);
		}

		static void AddIfPresent(List<string> dest, string assetPath)
		{
			if (string.IsNullOrEmpty(assetPath))
				return;
			if (AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(assetPath) == null)
			{
				Debug.LogWarning("BuildCustomUnitBundles: missing asset " + assetPath);
				return;
			}
			if (!dest.Contains(assetPath))
				dest.Add(assetPath);
		}

		static void AddRequiredSkinnedAsset(List<string> dest, string assetPath)
		{
			if (string.IsNullOrEmpty(assetPath))
				throw new InvalidOperationException("BuildCustomUnitBundles: skinned-lane asset path is empty.");
			if (AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(assetPath) == null)
				throw new InvalidOperationException("BuildCustomUnitBundles: skinned-lane missing required asset " + assetPath);
			if (!dest.Contains(assetPath))
				dest.Add(assetPath);
		}

		static bool IsSkinnedBattleLane(UnitEntry unit)
		{
			return unit != null
				&& string.Equals(unit.battlePresentationLane, "skinned_mesh", StringComparison.OrdinalIgnoreCase);
		}

		static bool IsSkinnedMapPrefab(UnitEntry unit)
		{
			if (unit == null || string.IsNullOrEmpty(unit.mapPrefabAsset))
				return false;
			var mapPrefab = unit.mapPrefabAsset.Replace('\\', '/');
			if (mapPrefab.IndexOf("/OwnedSkinned/", StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
			return IsSkinnedBattleLane(unit)
				&& !string.IsNullOrEmpty(unit.battlePrefabAsset)
				&& string.Equals(
					mapPrefab,
					unit.battlePrefabAsset.Replace('\\', '/'),
					StringComparison.OrdinalIgnoreCase);
		}

		static string FirstExistingSkinnedAsset(string root, params string[] names)
		{
			foreach (var name in names)
			{
				var path = root + "/" + name;
				if (AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(path) != null)
					return path;
			}
			return null;
		}

		static bool AddSkinnedBattleAssets(List<string> dest, string prefabPath)
		{
			if (string.IsNullOrEmpty(prefabPath))
				return false;
			var root = prefabPath.Substring(0, prefabPath.LastIndexOf('/'));
			var before = dest.Count;
			var mat = FirstExistingSkinnedAsset(root, "owned_skinned.mat", "crusader_owned_skinned.mat");
			// .png: def_retarget units ship a lossless albedo (the oceanid uvAtlas); the runtime loads jpg, then png.
			var albedo = FirstExistingSkinnedAsset(root, "owned_skinned_basecolor.jpg", "crusader_owned_skinned_basecolor.jpg", "owned_skinned_basecolor.png");
			var normal = FirstExistingSkinnedAsset(root, "owned_skinned_normal.png", "crusader_owned_skinned_normal.png");
			var metallic = FirstExistingSkinnedAsset(root, "owned_skinned_metallicgloss.png", "crusader_owned_skinned_metallicgloss.png");
			if (mat == null || albedo == null || normal == null || metallic == null)
				throw new InvalidOperationException("BuildCustomUnitBundles: skinned-lane missing mat/albedo/normal/metallic-gloss under " + root);
			AddRequiredSkinnedAsset(dest, mat);
			AddRequiredSkinnedAsset(dest, albedo);
			AddRequiredSkinnedAsset(dest, normal);
			AddRequiredSkinnedAsset(dest, metallic);
			AddIfPresent(dest, root + "/Source/master.glb");
			AddIfPresent(dest, root + "/Source/crusader_master_rigid_components.glb");
			var unitController = FirstExistingSkinnedAsset(root + "/Reference", "StockEsquireBattle.controller");
			if (unitController == null)
				throw new InvalidOperationException("BuildCustomUnitBundles: skinned-lane missing per-unit StockEsquireBattle.controller under " + root + "/Reference");
			AddRequiredSkinnedAsset(dest, unitController);
			var overridePath = FirstExistingSkinnedAsset(root, "owned_skinned.overrideController", "crusader_owned_skinned.overrideController");
			if (overridePath == null)
				throw new InvalidOperationException("BuildCustomUnitBundles: skinned-lane missing override controller under " + root);
			AddRequiredSkinnedAsset(dest, overridePath);
			var animationFolder = root + "/Animations";
			if (AssetDatabase.IsValidFolder(animationFolder))
			{
				foreach (var guid in AssetDatabase.FindAssets("t:AnimationClip", new[] { animationFolder }))
				{
					var path = AssetDatabase.GUIDToAssetPath(guid);
					if (path.EndsWith(".anim", StringComparison.OrdinalIgnoreCase))
						AddIfPresent(dest, path);
				}
			}
			return dest.Count > before;
		}

		static void AddSoundsForUnit(List<string> dest, string unitSid)
		{
			if (string.IsNullOrEmpty(unitSid))
				return;
			// Lane A: Assets/CustomUnits/<sid>/sounds — Lane B (homm3_import): Assets/CustomUnits/homm3_lab/<sid>/sounds
			var folders = new[]
			{
				"Assets/CustomUnits/" + unitSid + "/sounds",
				"Assets/CustomUnits/homm3_lab/" + unitSid + "/sounds"
			};
			var any = false;
			foreach (var folder in folders)
			{
				if (!AssetDatabase.IsValidFolder(folder))
					continue;
				any = true;
				// One tiny prefab per SFX (GameObject + AudioSource + clip), e.g. ESQUIRE_Attack_1.prefab — not raw WAVs.
				foreach (var guid in AssetDatabase.FindAssets("t:Prefab", new[] { folder }))
				{
					var p = AssetDatabase.GUIDToAssetPath(guid);
					if (p.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
						AddIfPresent(dest, p);
				}
			}

			if (!any)
				Debug.Log("BuildCustomUnitBundles: no sounds folder (optional) for unitSid=" + unitSid + " (checked lane A + homm3_lab paths).");
		}

		static void AddProjectilesForUnit(List<string> dest, string unitSid)
		{
			if (string.IsNullOrEmpty(unitSid))
				return;
			var folder = "Assets/CustomUnits/homm3_lab/" + unitSid + "/projectiles";
			if (!AssetDatabase.IsValidFolder(folder))
				return;
			foreach (var guid in AssetDatabase.FindAssets("t:Prefab", new[] { folder }))
			{
				var p = AssetDatabase.GUIDToAssetPath(guid);
				if (p.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
					AddIfPresent(dest, p);
			}
		}

		static void ValidateHomm3MapPrefabMaterial(UnitEntry u)
		{
			if (u == null || string.IsNullOrEmpty(u.unitSid) || string.IsNullOrEmpty(u.mapPrefabAsset))
				return;
			var mapPrefab = u.mapPrefabAsset.Replace('\\', '/');
			if (!mapPrefab.Contains("/homm3_lab/", StringComparison.OrdinalIgnoreCase))
				return;

			var expectedArray = "Assets/CustomUnits/homm3_lab/"
				+ u.unitSid
				+ "/Generated/MapBillboard/Array/map_array.mat";
			var expectedLegacy = "Assets/CustomUnits/homm3_lab/"
				+ u.unitSid
				+ "/Generated/MapBillboard/Materials/map_frame_000.mat";
			var useArray = AssetDatabase.LoadAssetAtPath<Material>(expectedArray) != null;
			var expected = useArray ? expectedArray : expectedLegacy;
			if (AssetDatabase.LoadAssetAtPath<Material>(expected) == null)
				throw new InvalidOperationException(
					"BuildCustomUnitBundles: missing generated map material for "
					+ u.unitSid
					+ ": "
					+ expected
					+ ". Run Homm3BillboardAnimatorBuild before bundling.");

			var root = PrefabUtility.LoadPrefabContents(mapPrefab);
			try
			{
				var quad = root.transform.Find("billboard/quad");
				var renderer = quad ? quad.GetComponent<MeshRenderer>() : null;
				var actual = renderer && renderer.sharedMaterial
					? AssetDatabase.GetAssetPath(renderer.sharedMaterial).Replace('\\', '/')
					: "";
				if (!string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
				{
					throw new InvalidOperationException(
						"BuildCustomUnitBundles: stale map prefab material for "
						+ u.unitSid
						+ ": "
						+ mapPrefab
						+ " uses "
						+ (string.IsNullOrEmpty(actual) ? "(none)" : actual)
						+ "; expected "
						+ expected
						+ ". Run Homm3BillboardAnimatorBuild before bundling.");
				}
			}
			finally
			{
				PrefabUtility.UnloadPrefabContents(root);
			}
		}

		static bool AddHomm3ArrayMapAssets(List<string> dest, string unitSid)
		{
			if (string.IsNullOrEmpty(unitSid))
				return false;
			var mapRoot = "Assets/CustomUnits/homm3_lab/" + unitSid + "/Generated/MapBillboard";
			var arrayFolder = mapRoot + "/Array";
			var before = dest.Count;
			if (AssetDatabase.IsValidFolder(arrayFolder))
			{
				foreach (var guid in AssetDatabase.FindAssets("t:Texture2DArray", new[] { arrayFolder }))
				{
					var p = AssetDatabase.GUIDToAssetPath(guid);
					if (p.EndsWith(".asset", StringComparison.OrdinalIgnoreCase))
						AddIfPresent(dest, p);
				}
			}
			AddIfPresent(dest, arrayFolder + "/map_array.mat");
			AddIfPresent(dest, mapRoot + "/Homm3MapBillboard.controller");
			var clipsFolder = mapRoot + "/Clips";
			if (AssetDatabase.IsValidFolder(clipsFolder))
			{
				foreach (var guid in AssetDatabase.FindAssets("t:AnimationClip", new[] { clipsFolder }))
				{
					var p = AssetDatabase.GUIDToAssetPath(guid);
					if (p.EndsWith(".anim", StringComparison.OrdinalIgnoreCase))
						AddIfPresent(dest, p);
				}
			}
			return dest.Count > before;
		}

		/// <summary>Returns true when array-battle assets were found (skip per-frame materials).</summary>
		static bool AddHomm3ArrayBattleAssets(List<string> dest, string unitSid)
		{
			if (string.IsNullOrEmpty(unitSid))
				return false;
			var animRoot = "Assets/CustomUnits/homm3_lab/" + unitSid + "/Generated/BillboardAnim";
			var arrayFolder = animRoot + "/Array";
			var before = dest.Count;
			var arraysBefore = dest.Count;
			if (AssetDatabase.IsValidFolder(arrayFolder))
			{
				foreach (var guid in AssetDatabase.FindAssets("t:Texture2DArray", new[] { arrayFolder }))
				{
					var p = AssetDatabase.GUIDToAssetPath(guid);
					if (p.EndsWith(".asset", StringComparison.OrdinalIgnoreCase))
						AddIfPresent(dest, p);
				}
			}
			if (dest.Count == arraysBefore)
				AddIfPresent(dest, arrayFolder + "/battle_frames_array.asset");
			AddIfPresent(dest, arrayFolder + "/battle_array.mat");
			AddIfPresent(dest, animRoot + "/Homm3BattleBillboard.overrideController");
			var clipsFolder = animRoot + "/Clips";
			if (AssetDatabase.IsValidFolder(clipsFolder))
			{
				foreach (var guid in AssetDatabase.FindAssets("t:AnimationClip", new[] { clipsFolder }))
				{
					var p = AssetDatabase.GUIDToAssetPath(guid);
					if (p.EndsWith(".anim", StringComparison.OrdinalIgnoreCase))
						AddIfPresent(dest, p);
				}
			}
			return dest.Count > before;
		}

		static bool HasMapArrayMaterial(List<string> dest, string unitSid)
		{
			if (string.IsNullOrEmpty(unitSid) || dest == null)
				return false;
			var expected = ("Assets/CustomUnits/homm3_lab/" + unitSid + "/Generated/MapBillboard/Array/map_array.mat")
				.Replace('\\', '/');
			for (var i = 0; i < dest.Count; i++)
			{
				var p = (dest[i] ?? "").Replace('\\', '/');
				if (string.Equals(p, expected, StringComparison.OrdinalIgnoreCase))
					return true;
			}
			return false;
		}

		static void ValidateHomm3MapFrameAssetsExplicit(List<string> assetPaths, UnitEntry u)
		{
			if (u == null || string.IsNullOrEmpty(u.unitSid) || string.IsNullOrEmpty(u.mapPrefabAsset))
				return;
			if (HasMapArrayMaterial(assetPaths, u.unitSid))
				return;
			var expected = ("Assets/CustomUnits/homm3_lab/"
				+ u.unitSid
				+ "/Generated/MapBillboard/Materials/map_frame_000.mat").Replace('\\', '/');
			var hasExplicit = false;
			for (var i = 0; i < assetPaths.Count; i++)
			{
				var p = (assetPaths[i] ?? "").Replace('\\', '/');
				if (string.Equals(p, expected, StringComparison.OrdinalIgnoreCase))
				{
					hasExplicit = true;
					break;
				}
			}
			if (!hasExplicit)
			{
				throw new InvalidOperationException(
					"BuildCustomUnitBundles: adventure-map bundle for "
					+ u.unitSid
					+ " lacks explicit map_array.mat and map_frame_000.mat root assets. "
					+ "Runtime CountMapFrameAssetNamesInBundle only sees explicit names; "
					+ "dependency-only MapIdle materials leave adventure-map units invisible.");
			}
		}

		static void AddGeneratedHomm3FrameMaterials(
			List<string> dest,
			string unitSid,
			bool includeBattle = true,
			bool includeMap = true)
		{
			if (string.IsNullOrEmpty(unitSid) || (!includeBattle && !includeMap))
				return;
			var folders = new List<string>();
			if (includeBattle)
				folders.Add("Assets/CustomUnits/homm3_lab/" + unitSid + "/Generated/BillboardAnim/Materials");
			if (includeMap)
				folders.Add("Assets/CustomUnits/homm3_lab/" + unitSid + "/Generated/MapBillboard/Materials");
			foreach (var folder in folders)
			{
				if (!AssetDatabase.IsValidFolder(folder))
					continue;
				foreach (var guid in AssetDatabase.FindAssets("t:Material", new[] { folder }))
				{
					var p = AssetDatabase.GUIDToAssetPath(guid);
					if (p.EndsWith(".mat", StringComparison.OrdinalIgnoreCase))
						AddIfPresent(dest, p);
				}
			}
		}

		static void WriteReport(string outputPath, Manifest m)
		{
			try
			{
				var report = new Manifest
				{
					formatVersion = m.formatVersion,
					units = m.units
				};
				var path = Path.Combine(outputPath, "build_report.json");
				File.WriteAllText(
					path,
					JsonUtility.ToJson(report, prettyPrint: true));
			}
			catch (Exception ex)
			{
				Debug.LogWarning("BuildCustomUnitBundles: build_report.json failed: " + ex.Message);
			}
		}
	}
}
