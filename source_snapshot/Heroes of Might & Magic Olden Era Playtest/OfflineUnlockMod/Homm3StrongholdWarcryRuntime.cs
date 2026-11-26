using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using BattleHex = Hex.Session.Battle.Hex;
using DataHero = Hex.Session.Data.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3 Stronghold faction skill "Warcry" (skill_faction_homm3_stronghold), replacing the three Warcries hero actions.
///
/// Design (owner, 2026-11-17):
/// - The army keeps a chain going by attacking or using active abilities with every unit in turn. A plain move, a
///   wait or a skip/defend by any friendly unit breaks the chain (bonus and contributors reset).
/// - Every unit that attacked in melee during the chain is "warcrying" (a contributor). Ranged attacks and non-melee
///   abilities keep the chain alive but do not add a contributor or tick the counter (user, 2026-11-18); a shooter
///   that attacks in melee does both.
/// - When a friendly unit begins its turn after the chain was extended, the warcry bonus grows by the number of
///   contributors; the unit then has +bonus Attack for that turn. With 6 warcrying units the bonus grows by
///   6 per extension.
/// - Law pass 2026-11-25 (owner): the Warcry Attack and the Battle Tempo Initiative reach every friendly creature in the
///   Stronghold hero's army, not only Stronghold units (the former Tribes United law is retired).
/// - Advanced subskills: +10% damage on native terrain (data row only), the bonus also adds to the hero's Spell Power,
///   +2 Initiative for the round to friendly units that start a round with the warcry active.
/// - Expert subskills: a friendly retaliation makes that unit a contributor; killing an enemy stack adds 5 to the
///   bonus at once; dead allied stacks count as contributors for the rest of the battle (they survive a break).
/// - Model since 2026-11-18 (user; supersedes the growth wording above): the combo counter (WarSide.Bonus) goes up by
///   exactly 1 for each action that extends the chain. The Attack a friendly unit gets at its turn start is
///   counter x warcrying stacks x 1 / 1.5 / 2 at Basic / Advanced / Expert (rounded down), plus the flat kill bonus.
///
/// Mechanics (build 26615913): the Attack bonus is a direct write to the acting unit's live stat block
/// (<see cref="Homm3BuffDebuffNativeAdapter.TryAdjustUnitIntStat"/>), taken off when its turn ends, because buff rows
/// carry fixed stats and cannot be removed. There is no turn-start event, so the next actor is predicted from the
/// turn queue when an action ends (the bonus shows while the player plans) and confirmed or corrected at
/// ActionStarted. Committed attacks/abilities come from the token-pinned AbilityCommitExecute surface shared with
/// Bulwark Runes. The on-screen counter (<see cref="Homm3StrongholdWarcryCounter"/>) reads <see cref="TryGetCounter"/>.
///
/// Proof tier: source + build. Runtime unproven until the owner tests in game: the turn prediction, the hero Spell
/// Power write and whether +2 Initiative reorders the round are the open points; the first events of each session are
/// logged for that check.
/// </summary>
internal static class Homm3StrongholdWarcryRuntime
{
	internal const string FactionSkillSid = "skill_faction_homm3_stronghold";
	internal const string FactionSid = "homm3_stronghold";
	internal const string NativeTerrainSid = "sub_skill_faction_homm3_stronghold_1";
	internal const string SpellPowerSid = "sub_skill_faction_homm3_stronghold_2";
	internal const string InitiativeSid = "sub_skill_faction_homm3_stronghold_6";
	internal const string RetaliationSid = "sub_skill_faction_homm3_stronghold_4";
	internal const string KillBonusSid = "sub_skill_faction_homm3_stronghold_5";
	internal const string DeadAlliesSid = "sub_skill_faction_homm3_stronghold_3";
	/// <summary>Must match KILL_BONUS / ROUND_INITIATIVE in homm3_stronghold_warcry_core_overlay.py.</summary>
	internal const int KillBonus = 5;
	internal const int RoundInitiative = 2;

	private static class Pins
	{
		private static string At(string[] names, int index) => names != null && names.Length > index ? names[index] : "";
		internal static string[] BattleLogicTypes => GameSymbols.InfernoGating.BattleLogicTypeHints;
		internal static string LogicBattleClone => At(GameSymbols.InfernoGating.LogicBattleCloneMembers, 0);
		internal static string LogicGrid => At(GameSymbols.InfernoGating.LogicGridMembers, 0);
		internal static string LogicHubs => At(GameSymbols.InfernoGating.LogicHubsMembers, 0);
		internal static string LogicState => At(GameSymbols.InfernoGating.LogicStateMembers, 0);
		internal static string LogicQueue => At(GameSymbols.InfernoGating.LogicQueueMembers, 0);
		internal static string QueueToAct => At(GameSymbols.InfernoGating.QueueToActMembers, 0);
		internal static string HubsRoundHub => At(GameSymbols.InfernoGating.HubsRoundHubMembers, 0);
		internal static string StateSideWrappers => At(GameSymbols.InfernoGating.StateSideWrappersMembers, 0);
		internal static string SideWrapperTransferSide => At(GameSymbols.InfernoGating.SideWrapperTransferSideMembers, 0);
		internal static string GridHexes => At(GameSymbols.InfernoGating.GridHexesMembers, 0);
		internal static string FieldObjectSide => At(GameSymbols.InfernoGating.FieldObjectSideMembers, 0);
	}

	private sealed class Grant
	{
		internal Unit Unit;
		internal long Key;
		internal int Amount;
		internal int Growth;
		internal bool PendingBefore;
		internal int Before;
	}

	private sealed class StatLoan
	{
		internal Unit Unit;
		internal int Amount;
		internal int Before;
	}

	private sealed class SpellPowerSlot
	{
		internal object Hero;
		internal string StatMember;
		internal int Base;
	}

	internal sealed class WarSide
	{
		internal int SideIndex;
		internal int Rank;
		internal bool SpellPower;
		internal bool Initiative;
		internal bool Retaliation;
		internal bool Kill;
		internal bool DeadAllies;
		// law pass 2026-11-21: faction law levels, read once when the side is armed (Homm3StrongholdLawHooks).
		/// <summary>Drums of Krewlod (#5): starting counter 0/1/2.</summary>
		internal int DrumsStart;
		/// <summary>Smouldering Rage (#9): share of the counter a break keeps, 0/25/50 %.</summary>
		internal int SmoulderPct;
		/// <summary>law pass 2026-11-25: Unending Warcry (#13): 0 or 1; when 1, waiting or defending no longer breaks the chain.</summary>
		internal int Unending;
		/// <summary>law pass 2026-11-25: Unending Warcry (#13): the unit whose wait/defend the law held this action, so its
		/// ActionEnded does not defer a break either. Cleared when the next action starts.</summary>
		internal long WaitHeldKey;
		internal string HeroDescription;
		internal IntPtr SideWrapperPointer;
		internal object TransferSide;

		/// <summary>Combo counter: +1 for each action that extends the chain. See <see cref="AttackBonus"/>.</summary>
		internal int Bonus;
		/// <summary>Flat Attack from destroyed enemy stacks (Blood Rush), lost when the chain breaks.</summary>
		internal int KillFlat;
		internal int DisplayAttack;
		/// <summary>The chain was extended since the bonus last grew; the next friendly turn start grows it.</summary>
		internal bool Pending;
		internal readonly Dictionary<long, Unit> Contributors = new();
		internal readonly Dictionary<long, Unit> Dead = new();
		internal readonly HashSet<long> KillsCounted = new();
		internal long ActingKey;
		internal bool Extended;
		/// <summary>Counter ticks already given for hits in the current action (the first target only, so a double
		/// strike ticks twice and an area attack once).</summary>
		internal int HitTicks;
		internal long HitTarget;
		/// <summary>The acting unit's committed attack is a shot (or other non-melee attack): its hits keep the chain
		/// alive but do not tick the counter (user, 2026-11-18: ranged units were adding to the warcry).</summary>
		internal bool ActingShot;
		/// <summary>A unit ended an action without attacking. A hero ability or spell cast during a unit's turn is
		/// reported as an ActionEnded for that unit (2026-11-18 log: skill_warrior_ability during wolf rider turns), so the
		/// break waits: it is dropped if the same unit acts again, and lands when anyone else acts or the round ends.</summary>
		internal long DeferredBreakKey;
		internal string DeferredBreakReason;

		internal int DisplayValue;
		internal int DisplayContributors;
		internal int ChangeSerial;
		internal int BreakSerial;
	}

	private sealed class SideState
	{
		internal WarSide Side;
		internal Grant Grant;
		internal readonly List<StatLoan> InitiativeLoans = new();
		internal List<SpellPowerSlot> SpellPowerSlots;
		internal bool SpellPowerLogged;
	}

	private sealed class BattleState
	{
		internal object Logic;
		internal IntPtr LogicPointer;
		internal IntPtr HubPointer;
		internal readonly List<SideState> Sides = new();
		internal int Round;
		internal bool Ended;
	}

	internal struct CounterSnapshot
	{
		internal bool Active;
		internal int Value;
		internal int Contributors;
		/// <summary>Attack a Stronghold unit starting its turn now would get.</summary>
		internal int Attack;
		internal int ChangeSerial;
		internal int BreakSerial;
	}

	private static readonly object Gate = new();
	private static readonly List<BattleState> Battles = new();
	private static ManualLogSource _log;
	private static bool _attempted;
	private static bool _registered;
	private static int _logged;
	private static int _events;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static WarSide _displaySide;
	private static BattleState _displayBattle;

	internal static bool Registered => _registered;

	// ------------------------------------------------------------------ registration

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		// law pass 2026-11-25: War Festival (#33) weekly Gold; independent of the battle surfaces below.
		Homm3StrongholdLawHooks.TryRegisterWarFestival(harmony, log);
		var hexAssembly = typeof(TransferBattle).Assembly;
		try
		{
			var logicHeroType = hexAssembly.GetType(GameSymbols.CastleEliteStrategem.LogicHeroTypeName)
			                    ?? throw new TypeLoadException("Missing Hex.Session.Logic.Hero");
			_logicHeroDataHeroGetter = RequireMethod(logicHeroType, GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter.NameHints, typeof(DataHero), Type.EmptyTypes);
			var logicType = ResolveTypeByHints(hexAssembly, Pins.BattleLogicTypes, "homm3.stronghold.warcry.battleLogic");
			var init = logicType.GetMethod("Init", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
				           new[] { typeof(int), typeof(TransferBattle), typeof(bool), typeof(bool) }, null)
			           ?? throw new MissingMethodException("BattleLogic.Init(int, TransferBattle, bool, bool)");
			foreach (var name in new[] { Pins.LogicBattleClone, Pins.LogicGrid, Pins.LogicHubs, Pins.LogicState, Pins.LogicQueue })
				RequireProperty(logicType, name);
			var hubType = RequireProperty(RequireProperty(logicType, Pins.LogicHubs).PropertyType, Pins.HubsRoundHub).PropertyType;
			var roundStarted = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.RoundStartedDispatcher);
			var actionStarted = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.ActionStartedDispatcher);
			var actionEnded = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.ActionEndedDispatcher);
			var skip = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.SkipDispatcher);
			var wait = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.WaitDispatcher);
			var commitType = Homm3BulwarkRunesRuntime.ResolveAbilityRuntimeType()
			                 ?? throw new TypeLoadException("ability runtime type not found");
			var commit = Homm3BulwarkRunesRuntime.ResolveAbilityCommitExecuteMethod(commitType)
			             ?? throw new MissingMethodException("token-pinned AbilityCommitExecute not found");
			if (roundStarted == null || actionStarted == null || actionEnded == null || skip == null || wait == null)
				throw new MissingMethodException("a battle round-hub dispatcher (round/action/skip/wait) was not resolved");
			Patch(harmony, init, nameof(PostfixBattleLogicInit));
			Patch(harmony, roundStarted, nameof(PostfixRoundStarted));
			Patch(harmony, actionStarted, nameof(PostfixActionStarted));
			Patch(harmony, actionEnded, nameof(PostfixActionEnded));
			Patch(harmony, skip, nameof(PostfixSkipOrWait));
			Patch(harmony, wait, nameof(PostfixSkipOrWait));
			Patch(harmony, commit, nameof(PostfixAbilityCommitExecute));
			PatchPrefix(harmony, commit, nameof(PrefixAbilityCommitExecute));
			_registered = true;
			_log?.LogInfo("HoMM3 Stronghold Warcry [chain] registered: Init sides, round/action/skip/wait dispatchers, ability commit.");
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Stronghold Warcry [chain] NOT registered (fail closed: no chain, no bonus): " + ex.GetBaseException().Message);
			return;
		}

		// Optional surfaces: failure only drops the effects that need them.
		try
		{
			var logicType = ResolveTypeByHints(hexAssembly, Pins.BattleLogicTypes, "homm3.stronghold.warcry.battleLogic");
			var hubType = RequireProperty(RequireProperty(logicType, Pins.LogicHubs).PropertyType, Pins.HubsRoundHub).PropertyType;
			var damage = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.ObjectTookDamageDispatcher)
			             ?? throw new MissingMethodException("ObjectTookDamage dispatcher");
			Patch(harmony, damage, nameof(PostfixObjectTookDamage));
			_log?.LogInfo("HoMM3 Stronghold Warcry [deaths] registered: kill bonus and dead-ally contributors.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Stronghold Warcry [deaths] NOT registered (no kill bonus, no dead-ally contributors): " + ex.GetBaseException().Message);
		}
		try
		{
			var logicType = ResolveTypeByHints(hexAssembly, Pins.BattleLogicTypes, "homm3.stronghold.warcry.battleLogic");
			var hubType = RequireProperty(RequireProperty(logicType, Pins.LogicHubs).PropertyType, Pins.HubsRoundHub).PropertyType;
			var roundEnded = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.RoundEndedDispatcher)
			                 ?? throw new MissingMethodException("RoundEnded dispatcher");
			Patch(harmony, roundEnded, nameof(PostfixRoundEnded));
			_log?.LogInfo("HoMM3 Stronghold Warcry [initiative] registered: +" + RoundInitiative + " Initiative at round end for the next round.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Stronghold Warcry [initiative] NOT registered (no round Initiative): " + ex.GetBaseException().Message);
		}
		try
		{
			// The game rebuilds a unit's stat block from its modifier list mid-turn (2026-11-18 log: an orc's +4 Attack
			// was gone when its hit landed), wiping the direct writes. Re-add live loans to every rebuilt block.
			var rebuild = FindStatRebuild() ?? throw new MissingMethodException("Unit UnitStat(List<modifier>, bool, bool) rebuild");
			Patch(harmony, rebuild, nameof(PostfixUnitStatRebuild));
			_log?.LogInfo("HoMM3 Stronghold Warcry [stat rebuild] registered on Unit." + rebuild.Name + ": loans survive stat rebuilds.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Stronghold Warcry [stat rebuild] NOT registered (a mid-turn stat rebuild drops the Attack bonus): " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Unit's private UnitStat builder: returns UnitStat, takes (List&lt;modifier&gt;, bool, bool). Matched by shape.</summary>
	private static MethodInfo FindStatRebuild()
	{
		MethodInfo found = null;
		foreach (var method in typeof(Unit).GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (method.ReturnType != typeof(UnitStat) || method.IsSpecialName)
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != 3 || !parameters[0].ParameterType.IsGenericType
			    || parameters[1].ParameterType != typeof(bool) || parameters[2].ParameterType != typeof(bool))
				continue;
			if (found != null)
				throw new AmbiguousMatchException("two UnitStat rebuild candidates: " + found.Name + ", " + method.Name);
			found = method;
		}
		return found;
	}

	private static int _rebuildLogs;

	private static void PostfixUnitStatRebuild(Unit __instance, UnitStat __result)
	{
		try
		{
			if (__instance == null || __result == null || __instance.Pointer == IntPtr.Zero)
				return;
			var pointer = __instance.Pointer;
			int offence = 0, initiative = 0;
			lock (Gate)
			{
				if (Battles.Count == 0)
					return;
				foreach (var battle in Battles)
				{
					if (battle.Ended)
						continue;
					foreach (var state in battle.Sides)
					{
						if (state.Grant != null && state.Grant.Amount != 0 && state.Grant.Unit != null && state.Grant.Unit.Pointer == pointer)
							offence += state.Grant.Amount;
						foreach (var loan in state.InitiativeLoans)
						{
							if (loan.Unit != null && loan.Unit.Pointer == pointer)
								initiative += loan.Amount;
						}
					}
				}
			}
			if (offence == 0 && initiative == 0)
				return;
			Homm3BuffDebuffNativeAdapter.TryAdjustStatBlockInt(__result, "offence", offence, out var offenceNow);
			Homm3BuffDebuffNativeAdapter.TryAdjustStatBlockInt(__result, "initiative", initiative, out var initiativeNow);
			if (_rebuildLogs++ < 60)
				LogEvent("stat rebuild on " + Describe(__instance) + ": re-added Attack +" + offence + " (now " + offenceNow + ")"
				         + (initiative != 0 ? ", Initiative +" + initiative + " (now " + initiativeNow + ")" : ""));
		}
		catch (Exception ex)
		{
			LogLimited("stat rebuild re-add failed: " + ex.GetBaseException().Message);
		}
	}

	// ------------------------------------------------------------------ public queries

	/// <summary>State for the on-screen counter: the Warcry side that changed last in the live battle.</summary>
	internal static bool TryGetCounter(out CounterSnapshot snapshot)
	{
		snapshot = default;
		if (!_registered)
			return false;
		lock (Gate)
		{
			var side = _displaySide;
			if (side == null || _displayBattle == null || _displayBattle.Ended)
				return false;
			snapshot.Active = true;
			snapshot.Value = side.DisplayValue;
			snapshot.Contributors = side.DisplayContributors;
			snapshot.Attack = side.DisplayAttack;
			snapshot.ChangeSerial = side.ChangeSerial;
			snapshot.BreakSerial = side.BreakSerial;
			return true;
		}
	}

	/// <summary>Called by the shared battle-result prefix: the battle is over, drop loans and hide the counter.</summary>
	internal static void ObserveBeforeBattleResult(object battleLogic)
	{
		if (!_registered)
			return;
		try
		{
			var pointer = (battleLogic as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
			List<BattleState> ended = new();
			lock (Gate)
			{
				foreach (var battle in Battles)
				{
					if (!battle.Ended && (pointer == IntPtr.Zero || battle.LogicPointer == pointer))
						ended.Add(battle);
				}
				if (ended.Count == 0)
					ended.AddRange(Battles.FindAll(b => !b.Ended));
			}
			foreach (var battle in ended)
				EndBattle(battle);
		}
		catch (Exception ex)
		{
			LogLimited("battle-result cleanup failed closed: " + ex.GetBaseException().Message);
		}
	}

	// ------------------------------------------------------------------ battle start / end

	private static void PostfixBattleLogicInit(object __instance, TransferBattle __1)
	{
		try
		{
			List<BattleState> stale;
			lock (Gate)
				stale = Battles.FindAll(b => ReferenceEquals(b.Logic, __instance));
			foreach (var old in stale)
				EndBattle(old);
			lock (Gate)
				Battles.RemoveAll(b => ReferenceEquals(b.Logic, __instance));
			if (__1?.sides == null)
				return;
			var clone = ReadProperty(__instance, Pins.LogicBattleClone) as TransferBattle;
			var hub = ReadProperty(ReadProperty(__instance, Pins.LogicHubs), Pins.HubsRoundHub) as Il2CppObjectBase;
			if (clone?.sides == null || hub == null)
				return;
			BattleState battle = null;
			for (var sideIndex = 0; sideIndex < __1.sides.Length && sideIndex < clone.sides.Length; sideIndex++)
			{
				var side = __1.sides[sideIndex];
				if (side?.logicHero == null)
					continue;
				var dataHero = ResolveDataHero(side.logicHero);
				var rank = Math.Max(Homm3DungeonDraconicDominionHook.ResolveHeroSkillRank(dataHero, FactionSkillSid),
					Homm3DungeonDraconicDominionHook.ResolveHeroSkillRank(dataHero, "arena_" + FactionSkillSid));
				if (rank <= 0)
					continue;
				var wrapper = FindSideWrapper(__instance, clone.sides[sideIndex]) as Il2CppObjectBase;
				if (wrapper == null)
				{
					_log?.LogError("HoMM3 Stronghold Warcry: side wrapper for " + (dataHero?.configSid ?? "?") + " side " + sideIndex + " not found; no chain.");
					continue;
				}
				var war = new WarSide
				{
					SideIndex = sideIndex,
					Rank = Math.Min(3, rank),
					SpellPower = HasSubSkill(dataHero, SpellPowerSid),
					Initiative = HasSubSkill(dataHero, InitiativeSid),
					Retaliation = HasSubSkill(dataHero, RetaliationSid),
					Kill = HasSubSkill(dataHero, KillBonusSid),
					DeadAllies = HasSubSkill(dataHero, DeadAlliesSid),
					HeroDescription = (dataHero?.configSid ?? "?") + " side " + sideIndex,
					SideWrapperPointer = wrapper.Pointer,
					TransferSide = clone.sides[sideIndex],
				};
				// law pass 2026-11-21: Drums of Krewlod (#5), Smouldering Rage (#9).
				// law pass 2026-11-25: Unending Warcry (#13) (Tribes United retired: the Warcry reaches every friendly creature).
				// Rank 0 (law not taken or unreadable) keeps the current behaviour.
				war.DrumsStart = Math.Min(2, Homm3StrongholdLawHooks.Rank(Homm3StrongholdLawHooks.DrumsOfKrewlod, side, side.logicHero));
				war.SmoulderPct = Homm3StrongholdLawHooks.Level(Homm3StrongholdLawHooks.SmoulderPercentByLevel,
					Homm3StrongholdLawHooks.Rank(Homm3StrongholdLawHooks.SmoulderingRage, side, side.logicHero));
				war.Unending = Homm3StrongholdLawHooks.Rank(Homm3StrongholdLawHooks.UnendingWarcry, side, side.logicHero) > 0 ? 1 : 0;
				war.Bonus = war.DrumsStart; // contributors start empty: the counter turns into Attack only once a stack joins in melee
				battle ??= new BattleState { Logic = __instance, LogicPointer = (__instance as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero, HubPointer = hub.Pointer };
				battle.Sides.Add(new SideState { Side = war });
				_log?.LogInfo("HoMM3 Stronghold Warcry armed for " + war.HeroDescription + " rank " + war.Rank
				              + (war.SpellPower ? " +SpellPower" : "") + (war.Initiative ? " +Initiative" : "") + (war.Retaliation ? " +Retaliation" : "")
				              + (war.Kill ? " +KillBonus" : "") + (war.DeadAllies ? " +DeadAllies" : "")
				              + (war.DrumsStart > 0 ? " law:Drums=" + war.DrumsStart : "") + (war.SmoulderPct > 0 ? " law:Smoulder=" + war.SmoulderPct + "%" : "")
				              + (war.Unending > 0 ? " law:Unending" : "") + ".");
			}
			if (battle == null)
				return;
			lock (Gate)
			{
				Battles.Add(battle);
				while (Battles.Count > 6)
					Battles.RemoveAt(0);
				_displayBattle = battle;
				_displaySide = battle.Sides[0].Side;
			}
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Stronghold Warcry Init postfix failed closed (no chain this battle): " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Main or arena variant of a subskill.</summary>
	private static bool HasSubSkill(DataHero hero, string sid)
		=> Homm3DungeonDraconicDominionHook.HasHeroSubSkill(hero, sid) || Homm3DungeonDraconicDominionHook.HasHeroSubSkill(hero, "arena_" + sid);

	private static void EndBattle(BattleState battle)
	{
		if (battle == null || battle.Ended)
			return;
		battle.Ended = true;
		foreach (var state in battle.Sides)
		{
			try
			{
				RevokeGrant(state);
				ReturnInitiative(state);
				state.Side.Bonus = 0;
				state.Side.KillFlat = 0;
				ApplySpellPower(state);
			}
			catch (Exception ex)
			{
				LogLimited("end-of-battle cleanup failed for " + state.Side.HeroDescription + ": " + ex.GetBaseException().Message);
			}
		}
	}

	// ------------------------------------------------------------------ round events

	private static void PostfixRoundStarted(object __instance, object[] __args)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			if (battle == null || __args == null || __args.Length < 2 || __args[1] is not BattleEventArgs args)
				return;
			battle.Round = args.roundNumber;
			var first = AsUnit(args.target);
			LogEvent("RoundStarted " + args.roundNumber + " first=" + Describe(first));
			if (first != null)
				BeginTurn(battle, first, predicted: true);
		}
		catch (Exception ex)
		{
			LogLimited("RoundStarted handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Round end: last round's Initiative comes off, then friendly units get it for the next round while the warcry is active.</summary>
	private static void PostfixRoundEnded(object __instance)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			if (battle == null)
				return;
			List<(Unit Unit, IntPtr Side)> units = null;
			foreach (var state in battle.Sides)
			{
				ResolveDeferredBreak(battle, state, 0);
				ReturnInitiative(state);
				var side = state.Side;
				if (!side.Initiative || (side.Bonus <= 0 && !side.Pending))
					continue;
				units ??= LivingUnits(battle);
				var count = 0;
				foreach (var (unit, sidePointer) in units)
				{
					// law pass 2026-11-25: Battle Tempo reaches every friendly creature (no Stronghold gate).
					if (sidePointer != side.SideWrapperPointer)
						continue;
					if (!Homm3BuffDebuffNativeAdapter.TryAdjustUnitIntStat(unit, "initiative", RoundInitiative, out var before, out _, out var fail))
					{
						LogLimited("round Initiative failed on " + Describe(unit) + ": " + fail);
						continue;
					}
					state.InitiativeLoans.Add(new StatLoan { Unit = unit, Amount = RoundInitiative, Before = before });
					count++;
				}
				LogEvent("RoundEnded: warcry active for " + side.HeroDescription + " (bonus " + side.Bonus + "), +" + RoundInitiative + " Initiative on " + count + " unit(s) for the next round");
			}
		}
		catch (Exception ex)
		{
			LogLimited("RoundEnded handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	// ------------------------------------------------------------------ action events

	private static void PostfixActionStarted(object __instance, object[] __args)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			if (battle == null || __args == null || __args.Length < 2 || __args[1] is not BattleEventArgs args)
				return;
			var unit = AsUnit(args.target);
			if (unit == null)
				return;
			var key = Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
			var state = FindSide(battle, unit);
			LogEvent("ActionStarted " + Describe(unit) + (state == null ? " (not a Warcry side)" : ""));
			foreach (var other in battle.Sides)
			{
				if (other != state)
					other.Side.ActingKey = 0;
				ResolveDeferredBreak(battle, other, other == state ? key : 0);
			}
			if (state == null)
				return;
			if (state.Side.ActingKey == key)
				return; // nested start inside the same action
			state.Side.WaitHeldKey = 0; // law pass 2026-11-25: Unending Warcry (#13): a new action starts
			BeginTurn(battle, unit, predicted: false);
			state.Side.ActingKey = key;
			state.Side.Extended = false;
			state.Side.HitTicks = 0;
			state.Side.HitTarget = 0;
			state.Side.ActingShot = false;
		}
		catch (Exception ex)
		{
			LogLimited("ActionStarted handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixActionEnded(object __instance, object[] __args)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			if (battle == null)
				return;
			var unit = __args != null && __args.Length > 1 && __args[1] is BattleEventArgs args ? AsUnit(args.target) : null;
			var key = unit == null ? 0 : Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
			var state = unit == null ? null : FindSide(battle, unit);
			if (state != null)
			{
				var side = state.Side;
				if (side.Extended)
				{
					side.DeferredBreakKey = 0;
					// hits ticked the counter as they landed; an ability that hit nothing ticks once here
					if (side.HitTicks == 0 && !side.ActingShot)
						side.Bonus++;
					LogEvent("ActionEnded " + Describe(unit) + ": chain extended (counter " + side.Bonus + ", " + CountContributors(side) + " warcrying, Attack " + AttackBonus(side) + ")");
					ApplySpellPower(state);
					Refresh(battle, state, changed: true);
				}
				else if (side.Unending > 0 && key != 0 && side.WaitHeldKey == key)
				{
					// law pass 2026-11-25: Unending Warcry (#13): the action was a wait or defend; the chain holds.
					LogEvent("ActionEnded " + Describe(unit) + ": wait/defend, the chain holds (Unending Warcry)");
				}
				else
				{
					LogEvent("ActionEnded " + Describe(unit) + ": no attack or ability (the chain breaks unless this unit attacks next)");
					side.DeferredBreakKey = key;
					side.DeferredBreakReason = "action without attack or ability by " + Describe(unit);
				}
				side.WaitHeldKey = 0;
				side.Extended = false;
				side.HitTicks = 0;
				side.HitTarget = 0;
				side.ActingShot = false;
				side.ActingKey = 0;
				RevokeGrant(state);
				Refresh(battle, state, changed: false);
			}
			PredictNext(battle, key);
		}
		catch (Exception ex)
		{
			LogLimited("ActionEnded handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixSkipOrWait(object __instance, object[] __args)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			if (battle == null || __args == null || __args.Length < 2 || __args[1] is not BattleEventArgs args)
				return;
			var unit = AsUnit(args.target);
			var state = unit == null ? null : FindSide(battle, unit);
			if (state == null)
				return;
			// A unit that already used an ability in this action (one that does not end its turn) and then waits or
			// defends has acted: the chain holds and ActionEnded extends it.
			var key = Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
			if (state.Side.Extended && key != 0 && state.Side.ActingKey == key)
			{
				LogEvent("Skip/Wait " + Describe(unit) + " after its ability: the chain holds");
				return;
			}
			if (state.Side.Unending > 0)
			{
				// law pass 2026-11-25: Unending Warcry (#13): waiting or defending no longer breaks the Warcry. The counter
				// does not grow either; a plain move without an attack still breaks it.
				LogEvent("Skip/Wait " + Describe(unit) + ": the chain holds (Unending Warcry)");
				if (key != 0 && state.Side.DeferredBreakKey == key)
					state.Side.DeferredBreakKey = 0;
				state.Side.WaitHeldKey = key;
				return;
			}
			LogEvent("Skip/Wait " + Describe(unit));
			state.Side.Extended = false;
			state.Side.DeferredBreakKey = 0;
			Break(state, "wait or skip by " + Describe(unit));
		}
		catch (Exception ex)
		{
			LogLimited("Skip/Wait handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixAbilityCommitExecute(object __instance)
	{
		try
		{
			bool any;
			lock (Gate)
				any = Battles.Exists(b => !b.Ended);
			if (!any || !Homm3BulwarkRunesRuntime.TryReadCommittedAbility(__instance, out var casterObject, out var abilityType, out _, out _))
				return;
			var caster = AsUnit(casterObject);
			if (caster == null || !TryFindSide(caster, out var battle, out var state))
				return;
			var side = state.Side;
			var key = Homm3DirectStateIdentity.ResolveKeyOrZero(caster);
			if (key == 0)
				return;
			if (abilityType == EAbilityType.CounterAttack)
			{
				if (side.Retaliation && AddContributor(side, caster, key))
				{
					LogEvent("retaliation by " + Describe(caster) + ": joins the warcry (" + CountContributors(side) + " warcrying)");
					Refresh(battle, state, changed: true);
				}
				return;
			}
			if (side.ActingKey != 0 && side.ActingKey != key)
				return; // a triggered ability outside the unit's own action
			if (!TryClassifyCommit(__instance, caster, abilityType, out var melee, out var attackType))
				return;
			side.Extended = true;
			var refunded = 0;
			var shot = IsShot(melee, attackType, abilityType);
			if (shot)
				side.ActingShot = true;
			if (shot && side.HitTicks > 0)
			{
				// The prefix should already have kept a shot's hits off the counter; take back any that slipped through.
				refunded = side.HitTicks;
				side.Bonus = Math.Max(0, side.Bonus - refunded);
				side.HitTicks = 0;
			}
			var joined = melee && AddContributor(side, caster, key);
			LogEvent("commit " + abilityType + " by " + Describe(caster) + " attackType=" + (attackType ?? "<none>") + (melee ? " melee" : " not melee")
				+ (joined ? ": joins the warcry" : "") + (refunded > 0 ? ": " + refunded + " shot tick(s) taken back, counter " + side.Bonus : ""));
			if (joined || refunded > 0)
				Refresh(battle, state, changed: true);
		}
		catch (Exception ex)
		{
			LogLimited("ability commit handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Before the committed attack resolves: mark a shot so its hits do not tick the counter.</summary>
	private static void PrefixAbilityCommitExecute(object __instance)
	{
		try
		{
			bool any;
			lock (Gate)
				any = Battles.Exists(b => !b.Ended);
			if (!any || !Homm3BulwarkRunesRuntime.TryReadCommittedAbility(__instance, out var casterObject, out var abilityType, out _, out _))
				return;
			var caster = AsUnit(casterObject);
			if (caster == null || !TryFindSide(caster, out _, out var state))
				return;
			var key = Homm3DirectStateIdentity.ResolveKeyOrZero(caster);
			if (key == 0 || state.Side.ActingKey != key)
				return;
			if (TryClassifyCommit(__instance, caster, abilityType, out var melee, out var attackType))
				state.Side.ActingShot = IsShot(melee, attackType, abilityType);
		}
		catch (Exception ex)
		{
			LogLimited("ability commit prefix failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>A non-melee attack (a shooter's shot, a ranged attack ability). Abilities with no attack type, such as
	/// buffs, are not shots: they still tick the counter once at the end of the action.</summary>
	private static bool IsShot(bool melee, string attackType, EAbilityType abilityType)
		=> !melee && (!string.IsNullOrWhiteSpace(attackType) || abilityType != EAbilityType.Ability);

	/// <summary>False for commits that are not the unit's attack or active ability (moves, retaliations, passives).</summary>
	private static bool TryClassifyCommit(object commit, Unit caster, EAbilityType abilityType, out bool melee, out string attackType)
	{
		melee = false;
		attackType = null;
		if (abilityType != EAbilityType.DefaultAttack && abilityType != EAbilityType.AlternativeAttack && abilityType != EAbilityType.Ability)
			return false;
		var logic = Homm3TowerArtificingRuntime.ReadMember(commit, GameSymbols.BulwarkRunesLaws.AbilityRuntimeLogicConfigMembers);
		attackType = ReadString(logic, GameSymbols.BulwarkRunesLaws.AbilityLogicAttackTypeMembers);
		if (abilityType == EAbilityType.Ability)
		{
			var moveType = ReadString(logic, GameSymbols.BulwarkRunesLaws.AbilityLogicMoveTypeMembers);
			var castType = ReadString(logic, GameSymbols.BulwarkRunesLaws.AbilityLogicCastTypeMembers);
			if (!string.IsNullOrWhiteSpace(moveType) && string.IsNullOrWhiteSpace(attackType) && string.IsNullOrWhiteSpace(castType))
				return false; // movement-only ability: a move, it does not keep the chain
		}
		if (!string.IsNullOrWhiteSpace(attackType))
			melee = attackType.Trim().Equals("melee", StringComparison.OrdinalIgnoreCase);
		else
			melee = abilityType != EAbilityType.Ability && !Homm3FortressPredatorInstinctRuntime.IsRanged(caster);
		return true;
	}

	private static void PostfixObjectTookDamage(object __instance, object[] __args)
	{
		using var timing = Homm3LoadTiming.Scope("battle damage.warcry", Homm3LoadTiming.BattleScopeMinMs);
		try
		{
			var battle = FindBattleByHub(__instance);
			if (battle == null || __args == null || __args.Length < 2)
				return;
			if (!Homm3BattleEventNativeAdapter.TryReadDamageEvent(__args[1], out var info, out _))
				return;
			var receiver = AsUnit(info.Receiver);
			if (receiver == null)
				return;
			var receiverKey = Homm3DirectStateIdentity.ResolveKeyOrZero(receiver);
			if (receiverKey == 0)
				return;
			var receiverSide = SidePointer(receiver);
			var caster = AsUnit(info.Caster);
			var casterSide = caster == null ? IntPtr.Zero : SidePointer(caster);
			var casterKey = caster == null ? 0 : Homm3DirectStateIdentity.ResolveKeyOrZero(caster);
			// Point of contact: each hit the acting unit lands on its first target ticks the counter (user, 2026-11-18),
			// so a double strike counts twice and the number moves with the blow, not after the retaliation.
			if (casterKey != 0 && receiverSide != casterSide)
			{
				foreach (var state in battle.Sides)
				{
					var side = state.Side;
					if (casterSide != side.SideWrapperPointer || side.ActingKey != casterKey)
						continue;
					if (side.HitTarget == 0)
						side.HitTarget = receiverKey;
					if (side.HitTarget != receiverKey)
						continue;
					if (side.ActingShot)
					{
						side.Extended = true;
						side.DeferredBreakKey = 0;
						LogEvent("shot by " + Describe(caster) + " on " + Describe(receiver) + ": keeps the chain, counter stays " + side.Bonus);
						continue;
					}
					side.Bonus++;
					side.HitTicks++;
					side.Extended = true;
					side.DeferredBreakKey = 0;
					Homm3BuffDebuffNativeAdapter.TryAdjustUnitIntStat(caster, "offence", 0, out var offenceNow, out _, out _);
					LogEvent("hit " + side.HitTicks + " by " + Describe(caster) + " on " + Describe(receiver) + ": counter " + side.Bonus
						+ "; attacker Attack stat now " + offenceNow + " (granted +" + (state.Grant?.Amount ?? 0) + " over " + (state.Grant?.Before ?? 0) + ")");
					ApplySpellPower(state);
					Refresh(battle, state, changed: true);
				}
			}
			if (Homm3FortressPredatorInstinctRuntime.IsAlive(receiver))
				return;
			foreach (var state in battle.Sides)
			{
				var side = state.Side;
				if (receiverSide == side.SideWrapperPointer)
				{
					if (side.Dead.ContainsKey(receiverKey))
						continue;
					side.Dead[receiverKey] = receiver;
					side.Contributors.Remove(receiverKey);
					LogEvent("allied stack " + Describe(receiver) + " died" + (side.DeadAllies ? ": contributes for the rest of the battle" : ""));
					Refresh(battle, state, changed: side.DeadAllies);
				}
				else if (side.Kill && casterSide == side.SideWrapperPointer && side.KillsCounted.Add(receiverKey))
				{
					side.KillFlat += KillBonus;
					var grant = state.Grant;
					if (grant != null && grant.Amount > 0 && Homm3BuffDebuffNativeAdapter.TryAdjustUnitIntStat(grant.Unit, "offence", KillBonus, out _, out _, out _))
						grant.Amount += KillBonus;
					LogEvent(Describe(caster) + " destroyed " + Describe(receiver) + ": Attack +" + KillBonus + " -> " + AttackBonus(side));
					ApplySpellPower(state);
					Refresh(battle, state, changed: true);
				}
			}
		}
		catch (Exception ex)
		{
			LogLimited("damage handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	// ------------------------------------------------------------------ chain state

	/// <summary>Next actor from the turn queue (skipping the unit that just acted); a friendly one begins its turn now.</summary>
	private static void PredictNext(BattleState battle, long justActedKey)
	{
		var queue = ReadProperty(battle.Logic, Pins.LogicQueue);
		if (queue == null || ReadProperty(queue, Pins.QueueToAct) is not Il2CppSystem.Collections.Generic.List<Unit> toAct)
			return;
		for (var i = 0; i < toAct.Count; i++)
		{
			var unit = toAct[i];
			if (unit == null || !Homm3FortressPredatorInstinctRuntime.IsAlive(unit))
				continue;
			if (Homm3DirectStateIdentity.ResolveKeyOrZero(unit) == justActedKey)
				continue;
			BeginTurn(battle, unit, predicted: true);
			return;
		}
	}

	/// <summary>
	/// A friendly unit begins its turn: the bonus grows by the contributor count when the chain was extended since the
	/// last growth, and the unit gets the bonus as Attack. A wrong prediction is undone first.
	/// </summary>
	private static void BeginTurn(BattleState battle, Unit unit, bool predicted)
	{
		var key = Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
		if (key == 0)
			return;
		var state = FindSide(battle, unit);
		foreach (var other in battle.Sides)
		{
			// Any grant that is not for this unit was a wrong prediction (or belongs to a turn that never reported its end).
			var grant = other.Grant;
			if (grant == null || (other == state && grant.Key == key))
				continue;
			other.Side.Bonus = Math.Max(0, other.Side.Bonus - grant.Growth);
			other.Side.Pending = grant.PendingBefore || other.Side.Pending;
			LogEvent("turn prediction corrected: " + Describe(grant.Unit) + " did not act next; bonus back to " + other.Side.Bonus);
			RevokeGrant(other);
			ApplySpellPower(other);
			Refresh(battle, other, changed: false);
		}
		if (state == null || state.Grant != null)
			return;
		var side = state.Side;
		var pendingBefore = side.Pending;
		const int growth = 0; // the counter grows when an action extends the chain, not at turn start
		var bonus = AttackBonus(side);
		// law pass 2026-11-25: every friendly creature receives the Warcry Attack (owner: the Warcry works natively with
		// non-Stronghold units; the Tribes United law that lifted this gate is retired).
		var amount = bonus > 0 ? bonus : 0;
		var before = 0;
		if (amount > 0 && !Homm3BuffDebuffNativeAdapter.TryAdjustUnitIntStat(unit, "offence", amount, out before, out _, out var fail))
		{
			LogLimited("Attack bonus failed on " + Describe(unit) + ": " + fail);
			amount = 0;
		}
		state.Grant = new Grant { Unit = unit, Key = key, Amount = amount, Growth = growth, PendingBefore = pendingBefore, Before = before };
		if (bonus > 0)
			LogEvent((predicted ? "turn (predicted) " : "turn ") + Describe(unit) + ": counter " + side.Bonus + " x " + CountContributors(side) + " warcrying -> " + bonus + ", Attack +" + amount);
		ApplySpellPower(state);
		Refresh(battle, state, changed: false);
	}

	private static void RevokeGrant(SideState state)
	{
		var grant = state.Grant;
		state.Grant = null;
		if (grant == null || grant.Amount == 0)
			return;
		ReturnStat(grant.Unit, "offence", grant.Amount, grant.Before);
	}

	private static void ReturnInitiative(SideState state)
	{
		foreach (var loan in state.InitiativeLoans)
			ReturnStat(loan.Unit, "initiative", loan.Amount, loan.Before);
		state.InitiativeLoans.Clear();
	}

	/// <summary>Takes a loaned stat back. If the game rebuilt the stat block to its pre-loan value meanwhile, nothing is owed.</summary>
	private static void ReturnStat(Unit unit, string field, int amount, int before)
	{
		if (unit == null || unit.Pointer == IntPtr.Zero)
			return;
		if (!Homm3BuffDebuffNativeAdapter.TryAdjustUnitIntStat(unit, field, 0, out var current, out _, out var fail))
		{
			LogLimited("stat return (" + field + ") unreadable on " + Describe(unit) + ": " + fail);
			return;
		}
		if (current == before)
		{
			LogLimited(field + " on " + Describe(unit) + " was already back at " + before + " (stat block rebuilt by the game); nothing taken off.");
			return;
		}
		Homm3BuffDebuffNativeAdapter.TryAdjustUnitIntStat(unit, field, -amount, out _, out _, out _);
	}

	/// <summary>Lands a waiting break unless the unit that caused it is the one acting again.</summary>
	private static void ResolveDeferredBreak(BattleState battle, SideState state, long actingKey)
	{
		var side = state.Side;
		if (side.DeferredBreakKey == 0 || side.DeferredBreakKey == actingKey)
			return;
		side.DeferredBreakKey = 0;
		Break(state, side.DeferredBreakReason);
		Refresh(battle, state, changed: false);
	}

	private static void Break(SideState state, string reason)
	{
		var side = state.Side;
		if (side.Bonus == 0 && side.KillFlat == 0 && !side.Pending && side.Contributors.Count == 0)
			return;
		// law pass 2026-11-21: Smouldering Rage (#9) keeps 25%/50% of the counter (rounded down); Attack from kills and
		// the contributors still clear.
		var keep = side.SmoulderPct > 0 ? side.Bonus * side.SmoulderPct / 100 : 0;
		LogEvent("chain broken for " + side.HeroDescription + " (" + reason + "): counter " + side.Bonus + " lost"
		         + (keep > 0 ? ", " + keep + " kept (Smouldering Rage)" : ""));
		side.Bonus = keep;
		side.KillFlat = 0;
		side.Pending = false;
		side.Contributors.Clear();
		side.BreakSerial++;
		RevokeGrant(state);
		ApplySpellPower(state);
		BattleState battle;
		lock (Gate)
			battle = Battles.Find(b => b.Sides.Contains(state));
		Refresh(battle, state, changed: false);
	}

	private static bool AddContributor(WarSide side, Unit unit, long key)
	{
		if (side.Contributors.ContainsKey(key))
			return false;
		side.Contributors[key] = unit;
		return true;
	}

	/// <summary>Living contributors, plus every dead allied stack with the expert subskill.</summary>
	/// <summary>counter x warcrying stacks x (1, 1.5, 2 by rank), rounded down, plus the flat kill bonus.</summary>
	// law pass 2026-11-25: Unending Warcry (#13) no longer changes the multiplier (it now keeps the chain through waits/defends).
	private static int AttackBonus(WarSide side)
		=> side.Bonus * CountContributors(side) * (Math.Clamp(side.Rank, 1, 3) + 1) / 2 + side.KillFlat;

	private static int CountContributors(WarSide side)
	{
		var count = 0;
		List<long> gone = null;
		foreach (var pair in side.Contributors)
		{
			if (Homm3FortressPredatorInstinctRuntime.IsAlive(pair.Value))
				count++;
			else
				(gone ??= new List<long>()).Add(pair.Key);
		}
		if (gone != null)
		{
			foreach (var key in gone)
			{
				side.Dead[key] = side.Contributors[key];
				side.Contributors.Remove(key);
			}
		}
		return side.DeadAllies ? count + side.Dead.Count : count;
	}

	private static void Refresh(BattleState battle, SideState state, bool changed)
	{
		var side = state.Side;
		var contributors = CountContributors(side);
		var value = side.Bonus;
		lock (Gate)
		{
			if (changed || value != side.DisplayValue)
			{
				side.ChangeSerial++;
				if (battle != null && !battle.Ended)
				{
					_displayBattle = battle;
					_displaySide = side;
				}
			}
			side.DisplayValue = value;
			side.DisplayContributors = contributors;
			side.DisplayAttack = AttackBonus(side);
		}
	}

	// ------------------------------------------------------------------ hero Spell Power (best effort)

	/// <summary>Spell Power subskill: the battle copy of the hero carries base + bonus while the chain lives.</summary>
	private static void ApplySpellPower(SideState state)
	{
		var side = state.Side;
		if (!side.SpellPower)
			return;
		try
		{
			if (state.SpellPowerSlots == null)
			{
				state.SpellPowerSlots = new List<SpellPowerSlot>();
				var hero = Homm3TowerArtificingRuntime.ReadMember(side.TransferSide, GameSymbols.SkeletalNecromancy.TransferSideHeroMembers);
				foreach (var member in new[] { "heroStat", "heroStatUnclamped" })
				{
					var stat = ReadByName(hero, member);
					if (stat != null && ReadByName(stat, "spellPower") is { } raw)
						state.SpellPowerSlots.Add(new SpellPowerSlot { Hero = hero, StatMember = member, Base = Convert.ToInt32(raw) });
				}
				if (state.SpellPowerSlots.Count == 0)
					LogLimited("Spell Power subskill: hero stat block not readable for " + side.HeroDescription + "; no Spell Power bonus.");
			}
			foreach (var slot in state.SpellPowerSlots)
			{
				var stat = ReadByName(slot.Hero, slot.StatMember);
				if (stat == null)
					continue;
				var wanted = slot.Base + AttackBonus(side);
				if (ReadByName(stat, "spellPower") is { } current && Convert.ToInt32(current) == wanted)
					continue;
				var ok = WriteByName(stat, "spellPower", wanted);
				if (ok && stat.GetType().IsValueType)
					ok = WriteByName(slot.Hero, slot.StatMember, stat);
				if (!state.SpellPowerLogged)
				{
					state.SpellPowerLogged = true;
					var readBack = ReadByName(ReadByName(slot.Hero, slot.StatMember), "spellPower");
					_log?.LogInfo("HoMM3 Stronghold Warcry Spell Power: " + side.HeroDescription + " " + slot.StatMember + ".spellPower " + slot.Base + " -> " + wanted
					              + (ok ? "" : " WRITE FAILED") + " (reads back " + (readBack ?? "?") + ").");
				}
			}
		}
		catch (Exception ex)
		{
			LogLimited("Spell Power write failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static object ReadByName(object target, string name)
		=> Homm3TowerArtificingRuntime.ReadMember(target, new[] { name, "get_" + name });

	private static bool WriteByName(object target, string name, object value)
	{
		if (target == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = target.GetType();
		var property = type.GetProperty(name, flags);
		if (property != null && property.CanWrite && property.GetIndexParameters().Length == 0)
		{
			property.SetValue(target, value);
			return true;
		}
		var field = type.GetField(name, flags);
		if (field != null)
		{
			field.SetValue(target, value);
			return true;
		}
		var setter = type.GetMethod("set_" + name, flags);
		if (setter != null && setter.GetParameters().Length == 1)
		{
			setter.Invoke(target, new[] { value });
			return true;
		}
		return false;
	}

	// ------------------------------------------------------------------ helpers

	private static Unit AsUnit(object value)
	{
		if (value is Unit unit)
			return unit;
		if (value is not Il2CppObjectBase obj || obj.Pointer == IntPtr.Zero)
			return null;
		try
		{
			return obj.TryCast<Unit>();
		}
		catch
		{
			return null;
		}
	}

	private static IntPtr SidePointer(Unit unit)
		=> (ReadProperty(unit, Pins.FieldObjectSide) as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;

	private static SideState FindSide(BattleState battle, Unit unit)
	{
		var pointer = SidePointer(unit);
		if (pointer == IntPtr.Zero)
			return null;
		foreach (var state in battle.Sides)
		{
			if (state.Side.SideWrapperPointer == pointer)
				return state;
		}
		return null;
	}

	private static bool TryFindSide(Unit unit, out BattleState battle, out SideState state)
	{
		battle = null;
		state = null;
		var pointer = SidePointer(unit);
		if (pointer == IntPtr.Zero)
			return false;
		lock (Gate)
		{
			for (var i = Battles.Count - 1; i >= 0; i--)
			{
				if (Battles[i].Ended)
					continue;
				foreach (var candidate in Battles[i].Sides)
				{
					if (candidate.Side.SideWrapperPointer == pointer)
					{
						battle = Battles[i];
						state = candidate;
						return true;
					}
				}
			}
		}
		return false;
	}

	private static string UnitConfigId(Unit unit)
	{
		var config = unit?.prop_UnitLogicConfig_0;
		return config == null ? null : DeobfInteropCompat.GetConfigElementId(config)?.Trim();
	}

	/// <summary>Every living unit on the grid, once (large units cover two hexes), with its side wrapper pointer.</summary>
	private static List<(Unit Unit, IntPtr Side)> LivingUnits(BattleState battle)
	{
		var units = new List<(Unit, IntPtr)>();
		var hexes = ReadProperty(ReadProperty(battle.Logic, Pins.LogicGrid), Pins.GridHexes) as Il2CppReferenceArray<BattleHex>;
		if (hexes == null)
			return units;
		var seen = new HashSet<long>();
		foreach (var hex in hexes)
		{
			if (hex?.fieldObjects == null)
				continue;
			for (var i = 0; i < hex.fieldObjects.Count; i++)
			{
				var unit = hex.fieldObjects[i]?.TryCast<Unit>();
				if (unit == null || !Homm3FortressPredatorInstinctRuntime.IsAlive(unit))
					continue;
				var key = Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
				if (key == 0 || !seen.Add(key))
					continue;
				units.Add((unit, SidePointer(unit)));
			}
		}
		return units;
	}

	private static BattleState FindBattleByHub(object hub)
	{
		if (hub is not Il2CppObjectBase obj)
			return null;
		lock (Gate)
		{
			foreach (var battle in Battles)
			{
				if (battle.HubPointer == obj.Pointer && !battle.Ended)
					return battle;
			}
		}
		return null;
	}

	private static DataHero ResolveDataHero(object logicHero)
	{
		if (logicHero == null || _logicHeroDataHeroGetter == null || !_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(logicHero))
			return null;
		return _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) as DataHero;
	}

	private static object FindSideWrapper(object logic, TransferSide side)
	{
		var wrappers = ReadProperty(ReadProperty(logic, Pins.LogicState), Pins.StateSideWrappers);
		if (wrappers is not System.Collections.IEnumerable enumerable)
			return null;
		foreach (var wrapper in enumerable)
		{
			if (ReadProperty(wrapper, Pins.SideWrapperTransferSide) is TransferSide ts && ts.Pointer == side.Pointer)
				return wrapper;
		}
		return null;
	}

	private static string ReadString(object target, string[] names)
	{
		var raw = Homm3TowerArtificingRuntime.ReadMember(target, names);
		return raw == null ? null : raw as string ?? raw.ToString();
	}

	private static object ReadProperty(object obj, string name) => Homm3FortressPredatorInstinctRuntime.ReadProperty(obj, name);

	private static string Describe(Unit unit)
	{
		if (unit == null)
			return "<none>";
		var text = Homm3FortressPredatorInstinctRuntime.DescribeUnit(unit);
		if (!text.StartsWith("?", StringComparison.Ordinal))
			return text;
		try
		{
			// custom units have no baseSid; name them by their config id
			return (UnitConfigId(unit) ?? "?") + text.Substring(1);
		}
		catch
		{
			return text;
		}
	}

	private static Type ResolveTypeByHints(Assembly assembly, string[] hints, string id)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			if (!string.IsNullOrWhiteSpace(hint) && assembly.GetType(hint) is { } type)
				return type;
		}
		throw new TypeLoadException(id + " type not found from [" + string.Join(",", hints ?? Array.Empty<string>()) + "]");
	}

	private static PropertyInfo RequireProperty(Type type, string name)
	{
		PropertyInfo found = null;
		for (var cur = type; cur != null && found == null; cur = cur.BaseType)
			found = cur.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
		return found ?? throw new MissingMemberException((type?.FullName ?? "null") + "." + name);
	}

	private static MethodInfo RequireMethod(Type type, string[] names, Type returnType, Type[] parameterTypes)
	{
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var method = type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, parameterTypes, null);
			if (method != null && (returnType == null || method.ReturnType == returnType))
				return method;
		}
		throw new MissingMethodException((type?.FullName ?? "null") + " [" + string.Join(",", names ?? Array.Empty<string>()) + "]");
	}

	private static void Patch(Harmony harmony, MethodInfo target, string postfixName)
	{
		var postfix = typeof(Homm3StrongholdWarcryRuntime).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic)
		              ?? throw new MissingMethodException(postfixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException("postfix incompatible for " + target.DeclaringType?.FullName + "." + target.Name + ": " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static void PatchPrefix(Harmony harmony, MethodInfo target, string prefixName)
	{
		var prefix = typeof(Homm3StrongholdWarcryRuntime).GetMethod(prefixName, BindingFlags.Static | BindingFlags.NonPublic)
		             ?? throw new MissingMethodException(prefixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, prefix, out var reason))
			throw new MissingMethodException("prefix incompatible for " + target.DeclaringType?.FullName + "." + target.Name + ": " + reason);
		harmony.Patch(target, prefix: new HarmonyMethod(prefix) { priority = Priority.Last });
	}

	/// <summary>The first events of a session at Info level: the in-game check reads the chain from the log.</summary>
	private static void LogEvent(string message)
	{
		if (_events++ < 400)
			_log?.LogInfo("HoMM3 Stronghold Warcry: " + message);
	}

	private static void LogLimited(string message)
	{
		if (_logged++ < 80)
			_log?.LogWarning("HoMM3 Stronghold Warcry: " + message);
	}
}
