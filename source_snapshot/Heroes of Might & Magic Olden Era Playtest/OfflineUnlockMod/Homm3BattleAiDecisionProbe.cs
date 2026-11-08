using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Flag-gated read-only Harmony probe for the battle AI action picker (<c>dyt.bavi</c> family).
/// Observes chosen <see cref="GameSymbols.BattleAiDecision"/> picks only — no re-rank, no
/// score mutation, no execution interception.
/// Enable with <c>homm3_battle_ai_decision_probe.flag</c>.
/// Evidence: docs/ai_decision_logic_surface.md (source/static; runtime-unvalidated until live picks log).
/// </summary>
internal static class Homm3BattleAiDecisionProbe
{
	internal const string DiagnosticFlag = "homm3_battle_ai_decision_probe.flag";

	private const int LogCap = 200;
	private static bool _registered;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";
	private static ManualLogSource _log;
	private static int _logged;
	private static int _observed;
	private static int _patched;

	internal static string RegistrationAuditStatus => _registrationAuditStatus;
	internal static int PatchedCount => _patched;
	internal static int ObservedCount => _observed;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
		{
			_registrationAuditStatus = "SKIPPED: flag absent (" + DiagnosticFlag + ")";
			return;
		}

		_log = log;
		try
		{
			var actionType = ResolveNamedType(GameSymbols.BattleAiDecision.ActionTypeId, GameSymbols.BattleAiDecision.ActionTypeHints);
			var unitType = ResolveNamedType(GameSymbols.BattleAiDecision.UnitTypeId, GameSymbols.BattleAiDecision.UnitTypeHints);
			if (actionType == null || unitType == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: BattleAiAction/Unit types unresolved";
				log?.LogWarning("HoMM3 battle AI decision probe failed closed: BattleAiAction or Unit type missing.");
				return;
			}

			var brain = ResolveBrainType(actionType, unitType);
			if (brain == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: battle AI brain type unresolved";
				log?.LogWarning("HoMM3 battle AI decision probe failed closed: brain type not found (expected dyt or unique signature owner).");
				return;
			}

			var pickers = ResolvePickerMethods(brain, actionType, unitType);
			if (pickers.Count == 0)
			{
				_registrationAuditStatus = "FAILED_CLOSED: picker signature unresolved on " + brain.FullName;
				log?.LogWarning("HoMM3 battle AI decision probe failed closed: no hinted picker matching (Unit, List<Unit>, List<Unit>, List<BattleAiAction>) → BattleAiAction on " + brain.FullName + ".");
				return;
			}

			var postfix = AccessTools.Method(typeof(Homm3BattleAiDecisionProbe), nameof(PostfixPickAction));
			if (postfix == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: postfix missing";
				return;
			}

			var patched = 0;
			foreach (var method in pickers)
			{
				if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
				{
					log?.LogWarning("HoMM3 battle AI decision probe refused incompatible postfix for " + FormatMethod(method) + ": " + reason);
					continue;
				}
				harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
				patched++;
				log?.LogInfo("HoMM3 battle AI decision probe patched picker " + FormatMethod(method) + ".");
			}

			_patched = patched;
			if (patched == 0)
			{
				_registrationAuditStatus = "FAILED_CLOSED: zero compatible picker patches";
				log?.LogWarning("HoMM3 battle AI decision probe failed closed: Harmony refused all picker candidates.");
				return;
			}

			_registered = true;
			_registrationAuditStatus = "RUNTIME_HOOK_REGISTERED: pickerPatches=" + patched.ToString(CultureInfo.InvariantCulture)
				+ " brain=" + (brain.FullName ?? brain.Name);
			log?.LogInfo("HoMM3 battle AI decision probe registered " + patched + " read-only picker postfix(es). Observation only.");
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 battle AI decision probe failed closed during registration: " + ex.Message);
		}
	}

	private static Type ResolveBrainType(Type actionType, Type unitType)
	{
		foreach (var hint in GameSymbols.BattleAiDecision.BrainTypeHints)
		{
			var type = GameMember.FindType(GameSymbols.BattleAiDecision.BrainTypeId + "." + hint, hint)
				?? AccessTools.TypeByName(hint);
			if (type == null)
				continue;
			if (CollectSignatureMatches(type, actionType, unitType).Count == 0)
				continue;
			return type;
		}

		// Interop may rename dyt → ObjectPublic*. Require a unique signature owner.
		Type unique = null;
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try { types = assembly.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types ?? Array.Empty<Type>(); }
			catch { continue; }

			foreach (var type in types)
			{
				if (type == null || !type.IsClass)
					continue;
				if (CollectSignatureMatches(type, actionType, unitType).Count == 0)
					continue;
				if (unique != null && unique != type)
				{
					_log?.LogWarning(
						"HoMM3 battle AI decision probe: ambiguous brain signature owners "
						+ unique.FullName + " and " + type.FullName + "; refusing silent pick.");
					return null;
				}
				unique = type;
			}
		}
		return unique;
	}

	private static Type ResolveNamedType(string typeId, string[] hints)
	{
		if (hints == null)
			return null;
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var type = GameMember.FindType(typeId + "." + hint, hint) ?? AccessTools.TypeByName(hint);
			if (type != null)
				return type;
		}
		return null;
	}

	private static List<MethodInfo> CollectSignatureMatches(Type brain, Type actionType, Type unitType)
	{
		var matches = new List<MethodInfo>();
		if (brain == null || actionType == null || unitType == null)
			return matches;

		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
		MethodInfo[] declared;
		try { declared = brain.GetMethods(flags); }
		catch { return matches; }

		foreach (var method in declared)
		{
			if (!GameMember.TypesEquivalent(actionType, method.ReturnType))
				continue;
			ParameterInfo[] ps;
			try { ps = method.GetParameters(); }
			catch { continue; }
			if (ps.Length != 4)
				continue;
			if (!GameMember.TypesEquivalent(unitType, ps[0].ParameterType))
				continue;
			if (!IsListOf(ps[1].ParameterType, unitType))
				continue;
			if (!IsListOf(ps[2].ParameterType, unitType))
				continue;
			if (!IsListOf(ps[3].ParameterType, actionType))
				continue;
			matches.Add(method);
		}
		return matches;
	}

	private static List<MethodInfo> ResolvePickerMethods(Type brain, Type actionType, Type unitType)
	{
		var matches = CollectSignatureMatches(brain, actionType, unitType);
		var hintSet = new HashSet<string>(
			GameSymbols.BattleAiDecision.PickAction.NameHints ?? Array.Empty<string>(),
			StringComparer.Ordinal);

		matches.Sort((a, b) =>
		{
			var ha = hintSet.Contains(a.Name) || LooksLikeInteropPickerName(a.Name) ? 0 : 1;
			var hb = hintSet.Contains(b.Name) || LooksLikeInteropPickerName(b.Name) ? 0 : 1;
			if (ha != hb)
				return ha.CompareTo(hb);
			return string.CompareOrdinal(a.Name, b.Name);
		});

		// Fail closed unless the method name is a known hint or interop picker token.
		var hinted = matches.FindAll(m => hintSet.Contains(m.Name) || LooksLikeInteropPickerName(m.Name));
		if (hinted.Count > 0)
			return hinted;

		if (matches.Count > 0)
		{
			_log?.LogWarning(
				"HoMM3 battle AI decision probe: " + matches.Count
				+ " unhinted picker signature match(es) on " + (brain.FullName ?? brain.Name)
				+ "; refusing silent patch without PickAction name hints.");
		}
		return new List<MethodInfo>();
	}

	private static bool LooksLikeInteropPickerName(string name)
	{
		if (string.IsNullOrEmpty(name))
			return false;
		return name.IndexOf("BattleAiAction_Unit_List_1_Unit_List_1_Unit_List_1_BattleAiAction", StringComparison.Ordinal) >= 0;
	}

	private static bool IsListOf(Type type, Type elementType)
	{
		if (type == null || elementType == null || !type.IsGenericType)
			return false;
		if (type.Name == null || type.Name.IndexOf("List`1", StringComparison.Ordinal) < 0)
			return false;
		Type[] args;
		try { args = type.GetGenericArguments(); }
		catch { return false; }
		return args.Length == 1 && GameMember.TypesEquivalent(elementType, args[0]);
	}

	private static void PostfixPickAction(object __instance, MethodBase __originalMethod, object __result, object[] __args)
	{
		try
		{
			_observed++;
			if (_logged >= LogCap)
				return;
			_logged++;

			var sb = new StringBuilder(256);
			sb.Append("HoMM3 battle AI decision probe pick method=")
				.Append(__originalMethod?.Name ?? "?")
				.Append(" observed=")
				.Append(_observed.ToString(CultureInfo.InvariantCulture));
			AppendActionSummary(sb, __result);
			if (__args != null && __args.Length > 0 && __args[0] != null)
				sb.Append(" casterType=").Append(__args[0].GetType().Name);
			if (__args != null && __args.Length > 3)
				sb.Append(" candidates=").Append(DescribeCollectionCount(__args[3]));

			(_log ?? Plugin.LogSource)?.LogInfo(sb.ToString());
		}
		catch (Exception ex)
		{
			(_log ?? Plugin.LogSource)?.LogWarning("HoMM3 battle AI decision probe postfix failed: " + ex.Message);
		}
	}

	private static void AppendActionSummary(StringBuilder sb, object action)
	{
		if (action == null)
		{
			sb.Append(" result=null");
			return;
		}

		sb.Append(" resultType=").Append(action.GetType().Name);
		TryAppendField(sb, action, GameSymbols.BattleAiDecision.ActionTypeFieldHints, "actionType");
		TryAppendField(sb, action, GameSymbols.BattleAiDecision.ActionValueFieldHints, "value");
		TryAppendField(sb, action, GameSymbols.BattleAiDecision.ActionHexAttackFieldHints, "hexToAttack");
		TryAppendField(sb, action, GameSymbols.BattleAiDecision.ActionHexRunFieldHints, "hexToRun");
		TryAppendField(sb, action, GameSymbols.BattleAiDecision.ActionAbilityFieldHints, "ability");
	}

	private static void TryAppendField(StringBuilder sb, object obj, string[] fieldHints, string label)
	{
		if (obj == null || fieldHints == null)
			return;
		var type = obj.GetType();
		for (var i = 0; i < fieldHints.Length; i++)
		{
			var hint = fieldHints[i];
			if (string.IsNullOrWhiteSpace(hint) || hint.StartsWith("NativeFieldInfoPtr_", StringComparison.Ordinal))
				continue;
			FieldInfo field = null;
			try { field = type.GetField(hint, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance); }
			catch { }
			if (field == null)
				continue;
			object value;
			try { value = field.GetValue(obj); }
			catch { continue; }
			sb.Append(' ').Append(label).Append('=').Append(DescribeValue(value));
			return;
		}
	}

	private static string DescribeValue(object value)
	{
		if (value == null)
			return "null";
		if (value is Enum)
			return value.ToString();
		var type = value.GetType();
		if (type.IsPrimitive || value is string)
			return Convert.ToString(value, CultureInfo.InvariantCulture) ?? type.Name;
		return type.Name;
	}

	private static string DescribeCollectionCount(object collection)
	{
		if (collection == null)
			return "null";
		if (collection is ICollection c)
			return c.Count.ToString(CultureInfo.InvariantCulture);
		var prop = collection.GetType().GetProperty("Count", BindingFlags.Public | BindingFlags.Instance);
		if (prop != null)
		{
			try
			{
				var count = prop.GetValue(collection);
				return Convert.ToString(count, CultureInfo.InvariantCulture) ?? "?";
			}
			catch { }
		}
		return collection.GetType().Name;
	}

	private static string FormatMethod(MethodInfo method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
