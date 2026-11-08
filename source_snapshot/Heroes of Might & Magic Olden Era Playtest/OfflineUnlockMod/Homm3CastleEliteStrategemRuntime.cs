using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using DataHero = Hex.Session.Data.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Source-prepared June 21 for Castle Elite Strategem. The spell rows deliberately reuse
/// native Necromancer Will's world-magic mech so the game builds an eug handler; this
/// runtime intercepts only Castle rows with explicit mode parameters and mutates
/// TransferBattle side unit splits before BattleLogic.Init consumes them. Ambush also
/// switches to a Castle-owned arena layout that reuses native interact-object spawns and
/// standard tactics placement. Mode selection is stored per casting DataHero.id and consumed
/// after the first successful application, so only that hero's next battle applies Spread Out /
/// Compress / Ambush. Ambush battle entry was user-proven on June 21 (global mode, before per-hero
/// scoping). Per-hero scoping (Aug 8) read the casting WorldHero through a hint naming a type that
/// does not exist in live interop, so from then on every cast was refused ("world-magic WorldHero
/// member missing", live log 2026-09-27) and the spells did nothing. The handler -> WorldHero ->
/// LogicHero bridge is now pinned in GameSymbols and resolved with exact property types at
/// registration (build-validated against live Hex.dll); the cast path, one-shot consumption and
/// BattleLogic.Init application still need fresh runtime proof.
/// </summary>
internal static class Homm3CastleEliteStrategemRuntime
{
	private const string CastleFactionSid = "homm3_castle";
	private const string CastleHeroPrefix = "homm3_castle_hero_";
	private const string NativeNecromancyMechType = "change_use_necromancy";
	private const string ModeSpreadOut = "spread_out";
	private const string ModeCompress = "compress";
	private const string ModeAmbush = "ambush";
	private const string AmbushArenaLogicSid = "battleArena_homm3_castle_elite_strategem_ambush";
	private const int MaxBattleStacks = 7;
	private static readonly int[] LinearSlots = { 0, 1, 2, 3, 4, 5, 6 };
	private static readonly int[] CenterSlots = { 3, 2, 4, 1, 5, 0, 6 };

	private static bool _registered;
	private static ManualLogSource _log;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static PropertyInfo _handlerWorldHeroProperty;
	private static PropertyInfo _worldHeroLogicHeroProperty;
	private static int _modeRevisionCounter;
	private static int _loggedModeSelections;
	private static int _loggedApplications;
	private static int _loggedSkips;
	private static readonly Dictionary<int, HeroModeState> ModesByHeroId = new();

	private sealed class HeroModeState
	{
		internal string Mode;
		internal int Revision;
		internal string HeroSid;
		// Audit B4 (2026-09-27): hero ids repeat across saves/new games, so a mode is only valid
		// in the session (Homm3SessionIdentity) that selected it.
		internal long SessionKey;
	}

	/// <summary>
	/// Drops stored modes from other sessions (new game / load). Returns false (fail closed) when
	/// the current session cannot be identified; the caller must not apply any stored mode then.
	/// Contract: tools/validate_native_hook_safety_contract.py.
	/// </summary>
	private static bool TryPruneModesToCurrentSession(out long sessionKey, out string failReason)
	{
		if (!Homm3SessionIdentity.TryResolveSessionDataKey(out sessionKey, out failReason))
			return false;
		List<int> stale = null;
		foreach (var pair in ModesByHeroId)
		{
			if (pair.Value == null || pair.Value.SessionKey != sessionKey)
				(stale ??= new List<int>()).Add(pair.Key);
		}
		if (stale != null)
		{
			foreach (var heroId in stale)
				ModesByHeroId.Remove(heroId);
			_log?.LogInfo("HoMM3 Castle Elite Strategem: dropped " + stale.Count
				+ " stored mode(s) from a previous session (new game or load).");
		}
		failReason = null;
		return true;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			var handlerType = ResolveRequiredTypeByHint(
				hexAssembly,
				GameSymbols.CastleEliteStrategem.NecromancyWorldMagicHandlerTypeHints,
				"homm3.castle.eliteStrategem.necromancyHandler");
			var castMethod = ResolveRequiredExactNamedMethod(
				handlerType,
				typeof(bool),
				Type.EmptyTypes,
				GameSymbols.CastleEliteStrategem.NecromancyWorldMagicCast.NameHints[0],
				"homm3.castle.eliteStrategem.necromancyHandler.cast",
				m => !m.IsStatic);

			var battleLogicType = ResolveRequiredTypeByHint(
				hexAssembly,
				GameSymbols.DraconicDominion.BattleLogicTypeHints,
				"homm3.castle.eliteStrategem.battleLogic");
			var transferBattleType = ResolveRequiredTypeByName(
				hexAssembly,
				GameSymbols.DraconicDominion.TransferBattleTypeName,
				"homm3.castle.eliteStrategem.transferBattle");
			var battleLogicInitMethod = ResolveRequiredExactNamedMethod(
				battleLogicType,
				typeof(void),
				new[] { typeof(int), transferBattleType, typeof(bool), typeof(bool) },
				GameSymbols.DraconicDominion.BattleLogicInit.NameHints[0],
				"homm3.castle.eliteStrategem.battleLogic.init",
				m => !m.IsStatic);
			var logicHeroType = ResolveRequiredTypeByName(
				hexAssembly,
				GameSymbols.CastleEliteStrategem.LogicHeroTypeName,
				"homm3.castle.eliteStrategem.logicHero");
			_logicHeroDataHeroGetter = ResolveRequiredExactNamedMethod(
				logicHeroType,
				typeof(DataHero),
				Type.EmptyTypes,
				GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter.NameHints[0],
				"homm3.castle.eliteStrategem.logicHero.dataHeroGetter",
				m => !m.IsStatic);
			// Casting-hero identity bridge (handler -> WorldHero -> LogicHero). Resolved here, with
			// exact property types, so a drifted name fails registration loudly instead of every
			// cast failing closed later with "WorldHero member missing".
			var worldHeroType = ResolveRequiredTypeByHint(
				hexAssembly,
				GameSymbols.HomecomingBoatTravel.WorldHeroTypeHints,
				"homm3.castle.eliteStrategem.worldHero");
			_handlerWorldHeroProperty = ResolveRequiredTypedProperty(
				handlerType,
				GameSymbols.CastleEliteStrategem.NecromancyWorldMagicWorldHeroProperty,
				worldHeroType,
				"homm3.castle.eliteStrategem.necromancyHandler.worldHero");
			_worldHeroLogicHeroProperty = ResolveRequiredTypedProperty(
				worldHeroType,
				GameSymbols.CastleEliteStrategem.WorldHeroLogicHeroProperty,
				logicHeroType,
				"homm3.castle.eliteStrategem.worldHero.logicHero");

			PatchPrefix(harmony, castMethod, nameof(PrefixNecromancyWorldMagicCast));
			PatchPrefix(harmony, battleLogicInitMethod, nameof(PrefixBattleLogicInit));
			_registered = true;
			Homm3CastleEliteStrategemIndicatorBootstrap.Ensure();
			_log?.LogInfo("HoMM3 Castle Elite Strategem runtime registered on " + FormatMethod(castMethod) + " and " + FormatMethod(battleLogicInitMethod) + ". Spellbook selection is native-handler-compatible; start-combat slot placement remains runtime-unvalidated until live proof.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Castle Elite Strategem runtime not registered; exact surface missing: " + ex.Message);
		}
	}

	private static bool PrefixNecromancyWorldMagicCast(object __instance, ref bool __result)
	{
		var eliteModeRecognized = false;
		try
		{
			var setting = ReadMember(__instance, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicSettingMembers) as MagicSetting;
			if (!TryReadEliteStrategemMode(setting, out var mode, out var sidOrReason))
				return true;
			eliteModeRecognized = true;

			if (!TryResolveCastingHeroIdentity(__instance, out var heroId, out var heroSid, out var ownerFailReason))
			{
				__result = false;
				LogLimited("spellbook mode " + mode + " refused: casting hero identity unresolved (" + ownerFailReason + "); magic=" + sidOrReason + ".");
				return false;
			}

			if (!TryPruneModesToCurrentSession(out var sessionKey, out var sessionFailReason))
			{
				__result = false;
				LogLimited("spellbook mode " + mode + " refused: adventure session identity unresolved (" + sessionFailReason + "); magic=" + sidOrReason + ".");
				return false;
			}

			var revision = ++_modeRevisionCounter;
			ModesByHeroId[heroId] = new HeroModeState
			{
				Mode = mode,
				Revision = revision,
				HeroSid = heroSid,
				SessionKey = sessionKey,
			};
			Homm3CastleEliteStrategemIndicatorBootstrap.SetMode(mode, revision);
			__result = true;
			if (_loggedModeSelections++ < 24)
				_log?.LogInfo("HoMM3 Castle Elite Strategem mode selected: mode=" + mode + " magic=" + sidOrReason + " heroId=" + heroId + " heroSid=" + (heroSid ?? "null") + " revision=" + revision + "; scoped to that hero only; native Necromancer Will state mutation skipped.");
			return false;
		}
		catch (Exception ex)
		{
			if (eliteModeRecognized)
			{
				__result = false;
				LogLimited("recognized Castle spellbook mode interception failed closed; native handler suppressed: " + ex.Message);
				return false;
			}
			LogLimited("spellbook mode inspection failed; native handler remains responsible: " + ex.Message);
			return true;
		}
	}

	private static void PrefixBattleLogicInit(object __1)
	{
		try
		{
			ApplySelectedModeToBattle(__1 as TransferBattle);
		}
		catch (Exception ex)
		{
			LogLimited("battle init placement mutation failed closed: " + ex.Message);
		}
	}

	private static void ApplySelectedModeToBattle(TransferBattle transferBattle)
	{
		if (ModesByHeroId.Count == 0)
			return;
		if (!TryPruneModesToCurrentSession(out _, out var sessionFailReason))
		{
			LogLimited("stored Elite Strategem mode skipped: adventure session identity unresolved (" + sessionFailReason + ").");
			return;
		}
		if (ModesByHeroId.Count == 0)
			return;
		if (transferBattle?.sides == null || transferBattle.sides.Length < 2)
		{
			LogLimited("stored Elite Strategem mode skipped: transfer battle sides missing.");
			return;
		}

		var sides = transferBattle.sides.Where(side => side != null).ToList();
		if (sides.Count < 2)
		{
			LogLimited("stored Elite Strategem mode skipped: fewer than two non-null transfer sides.");
			return;
		}

		if (!TryFindOwnedStrategemSide(sides, out var ownerSide, out var ownerHeroId, out var ownerState, out var ownerFailReason))
		{
			LogLimited("stored Elite Strategem mode skipped: " + ownerFailReason + ".");
			return;
		}

		var mode = ownerState.Mode;
		var revision = ownerState.Revision;

		// Claim the one-shot token before mutating TransferBattle. If a later write
		// throws after a partial mutation, a future battle must not repeat that mode.
		ModesByHeroId.Remove(ownerHeroId);
		var changedSides = 0;
		var summaries = new List<string>();
		foreach (var side in sides)
		{
			if (ReferenceEquals(side, ownerSide))
				continue;
			if (TryApplyEnemyPlacementMode(side, mode, out var before, out var after, out var failReason))
			{
				changedSides++;
				summaries.Add("enemy before=[" + before + "] after=[" + after + "]");
			}
			else
			{
				LogLimited("selected mode " + mode + " skipped enemy side: " + failReason);
			}
		}

		string ownFailReason = null;
		string arenaFailReason = null;
		if (string.Equals(mode, ModeAmbush, StringComparison.Ordinal)
		    && TryAssignExistingUnitsToSlots(ownerSide, LinearSlots, out var ownBefore, out var ownAfter, out ownFailReason))
		{
			changedSides++;
			summaries.Add("owner before=[" + ownBefore + "] after=[" + ownAfter + "]");
		}
		else if (string.Equals(mode, ModeAmbush, StringComparison.Ordinal))
		{
			LogLimited("selected ambush mode could not reposition owner side: " + ownFailReason);
		}

		if (string.Equals(mode, ModeAmbush, StringComparison.Ordinal)
		    && TryApplyAmbushArenaLayout(transferBattle, ownerSide, sides, out var arenaSummary, out arenaFailReason))
		{
			changedSides++;
			summaries.Add(arenaSummary);
		}
		else if (string.Equals(mode, ModeAmbush, StringComparison.Ordinal))
		{
			LogLimited("selected ambush mode could not apply arena layout: " + arenaFailReason);
		}

		if (changedSides == 0)
		{
			if (!ModesByHeroId.ContainsKey(ownerHeroId))
				ModesByHeroId.Add(ownerHeroId, ownerState);
			LogLimited("selected mode " + mode + " failed closed: no side unit arrays were changed.");
			return;
		}

		if (_loggedApplications++ < 24)
			_log?.LogInfo("HoMM3 Castle Elite Strategem claimed and applied mode=" + mode + " heroSid=" + (ownerState.HeroSid ?? "null") + " heroId=" + ownerHeroId + " revision=" + revision + " before BattleLogic.Init; " + string.Join(" | ", summaries));
	}

	private static bool TryReadEliteStrategemMode(MagicSetting setting, out string mode, out string sidOrReason)
	{
		mode = null;
		sidOrReason = null;
		if (setting == null)
		{
			sidOrReason = "missing MagicSetting";
			return false;
		}
		if (!string.Equals(setting.mechType, NativeNecromancyMechType, StringComparison.Ordinal))
		{
			sidOrReason = "non-Elite mechType=" + (setting.mechType ?? "null");
			return false;
		}

		var candidate = FirstParameter(setting.parameters);
		if (!IsEliteMode(candidate))
		{
			sidOrReason = "non-Elite parameters";
			return false;
		}

		mode = candidate;
		sidOrReason = ResolveMagicSidFromDescription(setting) ?? candidate;
		return true;
	}

	private static string FirstParameter(object parameters)
	{
		if (parameters == null)
			return null;
		if (parameters is string[] managed && managed.Length > 0)
			return managed[0];
		if (parameters is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
				return item as string ?? item?.ToString();
		}
		return null;
	}

	private static string ResolveMagicSidFromDescription(MagicSetting setting)
	{
		try
		{
			if (setting == null)
				return null;
			var description = setting.castInfoSid;
			if (!string.IsNullOrWhiteSpace(description))
				return description;
		}
		catch { }
		return null;
	}

	private static bool TryApplyEnemyPlacementMode(TransferSide side, string mode, out string before, out string after, out string failReason)
	{
		before = SummarizeUnits(side?.units);
		after = null;
		failReason = null;
		if (side?.units == null || side.units.Length == 0)
		{
			failReason = "unit array missing";
			return false;
		}

		TransferUnit[] next;
		if (string.Equals(mode, ModeSpreadOut, StringComparison.Ordinal))
			next = BuildSpreadUnits(side.units, LinearSlots, out failReason);
		else if (string.Equals(mode, ModeCompress, StringComparison.Ordinal))
			next = BuildCompressedUnits(side.units, CenterSlots, out failReason);
		else if (string.Equals(mode, ModeAmbush, StringComparison.Ordinal))
			next = BuildCompressedUnits(side.units, LinearSlots, out failReason);
		else
		{
			failReason = "unknown mode " + (mode ?? "null");
			return false;
		}

		if (next == null || next.Length == 0)
			return false;
		side.units = next;
		after = SummarizeUnits(side.units);
		return true;
	}

	private static bool TryApplyAmbushArenaLayout(TransferBattle transferBattle, TransferSide castleSide, IReadOnlyList<TransferSide> sides, out string summary, out string failReason)
	{
		summary = null;
		failReason = null;
		if (transferBattle == null || castleSide == null || sides == null || sides.Count < 2)
		{
			failReason = "transfer battle, Castle side, or sides missing";
			return false;
		}

		var ordered = new List<TransferSide>(sides.Count);
		foreach (var side in sides)
			if (side != null && !ReferenceEquals(side, castleSide))
				ordered.Add(side);
		ordered.Add(castleSide);
		if (ordered.Count != sides.Count)
		{
			failReason = "ambush side ordering could not preserve all non-null sides";
			return false;
		}

		var beforeArena = transferBattle.arenaLogicSid ?? "null";
		var beforeOrder = SummarizeSideOrder(transferBattle.sides);
		transferBattle.arenaLogicSid = AmbushArenaLogicSid;
		transferBattle.sides = ordered.ToArray();
		summary = "ambush arena before=" + beforeArena + " after=" + AmbushArenaLogicSid
		          + " sideOrderBefore=[" + beforeOrder + "] sideOrderAfter=[" + SummarizeSideOrder(transferBattle.sides) + "]";
		return true;
	}

	private static bool TryFindOwnedStrategemSide(IReadOnlyList<TransferSide> sides, out TransferSide ownerSide, out int ownerHeroId, out HeroModeState ownerState, out string failReason)
	{
		ownerSide = null;
		ownerHeroId = 0;
		ownerState = null;
		failReason = null;
		if (sides == null || sides.Count == 0)
		{
			failReason = "transfer sides missing";
			return false;
		}

		TransferSide matchedSide = null;
		var matchedHeroId = 0;
		HeroModeState matchedState = null;
		var matchCount = 0;
		foreach (var side in sides)
		{
			if (side == null)
				continue;
			if (!TryResolveTransferSideHeroId(side, out var heroId, out _, out _))
				continue;
			if (!ModesByHeroId.TryGetValue(heroId, out var state) || !IsEliteMode(state?.Mode))
				continue;
			matchCount++;
			matchedSide = side;
			matchedHeroId = heroId;
			matchedState = state;
		}

		if (matchCount == 0)
		{
			failReason = "no battling hero owns a stored Elite Strategem mode";
			return false;
		}
		if (matchCount > 1)
		{
			failReason = "multiple battling heroes own Elite Strategem modes (" + matchCount + "); refuse ambiguous apply";
			return false;
		}

		ownerSide = matchedSide;
		ownerHeroId = matchedHeroId;
		ownerState = matchedState;
		return true;
	}

	private static bool TryResolveCastingHeroIdentity(object worldMagicHandler, out int heroId, out string heroSid, out string failReason)
	{
		heroId = 0;
		heroSid = null;
		failReason = null;
		if (worldMagicHandler == null)
		{
			failReason = "world-magic handler missing";
			return false;
		}

		if (_handlerWorldHeroProperty == null || _worldHeroLogicHeroProperty == null)
		{
			failReason = "casting-hero bridge not resolved at registration";
			return false;
		}
		if (!_handlerWorldHeroProperty.DeclaringType.IsInstanceOfType(worldMagicHandler))
		{
			failReason = "world-magic handler type " + worldMagicHandler.GetType().FullName + " is not " + _handlerWorldHeroProperty.DeclaringType.FullName;
			return false;
		}

		var worldHero = _handlerWorldHeroProperty.GetValue(worldMagicHandler);
		if (worldHero == null)
		{
			failReason = "world-magic handler " + _handlerWorldHeroProperty.Name + " (casting WorldHero) is null";
			return false;
		}

		var logicHero = _worldHeroLogicHeroProperty.GetValue(worldHero);
		if (logicHero == null)
		{
			failReason = "WorldHero " + _worldHeroLogicHeroProperty.Name + " (LogicHero) is null";
			return false;
		}

		if (!TryResolveLogicHeroIdentity(logicHero, out heroId, out heroSid, out failReason))
			return false;
		return true;
	}

	private static bool TryResolveTransferSideHeroId(TransferSide side, out int heroId, out string heroSid, out string failReason)
	{
		heroId = 0;
		heroSid = null;
		failReason = null;
		if (side == null)
		{
			failReason = "transfer side missing";
			return false;
		}

		if (side.logicHero != null
		    && TryResolveLogicHeroIdentity(side.logicHero, out heroId, out heroSid, out failReason))
			return true;

		var configSid = side.hero?.configId;
		if (IsCastleHeroSid(configSid))
		{
			failReason = "transfer side has Castle TransferHero.configId=" + configSid + " but LogicHero/DataHero id unresolved";
			return false;
		}

		failReason = "transfer side LogicHero/DataHero identity unresolved";
		return false;
	}

	private static bool TryResolveLogicHeroIdentity(object logicHero, out int heroId, out string heroSid, out string failReason)
	{
		heroId = 0;
		heroSid = null;
		failReason = null;
		if (logicHero == null)
		{
			failReason = "LogicHero missing";
			return false;
		}
		if (_logicHeroDataHeroGetter == null)
		{
			failReason = "LogicHero data-Hero getter unavailable";
			return false;
		}
		if (!_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(logicHero))
		{
			failReason = "LogicHero type mismatch for data-Hero getter";
			return false;
		}

		DataHero dataHero;
		try
		{
			dataHero = _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) as DataHero;
		}
		catch (Exception ex)
		{
			failReason = "LogicHero data-Hero resolution failed: " + ex.GetBaseException().Message;
			return false;
		}

		if (dataHero == null)
		{
			failReason = "LogicHero data-Hero missing";
			return false;
		}

		heroSid = dataHero.configSid;
		if (!TryReadDataHeroId(dataHero, out heroId))
		{
			failReason = "DataHero.id missing or non-positive; sid=" + (heroSid ?? "null");
			return false;
		}
		return true;
	}

	private static bool TryReadDataHeroId(DataHero dataHero, out int heroId)
	{
		heroId = 0;
		if (dataHero == null)
			return false;
		var raw = ReadMember(dataHero, GameSymbols.CastleEliteStrategem.DataHeroIdMembers);
		if (raw is int i && i > 0)
		{
			heroId = i;
			return true;
		}
		if (raw != null && int.TryParse(raw.ToString(), out var parsed) && parsed > 0)
		{
			heroId = parsed;
			return true;
		}
		return false;
	}

	private static TransferUnit[] BuildCompressedUnits(TransferUnit[] source, int[] slotOrder, out string failReason)
	{
		failReason = null;
		var input = NormalizeUnits(source, out failReason);
		if (input == null)
			return null;

		var bySid = new Dictionary<string, UnitBucket>(StringComparer.Ordinal);
		foreach (var unit in input)
		{
			if (!bySid.TryGetValue(unit.configSid, out var bucket))
			{
				bucket = new UnitBucket(unit.configSid, unit.modelIndex);
				bySid.Add(unit.configSid, bucket);
			}
			bucket.Stacks += unit.stacks;
		}

		var result = bySid.Values
			.OrderByDescending(bucket => bucket.Stacks)
			.ThenBy(bucket => bucket.ConfigSid, StringComparer.Ordinal)
			.Take(MaxBattleStacks)
			.Select((bucket, index) => NewTransferUnit(bucket.ConfigSid, bucket.Stacks, SlotAt(slotOrder, index), bucket.ModelIndex))
			.ToArray();
		return result;
	}

	private static TransferUnit[] BuildSpreadUnits(TransferUnit[] source, int[] slotOrder, out string failReason)
	{
		failReason = null;
		var units = NormalizeUnits(source, out failReason);
		if (units == null)
			return null;

		var working = units.Select(CloneBucket).ToList();
		while (working.Count < MaxBattleStacks)
		{
			var index = IndexOfLargestSplittableStack(working);
			if (index < 0)
				break;
			var original = working[index];
			var left = original.Stacks / 2;
			var right = original.Stacks - left;
			working[index] = new UnitBucket(original.ConfigSid, original.ModelIndex) { Stacks = left };
			working.Add(new UnitBucket(original.ConfigSid, original.ModelIndex) { Stacks = right });
		}

		var result = working
			.OrderByDescending(bucket => bucket.Stacks)
			.ThenBy(bucket => bucket.ConfigSid, StringComparer.Ordinal)
			.Take(MaxBattleStacks)
			.Select((bucket, index) => NewTransferUnit(bucket.ConfigSid, bucket.Stacks, SlotAt(slotOrder, index), bucket.ModelIndex))
			.ToArray();
		return result;
	}

	private static bool TryAssignExistingUnitsToSlots(TransferSide side, int[] slotOrder, out string before, out string after, out string failReason)
	{
		before = SummarizeUnits(side?.units);
		after = null;
		failReason = null;
		var units = NormalizeUnits(side?.units, out failReason);
		if (units == null)
			return false;
		var result = units
			.OrderBy(unit => unit.slotPos)
			.ThenBy(unit => unit.configSid, StringComparer.Ordinal)
			.Select((unit, index) => NewTransferUnit(unit.configSid, unit.stacks, SlotAt(slotOrder, index), unit.modelIndex))
			.ToArray();
		side.units = result;
		after = SummarizeUnits(side.units);
		return true;
	}

	private static List<TransferUnit> NormalizeUnits(TransferUnit[] source, out string failReason)
	{
		failReason = null;
		if (source == null || source.Length == 0)
		{
			failReason = "unit array missing";
			return null;
		}
		var units = new List<TransferUnit>(source.Length);
		foreach (var unit in source)
		{
			if (unit == null)
			{
				failReason = "unit array contains null entry";
				return null;
			}
			if (string.IsNullOrWhiteSpace(unit.configSid))
			{
				failReason = "unit has empty configSid";
				return null;
			}
			if (unit.stacks <= 0)
			{
				failReason = "unit " + unit.configSid + " has non-positive stacks=" + unit.stacks;
				return null;
			}
			units.Add(unit);
		}
		return units;
	}

	private static UnitBucket CloneBucket(TransferUnit unit)
	{
		return new UnitBucket(unit.configSid, unit.modelIndex) { Stacks = unit.stacks };
	}

	private static int IndexOfLargestSplittableStack(IReadOnlyList<UnitBucket> buckets)
	{
		var bestIndex = -1;
		var bestStacks = 1;
		for (var i = 0; i < buckets.Count; i++)
		{
			var stacks = buckets[i].Stacks;
			if (stacks <= bestStacks)
				continue;
			bestStacks = stacks;
			bestIndex = i;
		}
		return bestIndex;
	}

	private static TransferUnit NewTransferUnit(string sid, int stacks, int slot, int modelIndex)
	{
		var unit = new TransferUnit(sid, stacks, slot);
		unit.modelIndex = modelIndex;
		return unit;
	}

	private static int SlotAt(int[] slotOrder, int index)
	{
		if (slotOrder == null || slotOrder.Length == 0)
			return index;
		return slotOrder[Math.Min(index, slotOrder.Length - 1)];
	}

	private static bool IsCastleTransferSide(TransferSide side)
	{
		if (side == null)
			return false;
		if (IsCastleHeroSid(side.hero?.configId))
			return true;
		if (IsCastleHeroSid(ResolveLogicHeroSid(side.logicHero)))
			return true;
		if (side.units == null)
			return false;
		foreach (var unit in side.units)
		{
			if (unit == null || string.IsNullOrWhiteSpace(unit.configSid))
				continue;
			if (Homm3CustomFactionRegistry.TryGetFactionSidForCustomUnitSid(unit.configSid, out var factionSid)
			    && string.Equals(factionSid, CastleFactionSid, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static string ResolveLogicHeroSid(object logicHero)
	{
		if (logicHero == null || _logicHeroDataHeroGetter == null)
			return null;
		if (!_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(logicHero))
			return null;
		try
		{
			var dataHero = _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) as DataHero;
			return dataHero?.configSid;
		}
		catch
		{
			return null;
		}
	}

	private static bool IsCastleHeroSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid)
		       && sid.Trim().StartsWith(CastleHeroPrefix, StringComparison.Ordinal);
	}

	private static bool IsEliteMode(string mode)
	{
		return string.Equals(mode, ModeSpreadOut, StringComparison.Ordinal)
		       || string.Equals(mode, ModeCompress, StringComparison.Ordinal)
		       || string.Equals(mode, ModeAmbush, StringComparison.Ordinal);
	}

	private static string SummarizeUnits(TransferUnit[] units)
	{
		if (units == null)
			return "null";
		var parts = new List<string>(units.Length);
		for (var i = 0; i < units.Length; i++)
		{
			var unit = units[i];
			if (unit == null)
				parts.Add(i + ":null");
			else
				parts.Add(i + ":" + unit.configSid + "x" + unit.stacks + "@" + unit.slotPos);
		}
		return string.Join(",", parts);
	}

	private static string SummarizeSideOrder(TransferSide[] sides)
	{
		if (sides == null)
			return "null";
		var parts = new List<string>(sides.Length);
		for (var i = 0; i < sides.Length; i++)
		{
			var side = sides[i];
			if (side == null)
			{
				parts.Add(i + ":null");
				continue;
			}
			parts.Add(i + ":sideId=" + side.sideIdInWorld + ",control=" + side.controlType + ",castle=" + IsCastleTransferSide(side));
		}
		return string.Join(";", parts);
	}

	private static Type ResolveRequiredTypeByName(Assembly assembly, string fullName, string symbolId)
	{
		var type = assembly?.GetType(fullName);
		if (type != null)
			return type;
		throw new MissingMemberException(symbolId + " type not found: " + fullName);
	}

	private static Type ResolveRequiredTypeByHint(Assembly assembly, string[] hints, string symbolId)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			var type = assembly?.GetType(hint);
			if (type != null)
				return type;
		}
		throw new MissingMemberException(symbolId + " type not found from hints [" + string.Join(",", hints ?? Array.Empty<string>()) + "]");
	}

	private static MethodInfo ResolveRequiredExactNamedMethod(Type type, Type returnType, Type[] parameterTypes, string methodName, string symbolId, Func<MethodInfo, bool> predicate)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var method in type.GetMethods(flags))
		{
			if (!string.Equals(method.Name, methodName, StringComparison.Ordinal))
				continue;
			if (method.ReturnType != returnType)
				continue;
			var parameters = method.GetParameters();
			if (parameterTypes != null)
			{
				if (parameters.Length != parameterTypes.Length)
					continue;
				var exact = true;
				for (var i = 0; i < parameterTypes.Length; i++)
				{
					if (parameters[i].ParameterType != parameterTypes[i])
					{
						exact = false;
						break;
					}
				}
				if (!exact)
					continue;
			}
			if (predicate != null && !predicate(method))
				continue;
			return method;
		}
		throw new MissingMethodException(symbolId + " exact method not found on " + (type?.FullName ?? "null"));
	}

	private static PropertyInfo ResolveRequiredTypedProperty(Type type, string propertyName, Type propertyType, string symbolId)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			var property = cur.GetProperty(propertyName, flags);
			if (property == null)
				continue;
			if (property.PropertyType != propertyType || property.GetIndexParameters().Length != 0 || property.GetGetMethod(true) == null)
				throw new MissingMemberException(symbolId + " property " + cur.FullName + "." + propertyName + " has type " + property.PropertyType.FullName + ", expected " + propertyType.FullName);
			return property;
		}
		throw new MissingMemberException(symbolId + " property " + propertyName + " not found on " + (type?.FullName ?? "null") + " or its bases");
	}

	private static void PatchPrefix(Harmony harmony, MethodInfo target, string prefixName)
	{
		var prefix = AccessTools.Method(typeof(Homm3CastleEliteStrategemRuntime), prefixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, prefix, out var reason))
			throw new MissingMethodException("prefix incompatible for " + FormatMethod(target) + ": " + reason);
		harmony.Patch(target, prefix: new HarmonyMethod(prefix));
	}

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
			{
				var property = cur.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(obj);
				var field = cur.GetField(name, flags);
				if (field != null)
					return field.GetValue(obj);
				var method = cur.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null)
					return method.Invoke(obj, null);
			}
		}
		return null;
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "null" : method.DeclaringType?.FullName + "." + method.Name;
	}

	private static void LogLimited(string message)
	{
		if (_loggedSkips++ < 36)
			_log?.LogWarning("HoMM3 Castle Elite Strategem runtime: " + message);
	}

	private sealed class UnitBucket
	{
		internal UnitBucket(string configSid, int modelIndex)
		{
			ConfigSid = configSid;
			ModelIndex = modelIndex;
		}

		internal string ConfigSid { get; }
		internal int ModelIndex { get; }
		internal int Stacks { get; set; }
	}
}

internal static class Homm3CastleEliteStrategemIndicatorBootstrap
{
	private const string GoName = "Homm3CastleEliteStrategemIndicator";
	private static bool _registered;
	private static bool _attached;

	internal static void Ensure()
	{
		if (_attached)
			return;
		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3CastleEliteStrategemIndicatorBehaviour>();
				_registered = true;
			}

			var go = new GameObject(GoName);
			go.hideFlags = HideFlags.HideAndDontSave;
			if (go.AddComponent<Homm3CastleEliteStrategemIndicatorBehaviour>() == null)
				Plugin.LogSource?.LogError("HoMM3 Castle Elite Strategem indicator: AddComponent returned null.");
			UnityEngine.Object.DontDestroyOnLoad(go);
			_attached = true;
			Plugin.LogSource?.LogInfo("HoMM3 Castle Elite Strategem indicator: IMGUI host registered.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Castle Elite Strategem indicator: host registration failed: " + ex.Message);
		}
	}

	internal static void SetMode(string mode, int revision)
	{
		Ensure();
		Homm3CastleEliteStrategemIndicatorBehaviour.SetMode(mode, revision);
	}
}

public sealed class Homm3CastleEliteStrategemIndicatorBehaviour : MonoBehaviour
{
	private const float ReferenceHeight = 720f;
	private const float PanelWidth = 292f;
	private const float MinimumPanelHeight = 118f;
	private const float DisplaySeconds = 6f;
	private const float MinimumScale = 0.75f;
	private const float MaximumScale = 3f;
	private static readonly object LockObject = new();
	private static string s_mode;
	private static int s_revision;
	private static GUIStyle s_boxStyle;
	private static GUIStyle s_titleStyle;
	private static GUIStyle s_bodyStyle;
	private static GUIStyle s_buttonStyle;
	private static float s_visibleUntilRealtime;
	private static bool s_dismissed;
	private static int s_styleScaleBucket = -1;
	private static GUISkin s_styleSkin;

	internal static void SetMode(string mode, int revision)
	{
		if (string.IsNullOrWhiteSpace(mode))
			return;
		lock (LockObject)
		{
			s_mode = mode.Trim();
			s_revision = revision;
			s_visibleUntilRealtime = Time.realtimeSinceStartup + DisplaySeconds;
			s_dismissed = false;
		}
	}

	private void OnGUI()
	{
		if (Event.current == null || Screen.width <= 0 || Screen.height <= 0)
			return;

		string mode;
		int revision;
		bool dismissed;
		float visibleUntil;
		lock (LockObject)
		{
			mode = s_mode;
			revision = s_revision;
			dismissed = s_dismissed;
			visibleUntil = s_visibleUntilRealtime;
		}
		if (string.IsNullOrWhiteSpace(mode) || dismissed || Time.realtimeSinceStartup > visibleUntil)
			return;

		// IMGUI coordinates are screen pixels. Scale from the vertical reference so
		// 16:9 and ultrawide displays keep readable text without width-only drift.
		var scale = Mathf.Clamp(Screen.height / ReferenceHeight, MinimumScale, MaximumScale);
		EnsureStyles(scale);
		var safeMargin = Mathf.Clamp(16f * scale, 12f, 32f);
		var width = Mathf.Min(PanelWidth * scale, Mathf.Max(1f, Screen.width - safeMargin * 2f));
		var horizontalPadding = Mathf.Min(12f * scale, width * 0.15f);
		var contentWidth = Mathf.Max(1f, width - horizontalPadding * 2f);
		var bodyText = "Active: " + ModeTitle(mode) + "\nApplies to this hero's next battle. #" + revision;
		var bodyContent = new GUIContent(bodyText);
		var titleHeight = Mathf.Max(26f * scale, s_titleStyle.CalcHeight(new GUIContent("Elite Strategem"), contentWidth));
		var bodyHeight = Mathf.Max(40f * scale, s_bodyStyle.CalcHeight(bodyContent, contentWidth));
		var buttonHeight = Mathf.Max(24f * scale, s_buttonStyle.CalcHeight(new GUIContent("OK"), contentWidth));
		var verticalPadding = 10f * scale;
		var gap = 4f * scale;
		var height = Mathf.Max(MinimumPanelHeight * scale, verticalPadding * 2f + titleHeight + gap + bodyHeight + gap + buttonHeight);
		var maxHeight = Mathf.Max(1f, Screen.height - safeMargin * 2f);
		if (height > maxHeight)
		{
			bodyHeight = Mathf.Max(1f, maxHeight - verticalPadding * 2f - titleHeight - gap * 2f - buttonHeight);
			height = maxHeight;
		}
		var x = Mathf.Clamp((Screen.width - width) * 0.5f, safeMargin, Mathf.Max(safeMargin, Screen.width - width - safeMargin));
		var y = Mathf.Clamp(Screen.height * 0.24f, safeMargin, Mathf.Max(safeMargin, Screen.height - height - safeMargin));
		var rect = new Rect(x, y, width, height);
		GUI.Box(rect, GUIContent.none, s_boxStyle);
		var contentX = rect.x + horizontalPadding;
		var titleRect = new Rect(contentX, rect.y + verticalPadding, contentWidth, titleHeight);
		var bodyRect = new Rect(contentX, titleRect.yMax + gap, contentWidth, bodyHeight);
		var buttonWidth = Mathf.Min(76f * scale, contentWidth);
		var buttonRect = new Rect(rect.xMax - horizontalPadding - buttonWidth, rect.yMax - verticalPadding - buttonHeight, buttonWidth, buttonHeight);
		GUI.Label(titleRect, "Elite Strategem", s_titleStyle);
		GUI.Label(bodyRect, bodyContent, s_bodyStyle);
		if (GUI.Button(buttonRect, "OK", s_buttonStyle))
		{
			lock (LockObject)
			{
				s_dismissed = true;
			}
		}
	}

	private static void EnsureStyles(float scale)
	{
		var bucket = Mathf.RoundToInt(scale * 100f);
		if (bucket == s_styleScaleBucket && s_styleSkin == GUI.skin && s_boxStyle != null && s_titleStyle != null && s_bodyStyle != null && s_buttonStyle != null)
			return;
		s_styleScaleBucket = bucket;
		s_styleSkin = GUI.skin;
		s_boxStyle = new GUIStyle(GUI.skin.box);
		var padding = new RectOffset();
		padding.left = Mathf.RoundToInt(10f * scale);
		padding.right = Mathf.RoundToInt(10f * scale);
		padding.top = Mathf.RoundToInt(8f * scale);
		padding.bottom = Mathf.RoundToInt(8f * scale);
		s_boxStyle.padding = padding;
		s_titleStyle = new GUIStyle(GUI.skin.label)
		{
			fontSize = Mathf.RoundToInt(16f * scale),
			fontStyle = FontStyle.Bold,
			alignment = TextAnchor.MiddleLeft,
		};
		s_titleStyle.normal.textColor = new Color(1f, 0.92f, 0.58f, 1f);
		s_bodyStyle = new GUIStyle(GUI.skin.label)
		{
			fontSize = Mathf.RoundToInt(13f * scale),
			alignment = TextAnchor.UpperLeft,
			wordWrap = true,
		};
		s_bodyStyle.normal.textColor = Color.white;
		s_buttonStyle = new GUIStyle(GUI.skin.button)
		{
			fontSize = Mathf.RoundToInt(12f * scale),
			fontStyle = FontStyle.Bold,
			alignment = TextAnchor.MiddleCenter,
		};
	}

	private static string ModeTitle(string mode)
	{
		if (string.Equals(mode, "spread_out", StringComparison.Ordinal))
			return "Spread Out";
		if (string.Equals(mode, "compress", StringComparison.Ordinal))
			return "Compress";
		if (string.Equals(mode, "ambush", StringComparison.Ordinal))
			return "Ambush";
		return mode;
	}
}



