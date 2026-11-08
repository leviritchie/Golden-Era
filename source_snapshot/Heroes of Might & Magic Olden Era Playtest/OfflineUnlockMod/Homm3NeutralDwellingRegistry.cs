using System;
using System.Collections.Generic;
using System.IO;
using BepInEx;
using Newtonsoft.Json.Linq;

namespace OfflineUnlockMod;

/// <summary>
/// Billboard asset lookup for creature-keyed HoMM3 neutral dwellings
/// (<c>barracks_homm3_neutral_*</c> / land-on aliases).
/// </summary>
internal static class Homm3NeutralDwellingRegistry
{
	private static readonly object Gate = new();
	private static Dictionary<string, string> _pathsBySid;
	private static bool _loadAttempted;

	internal static bool TryGetBillboardRelativePath(string sid, out string relativePath)
	{
		relativePath = null;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		EnsureLoaded();
		if (_pathsBySid == null)
			return false;
		return _pathsBySid.TryGetValue(sid.Trim(), out relativePath)
			&& !string.IsNullOrWhiteSpace(relativePath);
	}

	private static void EnsureLoaded()
	{
		if (_loadAttempted)
			return;
		lock (Gate)
		{
			if (_loadAttempted)
				return;
			_loadAttempted = true;
			try
			{
				var path = Path.Combine(Paths.PluginPath, "OfflineUnlockMod", "homm3_neutral_dwellings.json");
				if (!File.Exists(path))
				{
					var alt = Path.Combine(Path.GetDirectoryName(typeof(Homm3NeutralDwellingRegistry).Assembly.Location) ?? string.Empty, "homm3_neutral_dwellings.json");
					path = File.Exists(alt) ? alt : path;
				}
				if (!File.Exists(path))
				{
					Plugin.LogSource?.LogWarning("Homm3NeutralDwellingRegistry: missing homm3_neutral_dwellings.json");
					_pathsBySid = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
					return;
				}
				var root = JObject.Parse(File.ReadAllText(path));
				var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
				// IL2CPP-safe: dwellings is a JArray of {sid, relativePath}, not a JObject map.
				if (root["dwellings"] is JArray rows)
				{
					for (var i = 0; i < rows.Count; i++)
					{
						if (rows[i] is not JObject row)
							continue;
						var key = row["sid"]?.ToString();
						var value = row["relativePath"]?.ToString();
						if (string.IsNullOrWhiteSpace(key) || string.IsNullOrWhiteSpace(value))
							continue;
						map[key.Trim()] = value.Trim().Replace('\\', '/');
					}
				}
				_pathsBySid = map;
				Plugin.LogSource?.LogInfo("Homm3NeutralDwellingRegistry: loaded " + map.Count + " dwelling billboard path(s).");
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning("Homm3NeutralDwellingRegistry: failed to load registry: " + ex.Message);
				_pathsBySid = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
			}
		}
	}
}
