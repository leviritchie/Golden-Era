using System;
using System.Collections.Generic;
using System.IO;
using BepInEx.Logging;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Vanilla dialog avatars use <c>icons/dialogue/...</c> keys resolved through <c>cko.sfo</c>
/// (dict 0 before Resources). Register HoMM3 hero + unit portraits under matching dialogue
/// keys at main-menu prewarm so dialog slides hit the native catalog without per-slide Harmony.
/// Unit keys: <c>icons/dialogue/dialogue_unit_h3_goblin</c> → <c>homm3_portraits/h3_goblin.png</c>.
/// </summary>
internal static class Homm3DialogPortraitCatalog
{
	internal const string DialogueIconPrefix = "icons/dialogue/dialogue_";

	internal static bool IsCustomDialogPortraitKey(string key)
	{
		return IsDialogHeroPortraitKey(key) || IsDialogUnitPortraitKey(key);
	}

	internal static bool IsDialogHeroPortraitKey(string key)
	{
		return TryGetHeroIconKeyFromDialogueKey(key, out _);
	}

	internal static bool IsDialogUnitPortraitKey(string key)
	{
		return TryGetUnitSidFromDialogueKey(key, out _);
	}

	internal static bool TryBuildDialogueIconKeyFromHeroIconKey(string heroIconKey, out string dialogueKey)
	{
		dialogueKey = null;
		if (string.IsNullOrWhiteSpace(heroIconKey))
			return false;
		var icon = heroIconKey.Trim();
		if (!icon.StartsWith("hero_homm3_", StringComparison.Ordinal))
			return false;
		dialogueKey = DialogueIconPrefix + icon;
		return true;
	}

	internal static bool TryBuildDialogueIconKeyFromUnitSid(string unitSid, out string dialogueKey)
	{
		dialogueKey = null;
		if (string.IsNullOrWhiteSpace(unitSid))
			return false;
		var sid = unitSid.Trim();
		if (!sid.StartsWith("h3_", StringComparison.Ordinal))
			return false;
		dialogueKey = DialogueIconPrefix + "unit_" + sid;
		return true;
	}

	internal static bool TryGetHeroIconKeyFromDialogueKey(string dialogueKey, out string heroIconKey)
	{
		heroIconKey = null;
		if (string.IsNullOrWhiteSpace(dialogueKey))
			return false;
		var key = dialogueKey.Trim();
		const string prefix = DialogueIconPrefix + "hero_homm3_";
		if (!key.StartsWith(prefix, StringComparison.Ordinal))
			return false;
		heroIconKey = "hero_homm3_" + key.Substring(prefix.Length);
		return Homm3CustomFactionRegistry.IsCustomHeroSid(heroIconKey);
	}

	internal static bool TryGetUnitSidFromDialogueKey(string dialogueKey, out string unitSid)
	{
		unitSid = null;
		if (string.IsNullOrWhiteSpace(dialogueKey))
			return false;
		var key = dialogueKey.Trim();
		const string prefix = DialogueIconPrefix + "unit_";
		if (!key.StartsWith(prefix, StringComparison.Ordinal))
			return false;
		var sid = key.Substring(prefix.Length);
		if (!sid.StartsWith("h3_", StringComparison.Ordinal))
			return false;
		unitSid = sid;
		return true;
	}

	internal static bool TryResolveDialogHeroPortraitSprite(string dialogueKey, out Sprite sprite)
	{
		sprite = null;
		if (!TryGetHeroIconKeyFromDialogueKey(dialogueKey, out var heroIconKey))
			return false;
		// Prefer the same sprite-cache path HUD portraits already use. When the
		// homm3UseUiPortraitBundles pilot flag is on, that cache serves the ui_portrait
		// AssetBundle sprite before PNG decode (PNG remains the per-sid fallback).
		// AssetBundle sprites registered into cko still produced blank dialog avatars in
		// runtime proof, so nothing registers into cko here — resolution goes through the
		// existing Homm3DialogAvatarPortraitHook bind-substitution surface only.
		if (Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(heroIconKey, out sprite)
		    && sprite)
			return true;
		return Homm3DialogPortraitBundle.TryLoadSprite(dialogueKey, heroIconKey, out sprite) && sprite;
	}

	internal static bool TryResolveDialogUnitPortraitSprite(string dialogueKey, out Sprite sprite)
	{
		sprite = null;
		if (!TryGetUnitSidFromDialogueKey(dialogueKey, out var unitSid))
			return false;
		// Unit dialog portraits resolve through the static portrait cache; when the
		// homm3UseUiPortraitBundles pilot flag is on, that cache serves the ui_portrait
		// AssetBundle sprite for h3_* SIDs before PNG decode (PNG remains the per-sid fallback).
		return Homm3ImportPortraitSpriteCache.TryGetOrCreateStaticPortraitSprite(unitSid, out sprite)
		       && sprite;
	}

	internal static bool TryResolveCustomDialogPortraitSprite(string dialogueKey, out Sprite sprite)
	{
		if (TryResolveDialogHeroPortraitSprite(dialogueKey, out sprite) && sprite)
			return true;
		return TryResolveDialogUnitPortraitSprite(dialogueKey, out sprite) && sprite;
	}

	/// <summary>
	/// Fail-closed: required dialog portrait PNG paths exist. Does not decode or inject into cko.
	/// Dialog slides resolve via <see cref="Homm3DialogAvatarPortraitHook"/> on first bind;
	/// UI icon paths register into cko lazily through <see cref="Homm3NativeSpriteCatalogRegistrar"/>.
	/// </summary>
	internal static int ValidateRequiredDialogPortraitFilesOrFail(ManualLogSource log)
	{
		var validated = 0;
		var missing = new List<string>();
		foreach (var heroSid in Homm3CustomFactionRegistry.EnumerateRequiredHeroPortraitKeys())
		{
			if (!Homm3CustomFactionRegistry.TryReverseHeroPortraitKey(heroSid, out var heroIconKey)
			    || string.IsNullOrWhiteSpace(heroIconKey))
			{
				if (!TryHeroIconKeyFromPortraitSid(heroSid, out heroIconKey))
				{
					missing.Add(heroSid + " (no icon key)");
					continue;
				}
			}

			if (!TryBuildDialogueIconKeyFromHeroIconKey(heroIconKey, out _))
			{
				missing.Add(heroSid + " (no dialogue key for " + heroIconKey + ")");
				continue;
			}

			if (!HeroDialogPortraitFileExists(heroSid, heroIconKey))
				missing.Add(heroSid + " (missing portrait file for " + heroIconKey + ")");
			else
				validated++;
		}

		if (missing.Count > 0)
		{
			throw new InvalidOperationException(
				"Homm3DialogPortraitCatalog: failed to validate "
				+ missing.Count
				+ " dialog portrait key(s), e.g. '"
				+ missing[0]
				+ "'.");
		}

		var unitValidated = ValidateUnitDialogPortraitFiles(log);
		log?.LogInfo(
			"Homm3DialogPortraitCatalog: validated "
			+ validated
			+ " hero dialog portrait file(s) and "
			+ unitValidated
			+ " unit dialog portrait file(s) (decode deferred until first UI need).");
		return validated + unitValidated;
	}

	private static bool HeroDialogPortraitFileExists(string heroSid, string heroIconKey)
	{
		var keys = new List<string>();
		if (!string.IsNullOrWhiteSpace(heroSid))
			keys.Add(heroSid.Trim());
		if (!string.IsNullOrWhiteSpace(heroIconKey))
			keys.Add(heroIconKey.Trim());
		if (Homm3CustomFactionRegistry.TryNormalizeHeroPortraitKey(heroIconKey, out var normalized)
		    && !string.IsNullOrWhiteSpace(normalized))
			keys.Add(normalized);
		foreach (var dir in new[] { "homm3_portraits", "homm3_hero_portraits", "homm3_hero_portraits_upscaled" })
		{
			foreach (var key in keys)
			{
				if (Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(Path.Combine(dir, key + ".png")) != null)
					return true;
			}
		}
		return false;
	}

	private static int ValidateUnitDialogPortraitFiles(ManualLogSource log)
	{
		var validated = 0;
		var pluginRoot = Path.GetDirectoryName(typeof(Homm3DialogPortraitCatalog).Assembly.Location);
		if (string.IsNullOrWhiteSpace(pluginRoot))
			return 0;
		var portraitsDir = Path.Combine(pluginRoot, "homm3_portraits");
		if (!Directory.Exists(portraitsDir))
		{
			log?.LogInfo("Homm3DialogPortraitCatalog: no homm3_portraits folder for unit dialog validation.");
			return 0;
		}

		foreach (var path in Directory.GetFiles(portraitsDir, "h3_*.png"))
		{
			var sid = Path.GetFileNameWithoutExtension(path);
			if (!TryBuildDialogueIconKeyFromUnitSid(sid, out _))
				continue;
			if (!File.Exists(path))
				throw new FileNotFoundException("Required HoMM3 unit dialog portrait PNG missing.", path);
			validated++;
		}
		return validated;
	}

	private static bool TryHeroIconKeyFromPortraitSid(string portraitSid, out string heroIconKey)
	{
		heroIconKey = null;
		if (string.IsNullOrWhiteSpace(portraitSid))
			return false;
		// homm3_stronghold_hero_2 -> hero_homm3_stronghold_2
		var sid = portraitSid.Trim();
		const string marker = "_hero_";
		var idx = sid.IndexOf(marker, StringComparison.Ordinal);
		if (idx <= 0 || !sid.StartsWith("homm3_", StringComparison.Ordinal))
			return false;
		var faction = sid.Substring("homm3_".Length, idx - "homm3_".Length);
		var number = sid.Substring(idx + marker.Length);
		if (string.IsNullOrWhiteSpace(faction) || string.IsNullOrWhiteSpace(number))
			return false;
		heroIconKey = "hero_homm3_" + faction + "_" + number;
		return Homm3CustomFactionRegistry.IsCustomHeroSid(heroIconKey);
	}
}
