using System;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// <b>Deprecated — do not attach.</b> Map fog/visibility mirroring never worked in any shipped build.
/// HoMM3 units must use <see cref="Homm3NativeShellRendererTransplantSync"/> on the vanilla shell renderer instead.
/// This type is kept only for Il2Cpp registration and name-based enumeration of legacy prefabs (verified 2026-09-19: zero AddComponent sites).
/// </summary>
public sealed class Homm3NativeShellVisibilitySync : MonoBehaviour
{
	private const string VisualRootName = "homm3_map_visual";
	private static int _diagRemaining = 12;
	private static int _ancestryDiagRemaining = 16;

	private Renderer[] _nativeRenderers;
	private Renderer[] _visualRenderers;
	private int _lastState = -1;
	private bool _loggedAncestry;

	private void Awake()
	{
		Refresh();
	}

	private void LateUpdate()
	{
		if (_nativeRenderers == null || _nativeRenderers.Length == 0 || _visualRenderers == null || _visualRenderers.Length == 0)
			Refresh();
		LogAncestryOnce();

		for (var i = 0; _nativeRenderers != null && i < _nativeRenderers.Length; i++)
		{
			var r = _nativeRenderers[i];
			if (r && !r.forceRenderingOff)
				PrepareNativeDriverRenderer(r);
		}

		// Visibility is driven by the shell GameObject's active state: the engine's fog-of-war
		// system calls SetActive(true/false) on the map-object GameObject (which is this shell).
		// When no shell renderers remain (all stripped by Refresh), fall back to activeInHierarchy.
		var visible = AnyNativeRendererEnabled();
		if (!visible && (_nativeRenderers == null || _nativeRenderers.Length == 0))
			visible = gameObject && gameObject.activeInHierarchy;
		var state = visible ? 1 : 0;
		if (state == _lastState)
			return;
		_lastState = state;

		for (var i = 0; i < _visualRenderers.Length; i++)
		{
			var r = _visualRenderers[i];
			if (r)
				r.enabled = visible;
		}

		if (_diagRemaining > 0)
		{
			_diagRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3Import: native-shell visibility mirror root='"
				+ (gameObject ? gameObject.name : "?")
				+ "' nativeRenderers="
				+ (_nativeRenderers?.Length ?? 0)
				+ " visualRenderers="
				+ (_visualRenderers?.Length ?? 0)
				+ " visible="
				+ visible
				+ " activeInHierarchy="
				+ (gameObject ? gameObject.activeInHierarchy : false)
				+ ".");
		}
	}

	private void LogAncestryOnce()
	{
		if (_loggedAncestry || _ancestryDiagRemaining <= 0)
			return;
		_loggedAncestry = true;
		_ancestryDiagRemaining--;

		var msg = "Homm3Import: native-shell ancestry root='"
		          + (gameObject ? gameObject.name : "?")
		          + "'";
		var depth = 0;
		for (var t = transform; t != null && depth < 8; t = t.parent, depth++)
		{
			msg += " | p"
			       + depth
			       + "='"
			       + (t.name ?? "?")
			       + "' active="
			       + t.gameObject.activeInHierarchy
			       + " comps=["
			       + DescribeComponents(t.gameObject, 10)
			       + "]";
		}
		Plugin.LogSource?.LogInfo(msg);
	}

	private static string DescribeComponents(GameObject go, int max)
	{
		if (!go)
			return string.Empty;
		var comps = go.GetComponents<Component>();
		var s = string.Empty;
		for (var i = 0; comps != null && i < comps.Length && i < max; i++)
		{
			var c = comps[i];
			if (!c)
				continue;
			if (s.Length > 0)
				s += ",";
			s += c.GetType().Name;
		}
		if (comps != null && comps.Length > max)
			s += ",+" + (comps.Length - max);
		return s;
	}

	private void Refresh()
	{
		var visual = FindVisualRoot();
		var all = GetComponentsInChildren<Renderer>(true);
		var native = new System.Collections.Generic.List<Renderer>();
		var visualRs = new System.Collections.Generic.List<Renderer>();

		for (var i = 0; all != null && i < all.Length; i++)
		{
			var r = all[i];
			if (!r)
				continue;
			if (visual && IsUnder(r.transform, visual))
				visualRs.Add(r);
			else
			{
				// Keep the vanilla renderer as a fog-visibility driver: forceRenderingOff
				// prevents it from drawing, but enabled/disabled state is still toggled by
				// the engine's fog-of-war / map-visibility system.
				r.forceRenderingOff = true;
				r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
				r.receiveShadows = false;
				native.Add(r);
			}
		}

		_nativeRenderers = native.ToArray();
		_visualRenderers = visualRs.ToArray();
		_lastState = -1;
	}

	private Transform FindVisualRoot()
	{
		var trs = GetComponentsInChildren<Transform>(true);
		for (var i = 0; trs != null && i < trs.Length; i++)
		{
			var t = trs[i];
			if (t && string.Equals(t.name, VisualRootName, StringComparison.Ordinal))
				return t;
		}
		return null;
	}

	private static void PrepareNativeDriverRenderer(Renderer r)
	{
		if (!r)
			return;
		Homm3ImportVisuals.PrepareNativeShellDriverRenderer(r);
	}

	private bool AnyNativeRendererEnabled()
	{
		for (var i = 0; _nativeRenderers != null && i < _nativeRenderers.Length; i++)
		{
			var r = _nativeRenderers[i];
			if (r && r.enabled && r.gameObject.activeInHierarchy)
				return true;
		}
		return _nativeRenderers == null || _nativeRenderers.Length == 0;
	}

	private static bool IsUnder(Transform t, Transform parent)
	{
		if (!t || !parent)
			return false;
		for (var cur = t; cur != null; cur = cur.parent)
			if (cur == parent)
				return true;
		return false;
	}
}
