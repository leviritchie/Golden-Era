using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Loads hero specialization icon keys from packed Core data and resolves sprites for UI hooks.
/// </summary>
internal static class Homm3HeroSpecializationIconSpriteCache
{
	private static Dictionary<string, string> _iconBySpecSid;
	private static HashSet<string> _knownIconKeys;
	private static bool _loadLogged;

	internal static bool TryGetIconKeyForSpecSid(string specSid, out string iconKey)
	{
		iconKey = null;
		if (string.IsNullOrWhiteSpace(specSid))
			return false;
		EnsureMapsLoaded();
		return _iconBySpecSid.TryGetValue(specSid.Trim(), out iconKey) && !string.IsNullOrWhiteSpace(iconKey);
	}

	internal static bool IsKnownSpecializationIconKey(string iconKey)
	{
		if (string.IsNullOrWhiteSpace(iconKey))
			return false;
		EnsureMapsLoaded();
		return _knownIconKeys.Contains(iconKey.Trim());
	}

	internal static bool TryResolveSprite(string iconKey, out Sprite sprite)
	{
		sprite = null;
		if (string.IsNullOrWhiteSpace(iconKey))
			return false;

		var key = iconKey.Trim();
		EnsureMapsLoaded();
		var requiresDeployedPortrait = key.StartsWith("h3_", StringComparison.Ordinal)
		                               || IsHeroSpecializationIconKey(key);

		if (requiresDeployedPortrait)
		{
			if (IsHeroSpecializationIconKey(key))
			{
				var heroIconKey = key.Substring(0, key.Length - "_specialization_icon".Length);
				if (Homm3ImportPortraitSpriteCache.TryGetOrCreateStaticPortraitSprite(heroIconKey, out sprite) && sprite)
					return true;
			}
			else if (Homm3ImportPortraitSpriteCache.TryGetOrCreateStaticPortraitSprite(key, out sprite) && sprite)
				return true;

			// Do not fall back to already-loaded Core/battle sprites for specialization rows.
			return false;
		}

		if (Homm3FactionSkillIconSpriteCache.IsFactionSkillIconKey(key)
		    && Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(key, out sprite)
		    && sprite)
			return true;
		if (Homm3CustomUiIconHook.TryResolveLoadedVanillaSprite(key, out sprite) && sprite)
			return true;
		if (Homm3ImportPortraitSpriteCache.TryGetOrCreateStrongholdHeroSpriteForIconKey(key, out sprite) && sprite)
			return true;
		return false;
	}

	private static bool IsHeroSpecializationIconKey(string key)
	{
		if (!key.EndsWith("_specialization_icon", StringComparison.Ordinal))
			return false;
		var heroIconKey = key.Substring(0, key.Length - "_specialization_icon".Length);
		return Homm3CustomFactionRegistry.IsCustomHeroSid(heroIconKey);
	}

	private static void EnsureMapsLoaded()
	{
		if (_iconBySpecSid != null && _knownIconKeys != null)
			return;

		_iconBySpecSid = new Dictionary<string, string>(StringComparer.Ordinal);
		_knownIconKeys = new HashSet<string>(StringComparer.Ordinal);
		var loadedRows = 0;
		try
		{
			var coreZipPath = LauncherConfigReader.GetCoreZipPath();
			if (!File.Exists(coreZipPath))
			{
				LogLoadOnce("Core.zip not found at '" + coreZipPath + "'.", true);
				return;
			}

			using var archive = ZipFile.OpenRead(coreZipPath);
			foreach (var entry in archive.Entries)
			{
				if (entry == null)
					continue;
				var entryName = (entry.FullName ?? string.Empty).Replace('\\', '/');
				if (!entryName.StartsWith("DB/heroes_specializations/specializations_homm3_", StringComparison.Ordinal)
				    || !entryName.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
					continue;

				using var reader = new StreamReader(entry.Open());
				var root = JObject.Parse(reader.ReadToEnd());
				var arrayToken = root["array"];
				if (arrayToken == null || arrayToken.Type != JTokenType.Array)
					continue;

				JArray array;
				try
				{
					array = JArray.Parse(arrayToken.ToString());
				}
				catch
				{
					continue;
				}

				for (var i = 0; i < array.Count; i++)
				{
					var rowToken = array[i];
					if (rowToken == null || rowToken.Type != JTokenType.Object)
						continue;

					JObject item;
					try
					{
						item = JObject.Parse(rowToken.ToString());
					}
					catch
					{
						continue;
					}

					var id = item["id"]?.ToString();
					var icon = item["icon"]?.ToString();
					if (string.IsNullOrWhiteSpace(id) || string.IsNullOrWhiteSpace(icon))
						continue;
					id = id.Trim();
					icon = icon.Trim();
					_iconBySpecSid[id] = icon;
					_knownIconKeys.Add(icon);
					loadedRows++;
				}
			}
		}
		catch (Exception ex)
		{
			LogLoadOnce("failed to load Core specialization icon map: " + ex.Message, true);
			return;
		}

		LogLoadOnce("loaded " + loadedRows + " hero specialization icon row(s) from Core.zip.", loadedRows == 0);
	}

	private static void LogLoadOnce(string message, bool warning)
	{
		if (_loadLogged)
			return;
		_loadLogged = true;
		if (warning)
			Plugin.LogSource?.LogWarning("Homm3HeroSpecializationIcon: " + message);
		else
			Plugin.LogSource?.LogInfo("Homm3HeroSpecializationIcon: " + message);
	}
}
