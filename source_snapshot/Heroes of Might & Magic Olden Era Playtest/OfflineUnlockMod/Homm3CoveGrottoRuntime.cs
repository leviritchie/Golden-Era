using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime;
using UnityEngine;
using DataHero = Hex.Session.Data.Hero;
using DataObjCity = Hex.Session.Data.ObjCity;
using DataRoot = Hex.Session.Data.Data;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3/HotA Cove Grotto (building pass 2026-11-22, cove.md section 1 and 3): a hero in a Cove town that has
/// <c>Build_Grotto</c> may sacrifice creatures for experience, using the Altar of Sacrifice exchange.
///
/// Exchange (VCMI market CREATURE_EXP, the HoMM3 table): experience per creature = floor(value / 40) x 5, where value
/// is the creature's HoMM3 AI value. The port has no AI value, so the creature's UnitLogicConfig.squadValue stands in
/// (h3_pikeman 73 vs HoMM3 80, h3_angel 3731 vs 5019); the port's exp_standard level table equals HoMM3's through level 6,
/// so the experience scale is 1.0. Examples: Pikeman 5, Crew Mate 10, Angel 465 per creature. Paid through the native
/// hero experience component AddExp(xp, true) (the War Captives Execute path), so Learning and the native level-up loop apply.
///
/// Artifacts are not offered: the plugin has no proven native artifact-removal call, and writing the hero's
/// DataItemsContainer directly would desync item caches and bonuses. HotA artifact values for the record:
/// treasure 1000, minor 1500, major 3000, relic 6000 experience.
///
/// The window opens from a town-screen "Grotto" button (no custom building-click UI is proven in this plugin), shown
/// only while the town screen is open on a Cove town the local human owns, with the Grotto built and a hero present
/// (visitor first, else the garrison hero). Each sacrifice closes the window first (so a native level-up dialog is never
/// hidden under it), re-reads the army, removes the creatures through <see cref="Homm3PartyArmyWriter"/> (native party
/// calls, army read back), and pays experience only when the army reads back as written. The hero always keeps at
/// least one creature.
/// </summary>
internal static class Homm3CoveGrottoRuntime
{
	internal const string BuildingSid = "Build_Grotto";
	internal const string CoveFactionSid = "homm3_cove";
	internal const int ExpValueDivisor = 40;
	internal const int ExpPerStep = 5;
	private const string LogPrefix = "HoMM3 Cove Grotto: ";

	private static readonly string[] CityVisitorHeroMembers = { "visitorHeroId" };
	private static readonly string[] CityGarrisonHeroMembers = { "garnisonHeroId", "garrisonHeroId" };
	private static readonly string[] CityConfigSidMembers = { "sidConfig", "configSid" };
	private static readonly string[] CityOwnerMembers = { "ownerSide" };
	private static readonly string[] HeroLevelMembers = { "currentLevel", "level" };
	private static readonly string[] HeroExpMembers = { "currentExp", "exp" };

	private static ManualLogSource _log;
	private static bool _attempted;
	private static bool _registered;
	private static Type _logicHeroType;
	private static PropertyInfo _expComponentProperty;
	private static MethodInfo _expAddMethod;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static Type _cityCameraType;

	// Logic hero registry found by shape on the global logic root: root.<registry> -> List<Logic.Hero>.
	private static PropertyInfo _registryProperty;
	private static PropertyInfo _registryListProperty;
	private static readonly Dictionary<int, object> LogicHeroCache = new();
	private static int _loggedLookupFails;

	internal static bool IsRegistered => _registered;

	// ---------------------------------------------------------------- registration

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted)
			return;
		_attempted = true;
		_log = log;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			_logicHeroType = hexAssembly.GetType(GameSymbols.CastleEliteStrategem.LogicHeroTypeName)
			                 ?? throw new TypeLoadException("Missing " + GameSymbols.CastleEliteStrategem.LogicHeroTypeName);
			_logicHeroDataHeroGetter = ResolveMethod(_logicHeroType, typeof(DataHero), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter);
			var expName = GameSymbols.DungeonCaptives.LogicHeroExpComponentMembers[0];
			_expComponentProperty = _logicHeroType.GetProperty(expName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			                        ?? throw new MissingMemberException("homm3.cove.grotto.logicHero.expComponent property " + expName + " not found");
			_expAddMethod = ResolveMethod(_expComponentProperty.PropertyType, typeof(void), new[] { typeof(int), typeof(bool) }, GameSymbols.DungeonCaptives.ExpComponentAddExp);
			if (!Homm3PartyArmyWriter.TryResolve(_logicHeroType, out var writerFail))
				throw new InvalidOperationException("party writer unresolved: " + writerFail);
			_cityCameraType = ModActions.GetHexType(GameSymbols.FactoryCityScene.CityCameraControllerTypeName);
			if (!Homm3CoveGrottoWindow.EnsureTicker(out var tickerFail))
				throw new InvalidOperationException("town button ticker: " + tickerFail);
			_registered = true;
			_log?.LogInfo(LogPrefix + "registered: exp=" + _expAddMethod.DeclaringType?.Name + "." + _expAddMethod.Name
				+ ", writer=" + Homm3PartyArmyWriter.Describe() + ", city camera=" + (_cityCameraType?.Name ?? "unresolved (button gated on city data only)") + ".");
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + "NOT registered (fail closed: no Grotto button): " + ex.GetBaseException().Message);
		}
	}

	private static MethodInfo ResolveMethod(Type type, Type returnType, Type[] parameterTypes, GameSymbols.MethodSymbol symbol)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in symbol.NameHints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			MethodInfo found = null;
			var count = 0;
			foreach (var method in type.GetMethods(flags))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal) || method.ReturnType != returnType)
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != parameterTypes.Length)
					continue;
				var exact = true;
				for (var i = 0; i < parameters.Length && exact; i++)
					exact = parameters[i].ParameterType == parameterTypes[i];
				if (!exact)
					continue;
				found = method;
				count++;
			}
			if (count == 1)
				return found;
			if (count > 1)
				throw new AmbiguousMatchException(symbol.Id + " matched " + count + " methods named " + name + " on " + type.FullName);
		}
		throw new MissingMethodException(symbol.Id + " exact method not found on " + (type?.FullName ?? "null"));
	}

	// ---------------------------------------------------------------- town context

	internal sealed class Context
	{
		internal DataObjCity City;
		internal DataHero DataHero;
		internal object LogicHero;
		internal int HeroId;
		internal string HeroName;
		internal string CityName;
	}

	internal sealed class StackRow
	{
		internal int Slot;
		internal string Sid;
		internal string Name;
		internal int Count;
		internal int ExpEach;
	}

	/// <summary>Is the town screen open on a Cove town this local human owns, with the Grotto built and a hero present?</summary>
	internal static bool TryGetContext(out Context context, out string reason)
	{
		context = null;
		reason = null;
		if (!_registered)
		{
			reason = "not registered";
			return false;
		}
		var city = ModActions.GetCurrentCityData();
		if (city == null || city.Pointer == IntPtr.Zero)
		{
			reason = "no town open";
			return false;
		}
		if (!IsCoveCity(city))
		{
			reason = "not a Cove town";
			return false;
		}
		if (!Homm3TownBuildingReader.CityHasBuilding(city, BuildingSid))
		{
			reason = "Grotto not built";
			return false;
		}
		var owner = ReadInt(city, CityOwnerMembers, -1);
		if (owner < 0 || !Homm3FactoryLogisticsRuntime.IsLocalHuman(owner))
		{
			reason = "town not owned by the local human";
			return false;
		}
		var heroId = ReadInt(city, CityVisitorHeroMembers, -1);
		var hero = heroId >= 0 ? FindDataHero(heroId) : null;
		if (hero == null || hero.sideId != owner)
		{
			heroId = ReadInt(city, CityGarrisonHeroMembers, -1);
			hero = heroId >= 0 ? FindDataHero(heroId) : null;
		}
		if (hero == null || hero.sideId != owner)
		{
			reason = "no hero in town";
			return false;
		}
		context = new Context
		{
			City = city,
			DataHero = hero,
			HeroId = heroId,
			HeroName = Homm3HeroDisplayNames.Resolve(hero.configSid) ?? hero.configSid ?? "Hero",
			CityName = Homm3TowerArtificingRuntime.ReadMember(city, new[] { "cityName" }) as string,
		};
		return true;
	}

	/// <summary>Cheap per-frame gate for the town button: the native town camera is live (when resolvable).</summary>
	internal static bool TownSceneActive()
	{
		if (_cityCameraType == null)
			return true;
		try
		{
			var found = UnityObject.FindObjectsOfType(Il2CppType.From(_cityCameraType));
			return found != null && found.Length > 0;
		}
		catch
		{
			return true;
		}
	}

	private static bool IsCoveCity(DataObjCity city)
	{
		var fraction = ModActions.GetCurrentCityFraction();
		if (string.Equals(fraction, CoveFactionSid, StringComparison.OrdinalIgnoreCase))
			return true;
		var sid = Homm3TowerArtificingRuntime.ReadMember(city, CityConfigSidMembers) as string;
		return sid != null && sid.IndexOf(CoveFactionSid, StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static DataHero FindDataHero(int heroId)
	{
		if (!Homm3FactoryLogisticsEffects.TryGetData(out DataRoot data, out _) || data == null)
			return null;
		var heroes = Homm3TowerArtificingRuntime.ReadMember(data, GameSymbols.AdventureAiDecision.DataRootHeroesMembers);
		var list = heroes is Il2CppSystem.Object ? Homm3TowerArtificingRuntime.ReadMember(heroes, new[] { "list", "array" }) ?? heroes : heroes;
		foreach (var item in Homm3FactoryLogisticsEffects.Enumerate(list))
		{
			if (item is DataHero hero && Homm3FactoryLogisticsEffects.HeroId(hero) == heroId)
				return hero;
		}
		return null;
	}

	// ---------------------------------------------------------------- logic hero

	private static DataHero DataHeroOf(object logicHero)
	{
		if (logicHero == null || _logicHeroDataHeroGetter == null)
			return null;
		try
		{
			return _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) as DataHero;
		}
		catch
		{
			return null;
		}
	}

	private static bool Matches(object logicHero, DataHero dataHero)
	{
		if (logicHero is not Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase obj || obj.Pointer == IntPtr.Zero)
			return false;
		var dh = DataHeroOf(logicHero);
		return dh != null && dh.Pointer == dataHero.Pointer;
	}

	/// <summary>
	/// The logic hero of a data hero: the logistics cache, this runtime's cache, then the global logic root's hero
	/// registry (found by shape: a root property whose type carries a List&lt;Logic.Hero&gt; property).
	/// </summary>
	internal static bool TryResolveLogicHero(Context context, out string failReason)
	{
		failReason = null;
		var dataHero = context.DataHero;
		object found = Homm3FactoryLogisticsRuntime.CachedLogicHero(dataHero);
		if (found == null && LogicHeroCache.TryGetValue(context.HeroId, out var cached) && Matches(cached, dataHero))
			found = cached;
		if (found == null)
		{
			foreach (var candidate in RegistryHeroes(out failReason))
			{
				if (!Matches(candidate, dataHero))
					continue;
				found = candidate;
				break;
			}
		}
		if (found == null)
		{
			failReason ??= "hero not in the logic hero registry";
			if (_loggedLookupFails++ < 5)
				_log?.LogWarning(LogPrefix + "logic hero lookup failed for hero " + context.HeroId + ": " + failReason);
			return false;
		}
		LogicHeroCache[context.HeroId] = found;
		context.LogicHero = found;
		return true;
	}

	private static IEnumerable<object> RegistryHeroes(out string failReason)
	{
		failReason = null;
		var result = new List<object>();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var root in LogicRoots())
		{
			if (_registryProperty != null && _registryProperty.DeclaringType.IsInstanceOfType(root))
			{
				CollectFrom(SafeGet(_registryProperty, root), _registryListProperty, result);
				if (result.Count > 0)
					return result;
			}
			foreach (var property in root.GetType().GetProperties(flags))
			{
				if (property.GetIndexParameters().Length != 0 || property.GetGetMethod(true) == null)
					continue;
				var listProperty = HeroListProperty(property.PropertyType);
				if (listProperty == null)
					continue;
				CollectFrom(SafeGet(property, root), listProperty, result);
				if (result.Count == 0)
					continue;
				_registryProperty = property;
				_registryListProperty = listProperty;
				_log?.LogInfo(LogPrefix + "logic hero registry: " + root.GetType().Name + "." + property.Name + " -> " + listProperty.Name + ".");
				return result;
			}
		}
		failReason = "logic hero registry not found on the logic root";
		return result;
	}

	private static PropertyInfo HeroListProperty(Type registryType)
	{
		if (registryType == null || registryType.IsPrimitive || registryType == typeof(string))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var property in registryType.GetProperties(flags))
		{
			var type = property.PropertyType;
			if (property.GetIndexParameters().Length != 0 || !type.IsGenericType || !type.Name.StartsWith("List`1", StringComparison.Ordinal))
				continue;
			var args = type.GetGenericArguments();
			if (args.Length == 1 && args[0] == _logicHeroType)
				return property;
		}
		return null;
	}

	private static void CollectFrom(object registry, PropertyInfo listProperty, List<object> result)
	{
		if (registry == null || listProperty == null)
			return;
		foreach (var item in Homm3FactoryLogisticsEffects.Enumerate(SafeGet(listProperty, registry)))
		{
			if (_logicHeroType.IsInstanceOfType(item))
				result.Add(item);
		}
	}

	private static IEnumerable<object> LogicRoots()
	{
		foreach (var typeName in GameSymbols.CustomFactionLawRuntime.GlobalLogicRootTypeHints)
		{
			var type = string.IsNullOrWhiteSpace(typeName) ? null : GameMember.FindType("cove.grotto.globalLogicRoot." + typeName, typeName, null, false);
			if (type == null)
				continue;
			foreach (var name in GameSymbols.CustomFactionLawRuntime.GlobalLogicRootInstanceMembers)
			{
				if (TryReadStatic(type, name, out var root) && root != null)
				{
					yield return root;
					break;
				}
			}
		}
	}

	private static bool TryReadStatic(Type type, string name, out object value)
	{
		value = null;
		if (string.IsNullOrWhiteSpace(name))
			return false;
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			RuntimeHelpers.RunClassConstructor(type.TypeHandle);
		}
		catch
		{
		}
		try
		{
			var property = type.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0 && property.GetGetMethod(true) != null)
			{
				value = property.GetValue(null);
				return value != null;
			}
			var field = type.GetField(name, flags);
			if (field != null)
			{
				value = field.GetValue(null);
				return value != null;
			}
		}
		catch
		{
		}
		return false;
	}

	private static object SafeGet(PropertyInfo property, object target)
	{
		try
		{
			return property.GetValue(target);
		}
		catch
		{
			return null;
		}
	}

	// ---------------------------------------------------------------- exchange

	/// <summary>Experience for one creature of this sid: floor(squadValue / 40) x 5 (0 when the config is unknown).</summary>
	internal static int ExpPerCreature(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return 0;
		UnitLogicConfig config;
		try
		{
			config = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(sid);
		}
		catch
		{
			return 0;
		}
		if (config == null)
			return 0;
		return Math.Max(0, config.squadValue) / ExpValueDivisor * ExpPerStep;
	}

	internal static bool TryReadStacks(Context context, out List<StackRow> stacks, out int totalCreatures, out string failReason)
	{
		stacks = new List<StackRow>();
		totalCreatures = 0;
		if (context.LogicHero == null && !TryResolveLogicHero(context, out failReason))
			return false;
		if (!Homm3PartyArmyWriter.TryReadArmy(context.LogicHero, context.DataHero, out var slotSid, out var slotCount, out _, out failReason))
			return false;
		for (var slot = 0; slot < slotSid.Length; slot++)
		{
			if (slotSid[slot] == null || slotCount[slot] <= 0)
				continue;
			totalCreatures += slotCount[slot];
			stacks.Add(new StackRow
			{
				Slot = slot,
				Sid = slotSid[slot],
				Name = Homm3UnitDisplayNames.Resolve(slotSid[slot]) ?? slotSid[slot],
				Count = slotCount[slot],
				ExpEach = ExpPerCreature(slotSid[slot]),
			});
		}
		return true;
	}

	/// <summary>Most creatures of a stack that may go while the hero keeps at least one creature.</summary>
	internal static int MaxSacrifice(StackRow row, int totalCreatures)
	{
		if (row == null || row.ExpEach <= 0)
			return 0;
		return Math.Max(0, Math.Min(row.Count, totalCreatures - 1));
	}

	internal static int HeroLevel(DataHero hero) => Homm3TowerArtificingRuntime.ReadMember(hero, HeroLevelMembers) is int v ? v : -1;

	internal static long HeroExp(DataHero hero)
	{
		var value = Homm3TowerArtificingRuntime.ReadMember(hero, HeroExpMembers);
		return value switch
		{
			int i => i,
			long l => l,
			_ => -1,
		};
	}

	/// <summary>
	/// Removes <paramref name="count"/> creatures from the stack in <paramref name="slot"/> (which must still hold
	/// <paramref name="sid"/>) and pays the experience. Returns the player-facing result line.
	/// </summary>
	internal static string Sacrifice(Context context, int slot, string sid, int count)
	{
		try
		{
			if (context == null || count <= 0)
				return "Nothing was sacrificed.";
			if (context.LogicHero == null && !TryResolveLogicHero(context, out var heroFail))
				return "The Grotto could not reach the hero (" + heroFail + ").";
			if (!Homm3PartyArmyWriter.TryReadArmy(context.LogicHero, context.DataHero, out var slotSid, out var slotCount, out var totals, out var readFail))
				return "The Grotto could not read the army (" + readFail + ").";
			if (slot < 0 || slot >= slotSid.Length || !string.Equals(slotSid[slot], sid, StringComparison.Ordinal))
				return "The army changed; nothing was sacrificed.";
			var total = 0;
			foreach (var c in slotCount)
				total += Math.Max(0, c);
			count = Math.Min(count, slotCount[slot]);
			if (total - count < 1)
				count = total - 1;
			var expEach = ExpPerCreature(sid);
			if (count <= 0 || expEach <= 0)
				return "The hero must keep at least one creature.";

			var targetSid = (string[])slotSid.Clone();
			var targetCount = (int[])slotCount.Clone();
			targetCount[slot] -= count;
			if (targetCount[slot] <= 0)
			{
				targetCount[slot] = 0;
				targetSid[slot] = null;
			}
			var steps = new List<string>();
			var result = Homm3PartyArmyWriter.Write(context.LogicHero, context.DataHero, targetSid, targetCount, totals, steps, out var writeFail);
			var name = Homm3UnitDisplayNames.Resolve(sid) ?? sid;
			switch (result)
			{
				case Homm3PartyArmyWriter.WriteResult.Refused:
					return "Nothing was sacrificed (" + writeFail + ").";
				case Homm3PartyArmyWriter.WriteResult.WriteFailed:
					_log?.LogError(LogPrefix + "army write failed after [" + string.Join(", ", steps) + "]: " + writeFail + "; no experience paid.");
					return "The sacrifice failed while changing the army (see the log).";
				case Homm3PartyArmyWriter.WriteResult.ReadBackMismatch:
					_log?.LogError(LogPrefix + "army reads back differently [" + writeFail + "] after [" + string.Join(", ", steps) + "]; no experience paid.");
					return "The army did not update as expected; no experience was paid (see the log).";
			}

			var xp = (long)count * expEach;
			var paid = (int)Math.Min(int.MaxValue, xp);
			var expComponent = _expComponentProperty.GetValue(context.LogicHero);
			if (expComponent == null)
			{
				_log?.LogError(LogPrefix + count + " " + sid + " removed but the hero exp component is null; " + paid + " exp unpaid.");
				return count.ToString(CultureInfo.InvariantCulture) + " " + name + " sacrificed, but the experience could not be paid (see the log).";
			}
			var before = HeroExp(context.DataHero);
			_expAddMethod.Invoke(expComponent, new object[] { paid, true });
			var after = HeroExp(context.DataHero);
			_log?.LogInfo(LogPrefix + context.HeroName + " sacrificed " + count + " " + sid + " (slot " + slot + ") for " + paid
				+ " exp (" + expEach + " each); hero exp " + before + " -> " + after + "; steps [" + string.Join(", ", steps) + "].");
			return context.HeroName + " sacrificed " + count.ToString("N0", CultureInfo.InvariantCulture) + " " + name
			       + " for " + paid.ToString("N0", CultureInfo.InvariantCulture) + " experience.";
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + "sacrifice failed: " + ex.GetBaseException().Message);
			return "The sacrifice failed (see the log).";
		}
	}

	// ---------------------------------------------------------------- helpers

	private static int ReadInt(object target, string[] names, int fallback)
	{
		var value = Homm3TowerArtificingRuntime.ReadMember(target, names);
		return value switch
		{
			int i => i,
			long l when l >= int.MinValue && l <= int.MaxValue => (int)l,
			short s => s,
			_ => fallback,
		};
	}
}
