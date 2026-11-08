using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

internal static class Homm3HomecomingWaterTileOverlayVisual
{
	private const string LogPrefix = "HOMM3_WATER_TILE_OVERLAY";
	private const string VisualRootName = "homm3_water_tile_overlay_visual";
	private const string QuadName = "quad";
	private const string AssetRelativeDir = "homm3_runtime_assets/custom_biomes/water_animation";
	private const string ManifestName = "water_animation_manifest.json";
	private const string ManifestSchema = "homm3.homecoming_terrain_water_animation.v1";
	private const float OverlayLift = 0.028f;
	private const float OverlaySize = 1.0f;

	private static readonly Dictionary<int, string> SidByTileCode = new()
	{
		{ 18, "homm3_homecoming_water_overlay_deep" },
		{ 19, "homm3_homecoming_water_overlay_shore_north" },
		{ 20, "homm3_homecoming_water_overlay_shore_south" },
		{ 21, "homm3_homecoming_water_overlay_shore_west" },
		{ 22, "homm3_homecoming_water_overlay_shore_east" },
	};

	private static readonly Dictionary<string, int> TileCodeBySid = SidByTileCode.ToDictionary(item => item.Value, item => item.Key, StringComparer.Ordinal);
	private static readonly Dictionary<string, Material> _materialBySid = new(StringComparer.Ordinal);
	private static Dictionary<string, Texture2D[]> _framesBySid;
	private static ManualLogSource _log;
	private static Mesh _horizontalQuadMesh;
	private static bool _registered;
	private static bool _manifestLoaded;
	private static float _frameMs = 125f;
	private static int _applyLogRemaining = 32;
	private static int _failureLogRemaining = 12;

	private sealed class RequiredOverlayFailure : InvalidOperationException
	{
		internal RequiredOverlayFailure(string message) : base(Homm3HomecomingWaterTileOverlayVisual.LogPrefix + " " + message)
		{
		}

		internal RequiredOverlayFailure(string message, Exception inner) : base(Homm3HomecomingWaterTileOverlayVisual.LogPrefix + " " + message, inner)
		{
		}
	}

	internal static bool IsKnownSid(string sid)
	{
		return !string.IsNullOrEmpty(sid) && TileCodeBySid.ContainsKey(sid);
	}

	internal static bool IsRequiredFailure(Exception ex)
	{
		return ex is RequiredOverlayFailure;
	}

	private static RequiredOverlayFailure RequiredFailure(string message)
	{
		return new RequiredOverlayFailure(message);
	}

	private static RequiredOverlayFailure RequiredFailure(string message, Exception inner)
	{
		return new RequiredOverlayFailure(message, inner);
	}

	internal static void RegisterRequired(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw RequiredFailure("requires Harmony to attach the map-object visual hook.");
		_log = log;
		LoadRequiredManifest();
		Homm3ImportVisuals.EnsureHomm3MapIdleAnimatorHostRequired(log, LogPrefix);
		Homm3MapObjectUnitVisualHook.RegisterRequiredReleaseSafeSlice(harmony, log);
		_registered = true;
		_log?.LogInfo(LogPrefix + " registered pathable environment-object water overlay visual sids=" + string.Join(",", TileCodeBySid.Keys.OrderBy(value => value)) + ".");
	}

	internal static bool TryApply(GameObject root, string sid, ManualLogSource log)
	{
		if (!_registered || !IsKnownSid(sid))
			return false;
		ApplyRequired(root, sid, log);
		return true;
	}

	private static void ApplyRequired(GameObject root, string sid, ManualLogSource log)
	{
		if (!root)
			throw RequiredFailure("recognized sid=" + sid + " but map-object root was null.");
		_log ??= log;
		LoadRequiredManifest();
		if (!_framesBySid.TryGetValue(sid, out var frames) || frames == null || frames.Length <= 1 || !frames[0])
			throw RequiredFailure("missing loaded animation frames for sid=" + sid + ".");

		var donorRenderer = FindBestDonorRenderer(root);
		if (!donorRenderer || !donorRenderer.sharedMaterial || !donorRenderer.sharedMaterial.shader)
			throw RequiredFailure("could not find a native Hex/Lit donor renderer for sid=" + sid + " root=" + (root.name ?? "?") + ".");

		var material = GetOrCreateOverlayMaterial(sid, donorRenderer, frames);
		RemoveExistingOverlay(root);

		var visualRoot = new GameObject(VisualRootName);
		visualRoot.transform.SetParent(root.transform, false);
		visualRoot.transform.localPosition = Vector3.up * OverlayLift;
		visualRoot.transform.localRotation = Quaternion.identity;
		visualRoot.transform.localScale = Vector3.one;
		visualRoot.layer = donorRenderer.gameObject ? donorRenderer.gameObject.layer : root.layer;
		visualRoot.SetActive(true);
		visualRoot.transform.SetSiblingIndex(root.transform.childCount - 1);

		var quadGo = new GameObject(QuadName);
		quadGo.transform.SetParent(visualRoot.transform, false);
		quadGo.transform.localPosition = Vector3.zero;
		quadGo.transform.localRotation = Quaternion.identity;
		quadGo.transform.localScale = new Vector3(OverlaySize, OverlaySize, OverlaySize);
		quadGo.layer = visualRoot.layer;

		var meshFilter = quadGo.AddComponent<MeshFilter>();
		var renderer = quadGo.AddComponent<MeshRenderer>();
		meshFilter.sharedMesh = GetOrCreateHorizontalQuadMesh();
		renderer.sharedMaterial = material;
		EsquireBattleVisualPresentation.ApplyMapRendererFlagsFromDonor(donorRenderer, visualRoot);
		renderer.enabled = true;
		renderer.forceRenderingOff = false;
		renderer.shadowCastingMode = ShadowCastingMode.Off;
		renderer.receiveShadows = false;
		renderer.allowOcclusionWhenDynamic = false;

		Homm3MapIdleTextureAnimatorRegistry.Register(material, frames, _frameMs);
		Homm3MapIdleTextureAnimatorRegistry.RegisterRenderer(renderer);
		var animator = quadGo.GetComponent<Homm3MapIdleTextureAnimator>() ?? quadGo.AddComponent<Homm3MapIdleTextureAnimator>();
		if (!animator)
		{
			RemoveExistingOverlay(root);
			throw RequiredFailure("failed to attach map idle texture animator component for sid=" + sid + ".");
		}

		HideExistingRenderers(root);
		if (_applyLogRemaining > 0)
		{
			_applyLogRemaining--;
			_log?.LogInfo(
				LogPrefix
				+ " applied sid="
				+ sid
				+ " root="
				+ (root.name ?? "?")
				+ " donor="
				+ (donorRenderer.name ?? "?")
				+ " material="
				+ (material.name ?? "?")
				+ " frames="
				+ frames.Length.ToString(CultureInfo.InvariantCulture)
				+ ".");
		}
	}

	private static void LoadRequiredManifest()
	{
		if (_manifestLoaded)
			return;
		try
		{
			LoadRequiredManifestCore();
		}
		catch (Exception ex) when (!(ex is RequiredOverlayFailure))
		{
			throw RequiredFailure("failed to load required animation manifest.", ex);
		}
	}

	private static void LoadRequiredManifestCore()
	{
		var manifestPath = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", AssetRelativeDir, ManifestName);
		if (!File.Exists(manifestPath))
			throw new FileNotFoundException("Required Homecoming water tile overlay animation manifest is missing.", manifestPath);
		var root = JObject.Parse(File.ReadAllText(manifestPath));
		if (!string.Equals((string)root["schema"], ManifestSchema, StringComparison.Ordinal))
			throw new InvalidOperationException("Unexpected Homecoming water tile overlay animation manifest schema: " + (string)root["schema"]);
		var fps = (float?)root["framesPerSecond"] ?? 8f;
		if (fps <= 0f)
			throw new InvalidOperationException("Homecoming water tile overlay animation manifest has invalid framesPerSecond=" + fps.ToString(CultureInfo.InvariantCulture) + ".");
		_frameMs = 1000f / fps;
		var expectedFrameCount = (int?)root["frameCount"] ?? 0;
		if (expectedFrameCount <= 1)
			throw new InvalidOperationException("Homecoming water tile overlay animation manifest must contain more than one frame.");
		var sequences = RequiredObjectToken(root, "tileCodeSequences", manifestPath);
		var loaded = new Dictionary<string, Texture2D[]>(StringComparer.Ordinal);
		foreach (var tileCode in GameSymbols.HomecomingBoatTravel.RetiredGoldenEraWaterTileCodes)
		{
			if (!SidByTileCode.TryGetValue(tileCode, out var sid))
				throw new InvalidOperationException(LogPrefix + " has no overlay SID for registered water tileCode=" + tileCode.ToString(CultureInfo.InvariantCulture) + ".");
			var tileCodeKey = tileCode.ToString(CultureInfo.InvariantCulture);
			var token = RequiredObjectToken(sequences, tileCodeKey, manifestPath);
			var files = RequiredArrayToken(token, "files", manifestPath);
			if (files == null || files.Count != expectedFrameCount)
				throw new InvalidOperationException("Homecoming water tile overlay tileCode=" + tileCode.ToString(CultureInfo.InvariantCulture) + " frame count mismatch.");
			var frames = new List<Texture2D>();
			for (var fileIndex = 0; fileIndex < files.Count; fileIndex++)
				frames.Add(LoadFrameTexture(ResolveFramePath(manifestPath, (string)files[fileIndex])));
			loaded[sid] = frames.ToArray();
		}
		_framesBySid = loaded;
		_manifestLoaded = true;
	}

	private static JObject RequiredObjectToken(JObject parent, string name, string manifestPath)
	{
		var token = parent?[name];
		if (token == null || token.Type != JTokenType.Object)
			throw new InvalidOperationException(manifestPath + ": missing object " + name + ".");
		return token as JObject ?? JObject.Parse(token.ToString());
	}

	private static JArray RequiredArrayToken(JObject parent, string name, string manifestPath)
	{
		var token = parent?[name];
		if (token == null || token.Type != JTokenType.Array)
			throw new InvalidOperationException(manifestPath + ": missing array " + name + ".");
		return token as JArray ?? JArray.Parse(token.ToString());
	}

	private static string ResolveFramePath(string manifestPath, string relativePath)
	{
		if (string.IsNullOrWhiteSpace(relativePath))
			throw new InvalidOperationException("Homecoming water tile overlay animation manifest contains an empty frame path.");
		var fullPath = Path.Combine(Path.GetDirectoryName(manifestPath) ?? string.Empty, relativePath.Replace('/', Path.DirectorySeparatorChar));
		if (!File.Exists(fullPath))
			throw new FileNotFoundException("Missing Homecoming water tile overlay animation frame.", fullPath);
		return fullPath;
	}

	private static Texture2D LoadFrameTexture(string fullPath)
	{
		var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false)
		{
			name = "HOMM3_WATER_TILE_OVERLAY_" + Path.GetFileNameWithoutExtension(fullPath),
			filterMode = FilterMode.Point,
			wrapMode = TextureWrapMode.Clamp
		};
		if (!ImageConversion.LoadImage(texture, File.ReadAllBytes(fullPath), false))
		{
			UnityObject.Destroy(texture);
			throw new InvalidOperationException("Failed to load Homecoming water tile overlay animation frame: " + fullPath);
		}
		texture.filterMode = FilterMode.Point;
		texture.wrapMode = TextureWrapMode.Clamp;
		return texture;
	}

	private static Material GetOrCreateOverlayMaterial(string sid, Renderer donorRenderer, Texture2D[] frames)
	{
		if (_materialBySid.TryGetValue(sid, out var cached) && cached)
		{
			Homm3ImportVisuals.RebindTownStyleUnitBillboardTexture(cached, frames[0]);
			return cached;
		}
		if (!donorRenderer || !donorRenderer.sharedMaterial || frames == null || frames.Length == 0 || !frames[0])
			throw RequiredFailure("cannot create overlay material for sid=" + sid + " without a donor material and first frame.");
		var materialName = "HOMM3_unit_map_billboard_homecoming_water_overlay_" + sid;
		var material = EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial(donorRenderer.sharedMaterial, frames[0], materialName);
		if (!material)
			throw RequiredFailure("could not create Hex/Lit overlay material for sid=" + sid + ".");
		_materialBySid[sid] = material;
		return material;
	}

	private static Renderer FindBestDonorRenderer(GameObject root)
	{
		if (!root)
			return null;
		Renderer best = null;
		var bestScore = float.NegativeInfinity;
		foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!renderer || IsUnderOverlayRoot(renderer.transform))
				continue;
			var material = renderer.sharedMaterial;
			if (!material || !material.shader)
				continue;
			var shaderName = material.shader.name ?? string.Empty;
			if (shaderName.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			var score = 0f;
			if (renderer.enabled && !renderer.forceRenderingOff)
				score += 1000f;
			if (material.renderQueue >= 2000 && material.renderQueue <= 2500)
				score += 500f;
			score += Mathf.Clamp(renderer.bounds.size.sqrMagnitude, 0f, 100f);
			if (score <= bestScore)
				continue;
			bestScore = score;
			best = renderer;
		}
		return best;
	}

	private static void HideExistingRenderers(GameObject root)
	{
		if (!root)
			return;
		foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!renderer || IsUnderOverlayRoot(renderer.transform))
				continue;
			renderer.enabled = false;
			renderer.forceRenderingOff = true;
			renderer.shadowCastingMode = ShadowCastingMode.Off;
		}
	}

	private static void RemoveExistingOverlay(GameObject root)
	{
		if (!root)
			return;
		for (var index = root.transform.childCount - 1; index >= 0; index--)
		{
			var child = root.transform.GetChild(index);
			if (!child || !string.Equals(child.name, VisualRootName, StringComparison.Ordinal))
				continue;
			child.gameObject.SetActive(false);
			UnityObject.Destroy(child.gameObject);
		}
	}

	private static bool IsUnderOverlayRoot(Transform transform)
	{
		for (var current = transform; current != null; current = current.parent)
			if (string.Equals(current.name, VisualRootName, StringComparison.Ordinal))
				return true;
		return false;
	}

	private static Mesh GetOrCreateHorizontalQuadMesh()
	{
		if (_horizontalQuadMesh)
			return _horizontalQuadMesh;
		_horizontalQuadMesh = new Mesh { name = "HOMM3_homecoming_water_tile_overlay_quad" };
		_horizontalQuadMesh.vertices = new[]
		{
			new Vector3(-0.5f, 0f, -0.5f),
			new Vector3(0.5f, 0f, -0.5f),
			new Vector3(-0.5f, 0f, 0.5f),
			new Vector3(0.5f, 0f, 0.5f)
		};
		_horizontalQuadMesh.uv = new[] { new Vector2(0f, 0f), new Vector2(1f, 0f), new Vector2(0f, 1f), new Vector2(1f, 1f) };
		_horizontalQuadMesh.triangles = new[] { 0, 2, 1, 2, 3, 1 };
		_horizontalQuadMesh.RecalculateNormals();
		_horizontalQuadMesh.RecalculateBounds();
		return _horizontalQuadMesh;
	}

	private static void LogFailure(string message)
	{
		if (_failureLogRemaining <= 0)
			return;
		_failureLogRemaining--;
		_log?.LogWarning(LogPrefix + " " + message);
	}
}
