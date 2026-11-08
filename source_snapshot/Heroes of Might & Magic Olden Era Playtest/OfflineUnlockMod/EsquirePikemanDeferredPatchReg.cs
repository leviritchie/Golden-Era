using System;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>Applies the Esquire <c>ResManager</c> Harmony prefix after <see cref="MinFrames"/> so the init scene is not affected at plugin load.</summary>
public sealed class EsquirePikemanDeferredPatchReg : MonoBehaviour
{
	public int MinFrames = 30;

	private void Update()
	{
		if (Time.frameCount < MinFrames)
			return;
		try
		{
			var fc = Time.frameCount;
			EsquirePikemanVisuals.ApplyPendingHarmonyPrefix(Plugin.LogSource, fc);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("EsquirePikeman: deferred patch tick failed: " + ex);
		}
		finally
		{
			Destroy(gameObject);
		}
	}
}

/// <summary>Registers the Il2Cpp <see cref="EsquirePikemanDeferredPatchReg"/> type once and spawns a hidden host.</summary>
internal static class EsquirePikemanDeferredScheduler
{
	private static bool _registeredType;

	internal static void Schedule(int minFrames, ManualLogSource log)
	{
		try
		{
			if (!_registeredType)
			{
				ClassInjector.RegisterTypeInIl2Cpp<EsquirePikemanDeferredPatchReg>();
				_registeredType = true;
			}

			var go = new GameObject("EsquirePikemanDeferredPatch");
			go.hideFlags = HideFlags.HideAndDontSave;
			UnityEngine.Object.DontDestroyOnLoad(go);
			var reg = go.AddComponent<EsquirePikemanDeferredPatchReg>();
			reg.MinFrames = Math.Max(1, minFrames);
			log?.LogInfo(
				"EsquirePikeman: scheduled ResManager Harmony prefix after frame "
				+ reg.MinFrames
				+ " (esquirePikemanDeferPatch=true).");
		}
		catch (Exception ex)
		{
			log?.LogError(
				"EsquirePikeman: frame-based deferred scheduling failed (ClassInjector/GameObject); trying scene-load defer instead of immediate patch: "
				+ ex);
			EsquirePikemanSceneDefer.Schedule(0, log);
		}
	}
}
