using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.Runtime;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Suppresses <see cref="System.Collections.Generic.KeyNotFoundException"/> thrown in
/// <c>BhSelectedUnitHud.bdon(object, BattleEventArgs)</c> when custom unit SIDs (e.g. <c>h3_roc</c>,
/// <c>h3_orc</c>) are not present in the vanilla portrait/config dictionary the method indexes directly.
/// Without this suppressor the exception propagates through the battle update loop and freezes the game.
/// </summary>
internal static class Homm3ImportBhSelectedUnitHudFix
{
	private static bool _patched;
	private static int _loggedSuppressed;
	private static int _loggedPortraitReplace;
	private static int _loggedHudDiag;
	private static int _loggedScenePortraitReplace;
	private static int _loggedSceneAbilityCleanup;
	private static int _loggedDictionarySeed;
	private static int _loggedControlsRecovery;
	private static int _loggedDirectControlsBind;
	private static int _loggedControlsSelection;
	private static int _loggedReleaseAbilityClick;
	private static int _loggedReleaseAbilityClickFallback;
	private static int _loggedReleaseHotkey;
	private static int _loggedReleaseActionBarLookup;
	private static int _releaseAbilityClickDepth;
	private static BhUnitAbilityView _releaseAbilityClickView;
	private static bool _releaseAbilityClickForwarded;
	private static int _loggedReleaseNoAbilityCleanup;
	private static int _loggedReleaseAlias;
	private static int _loggedReleaseConfigAbilityFallback;
	private static int _loggedReleaseActionBarPrewarm;
	private static int _loggedReleaseActionBarPrewarmIconMiss;
	private static int _loggedReleaseManagerInit;
	private static int _loggedNativeSidFieldRead;
	private static int _loggedNativeManagerFieldTypeMiss;
	private static int _loggedDirectControlsBindInfo;
	private static bool _hotkeyFallbackRegistered;
	private static bool _hotkeyFallbackAttached;
	private static string _lastBoundControlsSid;
	private static BhUnitControlsView _lastBoundControlsView;
	private static object _lastBoundControlsAbilities;
	private static string _lastBoundReleaseControlsSid;
	private static BhUnitControlsView _lastBoundReleaseControlsView;
	private static Array _lastBoundReleaseControlsAbilities;
	private static long _lastBoundReleaseControlsUnitKey;
	private static string _lastNoReleaseControlsSid;
	private static long _lastNoReleaseControlsUnitKey;
	private static string _lastTurnViewUnitSid;
	private static Unit _lastTurnViewUnit;
	private static long _lastTurnViewUnitKey;
	private static readonly Dictionary<long, object> ReleaseAbilityByView = new();
	private static readonly Dictionary<int, bool> AbilityViewEnabledByInstanceId = new();
	private static readonly Dictionary<string, Array> PrewarmedReleaseActionBarAbilitiesBySid = new(StringComparer.OrdinalIgnoreCase);
	private static readonly HashSet<string> NoReleaseActionBarSids = new(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, MethodInfo> ReleaseConfigTableTryGetMethods = new(StringComparer.Ordinal);
	private static readonly HashSet<MethodInfo> FailedReleaseAbilityWrapperInitMethods = new();
	private static readonly List<Image> ScenePortraitTargets = new();
	private static readonly List<GameObject> SceneAbilityTargets = new();
	private const string SelectedBattleActionBarAbilityPathFragment = "BattleBottomHudCanvas/BottomGroupPanel/UNITPart/UNIT ABILITIES/";
	private static Type _releaseConfigRootType;
	private static object _releaseConfigRoot;
	private static object _releaseUnitLogicConfigTable;
	private static object _releaseUnitViewConfigTable;

	internal static ReleaseActionBarPrewarmResult PrewarmReleaseActionBarsForSids(IEnumerable<string> sids, ManualLogSource log)
	{
		if (!IsReleaseConfigActionBarFallbackEnabled())
			return default;
		if (sids == null)
			return default;
		var warmed = 0;
		var warmedIcons = 0;
		var missedIcons = 0;
		var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
		foreach (var rawSid in sids)
		{
			var sid = rawSid?.Trim();
			if (string.IsNullOrWhiteSpace(sid) || !seen.Add(sid))
				continue;
			if (!Homm3CustomFactionRegistry.IsCustomUnitSid(sid))
				continue;
			try
			{
				if (!TryResolveReleaseUnitConfigsBySid(sid, out var logicConfig, out var viewConfig))
					continue;
				var abilities = BuildReleaseActionBarAbilitiesFromConfigs(logicConfig, viewConfig, sid);
				if (abilities == null || abilities.Length <= 0)
				{
					CacheNoReleaseActionBarSid(sid);
					continue;
				}
				PrewarmedReleaseActionBarAbilitiesBySid[sid] = abilities;
				NoReleaseActionBarSids.Remove(sid);
				for (var i = 0; i < abilities.Length; i++)
				{
					var abilityView = GetReleaseAbilityView(abilities.GetValue(i));
					if (Homm3CustomUiIconHook.PrewarmBattleAbilityIconForConfig(abilityView, out var iconKey))
					{
						warmedIcons++;
						continue;
					}
					missedIcons++;
					if (IsDiagnosticEnabled() && _loggedReleaseActionBarPrewarmIconMiss < 12)
					{
						_loggedReleaseActionBarPrewarmIconMiss++;
						log?.LogInfo("Homm3Import selected-unit HUD action-bar prewarm missed icon sid='" + sid + "' key='" + (iconKey ?? "?") + "'.");
					}
				}
				warmed++;
			}
			catch (Exception ex)
			{
				if (_loggedReleaseActionBarPrewarm < 8)
				{
					_loggedReleaseActionBarPrewarm++;
					log?.LogWarning("Homm3Import selected-unit HUD action-bar prewarm failed for sid='" + sid + "': " + ex.Message);
				}
			}
		}
		return new ReleaseActionBarPrewarmResult(warmed, warmedIcons, missedIcons);
	}
	private static bool _scenePortraitTargetsResolved;
	private static int _scenePortraitScanAttempts;
	private static bool _sceneAbilityTargetsScanned;
	private const int MaxScenePortraitScanAttempts = 3;
	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched || h == null)
			return;
		_patched = true;
		log?.LogInfo("Homm3Import BhSelectedUnitHud legacy hook skipped: stale pre-release selected-HUD wrapper path is quarantined.");
	}

	internal static void TryRegisterRelease(Harmony h, ManualLogSource log)
	{
		RegisterRelease(h, log, required: false);
	}

	internal static void RegisterReleaseRequired(Harmony h, ManualLogSource log)
	{
		RegisterRelease(h, log, required: true);
	}

	private static void RegisterRelease(Harmony h, ManualLogSource log, bool required)
	{
		if (_patched || h == null)
		{
			if (h == null && required)
			{
				throw new InvalidOperationException("Required HoMM3 release selected-unit HUD guard cannot register without a Harmony instance.");
			}
			return;
		}
		try
		{
			var eventBinds = FindMethodsByNamesAndSecondParameter(typeof(BhSelectedUnitHud), GameSymbols.SelectedUnitHud.HudEventBind.NameHints, typeof(BattleEventArgs));
			if (eventBinds.Count == 0)
			{
				var message = "Homm3Import: BhSelectedUnitHud.begr/beet event bind not found; release selected-unit HUD guard inactive.";
				if (required)
				{
					throw new MissingMethodException(message);
				}
				log?.LogWarning(message);
				return;
			}

			var directBinds = FindMethodsByNamesAndSecondParameter(typeof(BhSelectedUnitHud), GameSymbols.SelectedUnitHud.HudDirectBind.NameHints, typeof(Unit));
			if (directBinds.Count == 0)
			{
				var message = "Homm3Import: BhSelectedUnitHud.begs/begt direct unit bind not found; release selected-unit HUD guard incomplete.";
				if (required)
				{
					throw new MissingMethodException(message);
				}
				log?.LogWarning(message);
			}

			if (required)
				ValidateRequiredReleaseActionBarSurface(log);

			foreach (var eventBind in eventBinds)
			{
				h.Patch(eventBind,
					prefix: new HarmonyMethod(typeof(Homm3ImportBhSelectedUnitHudFix), nameof(PrefixBeetRelease)),
					postfix: new HarmonyMethod(typeof(Homm3ImportBhSelectedUnitHudFix), nameof(PostfixBeetRelease)),
					finalizer: new HarmonyMethod(typeof(Homm3ImportBhSelectedUnitHudFix), nameof(FinalizerBeetRelease)));
			}
			foreach (var directBind in directBinds)
			{
				h.Patch(directBind,
					prefix: new HarmonyMethod(typeof(Homm3ImportBhSelectedUnitHudFix), nameof(PrefixBegsRelease)),
					postfix: new HarmonyMethod(typeof(Homm3ImportBhSelectedUnitHudFix), nameof(PostfixBegsRelease)),
					finalizer: new HarmonyMethod(typeof(Homm3ImportBhSelectedUnitHudFix), nameof(FinalizerBegsRelease)));
			}
			PatchReleaseAbilityClickDiagnostics(h, log);
			PatchReleaseHotkeyHandling(h, log);
			WarmReleaseActionBarResolverForCustomUnits(log);
			_patched = true;
			log?.LogInfo("Homm3Import: Harmony prefix/postfix/finalizer on release BhSelectedUnitHud event binds [" + FormatMethodNames(eventBinds) + "] and direct binds [" + FormatMethodNames(directBinds) + "] (custom SID HUD guard).");
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3Import release BhSelectedUnitHud.beet fix failed: " + ex);
			if (required)
			{
				throw new InvalidOperationException("Required HoMM3 release selected-unit HUD guard registration failed.", ex);
			}
		}
	}

	private static bool IsReleaseAbilityManager(object value)
	{
		var managerType = GameInteropTypes.ReleaseAbilityManagerType;
		return value != null && managerType != null && GameInteropTypes.TypesMatch(value.GetType(), managerType);
	}

	private static bool IsReleaseAbilityWrapper(object value)
	{
		var wrapperType = GameInteropTypes.ReleaseAbilityWrapperType;
		return value != null && wrapperType != null && GameInteropTypes.TypesMatch(value.GetType(), wrapperType);
	}

	private static bool IsReleaseAbilityArrayParameterType(Type parameterType, Type wrapperType)
	{
		if (parameterType == null || wrapperType == null)
			return false;
		if (parameterType.IsArray)
			return GameInteropTypes.TypesMatch(parameterType.GetElementType(), wrapperType);
		return GameInteropTypes.IsReleaseAbilityArrayReturnType(parameterType, wrapperType);
	}

	private static bool IsReleaseAbilityWrapperParameterType(Type parameterType, Type wrapperType)
	{
		return parameterType != null && wrapperType != null && GameInteropTypes.TypesMatch(parameterType, wrapperType);
	}

	private static int GetReleaseAbilityArrayLength(Array abilities) => abilities?.Length ?? 0;

	private static object GetReleaseAbilityArrayElement(Array abilities, int index)
	{
		if (abilities == null || index < 0 || index >= abilities.Length)
			return null;
		return abilities.GetValue(index);
	}

	private static Array CoerceReleaseAbilityArray(object value)
	{
		if (value == null)
			return null;
		if (value is Array array)
			return array;
		try
		{
			var valueType = value.GetType();
			var lengthProp = valueType.GetProperty("Length");
			if (lengthProp == null)
				return null;
			var length = (int)lengthProp.GetValue(value);
			if (length <= 0)
				return Array.Empty<object>();
			var getItem = valueType.GetMethod("get_Item", new[] { typeof(int) });
			if (getItem == null)
				return null;
			var result = new object[length];
			for (var i = 0; i < length; i++)
				result[i] = getItem.Invoke(value, new object[] { i });
			return result;
		}
		catch
		{
			return null;
		}
	}

	private static object CoerceReleaseAbilityArrayArgument(Array source, Type targetType)
	{
		if (source == null)
			return null;
		if (targetType == null)
			return source;
		if (targetType.IsArray)
		{
			var elementType = targetType.GetElementType() ?? typeof(object);
			var converted = Array.CreateInstance(elementType, source.Length);
			for (var i = 0; i < source.Length; i++)
				converted.SetValue(CoerceReleaseAbilityWrapperArgument(source.GetValue(i), elementType), i);
			return converted;
		}
		if (targetType.Name.StartsWith("Il2CppReferenceArray", StringComparison.Ordinal))
		{
			var elementType = targetType.GetGenericArguments().Length == 1
				? targetType.GetGenericArguments()[0]
				: typeof(object);
			var ctor = targetType.GetConstructor(new[] { typeof(int) });
			if (ctor != null)
			{
				var il2cppArray = ctor.Invoke(new object[] { source.Length });
				var setItem = targetType.GetMethod("set_Item");
				if (setItem != null)
				{
					for (var i = 0; i < source.Length; i++)
						setItem.Invoke(il2cppArray, new[] { i, CoerceReleaseAbilityWrapperArgument(source.GetValue(i), elementType) });
				}
				return il2cppArray;
			}
		}
		return source;
	}

	private static object CoerceReleaseAbilityWrapperArgument(object source, Type targetType)
	{
		if (source == null || targetType == null)
			return source;
		if (targetType.IsInstanceOfType(source))
			return source;
		if (source is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero)
		{
			var converted = CreateIl2CppObjectWrapper(il2Cpp.Pointer, targetType);
			if (converted != null && targetType.IsInstanceOfType(converted))
				return converted;
		}
		return source;
	}

	private static Array BuildReleaseAbilityArray(IList<object> abilities)
	{
		if (abilities == null || abilities.Count <= 0)
			return null;
		var result = new object[abilities.Count];
		for (var i = 0; i < abilities.Count; i++)
			result[i] = abilities[i];
		return result;
	}

	private static List<MethodInfo> FindMethodsByNamesAndSecondParameter(Type type, string[] names, Type secondParameterType)
	{
		var matches = new List<MethodInfo>();
		if (type == null || secondParameterType == null)
			return matches;
		var seen = new HashSet<MethodInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		MethodInfo[] declaredMethods;
		try { declaredMethods = type.GetMethods(flags); }
		catch { declaredMethods = Array.Empty<MethodInfo>(); }

		if (names != null)
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				foreach (var method in declaredMethods)
				{
					if (!string.Equals(method.Name, name, StringComparison.Ordinal))
						continue;
					if (!MatchesSecondParameterShape(method, secondParameterType))
						continue;
					if (seen.Add(method))
						matches.Add(method);
				}
			}
		}

		if (matches.Count > 0)
			return matches;

		foreach (var method in declaredMethods)
		{
			if (method.IsStatic)
				continue;
			if (!MatchesSecondParameterShape(method, secondParameterType))
				continue;
			if (seen.Add(method))
				matches.Add(method);
		}

		return matches;
	}

	private static bool MatchesSecondParameterShape(MethodInfo method, Type secondParameterType)
	{
		if (method == null || secondParameterType == null)
			return false;
		var parameters = method.GetParameters();
		if (parameters.Length != 2 || !ParameterTypesMatch(parameters[1].ParameterType, secondParameterType))
			return false;
		if (string.Equals(secondParameterType.Name, "BattleEventArgs", StringComparison.Ordinal))
		{
			var first = parameters[0].ParameterType;
			return first == typeof(object)
			       || string.Equals(first?.Name, "Object", StringComparison.Ordinal)
			       || (first != null && !first.IsValueType);
		}
		if (string.Equals(secondParameterType.Name, "Unit", StringComparison.Ordinal))
		{
			var first = parameters[0].ParameterType;
			return first == typeof(bool) || string.Equals(first?.Name, "Boolean", StringComparison.Ordinal);
		}
		return true;
	}

	private static bool ParameterTypesMatch(Type actual, Type expected)
	{
		if (actual == null || expected == null)
			return actual == expected;
		if (actual == expected)
			return true;
		return string.Equals(actual.FullName, expected.FullName, StringComparison.Ordinal)
		       || string.Equals(actual.Name, expected.Name, StringComparison.Ordinal);
	}

	private static string FormatMethodNames(List<MethodInfo> methods)
	{
		if (methods == null || methods.Count == 0)
			return "none";
		var names = new List<string>();
		for (var i = 0; i < methods.Count; i++)
			names.Add(methods[i]?.Name ?? "?");
		return string.Join(",", names);
	}

	private static MethodInfo FindMethodByNameAndArity(Type type, string methodName, int parameterCount)
	{
		if (type == null)
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
		{
			if (!string.Equals(method.Name, methodName, StringComparison.Ordinal))
				continue;
			if (method.GetParameters().Length == parameterCount)
				return method;
		}
		return null;
	}

	private static MethodInfo FindFirstMethodByNames(Type type, int parameterCount, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var method = FindMethodByNameAndArity(type, names[i], parameterCount);
			if (method != null)
				return method;
		}
		return null;
	}

	private static MethodInfo FindFirstMethodByNamesAndFirstParameterType(Type type, GameSymbols.MethodSymbol symbol, Type firstParameterType)
	{
		if (type == null || firstParameterType == null || symbol.NameHints == null)
			return null;
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
		for (var i = 0; i < symbol.NameHints.Length; i++)
		{
			var name = symbol.NameHints[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in type.GetMethods(flags))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length > 0 && parameters[0].ParameterType == firstParameterType)
					return method;
			}
		}
		return null;
	}

	private static void PatchReleaseAbilityClickDiagnostics(Harmony h, ManualLogSource log)
	{
		var clicked = FindMethodByNameAndArity(typeof(BhUnitAbilityView), "OnClicked", 0);
		if (clicked != null)
			h.Patch(clicked,
				prefix: new HarmonyMethod(typeof(Homm3ImportBhSelectedUnitHudFix), nameof(PrefixReleaseAbilityClicked)),
				postfix: new HarmonyMethod(typeof(Homm3ImportBhSelectedUnitHudFix), nameof(PostfixReleaseAbilityClicked)));

		var controlsClickMethods = FindReleaseControlsClickMethods(typeof(BhUnitControlsView), log);
		for (var i = 0; i < controlsClickMethods.Count; i++)
		{
			var controlsClick = controlsClickMethods[i];
			h.Patch(controlsClick,
				prefix: new HarmonyMethod(typeof(Homm3ImportBhSelectedUnitHudFix), nameof(PrefixReleaseControlsAbilityClicked)),
				postfix: new HarmonyMethod(typeof(Homm3ImportBhSelectedUnitHudFix), nameof(PostfixReleaseControlsAbilityClicked)));
		}

		if (clicked != null || controlsClickMethods.Count > 0)
			log?.LogInfo("Homm3Import: release ability click handling patched clicked=" + (clicked != null) + " controls=" + controlsClickMethods.Count + ".");
	}

	private static List<MethodInfo> FindReleaseControlsClickMethods(Type type, ManualLogSource log = null)
	{
		var result = new List<MethodInfo>();
		if (type == null)
			return result;

		var hints = GameSymbols.SelectedUnitHud.ControlsClick.NameHints ?? Array.Empty<string>();
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var methods = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			for (var j = 0; j < methods.Length; j++)
			{
				var method = methods[j];
				if (!string.Equals(method.Name, hint, StringComparison.Ordinal))
					continue;
				if (!IsReleaseControlsClickCandidate(method))
					continue;
				if (!result.Contains(method))
					result.Add(method);
			}
		}
		if (result.Count > 0)
		{
			log?.LogInfo("Homm3Import: release ability click controls exact candidates: " + DescribeMethods(result) + ".");
			return result;
		}

		MethodInfo unique = null;
		var candidates = new List<string>();
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (!IsReleaseControlsClickCandidate(method))
				continue;
			candidates.Add(method.Name);
			if (unique == null)
				unique = method;
			else
				unique = null;
		}

		if (candidates.Count == 1)
		{
			log?.LogInfo("Homm3Import: release ability click controls method resolved by unique shape " + candidates[0] + ".");
			result.Add(unique);
			return result;
		}
		if (candidates.Count > 1)
		{
			log?.LogWarning("Homm3Import: release ability click controls method ambiguous by shape: " + string.Join(",", candidates));
		}
		return result;
	}

	private static bool IsReleaseControlsClickCandidate(MethodInfo method)
	{
		if (method == null || method.IsSpecialName || method.ReturnType != typeof(void))
			return false;
		var parameters = method.GetParameters();
		return parameters.Length == 1 && ParameterTypesMatch(parameters[0].ParameterType, typeof(BhUnitAbilityView));
	}

	private static BhUnitControlsView TryGetReleaseControlsViewForAbilityClick(BhUnitAbilityView view)
	{
		try
		{
			var direct = TryGetMemberValue(view, "controlsView") as BhUnitControlsView;
			if (ControlsViewOwnsReleaseAbilityView(direct, view))
				return direct;

			var huds = Resources.FindObjectsOfTypeAll<BhSelectedUnitHud>();
			for (var i = 0; i < huds.Length; i++)
			{
				var hud = huds[i];
				if (hud == null || hud.controlsView == null)
					continue;
				if (!hud.gameObject.activeInHierarchy && !string.Equals(hud.name, "UNIT SELECTION", StringComparison.Ordinal))
					continue;
				if (ControlsViewOwnsReleaseAbilityView(hud.controlsView, view))
					return hud.controlsView;
			}
		}
		catch
		{
		}
		return null;
	}

	private static bool ControlsViewOwnsReleaseAbilityView(BhUnitControlsView controlsView, BhUnitAbilityView view)
	{
		if (controlsView == null || view == null)
			return false;
		try
		{
			var views = controlsView.abilities;
			if (views == null)
				return ReferenceEquals(TryGetMemberValue(view, "controlsView") as BhUnitControlsView, controlsView);
			var viewKey = GetIl2CppObjectKey(view);
			for (var i = 0; i < views.Count; i++)
			{
				var candidate = views[i];
				if (ReferenceEquals(candidate, view))
					return true;
				var candidateKey = GetIl2CppObjectKey(candidate);
				if (viewKey != 0 && candidateKey != 0 && viewKey == candidateKey)
					return true;
			}
		}
		catch
		{
		}
		return false;
	}

	private static string DescribeMethods(List<MethodInfo> methods)
	{
		if (methods == null || methods.Count == 0)
			return "(none)";
		var names = new List<string>();
		for (var i = 0; i < methods.Count; i++)
			names.Add(methods[i]?.Name ?? "(null)");
		return string.Join(",", names);
	}

	private static void PatchReleaseHotkeyHandling(Harmony h, ManualLogSource log)
	{
		var controlsHotkey = FindReleaseControlsHotkeyMethod(typeof(BhUnitControlsView));
		if (controlsHotkey == null)
		{
			log?.LogWarning("Homm3Import: release ability hotkey handler not found; custom ability number keys inactive.");
			return;
		}

		h.Patch(controlsHotkey,
			prefix: new HarmonyMethod(typeof(Homm3ImportBhSelectedUnitHudFix), nameof(PrefixReleaseControlsViewHotkey)));
		log?.LogInfo("Homm3Import: release ability hotkey handling patched " + controlsHotkey.Name + ".");
	}

	private static void PrefixReleaseAbilityClicked(BhUnitAbilityView __instance)
	{
		_releaseAbilityClickDepth++;
		_releaseAbilityClickView = __instance;
		_releaseAbilityClickForwarded = false;
		LogReleaseAbilityClick("view.OnClicked", __instance, null);
	}

	private static void PostfixReleaseAbilityClicked(BhUnitAbilityView __instance)
	{
		try
		{
			if (_releaseAbilityClickDepth > 0
			    && !_releaseAbilityClickForwarded
			    && SameIl2CppObject(_releaseAbilityClickView, __instance)
			    && IsReleaseActionBarAbilityView(__instance))
			{
				var ability = GetReleaseAbility(__instance);
				var controlsView = TryGetReleaseControlsViewForAbilityClick(__instance);
				if (ability != null && controlsView != null)
				{
					var selected = IsReleaseControlAbilitySelected(controlsView, __instance);
					InvokeReleaseControlsSelect(controlsView, selected ? null : ability);
					if (IsDiagnosticEnabled() && _loggedReleaseAbilityClickFallback < 20)
					{
						_loggedReleaseAbilityClickFallback++;
						Plugin.LogSource?.LogInfo(
							"Homm3Import release ability click fallback: "
							+ (selected ? "cleared " : "selected ")
							+ DescribeReleaseAbility(ability)
							+ " through native controls selection after OnClicked did not enter a state-changing controls click handler.");
					}
					return;
				}
				if (IsDiagnosticEnabled() && _loggedReleaseAbilityClickFallback < 20)
				{
					_loggedReleaseAbilityClickFallback++;
					Plugin.LogSource?.LogInfo(
						"Homm3Import release ability click native miss: OnClicked did not enter controls.begu for "
						+ DescribeReleaseAbility(ability)
						+ " controlsBound=" + DescribeReleaseControls(controlsView)
						+ ". No fallback was invoked.");
				}
			}
		}
		catch (Exception ex)
		{
			if (_loggedReleaseAbilityClickFallback < 20)
			{
				_loggedReleaseAbilityClickFallback++;
				Plugin.LogSource?.LogWarning("Homm3Import release ability click native miss diagnostic failed: " + ex.Message);
			}
		}
		finally
		{
			_releaseAbilityClickDepth = Math.Max(0, _releaseAbilityClickDepth - 1);
			if (_releaseAbilityClickDepth == 0)
			{
				_releaseAbilityClickView = null;
				_releaseAbilityClickForwarded = false;
			}
		}
	}

	private static void PrefixReleaseControlsAbilityClicked(BhUnitControlsView __instance, BhUnitAbilityView __0, ref bool __state)
	{
		if (_releaseAbilityClickDepth > 0 && SameIl2CppObject(_releaseAbilityClickView, __0))
			_releaseAbilityClickForwarded = true;
		__state = IsReleaseControlAbilitySelected(__instance, __0);
		LogReleaseAbilityClick("controls.begu", __0, __instance);
	}

	private static void PostfixReleaseControlsAbilityClicked(BhUnitControlsView __instance, BhUnitAbilityView __0, bool __state)
	{
		try
		{
			if (__instance == null || __0 == null || !IsReleaseActionBarAbilityView(__0, __instance))
				return;
			var ability = GetReleaseAbility(__0);
			if (ability == null)
				return;
			if (__state)
			{
				InvokeReleaseControlsSelect(__instance, null);
				LogReleaseAbilityClick("controls.begz-clear", __0, __instance);
				return;
			}
			var selectedView = GetReleaseSelectedAbilityView(__instance);
			var selected = GetReleaseAbility(selectedView);
			if (SameReleaseAbility(selected, ability))
				return;
			InvokeReleaseControlsSelect(__instance, ability);
			LogReleaseAbilityClick("controls.begz-sync", __0, __instance);
		}
		catch (Exception ex)
		{
			if (_loggedReleaseAbilityClickFallback < 20)
			{
				_loggedReleaseAbilityClickFallback++;
				Plugin.LogSource?.LogWarning("Homm3Import release ability native selection sync failed: " + ex.Message);
			}
		}
	}

	private static bool IsReleaseControlAbilitySelected(BhUnitControlsView controlsView, BhUnitAbilityView view)
	{
		try
		{
			if (controlsView == null || view == null)
				return false;
			var selectedView = GetReleaseSelectedAbilityView(controlsView);
			var selected = GetReleaseAbility(selectedView);
			var ability = GetReleaseAbility(view);
			return SameReleaseAbility(selected, ability);
		}
		catch
		{
			return false;
		}
	}

	private static void LogReleaseAbilityClick(string source, BhUnitAbilityView view, BhUnitControlsView controlsView)
	{
		if (!IsDiagnosticEnabled())
			return;
		if (_loggedReleaseAbilityClick >= 40)
			return;
		_loggedReleaseAbilityClick++;
		try
		{
			var ability = GetReleaseAbility(view);
			var viewConfig = GetReleaseAbilityView(ability);
			var logic = GetReleaseAbilityLogic(ability);
			var viewBase = TryGetMemberValue(view, "viewBase") as Component;
			var viewGo = view != null ? view.gameObject : null;
			var viewBaseGo = viewBase != null ? viewBase.gameObject : null;
			Plugin.LogSource?.LogInfo(
				"Homm3Import release ability click: source=" + source
				+ " view='" + (viewGo != null ? viewGo.name : "?") + "' active=" + (viewGo != null && viewGo.activeInHierarchy)
				+ " viewBase='" + (viewBaseGo != null ? viewBaseGo.name : "?") + "' viewBaseActive=" + (viewBaseGo != null && viewBaseGo.activeInHierarchy)
				+ " ability=" + DescribeReleaseAbility(ability)
				+ " viewName='" + SafeString(viewConfig?.name) + "'"
				+ " attackType='" + SafeString(logic?.attackType_) + "'"
				+ " canShow=" + (viewConfig != null && viewConfig.canShowOnUI)
				+ " viewState=" + DescribeReleaseAbilityViewState(view)
				+ " controlsBound=" + DescribeReleaseControls(controlsView ?? TryGetMemberValue(view, "controlsView") as BhUnitControlsView)
				+ ".");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogInfo("Homm3Import release ability click: source=" + source + " diag failed: " + ex.Message);
		}
	}

	private static bool IsReleaseActionBarAbilityView(BhUnitAbilityView view, BhUnitControlsView knownControlsView = null)
	{
		try
		{
			if (view == null || !view.gameObject.activeInHierarchy)
				return false;
			var ability = GetReleaseAbility(view);
			if (ability == null)
				return false;
			var controlsView = knownControlsView ?? TryGetMemberValue(view, "controlsView") as BhUnitControlsView;
			if (controlsView == null)
				return false;
			var views = controlsView.abilities;
			if (views == null)
				return IsRecoveredReleaseControlsContext(controlsView)
				       && IsReleaseAbilityViewClickReady(view)
				       && CanShowOnActionBar(ability)
				       && CachedReleaseControlsContainAbility(controlsView, ability);
			var viewKey = GetIl2CppObjectKey(view);
			for (var i = 0; i < views.Count; i++)
			{
				var candidate = views[i];
				if (ReferenceEquals(candidate, view))
					return true;
				var candidateKey = GetIl2CppObjectKey(candidate);
				if (viewKey != 0 && candidateKey != 0 && viewKey == candidateKey)
					return true;
			}
			if (IsRecoveredReleaseControlsContext(controlsView)
			    && IsReleaseAbilityViewClickReady(view)
			    && CanShowOnActionBar(ability)
			    && CachedReleaseControlsContainAbility(controlsView, ability))
				return true;
			return false;
		}
		catch
		{
			return false;
		}
	}

	private static bool PrefixBeetRelease(BhSelectedUnitHud __instance, BattleEventArgs __1, ref SelectedUnitHudCustomSidState __state, MethodBase __originalMethod)
	{
		__state = null;
		try
		{
			var unit = __1?.target;
			var sid = SafeExtractSidFieldOnly(unit);
			if (string.IsNullOrWhiteSpace(sid) || !Homm3CustomFactionRegistry.IsCustomUnitSid(sid))
			{
				ClearSelectedUnitPortraitOverride(__instance, sid, "release-beet-prefix-native");
				ClearCachedReleaseControls();
				return true;
			}

			ApplySelectedUnitPortrait(__instance, sid, "release-beet-prefix");
			var seeded = 0;
			__state = BeginReleaseCustomSidBind(unit, sid);
			if (IsDiagnosticEnabled() && _loggedReleaseAlias < 20)
			{
				_loggedReleaseAlias++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import selected-unit HUD release guard: preserved custom sid='" + sid
					+ "' for " + FormatMethod(__originalMethod)
					+ "; seeded=" + seeded
					+ "; donor identity aliasing disabled.");
			}
			return true;
		}
		catch (Exception ex)
		{
			if (_loggedReleaseAlias < 8)
			{
				_loggedReleaseAlias++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release custom-SID guard failed: " + ex.Message);
			}
			return true;
		}
	}
	private static bool PrefixBegsRelease(BhSelectedUnitHud __instance, Unit __1, ref SelectedUnitHudCustomSidState __state, MethodBase __originalMethod)
	{
		__state = null;
		try
		{
			var unit = __1;
			var sid = SafeExtractSidFieldOnly(unit);
			if (string.IsNullOrWhiteSpace(sid) || !Homm3CustomFactionRegistry.IsCustomUnitSid(sid))
			{
				ClearSelectedUnitPortraitOverride(__instance, sid, "release-begs-prefix-native");
				ClearCachedReleaseControls();
				return true;
			}

			ApplySelectedUnitPortrait(__instance, sid, "release-begs-prefix");
			var seeded = 0;
			__state = BeginReleaseCustomSidBind(unit, sid);
			if (IsDiagnosticEnabled() && _loggedReleaseAlias < 20)
			{
				_loggedReleaseAlias++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import selected-unit HUD direct release guard: preserved custom sid='" + sid
					+ "' for " + FormatMethod(__originalMethod)
					+ "; seeded=" + seeded
					+ "; donor identity aliasing disabled.");
			}
			return true;
		}
		catch (Exception ex)
		{
			if (_loggedReleaseAlias < 8)
			{
				_loggedReleaseAlias++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD direct release custom-SID guard failed: " + ex.Message);
			}
			return true;
		}
	}
	private static void PostfixBeetRelease(BhSelectedUnitHud __instance, BattleEventArgs __1, SelectedUnitHudCustomSidState __state)
	{
		var sid = __state?.OriginalSid ?? SafeExtractSid(__1?.target);
		ApplySelectedUnitPortrait(__instance, sid, "release-beet-postfix");
		RecoverUnitControlsRelease(__instance, __1?.target, sid);
	}
	internal static void RememberReleaseAbilityViewAbility(BhUnitAbilityView view, object ability)
	{
		if (view == null)
			return;
		var key = Homm3DirectStateIdentity.ResolveKeyOrZero(view);
		if (IsReleaseAbilityWrapper(ability))
			ReleaseAbilityByView[key] = ability;
		else
			ReleaseAbilityByView.Remove(key);
	}

	private static void PostfixBegsRelease(BhSelectedUnitHud __instance, Unit __1, SelectedUnitHudCustomSidState __state)
	{
		var sid = __state?.OriginalSid ?? SafeExtractSid(__1);
		ApplySelectedUnitPortrait(__instance, sid, "release-begs-postfix");
		RecoverUnitControlsRelease(__instance, __1, sid);
	}
	private static Exception FinalizerBeetRelease(Exception __exception, BhSelectedUnitHud __instance, BattleEventArgs __1, SelectedUnitHudCustomSidState __state)
	{
		try
		{
			return FinalizerBeetReleaseCore(__exception, __instance, __1, __state);
		}
		catch (Exception recoveryFailure)
		{
			// A finalizer that throws escapes into native BhSelectedUnitHud. Custom-unit events decline
			// with a log; vanilla events keep the original exception (or none) unchanged.
			var sid = __state?.OriginalSid ?? SafeExtractSid(__1?.target);
			if (!IsCustomSid(sid))
				return __exception;
			LogCustomSidMissSuppressed("beet-recovery", null, sid, sid, recoveryFailure);
			return null;
		}
	}

	private static Exception FinalizerBeetReleaseCore(Exception __exception, BhSelectedUnitHud __instance, BattleEventArgs __1, SelectedUnitHudCustomSidState __state)
	{
		var sid = __state?.OriginalSid ?? SafeExtractSid(__1?.target);
		if (__exception == null)
		{
			ApplySelectedUnitPortrait(__instance, sid, "release-beet-finalizer-ok");
			return null;
		}
		if (!IsKeyNotFoundException(__exception))
		{
			if (!IsCustomSid(sid))
				return __exception;
			LogCustomSidMissSuppressed("beet-other", null, sid, sid, __exception);
			return null;
		}

		var missingSid = ExtractMissingKey(__exception);
		var eventSid = SafeExtractSid(__1?.target);
		if (ShouldIgnoreStaleReleaseSuppressedEvent(eventSid, missingSid))
		{
			LogIgnoredStaleReleaseSuppressedEvent(eventSid, missingSid);
			LogSuppressedReleaseBeetException(__exception);
			return null;
		}
		if (!IsReleaseRecoverableCustomSidMiss(__state, sid, eventSid, missingSid))
			return __exception;

		var recoverSid = ResolveReleaseRecoverSid(sid, eventSid, missingSid);
		LogCustomSidMissSuppressed("beet", missingSid, eventSid, recoverSid, __exception);
		ApplySelectedUnitPortrait(__instance, recoverSid, "release-beet-finalizer-suppressed");
		RecoverUnitControlsRelease(__instance, __1?.target, recoverSid);
		LogSuppressedReleaseBeetException(__exception);
		return null;
	}
	private static Exception FinalizerBegsRelease(Exception __exception, BhSelectedUnitHud __instance, Unit __1, SelectedUnitHudCustomSidState __state)
	{
		try
		{
			return FinalizerBegsReleaseCore(__exception, __instance, __1, __state);
		}
		catch (Exception recoveryFailure)
		{
			// A finalizer that throws escapes into native BhSelectedUnitHud. Custom-unit events decline
			// with a log; vanilla events keep the original exception (or none) unchanged.
			var sid = __state?.OriginalSid ?? SafeExtractSid(__1);
			if (!IsCustomSid(sid))
				return __exception;
			LogCustomSidMissSuppressed("begs-recovery", null, sid, sid, recoveryFailure);
			return null;
		}
	}

	private static Exception FinalizerBegsReleaseCore(Exception __exception, BhSelectedUnitHud __instance, Unit __1, SelectedUnitHudCustomSidState __state)
	{
		var sid = __state?.OriginalSid ?? SafeExtractSid(__1);
		if (__exception == null)
		{
			ApplySelectedUnitPortrait(__instance, sid, "release-begs-finalizer-ok");
			return null;
		}
		if (!IsKeyNotFoundException(__exception))
		{
			if (!IsCustomSid(sid))
				return __exception;
			LogCustomSidMissSuppressed("begs-other", null, sid, sid, __exception);
			return null;
		}

		var missingSid = ExtractMissingKey(__exception);
		var eventSid = SafeExtractSid(__1);
		if (ShouldIgnoreStaleReleaseSuppressedEvent(eventSid, missingSid))
		{
			LogIgnoredStaleReleaseSuppressedEvent(eventSid, missingSid);
			LogSuppressedReleaseBeetException(__exception);
			return null;
		}
		if (!IsReleaseRecoverableCustomSidMiss(__state, sid, eventSid, missingSid))
			return __exception;

		var recoverSid = ResolveReleaseRecoverSid(sid, eventSid, missingSid);
		LogCustomSidMissSuppressed("begs", missingSid, eventSid, recoverSid, __exception);
		ApplySelectedUnitPortrait(__instance, recoverSid, "release-begs-finalizer-suppressed");
		RecoverUnitControlsRelease(__instance, __1, recoverSid);
		LogSuppressedReleaseBeetException(__exception);
		return null;
	}
	private static SelectedUnitHudCustomSidState BeginReleaseCustomSidBind(Unit unit, string originalSid)
	{
		if (unit == null || string.IsNullOrWhiteSpace(originalSid))
			return null;
		return new SelectedUnitHudCustomSidState
		{
			Unit = unit,
			OriginalSid = originalSid
		};
	}

	/// <summary>
	/// Audit A4 (2026-09-27): native BhSelectedUnitHud release handlers index a config dictionary by
	/// unit sid; a custom sid (h3_firebird, h3_pixie, ...) that is not the HUD's current bound sid
	/// used to be rethrown into native code. The whole custom-sid class is now recoverable: a
	/// KeyNotFoundException whose missing key is a custom unit sid, or whose key could not be read
	/// while the event/HUD unit is custom. Vanilla-sid misses still propagate unchanged.
	/// Contract: tools/validate_native_hook_safety_contract.py.
	/// </summary>
	private static bool IsReleaseRecoverableCustomSidMiss(SelectedUnitHudCustomSidState state, string sid, string eventSid, string missingSid)
	{
		if (!string.IsNullOrWhiteSpace(missingSid))
			return Homm3CustomFactionRegistry.IsCustomUnitSid(missingSid);
		return IsCustomSid(eventSid) || IsCustomSid(sid) || IsCustomSid(state?.OriginalSid);
	}

	private static bool IsCustomSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid) && Homm3CustomFactionRegistry.IsCustomUnitSid(sid);
	}

	private static string ResolveReleaseRecoverSid(string sid, string eventSid, string missingSid)
	{
		// Recover the HUD for the unit it is showing; the missing key may belong to another unit.
		if (IsCustomSid(sid))
			return sid;
		if (IsCustomSid(eventSid))
			return eventSid;
		return IsCustomSid(missingSid) ? missingSid : sid;
	}

	private static readonly HashSet<string> LoggedCustomSidMisses = new(StringComparer.OrdinalIgnoreCase);

	private static void LogCustomSidMissSuppressed(string handler, string missingSid, string eventSid, string recoverSid, Exception exception)
	{
		var key = handler + "|" + (missingSid ?? "?") + "|" + (eventSid ?? "?");
		lock (LoggedCustomSidMisses)
		{
			if (!LoggedCustomSidMisses.Add(key))
				return;
		}
		Plugin.LogSource?.LogWarning(
			"Homm3Import BhSelectedUnitHud." + handler + ": native KeyNotFoundException for custom unit sid suppressed"
			+ " missing='" + (missingSid ?? "<unreadable>") + "' event='" + (eventSid ?? "?")
			+ "' recovered='" + (recoverSid ?? "?") + "' (" + exception.GetType().Name + ": " + exception.Message
			+ "). Logged once per (handler, missing, event) sid.");
	}

	private sealed class SelectedUnitHudCustomSidState
	{
		internal Unit Unit;
		internal string OriginalSid;
	}
	private static void LogSuppressedReleaseBeetException(Exception exception)
	{
		if (!IsDiagnosticEnabled())
			return;
		if (_loggedSuppressed < 12)
		{
			_loggedSuppressed++;
			Plugin.LogSource?.LogWarning(
				"Homm3Import BhSelectedUnitHud.beet: KeyNotFoundException suppressed; "
				+ exception.Message);
		}
	}

	private static void WarmReleaseActionBarResolverForCustomUnits(ManualLogSource log)
	{
		if (!IsReleaseConfigActionBarFallbackEnabled())
			return;
		try
		{
			var result = PrewarmReleaseActionBarsForSids(Homm3CustomFactionRegistry.EnumerateCustomUnitSids(), log);
			if (IsDiagnosticEnabled())
			{
				log?.LogInfo(
					"Homm3Import selected-unit HUD action-bar resolver warmed for custom unit SIDs: "
					+ result.ActionBars
					+ " action-bar config(s), "
					+ result.Icons
					+ " icon(s), "
					+ result.IconMisses
					+ " icon miss(es), "
					+ NoReleaseActionBarSids.Count
					+ " no-action-bar sid(s).");
			}
		}
		catch (Exception ex)
		{
			if (_loggedReleaseActionBarPrewarm < 8)
			{
				_loggedReleaseActionBarPrewarm++;
				log?.LogWarning("Homm3Import selected-unit HUD action-bar resolver warmup failed: " + ex.Message);
			}
		}
	}

	private static bool ShouldIgnoreStaleReleaseSuppressedEvent(string eventSid, string missingSid)
	{
		if (!IsCachedControlsSid(missingSid))
			return false;
		if (IsCachedControlsSid(eventSid))
			return false;
		if (!string.IsNullOrWhiteSpace(eventSid))
			return true;
		return IsCachedControlsSid(_lastBoundReleaseControlsSid)
		       && !string.Equals(missingSid, _lastBoundReleaseControlsSid, StringComparison.OrdinalIgnoreCase);
	}

	private static void LogIgnoredStaleReleaseSuppressedEvent(string eventSid, string missingSid)
	{
		if (!IsDiagnosticEnabled())
			return;
		if (_loggedControlsRecovery >= 20)
			return;
		_loggedControlsRecovery++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import selected-unit HUD release controls: ignored stale suppressed lookup missingSid='"
			+ (missingSid ?? "?") + "' eventSid='" + (eventSid ?? "?")
			+ "' currentSid='" + (_lastBoundReleaseControlsSid ?? "?") + "'.");
	}

	private static bool PrefixBdon(BhSelectedUnitHud __instance, BattleEventArgs __1)
	{
		try
		{
			var sid = ExtractSid(__1?.target);
			if (string.IsNullOrWhiteSpace(sid) || !Homm3CustomFactionRegistry.TryGetDonorSid(sid, out var donorSid))
				return true;

			var seeded = SeedCustomSidDictionaries(__instance, sid, donorSid);
			if (seeded > 0 && Homm3DiagnosticFlags.IsEnabled("homm3_selected_hud_diag.flag") && _loggedDictionarySeed < 20)
			{
				_loggedDictionarySeed++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import selected-unit HUD: seeded " + seeded
					+ " dictionary entr" + (seeded == 1 ? "y" : "ies")
					+ " for sid='" + sid + "' from donor='" + donorSid + "'.");
			}

			ApplySelectedUnitPortrait(__instance, __1?.target, "prefix-custom-skip");
			RecoverUnitControls(__instance, __1?.target, sid);
			return false;
		}
		catch (Exception ex)
		{
			if (_loggedDictionarySeed < 5)
			{
				_loggedDictionarySeed++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD dictionary seed failed: " + ex.Message);
			}
			return true;
		}
	}

	private static void PostfixBdon(BhSelectedUnitHud __instance, BattleEventArgs __1)
	{
		ApplySelectedUnitPortrait(__instance, __1?.target, "postfix");
	}

	private static int SeedCustomSidDictionaries(BhSelectedUnitHud hud, string sid, string donorSid)
	{
		var seeded = 0;
		var flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = typeof(BhSelectedUnitHud); type != null; type = type.BaseType)
		{
			foreach (var field in type.GetFields(flags))
			{
				object value = null;
				try { value = field.GetValue(field.IsStatic ? null : hud); } catch { }
				if (value == null)
					continue;
				if (TrySeedDictionary(value, sid, donorSid))
					seeded++;
			}
		}
		return seeded;
	}


	private static bool TrySeedDictionary(object value, string sid, string donorSid)
	{
		if (value is not IDictionary dict)
			return TrySeedDictionaryLike(value, sid, donorSid);
		try
		{
			if (!dict.Contains(donorSid) || dict.Contains(sid))
				return false;
			dict[sid] = dict[donorSid];
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static Exception FinalizerBdon(Exception __exception, BhSelectedUnitHud __instance, BattleEventArgs __1)
	{
		if (__exception == null)
		{
			ApplySelectedUnitPortrait(__instance, __1?.target, "finalizer-ok");
			return null;
		}
		if (!IsKeyNotFoundException(__exception))
			return __exception;

		var eventSid = ExtractSid(__1?.target);
		var missingSid = ExtractMissingKey(__exception);
		if (ShouldIgnoreStaleSuppressedEvent(eventSid, missingSid))
		{
			LogIgnoredStaleSuppressedEvent(eventSid, missingSid);
			LogSuppressedBdonException(__exception);
			return null;
		}

		var sid = !string.IsNullOrWhiteSpace(missingSid) && Homm3CustomFactionRegistry.IsCustomUnitSid(missingSid)
			? missingSid
			: eventSid;
		if (string.IsNullOrWhiteSpace(sid))
			sid = missingSid;
		ApplySelectedUnitPortrait(__instance, sid, "finalizer-suppressed");
		RecoverUnitControls(__instance, __1?.target, sid);
		LogSuppressedBdonException(__exception);
		return null; // suppress; allows battle update loop to continue
	}

	private static void LogSuppressedBdonException(Exception exception)
	{
		if (!IsDiagnosticEnabled())
			return;
		if (_loggedSuppressed < 5)
		{
			_loggedSuppressed++;
			Plugin.LogSource?.LogWarning(
				"Homm3Import BhSelectedUnitHud.bdon: KeyNotFoundException suppressed â€” "
				+ exception.Message);
		}
	}

	private static bool ShouldIgnoreStaleSuppressedEvent(string eventSid, string missingSid)
	{
		if (!IsCachedControlsSid(missingSid))
			return false;
		if (IsCachedControlsSid(eventSid))
			return false;
		if (!string.IsNullOrWhiteSpace(eventSid))
			return true;
		return IsCachedControlsSid(_lastBoundControlsSid)
			&& !string.Equals(missingSid, _lastBoundControlsSid, StringComparison.OrdinalIgnoreCase);
	}

	private static void LogIgnoredStaleSuppressedEvent(string eventSid, string missingSid)
	{
		if (!IsDiagnosticEnabled())
			return;
		if (_loggedControlsRecovery >= 20)
			return;
		_loggedControlsRecovery++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import selected-unit HUD controls: ignored stale suppressed lookup missingSid='"
			+ (missingSid ?? "?") + "' eventSid='" + (eventSid ?? "?")
			+ "' currentSid='" + (_lastBoundControlsSid ?? "?") + "'.");
	}

	private static void RecoverUnitControls(BhSelectedUnitHud hud, Unit unit, string sid)
	{
		if (_loggedControlsRecovery < 5 && Homm3CustomFactionRegistry.IsCustomUnitSid(sid))
		{
			_loggedControlsRecovery++;
			LogDiagnostic("Homm3Import selected-unit HUD legacy controls recovery skipped for sid='" + sid + "'; release recovery owns current action bars.");
		}
	}

	private static void DirectBindUnitControls(BhUnitControlsView controlsView, Unit unit, string sid)
	{
		if (_loggedDirectControlsBind < 5 && Homm3CustomFactionRegistry.IsCustomUnitSid(sid))
		{
			_loggedDirectControlsBind++;
			LogDiagnostic("Homm3Import selected-unit HUD legacy direct bind skipped for sid='" + sid + "'.");
		}
	}

	private static void RecoverUnitControlsRelease(BhSelectedUnitHud hud, Unit unit, string sid)
	{
		try
		{
			if (hud == null || string.IsNullOrWhiteSpace(sid) || !Homm3CustomFactionRegistry.IsCustomUnitSid(sid))
				return;
			var controlsView = hud.controlsView;
			if (controlsView == null)
			{
				if (_loggedControlsRecovery < 5)
				{
					_loggedControlsRecovery++;
					Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release controls recovery skipped: controlsView is null for sid='" + sid + "'.");
				}
				return;
			}
			var eventUnitKey = GetIl2CppObjectKey(unit);
			if (eventUnitKey != 0
			    && _lastBoundReleaseControlsUnitKey != 0
			    && eventUnitKey == _lastBoundReleaseControlsUnitKey
			    && TryKeepCachedReleaseControlsActiveSameSid(controlsView, sid, "selected-HUD same-unit event refresh"))
			{
				return;
			}
			if (TryKeepCachedReleaseControlsHotPath(controlsView, sid, eventUnitKey, "selected-HUD repeated refresh"))
				return;

			if (unit == null)
			{
				if (TryDirectBindReleaseControlsFromTurnViewUnit(hud, controlsView, sid, "turn-view:missing-event-unit"))
					return;
				if (TryKeepOrRestoreCachedReleaseControls(controlsView, sid, "transient missing release unit after suppressed lookup failure"))
					return;
				TryPreserveNativeReleaseControls(controlsView, sid, "missing release event unit");
				return;
			}

			var unitSid = SafeExtractSidFieldOnly(unit);
			if (string.IsNullOrWhiteSpace(unitSid))
			{
				DirectBindUnitControlsRelease(controlsView, unit, sid);
				RefreshReleaseBasicCommands(hud.basicCommands, unit, sid);
				if (IsSameCachedReleaseControlsSid(sid)
				    && _lastBoundReleaseControlsAbilities != null
				    && CachedReleaseControlsAlreadyBound(controlsView, sid, _lastBoundReleaseControlsAbilities, eventUnitKey))
				{
					return;
				}
				if (TryDirectBindReleaseControlsFromTurnViewUnit(hud, controlsView, sid, "turn-view:unreadable-event-unit"))
					return;
				if (TryKeepOrRestoreCachedReleaseControls(controlsView, sid, "unreadable release event unit after suppressed lookup failure"))
					return;
				TryPreserveNativeReleaseControls(controlsView, sid, "unreadable release event unit");
				return;
			}
			if (!string.IsNullOrWhiteSpace(unitSid) && !string.Equals(unitSid, sid, StringComparison.OrdinalIgnoreCase))
			{
				if (TryDirectBindReleaseControlsFromTurnViewUnit(hud, controlsView, sid, "turn-view:stale-event-unit:" + (unitSid ?? "?")))
					return;
				if (TryKeepOrRestoreCachedReleaseControls(controlsView, sid, "stale release event unit '" + (unitSid ?? "?") + "' after suppressed lookup failure"))
					return;
				TryPreserveNativeReleaseControls(controlsView, sid, "stale release event unit '" + (unitSid ?? "?") + "'");
				return;
			}

			DirectBindUnitControlsRelease(controlsView, unit, sid);
			RefreshReleaseBasicCommands(hud.basicCommands, unit, sid);
			if (_loggedControlsRecovery < 20)
			{
				_loggedControlsRecovery++;
				LogDiagnostic("Homm3Import selected-unit HUD release controls: rebound ability controls for sid='" + sid + "' after suppressed lookup failure.");
			}
		}
		catch (Exception ex)
		{
			if (_loggedControlsRecovery < 5)
			{
				_loggedControlsRecovery++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release controls recovery failed: " + ex.Message);
			}
		}
	}

	private static bool TryDirectBindReleaseControlsFromTurnViewUnit(BhSelectedUnitHud hud, BhUnitControlsView controlsView, string sid, string reason)
	{
		var unit = TryFindReleaseTurnViewUnitBySid(sid);
		if (unit == null)
			return false;
		var unitKey = GetIl2CppObjectKey(unit);
		if (IsReleaseConfigActionBarFallbackEnabled() && IsCachedNoReleaseControlsUnit(sid, unitKey))
		{
			ClearReleaseNoActionBarControls(controlsView, sid, "cached-no-actionbar:" + (reason ?? "?"));
			return false;
		}
		DirectBindUnitControlsRelease(controlsView, unit, sid);
		RefreshReleaseBasicCommands(hud?.basicCommands, unit, sid);
		var success = _lastBoundReleaseControlsUnitKey == unitKey
		              && IsSameCachedReleaseControlsSid(sid)
		              && _lastBoundReleaseControlsAbilities != null
		              && CachedReleaseControlsAlreadyBound(controlsView, sid, _lastBoundReleaseControlsAbilities, unitKey);
		if (_loggedControlsRecovery < 20)
		{
			_loggedControlsRecovery++;
			LogDiagnostic(
				"Homm3Import selected-unit HUD release controls: turn-view unit recovery "
				+ (success ? "bound" : "found no action-bar abilities")
				+ " for sid='" + sid + "' reason='" + (reason ?? "?")
				+ "' count=" + (_lastBoundReleaseControlsAbilities?.Length ?? -1) + ".");
		}
		return success;
	}

	private static Unit TryFindReleaseTurnViewUnitBySid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		try
		{
			if (_lastTurnViewUnit != null
			    && _lastTurnViewUnitKey != 0
			    && string.Equals(_lastTurnViewUnitSid, sid, StringComparison.OrdinalIgnoreCase)
			    && GetIl2CppObjectKey(_lastTurnViewUnit) == _lastTurnViewUnitKey
			    && string.Equals(SafeExtractSidFieldOnly(_lastTurnViewUnit), sid, StringComparison.OrdinalIgnoreCase))
			{
				return _lastTurnViewUnit;
			}

			var turnViews = Resources.FindObjectsOfTypeAll<BhTurnView>();
			Unit firstMatch = null;
			for (var i = 0; i < turnViews.Length; i++)
			{
				var turnView = turnViews[i];
				if (turnView == null)
					continue;
				var unit = TryReadNativeObjectMember<Unit>(turnView, GameSymbols.BattleUi.TurnViewUnitFields)
				           ?? TryGetFirstMemberValue(turnView, GameSymbols.BattleUi.TurnViewUnitFields) as Unit;
				if (unit == null)
					continue;
				var unitSid = SafeExtractSidFieldOnly(unit);
				if (!string.Equals(unitSid, sid, StringComparison.OrdinalIgnoreCase))
					continue;
				firstMatch ??= unit;
				try
				{
					if (turnView.gameObject != null && turnView.gameObject.activeInHierarchy)
					{
						CacheTurnViewUnit(sid, unit);
						return unit;
					}
				}
				catch { }
			}
			if (firstMatch != null)
				CacheTurnViewUnit(sid, firstMatch);
			return firstMatch;
		}
		catch
		{
			return null;
		}
	}

	private static void CacheTurnViewUnit(string sid, Unit unit)
	{
		var unitKey = GetIl2CppObjectKey(unit);
		if (string.IsNullOrWhiteSpace(sid) || unit == null || unitKey == 0)
			return;
		_lastTurnViewUnitSid = sid;
		_lastTurnViewUnit = unit;
		_lastTurnViewUnitKey = unitKey;
	}

	private static void DirectBindUnitControlsRelease(BhUnitControlsView controlsView, Unit unit, string sid)
	{
		try
		{
			if (controlsView == null || unit == null)
				return;

			var unitKey = GetIl2CppObjectKey(unit);
			if (IsReleaseConfigActionBarFallbackEnabled() && IsCachedNoReleaseControlsUnit(sid, unitKey))
			{
				var cachedHidden = ClearReleaseNoActionBarControls(controlsView, sid, "cache:no-actionbar");
				LogDirectReleaseControlsBind("kept: cached no live release action-bar abilities; hid staleViews=" + cachedHidden, sid, "cache:no-actionbar", null);
				return;
			}
			var unitChanged = _lastBoundReleaseControlsUnitKey != 0
			                  && unitKey != 0
			                  && unitKey != _lastBoundReleaseControlsUnitKey;
			if (!unitChanged && TryKeepCachedReleaseControlsHotPath(controlsView, sid, unitKey, "direct bind repeated refresh"))
				return;
			var manager = TryGetReleaseAbilityManager(unit);
			var result = FindReleaseActionBarAbilities(unit, manager, sid);
			if ((result.Abilities == null || result.Abilities.Length <= 0)
			    && IsReleaseConfigActionBarFallbackEnabled())
			{
				var sidResult = FindReleaseActionBarAbilitiesBySid(sid);
				if (sidResult.Abilities != null && sidResult.Abilities.Length > 0)
					result = sidResult;
			}
			if ((result.Abilities == null || result.Abilities.Length <= 0)
			    && IsSameCachedReleaseControlsSid(sid)
			    && _lastBoundReleaseControlsAbilities != null
			    && _lastBoundReleaseControlsAbilities.Length > 0)
			{
				result = new ReleaseAbilityArrayResult("cache:" + sid, _lastBoundReleaseControlsAbilities);
			}
			LogReleaseActionBarLookup(unit, sid, manager, result);

			if (!unitChanged && CachedReleaseControlsAlreadyBound(controlsView, sid, result.Abilities, unitKey))
			{
				_lastBoundReleaseControlsView = controlsView;
				CacheBoundReleaseControls(sid, result.Abilities, unitKey);
				InvokeReleaseControlsClickEnabled(controlsView, true);
				LogDirectReleaseControlsBind("kept: cached matching release action-bar abilities already bound", sid, result.Source, result.Abilities);
				return;
			}

			if (!unitChanged && ExistingReleaseControlsAlreadyBound(controlsView, result.Abilities))
			{
				var sameCachedUnit = IsSameCachedReleaseControlsSid(sid)
				                     && unitKey != 0
				                     && unitKey == _lastBoundReleaseControlsUnitKey;
				_lastBoundReleaseControlsView = controlsView;
				CacheBoundReleaseControls(sid, result.Abilities, unitKey);
				if (!sameCachedUnit)
					Homm3CustomUiIconHook.RefreshBattleAbilityIconsIn(controlsView);
				LogDirectReleaseControlsBind("kept: matching release action-bar abilities already bound", sid, result.Source, result.Abilities);
				return;
			}

			if (result.Abilities == null || result.Abilities.Length <= 0)
			{
				if (!IsConclusiveNoReleaseActionBarResult(result))
				{
					TryPreserveNativeReleaseControls(controlsView, sid, result.Source ?? "native-manager-miss");
					return;
				}
				if (unitChanged)
				{
					TryClearReleaseControlsSelectedViewField(controlsView, sid, "unit transition with no live release action-bar abilities");
					ClearCachedReleaseControls();
				}
				CacheNoReleaseControls(sid, unitKey);
				var hidden = ClearReleaseNoActionBarControls(controlsView, sid, result.Source);
				LogDirectReleaseControlsBind("kept: no live release action-bar abilities; hid staleViews=" + hidden, sid, result.Source, result.Abilities);
				return;
			}

			var selected = unitChanged ? null : FindCurrentSelectedReleaseAbility(controlsView, result.Abilities);
			controlsView.Clear();
			InvokeReleaseControlsBind(controlsView, result.Abilities, selected);
			if (unitChanged)
				TryClearReleaseControlsSelectedViewField(controlsView, sid, "unit transition");
			InvokeReleaseControlsClickEnabled(controlsView, true);
			Homm3CustomUiIconHook.RefreshBattleAbilityIconsIn(controlsView);
			_lastBoundReleaseControlsView = controlsView;
			CacheBoundReleaseControls(sid, result.Abilities, unitKey);
			ClearNoReleaseControlsCache();
			LogDirectReleaseControlsBind(unitChanged ? "bound: cleared selected action for new unit" : "bound", sid, result.Source, result.Abilities);
		}
		catch (Exception ex)
		{
			if (_loggedDirectControlsBind < 8)
			{
				_loggedDirectControlsBind++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release controls direct bind failed for sid='" + sid + "': " + ex.Message);
			}
		}
	}

	private static bool DirectBindUnitControlsReleaseFromUnitConfigs(BhUnitControlsView controlsView, Unit unit, string sid, string source)
	{
		try
		{
			if (!IsReleaseConfigActionBarFallbackEnabled())
				return false;
			if (controlsView == null || unit == null || string.IsNullOrWhiteSpace(sid) || !Homm3CustomFactionRegistry.IsCustomUnitSid(sid))
				return false;
			var abilities = BuildReleaseActionBarAbilitiesFromUnitConfigs(unit, sid);
			if (abilities == null || abilities.Length <= 0)
				return false;

			var unitKey = GetIl2CppObjectKey(unit);
			if (CachedReleaseControlsAlreadyBound(controlsView, sid, abilities, unitKey))
			{
				_lastBoundReleaseControlsView = controlsView;
				CacheBoundReleaseControls(sid, abilities, unitKey);
				InvokeReleaseControlsClickEnabled(controlsView, true);
				LogDirectReleaseControlsBind("kept: cached matching unit-config release action-bar abilities already bound", sid, source, abilities);
				return true;
			}

			if (ExistingReleaseControlsAlreadyBound(controlsView, abilities))
			{
				_lastBoundReleaseControlsView = controlsView;
				CacheBoundReleaseControls(sid, abilities, unitKey);
				Homm3CustomUiIconHook.RefreshBattleAbilityIconsIn(controlsView);
				LogDirectReleaseControlsBind("kept: matching unit-config release action-bar abilities already bound", sid, source, abilities);
				return true;
			}

			controlsView.Clear();
			InvokeReleaseControlsBind(controlsView, abilities, null);
			InvokeReleaseControlsClickEnabled(controlsView, true);
			Homm3CustomUiIconHook.RefreshBattleAbilityIconsIn(controlsView);
			_lastBoundReleaseControlsView = controlsView;
			CacheBoundReleaseControls(sid, abilities, unitKey);
			LogDirectReleaseControlsBind("bound: rebuilt from live unit config fields", sid, source, abilities);
			return true;
		}
		catch (Exception ex)
		{
			if (_loggedDirectControlsBind < 8)
			{
				_loggedDirectControlsBind++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release controls unit-config bind failed for sid='" + sid + "': " + ex.Message);
			}
			return false;
		}
	}

	private static bool DirectBindUnitControlsReleaseFromSid(BhUnitControlsView controlsView, string sid, string source)
	{
		try
		{
			if (!IsReleaseConfigActionBarFallbackEnabled())
				return false;
			if (controlsView == null || string.IsNullOrWhiteSpace(sid) || !Homm3CustomFactionRegistry.IsCustomUnitSid(sid))
				return false;
			if (TryKeepCachedReleaseControlsActiveSameSid(controlsView, sid, "sid-config repeated refresh:" + (source ?? "?")))
				return true;

			var result = FindReleaseActionBarAbilitiesBySid(sid);
			var abilities = result.Abilities;
			if (abilities == null || abilities.Length <= 0)
				return false;
			var resolvedSource = string.IsNullOrWhiteSpace(source)
				? result.Source
				: source + ":" + result.Source;

			var sidKey = GetSidConfigCacheKey(sid);
			if (CachedReleaseControlsAlreadyBound(controlsView, sid, abilities, sidKey))
			{
				_lastBoundReleaseControlsView = controlsView;
				CacheBoundReleaseControls(sid, abilities, sidKey);
				InvokeReleaseControlsClickEnabled(controlsView, true);
				LogDirectReleaseControlsBind("kept: cached matching sid-config release action-bar abilities already bound", sid, resolvedSource, abilities);
				return true;
			}

			if (ExistingReleaseControlsAlreadyBound(controlsView, abilities))
			{
				_lastBoundReleaseControlsView = controlsView;
				CacheBoundReleaseControls(sid, abilities, sidKey);
				Homm3CustomUiIconHook.RefreshBattleAbilityIconsIn(controlsView);
				LogDirectReleaseControlsBind("kept: matching sid-config release action-bar abilities already bound", sid, resolvedSource, abilities);
				return true;
			}

			controlsView.Clear();
			InvokeReleaseControlsBind(controlsView, abilities, null);
			InvokeReleaseControlsClickEnabled(controlsView, true);
			Homm3CustomUiIconHook.RefreshBattleAbilityIconsIn(controlsView);
			_lastBoundReleaseControlsView = controlsView;
			CacheBoundReleaseControls(sid, abilities, sidKey);
			LogDirectReleaseControlsBind("bound: rebuilt from custom sid config", sid, resolvedSource, abilities);
			return true;
		}
		catch (Exception ex)
		{
			if (_loggedDirectControlsBind < 8)
			{
				_loggedDirectControlsBind++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release controls sid-config bind failed for sid='" + sid + "': " + ex.Message);
			}
			return false;
		}
	}

	private static bool TrySeedDictionaryLike(object value, string sid, string donorSid)
	{
		if (value == null || string.IsNullOrWhiteSpace(sid) || string.IsNullOrWhiteSpace(donorSid))
			return false;
		try
		{
			if (!TryGetDictionaryLikeValue(value, donorSid, out var donorValue))
				return false;
			if (TryDictionaryLikeContainsKey(value, sid))
				return false;
			return TrySetDictionaryLikeValue(value, sid, donorValue);
		}
		catch
		{
			return false;
		}
	}

	private static bool TryDictionaryLikeContainsKey(object value, string key)
	{
		var type = value.GetType();
		var contains = FindDictionaryLikeMethod(type, "ContainsKey", 1);
		if (contains != null)
		{
			try
			{
				return contains.Invoke(value, new object[] { key }) is bool found && found;
			}
			catch { }
		}
		return TryGetDictionaryLikeValue(value, key, out _);
	}

	private static bool TryGetDictionaryLikeValue(object value, string key, out object result)
	{
		result = null;
		if (value == null || string.IsNullOrWhiteSpace(key))
			return false;
		var type = value.GetType();
		var tryGet = FindDictionaryLikeMethod(type, "TryGetValue", 2);
		if (tryGet != null)
		{
			try
			{
				var args = new object[] { key, null };
				if (tryGet.Invoke(value, args) is bool found && found)
				{
					result = args[1];
					return result != null;
				}
			}
			catch { }
		}

		var getter = FindDictionaryLikeMethod(type, "get_Item", 1);
		if (getter != null)
		{
			try
			{
				result = getter.Invoke(value, new object[] { key });
				return result != null;
			}
			catch { }
		}
		return false;
	}

	private static bool TrySetDictionaryLikeValue(object value, string key, object item)
	{
		if (value == null || string.IsNullOrWhiteSpace(key) || item == null)
			return false;
		var type = value.GetType();
		var setter = FindDictionaryLikeMethod(type, "set_Item", 2);
		if (setter != null)
		{
			try
			{
				setter.Invoke(value, new[] { key, item });
				return true;
			}
			catch { }
		}
		var add = FindDictionaryLikeMethod(type, "Add", 2);
		if (add != null)
		{
			try
			{
				add.Invoke(value, new[] { key, item });
				return true;
			}
			catch { }
		}
		return false;
	}

	private static MethodInfo FindDictionaryLikeMethod(Type type, string name, int parameterCount)
	{
		if (type == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var method in type.GetMethods(flags))
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (method.GetParameters().Length == parameterCount)
				return method;
		}
		return null;
	}

	private static void FailClosedReleaseControls(BhUnitControlsView controlsView, string sid, string reason)
	{
		try
		{
			TryClearReleaseControlsSelectedViewField(controlsView, sid, reason);
			var hidden = ClearReleaseNoActionBarControls(controlsView, sid, reason);
			ClearCachedReleaseControls();
			LogDirectReleaseControlsBind("cleared: " + reason + "; hid staleViews=" + hidden, sid, null, null);
		}
		catch (Exception ex)
		{
			if (_loggedDirectControlsBind < 8)
			{
				_loggedDirectControlsBind++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release controls fail-closed cleanup failed for sid='" + sid + "': " + ex.Message);
			}
		}
	}

	private static void TryClearReleaseControlsSelection(BhUnitControlsView controlsView, string sid, string reason)
	{
		TryClearReleaseControlsSelectedViewField(controlsView, sid, reason);
	}

	private static int ClearReleaseNoActionBarControls(BhUnitControlsView controlsView, string sid, string source)
	{
		if (controlsView == null)
			return 0;
		ClearCachedReleaseControls();
		ClearReleaseAbilityViewState(controlsView, sid);
		TryClearReleaseControlsSelectedViewField(controlsView, sid, "no action-bar abilities: " + (source ?? "?"));
		var hidden = HideReleaseNoActionBarAbilityViews(controlsView, sid, source);
		hidden += ClearSelectedBattleActionBarAbilityViews(sid, source);
		try { controlsView.Clear(); }
		catch (Exception ex) { LogReleaseNoAbilityCleanupWarning(sid, "native controls clear", ex); }
		try { InvokeReleaseControlsClickEnabled(controlsView, false); }
		catch (Exception ex) { LogReleaseNoAbilityCleanupWarning(sid, "click disable", ex); }
		Homm3CustomUiIconHook.ClearBattleAbilityIconsIn(controlsView);
		hidden += HideReleaseNoActionBarAbilityViews(controlsView, sid, source);
		hidden += ClearSelectedBattleActionBarAbilityViews(sid, source);
		return hidden;
	}

	private static void ClearReleaseAbilityViewState(BhUnitControlsView controlsView, string sid)
	{
		try
		{
			var views = controlsView?.abilities;
			if (views == null)
				return;
			for (var i = 0; i < views.Count; i++)
				ClearReleaseAbilityViewState(views[i], sid);
		}
		catch (Exception ex)
		{
			LogReleaseNoAbilityCleanupWarning(sid, "ability view list cleanup", ex);
		}
	}

	private static void ClearReleaseAbilityViewState(BhUnitAbilityView view, string sid)
	{
		if (view == null)
			return;
		RememberReleaseAbilityViewAbility(view, null);
		try { AbilityViewEnabledByInstanceId.Remove(view.GetInstanceID()); }
		catch (Exception ex) { LogReleaseNoAbilityCleanupWarning(sid, "ability view enabled-state cleanup", ex); }
		var abilityType = GameInteropTypes.ReleaseAbilityWrapperType;
		if (abilityType != null
		    && !TrySetFirstMemberValue(view, GameSymbols.SelectedUnitHud.AbilityViewAbilityFields, abilityType, null))
		{
			LogReleaseNoAbilityCleanupWarning(sid, "ability view native wrapper field cleanup", null);
		}
	}

	private static void LogReleaseNoAbilityCleanupWarning(string sid, string step, Exception ex)
	{
		if (_loggedReleaseNoAbilityCleanup >= 8)
			return;
		_loggedReleaseNoAbilityCleanup++;
		Plugin.LogSource?.LogWarning(
			"Homm3Import selected-unit HUD release no-action-bar cleanup "
			+ (step ?? "?")
			+ " failed for sid='"
			+ (sid ?? "?")
			+ "': "
			+ (ex != null ? ex.Message : "unknown"));
	}

	private static int HideReleaseNoActionBarAbilityViews(BhUnitControlsView controlsView, string sid, string source)
	{
		var hidden = 0;
		try
		{
			var views = controlsView?.abilities;
			if (views == null)
				return 0;

			for (var i = 0; i < views.Count; i++)
			{
				var view = views[i];
				var go = view != null ? view.gameObject : null;
				if (go == null || !go.activeSelf)
					continue;

				go.SetActive(false);
				hidden++;
			}

			if (hidden > 0 && IsDiagnosticEnabled() && _loggedReleaseNoAbilityCleanup < 20)
			{
				_loggedReleaseNoAbilityCleanup++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import selected-unit HUD release controls: hid "
					+ hidden
					+ " stale action-bar view(s) for no-ability sid='"
					+ sid
					+ "' source='"
					+ (source ?? "?")
					+ "' and cleared custom icon state.");
			}
		}
		catch (Exception ex)
		{
			if (_loggedReleaseNoAbilityCleanup < 5)
			{
				_loggedReleaseNoAbilityCleanup++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release no-ability cleanup failed for sid='" + sid + "': " + ex.Message);
			}
		}
		return hidden;
	}

	private static int ClearSelectedBattleActionBarAbilityViews(string sid, string source)
	{
		var hidden = 0;
		try
		{
			var views = Resources.FindObjectsOfTypeAll<BhUnitAbilityView>();
			for (var i = 0; i < views.Length; i++)
			{
				var view = views[i];
				var go = view != null ? view.gameObject : null;
				if (go == null || !go.activeSelf)
					continue;
				var path = GetPath(go.transform);
				if (path.IndexOf(SelectedBattleActionBarAbilityPathFragment, StringComparison.Ordinal) < 0)
					continue;

				ClearReleaseAbilityViewState(view, sid);
				Homm3CustomUiIconHook.ClearBattleAbilityIconsIn(view);
				go.SetActive(false);
				hidden++;
				if (IsDiagnosticEnabled() && _loggedSceneAbilityCleanup < 20)
				{
					_loggedSceneAbilityCleanup++;
					Plugin.LogSource?.LogInfo(
						"Homm3Import selected-unit HUD release no-action-bar cleanup: hid selected battle action-bar ability path='"
						+ path
						+ "' sid='"
						+ (sid ?? "?")
						+ "' source='"
						+ (source ?? "?")
						+ "'.");
				}
			}
		}
		catch (Exception ex)
		{
			LogReleaseNoAbilityCleanupWarning(sid, "selected battle action-bar ability cleanup", ex);
		}
		return hidden;
	}

	private static void ClearCachedReleaseControls()
	{
		_lastBoundReleaseControlsSid = null;
		_lastBoundReleaseControlsView = null;
		_lastBoundReleaseControlsAbilities = null;
		_lastBoundReleaseControlsUnitKey = 0;
	}

	private static void CacheNoReleaseControls(string sid, long unitKey)
	{
		if (string.IsNullOrWhiteSpace(sid) || unitKey == 0)
			return;
		_lastNoReleaseControlsSid = sid;
		_lastNoReleaseControlsUnitKey = unitKey;
	}

	private static void CacheNoReleaseActionBarSid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return;
		NoReleaseActionBarSids.Add(sid.Trim());
	}

	private static bool IsKnownNoReleaseActionBarSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid) && NoReleaseActionBarSids.Contains(sid.Trim());
	}

	private static bool IsReleaseConfigActionBarFallbackEnabled()
	{
		return Homm3DiagnosticFlags.IsEnabled("homm3_custom_ability_config_fallback.flag");
	}

	private static void ClearNoReleaseControlsCache()
	{
		_lastNoReleaseControlsSid = null;
		_lastNoReleaseControlsUnitKey = 0;
	}

	private static bool IsCachedNoReleaseControlsUnit(string sid, long unitKey)
	{
		return unitKey != 0
		       && !string.IsNullOrWhiteSpace(sid)
		       && unitKey == _lastNoReleaseControlsUnitKey
		       && string.Equals(sid, _lastNoReleaseControlsSid, StringComparison.OrdinalIgnoreCase);
	}

	private static bool TryKeepOrRestoreCachedReleaseControls(BhUnitControlsView controlsView, string sid, string reason)
	{
		try
		{
			if (controlsView == null
			    || !IsSameCachedReleaseControlsSid(sid)
			    || _lastBoundReleaseControlsAbilities == null
			    || _lastBoundReleaseControlsAbilities.Length <= 0)
			{
				return false;
			}

			_lastBoundReleaseControlsView = controlsView;
			if (CachedReleaseControlsAlreadyBound(controlsView, sid, _lastBoundReleaseControlsAbilities, _lastBoundReleaseControlsUnitKey))
			{
				InvokeReleaseControlsClickEnabled(controlsView, true);
				LogDirectReleaseControlsBind("kept: " + reason, sid, "cache:" + sid, _lastBoundReleaseControlsAbilities);
				return true;
			}

			var selected = FindCurrentSelectedReleaseAbility(controlsView, _lastBoundReleaseControlsAbilities);
			controlsView.Clear();
			InvokeReleaseControlsBind(controlsView, _lastBoundReleaseControlsAbilities, selected);
			InvokeReleaseControlsClickEnabled(controlsView, true);
			Homm3CustomUiIconHook.RefreshBattleAbilityIconsIn(controlsView);
			LogDirectReleaseControlsBind("restored: " + reason, sid, "cache:" + sid, _lastBoundReleaseControlsAbilities);
			return true;
		}
		catch (Exception ex)
		{
			if (_loggedDirectControlsBind < 8)
			{
				_loggedDirectControlsBind++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release controls cache restore failed for sid='" + sid + "': " + ex.Message);
			}
			return false;
		}
	}

	private static bool TryPreserveNativeReleaseControls(BhUnitControlsView controlsView, string sid, string reason)
	{
		if (controlsView == null)
			return false;
		try
		{
			InvokeReleaseControlsClickEnabled(controlsView, true);
			Homm3CustomUiIconHook.RefreshBattleAbilityIconsIn(controlsView);
			LogDirectReleaseControlsBind("preserved native controls: " + (reason ?? "?"), sid, "native", GetReleaseCurrentAbilityArray(controlsView));
			return true;
		}
		catch (Exception ex)
		{
			if (_loggedDirectControlsBind < 8)
			{
				_loggedDirectControlsBind++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release controls preserve failed for sid='" + sid + "': " + ex.Message);
			}
			return false;
		}
	}

	private static bool TryKeepCachedReleaseControlsHotPath(BhUnitControlsView controlsView, string sid, long unitKey, string reason)
	{
		try
		{
			if (controlsView == null
			    || !IsSameCachedReleaseControlsSid(sid)
			    || _lastBoundReleaseControlsAbilities == null
			    || _lastBoundReleaseControlsAbilities.Length <= 0)
			{
				return false;
			}
			var effectiveUnitKey = GetCachedReleaseHotPathUnitKey(sid, unitKey);
			if (_lastBoundReleaseControlsUnitKey != 0)
			{
				if (effectiveUnitKey == 0 || effectiveUnitKey != _lastBoundReleaseControlsUnitKey)
					return false;
			}
			if (CachedReleaseControlsStillInstalledFast(controlsView, sid, _lastBoundReleaseControlsAbilities, effectiveUnitKey))
			{
				CacheBoundReleaseControls(sid, _lastBoundReleaseControlsAbilities, effectiveUnitKey);
				InvokeReleaseControlsClickEnabled(controlsView, true);
				LogDirectReleaseControlsBind("kept: " + reason, sid, "cache-fast:" + sid, _lastBoundReleaseControlsAbilities);
				return true;
			}
			if (!ExistingReleaseControlsAlreadyBound(controlsView, _lastBoundReleaseControlsAbilities))
				return false;

			_lastBoundReleaseControlsView = controlsView;
			CacheBoundReleaseControls(sid, _lastBoundReleaseControlsAbilities, unitKey);
			InvokeReleaseControlsClickEnabled(controlsView, true);
			LogDirectReleaseControlsBind("kept: " + reason, sid, "cache-hot:" + sid, _lastBoundReleaseControlsAbilities);
			return true;
		}
		catch (Exception ex)
		{
			if (_loggedDirectControlsBind < 8)
			{
				_loggedDirectControlsBind++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release controls hot-path cache check failed for sid='" + sid + "': " + ex.Message);
			}
			return false;
		}
	}

	private static bool TryKeepCachedReleaseControlsActiveSameSid(BhUnitControlsView controlsView, string sid, string reason)
	{
		try
		{
			if (controlsView == null
			    || !ReferenceEquals(controlsView, _lastBoundReleaseControlsView)
			    || !IsSameCachedReleaseControlsSid(sid)
			    || _lastBoundReleaseControlsAbilities == null
			    || _lastBoundReleaseControlsAbilities.Length <= 0)
			{
				return false;
			}
			if (!CachedReleaseControlsStillInstalledFast(controlsView, sid, _lastBoundReleaseControlsAbilities, _lastBoundReleaseControlsUnitKey))
				return false;

			InvokeReleaseControlsClickEnabled(controlsView, true);
			LogDirectReleaseControlsBind("kept: " + reason, sid, "cache-active-fast:" + sid, _lastBoundReleaseControlsAbilities);
			return true;
		}
		catch (Exception ex)
		{
			if (_loggedDirectControlsBind < 8)
			{
				_loggedDirectControlsBind++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release controls active-cache check failed for sid='" + sid + "': " + ex.Message);
			}
			return false;
		}
	}

	private static long GetCachedReleaseHotPathUnitKey(string sid, long eventUnitKey)
	{
		if (eventUnitKey != 0)
			return eventUnitKey;
		try
		{
			if (_lastBoundReleaseControlsUnitKey == 0
			    || _lastTurnViewUnit == null
			    || _lastTurnViewUnitKey == 0
			    || _lastTurnViewUnitKey != _lastBoundReleaseControlsUnitKey
			    || !string.Equals(_lastTurnViewUnitSid, sid, StringComparison.OrdinalIgnoreCase))
			{
				return 0;
			}
			if (GetIl2CppObjectKey(_lastTurnViewUnit) != _lastTurnViewUnitKey)
				return 0;
			if (!string.Equals(SafeExtractSidFieldOnly(_lastTurnViewUnit), sid, StringComparison.OrdinalIgnoreCase))
				return 0;
			return _lastTurnViewUnitKey;
		}
		catch
		{
			return 0;
		}
	}

	private static bool CachedReleaseControlsStillInstalledFast(BhUnitControlsView controlsView, string sid, Array abilities, long unitKey)
	{
		try
		{
			if (controlsView == null || abilities == null || abilities.Length <= 0)
				return false;
			if (!ReferenceEquals(controlsView, _lastBoundReleaseControlsView))
				return false;
			if (!IsSameCachedReleaseControlsSid(sid))
				return false;
			if (unitKey != 0 && _lastBoundReleaseControlsUnitKey != 0 && unitKey != _lastBoundReleaseControlsUnitKey)
				return false;
			var current = GetReleaseCurrentAbilityArray(controlsView);
			if (current == null || current.Length != abilities.Length)
				return false;
			for (var i = 0; i < abilities.Length; i++)
			{
				var cached = abilities.GetValue(i);
				var live = current.GetValue(i);
				if (!ReferenceEquals(cached, live))
				{
					var cachedKey = GetIl2CppObjectKey(cached);
					var liveKey = GetIl2CppObjectKey(live);
					if (cachedKey == 0 || liveKey == 0 || cachedKey != liveKey)
						return false;
				}
			}

			for (var i = 0; i < abilities.Length; i++)
			{
				if (!ActiveReleaseControlsContainAbilityFast(controlsView, abilities.GetValue(i)))
					return false;
			}
			return true;
		}
		catch { }
		return false;
	}

	private static bool ActiveReleaseControlsContainAbilityFast(BhUnitControlsView controlsView, object ability)
	{
		try
		{
			var views = controlsView?.abilities;
			if (views == null || ability == null)
				return false;
			var abilityKey = GetIl2CppObjectKey(ability);
			for (var i = 0; i < views.Count; i++)
			{
				var view = views[i];
				var go = view != null ? view.gameObject : null;
				if (go == null || !go.activeInHierarchy || !IsReleaseAbilityViewClickReady(view))
					continue;
				var viewAbility = GetReleaseAbility(view);
				if (ReferenceEquals(viewAbility, ability))
					return true;
				var viewAbilityKey = GetIl2CppObjectKey(viewAbility);
				if (abilityKey != 0 && viewAbilityKey != 0 && abilityKey == viewAbilityKey)
					return true;
			}
		}
		catch { }
		return false;
	}

	private static bool TryKeepOrRestoreCachedControls(BhUnitControlsView controlsView, string sid, string reason)
	{
		return false;
	}

	internal static void ProcessHotkeyFallback()
	{
		// Legacy fallback intentionally disabled; release hotkeys route through the current controls path.
	}

	private static int GetPressedFallbackAbilitySlot()
	{
		if (Input.GetKeyDown(KeyCode.Alpha1) || Input.GetKeyDown(KeyCode.Keypad1))
			return 0;
		if (Input.GetKeyDown(KeyCode.Alpha2) || Input.GetKeyDown(KeyCode.Keypad2))
			return 1;
		if (Input.GetKeyDown(KeyCode.Alpha3) || Input.GetKeyDown(KeyCode.Keypad3))
			return 2;
		if (Input.GetKeyDown(KeyCode.Alpha4) || Input.GetKeyDown(KeyCode.Keypad4))
			return 3;
		if (Input.GetKeyDown(KeyCode.Alpha5) || Input.GetKeyDown(KeyCode.Keypad5))
			return 4;
		return -1;
	}

	private static int ClearAndHideUnitControls(BhUnitControlsView controlsView)
	{
		if (controlsView == null)
			return 0;

		var hidden = 0;
		try
		{
			controlsView.Clear();
		}
		catch { }

		try
		{
			var views = controlsView.abilities;
			if (views == null)
				return hidden;
			for (var i = 0; i < views.Count; i++)
			{
				var abilityView = views[i];
				var go = abilityView != null ? abilityView.gameObject : null;
				if (go == null || !go.activeSelf)
					continue;
				go.SetActive(false);
				hidden++;
			}
		}
		catch { }

		return hidden;
	}

	private static void PostfixAbilityViewBindAvailability(BhUnitAbilityView __instance, object __0)
	{
	}

	private static bool PrefixControlsViewClick(BhUnitControlsView __instance, BhUnitAbilityView __0, out bool __state)
	{
		__state = false;
		return true;
	}

	private static void PostfixControlsViewClick(BhUnitControlsView __instance, BhUnitAbilityView __0, bool __state)
	{
	}

	private static bool PrefixControlsViewHotkey(BhUnitControlsView __instance, object __0, HotkeyAbilityArgs __1)
	{
		return true;
	}

	private static bool PrefixReleaseControlsViewHotkey(BhUnitControlsView __instance, object __0, HotkeyAbilityArgs __1)
	{
		try
		{
			if (__instance == null || __1 == null || __1.isEsc || __1.isReturnDeselect)
				return true;
			if (!IsReleaseHotkeyControlsContext(__instance))
			{
				LogReleaseHotkeyDecision("native: non-custom context", __instance, __1.idButton, null);
				return true;
			}

			var releaseView = FindReleaseHotkeyView(__instance, __1.idButton);
			if (releaseView == null)
			{
				LogReleaseHotkeyDecision("native: no slot match", __instance, __1.idButton, null);
				return true;
			}
			InvokeReleaseControlsClick(__instance, releaseView);
			LogReleaseHotkeyDecision("handled: click", __instance, __1.idButton, releaseView);
			LogReleaseAbilityClick("controls.hotkey-click", releaseView, __instance);
			return false;
		}
		catch (Exception ex)
		{
			if (_loggedControlsSelection < 6)
			{
				_loggedControlsSelection++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release hotkey sync failed: " + ex.Message);
			}
			return true;
		}
	}

	private static BhUnitAbilityView FindReleaseHotkeyView(BhUnitControlsView controlsView, int idButton)
	{
		if (idButton > 0)
		{
			var shiftedIndex = idButton - 1;
			if (IsReleaseHotkeyActionBarSlot(controlsView, shiftedIndex))
				return TryGetReleaseHotkeyViewAt(controlsView, shiftedIndex);
		}
		return TryGetReleaseHotkeyViewAt(controlsView, idButton);
	}

	private static BhUnitAbilityView TryGetReleaseHotkeyViewAt(BhUnitControlsView controlsView, int index)
	{
		try
		{
			var views = controlsView?.abilities;
			if (views == null || index < 0 || index >= views.Count)
				return null;
			var view = views[index];
			return IsHotkeyableReleaseActionBarView(controlsView, view) ? view : null;
		}
		catch
		{
			return null;
		}
	}

	private static bool IsHotkeyableReleaseActionBarView(BhUnitControlsView controlsView, BhUnitAbilityView abilityView)
	{
		try
		{
			var go = abilityView != null ? abilityView.gameObject : null;
			if (!IsReleaseHotkeyControlsContext(controlsView) || go == null || !go.activeInHierarchy)
				return false;

			var ability = GetReleaseAbility(abilityView);
			return ability != null
				&& CanShowOnActionBar(ability)
				&& IsReleaseAbilityViewClickReady(abilityView)
				&& ReleaseHotkeyControlsContainAbility(controlsView, ability);
		}
		catch
		{
			return false;
		}
	}

	private static bool IsReleaseHotkeyActionBarSlot(BhUnitControlsView controlsView, int index)
	{
		try
		{
			var views = controlsView?.abilities;
			if (views == null || index < 0 || index >= views.Count)
				return false;
			var view = views[index];
			var go = view != null ? view.gameObject : null;
			if (!IsReleaseHotkeyControlsContext(controlsView) || go == null || !go.activeInHierarchy)
				return false;

			var ability = GetReleaseAbility(view);
			return ability != null
				&& CanShowOnActionBar(ability)
				&& ReleaseHotkeyControlsContainAbility(controlsView, ability);
		}
		catch
		{
			return false;
		}
	}

	private static bool IsRecoveredReleaseControlsContext(BhUnitControlsView controlsView)
	{
		return controlsView != null
			&& ReferenceEquals(controlsView, _lastBoundReleaseControlsView)
			&& IsSameCachedReleaseControlsSid(_lastBoundReleaseControlsSid)
			&& _lastBoundReleaseControlsAbilities != null
			&& _lastBoundReleaseControlsAbilities.Length > 0
			&& CachedReleaseControlsAlreadyBound(controlsView, _lastBoundReleaseControlsSid, _lastBoundReleaseControlsAbilities, _lastBoundReleaseControlsUnitKey);
	}

	private static bool IsReleaseHotkeyControlsContext(BhUnitControlsView controlsView)
	{
		return controlsView != null
			&& ReferenceEquals(controlsView, _lastBoundReleaseControlsView)
			&& IsSameCachedReleaseControlsSid(_lastBoundReleaseControlsSid)
			&& _lastBoundReleaseControlsAbilities != null
			&& _lastBoundReleaseControlsAbilities.Length > 0;
	}

	private static bool ReleaseHotkeyControlsContainAbility(BhUnitControlsView controlsView, object ability)
	{
		return ReleaseControlsContainAbility(controlsView, ability)
		       || CachedReleaseControlsContainAbility(controlsView, ability);
	}

	private static void LogReleaseHotkeyDecision(string action, BhUnitControlsView controlsView, int idButton, BhUnitAbilityView view)
	{
		if (!IsDiagnosticEnabled())
			return;
		if (_loggedReleaseHotkey >= 30)
			return;
		_loggedReleaseHotkey++;
		try
		{
			var views = controlsView?.abilities;
			Plugin.LogSource?.LogInfo(
				"Homm3Import release ability hotkey: "
				+ action
				+ " idButton=" + idButton
				+ " cachedSid='" + (_lastBoundReleaseControlsSid ?? "?") + "'"
				+ " views=" + (views != null ? views.Count : -1)
				+ " selected=" + (GetReleaseSelectedAbilityView(controlsView) != null)
				+ " ability=" + DescribeReleaseAbility(GetReleaseAbility(view))
				+ ".");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogInfo("Homm3Import release ability hotkey: " + action + " idButton=" + idButton + " diag failed: " + ex.Message);
		}
	}

	private static bool IsAbilityViewEnabled(BhUnitAbilityView view)
	{
		if (view == null)
			return false;
		try
		{
			if (AbilityViewEnabledByInstanceId.TryGetValue(view.GetInstanceID(), out var enabled))
				return enabled;
		}
		catch { }
		return true;
	}

	private static void EnsureHotkeyFallback()
	{
		if (_hotkeyFallbackAttached)
			return;

		try
		{
			if (!_hotkeyFallbackRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3RecoveredHudHotkeyFallback>();
				_hotkeyFallbackRegistered = true;
			}

			var go = new GameObject("Homm3RecoveredHudHotkeyFallback");
			go.hideFlags = HideFlags.HideAndDontSave;
			go.AddComponent<Homm3RecoveredHudHotkeyFallback>();
			UnityEngine.Object.DontDestroyOnLoad(go);
			_hotkeyFallbackAttached = true;
			Plugin.LogSource?.LogInfo("Homm3Import selected-unit HUD controls fallback hotkeys attached.");
		}
		catch (Exception ex)
		{
			if (_loggedControlsSelection < 6)
			{
				_loggedControlsSelection++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD controls fallback hotkey attach failed: " + ex.Message);
			}
		}
	}

	private static bool IsCachedControlsSid(string sid)
	{
		return Homm3CustomFactionRegistry.IsCustomUnitSid(sid);
	}

	private static bool IsSameCachedControlsSid(string sid)
	{
		return IsCachedControlsSid(sid)
			&& string.Equals(sid, _lastBoundControlsSid, StringComparison.OrdinalIgnoreCase);
	}

	private static bool IsExplicitActionBarAbility(AbilityViewConfig view)
	{
		if (view == null)
			return false;

		var name = SafeString(view.name);
		if (string.Equals(name, "common_attack_1_name", StringComparison.OrdinalIgnoreCase))
			return string.Equals(SafeString(view.abilityType), "Ability_type_attack_alt", StringComparison.OrdinalIgnoreCase);
		if (name.StartsWith("base_passive_", StringComparison.OrdinalIgnoreCase))
			return false;

		var abilityType = SafeString(view.abilityType);
		if (abilityType.StartsWith("Ability_type_", StringComparison.OrdinalIgnoreCase))
			return true;

		var info = SafeString(view.infoDescription);
		return info.StartsWith("ability_", StringComparison.OrdinalIgnoreCase);
	}

	private static object TryGetReleaseAbilityManager(Unit unit)
	{
		if (unit == null)
			return null;
		for (var current = unit.GetType(); current != null; current = current.BaseType)
		{
			var field = FindReleaseAbilityManagerField(current);
			if (field != null)
			{
				try
				{
					var manager = field.GetValue(unit);
					if (IsReleaseAbilityManager(manager))
						return manager;
				}
				catch { }
			}

			var getter = FindReleaseAbilityManagerGetter(current);
			if (getter != null)
			{
				try
				{
					var manager = getter.Invoke(unit, null);
					if (IsReleaseAbilityManager(manager))
						return manager;
				}
				catch
				{
				}
			}
		}
		var hints = GameSymbols.SelectedUnitHud.AbilityManagerFields ?? Array.Empty<string>();
		for (var i = 0; i < hints.Length; i++)
		{
			var manager = TryReadNativeObjectMember(unit, hints[i], GameInteropTypes.ReleaseAbilityManagerType);
			if (IsReleaseAbilityManager(manager))
				return manager;
		}
		return TryCreateReleaseAbilityManagerFromFieldObject(unit);
	}

	private static object TryCreateReleaseAbilityManagerFromFieldObject(Unit unit)
	{
		if (unit == null)
			return null;
		var abilityManagerType = GameInteropTypes.ReleaseAbilityManagerType;
		if (abilityManagerType == null)
			return null;
		var init = FindReleaseAbilityManagerFieldObjectInit(abilityManagerType, unit.GetType());
		if (init == null)
			return null;
		try
		{
			var manager = Activator.CreateInstance(abilityManagerType);
			if (!IsReleaseAbilityManager(manager))
				return null;
			init.Invoke(manager, new object[] { unit });
			if (_loggedReleaseManagerInit < 8)
			{
				_loggedReleaseManagerInit++;
				LogDiagnostic(
					"Homm3Import selected-unit HUD release controls: initialized transient ability manager via "
					+ init.Name
					+ " for unitType='"
					+ unit.GetType().FullName
					+ "'.");
			}
			return manager;
		}
		catch (Exception ex)
		{
			if (_loggedReleaseManagerInit < 8)
			{
				_loggedReleaseManagerInit++;
				Plugin.LogSource?.LogWarning(
					"Homm3Import selected-unit HUD release controls: transient ability manager init failed via "
					+ init.Name
					+ ": "
					+ ex.Message);
			}
			return null;
		}
	}

	private static MethodInfo FindReleaseAbilityManagerFieldObjectInit(Type managerType, Type unitType)
	{
		if (managerType == null || unitType == null)
			return null;
		MethodInfo[] methods;
		try
		{
			methods = managerType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
		}
		catch
		{
			return null;
		}

		var hints = GameSymbols.SelectedUnitHud.AbilityManagerFieldObjectInit.NameHints ?? Array.Empty<string>();
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			for (var j = 0; j < methods.Length; j++)
			{
				var method = methods[j];
				if (!string.Equals(method.Name, hint, StringComparison.Ordinal))
					continue;
				if (IsReleaseAbilityManagerFieldObjectInit(method, unitType))
					return method;
			}
		}
		return null;
	}

	private static bool IsReleaseAbilityManagerFieldObjectInit(MethodInfo method, Type unitType)
	{
		if (method == null || unitType == null)
			return false;
		if (method.ReturnType != typeof(void))
			return false;
		var ps = method.GetParameters();
		return ps.Length == 1 && ps[0].ParameterType.IsAssignableFrom(unitType);
	}

	private static FieldInfo FindReleaseAbilityManagerField(Type type)
	{
		if (type == null)
			return null;
		var abilityManagerType = GameInteropTypes.ReleaseAbilityManagerType;
		if (abilityManagerType == null)
			return null;
		FieldInfo[] fields;
		try
		{
			fields = type.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
		}
		catch
		{
			return null;
		}

		var hints = GameSymbols.SelectedUnitHud.AbilityManagerFields ?? Array.Empty<string>();
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrEmpty(hint))
				continue;
			for (var j = 0; j < fields.Length; j++)
			{
				var field = fields[j];
				if (string.Equals(field.Name, hint, StringComparison.Ordinal) && GameInteropTypes.TypesMatch(field.FieldType, abilityManagerType))
					return field;
			}
		}
		FieldInfo unique = null;
		for (var i = 0; i < fields.Length; i++)
		{
			var field = fields[i];
			if (!GameInteropTypes.TypesMatch(field.FieldType, abilityManagerType))
				continue;
			if (unique != null)
				return null;
			unique = field;
		}
		return unique;
	}

	private static MethodInfo FindReleaseAbilityManagerGetter(Type type)
	{
		if (type == null)
			return null;
		MethodInfo[] methods;
		try
		{
			methods = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
		}
		catch
		{
			return null;
		}

		var hints = GameSymbols.SelectedUnitHud.AbilityManagerGetter.NameHints ?? Array.Empty<string>();
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrEmpty(hint))
				continue;
			for (var j = 0; j < methods.Length; j++)
			{
				var method = methods[j];
				if (string.Equals(method.Name, hint, StringComparison.Ordinal) && IsReleaseAbilityManagerGetter(method))
					return method;
			}
		}
		return null;
	}

	private static bool IsReleaseAbilityManagerGetter(MethodInfo method)
	{
		var abilityManagerType = GameInteropTypes.ReleaseAbilityManagerType;
		if (method == null || abilityManagerType == null)
			return false;
		if (!GameInteropTypes.TypesMatch(method.ReturnType, abilityManagerType))
			return false;
		var ps = method.GetParameters();
		return ps.Length == 0;
	}
	private static void ValidateRequiredReleaseActionBarSurface(ManualLogSource log)
	{
		var abilityManagerType = GameInteropTypes.ReleaseAbilityManagerType;
		var abilityWrapperType = GameInteropTypes.ReleaseAbilityWrapperType;
		if (abilityManagerType == null)
			throw new MissingMemberException(typeof(Unit).FullName, "dxx ability manager field/getter");
		if (abilityWrapperType == null)
			throw new MissingMemberException(typeof(Unit).FullName, "dxy ability wrapper type");
		var hasManagerSurface = HasReleaseAbilityManagerSurface(typeof(Unit));
		var hasFieldObjectManagerInit = FindReleaseAbilityManagerFieldObjectInit(abilityManagerType, typeof(Unit)) != null;
		if (!hasManagerSurface && !hasFieldObjectManagerInit)
		{
			if (!IsReleaseConfigActionBarFallbackEnabled())
				throw new MissingMemberException(typeof(Unit).FullName, abilityManagerType.Name + " field/getter or field-object init");
			log?.LogWarning(
				"Homm3Import release selected-unit HUD: Unit did not expose a unique "
				+ abilityManagerType.Name
				+ " field/getter or field-object init during startup validation; explicit config fallback is enabled.");
		}
		var bucket = FindReleaseAbilityBucketMethod(abilityManagerType);
		if (bucket == null && (!IsReleaseConfigActionBarFallbackEnabled() || !HasReleaseConfigAbilitySurface()))
			throw new MissingMethodException(abilityManagerType.FullName, "ability manager bucket or UnitLogicConfig/UnitViewConfig ability buckets");
		if (FindReleaseControlsBindMethod(typeof(BhUnitControlsView)) == null)
			throw new MissingMethodException(typeof(BhUnitControlsView).FullName, "controls bind (abilities, ability, bool)");
		var clickEnabled = FindReleaseControlsClickEnabledMethod(typeof(BhUnitControlsView));
		if (clickEnabled == null)
			throw new MissingMethodException(typeof(BhUnitControlsView).FullName, "controls setClickEnabled(bool)");
		if (FindReleaseControlsSelectMethod(typeof(BhUnitControlsView)) == null)
			throw new MissingMethodException(typeof(BhUnitControlsView).FullName, "controls select(ability)");
		var abilityClicked = FindMethodByNameAndArity(typeof(BhUnitAbilityView), "OnClicked", 0);
		if (abilityClicked == null)
			throw new MissingMethodException(typeof(BhUnitAbilityView).FullName, "OnClicked()");
		var controlsClickMethods = FindReleaseControlsClickMethods(typeof(BhUnitControlsView));
		if (controlsClickMethods.Count == 0)
			throw new MissingMethodException(typeof(BhUnitControlsView).FullName, "controls click(BhUnitAbilityView)");
		if (FindReleaseControlsHotkeyMethod(typeof(BhUnitControlsView)) == null)
			throw new MissingMethodException(typeof(BhUnitControlsView).FullName, "ControlsHotkey(object,HotkeyAbilityArgs)");
		var basicCommandsType = FindReleaseBasicCommandsType();
		if (basicCommandsType == null)
			throw new MissingMemberException("Hex.UI.BhUnitBasicCommands", "selected-unit basic command type");
		var waitRefresh = FindReleaseBasicCommandsRefreshMethod(basicCommandsType, GameSymbols.SelectedUnitHud.BasicCommandsWaitRefresh);
		var skipRefresh = FindReleaseBasicCommandsRefreshMethod(basicCommandsType, GameSymbols.SelectedUnitHud.BasicCommandsSkipRefresh);
		if (waitRefresh == null)
			throw new MissingMethodException(basicCommandsType.FullName, "wait refresh(Unit)");
		if (skipRefresh == null)
			throw new MissingMethodException(basicCommandsType.FullName, "skip refresh(Unit)");
		log?.LogInfo(
			"Homm3Import release selected-unit HUD action-bar surface required; bucket="
			+ (bucket?.Name ?? "explicit-unit-config-fallback")
			+ ", managerSurface="
			+ (hasManagerSurface ? "unit-member" : hasFieldObjectManagerInit ? "field-object-init" : "none")
			+ ", clickEnabled="
			+ clickEnabled.Name
			+ ", abilityClicked="
			+ abilityClicked.Name
			+ ", controlsClick="
			+ DescribeMethods(controlsClickMethods)
			+ ", basicCommands="
			+ waitRefresh.Name
			+ "/"
			+ skipRefresh.Name
			+ ".");
	}

	private static bool HasReleaseAbilityManagerSurface(Type type)
	{
		if (type == null)
			return false;
		for (var current = type; current != null; current = current.BaseType)
		{
			if (FindReleaseAbilityManagerField(current) != null)
				return true;
			if (FindReleaseAbilityManagerGetter(current) != null)
				return true;
		}
		return false;
	}

	private static void InvokeReleaseControlsBind(
		BhUnitControlsView controlsView,
		Array abilities,
		object selected)
	{
		if (controlsView == null || abilities == null)
			return;
		var method = FindReleaseControlsBindMethod(controlsView.GetType());
		if (method == null)
			throw new MissingMethodException(controlsView.GetType().FullName, "bejr(abilities, ability, bool)");
		var ps = method.GetParameters();
		var abilityArg = CoerceReleaseAbilityArrayArgument(abilities, ps[0].ParameterType);
		var selectedArg = CoerceReleaseAbilityWrapperArgument(selected, ps[1].ParameterType);
		method.Invoke(controlsView, new[] { abilityArg, selectedArg, true });
	}

	private static MethodInfo FindReleaseControlsBindMethod(Type type)
	{
		if (type == null)
			return null;
		var hinted = FindReleaseControlsBindMethodByNames(type, GameSymbols.SelectedUnitHud.ControlsBind.NameHints);
		if (IsReleaseControlsBindMethod(hinted))
			return hinted;
		var wrapperType = GameInteropTypes.ReleaseAbilityWrapperType;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (IsReleaseControlsBindMethod(method, wrapperType))
				return method;
		}
		return null;
	}

	private static MethodInfo FindReleaseControlsBindMethodByNames(Type type, string[] names)
	{
		if (type == null || names == null || names.Length == 0)
			return null;
		var methods = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			MethodInfo match = null;
			foreach (var method in methods)
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal) || !IsReleaseControlsBindMethod(method))
					continue;
				if (match != null)
					return null;
				match = method;
			}
			if (match != null)
				return match;
		}
		return null;
	}

	private static bool IsReleaseControlsBindMethod(MethodInfo method, Type wrapperType = null)
	{
		if (method == null || method.ReturnType != typeof(void))
			return false;
		wrapperType ??= GameInteropTypes.ReleaseAbilityWrapperType;
		var ps = method.GetParameters();
		return ps.Length == 3
		       && ParameterTypesMatch(ps[2].ParameterType, typeof(bool))
		       && IsReleaseAbilityArrayParameterType(ps[0].ParameterType, wrapperType)
		       && IsReleaseAbilityWrapperParameterType(ps[1].ParameterType, wrapperType);
	}

	private static void InvokeReleaseControlsClick(BhUnitControlsView controlsView, BhUnitAbilityView view)
	{
		if (controlsView == null || view == null)
			return;
		var methods = FindReleaseControlsClickMethods(controlsView.GetType());
		if (methods.Count != 1)
			throw new MissingMethodException(controlsView.GetType().FullName, "controls click(BhUnitAbilityView)");
		methods[0].Invoke(controlsView, new object[] { view });
	}
	private static void InvokeReleaseControlsClickEnabled(BhUnitControlsView controlsView, bool enabled)
	{
		if (controlsView == null)
			return;
		var method = FindReleaseControlsClickEnabledMethod(controlsView.GetType());
		if (method == null)
			throw new MissingMethodException(controlsView.GetType().FullName, "controls setClickEnabled(bool)");
		method.Invoke(controlsView, new object[] { enabled });
	}

	private static void RefreshReleaseBasicCommands(object basicCommands, Unit unit, string sid)
	{
		if (basicCommands == null || unit == null)
			return;
		var type = basicCommands.GetType();
		var waitMethod = FindReleaseBasicCommandsRefreshMethod(type, GameSymbols.SelectedUnitHud.BasicCommandsWaitRefresh);
		var skipMethod = FindReleaseBasicCommandsRefreshMethod(type, GameSymbols.SelectedUnitHud.BasicCommandsSkipRefresh);
		try
		{
			if (waitMethod == null)
				throw new MissingMethodException(type.FullName, "wait refresh(Unit)");
			if (skipMethod == null)
				throw new MissingMethodException(type.FullName, "skip refresh(Unit)");
			waitMethod.Invoke(basicCommands, new object[] { unit });
			skipMethod.Invoke(basicCommands, new object[] { unit });
			if (_loggedDirectControlsBind < 12)
			{
				_loggedDirectControlsBind++;
				LogDiagnostic(
					"Homm3Import selected-unit HUD release basic commands: refreshed wait/skip buttons via "
					+ waitMethod.Name
					+ "/"
					+ skipMethod.Name
					+ " for sid='"
					+ (sid ?? "?")
					+ "'.");
			}
		}
		catch (Exception ex)
		{
			if (_loggedDirectControlsBind < 12)
			{
				_loggedDirectControlsBind++;
				Plugin.LogSource?.LogWarning(
					"Homm3Import selected-unit HUD release basic command refresh failed for sid='"
					+ (sid ?? "?")
					+ "': "
					+ ex.Message);
			}
		}
	}

	private static Type FindReleaseBasicCommandsType()
	{
		var names = GameSymbols.SelectedUnitHud.BasicCommandsTypeNames ?? Array.Empty<string>();
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = GameMember.FindType("battle.selectedUnit.basicCommands." + name, name);
			if (type != null)
				return type;
		}
		return null;
	}

	private static MethodInfo FindReleaseBasicCommandsRefreshMethod(Type type, GameSymbols.MethodSymbol symbol)
	{
		if (type == null)
			return null;
		return GameMember.FindFirstMethodByNames(
			type,
			new[] { typeof(Unit) },
			symbol);
	}

	private static void InvokeReleaseControlsSelect(BhUnitControlsView controlsView, object ability)
	{
		if (controlsView == null)
			return;
		var method = FindReleaseControlsSelectMethod(controlsView.GetType());
		if (method == null)
			throw new MissingMethodException(controlsView.GetType().FullName, "controls select(ability wrapper)");
		var ps = method.GetParameters();
		method.Invoke(controlsView, new[] { CoerceReleaseAbilityWrapperArgument(ability, ps[0].ParameterType) });
	}

	private static MethodInfo FindReleaseControlsSelectMethod(Type type)
	{
		if (type == null)
			return null;
		var wrapperType = GameInteropTypes.ReleaseAbilityWrapperType;
		if (wrapperType == null)
			return null;
		var named = GameMember.FindMethodsByNames(
			type,
			new[] { wrapperType },
			GameSymbols.SelectedUnitHud.ControlsSelect);
		if (named.Length > 0)
		{
			for (var i = 0; i < named.Length; i++)
			{
				if (IsReleaseControlsSelectMethod(named[i], wrapperType))
					return named[i];
			}
		}

		MethodInfo unique = null;
		var matches = 0;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (!IsReleaseControlsSelectMethod(method, wrapperType))
				continue;
			matches++;
			unique = matches == 1 ? method : null;
		}
		return matches == 1 ? unique : null;
	}

	private static bool IsReleaseControlsSelectMethod(MethodInfo method, Type wrapperType)
	{
		if (method == null || method.IsSpecialName || method.ReturnType != typeof(void))
			return false;
		var ps = method.GetParameters();
		return ps.Length == 1 && IsReleaseAbilityWrapperParameterType(ps[0].ParameterType, wrapperType);
	}

	private static MethodInfo FindReleaseControlsHotkeyMethod(Type type)
	{
		if (type == null)
			return null;
		return GameMember.FindFirstMethod(
			type,
			typeof(void),
			new[] { typeof(object), typeof(HotkeyAbilityArgs) },
			GameSymbols.SelectedUnitHud.ControlsHotkey);
	}

	private static MethodInfo FindReleaseControlsClickEnabledMethod(Type type)
	{
		if (type == null)
			return null;
		return GameMember.FindFirstMethod(
			type,
			typeof(void),
			new[] { typeof(bool) },
			GameSymbols.SelectedUnitHud.ControlsClickEnabled);
	}

	private static Array InvokeReleaseAbilityBucket(object manager, EAbilityType type)
	{
		if (manager == null)
			return null;
		var method = FindReleaseAbilityBucketMethod(manager.GetType());
		if (method == null)
			return null;
		try { return CoerceReleaseAbilityArray(method.Invoke(manager, new object[] { type })); }
		catch { return null; }
	}

	private static MethodInfo FindReleaseAbilityBucketMethod(Type type)
	{
		if (type == null)
			return null;
		MethodInfo[] methods;
		try
		{
			methods = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
		}
		catch
		{
			return null;
		}

		var hints = GameSymbols.SelectedUnitHud.AbilityBucket.NameHints ?? Array.Empty<string>();
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrEmpty(hint))
				continue;
			for (var j = 0; j < methods.Length; j++)
			{
				var method = methods[j];
				if (string.Equals(method.Name, hint, StringComparison.Ordinal) && IsReleaseAbilityBucketMethod(method))
					return method;
			}
		}
		for (var i = 0; i < methods.Length; i++)
		{
			var method = methods[i];
			if (IsReleaseAbilityBucketMethod(method))
				return method;
		}
		return null;
	}

	private static bool IsReleaseAbilityBucketMethod(MethodInfo method)
	{
		if (method == null)
			return false;
		var wrapperType = GameInteropTypes.ReleaseAbilityWrapperType;
		if (wrapperType == null)
			return false;
		if (!GameInteropTypes.IsReleaseAbilityArrayReturnType(method.ReturnType, wrapperType))
			return false;
		var ps = method.GetParameters();
		return ps.Length == 1 && ps[0].ParameterType == typeof(EAbilityType);
	}

	private static AbilityLogicConfig GetReleaseAbilityLogic(object ability)
	{
		return TryGetFirstMemberValue(ability, GameSymbols.SelectedUnitHud.AbilityLogicFields) as AbilityLogicConfig;
	}

	private static AbilityViewConfig GetReleaseAbilityView(object ability)
	{
		return TryGetFirstMemberValue(ability, GameSymbols.SelectedUnitHud.AbilityViewFields) as AbilityViewConfig;
	}

	private static object FindCurrentSelectedReleaseAbility(BhUnitControlsView controlsView, Array abilities)
	{
		try
		{
			if (controlsView == null || abilities == null || abilities.Length <= 0)
				return null;

			var selectedView = GetReleaseSelectedAbilityView(controlsView);
			if (selectedView == null)
				return null;

			var selected = GetReleaseAbility(selectedView);
			if (selected == null)
				return null;

			for (var i = 0; i < abilities.Length; i++)
			{
				if (SameReleaseAbility(abilities.GetValue(i), selected))
					return selected;
			}
		}
		catch { }

		return null;
	}

	private static bool ExistingReleaseControlsAlreadyBound(BhUnitControlsView controlsView, Array abilities)
	{
		try
		{
			if (controlsView == null || abilities == null || abilities.Length <= 0)
				return false;

			var current = GetReleaseCurrentAbilityArray(controlsView);
			if (current == null || current.Length != abilities.Length)
				return false;

			for (var i = 0; i < abilities.Length; i++)
			{
				if (!SameReleaseAbility(current.GetValue(i), abilities.GetValue(i)))
					return false;
			}

			return ActiveReleaseControlsContainAbilities(controlsView, abilities);
		}
		catch
		{
			return false;
		}
	}

	private static bool CachedReleaseControlsAlreadyBound(BhUnitControlsView controlsView, string sid, Array abilities, long unitKey)
	{
		try
		{
			if (controlsView == null || abilities == null || abilities.Length <= 0)
				return false;
			if (!ReferenceEquals(controlsView, _lastBoundReleaseControlsView))
				return false;
			if (!IsSameCachedReleaseControlsSid(sid))
				return false;
			if (unitKey != 0 && _lastBoundReleaseControlsUnitKey != 0 && unitKey != _lastBoundReleaseControlsUnitKey)
				return false;
			if (_lastBoundReleaseControlsAbilities == null || _lastBoundReleaseControlsAbilities.Length != abilities.Length)
				return false;

			for (var i = 0; i < abilities.Length; i++)
			{
				if (!SameReleaseAbility(_lastBoundReleaseControlsAbilities.GetValue(i), abilities.GetValue(i)))
					return false;
			}

			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool CachedReleaseControlsContainAbility(BhUnitControlsView controlsView, object ability)
	{
		try
		{
			if (controlsView == null || ability == null)
				return false;
			if (!ReferenceEquals(controlsView, _lastBoundReleaseControlsView))
				return false;
			if (!IsSameCachedReleaseControlsSid(_lastBoundReleaseControlsSid))
				return false;
			if (_lastBoundReleaseControlsAbilities == null || _lastBoundReleaseControlsAbilities.Length <= 0)
				return false;
			for (var i = 0; i < _lastBoundReleaseControlsAbilities.Length; i++)
			{
				if (SameReleaseAbility(_lastBoundReleaseControlsAbilities.GetValue(i), ability))
					return true;
			}
		}
		catch
		{
		}
		return false;
	}

	private static bool ActiveReleaseControlsContainAbilities(BhUnitControlsView controlsView, Array abilities)
	{
		try
		{
			var views = controlsView?.abilities;
			if (views == null || abilities == null || abilities.Length <= 0)
				return false;

			for (var i = 0; i < abilities.Length; i++)
			{
				if (!ActiveReleaseControlsContainAbility(views, abilities.GetValue(i)))
					return false;
			}
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool ActiveReleaseControlsContainAbility(Il2CppSystem.Collections.Generic.List<BhUnitAbilityView> views, object ability)
	{
		for (var i = 0; i < views.Count; i++)
		{
			var view = views[i];
			var go = view != null ? view.gameObject : null;
			if (go == null || !go.activeSelf)
				continue;
			if (SameReleaseAbility(GetReleaseAbility(view), ability) && IsReleaseAbilityViewClickReady(view))
				return true;
		}
		return false;
	}

	private static bool ReleaseControlsContainAbility(BhUnitControlsView controlsView, object ability)
	{
		try
		{
			var current = GetReleaseCurrentAbilityArray(controlsView);
			if (current == null || ability == null)
				return false;
			for (var i = 0; i < current.Length; i++)
			{
				if (SameReleaseAbility(current.GetValue(i), ability))
					return true;
			}
		}
		catch { }
		return false;
	}

	private static bool SameReleaseAbility(object left, object right)
	{
		if (left == null || right == null)
			return false;
		if (ReferenceEquals(left, right))
			return true;
		var leftKey = GetIl2CppObjectKey(left);
		var rightKey = GetIl2CppObjectKey(right);
		if (leftKey != 0 && rightKey != 0 && leftKey == rightKey)
			return true;

		try
		{
			var leftView = GetReleaseAbilityView(left);
			var rightView = GetReleaseAbilityView(right);
			var leftLogic = GetReleaseAbilityLogic(left);
			var rightLogic = GetReleaseAbilityLogic(right);
			var leftName = SafeString(leftView?.name);
			var rightName = SafeString(rightView?.name);
			var leftAbilityType = SafeString(leftView?.abilityType);
			var rightAbilityType = SafeString(rightView?.abilityType);
			var leftAttackType = SafeString(leftLogic?.attackType_);
			var rightAttackType = SafeString(rightLogic?.attackType_);
			var hasIdentity = (!string.IsNullOrWhiteSpace(leftName) && !string.IsNullOrWhiteSpace(rightName))
			                  || (!string.IsNullOrWhiteSpace(leftAbilityType) && !string.IsNullOrWhiteSpace(rightAbilityType));
			return hasIdentity
			       && string.Equals(leftName, rightName, StringComparison.OrdinalIgnoreCase)
			       && string.Equals(leftAbilityType, rightAbilityType, StringComparison.OrdinalIgnoreCase)
			       && string.Equals(leftAttackType, rightAttackType, StringComparison.OrdinalIgnoreCase);
		}
		catch
		{
			return false;
		}
	}

	private static string DescribeReleaseAbility(object ability)
	{
		if (ability == null)
			return "null";
		try
		{
			var view = GetReleaseAbilityView(ability);
			var logic = GetReleaseAbilityLogic(ability);
			return "'"
			       + SafeString(view?.name)
			       + "' type='"
			       + SafeString(view?.abilityType)
			       + "' attackType='"
			       + SafeString(logic?.attackType_)
			       + "'";
		}
		catch
		{
			return ability.GetType().Name;
		}
	}

	private static string DescribeReleaseControls(BhUnitControlsView controlsView)
	{
		if (controlsView == null)
			return "null";
		try
		{
			var current = GetReleaseCurrentAbilityArray(controlsView);
			var selectedView = GetReleaseSelectedAbilityView(controlsView);
			var selected = GetReleaseAbility(selectedView);
			var active = 0;
			var views = controlsView.abilities;
			if (views != null)
			{
				for (var i = 0; i < views.Count; i++)
				{
					var view = views[i];
					if (view != null && view.gameObject != null && view.gameObject.activeInHierarchy)
						active++;
				}
			}
			return "current=" + (current != null ? current.Length : 0)
			       + " activeViews=" + active
			       + " selected=" + DescribeReleaseAbility(selected);
		}
		catch (Exception ex)
		{
			return "diag-failed:" + ex.GetType().Name;
		}
	}

	private static bool IsReleaseAbilityViewClickReady(BhUnitAbilityView view)
	{
		try
		{
			if (view == null)
				return false;
			if (GetReleaseAbilityWrapper(view) == null && GetReleaseAbility(view) == null)
				return false;
			if ((TryGetBoolMember(view, "cgvr", out var clickBlocked) || TryGetBoolMember(view, "cguc", out clickBlocked)) && clickBlocked)
				return false;
			if ((TryGetBoolMember(view, "cgvt", out var clickEnabled) || TryGetBoolMember(view, "cgue", out clickEnabled)) && !clickEnabled)
				return false;
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static string DescribeReleaseAbilityViewState(BhUnitAbilityView view)
	{
		try
		{
			if (view == null)
				return "null";
			var hasNativeAbility = GetReleaseAbilityWrapper(view) != null || GetReleaseAbility(view) != null;
			var hasClickBlocked = TryGetBoolMember(view, "cgvr", out var clickBlocked) || TryGetBoolMember(view, "cguc", out clickBlocked);
			var hasClickEnabled = TryGetBoolMember(view, "cgvt", out var clickEnabled) || TryGetBoolMember(view, "cgue", out clickEnabled);
			return "nativeAbility=" + hasNativeAbility
			       + " clickBlocked=" + (hasClickBlocked ? clickBlocked.ToString() : "?")
			       + " clickEnabled=" + (hasClickEnabled ? clickEnabled.ToString() : "?")
			       + " clickReady=" + IsReleaseAbilityViewClickReady(view);
		}
		catch (Exception ex)
		{
			return "diag-failed:" + ex.GetType().Name;
		}
	}

	private static ReleaseAbilityArrayResult FindReleaseActionBarAbilities(Unit unit, object manager, string sid)
	{
		if (manager != null)
		{
			NormalizeReleaseManagerBuckets(manager, "release-actionbar-query");
			var uiArray = MergeReleaseActionBarAbilityBuckets(manager);
			if (uiArray != null && uiArray.Length > 0)
				return new ReleaseAbilityArrayResult("manager:DefaultAttack+AlternativeAttack+Ability", uiArray);
		}
		else if (!IsReleaseConfigActionBarFallbackEnabled())
		{
			return new ReleaseAbilityArrayResult("manager:unresolved", null);
		}

		if (!IsReleaseConfigActionBarFallbackEnabled())
			return new ReleaseAbilityArrayResult("manager:none", null);

		var configArray = BuildReleaseActionBarAbilitiesFromUnitConfigs(unit, sid);
		if (configArray != null && configArray.Length > 0)
			return new ReleaseAbilityArrayResult("unit-config:DefaultAttack+AlternativeAttack+Ability", configArray);

		return new ReleaseAbilityArrayResult("none", null);
	}

	private static bool IsConclusiveNoReleaseActionBarResult(ReleaseAbilityArrayResult result)
	{
		var source = result.Source ?? string.Empty;
		return string.Equals(source, "manager:none", StringComparison.Ordinal)
		       || string.Equals(source, "none", StringComparison.Ordinal)
		       || source.IndexOf("no-actionbar-abilities", StringComparison.Ordinal) >= 0;
	}

	private static ReleaseAbilityArrayResult FindReleaseActionBarAbilitiesBySid(string sid)
	{
		if (!IsReleaseConfigActionBarFallbackEnabled())
			return new ReleaseAbilityArrayResult("sid-config:disabled", null);
		if (string.IsNullOrWhiteSpace(sid) || !Homm3CustomFactionRegistry.IsCustomUnitSid(sid))
			return new ReleaseAbilityArrayResult("sid-config:none", null);
		if (IsKnownNoReleaseActionBarSid(sid))
			return new ReleaseAbilityArrayResult("sid-config:no-actionbar-abilities:cached", null);
		if (PrewarmedReleaseActionBarAbilitiesBySid.TryGetValue(sid.Trim(), out var prewarmed)
		    && prewarmed != null
		    && prewarmed.Length > 0)
		{
			return new ReleaseAbilityArrayResult("sid-config:prewarmed:DefaultAttack+AlternativeAttack+Ability", prewarmed);
		}
		if (!TryResolveReleaseUnitConfigsBySid(sid, out var logicConfig, out var viewConfig))
		{
			return new ReleaseAbilityArrayResult("sid-config:missing-config", null);
		}
		var configArray = BuildReleaseActionBarAbilitiesFromConfigs(logicConfig, viewConfig, sid);
		if (configArray != null && configArray.Length > 0)
		{
			PrewarmedReleaseActionBarAbilitiesBySid[sid.Trim()] = configArray;
			NoReleaseActionBarSids.Remove(sid.Trim());
		}
		else
		{
			CacheNoReleaseActionBarSid(sid);
		}
		return configArray != null && configArray.Length > 0
			? new ReleaseAbilityArrayResult("sid-config:DefaultAttack+AlternativeAttack+Ability", configArray)
			: new ReleaseAbilityArrayResult("sid-config:no-actionbar-abilities", null);
	}

	private static Array BuildReleaseActionBarAbilitiesFromUnitConfigs(Unit unit, string sid = null)
	{
		if (unit == null)
			return null;
		var logicConfig = TryGetSelectedUnitLogicConfig(unit);
		var viewConfig = TryGetSelectedUnitViewConfig(unit);
		if (logicConfig == null || viewConfig == null)
		{
			LogReleaseConfigAbilityFallbackWarning(
				"unit config fields missing: logic=" + (logicConfig != null)
				+ " view=" + (viewConfig != null)
				+ " unitType=" + unit.GetType().FullName);
			return null;
		}

		return BuildReleaseActionBarAbilitiesFromConfigs(logicConfig, viewConfig, sid);
	}

	private static bool SelectedUnitConfigsMatchSid(Unit unit, string sid)
	{
		if (unit == null || string.IsNullOrWhiteSpace(sid))
			return false;
		var logicConfig = TryGetSelectedUnitLogicConfig(unit);
		var viewConfig = TryGetSelectedUnitViewConfig(unit);
		return ConfigMatchesSid(logicConfig, sid) || ConfigMatchesSid(viewConfig, sid);
	}

	private static bool ConfigMatchesSid(object config, string sid)
	{
		var id = TryGetConfigId(config);
		return !string.IsNullOrWhiteSpace(id)
		       && string.Equals(id.Trim(), sid.Trim(), StringComparison.OrdinalIgnoreCase);
	}

	private static UnitLogicConfig TryGetSelectedUnitLogicConfig(Unit unit)
	{
		if (unit == null)
			return null;
		var fieldValue = TryGetFirstMemberValue(unit, GameSymbols.SelectedUnitHud.UnitLogicConfigFields, typeof(UnitLogicConfig)) as UnitLogicConfig;
		return fieldValue
		       ?? TryReadNativeObjectMember<UnitLogicConfig>(unit, GameSymbols.SelectedUnitHud.UnitLogicConfigFields)
		       ?? InvokeExactSelectedUnitConfigGetter(unit, GameSymbols.SelectedUnitHud.UnitLogicConfigGetter, typeof(UnitLogicConfig)) as UnitLogicConfig;
	}

	private static UnitViewConfig TryGetSelectedUnitViewConfig(Unit unit)
	{
		if (unit == null)
			return null;
		var fieldValue = TryGetFirstMemberValue(unit, GameSymbols.SelectedUnitHud.UnitViewConfigFields, typeof(UnitViewConfig)) as UnitViewConfig;
		return fieldValue
		       ?? TryReadNativeObjectMember<UnitViewConfig>(unit, GameSymbols.SelectedUnitHud.UnitViewConfigFields)
		       ?? InvokeExactSelectedUnitConfigGetter(unit, GameSymbols.SelectedUnitHud.UnitViewConfigGetter, typeof(UnitViewConfig)) as UnitViewConfig;
	}

	private static object InvokeExactSelectedUnitConfigGetter(Unit unit, GameSymbols.MethodSymbol symbol, Type expectedReturnType)
	{
		if (unit == null || symbol.NameHints == null || expectedReturnType == null)
			return null;
		try
		{
			var method = GameMember.FindFirstMethodByNames(unit.GetType(), Array.Empty<Type>(), symbol);
			if (method == null || !GameInteropTypes.TypesMatch(method.ReturnType, expectedReturnType))
				return null;
			return method.Invoke(unit, null);
		}
		catch (Exception ex)
		{
			LogReleaseConfigAbilityFallbackWarning(symbol.Id + " invocation failed: " + ex.Message);
			return null;
		}
	}

	private static Array BuildReleaseActionBarAbilitiesFromConfigs(UnitLogicConfig logicConfig, UnitViewConfig viewConfig, string sid)
	{
		if (logicConfig == null || viewConfig == null)
			return null;
		var uiAbilities = new List<object>();
		AppendReleaseConfigActionBarAbilities(uiAbilities, logicConfig, viewConfig, EAbilityType.DefaultAttack);
		AppendReleaseConfigActionBarAbilities(uiAbilities, logicConfig, viewConfig, EAbilityType.AlternativeAttack);
		AppendReleaseConfigActionBarAbilities(uiAbilities, logicConfig, viewConfig, EAbilityType.Ability);
		if (uiAbilities.Count <= 0)
		{
			LogReleaseConfigAbilityFallbackWarning(
				"unit config buckets produced no action-bar abilities for sid='"
				+ (sid ?? "?")
				+ "'.");
		}
		return uiAbilities.Count <= 0 ? null : BuildReleaseAbilityArray(uiAbilities);
	}

	private static bool TryResolveReleaseUnitConfigsBySid(string sid, out UnitLogicConfig logic, out UnitViewConfig view)
	{
		logic = null;
		view = null;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		if (!TryGetReleaseConfigTables(out var logicTable, out var viewTable))
		{
			LogReleaseConfigAbilityFallbackWarning("config root missing for sid='" + sid + "'.");
			return false;
		}
		return TryLookupReleaseConfigBySid(logicTable, sid.Trim(), out logic)
		       && TryLookupReleaseConfigBySid(viewTable, sid.Trim(), out view)
		       && logic != null
		       && view != null;
	}

	private static bool TryGetReleaseConfigTables(out object logicTable, out object viewTable)
	{
		logicTable = _releaseUnitLogicConfigTable;
		viewTable = _releaseUnitViewConfigTable;
		if (logicTable != null && viewTable != null)
			return true;

		var rootType = _releaseConfigRootType ?? FindFirstRuntimeType(GameSymbols.UnitPreviewAbilityIcons.ConfigRootTypeNames);
		if (rootType == null)
			return false;
		_releaseConfigRootType = rootType;

		var root = _releaseConfigRoot ?? TryGetFirstStaticMemberValue(rootType, GameSymbols.UnitPreviewAbilityIcons.ConfigRootMembers);
		if (root == null)
			return false;
		_releaseConfigRoot = root;

		logicTable = _releaseUnitLogicConfigTable ?? TryGetFirstMemberValue(root, GameSymbols.UnitPreviewAbilityIcons.UnitLogicConfigTables);
		viewTable = _releaseUnitViewConfigTable ?? TryGetFirstMemberValue(root, GameSymbols.UnitPreviewAbilityIcons.UnitViewConfigTables);
		if (logicTable == null || viewTable == null)
			return false;

		_releaseUnitLogicConfigTable = logicTable;
		_releaseUnitViewConfigTable = viewTable;
		return true;
	}

	private static bool TryLookupReleaseConfigBySid<T>(object table, string sid, out T value) where T : class
	{
		value = null;
		if (table == null || string.IsNullOrWhiteSpace(sid))
			return false;
		try
		{
			var method = FindConfigTableTryGetMethod(table.GetType(), typeof(T));
			if (method == null)
				return false;
			var args = new object[] { sid, null };
			if (!(method.Invoke(table, args) is bool found) || !found)
				return false;
			value = args[1] as T;
			return value != null;
		}
		catch (Exception ex)
		{
			LogReleaseConfigAbilityFallbackWarning("config lookup failed for sid='" + sid + "': " + ex.Message);
			return false;
		}
	}

	private static MethodInfo FindConfigTableTryGetMethod(Type tableType, Type valueType)
	{
		if (tableType == null || valueType == null)
			return null;
		var cacheKey = tableType.FullName + "|" + valueType.FullName;
		if (ReleaseConfigTableTryGetMethods.TryGetValue(cacheKey, out var cached))
			return cached;
		var names = GameSymbols.UnitPreviewAbilityIcons.ConfigTableTryGet.NameHints;
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in tableType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal) || !IsConfigTableTryGetMethod(method, valueType))
					continue;
				ReleaseConfigTableTryGetMethods[cacheKey] = method;
				return method;
			}
		}
		return null;
	}

	private static bool IsConfigTableTryGetMethod(MethodInfo method, Type valueType)
	{
		if (method == null || method.ReturnType != typeof(bool) || valueType == null)
			return false;
		var ps = method.GetParameters();
		return ps.Length == 2
		       && ps[0].ParameterType == typeof(string)
		       && ps[1].IsOut
		       && ParameterTypesMatch(ps[1].ParameterType.GetElementType(), valueType);
	}

	private static void AppendReleaseConfigActionBarAbilities(List<object> target, UnitLogicConfig logicConfig, UnitViewConfig viewConfig, EAbilityType type)
	{
		if (target == null || logicConfig == null || viewConfig == null)
			return;
		var logicArray = InvokeConfigAbilityArray(logicConfig, GameSymbols.SelectedUnitHud.UnitLogicAbilityBucket, type);
		var length = logicArray != null ? logicArray.Length : 0;
		if (length <= 0)
			return;
		var viewArray = InvokeConfigAbilityArray(viewConfig, GameSymbols.SelectedUnitHud.UnitViewAbilityBucket, type);
		for (var i = 0; i < length; i++)
		{
			var logic = logicArray.GetValue(i) as AbilityLogicConfig;
			var view = InvokeConfigAbilityAt(viewConfig, type, i)
			           ?? (viewArray != null && i < viewArray.Length ? viewArray.GetValue(i) as AbilityViewConfig : null);
			var ability = CreateReleaseAbilityWrapper(logic, view, type, i);
			if (ability != null && CanShowOnActionBar(ability) && !ContainsReleaseAbility(target, ability))
				target.Add(ability);
		}
	}

	private static bool HasReleaseConfigAbilitySurface()
	{
		return HasReleaseUnitConfigMemberSurface()
		       && FindConfigAbilityArrayMethod(typeof(UnitLogicConfig), GameSymbols.SelectedUnitHud.UnitLogicAbilityBucket, typeof(AbilityLogicConfig)) != null
		       && FindConfigAbilityArrayMethod(typeof(UnitViewConfig), GameSymbols.SelectedUnitHud.UnitViewAbilityBucket, typeof(AbilityViewConfig)) != null
		       && FindConfigAbilityAtMethod(typeof(UnitViewConfig)) != null
		       && FindReleaseAbilityWrapperInitMethod(GameInteropTypes.ReleaseAbilityWrapperType) != null;
	}

	private static bool HasReleaseUnitConfigMemberSurface()
	{
		return HasNamedOrTypedMember(typeof(Unit), GameSymbols.SelectedUnitHud.UnitLogicConfigFields, typeof(UnitLogicConfig))
		       && HasNamedOrTypedMember(typeof(Unit), GameSymbols.SelectedUnitHud.UnitViewConfigFields, typeof(UnitViewConfig));
	}

	private static bool HasNamedOrTypedMember(Type ownerType, string[] names, Type expectedType)
	{
		if (ownerType == null || expectedType == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		if (names != null)
		{
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				for (var current = ownerType; current != null; current = current.BaseType)
				{
					var field = current.GetField(name, flags);
					if (field != null && ParameterTypesMatch(field.FieldType, expectedType))
						return true;
				}
			}
		}
		FieldInfo unique = null;
		for (var current = ownerType; current != null; current = current.BaseType)
		{
			foreach (var field in current.GetFields(flags))
			{
				if (!ParameterTypesMatch(field.FieldType, expectedType))
					continue;
				if (unique != null)
					return false;
				unique = field;
			}
		}
		return unique != null;
	}

	private static Array InvokeConfigAbilityArray(object config, GameSymbols.MethodSymbol symbol, EAbilityType type)
	{
		if (config == null)
			return null;
		var elementType = config is UnitLogicConfig ? typeof(AbilityLogicConfig) : typeof(AbilityViewConfig);
		var method = FindConfigAbilityArrayMethod(config.GetType(), symbol, elementType);
		if (method == null)
			return null;
		try { return CoerceConfigArray(method.Invoke(config, new object[] { type }), elementType); }
		catch (Exception ex)
		{
			LogReleaseConfigAbilityFallbackWarning("ability array invoke failed on " + config.GetType().Name + "." + method.Name + ": " + ex.Message);
			return null;
		}
	}

	private static AbilityViewConfig InvokeConfigAbilityAt(UnitViewConfig config, EAbilityType type, int index)
	{
		if (config == null)
			return null;
		var method = FindConfigAbilityAtMethod(config.GetType());
		if (method == null)
			return null;
		try { return method.Invoke(config, new object[] { type, index }) as AbilityViewConfig; }
		catch (Exception ex)
		{
			LogReleaseConfigAbilityFallbackWarning("ability view lookup failed on " + method.Name + ": " + ex.Message);
			return null;
		}
	}

	private static MethodInfo FindConfigAbilityArrayMethod(Type type, GameSymbols.MethodSymbol symbol, Type elementType)
	{
		if (type == null || elementType == null)
			return null;
		var method = GameMember.FindFirstMethodByNames(type, new[] { typeof(EAbilityType) }, symbol);
		if (method != null && IsConfigAbilityArrayMethod(method, elementType))
			return method;
		foreach (var candidate in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (IsConfigAbilityArrayMethod(candidate, elementType))
				return candidate;
		}
		return null;
	}

	private static bool IsConfigAbilityArrayMethod(MethodInfo method, Type elementType)
	{
		if (method == null || elementType == null)
			return false;
		var ps = method.GetParameters();
		return ps.Length == 1
		       && ParameterTypesMatch(ps[0].ParameterType, typeof(EAbilityType))
		       && IsArrayLikeReturnType(method.ReturnType, elementType);
	}

	private static MethodInfo FindConfigAbilityAtMethod(Type type)
	{
		if (type == null)
			return null;
		var method = GameMember.FindFirstMethodByNames(type, new[] { typeof(EAbilityType), typeof(int) }, GameSymbols.SelectedUnitHud.UnitViewAbilityAt);
		if (method != null && IsConfigAbilityAtMethod(method))
			return method;
		foreach (var candidate in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (IsConfigAbilityAtMethod(candidate))
				return candidate;
		}
		return null;
	}

	private static bool IsConfigAbilityAtMethod(MethodInfo method)
	{
		if (method == null || !ParameterTypesMatch(method.ReturnType, typeof(AbilityViewConfig)))
			return false;
		var ps = method.GetParameters();
		return ps.Length == 2
		       && ParameterTypesMatch(ps[0].ParameterType, typeof(EAbilityType))
		       && ParameterTypesMatch(ps[1].ParameterType, typeof(int));
	}

	private static Array CoerceConfigArray(object value, Type elementType)
	{
		if (value == null || elementType == null)
			return null;
		if (value is Array array)
			return array;
		try
		{
			var lengthProp = value.GetType().GetProperty("Length", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			var getItem = value.GetType().GetMethod("get_Item", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance, null, new[] { typeof(int) }, null);
			if (lengthProp?.GetValue(value) is not int length || length <= 0 || getItem == null)
				return null;
			var result = Array.CreateInstance(elementType, length);
			for (var i = 0; i < length; i++)
				result.SetValue(getItem.Invoke(value, new object[] { i }), i);
			return result;
		}
		catch (Exception ex)
		{
			LogReleaseConfigAbilityFallbackWarning("ability array coercion failed: " + ex.Message);
			return null;
		}
	}

	private static bool IsArrayLikeReturnType(Type returnType, Type elementType)
	{
		if (returnType == null || elementType == null)
			return false;
		if (returnType.IsArray)
			return ParameterTypesMatch(returnType.GetElementType(), elementType);
		if (!returnType.IsGenericType || !returnType.Name.StartsWith("Il2CppReferenceArray", StringComparison.Ordinal))
			return false;
		var args = returnType.GetGenericArguments();
		return args.Length == 1 && ParameterTypesMatch(args[0], elementType);
	}

	private static object CreateReleaseAbilityWrapper(AbilityLogicConfig logic, AbilityViewConfig view, EAbilityType type, int index)
	{
		var wrapperType = GameInteropTypes.ReleaseAbilityWrapperType;
		if (logic == null || view == null || wrapperType == null)
			return null;
		var methods = FindReleaseAbilityWrapperInitMethods(wrapperType);
		if (methods.Count == 0)
			return null;
		Exception lastFailure = null;
		for (var i = 0; i < methods.Count; i++)
		{
			var init = methods[i];
			if (FailedReleaseAbilityWrapperInitMethods.Contains(init))
				continue;
			try
			{
				var ability = Activator.CreateInstance(wrapperType);
				if (ability == null)
					continue;
				init.Invoke(ability, new object[] { logic, view, new AbilityID(type, index) });
				return ability;
			}
			catch (Exception ex)
			{
				lastFailure = ex is TargetInvocationException && ex.InnerException != null ? ex.InnerException : ex;
				FailedReleaseAbilityWrapperInitMethods.Add(init);
				LogReleaseConfigAbilityFallbackWarning("ability wrapper construction failed via " + init.Name + ": " + lastFailure.GetType().Name + ": " + lastFailure.Message);
			}
		}
		if (lastFailure == null)
			LogReleaseConfigAbilityFallbackWarning("ability wrapper construction failed: no wrapper instance could be created");
		return null;
	}

	private static MethodInfo FindReleaseAbilityWrapperInitMethod(Type wrapperType)
	{
		var methods = FindReleaseAbilityWrapperInitMethods(wrapperType);
		return methods.Count == 1 ? methods[0] : null;
	}

	private static List<MethodInfo> FindReleaseAbilityWrapperInitMethods(Type wrapperType)
	{
		if (wrapperType == null)
			return new List<MethodInfo>();
		var methods = wrapperType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
		var matches = new List<MethodInfo>();
		var seen = new HashSet<MethodInfo>();
		var hints = GameSymbols.SelectedUnitHud.AbilityWrapperInit.NameHints ?? Array.Empty<string>();
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			for (var j = 0; j < methods.Length; j++)
			{
				var candidate = methods[j];
				if (!string.Equals(candidate.Name, hint, StringComparison.Ordinal)
				    || !IsReleaseAbilityWrapperInitMethod(candidate)
				    || !seen.Add(candidate))
					continue;
				matches.Add(candidate);
			}
		}
		foreach (var candidate in methods)
		{
			if (string.Equals(candidate.Name, "Init", StringComparison.Ordinal)
			    && IsReleaseAbilityWrapperInitMethod(candidate)
			    && seen.Add(candidate))
				matches.Add(candidate);
		}
		return matches;
	}

	private static bool IsReleaseAbilityWrapperInitMethod(MethodInfo method)
	{
		if (method == null || method.ReturnType != typeof(void))
			return false;
		var ps = method.GetParameters();
		return ps.Length == 3
		       && ParameterTypesMatch(ps[0].ParameterType, typeof(AbilityLogicConfig))
		       && ParameterTypesMatch(ps[1].ParameterType, typeof(AbilityViewConfig))
		       && ParameterTypesMatch(ps[2].ParameterType, typeof(AbilityID));
	}

	private static void LogReleaseConfigAbilityFallbackWarning(string message)
	{
		if (!IsDiagnosticEnabled())
			return;
		if (_loggedReleaseConfigAbilityFallback >= 8)
			return;
		_loggedReleaseConfigAbilityFallback++;
		Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD unit-config ability fallback: " + message);
	}

	private static void NormalizeReleaseManagerBuckets(object manager, string source)
	{
		if (manager == null)
			return;
		NormalizeReleaseAbilityArray(TryGetReleaseAbilityArray(manager, EAbilityType.DefaultAttack), source + ":DefaultAttack");
		NormalizeReleaseAbilityArray(TryGetReleaseAbilityArray(manager, EAbilityType.AlternativeAttack), source + ":AlternativeAttack");
		NormalizeReleaseAbilityArray(TryGetReleaseAbilityArray(manager, EAbilityType.Ability), source + ":Ability");
	}

	private static void NormalizeReleaseAbilityArray(Array abilities, string source)
	{
		if (abilities == null || abilities.Length <= 0)
			return;
		for (var i = 0; i < abilities.Length; i++)
			NormalizeReleaseAbility(abilities.GetValue(i), source);
	}

	private static void NormalizeReleaseAbility(object ability, string source)
	{
		if (ability == null)
			return;
		try
		{
			var logic = GetReleaseAbilityLogic(ability);
			var view = GetReleaseAbilityView(ability);
			if (!ShouldNormalizeReleaseNoEnergyAbility(logic, view))
				return;

			logic.energyLevel = 0;
			logic.dontUseEnergy = true;
			if (IsDiagnosticEnabled() && _loggedDirectControlsBind < 12)
			{
				_loggedDirectControlsBind++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import selected-unit HUD release ability normalized: source='"
					+ source
					+ "' "
					+ SummarizeReleaseAbility(ability)
					+ ".");
			}
		}
		catch (Exception ex)
		{
			if (IsDiagnosticEnabled() && _loggedDirectControlsBind < 8)
			{
				_loggedDirectControlsBind++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD release ability normalize failed: " + ex.Message);
			}
		}
	}

	private static bool ShouldNormalizeReleaseNoEnergyAbility(AbilityLogicConfig logic, AbilityViewConfig view)
	{
		if (logic == null || view == null)
			return false;
		if (!logic.dontUseEnergy)
			return false;

		var name = view.name ?? string.Empty;
		if (name.StartsWith("h3_", StringComparison.OrdinalIgnoreCase))
			return true;
		return string.Equals(name, "common_attack_1_name", StringComparison.OrdinalIgnoreCase)
		       && string.Equals(view.abilityType, "Ability_type_attack_alt", StringComparison.OrdinalIgnoreCase);
	}

	private static Array MergeReleaseActionBarAbilityBuckets(object manager)
	{
		var uiAbilities = new List<object>();
		AppendReleaseActionBarAbilities(uiAbilities, TryGetReleaseAbilityArray(manager, EAbilityType.DefaultAttack));
		AppendReleaseActionBarAbilities(uiAbilities, TryGetReleaseAbilityArray(manager, EAbilityType.AlternativeAttack));
		AppendReleaseActionBarAbilities(uiAbilities, TryGetReleaseAbilityArray(manager, EAbilityType.Ability));
		return uiAbilities.Count <= 0 ? null : BuildReleaseAbilityArray(uiAbilities);
	}

	private static void AppendReleaseActionBarAbilities(List<object> target, Array source)
	{
		if (target == null || source == null || source.Length <= 0)
			return;

		for (var i = 0; i < source.Length; i++)
		{
			var ability = source.GetValue(i);
			if (!CanShowOnActionBar(ability) || ContainsReleaseAbility(target, ability))
				continue;
			target.Add(ability);
		}
	}

	private static void AppendReleaseActionBarAbilities(List<object> target, IEnumerable<object> source)
	{
		if (target == null || source == null)
			return;
		foreach (var ability in source)
		{
			if (!CanShowOnActionBar(ability) || ContainsReleaseAbility(target, ability))
				continue;
			target.Add(ability);
		}
	}

	private static bool ContainsReleaseAbility(List<object> abilities, object ability)
	{
		if (abilities == null || ability == null)
			return false;
		for (var i = 0; i < abilities.Count; i++)
		{
			if (SameReleaseAbility(abilities[i], ability))
				return true;
		}
		return false;
	}

	private static bool CanShowOnActionBar(object ability)
	{
		try
		{
			if (ability == null)
				return false;
			var view = GetReleaseAbilityView(ability);
			if (view == null)
				return false;

			if (view.canShowOnUI)
				return true;

			if (IsMeleeAttackActionBarRecoveryAbility(ability, view))
				return true;

			return IsExplicitActionBarAbility(view);
		}
		catch
		{
			return false;
		}
	}

	private static bool IsMeleeAttackActionBarRecoveryAbility(object ability, AbilityViewConfig view)
	{
		if (ability == null || view == null)
			return false;
		var logic = GetReleaseAbilityLogic(ability);
		if (logic == null || !IsMeleeAttackLogic(logic))
			return false;
		var name = SafeString(view.name);
		var abilityType = SafeString(view.abilityType);
		return string.Equals(name, "common_attack_1_name", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(abilityType, "Ability_type_attack", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(abilityType, "Ability_type_attack_alt", StringComparison.OrdinalIgnoreCase);
	}

	private static bool IsMeleeAttackLogic(AbilityLogicConfig logic)
	{
		if (logic == null)
			return false;
		return string.Equals(SafeString(logic.attackType_), "melee", StringComparison.OrdinalIgnoreCase);
	}

	private static Array TryGetReleaseAbilityArray(object manager, EAbilityType type)
	{
		try
		{
			return InvokeReleaseAbilityBucket(manager, type);
		}
		catch
		{
			return null;
		}
	}

	private static object GetReleaseAbility(BhUnitAbilityView view)
	{
		if (view == null)
			return null;
		try
		{
			if (ReleaseAbilityByView.TryGetValue(Homm3DirectStateIdentity.ResolveKeyOrZero(view), out var cached)
			    && IsReleaseAbilityWrapper(cached))
				return cached;
			var nativeAbility = TryReadReleaseAbilityViewAbility(view);
			if (IsReleaseAbilityWrapper(nativeAbility))
			{
				RememberReleaseAbilityViewAbility(view, nativeAbility);
				return nativeAbility;
			}
			var ability = TryGetFirstMemberValue(view, GameSymbols.SelectedUnitHud.AbilityViewAbilityFields);
			if (IsReleaseAbilityWrapper(ability))
			{
				RememberReleaseAbilityViewAbility(view, ability);
				return ability;
			}
			var wrapperAbility = TryGetReleaseAbilityFromViewWrapper(view);
			if (IsReleaseAbilityWrapper(wrapperAbility))
			{
				RememberReleaseAbilityViewAbility(view, wrapperAbility);
				return wrapperAbility;
			}
		}
		catch { }
		return null;
	}

	private static object TryGetReleaseAbilityFromViewWrapper(BhUnitAbilityView view)
	{
		if (view == null)
			return null;
		var wrapper = GetReleaseAbilityWrapper(view);
		if (wrapper == null)
			return null;
		var names = GameSymbols.SelectedUnitHud.AbilityWrapperTryGetAbility.NameHints;
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var ability = TryInvokeReleaseAbilityOut(wrapper, names[i]);
			if (IsReleaseAbilityWrapper(ability))
				return ability;
		}
		return null;
	}

	private static object TryInvokeReleaseAbilityOut(object wrapper, string methodName)
	{
		if (wrapper == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		try
		{
			var method = FindMethodByNameAndArity(wrapper.GetType(), methodName, 1);
			if (method == null || method.ReturnType != typeof(bool))
				return null;
			var ps = method.GetParameters();
			if (ps.Length != 1 || !ps[0].IsOut)
				return null;
			var args = new object[] { null };
			if (!(method.Invoke(wrapper, args) is bool ok) || !ok)
				return null;
			return IsReleaseAbilityWrapper(args[0]) ? args[0] : null;
		}
		catch
		{
			return null;
		}
	}

	private static object TryReadReleaseAbilityViewAbility(BhUnitAbilityView view)
	{
		if (view == null)
			return null;
		var names = GameSymbols.SelectedUnitHud.AbilityViewAbilityFields;
		var wrapperType = GameInteropTypes.ReleaseAbilityWrapperType;
		if (names == null || wrapperType == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var ability = TryReadNativeObjectMember(view, names[i], wrapperType);
			if (IsReleaseAbilityWrapper(ability))
				return ability;
		}
		return null;
	}

	private static object GetReleaseAbilityWrapper(BhUnitAbilityView view)
	{
		if (view == null)
			return null;
		return TryGetFirstMemberValue(view, GameSymbols.SelectedUnitHud.AbilityViewWrapperFields);
	}

	private static BhUnitAbilityView GetReleaseSelectedAbilityView(BhUnitControlsView controlsView)
	{
		if (controlsView == null)
			return null;
		return TryReadNativeObjectMember<BhUnitAbilityView>(controlsView, GameSymbols.SelectedUnitHud.ControlsSelectedViewFields)
		       ?? TryGetFirstMemberValue(controlsView, GameSymbols.SelectedUnitHud.ControlsSelectedViewFields) as BhUnitAbilityView;
	}

	private static void TryClearReleaseControlsSelectedViewField(BhUnitControlsView controlsView, string sid, string reason)
	{
		if (controlsView == null)
			return;
		if (!TrySetFirstMemberValue(controlsView, GameSymbols.SelectedUnitHud.ControlsSelectedViewFields, typeof(BhUnitAbilityView), null))
			return;
		LogDirectReleaseControlsBind("cleared selected action field: " + reason, sid, null, null);
	}

	private static Array GetReleaseCurrentAbilityArray(BhUnitControlsView controlsView)
	{
		if (controlsView == null)
			return null;
		return CoerceReleaseAbilityArray(TryGetFirstMemberValue(controlsView, GameSymbols.SelectedUnitHud.ControlsCurrentAbilityArrayFields));
	}

	private static void CacheBoundReleaseControls(string sid, Array abilities, long unitKey = 0)
	{
		if (!IsCachedControlsSid(sid) || abilities == null || abilities.Length <= 0)
			return;
		_lastBoundReleaseControlsSid = sid;
		_lastBoundReleaseControlsAbilities = abilities;
		if (unitKey != 0)
			_lastBoundReleaseControlsUnitKey = unitKey;
	}

	private static long GetSidConfigCacheKey(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return 0;
		unchecked
		{
			long hash = 1469598103934665603L;
			for (var i = 0; i < sid.Length; i++)
			{
				hash ^= char.ToUpperInvariant(sid[i]);
				hash *= 1099511628211L;
			}
			return hash == 0 ? 1 : hash;
		}
	}

	private static long GetIl2CppObjectKey(object value)
	{
		try
		{
			return value is Il2CppObjectBase obj && obj.Pointer != IntPtr.Zero
				? obj.Pointer.ToInt64()
				: 0;
		}
		catch
		{
			return 0;
		}
	}

	private static bool SameIl2CppObject(object left, object right)
	{
		if (left == null || right == null)
			return false;
		if (ReferenceEquals(left, right))
			return true;
		var leftKey = GetIl2CppObjectKey(left);
		var rightKey = GetIl2CppObjectKey(right);
		return leftKey != 0 && rightKey != 0 && leftKey == rightKey;
	}

	private static bool IsSameCachedReleaseControlsSid(string sid)
	{
		return IsCachedControlsSid(sid)
		       && string.Equals(sid, _lastBoundReleaseControlsSid, StringComparison.OrdinalIgnoreCase);
	}

	private static void LogDirectReleaseControlsBind(string action, string sid, string source, Array abilities)
	{
		if (!IsDiagnosticEnabled())
			return;
		if (_loggedDirectControlsBindInfo >= 30)
			return;
		_loggedDirectControlsBindInfo++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import selected-unit HUD release controls direct bind: " + action
			+ " sid='" + sid + "' source='" + (source ?? "?")
			+ "' count=" + (abilities != null ? abilities.Length : -1)
			+ " first=" + SummarizeReleaseAbility(abilities != null && abilities.Length > 0 ? abilities.GetValue(0) : null) + ".");
	}

	private static void LogReleaseActionBarLookup(Unit unit, string sid, object manager, ReleaseAbilityArrayResult result)
	{
		if (!IsDiagnosticEnabled())
			return;
		if (_loggedReleaseActionBarLookup >= 40)
			return;
		_loggedReleaseActionBarLookup++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import selected-unit HUD release action-bar lookup:"
			+ " sid='" + (sid ?? "?") + "'"
			+ " unitType='" + (unit != null ? unit.GetType().FullName : "(null)") + "'"
			+ " manager=" + (manager != null ? manager.GetType().FullName : "(null)")
			+ " logicField='" + FindFirstMatchingFieldName(unit, GameSymbols.SelectedUnitHud.UnitLogicConfigFields, typeof(UnitLogicConfig)) + "'"
			+ " viewField='" + FindFirstMatchingFieldName(unit, GameSymbols.SelectedUnitHud.UnitViewConfigFields, typeof(UnitViewConfig)) + "'"
			+ " source='" + (result.Source ?? "?") + "'"
			+ " count=" + (result.Abilities != null ? result.Abilities.Length : -1)
			+ " first=" + SummarizeReleaseAbility(result.Abilities != null && result.Abilities.Length > 0 ? result.Abilities.GetValue(0) : null) + ".");
	}

	private static string FindFirstMatchingFieldName(object owner, string[] names, Type expectedType)
	{
		if (owner == null || names == null || expectedType == null)
			return "";
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var current = owner.GetType(); current != null; current = current.BaseType)
			{
				var field = current.GetField(name, flags);
				if (field != null && ParameterTypesMatch(field.FieldType, expectedType))
					return field.Name;
			}
		}
		return "";
	}

	private static bool IsDiagnosticEnabled()
	{
		return Homm3DiagnosticFlags.IsEnabled("homm3_selected_hud_diag.flag");
	}

	private static void LogDiagnostic(string message)
	{
		if (IsDiagnosticEnabled())
			Plugin.LogSource?.LogInfo(message);
	}

	private readonly struct ReleaseAbilityArrayResult
	{
		public ReleaseAbilityArrayResult(string source, Array abilities)
		{
			Source = source;
			Abilities = abilities;
		}

		public string Source { get; }
		public Array Abilities { get; }
	}

	internal readonly struct ReleaseActionBarPrewarmResult
	{
		public ReleaseActionBarPrewarmResult(int actionBars, int icons, int iconMisses)
		{
			ActionBars = actionBars;
			Icons = icons;
			IconMisses = iconMisses;
		}

		public int ActionBars { get; }
		public int Icons { get; }
		public int IconMisses { get; }
	}

	private static string SummarizeReleaseAbility(object ability)
	{
		if (ability == null)
			return "null";
		try
		{
			var logic = GetReleaseAbilityLogic(ability);
			var view = GetReleaseAbilityView(ability);
			return "type=" + SafeString(logic?.attackType_)
			       + ",energy=" + (logic != null ? logic.energyLevel : -1)
			       + ",actionCost=" + (logic != null ? logic.actionCost : -1)
			       + ",noEnergy=" + (logic != null && logic.dontUseEnergy)
			       + ",viewName=" + SafeString(view?.name)
			       + ",viewType=" + SafeString(view?.abilityType)
			       + ",canUI=" + (view != null && view.canShowOnUI);
		}
		catch (Exception ex)
		{
			return "err:" + ex.Message;
		}
	}

	private static string SafeString(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return "?";
		return value.Length <= 48 ? value : value.Substring(0, 48) + "...";
	}

	private static void ApplySelectedUnitPortrait(BhSelectedUnitHud hud, Unit unit, string source)
	{
		try
		{
			if (hud == null || unit == null)
				return;
			var sid = ExtractSid(unit);
			ApplySelectedUnitPortrait(hud, sid, source);
		}
		catch (Exception ex)
		{
			if (_loggedPortraitReplace < 5)
			{
				_loggedPortraitReplace++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD portrait failed: " + ex.Message);
			}
		}
	}

	private static void ApplySelectedUnitPortrait(BhSelectedUnitHud hud, string sid, string source)
	{
		try
		{
			if (hud == null || string.IsNullOrWhiteSpace(sid))
				return;
			if (!Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(sid, out var sprite) || sprite == null)
			{
				ClearSelectedUnitPortraitOverride(hud, sid, source + "-missing-homm3-sprite");
				return;
			}

			var replaced = ReplacePortraitFields(hud, sprite);
			if (replaced == 0)
				replaced = ReplacePortraitChildren(hud, sprite);
			if (replaced == 0)
				replaced = ReplaceLikelyUnitImages(hud, sprite);
			if (replaced == 0)
				replaced = ReplaceSceneDonorPortraitImages(sid, sprite);
			if (replaced == 0)
				LogHudSurfaceDiag(hud, sid, "portrait-miss");
			if (replaced <= 0 || !IsDiagnosticEnabled() || _loggedPortraitReplace >= 30)
				return;
			_loggedPortraitReplace++;
			Plugin.LogSource?.LogInfo(
				"Homm3Import selected-unit HUD portrait: replaced " + replaced
				+ " image(s) for sid='" + sid + "' via " + source + ".");
		}
		catch (Exception ex)
		{
			if (_loggedPortraitReplace < 5)
			{
				_loggedPortraitReplace++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD portrait failed: " + ex.Message);
			}
		}
	}

	private static int ReplacePortraitFields(BhSelectedUnitHud hud, Sprite sprite)
	{
		var replaced = 0;
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = hud.GetType(); type != null; type = type.BaseType)
		{
			foreach (var field in type.GetFields(flags))
			{
				if (!typeof(Image).IsAssignableFrom(field.FieldType))
					continue;
				if (!IsPortraitName(field.Name))
					continue;
				Image image = null;
				try { image = field.GetValue(hud) as Image; } catch { }
				if (ApplySprite(image, sprite))
					replaced++;
			}
		}
		return replaced;
	}

	private static int ReplacePortraitChildren(BhSelectedUnitHud hud, Sprite sprite)
	{
		var mn = hud as MonoBehaviour;
		if (mn == null)
			return 0;
		var root = mn.transform;
		if (root == null)
			return 0;
		var replaced = 0;
		var images = root.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (image == null)
				continue;
			var name = image.name ?? string.Empty;
			var parentName = image.transform?.parent != null ? image.transform.parent.name : string.Empty;
			if (!IsPortraitName(name) && !IsPortraitName(parentName))
				continue;
			if (ApplySprite(image, sprite))
				replaced++;
		}
		return replaced;
	}

	private static int ReplaceLikelyUnitImages(BhSelectedUnitHud hud, Sprite sprite)
	{
		var mn = hud as MonoBehaviour;
		if (mn == null || mn.transform == null)
			return 0;
		var replaced = 0;
		var images = mn.transform.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (image == null)
				continue;
			if (!LooksLikeUnitPortraitImage(image))
				continue;
			if (ApplySprite(image, sprite))
				replaced++;
		}
		return replaced;
	}

	private static int ReplaceSceneDonorPortraitImages(string sid, Sprite sprite)
	{
		var replaced = 0;
		try
		{
			replaced = ReplaceCachedScenePortraitTargets(sid, sprite);
			if (replaced > 0)
				return replaced;
			if (_scenePortraitTargetsResolved || _scenePortraitScanAttempts >= MaxScenePortraitScanAttempts)
				return 0;
			_scenePortraitScanAttempts++;

			var images = Resources.FindObjectsOfTypeAll<Image>();
			for (var i = 0; i < images.Length; i++)
			{
				var image = images[i];
				if (image == null || image.gameObject == null || !image.gameObject.activeInHierarchy)
					continue;
				if (!IsUnderCanvas(image.transform))
					continue;
				if (!LooksLikeSelectedBattleHudImage(image))
					continue;

				if (!ScenePortraitTargets.Contains(image))
					ScenePortraitTargets.Add(image);
				var oldSprite = image.sprite != null ? image.sprite.name : "?";
				if (!ApplySprite(image, sprite))
					continue;
				replaced++;
				if (IsDiagnosticEnabled() && _loggedScenePortraitReplace < 20)
				{
					_loggedScenePortraitReplace++;
					Plugin.LogSource?.LogInfo(
						"Homm3Import selected-unit HUD scene portrait: replaced image path='"
						+ GetPath(image.transform) + "' oldSprite='" + oldSprite
						+ "' sid='" + sid + "' sprite='" + sprite.name + "'.");
				}
			}
			if (replaced > 0)
				_scenePortraitTargetsResolved = true;
		}
		catch (Exception ex)
		{
			if (_loggedScenePortraitReplace < 5)
			{
				_loggedScenePortraitReplace++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD scene portrait scan failed: " + ex.Message);
			}
		}
		return replaced;
	}

	private static int ReplaceCachedScenePortraitTargets(string sid, Sprite sprite)
	{
		var replaced = 0;
		for (var i = ScenePortraitTargets.Count - 1; i >= 0; i--)
		{
			var image = ScenePortraitTargets[i];
			if (image == null || image.gameObject == null)
			{
				ScenePortraitTargets.RemoveAt(i);
				continue;
			}
			if (!image.gameObject.activeInHierarchy)
				continue;
			if (!LooksLikeCachedSelectedBattleHudImage(image))
			{
				ScenePortraitTargets.RemoveAt(i);
				continue;
			}
			var oldSprite = image.sprite != null ? image.sprite.name : "?";
			if (!ApplySprite(image, sprite))
				continue;
			replaced++;
			if (IsDiagnosticEnabled() && _loggedScenePortraitReplace < 20)
			{
				_loggedScenePortraitReplace++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import selected-unit HUD scene portrait: updated cached image path='"
					+ GetPath(image.transform) + "' oldSprite='" + oldSprite
					+ "' sid='" + sid + "' sprite='" + sprite.name + "'.");
			}
		}
		if (ScenePortraitTargets.Count == 0)
			_scenePortraitTargetsResolved = false;
		return replaced;
	}

	private static bool ApplySprite(Image image, Sprite sprite)
	{
		if (image == null || sprite == null)
			return false;
		if (image.sprite == sprite && image.overrideSprite == sprite && image.enabled && image.preserveAspect)
			return true;
		image.sprite = sprite;
		image.overrideSprite = sprite;
		image.preserveAspect = true;
		if (!image.enabled)
			image.enabled = true;
		return true;
	}

	private static void ClearSelectedUnitPortraitOverride(BhSelectedUnitHud hud, string sid, string source)
	{
		try
		{
			if (hud == null)
				return;
			var cleared = 0;
			cleared += ClearPortraitFields(hud);
			cleared += ClearPortraitChildren(hud);
			cleared += ClearLikelyUnitImages(hud);
			cleared += ClearCachedScenePortraitTargets();
			if (cleared <= 0 || !IsDiagnosticEnabled() || _loggedPortraitReplace >= 30)
				return;
			_loggedPortraitReplace++;
			Plugin.LogSource?.LogInfo(
				"Homm3Import selected-unit HUD portrait: cleared " + cleared
				+ " stale HoMM3 image(s) for sid='" + (sid ?? "?") + "' via " + (source ?? "?") + ".");
		}
		catch (Exception ex)
		{
			if (_loggedPortraitReplace < 5)
			{
				_loggedPortraitReplace++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD portrait cleanup failed: " + ex.Message);
			}
		}
	}

	private static int ClearPortraitFields(BhSelectedUnitHud hud)
	{
		var cleared = 0;
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = hud.GetType(); type != null; type = type.BaseType)
		{
			foreach (var field in type.GetFields(flags))
			{
				if (!typeof(Image).IsAssignableFrom(field.FieldType))
					continue;
				if (!IsPortraitName(field.Name))
					continue;
				Image image = null;
				try { image = field.GetValue(hud) as Image; } catch { }
				if (ClearHomm3PortraitOverride(image))
					cleared++;
			}
		}
		return cleared;
	}

	private static int ClearPortraitChildren(BhSelectedUnitHud hud)
	{
		var mn = hud as MonoBehaviour;
		if (mn == null || mn.transform == null)
			return 0;
		var cleared = 0;
		var images = mn.transform.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (image == null)
				continue;
			var name = image.name ?? string.Empty;
			var parentName = image.transform?.parent != null ? image.transform.parent.name : string.Empty;
			if (!IsPortraitName(name) && !IsPortraitName(parentName))
				continue;
			if (ClearHomm3PortraitOverride(image))
				cleared++;
		}
		return cleared;
	}

	private static int ClearLikelyUnitImages(BhSelectedUnitHud hud)
	{
		var mn = hud as MonoBehaviour;
		if (mn == null || mn.transform == null)
			return 0;
		var cleared = 0;
		var images = mn.transform.GetComponentsInChildren<Image>(true);
		for (var i = 0; i < images.Length; i++)
		{
			var image = images[i];
			if (image == null || !LooksLikeUnitPortraitImage(image))
				continue;
			if (ClearHomm3PortraitOverride(image))
				cleared++;
		}
		return cleared;
	}

	private static int ClearCachedScenePortraitTargets()
	{
		var cleared = 0;
		for (var i = ScenePortraitTargets.Count - 1; i >= 0; i--)
		{
			var image = ScenePortraitTargets[i];
			if (image == null || image.gameObject == null)
			{
				ScenePortraitTargets.RemoveAt(i);
				continue;
			}
			if (!image.gameObject.activeInHierarchy)
				continue;
			if (!LooksLikeCachedSelectedBattleHudImage(image))
			{
				ScenePortraitTargets.RemoveAt(i);
				continue;
			}
			if (ClearHomm3PortraitOverride(image))
				cleared++;
		}
		if (ScenePortraitTargets.Count == 0)
			_scenePortraitTargetsResolved = false;
		return cleared;
	}

	private static bool ClearHomm3PortraitOverride(Image image)
	{
		if (image == null)
			return false;
		var changed = false;
		if (Homm3ImportPortraitSpriteCache.IsHomm3PortraitSprite(image.overrideSprite))
		{
			image.overrideSprite = null;
			changed = true;
		}
		if (Homm3ImportPortraitSpriteCache.IsHomm3PortraitSprite(image.sprite))
		{
			image.sprite = null;
			changed = true;
		}
		return changed;
	}

	private static bool IsPortraitName(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return false;
		var n = name.ToLowerInvariant();
		return n.Contains("portrait") || n.Contains("unitpic") || n.Contains("pic") || n.Contains("face");
	}

	private static bool LooksLikeUnitPortraitImage(Image image)
	{
		if (image == null)
			return false;
		var name = image.name ?? string.Empty;
		var parent = image.transform?.parent != null ? image.transform.parent.name : string.Empty;
		var spriteName = image.sprite != null ? image.sprite.name ?? string.Empty : string.Empty;
		if (IsPortraitName(name) || IsPortraitName(parent))
			return true;
		var n = (name + " " + parent + " " + spriteName).ToLowerInvariant();
		if (n.Contains("hydra") || n.Contains("trogl") || n.Contains("assassin") || n.Contains("blade_dancer") || n.Contains("minos") || n.Contains("medusa") || n.Contains("black_dragon"))
			return true;
		if (n.Contains("unit") && (n.Contains("icon") || n.Contains("image")))
			return true;
		return false;
	}

	private static bool LooksLikeSelectedBattleHudImage(Image image)
	{
		if (image == null)
			return false;
		var path = GetPath(image.transform);
		var spriteName = image.sprite != null ? image.sprite.name ?? string.Empty : string.Empty;
		var n = (path + " " + image.name + " " + spriteName).ToLowerInvariant();
		if (IsTurnOrderPath(n))
			return false;
		if (n.Contains("ability") || n.Contains("skill") || n.Contains("cooldown") || n.Contains("spell") || n.Contains("buff") || n.Contains("law") || n.Contains("hero"))
			return false;
		if (!n.Contains("unit") && !n.Contains("selection") && !n.Contains("selected") && !n.Contains("hud"))
			return false;
		return IsDonorUnitArtName(spriteName);
	}

	private static bool LooksLikeCachedSelectedBattleHudImage(Image image)
	{
		if (image == null || image.gameObject == null || !image.gameObject.activeInHierarchy)
			return false;
		var path = GetPath(image.transform);
		var n = path.ToLowerInvariant();
		if (IsTurnOrderPath(n))
			return false;
		if (n.Contains("ability") || n.Contains("skill") || n.Contains("cooldown") || n.Contains("spell") || n.Contains("buff") || n.Contains("law") || n.Contains("hero"))
			return false;
		return n.Contains("battlebottomhudcanvas")
			&& n.Contains("unitpart")
			&& n.Contains("unit pic")
			&& n.Contains("back portrait");
	}

	private static bool IsDonorUnitArtName(string text)
	{
		if (string.IsNullOrWhiteSpace(text))
			return false;
		var n = text.ToLowerInvariant();
		return n.Contains("hydra")
			|| n.Contains("trogl")
			|| n.Contains("assassin")
			|| n.Contains("blade_dancer")
			|| n.Contains("minos")
			|| n.Contains("medusa")
			|| n.Contains("black_dragon")
			|| n.Contains("pet_")
			|| n.Contains("pet ");
	}

	private static bool IsTurnOrderPath(string text)
	{
		if (string.IsNullOrWhiteSpace(text))
			return false;
		var n = text.ToLowerInvariant();
		return n.Contains("order hud")
			|| n.Contains("turn item")
			|| n.Contains("turn view")
			|| n.Contains("turnview")
			|| n.Contains("turn order")
			|| n.Contains("turn_order")
			|| n.Contains("initiative")
			|| n.Contains("timeline")
			|| n.Contains("queue");
	}

	private static void ClearStaleAbilityViews(BhSelectedUnitHud hud)
	{
		try
		{
			var mn = hud as MonoBehaviour;
			if (mn == null || mn.transform == null)
				return;
			var hidden = 0;
			var components = mn.GetComponentsInChildren<Component>(true);
			for (var i = 0; i < components.Length; i++)
			{
				var component = components[i];
				if (component == null)
					continue;
				var typeName = component.GetType().FullName ?? component.GetType().Name;
				var go = component.gameObject;
				if (go == null || !LooksLikeAbilityView(typeName, go.name))
					continue;
				if (!go.activeSelf)
					continue;
				go.SetActive(false);
				hidden++;
			}
			if (hidden > 0 && IsDiagnosticEnabled() && _loggedPortraitReplace < 30)
			{
				_loggedPortraitReplace++;
				Plugin.LogSource?.LogInfo("Homm3Import selected-unit HUD: hid " + hidden + " stale ability view object(s) after custom SID lookup failure.");
			}
			if (hidden == 0)
				hidden = ClearSceneStaleAbilityViews();
			if (hidden == 0 && !_sceneAbilityTargetsScanned)
				LogHudSurfaceDiag(hud, null, "ability-miss");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD ability cleanup failed: " + ex.Message);
		}
	}

	private static int ClearSceneStaleAbilityViews()
	{
		var hidden = 0;
		try
		{
			hidden = HideCachedSceneAbilityTargets();
			if (_sceneAbilityTargetsScanned)
				return hidden;

			var components = Resources.FindObjectsOfTypeAll<Component>();
			for (var i = 0; i < components.Length; i++)
			{
				var component = components[i];
				if (component == null || component.gameObject == null || !component.gameObject.activeInHierarchy)
					continue;
				if (!IsUnderCanvas(component.transform))
					continue;
				var typeName = component.GetType().FullName ?? component.GetType().Name;
				var path = GetPath(component.transform);
				if (!LooksLikeSelectedBattleAbilityView(typeName, component.gameObject.name, path))
					continue;

				var go = component.gameObject;
				if (!go.activeSelf)
					continue;
				if (!SceneAbilityTargets.Contains(go))
					SceneAbilityTargets.Add(go);
				go.SetActive(false);
				hidden++;
				if (IsDiagnosticEnabled() && _loggedSceneAbilityCleanup < 20)
				{
					_loggedSceneAbilityCleanup++;
					Plugin.LogSource?.LogInfo(
						"Homm3Import selected-unit HUD scene ability: hid object path='"
						+ path + "' type='" + typeName + "'.");
				}
			}
			if (hidden > 0 && IsDiagnosticEnabled() && _loggedSceneAbilityCleanup < 25)
			{
				_loggedSceneAbilityCleanup++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import selected-unit HUD scene ability: hid " + hidden
					+ " stale active ability object(s) after custom SID lookup failure.");
			}
			_sceneAbilityTargetsScanned = true;
		}
		catch (Exception ex)
		{
			if (_loggedSceneAbilityCleanup < 5)
			{
				_loggedSceneAbilityCleanup++;
				Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD scene ability cleanup failed: " + ex.Message);
			}
		}
		return hidden;
	}

	private static int HideCachedSceneAbilityTargets()
	{
		var hidden = 0;
		for (var i = SceneAbilityTargets.Count - 1; i >= 0; i--)
		{
			var go = SceneAbilityTargets[i];
			if (go == null)
			{
				SceneAbilityTargets.RemoveAt(i);
				continue;
			}
			if (!go.activeSelf)
				continue;
			go.SetActive(false);
			hidden++;
		}
		return hidden;
	}

	private static bool LooksLikeAbilityView(string typeName, string objectName)
	{
		var t = (typeName ?? string.Empty).ToLowerInvariant();
		var n = (objectName ?? string.Empty).ToLowerInvariant();
		if (t.Contains("bhunitabilityview") || t.Contains("unitability"))
			return true;
		if (n.Contains("ability") || n.Contains("skill") || n.Contains("cooldown") || n.Contains("focus"))
			return true;
		return false;
	}

	private static bool LooksLikeSelectedBattleAbilityView(string typeName, string objectName, string path)
	{
		var t = (typeName ?? string.Empty).ToLowerInvariant();
		var n = (objectName ?? string.Empty).ToLowerInvariant();
		var p = (path ?? string.Empty).ToLowerInvariant();
		if (t.Contains("tooltip") || p.Contains("tooltip") || p.Contains("hire") || p.Contains("city"))
			return false;
		if (t.Contains("bhunitabilityview"))
			return true;
		if (!p.Contains("unit") && !p.Contains("selection") && !p.Contains("selected") && !p.Contains("hud"))
			return false;
		return t.Contains("unitability")
			|| n.Contains("unitability")
			|| n.Contains("ability")
			|| n.Contains("skill")
			|| n.Contains("cooldown")
			|| n.Contains("focus");
	}

	private static bool IsUnderCanvas(Transform transform)
	{
		for (var t = transform; t != null; t = t.parent)
		{
			if (t.GetComponent<Canvas>() != null)
				return true;
		}
		return false;
	}

	private static string GetPath(Transform transform)
	{
		if (transform == null)
			return string.Empty;
		var path = transform.name ?? string.Empty;
		for (var t = transform.parent; t != null; t = t.parent)
			path = (t.name ?? string.Empty) + "/" + path;
		return path;
	}

	private static void LogHudSurfaceDiag(BhSelectedUnitHud hud, string sid, string reason)
	{
		if (!IsDiagnosticEnabled())
			return;
		if (_loggedHudDiag >= 8)
			return;
		_loggedHudDiag++;
		try
		{
			var mn = hud as MonoBehaviour;
			if (mn == null || mn.transform == null)
			{
				Plugin.LogSource?.LogInfo("Homm3Import selected-unit HUD diag[" + reason + "]: no MonoBehaviour/transform sid='" + (sid ?? "?") + "'.");
				return;
			}

			var images = mn.transform.GetComponentsInChildren<Image>(true);
			var imageRows = new System.Text.StringBuilder();
			var imageCount = Math.Min(images.Length, 36);
			for (var i = 0; i < imageCount; i++)
			{
				var image = images[i];
				if (image == null)
					continue;
				if (imageRows.Length > 0)
					imageRows.Append(" | ");
				imageRows.Append(image.name)
					.Append(" active=").Append(image.gameObject != null && image.gameObject.activeSelf)
					.Append(" en=").Append(image.enabled)
					.Append(" sprite=").Append(image.sprite != null ? image.sprite.name : "?")
					.Append(" parent=").Append(image.transform?.parent != null ? image.transform.parent.name : "?");
			}

			var comps = mn.transform.GetComponentsInChildren<Component>(true);
			var compRows = new System.Text.StringBuilder();
			var compLogged = 0;
			for (var i = 0; i < comps.Length && compLogged < 50; i++)
			{
				var comp = comps[i];
				if (comp == null || comp.gameObject == null)
					continue;
				var zj = comp.GetType().FullName ?? comp.GetType().Name;
				var lower = (zj + " " + comp.gameObject.name).ToLowerInvariant();
				if (!lower.Contains("ability") && !lower.Contains("skill") && !lower.Contains("cooldown") && !lower.Contains("unit"))
					continue;
				if (compRows.Length > 0)
					compRows.Append(" | ");
				compRows.Append(comp.gameObject.name)
					.Append(":").Append(zj)
					.Append(" active=").Append(comp.gameObject.activeSelf);
				compLogged++;
			}

			Plugin.LogSource?.LogInfo(
				"Homm3Import selected-unit HUD diag[" + reason + "] sid='" + (sid ?? "?")
				+ "' root='" + mn.name + "' images=" + images.Length + " [" + imageRows + "] comps=[" + compRows + "].");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import selected-unit HUD diag failed: " + ex.Message);
		}
	}

	private static string ExtractMissingKey(Exception ex)
	{
		for (var e = ex; e != null; e = e.InnerException)
		{
			var msg = e.Message ?? string.Empty;
			var marker = "key '";
			var i = msg.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
			if (i < 0)
				continue;
			i += marker.Length;
			var j = msg.IndexOf('\'', i);
			if (j > i)
				return msg.Substring(i, j - i);
		}
		return null;
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static string SafeExtractSid(Unit unit)
	{
		try
		{
			return ExtractSid(unit);
		}
		catch
		{
			return null;
		}
	}

	private static string SafeExtractSidFieldOnly(Unit unit)
	{
		try
		{
			return ExtractSidFieldOnly(unit);
		}
		catch
		{
			return null;
		}
	}

	private static string ExtractSid(Unit unit)
	{
		if (unit == null)
			return null;
		var direct = FirstSidCandidate(
			TryGetStringMember(unit, "sid"),
			TryGetStringMember(unit, "configSid"));
		if (!string.IsNullOrWhiteSpace(direct))
			return direct;

		var transferSid = ExtractSidFromMembers(unit, GameSymbols.BattleUi.UnitTransferFields);
		if (!string.IsNullOrWhiteSpace(transferSid))
			return transferSid;

		var configSid = ExtractSidFromMembers(unit, GameSymbols.BattleUi.UnitConfigIdFields);
		if (!string.IsNullOrWhiteSpace(configSid))
			return configSid;

		var shapeSid = ExtractSidFromMembers(unit, GameSymbols.BattleUi.UnitShapeNestedFields);
		if (!string.IsNullOrWhiteSpace(shapeSid))
			return shapeSid;

		try
		{
			var prop = unit.GetType().GetProperty("sid", BindingFlags.Public | BindingFlags.Instance);
			if (prop != null && prop.CanRead)
				return (prop.GetValue(unit) as string)?.Trim();
		}
		catch { }

		return null;
	}

	private static string ExtractSidFieldOnly(Unit unit)
	{
		if (unit == null)
			return null;
		var direct = FirstSidCandidate(
			TryGetStringMember(unit, "sid"),
			TryGetStringMember(unit, "configSid"));
		if (!string.IsNullOrWhiteSpace(direct))
			return direct;

		var transferSid = ExtractSidFromMembersFieldOnly(unit, GameSymbols.BattleUi.UnitTransferFields);
		if (!string.IsNullOrWhiteSpace(transferSid))
			return transferSid;

		var configSid = ExtractSidFromMembersFieldOnly(unit, GameSymbols.BattleUi.UnitConfigIdFields);
		if (!string.IsNullOrWhiteSpace(configSid))
			return configSid;

		return ExtractSidFromMembersFieldOnly(unit, GameSymbols.BattleUi.UnitShapeNestedFields);
	}

	private static string ExtractSidFromMembers(object owner, string[] memberNames)
	{
		if (owner == null || memberNames == null)
			return null;
		for (var i = 0; i < memberNames.Length; i++)
		{
			var value = ExtractSidFromObject(TryGetUnitMemberValue(owner, memberNames[i]) ?? TryReadNativeObjectMember(owner, memberNames[i]));
			if (!string.IsNullOrWhiteSpace(value))
				return value;
		}
		return null;
	}

	private static string ExtractSidFromMembersFieldOnly(object owner, string[] memberNames)
	{
		if (owner == null || memberNames == null)
			return null;
		for (var i = 0; i < memberNames.Length; i++)
		{
			var value = ExtractSidFromObject(TryGetMemberValue(owner, memberNames[i]) ?? TryReadNativeObjectMember(owner, memberNames[i]));
			if (!string.IsNullOrWhiteSpace(value))
				return value;
		}
		return null;
	}

	private static object TryGetUnitMemberValue(object owner, string name)
	{
		return TryGetMemberValue(owner, name) ?? TryInvokeNoArg(owner, name);
	}

	private static string ExtractSidFromObject(object value)
	{
		if (value == null)
			return null;
		if (value is string text)
			return string.IsNullOrWhiteSpace(text) ? null : text.Trim();

		return FirstSidCandidate(
			TryGetStringMember(value, "configSid"),
			TryGetStringMember(value, "sid"),
			DeobfInteropCompat.GetConfigElementId(value),
			TryGetStringMember(value, "id"),
			TryGetStringMember(value, "cnee"),
			TryGetStringMember(value, "cnei"),
			TryReadNativeStringMember(value, "configSid"),
			TryReadNativeStringMember(value, "sid"),
			TryReadNativeStringMember(value, "id"),
			TryReadNativeStringMember(value, "cnee"),
			TryReadNativeStringMember(value, "cnei"));
	}

	private static string FirstSidCandidate(params string[] values)
	{
		if (values == null)
			return null;
		for (var i = 0; i < values.Length; i++)
		{
			var value = values[i];
			if (!string.IsNullOrWhiteSpace(value))
				return value.Trim();
		}
		return null;
	}

	private static object TryGetMemberValue(object owner, string name)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = owner.GetType();
		try
		{
			var field = type.GetField(name, flags);
			if (field != null)
				return field.GetValue(owner);
		}
		catch { }
		return null;
	}

	private static object TryReadNativeObjectMember(object owner, string name)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name))
			return null;
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		for (var current = owner.GetType(); current != null; current = current.BaseType)
		{
			var fieldPtr = ResolveNativeFieldPointer(current, name);
			if (fieldPtr == IntPtr.Zero)
				continue;
			var fieldTypeName = ResolveNativeFieldTypeName(fieldPtr);
			var fieldType = ResolveNativeFieldManagedType(fieldTypeName);
			if (fieldType == null || !typeof(Il2CppObjectBase).IsAssignableFrom(fieldType))
				continue;
			try
			{
				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
				if (valuePtr == IntPtr.Zero)
					continue;
				return CreateIl2CppObjectWrapper(valuePtr, fieldType);
			}
			catch
			{
			}
		}
		return null;
	}

	private static object TryReadNativeObjectMemberWithFieldType(object owner, string name)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name))
			return null;
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		for (var current = owner.GetType(); current != null; current = current.BaseType)
		{
			var fieldPtr = ResolveNativeFieldPointer(current, name);
			if (fieldPtr == IntPtr.Zero)
				continue;
			var fieldTypeName = ResolveNativeFieldTypeName(fieldPtr);
			var fieldType = ResolveNativeFieldManagedType(fieldTypeName);
			if (fieldType == null || !typeof(Il2CppObjectBase).IsAssignableFrom(fieldType))
				continue;
			try
			{
				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
				if (valuePtr == IntPtr.Zero)
					continue;
				return CreateIl2CppObjectWrapper(valuePtr, fieldType);
			}
			catch
			{
			}
		}
		return null;
	}

	private static T TryReadNativeObjectMember<T>(object owner, string[] names)
		where T : Il2CppObjectBase
	{
		if (owner == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryReadNativeObjectMember<T>(owner, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static T TryReadNativeObjectMember<T>(object owner, string name)
		where T : Il2CppObjectBase
	{
		if (owner == null || string.IsNullOrWhiteSpace(name))
			return null;
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		for (var current = owner.GetType(); current != null; current = current.BaseType)
		{
			var fieldPtr = ResolveNativeFieldPointer(current, name);
			if (fieldPtr == IntPtr.Zero)
				continue;
			if (!NativeFieldTypeAssignableTo<T>(fieldPtr))
				continue;
			try
			{
				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
				if (valuePtr == IntPtr.Zero)
					continue;
				return Il2CppObjectPool.Get<T>(valuePtr);
			}
			catch
			{
			}
		}
		return null;
	}

	private static object TryReadNativeObjectMember(object owner, string name, Type expectedType)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name) || expectedType == null)
			return null;
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		for (var current = owner.GetType(); current != null; current = current.BaseType)
		{
			var fieldPtr = ResolveNativeFieldPointer(current, name);
			if (fieldPtr == IntPtr.Zero)
				continue;
			var fieldTypeName = ResolveNativeFieldTypeName(fieldPtr);
			if (!NativeFieldTypeAssignableTo(fieldTypeName, expectedType))
			{
				LogNativeManagerFieldTypeMiss(owner, name, fieldTypeName, expectedType);
				continue;
			}
			try
			{
				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
				if (valuePtr == IntPtr.Zero)
					continue;
				return CreateIl2CppObjectWrapper(valuePtr, expectedType);
			}
			catch
			{
			}
		}
		return null;
	}

	private static string TryReadNativeStringMember(object owner, string name)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name))
			return null;
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		for (var current = owner.GetType(); current != null; current = current.BaseType)
		{
			var fieldPtr = ResolveNativeFieldPointer(current, name);
			if (fieldPtr == IntPtr.Zero)
				continue;
			if (!NativeFieldTypeIsString(fieldPtr))
				continue;
			try
			{
				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
				if (valuePtr == IntPtr.Zero)
					continue;
				var text = IL2CPP.Il2CppStringToManaged(valuePtr);
				if (string.IsNullOrWhiteSpace(text))
					continue;
				if (IsDiagnosticEnabled()
				    && _loggedNativeSidFieldRead < 8
				    && Homm3CustomFactionRegistry.IsCustomUnitSid(text))
				{
					_loggedNativeSidFieldRead++;
					Plugin.LogSource?.LogInfo(
						"Homm3Import selected-unit HUD native SID field read: owner='"
						+ owner.GetType().FullName
						+ "' field='"
						+ name
						+ "' sid='"
						+ text
						+ "'.");
				}
				return text.Trim();
			}
			catch
			{
			}
		}
		return null;
	}

	private static bool TryWriteNativeStringMember(object owner, string name, string value)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name) || value == null)
			return false;
		if (owner is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return false;
		for (var current = owner.GetType(); current != null; current = current.BaseType)
		{
			var fieldPtr = ResolveNativeFieldPointer(current, name);
			if (fieldPtr == IntPtr.Zero)
				continue;
			if (!NativeFieldTypeIsString(fieldPtr))
				continue;
			try
			{
				var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
				var targetAddress = IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr));
				IL2CPP.il2cpp_gc_wbarrier_set_field(objectPtr, targetAddress, IL2CPP.ManagedStringToIl2Cpp(value));
				return true;
			}
			catch
			{
			}
		}
		return false;
	}

	private static bool NativeFieldTypeIsString(IntPtr fieldPtr)
	{
		var fieldTypeName = ResolveNativeFieldTypeName(fieldPtr);
		if (string.IsNullOrWhiteSpace(fieldTypeName))
			return false;
		var clean = CleanIl2CppTypeName(fieldTypeName);
		return string.Equals(clean, "System.String", StringComparison.Ordinal)
		       || string.Equals(clean, "String", StringComparison.Ordinal)
		       || string.Equals(clean, "Il2CppSystem.String", StringComparison.Ordinal);
	}

	private static IntPtr ResolveNativeFieldPointer(Type ownerType, string logicalName)
	{
		if (ownerType == null || string.IsNullOrWhiteSpace(logicalName))
			return IntPtr.Zero;
		TryInitializeIl2CppType(ownerType);
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		for (var current = ownerType; current != null; current = current.BaseType)
		{
			foreach (var candidate in ExpandNativeFieldCandidates(logicalName))
			{
				try
				{
					var managedField = current.GetField(candidate.NativeInfoName, flags);
					if (managedField != null && managedField.FieldType == typeof(IntPtr) && managedField.IsStatic)
					{
						var ptr = (IntPtr)managedField.GetValue(null);
						if (ptr != IntPtr.Zero)
							return ptr;
					}
				}
				catch
				{
				}

				// Do not call IL2CPP.GetIl2CppField here. It logs every miss as an
				// Il2CppInterop error, which turns stale candidate probing into log spam.
				// This hot path only uses generated interop field handles.
			}
		}
		return IntPtr.Zero;
	}

	private static bool NativeFieldTypeAssignableTo<T>(IntPtr fieldPtr)
		where T : Il2CppObjectBase
	{
		return NativeFieldTypeAssignableTo(fieldPtr, typeof(T));
	}

	private static bool NativeFieldTypeAssignableTo(IntPtr fieldPtr, Type expectedType)
	{
		return NativeFieldTypeAssignableTo(ResolveNativeFieldTypeName(fieldPtr), expectedType);
	}

	private static bool NativeFieldTypeAssignableTo(Type fieldType, Type expectedType)
	{
		return fieldType != null
		       && expectedType != null
		       && (expectedType.IsAssignableFrom(fieldType) || GameInteropTypes.TypesMatch(fieldType, expectedType));
	}

	private static bool NativeFieldTypeAssignableTo(string nativeTypeName, Type expectedType)
	{
		if (string.IsNullOrWhiteSpace(nativeTypeName) || expectedType == null)
			return false;
		var clean = CleanIl2CppTypeName(nativeTypeName);
		if (string.Equals(clean, expectedType.FullName, StringComparison.Ordinal)
		    || string.Equals(clean, expectedType.Name, StringComparison.Ordinal))
			return true;
		if (NativeTypeNameMatchesExpectedAlias(clean, expectedType))
			return true;
		if (!expectedType.IsGenericType)
			return false;
		var genericDefinition = expectedType.GetGenericTypeDefinition();
		if (!NativeTypeNameStartsWithGenericDefinition(clean, genericDefinition))
			return false;
		var args = expectedType.GetGenericArguments();
		for (var i = 0; i < args.Length; i++)
		{
			if (NativeTypeNameContainsExpectedAlias(clean, args[i]))
				continue;
			return false;
		}
		return true;
	}

	private static bool NativeTypeNameMatchesExpectedAlias(string nativeTypeName, Type expectedType)
	{
		if (string.IsNullOrWhiteSpace(nativeTypeName) || expectedType == null)
			return false;
		var aliases = GetNativeTypeAliases(expectedType);
		for (var i = 0; i < aliases.Length; i++)
		{
			var alias = aliases[i];
			if (string.IsNullOrWhiteSpace(alias))
				continue;
			if (string.Equals(nativeTypeName, alias, StringComparison.Ordinal)
			    || nativeTypeName.EndsWith("." + alias, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool NativeTypeNameStartsWithGenericDefinition(string nativeTypeName, Type genericDefinition)
	{
		if (string.IsNullOrWhiteSpace(nativeTypeName) || genericDefinition == null)
			return false;
		var names = new[]
		{
			genericDefinition.FullName,
			genericDefinition.Name,
			NormalizeIl2CppSystemGenericName(genericDefinition.FullName),
			NormalizeIl2CppSystemGenericName(genericDefinition.Name)
		};
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			if (nativeTypeName.StartsWith(name, StringComparison.Ordinal))
				return true;
			var tick = name.IndexOf('`');
			if (tick > 0 && nativeTypeName.StartsWith(name.Substring(0, tick) + "<", StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static string NormalizeIl2CppSystemGenericName(string typeName)
	{
		if (string.IsNullOrWhiteSpace(typeName))
			return null;
		return typeName.StartsWith("Il2CppSystem.", StringComparison.Ordinal)
			? "System." + typeName.Substring("Il2CppSystem.".Length)
			: null;
	}

	private static bool NativeTypeNameContainsExpectedAlias(string nativeTypeName, Type expectedType)
	{
		if (string.IsNullOrWhiteSpace(nativeTypeName) || expectedType == null)
			return false;
		var fullName = expectedType.FullName ?? "";
		var shortName = expectedType.Name ?? "";
		if (fullName.Length > 0 && nativeTypeName.IndexOf(fullName, StringComparison.Ordinal) >= 0)
			return true;
		if (shortName.Length > 0 && nativeTypeName.IndexOf(shortName, StringComparison.Ordinal) >= 0)
			return true;
		var aliases = GetNativeTypeAliases(expectedType);
		for (var i = 0; i < aliases.Length; i++)
		{
			var alias = aliases[i];
			if (!string.IsNullOrWhiteSpace(alias) && NativeTypeNameContainsTypeToken(nativeTypeName, alias))
				return true;
		}
		return false;
	}

	private static bool NativeTypeNameContainsTypeToken(string nativeTypeName, string token)
	{
		if (string.IsNullOrWhiteSpace(nativeTypeName) || string.IsNullOrWhiteSpace(token))
			return false;
		var start = 0;
		while (start < nativeTypeName.Length)
		{
			var index = nativeTypeName.IndexOf(token, start, StringComparison.Ordinal);
			if (index < 0)
				return false;
			var before = index == 0 ? '\0' : nativeTypeName[index - 1];
			var afterIndex = index + token.Length;
			var after = afterIndex >= nativeTypeName.Length ? '\0' : nativeTypeName[afterIndex];
			if (IsNativeTypeNameTokenBoundary(before) && IsNativeTypeNameTokenBoundary(after))
				return true;
			start = index + token.Length;
		}
		return false;
	}

	private static bool IsNativeTypeNameTokenBoundary(char c)
	{
		return c == '\0'
		       || c == '<'
		       || c == '>'
		       || c == ','
		       || c == ' '
		       || c == '['
		       || c == ']'
		       || c == '*'
		       || c == '&'
		       || c == '.';
	}

	private static string[] GetNativeTypeAliases(Type expectedType)
	{
		return GameInteropTypes.GetNativeTypeAliases(expectedType);
	}

	private static void LogNativeManagerFieldTypeMiss(object owner, string fieldName, string fieldTypeName, Type expectedType)
	{
		if (_loggedNativeManagerFieldTypeMiss >= 12)
			return;
		_loggedNativeManagerFieldTypeMiss++;
		Plugin.LogSource?.LogWarning(
			"Homm3Import selected-unit HUD native manager field skipped: owner='"
			+ (owner?.GetType().FullName ?? "?")
			+ "' field='"
			+ fieldName
			+ "' fieldType='"
			+ (string.IsNullOrWhiteSpace(fieldTypeName) ? "?" : fieldTypeName)
			+ "' expected='"
			+ (expectedType?.FullName ?? "?")
			+ "'.");
	}

	private static string ResolveNativeFieldTypeName(IntPtr fieldPtr)
	{
		if (fieldPtr == IntPtr.Zero)
			return null;
		try
		{
			var getType = typeof(IL2CPP).GetMethod("il2cpp_field_get_type", BindingFlags.Public | BindingFlags.Static);
			var getName = typeof(IL2CPP).GetMethod("il2cpp_type_get_name", BindingFlags.Public | BindingFlags.Static);
			if (getType == null || getName == null)
				return null;
			var typePtr = getType.Invoke(null, new object[] { fieldPtr });
			if (typePtr is not IntPtr nativeType || nativeType == IntPtr.Zero)
				return null;
			var nameResult = getName.Invoke(null, new object[] { nativeType });
			return nameResult switch
			{
				string text => text,
				IntPtr ptr when ptr != IntPtr.Zero => Marshal.PtrToStringAnsi(ptr),
				_ => null
			};
		}
		catch
		{
			return null;
		}
	}

	private static Type ResolveNativeFieldManagedType(string nativeTypeName)
	{
		var clean = CleanIl2CppTypeName(nativeTypeName);
		if (string.IsNullOrWhiteSpace(clean))
			return null;
		if (string.Equals(clean, typeof(Unit).FullName, StringComparison.Ordinal))
			return typeof(Unit);
		if (string.Equals(clean, typeof(UnitLogicConfig).FullName, StringComparison.Ordinal))
			return typeof(UnitLogicConfig);
		if (string.Equals(clean, typeof(UnitViewConfig).FullName, StringComparison.Ordinal))
			return typeof(UnitViewConfig);
		if (string.Equals(clean, typeof(BhUnitAbilityView).FullName, StringComparison.Ordinal))
			return typeof(BhUnitAbilityView);
		if (string.Equals(clean, typeof(BhUnitControlsView).FullName, StringComparison.Ordinal))
			return typeof(BhUnitControlsView);
		if (string.Equals(clean, typeof(BhSelectedUnitHud).FullName, StringComparison.Ordinal))
			return typeof(BhSelectedUnitHud);
		try
		{
			var type = Type.GetType(clean, false);
			if (type != null)
				return type;
			foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
			{
				try
				{
					type = assembly.GetType(clean, false);
					if (type != null)
						return type;
				}
				catch
				{
				}
			}
		}
		catch
		{
		}
		return null;
	}

	private static string CleanIl2CppTypeName(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return "";
		var value = name.Trim();
		if (value.StartsWith("class ", StringComparison.Ordinal))
			value = value.Substring("class ".Length);
		else if (value.StartsWith("struct ", StringComparison.Ordinal))
			value = value.Substring("struct ".Length);
		return value.TrimEnd('*', '&').Trim();
	}

	private static object CreateIl2CppObjectWrapper(IntPtr valuePtr, Type expectedType)
	{
		if (valuePtr == IntPtr.Zero || expectedType == null)
			return null;
		try
		{
			if (typeof(Il2CppObjectBase).IsAssignableFrom(expectedType))
			{
				foreach (var method in typeof(Il2CppObjectPool).GetMethods(BindingFlags.Public | BindingFlags.Static))
				{
					if (!string.Equals(method.Name, "Get", StringComparison.Ordinal) || !method.IsGenericMethodDefinition)
						continue;
					var parameters = method.GetParameters();
					if (parameters.Length == 1 && parameters[0].ParameterType == typeof(IntPtr))
						return method.MakeGenericMethod(expectedType).Invoke(null, new object[] { valuePtr });
				}
			}
		}
		catch
		{
		}
		return null;
	}

	private static IEnumerable<(string Il2CppName, string NativeInfoName)> ExpandNativeFieldCandidates(string logicalName)
	{
		if (string.IsNullOrWhiteSpace(logicalName))
			yield break;

		yield return (logicalName, "NativeFieldInfoPtr_" + logicalName);

		if (logicalName.StartsWith("<", StringComparison.Ordinal) && logicalName.EndsWith(">k__BackingField", StringComparison.Ordinal))
		{
			var end = logicalName.IndexOf('>', StringComparison.Ordinal);
			if (end > 1)
			{
				var inner = logicalName.Substring(1, end - 1);
				yield return (logicalName, "NativeFieldInfoPtr__" + inner + "_k__BackingField");
				yield return ("_" + inner + "_k__BackingField", "NativeFieldInfoPtr__" + inner + "_k__BackingField");
				yield return (inner, "NativeFieldInfoPtr_" + inner);
			}
		}

		if (logicalName.StartsWith("_", StringComparison.Ordinal) && logicalName.EndsWith("_k__BackingField", StringComparison.Ordinal))
		{
			var inner = logicalName.Substring(1, logicalName.Length - "_k__BackingField".Length - 1);
			if (!string.IsNullOrWhiteSpace(inner))
			{
				yield return ("<" + inner + ">k__BackingField", "NativeFieldInfoPtr__" + inner + "_k__BackingField");
				yield return (inner, "NativeFieldInfoPtr_" + inner);
			}
		}
	}

	private static IntPtr GetNativeClassPtr(Type managedType)
	{
		if (managedType == null)
			return IntPtr.Zero;
		try
		{
			var storeType = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			var nativeClassPtrField = storeType.GetField("NativeClassPtr", BindingFlags.Static | BindingFlags.Public);
			if (nativeClassPtrField?.FieldType == typeof(IntPtr))
			{
				var value = (IntPtr)nativeClassPtrField.GetValue(null);
				if (value != IntPtr.Zero)
					return value;
			}
		}
		catch
		{
		}
		try
		{
			var field = managedType.GetField("NativeClassPtr", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (field?.FieldType == typeof(IntPtr))
				return (IntPtr)field.GetValue(null);
		}
		catch
		{
		}
		return IntPtr.Zero;
	}

	private static void TryInitializeIl2CppType(Type managedType)
	{
		if (managedType == null)
			return;
		try
		{
			RuntimeHelpers.RunClassConstructor(managedType.TypeHandle);
		}
		catch
		{
		}
	}

	private static Type FindFirstRuntimeType(string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = GameMember.FindType("battle.selectedUnit.configRoot." + name, name);
			if (type != null)
				return type;
			foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
			{
				try
				{
					type = assembly.GetType(name, throwOnError: false);
					if (type != null)
						return type;
				}
				catch { }
			}
		}
		return null;
	}

	private static object TryGetFirstStaticMemberValue(Type type, string[] names)
	{
		if (type == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(null);
			}
			catch { }
			try
			{
				var property = type.GetProperty(name, flags);
				if (property != null
				    && property.CanRead
				    && property.GetIndexParameters().Length == 0
				    && GameInteropTypes.TypesMatch(property.PropertyType, type))
					return property.GetValue(null, null);
			}
			catch { }
		}
		return null;
	}

	private static object TryGetFirstMemberValue(object owner, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryGetMemberValue(owner, names[i]) ?? TryReadNativeObjectMember(owner, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryGetFirstMemberValue(object owner, string[] names, Type expectedType)
	{
		if (owner == null || expectedType == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		if (names != null)
		{
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				for (var current = owner.GetType(); current != null; current = current.BaseType)
				{
					var field = current.GetField(name, flags);
					if (field == null || !ParameterTypesMatch(field.FieldType, expectedType))
						continue;
					try { return field.GetValue(owner); }
					catch { continue; }
				}
				var nativeValue = TryReadNativeObjectMember(owner, name);
				if (nativeValue != null && ParameterTypesMatch(nativeValue.GetType(), expectedType))
					return nativeValue;
			}
		}

		FieldInfo unique = null;
		for (var current = owner.GetType(); current != null; current = current.BaseType)
		{
			foreach (var field in current.GetFields(flags))
			{
				if (!ParameterTypesMatch(field.FieldType, expectedType))
					continue;
				if (unique != null)
					return null;
				unique = field;
			}
		}
		if (unique == null)
			return null;
		try { return unique.GetValue(owner); }
		catch { return null; }
	}

	private static bool TrySetFirstMemberValue(object owner, string[] names, Type expectedType, object value)
	{
		if (owner == null || names == null || expectedType == null)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var current = owner.GetType(); current != null; current = current.BaseType)
			{
				var field = current.GetField(name, flags);
				if (field == null || !ParameterTypesMatch(field.FieldType, expectedType))
					continue;
				try
				{
					field.SetValue(owner, value);
					return true;
				}
				catch
				{
					return false;
				}
			}
		}
		return false;
	}

	private static object TryInvokeNoArg(object owner, string name)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			var method = owner.GetType().GetMethod(name, flags);
			if (method == null || method.GetParameters().Length != 0)
				return null;
			return method.Invoke(owner, null);
		}
		catch { }
		return null;
	}

	private static object TryInvokeFirstNoArg(object owner, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryInvokeNoArg(owner, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static string TryGetStringMember(object owner, string name)
	{
		return TryGetMemberValue(owner, name) as string ?? TryReadNativeStringMember(owner, name);
	}

	private static bool TryGetBoolMember(object owner, string name, out bool value)
	{
		value = false;
		var raw = TryGetMemberValue(owner, name);
		if (raw is bool boolValue)
		{
			value = boolValue;
			return true;
		}
		if (raw != null && bool.TryParse(raw.ToString(), out var parsed))
		{
			value = parsed;
			return true;
		}
		return false;
	}

	private static bool TrySetStringMember(object owner, string name, string value)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name))
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = owner.GetType();
		try
		{
			var prop = type.GetProperty(name, flags);
			if (prop != null && prop.CanWrite && prop.GetIndexParameters().Length == 0 && prop.PropertyType == typeof(string))
			{
				prop.SetValue(owner, value);
				return true;
			}
		}
		catch { }
		try
		{
			var field = type.GetField(name, flags);
			if (field != null && field.FieldType == typeof(string))
			{
				field.SetValue(owner, value);
				return true;
			}
		}
		catch { }
		return TryWriteNativeStringMember(owner, name, value);
	}

	private static bool WriteUnitSid(Unit unit, string value)
	{
		if (unit == null || string.IsNullOrWhiteSpace(value))
			return false;
		var wrote = false;
		wrote |= TrySetStringMember(unit, "sid", value);
		wrote |= TrySetStringMember(unit, "<sid>k__BackingField", value);
		wrote |= TrySetStringMember(unit, "configSid", value);
		foreach (var name in GameSymbols.BattleUi.UnitTransferFields)
			wrote |= TrySetStringMember(GetUnitConfigObject(unit, name), "configSid", value);
		foreach (var name in GameSymbols.BattleUi.UnitConfigIdFields)
			wrote |= TrySetStringMember(GetUnitConfigObject(unit, name), "id", value);
		foreach (var name in GameSymbols.SelectedUnitHud.UnitSidTransferFields)
			wrote |= TrySetStringMember(GetUnitConfigObject(unit, name), "configSid", value);
		foreach (var name in GameSymbols.SelectedUnitHud.UnitSidConfigIdFields)
			wrote |= TrySetStringMember(GetUnitConfigObject(unit, name), "id", value);
		return wrote;
	}


	private static object GetUnitConfigObject(Unit unit, string propertyName)
	{
		return TryGetUnitMemberValue(unit, propertyName)
		       ?? TryReadNativeObjectMember(unit, propertyName)
		       ?? TryGetMemberValue(unit, "<" + propertyName + ">k__BackingField")
		       ?? TryGetMemberValue(unit, "_" + propertyName + "_k__BackingField")
		       ?? TryReadNativeObjectMember(unit, "<" + propertyName + ">k__BackingField")
		       ?? TryReadNativeObjectMember(unit, "_" + propertyName + "_k__BackingField");
	}



	private static string TryGetConfigId(object config)
	{
		return DeobfInteropCompat.GetConfigElementId(config)
		       ?? TryGetStringMember(config, "id")
		       ?? TryGetStringMember(config, "<id>k__BackingField")
		       ?? TryGetStringMember(config, "cnas");
	}

	private static bool TrySetConfigId(object config, string value)
	{
		return DeobfInteropCompat.TrySetConfigElementId(config, value)
		       || TrySetStringMember(config, "id", value)
		       || TrySetStringMember(config, "<id>k__BackingField", value)
		       || TrySetStringMember(config, "cnas", value);
	}

	private static bool IsKeyNotFoundException(Exception ex)
	{
		for (var e = ex; e != null; e = e.InnerException)
		{
			if (e.GetType().Name == "KeyNotFoundException")
				return true;
		}
		return ex.ToString().IndexOf("KeyNotFoundException", StringComparison.Ordinal) >= 0;
	}
}

public sealed class Homm3RecoveredHudHotkeyFallback : MonoBehaviour
{
	private void Update()
	{
		Homm3ImportBhSelectedUnitHudFix.ProcessHotkeyFallback();
	}
}
