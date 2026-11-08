using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Data;
using Hex.UI.City;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace OfflineUnlockMod;

internal static class Homm3StrongholdTownLayers
{
	private const string LayerRootName = "OfflineUnlockStrongholdTownLayers";
	private const string BackdropObjectName = "OfflineUnlockCityBackdrop";
	private const string SessionFadeCanvasName = "Fade Canvas";
	private const string SessionFadeImageName = "image";
	private const string StrongholdFolderName = "homm3_stronghold";
	private const string TowerFolderName = "homm3_tower";
	private const string FortressFolderName = "homm3_fortress";
	private const string CoveFolderName = "homm3_cove";
	private const string TownPrefabBundleRelativePath = "homm3_town_prefabs/homm3_town_prefabs";
	// Unity stores AssetBundle asset names lower-case; keep this in the same
	// canonical form emitted by tools/build_homm3_town_prefabs.ps1.
	private const string TownPrefabAssetRoot = "assets/generated/homm3townprefabs";
	private const float ReferenceWidth = 1920f;
	private const float ReferenceHeight = 1080f;
	private const float TownLayerReferenceWidth = 800f;
	private const float TownLayerReferenceHeight = 600f;

	private const string BuildingLayerMapFileName = "building_layer_map.json";

	private sealed class CachedFileStamp
	{
		internal CachedFileStamp(int frame, string stamp)
		{
			Frame = frame;
			Stamp = stamp;
		}

		internal int Frame { get; }
		internal string Stamp { get; }
	}

	private sealed class CachedLayerTexture
	{
		internal string Stamp;
		internal Texture2D Texture;
	}

	private sealed class LayerUpdateProfile
	{
		internal int Buildings;
		internal int ActiveLayers;
		internal int CreatedImages;
		internal long ResolveMs;
		internal long EnsureImageMs;
		internal long TextureMs;
		internal long TransformMs;
		internal long AnimMs;
		internal long SortMs;
		internal long SiblingMs;
		internal long HideMs;
		internal long EffectsMs;
		internal int AnimPlayers;
		internal int EffectFades;
		internal bool UsedPrefab;
	}

	private sealed class MemberAccessor
	{
		internal FieldInfo Field;

		internal bool TryGetValue(object instance, out object value)
		{
			value = null;
			if (instance == null)
				return false;
			if (Field != null)
			{
				try
				{
					value = Field.GetValue(instance);
					return true;
				}
				catch
				{
					// Ignore and fall through.
				}
			}
			return false;
		}
	}

	private sealed class LayerPlacement
	{
		internal LayerPlacement(int x, int y, int z, int order, float referenceX, float referenceY, float referenceWidth, float referenceHeight, string sprite = null, string structure = null, bool hidden = false)
		{
			X = x;
			Y = y;
			Z = z;
			Order = order;
			ReferenceX = referenceX;
			ReferenceY = referenceY;
			ReferenceWidth = referenceWidth;
			ReferenceHeight = referenceHeight;
			Sprite = sprite;
			Structure = structure;
			Hidden = hidden;
		}

		internal int X { get; }
		internal int Y { get; }
		internal int Z { get; }
		internal int Order { get; }
		internal float ReferenceX { get; }
		internal float ReferenceY { get; }
		internal float ReferenceWidth { get; }
		internal float ReferenceHeight { get; }
		internal string Sprite { get; }
		internal string Structure { get; }
		internal bool Hidden { get; }
	}

	private sealed class ActiveLayerEntry
	{
		internal ActiveLayerEntry(RawImage image, LayerPlacement placement)
		{
			Image = image;
			Placement = placement;
		}

		internal RawImage Image { get; }
		internal LayerPlacement Placement { get; }
	}

	private sealed class PlannedLayerEntry
	{
		internal PlannedLayerEntry(string buildingSid, string layerId, int level, LayerPlacement placement)
		{
			BuildingSid = buildingSid;
			LayerId = layerId;
			Level = level;
			Placement = placement;
		}

		internal string BuildingSid { get; }
		internal string LayerId { get; }
		internal int Level { get; }
		internal LayerPlacement Placement { get; }
	}

	private sealed class PendingAnimAttachment
	{
		internal RawImage Image;
		internal string Fraction;
		internal string LayerId;
		internal int Level;
	}

	private sealed class ObservedTownBuildingState
	{
		internal string Fraction;
		internal readonly Dictionary<string, BuildingData> Buildings = new Dictionary<string, BuildingData>(StringComparer.OrdinalIgnoreCase);
	}

	// Layer placements are loaded at runtime from positions.json in the layers folder.
	// Edit that file and re-enter the city to see changes - no rebuild needed.
	private static readonly Dictionary<string, Dictionary<string, LayerPlacement>> _layerPlacementsCacheByRoot = new Dictionary<string, Dictionary<string, LayerPlacement>>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, string> _layerPlacementsStampByRoot = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, Dictionary<string, string>> _buildingLayerIdsCacheByRoot = new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, Dictionary<string, Dictionary<int, string>>> _buildingLayerLevelsCacheByRoot = new Dictionary<string, Dictionary<string, Dictionary<int, string>>>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, string> _buildingLayerIdsStampByRoot = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, CachedFileStamp> _fileStampCacheByPath = new Dictionary<string, CachedFileStamp>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, CachedLayerTexture> _layerTextureCacheByPath = new Dictionary<string, CachedLayerTexture>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<Type, Dictionary<string, MemberAccessor>> _memberAccessorCacheByType = new Dictionary<Type, Dictionary<string, MemberAccessor>>();
	private static bool _loggedSessionFadeRelease;
	private static float _lastSessionFadeReleaseAttempt;
	private static Graphic _cachedSessionFadeGraphic;
	private static int _cachedSessionFadeSceneHandle = -1;

	private static IReadOnlyDictionary<string, LayerPlacement> GetLayerPlacements(string fraction, bool requireValidMetadata = false)
	{
		var layerRoot = ResolveTownLayerRootRelativePath(fraction);
		if (layerRoot == null)
		{
			return new Dictionary<string, LayerPlacement>(StringComparer.OrdinalIgnoreCase);
		}

		var jsonRelPath = Path.Combine(layerRoot, "positions.json");
		var jsonPath = ResolveExistingPath(jsonRelPath, logMissing: false);
		var stamp = jsonPath != null ? GetTextureStamp(jsonPath) : null;
		if (!requireValidMetadata
			&& _layerPlacementsCacheByRoot.TryGetValue(layerRoot, out var cached)
			&& _layerPlacementsStampByRoot.TryGetValue(layerRoot, out var cachedStamp)
			&& string.Equals(cachedStamp, stamp, StringComparison.Ordinal))
		{
			return cached;
		}

		var parsed = ParseLayerPlacements(jsonPath, requireValidMetadata);
		_layerPlacementsStampByRoot[layerRoot] = stamp;
		_layerPlacementsCacheByRoot[layerRoot] = parsed;
		return parsed;
	}

	private static Dictionary<string, LayerPlacement> ParseLayerPlacements(string jsonPath, bool requireValidMetadata = false)
	{
		var result = new Dictionary<string, LayerPlacement>(StringComparer.OrdinalIgnoreCase);
		if (jsonPath == null || !File.Exists(jsonPath))
		{
			if (requireValidMetadata)
				throw new InvalidOperationException("required town positions.json is missing at " + (jsonPath ?? "(null)") + ".");
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town layers: positions.json not found at " + (jsonPath ?? "(null)"));
			return result;
		}

		try
		{
			var jroot = JObject.Parse(File.ReadAllText(jsonPath));
			var layersToken = jroot["layers"];
			if (layersToken == null)
			{
				if (requireValidMetadata)
					throw new InvalidOperationException("positions.json has no layers array at " + jsonPath + ".");
				return result;
			}

			// Re-parse via string to avoid IL2CPP JArray cast issues (same pattern as Homm3ImportVisuals).
			JArray arr;
			try
			{
				arr = JArray.Parse(layersToken.ToString());
			}
			catch (Exception ex)
			{
				if (requireValidMetadata)
					throw new InvalidOperationException("positions.json layers array is invalid at " + jsonPath + ": " + ex.Message, ex);
				Plugin.LogSource?.LogWarning("HoMM3 Stronghold town layers: could not parse layers array: " + ex.Message);
				return result;
			}

			for (var i = 0; i < arr.Count; i++)
			{
				JObject entry;
				try
				{
					entry = JObject.Parse(arr[i].ToString());
				}
				catch
				{
					if (requireValidMetadata)
						throw new InvalidOperationException("positions.json has an invalid layer entry at index " + i + " in " + jsonPath + ".");
					continue;
				}

				var id = entry["id"]?.ToString() ?? "";
				if (string.IsNullOrEmpty(id))
				{
					if (requireValidMetadata)
						throw new InvalidOperationException("positions.json layer entry " + i + " has no id in " + jsonPath + ".");
					continue;
				}

				var hasX = int.TryParse(entry["x"]?.ToString(), out var x);
				var hasY = int.TryParse(entry["y"]?.ToString(), out var y);
				var hasZ = int.TryParse(entry["z"]?.ToString(), out var z);
				if (requireValidMetadata && (!hasX || !hasY || !hasZ))
					throw new InvalidOperationException("positions.json layer " + id + " has invalid x/y/z coordinates in " + jsonPath + ".");
				if (!TryParseRequiredReferenceFloat(entry, "reference_x", out var referenceX)
				    || !TryParseRequiredReferenceFloat(entry, "reference_y", out var referenceY)
				    || !TryParseRequiredReferenceFloat(entry, "reference_w", out var referenceWidth)
				    || !TryParseRequiredReferenceFloat(entry, "reference_h", out var referenceHeight))
				{
					if (requireValidMetadata)
						throw new InvalidOperationException("positions.json layer " + id + " lacks valid reference bounds in " + jsonPath + ".");
					Plugin.LogSource?.LogWarning(
						"HoMM3 Stronghold town layers: skipping "
						+ id
						+ " because positions.json lacks prebaked reference_x/reference_y/reference_w/reference_h.");
					continue;
				}
				var sprite = entry["sprite"]?.ToString();
				if (string.IsNullOrEmpty(sprite)) sprite = null;
				var structure = entry["structure"]?.ToString();
				if (string.IsNullOrEmpty(structure)) structure = null;
				var hidden = string.Equals(entry["hidden"]?.ToString(), "true", StringComparison.OrdinalIgnoreCase);
				if (requireValidMetadata && result.ContainsKey(id))
					throw new InvalidOperationException("positions.json contains duplicate layer id " + id + " in " + jsonPath + ".");
				result[id] = new LayerPlacement(x, y, z, i, referenceX, referenceY, referenceWidth, referenceHeight, sprite, structure, hidden);
			}

			Plugin.LogSource?.LogInfo("HoMM3 Stronghold town layers: loaded " + result.Count + " placements from positions.json");
		}
		catch (Exception ex)
		{
			if (requireValidMetadata)
				throw new InvalidOperationException("required town positions metadata is invalid at " + jsonPath + ": " + ex.Message, ex);
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town layers: failed to parse positions.json: " + ex.Message);
		}

		return result;
	}

	private static bool TryParseRequiredReferenceFloat(JObject entry, string key, out float value)
	{
		value = 0f;
		var token = entry?[key];
		if (token == null)
		{
			return false;
		}

		return Homm3JsonNumber.TryParseFloat(
			token.ToString(),
			out value);
	}

	private static IReadOnlyDictionary<string, Dictionary<int, string>> GetBuildingLayerLevels(string fraction, bool requireValidMetadata = false)
	{
		var layerRoot = ResolveTownLayerRootRelativePath(fraction);
		if (layerRoot == null)
		{
			return new Dictionary<string, Dictionary<int, string>>(StringComparer.OrdinalIgnoreCase);
		}

		var jsonRelPath = Path.Combine(layerRoot, BuildingLayerMapFileName);
		var jsonPath = ResolveExistingPath(jsonRelPath, logMissing: false);
		var stamp = jsonPath != null ? GetTextureStamp(jsonPath) : null;
		if (!requireValidMetadata
			&& _buildingLayerLevelsCacheByRoot.TryGetValue(layerRoot, out var cached)
			&& _buildingLayerIdsStampByRoot.TryGetValue(layerRoot, out var cachedStamp)
			&& string.Equals(cachedStamp, stamp, StringComparison.Ordinal))
		{
			return cached;
		}

		GetBuildingLayerIds(fraction, requireValidMetadata);
		return _buildingLayerLevelsCacheByRoot.TryGetValue(layerRoot, out var parsed)
			? parsed
			: new Dictionary<string, Dictionary<int, string>>(StringComparer.OrdinalIgnoreCase);
	}

	private static IReadOnlyDictionary<string, string> GetBuildingLayerIds(string fraction, bool requireValidMetadata = false)
	{
		var layerRoot = ResolveTownLayerRootRelativePath(fraction);
		if (layerRoot == null)
		{
			return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
		}

		var jsonRelPath = Path.Combine(layerRoot, BuildingLayerMapFileName);
		var jsonPath = ResolveExistingPath(jsonRelPath, logMissing: false);
		var stamp = jsonPath != null ? GetTextureStamp(jsonPath) : null;
		if (!requireValidMetadata
			&& _buildingLayerIdsCacheByRoot.TryGetValue(layerRoot, out var cached)
			&& _buildingLayerIdsStampByRoot.TryGetValue(layerRoot, out var cachedStamp)
			&& string.Equals(cachedStamp, stamp, StringComparison.Ordinal))
		{
			return cached;
		}

		var parsed = ParseBuildingLayerIds(jsonPath, GetDefaultBuildingLayerIds(fraction), requireValidMetadata);
		var parsedLevels = ParseBuildingLayerLevels(jsonPath, requireValidMetadata);
		_buildingLayerIdsStampByRoot[layerRoot] = stamp;
		_buildingLayerIdsCacheByRoot[layerRoot] = parsed;
		_buildingLayerLevelsCacheByRoot[layerRoot] = parsedLevels;
		return parsed;
	}

	private static Dictionary<string, string> ParseBuildingLayerIds(
		string jsonPath,
		IReadOnlyDictionary<string, string> defaultLayerIds,
		bool requireValidMetadata = false)
	{
		var result = new Dictionary<string, string>(defaultLayerIds ?? StrongholdBuildingLayerIds, StringComparer.OrdinalIgnoreCase);
		if (jsonPath == null || !File.Exists(jsonPath))
		{
			if (requireValidMetadata)
				throw new InvalidOperationException("required " + BuildingLayerMapFileName + " is missing at " + (jsonPath ?? "(null)") + ".");
			return result;
		}

		try
		{
			var jroot = JObject.Parse(File.ReadAllText(jsonPath));
			var mapToken = jroot["buildingLayerIds"] ?? jroot["map"];
			if (mapToken == null)
			{
				if (requireValidMetadata)
					throw new InvalidOperationException(BuildingLayerMapFileName + " has no buildingLayerIds object at " + jsonPath + ".");
				Plugin.LogSource?.LogWarning("HoMM3 Stronghold town layers: " + BuildingLayerMapFileName + " has no buildingLayerIds object.");
				return result;
			}

			var map = mapToken as JObject ?? JObject.Parse(mapToken.ToString());
			var mapJson = map.ToString(Newtonsoft.Json.Formatting.None);
			var matches = System.Text.RegularExpressions.Regex.Matches(
				mapJson,
				"\"(?<key>[^\"\\\\]*(?:\\\\.[^\"\\\\]*)*)\"\\s*:\\s*\"(?<value>[^\"\\\\]*(?:\\\\.[^\"\\\\]*)*)\"");
			if (requireValidMetadata && (map.Count == 0 || matches.Count != map.Count))
				throw new InvalidOperationException(BuildingLayerMapFileName + " buildingLayerIds contains no mappings or unsupported entries at " + jsonPath + ".");
			for (var i = 0; i < matches.Count; i++)
			{
				var match = matches[i];
				var buildingSid = match.Groups["key"].Value;
				var layerId = match.Groups["value"].Value;
				if (string.IsNullOrWhiteSpace(buildingSid) || string.IsNullOrWhiteSpace(layerId))
				{
					if (requireValidMetadata)
						throw new InvalidOperationException(BuildingLayerMapFileName + " contains an empty building or layer id at " + jsonPath + ".");
					continue;
				}

				result[buildingSid] = layerId;
			}

			Plugin.LogSource?.LogInfo(
				"HoMM3 Stronghold town layers: loaded " + result.Count + " building-layer mappings from " + BuildingLayerMapFileName);
		}
		catch (Exception ex)
		{
			if (requireValidMetadata)
				throw new InvalidOperationException("required " + BuildingLayerMapFileName + " metadata is invalid at " + jsonPath + ": " + ex.Message, ex);
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town layers: failed to parse " + BuildingLayerMapFileName + ": " + ex.Message);
		}

		return result;
	}

	private static Dictionary<string, Dictionary<int, string>> ParseBuildingLayerLevels(string jsonPath, bool requireValidMetadata = false)
	{
		var result = new Dictionary<string, Dictionary<int, string>>(StringComparer.OrdinalIgnoreCase);
		if (jsonPath == null || !File.Exists(jsonPath))
		{
			if (requireValidMetadata)
				throw new InvalidOperationException("required " + BuildingLayerMapFileName + " is missing at " + (jsonPath ?? "(null)") + ".");
			return result;
		}

		try
		{
			var jroot = JObject.Parse(File.ReadAllText(jsonPath));
			// This map feeds the legacy dynamic layer resolver; nativeLevels belongs to the owned city scene join.
			var levelsToken = jroot["levels"];
			if (levelsToken == null)
			{
				return result;
			}

			var levels = levelsToken.TryCast<JObject>();
			if (levels == null)
			{
				if (requireValidMetadata)
					throw new InvalidOperationException(BuildingLayerMapFileName + " levels must be a JSON object at " + jsonPath + ".");
				levels = JObject.Parse(levelsToken.ToString());
			}
			if (requireValidMetadata)
			{
				if (levels.Count == 0)
					throw new InvalidOperationException(BuildingLayerMapFileName + " levels object is empty at " + jsonPath + ".");
				var buildingEnumerator = GetJsonPropertyEnumerator(levels.Properties());
				while (buildingEnumerator.MoveNext())
				{
					var building = buildingEnumerator.Current?.TryCast<JProperty>();
					var buildingLevels = building?.Value?.TryCast<JObject>();
					if (building == null || string.IsNullOrWhiteSpace(building.Name) || buildingLevels == null)
						throw new InvalidOperationException(BuildingLayerMapFileName + " has an invalid per-level mapping for " + (building?.Name ?? "(null)") + " at " + jsonPath + ".");

					var parsedLevels = new Dictionary<int, string>();
					var levelEnumerator = GetJsonPropertyEnumerator(buildingLevels.Properties());
					while (levelEnumerator.MoveNext())
					{
						var level = levelEnumerator.Current?.TryCast<JProperty>();
						if (level == null)
							throw new InvalidOperationException(BuildingLayerMapFileName + " has an invalid per-level mapping for " + building.Name + " at " + jsonPath + ".");
						if (!int.TryParse(level.Name, out var parsedLevel) || parsedLevel <= 0
						    || level.Value == null
						    || level.Value.Type != JTokenType.String
						    || string.IsNullOrWhiteSpace(level.Value.ToString()))
							throw new InvalidOperationException(BuildingLayerMapFileName + " has an invalid layer id for " + building.Name + " level " + level.Name + " at " + jsonPath + ".");

						parsedLevels[parsedLevel] = level.Value.ToString();
					}
					if (parsedLevels.Count == 0)
						throw new InvalidOperationException(BuildingLayerMapFileName + " has no levels for " + building.Name + " at " + jsonPath + ".");
					result[building.Name] = parsedLevels;
				}
				return result;
			}

			var levelsJson = levels.ToString(Newtonsoft.Json.Formatting.None);
			var buildingMatches = System.Text.RegularExpressions.Regex.Matches(
				levelsJson,
				"\"(?<building>[^\"\\\\]*(?:\\\\.[^\"\\\\]*)*)\"\\s*:\\s*\\{(?<levels>[^{}]*)\\}");
			for (var i = 0; i < buildingMatches.Count; i++)
			{
				var buildingSid = buildingMatches[i].Groups["building"].Value;
				if (string.IsNullOrEmpty(buildingSid))
				{
					continue;
				}

				var map = new Dictionary<int, string>();
				var levelMatches = System.Text.RegularExpressions.Regex.Matches(
					buildingMatches[i].Groups["levels"].Value,
					"\"(?<level>\\d+)\"\\s*:\\s*\"(?<layer>[^\"\\\\]*(?:\\\\.[^\"\\\\]*)*)\"");
				for (var levelIndex = 0; levelIndex < levelMatches.Count; levelIndex++)
				{
					if (!int.TryParse(levelMatches[levelIndex].Groups["level"].Value, out var level) || level <= 0)
					{
						continue;
					}

					var layerId = levelMatches[levelIndex].Groups["layer"].Value;
					if (string.IsNullOrEmpty(layerId))
					{
						continue;
					}

					map[level] = layerId;
				}

				if (map.Count > 0)
				{
					result[buildingSid] = map;
				}
			}

			if (result.Count > 0)
			{
				Plugin.LogSource?.LogInfo(
					"HoMM3 Stronghold town layers: loaded " + result.Count + " per-level building-layer mappings from " + BuildingLayerMapFileName);
			}
		}
		catch (Exception ex)
		{
			if (requireValidMetadata)
				throw new InvalidOperationException("required " + BuildingLayerMapFileName + " per-level metadata is invalid at " + jsonPath + ": " + ex.Message, ex);
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town layers: failed to parse per-level mappings from " + BuildingLayerMapFileName + ": " + ex.Message);
		}

		return result;
	}

	private static Il2CppSystem.Collections.IEnumerator GetJsonPropertyEnumerator(
		Il2CppSystem.Collections.Generic.IEnumerable<JProperty> properties)
	{
		if (properties == null)
			throw new InvalidOperationException("required JSON property sequence is null.");

		var enumerator = properties.Cast<Il2CppSystem.Collections.IEnumerable>().GetEnumerator();
		if (enumerator == null)
			throw new InvalidOperationException("required JSON property sequence has no enumerator.");
		return enumerator;
	}

	private static readonly IReadOnlyDictionary<string, string> StrongholdBuildingLayerIds = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
	{
		["Build_Tier_1"] = "dwellingUp2Lvl1",
		["Build_Tier_2"] = "dwellingUp2Lvl2",
		["Build_Tier_3"] = "dwellingUp2Lvl3",
		["Build_Tier_4"] = "dwellingUp2Lvl4",
		["Build_Tier_5"] = "dwellingUp2Lvl5",
		["Build_Tier_6"] = "dwellingUp2Lvl6",
		["Build_Tier_7"] = "dwellingUp2Lvl7",
		["Build_Main"] = "extraCapitol",
		["Build_Tavern"] = "tavern",
		["Build_Market"] = "market",
		["Build_Artifact_Market"] = "artifactMarket",
		["Build_Magic_Guild"] = "magicGuild",
		["Build_Bank"] = "odu",
		["Build_Treasury"] = "artifactMarket",
		["Build_Resource_Depot"] = "resourceDepot",
		["Build_Resource_Depot_level_2"] = "resourceDepot",
		["Build_Wall"] = "wall",
		["Build_Gymnasium"] = "spyNetwork",
		["Build_Lyceum"] = "horde1",
		["Build_Spy_Network"] = "lyceum",
	};

	private static readonly IReadOnlyDictionary<string, string> TowerBuildingLayerIds = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
	{
		["Build_Tier_1"] = "tbtwdw_0",
		["Build_Tier_2"] = "tbtwdw_1",
		["Build_Tier_3"] = "tbtwdw_2",
		["Build_Tier_4"] = "tbtwdw_3",
		["Build_Tier_5"] = "tbtwdw_4",
		["Build_Tier_6"] = "tbtwdw_5",
		["Build_Tier_7"] = "tbtwdw_6",
		["Build_Main"] = "tbtwhall",
		["Build_Wall"] = "tbtwcstl",
		["Build_Tavern"] = "tbtwtvrn",
		["Build_Market"] = "tbtwmark",
		["Build_Artifact_Market"] = "tbtwspec",
		["Build_Magic_Guild"] = "tbtwmage",
		["Build_Bank"] = "tbtwhall_4",
		["Build_Treasury"] = "tbtwblak",
		["Build_Resource_Depot"] = "tbtwsilo",
		["Build_Resource_Depot_level_2"] = "tbtwext2",
		["Build_Training_Range"] = "tbtwext0",
		["Build_Intelligence_Academy"] = "tbtwext1",
		["Build_Golden_Calf"] = "tbtwholy",
	};

	private static IReadOnlyDictionary<string, string> GetDefaultBuildingLayerIds(string fraction)
	{
		if (string.Equals(fraction, TowerFolderName, StringComparison.OrdinalIgnoreCase))
			return TowerBuildingLayerIds;
		if (string.Equals(fraction, StrongholdFolderName, StringComparison.OrdinalIgnoreCase))
			return StrongholdBuildingLayerIds;
		return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
	}
	private static readonly HashSet<string> LoggedMissingAssets = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
	private static readonly HashSet<string> LoggedEmptyState = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

	private static RectTransform _root;
	private static bool _rootFromPrefab;
	private static string _rootPrefabFraction;
	private static int _rootCreatedFrame;
	private static int _lastUnchangedSyncFrame = -1;
	private static int _lastSyncFrame = -1;
	private static AssetBundle _townPrefabBundle;
	private static string _townPrefabBundlePath;
	private static readonly Dictionary<string, GameObject> TownPrefabCache = new Dictionary<string, GameObject>(StringComparer.OrdinalIgnoreCase);
	private static readonly HashSet<string> LoggedPrefabUnavailable = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
	private static readonly List<PendingAnimAttachment> PendingPrefabAnimations = new List<PendingAnimAttachment>();
	private static readonly Dictionary<string, ObservedTownBuildingState> ObservedBuildingDataByTownKey = new Dictionary<string, ObservedTownBuildingState>(StringComparer.OrdinalIgnoreCase);
	private static readonly HashSet<string> LoggedObservedTownKeyFallbacks = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
	private static bool? _townPrefabsEnabled;
	private static RectTransform _cachedCityPanelRoot;
	private static int _cachedCityPanelSceneHandle;
	private static string _cachedCityPanelSceneName;
	private static string _lastSignature;
	private static string _lastAppliedLayerTransformSignature;
	private static string _diagFiredFraction;
	private static bool _hasSeenVisibleLayerState;
	private static HashSet<string> _knownVisibleLayerKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
	private static bool _loggedLayerTransformBasis;
	private static readonly Dictionary<Renderer, bool> SuppressedDonorCityRenderers = new Dictionary<Renderer, bool>();
	private static int _donorSuppressSceneHandle = -1;
	private static bool _deferredSyncQueued;
	private static int _deferredSyncAttempts;
	private static int _loggedObservedBuildingData;

	internal static void RememberObservedBuildingData(string fraction, object townContext, BuildingData data, string source)
	{
		try
		{
			if (data == null)
				return;
			var townKey = BuildObservedTownKey(fraction, townContext);
			if (townKey == null)
				return;
			if (!TryGetBuildingSid(data, out var sid))
				return;
			var level = Math.Max(1, GetBuildingLevel(data));
			var key = sid + ":" + level;
			if (!ObservedBuildingDataByTownKey.TryGetValue(townKey, out var state))
			{
				state = new ObservedTownBuildingState();
				ObservedBuildingDataByTownKey[townKey] = state;
			}
			if (IsSupportedTownFraction(fraction))
				state.Fraction = fraction;
			var isNew = !state.Buildings.ContainsKey(key);
			state.Buildings[key] = data;
			_lastSignature = null;
			if (isNew && _loggedObservedBuildingData < 40 && Homm3DiagnosticFlags.IsEnabled("homm3_town_layers_diag.flag"))
			{
				_loggedObservedBuildingData++;
				Plugin.LogSource?.LogInfo(
					"HoMM3 town layers: observed building data"
					+ " townKey='" + townKey + "'"
					+ " fraction='" + (fraction ?? "") + "'"
					+ " sid='" + sid + "'"
					+ " level=" + level
					+ " constructed=" + IsBuildingConstructed(data)
					+ " source=" + (source ?? "null")
					+ ".");
			}
			ScheduleDeferredSync();
		}
		catch (Exception ex)
		{
			if (_loggedObservedBuildingData < 40)
			{
				_loggedObservedBuildingData++;
				Plugin.LogSource?.LogWarning("HoMM3 town layers: observe building data failed: " + ex.Message);
			}
		}
	}

	internal static void ClearObservedBuildingData()
	{
		ObservedBuildingDataByTownKey.Clear();
		_lastSignature = null;
		_loggedObservedBuildingData = 0;
	}

	/// <summary>
	/// Constructed BuildingData SIDs/levels for owned cityFactory world art activation.
	/// Prefer live ObjCity; fall back to observed build-tree captures when city is briefly null.
	/// </summary>
	private static string BuildObservedTownKey(string fraction, object townContext)
	{
		try
		{
			var currentWrapper = ModActions.GetCurrentCityWrapper();
			if (currentWrapper != null)
				return "wrapper:" + RuntimeHelpers.GetHashCode(currentWrapper);
			if (!IsSupportedTownFraction(fraction))
				return null;
			var scope = ModActions.GetCurrentCityPresentationScopeKey();
			if (!string.IsNullOrWhiteSpace(scope))
			{
				if (Homm3DiagnosticFlags.IsEnabled("homm3_town_layers_diag.flag")
				    && LoggedObservedTownKeyFallbacks.Add(fraction + "|" + scope))
				{
					Plugin.LogSource?.LogInfo(
						"HoMM3 town layers: using presentation-scope building cache"
						+ " fraction='" + (fraction ?? "") + "'"
						+ " scope='" + scope + "'.");
				}
				return "presentation:" + fraction + ":" + scope;
			}

			var context = townContext;
			if (context != null)
				return "wrapper:" + RuntimeHelpers.GetHashCode(context);
			return null;
		}
		catch
		{
			return null;
		}
	}

	internal static void SyncCurrentCityLayers()
	{
		var stopwatch = Stopwatch.StartNew();
		var phase = Stopwatch.StartNew();
		long panelMs = 0;
		long fractionMs = 0;
		long musicMs = 0;
		long cityMs = 0;
		long buildingsMs = 0;
		long signatureMs = 0;
		long rootMs = 0;
		long updateMs = 0;
		long postMs = 0;
		LayerUpdateProfile updateProfile = null;
		try
		{
			// Many city hooks call Sync on the same frame; one pass is enough once a city panel exists.
			var frame = Time.frameCount;
			if (_lastSyncFrame == frame)
				return;

			var panelRoot = FindCityPanelRectTransform();
			panelMs = phase.ElapsedMilliseconds;
			phase.Restart();
			if (panelRoot == null)
			{
				return;
			}

			var scene = panelRoot.gameObject.scene;
			if (!scene.IsValid() || !IsCityInteriorSceneName(scene.name))
			{
				return;
			}

			_lastSyncFrame = frame;

			var fraction = ModActions.GetCurrentCityFraction();
			fractionMs = phase.ElapsedMilliseconds;
			phase.Restart();
			if (!IsSupportedTownFraction(fraction))
			{
				Homm3StrongholdCityMusic.StopTownMusic();
				ClearTownLayers();
				return;
			}

			// Factory cityFactory ownership: world art + native BhBuilding clicks only.
			// Do not fall through to CanvasCityPanel Route A layers or UI click relays.
			// Do not RestoreDonorCityRenderers here — Route A suppress is a no-op for owned city,
			// and EnsureOwnedCityPresentationActive already owns HideDonorPresentation.
			if (Homm3FactoryCitySceneRegistrar.OwnsActiveFactoryCityWorld(fraction))
			{
				Homm3FactoryCitySceneRegistrar.EnsureOwnedCityPresentationActive();
				ClearTownLayers();
				if (Homm3StrongholdCityMusic.HasTownMusicBundle(fraction))
					Homm3StrongholdCityMusic.EnsureTownMusicPlaying(fraction);
				return;
			}

			if (Homm3StrongholdCityMusic.HasTownMusicBundle(fraction))
				Homm3StrongholdCityMusic.EnsureTownMusicPlaying(fraction);
			musicMs = phase.ElapsedMilliseconds;
			phase.Restart();
			var city = TryGetCurrentCity();
			cityMs = phase.ElapsedMilliseconds;
			phase.Restart();
			if (Homm3DiagnosticFlags.IsEnabled("homm3_town_layers_diag.flag"))
				FireDiagnosticOnce(fraction, city);

			List<BuildingData> entries;
			if (city == null)
			{
				entries = GetObservedConstructedBuildings(fraction);
				if (entries.Count == 0)
				{
					ClearTownLayers();
					return;
				}
			}
			else
			{
				entries = GetConstructedBuildings(city);
				if (entries.Count == 0)
				{
					var observed = GetObservedConstructedBuildings(fraction);
					if (observed.Count > 0)
						entries = observed;
				}
			}

			_deferredSyncAttempts = 0;
			buildingsMs = phase.ElapsedMilliseconds;
			phase.Restart();
			var signature = BuildSignature(fraction, entries, panelRoot);
			signatureMs = phase.ElapsedMilliseconds;
			phase.Restart();

			// Unchanged-signature fast path applies to dynamic and prefab roots.
			// Prefab-only gating left this dead while SyncCurrentCityLayers used EnsureDynamicLayerRoot,
			// so town refresh postfixes re-ran full UpdateLayerImages (anim attach + donor suppress).
			if (_root != null && _root && string.Equals(_lastSignature, signature, StringComparison.Ordinal))
			{
				if (_lastUnchangedSyncFrame == frame)
				{
					return;
				}

				_lastUnchangedSyncFrame = frame;
				var transformSignature = ModActions.GetCityBackdropTransformSignature(panelRoot);
				if (!string.Equals(_lastAppliedLayerTransformSignature, transformSignature, StringComparison.Ordinal)
				    || _root.parent != panelRoot
				    || !_root.gameObject.activeSelf)
				{
					ApplyLayerRootTransform(_root, panelRoot);
					ApplyLayerSiblingIndex(_root, panelRoot);
					_lastAppliedLayerTransformSignature = transformSignature;
				}
				_root.gameObject.SetActive(true);
				if (_rootFromPrefab)
					AttachPendingPrefabAnimations();
				ReleaseSessionFadeWhenReady(fraction);
				postMs = phase.ElapsedMilliseconds;
				// Menu order is owned by Homm3TownUiCanvasLiftPump / panel-open hooks — not every sync.
				return;
			}

			var root = EnsureDynamicLayerRoot(panelRoot);
			ApplyLayerRootTransform(root, panelRoot);
			ApplyLayerSiblingIndex(root, panelRoot);
			_lastAppliedLayerTransformSignature = ModActions.GetCityBackdropTransformSignature(panelRoot);
			rootMs = phase.ElapsedMilliseconds;
			phase.Restart();
			updateProfile = UpdateLayerImages(root, fraction, entries);
			if (updateProfile != null && updateProfile.ActiveLayers > 0)
				SuppressDonorCityRenderersForCustomTown(panelRoot);
			updateMs = phase.ElapsedMilliseconds;
			phase.Restart();
			_lastSignature = signature;
			_lastUnchangedSyncFrame = -1;
			ReleaseSessionFadeWhenReady(fraction);
			postMs = phase.ElapsedMilliseconds;
			if (entries.Count == 0 && LoggedEmptyState.Add(fraction))
			{
				Plugin.LogSource?.LogInfo(
					"HoMM3 Stronghold town layers: synced empty building state for fraction '" + fraction + "'.");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("HoMM3 Stronghold town layers: sync failed: " + ex.Message);
			throw;
		}
		finally
		{
			stopwatch.Stop();
			if (stopwatch.ElapsedMilliseconds >= 100)
			{
				Plugin.LogSource?.LogInfo(
					"HoMM3 Stronghold town layers: sync took "
					+ stopwatch.ElapsedMilliseconds
					+ " ms (slow calls only)."
					+ " panel=" + panelMs
					+ " fraction=" + fractionMs
					+ " music=" + musicMs
					+ " city=" + cityMs
					+ " buildings=" + buildingsMs
					+ " signature=" + signatureMs
					+ " root=" + rootMs
					+ " update=" + updateMs
					+ " post=" + postMs
					+ FormatLayerUpdateProfile(updateProfile));
			}
		}
	}

	private static string FormatLayerUpdateProfile(LayerUpdateProfile profile)
	{
		if (profile == null)
			return "";

		return " updateDetail={buildings:" + profile.Buildings
			+ ",active:" + profile.ActiveLayers
			+ ",created:" + profile.CreatedImages
			+ ",prefab:" + (profile.UsedPrefab ? "true" : "false")
			+ ",resolve:" + profile.ResolveMs
			+ ",ensure:" + profile.EnsureImageMs
			+ ",texture:" + profile.TextureMs
			+ ",transform:" + profile.TransformMs
			+ ",anim:" + profile.AnimMs
			+ ",animPlayers:" + profile.AnimPlayers
			+ ",sort:" + profile.SortMs
			+ ",sibling:" + profile.SiblingMs
			+ ",hide:" + profile.HideMs
			+ ",effects:" + profile.EffectsMs
			+ ",effectFades:" + profile.EffectFades
			+ "}";
	}

	private static void ReleaseSessionFadeWhenReady(string fraction)
	{
		if (!IsSupportedTownFraction(fraction) || _root == null || !_root || !_root.gameObject.activeInHierarchy)
			return;
		if (!HasRenderableLayer(_root))
			return;

		var now = Time.unscaledTime;
		if (now - _lastSessionFadeReleaseAttempt < 0.05f)
			return;
		_lastSessionFadeReleaseAttempt = now;

		try
		{
			if (TryReleaseSessionFadeGraphic(fraction))
				return;
			var effects = Homm3StrongholdTownBuildEffects.TryAttach(_root.gameObject, Plugin.LogSource);
			effects?.BeginSessionFadeRelease(fraction);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom town layers: session fade release failed: " + ex.Message);
		}
	}

	internal static bool TryReleaseSessionFadeGraphic(string fraction)
	{
		var graphic = FindSessionFadeGraphic();
		if (!IsSessionFadeGraphic(graphic, requireActive: true))
			return false;
		var color = graphic.color;
		var changed = false;
		if (graphic.raycastTarget)
		{
			graphic.raycastTarget = false;
			changed = true;
		}
		if (color.a > 0.001f)
		{
			graphic.color = new Color(color.r, color.g, color.b, 0f);
			changed = true;
		}
		if (!changed)
			return true;
		if (!_loggedSessionFadeRelease)
		{
			_loggedSessionFadeRelease = true;
			Plugin.LogSource?.LogInfo(
				"HoMM3 custom town layers: released session fade visual/raycast blocker after custom town layers became renderable"
				+ " fraction='" + (fraction ?? "") + "'.");
		}
		return true;
	}

	private static void RestoreSessionFadeRaycastTarget()
	{
		try
		{
			var graphic = FindSessionFadeGraphic();
			if (!IsSessionFadeGraphic(graphic, requireActive: false))
				return;
			if (!graphic.raycastTarget)
				graphic.raycastTarget = true;
			if (!graphic.gameObject.activeInHierarchy)
			{
				var color = graphic.color;
				if (color.a < 0.999f)
					graphic.color = new Color(color.r, color.g, color.b, 1f);
			}
		}
		catch
		{
		}
	}

	private static Graphic FindSessionFadeGraphic()
	{
		var fadeScene = SceneManager.GetSceneByName("sessionFade");
		var fadeHandle = fadeScene.IsValid() ? fadeScene.handle : 0;
		if (_cachedSessionFadeGraphic != null
		    && _cachedSessionFadeGraphic
		    && _cachedSessionFadeSceneHandle == fadeHandle)
		{
			return _cachedSessionFadeGraphic;
		}

		GameObject canvasObject = null;
		if (fadeScene.IsValid() && fadeScene.isLoaded)
		{
			var roots = fadeScene.GetRootGameObjects();
			for (var i = 0; i < roots.Length; i++)
			{
				var root = roots[i];
				if (root != null && root && string.Equals(root.name ?? "", SessionFadeCanvasName, StringComparison.Ordinal))
				{
					canvasObject = root;
					break;
				}
			}
		}

		// Avoid GameObject.Find on the hot town-sync path — it walked the whole hierarchy (~200ms).
		if (canvasObject == null || !canvasObject)
		{
			_cachedSessionFadeGraphic = null;
			_cachedSessionFadeSceneHandle = fadeHandle;
			return null;
		}

		var imageTransform = canvasObject.transform.Find(SessionFadeImageName);
		_cachedSessionFadeGraphic = imageTransform != null ? imageTransform.GetComponent<Graphic>() : null;
		_cachedSessionFadeSceneHandle = fadeHandle;
		return _cachedSessionFadeGraphic;
	}


	private static void SuppressDonorCityRenderersForCustomTown(RectTransform panelRoot)
	{
		var fraction = ModActions.GetCurrentCityFraction();
		if (Homm3FactoryCitySceneRegistrar.OwnsActiveFactoryCityWorld(fraction))
			return;

		var scene = SceneManager.GetActiveScene();
		if (!scene.IsValid() || !IsCityInteriorSceneName(scene.name))
			return;

		// Full scene GetComponentsInChildren over hundreds of donor renderers is expensive.
		// Once suppressed for this city-interior scene instance, do not rescan unless cleared.
		if (_donorSuppressSceneHandle == scene.handle && SuppressedDonorCityRenderers.Count > 0)
			return;

		try
		{
			var roots = scene.GetRootGameObjects();
			var suppressed = 0;
			for (var i = 0; i < roots.Length; i++)
			{
				var root = roots[i];
				if (root == null || IsTownUiOrCustomArtRoot(root, panelRoot))
					continue;

				var renderers = root.GetComponentsInChildren<Renderer>(true);
				for (var j = 0; j < renderers.Length; j++)
				{
					var renderer = renderers[j];
					if (renderer == null || IsRendererUnderTownUiOrCustomArt(renderer, panelRoot))
						continue;
					if (!SuppressedDonorCityRenderers.ContainsKey(renderer))
						SuppressedDonorCityRenderers[renderer] = renderer.enabled;
					if (renderer.enabled)
					{
						renderer.enabled = false;
						suppressed++;
					}
				}
			}

			_donorSuppressSceneHandle = scene.handle;
			if (suppressed > 0)
				Plugin.LogSource?.LogInfo("HoMM3 town layers: suppressed " + suppressed + " donor city renderer(s) behind custom town art.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 town layers: donor city renderer suppression failed: " + ex.Message);
			throw;
		}
	}

	private static void RestoreDonorCityRenderers()
	{
		if (SuppressedDonorCityRenderers.Count == 0)
		{
			_donorSuppressSceneHandle = -1;
			return;
		}

		foreach (var pair in SuppressedDonorCityRenderers.ToArray())
		{
			var renderer = pair.Key;
			if (renderer != null)
				renderer.enabled = pair.Value;
		}
		SuppressedDonorCityRenderers.Clear();
		_donorSuppressSceneHandle = -1;
	}

	private static bool IsTownUiOrCustomArtRoot(GameObject root, RectTransform panelRoot)
	{
		if (root == null)
			return true;
		if (panelRoot != null && root == panelRoot.gameObject)
			return true;
		var name = root.name ?? "";
		return string.Equals(name, "CanvasCityPanel", StringComparison.Ordinal)
		       || string.Equals(name, "Canvas", StringComparison.Ordinal)
		       || string.Equals(name, "EventSystem", StringComparison.Ordinal)
		       || string.Equals(name, SessionFadeCanvasName, StringComparison.Ordinal)
		       || string.Equals(name, "OfflineUnlockFactoryWorldBackdrop", StringComparison.Ordinal)
		       || string.Equals(name, LayerRootName, StringComparison.Ordinal)
		       || string.Equals(name, "Homm3LiveProbeWorkbenchBridge", StringComparison.Ordinal);
	}

	private static bool IsRendererUnderTownUiOrCustomArt(Renderer renderer, RectTransform panelRoot)
	{
		var transform = renderer != null ? renderer.transform : null;
		var depth = 0;
		while (transform != null && depth < 64)
		{
			if (panelRoot != null && transform == panelRoot)
				return true;
			var name = transform.name ?? "";
			if (string.Equals(name, LayerRootName, StringComparison.Ordinal)
			    || string.Equals(name, BackdropObjectName, StringComparison.Ordinal)
			    || string.Equals(name, "CanvasCityPanel", StringComparison.Ordinal)
			    || string.Equals(name, SessionFadeCanvasName, StringComparison.Ordinal))
			{
				return true;
			}
			transform = transform.parent;
			depth++;
		}
		return false;
	}

	private static bool HasRenderableLayer(RectTransform root)
	{
		try
		{
			var images = root.GetComponentsInChildren<RawImage>(true);
			for (var i = 0; i < images.Length; i++)
			{
				var image = images[i];
				if (image == null || !image || !image.enabled || image.gameObject == null || !image.gameObject.activeInHierarchy)
					continue;
				var texture = image.texture;
				if (texture != null && texture && texture.width > 0 && texture.height > 0)
					return true;
			}
		}
		catch
		{
		}
		return false;
	}

	private static bool IsSessionFadeGraphic(Graphic graphic, bool requireActive)
	{
		if (graphic == null || !graphic || graphic.gameObject == null || !graphic.enabled)
			return false;
		if (requireActive && !graphic.gameObject.activeInHierarchy)
			return false;
		var scene = graphic.gameObject.scene;
		if (!scene.IsValid() || !string.Equals(scene.name ?? "", "sessionFade", StringComparison.Ordinal))
			return false;
		var parent = graphic.transform != null ? graphic.transform.parent : null;
		return parent != null
		       && string.Equals(parent.name ?? "", SessionFadeCanvasName, StringComparison.Ordinal)
		       && string.Equals(graphic.gameObject.name ?? "", SessionFadeImageName, StringComparison.Ordinal);
	}

	private static string UnityPath(Transform transform)
	{
		if (transform == null)
			return "";
		var parts = new List<string>();
		var cursor = transform;
		var depth = 0;
		while (cursor != null && depth < 32)
		{
			parts.Add(cursor.name ?? "");
			cursor = cursor.parent;
			depth++;
		}
		parts.Reverse();
		return string.Join("/", parts);
	}

	private static void DisableLegacyTownBackdropObjects(RectTransform panelRoot)
	{
		try
		{
			if (panelRoot != null)
			{
				var legacyBackdropIndex = FindChildIndex(panelRoot, BackdropObjectName);
				if (legacyBackdropIndex >= 0)
					panelRoot.GetChild(legacyBackdropIndex).gameObject.SetActive(false);
			}

			// Scene-scoped walk only — FindObjectsOfType<GameObject>(true) scanned the whole
			// runtime heap every sync and was a town-entry hitch source.
			var scene = panelRoot != null && panelRoot.gameObject != null
				? panelRoot.gameObject.scene
				: SceneManager.GetActiveScene();
			if (!scene.IsValid() || !string.Equals(scene.name ?? "", "CityUI", StringComparison.Ordinal))
				return;

			var roots = scene.GetRootGameObjects();
			for (var i = 0; i < roots.Length; i++)
			{
				var root = roots[i];
				if (root == null || !root)
					continue;
				DisableLegacyTownBackdropUnder(root.transform);
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom city scene: disabling legacy backdrop failed: " + ex.Message);
		}
	}

	private static void DisableLegacyTownBackdropUnder(Transform current)
	{
		if (current == null)
			return;
		if (string.Equals(current.name ?? "", BackdropObjectName, StringComparison.Ordinal))
		{
			var path = UnityPath(current);
			if (string.Equals(path, "OfflineUnlockCustomTownArtRoot/" + BackdropObjectName, StringComparison.Ordinal)
			    || path.EndsWith("/" + BackdropObjectName, StringComparison.Ordinal))
			{
				current.gameObject.SetActive(false);
			}
		}

		for (var i = 0; i < current.childCount; i++)
			DisableLegacyTownBackdropUnder(current.GetChild(i));
	}
	internal static void ClearTownLayers()
	{
		try
		{
			RestoreSessionFadeRaycastTarget();
			RestoreDonorCityRenderers();
			_loggedSessionFadeRelease = false;
			_cachedSessionFadeGraphic = null;
			_cachedSessionFadeSceneHandle = -1;
			if (_root != null)
			{
				_root.gameObject.SetActive(false);
			}
			_lastSignature = null;
			_lastAppliedLayerTransformSignature = null;
			_lastSyncFrame = -1;
			_diagFiredFraction = null;
			_hasSeenVisibleLayerState = false;
			_knownVisibleLayerKeys.Clear();
			ModActions.ClearCustomTownUiAboveArtGate();
			if (!TryKeepTownMusicPlayingForCurrentTown())
			{
				_deferredSyncAttempts = 0;
				Homm3StrongholdCityMusic.StopTownMusic();
			}
			else
			{
				ScheduleDeferredSync();
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town layers: clear failed: " + ex.Message);
		}
	}

	internal static int PrewarmFactionAssets(string fraction)
	{
		return PrewarmFactionAssets(fraction, out _, out _, out _, out _);
	}

	internal static int ValidateFactionAssetSourcesOrFail(string fraction)
	{
		if (!IsSupportedTownFraction(fraction))
			throw new InvalidOperationException("unsupported HoMM3 town fraction " + (fraction ?? "(null)") + ".");

		var layerRoot = ResolveTownLayerRootRelativePath(fraction);
		if (layerRoot == null)
			throw new InvalidOperationException("town layer root is unresolved for " + fraction + ".");

		var positionsPath = ResolveExistingPath(Path.Combine(layerRoot, "positions.json"), logMissing: false);
		if (positionsPath == null)
			throw new InvalidOperationException("required town layer positions.json is missing for " + fraction + ".");

		var buildingMapPath = ResolveExistingPath(Path.Combine(layerRoot, BuildingLayerMapFileName), logMissing: false);
		if (buildingMapPath == null)
			throw new InvalidOperationException("required town building layer map is missing for " + fraction + ".");

		var placements = GetLayerPlacements(fraction, requireValidMetadata: true);
		if (placements == null || placements.Count == 0)
			throw new InvalidOperationException("town positions metadata has no usable placements for " + fraction + ".");

		// Reuse the runtime parsers so validation and first-use rendering resolve the same metadata.
		var buildingLayerIds = GetBuildingLayerIds(fraction, requireValidMetadata: true);
		GetBuildingLayerLevels(fraction);
		if (buildingLayerIds == null || buildingLayerIds.Count == 0)
			throw new InvalidOperationException("town building layer map has no usable ids for " + fraction + ".");

		var missingSources = new List<string>();
		var checkedSources = 0;
		foreach (var pair in placements)
		{
			var placement = pair.Value;
			if (placement == null)
			{
				missingSources.Add(pair.Key + " has no parsed placement");
				continue;
			}
			if (placement.Hidden)
				continue;

			if (string.IsNullOrWhiteSpace(placement.Sprite))
			{
				missingSources.Add(pair.Key + " has no sprite declaration");
				continue;
			}

			var relativePath = Path.Combine(layerRoot, placement.Sprite);
			if (ResolveExistingPath(relativePath, logMissing: false) == null)
				missingSources.Add(pair.Key + " -> " + relativePath);
			else
				checkedSources++;
		}

		if (missingSources.Count > 0)
		{
			var summary = string.Join(", ", missingSources.Take(12));
			if (missingSources.Count > 12)
				summary += ", ... (" + (missingSources.Count - 12) + " more)";
			throw new InvalidOperationException("required town layer sources are missing for " + fraction + ": " + summary + ".");
		}

		return checkedSources;
	}

	internal static int PrewarmFactionAssets(
		string fraction,
		out int animationFrames,
		out int animatedEntries,
		out int failedAnimationEntries,
		out bool prefabAssetLoaded)
	{
		animationFrames = 0;
		animatedEntries = 0;
		failedAnimationEntries = 0;
		prefabAssetLoaded = false;
		if (!IsSupportedTownFraction(fraction))
			return 0;

		var stopwatch = Stopwatch.StartNew();
		var staticLayerTextures = 0;
		try
		{
			GetLayerPlacements(fraction);
			GetBuildingLayerIds(fraction);
			GetBuildingLayerLevels(fraction);
			staticLayerTextures = PrewarmFactionLayerTextures(fraction);
			animationFrames = Homm3StrongholdTownAnimPlayer.PrewarmFactionAnimations(
				fraction,
				out animatedEntries,
				out failedAnimationEntries);
			prefabAssetLoaded = TryPrewarmTownPrefabAsset(fraction);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town layers: prewarm failed for " + fraction + ": " + ex.Message);
			throw;
		}
		finally
		{
			stopwatch.Stop();
			Plugin.LogSource?.LogInfo(
				"HoMM3 town presentation prewarm detail: fraction="
				+ fraction
				+ ", staticLayerTextures="
				+ staticLayerTextures
				+ ", animationFrames="
				+ animationFrames
				+ ", animatedEntries="
				+ animatedEntries
				+ ", failedAnimationEntries="
				+ failedAnimationEntries
				+ ", prefabAssetLoaded="
				+ (prefabAssetLoaded ? "true" : "false")
				+ ", elapsedMs="
				+ stopwatch.ElapsedMilliseconds
				+ ".");
		}

		return staticLayerTextures + animationFrames + (prefabAssetLoaded ? 1 : 0);
	}

	private static int PrewarmFactionLayerTextures(string fraction)
	{
		var placements = GetLayerPlacements(fraction);
		if (placements == null || placements.Count == 0)
			return 0;

		var loaded = 0;
		foreach (var pair in placements)
		{
			var placement = pair.Value;
			if (placement == null || placement.Hidden || string.IsNullOrWhiteSpace(placement.Sprite))
				continue;
			if (LoadTownLayerTexture(fraction, pair.Key, placement) != null)
				loaded++;
		}

		return loaded;
	}

	private static void ScheduleDeferredSync()
	{
		if (_deferredSyncQueued || _deferredSyncAttempts >= 30)
		{
			return;
		}

		_deferredSyncQueued = true;
		_deferredSyncAttempts++;
		Homm3PreviewApplyNextFrame.QueueOrRun(Plugin.LogSource, () =>
		{
			_deferredSyncQueued = false;
			SyncCurrentCityLayers();
		});
	}

	private static bool TryKeepTownMusicPlayingForCurrentTown()
	{
		try
		{
			var fraction = ModActions.GetCurrentCityFraction();
			if (!IsSupportedTownFraction(fraction) || !Homm3StrongholdCityMusic.HasTownMusicBundle(fraction))
			{
				return false;
			}

			var panelRoot = FindCityPanelRectTransform();
			if (panelRoot == null)
			{
				return false;
			}

			var scene = panelRoot.gameObject.scene;
			if (!scene.IsValid() || !IsCityInteriorSceneName(scene.name))
				return false;

			// Town music depends only on the proven current custom-town identity and live city panel,
			// not on building-layer reconstruction or cached wrapper availability.
			Homm3StrongholdCityMusic.EnsureTownMusicPlaying(fraction);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static void FireDiagnosticOnce(string fraction, ObjCity city)
	{
		if (string.Equals(_diagFiredFraction, fraction, StringComparison.Ordinal))
		{
			return;
		}

		_diagFiredFraction = fraction;
		var sb = new System.Text.StringBuilder();
		sb.Append("TownLayers diagnostic for fraction '").Append(fraction).Append("':");

		// --- city session path ---
		var sessionType = ModActions.GetHexType("Hex.UI.City.BhCityUISession");
		sb.Append("\n  BhCityUISession type: ").Append(sessionType?.FullName ?? "NOT FOUND");

		var wrapper = ModActions.GetCurrentCityWrapper();
		sb.Append("\n  city wrapper: ").Append(wrapper == null ? "null" : wrapper.GetType().FullName);
		if (wrapper != null)
		{
			var props = wrapper.GetType()
				.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
				.Select(p => p.Name).Take(20);
			sb.Append("\n  city wrapper fields: ").Append(string.Join(", ", props));
		}

		sb.Append("\n  ObjCity resolved: ").Append(city == null ? "null" : "ok");

		// --- building list probe ---
		if (city != null && city.buildings != null)
		{
			sb.Append("\n  buildings type: ").Append(city.buildings.GetType().FullName);
			var bProps = city.buildings.GetType()
				.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
				.Select(p => p.Name).Take(20);
			sb.Append("\n  buildings props: ").Append(string.Join(", ", bProps));

			var fieldListWorked = false;
			foreach (var candidate in GameSymbols.ReleaseTownUi.BuildingDataListMembers)
			{
				var val = GetMemberValue(city.buildings, candidate);
				sb.Append("\n  buildings.").Append(candidate).Append(": ")
					.Append(val == null ? "null" : val.GetType().FullName);
				if (EnumerateBuildingData(val).Count > 0)
					fieldListWorked = true;
			}

			// Exact list accessors proven on Hex.Session.Data.BuildingsData; probe only when fields are not enough.
			foreach (var method in fieldListWorked ? Array.Empty<string>() : GameSymbols.ReleaseTownUi.BuildingDataListMethods)
			{
				var listObj = GetExactNoArgMethodValue(city.buildings, method);
				var buildingData = EnumerateBuildingData(listObj);
				if (buildingData.Count == 0)
				{
					sb.Append("\n  ").Append(method).Append(": empty/cast failed, type=")
						.Append(listObj?.GetType().FullName ?? "null");
					continue;
				}

				var sids = new List<string>();
				for (var i = 0; i < buildingData.Count; i++)
				{
					var bd = buildingData[i];
					if (bd != null && TryGetBuildingSid(bd, out var sid))
					{
						sids.Add($"{sid}(lvl={GetBuildingLevel(bd)},built={IsBuildingConstructed(bd)})");
					}
				}
				sb.Append("\n  ").Append(method).Append(" (").Append(sids.Count).Append("): ")
					.Append(sids.Count == 0 ? "EMPTY" : string.Join(", ", sids));
			}

			// Named categories - show type and count even if cast fails
			foreach (var cat in BuildingCategories)
			{
				var catObj = GetMemberValue(city.buildings, cat);
				if (catObj == null)
				{
					continue;
				}

				var buildingData = EnumerateBuildingData(catObj);
				if (buildingData.Count == 0)
				{
					sb.Append("\n  ").Append(cat).Append(": empty/cast failed, type=")
						.Append(catObj.GetType().FullName);
					continue;
				}

				var sids = new List<string>();
				for (var i = 0; i < buildingData.Count; i++)
				{
					var bd = buildingData[i];
					if (bd != null && TryGetBuildingSid(bd, out var sid))
					{
						sids.Add($"{sid}(lvl={GetBuildingLevel(bd)},built={IsBuildingConstructed(bd)})");
					}
				}
				sb.Append("\n  ").Append(cat).Append(" (").Append(sids.Count).Append("): ")
					.Append(sids.Count == 0 ? "EMPTY" : string.Join(", ", sids));
			}
		}
		else if (city != null)
		{
			sb.Append("\n  city.buildings: null");
		}

		Plugin.LogSource?.LogInfo(sb.ToString());
	}

	private static ObjCity TryGetCurrentCity()
	{
		try
		{
			return ModActions.GetCurrentCityData();
		}
		catch
		{
			return null;
		}
	}

	// Named categories on BuildingsData (from diagnostic log).
	private static readonly string[] BuildingCategories = new[]
	{
		"hires", "mains", "magicGuilds", "walls", "markets", "taverns",
		"banks", "manaFountains", "intelligences", "bonusBanks",
		"unitsConverters", "trainingRanges", "rebirthShrines",
		"heroBonusBanks", "cityBonusBanks", "myceliumRoots",
		"portalSummonings", "artifactChangers", "artifactMarkets",
	};

	private static List<BuildingData> GetConstructedBuildings(ObjCity city)
	{
		var result = new List<BuildingData>();
		if (city == null || city.buildings == null)
		{
			return result;
		}

		var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

		// Try the obfuscated methods first - they're confirmed to return List<BuildingData>.
		foreach (var field in GameSymbols.ReleaseTownUi.BuildingDataListMembers)
		{
			var listObj = GetMemberValue(city.buildings, field);
			var buildingData = EnumerateBuildingData(listObj);
			if (buildingData.Count == 0)
			{
				continue;
			}

			for (var i = 0; i < buildingData.Count; i++)
			{
				var data = buildingData[i];
				if (data == null || !IsBuildingConstructed(data) || !TryGetBuildingSid(data, out var sid))
				{
					continue;
				}

				var level = GetBuildingLevel(data);
				if (seen.Add(sid + ":" + level))
				{
					result.Add(data);
				}
			}
		}

		// Fallback: also check named categories (may return subclass lists - attempt the cast anyway).
		if (result.Count == 0)
		{
			foreach (var method in GameSymbols.ReleaseTownUi.BuildingDataListMethods)
			{
				var listObj = GetExactNoArgMethodValue(city.buildings, method);
				var buildingData = EnumerateBuildingData(listObj);
				if (buildingData.Count == 0)
				{
					continue;
				}

				for (var i = 0; i < buildingData.Count; i++)
				{
					var data = buildingData[i];
					if (data == null || !IsBuildingConstructed(data) || !TryGetBuildingSid(data, out var sid))
					{
						continue;
					}

					var level = GetBuildingLevel(data);
					if (seen.Add(sid + ":" + level))
					{
						result.Add(data);
					}
				}
			}
		}

		// Fallback: also check named categories field-only.
		if (result.Count == 0)
		{
			foreach (var category in BuildingCategories)
			{
				var listObj = GetMemberValue(city.buildings, category);
				var buildingData = EnumerateBuildingData(listObj);
				if (buildingData.Count == 0)
				{
					continue;
				}

				for (var i = 0; i < buildingData.Count; i++)
				{
					var data = buildingData[i];
					if (data == null || !IsBuildingConstructed(data) || !TryGetBuildingSid(data, out var sid))
					{
						continue;
					}

					var level = GetBuildingLevel(data);
					if (seen.Add(sid + ":" + level))
					{
						result.Add(data);
					}
				}
			}
		}

		return result
			.OrderBy(GetBuildingLevel)
			.ThenBy(x => TryGetBuildingSid(x, out var sid) ? sid : "", StringComparer.OrdinalIgnoreCase)
			.ToList();
	}

	private static List<BuildingData> GetObservedConstructedBuildings(string fraction)
	{
		var result = new List<BuildingData>();
		if (string.IsNullOrWhiteSpace(fraction))
			return result;
		var townKey = BuildObservedTownKey(fraction, null);
		if (townKey == null
			|| !ObservedBuildingDataByTownKey.TryGetValue(townKey, out var state)
			|| state == null
			|| state.Buildings.Count == 0)
		{
			return result;
		}
		if (!IsSupportedTownFraction(state.Fraction))
			state.Fraction = fraction;
		if (!string.Equals(state.Fraction, fraction, StringComparison.OrdinalIgnoreCase))
			return result;

		var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
		foreach (var pair in state.Buildings)
		{
			var data = pair.Value;
			if (data == null || !IsBuildingConstructed(data) || !TryGetBuildingSid(data, out var sid))
				continue;
			var level = Math.Max(1, GetBuildingLevel(data));
			if (seen.Add(sid + ":" + level))
				result.Add(data);
		}

		return result
			.OrderBy(GetBuildingLevel)
			.ThenBy(x => TryGetBuildingSid(x, out var sid) ? sid : "", StringComparer.OrdinalIgnoreCase)
			.ToList();
	}

	internal static bool TryGetBuildingSid(BuildingData data, out string sid)
	{
		sid = null;
		if (data == null)
			return false;

		for (var i = 0; i < GameSymbols.ReleaseTownUi.BuildingDataSidMembers.Length; i++)
		{
			sid = TryGetBuildingDataMemberValue(data, GameSymbols.ReleaseTownUi.BuildingDataSidMembers[i], out var value) ? value as string : null;
			if (!string.IsNullOrWhiteSpace(sid))
				return true;
		}
		for (var i = 0; i < GameSymbols.ReleaseTownUi.BuildingDataSidAccessorMethods.Length; i++)
		{
			sid = TryInvokeExactBuildingDataAccessor(data, GameSymbols.ReleaseTownUi.BuildingDataSidAccessorMethods[i]) as string;
			if (!string.IsNullOrWhiteSpace(sid))
				return true;
		}
		return !string.IsNullOrWhiteSpace(sid);
	}

	internal static int GetBuildingLevel(BuildingData data)
	{
		if (data == null)
			return 0;

		object value = null;
		for (var i = 0; i < GameSymbols.ReleaseTownUi.BuildingDataLevelMembers.Length; i++)
		{
			value = TryGetBuildingDataMemberValue(data, GameSymbols.ReleaseTownUi.BuildingDataLevelMembers[i], out var candidate) ? candidate : null;
			if (value != null)
				break;
		}
		if (value == null)
		{
			for (var i = 0; i < GameSymbols.ReleaseTownUi.BuildingDataLevelAccessorMethods.Length; i++)
			{
				value = TryInvokeExactBuildingDataAccessor(data, GameSymbols.ReleaseTownUi.BuildingDataLevelAccessorMethods[i]);
				if (value != null)
					break;
			}
		}
		if (value == null)
			return 0;

		try
		{
			return Convert.ToInt32(value);
		}
		catch
		{
			return 0;
		}
	}

#if !RELEASE_CANDIDATE_BUILD
	internal static LiveProbeTownLayerState GetLiveProbeLayerState()
	{
		var state = new LiveProbeTownLayerState();
		try
		{
			if (_root == null || !_root)
				return state;
			state.RootExists = true;
			state.RootActive = _root.gameObject != null && _root.gameObject.activeInHierarchy;
			state.RootObjectId = _root.gameObject != null ? _root.gameObject.GetInstanceID() : 0;
			state.RootPath = UnityPath(_root);
			state.RootScene = _root.gameObject != null && _root.gameObject.scene.IsValid() ? _root.gameObject.scene.name : "";
			var rawImages = _root.GetComponentsInChildren<RawImage>(true);
			state.RawImageCount = rawImages == null ? 0 : rawImages.Length;
			if (rawImages != null)
			{
				for (var i = 0; i < rawImages.Length; i++)
				{
					var image = rawImages[i];
					if (image != null && image.enabled && image.gameObject != null && image.gameObject.activeInHierarchy)
						state.ActiveLayerCount++;
				}
			}
			var graphics = _root.GetComponentsInChildren<Graphic>(true);
			state.GraphicCount = graphics == null ? 0 : graphics.Length;
		}
		catch
		{
		}
		return state;
	}
#endif

	private static bool IsBuildingConstructed(BuildingData data)
	{
		if (data == null)
			return false;

		for (var i = 0; i < GameSymbols.ReleaseTownUi.BuildingDataConstructedMembers.Length; i++)
		{
			var value = TryGetBuildingDataMemberValue(data, GameSymbols.ReleaseTownUi.BuildingDataConstructedMembers[i], out var candidate) ? candidate : null;
			if (value is bool built)
				return built;
		}
		for (var i = 0; i < GameSymbols.ReleaseTownUi.BuildingDataConstructedAccessorMethods.Length; i++)
		{
			var value = TryInvokeExactBuildingDataAccessor(data, GameSymbols.ReleaseTownUi.BuildingDataConstructedAccessorMethods[i]);
			if (value is bool built)
				return built;
		}
		return false;
	}

	private static object TryInvokeExactBuildingDataAccessor(BuildingData data, string methodName)
	{
		if (data == null || string.IsNullOrEmpty(methodName))
			return null;
		if (!ContainsExact(GameSymbols.ReleaseTownUi.BuildingDataSidAccessorMethods, methodName)
		    && !ContainsExact(GameSymbols.ReleaseTownUi.BuildingDataLevelAccessorMethods, methodName)
		    && !ContainsExact(GameSymbols.ReleaseTownUi.BuildingDataConstructedAccessorMethods, methodName))
			return null;
		try
		{
			var method = data.GetType().GetMethod(methodName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
			if (method == null || !IsExpectedBuildingDataAccessorReturnType(methodName, method.ReturnType))
				return null;
			return method.Invoke(data, Array.Empty<object>());
		}
		catch
		{
			return null;
		}
	}

	private static bool IsExpectedBuildingDataAccessorReturnType(string methodName, Type returnType)
	{
		if (returnType == null)
			return false;
		if (ContainsExact(GameSymbols.ReleaseTownUi.BuildingDataSidAccessorMethods, methodName))
			return returnType == typeof(string);
		if (ContainsExact(GameSymbols.ReleaseTownUi.BuildingDataLevelAccessorMethods, methodName))
			return returnType == typeof(int);
		if (ContainsExact(GameSymbols.ReleaseTownUi.BuildingDataConstructedAccessorMethods, methodName))
			return returnType == typeof(bool);
		return false;
	}

	private static bool ContainsExact(string[] values, string value)
	{
		if (values == null || value == null)
			return false;
		for (var i = 0; i < values.Length; i++)
		{
			if (string.Equals(values[i], value, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool TryGetBuildingDataMemberValue(BuildingData data, string name, out object value)
	{
		value = null;
		if (data == null || string.IsNullOrEmpty(name))
			return false;

		var type = data.GetType();
		var field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		if (field != null)
		{
			try
			{
				value = field.GetValue(data);
				return true;
			}
			catch
			{
				value = null;
			}
		}

		return false;
	}

	private static List<BuildingData> EnumerateBuildingData(object listObj)
	{
		var result = new List<BuildingData>();
		if (listObj == null)
			return result;

		if (listObj is Il2CppSystem.Collections.Generic.List<BuildingData> exactList)
		{
			for (var i = 0; i < exactList.Count; i++)
				if (exactList[i] != null)
					result.Add(exactList[i]);
			return result;
		}

		if (listObj is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
				if (item is BuildingData data)
					result.Add(data);
			if (result.Count > 0)
				return result;
		}

		try
		{
			var type = listObj.GetType();
			var countValue = GetMemberValue(listObj, "Count");
			if (countValue == null)
				countValue = GetMemberValue(listObj, "count");
			if (countValue == null)
				return result;
			var count = Convert.ToInt32(countValue);
			var indexer = type.GetProperty("Item", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			var getItem = type.GetMethod("get_Item", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new[] { typeof(int) }, null);
			for (var i = 0; i < count; i++)
			{
				object item = null;
				try
				{
					item = indexer != null
						? indexer.GetValue(listObj, new object[] { i })
						: getItem?.Invoke(listObj, new object[] { i });
				}
				catch
				{
					continue;
				}
				if (item is BuildingData data)
					result.Add(data);
			}
		}
		catch
		{
		}

		return result;
	}

	private static string BuildSignature(string fraction, IReadOnlyList<BuildingData> buildings, RectTransform panelRoot)
	{
		var layerRoot = ResolveTownLayerRootRelativePath(fraction);
		GetLayerPlacements(fraction); // ensure placement stamp is current before we embed it
		GetBuildingLayerIds(fraction); // ensure mapping stamp is current before we embed it
		var sb = new System.Text.StringBuilder();
		sb.Append(fraction ?? "");
		sb.Append("~root:").Append(layerRoot ?? "none");
		sb.Append("~pos:").Append(layerRoot != null && _layerPlacementsStampByRoot.TryGetValue(layerRoot, out var posStamp) ? posStamp ?? "none" : "none");
		sb.Append("~map:").Append(layerRoot != null && _buildingLayerIdsStampByRoot.TryGetValue(layerRoot, out var mapStamp) ? mapStamp ?? "default" : "default");
		sb.Append("~mode:dynamic");
		sb.Append("~xfm:").Append(ModActions.GetCityBackdropTransformSignature(panelRoot));
		var plannedLayers = PlanActiveLayers(fraction, buildings);
		for (var i = 0; i < plannedLayers.Count; i++)
		{
			var planned = plannedLayers[i];
			sb.Append('|').Append(planned.LayerId ?? "").Append(':').Append(planned.Level);
			if (planned.Placement?.Sprite != null)
				sb.Append("~spr:").Append(planned.Placement.Sprite);
			// Do not FileInfo-stamp every sprite on the hot sync path; pos/map stamps already
			// invalidate when placement/mapping JSON changes.
		}

		return sb.ToString();
	}


	private static RectTransform EnsureDynamicLayerRoot(RectTransform panelRoot)
	{
		if (panelRoot == null)
			throw new InvalidOperationException("CanvasCityPanel is missing while creating HoMM3 town layer root.");

		if (_root != null && _rootFromPrefab)
		{
			UnityEngine.Object.Destroy(_root.gameObject);
			_root = null;
			_rootFromPrefab = false;
			_rootPrefabFraction = null;
			PendingPrefabAnimations.Clear();
		}

		if (_root != null && _root)
		{
			if (_root.parent != panelRoot)
				_root.SetParent(panelRoot, false);
			_root.gameObject.SetActive(true);
			_rootFromPrefab = false;
			_rootPrefabFraction = null;
			return _root;
		}

		var go = new GameObject(LayerRootName);
		var rect = go.AddComponent<RectTransform>();
		rect.SetParent(panelRoot, false);
		go.SetActive(true);
		_root = rect;
		_rootFromPrefab = false;
		_rootPrefabFraction = null;
		_rootCreatedFrame = Time.frameCount;
		return rect;
	}

	private static void ApplyLayerRootTransform(RectTransform layerRoot, RectTransform panelRoot)
	{
		if (layerRoot == null || panelRoot == null)
		{
			return;
		}

		layerRoot.anchorMin = Vector2.zero;
		layerRoot.anchorMax = Vector2.one;
		layerRoot.pivot = new Vector2(0.5f, 0.5f);
		ModActions.ApplyCityBackdropTransformToLayerRoot(panelRoot, layerRoot);
		EnsureTownLayerCanvasOrder(layerRoot);
		layerRoot.localScale = Vector3.one;
		layerRoot.localRotation = Quaternion.identity;
	}

	private static void EnsureTownLayerCanvasOrder(RectTransform layerRoot)
	{
		if (layerRoot == null)
			return;

		var source = ModActions.ResolveCityPanelSourceCanvas();
		if (source != null && IsUnderTransform(layerRoot, source.transform))
		{
			var nested = layerRoot.GetComponent<Canvas>();
			if (nested != null)
				ModActions.EnsureCustomTownArtCanvas(nested, ModActions.CustomTownLayerSortingOrder);
			return;
		}

		var canvas = layerRoot.GetComponent<Canvas>() ?? layerRoot.gameObject.AddComponent<Canvas>();
		ModActions.EnsureCustomTownArtCanvas(canvas, ModActions.CustomTownLayerSortingOrder);
	}

	private static bool IsUnderTransform(Transform child, Transform ancestor)
	{
		if (child == null || ancestor == null)
			return false;
		for (var current = child; current != null; current = current.parent)
		{
			if (current == ancestor)
				return true;
		}
		return false;
	}

	private static void ApplyLayerSiblingIndex(RectTransform layerRoot, RectTransform panelRoot)
	{
		if (layerRoot == null || panelRoot == null)
			return;

		if (layerRoot.parent == panelRoot)
			ModActions.EnsureCityPanelNativeHudSiblingOrder(panelRoot, layerRoot);

		ModActions.EnsureCustomTownUiAboveTownArt(panelRoot);
	}

	private static bool TryEnsurePrefabLayerRoot(RectTransform panelRoot, string fraction, out RectTransform prefabRoot)
	{
		prefabRoot = null;
		if (!AreTownPrefabsEnabled())
			return false;

		if (panelRoot == null || string.IsNullOrWhiteSpace(fraction))
			return false;

		var prefab = LoadTownPrefab(fraction);
		if (prefab == null)
			throw new InvalidOperationException("required HoMM3 town prefab asset is missing for fraction '" + fraction + "'.");

		if (_root != null
			&& _rootFromPrefab
			&& string.Equals(_rootPrefabFraction, fraction, StringComparison.OrdinalIgnoreCase))
		{
			if (_root.parent != panelRoot)
				_root.SetParent(panelRoot, false);
			_root.gameObject.SetActive(true);
			prefabRoot = _root;
			return true;
		}

		if (_root != null)
		{
			UnityEngine.Object.Destroy(_root.gameObject);
			_root = null;
			PendingPrefabAnimations.Clear();
		}

		var instance = UnityEngine.Object.Instantiate(prefab);
		if (instance == null)
			throw new InvalidOperationException("failed to instantiate required HoMM3 town prefab for fraction '" + fraction + "'.");

		instance.name = LayerRootName;
		var rect = instance.GetComponent<RectTransform>() ?? instance.AddComponent<RectTransform>();
		rect.SetParent(panelRoot, false);
		instance.SetActive(true);
		_root = rect;
		_rootFromPrefab = true;
		_rootPrefabFraction = fraction;
		_rootCreatedFrame = Time.frameCount;
		prefabRoot = rect;
		Plugin.LogSource?.LogInfo("HoMM3 town prefabs: instantiated prefab for " + fraction + ".");
		return true;
	}

	private static bool TryPrewarmTownPrefabAsset(string fraction)
	{
		if (string.IsNullOrWhiteSpace(fraction))
			return false;
		if (!AreTownPrefabsEnabled())
			return false;
		try
		{
			return LoadTownPrefab(fraction) != null;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogInfo("HoMM3 town prefabs: prewarm unavailable for " + fraction + ": " + ex.Message);
			return false;
		}
	}

	private static GameObject LoadTownPrefab(string fraction)
	{
		var bundle = LoadTownPrefabBundle();

		if (TownPrefabCache.TryGetValue(fraction, out var cached) && cached != null)
			return cached;

		var assetName = TownPrefabAssetRoot + "/" + fraction + "/" + fraction + "_town.prefab";
		var prefab = bundle.LoadAsset<GameObject>(assetName);
		if (prefab == null)
		{
			throw new InvalidOperationException(
				"HoMM3 town prefab bundle is present but has no prefab for "
				+ fraction
				+ " at "
				+ assetName
				+ ".");
		}

		TownPrefabCache[fraction] = prefab;
		return prefab;
	}

	private static AssetBundle LoadTownPrefabBundle()
	{
		var path = ResolveExistingPath(TownPrefabBundleRelativePath, logMissing: false);
		if (path == null)
			throw new InvalidOperationException("required HoMM3 town prefab bundle is missing at " + TownPrefabBundleRelativePath + ".");

		if (_townPrefabBundle != null && string.Equals(_townPrefabBundlePath, path, StringComparison.OrdinalIgnoreCase))
			return _townPrefabBundle;

		if (_townPrefabBundle != null)
			_townPrefabBundle.Unload(false);
		TownPrefabCache.Clear();
		_townPrefabBundle = AssetBundle.LoadFromFile(path);
		_townPrefabBundlePath = path;
		if (_townPrefabBundle == null)
			throw new InvalidOperationException("required HoMM3 town prefab bundle failed to load from " + path + ".");

		Plugin.LogSource?.LogInfo("HoMM3 town prefabs: loaded bundle " + path + ".");
		return _townPrefabBundle;
	}

	private static bool AreTownPrefabsEnabled()
	{
		if (_townPrefabsEnabled.HasValue)
			return _townPrefabsEnabled.Value;
		var cfg = LauncherConfigReader.TryLoad();
		_townPrefabsEnabled = cfg == null || cfg.Homm3TownPrefabs;
		if (!_townPrefabsEnabled.Value)
			throw new InvalidOperationException("HoMM3 town prefabs are disabled in launcher config; dynamic loose town layers are not a production fallback.");
		return true;
	}

	private static string GetTownPrefabBundleStamp()
	{
		var path = ResolveExistingPath(TownPrefabBundleRelativePath, logMissing: false);
		return path == null ? null : GetTextureStamp(path);
	}


	private static LayerUpdateProfile UpdateLayerImages(RectTransform layerRoot, string fraction, IReadOnlyList<BuildingData> buildings)
	{
		var profile = new LayerUpdateProfile { Buildings = buildings?.Count ?? 0, UsedPrefab = false };
		var phase = Stopwatch.StartNew();
		var activeNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
		var activeEntries = new List<ActiveLayerEntry>();
		var activeKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
		var newlyVisibleImages = new List<RawImage>();
		PendingPrefabAnimations.Clear();

		var plannedLayers = PlanActiveLayers(fraction, buildings);
		for (var i = 0; i < plannedLayers.Count; i++)
		{
			var planned = plannedLayers[i];
			var level = planned.Level;
			var layerId = planned.LayerId;
			var placement = planned.Placement;
			profile.ResolveMs += phase.ElapsedMilliseconds;
			phase.Restart();
			if (layerId == null || placement == null || placement.Hidden)
				continue;

			var texture = LoadTownLayerTexture(fraction, layerId, placement);
			profile.TextureMs += phase.ElapsedMilliseconds;
			phase.Restart();
			if (texture == null)
				continue;

			var objectName = BuildLayerObjectName(layerId, level);
			var image = EnsureLayerImage(layerRoot, objectName, out var created);
			if (created)
				profile.CreatedImages++;
			profile.EnsureImageMs += phase.ElapsedMilliseconds;
			phase.Restart();

			image.texture = texture;
			image.color = Color.white;
			// Pass clicks through to world BhBuilding (PhysicsRaycaster). Never capture on Route A art.
			image.raycastTarget = false;
			image.maskable = false;
			ApplyLayerImageTransform(image.rectTransform, layerRoot, texture, placement);
			profile.TransformMs += phase.ElapsedMilliseconds;
			phase.Restart();
			image.gameObject.SetActive(true);
			Homm3StrongholdTownAnimPlayer.TryAttach(image, fraction, layerId, level);
			profile.AnimPlayers++;
			profile.AnimMs += phase.ElapsedMilliseconds;
			phase.Restart();

			activeNames.Add(image.gameObject.name);
			activeEntries.Add(new ActiveLayerEntry(image, placement));
			var layerKey = BuildVisibleLayerKey(layerId, level);
			activeKeys.Add(layerKey);
			if (_hasSeenVisibleLayerState && !_knownVisibleLayerKeys.Contains(layerKey))
				newlyVisibleImages.Add(image);
		}

		activeEntries.Sort((left, right) =>
		{
			var zCompare = left.Placement.Z.CompareTo(right.Placement.Z);
			return zCompare != 0 ? zCompare : left.Placement.Order.CompareTo(right.Placement.Order);
		});
		profile.SortMs = phase.ElapsedMilliseconds;
		phase.Restart();

		for (var i = 0; i < activeEntries.Count; i++)
			activeEntries[i].Image.transform.SetSiblingIndex(i);
		profile.SiblingMs = phase.ElapsedMilliseconds;
		phase.Restart();

		for (var i = 0; i < layerRoot.childCount; i++)
		{
			var child = layerRoot.GetChild(i)?.gameObject;
			if (child != null && !activeNames.Contains(child.name))
				child.SetActive(false);
		}
		profile.HideMs = phase.ElapsedMilliseconds;
		phase.Restart();

		layerRoot.gameObject.SetActive(activeNames.Count > 0);
		var effects = Homm3StrongholdTownBuildEffects.TryAttach(layerRoot.gameObject, Plugin.LogSource);
		if (newlyVisibleImages.Count > 0 && effects != null)
		{
			for (var i = 0; i < newlyVisibleImages.Count; i++)
				effects.BeginFade(newlyVisibleImages[i]);
			effects.PlayBuildSound();
			profile.EffectFades = newlyVisibleImages.Count;
		}
		profile.EffectsMs = phase.ElapsedMilliseconds;
		profile.ActiveLayers = activeEntries.Count;

		_knownVisibleLayerKeys = activeKeys;
		_hasSeenVisibleLayerState = true;
		return profile;
	}

	private static RawImage EnsureLayerImage(RectTransform layerRoot, string objectName, out bool created)
	{
		created = false;
		var existing = layerRoot.Find(objectName);
		if (existing != null)
		{
			var existingImage = existing.GetComponent<RawImage>();
			if (existingImage != null)
				return existingImage;
		}

		var go = new GameObject(objectName);
		go.AddComponent<RectTransform>();
		var image = go.AddComponent<RawImage>();
		go.transform.SetParent(layerRoot, false);
		created = true;
		return image;
	}

	private static Texture2D LoadTownLayerTexture(string fraction, string layerId, LayerPlacement placement)
	{
		var layerRoot = ResolveTownLayerRootRelativePath(fraction);
		var spriteName = placement?.Sprite;
		if (string.IsNullOrWhiteSpace(layerRoot) || string.IsNullOrWhiteSpace(spriteName))
		{
			Plugin.LogSource?.LogWarning("HoMM3 town layers: planned layer '" + (layerId ?? "(null)") + "' has no deployed sprite for fraction '" + (fraction ?? "(null)") + "'.");
			return null;
		}

		var relativePath = Path.Combine(layerRoot, spriteName);
		var path = ResolveExistingPath(relativePath);
		if (path == null)
			return null;

		var stamp = GetTextureStamp(path);
		if (_layerTextureCacheByPath.TryGetValue(path, out var cached)
			&& cached != null
			&& cached.Texture != null
			&& string.Equals(cached.Stamp, stamp, StringComparison.Ordinal))
		{
			return cached.Texture;
		}

		try
		{
			var bytes = File.ReadAllBytes(path);
			var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
			texture.name = Path.GetFileNameWithoutExtension(path);
			if (!ImageConversion.LoadImage(texture, bytes, false))
			{
				UnityEngine.Object.Destroy(texture);
				Plugin.LogSource?.LogWarning("HoMM3 town layers: failed to decode layer texture " + relativePath + ".");
				return null;
			}

			texture.wrapMode = TextureWrapMode.Clamp;
			texture.filterMode = FilterMode.Bilinear;
			_layerTextureCacheByPath[path] = new CachedLayerTexture { Stamp = stamp, Texture = texture };
			return texture;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 town layers: failed to load layer texture " + relativePath + ": " + ex.Message);
			return null;
		}
	}

	private static LayerUpdateProfile UpdatePrefabLayerImages(RectTransform layerRoot, string fraction, IReadOnlyList<BuildingData> buildings)
	{
		var profile = new LayerUpdateProfile { Buildings = buildings?.Count ?? 0, UsedPrefab = true };
		var phase = Stopwatch.StartNew();
		var activeNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
		var activeEntries = new List<ActiveLayerEntry>();
		var activeKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
		var newlyVisibleImages = new List<RawImage>();
		PendingPrefabAnimations.Clear();

		var plannedLayers = PlanActiveLayers(fraction, buildings);
		for (var i = 0; i < plannedLayers.Count; i++)
		{
			var planned = plannedLayers[i];
			var level = planned.Level;
			var layerId = planned.LayerId;
			var placement = planned.Placement;
			profile.ResolveMs += phase.ElapsedMilliseconds;
			phase.Restart();
			if (layerId == null || placement == null)
				throw new InvalidOperationException("planned HoMM3 town layer is missing layer id or placement for fraction '" + fraction + "'.");

			var objectName = BuildLayerObjectName(layerId, level);
			var child = layerRoot.Find(objectName);
			if (child == null)
				throw new InvalidOperationException("required HoMM3 town prefab child missing for fraction '" + fraction + "': " + objectName + ".");
			var image = child.GetComponent<RawImage>();
			profile.EnsureImageMs += phase.ElapsedMilliseconds;
			phase.Restart();
			if (image == null)
				throw new InvalidOperationException("required HoMM3 town prefab RawImage missing for fraction '" + fraction + "': " + objectName + ".");
			var texture = image.texture as Texture2D;
			if (texture == null)
				throw new InvalidOperationException("required HoMM3 town prefab Texture2D missing for fraction '" + fraction + "': " + objectName + ".");

			image.color = Color.white;
			image.raycastTarget = false;
			image.maskable = false;
			ApplyLayerImageTransform(image.rectTransform, layerRoot, texture, placement);
			profile.TransformMs += phase.ElapsedMilliseconds;
			phase.Restart();
			image.gameObject.SetActive(true);
			PendingPrefabAnimations.Add(new PendingAnimAttachment
			{
				Image = image,
				Fraction = fraction,
				LayerId = layerId,
				Level = level
			});
			profile.AnimPlayers++;
			profile.AnimMs += phase.ElapsedMilliseconds;
			phase.Restart();

			activeNames.Add(image.gameObject.name);
			activeEntries.Add(new ActiveLayerEntry(image, placement));
			var layerKey = BuildVisibleLayerKey(layerId, level);
			activeKeys.Add(layerKey);
			if (_hasSeenVisibleLayerState && !_knownVisibleLayerKeys.Contains(layerKey))
				newlyVisibleImages.Add(image);
		}

		activeEntries.Sort((left, right) =>
		{
			var zCompare = left.Placement.Z.CompareTo(right.Placement.Z);
			return zCompare != 0 ? zCompare : left.Placement.Order.CompareTo(right.Placement.Order);
		});
		profile.SortMs = phase.ElapsedMilliseconds;
		phase.Restart();

		for (var i = 0; i < activeEntries.Count; i++)
			activeEntries[i].Image.transform.SetSiblingIndex(i);
		profile.SiblingMs = phase.ElapsedMilliseconds;
		phase.Restart();

		for (var i = 0; i < layerRoot.childCount; i++)
		{
			var child = layerRoot.GetChild(i)?.gameObject;
			if (child != null && !activeNames.Contains(child.name))
				child.SetActive(false);
		}
		profile.HideMs = phase.ElapsedMilliseconds;
		phase.Restart();

		layerRoot.gameObject.SetActive(activeNames.Count > 0);
		var effects = Homm3StrongholdTownBuildEffects.TryAttach(layerRoot.gameObject, Plugin.LogSource);
		if (newlyVisibleImages.Count > 0 && effects != null)
		{
			for (var i = 0; i < newlyVisibleImages.Count; i++)
				effects.BeginFade(newlyVisibleImages[i]);
			effects.PlayBuildSound();
			profile.EffectFades = newlyVisibleImages.Count;
		}
		profile.EffectsMs = phase.ElapsedMilliseconds;
		profile.ActiveLayers = activeEntries.Count;

		_knownVisibleLayerKeys = activeKeys;
		_hasSeenVisibleLayerState = true;
		return profile;
	}

	private static void AttachPendingPrefabAnimations()
	{
		if (PendingPrefabAnimations.Count == 0 || Time.frameCount <= _rootCreatedFrame)
			return;

		for (var i = 0; i < PendingPrefabAnimations.Count; i++)
		{
			var pending = PendingPrefabAnimations[i];
			Homm3StrongholdTownAnimPlayer.TryAttach(pending.Image, pending.Fraction, pending.LayerId, pending.Level);
		}
		PendingPrefabAnimations.Clear();
	}

	private static List<PlannedLayerEntry> PlanActiveLayers(string fraction, IReadOnlyList<BuildingData> buildings)
	{
		var result = new Dictionary<string, PlannedLayerEntry>(StringComparer.OrdinalIgnoreCase);
		if (buildings == null)
			return new List<PlannedLayerEntry>();

		for (var i = 0; i < buildings.Count; i++)
		{
			var building = buildings[i];
			if (!TryGetBuildingSid(building, out var sid))
				continue;
			var level = GetBuildingLevel(building);
			var layerId = ResolveLayerId(fraction, sid, level);
			var placement = ResolveLayerPlacement(fraction, layerId, level);
			if (layerId == null || placement == null)
				continue;

			var key = layerId + ":" + level;
			var rank = placement.Order;
			if (TryGetVcmiStructureGroupAndRank(placement.Structure, out var group, out var structureRank))
			{
				key = "vcmi:" + group;
				rank = structureRank;
			}

			var candidate = new PlannedLayerEntry(sid, layerId, level, placement);
			if (!result.TryGetValue(key, out var previous)
				|| rank > GetPlannedLayerRank(previous)
				|| (rank == GetPlannedLayerRank(previous) && placement.Order > previous.Placement.Order))
			{
				result[key] = candidate;
			}
		}

		return result.Values
			.OrderBy(entry => entry.Placement.Z)
			.ThenBy(entry => entry.Placement.Order)
			.ToList();
	}

	private static int GetPlannedLayerRank(PlannedLayerEntry entry)
	{
		if (entry == null || entry.Placement == null)
			return int.MinValue;
		return TryGetVcmiStructureGroupAndRank(entry.Placement.Structure, out _, out var rank) ? rank : entry.Placement.Order;
	}

	private static bool TryGetVcmiStructureGroupAndRank(string structure, out string group, out int rank)
	{
		group = null;
		rank = 0;
		if (string.IsNullOrEmpty(structure))
			return false;

		if (string.Equals(structure, "fort", StringComparison.OrdinalIgnoreCase)
			|| string.Equals(structure, "citadel", StringComparison.OrdinalIgnoreCase)
			|| string.Equals(structure, "castle", StringComparison.OrdinalIgnoreCase))
		{
			group = "fort";
			rank = string.Equals(structure, "castle", StringComparison.OrdinalIgnoreCase) ? 2
				: string.Equals(structure, "citadel", StringComparison.OrdinalIgnoreCase) ? 1 : 0;
			return true;
		}

		if (string.Equals(structure, "villageHall", StringComparison.OrdinalIgnoreCase)
			|| string.Equals(structure, "townHall", StringComparison.OrdinalIgnoreCase)
			|| string.Equals(structure, "cityHall", StringComparison.OrdinalIgnoreCase)
			|| string.Equals(structure, "capitol", StringComparison.OrdinalIgnoreCase))
		{
			group = "villageHall";
			rank = string.Equals(structure, "capitol", StringComparison.OrdinalIgnoreCase) ? 3
				: string.Equals(structure, "cityHall", StringComparison.OrdinalIgnoreCase) ? 2
				: string.Equals(structure, "townHall", StringComparison.OrdinalIgnoreCase) ? 1 : 0;
			return true;
		}

		var mageMatch = System.Text.RegularExpressions.Regex.Match(structure, "^mageGuild(?<level>\\d+)$", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
		if (mageMatch.Success && int.TryParse(mageMatch.Groups["level"].Value, out var mageLevel))
		{
			group = "mageGuild1";
			rank = mageLevel - 1;
			return true;
		}

		var dwellingMatch = System.Text.RegularExpressions.Regex.Match(structure, "^dwelling(?<upgrade>Up2|Up)?Lvl(?<tier>[1-7])$", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
		if (dwellingMatch.Success)
		{
			group = "dwellingLvl" + dwellingMatch.Groups["tier"].Value;
			var upgrade = dwellingMatch.Groups["upgrade"].Value;
			rank = string.Equals(upgrade, "Up2", StringComparison.OrdinalIgnoreCase) ? 2
				: string.Equals(upgrade, "Up", StringComparison.OrdinalIgnoreCase) ? 1 : 0;
			return true;
		}

		var hordeMatch = System.Text.RegularExpressions.Regex.Match(structure, "^horde(?<tier>[12])(?<upgr>Upgr)?$", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
		if (hordeMatch.Success)
		{
			group = "dwellingLvl1";
			rank = string.Equals(hordeMatch.Groups["tier"].Value, "2", StringComparison.OrdinalIgnoreCase) ? 3 : 1;
			if (hordeMatch.Groups["upgr"].Success)
				rank++;
			return true;
		}

		if (string.Equals(structure, "shipyard", StringComparison.OrdinalIgnoreCase)
			|| string.Equals(structure, "ship", StringComparison.OrdinalIgnoreCase))
		{
			group = "shipyard";
			rank = string.Equals(structure, "ship", StringComparison.OrdinalIgnoreCase) ? 1 : 0;
			return true;
		}

		return false;
	}

	private static string BuildVisibleLayerKey(string layerId, int level)
	{
		return (layerId ?? "") + ":" + level;
	}

	private static string ResolveLayerId(string fraction, string buildingSid, int level)
	{
		if (string.IsNullOrEmpty(buildingSid))
		{
			return null;
		}

		if (GetBuildingLayerLevels(fraction).TryGetValue(buildingSid, out var levels)
			&& levels.TryGetValue(level, out var levelLayerId)
			&& !string.IsNullOrEmpty(levelLayerId))
		{
			return levelLayerId;
		}

		if (GetBuildingLayerIds(fraction).TryGetValue(buildingSid, out var layerId))
		{
			return layerId;
		}

		return GetLayerPlacements(fraction).ContainsKey(buildingSid) ? buildingSid : null;
	}

	private static LayerPlacement ResolveLayerPlacement(string fraction, string layerId, int level)
	{
		if (string.IsNullOrEmpty(layerId))
		{
			return null;
		}

		var placements = GetLayerPlacements(fraction);
		var candidates = new[]
		{
			layerId + "_" + level,
			layerId + "_lvl" + level,
			layerId,
		};

		for (var i = 0; i < candidates.Length; i++)
		{
			if (placements.TryGetValue(candidates[i], out var placement))
			{
				return placement;
			}
		}

		return null;
	}

	// Positions are prebaked by tools/prebake_homm3_town_scene_coordinates.py
	// into a 1920x1080 reference canvas with the black 800x600 town plate
	// uniformly scaled to 1440x1080 and left-aligned for native menu clearance.
	private static void ApplyLayerImageTransform(RectTransform rect, RectTransform panelRoot, Texture2D texture, LayerPlacement placement)
	{
		if (rect == null || panelRoot == null || texture == null || placement == null)
		{
			return;
		}

		var rootRect = panelRoot.rect;
		var canvasW = rootRect.width > 1f ? rootRect.width : Screen.width;
		var canvasH = rootRect.height > 1f ? rootRect.height : Screen.height;
		if (!_loggedLayerTransformBasis)
		{
			_loggedLayerTransformBasis = true;
			Plugin.LogSource?.LogInfo(
				"HoMM3 Stronghold town layers: CanvasCityPanel basis "
				+ canvasW.ToString("0")
				+ "x"
				+ canvasH.ToString("0")
				+ "; editor preview should use --panel "
				+ canvasW.ToString("0")
				+ "x"
				+ canvasH.ToString("0")
				+ " when adjusting positions.");
		}

		var toCanvasX = canvasW / ReferenceWidth;
		var toCanvasY = canvasH / ReferenceHeight;

		var posX = placement.ReferenceX * toCanvasX;
		var posY = placement.ReferenceY * toCanvasY;

		rect.anchorMin = new Vector2(0f, 1f);
		rect.anchorMax = new Vector2(0f, 1f);
		rect.pivot = new Vector2(0f, 1f);
		rect.offsetMin = Vector2.zero;
		rect.offsetMax = Vector2.zero;
		rect.anchoredPosition = new Vector2(posX, -posY);
		rect.sizeDelta = new Vector2(placement.ReferenceWidth * toCanvasX, placement.ReferenceHeight * toCanvasY);
		rect.localScale = Vector3.one;
		rect.localRotation = Quaternion.identity;
	}

	private static string BuildLayerObjectName(string sid, int level)
	{
		return "OfflineUnlockStrongholdTownLayer_" + SanitizeLayerId(sid) + "_" + level;
	}

	private static string SanitizeLayerId(string sid)
	{
		if (string.IsNullOrEmpty(sid))
		{
			return "unknown";
		}

		var chars = sid.Select(ch => char.IsLetterOrDigit(ch) ? ch : '_').ToArray();
		return new string(chars);
	}

	private static string ResolveTownLayerRootRelativePath(string fraction)
	{
		var folderName = ResolveTownLayerFolderName(fraction);
		return folderName == null
			? null
			: Path.Combine("homm3_runtime_assets", "town_scene_refs", folderName, "layers");
	}

	private static string ResolveTownLayerFolderName(string fraction)
	{
		if (string.IsNullOrEmpty(fraction))
		{
			return null;
		}

		if (Homm3CustomFactionRegistry.IsCustomFactionSid(fraction))
			return fraction.Trim();

		return null;
	}

	private static string ResolveExistingPath(string relativePath, bool logMissing = true)
	{
		if (string.IsNullOrWhiteSpace(relativePath))
			return null;

		var underPlugin = Path.GetFullPath(Path.Combine(Paths.PluginPath, "OfflineUnlockMod", relativePath));
		if (File.Exists(underPlugin))
			return underPlugin;

		if (logMissing && LoggedMissingAssets.Add(relativePath))
			Plugin.LogSource?.LogInfo("HoMM3 Stronghold town layers: missing deployed plugin asset " + relativePath);
		return null;
	}

	private static string GetTextureStamp(string path)
	{
		try
		{
			var frame = Time.frameCount;
			if (!string.IsNullOrEmpty(path)
				&& _fileStampCacheByPath.TryGetValue(path, out var cached)
				&& cached != null
				&& cached.Frame == frame)
			{
				return cached.Stamp;
			}

			string stamp;
			if (!File.Exists(path))
			{
				stamp = null;
			}
			else
			{
				var info = new FileInfo(path);
				stamp = info.Length + ":" + info.LastWriteTimeUtc.Ticks;
			}

			if (!string.IsNullOrEmpty(path))
				_fileStampCacheByPath[path] = new CachedFileStamp(frame, stamp);
			return stamp;
		}
		catch
		{
			return null;
		}
	}

	private static object GetMemberValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
		{
			return null;
		}

		var t = obj.GetType();
		var accessor = GetMemberAccessor(t, name);
		return accessor.TryGetValue(obj, out var value) ? value : null;
	}

	private static object GetExactNoArgMethodValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
		{
			return null;
		}

		try
		{
			var method = obj.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
			return method == null ? null : method.Invoke(obj, Array.Empty<object>());
		}
		catch
		{
			return null;
		}
	}

	private static RectTransform FindCityPanelRectTransform()
	{
		var scene = SceneManager.GetActiveScene();
		if (IsCachedCityPanelRootValid(scene))
			return _cachedCityPanelRoot;

		var cityPanel = GameObject.Find("CanvasCityPanel");
		if (cityPanel == null)
		{
			ClearCachedCityPanelRoot();
			return null;
		}

		var rect = cityPanel.GetComponent<RectTransform>();
		if (rect != null)
			CacheCityPanelRoot(rect, scene);
		return rect;
	}

	private static MemberAccessor GetMemberAccessor(Type type, string name)
	{
		if (!_memberAccessorCacheByType.TryGetValue(type, out var byName))
		{
			byName = new Dictionary<string, MemberAccessor>(StringComparer.Ordinal);
			_memberAccessorCacheByType[type] = byName;
		}

		if (byName.TryGetValue(name, out var accessor))
			return accessor;
		accessor = new MemberAccessor
		{
			Field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
		};
		byName[name] = accessor;
		return accessor;
	}

	private static void CacheCityPanelRoot(RectTransform rect, Scene scene)
	{
		_cachedCityPanelRoot = rect;
		_cachedCityPanelSceneHandle = scene.IsValid() ? scene.handle : 0;
		_cachedCityPanelSceneName = scene.IsValid() ? scene.name : null;
	}

	private static void ClearCachedCityPanelRoot()
	{
		_cachedCityPanelRoot = null;
		_cachedCityPanelSceneHandle = 0;
		_cachedCityPanelSceneName = null;
	}

	private static bool IsCachedCityPanelRootValid(Scene activeScene)
	{
		if (_cachedCityPanelRoot == null || !_cachedCityPanelRoot)
			return false;
		var go = _cachedCityPanelRoot.gameObject;
		if (go == null || !go || !go.activeInHierarchy || !string.Equals(go.name, "CanvasCityPanel", StringComparison.Ordinal))
			return false;
		var scene = go.scene;
		return scene.IsValid()
		       && activeScene.IsValid()
		       && scene.handle == activeScene.handle
		       && _cachedCityPanelSceneHandle == activeScene.handle
		       && string.Equals(scene.name, activeScene.name, StringComparison.Ordinal)
		       && string.Equals(_cachedCityPanelSceneName, activeScene.name, StringComparison.Ordinal);
	}

	private static int FindChildIndex(RectTransform root, string childName)
	{
		if (root == null || string.IsNullOrEmpty(childName))
		{
			return -1;
		}

		for (var i = 0; i < root.childCount; i++)
		{
			var child = root.GetChild(i);
			if (child != null && string.Equals(child.name, childName, StringComparison.Ordinal))
			{
				return i;
			}
		}

		return -1;
	}

	private static bool IsSupportedTownFraction(string fraction)
	{
		if (string.IsNullOrEmpty(fraction))
		{
			return false;
		}

		return string.Equals(fraction, StrongholdFolderName, StringComparison.OrdinalIgnoreCase)
			|| string.Equals(fraction, TowerFolderName, StringComparison.OrdinalIgnoreCase)
			|| string.Equals(fraction, FortressFolderName, StringComparison.OrdinalIgnoreCase)
			|| string.Equals(fraction, CoveFolderName, StringComparison.OrdinalIgnoreCase)
			|| Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction);
	}

	private static bool IsCityInteriorSceneName(string sceneName)
	{
		return !string.IsNullOrEmpty(sceneName)
			&& sceneName.StartsWith("city", StringComparison.OrdinalIgnoreCase);
	}
}

public sealed class Homm3StrongholdTownBuildEffects : MonoBehaviour
{
	private const float FadeDurationSeconds = 0.55f;
	private const float SessionFadeReleaseWindowSeconds = 30.0f;
	private const float DefaultVolume = 0.9f;

	private sealed class FadeEntry
	{
		internal RawImage Image;
		internal float StartTime;
	}

	private static bool _registered;
	private static AudioClip _buildClip;
	private static bool _loadStarted;
	private static bool _loadFailed;

	private readonly List<FadeEntry> _fades = new List<FadeEntry>();
	private float _releaseSessionFadeUntil;
	private string _releaseSessionFadeFraction;
	private AudioSource _audioSource;

	public Homm3StrongholdTownBuildEffects(IntPtr ptr) : base(ptr) { }

	internal static Homm3StrongholdTownBuildEffects TryAttach(GameObject root, ManualLogSource log)
	{
		if (root == null || !root)
		{
			return null;
		}

		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3StrongholdTownBuildEffects>();
				_registered = true;
			}

			var existing = root.GetComponent<Homm3StrongholdTownBuildEffects>();
			if (existing != null)
			{
				StartClipLoadIfNeeded();
				return existing;
			}

			var added = root.AddComponent<Homm3StrongholdTownBuildEffects>();
			StartClipLoadIfNeeded();
			return added;
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 Stronghold town build effects: attach failed: " + ex.Message);
			return null;
		}
	}

	internal void BeginFade(RawImage image)
	{
		if (image == null || !image)
		{
			return;
		}

		try
		{
			var c = image.color;
			image.color = new Color(c.r, c.g, c.b, 0f);
			_fades.Add(new FadeEntry { Image = image, StartTime = Time.unscaledTime });
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town build effects: fade start failed: " + ex.Message);
		}
	}

	internal void PlayBuildSound()
	{
		StartClipLoadIfNeeded();
		if (_buildClip == null || !_buildClip)
		{
			return;
		}

		try
		{
			EnsureAudioSource();
			if (_audioSource != null && _audioSource)
			{
				_audioSource.PlayOneShot(_buildClip, DefaultVolume);
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town build effects: sound play failed: " + ex.Message);
		}
	}

	internal void BeginSessionFadeRelease(string fraction)
	{
		if (string.IsNullOrWhiteSpace(fraction))
			return;
		_releaseSessionFadeFraction = fraction;
		_releaseSessionFadeUntil = Mathf.Max(_releaseSessionFadeUntil, Time.unscaledTime + SessionFadeReleaseWindowSeconds);
	}

	private void Awake()
	{
		StartClipLoadIfNeeded();
	}

	internal static string PrewarmBuildEffects(ManualLogSource log)
	{
		try
		{
			StartClipLoadIfNeeded();
			return GetBuildSoundLoadStatus();
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 Stronghold town build effects: prewarm failed: " + ex.Message);
			return "exception";
		}
	}

	private static string GetBuildSoundLoadStatus()
	{
		if (_buildClip != null && _buildClip)
			return "loaded";
		if (_loadFailed)
			return "failed";
		if (_loadStarted)
			return "started";
		return "not-started";
	}

	private void Update()
	{
		TickFades();
		TickSessionFadeRelease();
	}

	private void EnsureAudioSource()
	{
		if (_audioSource != null && _audioSource)
		{
			return;
		}

		_audioSource = gameObject.AddComponent<AudioSource>();
		_audioSource.playOnAwake = false;
		_audioSource.loop = false;
		_audioSource.spatialBlend = 0f;
		_audioSource.volume = DefaultVolume;
		_audioSource.dopplerLevel = 0f;
	}

	private void TickFades()
	{
		if (_fades.Count == 0)
		{
			return;
		}

		var now = Time.unscaledTime;
		for (var i = _fades.Count - 1; i >= 0; i--)
		{
			var entry = _fades[i];
			var image = entry?.Image;
			if (image == null || !image)
			{
				_fades.RemoveAt(i);
				continue;
			}

			var t = Mathf.Clamp01((now - entry.StartTime) / FadeDurationSeconds);
			t = t * t * (3f - 2f * t);
			var c = image.color;
			image.color = new Color(c.r, c.g, c.b, t);
			if (t >= 1f)
			{
				image.color = new Color(c.r, c.g, c.b, 1f);
				_fades.RemoveAt(i);
			}
		}
	}

	private void TickSessionFadeRelease()
	{
		if (_releaseSessionFadeUntil <= 0f || Time.unscaledTime > _releaseSessionFadeUntil)
			return;
		if (Homm3StrongholdTownLayers.TryReleaseSessionFadeGraphic(_releaseSessionFadeFraction))
			_releaseSessionFadeUntil = 0f;
	}

	private static void StartClipLoadIfNeeded()
	{
		if (_loadStarted || _loadFailed || (_buildClip != null && _buildClip))
		{
			return;
		}

		_loadStarted = true;
		try
		{
			var path = ResolveBuildSoundPath();
			if (string.IsNullOrEmpty(path) || !File.Exists(path))
			{
				_loadFailed = true;
				Plugin.LogSource?.LogInfo("HoMM3 Stronghold town build effects: missing BUILDTWN.wav");
				return;
			}

			if (!TryLoadPcmWavClip(path, out _buildClip, out var failReason))
			{
				_loadFailed = true;
				Plugin.LogSource?.LogWarning(
					"HoMM3 Stronghold town build effects: BUILDTWN.wav load failed: " + failReason);
				return;
			}

			_buildClip.name = "HOMM3_BUILDTWN";
			Plugin.LogSource?.LogInfo("HoMM3 Stronghold town build effects: BUILDTWN.wav loaded.");
		}
		catch (Exception ex)
		{
			_loadFailed = true;
			Plugin.LogSource?.LogWarning("HoMM3 Stronghold town build effects: sound load failed: " + ex.Message);
		}
	}

	/// <summary>
	/// Golden Era IL2CPP lacks UnityWebRequestAudioModule DownloadHandlerAudioClip ctor.
	/// Load PCM16 mono/stereo WAV through AudioClip.Create instead.
	/// </summary>
	private static bool TryLoadPcmWavClip(string path, out AudioClip clip, out string failReason)
	{
		clip = null;
		failReason = null;
		var bytes = File.ReadAllBytes(path);
		if (bytes.Length < 44
		    || bytes[0] != (byte)'R' || bytes[1] != (byte)'I' || bytes[2] != (byte)'F' || bytes[3] != (byte)'F'
		    || bytes[8] != (byte)'W' || bytes[9] != (byte)'A' || bytes[10] != (byte)'V' || bytes[11] != (byte)'E')
		{
			failReason = "not a RIFF/WAVE file";
			return false;
		}

		var pos = 12;
		ushort audioFormat = 0;
		ushort channels = 0;
		var sampleRate = 0;
		ushort bitsPerSample = 0;
		byte[] pcm = null;
		while (pos + 8 <= bytes.Length)
		{
			var chunkId0 = bytes[pos];
			var chunkId1 = bytes[pos + 1];
			var chunkId2 = bytes[pos + 2];
			var chunkId3 = bytes[pos + 3];
			var chunkSize = bytes[pos + 4] | (bytes[pos + 5] << 8) | (bytes[pos + 6] << 16) | (bytes[pos + 7] << 24);
			var bodyStart = pos + 8;
			if (bodyStart + chunkSize > bytes.Length)
			{
				failReason = "truncated WAV chunk";
				return false;
			}

			if (chunkId0 == (byte)'f' && chunkId1 == (byte)'m' && chunkId2 == (byte)'t' && chunkId3 == (byte)' ')
			{
				if (chunkSize < 16)
				{
					failReason = "fmt chunk too small";
					return false;
				}
				audioFormat = (ushort)(bytes[bodyStart] | (bytes[bodyStart + 1] << 8));
				channels = (ushort)(bytes[bodyStart + 2] | (bytes[bodyStart + 3] << 8));
				sampleRate = bytes[bodyStart + 4] | (bytes[bodyStart + 5] << 8) | (bytes[bodyStart + 6] << 16) | (bytes[bodyStart + 7] << 24);
				bitsPerSample = (ushort)(bytes[bodyStart + 14] | (bytes[bodyStart + 15] << 8));
			}
			else if (chunkId0 == (byte)'d' && chunkId1 == (byte)'a' && chunkId2 == (byte)'t' && chunkId3 == (byte)'a')
			{
				pcm = new byte[chunkSize];
				Buffer.BlockCopy(bytes, bodyStart, pcm, 0, chunkSize);
			}

			pos = bodyStart + chunkSize + (chunkSize & 1);
		}

		if (audioFormat != 1)
		{
			failReason = "WAV must be PCM (format=1); got format=" + audioFormat
				+ " (convert ADPCM BUILDTWN.wav to PCM16 before deploy)";
			return false;
		}
		if (channels < 1 || channels > 2 || sampleRate <= 0 || bitsPerSample != 16 || pcm == null || pcm.Length < 2)
		{
			failReason = "unsupported PCM layout channels=" + channels + " rate=" + sampleRate + " bits=" + bitsPerSample;
			return false;
		}

		var sampleCount = pcm.Length / (2 * channels);
		if (sampleCount <= 0)
		{
			failReason = "empty PCM payload";
			return false;
		}

		var samples = new float[sampleCount * channels];
		for (var i = 0; i < sampleCount; i++)
		{
			for (var c = 0; c < channels; c++)
			{
				var offset = (i * channels + c) * 2;
				var sample = (short)(pcm[offset] | (pcm[offset + 1] << 8));
				samples[i * channels + c] = sample / 32768f;
			}
		}

		clip = AudioClip.Create("HOMM3_BUILDTWN", sampleCount, channels, sampleRate, false);
		if (clip == null || !clip)
		{
			failReason = "AudioClip.Create returned null";
			return false;
		}
		if (!clip.SetData(samples, 0))
		{
			failReason = "AudioClip.SetData failed";
			return false;
		}
		return true;
	}

	private static string ResolveBuildSoundPath()
	{
		var underPlugin = Path.GetFullPath(Path.Combine(Paths.PluginPath, "OfflineUnlockMod", "homm3_runtime_assets", "town_scene_refs", "homm3_stronghold", "audio", "BUILDTWN.wav"));
		return File.Exists(underPlugin) ? underPlugin : null;
	}
}

// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(BhCityUISession), nameof(BhCityUISession.tvw))]
internal static class Homm3StrongholdTownLayersBhCityOpenPatch
{
	private static void Postfix()
	{
		Homm3StrongholdTownLayers.SyncCurrentCityLayers();
	}
}

[HarmonyPatch]
internal static class Homm3StrongholdTownLayersBhCityHidePatch
{
	private static readonly MethodBase HideMethod = GameMember.FindFirstMethod(
		typeof(BhCityUISession),
		typeof(void),
		Type.EmptyTypes,
		GameSymbols.ReleaseTownUi.CitySessionHide);

	private static bool Prepare()
	{
		if (HideMethod != null)
			return true;

		Plugin.LogSource?.LogWarning("Homm3StrongholdTownLayers: city-session cleanup hook skipped because the pinned hide method is unavailable.");
		return false;
	}

	private static MethodBase TargetMethod()
	{
		return HideMethod;
	}

	private static void Postfix()
	{
		Homm3StrongholdTownLayers.ClearTownLayers();
	}
}

[HarmonyPatch(typeof(BhUIBuildingSession), nameof(BhUIBuildingSession.Init))]
internal static class Homm3StrongholdTownLayersBhBuildingInitPatch
{
	// Runtime-disabled: broad building-card/session lifecycle resync caused post-load town-layer churn; town layers sync on town entry instead.
	private static bool Prepare()
	{
		return false;
	}

	private static void Postfix()
	{
		Homm3StrongholdTownLayers.SyncCurrentCityLayers();
	}
}

[HarmonyPatch(typeof(BhUIBuildingSession), nameof(BhUIBuildingSession.OnHide))]
internal static class Homm3StrongholdTownLayersBhBuildingHidePatch
{
	// Runtime-disabled: broad building-card/session lifecycle resync caused post-load town-layer churn; town layers sync on town entry instead.
	private static bool Prepare()
	{
		return false;
	}

	private static void Postfix()
	{
		Homm3StrongholdTownLayers.SyncCurrentCityLayers();
	}
}

[HarmonyPatch(typeof(BhBuildingView), nameof(BhBuildingView.UpdateView))]
internal static class Homm3StrongholdTownLayersBhBuildingRefreshPatch
{
	// Runtime-disabled: broad building-card/session lifecycle resync caused post-load town-layer churn; town layers sync on town entry instead.
	private static bool Prepare()
	{
		return false;
	}

	private static void Postfix()
	{
		Homm3StrongholdTownLayers.SyncCurrentCityLayers();
	}
}

// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(Hex.Session.City.BhBuildingsManager), nameof(Hex.Session.City.BhBuildingsManager.baeq))]
internal static class Homm3StrongholdTownLayersBhBuildingsManagerRefreshPatch
{
	private static void Postfix()
	{
		Homm3StrongholdTownLayers.SyncCurrentCityLayers();
	}
}

[HarmonyPatch(typeof(Hex.Session.City.BhBuildingsManager), nameof(Hex.Session.City.BhBuildingsManager.OnDisable))]
internal static class Homm3StrongholdTownLayersBhBuildingsManagerHidePatch
{
	// Runtime-disabled: broad building-card/session lifecycle resync caused post-load town-layer churn; town layers sync on town entry instead.
	private static bool Prepare()
	{
		return false;
	}

	private static void Postfix()
	{
		Homm3StrongholdTownLayers.SyncCurrentCityLayers();
	}
}

[HarmonyPatch(typeof(Hex.Session.City.BhTownInput), nameof(Hex.Session.City.BhTownInput.ExitTownCmd))]
internal static class Homm3StrongholdTownLayersBhTownExitPatch
{
	private static void Postfix()
	{
		Homm3StrongholdTownLayers.ClearTownLayers();
	}
}
