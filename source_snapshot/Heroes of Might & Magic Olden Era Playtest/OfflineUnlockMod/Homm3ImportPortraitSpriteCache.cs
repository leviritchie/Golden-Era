using System;
using System.Collections.Generic;
using System.IO;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Shared portrait <see cref="Sprite"/> cache for HoMM3-imported unit SIDs. Used by tooltip and slot hooks
/// (<see cref="Homm3ImportTooltipPortraitHook"/>, <see cref="Homm3ImportArmyStripPortraitHook"/>) so a PNG is
/// loaded once per sid and the same sprite instance is reused across UI surfaces.
/// </summary>
internal static class Homm3ImportPortraitSpriteCache
{
	internal const string UpscaledHeroPortraitFolder = "homm3_hero_portraits_upscaled";
	internal const string StandardHeroPortraitFolder = "homm3_hero_portraits";

	private static readonly Dictionary<string, Sprite> SpritesBySid = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedBundleResolution = new(StringComparer.Ordinal);
	private static Dictionary<string, string> _heroPortraitAliases;
	private static HashSet<string> _requiredHeroPortraitKeys;

	internal static bool TryGetOrCreateStrongholdHeroSpriteForIconKey(string iconKey, out Sprite sprite)
	{
		sprite = null;
		var sid = NormalizeHomm3HeroPortraitKey(iconKey);
		return sid != null && TryGetOrCreateSprite(sid, out sprite) && sprite;
	}

	internal static bool TryGetOrCreateSprite(string sid, out Sprite sprite)
	{
		sprite = null;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var key = sid.Trim();
		if (TryGetCachedPortraitSprite(key, allowBattleFallback: true, out sprite))
			return true;

		// Phase 2 pilot: homm3_ui_portraits AssetBundle before PNG decode; PNG stays the per-sid fallback.
		if (TryGetOrCreateBundlePortraitSprite(key, out sprite) && sprite)
			return true;

		Texture2D texture = null;
		if (TryLoadStaticPortraitTexture(key, out texture) && texture != null)
			return CreateAndCacheSprite(key, texture, "homm3_static_portrait_", out sprite);

		if (Homm3ImportVisuals.TryGetBattleTemplateForUnitSid(key, Plugin.LogSource, out var template) && template)
			texture = BattlePrefabPortraitTexture.TryGetFirstTexture(template);

		if (texture == null)
			return false;

		return CreateAndCacheSprite(key, texture, "homm3_preview_", out sprite);
	}

	/// <summary>
	/// UI surfaces that must show HoMM3 interface portraits (hero specialization, etc.) must not
	/// reuse battle-prefab fallback textures cached by <see cref="TryGetOrCreateSprite"/>.
	/// </summary>
	internal static bool TryGetOrCreateStaticPortraitSprite(string sid, out Sprite sprite)
	{
		sprite = null;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var key = sid.Trim();
		if (TryGetCachedPortraitSprite(key, allowBattleFallback: false, out sprite))
			return true;
		// Phase 2 pilot: homm3_ui_portraits AssetBundle before PNG decode; PNG stays the per-sid fallback.
		if (TryGetOrCreateBundlePortraitSprite(key, out sprite) && sprite)
			return true;
		if (!TryLoadStaticPortraitTexture(key, out var texture) || texture == null)
			return false;
		return CreateAndCacheSprite(key, texture, "homm3_static_portrait_", out sprite);
	}

	private static bool TryGetCachedPortraitSprite(string sid, bool allowBattleFallback, out Sprite sprite)
	{
		sprite = null;
		if (!SpritesBySid.TryGetValue(sid, out sprite) || !sprite)
			return false;
		var name = sprite.name ?? string.Empty;
		if (name.StartsWith("homm3_static_portrait_", StringComparison.Ordinal))
			return true;
		if (allowBattleFallback && name.StartsWith("homm3_preview_", StringComparison.Ordinal))
			return true;
		sprite = null;
		return false;
	}

	/// <summary>
	/// Phase 2 pilot: when <c>homm3UseUiPortraitBundles</c> is on, load the portrait from the
	/// homm3_ui_portraits AssetBundle before any PNG decode. On a hit the shared bundle sprite is
	/// renamed to the <c>homm3_static_portrait_</c> convention so every downstream name-based check
	/// (cache quality gate, stale-override clearers) treats it exactly like the PNG-created sprite;
	/// renaming does not affect future <c>AssetBundle.LoadAsset</c> lookups (container-keyed).
	/// Misses fall through to the existing PNG path and are logged once per sid (bundle-hit/bundle-miss).
	/// </summary>
	private static bool TryGetOrCreateBundlePortraitSprite(string sid, out Sprite sprite)
	{
		sprite = null;
		if (!Homm3UiPortraitBundle.IsEnabled())
			return false;
		foreach (var candidate in EnumeratePortraitKeyCandidates(sid))
		{
			var assetName = Homm3UiPortraitBundle.BuildAssetName(candidate);
			if (!Homm3UiPortraitBundle.TryLoadSprite(assetName, out var loaded) || !loaded)
				continue;
			loaded.name = "homm3_static_portrait_" + sid;
			SpritesBySid[sid] = loaded;
			sprite = loaded;
			LogBundlePortraitResolution(sid, hit: true);
			return true;
		}
		LogBundlePortraitResolution(sid, hit: false);
		return false;
	}

	private static void LogBundlePortraitResolution(string sid, bool hit)
	{
		if (!LoggedBundleResolution.Add(sid))
			return;
		Plugin.LogSource?.LogInfo(
			"Homm3Import portrait cache: "
			+ (hit ? "bundle-hit" : "bundle-miss")
			+ " sid='"
			+ sid
			+ "' (homm3_ui_portraits"
			+ (hit ? "" : "; falling back to PNG")
			+ ").");
	}

	/// <summary>
	/// Candidate portrait keys in the same order the PNG resolver tries filenames: the sid itself,
	/// hero icon-key normalization, the reverse hero form, then manifest alias (+ its normalization).
	/// </summary>
	private static IEnumerable<string> EnumeratePortraitKeyCandidates(string sid)
	{
		var seen = new HashSet<string>(StringComparer.Ordinal);
		if (seen.Add(sid))
			yield return sid;

		var normalizedHeroSid = NormalizeHomm3HeroPortraitKey(sid);
		if (normalizedHeroSid != null && seen.Add(normalizedHeroSid))
			yield return normalizedHeroSid;

		var reverseHeroSid = ReverseHomm3HeroPortraitKey(sid);
		if (reverseHeroSid != null && seen.Add(reverseHeroSid))
			yield return reverseHeroSid;

		var aliasSid = ResolveManifestHeroPortraitAlias(sid);
		if (!string.IsNullOrWhiteSpace(aliasSid))
		{
			var trimmedAlias = aliasSid.Trim();
			if (seen.Add(trimmedAlias))
				yield return trimmedAlias;
			var normalizedAliasSid = NormalizeHomm3HeroPortraitKey(trimmedAlias);
			if (normalizedAliasSid != null && seen.Add(normalizedAliasSid))
				yield return normalizedAliasSid;
		}
	}

	internal static void ValidateUpscaledHeroPortraitPayloadOrFail()
	{
		if (!UseUpscaledHeroPortraits())
			return;

		var missing = new List<string>();
		foreach (var sid in Homm3CustomFactionRegistry.EnumerateRequiredHeroPortraitKeys())
		{
			var path = ResolvePluginAssetPath(Path.Combine(UpscaledHeroPortraitFolder, sid + ".png"));
			if (path == null)
				missing.Add(sid);
		}

		if (missing.Count == 0)
			return;

		throw new InvalidOperationException(
			"homm3UseUpscaledHeroPortraits is enabled but "
			+ UpscaledHeroPortraitFolder
			+ " is missing "
			+ missing.Count
			+ " required hero portrait(s), e.g. '"
			+ missing[0]
			+ "'. Run tools/import_homm3_upscaled_hero_portraits.py and redeploy the plugin folder.");
	}

	/// <summary>
	/// Fail-closed existence check for required unit/hero portrait PNGs.
	/// Does not decode textures — main-menu cost exploded when this path called
	/// <see cref="ImageConversion.LoadImage"/> for every SID (especially after painted upscales).
	/// Sprites still load lazily via <see cref="TryGetOrCreateSprite"/> / static portrait APIs.
	/// </summary>
	internal static int ValidateRequiredStaticPortraitFilesOrFail()
	{
		ValidateUpscaledHeroPortraitPayloadOrFail();

		var required = new SortedSet<string>(StringComparer.Ordinal);
		foreach (var sid in Homm3CustomFactionRegistry.EnumerateCustomUnitSids())
			required.Add(sid);
		foreach (var sid in Homm3CustomFactionRegistry.EnumerateRequiredHeroPortraitKeys())
			required.Add(sid);

		var count = 0;
		foreach (var sid in required)
		{
			var path = IsRequiredHeroPortraitKey(sid) && UseUpscaledHeroPortraits()
				? ResolvePrewarmPortraitPath(sid)
				: ResolveStaticPortraitPath(sid);
			if (path == null || !File.Exists(path))
			{
				throw new FileNotFoundException(
					"Required HoMM3 portrait file was not found under the deployed OfflineUnlockMod plugin folder.",
					sid + ".png");
			}

			count++;
		}

		return count;
	}

	/// <summary>Legacy name kept for callers that still expect decode-prewarm; prefer validate-only at menu.</summary>
	internal static int PrewarmRequiredStaticPortraitSprites()
	{
		return ValidateRequiredStaticPortraitFilesOrFail();
	}

	internal static bool IsHomm3PortraitSprite(Sprite sprite)
	{
		return sprite != null
			&& !string.IsNullOrEmpty(sprite.name)
			&& (sprite.name.StartsWith("homm3_static_portrait_", StringComparison.Ordinal)
			    || sprite.name.StartsWith("homm3_preview_", StringComparison.Ordinal));
	}

	private static bool CreateAndCacheSprite(string sid, Texture2D texture, string spriteNamePrefix, out Sprite sprite)
	{
		sprite = Sprite.Create(
			texture,
			new Rect(0f, 0f, texture.width, texture.height),
			new Vector2(0.5f, 0.5f),
			100f,
			0,
			SpriteMeshType.FullRect);
		sprite.name = spriteNamePrefix + sid;
		SpritesBySid[sid] = sprite;
		return true;
	}

	private static bool TryLoadStaticPortraitTexture(string sid, out Texture2D texture)
	{
		texture = null;
		var path = ResolveStaticPortraitPath(sid);
		if (path == null)
			return false;
		try
		{
			return TryLoadStaticPortraitTextureFromPath(sid, path, out texture);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import portrait cache: failed to load static portrait '" + path + "': " + ex.Message);
			return false;
		}
	}

	private static bool TryLoadRequiredStaticPortraitTexture(string sid, out Texture2D texture)
	{
		texture = null;
		var path = IsRequiredHeroPortraitKey(sid) && UseUpscaledHeroPortraits()
			? ResolvePrewarmPortraitPath(sid)
			: ResolveStaticPortraitPath(sid);
		if (path == null)
			throw new FileNotFoundException("Required HoMM3 portrait file was not found under the deployed OfflineUnlockMod plugin folder.", sid + ".png");
		try
		{
			return TryLoadStaticPortraitTextureFromPath(sid, path, out texture);
		}
		catch (Exception ex)
		{
			throw new InvalidOperationException("Failed to load required HoMM3 portrait file '" + path + "': " + ex.Message, ex);
		}
	}

	private static bool TryLoadStaticPortraitTextureFromPath(string sid, string path, out Texture2D texture)
	{
		texture = null;
		var bytes = File.ReadAllBytes(path);
		var t = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: false);
		var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
		for (var i = 0; i < bytes.Length; i++)
			il2cppBytes[i] = bytes[i];
		if (!ImageConversion.LoadImage(t, il2cppBytes))
		{
			UnityEngine.Object.Destroy(t);
			return false;
		}
		t.name = "homm3_portrait_" + sid;
		t.filterMode = FilterMode.Bilinear;
		t.wrapMode = TextureWrapMode.Clamp;
		texture = t;
		return true;
	}

	private static bool UseUpscaledHeroPortraits()
	{
		var cfg = LauncherConfigReader.TryLoad();
		return cfg != null && cfg.Homm3UseUpscaledHeroPortraits;
	}

	private static bool IsRequiredHeroPortraitKey(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		_requiredHeroPortraitKeys ??= BuildRequiredHeroPortraitKeySet();
		return _requiredHeroPortraitKeys.Contains(sid.Trim());
	}

	private static HashSet<string> BuildRequiredHeroPortraitKeySet()
	{
		var keys = new HashSet<string>(StringComparer.Ordinal);
		foreach (var key in Homm3CustomFactionRegistry.EnumerateRequiredHeroPortraitKeys())
			keys.Add(key);
		return keys;
	}

	private static string[] GetRuntimePortraitCandidateDirs()
	{
		if (UseUpscaledHeroPortraits())
			return new[] { UpscaledHeroPortraitFolder, "homm3_portraits", StandardHeroPortraitFolder };
		return new[] { "homm3_portraits", StandardHeroPortraitFolder };
	}

	private static string[] GetPrewarmPortraitCandidateDirs()
	{
		return new[] { "homm3_portraits", StandardHeroPortraitFolder };
	}

	private static string ResolvePrewarmPortraitPath(string sid)
	{
		return ResolvePortraitPathInDirs(sid, GetPrewarmPortraitCandidateDirs());
	}

	private static string ResolveStaticPortraitPath(string sid)
	{
		return ResolvePortraitPathInDirs(sid, GetRuntimePortraitCandidateDirs());
	}

	private static string ResolvePortraitPathInDirs(string sid, string[] candidateDirs)
	{
		// Try exact SID filename first
		var file = sid + ".png";
		foreach (var dlv in candidateDirs)
		{
			var path = ResolvePluginAssetPath(Path.Combine(dlv, file));
			if (path != null)
				return path;
		}

		// Hero SID format mapping: hero_homm3_<faction>_N -> homm3_<faction>_hero_N
		var normalizedHeroSid = NormalizeHomm3HeroPortraitKey(sid);
		if (normalizedHeroSid != null && !string.Equals(normalizedHeroSid, sid, StringComparison.Ordinal))
		{
			var altFile = normalizedHeroSid + ".png";
			foreach (var dlv in candidateDirs)
			{
				var path = ResolvePluginAssetPath(Path.Combine(dlv, altFile));
				if (path != null)
					return path;
			}
		}

		// Reverse mapping: homm3_<faction>_hero_N -> hero_homm3_<faction>_N
		var reverseHeroSid = ReverseHomm3HeroPortraitKey(sid);
		if (reverseHeroSid != null)
		{
			var altFile = reverseHeroSid + ".png";
			foreach (var dlv in candidateDirs)
			{
				var path = ResolvePluginAssetPath(Path.Combine(dlv, altFile));
				if (path != null)
					return path;
			}
		}

		var aliasSid = ResolveManifestHeroPortraitAlias(sid);
		if (!string.IsNullOrWhiteSpace(aliasSid) && !string.Equals(aliasSid, sid, StringComparison.Ordinal))
		{
			var aliasFile = aliasSid + ".png";
			foreach (var dlv in candidateDirs)
			{
				var path = ResolvePluginAssetPath(Path.Combine(dlv, aliasFile));
				if (path != null)
					return path;
			}

			var normalizedAliasSid = NormalizeHomm3HeroPortraitKey(aliasSid);
			if (normalizedAliasSid != null && !string.Equals(normalizedAliasSid, aliasSid, StringComparison.Ordinal))
			{
				var altFile = normalizedAliasSid + ".png";
				foreach (var dlv in candidateDirs)
				{
					var path = ResolvePluginAssetPath(Path.Combine(dlv, altFile));
					if (path != null)
						return path;
				}
			}
		}

		return null;
	}

	internal static string ResolvePluginAssetPath(string relativePath)
	{
		if (string.IsNullOrWhiteSpace(relativePath))
			return null;
		var normalized = relativePath.Replace('\\', '/').TrimStart('/');
		if (Homm3CustomFactionRegistry.TryGetStartupAssetPath(normalized, out var manifestPath)
		    && File.Exists(manifestPath))
			return manifestPath;

		var root = BepInEx.Paths.PluginPath;
		var underNested = Path.GetFullPath(Path.Combine(root, "OfflineUnlockMod", normalized));
		if (File.Exists(underNested))
			return underNested;
		var underRoot = Path.GetFullPath(Path.Combine(root, normalized));
		return File.Exists(underRoot) ? underRoot : null;
	}

	private static string ResolveManifestHeroPortraitAlias(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		var key = sid.Trim();
		var aliases = LoadHeroPortraitAliases();
		if (aliases.TryGetValue(key, out var alias))
			return alias;
		var normalized = NormalizeHomm3HeroPortraitKey(key);
		if (normalized != null && aliases.TryGetValue(normalized, out alias))
			return alias;
		var reverse = ReverseHomm3HeroPortraitKey(key);
		if (reverse != null && aliases.TryGetValue(reverse, out alias))
			return alias;
		return null;
	}

	private static Dictionary<string, string> LoadHeroPortraitAliases()
	{
		if (_heroPortraitAliases != null)
			return _heroPortraitAliases;

		var result = new Dictionary<string, string>(StringComparer.Ordinal);
		var manifestPath = Path.Combine(BepInEx.Paths.PluginPath, "OfflineUnlockMod", "homm3_hero_portraits", "manifest.json");
		try
		{
			if (!File.Exists(manifestPath))
				return _heroPortraitAliases = result;

			var json = File.ReadAllText(manifestPath);
			var root = Newtonsoft.Json.Linq.JObject.Parse(json);
			var entries = root["entries"] as Newtonsoft.Json.Linq.JObject;
			if (entries == null)
				return _heroPortraitAliases = result;

			var entriesMap = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, Newtonsoft.Json.Linq.JObject>>(
				entries.ToString(Newtonsoft.Json.Formatting.None));
			if (entriesMap == null)
				return _heroPortraitAliases = result;

			foreach (var pair in entriesMap)
			{
				var alias = pair.Value?["sourceAliasOf"]?.ToString();
				if (string.IsNullOrWhiteSpace(alias))
					continue;
				AddHeroPortraitAlias(result, pair.Key, alias.Trim());
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import portrait cache: failed to load hero portrait aliases: " + ex.Message);
		}

		_heroPortraitAliases = result;
		return _heroPortraitAliases;
	}

	private static void AddHeroPortraitAlias(Dictionary<string, string> aliases, string key, string alias)
	{
		if (string.IsNullOrWhiteSpace(key) || string.IsNullOrWhiteSpace(alias))
			return;
		aliases[key] = alias;
		var reverseKey = ReverseHomm3HeroPortraitKey(key);
		var reverseAlias = ReverseHomm3HeroPortraitKey(alias);
		if (reverseKey != null && reverseAlias != null)
			aliases[reverseKey] = reverseAlias;
	}

	private static string NormalizeHomm3HeroPortraitKey(string key)
	{
		return Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(key, out var portraitKey)
			? portraitKey
			: null;
	}

	private static string ReverseHomm3HeroPortraitKey(string key)
	{
		return Homm3CustomFactionRegistry.TryReverseHeroPortraitKey(key, out var iconKey)
			? iconKey
			: null;
	}
}
