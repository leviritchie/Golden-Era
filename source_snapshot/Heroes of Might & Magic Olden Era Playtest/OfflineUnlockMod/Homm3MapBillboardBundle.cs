using System;
using System.IO;
using BepInEx.Logging;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Optional AssetBundle of HoMM3 map billboard Sprites (Phase 2 pilot). Asset names are
/// <c>map_billboard_&lt;key&gt;</c> where the key derives from the registry billboard relative path
/// (see <see cref="TryDeriveBillboardAssetKey"/>). Sprites were imported Point-filtered; their
/// textures are compressed and not CPU-readable, so callers that need pixels (e.g. bottom padding)
/// must copy through the GPU instead of GetPixels32.
/// Loaded once via <see cref="AssetBundle.LoadFromFile"/> using the same plugin-asset resolution
/// pattern as <see cref="Homm3DialogPortraitBundle"/>.
/// </summary>
internal static class Homm3MapBillboardBundle
{
	internal const string BundleName = "homm3_map_billboards";
	internal const string RelativeBundlePath = "homm3_map_billboards/homm3_map_billboards";
	internal const string RelativeManifestPath = "homm3_map_billboards/manifest.json";
	internal const string AssetNamePrefix = "map_billboard_";

	/// <summary>Registry billboard paths live under this plugin-relative root.</summary>
	private const string MapObjectRefsPrefix = "homm3_runtime_assets/map_object_refs/";

	private static AssetBundle _bundle;
	private static bool _loadAttempted;
	private static int _loggedLoad;

	internal static bool IsLoaded => _bundle != null;

	internal static bool IsEnabled()
	{
		var cfg = LauncherConfigReader.TryLoad();
		return cfg != null && cfg.Homm3UseBillboardBundles;
	}

	/// <summary>
	/// Derives the Phase 1 bundle asset key from a registry billboard relative path. Mirrors
	/// tools/homm3_import/build_homm3_billboard_bundle.py derive_billboard_key exactly: the path must
	/// live under homm3_runtime_assets/map_object_refs/, the key is built from the containing
	/// directory (a trailing .dir is stripped from the leaf), components join with "__", lowercase,
	/// and non [a-z0-9_] characters become "_". Fail-closed: returns false when the mapping cannot be
	/// derived instead of guessing a key that would silently miss.
	/// </summary>
	internal static bool TryDeriveBillboardAssetKey(string relativePath, out string assetKey)
	{
		assetKey = null;
		if (string.IsNullOrWhiteSpace(relativePath))
			return false;
		var normalized = relativePath.Replace('\\', '/').TrimStart('/');
		if (!normalized.StartsWith(MapObjectRefsPrefix, StringComparison.OrdinalIgnoreCase))
			return false;
		var rest = normalized.Substring(MapObjectRefsPrefix.Length);
		var parts = rest.Split('/');
		if (parts.Length < 2)
			return false;

		// The key comes from the containing directory, not the file name: the bundle intentionally
		// carries only the main 00_00 frame per map_object_refs directory.
		var dirPartCount = parts.Length - 1;
		var last = parts[dirPartCount - 1];
		if (last.EndsWith(".dir", StringComparison.OrdinalIgnoreCase))
			last = last.Substring(0, last.Length - ".dir".Length);
		parts[dirPartCount - 1] = last;

		var joined = string.Join("__", parts, 0, dirPartCount).ToLowerInvariant();
		var chars = joined.ToCharArray();
		for (var i = 0; i < chars.Length; i++)
		{
			var c = chars[i];
			var keep = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
			if (!keep)
				chars[i] = '_';
		}
		var sanitized = new string(chars);
		if (string.IsNullOrWhiteSpace(sanitized))
			return false;
		assetKey = AssetNamePrefix + sanitized;
		return true;
	}

	/// <summary>
	/// Loads the billboard texture for a registry relative path. The returned texture is the shared
	/// bundle texture behind the sprite; callers may set filter/wrap modes but must not Destroy it or
	/// read pixels from it (compressed, not CPU-readable).
	/// </summary>
	internal static bool TryLoadTexture(string relativePath, out Texture2D texture)
	{
		texture = null;
		if (!TryDeriveBillboardAssetKey(relativePath, out var assetKey))
			return false;
		EnsureLoaded();
		if (_bundle == null)
			return false;
		try
		{
			var sprite = _bundle.LoadAsset<Sprite>(assetKey);
			if (!sprite)
				return false;
			texture = sprite.texture;
			return texture;
		}
		catch (Exception ex)
		{
			if (_loggedLoad++ < 8)
				Plugin.LogSource?.LogWarning(
					"Homm3MapBillboardBundle: LoadAsset failed for '" + assetKey + "': " + ex.Message);
			texture = null;
			return false;
		}
	}

	/// <summary>
	/// Fail-closed pilot gate for the main-menu preloader: bundle file and manifest.json must exist
	/// under the deployed plugin folder, and the manifest must parse with the expected bundle name and
	/// a non-empty asset list. Reads manifest JSON only — never LoadAllAssets or texture decode.
	/// PNG payloads are still validated separately (dual deploy during the pilot).
	/// </summary>
	internal static void ValidateBundlePayloadOrFail(ManualLogSource log)
	{
		var bundlePath = ResolveBundleFilePath();
		if (bundlePath == null || !File.Exists(bundlePath))
		{
			throw new FileNotFoundException(
				"homm3UseBillboardBundles is enabled but the homm3_map_billboards AssetBundle is missing "
				+ "under the deployed OfflineUnlockMod plugin folder. Run tools/homm3_import/build_homm3_billboard_bundle.py "
				+ "and redeploy the plugin folder (or turn the flag off to stay on PNG billboards).",
				RelativeBundlePath);
		}

		var assetNames = Homm3UiPortraitBundle.LoadManifestAssetNamesOrFail(RelativeManifestPath, BundleName, "homm3UseBillboardBundles");
		log?.LogInfo(
			"Homm3MapBillboardBundle: validated bundle file and manifest ("
			+ assetNames.Count
			+ " declared asset(s)); no texture decode at menu.");
	}

	private static void EnsureLoaded()
	{
		if (_loadAttempted)
			return;
		_loadAttempted = true;
		var path = ResolveBundleFilePath();
		if (path == null || !File.Exists(path))
			return;
		try
		{
			_bundle = AssetBundle.LoadFromFile(path);
			if (_bundle == null)
			{
				Plugin.LogSource?.LogWarning(
					"Homm3MapBillboardBundle: AssetBundle.LoadFromFile returned null for " + path);
				return;
			}
			Plugin.LogSource?.LogInfo("Homm3MapBillboardBundle: loaded " + path);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(
				"Homm3MapBillboardBundle: failed to load " + path + ": " + ex.Message);
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
