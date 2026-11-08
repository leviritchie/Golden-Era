// Map adventure billboard: Texture2DArray + BC7/DXT5 (same shader as battle) with MapIdle timing clip.
// Pilot: set mapTexture2DArray=1 in authoring.json after map RIFE (extracted_map/.rife_map_done.json).

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Globalization;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace OldenEra.Homm3Import
{
	public static partial class Homm3BillboardAnimatorBuild
	{
		const string MapArrayRel = "Array";
		const string MapArrayManifestFileName = "array_map_manifest.json";
		const string MapArrayMaterialAssetName = "map_array.mat";

		static bool UseMapTexture2DArray() =>
			_authoring != null && _authoring.mapTexture2DArray != 0;

		static void RebuildMapTexture2DArray()
		{
			var framesRoot = ResolveMapFramesFolder();
			if (ApplyFolderPngMeshBillboardImport(framesRoot))
				AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

			if (!TryLoadDefExtractManifestForFolder(framesRoot, out var manifest, out var jsonPath))
				throw new InvalidOperationException(
					"Map Texture2DArray build requires defextract JSON under " + framesRoot + ".");

			var rel = GetRelativeFramePathsForGroup(manifest, GroupIdle);
			if (rel.Count == 0)
				rel = GetRelativeFramePathsForGroup(manifest, GroupMovement);
			if (rel.Count == 0)
				throw new InvalidOperationException(
					"Map Texture2DArray build: no idle/movement frames in " + jsonPath + " for " + _authoring.unitSid);

			var globalPaths = rel
				.Select(p => p?.Replace('\\', '/'))
				.Where(p => !string.IsNullOrEmpty(p))
				.ToList();
			if (globalPaths.Count == 0)
				throw new InvalidOperationException("Map Texture2DArray build: empty frame list for " + _authoring.unitSid);

			var playbackFps = ResolveMapPlaybackFps();
			var arrayFolder = $"{MapGeneratedRoot}/{MapArrayRel}";
			EnsureFolder(MapGeneratedRoot);
			EnsureFolder($"{MapGeneratedRoot}/{ClipsRel}");
			EnsureFolder(arrayFolder);

			ClearSubfolders($"{MapGeneratedRoot}/{MaterialsRel}", $"{MapGeneratedRoot}/{ClipsRel}", arrayFolder);
			if (AssetDatabase.LoadAssetAtPath<AnimatorController>(MapAnimatorControllerPath))
				AssetDatabase.DeleteAsset(MapAnimatorControllerPath);

			var matAssetPath = $"{arrayFolder}/{MapArrayMaterialAssetName}";
			var manifestAssetPath = $"{MapGeneratedRoot}/{MapArrayManifestFileName}";
			foreach (var asset in AssetDatabase.FindAssets("t:Texture2DArray", new[] { arrayFolder }))
			{
				var path = AssetDatabase.GUIDToAssetPath(asset);
				if (!string.IsNullOrEmpty(path))
					AssetDatabase.DeleteAsset(path);
			}
			if (AssetDatabase.LoadAssetAtPath<Material>(matAssetPath))
				AssetDatabase.DeleteAsset(matAssetPath);
			if (File.Exists(manifestAssetPath))
				AssetDatabase.DeleteAsset(manifestAssetPath);

			var textures = LoadMapTexturesForRelativePaths(globalPaths, framesRoot);
			List<Texture2DArray> arrayChunks;
			try
			{
				arrayChunks = BuildTexture2DArrayAssetsChunked(textures, arrayFolder);
			}
			finally
			{
				ReleaseTransientBattleSourceTextures(textures);
			}
			if (arrayChunks.Count > ArrayTexturePropertyNames.Length)
				throw new InvalidOperationException(
					"Map Texture2DArray build: "
					+ globalPaths.Count
					+ " frames need "
					+ arrayChunks.Count
					+ " arrays (max "
					+ ArrayTexturePropertyNames.Length
					+ ").");

			var arrayShader = Shader.Find("OldenEra/Homm3/BillboardArray");
			if (arrayShader == null)
				throw new InvalidOperationException(
					"Shader OldenEra/Homm3/BillboardArray missing. Copy Homm3BillboardArray.shader into Assets/Shaders/.");

			var arrayMaterial = new Material(arrayShader);
			arrayMaterial.name = "homm3_map_array";
			arrayMaterial.SetFloat("_ArraySliceSize", MaxTexture2DArraySlices);
			for (var i = 0; i < arrayChunks.Count; i++)
				arrayMaterial.SetTexture(ArrayTexturePropertyNames[i], arrayChunks[i]);
			AssetDatabase.CreateAsset(arrayMaterial, matAssetPath);
			AssetDatabase.SaveAssets();
			AssetDatabase.ImportAsset(matAssetPath, ImportAssetOptions.ForceUpdate | ImportAssetOptions.ForceSynchronousImport);
			arrayMaterial = AssetDatabase.LoadAssetAtPath<Material>(matAssetPath);
			if (arrayMaterial == null)
				throw new InvalidOperationException("Map Texture2DArray build failed to load saved material at " + matAssetPath);

			var indices = Enumerable.Range(0, globalPaths.Count).ToArray();
			var mapClip = CreateArrayTimingClip(MapWalkClipName, indices.Length, playbackFps, loop: true);
			var clipPath = $"{MapGeneratedRoot}/{ClipsRel}/{MapWalkClipName}.anim";
			AssetDatabase.CreateAsset(mapClip, clipPath);
			AssetDatabase.SaveAssets();
			var clipAsset = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
			if (clipAsset == null)
				throw new InvalidOperationException("Failed to load saved map array clip at " + clipPath);

			var manifestData = new Homm3BattleArrayManifestData
			{
				unitSid = _authoring.unitSid,
				frameCount = globalPaths.Count,
				arrayChunkSize = MaxTexture2DArraySlices,
				arrayCount = arrayChunks.Count,
				baseAttackGroup = GroupAttackFront,
				clips = new[]
				{
					new Homm3BattleArrayClipDef
					{
						name = MapWalkClipName,
						indices = indices,
						fps = playbackFps,
						loop = 1,
						attackBaseGroup = -1
					}
				}
			};

			var json = JsonUtility.ToJson(manifestData, true);
			var projectRoot = Path.GetDirectoryName(Application.dataPath) ?? "";
			var manifestFullPath = Path.Combine(projectRoot, manifestAssetPath.Replace('/', Path.DirectorySeparatorChar));
			Directory.CreateDirectory(Path.GetDirectoryName(manifestFullPath) ?? projectRoot);
			File.WriteAllText(manifestFullPath, json);
			AssetDatabase.ImportAsset(manifestAssetPath, ImportAssetOptions.ForceUpdate);
			CopyMapArrayManifestToOfflineLab(manifestFullPath);

			var animatorController = CreateOrReplaceMapAnimatorController(clipAsset);
			AssignArrayMaterialToMapPrefab(arrayMaterial, animatorController);

			Debug.Log(
				"Homm3BillboardAnimatorBuild: map Texture2DArray complete sid="
				+ _authoring.unitSid
				+ " frames="
				+ globalPaths.Count
				+ " fps="
				+ playbackFps.ToString(CultureInfo.InvariantCulture)
				+ " from "
				+ jsonPath);
		}

		static List<Texture2D> LoadMapTexturesForRelativePaths(List<string> relativePaths, string framesDir)
		{
			var parent = Path.GetDirectoryName(framesDir.Replace('\\', '/').TrimEnd('/'))?.Replace('\\', '/');
			if (string.IsNullOrEmpty(parent))
				throw new InvalidOperationException("Invalid map frames folder: " + framesDir);
			var list = new List<Texture2D>(relativePaths.Count);
			foreach (var rel in relativePaths)
			{
				var assetPath = $"{parent}/{rel}";
				var tex = FirstTexture2DAtPath(assetPath);
				if (tex == null)
					throw new InvalidOperationException("Map Texture2DArray build: missing texture at " + assetPath);
				list.Add(tex);
			}
			return list;
		}

		static float ResolveMapPlaybackFps()
		{
			var fromRife = TryReadMapRifeTargetFpsForAuthoringUnit(_authoring?.unitSid);
			if (fromRife > 0f)
				return fromRife;
			if (_authoring != null && _authoring.mapFlipBookFps > 0f)
				return _authoring.mapFlipBookFps;
			return 50f;
		}

		static float TryReadMapRifeTargetFpsForAuthoringUnit(string unitSid)
		{
			if (string.IsNullOrEmpty(unitSid))
				return 0f;
			var projectRoot = Path.GetDirectoryName(Application.dataPath) ?? "";
			var repoRoot = Path.GetFullPath(Path.Combine(Application.dataPath, "..", ".."));
			var candidates = new[]
			{
				Path.Combine(Application.dataPath, "CustomUnits", "homm3_lab", unitSid, "extracted_map", ".rife_map_done.json"),
				Path.Combine(projectRoot, "Heroes of Might & Magic Olden Era Playtest", "OfflineUnlockMod", "homm3_lab", unitSid, "extracted_map", ".rife_map_done.json"),
				Path.Combine(repoRoot, "Heroes of Might & Magic Olden Era Playtest", "OfflineUnlockMod", "homm3_lab", unitSid, "extracted_map", ".rife_map_done.json")
			};
			foreach (var path in candidates)
			{
				if (!File.Exists(path))
					continue;
				try
				{
					var root = JObject.Parse(File.ReadAllText(path));
					if (root["targetFps"] != null
					    && float.TryParse(root["targetFps"].ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var top)
					    && top > 0f)
						return top;
				}
				catch
				{
					// next candidate
				}
			}
			return 0f;
		}

		static void AssignArrayMaterialToMapPrefab(Material arrayMaterial, AnimatorController controller)
		{
			var map = AssetDatabase.LoadAssetAtPath<GameObject>(MapPrefabPath);
			if (map == null)
				throw new InvalidOperationException("map.prefab missing: " + MapPrefabPath);

			var mapRoot = PrefabUtility.LoadPrefabContents(MapPrefabPath);
			try
			{
				EnsureMapPrefabBillboardStructure(mapRoot, arrayMaterial);
				var quad = mapRoot.transform.Find(QuadRendererPath);
				if (quad == null)
					throw new InvalidOperationException("map.prefab missing " + QuadRendererPath);
				var renderer = quad.GetComponent<MeshRenderer>();
				if (renderer == null)
					throw new InvalidOperationException("map quad missing MeshRenderer.");
				renderer.sharedMaterials = new[] { arrayMaterial };
				EditorUtility.SetDirty(renderer);
				RemoveArrayTimingChannelIfPresent(mapRoot);
				EnsureArrayTimingChild(mapRoot);
				WireMapAnimator(mapRoot, controller);
				PrefabUtility.SaveAsPrefabAsset(mapRoot, MapPrefabPath, out var saved);
				if (!saved)
					throw new InvalidOperationException("Failed to save map prefab at " + MapPrefabPath);
				AssetDatabase.ImportAsset(MapPrefabPath, ImportAssetOptions.ForceUpdate | ImportAssetOptions.ForceSynchronousImport);
				var actualPath = AssetDatabase.GetAssetPath(renderer.sharedMaterial)?.Replace('\\', '/') ?? "";
				if (!string.Equals(actualPath, AssetDatabase.GetAssetPath(arrayMaterial)?.Replace('\\', '/'), StringComparison.OrdinalIgnoreCase))
					throw new InvalidOperationException(
						"Map prefab material assignment did not persist for "
						+ _authoring.unitSid
						+ ": "
						+ actualPath);
			}
			finally
			{
				PrefabUtility.UnloadPrefabContents(mapRoot);
			}
		}

		static void CopyMapArrayManifestToOfflineLab(string manifestFullPath)
		{
			if (string.IsNullOrEmpty(_authoring?.unitSid) || !File.Exists(manifestFullPath))
				return;
			var repoRoot = Path.GetFullPath(Path.Combine(Application.dataPath, "..", ".."));
			var offlineRoot = Path.Combine(
				repoRoot,
				"Heroes of Might & Magic Olden Era Playtest",
				"OfflineUnlockMod",
				"homm3_lab",
				_authoring.unitSid,
				"Generated",
				"MapBillboard");
			Directory.CreateDirectory(offlineRoot);
			File.Copy(manifestFullPath, Path.Combine(offlineRoot, MapArrayManifestFileName), overwrite: true);
		}
	}
}
