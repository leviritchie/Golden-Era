using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Flag-gated, read-only probe for selected-unit action-bar keyboard hotkeys.
/// Answers whether native <c>beme</c> can see emb-backed slots after custom SID bind/recovery.
/// Enable only locally: place <c>homm3_selected_unit_hud_hotkey_probe.flag</c> beside the
/// deployed plugin and build with <c>/p:EnableSelectedUnitHudHotkeyProbe=true</c>.
/// Static evidence: <c>experiments/selected_unit_hud_hotkey_static/STATIC_ANALYSIS.md</c>.
/// </summary>
internal static class Homm3SelectedUnitHudHotkeyProbe
{
	internal const string DiagnosticFlag = "homm3_selected_unit_hud_hotkey_probe.flag";
	internal const string GrepKey = "HOMM3_SUH_HOTKEY_PROBE";

	private const int LogCap = 240;
	private static bool _registered;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";
	private static ManualLogSource _log;
	private static int _logged;
	private static int _observed;
	private static int _patched;

	private static FieldInfo _abilityViewUiWrapperField;
	private static FieldInfo _abilityViewActionWrapperField;
	private static readonly string[] ClickBlockedHints = { "cgvr", "cguc", "chag" };
	private static readonly string[] ClickEnabledHints = { "cgvt", "cgue", "chaj" };

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
			var patched = 0;

			foreach (var m in FindHudEventBinds())
			{
				harmony.Patch(
					m,
					prefix: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(PrefixHudEventBind)),
					postfix: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(PostfixHudEventBind)),
					finalizer: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(FinalizerHudEventBind)));
				patched++;
			}

			foreach (var m in FindHudDirectBinds())
			{
				harmony.Patch(
					m,
					prefix: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(PrefixHudDirectBind)),
					postfix: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(PostfixHudDirectBind)),
					finalizer: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(FinalizerHudDirectBind)));
				patched++;
			}

			foreach (var m in FindControlsBindMethods())
			{
				harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(PostfixControlsBind)));
				patched++;
			}

			foreach (var m in FindControlsHotkeyMethods())
			{
				harmony.Patch(
					m,
					prefix: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(PrefixControlsHotkey)),
					postfix: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(PostfixControlsHotkey)));
				patched++;
			}

			foreach (var m in FindControlsClickMethods())
			{
				harmony.Patch(m, prefix: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(PrefixControlsClick)));
				patched++;
			}

			var onClicked = AccessTools.Method(typeof(BhUnitAbilityView), "OnClicked");
			if (onClicked != null)
			{
				harmony.Patch(onClicked, prefix: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(PrefixAbilityOnClicked)));
				patched++;
			}

			foreach (var m in FindAbilityViewBindMethods())
			{
				harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3SelectedUnitHudHotkeyProbe), nameof(PostfixAbilityViewBind)));
				patched++;
			}

			if (patched == 0)
			{
				_registrationAuditStatus = "FAILED_CLOSED: no surfaces patched";
				log?.LogWarning(GrepKey + " registration failed closed: no matching methods.");
				return;
			}

			_patched = patched;
			_registered = true;
			_registrationAuditStatus = "REGISTERED patched=" + patched;
			log?.LogWarning(GrepKey + " registered patched=" + patched + " (read-only; flag=" + DiagnosticFlag + ").");
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.GetType().Name + ": " + ex.Message;
			log?.LogWarning(GrepKey + " registration failed: " + ex.Message);
		}
	}

	private static IEnumerable<MethodInfo> FindHudEventBinds()
	{
		return GameMember.FindMethodsByNames(
			typeof(BhSelectedUnitHud),
			new[] { typeof(object), typeof(BattleEventArgs) },
			GameSymbols.SelectedUnitHud.HudEventBind);
	}

	private static IEnumerable<MethodInfo> FindHudDirectBinds()
	{
		var found = new List<MethodInfo>();
		foreach (var m in typeof(BhSelectedUnitHud).GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (m.ReturnType != typeof(void))
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 2 || ps[0].ParameterType != typeof(bool) || ps[1].ParameterType != typeof(Unit))
				continue;
			if (NameMatches(m.Name, GameSymbols.SelectedUnitHud.HudDirectBind.NameHints))
				found.Add(m);
		}
		return found;
	}

	private static IEnumerable<MethodInfo> FindControlsBindMethods()
	{
		var found = new List<MethodInfo>();
		foreach (var m in typeof(BhUnitControlsView).GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (m.ReturnType != typeof(void))
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 3 || ps[2].ParameterType != typeof(bool))
				continue;
			if (!ps[0].ParameterType.IsArray && !IsIl2CppReferenceArray(ps[0].ParameterType))
				continue;
			if (!NameMatches(m.Name, GameSymbols.SelectedUnitHud.ControlsBind.NameHints))
				continue;
			found.Add(m);
		}
		return found;
	}

	private static IEnumerable<MethodInfo> FindControlsHotkeyMethods()
	{
		return GameMember.FindMethods(
			typeof(BhUnitControlsView),
			typeof(void),
			new[] { typeof(object), typeof(HotkeyAbilityArgs) },
			GameSymbols.SelectedUnitHud.ControlsHotkey);
	}

	private static IEnumerable<MethodInfo> FindControlsClickMethods()
	{
		return GameMember.FindMethods(
			typeof(BhUnitControlsView),
			typeof(void),
			new[] { typeof(BhUnitAbilityView) },
			GameSymbols.SelectedUnitHud.ControlsClick);
	}

	private static IEnumerable<MethodInfo> FindAbilityViewBindMethods()
	{
		var found = new List<MethodInfo>();
		foreach (var m in typeof(BhUnitAbilityView).GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (m.ReturnType != typeof(void))
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 2 || ps[1].ParameterType != typeof(bool))
				continue;
			if (NameMatches(m.Name, GameSymbols.SelectedUnitHud.AbilityViewBind.NameHints))
				found.Add(m);
		}
		return found;
	}

	private static bool IsIl2CppReferenceArray(Type type)
	{
		if (type == null)
			return false;
		var name = type.Name ?? "";
		return name.StartsWith("Il2CppReferenceArray", StringComparison.Ordinal)
		       || name.StartsWith("Il2CppStructArray", StringComparison.Ordinal);
	}

	private static bool NameMatches(string name, IEnumerable<string> hints)
	{
		if (string.IsNullOrWhiteSpace(name) || hints == null)
			return false;
		foreach (var hint in hints)
		{
			if (!string.IsNullOrWhiteSpace(hint) && string.Equals(name, hint, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static void PrefixHudEventBind(BhSelectedUnitHud __instance, BattleEventArgs __1, MethodBase __originalMethod)
	{
		LogHud("hud.event.prefix", __instance, __1?.target, null, __originalMethod);
	}

	private static void PostfixHudEventBind(BhSelectedUnitHud __instance, BattleEventArgs __1, MethodBase __originalMethod)
	{
		LogHud("hud.event.postfix", __instance, __1?.target, null, __originalMethod);
		DumpControls("hud.event.postfix", __instance?.controlsView, SafeSid(__1?.target));
	}

	private static Exception FinalizerHudEventBind(Exception __exception, BhSelectedUnitHud __instance, BattleEventArgs __1, MethodBase __originalMethod)
	{
		if (__exception != null)
			LogHud("hud.event.finalizer.ex", __instance, __1?.target, __exception, __originalMethod);
		return __exception;
	}

	private static void PrefixHudDirectBind(BhSelectedUnitHud __instance, Unit __1, MethodBase __originalMethod)
	{
		LogHud("hud.direct.prefix", __instance, __1, null, __originalMethod);
	}

	private static void PostfixHudDirectBind(BhSelectedUnitHud __instance, Unit __1, MethodBase __originalMethod)
	{
		LogHud("hud.direct.postfix", __instance, __1, null, __originalMethod);
		DumpControls("hud.direct.postfix", __instance?.controlsView, SafeSid(__1));
	}

	private static Exception FinalizerHudDirectBind(Exception __exception, BhSelectedUnitHud __instance, Unit __1, MethodBase __originalMethod)
	{
		if (__exception != null)
			LogHud("hud.direct.finalizer.ex", __instance, __1, __exception, __originalMethod);
		return __exception;
	}

	private static void PostfixControlsBind(BhUnitControlsView __instance, MethodBase __originalMethod)
	{
		_observed++;
		DumpControls("controls.bind:" + (__originalMethod?.Name ?? "?"), __instance, null);
	}

	private static void PrefixControlsHotkey(BhUnitControlsView __instance, object __0, HotkeyAbilityArgs __1, MethodBase __originalMethod)
	{
		_observed++;
		if (!ShouldLog())
			return;
		try
		{
			var idButton = __1 != null ? __1.idButton : -1;
			var prediction = PredictNativeHotkey(__instance, __1);
			Info(
				"hotkey.prefix method=" + (__originalMethod?.Name ?? "?")
				+ " idButton=" + idButton
				+ " isEsc=" + (__1 != null && __1.isEsc)
				+ " isReturnDeselect=" + (__1 != null && __1.isReturnDeselect)
				+ " " + prediction
				+ " " + SummarizeControls(__instance));
		}
		catch (Exception ex)
		{
			Info("hotkey.prefix diag-failed: " + ex.Message);
		}
	}

	private static void PostfixControlsHotkey(BhUnitControlsView __instance, object __0, HotkeyAbilityArgs __1, MethodBase __originalMethod)
	{
		if (!ShouldLog())
			return;
		try
		{
			Info(
				"hotkey.postfix method=" + (__originalMethod?.Name ?? "?")
				+ " idButton=" + (__1 != null ? __1.idButton : -1)
				+ " selected=" + DescribeAbilityView(GetSelectedAbilityView(__instance))
				+ " " + SummarizeControls(__instance));
		}
		catch (Exception ex)
		{
			Info("hotkey.postfix diag-failed: " + ex.Message);
		}
	}

	private static void PrefixControlsClick(BhUnitControlsView __instance, BhUnitAbilityView __0, MethodBase __originalMethod)
	{
		if (!ShouldLog())
			return;
		Info(
			"controls.click method=" + (__originalMethod?.Name ?? "?")
			+ " view=" + DescribeAbilityView(__0)
			+ " " + SummarizeControls(__instance));
	}

	private static void PrefixAbilityOnClicked(BhUnitAbilityView __instance)
	{
		if (!ShouldLog())
			return;
		Info("ability.OnClicked " + DescribeAbilityView(__instance));
	}

	private static void PostfixAbilityViewBind(BhUnitAbilityView __instance, object __0, bool __1, MethodBase __originalMethod)
	{
		if (!ShouldLog())
			return;
		Info(
			"ability.bind method=" + (__originalMethod?.Name ?? "?")
			+ " controllable=" + __1
			+ " embArgNull=" + (__0 == null)
			+ " " + DescribeAbilityView(__instance));
	}

	private static string PredictNativeHotkey(BhUnitControlsView controls, HotkeyAbilityArgs args)
	{
		if (controls == null)
			return "nativePredict=controls-null";
		if (args == null)
			return "nativePredict=args-null";
		if (args.isEsc || args.isReturnDeselect)
			return "nativePredict=esc-or-deselect";

		var views = controls.abilities;
		var count = views != null ? views.Count : -1;
		var id = args.idButton;
		if (views == null)
			return "nativePredict=abilities-null count=-1 idButton=" + id;
		if (count <= id)
			return "nativePredict=index-oob count=" + count + " idButton=" + id + " (Count<=idButton)";

		BhUnitAbilityView atRaw = null;
		BhUnitAbilityView atShifted = null;
		try { if (id >= 0 && id < count) atRaw = views[id]; } catch { }
		try
		{
			var shifted = id - 1;
			if (shifted >= 0 && shifted < count)
				atShifted = views[shifted];
		}
		catch { }

		var rawEmb = HasUiWrapper(atRaw);
		var shiftedEmb = HasUiWrapper(atShifted);
		var nativeWouldClick = atRaw != null && rawEmb;
		return "nativePredict="
		       + (nativeWouldClick ? "would-belo" : "bail")
		       + " count=" + count
		       + " raw[" + id + "]=" + DescribeAbilityView(atRaw)
		       + " shifted[" + (id - 1) + "]=" + DescribeAbilityView(atShifted)
		       + " rawHasEmb=" + rawEmb
		       + " shiftedHasEmb=" + shiftedEmb;
	}

	private static void LogHud(string source, BhSelectedUnitHud hud, Unit unit, Exception ex, MethodBase method)
	{
		if (!ShouldLog() && ex == null)
			return;
		var sid = SafeSid(unit);
		var custom = Homm3CustomFactionRegistry.IsCustomUnitSid(sid);
		Info(
			source
			+ " method=" + (method?.Name ?? "?")
			+ " sid='" + (sid ?? "?") + "'"
			+ " custom=" + custom
			+ " unitNull=" + (unit == null)
			+ " controlsNull=" + (hud?.controlsView == null)
			+ (ex != null ? (" ex=" + ex.GetType().Name + " msg='" + Truncate(ex.Message, 180) + "'") : "")
			+ " " + SummarizeControls(hud?.controlsView));
	}

	private static void DumpControls(string source, BhUnitControlsView controls, string sidHint)
	{
		if (!ShouldLog())
			return;
		Info(source + " sidHint='" + (sidHint ?? "?") + "' " + SummarizeControls(controls) + " slots=[" + DescribeSlots(controls) + "]");
	}

	private static string SummarizeControls(BhUnitControlsView controls)
	{
		if (controls == null)
			return "controls=null";
		try
		{
			var views = controls.abilities;
			var active = 0;
			var emb = 0;
			var dxy = 0;
			var clickReady = 0;
			if (views != null)
			{
				for (var i = 0; i < views.Count; i++)
				{
					var view = views[i];
					if (view == null)
						continue;
					var go = view.gameObject;
					if (go != null && go.activeInHierarchy)
						active++;
					if (HasUiWrapper(view))
						emb++;
					if (HasActionWrapper(view))
						dxy++;
					if (LooksClickReady(view))
						clickReady++;
				}
			}
			return "views=" + (views != null ? views.Count : -1)
			       + " active=" + active
			       + " emb=" + emb
			       + " dxy=" + dxy
			       + " clickReady=" + clickReady
			       + " selected=" + DescribeAbilityView(GetSelectedAbilityView(controls));
		}
		catch (Exception ex)
		{
			return "controls=diag-failed:" + ex.GetType().Name;
		}
	}

	private static string DescribeSlots(BhUnitControlsView controls)
	{
		if (controls?.abilities == null)
			return "";
		var sb = new StringBuilder();
		try
		{
			var views = controls.abilities;
			for (var i = 0; i < views.Count; i++)
			{
				if (i > 0)
					sb.Append(" | ");
				sb.Append('#').Append(i).Append('=').Append(DescribeAbilityView(views[i]));
			}
		}
		catch (Exception ex)
		{
			sb.Append("diag-failed:").Append(ex.GetType().Name);
		}
		return sb.ToString();
	}

	private static string DescribeAbilityView(BhUnitAbilityView view)
	{
		if (view == null)
			return "null";
		try
		{
			var go = view.gameObject;
			return "{"
			       + "active=" + (go != null && go.activeInHierarchy)
			       + " emb=" + HasUiWrapper(view)
			       + " dxy=" + HasActionWrapper(view)
			       + " blocked=" + ReadBool(view, ClickBlockedHints)
			       + " enabled=" + ReadBool(view, ClickEnabledHints)
			       + " clickReady=" + LooksClickReady(view)
			       + "}";
		}
		catch
		{
			return "{diag-failed}";
		}
	}

	private static bool LooksClickReady(BhUnitAbilityView view)
	{
		if (view == null)
			return false;
		if (!HasUiWrapper(view) && !HasActionWrapper(view))
			return false;
		var blocked = ReadBool(view, ClickBlockedHints);
		if (blocked == true)
			return false;
		var enabled = ReadBool(view, ClickEnabledHints);
		if (enabled == false)
			return false;
		return true;
	}

	private static bool HasUiWrapper(BhUnitAbilityView view)
	{
		return ReadField(view, ref _abilityViewUiWrapperField, GameSymbols.SelectedUnitHud.AbilityViewWrapperFields) != null;
	}

	private static bool HasActionWrapper(BhUnitAbilityView view)
	{
		return ReadField(view, ref _abilityViewActionWrapperField, GameSymbols.SelectedUnitHud.AbilityViewAbilityFields) != null;
	}

	private static object ReadField(BhUnitAbilityView view, ref FieldInfo cached, string[] hints)
	{
		if (view == null)
			return null;
		try
		{
			cached ??= FindInstanceField(typeof(BhUnitAbilityView), hints);
			return cached?.GetValue(view);
		}
		catch
		{
			return null;
		}
	}

	private static bool? ReadBool(BhUnitAbilityView view, string[] hints)
	{
		if (view == null)
			return null;
		try
		{
			var field = FindInstanceField(typeof(BhUnitAbilityView), hints);
			if (field == null || field.FieldType != typeof(bool))
				return null;
			return (bool)field.GetValue(view);
		}
		catch
		{
			return null;
		}
	}

	private static FieldInfo FindInstanceField(Type type, string[] hints)
	{
		if (type == null || hints == null)
			return null;
		foreach (var hint in hints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var field = type.GetField(hint, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (field != null)
				return field;
		}
		return null;
	}

	private static BhUnitAbilityView GetSelectedAbilityView(BhUnitControlsView controls)
	{
		if (controls == null)
			return null;
		try
		{
			foreach (var hint in GameSymbols.SelectedUnitHud.ControlsSelectedViewFields)
			{
				var field = typeof(BhUnitControlsView).GetField(hint, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (field != null && typeof(BhUnitAbilityView).IsAssignableFrom(field.FieldType))
					return field.GetValue(controls) as BhUnitAbilityView;
			}
		}
		catch { }
		return null;
	}

	private static string SafeSid(Unit unit)
	{
		if (unit == null)
			return null;
		try
		{
			var transfer = TryGetFirstMember(unit, GameSymbols.BattleUi.UnitTransferFields);
			var sid = DeobfInteropCompat.GetUnitPortraitSid(transfer)
			          ?? TryGetStringMember(transfer, "configSid")
			          ?? TryGetStringMember(transfer, "sid")
			          ?? TryGetStringMember(unit, "sid")
			          ?? TryGetStringMember(unit, "configSid");
			if (!string.IsNullOrWhiteSpace(sid))
				return sid.Trim();
			var config = TryGetFirstMember(unit, GameSymbols.BattleUi.UnitConfigIdFields);
			sid = DeobfInteropCompat.GetConfigElementId(config)
			      ?? TryGetStringMember(config, "id")
			      ?? TryGetStringMember(config, "sid");
			return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
		}
		catch
		{
			return null;
		}
	}

	private static object TryGetFirstMember(object target, string[] fieldHints)
	{
		if (target == null || fieldHints == null)
			return null;
		var type = target.GetType();
		foreach (var hint in fieldHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			try
			{
				var field = type.GetField(hint, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (field != null)
				{
					var value = field.GetValue(target);
					if (value != null)
						return value;
				}
				var prop = type.GetProperty(hint, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (prop != null && prop.GetIndexParameters().Length == 0)
				{
					var value = prop.GetValue(target, null);
					if (value != null)
						return value;
				}
			}
			catch { }
		}
		return null;
	}

	private static string TryGetStringMember(object target, string name)
	{
		if (target == null || string.IsNullOrWhiteSpace(name))
			return null;
		try
		{
			var type = target.GetType();
			var field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (field != null && field.FieldType == typeof(string))
				return field.GetValue(target) as string;
			var prop = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (prop != null && prop.PropertyType == typeof(string) && prop.GetIndexParameters().Length == 0)
				return prop.GetValue(target, null) as string;
		}
		catch { }
		return null;
	}

	private static bool ShouldLog()
	{
		return _logged < LogCap;
	}

	private static void Info(string message)
	{
		if (!ShouldLog())
			return;
		_logged++;
		_log?.LogInfo(GrepKey + " " + message);
	}

	private static string Truncate(string value, int max)
	{
		if (string.IsNullOrEmpty(value) || value.Length <= max)
			return value ?? "";
		return value.Substring(0, max) + "…";
	}
}
