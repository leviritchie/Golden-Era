using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using BepInEx.Logging;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Catalog-driven interior town-scene Meshy meshes (cityFactory world).
/// Policy: mesh = meshy-t2 untextured; materials = meshy-6 keep-lighting + PBR.
/// Gate: <see cref="LauncherConfig.Homm3TownSceneMeshes"/>. Fail-closed for catalog hits —
/// no silent HotA quad fallback when the flag is on and the layer is catalogued.
/// </summary>
internal static class Homm3TownSceneMeshBundle
{
	internal const string BundleName = "homm3_town_scene_meshes";
	internal const string RelativeBundlePath = "homm3_town_scene_meshes/homm3_town_scene_meshes";
	internal const string RelativeCatalogPath = "homm3_town_scene_meshes/catalog.json";
	internal const string RelativeManifestPath = "homm3_town_scene_meshes/manifest.json";
	internal const string MeshChildPrefix = "OfflineUnlockTownSceneMesh_";
	internal const string CatalogSchema = "homm3_town_scene_mesh_catalog.v1";
	internal const float DefaultFrontYawDegrees = 180f;

	private static AssetBundle _bundle;
	private static bool _loadAttempted;
	private static bool _catalogLoadAttempted;
	private static int _loggedLoad;
	private static Dictionary<string, CatalogEntry> _byLayerId;
	private static readonly Dictionary<string, GameObject> PrefabsByKey =
		new(StringComparer.OrdinalIgnoreCase);

	internal sealed class CatalogEntry
	{
		internal string RelativePng;
		internal string PrefabKey;
		internal string Kind;
		internal string Fraction;
		internal string BuildingSid;
		internal string LayerId;
		internal int NativeLevel;
		internal float TargetHeight;
		internal float StageDepthFromBackdrop;
	}

	internal static bool IsEnabled()
	{
		var cfg = LauncherConfigReader.TryLoad();
		return cfg != null && cfg.Homm3TownSceneMeshes;
	}

	internal static float GetRuntimeScale()
	{
		var cfg = LauncherConfigReader.TryLoad();
		if (cfg == null)
			return 1f;
		var scale = (float)cfg.Homm3TownSceneMeshesScale;
		return scale > 0.01f ? scale : 1f;
	}

	internal static bool TryGetEntryForLayer(string layerId, out CatalogEntry entry)
	{
		entry = null;
		if (string.IsNullOrWhiteSpace(layerId))
			return false;
		EnsureCatalog(null);
		if (_byLayerId == null || _byLayerId.Count == 0)
			return false;
		return _byLayerId.TryGetValue(layerId.Trim(), out entry) && entry != null;
	}

	internal static bool HasMeshForLayer(string layerId) =>
		TryGetEntryForLayer(layerId, out _);

	internal static bool TryLoadPrefab(string layerId, out GameObject prefab, out CatalogEntry entry, ManualLogSource log)
	{
		prefab = null;
		entry = null;
		if (!TryGetEntryForLayer(layerId, out entry))
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
					"Homm3TownSceneMeshBundle: LoadAsset<GameObject>('"
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
					"Homm3TownSceneMeshBundle: failed to load prefab '"
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
				"homm3TownSceneMeshes is enabled but catalog.json is missing under the deployed "
				+ "OfflineUnlockMod/homm3_town_scene_meshes folder. Run "
				+ "tools/homm3_import/build_homm3_town_scene_meshes_bundle.py "
				+ "and redeploy (or turn the flag off to keep HotA quads).",
				RelativeCatalogPath);
		}

		EnsureCatalog(log);
		if (_byLayerId == null || _byLayerId.Count == 0)
			throw new InvalidOperationException(
				"homm3TownSceneMeshes is enabled but the town-scene mesh catalog has zero entries.");

		EnsureBundle(log);
		if (_bundle == null)
		{
			throw new FileNotFoundException(
				"homm3TownSceneMeshes is enabled but the homm3_town_scene_meshes AssetBundle is missing.",
				RelativeBundlePath);
		}

		foreach (var pair in _byLayerId)
		{
			if (!TryLoadPrefab(pair.Key, out var prefab, out _, log) || !prefab)
			{
				throw new InvalidOperationException(
					"homm3TownSceneMeshes catalog layer '"
					+ pair.Key
					+ "' failed prefab load.");
			}
		}

		log?.LogInfo(
			"Homm3TownSceneMeshBundle: validated catalog ("
			+ _byLayerId.Count
			+ " entries); prefab load deferred until town apply.");
	}

	internal static bool TryRebindRenderersToCityDonor(
		GameObject meshRoot,
		Material donorMaterial,
		ManualLogSource log)
	{
		if (!meshRoot)
			return false;
		if (!donorMaterial || donorMaterial.shader == null)
		{
			log?.LogError(
				"Homm3TownSceneMeshBundle: donor material missing; refuse mesh apply.");
			return false;
		}

		var renderers = meshRoot.GetComponentsInChildren<MeshRenderer>(true);
		if (renderers == null || renderers.Length == 0)
		{
			log?.LogError("Homm3TownSceneMeshBundle: prefab instance has no MeshRenderer.");
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
					"Homm3TownSceneMeshBundle: MeshRenderer '"
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
						"Homm3TownSceneMeshBundle: material slot "
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
					name = "HOMM3_town_scene_mesh_" + (source ? source.name : "slot") + "_" + i
				};
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
				rebound[i] = clone;
			}

			renderer.sharedMaterials = rebound;
			renderer.enabled = true;
			renderer.forceRenderingOff = false;
			renderer.shadowCastingMode = ShadowCastingMode.On;
			renderer.receiveShadows = true;
		}

		return true;
	}

	/// <summary>
	/// Seat a unit-height Meshy mesh into HotA reference-rect stage depth in front of the backdrop.
	/// XY follows the same camera-plane mapping as HotA quads; depth uses
	/// <paramref name="stageDepthFromBackdrop"/> so volume is real (not coplanar 0.001 faking).
	/// </summary>
	internal static void SeatAtTownStage(
		GameObject instance,
		float referenceX,
		float referenceY,
		float referenceWidth,
		float referenceHeight,
		float canvasWidth,
		float canvasHeight,
		float backdropDistance,
		float stageDepthFromBackdrop,
		Camera camera,
		float frontYawDegrees,
		ManualLogSource log)
	{
		if (!instance || camera == null)
			throw new InvalidOperationException("Homm3TownSceneMeshBundle: cannot seat with null instance/camera.");
		if (canvasWidth <= 0f || canvasHeight <= 0f)
			throw new InvalidOperationException("Homm3TownSceneMeshBundle: invalid canvas for seating.");

		var distance = Mathf.Max(1f, backdropDistance - Mathf.Max(0.25f, stageDepthFromBackdrop));
		var frustumHeight = camera.orthographic
			? camera.orthographicSize * 2f
			: 2f * distance * Mathf.Tan(camera.fieldOfView * 0.5f * Mathf.Deg2Rad);
		var frustumWidth = frustumHeight * camera.aspect;
		var centerX = (referenceX + referenceWidth * 0.5f) / canvasWidth - 0.5f;
		var centerY = 0.5f - (referenceY + referenceHeight * 0.5f) / canvasHeight;
		var cam = camera.transform;
		var center = cam.position + cam.forward * distance
			+ cam.right * (centerX * frustumWidth) + cam.up * (centerY * frustumHeight);
		var worldHeight = referenceHeight / canvasHeight * frustumHeight;
		if (worldHeight <= 0.0001f)
			throw new InvalidOperationException("Homm3TownSceneMeshBundle: computed world height is zero.");

		var t = instance.transform;
		t.position = center;
		t.rotation = Quaternion.LookRotation(-cam.forward, cam.up)
			* Quaternion.Euler(0f, frontYawDegrees, 0f);
		t.localScale = Vector3.one;

		var renderers = instance.GetComponentsInChildren<Renderer>(true);
		if (renderers == null || renderers.Length == 0)
			throw new InvalidOperationException("Homm3TownSceneMeshBundle: no Renderer to scale.");
		var bounds = renderers[0].bounds;
		for (var i = 1; i < renderers.Length; i++)
		{
			if (renderers[i])
				bounds.Encapsulate(renderers[i].bounds);
		}
		var meshHeight = bounds.size.y;
		if (meshHeight <= 0.0001f)
			throw new InvalidOperationException("Homm3TownSceneMeshBundle: mesh bounds height is zero.");

		var scale = worldHeight / meshHeight * GetRuntimeScale();
		t.localScale = Vector3.one * scale;

		renderers = instance.GetComponentsInChildren<Renderer>(true);
		bounds = renderers[0].bounds;
		for (var i = 1; i < renderers.Length; i++)
		{
			if (renderers[i])
				bounds.Encapsulate(renderers[i].bounds);
		}
		// Put the mesh bottom on the bottom of the HotA reference rect (ground contact).
		var footY = 0.5f - (referenceY + referenceHeight) / canvasHeight;
		var foot = cam.position + cam.forward * distance
			+ cam.right * (centerX * frustumWidth) + cam.up * (footY * frustumHeight);
		var deltaY = foot.y - bounds.min.y;
		t.position += new Vector3(0f, deltaY, 0f);

		log?.LogInfo(
			"Homm3TownSceneMeshBundle: seated distance="
			+ distance.ToString("0.###", CultureInfo.InvariantCulture)
			+ " worldHeight="
			+ worldHeight.ToString("0.###", CultureInfo.InvariantCulture)
			+ " scale="
			+ scale.ToString("0.###", CultureInfo.InvariantCulture)
			+ ".");
	}

	private static void EnsureCatalog(ManualLogSource log)
	{
		if (_catalogLoadAttempted)
			return;
		_catalogLoadAttempted = true;
		_byLayerId = new Dictionary<string, CatalogEntry>(StringComparer.OrdinalIgnoreCase);
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeCatalogPath);
		if (path == null || !File.Exists(path))
		{
			log?.LogWarning("Homm3TownSceneMeshBundle: catalog missing at " + RelativeCatalogPath);
			return;
		}

		var root = JObject.Parse(File.ReadAllText(path));
		var schema = root["schema"]?.ToString();
		if (!string.Equals(schema, CatalogSchema, StringComparison.Ordinal))
		{
			throw new InvalidOperationException(
				"homm3_town_scene_meshes catalog schema mismatch: expected "
				+ CatalogSchema
				+ ", got "
				+ (schema ?? "<null>"));
		}

		// IL2CPP Newtonsoft: `as JArray` / `as JObject` often miss; re-parse via ToString like
		// Homm3MapBuildingMeshBundle. Silent empty catalog must not FailFast as "zero entries".
		var entriesToken = root["entries"];
		var rows = entriesToken as JArray
		           ?? (entriesToken != null ? JArray.Parse(entriesToken.ToString()) : null);
		if (rows == null)
			throw new InvalidOperationException(
				"homm3_town_scene_meshes catalog missing entries array at " + path);
		for (var i = 0; i < rows.Count; i++)
		{
			var row = rows[i] as JObject
			          ?? (rows[i] != null ? JObject.Parse(rows[i].ToString()) : null);
			if (row == null)
				continue;
			var layerId = ReadOptionalString(row, "layerId");
			var prefabKey = ReadOptionalString(row, "prefabKey");
			if (string.IsNullOrWhiteSpace(layerId) || string.IsNullOrWhiteSpace(prefabKey))
				continue;
			var entry = new CatalogEntry
			{
				RelativePng = ReadOptionalString(row, "relativePng") ?? string.Empty,
				PrefabKey = prefabKey.Trim(),
				Kind = ReadOptionalString(row, "kind") ?? "town_building",
				Fraction = ReadOptionalString(row, "fraction") ?? string.Empty,
				BuildingSid = ReadOptionalString(row, "buildingSid") ?? string.Empty,
				LayerId = layerId.Trim(),
				NativeLevel = ParseIntString(ReadOptionalString(row, "nativeLevel"), 1),
				TargetHeight = ParseFloatString(ReadOptionalString(row, "targetHeight"), 1f),
				StageDepthFromBackdrop = ParseFloatString(
					ReadOptionalString(row, "stageDepthFromBackdrop"),
					4f)
			};
			_byLayerId[entry.LayerId] = entry;
		}

		if (_byLayerId.Count == 0)
		{
			throw new InvalidOperationException(
				"homm3_town_scene_meshes catalog at "
				+ path
				+ " parsed with zero usable layerId/prefabKey rows (entries.Count="
				+ rows.Count
				+ ").");
		}
	}

	private static void EnsureBundle(ManualLogSource log)
	{
		if (_loadAttempted)
			return;
		_loadAttempted = true;
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeBundlePath);
		if (path == null || !File.Exists(path))
		{
			log?.LogError("Homm3TownSceneMeshBundle: bundle file missing at " + RelativeBundlePath);
			return;
		}
		try
		{
			_bundle = AssetBundle.LoadFromFile(path);
			if (_bundle == null)
				log?.LogError("Homm3TownSceneMeshBundle: LoadFromFile returned null for " + path);
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3TownSceneMeshBundle: LoadFromFile failed: " + ex.Message);
		}
	}

	/// <summary>
	/// Proxy-safe scalar read. Do not call <c>JToken.Value&lt;T&gt;</c> or rely on <c>JToken.Type</c>
	/// under IL2CPP Newtonsoft.
	/// </summary>
	private static string ReadOptionalString(JToken parent, string property)
	{
		if (parent == null || string.IsNullOrEmpty(property))
			return null;
		var token = parent[property];
		if (token == null)
			return null;
		var text = token.ToString();
		return string.IsNullOrWhiteSpace(text) ? null : text;
	}

	private static float ParseFloatString(string text, float fallback)
	{
		if (string.IsNullOrEmpty(text))
			return fallback;
		return Homm3JsonNumber.TryParseFloat(
			text,
			out var value)
			? value
			: fallback;
	}

	private static int ParseIntString(string text, int fallback)
	{
		if (string.IsNullOrEmpty(text))
			return fallback;
		return int.TryParse(
			text,
			NumberStyles.Integer,
			CultureInfo.InvariantCulture,
			out var value)
			? value
			: fallback;
	}
}
