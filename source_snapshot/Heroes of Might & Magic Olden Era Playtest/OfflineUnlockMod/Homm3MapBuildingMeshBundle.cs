using System;
using System.Collections.Generic;
using System.IO;
using BepInEx.Logging;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Catalog-driven adventure-map building meshes (cities + dwellings) from Meshy t2.
/// Gate: <see cref="LauncherConfig.Homm3MapBuildingMeshes"/>. Fail-closed when enabled for
/// static wired billboard paths present in the catalog — no silent PNG fallback for those hits.
/// Animated / uncatalogued billboards keep the PNG path.
/// </summary>
internal static class Homm3MapBuildingMeshBundle
{
	internal const string BundleName = "homm3_map_building_meshes";
	internal const string RelativeBundlePath = "homm3_map_building_meshes/homm3_map_building_meshes";
	internal const string RelativeCatalogPath = "homm3_map_building_meshes/catalog.json";
	internal const string RelativeManifestPath = "homm3_map_building_meshes/manifest.json";
	internal const string MeshRootPrefix = "homm3_custom_city_mesh_";
	internal const string CatalogSchema = "homm3_map_building_mesh_catalog.v1";

	private static AssetBundle _bundle;
	private static bool _loadAttempted;
	private static bool _catalogLoadAttempted;
	private static int _loggedLoad;
	private static Dictionary<string, CatalogEntry> _byRelativePng;
	private static readonly Dictionary<string, GameObject> PrefabsByKey = new(StringComparer.OrdinalIgnoreCase);

	internal sealed class CatalogEntry
	{
		internal string RelativePng;
		internal string PrefabKey;
		internal string Kind;
		internal float TargetHeight;
		/// <summary>Optional slight yaw (degrees) on top of <see cref="BillboardFrontYawDegrees"/>.</summary>
		internal float ArtYawDegrees;
	}

	private static readonly Dictionary<string, Material> ReboundMaterialCache =
		new(StringComparer.Ordinal);

	/// <summary>
	/// Meshy/glTF "front" is opposite the adventure approach after import.
	/// Map facing must come from the parent transform (PNG identity local) — never from raw
	/// <c>bvmu</c> rotation × 90 (OE uses values like 0/10 as footprint/mirror encoding).
	/// </summary>
	internal const float BillboardFrontYawDegrees = 180f;

	private static readonly Dictionary<string, float> CachedArtYawByKey =
		new(StringComparer.OrdinalIgnoreCase);

	private static readonly float[] ArtYawCandidates = { -25f, -15f, 0f, 15f, 25f };

	private static int _poseLogRemaining = 12;

	internal static bool IsEnabled()
	{
		var cfg = LauncherConfigReader.TryLoad();
		if (cfg == null)
			return false;
		if (cfg.Homm3MapBuildingMeshes)
			return true;
		// One-revision alias: old Tower-only flag enables the shared catalog path.
		return cfg.Homm3TowerCityMapMesh;
	}

	internal static float GetRuntimeScale()
	{
		var cfg = LauncherConfigReader.TryLoad();
		if (cfg == null)
			return 1f;
		var scale = cfg.Homm3MapBuildingMeshes
			? (float)cfg.Homm3MapBuildingMeshesScale
			: (float)cfg.Homm3TowerCityMapMeshScale;
		return scale > 0.01f ? scale : 1f;
	}

	internal static bool TryGetEntry(string relativePng, out CatalogEntry entry)
	{
		entry = null;
		if (string.IsNullOrWhiteSpace(relativePng))
			return false;
		EnsureCatalog(null);
		if (_byRelativePng == null || _byRelativePng.Count == 0)
			return false;
		var key = NormalizeRelative(relativePng);
		return _byRelativePng.TryGetValue(key, out entry) && entry != null;
	}

	internal static bool HasMeshForRelativePath(string relativePng) =>
		TryGetEntry(relativePng, out _);

	internal static bool TryLoadPrefab(string relativePng, out GameObject prefab, out CatalogEntry entry, ManualLogSource log)
	{
		prefab = null;
		entry = null;
		if (!TryGetEntry(relativePng, out entry))
			return false;
		EnsureBundle(log);
		if (_bundle == null)
			return false;
		if (PrefabsByKey.TryGetValue(entry.PrefabKey, out var cached) && cached)
		{
			prefab = cached;
			return true;
		}
		try
		{
			var loaded = _bundle.LoadAsset<GameObject>(entry.PrefabKey);
			if (!loaded)
			{
				log?.LogError(
					"Homm3MapBuildingMeshBundle: LoadAsset<GameObject>('"
					+ entry.PrefabKey
					+ "') returned null.");
				return false;
			}
			PrefabsByKey[entry.PrefabKey] = loaded;
			prefab = loaded;
			return true;
		}
		catch (Exception ex)
		{
			if (_loggedLoad++ < 8)
				log?.LogError(
					"Homm3MapBuildingMeshBundle: failed to load prefab '"
					+ entry.PrefabKey
					+ "': "
					+ ex.Message);
			return false;
		}
	}

	internal static void ValidateBundlePayloadOrFail(ManualLogSource log)
	{
		var catalogPath = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeCatalogPath);
		if (catalogPath == null || !File.Exists(catalogPath))
		{
			throw new FileNotFoundException(
				"homm3MapBuildingMeshes is enabled but catalog.json is missing under the deployed "
				+ "OfflineUnlockMod/homm3_map_building_meshes folder. Run "
				+ "tools/homm3_import/build_homm3_map_building_meshes_bundle.py "
				+ "and redeploy (or turn the flag off to keep PNG billboards).",
				RelativeCatalogPath);
		}

		EnsureCatalog(log);
		if (_byRelativePng == null || _byRelativePng.Count == 0)
		{
			throw new InvalidOperationException(
				"homm3MapBuildingMeshes is enabled but catalog.json has no mesh entries.");
		}

		foreach (var entry in _byRelativePng.Values)
		{
			var rel = entry.RelativePng ?? string.Empty;
			if (rel.IndexOf("town_scene_refs", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				throw new InvalidOperationException(
					"homm3MapBuildingMeshes catalog must not include town_scene_refs paths: " + rel);
			}
			var leaf = Path.GetFileName(Path.GetDirectoryName(rel.Replace('/', Path.DirectorySeparatorChar)) ?? string.Empty);
			if (!string.IsNullOrEmpty(leaf)
			    && leaf.StartsWith("avw", StringComparison.OrdinalIgnoreCase))
			{
				throw new InvalidOperationException(
					"homm3MapBuildingMeshes catalog must not include AVW wandering paths: " + rel);
			}
		}

		var bundlePath = ResolveBundleFilePath();
		if (bundlePath == null || !File.Exists(bundlePath))
		{
			throw new FileNotFoundException(
				"homm3MapBuildingMeshes is enabled but the homm3_map_building_meshes AssetBundle is missing.",
				RelativeBundlePath);
		}

		var assetNames = Homm3UiPortraitBundle.LoadManifestAssetNamesOrFail(
			RelativeManifestPath,
			BundleName,
			"homm3MapBuildingMeshes");
		foreach (var entry in _byRelativePng.Values)
		{
			if (!assetNames.Contains(entry.PrefabKey))
			{
				throw new InvalidOperationException(
					"homm3MapBuildingMeshes catalog prefab '"
					+ entry.PrefabKey
					+ "' is missing from AssetBundle manifest.");
			}
		}

		log?.LogInfo(
			"Homm3MapBuildingMeshBundle: validated catalog ("
			+ _byRelativePng.Count
			+ " entries) and bundle manifest ("
			+ assetNames.Count
			+ " asset(s)); prefab load deferred until map apply.");
	}

	/// <summary>
	/// Rebind each MeshRenderer to a Hex/Lit clone from the donor so adventure-map fog/lighting match.
	/// Keeps bundled albedo (+ normal/metallic/roughness when present on the authored material).
	/// Materials are cached by (donor, authored slot) so map load does not allocate a new Material
	/// per building instance.
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
				"Homm3MapBuildingMeshBundle: donor Hex/Lit material missing; refuse mesh apply.");
			return false;
		}

		var shaderName = donorMaterial.shader.name ?? string.Empty;
		if (shaderName.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) < 0
		    && shaderName.IndexOf("Hex\\Lit", StringComparison.OrdinalIgnoreCase) < 0)
		{
			log?.LogError(
				"Homm3MapBuildingMeshBundle: donor material shader='"
				+ shaderName
				+ "' is not Hex/Lit; refuse mesh apply (no silent non-map shader).");
			return false;
		}

		var renderers = meshRoot.GetComponentsInChildren<MeshRenderer>(true);
		if (renderers == null || renderers.Length == 0)
		{
			log?.LogError("Homm3MapBuildingMeshBundle: prefab instance has no MeshRenderer.");
			return false;
		}

		var donorId = donorMaterial.GetInstanceID();
		foreach (var renderer in renderers)
		{
			if (!renderer)
				continue;
			if (Homm3MapBuildingMeshProjectedFx.IsFxChildObject(renderer.transform))
				continue;
			var sourceMats = renderer.sharedMaterials;
			if (sourceMats == null || sourceMats.Length == 0)
			{
				log?.LogError(
					"Homm3MapBuildingMeshBundle: MeshRenderer '"
					+ renderer.name
					+ "' has no materials.");
				return false;
			}

			var rebound = new Material[sourceMats.Length];
			for (var i = 0; i < sourceMats.Length; i++)
			{
				var source = sourceMats[i];
				var sourceId = source ? source.GetInstanceID() : 0;
				var cacheKey = donorId.ToString() + "|" + sourceId.ToString() + "|" + i.ToString();
				if (ReboundMaterialCache.TryGetValue(cacheKey, out var cached) && cached)
				{
					rebound[i] = cached;
					continue;
				}

				var albedo = source
					? (source.HasProperty("_BaseMap") ? source.GetTexture("_BaseMap") : null)
					  ?? (source.HasProperty("_MainTex") ? source.GetTexture("_MainTex") : null)
					  ?? source.mainTexture
					: null;
				if (!albedo)
				{
					log?.LogError(
						"Homm3MapBuildingMeshBundle: material slot "
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
				var metallic = source && source.HasProperty("_MetallicGlossMap")
					? source.GetTexture("_MetallicGlossMap")
					: null;
				var smoothness = source && source.HasProperty("_Smoothness")
					? source.GetFloat("_Smoothness")
					: 0.35f;

				var clone = new Material(donorMaterial)
				{
					name = "HOMM3_map_building_mesh_" + (source ? source.name : "slot") + "_" + i
				};
				EsquirePikemanVisuals.SanitizeMapMaterialForOpaqueMesh(clone);
				if (clone.HasProperty("_MainTex"))
					clone.SetTexture("_MainTex", albedo);
				else
					clone.mainTexture = albedo;
				if (clone.HasProperty("_BaseMap"))
					clone.SetTexture("_BaseMap", albedo);
				if (normal && clone.HasProperty("_BumpMap"))
				{
					clone.SetTexture("_BumpMap", normal);
					clone.EnableKeyword("_NORMALMAP");
				}
				if (metallic && clone.HasProperty("_MetallicGlossMap"))
				{
					clone.SetTexture("_MetallicGlossMap", metallic);
					clone.EnableKeyword("_METALLICGLOSSMAP");
				}
				if (clone.HasProperty("_Smoothness"))
					clone.SetFloat("_Smoothness", smoothness);
				ReboundMaterialCache[cacheKey] = clone;
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

	/// <summary>
	/// Pose Meshy meshes under the map object's own facing (parent inherit, like PNG identity local).
	/// Apply fixed Meshy front correction (+180°) and a cheap cached slight art yaw. Do not pass
	/// raw placed-object rotation × 90 as <paramref name="mapFacingYawDegrees"/>.
	/// </summary>
	internal static void OrientToBillboardArtAndSeat(GameObject instance, ManualLogSource log)
	{
		OrientToBillboardArtAndSeat(instance, mapFacingYawDegrees: 0f, artYawDegrees: 0f, cacheKey: null, log);
	}

	internal static void OrientToBillboardArtAndSeat(
		GameObject instance,
		float artYawDegrees,
		ManualLogSource log)
	{
		OrientToBillboardArtAndSeat(instance, mapFacingYawDegrees: 0f, artYawDegrees, cacheKey: null, log);
	}

	internal static void OrientToBillboardArtAndSeat(
		GameObject instance,
		float mapFacingYawDegrees,
		float artYawDegrees,
		string cacheKey,
		ManualLogSource log)
	{
		if (!instance)
			return;
		var t = instance.transform;
		var upright = ResolveUprightPitchOnce(t, log);

		float chosenArtYaw = artYawDegrees;
		if (Math.Abs(artYawDegrees) < 0.01f && !string.IsNullOrWhiteSpace(cacheKey))
		{
			if (!CachedArtYawByKey.TryGetValue(cacheKey, out chosenArtYaw))
			{
				chosenArtYaw = PickCachedArtYaw(t, upright, mapFacingYawDegrees);
				CachedArtYawByKey[cacheKey] = chosenArtYaw;
			}
		}

		t.localRotation = Quaternion.Euler(
			                  0f,
			                  mapFacingYawDegrees + BillboardFrontYawDegrees + chosenArtYaw,
			                  0f)
		                  * upright;
		SeatBottomToParentGround(t, log);
		if (log != null && _poseLogRemaining > 0)
		{
			_poseLogRemaining--;
			log.LogInfo(
				"Homm3MapBuildingMeshBundle: billboard-art pose euler="
				+ t.localEulerAngles.ToString("0.#")
				+ " mapFacing="
				+ mapFacingYawDegrees.ToString("0.#")
				+ " frontYaw="
				+ BillboardFrontYawDegrees.ToString("0.#")
				+ " artYaw="
				+ chosenArtYaw.ToString("0.#"));
		}
	}

	private static float PickCachedArtYaw(Transform root, Quaternion upright, float mapFacingYawDegrees)
	{
		var bestYaw = 0f;
		var bestScore = float.NegativeInfinity;
		for (var i = 0; i < ArtYawCandidates.Length; i++)
		{
			var yaw = ArtYawCandidates[i];
			root.localRotation = Quaternion.Euler(
				                     0f,
				                     mapFacingYawDegrees + BillboardFrontYawDegrees + yaw,
				                     0f)
			                     * upright;
			if (!TryGetRendererBounds(root, out var size))
				continue;
			var score = size.y * 0.5f + size.x * 0.45f - size.z * 0.45f;
			if (score <= bestScore)
				continue;
			bestScore = score;
			bestYaw = yaw;
		}
		return bestYaw;
	}

	/// <summary>Obsolete — use <see cref="OrientToBillboardArtAndSeat"/>.</summary>
	internal static void OrientFacingHomm3AndSeat(GameObject instance, ManualLogSource log) =>
		OrientToBillboardArtAndSeat(instance, log);

	/// <summary>Obsolete — donor pose abandoned; use <see cref="OrientToBillboardArtAndSeat"/>.</summary>
	internal static void OrientToDonorAndSeat(
		GameObject instance,
		Renderer donorRenderer,
		ManualLogSource log)
	{
		OrientToBillboardArtAndSeat(instance, log);
	}

	/// <summary>Obsolete alias for <see cref="OrientToBillboardArtAndSeat"/>.</summary>
	internal static void OrientFacingSouthAndSeat(GameObject instance, ManualLogSource log) =>
		OrientToBillboardArtAndSeat(instance, log);

	private static Quaternion ResolveUprightPitchOnce(Transform root, ManualLogSource log)
	{
		if (!TryGetRendererBounds(root, out var size))
			return Quaternion.identity;

		var flatOnGround = size.y < size.x * 0.85f && size.y < size.z * 0.85f;
		if (!flatOnGround)
			return Quaternion.identity;

		var candidates = new[]
		{
			Quaternion.identity,
			Quaternion.Euler(-90f, 0f, 0f),
			Quaternion.Euler(90f, 0f, 0f),
			Quaternion.Euler(0f, 0f, -90f),
			Quaternion.Euler(0f, 0f, 90f)
		};
		var best = Quaternion.identity;
		var bestHeight = -1f;
		for (var i = 0; i < candidates.Length; i++)
		{
			root.localRotation = candidates[i];
			if (!TryGetRendererBounds(root, out var candidateSize))
				continue;
			if (candidateSize.y <= bestHeight)
				continue;
			bestHeight = candidateSize.y;
			best = candidates[i];
		}

		if (_poseLogRemaining > 0)
		{
			log?.LogInfo(
				"Homm3MapBuildingMeshBundle: flat upright euler="
				+ best.eulerAngles.ToString("0.#")
				+ " height="
				+ bestHeight.ToString("0.###")
				+ " fromSize="
				+ size.ToString("0.###"));
		}

		return best;
	}

	internal static void SeatBottomToParentGround(Transform root, ManualLogSource log)
	{
		if (!root || !root.parent)
			return;
		var renderers = root.GetComponentsInChildren<MeshRenderer>(true);
		if (renderers == null || renderers.Length == 0)
			return;

		Bounds? bounds = null;
		for (var i = 0; i < renderers.Length; i++)
		{
			var r = renderers[i];
			if (!r)
				continue;
			if (bounds == null)
				bounds = r.bounds;
			else
			{
				var b = bounds.Value;
				b.Encapsulate(r.bounds);
				bounds = b;
			}
		}
		if (bounds == null)
			return;

		var bFinal = bounds.Value;
		var worldBottom = new Vector3(bFinal.center.x, bFinal.min.y, bFinal.center.z);
		var localBottom = root.parent.InverseTransformPoint(worldBottom);
		var lp = root.localPosition;
		root.localPosition = new Vector3(lp.x, lp.y - localBottom.y, lp.z);
	}

	private static bool TryGetRendererBounds(Transform root, out Vector3 size)
	{
		size = Vector3.zero;
		if (!root)
			return false;
		var renderers = root.GetComponentsInChildren<MeshRenderer>(true);
		if (renderers == null || renderers.Length == 0)
			return false;
		Bounds? bounds = null;
		for (var i = 0; i < renderers.Length; i++)
		{
			var r = renderers[i];
			if (!r)
				continue;
			if (bounds == null)
				bounds = r.bounds;
			else
			{
				var b = bounds.Value;
				b.Encapsulate(r.bounds);
				bounds = b;
			}
		}
		if (bounds == null)
			return false;
		size = bounds.Value.size;
		return true;
	}

	private static void EnsureCatalog(ManualLogSource log)
	{
		if (_catalogLoadAttempted)
			return;
		_catalogLoadAttempted = true;
		_byRelativePng = new Dictionary<string, CatalogEntry>(StringComparer.OrdinalIgnoreCase);
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeCatalogPath);
		if (path == null || !File.Exists(path))
		{
			log?.LogWarning("Homm3MapBuildingMeshBundle: catalog missing at " + RelativeCatalogPath);
			return;
		}
		try
		{
			var root = Newtonsoft.Json.Linq.JObject.Parse(File.ReadAllText(path));
			var schema = root["schema"]?.ToString() ?? string.Empty;
			if (!string.Equals(schema, CatalogSchema, StringComparison.Ordinal))
			{
				throw new InvalidOperationException(
					"homm3_map_building_meshes catalog schema mismatch: expected "
					+ CatalogSchema
					+ " got "
					+ schema);
			}
			var entriesToken = root["entries"];
			var entries = entriesToken as Newtonsoft.Json.Linq.JArray
			              ?? (entriesToken != null
				              ? Newtonsoft.Json.Linq.JArray.Parse(entriesToken.ToString())
				              : null);
			if (entries == null)
				throw new InvalidOperationException("catalog missing entries array");
			for (var i = 0; i < entries.Count; i++)
			{
				var row = entries[i] as Newtonsoft.Json.Linq.JObject
				          ?? (entries[i] != null
					          ? Newtonsoft.Json.Linq.JObject.Parse(entries[i].ToString())
					          : null);
				if (row == null)
					continue;
				var relativePng = row["relativePng"]?.ToString();
				var prefabKey = row["prefabKey"]?.ToString();
				var kind = row["kind"]?.ToString() ?? "building";
				var heightToken = row["targetHeight"]?.ToString();
				var height = 2.25f;
				if (!string.IsNullOrWhiteSpace(heightToken)
				    && Homm3JsonNumber.TryParseFloat(
					    heightToken,
					    out var parsed)
				    && parsed > 0.01f)
				{
					height = parsed;
				}
				var artYaw = 0f;
				var artYawToken = row["artYawDegrees"]?.ToString();
				if (!string.IsNullOrWhiteSpace(artYawToken)
				    && Homm3JsonNumber.TryParseFloat(
					    artYawToken,
					    out var parsedYaw))
				{
					artYaw = parsedYaw;
				}
				if (string.IsNullOrWhiteSpace(relativePng) || string.IsNullOrWhiteSpace(prefabKey))
					continue;
				var entry = new CatalogEntry
				{
					RelativePng = relativePng.Replace('\\', '/'),
					PrefabKey = prefabKey,
					Kind = kind,
					TargetHeight = height,
					ArtYawDegrees = artYaw
				};
				_byRelativePng[NormalizeRelative(entry.RelativePng)] = entry;
			}
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3MapBuildingMeshBundle: catalog parse failed: " + ex.Message);
			_byRelativePng.Clear();
		}
	}

	private static string NormalizeRelative(string relativePng)
	{
		return (relativePng ?? string.Empty).Replace('\\', '/').Trim().TrimStart('/');
	}

	private static void EnsureBundle(ManualLogSource log)
	{
		if (_loadAttempted)
			return;
		_loadAttempted = true;
		var path = ResolveBundleFilePath();
		if (path == null || !File.Exists(path))
		{
			log?.LogError(
				"Homm3MapBuildingMeshBundle: bundle file missing at "
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
					"Homm3MapBuildingMeshBundle: AssetBundle.LoadFromFile returned null for " + path);
				return;
			}
			log?.LogInfo("Homm3MapBuildingMeshBundle: loaded bundle from " + path);
		}
		catch (Exception ex)
		{
			if (_loggedLoad++ < 8)
				log?.LogError(
					"Homm3MapBuildingMeshBundle: failed to load " + path + ": " + ex.Message);
			_bundle = null;
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
