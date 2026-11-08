using System;
using System.Collections.Generic;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Runs preview model replacement on <c>LateUpdate</c> (not <c>Update</c>) so it runs after vanilla
/// <c>BhUnitPreviews</c> / <c>clb</c> setup in the same frame, reducing races where <c>Model</c> is reset after our work.
/// </summary>
internal static class Homm3PreviewApplyNextFrame
{
	private static bool _registered;
	private static Homm3PreviewApplyBehaviour _behaviour;
	private static readonly Queue<Action> Pending = new();

	internal static void Ensure(ManualLogSource log)
	{
		if (_behaviour != null)
			return;
		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3PreviewApplyBehaviour>();
				_registered = true;
			}
			var go = new GameObject("Homm3PreviewApplyNextFrame");
			go.hideFlags = HideFlags.HideAndDontSave;
			_behaviour = go.AddComponent<Homm3PreviewApplyBehaviour>();
			if (_behaviour == null)
			{
				log?.LogWarning("Homm3PreviewApplyNextFrame: AddComponent returned null; preview swap runs synchronously.");
				return;
			}
			UnityEngine.Object.DontDestroyOnLoad(go);
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3PreviewApplyNextFrame: could not create runner: " + ex);
		}
	}

	internal static void QueueOrRun(ManualLogSource log, Action work)
	{
		Ensure(log);
		if (_behaviour == null || work == null)
		{
			work?.Invoke();
			return;
		}
		Pending.Enqueue(work);
	}

	internal static void QueueRequired(ManualLogSource log, Action work, string owner)
	{
		Ensure(log);
		if (work == null)
			throw new ArgumentNullException(nameof(work));
		if (_behaviour == null)
			throw new InvalidOperationException((owner ?? "Deferred work")
				+ " requires the LateUpdate runner; synchronous fallback is forbidden.");
		Pending.Enqueue(work);
	}
	/// <summary>
	/// Drain only work that was already queued when this LateUpdate began.
	/// Work enqueued from inside a drained callback must wait until the next LateUpdate —
	/// otherwise a wait/retry loop (e.g. factory city presentation readiness) can spin
	/// forever in one frame and freeze the game before native Main can bind.
	/// </summary>
	internal static void DrainPending()
	{
		var scheduled = Pending.Count;
		for (var i = 0; i < scheduled; i++)
		{
			if (Pending.Count == 0)
				break;
			Pending.Dequeue()?.Invoke();
		}
	}
}

/// <summary>Must be <c>public</c> for Il2CppInterop <see cref="ClassInjector"/> registration.</summary>
public sealed class Homm3PreviewApplyBehaviour : MonoBehaviour
{
	private void LateUpdate()
	{
		Homm3PreviewApplyNextFrame.DrainPending();
		Homm3HireUnitPortraitAnimator.TickAll();
	}
}
