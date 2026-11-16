using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Makes the Tower Artificing picker modal over the adventure map, using the game's own input gates
/// (late-build mono decomp .tmp/town_pick/hex_src; native bodies checked on 26615913):
/// <list type="bullet">
/// <item>Hex.CursorRayCast.IsOverUI: WorldInput.OnInputProcess (hover cursor + click handlers), LeftClickAction /
/// RightClickAction, KeyboardHeroMoveInput, WorldCursorLogic*, interactable hover and CameraInput all skip while it is
/// true. Vanilla sets it from BhUiInteractElement.OnPointerEnter; the picker has none, so the map saw the mouse and
/// changed the cursor under the picker. Held true every frame while open.</item>
/// <item>InputReceiver.TryToPush: every Listen()ed action (EndTurn, Space use-object, Tab, hotkey windows, Esc menu,
/// quick save/load, numpad moves) fires through it. A prefix returning false drops them all. The picker itself polls
/// UnityEngine.Input, so its own Esc / clicks / wheel are unaffected.</item>
/// <item>Cursor: Homm3OwnedCityMapCursorSuppress.SetModalNormal shows the game's Normal cursor and drops every other
/// ECursor apply until release.</item>
/// </list>
/// The key block outlives Close by one frame, so the Esc / click that closes the picker cannot also open the Esc menu
/// or move the hero (the picker's Update and the game's input pass run in either order inside a frame).
/// </summary>
internal static class Homm3TowerArtificingPickerInputBlock
{
	private const string LogPrefix = "HoMM3 Tower Artificing picker input: ";
	private const string CursorOwner = "tower_artificing_picker";
	private const BindingFlags StaticFlags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
	private const BindingFlags InstanceFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

	private static bool _registrationAttempted;
	private static ManualLogSource _log;
	private static PropertyInfo _isOverUi;
	private static int _pushPatches;
	private static bool _active;
	private static int _blockUntilFrame = -1;
	private static bool _loggedOverUiFailure;

	internal static void TryRegister(Harmony harmony, Assembly hexAssembly, ManualLogSource log)
	{
		if (_registrationAttempted || harmony == null || hexAssembly == null)
			return;
		_registrationAttempted = true;
		_log = log;
		var parts = new List<string>();

		try
		{
			var rayCast = ResolveType(hexAssembly, GameSymbols.TowerArtificing.CursorRayCastTypeHints, "cursorRayCast");
			foreach (var name in GameSymbols.TowerArtificing.CursorRayCastIsOverUiMembers)
			{
				var property = rayCast.GetProperty(name, StaticFlags);
				if (property != null && property.PropertyType == typeof(bool) && property.CanRead && property.CanWrite)
				{
					_isOverUi = property;
					break;
				}
			}
			if (_isOverUi == null)
				throw new MissingMemberException(rayCast.FullName + " has no static bool IsOverUI accessor");
			parts.Add("isOverUI=" + rayCast.Name + "." + _isOverUi.Name);
		}
		catch (Exception ex)
		{
			parts.Add("isOverUI=MISSING(" + ex.GetBaseException().Message + ")");
		}

		try
		{
			var receiver = ResolveType(hexAssembly, GameSymbols.TowerArtificing.InputReceiverTypeHints, "inputReceiver");
			var targets = new List<MethodInfo>();
			MethodInfo baseMethod = null;
			foreach (var name in GameSymbols.TowerArtificing.InputReceiverTryToPushHints)
			{
				baseMethod = FindTryToPush(receiver, name);
				if (baseMethod != null)
					break;
			}
			if (baseMethod == null)
				throw new MissingMethodException(receiver.FullName + " has no bool TryToPush(InputAction)");
			targets.Add(baseMethod);
			var inputActionType = baseMethod.GetParameters()[0].ParameterType;

			// Native overrides are separate function bodies; patch each one declared by a subclass.
			Type[] types;
			try { types = hexAssembly.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types; }
			foreach (var type in types)
			{
				if (type == null || type == receiver || !receiver.IsAssignableFrom(type))
					continue;
				foreach (var method in type.GetMethods(InstanceFlags))
				{
					if (method.ReturnType != typeof(bool) || !method.IsVirtual)
						continue;
					var ps = method.GetParameters();
					if (ps.Length == 1 && ps[0].ParameterType == inputActionType)
						targets.Add(method);
				}
			}

			foreach (var target in targets)
			{
				Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3TowerArtificingPickerInputBlock), target, nameof(PrefixTryToPush), null);
				_pushPatches++;
			}
			parts.Add("tryToPush=" + _pushPatches + " (" + receiver.Name + "." + baseMethod.Name + ")");
		}
		catch (Exception ex)
		{
			parts.Add("tryToPush=MISSING(" + ex.GetBaseException().Message + ") patched=" + _pushPatches);
		}

		_log?.LogInfo(LogPrefix + "registered " + string.Join(" ", parts));
	}

	/// <summary>Picker opened: raise the game's input gates and show the Normal cursor.</summary>
	internal static void Begin()
	{
		_active = true;
		SetOverUi(true);
		if (!Homm3OwnedCityMapCursorSuppress.SetModalNormal(CursorOwner, true, out var detail))
			_log?.LogWarning(LogPrefix + "cursor not overridden: " + detail);
	}

	/// <summary>Every frame while open: vanilla BhUiInteractElement.OnPointerExit under the picker can clear the flag.</summary>
	internal static void Hold()
	{
		if (_active)
			SetOverUi(true);
	}

	/// <summary>Picker closed: release the gates; keys and clicks stay blocked through the next frame.</summary>
	internal static void End()
	{
		if (!_active)
			return;
		_active = false;
		_blockUntilFrame = Time.frameCount + 1;
		SetOverUi(false);
		Homm3OwnedCityMapCursorSuppress.SetModalNormal(CursorOwner, false, out _);
	}

	private static bool Blocking => _active || Time.frameCount <= _blockUntilFrame;

	private static bool PrefixTryToPush(ref bool __result)
	{
		if (!Blocking)
			return true;
		__result = false;
		return false;
	}

	private static void SetOverUi(bool value)
	{
		if (_isOverUi == null)
			return;
		try
		{
			if ((bool)_isOverUi.GetValue(null) != value)
				_isOverUi.SetValue(null, value);
		}
		catch (Exception ex)
		{
			if (_loggedOverUiFailure)
				return;
			_loggedOverUiFailure = true;
			_log?.LogWarning(LogPrefix + "IsOverUI write failed: " + ex.GetBaseException().Message);
		}
	}

	private static MethodInfo FindTryToPush(Type receiver, string name)
	{
		foreach (var method in receiver.GetMethods(InstanceFlags))
		{
			if (method.Name != name || method.ReturnType != typeof(bool))
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 1 && string.Equals(ps[0].ParameterType.FullName, "Hex.InputSys.InputAction", StringComparison.Ordinal))
				return method;
		}
		return null;
	}

	private static Type ResolveType(Assembly assembly, string[] hints, string what)
	{
		foreach (var hint in hints)
		{
			var type = assembly.GetType(hint);
			if (type != null)
				return type;
		}
		throw new TypeLoadException(what + " type not found from hints [" + string.Join(",", hints) + "]");
	}
}
