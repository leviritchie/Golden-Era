using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using BattleHex = Hex.Session.Battle.Hex;
using DataBuildingData = Hex.Session.Data.BuildingData;
using DataObjCity = Hex.Session.Data.ObjCity;

namespace OfflineUnlockMod;

/// <summary>
/// Lightning Rod (Factory grail, <c>Build_Golden_Calf</c> in <c>homm3_factory_city</c>), building pass 2026-11-22.
/// At round 1, before the first turn, every battle side that has a hero strikes each enemy stack once for
/// the sum over its owned Factory towns with the Rod of 7 x (4 + distinct built building SIDs in that town).
/// Several Rods add up. The int goes to the unit damage method as final damage (no Defense step).
/// Hooks: BattleLogic.Init postfix (records the battle) and the round hub RoundStarted dispatcher postfix
/// (strikes once). Both mirror <see cref="Homm3CastleLawHooks"/>.
/// </summary>
internal static class Homm3FactoryLightningRodRuntime
{
	internal const string RodSid = "Build_Golden_Calf";
	internal const int DamagePerBuilding = 7;
	internal const int BaseBuildings = 4;

	private sealed class Strike
	{
		internal object Wrapper;
		internal int Damage;
		internal int Rods;
	}

	private sealed class Pending
	{
		internal object Logic;
		internal IntPtr HubPointer;
		internal List<Strike> Strikes;
		internal bool Done;
	}

	private static readonly object Gate = new();
	private static readonly List<Pending> Battles = new();
	private static bool _attempted;
	private static bool _disabled;
	private static ManualLogSource _log;
	private static int _logged;
	private static MethodInfo _applyDamage;
	private static Type _casterType;
	private static Type _castSourceType;
	private static object _fromMech;

	private static string At(string[] names, int index) => names != null && names.Length > index ? names[index] : "";
	private static string LogicBattleClone => At(GameSymbols.InfernoGating.LogicBattleCloneMembers, 0);
	private static string LogicGrid => At(GameSymbols.InfernoGating.LogicGridMembers, 0);
	private static string LogicHubs => At(GameSymbols.InfernoGating.LogicHubsMembers, 0);
	private static string LogicState => At(GameSymbols.InfernoGating.LogicStateMembers, 0);
	private static string HubsRoundHub => At(GameSymbols.InfernoGating.HubsRoundHubMembers, 0);
	private static string StateSideWrappers => At(GameSymbols.InfernoGating.StateSideWrappersMembers, 0);
	private static string SideWrapperTransferSide => At(GameSymbols.InfernoGating.SideWrapperTransferSideMembers, 0);
	private static string GridHexes => At(GameSymbols.InfernoGating.GridHexesMembers, 0);
	private static string FieldObjectSide => At(GameSymbols.InfernoGating.FieldObjectSideMembers, 0);

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			Type logicType = null;
			foreach (var hint in GameSymbols.InfernoGating.BattleLogicTypeHints ?? Array.Empty<string>())
			{
				if (!string.IsNullOrWhiteSpace(hint) && hexAssembly.GetType(hint) is { } type)
				{
					logicType = type;
					break;
				}
			}
			if (logicType == null)
				throw new TypeLoadException("BattleLogic type not found");
			var init = logicType.GetMethod("Init", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
				           new[] { typeof(int), typeof(TransferBattle), typeof(bool), typeof(bool) }, null)
			           ?? throw new MissingMethodException("BattleLogic.Init(int, TransferBattle, bool, bool)");
			var hubsProperty = FindProperty(logicType, LogicHubs) ?? throw new MissingMemberException(logicType.FullName + "." + LogicHubs);
			var hubType = (FindProperty(hubsProperty.PropertyType, HubsRoundHub) ?? throw new MissingMemberException(hubsProperty.PropertyType.FullName + "." + HubsRoundHub)).PropertyType;
			var roundStarted = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.RoundStartedDispatcher);
			ResolveDamageMethod();
			Patch(harmony, init, nameof(PostfixBattleLogicInit));
			Patch(harmony, roundStarted, nameof(PostfixRoundStarted));
			_log?.LogInfo("HoMM3 Factory Lightning Rod registered: round-1 strike for sides owning Factory towns with " + RodSid + ".");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Factory Lightning Rod NOT registered (the grail strike does nothing): " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Unit direct-damage method (8 params, void), resolved the way Homm3UnitKitBattleHooks does.</summary>
	private static void ResolveDamageMethod()
	{
		foreach (var name in GameSymbols.BattleEventLaws.BattleUnitApplyDamage.NameHints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name) || GameSymbolScope.IsSentinel(name))
				continue;
			foreach (var method in typeof(Unit).GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly | BindingFlags.Instance))
			{
				if (method.Name == name && !method.IsSpecialName && !method.ContainsGenericParameters && method.ReturnType == typeof(void)
				    && method.GetParameters().Length == 8)
				{
					_applyDamage = method;
					break;
				}
			}
			if (_applyDamage != null)
				break;
		}
		if (_applyDamage == null)
			throw new MissingMethodException("Unit apply-damage method (" + GameSymbols.BattleEventLaws.BattleUnitApplyDamage.Id + ")");
		var parameters = _applyDamage.GetParameters();
		_casterType = parameters[0].ParameterType;
		_castSourceType = parameters[1].ParameterType;
		var mechType = parameters[4].ParameterType;
		if (!mechType.IsEnum || !Enum.IsDefined(mechType, "AdditionalDamage"))
			throw new MissingMemberException(mechType.FullName + ".AdditionalDamage");
		_fromMech = Enum.Parse(mechType, "AdditionalDamage");
		if (parameters[3].ParameterType != typeof(int) || parameters[5].ParameterType != typeof(bool)
		    || parameters[6].ParameterType != typeof(float) || parameters[7].ParameterType != typeof(bool))
			throw new MissingMethodException("Unit apply-damage method shape changed: " + _applyDamage.Name);
	}

	private static void PostfixBattleLogicInit(object __instance, TransferBattle __1)
	{
		if (_disabled)
			return;
		try
		{
			if (__1?.sides == null)
				return;
			var clone = ReadProperty(__instance, LogicBattleClone) as TransferBattle;
			var strikes = new List<Strike>();
			for (var i = 0; i < __1.sides.Length; i++)
			{
				var side = __1.sides[i];
				if (side?.hero == null)
					continue;
				var damage = SideRodDamage(side, out var rods);
				if (damage <= 0)
					continue;
				object wrapper = null;
				if (clone?.sides != null && i < clone.sides.Length && clone.sides[i] != null)
					wrapper = FindSideWrapper(__instance, clone.sides[i]);
				wrapper ??= FindSideWrapper(__instance, side);
				if (wrapper == null)
				{
					LogLimited("side " + i + " owns " + rods + " Lightning Rod(s) but its battle side wrapper was not found; its strike is skipped.");
					continue;
				}
				strikes.Add(new Strike { Wrapper = wrapper, Damage = damage, Rods = rods });
			}
			if (strikes.Count == 0)
				return;
			var hub = ReadProperty(ReadProperty(__instance, LogicHubs), HubsRoundHub) as Il2CppObjectBase;
			if (hub == null)
			{
				LogLimited("round hub missing after Init; Lightning Rod strike skipped.");
				return;
			}
			lock (Gate)
			{
				Battles.RemoveAll(b => b.HubPointer == hub.Pointer);
				Battles.Add(new Pending { Logic = __instance, HubPointer = hub.Pointer, Strikes = strikes });
				while (Battles.Count > 6)
					Battles.RemoveAt(0);
			}
		}
		catch (Exception ex)
		{
			LogLimited("Init postfix failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Sum over owned Factory towns with the Rod of 7 x (4 + distinct built SIDs).</summary>
	private static int SideRodDamage(TransferSide side, out int rods)
	{
		rods = 0;
		var total = 0;
		foreach (var city in Homm3TownBuildingReader.SideCities(side))
		{
			if (city == null || !Homm3FactoryTownFacts.IsFactoryCity(city) || !Homm3TownBuildingReader.CityHasBuilding(city, RodSid))
				continue;
			var built = Homm3FactoryTownFacts.CountDistinctBuilt(city);
			if (built <= 0)
			{
				LogLimited("a Factory town with the Lightning Rod had an unreadable building list; that Rod is skipped.");
				continue;
			}
			rods++;
			total += DamagePerBuilding * (BaseBuildings + built);
		}
		return total;
	}

	private static void PostfixRoundStarted(object __instance, object[] __args)
	{
		if (_disabled)
			return;
		try
		{
			if (__instance is not Il2CppObjectBase hub || __args == null || __args.Length < 2 || __args[1] is not BattleEventArgs args || args.roundNumber < 1)
				return;
			Pending pending = null;
			lock (Gate)
			{
				foreach (var battle in Battles)
				{
					if (!battle.Done && battle.HubPointer == hub.Pointer)
					{
						pending = battle;
						battle.Done = true;
						break;
					}
				}
				if (pending != null)
					Battles.Remove(pending);
			}
			if (pending == null)
				return;
			var units = CollectUnits(pending.Logic);
			if (units == null)
			{
				LogLimited("battle grid missing at round 1; Lightning Rod strike skipped.");
				return;
			}
			foreach (var strike in pending.Strikes)
			{
				if (strike.Wrapper is not Il2CppObjectBase own)
					continue;
				Unit caster = null;
				foreach (var (unit, wrapper) in units)
				{
					if (wrapper.Pointer == own.Pointer && Homm3FortressPredatorInstinctRuntime.IsAlive(unit))
					{
						caster = unit;
						break;
					}
				}
				if (caster == null)
				{
					LogLimited("striking side has no living stack to act as the damage caster; its Lightning Rod strike is skipped.");
					continue;
				}
				if (!TryRewrap(caster, _casterType, out var casterArg, out var fail))
				{
					Disable("caster is not a native " + _casterType.Name + " (" + fail + ")");
					return;
				}
				var castSourceArg = TryRewrap(caster, _castSourceType, out var source, out _) ? source : null;
				var hit = 0;
				foreach (var (unit, wrapper) in units)
				{
					if (wrapper.Pointer == own.Pointer || !Homm3FortressPredatorInstinctRuntime.IsAlive(unit))
						continue;
					// immuneToDamage=false, scalar=0 (unused for a plain hit), cumulative=true.
					if (!NativeCombatWriteGateway.TryInvokeRedirectedDamage(_applyDamage, unit, casterArg, castSourceArg, null, strike.Damage, _fromMech, false, 0f, true, out fail))
					{
						Disable("damage invoke failed on " + Homm3FortressPredatorInstinctRuntime.DescribeUnit(unit) + ": " + fail);
						return;
					}
					hit++;
				}
				_log?.LogInfo("HoMM3 Factory Lightning Rod at round " + args.roundNumber + ": " + strike.Rods + " Rod(s), " + strike.Damage
				              + " damage to each of " + hit + " enemy stack(s).");
			}
		}
		catch (Exception ex)
		{
			LogLimited("RoundStarted handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static List<(Unit Unit, Il2CppObjectBase Wrapper)> CollectUnits(object logic)
	{
		if (ReadProperty(ReadProperty(logic, LogicGrid), GridHexes) is not Il2CppReferenceArray<BattleHex> hexes)
			return null;
		var result = new List<(Unit, Il2CppObjectBase)>();
		var seen = new HashSet<IntPtr>();
		foreach (var hex in hexes)
		{
			if (hex?.fieldObjects == null)
				continue;
			for (var i = 0; i < hex.fieldObjects.Count; i++)
			{
				var unit = hex.fieldObjects[i]?.TryCast<Unit>();
				// A large unit stands on two hexes: one entry per unit.
				if (unit == null || !seen.Add(unit.Pointer) || ReadProperty(unit, FieldObjectSide) is not Il2CppObjectBase wrapper)
					continue;
				result.Add((unit, wrapper));
			}
		}
		return result;
	}

	private static readonly Dictionary<Type, IntPtr> NativeClassByType = new();

	/// <summary>Re-wraps a proxy as <paramref name="expectedType"/> only when its native class implements it.</summary>
	private static bool TryRewrap(Il2CppObjectBase proxy, Type expectedType, out object typed, out string failReason)
	{
		typed = null;
		if (proxy == null || proxy.Pointer == IntPtr.Zero || !typeof(Il2CppObjectBase).IsAssignableFrom(expectedType))
		{
			failReason = "not a live interop object";
			return false;
		}
		if (expectedType.IsInstanceOfType(proxy))
		{
			typed = proxy;
			failReason = null;
			return true;
		}
		IntPtr expectedClass;
		lock (NativeClassByType)
		{
			if (!NativeClassByType.TryGetValue(expectedType, out expectedClass))
			{
				try
				{
					var store = typeof(Il2CppClassPointerStore<>).MakeGenericType(expectedType);
					RuntimeHelpers.RunClassConstructor(store.TypeHandle);
					expectedClass = store.GetField("NativeClassPtr", BindingFlags.Public | BindingFlags.Static)?.GetValue(null) is IntPtr ptr ? ptr : IntPtr.Zero;
				}
				catch
				{
					expectedClass = IntPtr.Zero;
				}
				NativeClassByType[expectedType] = expectedClass;
			}
		}
		if (expectedClass == IntPtr.Zero)
		{
			failReason = "native class of " + expectedType.FullName + " unresolved";
			return false;
		}
		var actual = IL2CPP.il2cpp_object_get_class(proxy.Pointer);
		if (actual == IntPtr.Zero || !IL2CPP.il2cpp_class_is_assignable_from(expectedClass, actual))
		{
			failReason = "native class is " + (actual == IntPtr.Zero ? "unknown" : Marshal.PtrToStringAnsi(IL2CPP.il2cpp_class_get_name(actual)));
			return false;
		}
		typed = Activator.CreateInstance(expectedType, proxy.Pointer);
		failReason = null;
		return typed != null;
	}

	private static void Disable(string reason)
	{
		_disabled = true;
		lock (Gate)
			Battles.Clear();
		_log?.LogWarning("HoMM3 Factory Lightning Rod disabled for this session: " + reason);
	}

	private static object FindSideWrapper(object logic, TransferSide side)
	{
		if (side == null)
			return null;
		if (ReadProperty(ReadProperty(logic, LogicState), StateSideWrappers) is not System.Collections.IEnumerable wrappers)
			return null;
		foreach (var wrapper in wrappers)
		{
			if (ReadProperty(wrapper, SideWrapperTransferSide) is TransferSide ts && ts.Pointer == side.Pointer)
				return wrapper;
		}
		return null;
	}

	private static readonly Dictionary<(Type, string), PropertyInfo> PropertyCache = new();

	private static PropertyInfo FindProperty(Type type, string name)
	{
		if (type == null || string.IsNullOrEmpty(name))
			return null;
		lock (PropertyCache)
		{
			if (PropertyCache.TryGetValue((type, name), out var cached))
				return cached;
			PropertyInfo found = null;
			for (var cur = type; cur != null && found == null; cur = cur.BaseType)
				found = cur.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			PropertyCache[(type, name)] = found;
			return found;
		}
	}

	private static object ReadProperty(object obj, string name)
	{
		if (obj == null)
			return null;
		var property = FindProperty(obj.GetType(), name);
		if (property != null)
			return property.GetValue(obj);
		var method = obj.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
		return method?.Invoke(obj, null);
	}

	private static void Patch(Harmony harmony, MethodInfo target, string postfixName)
	{
		var postfix = typeof(Homm3FactoryLightningRodRuntime).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
		if (postfix == null)
			throw new MissingMethodException("postfix missing for " + target?.DeclaringType?.FullName + "." + target?.Name);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException("postfix incompatible for " + target?.DeclaringType?.FullName + "." + target?.Name + ": " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static void LogLimited(string message)
	{
		if (_logged++ < 40)
			_log?.LogWarning("HoMM3 Factory Lightning Rod: " + message);
	}
}

/// <summary>Factory town facts shared by the Lightning Rod and the Mana Generator (building pass 2026-11-22).</summary>
internal static class Homm3FactoryTownFacts
{
	internal const string FactoryCitySid = "homm3_factory_city";

	/// <summary>The town's city config id, read from <c>BuildingData.citySid</c> (named live member) of its buildings.</summary>
	internal static string ReadCitySid(object city)
	{
		foreach (var building in Buildings(city))
		{
			var sid = (building as DataBuildingData ?? (building as Il2CppObjectBase)?.TryCast<DataBuildingData>())?.citySid;
			if (!string.IsNullOrWhiteSpace(sid))
				return sid;
		}
		return null;
	}

	internal static bool IsFactoryCity(object city) => string.Equals(ReadCitySid(city), FactoryCitySid, StringComparison.Ordinal);

	/// <summary>Distinct building SIDs built at level 1 or more (extra levels not counted); 0 when unreadable.</summary>
	internal static int CountDistinctBuilt(object city)
	{
		var sids = new HashSet<string>(StringComparer.Ordinal);
		foreach (var building in Buildings(city))
		{
			if (Homm3ConstructionNativeAdapter.TryReadBuildingIdentity(building, out var info, out _)
			    && info.IsConstructed && info.Level > 0 && !string.IsNullOrWhiteSpace(info.Sid))
				sids.Add(info.Sid);
		}
		return sids.Count;
	}

	/// <summary>The data city (<c>ObjCity</c>) behind a city context: ObjCity itself or the city logic's ObjCity.</summary>
	internal static DataObjCity ResolveObjCity(object city)
	{
		if (city is DataObjCity direct)
			return direct;
		var raw = Homm3TowerArtificingRuntime.ReadMember(city, Concat(GameSymbols.ConstructionCommitLaws.CityLogicObjCityMembers,
			GameSymbols.ConstructionCommitLaws.CityLogicObjCityAccessorMethods));
		return raw as DataObjCity ?? (raw as Il2CppObjectBase)?.TryCast<DataObjCity>()
		       ?? (city as Il2CppObjectBase)?.TryCast<DataObjCity>();
	}

	/// <summary>The BuildingsData all-buildings list (every section's rows), via the release-town-UI pins.</summary>
	private static IEnumerable<object> Buildings(object city)
	{
		if (city == null || !Homm3ConstructionNativeAdapter.TryResolveBuildingsDataFromCityContext(city, out var buildingsData, out _))
			yield break;
		var list = Homm3TowerArtificingRuntime.ReadMember(buildingsData, Concat(GameSymbols.ReleaseTownUi.BuildingDataListMembers,
			GameSymbols.ReleaseTownUi.BuildingDataListMethods));
		if (list == null)
			yield break;
		var type = list.GetType();
		var countProperty = type.GetProperty("Count", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		var indexer = type.GetMethod("get_Item", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new[] { typeof(int) }, null);
		if (countProperty?.GetValue(list) is not int count || indexer == null)
			yield break;
		for (var i = 0; i < count; i++)
		{
			var item = indexer.Invoke(list, new object[] { i });
			if (item != null)
				yield return item;
		}
	}

	private static string[] Concat(string[] a, string[] b)
	{
		var result = new string[(a?.Length ?? 0) + (b?.Length ?? 0)];
		a?.CopyTo(result, 0);
		b?.CopyTo(result, a?.Length ?? 0);
		return result;
	}
}
