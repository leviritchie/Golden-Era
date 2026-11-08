using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using BepInEx.Logging;
using HarmonyLib;
using OldenAiSim;

namespace OfflineUnlockMod;

/// <summary>
/// Day-start: export state → OldenAiSim.Evaluate → bias cache.
/// Task score: postfix on <c>ffe.bjsj</c> multiplies score when apply flag is set.
/// Flags: <c>homm3_adventure_ai_weight_bridge.flag</c> (register),
/// <c>homm3_adventure_ai_weight_apply.flag</c> (mutate scores; otherwise log-only).
/// Evidence: docs/ai_external_sim_weight_bridge.md
/// </summary>
internal static class Homm3AdventureAiWeightBridge
{
	internal const string DiagnosticFlag = "homm3_adventure_ai_weight_bridge.flag";
	internal const string WeightApplyFlag = "homm3_adventure_ai_weight_apply.flag";

	private const int LogCap = 128;
	private static bool _registered;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";
	private static ManualLogSource _log;
	private static int _logged;
	private static int _dayRuns;
	private static int _scoreObservations;
	private static int _scoreApplies;
	private static int _patched;
	private static readonly object BiasGate = new object();
	private static Dictionary<long, float> _biases = new Dictionary<long, float>();
	private static int _biasSide = -1;
	private static bool _biasesReadyForApply;
	private static string _lastDiagnostics = "";

	internal static string RegistrationAuditStatus => _registrationAuditStatus;
	internal static int PatchedCount => _patched;
	internal static int DayRunCount => _dayRuns;
	internal static int ScoreApplyCount => _scoreApplies;

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
				_registrationAuditStatus = "FAILED_CLOSED: day controller unresolved";
				log?.LogWarning("HoMM3 adventure AI weight bridge failed closed: day controller missing.");
				return;
			}

			var onStartDay = ResolveOnStartDay(dayController);
			if (onStartDay == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: OnStartDay unresolved";
				return;
			}

			var scorer = ResolveTaskScorerType();
			if (scorer == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: task scorer type unresolved (ffe)";
				log?.LogWarning("HoMM3 adventure AI weight bridge failed closed: ffe not found.");
				return;
			}

			var scoreMethods = ResolveScoreTaskMethods(scorer);
			if (scoreMethods.Count == 0)
			{
				_registrationAuditStatus = "FAILED_CLOSED: bjsj signature unresolved on " + scorer.FullName;
				return;
			}

			var dayPostfix = AccessTools.Method(typeof(Homm3AdventureAiWeightBridge), nameof(PostfixOnStartDay));
			var scorePostfix = AccessTools.Method(typeof(Homm3AdventureAiWeightBridge), nameof(PostfixScoreTask));
			if (dayPostfix == null || scorePostfix == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: postfix missing";
				return;
			}

			var patched = 0;
			if (GameMember.IsHarmonyPatchCompatible(onStartDay, dayPostfix, out var dayReason))
			{
				harmony.Patch(onStartDay, postfix: new HarmonyMethod(dayPostfix) { priority = Priority.Last });
				patched++;
				log?.LogInfo("HoMM3 adventure AI weight bridge patched " + FormatMethod(onStartDay) + ".");
			}
			else
				log?.LogWarning("HoMM3 adventure AI weight bridge refused OnStartDay patch: " + dayReason);

			foreach (var method in scoreMethods)
			{
				if (!GameMember.IsHarmonyPatchCompatible(method, scorePostfix, out var reason))
				{
					log?.LogWarning("HoMM3 adventure AI weight bridge refused score patch for " + FormatMethod(method) + ": " + reason);
					continue;
				}
				harmony.Patch(method, postfix: new HarmonyMethod(scorePostfix) { priority = Priority.Last });
				patched++;
				log?.LogInfo("HoMM3 adventure AI weight bridge patched " + FormatMethod(method) + ".");
			}

			_patched = patched;
			if (patched < 2)
			{
				_registrationAuditStatus = "FAILED_CLOSED: need OnStartDay + at least one bjsj patch; got " + patched;
				return;
			}

			_registered = true;
			_registrationAuditStatus = "RUNTIME_HOOK_REGISTERED: patches=" + patched.ToString(CultureInfo.InvariantCulture)
				+ " apply=" + Homm3DiagnosticFlags.IsEnabled(WeightApplyFlag);
			log?.LogInfo("HoMM3 adventure AI weight bridge registered. applyFlag="
				+ Homm3DiagnosticFlags.IsEnabled(WeightApplyFlag) + ".");
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 adventure AI weight bridge failed closed: " + ex.Message);
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
			if (ResolveOnStartDay(type) == null)
				continue;
			return type;
		}
		return null;
	}

	private static MethodInfo ResolveOnStartDay(Type dayController)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		MethodInfo[] declared;
		try { declared = dayController.GetMethods(flags); }
		catch { return null; }
		MethodInfo preferred = null;
		foreach (var method in declared)
		{
			if (method.ReturnType != typeof(void))
				continue;
			ParameterInfo[] ps;
			try { ps = method.GetParameters(); }
			catch { continue; }
			if (ps.Length != 0)
				continue;
			if (string.Equals(method.Name, "OnStartDay", StringComparison.Ordinal))
				return method;
			foreach (var hint in GameSymbols.AdventureAiDecision.OnStartDay.NameHints ?? Array.Empty<string>())
			{
				if (string.Equals(method.Name, hint, StringComparison.Ordinal))
					preferred ??= method;
			}
		}
		return preferred;
	}

	private static Type ResolveTaskScorerType()
	{
		foreach (var hint in GameSymbols.AdventureAiDecision.TaskScorerTypeHints)
		{
			var type = GameMember.FindType(GameSymbols.AdventureAiDecision.TaskScorerTypeId + "." + hint, hint)
				?? AccessTools.TypeByName(hint);
			if (type != null && CollectScoreMethods(type).Count > 0)
				return type;
		}

		var priorityType = ResolveNamedType(
			GameSymbols.AdventureAiDecision.HeroAiPriorityTypeId,
			GameSymbols.AdventureAiDecision.HeroAiPriorityTypeHints);
		if (priorityType == null)
			return null;

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
				if (CollectScoreMethods(type, priorityType).Count == 0)
					continue;
				if (unique != null && unique != type)
				{
					_log?.LogWarning("HoMM3 adventure AI weight bridge: ambiguous ffe owners; refusing.");
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

	private static List<MethodInfo> CollectScoreMethods(Type scorer, Type priorityType = null)
	{
		priorityType ??= ResolveNamedType(
			GameSymbols.AdventureAiDecision.HeroAiPriorityTypeId,
			GameSymbols.AdventureAiDecision.HeroAiPriorityTypeHints);
		var matches = new List<MethodInfo>();
		if (scorer == null || priorityType == null)
			return matches;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		MethodInfo[] declared;
		try { declared = scorer.GetMethods(flags); }
		catch { return matches; }
		foreach (var method in declared)
		{
			if (method.ReturnType != typeof(int))
				continue;
			ParameterInfo[] ps;
			try { ps = method.GetParameters(); }
			catch { continue; }
			if (ps.Length != 10)
				continue;
			if (!GameMember.TypesEquivalent(priorityType, ps[0].ParameterType))
				continue;
			if (ps[1].ParameterType != typeof(int))
				continue;
			matches.Add(method);
		}
		return matches;
	}

	private static List<MethodInfo> ResolveScoreTaskMethods(Type scorer)
	{
		var matches = CollectScoreMethods(scorer);
		var hintSet = new HashSet<string>(
			GameSymbols.AdventureAiDecision.ScoreTask.NameHints ?? Array.Empty<string>(),
			StringComparer.Ordinal);
		var hinted = matches.FindAll(m => hintSet.Contains(m.Name));
		if (hinted.Count > 0)
			return hinted;
		if (matches.Count > 0)
		{
			_log?.LogWarning(
				"HoMM3 adventure AI weight bridge: " + matches.Count
				+ " unhinted score signature(s); refusing silent patch.");
		}
		return new List<MethodInfo>();
	}

	private static void PostfixOnStartDay(object __instance)
	{
		try
		{
			_dayRuns++;
			var applyFlag = Homm3DiagnosticFlags.IsEnabled(WeightApplyFlag);
			if (!TryResolveLiveSide(__instance, out var liveSide, out var resolveError))
			{
				ClearBiases();
				LogDay("capture=FAILED_CLOSED sideResolve=" + (resolveError ?? "?") + " applyFlag=" + applyFlag);
				return;
			}

			if (!Homm3AdventureLookaheadState.TryCaptureFromLiveSide(liveSide, out var capture, out var captureError))
			{
				ClearBiases();
				LogDay("capture=FAILED_CLOSED side=" + (captureError ?? "?") + " applyFlag=" + applyFlag);
				return;
			}

			capture.Day = Homm3AdventureLookaheadState.ReadInt(
				__instance,
				GameSymbols.AdventureAiDecision.DayIndexOnDayControllerHints,
				capture.Day);

			if (!Homm3AiDriverBridge.TryCaptureAdventureLiveWorld(capture, out var liveReport))
			{
				ClearBiases();
				LogDay("capture=FAILED_CLOSED live=" + (liveReport ?? "?") + " applyFlag=" + applyFlag);
				return;
			}
			if (!capture.TryValidateForSimulation(applyFlag, out var readinessError))
			{
				ClearBiases();
				LogDay("capture=FAILED_CLOSED readiness=" + (readinessError ?? "?")
					+ " live=" + (liveReport ?? "?") + " applyFlag=" + applyFlag);
				return;
			}

			var simState = capture.ToSimState();
			var result = AdventureSimulator.Evaluate(simState, new AdventureSimKnobs());
			var allowApply = applyFlag && result != null && result.Ok && !capture.MoveCostProvisional;
			InstallBiases(capture.SideIndex, result, allowApply);

			var sb = new StringBuilder(384);
			sb.Append("ok=").Append(result.Ok)
				.Append(" preferred=").Append(result.PreferredKind).Append(':').Append(result.PreferredId)
				.Append(" biases=").Append(result.Biases?.Count ?? 0)
				.Append(' ').Append(result.Diagnostics ?? "")
				.Append(" live=").Append(liveReport ?? "?")
				.Append(" applyFlag=").Append(applyFlag)
				.Append(" applyReady=").Append(allowApply);
			if (!string.IsNullOrEmpty(result.Error))
				sb.Append(" err=").Append(result.Error);
			_lastDiagnostics = sb.ToString();
			LogDay(_lastDiagnostics);
		}
		catch (Exception ex)
		{
			ClearBiases();
			(_log ?? Plugin.LogSource)?.LogWarning("HoMM3 adventure AI weight bridge day postfix failed: " + ex.Message);
		}
	}


	private static void InstallBiases(int sideIndex, AdventureSimResult result, bool readyForApply)
	{
		var map = new Dictionary<long, float>();
		if (result?.Biases != null)
		{
			for (var i = 0; i < result.Biases.Count; i++)
			{
				var b = result.Biases[i];
				if (b == null || b.Multiplier <= 0f)
					continue;
				map[BiasKey(b.TargetKind, b.TargetId)] = b.Multiplier;
				if (b.TargetId != 0)
					map[BiasKey(AdventureSimTargetKind.Unknown, b.TargetId)] = b.Multiplier;
			}
		}
		lock (BiasGate)
		{
			_biasSide = sideIndex;
			_biases = map;
			_biasesReadyForApply = readyForApply;
		}
	}

	private static void ClearBiases()
	{
		lock (BiasGate)
		{
			_biasSide = -1;
			_biases = new Dictionary<long, float>();
			_biasesReadyForApply = false;
		}
	}

	private static long BiasKey(AdventureSimTargetKind kind, int id)
	{
		return ((long)(int)kind << 32) | (uint)id;
	}

	private static void PostfixScoreTask(object __instance, ref int __result)
	{
		try
		{
			_scoreObservations++;
			float bias;
			if (!TryGetBiasForCandidate(__instance, out bias))
				return;

			var applyFlag = Homm3DiagnosticFlags.IsEnabled(WeightApplyFlag);
			bool readyForApply;
			lock (BiasGate)
				readyForApply = _biasesReadyForApply;
			var apply = applyFlag && readyForApply;
			var before = __result;
			if (apply)
			{
				var scaled = (int)Math.Round(__result * bias);
				__result = scaled;
				_scoreApplies++;
			}

			if (_logged < LogCap)
			{
				_logged++;
				(_log ?? Plugin.LogSource)?.LogInfo(
					"HoMM3 adventure AI weight bridge score obs="
					+ _scoreObservations.ToString(CultureInfo.InvariantCulture)
					+ " before=" + before.ToString(CultureInfo.InvariantCulture)
					+ " bias=" + bias.ToString("0.###", CultureInfo.InvariantCulture)
					+ " apply=" + apply
					+ " applyFlag=" + applyFlag
					+ " ready=" + readyForApply
					+ " after=" + __result.ToString(CultureInfo.InvariantCulture));
			}
		}
		catch (Exception ex)
		{
			(_log ?? Plugin.LogSource)?.LogWarning("HoMM3 adventure AI weight bridge score postfix failed: " + ex.Message);
		}
	}

	private static bool TryGetBiasForCandidate(object task, out float bias)
	{
		bias = 1f;
		Dictionary<long, float> map;
		lock (BiasGate)
		{
			map = _biases;
		}
		if (map == null || map.Count == 0 || task == null)
			return false;

		var ids = new List<int>();
		foreach (var hint in GameSymbols.AdventureAiDecision.TaskTargetIdFieldHints)
		{
			var v = Homm3AdventureLookaheadState.ReadMember(task, new[] { hint });
			if (v == null)
				continue;
			try { ids.Add(Convert.ToInt32(v, CultureInfo.InvariantCulture)); }
			catch { }
		}

		var worldObj = Homm3AdventureLookaheadState.ReadMember(
			task,
			GameSymbols.AdventureAiDecision.TaskTargetWorldObjectFieldHints);
		if (worldObj != null)
		{
			var dataObj = Homm3AdventureLookaheadState.ReadMember(
				worldObj,
				GameSymbols.AdventureAiDecision.WorldObjectDataObjectFieldHints);
			if (dataObj != null)
			{
				var id = Homm3AdventureLookaheadState.ReadInt(
					dataObj,
					GameSymbols.AdventureAiDecision.DataObjectIdFieldHints,
					0);
				if (id != 0)
					ids.Add(id);
			}
		}

		for (var i = 0; i < ids.Count; i++)
		{
			var id = ids[i];
			if (id == 0)
				continue;
			if (map.TryGetValue(BiasKey(AdventureSimTargetKind.Unknown, id), out bias))
				return true;
			if (map.TryGetValue(BiasKey(AdventureSimTargetKind.Neutral, id), out bias))
				return true;
			if (map.TryGetValue(BiasKey(AdventureSimTargetKind.Town, id), out bias))
				return true;
			if (map.TryGetValue(BiasKey(AdventureSimTargetKind.Hero, id), out bias))
				return true;
			if (map.TryGetValue(BiasKey(AdventureSimTargetKind.Pickup, id), out bias))
				return true;
			if (map.TryGetValue(BiasKey(AdventureSimTargetKind.Node, id), out bias))
				return true;
		}
		return false;
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
			error = "locator unresolved";
			return false;
		}
		var sideRuntime = Homm3AdventureLookaheadState.ReadMember(
			locator,
			GameSymbols.AdventureAiDecision.SideRuntimeOnLocatorHints);
		if (sideRuntime == null)
		{
			error = "side runtime unresolved";
			return false;
		}
		liveSide = Homm3AdventureLookaheadState.ReadMember(
			sideRuntime,
			GameSymbols.AdventureAiDecision.SideOnRuntimeHints);
		if (liveSide == null)
		{
			error = "Side unresolved";
			return false;
		}
		return true;
	}

	private static void LogDay(string message)
	{
		if (_logged >= LogCap)
			return;
		_logged++;
		(_log ?? Plugin.LogSource)?.LogInfo("HoMM3 adventure AI weight bridge day " + message);
	}

	private static string FormatMethod(MethodInfo method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
