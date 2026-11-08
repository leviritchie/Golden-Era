using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using BepInEx;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Two-layer animation player for HoMM3 Stronghold building DEF animations.
///
/// HoMM3 building DEFs encode frame 0 as the full building backdrop (identical to the
/// static PNG) and frames 1-N as overlay-only content (animated fire/smoke/creature with
/// transparent background). The game originally renders these in two passes: backdrop first,
/// overlay on top. We replicate this with two RawImages:
///
///   _targetImage  — the base layer, permanently shows frame 0 (full building)
///   _overlayImage — a child RawImage that cycles all frames; transparent pixels
///                   let the base show through
///
/// Driven by HoMM3 DEF frame PNGs extracted by tools/extract_stronghold_town_anims.py.
/// Attached automatically by Homm3StrongholdTownLayers when animation metadata exists.
/// Coexists with Homm3StrongholdTownBuildEffects fade-in (overlay alpha tracks base alpha).
/// </summary>
public sealed class Homm3StrongholdTownAnimPlayer : MonoBehaviour
{
	private const string AnimFolderName = "anims";
	private const string MetadataFileName = "metadata.json";
	private const string OverlayObjectName = "Homm3AnimOverlay";

	private static bool _registered;
	private static readonly Dictionary<string, Dictionary<string, JObject>> _metadataCacheByRoot = new Dictionary<string, Dictionary<string, JObject>>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, string> _metadataStampByRoot = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, CachedFrameSet> _frameSetsByCacheKey = new Dictionary<string, CachedFrameSet>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, string> _cacheKeyByAnimId = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
	private static readonly HashSet<string> _loggedLookupAttempts = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
	private static bool _diagFired;

	private RawImage _targetImage;
	private RawImage _overlayImage;
	private Texture2D[] _frames;
	private string _layerRootRelativePath;
	private string _initializedResolvedKey;
	private float _frameRateMs = 100f;
	private float _timer;
	private int _currentFrame;
	private bool _started;

	private sealed class CachedFrameSet
	{
		internal CachedFrameSet(Texture2D[] frames)
		{
			Frames = frames;
		}

		internal Texture2D[] Frames { get; }
	}

	internal static IReadOnlyDictionary<string, JObject> GetMetadata(string fraction, bool requireValidMetadata = false)
	{
		var layerRoot = ResolveTownLayerRootRelativePath(fraction);
		if (layerRoot == null)
		{
			return new Dictionary<string, JObject>(StringComparer.OrdinalIgnoreCase);
		}

		var jsonPath = ResolveExistingPath(Path.Combine(layerRoot, AnimFolderName, MetadataFileName), logMissing: false);
		var stamp = jsonPath != null ? GetTextureStamp(jsonPath) : null;
		if (!requireValidMetadata
			&& _metadataCacheByRoot.TryGetValue(layerRoot, out var cached)
			&& _metadataStampByRoot.TryGetValue(layerRoot, out var cachedStamp)
			&& string.Equals(cachedStamp, stamp, StringComparison.Ordinal))
		{
			return cached;
		}

		var parsed = LoadMetadata(jsonPath, requireValidMetadata);
		_metadataStampByRoot[layerRoot] = stamp;
		_metadataCacheByRoot[layerRoot] = parsed;
		return parsed;
	}

	private static Dictionary<string, JObject> LoadMetadata(string jsonPath, bool requireValidMetadata = false)
	{
		var result = new Dictionary<string, JObject>(StringComparer.OrdinalIgnoreCase);
		if (jsonPath == null || !File.Exists(jsonPath))
		{
			if (requireValidMetadata)
				throw new InvalidOperationException("required town animation metadata.json is missing at " + (jsonPath ?? "(null)") + ".");
			return result;
		}

		try
		{
			// IL2CPP-safe: use JArray with index-based access (JProperty casts don't work in IL2CPP proxy).
			var arr = JArray.Parse(File.ReadAllText(jsonPath));
			for (var i = 0; i < arr.Count; i++)
			{
				JObject entry;
				try
				{
					entry = JObject.Parse(arr[i].ToString());
				}
				catch
				{
					if (requireValidMetadata)
						throw new InvalidOperationException("metadata.json has an invalid animation entry at index " + i + " in " + jsonPath + ".");
					continue;
				}

				var id = entry["id"]?.ToString();
				if (string.IsNullOrWhiteSpace(id))
				{
					if (requireValidMetadata)
						throw new InvalidOperationException("metadata.json animation entry " + i + " has no id in " + jsonPath + ".");
					continue;
				}
				if (requireValidMetadata && result.ContainsKey(id))
					throw new InvalidOperationException("metadata.json contains duplicate animation id " + id + " in " + jsonPath + ".");
				if (!string.IsNullOrEmpty(id))
				{
					result[id] = entry;
				}
			}
		}
		catch (Exception ex)
		{
			if (requireValidMetadata)
				throw new InvalidOperationException("required town animation metadata is invalid at " + jsonPath + ": " + ex.Message, ex);
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town anims: failed to parse metadata.json: " + ex.Message);
		}

		return result;
	}

	/// <summary>
	/// Returns the animation lookup key for a layer ID and building level.
	/// </summary>
	internal static string BuildAnimKey(string layerId, int level)
	{
		if (string.IsNullOrEmpty(layerId))
		{
			return null;
		}

		return layerId + "_" + level;
	}

	/// <summary>
	/// Attempt to attach or return an existing anim player for a given RawImage.
	/// Returns null if no animation metadata exists for this layer+level.
	/// </summary>
	internal static Homm3StrongholdTownAnimPlayer TryAttach(RawImage image, string fraction, string layerId, int level)
	{
		if (image == null || !image)
		{
			return null;
		}

		var key = BuildAnimKey(layerId, level);
		if (key == null)
		{
			return null;
		}

		var layerRoot = ResolveTownLayerRootRelativePath(fraction);
		if (layerRoot == null)
		{
			return null;
		}

		FireDiagnosticOnce(fraction);

		var metadata = GetMetadata(fraction);
		var resolved = TryResolveAnimationMetadata(metadata, fraction, layerId, level, key, out var animMeta, out var resolvedKey);
		if (Homm3DiagnosticFlags.IsEnabled("homm3_town_layers_diag.flag") && _loggedLookupAttempts.Add(key))
		{
			var found = resolved ? "FOUND " + resolvedKey : "NOT FOUND";
			Plugin.LogSource?.LogInfo(
				"HoMM3 Stronghold town anims: lookup layerId='" + layerId +
				"' level=" + level + " key='" + key + "' => " + found +
				" (metadata has " + metadata.Count + " entries: " +
				string.Join(", ", metadata.Keys) + ")");
		}

		if (!resolved)
		{
			return null;
		}

		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3StrongholdTownAnimPlayer>();
				_registered = true;
			}

			var existing = image.GetComponent<Homm3StrongholdTownAnimPlayer>();
			if (existing != null)
			{
				existing.InitializeFrames(image, layerRoot, animMeta, resolvedKey);
				return existing;
			}

			var added = image.gameObject.AddComponent<Homm3StrongholdTownAnimPlayer>();
			added?.InitializeFrames(image, layerRoot, animMeta, resolvedKey);
			return added;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town anims: attach failed: " + ex.Message);
			return null;
		}
	}

	internal static int ValidateFactionAnimationSourcesOrFail(string fraction)
	{
		var metadata = GetMetadata(fraction, requireValidMetadata: true);
		if (metadata == null || metadata.Count == 0)
			throw new InvalidOperationException("required town animation metadata is missing or empty for " + fraction + ".");

		var layerRoot = ResolveTownLayerRootRelativePath(fraction);
		if (layerRoot == null)
			throw new InvalidOperationException("town animation root is unresolved for " + fraction + ".");

		var missingSources = new List<string>();
		var checkedFrames = 0;
		foreach (var pair in metadata)
		{
			var animMeta = pair.Value;
			var framesToken = animMeta?["frames"];
			if (framesToken == null)
			{
				missingSources.Add(pair.Key + " has no frames declaration");
				continue;
			}

			JArray frames;
			try
			{
				frames = JArray.Parse(framesToken.ToString());
			}
			catch (Exception ex)
			{
				missingSources.Add(pair.Key + " has invalid frames metadata: " + ex.Message);
				continue;
			}
			if (frames.Count == 0)
			{
				missingSources.Add(pair.Key + " has an empty frames list");
				continue;
			}

			var animId = animMeta["id"]?.ToString();
			if (string.IsNullOrWhiteSpace(animId))
				animId = pair.Key;
			if (!IsSingleDirectoryComponent(animId))
			{
				missingSources.Add(pair.Key + " has an invalid animation id (expected one directory name): " + animId);
				continue;
			}

			var frameDir = ResolveAnimationDirectory(layerRoot, animId);
			if (frameDir == null)
			{
				missingSources.Add(pair.Key + " frame directory is missing or outside the animation root");
				continue;
			}

			for (var i = 0; i < frames.Count; i++)
			{
				var frameName = frames[i]?.ToString();
				if (string.IsNullOrWhiteSpace(frameName))
				{
					missingSources.Add(pair.Key + " has an empty frame path at index " + i);
					continue;
				}

				var path = ResolveContainedChildPath(frameDir, frameName);
				if (path == null)
					missingSources.Add(pair.Key + " frame path escapes its animation directory: " + frameName);
				else if (!File.Exists(path))
					missingSources.Add(pair.Key + " -> " + path);
				else
					checkedFrames++;
			}
		}

		if (missingSources.Count > 0)
		{
			var summary = string.Join(", ", missingSources.Take(12));
			if (missingSources.Count > 12)
				summary += ", ... (" + (missingSources.Count - 12) + " more)";
			throw new InvalidOperationException("required town animation sources are invalid for " + fraction + ": " + summary + ".");
		}

		return checkedFrames;
	}

	internal static int PrewarmFactionAnimations(string fraction, out int animatedEntries, out int failedEntries)
	{
		animatedEntries = 0;
		failedEntries = 0;
		var metadata = GetMetadata(fraction);
		if (metadata == null || metadata.Count == 0)
			return 0;

		var layerRoot = ResolveTownLayerRootRelativePath(fraction);
		if (layerRoot == null)
			return 0;

		var loadedFrames = 0;
		foreach (var pair in metadata)
		{
			animatedEntries++;
			try
			{
				var animMeta = pair.Value;
				var framesArr = animMeta?["frames"];
				if (framesArr == null)
				{
					failedEntries++;
					continue;
				}

				JArray arr;
				try
				{
					arr = JArray.Parse(framesArr.ToString());
				}
				catch
				{
					failedEntries++;
					continue;
				}

				var animId = animMeta["id"]?.ToString();
				if (string.IsNullOrWhiteSpace(animId))
					animId = pair.Key;
				var frameDir = ResolveAnimationDirectory(layerRoot, animId);
				if (frameDir == null)
				{
					failedEntries++;
					Plugin.LogSource?.LogWarning("HoMM3 Stronghold town anims: invalid or missing frame directory for " + animId);
					continue;
				}

				var animCacheId = frameDir + "|" + animId;
				var cacheKey = BuildFrameCacheKey(animId, frameDir, arr);
				if (string.IsNullOrEmpty(cacheKey))
				{
					failedEntries++;
					continue;
				}

				var frames = GetOrLoadFrames(animCacheId, cacheKey, frameDir, arr);
				if (frames == null)
				{
					failedEntries++;
					continue;
				}

				for (var i = 0; i < frames.Length; i++)
				{
					if (frames[i] != null && frames[i])
						loadedFrames++;
				}
			}
			catch (Exception ex)
			{
				failedEntries++;
				Plugin.LogSource?.LogWarning("HoMM3 Stronghold town anims: prewarm failed for " + pair.Key + ": " + ex.Message);
			}
		}

		return loadedFrames;
	}

	private static bool TryResolveAnimationMetadata(
		IReadOnlyDictionary<string, JObject> metadata,
		string fraction,
		string layerId,
		int level,
		string levelKey,
		out JObject animMeta,
		out string resolvedKey)
	{
		animMeta = null;
		resolvedKey = null;

		if (metadata == null || string.IsNullOrEmpty(layerId))
		{
			return false;
		}

		if (!string.IsNullOrEmpty(levelKey) && metadata.TryGetValue(levelKey, out animMeta))
		{
			resolvedKey = levelKey;
			return true;
		}

		if (metadata.TryGetValue(layerId, out animMeta))
		{
			resolvedKey = layerId;
			return true;
		}

		var aliasKey = ResolveAnimationAlias(fraction, layerId, level);
		if (!string.IsNullOrEmpty(aliasKey) && metadata.TryGetValue(aliasKey, out animMeta))
		{
			resolvedKey = aliasKey;
			return true;
		}

		return false;
	}

	private static string ResolveAnimationAlias(string fraction, string layerId, int level)
	{
		if (string.IsNullOrWhiteSpace(fraction) || string.IsNullOrWhiteSpace(layerId))
		{
			return null;
		}

		if (string.Equals(fraction, "homm3_tower", StringComparison.OrdinalIgnoreCase))
		{
			// Tower static layers now use original HoMM3 TBTW ids for correct placement.
			// The available multi-frame DEF extractions still use the older synthetic
			// dwellingUp2Lvl* ids, so bridge only the known animated dwelling layers.
			switch (layerId)
			{
				case "tbtwdw_0":
					return level <= 2 ? "dwellingUp2Lvl1_1" : null;
				case "tbtwdw_2":
					return level <= 2 ? "dwellingUp2Lvl3_1" : null;
				case "tbtwdw_6":
					return level <= 2 ? "dwellingUp2Lvl7_1" : null;
			}
		}

		return null;
	}

	private void InitializeFrames(RawImage image, string layerRootRelativePath, JObject animMeta, string resolvedKey)
	{
		if (image == null || !image || string.IsNullOrEmpty(layerRootRelativePath) || animMeta == null)
		{
			return;
		}

		_targetImage = image;
		_layerRootRelativePath = layerRootRelativePath;

		// Cheap idempotent skip before frame-directory stamp walks.
		if (_started
			&& string.Equals(_initializedResolvedKey, resolvedKey, StringComparison.Ordinal)
			&& HasLiveFrame(_frames))
		{
			return;
		}

		// Read frame rate
		var frMs = animMeta["frameRateMs"];
		if (frMs != null)
		{
			Homm3JsonNumber.TryParseFloat(frMs.ToString(), out _frameRateMs);
		}

		// Read frame list
		var framesArr = animMeta["frames"];
		if (framesArr == null)
		{
			return;
		}

		JArray arr;
		try
		{
			arr = JArray.Parse(framesArr.ToString());
		}
		catch
		{
			return;
		}

		var animId = animMeta["id"]?.ToString();
		if (string.IsNullOrWhiteSpace(animId))
		{
			animId = !string.IsNullOrWhiteSpace(resolvedKey)
				? resolvedKey
				: StripLayerObjectNamePrefix(image.gameObject.name);
		}

		var frameDir = ResolveAnimationDirectory(_layerRootRelativePath, animId);

		if (frameDir == null)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town anims: invalid or missing frame directory for " + animId);
			return;
		}

		var animCacheId = frameDir + "|" + animId;
		var cacheKey = BuildFrameCacheKey(animId, frameDir, arr);
		if (string.IsNullOrEmpty(cacheKey))
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town anims: frame path is invalid or escapes its animation directory for " + animId);
			return;
		}

		_frames = GetOrLoadFrames(animCacheId, cacheKey, frameDir, arr);
		if (_frames != null && _frames.Length > 0)
		{
			_timer = 0f;
			_currentFrame = 0;

			// Frame 0 is the full-building backdrop — stays on the base RawImage permanently.
			if (_frames[0] != null && _frames[0])
			{
				_targetImage.texture = _frames[0];
			}

			// Overlay child cycles through all frames; transparent pixels reveal the base.
			EnsureOverlayImage(image);
			if (_overlayImage != null && _overlayImage)
			{
				_overlayImage.color = _targetImage.color;
				SetOverlayFrame(_frames[0]);
			}

			_initializedResolvedKey = resolvedKey;
			_started = true;
		}
	}

	private static string BuildFrameCacheKey(string strippedId, string frameDir, JArray arr)
	{
		if (string.IsNullOrEmpty(strippedId) || string.IsNullOrEmpty(frameDir) || arr == null || arr.Count == 0)
			return null;

		var parts = new List<string>(arr.Count + 1) { frameDir + "|" + strippedId };
		for (var i = 0; i < arr.Count; i++)
		{
			var frameName = arr[i].ToString();
			var resolved = ResolveContainedChildPath(frameDir, frameName);
			if (resolved == null)
				return null;
			parts.Add(frameName + "@" + (GetTextureStamp(resolved) ?? "missing"));
		}
		return string.Join("|", parts);
	}

	private static Texture2D[] GetOrLoadFrames(string animCacheId, string cacheKey, string frameDir, JArray arr)
	{
		if (_frameSetsByCacheKey.TryGetValue(cacheKey, out var cached) && cached != null)
		{
			if (HasLiveFrame(cached.Frames))
				return cached.Frames;
			_frameSetsByCacheKey.Remove(cacheKey);
		}

		if (_cacheKeyByAnimId.TryGetValue(animCacheId, out var previousKey)
			&& !string.Equals(previousKey, cacheKey, StringComparison.OrdinalIgnoreCase)
			&& _frameSetsByCacheKey.TryGetValue(previousKey, out var oldSet))
		{
			DestroyFrameSet(oldSet);
			_frameSetsByCacheKey.Remove(previousKey);
		}

		var frames = new Texture2D[arr.Count];
		for (var i = 0; i < arr.Count; i++)
		{
			var frameName = arr[i].ToString();
			var resolved = ResolveContainedChildPath(frameDir, frameName);
			if (resolved == null)
			{
				Plugin.LogSource?.LogWarning("HoMM3 Stronghold town anims: frame path escapes its animation directory: " + frameName);
				return null;
			}
			if (!File.Exists(resolved))
			{
				Plugin.LogSource?.LogWarning("HoMM3 Stronghold town anims: missing frame " + resolved);
				continue;
			}

			frames[i] = LoadFrameTexture(resolved, frameName);
		}

		var frameSet = new CachedFrameSet(frames);
		_frameSetsByCacheKey[cacheKey] = frameSet;
		_cacheKeyByAnimId[animCacheId] = cacheKey;
		return frames;
	}

	private static bool HasLiveFrame(Texture2D[] frames)
	{
		if (frames == null)
			return false;
		for (var i = 0; i < frames.Length; i++)
		{
			if (frames[i] != null && frames[i])
				return true;
		}
		return false;
	}

	private static Texture2D LoadFrameTexture(string path, string frameName)
	{
		try
		{
			var rawBytes = File.ReadAllBytes(path);
			var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
			var il2cppBytes = new Il2CppStructArray<byte>(rawBytes.LongLength);
			for (var j = 0; j < rawBytes.Length; j++) il2cppBytes[j] = rawBytes[j];
			if (!ImageConversion.LoadImage(tex, il2cppBytes))
			{
				Destroy(tex);
				return null;
			}

			tex.name = frameName;
			tex.filterMode = FilterMode.Bilinear;
			tex.wrapMode = TextureWrapMode.Clamp;
			tex.hideFlags = HideFlags.DontUnloadUnusedAsset;
			return tex;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town anims: failed to load frame " + frameName + ": " + ex.Message);
			return null;
		}
	}

	private static void DestroyFrameSet(CachedFrameSet frameSet)
	{
		var frames = frameSet?.Frames;
		if (frames == null)
			return;

		for (var i = 0; i < frames.Length; i++)
		{
			if (frames[i] != null && frames[i])
			{
				Destroy(frames[i]);
			}
		}
	}

	private void EnsureOverlayImage(RawImage baseImage)
	{
		if (_overlayImage != null && _overlayImage)
		{
			return;
		}

		_overlayImage = null;

		// Try to reuse an existing overlay child (e.g. from a previous InitializeFrames call).
		var existingT = baseImage.transform.Find(OverlayObjectName);
		if (existingT != null)
		{
			_overlayImage = existingT.GetComponent<RawImage>();
			if (_overlayImage != null && _overlayImage)
			{
				return;
			}
		}

		try
		{
			var go = new GameObject(OverlayObjectName);
			var rect = go.AddComponent<RectTransform>();
			_overlayImage = go.AddComponent<RawImage>();
			rect.SetParent(baseImage.rectTransform, false);
			// Stretch to fill the base image's rect exactly.
			rect.anchorMin = Vector2.zero;
			rect.anchorMax = Vector2.one;
			rect.offsetMin = Vector2.zero;
			rect.offsetMax = Vector2.zero;
			rect.localScale = Vector3.one;
			rect.localRotation = Quaternion.identity;
			_overlayImage.raycastTarget = false;
			_overlayImage.maskable = false;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town anims: overlay create failed: " + ex.Message);
			_overlayImage = null;
		}
	}

	private void SetOverlayFrame(Texture2D frame)
	{
		if (_overlayImage == null || !_overlayImage)
		{
			return;
		}

		if (frame != null && frame)
		{
			_overlayImage.texture = frame;
			if (!_overlayImage.enabled)
			{
				_overlayImage.enabled = true;
			}
			return;
		}

		_overlayImage.texture = null;
		if (_overlayImage.enabled)
		{
			_overlayImage.enabled = false;
		}
	}

	private static void FireDiagnosticOnce(string fraction)
	{
		if (!Homm3DiagnosticFlags.IsEnabled("homm3_town_layers_diag.flag"))
		{
			return;
		}

		if (_diagFired)
		{
			return;
		}

		_diagFired = true;
		var meta = GetMetadata(fraction);
		Plugin.LogSource?.LogInfo(
			"HoMM3 Stronghold town anims: metadata loaded, " + meta.Count +
			" animated entries. Keys: [" + string.Join(", ", meta.Keys) + "]");
	}

	private static string ResolveTownLayerRootRelativePath(string fraction)
	{
		var folderName = ResolveTownLayerFolderName(fraction);
		return folderName == null
			? null
			: Path.Combine("homm3_runtime_assets", "town_scene_refs", folderName, "layers");
	}

	private static string ResolveTownLayerFolderName(string fraction)
	{
		if (string.IsNullOrEmpty(fraction))
		{
			return null;
		}

		if (Homm3CustomFactionRegistry.IsCustomFactionSid(fraction))
			return fraction.Trim();

		if (string.Equals(fraction, "dungeon_raw", StringComparison.OrdinalIgnoreCase))
			return "homm3_stronghold";

		return null;
	}

	private static string StripLayerObjectNamePrefix(string gameObjectName)
	{
		if (string.IsNullOrEmpty(gameObjectName))
		{
			return gameObjectName;
		}

		const string prefix = "OfflineUnlockStrongholdTownLayer_";
		return gameObjectName.StartsWith(prefix, StringComparison.Ordinal)
			? gameObjectName.Substring(prefix.Length)
			: gameObjectName;
	}

	private void Update()
	{
		if (!_started || _frames == null || _frames.Length == 0
			|| _targetImage == null || !_targetImage
			|| _overlayImage == null || !_overlayImage)
		{
			return;
		}

		// Track base image alpha so the overlay fades in alongside the base during build effects.
		var baseAlpha = _targetImage.color.a;
		var oc = _overlayImage.color;
		if (Math.Abs(oc.a - baseAlpha) > 0.001f)
		{
			_overlayImage.color = new Color(oc.r, oc.g, oc.b, baseAlpha);
		}

		_timer += Time.unscaledDeltaTime * 1000f;
		if (_timer < _frameRateMs)
		{
			return;
		}

		_timer -= _frameRateMs;
		_currentFrame = (_currentFrame + 1) % _frames.Length;

		var frame = _frames[_currentFrame];
		SetOverlayFrame(frame);
	}

	private void OnDestroy()
	{
		if (_overlayImage != null && _overlayImage)
		{
			Destroy(_overlayImage.gameObject);
			_overlayImage = null;
		}

		_frames = null;
	}

	private static string ResolveExistingPath(string relativePath, bool logMissing = true)
	{
		var underPlugin = Path.GetFullPath(Path.Combine(Paths.PluginPath, "OfflineUnlockMod", relativePath));
		if (File.Exists(underPlugin))
		{
			return underPlugin;
		}

		var legacy = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "OfflineUnlockMod", relativePath));
		if (File.Exists(legacy))
		{
			return legacy;
		}

		return null;
	}

	private static string ResolveExistingDirectory(string relativePath)
	{
		var underPlugin = Path.GetFullPath(Path.Combine(Paths.PluginPath, "OfflineUnlockMod", relativePath));
		if (Directory.Exists(underPlugin))
		{
			return underPlugin;
		}

		var legacy = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "OfflineUnlockMod", relativePath));
		if (Directory.Exists(legacy))
		{
			return legacy;
		}

		return null;
	}

	private static string ResolveAnimationDirectory(string layerRootRelativePath, string animId)
	{
		if (!IsSingleDirectoryComponent(animId))
			return null;

		var animRoot = ResolveExistingDirectory(Path.Combine(layerRootRelativePath, AnimFolderName));
		if (animRoot == null)
			return null;

		var frameDir = ResolveContainedChildPath(animRoot, animId);
		return frameDir != null && Directory.Exists(frameDir) ? frameDir : null;
	}

	private static bool IsSingleDirectoryComponent(string value)
	{
		return !string.IsNullOrWhiteSpace(value)
			&& value != "."
			&& value != ".."
			&& !Path.IsPathRooted(value)
			&& value.IndexOf('/') < 0
			&& value.IndexOf('\\') < 0
			&& value.IndexOfAny(Path.GetInvalidFileNameChars()) < 0;
	}

	private static string ResolveContainedChildPath(string rootDirectory, string relativePath)
	{
		if (string.IsNullOrWhiteSpace(rootDirectory)
			|| string.IsNullOrWhiteSpace(relativePath)
			|| Path.IsPathRooted(relativePath))
			return null;

		var canonicalRoot = Path.GetFullPath(rootDirectory);
		var candidate = Path.GetFullPath(Path.Combine(canonicalRoot, relativePath));
		var rootPrefix = canonicalRoot.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
			+ Path.DirectorySeparatorChar;
		return candidate.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase) ? candidate : null;
	}

	private static string GetTextureStamp(string path)
	{
		try
		{
			if (!File.Exists(path))
			{
				return null;
			}

			var info = new FileInfo(path);
			return info.Length + ":" + info.LastWriteTimeUtc.Ticks;
		}
		catch
		{
			return null;
		}
	}
}
