using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Hex.Session.Data;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using DataHero = Hex.Session.Data.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3 Dungeon Captives (replaces Draconic Dominion's flee-recruit redirect).
///
/// Capture: when a human clicks the native "let them flee" button (BhSquadEscapeUISession escape
/// click) and the hero owns skill_faction_homm3_dungeon, the fleeing squad's strength
/// (sum of UnitLogicConfig.squadValue x amount) is banked on the hero. The prefix only reads the
/// squad/hero context; the postfix records it after the native flee resolved, so the fight button
/// never records anything and the native flow is never suppressed.
///
/// State lives only in native hero map buffs, so it is saved and loaded with the hero by the
/// native buff system (Data.Hero.buffs): one visible tier buff (homm3_dungeon_captives_tier_N,
/// +N Attack / +N Defense) and hidden binary-weight marker buffs that encode the exact banked
/// strength (100-strength units) and the captured-squad count. Every read reconstructs the state
/// from those buffs; there is no managed cache that could leak across saves or sessions.
///
/// Spells: Execute / Ransom rows reuse the native Necromancer Will world-magic handler (the Castle
/// Elite Strategem pattern) with Dungeon-only parameters [mode, level]. Execute grants XP through
/// the native exp component AddExp (native level-up loop), Ransom grants gold through the shared
/// reward-economy adapter. Both empty the captives first and pay only after the buffs were cleared.
///
/// UI: Homm3DungeonCaptivesHud (hero-portrait skill meter, shared Homm3HeroSkillMeterHud) and Homm3DungeonCaptivesBuffTooltip (live
/// hero-profile buff tooltip) in Homm3DungeonCaptivesHud.cs; both read this state on demand.
///
/// Proof tier: source + static native disassembly + build. Runtime unproven.
/// </summary>
internal static class Homm3DungeonCaptivesRuntime
{
	internal const string FactionSkillSid = "skill_faction_homm3_dungeon";
	internal const string InterrogationSubSkillSid = "sub_skill_faction_homm3_dungeon_draconic_diplomacy_2";
	internal const string SlaveMarketsSubSkillSid = "sub_skill_faction_homm3_dungeon_draconic_diplomacy_5";
	internal const string DungeonCellsSubSkillSid = "sub_skill_faction_homm3_dungeon_draconic_diplomacy_6";

	private const string NativeNecromancyMechType = "change_use_necromancy";
	internal const string ExecuteMode = "homm3_dungeon_captives_execute";
	internal const string RansomMode = "homm3_dungeon_captives_ransom";

	internal const string TierBuffPrefix = "homm3_dungeon_captives_tier_";
	internal const string StrengthBitBuffPrefix = "homm3_dungeon_captives_strength_bit_";
	internal const string SquadBitBuffPrefix = "homm3_dungeon_captives_squads_bit_";
	internal const int StrengthBitCount = 20;
	internal const int SquadBitCount = 8;
	internal const int StrengthUnit = 100;
	internal const int MaxStrengthUnits = (1 << StrengthBitCount) - 1;
	internal const int MaxSquads = (1 << SquadBitCount) - 1;

	/// <summary>Effective-strength thresholds for tiers 1..5 (tier N = +N Attack / +N Defense).</summary>
	internal static readonly int[] TierThresholds = { 2000, 6000, 12000, 22000, 36000 };

	/// <summary>Execute XP per banked strength at Basic/Advanced/Expert (K_xp 0.11 x 0.5/0.75/1.0).</summary>
	internal static readonly double[] ExecuteXpPerStrength = { 0.055, 0.0825, 0.11 };

	/// <summary>Ransom gold per banked strength at Basic/Advanced/Expert (K_gold 0.8 x 0.25/0.375/0.5).</summary>
	internal static readonly double[] RansomGoldPerStrength = { 0.2, 0.3, 0.4 };

	internal const double SlaveMarketsGoldMultiplier = 1.25;
	internal const double InterrogationManaPerXp = 0.10;
	internal const double DungeonCellsTierStrengthMultiplier = 1.25;
	private const float CaptureDedupeSeconds = 2f;

	private static bool _registrationAttempted;
	/// <summary>Core stage (hero bridge, exp, buffs) resolved; the UI snapshot and both hooks need it.</summary>
	private static bool _registered;
	private static bool _spellsRegistered;
	private static bool _captureRegistered;
	private static ManualLogSource _log;
	private static MemberInfo _escapeSquadMember;
	private static MemberInfo _escapeWorldHeroMember;
	private static MemberInfo _squadDataMember;
	private static PropertyInfo _worldHeroLogicHeroProperty;
	private static PropertyInfo _handlerWorldHeroProperty;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static PropertyInfo _expComponentProperty;
	private static MethodInfo _expAddMethod;
	private static PropertyInfo _buffManagerProperty;
	private static MethodInfo _buffAddMethod;
	private static MethodInfo _buffRemoveMethod;
	private static MethodInfo _buffGetMethod;
	private static IntPtr _lastCapturedSquadPointer;
	private static float _lastCaptureRealtime;
	private static int _loggedCaptures;
	private static int _loggedCasts;
	private static int _loggedSkips;
	private static int _loggedEscapeClicks;
	private static int _loggedForeignCasts;

	internal sealed class CaptureContext
	{
		internal object LogicHero;
		internal DataHero DataHero;
		internal long Strength;
		internal IntPtr SquadPointer;
		internal string SquadSummary;
	}

	internal readonly struct CaptivesState
	{
		internal CaptivesState(int strengthUnits, int squads, int tier)
		{
			StrengthUnits = strengthUnits;
			Squads = squads;
			Tier = tier;
		}

		internal int StrengthUnits { get; }
		internal int Squads { get; }
		internal int Tier { get; }
		internal long Strength => (long)StrengthUnits * StrengthUnit;
		internal bool IsEmpty => StrengthUnits <= 0;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registrationAttempted || harmony == null)
			return;
		_registrationAttempted = true;
		_log = log;
		var hexAssembly = typeof(TransferBattle).Assembly;

		// Stage 1 (core): hero bridge, exp component and buff manager. Spells, capture and UI all need it.
		Type worldHeroType = null;
		try
		{
			var logicHeroType = hexAssembly.GetType(GameSymbols.CastleEliteStrategem.LogicHeroTypeName)
			                    ?? throw new TypeLoadException("Missing Hex.Session.Logic.Hero");
			// Hero bridge (WorldHero -> Logic.Hero -> Data.Hero), shared with Castle Elite Strategem.
			worldHeroType = ResolveRequiredTypeByHint(hexAssembly, GameSymbols.HomecomingBoatTravel.WorldHeroTypeHints, "homm3.dungeon.captives.worldHero");
			_worldHeroLogicHeroProperty = ResolveRequiredTypedProperty(worldHeroType, GameSymbols.CastleEliteStrategem.WorldHeroLogicHeroProperty, logicHeroType, "homm3.dungeon.captives.worldHero.logicHero");
			_logicHeroDataHeroGetter = ResolveRequiredNamedMethod(logicHeroType, typeof(DataHero), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter, instance: true);

			// Native exp component + AddExp(int, bool).
			_expComponentProperty = ResolveRequiredProperty(logicHeroType, GameSymbols.DungeonCaptives.LogicHeroExpComponentMembers[0], "homm3.dungeon.captives.logicHero.expComponent");
			_expAddMethod = ResolveRequiredNamedMethod(_expComponentProperty.PropertyType, typeof(void), new[] { typeof(int), typeof(bool) }, GameSymbols.DungeonCaptives.ExpComponentAddExp, instance: true);

			// Native hero map-buff manager Add/Remove/Get.
			_buffManagerProperty = ResolveRequiredProperty(logicHeroType, GameSymbols.DungeonCaptives.LogicHeroBuffManagerMembers[0], "homm3.dungeon.captives.logicHero.buffManager");
			var buffManagerType = _buffManagerProperty.PropertyType;
			_buffAddMethod = ResolveRequiredNamedMethod(buffManagerType, typeof(void), new[] { typeof(string), typeof(Il2CppReferenceArray<BuffDuration>) }, GameSymbols.DungeonCaptives.BuffManagerAdd, instance: true);
			_buffRemoveMethod = ResolveRequiredNamedMethod(buffManagerType, typeof(void), new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerRemove, instance: true);
			_buffGetMethod = ResolveRequiredNamedMethod(buffManagerType, null, new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerGet, instance: true);
			if (!string.Equals(_buffGetMethod.ReturnType.FullName, "Hex.Session.Logic.Buff", StringComparison.Ordinal))
				throw new MissingMethodException("homm3.dungeon.captives.buffManager.get returns " + _buffGetMethod.ReturnType.FullName + ", expected Hex.Session.Logic.Buff");
			_registered = true;
			_log?.LogInfo("HoMM3 Dungeon Captives [core] registered: worldHero=" + worldHeroType.FullName
				+ ", exp=" + FormatMethod(_expAddMethod)
				+ ", buffs=" + FormatMethod(_buffAddMethod) + "/" + _buffRemoveMethod.Name + "/" + _buffGetMethod.Name + ".");
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Dungeon Captives [core] NOT registered (fail closed: no capture, no Execute/Ransom handling, no meter): " + ex.GetBaseException().Message);
		}

		if (_registered)
		{
			// Stage 2 (spells): Execute / Ransom ride the native Necromancer Will world-magic handler (Castle Elite Strategem pattern).
			try
			{
				var handlerType = ResolveRequiredTypeByHint(hexAssembly, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicHandlerTypeHints, "homm3.dungeon.captives.necromancyHandler");
				var castMethod = ResolveRequiredNamedMethod(handlerType, typeof(bool), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicCast, instance: true);
				_handlerWorldHeroProperty = ResolveRequiredTypedProperty(handlerType, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicWorldHeroProperty, worldHeroType, "homm3.dungeon.captives.necromancyHandler.worldHero");
				Patch(harmony, castMethod, nameof(PrefixNecromancyWorldMagicCast), null);
				_spellsRegistered = true;
				_log?.LogInfo("HoMM3 Dungeon Captives [spells] registered: Execute/Ransom prefix on " + FormatMethod(castMethod) + ".");
			}
			catch (Exception ex)
			{
				_log?.LogError("HoMM3 Dungeon Captives [spells] NOT registered (Execute/Ransom fall through to the native Necromancer Will handler and do nothing): " + ex.GetBaseException().Message);
			}

			// Stage 3 (capture): the escape popup context members, then its own escape click.
			try
			{
				var escapeType = hexAssembly.GetType(GameSymbols.DraconicDominion.SquadEscapeUiTypeName)
				                 ?? throw new TypeLoadException("Missing " + GameSymbols.DraconicDominion.SquadEscapeUiTypeId + " type " + GameSymbols.DraconicDominion.SquadEscapeUiTypeName);
				// Declared on the popup itself: live interop also exposes the hidden base BhScreen method with the same name and signature.
				var escapeClick = ResolveRequiredNamedMethod(escapeType, typeof(void), Type.EmptyTypes, GameSymbols.DraconicDominion.SquadEscapeOnEscapeClick, instance: true, declaredOnType: true);
				_escapeSquadMember = ResolveRequiredMember(escapeType, GameSymbols.DraconicDominion.SquadEscapeSquadMembers, "homm3.dungeon.captives.escape.squad");
				_escapeWorldHeroMember = ResolveRequiredMember(escapeType, GameSymbols.DraconicDominion.SquadEscapeLogicHeroMembers, "homm3.dungeon.captives.escape.worldHero");
				var squadWrapperType = MemberValueType(_escapeSquadMember);
				var escapeHeroType = MemberValueType(_escapeWorldHeroMember);
				_squadDataMember = ResolveRequiredTypedMember(squadWrapperType, typeof(DataSquad), GameSymbols.DraconicDominion.SquadWrapperDataSquadMembers, "homm3.dungeon.captives.squadWrapper.dataSquad");
				if (escapeHeroType != worldHeroType)
					throw new MissingMemberException("homm3.dungeon.captives escape-popup hero type " + escapeHeroType.FullName + " differs from the world hero type " + worldHeroType.FullName);
				Patch(harmony, escapeClick, nameof(PrefixEscapeClick), nameof(PostfixEscapeClick));
				_captureRegistered = true;
				_log?.LogInfo("HoMM3 Dungeon Captives [capture] registered: " + FormatMethod(escapeClick)
					+ " (prefix reads, postfix records), squad=" + _escapeSquadMember.Name + "." + _squadDataMember.Name + ", hero=" + _escapeWorldHeroMember.Name + ".");
			}
			catch (Exception ex)
			{
				_log?.LogError("HoMM3 Dungeon Captives [capture] NOT registered (letting enemies flee banks nothing; flee stays native): " + ex.GetBaseException().Message);
			}

			Homm3DungeonCaptivesHud.TryRegister(harmony, log);
			Homm3DungeonCaptivesBuffTooltip.TryRegister(harmony, log);
		}

		var allOk = _registered && _spellsRegistered && _captureRegistered && Homm3DungeonCaptivesHud.IsRegistered && Homm3DungeonCaptivesBuffTooltip.IsRegistered;
		var summary = "HoMM3 Dungeon Captives registration summary: core=" + Stage(_registered) + " spells=" + Stage(_spellsRegistered)
			+ " capture=" + Stage(_captureRegistered) + " meter=" + Stage(Homm3DungeonCaptivesHud.IsRegistered)
			+ " tooltip=" + Stage(Homm3DungeonCaptivesBuffTooltip.IsRegistered) + ". Proof tier: build; runtime unproven.";
		if (allOk)
			_log?.LogInfo(summary);
		else
			_log?.LogError(summary);
	}

	private static string Stage(bool ok)
	{
		return ok ? "ok" : "FAILED";
	}

	// ---------------------------------------------------------------- capture

	private static void PrefixEscapeClick(object __instance, ref CaptureContext __state)
	{
		__state = null;
		try
		{
			var squadWrapper = ReadResolvedMember(__instance, _escapeSquadMember);
			var squad = ReadResolvedMember(squadWrapper, _squadDataMember) as DataSquad;
			if (squad == null || !squad.isEscape)
			{
				LogEscapeClick("escape click fired; nothing recorded: " + (squad == null ? "popup squad unresolved" : "squad not marked DataSquad.isEscape") + ".");
				return;
			}
			var worldHero = ReadResolvedMember(__instance, _escapeWorldHeroMember);
			var logicHero = worldHero == null ? null : _worldHeroLogicHeroProperty.GetValue(worldHero);
			var dataHero = ResolveDataHero(logicHero);
			if (dataHero == null)
			{
				LogEscapeClick("escape click fired; nothing recorded: popup hero unresolved (worldHero " + (worldHero == null ? "null" : "set") + ", logicHero " + (logicHero == null ? "null" : "set") + ").");
				return;
			}
			var rank = Homm3DungeonDraconicDominionHook.ResolveFactionSkillRank(dataHero);
			if (rank <= 0)
			{
				LogEscapeClick("escape click fired; nothing recorded: hero " + DescribeHero(dataHero) + " lacks " + FactionSkillSid + ".");
				return;
			}
			if (!TryComputeSquadStrength(squad, out var strength, out var summary, out var failReason))
			{
				LogSkip("capture refused: " + failReason + " (squad " + summary + ").");
				return;
			}
			LogEscapeClick("escape click fired: hero " + DescribeHero(dataHero) + " rank=" + rank + " squad=[" + summary + "] strength=" + strength + "; recording after the native flee.");
			__state = new CaptureContext
			{
				LogicHero = logicHero,
				DataHero = dataHero,
				Strength = strength,
				SquadPointer = (squadWrapper as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero,
				SquadSummary = summary,
			};
		}
		catch (Exception ex)
		{
			__state = null;
			LogSkip("capture context read failed; nothing recorded: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixEscapeClick(CaptureContext __state)
	{
		if (__state == null)
			return;
		try
		{
			var now = Time.realtimeSinceStartup;
			if (__state.SquadPointer != IntPtr.Zero
			    && __state.SquadPointer == _lastCapturedSquadPointer
			    && now - _lastCaptureRealtime < CaptureDedupeSeconds)
			{
				LogSkip("capture deduped: same escape squad clicked again within " + CaptureDedupeSeconds + "s.");
				return;
			}
			_lastCapturedSquadPointer = __state.SquadPointer;
			_lastCaptureRealtime = now;

			if (!TryReadState(__state.LogicHero, __state.DataHero, out var before, out var readFail))
			{
				LogSkip("capture refused: captives state unreadable (" + readFail + ").");
				return;
			}
			var addedUnits = (int)Math.Max(1, Math.Min(MaxStrengthUnits, (__state.Strength + StrengthUnit / 2) / StrengthUnit));
			var units = (int)Math.Min(MaxStrengthUnits, (long)before.StrengthUnits + addedUnits);
			var squads = Math.Min(MaxSquads, before.Squads + 1);
			if (!TryWriteState(__state.LogicHero, __state.DataHero, units, squads, out var after, out var writeFail))
			{
				_log?.LogError("HoMM3 Dungeon Captives: capture write incomplete (" + writeFail + "); state may be partial.");
				return;
			}
			var readback = TryReadState(__state.LogicHero, __state.DataHero, out var stored, out var readbackFail)
				? "readback strength=" + stored.Strength + " squads=" + stored.Squads + " tierBuff=" + stored.Tier
				: "readback failed (" + readbackFail + ")";
			if (_loggedCaptures++ < 40)
				_log?.LogInfo("HoMM3 Dungeon Captives captured: hero=" + DescribeHero(__state.DataHero)
					+ " squad=[" + __state.SquadSummary + "] strength=+" + __state.Strength
					+ " banked=" + after.Strength + " squads=" + after.Squads + " tier=" + before.Tier + "->" + after.Tier + "; " + readback + ".");
			Homm3DungeonCaptivesHud.NotifyStateChanged("capture");
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Dungeon Captives: capture record failed: " + ex.GetBaseException().Message);
		}
	}

	private static bool TryComputeSquadStrength(DataSquad squad, out long strength, out string summary, out string failReason)
	{
		strength = 0;
		failReason = null;
		var parts = new List<string>();
		if (squad?.units == null)
		{
			summary = "none";
			failReason = "fleeing squad has no units";
			return false;
		}
		foreach (var unit in squad.units)
		{
			if (unit == null || unit.amount <= 0)
				continue;
			var sid = NormalizeSid(ReadMember(unit, GameSymbols.DraconicDominion.DataSquadUnitSidMembers) as string);
			parts.Add((sid ?? "?") + ":" + unit.amount);
			var config = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(sid);
			if (config == null)
			{
				summary = string.Join(",", parts);
				failReason = "UnitLogicConfig missing for " + (sid ?? "null");
				return false;
			}
			strength += (long)Math.Max(0, config.squadValue) * unit.amount;
		}
		summary = parts.Count == 0 ? "none" : string.Join(",", parts);
		if (strength <= 0)
		{
			failReason = "fleeing squad strength is 0";
			return false;
		}
		return true;
	}

	// ---------------------------------------------------------------- spells

	private static bool PrefixNecromancyWorldMagicCast(object __instance, ref bool __result)
	{
		var recognized = false;
		try
		{
			var setting = ReadMember(__instance, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicSettingMembers) as MagicSetting;
			if (!TryReadCaptivesSpell(setting, out var mode, out var level, out var malformed))
			{
				if (malformed != null)
				{
					__result = false;
					_log?.LogError("HoMM3 Dungeon Captives spell refused: malformed Captives magic setting (" + malformed + "); native handler suppressed.");
					return false;
				}
				if (setting != null && string.Equals(setting.mechType, NativeNecromancyMechType, StringComparison.Ordinal) && _loggedForeignCasts++ < 8)
					_log?.LogInfo("HoMM3 Dungeon Captives spell hook: non-Captives Necromancer Will setting passed through (params=[" + string.Join(",", ReadParameters(setting.parameters)) + "]).");
				return true;
			}
			recognized = true;
			__result = false;

			var worldHero = _handlerWorldHeroProperty.DeclaringType.IsInstanceOfType(__instance) ? _handlerWorldHeroProperty.GetValue(__instance) : null;
			var logicHero = worldHero == null ? null : _worldHeroLogicHeroProperty.GetValue(worldHero);
			var dataHero = ResolveDataHero(logicHero);
			var title = string.Equals(mode, ExecuteMode, StringComparison.Ordinal) ? "Execute" : "Ransom";
			if (dataHero == null)
			{
				_log?.LogError("HoMM3 Dungeon Captives " + title + " refused: casting hero unresolved (worldHero " + (worldHero == null ? "null" : "set")
					+ ", logicHero " + (logicHero == null ? "null" : "set") + ", handler " + (__instance?.GetType().FullName ?? "null") + ").");
				return false;
			}
			if (!TryReadState(logicHero, dataHero, out var state, out var readFail))
			{
				_log?.LogError("HoMM3 Dungeon Captives " + title + " refused: captives state unreadable (" + readFail + ").");
				return false;
			}
			if (_loggedCasts++ < 40)
				_log?.LogInfo("HoMM3 Dungeon Captives spell cast: " + title + " level=" + level + " hero=" + DescribeHero(dataHero)
					+ " held strength=" + state.Strength + " squads=" + state.Squads + " tierBuff=" + state.Tier + ".");
			if (state.IsEmpty)
			{
				_log?.LogInfo("HoMM3 Dungeon Captives " + title + " refused: hero " + DescribeHero(dataHero) + " holds no captives.");
				return false;
			}

			var strength = state.Strength;
			if (string.Equals(mode, ExecuteMode, StringComparison.Ordinal))
			{
				var xp = ComputeExecuteXp(strength, level);
				var mana = HasSubSkill(dataHero, InterrogationSubSkillSid) ? ComputeInterrogationMana(xp) : 0;
				var expComponent = _expComponentProperty.GetValue(logicHero);
				if (expComponent == null)
				{
					_log?.LogError("HoMM3 Dungeon Captives Execute refused: native exp component missing; captives kept.");
					return false;
				}
				if (!TryWriteState(logicHero, dataHero, 0, 0, out _, out var clearFail))
				{
					_log?.LogError("HoMM3 Dungeon Captives Execute refused: clearing captives failed (" + clearFail + "); no XP granted.");
					return false;
				}
				var levelBefore = dataHero.currentLevel;
				var expBefore = dataHero.currentExp;
				var manaBefore = dataHero.mana;
				_expAddMethod.Invoke(expComponent, new object[] { xp, true });
				if (mana > 0)
					dataHero.mana += mana;
				__result = true;
				_log?.LogInfo("HoMM3 Dungeon Captives Execute payout: hero=" + DescribeHero(dataHero) + " level=" + level + " strength=" + strength
					+ " squads=" + state.Squads + " xp=+" + xp + " (native AddExp, exp bonus applies) exp " + expBefore + "->" + dataHero.currentExp
					+ " heroLevel " + levelBefore + "->" + dataHero.currentLevel + " interrogationMana=+" + mana + " mana " + manaBefore + "->" + dataHero.mana
					+ "; captives emptied, tier buff removed.");
				Homm3DungeonCaptivesHud.NotifyStateChanged("execute");
				return false;
			}

			var gold = ComputeRansomGold(strength, level, HasSubSkill(dataHero, SlaveMarketsSubSkillSid));
			if (!Homm3CustomFactionLawRuntime.TryResolveDataSideFromLogicHeroExplained(logicHero, out var dataSide, out var sideFail))
			{
				_log?.LogError("HoMM3 Dungeon Captives Ransom refused: hero side unresolved (" + sideFail + "); captives kept.");
				return false;
			}
			if (!Homm3RewardEconomyNativeAdapter.TryResolveGoldResourceFromSide(dataSide, out var goldResource, out var goldBefore, out var goldFail))
			{
				_log?.LogError("HoMM3 Dungeon Captives Ransom refused: gold resource unresolved (" + goldFail + "); captives kept.");
				return false;
			}
			if (!TryWriteState(logicHero, dataHero, 0, 0, out _, out var ransomClearFail))
			{
				_log?.LogError("HoMM3 Dungeon Captives Ransom refused: clearing captives failed (" + ransomClearFail + "); no gold granted.");
				return false;
			}
			if (!Homm3RewardEconomyNativeAdapter.TryAddResourceValue(goldResource, gold, out var addFail))
			{
				_log?.LogError("HoMM3 Dungeon Captives Ransom: captives emptied but gold add failed (" + addFail + ").");
				return false;
			}
			__result = true;
			_log?.LogInfo("HoMM3 Dungeon Captives Ransom payout: hero=" + DescribeHero(dataHero) + " level=" + level + " strength=" + strength
					+ " squads=" + state.Squads + " gold=+" + gold + " (before " + goldBefore.Value + ")"
					+ (HasSubSkill(dataHero, SlaveMarketsSubSkillSid) ? " slaveMarkets=x1.25" : "") + "; captives emptied, tier buff removed.");
			Homm3DungeonCaptivesHud.NotifyStateChanged("ransom");
			return false;
		}
		catch (Exception ex)
		{
			if (recognized)
			{
				__result = false;
				_log?.LogError("HoMM3 Dungeon Captives spell failed closed; native handler suppressed: " + ex.GetBaseException().Message);
				return false;
			}
			LogSkip("spell inspection failed; native handler remains responsible: " + ex.GetBaseException().Message);
			return true;
		}
	}

	/// <summary>True for a well-formed Captives setting; <paramref name="malformed"/> is set when the first parameter
	/// names a Captives mode but the row is unusable (so the native Necromancer Will handler must not run it either).</summary>
	private static bool TryReadCaptivesSpell(MagicSetting setting, out string mode, out int level, out string malformed)
	{
		mode = null;
		level = 0;
		malformed = null;
		if (setting == null || !string.Equals(setting.mechType, NativeNecromancyMechType, StringComparison.Ordinal))
			return false;
		var parameters = ReadParameters(setting.parameters);
		if (parameters.Count < 1)
			return false;
		if (!string.Equals(parameters[0], ExecuteMode, StringComparison.Ordinal) && !string.Equals(parameters[0], RansomMode, StringComparison.Ordinal))
			return false;
		if (parameters.Count < 2 || !int.TryParse(parameters[1], out level) || level < 1 || level > 3)
		{
			level = 0;
			malformed = "params=[" + string.Join(",", parameters) + "], expected [mode, 1..3]";
			return false;
		}
		mode = parameters[0];
		return true;
	}

	internal static int ComputeExecuteXp(long strength, int level)
	{
		var index = Math.Max(1, Math.Min(3, level)) - 1;
		return (int)Math.Min(int.MaxValue, Math.Round(strength * ExecuteXpPerStrength[index]));
	}

	internal static int ComputeInterrogationMana(int xp)
	{
		return (int)Math.Round(xp * InterrogationManaPerXp);
	}

	internal static int ComputeRansomGold(long strength, int level, bool slaveMarkets)
	{
		var index = Math.Max(1, Math.Min(3, level)) - 1;
		var gold = strength * RansomGoldPerStrength[index] * (slaveMarkets ? SlaveMarketsGoldMultiplier : 1.0);
		return (int)Math.Min(int.MaxValue, Math.Round(gold));
	}

	internal static int ComputeTier(long strength, bool dungeonCells)
	{
		var effective = strength * (dungeonCells ? DungeonCellsTierStrengthMultiplier : 1.0);
		var tier = 0;
		for (var i = 0; i < TierThresholds.Length; i++)
		{
			if (effective >= TierThresholds[i])
				tier = i + 1;
		}
		return tier;
	}

	// ---------------------------------------------------------------- buff-backed state

	/// <summary>Reconstructs the captives state from the hero's native buffs (save/load safe).</summary>
	internal static bool TryReadState(object logicHero, DataHero dataHero, out CaptivesState state, out string failReason)
	{
		state = default;
		var manager = ResolveBuffManager(logicHero, out failReason);
		if (manager == null)
			return false;
		var units = 0;
		for (var bit = 0; bit < StrengthBitCount; bit++)
		{
			if (HasBuff(manager, StrengthBitBuffPrefix + bit))
				units |= 1 << bit;
		}
		var squads = 0;
		for (var bit = 0; bit < SquadBitCount; bit++)
		{
			if (HasBuff(manager, SquadBitBuffPrefix + bit))
				squads |= 1 << bit;
		}
		var tier = 0;
		for (var t = 1; t <= TierThresholds.Length; t++)
		{
			if (HasBuff(manager, TierBuffPrefix + t))
				tier = t;
		}
		state = new CaptivesState(units, squads, tier);
		failReason = null;
		return true;
	}

	/// <summary>Writes units/squads as marker buffs and keeps exactly one tier buff for the derived tier.</summary>
	private static bool TryWriteState(object logicHero, DataHero dataHero, int units, int squads, out CaptivesState written, out string failReason)
	{
		written = default;
		var manager = ResolveBuffManager(logicHero, out failReason);
		if (manager == null)
			return false;
		units = Math.Max(0, Math.Min(MaxStrengthUnits, units));
		squads = units == 0 ? 0 : Math.Max(0, Math.Min(MaxSquads, squads));
		var tier = units == 0 ? 0 : ComputeTier((long)units * StrengthUnit, HasSubSkill(dataHero, DungeonCellsSubSkillSid));
		var failures = new List<string>();
		for (var bit = 0; bit < StrengthBitCount; bit++)
			SetBuff(manager, StrengthBitBuffPrefix + bit, (units & (1 << bit)) != 0, failures);
		for (var bit = 0; bit < SquadBitCount; bit++)
			SetBuff(manager, SquadBitBuffPrefix + bit, (squads & (1 << bit)) != 0, failures);
		// Tier 0 is the visible bonus-less "captives held" buff below the first threshold.
		for (var t = 0; t <= TierThresholds.Length; t++)
			SetBuff(manager, TierBuffPrefix + t, t == tier && units > 0, failures);
		written = new CaptivesState(units, squads, tier);
		if (failures.Count == 0)
			return true;
		failReason = string.Join("; ", failures);
		return false;
	}

	private static object ResolveBuffManager(object logicHero, out string failReason)
	{
		failReason = null;
		if (logicHero == null || !_buffManagerProperty.DeclaringType.IsInstanceOfType(logicHero))
		{
			failReason = "logic hero missing or not Hex.Session.Logic.Hero";
			return null;
		}
		var manager = _buffManagerProperty.GetValue(logicHero);
		if (manager == null)
			failReason = "hero buff manager is null";
		return manager;
	}

	private static bool HasBuff(object manager, string sid)
	{
		return _buffGetMethod.Invoke(manager, new object[] { sid }) != null;
	}

	private static void SetBuff(object manager, string sid, bool wanted, List<string> failures)
	{
		try
		{
			var present = HasBuff(manager, sid);
			if (present == wanted)
				return;
			if (wanted)
			{
				var durations = new Il2CppReferenceArray<BuffDuration>(1);
				durations[0] = new BuffDuration(EBuffDurationType.Infinite, -1);
				_buffAddMethod.Invoke(manager, new object[] { sid, durations });
			}
			else
			{
				// Native Remove only drops dispellable configs: the Captives rows are isDispellable=true.
				_buffRemoveMethod.Invoke(manager, new object[] { sid });
			}
			if (HasBuff(manager, sid) != wanted)
				failures.Add(sid + (wanted ? " add did not stick (buff config missing from Core?)" : " remove did not stick (config not dispellable?)"));
		}
		catch (Exception ex)
		{
			failures.Add(sid + " " + (wanted ? "add" : "remove") + " threw " + ex.GetBaseException().Message);
		}
	}

	// ---------------------------------------------------------------- UI snapshot

	/// <summary>Live numbers for the hero skill meter and the buff tooltip, from the buff-backed state and the hero's real skills.</summary>
	internal static Homm3DungeonCaptivesUi.Snapshot BuildUiSnapshot(DataHero dataHero, CaptivesState state)
	{
		var rank = Homm3DungeonDraconicDominionHook.ResolveFactionSkillRank(dataHero);
		var cells = HasSubSkill(dataHero, DungeonCellsSubSkillSid);
		var interrogation = HasSubSkill(dataHero, InterrogationSubSkillSid);
		var slaveMarkets = HasSubSkill(dataHero, SlaveMarketsSubSkillSid);
		var effective = (long)Math.Round(state.Strength * (cells ? DungeonCellsTierStrengthMultiplier : 1.0));
		var tier = state.IsEmpty ? 0 : ComputeTier(state.Strength, cells);
		var next = tier >= TierThresholds.Length ? 0 : TierThresholds[tier];
		// Cumulative toward the next tier, so the meter fill equals the "effective / next" hover numbers.
		var progress = next == 0 ? 1f : Mathf.Clamp01((float)effective / next);
		var xp = rank > 0 ? ComputeExecuteXp(state.Strength, rank) : 0;
		return new Homm3DungeonCaptivesUi.Snapshot
		{
			Squads = state.Squads,
			Strength = state.Strength,
			EffectiveStrength = effective,
			Tier = tier,
			NextThreshold = next,
			Progress = progress,
			ExecuteXp = xp,
			InterrogationMana = rank > 0 && interrogation ? ComputeInterrogationMana(xp) : 0,
			RansomGold = rank > 0 ? ComputeRansomGold(state.Strength, rank, slaveMarkets) : 0,
			Rank = rank,
			DungeonCells = cells,
			Interrogation = interrogation,
			SlaveMarkets = slaveMarkets,
		};
	}

	/// <summary>Reads the state of a Logic.Hero and builds the UI snapshot; false (with a reason) when unreadable.</summary>
	internal static bool TryBuildUiSnapshot(object logicHero, out DataHero dataHero, out Homm3DungeonCaptivesUi.Snapshot snapshot, out string failReason)
	{
		snapshot = null;
		dataHero = null;
		if (!_registered)
		{
			failReason = "Captives runtime not registered";
			return false;
		}
		dataHero = ResolveDataHero(logicHero);
		if (dataHero == null)
		{
			failReason = "Data.Hero unresolved from logic hero";
			return false;
		}
		if (!TryReadState(logicHero, dataHero, out var state, out failReason))
			return false;
		snapshot = BuildUiSnapshot(dataHero, state);
		return true;
	}

	internal static bool IsLogicHero(object candidate)
	{
		return candidate != null && _buffManagerProperty != null && _buffManagerProperty.DeclaringType.IsInstanceOfType(candidate);
	}

	// ---------------------------------------------------------------- helpers

	internal static DataHero ResolveDataHero(object logicHero)
	{
		if (logicHero == null || !_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(logicHero))
			return null;
		return _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) as DataHero;
	}

	private static bool HasSubSkill(DataHero dataHero, string sid)
	{
		return dataHero != null && Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, sid);
	}

	private static string DescribeHero(DataHero dataHero)
	{
		if (dataHero == null)
			return "null";
		var id = ReadMember(dataHero, GameSymbols.CastleEliteStrategem.DataHeroIdMembers);
		var session = Homm3SessionIdentity.TryResolveSessionDataKey(out var sessionKey, out _) ? sessionKey.ToString("X") : "?";
		return (dataHero.configSid ?? "?") + "#" + (id?.ToString() ?? "?") + "@session" + session;
	}

	private static List<string> ReadParameters(object parameters)
	{
		var result = new List<string>();
		if (parameters is string[] managed)
		{
			result.AddRange(managed);
			return result;
		}
		if (parameters is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
				result.Add(item as string ?? item?.ToString());
		}
		return result;
	}

	/// <param name="declaredOnType">Only methods declared on <paramref name="type"/> itself. Required where live interop hides a
	/// base-class wrapper with the same generated name and signature (C# <c>new</c>), because reflection returns both.</param>
	private static MethodInfo ResolveRequiredNamedMethod(Type type, Type returnType, Type[] parameterTypes, GameSymbols.MethodSymbol symbol, bool instance, bool declaredOnType = false)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in symbol.NameHints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var matches = new List<MethodInfo>();
			foreach (var method in type.GetMethods(flags))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal) || method.IsStatic == instance)
					continue;
				if (declaredOnType && method.DeclaringType != type)
					continue;
				if (returnType != null && method.ReturnType != returnType)
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != parameterTypes.Length)
					continue;
				var exact = true;
				for (var i = 0; i < parameters.Length; i++)
				{
					if (parameters[i].ParameterType != parameterTypes[i])
					{
						exact = false;
						break;
					}
				}
				if (exact && !matches.Contains(method))
					matches.Add(method);
			}
			if (matches.Count == 1)
				return matches[0];
			if (matches.Count > 1)
			{
				var owners = new List<string>();
				foreach (var match in matches)
					owners.Add(match.DeclaringType?.FullName ?? "?");
				throw new AmbiguousMatchException(symbol.Id + " matched " + matches.Count + " methods named " + name + " on " + type.FullName
					+ " (declared on " + string.Join(", ", owners) + ")");
			}
		}
		throw new MissingMethodException(symbol.Id + " exact method not found on " + (type?.FullName ?? "null") + (declaredOnType ? " (declared on the type itself)" : ""));
	}

	private static PropertyInfo ResolveRequiredProperty(Type type, string name, string symbolId)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var property = type?.GetProperty(name, flags);
		if (property == null || property.GetIndexParameters().Length != 0 || property.GetGetMethod(true) == null)
			throw new MissingMemberException(symbolId + " property " + name + " not found on " + (type?.FullName ?? "null"));
		return property;
	}

	private static PropertyInfo ResolveRequiredTypedProperty(Type type, string name, Type propertyType, string symbolId)
	{
		var property = ResolveRequiredProperty(type, name, symbolId);
		if (property.PropertyType != propertyType)
			throw new MissingMemberException(symbolId + " property " + name + " has type " + property.PropertyType.FullName + ", expected " + propertyType.FullName);
		return property;
	}

	private static MemberInfo ResolveRequiredMember(Type type, string[] names, string symbolId)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var property = type.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0 && property.GetGetMethod(true) != null)
				return property;
			var field = type.GetField(name, flags);
			if (field != null)
				return field;
		}
		throw new MissingMemberException(symbolId + " member not found on " + type.FullName);
	}

	private static MemberInfo ResolveRequiredTypedMember(Type type, Type valueType, string[] names, string symbolId)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var property = type.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0 && property.GetGetMethod(true) != null && property.PropertyType == valueType)
				return property;
			var field = type.GetField(name, flags);
			if (field != null && field.FieldType == valueType)
				return field;
			var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null && method.ReturnType == valueType)
				return method;
		}
		throw new MissingMemberException(symbolId + " " + valueType.FullName + " member not found on " + type.FullName);
	}

	private static Type MemberValueType(MemberInfo member)
	{
		return member switch
		{
			PropertyInfo property => property.PropertyType,
			FieldInfo field => field.FieldType,
			MethodInfo method => method.ReturnType,
			_ => throw new MissingMemberException("unsupported member " + member),
		};
	}

	private static Type ResolveRequiredTypeByHint(Assembly assembly, string[] hints, string symbolId)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var type = assembly?.GetType(hint);
			if (type != null)
				return type;
		}
		throw new TypeLoadException(symbolId + " type not found from hints [" + string.Join(",", hints ?? Array.Empty<string>()) + "]");
	}

	private static object ReadResolvedMember(object instance, MemberInfo member)
	{
		if (instance == null || member == null)
			return null;
		return member switch
		{
			PropertyInfo property => property.GetValue(instance, null),
			FieldInfo field => field.GetValue(instance),
			MethodInfo method => method.Invoke(instance, Array.Empty<object>()),
			_ => null,
		};
	}

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var cur = type; cur != null && cur != typeof(object); cur = cur.BaseType)
			{
				var property = cur.GetProperty(name, flags | BindingFlags.DeclaredOnly);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(obj);
				var field = cur.GetField(name, flags | BindingFlags.DeclaredOnly);
				if (field != null)
					return field.GetValue(obj);
				var method = cur.GetMethod(name, flags | BindingFlags.DeclaredOnly, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void))
					return method.Invoke(obj, null);
			}
		}
		return null;
	}

	private static void Patch(Harmony harmony, MethodInfo target, string prefixName, string postfixName)
	{
		const BindingFlags flags = BindingFlags.Static | BindingFlags.NonPublic;
		var prefix = prefixName == null ? null : typeof(Homm3DungeonCaptivesRuntime).GetMethod(prefixName, flags);
		var postfix = postfixName == null ? null : typeof(Homm3DungeonCaptivesRuntime).GetMethod(postfixName, flags);
		if (prefix != null && !GameMember.IsHarmonyPatchCompatible(target, prefix, out var prefixReason))
			throw new MissingMethodException("prefix incompatible for " + FormatMethod(target) + ": " + prefixReason);
		if (postfix != null && !GameMember.IsHarmonyPatchCompatible(target, postfix, out var postfixReason))
			throw new MissingMethodException("postfix incompatible for " + FormatMethod(target) + ": " + postfixReason);
		harmony.Patch(target,
			prefix: prefix == null ? null : new HarmonyMethod(prefix),
			postfix: postfix == null ? null : new HarmonyMethod(postfix));
	}

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "null" : method.DeclaringType?.FullName + "." + method.Name;
	}

	private static void LogEscapeClick(string message)
	{
		if (_loggedEscapeClicks++ < 40)
			_log?.LogInfo("HoMM3 Dungeon Captives capture: " + message);
	}

	private static void LogSkip(string message)
	{
		if (_loggedSkips++ < 40)
			_log?.LogWarning("HoMM3 Dungeon Captives: " + message);
	}
}
