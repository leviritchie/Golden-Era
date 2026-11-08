using System;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

/// <summary>
/// Defers the Esquire <c>ResManager</c> prefix until a few <c>SceneManager.LoadScene</c> calls. Uses only Harmony
/// (no <c>ClassInjector</c> or Il2Cpp <c>GameObject</c> during BepInEx <c>Plugin.Load</c>).
/// Il2CPP <c>SceneManager.sceneLoaded</c> is not C#-subscribable; event wiring is not delegate-compatible in interop.
/// </summary>
internal static class EsquirePikemanSceneDefer
{
	private static Harmony _sceneHarm;
	private static bool _patched;
	private static int _skipsLeft;

	/// <summary>After <paramref name="skipLoadEvents"/> <c>LoadScene</c> <em>completions</em> (any overload), apply the ResManager prefix.</summary>
	internal static void Schedule(int skipLoadEvents, ManualLogSource log)
	{
		if (_patched)
			return;
		_skipsLeft = Mathf.Max(0, skipLoadEvents);
		_sceneHarm = new Harmony(Plugin.PluginGuid + ".esquireSceneLoad");
		var t = typeof(SceneManager);
		var loadMethods = t
			.GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly)
			.Where(
				m => m.Name == "LoadScene"
				|| m.Name == "LoadSceneAsync")
			.ToList();
		if (loadMethods.Count == 0)
		{
			log?.LogError(
				"EsquirePikeman: no public static SceneManager LoadScene/LoadSceneAsync; cannot defer by load calls. Applying ResManager prefix now.");
			_sceneHarm = null;
			EsquirePikemanVisuals.ApplyPendingHarmonyPrefix(log, -1);
			return;
		}

		var failed = 0;
		var hook = new HarmonyMethod(typeof(EsquirePikemanSceneDefer), nameof(PostAfterLoadScene));
		foreach (var m in loadMethods)
		{
			try
			{
				_sceneHarm.Patch(m, postfix: hook);
			}
			catch (Exception ex)
			{
				failed++;
				log?.LogWarning("EsquirePikeman: could not Harmony-postfix " + m + " : " + ex.Message);
			}
		}

		if (failed == loadMethods.Count)
		{
			log?.LogError("EsquirePikeman: all LoadScene postfix patches failed. Applying ResManager prefix now.");
			_sceneHarm?.UnpatchSelf();
			_sceneHarm = null;
			EsquirePikemanVisuals.ApplyPendingHarmonyPrefix(log, -1);
			return;
		}

		_patched = true;
		var sceneName = "(unknown)";
		try
		{
			var s = SceneManager.GetActiveScene();
			if (s.IsValid() && s.isLoaded)
			{
				sceneName = s.name;
			}
		}
		catch
		{
		}

		Diag("SceneDeferSubscribed", "skips=" + _skipsLeft + " active=" + sceneName, log);
		log?.LogInfo(
			"EsquirePikeman: will apply ResManager prefix after "
			+ _skipsLeft
			+ " more SceneManager.LoadScene call(s) (esquirePikemanDeferBySceneLoad=true: Harmony on LoadScene, no early ClassInjector/GameObject).");
	}

	internal static void Cancel()
	{
		_sceneHarm?.UnpatchSelf();
		_sceneHarm = null;
		_patched = false;
		_skipsLeft = 0;
	}

	/// <summary>
	/// Runs after <c>LoadScene</c> / <c>LoadSceneAsync</c> returns. For <c>LoadSceneAsync</c> this is when the
	/// async load is <em>started</em>, not when the scene has finished; good enough to leave chain load behind.
	/// </summary>
	private static void PostAfterLoadScene()
	{
		if (EsquirePikemanVisuals.IsResManagerPrefixPatched)
		{
			Unhook();
			return;
		}

		if (!EsquirePikemanVisuals.HasPendingResManagerPrefix)
		{
			Unhook();
			return;
		}

		if (_skipsLeft > 0)
		{
			_skipsLeft--;
			var sn = "unknown";
			try
			{
				sn = SceneManager.GetActiveScene().name;
			}
			catch
			{
			}
			Diag("SceneDeferSkip", "remainingSkips=" + _skipsLeft + " active=" + sn, null);
			return;
		}

		var fc = -1;
		try
		{
			fc = Time.frameCount;
		}
		catch
		{
		}

		var sn2 = "unknown";
		try
		{
			sn2 = SceneManager.GetActiveScene().name;
		}
		catch
		{
		}
		Diag("SceneDeferApply", "name=" + sn2 + " frame=" + fc, null);
		Unhook();
		// Do not call Apply in this postfix: same stack as LoadScene/LoadSceneAsync can run during Session/OnScenesLoaded and break in-session state.
		var off = EsquirePikemanVisuals.DeferredResManagerOffsetFrames;
		EsquirePikemanResManagerAtFrame.ScheduleFromNow(off, Plugin.LogSource);
	}

	private static void Unhook() => Cancel();

	private static void Diag(string @event, string detail, ManualLogSource log) =>
		EsquirePikemanVisuals.DiagForSceneDefer(@event, detail, log);
}
