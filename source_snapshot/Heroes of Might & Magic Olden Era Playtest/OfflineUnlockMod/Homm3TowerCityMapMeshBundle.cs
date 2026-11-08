using System;
using System.IO;
using BepInEx.Logging;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Tower adventure-map city 3D mesh pilot. Loads <c>homm3_tower_city_map_mesh</c> AssetBundle
/// prefab <c>tower_city_map_mesh</c> (Meshy FBX authored to ~5.15 world units tall).
/// Gate: <see cref="LauncherConfig.Homm3TowerCityMapMesh"/>. Fail-closed when enabled —
/// no silent PNG billboard fallback.
/// </summary>
internal static class Homm3TowerCityMapMeshBundle
{
	internal const string BundleName = "homm3_tower_city_map_mesh";
	internal const string RelativeBundlePath = "homm3_tower_city_map_mesh/homm3_tower_city_map_mesh";
	internal const string RelativeManifestPath = "homm3_tower_city_map_mesh/manifest.json";
	internal const string PrefabAssetName = "tower_city_map_mesh";
	internal const string TowerCitySid = "homm3_tower_city";
	internal const string MeshRootPrefix = Homm3MapBuildingMeshBundle.MeshRootPrefix;

	private static AssetBundle _bundle;
	private static GameObject _prefab;
	private static bool _loadAttempted;
	private static int _loggedLoad;

	internal static bool IsEnabled()
	{
		var cfg = LauncherConfigReader.TryLoad();
		return cfg != null && cfg.Homm3TowerCityMapMesh;
	}

	internal static bool IsTowerCitySid(string citySid) =>
		string.Equals(citySid, TowerCitySid, StringComparison.OrdinalIgnoreCase);

	internal static bool ShouldApplyMesh(string citySid) =>
		IsEnabled() && IsTowerCitySid(citySid);

	internal static float GetRuntimeScale()
	{
		var cfg = LauncherConfigReader.TryLoad();
		if (cfg == null)
			return 1f;
		var scale = (float)cfg.Homm3TowerCityMapMeshScale;
		return scale > 0.01f ? scale : 1f;
	}

	internal static void ValidateBundlePayloadOrFail(ManualLogSource log)
	{
		var bundlePath = ResolveBundleFilePath();
		if (bundlePath == null || !File.Exists(bundlePath))
		{
			throw new FileNotFoundException(
				"homm3TowerCityMapMesh is enabled but the homm3_tower_city_map_mesh AssetBundle is missing "
				+ "under the deployed OfflineUnlockMod plugin folder. Run "
				+ "tools/homm3_import/build_homm3_tower_city_map_mesh_bundle.py "
				+ "and redeploy the plugin folder (or turn the flag off to keep the PNG town billboard).",
				RelativeBundlePath);
		}

		var assetNames = Homm3UiPortraitBundle.LoadManifestAssetNamesOrFail(
			RelativeManifestPath,
			BundleName,
			"homm3TowerCityMapMesh");
		if (!assetNames.Contains(PrefabAssetName))
		{
			throw new InvalidOperationException(
				"homm3TowerCityMapMesh is enabled but manifest.json does not declare prefab asset '"
				+ PrefabAssetName
				+ "'.");
		}

		log?.LogInfo(
			"Homm3TowerCityMapMeshBundle: validated bundle file and manifest ("
			+ assetNames.Count
			+ " declared asset(s)); prefab load deferred until map apply.");
	}

	internal static bool TryLoadPrefab(out GameObject prefab, ManualLogSource log)
	{
		prefab = null;
		EnsureLoaded(log);
		if (_prefab == null)
			return false;
		prefab = _prefab;
		return true;
	}

	/// <summary>
	/// Rebind each MeshRenderer to a Hex/Lit clone from the donor so adventure-map fog/lighting match.
	/// Uses bundled albedo (+ normal when present). Fail-closed if donor Hex/Lit cannot be cloned.
	/// </summary>
	internal static bool TryRebindRenderersToMapDonor(
		GameObject meshRoot,
		Material donorMaterial,
		ManualLogSource log)
	{
		if (!meshRoot)
			return false;
		if (!donorMaterial || donorMaterial.shader == null)
		{
			log?.LogError(
				"Homm3TowerCityMapMeshBundle: donor Hex/Lit material missing; refuse Tower mesh apply.");
			return false;
		}

		var shaderName = donorMaterial.shader.name ?? string.Empty;
		if (shaderName.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) < 0
		    && shaderName.IndexOf("Hex\\Lit", StringComparison.OrdinalIgnoreCase) < 0)
		{
			log?.LogError(
				"Homm3TowerCityMapMeshBundle: donor material shader='"
				+ shaderName
				+ "' is not Hex/Lit; refuse Tower mesh apply (no silent non-map shader).");
			return false;
		}

		var renderers = meshRoot.GetComponentsInChildren<MeshRenderer>(true);
		if (renderers == null || renderers.Length == 0)
		{
			log?.LogError("Homm3TowerCityMapMeshBundle: prefab instance has no MeshRenderer.");
			return false;
		}

		foreach (var renderer in renderers)
		{
			if (!renderer)
				continue;
			var sourceMats = renderer.sharedMaterials;
			if (sourceMats == null || sourceMats.Length == 0)
			{
				log?.LogError(
					"Homm3TowerCityMapMeshBundle: MeshRenderer '"
					+ renderer.name
					+ "' has no materials.");
				return false;
			}

			var rebound = new Material[sourceMats.Length];
			for (var i = 0; i < sourceMats.Length; i++)
			{
				var source = sourceMats[i];
				var albedo = source
					? (source.HasProperty("_BaseMap") ? source.GetTexture("_BaseMap") : null)
					  ?? (source.HasProperty("_MainTex") ? source.GetTexture("_MainTex") : null)
					  ?? source.mainTexture
					: null;
				if (!albedo)
				{
					log?.LogError(
						"Homm3TowerCityMapMeshBundle: material slot "
						+ i
						+ " on '"
						+ renderer.name
						+ "' has no albedo texture.");
					return false;
				}

				var normal = source
					? (source.HasProperty("_BumpMap") ? source.GetTexture("_BumpMap") : null)
					  ?? (source.HasProperty("_NormalMap") ? source.GetTexture("_NormalMap") : null)
					: null;

				var clone = new Material(donorMaterial)
				{
					name = "HOMM3_tower_city_map_mesh_" + renderer.name + "_" + i
				};
				EsquirePikemanVisuals.SanitizeMapMaterialForOpaqueMesh(clone);
				if (clone.HasProperty("_MainTex"))
					clone.SetTexture("_MainTex", albedo);
				else
					clone.mainTexture = albedo;
				if (normal && clone.HasProperty("_BumpMap"))
				{
					clone.SetTexture("_BumpMap", normal);
					clone.EnableKeyword("_NORMALMAP");
				}
				rebound[i] = clone;
			}

			renderer.sharedMaterials = rebound;
			renderer.enabled = true;
			renderer.forceRenderingOff = false;
			renderer.shadowCastingMode = ShadowCastingMode.On;
			renderer.receiveShadows = true;
			renderer.allowOcclusionWhenDynamic = false;
		}

		return true;
	}

	private static void EnsureLoaded(ManualLogSource log)
	{
		if (_loadAttempted)
			return;
		_loadAttempted = true;
		var path = ResolveBundleFilePath();
		if (path == null || !File.Exists(path))
		{
			log?.LogError(
				"Homm3TowerCityMapMeshBundle: bundle file missing at "
				+ RelativeBundlePath
				+ " (resolved="
				+ (path ?? "null")
				+ ").");
			return;
		}

		try
		{
			_bundle = AssetBundle.LoadFromFile(path);
			if (_bundle == null)
			{
				log?.LogError(
					"Homm3TowerCityMapMeshBundle: AssetBundle.LoadFromFile returned null for " + path);
				return;
			}

			_prefab = _bundle.LoadAsset<GameObject>(PrefabAssetName);
			if (_prefab == null)
			{
				log?.LogError(
					"Homm3TowerCityMapMeshBundle: LoadAsset<GameObject>('"
					+ PrefabAssetName
					+ "') returned null from "
					+ path);
				return;
			}

			log?.LogInfo("Homm3TowerCityMapMeshBundle: loaded prefab from " + path);
		}
		catch (Exception ex)
		{
			if (_loggedLoad++ < 8)
				log?.LogError(
					"Homm3TowerCityMapMeshBundle: failed to load " + path + ": " + ex.Message);
			_bundle = null;
			_prefab = null;
		}
	}

	private static string ResolveBundleFilePath()
	{
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeBundlePath);
		if (path == null)
			path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeBundlePath + ".bundle");
		return path;
	}
}
