using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.GameScenes;
using Hex.Session.City;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using UnityEngine.Bindings;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Owned city-world load path shared by custom factions that present HotA art on cityFactory
/// (see GameSymbols.FactoryCityScene.OwnedCityWorldFactionSids): additive LoadScene of authored
/// cityHuman2, move those live roots into a Factory-owned cityFactory Scene container, bind Di2,
/// allow native Void(EScene).
/// Do not Instantiate scene roots (that skips LoadScene lifecycle and black-screens).
/// Ownership of the scene name is Core/manifest citySceneName=cityFactory — not a Harmony
/// rewrite of ObjCityConfig.get_sceneName (IL2CPP field accessor; live-negative).
/// Agent warning: do not port or cite failed playtest city_hive helpers under
/// _decompiled_shipped as load-path evidence. Vanilla Hive (demon/cityDemon) is unrelated.
/// Factory presentation is user-visible proven; peer factions on this path still need their own proof.
/// </summary>
internal static class Homm3FactoryCitySceneRegistrar
{
	private const string LogPrefix = "HoMM3 factory city scene: ";

	private static bool _registered;
	private static ManualLogSource _log;
	private static bool _enabled;
	private static bool _loggedParseMap;
	private static bool _loggedWorldOwned;
	private static bool _loggedRegister;
	private static bool _cloneFailed;
	private static bool _factoryCityLoadRequested;
	private static bool _factoryCitySessionInjected;
	private static bool _factoryPresentationReconcileQueued;
	private static bool _factoryPresentationReconcileRunning;
	/// <summary>
	/// Set when QueueFactoryPresentationReconcile is requested while a reconcile is already
	/// queued/running. Without this, native building-mutation posts during the first readiness
	/// wait are dropped and Main never re-triggers Apply (black CityCamera + visible Temple donors).
	/// </summary>
	private static bool _factoryPresentationReconcilePending;
	private static bool _presentationFailed;
	private static string _lastPresentationWaitReason;
	/// <summary>
	/// After first ready apply, keep reconciling briefly so late-activating BhBuilding variants
	/// get HotA art instead of staying blank under HideDonorPresentation.
	/// </summary>
	private static int _presentationSettleFramesLeft;
	private static bool _presentationSettleArmed;
	private static Scene _factoryScene;
	private static readonly List<GameObject> _ownedRoots = new();
	private static Type _sessionEntryType;
	private static Type _sessionEntryArrayType;
	private static MethodInfo _sessionEntryEsceneGetter;
	private static MethodBase _sessionEntrySceneSetter;

	internal static bool IsRegistered => _registered;

	/// <summary>
	/// True when a custom faction is presenting the owned cityFactory Unity world (not Route A posters).
	/// Poster-path donor-renderer suppression must not run in this mode (live-positive black screen).
	/// </summary>
	internal static bool OwnsActiveFactoryCityWorld(string fraction)
	{
		if (!_enabled || !_registered)
			return false;
		if (!GameSymbols.FactoryCityScene.IsOwnedCityWorldFaction(fraction))
			return false;
		return IsOwnedCityWorldSceneActive();
	}

	/// <summary>
	/// True when the owned cityFactory Unity scene is the active scene (any owned custom faction).
	/// Used by map-city-interact cursor suppress while sessionWorld remains loaded under town.
	/// </summary>
	internal static bool IsOwnedCityWorldSceneActive()
	{
		if (!_enabled || !_registered)
			return false;
		var active = SceneManager.GetActiveScene();
		return active.IsValid()
			&& string.Equals(active.name, GameSymbols.FactoryCityScene.FactoryUnitySceneName, StringComparison.Ordinal);
	}

	internal static void RegisterRequired(Harmony harmony, ManualLogSource log, bool enabled)
	{
		_log = log;
		_enabled = enabled;
		if (!enabled)
		{
			log?.LogInfo(LogPrefix + "disabled (homm3FactoryCitySceneReplace=false).");
			return;
		}

		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException("Harmony was not initialized before Factory city scene registration.");

		_sessionEntryType = GameMember.FindType(
			GameSymbols.FactoryCityScene.SessionSceneEntryTypeId,
			GameSymbols.FactoryCityScene.SessionSceneEntryTypeHints[0]);
		if (_sessionEntryType == null)
			throw new InvalidOperationException(LogPrefix + "session scene entry type missing.");
		_sessionEntryArrayType = typeof(Il2CppReferenceArray<>).MakeGenericType(_sessionEntryType);
		ResolveSessionEntryAccessorsOrThrow();
		Homm3PreviewApplyNextFrame.Ensure(log);

		var patched = 0;
		patched += PatchEsceneFromString(harmony);
		patched += PatchEsceneSceneLoad(harmony);
		patched += PatchEsceneSceneIsLoaded(harmony);
		patched += PatchLoadScene(harmony);
		patched += PatchLoadSceneAsync(harmony);
		patched += PatchSessionLoaderAllScenes(harmony);
		patched += PatchNativeBuildingMutation(harmony);
		patched += Homm3FactoryCityWorldVisuals.RegisterHarmony(harmony);
		PatchCityUiSceneCrumbs(harmony);

		if (patched == 0)
			throw new InvalidOperationException(LogPrefix + "no patch surfaces registered.");

		_registered = true;
		log?.LogInfo(LogPrefix + "registered " + patched + " patch surface(s). Unity scene='"
			+ GameSymbols.FactoryCityScene.FactoryUnitySceneName
			+ "' session EScene ordinal=" + GameSymbols.FactoryCityScene.SessionESceneOrdinal
			+ " (frozen metadata name cityFactory). Requires Core/manifest citySceneName=cityFactory "
			+ "for all owned custom factions ("
			+ GameSymbols.FactoryCityScene.OwnedCityWorldFactionSids.Length + ").");
	}

	private static void ResolveSessionEntryAccessorsOrThrow()
	{
		_sessionEntryEsceneGetter = null;
		foreach (var name in GameSymbols.FactoryCityScene.SessionEntryEsceneGetterNames)
		{
			_sessionEntryEsceneGetter = AccessTools.Method(_sessionEntryType, name)
				?? AccessTools.PropertyGetter(_sessionEntryType, name);
			if (_sessionEntryEsceneGetter != null)
				break;
		}

		if (_sessionEntryEsceneGetter == null)
			throw new InvalidOperationException(LogPrefix + "session entry EScene getter missing.");

		_sessionEntrySceneSetter = null;
		foreach (var name in GameSymbols.FactoryCityScene.SessionEntrySceneSetterNames)
		{
			_sessionEntrySceneSetter = AccessTools.PropertySetter(_sessionEntryType, name)
				?? AccessTools.Method(_sessionEntryType, name);
			if (_sessionEntrySceneSetter != null)
				break;
		}

		if (_sessionEntrySceneSetter == null)
			throw new InvalidOperationException(LogPrefix + "session entry Scene setter missing.");
	}

	private static int PatchEsceneSceneLoad(Harmony harmony)
	{
		var loadType = GameMember.FindType(
			GameSymbols.FactoryCityScene.EsceneSceneLoadTypeId,
			GameSymbols.FactoryCityScene.EsceneSceneLoadTypeHints[0]);
		if (loadType == null)
			throw new InvalidOperationException(LogPrefix + "EScene scene-load helper type missing.");

		var methods = GameMember.FindMethodsByNames(
			loadType,
			null,
			GameSymbols.FactoryCityScene.EsceneSceneLoad);
		if (methods.Length == 0)
			throw new InvalidOperationException(LogPrefix + "EScene scene-load methods missing on " + loadType.FullName);

		var prefix = new HarmonyMethod(typeof(Homm3FactoryCitySceneRegistrar), nameof(PrefixEsceneSceneLoad));
		var postfix = new HarmonyMethod(typeof(Homm3FactoryCitySceneRegistrar), nameof(PostfixEsceneSceneLoad));
		var count = 0;
		foreach (var method in methods)
		{
			var ps = method.GetParameters();
			if (ps.Length < 1 || ps[0].ParameterType != typeof(EScene))
				continue;
			if (method.ReturnType != typeof(void))
				continue;
			if (method.IsStatic)
				continue;
			harmony.Patch(method, prefix: prefix, postfix: postfix);
			count++;
		}

		if (count == 0)
			throw new InvalidOperationException(LogPrefix + "no Void(EScene…) load surfaces patched on " + loadType.FullName);
		return count;
	}

	private static int PatchNativeBuildingMutation(Harmony harmony)
	{
		var methods = typeof(BhBuildingsManager).GetMethods(
			BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		MethodInfo match = null;
		var count = 0;
		for (var i = 0; i < methods.Length; i++)
		{
			var method = methods[i];
			if (!string.Equals(method.Name,
				    GameSymbols.FactoryCityScene.BuildingMutationMethodName,
				    StringComparison.Ordinal))
				continue;
			var parameters = method.GetParameters();
			if (method.ReturnType != typeof(void) || parameters.Length != 2
				|| parameters[1].ParameterType != typeof(bool))
				continue;
			match = method;
			count++;
		}
		if (count != 1 || match == null)
			throw new InvalidOperationException(LogPrefix + "expected exactly one native BhBuildingsManager "
				+ "building-mutation method; found " + count + ".");
		harmony.Patch(match, postfix: new HarmonyMethod(
			typeof(Homm3FactoryCitySceneRegistrar), nameof(PostfixNativeBuildingMutation)));
		return 1;
	}

	private static void PostfixNativeBuildingMutation()
	{
		if (!_enabled || !OwnsActiveFactoryCityWorld(ModActions.GetCurrentCityFraction()))
			return;
		try
		{
			// Town-layer sync calls Ensure every frame and early-returns once art is applied.
			// Construction/upgrade must invalidate that gate or Fort/Walls (and peers) stay
			// gameplay-active while donor meshes stay hidden with no HotA replacement.
			Homm3FactoryCityWorldVisuals.InvalidateAppliedSignature();
			QueueFactoryPresentationReconcile("native building mutation");
		}
		catch (Exception ex)
		{
			FailOwnedCityPresentation("presentation schedule after native building mutation", ex);
		}
	}
	private static int PatchEsceneSceneIsLoaded(Harmony harmony)
	{
		var loadType = GameMember.FindType(
			GameSymbols.FactoryCityScene.EsceneSceneLoadTypeId,
			GameSymbols.FactoryCityScene.EsceneSceneLoadTypeHints[0]);
		if (loadType == null)
			throw new InvalidOperationException(LogPrefix + "EScene scene-load helper type missing for IsLoaded.");

		var methods = GameMember.FindMethodsByNames(
			loadType,
			new[] { typeof(EScene) },
			GameSymbols.FactoryCityScene.EsceneSceneIsLoaded);
		if (methods.Length == 0)
			throw new InvalidOperationException(LogPrefix + "EScene IsLoaded method missing.");

		var prefix = new HarmonyMethod(typeof(Homm3FactoryCitySceneRegistrar), nameof(PrefixEsceneSceneIsLoaded));
		foreach (var method in methods)
			harmony.Patch(method, prefix: prefix);
		return methods.Length;
	}

	/// <summary>
	/// Pass-through only. Native Di2 owns IsLoaded via its dictionary; inventing true
	/// while skipping Void caused CityUI-with-black-world (live-negative).
	/// </summary>
	private static bool PrefixEsceneSceneIsLoaded(EScene __0)
	{
		return true;
	}

	/// <summary>
	/// Bind cityFactory into Di2's EScene→entry dictionary, then allow native Void(EScene)
	/// to run. Skipping Void after inventing a parallel world was a black-screen owner miss.
	/// </summary>
	private static bool PrefixEsceneSceneLoad(object __instance, EScene __0)
	{
		if (!_enabled)
			return true;
		if (!__0.Equals(FactorySessionEscene()))
		{
			LogNonFactoryVoidWhileOwnedCityActive(__0);
			return true;
		}

		try
		{
			BeginFactoryCityOpenAttempt("Void(EScene)");
			if (__instance == null)
				throw new InvalidOperationException(LogPrefix + "Di2 Void(EScene) __instance was null.");

			EnsureFactoryCityWorldOwned();
			if (_cloneFailed || !_factoryScene.IsValid() || !_factoryScene.isLoaded)
			{
				_log?.LogError(LogPrefix + "world own failed; refusing to let native Void run without a loaded cityFactory Scene.");
				return false;
			}

			// BhBuildingsManager subscribes to native city-state events in OnEnable.
			// It must be active before Di2 runs the Factory EScene transition; activating
			// the content root in the postfix is too late and leaves every BhBuilding
			// inactive and unbound.
			EnsureOwnedBuildingManagerRootActive();
			BindFactorySceneIntoDi2OrThrow(__instance);
			_log?.LogInfo(LogPrefix + "bound cityFactory handle=" + _factoryScene.handle
				+ " into Di2 dictionary for ordinal "
				+ GameSymbols.FactoryCityScene.SessionESceneOrdinal
				+ "; allowing native Void(EScene).");
			return true;
		}
		catch (Exception ex)
		{
			_cloneFailed = true;
			_log?.LogError(LogPrefix + "EScene load bind failed: " + ex);
			return false;
		}
	}

	// --- Recruit-panel -> world flip crumbs (2026-10-05) ---------------------------------
	// In-game: recruiting or closing the HireUnitsMap panel in an owned cityFactory town made
	// native code run Di2 Void(non-factory) (activeScene -> worldLight), suspending the town and
	// leaving an 8-slot placeholder hire screen. The native caller is reached through delegates,
	// so these crumbs name the requested EScene and the last city-UI call that preceded it.
	private const int SceneCrumbLimit = 32;
	private static int _sceneCrumbCount;
	private static string _lastCityUiCrumb = "<none>";
	private static int _lastCityUiCrumbFrame = -1;

	private static bool IsOwnedCityActiveNow()
	{
		if (!(_factoryScene.IsValid() && _factoryScene.isLoaded) || !HasLiveOwnedRoots())
			return false;
		var active = SceneManager.GetActiveScene();
		return active.IsValid()
			&& string.Equals(active.name, GameSymbols.FactoryCityScene.FactoryUnitySceneName, StringComparison.Ordinal);
	}

	private static void LogNonFactoryVoidWhileOwnedCityActive(EScene requested)
	{
		try
		{
			if (_sceneCrumbCount >= SceneCrumbLimit || !IsOwnedCityActiveNow())
				return;
			_sceneCrumbCount++;
			var frame = Time.frameCount;
			_log?.LogInfo(LogPrefix + "SCENE_CRUMB native Void(" + requested + "=" + (int)requested
				+ ") requested while cityFactory active; frame=" + frame
				+ " lastCityUi='" + _lastCityUiCrumb + "' framesSince="
				+ (_lastCityUiCrumbFrame < 0 ? "n/a" : (frame - _lastCityUiCrumbFrame).ToString())
				+ " managed=" + ShortManagedStack() + ".");
		}
		catch
		{
		}
	}

	private static string ShortManagedStack()
	{
		try
		{
			var frames = new System.Diagnostics.StackTrace(2, false).GetFrames();
			if (frames == null || frames.Length == 0)
				return "<native-only>";
			var parts = new List<string>();
			foreach (var f in frames)
			{
				var m = f?.GetMethod();
				if (m == null)
					continue;
				parts.Add((m.DeclaringType?.Name ?? "?") + "." + m.Name);
				if (parts.Count >= 6)
					break;
			}
			return parts.Count == 0 ? "<native-only>" : string.Join(" < ", parts);
		}
		catch
		{
			return "<stack-unavailable>";
		}
	}

	private static void NoteCityUiCrumb(string what)
	{
		try
		{
			if (!IsOwnedCityActiveNow())
				return;
			_lastCityUiCrumb = what;
			_lastCityUiCrumbFrame = Time.frameCount;
		}
		catch
		{
		}
	}

	private static void CrumbCityUiCall(MethodBase __originalMethod)
	{
		NoteCityUiCrumb((__originalMethod?.DeclaringType?.Name ?? "?") + "." + (__originalMethod?.Name ?? "?"));
	}

	private static void CrumbCityUiNavigationCall(MethodBase __originalMethod, Hex.UI.City.ECityNavigation __0)
	{
		NoteCityUiCrumb((__originalMethod?.DeclaringType?.Name ?? "?") + "." + (__originalMethod?.Name ?? "?") + "(" + __0 + ")");
	}

	private static void PatchCityUiSceneCrumbs(Harmony harmony)
	{
		var plain = typeof(Homm3FactoryCitySceneRegistrar).GetMethod(nameof(CrumbCityUiCall), BindingFlags.Static | BindingFlags.NonPublic);
		var nav = typeof(Homm3FactoryCitySceneRegistrar).GetMethod(nameof(CrumbCityUiNavigationCall), BindingFlags.Static | BindingFlags.NonPublic);
		var targets = new (Type type, string name, Type[] args, MethodInfo prefix)[]
		{
			(typeof(Hex.UI.City.BhHireCityView), nameof(Hex.UI.City.BhHireCityView.OnExitBtn), Type.EmptyTypes, plain),
			(typeof(Hex.UI.City.BhHireCityView), "Close", Type.EmptyTypes, plain),
			(typeof(Hex.UI.City.BhNavigationView), nameof(Hex.UI.City.BhNavigationView.OnDeselect), new[] { typeof(Hex.UI.City.ECityNavigation) }, nav),
			(typeof(Hex.UI.City.BhNavigationView), nameof(Hex.UI.City.BhNavigationView.Hide), new[] { typeof(Hex.UI.City.ECityNavigation) }, nav),
			(typeof(BhTownInput), nameof(BhTownInput.ExitTownCmd), Type.EmptyTypes, plain),
		};
		var count = 0;
		foreach (var t in targets)
		{
			try
			{
				var method = t.type.GetMethod(t.name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly, null, t.args, null);
				if (method == null || t.prefix == null)
					continue;
				if (!GameMember.IsHarmonyPatchCompatible(method, t.prefix, out var reason))
				{
					_log?.LogWarning(LogPrefix + "scene crumb skipped " + t.type.Name + "." + t.name + ": " + reason);
					continue;
				}
				harmony.Patch(method, prefix: new HarmonyMethod(t.prefix));
				count++;
			}
			catch (Exception ex)
			{
				_log?.LogWarning(LogPrefix + "scene crumb patch failed " + t.type.Name + "." + t.name + ": " + ex.GetType().Name + ": " + ex.Message);
			}
		}
		_log?.LogInfo(LogPrefix + "scene crumbs patched " + count + "/" + targets.Length + " city-UI surface(s).");
	}

	private static void PostfixEsceneSceneLoad(object __instance, EScene __0)
	{
		if (!_enabled)
			return;

		var active = SceneManager.GetActiveScene();
		var activeName = active.IsValid() ? active.name : "<invalid>";
		var factoryLoaded = _factoryScene.IsValid() && _factoryScene.isLoaded;

		// Other EScene transitions can return while cityFactory remains loaded. Its camera and
		// lights must be parked whenever cityFactory is no longer the active Unity scene.
		if (!__0.Equals(FactorySessionEscene()))
		{
			if (factoryLoaded
				&& HasLiveOwnedRoots()
				&& !(active.IsValid()
					&& string.Equals(activeName, GameSymbols.FactoryCityScene.FactoryUnitySceneName, StringComparison.Ordinal)))
			{
				SuspendOwnedCityPresentation("Void(non-factory) requested=" + __0 + "=" + (int)__0 + " activeScene='" + activeName + "'");
			}
			else if (_factoryCityLoadRequested
			         && !(active.IsValid()
			              && string.Equals(activeName, GameSymbols.FactoryCityScene.FactoryUnitySceneName, StringComparison.Ordinal)))
			{
				_log?.LogInfo(LogPrefix + "ended Factory city open attempt on Void(non-factory) activeScene='"
					+ activeName + "' (cloneFailed=" + _cloneFailed + ").");
				EndFactoryCityOpenAttempt();
			}
			return;
		}

		if (_cloneFailed || _presentationFailed)
			return;

		try
		{
			if (active.IsValid()
				&& string.Equals(activeName, GameSymbols.FactoryCityScene.FactoryUnitySceneName, StringComparison.Ordinal))
			{
				// Activate the deterministic black camera domain immediately. Native BhBuilding
				// variants finish activating later in this frame and are composed from the exact
				// native mutation postfix through one LateUpdate reconciliation.
				EnsureOwnedCityPresentationActive();
			}
			else
			{
				SuspendOwnedCityPresentation("Factory Void returned activeScene='" + activeName + "'");
			}
		}
		catch (Exception ex)
		{
			FailOwnedCityPresentation("presentation activate after Void", ex);
		}

		_log?.LogInfo(LogPrefix + "native Void(EScene) returned; activeScene='"
			+ activeName
			+ "' factoryLoaded=" + factoryLoaded
			+ " liveRoots=" + CountLiveOwnedRoots() + ".");
	}
	private static int PatchEsceneFromString(Harmony harmony)
	{
		var parseType = GameMember.FindType(
			GameSymbols.FactoryCityScene.SceneNameParseTypeId,
			GameSymbols.FactoryCityScene.SceneNameParseTypeHints[0]);
		if (parseType == null)
			throw new InvalidOperationException(LogPrefix + "EScene-from-string type missing.");

		var methods = GameMember.FindMethodsByNames(
			parseType,
			new[] { typeof(string) },
			GameSymbols.FactoryCityScene.SceneNameParse);
		if (methods.Length == 0)
			throw new InvalidOperationException(LogPrefix + "EScene-from-string methods missing on " + parseType.FullName);

		var prefix = new HarmonyMethod(typeof(Homm3FactoryCitySceneRegistrar), nameof(PrefixEsceneFromString));
		foreach (var method in methods)
			harmony.Patch(method, prefix: prefix);
		return methods.Length;
	}

	private static int PatchLoadScene(Harmony harmony)
	{
		var count = 0;
		foreach (var method in AccessTools.GetDeclaredMethods(typeof(SceneManager)))
		{
			if (method.Name != "LoadScene")
				continue;
			var ps = method.GetParameters();
			if (ps.Length < 1 || ps[0].ParameterType != typeof(string))
				continue;

			if (method.ReturnType == typeof(Scene))
			{
				harmony.Patch(
					method,
					prefix: new HarmonyMethod(typeof(Homm3FactoryCitySceneRegistrar), nameof(PrefixLoadSceneStringReturningScene)));
			}
			else
			{
				harmony.Patch(
					method,
					prefix: new HarmonyMethod(typeof(Homm3FactoryCitySceneRegistrar), nameof(PrefixLoadSceneString)));
			}

			count++;
		}

		if (count == 0)
			throw new InvalidOperationException(LogPrefix + "SceneManager.LoadScene(string…) overloads missing.");
		return count;
	}

	private static int PatchLoadSceneAsync(Harmony harmony)
	{
		var count = 0;
		foreach (var method in AccessTools.GetDeclaredMethods(typeof(SceneManager)))
		{
			if (method.Name != "LoadSceneAsync")
				continue;
			var ps = method.GetParameters();
			if (ps.Length < 1 || ps[0].ParameterType != typeof(string))
				continue;

			harmony.Patch(
				method,
				prefix: new HarmonyMethod(typeof(Homm3FactoryCitySceneRegistrar), nameof(PrefixLoadSceneAsyncString)));
			count++;
		}

		if (count == 0)
			throw new InvalidOperationException(LogPrefix + "SceneManager.LoadSceneAsync(string…) overloads missing.");
		return count;
	}

	private static int PatchSessionLoaderAllScenes(Harmony harmony)
	{
		var loaderType = GameMember.FindType(
			GameSymbols.FactoryCityScene.SessionLoaderTypeId,
			GameSymbols.FactoryCityScene.SessionLoaderTypeHints[0]);
		if (loaderType == null)
			throw new InvalidOperationException(LogPrefix + "Hex.Session.Loader type missing.");

		var methods = GameMember.FindMethodsByNames(
			loaderType,
			null,
			GameSymbols.FactoryCityScene.SessionLoaderAllScenesLoaded);
		if (methods.Length == 0)
			throw new InvalidOperationException(LogPrefix + "Session.Loader all-scenes method missing (GameSymbols pin).");

		var prefix = new HarmonyMethod(typeof(Homm3FactoryCitySceneRegistrar), nameof(PrefixSessionLoaderAllScenes));
		foreach (var method in methods)
			harmony.Patch(method, prefix: prefix);
		return methods.Length;
	}

	private static bool PrefixEsceneFromString(string a, ref EScene __result)
	{
		if (!_enabled || string.IsNullOrEmpty(a))
			return true;
		if (!string.Equals(a, GameSymbols.FactoryCityScene.FactoryUnitySceneName, StringComparison.Ordinal))
			return true;

		// Native metadata pin makes Enum.Parse("cityFactory") work in IL2CPP. Managed interop
		// Hex.dll may still label ordinal 26 as cityGnome — force the ordinal for session code.
		__result = FactorySessionEscene();
		if (!_loggedParseMap)
		{
			_loggedParseMap = true;
			_log?.LogInfo(LogPrefix + "bound sceneName '" + a + "' -> EScene ordinal "
				+ GameSymbols.FactoryCityScene.SessionESceneOrdinal + " (cityFactory).");
		}

		return false;
	}

	private static EScene FactorySessionEscene()
	{
		return (EScene)GameSymbols.FactoryCityScene.SessionESceneOrdinal;
	}

	private static bool PrefixLoadSceneString(string sceneName)
	{
		if (!_enabled || string.IsNullOrEmpty(sceneName))
			return true;
		if (!IsFactoryOwnedLoadName(sceneName))
			return true;

		try
		{
			BeginFactoryCityOpenAttempt("LoadScene('" + sceneName + "')");
			EnsureFactoryCityWorldOwned();
			if (_cloneFailed || !_factoryScene.IsValid())
			{
				_log?.LogError(LogPrefix + "world own failed; refusing silent donor LoadScene fallback for '" + sceneName + "'.");
				return false;
			}

			_log?.LogInfo(LogPrefix + "intercepted LoadScene('" + sceneName + "') -> cityFactory handle="
				+ _factoryScene.handle + ".");
			return false;
		}
		catch (Exception ex)
		{
			_cloneFailed = true;
			_log?.LogError(LogPrefix + "LoadScene intercept failed: " + ex);
			return false;
		}
	}

	private static bool PrefixLoadSceneStringReturningScene(string sceneName, ref Scene __result)
	{
		if (!_enabled || string.IsNullOrEmpty(sceneName))
			return true;
		if (!IsFactoryOwnedLoadName(sceneName))
			return true;

		try
		{
			BeginFactoryCityOpenAttempt("LoadScene('" + sceneName + "')");
			EnsureFactoryCityWorldOwned();
			if (_cloneFailed || !_factoryScene.IsValid())
			{
				_log?.LogError(LogPrefix + "world own failed; refusing silent donor LoadScene fallback for '" + sceneName + "'.");
				__result = default;
				return false;
			}

			__result = _factoryScene;
			_log?.LogInfo(LogPrefix + "intercepted LoadScene('" + sceneName + "') returning cityFactory handle="
				+ _factoryScene.handle + ".");
			return false;
		}
		catch (Exception ex)
		{
			_cloneFailed = true;
			_log?.LogError(LogPrefix + "LoadScene (Scene-returning) intercept failed: " + ex);
			__result = default;
			return false;
		}
	}

	private static bool PrefixLoadSceneAsyncString(string sceneName, ref AsyncOperation __result)
	{
		if (!_enabled || string.IsNullOrEmpty(sceneName))
			return true;
		if (!IsFactoryOwnedLoadName(sceneName))
			return true;

		// Do not invent a side-effecting AsyncOperation placeholder (e.g. UnloadUnusedAssets).
		// Fail closed until the live city loader is proven to use sync LoadScene, or a safe
		// completed AsyncOperation handle is available.
		BeginFactoryCityOpenAttempt("LoadSceneAsync('" + sceneName + "')");
		_cloneFailed = true;
		__result = null;
		_log?.LogError(LogPrefix + "LoadSceneAsync('" + sceneName
			+ "') is not supported for Factory city ownership; refuse (use sync LoadScene path).");
		return false;
	}

	private static bool IsFactoryOwnedLoadName(string sceneName)
	{
		return string.Equals(sceneName, GameSymbols.FactoryCityScene.FactoryUnitySceneName, StringComparison.Ordinal)
			|| string.Equals(sceneName, "cityGnome", StringComparison.Ordinal); // pre-pin interop ToString only
	}

	private static void PrefixSessionLoaderAllScenes(object[] __args)
	{
		if (!_enabled || __args == null || __args.Length < 1)
			return;
		try
		{
			// Do not own/move here: EnsureFactoryCityWorldOwned unloads donor cityHuman2,
			// which must only happen on a Factory city open, never for Castle.
			if (_cloneFailed)
				return;

			if (_ownedRoots.Count == 0 || !_factoryScene.IsValid() || !_factoryScene.isLoaded)
			{
				if (_factoryCityLoadRequested && !_factoryCitySessionInjected)
				{
					var active = SceneManager.GetActiveScene();
					var onFactory = active.IsValid()
						&& string.Equals(active.name, GameSymbols.FactoryCityScene.FactoryUnitySceneName,
							StringComparison.Ordinal);
					if (!onFactory)
					{
						// Leave-town / adventure session register while a prior Factory open flag
						// was still set. Clearing the flag is required; sticky _cloneFailed here
						// black-screens the next custom town (live-negative Conflux→Inferno).
						_factoryCityLoadRequested = false;
						_log?.LogInfo(LogPrefix
							+ "cleared stale Factory load request during non-cityFactory session register; active='"
							+ (active.IsValid() ? active.name : "<invalid>") + "'.");
						return;
					}

					_cloneFailed = true;
					throw new InvalidOperationException(LogPrefix
						+ "session loader ran after Factory load request but cityFactory world is not ready.");
				}

				return;
			}

			var loadedScenes = __args[0];
			if (loadedScenes == null)
				throw new InvalidOperationException(LogPrefix + "session loader all-scenes arg[0] was null.");
			__args[0] = InjectFactorySessionEntry(loadedScenes);
			_factoryCitySessionInjected = true;
		}
		catch (Exception ex)
		{
			_cloneFailed = true;
			_log?.LogError(LogPrefix + "session scene register failed: " + ex);
		}
	}

	private static object InjectFactorySessionEntry(object loadedScenesObj)
	{
		var token = FactorySessionEscene();

		var length = (int)AccessTools.Property(loadedScenesObj.GetType(), "Length").GetValue(loadedScenesObj);
		var indexer = loadedScenesObj.GetType().GetProperty("Item");
		if (indexer == null)
			throw new InvalidOperationException(LogPrefix + "session entry array indexer missing.");

		for (var i = 0; i < length; i++)
		{
			var existing = indexer.GetValue(loadedScenesObj, new object[] { i });
			if (existing == null)
				continue;
			var existingToken = ReadEntryEscene(existing);
			if (!existingToken.Equals(token))
				continue;
			WriteEntryScene(existing, _factoryScene);
			if (!_loggedRegister)
			{
				_loggedRegister = true;
				_log?.LogInfo(LogPrefix + "updated existing session entry EScene ordinal "
					+ GameSymbols.FactoryCityScene.SessionESceneOrdinal + " -> cityFactory Scene.");
			}

			return loadedScenesObj;
		}

		var ctor = _sessionEntryType.GetConstructor(new[] { typeof(EScene), typeof(Scene) });
		if (ctor == null)
			throw new InvalidOperationException(LogPrefix + "session entry ctor(EScene, Scene) missing.");
		var entry = ctor.Invoke(new object[] { token, _factoryScene });

		var grown = Activator.CreateInstance(_sessionEntryArrayType, length + 1);
		for (var i = 0; i < length; i++)
			indexer.SetValue(grown, indexer.GetValue(loadedScenesObj, new object[] { i }), new object[] { i });
		indexer.SetValue(grown, entry, new object[] { length });

		if (!_loggedRegister)
		{
			_loggedRegister = true;
			_log?.LogInfo(LogPrefix + "registered cityFactory Scene as EScene ordinal "
				+ GameSymbols.FactoryCityScene.SessionESceneOrdinal + " in session scene list.");
		}

		return grown;
	}

	private static EScene ReadEntryEscene(object entry)
	{
		return (EScene)_sessionEntryEsceneGetter.Invoke(entry, null);
	}

	private static void WriteEntryScene(object entry, Scene scene)
	{
		_sessionEntrySceneSetter.Invoke(entry, new object[] { scene });
	}

	private static void BindFactorySceneIntoDi2OrThrow(object di2)
	{
		if (!_factoryScene.IsValid() || !_factoryScene.isLoaded)
			throw new InvalidOperationException(LogPrefix + "cannot bind Di2 entry: cityFactory Scene is not loaded.");

		MethodBase dictGetter = null;
		foreach (var name in GameSymbols.FactoryCityScene.EsceneSceneLoadDictionaryMembers)
		{
			dictGetter = AccessTools.PropertyGetter(di2.GetType(), name)
				?? AccessTools.Method(di2.GetType(), name);
			if (dictGetter != null)
				break;
		}

		if (dictGetter == null)
			throw new InvalidOperationException(LogPrefix + "Di2 EScene→entry dictionary getter missing.");

		var dict = dictGetter.Invoke(di2, null);
		if (dict == null)
			throw new InvalidOperationException(LogPrefix + "Di2 EScene→entry dictionary was null.");

		var token = FactorySessionEscene();
		object entry = null;
		var tryGetValue = AccessTools.Method(dict.GetType(), "TryGetValue");
		if (tryGetValue != null)
		{
			var args = new object[] { token, null };
			try
			{
				if ((bool)tryGetValue.Invoke(dict, args))
					entry = args[1];
			}
			catch (Exception ex)
			{
				_log?.LogWarning(LogPrefix + "Di2 TryGetValue failed (" + ex.GetType().Name
					+ "); falling back to ContainsKey/get_Item.");
				entry = null;
			}
		}

		if (entry == null)
		{
			var contains = AccessTools.Method(dict.GetType(), "ContainsKey", new[] { typeof(EScene) });
			var getItem = AccessTools.Method(dict.GetType(), "get_Item", new[] { typeof(EScene) })
				?? AccessTools.Method(dict.GetType(), "get_Item");
			if (contains != null && getItem != null && (bool)contains.Invoke(dict, new object[] { token }))
				entry = getItem.Invoke(dict, new object[] { token });
		}

		if (entry == null)
		{
			var ctor = _sessionEntryType.GetConstructor(new[] { typeof(EScene), typeof(Scene) });
			if (ctor == null)
				throw new InvalidOperationException(LogPrefix + "session entry ctor(EScene, Scene) missing for Di2 bind.");
			entry = ctor.Invoke(new object[] { token, _factoryScene });

			var setItem = dict.GetType().GetMethod("set_Item", new[] { typeof(EScene), _sessionEntryType })
				?? dict.GetType().GetMethod("set_Item");
			if (setItem == null)
				throw new InvalidOperationException(LogPrefix + "Di2 dictionary set_Item missing.");
			setItem.Invoke(dict, new object[] { token, entry });
			_log?.LogInfo(LogPrefix + "inserted Di2 dictionary entry for ordinal "
				+ GameSymbols.FactoryCityScene.SessionESceneOrdinal + ".");
		}
		else
		{
			WriteEntryScene(entry, _factoryScene);
			_log?.LogInfo(LogPrefix + "updated Di2 dictionary entry Scene for ordinal "
				+ GameSymbols.FactoryCityScene.SessionESceneOrdinal + ".");
		}
	}

	/// <summary>
	/// Vanilla load contract: additive LoadScene(cityHuman2) for authored content, then
	/// MoveGameObjectToScene into cityFactory. Do not Instantiate — that duplicates objects
	/// without the LoadScene lifecycle and produced a black world after Di2/Void succeeded.
	/// CreateScene(cityFactory) is only the Factory-owned container (no authored .unity yet).
	/// </summary>
	private static void EnsureFactoryCityWorldOwned()
	{
		if (_cloneFailed)
		{
			// Leave-town session-register races used to sticky-fail forever even when cityFactory
			// roots were still live. Recover so the next custom town can Void successfully.
			if (HasLiveOwnedRoots() && _factoryScene.IsValid() && _factoryScene.isLoaded)
			{
				_log?.LogWarning(LogPrefix
					+ "recovering from sticky cloneFailed; reusing live cityFactory roots.");
				_cloneFailed = false;
			}
			else
				return;
		}
		if (_factoryScene.IsValid() && _factoryScene.isLoaded && HasLiveOwnedRoots())
			return;

		try
		{
			EnsureDonorTemplateLoaded();
			var donor = SceneManager.GetSceneByName(GameSymbols.FactoryCityScene.DonorUnitySceneName);
			if (!donor.IsValid() || !donor.isLoaded)
				throw new InvalidOperationException(LogPrefix + "donor scene cityHuman2 is not loaded; cannot move roots.");

			_factoryScene = SceneManager.GetSceneByName(GameSymbols.FactoryCityScene.FactoryUnitySceneName);
			if (!_factoryScene.IsValid())
				_factoryScene = CreateFactoryUnitySceneOrThrow();
			if (!_factoryScene.IsValid())
				throw new InvalidOperationException(LogPrefix + "failed to create cityFactory scene container.");

			// If cityFactory still holds stale roots from a prior attempt, clear them before move.
			ClearFactorySceneRoots();
			_ownedRoots.Clear();

			var donorRoots = donor.GetRootGameObjects();
			foreach (var root in donorRoots)
			{
				if (root == null)
					continue;
				SceneManager.MoveGameObjectToScene(root, _factoryScene);
				_ownedRoots.Add(root);
			}

			if (_ownedRoots.Count == 0)
				throw new InvalidOperationException(LogPrefix + "LoadScene(cityHuman2) had zero root GameObjects to move.");

			ValidateOwnedContractOrThrow();
			// Unload empty donor so Castle can LoadScene(cityHuman2) fresh later.
			if (!SceneManager.UnloadScene(donor))
				throw new InvalidOperationException(LogPrefix + "UnloadScene(cityHuman2) after move returned false.");

			if (!SceneManager.SetActiveScene(_factoryScene))
				throw new InvalidOperationException(LogPrefix + "SetActiveScene(cityFactory) after move returned false.");

			EnsureOwnedBuildingManagerRootActive();

			if (_loggedWorldOwned)
				return;
			_loggedWorldOwned = true;
			_log?.LogInfo(LogPrefix + "moved " + _ownedRoots.Count
				+ " LoadScene'd root(s) from cityHuman2 into cityFactory (no Instantiate), "
				+ "unloaded donor, set active scene.");
		}
		catch (Exception)
		{
			_cloneFailed = true;
			throw;
		}
	}

	/// <summary>
	/// Live-positive: synthetic cityFactory ownership left CityCamera and Lights inactive after
	/// Di2 Void succeeded. Probe SetActive on those two roots restored the background framing.
	/// BhBuildingsManager lifecycle is separate and must be active before native Void(EScene).
	/// Call after own and after Void; also from Route A skip.
	/// </summary>
	internal static void EnsureOwnedCityPresentationActive()
	{
		if (_presentationFailed)
			return;
		try
		{
			EnsureOwnedCityPresentationActiveOrThrow();
		}
		catch (Exception ex)
		{
			FailOwnedCityPresentation("presentation activation", ex);
		}
	}

	private static void EnsureOwnedCityPresentationActiveOrThrow()
	{
		if (_presentationFailed)
			return;
		if (!_enabled || !_registered)
			return;
		if (!_factoryScene.IsValid() || !_factoryScene.isLoaded)
			_factoryScene = SceneManager.GetSceneByName(GameSymbols.FactoryCityScene.FactoryUnitySceneName);
		if (!_factoryScene.IsValid() || !_factoryScene.isLoaded)
			throw new InvalidOperationException(LogPrefix + "EnsureOwnedCityPresentationActive requires a loaded cityFactory scene.");

		var active = SceneManager.GetActiveScene();
		if (!active.IsValid()
			|| !string.Equals(active.name, GameSymbols.FactoryCityScene.FactoryUnitySceneName, StringComparison.Ordinal))
		{
			SuspendOwnedCityPresentation("Ensure skipped; activeScene='"
				+ (active.IsValid() ? active.name : "<invalid>") + "'");
			return;
		}

		Homm3OwnedCityMapCursorSuppress.NotifyOwnedCityPresentationActive();

		var required = GameSymbols.FactoryCityScene.RequiredPresentationRootNames;
		if (required == null || required.Length == 0)
			throw new InvalidOperationException(LogPrefix + "RequiredPresentationRootNames is empty.");

		var activated = new List<string>();
		var found = new HashSet<string>(StringComparer.Ordinal);
		var roots = _factoryScene.GetRootGameObjects();
		for (var i = 0; i < roots.Length; i++)
		{
			var root = roots[i];
			if (root == null)
				continue;

			for (var r = 0; r < required.Length; r++)
			{
				var name = required[r];
				if (!string.Equals(root.name, name, StringComparison.Ordinal))
					continue;

				found.Add(name);
				if (!root.activeSelf)
				{
					root.SetActive(true);
					activated.Add(name);
				}

				if (string.Equals(name, "CityCamera", StringComparison.Ordinal))
					EnsureCityCameraSolidBlack(root);
			}
		}

		var missing = new List<string>();
		for (var r = 0; r < required.Length; r++)
		{
			if (!found.Contains(required[r]))
				missing.Add(required[r]);
		}

		if (missing.Count > 0)
			throw new InvalidOperationException(LogPrefix + "cityFactory missing required presentation root(s): "
				+ string.Join(", ", missing));

		for (var r = 0; r < required.Length; r++)
		{
			var name = required[r];
			GameObject match = null;
			for (var i = 0; i < roots.Length; i++)
			{
				var root = roots[i];
				if (root != null && string.Equals(root.name, name, StringComparison.Ordinal))
				{
					match = root;
					break;
				}
			}

			if (match == null || !match.activeInHierarchy)
				throw new InvalidOperationException(LogPrefix + "cityFactory presentation root '"
					+ name + "' is not activeInHierarchy after SetActive.");
		}

		if (activated.Count > 0)
			_log?.LogInfo(LogPrefix + "activated presentation root(s): " + string.Join(", ", activated) + ".");

		// Fatal apply previously parked the BhBuildingsManager root. Re-activate it before
		// lifecycle validation so a fixed layer map can recover mid-session without leave/re-enter
		// (live-negative: inactive-manager spam after first missing nativeLevels miss).
		EnsureOwnedBuildingManagerRootActive();

		if (!TryValidateOwnedBuildingLifecycle(out var waitingReason))
		{
			if (!string.Equals(_lastPresentationWaitReason, waitingReason, StringComparison.Ordinal))
			{
				_lastPresentationWaitReason = waitingReason;
				_log?.LogInfo(LogPrefix + "Factory presentation waiting for native lifecycle: " + waitingReason);
			}
			// Always arm a follow-up frame. While reconcile is running, Queue is a no-op unless
			// pending is set — otherwise the first wait never retries after Main binds.
			QueueFactoryPresentationReconcile("presentation readiness");
			return;
		}

		_lastPresentationWaitReason = null;

		// Always invoke Apply: its join-signature gate is cheap once textures load after the match
		// check. A blind IsApplied early-return locked Rampart (and peers) at "applied 1 building"
		// while Main/Tavern/Market activated later with donors already hidden (BepInEx live-negative).
		Homm3FactoryCityWorldVisuals.ApplyOwnedFactoryWorldArt();
		// Native variants can finish activating a few frames after the first ready apply.
		// Arm settle once; do not re-arm after the countdown reaches 0 (live-negative load storm).
		if (!_presentationSettleArmed)
		{
			_presentationSettleArmed = true;
			_presentationSettleFramesLeft = 8;
			if (!_factoryPresentationReconcileRunning)
				QueueFactoryPresentationReconcile("presentation settle");
		}
	}

	/// <summary>
	/// Park cityFactory Lights/CityCamera while the owned scene stays loaded but is not active.
	/// Live-positive: leaving those roots on after Void→worldLight broke adventure-map lighting.
	/// </summary>
	internal static void SuspendOwnedCityPresentation(string reason)
	{
		if (!_enabled || !_registered)
			return;
		if (!_factoryScene.IsValid() || !_factoryScene.isLoaded)
		{
			// Town leave must not poison the next open even when cityFactory is already gone.
			EndFactoryCityOpenAttempt();
			return;
		}

		var required = GameSymbols.FactoryCityScene.RequiredPresentationRootNames;
		if (required == null || required.Length == 0)
			return;

		var deactivated = new List<string>();
		var roots = _factoryScene.GetRootGameObjects();
		for (var i = 0; i < roots.Length; i++)
		{
			var root = roots[i];
			if (root == null)
				continue;
			for (var r = 0; r < required.Length; r++)
			{
				var name = required[r];
				if (!string.Equals(root.name, name, StringComparison.Ordinal))
					continue;
				if (root.activeSelf)
				{
					root.SetActive(false);
					deactivated.Add(name);
				}
			}
		}

		_lastPresentationWaitReason = null;
		Homm3FactoryCityWorldVisuals.ClearOwnedFactoryWorldArt();
		ModActions.ResetCityBackdropBasisSize();
		Homm3OwnedCityMapCursorSuppress.NotifyOwnedCityPresentationSuspended(reason);

		// Town leave must not poison the next custom-faction city open.
		EndFactoryCityOpenAttempt();
		if (_cloneFailed && HasLiveOwnedRoots() && _factoryScene.IsValid() && _factoryScene.isLoaded)
		{
			_log?.LogWarning(LogPrefix
				+ "clearing sticky cloneFailed on suspend; cityFactory roots are still live.");
			_cloneFailed = false;
		}

		var manager = FindOwnedBuildingsManagerOrThrow();
		var managerRoot = manager.transform.root.gameObject;
		if (managerRoot.activeSelf)
		{
			managerRoot.SetActive(false);
			deactivated.Add("BhBuildingsManager root");
		}

		if (deactivated.Count > 0)
			_log?.LogInfo(LogPrefix + "suspended presentation root(s): " + string.Join(", ", deactivated)
				+ " (" + reason + ").");
	}
	/// <summary>
	/// Audit B2 (2026-09-27): one Factory city open is one attempt. _cloneFailed and
	/// _factoryCitySessionInjected were sticky across opens (only recoverable while cityFactory
	/// roots were still live), so a single failed ownership attempt refused every later open and
	/// black-screened it. A new attempt starts when no Factory load request is outstanding: it
	/// clears the previous attempt's failure (logged) and injection flag. Within one attempt a
	/// failure still fails closed for the remaining prefixes. Leaving the city (Suspend) ends the
	/// attempt even when the cityFactory scene is already gone.
	/// Contract: tools/validate_native_hook_safety_contract.py.
	/// </summary>
	private static void BeginFactoryCityOpenAttempt(string source)
	{
		if (_factoryCityLoadRequested)
			return;
		if (_cloneFailed)
		{
			_log?.LogWarning(LogPrefix + "new Factory city open (" + source
				+ ") retries world ownership after a previous failed attempt.");
			_cloneFailed = false;
		}
		_factoryCitySessionInjected = false;
		_factoryCityLoadRequested = true;
	}

	private static void EndFactoryCityOpenAttempt()
	{
		_factoryCityLoadRequested = false;
		_factoryCitySessionInjected = false;
		_presentationFailed = false;
		_presentationSettleFramesLeft = 0;
		_presentationSettleArmed = false;
		_factoryPresentationReconcilePending = false;
	}

	private static void EnsureCityCameraSolidBlack(GameObject cityCameraRoot)
	{
		if (cityCameraRoot == null)
			throw new InvalidOperationException(LogPrefix + "CityCamera root is null.");
		var mainCamera = cityCameraRoot.transform.Find("MainCamera");
		var camera = mainCamera != null
			? mainCamera.GetComponent<Camera>()
			: cityCameraRoot.GetComponentInChildren<Camera>(true);
		if (camera == null)
			throw new InvalidOperationException(LogPrefix + "CityCamera has no Camera component.");
		camera.clearFlags = CameraClearFlags.SolidColor;
		camera.backgroundColor = Color.black;
		DisableDonorCityLensFlares(camera);
	}

	/// <summary>
	/// cityFactory is built from the Castle donor cityHuman2, whose Lights root carries two
	/// native screen-space sun flares (Lights/LensFlareCursor, Lights/LensFlareCursorFree; the
	/// obfuscated flare MonoBehaviour referenced by BhCityCameraController.lensFlares) drawn by the
	/// MainCamera's BhCameraContext (serialized lensFlares=1 in cityHuman2). That top-right sun
	/// suits Castle's own sky but not the HoMM3 town paintings every owned-world faction shows,
	/// so the owned world turns the camera's native lens-flare pass off. Vanilla Castle loads
	/// cityHuman2 fresh and keeps its flare. Static/decomp evidence:
	/// artifacts/claude_takeover_20260927/town_flare. User-visible removal is unproven.
	/// A missing BhCameraContext is logged as an error and the flare is left as native draws it.
	/// </summary>
	private static void DisableDonorCityLensFlares(Camera camera)
	{
		var context = camera.GetComponent(Il2CppType.Of<Hex.Render.BhCameraContext>())
			?.TryCast<Hex.Render.BhCameraContext>();
		if (context == null)
		{
			if (!_lensFlareContextMissingLogged)
			{
				_lensFlareContextMissingLogged = true;
				_log?.LogError(LogPrefix + "cityFactory MainCamera '" + camera.name
					+ "' has no Hex.Render.BhCameraContext; cannot disable the cityHuman2 donor sun flare.");
			}
			return;
		}

		if (!context.lensFlares)
			return;
		context.lensFlares = false;
		_log?.LogInfo(LogPrefix + "disabled cityHuman2 donor lens flares on cityFactory MainCamera (BhCameraContext.lensFlares true -> false).");
	}

	private static bool _lensFlareContextMissingLogged;
	private static void EnsureOwnedBuildingManagerRootActive()
	{
		var manager = FindOwnedBuildingsManagerOrThrow();
		var managerRoot = manager.transform.root.gameObject;
		if (managerRoot.scene.handle != _factoryScene.handle)
			throw new InvalidOperationException(LogPrefix
				+ "BhBuildingsManager root is not owned by cityFactory.");

		if (!managerRoot.activeSelf)
		{
			managerRoot.SetActive(true);
			_log?.LogInfo(LogPrefix + "activated BhBuildingsManager root before native Void(EScene).");
		}

		if (!manager.gameObject.activeInHierarchy)
			throw new InvalidOperationException(LogPrefix
				+ "BhBuildingsManager is not activeInHierarchy after activating its root.");
	}

	private static void FailOwnedCityPresentation(string context, Exception failure)
	{
		try
		{
			// Suspend clears sticky failure so a normal leave-town park can reopen later.
			// Re-arm AFTER suspend or town-layer sync retries Ensure forever (black screen + error loop).
			SuspendOwnedCityPresentation("fatal " + context);
			_log?.LogError(LogPrefix + context + " failed; Factory presentation was suspended: " + failure);
		}
		catch (Exception rollbackFailure)
		{
			_log?.LogError(new AggregateException(LogPrefix + context
				+ " failed and presentation suspension also failed.", failure, rollbackFailure));
		}
		finally
		{
			_presentationFailed = true;
		}
	}

	private static void QueueFactoryPresentationReconcile(string reason)
	{
		if (_factoryPresentationReconcileQueued || _factoryPresentationReconcileRunning)
		{
			_factoryPresentationReconcilePending = true;
			return;
		}
		_factoryPresentationReconcileQueued = true;
		try
		{
			Homm3PreviewApplyNextFrame.QueueRequired(_log, () =>
			{
				_factoryPresentationReconcileQueued = false;
				_factoryPresentationReconcileRunning = true;
				try
				{
					if (OwnsActiveFactoryCityWorld(ModActions.GetCurrentCityFraction()))
						EnsureOwnedCityPresentationActive();
				}
				catch (Exception ex)
				{
					FailOwnedCityPresentation("presentation reconcile after " + reason, ex);
				}
				finally
				{
					_factoryPresentationReconcileRunning = false;
					var pending = _factoryPresentationReconcilePending;
					_factoryPresentationReconcilePending = false;

					// Countdown only on settle passes.
					if (string.Equals(reason, "presentation settle", StringComparison.Ordinal)
						&& _presentationSettleFramesLeft > 0)
					{
						_presentationSettleFramesLeft--;
						if (_presentationSettleFramesLeft > 0)
							QueueFactoryPresentationReconcile("presentation settle");
						else if (pending)
							QueueFactoryPresentationReconcile("presentation readiness");
					}
					else if (_lastPresentationWaitReason != null || pending)
					{
						// Still waiting for Main/binding, or a mutation arrived mid-reconcile.
						if (OwnsActiveFactoryCityWorld(ModActions.GetCurrentCityFraction()))
							QueueFactoryPresentationReconcile("presentation readiness");
					}
				}
			}, "Factory presentation reconciliation");
		}
		catch
		{
			_factoryPresentationReconcileQueued = false;
			throw;
		}
	}

	private static bool TryValidateOwnedBuildingLifecycle(out string waitingReason)
	{
		var manager = FindOwnedBuildingsManagerOrThrow();
		if (!manager.gameObject.activeInHierarchy)
			throw new InvalidOperationException(LogPrefix + "BhBuildingsManager is inactive after native Void(EScene).");

		var buildings = manager.transform.root.GetComponentsInChildren<BhBuilding>(true);
		var active = 0;
		var activeBound = 0;
		for (var i = 0; i < buildings.Length; i++)
		{
			var building = buildings[i];
			if (building == null || building.gameObject == null || !building.gameObject.activeInHierarchy)
				continue;
			active++;
			if (Homm3FactoryCityWorldVisuals.HasBoundBuildingLogic(building))
				activeBound++;
		}

		if (active == 0)
		{
			waitingReason = "zero active BhBuilding variants";
			return false;
		}
		if (activeBound != active)
		{
			waitingReason = activeBound + "/" + active
				+ " active BhBuilding variants bound to native Building logic";
			return false;
		}

		// Town hall (Main) is present in every constructed city. Composing before it binds paints
		// whichever dwelling woke first, hides Castle donor meshes, then never shows the hall.
		var mainBound = false;
		for (var i = 0; i < buildings.Length; i++)
		{
			var building = buildings[i];
			if (building == null || building.gameObject == null || !building.gameObject.activeInHierarchy)
				continue;
			if (!Homm3FactoryCityWorldVisuals.HasBoundBuildingLogic(building))
				continue;
			if (!string.Equals(Homm3FactoryCityWorldVisuals.FindSceneSlotName(building.transform),
				    "Main", StringComparison.Ordinal))
				continue;
			mainBound = true;
			break;
		}
		if (!mainBound)
		{
			waitingReason = "Main (town hall) BhBuilding not yet active and bound";
			return false;
		}

		waitingReason = null;
		return true;
	}
	private static BhBuildingsManager FindOwnedBuildingsManagerOrThrow()
	{
		BhBuildingsManager match = null;
		var count = 0;
		foreach (var root in _ownedRoots)
		{
			if (root == null)
				continue;
			var managers = root.GetComponentsInChildren<BhBuildingsManager>(true);
			if (managers == null)
				continue;
			for (var i = 0; i < managers.Length; i++)
			{
				if (managers[i] == null)
					continue;
				match = managers[i];
				count++;
			}
		}

		if (count != 1 || match == null)
			throw new InvalidOperationException(LogPrefix
				+ "cityFactory requires exactly one BhBuildingsManager; found " + count + ".");
		return match;
	}
	private static bool HasLiveOwnedRoots()
	{
		return CountLiveOwnedRoots() > 0;
	}

	private static int CountLiveOwnedRoots()
	{
		var count = 0;
		foreach (var root in _ownedRoots)
		{
			if (root != null)
				count++;
		}

		return count;
	}

	/// <summary>
	/// Live Golden Era interop cannot use the managed CreateScene(string, …) wrapper:
	/// it calls Il2CppSystem.ReadOnlySpan`1.GetPinnableReference(),
	/// which is missing (MissingMethodException → black town after refuse).
	/// Call CreateScene_Injected with a pinned ManagedSpanWrapper instead.
	/// CreateSceneParameters still uses default struct + localPhysicsMode (no
	/// LocalPhysicsMode ctor on this interop).
	/// </summary>
	private static unsafe Scene CreateFactoryUnitySceneOrThrow()
	{
		var name = GameSymbols.FactoryCityScene.FactoryUnitySceneName;
		if (string.IsNullOrEmpty(name))
			throw new InvalidOperationException(LogPrefix + "FactoryUnitySceneName is empty.");

		var parameters = default(CreateSceneParameters);
		parameters.localPhysicsMode = LocalPhysicsMode.None;
		Scene scene = default;
		fixed (char* chars = name)
		{
			var span = new ManagedSpanWrapper(chars, name.Length);
			SceneManager.CreateScene_Injected(ref span, ref parameters, out scene);
		}

		if (!scene.IsValid())
			throw new InvalidOperationException(LogPrefix
				+ "CreateScene_Injected(cityFactory) returned an invalid scene.");
		return scene;
	}

	private static void EnsureDonorTemplateLoaded()
	{
		var donor = SceneManager.GetSceneByName(GameSymbols.FactoryCityScene.DonorUnitySceneName);
		if (donor.IsValid() && donor.isLoaded)
			return;
		SceneManager.LoadScene(GameSymbols.FactoryCityScene.DonorUnitySceneName, LoadSceneMode.Additive);
		donor = SceneManager.GetSceneByName(GameSymbols.FactoryCityScene.DonorUnitySceneName);
		if (!donor.IsValid() || !donor.isLoaded)
			throw new InvalidOperationException(LogPrefix + "additive LoadScene(cityHuman2) did not produce a loaded scene.");
	}

	private static void ClearFactorySceneRoots()
	{
		if (!_factoryScene.IsValid())
			return;
		foreach (var root in _factoryScene.GetRootGameObjects())
		{
			if (root != null)
				Object.DestroyImmediate(root);
		}
	}

	private static void ValidateOwnedContractOrThrow()
	{
		var managerType = ModActions.GetHexType(GameSymbols.FactoryCityScene.BuildingsManagerTypeName);
		if (managerType == null)
			throw new InvalidOperationException(LogPrefix + "BhBuildingsManager type missing after move.");

		var managerIl2Cpp = Il2CppType.From(managerType);
		Component manager = null;
		foreach (var root in _ownedRoots)
		{
			if (root == null)
				continue;
			manager = root.GetComponentInChildren(managerIl2Cpp, true);
			if (manager != null)
				break;
		}

		if (manager == null)
			throw new InvalidOperationException(LogPrefix + "cityFactory missing BhBuildingsManager after move.");

		var cameraType = ModActions.GetHexType("Hex.Session.City.BhCityCameraController");
		if (cameraType == null)
			throw new InvalidOperationException(LogPrefix + "BhCityCameraController type missing after move.");

		var cameraIl2Cpp = Il2CppType.From(cameraType);
		Component camera = null;
		foreach (var root in _ownedRoots)
		{
			if (root == null)
				continue;
			camera = root.GetComponentInChildren(cameraIl2Cpp, true);
			if (camera != null)
				break;
		}

		if (camera == null)
			throw new InvalidOperationException(LogPrefix + "cityFactory missing BhCityCameraController after move.");

		var buildingType = ModActions.GetHexType(GameSymbols.FactoryCityScene.BuildingTypeName);
		if (buildingType == null)
			throw new InvalidOperationException(LogPrefix + "BhBuilding type missing after move.");

		var buildingIl2Cpp = Il2CppType.From(buildingType);
		var buildingCount = 0;
		foreach (var root in _ownedRoots)
		{
			if (root == null)
				continue;
			var found = root.GetComponentsInChildren(buildingIl2Cpp, true);
			if (found != null)
				buildingCount += found.Length;
		}

		if (buildingCount < GameSymbols.FactoryCityScene.ExpectedBhBuildingCount)
			throw new InvalidOperationException(LogPrefix + "cityFactory BhBuilding count=" + buildingCount
				+ " expected>=" + GameSymbols.FactoryCityScene.ExpectedBhBuildingCount + " after move.");

		var expectedSlots = GameSymbols.FactoryCityScene.ExpectedSceneSlotNames;
		var missingSlots = new List<string>();
		foreach (var slotName in expectedSlots)
		{
			var found = false;
			foreach (var root in _ownedRoots)
			{
				if (root == null)
					continue;
				if (FindTransformNamed(root.transform, slotName) != null)
				{
					found = true;
					break;
				}
			}

			if (!found)
				missingSlots.Add(slotName);
		}

		if (missingSlots.Count > 0)
			throw new InvalidOperationException(LogPrefix + "cityFactory missing sceneSlot name(s) after move: "
				+ string.Join(", ", missingSlots));
	}

	private static Transform FindTransformNamed(Transform root, string name)
	{
		if (root == null)
			return null;
		if (string.Equals(root.name, name, StringComparison.Ordinal))
			return root;
		for (var i = 0; i < root.childCount; i++)
		{
			var hit = FindTransformNamed(root.GetChild(i), name);
			if (hit != null)
				return hit;
		}

		return null;
	}
}
