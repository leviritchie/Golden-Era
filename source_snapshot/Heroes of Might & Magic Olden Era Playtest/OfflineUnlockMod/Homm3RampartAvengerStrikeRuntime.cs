using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using BattleHex = Hex.Session.Battle.Hex;
using DataHero = Hex.Session.Data.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3 Rampart faction skill "Avenger" (skill_faction_homm3_rampart), reworked 2026-11-19 (owner design):
/// when an enemy attacks a stack of a Rampart hero's army, up to 1/2/3 other friendly stacks (Basic/Advanced/Expert)
/// move 0/1/2 hexes and make a support melee attack on the attacker, an avenging strike. Highest Initiative strikes
/// first and wins the slots. Avenging strikes do not generate Focus by default.
///
/// Subskills (SIDs keep their old tier slots so saves keep their picks):
/// - Advanced weakening_ray "Native Terrain": +10% damage dealt on native terrain (Core data only).
/// - Advanced fatal_decay "Rallying Fury": avenging strikes generate Focus.
/// - Advanced long_mark "Hold the Line": strikers that moved go back to their starting hex after the strike.
/// - Expert native_terrain "Volley of Vengeance": ranged stacks can take the first strike of a chain (they shoot from
///   where they stand; a ranged stack already next to the attacker hits in melee).
/// - Expert wide_mark "Swift Vengeance": avenging strikes are not retaliated against (Swift Strike).
/// - Expert focus_efficiency "Blood for Blood": enemy retaliations against the army also start a chain, except
///   retaliations against avenging strikes.
///
/// Mechanism (build 26615913 pins in <see cref="GameSymbols.RampartAvengerStrike"/>, evidence
/// V:\olden_port_work\avenger_strike): an AttackStep (eux) Begin postfix reads the attacker and its target hexes. For
/// a target on an armed side, the chain picks strikers and asks the attack builder (eqd.bhqa) to queue, per striker, a
/// free default attack with its approach path (empty when already adjacent), plus the return move (eqd.bhpr) when the
/// return pick is on. The queued steps run after the current attack sequence. Every step the chain queued is marked
/// derived, so avenging strikes and their retaliations never start another chain. Swift Strike is a prefix on the
/// counter queue (eqd.bhqp) while a chain is building; the Focus rule is a prefix on the energy grant that refuses
/// positive grants while a marked avenging AttackStep is the step queue's current step.
///
/// Every hook fails closed to the native result. Proof tier: static decompile + build; runtime unproven.
/// </summary>
internal static class Homm3RampartAvengerStrikeRuntime
{
	internal const string FactionSkillSid = "skill_faction_homm3_rampart";
	internal const string NativeTerrainSid = "sub_skill_faction_homm3_rampart_avenger_weakening_ray";
	internal const string FocusSid = "sub_skill_faction_homm3_rampart_avenger_fatal_decay";
	internal const string ReturnSid = "sub_skill_faction_homm3_rampart_avenger_long_mark";
	internal const string RangedFirstSid = "sub_skill_faction_homm3_rampart_avenger_native_terrain";
	internal const string SwiftStrikeSid = "sub_skill_faction_homm3_rampart_avenger_wide_mark";
	internal const string RetaliationTriggerSid = "sub_skill_faction_homm3_rampart_avenger_focus_efficiency";

	/// <summary>Index = skill rank. Must match STRIKERS_BY_RANK in homm3_rampart_avenger_core_overlay.py.</summary>
	internal static readonly int[] StrikersByRank = { 0, 1, 2, 3 };
	/// <summary>Index = skill rank. Must match MOVE_HEXES_BY_RANK in homm3_rampart_avenger_core_overlay.py.</summary>
	internal static readonly int[] MoveHexesByRank = { 0, 0, 1, 2 };

	private const int StatePlaying = 2;
	// Hex.Configs.EAbilityType: DefaultAttack = 1, AlternativeAttack = 3. Shooters keep their melee attack in
	// alternativeAttacks (defaultAttacks holds only the shot).
	private const int DefaultAttackAbilityType = 1;
	private const int AlternativeAttackAbilityType = 3;
	private const int MoveSourceDefault = 1;

	private static class Pins
	{
		private static string At(string[] names, int index) => names != null && names.Length > index ? names[index] : "";
		internal static string LogicState => At(GameSymbols.InfernoGating.LogicStateMembers, 0);
		internal static string LogicGrid => At(GameSymbols.InfernoGating.LogicGridMembers, 0);
		internal static string LogicBattleClone => At(GameSymbols.InfernoGating.LogicBattleCloneMembers, 0);
		internal static string StateSideWrappers => At(GameSymbols.InfernoGating.StateSideWrappersMembers, 0);
		internal static string SideWrapperTransferSide => At(GameSymbols.InfernoGating.SideWrapperTransferSideMembers, 0);
		internal static string GridHexes => At(GameSymbols.InfernoGating.GridHexesMembers, 0);
		internal static string FieldObjectSide => At(GameSymbols.InfernoGating.FieldObjectSideMembers, 0);
		internal static string UnitStat => At(GameSymbols.InfernoGating.UnitStatMembers, 0);
		internal static string LogicBuilder => At(GameSymbols.RampartAvengerStrike.LogicAttackBuilderMembers, 0);
		internal static string LogicQueue => At(GameSymbols.RampartAvengerStrike.LogicStepQueueMembers, 0);
		internal static string QueueCurrent => At(GameSymbols.RampartAvengerStrike.QueueCurrentStepMembers, 0);
		internal static string QueuePending => At(GameSymbols.RampartAvengerStrike.QueuePendingMembers, 0);
		internal static string AttackTargets => At(GameSymbols.RampartAvengerStrike.AttackStepTargetHexesMembers, 0);
		internal static string AttackAttacker => At(GameSymbols.RampartAvengerStrike.AttackStepAttackerMembers, 0);
		internal static string CounterCounterattacker => At(GameSymbols.CounterattackStepLaws.StepCounterattackerMembers, 0);
		internal static string CounterCountered => At(GameSymbols.CounterattackStepLaws.StepAttackerMembers, 0);
		internal static string StepState => At(GameSymbols.CounterattackStepLaws.StepStateMembers, 0);
		internal static string StatePathfinder => At(GameSymbols.RampartAvengerStrike.StatePathfinderMembers, 0);
		internal static string FieldObjectId => At(GameSymbols.RampartAvengerStrike.FieldObjectIdMembers, 0);
		internal static string FieldObjectPosition => At(GameSymbols.RampartAvengerStrike.FieldObjectPositionMembers, 0);
		internal static string PositionHex => At(GameSymbols.RampartAvengerStrike.PositionHexMembers, 0);
		internal static string StatMovementType => At(GameSymbols.RampartAvengerStrike.UnitStatMovementTypeMembers, 0);
	}

	private sealed class ArmedSide
	{
		internal int Rank;
		internal bool Focus;
		internal bool Return;
		internal bool RangedFirst;
		internal bool SwiftStrike;
		internal bool RetaliationTrigger;
		// law pass 2026-11-21: faction law levels, read once when the side is armed (Homm3RampartLawHooks).
		/// <summary>Wardens' Oath (#5): avenging strikes deal +0/10/20 % Damage.</summary>
		internal int OathPercent;
		/// <summary>law pass 2026-11-25: Thorned Vengeance (#9) buff level 0/1/2: enemy stacks hit by an avenging strike lose 2/4 Initiative this round.</summary>
		internal int ThornedLevel;
		/// <summary>law pass 2026-11-25: Mighty Oaks (#11) buff level 0/1: the striking stack takes -20% Damage this round.</summary>
		internal int OaksLevel;
		/// <summary>Elder's Ward (#13): the avenged enemy attack deals -0/10/20 % Damage.</summary>
		internal int WardPercent;
		/// <summary>law pass 2026-11-25: Call of the Grove (#30): the striker heals 0/30 % of the Damage its avenging strike deals.</summary>
		internal int GrovePercent;
		internal bool HasHitLaws => ThornedLevel > 0 || GrovePercent > 0;
		internal string HeroDescription;
		internal IntPtr WrapperPointer;
	}

	/// <summary>law pass 2026-11-21: Elder's Ward (#13). An enemy attack (or retaliation) step that started a chain.</summary>
	private sealed class AnsweredAttack
	{
		internal IntPtr Step;
		internal IntPtr Attacker;
		internal IntPtr Victim;
		internal ArmedSide Side;
	}

	private sealed class BattleState
	{
		internal object Logic;
		internal IntPtr LogicPointer;
		internal readonly List<ArmedSide> Sides = new();
		/// <summary>Native pointers of every step a chain queued (moves, avenging attacks, their counters).</summary>
		internal readonly HashSet<IntPtr> Derived = new();
		/// <summary>Avenging AttackStep pointer → the side whose chain queued it.</summary>
		internal readonly Dictionary<IntPtr, ArmedSide> AvengingAttacks = new();
		internal IntPtr SuppressFocusStep;
		/// <summary>law pass 2026-11-21: Wardens' Oath (#5). The avenging AttackStep now playing and its side.</summary>
		internal IntPtr CurrentAvengingStep;
		internal ArmedSide CurrentAvengingSide;
		/// <summary>law pass 2026-11-25: the striking unit of <see cref="CurrentAvengingStep"/> (Thorned Vengeance #9, Call of the Grove #30).</summary>
		internal IntPtr CurrentStriker;
		/// <summary>law pass 2026-11-25: Mighty Oaks (#11) striker to buff in the AttackStep Begin postfix, and its step.</summary>
		internal Unit PendingOaksStriker;
		internal IntPtr PendingOaksStep;
		/// <summary>law pass 2026-11-21: Elder's Ward (#13). Answered enemy steps (a few at most; pruned when not current).</summary>
		internal readonly List<AnsweredAttack> Answered = new();
		internal int Chains;
		/// <summary>Units whose armed Covering Fire buff has already fired; dropped once the buff is gone.</summary>
		internal readonly Dictionary<IntPtr, Unit> CoveringFireSpent = new();
	}

	private sealed class Candidate
	{
		internal Unit Unit;
		internal int Id;
		internal int Initiative;
		internal bool Ranged;
		internal bool Adjacent;
		internal int[] Path;
		internal int TargetHexId;
		internal int OriginHexId;
		internal int DestinationHexId;
		internal int AttackIndex;
		internal int AbilityType = DefaultAttackAbilityType;
		internal object MovementType;
	}

	private static readonly object Gate = new();
	private static readonly List<BattleState> Battles = new();
	private static ManualLogSource _log;
	private static bool _attempted;
	private static bool _registered;
	private static bool _swiftStrikeLive;
	private static bool _focusLive;
	private static bool _retaliationLive;
	// law pass 2026-11-25: Thorned Vengeance (#9) / Call of the Grove (#30) on avenging hits (battle damage event).
	private static bool _lawHitsLive;
	private static MethodInfo _healMethod;
	private static object _healType;
	[ThreadStatic] private static bool _inLawHit;
	private static int _logged;
	private static int _infoLogged;
	[ThreadStatic] private static bool _buildingSwift;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static MethodInfo _queueAttack;
	private static MethodInfo _queueMove;
	private static MethodInfo _findPath;
	private static MethodInfo _pathToHexIds;
	private static MethodInfo _hexDistance;
	private static Type _attackStepType;
	private static IntPtr _attackStepClass;
	private static Type _moveSourceType;
	private static readonly Dictionary<Type, PropertyInfo[]> AttackTypeProperties = new();

	internal static bool Registered => _registered;

	// ------------------------------------------------------------------ registration

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		var hexAssembly = typeof(TransferBattle).Assembly;
		try
		{
			var logicHeroType = hexAssembly.GetType(GameSymbols.CastleEliteStrategem.LogicHeroTypeName)
			                    ?? throw new TypeLoadException("Missing Hex.Session.Logic.Hero");
			_logicHeroDataHeroGetter = RequireMethod(logicHeroType, GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter.NameHints, typeof(DataHero), Type.EmptyTypes);
			var logicType = ResolveTypeByHints(hexAssembly, GameSymbols.InfernoGating.BattleLogicTypeHints, "homm3.rampart.avenger.battleLogic");
			var init = logicType.GetMethod("Init", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
				           new[] { typeof(int), typeof(TransferBattle), typeof(bool), typeof(bool) }, null)
			           ?? throw new MissingMethodException("BattleLogic.Init(int, TransferBattle, bool, bool)");
			var builderType = RequireProperty(logicType, Pins.LogicBuilder).PropertyType;
			var queueType = RequireProperty(logicType, Pins.LogicQueue).PropertyType;
			RequireProperty(queueType, Pins.QueueCurrent);
			RequireProperty(queueType, Pins.QueuePending);
			var stateType = RequireProperty(logicType, Pins.LogicState).PropertyType;
			var pathfinderType = RequireProperty(stateType, Pins.StatePathfinder).PropertyType;
			_queueAttack = FindMethodByName(builderType, GameSymbols.RampartAvengerStrike.QueueAttack.NameHints, 9)
			               ?? throw new MissingMethodException("eqd.bhqa (queue attack)");
			_queueMove = FindMethodByName(builderType, GameSymbols.RampartAvengerStrike.QueueMove.NameHints, 6)
			             ?? throw new MissingMethodException("eqd.bhpr (queue move)");
			_moveSourceType = _queueMove.GetParameters()[3].ParameterType;
			_findPath = FindMethodByName(pathfinderType, GameSymbols.RampartAvengerStrike.FindPath.NameHints, 5)
			            ?? throw new MissingMethodException("eqc.bhol (find path)");
			_pathToHexIds = FindMethodByName(pathfinderType, GameSymbols.RampartAvengerStrike.PathToHexIds.NameHints, 1)
			                ?? throw new MissingMethodException("eqc.bhoi (path to hex ids)");
			_hexDistance = FindMethodByName(pathfinderType, GameSymbols.RampartAvengerStrike.HexDistance.NameHints, 2, wantStatic: true)
			               ?? throw new MissingMethodException("eqc hex distance");
			_attackStepType = ResolveTypeByHints(hexAssembly, GameSymbols.RampartAvengerStrike.AttackStepTypeHints, "homm3.rampart.avenger.attackStep");
			RequireProperty(_attackStepType, Pins.AttackTargets);
			RequireProperty(_attackStepType, Pins.AttackAttacker);
			RequireProperty(_attackStepType, Pins.StepState);
			_attackStepClass = NativeClassPointer(_attackStepType);
			if (_attackStepClass == IntPtr.Zero)
				throw new TypeLoadException("AttackStep native class pointer unresolved");
			var attackBegin = FindMethodByName(_attackStepType, GameSymbols.RampartAvengerStrike.AttackStepBegin.NameHints, 0, declaredOnly: true)
			                  ?? throw new MissingMethodException("eux.Begin");

			Patch(harmony, init, null, nameof(PostfixBattleLogicInit));
			Patch(harmony, attackBegin, nameof(PrefixAttackStepBegin), nameof(PostfixAttackStepBegin));
			_registered = true;
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Rampart Avenger strikes NOT registered (fail closed: no avenging strikes): " + ex.GetBaseException().Message);
			return;
		}

		// Swift Strike: counter-queue prefix while a chain is building.
		try
		{
			var builderType = FindType(hexAssembly, GameSymbols.FortressPredatorInstinct.AttackBuilderTypeHints);
			var queueCounter = FindMethodByName(builderType, GameSymbols.FortressPredatorInstinct.QueueCounter.NameHints, 7);
			if (queueCounter != null)
			{
				Patch(harmony, queueCounter, nameof(PrefixQueueCounter), null);
				_swiftStrikeLive = true;
			}
		}
		catch (Exception ex)
		{
			LogLimited("Swift Strike hook not registered (avenging strikes can be retaliated against): " + ex.GetBaseException().Message);
		}

		// Focus rule: energy grant prefix.
		try
		{
			var managerType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.FocusLawsEnergyManager);
			MethodInfo grant = null;
			foreach (var name in GameSymbols.FocusLaws.GrantEnergy.NameHints ?? Array.Empty<string>())
			{
				if (string.IsNullOrWhiteSpace(name) || managerType == null || grant != null)
					continue;
				foreach (var method in managerType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
				{
					var parameters = method.GetParameters();
					if (method.Name == name && method.ReturnType == typeof(void) && parameters.Length == 1 && parameters[0].ParameterType == typeof(int))
					{
						grant = method;
						break;
					}
				}
			}
			if (grant != null)
			{
				Patch(harmony, grant, nameof(PrefixGrantEnergy), null);
				_focusLive = true;
			}
		}
		catch (Exception ex)
		{
			LogLimited("Focus hook not registered (avenging strikes generate Focus): " + ex.GetBaseException().Message);
		}

		// Expert retaliation trigger: CounterAttackStep Begin postfix.
		try
		{
			var counterType = FindType(hexAssembly, GameSymbols.CounterattackStepLaws.StepTypeHints);
			var counterBegin = counterType == null ? null : FindMethodByName(counterType, GameSymbols.CounterattackStepLaws.StepBegin.NameHints, 0, declaredOnly: true);
			if (counterBegin != null)
			{
				RequireProperty(counterType, Pins.CounterCounterattacker);
				RequireProperty(counterType, Pins.CounterCountered);
				Patch(harmony, counterBegin, null, nameof(PostfixCounterStepBegin));
				_retaliationLive = true;
			}
		}
		catch (Exception ex)
		{
			LogLimited("retaliation trigger not registered (Blood for Blood does nothing): " + ex.GetBaseException().Message);
		}

		// law pass 2026-11-25: Thorned Vengeance (#9) / Call of the Grove (#30): battle damage event postfix (the Tower /
		// Stronghold / Bulwark pattern). Heal is UnitHealer.Heal WithRealUntilStart (the Necropolis counter-doctrine heal).
		try
		{
			var hubType = Homm3TowerArtificingRuntime.ResolveLogicEventHubType()
			              ?? throw new TypeLoadException("battle event hub type not found");
			var damage = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.ObjectTookDamageDispatcher)
			             ?? throw new MissingMethodException("ObjectTookDamage dispatcher");
			if (!TryResolveHeal(out var healFail))
				LogLimited("Call of the Grove heal off: " + healFail);
			Patch(harmony, damage, null, nameof(PostfixObjectTookDamage));
			_lawHitsLive = true;
		}
		catch (Exception ex)
		{
			LogLimited("law hit hook not registered (Thorned Vengeance and Call of the Grove do nothing): " + ex.GetBaseException().Message);
		}

		_log?.LogInfo("HoMM3 Rampart Avenger strikes registered: attack trigger, Swift Strike=" + _swiftStrikeLive + ", Focus rule=" + _focusLive + ", retaliation trigger=" + _retaliationLive
		              + ", law hits=" + _lawHitsLive + " (heal " + (_healMethod != null) + ").");
	}

	// ------------------------------------------------------------------ battle start / end

	private static void PostfixBattleLogicInit(object __instance, TransferBattle __1)
	{
		try
		{
			lock (Gate)
				Battles.RemoveAll(b => ReferenceEquals(b.Logic, __instance));
			if (__1?.sides == null || __instance is not Il2CppObjectBase logicObject)
				return;
			var clone = ReadProperty(__instance, Pins.LogicBattleClone) as TransferBattle;
			if (clone?.sides == null)
				return;
			BattleState battle = null;
			for (var sideIndex = 0; sideIndex < __1.sides.Length && sideIndex < clone.sides.Length; sideIndex++)
			{
				var side = __1.sides[sideIndex];
				if (side == null)
					continue;
				// Sides without the skill (rank 0, hero or not) are tracked too: unit-kit reaction shots
				// (Covering Fire) work in any army. Rank 0 never starts an avenging chain.
				var dataHero = side.logicHero == null ? null : ResolveDataHero(side.logicHero);
				var rank = dataHero == null ? 0 : Math.Max(
					Homm3DungeonDraconicDominionHook.ResolveHeroSkillRank(dataHero, FactionSkillSid),
					Homm3DungeonDraconicDominionHook.ResolveHeroSkillRank(dataHero, "arena_" + FactionSkillSid));
				if (rank < 0)
					rank = 0;
				var wrapper = FindSideWrapper(__instance, clone.sides[sideIndex]) as Il2CppObjectBase;
				if (wrapper == null)
				{
					if (rank > 0)
						LogLimited("side wrapper for " + (dataHero?.configSid ?? "?") + " side " + sideIndex + " not found; no avenging strikes.");
					continue;
				}
				var armed = new ArmedSide
				{
					Rank = Math.Min(3, rank),
					Focus = rank > 0 && HasSubSkill(dataHero, FocusSid),
					Return = rank > 0 && HasSubSkill(dataHero, ReturnSid),
					RangedFirst = rank > 0 && HasSubSkill(dataHero, RangedFirstSid),
					SwiftStrike = rank > 0 && HasSubSkill(dataHero, SwiftStrikeSid),
					RetaliationTrigger = rank > 0 && HasSubSkill(dataHero, RetaliationTriggerSid),
					HeroDescription = (dataHero?.configSid ?? "?") + " side " + sideIndex,
					WrapperPointer = wrapper.Pointer,
				};
				if (armed.Rank > 0)
				{
					// law pass 2026-11-21: Wardens' Oath (#5), Elder's Ward (#13). law pass 2026-11-25: Thorned Vengeance (#9),
					// Mighty Oaks (#11), Call of the Grove (#30). Only with the skill; rank 0 (law not taken or unreadable)
					// keeps current behaviour.
					armed.OathPercent = Homm3RampartLawHooks.Level(Homm3RampartLawHooks.OathPercentByLevel,
						Homm3RampartLawHooks.Rank(Homm3RampartLawHooks.WardensOath, side, side.logicHero));
					armed.ThornedLevel = Homm3RampartLawHooks.Level(Homm3RampartLawHooks.ThornedLevelByLevel,
						Homm3RampartLawHooks.Rank(Homm3RampartLawHooks.ThornedVengeance, side, side.logicHero));
					armed.OaksLevel = Homm3RampartLawHooks.Level(Homm3RampartLawHooks.OaksLevelByLevel,
						Homm3RampartLawHooks.Rank(Homm3RampartLawHooks.MightyOaks, side, side.logicHero));
					armed.WardPercent = Homm3RampartLawHooks.Level(Homm3RampartLawHooks.WardPercentByLevel,
						Homm3RampartLawHooks.Rank(Homm3RampartLawHooks.EldersWard, side, side.logicHero));
					armed.GrovePercent = Homm3RampartLawHooks.Level(Homm3RampartLawHooks.GrovePercentByLevel,
						Homm3RampartLawHooks.Rank(Homm3RampartLawHooks.CallOfTheGrove, side, side.logicHero));
				}
				battle ??= new BattleState { Logic = __instance, LogicPointer = logicObject.Pointer };
				battle.Sides.Add(armed);
				if (armed.Rank > 0)
					LogInfo("armed for " + armed.HeroDescription + " rank " + armed.Rank + " (" + StrikersByRank[armed.Rank] + " striker(s), "
					        + MoveHexesByRank[armed.Rank] + " hex move)"
				        + (armed.Focus ? " +Focus" : "") + (armed.Return ? " +Return" : "") + (armed.RangedFirst ? " +RangedFirst" : "")
				        + (armed.SwiftStrike ? " +SwiftStrike" : "") + (armed.RetaliationTrigger ? " +RetaliationTrigger" : "")
				        + (armed.OathPercent > 0 ? " law:Oath+" + armed.OathPercent + "%" : "") + (armed.ThornedLevel > 0 ? " law:Thorned L" + armed.ThornedLevel : "")
				        + (armed.OaksLevel > 0 ? " law:Oaks L" + armed.OaksLevel : "") + (armed.WardPercent > 0 ? " law:Ward-" + armed.WardPercent + "%" : "")
				        + (armed.GrovePercent > 0 ? " law:Grove " + armed.GrovePercent + "%" : "") + ".");
			}
			if (battle == null)
				return;
			lock (Gate)
			{
				Battles.Add(battle);
				while (Battles.Count > 6)
					Battles.RemoveAt(0);
			}
		}
		catch (Exception ex)
		{
			LogLimited("Init postfix failed closed (no avenging strikes this battle): " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Called by the shared battle-result prefix: the battle is over, drop its state.</summary>
	internal static void ObserveBeforeBattleResult(object battleLogic)
	{
		if (!_registered)
			return;
		var pointer = (battleLogic as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
		lock (Gate)
		{
			if (pointer == IntPtr.Zero)
				Battles.Clear();
			else
				Battles.RemoveAll(b => b.LogicPointer == pointer);
		}
	}

	// ------------------------------------------------------------------ triggers

	/// <summary>An avenging AttackStep is starting: arm the Focus rule for it when its side lacks the Focus pick.</summary>
	private static void PrefixAttackStepBegin(object __instance)
	{
		try
		{
			if (__instance is not Il2CppObjectBase step)
				return;
			lock (Gate)
			{
				foreach (var battle in Battles)
				{
					// law pass 2026-11-21: a new AttackStep ends the previous step's law windows (Wardens' Oath #5,
					// Elder's Ward #13), so a reused native pointer never matches a finished step.
					if (battle.CurrentAvengingStep != step.Pointer)
					{
						battle.CurrentAvengingStep = IntPtr.Zero;
						battle.CurrentAvengingSide = null;
						battle.CurrentStriker = IntPtr.Zero;
					}
					battle.Answered.RemoveAll(a => a.Step != step.Pointer);
				}
				foreach (var battle in Battles)
				{
					if (!battle.AvengingAttacks.TryGetValue(step.Pointer, out var side))
						continue;
					battle.AvengingAttacks.Remove(step.Pointer);
					battle.SuppressFocusStep = side.Focus ? IntPtr.Zero : step.Pointer;
					// law pass 2026-11-21: Wardens' Oath (#5) reads this while the step is the queue's current step.
					battle.CurrentAvengingStep = step.Pointer;
					battle.CurrentAvengingSide = side;
					// law pass 2026-11-25: Thorned Vengeance (#9) / Call of the Grove (#30) match hits by this striker;
					// Mighty Oaks (#11) buffs it in the Begin postfix, before the strike and its retaliation resolve.
					var striker = ReadProperty(__instance, Pins.AttackAttacker) as Unit;
					battle.CurrentStriker = striker?.Pointer ?? IntPtr.Zero;
					if (side.OaksLevel > 0 && striker != null)
					{
						battle.PendingOaksStriker = striker;
						battle.PendingOaksStep = step.Pointer;
					}
					return;
				}
			}
		}
		catch
		{
			// Focus rule stays off for this step
		}
	}

	private static void PostfixAttackStepBegin(object __instance)
	{
		ApplyPendingMightyOaks(__instance);
		try
		{
			if (__instance is not Il2CppObjectBase step || ReadInt(__instance, Pins.StepState, -1) != StatePlaying)
				return;
			if (ReadProperty(__instance, Pins.AttackAttacker) is not Unit attacker || !IsAlive(attacker))
				return;
			var attackerSide = SidePointer(attacker);
			BattleState battle;
			lock (Gate)
			{
				battle = FindBattleForPointers(attackerSide, step.Pointer, out var derived);
				if (battle == null || derived)
					return;
			}
			if (ReadProperty(__instance, Pins.AttackTargets) is not Il2CppStructArray<int> targets || targets.Length == 0)
				return;
			var hexes = ReadHexes(battle.Logic);
			if (hexes == null)
				return;
			foreach (var hexId in targets)
			{
				if (hexId < 0 || hexId >= hexes.Length || hexes[hexId] == null)
					continue;
				var target = OccupantUnit(hexes[hexId], attacker);
				if (target == null)
					continue;
				var targetSide = SidePointer(target);
				if (targetSide == IntPtr.Zero || targetSide == attackerSide)
					continue;
				var armed = FindArmedSide(battle, targetSide);
				if (armed == null)
					continue;
				RunCoveringFire(battle, armed, attacker, target, hexes);
				if (armed.Rank > 0 && RunChain(battle, armed, attacker, target, hexes, "attack") > 0)
					NoteAnswered(battle, armed, step.Pointer, attacker, target);
				return;
			}
		}
		catch (Exception ex)
		{
			LogLimited("attack trigger failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixCounterStepBegin(object __instance)
	{
		try
		{
			if (__instance is not Il2CppObjectBase step || ReadInt(__instance, Pins.StepState, -1) != StatePlaying)
				return;
			if (ReadProperty(__instance, Pins.CounterCounterattacker) is not Unit retaliator || ReadProperty(__instance, Pins.CounterCountered) is not Unit victim)
				return;
			if (!IsAlive(retaliator))
				return;
			var victimSide = SidePointer(victim);
			var retaliatorSide = SidePointer(retaliator);
			if (victimSide == IntPtr.Zero || victimSide == retaliatorSide)
				return;
			BattleState battle;
			lock (Gate)
			{
				battle = FindBattleForPointers(victimSide, step.Pointer, out var derived);
				if (battle == null || derived)
					return;
			}
			var armed = FindArmedSide(battle, victimSide);
			if (armed == null || !armed.RetaliationTrigger)
				return;
			var hexes = ReadHexes(battle.Logic);
			if (hexes != null && RunChain(battle, armed, retaliator, victim, hexes, "retaliation") > 0)
				NoteAnswered(battle, armed, step.Pointer, retaliator, victim);
		}
		catch (Exception ex)
		{
			LogLimited("retaliation trigger failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>bhqp(anchor, attacker, counterattacker, ...): false skips the counter while a Swift Strike chain builds.</summary>
	private static bool PrefixQueueCounter()
	{
		return !_buildingSwift;
	}

	/// <summary>Energy grant (delta): refuse Focus gains while an avenging attack without the Focus pick is playing.</summary>
	private static bool PrefixGrantEnergy(int __0)
	{
		if (__0 <= 0)
			return true;
		try
		{
			lock (Gate)
			{
				foreach (var battle in Battles)
				{
					if (battle.SuppressFocusStep == IntPtr.Zero)
						continue;
					var current = (ReadProperty(ReadProperty(battle.Logic, Pins.LogicQueue), Pins.QueueCurrent) as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
					if (current == battle.SuppressFocusStep)
						return false;
					battle.SuppressFocusStep = IntPtr.Zero;
				}
			}
		}
		catch
		{
			// grant stays native
		}
		return true;
	}

	// ------------------------------------------------------------------ covering fire (unit kit, any army)

	/// <summary>
	/// Unit-kit reaction shot (Homm3UnitKitRuntime): a ranged stack on the victim's side that is adjacent to the
	/// victim, carries the armed Covering Fire buff and can shoot (not adjacent to the attacker) shoots the attacker
	/// once per arming. Native buffs cannot be removed from here, so the single use is a spent mark that lasts until
	/// the buff has expired. The shot is queued like an avenging strike and marked derived (it starts no chain).
	/// </summary>
	private static void RunCoveringFire(BattleState battle, ArmedSide side, Unit attacker, Unit victim, BattleHex[] hexes)
	{
		var buffSid = Homm3UnitKitRuntime.CoveringFireBuffSid;
		if (string.IsNullOrEmpty(buffSid))
			return;
		try
		{
			if (battle.CoveringFireSpent.Count > 0)
			{
				var expired = new List<IntPtr>();
				foreach (var entry in battle.CoveringFireSpent)
				{
					if (!IsAlive(entry.Value) || !HasBuff(entry.Value, buffSid))
						expired.Add(entry.Key);
				}
				foreach (var key in expired)
					battle.CoveringFireSpent.Remove(key);
			}
			var victimHexes = new List<BattleHex>();
			var attackerHexes = new List<BattleHex>();
			var unitHexes = new Dictionary<IntPtr, List<BattleHex>>();
			var units = new Dictionary<IntPtr, Unit>();
			foreach (var hex in hexes)
			{
				if (hex?.fieldObjects == null)
					continue;
				for (var i = 0; i < hex.fieldObjects.Count; i++)
				{
					var unit = hex.fieldObjects[i]?.TryCast<Unit>();
					if (unit == null || !IsAlive(unit))
						continue;
					if (unit.Pointer == victim.Pointer)
						victimHexes.Add(hex);
					else if (unit.Pointer == attacker.Pointer)
						attackerHexes.Add(hex);
					else if (SidePointer(unit) == side.WrapperPointer)
					{
						if (!unitHexes.TryGetValue(unit.Pointer, out var list))
						{
							unitHexes[unit.Pointer] = list = new List<BattleHex>();
							units[unit.Pointer] = unit;
						}
						list.Add(hex);
					}
				}
			}
			if (victimHexes.Count == 0 || attackerHexes.Count == 0 || units.Count == 0)
				return;
			object builder = null;
			object pending = null;
			foreach (var entry in units)
			{
				var unit = entry.Value;
				if (battle.CoveringFireSpent.ContainsKey(entry.Key) || !IsRanged(unit))
					continue;
				var own = unitHexes[entry.Key];
				if (!AnyAdjacent(own, victimHexes) || AnyAdjacent(own, attackerHexes))
					continue;
				if (!HasBuff(unit, buffSid))
					continue;
				if (!TryPickAttack(unit, true, out var abilityType, out var attackIndex))
					continue;
				if (builder == null)
				{
					builder = ReadProperty(battle.Logic, Pins.LogicBuilder);
					pending = ReadProperty(ReadProperty(battle.Logic, Pins.LogicQueue), Pins.QueuePending);
					if (builder == null || pending == null)
					{
						LogLimited("covering fire skipped: builder/queue unreadable.");
						return;
					}
				}
				var id = ReadInt(unit, Pins.FieldObjectId, -1);
				var origin = MainHex(unit) ?? own[0];
				if (id < 0 || origin == null)
					continue;
				var candidate = new Candidate
				{
					Unit = unit,
					Id = id,
					Ranged = true,
					OriginHexId = origin.index,
					TargetHexId = attackerHexes[0].index,
					AbilityType = abilityType,
					AttackIndex = attackIndex,
					MovementType = ReadProperty(ReadProperty(unit, Pins.UnitStat), Pins.StatMovementType),
				};
				if (!QueueStrike(battle, side, builder, pending, candidate, Array.Empty<int>(), candidate.TargetHexId, out var detail))
				{
					LogLimited("covering fire by " + DescribeUnit(unit) + " was not queued: " + detail);
					continue;
				}
				battle.CoveringFireSpent[entry.Key] = unit;
				LogInfo("covering fire: " + DescribeUnit(unit) + " shoots " + DescribeUnit(attacker) + " for attacking " + DescribeUnit(victim) + ".");
			}
		}
		catch (Exception ex)
		{
			LogLimited("covering fire failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// Living friendly stacks standing next to <paramref name="unit"/> (any of its hexes), for unit-kit rules
	/// (Shield Wall). -1 when the battle or grid cannot be read; callers fail closed.
	/// </summary>
	internal static int CountAdjacentAllies(Unit unit)
	{
		if (unit == null || unit.Pointer == IntPtr.Zero)
			return -1;
		try
		{
			lock (Gate)
			{
				var sidePointer = SidePointer(unit);
				var battle = FindBattleForPointers(sidePointer, IntPtr.Zero, out _);
				var hexes = battle == null ? null : ReadHexes(battle.Logic);
				if (hexes == null)
					return -1;
				var own = new List<BattleHex>();
				var allies = new Dictionary<IntPtr, List<BattleHex>>();
				foreach (var hex in hexes)
				{
					if (hex?.fieldObjects == null)
						continue;
					for (var i = 0; i < hex.fieldObjects.Count; i++)
					{
						var other = hex.fieldObjects[i]?.TryCast<Unit>();
						if (other == null)
							continue;
						if (other.Pointer == unit.Pointer)
							own.Add(hex);
						else if (SidePointer(other) == sidePointer && IsAlive(other))
						{
							if (!allies.TryGetValue(other.Pointer, out var list))
								allies[other.Pointer] = list = new List<BattleHex>();
							list.Add(hex);
						}
					}
				}
				if (own.Count == 0)
					return -1;
				var count = 0;
				foreach (var list in allies.Values)
				{
					if (AnyAdjacent(own, list))
						count++;
				}
				return count;
			}
		}
		catch
		{
			return -1;
		}
	}

	private static bool HasBuff(Unit unit, string buffSid)
		=> Homm3BuffDebuffNativeAdapter.TryRequireBuffSidFromReceiver(unit, buffSid, out var info, out _) && info.HasSid;

	private static bool AnyAdjacent(List<BattleHex> a, List<BattleHex> b)
	{
		foreach (var x in a)
		{
			foreach (var y in b)
			{
				if (Distance(x, y) == 1)
					return true;
			}
		}
		return false;
	}

	// ------------------------------------------------------------------ law damage (law pass 2026-11-21)

	/// <summary>law pass 2026-11-21: Elder's Ward (#13). Remembers an enemy step whose attack the side answered.</summary>
	private static void NoteAnswered(BattleState battle, ArmedSide side, IntPtr step, Unit attacker, Unit victim)
	{
		if (side == null || side.WardPercent <= 0 || step == IntPtr.Zero || attacker == null || victim == null)
			return;
		lock (Gate)
		{
			battle.Answered.RemoveAll(a => a.Step == step);
			battle.Answered.Add(new AnsweredAttack { Step = step, Attacker = attacker.Pointer, Victim = victim.Pointer, Side = side });
			while (battle.Answered.Count > 8)
				battle.Answered.RemoveAt(0);
		}
	}

	/// <summary>
	/// Damage contribution for the committed-damage owner (same contract as
	/// <see cref="Homm3FortressPredatorInstinctRuntime.DamagePercent"/>):
	/// - Wardens' Oath (#5): +10/+20 % on hits by a striker of the side whose avenging AttackStep is the queue's current
	///   step. Retaliations against the strike come from the other side and get nothing.
	/// - Elder's Ward (#13): -10/-20 % on hits from the answered attacker to its victim while the step that started the
	///   chain (an attack, or a retaliation with Blood for Blood) is the queue's current step.
	/// Fail closed: anything unreadable returns 0.
	/// </summary>
	internal static int DamagePercent(object caster, object receiver, out string detail)
	{
		detail = null;
		if (!_registered || caster is not Unit casterUnit || receiver is not Il2CppObjectBase receiverObject)
			return 0;
		try
		{
			List<BattleState> battles;
			lock (Gate)
			{
				if (Battles.Count == 0)
					return 0;
				battles = new List<BattleState>(Battles);
			}
			foreach (var battle in battles)
			{
				ArmedSide oathSide;
				IntPtr oathStep;
				List<AnsweredAttack> answered;
				lock (Gate)
				{
					oathSide = battle.CurrentAvengingSide;
					oathStep = battle.CurrentAvengingStep;
					answered = battle.Answered.Count == 0 ? null : new List<AnsweredAttack>(battle.Answered);
				}
				if ((oathSide == null || oathSide.OathPercent <= 0) && answered == null)
					continue;
				var current = (ReadProperty(ReadProperty(battle.Logic, Pins.LogicQueue), Pins.QueueCurrent) as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
				if (current == IntPtr.Zero)
					continue;
				if (oathSide != null && oathSide.OathPercent > 0 && current == oathStep && SidePointer(casterUnit) == oathSide.WrapperPointer)
				{
					detail = "Rampart Wardens' Oath +" + oathSide.OathPercent + "% on an avenging strike (" + oathSide.HeroDescription + ")";
					return oathSide.OathPercent;
				}
				if (answered == null)
					continue;
				foreach (var entry in answered)
				{
					if (entry.Step != current || entry.Attacker != casterUnit.Pointer || entry.Victim != receiverObject.Pointer)
						continue;
					detail = "Rampart Elder's Ward -" + entry.Side.WardPercent + "% on an avenged attack (" + entry.Side.HeroDescription + ")";
					return -entry.Side.WardPercent;
				}
			}
		}
		catch
		{
			// fail closed: native damage
		}
		return 0;
	}

	// ------------------------------------------------------------------ law pass 2026-11-25: avenging-hit laws

	/// <summary>
	/// law pass 2026-11-25: Mighty Oaks (#11). The avenging AttackStep that the prefix marked is starting: the striking
	/// stack takes -20% Damage until the end of the round (law buff, duration 1), so it covers the retaliation too.
	/// </summary>
	private static void ApplyPendingMightyOaks(object instance)
	{
		try
		{
			if (instance is not Il2CppObjectBase step)
				return;
			Unit striker = null;
			int level = 0;
			lock (Gate)
			{
				foreach (var battle in Battles)
				{
					if (battle.PendingOaksStriker == null || battle.PendingOaksStep != step.Pointer)
						continue;
					striker = battle.PendingOaksStriker;
					level = battle.CurrentAvengingSide?.OaksLevel ?? 0;
					battle.PendingOaksStriker = null;
					battle.PendingOaksStep = IntPtr.Zero;
					break;
				}
			}
			if (striker == null || level <= 0 || !IsAlive(striker))
				return;
			var sid = Homm3RampartLawHooks.OaksBuffPrefix + level;
			if (Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(striker, sid, striker, 1, 1, 0, true, out _, out var fail))
				LogInfo("Mighty Oaks " + sid + " on the avenging striker.");
			else
				LogLimited("Mighty Oaks " + sid + " failed: " + fail);
		}
		catch (Exception ex)
		{
			LogLimited("Mighty Oaks failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>
	/// law pass 2026-11-25: Thorned Vengeance (#9) and Call of the Grove (#30). A battle damage event whose caster is the
	/// striker of the avenging AttackStep that is the queue's current step, on an enemy: the receiver loses 2/4 Initiative
	/// until the end of the round (law buff, duration 1) and the striker heals 30% of the Damage dealt (UnitHealer.Heal
	/// WithRealUntilStart: restores fallen creatures up to the starting stack size; a destroyed stack is not revived).
	/// Fail closed: anything unreadable does nothing.
	/// </summary>
	private static void PostfixObjectTookDamage(object __instance, object[] __args)
	{
		if (!_lawHitsLive || _inLawHit || __args == null || __args.Length < 2)
			return;
		_inLawHit = true;
		try
		{
			List<BattleState> battles = null;
			lock (Gate)
			{
				foreach (var battle in Battles)
				{
					if (battle.CurrentStriker != IntPtr.Zero && battle.CurrentAvengingSide != null && battle.CurrentAvengingSide.HasHitLaws)
						(battles ??= new List<BattleState>()).Add(battle);
				}
			}
			if (battles == null)
				return;
			if (!Homm3BattleEventNativeAdapter.TryReadDamageEvent(__args[1], out var hit, out _))
				return;
			if (hit.Damage <= 0 || hit.ImmuneToDamage)
				return;
			var caster = AsUnit(hit.Caster);
			var receiver = AsUnit(hit.Receiver);
			if (caster == null || receiver == null)
				return;
			foreach (var battle in battles)
			{
				ArmedSide side;
				IntPtr step;
				lock (Gate)
				{
					side = battle.CurrentAvengingSide;
					step = battle.CurrentAvengingStep;
					if (side == null || battle.CurrentStriker != caster.Pointer)
						continue;
				}
				var current = (ReadProperty(ReadProperty(battle.Logic, Pins.LogicQueue), Pins.QueueCurrent) as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
				if (current == IntPtr.Zero || current != step)
					continue;
				var receiverSide = SidePointer(receiver);
				if (receiverSide == IntPtr.Zero || receiverSide == side.WrapperPointer || SidePointer(caster) != side.WrapperPointer)
					continue;
				if (side.ThornedLevel > 0 && IsAlive(receiver))
				{
					var sid = Homm3RampartLawHooks.ThornedBuffPrefix + side.ThornedLevel;
					if (Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(receiver, sid, caster, 1, 1, 0, true, out _, out var buffFail))
						LogInfo("Thorned Vengeance " + sid + " on the struck enemy (" + side.HeroDescription + ").");
					else
						LogLimited("Thorned Vengeance " + sid + " failed: " + buffFail);
				}
				if (side.GrovePercent > 0 && IsAlive(caster))
				{
					var amount = (int)Math.Round(hit.Damage * (side.GrovePercent / 100.0), MidpointRounding.AwayFromZero);
					if (amount > 0)
						LogInfo("Call of the Grove: " + Heal(caster, amount) + " (" + side.GrovePercent + "% of " + hit.Damage + ").");
				}
				return;
			}
		}
		catch (Exception ex)
		{
			LogLimited("law hit postfix failed closed: " + ex.GetBaseException().Message);
		}
		finally
		{
			_inLawHit = false;
		}
	}

	private static string Heal(Unit unit, int amount)
	{
		if (_healMethod == null || _healType == null)
			return "heal skipped (UnitHealer.Heal unresolved)";
		var parameterType = _healMethod.GetParameters()[0].ParameterType;
		object unitArg = parameterType.IsInstanceOfType(unit) ? unit : null;
		if (unitArg == null && typeof(Il2CppObjectBase).IsAssignableFrom(parameterType) && unit.Pointer != IntPtr.Zero)
			unitArg = Activator.CreateInstance(parameterType, unit.Pointer);
		if (unitArg == null)
			return "heal skipped (striker is not a healable Unit)";
		// revive=false: a destroyed stack stays dead; WithRealUntilStart restores fallen creatures up to the start size.
		_healMethod.Invoke(null, new[] { unitArg, amount, _healType, false });
		return "healed " + amount + " HP";
	}

	/// <summary>UnitHealer.Heal(this Unit, int, EHealType, bool) and EHealType.WithRealUntilStart (same lookup as the Necropolis counter doctrine).</summary>
	private static bool TryResolveHeal(out string failReason)
	{
		var type = GameMember.FindTypeFromHints("homm3.rampart.avenger.unitHealer", GameSymbols.TowerArtificing.UnitHealerTypeHints);
		if (type == null)
		{
			failReason = "UnitHealer type not found";
			return false;
		}
		MethodInfo selected = null;
		foreach (var name in GameSymbols.TowerArtificing.UnitHealerHeal.NameHints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name) || GameSymbolScope.IsSentinel(name))
				continue;
			foreach (var method in type.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal) || method.ReturnType != typeof(void) || method.ContainsGenericParameters)
					continue;
				var p = method.GetParameters();
				if (p.Length != 4
				    || !typeof(Il2CppObjectBase).IsAssignableFrom(p[0].ParameterType)
				    || p[1].ParameterType != typeof(int)
				    || !p[2].ParameterType.IsEnum
				    || p[3].ParameterType != typeof(bool))
					continue;
				if (selected != null && !ReferenceEquals(selected, method))
				{
					failReason = "UnitHealer.Heal ambiguous on " + type.FullName;
					return false;
				}
				selected = method;
			}
			if (selected != null)
				break;
		}
		if (selected == null)
		{
			failReason = "UnitHealer.Heal(Unit, int, EHealType, bool) not found on " + type.FullName;
			return false;
		}
		try
		{
			_healType = Enum.Parse(selected.GetParameters()[2].ParameterType, "WithRealUntilStart");
		}
		catch (ArgumentException)
		{
			failReason = "EHealType.WithRealUntilStart not found";
			return false;
		}
		_healMethod = selected;
		failReason = null;
		return true;
	}

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

	// ------------------------------------------------------------------ chain

	/// <summary>Queues the avenging strikes; returns how many were queued (0 when none).</summary>
	private static int RunChain(BattleState battle, ArmedSide side, Unit attacker, Unit victim, BattleHex[] hexes, string cause)
	{
		var builder = ReadProperty(battle.Logic, Pins.LogicBuilder);
		var queue = ReadProperty(battle.Logic, Pins.LogicQueue);
		var pending = ReadProperty(queue, Pins.QueuePending);
		var pathfinder = ReadProperty(ReadProperty(battle.Logic, Pins.LogicState), Pins.StatePathfinder);
		if (builder == null || pending == null || pathfinder == null)
		{
			LogLimited("chain skipped: builder/queue/pathfinder unreadable.");
			return 0;
		}
		var attackerId = ReadInt(attacker, Pins.FieldObjectId, -1);
		if (attackerId < 0)
			return 0;

		// Occupancy from the grid: unit pointer → its hexes (large units cover two).
		var unitHexes = new Dictionary<IntPtr, List<BattleHex>>();
		var units = new Dictionary<IntPtr, Unit>();
		var occupied = new HashSet<int>();
		foreach (var hex in hexes)
		{
			if (hex?.fieldObjects == null)
				continue;
			for (var i = 0; i < hex.fieldObjects.Count; i++)
			{
				var unit = hex.fieldObjects[i]?.TryCast<Unit>();
				if (unit == null || !IsAlive(unit))
					continue;
				occupied.Add(hex.index);
				if (!unitHexes.TryGetValue(unit.Pointer, out var list))
				{
					unitHexes[unit.Pointer] = list = new List<BattleHex>();
					units[unit.Pointer] = unit;
				}
				list.Add(hex);
			}
		}
		if (!unitHexes.TryGetValue(attacker.Pointer, out var attackerHexes) || attackerHexes.Count == 0)
			return 0;

		// law pass 2026-11-25: the old Call of the Grove (+1 striker) and Paths of the Glade (+1 hex) levers are retired.
		var maxStrikers = StrikersByRank[side.Rank];
		var moveHexes = MoveHexesByRank[side.Rank];
		var candidates = new List<Candidate>();
		foreach (var entry in units)
		{
			var unit = entry.Value;
			if (entry.Key == victim.Pointer || entry.Key == attacker.Pointer || SidePointer(unit) != side.WrapperPointer)
				continue;
			var candidate = BuildCandidate(unit, unitHexes[entry.Key], attackerHexes, side, moveHexes);
			if (candidate != null)
				candidates.Add(candidate);
		}
		if (candidates.Count == 0)
			return 0;
		candidates.Sort((a, b) => b.Initiative.CompareTo(a.Initiative));

		var reserved = new HashSet<int>();
		var struck = new List<string>();
		foreach (var candidate in candidates)
		{
			if (struck.Count >= maxStrikers)
				break;
			// Ranged stacks shoot only as the first strike of a chain (Expert pick); otherwise they need melee reach.
			var shoot = candidate.Ranged && !candidate.Adjacent;
			if (shoot && (!side.RangedFirst || struck.Count > 0))
				continue;
			int[] path;
			int destination;
			int targetHexId;
			if (candidate.Adjacent || shoot)
			{
				path = Array.Empty<int>();
				destination = candidate.OriginHexId;
				targetHexId = candidate.TargetHexId;
			}
			else
			{
				if (!TryPlanApproach(pathfinder, candidate, attackerHexes, occupied, reserved, moveHexes, hexes, out path, out destination, out targetHexId))
					continue;
			}
			if (!TryPickAttack(candidate.Unit, shoot, out var abilityType, out var attackIndex))
			{
				LogLimited("strike by " + DescribeUnit(candidate.Unit) + " skipped: no " + (shoot ? "ranged" : "melee") + " attack");
				continue;
			}
			candidate.AbilityType = abilityType;
			candidate.AttackIndex = attackIndex;
			if (!QueueStrike(battle, side, builder, pending, candidate, path, targetHexId, out var detail))
			{
				LogLimited("strike by " + DescribeUnit(candidate.Unit) + " was not queued: " + detail);
				continue;
			}
			if (path.Length > 0)
			{
				reserved.Add(destination);
				if (!side.Return)
				{
					occupied.Remove(candidate.OriginHexId);
					occupied.Add(destination);
				}
			}
			struck.Add(DescribeUnit(candidate.Unit) + (shoot ? " shot" : path.Length > 0 ? " moved " + path.Length + (side.Return ? " +return" : "") : " in place"));
		}
		if (struck.Count == 0)
			return 0;
		battle.Chains++;
		LogInfo("chain " + battle.Chains + " (" + cause + ") for " + side.HeroDescription + ": " + DescribeUnit(victim) + " attacked by " + DescribeUnit(attacker)
		        + " → " + string.Join(", ", struck) + (side.SwiftStrike ? " [Swift Strike]" : "") + (side.Focus ? "" : " [no Focus]") + ".");
		return struck.Count;
	}

	private static Candidate BuildCandidate(Unit unit, List<BattleHex> ownHexes, List<BattleHex> attackerHexes, ArmedSide side, int moveHexes)
	{
		var attacks = unit.prop_UnitLogicConfig_0?.defaultAttacks;
		if (attacks == null || attacks.Length == 0)
			return null;
		var id = ReadInt(unit, Pins.FieldObjectId, -1);
		var origin = MainHex(unit) ?? ownHexes[0];
		if (id < 0 || origin == null)
			return null;
		var candidate = new Candidate
		{
			Unit = unit,
			Id = id,
			Ranged = IsRanged(unit),
			OriginHexId = origin.index,
			TargetHexId = -1,
			MovementType = ReadProperty(ReadProperty(unit, Pins.UnitStat), Pins.StatMovementType),
		};
		Homm3BuffDebuffNativeAdapter.TryAdjustUnitIntStat(unit, "initiative", 0, out candidate.Initiative, out _, out _);
		foreach (var own in ownHexes)
		{
			foreach (var target in attackerHexes)
			{
				if (Distance(own, target) == 1)
				{
					candidate.Adjacent = true;
					candidate.TargetHexId = target.index;
					break;
				}
			}
			if (candidate.Adjacent)
				break;
		}
		if (candidate.Adjacent)
			return candidate;
		if (candidate.Ranged)
		{
			if (!side.RangedFirst)
				return null;
			candidate.TargetHexId = attackerHexes[0].index;
			return candidate;
		}
		// Melee stacks out of reach can step in; large stacks only strike from where they stand
		// (law pass 2026-11-25: the old Mighty Oaks gate lift is retired).
		return moveHexes > 0 && ownHexes.Count == 1 ? candidate : null;
	}

	private static bool TryPlanApproach(object pathfinder, Candidate candidate, List<BattleHex> attackerHexes, HashSet<int> occupied,
		HashSet<int> reserved, int moveHexes, BattleHex[] hexes, out int[] bestPath, out int bestDestination, out int bestTarget)
	{
		bestPath = null;
		bestDestination = -1;
		bestTarget = -1;
		var origin = candidate.OriginHexId >= 0 && candidate.OriginHexId < hexes.Length ? hexes[candidate.OriginHexId] : null;
		if (origin == null)
			return false;
		var flyer = IsFlyer(candidate.MovementType);
		foreach (var target in attackerHexes)
		{
			foreach (var hex in hexes)
			{
				if (hex == null || hex.blockedByMap || hex.blockedFromAll || hex.tempBlocked)
					continue;
				if (occupied.Contains(hex.index) || reserved.Contains(hex.index))
					continue;
				if (Distance(hex, target) != 1)
					continue;
				var distance = Distance(origin, hex);
				if (distance < 1 || distance > moveHexes)
					continue;
				var path = FindPath(pathfinder, candidate.Unit, hex);
				if (path == null || path.Length == 0)
					continue;
				if (!flyer && path.Length > moveHexes)
					continue;
				var crossesReserved = false;
				foreach (var step in path)
				{
					if (reserved.Contains(step))
						crossesReserved = true;
				}
				if (crossesReserved)
					continue;
				if (bestPath == null || path.Length < bestPath.Length)
				{
					bestPath = path;
					bestDestination = hex.index;
					bestTarget = target.index;
				}
			}
		}
		return bestPath != null;
	}

	private static bool QueueStrike(BattleState battle, ArmedSide side, object builder, object pending, Candidate candidate, int[] path, int targetHexId, out string detail)
	{
		detail = null;
		var before = ListCount(pending);
		if (before < 0)
		{
			detail = "pending step list unreadable";
			return false;
		}
		// The builder may insert anywhere, so new steps are found by pointer, not by index.
		var existing = PendingPointers(pending);
		var pathArray = new Il2CppStructArray<int>(path.Length);
		for (var i = 0; i < path.Length; i++)
			pathArray[i] = path[i];
		var targetArray = new Il2CppStructArray<int>(1);
		targetArray[0] = targetHexId;
		var movementParameter = _queueAttack.GetParameters()[4].ParameterType;
		var movement = candidate.MovementType != null && movementParameter.IsInstanceOfType(candidate.MovementType)
			? candidate.MovementType
			: Enum.ToObject(movementParameter, 0);
		_buildingSwift = side.SwiftStrike && _swiftStrikeLive;
		try
		{
			_queueAttack.Invoke(builder, new object[] { candidate.Id, candidate.Id, pathArray, targetArray, movement, candidate.AbilityType, candidate.AttackIndex, true, false });
		}
		catch (Exception ex)
		{
			detail = "bhqa threw: " + ex.GetBaseException().Message;
			return false;
		}
		finally
		{
			_buildingSwift = false;
		}
		var afterAttack = ListCount(pending);
		if (afterAttack <= before)
		{
			detail = "the builder refused the attack (no steps queued)";
			return false;
		}
		if (side.Return && path.Length > 0)
		{
			var back = new Il2CppStructArray<int>(path.Length);
			back[0] = candidate.OriginHexId;
			for (var i = 1; i < path.Length; i++)
				back[i] = path[path.Length - i];
			try
			{
				_queueMove.Invoke(builder, new object[] { candidate.Id, candidate.Id, movement, Enum.ToObject(_moveSourceType, MoveSourceDefault), back, false });
			}
			catch (Exception ex)
			{
				LogLimited("return move for " + DescribeUnit(candidate.Unit) + " failed (stays at the attacker): " + ex.GetBaseException().Message);
			}
		}
		var after = ListCount(pending);
		lock (Gate)
		{
			for (var i = 0; i < after; i++)
			{
				if (ListItem(pending, i) is not Il2CppObjectBase step || existing.Contains(step.Pointer))
					continue;
				battle.Derived.Add(step.Pointer);
				if (!IsNativeInstance(step, _attackStepClass))
					continue;
				var wrapper = Activator.CreateInstance(_attackStepType, step.Pointer);
				if (ReadProperty(wrapper, Pins.AttackAttacker) is Unit striker && striker.Pointer == candidate.Unit.Pointer)
					battle.AvengingAttacks[step.Pointer] = side;
			}
			PruneDerived(battle, pending);
		}
		return true;
	}

	private static HashSet<IntPtr> PendingPointers(object pending)
	{
		var set = new HashSet<IntPtr>();
		var count = ListCount(pending);
		for (var i = 0; i < count; i++)
		{
			if (ListItem(pending, i) is Il2CppObjectBase step)
				set.Add(step.Pointer);
		}
		return set;
	}

	/// <summary>Drops marks for steps that already ran (no longer pending or current), so freed pointers never match later.</summary>
	private static void PruneDerived(BattleState battle, object pending)
	{
		if (battle.Derived.Count < 64)
			return;
		var live = PendingPointers(pending);
		var current = (ReadProperty(ReadProperty(battle.Logic, Pins.LogicQueue), Pins.QueueCurrent) as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
		if (current != IntPtr.Zero)
			live.Add(current);
		battle.Derived.RemoveWhere(p => !live.Contains(p));
		var stale = new List<IntPtr>();
		foreach (var key in battle.AvengingAttacks.Keys)
		{
			if (!live.Contains(key))
				stale.Add(key);
		}
		foreach (var key in stale)
			battle.AvengingAttacks.Remove(key);
	}

	// ------------------------------------------------------------------ helpers

	private static BattleState FindBattleForPointers(IntPtr sidePointer, IntPtr stepPointer, out bool derived)
	{
		derived = false;
		if (sidePointer == IntPtr.Zero)
			return null;
		foreach (var battle in Battles)
		{
			// Any unit of a tracked battle has one of its wrappers; the attacker may belong to the unarmed side, so
			// match through the logic's own side-wrapper list.
			if (!BattleOwnsWrapper(battle, sidePointer))
				continue;
			derived = battle.Derived.Contains(stepPointer);
			return battle;
		}
		return null;
	}

	private static readonly ConditionalWeakTable<object, HashSet<IntPtr>> WrapperSets = new();

	private static bool BattleOwnsWrapper(BattleState battle, IntPtr sidePointer)
	{
		foreach (var side in battle.Sides)
		{
			if (side.WrapperPointer == sidePointer)
				return true;
		}
		if (!WrapperSets.TryGetValue(battle, out var set))
		{
			set = new HashSet<IntPtr>();
			if (ReadProperty(ReadProperty(battle.Logic, Pins.LogicState), Pins.StateSideWrappers) is IEnumerable wrappers)
			{
				foreach (var wrapper in wrappers)
				{
					if (wrapper is Il2CppObjectBase obj)
						set.Add(obj.Pointer);
				}
			}
			WrapperSets.Add(battle, set);
		}
		return set.Contains(sidePointer);
	}

	private static ArmedSide FindArmedSide(BattleState battle, IntPtr sidePointer)
	{
		foreach (var side in battle.Sides)
		{
			if (side.WrapperPointer == sidePointer)
				return side;
		}
		return null;
	}

	private static BattleHex[] ReadHexes(object logic)
	{
		if (ReadProperty(ReadProperty(logic, Pins.LogicGrid), Pins.GridHexes) is not Il2CppReferenceArray<BattleHex> array)
			return null;
		var result = new BattleHex[array.Length];
		for (var i = 0; i < array.Length; i++)
		{
			var hex = array[i];
			if (hex != null && hex.index >= 0 && hex.index < result.Length)
				result[hex.index] = hex;
		}
		return result;
	}

	/// <summary>The living unit on <paramref name="hex"/> other than <paramref name="except"/>.</summary>
	private static Unit OccupantUnit(BattleHex hex, Unit except)
	{
		if (hex?.fieldObjects == null)
			return null;
		for (var i = 0; i < hex.fieldObjects.Count; i++)
		{
			var unit = hex.fieldObjects[i]?.TryCast<Unit>();
			if (unit != null && unit.Pointer != except.Pointer && IsAlive(unit))
				return unit;
		}
		return null;
	}

	private static BattleHex MainHex(Unit unit)
	{
		if (unit == null)
			return null;
		return ReadProperty(ReadProperty(unit, Pins.FieldObjectPosition), Pins.PositionHex) as BattleHex;
	}

	private static IntPtr SidePointer(Unit unit)
		=> (ReadProperty(unit, Pins.FieldObjectSide) as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;

	private static int Distance(BattleHex a, BattleHex b)
	{
		try
		{
			return (int)_hexDistance.Invoke(null, new object[] { a, b });
		}
		catch
		{
			return int.MaxValue;
		}
	}

	private static int[] FindPath(object pathfinder, Unit unit, BattleHex destination)
	{
		try
		{
			var list = new Il2CppSystem.Collections.Generic.List<BattleHex>();
			var args = new object[] { unit, destination, UnityEngine.Vector3.zero, false, list };
			if (_findPath.Invoke(pathfinder, args) is not true)
				return null;
			if (_pathToHexIds.Invoke(pathfinder, new object[] { list }) is not Il2CppStructArray<int> ids)
				return null;
			var result = new int[ids.Length];
			for (var i = 0; i < ids.Length; i++)
				result[i] = ids[i];
			return result;
		}
		catch (Exception ex)
		{
			LogLimited("path query failed for " + DescribeUnit(unit) + ": " + ex.GetBaseException().Message);
			return null;
		}
	}

	private static bool IsFlyer(object movementType)
	{
		var name = movementType?.ToString();
		return name == nameof(EMovementType.Fly) || name == nameof(EMovementType.Teleport);
	}

	/// <summary>
	/// The attack an avenging strike uses: the shot from defaultAttacks when <paramref name="shoot"/>; otherwise the
	/// first melee entry of defaultAttacks, then of alternativeAttacks (a shooter's melee attack lives there). False when
	/// the unit has no attack of that kind, so a shooter never fires its shot as a "melee" strike.
	/// </summary>
	private static bool TryPickAttack(Unit unit, bool shoot, out int abilityType, out int index)
	{
		abilityType = DefaultAttackAbilityType;
		index = 0;
		var config = unit.prop_UnitLogicConfig_0;
		if (config == null)
			return !shoot;
		if (FindAttack(config.defaultAttacks, shoot, out index))
			return true;
		if (!shoot && FindAttack(config.alternativeAttacks, false, out index))
		{
			abilityType = AlternativeAttackAbilityType;
			return true;
		}
		index = 0;
		return false;
	}

	private static bool FindAttack(Il2CppReferenceArray<AbilityLogicConfig> attacks, bool shoot, out int index)
	{
		index = 0;
		if (attacks == null)
			return false;
		for (var i = 0; i < attacks.Length; i++)
		{
			if (attacks[i] == null)
				continue;
			var type = ReadAttackType(attacks[i]);
			if (type == EAttackType.Unknown)
				continue;
			var ranged = type == EAttackType.Shoot || type == EAttackType.Range;
			if (ranged == shoot)
			{
				index = i;
				return true;
			}
		}
		return false;
	}

	private static bool IsRanged(Unit unit)
	{
		var attacks = unit.prop_UnitLogicConfig_0?.defaultAttacks;
		if (attacks == null)
			return false;
		for (var i = 0; i < attacks.Length; i++)
		{
			var type = attacks[i] == null ? EAttackType.Unknown : ReadAttackType(attacks[i]);
			if (type == EAttackType.Shoot || type == EAttackType.Range)
				return true;
		}
		return false;
	}

	private static EAttackType ReadAttackType(AbilityLogicConfig attack)
	{
		var type = attack.GetType();
		PropertyInfo[] properties;
		lock (AttackTypeProperties)
		{
			if (!AttackTypeProperties.TryGetValue(type, out properties))
			{
				properties = Array.FindAll(type.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic),
					p => p.PropertyType == typeof(EAttackType) && p.CanRead && p.GetIndexParameters().Length == 0);
				AttackTypeProperties[type] = properties;
			}
		}
		foreach (var property in properties)
		{
			try
			{
				if (property.GetValue(attack) is EAttackType value && value != EAttackType.Unknown)
					return value;
			}
			catch
			{
				// next property
			}
		}
		return EAttackType.Unknown;
	}

	private static bool IsAlive(Unit unit) => Homm3FortressPredatorInstinctRuntime.IsAlive(unit);

	private static string DescribeUnit(Unit unit) => Homm3FortressPredatorInstinctRuntime.DescribeUnit(unit);

	private static bool HasSubSkill(DataHero hero, string sid)
		=> Homm3DungeonDraconicDominionHook.HasHeroSubSkill(hero, sid) || Homm3DungeonDraconicDominionHook.HasHeroSubSkill(hero, "arena_" + sid);

	private static DataHero ResolveDataHero(object logicHero)
	{
		if (logicHero == null || _logicHeroDataHeroGetter == null || !_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(logicHero))
			return null;
		return _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>()) as DataHero;
	}

	private static object FindSideWrapper(object logic, TransferSide side)
	{
		if (ReadProperty(ReadProperty(logic, Pins.LogicState), Pins.StateSideWrappers) is not IEnumerable wrappers)
			return null;
		foreach (var wrapper in wrappers)
		{
			if (ReadProperty(wrapper, Pins.SideWrapperTransferSide) is TransferSide ts && ts.Pointer == side.Pointer)
				return wrapper;
		}
		return null;
	}

	private static int ListCount(object list)
	{
		if (list == null)
			return -1;
		try
		{
			return Convert.ToInt32(ReadProperty(list, "Count"));
		}
		catch
		{
			return -1;
		}
	}

	private static object ListItem(object list, int index)
	{
		try
		{
			var method = list.GetType().GetMethod("get_Item", BindingFlags.Instance | BindingFlags.Public, null, new[] { typeof(int) }, null);
			return method?.Invoke(list, new object[] { index });
		}
		catch
		{
			return null;
		}
	}

	private static IntPtr NativeClassPointer(Type managedType)
	{
		var store = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
		RuntimeHelpers.RunClassConstructor(store.TypeHandle);
		return store.GetField("NativeClassPtr", BindingFlags.Public | BindingFlags.Static)?.GetValue(null) is IntPtr ptr ? ptr : IntPtr.Zero;
	}

	private static bool IsNativeInstance(Il2CppObjectBase obj, IntPtr expectedClass)
	{
		if (obj == null || obj.Pointer == IntPtr.Zero || expectedClass == IntPtr.Zero)
			return false;
		var actual = IL2CPP.il2cpp_object_get_class(obj.Pointer);
		return actual != IntPtr.Zero && IL2CPP.il2cpp_class_is_assignable_from(expectedClass, actual);
	}

	private static int ReadInt(object obj, string name, int fallback)
	{
		try
		{
			var value = ReadProperty(obj, name);
			return value == null ? fallback : Convert.ToInt32(value);
		}
		catch
		{
			return fallback;
		}
	}

	private static object ReadProperty(object obj, string name) => Homm3FortressPredatorInstinctRuntime.ReadProperty(obj, name);

	private static Type FindType(Assembly assembly, string[] hints)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			if (!string.IsNullOrWhiteSpace(hint) && assembly.GetType(hint) is { } type)
				return type;
		}
		return null;
	}

	private static Type ResolveTypeByHints(Assembly assembly, string[] hints, string id)
		=> FindType(assembly, hints) ?? throw new TypeLoadException(id + " type not found from [" + string.Join(",", hints ?? Array.Empty<string>()) + "]");

	private static PropertyInfo RequireProperty(Type type, string name)
	{
		for (var cur = type; cur != null; cur = cur.BaseType)
		{
			var property = cur.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			if (property != null)
				return property;
		}
		throw new MissingMemberException((type?.FullName ?? "null") + "." + name);
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

	private static MethodInfo FindMethodByName(Type type, string[] names, int parameterCount, bool wantStatic = false, bool declaredOnly = false)
	{
		if (type == null)
			return null;
		var flags = BindingFlags.Public | BindingFlags.NonPublic | (wantStatic ? BindingFlags.Static : BindingFlags.Instance);
		if (declaredOnly)
			flags |= BindingFlags.DeclaredOnly;
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in type.GetMethods(flags))
			{
				if (method.Name == name && method.GetParameters().Length == parameterCount)
					return method;
			}
		}
		return null;
	}

	private static void Patch(Harmony harmony, MethodInfo target, string prefixName, string postfixName)
	{
		const BindingFlags flags = BindingFlags.Static | BindingFlags.NonPublic;
		var prefix = prefixName == null ? null : typeof(Homm3RampartAvengerStrikeRuntime).GetMethod(prefixName, flags);
		var postfix = postfixName == null ? null : typeof(Homm3RampartAvengerStrikeRuntime).GetMethod(postfixName, flags);
		if (prefix != null && !GameMember.IsHarmonyPatchCompatible(target, prefix, out var prefixReason))
			throw new MissingMethodException("prefix incompatible for " + target.DeclaringType?.FullName + "." + target.Name + ": " + prefixReason);
		if (postfix != null && !GameMember.IsHarmonyPatchCompatible(target, postfix, out var postfixReason))
			throw new MissingMethodException("postfix incompatible for " + target.DeclaringType?.FullName + "." + target.Name + ": " + postfixReason);
		harmony.Patch(target,
			prefix: prefix == null ? null : new HarmonyMethod(prefix),
			postfix: postfix == null ? null : new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static void LogInfo(string message)
	{
		if (_infoLogged++ < 300)
			_log?.LogInfo("HoMM3 Rampart Avenger: " + message);
	}

	private static void LogLimited(string message)
	{
		if (_logged++ < 80)
			_log?.LogWarning("HoMM3 Rampart Avenger: " + message);
	}
}
