using System;
using System.IO;
using BepInEx.Logging;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Optional AssetBundle of HoMM3 artifact adventure-map billboard Sprites (Phase 2 pilot).
/// Asset names are <c>artifact_map_billboard_&lt;sid&gt;</c>. Sprites were imported Point-filtered;
/// textures are compressed and shared — callers must not Destroy them. Unlike town map billboards,
/// artifacts do not need bottom-padding GPU blit.
/// Gate: <see cref="LauncherConfig.Homm3UseBillboardBundles"/> (same flag as town map billboards).
/// </summary>
internal static class Homm3ArtifactMapBillboardBundle
{
	internal const string BundleName = "homm3_artifact_map_billboards";
	internal const string RelativeBundlePath = "homm3_artifact_map_billboards/homm3_artifact_map_billboards";
	internal const string RelativeManifestPath = "homm3_artifact_map_billboards/manifest.json";
	internal const string AssetNamePrefix = "artifact_map_billboard_";

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
	/// Derives the bundle asset name from a catalog SID. Mirrors
	/// tools/homm3_import/build_homm3_artifact_map_billboard_bundle.py: lowercase, non [a-z0-9_] → "_".
	/// </summary>
	internal static bool TryDeriveAssetName(string sid, out string assetName)
	{
		assetName = null;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var chars = sid.Trim().ToLowerInvariant().ToCharArray();
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
		assetName = AssetNamePrefix + sanitized;
		return true;
	}

	/// <summary>
	/// Loads the shared bundle texture for an artifact SID. Callers may set filter/wrap modes but
	/// must not Destroy the texture or read pixels from it (compressed, not CPU-readable).
	/// </summary>
	internal static bool TryLoadTexture(string sid, out Texture2D texture)
	{
		texture = null;
		if (!TryDeriveAssetName(sid, out var assetName))
			return false;
		EnsureLoaded();
		if (_bundle == null)
			return false;
		try
		{
			var sprite = _bundle.LoadAsset<Sprite>(assetName);
			if (!sprite)
				return false;
			texture = sprite.texture;
			return texture;
		}
		catch (Exception ex)
		{
			if (_loggedLoad++ < 8)
				Plugin.LogSource?.LogWarning(
					"Homm3ArtifactMapBillboardBundle: LoadAsset failed for '" + assetName + "': " + ex.Message);
			texture = null;
			return false;
		}
	}

	/// <summary>
	/// Fail-closed pilot gate for the main-menu preloader: bundle file and manifest.json must exist
	/// under the deployed plugin folder, and the manifest must parse with the expected bundle name and
	/// a non-empty asset list. Reads manifest JSON only — never LoadAllAssets or texture decode.
	/// PNG payloads remain dual-deployed as fallback.
	/// </summary>
	internal static void ValidateBundlePayloadOrFail(ManualLogSource log)
	{
		var bundlePath = ResolveBundleFilePath();
		if (bundlePath == null || !File.Exists(bundlePath))
		{
			throw new FileNotFoundException(
				"homm3UseBillboardBundles is enabled but the homm3_artifact_map_billboards AssetBundle is missing "
				+ "under the deployed OfflineUnlockMod plugin folder. Run "
				+ "tools/homm3_import/build_homm3_artifact_map_billboard_bundle.py "
				+ "and redeploy the plugin folder (or turn the flag off to stay on PNG billboards).",
				RelativeBundlePath);
		}

		var assetNames = Homm3UiPortraitBundle.LoadManifestAssetNamesOrFail(
			RelativeManifestPath,
			BundleName,
			"homm3UseBillboardBundles");
		log?.LogInfo(
			"Homm3ArtifactMapBillboardBundle: validated bundle file and manifest ("
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
					"Homm3ArtifactMapBillboardBundle: AssetBundle.LoadFromFile returned null for " + path);
				return;
			}
			Plugin.LogSource?.LogInfo("Homm3ArtifactMapBillboardBundle: loaded " + path);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(
				"Homm3ArtifactMapBillboardBundle: failed to load " + path + ": " + ex.Message);
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
