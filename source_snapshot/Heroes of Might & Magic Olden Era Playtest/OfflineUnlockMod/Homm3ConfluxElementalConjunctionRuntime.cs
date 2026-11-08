using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

/// <summary>
/// Source-prepared June 19 from edited hard-law CSV. Applies Conflux elemental-family
/// battle-start law bonuses by temporarily mutating TransferHero hero stats before
/// native BattleLogic.Init builds battle state, then restoring immediately after Init.
/// Runtime behavior is unvalidated until a Conflux combat pilot proves visible stats.
/// </summary>
internal static class Homm3ConfluxElementalConjunctionRuntime
{
	private const string ConfluxFactionSid = "homm3_conflux";
	private static bool _registered;
	private static ManualLogSource _log;
	private static int _loggedApplications;
	private static int _loggedSkips;

	private static readonly Dictionary<string, string> ElementalFamiliesByUnitSid = new(StringComparer.Ordinal)
	{
		{ "h3_pixie", "pixie" },
		{ "h3_pixie_upg", "pixie" },
		{ "h3_pixie_upg_alt", "pixie" },
		{ "h3_air_elemental", "air" },
		{ "h3_air_elemental_upg", "air" },
		{ "h3_air_elemental_upg_alt", "air" },
		{ "h3_water_elemental", "water" },
		{ "h3_water_elemental_upg", "water" },
		{ "h3_water_elemental_upg_alt", "water" },
		{ "h3_fire_elemental", "fire" },
		{ "h3_fire_elemental_upg", "fire" },
		{ "h3_fire_elemental_upg_alt", "fire" },
		{ "h3_earth_elemental", "earth" },
		{ "h3_earth_elemental_upg", "earth" },
		{ "h3_earth_elemental_upg_alt", "earth" },
		{ "h3_psychic_elemental", "psychic" },
		{ "h3_psychic_elemental_upg", "psychic" },
		{ "h3_psychic_elemental_upg_alt", "psychic" },
		{ "h3_firebird", "firebird" },
		{ "h3_firebird_upg", "firebird" },
		{ "h3_firebird_upg_alt", "firebird" },
	};

	private sealed class BattleInitState
	{
		internal readonly List<HeroStatSnapshot> Snapshots = new();
	}

	private sealed class HeroStatSnapshot
	{
		internal object Stat;
		internal MemberInfo Member;
		internal int OriginalValue;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			var battleLogicType = ResolveRequiredTypeByHint(
				hexAssembly,
				GameSymbols.DraconicDominion.BattleLogicTypeHints,
				"homm3.conflux.elementalConjunction.battleLogic");
			var transferBattleType = ResolveRequiredTypeByName(
				hexAssembly,
				GameSymbols.DraconicDominion.TransferBattleTypeName,
				"homm3.conflux.elementalConjunction.transferBattle");
			var battleLogicInitMethod = ResolveRequiredExactNamedMethod(
				battleLogicType,
				typeof(void),
				new[] { typeof(int), transferBattleType, typeof(bool), typeof(bool) },
				GameSymbols.DraconicDominion.BattleLogicInit.NameHints[0],
				"homm3.conflux.elementalConjunction.battleLogic.init",
				m => !m.IsStatic);

			PatchPrefix(harmony, battleLogicInitMethod, nameof(PrefixBattleLogicInit));
			PatchFinalizer(harmony, battleLogicInitMethod, nameof(FinalizerBattleLogicInit));
			_registered = true;
			_log?.LogInfo("HoMM3 Conflux Elemental Conjunction runtime registered on " + FormatMethod(battleLogicInitMethod) + ". Gameplay is packet-gated and fails closed if active law/rank or stat members are unresolved.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Conflux Elemental Conjunction runtime not registered; exact startup surface missing: " + ex.Message);
		}
	}

	private static void PrefixBattleLogicInit(object __1, ref BattleInitState __state)
	{
		__state = null;
		try
		{
			__state = ApplyBattleInitBonuses(__1);
		}
		catch (Exception ex)
		{
			LogLimited("battle init mutation failed closed: " + ex.Message);
		}
	}

	private static Exception FinalizerBattleLogicInit(Exception __exception, BattleInitState __state)
	{
		RestoreSnapshots(__state);
		return __exception;
	}

	private static BattleInitState ApplyBattleInitBonuses(object transferBattle)
	{
		if (transferBattle == null)
			return null;
		var sidesValue = ReadMember(transferBattle, GameSymbols.DraconicDominion.TransferBattleSidesMembers);
		var transferSides = EnumerateObjects(sidesValue).Where(side => side != null).ToList();
		if (transferSides.Count == 0)
			return null;

		var state = new BattleInitState();
		foreach (var transferSideObject in transferSides)
		{
			var transferSide = transferSideObject as TransferSide;
			if (transferSide == null)
			{
				LogLimited("battle init skipped side with unexpected transfer-side type: " + DescribeObject(transferSideObject));
				continue;
			}

			var familyCount = CountUniqueElementalFamilies(transferSide, out var families);
			if (familyCount <= 0)
				continue;

			var changed = 0;
			changed += TryApplyLawStat(transferSideObject, Homm3CustomFactionLawRuntime.MeleeFormationIndex, "battle.melee-formation", "attack", new[] { "attack" }, familyCount, state, families) ? 1 : 0;
			changed += TryApplyLawStat(transferSideObject, Homm3CustomFactionLawRuntime.RangedFormationIndex, "battle.ranged-formation", "defense", new[] { "defense", "defence" }, familyCount, state, families) ? 1 : 0;
			changed += TryApplyLawStat(transferSideObject, Homm3CustomFactionLawRuntime.SpellSchoolAccessHighIndex, "spell.high", "spell power", new[] { "spellPower", "spellpower", "magicPower", "power" }, familyCount, state, families) ? 1 : 0;

			if (changed == 0)
				LogLimited("battle init found Conflux elemental families but no active implemented law applied; families=" + families + ".");
		}

		return state.Snapshots.Count == 0 ? null : state;
	}

	private static bool TryApplyLawStat(object transferSideObject, int lawIndex, string handlerKey, string label, string[] memberNames, int familyCount, BattleInitState state, string families)
	{
		if (!Homm3CustomLawHandlerRegistry.TryEnterHandler(transferSideObject, handlerKey, lawIndex, out var context, out var failReason))
		{
			LogLimited("battle init " + label + " skipped: " + failReason);
			return false;
		}
		if (!string.Equals(context.Law.FactionSid, ConfluxFactionSid, StringComparison.Ordinal))
			return false;

		var transferHero = ResolveTransferHero(transferSideObject);
		if (transferHero == null)
		{
			LogLimited("battle init " + label + " failed closed for " + context + ": transfer hero missing.");
			return false;
		}

		var changed = 0;
		changed += TryApplyStatDelta(transferHero.heroStat, memberNames, familyCount, state) ? 1 : 0;
		changed += TryApplyStatDelta(transferHero.heroStatUnclamped, memberNames, familyCount, state) ? 1 : 0;
		if (changed == 0)
		{
			LogLimited("battle init " + label + " failed closed for " + context + ": exact HeroStat member not found from candidates [" + string.Join(",", memberNames) + "].");
			return false;
		}

		if (_loggedApplications++ < 24)
			_log?.LogInfo("HoMM3 Conflux Elemental Conjunction applied +" + familyCount + " " + label + " before battle init: context={" + context + "} families=" + families + " heroStats=" + changed + ". Restored after Init; expected native battle state should capture the temporary transfer stats.");
		return true;
	}

	private static int CountUniqueElementalFamilies(TransferSide transferSide, out string detail)
	{
		var families = new HashSet<string>(StringComparer.Ordinal);
		if (transferSide?.units != null)
		{
			foreach (var unit in transferSide.units)
			{
				var sid = NormalizeSid(unit?.configSid);
				if (sid != null && ElementalFamiliesByUnitSid.TryGetValue(sid, out var family))
					families.Add(family);
			}
		}
		detail = families.Count == 0 ? "none" : string.Join(",", families.OrderBy(value => value, StringComparer.Ordinal));
		return families.Count;
	}

	private static TransferHero ResolveTransferHero(object transferSide)
	{
		return (transferSide as TransferSide)?.hero;
	}

	private static bool TryApplyStatDelta(object heroStat, string[] names, int delta, BattleInitState state)
	{
		if (heroStat == null || names == null || delta == 0 || state == null)
			return false;
		var type = heroStat.GetType();
		foreach (var name in names)
		{
			var member = ResolveWritableIntMember(type, name);
			if (member == null)
				continue;
			var current = ReadIntMember(heroStat, member);
			RecordSnapshot(state, heroStat, member, current);
			WriteIntMember(heroStat, member, checked(current + delta));
			return true;
		}
		return false;
	}

	private static MemberInfo ResolveWritableIntMember(Type type, string name)
	{
		if (type == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var field = type.GetField(name, flags);
		if (field != null && field.FieldType == typeof(int) && !field.IsInitOnly)
			return field;
		var property = type.GetProperty(name, flags);
		if (property != null && property.PropertyType == typeof(int) && property.CanRead && property.CanWrite)
			return property;
		return null;
	}

	private static int ReadIntMember(object target, MemberInfo member)
	{
		return member switch
		{
			FieldInfo field => (int)field.GetValue(target),
			PropertyInfo property => (int)property.GetValue(target),
			_ => 0,
		};
	}

	private static void WriteIntMember(object target, MemberInfo member, int value)
	{
		switch (member)
		{
			case FieldInfo field:
				field.SetValue(target, value);
				break;
			case PropertyInfo property:
				property.SetValue(target, value);
				break;
		}
	}

	private static void RecordSnapshot(BattleInitState state, object stat, MemberInfo member, int originalValue)
	{
		if (state.Snapshots.Any(snapshot => ReferenceEquals(snapshot.Stat, stat) && snapshot.Member == member))
			return;
		state.Snapshots.Add(new HeroStatSnapshot { Stat = stat, Member = member, OriginalValue = originalValue });
	}

	private static void RestoreSnapshots(BattleInitState state)
	{
		if (state == null)
			return;
		foreach (var snapshot in state.Snapshots)
		{
			if (snapshot?.Stat == null || snapshot.Member == null)
				continue;
			WriteIntMember(snapshot.Stat, snapshot.Member, snapshot.OriginalValue);
		}
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

	private static void PatchPrefix(Harmony harmony, MethodInfo target, string prefixName)
	{
		var prefix = AccessTools.Method(typeof(Homm3ConfluxElementalConjunctionRuntime), prefixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, prefix, out var reason))
			throw new MissingMethodException("prefix incompatible for " + FormatMethod(target) + ": " + reason);
		harmony.Patch(target, prefix: new HarmonyMethod(prefix));
	}

	private static void PatchFinalizer(Harmony harmony, MethodInfo target, string finalizerName)
	{
		var finalizer = AccessTools.Method(typeof(Homm3ConfluxElementalConjunctionRuntime), finalizerName);
		if (!GameMember.IsHarmonyPatchCompatible(target, finalizer, out var reason))
			throw new MissingMethodException("finalizer incompatible for " + FormatMethod(target) + ": " + reason);
		harmony.Patch(target, finalizer: new HarmonyMethod(finalizer));
	}

	private static IEnumerable<object> EnumerateObjects(object value)
	{
		if (value == null)
			yield break;
		if (value is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
				yield return item;
		}
	}

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			var property = type.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0)
				return property.GetValue(obj);
			var field = type.GetField(name, flags);
			if (field != null)
				return field.GetValue(obj);
			var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null)
				return method.Invoke(obj, null);
		}
		return null;
	}

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "null" : method.DeclaringType?.FullName + "." + method.Name;
	}

	private static string DescribeObject(object value)
	{
		return value == null ? "null" : value.GetType().FullName;
	}

	private static void LogLimited(string message)
	{
		if (_loggedSkips++ < 24)
			_log?.LogWarning("HoMM3 Conflux Elemental Conjunction runtime: " + message);
	}
}
