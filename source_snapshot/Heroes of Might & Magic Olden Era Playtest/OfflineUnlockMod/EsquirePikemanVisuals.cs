using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Replaces <c>esquire</c> / <c>esquire_map</c> visuals from a local <see cref="AssetBundle"/>
/// (same <c>units/...</c> keys; no <c>Core.zip</c> edit) via narrow hooks. Adventure stacks also use a <b>map-only</b>
/// <c>ResManager.Get&lt;GameObject&gt;</c> postfix: adventure-map prefabs and <b>battle SFX</b> under
/// <c>sounds/battle/units/esquire/</c> — same as vanilla: small **Editor-built** prefabs (<see cref="GameObject"/> +
/// <see cref="AudioSource"/> + mixer/spatial settings), packed as <c>Assets/CustomUnits/esquire/sounds/ESQUIRE_*.prefab</c> in the bundle.
/// We avoid the legacy full <c>ResManager</c> prefix that broke <c>Map.Init</c>.
/// <c>battle.prefab</c> uses <c>MeshRenderer</c> + quad (bundle: <c>Sprites/Default</c> is fine in battle). <c>map.prefab</c> frame materials: default <c>hexLitVanilla</c> copies stock <c>esquire_map</c> (<c>Esquire_mat</c> / <c>Hex/Lit</c>) onto the native shell renderer via transplant; <c>spritesDefault</c> is debug-only. <see cref="EsquirePikemanMapBillboardFogSync"/> and <see cref="Homm3NativeShellVisibilitySync"/> do not work for map FoW — never attach them for HoMM3 units.
/// </summary>
internal static class EsquirePikemanVisuals
{
	/// <summary>Base pikeman battle prefab key only. <c>esquire_upg*</c> / other ids are separate units with their own assets — do not map them here.</summary>
	public const string BattleResPath = "units/Humans/1Prefabs/esquire";

	/// <summary>Base pikeman adventure-map key only. Upgrade/cosmetic rows use other <c>…_map</c> paths and are out of scope for <c>custom_units_esquire</c>.</summary>
	public const string MapResPath = "units/Humans/1Prefabs/esquire_map";

	/// <summary>Shipped battle SFX lookups use <c>Get&lt;GameObject&gt;</c> with paths whose final segment is <c>ESQUIRE_*</c> (e.g. <c>…/attack/ESQUIRE_Attack_1</c>).</summary>
	const string EsquireBattleSoundPathPrefix = "sounds/battle/units/esquire/";

	/// <summary>Editor-authored SFX prefabs (one per clip); must match Unity asset paths in <c>custom_units_esquire</c>.</summary>
	const string EsquireSoundPrefabAssetDir = "Assets/CustomUnits/esquire/sounds/";

	static string EsquireSoundPrefabAssetPath(string stem) =>
		EsquireSoundPrefabAssetDir + stem + ".prefab";

	/// <summary>Maps a spawner <c>Spawn(string relativePath, …)</c> first argument to the same <c>units/…</c> form as <c>ResManager</c> keys.</summary>
	internal static string ToUnitsResPathFromSpawnPath(string pathFromSpawn)
	{
		if (string.IsNullOrEmpty(pathFromSpawn))
			return string.Empty;
		var p = pathFromSpawn.Trim().Replace('\\', '/');
		if (p.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
			p = p.Substring(0, p.Length - ".prefab".Length);
		if (p.StartsWith("units/", StringComparison.Ordinal))
			return p;
		return "units/" + p;
	}

	static string NormalizeEsquireSoundLeaf(string leaf)
	{
		if (string.IsNullOrEmpty(leaf))
			return leaf;
		leaf = leaf.Trim().TrimEnd('/');
		while (leaf.Length > 0 && (leaf[^1] == '#' || leaf[^1] == '\''))
			leaf = leaf[..^1];
		return leaf;
	}

	/// <summary>Final path segment must be shipped prefab root name (e.g. <c>ESQUIRE_Attack_1</c>) — matches bundle prefab file.</summary>
	static bool TryGetEsquireSoundStemFromResPath(string normPath, out string stem)
	{
		stem = null;
		if (string.IsNullOrEmpty(normPath))
			return false;
		var leaf = NormalizeEsquireSoundLeaf(Path.GetFileName(normPath.TrimEnd('/')));
		if (string.IsNullOrEmpty(leaf)
		    || !leaf.StartsWith("ESQUIRE_", StringComparison.OrdinalIgnoreCase))
			return false;
		stem = leaf;
		return true;
	}

	/// <returns><c>true</c> if <paramref name="resPath"/> is under <see cref="EsquireBattleSoundPathPrefix"/> (caller skips normal map/battle handling).</returns>
	static bool TryApplyEsquireBattleSoundPrefabIfPath(string resPath, ref GameObject __result)
	{
		if (string.IsNullOrEmpty(resPath))
			return false;
		var norm = resPath.Trim().Replace('\\', '/');
		if (!norm.StartsWith(EsquireBattleSoundPathPrefix, StringComparison.OrdinalIgnoreCase))
			return false;

		if (Interlocked.CompareExchange(ref _inReentrantGet, 1, 0) != 0)
		{
			Diag("EsquireSoundResReentrancyBail", "path=" + SanitizeForDiag(resPath), Plugin.LogSource);
			return true;
		}

		try
		{
			VerboseLogEveryResGet(resPath);
			int frame;
			try
			{
				frame = Time.frameCount;
			}
			catch
			{
				frame = -1;
			}

			_lastEsquireGetPath = resPath;
			_lastEsquireGetFrame = frame;
			Diag(
				"EsquireSoundResEnter",
				"path=" + SanitizeForDiag(resPath) + " frame=" + frame + " resNull=" + (__result == null),
				Plugin.LogSource);
			try
			{
				TryInit(Plugin.LogSource);
			}
			catch (Exception ex)
			{
				Diag("TryInitException", ex.ToString(), Plugin.LogSource);
				Plugin.LogSource?.LogError("EsquirePikeman: TryInit failed: " + ex);
				return true;
			}

			if (_bundle == null || !TryGetEsquireSoundStemFromResPath(norm, out var stem))
				return true;

			GameObject prefab;
			try
			{
				prefab = _bundle.LoadAsset<GameObject>(EsquireSoundPrefabAssetPath(stem));
			}
			catch
			{
				prefab = null;
			}

			if (prefab && prefab)
			{
				__result = prefab;
				Diag("EsquireSoundResReplaced", "path=" + SanitizeForDiag(norm) + " stem=" + stem, Plugin.LogSource);
				if (_verbose)
				{
					var a = prefab.GetComponent<AudioSource>();
					Plugin.LogSource?.LogInfo(
						"EsquirePikeman: ResManager GameObject (sound) for '"
						+ resPath
						+ "' → bundle '"
						+ stem
						+ "' clip="
						+ (a && a.clip ? a.clip.name : "?")
						+ ".");
				}
			}
			else if (VerboseEsquireHooks)
			{
				Plugin.LogSource?.LogWarning(
					"EsquirePikeman: no bundle sound prefab for stem '"
					+ stem
					+ "' at '"
					+ EsquireSoundPrefabAssetPath(stem)
					+ "' (Res path '"
					+ resPath
					+ "').");
			}

			return true;
		}
		finally
		{
			Interlocked.Exchange(ref _inReentrantGet, 0);
		}
	}

	/// <summary>Loads <c>custom_units_esquire</c> when needed from Harmony postfixes (battle, map).</summary>
	internal static void EnsureEsquireBundleLoaded(ManualLogSource log) => TryInit(log);

	/// <summary>Used by <see cref="EsquirePikemanNarrowSpawnerHook"/>; loads bundle on first use like the ResManager prefix.</summary>
	internal static bool TryGetEsquireTemplateForUnitsPath(string unitsPath, ManualLogSource log, out GameObject template)
	{
		template = null;
		if (string.IsNullOrEmpty(unitsPath))
			return false;
		if (unitsPath != BattleResPath && unitsPath != MapResPath)
			return false;
		if (unitsPath == MapResPath && !_swapAdventureMap)
			return false;
		TryInit(log);
		if (unitsPath == BattleResPath)
			template = _battle;
		else
			template = _map;
		return template != null;
	}

	/// <summary>
	/// Swap <paramref name="result"/> to the bundle map prefab and copy layer/sorting from the stock prefab currently in <paramref name="result"/>.
	/// Shared by <see cref="EsquirePikemanUnitViewHook"/> and <see cref="PostfixResGetGameObjectMapOnly"/>.
	/// </summary>
	internal static bool TryFinalizeMapVisualSwap(ref GameObject result, ManualLogSource log)
	{
		if (!_swapAdventureMap)
			return false;
		if (!TryGetEsquireTemplateForUnitsPath(MapResPath, log, out var template) || template == null || !template)
			return false;
		var vanilla = result;
		if (vanilla && !ReferenceEquals(vanilla, template))
		{
			if (!MapModeIsSpritesDefault() && _vanillaMapMaterialTemplate == null)
			{
				var donorR = EsquireBattleVisualPresentation.TryFindDominantRenderable(vanilla);
				if (donorR != null && donorR.sharedMaterial)
					_vanillaMapMaterialTemplate = donorR.sharedMaterial;
				else
				{
					foreach (var r in vanilla.GetComponentsInChildren<Renderer>(true))
					{
						if (r && r.sharedMaterial)
						{
							_vanillaMapMaterialTemplate = r.sharedMaterial;
							break;
						}
					}
				}

				if (_vanillaMapMaterialTemplate != null)
				{
					log?.LogInfo(
						"EsquirePikeman: captured vanilla map donor mat='"
						+ _vanillaMapMaterialTemplate.name
						+ "' shader='"
						+ (_vanillaMapMaterialTemplate.shader ? _vanillaMapMaterialTemplate.shader.name : "(null)")
						+ "'.");
					RebindMapBundleMaterialsToVanillaTemplate(template, log);
				}
			}
			else if (MapModeIsSpritesDefault() && _verbose && _vanillaMapMaterialTemplate == null)
			{
				log?.LogInfo(
					"EsquirePikeman: map billboard mode=spritesDefault — skipping Esquire_mat clone; Sprites/Default + fog sync.");
			}

			// Build a native shell from the vanilla map prefab so the engine keeps the stock
			// BhMapSquad / map-object component tree (same path as vanilla map sprites).
			var shell = CloneVanillaMapShellForAdventure(vanilla, template, log);
			if (shell)
			{
				result = shell;
				return true;
			}

			var matched = EsquireBattleVisualPresentation.SyncAdventureMapPrefabPresentationFromVanilla(vanilla, template);
			if (matched == 0)
			{
				EsquireBattleVisualPresentation.SyncLayersOnlyFromVanilla(vanilla, template);
				EsquireBattleVisualPresentation.SyncMapRenderersSortingDepthFirstFallback(vanilla, template);
			}
		}

		ConfigureMapPrefabBillboardRenderers(template, log);
		result = template;
		return true;
	}

	/// <summary>
	/// Esquire lane: wrap the bundle quad in a shell cloned from the vanilla map prefab so the engine
	/// fog-of-war / map-object system still sees the original component tree (BhMapSquad, etc.).
	/// Mirrors <see cref="Homm3ImportVisuals.CreateNativeShellMapPrefabForAdventure"/> without
	/// adding a separate Homm3 lane entry requirement.
	/// </summary>
	private static GameObject CloneVanillaMapShellForAdventure(GameObject vanilla, GameObject bundleTemplate, ManualLogSource log)
	{
		if (!vanilla || !bundleTemplate)
			return null;
		try
		{
			var shell = UnityEngine.Object.Instantiate(vanilla);
			if (!shell)
				return null;
			shell.name = (bundleTemplate.name ?? "esquire_map") + "_native_shell";

			// Keep vanilla renderers registered with the engine but not visible.
			foreach (var r in shell.GetComponentsInChildren<Renderer>(true))
			{
				if (!r)
					continue;
				r.forceRenderingOff = true;
				r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
				r.receiveShadows = false;
			}

			var visual = UnityEngine.Object.Instantiate(bundleTemplate);
			if (!visual)
			{
				UnityEngine.Object.Destroy(shell);
				return null;
			}
			visual.name = "esquire_map_visual";
			visual.transform.SetParent(shell.transform, false);
			visual.transform.SetSiblingIndex(shell.transform.childCount - 1);
			visual.transform.localPosition = Vector3.zero;
			visual.transform.localRotation = Quaternion.identity;
			visual.transform.localScale = Vector3.one;

			ConfigureMapPrefabBillboardRenderers(visual, log);
			Homm3ImportVisuals.RemoveNativeShellVisibilityMirrors(shell, log);

			log?.LogInfo(
				"EsquirePikeman: native-shell map swap vanilla='"
				+ (vanilla.name ?? "?")
				+ "' shell='"
				+ shell.name
				+ "' visualRenderers="
				+ visual.GetComponentsInChildren<Renderer>(true).Length
				+ ".");
			return shell;
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquirePikeman: native-shell map swap failed; falling back to direct template: " + ex.Message);
			return null;
		}
	}

	/// <summary>
	/// Custom map art is a large <see cref="MeshRenderer"/> quad; <see cref="ShadowCastingMode.On"/> projects a huge shadow and
	/// extra passes can read wrong. Match a lightweight billboard: no cast, no receive.
	/// </summary>
	private static void ConfigureMapPrefabBillboardRenderers(GameObject mapRoot, ManualLogSource log)
	{
		if (!mapRoot)
			return;
		var n = 0;
		foreach (var nd in mapRoot.GetComponentsInChildren<MeshRenderer>(true))
		{
			if (!nd)
				continue;
			nd.shadowCastingMode = ShadowCastingMode.Off;
			nd.receiveShadows = false;
			n++;
		}

		if (n > 0)
			log?.LogInfo("EsquirePikeman: map billboard MeshRenderer shadowCast=Off receiveShadows=false (count=" + n + ").");
	}

	// Battle bundle mesh must render in the game's 3D battle pass: MeshRenderer + quad, material shader Hex/Lit or Sprites/Default (not SpriteRenderer-only).
	private const string BattleAssetName = "Assets/CustomUnits/esquire/battle.prefab";
	private const string MapAssetName = "Assets/CustomUnits/esquire/map.prefab";
	private const string BundleFileName = "custom_units_esquire";

	private static AssetBundle _bundle;
	private static GameObject _battle;
	private static GameObject _map;
	/// <summary>First slot-0 shared material from stock <c>esquire_map</c> (e.g. <c>Esquire_mat</c>); cleared on bundle unload/reload.</summary>
	private static Material _vanillaMapMaterialTemplate;
	/// <summary>HoMM3 pikeman SFX (raw <see cref="AudioClip"/> in bundle, keyed by stem like <c>ESQUIRE_Attack_1</c>) for <see cref="EsquireBattleAudioPlayer"/>; cleared on bundle reload.</summary>
	private static Dictionary<string, AudioClip> _audioClips;
	private static bool _audioPlayerTypeRegistered;
	private static bool _clipDriverTypeRegistered;
	private static bool _logged;
	private static bool _applyHarmony = true;
	private static bool _deferPatch;
	private static bool _deferBySceneLoad = true;
	private static int _deferSceneLoadSkips;
	private static int _deferPatchFrames;
	/// <summary>Extra engine frames to wait (after a scene-load trigger) before applying the <c>ResManager</c> prefix; 0 = apply immediately in the LoadScene hook.</summary>
	private static int _deferResManagerOffsetFrames = 2;
	private static bool _swapAdventureMap = true;
	/// <summary><c>hexLitVanilla</c> (default) or <c>spritesDefault</c>; see mod config <c>esquirePikemanMapBillboardMaterialMode</c>.</summary>
	private static string _mapBillboardMaterialMode = "hexLitVanilla";
	private static bool _mapBillboardFogSyncTypeRegistered;
	private static bool _homm3MapMaterialSyncTypeRegistered;
	private static bool _homm3NativeShellVisibilitySyncTypeRegistered;
	private static bool _homm3NativeShellRendererTransplantSyncTypeRegistered;
	/// <summary>Il2Cpp: do not use <c>GetComponent&lt;EsquirePikemanMapBillboardFogSync&gt;</c> — it can throw <c>TypeInitializationException</c>; match on <see cref="Component"/> <c>Type.Name</c> instead.</summary>
	private const string MapBillboardFogSyncSimpleName = "EsquirePikemanMapBillboardFogSync";
	/// <summary>HoMM3 <c>hexLitVanilla</c>: <see cref="TryRebindHomm3MapMaterialsFromVanilla"/> must run once per loaded map prefab — <c>rtd()</c> repeats and would reset animator/FoW uniforms every call.</summary>
	private static readonly HashSet<int> Homm3MapHexLitReboundTemplateIds = new();
	private static readonly HashSet<int> Homm3MapHexLitReboundMaterialIds = new();
	private static bool _loggedHomm3EsquireDonorFallback;
	private static int _homm3MapRendererDiagRemaining = 8;
	private static int _homm3MapMaterialResultDiagRemaining = 8;
	private static bool _loggedHomm3SpritesDefaultFogSyncDisabled;
	private static bool _mapBillboardModeConfiguredOnce;
	private static string _lastConfiguredMapBillboardMaterialMode = "";
	/// <summary>When <c>true</c>, Harmony uses a postfix (vanilla runs first) instead of prefix+skip.</summary>
	private static bool _resManagerPostfix;
	private static bool _fileDiagnostics;
	private static bool _verbose;
	private static bool _battleSyncVanillaPresentation = true;
	private static bool _battleBeiSecondArgTrue;
	private static bool _battleAlignFeetToVanilla = true;
	private static float _battleBillboardExtraY;
	private static float _battleSfxVolume = 0.45f;
	private static int _diagLines;
	private static int _diagMaxLines = 2000;
	private static readonly object DiagFileLock = new();
	private static StreamWriter _diagStreamWriter;
	private static string _diagnosticsPath;
	private static bool _diagHeaderWritten;
	private static string _diagBuildLabel = "?";
	private static bool _resManagerPrefixPatched;
	private static Harmony _pendingHarmony;
	private static MethodInfo _pendingClosedResManagerGet;

	internal static bool IsResManagerPrefixPatched => _resManagerPrefixPatched;

	internal static bool HasPendingResManagerPrefix =>
		_pendingHarmony != null && _pendingClosedResManagerGet != null;

	internal static bool BattleSyncVanillaPresentation => _battleSyncVanillaPresentation;

	internal static bool BattleBeiSecondArgTrue => _battleBeiSecondArgTrue;

	internal static bool BattleAlignFeetToVanilla => _battleAlignFeetToVanilla;

	internal static float BattleBillboardExtraY => _battleBillboardExtraY;

	/// <summary>0–1 linear gain for Esquire bundle battle SFX (<c>esquireBattleSfxVolume</c>).</summary>
	internal static float BattleSfxVolume => _battleSfxVolume;

	/// <summary>True when <c>esquirePikemanVerbose</c> is on; used for opt-in battle Animator telemetry.</summary>
	internal static bool VerboseEsquireHooks => _verbose;

	/// <summary>For diagnostics when map <c>rtd()</c> swap misses (e.g. <c>esquirePikemanSwapAdventureMap</c> off).</summary>
	internal static bool SwapAdventureMapEnabledForDiag => _swapAdventureMap;

	internal static void DiagForSceneDefer(string @event, string detail, ManualLogSource log) =>
		Diag(@event, detail, log);

	/// <summary>Frames to defer after a <c>LoadScene</c> trigger before installing the <c>ResManager</c> prefix (avoids <c>Session.OnScenesLoaded</c> races).</summary>
	internal static int DeferredResManagerOffsetFrames => _deferResManagerOffsetFrames;

	private static string _lastEsquireGetPath;
	private static int _lastEsquireGetFrame = -1;

	/// <summary>Single-line state for <see cref="EsquireUnityErrorCorrelator"/> (not a substitute for Unity/Player.log stacks).</summary>
	internal static string GetCorrelationSnapshot()
	{
		return "build="
			+ SanitizeForDiag(_diagBuildLabel)
			+ " resManagerPatched="
			+ _resManagerPrefixPatched
			+ " resManagerPending="
			+ HasPendingResManagerPrefix
			+ " lastEsquireGetPath="
			+ SanitizeForDiag(_lastEsquireGetPath ?? "(none)")
			+ " lastEsquireGetFrame="
			+ _lastEsquireGetFrame
			+ " swapMap="
			+ _swapAdventureMap
			+ " deferResManagerOffsetFrames="
			+ _deferResManagerOffsetFrames
			+ " verbose="
			+ _verbose
			+ " battleSync="
			+ _battleSyncVanillaPresentation
			+ " battleBeiTrue="
			+ _battleBeiSecondArgTrue
			+ " battleAlignFeet="
			+ _battleAlignFeetToVanilla
			+ " battleExtraY="
			+ _battleBillboardExtraY.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ " resManagerPostfix="
			+ _resManagerPostfix
			+ " mapBillboardMode="
			+ SanitizeForDiag(_mapBillboardMaterialMode ?? "?")
			+ " diagCap="
			+ _diagMaxLines;
	}

	/// <summary>Call from <see cref="Plugin.Load"/> before <see cref="PrewarmInPluginLoad"/> / <see cref="TryRegister"/>.</summary>
	internal static void Configure(
		bool applyHarmony,
		bool fileDiagnostics,
		string buildVersionLabel,
		bool deferPatch,
		bool deferBySceneLoad,
		int deferSceneLoadSkips,
		int deferPatchFrames,
		int deferResManagerOffsetFrames,
		bool swapAdventureMap,
		bool resManagerPostfix,
		bool unityErrorCorrelator,
		bool verbose,
		bool battleSyncVanillaPresentation = true,
		bool battleBeiSecondArgTrue = false,
		bool battleAlignFeetToVanilla = true,
		double battleBillboardExtraY = 0,
		string mapBillboardMaterialMode = "hexLitVanilla",
		double battleSfxVolume = 0.45)
	{
		CloseDiagWriter();
		EsquirePikemanSceneDefer.Cancel();
		EsquirePikemanResManagerAtFrame.Cancel();
		EsquireUnityErrorCorrelator.Disable();
		EsquirePikemanBattlePoolHook.Cancel();
		EsquirePikemanUnitViewHook.Cancel();
		EsquireBattleAnimatorSetHook.Cancel();
		_applyHarmony = applyHarmony;
		_resManagerPostfix = resManagerPostfix;
		_verbose = verbose;
		_battleSyncVanillaPresentation = battleSyncVanillaPresentation;
		_battleBeiSecondArgTrue = battleBeiSecondArgTrue;
		_battleAlignFeetToVanilla = battleAlignFeetToVanilla;
		_battleBillboardExtraY = (float)battleBillboardExtraY;
		if (double.IsNaN(battleSfxVolume) || double.IsInfinity(battleSfxVolume))
			battleSfxVolume = 0.45;
		_battleSfxVolume = Mathf.Clamp01((float)battleSfxVolume);
		_fileDiagnostics = fileDiagnostics || verbose;
		_diagMaxLines = verbose ? 50000 : 2000;
		_deferPatch = deferPatch;
		_deferBySceneLoad = deferBySceneLoad;
		_deferSceneLoadSkips = deferSceneLoadSkips;
		_deferPatchFrames = deferPatchFrames;
		_deferResManagerOffsetFrames = deferResManagerOffsetFrames;
		_swapAdventureMap = swapAdventureMap;
		_mapBillboardMaterialMode = LauncherConfigReader.NormalizeEsquireMapBillboardMaterialMode(mapBillboardMaterialMode);
		if (_mapBillboardModeConfiguredOnce
		    && !string.Equals(
			    _lastConfiguredMapBillboardMaterialMode,
			    _mapBillboardMaterialMode,
			    StringComparison.OrdinalIgnoreCase))
			Homm3MapHexLitReboundTemplateIds.Clear();
		_mapBillboardModeConfiguredOnce = true;
		_lastConfiguredMapBillboardMaterialMode = _mapBillboardMaterialMode ?? string.Empty;
		_diagBuildLabel = buildVersionLabel ?? "?";
		_diagnosticsPath = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "esquire_diagnostics.log");
		_diagHeaderWritten = false;
		_diagLines = 0;
		_resManagerPrefixPatched = false;
		ResManagerGameObjectLaneHooks.ResetRegistrationStateForUnload();
		_pendingHarmony = null;
		_pendingClosedResManagerGet = null;
		_lastEsquireGetPath = null;
		_lastEsquireGetFrame = -1;
		EsquireUnityErrorCorrelator.SetEnabled(unityErrorCorrelator, Plugin.LogSource);
	}

	/// <summary>
	/// Applies <c>esquirePikemanMapBillboardMaterialMode</c> from launcher config when <see cref="Configure"/> is not invoked
	/// (<c>esquirePikemanVisuals=false</c>). Without this, Homm3Import map finish never sees <c>spritesDefault</c> and fog sync does not attach.
	/// Call from <see cref="Plugin.Load"/> before Homm3 hooks; <see cref="Configure"/> may run afterward and reapply the same mode.
	/// </summary>
	internal static void ApplyMapBillboardMaterialModeFromLauncher(string mapBillboardMaterialMode)
	{
		var normalized = LauncherConfigReader.NormalizeEsquireMapBillboardMaterialMode(mapBillboardMaterialMode);
		if (_mapBillboardModeConfiguredOnce
		    && !string.Equals(
			    _lastConfiguredMapBillboardMaterialMode,
			    normalized,
			    StringComparison.OrdinalIgnoreCase))
			Homm3MapHexLitReboundTemplateIds.Clear();
		_mapBillboardMaterialMode = normalized;
		_mapBillboardModeConfiguredOnce = true;
		_lastConfiguredMapBillboardMaterialMode = _mapBillboardMaterialMode ?? string.Empty;
	}

	/// <summary>Load the Esquire <see cref="AssetBundle"/> in <c>Plugin.Load</c> (A/B: compare with/without the Harmony patch).</summary>
	public static void PrewarmInPluginLoad(ManualLogSource log)
	{
		Diag("PrewarmStart", string.Empty, log);
		try
		{
			TryInit(log);
		}
		catch (Exception ex)
		{
			Diag("PrewarmException", ex.ToString(), log);
			log?.LogError("EsquirePikeman: Prewarm (Plugin.Load) failed: " + ex);
		}

		Diag(
			"PrewarmEnd",
			"battle="
			+ (_battle != null)
			+ " map="
			+ (_map != null)
			+ " battleAlive="
			+ (_battle != null && _battle)
			+ " mapAlive="
			+ (_map != null && _map),
			log);
	}

	public static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (!_applyHarmony)
		{
			log?.LogWarning("EsquirePikeman: Harmony NOT applied (esquirePikemanApplyHarmony=false).");
			Diag("RegisterSkipped", "applyHarmony=false", log);
			return;
		}

		// Do NOT use the legacy ResManager prefix/skip for all GameObject gets — it broke Map.Init.
		// Battle: dzk.bath postfix. Map stacks: often ResManager with paths like `Humans/...` (normalize to MapResPath), not UnitViewConfig.rtd().
		EsquirePikemanBattlePoolHook.TryRegister(h, log);
		ResManagerGameObjectLaneHooks.TryRegister(h, log);
		EsquirePikemanUnitViewHook.TryRegister(h, log);
		EsquireBattleAnimatorSetHook.TryRegister(h, log);
	}

	/// <summary>Adventure-map prefab loads + esquire battle SFX <c>Get&lt;GameObject&gt;</c> — normalize <paramref name="resPath"/> before comparing to <see cref="MapResPath"/>.</summary>
	public static void PostfixResGetGameObjectMapOnly(
		[HarmonyArgument(0)] string resPath,
		ref GameObject __result)
	{
		if (string.IsNullOrEmpty(resPath))
			return;
		if (TryApplyEsquireBattleSoundPrefabIfPath(resPath, ref __result))
			return;
		if (!_swapAdventureMap)
			return;
		var unitsPath = ToUnitsResPathFromSpawnPath(resPath);
		if (!string.Equals(unitsPath, MapResPath, StringComparison.Ordinal))
			return;

		VerboseLogEveryResGet(resPath);

		if (Interlocked.CompareExchange(ref _inReentrantGet, 1, 0) != 0)
		{
			Diag("PostfixMapResReentrancyBail", "path=" + SanitizeForDiag(resPath), Plugin.LogSource);
			return;
		}

		try
		{
			int frame;
			try
			{
				frame = Time.frameCount;
			}
			catch
			{
				frame = -1;
			}

			_lastEsquireGetPath = resPath;
			_lastEsquireGetFrame = frame;
			Diag(
				"PostfixMapResEnter",
				"path=" + SanitizeForDiag(resPath) + " unitsPath=" + SanitizeForDiag(unitsPath) + " frame=" + frame + " resNull=" + (__result == null),
				Plugin.LogSource);
			try
			{
				TryInit(Plugin.LogSource);
			}
			catch (Exception ex)
			{
				Diag("TryInitException", ex.ToString(), Plugin.LogSource);
				Plugin.LogSource?.LogError("EsquirePikeman: TryInit failed: " + ex);
				return;
			}

			if (!TryFinalizeMapVisualSwap(ref __result, Plugin.LogSource))
				return;
			Diag("PostfixMapResReplaced", "unitsPath=" + SanitizeForDiag(unitsPath), Plugin.LogSource);
			Plugin.LogSource?.LogInfo(
				"EsquirePikeman: ResManager map postfix replaced '"
				+ resPath
				+ "' (unitsPath="
				+ unitsPath
				+ ") template='"
				+ (__result ? __result.name : "?")
				+ "').");
		}
		finally
		{
			Interlocked.Exchange(ref _inReentrantGet, 0);
		}
	}

	/// <summary>Called at end of <see cref="TryRegister"/> (immediate) or from <see cref="EsquirePikemanDeferredPatchReg"/> (deferred).</summary>
	internal static void ApplyPendingHarmonyPrefix(ManualLogSource log, int frameWhen)
	{
		if (_resManagerPrefixPatched)
			return;
		if (_pendingHarmony == null || _pendingClosedResManagerGet == null)
		{
			log?.LogWarning("EsquirePikeman: ApplyPendingHarmonyPrefix: no pending method (unexpected).");
			return;
		}

		try
		{
			if (_resManagerPostfix)
			{
				_pendingHarmony.Patch(
					_pendingClosedResManagerGet,
					postfix: new HarmonyMethod(
						typeof(EsquirePikemanVisuals),
						nameof(PostfixResGetGameObject)));
			}
			else
			{
				// Prefix+skip: IL2CPP return slot is not touched for non-esquire Get<GameObject> calls.
				_pendingHarmony.Patch(
					_pendingClosedResManagerGet,
					prefix: new HarmonyMethod(
						typeof(EsquirePikemanVisuals),
						nameof(PrefixResGetGameObject)));
			}
		}
		catch (Exception ex)
		{
			log?.LogError(
				"EsquirePikeman: failed to apply ResManager "
				+ (_resManagerPostfix ? "postfix" : "prefix")
				+ ": "
				+ ex);
			_pendingClosedResManagerGet = null;
			_pendingHarmony = null;
			return;
		}

		_pendingClosedResManagerGet = null;
		_pendingHarmony = null;
		_resManagerPrefixPatched = true;
		int fc;
		try
		{
			fc = Time.frameCount;
		}
		catch
		{
			fc = -1;
		}

		var at = frameWhen >= 0
			? "deferred@frame" + frameWhen
			: "immediate@frame" + fc;
		var kind = _resManagerPostfix ? "postfix" : "prefix";
		log?.LogInfo(
			"EsquirePikeman: Harmony "
			+ kind
			+ " on Hex.ResManager.GameObject bmeo[GameObject](string) ("
			+ at
			+ ")");
		Diag(
			"RegisterPatched",
			"closed=ResManager bmeo[GameObject] kind=" + kind + " " + at,
			log);
	}

	private static int _inReentrantGet;

	private static void VerboseLogEveryResGet(string resPath)
	{
		if (!_verbose)
			return;
		var xx = -1;
		try
		{
			xx = Time.frameCount;
		}
		catch
		{
		}
		Diag("ResGetGameObject", "path=" + SanitizeForDiag(resPath) + " frame=" + xx, Plugin.LogSource);
	}

	/// <summary>Postfix: vanilla <c>Get</c> already ran; replace <paramref name="__result"/> for esquire paths (no skip-original).</summary>
	public static void PostfixResGetGameObject(
		[HarmonyArgument(0)] string resPath,
		ref GameObject __result)
	{
		if (string.IsNullOrEmpty(resPath))
			return;

		if (TryApplyEsquireBattleSoundPrefabIfPath(resPath, ref __result))
			return;

		VerboseLogEveryResGet(resPath);

		if (resPath != BattleResPath && resPath != MapResPath)
			return;
		if (resPath == MapResPath && !_swapAdventureMap)
			return;

		if (Interlocked.CompareExchange(ref _inReentrantGet, 1, 0) != 0)
		{
			Diag("PostfixReentrancyBail", "path=" + SanitizeForDiag(resPath), Plugin.LogSource);
			return;
		}

		try
		{
			var frame = 0;
			try
			{
				frame = Time.frameCount;
			}
			catch
			{
				frame = -1;
			}

			_lastEsquireGetPath = resPath;
			_lastEsquireGetFrame = frame;

			Diag(
				"PostfixEnter",
				"path=" + SanitizeForDiag(resPath) + " frame=" + frame + " resNullPost=" + (__result == null),
				Plugin.LogSource);
			try
			{
				TryInit(Plugin.LogSource);
			}
			catch (Exception ex)
			{
				Diag("TryInitException", ex.ToString(), Plugin.LogSource);
				Plugin.LogSource?.LogError("EsquirePikeman: TryInit failed: " + ex);
				return;
			}

			if (resPath == BattleResPath && _battle)
			{
				// __result is the game's cached asset reference — do not Destroy it.
				// Return the bundle template directly; the caller Instantiates it.
				__result = _battle;
				Diag("PostfixReplaced", "path=battle", Plugin.LogSource);
				return;
			}

			if (resPath == MapResPath && _map)
			{
				__result = _map;
				Diag("PostfixReplaced", "path=map", Plugin.LogSource);
			}
			else
			{
				Diag(
					"PostfixKeepVanilla",
					"path=" + SanitizeForDiag(resPath) + " (no template to swap)",
					Plugin.LogSource);
			}
		}
		finally
		{
			Interlocked.Exchange(ref _inReentrantGet, 0);
		}
	}

	/// <summary>
	/// Return <c>false</c> to skip the original and use <paramref name="__result"/>;
	/// <c>true</c> to run the vanilla <c>Get&lt;GameObject&gt;</c>.
	/// </summary>
	public static bool PrefixResGetGameObject(
		[HarmonyArgument(0)] string resPath,
		ref GameObject __result)
	{
		if (string.IsNullOrEmpty(resPath))
			return true;

		if (TryApplyEsquireBattleSoundPrefabIfPath(resPath, ref __result))
		{
			if (__result != null)
				return false;
			return true;
		}

		VerboseLogEveryResGet(resPath);

		if (resPath != BattleResPath && resPath != MapResPath)
			return true;
		// A/B: custom map prefab can mismatch stack/squad child indices; keep vanilla `esquire_map` when off.
		if (resPath == MapResPath && !_swapAdventureMap)
			return true;

		// Re-entrancy: TryInit/AssetBundle must not run nested inside another ResManager Get.
		if (Interlocked.CompareExchange(ref _inReentrantGet, 1, 0) != 0)
		{
			Diag("PrefixReentrancyBail", "path=" + SanitizeForDiag(resPath), Plugin.LogSource);
			return true;
		}

		var frame = 0;
		try
		{
			try
			{
				frame = Time.frameCount;
			}
			catch
			{
				frame = -1;
			}

			_lastEsquireGetPath = resPath;
			_lastEsquireGetFrame = frame;

			Diag(
				"PrefixEnter",
				"path=" + SanitizeForDiag(resPath) + " frame=" + frame + " resNullPre=" + (__result == null),
				Plugin.LogSource);
			try
			{
				TryInit(Plugin.LogSource);
			}
			catch (Exception ex)
			{
				Diag("TryInitException", ex.ToString(), Plugin.LogSource);
				Plugin.LogSource?.LogError("EsquirePikeman: TryInit failed: " + ex);
				return true;
			}

			if (resPath == BattleResPath && _battle)
			{
				__result = _battle;
				Diag("PrefixSkipOriginal", "path=battle", Plugin.LogSource);
				return false;
			}

			if (resPath == MapResPath && _map)
			{
				__result = _map;
				Diag("PrefixSkipOriginal", "path=map", Plugin.LogSource);
				return false;
			}
		}
		finally
		{
			Interlocked.Exchange(ref _inReentrantGet, 0);
		}

		Diag("PrefixRunVanilla", "path=" + SanitizeForDiag(resPath) + " (no swap — assets or bundle missing)", Plugin.LogSource);
		return true;
	}

	/// <summary>Templates can become Unity "fake null" after unload/reload; retry load instead of one-shot <c>_tried</c>.</summary>
	private static bool EsquireTemplatesAlive()
	{
		if (_battle == null || !_battle)
			return false;
		if (_swapAdventureMap && (_map == null || !_map))
			return false;
		return true;
	}

	private static void TryInit(ManualLogSource log)
	{
		if (EsquireTemplatesAlive())
		{
			Diag("TryInitNoop", "templates alive", log);
			return;
		}

		if (_bundle != null)
		{
			try
			{
				_bundle.Unload(unloadAllLoadedObjects: false);
			}
			catch (Exception ex)
			{
				Diag("TryInitStaleBundleUnload", ex.Message, log);
			}

			_bundle = null;
		}

		_battle = null;
		_map = null;
		_vanillaMapMaterialTemplate = null;
		_audioClips = null;
		_audioPlayerTypeRegistered = false;
		_clipDriverTypeRegistered = false;
		Diag("TryInitStart", "loading bundle", log);

		foreach (var p in GetBundleFileCandidates())
		{
			if (p == null || !File.Exists(p))
				continue;

			Diag("BundleCandidate", p, log);
			_bundle = AssetBundle.LoadFromFile(p);
			if (_bundle == null)
			{
				Diag("BundleLoadFromFileNull", p, log);
				continue;
			}

			_battle = _bundle.LoadAsset<GameObject>(BattleAssetName);
			_map = _bundle.LoadAsset<GameObject>(MapAssetName);
			// Adventure-map swap is optional: if it is off, a missing map prefab must not
			// discard an otherwise valid battle prefab (common when only battle was rebuilt).
			var battleOk = _battle != null;
			var mapOk = _map != null || !_swapAdventureMap;
			if (battleOk && mapOk)
			{
				log?.LogInfo("EsquirePikeman: loaded bundle from " + p);
				Diag("TryInitOk", p, log);
				IndexEsquireAudioClipsFromBundle(log);
				EnsureEsquireBattleAudioPlayerTypeRegistered(log);
				if (_swapAdventureMap && _map && MapModeIsSpritesDefault())
				{
					EnsureMapBillboardFogSyncTypeRegistered(log);
					TryAddFogSyncToMapPrefab(_map, log);
					RestoreMapFrameMaterialsToSpritesDefault(log);
				}

				return;
			}

			_battle = null;
			_map = null;
			_bundle?.Unload( unloadAllLoadedObjects: false);
			_bundle = null;
		}

		if (!_logged)
		{
			_logged = true;
			log?.LogWarning(
				"EsquirePikeman: no usable bundle. Place '" + BundleFileName
				+ "' next to OfflineUnlockMod.dll (see custom_prefab_pipeline build_out).");
			Diag("TryInitNoBundle", "see log warning", log);
		}
	}

	/// <summary>Indexed from <see cref="_bundle"/> for <see cref="EsquireBattleAudioPlayer"/> (raw clips by asset name).</summary>
	private static void IndexEsquireAudioClipsFromBundle(ManualLogSource log)
	{
		_audioClips = new Dictionary<string, AudioClip>(StringComparer.OrdinalIgnoreCase);
		if (_bundle == null)
			return;
		try
		{
			foreach (var o in _bundle.LoadAllAssets())
			{
				var clip = o == null ? null : o.TryCast<AudioClip>();
				if (!clip)
					continue;
				_audioClips[clip.name] = clip;
			}

			// LoadAllAssets() returns only top-level bundle entries; AudioClips embedded only on sound prefabs
			// (EsquireBattleSoundPrefabsBuild) are sub-assets and are skipped — harvest clips from those prefabs.
			if (_audioClips.Count == 0)
				HarvestEsquireSfxFromSoundPrefabs(_bundle, _audioClips, log);

			if (log != null && _audioClips.Count > 0)
				log.LogInfo("EsquirePikeman: indexed " + _audioClips.Count + " bundle AudioClip(s) for EsquireBattleAudioPlayer.");
			else if (log != null)
				log.LogWarning(
					"EsquirePikeman: no AudioClip entries in bundle for EsquireBattleAudioPlayer (rebuild custom_units_esquire with EsquireBattleSoundPrefabsBuild + sounds/*.wav).");

			if (Homm3UpscaledBattleSfx.TryFillEsquireClips(_audioClips, log) && log != null)
				log.LogInfo("EsquirePikeman: replaced battle SFX stems from UniverSR cache (" + _audioClips.Count + ").");
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquirePikeman: audio clip indexing failed (SFX hooks may fall back empty): " + ex.Message);
		}
	}

	/// <summary>
	/// Sound SFX ship as tiny prefabs (root <see cref="AudioSource"/> + clip). <c>LoadAllAssets</c> skips those clips;
	/// <c>GetAllAssetNames</c> is sometimes empty under IL2CPP — fall back to known Unity asset paths from the build pipeline.
	/// </summary>
	private static void HarvestEsquireSfxFromSoundPrefabs(AssetBundle bundle, Dictionary<string, AudioClip> dest, ManualLogSource log)
	{
		static void AddFromGameObject(GameObject go, Dictionary<string, AudioClip> d)
		{
			if (go == null || !go)
				return;
			AudioSource[] srcs;
			try
			{
				srcs = go.GetComponentsInChildren<AudioSource>(true);
			}
			catch
			{
				return;
			}

			if (srcs == null)
				return;
			for (var si = 0; si < srcs.Length; si++)
			{
				var src = srcs[si];
				if (src == null || !src)
					continue;
				var c = src.clip;
				if (!c)
					continue;
				var nm = c.name;
				if (string.IsNullOrEmpty(nm) || nm.IndexOf("ESQUIRE_", StringComparison.OrdinalIgnoreCase) < 0)
					continue;
				d[nm] = c;
			}
		}

		try
		{
			var names = bundle.GetAllAssetNames();
			var n = 0;
			if (names != null)
			{
				try
				{
					n = names.Length;
				}
				catch
				{
					n = 0;
				}
			}

			if (n > 0)
			{
				for (var i = 0; i < n; i++)
				{
					string path = null;
					try
					{
						path = names[i];
					}
					catch
					{
						continue;
					}

					if (string.IsNullOrEmpty(path) || !path.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
						continue;
					GameObject go = null;
					try
					{
						go = bundle.LoadAsset<GameObject>(path);
					}
					catch
					{
						continue;
					}

					AddFromGameObject(go, dest);
				}
			}

			if (dest.Count == 0)
			{
				var prefixes = new[]
				{
					"Assets/CustomUnits/esquire/sounds/",
					"assets/customunits/esquire/sounds/",
				};
				foreach (var prefix in prefixes)
				{
					foreach (var stem in EsquireBattleAudioPlayer.EnumerateExpectedSfxStems())
					{
						var path = prefix + stem + ".prefab";
						try
						{
							var go = bundle.LoadAsset<GameObject>(path);
							AddFromGameObject(go, dest);
						}
						catch
						{
							// ignore missing path
						}
					}
				}
			}

			if (dest.Count == 0 && log != null && n > 0)
			{
				var sample = new System.Text.StringBuilder(256);
				var max = Math.Min(n, 12);
				for (var i = 0; i < max; i++)
				{
					try
					{
						if (i > 0)
							sample.Append("; ");
						sample.Append(names[i]);
					}
					catch
					{
						break;
					}
				}

				log.LogWarning("EsquirePikeman: bundle has " + n + " asset name(s) but no ESQUIRE_* AudioClip on prefabs. First entries: " + sample);
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquirePikeman: sound-prefab clip harvest failed: " + ex.Message);
		}
	}

	internal static bool TryGetEsquireAudioClip(string stem, out AudioClip clip)
	{
		clip = null;
		if (string.IsNullOrEmpty(stem) || _audioClips == null)
			return false;
		return _audioClips.TryGetValue(stem, out clip) && clip;
	}

	/// <summary>Il2Cpp inject for <see cref="EsquireBattleAudioPlayer"/>; safe to call before every <c>AddComponent</c>.</summary>
	internal static void EnsureEsquireBattleAudioPlayerTypeRegistered(ManualLogSource log)
	{
		if (_audioPlayerTypeRegistered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<EsquireBattleAudioPlayer>();
			_audioPlayerTypeRegistered = true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquirePikeman: EsquireBattleAudioPlayer Il2Cpp register failed: " + ex.Message);
		}
	}

	internal static void EnsureEsquireBattleClipAudioDriverTypeRegistered(ManualLogSource log)
	{
		if (_clipDriverTypeRegistered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<EsquireBattleClipAudioDriver>();
			_clipDriverTypeRegistered = true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquirePikeman: EsquireBattleClipAudioDriver Il2Cpp register failed: " + ex.Message);
		}
	}

	/// <summary>
	/// <c>hexLitVanilla</c>: clone <see cref="_vanillaMapMaterialTemplate"/> onto materials used only by this esquire
	/// <c>map.prefab</c> mesh renderers. Do <b>not</b> scan <see cref="Resources.FindObjectsOfTypeAll"/> for <c>map_frame_*</c> —
	/// that mutates every loaded asset with those names (other HoMM3 bundles, wrong order) and corrupts the map/FoW view.
	/// Il2CppInterop: assign <c>shader</c>, <c>CopyPropertiesFromMaterial</c>, mirror keywords/renderQueue, restore
	/// <c>_MainTex</c>, clear <c>_HexFade</c>, <see cref="SanitizeMapMaterialForHoMm3QuadBillboard"/>.
	/// </summary>
	private static void RebindMapBundleMaterialsToVanillaTemplate(GameObject esquireMapPrefab, ManualLogSource log)
	{
		if (esquireMapPrefab == null || !_vanillaMapMaterialTemplate)
			return;
		try
		{
			var donor = _vanillaMapMaterialTemplate;
			string postSanitizeKwSample = null;
			var n = RebindMapRenderersClonedToDonor(esquireMapPrefab, donor, ref postSanitizeKwSample);

			var tShader = donor.shader;
			var tKw = donor.shaderKeywords;
			log?.LogInfo(
				"EsquirePikeman: cloned vanilla map donor onto "
				+ n
				+ " material slot(s) on esquire map prefab; template shader="
				+ (tShader ? tShader.name : "(null)")
				+ " keywords=["
				+ (tKw != null ? string.Join(",", tKw) : string.Empty)
				+ "] (FoW + lighting + outline).");
			if (!string.IsNullOrEmpty(postSanitizeKwSample))
				log?.LogInfo("EsquirePikeman: first rebound material keywords after sanitize=[" + postSanitizeKwSample + "]");
			Diag("MapVanillaCloneRebound", "count=" + n, log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquirePikeman: vanilla map material clone failed: " + ex);
			Diag("MapVanillaCloneException", ex.ToString(), log);
		}
	}

	/// <summary>
	/// Lane B <c>hexLitVanilla</c>: clone the <b>swapped unit’s</b> stock map prefab material onto the HoMM3 bundle mesh
	/// (same pipeline as <see cref="RebindMapBundleMaterialsToVanillaTemplate"/>, but donor = griffin/swordsman vanilla, not esquire).
	/// </summary>
	internal static void TryRebindHomm3MapMaterialsFromVanilla(GameObject vanillaMapPrefab, GameObject homm3Template, ManualLogSource log)
	{
		TryRebindHomm3MapMaterialsFromVanilla(vanillaMapPrefab, homm3Template, null, log);
	}

	/// <summary>
	/// Same as <see cref="TryRebindHomm3MapMaterialsFromVanilla(GameObject, GameObject, ManualLogSource)"/>, plus scoped
	/// <c>map_frame_*</c> material assets from the HoMM3 bundle. The animator swaps those assets every frame, so rebinding
	/// only the renderer's current slot lets the next animation tick restore corrupted/unfogged materials.
	/// </summary>
	internal static void TryRebindHomm3MapMaterialsFromVanilla(
		GameObject vanillaMapPrefab,
		GameObject homm3Template,
		IEnumerable<Material> scopedFrameMaterials,
		ManualLogSource log)
	{
		if (MapModeIsSpritesDefault() || vanillaMapPrefab == null || homm3Template == null)
			return;
		var templateId = homm3Template.GetInstanceID();
		var templateAlreadyRebound = Homm3MapHexLitReboundTemplateIds.Contains(templateId);
		if (templateAlreadyRebound && scopedFrameMaterials == null)
			return;
		if (!TryFindHomm3MapDonorMaterialFromVanilla(vanillaMapPrefab, log, out var donor) || !donor)
		{
			log?.LogWarning("Homm3Import: hexLitVanilla map rebind skipped — no donor material on vanilla map prefab.");
			return;
		}
		TryEnsureHomm3MapMaterialSync(homm3Template, donor, log);
		LogHomm3MapRendererDiag(homm3Template, donor, templateAlreadyRebound, log);

		try
		{
			string postSanitizeKwSample = null;
			var frameN = RebindScopedMapFrameMaterialsToDonor(scopedFrameMaterials, donor, ref postSanitizeKwSample);
			var n = templateAlreadyRebound
				? 0
				: RebindMapRenderersClonedToDonor(homm3Template, donor, ref postSanitizeKwSample);

			if (n > 0 || frameN > 0)
				Homm3MapHexLitReboundTemplateIds.Add(templateId);

			LogHomm3MapMaterialResultDiag(homm3Template, donor, postSanitizeKwSample, log);

			log?.LogInfo(
				"Homm3Import: hexLitVanilla rebound "
				+ n
				+ " renderer material slot(s), "
				+ frameN
				+ " scoped frame material asset(s) from vanilla donor shader="
				+ (donor.shader ? donor.shader.name : "(null)")
				+ ".");
			if (!string.IsNullOrEmpty(postSanitizeKwSample))
				log?.LogInfo("Homm3Import: first rebound map material keywords after sanitize=[" + postSanitizeKwSample + "]");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: vanilla donor map material rebind failed: " + ex);
		}
	}

	/// <summary>
	/// Clone each map renderer slot to a new <see cref="Material"/> before rebinding — never mutate AssetBundle assets in place.
	/// </summary>
	private static int RebindMapRenderersClonedToDonor(GameObject root, Material donor, ref string postSanitizeKwSample)
	{
		if (root == null || !donor)
			return 0;
		var n = 0;
		foreach (var r in root.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			var mats = r.sharedMaterials;
			if (mats == null || mats.Length == 0)
				continue;
			var copy = new Material[mats.Length];
			for (var i = 0; i < mats.Length; i++)
			{
				var m = mats[i];
				if (!m)
					continue;
				if (Homm3ImportVisuals.IsHomm3MapArrayBillboardMaterial(m))
				{
					copy[i] = m;
					continue;
				}
				var inst = new Material(m);
				RebindOneMapMaterialToDonor(inst, donor);
				copy[i] = inst;
				n++;
				if (postSanitizeKwSample == null && inst.shaderKeywords != null && inst.shaderKeywords.Length > 0)
					postSanitizeKwSample = string.Join(",", inst.shaderKeywords);
			}

			r.sharedMaterials = copy;
		}

		return n;
	}

	private static void LogHomm3MapRendererDiag(GameObject root, Material donor, bool templateAlreadyRebound, ManualLogSource log)
	{
		if (!_verbose || !root || _homm3MapRendererDiagRemaining <= 0)
			return;
		_homm3MapRendererDiagRemaining--;
		try
		{
			var meshCount = root.GetComponentsInChildren<MeshRenderer>(true).Length;
			var spriteCount = root.GetComponentsInChildren<SpriteRenderer>(true).Length;
			var allCount = root.GetComponentsInChildren<Renderer>(true).Length;
			var first = root.GetComponentInChildren<Renderer>(true);
			var fm = first ? first.sharedMaterial : null;
			log?.LogInfo(
				"Homm3Import: map renderer diag root='"
				+ (root.name ?? "?")
				+ "' renderers="
				+ allCount
				+ " mesh="
				+ meshCount
				+ " sprite="
				+ spriteCount
				+ " alreadyRebound="
				+ templateAlreadyRebound
				+ " firstType="
				+ (first != null ? first.GetType().Name : "(none)")
				+ " firstMat='"
				+ (fm ? fm.name : "(null)")
				+ "' firstShader="
				+ (fm && fm.shader ? fm.shader.name : "(null)")
				+ " donorQueue="
				+ (donor ? donor.renderQueue : -1)
				+ " firstShadow="
				+ (first != null ? first.shadowCastingMode.ToString() : "?")
				+ " donor='"
				+ (donor ? donor.name : "(null)")
				+ "' donorShader="
				+ (donor && donor.shader ? donor.shader.name : "(null)")
				+ " donorKeywords=["
				+ (donor && donor.shaderKeywords != null ? string.Join(",", donor.shaderKeywords) : string.Empty)
				+ "]"
				+ ".");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: map renderer diag failed: " + ex.Message);
		}
	}

	private static void LogHomm3MapMaterialResultDiag(GameObject root, Material donor, string postSanitizeKwSample, ManualLogSource log)
	{
		if (!_verbose || !root || _homm3MapMaterialResultDiagRemaining <= 0)
			return;
		_homm3MapMaterialResultDiagRemaining--;
		try
		{
			var first = root.GetComponentInChildren<Renderer>(true);
			var mat = first ? first.sharedMaterial : null;
			log?.LogInfo(
				"Homm3Import: map material result diag donor=["
				+ DescribeMaterialForRuntimeSync(donor)
				+ "] firstFinal=["
				+ DescribeMaterialForRuntimeSync(mat)
				+ "] sampleKeywordsAfterSanitize=["
				+ (postSanitizeKwSample ?? string.Empty)
				+ "].");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: map material result diag failed: " + ex.Message);
		}
	}

	private static int RebindScopedMapFrameMaterialsToDonor(
		IEnumerable<Material> scopedFrameMaterials,
		Material donor,
		ref string postSanitizeKwSample)
	{
		if (scopedFrameMaterials == null || !donor)
			return 0;
		var n = 0;
		foreach (var m in scopedFrameMaterials)
		{
			if (!IsHomm3MapFrameMaterial(m))
				continue;
			var id = m.GetInstanceID();
			if (!Homm3MapHexLitReboundMaterialIds.Add(id))
				continue;
			RebindOneMapMaterialToDonor(m, donor);
			n++;
			if (postSanitizeKwSample == null && m.shaderKeywords != null && m.shaderKeywords.Length > 0)
				postSanitizeKwSample = string.Join(",", m.shaderKeywords);
		}

		return n;
	}

	internal static bool TryFindHomm3MapDonorMaterialFromVanilla(GameObject vanillaMapPrefab, ManualLogSource log, out Material donor)
	{
		donor = null;
		if (TryFindBestHexLitMapMaterialOnTree(vanillaMapPrefab, log, out var hexLit) && hexLit)
		{
			donor = hexLit;
			return true;
		}

		var meshDonor = EsquireBattleVisualPresentation.TryFindDominantRenderable(vanillaMapPrefab);
		if (meshDonor != null && IsHexLitMaterial(meshDonor.sharedMaterial))
		{
			donor = meshDonor.sharedMaterial;
			return true;
		}

		if (TryFindDominantSpriteMapMaterial(vanillaMapPrefab, out var spriteMat) && IsHexLitMaterial(spriteMat))
		{
			donor = spriteMat;
			return true;
		}

		if (_vanillaMapMaterialTemplate)
		{
			donor = _vanillaMapMaterialTemplate;
			if (!_loggedHomm3EsquireDonorFallback)
			{
				_loggedHomm3EsquireDonorFallback = true;
				log?.LogInfo(
					"Homm3Import: hexLitVanilla donor fallback = Esquire map template material (cross-unit) when vanilla has no mesh/sprite Hex/Lit donor.");
			}

			return true;
		}

		if (meshDonor != null && meshDonor.sharedMaterial)
		{
			donor = meshDonor.sharedMaterial;
			log?.LogWarning(
				"Homm3Import: hexLitVanilla donor fallback is not Hex/Lit (shader="
				+ (donor.shader ? donor.shader.name : "(null)")
				+ "); fog may be incomplete.");
			return true;
		}

		if (spriteMat)
		{
			donor = spriteMat;
			log?.LogWarning(
				"Homm3Import: hexLitVanilla sprite donor fallback is not Hex/Lit (shader="
				+ (donor.shader ? donor.shader.name : "(null)")
				+ "); fog may be incomplete.");
			return true;
		}

		return false;
	}

	private static bool TryFindDominantSpriteMapMaterial(GameObject vanilla, out Material mat)
	{
		mat = null;
		if (!vanilla)
			return false;
		var best = -1f;
		foreach (var sr in vanilla.GetComponentsInChildren<SpriteRenderer>(true))
		{
			if (!sr || !sr.enabled)
				continue;
			var sm = sr.sharedMaterial;
			if (!sm)
				continue;
			var sqr = sr.bounds.size.sqrMagnitude;
			if (sqr <= best)
				continue;
			best = sqr;
			mat = sm;
		}

		return mat;
	}

	private static bool TryFindBestHexLitMapMaterialOnTree(GameObject vanilla, ManualLogSource log, out Material mat)
	{
		mat = null;
		if (!vanilla)
			return false;
		var bestScore = float.NegativeInfinity;
		Renderer bestRenderer = null;
		foreach (var r in vanilla.GetComponentsInChildren<Renderer>(true))
		{
			if (!r)
				continue;
			var sm = r.sharedMaterial;
			if (!sm || !sm.shader)
				continue;
			var sn = sm.shader.name;
			if (string.IsNullOrEmpty(sn))
				continue;
			if (sn.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			float score;
			try
			{
				score = ScoreHexLitMapDonor(r, sm);
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3Import: Hex/Lit donor scoring skipped one renderer: " + ex.Message);
				score = 0f;
			}
			if (score <= bestScore)
				continue;
			bestScore = score;
			bestRenderer = r;
			mat = sm;
		}

		if (mat && _verbose)
		{
			var kw = mat.shaderKeywords;
			log?.LogInfo(
				"Homm3Import: selected Hex/Lit donor mat='"
				+ mat.name
				+ "' renderer="
				+ (bestRenderer != null ? bestRenderer.GetType().Name : "?")
				+ " score="
				+ bestScore.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " queue="
				+ mat.renderQueue
				+ " keywords=["
				+ (kw != null ? string.Join(",", kw) : string.Empty)
				+ "].");
		}

		return mat;
	}

	private static float ScoreHexLitMapDonor(Renderer r, Material m)
	{
		var score = 0f;
		if (r && r.enabled)
			score += 1000f;
		if (r)
		{
			var sqr = r.bounds.size.sqrMagnitude;
			score += (sqr < 100000f ? sqr : 100000f) * 0.01f;
		}
		if (m)
		{
			if (m.renderQueue is >= 2000 and <= 2500)
				score += 250f;
			if (HasMaterialKeyword(m, "HEX_DITHER_FADE_ENABLED"))
				score += 400f;
			if (HasMaterialKeyword(m, "HEX_ALPHA_CLIP_ENABLED"))
				score += 300f;
			if (HasMaterialKeyword(m, "HEX_EMISSION_MAP_ENABLED"))
				score += 50f;
			if (HasMaterialKeyword(m, "_EMISSION"))
				score -= 100f;
			if (HasMaterialKeyword(m, "_SEGMENTED_ON"))
				score -= 250f;
			if (HasMaterialKeyword(m, "_SMOOTHFROMMAPSWITCH_ON"))
				score -= 250f;
		}

		return score;
	}

	private static bool HasMaterialKeyword(Material m, string keyword)
	{
		if (!m || string.IsNullOrEmpty(keyword))
			return false;
		var kws = m.shaderKeywords;
		if (kws == null)
			return false;
		for (var i = 0; i < kws.Length; i++)
			if (string.Equals(kws[i], keyword, StringComparison.Ordinal))
				return true;
		return false;
	}

	private static bool IsHexLitMaterial(Material m)
	{
		if (!m || !m.shader)
			return false;
		var sn = m.shader.name;
		return !string.IsNullOrEmpty(sn)
		       && sn.IndexOf("Hex/Lit", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	/// <summary>
	/// The game's own Hex/Lit (5 passes: forward, fog, shadow caster...). Owned lab bundles ship a
	/// 1-pass stub also named "Hex/Lit" with no fog keywords or shadow caster; cloning it as a donor
	/// loses adventure-map fog and shadows, so the name alone is never native identity.
	/// </summary>
	internal static bool IsNativeHexLitShader(Shader shader)
	{
		return shader
		       && shader.isSupported
		       && string.Equals(shader.name, "Hex/Lit", StringComparison.Ordinal)
		       && shader.passCount > 1;
	}

	internal static bool TryFindLoadedUnitStyleHexLitMapDonor(ManualLogSource log, out Material donor)
	{
		donor = null;
		var bestScore = float.NegativeInfinity;
		try
		{
			var materials = Resources.FindObjectsOfTypeAll<Material>();
			for (var i = 0; materials != null && i < materials.Length; i++)
			{
				var m = materials[i];
				if (!m || !IsHexLitMaterial(m))
					continue;
				var score = ScoreLoadedUnitStyleHexLitMapDonor(m);
				if (score <= bestScore)
					continue;
				bestScore = score;
				donor = m;
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: loaded Hex/Lit unit-style donor scan failed: " + ex.Message);
		}

		return donor && bestScore > 0f;
	}

	private static float ScoreLoadedUnitStyleHexLitMapDonor(Material material)
	{
		if (!material)
			return float.NegativeInfinity;
		var name = material.name ?? string.Empty;
		var score = 0f;
		if (material.renderQueue is >= 2000 and <= 2500)
			score += 200f;
		if (HasMaterialKeyword(material, "HEX_DITHER_FADE_ENABLED"))
			score += 500f;
		if (HasMaterialKeyword(material, "HEX_ALPHA_CLIP_ENABLED"))
			score += 350f;
		if (HasMaterialKeyword(material, "HEX_BLEND_INTO_TERRAIN_POSITION")
		    || HasMaterialKeyword(material, "HEX_BLEND_INTO_TERRAIN_COLOR"))
			score -= 1000f;
		if (ContainsAnyMapDonorNameToken(name, "troglodyte", "pet_", "minos", "medusa", "hydra", "gremlin", "pikeman"))
			score += 650f;
		if (ContainsAnyMapDonorNameToken(name, "byzantine", "palace", "city", "building", "terrain", "ground", "water"))
			score -= 800f;
		if (!HasAnyMainTextureForMapDonor(material))
			score -= 200f;
		// The installed Hex/Lit declares no _BumpMap/_NormalMap/_MetallicGlossMap
		// (docs/homm3_prebaked_lighting.md); requiring them rejected every loaded donor.
		if (!material.HasProperty("_MainTex"))
			return float.NegativeInfinity;
		if (!IsNativeHexLitShader(material.shader))
			return float.NegativeInfinity;
		return score;
	}

	private static bool ContainsAnyMapDonorNameToken(string value, params string[] needles)
	{
		if (string.IsNullOrEmpty(value) || needles == null)
			return false;
		for (var i = 0; i < needles.Length; i++)
			if (!string.IsNullOrEmpty(needles[i]) && value.IndexOf(needles[i], StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		return false;
	}

	private static bool HasAnyMainTextureForMapDonor(Material material)
	{
		if (!material)
			return false;
		try
		{
			if (material.HasProperty("_MainTex") && material.GetTexture("_MainTex"))
				return true;
		}
		catch { }
		return material.mainTexture;
	}

	private static bool IsHomm3MapFrameMaterial(Material m)
	{
		return m
		       && !string.IsNullOrEmpty(m.name)
		       && (m.name.StartsWith("map_frame_", StringComparison.Ordinal)
		           || m.name.StartsWith("homm3_frame_", StringComparison.Ordinal));
	}

	internal static bool IsHomm3MapFrameMaterialForRuntimeSync(Material m) => IsHomm3MapFrameMaterial(m);

	internal static bool IsHexLitMaterialForRuntimeSync(Material m) => IsHexLitMaterial(m);

	internal static Material CloneHomm3MapFrameMaterialForRuntimeSync(Material source, Material donor)
	{
		if (!source || !donor)
			return null;
		var clone = new Material(source)
		{
			name = "HOMM3_map_hexlit_" + source.name
		};
		RebindOneMapMaterialToDonor(clone, donor);
		return clone;
	}

	internal static Material CreateSanitizedHexLitMapBillboardMaterial(
		Material donor,
		Texture mainTexture,
		string materialName,
		bool keepRevealed = false)
	{
		if (!donor || !mainTexture)
			return null;
		var clone = new Material(donor)
		{
			name = string.IsNullOrWhiteSpace(materialName) ? "HOMM3_map_hexlit_billboard" : materialName
		};
		if (clone.HasProperty("_MainTex"))
			clone.SetTexture("_MainTex", mainTexture);
		else
			clone.mainTexture = mainTexture;
		RebindOneMapMaterialToDonor(clone, donor, keepRevealed);
		return clone;
	}

	/// <summary>
	/// HoMM3 quad billboard: clone donor <c>Hex/Lit</c> so fog/lighting match vanilla, restore flip-book <c>_MainTex</c>,
	/// then strip skinned-mesh keywords/maps (<c>CopyPropertiesFromMaterial</c> pulls normals/spec keywords that paint garbage on a single quad).
	/// </summary>
	private static void RebindOneMapMaterialToDonor(Material m, Material donor, bool keepRevealed = false)
	{
		if (!m || !donor)
			return;
		var tex = m.HasProperty("_MainTex") ? m.GetTexture("_MainTex") : m.mainTexture;

		m.shader = donor.shader;
		m.CopyPropertiesFromMaterial(donor);

		var clearKw = m.shaderKeywords;
		if (clearKw != null)
		{
			foreach (var kw in clearKw)
			{
				if (!string.IsNullOrEmpty(kw))
					m.DisableKeyword(kw);
			}
		}

		var addKw = donor.shaderKeywords;
		if (addKw != null)
		{
			foreach (var kw in addKw)
			{
				if (!string.IsNullOrEmpty(kw))
					m.EnableKeyword(kw);
			}
		}

		SetMapBillboardMainTextureSlots(m, tex);

		ForceHexLitMapBillboardCutoutState(m, donor);

		SanitizeMapMaterialForHoMm3QuadBillboard(m);
		NullNonMainTextureSlotsForShader(m);
		SetMapBillboardMainTextureSlots(m, tex);
		StripKeywordsExceptHexFogAndAlphaCutout(m);
		FinalizeHexLitMapBillboardMaterial(m, donor, keepRevealed);
	}

	/// <summary>
	/// Map billboards must write depth and stay fully faded-in over terrain/water tiles. Donor <c>Hex/Lit</c>
	/// materials copied from city meshes can leave <c>_ZWrite</c> off or volatile fade state that makes the color
	/// pass disappear wherever water still wins the depth test behind the quad.
	/// </summary>
	/// <param name="keepRevealed">
	/// When true, force <c>_HexFade=1</c> for coastal custom-town billboards that must stay visible over water.
	/// Adventure-map units must pass false so fog-of-war can hide the HoMM3 quad via the native shell driver.
	/// </param>
	internal static void FinalizeHexLitMapBillboardMaterial(Material m, Material donor, bool keepRevealed = false)
	{
		if (!m)
			return;

		if (keepRevealed && m.HasProperty("_HexFade"))
			m.SetFloat("_HexFade", 1f);
		if (m.HasProperty("_ZWrite"))
			m.SetFloat("_ZWrite", 1f);
		if (m.HasProperty("_ZTest"))
			m.SetFloat("_ZTest", (float)CompareFunction.LessEqual);

		if (m.HasProperty("_EmissionTex"))
			m.SetTexture("_EmissionTex", null);
		if (m.HasProperty("_EmissionColor"))
			m.SetColor("_EmissionColor", Color.black);
		try { m.DisableKeyword("HEX_EMISSION_MAP_ENABLED"); } catch { }
		try { m.DisableKeyword("_EMISSION"); } catch { }

		var donorQueue = donor ? donor.renderQueue : -1;
		var queue = donorQueue is >= 2000 and <= 2500 ? donorQueue : 2450;
		// Stay in the alpha-tested map bucket, but render after most opaque terrain/water geometry.
		m.renderQueue = Mathf.Clamp(Mathf.Max(queue, 2460), 2450, 2499);
	}

	private static readonly string[] MapBillboardMainTexturePropertyNames =
	{
		"_MainTex",
		"_BaseMap",
		"_BaseColorMap",
		"_AlbedoMap",
		"_DiffuseMap",
		"_MainTexture"
	};

	private static void SetMapBillboardMainTextureSlots(Material m, Texture tex)
	{
		if (!m || !tex)
			return;
		for (var i = 0; i < MapBillboardMainTexturePropertyNames.Length; i++)
		{
			var prop = MapBillboardMainTexturePropertyNames[i];
			if (m.HasProperty(prop))
			{
				m.SetTexture(prop, tex);
				m.SetTextureScale(prop, Vector2.one);
				m.SetTextureOffset(prop, Vector2.zero);
			}
		}
		m.mainTexture = tex;
		m.mainTextureScale = Vector2.one;
		m.mainTextureOffset = Vector2.zero;
	}

	private static void ForceHexLitMapBillboardCutoutState(Material m, Material donor)
	{
		if (!m)
			return;

		m.EnableKeyword("HEX_DITHER_FADE_ENABLED");
		m.EnableKeyword("HEX_ALPHA_CLIP_ENABLED");
		m.EnableKeyword("_ALPHATEST_ON");

		if (m.HasProperty("_AlphaClip"))
			m.SetFloat("_AlphaClip", 1f);
		if (m.HasProperty("_AlphaCutoff"))
			m.SetFloat("_AlphaCutoff", 0.05f);
		if (m.HasProperty("_Cutoff"))
			m.SetFloat("_Cutoff", 0.05f);
		if (m.HasProperty("_AlphaClipThreshold"))
			m.SetFloat("_AlphaClipThreshold", 0.05f);

		// Queue/depth finalized in FinalizeHexLitMapBillboardMaterial so coastal water cannot win over the quad.
	}

	private static readonly string[] MapBillboardSecondaryTexturePropertyNames =
	{
		"_BumpMap",
		"_NormalMap",
		"_MetallicGlossMap",
		"_SpecGlossMap",
		"_OcclusionMap",
		"_ParallaxMap",
		"_EmissionMap",
		"_DetailAlbedoMap",
		"_DetailNormalMap",
		"_DetailMask",
		"_MetallicSpecGlossMap",
		"_ClearCoatMap",
		"_TranslucencyMap",
		"_SpecMap",
		"_GlossMap",
	};

	/// <summary>
	/// Opaque adventure-map mesh (Tower Meshy castle pilot): keep Hex/Lit fog/lighting and allow normals,
	/// but strip terrain-blend / flag displacement that warps a free-standing mesh into the ground.
	/// Does not clear <c>_BumpMap</c> — callers assign albedo/normal after this.
	/// </summary>
	internal static void SanitizeMapMaterialForOpaqueMesh(Material m)
	{
		if (!m)
			return;
		if (m.HasProperty("_Color"))
			m.SetColor("_Color", Color.white);
		if (m.HasProperty("_EmissionColor"))
			m.SetColor("_EmissionColor", Color.black);
		if (m.HasProperty("_VertexDisplacementType"))
			m.SetFloat("_VertexDisplacementType", 0f);
		if (m.HasProperty("_FlagPower"))
			m.SetVector("_FlagPower", Vector4.zero);
		if (m.HasProperty("_FlagDirection"))
			m.SetVector("_FlagDirection", Vector4.zero);
		if (m.HasProperty("_FlagSpeed"))
			m.SetFloat("_FlagSpeed", 0f);
		if (m.HasProperty("_MainTex_ST"))
			m.SetVector("_MainTex_ST", new Vector4(1f, 1f, 0f, 0f));

		var kw = m.shaderKeywords;
		if (kw == null || kw.Length == 0)
			return;
		var snapshot = new string[kw.Length];
		Array.Copy(kw, snapshot, kw.Length);
		foreach (var k in snapshot)
		{
			if (string.IsNullOrEmpty(k))
				continue;
			if (string.Equals(k, "HEX_BLEND_INTO_TERRAIN_POSITION", StringComparison.Ordinal)
			    || string.Equals(k, "HEX_BLEND_INTO_TERRAIN_COLOR", StringComparison.Ordinal)
			    || string.Equals(k, "HEX_VERTEX_DISPLACEMENT_FLAG", StringComparison.Ordinal)
			    || string.Equals(k, "HEX_EMISSION_MAP_ENABLED", StringComparison.Ordinal))
			{
				m.DisableKeyword(k);
			}
		}
	}

	/// <summary>
	/// <c>Esquire_mat</c> assigns normal/spec/emission/detail maps for a skinned body. A billboard uses UV0 over the whole quad; those
	/// textures sample noise → glitchy halos. Keep donor Hex/Lit feature keywords for FoW/lighting/selection, but drop
	/// standard Unity map keywords for the texture slots we clear.
	/// </summary>
	private static void SanitizeMapMaterialForHoMm3QuadBillboard(Material m)
	{
		if (!m)
			return;
		foreach (var prop in MapBillboardSecondaryTexturePropertyNames)
		{
			if (m.HasProperty(prop))
				m.SetTexture(prop, null);
		}

		if (m.HasProperty("_Metallic"))
			m.SetFloat("_Metallic", 0f);
		if (m.HasProperty("_Glossiness"))
			m.SetFloat("_Glossiness", 0f);
		if (m.HasProperty("_Smoothness"))
			m.SetFloat("_Smoothness", 0f);
		if (m.HasProperty("_OcclusionStrength"))
			m.SetFloat("_OcclusionStrength", 0f);
		if (m.HasProperty("_MainTex_ST"))
			m.SetVector("_MainTex_ST", new Vector4(1f, 1f, 0f, 0f));
		if (m.HasProperty("_Color"))
			m.SetColor("_Color", Color.white);
		if (m.HasProperty("_EmissionColor"))
			m.SetColor("_EmissionColor", Color.black);
		if (m.HasProperty("_VertexDisplacementType"))
			m.SetFloat("_VertexDisplacementType", 0f);
		if (m.HasProperty("_FlagPower"))
			m.SetVector("_FlagPower", Vector4.zero);
		if (m.HasProperty("_FlagDirection"))
			m.SetVector("_FlagDirection", Vector4.zero);
		if (m.HasProperty("_FlagSpeed"))
			m.SetFloat("_FlagSpeed", 0f);

		var kw = m.shaderKeywords;
		if (kw == null || kw.Length == 0)
			return;
		var snapshot = new string[kw.Length];
		Array.Copy(kw, snapshot, kw.Length);
		foreach (var k in snapshot)
		{
			if (string.IsNullOrEmpty(k) || k.StartsWith("HEX_", StringComparison.Ordinal))
				continue;
			if (k == "_EMISSION"
			    || k == "_SEGMENTED_ON"
			    || k == "_SMOOTHFROMMAPSWITCH_ON"
			    || k == "_NORMALMAP"
			    || k == "_METALLICGLOSSMAP"
			    || k == "_SPECGLOSSMAP"
			    || k == "_PARALLAXMAP"
			    || k == "_DETAIL_MULX2"
			    || k == "_DETAIL"
			    || k == "_CLEARCOAT")
				m.DisableKeyword(k);
		}
	}

	/// <summary>
	/// Clears every <see cref="ShaderPropertyType.Texture"/> slot on <paramref name="m"/>.shader except <c>_MainTex</c>
	/// (PBR/detail maps from a skinned donor still sample the quad’s UV0 and look like static/corruption).
	/// </summary>
	private static void NullNonMainTextureSlotsForShader(Material m)
	{
		if (!m || !m.shader)
			return;
		try
		{
			var zj = m.shader;
			var n = zj.GetPropertyCount();
			for (var i = 0; i < n; i++)
			{
				if (zj.GetPropertyType(i) != ShaderPropertyType.Texture)
					continue;
				var propName = zj.GetPropertyName(i);
				if (IsMapBillboardMainTextureProperty(propName))
					continue;
				if (m.HasProperty(propName))
					m.SetTexture(propName, null);
			}
		}
		catch
		{
			// Older Unity / stripped shader API — SanitizeMapMaterialForHoMm3QuadBillboard list already cleared common slots.
		}
	}

	/// <summary>
	/// After donor clone, only <c>HEX_*</c> fog keywords plus alpha/cutout variants should remain — everything else came from Esquire body mats.
	/// </summary>
	private static bool IsMapBillboardMainTextureProperty(string propName)
	{
		if (string.IsNullOrEmpty(propName))
			return false;
		for (var i = 0; i < MapBillboardMainTexturePropertyNames.Length; i++)
			if (string.Equals(propName, MapBillboardMainTexturePropertyNames[i], StringComparison.Ordinal))
				return true;
		return false;
	}

	private static void StripKeywordsExceptHexFogAndAlphaCutout(Material m)
	{
		if (!m)
			return;
		var kw = m.shaderKeywords;
		if (kw == null || kw.Length == 0)
			return;
		var snapshot = new string[kw.Length];
		Array.Copy(kw, snapshot, kw.Length);
		foreach (var k in snapshot)
		{
			if (string.IsNullOrEmpty(k))
				continue;
			if (ShouldKeepKeywordForHexLitMapBillboard(k))
				continue;
			m.DisableKeyword(k);
		}
	}

	private static bool ShouldKeepKeywordForHexLitMapBillboard(string k)
	{
		// Native flag/building materials can animate vertices through Hex/Lit. A HoMM3 map
		// billboard is a single upright quad, so any inherited displacement makes the whole
		// town/unit cutout drift instead of animating source geometry.
		if (string.Equals(k, "HEX_VERTEX_DISPLACEMENT_FLAG", StringComparison.Ordinal))
			return false;
		if (string.Equals(k, "HEX_EMISSION_MAP_ENABLED", StringComparison.Ordinal))
			return false;
		// Native city meshes can blend their lower geometry into terrain by world position or vertex color.
		// On a single upright HoMM3 quad this paints/distorts the bottom of the sprite.
		if (string.Equals(k, "HEX_BLEND_INTO_TERRAIN_POSITION", StringComparison.Ordinal)
		    || string.Equals(k, "HEX_BLEND_INTO_TERRAIN_COLOR", StringComparison.Ordinal))
			return false;
		if (k.StartsWith("HEX_", StringComparison.Ordinal))
			return true;
		if (k.IndexOf("ALPHA", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		if (k.IndexOf("CUTOUT", StringComparison.OrdinalIgnoreCase) >= 0
		    || k.IndexOf("ALPHATEST", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		return false;
	}

	internal static string DescribeMaterialForRuntimeSync(Material m)
	{
		if (!m)
			return "(null)";
		var kw = m.shaderKeywords;
		return "name='"
		       + (m.name ?? "?")
		       + "' shader="
		       + (m.shader ? m.shader.name : "(null)")
		       + " queue="
		       + m.renderQueue
		       + " keywords=["
		       + (kw != null ? string.Join(",", kw) : string.Empty)
		       + "]";
	}

	private static string SanitizeForDiag(string s)
	{
		if (string.IsNullOrEmpty(s))
			return string.Empty;
		return s.Replace("\r", " ").Replace("\n", " ").Replace("\t", " ");
	}

	private static void CloseDiagWriter()
	{
		lock (DiagFileLock)
		{
			if (_diagStreamWriter != null)
			{
				try
				{
					_diagStreamWriter.Flush();
					_diagStreamWriter.Dispose();
				}
				catch
				{
				}
				_diagStreamWriter = null;
			}
		}
	}

	private static void EnsureDiagWriterUnlocked()
	{
		if (_diagStreamWriter != null)
			return;
		if (string.IsNullOrEmpty(_diagnosticsPath))
			_diagnosticsPath = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "esquire_diagnostics.log");
		var dlv = Path.GetDirectoryName(_diagnosticsPath);
		if (!string.IsNullOrEmpty(dlv) && !Directory.Exists(dlv))
		{
			Directory.CreateDirectory(dlv);
		}
		var fs = new FileStream(_diagnosticsPath, FileMode.Append, FileAccess.Write, FileShare.Read);
		_diagStreamWriter = new StreamWriter(fs, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
	}

	/// <summary>TSV lines to <c>BepInEx/plugins/OfflineUnlockMod/esquire_diagnostics.log</c> when <c>esquirePikemanDiagnostics</c> is on (or verbose).</summary>
	private static void Diag(string @event, string detail, ManualLogSource log)
	{
		if (!_fileDiagnostics)
			return;
		if (string.IsNullOrEmpty(_diagnosticsPath))
			_diagnosticsPath = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "esquire_diagnostics.log");
		var n = Interlocked.Increment(ref _diagLines);
		if (n > _diagMaxLines)
		{
			Interlocked.Decrement(ref _diagLines);
			return;
		}

		try
		{
			int frame;
			try
			{
				frame = Time.frameCount;
			}
			catch
			{
				frame = -1;
			}

			var line = new StringBuilder();
			line.Append(DateTime.UtcNow.ToString("O")).Append('\t');
			line.Append("f=").Append(frame).Append('\t');
			line.Append(SanitizeForDiag(@event)).Append('\t');
			line.Append(SanitizeForDiag(detail)).AppendLine();
			var lineText = line.ToString();
			lock (DiagFileLock)
			{
				EnsureDiagWriterUnlocked();
				if (!_diagHeaderWritten)
				{
					_diagHeaderWritten = true;
					_diagStreamWriter.Write(
						"utc\tframe\tevent\tdetail\n# build="
						+ SanitizeForDiag(_diagBuildLabel)
						+ " MaxLines="
						+ _diagMaxLines
						+ (_verbose ? " verbose=on" : string.Empty)
						+ "\n");
				}

				_diagStreamWriter.Write(lineText);
				if (_verbose && (n & 0x3F) == 0)
					_diagStreamWriter.Flush();
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquirePikeman: diagnostics file write failed: " + ex.Message);
		}
	}

	private static string[] GetBundleFileCandidates()
	{
		var pluginDir = Path.Combine(Paths.PluginPath, "OfflineUnlockMod");
		return new[]
		{
			Path.Combine(pluginDir, BundleFileName),
			Path.Combine(pluginDir, "unity_exports", "crewmate", BundleFileName),
		};
	}

	internal static void Unload()
	{
		CloseDiagWriter();
		EsquirePikemanSceneDefer.Cancel();
		EsquirePikemanResManagerAtFrame.Cancel();
		EsquireUnityErrorCorrelator.Disable();
		EsquirePikemanBattlePoolHook.Cancel();
		EsquirePikemanUnitViewHook.Cancel();
		EsquireBattleAnimatorSetHook.Cancel();
		_resManagerPrefixPatched = false;
		ResManagerGameObjectLaneHooks.ResetRegistrationStateForUnload();
		_pendingHarmony = null;
		_pendingClosedResManagerGet = null;
		try
		{
			var go = GameObject.Find("EsquirePikemanDeferredPatch");
			if (go)
				UnityEngine.Object.Destroy(go);
		}
		catch
		{
		}

		if (_bundle)
			_bundle.Unload(unloadAllLoadedObjects: false);
		_bundle = null;
		_battle = null;
		_map = null;
		_vanillaMapMaterialTemplate = null;
		Homm3MapHexLitReboundTemplateIds.Clear();
		Homm3MapHexLitReboundMaterialIds.Clear();
		_loggedHomm3SpritesDefaultFogSyncDisabled = false;
		_mapBillboardModeConfiguredOnce = false;
		_lastConfiguredMapBillboardMaterialMode = string.Empty;
		_diagHeaderWritten = false;
		_diagLines = 0;
		_verbose = false;
		_diagMaxLines = 2000;
		_battleSyncVanillaPresentation = true;
		_battleBeiSecondArgTrue = false;
		_battleAlignFeetToVanilla = true;
		_battleBillboardExtraY = 0f;
		_mapBillboardMaterialMode = "hexLitVanilla";
	}

	/// <summary>
	/// Prefer merged <see cref="LauncherConfigReader.TryLoad"/> value — static <see cref="_mapBillboardMaterialMode"/> can lag if
	/// init order changes; avoids picking spritesDefault branch when plugin <c>config.json</c> says hexLitVanilla.
	/// </summary>
	private static bool MapModeIsSpritesDefault()
	{
		try
		{
			var cfg = LauncherConfigReader.TryLoad();
			if (cfg != null)
			{
				var n = LauncherConfigReader.NormalizeEsquireMapBillboardMaterialMode(cfg.EsquirePikemanMapBillboardMaterialMode);
				_mapBillboardMaterialMode = n;
				return string.Equals(n, "spritesDefault", StringComparison.OrdinalIgnoreCase);
			}
		}
		catch
		{
			// ignore
		}

		return string.Equals(_mapBillboardMaterialMode, "spritesDefault", StringComparison.OrdinalIgnoreCase);
	}

	/// <summary>Lane B + config: <c>spritesDefault</c> uses fog sync; <c>hexLitVanilla</c> uses vanilla donor Hex/Lit rebind.</summary>
	internal static bool IsMapBillboardSpritesDefaultMode() => MapModeIsSpritesDefault();

	private static bool MapHierarchyHasFogSyncComponent(GameObject root)
	{
		if (!root)
			return false;
		foreach (var c in root.GetComponentsInChildren<Component>(true))
		{
			if (!c)
				continue;
			if (string.Equals(c.GetType().Name, MapBillboardFogSyncSimpleName, StringComparison.Ordinal))
				return true;
		}

		return false;
	}

	private static int DestroyAllFogSyncComponentsInHierarchy(GameObject root, ManualLogSource log)
	{
		var n = 0;
		if (!root)
			return 0;
		foreach (var c in root.GetComponentsInChildren<Component>(true))
		{
			if (!c)
				continue;
			if (!string.Equals(c.GetType().Name, MapBillboardFogSyncSimpleName, StringComparison.Ordinal))
				continue;
			try
			{
				UnityEngine.Object.Destroy(c);
				n++;
			}
			catch (Exception ex)
			{
				log?.LogWarning("EsquirePikeman: fog sync Destroy failed: " + ex.Message);
			}
		}

		return n;
	}

	internal static void EnsureMapBillboardFogSyncTypeRegistered(ManualLogSource log)
	{
		if (_mapBillboardFogSyncTypeRegistered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<EsquirePikemanMapBillboardFogSync>();
			_mapBillboardFogSyncTypeRegistered = true;
			log?.LogInfo("EsquirePikeman: registered Il2Cpp type EsquirePikemanMapBillboardFogSync (Sprites/Default map FoW).");
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquirePikeman: EsquirePikemanMapBillboardFogSync registration failed: " + ex);
		}
	}

	private static void EnsureHomm3MapMaterialSyncTypeRegistered(ManualLogSource log)
	{
		if (_homm3MapMaterialSyncTypeRegistered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3MapBillboardMaterialSync>();
			_homm3MapMaterialSyncTypeRegistered = true;
			log?.LogInfo("Homm3Import: registered Il2Cpp type Homm3MapBillboardMaterialSync (animated Hex/Lit map frames).");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: Homm3MapBillboardMaterialSync registration failed: " + ex);
		}
	}

	internal static void EnsureHomm3NativeShellVisibilitySyncTypeRegistered(ManualLogSource log)
	{
		if (_homm3NativeShellVisibilitySyncTypeRegistered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3NativeShellVisibilitySync>();
			_homm3NativeShellVisibilitySyncTypeRegistered = true;
			log?.LogInfo("Homm3Import: registered Il2Cpp type Homm3NativeShellVisibilitySync (native unit visibility mirror).");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: Homm3NativeShellVisibilitySync registration failed: " + ex);
		}
	}

	internal static bool IsHomm3NativeShellVisibilitySyncTypeRegistered => _homm3NativeShellVisibilitySyncTypeRegistered;

	internal static void EnsureHomm3NativeShellRendererTransplantSyncTypeRegistered(ManualLogSource log)
	{
		if (_homm3NativeShellRendererTransplantSyncTypeRegistered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3NativeShellRendererTransplantSync>();
			_homm3NativeShellRendererTransplantSyncTypeRegistered = true;
			log?.LogInfo("Homm3Import: registered Il2Cpp type Homm3NativeShellRendererTransplantSync (native unit renderer transplant).");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: Homm3NativeShellRendererTransplantSync registration failed: " + ex);
		}
	}

	internal static bool IsHomm3NativeShellRendererTransplantSyncTypeRegistered => _homm3NativeShellRendererTransplantSyncTypeRegistered;

	private static void TryEnsureHomm3MapMaterialSync(GameObject mapRoot, Material donor, ManualLogSource log)
	{
		if (!mapRoot || !donor || MapModeIsSpritesDefault())
			return;
		EnsureHomm3MapMaterialSyncTypeRegistered(log);
		if (!_homm3MapMaterialSyncTypeRegistered)
			return;

		try
		{
			var sync = mapRoot.GetComponent<Homm3MapBillboardMaterialSync>();
			if (!sync)
			{
				sync = mapRoot.AddComponent<Homm3MapBillboardMaterialSync>();
				log?.LogInfo("Homm3Import: attached runtime Hex/Lit frame sync to map prefab '" + (mapRoot.name ?? "?") + "'.");
			}

			sync.ConfigureHexLitDonor(donor);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: runtime Hex/Lit frame sync attach failed: " + ex);
		}
	}

	/// <summary>
	/// HoMM3 imports intentionally do not use explicit per-instance fog polling. Native <c>Hex/Lit</c> is the stable path;
	/// <see cref="EsquirePikemanMapBillboardFogSync"/> (shader has no FoW). Do not attach under <c>hexLitVanilla</c> — conflicts with Hex/Lit fog.
	/// </summary>
	internal static void TryEnsureHomm3ImportMapBillboardFogSync(GameObject mapRoot, ManualLogSource log)
	{
		if (!mapRoot || !MapModeIsSpritesDefault() || _loggedHomm3SpritesDefaultFogSyncDisabled)
			return;
		_loggedHomm3SpritesDefaultFogSyncDisabled = true;
		log?.LogInfo("Homm3Import: spritesDefault fog polling disabled for HoMM3 imports; use hexLitVanilla for engine FoW.");
	}

	internal static void TryRemoveHomm3MapBillboardFogSync(GameObject mapRoot, ManualLogSource log)
	{
		if (!mapRoot)
			return;
		var n = DestroyAllFogSyncComponentsInHierarchy(mapRoot, log);
		if (n > 0)
			log?.LogInfo("Homm3Import: removed " + n + " map fog sync component(s) (hexLitVanilla).");
	}

	/// <returns><c>true</c> if a new component was added.</returns>
	private static bool TryAddFogSyncToMapPrefabCore(GameObject mapRoot, ManualLogSource log)
	{
		if (!mapRoot || !_mapBillboardFogSyncTypeRegistered)
			return false;
		try
		{
			if (MapHierarchyHasFogSyncComponent(mapRoot))
				return false;
			mapRoot.AddComponent<EsquirePikemanMapBillboardFogSync>();
			return true;
		}
		catch (TypeInitializationException ex)
		{
			log?.LogWarning("EsquirePikeman: map prefab fog sync AddComponent (Il2Cpp type init): " + ex.Message);
			return false;
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquirePikeman: map prefab fog sync attach failed: " + ex);
			return false;
		}
	}

	private static void TryAddFogSyncToMapPrefab(GameObject mapRoot, ManualLogSource log)
	{
		if (!mapRoot || !MapModeIsSpritesDefault())
			return;
		EnsureMapBillboardFogSyncTypeRegistered(log);
		if (!TryAddFogSyncToMapPrefabCore(mapRoot, log))
			return;
		log?.LogInfo("EsquirePikeman: attached EsquirePikemanMapBillboardFogSync to map prefab root.");
	}

	internal static void TryRestoreHomm3MapMaterialsToSpritesDefault(
		GameObject mapRoot,
		IEnumerable<Material> scopedFrameMaterials,
		ManualLogSource log)
	{
		if (!mapRoot || !MapModeIsSpritesDefault())
			return;
		var zj = Shader.Find("Sprites/Default");
		if (!zj)
		{
			log?.LogWarning("Homm3Import: Shader.Find(\"Sprites/Default\") failed; scoped map frames unchanged.");
			return;
		}

		try
		{
			var seen = new HashSet<int>();
			var n = RestoreMaterialsToSpritesDefault(scopedFrameMaterials, zj, seen);
			foreach (var r in mapRoot.GetComponentsInChildren<Renderer>(true))
			{
				if (!r)
					continue;
				n += RestoreMaterialsToSpritesDefault(r.sharedMaterials, zj, seen);
			}

			if (n > 0)
				log?.LogInfo("Homm3Import: scoped map_frame material(s) set to Sprites/Default (count=" + n + ").");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import: scoped Sprites/Default map frame restore failed: " + ex);
		}
	}

	private static int RestoreMaterialsToSpritesDefault(IEnumerable<Material> materials, Shader shader, HashSet<int> seen)
	{
		if (materials == null || !shader || seen == null)
			return 0;
		var n = 0;
		foreach (var m in materials)
		{
			if (!RestoreOneMapFrameMaterialToSpritesDefault(m, shader, seen))
				continue;
			n++;
		}

		return n;
	}

	private static bool RestoreOneMapFrameMaterialToSpritesDefault(Material m, Shader shader, HashSet<int> seen)
	{
		if (!IsHomm3MapFrameMaterial(m) || !shader)
			return false;
		var id = m.GetInstanceID();
		if (!seen.Add(id))
			return false;
		Homm3MapHexLitReboundMaterialIds.Remove(id);
		var tex = m.HasProperty("_MainTex") ? m.GetTexture("_MainTex") : m.mainTexture;
		var clearKw = m.shaderKeywords;
		if (clearKw != null)
		{
			foreach (var kw in clearKw)
			{
				if (!string.IsNullOrEmpty(kw))
					m.DisableKeyword(kw);
			}
		}

		m.shader = shader;
		if (tex && m.HasProperty("_MainTex"))
			m.SetTexture("_MainTex", tex);
		if (m.HasProperty("_Color"))
			m.SetColor("_Color", Color.white);
		return true;
	}

	/// <summary>
	/// HoMM3-style billboard: <c>Sprites/Default</c> on bundle <c>map_frame_*</c> materials. Fog is handled by
	/// <see cref="EsquirePikemanMapBillboardFogSync"/> (shader has no FoW).
	/// </summary>
	private static void RestoreMapFrameMaterialsToSpritesDefault(ManualLogSource log)
	{
		if (_bundle == null)
			return;
		var zj = Shader.Find("Sprites/Default");
		if (!zj)
		{
			log?.LogWarning("EsquirePikeman: Shader.Find(\"Sprites/Default\") failed; map frames unchanged.");
			Diag("MapSpritesDefaultShaderMissing", string.Empty, log);
			return;
		}

		try
		{
			var seen = new HashSet<int>();
			var n = 0;
			foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<Material>()))
			{
				var m = obj == null ? null : obj.TryCast<Material>();
				if (!IsHomm3MapFrameMaterial(m))
					continue;
				if (!seen.Add(m.GetInstanceID()))
					continue;
				var tex = m.HasProperty("_MainTex") ? m.GetTexture("_MainTex") : m.mainTexture;
				var clearKw = m.shaderKeywords;
				if (clearKw != null)
				{
					foreach (var kw in clearKw)
					{
						if (!string.IsNullOrEmpty(kw))
							m.DisableKeyword(kw);
					}
				}

				m.shader = zj;
				if (tex && m.HasProperty("_MainTex"))
					m.SetTexture("_MainTex", tex);
				if (m.HasProperty("_Color"))
					m.SetColor("_Color", Color.white);
				n++;
			}

			log?.LogInfo("EsquirePikeman: map_frame material(s) set to Sprites/Default (count=" + n + ").");
			Diag("MapSpritesDefaultRestore", "count=" + n, log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquirePikeman: Sprites/Default map frame restore failed: " + ex);
			Diag("MapSpritesDefaultException", ex.ToString(), log);
		}
	}
}
