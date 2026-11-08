using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise reward/capture economy laws.
/// This traces exact reward-set queue/remove/apply surfaces so later laws can
/// distinguish committed object rewards from generic resource mutations.
/// </summary>
internal static class Homm3RewardCommitLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_reward_commit_law_diag.flag";

	private const int LogCap = 120;
	private const int MaxRewardItems = 5;
	private static bool _registered;
	private static int _logged;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";

	internal static string RegistrationAuditStatus => _registrationAuditStatus;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
		{
			_registrationAuditStatus = "DIAGNOSTIC_FLAG_NOT_ENABLED";
			return;
		}
		_registered = true;

		var patched = 0;
		try
		{
			patched += PatchRewardApply(harmony, log);
			patched += PatchRewardSetList(harmony, log);
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 reward commit law diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			_registrationAuditStatus = "FAILED_CLOSED: no exact startup hook surfaces patched";
			log?.LogWarning("HoMM3 reward commit law diagnostics found no exact reward surfaces; reward/capture economy law gameplay remains disabled.");
			return;
		}

		_registrationAuditStatus = "DIAGNOSTIC_HOOK_REGISTERED: exact trace patches=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
		log?.LogInfo("HoMM3 reward commit law diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 reward commit law diagnostics: traces are observational only; do not grant reward/capture law resources until runtime proof confirms commit ordering, idempotence, and source identity.");
		log?.LogInfo("HoMM3 reward commit law diagnostics: active-law state is attempted only through the shared exact resolver; none-or-unresolved is not negative gameplay evidence.");
	}

	private static int PatchRewardApply(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.RewardCommitLawsRewardApplier);
		if (type == null)
		{
			log?.LogWarning("HoMM3 reward commit law diagnostics: exact czy reward applier type not found.");
			return 0;
		}

		var patched = 0;
		for (var i = 0; i < GameSymbols.RewardCommitLaws.RewardSetApply.NameHints.Length; i++)
		{
			patched += PatchExactVoidMethod(
				harmony,
				log,
				type,
				GameSymbols.RewardCommitLaws.RewardSetApply.NameHints[i],
				new[] { "Hero", "DataRewardSet" },
				nameof(PostfixRewardSetApply),
				"reward-set-apply");
		}

		return patched;
	}

	private static int PatchRewardSetList(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.RewardCommitLawsDataRewardSets);
		if (type == null)
		{
			log?.LogWarning("HoMM3 reward commit law diagnostics: exact DataRewardSets type not found.");
			return 0;
		}

		var patched = 0;
		for (var i = 0; i < GameSymbols.RewardCommitLaws.RewardSetQueued.NameHints.Length; i++)
			patched += PatchExactVoidMethod(
				harmony,
				log,
				type,
				GameSymbols.RewardCommitLaws.RewardSetQueued.NameHints[i],
				new[] { "DataRewardSet" },
				nameof(PrefixRewardSetQueued),
				"reward-set-queued");
		for (var i = 0; i < GameSymbols.RewardCommitLaws.RewardSetRemoved.NameHints.Length; i++)
			patched += PatchExactVoidMethod(
				harmony,
				log,
				type,
				GameSymbols.RewardCommitLaws.RewardSetRemoved.NameHints[i],
				new[] { "DataRewardSet" },
				nameof(PrefixRewardSetRemoved),
				"reward-set-removed");
		if (patched == 0)
			log?.LogWarning("HoMM3 reward commit law diagnostics: exact DataRewardSets queue/remove methods were not found; refusing broad one-DataRewardSet fallback.");
		return patched;
	}

	private static int PatchExactVoidMethod(
		Harmony harmony,
		ManualLogSource log,
		Type type,
		string methodName,
		string[] expectedParameterTypeNames,
		string patchName,
		string stage)
	{
		var method = ResolveExactVoidMethod(type, methodName, expectedParameterTypeNames);
		if (method == null)
		{
			log?.LogWarning("HoMM3 reward commit law diagnostics: exact void " + type.FullName + "." + methodName + "(" + string.Join(",", expectedParameterTypeNames ?? Array.Empty<string>()) + ") not found for " + stage + ".");
			return 0;
		}

		var patch = AccessTools.Method(typeof(Homm3RewardCommitLawDiagnostics), patchName);
		if (patch == null)
		{
			log?.LogWarning("HoMM3 reward commit law diagnostics: patch " + patchName + " not found.");
			return 0;
		}

		if (!GameMember.IsHarmonyPatchCompatible(method, patch, out var reason))
		{
			log?.LogWarning("HoMM3 reward commit law diagnostics: refusing incompatible patch for " + FormatMethod(method) + ": " + reason);
			return 0;
		}

		var harmonyMethod = new HarmonyMethod(patch) { priority = Priority.Last };
		if (patchName.StartsWith("Prefix", StringComparison.Ordinal))
			harmony.Patch(method, prefix: harmonyMethod);
		else
			harmony.Patch(method, postfix: harmonyMethod);
		return 1;
	}

	private static MethodInfo ResolveExactVoidMethod(Type type, string name, string[] expectedParameterTypeNames)
	{
		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var method in methods)
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (method.IsSpecialName)
				continue;
			if (method.ReturnType != typeof(void))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != expectedParameterTypeNames.Length)
				continue;
			var parameterTypesMatch = true;
			for (var i = 0; i < parameters.Length; i++)
			{
				var parameterTypeName = parameters[i].ParameterType.Name;
				var parameterFullName = parameters[i].ParameterType.FullName ?? parameterTypeName;
				if (!string.Equals(parameterTypeName, expectedParameterTypeNames[i], StringComparison.Ordinal)
				    && !parameterFullName.EndsWith("." + expectedParameterTypeNames[i], StringComparison.Ordinal))
				{
					parameterTypesMatch = false;
					break;
				}
			}
			if (!parameterTypesMatch)
				continue;
			return method;
		}

		return null;
	}

	private static void PostfixRewardSetApply(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("reward-set-apply", __instance, __originalMethod, __args);
	}

	private static void PrefixRewardSetQueued(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("reward-set-queued", __instance, __originalMethod, __args);
	}

	private static void PrefixRewardSetRemoved(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("reward-set-removed", __instance, __originalMethod, __args);
	}

	private static void LogTrace(string stage, object instance, MethodBase method, object[] args)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;

			var rewardSet = args != null && args.Length > 0 ? args[args.Length - 1] : null;
			Plugin.LogSource?.LogInfo(
				"HoMM3 reward commit law diagnostic: "
				+ stage
				+ " method="
				+ FormatMethod(method)
				+ " instance="
				+ DescribeObjectContext(instance)
				+ " args="
				+ DescribeArgs(args)
				+ " rewardSet="
				+ DescribeRewardSet(rewardSet)
				+ " handlerGate="
				+ Homm3CustomLawHandlerTrace.Describe(
					rewardSet ?? instance,
					Homm3CustomLawHandlerTrace.RewardGoldEconomy,
					Homm3CustomLawHandlerTrace.RewardCalendar)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 reward commit law diagnostic log failed: " + ex.Message);
		}
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static string DescribeArgs(object[] args)
	{
		if (args == null || args.Length == 0)
			return "[]";

		var parts = new string[args.Length];
		for (var i = 0; i < args.Length; i++)
			parts[i] = DescribeObjectContext(args[i]);
		return "[" + string.Join(",", parts) + "]";
	}

	private static string DescribeRewardSet(object rewardSet)
	{
		if (rewardSet == null)
			return "null";

		var type = rewardSet.GetType();
		var parts = new List<string>
		{
			"type=" + (type.FullName ?? type.Name)
		};

		AddNamedValue(rewardSet, type, parts, "id");
		AddNamedValue(rewardSet, type, parts, "heroId");
		AddNamedValue(rewardSet, type, parts, "objectId");
		AddNamedValue(rewardSet, type, parts, "label");
		AddNamedValue(rewardSet, type, parts, "showType");
		AddNamedValue(rewardSet, type, parts, "applyType");
		AddNamedValue(rewardSet, type, parts, "cancelType");
		parts.Add("activeKnownCustomLawsFromThisObject=" + DescribeActiveKnownCustomLaws(rewardSet));
		AddRewardItems(rewardSet, type, parts);

		return "{" + string.Join("|", parts) + "}";
	}

	private static string DescribeActiveKnownCustomLaws(object owner)
	{
		if (owner == null)
			return "null";

		var lawParts = new List<string>(8);
		foreach (var lawIndex in Homm3CustomFactionLawRuntime.KnownRuntimeLawIndices)
		{
			if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(owner, lawIndex, out var state))
				continue;
			lawParts.Add("index=" + state.Index
			             + ",rank=" + state.Rank
			             + ",faction=" + state.FactionSid
			             + ",family=" + state.Family);
			if (lawParts.Count >= 8)
				break;
		}

		return lawParts.Count == 0 ? "none-or-unresolved" : "[" + string.Join(";", lawParts) + "]";
	}

	private static void AddRewardItems(object rewardSet, Type type, List<string> parts)
	{
		if (!TryGetMemberValue(rewardSet, type, "rewards", out var rewards) || rewards == null)
		{
			parts.Add("rewards=(absent)");
			return;
		}

		if (rewards is string || !(rewards is IEnumerable enumerable))
		{
			parts.Add("rewards=" + SafeFormatValue(rewards));
			return;
		}

		var items = new List<string>();
		var count = 0;
		foreach (var item in enumerable)
		{
			count++;
			if (items.Count < MaxRewardItems)
				items.Add(DescribeRewardItem(item));
		}

		parts.Add("rewardCount=" + count);
		parts.Add("rewardItems=[" + string.Join(";", items) + "]");
	}

	private static string DescribeRewardItem(object reward)
	{
		if (reward == null)
			return "null";

		var type = reward.GetType();
		var parts = new List<string>
		{
			"type=" + (type.FullName ?? type.Name)
		};

		AddNamedValue(reward, type, parts, "stringRewardType");
		AddNamedValue(reward, type, parts, "rewardType");
		AddNamedValue(reward, type, parts, "rewardName");
		AddNamedValue(reward, type, parts, "rewardDesc");
		AddNamedValue(reward, type, parts, "rewardIcon");
		AddNamedValue(reward, type, parts, "parameters");
		return "{" + string.Join(",", parts) + "}";
	}

	private static string DescribeObjectContext(object value)
	{
		if (value == null)
			return "null";

		var type = value.GetType();
		var parts = new List<string>
		{
			"type=" + (type.FullName ?? type.Name)
		};

		var obfuscated = GameMember.ReadObfuscatedName(type);
		if (!string.IsNullOrEmpty(obfuscated))
			parts.Add("obf=" + obfuscated);
		AddNamedValue(value, type, parts, "id");
		AddNamedValue(value, type, parts, "sid");
		AddNamedValue(value, type, parts, "heroId");
		AddNamedValue(value, type, parts, "objectId");
		parts.Add("activeKnownCustomLawsFromThisObject=" + DescribeActiveKnownCustomLaws(value));
		return "{" + string.Join("|", parts) + "}";
	}

	private static void AddNamedValue(object instance, Type type, List<string> parts, string name)
	{
		if (!TryGetMemberValue(instance, type, name, out var value))
			return;
		parts.Add(name + "=" + SafeFormatValue(value));
	}

	private static string SafeFormatValue(object value)
	{
		if (value == null)
			return "null";

		try
		{
			if (value is string text)
				return Limit(text);
			if (value is IEnumerable enumerable && !(value is string))
			{
				var count = 0;
				foreach (var ignored in enumerable)
					count++;
				return "IEnumerable(count=" + count + ")";
			}

			var type = value.GetType();
			if (type.IsPrimitive || type.IsEnum || value is decimal || value is IntPtr || value is UIntPtr)
				return Limit(Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture));
			return "type=" + (type.FullName ?? type.Name);
		}
		catch
		{
			return "(err)";
		}
	}

	private static string Limit(string text)
	{
		if (string.IsNullOrEmpty(text))
			return "(empty)";
		return text.Length <= 96 ? text : text.Substring(0, 96) + "...";
	}

	private static bool TryGetMemberValue(object instance, Type type, string name, out object value)
	{
		value = null;
		if (instance == null || type == null || string.IsNullOrEmpty(name))
			return false;

		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			try
			{
				var field = current.GetField(name, flags | BindingFlags.DeclaredOnly);
				if (field != null)
				{
					value = field.GetValue(instance);
					return true;
				}
			}
			catch
			{
				// Exact diagnostic read only; absence/failure means no value.
			}

			try
			{
				var prop = current.GetProperty(name, flags | BindingFlags.DeclaredOnly);
				if (prop != null && prop.GetIndexParameters().Length == 0)
				{
					value = prop.GetValue(instance);
					return true;
				}
			}
			catch
			{
				// Exact diagnostic read only; absence/failure means no value.
			}
		}

		return false;
	}
}
