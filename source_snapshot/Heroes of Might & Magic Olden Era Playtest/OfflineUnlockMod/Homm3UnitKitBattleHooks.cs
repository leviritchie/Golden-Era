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
using Kind = OfflineUnlockMod.Homm3UnitKitRules.RuleKind;

namespace OfflineUnlockMod;

/// <summary>
/// Battle hooks for the unit design kits (contract docs/unit_ability_pass_20261121/RUNTIME_CONTRACT.md). The damage
/// math lives in <see cref="Homm3UnitKitRuntime"/>; this class supplies the battle facts and the rules that act:
///
/// - Turn stamps (turn_state, counter_state): round / action / wait / defend dispatchers, the ability commit (which
///   ability a unit committed, whether it is a shot, counterattacks), and moves seen at the attack builder (eqd.bhqa
///   path, eqd.bhpr path, eqd.bhqd movePath).
/// - Per-round damage records (hit_this_round, retribution) and attack-taken charges (stored_fury): own prefix and
///   postfix on the 8-argument Unit damage method, next to the committed-damage owner.
/// - Free attacks (guard_strike, zone_shot, spell_echo) are queued through the attack builder like Rampart Avenger
///   strikes (eqd.bhqa: unitId, anchorId, path, targetHexIds, EMovementType, abilityType, abilityIndex, free, forced).
///   The queued AttackStep is marked so its hits deal the rule's percent and so it triggers nothing here.
///   zone_shot is queued when the mover's build finishes and moved in front of the mover's first AttackStep.
/// - arrival_buff: at the mover's ActionEnded. kill_extra_action: a kill by the holder's active ability adds the
///   rule's buff (add_action_points) at once, once per round.
/// - Nested damage (bodyguard share, brand_splash, ability_feedback): a second Unit damage call from the damage
///   postfix, the pattern of <see cref="NativeCombatWriteGateway.TryInvokeRedirectedDamage"/>. Nested hits are never
///   re-scaled and never splash again.
/// - charge_no_counter: counter-queue prefix (eqd.bhqp) while the holder's attack is building after a long enough move.
/// - scatter: a queued move (eqd.bhpr) away from a melee attacker the holder survived.
/// - spell_echo: hero battle ability cast body (eov.bhav) target hexes.
///
/// Every hook catches its own errors: a failure disables that rule kind for the session (one log line) and the battle
/// goes on natively. Nothing here is seen by the AI or the damage forecast.
/// Proof tier: build only; runtime unproven.
/// </summary>
internal static class Homm3UnitKitBattleHooks
{
	private const int StatePlaying = 2;
	private const int DefaultAttackAbilityType = 1;
	private const int AlternativeAttackAbilityType = 3;
	private const int MoveSourceDefault = 1;
	private const int ArrivalBuffDuration = 2;

	internal struct CommitInfo
	{
		internal long Serial;
		internal EAbilityType Type;
		internal bool Ranged;
		internal int Index;
		/// <summary>A basic attack, alternative attack, counterattack, or an ability with an attack type.</summary>
		internal bool IsAttack;
	}

	private static class Pins
	{
		private static string At(string[] names, int index) => names != null && names.Length > index ? names[index] : "";
		internal static string LogicHubs => At(GameSymbols.InfernoGating.LogicHubsMembers, 0);
		internal static string HubsRoundHub => At(GameSymbols.InfernoGating.HubsRoundHubMembers, 0);
		internal static string LogicState => At(GameSymbols.InfernoGating.LogicStateMembers, 0);
		internal static string LogicGrid => At(GameSymbols.InfernoGating.LogicGridMembers, 0);
		internal static string StateSideWrappers => At(GameSymbols.InfernoGating.StateSideWrappersMembers, 0);
		internal static string GridHexes => At(GameSymbols.InfernoGating.GridHexesMembers, 0);
		internal static string FieldObjectSide => At(GameSymbols.InfernoGating.FieldObjectSideMembers, 0);
		internal static string UnitStat => At(GameSymbols.InfernoGating.UnitStatMembers, 0);
		internal static string HeroAbilitySide => At(GameSymbols.InfernoGating.HeroAbilitySideMembers, 0);
		internal static string LogicBuilder => At(GameSymbols.RampartAvengerStrike.LogicAttackBuilderMembers, 0);
		internal static string LogicQueue => At(GameSymbols.RampartAvengerStrike.LogicStepQueueMembers, 0);
		internal static string QueuePending => At(GameSymbols.RampartAvengerStrike.QueuePendingMembers, 0);
		internal static string AttackTargets => At(GameSymbols.RampartAvengerStrike.AttackStepTargetHexesMembers, 0);
		internal static string AttackAttacker => At(GameSymbols.RampartAvengerStrike.AttackStepAttackerMembers, 0);
		internal static string StepState => At(GameSymbols.CounterattackStepLaws.StepStateMembers, 0);
		internal static string StatePathfinder => At(GameSymbols.RampartAvengerStrike.StatePathfinderMembers, 0);
		internal static string FieldObjectId => At(GameSymbols.RampartAvengerStrike.FieldObjectIdMembers, 0);
		internal static string FieldObjectPosition => At(GameSymbols.RampartAvengerStrike.FieldObjectPositionMembers, 0);
		internal static string PositionHex => At(GameSymbols.RampartAvengerStrike.PositionHexMembers, 0);
		internal static string StatMovementType => At(GameSymbols.RampartAvengerStrike.UnitStatMovementTypeMembers, 0);
	}

	private sealed class Stamp
	{
		internal bool Acted;
		internal bool Waited;
		internal bool WaitedThisAction;
		internal bool MovedRound;
		internal bool MovedThisAction;
		internal int MoveHexesThisAction;
		internal int Counters;
	}

	private sealed class Scaled
	{
		internal long Key;
		internal int Percent;
		internal string Name;
	}

	private sealed class FieldUnit
	{
		internal Unit Unit;
		internal long Key;
		internal int Id;
		internal IntPtr Side;
		internal readonly List<BattleHex> Hexes = new();
	}

	private sealed class Field
	{
		internal int Frame;
		internal BattleHex[] Hexes;
		internal readonly Dictionary<IntPtr, FieldUnit> Units = new();
	}

	private sealed class ZoneShot
	{
		internal FieldUnit Holder;
		internal Homm3UnitKitRules.Rule Rule;
		internal long MoverKey;
		internal IntPtr MoverPointer;
		internal int DestinationHexId;
	}

	private sealed class BattleState
	{
		internal object Logic;
		internal IntPtr LogicPointer;
		internal IntPtr HubPointer;
		internal HashSet<IntPtr> Wrappers;
		internal int Round;
		internal readonly Dictionary<long, Stamp> Stamps = new();
		internal readonly Dictionary<long, bool> LastActionMoved = new();
		/// <summary>Target key → (caster key → caster side) of every stack that damaged it this round.</summary>
		internal readonly Dictionary<long, Dictionary<long, IntPtr>> DamagedBy = new();
		/// <summary>Side pointer → keys of enemy stacks that damaged any stack of that side this round.</summary>
		internal readonly Dictionary<IntPtr, HashSet<long>> SideDamagedBy = new();
		internal readonly Dictionary<(long, Kind), int> Uses = new();
		internal readonly HashSet<long> KillExtraUsed = new();
		internal readonly HashSet<IntPtr> OwnSteps = new();
		internal readonly Dictionary<IntPtr, Scaled> ScaledSteps = new();
		internal readonly List<ZoneShot> ZoneFallback = new();
		internal Field FieldCache;
	}

	/// <summary>One Unit damage call: the raw damage before any percent rule, and the guard that claimed a share.</summary>
	private sealed class HitFrame
	{
		internal HitFrame Previous;
		internal IntPtr Receiver;
		internal int RawDamage;
		internal Unit Guard;
		internal long GuardKey;
		internal int GuardShare;
	}

	private static readonly object Gate = new();
	private static readonly List<BattleState> Battles = new();
	private static readonly Dictionary<long, CommitInfo> Commits = new();
	private static readonly HashSet<string> Failed = new(StringComparer.Ordinal);
	private static long _serial;
	private static Scaled _activeScaled;
	private static ManualLogSource _log;
	private static bool _attempted;
	private static bool _coreLive;
	private static bool _damageLive;
	private static bool _queueLive;
	private static bool _chargeLive;
	private static bool _castLive;
	private static int _events;
	private static int _warnings;

	[ThreadStatic] private static int _nested;
	[ThreadStatic] private static HitFrame _frame;
	[ThreadStatic] private static int _buildDepth;
	[ThreadStatic] private static bool _ownQueue;
	[ThreadStatic] private static bool _flushing;
	[ThreadStatic] private static List<ZoneShot> _deferredZone;
	[ThreadStatic] private static HashSet<IntPtr> _buildSnapshot;
	[ThreadStatic] private static BattleState _buildBattle;
	[ThreadStatic] private static List<IntPtr> _chargeAttackers;

	private static MethodInfo _queueAttack;
	private static MethodInfo _queueMove;
	private static MethodInfo _hexDistance;
	private static Type _attackStepType;
	private static IntPtr _attackStepClass;
	private static Type _moveSourceType;
	private static readonly Dictionary<Type, PropertyInfo[]> AttackTypeProperties = new();
	private static readonly List<Homm3UnitKitRules.Rule> BrandRules = CollectRules(Kind.BrandSplash);

	/// <summary>True while a nested kit hit (bodyguard share, splash, feedback) is being dealt.</summary>
	internal static bool InNestedDamage => _nested > 0;

	// ------------------------------------------------------------------ registration

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		if (Homm3UnitKitRules.Rules.Count == 0)
			return;
		var hexAssembly = typeof(TransferBattle).Assembly;
		Type logicType = null;
		try
		{
			logicType = ResolveTypeByHints(hexAssembly, GameSymbols.InfernoGating.BattleLogicTypeHints, "unitkit.battleLogic");
			var init = logicType.GetMethod("Init", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
				           new[] { typeof(int), typeof(TransferBattle), typeof(bool), typeof(bool) }, null)
			           ?? throw new MissingMethodException("BattleLogic.Init(int, TransferBattle, bool, bool)");
			var hubType = RequireProperty(RequireProperty(logicType, Pins.LogicHubs).PropertyType, Pins.HubsRoundHub).PropertyType;
			var roundStarted = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.RoundStartedDispatcher);
			var actionStarted = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.ActionStartedDispatcher);
			var actionEnded = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.ActionEndedDispatcher);
			var skip = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.SkipDispatcher);
			var wait = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.WaitDispatcher);
			var commitType = Homm3BulwarkRunesRuntime.ResolveAbilityRuntimeType() ?? throw new TypeLoadException("ability runtime type not found");
			var commit = Homm3BulwarkRunesRuntime.ResolveAbilityCommitExecuteMethod(commitType) ?? throw new MissingMethodException("AbilityCommitExecute not found");
			if (roundStarted == null || actionStarted == null || actionEnded == null || skip == null || wait == null)
				throw new MissingMethodException("a round-hub dispatcher (round/action/skip/wait) was not resolved");
			var stateType = RequireProperty(logicType, Pins.LogicState).PropertyType;
			var pathfinderType = RequireProperty(stateType, Pins.StatePathfinder).PropertyType;
			_hexDistance = FindMethodByName(pathfinderType, GameSymbols.RampartAvengerStrike.HexDistance.NameHints, 2, wantStatic: true)
			               ?? throw new MissingMethodException("eqc hex distance");
			Patch(harmony, init, null, nameof(PostfixBattleLogicInit));
			Patch(harmony, roundStarted, null, nameof(PostfixRoundStarted));
			Patch(harmony, actionStarted, null, nameof(PostfixActionStarted));
			Patch(harmony, actionEnded, null, nameof(PostfixActionEnded));
			Patch(harmony, skip, null, nameof(PostfixSkip));
			Patch(harmony, wait, null, nameof(PostfixWait));
			Patch(harmony, commit, nameof(PrefixAbilityCommitExecute), null);
			_coreLive = true;
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 unit kit battle hooks NOT registered (turn_state, counter_state, first_hit, streak and fury rules, abilityOnly and attack filters, adjacency rules and every acting rule stay off): "
				+ ex.GetBaseException().Message);
			return;
		}

		try
		{
			var unitType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsBattleUnit) ?? throw new TypeLoadException("battle Unit type");
			MethodInfo damage = null;
			foreach (var name in GameSymbols.BattleEventLaws.BattleUnitApplyDamage.NameHints ?? Array.Empty<string>())
			{
				damage = ResolveDeclaredVoidMethod(unitType, name, 8);
				if (damage != null)
					break;
			}
			if (damage == null)
				throw new MissingMethodException("8-argument Unit damage method");
			var prefix = GameMember.FindOwnedPatchMethod(typeof(Homm3UnitKitBattleHooks), nameof(PrefixApplyDamage));
			var postfix = GameMember.FindOwnedPatchMethod(typeof(Homm3UnitKitBattleHooks), nameof(PostfixApplyDamage));
			if (prefix == null || postfix == null)
				throw new MissingMethodException("damage patch methods");
			if (!GameMember.IsHarmonyPatchCompatible(damage, prefix, out var reason) || !GameMember.IsHarmonyPatchCompatible(damage, postfix, out reason))
				throw new MissingMethodException("damage patch incompatible: " + reason);
			harmony.Patch(damage, prefix: new HarmonyMethod(prefix) { priority = Priority.First }, postfix: new HarmonyMethod(postfix) { priority = Priority.Low });
			_damageLive = true;
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 unit kit battle hooks [damage] NOT registered (hit_this_round, retribution, stored_fury, kill_extra_action, bodyguard, brand_splash, ability_feedback, scatter stay off): "
				+ ex.GetBaseException().Message);
		}

		try
		{
			var builderType = RequireProperty(logicType, Pins.LogicBuilder).PropertyType;
			var queueType = RequireProperty(logicType, Pins.LogicQueue).PropertyType;
			RequireProperty(queueType, Pins.QueuePending);
			_queueAttack = FindMethodByName(builderType, GameSymbols.RampartAvengerStrike.QueueAttack.NameHints, 9) ?? throw new MissingMethodException("eqd.bhqa (queue attack)");
			_queueMove = FindMethodByName(builderType, GameSymbols.RampartAvengerStrike.QueueMove.NameHints, 6) ?? throw new MissingMethodException("eqd.bhpr (queue move)");
			_moveSourceType = _queueMove.GetParameters()[3].ParameterType;
			_attackStepType = ResolveTypeByHints(hexAssembly, GameSymbols.RampartAvengerStrike.AttackStepTypeHints, "unitkit.attackStep");
			RequireProperty(_attackStepType, Pins.AttackTargets);
			RequireProperty(_attackStepType, Pins.AttackAttacker);
			RequireProperty(_attackStepType, Pins.StepState);
			_attackStepClass = NativeClassPointer(_attackStepType);
			if (_attackStepClass == IntPtr.Zero)
				throw new TypeLoadException("AttackStep native class pointer unresolved");
			var attackBegin = FindMethodByName(_attackStepType, GameSymbols.RampartAvengerStrike.AttackStepBegin.NameHints, 0, declaredOnly: true)
			                  ?? throw new MissingMethodException("eux.Begin");
			var buildAttack = FindMethodByName(builderType, GameSymbols.FortressPredatorInstinct.BuildAttack.NameHints, 7)
			                  ?? throw new MissingMethodException("eqd.bhqd (build attack)");
			Patch(harmony, attackBegin, nameof(PrefixAttackStepBegin), nameof(PostfixAttackStepBegin));
			PatchWithFinalizer(harmony, _queueAttack, nameof(PrefixQueueAttack), nameof(FinalizerBuild));
			PatchWithFinalizer(harmony, _queueMove, nameof(PrefixQueueMove), nameof(FinalizerBuild));
			PatchWithFinalizer(harmony, buildAttack, nameof(PrefixBuildAttack), nameof(FinalizerBuildAttack));
			_queueLive = true;
			var queueCounter = FindMethodByName(builderType, GameSymbols.FortressPredatorInstinct.QueueCounter.NameHints, 7);
			if (queueCounter != null)
			{
				Patch(harmony, queueCounter, nameof(PrefixQueueCounter), null);
				_chargeLive = true;
			}
		}
		catch (Exception ex)
		{
			_queueAttack = null; // QueueStrike refuses; patches already applied stay inert
			_queueMove = null;
			_log?.LogWarning("HoMM3 unit kit battle hooks [queue] NOT registered (moved_target, stood_ground, guard_strike, zone_shot, spell_echo, charge_no_counter, scatter stay off): "
				+ ex.GetBaseException().Message);
		}

		if (_queueLive && Homm3UnitKitRuntime.TableHas(Kind.SpellEcho))
		{
			try
			{
				var abilityType = ResolveTypeByHints(hexAssembly, GameSymbols.InfernoGating.HeroAbilityTypeHints, "unitkit.heroAbility");
				foreach (var name in GameSymbols.FortressPredatorInstinct.HeroAbilityCast.NameHints ?? Array.Empty<string>())
				{
					if (string.IsNullOrEmpty(name) || _castLive)
						continue;
					foreach (var method in abilityType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
					{
						if (method.Name == name && method.ReturnType == typeof(void) && method.GetParameters().Length == 4)
						{
							Patch(harmony, method, null, nameof(PostfixHeroAbilityCast));
							_castLive = true;
							break;
						}
					}
				}
				if (!_castLive)
					throw new MissingMethodException("hero ability cast body (eov.bhav)");
			}
			catch (Exception ex)
			{
				_log?.LogWarning("HoMM3 unit kit battle hooks [spell echo] NOT registered (spell_echo stays off): " + ex.GetBaseException().Message);
			}
		}
		_log?.LogInfo("HoMM3 unit kit battle hooks registered: turn stamps + commits, damage=" + _damageLive + ", queue=" + _queueLive
			+ ", charge=" + _chargeLive + ", spell echo=" + _castLive + ".");
	}

	internal static void ClearForBattle()
	{
		lock (Gate)
		{
			Commits.Clear();
			_activeScaled = null;
		}
	}

	// ------------------------------------------------------------------ facts for Homm3UnitKitRuntime

	internal static bool TryGetCommit(long casterKey, out CommitInfo commit)
	{
		lock (Gate)
			return Commits.TryGetValue(casterKey, out commit);
	}

	internal static int ScaledStrikePercent(long casterKey, out string name)
	{
		name = null;
		lock (Gate)
		{
			if (_activeScaled == null || _activeScaled.Key != casterKey)
				return 0;
			name = _activeScaled.Name;
			return _activeScaled.Percent;
		}
	}

	internal static bool TurnFact(int fact, Unit holder, long holderKey, long targetKey, out string why)
	{
		why = null;
		if (!_coreLive)
			return false;
		var battle = FindBattleForUnit(holder);
		if (battle == null)
			return false;
		lock (Gate)
		{
			switch (fact)
			{
				case Homm3UnitKitRules.FactStoodGround:
				{
					if (!_queueLive)
						return false;
					battle.Stamps.TryGetValue(holderKey, out var own);
					battle.LastActionMoved.TryGetValue(holderKey, out var moved);
					if (moved || (own != null && own.MovedThisAction))
						return false;
					why = "did not move";
					return true;
				}
				case Homm3UnitKitRules.FactUnactedTarget:
					if (battle.Stamps.TryGetValue(targetKey, out var a) && a.Acted)
						return false;
					why = "target has not acted";
					return true;
				case Homm3UnitKitRules.FactMovedTarget:
					if (!_queueLive || !battle.Stamps.TryGetValue(targetKey, out var m) || !m.MovedRound)
						return false;
					why = "target moved this round";
					return true;
				case Homm3UnitKitRules.FactWaitedTarget:
					if (!battle.Stamps.TryGetValue(targetKey, out var w) || !w.Waited)
						return false;
					why = "target waited";
					return true;
			}
		}
		return false;
	}

	internal static bool CounterFact(int state, Unit target, long targetKey, out string why)
	{
		why = null;
		var battle = FindBattleForUnit(target);
		if (battle == null)
			return false;
		int counters;
		lock (Gate)
			counters = battle.Stamps.TryGetValue(targetKey, out var stamp) ? stamp.Counters : 0;
		if (state == Homm3UnitKitRules.CounterUsed)
		{
			if (counters <= 0)
				return false;
			why = "target has counterattacked";
			return true;
		}
		// numCounters is the unit's counterattacks per round (Core stat); unreadable counts as one.
		var limit = Homm3BuffDebuffNativeAdapter.TryAdjustUnitIntStat(target, "numCounters", 0, out var n, out _, out _) ? n : 1;
		if (limit > 0 && counters < limit)
			return false;
		why = "target has no counterattack left";
		return true;
	}

	internal static bool TryNeighbourhood(Unit holder, Unit target, out int flankAllies, out int targetAllies, out int holderEnemies)
	{
		flankAllies = targetAllies = holderEnemies = 0;
		var battle = FindBattleForUnit(holder);
		var field = battle == null ? null : Snapshot(battle);
		if (field == null || !field.Units.TryGetValue(holder.Pointer, out var h) || !field.Units.TryGetValue(target.Pointer, out var t))
			return false;
		foreach (var other in field.Units.Values)
		{
			if (other == h || other == t)
				continue;
			if (other.Side == h.Side && Adjacent(other, t))
				flankAllies++;
			if (other.Side == t.Side && Adjacent(other, t))
				targetAllies++;
			if (other.Side != h.Side && Adjacent(other, h))
				holderEnemies++;
		}
		if (t.Side != h.Side && Adjacent(t, h))
			holderEnemies++;
		return true;
	}

	internal static int OtherAlliesHitThisRound(long targetKey, Unit holder, long holderKey)
	{
		var battle = FindBattleForUnit(holder);
		if (battle == null || !_damageLive)
			return 0;
		var side = SidePointer(holder);
		lock (Gate)
		{
			if (!battle.DamagedBy.TryGetValue(targetKey, out var casters))
				return 0;
			var count = 0;
			foreach (var entry in casters)
			{
				if (entry.Key != holderKey && entry.Value == side)
					count++;
			}
			return count;
		}
	}

	internal static bool DamagedSideThisRound(Unit holder, long targetKey)
	{
		var battle = FindBattleForUnit(holder);
		if (battle == null || !_damageLive)
			return false;
		var side = SidePointer(holder);
		lock (Gate)
			return battle.SideDamagedBy.TryGetValue(side, out var set) && set.Contains(targetKey);
	}

	internal static bool IsHealthiestOfItsSide(Unit target)
	{
		var battle = FindBattleForUnit(target);
		var field = battle == null ? null : Snapshot(battle);
		if (field == null || !field.Units.TryGetValue(target.Pointer, out var t) || !DamageKillMapping.TryReadStackHealth(target, out var own))
			return false;
		foreach (var other in field.Units.Values)
		{
			if (other == t || other.Side != t.Side)
				continue;
			if (DamageKillMapping.TryReadStackHealth(other.Unit, out var health) && health > own)
				return false;
		}
		return true;
	}

	internal static bool IsBehindBlocked(Unit holder, Unit target, out string why)
	{
		why = null;
		var battle = FindBattleForUnit(holder);
		var field = battle == null ? null : Snapshot(battle);
		if (field == null || !field.Units.TryGetValue(target.Pointer, out var t) || !field.Units.TryGetValue(holder.Pointer, out var h))
			return false;
		var from = MainHex(h);
		var at = MainHex(t);
		if (from == null || at == null)
			return false;
		var dx = at.position.x - from.position.x;
		var dz = at.position.z - from.position.z;
		var length = Math.Sqrt(dx * dx + dz * dz);
		if (length < 1e-4)
			return false;
		BattleHex best = null;
		var bestCos = -2.0;
		foreach (var hex in field.Hexes)
		{
			if (hex == null || t.Hexes.Contains(hex) || Distance(at, hex) != 1)
				continue;
			var hx = hex.position.x - at.position.x;
			var hz = hex.position.z - at.position.z;
			var hl = Math.Sqrt(hx * hx + hz * hz);
			if (hl < 1e-4)
				continue;
			var cos = (hx * dx + hz * dz) / (hl * length);
			if (cos > bestCos)
			{
				bestCos = cos;
				best = hex;
			}
		}
		if (best == null || bestCos < 0.5)
		{
			why = "battlefield edge behind it";
			return true;
		}
		if (best.blockedByMap || best.blockedFromAll || best.tempBlocked)
		{
			why = "obstacle behind it";
			return true;
		}
		foreach (var other in field.Units.Values)
		{
			if (other != t && other.Hexes.Contains(best))
			{
				why = "a stack behind it";
				return true;
			}
		}
		return false;
	}

	/// <summary>bodyguard: an adjacent friendly guard of <paramref name="receiver"/> claims a share of the hit being
	/// committed now; the damage postfix deals it to the guard. False when the hit frame is not live.</summary>
	internal static bool TryClaimBodyguard(Unit receiver, long receiverKey, out Homm3UnitKitRules.Rule rule, out string guardName)
	{
		rule = null;
		guardName = null;
		var frame = _frame;
		if (!_damageLive || frame == null || frame.Receiver != receiver.Pointer || frame.Guard != null || frame.RawDamage <= 0)
			return false;
		var battle = FindBattleForUnit(receiver);
		var field = battle == null ? null : Snapshot(battle);
		if (field == null || !field.Units.TryGetValue(receiver.Pointer, out var r))
			return false;
		foreach (var other in field.Units.Values)
		{
			if (other == r || other.Side != r.Side || !Adjacent(other, r))
				continue;
			var guardRule = Homm3UnitKitRuntime.FindRule(other.Unit, other.Key, Kind.Bodyguard);
			if (guardRule == null || !IsAlive(other.Unit))
				continue;
			frame.Guard = other.Unit;
			frame.GuardKey = other.Key;
			frame.GuardShare = guardRule.Percent;
			rule = guardRule;
			guardName = DescribeUnit(other.Unit);
			return true;
		}
		return false;
	}

	// ------------------------------------------------------------------ battle lifecycle and turn stamps

	private static void PostfixBattleLogicInit(object __instance)
	{
		try
		{
			if (__instance is not Il2CppObjectBase logic)
				return;
			var hub = ReadProperty(ReadProperty(__instance, Pins.LogicHubs), Pins.HubsRoundHub) as Il2CppObjectBase;
			lock (Gate)
			{
				Battles.RemoveAll(b => b.LogicPointer == logic.Pointer);
				Battles.Add(new BattleState { Logic = __instance, LogicPointer = logic.Pointer, HubPointer = hub?.Pointer ?? IntPtr.Zero });
				while (Battles.Count > 6)
					Battles.RemoveAt(0);
			}
		}
		catch (Exception ex)
		{
			Fail("battle init", ex);
		}
	}

	private static void PostfixRoundStarted(object __instance, object[] __args)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			if (battle == null)
				return;
			var round = __args != null && __args.Length > 1 && __args[1] is BattleEventArgs args ? args.roundNumber : battle.Round + 1;
			lock (Gate)
			{
				battle.Round = round;
				foreach (var stamp in battle.Stamps.Values)
				{
					stamp.Acted = stamp.Waited = stamp.WaitedThisAction = stamp.MovedRound = false;
					stamp.Counters = 0;
				}
				battle.DamagedBy.Clear();
				battle.SideDamagedBy.Clear();
				battle.Uses.Clear();
				battle.KillExtraUsed.Clear();
				battle.ZoneFallback.Clear();
				_activeScaled = null;
			}
			Homm3UnitKitRuntime.OnRoundStarted();
		}
		catch (Exception ex)
		{
			Fail("round start", ex);
		}
	}

	private static void PostfixActionStarted(object __instance, object[] __args)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			var unit = battle == null ? null : TargetOf(__args);
			var key = unit == null ? 0 : Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
			if (key == 0)
				return;
			lock (Gate)
			{
				var stamp = StampOf(battle, key);
				if (!stamp.MovedThisAction && !stamp.WaitedThisAction)
					stamp.MoveHexesThisAction = 0;
			}
		}
		catch (Exception ex)
		{
			Fail("action start", ex);
		}
	}

	private static void PostfixActionEnded(object __instance, object[] __args)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			var unit = battle == null ? null : TargetOf(__args);
			var key = unit == null ? 0 : Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
			lock (Gate)
				_activeScaled = null;
			if (key == 0)
				return;
			bool moved;
			lock (Gate)
			{
				var stamp = StampOf(battle, key);
				if (!stamp.WaitedThisAction)
					stamp.Acted = true;
				moved = stamp.MovedThisAction;
				battle.LastActionMoved[key] = moved;
				stamp.MovedThisAction = false;
				stamp.WaitedThisAction = false;
				stamp.MoveHexesThisAction = 0;
			}
			if (moved && Homm3UnitKitRuntime.TableHas(Kind.ArrivalBuff))
				RunArrivalBuff(battle, unit, key);
		}
		catch (Exception ex)
		{
			Fail("action end", ex);
		}
	}

	private static void PostfixWait(object __instance, object[] __args)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			var unit = battle == null ? null : TargetOf(__args);
			var key = unit == null ? 0 : Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
			if (key == 0)
				return;
			lock (Gate)
			{
				var stamp = StampOf(battle, key);
				stamp.Waited = true;
				stamp.WaitedThisAction = true;
				stamp.Acted = false; // Wait is not acting, whichever order Wait and ActionEnded arrive in
			}
		}
		catch (Exception ex)
		{
			Fail("wait", ex);
		}
	}

	private static void PostfixSkip(object __instance, object[] __args)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			var unit = battle == null ? null : TargetOf(__args);
			var key = unit == null ? 0 : Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
			if (key == 0)
				return;
			lock (Gate)
				StampOf(battle, key).Acted = true; // Defend is acting
		}
		catch (Exception ex)
		{
			Fail("defend", ex);
		}
	}

	/// <summary>Before the committed ability resolves: what the caster committed (attack type, shot, slot).</summary>
	private static void PrefixAbilityCommitExecute(object __instance)
	{
		try
		{
			if (!Homm3BulwarkRunesRuntime.TryReadCommittedAbility(__instance, out var casterObject, out var abilityType, out var index, out _))
				return;
			if (abilityType != EAbilityType.DefaultAttack && abilityType != EAbilityType.AlternativeAttack
			    && abilityType != EAbilityType.Ability && abilityType != EAbilityType.CounterAttack)
				return;
			var caster = AsUnit(casterObject);
			var key = caster == null ? 0 : Homm3DirectStateIdentity.ResolveKeyOrZero(caster);
			if (key == 0)
				return;
			var logic = Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.BulwarkRunesLaws.AbilityRuntimeLogicConfigMembers);
			var attackType = ReadString(logic, GameSymbols.BulwarkRunesLaws.AbilityLogicAttackTypeMembers);
			if (abilityType == EAbilityType.Ability && string.IsNullOrWhiteSpace(attackType))
			{
				var moveType = ReadString(logic, GameSymbols.BulwarkRunesLaws.AbilityLogicMoveTypeMembers);
				var castType = ReadString(logic, GameSymbols.BulwarkRunesLaws.AbilityLogicCastTypeMembers);
				if (!string.IsNullOrWhiteSpace(moveType) && string.IsNullOrWhiteSpace(castType))
					return; // movement-only ability: a move, not a commit the rules read
			}
			bool ranged;
			if (!string.IsNullOrWhiteSpace(attackType))
			{
				var t = attackType.Trim();
				ranged = !t.Equals("melee", StringComparison.OrdinalIgnoreCase);
			}
			else
				ranged = abilityType != EAbilityType.CounterAttack && abilityType != EAbilityType.Ability && Homm3FortressPredatorInstinctRuntime.IsRanged(caster);
			var isAttack = abilityType != EAbilityType.Ability || !string.IsNullOrWhiteSpace(attackType);
			lock (Gate)
			{
				Commits[key] = new CommitInfo { Serial = ++_serial, Type = abilityType, Ranged = ranged, Index = index, IsAttack = isAttack };
				if (abilityType == EAbilityType.CounterAttack)
				{
					var battle = FindBattleForUnitLocked(caster);
					if (battle != null)
						StampOf(battle, key).Counters++;
				}
			}
		}
		catch (Exception ex)
		{
			Fail("ability commit", ex);
		}
	}

	// ------------------------------------------------------------------ damage step: records and acting rules

	private static void PrefixApplyDamage(object __instance, ref int __3, bool __5, out HitFrame __state)
	{
		__state = null;
		try
		{
			if (__instance is not Il2CppObjectBase receiver || receiver.Pointer == IntPtr.Zero)
				return;
			__state = new HitFrame { Previous = _frame, Receiver = receiver.Pointer, RawDamage = __5 ? 0 : __3 };
			_frame = __state;
		}
		catch
		{
			__state = null;
		}
	}

	private static void PostfixApplyDamage(object __instance, object __0, object __1, object __2, ref int __3, object __4, bool __5, float __6, bool __7,
		MethodBase __originalMethod, HitFrame __state)
	{
		if (__state == null)
			return;
		_frame = __state.Previous;
		if (_nested > 0 || __5 || __3 <= 0)
			return;
		try
		{
			var receiver = AsUnit(__instance);
			var caster = AsUnit(__0);
			if (receiver == null)
				return;
			var battle = FindBattleForUnit(receiver);
			if (battle == null)
				return;
			var receiverKey = Homm3DirectStateIdentity.ResolveKeyOrZero(receiver);
			var casterKey = caster == null ? 0 : Homm3DirectStateIdentity.ResolveKeyOrZero(caster);
			var receiverSide = SidePointer(receiver);
			var casterSide = caster == null ? IntPtr.Zero : SidePointer(caster);
			var enemyHit = casterKey != 0 && receiverKey != 0 && casterKey != receiverKey && casterSide != IntPtr.Zero && casterSide != receiverSide;
			CommitInfo commit = default;
			var hasCommit = enemyHit && TryGetCommit(casterKey, out commit);
			var unitAttack = hasCommit && commit.IsAttack;
			if (enemyHit)
			{
				lock (Gate)
				{
					if (!battle.DamagedBy.TryGetValue(receiverKey, out var casters))
						battle.DamagedBy[receiverKey] = casters = new Dictionary<long, IntPtr>();
					casters[casterKey] = casterSide;
					if (!battle.SideDamagedBy.TryGetValue(receiverSide, out var attackers))
						battle.SideDamagedBy[receiverSide] = attackers = new HashSet<long>();
					attackers.Add(casterKey);
				}
			}
			if (unitAttack)
				Homm3UnitKitRuntime.NoteAttackTaken(receiver, receiverKey, casterKey, commit.Serial);
			var alive = IsAlive(receiver);
			var method = __originalMethod as MethodInfo;

			if (!alive && hasCommit && commit.Type == EAbilityType.Ability)
				Guard(Kind.KillExtraAction, () => RunKillExtraAction(battle, caster, casterKey, commit));
			if (__state.Guard != null && method != null)
			{
				var frame = __state;
				Guard(Kind.Bodyguard, () => RunBodyguard(method, frame, __0, __1, __2, __4, __6, __7));
			}
			if (unitAttack && BrandRules.Count > 0 && method != null)
			{
				var dealt = __3;
				Guard(Kind.BrandSplash, () => RunBrandSplash(battle, method, receiver, dealt, __0, __1, __2, __4, __6, __7));
			}
			if (hasCommit && commit.Type == EAbilityType.Ability && method != null && Homm3UnitKitRuntime.TableHas(Kind.AbilityFeedback))
				Guard(Kind.AbilityFeedback, () => RunAbilityFeedback(battle, method, caster, casterKey, commit, __1, __2, __4, __6, __7));
			if (alive && unitAttack && !commit.Ranged && _queueLive && Homm3UnitKitRuntime.TableHas(Kind.Scatter))
				Guard(Kind.Scatter, () => RunScatter(battle, receiver, receiverKey, caster, casterKey, commit));
		}
		catch (Exception ex)
		{
			Fail("damage postfix", ex);
		}
	}

	private static void RunKillExtraAction(BattleState battle, Unit holder, long holderKey, CommitInfo commit)
	{
		var rule = Homm3UnitKitRuntime.FindRule(holder, holderKey, Kind.KillExtraAction);
		if (rule == null || (rule.AbilityIndex >= 0 && rule.AbilityIndex != commit.Index) || !IsAlive(holder))
			return;
		lock (Gate)
		{
			if (!battle.KillExtraUsed.Add(holderKey))
				return;
		}
		if (Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(holder, rule.Buff, holder, 1, 1, 0, true, out _, out var fail))
			LogEvent(rule.Name + ": " + DescribeUnit(holder) + " destroyed a stack with its ability and acts again (" + rule.Buff + ").");
		else
			LogWarning(rule.Name + ": extra-action buff " + rule.Buff + " was not added to " + DescribeUnit(holder) + ": " + fail);
	}

	private static void RunBodyguard(MethodInfo method, HitFrame frame, object caster, object castSource, object dealer, object fromMech, float scalar, bool cumulative)
	{
		if (frame.Guard == null || !IsAlive(frame.Guard))
			return;
		var share = (int)Math.Max(1L, (long)frame.RawDamage * frame.GuardShare / 100L);
		if (DealNested(method, frame.Guard, caster, castSource, dealer, share, fromMech, scalar, cumulative))
			LogEvent("bodyguard: " + DescribeUnit(frame.Guard) + " takes " + share + " damage for an adjacent ally.");
	}

	private static void RunBrandSplash(BattleState battle, MethodInfo method, Unit receiver, int dealt, object caster, object castSource, object dealer, object fromMech, float scalar, bool cumulative)
	{
		foreach (var rule in BrandRules)
		{
			if (Homm3UnitKitRuntime.IsDisabled(Kind.BrandSplash))
				return;
			if (!Homm3BuffDebuffNativeAdapter.TryRequireBuffSidFromReceiver(receiver, rule.Buff, out var info, out _) || !info.HasSid)
				continue;
			var field = Snapshot(battle, fresh: true);
			if (field == null || !field.Units.TryGetValue(receiver.Pointer, out var r))
				return;
			var splash = (int)Math.Max(1L, (long)dealt * rule.Percent / 100L);
			var victims = new List<Unit>();
			foreach (var other in field.Units.Values)
			{
				if (other != r && other.Side == r.Side && Adjacent(other, r))
					victims.Add(other.Unit);
			}
			foreach (var victim in victims)
				DealNested(method, victim, caster, castSource, dealer, splash, fromMech, scalar, cumulative);
			if (victims.Count > 0)
				LogEvent(rule.Name + ": " + splash + " splash damage to " + victims.Count + " stack(s) next to " + DescribeUnit(receiver) + ".");
			return; // one brand per hit
		}
	}

	private static readonly HashSet<(long, long, long)> FeedbackDone = new();

	private static void RunAbilityFeedback(BattleState battle, MethodInfo method, Unit caster, long casterKey, CommitInfo commit, object castSource, object dealer, object fromMech, float scalar, bool cumulative)
	{
		var field = Snapshot(battle);
		if (field == null || !field.Units.TryGetValue(caster.Pointer, out var c))
			return;
		foreach (var holder in new List<FieldUnit>(field.Units.Values))
		{
			if (holder.Side == c.Side)
				continue;
			var rule = Homm3UnitKitRuntime.FindRule(holder.Unit, holder.Key, Kind.AbilityFeedback);
			if (rule == null || MinDistance(holder, c) > rule.Radius)
				continue;
			lock (Gate)
			{
				if (FeedbackDone.Count > 512)
					FeedbackDone.Clear();
				if (!FeedbackDone.Add((holder.Key, casterKey, commit.Serial)))
					continue;
			}
			if (!Homm3UnitKitRuntime.TryCasterBasicDamage(holder.Unit, out var basic))
				continue;
			var damage = (int)Math.Max(1L, basic * rule.Percent / 100L);
			if (DealNested(method, caster, holder.Unit, castSource, dealer, damage, fromMech, scalar, cumulative))
				LogEvent(rule.Name + ": " + DescribeUnit(holder.Unit) + " deals " + damage + " to " + DescribeUnit(caster) + " for its ability.");
		}
	}

	private static readonly HashSet<(long, long)> ScatterDone = new();

	private static void RunScatter(BattleState battle, Unit holder, long holderKey, Unit attacker, long attackerKey, CommitInfo commit)
	{
		var rule = Homm3UnitKitRuntime.FindRule(holder, holderKey, Kind.Scatter);
		if (rule == null)
			return;
		lock (Gate)
		{
			if (ScatterDone.Count > 256)
				ScatterDone.Clear();
			if (!ScatterDone.Add((holderKey, commit.Serial ^ (attackerKey << 20))))
				return;
		}
		var field = Snapshot(battle, fresh: true);
		if (field == null || !field.Units.TryGetValue(holder.Pointer, out var h) || !field.Units.TryGetValue(attacker.Pointer, out var a))
			return;
		if (h.Hexes.Count != 1)
			return; // wide stacks do not scatter
		var start = h.Hexes[0];
		var from = MainHex(a);
		if (from == null)
			return;
		var dx = start.position.x - from.position.x;
		var dz = start.position.z - from.position.z;
		var length = Math.Sqrt(dx * dx + dz * dz);
		if (length < 1e-4)
			return;
		var path = new List<BattleHex>();
		var current = start;
		for (var step = 0; step < rule.Hexes; step++)
		{
			BattleHex best = null;
			var bestCos = 0.5;
			foreach (var hex in field.Hexes)
			{
				if (hex == null || hex == current || path.Contains(hex) || Distance(current, hex) != 1 || !IsFree(field, hex, h))
					continue;
				var hx = hex.position.x - current.position.x;
				var hz = hex.position.z - current.position.z;
				var hl = Math.Sqrt(hx * hx + hz * hz);
				if (hl < 1e-4)
					continue;
				var cos = (hx * dx + hz * dz) / (hl * length);
				if (cos > bestCos)
				{
					bestCos = cos;
					best = hex;
				}
			}
			if (best == null)
				break;
			path.Add(best);
			current = best;
		}
		if (path.Count == 0)
			return;
		var builder = ReadProperty(battle.Logic, Pins.LogicBuilder);
		var pending = ReadProperty(ReadProperty(battle.Logic, Pins.LogicQueue), Pins.QueuePending);
		if (builder == null || pending == null || h.Id < 0)
			return;
		var ids = new Il2CppStructArray<int>(path.Count);
		for (var i = 0; i < path.Count; i++)
			ids[i] = path[path.Count - 1 - i].index; // destination first, start excluded
		var movementParameter = _queueMove.GetParameters()[2].ParameterType;
		var movement = MovementOf(holder, movementParameter);
		var existing = PendingPointers(pending);
		_ownQueue = true;
		try
		{
			_queueMove.Invoke(builder, new object[] { h.Id, h.Id, movement, Enum.ToObject(_moveSourceType, MoveSourceDefault), ids, false });
		}
		finally
		{
			_ownQueue = false;
		}
		var added = MarkOwn(battle, pending, existing, null);
		if (added.Count == 0)
		{
			LogWarning(rule.Name + ": the builder refused the move for " + DescribeUnit(holder) + ".");
			return;
		}
		LogEvent(rule.Name + ": " + DescribeUnit(holder) + " scatters " + path.Count + " hex(es) away from " + DescribeUnit(attacker) + ".");
	}

	private static void RunArrivalBuff(BattleState battle, Unit mover, long moverKey)
	{
		if (Homm3UnitKitRuntime.IsDisabled(Kind.ArrivalBuff))
			return;
		try
		{
			var field = Snapshot(battle, fresh: true);
			if (field == null || !field.Units.TryGetValue(mover.Pointer, out var m))
				return;
			foreach (var holder in field.Units.Values)
			{
				if (holder.Side == m.Side)
					continue;
				var rule = Homm3UnitKitRuntime.FindRule(holder.Unit, holder.Key, Kind.ArrivalBuff);
				if (rule == null || MinDistance(holder, m) > rule.Radius)
					continue;
				if (Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(mover, rule.Buff, holder.Unit, 1, ArrivalBuffDuration, 0, true, out _, out var fail))
					LogEvent(rule.Name + ": " + DescribeUnit(mover) + " ended its move near " + DescribeUnit(holder.Unit) + " (" + rule.Buff + ").");
				else
					LogWarning(rule.Name + ": " + rule.Buff + " was not added to " + DescribeUnit(mover) + ": " + fail);
			}
		}
		catch (Exception ex)
		{
			Homm3UnitKitRuntime.DisableKind(Kind.ArrivalBuff, ex);
		}
	}

	private static bool DealNested(MethodInfo method, Unit receiver, object caster, object castSource, object dealer, int damage, object fromMech, float scalar, bool cumulative)
	{
		if (receiver == null || damage <= 0 || !IsAlive(receiver))
			return false;
		_nested++;
		try
		{
			method.Invoke(receiver, new object[] { caster, castSource, dealer, damage, fromMech, false, scalar, cumulative });
			return true;
		}
		finally
		{
			_nested--;
		}
	}

	// ------------------------------------------------------------------ attack steps: scaled strikes, guard_strike

	private static void PrefixAttackStepBegin(object __instance)
	{
		try
		{
			if (__instance is not Il2CppObjectBase step)
				return;
			var attacker = ReadProperty(__instance, Pins.AttackAttacker) as Unit;
			var attackerKey = attacker == null ? 0 : Homm3DirectStateIdentity.ResolveKeyOrZero(attacker);
			lock (Gate)
			{
				foreach (var battle in Battles)
				{
					if (!battle.ScaledSteps.TryGetValue(step.Pointer, out var scaled))
						continue;
					battle.ScaledSteps.Remove(step.Pointer);
					_activeScaled = scaled;
					return;
				}
				if (_activeScaled != null && _activeScaled.Key == attackerKey)
					_activeScaled = null; // a normal attack by the same unit
			}
		}
		catch
		{
			// scaling stays as it was
		}
	}

	private static void PostfixAttackStepBegin(object __instance)
	{
		try
		{
			if (__instance is not Il2CppObjectBase step || ReadInt(__instance, Pins.StepState, -1) != StatePlaying)
				return;
			if (ReadProperty(__instance, Pins.AttackAttacker) is not Unit attacker || !IsAlive(attacker))
				return;
			var battle = FindBattleForUnit(attacker);
			if (battle == null)
				return;
			lock (Gate)
			{
				if (battle.OwnSteps.Contains(step.Pointer))
					return; // a strike the kits queued triggers nothing
			}
			var attackerKey = Homm3DirectStateIdentity.ResolveKeyOrZero(attacker);
			if (battle.ZoneFallback.Count > 0)
				RunZoneFallback(battle, attacker, attackerKey);
			if (!Homm3UnitKitRuntime.TableHas(Kind.GuardStrike) || Homm3UnitKitRuntime.IsDisabled(Kind.GuardStrike))
				return;
			if (ReadProperty(__instance, Pins.AttackTargets) is not Il2CppStructArray<int> targets || targets.Length == 0)
				return;
			try
			{
				RunGuardStrike(battle, attacker, targets);
			}
			catch (Exception ex)
			{
				Homm3UnitKitRuntime.DisableKind(Kind.GuardStrike, ex);
			}
		}
		catch (Exception ex)
		{
			Fail("attack step", ex);
		}
	}

	private static void RunGuardStrike(BattleState battle, Unit attacker, Il2CppStructArray<int> targets)
	{
		var field = Snapshot(battle, fresh: true);
		if (field == null || !field.Units.TryGetValue(attacker.Pointer, out var a))
			return;
		FieldUnit victim = null;
		foreach (var hexId in targets)
		{
			if (hexId < 0 || hexId >= field.Hexes.Length || field.Hexes[hexId] == null)
				continue;
			foreach (var unit in field.Units.Values)
			{
				if (unit != a && unit.Side != a.Side && unit.Hexes.Contains(field.Hexes[hexId]))
				{
					victim = unit;
					break;
				}
			}
			if (victim != null)
				break;
		}
		if (victim == null || !Adjacent(a, victim))
			return; // ranged attacks and attacks on nothing do not trigger it
		foreach (var holder in new List<FieldUnit>(field.Units.Values))
		{
			if (holder == victim || holder.Side != victim.Side || !Adjacent(holder, victim) || !Adjacent(holder, a))
				continue;
			var rule = Homm3UnitKitRuntime.FindRule(holder.Unit, holder.Key, Kind.GuardStrike);
			if (rule == null || !TrySpend(battle, holder.Key, Kind.GuardStrike, rule.PerRound))
				continue;
			var targetHex = AdjacentHexOf(a, holder);
			string detail = null;
			if (targetHex == null || !QueueStrike(battle, holder, targetHex.index, shoot: false, rule, out detail))
			{
				Refund(battle, holder.Key, Kind.GuardStrike);
				LogWarning(rule.Name + ": strike by " + DescribeUnit(holder.Unit) + " was not queued: " + (detail ?? "no hex"));
				continue;
			}
			LogEvent(rule.Name + ": " + DescribeUnit(holder.Unit) + " strikes " + DescribeUnit(attacker) + " for attacking " + DescribeUnit(victim.Unit) + ".");
		}
	}

	// ------------------------------------------------------------------ builder: moves, zone_shot, charge_no_counter

	private static void PrefixQueueAttack(int __0, object __2)
	{
		EnterBuild();
		if (!_ownQueue && __2 is Il2CppStructArray<int> path && path.Length > 0)
			NoteMoveById(__0, path.Length, path[0]);
	}

	private static void PrefixQueueMove(int __0, object __4)
	{
		EnterBuild();
		if (!_ownQueue && __4 is Il2CppStructArray<int> path && path.Length > 0)
			NoteMoveById(__0, path.Length, path[0]);
	}

	private static void PrefixBuildAttack(object __1, object __4)
	{
		EnterBuild();
		IntPtr charge = IntPtr.Zero;
		try
		{
			var attacker = AsUnit(__1);
			if (attacker != null && !_ownQueue)
			{
				var moved = __4 is Il2CppStructArray<int> path ? path.Length : 0;
				if (moved > 0 && __4 is Il2CppStructArray<int> p)
					NoteMove(attacker, moved, p[0]);
				charge = ChargeFor(attacker, moved);
			}
		}
		catch (Exception ex)
		{
			Homm3UnitKitRuntime.DisableKind(Kind.ChargeNoCounter, ex);
		}
		(_chargeAttackers ??= new List<IntPtr>()).Add(charge);
	}

	private static void FinalizerBuildAttack()
	{
		if (_chargeAttackers != null && _chargeAttackers.Count > 0)
			_chargeAttackers.RemoveAt(_chargeAttackers.Count - 1);
		FinalizerBuild();
	}

	private static void FinalizerBuild()
	{
		if (_buildDepth > 0)
			_buildDepth--;
		if (_buildDepth != 0 || _flushing)
			return;
		var deferred = _deferredZone;
		var snapshot = _buildSnapshot;
		var battle = _buildBattle;
		_deferredZone = null;
		_buildSnapshot = null;
		_buildBattle = null;
		if (deferred == null || deferred.Count == 0)
			return;
		_flushing = true;
		try
		{
			FlushZoneShots(deferred, snapshot);
		}
		catch (Exception ex)
		{
			Homm3UnitKitRuntime.DisableKind(Kind.ZoneShot, ex);
		}
		finally
		{
			_flushing = false;
		}
	}

	private static void EnterBuild()
	{
		_buildDepth++;
	}

	/// <summary>bhqp(anchor, attacker, counterattacker, ...): false skips the counter of a charging holder's attack.</summary>
	private static bool PrefixQueueCounter(object __1)
	{
		try
		{
			if (_chargeAttackers == null || _chargeAttackers.Count == 0 || __1 is not Il2CppObjectBase attacker)
				return true;
			var charge = _chargeAttackers[_chargeAttackers.Count - 1];
			if (charge == IntPtr.Zero || charge != attacker.Pointer)
				return true;
			LogEvent("charge_no_counter: no counterattack against " + DescribeUnit(AsUnit(__1)) + "'s charge.");
			return false;
		}
		catch
		{
			return true;
		}
	}

	private static IntPtr ChargeFor(Unit attacker, int movePathLength)
	{
		if (!_chargeLive || !Homm3UnitKitRuntime.TableHas(Kind.ChargeNoCounter))
			return IntPtr.Zero;
		var key = Homm3DirectStateIdentity.ResolveKeyOrZero(attacker);
		var rule = Homm3UnitKitRuntime.FindRule(attacker, key, Kind.ChargeNoCounter);
		if (rule == null)
			return IntPtr.Zero;
		var moved = movePathLength;
		var battle = FindBattleForUnit(attacker);
		if (battle != null)
		{
			lock (Gate)
			{
				if (battle.Stamps.TryGetValue(key, out var stamp))
					moved = Math.Max(moved, stamp.MoveHexesThisAction);
			}
		}
		if (moved < rule.Hexes || (TryGetCommit(key, out var commit) && commit.IsAttack && commit.Ranged))
			return IntPtr.Zero;
		return attacker.Pointer;
	}

	private static void NoteMoveById(int unitId, int hexes, int destinationHexId)
	{
		try
		{
			foreach (var battle in SnapshotBattles())
			{
				var field = Snapshot(battle, fresh: true);
				if (field == null)
					continue;
				foreach (var unit in field.Units.Values)
				{
					if (unit.Id == unitId)
					{
						NoteMove(unit.Unit, hexes, destinationHexId);
						return;
					}
				}
			}
		}
		catch (Exception ex)
		{
			Fail("move stamp", ex);
		}
	}

	private static void NoteMove(Unit mover, int hexes, int destinationHexId)
	{
		var battle = FindBattleForUnit(mover);
		var key = Homm3DirectStateIdentity.ResolveKeyOrZero(mover);
		if (battle == null || key == 0)
			return;
		lock (Gate)
		{
			var stamp = StampOf(battle, key);
			stamp.MovedRound = true;
			stamp.MovedThisAction = true;
			stamp.MoveHexesThisAction = Math.Max(stamp.MoveHexesThisAction, hexes);
		}
		if (Homm3UnitKitRuntime.TableHas(Kind.ZoneShot) && !Homm3UnitKitRuntime.IsDisabled(Kind.ZoneShot))
		{
			try
			{
				PlanZoneShots(battle, mover, key, destinationHexId);
			}
			catch (Exception ex)
			{
				Homm3UnitKitRuntime.DisableKind(Kind.ZoneShot, ex);
			}
		}
	}

	private static void PlanZoneShots(BattleState battle, Unit mover, long moverKey, int destinationHexId)
	{
		var field = Snapshot(battle);
		if (field == null || destinationHexId < 0 || destinationHexId >= field.Hexes.Length || field.Hexes[destinationHexId] == null
		    || !field.Units.TryGetValue(mover.Pointer, out var m))
			return;
		var destination = field.Hexes[destinationHexId];
		foreach (var holder in field.Units.Values)
		{
			if (holder.Side == m.Side)
				continue;
			var rule = Homm3UnitKitRuntime.FindRule(holder.Unit, holder.Key, Kind.ZoneShot);
			if (rule == null || !CanShoot(field, holder))
				continue;
			var near = false;
			foreach (var hex in holder.Hexes)
			{
				if (Distance(hex, destination) <= rule.Radius)
				{
					near = true;
					break;
				}
			}
			if (!near)
				continue;
			_deferredZone ??= new List<ZoneShot>();
			if (_deferredZone.Exists(z => z.Holder.Key == holder.Key && z.MoverKey == moverKey))
				continue;
			if (!TrySpend(battle, holder.Key, Kind.ZoneShot, rule.PerRound))
				continue;
			if (_deferredZone.Count == 0)
			{
				_buildBattle = battle;
				var pending = ReadProperty(ReadProperty(battle.Logic, Pins.LogicQueue), Pins.QueuePending);
				_buildSnapshot = pending == null ? null : PendingPointers(pending);
			}
			_deferredZone.Add(new ZoneShot { Holder = holder, Rule = rule, MoverKey = moverKey, MoverPointer = mover.Pointer, DestinationHexId = destinationHexId });
		}
	}

	/// <summary>The mover's build is complete: queue each planned shot and move it in front of the mover's first
	/// AttackStep of that build. A refused shot falls back to the mover's next AttackStep (after its attack).</summary>
	private static void FlushZoneShots(List<ZoneShot> shots, HashSet<IntPtr> snapshot)
	{
		foreach (var shot in shots)
		{
			var battle = FindBattleForUnit(shot.Holder.Unit);
			if (battle == null || !IsAlive(shot.Holder.Unit))
				continue;
			var pending = ReadProperty(ReadProperty(battle.Logic, Pins.LogicQueue), Pins.QueuePending);
			if (pending == null)
				continue;
			// the mover's own steps from this build, before the shot is added
			IntPtr firstAttack = IntPtr.Zero;
			var count = ListCount(pending);
			for (var i = 0; i < count && snapshot != null; i++)
			{
				if (ListItem(pending, i) is not Il2CppObjectBase step || snapshot.Contains(step.Pointer) || battle.OwnSteps.Contains(step.Pointer))
					continue;
				if (IsNativeInstance(step, _attackStepClass))
				{
					firstAttack = step.Pointer;
					break;
				}
			}
			if (!QueueStrike(battle, shot.Holder, shot.DestinationHexId, shoot: true, shot.Rule, out var detail, out var added))
			{
				lock (Gate)
					battle.ZoneFallback.Add(shot);
				LogWarning(shot.Rule.Name + ": shot by " + DescribeUnit(shot.Holder.Unit) + " at the arrival hex was not queued (" + detail + "); it fires at the mover's next attack instead.");
				continue;
			}
			var moved = firstAttack != IntPtr.Zero && MoveStepsBefore(pending, added, firstAttack);
			LogEvent(shot.Rule.Name + ": " + DescribeUnit(shot.Holder.Unit) + " shoots a stack arriving within " + shot.Rule.Radius + " hexes"
				+ (moved ? " (before its attack)." : firstAttack == IntPtr.Zero ? "." : " (after its attack: reorder failed)."));
		}
	}

	private static void RunZoneFallback(BattleState battle, Unit attacker, long attackerKey)
	{
		List<ZoneShot> due;
		lock (Gate)
		{
			due = battle.ZoneFallback.FindAll(z => z.MoverKey == attackerKey);
			battle.ZoneFallback.RemoveAll(z => z.MoverKey == attackerKey);
		}
		if (due.Count == 0)
			return;
		var target = MainHex(attacker);
		if (target == null)
			return;
		foreach (var shot in due)
		{
			if (!IsAlive(shot.Holder.Unit))
				continue;
			if (QueueStrike(battle, shot.Holder, target.index, shoot: true, shot.Rule, out var detail))
				LogEvent(shot.Rule.Name + ": " + DescribeUnit(shot.Holder.Unit) + " shoots " + DescribeUnit(attacker) + " (fallback, after its attack).");
			else
				LogWarning(shot.Rule.Name + ": fallback shot not queued: " + detail);
		}
	}

	// ------------------------------------------------------------------ spell_echo

	private static void PostfixHeroAbilityCast(object __instance, object __1)
	{
		if (Homm3UnitKitRuntime.IsDisabled(Kind.SpellEcho))
			return;
		try
		{
			if (__1 is not Il2CppStructArray<int> targets || targets.Length == 0)
				return;
			var sidePointer = (ReadProperty(__instance, Pins.HeroAbilitySide) as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
			if (sidePointer == IntPtr.Zero)
				return;
			BattleState battle = null;
			foreach (var candidate in SnapshotBattles())
			{
				if (BattleOwnsWrapper(candidate, sidePointer))
				{
					battle = candidate;
					break;
				}
			}
			var field = battle == null ? null : Snapshot(battle, fresh: true);
			if (field == null)
				return;
			foreach (var holder in new List<FieldUnit>(field.Units.Values))
			{
				if (holder.Side != sidePointer)
					continue;
				var rule = Homm3UnitKitRuntime.FindRule(holder.Unit, holder.Key, Kind.SpellEcho);
				if (rule == null || !CanShoot(field, holder))
					continue;
				FieldUnit enemy = null;
				var enemyHex = -1;
				foreach (var hexId in targets)
				{
					if (hexId < 0 || hexId >= field.Hexes.Length || field.Hexes[hexId] == null)
						continue;
					foreach (var unit in field.Units.Values)
					{
						if (unit.Side != sidePointer && unit.Hexes.Contains(field.Hexes[hexId]))
						{
							enemy = unit;
							enemyHex = hexId;
							break;
						}
					}
					if (enemy != null)
						break;
				}
				if (enemy == null || !TrySpend(battle, holder.Key, Kind.SpellEcho, rule.PerRound))
					continue;
				if (QueueStrike(battle, holder, enemyHex, shoot: true, rule, out var detail))
					LogEvent(rule.Name + ": " + DescribeUnit(holder.Unit) + " shoots " + DescribeUnit(enemy.Unit) + " after its hero's cast.");
				else
				{
					Refund(battle, holder.Key, Kind.SpellEcho);
					LogWarning(rule.Name + ": shot not queued: " + detail);
				}
			}
		}
		catch (Exception ex)
		{
			Homm3UnitKitRuntime.DisableKind(Kind.SpellEcho, ex);
		}
	}

	// ------------------------------------------------------------------ queueing

	private static bool QueueStrike(BattleState battle, FieldUnit holder, int targetHexId, bool shoot, Homm3UnitKitRules.Rule rule, out string detail)
		=> QueueStrike(battle, holder, targetHexId, shoot, rule, out detail, out _);

	private static bool QueueStrike(BattleState battle, FieldUnit holder, int targetHexId, bool shoot, Homm3UnitKitRules.Rule rule, out string detail, out List<IntPtr> added)
	{
		detail = null;
		added = null;
		if (_queueAttack == null)
		{
			detail = "attack builder not resolved";
			return false;
		}
		if (!TryPickAttack(holder.Unit, shoot, out var abilityType, out var attackIndex))
		{
			detail = shoot ? "no shot" : "no melee attack";
			return false;
		}
		var builder = ReadProperty(battle.Logic, Pins.LogicBuilder);
		var pending = ReadProperty(ReadProperty(battle.Logic, Pins.LogicQueue), Pins.QueuePending);
		if (builder == null || pending == null || holder.Id < 0)
		{
			detail = "builder/queue/unit id unreadable";
			return false;
		}
		var existing = PendingPointers(pending);
		var targetArray = new Il2CppStructArray<int>(1);
		targetArray[0] = targetHexId;
		var movement = MovementOf(holder.Unit, _queueAttack.GetParameters()[4].ParameterType);
		_ownQueue = true;
		try
		{
			_queueAttack.Invoke(builder, new object[] { holder.Id, holder.Id, new Il2CppStructArray<int>(0), targetArray, movement, abilityType, attackIndex, true, false });
		}
		catch (Exception ex)
		{
			detail = "bhqa threw: " + ex.GetBaseException().Message;
			return false;
		}
		finally
		{
			_ownQueue = false;
		}
		added = MarkOwn(battle, pending, existing, new Scaled { Key = holder.Key, Percent = rule.Percent, Name = rule.Name }, holder.Unit);
		if (added.Count == 0)
		{
			detail = "the builder refused the attack (no steps queued)";
			return false;
		}
		return true;
	}

	/// <summary>Marks the steps added since <paramref name="existing"/> as the kits' own; the holder's AttackSteps get the scale.</summary>
	private static List<IntPtr> MarkOwn(BattleState battle, object pending, HashSet<IntPtr> existing, Scaled scale, Unit striker = null)
	{
		var added = new List<IntPtr>();
		var count = ListCount(pending);
		lock (Gate)
		{
			if (battle.OwnSteps.Count > 256)
			{
				var live = PendingPointers(pending);
				battle.OwnSteps.RemoveWhere(p => !live.Contains(p));
				var stale = new List<IntPtr>();
				foreach (var key in battle.ScaledSteps.Keys)
				{
					if (!live.Contains(key))
						stale.Add(key);
				}
				foreach (var key in stale)
					battle.ScaledSteps.Remove(key);
			}
			for (var i = 0; i < count; i++)
			{
				if (ListItem(pending, i) is not Il2CppObjectBase step || existing.Contains(step.Pointer))
					continue;
				added.Add(step.Pointer);
				battle.OwnSteps.Add(step.Pointer);
				if (scale == null || striker == null || !IsNativeInstance(step, _attackStepClass))
					continue;
				var wrapper = Activator.CreateInstance(_attackStepType, step.Pointer);
				if (ReadProperty(wrapper, Pins.AttackAttacker) is Unit attacker && attacker.Pointer == striker.Pointer)
					battle.ScaledSteps[step.Pointer] = scale;
			}
		}
		return added;
	}

	/// <summary>Moves <paramref name="steps"/> (in order) in front of <paramref name="before"/> in the pending list.</summary>
	private static bool MoveStepsBefore(object pending, List<IntPtr> steps, IntPtr before)
	{
		try
		{
			var type = pending.GetType();
			var removeAt = type.GetMethod("RemoveAt", BindingFlags.Instance | BindingFlags.Public, null, new[] { typeof(int) }, null);
			MethodInfo insert = null;
			foreach (var method in type.GetMethods(BindingFlags.Instance | BindingFlags.Public))
			{
				if (method.Name == "Insert" && method.GetParameters().Length == 2 && method.GetParameters()[0].ParameterType == typeof(int))
				{
					insert = method;
					break;
				}
			}
			if (removeAt == null || insert == null)
				return false;
			foreach (var pointer in steps)
			{
				var count = ListCount(pending);
				int from = -1, to = -1;
				object item = null;
				for (var i = 0; i < count; i++)
				{
					if (ListItem(pending, i) is not Il2CppObjectBase step)
						continue;
					if (step.Pointer == pointer)
					{
						from = i;
						item = step;
					}
					if (step.Pointer == before && to < 0)
						to = i;
				}
				if (from < 0 || to < 0 || item == null)
					return false;
				if (from < to)
					continue; // already in front
				removeAt.Invoke(pending, new object[] { from });
				insert.Invoke(pending, new[] { (object)to, item });
			}
			return true;
		}
		catch (Exception ex)
		{
			LogWarning("pending step reorder failed: " + ex.GetBaseException().Message);
			return false;
		}
	}

	private static object MovementOf(Unit unit, Type parameterType)
	{
		var value = ReadProperty(ReadProperty(unit, Pins.UnitStat), Pins.StatMovementType);
		return value != null && parameterType.IsInstanceOfType(value) ? value : Enum.ToObject(parameterType, 0);
	}

	private static bool TrySpend(BattleState battle, long key, Kind kind, int perRound)
	{
		lock (Gate)
		{
			battle.Uses.TryGetValue((key, kind), out var used);
			if (used >= Math.Max(1, perRound))
				return false;
			battle.Uses[(key, kind)] = used + 1;
			return true;
		}
	}

	private static void Refund(BattleState battle, long key, Kind kind)
	{
		lock (Gate)
		{
			if (battle.Uses.TryGetValue((key, kind), out var used) && used > 0)
				battle.Uses[(key, kind)] = used - 1;
		}
	}

	// ------------------------------------------------------------------ grid

	private static Field Snapshot(BattleState battle, bool fresh = false)
	{
		var frame = UnityEngine.Time.frameCount;
		var cached = battle.FieldCache;
		if (!fresh && cached != null && cached.Frame == frame)
			return cached;
		if (ReadProperty(ReadProperty(battle.Logic, Pins.LogicGrid), Pins.GridHexes) is not Il2CppReferenceArray<BattleHex> array)
			return null;
		var field = new Field { Frame = frame, Hexes = new BattleHex[array.Length] };
		for (var i = 0; i < array.Length; i++)
		{
			var hex = array[i];
			if (hex == null || hex.index < 0 || hex.index >= field.Hexes.Length)
				continue;
			field.Hexes[hex.index] = hex;
			if (hex.fieldObjects == null)
				continue;
			for (var j = 0; j < hex.fieldObjects.Count; j++)
			{
				var unit = hex.fieldObjects[j]?.TryCast<Unit>();
				if (unit == null)
					continue;
				if (!field.Units.TryGetValue(unit.Pointer, out var entry))
				{
					if (!IsAlive(unit))
						continue;
					entry = new FieldUnit
					{
						Unit = unit,
						Key = Homm3DirectStateIdentity.ResolveKeyOrZero(unit),
						Id = ReadInt(unit, Pins.FieldObjectId, -1),
						Side = SidePointer(unit),
					};
					field.Units[unit.Pointer] = entry;
				}
				entry.Hexes.Add(hex);
			}
		}
		battle.FieldCache = field;
		return field;
	}

	private static bool Adjacent(FieldUnit a, FieldUnit b) => MinDistance(a, b) == 1;

	private static int MinDistance(FieldUnit a, FieldUnit b)
	{
		var best = int.MaxValue;
		foreach (var x in a.Hexes)
		{
			foreach (var y in b.Hexes)
			{
				var d = Distance(x, y);
				if (d < best)
					best = d;
			}
		}
		return best;
	}

	/// <summary>A hex of <paramref name="target"/> next to <paramref name="from"/>.</summary>
	private static BattleHex AdjacentHexOf(FieldUnit target, FieldUnit from)
	{
		foreach (var x in target.Hexes)
		{
			foreach (var y in from.Hexes)
			{
				if (Distance(x, y) == 1)
					return x;
			}
		}
		return null;
	}

	/// <summary>A shooter that can shoot now: it has a ranged attack and no enemy stands next to it.</summary>
	private static bool CanShoot(Field field, FieldUnit holder)
	{
		if (!IsAlive(holder.Unit) || !TryPickAttack(holder.Unit, true, out _, out _))
			return false;
		foreach (var other in field.Units.Values)
		{
			if (other.Side != holder.Side && Adjacent(other, holder))
				return false;
		}
		return true;
	}

	private static bool IsFree(Field field, BattleHex hex, FieldUnit self)
	{
		if (hex.blockedByMap || hex.blockedFromAll || hex.tempBlocked)
			return false;
		foreach (var unit in field.Units.Values)
		{
			if (unit != self && unit.Hexes.Contains(hex))
				return false;
		}
		return true;
	}

	private static BattleHex MainHex(FieldUnit unit)
		=> ReadProperty(ReadProperty(unit.Unit, Pins.FieldObjectPosition), Pins.PositionHex) as BattleHex ?? (unit.Hexes.Count > 0 ? unit.Hexes[0] : null);

	private static BattleHex MainHex(Unit unit)
		=> ReadProperty(ReadProperty(unit, Pins.FieldObjectPosition), Pins.PositionHex) as BattleHex;

	private static int Distance(BattleHex a, BattleHex b)
	{
		if (a == null || b == null || _hexDistance == null)
			return int.MaxValue;
		if (a.Pointer == b.Pointer)
			return 0;
		try
		{
			return (int)_hexDistance.Invoke(null, new object[] { a, b });
		}
		catch
		{
			return int.MaxValue;
		}
	}

	// ------------------------------------------------------------------ battles and sides

	private static BattleState FindBattleByHub(object hub)
	{
		var pointer = (hub as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
		if (pointer == IntPtr.Zero)
			return null;
		lock (Gate)
		{
			foreach (var battle in Battles)
			{
				if (battle.HubPointer == pointer)
					return battle;
			}
		}
		return null;
	}

	private static BattleState FindBattleForUnit(Unit unit)
	{
		if (unit == null)
			return null;
		lock (Gate)
			return FindBattleForUnitLocked(unit);
	}

	private static BattleState FindBattleForUnitLocked(Unit unit)
	{
		var side = SidePointer(unit);
		if (side == IntPtr.Zero)
			return null;
		for (var i = Battles.Count - 1; i >= 0; i--)
		{
			if (BattleOwnsWrapper(Battles[i], side))
				return Battles[i];
		}
		return null;
	}

	private static List<BattleState> SnapshotBattles()
	{
		lock (Gate)
			return new List<BattleState>(Battles);
	}

	private static bool BattleOwnsWrapper(BattleState battle, IntPtr sidePointer)
	{
		if (battle.Wrappers == null || battle.Wrappers.Count == 0)
		{
			var set = new HashSet<IntPtr>();
			if (ReadProperty(ReadProperty(battle.Logic, Pins.LogicState), Pins.StateSideWrappers) is IEnumerable wrappers)
			{
				foreach (var wrapper in wrappers)
				{
					if (wrapper is Il2CppObjectBase obj)
						set.Add(obj.Pointer);
				}
			}
			battle.Wrappers = set;
		}
		return battle.Wrappers.Contains(sidePointer);
	}

	private static Stamp StampOf(BattleState battle, long key)
	{
		if (!battle.Stamps.TryGetValue(key, out var stamp))
			battle.Stamps[key] = stamp = new Stamp();
		return stamp;
	}

	private static Unit TargetOf(object[] args)
		=> args != null && args.Length > 1 && args[1] is BattleEventArgs eventArgs ? AsUnit(eventArgs.target) : null;

	private static IntPtr SidePointer(Unit unit)
		=> (ReadProperty(unit, Pins.FieldObjectSide) as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;

	private static Unit AsUnit(object value) => Homm3UnitKitRuntime.AsUnit(value);

	// ------------------------------------------------------------------ attacks

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

	// ------------------------------------------------------------------ small helpers

	private static void Guard(Kind kind, Action action)
	{
		if (Homm3UnitKitRuntime.IsDisabled(kind))
			return;
		try
		{
			action();
		}
		catch (Exception ex)
		{
			Homm3UnitKitRuntime.DisableKind(kind, ex);
		}
	}

	private static bool IsAlive(Unit unit) => unit != null && Homm3FortressPredatorInstinctRuntime.IsAlive(unit);

	private static string DescribeUnit(Unit unit) => unit == null ? "<unit>" : Homm3FortressPredatorInstinctRuntime.DescribeUnit(unit);

	private static object ReadProperty(object obj, string name) => Homm3FortressPredatorInstinctRuntime.ReadProperty(obj, name);

	private static string ReadString(object target, string[] names)
	{
		var raw = Homm3TowerArtificingRuntime.ReadMember(target, names);
		return raw == null ? null : raw as string ?? raw.ToString();
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

	private static List<Homm3UnitKitRules.Rule> CollectRules(Kind kind)
	{
		var list = new List<Homm3UnitKitRules.Rule>();
		var seen = new HashSet<string>(StringComparer.Ordinal);
		foreach (var rules in Homm3UnitKitRules.Rules.Values)
		{
			foreach (var rule in rules)
			{
				if (rule.Kind == kind && !string.IsNullOrEmpty(rule.Buff) && seen.Add(rule.Buff))
					list.Add(rule);
			}
		}
		return list;
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
		for (var cur = type; cur != null; cur = cur.BaseType)
		{
			var property = cur.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			if (property != null)
				return property;
		}
		throw new MissingMemberException((type?.FullName ?? "null") + "." + name);
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

	private static MethodInfo ResolveDeclaredVoidMethod(Type type, string name, int parameterCount)
	{
		if (type == null || string.IsNullOrWhiteSpace(name) || GameSymbolScope.IsSentinel(name))
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly | BindingFlags.Instance))
		{
			if (method.Name == name && !method.IsSpecialName && !method.ContainsGenericParameters && method.ReturnType == typeof(void)
			    && method.GetParameters().Length == parameterCount)
				return method;
		}
		return null;
	}

	private static void Patch(Harmony harmony, MethodInfo target, string prefixName, string postfixName)
	{
		const BindingFlags flags = BindingFlags.Static | BindingFlags.NonPublic;
		var prefix = prefixName == null ? null : typeof(Homm3UnitKitBattleHooks).GetMethod(prefixName, flags) ?? throw new MissingMethodException(prefixName);
		var postfix = postfixName == null ? null : typeof(Homm3UnitKitBattleHooks).GetMethod(postfixName, flags) ?? throw new MissingMethodException(postfixName);
		if (prefix != null && !GameMember.IsHarmonyPatchCompatible(target, prefix, out var prefixReason))
			throw new MissingMethodException("prefix incompatible for " + target.DeclaringType?.FullName + "." + target.Name + ": " + prefixReason);
		if (postfix != null && !GameMember.IsHarmonyPatchCompatible(target, postfix, out var postfixReason))
			throw new MissingMethodException("postfix incompatible for " + target.DeclaringType?.FullName + "." + target.Name + ": " + postfixReason);
		harmony.Patch(target,
			prefix: prefix == null ? null : new HarmonyMethod(prefix) { priority = Priority.Last },
			postfix: postfix == null ? null : new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static void PatchWithFinalizer(Harmony harmony, MethodInfo target, string prefixName, string finalizerName)
	{
		const BindingFlags flags = BindingFlags.Static | BindingFlags.NonPublic;
		var prefix = typeof(Homm3UnitKitBattleHooks).GetMethod(prefixName, flags) ?? throw new MissingMethodException(prefixName);
		var finalizer = typeof(Homm3UnitKitBattleHooks).GetMethod(finalizerName, flags) ?? throw new MissingMethodException(finalizerName);
		if (!GameMember.IsHarmonyPatchCompatible(target, prefix, out var reason))
			throw new MissingMethodException("prefix incompatible for " + target.DeclaringType?.FullName + "." + target.Name + ": " + reason);
		// Priority.First: the depth count must rise before any prefix that could skip the original.
		harmony.Patch(target, prefix: new HarmonyMethod(prefix) { priority = Priority.First }, finalizer: new HarmonyMethod(finalizer));
	}

	private static void Fail(string where, Exception ex)
	{
		bool first;
		lock (Gate)
			first = Failed.Add(where);
		if (first)
			LogWarning(where + " hook failed closed: " + ex.GetBaseException().Message);
	}

	internal static void LogEvent(string message)
	{
		if (_events++ < 400)
			_log?.LogInfo("HoMM3 unit kit: " + message);
	}

	internal static void LogWarning(string message)
	{
		if (_warnings++ < 120)
			_log?.LogWarning("HoMM3 unit kit: " + message);
	}
}
