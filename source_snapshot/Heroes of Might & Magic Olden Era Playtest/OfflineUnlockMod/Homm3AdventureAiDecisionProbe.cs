using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Flag-gated read-only Harmony probe for adventure AI day start (<c>fjl.OnStartDay</c>).
/// Captures a mark-centric <see cref="Homm3AdventureLookaheadState"/> snapshot for logging only —
/// no mark writeback, no search, no enter-node redirects.
/// Enable with <c>homm3_adventure_ai_decision_probe.flag</c>.
/// Evidence: docs/ai_lookahead_requirements.md (source/static; runtime-unvalidated until live AI days log).
/// </summary>
internal static class Homm3AdventureAiDecisionProbe
{
	internal const string DiagnosticFlag = "homm3_adventure_ai_decision_probe.flag";

	private const int LogCap = 64;
	private static bool _registered;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";
	private static ManualLogSource _log;
	private static int _logged;
	private static int _observed;
	private static int _patched;
	private static int _captureFailures;

	internal static string RegistrationAuditStatus => _registrationAuditStatus;
	internal static int PatchedCount => _patched;
	internal static int ObservedCount => _observed;
	internal static int CaptureFailureCount => _captureFailures;

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
			var dayController = ResolveDayControllerType();
			if (dayController == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: day controller type unresolved (expected fjl)";
				log?.LogWarning("HoMM3 adventure AI decision probe failed closed: day controller type not found.");
				return;
			}

			var methods = ResolveOnStartDayMethods(dayController);
			if (methods.Count == 0)
			{
				_registrationAuditStatus = "FAILED_CLOSED: OnStartDay signature unresolved on " + dayController.FullName;
				log?.LogWarning("HoMM3 adventure AI decision probe failed closed: no hinted void OnStartDay() on " + dayController.FullName + ".");
				return;
			}

			var postfix = AccessTools.Method(typeof(Homm3AdventureAiDecisionProbe), nameof(PostfixOnStartDay));
			if (postfix == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: postfix missing";
				return;
			}

			var patched = 0;
			foreach (var method in methods)
			{
				if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
				{
					log?.LogWarning("HoMM3 adventure AI decision probe refused incompatible postfix for " + FormatMethod(method) + ": " + reason);
					continue;
				}
				harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
				patched++;
				log?.LogInfo("HoMM3 adventure AI decision probe patched " + FormatMethod(method) + ".");
			}

			_patched = patched;
			if (patched == 0)
			{
				_registrationAuditStatus = "FAILED_CLOSED: zero compatible OnStartDay patches";
				log?.LogWarning("HoMM3 adventure AI decision probe failed closed: Harmony refused all OnStartDay candidates.");
				return;
			}

			_registered = true;
			_registrationAuditStatus = "RUNTIME_HOOK_REGISTERED: onStartDayPatches=" + patched.ToString(CultureInfo.InvariantCulture)
				+ " dayController=" + (dayController.FullName ?? dayController.Name);
			log?.LogInfo("HoMM3 adventure AI decision probe registered " + patched + " read-only OnStartDay postfix(es). Observation only.");
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 adventure AI decision probe failed closed during registration: " + ex.Message);
		}
	}

	private static Type ResolveDayControllerType()
	{
		foreach (var hint in GameSymbols.AdventureAiDecision.DayControllerTypeHints)
		{
			var type = GameMember.FindType(GameSymbols.AdventureAiDecision.DayControllerTypeId + "." + hint, hint)
				?? AccessTools.TypeByName(hint);
			if (type == null || !type.IsClass)
				continue;
			if (CollectVoidNoArgInstanceMethods(type).Count == 0)
				continue;
			if (!HasLocatorField(type))
				continue;
			return type;
		}

		// Interop may rename fjl → ObjectPublic*. Require a unique owner of hinted OnStartDay names.
		var hintSet = new HashSet<string>(
			GameSymbols.AdventureAiDecision.OnStartDay.NameHints ?? Array.Empty<string>(),
			StringComparer.Ordinal);
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
				var hits = 0;
				foreach (var method in CollectVoidNoArgInstanceMethods(type))
				{
					if (hintSet.Contains(method.Name))
						hits++;
				}
				if (hits == 0)
					continue;
				if (!HasLocatorField(type))
					continue;
				if (unique != null && unique != type)
				{
					_log?.LogWarning(
						"HoMM3 adventure AI decision probe: ambiguous day-controller owners "
						+ unique.FullName + " and " + type.FullName + "; refusing silent pick.");
					return null;
				}
				unique = type;
			}
		}
		return unique;
	}

	private static bool HasLocatorField(Type dayController)
	{
		if (dayController == null)
			return false;
		foreach (var hint in GameSymbols.AdventureAiDecision.LocatorFieldOnDayControllerHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			try
			{
				if (dayController.GetField(hint, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance) != null)
					return true;
			}
			catch { }
		}
		return false;
	}

	private static List<MethodInfo> CollectVoidNoArgInstanceMethods(Type type)
	{
		var matches = new List<MethodInfo>();
		if (type == null)
			return matches;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		MethodInfo[] declared;
		try { declared = type.GetMethods(flags); }
		catch { return matches; }

		foreach (var method in declared)
		{
			if (method.ReturnType != typeof(void))
				continue;
			ParameterInfo[] ps;
			try { ps = method.GetParameters(); }
			catch { continue; }
			if (ps.Length != 0)
				continue;
			matches.Add(method);
		}
		return matches;
	}

	private static List<MethodInfo> ResolveOnStartDayMethods(Type dayController)
	{
		var matches = CollectVoidNoArgInstanceMethods(dayController);
		var hintSet = new HashSet<string>(
			GameSymbols.AdventureAiDecision.OnStartDay.NameHints ?? Array.Empty<string>(),
			StringComparer.Ordinal);

		var hinted = matches.FindAll(m => hintSet.Contains(m.Name));
		if (hinted.Count == 0)
		{
			_log?.LogWarning(
				"HoMM3 adventure AI decision probe: " + matches.Count
				+ " void() method(s) on " + (dayController.FullName ?? dayController.Name)
				+ " but none match OnStartDay name hints; refusing silent patch.");
			return new List<MethodInfo>();
		}

		// Prefer readable OnStartDay; still patch all hinted aliases that share the day-entry body.
		hinted.Sort((a, b) =>
		{
			var ha = string.Equals(a.Name, "OnStartDay", StringComparison.Ordinal) ? 0 : 1;
			var hb = string.Equals(b.Name, "OnStartDay", StringComparison.Ordinal) ? 0 : 1;
			if (ha != hb)
				return ha.CompareTo(hb);
			return string.CompareOrdinal(a.Name, b.Name);
		});

		// Patch only the preferred readable name when present to avoid triple-firing shared RVA aliases.
		foreach (var method in hinted)
		{
			if (string.Equals(method.Name, "OnStartDay", StringComparison.Ordinal))
				return new List<MethodInfo> { method };
		}
		return new List<MethodInfo> { hinted[0] };
	}

	private static void PostfixOnStartDay(object __instance, MethodBase __originalMethod)
	{
		try
		{
			_observed++;
			if (_logged >= LogCap)
				return;
			_logged++;

			var sb = new StringBuilder(320);
			sb.Append("HoMM3 adventure AI decision probe OnStartDay method=")
				.Append(__originalMethod?.Name ?? "?")
				.Append(" observed=")
				.Append(_observed.ToString(CultureInfo.InvariantCulture));

			if (!TryResolveLiveSide(__instance, out var liveSide, out var resolveError))
			{
				_captureFailures++;
				sb.Append(" capture=FAILED sideResolve=").Append(resolveError ?? "?");
				(_log ?? Plugin.LogSource)?.LogInfo(sb.ToString());
				return;
			}

			if (!Homm3AdventureLookaheadState.TryCaptureFromLiveSide(liveSide, out var state, out var captureError))
			{
				_captureFailures++;
				sb.Append(" capture=FAILED ").Append(captureError ?? "?");
				(_log ?? Plugin.LogSource)?.LogInfo(sb.ToString());
				return;
			}

			state.Day = Homm3AdventureLookaheadState.ReadInt(
				__instance,
				GameSymbols.AdventureAiDecision.DayIndexOnDayControllerHints,
				0);
			state.ActiveStrategyHint = TryReadActiveStrategyHint(__instance);
			var liveCaptureOk = Homm3AiDriverBridge.TryCaptureAdventureLiveWorld(state, out var liveReport);
			sb.Append(" liveCapture=").Append(liveCaptureOk)
				.Append(" live=").Append(liveReport ?? "?");
			sb.Append(' ').Append(state.FormatSummary());
			(_log ?? Plugin.LogSource)?.LogInfo(sb.ToString());
		}
		catch (Exception ex)
		{
			_captureFailures++;
			(_log ?? Plugin.LogSource)?.LogWarning("HoMM3 adventure AI decision probe postfix failed: " + ex.Message);
		}
	}

	private static bool TryResolveLiveSide(object dayController, out object liveSide, out string error)
	{
		liveSide = null;
		error = null;
		if (dayController == null)
		{
			error = "dayController null";
			return false;
		}

		var locator = Homm3AdventureLookaheadState.ReadMember(
			dayController,
			GameSymbols.AdventureAiDecision.LocatorFieldOnDayControllerHints);
		if (locator == null)
		{
			error = "locator field unresolved";
			return false;
		}

		var sideRuntime = Homm3AdventureLookaheadState.ReadMember(
			locator,
			GameSymbols.AdventureAiDecision.SideRuntimeOnLocatorHints);
		if (sideRuntime == null)
		{
			error = "side runtime on locator unresolved";
			return false;
		}

		liveSide = Homm3AdventureLookaheadState.ReadMember(
			sideRuntime,
			GameSymbols.AdventureAiDecision.SideOnRuntimeHints);
		if (liveSide == null)
		{
			error = "Side on runtime unresolved";
			return false;
		}
		return true;
	}

	private static string TryReadActiveStrategyHint(object dayController)
	{
		var active = Homm3AdventureLookaheadState.ReadMember(
			dayController,
			GameSymbols.AdventureAiDecision.ActiveStrategyFieldHints);
		if (active == null)
			return null;
		var config = Homm3AdventureLookaheadState.ReadMember(
			active,
			GameSymbols.AdventureAiDecision.StrategyConfigOnRunnerHints);
		if (config == null)
			return active.GetType().Name;
		var sid = Homm3AdventureLookaheadState.ReadMember(config, new[] { "sid", "id", "name" });
		return sid?.ToString() ?? config.GetType().Name;
	}

	private static string FormatMethod(MethodInfo method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
