using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Map;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Il2CppInterop.Runtime.Runtime;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

/// <summary>
/// Homecoming water traversal coordinator. The registered Homecoming water tile set
/// stays native terrain with a finite TileConfig penalty; heroes already on one of
/// those water tiles receive a one-turn native HeroStat landscape-penalty relief
/// before native Hero.OnStartDay; accepted native node-entry transitions swap between
/// boat and default hero visuals when terrain changes.
/// </summary>
internal static class Homm3HomecomingWaterTraversalBridge
{
	internal const string RetirementReason = "direct_state_node_and_move_point_bridge_retired";
	internal const string ActiveArchitecture = "native_tile_penalty_plus_hero_start_day_landscape_stat_and_boat_visual";
	internal const string BoatSpriteKey = "homecoming_water_boat";
	private const string LogPrefix = "HOMM3_HOMECOMING_WATER_TRAVERSAL";
	private const string BoatSpriteFolder = "homm3_boat_1";
	private const string BoatSpriteDir = "ab01_.dir";
	private const float WaterStartLandscapePenaltyPerBonusTarget = -1.0f;
	private const float FloatEpsilon = 0.0001f;

	private sealed class LandscapePenaltyOverlay
	{
		internal object Stat;
		internal string MemberName;
		internal float Delta;
	}

	private static readonly Dictionary<string, LandscapePenaltyOverlay> ActiveLandscapePenaltyOverlays = new();
	private static Type _worldOwnerComponentType;
	private static bool _registered;
	private static ManualLogSource _log;
	private static int _loggedApplied;
	private static int _loggedFailed;
	private static int _loggedTransitionApplied;
	private static int _loggedTransitionRestored;
	private static int _loggedTransitionSkipped;
	private static int _loggedNodeMiss;
	private static int _loggedBenefitApplied;
	private static int _loggedBenefitRemoved;
	private static int _loggedBenefitSkipped;

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException("Harmony was not initialized before Homecoming water traversal registration.");

		_log = log;
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.HomecomingBoatTravelWorldHero);
		if (type == null)
			throw new MissingMemberException("Homecoming water traversal world hero type not found.");

		var startDay = AccessTools.Method(type, GameSymbols.HomecomingBoatTravel.WorldHeroStartDayName, Type.EmptyTypes);
		if (startDay == null)
			throw new MissingMethodException(type.FullName, "OnStartDay()");

		var enterNode = FindInstanceMethod(type, GameSymbols.HomecomingBoatTravel.WorldHeroEnterNode, typeof(int));
		if (enterNode == null)
			throw new MissingMethodException(type.FullName, "accepted node transition " + GameSymbols.HomecomingBoatTravel.WorldHeroEnterNode.Id);

		var prefix = typeof(Homm3HomecomingWaterTraversalBridge).GetMethod(nameof(PrefixWorldHeroStartDay), BindingFlags.NonPublic | BindingFlags.Static);
		if (prefix == null)
			throw new MissingMethodException(nameof(Homm3HomecomingWaterTraversalBridge), nameof(PrefixWorldHeroStartDay));
		var enterNodePostfix = typeof(Homm3HomecomingWaterTraversalBridge).GetMethod(nameof(PostfixWorldHeroEnterNode), BindingFlags.NonPublic | BindingFlags.Static);
		if (enterNodePostfix == null)
			throw new MissingMethodException(nameof(Homm3HomecomingWaterTraversalBridge), nameof(PostfixWorldHeroEnterNode));
		harmony.Patch(startDay, prefix: new HarmonyMethod(prefix));
		harmony.Patch(enterNode, postfix: new HarmonyMethod(enterNodePostfix));
		_registered = true;
		log?.LogInfo(LogPrefix + " registered hero-start-day native HeroStat relief and enter-node boat visual architecture=" + ActiveArchitecture + ".");
	}

	internal static bool TryApplyHeroWaterVisualOverride(GameObject root, string source, params object[] heroStateCandidates)
	{
		if (!root)
			return false;
		if (!TryResolveHeroNode(heroStateCandidates, out var node, out var nodeSource))
		{
			LogNodeMiss(source);
			return false;
		}
		if (!TryReadCurrentMapData(out var mapData, out var fileMapName, out var reason))
			return false;
		if (!HomecomingMapProfile.TryResolve(fileMapName, mapData, out var profile))
			return false;
		if (!profile.ContainsRuntimeWaterNode(node))
			return false;
		if (!TryReadOceanCell(mapData, node, out var ocean, out reason))
			return false;
		if (!ocean)
			return false;

		var spriteRoot = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "homm3_boat_map_sprites", BoatSpriteFolder, BoatSpriteDir);
		var applied = Homm3HeroMapSpriteHook.TryApplyExternalSpriteOverride(
			root,
			"homecoming-water-node-" + node.ToString(CultureInfo.InvariantCulture),
			BoatSpriteKey,
			spriteRoot,
			Plugin.LogSource,
			LogPrefix);
		if (applied)
		{
			if (_loggedApplied < 20)
			{
				_loggedApplied++;
				Plugin.LogSource?.LogInfo(LogPrefix
					+ " boat_visual_applied source=" + (source ?? "<unknown>")
					+ " node=" + node.ToString(CultureInfo.InvariantCulture)
					+ " nodeSource=" + nodeSource
					+ " root='" + (root.name ?? "?") + "'"
					+ " spriteKey=" + BoatSpriteKey
					+ " architecture=" + ActiveArchitecture);
			}
		}
		else if (_loggedFailed < 20)
		{
			_loggedFailed++;
			Plugin.LogSource?.LogWarning(LogPrefix
				+ " failed closed: water hero boat visual could not be applied source=" + (source ?? "<unknown>")
				+ " node=" + node.ToString(CultureInfo.InvariantCulture)
				+ " spriteRoot='" + spriteRoot + "'.");
		}
		return true;
	}

	private static void PrefixWorldHeroStartDay(object __instance)
	{
		try
		{
			ApplyWaterStartBenefitsForHero(__instance);
		}
		catch (Exception ex)
		{
			LogBenefitSkip("turn-start relief failed closed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static void PostfixWorldHeroEnterNode(object __instance, object __result, object[] __args)
	{
		try
		{
			if (!TryReadEnterNodeAccepted(__result, out var accepted))
			{
				LogTransitionSkip("enter-node result unresolved");
				return;
			}
			if (!accepted)
				return;
			if (__args == null || __args.Length == 0 || !TryConvertInt(__args[0], out var node))
			{
				LogTransitionSkip("enter-node target node unresolved");
				return;
			}
			RefreshHeroWaterVisualForTargetNode(__instance, node, "enter-node");
		}
		catch (Exception ex)
		{
			LogTransitionSkip("enter-node visual refresh failed closed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static void RefreshHeroWaterVisualForTargetNode(object worldHero, int node, string source)
	{
		if (worldHero == null)
		{
			LogTransitionSkip("missing world hero for " + source);
			return;
		}
		if (!TryReadCurrentMapData(out var mapData, out var fileMapName, out var mapReason))
		{
			LogTransitionSkip("map unavailable for " + source + ": " + mapReason);
			return;
		}
		if (!HomecomingMapProfile.TryResolve(fileMapName, mapData, out var profile))
			return;
		var ocean = false;
		var insideRuntimeWaterScope = profile.ContainsRuntimeWaterNode(node);
		if (insideRuntimeWaterScope && !TryReadOceanCell(mapData, node, out ocean, out var tileReason))
		{
			LogTransitionSkip("ocean cell read failed for " + source + ": " + tileReason);
			return;
		}

		var logicHero = TryReadFirstMember(worldHero, GameSymbols.HomecomingBoatTravel.WorldHeroLogicHeroMembers);
		var dataHero = ResolveDataHeroFromSideEntry(worldHero);

		if (insideRuntimeWaterScope && ocean)
		{
			var spriteRoot = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "homm3_boat_map_sprites", BoatSpriteFolder, BoatSpriteDir);
			var applied = Homm3HeroMapSpriteHook.TryApplyExternalSpriteOverrideFromHeroState(
				"homecoming-water-node-" + node.ToString(CultureInfo.InvariantCulture),
				BoatSpriteKey,
				spriteRoot,
				Plugin.LogSource,
				LogPrefix,
				worldHero,
				logicHero,
				dataHero);
			if (applied && _loggedTransitionApplied < 24)
			{
				_loggedTransitionApplied++;
				Plugin.LogSource?.LogInfo(LogPrefix
					+ " boat_visual_transition_applied source=" + (source ?? "?")
					+ " node=" + node.ToString(CultureInfo.InvariantCulture)
					+ " ocean=" + ocean.ToString()
					+ " architecture=" + ActiveArchitecture + ".");
			}
			else if (!applied)
			{
				LogTransitionSkip("boat visual apply failed for node=" + node.ToString(CultureInfo.InvariantCulture));
			}
			return;
		}

		var restored = Homm3HeroMapSpriteHook.TryRestoreDefaultSpriteOverrideFromHeroState("water-exit:" + (source ?? "?"), worldHero, logicHero, dataHero);
		if (restored && _loggedTransitionRestored < 24)
		{
			_loggedTransitionRestored++;
			Plugin.LogSource?.LogInfo(LogPrefix
				+ " boat_visual_transition_restored source=" + (source ?? "?")
				+ " node=" + node.ToString(CultureInfo.InvariantCulture)
				+ " ocean=" + ocean.ToString()
				+ " architecture=" + ActiveArchitecture + ".");
		}
		else if (!restored)
		{
			LogTransitionSkip("default visual restore failed for node=" + node.ToString(CultureInfo.InvariantCulture));
		}
	}

	private static bool TryReadEnterNodeAccepted(object result, out bool accepted)
	{
		accepted = false;
		if (!TryConvertInt(result, out var raw))
			return false;
		accepted = raw == 0;
		return true;
	}

	private static bool TryConvertInt(object value, out int result)
	{
		result = 0;
		if (value == null)
			return false;
		try
		{
			result = Convert.ToInt32(value, CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static void LogTransitionSkip(string message)
	{
		if (_loggedTransitionSkipped >= 20)
			return;
		_loggedTransitionSkipped++;
		_log?.LogInfo(LogPrefix + " water_visual_transition_skip " + message);
	}

	private static void ApplyWaterStartBenefitsForHero(object worldHero)
	{
		if (worldHero == null)
		{
			LogBenefitSkip("missing world hero");
			return;
		}

		var dataHero = ResolveDataHeroFromSideEntry(worldHero);
		if (dataHero == null)
		{
			LogBenefitSkip("world hero did not resolve to Data.Hero");
			return;
		}

		var heroKey = GetStableObjectKey(dataHero);
		var removed = TryRemoveLandscapePenaltyOverlay(heroKey, "hero-start-day-refresh");
		var mapAvailable = TryReadCurrentMapData(out var mapData, out var fileMapName, out var mapReason);
		HomecomingMapProfile profile = null;
		var isHomecomingMap = mapAvailable && HomecomingMapProfile.TryResolve(fileMapName, mapData, out profile);
		if (!isHomecomingMap)
		{
			if (!mapAvailable && _loggedBenefitSkipped < 8)
			{
				_loggedBenefitSkipped++;
				_log?.LogInfo(LogPrefix + " water_start_relief skipped hero=" + heroKey + " reason=" + mapReason + ".");
			}
			return;
		}

		if (!TryResolveHeroNodeFromCandidate(dataHero, out var node, out var nodeSource))
		{
			LogBenefitSkip("hero node unresolved for turn-start relief");
			return;
		}
		if (!profile.ContainsRuntimeWaterNode(node))
		{
			LogBenefitSkip("turn-start node outside Homecoming water runtime profile " + profile.Id);
			return;
		}
		if (!TryReadOceanCell(mapData, node, out var ocean, out var tileReason))
		{
			LogBenefitSkip("ocean cell read failed for turn-start relief: " + tileReason);
			return;
		}

		var applied = false;
		if (ocean)
			applied = TryApplyWaterStartLandscapePenaltyBenefit(dataHero, heroKey, node, nodeSource, -1);

		if ((applied || removed) && _loggedBenefitApplied < 24)
		{
			_loggedBenefitApplied++;
			_log?.LogInfo(LogPrefix
				+ " water_start_relief_refresh hero=" + heroKey
				+ " map=" + (fileMapName ?? "?")
				+ " node=" + node.ToString(CultureInfo.InvariantCulture)
				+ " nodeSource=" + nodeSource
				+ " ocean=" + ocean.ToString()
				+ " applied=" + applied.ToString()
				+ " removed=" + removed.ToString()
				+ " architecture=" + ActiveArchitecture + ".");
		}
	}

	private static bool TryApplyWaterStartLandscapePenaltyBenefit(object dataHero, string heroKey, int node, string nodeSource, int currentDay)
	{
		var stats = TryReadFirstMember(dataHero, GameSymbols.HomecomingBoatTravel.DataHeroAdditionalStatsMembers);
		if (stats == null)
		{
			LogBenefitSkip("Data.Hero.additionalStats unresolved for water-start relief");
			return false;
		}
		if (!TryReadFloatMember(stats, GameSymbols.HomecomingBoatTravel.HeroStatLandscapePenaltyPerBonusMembers, out var current, out var memberName))
		{
			LogBenefitSkip("HeroStat.landscapePenaltyPerBonus unresolved for water-start relief");
			return false;
		}

		var delta = WaterStartLandscapePenaltyPerBonusTarget - current;
		if (delta >= -FloatEpsilon)
			return false;
		var target = current + delta;
		if (!TryWriteFloatMember(stats, memberName, target))
		{
			LogBenefitSkip("HeroStat.landscapePenaltyPerBonus write failed for water-start relief");
			return false;
		}

		ActiveLandscapePenaltyOverlays[heroKey] = new LandscapePenaltyOverlay
		{
			Stat = stats,
			MemberName = memberName,
			Delta = delta,
		};
		if (_loggedBenefitApplied < 24)
		{
			_log?.LogInfo(LogPrefix
				+ " water_start_relief_applied node=" + node.ToString(CultureInfo.InvariantCulture)
				+ " nodeSource=" + nodeSource
				+ " day=" + (currentDay >= 0 ? currentDay.ToString(CultureInfo.InvariantCulture) : "?")
				+ " member=" + memberName
				+ " from=" + current.ToString(CultureInfo.InvariantCulture)
				+ " to=" + target.ToString(CultureInfo.InvariantCulture)
				+ ".");
		}
		return true;
	}

	private static bool TryRemoveLandscapePenaltyOverlay(string heroKey, string source)
	{
		if (string.IsNullOrWhiteSpace(heroKey) || !ActiveLandscapePenaltyOverlays.TryGetValue(heroKey, out var overlay))
			return false;
		ActiveLandscapePenaltyOverlays.Remove(heroKey);
		if (overlay?.Stat == null || string.IsNullOrWhiteSpace(overlay.MemberName))
			return false;
		if (!TryReadFloatMember(overlay.Stat, new[] { overlay.MemberName }, out var current, out var memberName))
			return false;
		var restored = current - overlay.Delta;
		if (!TryWriteFloatMember(overlay.Stat, memberName, restored))
			return false;
		if (_loggedBenefitRemoved < 24)
		{
			_loggedBenefitRemoved++;
			_log?.LogInfo(LogPrefix
				+ " water_start_relief_removed source=" + source
				+ " member=" + memberName
				+ " from=" + current.ToString(CultureInfo.InvariantCulture)
				+ " to=" + restored.ToString(CultureInfo.InvariantCulture)
				+ ".");
		}
		return true;
	}

	private static void LogNodeMiss(string source)
	{
		if (_loggedNodeMiss >= 8)
			return;
		_loggedNodeMiss++;
		Plugin.LogSource?.LogInfo(LogPrefix + " water_visual_probe node_unresolved source=" + (source ?? "<unknown>") + "; default hero visual path remains active.");
	}

	private static void LogBenefitSkip(string message)
	{
		if (_loggedBenefitSkipped >= 20)
			return;
		_loggedBenefitSkipped++;
		_log?.LogInfo(LogPrefix + " water_start_relief_skip " + message);
	}

	private static bool TryResolveHeroNode(object[] candidates, out int node, out string source)
	{
		node = -1;
		source = null;
		foreach (var candidate in candidates ?? Array.Empty<object>())
		{
			if (TryResolveHeroNodeFromCandidate(candidate, out node, out source))
				return true;
		}
		return false;
	}

	private static bool TryResolveHeroNodeFromCandidate(object candidate, out int node, out string source)
	{
		node = -1;
		source = null;
		if (candidate == null)
			return false;
		if (TryReadIntMember(candidate, GameSymbols.HomecomingBoatTravel.DataHeroNodeMembers, out node))
		{
			source = "direct-data-hero-node";
			return true;
		}
		var logicHero = TryReadFirstMember(candidate, GameSymbols.HeroMap.SessionHeroLogicFields)
		                ?? TryReadFirstMember(candidate, GameSymbols.HomecomingBoatTravel.WorldHeroLogicHeroMembers);
		if (logicHero != null && TryResolveHeroNodeFromLogicHero(logicHero, out node, out source))
			return true;
		if (TryResolveHeroNodeFromLogicHero(candidate, out node, out source))
			return true;
		return false;
	}

	private static bool TryResolveHeroNodeFromLogicHero(object logicHero, out int node, out string source)
	{
		node = -1;
		source = null;
		if (logicHero == null)
			return false;
		var dataHero = TryReadFirstMember(logicHero, GameSymbols.HomecomingBoatTravel.LogicHeroDataHeroMembers);
		if (dataHero == null)
			return false;
		if (!TryReadIntMember(dataHero, GameSymbols.HomecomingBoatTravel.DataHeroNodeMembers, out node))
			return false;
		source = "logic-hero-data-node";
		return true;
	}

	private static object ResolveDataHeroFromSideEntry(object entry)
	{
		if (entry == null)
			return null;
		if (LooksLikeDataHero(entry))
			return entry;
		var directDataHero = TryReadFirstMember(entry, GameSymbols.HomecomingBoatTravel.LogicHeroDataHeroMembers);
		if (LooksLikeDataHero(directDataHero))
			return directDataHero;
		var logicHero = TryReadFirstMember(entry, GameSymbols.HomecomingBoatTravel.WorldHeroLogicHeroMembers)
		                ?? TryReadFirstMember(entry, GameSymbols.HeroMap.SessionHeroLogicFields);
		if (logicHero == null)
			return null;
		var dataHero = TryReadFirstMember(logicHero, GameSymbols.HomecomingBoatTravel.LogicHeroDataHeroMembers);
		return LooksLikeDataHero(dataHero) ? dataHero : null;
	}

	private static bool LooksLikeDataHero(object value)
	{
		return value != null
		       && (TryReadIntMember(value, GameSymbols.HomecomingBoatTravel.DataHeroNodeMembers, out _)
		           || TryReadFirstMember(value, GameSymbols.HomecomingBoatTravel.DataHeroAdditionalStatsMembers) != null);
	}

	private static bool TryReadCurrentMapData(out object mapData, out string fileMapName, out string reason)
	{
		mapData = null;
		fileMapName = null;
		reason = null;
		for (var i = 0; i < SceneManager.sceneCount; i++)
		{
			var scene = SceneManager.GetSceneAt(i);
			if (!scene.IsValid() || !scene.isLoaded)
				continue;
			GameObject[] roots;
			try { roots = scene.GetRootGameObjects(); }
			catch (Exception ex)
			{
				reason = "scene_root_read_failed " + ex.Message;
				continue;
			}
			foreach (var root in roots)
			{
				if (!root || !string.Equals(root.name, GameSymbols.HomecomingBoatTravel.WorldRootName, StringComparison.Ordinal))
					continue;
				if (!TryGetMapFromWorldRoot(root, out var mapInstance, out reason))
					continue;
				if (!TryGetMapData(mapInstance, out mapData))
				{
					reason = "map_data_unresolved";
					continue;
				}
				fileMapName = ReadMapDataString(mapData, 0) ?? ReadMapDataString(mapInstance, 0);
				if (string.IsNullOrWhiteSpace(fileMapName))
				{
					reason = "fileMapName_unresolved";
					continue;
				}
				return true;
			}
		}
		if (reason == null)
			reason = "world_root_not_found";
		return false;
	}

	private static bool TryGetMapFromWorldRoot(GameObject worldRoot, out object mapInstance, out string reason)
	{
		mapInstance = null;
		reason = null;
		var worldType = ResolveWorldOwnerType();
		if (worldType == null)
		{
			reason = "world_owner_type_unresolved";
			return false;
		}
		Component worldComponent;
		try { worldComponent = worldRoot.GetComponent(Il2CppType.From(worldType))?.TryCast<Component>(); }
		catch (Exception ex)
		{
			reason = "world_component_lookup_failed " + ex.Message;
			return false;
		}
		if (!worldComponent)
		{
			reason = "world_component_missing " + (worldType.FullName ?? worldType.Name);
			return false;
		}
		var worldOwner = TryWrapIl2CppObjectAs(worldComponent, worldType) ?? worldComponent;
		var map = InvokeFirstNoArg(worldOwner, typeof(Map), GameSymbols.HomecomingBoatTravel.WorldMap);
		if (map == null)
		{
			reason = "world_map_getter_unresolved " + (worldType.FullName ?? worldType.Name);
			return false;
		}
		mapInstance = map;
		return true;
	}

	private static Type ResolveWorldOwnerType()
	{
		if (_worldOwnerComponentType != null)
			return _worldOwnerComponentType;
		_worldOwnerComponentType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.HomecomingBoatTravelWorldOwner);
		return _worldOwnerComponentType;
	}

	private static bool TryGetMapData(object value, out object mapData)
	{
		mapData = null;
		if (value == null)
			return false;
		if (value is MapData)
		{
			mapData = value;
			return true;
		}
		var direct = InvokeFirstNoArg(value, typeof(MapData), GameSymbols.HomecomingBoatTravel.MapData);
		if (direct == null)
			return false;
		mapData = direct;
		return true;
	}

	private static string ReadMapDataString(object value, int depth)
	{
		if (value == null || depth > 4)
			return null;
		foreach (var name in GameSymbols.HomecomingBoatTravel.MapDataFileNameMembers)
		{
			var direct = TryReadMember(value, name) as string;
			if (!string.IsNullOrWhiteSpace(direct))
				return direct;
		}
		if (TryGetMapData(value, out var mapData) && !ReferenceEquals(mapData, value))
		{
			var fromMapData = ReadMapDataString(mapData, depth + 1);
			if (!string.IsNullOrWhiteSpace(fromMapData))
				return fromMapData;
		}
		foreach (var nestedName in new[] { "data", "mapData", "sessionData", "map" })
		{
			var nested = TryReadMember(value, nestedName);
			if (nested == null || ReferenceEquals(nested, value) || nested is string)
				continue;
			var fromNested = ReadMapDataString(nested, depth + 1);
			if (!string.IsNullOrWhiteSpace(fromNested))
				return fromNested;
		}
		return null;
	}

	private static bool TryReadOceanCell(object mapData, int node, out bool ocean, out string reason)
	{
		ocean = false;
		if (!TryReadMapByte(mapData, GameSymbols.HomecomingBoatTravel.MapDataTilesMapMembers, "tilesMap", node, out var tile, out reason))
			return false;
		if (!TryReadMapByte(mapData, GameSymbols.HomecomingBoatTravel.MapDataWaterMapMembers, "waterMap", node, out var water, out reason))
			return false;
		if (!TryReadMapByte(mapData, GameSymbols.HomecomingBoatTravel.MapDataLevelsMapMembers, "levelsMap", node, out var level, out reason))
			return false;
		ocean = GameSymbols.HomecomingBoatTravel.IsOceanCell(tile, water, level);
		return true;
	}

	private static bool TryReadMapByte(object mapData, string[] members, string arrayName, int node, out int tile, out string reason)
	{
		tile = 0;
		reason = null;
		if (node < 0)
		{
			reason = "negative_node";
			return false;
		}
		var raw = TryReadFirstMember(mapData, members);
		if (raw == null)
		{
			reason = arrayName + "_member_missing";
			return false;
		}
		if (raw is byte[] bytes)
		{
			if (node >= bytes.Length)
			{
				reason = "node_out_of_range length=" + bytes.Length.ToString(CultureInfo.InvariantCulture);
				return false;
			}
			tile = bytes[node];
			return true;
		}
		if (raw is Il2CppStructArray<byte> il2CppBytes)
		{
			if (node >= il2CppBytes.Length)
			{
				reason = "node_out_of_range length=" + il2CppBytes.Length.ToString(CultureInfo.InvariantCulture);
				return false;
			}
			tile = il2CppBytes[node];
			return true;
		}
		if (raw is Il2CppStructArray<sbyte> il2CppSignedBytes)
		{
			if (node >= il2CppSignedBytes.Length)
			{
				reason = "node_out_of_range length=" + il2CppSignedBytes.Length.ToString(CultureInfo.InvariantCulture);
				return false;
			}
			tile = il2CppSignedBytes[node];
			return true;
		}
		if (raw is Array array)
		{
			if (node >= array.Length)
			{
				reason = "node_out_of_range length=" + array.Length.ToString(CultureInfo.InvariantCulture);
				return false;
			}
			try
			{
				tile = Convert.ToInt32(array.GetValue(node), CultureInfo.InvariantCulture);
				return true;
			}
			catch (Exception ex)
			{
				reason = "array_value_convert_failed " + ex.Message;
				return false;
			}
		}
		reason = "unsupported_" + arrayName + "_type " + raw.GetType().FullName;
		return false;
	}

	private static MethodInfo FindInstanceMethod(Type type, GameSymbols.MethodSymbol symbol, params Type[] parameterTypes)
	{
		if (type == null || symbol.NameHints == null)
			return null;
		var expectedParameters = parameterTypes ?? Type.EmptyTypes;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var cursor = type; cursor != null; cursor = cursor.BaseType)
		{
			foreach (var name in symbol.NameHints)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					var method = cursor.GetMethod(name, flags, null, expectedParameters, null);
					if (method != null)
						return method;
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private static object InvokeFirstNoArg(object obj, Type expectedReturnType, GameSymbols.MethodSymbol symbol)
	{
		if (obj == null || expectedReturnType == null || symbol.NameHints == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = obj.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in symbol.NameHints)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				MethodInfo method;
				try { method = type.GetMethod(name, flags, null, Type.EmptyTypes, null); }
				catch { method = null; }
				if (method == null || !expectedReturnType.IsAssignableFrom(method.ReturnType))
					continue;
				try { return method.Invoke(obj, null); }
				catch { return null; }
			}
		}
		return null;
	}

	private static object TryWrapIl2CppObjectAs(object value, Type expectedType)
	{
		if (value == null || expectedType == null || !typeof(Il2CppObjectBase).IsAssignableFrom(expectedType))
			return null;
		if (expectedType.IsInstanceOfType(value))
			return value;
		if (value is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		try
		{
			TryInitializeIl2CppType(expectedType);
			var method = typeof(Il2CppObjectPool).GetMethod("Get", BindingFlags.Public | BindingFlags.Static, null, new[] { typeof(IntPtr) }, null);
			if (method == null || !method.IsGenericMethodDefinition)
				return null;
			return method.MakeGenericMethod(expectedType).Invoke(null, new object[] { il2Cpp.Pointer });
		}
		catch { return null; }
	}

	private static void TryInitializeIl2CppType(Type managedType)
	{
		if (managedType == null)
			return;
		try
		{
			var classPointerStore = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			RuntimeHelpers.RunClassConstructor(classPointerStore.TypeHandle);
		}
		catch { }
	}

	private static Type GetTypeByName(string name)
	{
		var type = AccessTools.TypeByName(name) ?? AccessTools.TypeByName("Hex." + name);
		if (type != null)
			return type;
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			try { type = assembly.GetType(name, false) ?? assembly.GetType("Hex." + name, false); }
			catch { type = null; }
			if (type != null)
				return type;
		}
		return null;
	}

	private static MemberInfo FindReadableMember(Type type, Type expectedReturnType, string[] names)
	{
		if (type == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var cursor = type; cursor != null; cursor = cursor.BaseType)
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var field = cursor.GetField(name, flags);
				if (field != null && (expectedReturnType == null || expectedReturnType.IsAssignableFrom(field.FieldType)))
					return field;
				var property = cursor.GetProperty(name, flags);
				if (property?.GetMethod != null && property.GetIndexParameters().Length == 0 && (expectedReturnType == null || expectedReturnType.IsAssignableFrom(property.PropertyType)))
					return property;
				var method = cursor.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && (expectedReturnType == null || expectedReturnType.IsAssignableFrom(method.ReturnType)))
					return method;
			}
		}
		return null;
	}

	private static object GetMemberValue(object instance, MemberInfo member)
	{
		if (instance == null || member == null)
			return null;
		try
		{
			return member switch
			{
				FieldInfo field => field.GetValue(instance),
				PropertyInfo property when property.GetIndexParameters().Length == 0 => property.GetValue(instance, null),
				MethodInfo method when method.GetParameters().Length == 0 => method.Invoke(instance, null),
				_ => null,
			};
		}
		catch { return null; }
	}

	private static string GetStableObjectKey(object value)
	{
		if (value is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero)
			return "il2cpp:" + il2Cpp.Pointer.ToString("x");
		return value == null ? "null" : "managed:" + RuntimeHelpers.GetHashCode(value).ToString(CultureInfo.InvariantCulture);
	}

	private static bool TryReadIntMember(object instance, string[] names, out int value)
	{
		value = 0;
		foreach (var name in names ?? Array.Empty<string>())
		{
			var raw = TryReadMember(instance, name);
			if (raw == null)
				continue;
			try
			{
				value = Convert.ToInt32(raw, CultureInfo.InvariantCulture);
				return true;
			}
			catch { }
		}
		return false;
	}

	private static bool TryReadFloatMember(object instance, string[] names, out float value, out string memberName)
	{
		value = 0f;
		memberName = null;
		foreach (var name in names ?? Array.Empty<string>())
		{
			var raw = TryReadMember(instance, name);
			if (raw == null)
				continue;
			try
			{
				value = Convert.ToSingle(raw, CultureInfo.InvariantCulture);
				memberName = name;
				return true;
			}
			catch { }
		}
		return false;
	}

	private static bool TryWriteFloatMember(object instance, string name, float value)
	{
		if (instance == null || string.IsNullOrWhiteSpace(name))
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = instance.GetType(); type != null; type = type.BaseType)
		{
			try
			{
				var field = type.GetField(name, flags);
				if (field != null && field.FieldType == typeof(float))
				{
					field.SetValue(instance, value);
					return true;
				}
				var property = type.GetProperty(name, flags);
				if (property?.SetMethod != null && property.PropertyType == typeof(float) && property.GetIndexParameters().Length == 0)
				{
					property.SetValue(instance, value, null);
					return true;
				}
			}
			catch { }
		}
		return false;
	}

	private static object TryReadFirstMember(object instance, string[] names)
	{
		foreach (var name in names ?? Array.Empty<string>())
		{
			var value = TryReadMember(instance, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryReadMember(object instance, string name)
	{
		if (instance == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = instance.GetType(); type != null; type = type.BaseType)
		{
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(instance);
				var property = type.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(instance, null);
				var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null)
					return method.Invoke(instance, null);
			}
			catch { }
		}
		return null;
	}
}
