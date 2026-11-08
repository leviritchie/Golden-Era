using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BepInEx;
using BepInEx.Logging;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// UniverSR 48 kHz unique-clip cache for custom unit battle SFX.
/// When a lab SID is in catalog.json, those WAVs replace bundle AudioClips for that unit.
/// </summary>
internal static class Homm3UpscaledBattleSfx
{
	const string FolderName = "homm3_upscaled_sfx";
	const string CatalogFileName = "catalog.json";
	static readonly object Gate = new();
	static bool _loadAttempted;
	static JObject _catalog;
	static string _root;
	static readonly Dictionary<string, AudioClip> ClipsById = new(StringComparer.OrdinalIgnoreCase);

	internal static bool TryFillLabClips(string labSid, string stemPrefix, Dictionary<string, AudioClip> dest, ManualLogSource log)
	{
		if (dest == null || string.IsNullOrEmpty(labSid) || string.IsNullOrEmpty(stemPrefix))
			return false;
		EnsureLoaded(log);
		if (_catalog == null)
			return false;
		if (!TryUnitRoles(labSid, out var roles))
			return false;
		FillStems(stemPrefix, roles, dest, log);
		return true;
	}

	internal static bool TryFillEsquireClips(Dictionary<string, AudioClip> dest, ManualLogSource log)
	{
		if (dest == null)
			return false;
		EnsureLoaded(log);
		if (_catalog == null)
			return false;
		var filled = false;
		if (TryUnitRoles("esquire", out var baseRoles))
		{
			FillStems("ESQUIRE_", baseRoles, dest, log);
			filled = true;
		}

		if (TryUnitRoles("esquire_upg", out var upgRoles))
		{
			FillStems("ESQUIRE_UPG_", upgRoles, dest, log);
			filled = true;
		}

		return filled;
	}

	static void FillStems(string stemPrefix, Dictionary<string, string> roles, Dictionary<string, AudioClip> dest, ManualLogSource log)
	{
		if (roles.TryGetValue("attack", out var attack))
			AssignVariants(dest, stemPrefix + "Attack_", 1, 4, attack, log);
		if (roles.TryGetValue("wince", out var wince))
			AssignVariants(dest, stemPrefix + "Damage_", 1, 4, wince, log);
		if (roles.TryGetValue("move", out var move))
		{
			AssignVariants(dest, stemPrefix + "Walk_", 1, 4, move, log);
			AssignVariants(dest, stemPrefix + "Victory_A_", 1, 8, move, log);
			AssignVariants(dest, stemPrefix + "Victory_B_", 1, 3, move, log);
		}

		if (roles.TryGetValue("killed", out var killed))
		{
			AssignVariants(dest, stemPrefix + "Death_A_", 1, 4, killed, log);
			AssignVariants(dest, stemPrefix + "Death_B_", 1, 4, killed, log);
			AssignVariants(dest, stemPrefix + "Death_C_", 1, 4, killed, log);
		}
	}

	static void AssignVariants(Dictionary<string, AudioClip> dest, string stemPrefix, int lo, int hi, string clipId, ManualLogSource log)
	{
		var clip = LoadClip(clipId, log);
		if (clip == null || !clip)
			return;
		for (var i = lo; i <= hi; i++)
			dest[stemPrefix + i] = clip;
	}

	static AudioClip LoadClip(string clipId, ManualLogSource log)
	{
		if (string.IsNullOrEmpty(clipId))
			return null;
		lock (Gate)
		{
			if (ClipsById.TryGetValue(clipId, out var cached) && cached)
				return cached;
			var rel = ReadString(_catalog["clips"]?[clipId]);
			if (string.IsNullOrEmpty(rel) || string.IsNullOrEmpty(_root))
			{
				log?.LogError("Homm3UpscaledBattleSfx: catalog missing clip '" + clipId + "'.");
				return null;
			}

			var path = Path.GetFullPath(Path.Combine(_root, rel.Replace('/', Path.DirectorySeparatorChar)));
			if (!File.Exists(path))
			{
				log?.LogError("Homm3UpscaledBattleSfx: missing WAV " + path);
				return null;
			}

			try
			{
				var clip = Homm3PcmWav.Load(path, clipId);
				ClipsById[clipId] = clip;
				return clip;
			}
			catch (Exception ex)
			{
				log?.LogError("Homm3UpscaledBattleSfx: failed to load " + path + ": " + ex.Message);
				return null;
			}
		}
	}

	static bool TryUnitRoles(string labSid, out Dictionary<string, string> roles)
	{
		roles = null;
		var units = _catalog?["units"];
		if (units == null)
			return false;
		var unit = units[labSid];
		if (unit == null || !unit.HasValues)
			return false;
		roles = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
		foreach (var role in new[] { "attack", "move", "wince", "killed", "defend", "shot" })
		{
			var id = ReadString(unit[role]);
			if (!string.IsNullOrEmpty(id))
				roles[role] = id;
		}

		return roles.Count > 0;
	}

	static void EnsureLoaded(ManualLogSource log)
	{
		lock (Gate)
		{
			if (_loadAttempted)
				return;
			_loadAttempted = true;
			_root = ResolveRoot();
			if (string.IsNullOrEmpty(_root))
			{
				log?.LogWarning("Homm3UpscaledBattleSfx: catalog folder not found; using bundle AudioClips.");
				return;
			}

			var catalogPath = Path.Combine(_root, CatalogFileName);
			if (!File.Exists(catalogPath))
			{
				log?.LogWarning("Homm3UpscaledBattleSfx: missing " + catalogPath + "; using bundle AudioClips.");
				return;
			}

			try
			{
				_catalog = JObject.Parse(File.ReadAllText(catalogPath));
				log?.LogInfo("Homm3UpscaledBattleSfx: loaded " + catalogPath);
			}
			catch (Exception ex)
			{
				log?.LogError("Homm3UpscaledBattleSfx: catalog parse failed: " + ex.Message);
			}
		}
	}

	static string ResolveRoot()
	{
		var candidates = new[]
		{
			Path.Combine(Paths.PluginPath, "OfflineUnlockMod", FolderName),
			Path.Combine(Paths.PluginPath, FolderName),
		};
		try
		{
			var loc = Assembly.GetExecutingAssembly().Location;
			if (!string.IsNullOrEmpty(loc))
			{
				var dir = Path.GetDirectoryName(loc);
				if (!string.IsNullOrEmpty(dir))
					candidates = new[]
					{
						Path.Combine(dir, FolderName),
						candidates[0],
						candidates[1],
					};
			}
		}
		catch
		{
		}

		for (var i = 0; i < candidates.Length; i++)
		{
			var path = candidates[i];
			if (!string.IsNullOrEmpty(path) && File.Exists(Path.Combine(path, CatalogFileName)))
				return path;
		}

		return null;
	}

	static string ReadString(JToken token)
	{
		if (token == null || token.Type == JTokenType.Null)
			return null;
		try
		{
			return token.ToString();
		}
		catch
		{
			return null;
		}
	}
}
