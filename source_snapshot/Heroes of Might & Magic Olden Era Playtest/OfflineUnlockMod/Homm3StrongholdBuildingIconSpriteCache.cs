using System;
using System.Collections.Generic;
using System.IO;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3StrongholdBuildingIconSpriteCache
{
	private static readonly string StrongholdLayerFolder = Path.Combine("homm3_runtime_assets", "town_scene_refs", "homm3_stronghold", "layers");
	private static readonly string TowerLayerFolder = Path.Combine("homm3_runtime_assets", "town_scene_refs", "homm3_tower", "layers");
	private static readonly string TowerBuildingIconFolder = Path.Combine("homm3_runtime_assets", "town_scene_refs", "homm3_tower", "building_icons", "althalltowr.dir");
	private static readonly string FortressBuildingIconFolder = Path.Combine("homm3_runtime_assets", "town_scene_refs", "homm3_fortress", "building_icons", "hallfortalt.dir");
	private const string BlueprintSuffix = "_BP";
	private static readonly HashSet<string> LoggedBlueprintKeys = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, Sprite> SpritesByKey = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, SourceMapEntry> SourceMapsByFaction = new(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, string> SourceMapStampsByFaction = new(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, (string Folder, string File)> FileByKey = new(StringComparer.Ordinal)
	{
		["homm3_stronghold_building_Build_Main_level_1"] = (StrongholdLayerFolder, "extraCapitol_1.png"),
		["homm3_stronghold_building_Build_Main_level_2"] = (StrongholdLayerFolder, "extraCapitol_2.png"),
		["homm3_stronghold_building_Build_Main_level_3"] = (StrongholdLayerFolder, "extraCapitol_4.png"),
		["homm3_stronghold_building_Build_Tavern_level_1"] = (StrongholdLayerFolder, "tavern.png"),
		["homm3_stronghold_building_Build_Market_level_1"] = (StrongholdLayerFolder, "market.png"),
		["homm3_stronghold_building_Build_Artifact_Market_level_1"] = (StrongholdLayerFolder, "artifactMarket.png"),
		["homm3_stronghold_building_Build_Tier_1_level_1"] = (StrongholdLayerFolder, "dwellingUp2Lvl1.png"),
		["homm3_stronghold_building_Build_Tier_1_level_2"] = (StrongholdLayerFolder, "dwellingUp2Lvl1_2.png"),
		["homm3_stronghold_building_Build_Tier_2_level_1"] = (StrongholdLayerFolder, "dwellingUp2Lvl2.png"),
		["homm3_stronghold_building_Build_Tier_2_level_2"] = (StrongholdLayerFolder, "dwellingUp2Lvl2_2.png"),
		["homm3_stronghold_building_Build_Tier_3_level_1"] = (StrongholdLayerFolder, "dwellingUp2Lvl3.png"),
		["homm3_stronghold_building_Build_Tier_3_level_2"] = (StrongholdLayerFolder, "dwellingUp2Lvl3_2.png"),
		["homm3_stronghold_building_Build_Tier_4_level_1"] = (StrongholdLayerFolder, "dwellingUp2Lvl4.png"),
		["homm3_stronghold_building_Build_Tier_4_level_2"] = (StrongholdLayerFolder, "dwellingUp2Lvl4_2.png"),
		["homm3_stronghold_building_Build_Tier_5_level_1"] = (StrongholdLayerFolder, "dwellingUp2Lvl5.png"),
		["homm3_stronghold_building_Build_Tier_5_level_2"] = (StrongholdLayerFolder, "dwellingUp2Lvl5_2.png"),
		["homm3_stronghold_building_Build_Tier_6_level_1"] = (StrongholdLayerFolder, "dwellingUp2Lvl6.png"),
		["homm3_stronghold_building_Build_Tier_6_level_2"] = (StrongholdLayerFolder, "dwellingUp2Lvl6_2.png"),
		["homm3_stronghold_building_Build_Tier_7_level_1"] = (StrongholdLayerFolder, "dwellingUp2Lvl7.png"),
		["homm3_stronghold_building_Build_Tier_7_level_2"] = (StrongholdLayerFolder, "dwellingUp2Lvl7_2.png"),
		["homm3_stronghold_building_Build_Magic_Guild_level_1"] = (StrongholdLayerFolder, "magicGuild_1.png"),
		["homm3_stronghold_building_Build_Magic_Guild_level_2"] = (StrongholdLayerFolder, "magicGuild_2.png"),
		["homm3_stronghold_building_Build_Magic_Guild_level_3"] = (StrongholdLayerFolder, "magicGuild_3.png"),
		["homm3_stronghold_building_Build_Magic_Guild_level_4"] = (StrongholdLayerFolder, "magicGuild_3.png"),
		["homm3_stronghold_building_Build_Magic_Guild_level_5"] = (StrongholdLayerFolder, "magicGuild_3.png"),
		["homm3_stronghold_building_Build_Bank_level_1"] = (StrongholdLayerFolder, "bank.png"),
		["homm3_stronghold_building_Build_Treasury_level_1"] = (StrongholdLayerFolder, "wall_1.png"),
		["homm3_stronghold_building_Build_Resource_Depot_level_1"] = (StrongholdLayerFolder, "resourceDepot.png"),
		["homm3_stronghold_building_Build_Resource_Depot_level_2_level_1"] = (StrongholdLayerFolder, "resourceDepot.png"),
		["homm3_stronghold_building_Build_Wall_level_1"] = (StrongholdLayerFolder, "treasury.png"),
		["homm3_stronghold_building_Build_Wall_level_2"] = (StrongholdLayerFolder, "treasury.png"),
		["homm3_stronghold_building_Build_Wall_level_3"] = (StrongholdLayerFolder, "treasury.png"),
		["homm3_stronghold_building_Build_Gymnasium_level_1"] = (StrongholdLayerFolder, "spyNetwork.png"),
		["homm3_stronghold_building_Build_Lyceum_level_1"] = (StrongholdLayerFolder, "resourceDepotLevel2.png"),
		["homm3_stronghold_building_Build_Spy_Network_level_1"] = (StrongholdLayerFolder, "lyceum.png"),

		// Tower hall/icon frames follow VCMI third-upgrades
		// config/town-screen/tower/factions.json hallSlots order, flattened in declaration order.
		// Do not remap these by visual guessing: many Tower silhouettes are similar at icon size.
		["homm3_tower_building_Build_Main_level_1"] = (TowerBuildingIconFolder, "00_00.png"),
		["homm3_tower_building_Build_Main_level_2"] = (TowerBuildingIconFolder, "00_01.png"),
		["homm3_tower_building_Build_Main_level_3"] = (TowerBuildingIconFolder, "00_02.png"),
		["homm3_tower_building_Build_Wall_level_1"] = (TowerBuildingIconFolder, "00_04.png"),
		["homm3_tower_building_Build_Wall_level_2"] = (TowerBuildingIconFolder, "00_05.png"),
		["homm3_tower_building_Build_Wall_level_3"] = (TowerBuildingIconFolder, "00_06.png"),
		["homm3_tower_building_Build_Tavern_level_1"] = (TowerBuildingIconFolder, "00_07.png"),
		["homm3_tower_building_Build_Market_level_1"] = (TowerBuildingIconFolder, "00_09.png"),
		["homm3_tower_building_Build_Resource_Depot_level_1"] = (TowerBuildingIconFolder, "00_10.png"),
		["homm3_tower_building_Build_Magic_Guild_level_1"] = (TowerBuildingIconFolder, "00_11.png"),
		["homm3_tower_building_Build_Magic_Guild_level_2"] = (TowerBuildingIconFolder, "00_12.png"),
		["homm3_tower_building_Build_Magic_Guild_level_3"] = (TowerBuildingIconFolder, "00_13.png"),
		["homm3_tower_building_Build_Magic_Guild_level_4"] = (TowerBuildingIconFolder, "00_14.png"),
		["homm3_tower_building_Build_Magic_Guild_level_5"] = (TowerBuildingIconFolder, "00_15.png"),
		["homm3_tower_building_Build_Artifact_Market_level_1"] = (TowerBuildingIconFolder, "00_16.png"),
		["homm3_tower_building_Build_Intelligence_Academy_level_1"] = (TowerBuildingIconFolder, "00_19.png"),
		["homm3_tower_building_Build_Training_Range_level_1"] = (TowerBuildingIconFolder, "00_18.png"),
		["homm3_tower_building_Build_Bank_level_1"] = (TowerBuildingIconFolder, "00_03.png"),
		["homm3_tower_building_Build_Treasury_level_1"] = (TowerBuildingIconFolder, "00_08.png"),
		["homm3_tower_building_Build_Resource_Depot_level_2_level_1"] = (TowerBuildingIconFolder, "00_17.png"),
		["homm3_tower_building_Build_Golden_Calf_level_1"] = (TowerBuildingIconFolder, "00_22.png"),
		["homm3_tower_building_Build_Tier_1_level_1"] = (TowerBuildingIconFolder, "00_23.png"),
		["homm3_tower_building_Build_Tier_1_level_2"] = (TowerBuildingIconFolder, "00_24.png"),
		["homm3_tower_building_Build_Tier_2_level_1"] = (TowerBuildingIconFolder, "00_26.png"),
		["homm3_tower_building_Build_Tier_2_level_2"] = (TowerBuildingIconFolder, "00_27.png"),
		["homm3_tower_building_Build_Tier_3_level_1"] = (TowerBuildingIconFolder, "00_29.png"),
		["homm3_tower_building_Build_Tier_3_level_2"] = (TowerBuildingIconFolder, "00_30.png"),
		["homm3_tower_building_Build_Tier_4_level_1"] = (TowerBuildingIconFolder, "00_32.png"),
		["homm3_tower_building_Build_Tier_4_level_2"] = (TowerBuildingIconFolder, "00_33.png"),
		["homm3_tower_building_Build_Tier_5_level_1"] = (TowerBuildingIconFolder, "00_35.png"),
		["homm3_tower_building_Build_Tier_5_level_2"] = (TowerBuildingIconFolder, "00_36.png"),
		["homm3_tower_building_Build_Tier_6_level_1"] = (TowerBuildingIconFolder, "00_38.png"),
		["homm3_tower_building_Build_Tier_6_level_2"] = (TowerBuildingIconFolder, "00_39.png"),
		["homm3_tower_building_Build_Tier_7_level_1"] = (TowerBuildingIconFolder, "00_41.png"),
		["homm3_tower_building_Build_Tier_7_level_2"] = (TowerBuildingIconFolder, "00_42.png"),

		// Fortress hall/icon frames follow VCMI third-upgrades
		// config/town-screen/fortress/factions.json hallSlots order, flattened in declaration order.
		["homm3_fortress_building_Build_Main_level_1"] = (FortressBuildingIconFolder, "00_00.png"),
		["homm3_fortress_building_Build_Main_level_2"] = (FortressBuildingIconFolder, "00_01.png"),
		["homm3_fortress_building_Build_Main_level_3"] = (FortressBuildingIconFolder, "00_02.png"),
		["homm3_fortress_building_Build_Wall_level_1"] = (FortressBuildingIconFolder, "00_04.png"),
		["homm3_fortress_building_Build_Wall_level_2"] = (FortressBuildingIconFolder, "00_05.png"),
		["homm3_fortress_building_Build_Wall_level_3"] = (FortressBuildingIconFolder, "00_06.png"),
		["homm3_fortress_building_Build_Tavern_level_1"] = (FortressBuildingIconFolder, "00_07.png"),
		["homm3_fortress_building_Build_Treasury_level_1"] = (FortressBuildingIconFolder, "00_08.png"),
		["homm3_fortress_building_Build_Market_level_1"] = (FortressBuildingIconFolder, "00_09.png"),
		["homm3_fortress_building_Build_Resource_Depot_level_1"] = (FortressBuildingIconFolder, "00_10.png"),
		["homm3_fortress_building_Build_Magic_Guild_level_1"] = (FortressBuildingIconFolder, "00_11.png"),
		["homm3_fortress_building_Build_Magic_Guild_level_2"] = (FortressBuildingIconFolder, "00_12.png"),
		["homm3_fortress_building_Build_Magic_Guild_level_3"] = (FortressBuildingIconFolder, "00_13.png"),
		["homm3_fortress_building_Build_Magic_Guild_level_4"] = (FortressBuildingIconFolder, "00_13.png"),
		["homm3_fortress_building_Build_Magic_Guild_level_5"] = (FortressBuildingIconFolder, "00_13.png"),
		["homm3_fortress_building_Build_Bank_level_1"] = (FortressBuildingIconFolder, "00_15.png"),
		["homm3_fortress_building_Build_Gymnasium_level_1"] = (FortressBuildingIconFolder, "00_16.png"),
		["homm3_fortress_building_Build_Lyceum_level_1"] = (FortressBuildingIconFolder, "00_17.png"),
		["homm3_fortress_building_Build_Resource_Depot_level_2_level_1"] = (FortressBuildingIconFolder, "00_19.png"),
		["homm3_fortress_building_Build_Tier_1_level_1"] = (FortressBuildingIconFolder, "00_21.png"),
		["homm3_fortress_building_Build_Tier_1_level_2"] = (FortressBuildingIconFolder, "00_22.png"),
		["homm3_fortress_building_Build_Tier_2_level_1"] = (FortressBuildingIconFolder, "00_24.png"),
		["homm3_fortress_building_Build_Tier_2_level_2"] = (FortressBuildingIconFolder, "00_25.png"),
		["homm3_fortress_building_Build_Tier_3_level_1"] = (FortressBuildingIconFolder, "00_27.png"),
		["homm3_fortress_building_Build_Tier_3_level_2"] = (FortressBuildingIconFolder, "00_28.png"),
		["homm3_fortress_building_Build_Tier_4_level_1"] = (FortressBuildingIconFolder, "00_30.png"),
		["homm3_fortress_building_Build_Tier_4_level_2"] = (FortressBuildingIconFolder, "00_31.png"),
		["homm3_fortress_building_Build_Tier_5_level_1"] = (FortressBuildingIconFolder, "00_33.png"),
		["homm3_fortress_building_Build_Tier_5_level_2"] = (FortressBuildingIconFolder, "00_34.png"),
		["homm3_fortress_building_Build_Tier_6_level_1"] = (FortressBuildingIconFolder, "00_36.png"),
		["homm3_fortress_building_Build_Tier_6_level_2"] = (FortressBuildingIconFolder, "00_37.png"),
		["homm3_fortress_building_Build_Tier_7_level_1"] = (FortressBuildingIconFolder, "00_39.png"),
		["homm3_fortress_building_Build_Tier_7_level_2"] = (FortressBuildingIconFolder, "00_40.png"),
	};

	internal static bool IsStrongholdBuildingIconKey(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return false;
		var trimmed = key.Trim();
		return Homm3CustomFactionRegistry.IsCustomBuildingIconKey(trimmed);
	}

	internal static bool TryGetOrCreateSprite(string iconKey, out Sprite sprite)
	{
		sprite = null;
		if (!IsStrongholdBuildingIconKey(iconKey))
			return false;

		var key = iconKey.Trim();
		if (SpritesByKey.TryGetValue(key, out sprite) && sprite)
			return true;
		// Native build panel / building tooltip asks for '<building>_level_N_BP' (vanilla ships a
		// separate blueprint sprite per building). HoMM3 has exactly one hall icon per building and
		// no blueprint art, so the blueprint key resolves to that same hall icon by explicit rule.
		// If the base icon is itself unresolved this returns false and the caller declines + logs.
		if (key.EndsWith(BlueprintSuffix, StringComparison.Ordinal))
		{
			var baseKey = key.Substring(0, key.Length - BlueprintSuffix.Length);
			if (baseKey.Length == 0 || !TryGetOrCreateSprite(baseKey, out sprite) || !sprite)
			{
				sprite = null;
				return false;
			}
			SpritesByKey[key] = sprite;
			if (LoggedBlueprintKeys.Add(key))
				Plugin.LogSource?.LogInfo("Homm3StrongholdBuildingIcon: blueprint key '" + key + "' uses HoMM3 hall icon '" + baseKey + "' (HoMM3 has no blueprint art).");
			return true;
		}
		if (!TryResolveSourceMappedFile(key, out var file)
			&& !FileByKey.TryGetValue(key, out file))
			return false;

		var path = ResolveIconPath(file.Folder, file.File);
		if (path == null)
			return false;

		try
		{
			var bytes = File.ReadAllBytes(path);
			var texture = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: false);
			var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
			for (var i = 0; i < bytes.Length; i++)
				il2cppBytes[i] = bytes[i];
			if (!ImageConversion.LoadImage(texture, il2cppBytes))
			{
				UnityEngine.Object.Destroy(texture);
				return false;
			}

			texture.name = "homm3_building_icon_" + key;
			texture.filterMode = FilterMode.Bilinear;
			texture.wrapMode = TextureWrapMode.Clamp;
			sprite = Sprite.Create(
				texture,
				new Rect(0f, 0f, texture.width, texture.height),
				new Vector2(0.5f, 0.5f),
				100f,
				0,
				SpriteMeshType.FullRect);
			sprite.name = "homm3_building_icon_sprite_" + key;
			SpritesByKey[key] = sprite;
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3StrongholdBuildingIcon: failed to load '" + path + "': " + ex.Message);
			return false;
		}
	}

	private static string ResolveIconPath(string folder, string file)
	{
		var roots = new[] { BepInEx.Paths.PluginPath, BepInEx.Paths.GameRootPath };
		foreach (var root in roots)
		{
			var path = Path.Combine(root, "OfflineUnlockMod", folder, file);
			if (File.Exists(path))
				return path;
		}
		return null;
	}

	private static bool TryResolveSourceMappedFile(string key, out (string Folder, string File) file)
	{
		file = default;
		if (!TryParseCustomBuildingIconKey(key, out var factionSid, out var buildingSid, out var level))
			return false;

		var sourceMap = GetSourceMap(factionSid);
		if (sourceMap == null)
			return false;

		if (!sourceMap.FileByBuildingLevel.TryGetValue(BuildSourceMapKey(buildingSid, level), out var mappedFile)
			&& !sourceMap.FileByBuildingLevel.TryGetValue(BuildSourceMapKey(buildingSid, 1), out mappedFile))
			return false;

		file = (Path.Combine(sourceMap.FolderRoot, mappedFile.Folder), mappedFile.File);
		return true;
	}

	private static bool TryParseCustomBuildingIconKey(string key, out string factionSid, out string buildingSid, out int level)
	{
		factionSid = null;
		buildingSid = null;
		level = 0;
		if (string.IsNullOrWhiteSpace(key))
			return false;

		var trimmed = key.Trim();
		foreach (var candidateFaction in Homm3CustomFactionRegistry.EnumerateFactionSids())
		{
			var prefix = Homm3CustomFactionRegistry.GetBuildingIconKeyPrefix(candidateFaction);
			if (string.IsNullOrEmpty(prefix) || !trimmed.StartsWith(prefix, StringComparison.Ordinal))
				continue;

			factionSid = candidateFaction;
			var body = trimmed.Substring(prefix.Length);
			var marker = body.LastIndexOf("_level_", StringComparison.Ordinal);
			if (marker <= 0)
				return false;

			buildingSid = body.Substring(0, marker);
			return int.TryParse(body.Substring(marker + "_level_".Length), out level) && level > 0;
		}

		return false;
	}

	private static SourceMapEntry GetSourceMap(string factionSid)
	{
		if (string.IsNullOrWhiteSpace(factionSid))
			return null;

		var folderRoot = Path.Combine("homm3_runtime_assets", "town_scene_refs", factionSid, "building_icons");
		var sourceMapPath = ResolveSourceMapPath(folderRoot);
		var stamp = GetFileStamp(sourceMapPath);
		if (SourceMapsByFaction.TryGetValue(factionSid, out var cached)
			&& SourceMapStampsByFaction.TryGetValue(factionSid, out var cachedStamp)
			&& string.Equals(cachedStamp, stamp, StringComparison.Ordinal))
			return cached;

		SourceMapStampsByFaction[factionSid] = stamp;
		var parsed = ParseSourceMap(sourceMapPath, folderRoot);
		if (parsed != null)
			SourceMapsByFaction[factionSid] = parsed;
		else
			SourceMapsByFaction.Remove(factionSid);
		return parsed;
	}

	private static string ResolveSourceMapPath(string folderRoot)
	{
		var roots = new[] { BepInEx.Paths.PluginPath, BepInEx.Paths.GameRootPath };
		foreach (var root in roots)
		{
			var folder = Path.Combine(root, "OfflineUnlockMod", folderRoot);
			if (!Directory.Exists(folder))
				continue;
			var files = Directory.GetFiles(folder, "*_source_map.json", SearchOption.TopDirectoryOnly);
			if (files.Length > 0)
				return files[0];
		}
		return null;
	}

	private static SourceMapEntry ParseSourceMap(string path, string folderRoot)
	{
		if (string.IsNullOrEmpty(path) || !File.Exists(path))
			return null;

		try
		{
			var root = JObject.Parse(File.ReadAllText(path));
			var frameFolder = root["folder"]?.ToString();
			if (string.IsNullOrWhiteSpace(frameFolder))
				frameFolder = root["iconFolder"]?.ToString();
			if (string.IsNullOrWhiteSpace(frameFolder))
				return null;

			var result = new Dictionary<string, SourceMappedFile>(StringComparer.OrdinalIgnoreCase);
			// Live-negative (Fortress black cityFactory): a nested-object-blind regex skipped
			// object-valued map entries such as Build_Spring_of_Life → {folder, file}. PrefixSpriteResolver then
			// threw sprite-unresolved during native city UI init, Main never bound, and the owned
			// camera stayed on the SolidColor black plate. Index known keys and parse string or
			// object values; do not foreach JProperty (IL2CPP Newtonsoft proxy).
			AddMappedFilesFromMapObject(root["map"], frameFolder, result);
			AddMappedFilesFromExplicitFiles(root["explicitFiles"], frameFolder, result);

			var frames = root["frames"] as JArray;
			if (frames == null && root["frames"] != null)
				frames = JArray.Parse(root["frames"].ToString());
			if (frames != null)
			{
				for (var frameIndex = 0; frameIndex < frames.Count; frameIndex++)
				{
					var frame = frames[frameIndex];
					var building = frame["oldenEraSid"]?.ToString();
					var file = frame["frame"]?.ToString();
					if (string.IsNullOrWhiteSpace(building) || string.IsNullOrWhiteSpace(file))
						continue;
					if (!int.TryParse(frame["oldenEraLevel"]?.ToString(), out var levelNumber) || levelNumber <= 0)
						continue;
					result[BuildSourceMapKey(building, levelNumber)] = new SourceMappedFile(frameFolder, file);
				}
			}

			return result.Count == 0 ? null : new SourceMapEntry(folderRoot, frameFolder, result);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3StrongholdBuildingIcon: failed to parse source map '" + path + "': " + ex.Message);
			return null;
		}
	}

	private static string BuildSourceMapKey(string buildingSid, int level)
	{
		return (buildingSid ?? "") + "\n" + Math.Max(1, level);
	}

	private static void AddMappedFilesFromMapObject(
		JToken mapToken,
		string defaultFolder,
		Dictionary<string, SourceMappedFile> result)
	{
		if (mapToken == null || mapToken.Type != JTokenType.Object || result == null)
			return;

		JObject map;
		try
		{
			map = JObject.Parse(mapToken.ToString());
		}
		catch
		{
			return;
		}

		var mapJson = map.ToString(Newtonsoft.Json.Formatting.None);
		var buildingMatches = System.Text.RegularExpressions.Regex.Matches(
			mapJson,
			"\"(?<building>Build_[^\"]+)\"\\s*:");
		var seen = new HashSet<string>(StringComparer.Ordinal);
		for (var i = 0; i < buildingMatches.Count; i++)
		{
			var building = buildingMatches[i].Groups["building"].Value;
			if (string.IsNullOrWhiteSpace(building) || building.IndexOf(':') >= 0 || !seen.Add(building))
				continue;
			var levelsToken = map[building];
			if (levelsToken == null || levelsToken.Type != JTokenType.Object)
				continue;

			JObject levels;
			try
			{
				levels = JObject.Parse(levelsToken.ToString());
			}
			catch
			{
				continue;
			}

			for (var level = 1; level <= 8; level++)
			{
				var levelToken = levels[level.ToString()];
				if (levelToken == null || levelToken.Type == JTokenType.Null)
					continue;
				if (!TryParseSourceMappedFile(levelToken, defaultFolder, out var mappedFile))
					continue;
				result[BuildSourceMapKey(building, level)] = mappedFile;
			}
		}
	}

	private static void AddMappedFilesFromExplicitFiles(
		JToken explicitToken,
		string defaultFolder,
		Dictionary<string, SourceMappedFile> result)
	{
		if (explicitToken == null || explicitToken.Type != JTokenType.Object || result == null)
			return;

		JObject explicitFiles;
		try
		{
			explicitFiles = JObject.Parse(explicitToken.ToString());
		}
		catch
		{
			return;
		}

		var explicitJson = explicitFiles.ToString(Newtonsoft.Json.Formatting.None);
		var keyMatches = System.Text.RegularExpressions.Regex.Matches(
			explicitJson,
			"\"(?<key>Build_[^\"]+:[0-9]+)\"\\s*:");
		var seen = new HashSet<string>(StringComparer.Ordinal);
		for (var i = 0; i < keyMatches.Count; i++)
		{
			var key = keyMatches[i].Groups["key"].Value;
			if (string.IsNullOrWhiteSpace(key) || !seen.Add(key))
				continue;
			var split = key.LastIndexOf(':');
			if (split <= 0 || split == key.Length - 1)
				continue;
			var building = key.Substring(0, split);
			if (!int.TryParse(key.Substring(split + 1), out var level) || level <= 0)
				continue;
			if (!TryParseSourceMappedFile(explicitFiles[key], defaultFolder, out var mappedFile))
				continue;
			result[BuildSourceMapKey(building, level)] = mappedFile;
		}
	}

	private static bool TryParseSourceMappedFile(JToken token, string defaultFolder, out SourceMappedFile mappedFile)
	{
		mappedFile = default;
		if (token == null || token.Type == JTokenType.Null)
			return false;

		string file;
		string folder;
		if (token.Type == JTokenType.String)
		{
			file = token.ToString();
			folder = defaultFolder;
		}
		else if (token.Type == JTokenType.Object)
		{
			JObject obj;
			try
			{
				obj = JObject.Parse(token.ToString());
			}
			catch
			{
				return false;
			}

			file = obj["file"]?.ToString();
			folder = obj["folder"]?.ToString();
		}
		else
			return false;

		if (string.IsNullOrWhiteSpace(folder))
			folder = defaultFolder;
		if (string.IsNullOrWhiteSpace(file))
			return false;

		mappedFile = new SourceMappedFile(folder, file);
		return true;
	}

	private static string GetFileStamp(string path)
	{
		if (string.IsNullOrEmpty(path) || !File.Exists(path))
			return null;
		try
		{
			var info = new FileInfo(path);
			return info.Length + ":" + info.LastWriteTimeUtc.Ticks;
		}
		catch
		{
			return null;
		}
	}

	private sealed class SourceMapEntry
	{
		internal SourceMapEntry(string folderRoot, string frameFolder, Dictionary<string, SourceMappedFile> fileByBuildingLevel)
		{
			FolderRoot = folderRoot;
			FrameFolder = frameFolder;
			FileByBuildingLevel = fileByBuildingLevel;
		}

		internal string FolderRoot { get; }
		internal string FrameFolder { get; }
		internal Dictionary<string, SourceMappedFile> FileByBuildingLevel { get; }
	}

	private readonly struct SourceMappedFile
	{
		internal SourceMappedFile(string folder, string file)
		{
			Folder = folder;
			File = file;
		}

		internal string Folder { get; }
		internal string File { get; }
	}
}
