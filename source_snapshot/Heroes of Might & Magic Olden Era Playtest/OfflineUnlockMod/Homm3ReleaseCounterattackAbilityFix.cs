using System;
using System.Collections;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

internal static class Homm3ReleaseCounterattackAbilityFix
{
	private static bool _patched;
	private static ManualLogSource _log;
	private static int _logged;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_patched || harmony == null)
			return;

		_log = log;
		var patched = 0;
		var initMethods = FindManagerInitMethods();
		if (initMethods.Length > 0)
		{
			foreach (var method in initMethods)
			{
				harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm3ReleaseCounterattackAbilityFix), nameof(PostfixManagerInit)));
				patched++;
			}
		}
		else
		{
			log?.LogWarning("Homm3 release counterattack fix: dxr init aliases not found.");
		}

		if (patched > 0)
			log?.LogInfo("Homm3 release counterattack fix: registered " + patched + " ability manager patch(es).");
		_patched = true;
	}

	private static MethodInfo[] FindManagerInitMethods()
	{
		var managerType = FindRuntimeType(GameSymbols.BattleCommand.AbilityManagerTypeNames);
		var unitType = FindRuntimeType(GameSymbols.BattleCommand.RuntimeUnitTypeNames);
		if (managerType == null || unitType == null)
			return Array.Empty<MethodInfo>();
		return GameMember.FindMethodsByNames(
			managerType,
			new[] { unitType },
			GameSymbols.BattleCommand.AbilityManagerInit);
	}

	private static Type FindRuntimeType(string[] typeNames)
	{
		if (typeNames == null)
			return null;
		var asm = typeof(Unit).Assembly;
		foreach (var typeName in typeNames)
		{
			if (string.IsNullOrWhiteSpace(typeName))
				continue;
			try
			{
				var type = asm.GetType(typeName, throwOnError: false) ?? ModActions.GetHexType(typeName);
				if (type != null)
					return type;
			}
			catch
			{
			}
		}
		return null;
	}

	private static void PostfixManagerInit(object __instance, object __0)
	{
		try
		{
			if (__instance == null || __0 == null)
				return;
			var sid = ExtractSid(__0);
			if (!IsStrongholdUnitSid(sid))
				return;

			var normalized = 0;
			normalized += NormalizeBucket(__instance, EAbilityType.DefaultAttack, sid);
			normalized += NormalizeBucket(__instance, EAbilityType.AlternativeAttack, sid);
			if (normalized > 0 && _logged < 20)
			{
				_logged++;
				_log?.LogInfo("Homm3 release counterattack fix: normalized " + normalized + " melee counter recognition item(s) for sid='" + sid + "'.");
			}
		}
		catch (Exception ex)
		{
			if (_logged < 8)
			{
				_logged++;
				_log?.LogWarning("Homm3 release counterattack fix failed: " + ex.GetType().Name + ": " + ex.Message);
			}
		}
	}

	private static int NormalizeBucket(object manager, EAbilityType type, string sid)
	{
		var values = InvokeBucket(manager, type);
		if (values == null)
			return 0;

		var normalized = 0;
		foreach (var value in values)
		{
			if (NormalizeAbility(value, type, sid))
				normalized++;
		}
		return normalized;
	}

	private static int NormalizeRuntimeUnitAttackTags(object caster, object manager)
	{
		if (caster == null || manager == null)
			return 0;
		var addMelee = BucketHasMeleeAttack(manager, EAbilityType.DefaultAttack)
		               || BucketHasMeleeAttack(manager, EAbilityType.AlternativeAttack);
		if (!addMelee)
			return 0;
		return AddRuntimeTag(caster, "melee_attack") ? 1 : 0;
	}

	private static bool BucketHasMeleeAttack(object manager, EAbilityType type)
	{
		var values = InvokeBucket(manager, type);
		if (values == null)
			return false;
		foreach (var value in values)
		{
			if (AbilityIsMeleeAttack(value))
				return true;
		}
		return false;
	}

	private static IEnumerable InvokeBucket(object manager, EAbilityType type)
	{
		var method = GameMember.FindFirstMethodByNames(
			manager.GetType(),
			new[] { typeof(EAbilityType) },
			GameSymbols.BattleCommand.AbilityBucket);
		if (method == null)
			return null;
		return method.Invoke(manager, new object[] { type }) as IEnumerable;
	}

	private static bool NormalizeAbility(object ability, EAbilityType bucket, string sid)
	{
		var logic = TryGetFirstMemberValue(ability, GameSymbols.BattleCommand.AbilityLogicConfigFields) as AbilityLogicConfig;
		var dealer = logic?.damageDealer;
		if (logic == null || dealer == null)
			return false;
		if (!IsMelee(logic))
			return false;
		if (dealer.triggerCounter)
			return false;

		dealer.triggerCounter = true;
		if (_logged < 20)
		{
			_logged++;
			_log?.LogInfo(
				"Homm3 release counterattack fix: set triggerCounter sid='" + sid
				+ "' bucket=" + bucket
				+ " ability=" + DescribeAbility(ability) + ".");
		}
		return true;
	}

	private static bool AbilityIsMeleeAttack(object ability)
	{
		var logic = TryGetFirstMemberValue(ability, GameSymbols.BattleCommand.AbilityLogicConfigFields) as AbilityLogicConfig;
		return logic != null && IsMelee(logic);
	}

	private static bool AddRuntimeTag(object caster, string tag)
	{
		if (caster == null || string.IsNullOrWhiteSpace(tag))
			return false;
		var tags = TryGetFirstMemberValue(caster, GameSymbols.BattleCommand.RuntimeTagListFields);
		if (tags == null || RuntimeTagsContain(tags, tag))
			return false;
		if (tags is Il2CppSystem.Collections.Generic.List<string> typed)
		{
			typed.Add(tag);
			return true;
		}
		try
		{
			var add = AccessTools.Method(tags.GetType(), "Add", new[] { typeof(string) });
			if (add != null)
			{
				add.Invoke(tags, new object[] { tag });
				return true;
			}
		}
		catch { }
		return false;
	}

	private static bool RuntimeTagsContain(object tags, string tag)
	{
		if (tags == null || string.IsNullOrWhiteSpace(tag))
			return false;
		if (tags is Il2CppSystem.Collections.Generic.List<string> typed)
		{
			for (var i = 0; i < typed.Count; i++)
			{
				if (string.Equals(typed[i], tag, StringComparison.OrdinalIgnoreCase))
					return true;
			}
			return false;
		}
		if (tags is IEnumerable enumerable)
		{
			foreach (var value in enumerable)
			{
				if (string.Equals(value?.ToString(), tag, StringComparison.OrdinalIgnoreCase))
					return true;
			}
		}
		return false;
	}

	private static bool IsMelee(AbilityLogicConfig logic)
	{
		var text = ReadStringField(logic, "attackType_");
		if (!string.IsNullOrWhiteSpace(text))
			return string.Equals(text, "melee", StringComparison.OrdinalIgnoreCase);
		try
		{
			foreach (var name in GameSymbols.BattleCommand.AttackTypeMembers)
			{
				var property = AccessTools.Property(logic.GetType(), name);
				var value = property?.GetValue(logic);
				if (string.Equals(value?.ToString(), "Melee", StringComparison.OrdinalIgnoreCase))
					return true;
			}
			return false;
		}
		catch
		{
			return false;
		}
	}

	private static string ReadStringField(object target, string name)
	{
		try
		{
			var field = AccessTools.Field(target.GetType(), name);
			return field?.GetValue(target) as string;
		}
		catch
		{
			return null;
		}
	}

	private static string DescribeAbility(object ability)
	{
		try
		{
			var logic = TryGetFirstMemberValue(ability, GameSymbols.BattleCommand.AbilityLogicConfigFields) as AbilityLogicConfig;
			var view = TryGetFirstMemberValue(ability, GameSymbols.BattleCommand.AbilityViewConfigFields) as AbilityViewConfig;
			return "name=" + (view?.name ?? "?")
			       + ",type=" + (view?.abilityType ?? "?")
			       + ",attack=" + (ReadStringField(logic, "attackType_") ?? "?");
		}
		catch
		{
			return "?";
		}
	}

	private static object TryGetMemberValue(object target, string name)
	{
		if (target == null || string.IsNullOrWhiteSpace(name))
			return null;
		try
		{
			var field = FindField(target.GetType(), name);
			if (field != null)
				return field.GetValue(target);
		}
		catch { }
		try
		{
			var property = FindProperty(target.GetType(), name);
			if (property != null)
				return property.GetValue(target);
		}
		catch { }
		return null;
	}

	private static object TryGetFirstMemberValue(object target, string[] names)
	{
		if (target == null || names == null)
			return null;
		foreach (var name in names)
		{
			var value = TryGetMemberValue(target, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static string ExtractSid(object unit)
	{
		if (unit == null)
			return null;
		foreach (var name in GameSymbols.BattleCommand.UnitSidFields)
		{
			var value = TryGetMemberValue(unit, name) as string;
			if (!string.IsNullOrWhiteSpace(value))
				return value;
		}
		foreach (var nestedName in GameSymbols.BattleCommand.UnitNestedConfigFields)
		{
			var nested = TryGetMemberValue(unit, nestedName);
			foreach (var sidName in GameSymbols.BattleCommand.UnitConfigSidMembers)
			{
				var value = TryGetMemberValue(nested, sidName) as string;
				if (!string.IsNullOrWhiteSpace(value))
					return value;
			}
		}
		foreach (var name in GameSymbols.BattleCommand.UnitConfigSidGetter.NameHints)
		{
			try
			{
				var method = AccessTools.Method(unit.GetType(), name, Type.EmptyTypes);
				var value = method?.Invoke(unit, null) as string;
				if (!string.IsNullOrWhiteSpace(value))
					return value;
			}
			catch { }
		}
		return null;
	}

	private static FieldInfo FindField(Type type, string name)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		for (var current = type; current != null; current = current.BaseType)
		{
			var field = current.GetField(name, flags);
			if (field != null)
				return field;
		}
		return null;
	}

	private static PropertyInfo FindProperty(Type type, string name)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		for (var current = type; current != null; current = current.BaseType)
		{
			var property = current.GetProperty(name, flags);
			if (property != null)
				return property;
		}
		return null;
	}

	private static bool IsStrongholdUnitSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid)
		       && sid.StartsWith("h3_", StringComparison.OrdinalIgnoreCase);
	}
}
