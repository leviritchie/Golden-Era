using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Exact native adapter for battle spell cooldown state.
/// Source-prepared from June 18 decomp/live-bridge evidence. This class is not
/// registered as a Harmony hook and performs no gameplay by itself; future law
/// handlers should use it instead of raw field writes or signature fallbacks.
/// </summary>
internal static class Homm3SpellCooldownNativeAdapter
{
	private static Type _battleSpellLogicType;
	private static Type _battleSpellPoolType;
	private static MethodInfo _effectiveCooldown;
	private static MethodInfo _setCooldown;
	private static MethodInfo _addCooldownIfReady;
	private static MethodInfo _decrementCooldown;
	private static MethodInfo _poolCooldownShift;
	private static bool _resolved;
	private static string _resolveFailure;

	internal static bool TryReadEffectiveCooldown(object battleSpell, out int cooldown, out string failReason)
	{
		cooldown = 0;
		if (!TryResolve(out failReason))
			return false;
		if (battleSpell == null)
		{
			failReason = "battle spell instance is null";
			return false;
		}
		if (_effectiveCooldown == null)
		{
			failReason = "effective cooldown method is unresolved";
			return false;
		}

		try
		{
			var raw = _effectiveCooldown.Invoke(battleSpell, Array.Empty<object>());
			cooldown = Convert.ToInt32(raw, System.Globalization.CultureInfo.InvariantCulture);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "effective cooldown read failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TrySetCooldown(object battleSpell, int cooldown, out string failReason)
	{
		if (!TryResolve(out failReason))
			return false;
		if (battleSpell == null)
		{
			failReason = "battle spell instance is null";
			return false;
		}
		if (_setCooldown == null)
		{
			failReason = "set cooldown method is unresolved; law.spellCooldown.setCooldown has no strict generated-name proof yet";
			return false;
		}

		try
		{
			_setCooldown.Invoke(battleSpell, new object[] { Math.Max(0, cooldown) });
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "set cooldown invoke failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryReduceCooldownBy(object battleSpell, int amount, out string failReason)
	{
		if (amount <= 0)
		{
			failReason = "cooldown reduction amount must be positive";
			return false;
		}
		if (!TryReadEffectiveCooldown(battleSpell, out var current, out failReason))
			return false;
		if (current <= 0)
		{
			failReason = "cooldown is already zero";
			return false;
		}

		var decrements = Math.Min(amount, current);
		for (var i = 0; i < decrements; i++)
		{
			if (!TryDecrementCooldown(battleSpell, out failReason))
				return false;
		}

		failReason = null;
		return true;
	}

	internal static bool TryAddCooldownIfReady(object battleSpell, int cooldown, out string failReason)
	{
		if (!TryResolve(out failReason))
			return false;
		if (battleSpell == null)
		{
			failReason = "battle spell instance is null";
			return false;
		}
		if (_addCooldownIfReady == null)
		{
			failReason = "add cooldown if ready method is unresolved";
			return false;
		}

		try
		{
			_addCooldownIfReady.Invoke(battleSpell, new object[] { Math.Max(0, cooldown) });
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "add cooldown if ready invoke failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryDecrementCooldown(object battleSpell, out string failReason)
	{
		if (!TryResolve(out failReason))
			return false;
		if (battleSpell == null)
		{
			failReason = "battle spell instance is null";
			return false;
		}
		if (_decrementCooldown == null)
		{
			failReason = "decrement cooldown method is unresolved";
			return false;
		}

		try
		{
			_decrementCooldown.Invoke(battleSpell, Array.Empty<object>());
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "decrement cooldown invoke failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryShiftPoolCooldowns(object battleSpellPool, int delta, bool includeReady, out string failReason)
	{
		if (!TryResolve(out failReason))
			return false;
		if (battleSpellPool == null)
		{
			failReason = "battle spell pool instance is null";
			return false;
		}
		if (_poolCooldownShift == null)
		{
			failReason = "pool cooldown shift method is unresolved";
			return false;
		}

		try
		{
			_poolCooldownShift.Invoke(battleSpellPool, new object[] { delta, includeReady });
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "pool cooldown shift invoke failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryReadSpellPoolSpells(object battleSpellPool, out object[] battleSpells, out string failReason)
	{
		battleSpells = null;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateSpellPool(battleSpellPool, out failReason))
			return false;

		var raw = ReadFirstExactMember(
			battleSpellPool,
			battleSpellPool.GetType(),
			GameSymbols.SpellCooldownLaws.BattleSpellPoolSpellArrayMembers,
			GameSymbols.SpellCooldownLaws.BattleSpellPoolSpellArrayAccessorMethods);
		if (raw == null)
		{
			failReason = "battle spell pool did not expose exact spell array";
			return false;
		}

		var spells = new List<object>();
		if (raw is Array array)
		{
			for (var i = 0; i < array.Length; i++)
			{
				var spell = array.GetValue(i);
				if (spell != null)
					spells.Add(spell);
			}
		}
		else if (raw is System.Collections.IEnumerable enumerable && raw is not string)
		{
			foreach (var spell in enumerable)
			{
				if (spell != null)
					spells.Add(spell);
			}
		}
		else
		{
			failReason = "battle spell pool spell member is not enumerable";
			return false;
		}

		if (spells.Count == 0)
		{
			failReason = "battle spell pool exposed no spells";
			return false;
		}

		battleSpells = spells.ToArray();
		failReason = null;
		return true;
	}

	internal static bool TryReadSpellPoolCurrentSpell(object battleSpellPool, out object battleSpell, out string failReason)
	{
		battleSpell = null;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateSpellPool(battleSpellPool, out failReason))
			return false;
		battleSpell = ReadFirstExactMember(
			battleSpellPool,
			battleSpellPool.GetType(),
			GameSymbols.SpellCooldownLaws.BattleSpellPoolCurrentSpellMembers,
			Array.Empty<string>());
		if (battleSpell == null)
		{
			failReason = "battle spell pool did not expose exact current spell";
			return false;
		}
		failReason = null;
		return true;
	}

	internal static bool TryReadSpellPoolCaster(object battleSpellPool, out object caster, out string failReason)
	{
		caster = null;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateSpellPool(battleSpellPool, out failReason))
			return false;
		caster = ReadFirstExactMember(
			battleSpellPool,
			battleSpellPool.GetType(),
			GameSymbols.SpellCooldownLaws.BattleSpellPoolCasterMembers,
			Array.Empty<string>());
		if (caster == null)
		{
			failReason = "battle spell pool did not expose exact caster";
			return false;
		}
		failReason = null;
		return true;
	}

	internal static bool TryReadSpellPoolTransferSide(object battleSpellPool, out object transferSide, out string failReason)
	{
		transferSide = null;
		if (!TryReadSpellPoolCaster(battleSpellPool, out var caster, out failReason))
			return false;
		transferSide = ReadFirstExactMember(
			caster,
			caster.GetType(),
			GameSymbols.SpellCooldownLaws.BattleSpellCasterTransferSideMembers,
			Array.Empty<string>());
		if (transferSide == null)
		{
			failReason = "battle spell pool caster did not expose exact transfer side";
			return false;
		}
		failReason = null;
		return true;
	}

	internal static bool TryReadSpellPoolCooldownLawOwner(object battleSpellPool, out object lawOwner, out string failReason)
	{
		lawOwner = null;
		if (!TryReadSpellPoolTransferSide(battleSpellPool, out var transferSide, out failReason))
			return false;
		lawOwner = ReadFirstExactMember(
			transferSide,
			transferSide.GetType(),
			GameSymbols.SpellCooldownLaws.BattleSpellTransferSideLogicHeroMembers,
			Array.Empty<string>());
		if (lawOwner == null)
		{
			failReason = "battle spell transfer side did not expose exact logic hero law owner";
			return false;
		}
		if (!Homm3CustomLawHandlerRegistry.TryProbeHandler(
			    lawOwner,
			    "spell.cooldown",
			    Homm3CustomFactionLawRuntime.SpellCooldownModifierIndex,
			    out _,
			    out failReason))
		{
			return false;
		}
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

		_effectiveCooldown = ResolveExactMethod(
			_battleSpellLogicType,
			GameSymbols.SpellCooldownLaws.EffectiveCooldown.NameHints,
			typeof(int),
			Array.Empty<string>());
		_decrementCooldown = ResolveExactMethod(
			_battleSpellLogicType,
			GameSymbols.SpellCooldownLaws.DecrementCooldown.NameHints,
			typeof(void),
			Array.Empty<string>());
		_setCooldown = ResolveExactMethod(
			_battleSpellLogicType,
			GameSymbols.SpellCooldownLaws.SetCooldown.NameHints,
			typeof(void),
			new[] { "Int32" });
		_addCooldownIfReady = ResolveExactMethod(
			_battleSpellLogicType,
			GameSymbols.SpellCooldownLaws.AddCooldownIfReady.NameHints,
			typeof(void),
			new[] { "Int32" });
		_poolCooldownShift = ResolveExactMethod(
			_battleSpellPoolType,
			GameSymbols.SpellCooldownLaws.SpellPoolCooldownShift.NameHints,
			typeof(void),
			new[] { "Int32", "Boolean" });

		if (_effectiveCooldown == null)
			return FailResolve("effective cooldown method was not found by exact name", out failReason);
		if (_decrementCooldown == null)
			return FailResolve("decrement cooldown method was not found by exact name", out failReason);
		if (_addCooldownIfReady == null)
			return FailResolve("add cooldown if ready method was not found by exact name", out failReason);
		if (_poolCooldownShift == null)
			return FailResolve("pool cooldown shift method was not found by exact name", out failReason);

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
		if (_battleSpellPoolType == null)
		{
			failReason = "battle spell pool type is unresolved";
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

	private static object ReadFirstExactMember(object value, Type type, string[] fields, string[] methods)
	{
		if (value == null || type == null)
			return null;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			foreach (var fieldName in fields ?? Array.Empty<string>())
			{
				if (string.IsNullOrWhiteSpace(fieldName))
					continue;
				try
				{
					var field = current.GetField(fieldName, flags);
					if (field != null)
						return field.GetValue(value);
				}
				catch
				{
				}
				try
				{
					var property = current.GetProperty(fieldName, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
						return property.GetValue(value, null);
				}
				catch
				{
				}
			}
			foreach (var methodName in methods ?? Array.Empty<string>())
			{
				if (string.IsNullOrWhiteSpace(methodName))
					continue;
				try
				{
					var method = current.GetMethod(methodName, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
						return method.Invoke(value, null);
				}
				catch
				{
				}
			}
		}
		return null;
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
}
