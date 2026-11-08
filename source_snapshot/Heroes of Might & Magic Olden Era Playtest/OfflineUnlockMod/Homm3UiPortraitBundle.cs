using System;
using System.Collections.Generic;
using System.IO;
using BepInEx.Logging;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Optional AssetBundle of HoMM3 UI portrait Sprites (Phase 2 pilot). Asset names are
/// <c>ui_portrait_&lt;sid&gt;</c> where the sid matches the source PNG stem: unit SIDs
/// (<c>h3_*</c> from homm3_portraits) and hero portrait keys (<c>homm3_&lt;faction&gt;_hero_&lt;n&gt;</c>
/// from homm3_hero_portraits_upscaled, capped at 512px by the Unity importer).
/// Loaded once via <see cref="AssetBundle.LoadFromFile"/> using the same plugin-asset resolution
/// pattern as <see cref="Homm3DialogPortraitBundle"/>. The bundle stays loaded for the session;
/// sprites returned by <see cref="TryLoadSprite"/> are shared bundle assets, not per-caller copies.
/// </summary>
internal static class Homm3UiPortraitBundle
{
	internal const string BundleName = "homm3_ui_portraits";
	internal const string RelativeBundlePath = "homm3_ui_portraits/homm3_ui_portraits";
	internal const string RelativeManifestPath = "homm3_ui_portraits/manifest.json";
	internal const string AssetNamePrefix = "ui_portrait_";

	private static AssetBundle _bundle;
	private static bool _loadAttempted;
	private static int _loggedLoad;

	internal static bool IsLoaded => _bundle != null;

	internal static bool IsEnabled()
	{
		var cfg = LauncherConfigReader.TryLoad();
		return cfg != null && cfg.Homm3UseUiPortraitBundles;
	}

	/// <summary>Loads a portrait sprite by full asset name (e.g. ui_portrait_h3_goblin).</summary>
	internal static bool TryLoadSprite(string assetName, out Sprite sprite)
	{
		sprite = null;
		if (string.IsNullOrWhiteSpace(assetName))
			return false;
		EnsureLoaded();
		if (_bundle == null)
			return false;
		try
		{
			sprite = _bundle.LoadAsset<Sprite>(assetName.Trim());
			return sprite;
		}
		catch (Exception ex)
		{
			if (_loggedLoad++ < 8)
				Plugin.LogSource?.LogWarning(
					"Homm3UiPortraitBundle: LoadAsset failed for '" + assetName + "': " + ex.Message);
			sprite = null;
			return false;
		}
	}

	/// <summary>Builds the bundle asset name for a portrait key (PNG stem form, e.g. h3_goblin or homm3_castle_hero_1).</summary>
	internal static string BuildAssetName(string portraitKey)
	{
		return string.IsNullOrWhiteSpace(portraitKey)
			? null
			: AssetNamePrefix + portraitKey.Trim().ToLowerInvariant();
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
				"homm3UseUiPortraitBundles is enabled but the homm3_ui_portraits AssetBundle is missing "
				+ "under the deployed OfflineUnlockMod plugin folder. Run tools/homm3_import/build_homm3_ui_portrait_bundle.py "
				+ "and redeploy the plugin folder (or turn the flag off to stay on PNG portraits).",
				RelativeBundlePath);
		}

		var assetNames = LoadManifestAssetNamesOrFail(RelativeManifestPath, BundleName, "homm3UseUiPortraitBundles");
		log?.LogInfo(
			"Homm3UiPortraitBundle: validated bundle file and manifest ("
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
					"Homm3UiPortraitBundle: AssetBundle.LoadFromFile returned null for " + path);
				return;
			}
			Plugin.LogSource?.LogInfo("Homm3UiPortraitBundle: loaded " + path);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(
				"Homm3UiPortraitBundle: failed to load " + path + ": " + ex.Message);
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

	internal static List<string> LoadManifestAssetNamesOrFail(string relativeManifestPath, string expectedBundleName, string flagName)
	{
		var manifestPath = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(relativeManifestPath);
		if (manifestPath == null || !File.Exists(manifestPath))
		{
			throw new FileNotFoundException(
				flagName
				+ " is enabled but the bundle asset manifest is missing under the deployed OfflineUnlockMod plugin folder. "
				+ "Re-run the Phase 1 bundle build and redeploy the plugin folder (or turn the flag off).",
				relativeManifestPath);
		}

		Newtonsoft.Json.Linq.JObject root;
		try
		{
			root = Newtonsoft.Json.Linq.JObject.Parse(File.ReadAllText(manifestPath));
		}
		catch (Exception ex)
		{
			throw new InvalidOperationException(
				flagName + " is enabled but the bundle asset manifest '" + manifestPath + "' is not valid JSON: " + ex.Message, ex);
		}

		var bundleName = root["bundle"]?.ToString();
		if (!string.Equals(bundleName, expectedBundleName, StringComparison.Ordinal))
		{
			throw new InvalidOperationException(
				flagName
				+ " is enabled but the bundle asset manifest '"
				+ manifestPath
				+ "' declares bundle='"
				+ (bundleName ?? "(null)")
				+ "' instead of '"
				+ expectedBundleName
				+ "'.");
		}

		// IL2CPP: `token as JArray` is often null even for real JSON arrays — same pattern as
		// Homm3ImportVisuals / Homm3CustomFactionRegistry.ParseArrayToken.
		var assetsToken = root["assets"];
		if (assetsToken == null || assetsToken.Type != Newtonsoft.Json.Linq.JTokenType.Array)
		{
			throw new InvalidOperationException(
				flagName
				+ " is enabled but the bundle asset manifest '"
				+ manifestPath
				+ "' has no asset entries; refusing to trust an empty bundle manifest.");
		}

		Newtonsoft.Json.Linq.JArray assets;
		try
		{
			assets = assetsToken as Newtonsoft.Json.Linq.JArray
				?? Newtonsoft.Json.Linq.JArray.Parse(assetsToken.ToString());
		}
		catch (Exception ex)
		{
			throw new InvalidOperationException(
				flagName
				+ " is enabled but the bundle asset manifest '"
				+ manifestPath
				+ "' assets array could not be parsed: "
				+ ex.Message,
				ex);
		}

		if (assets.Count == 0)
		{
			throw new InvalidOperationException(
				flagName
				+ " is enabled but the bundle asset manifest '"
				+ manifestPath
				+ "' has no asset entries; refusing to trust an empty bundle manifest.");
		}

		var names = new List<string>(assets.Count);
		for (var i = 0; i < assets.Count; i++)
		{
			var name = assets[i]?.ToString();
			if (!string.IsNullOrWhiteSpace(name))
				names.Add(name.Trim());
		}
		if (names.Count == 0)
		{
			throw new InvalidOperationException(
				flagName
				+ " is enabled but the bundle asset manifest '"
				+ manifestPath
				+ "' has no usable asset names; refusing to trust an empty bundle manifest.");
		}
		return names;
	}
}
