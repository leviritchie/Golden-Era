using System;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Time-sampled facing diagnostic for the owned-skinned battle lane. Logs the replacement
/// root's rotation over ~3 seconds plus the visual roots of nearby vanilla battle units in
/// the same battle, so the game's own facing convention (the ecz orientation transform
/// values it writes) can be read directly. Diagnostic-only; gated by
/// <c>homm3_battle_visual_diag.flag</c> and capped at a few attachments.
/// </summary>
public sealed class Homm3SkinnedFacingDiag : MonoBehaviour
{
	private const int MaxSamples = 32;
	private const float SampleIntervalSeconds = 0.25f;

	private static bool _typeRegistered;
	private static int _attachedCount;

	private ManualLogSource _log;
	private Transform _battleRoot;
	private float _nextSampleAt;
	private int _samplesTaken;
	private int _rotationChangeLogs;
	private Vector3 _lastLoggedEuler;

	public Homm3SkinnedFacingDiag(IntPtr ptr) : base(ptr) { }

	internal static void TryAttach(GameObject instance, ManualLogSource log)
	{
		try
		{
			if (!instance || !instance)
				return;
			if (!Homm3DiagnosticFlags.IsEnabled("homm3_battle_visual_diag.flag"))
				return;
			if (_attachedCount >= 2)
				return;
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3SkinnedFacingDiag>();
				_typeRegistered = true;
			}

			_attachedCount++;
			var diag = instance.AddComponent<Homm3SkinnedFacingDiag>();
			diag._log = log;
			log?.LogInfo("Homm3 skinned facing diag: attached to '" + (instance.name ?? "?") + "'.");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 skinned facing diag: attach failed: " + ex.Message);
		}
	}

	private void Start()
	{
		if (_log == null)
			return;
		// instance -> 'Unit' container -> battle scene root (walk to the top).
		var current = transform.parent;
		var top = transform;
		while (current != null)
		{
			top = current;
			current = current.parent;
		}
		_battleRoot = top;
		_nextSampleAt = Time.unscaledTime + 0.5f;
		_lastLoggedEuler = transform.eulerAngles;
		_log.LogInfo(
			"Homm3 skinned facing diag: battleRoot='" + (_battleRoot ? _battleRoot.name ?? "?" : "?")
			+ "' childCount=" + (_battleRoot ? _battleRoot.childCount : -1)
			+ " selfPath='" + BuildPath(transform, 4) + "'.");
		LogAncestors();
	}

	private void LogAncestors()
	{
		var sb = new System.Text.StringBuilder(256);
		sb.Append("Homm3 skinned facing diag: ancestors");
		var cur = transform;
		for (var i = 0; i < 4 && cur != null; i++)
		{
			sb.Append(" | '").Append(cur.name ?? "?").Append("' localEuler=")
				.Append(Format(cur.localEulerAngles))
				.Append(" worldEuler=")
				.Append(Format(cur.eulerAngles))
				.Append(" localScl=")
				.Append(cur.localScale.ToString("F3"))
				.Append(" pos=")
				.Append(cur.position.ToString("F3"));
			cur = cur.parent;
		}
		_log.LogInfo(sb.ToString());
	}

	private static string BuildPath(Transform t, int maxDepth)
	{
		var parts = new string[maxDepth];
		var n = 0;
		for (var cur = t; cur != null && n < maxDepth; cur = cur.parent)
			parts[n++] = cur.name ?? "?";
		System.Array.Reverse(parts, 0, n);
		return string.Join("/", parts, 0, n);
	}

	private void LateUpdate()
	{
		if (_log == null || _samplesTaken >= MaxSamples)
			return;
		var now = Time.unscaledTime;

		var euler = transform.eulerAngles;
		if (Vector3.Distance(euler, _lastLoggedEuler) > 1f && _rotationChangeLogs < 6)
		{
			_rotationChangeLogs++;
			_log.LogInfo(
				"Homm3 skinned facing diag: self rotation CHANGED to euler=" + Format(euler)
				+ " pos=" + transform.position.ToString("F3")
				+ " t=" + now.ToString("F2") + ".");
			_lastLoggedEuler = euler;
		}

		if (now < _nextSampleAt)
			return;
		_nextSampleAt = now + SampleIntervalSeconds;
		_samplesTaken++;

		_log.LogInfo(
			"Homm3 skinned facing diag: sample=" + _samplesTaken
			+ " self euler=" + Format(euler)
			+ " pos=" + transform.position.ToString("F3")
			+ " parent='" + (transform.parent ? transform.parent.name ?? "?" : "?") + "'.");

		if (_battleRoot == null)
			return;
		var meshForwardLocal = Vector3.forward;
		var marker = transform.Find(Homm3ImportVisuals.SkinnedBattleLaneMarkerName);
		if (marker && marker)
			meshForwardLocal = marker.localRotation * Vector3.forward;
		var meshForward = transform.rotation * meshForwardLocal;
		meshForward.y = 0f;
		meshForward.Normalize();
		var scanned = 0;
		var validTargets = 0;
		for (var i = 0; i < _battleRoot.childCount; i++)
		{
			var container = _battleRoot.GetChild(i);
			if (container == null)
				continue;
			if (string.Equals(container.name, "ValidTarget(Clone)", StringComparison.Ordinal)
			    || (container.name ?? string.Empty).StartsWith("ValidTarget", StringComparison.Ordinal))
			{
				validTargets++;
				continue;
			}
			var visual = FindVisualRoot(container);
			if (visual == null && scanned >= 12)
				continue;
			scanned++;
			if (scanned > 12)
				continue;
			var toContainer = container.position - transform.position;
			toContainer.y = 0f;
			var angleTo = meshForward.sqrMagnitude > 1e-6f && toContainer.sqrMagnitude > 1e-6f
				? Vector3.SignedAngle(meshForward, toContainer.normalized, Vector3.up).ToString("0.#")
				: "?";
			_log.LogInfo(
				"Homm3 skinned facing diag: container '" + (container.name ?? "?") + "'"
				+ " euler=" + Format(container.eulerAngles)
				+ " pos=" + container.position.ToString("F3")
				+ " localScl=" + container.localScale.ToString("F3")
				+ " renderer=" + (visual ? visual.name ?? "?" : "none")
				+ " angleFromMeshFwd=" + angleTo + ".");
		}
		if (validTargets > 0 && _samplesTaken <= 2)
			_log.LogInfo("Homm3 skinned facing diag: skipped " + validTargets + " ValidTarget prop(s).");
	}

	private static Transform FindVisualRoot(Transform container)
	{
		if (container == null)
			return null;
		if (HasRenderer(container))
			return container;
		for (var i = 0; i < container.childCount; i++)
		{
			var child = container.GetChild(i);
			if (HasRenderer(child))
				return child;
		}
		return null;
	}

	private static bool HasRenderer(Transform t)
	{
		return t.GetComponent<Renderer>() != null
		       || t.GetComponentInChildren<Renderer>(true) != null;
	}

	private static string Format(Vector3 euler)
	{
		return "(" + euler.x.ToString("0.#") + ", " + euler.y.ToString("0.#") + ", " + euler.z.ToString("0.#") + ")";
	}
}
