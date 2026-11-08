using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using Newtonsoft.Json.Linq;

namespace OfflineUnlockMod;

/// <summary>
/// Data-owned icon map for generated HoMM3 custom faction hero actions.
/// </summary>
internal static class Homm3CustomHeroAbilityIconSpriteCache
{
	private const string HeroAbilitiesPath = "DB/heroes_abilities/heroes_abilities_base/hero_abilities.json";
	private static Dictionary<string, string[]> _iconsByAbilitySid;
	private static bool _successLogged;
	private static int _loadFailureCount;
	private static DateTime _nextLoadRetryUtc;

	internal static bool HasIconForAbilitySid(string abilitySid)
	{
		if (string.IsNullOrWhiteSpace(abilitySid))
			return false;
		var trimmedSid = abilitySid.Trim();
		if (!IsCustomFactionHeroAbilitySid(trimmedSid))
			return false;
		if (!EnsureLoaded())
			throw new InvalidOperationException("HoMM3 custom hero ability icon map failed to load before checking '" + trimmedSid + "'.");
		return _iconsByAbilitySid.ContainsKey(trimmedSid);
	}

	internal static bool TryGetIconKeyForAbility(string abilitySid, int level, out string iconKey)
	{
		iconKey = null;
		if (string.IsNullOrWhiteSpace(abilitySid))
			return false;

		var trimmedSid = abilitySid.Trim();
		if (!IsCustomFactionHeroAbilitySid(trimmedSid))
			return false;
		if (!EnsureLoaded())
			throw new InvalidOperationException("HoMM3 custom hero ability icon map failed to load before resolving '" + trimmedSid + "'.");
		if (!_iconsByAbilitySid.TryGetValue(trimmedSid, out var icons)
		    || icons == null
		    || icons.Length == 0)
			return false;

		if (level >= 0 && level < icons.Length && !string.IsNullOrWhiteSpace(icons[level]))
		{
			iconKey = icons[level].Trim();
			return true;
		}

		if (icons.Length == 1 && !string.IsNullOrWhiteSpace(icons[0]))
		{
			iconKey = icons[0].Trim();
			return true;
		}

		return false;
	}

	private static bool EnsureLoaded()
	{
		if (_iconsByAbilitySid != null)
			return true;
		if (_nextLoadRetryUtc > DateTime.MinValue && DateTime.UtcNow < _nextLoadRetryUtc)
			return false;

		var loadedIcons = new Dictionary<string, string[]>(StringComparer.Ordinal);
		var loadedRows = 0;
		try
		{
			var coreZipPath = LauncherConfigReader.GetCoreZipPath();
			if (!File.Exists(coreZipPath))
			{
				LogLoadFailure("Core.zip not found at '" + coreZipPath + "'.");
				return false;
			}

			using var archive = ZipFile.OpenRead(coreZipPath);
			var entry = archive.GetEntry(HeroAbilitiesPath);
			if (entry == null)
			{
				LogLoadFailure(HeroAbilitiesPath + " not found in Core.zip at '" + coreZipPath + "'.");
				return false;
			}

			using var reader = new StreamReader(entry.Open());
			var json = reader.ReadToEnd();
			var root = JObject.Parse(json);
			var arrayToken = root["array"];
			if (arrayToken == null || arrayToken.Type != JTokenType.Array)
			{
				LogLoadFailure(
					HeroAbilitiesPath
					+ " has no array in Core.zip at '"
					+ coreZipPath
					+ "'; rootType='"
					+ root.Type
					+ "' arrayTokenType='"
					+ (arrayToken == null ? "<null>" : arrayToken.Type.ToString())
					+ "' rootPreview='"
					+ DescribeRootPreview(root)
					+ "' length="
					+ json.Length
					+ ".");
				return false;
			}

			JArray rows;
			try
			{
				rows = JArray.Parse(arrayToken.ToString());
			}
			catch (Exception ex)
			{
				LogLoadFailure(HeroAbilitiesPath + " array parse failed in Core.zip at '" + coreZipPath + "': " + ex.Message);
				return false;
			}

			for (var rowIndex = 0; rowIndex < rows.Count; rowIndex++)
			{
				var rowToken = rows[rowIndex];
				if (rowToken == null || rowToken.Type != JTokenType.Object)
					continue;
				JObject row;
				try
				{
					row = JObject.Parse(rowToken.ToString());
				}
				catch (Exception ex)
				{
					LogLoadFailure(HeroAbilitiesPath + " row " + rowIndex + " parse failed: " + ex.Message);
					return false;
				}

				var id = row["id"]?.ToString()?.Trim();
				if (!IsCustomFactionHeroAbilitySid(id))
					continue;
				var levelsToken = row["levels"];
				if (levelsToken == null || levelsToken.Type != JTokenType.Array)
				{
					LogLoadFailure(HeroAbilitiesPath + " custom hero ability row '" + id + "' has no levels array.");
					return false;
				}
				var levels = JArray.Parse(levelsToken.ToString());
				if (levels.Count == 0)
				{
					LogLoadFailure(HeroAbilitiesPath + " custom hero ability row '" + id + "' has no levels.");
					return false;
				}

				var icons = new string[levels.Count];
				for (var i = 0; i < levels.Count; i++)
				{
					var levelToken = levels[i];
					if (levelToken == null || levelToken.Type != JTokenType.Object)
					{
						LogLoadFailure(HeroAbilitiesPath + " custom hero ability row '" + id + "' level " + i + " is not an object.");
						return false;
					}
					JObject level;
					try
					{
						level = JObject.Parse(levelToken.ToString());
					}
					catch (Exception ex)
					{
						LogLoadFailure(HeroAbilitiesPath + " custom hero ability row '" + id + "' level " + i + " parse failed: " + ex.Message);
						return false;
					}

					var icon = level["icon"]?.ToString()?.Trim();
					if (string.IsNullOrWhiteSpace(icon))
					{
						LogLoadFailure(HeroAbilitiesPath + " custom hero ability row '" + id + "' level " + i + " has no icon.");
						return false;
					}
					icons[i] = icon;
				}

				loadedIcons[id] = icons;
				loadedRows++;
			}
		}
		catch (Exception ex)
		{
			LogLoadFailure("failed to load Core custom hero ability icon map: " + ex.Message);
			return false;
		}

		if (loadedRows == 0)
		{
			LogLoadFailure("loaded zero custom hero ability icon rows from Core.zip.");
			return false;
		}

		_iconsByAbilitySid = loadedIcons;
		_nextLoadRetryUtc = DateTime.MinValue;
		LogLoadSuccess("loaded " + loadedRows + " custom hero ability icon row(s) from Core.zip.", false);
		return true;
	}

	private static bool IsCustomFactionHeroAbilitySid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid)
		       && sid.StartsWith("skill_faction_homm3_", StringComparison.Ordinal)
		       && sid.IndexOf("_ability_", StringComparison.Ordinal) >= 0;
	}

	private static string DescribeRootPreview(JObject root)
	{
		if (root == null)
			return "<null>";
		var compact = root.ToString(Newtonsoft.Json.Formatting.None);
		if (compact.Length > 240)
			compact = compact.Substring(0, 240);
		return compact.Length == 0 ? "<empty>" : compact;
	}

	private static void LogLoadFailure(string message)
	{
		_loadFailureCount++;
		_nextLoadRetryUtc = DateTime.UtcNow.AddSeconds(2);
		if (_loadFailureCount != 1 && _loadFailureCount % 120 != 0)
			return;
		Plugin.LogSource?.LogWarning("Homm3CustomHeroAbilityIcon: " + message + " attempt=" + _loadFailureCount + ".");
	}

	private static void LogLoadSuccess(string message, bool warning)
	{
		if (_successLogged)
			return;
		_successLogged = true;
		if (warning)
			Plugin.LogSource?.LogWarning("Homm3CustomHeroAbilityIcon: " + message);
		else
			Plugin.LogSource?.LogInfo("Homm3CustomHeroAbilityIcon: " + message);
	}
}
