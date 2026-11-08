using System;
using System.IO;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Optional AssetBundle of dialog portrait Sprites. When present under the plugin folder,
/// <see cref="Homm3DialogPortraitCatalog"/> prefers these over PNG <c>Sprite.Create</c>.
/// Bundle asset names may be the full dialogue key or the short <c>dialogue_hero_homm3_*</c> leaf.
/// </summary>
internal static class Homm3DialogPortraitBundle
{
	internal const string RelativeBundlePath = "homm3_dialog_portraits/homm3_dialog_portraits";
	private static AssetBundle _bundle;
	private static bool _loadAttempted;
	private static int _loggedLoad;

	internal static bool IsLoaded => _bundle != null;

	internal static bool TryLoadSprite(string dialogueKey, string heroIconKey, out Sprite sprite)
	{
		sprite = null;
		EnsureLoaded();
		if (_bundle == null)
			return false;

		if (TryLoadNamed(_bundle, dialogueKey, out sprite) && sprite)
			return true;

		if (!string.IsNullOrWhiteSpace(dialogueKey))
		{
			var slash = dialogueKey.LastIndexOf('/');
			if (slash >= 0 && slash + 1 < dialogueKey.Length
			    && TryLoadNamed(_bundle, dialogueKey.Substring(slash + 1), out sprite)
			    && sprite)
				return true;
		}

		if (!string.IsNullOrWhiteSpace(heroIconKey)
		    && TryLoadNamed(_bundle, "dialogue_" + heroIconKey.Trim(), out sprite)
		    && sprite)
			return true;

		return false;
	}

	private static bool TryLoadNamed(AssetBundle bundle, string name, out Sprite sprite)
	{
		sprite = null;
		if (bundle == null || string.IsNullOrWhiteSpace(name))
			return false;
		try
		{
			sprite = bundle.LoadAsset<Sprite>(name.Trim());
			return sprite;
		}
		catch (Exception ex)
		{
			if (_loggedLoad++ < 8)
				Plugin.LogSource?.LogWarning(
					"Homm3DialogPortraitBundle: LoadAsset failed for '" + name + "': " + ex.Message);
			sprite = null;
			return false;
		}
	}

	private static void EnsureLoaded()
	{
		if (_loadAttempted)
			return;
		_loadAttempted = true;
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeBundlePath);
		if (path == null)
		{
			// Also accept .bundle suffix variants next to the relative path.
			path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeBundlePath + ".bundle");
		}
		if (path == null || !File.Exists(path))
			return;
		try
		{
			_bundle = AssetBundle.LoadFromFile(path);
			if (_bundle == null)
			{
				Plugin.LogSource?.LogWarning(
					"Homm3DialogPortraitBundle: AssetBundle.LoadFromFile returned null for " + path);
				return;
			}
			Plugin.LogSource?.LogInfo("Homm3DialogPortraitBundle: loaded " + path);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(
				"Homm3DialogPortraitBundle: failed to load " + path + ": " + ex.Message);
			_bundle = null;
		}
	}
}
