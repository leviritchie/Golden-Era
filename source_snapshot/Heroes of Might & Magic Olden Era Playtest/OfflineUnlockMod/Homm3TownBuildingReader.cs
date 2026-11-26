using System;
using System.Collections.Generic;
using System.Reflection;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using DataHero = Hex.Session.Data.Hero;
using DataObjCity = Hex.Session.Data.ObjCity;
using DataRoot = Hex.Session.Data.Data;
using DataSide = Hex.Session.Data.Side;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22: the shared "does this town / side have building X at level N" reader that every
/// plugin building codes against (BUILD_BRIEF "Reader API").
///
/// Live surfaces (Hex.dll interop of build 26615913, re-read 2026-11-22):
/// - <c>Hex.Session.Data.ObjCity</c> (: DataObject): <c>idMapObject</c>, <c>sidConfig</c>, <c>ownerSide</c>,
///   <c>garnisonHeroId</c>, <c>visitorHeroId</c>, <c>inBattle</c>, <c>buildings</c> (BuildingsData).
/// - <c>Hex.Session.Data.BuildingsData</c>: one typed <c>List&lt;Building*&gt;</c> per section (mains ... walls). Grail
///   rows (<c>EBuildingType.Graal</c>) are created into <c>bonusBanks</c>. The lazy aggregate
///   (<c>prop_List_1_BuildingData_0</c>) is skipped on purpose so the reader never triggers its lazy build.
/// - <c>Hex.Session.Data.BuildingData</c>: sid (<c>GameSymbols.ReleaseTownUi.BuildingDataSidMembers</c>, read through
///   <see cref="Homm3ConstructionNativeAdapter.TryReadBuildingIdentity"/>), <c>level</c>, <c>isConstructed</c>,
///   <c>citySid</c> (the owning city config id, e.g. <c>homm3_castle_city</c>).
///
/// Built level = <c>isConstructed ? level : 0</c> (max over rows sharing the SID). City identity is the rows'
/// <c>citySid</c>, falling back to <c>ObjCity.sidConfig</c>; land-on clones match their canonical city id.
///
/// Main thread only. Every entry point fails closed (0 / false / empty) and never throws. The city list is cached
/// per (session Data pointer, game day); ownership and building levels are read live so a same-day capture or
/// construction is seen immediately.
/// </summary>
public static class Homm3TownBuildingReader
{
	private static IntPtr _cacheDataPtr;
	private static int _cacheDay = int.MinValue;
	private static readonly List<DataObjCity> _cityCache = new();
	private static PropertyInfo[] _sectionListProperties;
	private static int _loggedFailures;

	// ------------------------------------------------------------------ public API (BUILD_BRIEF, exact)

	/// <summary>Built level of <paramref name="buildingSid"/> in <paramref name="city"/>; 0 = not built or unreadable.</summary>
	public static int CityBuildingLevel(object city, string buildingSid)
	{
		try
		{
			if (string.IsNullOrWhiteSpace(buildingSid))
				return 0;
			var buildings = ResolveBuildingsData(city);
			return buildings == null ? 0 : BuiltLevel(buildings, buildingSid.Trim());
		}
		catch (Exception ex)
		{
			LogFailure("CityBuildingLevel(" + buildingSid + ") failed closed: " + ex.GetBaseException().Message);
			return 0;
		}
	}

	public static bool CityHasBuilding(object city, string buildingSid, int level = 1)
	{
		var built = CityBuildingLevel(city, buildingSid);
		return built > 0 && built >= Math.Max(1, level);
	}

	/// <summary>Number of towns owned by <paramref name="owner"/>'s side that have <paramref name="buildingSid"/> built (any level).</summary>
	public static int SideBuildingCount(object owner, string buildingSid, string citySid = null)
	{
		try
		{
			if (string.IsNullOrWhiteSpace(buildingSid))
				return 0;
			var count = 0;
			foreach (var city in SideCities(owner))
			{
				if (!string.IsNullOrWhiteSpace(citySid) && !CityMatchesSid(city, citySid))
					continue;
				if (CityBuildingLevel(city, buildingSid) > 0)
					count++;
			}
			return count;
		}
		catch (Exception ex)
		{
			LogFailure("SideBuildingCount(" + buildingSid + ") failed closed: " + ex.GetBaseException().Message);
			return 0;
		}
	}

	public static bool SideHasBuilding(object owner, string buildingSid, string citySid = null)
	{
		return SideBuildingCount(owner, buildingSid, citySid) > 0;
	}

	/// <summary>The live <c>Hex.Session.Data.ObjCity</c> objects currently owned by <paramref name="owner"/>'s side.</summary>
	public static IEnumerable<object> SideCities(object owner)
	{
		var result = new List<object>();
		try
		{
			if (!TryResolveSideIndex(owner, out var sideIndex) || sideIndex < 0)
				return result;
			foreach (var city in Cities())
			{
				if (city != null && city.ownerSide == sideIndex)
					result.Add(city);
			}
		}
		catch (Exception ex)
		{
			LogFailure("SideCities failed closed: " + ex.GetBaseException().Message);
			result.Clear();
		}
		return result;
	}

	/// <summary>
	/// The town under siege for a battle logic, a <c>TransferBattle</c> or a defending <c>TransferSide</c>.
	/// <paramref name="city"/> is a <c>Hex.Session.Data.ObjCity</c>; null (and false) when the battle is not a siege
	/// or the town cannot be identified exactly.
	/// </summary>
	public static bool TryGetBesiegedCity(object battleLogicOrState, out object city)
	{
		city = null;
		try
		{
			var transferBattle = ResolveTransferBattle(battleLogicOrState);
			if (transferBattle == null || !TryGetSiegeDefender(transferBattle, out var objCity, out _, out _))
				return false;
			city = objCity;
			return true;
		}
		catch (Exception ex)
		{
			LogFailure("TryGetBesiegedCity failed closed: " + ex.GetBaseException().Message);
			city = null;
			return false;
		}
	}

	// ------------------------------------------------------------------ shared helpers for the building runtimes

	/// <summary>True for a town siege: <c>battleType == ForCity</c>, or a siege arena when the type is unreadable.</summary>
	internal static bool IsSiegeBattle(TransferBattle transferBattle)
	{
		if (transferBattle == null)
			return false;
		try
		{
			if (transferBattle.battleType == EBattleType.ForCity)
				return true;
			if (transferBattle.battleType != EBattleType.OnMap && transferBattle.battleType != EBattleType.ForInteractObject)
				return (transferBattle.arenaLogicSid ?? string.Empty).IndexOf("siege", StringComparison.OrdinalIgnoreCase) >= 0;
			return false;
		}
		catch
		{
			return false;
		}
	}

	/// <summary>
	/// Resolve the besieged town and the defending transfer side of a siege. The defender is the side whose
	/// <c>sideIdInWorld</c> owns the town: a <c>Type_Hero</c> side matches the town's garrison or visiting hero id
	/// (<c>BattleMaker</c> builds hero sides with <c>entityIdInWorld = hero.id</c>); a <c>Type_Garnison</c> side
	/// (entity id = the garrison party id, which ObjCity does not expose) matches the single owned town flagged
	/// <c>inBattle</c>. Sides are tried defender-first (index 1, as <c>BattleMaker.StartBattleForCity</c> builds them).
	/// </summary>
	internal static bool TryGetSiegeDefender(TransferBattle transferBattle, out DataObjCity city, out int defenderIndex, out TransferSide defender)
	{
		city = null;
		defenderIndex = -1;
		defender = null;
		if (!IsSiegeBattle(transferBattle))
			return false;
		var sides = transferBattle.sides;
		if (sides == null || sides.Length < 2)
			return false;
		var cities = Cities();
		if (cities.Count == 0)
			return false;

		var order = new List<int>(sides.Length);
		if (sides.Length > 1)
			order.Add(1);
		for (var i = 0; i < sides.Length; i++)
			if (i != 1)
				order.Add(i);

		foreach (var index in order)
		{
			var side = sides[index];
			if (side == null)
				continue;
			var owner = side.sideIdInWorld;
			if (owner < 0)
				continue;
			DataObjCity match = null;
			if (side.typeInWorld == TransferSide.EType.Type_Hero)
			{
				var heroId = side.entityIdInWorld;
				if (heroId < 0)
					continue;
				foreach (var c in cities)
				{
					if (c == null || c.ownerSide != owner)
						continue;
					if (c.garnisonHeroId == heroId || c.visitorHeroId == heroId)
					{
						match = c;
						break;
					}
				}
			}
			else if (side.typeInWorld == TransferSide.EType.Type_Garnison)
			{
				var candidates = 0;
				foreach (var c in cities)
				{
					if (c == null || c.ownerSide != owner || !c.inBattle)
						continue;
					candidates++;
					match = c;
				}
				if (candidates != 1)
					match = null;
			}
			if (match == null)
				continue;
			city = match;
			defenderIndex = index;
			defender = side;
			return true;
		}
		return false;
	}

	/// <summary>True when the town's identity (rows' <c>citySid</c>, else <c>sidConfig</c>) is <paramref name="citySid"/> or a land-on clone of it.</summary>
	internal static bool CityMatchesSid(object city, string citySid)
	{
		if (string.IsNullOrWhiteSpace(citySid))
			return true;
		var identity = CityIdentity(city);
		return !string.IsNullOrWhiteSpace(identity) && Homm3CustomFactionRegistry.MatchesCitySidOrLandOnAlias(identity, citySid);
	}

	/// <summary>The town's city config id (e.g. <c>homm3_stronghold_city</c>), or null.</summary>
	internal static string CityIdentity(object city)
	{
		try
		{
			var objCity = city as DataObjCity;
			var buildings = ResolveBuildingsData(city);
			if (buildings != null)
			{
				foreach (var row in EnumerateRows(buildings))
				{
					var sid = row.citySid;
					if (!string.IsNullOrWhiteSpace(sid))
						return sid.Trim();
				}
			}
			var config = objCity?.sidConfig;
			return string.IsNullOrWhiteSpace(config) ? null : config.Trim();
		}
		catch
		{
			return null;
		}
	}

	// ------------------------------------------------------------------ internals

	private static List<DataObjCity> Cities()
	{
		if (!Homm3FactoryLogisticsEffects.TryGetData(out DataRoot data, out var fail) || data == null)
		{
			LogFailure("session Data unresolved: " + fail);
			_cityCache.Clear();
			_cacheDataPtr = IntPtr.Zero;
			return _cityCache;
		}
		var day = data.daysInGameCount;
		if (data.Pointer == _cacheDataPtr && day == _cacheDay && _cityCache.Count > 0)
			return _cityCache;
		_cityCache.Clear();
		_cacheDataPtr = data.Pointer;
		_cacheDay = day;
		var list = data.objects?.cityObjs;
		for (var i = 0; list != null && i < list.Count; i++)
		{
			var c = list[i];
			if (c != null)
				_cityCache.Add(c);
		}
		return _cityCache;
	}

	private static object ResolveBuildingsData(object city)
	{
		if (city == null)
			return null;
		if (city is DataObjCity objCity)
			return objCity.buildings;
		if (city is Hex.Session.Data.BuildingsData direct)
			return direct;
		// BhCity / city logic / any context the construction adapter understands.
		return Homm3ConstructionNativeAdapter.TryResolveBuildingsDataFromCityContext(city, out var buildings, out _) ? buildings : null;
	}

	private static int BuiltLevel(object buildings, string buildingSid)
	{
		var best = 0;
		foreach (var row in EnumerateRows(buildings))
		{
			if (!Homm3ConstructionNativeAdapter.TryReadBuildingIdentity(row, out var info, out _))
				continue;
			if (!string.Equals(info.Sid, buildingSid, StringComparison.Ordinal))
				continue;
			var level = info.IsConstructed ? info.Level : 0;
			if (level > best)
				best = level;
		}
		return best;
	}

	private static IEnumerable<Hex.Session.Data.BuildingData> EnumerateRows(object buildings)
	{
		if (buildings == null)
			yield break;
		foreach (var property in SectionListProperties(buildings.GetType()))
		{
			object list;
			try
			{
				list = property.GetValue(buildings);
			}
			catch
			{
				continue;
			}
			foreach (var item in Homm3FactoryLogisticsEffects.Enumerate(list))
			{
				if (item is Hex.Session.Data.BuildingData row)
					yield return row;
				else if (item is Il2CppObjectBase baseObj && baseObj.Pointer != IntPtr.Zero)
				{
					Hex.Session.Data.BuildingData cast = null;
					try
					{
						cast = baseObj.TryCast<Hex.Session.Data.BuildingData>();
					}
					catch
					{
						// not a building row
					}
					if (cast != null)
						yield return cast;
				}
			}
		}
	}

	/// <summary>Every typed per-section list on BuildingsData (List&lt;BuildingX&gt; where BuildingX : BuildingData), minus the lazy aggregate.</summary>
	private static PropertyInfo[] SectionListProperties(Type buildingsType)
	{
		if (_sectionListProperties != null && _sectionListProperties.Length > 0 && _sectionListProperties[0].DeclaringType == buildingsType)
			return _sectionListProperties;
		var found = new List<PropertyInfo>();
		foreach (var property in buildingsType.GetProperties(BindingFlags.Instance | BindingFlags.Public))
		{
			if (property.GetIndexParameters().Length != 0)
				continue;
			var type = property.PropertyType;
			if (!type.IsGenericType || type.GetGenericArguments().Length != 1)
				continue;
			var element = type.GetGenericArguments()[0];
			if (!typeof(Hex.Session.Data.BuildingData).IsAssignableFrom(element))
				continue;
			// The aggregate is List<BuildingData> exactly (field_Private_/prop_List_1_BuildingData_0); sections use subtypes.
			if (element == typeof(Hex.Session.Data.BuildingData))
				continue;
			found.Add(property);
		}
		_sectionListProperties = found.ToArray();
		return _sectionListProperties;
	}

	private static TransferBattle ResolveTransferBattle(object source)
	{
		if (source == null)
			return null;
		if (source is TransferBattle direct)
			return direct;
		// A lone TransferSide has no back-reference to its battle; callers pass the logic or the TransferBattle.
		if (source is TransferSide)
			return null;
		var started = Homm3TowerArtificingRuntime.ReadMember(source, GameSymbols.BattleResultLaws.BattleLogicStartedTransferBattleFields) as TransferBattle;
		if (started != null)
			return started;
		return Homm3TowerArtificingRuntime.ReadMember(source, GameSymbols.BattleResultLaws.BattleLogicTransferBattleFields) as TransferBattle;
	}

	internal static bool TryResolveSideIndex(object owner, out int sideIndex)
	{
		sideIndex = -1;
		switch (owner)
		{
			case null:
				return false;
			case int i:
				sideIndex = i;
				return true;
			case DataSide dataSide:
				sideIndex = dataSide.index;
				return true;
			case TransferSide transferSide:
				sideIndex = transferSide.sideIdInWorld;
				return sideIndex >= 0;
			case DataHero hero:
				sideIndex = hero.sideId;
				return sideIndex >= 0;
			case DataObjCity city:
				sideIndex = city.ownerSide;
				return sideIndex >= 0;
		}
		try
		{
			if (Homm3TowerArtificingRuntime.ReadMember(owner, GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers) is int direct)
			{
				sideIndex = direct;
				return true;
			}
			if (Homm3TowerArtificingRuntime.ReadMember(owner, GameSymbols.CustomFactionLawRuntime.LogicSideDataSideMembers) is DataSide viaLogicSide)
			{
				sideIndex = viaLogicSide.index;
				return true;
			}
			if (Homm3CustomFactionLawRuntime.TryResolveDataSideFromLogicHeroExplained(owner, out var viaHero, out _) && viaHero is DataSide heroSide)
			{
				sideIndex = heroSide.index;
				return true;
			}
		}
		catch
		{
			// fail closed below
		}
		return false;
	}

	private static void LogFailure(string message)
	{
		if (_loggedFailures++ < 16)
			Plugin.LogSource?.LogWarning("HoMM3 town building reader: " + message);
	}
}
