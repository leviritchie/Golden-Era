using System;
using UnityEngine;

namespace OfflineUnlockMod;

public sealed class Homm3MapSquadRuntimeAttach : MonoBehaviour
{
	private static int _diagRemaining = 40;
	private static int _bridgeFailureDiagRemaining = 4;
	private bool _attached;
	private bool _disabledAfterBridgeFailure;
	private int _frames;

	private void Awake()
	{
		SafeTryAttach("awake");
	}

	private void OnEnable()
	{
		_attached = false;
		_disabledAfterBridgeFailure = false;
		_frames = 0;
		SafeTryAttach("enable");
	}

	private void LateUpdate()
	{
		if (_attached || _disabledAfterBridgeFailure)
			return;
		_frames++;
		SafeTryAttach("late" + _frames);
	}

	private void SafeTryAttach(string source)
	{
		try
		{
			TryAttach(source);
		}
		catch (Exception ex)
		{
			_disabledAfterBridgeFailure = true;
			enabled = false;
			if (_bridgeFailureDiagRemaining > 0)
			{
				_bridgeFailureDiagRemaining--;
				Plugin.LogSource?.LogWarning(
					"Homm3Import runtime squad attach disabled after IL2CPP bridge failure: "
					+ ex.GetType().Name
					+ ": "
					+ ex.Message);
			}
		}
	}

	private void TryAttach(string source)
	{
		var squadRoot = FindRuntimeSquadRoot();
		if (!squadRoot)
			return;

		var mirror = Homm3MapSquadVisualControllerHook.GetComponentSafe<Homm3MapSquadVisualMirror>(squadRoot.gameObject);
		if (!mirror)
			mirror = Homm3MapSquadVisualControllerHook.AddComponentSafe<Homm3MapSquadVisualMirror>(squadRoot.gameObject);
		mirror.Configure();
		_attached = true;

		if (_diagRemaining > 0)
		{
			_diagRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3Import runtime squad attach: source="
				+ source
				+ " shell='"
				+ (gameObject ? gameObject.name : "?")
				+ "' attachedTo='"
				+ (squadRoot.name ?? "?")
				+ "' path="
				+ BuildAncestry()
				+ ".");
		}
	}

	private Transform FindRuntimeSquadRoot()
	{
		var parent = transform.parent;
		if (!parent)
			return null;

		for (var t = parent; t != null; t = t.parent)
		{
			var n = t.name ?? string.Empty;
			if (n.StartsWith("squad ", StringComparison.OrdinalIgnoreCase))
				return t;
		}

		return parent;
	}

	private string BuildAncestry()
	{
		var s = string.Empty;
		var depth = 0;
		for (var t = transform; t != null && depth < 6; t = t.parent, depth++)
		{
			if (s.Length > 0)
				s += " <- ";
			s += t.name ?? "?";
		}
		return s;
	}
}
