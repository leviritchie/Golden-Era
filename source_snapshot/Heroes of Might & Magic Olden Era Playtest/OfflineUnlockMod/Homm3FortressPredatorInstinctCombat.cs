using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using BattleHex = Hex.Session.Battle.Hex;

namespace OfflineUnlockMod;

/// <summary>
/// Fortress Predator Instinct expert subskills that change the native attack sequence (build 26615913 pins in
/// <see cref="GameSymbols.FortressPredatorInstinct"/>; evidence V:\olden_port_work\predator_instinct\research_a).
///
/// - Pounce: prefix on the attack builder's counter-queue (eqd.bhqp) skips the CounterAttackStep when the attacker is
///   a Pounce predator and the counterattacker is its prey. bhqp is the only place a counter (normal, parry or the
///   after-attack half of counter_before_and_after_attack) is queued, so no charge is spent and no shared config
///   (triggerCounter, alwaysCounter) is touched. A postfix on the damage-preview forecast (eqd.bhqo) keeps the UI honest.
/// - Cautious: prefix on the attack builder (eqd.bhqd) remembers the attacker; a postfix on the parry predicate
///   (eqd.bhqe, "target counters before the attack") answers true when the target is a Cautious predator and the
///   attacker is its prey. Native parry then runs unchanged: counter first, still gated by charge/reach/triggerCounter.
/// - Frenzy taunt: postfix on the taunt choke point (ezx.bjug, "taunt blocks this hex") marks every hex holding an
///   enemy other than the prey as blocked for a frenzied predator, but only while the prey is reachable this turn
///   (ezx.bjui, the native taunt reach rule), so a predator that cannot reach its prey is never frozen. Empty hexes keep
///   the native answer, so movement is unaffected. Counters pass ignoreTaunt and never reach bjug.
///
/// Pairs are matched by native-pointer keys (<see cref="Homm3FortressPredatorInstinctRuntime.FindPair"/>), so AI
/// battle clones never match. Every hook fails closed to the native result.
/// Proof tier: static decompile + build. Runtime unproven until the owner tests in game.
/// </summary>
internal static class Homm3FortressPredatorInstinctCombat
{
	[ThreadStatic] private static List<Unit> _attackers;
	private static ManualLogSource _log;
	private static bool _attempted;
	private static bool _pounce;
	private static bool _cautious;
	private static bool _taunt;
	private static MethodInfo _canReachTaunter;
	private static int _logged;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		if (!Homm3FortressPredatorInstinctRuntime.Registered)
		{
			log?.LogWarning("HoMM3 Fortress Predator Instinct combat hooks skipped: the pairing runtime is not registered.");
			return;
		}
		var hexAssembly = typeof(TransferBattle).Assembly;
		var builder = FindType(hexAssembly, GameSymbols.FortressPredatorInstinct.AttackBuilderTypeHints);
		var rules = FindType(hexAssembly, GameSymbols.FortressPredatorInstinct.TargetRulesTypeHints);
		var self = typeof(Homm3FortressPredatorInstinctCombat);

		_pounce = TryPatch(harmony, builder, GameSymbols.FortressPredatorInstinct.QueueCounter, 7, "Pounce counter queue", prefix: self.GetMethod(nameof(PrefixQueueCounter), BindingFlags.NonPublic | BindingFlags.Static));
		if (_pounce)
			TryPatch(harmony, builder, GameSymbols.FortressPredatorInstinct.WillRetaliate, 5, "Pounce retaliation forecast", postfix: self.GetMethod(nameof(PostfixWillRetaliate), BindingFlags.NonPublic | BindingFlags.Static));

		var buildPatched = TryPatch(harmony, builder, GameSymbols.FortressPredatorInstinct.BuildAttack, 7, "Cautious attacker scope",
			prefix: self.GetMethod(nameof(PrefixBuildAttack), BindingFlags.NonPublic | BindingFlags.Static),
			finalizer: self.GetMethod(nameof(FinalizerBuildAttack), BindingFlags.NonPublic | BindingFlags.Static));
		_cautious = buildPatched && TryPatch(harmony, builder, GameSymbols.FortressPredatorInstinct.TargetParries, 1, "Cautious parry predicate", postfix: self.GetMethod(nameof(PostfixTargetParries), BindingFlags.NonPublic | BindingFlags.Static));

		_canReachTaunter = FindMethod(rules, GameSymbols.FortressPredatorInstinct.CanReachTaunter, 3);
		_taunt = _canReachTaunter != null
		         && TryPatch(harmony, rules, GameSymbols.FortressPredatorInstinct.TauntBlocksHex, 3, "Frenzy taunt", postfix: self.GetMethod(nameof(PostfixTauntBlocksHex), BindingFlags.NonPublic | BindingFlags.Static));
		if (_canReachTaunter == null)
			log?.LogWarning("HoMM3 Fortress Predator Instinct: taunt reach check not found; Frenzy grants Haste without the taunt.");
		log?.LogInfo("HoMM3 Fortress Predator Instinct combat hooks: Pounce=" + _pounce + ", Cautious=" + _cautious + ", Frenzy taunt=" + _taunt + ".");
	}

	/// <summary>Called when Frenzy is cast. The taunt itself is the bjug postfix reading <c>pair.Frenzied</c>.</summary>
	internal static bool TryTauntByPrey(Homm3FortressPredatorInstinctRuntime.Pair pair, out string detail)
	{
		detail = _taunt ? "taunt hook live" : "taunt hook missing";
		return _taunt && pair != null && pair.Frenzied;
	}

	internal static void OnFrenzyEnded(Homm3FortressPredatorInstinctRuntime.HunterSide side)
	{
		LogLimited("Frenzy ended for " + side?.HeroDescription + "; predators are no longer taunted.");
	}

	// ------------------------------------------------------------------ Pounce

	/// <summary>bhqp(anchor, attacker, counterattacker, ability, hexes, delay, forced): false skips queueing the counter.</summary>
	private static bool PrefixQueueCounter(Unit __1, Unit __2)
	{
		try
		{
			var pair = Homm3FortressPredatorInstinctRuntime.FindPair(__1, __2);
			if (pair == null || !pair.Side.Pounce)
				return true;
			LogLimited("Pounce: " + Homm3FortressPredatorInstinctRuntime.DescribeUnit(__2) + " cannot retaliate against its predator " + Homm3FortressPredatorInstinctRuntime.DescribeUnit(__1) + ".");
			return false;
		}
		catch (Exception ex)
		{
			LogLimited("Pounce prefix failed closed: " + ex.GetBaseException().Message);
			return true;
		}
	}

	private static void PostfixWillRetaliate(Unit __0, Unit __1, ref bool __result)
	{
		if (!__result)
			return;
		try
		{
			var pair = Homm3FortressPredatorInstinctRuntime.FindPair(__0, __1);
			if (pair != null && pair.Side.Pounce)
				__result = false;
		}
		catch
		{
			// keep the native forecast
		}
	}

	// ------------------------------------------------------------------ Cautious

	private static void PrefixBuildAttack(Unit __1)
	{
		(_attackers ??= new List<Unit>()).Add(__1);
	}

	private static Exception FinalizerBuildAttack(Exception __exception)
	{
		if (_attackers != null && _attackers.Count > 0)
			_attackers.RemoveAt(_attackers.Count - 1);
		return __exception;
	}

	/// <summary>bhqe(target): true makes the target counter before the attack (native parry order).</summary>
	private static void PostfixTargetParries(Unit __0, ref bool __result)
	{
		if (__result || _attackers == null || _attackers.Count == 0)
			return;
		try
		{
			var attacker = _attackers[_attackers.Count - 1];
			var pair = Homm3FortressPredatorInstinctRuntime.FindPair(__0, attacker);
			if (pair == null || !pair.Side.Cautious)
				return;
			__result = true;
			LogLimited("Cautious: " + Homm3FortressPredatorInstinctRuntime.DescribeUnit(__0) + " parries its prey " + Homm3FortressPredatorInstinctRuntime.DescribeUnit(attacker) + ".");
		}
		catch (Exception ex)
		{
			LogLimited("Cautious postfix failed closed: " + ex.GetBaseException().Message);
		}
	}

	// ------------------------------------------------------------------ Frenzy taunt

	/// <summary>bjug(battle, unit, targetHex): true when taunt blocks the hex for <paramref name="__1"/>.</summary>
	private static void PostfixTauntBlocksHex(object __0, Unit __1, BattleHex __2, ref bool __result)
	{
		if (__result || __1 == null || __2 == null)
			return;
		try
		{
			var pair = Homm3FortressPredatorInstinctRuntime.FindByPredator(__1);
			if (pair == null || !pair.Frenzied || pair.Side.FrenzyRound < 0)
				return;
			var occupant = ReadOccupant(__2);
			if (occupant == null || occupant.Pointer == IntPtr.Zero || occupant.Pointer == __1.Pointer)
				return;
			if (Homm3DirectStateIdentity.ResolveKeyOrZero(occupant) == pair.PreyKey)
				return;
			if (!Homm3FortressPredatorInstinctRuntime.IsAlive(pair.Prey))
				return;
			if (!(_canReachTaunter.Invoke(null, new[] { __0, __1, pair.Prey }) is bool reach) || !reach)
				return;
			__result = true;
		}
		catch (Exception ex)
		{
			LogLimited("Frenzy taunt postfix failed closed: " + ex.GetBaseException().Message);
		}
	}

	// ------------------------------------------------------------------ plumbing

	private static PropertyInfo _hexOccupant;

	private static Unit ReadOccupant(BattleHex hex)
	{
		if (_hexOccupant == null)
		{
			foreach (var name in GameSymbols.FortressPredatorInstinct.HexOccupantMembers)
			{
				var property = typeof(BattleHex).GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (property != null && typeof(Unit).IsAssignableFrom(property.PropertyType))
				{
					_hexOccupant = property;
					break;
				}
			}
			if (_hexOccupant == null)
				throw new MissingMemberException("Hex occupant property " + string.Join("|", GameSymbols.FortressPredatorInstinct.HexOccupantMembers));
		}
		return _hexOccupant.GetValue(hex) as Unit;
	}

	private static Type FindType(Assembly assembly, string[] hints)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			var type = assembly.GetType(hint) ?? GameMember.FindType(hint, hint);
			if (type != null)
				return type;
		}
		return null;
	}

	private static MethodInfo FindMethod(Type type, GameSymbols.MethodSymbol symbol, int parameterCount)
	{
		if (type == null || symbol.NameHints == null)
			return null;
		foreach (var name in symbol.NameHints)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			foreach (var method in type.GetMethods(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (method.Name == name && method.GetParameters().Length == parameterCount)
					return method;
			}
		}
		return null;
	}

	private static bool TryPatch(Harmony harmony, Type owner, GameSymbols.MethodSymbol symbol, int parameterCount, string label, MethodInfo prefix = null, MethodInfo postfix = null, MethodInfo finalizer = null)
	{
		try
		{
			var target = FindMethod(owner, symbol, parameterCount);
			if (target == null)
			{
				_log?.LogWarning("HoMM3 Fortress Predator Instinct: " + label + " target " + (owner?.FullName ?? "<type missing>") + "." + string.Join("|", symbol.NameHints) + " not found; subskill disabled.");
				return false;
			}
			harmony.Patch(target,
				prefix: prefix == null ? null : new HarmonyMethod(prefix),
				postfix: postfix == null ? null : new HarmonyMethod(postfix),
				finalizer: finalizer == null ? null : new HarmonyMethod(finalizer));
			return true;
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Fortress Predator Instinct: " + label + " patch failed; subskill disabled: " + ex.GetBaseException().Message);
			return false;
		}
	}

	private static void LogLimited(string message)
	{
		if (_logged >= 60)
			return;
		_logged++;
		_log?.LogInfo("HoMM3 Fortress Predator Instinct: " + message);
	}
}
