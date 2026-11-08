using System;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Applies <see cref="EsquirePikemanVisuals.ApplyPendingHarmonyPrefix"/> on a later <c>Update</c> so we are not installing
/// the <c>ResManager</c> prefix on the same call stack as <c>SceneManager.LoadScene</c> / <c>LoadSceneAsync</c> (which can
/// overlap <c>Session.OnScenesLoaded</c> and break in-session collections).
/// </summary>
public sealed class EsquirePikemanResManagerAtFrameReg : MonoBehaviour
{
	public int TargetFrame = -1;

	private void Update()
	{
		if (TargetFrame < 0)
		{
			Destroy(gameObject);
			return;
		}

		int fc;
		try
		{
			fc = Time.frameCount;
		}
		catch
		{
			fc = int.MaxValue;
		}

		if (fc < TargetFrame)
			return;
		try
		{
			EsquirePikemanVisuals.ApplyPendingHarmonyPrefix(Plugin.LogSource, fc);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("EsquirePikeman: at-frame ResManager patch failed: " + ex);
		}
		finally
		{
			Destroy(gameObject);
		}
	}
}

internal static class EsquirePikemanResManagerAtFrame
{
	private static bool _registeredType;

	internal static void ScheduleFromNow(int framesFromNow, ManualLogSource log)
	{
		if (framesFromNow <= 0)
		{
			var f0 = -1;
			try
			{
				f0 = Time.frameCount;
			}
			catch
			{
			}
			EsquirePikemanVisuals.ApplyPendingHarmonyPrefix(log, f0);
			return;
		}

		int now;
		try
		{
			now = Time.frameCount;
		}
		catch
		{
			EsquirePikemanVisuals.ApplyPendingHarmonyPrefix(log, -1);
			return;
		}

		var target = now + Math.Max(0, framesFromNow);
		if (now >= target)
		{
			EsquirePikemanVisuals.ApplyPendingHarmonyPrefix(log, now);
			return;
		}

		try
		{
			if (!_registeredType)
			{
				ClassInjector.RegisterTypeInIl2Cpp<EsquirePikemanResManagerAtFrameReg>();
				_registeredType = true;
			}

			var go = new GameObject("EsquirePikemanResManagerAtFrame");
			go.hideFlags = HideFlags.HideAndDontSave;
			UnityEngine.Object.DontDestroyOnLoad(go);
			var reg = go.AddComponent<EsquirePikemanResManagerAtFrameReg>();
			reg.TargetFrame = target;
			log?.LogInfo(
				"EsquirePikeman: will apply ResManager prefix at end of frame "
				+ target
				+ " (esquirePikemanDeferResManagerOffsetFrames="
				+ framesFromNow
				+ ", away from LoadScene/Session).");
		}
		catch (Exception ex)
		{
			log?.LogError("EsquirePikeman: at-frame scheduling failed; applying ResManager prefix now: " + ex);
			EsquirePikemanVisuals.ApplyPendingHarmonyPrefix(log, -1);
		}
	}

	internal static void Cancel()
	{
		try
		{
			var go = GameObject.Find("EsquirePikemanResManagerAtFrame");
			if (go)
				UnityEngine.Object.Destroy(go);
		}
		catch
		{
		}
	}
}
