using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using BuffDuration = Hex.Session.Data.BuffDuration;
using DataHero = Hex.Session.Data.Hero;
using DataParty = Hex.Session.Data.DataParty;
using EListenerCallbackCall = Hex.Session.Logic.EListenerCallbackCall;
using PartyChangedType = Hex.Events.PartyChangedType;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3 Dungeon War Captives (skill_faction_homm3_dungeon; replaces the 2026-10-12 flee-capture Captives bank).
///
/// Captives: when a hero with the faction skill wins a battle, every enemy creature killed (started minus remaining
/// stacks on every other side, x UnitLogicConfig.squadValue) is summed; captives = floor(value x (1.15 with Dungeon
/// Cells) / <see cref="ValuePerCaptive"/>). Nothing happens at 0 captives.
///
/// Choice (one per battle):
///   Execute  hero gains ExecuteXpPerCaptive[rank] XP per captive through the native exp component AddExp (exp bonus and
///            level-up loop apply); Interrogation adds 1.5% of that XP as mana (rounded).
///   Ransom   RansomGoldPerCaptive[rank] gold per captive (Slave Markets +25%).
///   Eat      EatPercent[rank] of each own stack's losses this battle (floor), capped so the restored squad value never
///            exceeds the captives' value. Written into the winner TransferSide before the native result applies it.
///   Enslave  (Enslave Captives subskill) the captives join the hero's enslaved count: a hidden binary-weight buff set
///            saved with the hero; the day-start consumer pays EnslaveGoldPerDay[rank] per enslaved captive (Slave Markets
///            +25%) for as long as the hero exists. The visible bonus-less enslaved buff carries a live tooltip.
///   Recruit  (Recruit Captives subskill) RecruitPercent[rank] of each defeated creature type at its full native unitCost,
///            added to the hero's army (existing stacks merge; new types need a free slot of the 7).
///
/// Flow: the shared battle-result prefix (Homm3RuntimeMechanicHooks.PrefixBattleResultCleanup ->
/// <see cref="ObserveBeforeBattleResult"/>) builds the offer while the result still holds the battle's losses. A local
/// human's <see cref="Homm3DungeonWarCaptivesWindow"/> is queued to open ~0.6 s after the native result has been written,
/// so the army strip and hero panel show the post-battle state, and the choice pays into the live hero (Execute XP/mana
/// stick). Eat and Recruit then add units through the logic party's native AddUnits (merge into a same-sid stack or a free
/// slot of 7; fires the party-changed listeners). AI winners pick Eat when it restores anything, else Ransom, before the
/// result applies (Eat writes the winner TransferSide).
///
/// Legacy (Captives bank saves): a hero still holding the old strength bank is paid it once as Ransom at day start and
/// the old buffs are cleared; old Execute/Ransom spells left in a spellbook are suppressed (the native Necromancer Will
/// toggle must never run for them).
///
/// Proof tier: source + build. Runtime unproven: the post-result window timing, the logic-party AddUnits for Eat
/// and Recruit, the day-start payout and the window all need the Golden Era checklist in
/// docs/homm3_faction_plans/dungeon.md.
/// </summary>
internal static class Homm3DungeonCaptivesRuntime
{
	internal const string FactionSkillSid = "skill_faction_homm3_dungeon";
	internal const string InterrogationSubSkillSid = "sub_skill_faction_homm3_dungeon_draconic_diplomacy_2";
	internal const string EnslaveSubSkillSid = "sub_skill_faction_homm3_dungeon_draconic_diplomacy_3";
	internal const string RecruitSubSkillSid = "sub_skill_faction_homm3_dungeon_draconic_diplomacy_4";
	internal const string SlaveMarketsSubSkillSid = "sub_skill_faction_homm3_dungeon_draconic_diplomacy_5";
	internal const string DungeonCellsSubSkillSid = "sub_skill_faction_homm3_dungeon_draconic_diplomacy_6";

	internal const int ValuePerCaptive = 100;
	internal static readonly int[] ExecuteXpPerCaptive = { 6, 9, 12 };
	internal static readonly int[] RansomGoldPerCaptive = { 10, 15, 20 };
	internal static readonly double[] EnslaveGoldPerDay = { 1.0, 1.5, 2.0 };
	internal static readonly int[] EatPercent = { 20, 30, 40 };
	internal static readonly int[] RecruitPercent = { 10, 15, 20 };
	internal const double SlaveMarketsGoldMultiplier = 1.25;
	internal const double DungeonCellsCaptiveMultiplier = 1.15;
	internal const double InterrogationManaPerXp = 0.015; // 2026-11-15 user: 15% of the former 10%
	internal const int MaxArmySlots = 7;

	internal const string EnslavedBuffSid = "homm3_dungeon_captives_enslaved";
	internal const string EnslavedBitBuffPrefix = "homm3_dungeon_captives_enslaved_bit_";
	internal const int EnslavedBitCount = 20;
	internal const int MaxEnslaved = (1 << EnslavedBitCount) - 1;

	// Legacy Captives bank (pre War Captives saves): read once, paid as Ransom, cleared.
	private const string NativeNecromancyMechType = "change_use_necromancy";
	private const string LegacyExecuteMode = "homm3_dungeon_captives_execute";
	private const string LegacyRansomMode = "homm3_dungeon_captives_ransom";
	private const string LegacyTierBuffPrefix = "homm3_dungeon_captives_tier_";
	private const string LegacyStrengthBitBuffPrefix = "homm3_dungeon_captives_strength_bit_";
	private const string LegacySquadBitBuffPrefix = "homm3_dungeon_captives_squads_bit_";
	private const int LegacyStrengthBitCount = 20;
	private const int LegacySquadBitCount = 8;
	private const int LegacyTierCount = 5;
	private const int LegacyStrengthUnit = 100;

	private const string GoldResourceName = "gold";
	private const string LogPrefix = "HoMM3 Dungeon War Captives: ";

	internal enum Choice
	{
		Execute,
		Ransom,
		Eat,
		Enslave,
		Recruit,
	}

	internal sealed class UnitLine
	{
		internal string Sid;
		internal int Count;
		internal int SlotPos;
		internal int SquadValue;
		/// <summary>Native unitCost per creature (resource, amount); filled for Recruit lines.</summary>
		internal readonly List<(string Name, int Cost)> Cost = new();
	}

	internal sealed class Offer
	{
		internal int BattleKey;
		internal object LogicHero;
		internal DataHero DataHero;
		internal string HeroSid;
		internal int Rank;
		internal bool IsLocalHuman;
		internal long DefeatedValue;
		internal int Captives;
		internal bool Interrogation;
		internal bool HasEnslave;
		internal bool HasRecruit;
		internal bool SlaveMarkets;
		internal bool DungeonCells;
		internal int ExecuteXp;
		internal int ExecuteMana;
		internal int RansomGold;
		internal int EnslavedBefore;
		internal int EnslaveDailyGoldAfter;
		internal readonly List<UnitLine> Eat = new();
		internal int EatCreatures;
		internal readonly List<UnitLine> Recruit = new();
		internal int RecruitCreatures;
		internal readonly SortedDictionary<string, int> RecruitCost = new(StringComparer.Ordinal);
		internal string RecruitBlocked;
		/// <summary>True only for the AI's automatic pick, made before the native result applies (Eat writes the winner
		/// TransferSide). The human's window opens after the result, so its Eat/Recruit add units through the logic party.</summary>
		internal bool ArmyWritable;
		// law pass 2026-11-21 / 2026-11-25: the owning hero's Dungeon law levels, read once when the offer is built.
		internal int BlackMarketLevel;
		internal int CouriersLevel;
		internal int TaskmastersLevel;
		internal bool OverlordsDue;
		/// <summary>law pass 2026-11-25: Captive Couriers (#7) paid once per battle, whatever the fate (or fallback).</summary>
		internal bool CouriersPaid;
		/// <summary>law pass 2026-11-21: Overlord's Due (#30) second fate: half strength, Execute/Ransom/Eat only,
		/// never the fate in <see cref="Excluded"/>.</summary>
		internal bool SecondFate;
		internal Choice Excluded;
	}

	private static bool _registrationAttempted;
	private static bool _registered;
	private static bool _partyRegistered;
	private static bool _dayStartRegistered;
	private static ManualLogSource _log;
	private static PropertyInfo _handlerWorldHeroProperty;
	private static PropertyInfo _worldHeroLogicHeroProperty;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static Type _logicHeroType;
	private static PropertyInfo _expComponentProperty;
	private static MethodInfo _expAddMethod;
	private static PropertyInfo _buffManagerProperty;
	private static MethodInfo _buffAddMethod;
	private static MethodInfo _buffRemoveMethod;
	private static MethodInfo _buffGetMethod;
	private static MethodInfo _transferSideAddSpawnedUnit;
	private static MethodInfo _transferSideSortBySlot;
	private static PropertyInfo _logicHeroPartyProperty;
	private static MethodInfo _partyAddUnitsMethod;
	private static bool _arrangeRegistered;

	private static readonly object Gate = new();
	private static readonly HashSet<int> Resolved = new();
	private static int _loggedEvents;
	private static int _loggedSkips;

	// ---------------------------------------------------------------- registration

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registrationAttempted || harmony == null)
			return;
		_registrationAttempted = true;
		_log = log;
		var hexAssembly = typeof(TransferBattle).Assembly;

		// Core: hero bridge, exp component, buff manager, TransferSide unit add. Everything else needs it.
		Type worldHeroType = null;
		try
		{
			_logicHeroType = hexAssembly.GetType(GameSymbols.CastleEliteStrategem.LogicHeroTypeName)
			                 ?? throw new TypeLoadException("Missing Hex.Session.Logic.Hero");
			worldHeroType = ResolveRequiredTypeByHint(hexAssembly, GameSymbols.HomecomingBoatTravel.WorldHeroTypeHints, "homm3.dungeon.captives.worldHero");
			_worldHeroLogicHeroProperty = ResolveRequiredTypedProperty(worldHeroType, GameSymbols.CastleEliteStrategem.WorldHeroLogicHeroProperty, _logicHeroType, "homm3.dungeon.captives.worldHero.logicHero");
			_logicHeroDataHeroGetter = ResolveRequiredNamedMethod(_logicHeroType, typeof(DataHero), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter, instance: true);
			_expComponentProperty = ResolveRequiredProperty(_logicHeroType, GameSymbols.DungeonCaptives.LogicHeroExpComponentMembers[0], "homm3.dungeon.captives.logicHero.expComponent");
			_expAddMethod = ResolveRequiredNamedMethod(_expComponentProperty.PropertyType, typeof(void), new[] { typeof(int), typeof(bool) }, GameSymbols.DungeonCaptives.ExpComponentAddExp, instance: true);
			_buffManagerProperty = ResolveRequiredProperty(_logicHeroType, GameSymbols.DungeonCaptives.LogicHeroBuffManagerMembers[0], "homm3.dungeon.captives.logicHero.buffManager");
			var buffManagerType = _buffManagerProperty.PropertyType;
			_buffAddMethod = ResolveRequiredNamedMethod(buffManagerType, typeof(void), new[] { typeof(string), typeof(Il2CppReferenceArray<BuffDuration>) }, GameSymbols.DungeonCaptives.BuffManagerAdd, instance: true);
			_buffRemoveMethod = ResolveRequiredNamedMethod(buffManagerType, typeof(void), new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerRemove, instance: true);
			_buffGetMethod = ResolveRequiredNamedMethod(buffManagerType, null, new[] { typeof(string) }, GameSymbols.DungeonCaptives.BuffManagerGet, instance: true);
			if (!string.Equals(_buffGetMethod.ReturnType.FullName, "Hex.Session.Logic.Buff", StringComparison.Ordinal))
				throw new MissingMethodException("homm3.dungeon.captives.buffManager.get returns " + _buffGetMethod.ReturnType.FullName + ", expected Hex.Session.Logic.Buff");
			_transferSideAddSpawnedUnit = ResolveRequiredNamedMethod(typeof(TransferSide), typeof(void), new[] { typeof(TransferUnit), typeof(bool) }, GameSymbols.SkeletalNecromancy.TransferSideAddSpawnedUnit, instance: true);
			_transferSideSortBySlot = ResolveRequiredNamedMethod(typeof(TransferSide), typeof(void), Type.EmptyTypes, GameSymbols.SkeletalNecromancy.TransferSideSortBySlot, instance: true);
			if (!Homm3RuntimeMechanicHooks.TryRegisterSharedBattleResult(harmony, log))
				throw new InvalidOperationException("shared battle-result hook did not register");
			_registered = true;
			_log?.LogInfo(LogPrefix + "[core] registered: exp=" + FormatMethod(_expAddMethod) + ", buffs=" + FormatMethod(_buffAddMethod)
				+ ", transferSide add=" + _transferSideAddSpawnedUnit.Name + "/sort=" + _transferSideSortBySlot.Name + ", shared battle-result prefix.");
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + "[core] NOT registered (fail closed: no captives after battles): " + ex.GetBaseException().Message);
		}

		if (_registered)
		{
			// Party: the human's window opens after the native result, so Eat and Recruit add units through the logic party's
			// native AddUnits, which also fires the party-changed listeners (army strip refresh).
			try
			{
				_logicHeroPartyProperty = ResolveRequiredProperty(_logicHeroType, GameSymbols.DungeonCaptives.LogicHeroPartyMembers[0], "homm3.dungeon.captives.logicHero.party");
				_partyAddUnitsMethod = ResolveRequiredNamedMethod(_logicHeroPartyProperty.PropertyType, typeof(void),
					new[] { typeof(string), typeof(int), typeof(EListenerCallbackCall) }, GameSymbols.DungeonCaptives.LogicPartyAddUnits, instance: true);
				_partyRegistered = true;
				_log?.LogInfo(LogPrefix + "[party] registered: add units=" + FormatMethod(_partyAddUnitsMethod) + ".");
			}
			catch (Exception ex)
			{
				_log?.LogError(LogPrefix + "[party] NOT registered (Eat/Recruit unavailable on the choice window): " + ex.GetBaseException().Message);
			}

			// Recruit panel: the chosen army arrangement is written to the logic party's Data.Units (slot, stacks), new stacks
			// through the native AddUnitAtSlot, then the party listeners run once (army strip refresh).
			// The army write is the shared Homm3PartyArmyWriter (also used by Conflux Elemental Fusion).
			if (_partyRegistered)
			{
				if (Homm3PartyArmyWriter.TryResolve(_logicHeroType, out var writerFail))
				{
					_arrangeRegistered = true;
					_log?.LogInfo(LogPrefix + "[recruit panel] registered: " + Homm3PartyArmyWriter.Describe() + ".");
				}
				else
				{
					_log?.LogError(LogPrefix + "[recruit panel] NOT registered (Recruit unavailable on the choice window): " + writerFail);
				}
			}

			// Spells: suppress leftover Captives-bank Execute/Ransom rows before the native Necromancer Will toggle sees them.
			try
			{
				var handlerType = ResolveRequiredTypeByHint(hexAssembly, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicHandlerTypeHints, "homm3.dungeon.captives.necromancyHandler");
				var castMethod = ResolveRequiredNamedMethod(handlerType, typeof(bool), Type.EmptyTypes, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicCast, instance: true);
				_handlerWorldHeroProperty = ResolveRequiredTypedProperty(handlerType, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicWorldHeroProperty, worldHeroType, "homm3.dungeon.captives.necromancyHandler.worldHero");
				Patch(harmony, castMethod, nameof(PrefixNecromancyWorldMagicCast), null);
				_log?.LogInfo(LogPrefix + "[legacy spells] registered: retired Execute/Ransom rows are suppressed on " + FormatMethod(castMethod) + ".");
			}
			catch (Exception ex)
			{
				_log?.LogError(LogPrefix + "[legacy spells] NOT registered (a leftover Execute/Ransom spell would reach the native Necromancer Will toggle): " + ex.GetBaseException().Message);
			}

			if (Homm3SwashbucklerGoldHook.TryRegisterDayStartHeroConsumer("homm3.dungeon.warCaptives", OnDayStartHero, out var dayStartFailure))
				_dayStartRegistered = true;
			else
				_log?.LogError(LogPrefix + "[day start] NOT registered (no enslaved gold, no legacy bank payout): " + dayStartFailure);
			if (!Homm3SwashbucklerGoldHook.TryRegisterDayStartHeroForecast("homm3.dungeon.warCaptives", ForecastDayStartHero, out var forecastFailure))
				_log?.LogWarning(LogPrefix + "[income preview] enslaved gold not shown in the gold tooltip: " + forecastFailure);

			Homm3DungeonCaptivesBuffTooltip.TryRegister(harmony, log);
			// The choice window is modal through the Artificing picker's input gates (idempotent registration).
			Homm3TowerArtificingPickerInputBlock.TryRegister(harmony, hexAssembly, log);
		}

		var summary = LogPrefix + "registration summary: core=" + Stage(_registered) + " party=" + Stage(_partyRegistered)
			+ " dayStart=" + Stage(_dayStartRegistered) + " tooltip=" + Stage(Homm3DungeonCaptivesBuffTooltip.IsRegistered) + ". Proof tier: build; runtime unproven.";
		if (_registered && _partyRegistered && _dayStartRegistered && Homm3DungeonCaptivesBuffTooltip.IsRegistered)
			_log?.LogInfo(summary);
		else
			_log?.LogError(summary);
	}

	private static string Stage(bool ok) => ok ? "ok" : "FAILED";

	// Sides whose hero chose on the captives window this session (only the local human player gets the window):
	// their day-start enslaved gold is announced on the result banner.
	private static readonly HashSet<int> LocalSides = new();
	private static readonly List<string> DayStartLines = new();
	private static int _dayStartFrame = -1;
	private static long _dayStartTotal;

	private static void AnnounceDayStart(DataHero dataHero, int enslaved, int daily)
	{
		lock (LocalSides)
		{
			if (!LocalSides.Contains(dataHero.sideId))
				return;
		}
		var frame = UnityEngine.Time.frameCount;
		if (frame != _dayStartFrame)
		{
			_dayStartFrame = frame;
			DayStartLines.Clear();
		}
		var name = Homm3HeroDisplayNames.Resolve(dataHero.configSid) ?? dataHero.configSid;
		_dayStartTotal = (_dayStartFrame == frame && DayStartLines.Count > 0 ? _dayStartTotal : 0) + daily;
		DayStartLines.Add(name + ": " + enslaved + " enslaved captives, +" + daily.ToString("N0") + " Gold");
		var header = "War Captives income today: +" + _dayStartTotal.ToString("N0") + " Gold";
		Homm3DungeonWarCaptivesWindow.ShowBanner(header + "\n" + string.Join("\n", DayStartLines), DayStartLines.Count + 1);
	}

	/// <summary>
	/// The window's choice. The window opens after the native battle result has applied, so every choice pays straight
	/// into the live hero/army: Execute/Ransom/Enslave directly, Eat through the logic party's native AddUnits, Recruit by
	/// writing the recruit panel's army arrangement (<paramref name="board"/>; null recruits everything that fits).
	/// </summary>
	internal static bool Choose(Offer offer, Choice choice, out string failReason, RecruitBoard board = null)
	{
		failReason = null;
		if (offer == null)
		{
			failReason = "no offer";
			return false;
		}
		// The result write-back can replace the Data.Hero behind the logic hero; pay into the live one.
		var live = ResolveDataHero(offer.LogicHero);
		if (live != null)
			offer.DataHero = live;
		if (!IsChoiceAvailable(offer, choice, out failReason))
			return false;
		if (offer.DataHero != null)
			lock (LocalSides)
				LocalSides.Add(offer.DataHero.sideId);
		LogEvent("battle " + offer.BattleKey + ": " + choice + " chosen after the result applied.");
		switch (choice)
		{
			case Choice.Eat:
				ApplyEat(offer, (string sid, int count, int slot, out string how) => AddUnitsToParty(offer, sid, count, out how), null);
				break;
			case Choice.Recruit:
				if (board == null)
				{
					board = NewRecruitBoard(offer, out var boardFail);
					if (board == null)
					{
						failReason = boardFail;
						return false;
					}
					board.RecruitAll();
				}
				if (!ApplyRecruitBoard(offer, board, out failReason))
					return false;
				break;
			default:
				ApplyDirect(offer, choice);
				break;
		}
		// law pass 2026-11-25: Captive Couriers (#7)
		GrantCaptiveCouriers(offer);
		return true;
	}

	/// <summary>Why a choice cannot be taken right now (null when it can); the window greys the row with this text.</summary>
	internal static bool IsChoiceAvailable(Offer offer, Choice choice, out string reason)
	{
		reason = null;
		// law pass 2026-11-21: Overlord's Due (#30) second fate: Execute, Ransom or Eat, never the fate already taken.
		if (offer != null && offer.SecondFate)
		{
			if (!IsSecondFateChoice(choice))
			{
				reason = "Not offered as a second fate";
				return false;
			}
			if (choice == offer.Excluded)
			{
				reason = "Already chosen";
				return false;
			}
		}
		switch (choice)
		{
			case Choice.Eat:
				if (offer.EatCreatures <= 0)
					reason = "No losses to recover";
				else if (!offer.ArmyWritable && !_partyRegistered)
					reason = "Unavailable (see the log)";
				else if (!offer.ArmyWritable && !PartyFits(offer, offer.Eat))
					reason = "No free army slot";
				break;
			case Choice.Enslave:
				if (!offer.HasEnslave)
					reason = "Requires Enslave Captives";
				break;
			case Choice.Recruit:
				if (!offer.HasRecruit)
					reason = "Requires Recruit Captives";
				else if (offer.RecruitBlocked != null)
					reason = offer.RecruitBlocked;
				else if (offer.RecruitCreatures <= 0)
					reason = "Too few captives to recruit";
				else if (offer.ArmyWritable)
				{
					if (!PartyFits(offer, offer.Recruit))
						reason = "No free army slot";
					else if (!CanAfford(offer, offer.RecruitCost, out var missing))
						reason = "Not enough " + missing;
				}
				else if (!_arrangeRegistered)
					reason = "Unavailable (see the log)";
				else if (!AnyRecruitFits(offer))
					reason = "No free army slot";
				else if (!CanAffordOne(offer, out var missingOne))
					reason = "Not enough " + missingOne;
				break;
		}
		return reason == null;
	}

	// ---------------------------------------------------------------- law pass 2026-11-21: Overlord's Due (#30)

	internal static bool IsSecondFateChoice(Choice choice) => choice == Choice.Execute || choice == Choice.Ransom || choice == Choice.Eat;

	/// <summary>The fallback when a window choice is refused or the window fails: Ransom, or Execute when a second
	/// fate already excludes Ransom.</summary>
	internal static Choice FallbackChoice(Offer offer)
	{
		return offer != null && offer.SecondFate && offer.Excluded == Choice.Ransom ? Choice.Execute : Choice.Ransom;
	}

	/// <summary>
	/// The half-strength second offer after a first fate was applied, when the hero owns Overlord's Due. Half the
	/// captives, half the Experience/Mana/Gold, half of each Eat stack; Enslave and Recruit are never offered (they
	/// persist), and the fate already taken is excluded. False when the law is not owned or this is already the second.
	/// </summary>
	internal static bool TryBuildSecondFate(Offer first, Choice applied, out Offer second)
	{
		second = null;
		if (first == null || first.SecondFate || !first.OverlordsDue)
			return false;
		var o = new Offer
		{
			BattleKey = first.BattleKey,
			LogicHero = first.LogicHero,
			DataHero = first.DataHero,
			HeroSid = first.HeroSid,
			Rank = first.Rank,
			IsLocalHuman = first.IsLocalHuman,
			DefeatedValue = first.DefeatedValue,
			Captives = Math.Max(1, Homm3DungeonLawHooks.Half(first.Captives)),
			Interrogation = first.Interrogation,
			HasEnslave = false,
			HasRecruit = false,
			SlaveMarkets = first.SlaveMarkets,
			DungeonCells = first.DungeonCells,
			ExecuteXp = Homm3DungeonLawHooks.Half(first.ExecuteXp),
			ExecuteMana = Homm3DungeonLawHooks.Half(first.ExecuteMana),
			RansomGold = Homm3DungeonLawHooks.Half(first.RansomGold),
			EnslavedBefore = first.EnslavedBefore,
			EnslaveDailyGoldAfter = first.EnslaveDailyGoldAfter,
			RecruitBlocked = "Not offered as a second fate",
			ArmyWritable = first.ArmyWritable,
			BlackMarketLevel = first.BlackMarketLevel,
			CouriersLevel = first.CouriersLevel,
			TaskmastersLevel = first.TaskmastersLevel,
			OverlordsDue = first.OverlordsDue,
			CouriersPaid = true,
			SecondFate = true,
			Excluded = applied,
		};
		foreach (var line in first.Eat)
		{
			var count = Homm3DungeonLawHooks.Half(line.Count);
			if (count <= 0)
				continue;
			o.Eat.Add(new UnitLine { Sid = line.Sid, Count = count, SlotPos = line.SlotPos, SquadValue = line.SquadValue });
			o.EatCreatures += count;
		}
		second = o;
		LogEvent("battle " + first.BattleKey + ": Overlord's Due second fate built (excluding " + applied + "). " + DescribeOffer(o));
		return true;
	}

	/// <summary>Second fate without a window (AI, or a window that failed): Ransom, or Execute when Ransom was the first
	/// fate. Pays straight into the hero; no army writes.</summary>
	internal static void ApplySecondFateDirect(Offer first, Choice applied)
	{
		if (!TryBuildSecondFate(first, applied, out var second))
			return;
		var pick = second.Excluded == Choice.Ransom ? Choice.Execute : Choice.Ransom;
		LogEvent("battle " + first.BattleKey + ": Overlord's Due second fate applied directly: " + pick + ".");
		ApplyDirect(second, pick);
	}

	// ---------------------------------------------------------------- battle result

	/// <summary>
	/// Called by Homm3RuntimeMechanicHooks.PrefixBattleResultCleanup before the native result applies (alreadyApplied=false).
	/// The offer is built here (the result still holds the battle's losses); a local human's window is queued to open once
	/// the result has been written and the HUD refreshed, the AI picks now.
	/// </summary>
	internal static void ObserveBeforeBattleResult(object battleLogic, bool showNotification)
	{
		if (!_registered || battleLogic == null)
			return;
		try
		{
			var key = BattleKey(battleLogic);
			lock (Gate)
			{
				if (!Resolved.Add(key))
					return;
			}
			if (!TryBuildOffer(battleLogic, out var offer, out var why))
			{
				if (why != null)
					LogEvent("battle " + key + ": no captives offer (" + why + ").");
				return;
			}
			if (offer.IsLocalHuman)
			{
				offer.ArmyWritable = false;
				if (!Homm3DungeonWarCaptivesWindow.OpenAfterResult(offer, out var fail))
				{
					_log?.LogError(LogPrefix + "choice window could not be queued for battle " + key + " (" + fail + "); paying Ransom.");
					ApplyDirect(offer, Choice.Ransom);
					// law pass 2026-11-25: Captive Couriers (#7)
					GrantCaptiveCouriers(offer);
					// law pass 2026-11-21: Overlord's Due (#30) still pays its half-strength second fate.
					ApplySecondFateDirect(offer, Choice.Ransom);
				}
				else
				{
					LogEvent("battle " + key + ": choice window queued to open after the result applies. " + DescribeOffer(offer));
				}
				return;
			}
			offer.ArmyWritable = true;
			var aiChoice = offer.EatCreatures > 0 ? Choice.Eat : Choice.Ransom;
			Apply(battleLogic, offer, aiChoice);
			// law pass 2026-11-25: Captive Couriers (#7)
			GrantCaptiveCouriers(offer);
			// law pass 2026-11-21: Overlord's Due (#30): AI takes Ransom after Eat, Execute after Ransom, at half strength.
			ApplySecondFateDirect(offer, aiChoice);
		}
		catch (Exception ex)
		{
			LogSkip("battle-result captives failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>AI pick, before the native result applies: Eat writes the winner TransferSide.</summary>
	private static void Apply(object battleLogic, Offer offer, Choice choice)
	{
		if (choice == Choice.Eat || choice == Choice.Recruit)
		{
			var transfer = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicTransferBattleFields) as TransferBattle;
			var result = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicBattleResultInfoFields) as BattleResultInfo;
			var winner = transfer?.sides != null && result != null && result.winnerIndex >= 0 && result.winnerIndex < transfer.sides.Length
				? transfer.sides[result.winnerIndex]
				: null;
			if (winner == null)
			{
				_log?.LogError(LogPrefix + "battle " + offer.BattleKey + ": winner TransferSide unreadable; " + choice + " replaced by Ransom.");
				ApplyDirect(offer, Choice.Ransom);
				return;
			}
			UnitAdder add = (string sid, int count, int slot, out string how) => AddUnits(winner, sid, count, slot, out how);
			Action done = () => _transferSideSortBySlot.Invoke(winner, Array.Empty<object>());
			if (choice == Choice.Eat)
				ApplyEat(offer, add, done);
			else
				ApplyRecruit(offer, add, done);
			return;
		}
		ApplyDirect(offer, choice);
	}

	private delegate bool UnitAdder(string sid, int count, int preferredSlot, out string how);

	/// <summary>Live army of the offer's hero after the result: Data.Hero.party.units as (sid, stacks).</summary>
	private static List<(string Sid, int Stacks)> ReadParty(Offer offer)
	{
		var list = new List<(string, int)>();
		var units = offer.DataHero?.party?.units;
		if (units == null)
			return list;
		for (var i = 0; i < units.Count; i++)
		{
			var unit = units[i];
			if (unit == null)
				continue;
			list.Add((NormalizeSid(ReadMember(unit, GameSymbols.AdventureAiDecision.DataUnitSidFieldHints) as string), unit.stacks));
		}
		return list;
	}

	/// <summary>Native AddUnits merges into a same-sid stack, else takes a free slot (7 max); every new sid needs one.</summary>
	private static bool PartyFits(Offer offer, List<UnitLine> lines)
	{
		try
		{
			var party = ReadParty(offer);
			var present = new HashSet<string>(StringComparer.Ordinal);
			foreach (var (sid, _) in party)
			{
				if (sid != null)
					present.Add(sid);
			}
			var free = 7 - party.Count;
			foreach (var line in lines)
			{
				if (line.Count > 0 && present.Add(line.Sid))
					free--;
			}
			return free >= 0;
		}
		catch (Exception ex)
		{
			LogSkip("army slot check failed: " + ex.GetBaseException().Message);
			return false;
		}
	}

	private static int PartyStacksOf(Offer offer, string sid)
	{
		var total = 0;
		foreach (var (s, n) in ReadParty(offer))
		{
			if (string.Equals(s, sid, StringComparison.Ordinal))
				total += n;
		}
		return total;
	}

	private static bool AddUnitsToParty(Offer offer, string sid, int count, out string how)
	{
		how = null;
		try
		{
			var party = _logicHeroPartyProperty.GetValue(offer.LogicHero);
			if (party == null)
			{
				how = ":no-party";
				return false;
			}
			var before = PartyStacksOf(offer, sid);
			_partyAddUnitsMethod.Invoke(party, new object[] { sid, count, EListenerCallbackCall.RealAndPrediction });
			var after = PartyStacksOf(offer, sid);
			how = "(" + before + "->" + after + ")";
			return after - before == count;
		}
		catch (Exception ex)
		{
			how = ":" + ex.GetBaseException().Message;
			return false;
		}
	}

	/// <summary>Execute / Ransom / Enslave pay without touching the battle result.</summary>
	private static void ApplyDirect(Offer offer, Choice choice)
	{
		try
		{
			switch (choice)
			{
				case Choice.Execute:
					PayExecute(offer);
					break;
				case Choice.Enslave:
					PayEnslave(offer);
					break;
				default:
					if (choice != Choice.Ransom)
						_log?.LogWarning(LogPrefix + "battle " + offer.BattleKey + ": " + choice + " cannot apply after the result; paying Ransom.");
					PayRansom(offer);
					break;
			}
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + "battle " + offer.BattleKey + " " + choice + " payout failed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Player-facing result of an applied choice, shown as a fading banner only to the local human who chose it.</summary>
	// Called by the payout itself, which runs when the native battle apply resumes (after the window closed), so the
	// result banner is shown from here rather than from the window's Finish. AI picks pay the same way but stay silent:
	// their outcome goes to the log only.
	private static void Report(Offer offer, string outcome)
	{
		if (string.IsNullOrEmpty(outcome))
			return;
		if (offer == null || !offer.IsLocalHuman)
		{
			LogEvent("battle " + offer?.BattleKey + ": AI outcome (no banner): " + outcome);
			return;
		}
		try
		{
			Homm3DungeonWarCaptivesWindow.ShowBanner(outcome);
		}
		catch (Exception ex)
		{
			LogSkip("result banner failed: " + ex.GetBaseException().Message);
		}
	}

	private static void PayExecute(Offer offer)
	{
		var expComponent = _expComponentProperty.GetValue(offer.LogicHero);
		if (expComponent == null)
		{
			_log?.LogError(LogPrefix + "Execute: native exp component missing on " + DescribeHero(offer.DataHero) + "; no XP.");
			return;
		}
		var levelBefore = offer.DataHero.currentLevel;
		var expBefore = offer.DataHero.currentExp;
		_expAddMethod.Invoke(expComponent, new object[] { offer.ExecuteXp, true });
		if (offer.ExecuteMana > 0)
			offer.DataHero.mana += offer.ExecuteMana;
		LogEvent("Execute: " + DescribeHero(offer.DataHero) + " captives=" + offer.Captives + " xp=+" + offer.ExecuteXp + " (exp " + expBefore + "->" + offer.DataHero.currentExp
			+ ", level " + levelBefore + "->" + offer.DataHero.currentLevel + ") mana=+" + offer.ExecuteMana + ".");
		var levelAfter = offer.DataHero.currentLevel;
		Report(offer, "Executed " + offer.Captives + " captives: +" + offer.ExecuteXp.ToString("N0") + " Experience"
			+ (levelAfter > levelBefore ? " (level " + levelBefore + " → " + levelAfter + ")" : "")
			+ (offer.ExecuteMana > 0 ? ", +" + offer.ExecuteMana + " Mana" : "") + ".");
	}

	private static void PayRansom(Offer offer)
	{
		if (!TryAddGold(offer.LogicHero, offer.RansomGold, out var before, out var fail))
		{
			_log?.LogError(LogPrefix + "Ransom: " + fail + " (" + DescribeHero(offer.DataHero) + ", gold +" + offer.RansomGold + " not paid).");
			return;
		}
		// law pass 2026-11-25: Black Market Ransoms (#5): 1 Mercury per 20 / 10 captives ransomed.
		var mercury = PayBlackMarketMercury(offer);
		LogEvent("Ransom: " + DescribeHero(offer.DataHero) + " captives=" + offer.Captives + " gold=+" + offer.RansomGold + " (before " + before + ")"
			+ (offer.SlaveMarkets ? " slaveMarkets x1.25" : "") + (mercury > 0 ? " blackMarket mercury=+" + mercury : "") + ".");
		Report(offer, "Ransomed " + offer.Captives + " captives: +" + offer.RansomGold.ToString("N0") + " Gold" + (mercury > 0 ? ", +" + mercury + " Mercury" : "") + ".");
	}

	/// <summary>law pass 2026-11-25: Black Market Ransoms (#5). Pays the Mercury and returns it (0 when not owned or on any failure).</summary>
	private static int PayBlackMarketMercury(Offer offer)
	{
		var mercury = Homm3DungeonLawHooks.BlackMarketMercury(offer.BlackMarketLevel, offer.Captives);
		if (mercury <= 0)
			return 0;
		try
		{
			if (!TryResolveHeroSide(offer.LogicHero, out var dataSide, out var sideFail))
			{
				_log?.LogError(LogPrefix + "Black Market Ransoms: hero side unresolved (" + sideFail + "); no Mercury.");
				return 0;
			}
			if (!Homm3RewardEconomyNativeAdapter.TryResolveResourceFromSide(dataSide, "mercury", out var resource, out _, out var fail)
				|| !Homm3RewardEconomyNativeAdapter.TryAddResourceValue(resource, mercury, out fail))
			{
				_log?.LogError(LogPrefix + "Black Market Ransoms: +" + mercury + " Mercury not paid (" + fail + ").");
				return 0;
			}
			return mercury;
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + "Black Market Ransoms failed closed: " + ex.GetBaseException().Message);
			return 0;
		}
	}

	private static void PayEnslave(Offer offer)
	{
		if (!TryReadEnslaved(offer.LogicHero, out var before, out var readFail))
		{
			_log?.LogError(LogPrefix + "Enslave: enslaved count unreadable (" + readFail + "); paying Ransom instead.");
			PayRansom(offer);
			return;
		}
		var after = (int)Math.Min(MaxEnslaved, (long)before + offer.Captives);
		if (!TryWriteEnslaved(offer.LogicHero, after, out var writeFail))
		{
			_log?.LogError(LogPrefix + "Enslave: write incomplete (" + writeFail + "); enslaved count may be partial.");
			return;
		}
		LogEvent("Enslave: " + DescribeHero(offer.DataHero) + " captives=" + offer.Captives + " enslaved " + before + "->" + after
			+ " daily gold now " + ComputeEnslaveDailyGold(after, offer.Rank, offer.SlaveMarkets) + ".");
		Report(offer, "Enslaved " + offer.Captives + " captives (" + after + " in total): +" + ComputeEnslaveDailyGold(after, offer.Rank, offer.SlaveMarkets).ToString("N0") + " Gold per day.");
	}

	// ---------------------------------------------------------------- recruit panel board

	/// <summary>
	/// The recruit panel's two rows, as in the native diplomacy join panel: the hero's army (top, 7 slots by slotPos) and
	/// the captives willing to join (bottom). Stacks move freely, merge on the same sid and split into empty slots; as in the
	/// native panel the hero's own troops may be moved down and released too, the one rule being that the army keeps at
	/// least one stack. Whatever stays in the bottom row leaves: captives are not recruited, own troops are dismissed.
	/// </summary>
	internal sealed class RecruitBoard
	{
		internal const string ArmyNeedsAStack = "Your hero must keep at least one stack.";
		internal readonly string[] TopSid = new string[MaxArmySlots];
		internal readonly int[] TopCount = new int[MaxArmySlots];
		internal readonly string[] BottomSid = new string[MaxArmySlots];
		internal readonly int[] BottomCount = new int[MaxArmySlots];
		internal readonly Dictionary<string, int> Own = new(StringComparer.Ordinal);
		internal readonly Dictionary<string, int> Captives = new(StringComparer.Ordinal);
		internal readonly Dictionary<string, List<(string Name, int Cost)>> UnitCosts = new(StringComparer.Ordinal);

		internal string Sid(bool top, int i) => top ? TopSid[i] : BottomSid[i];
		internal int Count(bool top, int i) => top ? TopCount[i] : BottomCount[i];

		private void Set(bool top, int i, string sid, int count)
		{
			if (count <= 0 || sid == null)
			{
				sid = null;
				count = 0;
			}
			if (top)
			{
				TopSid[i] = sid;
				TopCount[i] = count;
			}
			else
			{
				BottomSid[i] = sid;
				BottomCount[i] = count;
			}
		}

		internal int Total(bool top, string sid)
		{
			var total = 0;
			for (var i = 0; i < MaxArmySlots; i++)
			{
				if (string.Equals(Sid(top, i), sid, StringComparison.Ordinal))
					total += Count(top, i);
			}
			return total;
		}

		/// <summary>Captives of the sid that end up in the army (top total above the hero's own count).</summary>
		internal int Recruited(string sid)
		{
			Own.TryGetValue(sid, out var own);
			return Math.Max(0, Total(true, sid) - own);
		}

		internal int RecruitedTotal()
		{
			var total = 0;
			foreach (var sid in Captives.Keys)
				total += Recruited(sid);
			return total;
		}

		/// <summary>The hero's own creatures of the sid that end up below (released): own count above the army total.</summary>
		internal int Released(string sid)
		{
			Own.TryGetValue(sid, out var own);
			return Math.Max(0, own - Total(true, sid));
		}

		internal int ReleasedTotal()
		{
			var total = 0;
			foreach (var sid in Own.Keys)
				total += Released(sid);
			return total;
		}

		/// <summary>True when confirming would change the army (something recruited or released).</summary>
		internal bool Changed => RecruitedTotal() > 0 || ReleasedTotal() > 0;

		private bool Valid()
		{
			for (var i = 0; i < MaxArmySlots; i++)
			{
				if (TopSid[i] != null)
					return true;
			}
			return false;
		}

		internal int FirstFree(bool top)
		{
			for (var i = 0; i < MaxArmySlots; i++)
			{
				if (Sid(top, i) == null)
					return i;
			}
			return -1;
		}

		private int FirstOf(bool top, string sid, int except)
		{
			for (var i = 0; i < MaxArmySlots; i++)
			{
				if (i != except && string.Equals(Sid(top, i), sid, StringComparison.Ordinal))
					return i;
			}
			return -1;
		}

		/// <summary>
		/// Moves <paramref name="amount"/> creatures (all when &lt;= 0) from one slot to another: into an empty slot, onto the same
		/// sid (merge), or a whole-stack swap with another sid. Returns null on success, "" for a no-op, else why it was refused
		/// (the board is unchanged).
		/// </summary>
		internal string Move(bool fromTop, int from, bool toTop, int to, int amount = 0)
		{
			if (from < 0 || to < 0 || from >= MaxArmySlots || to >= MaxArmySlots || (fromTop == toTop && from == to))
				return "";
			var sid = Sid(fromTop, from);
			var count = Count(fromTop, from);
			if (sid == null)
				return "";
			if (amount <= 0 || amount > count)
				amount = count;
			var snapshot = Snapshot();
			var targetSid = Sid(toTop, to);
			var targetCount = Count(toTop, to);
			if (targetSid == null)
			{
				Set(toTop, to, sid, amount);
				Set(fromTop, from, sid, count - amount);
			}
			else if (string.Equals(targetSid, sid, StringComparison.Ordinal))
			{
				Set(toTop, to, sid, targetCount + amount);
				Set(fromTop, from, sid, count - amount);
			}
			else
			{
				if (amount < count)
					return "Split into an empty slot.";
				Set(toTop, to, sid, count);
				Set(fromTop, from, targetSid, targetCount);
			}
			if (Valid())
				return null;
			Restore(snapshot);
			return ArmyNeedsAStack;
		}

		/// <summary>Sends a stack to the other row (onto its sid, else the first empty slot).</summary>
		internal string MoveToOtherRow(bool top, int i)
		{
			var sid = Sid(top, i);
			if (sid == null)
				return "";
			var target = FirstOf(!top, sid, -1);
			if (target < 0)
				target = FirstFree(!top);
			if (target < 0)
				return top ? "No free slot among the captives." : "No free army slot.";
			return Move(top, i, !top, target);
		}

		/// <summary>Splits <paramref name="amount"/> creatures off into the row's first empty slot.</summary>
		internal string Split(bool top, int i, int amount)
		{
			if (Sid(top, i) == null || Count(top, i) < 2)
				return "";
			var free = FirstFree(top);
			if (free < 0)
				return "No empty slot to split into.";
			return Move(top, i, top, free, Math.Max(1, Math.Min(amount, Count(top, i) - 1)));
		}

		/// <summary>Gathers every stack of the slot's sid in the same row into this slot.</summary>
		internal string Gather(bool top, int i)
		{
			var sid = Sid(top, i);
			if (sid == null)
				return "";
			for (var j = 0; j < MaxArmySlots; j++)
			{
				if (j != i && string.Equals(Sid(top, j), sid, StringComparison.Ordinal))
					Move(top, j, top, i);
			}
			return null;
		}

		/// <summary>Native "Add all Army": every captive stack moves up as far as the army has room.</summary>
		internal void RecruitAll()
		{
			for (var i = 0; i < MaxArmySlots; i++)
			{
				if (BottomSid[i] != null)
					MoveToOtherRow(false, i);
			}
		}

		internal SortedDictionary<string, int> Cost()
		{
			var total = new SortedDictionary<string, int>(StringComparer.Ordinal);
			foreach (var pair in UnitCosts)
			{
				var recruited = Recruited(pair.Key);
				if (recruited <= 0)
					continue;
				foreach (var (name, cost) in pair.Value)
				{
					total.TryGetValue(name, out var have);
					total[name] = (int)Math.Min(int.MaxValue, have + (long)cost * recruited);
				}
			}
			return total;
		}

		private (string[] TopSid, int[] TopCount, string[] BottomSid, int[] BottomCount) Snapshot()
		{
			return ((string[])TopSid.Clone(), (int[])TopCount.Clone(), (string[])BottomSid.Clone(), (int[])BottomCount.Clone());
		}

		private void Restore((string[] TopSid, int[] TopCount, string[] BottomSid, int[] BottomCount) s)
		{
			Array.Copy(s.TopSid, TopSid, MaxArmySlots);
			Array.Copy(s.TopCount, TopCount, MaxArmySlots);
			Array.Copy(s.BottomSid, BottomSid, MaxArmySlots);
			Array.Copy(s.BottomCount, BottomCount, MaxArmySlots);
		}
	}

	/// <summary>The live army (top, by slotPos) and the offered captives (bottom), or null with the reason.</summary>
	internal static RecruitBoard NewRecruitBoard(Offer offer, out string failReason)
	{
		if (!Homm3PartyArmyWriter.TryReadArmy(offer.LogicHero, offer.DataHero, out var slotSid, out var slotCount, out var totals, out failReason))
			return null;
		var board = new RecruitBoard();
		Array.Copy(slotSid, board.TopSid, MaxArmySlots);
		Array.Copy(slotCount, board.TopCount, MaxArmySlots);
		foreach (var pair in totals)
			board.Own[pair.Key] = pair.Value;
		var slot = 0;
		foreach (var line in offer.Recruit)
		{
			if (line.Count <= 0 || slot >= MaxArmySlots)
				continue;
			board.BottomSid[slot] = line.Sid;
			board.BottomCount[slot] = line.Count;
			slot++;
			board.Captives.TryGetValue(line.Sid, out var have);
			board.Captives[line.Sid] = have + line.Count;
			board.UnitCosts[line.Sid] = line.Cost;
		}
		return board;
	}

	/// <summary>True when at least one offered captive can join: its sid is already in the army or a slot is free.</summary>
	private static bool AnyRecruitFits(Offer offer)
	{
		var board = NewRecruitBoard(offer, out _);
		if (board == null)
			return false;
		if (board.FirstFree(true) >= 0)
			return true;
		foreach (var sid in board.Captives.Keys)
		{
			if (board.Own.ContainsKey(sid))
				return true;
		}
		return false;
	}

	/// <summary>True when the side can pay for one creature of at least one offered type.</summary>
	private static bool CanAffordOne(Offer offer, out string missing)
	{
		missing = null;
		foreach (var line in offer.Recruit)
		{
			var one = new Dictionary<string, int>(StringComparer.Ordinal);
			foreach (var (name, cost) in line.Cost)
				one[name] = cost;
			if (CanAfford(offer, one, out var shortOne))
				return true;
			missing ??= shortOne;
		}
		return false;
	}

	/// <summary>
	/// Writes the recruit panel's army row to the live party and charges the recruited captives: existing Data.Units of a
	/// sid are reused (slotPos and stacks rewritten; a merged-away stack is removed from the list), new stacks go through
	/// the native AddUnitAtSlot, then the party listeners run once. Charges only after the army reads back as arranged.
	/// Returns false (nothing changed) when the arrangement cannot be paid or the army changed under the panel.
	/// </summary>
	private static bool ApplyRecruitBoard(Offer offer, RecruitBoard board, out string failReason)
	{
		failReason = null;
		if (!_arrangeRegistered)
		{
			failReason = "recruit panel calls unresolved";
			return false;
		}
		if (!board.Changed)
		{
			failReason = "the army was not changed";
			return false;
		}
		var cost = board.Cost();
		if (!CanAfford(offer, cost, out var missing))
		{
			failReason = "not enough " + missing;
			return false;
		}
		if (!TryResolveHeroSide(offer.LogicHero, out var dataSide, out var sideFail))
		{
			failReason = "hero side unresolved (" + sideFail + ")";
			return false;
		}
		var steps = new List<string>();
		switch (Homm3PartyArmyWriter.Write(offer.LogicHero, offer.DataHero, board.TopSid, board.TopCount, board.Own, steps, out var writeFail))
		{
			case Homm3PartyArmyWriter.WriteResult.Refused:
				failReason = writeFail;
				return false;
			case Homm3PartyArmyWriter.WriteResult.WriteFailed:
				_log?.LogError(LogPrefix + "Recruit: army write failed after [" + string.Join(", ", steps) + "]: " + writeFail + "; nothing charged.");
				Report(offer, "Recruit failed while arranging the army (see the log).");
				return true;
			case Homm3PartyArmyWriter.WriteResult.ReadBackMismatch:
				_log?.LogError(LogPrefix + "Recruit: army reads back differently [" + writeFail + "] after [" + string.Join(", ", steps) + "]; nothing charged.");
				Report(offer, "Recruit: the army did not update as arranged (see the log).");
				return true;
		}
		foreach (var pair in cost)
		{
			if (pair.Value <= 0)
				continue;
			if (!Homm3RewardEconomyNativeAdapter.TryResolveResourceFromSide(dataSide, pair.Key, out var resource, out _, out var spendFail)
				|| !Homm3RewardEconomyNativeAdapter.TryAddResourceValue(resource, -pair.Value, out spendFail))
				_log?.LogError(LogPrefix + "Recruit: spending " + pair.Value + " " + pair.Key + " failed (" + spendFail + ").");
		}
		var parts = new List<string>();
		foreach (var sid in board.Captives.Keys)
		{
			var recruited = board.Recruited(sid);
			if (recruited > 0)
				parts.Add((Homm3UnitDisplayNames.Resolve(sid) ?? sid) + " x" + recruited);
		}
		var released = new List<string>();
		foreach (var sid in board.Own.Keys)
		{
			var gone = board.Released(sid);
			if (gone > 0)
				released.Add((Homm3UnitDisplayNames.Resolve(sid) ?? sid) + " x" + gone);
		}
		LogEvent("Recruit: " + DescribeHero(offer.DataHero) + " captives=" + offer.Captives + " recruited [" + string.Join(", ", parts) + "] for "
			+ FormatCost(cost) + ", released own [" + string.Join(", ", released) + "]; army [" + string.Join(", ", steps) + "].");
		var outcome = new List<string>();
		if (parts.Count > 0)
			outcome.Add("Recruited " + string.Join(", ", parts) + " for " + FormatCost(cost));
		if (released.Count > 0)
			outcome.Add((parts.Count > 0 ? "released " : "Released ") + string.Join(", ", released));
		Report(offer, string.Join("; ", outcome) + ".");
		return true;
	}

	private static void ApplyEat(Offer offer, UnitAdder add, Action done)
	{
		var parts = new List<string>();
		foreach (var line in offer.Eat)
		{
			if (line.Count <= 0)
				continue;
			if (add(line.Sid, line.Count, line.SlotPos, out var how))
				parts.Add(line.Sid + "+" + line.Count + how);
			else
				parts.Add(line.Sid + "+" + line.Count + ":FAILED" + how);
		}
		done?.Invoke();
		LogEvent("Eat: " + DescribeHero(offer.DataHero) + " captives=" + offer.Captives + " restored [" + string.Join(",", parts) + "].");
		Report(offer, "Ate " + offer.Captives + " captives: restored " + DescribeLines(offer.Eat) + ".");
	}

	private static void ApplyRecruit(Offer offer, UnitAdder add, Action done)
	{
		if (!TryResolveHeroSide(offer.LogicHero, out var dataSide, out var sideFail))
		{
			_log?.LogError(LogPrefix + "Recruit: hero side unresolved (" + sideFail + "); paying Ransom.");
			PayRansom(offer);
			return;
		}
		var resources = new List<(string Name, object Resource, int Cost)>();
		foreach (var cost in offer.RecruitCost)
		{
			if (cost.Value <= 0)
				continue;
			if (!Homm3RewardEconomyNativeAdapter.TryResolveResourceFromSide(dataSide, cost.Key, out var resource, out var info, out var fail) || info.Value < cost.Value)
			{
				_log?.LogWarning(LogPrefix + "Recruit: " + cost.Key + " " + (fail ?? info.Value + " < " + cost.Value) + "; paying Ransom instead.");
				PayRansom(offer);
				return;
			}
			resources.Add((cost.Key, resource, cost.Value));
		}
		foreach (var (name, resource, value) in resources)
		{
			if (!Homm3RewardEconomyNativeAdapter.TryAddResourceValue(resource, -value, out var spendFail))
				_log?.LogError(LogPrefix + "Recruit: spending " + value + " " + name + " failed (" + spendFail + ").");
		}
		var parts = new List<string>();
		foreach (var line in offer.Recruit)
		{
			if (line.Count <= 0)
				continue;
			parts.Add(line.Sid + "+" + line.Count + (add(line.Sid, line.Count, -1, out var how) ? how : ":FAILED" + how));
		}
		done?.Invoke();
		LogEvent("Recruit: " + DescribeHero(offer.DataHero) + " captives=" + offer.Captives + " recruited [" + string.Join(",", parts) + "] for " + FormatCost(offer.RecruitCost) + ".");
		Report(offer, "Recruited " + DescribeLines(offer.Recruit) + " for " + FormatCost(offer.RecruitCost) + ".");
	}

	private static string DescribeLines(List<UnitLine> lines)
	{
		var parts = new List<string>();
		foreach (var line in lines)
		{
			if (line.Count > 0)
				parts.Add((Homm3UnitDisplayNames.Resolve(line.Sid) ?? line.Sid) + " x" + line.Count);
		}
		return parts.Count == 0 ? "nothing" : string.Join(", ", parts);
	}

	/// <summary>Merges into a living stack of the sid (the given slot first), else adds a new stack the way Skeletal Necromancy does.</summary>
	private static bool AddUnits(TransferSide side, string sid, int count, int preferredSlot, out string how)
	{
		how = null;
		TransferUnit target = null;
		if (side.units != null)
		{
			foreach (var unit in side.units)
			{
				if (unit == null || !string.Equals(NormalizeSid(unit.configSid), sid, StringComparison.Ordinal))
					continue;
				if (preferredSlot >= 0 && unit.slotPos == preferredSlot)
				{
					target = unit;
					break;
				}
				if (target == null && unit.stacks > 0)
					target = unit;
			}
		}
		if (target != null)
		{
			var before = target.stacks;
			target.stacks = Math.Max(0, before) + count;
			how = "@slot" + target.slotPos + "(" + before + "->" + target.stacks + ")";
			return true;
		}
		_transferSideAddSpawnedUnit.Invoke(side, new object[] { new TransferUnit(sid, count, 0), true });
		how = ":new";
		return true;
	}

	// ---------------------------------------------------------------- offer

	internal static bool TryBuildOffer(object battleLogic, out Offer offer, out string why)
	{
		offer = null;
		why = null;
		var transfer = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicTransferBattleFields) as TransferBattle;
		var started = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicStartedTransferBattleFields) as TransferBattle;
		var result = ReadMember(battleLogic, GameSymbols.SkeletalNecromancy.BattleLogicBattleResultInfoFields) as BattleResultInfo;
		if (transfer?.sides == null || started?.sides == null || result == null)
		{
			why = "battle result unreadable";
			return false;
		}
		var winnerIndex = result.winnerIndex;
		if (winnerIndex < 0 || winnerIndex >= started.sides.Length)
			return false;
		var winnerStarted = started.sides[winnerIndex];
		var winnerAfter = winnerIndex < transfer.sides.Length ? transfer.sides[winnerIndex] : null;
		var logicHero = winnerStarted?.logicHero ?? winnerAfter?.logicHero;
		var dataHero = ResolveDataHero(logicHero);
		var rank = Homm3DungeonDraconicDominionHook.ResolveFactionSkillRank(dataHero);
		if (rank <= 0)
			return false;

		var o = new Offer
		{
			BattleKey = BattleKey(battleLogic),
			LogicHero = logicHero,
			DataHero = dataHero,
			HeroSid = dataHero.configSid,
			Rank = rank,
			IsLocalHuman = winnerStarted != null && winnerStarted.controlType == TransferSide.EControlType.ME,
			Interrogation = HasSubSkill(dataHero, InterrogationSubSkillSid),
			HasEnslave = HasSubSkill(dataHero, EnslaveSubSkillSid),
			HasRecruit = HasSubSkill(dataHero, RecruitSubSkillSid),
			SlaveMarkets = HasSubSkill(dataHero, SlaveMarketsSubSkillSid),
			DungeonCells = HasSubSkill(dataHero, DungeonCellsSubSkillSid),
		};
		// law pass 2026-11-25: Dungeon laws #5 Black Market Ransoms, #7 Captive Couriers, #9 Taskmasters and #30 Overlord's Due
		// on the winner's logic hero. Taskmasters no longer grants Recruit (the Recruit Captives subskill does).
		o.BlackMarketLevel = Homm3DungeonLawHooks.Rank(logicHero, Homm3DungeonLawHooks.BlackMarketRansomsLaw);
		o.CouriersLevel = Homm3DungeonLawHooks.Rank(logicHero, Homm3DungeonLawHooks.CaptiveCouriersLaw);
		o.TaskmastersLevel = Homm3DungeonLawHooks.Rank(logicHero, Homm3DungeonLawHooks.TaskmastersLaw);
		o.OverlordsDue = Homm3DungeonLawHooks.HasOverlordsDue(logicHero);
		NoteDailyMovement(dataHero);

		// Defeated enemies: every other side, started minus remaining, by sid.
		var killedBySid = new Dictionary<string, int>(StringComparer.Ordinal);
		for (var sideIndex = 0; sideIndex < started.sides.Length; sideIndex++)
		{
			if (sideIndex == winnerIndex)
				continue;
			var after = sideIndex < transfer.sides.Length ? transfer.sides[sideIndex] : null;
			foreach (var (unit, lost) in Losses(started.sides[sideIndex], after))
			{
				var sid = NormalizeSid(unit.configSid);
				var config = ResolveConfig(unit);
				if (sid == null || config == null)
					continue;
				o.DefeatedValue += (long)Math.Max(0, config.squadValue) * lost;
				killedBySid.TryGetValue(sid, out var have);
				killedBySid[sid] = have + lost;
			}
		}
		var captives = o.DefeatedValue * (o.DungeonCells ? DungeonCellsCaptiveMultiplier : 1.0) / ValuePerCaptive;
		o.Captives = (int)Math.Min(MaxEnslaved, Math.Floor(captives));
		if (o.Captives <= 0)
		{
			why = "defeated value " + o.DefeatedValue + " below one captive";
			return false;
		}

		var index = rank - 1;
		var baseExecuteXp = (int)Math.Min(int.MaxValue, (long)o.Captives * ExecuteXpPerCaptive[index]);
		o.ExecuteXp = baseExecuteXp;
		o.ExecuteMana = o.Interrogation ? (int)Math.Round(baseExecuteXp * InterrogationManaPerXp, MidpointRounding.AwayFromZero) : 0;
		o.RansomGold = (int)Math.Min(int.MaxValue, Math.Floor((long)o.Captives * RansomGoldPerCaptive[index] * (o.SlaveMarkets ? SlaveMarketsGoldMultiplier : 1.0)));
		if (TryReadEnslaved(logicHero, out var enslaved, out _))
			o.EnslavedBefore = enslaved;
		o.EnslaveDailyGoldAfter = ComputeEnslaveDailyGold((int)Math.Min(MaxEnslaved, (long)o.EnslavedBefore + o.Captives), rank, o.SlaveMarkets);

		BuildEat(o, winnerStarted, winnerAfter);
		BuildRecruit(o, killedBySid, winnerAfter);
		offer = o;
		return true;
	}

	private static void BuildEat(Offer o, TransferSide started, TransferSide after)
	{
		var percent = EatPercent[o.Rank - 1];
		long value = 0;
		foreach (var (unit, lost) in Losses(started, after))
		{
			var count = lost * percent / 100;
			var config = ResolveConfig(unit);
			if (count <= 0 || config == null)
				continue;
			var line = new UnitLine { Sid = NormalizeSid(unit.configSid), Count = count, SlotPos = unit.slotPos, SquadValue = Math.Max(0, config.squadValue) };
			o.Eat.Add(line);
			value += (long)line.SquadValue * count;
		}
		// Never restore more squad value than the captives were worth: scale every stack by the same factor (floor).
		var cap = (long)o.Captives * ValuePerCaptive;
		if (value > cap && value > 0)
		{
			var factor = (double)cap / value;
			foreach (var line in o.Eat)
				line.Count = (int)Math.Floor(line.Count * factor);
		}
		o.Eat.RemoveAll(line => line.Count <= 0);
		foreach (var line in o.Eat)
			o.EatCreatures += line.Count;
	}

	private static void BuildRecruit(Offer o, Dictionary<string, int> killedBySid, TransferSide winnerAfter)
	{
		if (!o.HasRecruit)
			return;
		var percent = RecruitPercent[o.Rank - 1];
		var candidates = new List<UnitLine>();
		foreach (var pair in killedBySid)
		{
			var count = pair.Value * percent / 100;
			var config = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(pair.Key);
			if (count <= 0 || config == null)
				continue;
			candidates.Add(new UnitLine { Sid = pair.Key, Count = count, SlotPos = -1, SquadValue = Math.Max(0, config.squadValue) });
		}
		// Highest total value first; the recruit panel's captive row has seven slots, so the best seven types are offered.
		// Army fit is the panel's job (the player merges, splits or leaves stacks behind).
		candidates.Sort((a, b) => ((long)b.SquadValue * b.Count).CompareTo((long)a.SquadValue * a.Count));
		foreach (var line in candidates)
		{
			if (o.Recruit.Count >= MaxArmySlots)
				break;
			var config = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(line.Sid);
			foreach (var (name, listCost) in UnitCost(config))
			{
				// law pass 2026-11-25: Taskmasters (#9): Recruit costs 25% / 50% less Gold.
				var cost = string.Equals(name, "gold", StringComparison.Ordinal) ? Homm3DungeonLawHooks.TaskmastersGoldCost(o.TaskmastersLevel, listCost) : listCost;
				line.Cost.Add((name, cost));
				o.RecruitCost.TryGetValue(name, out var have);
				o.RecruitCost[name] = (int)Math.Min(int.MaxValue, have + (long)cost * line.Count);
			}
			o.Recruit.Add(line);
			o.RecruitCreatures += line.Count;
		}
	}

	private static IEnumerable<(TransferUnit Unit, int Lost)> Losses(TransferSide started, TransferSide after)
	{
		if (started?.units == null)
			yield break;
		foreach (var before in started.units)
		{
			if (before == null || before.stacks <= 0)
				continue;
			var sid = NormalizeSid(before.configSid);
			var remaining = 0;
			if (after?.units != null)
			{
				foreach (var candidate in after.units)
				{
					if (candidate != null && candidate.slotPos == before.slotPos && string.Equals(NormalizeSid(candidate.configSid), sid, StringComparison.Ordinal))
					{
						remaining = Math.Max(0, candidate.stacks);
						break;
					}
				}
			}
			var lost = Math.Max(0, before.stacks - remaining);
			if (lost > 0)
				yield return (before, lost);
		}
	}

	private static UnitLogicConfig ResolveConfig(TransferUnit unit)
	{
		return unit?.prop_UnitLogicConfig_0 ?? Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(unit?.configSid);
	}

	private static IEnumerable<(string Name, int Cost)> UnitCost(UnitLogicConfig config)
	{
		var costs = config?.unitCost?.costResArray;
		for (var i = 0; costs != null && i < costs.Length; i++)
		{
			var name = NormalizeSid(costs[i]?.name);
			if (name != null && ReadMember(costs[i], GameSymbols.DraconicDominion.ResNameAndCostCostMembers) is int cost && cost > 0)
				yield return (name, cost);
		}
	}

	/// <summary>True when the hero's side holds every resource of <paramref name="price"/>; else names the first short one.</summary>
	internal static bool CanAfford(Offer offer, IEnumerable<KeyValuePair<string, int>> price, out string missing)
	{
		missing = null;
		if (!TryResolveHeroSide(offer.LogicHero, out var dataSide, out _))
		{
			missing = "resources (side unreadable)";
			return false;
		}
		foreach (var cost in price)
		{
			if (cost.Value <= 0)
				continue;
			if (!Homm3RewardEconomyNativeAdapter.TryResolveResourceFromSide(dataSide, cost.Key, out _, out var info, out _) || info.Value < cost.Value)
			{
				missing = cost.Key;
				return false;
			}
		}
		return true;
	}

	internal static int ComputeEnslaveDailyGold(int enslaved, int rank, bool slaveMarkets)
	{
		if (enslaved <= 0)
			return 0;
		var index = Math.Max(1, Math.Min(3, rank)) - 1;
		return (int)Math.Min(int.MaxValue / 2, Math.Floor(enslaved * EnslaveGoldPerDay[index] * (slaveMarkets ? SlaveMarketsGoldMultiplier : 1.0)));
	}

	internal static string FormatCost(IDictionary<string, int> cost)
	{
		var parts = new List<string>();
		foreach (var pair in cost)
		{
			if (pair.Value > 0)
				parts.Add(pair.Value.ToString("N0", System.Globalization.CultureInfo.InvariantCulture) + " " + pair.Key);
		}
		return parts.Count == 0 ? "free" : string.Join(", ", parts);
	}

	private static string DescribeOffer(Offer o)
	{
		return "hero=" + DescribeHero(o.DataHero) + " rank=" + o.Rank + (o.SecondFate ? " secondFate(excl " + o.Excluded + ")" : "")
			+ (o.BlackMarketLevel > 0 || o.CouriersLevel > 0 || o.TaskmastersLevel > 0 || o.OverlordsDue
				? " laws[blackMarket L" + o.BlackMarketLevel + " couriers L" + o.CouriersLevel + " taskmasters L" + o.TaskmastersLevel + (o.OverlordsDue ? " overlord" : "") + "]"
				: "")
			+ " defeatedValue=" + o.DefeatedValue + " captives=" + o.Captives
			+ " execute=+" + o.ExecuteXp + "xp/+" + o.ExecuteMana + "mana ransom=+" + o.RansomGold + "g eat=" + o.EatCreatures
			+ (o.HasEnslave ? " enslave->" + o.EnslaveDailyGoldAfter + "g/day" : "")
			+ (o.HasRecruit ? " recruit=" + o.RecruitCreatures + " for " + FormatCost(o.RecruitCost) + (o.RecruitBlocked != null ? " (" + o.RecruitBlocked + ")" : "") : "");
	}

	// ---------------------------------------------------------------- day start: enslaved gold + legacy bank

	/// <summary>Shared day-start consumer (Homm3SwashbucklerGoldHook): gold for this hero's enslaved captives, plus a legacy bank payout once.</summary>
	/// <summary>Side-effect-free <see cref="OnDayStartHero"/> for the gold-hover income preview (enslaved gold only).</summary>
	private static (int Gold, string Label) ForecastDayStartHero(object entry)
	{
		if (entry == null || _logicHeroType == null || !_logicHeroType.IsInstanceOfType(entry))
			return (0, null);
		var dataHero = ResolveDataHero(entry);
		if (dataHero == null || !TryReadEnslaved(entry, out var enslaved, out _) || enslaved <= 0)
			return (0, null);
		var rank = Math.Max(1, Homm3DungeonDraconicDominionHook.ResolveFactionSkillRank(dataHero));
		var daily = ComputeEnslaveDailyGold(enslaved, rank, HasSubSkill(dataHero, SlaveMarketsSubSkillSid));
		var name = Homm3HeroDisplayNames.Resolve(dataHero.configSid) ?? dataHero.configSid;
		return ((int)Math.Min(int.MaxValue / 2, daily), "Enslaved captives (" + name + ", " + enslaved + ")");
	}

	private static int OnDayStartHero(object entry)
	{
		if (entry == null || _logicHeroType == null || !_logicHeroType.IsInstanceOfType(entry))
			return 0;
		try
		{
			var dataHero = ResolveDataHero(entry);
			// law pass 2026-11-25: Captive Couriers (#7): the day-start movement is the hero's daily movement.
			NoteDailyMovement(dataHero);
			var manager = ResolveBuffManager(entry, out _);
			if (dataHero == null || manager == null)
				return 0;
			var rank = Math.Max(1, Homm3DungeonDraconicDominionHook.ResolveFactionSkillRank(dataHero));
			var slaveMarkets = HasSubSkill(dataHero, SlaveMarketsSubSkillSid);
			long gold = 0;
			if (TryReadEnslaved(entry, out var enslaved, out _) && enslaved > 0)
			{
				var daily = ComputeEnslaveDailyGold(enslaved, rank, slaveMarkets);
				gold += daily;
				LogEvent("day start: " + DescribeHero(dataHero) + " enslaved=" + enslaved + " gold=+" + daily + ".");
				try
				{
					AnnounceDayStart(dataHero, enslaved, daily);
				}
				catch (Exception ex)
				{
					LogSkip("day-start banner failed: " + ex.GetBaseException().Message);
				}
			}
			gold += MigrateLegacyBank(entry, dataHero, manager, rank, slaveMarkets);
			return (int)Math.Min(int.MaxValue / 2, gold);
		}
		catch (Exception ex)
		{
			LogSkip("day-start captives failed closed: " + ex.GetBaseException().Message);
			return 0;
		}
	}

	private static long MigrateLegacyBank(object logicHero, DataHero dataHero, object manager, int rank, bool slaveMarkets)
	{
		var units = 0;
		for (var bit = 0; bit < LegacyStrengthBitCount; bit++)
		{
			if (HasBuff(manager, LegacyStrengthBitBuffPrefix + bit))
				units |= 1 << bit;
		}
		var any = units > 0;
		for (var bit = 0; !any && bit < LegacySquadBitCount; bit++)
			any = HasBuff(manager, LegacySquadBitBuffPrefix + bit);
		for (var tier = 0; !any && tier <= LegacyTierCount; tier++)
			any = HasBuff(manager, LegacyTierBuffPrefix + tier);
		if (!any)
			return 0;
		var failures = new List<string>();
		for (var bit = 0; bit < LegacyStrengthBitCount; bit++)
			SetBuff(manager, LegacyStrengthBitBuffPrefix + bit, false, failures);
		for (var bit = 0; bit < LegacySquadBitCount; bit++)
			SetBuff(manager, LegacySquadBitBuffPrefix + bit, false, failures);
		for (var tier = 0; tier <= LegacyTierCount; tier++)
			SetBuff(manager, LegacyTierBuffPrefix + tier, false, failures);
		if (failures.Count > 0)
		{
			_log?.LogError(LogPrefix + "legacy Captives bank of " + DescribeHero(dataHero) + " not cleared (" + string.Join("; ", failures) + "); no payout, retried next day.");
			return 0;
		}
		var captives = (long)units * LegacyStrengthUnit / ValuePerCaptive;
		var gold = (long)Math.Floor(captives * RansomGoldPerCaptive[rank - 1] * (slaveMarkets ? SlaveMarketsGoldMultiplier : 1.0));
		_log?.LogInfo(LogPrefix + "legacy Captives bank of " + DescribeHero(dataHero) + " (" + (long)units * LegacyStrengthUnit + " strength) paid as Ransom: +" + gold + " gold; old buffs cleared.");
		return gold;
	}

	// ---------------------------------------------------------------- enslaved state (buffs)

	internal static bool TryReadEnslaved(object logicHero, out int count, out string failReason)
	{
		count = 0;
		var manager = ResolveBuffManager(logicHero, out failReason);
		if (manager == null)
			return false;
		for (var bit = 0; bit < EnslavedBitCount; bit++)
		{
			if (HasBuff(manager, EnslavedBitBuffPrefix + bit))
				count |= 1 << bit;
		}
		return true;
	}

	private static bool TryWriteEnslaved(object logicHero, int count, out string failReason)
	{
		var manager = ResolveBuffManager(logicHero, out failReason);
		if (manager == null)
			return false;
		count = Math.Max(0, Math.Min(MaxEnslaved, count));
		var failures = new List<string>();
		for (var bit = 0; bit < EnslavedBitCount; bit++)
			SetBuff(manager, EnslavedBitBuffPrefix + bit, (count & (1 << bit)) != 0, failures);
		SetBuff(manager, EnslavedBuffSid, count > 0, failures);
		if (failures.Count == 0)
			return true;
		failReason = string.Join("; ", failures);
		return false;
	}

	private static object ResolveBuffManager(object logicHero, out string failReason)
	{
		failReason = null;
		if (logicHero == null || _buffManagerProperty == null || !_buffManagerProperty.DeclaringType.IsInstanceOfType(logicHero))
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
			if (HasBuff(manager, sid) == wanted)
				return;
			if (wanted)
			{
				var durations = new Il2CppReferenceArray<BuffDuration>(1);
				durations[0] = new BuffDuration(EBuffDurationType.Infinite, -1);
				_buffAddMethod.Invoke(manager, new object[] { sid, durations });
			}
			else
			{
				// Native Remove only drops dispellable configs: every Captives row is isDispellable=true.
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

	// ---------------------------------------------------------------- UI snapshot (enslaved buff tooltip)

	internal static bool TryBuildUiSnapshot(object logicHero, out Homm3DungeonCaptivesUi.Snapshot snapshot, out string failReason)
	{
		snapshot = null;
		if (!_registered)
		{
			failReason = "War Captives runtime not registered";
			return false;
		}
		var dataHero = ResolveDataHero(logicHero);
		if (dataHero == null)
		{
			failReason = "Data.Hero unresolved from logic hero";
			return false;
		}
		if (!TryReadEnslaved(logicHero, out var enslaved, out failReason))
			return false;
		var rank = Math.Max(1, Homm3DungeonDraconicDominionHook.ResolveFactionSkillRank(dataHero));
		var slaveMarkets = HasSubSkill(dataHero, SlaveMarketsSubSkillSid);
		snapshot = new Homm3DungeonCaptivesUi.Snapshot
		{
			Enslaved = enslaved,
			DailyGold = ComputeEnslaveDailyGold(enslaved, rank, slaveMarkets),
			GoldPerCaptive = EnslaveGoldPerDay[rank - 1] * (slaveMarkets ? SlaveMarketsGoldMultiplier : 1.0),
			Rank = rank,
			SlaveMarkets = slaveMarkets,
		};
		return true;
	}

	internal static bool IsLogicHero(object candidate)
	{
		return candidate != null && _logicHeroType != null && _logicHeroType.IsInstanceOfType(candidate);
	}

	// ---------------------------------------------------------------- legacy spells

	/// <summary>Suppresses retired Captives-bank Execute/Ransom rows; any other Necromancer Will setting passes through.</summary>
	private static bool PrefixNecromancyWorldMagicCast(object __instance, ref bool __result)
	{
		try
		{
			var setting = ReadMember(__instance, GameSymbols.CastleEliteStrategem.NecromancyWorldMagicSettingMembers) as MagicSetting;
			if (setting == null || !string.Equals(setting.mechType, NativeNecromancyMechType, StringComparison.Ordinal))
				return true;
			var parameters = ReadParameters(setting.parameters);
			if (parameters.Count < 1 || (!string.Equals(parameters[0], LegacyExecuteMode, StringComparison.Ordinal) && !string.Equals(parameters[0], LegacyRansomMode, StringComparison.Ordinal)))
				return true;
			__result = false;
			_log?.LogWarning(LogPrefix + "retired Captives spell " + parameters[0] + " cast; suppressed (War Captives pays after battles; a legacy bank is paid as Ransom at day start).");
			return false;
		}
		catch (Exception ex)
		{
			LogSkip("legacy spell inspection failed; native handler remains responsible: " + ex.GetBaseException().Message);
			return true;
		}
	}

	// ---------------------------------------------------------------- law pass 2026-11-25: Captive Couriers (#7)

	/// <summary>Highest movement seen per data hero today (day start runs after the native movement refill).</summary>
	private static readonly Dictionary<int, (int Day, int Max)> DailyMovement = new();
	private static MethodInfo _setMovePoints;
	private static Type _setMovePointsOwner;

	private static void NoteDailyMovement(DataHero hero)
	{
		try
		{
			if (hero == null || !Homm3FactoryLogisticsEffects.TryGetData(out var data, out _) || data == null)
				return;
			var day = data.daysInGameCount;
			var move = hero.worldMovePoints;
			lock (DailyMovement)
			{
				if (!DailyMovement.TryGetValue(hero.field_Public_Int32_0, out var seen) || seen.Day != day || move > seen.Max)
					DailyMovement[hero.field_Public_Int32_0] = (day, move);
			}
		}
		catch
		{
			// Diagnostic cache only: a miss leaves the current movement as the daily figure (grants less, never more).
		}
	}

	/// <summary>
	/// After the hero's fate choice (once per battle; never on the Overlord's Due second fate), restores the level's
	/// share of the hero's daily movement through the native move-point controller, capped at the daily movement.
	/// Fails closed: no world hero, controller or readback means no movement and a log line.
	/// </summary>
	private static void GrantCaptiveCouriers(Offer offer)
	{
		if (offer == null || offer.CouriersPaid || offer.SecondFate || offer.CouriersLevel <= 0)
			return;
		offer.CouriersPaid = true;
		try
		{
			var hero = ResolveDataHero(offer.LogicHero) ?? offer.DataHero;
			if (hero == null || !Homm3FactoryLogisticsEffects.TryGetData(out var data, out var dataFail) || data == null)
			{
				LogSkip("Captive Couriers: hero or session data unreadable; no movement.");
				return;
			}
			var now = hero.worldMovePoints;
			var max = now;
			lock (DailyMovement)
			{
				if (DailyMovement.TryGetValue(hero.field_Public_Int32_0, out var seen) && seen.Day == data.daysInGameCount)
					max = Math.Max(seen.Max, now);
			}
			var target = (int)Math.Min(max, now + Math.Floor(max * Homm3DungeonLawHooks.CaptiveCouriersShare(offer.CouriersLevel)));
			if (target <= now)
			{
				LogEvent("Captive Couriers: " + DescribeHero(hero) + " movement " + now + " of " + max + "; nothing to restore.");
				return;
			}
			if (!TrySetWorldMovement(offer.LogicHero, hero, target, out var fail))
			{
				_log?.LogWarning(LogPrefix + "Captive Couriers: movement not restored (" + fail + ").");
				return;
			}
			LogEvent("Captive Couriers L" + offer.CouriersLevel + ": " + DescribeHero(hero) + " movement " + now + " -> " + target + " (daily " + max + ").");
		}
		catch (Exception ex)
		{
			LogSkip("Captive Couriers failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Sets a hero's world movement through its world hero's native move-point controller and reads it back.</summary>
	private static bool TrySetWorldMovement(object logicHero, DataHero hero, int target, out string fail)
	{
		fail = null;
		var worldHero = FindWorldHero(logicHero);
		if (worldHero == null)
		{
			fail = "world hero not in the session hero registry";
			return false;
		}
		var controller = ReadMember(worldHero, GameSymbols.HomecomingBoatTravel.WorldHeroMovePointControllerMembers);
		if (controller == null)
		{
			fail = "move-point controller unreadable (HomecomingBoatTravel.WorldHeroMovePointControllerMembers)";
			return false;
		}
		var type = controller.GetType();
		if (_setMovePointsOwner != type)
		{
			_setMovePointsOwner = type;
			_setMovePoints = GameMember.FindFirstMethodByNames(type, new[] { typeof(int) }, GameSymbols.HomecomingBoatTravel.MovePointControllerSetWorldMovePoints);
			if (_setMovePoints != null && _setMovePoints.ReturnType != typeof(void))
				_setMovePoints = null;
		}
		if (_setMovePoints == null)
		{
			fail = "set-move-points unresolved on " + type.Name + " (HomecomingBoatTravel.MovePointControllerSetWorldMovePoints)";
			return false;
		}
		var before = hero.worldMovePoints;
		_setMovePoints.Invoke(controller, new object[] { target });
		var after = hero.worldMovePoints;
		if (after != target)
		{
			fail = "readback " + before + "->" + after + " is not " + target;
			return false;
		}
		return true;
	}

	/// <summary>The world hero whose logic hero is <paramref name="logicHero"/>, from the session hero registry (null when absent).</summary>
	private static object FindWorldHero(object logicHero)
	{
		if (logicHero == null || _worldHeroLogicHeroProperty == null)
			return null;
		var target = logicHero is Il2CppObjectBase native ? native.Pointer : IntPtr.Zero;
		var entries = new List<object>();
		Homm3AiDriverLogicHeroRegistry.CopyEntriesTo(entries);
		foreach (var entry in entries)
		{
			try
			{
				if (entry == null || !_worldHeroLogicHeroProperty.DeclaringType.IsInstanceOfType(entry))
					continue;
				var candidate = _worldHeroLogicHeroProperty.GetValue(entry);
				if (candidate == null)
					continue;
				if (ReferenceEquals(candidate, logicHero) || (target != IntPtr.Zero && candidate is Il2CppObjectBase c && c.Pointer == target))
					return entry;
			}
			catch
			{
				// A stale registry row: skip it.
			}
		}
		return null;
	}

	// ---------------------------------------------------------------- helpers

	/// <summary>The hero's data side: the shared logic-hero -> data-root path, else the live side the day-start hook
	/// recorded for the data hero's sideId (that hook does not fire on day 1).</summary>
	private static bool TryResolveHeroSide(object logicHero, out object dataSide, out string failReason)
	{
		if (Homm3CustomFactionLawRuntime.TryResolveDataSideFromLogicHeroExplained(logicHero, out dataSide, out var pathFail))
		{
			failReason = null;
			return true;
		}
		var dataHero = ResolveDataHero(logicHero);
		if (dataHero != null && Homm3SwashbucklerGoldHook.TryGetDayStartSide(dataHero.sideId, out var side))
		{
			dataSide = side;
			failReason = null;
			if (!_loggedSideFallback)
			{
				_loggedSideFallback = true;
				LogEvent("hero side via the day-start side cache (side=" + dataHero.sideId + "; shared path: " + pathFail + ").");
			}
			return true;
		}
		dataSide = null;
		failReason = pathFail + "; day-start side cache has no side " + (dataHero == null ? "?" : dataHero.sideId.ToString());
		return false;
	}

	private static bool _loggedSideFallback;

	private static bool TryAddGold(object logicHero, int gold, out int before, out string failReason)
	{
		before = 0;
		if (!TryResolveHeroSide(logicHero, out var dataSide, out var sideFail))
		{
			failReason = "hero side unresolved (" + sideFail + ")";
			return false;
		}
		if (!Homm3RewardEconomyNativeAdapter.TryResolveGoldResourceFromSide(dataSide, out var goldResource, out var info, out var goldFail))
		{
			failReason = "gold resource unresolved (" + goldFail + ")";
			return false;
		}
		before = info.Value;
		if (gold <= 0)
		{
			failReason = null;
			return true;
		}
		return Homm3RewardEconomyNativeAdapter.TryAddResourceValue(goldResource, gold, out failReason);
	}

	internal static DataHero ResolveDataHero(object logicHero)
	{
		if (logicHero == null || _logicHeroDataHeroGetter == null || !_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(logicHero))
			return null;
		return _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) as DataHero;
	}

	private static bool HasSubSkill(DataHero dataHero, string sid)
	{
		return dataHero != null && Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, sid);
	}

	internal static string DescribeHero(DataHero dataHero)
	{
		if (dataHero == null)
			return "null";
		var id = ReadMember(dataHero, GameSymbols.CastleEliteStrategem.DataHeroIdMembers);
		return (dataHero.configSid ?? "?") + "#" + (id?.ToString() ?? "?");
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
		return battleLogic.GetHashCode();
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

	private static MethodInfo ResolveRequiredNamedMethod(Type type, Type returnType, Type[] parameterTypes, GameSymbols.MethodSymbol symbol, bool instance)
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
				throw new AmbiguousMatchException(symbol.Id + " matched " + matches.Count + " methods named " + name + " on " + type.FullName);
		}
		throw new MissingMethodException(symbol.Id + " exact method not found on " + (type?.FullName ?? "null"));
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

	private static void LogEvent(string message)
	{
		if (_loggedEvents++ < 80)
			_log?.LogInfo(LogPrefix + message);
	}

	private static void LogSkip(string message)
	{
		if (_loggedSkips++ < 40)
			_log?.LogWarning(LogPrefix + message);
	}
}
