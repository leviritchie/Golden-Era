using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

/// <summary>
/// Marshal Suppressing Fire: native trap placement stays jaws/VFX, but damage must not
/// use Magog <c>statDmgMult</c> on the trap. Live trap type
/// <c>FieldObjectPublicObBoTrAcTrcg1AcHeUnUnique.Init</c> allocates an empty
/// <see cref="UnitStat"/> at <c>cgtp</c> (source/static + Init disasm); no Core trap
/// donor uses <c>statDmgMult</c>. Wall-of-Flame CastDealerConfig base damage is the
/// stamped trap damage shape. At Init, stamp 150% of the placer stack's damageMin/Max
/// onto the instance TrapConfig clone so trigger damage matches the ability text.
/// Proof boundary: startup registration is the acceptance bar; combat stamping and
/// observed damage remain unvalidated.
/// </summary>
internal static class Homm3MarshalSuppressingFireTrapBridge
{
	internal const string ActiveArchitecture = "marshal_suppressing_fire_wall_of_flame_stamp";
	private const string LogPrefix = "HOMM3_MARSHAL_SUPPRESSING_FIRE";
	private const float AttackDamageMult = 1.5f;
	private const BindingFlags MemberFlags =
		BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

	private static bool _registered;
	private static ManualLogSource _log;
	private static MethodInfo _trapInit;
	private static int _loggedStamps;
	private static int _loggedRejects;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			if (!TryResolveTrapInit(out var reason))
			{
				log?.LogWarning(LogPrefix + " skipped: " + reason);
				return;
			}
			harmony.Patch(
				_trapInit,
				postfix: new HarmonyMethod(typeof(Homm3MarshalSuppressingFireTrapBridge), nameof(PostfixTrapInit)));
			_registered = true;
			log?.LogInfo(
				LogPrefix
				+ " registered architecture="
				+ ActiveArchitecture
				+ " init="
				+ (_trapInit.DeclaringType?.FullName ?? "?")
				+ "."
				+ _trapInit.Name
				+ ".");
		}
		catch (Exception ex)
		{
			// Optional combat stamp must not abort the whole OfflineUnlockMod Load path.
			log?.LogWarning(LogPrefix + " skipped: exception:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static bool TryResolveTrapInit(out string reason)
	{
		reason = null;
		Type trapType = null;
		foreach (var hint in GameSymbols.MarshalSuppressingFireTrap.TrapRuntimeTypeHints)
		{
			trapType = AccessTools.TypeByName(hint);
			if (trapType != null)
				break;
		}
		if (trapType == null)
		{
			reason = "trap_runtime_type_unresolved";
			return false;
		}

		// Declared-only: base FieldObject also exposes Init, and AccessTools.Method("Init")
		// throws AmbiguousMatchException which would abort the whole plugin Load.
		MethodInfo match = null;
		foreach (var method in AccessTools.GetDeclaredMethods(trapType))
		{
			if (method == null)
				continue;
			if (!IsTrapInitMemberName(method.Name))
				continue;
			var ps = method.GetParameters();
			if (method.ReturnType != typeof(bool) || ps.Length != 6)
				continue;
			if (ps[0].ParameterType != typeof(string) || ps[1].ParameterType != typeof(int))
				continue;
			if (match != null)
			{
				reason = "trap_Init_ambiguous";
				return false;
			}
			match = method;
		}

		if (match == null)
		{
			reason = "trap_Init_unresolved";
			return false;
		}

		_trapInit = match;
		return true;
	}

	private static bool IsTrapInitMemberName(string name)
	{
		if (string.IsNullOrEmpty(name))
			return false;
		foreach (var hint in GameSymbols.MarshalSuppressingFireTrap.TrapInitMembers)
		{
			if (string.Equals(name, hint, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static void PostfixTrapInit(object __instance, bool __result, object[] __args)
	{
		if (!__result || __instance == null || __args == null || __args.Length < 6)
			return;
		var sid = __args[0] as string;
		if (!string.Equals(sid, GameSymbols.MarshalSuppressingFireTrap.TrapSid, StringComparison.Ordinal))
			return;

		try
		{
			if (!TryStampPlacerAttackDamage(__instance, __args[5], out var minDamage, out var maxDamage, out var detail))
			{
				LogReject(detail);
				return;
			}
			LogStamp(minDamage, maxDamage, detail);
		}
		catch (Exception ex)
		{
			LogReject("exception:" + ex.Message);
		}
	}

	private static bool TryStampPlacerAttackDamage(
		object trap,
		object initialCastSource,
		out int minDamage,
		out int maxDamage,
		out string detail)
	{
		minDamage = 0;
		maxDamage = 0;
		detail = null;

		if (!Homm3BattleEventNativeAdapter.TryResolveBattleUnit(initialCastSource, out var placer)
		    || placer == null)
		{
			detail = "placer_unit_unresolved";
			return false;
		}
		if (!DamageKillMapping.TryGetCombatStats(placer, out var stats) || stats == null)
		{
			detail = "placer_unitstat_unresolved";
			return false;
		}
		if (!DamageKillMapping.TryGetStackCount(placer, out var stacks) || stacks <= 0)
		{
			detail = "placer_stack_unresolved";
			return false;
		}

		var damageMin = Math.Max(0, stats.damageMin);
		var damageMax = Math.Max(damageMin, stats.damageMax);
		minDamage = ScaleStackDamage(damageMin, stacks);
		maxDamage = ScaleStackDamage(damageMax, stacks);
		if (minDamage <= 0 || maxDamage <= 0)
		{
			detail = "scaled_damage_non_positive stacks=" + stacks
			         + " damageMin=" + damageMin
			         + " damageMax=" + damageMax;
			return false;
		}

		if (!TryResolveInstanceTrapConfig(trap, out var trapConfig, out var configSource))
		{
			detail = "instance_trap_config_unresolved";
			return false;
		}
		var dealer = trapConfig.damageDealer;
		if (dealer == null)
		{
			detail = "damage_dealer_null source=" + configSource;
			return false;
		}

		dealer.minBaseDmg = minDamage;
		dealer.maxBaseDmg = maxDamage;
		dealer.minStackDmg = 0;
		dealer.maxStackDmg = 0;
		dealer.statDmgMult = 0f;
		detail = "source=" + configSource
		         + " stacks=" + stacks
		         + " unitDamage=" + damageMin + "-" + damageMax
		         + " mult=" + AttackDamageMult.ToString("0.##");
		return true;
	}

	private static int ScaleStackDamage(int perCreatureDamage, int stacks)
	{
		var scaled = perCreatureDamage * (double)stacks * AttackDamageMult;
		if (scaled <= 0d || scaled > int.MaxValue)
			return 0;
		return Math.Max(1, (int)Math.Round(scaled, MidpointRounding.AwayFromZero));
	}

	private static bool TryResolveInstanceTrapConfig(object trap, out TrapConfig trapConfig, out string source)
	{
		trapConfig = null;
		source = null;
		var type = trap.GetType();
		foreach (var name in GameSymbols.MarshalSuppressingFireTrap.InstanceTrapConfigMembers)
		{
			var prop = type.GetProperty(name, MemberFlags);
			if (prop != null && typeof(TrapConfig).IsAssignableFrom(prop.PropertyType))
			{
				trapConfig = prop.GetValue(trap, null) as TrapConfig;
				if (trapConfig != null)
				{
					source = "prop:" + name;
					return true;
				}
			}
			var field = type.GetField(name, MemberFlags);
			if (field != null && typeof(TrapConfig).IsAssignableFrom(field.FieldType))
			{
				trapConfig = field.GetValue(trap) as TrapConfig;
				if (trapConfig != null)
				{
					source = "field:" + name;
					return true;
				}
			}
			var method = type.GetMethod(name, MemberFlags, null, Type.EmptyTypes, null);
			if (method != null && typeof(TrapConfig).IsAssignableFrom(method.ReturnType))
			{
				trapConfig = method.Invoke(trap, null) as TrapConfig;
				if (trapConfig != null)
				{
					source = "method:" + name;
					return true;
				}
			}
		}
		return false;
	}

	private static void LogStamp(int minDamage, int maxDamage, string detail)
	{
		if (_loggedStamps++ >= 16)
			return;
		_log?.LogInfo(
			LogPrefix
			+ " stamped wall-of-flame base damage="
			+ minDamage
			+ "-"
			+ maxDamage
			+ " "
			+ detail
			+ ".");
	}

	private static void LogReject(string detail)
	{
		if (_loggedRejects++ >= 16)
			return;
		_log?.LogWarning(LogPrefix + " stamp rejected: " + detail);
	}
}
