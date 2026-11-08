using System;
using System.Collections.Generic;
using Il2CppInterop.Runtime;
using UnityEngine;

namespace OfflineUnlockMod;

public sealed class Homm3MapSquadVisualMirror : MonoBehaviour
{
	private const string VisualRootName = "homm3_map_visual";
	private static int _diagRemaining = 32;

	private Renderer[] _visualRenderers;
	private Transform _visualRoot;
	private int _lastState = -1;

	private void Awake()
	{
		Refresh();
		Apply("awake");
	}

	private void OnEnable()
	{
		Apply("enable");
	}

	private void OnDisable()
	{
		SetVisualRenderers(false, "disable");
	}

	private void LateUpdate()
	{
		Apply("late");
	}

	internal void Configure()
	{
		Refresh();
		Apply("configure");
	}

	private void Apply(string source)
	{
		if (_visualRenderers == null || _visualRenderers.Length == 0 || !_visualRoot)
			Refresh();
		var visible = gameObject && gameObject.activeInHierarchy;
		SetVisualRenderers(visible, source);
	}

	private void SetVisualRenderers(bool visible, string source)
	{
		var state = visible ? 1 : 0;
		if (state == _lastState)
			return;
		_lastState = state;

		for (var i = 0; _visualRenderers != null && i < _visualRenderers.Length; i++)
		{
			var r = _visualRenderers[i];
			if (!r)
				continue;
			r.enabled = visible;
			r.forceRenderingOff = !visible;
		}

		if (_diagRemaining > 0)
		{
			_diagRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3Import map squad visual mirror: source="
				+ source
				+ " root='"
				+ (gameObject ? gameObject.name : "?")
				+ "' activeSelf="
				+ (gameObject ? gameObject.activeSelf : false)
				+ " activeInHierarchy="
				+ (gameObject ? gameObject.activeInHierarchy : false)
				+ " appliedVisible="
				+ visible
				+ " visualRenderers="
				+ (_visualRenderers?.Length ?? 0)
				+ ".");
		}
	}

	private void Refresh()
	{
		_visualRoot = FindVisualRoot();
		_visualRenderers = _visualRoot
			? CollectRenderers(_visualRoot)
			: Array.Empty<Renderer>();
		_lastState = -1;
		DisableLegacyShellMirrors();
	}

	private Transform FindVisualRoot()
	{
		return FindDescendant(transform, VisualRootName);
	}

	private static Transform FindDescendant(Transform root, string name)
	{
		if (!root)
			return null;
		if (string.Equals(root.name, name, StringComparison.Ordinal))
			return root;
		for (var i = 0; i < root.childCount; i++)
		{
			var found = FindDescendant(root.GetChild(i), name);
			if (found)
				return found;
		}
		return null;
	}

	private static Renderer[] CollectRenderers(Transform root)
	{
		var result = new List<Renderer>();
		CollectRenderers(root, result);
		return result.ToArray();
	}

	private static void CollectRenderers(Transform root, List<Renderer> result)
	{
		if (!root)
			return;
		var renderer = root.GetComponent(Il2CppType.Of<Renderer>())?.TryCast<Renderer>();
		if (renderer)
			result.Add(renderer);
		for (var i = 0; i < root.childCount; i++)
			CollectRenderers(root.GetChild(i), result);
	}

	private void DisableLegacyShellMirrors()
	{
		var oldShellMirrors = CollectShellVisibilitySyncs(transform);
		for (var i = 0; oldShellMirrors != null && i < oldShellMirrors.Length; i++)
		{
			var m = oldShellMirrors[i];
			if (m)
				m.enabled = false;
		}
	}

	private static Behaviour[] CollectShellVisibilitySyncs(Transform root)
	{
		var result = new List<Behaviour>();
		CollectShellVisibilitySyncs(root, result);
		return result.ToArray();
	}

	private static void CollectShellVisibilitySyncs(Transform root, List<Behaviour> result)
	{
		if (!root)
			return;
		var components = root.GetComponents(Il2CppType.Of<Component>());
		for (var i = 0; components != null && i < components.Length; i++)
		{
			var component = components[i];
			if (!component || !string.Equals(component.GetType().Name, "Homm3NativeShellVisibilitySync", StringComparison.Ordinal))
				continue;
			var behaviour = component.TryCast<Behaviour>();
			if (behaviour)
				result.Add(behaviour);
		}
		for (var i = 0; i < root.childCount; i++)
			CollectShellVisibilitySyncs(root.GetChild(i), result);
	}
}
