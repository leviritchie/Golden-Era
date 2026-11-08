using System;
using System.Reflection;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Exact native adapter for battle spell cast-gate surfaces.
/// Source-prepared from June 18 decomp/live-bridge metadata evidence. This
/// class does not register hooks, does not alter spell availability, and does
/// not synchronize UI. It only centralizes exact gate reads for future spell
/// law handlers after packet proof is promoted.
/// </summary>
internal static class Homm3SpellCastGateNativeAdapter
{
	private static Type _battleSpellLogicType;
	private static Type _battleSpellPoolType;
	private static MethodInfo _cooldownReadiness;
	private static MethodInfo _fullCastGate;
	private static MethodInfo _spellCounterGate;
	private static MethodInfo _indexSelectionGate;
	private static bool _resolved;
	private static string _resolveFailure;

	internal static bool TryReadCooldownReadiness(object battleSpell, out bool ready, out string failReason)
	{
		ready = false;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateBattleSpell(battleSpell, out failReason))
			return false;
		if (_cooldownReadiness == null)
		{
			failReason = "cooldown readiness method is unresolved";
			return false;
		}

		try
		{
			ready = Convert.ToBoolean(_cooldownReadiness.Invoke(battleSpell, Array.Empty<object>()));
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "cooldown readiness read failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryReadFullCastGate(object battleSpell, object caster, out bool allowed, out string failReason)
	{
		allowed = false;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateBattleSpell(battleSpell, out failReason))
			return false;
		if (caster == null)
		{
			failReason = "caster instance is null";
			return false;
		}
		if (_fullCastGate == null)
		{
			failReason = "full cast gate method is unresolved";
			return false;
		}

		try
		{
			allowed = Convert.ToBoolean(_fullCastGate.Invoke(battleSpell, new[] { caster }));
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "full cast gate read failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryReadSpellCounterGate(object battleSpellPool, string spellSid, object school, out bool allowed, out string failReason)
	{
		allowed = false;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateSpellPool(battleSpellPool, out failReason))
			return false;
		if (string.IsNullOrWhiteSpace(spellSid))
		{
			failReason = "spell SID is empty";
			return false;
		}
		if (school == null)
		{
			failReason = "spell school is null";
			return false;
		}
		if (_spellCounterGate == null)
		{
			failReason = "spell counter gate method is unresolved";
			return false;
		}

		try
		{
			allowed = Convert.ToBoolean(_spellCounterGate.Invoke(battleSpellPool, new[] { spellSid, school }));
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "spell counter gate read failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryReadIndexSelectionGate(object battleSpellPool, int index, out bool allowed, out string failReason)
	{
		allowed = false;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateSpellPool(battleSpellPool, out failReason))
			return false;
		if (_indexSelectionGate == null)
		{
			failReason = "index selection gate method is unresolved";
			return false;
		}

		try
		{
			allowed = Convert.ToBoolean(_indexSelectionGate.Invoke(battleSpellPool, new object[] { index }));
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "index selection gate read failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryDescribeGateSurfaces(out string description, out string failReason)
	{
		description = null;
		if (!TryResolve(out failReason))
			return false;

		description =
			"battleSpellLogicType=" + DescribeType(_battleSpellLogicType)
			+ " cooldownReadiness=" + DescribeMethod(_cooldownReadiness)
			+ " fullCastGate=" + DescribeMethod(_fullCastGate)
			+ " battleSpellPoolType=" + DescribeType(_battleSpellPoolType)
			+ " spellCounterGate=" + DescribeMethod(_spellCounterGate)
			+ " indexSelectionGate=" + DescribeMethod(_indexSelectionGate);
		failReason = null;
		return true;
	}

	internal static bool TryResolve(out string failReason)
	{
		if (_resolved)
		{
			failReason = _resolveFailure;
			return _resolveFailure == null;
		}

		_resolved = true;
		_battleSpellLogicType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellCooldownLawsBattleSpellLogic);
		_battleSpellPoolType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellCooldownLawsBattleSpellPool);

		if (_battleSpellLogicType == null)
			return FailResolve("battle spell logic type was not found", out failReason);
		if (_battleSpellPoolType == null)
			return FailResolve("battle spell pool type was not found", out failReason);

		_cooldownReadiness = ResolveExactMethod(
			_battleSpellLogicType,
			GameSymbols.SpellCastGateLaws.CooldownReadinessGate.NameHints,
			typeof(bool),
			Array.Empty<string>());
		_fullCastGate = ResolveExactMethod(
			_battleSpellLogicType,
			GameSymbols.SpellCastGateLaws.FullCastGate.NameHints,
			typeof(bool),
			new[] { "eir" });
		_spellCounterGate = ResolveExactMethod(
			_battleSpellPoolType,
			GameSymbols.SpellCastGateLaws.SpellCounterGate.NameHints,
			typeof(bool),
			new[] { "String", "ESchool" });
		_indexSelectionGate = ResolveExactMethod(
			_battleSpellPoolType,
			GameSymbols.SpellCastGateLaws.SpellIndexSelectionGate.NameHints,
			typeof(bool),
			new[] { "Int32" });

		if (_cooldownReadiness == null)
			return FailResolve("cooldown readiness method was not found by exact name", out failReason);
		if (_fullCastGate == null)
			return FailResolve("full cast gate method was not found by exact name", out failReason);
		if (_spellCounterGate == null)
			return FailResolve("spell counter gate method was not found by exact name", out failReason);
		if (_indexSelectionGate == null)
			return FailResolve("index selection gate method was not found by exact name", out failReason);

		failReason = null;
		return true;
	}

	private static bool ValidateBattleSpell(object battleSpell, out string failReason)
	{
		if (battleSpell == null)
		{
			failReason = "battle spell instance is null";
			return false;
		}
		if (!_battleSpellLogicType.IsInstanceOfType(battleSpell))
		{
			failReason = "object is not a resolved battle spell logic instance";
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool ValidateSpellPool(object battleSpellPool, out string failReason)
	{
		if (battleSpellPool == null)
		{
			failReason = "battle spell pool instance is null";
			return false;
		}
		if (!_battleSpellPoolType.IsInstanceOfType(battleSpellPool))
		{
			failReason = "object is not a resolved battle spell pool instance";
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool FailResolve(string reason, out string failReason)
	{
		_resolveFailure = reason;
		failReason = reason;
		return false;
	}

	private static MethodInfo ResolveExactMethod(Type type, string[] names, Type requiredReturnType, string[] parameterTypeNames)
	{
		if (type == null)
			return null;

		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in methods)
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (method.IsSpecialName)
					continue;
				if (requiredReturnType != null && method.ReturnType != requiredReturnType)
					continue;
				if (!ParametersMatch(method, parameterTypeNames))
					continue;
				return method;
			}
		}

		return null;
	}

	private static bool ParametersMatch(MethodInfo method, string[] parameterTypeNames)
	{
		var parameters = method.GetParameters();
		parameterTypeNames ??= Array.Empty<string>();
		if (parameters.Length != parameterTypeNames.Length)
			return false;
		for (var i = 0; i < parameters.Length; i++)
		{
			var expected = parameterTypeNames[i];
			if (string.IsNullOrWhiteSpace(expected))
				continue;
			var actual = parameters[i].ParameterType;
			var actualName = actual.Name;
			var actualFullName = actual.FullName ?? actualName;
			var actualObfuscatedName = GameMember.ReadObfuscatedName(actual);
			if (!string.Equals(actualName, expected, StringComparison.Ordinal)
			    && !string.Equals(actualFullName, expected, StringComparison.Ordinal)
			    && !actualFullName.EndsWith("." + expected, StringComparison.Ordinal)
			    && !string.Equals(actualObfuscatedName, expected, StringComparison.Ordinal))
				return false;
		}
		return true;
	}

	private static string DescribeType(Type type)
	{
		return type?.FullName ?? "unresolved";
	}

	private static string DescribeMethod(MethodBase method)
	{
		if (method == null)
			return "unresolved";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
