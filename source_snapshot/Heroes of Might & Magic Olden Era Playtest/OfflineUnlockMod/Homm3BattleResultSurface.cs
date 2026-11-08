using System;
using System.Collections.Generic;
using System.Reflection;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

internal static class Homm3BattleResultSurface
{
	internal static bool HasBattleResultAlreadyAppliedSurface(MethodInfo applyBattleResultMethod)
	{
		if (applyBattleResultMethod == null)
			return false;
		var parameters = applyBattleResultMethod.GetParameters();
		return parameters.Length > 0 && FindAlreadyAppliedMember(parameters[0].ParameterType) != null;
	}

	internal static bool TryReadBattleResultAlreadyApplied(object battleLogic, out bool alreadyApplied)
	{
		alreadyApplied = false;
		if (battleLogic == null)
			return false;
		var type = battleLogic.GetType();
		var member = FindAlreadyAppliedMember(type);
		if (member is PropertyInfo property)
		{
			try
			{
				alreadyApplied = (bool)property.GetValue(battleLogic, null);
				return true;
			}
			catch
			{
				return false;
			}
		}
		if (member is FieldInfo field)
		{
			try
			{
				alreadyApplied = (bool)field.GetValue(battleLogic);
				return true;
			}
			catch
			{
				return false;
			}
		}
		if (member is MethodInfo method)
		{
			try
			{
				alreadyApplied = (bool)method.Invoke(battleLogic, Array.Empty<object>());
				return true;
			}
			catch
			{
				return false;
			}
		}
		return false;
	}

	private static MemberInfo FindAlreadyAppliedMember(Type type)
	{
		if (type == null)
			return null;
		foreach (var name in GameSymbols.BattleResultLaws.BattleLogicAlreadyAppliedFields)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var property = type.GetProperty(
				name,
				BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (property != null
			    && property.PropertyType == typeof(bool)
			    && property.GetIndexParameters().Length == 0)
				return property;
			var field = type.GetField(
				name,
				BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (field != null && field.FieldType == typeof(bool))
				return field;
			var method = type.GetMethod(
				name,
				BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance,
				null,
				Type.EmptyTypes,
				null);
			if (method != null && method.ReturnType == typeof(bool))
				return method;
		}
		return null;
	}

	internal static MethodInfo ResolveApplyBattleResultMethod()
	{
		var assembly = typeof(TransferSide).Assembly;
		var logicType = ResolveTypeByNames(assembly, GameSymbols.BattleResultLaws.BattleLogicTypeHints);
		if (logicType == null)
			return null;

		foreach (var managerType in ResolveTypesByNames(assembly, GameSymbols.BattleResultLaws.BattlesManagerTypeHints))
		{
			foreach (var name in GameSymbols.BattleResultLaws.ApplyBattleResult.NameHints)
			{
				var method = managerType.GetMethod(
					name,
					BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				if (method == null || method.ReturnType != typeof(void))
					continue;
				var parameters = method.GetParameters();
				if ((parameters.Length == 1 || parameters.Length == 2)
				    && parameters[0].ParameterType == logicType
				    && (parameters.Length == 1 || parameters[1].ParameterType == typeof(bool)))
					return method;
			}
		}

		return null;
	}

	private static Type ResolveTypeByNames(Assembly assembly, IEnumerable<string> names)
	{
		if (assembly == null || names == null)
			return null;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = assembly.GetType(name, throwOnError: false)
			           ?? GameMember.FindType("battle.resultSurface.type." + name, name);
			if (type != null && type.Assembly == assembly)
				return type;
		}
		return null;
	}

	private static IEnumerable<Type> ResolveTypesByNames(Assembly assembly, IEnumerable<string> names)
	{
		if (assembly == null || names == null)
			yield break;
		var emitted = new HashSet<Type>();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = assembly.GetType(name, throwOnError: false)
			           ?? GameMember.FindType("battle.resultSurface.type." + name, name);
			if (type != null && type.Assembly == assembly && emitted.Add(type))
				yield return type;
		}
	}
}
