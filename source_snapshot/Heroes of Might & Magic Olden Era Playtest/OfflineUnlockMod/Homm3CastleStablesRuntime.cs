using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using BuffDuration = Hex.Session.Data.BuffDuration;
using DataBuildingHeroBonusBank = Hex.Session.Data.BuildingHeroBonusBank;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Castle Stables (building pass 2026-11-22, docs/building_pass_20261122/castle.md): a hero visiting a Castle city that
/// has <c>Build_Stables</c> gets the vanilla adventure-map buff <c>stable_buff</c> (heroStat movementPerBonus 0.20) with
/// the vanilla Stables duration UntilNextWeek, once per hero per week (a hero still holding the buff is skipped).
///
/// The row is a heroBonusBanks carrier with no native bonus. The heroBonusBank logic class has its own HeroVisit and
/// OnConstruct overrides (the base Building virtuals are folded empty stubs and are never patched). For this SID only,
/// prefixes skip both natives: HeroVisit would record a once-ever visit and pop an empty bonus window, and OnConstruct
/// would pick a hero for the same empty popup. Every other heroBonusBank row runs natively.
///
/// Limitation: the buff raises max movement from the next day's refill; it does not top up the movement points of the
/// day of the visit (the vanilla Stables map object adds a separate MovePointsPercentAdditionReward for that).
/// No save state: the buff and its weekly expiry are native hero-buff data.
/// </summary>
internal static class Homm3CastleStablesRuntime
{
	internal const string StablesSid = "Build_Stables";
	internal const string StableBuffSid = "stable_buff";
	private const string LogPrefix = "HoMM3 Castle Stables: ";

	private static ManualLogSource _log;
	private static bool _attempted;
	private static bool _active;
	private static int _logged;
	private static PropertyInfo _heroLogicProperty;
	private static PropertyInfo _buffManagerProperty;
	private static MethodInfo _buffAdd, _buffGet;

	private static void Info(string message)
	{
		if (_logged++ < 120)
			_log?.LogInfo(LogPrefix + message);
	}

	private static void Warn(string message)
	{
		if (_logged++ < 120)
			_log?.LogWarning(LogPrefix + message);
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		try
		{
			if (!Homm3LogicBuildingShape.TryResolve(out var shapeFail))
				throw new MissingMemberException(shapeFail);
			var bankType = Homm3LogicBuildingShape.FindLogicTypeHoldingData(typeof(DataBuildingHeroBonusBank))
			               ?? throw new TypeLoadException("heroBonusBank logic type (field of type BuildingHeroBonusBank) not found or ambiguous");

			// HeroVisit override: the declared public virtual void(worldHero), where worldHero exposes the logic hero.
			MethodInfo visit = null;
			foreach (var m in bankType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly))
			{
				if (!m.IsVirtual || m.ReturnType != typeof(void) || m.Name == "Init")
					continue;
				var p = m.GetParameters();
				if (p.Length != 1 || FindLogicHeroProperty(p[0].ParameterType) is not { } heroProperty)
					continue;
				if (visit != null)
					throw new AmbiguousMatchException("two HeroVisit-shaped overrides on " + bankType.FullName);
				visit = m;
				_heroLogicProperty = heroProperty;
			}
			if (visit == null)
				throw new MissingMethodException(bankType.FullName, "HeroVisit override (public virtual void(worldHero))");
			var construct = Homm3LogicBuildingShape.FindDeclaredOnConstruct(bankType)
			                ?? throw new MissingMethodException(bankType.FullName, "OnConstruct override (protected virtual void())");

			_buffManagerProperty = typeof(LogicHero).GetProperty(GameSymbols.DungeonCaptives.LogicHeroBuffManagerMembers[0], BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			                       ?? throw new MissingMemberException("logic hero buff manager");
			var managerType = _buffManagerProperty.PropertyType;
			_buffAdd = Homm3TowerArtificingRuntime.ResolveExactMethod(managerType, typeof(void), new[] { typeof(string), typeof(Il2CppReferenceArray<BuffDuration>) }, GameSymbols.DungeonCaptives.BuffManagerAdd);
			_buffGet = Homm3TowerArtificingRuntime.ResolveExactMethod(managerType, null, new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerGet);

			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3CastleStablesRuntime), visit, nameof(PrefixHeroVisit), null);
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3CastleStablesRuntime), construct, nameof(PrefixOnConstruct), null);
			_active = true;
			_log?.LogInfo(LogPrefix + "registered on " + bankType.FullName + " visit=" + visit.Name + " construct=" + construct.Name + ".");
		}
		catch (Exception ex)
		{
			_active = false;
			_log?.LogWarning(LogPrefix + "NOT registered (Stables give no movement; a visit runs the empty native heroBonusBank): " + ex.GetBaseException().Message);
		}
	}

	private static PropertyInfo FindLogicHeroProperty(Type worldHeroType)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var named = worldHeroType.GetProperty(GameSymbols.CastleEliteStrategem.WorldHeroLogicHeroProperty, flags);
		if (named != null && named.PropertyType == typeof(LogicHero))
			return named;
		PropertyInfo match = null;
		foreach (var p in worldHeroType.GetProperties(flags))
		{
			if (p.PropertyType != typeof(LogicHero) || p.GetIndexParameters().Length != 0 || p.GetMethod == null)
				continue;
			if (match != null)
				return null;
			match = p;
		}
		return match;
	}

	private static bool IsStables(object building)
	{
		return Homm3LogicBuildingShape.TryReadIdentity(building, out var sid, out _, out _)
		       && string.Equals(sid, StablesSid, StringComparison.Ordinal);
	}

	/// <returns>false (skip native) for Build_Stables; true for every other heroBonusBank.</returns>
	private static bool PrefixHeroVisit(object __instance, object __0)
	{
		if (!_active)
			return true;
		try
		{
			if (!IsStables(__instance))
				return true;
			Grant(__0);
		}
		catch (Exception ex)
		{
			Warn("visit threw " + ex.GetBaseException().Message + "; no buff this visit.");
		}
		// The native visit has no bonus to give for this SID; skipping it also skips the once-ever record and popup.
		return false;
	}

	private static bool PrefixOnConstruct(object __instance)
	{
		if (!_active)
			return true;
		try
		{
			return !IsStables(__instance);
		}
		catch
		{
			return true;
		}
	}

	private static void Grant(object worldHero)
	{
		if (worldHero == null || _heroLogicProperty == null || !_heroLogicProperty.DeclaringType.IsInstanceOfType(worldHero))
			return;
		if (_heroLogicProperty.GetValue(worldHero) is not LogicHero hero || hero.Pointer == IntPtr.Zero)
			return;
		var manager = _buffManagerProperty.GetValue(hero);
		if (manager == null)
		{
			Warn("visiting hero has no buff manager; no Stables buff.");
			return;
		}
		if (_buffGet.Invoke(manager, new object[] { StableBuffSid }) != null)
			return; // Already has this week's Stables bonus.
		var durations = new Il2CppReferenceArray<BuffDuration>(1);
		durations[0] = new BuffDuration(EBuffDurationType.UntilNextWeek, 0);
		_buffAdd.Invoke(manager, new object[] { StableBuffSid, durations });
		if (_buffGet.Invoke(manager, new object[] { StableBuffSid }) != null)
			Info("visiting hero gets stable_buff (+20% movement until the end of the week).");
		else
			Warn("stable_buff did not stick on the visiting hero (heroes_buffs row missing?).");
	}
}
