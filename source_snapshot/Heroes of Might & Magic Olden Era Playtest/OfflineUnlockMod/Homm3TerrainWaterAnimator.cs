using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using BepInEx;
using BepInEx.Logging;
using Hex.Map;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

internal static class Homm3TerrainWaterAnimator
{
	private const string LogPrefix = "HOMM3_TERRAIN_WATER_ANIMATOR";
	private const string HostName = "HOMM3_TERRAIN_WATER_ANIMATOR_HOST";
	private const string AssetRelativeDir = "homm3_runtime_assets/custom_biomes/water_animation";
	private const string ManifestName = "water_animation_manifest.json";
	private const string ManifestSchema = "homm3.homecoming_terrain_water_animation.v1";
	private const string NativeBinding = "terrain_renderer_packed_color_layers_texture_node_upload";

	private sealed class Binding
	{
		internal object Renderer;
		internal Map Map;
		internal MethodInfo TextureNodeUploadMethod;
		internal int ExpectedLayerLength;
		internal int MapScopeGeneration;
		internal string SceneName;
		internal Dictionary<int, int> SlotsByTileCode;
		internal Dictionary<int, Il2CppStructArray<Color>[]> PreparedLayersByTileCode;
		internal string Source;
	}

	private static readonly Dictionary<long, Binding> BindingsByRendererKey = new();
	private static readonly List<long> StaleBindingIds = new();
	private static Dictionary<int, string[]> _framePathsByTileCode;
	private static ManualLogSource _log;
	private static bool _registeredType;
	private static bool _attachedHost;
	private static bool _manifestLoaded;
	private static float _frameMs = 125f;
	private static float _timerMs;
	private static int _frameIndex;
	private static int _bindingLogRemaining = 12;
	private static int _tickLogRemaining = 8;
	private static int _failureLogRemaining = 8;

	internal static Texture2D LoadSeedFrameTexture(int tileCode)
	{
		LoadRequiredManifest();
		if (_framePathsByTileCode == null || !_framePathsByTileCode.TryGetValue(tileCode, out var framePaths) || framePaths == null || framePaths.Length == 0)
		{
			throw new InvalidOperationException(
				LogPrefix + " has no seed frame for native water terrain tileCode="
				+ tileCode.ToString(CultureInfo.InvariantCulture)
				+ ".");
		}
		return LoadFrameTexture(framePaths[0]);
	}

	internal static void RegisterRequired(ManualLogSource log)
	{
		_log = log;
		LoadRequiredManifest();
		if (_attachedHost)
			return;
		if (!_registeredType)
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3TerrainWaterAnimatorHost>();
			_registeredType = true;
		}
		var go = new GameObject(HostName);
		go.hideFlags = HideFlags.HideAndDontSave;
		if (go.AddComponent<Homm3TerrainWaterAnimatorHost>() == null)
			throw new InvalidOperationException(LogPrefix + " host component registration failed.");
		UnityObject.DontDestroyOnLoad(go);
		_attachedHost = true;
		_log?.LogInfo(LogPrefix + " registered native terrain packed color layer animator frameMs=" + _frameMs.ToString(CultureInfo.InvariantCulture) + ".");
	}

	internal static void ResetBindingsForMapScopeChange(string source)
	{
		if (BindingsByRendererKey.Count == 0)
			return;
		BindingsByRendererKey.Clear();
		_timerMs = 0f;
		_frameIndex = 0;
		_log?.LogInfo(LogPrefix + " cleared packed color layer binding(s) after map scope change source=" + (source ?? "?") + ".");
	}

	internal static void RegisterTerrainPackedColorLayerBinding(
		object renderer,
		Map map,
		MethodInfo textureNodeUploadMethod,
		Il2CppReferenceArray<Il2CppStructArray<Color>> colorLayers,
		IDictionary<int, int> slotsByTileCode,
		int layerWidth,
		int layerHeight,
		long rendererKey,
		int mapScopeGeneration,
		string source)
	{
		if (renderer == null)
			throw new InvalidOperationException(LogPrefix + " packed color binding renderer was null source=" + (source ?? "?") + ".");
		if (map == null)
			throw new InvalidOperationException(LogPrefix + " packed color binding map was null source=" + (source ?? "?") + ".");
		if (textureNodeUploadMethod == null)
			throw new InvalidOperationException(LogPrefix + " packed color binding texture-node upload method was null source=" + (source ?? "?") + ".");
		if (colorLayers == null)
			throw new InvalidOperationException(LogPrefix + " packed color binding color layer array was null source=" + (source ?? "?") + ".");
		if (layerWidth <= 0 || layerHeight <= 0)
			throw new InvalidOperationException(LogPrefix + " packed color binding layer shape was invalid source=" + (source ?? "?") + ".");
		LoadRequiredManifest();
		var filtered = new Dictionary<int, int>();
		foreach (var tileCode in GameSymbols.HomecomingBoatTravel.RetiredGoldenEraWaterTileCodes)
		{
			if (slotsByTileCode == null || !slotsByTileCode.TryGetValue(tileCode, out var slot))
				continue;
			if (!_framePathsByTileCode.ContainsKey(tileCode))
				throw new InvalidOperationException(LogPrefix + " manifest does not define frames for water tileCode=" + tileCode.ToString(CultureInfo.InvariantCulture) + ".");
			if (slot < 0 || slot >= colorLayers.Length)
				throw new InvalidOperationException(LogPrefix + " packed color binding slot outside color layer array tileCode=" + tileCode.ToString(CultureInfo.InvariantCulture) + " slot=" + slot.ToString(CultureInfo.InvariantCulture) + " length=" + colorLayers.Length.ToString(CultureInfo.InvariantCulture) + ".");
			filtered[tileCode] = slot;
		}
		if (filtered.Count == 0)
			return;
		BindingsByRendererKey[rendererKey] = new Binding
		{
			Renderer = renderer,
			Map = map,
			TextureNodeUploadMethod = textureNodeUploadMethod,
			ExpectedLayerLength = layerWidth * layerHeight,
			MapScopeGeneration = mapScopeGeneration,
			SceneName = SceneManager.GetActiveScene().name ?? string.Empty,
			SlotsByTileCode = filtered,
			PreparedLayersByTileCode = PrepareLayersForTarget(layerWidth, layerHeight, filtered.Keys),
			Source = source,
		};
		ApplyFrameToBinding(BindingsByRendererKey[rendererKey], _frameIndex);
		if (_bindingLogRemaining > 0)
		{
			_bindingLogRemaining--;
			_log?.LogInfo(LogPrefix
			              + " registered terrain packed color water animation binding source="
			              + (source ?? "?")
			              + " method="
			              + textureNodeUploadMethod.Name
			              + " layerShape="
			              + layerWidth.ToString(CultureInfo.InvariantCulture)
			              + "x"
			              + layerHeight.ToString(CultureInfo.InvariantCulture)
			              + " slots="
			              + string.Join(",", filtered.OrderBy(item => item.Key).Select(item => item.Key.ToString(CultureInfo.InvariantCulture) + "->" + item.Value.ToString(CultureInfo.InvariantCulture)))
			              + ".");
		}
	}

	internal static void Tick()
	{
		if (BindingsByRendererKey.Count == 0)
			return;
		_timerMs += Math.Max(0f, Time.deltaTime) * 1000f;
		if (_timerMs < _frameMs)
			return;
		var steps = Math.Max(1, Mathf.FloorToInt(_timerMs / _frameMs));
		_timerMs -= steps * _frameMs;
		var frameCount = GetFrameCount();
		if (frameCount <= 1)
			return;
		_frameIndex = (_frameIndex + steps) % frameCount;
		StaleBindingIds.Clear();
		foreach (var entry in BindingsByRendererKey)
		{
			var binding = entry.Value;
			if (binding?.Renderer == null)
			{
				StaleBindingIds.Add(entry.Key);
				continue;
			}
			try
			{
				ApplyFrameToBinding(binding, _frameIndex);
			}
			catch (Exception ex)
			{
				LogFailure("binding removed after packed color rebuild failure source=" + (binding.Source ?? "?") + " error=" + ex.GetType().Name + ": " + ex.Message);
				StaleBindingIds.Add(entry.Key);
			}
		}
		for (var i = 0; i < StaleBindingIds.Count; i++)
			BindingsByRendererKey.Remove(StaleBindingIds[i]);
		if (_tickLogRemaining > 0)
		{
			_tickLogRemaining--;
			_log?.LogInfo(LogPrefix + " advanced native terrain water frame index=" + _frameIndex.ToString(CultureInfo.InvariantCulture) + " bindings=" + BindingsByRendererKey.Count.ToString(CultureInfo.InvariantCulture) + ".");
		}
	}

	private static Dictionary<int, Il2CppStructArray<Color>[]> PrepareLayersForTarget(int layerWidth, int layerHeight, IEnumerable<int> tileCodes)
	{
		var prepared = new Dictionary<int, Il2CppStructArray<Color>[]>();
		foreach (var tileCode in tileCodes)
		{
			var framePaths = _framePathsByTileCode[tileCode];
			var converted = new Il2CppStructArray<Color>[framePaths.Length];
			for (var index = 0; index < framePaths.Length; index++)
			{
				Texture2D frameTexture = null;
				try
				{
					frameTexture = LoadFrameTexture(framePaths[index]);
					converted[index] = Homm3SwampAutumnTintProof.BuildTerrainPackedColorLayer(frameTexture, layerWidth, layerHeight);
					if (converted[index] == null)
						throw new InvalidOperationException(LogPrefix + " could not build packed color layer for water tileCode=" + tileCode.ToString(CultureInfo.InvariantCulture) + " frame=" + index.ToString(CultureInfo.InvariantCulture) + " path=" + framePaths[index] + ".");
				}
				finally
				{
					if (frameTexture)
						UnityObject.Destroy(frameTexture);
				}
			}
			prepared[tileCode] = converted;
		}
		return prepared;
	}

	private static void ApplyFrameToBinding(Binding binding, int frameIndex)
	{
		if (!Homm3SwampAutumnTintProof.IsTerrainWaterAnimationBindingCurrent(binding.MapScopeGeneration))
			throw new InvalidOperationException(LogPrefix + " map scope generation changed for source=" + (binding.Source ?? "?") + ".");
		var currentScene = SceneManager.GetActiveScene().name ?? string.Empty;
		if (!string.Equals(currentScene, binding.SceneName ?? string.Empty, StringComparison.Ordinal))
			throw new InvalidOperationException(LogPrefix + " scene changed from " + (binding.SceneName ?? "?") + " to " + currentScene + " for source=" + (binding.Source ?? "?") + ".");
		if (!Homm3SwampAutumnTintProof.TryGetCurrentTerrainPackedColorLayers(binding.Renderer, binding.ExpectedLayerLength, out var colorLayers, out var reason))
			throw new InvalidOperationException(LogPrefix + " current packed color layers unavailable for source=" + (binding.Source ?? "?") + ": " + reason + ".");
		foreach (var item in binding.SlotsByTileCode)
		{
			if (item.Value < 0 || item.Value >= colorLayers.Length)
				throw new InvalidOperationException(LogPrefix + " water slot outside current packed color layer array tileCode=" + item.Key.ToString(CultureInfo.InvariantCulture) + " slot=" + item.Value.ToString(CultureInfo.InvariantCulture) + " length=" + colorLayers.Length.ToString(CultureInfo.InvariantCulture) + ".");
			var frames = binding.PreparedLayersByTileCode[item.Key];
			var frame = frames[frameIndex % frames.Length];
			colorLayers[item.Value] = frame;
		}
		try
		{
			binding.TextureNodeUploadMethod.Invoke(binding.Renderer, new object[] { binding.Map });
		}
		catch (TargetInvocationException ex)
		{
			throw new InvalidOperationException(LogPrefix + " native texture-node upload failed for source=" + (binding.Source ?? "?") + ".", ex.InnerException ?? ex);
		}
	}

	private static int GetFrameCount()
	{
		if (_framePathsByTileCode == null || _framePathsByTileCode.Count == 0)
			return 0;
		foreach (var framePaths in _framePathsByTileCode.Values)
			return framePaths?.Length ?? 0;
		return 0;
	}

	private static void LoadRequiredManifest()
	{
		if (_manifestLoaded)
			return;
		var manifestPath = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", AssetRelativeDir, ManifestName);
		if (!File.Exists(manifestPath))
			throw new FileNotFoundException("Required Homecoming terrain water animation manifest is missing.", manifestPath);
		var root = JObject.Parse(File.ReadAllText(manifestPath));
		if (!string.Equals((string)root["schema"], ManifestSchema, StringComparison.Ordinal))
			throw new InvalidOperationException("Unexpected Homecoming terrain water animation manifest schema: " + (string)root["schema"]);
		if (!string.Equals((string)root["nativeBinding"], NativeBinding, StringComparison.Ordinal))
			throw new InvalidOperationException("Unexpected Homecoming terrain water animation native binding: " + (string)root["nativeBinding"]);
		var fps = (float?)root["framesPerSecond"] ?? 8f;
		if (fps <= 0f)
			throw new InvalidOperationException("Homecoming terrain water animation manifest has invalid framesPerSecond=" + fps.ToString(CultureInfo.InvariantCulture) + ".");
		_frameMs = 1000f / fps;
		var expectedFrameCount = (int?)root["frameCount"] ?? 0;
		if (expectedFrameCount <= 1)
			throw new InvalidOperationException("Homecoming terrain water animation manifest must contain more than one frame.");
		var sequences = RequiredObjectToken(root, "tileCodeSequences", manifestPath);
		var loaded = new Dictionary<int, string[]>();
		foreach (var tileCode in GameSymbols.HomecomingBoatTravel.RetiredGoldenEraWaterTileCodes)
		{
			var tileCodeKey = tileCode.ToString(CultureInfo.InvariantCulture);
			var token = RequiredObjectToken(sequences, tileCodeKey, manifestPath);
			var files = RequiredArrayToken(token, "files", manifestPath);
			if (files == null || files.Count != expectedFrameCount)
				throw new InvalidOperationException("Homecoming terrain water animation tileCode=" + tileCode.ToString(CultureInfo.InvariantCulture) + " frame count mismatch.");
			var framePaths = new List<string>();
			for (var fileIndex = 0; fileIndex < files.Count; fileIndex++)
				framePaths.Add(ResolveFramePath(manifestPath, (string)files[fileIndex]));
			loaded[tileCode] = framePaths.ToArray();
		}
		_framePathsByTileCode = loaded;
		_manifestLoaded = true;
	}

	private static JObject RequiredObjectToken(JObject parent, string name, string manifestPath)
	{
		var token = parent?[name];
		if (token == null || token.Type != JTokenType.Object)
			throw new InvalidOperationException(manifestPath + ": missing object " + name + ".");
		// IL2CPP Newtonsoft proxies can make direct JObject casts return null on valid object tokens.
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
			throw new InvalidOperationException("Homecoming terrain water animation manifest contains an empty frame path.");
		var fullPath = Path.Combine(Path.GetDirectoryName(manifestPath) ?? string.Empty, relativePath.Replace('/', Path.DirectorySeparatorChar));
		if (!File.Exists(fullPath))
			throw new FileNotFoundException("Missing Homecoming terrain water animation frame.", fullPath);
		return fullPath;
	}

	private static Texture2D LoadFrameTexture(string fullPath)
	{
		if (string.IsNullOrWhiteSpace(fullPath) || !File.Exists(fullPath))
			throw new FileNotFoundException("Missing Homecoming terrain water animation frame.", fullPath ?? string.Empty);
		var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false)
		{
			name = "HOMM3_TERRAIN_WATER_ANIM_" + Path.GetFileNameWithoutExtension(fullPath),
			filterMode = FilterMode.Point,
			wrapMode = TextureWrapMode.Repeat
		};
		if (!ImageConversion.LoadImage(texture, File.ReadAllBytes(fullPath), false))
		{
			UnityObject.Destroy(texture);
			throw new InvalidOperationException("Failed to load Homecoming terrain water animation frame: " + fullPath);
		}
		texture.filterMode = FilterMode.Point;
		texture.wrapMode = TextureWrapMode.Repeat;
		return texture;
	}

	private static void LogFailure(string message)
	{
		if (_failureLogRemaining <= 0)
			return;
		_failureLogRemaining--;
		_log?.LogWarning(LogPrefix + " " + message);
	}
}

public sealed class Homm3TerrainWaterAnimatorHost : MonoBehaviour
{
	private void LateUpdate()
	{
		Homm3TerrainWaterAnimator.Tick();
	}
}
