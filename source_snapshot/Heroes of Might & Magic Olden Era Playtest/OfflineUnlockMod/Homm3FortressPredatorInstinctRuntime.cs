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
/// HoMM3 Fortress faction skill "Predator Instinct" (skill_faction_homm3_fortress), replacing Hunting Grounds.
///
/// Design (owner, 2026-11-14):
/// - At the start of each battle, each melee stack of a Fortress hero's army is paired 1-to-1 with a random enemy
///   stack (its prey). Surplus stacks on either side stay unpaired. Endurance Hunting lets ranged stacks hunt too.
/// - Predators deal +33/66/100% damage to their prey (Basic/Advanced/Expert) and, while that prey is alive, 17/33/50%
///   less damage to every other target (half the bonus; 16.5 rounds away from zero to 17 because the owner sums whole
///   percents). Counterattacks count like attacks. The penalty ends when the prey dies; pairs are never re-made. The
///   percent is contributed to the single committed-damage owner (<see cref="Homm3CounterattackDoctrineMutationRuntime"/> Unit damage prefix), so this
///   class never patches the damage method itself.
/// - Intimidation: prey hit by its predator gets native Ice Bolt slow (magic_ice_bolt_effect_0, -3 Initiative) for 2 rounds, applied after
///   the action ends (never inside the damage call).
/// - Frenzy (expert): 1-Focus hero action; every living predator gains native Haste (magic_haste_effect_1) for the
///   round and is taunted by its prey (<see cref="Homm3FortressPredatorInstinctCombat"/>).
/// - Cautious / Pounce (expert): pair-filtered parry and no-retaliation, owned by Homm3FortressPredatorInstinctCombat.
/// - Visible state: predator marker buff (rank text) and prey marker buff; hovering a Fortress stack draws the blood
///   line (Homm3FortressPredatorLine), which reads <see cref="TryGetHoverPair"/>.
///
/// Timing (build 26615913): BattleLogic.Init postfix records the Fortress sides; pairing happens at the first
/// RoundStarted (every opening stack is on the grid then). Units are keyed by native pointer
/// (<see cref="Homm3DirectStateIdentity"/>); battles are keyed by the round hub pointer, like Inferno Gating.
///
/// Proof tier: source + build. Runtime unproven until the owner tests in game.
/// </summary>
internal static class Homm3FortressPredatorInstinctRuntime
{
	internal const string FactionSkillSid = "skill_faction_homm3_fortress";
	internal const string SwampTacticsSid = "sub_skill_faction_homm3_fortress_swamp_advantage";
	internal const string IntimidationSid = "sub_skill_faction_homm3_fortress_mire_grip";
	internal const string EnduranceHuntingSid = "sub_skill_faction_homm3_fortress_thick_hides";
	internal const string FrenzySubSkillSid = "sub_skill_faction_homm3_fortress_bog_ambush";
	internal const string CautiousSid = "sub_skill_faction_homm3_fortress_stagnant_air";
	internal const string PounceSid = "sub_skill_faction_homm3_fortress_poisoned_mire";
	internal const string FrenzyAbilitySid = "skill_faction_homm3_fortress_ability_frenzy";
	internal const string PredatorBuffPrefix = "homm3_fortress_predator_";
	internal const string PreyBuffSid = "homm3_fortress_prey";
	internal const string IntimidationSlowSid = "magic_ice_bolt_effect_0";
	internal const string FrenzyHasteSid = "magic_haste_effect_1";
	internal const int IntimidationSlowRounds = 2;
	internal const int FrenzyRounds = 1;

	/// <summary>Predator/prey marker buffs last the battle (duration 0 expired after round 1, playtest 2); 99 as Tower Artificing grafts.</summary>
	internal const int MarkerDuration = 99;
	/// <summary>Index = skill rank. Must match BONUS_PERCENT_BY_RANK in homm3_fortress_predator_instinct_core_overlay.py.</summary>
	internal static readonly int[] BonusPercentByRank = { 0, 33, 66, 100 };
	/// <summary>
	/// Index = skill rank. Damage taken off a predator's hits on anything but its prey while the prey is alive: half the
	/// bonus, 16.5 rounded away from zero. Must match PENALTY_PERCENT_BY_RANK in the Core overlay.
	/// </summary>
	internal static readonly int[] PenaltyPercentByRank = { 0, 17, 33, 50 };

	private static class Pins
	{
		private static string At(string[] names, int index) => names != null && names.Length > index ? names[index] : "";
		internal static string[] BattleLogicTypes => GameSymbols.InfernoGating.BattleLogicTypeHints;
		internal static string LogicBattleClone => At(GameSymbols.InfernoGating.LogicBattleCloneMembers, 0);
		internal static string LogicGrid => At(GameSymbols.InfernoGating.LogicGridMembers, 0);
		internal static string LogicHubs => At(GameSymbols.InfernoGating.LogicHubsMembers, 0);
		internal static string LogicState => At(GameSymbols.InfernoGating.LogicStateMembers, 0);
		internal static string HubsRoundHub => At(GameSymbols.InfernoGating.HubsRoundHubMembers, 0);
		internal static string StateSideWrappers => At(GameSymbols.InfernoGating.StateSideWrappersMembers, 0);
		internal static string SideWrapperTransferSide => At(GameSymbols.InfernoGating.SideWrapperTransferSideMembers, 0);
		internal static string GridHexes => At(GameSymbols.InfernoGating.GridHexesMembers, 0);
		internal static string UnitData => At(GameSymbols.InfernoGating.UnitDataMembers, 0);
		internal static string FieldObjectSide => At(GameSymbols.InfernoGating.FieldObjectSideMembers, 0);
		internal static string UnitDataAlive => At(GameSymbols.InfernoGating.UnitDataAliveMembers, 0);
		internal static string[] HeroAbilityTypes => GameSymbols.InfernoGating.HeroAbilityTypeHints;
		internal static string HeroAbilityUsable => At(GameSymbols.InfernoGating.HeroAbilityUsableMembers, 0);
		internal static string HeroAbilityUsableWithFocus => At(GameSymbols.InfernoGating.HeroAbilityUsableMembers, 1);
		internal static string[] HeroAbilitySidMembers => GameSymbols.FortressPredatorInstinct.HeroAbilitySidMembers;
		internal static string HeroAbilitySide => At(GameSymbols.InfernoGating.HeroAbilitySideMembers, 0);
	}

	internal sealed class Pair
	{
		internal Unit Predator;
		internal Unit Prey;
		internal long PredatorKey;
		internal long PreyKey;
		internal HunterSide Side;
		internal bool Frenzied;
	}

	internal sealed class HunterSide
	{
		internal int SideIndex;
		internal int Rank;
		internal bool Intimidation;
		internal bool EnduranceHunting;
		internal bool Frenzy;
		internal bool Cautious;
		internal bool Pounce;
		internal string HeroDescription;
		internal object SideWrapper;
		internal IntPtr SideWrapperPointer;
		internal int FrenzyRound = -1;
	}

	private sealed class BattleState
	{
		internal object Logic;
		internal IntPtr HubPointer;
		internal readonly List<HunterSide> Sides = new();
		internal readonly List<Pair> Pairs = new();
		internal readonly Dictionary<long, Pair> ByPredator = new();
		internal readonly Dictionary<long, Pair> ByPrey = new();
		internal bool Paired;
		internal int Round;
	}

	private static readonly object Gate = new();
	private static readonly List<BattleState> Battles = new();
	private static readonly List<Pair> PendingIntimidation = new();
	private static readonly System.Random Rng = new();
	private static ManualLogSource _log;
	private static bool _attempted;
	private static bool _registered;
	private static int _logged;
	private static MethodInfo _logicHeroDataHeroGetter;
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
			var logicType = ResolveTypeByHints(hexAssembly, Pins.BattleLogicTypes, "homm3.fortress.predator.battleLogic");
			var init = logicType.GetMethod("Init", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
				           new[] { typeof(int), typeof(TransferBattle), typeof(bool), typeof(bool) }, null)
			           ?? throw new MissingMethodException("BattleLogic.Init(int, TransferBattle, bool, bool)");
			foreach (var name in new[] { Pins.LogicBattleClone, Pins.LogicGrid, Pins.LogicHubs, Pins.LogicState })
				RequireProperty(logicType, name, null);
			var hubType = RequireProperty(RequireProperty(logicType, Pins.LogicHubs, null).PropertyType, Pins.HubsRoundHub, null).PropertyType;
			var roundStarted = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.RoundStartedDispatcher);
			var actionEnded = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.ActionEndedDispatcher);
			Patch(harmony, init, null, nameof(PostfixBattleLogicInit));
			Patch(harmony, roundStarted, null, nameof(PostfixRoundStarted));
			Patch(harmony, actionEnded, null, nameof(PostfixActionEnded));
			_registered = true;
			_log?.LogInfo("HoMM3 Fortress Predator Instinct [battle] registered: Init sides, round-1 pairing, ActionEnded follow-ups. Damage bonus via the committed-damage owner.");
		}
		catch (Exception ex)
		{
			_log?.LogError("HoMM3 Fortress Predator Instinct [battle] NOT registered (fail closed: no pairs, no bonus): " + ex.GetBaseException().Message);
			return;
		}

		// Frenzy: cast observation + availability. Optional: failure leaves the action inert.
		try
		{
			var patched = 0;
			foreach (var typeHint in GameSymbols.BattleEventLaws.BattleEventDispatcherTypeHints)
			{
				var type = GameMember.FindType(GameSymbols.BattleEventLaws.BattleEventDispatcherTypeId + "." + typeHint, typeHint) ?? hexAssembly.GetType(typeHint);
				if (type == null)
					continue;
				foreach (var methodName in GameSymbols.BattleEventLaws.BattleEventDispatch.NameHints)
				{
					if (string.IsNullOrWhiteSpace(methodName))
						continue;
					foreach (var method in type.GetMethods(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
					{
						if (method.Name == methodName && method.ReturnType == typeof(void) && method.GetParameters().Length == 2)
						{
							Patch(harmony, method, null, nameof(PostfixBattleEventDispatch));
							patched++;
							break;
						}
					}
				}
			}
			var abilityType = ResolveTypeByHints(hexAssembly, Pins.HeroAbilityTypes, "homm3.fortress.predator.heroAbility");
			// Primary cast detection: the hero ability's own cast body (eov.bhav). The dispatcher path above only sees
			// CastAbilityEventArgs; hero abilities raise CastHeroAbilityEventArgs instead (2026-11-14 playtest: Frenzy
			// cast, nothing logged).
			var castPatched = false;
			foreach (var name in GameSymbols.FortressPredatorInstinct.HeroAbilityCast.NameHints ?? Array.Empty<string>())
			{
				if (string.IsNullOrEmpty(name) || castPatched)
					continue;
				foreach (var method in abilityType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
				{
					if (method.Name == name && method.ReturnType == typeof(void) && method.GetParameters().Length == 4)
					{
						Patch(harmony, method, null, nameof(PostfixHeroAbilityCast));
						patched++;
						castPatched = true;
						break;
					}
				}
			}
			if (!castPatched)
				_log?.LogWarning("HoMM3 Fortress Predator Instinct [frenzy]: hero ability cast body not found; only the battle-event path can see Frenzy.");
			foreach (var name in new[] { Pins.HeroAbilityUsable, Pins.HeroAbilityUsableWithFocus })
			{
				foreach (var method in abilityType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
				{
					if (method.Name == name && method.ReturnType == typeof(bool))
					{
						Patch(harmony, method, null, nameof(PostfixHeroAbilityUsable));
						patched++;
						break;
					}
				}
			}
			_log?.LogInfo("HoMM3 Fortress Predator Instinct [frenzy] registered: " + patched + " patch(es) (cast dispatch + availability).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Fortress Predator Instinct [frenzy] NOT registered (Frenzy does nothing): " + ex.GetBaseException().Message);
		}
	}

	// ------------------------------------------------------------------ public queries

	/// <summary>
	/// Damage contribution for the committed-damage owner: +bonus% when <paramref name="caster"/> is the predator of
	/// <paramref name="receiver"/>; -penalty% when <paramref name="caster"/> is a predator hitting anything else while its
	/// prey is alive. Counter hits pass the counterattacker as caster, so they count the same. Also queues
	/// Intimidation's slow for the end of the action. Never adds buffs here.
	/// </summary>
	internal static int DamagePercent(object caster, object receiver, out string detail)
	{
		detail = null;
		if (!_registered || caster == null || receiver == null)
			return 0;
		var casterKey = Homm3DirectStateIdentity.ResolveKeyOrZero(caster);
		var receiverKey = Homm3DirectStateIdentity.ResolveKeyOrZero(receiver);
		if (casterKey == 0 || receiverKey == 0)
			return 0;
		Pair offPrey = null;
		lock (Gate)
		{
			foreach (var battle in Battles)
			{
				if (!battle.ByPredator.TryGetValue(casterKey, out var pair))
					continue;
				var rank = Math.Max(0, Math.Min(3, pair.Side.Rank));
				if (pair.PreyKey != receiverKey)
				{
					offPrey = pair;
					break;
				}
				var percent = BonusPercentByRank[rank];
				if (pair.Side.Intimidation && !PendingIntimidation.Contains(pair))
					PendingIntimidation.Add(pair);
				detail = "Fortress Predator Instinct +" + percent + "% vs prey (" + pair.Side.HeroDescription + " rank " + pair.Side.Rank + ")";
				return percent;
			}
		}
		// Off-prey penalty only while the original prey lives (IsAlive reads native state; keep it outside the lock).
		if (offPrey == null || !IsAlive(offPrey.Prey))
			return 0;
		var penalty = PenaltyPercentByRank[Math.Max(0, Math.Min(3, offPrey.Side.Rank))];
		if (penalty == 0)
			return 0;
		detail = "Fortress Predator Instinct -" + penalty + "% off-prey while prey lives (" + offPrey.Side.HeroDescription + " rank " + offPrey.Side.Rank + ")";
		return -penalty;
	}

	/// <summary>The pair whose predator is <paramref name="attacker"/> and prey is <paramref name="defender"/>, or null.</summary>
	internal static Pair FindPair(object attacker, object defender)
	{
		if (!_registered)
			return null;
		var a = Homm3DirectStateIdentity.ResolveKeyOrZero(attacker);
		var d = Homm3DirectStateIdentity.ResolveKeyOrZero(defender);
		if (a == 0 || d == 0)
			return null;
		lock (Gate)
		{
			foreach (var battle in Battles)
			{
				if (battle.ByPredator.TryGetValue(a, out var pair) && pair.PreyKey == d)
					return pair;
			}
		}
		return null;
	}

	/// <summary>The pair whose predator is <paramref name="predator"/> (any prey), or null.</summary>
	internal static Pair FindByPredator(object predator)
	{
		if (!_registered)
			return null;
		var key = Homm3DirectStateIdentity.ResolveKeyOrZero(predator);
		if (key == 0)
			return null;
		lock (Gate)
		{
			foreach (var battle in Battles)
			{
				if (battle.ByPredator.TryGetValue(key, out var pair))
					return pair;
			}
		}
		return null;
	}

	/// <summary>Pair for a hovered stack: the hovered unit must be a living predator whose prey is alive.</summary>
	internal static bool TryGetHoverPair(object hovered, out Unit predator, out Unit prey, out bool frenzied)
	{
		predator = prey = null;
		frenzied = false;
		if (!_registered || hovered == null)
			return false;
		var key = Homm3DirectStateIdentity.ResolveKeyOrZero(hovered);
		if (key == 0)
			return false;
		Pair found = null;
		lock (Gate)
		{
			foreach (var battle in Battles)
			{
				if (battle.ByPredator.TryGetValue(key, out var pair))
					found = pair;
			}
		}
		if (found == null || !IsAlive(found.Predator) || !IsAlive(found.Prey))
			return false;
		predator = found.Predator;
		prey = found.Prey;
		frenzied = found.Frenzied && found.Side.FrenzyRound >= 0;
		return true;
	}

	/// <summary>Every live pair of every tracked battle (snapshot), for combat hooks and diagnostics.</summary>
	internal static List<Pair> SnapshotPairs()
	{
		var result = new List<Pair>();
		lock (Gate)
		{
			foreach (var battle in Battles)
				result.AddRange(battle.Pairs);
		}
		return result;
	}

	// ------------------------------------------------------------------ battle start

	private static void PostfixBattleLogicInit(object __instance, TransferBattle __1)
	{
		try
		{
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
				var rank = Homm3DungeonDraconicDominionHook.ResolveHeroSkillRank(dataHero, FactionSkillSid);
				if (rank <= 0)
					continue;
				var wrapper = FindSideWrapper(__instance, clone.sides[sideIndex]) as Il2CppObjectBase;
				if (wrapper == null)
				{
					_log?.LogError("HoMM3 Fortress Predator Instinct: side wrapper for " + (dataHero?.configSid ?? "?") + " side " + sideIndex + " not found; no pairs.");
					continue;
				}
				var hunter = new HunterSide
				{
					SideIndex = sideIndex,
					Rank = Math.Min(3, rank),
					Intimidation = Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, IntimidationSid),
					EnduranceHunting = Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, EnduranceHuntingSid),
					Frenzy = Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, FrenzySubSkillSid),
					Cautious = Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, CautiousSid),
					Pounce = Homm3DungeonDraconicDominionHook.HasHeroSubSkill(dataHero, PounceSid),
					HeroDescription = (dataHero?.configSid ?? "?") + " side " + sideIndex,
					SideWrapper = wrapper,
					SideWrapperPointer = wrapper.Pointer,
				};
				battle ??= new BattleState { Logic = __instance, HubPointer = hub.Pointer };
				battle.Sides.Add(hunter);
				_log?.LogInfo("HoMM3 Fortress Predator Instinct armed for " + hunter.HeroDescription + " rank " + hunter.Rank
				              + (hunter.Intimidation ? " +Intimidation" : "") + (hunter.EnduranceHunting ? " +EnduranceHunting" : "")
				              + (hunter.Frenzy ? " +Frenzy" : "") + (hunter.Cautious ? " +Cautious" : "") + (hunter.Pounce ? " +Pounce" : "") + ".");
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
			_log?.LogError("HoMM3 Fortress Predator Instinct Init postfix failed closed (no pairs this battle): " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixRoundStarted(object __instance, object[] __args)
	{
		try
		{
			var battle = FindBattleByHub(__instance);
			if (battle == null || __args == null || __args.Length < 2 || __args[1] is not BattleEventArgs args)
				return;
			battle.Round = args.roundNumber;
			if (!battle.Paired && args.roundNumber >= 1)
				BuildPairs(battle);
			foreach (var side in battle.Sides)
			{
				if (side.FrenzyRound >= 0 && args.roundNumber > side.FrenzyRound)
				{
					side.FrenzyRound = -1;
					foreach (var pair in battle.Pairs)
					{
						if (pair.Side == side)
							pair.Frenzied = false;
					}
					Homm3FortressPredatorInstinctCombat.OnFrenzyEnded(side);
				}
			}
		}
		catch (Exception ex)
		{
			LogLimited("RoundStarted handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void BuildPairs(BattleState battle)
	{
		battle.Paired = true;
		var grid = ReadProperty(battle.Logic, Pins.LogicGrid);
		var hexes = ReadProperty(grid, Pins.GridHexes) as Il2CppReferenceArray<BattleHex>;
		if (hexes == null)
		{
			LogLimited("pairing refused: battle grid unreadable.");
			return;
		}
		// Every living unit on the grid, once (large units cover two hexes), with its side wrapper pointer.
		var units = new List<(Unit Unit, long Key, IntPtr Side)>();
		var seen = new HashSet<long>();
		foreach (var hex in hexes)
		{
			if (hex?.fieldObjects == null)
				continue;
			for (var i = 0; i < hex.fieldObjects.Count; i++)
			{
				var unit = hex.fieldObjects[i]?.TryCast<Unit>();
				if (unit == null || !IsAlive(unit) || ReadProperty(unit, Pins.FieldObjectSide) is not Il2CppObjectBase wrapper)
					continue;
				var key = Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
				if (key == 0 || !seen.Add(key))
					continue;
				units.Add((unit, key, wrapper.Pointer));
			}
		}
		var takenPrey = new HashSet<long>();
		foreach (var side in battle.Sides)
		{
			var predators = new List<(Unit Unit, long Key)>();
			var prey = new List<(Unit Unit, long Key)>();
			var skippedRanged = 0;
			foreach (var entry in units)
			{
				if (entry.Side == side.SideWrapperPointer)
				{
					if (!side.EnduranceHunting && IsRanged(entry.Unit))
					{
						skippedRanged++;
						continue;
					}
					predators.Add((entry.Unit, entry.Key));
				}
				else if (!takenPrey.Contains(entry.Key))
				{
					prey.Add((entry.Unit, entry.Key));
				}
			}
			Shuffle(predators);
			Shuffle(prey);
			var count = Math.Min(predators.Count, prey.Count);
			var parts = new List<string>();
			for (var i = 0; i < count; i++)
			{
				var pair = new Pair
				{
					Predator = predators[i].Unit,
					PredatorKey = predators[i].Key,
					Prey = prey[i].Unit,
					PreyKey = prey[i].Key,
					Side = side,
				};
				takenPrey.Add(pair.PreyKey);
				lock (Gate)
				{
					battle.Pairs.Add(pair);
					battle.ByPredator[pair.PredatorKey] = pair;
					battle.ByPrey[pair.PreyKey] = pair;
				}
				var marks = (TryBuff(pair.Predator, PredatorBuffPrefix + side.Rank, 0, MarkerDuration) ? "" : " predator-mark FAILED")
				            + (TryBuff(pair.Prey, PreyBuffSid, 0, MarkerDuration) ? "" : " prey-mark FAILED");
				parts.Add(DescribeUnit(pair.Predator) + " -> " + DescribeUnit(pair.Prey) + marks);
			}
			_log?.LogInfo("HoMM3 Fortress Predator Instinct pairs for " + side.HeroDescription + " (" + predators.Count + " hunters, "
			              + prey.Count + " enemy stacks" + (skippedRanged > 0 ? ", " + skippedRanged + " ranged skipped" : "") + "): "
			              + (parts.Count == 0 ? "none" : string.Join("; ", parts)) + ".");
		}
	}

	// ------------------------------------------------------------------ follow-ups

	private static void PostfixActionEnded(object __instance)
	{
		try
		{
			if (FindBattleByHub(__instance) == null)
				return;
			List<Pair> pending;
			lock (Gate)
			{
				if (PendingIntimidation.Count == 0)
					return;
				pending = new List<Pair>(PendingIntimidation);
				PendingIntimidation.Clear();
			}
			foreach (var pair in pending)
			{
				if (!IsAlive(pair.Prey))
					continue;
				var ok = TryBuff(pair.Prey, IntimidationSlowSid, 1, IntimidationSlowRounds);
				LogLimited("Intimidation: " + DescribeUnit(pair.Prey) + " slowed (-3 Initiative) by its predator " + DescribeUnit(pair.Predator) + (ok ? "" : " FAILED") + ".");
			}
		}
		catch (Exception ex)
		{
			LogLimited("ActionEnded handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	// ------------------------------------------------------------------ Frenzy

	private static void PostfixBattleEventDispatch(object[] __args)
	{
		try
		{
			if (__args == null)
				return;
			foreach (var arg in __args)
			{
				if (arg == null || !Homm3BattleEventNativeAdapter.TryReadCastAbilityEvent(arg, out var info, out _) || !info.HasAbilityName(FrenzyAbilitySid))
					continue;
				var casterPtr = (info.Caster as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
				var casterSidePtr = (ReadProperty(info.Caster, Pins.FieldObjectSide) as Il2CppObjectBase ?? ReadProperty(info.Caster, Pins.HeroAbilitySide) as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
				var targets = new List<(BattleState Battle, HunterSide Side)>();
				lock (Gate)
				{
					foreach (var battle in Battles)
					{
						foreach (var side in battle.Sides)
						{
							if (side.Frenzy && side.FrenzyRound != battle.Round && (casterPtr == side.SideWrapperPointer || casterSidePtr == side.SideWrapperPointer))
								targets.Add((battle, side));
						}
					}
				}
				if (targets.Count == 0)
				{
					LogLimited("Frenzy cast observed but no Fortress hunter side matched the caster (" + info + ").");
					continue;
				}
				foreach (var (battle, side) in targets)
					Frenzy(battle, side);
			}
		}
		catch (Exception ex)
		{
			LogLimited("Frenzy cast handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static int _castHookSeen;

	private static void PostfixHeroAbilityCast(object __instance)
	{
		try
		{
			var castSid = ReadAbilitySid(__instance);
			if (_castHookSeen++ < 3)
				_log?.LogInfo("HoMM3 Fortress Predator Instinct: hero ability cast seen (sid=" + (castSid ?? "<unreadable>") + ").");
			if (!string.Equals(castSid, FrenzyAbilitySid, StringComparison.Ordinal))
				return;
			var wrapperPtr = (ReadProperty(__instance, Pins.HeroAbilitySide) as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
			BattleState targetBattle = null;
			HunterSide targetSide = null;
			lock (Gate)
			{
				if (!TryMatchFrenzySide(wrapperPtr, out targetBattle, out targetSide))
				{
					LogLimited("Frenzy cast (ability body) but no Fortress Frenzy side matched wrapper 0x" + wrapperPtr.ToString("X") + ".");
					return;
				}
				if (targetSide.FrenzyRound == targetBattle.Round)
					return; // already applied this round (battle-event path)
			}
			Frenzy(targetBattle, targetSide);
		}
		catch (Exception ex)
		{
			LogLimited("Frenzy cast (ability body) handler failed closed: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Pointer match first; when it fails, the only Frenzy side in any live battle (call under Gate).</summary>
	private static bool TryMatchFrenzySide(IntPtr wrapperPtr, out BattleState battle, out HunterSide side, bool log = true)
	{
		battle = null;
		side = null;
		BattleState onlyBattle = null;
		HunterSide only = null;
		var frenzySides = 0;
		foreach (var b in Battles)
		{
			foreach (var s in b.Sides)
			{
				if (!s.Frenzy)
					continue;
				if (wrapperPtr != IntPtr.Zero && s.SideWrapperPointer == wrapperPtr)
				{
					battle = b;
					side = s;
					return true;
				}
				frenzySides++;
				onlyBattle = b;
				only = s;
			}
		}
		if (frenzySides != 1)
			return false;
		battle = onlyBattle;
		side = only;
		if (log)
			_log?.LogInfo("HoMM3 Fortress Predator Instinct Frenzy: side matched by elimination (ability wrapper 0x" + wrapperPtr.ToString("X") + " vs side 0x" + only.SideWrapperPointer.ToString("X") + ").");
		return true;
	}

	private static void Frenzy(BattleState battle, HunterSide side)
	{
		side.FrenzyRound = battle.Round;
		var parts = new List<string>();
		foreach (var pair in battle.Pairs)
		{
			if (pair.Side != side || !IsAlive(pair.Predator))
				continue;
			pair.Frenzied = IsAlive(pair.Prey);
			var haste = TryBuff(pair.Predator, FrenzyHasteSid, 1, FrenzyRounds);
			var taunt = pair.Frenzied && Homm3FortressPredatorInstinctCombat.TryTauntByPrey(pair, out var tauntDetail) ? "taunted" : "no taunt";
			parts.Add(DescribeUnit(pair.Predator) + (haste ? " haste" : " haste FAILED") + ", " + taunt);
		}
		_log?.LogInfo("HoMM3 Fortress Predator Instinct Frenzy for " + side.HeroDescription + " round " + battle.Round + ": " + string.Join("; ", parts) + ".");
	}

	private static void PostfixHeroAbilityUsable(object __instance, ref bool __result)
	{
		if (!__result)
			return;
		try
		{
			if (!string.Equals(ReadAbilitySid(__instance), FrenzyAbilitySid, StringComparison.Ordinal))
				return;
			var wrapperPtr = (ReadProperty(__instance, Pins.HeroAbilitySide) as Il2CppObjectBase)?.Pointer ?? IntPtr.Zero;
			lock (Gate)
			{
				if (TryMatchFrenzySide(wrapperPtr, out var battle, out var side, log: false) && side.FrenzyRound != battle.Round)
				{
					foreach (var pair in battle.Pairs)
					{
						if (pair.Side == side && IsAlive(pair.Predator) && IsAlive(pair.Prey))
							return;
					}
				}
			}
			__result = false;
		}
		catch
		{
			__result = false;
		}
	}

	// ------------------------------------------------------------------ helpers

	private static BattleState FindBattleByHub(object hub)
	{
		if (hub is not Il2CppObjectBase obj)
			return null;
		lock (Gate)
		{
			foreach (var battle in Battles)
			{
				if (battle.HubPointer == obj.Pointer)
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

	/// <summary>Ranged = any default attack of type Shoot or Range (UnitLogicConfig.defaultAttacks). Unreadable = melee.</summary>
	internal static bool IsRanged(Unit unit)
	{
		try
		{
			var attacks = unit?.prop_UnitLogicConfig_0?.defaultAttacks;
			if (attacks == null)
				return false;
			for (var i = 0; i < attacks.Length; i++)
			{
				var attack = attacks[i];
				if (attack == null)
					continue;
				var type = ReadAttackType(attack);
				if (type == EAttackType.Shoot || type == EAttackType.Range)
					return true;
			}
		}
		catch (Exception ex)
		{
			LogLimited("attack type read failed (treated as melee): " + ex.GetBaseException().Message);
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
			if (property.GetValue(attack) is EAttackType value && value != EAttackType.Unknown)
				return value;
		}
		return EAttackType.Unknown;
	}

	internal static bool IsAlive(Unit unit)
	{
		if (unit == null || unit.Pointer == IntPtr.Zero)
			return false;
		try
		{
			var data = ReadProperty(unit, Pins.UnitData);
			if (data == null)
				return false;
			var method = data.GetType().GetMethod(Pins.UnitDataAlive, BindingFlags.Instance | BindingFlags.Public, null, Type.EmptyTypes, null);
			return method == null || (int)method.Invoke(data, null) > 0;
		}
		catch
		{
			return false;
		}
	}

	internal static bool TryBuff(Unit unit, string sid, int level, int duration)
	{
		if (Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(unit, sid, unit, level, duration, 0, true, out _, out var fail))
			return true;
		LogLimited("buff " + sid + " failed on " + DescribeUnit(unit) + ": " + fail);
		return false;
	}

	internal static string DescribeUnit(Unit unit)
	{
		try
		{
			return (unit?.prop_UnitLogicConfig_0?.baseSid ?? "?") + "#" + (Homm3DirectStateIdentity.ResolveKeyOrZero(unit) & 0xFFFF).ToString("x4");
		}
		catch
		{
			return "?";
		}
	}

	private static void Shuffle<T>(List<T> list)
	{
		for (var i = list.Count - 1; i > 0; i--)
		{
			var j = Rng.Next(i + 1);
			(list[i], list[j]) = (list[j], list[i]);
		}
	}

	private static readonly Dictionary<(Type, string), PropertyInfo> PropertyCache = new();

	private static PropertyInfo FindProperty(Type type, string name)
	{
		lock (PropertyCache)
		{
			if (PropertyCache.TryGetValue((type, name), out var cached))
				return cached;
			PropertyInfo found = null;
			for (var cur = type; cur != null && found == null; cur = cur.BaseType)
				found = cur.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			PropertyCache[(type, name)] = found;
			return found;
		}
	}

	private static string ReadAbilitySid(object ability)
	{
		foreach (var name in Pins.HeroAbilitySidMembers ?? Array.Empty<string>())
		{
			if (ReadProperty(ability, name) is string sid && sid.Length > 0)
				return sid;
		}
		return null;
	}

	internal static object ReadProperty(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
			return null;
		var property = FindProperty(obj.GetType(), name);
		if (property != null)
			return property.GetValue(obj);
		var method = obj.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
		return method?.Invoke(obj, null);
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

	private static PropertyInfo RequireProperty(Type type, string name, Type expected)
	{
		var property = FindProperty(type, name);
		if (property == null || (expected != null && property.PropertyType != expected))
			throw new MissingMemberException((type?.FullName ?? "null") + "." + name + (expected == null ? "" : " : " + expected.FullName));
		return property;
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

	private static void Patch(Harmony harmony, MethodInfo target, string prefixName, string postfixName)
	{
		const BindingFlags flags = BindingFlags.Static | BindingFlags.NonPublic;
		var prefix = prefixName == null ? null : typeof(Homm3FortressPredatorInstinctRuntime).GetMethod(prefixName, flags);
		var postfix = postfixName == null ? null : typeof(Homm3FortressPredatorInstinctRuntime).GetMethod(postfixName, flags);
		if (prefix != null && !GameMember.IsHarmonyPatchCompatible(target, prefix, out var prefixReason))
			throw new MissingMethodException("prefix incompatible for " + FormatMethod(target) + ": " + prefixReason);
		if (postfix != null && !GameMember.IsHarmonyPatchCompatible(target, postfix, out var postfixReason))
			throw new MissingMethodException("postfix incompatible for " + FormatMethod(target) + ": " + postfixReason);
		harmony.Patch(target,
			prefix: prefix == null ? null : new HarmonyMethod(prefix),
			postfix: postfix == null ? null : new HarmonyMethod(postfix) { priority = Priority.Last });
	}

	private static string FormatMethod(MethodBase method) => method == null ? "null" : method.DeclaringType?.FullName + "." + method.Name;

	internal static void LogLimited(string message)
	{
		if (_logged++ < 80)
			_log?.LogWarning("HoMM3 Fortress Predator Instinct: " + message);
	}
}
