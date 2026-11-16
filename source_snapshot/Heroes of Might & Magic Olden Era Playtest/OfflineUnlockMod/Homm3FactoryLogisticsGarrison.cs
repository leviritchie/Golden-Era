using System;
using System.Reflection;
using DataObjCity = Hex.Session.Data.ObjCity;
using DataParty = Hex.Session.Data.DataParty;

namespace OfflineUnlockMod;

/// <summary>
/// Resolves a town's heroless garrison as a live LOGIC party (the party type <see cref="Homm3PartyArmyWriter"/> writes),
/// for Rail Network remote hire into a town.
///
/// Path (26615913 interop, found by shape, no new symbol): the scene world singleton (existing
/// GameSymbols.HomecomingBoatTravel.WorldOwnerTypeHints / WorldSingletonMembers) → its only member whose type holds an
/// Il2Cpp Dictionary&lt;int, map-object logic&gt; that can hold the logic city (the map-object logic registry) → the entry
/// keyed by the city's idMapObject → must be the logic city (the only Hex type with a ctor(ObjCity)) whose ObjCity is
/// the very data city we were given → the map-object logic's only logic-party member. The party is accepted only when
/// its Data party is the city's own DataObject.garnisonParty (pointer equality); every other outcome refuses.
/// </summary>
internal static class Homm3FactoryLogisticsGarrison
{
	private const BindingFlags Instance = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
	private const BindingFlags Static = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

	private static bool _attempted;
	private static string _resolveFail;
	private static PropertyInfo _worldStatic;
	private static PropertyInfo _registryProperty;
	private static PropertyInfo _registryDictProperty;
	private static MethodInfo _dictContainsKey;
	private static MethodInfo _dictGetItem;
	private static Type _logicCityType;
	private static System.Reflection.MethodInfo _tryCastCity;
	private static PropertyInfo _logicCityDataProperty;
	private static PropertyInfo _logicObjectPartyProperty;

	/// <summary>
	/// The live logic party of <paramref name="city"/>'s heroless garrison. False with the reason when anything on the
	/// path is unresolved, missing, or does not point back at this city's own garrison party.
	/// </summary>
	internal static bool TryGetTownGarrisonParty(DataObjCity city, out object logicParty, out string fail)
	{
		logicParty = null;
		if (city == null || city.Pointer == IntPtr.Zero)
		{
			fail = "town data unreadable";
			return false;
		}
		if (!TryResolve(out fail))
			return false;
		try
		{
			var world = _worldStatic.GetValue(null);
			if (world == null)
			{
				fail = "world not loaded";
				return false;
			}
			var registry = _registryProperty.GetValue(world);
			var dict = registry == null ? null : _registryDictProperty.GetValue(registry);
			if (dict == null)
			{
				fail = "map-object logic registry unreadable";
				return false;
			}
			var key = city.idMapObject;
			if (!(_dictContainsKey.Invoke(dict, new object[] { key }) is bool has) || !has)
			{
				fail = "town " + key + " has no map-object logic";
				return false;
			}
			var logicObject = _dictGetItem.Invoke(dict, new object[] { key });
			// The dictionary hands back the base map-object wrapper (2026-11-16 playtest: "is not a town
			// (ObjectPublicObcrDaBoObLi1ObcwcrUnique)"). TryCast checks the native class and rewraps, null if not a town.
			if (logicObject is Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase baseWrapper && !_logicCityType.IsInstanceOfType(logicObject))
			{
				_tryCastCity ??= typeof(Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase).GetMethod(nameof(Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase.TryCast))!.MakeGenericMethod(_logicCityType);
				logicObject = _tryCastCity.Invoke(baseWrapper, null) ?? logicObject;
			}
			if (logicObject == null || !_logicCityType.IsInstanceOfType(logicObject))
			{
				fail = "map-object logic " + key + " is not a town (" + (logicObject?.GetType().Name ?? "null") + ")";
				return false;
			}
			var logicCityData = _logicCityDataProperty.GetValue(logicObject) as DataObjCity;
			if (logicCityData == null || logicCityData.Pointer != city.Pointer)
			{
				fail = "map-object logic " + key + " belongs to another town";
				return false;
			}
			var party = _logicObjectPartyProperty.GetValue(logicObject);
			var dataParty = Homm3PartyArmyWriter.DataPartyOf(party);
			var garrison = city.garnisonParty;
			if (dataParty == null || garrison == null || dataParty.Pointer != garrison.Pointer)
			{
				fail = "the town's logic party is not its garrison (" + (dataParty == null ? "no party" : garrison == null ? "no garrison data" : "different party") + ")";
				return false;
			}
			logicParty = party;
			fail = null;
			return true;
		}
		catch (Exception ex)
		{
			fail = "garrison lookup threw " + ex.GetBaseException().Message;
			return false;
		}
	}

	private static bool TryResolve(out string fail)
	{
		if (_logicObjectPartyProperty != null)
		{
			fail = null;
			return true;
		}
		var partyType = Homm3PartyArmyWriter.LogicPartyType;
		if (partyType == null)
		{
			// The writer resolves at Factory Logistics registration; do not cache this miss.
			fail = "party writer unresolved" + (Homm3PartyArmyWriter.ResolveFailure == null ? "" : " (" + Homm3PartyArmyWriter.ResolveFailure + ")");
			return false;
		}
		if (_attempted)
		{
			fail = _resolveFail;
			return false;
		}
		_attempted = true;
		try
		{
			var worldType = GameMember.FindTypeFromHints(GameSymbols.HomecomingBoatTravel.WorldOwnerTypeId, GameSymbols.HomecomingBoatTravel.WorldOwnerTypeHints)
			                ?? throw new TypeLoadException("world owner type (HomecomingBoatTravel.WorldOwnerTypeHints)");
			PropertyInfo worldStatic = null;
			foreach (var name in GameSymbols.HomecomingBoatTravel.WorldSingletonMembers ?? Array.Empty<string>())
			{
				var p = string.IsNullOrWhiteSpace(name) ? null : worldType.GetProperty(name, Static);
				if (p != null && p.GetIndexParameters().Length == 0 && worldType.IsAssignableFrom(p.PropertyType))
				{
					worldStatic = p;
					break;
				}
			}
			worldStatic ??= UniqueProperty(worldType, Static, t => worldType.IsAssignableFrom(t), "world singleton");

			var logicCityType = FindLogicCityType();
			var cityData = UniqueProperty(logicCityType, Instance, t => t == typeof(DataObjCity), "logic city ObjCity");
			var objectParty = UniqueProperty(logicCityType, Instance, t => t == partyType, "map-object logic party");

			PropertyInfo registry = null;
			PropertyInfo registryDict = null;
			foreach (var p in worldType.GetProperties(Instance))
			{
				if (p.GetIndexParameters().Length != 0 || p.PropertyType.IsValueType)
					continue;
				PropertyInfo[] inner;
				try
				{
					inner = p.PropertyType.GetProperties(Instance);
				}
				catch
				{
					continue;
				}
				foreach (var q in inner)
				{
					var qt = q.PropertyType;
					if (q.GetIndexParameters().Length != 0 || !qt.IsGenericType || qt.GetGenericTypeDefinition() != typeof(Il2CppSystem.Collections.Generic.Dictionary<,>))
						continue;
					var args = qt.GetGenericArguments();
					if (args[0] != typeof(int) || !args[1].IsAssignableFrom(logicCityType))
						continue;
					if (registry != null && registry.PropertyType != p.PropertyType)
						throw new AmbiguousMatchException("map-object logic registry: " + registry.PropertyType.FullName + " and " + p.PropertyType.FullName);
					// Interop exposes the same member twice (backing-field and prop_ wrappers); both read one object.
					registry ??= p;
					registryDict ??= q;
				}
			}
			if (registry == null)
				throw new MissingMemberException(worldType.FullName, "map-object logic registry (Dictionary<int, logic city base>)");

			var dictType = registryDict.PropertyType;
			var containsKey = dictType.GetMethod("ContainsKey", BindingFlags.Instance | BindingFlags.Public, null, new[] { typeof(int) }, null)
			                  ?? throw new MissingMethodException(dictType.FullName, "ContainsKey");
			var getItem = dictType.GetProperty("Item", BindingFlags.Instance | BindingFlags.Public, null, dictType.GetGenericArguments()[1], new[] { typeof(int) }, null)?.GetGetMethod()
			              ?? throw new MissingMethodException(dictType.FullName, "get_Item");

			_worldStatic = worldStatic;
			_registryProperty = registry;
			_registryDictProperty = registryDict;
			_dictContainsKey = containsKey;
			_dictGetItem = getItem;
			_logicCityType = logicCityType;
			_logicCityDataProperty = cityData;
			_logicObjectPartyProperty = objectParty;
			Homm3FactoryLogisticsRuntime.LogInfo("garrison delivery resolved: " + worldType.Name + "." + worldStatic.Name + " -> " + registry.Name + "." + registryDict.Name
				+ " -> " + logicCityType.Name + " (" + cityData.Name + ", party " + objectParty.Name + ").");
			fail = null;
			return true;
		}
		catch (Exception ex)
		{
			_resolveFail = fail = "garrison delivery unresolved: " + ex.GetBaseException().Message;
			Homm3FactoryLogisticsRuntime.LogError(_resolveFail + " (town garrisons cannot receive remote hires).");
			return false;
		}
	}

	/// <summary>The only non-abstract Hex type with a constructor taking exactly an ObjCity (the logic city).</summary>
	private static Type FindLogicCityType()
	{
		Type match = null;
		foreach (var type in GameMember.EnumerateHexTypes())
		{
			try
			{
				if (type == null || type.IsAbstract)
					continue;
				var ctor = type.GetConstructor(Instance, null, new[] { typeof(DataObjCity) }, null);
				var ps = ctor?.GetParameters();
				if (ps == null || ps.Length != 1 || ps[0].ParameterType != typeof(DataObjCity))
					continue;
				if (match != null)
					throw new AmbiguousMatchException("logic city shape: " + match.FullName + " and " + type.FullName);
				match = type;
			}
			catch (AmbiguousMatchException)
			{
				throw;
			}
			catch
			{
				// Types that fail to reflect are not the logic city.
			}
		}
		return match ?? throw new TypeLoadException("logic city type (ctor(ObjCity)) not found");
	}

	/// <summary>
	/// The single property (by type) matching <paramref name="typeOk"/>; interop's backing-field and prop_ wrappers of one
	/// member count once (prop_ preferred). Two distinct members of the matching type refuse.
	/// </summary>
	private static PropertyInfo UniqueProperty(Type type, BindingFlags flags, Func<Type, bool> typeOk, string what)
	{
		PropertyInfo backing = null;
		PropertyInfo wrapper = null;
		foreach (var p in type.GetProperties(flags))
		{
			if (p.GetIndexParameters().Length != 0 || p.GetGetMethod(true) == null || !typeOk(p.PropertyType))
				continue;
			if (p.Name.EndsWith("k__BackingField", StringComparison.Ordinal))
			{
				if (backing != null && backing.Name != p.Name)
					throw new AmbiguousMatchException(what + ": " + backing.Name + " and " + p.Name + " on " + type.FullName);
				backing = p;
			}
			else
			{
				if (wrapper != null && wrapper.Name != p.Name)
					throw new AmbiguousMatchException(what + ": " + wrapper.Name + " and " + p.Name + " on " + type.FullName);
				wrapper = p;
			}
		}
		return wrapper ?? backing ?? throw new MissingMemberException(type.FullName, what);
	}
}
