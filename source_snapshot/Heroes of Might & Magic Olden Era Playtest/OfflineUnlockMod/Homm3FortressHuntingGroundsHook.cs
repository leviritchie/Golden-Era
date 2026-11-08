using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Hex.Session.Data;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using DataHero = Hex.Session.Data.Hero;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Fortress faction skill "Hunting Grounds" (skill_faction_homm3_fortress), replacing Swamp Tactics.
///
/// Trophies: +1 per battle this hero wins (any opponent; a lost siege or a retreat is a loss, so it never counts).
/// The cap is 8/7/6 at Basic/Advanced/Expert. Reaching the cap restocks, once, every weekly event bank
/// (Core visitorsResetType OnStartWeek) this hero visited so far this week, by calling that bank's own native
/// OnStartWeek. The meter then stays full, so a hero gets at most one restock per week.
///
/// State lives only in native hero map buffs (saved with the hero): exactly one visible buff
/// homm3_fortress_trophies_{level}_{n}. It is added with duration UntilNextWeek, so the native buff system
/// empties the meter at every week start. A buff at the cap means this week's restock is used.
/// The creeping enemy Initiative/Speed penalty is carried by that buff's Core bonuses
/// (unitStat, receiverAllegiance enemy); this hook never edits battle stats.
///
/// Visited-bank records are in memory only (keyed by native pointers) and are cleared at the native week turn.
/// After a mid-week reload, banks visited before the reload are not restocked (documented gap).
/// Creature dwellings are excluded: they have no visitors list and use the weekly growth model
/// (unitsData weeklyIncrement / random_hires amounts), so "restocking" them would mint extra creatures.
///
/// Owners: battle wins come from the shared exact battle-result prefix
/// (Homm3RuntimeMechanicHooks.PrefixBattleResultCleanup), deduped per battle. Visits and the week turn
/// bind GameSymbols.FortressHuntingGrounds. Every surface resolves before anything is patched (fail closed, logged).
/// </summary>
internal static class Homm3FortressHuntingGroundsHook
{
	internal const string SkillSid = "skill_faction_homm3_fortress";
	internal const string TrophyBuffPrefix = "homm3_fortress_trophies_";
	private const string WeeklyResetType = "OnStartWeek";
	private const string LogPrefix = "HoMM3 Fortress Hunting Grounds: ";

	/// <summary>Per skill level (index 1..3). Must match make_fortress_hunting_grounds_* in apply_release_core_overlay.py.</summary>
	internal static readonly int[] CapByLevel = { 0, 8, 7, 6 };

	private sealed class TrophyState
	{
		internal int Level;
		internal int Count;
		internal string Sid;
	}

	private static bool _registered;
	private static ManualLogSource _log;
	private static PropertyInfo _buffManagerProperty;
	private static MethodInfo _buffAddMethod;
	private static MethodInfo _buffRemoveMethod;
	private static MethodInfo _buffGetMethod;
	private static MethodInfo _bankOnStartWeek;
	private static IntPtr _eventBankClass;
	private static bool _refreshing;
	private static int _loggedSkips;
	private static int _loggedBattleLines;
	private static int _loggedMeterLines;
	private static readonly Dictionary<IntPtr, string> _meterLastLog = new();
	private static int _weekTurnFrame = -1;

	// data-hero native pointer -> (bank logic native pointer -> bank logic wrapper)
	private static readonly Dictionary<IntPtr, Dictionary<IntPtr, object>> _visitedThisWeek = new();
	private static readonly HashSet<int> _countedBattles = new();

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new ArgumentNullException(nameof(harmony));
		_log = log;

		// Resolve every surface before patching anything, so a miss leaves no partial feature behind.
		var bankType = GameMember.FindType(GameSymbols.FortressHuntingGrounds.EventBankLogicTypeId, GameSymbols.FortressHuntingGrounds.EventBankLogicTypeHint);
		if (bankType == null)
			throw new TypeLoadException("Fortress Hunting Grounds: missing event-bank logic type (FortressHuntingGrounds.EventBankLogicTypeHint).");
		if (!HasReadableMember(bankType, GameSymbols.FortressHuntingGrounds.EventBankLogicBankMembers, typeof(ObjEventBank)))
			throw new MissingMemberException(bankType.FullName, "event-bank data member (FortressHuntingGrounds.EventBankLogicBankMembers)");
		if (!HasReadableMember(bankType, GameSymbols.FortressHuntingGrounds.EventBankLogicConfigMembers, typeof(ObjEventBankConfig)))
			throw new MissingMemberException(bankType.FullName, "event-bank config member (FortressHuntingGrounds.EventBankLogicConfigMembers)");

		var interact = GameMember.FindMethodsByNames(bankType, 1, GameSymbols.FortressHuntingGrounds.EventBankHeroInteract.Id, GameSymbols.FortressHuntingGrounds.EventBankHeroInteract.NameHints);
		if (interact.Length != 1 || interact[0].ReturnType != typeof(void) || interact[0].IsStatic
		    || !typeof(Il2CppObjectBase).IsAssignableFrom(interact[0].GetParameters()[0].ParameterType))
			throw new MissingMethodException(bankType.FullName, "event-bank hero interact: matched " + interact.Length);
		var weekly = GameMember.FindMethodsByNames(bankType, 0, GameSymbols.FortressHuntingGrounds.EventBankOnStartWeek.Id, GameSymbols.FortressHuntingGrounds.EventBankOnStartWeek.NameHints);
		if (weekly.Length != 1 || weekly[0].ReturnType != typeof(void) || weekly[0].IsStatic || weekly[0].DeclaringType != bankType)
			throw new MissingMethodException(bankType.FullName, "event-bank OnStartWeek override: matched " + weekly.Length);
		_bankOnStartWeek = weekly[0];

		var logicHeroType = typeof(LogicHero);
		_buffManagerProperty = ResolveRequiredProperty(logicHeroType, GameSymbols.FortressHuntingGrounds.LogicHeroBuffManagerMembers[0], "homm3.fortress.huntingGrounds.logicHero.buffManager");
		var managerType = _buffManagerProperty.PropertyType;
		_buffAddMethod = ResolveRequiredNamedMethod(managerType, typeof(void), new[] { typeof(string), typeof(Il2CppReferenceArray<BuffDuration>) }, GameSymbols.FortressHuntingGrounds.BuffManagerAdd);
		_buffRemoveMethod = ResolveRequiredNamedMethod(managerType, typeof(void), new[] { typeof(string) }, GameSymbols.FortressHuntingGrounds.BuffManagerRemove);
		_buffGetMethod = ResolveRequiredNamedMethod(managerType, null, new[] { typeof(string) }, GameSymbols.FortressHuntingGrounds.BuffManagerGet);
		if (!string.Equals(_buffGetMethod.ReturnType.FullName, "Hex.Session.Logic.Buff", StringComparison.Ordinal))
			throw new MissingMethodException("homm3.fortress.huntingGrounds.buffManager.get returns " + _buffGetMethod.ReturnType.FullName + ", expected Hex.Session.Logic.Buff");

		_eventBankClass = NativeClassOf(bankType);
		if (_eventBankClass == IntPtr.Zero)
			throw new TypeLoadException("Fortress Hunting Grounds: native class pointer unresolved for the fold guard.");

		// Battle wins: the shared exact battle-result prefix calls ObserveBeforeBattleResult.
		if (!Homm3RuntimeMechanicHooks.TryRegisterSharedBattleResult(harmony, log))
			throw new MissingMethodException("Fortress Hunting Grounds: shared battle-result hook unavailable (no trophies without it).");

		harmony.Patch(interact[0], prefix: new HarmonyMethod(typeof(Homm3FortressHuntingGroundsHook), nameof(PrefixBankInteract)));
		harmony.Patch(_bankOnStartWeek, prefix: new HarmonyMethod(typeof(Homm3FortressHuntingGroundsHook), nameof(PrefixBankOnStartWeek)));
		_registered = true;
		log?.LogInfo(LogPrefix + "registered: visit prefix " + interact[0].Name + ", week-turn prefix " + _bankOnStartWeek.Name
			+ " on " + bankType.Name + ", battle wins via the shared battle-result prefix, buffs "
			+ _buffAddMethod.Name + "/" + _buffRemoveMethod.Name + "/" + _buffGetMethod.Name
			+ ". Caps 8/7/6; penalty carried by Core trophy buffs. Proof tier: build; runtime unproven.");
		Homm3FortressHuntingGroundsMeter.TryRegister(harmony, log); // HUD only (hero-portrait meter); reads state via TryReadMeterState
	}

	// ---------------------------------------------------------------- visits / week turn

	private static void PrefixBankInteract(object __instance, object __0)
	{
		try
		{
			if (!IsNativeInstanceOf(__instance, _eventBankClass))
				return;
			var config = ReadMember(__instance, GameSymbols.FortressHuntingGrounds.EventBankLogicConfigMembers) as ObjEventBankConfig;
			if (config == null || !string.Equals(config.visitorsResetType?.Trim(), WeeklyResetType, StringComparison.Ordinal))
				return;
			var logicHero = ReadMember(__0, GameSymbols.CastleEliteStrategem.WorldHeroLogicHeroProperty) as LogicHero;
			var dataHero = ResolveDataHero(logicHero);
			if (dataHero == null)
			{
				LogSkip("weekly bank visit: visiting hero unreadable");
				return;
			}
			// Recorded for every hero, so a hero who learns the skill mid-week still restocks earlier visits.
			if (!_visitedThisWeek.TryGetValue(dataHero.Pointer, out var banks))
				_visitedThisWeek[dataHero.Pointer] = banks = new Dictionary<IntPtr, object>();
			banks[((Il2CppObjectBase)__instance).Pointer] = __instance;
		}
		catch (Exception ex)
		{
			LogSkip("weekly bank visit prefix failed: " + ex.Message);
		}
	}

	private static void PrefixBankOnStartWeek(object __instance)
	{
		if (_refreshing || !IsNativeInstanceOf(__instance, _eventBankClass))
			return;
		// Native week turn calls OnStartWeek for every bank in one frame: clear the visit records once.
		var frame = Time.frameCount;
		if (frame == _weekTurnFrame)
			return;
		_weekTurnFrame = frame;
		var heroes = _visitedThisWeek.Count;
		_visitedThisWeek.Clear();
		lock (_countedBattles)
			_countedBattles.Clear();
		_log?.LogInfo(LogPrefix + "week turn: cleared weekly-site visit records for " + heroes + " hero(es); trophy buffs expire natively (UntilNextWeek).");
	}

	// ---------------------------------------------------------------- battle wins

	/// <summary>Called by Homm3RuntimeMechanicHooks.PrefixBattleResultCleanup before the native result applies (alreadyApplied=false).</summary>
	internal static void ObserveBeforeBattleResult(object battleLogic, bool showNotification)
	{
		if (!_registered || battleLogic == null)
			return;
		try
		{
			var key = BattleKey(battleLogic);
			lock (_countedBattles)
			{
				if (_countedBattles.Contains(key))
				{
					LogBattle("battle-result skipped: battle=" + key + " already counted");
					return;
				}
			}
			var transfer = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicTransferBattleFields) as TransferBattle;
			var started = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicStartedTransferBattleFields) as TransferBattle;
			var result = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicBattleResultInfoFields) as BattleResultInfo;
			if (transfer?.sides == null || result == null)
			{
				LogBattle("battle-result FAILED: battle=" + key + " transfer/result data unreadable (transfer="
					+ (transfer == null ? "null" : transfer.sides == null ? "no sides" : "ok") + ", result=" + (result == null ? "null" : "ok") + ")", warn: true);
				return;
			}
			var winnerIndex = result.winnerIndex;
			LogBattle("battle-result seen: battle=" + key + " winnerIndex=" + winnerIndex + " sides=" + transfer.sides.Length
				+ " startedSides=" + (started?.sides == null ? "none" : started.sides.Length.ToString()));
			if (winnerIndex < 0 || winnerIndex >= transfer.sides.Length)
			{
				LogBattle("battle-result skipped: battle=" + key + " no winner side (winnerIndex=" + winnerIndex + ")");
				return;
			}
			var startedWinner = started?.sides != null && winnerIndex < started.sides.Length ? started.sides[winnerIndex] : null;
			var transferWinner = transfer.sides[winnerIndex];
			var winner = startedWinner ?? transferWinner;
			var logicHero = startedWinner?.logicHero;
			var heroSource = "startedTransferBattle";
			if (logicHero == null)
			{
				logicHero = transferWinner?.logicHero;
				heroSource = "transferBattle";
			}
			var transferHeroSid = (winner?.hero ?? transferWinner?.hero)?.configId;
			if (logicHero == null)
			{
				LogBattle("battle-result hero unresolved: battle=" + key + " winnerIndex=" + winnerIndex + " transferHero="
					+ (string.IsNullOrEmpty(transferHeroSid) ? "none" : transferHeroSid) + " control=" + winner?.controlType
					+ " (no Logic.Hero on the winning TransferSide in startedTransferBattle or transferBattle); no trophy");
				return;
			}
			var dataHero = ResolveDataHero(logicHero);
			if (dataHero == null)
			{
				LogBattle("battle-result hero unresolved: battle=" + key + " Logic.Hero -> Data.Hero read null (TowerBottomlessKnowledge.LogicHeroDataHeroMembers) via "
					+ heroSource + ", transferHero=" + (string.IsNullOrEmpty(transferHeroSid) ? "none" : transferHeroSid) + "; no trophy", warn: true);
				return;
			}
			LogBattle("battle-result hero resolved: battle=" + key + " hero=" + dataHero.configSid + " via " + heroSource + ".logicHero side=" + winnerIndex
				+ " control=" + winner?.controlType + " transferHero=" + (string.IsNullOrEmpty(transferHeroSid) ? "none" : transferHeroSid));
			var level = ReadSkillLevel(dataHero, out var skillsSummary, out var skillFail);
			if (skillFail != null)
			{
				LogBattle("battle-result rank FAILED: battle=" + key + " hero=" + dataHero.configSid + ": " + skillFail + "; no trophy", warn: true);
				return;
			}
			LogBattle("battle-result rank: battle=" + key + " hero=" + dataHero.configSid + " huntingGroundsLevel=" + level + " skills=[" + skillsSummary + "]"
				+ (level <= 0 ? "; no Hunting Grounds, no trophy" : ""));
			if (level <= 0)
				return;
			lock (_countedBattles)
				_countedBattles.Add(key);
			var isLocal = winner != null && winner.controlType == TransferSide.EControlType.ME;
			AwardTrophy(logicHero, dataHero, level, showNotification && isLocal);
		}
		catch (Exception ex)
		{
			LogSkip("battle result observe failed: " + ex.Message);
		}
	}

	private static void AwardTrophy(LogicHero logicHero, DataHero dataHero, int level, bool notify)
	{
		var manager = ResolveBuffManager(logicHero);
		if (manager == null)
		{
			LogBattle("trophy buff FAILED: hero " + dataHero.configSid + " buff manager unreadable (FortressHuntingGrounds.LogicHeroBuffManagerMembers); trophy not recorded", warn: true);
			return;
		}
		var before = ReadState(manager);
		var cap = CapByLevel[level];
		var oldCount = before == null ? 0 : before.Count;
		var wasCapped = before != null && before.Count >= CapByLevel[before.Level];
		var newCount = Math.Min(oldCount + 1, cap);
		var newSid = BuffSid(level, newCount);
		if (before != null && before.Level == level && before.Count == newCount)
		{
			_log?.LogInfo(LogPrefix + "trophy buff unchanged: hero " + dataHero.configSid + " won a battle; trophies stay " + newCount + "/" + cap + " (full; restock already used this week).");
			return;
		}
		if (!SetSingleBuff(manager, before?.Sid, newSid, out var failReason))
		{
			_log?.LogWarning(LogPrefix + "trophy buff FAILED: hero " + dataHero.configSid + " " + newSid + " (" + failReason + "); state unchanged where possible.");
			return;
		}
		_log?.LogInfo(LogPrefix + "trophy buff applied: hero " + dataHero.configSid + " won a battle: trophies " + oldCount + " -> " + newCount + "/" + cap
			+ " (level " + level + ", buff " + newSid + " verified by Get" + (string.IsNullOrEmpty(before?.Sid) || before.Sid == newSid ? "" : ", removed " + before.Sid) + ").");
		Homm3FortressHuntingGroundsMeter.NotifyStateChanged("trophy");
		if (newCount >= cap && !wasCapped)
		{
			var refreshed = RestockVisitedSites(dataHero, out var visited);
			// No popup by design (user UI direction 2026-10-12): the trophy buff tooltip flips to "restock: used";
			// a native donor (BhNotification / BhFloatingUI) is follow-up work, never an IMGUI box.
			_log?.LogInfo(LogPrefix + "hero " + dataHero.configSid + " filled the meter: The hunting grounds are restocked: " + refreshed
				+ " site(s) refreshed (of " + visited + " weekly site(s) visited this week; local=" + notify + "). Restock used until the week ends.");
		}
	}

	private static int RestockVisitedSites(DataHero dataHero, out int visited)
	{
		visited = 0;
		if (!_visitedThisWeek.TryGetValue(dataHero.Pointer, out var banks))
			return 0;
		visited = banks.Count;
		var refreshed = 0;
		_refreshing = true;
		try
		{
			foreach (var bank in banks.Values)
			{
				try
				{
					if (!IsNativeInstanceOf(bank, _eventBankClass))
						continue;
					var data = ReadMember(bank, GameSymbols.FortressHuntingGrounds.EventBankLogicBankMembers) as ObjEventBank;
					var list = data?.visitorsList;
					if (list == null || list.Count == 0)
						continue; // never actually visited (declined window) or already fresh
					_bankOnStartWeek.Invoke(bank, Array.Empty<object>());
					if (data.visitorsList == null || data.visitorsList.Count == 0)
						refreshed++;
					else
						LogSkip("restock: bank " + data.idMapObject + " visitors not cleared by OnStartWeek");
				}
				catch (Exception ex)
				{
					LogSkip("restock of one bank failed: " + ex.GetBaseException().Message);
				}
			}
		}
		finally
		{
			_refreshing = false;
		}
		banks.Clear();
		return refreshed;
	}

	/// <summary>
	/// Read-only accessor for the hero-portrait meter (Homm3FortressHuntingGroundsMeter): current skill level (0 = no
	/// skill), trophies and the level the trophy buff was recorded at (0 = no buff). No gameplay effect.
	/// </summary>
	internal static bool TryReadMeterState(object logicHero, out int skillLevel, out int trophies, out int buffLevel, out string failReason)
	{
		skillLevel = trophies = buffLevel = 0;
		failReason = null;
		if (!_registered)
		{
			failReason = "Hunting Grounds hook not registered";
			return false;
		}
		if (logicHero is not LogicHero hero)
		{
			failReason = "selected hero is not a Logic.Hero";
			return false;
		}
		var dataHero = ResolveDataHero(hero);
		if (dataHero == null)
		{
			failReason = "Data.Hero unresolved";
			LogMeterTransition(hero.Pointer, "meter read FAILED: Logic.Hero -> Data.Hero read null");
			return false;
		}
		skillLevel = ReadSkillLevel(dataHero, out var skillsSummary, out var skillFail);
		if (skillFail != null)
		{
			failReason = "skill rank unreadable: " + skillFail;
			LogMeterTransition(dataHero.Pointer, "meter read FAILED: hero=" + dataHero.configSid + " " + failReason);
			return false;
		}
		if (skillLevel <= 0)
		{
			LogMeterTransition(dataHero.Pointer, "meter hidden: hero=" + dataHero.configSid + " has no Hunting Grounds (skills=[" + skillsSummary + "])");
			return true;
		}
		var manager = ResolveBuffManager(hero);
		if (manager == null)
		{
			failReason = "buff manager unreadable";
			LogMeterTransition(dataHero.Pointer, "meter read FAILED: hero=" + dataHero.configSid + " level=" + skillLevel + " buff manager unreadable");
			return false;
		}
		var state = ReadState(manager);
		trophies = state?.Count ?? 0;
		buffLevel = state?.Level ?? 0;
		LogMeterTransition(dataHero.Pointer, "meter state ready: hero=" + dataHero.configSid + " level=" + skillLevel + " trophies=" + trophies + "/" + CapByLevel[skillLevel]
			+ " buff=" + (state?.Sid ?? "none"));
		return true;
	}

	/// <summary>Logs a meter read only when its outcome for that hero changes (HUD refreshes are frequent).</summary>
	private static void LogMeterTransition(IntPtr heroKey, string message)
	{
		lock (_meterLastLog)
		{
			if (_meterLastLog.TryGetValue(heroKey, out var last) && string.Equals(last, message, StringComparison.Ordinal))
				return;
			_meterLastLog[heroKey] = message;
			if (_loggedMeterLines >= 200)
				return;
			_loggedMeterLines++;
		}
		_log?.LogInfo(LogPrefix + message + ".");
	}

	// ---------------------------------------------------------------- buff state

	internal static string BuffSid(int level, int count) => TrophyBuffPrefix + level + "_" + count;

	private static TrophyState ReadState(object manager)
	{
		TrophyState found = null;
		for (var level = 1; level <= 3; level++)
		{
			for (var n = 1; n <= CapByLevel[level]; n++)
			{
				var sid = BuffSid(level, n);
				if (_buffGetMethod.Invoke(manager, new object[] { sid }) == null)
					continue;
				if (found == null || n > found.Count)
					found = new TrophyState { Level = level, Count = n, Sid = sid };
			}
		}
		return found;
	}

	private static bool SetSingleBuff(object manager, string oldSid, string newSid, out string failReason)
	{
		failReason = null;
		try
		{
			var durations = new Il2CppReferenceArray<BuffDuration>(1);
			durations[0] = new BuffDuration(EBuffDurationType.UntilNextWeek, 0);
			_buffAddMethod.Invoke(manager, new object[] { newSid, durations });
			if (_buffGetMethod.Invoke(manager, new object[] { newSid }) == null)
			{
				failReason = newSid + " add did not stick (buff config missing from Core?)";
				return false;
			}
			if (!string.IsNullOrEmpty(oldSid) && !string.Equals(oldSid, newSid, StringComparison.Ordinal))
			{
				// Native Remove only drops dispellable configs: the trophy rows are isDispellable=true.
				_buffRemoveMethod.Invoke(manager, new object[] { oldSid });
				if (_buffGetMethod.Invoke(manager, new object[] { oldSid }) != null)
					failReason = oldSid + " remove did not stick (config not dispellable?)";
			}
			return failReason == null;
		}
		catch (Exception ex)
		{
			failReason = "buff manager threw " + ex.GetBaseException().Message;
			return false;
		}
	}

	private static object ResolveBuffManager(LogicHero logicHero)
	{
		if (logicHero == null)
			return null;
		try
		{
			return _buffManagerProperty.GetValue(logicHero);
		}
		catch
		{
			return null;
		}
	}

	// ---------------------------------------------------------------- shared

	private static DataHero ResolveDataHero(LogicHero logicHero)
	{
		return logicHero == null ? null : ReadMember(logicHero, GameSymbols.TowerBottomlessKnowledge.LogicHeroDataHeroMembers) as DataHero;
	}

	/// <summary>
	/// Hunting Grounds rank (0 = hero lacks the skill). Data.Hero.skills.list is an Il2CppSystem List&lt;HeroSkill&gt;, which is
	/// not a managed IEnumerable (Il2CppInterop: List&lt;T&gt; : Il2CppSystem.Object), so it is read by Count/indexer. A
	/// non-null <paramref name="failReason"/> means the rank could not be read (distinct from "skill absent").
	/// </summary>
	private static int ReadSkillLevel(DataHero dataHero, out string skillsSummary, out string failReason)
	{
		skillsSummary = "";
		failReason = null;
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		if (skills == null)
		{
			failReason = "Data.Hero.skills unreadable (DraconicDominion.DataHeroSkillsMembers)";
			return 0;
		}
		var listObject = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		if (listObject is not Il2CppSystem.Collections.Generic.List<HeroSkill> list)
		{
			failReason = "HeroSkills.list is " + (listObject?.GetType().FullName ?? "null") + ", expected Il2CppSystem List<Hex.Session.Data.HeroSkill>";
			return 0;
		}
		var parts = new List<string>();
		var level = 0;
		var found = false;
		var count = list.Count;
		for (var i = 0; i < count; i++)
		{
			var skill = list[i];
			if (skill == null)
				continue;
			var sid = (ReadMember(skill, GameSymbols.DraconicDominion.HeroSkillSidMembers) as string)?.Trim();
			var skillLevel = ReadMember(skill, GameSymbols.DraconicDominion.HeroSkillLevelMembers);
			parts.Add((sid ?? "?") + ":" + (skillLevel is int shown ? shown.ToString() : "?"));
			if (found || !string.Equals(sid, SkillSid, StringComparison.Ordinal))
				continue;
			found = true;
			if (skillLevel is int value)
				level = Math.Max(0, Math.Min(3, value));
			else
				failReason = SkillSid + " level unreadable (DraconicDominion.HeroSkillLevelMembers)";
		}
		skillsSummary = parts.Count == 0 ? "none" : string.Join(",", parts);
		return failReason == null ? level : 0;
	}

	private static int BattleKey(object battleLogic)
	{
		if (ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicIdFields) is int id && id != 0)
			return id;
		if (battleLogic is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero)
		{
			var ptr = il2Cpp.Pointer.ToInt64();
			return unchecked((int)(ptr ^ (ptr >> 32)));
		}
		return 0;
	}

	private static PropertyInfo ResolveRequiredProperty(Type type, string name, string symbolId)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var property = type?.GetProperty(name, flags);
		if (property == null || property.GetIndexParameters().Length != 0 || property.GetGetMethod(true) == null)
			throw new MissingMemberException(symbolId + " property " + name + " not found on " + (type?.FullName ?? "null"));
		return property;
	}

	private static MethodInfo ResolveRequiredNamedMethod(Type type, Type returnType, Type[] parameterTypes, GameSymbols.MethodSymbol symbol)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in symbol.NameHints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var matches = new List<MethodInfo>();
			foreach (var method in type.GetMethods(flags))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (returnType != null && method.ReturnType != returnType)
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != parameterTypes.Length)
					continue;
				var exact = true;
				for (var i = 0; i < parameters.Length; i++)
					exact &= parameters[i].ParameterType == parameterTypes[i];
				if (exact && !matches.Contains(method))
					matches.Add(method);
			}
			if (matches.Count == 1)
				return matches[0];
			if (matches.Count > 1)
				throw new AmbiguousMatchException(symbol.Id + " matched " + matches.Count + " methods named " + name + " on " + type.FullName);
		}
		throw new MissingMethodException(type.FullName, symbol.Id);
	}

	private static IntPtr NativeClassOf(Type managedType)
	{
		try
		{
			var store = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			RuntimeHelpers.RunClassConstructor(store.TypeHandle);
			var field = store.GetField("NativeClassPtr", BindingFlags.Public | BindingFlags.Static);
			return field?.GetValue(null) is IntPtr ptr ? ptr : IntPtr.Zero;
		}
		catch
		{
			return IntPtr.Zero;
		}
	}

	private static bool IsNativeInstanceOf(object value, IntPtr expectedClass)
	{
		if (value is not Il2CppObjectBase obj || expectedClass == IntPtr.Zero)
			return false;
		var ptr = obj.Pointer;
		if (ptr == IntPtr.Zero)
			return false;
		var actual = IL2CPP.il2cpp_object_get_class(ptr);
		return actual != IntPtr.Zero && IL2CPP.il2cpp_class_is_assignable_from(expectedClass, actual);
	}

	private static bool HasReadableMember(Type type, string[] names, Type expected)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			var prop = type.GetProperty(name, flags);
			if (prop?.GetMethod != null && prop.PropertyType == expected)
				return true;
			var field = type.GetField(name, flags);
			if (field != null && field.FieldType == expected)
				return true;
		}
		return false;
	}

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			try
			{
				var prop = type.GetProperty(name, flags);
				if (prop?.GetMethod != null && prop.GetIndexParameters().Length == 0)
					return prop.GetValue(obj);
			}
			catch { }
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(obj);
			}
			catch { }
			try
			{
				var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void))
					return method.Invoke(obj, Array.Empty<object>());
			}
			catch { }
		}
		return null;
	}

	/// <summary>Per-battle trace (a few lines per battle; capped so a long AI-heavy session cannot flood the log).</summary>
	private static void LogBattle(string message, bool warn = false)
	{
		if (_loggedBattleLines >= 400)
			return;
		_loggedBattleLines++;
		if (warn)
			_log?.LogWarning(LogPrefix + message + ".");
		else
			_log?.LogInfo(LogPrefix + message + ".");
	}

	private static void LogSkip(string message)
	{
		if (_loggedSkips >= 24)
			return;
		_loggedSkips++;
		_log?.LogInfo(LogPrefix + message + ".");
	}
}
