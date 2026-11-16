using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Hex.Session.Logic;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using BuffDuration = Hex.Session.Data.BuffDuration;
using DataHero = Hex.Session.Data.Hero;
using DataObjHire = Hex.Session.Data.ObjHire;
using DataObjResMine = Hex.Session.Data.ObjResMine;
using DataSide = Hex.Session.Data.Side;
using LogicHero = Hex.Session.Logic.Hero;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Factory Logistics Network runtime (replaces Split Assembly; design docs/factory_logistics_network_design.md, API
/// docs/factory_logistics_runtime_contract.md). Native hooks:
/// - mine logic OnStartDay prefix: Export Office / logistics functions suppress the mine's own output (return false);
///   Export Office pays gold, Byproduct Processing pays gold plus extra output (fractions pooled in the carrier).
/// - mine + dwelling hero-visit postfixes: Upgrade Center marker, then <see cref="Homm3FactoryLogistics.VisitRequested"/>
///   (queued until no native hire window is open).
/// - mine + dwelling owner-change postfixes and every day start: capture wipe (enhancements of a building whose owner
///   is no longer the recorded side are destroyed).
/// - side logic OnStartDay prefix/postfix: pending switches / remote builds apply, Housing price, Arcane hero buffs.
/// - dwelling OnStartWeek prefix/postfix: Food Distribution Center and Support Hub reach add units, a Support Hub withholds its own, Mercenary HQ converts them to gold.
/// - world spell homm3_factory_logistics_network (Necromancer Will mode, like Conflux Fusion) opens the network viewer.
/// Local human sides only. State lives in a hidden side buff (Homm3FactoryLogisticsState). Proof tier: build only.
/// </summary>
internal static class Homm3FactoryLogisticsRuntime
{
	internal const string LogPrefix = "[FactoryLogistics] ";
	internal const string SpellMode = "homm3_factory_logistics_network";
	internal static bool Verbose;

	private static ManualLogSource _log;
	private static bool _attempted;
	internal static bool MineHooks, DwellingHooks, SideHooks, SpellHook, WeekHooks;
	private static Type _mineLogicType, _dwellingLogicType, _sideLogicType;
	private static PropertyInfo _dwellingHireProperty;
	private static PropertyInfo _sideDataProperty;
	private static PropertyInfo _handlerWorldHeroProperty;
	private static PropertyInfo _worldHeroLogicHeroProperty;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static PropertyInfo _buffManagerProperty;
	private static MethodInfo _buffAdd, _buffRemove, _buffGet;
	private static readonly Dictionary<string, int> _onceDay = new(StringComparer.Ordinal);
	private static readonly Dictionary<int, LogicHero> _logicHeroes = new();
	private static readonly HashSet<(int obj, int day)> _mineDayDone = new();
	private static readonly Dictionary<IntPtr, int[]> _weekSnapshot = new();
	private static readonly List<(DataHero hero, long key, float since)> _visitQueue = new();
	/// <summary>Skilled visits to a building not (yet) owned by the hero's side: a guard battle may follow (UX item 23).</summary>
	private static readonly Dictionary<int, PendingGuardVisit> _guardVisits = new();
	/// <summary>Hint for heroes without the skill: object id -> day it was last shown (UX item 22, once per building per day).</summary>
	private static readonly Dictionary<int, int> _hintDay = new();
	/// <summary>Side -> hero id of the last skilled hero that cast the spell or visited (the Ctrl+L hotkey prefers it).</summary>
	private static readonly Dictionary<int, int> _lastSkilledHero = new();
	private static readonly HashSet<(int side, int day)> _astrologyDayDone = new();
	private static Type _astrologyProgressType;
	private static MethodInfo _astrologyAdd;
	private static GameObject _hostObject;
	private static bool _hostTypeRegistered;
	private static int _eventLogs;

	// ---------------------------------------------------------------- logging

	internal static void LogInfo(string message) => (_log ?? Plugin.LogSource)?.LogInfo(LogPrefix + message);
	internal static void LogWarning(string message) => (_log ?? Plugin.LogSource)?.LogWarning(LogPrefix + message);
	internal static void LogError(string message) => (_log ?? Plugin.LogSource)?.LogError(LogPrefix + message);

	internal static void LogEvent(string message)
	{
		if (Verbose || _eventLogs++ < 400)
			LogInfo(message);
	}

	internal static void LogOncePerDay(string key, string message)
	{
		var day = Homm3FactoryLogisticsEffects.TryReadDay(out var d, out _, out _) ? d : -1;
		if (_onceDay.TryGetValue(key, out var last) && last == day)
			return;
		_onceDay[key] = day;
		LogWarning(message);
	}

	// ---------------------------------------------------------------- session

	private static IntPtr _sessionRoot, _sessionData;

	/// <summary>Re-reads the live session (Effects.TryGetData), which resets every cache when the key changed.</summary>
	internal static void ResetIfSessionChanged() => Homm3FactoryLogisticsEffects.TryGetData(out _, out _);

	/// <summary>
	/// Session key = (logic-root pointer, Data pointer). A changed Data pointer, or a changed non-zero root pointer,
	/// is a new session (load, new game, return to menu); a zero root (fallback Data path) never counts as a change.
	/// </summary>
	internal static void NoteSessionKey(IntPtr root, IntPtr data)
	{
		if (data == IntPtr.Zero)
			return;
		var changed = data != _sessionData || (root != IntPtr.Zero && _sessionRoot != IntPtr.Zero && root != _sessionRoot);
		if (root != IntPtr.Zero)
			_sessionRoot = root;
		if (!changed)
			return;
		var first = _sessionData == IntPtr.Zero;
		_sessionData = data;
		ResetSession(first ? "first session seen" : "session changed");
	}

	/// <summary>The single reset: every logistics runtime cache is cleared here and nowhere else.</summary>
	private static void ResetSession(string why)
	{
		Homm3FactoryLogisticsState.ClearCache();
		Homm3FactoryLogisticsEffects.ClearSessionCaches();
		_logicHeroes.Clear();
		_mineDayDone.Clear();
		_astrologyDayDone.Clear();
		_weekSnapshot.Clear();
		_visitQueue.Clear();
		_onceDay.Clear();
		_guardVisits.Clear();
		_hintDay.Clear();
		_lastSkilledHero.Clear();
		Homm3FactoryLogisticsDigest.Clear();
		_spellAiLogs = 0;
		Homm3FactoryLogisticsRange.Invalidate();
		LogInfo("session reset (" + why + "): state, heroes, mine config, network, day markers and range caches cleared.");
	}

	private static void MarkDirty(Homm3FactoryLogisticsState.SideState state, string why) => Homm3FactoryLogisticsState.MarkDirty(state, why);

	// ---------------------------------------------------------------- registration

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		Verbose = string.Equals(Environment.GetEnvironmentVariable("OE_FACTORY_LOGISTICS_VERBOSE"), "1", StringComparison.Ordinal);
		var configOk = Homm3FactoryLogisticsConfig.TryLoad(out var config, out var configFail);
		var hexAssembly = typeof(TransferBattle).Assembly;
		var notes = new List<string>();

		// Logic hero -> data hero, world hero -> logic hero (spell + visits).
		try
		{
			var worldHeroType = Homm3TowerArtificingRuntime.ResolveTypeByHints(hexAssembly, GameSymbols.HomecomingBoatTravel.WorldHeroTypeHints, "homm3.factory.logistics.worldHero");
			_worldHeroLogicHeroProperty = worldHeroType.GetProperty(GameSymbols.CastleEliteStrategem.WorldHeroLogicHeroProperty, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			                              ?? throw new MissingMemberException("world hero logic hero property");
			_logicHeroDataHeroGetter = Homm3TowerArtificingRuntime.ResolveExactMethod(typeof(LogicHero), typeof(DataHero), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter);
		}
		catch (Exception ex)
		{
			LogError("hero resolution failed (visits and the spell cannot identify heroes): " + ex.GetBaseException().Message);
		}

		// Hero buff manager (Arcane Manufactory stat buffs).
		try
		{
			_buffManagerProperty = typeof(LogicHero).GetProperty(GameSymbols.DungeonCaptives.LogicHeroBuffManagerMembers[0], BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			                       ?? throw new MissingMemberException("logic hero buff manager (DungeonCaptives.LogicHeroBuffManagerMembers)");
			var managerType = _buffManagerProperty.PropertyType;
			_buffAdd = Homm3TowerArtificingRuntime.ResolveExactMethod(managerType, typeof(void), new[] { typeof(string), typeof(Il2CppReferenceArray<BuffDuration>) }, GameSymbols.DungeonCaptives.BuffManagerAdd);
			_buffRemove = Homm3TowerArtificingRuntime.ResolveExactMethod(managerType, typeof(void), new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerRemove);
			_buffGet = FindMethodByHints(managerType, GameSymbols.DungeonCaptives.BuffManagerGet.NameHints, new[] { typeof(string) });
			if (_buffGet == null)
				throw new MissingMethodException("buff manager Get (DungeonCaptives.BuffManagerGet)");
			notes.Add("hero buffs ok");
		}
		catch (Exception ex)
		{
			_buffManagerProperty = null;
			LogError("hero buff manager unresolved (Arcane Manufactory hero stats off): " + ex.GetBaseException().Message);
		}

		// Mines.
		MethodInfo[] mineVisits = Array.Empty<MethodInfo>();
		MethodInfo mineOwner = null;
		try
		{
			_mineLogicType = GameMember.FindType(GameSymbols.CovePlunder.MineLogicTypeId, GameSymbols.CovePlunder.MineLogicTypeHint)
			                 ?? throw new TypeLoadException("mine logic type (CovePlunder.MineLogicTypeHint)");
			var startDay = _mineLogicType.GetMethod(GameSymbols.SwashbucklerGold.SideStartDayName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null)
			               ?? throw new MissingMethodException(_mineLogicType.FullName, GameSymbols.SwashbucklerGold.SideStartDayName);
			mineVisits = GameMember.FindMethodsByNames(_mineLogicType, 1, GameSymbols.CovePlunder.MineHeroVisitMethods.Id, GameSymbols.CovePlunder.MineHeroVisitMethods.NameHints);
			var owners = GameMember.FindMethodsByNames(_mineLogicType, 2, GameSymbols.CovePlunder.MineOwnerChanged.Id, GameSymbols.CovePlunder.MineOwnerChanged.NameHints);
			mineOwner = owners.Length == 1 ? owners[0] : null;
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3FactoryLogisticsRuntime), startDay, nameof(PrefixMineStartDay), null);
			foreach (var m in mineVisits)
				Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3FactoryLogisticsRuntime), m, null, nameof(PostfixMineVisit));
			if (mineOwner != null)
				Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3FactoryLogisticsRuntime), mineOwner, null, nameof(PostfixOwnerChanged));
			MineHooks = true;
			notes.Add("mine OnStartDay + " + mineVisits.Length + " visit + " + (mineOwner == null ? "NO" : "1") + " owner-change hook(s) on " + _mineLogicType.Name);
		}
		catch (Exception ex)
		{
			LogError("mine hooks NOT registered (mine enhancements have no effect, visits open nothing): " + ex.GetBaseException().Message);
		}

		// Dwellings: the map logic with ctor(ObjHire) and a real-name OnStartWeek (found by shape, no new symbol).
		try
		{
			_dwellingLogicType = FindDwellingLogicType() ?? throw new TypeLoadException("dwelling logic type (ctor(ObjHire) + OnStartWeek) not found");
			_dwellingHireProperty = FindPropertyOfType(_dwellingLogicType, typeof(DataObjHire)) ?? throw new MissingMemberException(_dwellingLogicType.FullName, "ObjHire property");
			var startWeek = _dwellingLogicType.GetMethod("OnStartWeek", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3FactoryLogisticsRuntime), startWeek, nameof(PrefixDwellingStartWeek), nameof(PostfixDwellingStartWeek));
			WeekHooks = true;
			var visits = 0;
			foreach (var m in mineVisits)
			{
				var twin = _dwellingLogicType.GetMethod(m.Name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, ParameterTypes(m), null);
				if (twin == null || twin.DeclaringType != _dwellingLogicType)
					continue;
				Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3FactoryLogisticsRuntime), twin, null, nameof(PostfixDwellingVisit));
				visits++;
			}
			var ownerTwin = mineOwner == null ? null : _dwellingLogicType.GetMethod(mineOwner.Name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, ParameterTypes(mineOwner), null);
			if (ownerTwin != null && ownerTwin.DeclaringType == _dwellingLogicType)
				Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3FactoryLogisticsRuntime), ownerTwin, null, nameof(PostfixOwnerChanged));
			DwellingHooks = visits > 0;
			notes.Add("dwelling OnStartWeek + " + visits + " visit + " + (ownerTwin == null ? "NO" : "1") + " owner-change hook(s) on " + _dwellingLogicType.Name);
		}
		catch (Exception ex)
		{
			LogError("dwelling hooks NOT registered (dwelling enhancements have no weekly effect): " + ex.GetBaseException().Message);
		}

		// Side day start.
		try
		{
			_sideLogicType = GameMember.FindType(GameSymbols.SwashbucklerGold.SideLogicTypeId, GameSymbols.SwashbucklerGold.SideLogicTypeHint)
			                 ?? throw new TypeLoadException("side logic type (SwashbucklerGold.SideLogicTypeHint)");
			_sideDataProperty = FindPropertyOfType(_sideLogicType, typeof(DataSide)) ?? throw new MissingMemberException(_sideLogicType.FullName, "Side property");
			var startDay = _sideLogicType.GetMethod(GameSymbols.SwashbucklerGold.SideStartDayName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null)
			               ?? throw new MissingMethodException(_sideLogicType.FullName, GameSymbols.SwashbucklerGold.SideStartDayName);
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3FactoryLogisticsRuntime), startDay, nameof(PrefixSideStartDay), nameof(PostfixSideStartDay));
			SideHooks = true;
			notes.Add("side OnStartDay on " + _sideLogicType.Name);
		}
		catch (Exception ex)
		{
			LogError("side day-start hook NOT registered (pending switches apply lazily on the next read only): " + ex.GetBaseException().Message);
		}

		// Trade Contracts: +markets on the world side's native market count (every trade price reads it).
		try
		{
			var worldSideType = Homm3TowerArtificingRuntime.ResolveTypeByHints(hexAssembly, GameSymbols.HomecomingBoatTravel.MovementTypeHints, "homm3.factory.logistics.worldSide");
			_worldSideDataProperty = FindPropertyOfType(worldSideType, typeof(DataSide));
			_worldSideLogicProperty = _worldSideDataProperty == null && _sideLogicType != null && _sideDataProperty != null ? FindPropertyOfType(worldSideType, _sideLogicType) : null;
			if (_worldSideDataProperty == null && _worldSideLogicProperty == null)
				throw new MissingMemberException(worldSideType.FullName, "Side / side logic property");
			var count = GameMember.FindFirstMethodByNames(worldSideType, Type.EmptyTypes, GameSymbols.FactoryLogisticsMarket.MarketsCount);
			if (count == null || count.IsStatic || count.ReturnType != typeof(int))
				throw new MissingMethodException(worldSideType.FullName, "market count (FactoryLogisticsMarket.MarketsCount)");
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3FactoryLogisticsRuntime), count, null, nameof(PostfixMarketsCount));
			notes.Add("market count " + count.Name + " on " + worldSideType.Name);
		}
		catch (Exception ex)
		{
			LogError("market count hook NOT registered (Trade Contracts gives only the native +1 market): " + ex.GetBaseException().Message);
		}

		// Hero list consumer: caches logic heroes and refreshes Arcane buffs per hero at day start.
		if (Homm3SwashbucklerGoldHook.TryRegisterDayStartHeroConsumer("factory_logistics", DayStartHero, out var consumerFail))
			notes.Add("day-start hero consumer");
		else
			LogWarning("day-start hero consumer not registered (" + consumerFail + "); Arcane buffs refresh only for heroes seen at a visit or cast.");

		// World spell.
		MethodInfo castMethod = null;
		try
		{
			var handlerType = Homm3TowerArtificingRuntime.ResolveTypeByHints(hexAssembly, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicHandlerTypeHints, "homm3.factory.logistics.necromancyHandler");
			castMethod = Homm3TowerArtificingRuntime.ResolveExactMethod(handlerType, typeof(bool), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicCast);
			_handlerWorldHeroProperty = handlerType.GetProperty(GameSymbols.CastleEliteStrategem.NecromancyWorldMagicWorldHeroProperty, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			                            ?? throw new MissingMemberException(handlerType.FullName, "world hero property");
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3FactoryLogisticsRuntime), castMethod, nameof(PrefixSpellCast), null);
			SpellHook = true;
			notes.Add("spell prefix for mode " + SpellMode);
		}
		catch (Exception ex)
		{
			Homm3TowerArtificingRuntime.UnpatchOwned(harmony, typeof(Homm3FactoryLogisticsRuntime), castMethod, nameof(PrefixSpellCast));
			LogError("spell hook NOT registered (the Logistics Network spell would reach the native Necromancer Will toggle): " + ex.GetBaseException().Message);
		}

		// The runtime host ticks the visit queue, the notices and the Ctrl+L hotkey from the start.
		EnsureHost();
		var writer = Homm3PartyArmyWriter.TryResolve(typeof(LogicHero), out var writerFail);
		LogInfo("registered: " + string.Join("; ", notes) + "; army writer " + (writer ? "ok" : "FAILED (" + writerFail + "; remote hire refuses)")
			+ "; config " + (configOk ? Homm3FactoryLogisticsConfig.ConfigPath + " (" + config.Enhancements.Count + " enhancements)" : "NOT LOADED (" + configFail + "; every effect off until it loads)")
			+ ". Local human sides only. Proof tier: build; runtime unproven.");
	}

	private static Type[] ParameterTypes(MethodInfo m)
	{
		var ps = m.GetParameters();
		var types = new Type[ps.Length];
		for (var i = 0; i < ps.Length; i++)
			types[i] = ps[i].ParameterType;
		return types;
	}

	private static MethodInfo FindMethodByHints(Type type, string[] names, Type[] parameters)
	{
		foreach (var name in names ?? Array.Empty<string>())
		{
			var m = type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, parameters, null);
			if (m != null)
				return m;
		}
		return null;
	}

	private static PropertyInfo FindPropertyOfType(Type type, Type propertyType)
	{
		PropertyInfo found = null;
		foreach (var p in type.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (p.PropertyType != propertyType || p.GetIndexParameters().Length != 0 || p.GetGetMethod(true) == null)
				continue;
			if (found != null && found.Name != p.Name)
			{
				// Prefer the interop field wrapper (field_*) when there are several; both read the same object.
				if (p.Name.StartsWith("field_", StringComparison.Ordinal))
					found = p;
				continue;
			}
			found = p;
		}
		return found;
	}

	private static Type FindDwellingLogicType()
	{
		Type match = null;
		foreach (var type in GameMember.EnumerateHexTypes())
		{
			try
			{
				// Exact parameter type: GetConstructor also accepts widening, so the shared map-logic base
				// ctor(DataObject) matched too and made the shape ambiguous (2026-11-16 playtest).
				var ctor = type == null || type.IsAbstract ? null : type.GetConstructor(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new[] { typeof(DataObjHire) }, null);
				var ctorParams = ctor?.GetParameters();
				if (ctorParams == null || ctorParams.Length != 1 || ctorParams[0].ParameterType != typeof(DataObjHire))
					continue;
				var week = type.GetMethod("OnStartWeek", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly, null, Type.EmptyTypes, null);
				if (week == null)
					continue;
				if (match != null)
				{
					LogWarning("dwelling logic shape is ambiguous (" + match.FullName + ", " + type.FullName + "); refusing.");
					return null;
				}
				match = type;
			}
			catch
			{
				// Types that fail to reflect are not the dwelling logic.
			}
		}
		return match;
	}

	// ---------------------------------------------------------------- shared helpers

	internal static bool TryResolveHeroFromWorldHero(object worldHero, out LogicHero logicHero, out DataHero dataHero)
	{
		logicHero = null;
		dataHero = null;
		if (worldHero == null || _worldHeroLogicHeroProperty == null || !_worldHeroLogicHeroProperty.DeclaringType.IsInstanceOfType(worldHero))
			return false;
		logicHero = _worldHeroLogicHeroProperty.GetValue(worldHero) as LogicHero;
		dataHero = DataHeroOf(logicHero);
		return dataHero != null;
	}

	internal static DataHero DataHeroOf(LogicHero logicHero)
	{
		if (logicHero == null || _logicHeroDataHeroGetter == null)
			return null;
		return _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) as DataHero;
	}

	internal static void RememberLogicHero(LogicHero logicHero, DataHero dataHero)
	{
		var id = Homm3FactoryLogisticsEffects.HeroId(dataHero);
		if (id >= 0 && logicHero != null)
			_logicHeroes[id] = logicHero;
	}

	internal static LogicHero CachedLogicHero(DataHero dataHero)
	{
		var id = Homm3FactoryLogisticsEffects.HeroId(dataHero);
		if (id < 0 || !_logicHeroes.TryGetValue(id, out var lh) || lh == null || lh.Pointer == IntPtr.Zero)
			return null;
		return DataHeroOf(lh)?.Pointer == dataHero.Pointer ? lh : null;
	}

	/// <summary>Faction skill rank 1..3 of a data hero, 0 when absent.</summary>
	internal static int SkillRank(DataHero dataHero, string skillSid)
	{
		if (dataHero == null)
			return 0;
		var skills = Homm3TowerArtificingRuntime.ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var list = Homm3TowerArtificingRuntime.ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		foreach (var heroSkill in Homm3FactoryLogisticsEffects.Enumerate(list))
		{
			var sid = (Homm3TowerArtificingRuntime.ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers) as string)?.Trim();
			if (!string.Equals(sid, skillSid, StringComparison.Ordinal))
				continue;
			return Homm3TowerArtificingRuntime.ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillLevelMembers) is int level ? Math.Max(1, Math.Min(3, level)) : 0;
		}
		return 0;
	}

	internal static bool IsLocalHuman(int sideIndex)
	{
		return Homm3FactoryLogisticsState.TryResolveSide(sideIndex, out var side, out _) && IsLocalHuman(side);
	}

	internal static bool IsLocalHuman(DataSide side) => side != null && string.Equals(side.typeOnCreate.ToString(), "Player", StringComparison.Ordinal);

	/// <summary>Applies due pending switches / remote builds and wipes captured buildings. Returns true when state changed.</summary>
	internal static bool Maintain(Homm3FactoryLogisticsState.SideState state, Homm3FactoryLogisticsEffects.World world, Homm3FactoryLogisticsConfig config)
	{
		var changed = false;
		var day = world.Day;
		var remove = new List<int>();
		foreach (var o in state.Objects.Values)
		{
			var owner = Homm3FactoryLogisticsEffects.OwnerOf(world, o.ObjectId);
			if (owner == Homm3FactoryLogisticsEffects.OwnerMissing)
			{
				// Unknown read (object not in the lists): never wipe on it.
				LogOncePerDay("missing-" + state.SideIndex + "-" + o.ObjectId, "object " + o.ObjectId + " (side " + state.SideIndex + ") is not in Data.objects; its enhancements are kept and skipped.");
				continue;
			}
			if (owner != state.SideIndex)
			{
				RestoreHousing(world, o);
				remove.Add(o.ObjectId);
				if (o.Built.Count > 0 || o.UpgradeCenter > 0)
					Homm3FactoryLogisticsDigest.NoteCaptureLoss(world, config, o);
				LogEvent("capture wipe: object " + o.ObjectId + " now owned by side " + owner + " (was " + state.SideIndex + "); " + o.Built.Count + " enhancement(s) destroyed.");
				continue;
			}
			if (o.PendingActiveCode != 0 && day > o.PendingActiveDay)
			{
				LogEvent("switch applied: object " + o.ObjectId + " active " + Name(config, o.ActiveCode) + " -> " + Name(config, o.PendingActiveCode) + " (day " + day + ").");
				Homm3FactoryLogisticsDigest.NoteSwitch(state.SideIndex, world, config, o.ObjectId, o.PendingActiveCode);
				o.ActiveCode = o.PendingActiveCode;
				o.PendingActiveCode = 0;
				o.PendingActiveDay = 0;
				changed = true;
			}
			foreach (var pair in o.Built)
			{
				var e = pair.Value;
				if (e.PendingLevel > e.Level && day > e.PendingDay)
				{
					LogEvent("remote build applied: object " + o.ObjectId + " " + Name(config, pair.Key) + " L" + e.Level + " -> L" + e.PendingLevel + " (day " + day + ").");
					var before = e.Level;
					e.Level = e.PendingLevel;
					e.PendingLevel = 0;
					e.PendingDay = 0;
					changed = true;
					// Spec: a remote build becomes active at the start of the next day (2026-11-16 playtest: a Rail Network
					// built remotely next to an active enhancement stayed inactive and needed a switch, costing a day).
					// Free: it replaces any pending switch and does not use the building's weekly switch.
					if (o.ActiveCode != pair.Key)
						LogEvent("remote build activates: object " + o.ObjectId + " active " + Name(config, o.ActiveCode) + " -> " + Name(config, pair.Key) + ".");
					o.ActiveCode = pair.Key;
					o.PendingActiveCode = 0;
					o.PendingActiveDay = 0;
					OnLevelApplied(config, world, state, o, pair.Key, before);
					Homm3FactoryLogisticsDigest.NoteRemoteBuild(state.SideIndex, world, config, o.ObjectId, pair.Key, e.Level);
				}
			}
		}
		foreach (var id in remove)
		{
			state.Objects.Remove(id);
			changed = true;
		}
		// Remove level-0 placeholders (a remote L1 build is stored at level 0 with a pending level until it applies).
		foreach (var o in state.Objects.Values)
		{
			var empty = new List<int>();
			foreach (var pair in o.Built)
			{
				if (pair.Value.Level <= 0 && pair.Value.PendingLevel <= 0)
					empty.Add(pair.Key);
			}
			foreach (var code in empty)
			{
				o.Built.Remove(code);
				changed = true;
			}
		}
		if (changed)
		{
			Homm3FactoryLogisticsEffects.InvalidateNetwork();
			Homm3FactoryLogisticsRange.Invalidate();
		}
		return changed;
	}

	internal static string Name(Homm3FactoryLogisticsConfig config, int code) => code == 0 ? "none" : config.Get(code)?.Id ?? ("#" + code);

	/// <summary>Food Distribution Center: a level raised while it is active adds this week's extra units at once (L3 rule).</summary>
	internal static void OnLevelApplied(Homm3FactoryLogisticsConfig config, Homm3FactoryLogisticsEffects.World world, Homm3FactoryLogisticsState.SideState state, Homm3FactoryLogisticsState.ObjectState o, int code, int previousLevel)
	{
		var e = config.Get(code);
		if (e == null || e.Effect != "food" || o.ActiveCode != code || !world.Dwellings.TryGetValue(o.ObjectId, out var dwelling))
			return;
		if (!o.Built.TryGetValue(code, out var built) || built.Level < config.MaxLevel)
			return;
		var net = Homm3FactoryLogisticsEffects.GetNetwork(state.SideIndex);
		var newPct = e.ValueAt(net.EffectiveLevel(e, o.ObjectId, built.Level));
		var oldPct = previousLevel <= 0 ? 0 : e.ValueAt(net.EffectiveLevel(e, o.ObjectId, previousLevel));
		var sets = dwelling.assortmentData?.unitSets;
		for (var i = 0; sets != null && i < sets.Count; i++)
		{
			var set = sets[i];
			if (set == null)
				continue;
			var add = (int)Math.Floor(set.weeklyIncrement * Math.Max(0, newPct - oldPct) / 100.0);
			if (add <= 0)
				continue;
			set.currentAmount += add;
			LogEvent("food center L" + built.Level + " immediate units: object " + o.ObjectId + " set " + i + " +" + add + " (now " + set.currentAmount + ").");
		}
	}

	internal static void ApplyHousing(Homm3FactoryLogisticsConfig config, Homm3FactoryLogisticsEffects.World world, Homm3FactoryLogisticsState.SideState state, Homm3FactoryLogisticsEffects.Network net)
	{
		foreach (var o in state.Objects.Values)
		{
			if (!world.Dwellings.TryGetValue(o.ObjectId, out var dwelling) || dwelling.assortmentData == null)
				continue;
			var e = Homm3FactoryLogisticsEffects.ActiveEnhancement(config, o);
			if (e == null || e.Effect != "housing")
			{
				RestoreHousing(world, o);
				continue;
			}
			var assortment = dwelling.assortmentData;
			if (!o.OrigExtraChargeMilli.HasValue)
			{
				var current = assortment.extraCharge;
				if (float.IsNaN(current) || float.IsInfinity(current) || 1.0 + current < MinPriceFactor)
				{
					LogOncePerDay("housing-orig-" + o.ObjectId, "housing office: object " + o.ObjectId + " native extraCharge " + current.ToString("0.###", CultureInfo.InvariantCulture) + " is outside the expected range; the discount is not applied.");
					continue;
				}
				o.OrigExtraChargeMilli = (int)Math.Round(current * 1000.0);
				MarkDirty(state, "housing original");
			}
			var pct = Math.Max(0.0, Math.Min(100.0, e.ValueAt(net.EffectiveLevel(e, o.ObjectId, Homm3FactoryLogisticsEffects.BuiltActiveLevel(o)))));
			// Native hire price factor = 1 + extraCharge. Discount is multiplicative and the factor never drops below MinPriceFactor.
			var origFactor = 1.0 + o.OrigExtraChargeMilli.Value / 1000.0;
			var factor = Math.Max(MinPriceFactor, origFactor * (1.0 - pct / 100.0));
			var target = (float)(factor - 1.0);
			if (Math.Abs(assortment.extraCharge - target) > 0.0005f)
			{
				assortment.extraCharge = target;
				LogEvent("housing office: object " + o.ObjectId + " extraCharge -> " + target.ToString("0.###", CultureInfo.InvariantCulture) + " (" + pct.ToString("0.#", CultureInfo.InvariantCulture) + "% off, price factor " + factor.ToString("0.###", CultureInfo.InvariantCulture) + ").");
			}
		}
	}

	/// <summary>Lowest hire price factor (1 + extraCharge) the Housing Office may produce.</summary>
	internal const double MinPriceFactor = 0.1;

	internal static void RestoreHousing(Homm3FactoryLogisticsEffects.World world, Homm3FactoryLogisticsState.ObjectState o)
	{
		if (!o.OrigExtraChargeMilli.HasValue)
			return;
		if (world.Dwellings.TryGetValue(o.ObjectId, out var dwelling) && dwelling.assortmentData != null)
		{
			dwelling.assortmentData.extraCharge = (float)(o.OrigExtraChargeMilli.Value / 1000.0);
			LogEvent("housing office: object " + o.ObjectId + " extraCharge restored to " + dwelling.assortmentData.extraCharge.ToString("0.###", CultureInfo.InvariantCulture) + ".");
			o.OrigExtraChargeMilli = null;
		}
		// Not in the world (demolished/unreadable): keep the original so a later read can still restore it.
	}

	/// <summary>Arcane Manufactory: exactly the buff of the hero's level (prefix + level), all other levels removed.</summary>
	internal static void ApplyArcane(Homm3FactoryLogisticsConfig config, LogicHero logicHero, DataHero dataHero, Homm3FactoryLogisticsEffects.Network net)
	{
		if (_buffManagerProperty == null || logicHero == null || dataHero == null)
			return;
		try
		{
			var manager = _buffManagerProperty.GetValue(logicHero);
			if (manager == null)
				return;
			var id = Homm3FactoryLogisticsEffects.HeroId(dataHero);
			var level = net != null && net.HeroArcaneLevel.TryGetValue(id, out var lv) ? Math.Min(config.HeroStatBuffMaxLevel, lv) : 0;
			for (var i = 1; i <= config.HeroStatBuffMaxLevel; i++)
			{
				var sid = config.HeroStatBuffPrefix + i.ToString(CultureInfo.InvariantCulture);
				var wanted = i == level;
				var has = _buffGet.Invoke(manager, new object[] { sid }) != null;
				if (has == wanted)
					continue;
				if (wanted)
				{
					var durations = new Il2CppReferenceArray<BuffDuration>(1);
					durations[0] = new BuffDuration(EBuffDurationType.Infinite, -1);
					_buffAdd.Invoke(manager, new object[] { sid, durations });
				}
				else
				{
					_buffRemove.Invoke(manager, new object[] { sid });
				}
				var now = _buffGet.Invoke(manager, new object[] { sid }) != null;
				if (now != wanted)
					LogOncePerDay("arcane-" + sid, "arcane buff " + sid + " " + (wanted ? "add" : "remove") + " did not stick on hero " + dataHero.configSid + " (missing heroes_buffs row?).");
				else
					LogEvent("arcane buff " + (wanted ? "+" : "-") + sid + " on hero " + dataHero.configSid + "#" + id + ".");
			}
		}
		catch (Exception ex)
		{
			LogOncePerDay("arcane", "arcane buff refresh threw " + ex.GetBaseException().Message);
		}
	}

	internal static void RefreshArcaneForCachedHeroes(int sideIndex)
	{
		if (!Homm3FactoryLogisticsConfig.TryLoad(out var config, out _))
			return;
		var net = Homm3FactoryLogisticsEffects.GetNetwork(sideIndex);
		foreach (var lh in new List<LogicHero>(_logicHeroes.Values))
		{
			var dh = lh == null || lh.Pointer == IntPtr.Zero ? null : DataHeroOf(lh);
			if (dh != null && dh.sideId == sideIndex)
				ApplyArcane(config, lh, dh, net);
		}
	}

	// ---------------------------------------------------------------- day start

	private static int DayStartHero(object entry)
	{
		try
		{
			var lh = entry as LogicHero;
			var dh = lh != null ? DataHeroOf(lh) : entry as DataHero;
			if (lh == null || dh == null)
				return 0;
			RememberLogicHero(lh, dh);
			if (!IsLocalHuman(dh.sideId) || !Homm3FactoryLogisticsConfig.TryLoad(out var config, out _))
				return 0;
			if (!Homm3FactoryLogisticsState.TryGet(dh.sideId, out var state, out _) || state.Objects.Count == 0)
			{
				ApplyArcane(config, lh, dh, null);
				return 0;
			}
			ApplyArcane(config, lh, dh, Homm3FactoryLogisticsEffects.GetNetwork(dh.sideId));
		}
		catch (Exception ex)
		{
			LogOncePerDay("dayhero", "day-start hero consumer threw " + ex.GetBaseException().Message);
		}
		return 0;
	}

	private static DataSide SideOf(object sideLogic)
	{
		if (sideLogic == null || _sideDataProperty == null || !_sideDataProperty.DeclaringType.IsInstanceOfType(sideLogic))
			return null;
		return _sideDataProperty.GetValue(sideLogic) as DataSide;
	}

	private static PropertyInfo _worldSideDataProperty;
	private static PropertyInfo _worldSideLogicProperty;
	private static readonly Dictionary<int, (int tick, int heroes)> _tradeContractCache = new();
	private static bool _loggedMarketCount;

	/// <summary>
	/// Trade Contracts: each alive hero of the side with the subskill counts as TradeContractsMarketsPerHero markets.
	/// The subskill row also grants native enableMarketsCounting (+1 inside this count), so the postfix adds the rest.
	/// Hero scan cached per side for 1 s (the count is read on every market UI refresh).
	/// </summary>
	private static void PostfixMarketsCount(object __instance, ref int __result)
	{
		try
		{
			DataSide side = null;
			if (_worldSideDataProperty != null)
				side = _worldSideDataProperty.GetValue(__instance) as DataSide;
			else if (_worldSideLogicProperty != null && _worldSideLogicProperty.GetValue(__instance) is { } logic)
				side = _sideDataProperty.GetValue(logic) as DataSide;
			if (side == null)
				return;
			var now = Environment.TickCount;
			if (!_tradeContractCache.TryGetValue(side.index, out var cached) || unchecked(now - cached.tick) > 1000)
			{
				var heroes = 0;
				if (Homm3FactoryLogisticsEffects.TryGetData(out var data, out _))
					foreach (var hero in Homm3FactoryLogisticsEffects.SideHeroes(new Homm3FactoryLogisticsEffects.World { Data = data }, side.index))
						if (Homm3DungeonDraconicDominionHook.HasHeroSubSkill(hero, Homm3FactoryLogisticsConfig.TradeContractsSubSkillSid))
							heroes++;
				_tradeContractCache[side.index] = cached = (now, heroes);
			}
			if (cached.heroes <= 0)
				return;
			var before = __result;
			__result += cached.heroes * (Homm3FactoryLogisticsConfig.TradeContractsMarketsPerHero - 1);
			if (!_loggedMarketCount)
			{
				_loggedMarketCount = true;
				LogEvent("trade contracts: side " + side.index + " market count " + before + " -> " + __result + " (" + cached.heroes + " hero(es)).");
			}
		}
		catch (Exception ex)
		{
			LogOncePerDay("markets", "market count postfix failed: " + ex.GetBaseException().Message);
		}
	}

	private static void PrefixSideStartDay(object __instance)
	{
		try
		{
			var side = SideOf(__instance);
			if (side == null || !IsLocalHuman(side))
				return;
			Homm3FactoryLogisticsState.ResetIfSessionChanged();
			Homm3FactoryLogisticsRange.Invalidate();
			Homm3FactoryLogisticsEffects.InvalidateNetwork();
			if (!Homm3FactoryLogisticsConfig.TryLoad(out var config, out var cfgFail))
			{
				LogOncePerDay("config", "config not loaded (" + cfgFail + "); Logistics Network effects are off.");
				return;
			}
			if (!Homm3FactoryLogisticsState.TryGet(side.index, out var state, out _) || state.Objects.Count == 0)
				return;
			if (!Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out var worldFail))
			{
				LogOncePerDay("world", "day start: world unreadable (" + worldFail + ").");
				return;
			}
			if (Maintain(state, world, config))
				MarkDirty(state, "day start");
		}
		catch (Exception ex)
		{
			LogOncePerDay("sideprefix", "side day-start prefix threw " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixSideStartDay(object __instance)
	{
		try
		{
			var side = SideOf(__instance);
			if (side == null || !IsLocalHuman(side) || !Homm3FactoryLogisticsConfig.TryLoad(out var config, out _))
				return;
			if (!Homm3FactoryLogisticsState.TryGet(side.index, out var state, out _))
				return;
			RefreshArcaneForCachedHeroes(side.index);
			if (state.Objects.Count == 0 || !Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out _))
			{
				// Safe point: the native day start is done; write whatever earlier hooks marked dirty.
				Homm3FactoryLogisticsState.FlushDirty();
				return;
			}
			var net = Homm3FactoryLogisticsEffects.GetNetwork(side.index, force: true);
			Homm3FactoryLogisticsDigest.OnSideDayStarted(side.index, world, state);
			ApplyHousing(config, world, state, net);
			GrantArcaneAstrology(__instance, side, config, net, world.Day);
			Homm3FactoryLogisticsState.FlushDirty();
			PruneMineDays(world.Day);
			LogEvent("day " + world.Day + " side " + side.index + ": " + state.Objects.Count + " logistics building(s), logistics level " + net.LogisticsLevel
				+ ", range " + (net.RangeOk ? "ok" : "OFF (" + net.RangeFail + ")") + ", power " + net.PowerBonus.Count + ", synth " + net.SynthMultiplier.Count
				+ ", +markets " + net.ExtraMarkets + ", arcane heroes " + net.HeroArcaneLevel.Count + ", astrology towns " + net.ArcaneAstrologyTowns
				+ ", converting dwellings " + net.DwellingConversion.Count + ", warehouse " + net.WarehouseDiscountPct + "%.");
		}
		catch (Exception ex)
		{
			LogOncePerDay("sidepostfix", "side day-start postfix threw " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// Arcane Manufactory astrology: +AstrologyPerTown experience per counted town (each Manufactory counts at most its
	/// effective level of owned towns in range), once per side and day, through the native add (ecx bcin, pinned in
	/// GameSymbols.FactoryLogisticsArcane) on the side logic's own astrology progression; the exp field is never
	/// written directly. Runs from the side OnStartDay postfix (the day-start safe point, DECISIONS.md #40/#55).
	/// Fails closed (no grant, logged) when the progression or the method does not resolve.
	/// </summary>
	private static void GrantArcaneAstrology(object sideLogic, DataSide side, Homm3FactoryLogisticsConfig config, Homm3FactoryLogisticsEffects.Network net, int day)
	{
		var towns = net.ArcaneAstrologyTowns;
		if (towns <= 0 || config.AstrologyPerTown <= 0 || day < 0 || !_astrologyDayDone.Add((side.index, day)))
			return;
		var amount = (int)Math.Min(int.MaxValue, (long)towns * config.AstrologyPerTown);
		try
		{
			var progress = Homm3TowerArtificingRuntime.ReadMember(sideLogic, GameSymbols.FactoryLogisticsArcane.SideAstrologyProgressMembers);
			if (progress == null)
			{
				LogError("astrology grant skipped: the side logic's astrology progression did not resolve (+" + amount + " for " + towns + " town(s) not granted).");
				return;
			}
			var type = progress.GetType();
			if (_astrologyProgressType != type)
			{
				_astrologyProgressType = type;
				_astrologyAdd = GameMember.FindFirstMethodByNames(type, new[] { typeof(int) }, GameSymbols.FactoryLogisticsArcane.AstrologyAddExp);
			}
			if (_astrologyAdd == null || _astrologyAdd.IsStatic || _astrologyAdd.ReturnType != typeof(void))
			{
				LogError("astrology grant skipped: the astrology add method did not resolve on " + type.Name + " (+" + amount + " not granted).");
				return;
			}
			var expBefore = side.currentAstrologyExp;
			var levelBefore = side.currentAstrologyLevel;
			_astrologyAdd.Invoke(progress, new object[] { amount });
			var expAfter = side.currentAstrologyExp;
			var levelAfter = side.currentAstrologyLevel;
			var moved = levelAfter != levelBefore || expAfter != expBefore;
			LogEvent("arcane astrology: side " + side.index + " day " + day + " +" + amount + " (" + towns + " town(s) x " + config.AstrologyPerTown + "); exp " + expBefore + " -> " + expAfter
				+ ", level " + levelBefore + " -> " + levelAfter + (moved ? "." : " (unchanged: astrology maxed, or the add refused)."));
		}
		catch (Exception ex)
		{
			LogError("astrology grant threw " + ex.GetBaseException().Message + " (+" + amount + " not granted).");
		}
	}

	/// <summary>Returns false (skip the native grant) when the active enhancement replaces the mine's output.</summary>
	private static bool PrefixMineStartDay(object __instance)
	{
		try
		{
			var mine = Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.CovePlunder.MineLogicResMineMembers) as DataObjResMine;
			if (mine == null)
				return true;
			var cfgObj = Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.CovePlunder.MineLogicConfigMembers) as ObjResMineConfig;
			if (cfgObj != null)
				Homm3FactoryLogisticsEffects.RememberMineConfig(mine.idMapObject, cfgObj.resName, cfgObj.resValue);
			var sideIndex = mine.ownerSide;
			if (sideIndex < 0 || !IsLocalHuman(sideIndex) || !Homm3FactoryLogisticsConfig.TryLoad(out var config, out _))
				return true;
			if (!Homm3FactoryLogisticsState.TryGet(sideIndex, out var state, out _) || !state.Objects.TryGetValue(mine.idMapObject, out var o))
				return true;
			if (!Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out _))
				return true;
			var changed = Maintain(state, world, config);
			if (!state.Objects.TryGetValue(mine.idMapObject, out o))
			{
				SaveIf(changed, state, "mine day");
				return true;
			}
			if (!_mineDayDone.Add((mine.idMapObject, world.Day)))
			{
				// Already handled today: keep the same decision without paying twice.
				return !Homm3FactoryLogisticsEffects.SuppressesOutput(Homm3FactoryLogisticsEffects.ActiveEnhancement(config, o));
			}
			var e = Homm3FactoryLogisticsEffects.ActiveEnhancement(config, o);
			if (e == null)
			{
				SaveIf(changed, state, "mine day");
				return true;
			}
			var resource = cfgObj?.resName ?? Homm3FactoryLogisticsEffects.MineResource(mine);
			var output = cfgObj != null && cfgObj.resValue > 0 ? cfgObj.resValue : Homm3FactoryLogisticsEffects.MineOutput(mine, resource);
			var net = Homm3FactoryLogisticsEffects.GetNetwork(sideIndex);
			var eff = net.EffectiveLevel(e, o.ObjectId, Homm3FactoryLogisticsEffects.BuiltActiveLevel(o));
			switch (e.Effect)
			{
				case "export":
				{
					var gold = Homm3FactoryLogisticsEffects.ExportGold(config, net, world, sideIndex, o.ObjectId, resource, output, eff);
					Grant(sideIndex, "gold", gold, "export office object " + o.ObjectId + " (" + output + " " + resource + ", L" + eff + ")");
					break;
				}
				case "byproduct":
				{
					Grant(sideIndex, "gold", (int)Math.Round(e.ValueAt(eff)), "byproduct object " + o.ObjectId + " L" + eff);
					var extraMilli = (long)Math.Round(output * e.Value2At(eff) * 10.0); // output x pct/100 x 1000
					var idx = Array.IndexOf(Homm3FactoryLogisticsState.PoolResources, resource);
					if (extraMilli > 0 && idx >= 0)
					{
						state.PoolMilli[idx] += extraMilli;
						var whole = (int)(state.PoolMilli[idx] / 1000);
						if (whole > 0 && Grant(sideIndex, resource, whole, "byproduct extra output object " + o.ObjectId))
							state.PoolMilli[idx] -= whole * 1000L;
						changed = true;
					}
					break;
				}
			}
			SaveIf(changed, state, "mine day");
			if (Homm3FactoryLogisticsEffects.SuppressesOutput(e))
			{
				LogEvent("mine " + o.ObjectId + " (" + resource + ") output suppressed by " + e.Id + " L" + eff + ".");
				return false;
			}
		}
		catch (Exception ex)
		{
			LogOncePerDay("mineday", "mine day prefix threw " + ex.GetBaseException().Message + " (native output kept).");
		}
		return true;
	}

	/// <summary>Native hooks never write side.buffs: they only mark the side dirty (flushed at the next safe point).</summary>
	private static void SaveIf(bool changed, Homm3FactoryLogisticsState.SideState state, string why)
	{
		if (changed)
			MarkDirty(state, why);
	}

	private static void PruneMineDays(int today)
	{
		if (_mineDayDone.Count > 0)
			_mineDayDone.RemoveWhere(k => k.day < today);
	}

	internal static bool Grant(int sideIndex, string resource, int amount, string why)
	{
		if (amount <= 0)
			return true;
		if (Homm3FactoryLogisticsEffects.TryAddResource(sideIndex, resource, amount, out var fail))
		{
			LogEvent("+" + amount + " " + resource + " to side " + sideIndex + ": " + why + ".");
			return true;
		}
		LogError("grant FAILED +" + amount + " " + resource + " to side " + sideIndex + " (" + why + "): " + fail);
		return false;
	}

	// ---------------------------------------------------------------- week start (dwellings)

	private static DataObjHire HireOf(object dwellingLogic)
	{
		if (dwellingLogic == null || _dwellingHireProperty == null || !_dwellingHireProperty.DeclaringType.IsInstanceOfType(dwellingLogic))
			return null;
		return _dwellingHireProperty.GetValue(dwellingLogic) as DataObjHire;
	}

	private static void PrefixDwellingStartWeek(object __instance)
	{
		try
		{
			var hire = HireOf(__instance);
			var sets = hire?.assortmentData?.unitSets;
			if (sets == null)
				return;
			var snap = new int[sets.Count];
			for (var i = 0; i < sets.Count; i++)
				snap[i] = sets[i]?.currentAmount ?? 0;
			_weekSnapshot[hire.Pointer] = snap;
		}
		catch (Exception ex)
		{
			LogOncePerDay("weekprefix", "dwelling week prefix threw " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixDwellingStartWeek(object __instance)
	{
		try
		{
			var hire = HireOf(__instance);
			if (hire == null || !_weekSnapshot.TryGetValue(hire.Pointer, out var snap))
				return;
			_weekSnapshot.Remove(hire.Pointer);
			var sideIndex = hire.ownerSide;
			if (sideIndex < 0 || !IsLocalHuman(sideIndex) || !Homm3FactoryLogisticsConfig.TryLoad(out var config, out _))
				return;
			// No logistics state at all means no Manufactory either: nothing to do for this dwelling.
			if (!Homm3FactoryLogisticsState.TryGet(sideIndex, out var state, out _) || state.Objects.Count == 0)
				return;
			if (!Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out _))
				return;
			var changed = Maintain(state, world, config);
			SaveIf(changed, state, "dwelling week");
			var net = Homm3FactoryLogisticsEffects.GetNetwork(sideIndex);
			state.Objects.TryGetValue(hire.idMapObject, out var o);
			var e = o == null ? null : Homm3FactoryLogisticsEffects.ActiveEnhancement(config, o);
			if (e != null && e.Effect == "support")
			{
				// Support Hub (DECISIONS.md #81): this dwelling produces nothing; its range boosts the others.
				var hubSets = hire.assortmentData.unitSets;
				for (var i = 0; i < hubSets.Count && i < snap.Length; i++)
				{
					if (hubSets[i] != null && hubSets[i].currentAmount > snap[i])
					{
						LogEvent("support hub object " + o.ObjectId + " set " + i + ": weekly +" + (hubSets[i].currentAmount - snap[i]) + " withheld (the hub produces no units).");
						hubSets[i].currentAmount = snap[i];
					}
				}
				return;
			}
			if (e != null && e.Effect != "food" && e.Effect != "mercenary")
				e = null;
			var supportPct = net.SupportGrowthPct.TryGetValue(hire.idMapObject, out var sp) ? sp : 0.0;
			// Order (DECISIONS.md #57, #81): Food Distribution Center and Support Hub extras first, both from the native
			// growth (they add, not multiply), then the Arcane conversion on the boosted growth; a Mercenary HQ turns the
			// week's units (Support Hub extras included) into gold, so nothing is left to convert there.
			if (e == null || e.Effect == "food")
				ConvertWeeklyGrowth(hire, snap, sideIndex, state, net, world, e, o, config, supportPct);
			else if (supportPct > 0.0)
				AddSupportGrowth(hire, snap, supportPct);
			if (e == null || e.Effect != "mercenary")
				return;
			var eff = net.EffectiveLevel(e, o.ObjectId, Homm3FactoryLogisticsEffects.BuiltActiveLevel(o));
			var sets = hire.assortmentData.unitSets;
			for (var i = 0; i < sets.Count && i < snap.Length; i++)
			{
				var set = sets[i];
				if (set == null)
					continue;
				var delta = set.currentAmount - snap[i];
				if (delta <= 0)
					continue;
				{
					var sid = set.sids != null && set.sids.Count > 0 ? set.sids[0] : null;
					var unit = sid == null ? null : Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(sid);
					var price = 0;
					if (unit != null)
						Homm3FactoryLogisticsEffects.ReadUnitCost(unit, config, out price, out _);
					if (unit == null || price <= 0)
					{
						// Unknown unit or price: the week's units stay (no conversion rather than units for nothing).
						LogOncePerDay("merc-" + o.ObjectId + "-" + i, "mercenary HQ object " + o.ObjectId + " set " + i + ": unit " + (sid ?? "(none)") + (unit == null ? " unresolved" : " has no gold price") + "; this week's units are left in the dwelling.");
						continue;
					}
					set.currentAmount = snap[i];
					var tier = Math.Max(1, Math.Min(7, unit.tier));
					var capValue = config.DwellingTierWeeklyValue.TryGetValue(tier, out var cap) ? cap : int.MaxValue;
					var synth = net.SynthMultiplier.TryGetValue(o.ObjectId, out var s) ? s : 1.0;
					var gold = (int)Math.Floor(Math.Min((long)delta * price, capValue) * e.ValueAt(eff) * synth);
					Grant(sideIndex, "gold", gold, "mercenary HQ object " + o.ObjectId + " (" + delta + "x " + sid + " @" + price + ", cap " + capValue + ", x" + e.ValueAt(eff) + ", synth x" + synth.ToString("0.##", CultureInfo.InvariantCulture) + ")");
				}
			}
		}
		catch (Exception ex)
		{
			LogOncePerDay("weekpostfix", "dwelling week postfix threw " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Support Hub extra units for a dwelling whose growth goes through no other step (Mercenary HQ): floor(native growth x pct).</summary>
	private static void AddSupportGrowth(DataObjHire hire, int[] snap, double supportPct)
	{
		var sets = hire.assortmentData.unitSets;
		for (var i = 0; i < sets.Count && i < snap.Length; i++)
		{
			var set = sets[i];
			var delta = set == null ? 0 : set.currentAmount - snap[i];
			if (delta <= 0)
				continue;
			var add = (int)Math.Floor(delta * supportPct / 100.0 + 1e-9);
			set.currentAmount += add;
			LogEvent("support hubs -> dwelling " + hire.idMapObject + " set " + i + ": weekly +" + delta + " -> +" + add + " extra (" + supportPct.ToString("0.#", CultureInfo.InvariantCulture) + "%).");
		}
	}

	/// <summary>
	/// Food Distribution Center extra units (when <paramref name="food"/> is set) and then the Arcane Manufactory
	/// conversion: floor(week growth x min(1, effective level / 6)) of each set's new units leave the native stock
	/// for this dwelling's upgraded stock, each unit picking one of the set's upgraded sids (deterministic per
	/// dwelling, set, week). Base-only sets (neutral dwellings) never convert. Native hook: state is only marked dirty.
	/// </summary>
	private static void ConvertWeeklyGrowth(DataObjHire hire, int[] snap, int sideIndex, Homm3FactoryLogisticsState.SideState state, Homm3FactoryLogisticsEffects.Network net,
		Homm3FactoryLogisticsEffects.World world, Homm3FactoryLogisticsConfig.Enhancement food, Homm3FactoryLogisticsState.ObjectState o, Homm3FactoryLogisticsConfig config,
		double supportPct)
	{
		var sets = hire.assortmentData.unitSets;
		var foodEff = food == null ? 0 : net.EffectiveLevel(food, o.ObjectId, Homm3FactoryLogisticsEffects.BuiltActiveLevel(o));
		var share = net.DwellingConversion.TryGetValue(hire.idMapObject, out var sh) ? sh : 0.0;
		for (var i = 0; i < sets.Count && i < snap.Length; i++)
		{
			var set = sets[i];
			if (set == null)
				continue;
			var delta = set.currentAmount - snap[i];
			if (delta <= 0)
				continue;
			var native = delta;
			if (food != null)
			{
				var add = (int)Math.Floor(native * food.ValueAt(foodEff) / 100.0);
				set.currentAmount += add;
				LogEvent("food center object " + o.ObjectId + " set " + i + ": weekly +" + native + " -> +" + add + " extra (L" + foodEff + ").");
				delta += add;
			}
			if (supportPct > 0.0)
			{
				var add = (int)Math.Floor(native * supportPct / 100.0 + 1e-9);
				set.currentAmount += add;
				LogEvent("support hubs -> dwelling " + hire.idMapObject + " set " + i + ": weekly +" + native + " -> +" + add + " extra (" + supportPct.ToString("0.#", CultureInfo.InvariantCulture) + "%).");
				delta += add;
			}
			var sidCount = set.sids?.Count ?? 0;
			if (share <= 0.0 || sidCount < 2 || i > 7)
				continue;
			var convert = Math.Min(set.currentAmount, (int)Math.Floor(delta * share + 1e-9));
			if (convert <= 0)
				continue;
			if (o == null)
				state.Objects[hire.idMapObject] = o = new Homm3FactoryLogisticsState.ObjectState { ObjectId = hire.idMapObject };
			var rng = new System.Random(unchecked(hire.idMapObject * 7919 + world.WeekId * 104729 + i * 31));
			var picked = new int[Math.Min(sidCount, 8)];
			for (var u = 0; u < convert; u++)
				picked[1 + rng.Next(picked.Length - 1)]++;
			set.currentAmount -= convert;
			var parts = new List<string>();
			for (var v = 1; v < picked.Length; v++)
			{
				if (picked[v] <= 0)
					continue;
				var key = Homm3FactoryLogisticsState.ObjectState.PoolKey(i, v);
				o.UpgradedPool[key] = (int)Math.Min(Homm3FactoryLogisticsState.UpoolCountMask, (long)(o.UpgradedPool.TryGetValue(key, out var have) ? have : 0) + picked[v]);
				parts.Add(picked[v] + "x " + set.sids[v]);
			}
			MarkDirty(state, "arcane conversion");
			LogEvent("arcane conversion object " + hire.idMapObject + " set " + i + ": week growth " + delta + " x " + (share * 100.0).ToString("0", CultureInfo.InvariantCulture) + "% -> "
				+ convert + " upgraded (" + string.Join(", ", parts) + "); native stock now " + set.currentAmount + ".");
		}
	}

	// ---------------------------------------------------------------- visits and captures

	private static void PostfixMineVisit(object __instance, object __0)
	{
		try
		{
			var mine = Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.CovePlunder.MineLogicResMineMembers) as DataObjResMine;
			if (mine == null)
				return;
			var cfgObj = Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.CovePlunder.MineLogicConfigMembers) as ObjResMineConfig;
			if (cfgObj != null)
				Homm3FactoryLogisticsEffects.RememberMineConfig(mine.idMapObject, cfgObj.resName, cfgObj.resValue);
			OnVisit(__0, mine.idMapObject, mine.ownerSide, "mine");
		}
		catch (Exception ex)
		{
			LogOncePerDay("minevisit", "mine visit postfix threw " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixDwellingVisit(object __instance, object __0)
	{
		try
		{
			var hire = HireOf(__instance);
			if (hire != null)
				OnVisit(__0, hire.idMapObject, hire.ownerSide, "dwelling");
		}
		catch (Exception ex)
		{
			LogOncePerDay("dwellingvisit", "dwelling visit postfix threw " + ex.GetBaseException().Message);
		}
	}

	private sealed class PendingGuardVisit
	{
		internal DataHero Hero;
		internal string Kind;
		internal float Since;
		internal bool SawBattle;
		internal float BattleEnded;
	}

	private static void OnVisit(object worldHero, int objectId, int ownerSide, string kind)
	{
		if (!TryResolveHeroFromWorldHero(worldHero, out var lh, out var dh))
			return;
		RememberLogicHero(lh, dh);
		if (!IsLocalHuman(dh.sideId) || !Homm3FactoryLogisticsConfig.TryLoad(out var config, out _))
			return;
		if (dh.sideId != ownerSide)
		{
			// Not owned (yet): a guarded building starts a battle first. Remember a skilled visit and open the panel when
			// the building's owner changes to the hero's side; a lost or fled battle drops it (UX item 23).
			if (SkillRank(dh, config.SkillSid) > 0)
			{
				_guardVisits[objectId] = new PendingGuardVisit { Hero = dh, Kind = kind, Since = Time.realtimeSinceStartup };
				EnsureHost();
				LogEvent("visit to unowned " + kind + " " + objectId + " by hero " + dh.configSid + ": waiting for a capture (guard battle?).");
			}
			return;
		}
		_guardVisits.Remove(objectId);
		ContinueVisit(dh, objectId, ownerSide, kind, config);
	}

	/// <summary>The owned-building part of a visit: Upgrade Center marker, then the panel (queued until the hire window closes).</summary>
	private static void ContinueVisit(DataHero dh, int objectId, int ownerSide, string kind, Homm3FactoryLogisticsConfig config)
	{
		var rank = SkillRank(dh, config.SkillSid);
		if (!Homm3FactoryLogisticsState.TryGet(ownerSide, out var state, out var stateFail))
		{
			if (rank > 0)
				LogError("visit ignored: state for side " + ownerSide + " unreadable (" + stateFail + ").");
			return;
		}
		if (rank <= 0)
		{
			// Without the skill the panel only opens to sell the dwelling's Arcane upgraded stock (DECISIONS.md #59).
			if (kind == "dwelling" && state.Objects.TryGetValue(objectId, out var stocked) && stocked.HasUpgradedStock)
			{
				_visitQueue.Add((dh, objectId, Time.realtimeSinceStartup));
				EnsureHost();
				LogEvent("visit queued (upgraded stock only): hero " + dh.configSid + " at dwelling " + objectId + ".");
				return;
			}
			HintUnskilledVisit(dh, objectId, state, config);
			return;
		}
		_lastSkilledHero[dh.sideId] = Homm3FactoryLogisticsEffects.HeroId(dh);
		if (Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out _) && Maintain(state, world, config))
			MarkDirty(state, "visit maintain");
		if (!state.Objects.TryGetValue(objectId, out var o))
			state.Objects[objectId] = o = new Homm3FactoryLogisticsState.ObjectState { ObjectId = objectId };
		if (o.UpgradeCenter < rank)
		{
			o.UpgradeCenter = rank;
			LogEvent("upgrade center: " + kind + " " + objectId + " marked at level " + rank + " by hero " + dh.configSid + ".");
			MarkDirty(state, "upgrade center");
		}
		_visitQueue.Add((dh, objectId, Time.realtimeSinceStartup));
		EnsureHost();
		LogEvent("visit queued: hero " + dh.configSid + " rank " + rank + " at " + kind + " " + objectId + ".");
	}

	/// <summary>
	/// UX item 22: a hero without the skill visits an owned mine or dwelling of a side that uses the network (a skilled
	/// hero, an existing record, or a town of the skill's faction): one hint line, once per building per day.
	/// </summary>
	private static void HintUnskilledVisit(DataHero dh, int objectId, Homm3FactoryLogisticsState.SideState state, Homm3FactoryLogisticsConfig config)
	{
		try
		{
			var day = Homm3FactoryLogisticsEffects.TryReadDay(out var d, out _, out _) ? d : -1;
			if (_hintDay.TryGetValue(objectId, out var shown) && shown == day)
				return;
			if (!IsNetworkSide(dh.sideId, state, config))
				return;
			_hintDay[objectId] = day;
			Homm3FactoryLogisticsDigest.Show("A hero with Logistics Network can enhance this building.");
		}
		catch (Exception ex)
		{
			LogOncePerDay("hint", "unskilled visit hint threw " + ex.GetBaseException().Message);
		}
	}

	private static bool IsNetworkSide(int sideIndex, Homm3FactoryLogisticsState.SideState state, Homm3FactoryLogisticsConfig config)
	{
		if (state.Objects.Count > 0)
			return true;
		if (!Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out _))
			return false;
		foreach (var hero in Homm3FactoryLogisticsEffects.SideHeroes(world, sideIndex))
		{
			if (SkillRank(hero, config.SkillSid) > 0)
				return true;
		}
		// The faction skill id ends with the faction id; its towns carry the faction id in their name token.
		var faction = SkillFaction(config.SkillSid);
		if (faction == null)
			return false;
		foreach (var city in world.Cities.Values)
		{
			if (city != null && city.ownerSide == sideIndex && string.Equals(Homm3FactoryLogistics.TownFactionSid(city.cityName), faction, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static string SkillFaction(string skillSid)
	{
		var prefix = "skill" + "_faction_";
		return skillSid != null && skillSid.StartsWith(prefix, StringComparison.Ordinal) && skillSid.Length > prefix.Length ? skillSid.Substring(prefix.Length) : null;
	}

	/// <summary>Hero id of the side's last skilled hero that cast the spell or visited (-1 = none this session).</summary>
	internal static int LastSkilledHeroId(int sideIndex) => _lastSkilledHero.TryGetValue(sideIndex, out var id) ? id : -1;

	/// <summary>A building whose owner changed to the side of a skilled hero that visited it while unowned: continue that visit.</summary>
	private static void ResolveGuardVisit(int objectId, Homm3FactoryLogisticsEffects.World world, Homm3FactoryLogisticsConfig config)
	{
		if (!_guardVisits.TryGetValue(objectId, out var pending))
			return;
		var owner = Homm3FactoryLogisticsEffects.OwnerOf(world, objectId);
		if (pending.Hero == null || pending.Hero.Pointer == IntPtr.Zero || owner != pending.Hero.sideId)
			return;
		_guardVisits.Remove(objectId);
		LogEvent("guarded " + pending.Kind + " " + objectId + " captured by hero " + pending.Hero.configSid + ": opening the panel after the battle.");
		ContinueVisit(pending.Hero, objectId, owner, pending.Kind, config);
	}

	/// <summary>Drops guard visits whose battle ended without a capture (lost or fled), or that never led to a battle.</summary>
	private static void TickGuardVisits(bool battle, float now)
	{
		if (_guardVisits.Count == 0)
			return;
		List<int> drop = null;
		foreach (var pair in _guardVisits)
		{
			var p = pair.Value;
			if (battle)
			{
				p.SawBattle = true;
				p.BattleEnded = 0f;
				continue;
			}
			if (p.SawBattle && p.BattleEnded <= 0f)
				p.BattleEnded = now;
			var expired = p.SawBattle ? now - p.BattleEnded > 10f : now - p.Since > 120f;
			if (expired)
				(drop ??= new List<int>()).Add(pair.Key);
		}
		if (drop == null)
			return;
		foreach (var id in drop)
		{
			LogEvent("guard visit to object " + id + " dropped (" + (_guardVisits[id].SawBattle ? "battle lost or fled" : "no battle or capture") + ").");
			_guardVisits.Remove(id);
		}
	}

	private static void PostfixOwnerChanged(object __instance)
	{
		try
		{
			var id = -1;
			if (Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.CovePlunder.MineLogicResMineMembers) is DataObjResMine mine)
				id = mine.idMapObject;
			else if (HireOf(__instance) is DataObjHire hire)
				id = hire.idMapObject;
			if (id < 0 || !Homm3FactoryLogisticsConfig.TryLoad(out var config, out _) || !Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out _))
				return;
			foreach (var state in new List<Homm3FactoryLogisticsState.SideState>(Homm3FactoryLogisticsState.LoadedSides()))
			{
				if (!state.Objects.ContainsKey(id))
					continue;
				if (Maintain(state, world, config))
					SaveIf(true, state, "capture");
			}
			Homm3FactoryLogisticsRange.Invalidate();
			Homm3FactoryLogisticsEffects.InvalidateNetwork();
			ResolveGuardVisit(id, world, config);
		}
		catch (Exception ex)
		{
			LogOncePerDay("owner", "owner-change postfix threw " + ex.GetBaseException().Message);
		}
	}

	// ---------------------------------------------------------------- spell

	private static bool PrefixSpellCast(object __instance, ref bool __result)
	{
		try
		{
			var setting = Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicSettingMembers) as MagicSetting;
			var parameters = new List<string>();
			if (setting?.parameters is IEnumerable en)
			{
				foreach (var p in en)
					parameters.Add(p as string ?? p?.ToString());
			}
			else if (setting?.parameters != null)
			{
				foreach (var p in Homm3FactoryLogisticsEffects.Enumerate(setting.parameters))
					parameters.Add(p as string ?? p?.ToString());
			}
			if (parameters.Count < 1 || !string.Equals(parameters[0], SpellMode, StringComparison.Ordinal))
				return true;
			// Result shape: the spell is free (0 mana, unlimited uses) and has no world effect, so every caster that is
			// not a verified local human gets the native success shape (__result = true, original skipped, no UI) and the
			// AI never sees a failed cast to retry. Only a local human whose viewer failed gets false (banner shown).
			__result = true;
			var worldHero = _handlerWorldHeroProperty != null && _handlerWorldHeroProperty.DeclaringType.IsInstanceOfType(__instance) ? _handlerWorldHeroProperty.GetValue(__instance) : null;
			if (!TryResolveHeroFromWorldHero(worldHero, out var lh, out var dh))
			{
				LogSpellAi("casting hero unresolved; treated as a no-op success.");
				return false;
			}
			RememberLogicHero(lh, dh);
			if (!IsLocalHuman(dh.sideId))
			{
				LogSpellAi("hero " + dh.configSid + " (side " + dh.sideId + ") is not a local human; no-op success, no UI.");
				return false;
			}
			Homm3FactoryLogistics.NoteSide(dh.sideId);
			_lastSkilledHero[dh.sideId] = Homm3FactoryLogisticsEffects.HeroId(dh);
			Homm3FactoryLogisticsState.FlushDirty(dh.sideId);
			if (!Homm3FactoryLogisticsViewer.Open(dh, out var fail))
			{
				LogWarning("viewer not opened: " + fail);
				Homm3DungeonWarCaptivesWindow.ShowBanner("Logistics Network: " + fail);
				__result = false;
			}
			else
			{
				LogEvent("viewer opened by hero " + dh.configSid + ".");
			}
			return false;
		}
		catch (Exception ex)
		{
			LogSpellAi("cast prefix threw " + ex.GetBaseException().Message + "; no-op success (original skipped).");
			__result = true;
			return false;
		}
	}

	private static int _spellAiLogs;

	private static void LogSpellAi(string message)
	{
		if (Verbose || _spellAiLogs++ < 20)
			LogWarning("logistics spell: " + message);
	}

	// ---------------------------------------------------------------- visit queue host

	private static void EnsureHost()
	{
		if (_hostObject != null)
			return;
		try
		{
			if (!_hostTypeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3FactoryLogisticsRuntimeHost>();
				_hostTypeRegistered = true;
			}
			_hostObject = new GameObject("Homm3FactoryLogisticsRuntimeHost");
			UnityObject.DontDestroyOnLoad(_hostObject);
			_hostObject.AddComponent<Homm3FactoryLogisticsRuntimeHost>();
		}
		catch (Exception ex)
		{
			_hostObject = null;
			LogError("visit host failed (" + ex.GetBaseException().Message + "); visits dispatch immediately.");
			DispatchAll(fromSafePoint: false);
		}
	}

	internal static bool HireWindowOpen()
	{
		try
		{
			var views = UnityObject.FindObjectsOfType(Il2CppType.Of<Hex.UI.City.BhHireCityView>());
			for (var i = 0; views != null && i < views.Length; i++)
			{
				if (views[i] is Component c && c != null && c.gameObject.activeInHierarchy)
					return true;
				var cast = views[i]?.TryCast<Component>();
				if (cast != null && cast.gameObject.activeInHierarchy)
					return true;
			}
		}
		catch
		{
			// Treat an unreadable UI as closed: the panel then opens over it rather than never.
		}
		return false;
	}

	private static int _closedFrames;

	internal static void Tick()
	{
		if (Homm3FactoryLogisticsState.AnyDirty)
		{
			// Cleared first: a failed save retries at the next MarkDirty or day start, not every frame.
			Homm3FactoryLogisticsState.AnyDirty = false;
			Homm3FactoryLogisticsState.FlushDirty();
		}
		TickPart("digest", Homm3FactoryLogisticsDigest.Tick);
		TickPart("hotkey", Homm3FactoryLogisticsMapHotkey.Tick);
		if (_visitQueue.Count == 0 && _guardVisits.Count == 0)
			return;
		// A guard battle (UX item 23): nothing opens while it runs; the capture postfix queues the visit.
		var now = Time.realtimeSinceStartup;
		var battle = TempleSwordsmanBillboardPrototype.IsBattleViewActive();
		TickGuardVisits(battle, now);
		if (_visitQueue.Count == 0)
			return;
		if ((battle || HireWindowOpen()) && now - _visitQueue[0].since < 600f)
		{
			_closedFrames = 0;
			return;
		}
		if (++_closedFrames < 3)
			return;
		DispatchAll(fromSafePoint: true);
	}

	private static void DispatchAll(bool fromSafePoint)
	{
		var items = new List<(DataHero hero, long key, float since)>(_visitQueue);
		_visitQueue.Clear();
		_closedFrames = 0;
		if (fromSafePoint)
			Homm3FactoryLogisticsState.FlushDirty();
		if (items.Count == 0)
			return;
		var last = items[items.Count - 1];
		Homm3FactoryLogistics.RaiseVisit(last.hero, last.key);
	}

	internal static void HostDestroyed() => _hostObject = null;

	private static void TickPart(string name, Action part)
	{
		try
		{
			part();
		}
		catch (Exception ex)
		{
			LogOncePerDay("tick-" + name, name + " tick threw " + ex.GetBaseException().Message);
		}
	}
}

public sealed class Homm3FactoryLogisticsRuntimeHost : MonoBehaviour
{
	public Homm3FactoryLogisticsRuntimeHost(IntPtr ptr) : base(ptr) { }

	private void Update()
	{
		try
		{
			Homm3FactoryLogisticsRuntime.Tick();
		}
		catch (Exception ex)
		{
			Homm3FactoryLogisticsRuntime.LogOncePerDay("tick", "visit host tick threw " + ex.GetBaseException().Message);
		}
	}

	private void OnDestroy() => Homm3FactoryLogisticsRuntime.HostDestroyed();
}
