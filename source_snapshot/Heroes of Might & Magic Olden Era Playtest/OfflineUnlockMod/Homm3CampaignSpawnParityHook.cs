using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Map;
using Hex.Session.Data;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

/// <summary>
/// StoryHub campaign spawn parity for HoMM3 ports.
///
/// Native <c>CreateCampaignSpawnsForSide</c> always leaves Bot <c>campaignSpawns.heroSid</c>
/// empty, so <c>CreateHeroOnCampaignSpawn</c> deletes placed hero-spawners without creating
/// heroes. Native <c>CreateCityOnCampaignSpawn</c> also replaces the placed city SID with
/// <c>Side.fractionConfig.city</c>, which paints Terraneus as Inferno when the Bot side was
/// forced to Inferno for Xyron. CreateCity likewise spawns the live city GO from
/// <c>fractionConfig.city</c> even when MapObjectInfo already carried a land-on SID.
///
/// This hook:
/// 1. Fills empty campaign heroSid from <c>propHeroes</c> for the same object id.
/// 2. Indexes placed city SIDs from <c>MapData.objects</c> (sid+ids rows) before CreateCity,
///    because live Map.ById lookup via SpawnsCreator statics is unreliable on Golden Era.
/// 3. Restores those SIDs onto MapObjectInfo and Side.fractionConfig.city for the CreateCity call.
/// </summary>
internal static class Homm3CampaignSpawnParityHook
{
	private const string LogPrefix = "HoMM3 campaign spawn parity";
	private static readonly ConcurrentDictionary<int, string> PendingCitySids = new();
	private static readonly ConcurrentDictionary<int, string> PlacedCitySidsById = new();
	private static readonly ConcurrentDictionary<int, string> PendingFractionCityRestores = new();
	private static readonly HashSet<string> LoggedHeroFills = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedCityPreserves = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedCreateCityDiag = new(StringComparer.Ordinal);

	private static bool _registered;
	private static ManualLogSource _log;
	private static Type _spawnsCreatorType;
	private static bool _loggedResolveFailure;
	private static bool _loggedFractionCityFieldMiss;
	private static bool _loggedMapDataIndex;
	private static string _indexedMapDataName;

	internal static bool IsRegistered => _registered;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;

		_log = log;
		try
		{
			_spawnsCreatorType = GameMember.FindType(
				GameSymbols.CampaignSpawnParity.SpawnsCreatorTypeId,
				GameSymbols.CampaignSpawnParity.SpawnsCreatorTypeHint,
				shapeFallback: ResolveSpawnsCreatorByShape);
			if (_spawnsCreatorType == null)
				throw new InvalidOperationException("SpawnsCreator type was not resolved.");

			var campaignSpawnMethods = FindCampaignSpawnMethods(_spawnsCreatorType);
			var createCityMethods = FindCreateCityMethods(_spawnsCreatorType);
			if (campaignSpawnMethods.Count == 0)
				throw new InvalidOperationException("no Create*OnCampaignSpawn(Side,string,PropSpawn,HeroArmy) methods found.");
			if (createCityMethods.Count == 0)
				throw new InvalidOperationException("no CreateCity(Side,MapObjectInfo) methods found.");

			var campaignPrefix = new HarmonyMethod(typeof(Homm3CampaignSpawnParityHook), nameof(PrefixCampaignSpawn));
			foreach (var method in campaignSpawnMethods)
				harmony.Patch(method, prefix: campaignPrefix);

			var cityPrefix = new HarmonyMethod(typeof(Homm3CampaignSpawnParityHook), nameof(PrefixCreateCity));
			var cityPostfix = new HarmonyMethod(typeof(Homm3CampaignSpawnParityHook), nameof(PostfixCreateCity));
			foreach (var method in createCityMethods)
				harmony.Patch(method, prefix: cityPrefix, postfix: cityPostfix);

			_registered = true;
			_log?.LogInfo(
				LogPrefix
				+ ": registered campaignSpawnPatches="
				+ campaignSpawnMethods.Count
				+ " createCityPatches="
				+ createCityMethods.Count
				+ " (prefix+postfix fractionConfig.city) on "
				+ _spawnsCreatorType.Name
				+ ".");
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + ": registration failed closed: " + ex);
			throw;
		}
	}

	private static Type ResolveSpawnsCreatorByShape()
	{
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try { types = assembly.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types; }
			catch { continue; }
			if (types == null)
				continue;
			foreach (var type in types)
			{
				if (type == null || !type.IsClass)
					continue;
				// Prefer static classes (abstract+sealed), but accept any type that owns the spawn methods.
				if (FindCampaignSpawnMethods(type).Count > 0 && FindCreateCityMethods(type).Count > 0)
					return type;
			}
		}
		return null;
	}

	private static List<MethodInfo> FindCampaignSpawnMethods(Type spawnsCreatorType)
	{
		var matches = new List<MethodInfo>();
		if (spawnsCreatorType == null)
			return matches;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly;
		MethodInfo[] methods;
		try { methods = spawnsCreatorType.GetMethods(flags); }
		catch { return matches; }
		foreach (var method in methods)
		{
			if (method.ReturnType != typeof(void))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != 4)
				continue;
			if (!TypeNameMatches(parameters[0].ParameterType, "Side")
			    || parameters[1].ParameterType != typeof(string)
			    || !TypeNameMatches(parameters[2].ParameterType, "PropSpawn")
			    || !TypeNameMatches(parameters[3].ParameterType, "HeroArmy"))
			{
				continue;
			}
			matches.Add(method);
		}
		matches.Sort((a, b) => string.CompareOrdinal(a.Name, b.Name));
		return matches;
	}

	private static List<MethodInfo> FindCreateCityMethods(Type spawnsCreatorType)
	{
		var matches = new List<MethodInfo>();
		if (spawnsCreatorType == null)
			return matches;

		var exactTypes = new[] { typeof(Side), typeof(MapObjectInfo) };
		var named = GameMember.FindMethodsByNames(
			spawnsCreatorType,
			exactTypes,
			GameSymbols.CustomDwellingRandomHire.HireMapObjectSpawners);
		if (named.Length > 0)
			return new List<MethodInfo>(named);

		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly;
		MethodInfo[] methods;
		try { methods = spawnsCreatorType.GetMethods(flags); }
		catch { return matches; }
		foreach (var method in methods)
		{
			if (method.ReturnType != typeof(void))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != 2)
				continue;
			if (!TypeNameMatches(parameters[0].ParameterType, "Side")
			    || !TypeNameMatches(parameters[1].ParameterType, "MapObjectInfo"))
			{
				continue;
			}
			matches.Add(method);
		}
		matches.Sort((a, b) => string.CompareOrdinal(a.Name, b.Name));
		return matches;
	}

	private static bool TypeNameMatches(Type type, string expectedName)
	{
		return type != null && string.Equals(type.Name, expectedName, StringComparison.Ordinal);
	}

	private static void PrefixCampaignSpawn(MethodBase __originalMethod, Side __0, ref string __1, PropSpawn __2, object __3)
	{
		try
		{
			if (__2 == null)
				return;

			var objectId = DeobfInteropCompat.GetIntMember(__2, "id", "field_Public_Int32_0");
			if (objectId <= 0)
				return;
			TryStashPlacedCitySid(objectId);

			if (!string.IsNullOrEmpty(__1))
				return;

			if (!TryResolvePropHeroSid(objectId, out var heroSid))
				return;

			__1 = heroSid;
			var key = objectId + "|" + heroSid + "|" + (__originalMethod?.Name ?? "?");
			if (LoggedHeroFills.Add(key))
			{
				_log?.LogInfo(
					LogPrefix
					+ ": filled empty campaign heroSid from propHeroes id="
					+ objectId
					+ " heroSid="
					+ heroSid
					+ " via "
					+ (__originalMethod?.Name ?? "?")
					+ ".");
			}
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + ": PrefixCampaignSpawn failed closed: " + ex.Message);
		}
	}

	private static void PrefixCreateCity(MethodBase __originalMethod, Side __0, ref MapObjectInfo __1)
	{
		try
		{
			var objectId = DeobfInteropCompat.GetMapObjectInfoId(__1);
			DeobfInteropCompat.TryGetMapObjectInfoSid(__1, out var currentSid);

			// Same Side+MapObjectInfo shape is shared with hire/dwelling spawners — ignore non-cities.
			if (!LooksLikeCitySid(currentSid) && !LooksLikeCitySid(PeekPendingOrMapCitySid(objectId)))
				return;

			// Campaign-spawn stash is best-effort. Player towns often hit CreateCity without
			// PrefixCampaignSpawn stashing; prefer MapData.objects index, then live map object.
			var placedSource = "pending";
			if (!PendingCitySids.TryRemove(objectId, out var placedSid) || string.IsNullOrWhiteSpace(placedSid))
			{
				if (TryResolvePlacedCitySid(objectId, out placedSid, out placedSource))
				{
					// placedSource already set by resolver
				}
				else
				{
					LogCreateCityDiag(objectId, currentSid, placedSid: null, fractionCity: ReadFractionConfigCity(__0),
						placedSource: "unresolved", via: __originalMethod?.Name, note: "placed city sid unresolved");
					return;
				}
			}
			if (string.Equals(placedSid, "random-city", StringComparison.Ordinal))
				return;
			if (!LooksLikeCitySid(placedSid))
				return;

			var fractionCity = ReadFractionConfigCity(__0);
			LogCreateCityDiag(objectId, currentSid, placedSid, fractionCity, placedSource, __originalMethod?.Name, note: null);

			var wroteInfoSid = false;
			if (!string.Equals(currentSid, placedSid, StringComparison.Ordinal))
			{
				DeobfInteropCompat.SetMapObjectInfoSid(ref __1, placedSid);
				wroteInfoSid = true;
			}

			// CreateCity spawns the live city GO from Side.fractionConfig.city even when
			// MapObjectInfo.sid already matches the placed land-on SID. Override for the call.
			var wroteFractionCity = false;
			if (!string.Equals(fractionCity, placedSid, StringComparison.Ordinal)
			    && TryWriteFractionConfigCity(__0, placedSid, out var previousFractionCity))
			{
				PendingFractionCityRestores[objectId] = previousFractionCity ?? string.Empty;
				wroteFractionCity = true;
				fractionCity = previousFractionCity;
			}

			if (!wroteInfoSid && !wroteFractionCity)
				return;

			var key = objectId + "|" + placedSid + "|" + (__originalMethod?.Name ?? "?");
			if (LoggedCityPreserves.Add(key))
			{
				_log?.LogInfo(
					LogPrefix
					+ ": preserved placed city sid info="
					+ (currentSid ?? "?")
					+ " fractionCity="
					+ (fractionCity ?? "?")
					+ " -> "
					+ placedSid
					+ " id="
					+ objectId
					+ " source="
					+ placedSource
					+ " wroteInfoSid="
					+ wroteInfoSid
					+ " wroteFractionCity="
					+ wroteFractionCity
					+ " via "
					+ (__originalMethod?.Name ?? "?")
					+ ".");
			}
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + ": PrefixCreateCity failed closed: " + ex.Message);
		}
	}

	private static void PostfixCreateCity(Side __0, MapObjectInfo __1)
	{
		try
		{
			var objectId = DeobfInteropCompat.GetMapObjectInfoId(__1);
			if (!PendingFractionCityRestores.TryRemove(objectId, out var previous) || previous == null)
				return;
			// Empty string means the field was previously null/blank.
			TryWriteFractionConfigCity(__0, previous.Length == 0 ? null : previous, out _);
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + ": PostfixCreateCity fractionConfig.city restore failed: " + ex.Message);
		}
	}

	private static string PeekPendingOrMapCitySid(int objectId)
	{
		if (PendingCitySids.TryGetValue(objectId, out var pending) && !string.IsNullOrWhiteSpace(pending))
			return pending;
		return TryResolvePlacedCitySid(objectId, out var placed, out _) ? placed : null;
	}

	private static bool LooksLikeCitySid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		return sid.IndexOf("city", StringComparison.OrdinalIgnoreCase) >= 0
		       || sid.IndexOf("town", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static void LogCreateCityDiag(
		int objectId,
		string currentSid,
		string placedSid,
		string fractionCity,
		string placedSource,
		string via,
		string note)
	{
		var key = objectId + "|" + (currentSid ?? "") + "|" + (placedSid ?? "") + "|" + (fractionCity ?? "");
		if (!LoggedCreateCityDiag.Add(key))
			return;
		_log?.LogInfo(
			LogPrefix
			+ ": CreateCity diag id="
			+ objectId
			+ " infoSid="
			+ (currentSid ?? "?")
			+ " placedSid="
			+ (placedSid ?? "?")
			+ " fractionCity="
			+ (fractionCity ?? "?")
			+ " source="
			+ (placedSource ?? "?")
			+ " via="
			+ (via ?? "?")
			+ (string.IsNullOrEmpty(note) ? "" : " note=" + note)
			+ ".");
	}

	/// <summary>
	/// Index placed city SIDs from MapData.objects rows. Call when MapData is ready
	/// (RMG capture path) and again as a CreateCity fallback.
	/// Golden Era: never touch MapDataObjects.sid/.ids managed properties.
	/// </summary>
	internal static void IndexPlacedCitySidsFromMapData(MapData mapData)
	{
		if (mapData == null)
			return;

		string mapName;
		try
		{
			mapName = DeobfInteropCompat.TryReadNativeStringMember(mapData, "fileMapName", "field_Public_String_0") ?? "?";
		}
		catch
		{
			mapName = "?";
		}
		if (string.Equals(_indexedMapDataName, mapName, StringComparison.Ordinal)
		    && !PlacedCitySidsById.IsEmpty)
		{
			return;
		}

		var objects = GetFirstMemberValue(mapData, GameSymbols.CampaignSpawnParity.MapDataObjectsListMemberHints);
		if (objects == null)
		{
			if (!_loggedMapDataIndex)
			{
				_loggedMapDataIndex = true;
				_log?.LogWarning(LogPrefix + ": MapData.objects list unresolved; CreateCity land-on restore may fail.");
			}
			return;
		}

		var indexed = 0;
		PlacedCitySidsById.Clear();
		foreach (var rowObj in EnumerateIl2CppList(objects))
		{
			try
			{
				if (!TryReadMapDataObjectProps(rowObj, out var sid, out var ids) || !LooksLikeCitySid(sid))
					continue;
				if (string.Equals(sid, "random-city", StringComparison.Ordinal))
					continue;
				for (var i = 0; i < ids.Count; i++)
				{
					var id = ids[i];
					if (id <= 0)
						continue;
					PlacedCitySidsById[id] = sid;
					indexed++;
				}
			}
			catch
			{
				/* skip malformed row */
			}
		}

		_indexedMapDataName = mapName;
		_loggedMapDataIndex = true;
		_log?.LogInfo(
			LogPrefix
			+ ": indexed MapData city sids count="
			+ indexed
			+ " uniqueIds="
			+ PlacedCitySidsById.Count
			+ " map="
			+ mapName
			+ ".");
	}

	/// <summary>
	/// Golden Era-safe index from JsonUtility MapData dump (already proven to contain land-on SIDs).
	/// </summary>
	internal static void IndexPlacedCitySidsFromMapDataJson(string mapDataJson, string mapNameHint = null)
	{
		if (string.IsNullOrWhiteSpace(mapDataJson))
			return;
		try
		{
			var root = Newtonsoft.Json.Linq.JObject.Parse(mapDataJson);
			var mapName = mapNameHint
			              ?? root.Value<string>("fileMapName")
			              ?? _indexedMapDataName
			              ?? "?";
			if (string.Equals(_indexedMapDataName, mapName, StringComparison.Ordinal)
			    && !PlacedCitySidsById.IsEmpty)
			{
				return;
			}

			var objects = root["objects"] as Newtonsoft.Json.Linq.JArray;
			if (objects == null || objects.Count == 0)
			{
				_log?.LogWarning(LogPrefix + ": MapData JSON objects[] missing; city sid index empty.");
				return;
			}

			var indexed = 0;
			PlacedCitySidsById.Clear();
			for (var rowIndex = 0; rowIndex < objects.Count; rowIndex++)
			{
				var rowObj = objects[rowIndex] as Newtonsoft.Json.Linq.JObject;
				if (rowObj == null)
					continue;
				var sid = rowObj.Value<string>("sid");
				if (!LooksLikeCitySid(sid) || string.Equals(sid, "random-city", StringComparison.Ordinal))
					continue;
				var idsToken = rowObj["ids"] as Newtonsoft.Json.Linq.JArray;
				if (idsToken == null)
					continue;
				for (var idIndex = 0; idIndex < idsToken.Count; idIndex++)
				{
					if (!int.TryParse(idsToken[idIndex]?.ToString(), out var id) || id <= 0)
						continue;
					PlacedCitySidsById[id] = sid;
					indexed++;
				}
			}

			_indexedMapDataName = mapName;
			_loggedMapDataIndex = true;
			_log?.LogInfo(
				LogPrefix
				+ ": indexed MapData JSON city sids count="
				+ indexed
				+ " uniqueIds="
				+ PlacedCitySidsById.Count
				+ " map="
				+ mapName
				+ ".");
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + ": MapData JSON city sid index failed: " + ex.Message);
		}
	}

	private static string ReadFractionConfigCity(Side side)
	{
		var fractionConfig = TryGetSideFractionConfig(side);
		if (fractionConfig == null)
			return null;
		// Native field only — FractionConfig.get_city() is MissingMethodException on Golden Era.
		return DeobfInteropCompat.TryReadNativeStringMember(
			fractionConfig,
			"city",
			"<city>k__BackingField",
			"_city",
			"field_Public_String_1",
			"field_Public_String_2",
			"field_Public_String_3",
			"field_Public_String_4",
			"field_Public_String_5");
	}

	private static bool TryWriteFractionConfigCity(Side side, string citySid, out string previousCity)
	{
		previousCity = null;
		var fractionConfig = TryGetSideFractionConfig(side);
		if (fractionConfig == null)
			return false;

		previousCity = ReadFractionConfigCity(side);
		if (string.Equals(previousCity, citySid, StringComparison.Ordinal))
			return false;

		if (DeobfInteropCompat.TryWriteNativeStringMember(
			    fractionConfig,
			    citySid,
			    "city",
			    "<city>k__BackingField",
			    "_city",
			    "field_Public_String_1",
			    "field_Public_String_2",
			    "field_Public_String_3",
			    "field_Public_String_4",
			    "field_Public_String_5"))
		{
			return true;
		}

		if (!_loggedFractionCityFieldMiss)
		{
			_loggedFractionCityFieldMiss = true;
			_log?.LogWarning(
				LogPrefix
				+ ": FractionConfig.city field was not writable; CreateCity may keep spawning stock cities.");
		}
		return false;
	}

	private static object TryGetSideFractionConfig(Side side)
	{
		if (side == null)
			return null;

		var named = GetFirstMemberValue(side, GameSymbols.CampaignSpawnParity.SideFractionConfigFields)
		            ?? GetFirstMemberValue(side, GameSymbols.CustomDwellingRandomHire.SideFractionConfigFields);
		if (named != null)
			return CastFractionConfig(named) ?? named;

		var native = DeobfInteropCompat.TryReadNativeObjectMember<FractionConfig>(
			side,
			GameSymbols.CampaignSpawnParity.SideFractionConfigFields);
		if (native != null)
			return native;

		return TryFindFractionConfigByType(side);
	}

	private static FractionConfig CastFractionConfig(object value)
	{
		if (value is FractionConfig typed)
			return typed;
		if (value is Il2CppObjectBase il2Cpp)
		{
			try
			{
				return il2Cpp.TryCast<FractionConfig>();
			}
			catch
			{
				return null;
			}
		}
		return null;
	}

	private static object TryFindFractionConfigByType(Side side)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var t = side.GetType(); t != null; t = t.BaseType)
		{
			try
			{
				foreach (var prop in t.GetProperties(flags))
				{
					if (prop.GetIndexParameters().Length != 0)
						continue;
					if (!IsFractionConfigType(prop.PropertyType))
						continue;
					try
					{
						var value = prop.GetValue(side);
						if (value != null)
							return value;
					}
					catch { /* keep searching */ }
				}
				foreach (var field in t.GetFields(flags))
				{
					if (!IsFractionConfigType(field.FieldType))
						continue;
					try
					{
						var value = field.GetValue(side);
						if (value != null)
							return value;
					}
					catch { /* keep searching */ }
				}
			}
			catch
			{
				/* keep walking base types */
			}
		}
		return null;
	}

	private static bool IsFractionConfigType(Type type)
	{
		if (type == null)
			return false;
		if (type == typeof(FractionConfig))
			return true;
		return string.Equals(type.Name, "FractionConfig", StringComparison.Ordinal);
	}

	private static bool TrySetFirstStringMember(object obj, string value, string[] names)
	{
		if (obj == null || names == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrEmpty(name))
					continue;
				try
				{
					var prop = t.GetProperty(name, flags);
					if (prop != null && prop.SetMethod != null && prop.PropertyType == typeof(string))
					{
						prop.SetValue(obj, value);
						return true;
					}
				}
				catch { /* keep searching */ }
				try
				{
					var field = t.GetField(name, flags);
					if (field != null && field.FieldType == typeof(string))
					{
						field.SetValue(obj, value);
						return true;
					}
				}
				catch { /* keep searching */ }
			}
		}
		return false;
	}

	private static void TryStashPlacedCitySid(int objectId)
	{
		if (!TryResolvePlacedCitySid(objectId, out var sid, out _))
			return;
		PendingCitySids[objectId] = sid;
	}

	private static bool TryResolvePlacedCitySid(int objectId, out string sid)
	{
		return TryResolvePlacedCitySid(objectId, out sid, out _);
	}

	private static bool TryResolvePlacedCitySid(int objectId, out string sid, out string source)
	{
		sid = null;
		source = null;
		if (objectId <= 0)
			return false;

		if (PlacedCitySidsById.TryGetValue(objectId, out sid) && !string.IsNullOrWhiteSpace(sid))
		{
			source = "mapdata-index";
			return true;
		}

		EnsureMapDataCityIndex();
		if (PlacedCitySidsById.TryGetValue(objectId, out sid) && !string.IsNullOrWhiteSpace(sid))
		{
			source = "mapdata-index";
			return true;
		}

		var map = TryResolveMap();
		if (map == null)
			return false;

		var placed = TryGetMapObjectById(map, objectId);
		if (placed == null)
			return false;
		if (!DeobfInteropCompat.TryGetPlacedMapObjectSid(placed, out sid) || string.IsNullOrWhiteSpace(sid))
			return false;
		if (string.Equals(sid, "random-city", StringComparison.Ordinal))
			return false;
		if (!LooksLikeCitySid(sid))
		{
			sid = null;
			return false;
		}

		source = "map-object";
		PlacedCitySidsById[objectId] = sid;
		return true;
	}

	private static void EnsureMapDataCityIndex()
	{
		if (!PlacedCitySidsById.IsEmpty)
			return;
		if (!TryResolveLiveMapData(out var mapData))
			return;
		IndexPlacedCitySidsFromMapData(mapData);
	}

	private static bool TryResolveLiveMapData(out MapData mapData)
	{
		mapData = null;
		try
		{
			for (var i = 0; i < SceneManager.sceneCount; i++)
			{
				var scene = SceneManager.GetSceneAt(i);
				if (!scene.IsValid() || !scene.isLoaded)
					continue;
				GameObject[] roots;
				try { roots = scene.GetRootGameObjects(); }
				catch { continue; }
				for (var r = 0; r < roots.Length; r++)
				{
					var root = roots[r];
					if (!root || !string.Equals(root.name, GameSymbols.HomecomingBoatTravel.WorldRootName, StringComparison.Ordinal))
						continue;

					var worldType = ResolveWorldOwnerType();
					if (worldType == null)
						return false;
					Component worldComponent;
					try
					{
						worldComponent = root.GetComponent(Il2CppInterop.Runtime.Il2CppType.From(worldType))
							?.TryCast<Component>();
					}
					catch
					{
						return false;
					}
					if (!worldComponent)
						return false;

					var mapObj = InvokeFirstNoArg(
						worldComponent,
						typeof(Map),
						GameSymbols.HomecomingBoatTravel.WorldMap.NameHints);
					var map = mapObj as Map
					          ?? (mapObj as Il2CppObjectBase)?.TryCast<Map>();
					if (map == null)
						return false;

					mapData = ResolveMapDataFromMap(map);
					return mapData != null;
				}
			}
		}
		catch (Exception ex)
		{
			if (!_loggedResolveFailure)
			{
				_loggedResolveFailure = true;
				_log?.LogWarning(LogPrefix + ": live MapData resolve failed: " + ex.Message);
			}
		}
		return false;
	}

	private static Type ResolveWorldOwnerType()
	{
		var hints = GameSymbols.HomecomingBoatTravel.WorldOwnerTypeHints;
		if (hints == null)
			return null;
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var type = GameMember.FindType(
				GameSymbols.HomecomingBoatTravel.WorldOwnerTypeId + "." + hint,
				hint);
			if (type != null)
				return type;
		}
		return null;
	}

	private static MapData ResolveMapDataFromMap(Map map)
	{
		if (map == null)
			return null;
		var direct = InvokeFirstNoArg(map, typeof(MapData), GameSymbols.HomecomingBoatTravel.MapData.NameHints);
		if (direct is MapData md)
			return md;
		if (direct is Il2CppObjectBase il2Cpp)
		{
			try
			{
				var cast = il2Cpp.TryCast<MapData>();
				if (cast != null)
					return cast;
			}
			catch
			{
				/* keep searching */
			}
		}
		return GetFirstMemberValue(map, new[] { "mapData", "get_mapData", "bvjr", "get_bvjr" }) as MapData;
	}

	private static object InvokeFirstNoArg(object owner, Type expectedReturnType, string[] names)
	{
		if (owner == null || expectedReturnType == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrEmpty(name))
					continue;
				try
				{
					var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && expectedReturnType.IsAssignableFrom(method.ReturnType))
						return method.Invoke(owner, null);
				}
				catch { /* keep searching */ }
				try
				{
					var prop = type.GetProperty(name, flags);
					if (prop != null
					    && prop.GetIndexParameters().Length == 0
					    && expectedReturnType.IsAssignableFrom(prop.PropertyType))
					{
						return prop.GetValue(owner);
					}
				}
				catch { /* keep searching */ }
			}
		}
		return null;
	}

	private static bool TryReadMapDataObjectProps(object rowObj, out string sid, out List<int> ids)
	{
		sid = null;
		ids = new List<int>();
		if (rowObj == null)
			return false;

		// Native fields only. Do not call MapDataObjects.sid / .ids — Golden Era stubs throw
		// MissingMethodException and that exception has escaped local catch blocks in practice.
		sid = DeobfInteropCompat.TryReadNativeStringMember(
			rowObj,
			"sid",
			"field_Public_String_0",
			"field_Public_String_1");

		var idsObj = DeobfInteropCompat.TryReadNativeObjectMember(
			             rowObj,
			             typeof(Il2CppInterop.Runtime.InteropTypes.Arrays.Il2CppStructArray<int>),
			             "ids",
			             "field_Public_Il2CppStructArray_1_Int32_0",
			             "field_Public_ArrayOf_Int32_0")
		             ?? GetFirstMemberValue(rowObj, new[]
		             {
			             "field_Public_Il2CppStructArray_1_Int32_0",
			             "field_Public_ArrayOf_Int32_0",
			             "ids"
		             });
		if (idsObj != null)
			AppendIntArray(idsObj, ids);

		return !string.IsNullOrWhiteSpace(sid) && ids.Count > 0;
	}

	private static void AppendIntArray(object idsObj, List<int> ids)
	{
		if (idsObj == null || ids == null)
			return;
		try
		{
			var lengthProp = idsObj.GetType().GetProperty("Length", BindingFlags.Instance | BindingFlags.Public)
			                 ?? idsObj.GetType().GetProperty("Count", BindingFlags.Instance | BindingFlags.Public);
			if (lengthProp == null)
				return;
			var length = Convert.ToInt32(lengthProp.GetValue(idsObj));
			var indexer = idsObj.GetType().GetMethod("get_Item", new[] { typeof(int) });
			if (indexer == null)
			{
				// Il2CppStructArray supports indexer via this[int]
				for (var i = 0; i < length; i++)
				{
					object value = null;
					try
					{
						var itemProp = idsObj.GetType().GetProperty("Item", new[] { typeof(int) });
						value = itemProp?.GetValue(idsObj, new object[] { i });
					}
					catch { value = null; }
					if (value != null)
						ids.Add(Convert.ToInt32(value));
				}
				return;
			}
			for (var i = 0; i < length; i++)
			{
				try
				{
					ids.Add(Convert.ToInt32(indexer.Invoke(idsObj, new object[] { i })));
				}
				catch
				{
					/* skip slot */
				}
			}
		}
		catch
		{
			/* ignore malformed ids */
		}
	}

	private static object TryResolveMap()
	{
		var fromStatic = TryReadStaticMember(
			_spawnsCreatorType,
			GameSymbols.CampaignSpawnParity.MapFieldHints,
			expectedTypeName: "Map");
		if (fromStatic != null)
			return fromStatic;

		// Fallback: ObjectsProperties is often enough for heroes; map may still be absent.
		return null;
	}

	private static object TryResolveObjectsProperties()
	{
		var fromStatic = TryReadStaticMember(
			_spawnsCreatorType,
			GameSymbols.CampaignSpawnParity.ObjectsPropertiesFieldHints,
			expectedTypeName: "ObjectsProperties");
		if (fromStatic != null)
			return fromStatic;

		var map = TryResolveMap();
		if (map != null)
			return Homm3MapObjectPropCityResolver.ResolveObjectsProperties(map);

		if (!_loggedResolveFailure)
		{
			_loggedResolveFailure = true;
			_log?.LogWarning(
				LogPrefix
				+ ": could not resolve SpawnsCreator ObjectsProperties/Map static members on "
				+ (_spawnsCreatorType?.Name ?? "?")
				+ "; dump="
				+ DescribeStaticMembers(_spawnsCreatorType));
		}
		return null;
	}

	private static object TryReadStaticMember(Type type, string[] hints, string expectedTypeName)
	{
		if (type == null || hints == null)
			return null;
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrEmpty(hint))
				continue;

			try
			{
				var prop = type.GetProperty(hint, flags);
				if (prop != null && prop.GetMethod != null && TypeNameLooksLike(prop.PropertyType, expectedTypeName))
				{
					var value = prop.GetValue(null);
					if (value != null)
						return value;
				}
			}
			catch { /* keep searching */ }

			try
			{
				var field = type.GetField(hint, flags);
				if (field != null && TypeNameLooksLike(field.FieldType, expectedTypeName))
				{
					var value = field.GetValue(null);
					if (value != null)
						return value;
				}
			}
			catch { /* keep searching */ }
		}

		// Shape fallback: unique static member whose type name matches.
		object unique = null;
		MemberInfo[] members;
		try
		{
			var list = new List<MemberInfo>();
			list.AddRange(type.GetFields(flags));
			list.AddRange(type.GetProperties(flags));
			members = list.ToArray();
		}
		catch
		{
			return null;
		}

		foreach (var member in members)
		{
			Type memberType = null;
			object value = null;
			try
			{
				if (member is FieldInfo field)
				{
					if (field.FieldType == typeof(IntPtr) || field.Name.StartsWith("NativeFieldInfoPtr_", StringComparison.Ordinal))
						continue;
					memberType = field.FieldType;
					value = field.GetValue(null);
				}
				else if (member is PropertyInfo prop && prop.GetMethod != null && prop.GetIndexParameters().Length == 0)
				{
					memberType = prop.PropertyType;
					value = prop.GetValue(null);
				}
			}
			catch
			{
				continue;
			}

			if (value == null || !TypeNameLooksLike(memberType, expectedTypeName))
				continue;
			if (unique != null)
				return null;
			unique = value;
		}
		return unique;
	}

	private static bool TypeNameLooksLike(Type type, string expectedTypeName)
	{
		if (type == null || string.IsNullOrEmpty(expectedTypeName))
			return false;
		if (string.Equals(type.Name, expectedTypeName, StringComparison.Ordinal))
			return true;
		var full = type.FullName;
		return !string.IsNullOrEmpty(full)
			&& (full.EndsWith("." + expectedTypeName, StringComparison.Ordinal)
			    || full.IndexOf(expectedTypeName, StringComparison.Ordinal) >= 0);
	}

	private static string DescribeStaticMembers(Type type)
	{
		if (type == null)
			return "<null>";
		try
		{
			const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			var parts = new List<string>();
			foreach (var field in type.GetFields(flags))
				parts.Add("F:" + field.Name + ":" + (field.FieldType?.Name ?? "?"));
			foreach (var prop in type.GetProperties(flags))
				parts.Add("P:" + prop.Name + ":" + (prop.PropertyType?.Name ?? "?"));
			return parts.Count == 0 ? "<none>" : string.Join(",", parts);
		}
		catch (Exception ex)
		{
			return "<error:" + ex.GetType().Name + ">";
		}
	}

	private static object TryGetMapObjectById(object map, int objectId)
	{
		if (map == null)
			return null;

		object objects = null;
		foreach (var name in GameSymbols.CampaignSpawnParity.MapObjectsMemberHints)
		{
			objects = GetMemberValue(map, name);
			if (objects != null)
				break;
		}
		if (objects == null)
			return null;

		foreach (var methodName in GameSymbols.CampaignSpawnParity.MapObjectsByIdMethodHints)
		{
			MethodInfo method = null;
			try
			{
				method = objects.GetType().GetMethod(
					methodName,
					BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
					null,
					new[] { typeof(int) },
					null);
			}
			catch
			{
				method = null;
			}
			if (method == null)
				continue;
			try
			{
				return method.Invoke(objects, new object[] { objectId });
			}
			catch
			{
				// keep trying
			}
		}
		return null;
	}

	private static bool TryResolvePropHeroSid(int objectId, out string heroSid)
	{
		heroSid = null;
		var objectsProperties = TryResolveObjectsProperties();
		if (objectsProperties == null)
			return false;
		return TryResolvePropHeroSidFromObjectsProperties(
			objectsProperties as ObjectsProperties,
			objectId,
			out heroSid);
	}

	internal static bool TryResolvePropHeroSidFromObjectsProperties(
		ObjectsProperties objectsProperties,
		int objectId,
		out string heroSid)
	{
		heroSid = null;
		if (objectsProperties == null || objectId <= 0)
			return false;

		object propHeroes = null;
		foreach (var name in GameSymbols.CampaignSpawnParity.PropHeroesMemberHints)
		{
			propHeroes = GetMemberValue(objectsProperties, name);
			if (propHeroes != null)
				break;
		}
		if (propHeroes == null)
			return false;

		foreach (var row in EnumerateIl2CppList(propHeroes))
		{
			if (row == null)
				continue;
			var id = DeobfInteropCompat.GetIntMember(row, "id", "field_Public_Int32_0");
			if (id != objectId)
				continue;
			var defined = GetBoolMember(row, "isDefined", "field_Public_Boolean_0");
			if (!defined)
				continue;
			heroSid = DeobfInteropCompat.TryReadNativeStringMember(row, "heroSid", "field_Public_String_0", "field_Public_String_1");
			return !string.IsNullOrWhiteSpace(heroSid);
		}
		return false;
	}

	internal static bool TryResolvePropHeroSidForObject(int objectId, out string heroSid)
	{
		return TryResolvePropHeroSid(objectId, out heroSid);
	}

	private static bool GetBoolMember(object obj, params string[] names)
	{
		var value = GetFirstMemberValue(obj, names);
		return value is bool b && b;
	}

	private static object GetFirstMemberValue(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = GetMemberValue(obj, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object GetMemberValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
			return null;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			try
			{
				var p = t.GetProperty(name, flags);
				if (p != null)
					return p.GetValue(obj);
			}
			catch { /* keep searching */ }
			try
			{
				var f = t.GetField(name, flags);
				if (f != null)
					return f.GetValue(obj);
			}
			catch { /* keep searching */ }
		}
		return null;
	}

	private static IEnumerable<object> EnumerateIl2CppList(object list)
	{
		if (list == null)
			yield break;

		int count;
		try
		{
			var countProp = list.GetType().GetProperty("Count", BindingFlags.Instance | BindingFlags.Public);
			if (countProp == null)
				yield break;
			count = Convert.ToInt32(countProp.GetValue(list));
		}
		catch
		{
			yield break;
		}

		MethodInfo indexer = null;
		foreach (var method in list.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public))
		{
			if (method.Name != "get_Item")
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length == 1 && parameters[0].ParameterType == typeof(int))
			{
				indexer = method;
				break;
			}
		}
		if (indexer == null)
			yield break;

		for (var i = 0; i < count; i++)
		{
			object item = null;
			try { item = indexer.Invoke(list, new object[] { i }); }
			catch { item = null; }
			if (item != null)
				yield return item;
		}
	}
}
