using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only packet bridge for counterattack laws.
/// This correlates the native battle attack command, ability resolution,
/// attack resolver, and committed damage event dispatch in one thread-local
/// trace. It does not alter attacks, counters, damage, events, or law state.
/// </summary>
internal static class Homm3CounterattackCorrelationLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_counterattack_correlation_law_diag.flag";

	private const int LogCap = 160;
	private const int MaxMemberSnapshots = 12;
	private static bool _registered;
	private static int _logged;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";

	internal static string RegistrationAuditStatus => _registrationAuditStatus;
	private static int _sequence;

	[ThreadStatic]
	private static CommandContext _currentCommand;

	[ThreadStatic]
	private static ResolverContext _currentResolver;

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
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: ability-resolve tracing is disabled after June 18 combat-entry softlock evidence. Do not re-enable without a narrower decomp-backed hook or live bridge proof.");
			patched += PatchBattleAttackCommand(harmony, log);
			patched += PatchAbilityChangeListeners(harmony, log);
			patched += PatchAbilityRuntimeChangeEvents(harmony, log);
			LogKnownStaleSurfaces(log);
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 counterattack correlation diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			_registrationAuditStatus = "FAILED_CLOSED: no exact startup hook surfaces patched";
			log?.LogWarning("HoMM3 counterattack correlation diagnostics found no exact command/resolver/damage surfaces; counterattack packet remains disabled.");
			return;
		}

		_registrationAuditStatus = "DIAGNOSTIC_HOOK_REGISTERED: exact trace patches=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
		log?.LogInfo("HoMM3 counterattack correlation diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 counterattack correlation diagnostics: this proves only command/resolver/damage correlation; law effects remain gated until a reviewed runtime capture separates normal attacks, counterattacks, follow-up attacks, and revenge/additional damage.");
	}

	private static void LogKnownStaleSurfaces(ManualLogSource log)
	{
		log?.LogWarning("HoMM3 counterattack correlation diagnostics: attack-resolver surfaces remain disabled because the June 18 refreshed decomp dossiers found no matching methods. The cty.hsg battle-attack command hook is source-prepared separately and remains runtime-unproven.");
	}

	private static int PatchBattleAttackCommand(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.CounterattackCorrelationLawsBattleAttackCommand);
		if (type == null)
		{
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: battle attack command type not found.");
			return 0;
		}

		var method = ResolveExactMethod(type, GameSymbols.CounterattackCorrelationLaws.BattleAttackExecute.NameHints, 0);
		if (method == null)
		{
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: exact battle attack command execute method not found.");
			return 0;
		}

		var prefix = AccessTools.Method(typeof(Homm3CounterattackCorrelationLawDiagnostics), nameof(PrefixBattleAttackCommand));
		var postfix = AccessTools.Method(typeof(Homm3CounterattackCorrelationLawDiagnostics), nameof(PostfixBattleAttackCommand));
		if (!PatchCompatible(method, prefix, log) || !PatchCompatible(method, postfix, log))
			return 0;

		harmony.Patch(
			method,
			prefix: new HarmonyMethod(prefix) { priority = Priority.First },
			postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return 1;
	}

	private static int PatchAbilityResolve(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.CounterattackCorrelationLawsAbilityManager);
		if (type == null)
		{
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: ability manager type not found.");
			return 0;
		}

		var method = ResolveExactMethod(type, GameSymbols.CounterattackCorrelationLaws.AbilityManagerResolve.NameHints, 3);
		if (method == null)
		{
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: exact ability manager resolve method not found.");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3CounterattackCorrelationLawDiagnostics), nameof(PostfixAbilityResolve));
		if (!PatchCompatible(method, postfix, log))
			return 0;

		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return 1;
	}

	private static int PatchAttackResolvers(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.CounterattackCorrelationLawsBattleLogic);
		if (type == null)
		{
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: battle logic type not found.");
			return 0;
		}

		var prefix = AccessTools.Method(typeof(Homm3CounterattackCorrelationLawDiagnostics), nameof(PrefixAttackResolver));
		var postfix = AccessTools.Method(typeof(Homm3CounterattackCorrelationLawDiagnostics), nameof(PostfixAttackResolver));
		var patched = 0;
		foreach (var methodName in GameSymbols.CounterattackCorrelationLaws.AttackResolver.NameHints)
		{
			var method = ResolveExactMethod(type, new[] { methodName }, 7);
			if (method == null)
			{
				log?.LogWarning("HoMM3 counterattack correlation diagnostics: exact attack resolver " + methodName + "(7 args) not found.");
				continue;
			}
			if (!PatchCompatible(method, prefix, log) || !PatchCompatible(method, postfix, log))
				continue;
			harmony.Patch(
				method,
				prefix: new HarmonyMethod(prefix) { priority = Priority.First },
				postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			patched++;
		}

		return patched;
	}

	private static int PatchAbilityRuntimeChangeEvents(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.CounterattackCorrelationLawsAbilityRuntime);
		if (type == null)
		{
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: ability runtime type not found.");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3CounterattackCorrelationLawDiagnostics), nameof(PostfixAbilityRuntimeChangeEvent));
		var patchedMethods = new HashSet<MethodInfo>();
		var patched = 0;
		foreach (var methodName in GameSymbols.CounterattackCorrelationLaws.AbilityRuntimeChangeEvent.NameHints)
		{
			var method = ResolveExactMethod(type, new[] { methodName }, 0);
			if (method == null)
				continue;
			if (!IsAbilityRuntimeChangeEventSignature(method))
			{
				log?.LogWarning("HoMM3 counterattack correlation diagnostics: refusing ability-runtime change-event candidate with wrong signature " + FormatMethod(method) + ".");
				continue;
			}
			if (!patchedMethods.Add(method))
				continue;
			if (!PatchCompatible(method, postfix, log))
				continue;
			harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			log?.LogInfo("HoMM3 counterattack correlation diagnostics: accepted decomp-backed dxy change-event factory " + FormatMethod(method) + ".");
			patched++;
		}

		if (patched == 0)
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: no exact dxy ChangeAbilityEventArgs factories found; ability-runtime trace remains disabled.");
		return patched;
	}

	private static int PatchAbilityChangeListeners(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.CounterattackCorrelationLawsAbilityListener);
		if (type == null)
		{
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: ability listener type not found.");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3CounterattackCorrelationLawDiagnostics), nameof(PostfixAbilityChangeListener));
		var patched = 0;
		foreach (var methodName in GameSymbols.CounterattackCorrelationLaws.AbilityListenerChanged.NameHints)
		{
			var method = ResolveExactAbilityListenerMethod(type, methodName);
			if (method == null)
				continue;

			if (!PatchCompatible(method, postfix, log))
				continue;

			harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			patched++;
		}

		if (patched == 0)
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: no exact ebv ability listener methods found; ability-type trace remains disabled.");
		return patched;
	}

	private static MethodInfo ResolveExactAbilityListenerMethod(Type type, string name)
	{
		foreach (var method in AccessTools.GetDeclaredMethods(type))
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (!IsAbilityListenerSignature(method))
				continue;
			return method;
		}

		return null;
	}

	private static bool IsAbilityListenerSignature(MethodInfo method)
	{
		if (method == null || method.IsSpecialName || method.ReturnType != typeof(void))
			return false;
		var ps = method.GetParameters();
		return ps.Length == 3
		       && IsBattleUnitType(ps[0].ParameterType)
		       && ps[1].ParameterType == typeof(EAbilityType)
		       && ps[2].ParameterType == typeof(int);
	}

	private static bool IsAbilityRuntimeChangeEventSignature(MethodInfo method)
	{
		if (method == null || method.IsSpecialName || method.ReturnType != typeof(ChangeAbilityEventArgs))
			return false;
		return method.GetParameters().Length == 0;
	}

	private static bool IsBattleUnitType(Type type)
	{
		return type != null
		       && (string.Equals(type.FullName, "Hex.Session.Battle.Unit", StringComparison.Ordinal)
		           || string.Equals(type.Name, "Unit", StringComparison.Ordinal));
	}

	private static bool IsIntArrayType(Type type)
	{
		return type != null && type.IsArray && type.GetElementType() == typeof(int);
	}

	private static MethodInfo ResolveExactMethod(Type type, string[] names, int parameterCount)
	{
		foreach (var name in names)
		{
			foreach (var method in AccessTools.GetDeclaredMethods(type))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (method.IsSpecialName)
					continue;
				if (method.GetParameters().Length != parameterCount)
					continue;
				return method;
			}
		}

		return null;
	}

	private static bool PatchCompatible(MethodInfo method, MethodInfo patch, ManualLogSource log)
	{
		if (patch == null)
		{
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: patch method missing for " + FormatMethod(method) + ".");
			return false;
		}
		if (!GameMember.IsHarmonyPatchCompatible(method, patch, out var reason))
		{
			log?.LogWarning("HoMM3 counterattack correlation diagnostics: refusing incompatible patch for " + FormatMethod(method) + ": " + reason);
			return false;
		}
		return true;
	}

	private static void PrefixBattleAttackCommand(object __instance, MethodBase __originalMethod)
	{
		var previous = _currentCommand;
		_currentCommand = CommandContext.Capture(++_sequence, __instance, __originalMethod, previous);
		LogTrace("command-start", __instance, __originalMethod, null, null);
	}

	private static void PostfixBattleAttackCommand(object __instance, MethodBase __originalMethod)
	{
		LogTrace("command-end", __instance, __originalMethod, null, null);
		_currentCommand = _currentCommand?.Previous;
	}

	private static void PostfixAbilityResolve(object __instance, MethodBase __originalMethod, object[] __args, object __result)
	{
		LogTrace("ability-resolve", __instance, __originalMethod, __args, __result);
	}

	private static void PrefixAttackResolver(object __instance, MethodBase __originalMethod, object[] __args)
	{
		var previous = _currentResolver;
		_currentResolver = ResolverContext.Capture(++_sequence, __instance, __originalMethod, __args, previous);
		LogTrace("resolver-start", __instance, __originalMethod, __args, null);
	}

	private static void PostfixAttackResolver(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("resolver-end", __instance, __originalMethod, __args, null);
		_currentResolver = _currentResolver?.Previous;
	}

	private static void PostfixAbilityChangeListener(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("ability-listener", __instance, __originalMethod, __args, null);
	}

	private static void PostfixAbilityRuntimeChangeEvent(object __instance, MethodBase __originalMethod, object __result)
	{
		LogTrace("ability-runtime-change-event", __instance, __originalMethod, null, __result);
	}

	private static void LogTrace(string stage, object instance, MethodBase method, object[] args, object result)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;
			Homm3DiagnosticBreadcrumbs.Enter("counterattack-correlation-law", method, stage);

			Plugin.LogSource?.LogInfo(
				"HoMM3 counterattack correlation diagnostic: "
				+ stage
				+ " method="
				+ FormatMethod(method)
				+ " command="
				+ (_currentCommand == null ? "none" : _currentCommand.Describe())
				+ " resolver="
				+ (_currentResolver == null ? "none" : _currentResolver.Describe())
				+ " instance="
				+ DescribeObjectContext(instance)
				+ " args="
				+ DescribeArgs(args)
				+ " result="
				+ DescribeObjectContext(result)
				+ " activeCounterstroke="
				+ DescribeActiveCounterstroke(args)
				+ " counterattackObservation="
				+ DescribeCounterattackObservation(args)
				+ " changeEventObservation="
				+ DescribeChangeEventObservation(stage, result)
				+ " changeEventProfile="
				+ DescribeChangeEventProfile(stage, result)
				+ " changeEventPlan="
				+ DescribeChangeEventPlan(stage, result)
				+ " counterattackProfile="
				+ DescribeCounterattackProfile(args)
				+ " counterattackPlan="
				+ DescribeCounterattackPlan(args)
				+ " handlerGate="
				+ Homm3CustomLawHandlerTrace.Describe(
					ResolveCounterattackHandlerOwner(args, instance),
					Homm3CustomLawHandlerTrace.CounterattackDoctrine)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 counterattack correlation diagnostic log failed: " + ex.Message);
		}
	}

	private static string DescribeCounterattackObservation(object[] args)
	{
		if (args == null || args.Length < 3)
			return "none";
		if (args[1] is not EAbilityType abilityType)
			return "unreadable-ability-type";
		if (args[2] is not int abilityIndex)
			return "unreadable-ability-index";
		return Homm3CustomCounterattackLawRuntime.TryObserveCounterattackAbility(
			args[0],
			abilityType,
			abilityIndex,
			out var observation,
			out var failReason)
			? observation.ToString()
			: "unresolved:" + failReason;
	}

	private static string DescribeChangeEventObservation(string stage, object result)
	{
		if (!string.Equals(stage, "ability-runtime-change-event", StringComparison.Ordinal))
			return "not-change-event-stage";
		return Homm3CustomCounterattackLawRuntime.TryObserveCounterattackChangeAbilityEvent(
			result,
			out var observation,
			out var failReason)
			? observation.ToString()
			: "unresolved:" + failReason;
	}

	private static string DescribeChangeEventProfile(string stage, object result)
	{
		if (!string.Equals(stage, "ability-runtime-change-event", StringComparison.Ordinal))
			return "not-change-event-stage";
		return Homm3CustomCounterattackLawRuntime.TryGetCandidateCounterattackDoctrineProfileForChangeAbilityEvent(
			result,
			out var observation,
			out var profile,
			out _,
			out var context,
			out var failReason)
			? "context={" + context + "} observation={" + observation + "} profile={" + profile + "}"
			: "unresolved:" + failReason;
	}

	private static string DescribeChangeEventPlan(string stage, object result)
	{
		if (!string.Equals(stage, "ability-runtime-change-event", StringComparison.Ordinal))
			return "not-change-event-stage";
		return Homm3CustomCounterattackLawRuntime.TryPlanCandidateCounterattackDoctrineEffectForChangeAbilityEvent(
			result,
			out var observation,
			out var profile,
			out _,
			out var context,
			out var plan,
			out var failReason)
			? "context={" + context + "} observation={" + observation + "} profile={" + profile + "} plan={" + plan + "}"
			: "unresolved:" + failReason;
	}

	private static string DescribeCounterattackProfile(object[] args)
	{
		if (args == null || args.Length < 3)
			return "none";
		if (args[1] is not EAbilityType abilityType)
			return "unreadable-ability-type";
		if (args[2] is not int abilityIndex)
			return "unreadable-ability-index";
		return Homm3CustomCounterattackLawRuntime.TryGetCandidateCounterattackDoctrineProfileForBattleObject(
			args[0],
			abilityType,
			abilityIndex,
			out var observation,
			out var profile,
			out _,
			out var context,
			out var failReason)
			? "context={" + context + "} observation={" + observation + "} profile={" + profile + "}"
			: "unresolved:" + failReason;
	}

	private static string DescribeCounterattackPlan(object[] args)
	{
		if (args == null || args.Length < 3)
			return "none";
		if (args[1] is not EAbilityType abilityType)
			return "unreadable-ability-type";
		if (args[2] is not int abilityIndex)
			return "unreadable-ability-index";
		return Homm3CustomCounterattackLawRuntime.TryPlanCandidateCounterattackDoctrineEffectForBattleObject(
			args[0],
			abilityType,
			abilityIndex,
			out var observation,
			out var profile,
			out _,
			out var context,
			out var plan,
			out var failReason)
			? "context={" + context + "} observation={" + observation + "} profile={" + profile + "} plan={" + plan + "}"
			: "unresolved:" + failReason;
	}

	private static string DescribeActiveCounterstroke(object[] args)
	{
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(args[i], Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex, out var state))
					return "index=" + state.Index + ",rank=" + state.Rank + ",faction=" + state.FactionSid + ",family=" + state.Family;
			}
		}

		if (_currentCommand != null && Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(_currentCommand.Source, Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex, out var commandState))
			return "index=" + commandState.Index + ",rank=" + commandState.Rank + ",faction=" + commandState.FactionSid + ",family=" + commandState.Family;
		if (_currentResolver != null && Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(_currentResolver.Source, Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex, out var resolverState))
			return "index=" + resolverState.Index + ",rank=" + resolverState.Rank + ",faction=" + resolverState.FactionSid + ",family=" + resolverState.Family;
		return "none-or-unresolved";
	}

	private static object ResolveCounterattackHandlerOwner(object[] args, object instance)
	{
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(args[i], Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex, out _))
					return args[i];
			}
		}

		if (_currentCommand != null)
			return _currentCommand.Source;
		if (_currentResolver != null)
			return _currentResolver.Source;
		return instance;
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

	private static string DescribeObjectContext(object value)
	{
		if (value == null)
			return "null";

		var type = value.GetType();
		var parts = new List<string>(MaxMemberSnapshots + 2)
		{
			"type=" + (type.FullName ?? type.Name)
		};

		var obfuscated = GameMember.ReadObfuscatedName(type);
		if (!string.IsNullOrEmpty(obfuscated))
			parts.Add("obf=" + obfuscated);

		AddSimpleMemberSnapshots(value, type, parts);
		return "{" + string.Join("|", parts) + "}";
	}

	private static void AddSimpleMemberSnapshots(object value, Type type, List<string> parts)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && parts.Count < MaxMemberSnapshots; current = current.BaseType)
		{
			foreach (var field in current.GetFields(flags))
			{
				if (field.IsStatic)
					continue;
				if (!TryFormatSimpleValue(field.FieldType, () => field.GetValue(value), out var formatted))
					continue;
				parts.Add(field.Name + "=" + formatted);
				if (parts.Count >= MaxMemberSnapshots)
					return;
			}
		}
	}

	private static string ReadFirstMember(object value, string[] names)
	{
		if (value == null || names == null)
			return "(absent)";
		var type = value.GetType();
		for (var i = 0; i < names.Length; i++)
		{
			if (TryReadMember(value, type, names[i], out var raw))
				return SafeFormatValue(raw);
		}
		return "(absent)";
	}

	private static bool TryReadMember(object value, Type type, string name, out object raw)
	{
		raw = null;
		if (value == null || type == null || string.IsNullOrWhiteSpace(name))
			return false;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			try
			{
				var field = current.GetField(name, flags);
				if (field != null)
				{
					raw = field.GetValue(value);
					return true;
				}
			}
			catch
			{
			}
			try
			{
				var property = current.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
				{
					raw = property.GetValue(value, null);
					return true;
				}
			}
			catch
			{
			}
			try
			{
				var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
				{
					raw = method.Invoke(value, null);
					return true;
				}
			}
			catch
			{
			}
		}
		return false;
	}

	private static bool TryFormatSimpleValue(Type valueType, Func<object> read, out string formatted)
	{
		formatted = null;
		try
		{
			var raw = read();
			if (raw == null)
			{
				formatted = "null";
				return true;
			}

			var runtimeType = raw.GetType();
			if (!IsSimpleType(valueType) && !IsSimpleType(runtimeType))
				return false;
			formatted = SafeFormatValue(raw);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static string SafeFormatValue(object value)
	{
		if (value == null)
			return "null";
		try
		{
			var text = Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
			if (string.IsNullOrEmpty(text))
				text = "(empty)";
			return text.Length <= 80 ? text : text.Substring(0, 80) + "...";
		}
		catch
		{
			return "(err)";
		}
	}

	private static bool IsSimpleType(Type type)
	{
		if (type == null)
			return false;
		if (type.IsPrimitive || type.IsEnum)
			return true;
		return type == typeof(string)
		       || type == typeof(decimal)
		       || type == typeof(IntPtr)
		       || type == typeof(UIntPtr);
	}

	private sealed class CommandContext
	{
		internal int Sequence;
		internal object Source;
		internal string Method;
		internal string AttackerId;
		internal string TargetId;
		internal string AbilityType;
		internal string AbilityIndex;
		internal CommandContext Previous;

		internal static CommandContext Capture(int sequence, object source, MethodBase method, CommandContext previous)
		{
			return new CommandContext
			{
				Sequence = sequence,
				Source = source,
				Method = FormatMethod(method),
				AttackerId = ReadFirstMember(source, GameSymbols.CounterattackCorrelationLaws.CommandAttackerIdFields),
				TargetId = ReadFirstMember(source, GameSymbols.CounterattackCorrelationLaws.CommandTargetIdFields),
				AbilityType = ReadFirstMember(source, GameSymbols.CounterattackCorrelationLaws.CommandAbilityTypeFields),
				AbilityIndex = ReadFirstMember(source, GameSymbols.CounterattackCorrelationLaws.CommandAbilityIndexFields),
				Previous = previous
			};
		}

		internal string Describe()
		{
			return "{seq=" + Sequence + ";method=" + Method + ";attackerId=" + AttackerId + ";targetId=" + TargetId + ";abilityType=" + AbilityType + ";abilityIndex=" + AbilityIndex + "}";
		}
	}

	private sealed class ResolverContext
	{
		internal int Sequence;
		internal object Source;
		internal string Method;
		internal string Args;
		internal ResolverContext Previous;

		internal static ResolverContext Capture(int sequence, object source, MethodBase method, object[] args, ResolverContext previous)
		{
			return new ResolverContext
			{
				Sequence = sequence,
				Source = source,
				Method = FormatMethod(method),
				Args = DescribeArgs(args),
				Previous = previous
			};
		}

		internal string Describe()
		{
			return "{seq=" + Sequence + ";method=" + Method + ";args=" + Args + "}";
		}
	}
}
