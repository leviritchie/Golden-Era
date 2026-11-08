using System;
using System.Globalization;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Cursors;

namespace OfflineUnlockMod;

/// <summary>
/// Owned cityFactory presentation: adventure-map hover keeps applying ECursor.PlayerInteractCity
/// (and HeroInteractCity*) every frame while sessionWorld stays loaded under the town.
/// Live-positive 2026-07-31: forcing Normal succeeds, then PlayerInteractCity rewrites within ~30 frames.
/// One choke-point: Prefix cursor-stack ECursor apply while cityFactory is the active Unity scene;
/// on first suppress (and on presentation activate) force Normal so the software texture catches up.
/// Proof: source/static + deploy; user-visible town cursor pending live sample after deploy.
/// </summary>
internal static class Homm3OwnedCityMapCursorSuppress
{
	internal const string ActiveArchitecture = "owned_city_map_city_interact_cursor_suppress";
	internal const string DiagnosticFlag = "homm3_owned_city_map_cursor_suppress_probe.flag";

	private const string LogPrefix = "HOMM3_OWNED_CITY_MAP_CURSOR";
	private const BindingFlags MemberFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

	private static bool _registered;
	private static ManualLogSource _log;
	private static bool _suppressActive;
	private static bool _forcedNormalForSession;
	private static int _loggedSuppress;
	private static int _prefixDepth;

	private static MethodInfo _cursorStackSingleton;
	private static MethodInfo _cursorStackApply;
	private static MethodInfo _cursorManagerSingleton;
	private static MethodInfo _cursorManagerSet;

	internal static void RegisterRequired(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException(LogPrefix + " Harmony was not initialized.");
		_log = log;

		if (!TryResolveCursorStack(out var reason))
			throw new InvalidOperationException(LogPrefix + " cursor stack unresolved: " + reason);
		if (!TryResolveCursorManagerSet(out reason))
			throw new InvalidOperationException(LogPrefix + " cursor manager set unresolved: " + reason);

		if (_cursorStackApply == null)
			throw new InvalidOperationException(LogPrefix + " no ECursor apply surface resolved.");

		var prefix = new HarmonyMethod(typeof(Homm3OwnedCityMapCursorSuppress), nameof(PrefixCursorStackApply));
		harmony.Patch(_cursorStackApply, prefix: prefix);

		_registered = true;
		log?.LogInfo(LogPrefix + " registered architecture=" + ActiveArchitecture
			+ " stackApply=" + (_cursorStackApply.DeclaringType?.FullName ?? "?")
			+ "." + _cursorStackApply.Name
			+ " managerSet=" + (_cursorManagerSet?.DeclaringType?.FullName ?? "?")
			+ "." + (_cursorManagerSet?.Name ?? "?") + ".");
	}

	/// <summary>
	/// Called when owned cityFactory presentation roots are activated. Forces Normal once so the
	/// enter-city texture does not linger until the first suppressed apply.
	/// </summary>
	internal static void NotifyOwnedCityPresentationActive()
	{
		if (!_registered)
			return;
		_suppressActive = true;
		if (_forcedNormalForSession)
			return;
		if (TryForceNormal(out var detail))
		{
			_forcedNormalForSession = true;
			_log?.LogInfo(LogPrefix + " forced Normal on owned-city activate (" + detail + ").");
		}
		else
			_log?.LogWarning(LogPrefix + " failed to force Normal on owned-city activate: " + detail);
	}

	internal static void NotifyOwnedCityPresentationSuspended(string reason)
	{
		if (!_suppressActive && !_forcedNormalForSession)
			return;
		_suppressActive = false;
		_forcedNormalForSession = false;
		_log?.LogInfo(LogPrefix + " suppress cleared (" + (reason ?? "unspecified") + ").");
	}

	private static bool IsMapCityInteractCursor(ECursor cursor)
	{
		return cursor == ECursor.PlayerInteractCity
			|| cursor == ECursor.HeroInteractCity
			|| cursor == ECursor.HeroInteractCityRed
			|| cursor == ECursor.HeroInteractCityGray;
	}

	private static bool PrefixCursorStackApply(ref ECursor __0)
	{
		// SceneManager and cursor-manager set can re-enter stack apply; never call them from inside this prefix.
		if (_prefixDepth > 0)
			return true;
		if (!_registered || !_suppressActive)
			return true;
		if (!IsMapCityInteractCursor(__0))
			return true;

		_prefixDepth++;
		try
		{
			LogSuppress(__0);
			if (!_forcedNormalForSession && TryForceNormal(out _))
				_forcedNormalForSession = true;
			return false;
		}
		finally
		{
			_prefixDepth--;
		}
	}

	private static bool TryResolveCursorStack(out string reason)
	{
		reason = null;
		_cursorStackApply = null;
		Type type = null;
		foreach (var hint in GameSymbols.HomecomingWaterPresentation.CursorStackTypeHints)
		{
			type = AccessTools.TypeByName(hint);
			if (type != null)
				break;
		}
		if (type == null)
		{
			reason = "cursor_stack_type_unresolved";
			return false;
		}

		_cursorStackSingleton = GameMember.FindFirstMethodByNames(
			type,
			Type.EmptyTypes,
			GameSymbols.HomecomingWaterPresentation.CursorStackSingleton);
		if (_cursorStackSingleton == null || !_cursorStackSingleton.IsStatic)
		{
			reason = "cursor_stack_singleton_unresolved";
			return false;
		}

		MethodInfo[] methods;
		try { methods = type.GetMethods(MemberFlags | BindingFlags.DeclaredOnly); }
		catch (Exception ex)
		{
			reason = "cursor_stack_methods_unreadable " + ex.Message;
			return false;
		}

		MethodInfo best = null;
		var bestRank = int.MaxValue;
		foreach (var method in methods)
		{
			if (method == null || method.IsStatic || method.ReturnType != typeof(bool))
				continue;
			ParameterInfo[] ps;
			try { ps = method.GetParameters(); }
			catch { continue; }
			if (ps.Length < 1 || ps.Length > 2)
				continue;
			if (ps[0].ParameterType != typeof(ECursor))
				continue;
			if (ps.Length == 2 && ps[1].ParameterType != typeof(int))
				continue;
			var rank = Array.IndexOf(GameSymbols.HomecomingWaterPresentation.CursorStackApplyMethodHints, method.Name);
			if (rank < 0)
				rank = 1000;
			if (rank < bestRank)
			{
				bestRank = rank;
				best = method;
			}
		}

		if (best == null)
		{
			reason = "cursor_stack_apply_unresolved";
			return false;
		}
		_cursorStackApply = best;
		return true;
	}

	private static bool TryResolveCursorManagerSet(out string reason)
	{
		reason = null;
		Type type = null;
		foreach (var hint in GameSymbols.HomecomingWaterPresentation.CursorManagerTypeHints)
		{
			type = AccessTools.TypeByName(hint);
			if (type != null)
				break;
		}
		if (type == null)
		{
			reason = "cursor_manager_type_unresolved";
			return false;
		}

		_cursorManagerSingleton = GameMember.FindFirstMethodByNames(
			type,
			Type.EmptyTypes,
			GameSymbols.HomecomingWaterPresentation.CursorManagerSingleton);
		if (_cursorManagerSingleton == null || !_cursorManagerSingleton.IsStatic)
		{
			reason = "cursor_manager_singleton_unresolved";
			return false;
		}

		MethodInfo best = null;
		var bestRank = int.MaxValue;
		MethodInfo[] methods;
		try { methods = type.GetMethods(MemberFlags | BindingFlags.DeclaredOnly); }
		catch (Exception ex)
		{
			reason = "cursor_manager_methods_unreadable " + ex.Message;
			return false;
		}
		foreach (var method in methods)
		{
			if (method == null || method.IsStatic || method.ReturnType != typeof(void))
				continue;
			ParameterInfo[] ps;
			try { ps = method.GetParameters(); }
			catch { continue; }
			if (ps.Length != 2)
				continue;
			if (ps[0].ParameterType != typeof(ECursor) || ps[1].ParameterType != typeof(int))
				continue;
			var rank = Array.IndexOf(GameSymbols.HomecomingWaterPresentation.CursorSetMethodHints, method.Name);
			if (rank < 0)
				rank = 1000;
			if (rank < bestRank)
			{
				bestRank = rank;
				best = method;
			}
		}
		if (best == null)
		{
			reason = "cursor_manager_set_unresolved";
			return false;
		}
		_cursorManagerSet = best;
		return true;
	}

	private static bool TryForceNormal(out string detail)
	{
		detail = null;
		if (_cursorManagerSingleton == null || _cursorManagerSet == null)
		{
			detail = "manager_unresolved";
			return false;
		}
		object manager;
		try { manager = _cursorManagerSingleton.Invoke(null, Array.Empty<object>()); }
		catch (Exception ex)
		{
			detail = "singleton_invoke " + ex.GetType().Name;
			return false;
		}
		if (manager == null)
		{
			detail = "singleton_null";
			return false;
		}
		try
		{
			_cursorManagerSet.Invoke(manager, new object[] { ECursor.Normal, 0 });
			detail = "set=" + _cursorManagerSet.Name;
			return true;
		}
		catch (Exception ex)
		{
			detail = "set_invoke " + ex.GetType().Name
				+ (ex.InnerException != null ? (":" + ex.InnerException.GetType().Name) : "");
			return false;
		}
	}

	private static void LogSuppress(ECursor cursor)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag) && _loggedSuppress >= 8)
			return;
		_loggedSuppress++;
		_log?.LogInfo(LogPrefix + " suppress " + cursor
			+ " count=" + _loggedSuppress.ToString(CultureInfo.InvariantCulture));
	}
}
