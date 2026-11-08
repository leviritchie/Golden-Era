using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Linq;
using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using Hex.Configs;
using Hex.GameHub.UICommon;
using Hex.MainMenu;
using Hex.Session;
using Hex.Session.City;
using Hex.Session.Hud;
using Hex.Session.UI;
using Hex.SharedLibrary.Models.Lobby;
using Hex.UI;
using Hex.UI.City;
using Hex.UI.GeneralKit;
using Hex.UI.SteamDemo;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Il2CppInterop.Runtime.Runtime;
using Il2CppSystem.Threading.Tasks;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace OfflineUnlockMod;

[BepInPlugin(PluginGuid, PluginName, PluginVersion)]
// SoftDependency: when AAA_CreateMarkerInterceptEarly is deployed, Chainloader loads it first
// so CreateMarker is hooked before OfflineUnlockMod's heavier startup touches battle types.
[BepInDependency(Homm3CreateMarkerInterceptBootstrap.EarlyPluginGuid, BepInDependency.DependencyFlags.SoftDependency)]
public sealed class Plugin : BasePlugin
{
	internal const string PluginGuid = "levir.heroesoe.offlineunlock";
	internal const string PluginName = "HeroesOE Offline Unlock";
	internal const string PluginVersion = "0.1.320";
#if OFFICIAL_DEOBF_BUILD
	internal const string OfficialDeobfBuildSentinel = "OFFLINE_UNLOCK_MOD_OFFICIAL_DEOBF_BUILD_SENTINEL_V1";
#else
	internal const string OfficialDeobfBuildSentinel = "OFFLINE_UNLOCK_MOD_NON_OFFICIAL_DEOBF_BUILD_SENTINEL_V1";
#endif

	internal static ManualLogSource LogSource;

	/// <summary>Shared Harmony instance for late-install patches (custom unit view routing).</summary>
	internal static Harmony HarmonyInstance;

	/// <summary>Set before <see cref="Hex.Session.Loader.vdk"/> for offline auto-launch; used to augment session probe hero SID matching.</summary>
	internal static OfflineQuickStartPlan LastResolvedOfflineLaunchPlan;

	/// <summary>Mirrors <see cref="LauncherConfig.SuppressBhAppStartTypeInitLoop"/> after <see cref="LauncherConfigReader.TryLoad"/>.</summary>
	internal static bool SuppressBhAppStartTypeInitLoop;

	private Harmony _harmony;
	private Harmony _probeHarmony;
	private Harmony _performanceHarmony;

	private void RegisterRequiredHomm3SelectedHudGuard(LauncherConfig cfg)
	{
		if (!cfg.Homm3ReleaseSelectedHud)
		{
			throw new InvalidOperationException(
				"Runtime-manifest HoMM3 custom units require homm3ReleaseSelectedHud=true. "
				+ "Disable homm3ImportEnabled for data-only startup tests instead of allowing custom combat SIDs to reach the native selected-unit HUD dictionary unguarded.");
		}

		Log.LogInfo("Homm3Import release selected-unit HUD guard required by runtime-manifest custom unit data.");
		Homm3ImportBhSelectedUnitHudFix.RegisterReleaseRequired(_harmony, Log);
	}

	/// <summary>
	/// Port bring-up (docs/port_to_current_game_version.md): on the pinned current build a required feature whose
	/// game symbols did not map is switched off with one error line instead of stopping the whole plugin. Used as an
	/// exception filter in front of the Golden Era fatal catch: it returns false on Golden Era and on an unknown build,
	/// so those still log fatal and rethrow exactly as before. Hooks the feature registered before it threw stay in place.
	/// </summary>
	private bool PortRequiredFeatureOff(string feature, Exception ex)
	{
		if (GameBuild.Kind != GameBuildKind.Current)
			return false;
		Log.LogError(
			"PORT: required feature OFF on " + GameBuild.Describe() + ": " + feature + " ("
			+ ex.GetType().Name + ": " + ex.Message + "). The plugin keeps loading; hooks this feature registered before "
			+ "the failure stay in place.");
		return true;
	}

	private void RegisterRequiredHomm3MapBillboardHooks()
	{
		if (_harmony == null)
			throw new InvalidOperationException("Harmony was not initialized before required HoMM3 map billboard registration.");
		if (Homm3MapLoadFlightRecorder.DisableTownDwellingBillboards)
		{
			Log.LogWarning("HoMM3 release-safe town/dwelling map billboard hooks skipped by diagnostic flag " + Homm3MapLoadFlightRecorder.DisableTownDwellingBillboardsFlag + ".");
			Homm3MapLoadFlightRecorder.Mark("plugin.skip-town-dwelling-map-billboards", Homm3MapLoadFlightRecorder.DisableTownDwellingBillboardsFlag);
			return;
		}

		Log.LogInfo("HoMM3 release-safe map billboard hooks required by runtime-manifest custom faction data.");
		try
		{
			Homm3CustomTownMapBillboard.RegisterRequiredReleaseSafeMapObjectSlice(_harmony, Log);
			Homm3RandomHireResolverHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
			Homm3StrongholdDwellingMapBillboard.RegisterRequiredReleaseSafeMapObjectSlice(_harmony, Log);
			Homm3ArtifactMapBillboard.RegisterRequiredReleaseSafeMapObjectSlice(_harmony, Log);
		}
		catch (Exception ex) when (PortRequiredFeatureOff("HoMM3 release-safe map billboard", ex))
		{
		}
		catch (Exception ex)
		{
			Log.LogFatal("HoMM3 release-safe map billboard hook registration failed during startup: " + ex);
			throw;
		}

		try
		{
			Homm3CampaignSpawnParityHook.TryRegister(_harmony, Log);
		}
		catch (Exception ex)
		{
			// Campaign hero/city parity must not block billboard/town hooks; map still loads.
			Log.LogError("HoMM3 campaign spawn parity hook registration failed: " + ex);
		}

		try
		{
			Homm3PrisonHeroBindingHook.TryRegister(_harmony, Log);
		}
		catch (Exception ex)
		{
			// Native prison binding is optional for maps without generated propHeroes rows.
			// Keep startup alive, but leave the failed binding visible in the log.
			Log.LogError("HoMM3 prison hero binding hook registration failed: " + ex);
		}

		try
		{
			Homm3QuestsSystemReinitGuard.TryRegister(_harmony, Log);
		}
		catch (Exception ex)
		{
			Log.LogError("HoMM3 QuestsSystem reinit guard registration failed: " + ex);
		}

		try
		{
			Homm3StoryHubMapBackgroundHook.TryRegister(_harmony, Log);
		}
		catch (Exception ex)
		{
			Log.LogError("HoMM3 StoryHub map background hook registration failed: " + ex);
		}
	}

	private void RegisterRequiredReleaseSafeCityTownUi()
	{
		if (_harmony == null)
			throw new InvalidOperationException("Harmony was not initialized before required release-safe city/town UI registration.");

		try
		{
			Homm3TownUiCanvasLiftPump.Ensure(Log);
			var patched = PatchReleaseSafeCityTownUi(_harmony);
			if (patched == 0)
				throw new InvalidOperationException("no release-safe city/town UI patch surfaces registered.");
		}
		catch (Exception ex) when (PortRequiredFeatureOff("Release-safe city/town UI", ex))
		{
		}
		catch (Exception ex)
		{
			Log.LogFatal("Release-safe city/town UI hook registration failed during startup: " + ex);
			throw;
		}
	}

	public override void Load()
	{
		LogSource = Log;
		// Build identity selects GameSymbols.TypeGroups scopes; an unknown GameAssembly.dll refuses them loudly.
		GameBuild.LogIdentity(Log);
		Homm3LoadTiming.Mark("Plugin.Load.begin");
		Homm3LoadTiming.EnsureFrameProbe(Log);
		// Earliest practical CreateMarker intercept for olden_cs_recovery edb::.cctor call-trace.
		Homm3CreateMarkerInterceptBootstrap.TryInstallAtPluginLoad(Log);
		LogModDllProbe();
		if (Homm3DiagnosticFlags.IsEnabled("homm3_runtime_probes_enabled.flag")
		    || Homm3DiagnosticFlags.IsEnabled("homm3_frame_stall_monitor.flag")
		    || Homm3DiagnosticFlags.IsEnabled("homm3_runtime_performance_profiler.flag")
		    || Homm3DiagnosticFlags.IsEnabled("homm3_map_load_flight_recorder.flag"))
			FrameStallMonitor.Ensure(Log);
		LocKitDebugProbe.TryRun(Log);
		// Resolve launcher + mod JSON merge before any [HarmonyPatch] Prepare() runs
		// (histogram patches gate on this; a cold cache / wrong order can skip all hooks).
		var cfg = LauncherConfigReader.TryLoad();
		OfflinePerformanceProfiler.Configure(Log);
		using var loadProfileScope = OfflinePerformanceProfiler.Scope("Plugin.Load.afterConfig");
		_harmony = new Harmony(PluginGuid);
		HarmonyInstance = _harmony;
		if (!LauncherConfigReader.TryGetHomm3NativePreviewStartupDeferral(out var deferNativePreviewStartup, out var previewDeferralConfigDiagnostic))
		{
			Log.LogError("Homm3NativePreviewStartupDeferral unavailable: " + previewDeferralConfigDiagnostic + "; no hooks installed.");
		}
		else if (deferNativePreviewStartup)
		{
			Homm3NativePreviewStartupDeferral.TryRegister(_harmony, Log);
		}
		else
		{
			Log.LogInfo("Homm3NativePreviewStartupDeferral skipped: homm3NativePreviewStartupDeferral=false (default). No hooks installed.");
		}
		Homm3HomecomingMapEmissionFeasibilityProbe.TryRegister(_harmony, Log);
		Homm3RmgMapCaptureBridge.TryRegister(_harmony, Log);
		// Early, before any report can be submitted; fail-closed contract in docs/mod_bug_reporting.md.
		ModBugReportRedirect.TryRegister(_harmony, Log, cfg);
		// After the redirect: it only takes SendReport when the redirect is not holding it.
		NativeTelemetryBlock.TryRegister(_harmony, Log, cfg);
		// Independent of both: refuses the developer's analytics host at the gRPC channel, then warns on screen when
		// the redirect is not Redirecting.
		NativeAnalyticsHostGuard.TryRegister(_harmony, Log, cfg);
		NativeAnalyticsHostGuard.ShowStateWarningIfNeeded(cfg);
		if (cfg.Homm3ReleaseCombatMusic)
		{
			try
			{
				Homm3GlobalCombatMusic.Ensure(Log, _harmony);
			}
			catch (Exception ex)
			{
				Log.LogWarning("Homm3GlobalCombatMusic: skipped so the rest of the plugin can load: " + ex.GetType().Name + ": " + ex.Message);
			}
		}
		else
		{
			Log.LogInfo("Homm3GlobalCombatMusic: skipped by homm3ReleaseCombatMusic=false.");
		}
		try
		{
			var manifestDir = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "custom_factions");
			var manifestCount = Homm3CustomFactionRegistry.InitializeFromManifestDirectory(manifestDir);
			Log.LogInfo("HoMM3 custom faction registry loaded " + manifestCount + " manifest(s) from " + manifestDir);
			Homm3RuntimeMechanicRegistry.PrepareFromDirectory(
				Path.Combine(manifestDir, "runtime_mechanics"),
				Log);
		}
		catch (Exception ex)
		{
			Log.LogFatal("HoMM3 custom faction registry failed during startup: " + ex);
			throw;
		}
		SuppressBhAppStartTypeInitLoop = cfg.SuppressBhAppStartTypeInitLoop;
		var assembly = Assembly.GetExecutingAssembly();
		if (cfg.Homm3UiInspector || Homm3DiagnosticFlags.IsEnabled("homm3UiInspector.flag"))
		{
			Homm3UiInspectorOverlayBootstrap.Ensure();
		}
		Homm3HomecomingLayerViewToggleBootstrap.Ensure(Log);
		Homm2ShadeObjectClassStamp.Ensure(Log);
#if !RELEASE_CANDIDATE_BUILD
		if (cfg.Homm3LiveProbeWorkbench
		    || Homm3DiagnosticFlags.IsEnabled("homm3_runtime_probes_enabled.flag")
		    || Homm3DiagnosticFlags.IsEnabled(Homm3LiveProbeWorkbench.FlagFileName))
					Homm3LiveProbeWorkbench.Configure(Log, cfg, _harmony);
		if (cfg.Homm3AiDriverBridge || Homm3DiagnosticFlags.IsEnabled(Homm3AiDriverBridge.FlagFileName))
			Homm3AiDriverBridge.Configure(Log, cfg, _harmony);
#endif
		if ((cfg.Homm3CustomBiomeRegistration || cfg.Homm3SwampAutumnTintProof)
		    && Homm3MapLoadFlightRecorder.DisableCustomBiomeRegistration)
		{
			Log.LogWarning("HoMM3 custom biome registration skipped by diagnostic flag " + Homm3MapLoadFlightRecorder.DisableCustomBiomeRegistrationFlag + ".");
			Homm3MapLoadFlightRecorder.Mark("plugin.skip-custom-biome-registration", Homm3MapLoadFlightRecorder.DisableCustomBiomeRegistrationFlag);
		}
		else if (cfg.Homm3CustomBiomeRegistration || cfg.Homm3SwampAutumnTintProof)
		{
			Homm3MapLoadFlightRecorder.Mark("plugin.register-custom-biome-registration");
			try
			{
				Homm3SwampAutumnTintProof.RegisterRequired(_harmony, Log);
			}
			catch (Exception ex) when (PortRequiredFeatureOff("HoMM3 custom biome registration", ex))
			{
			}
		}
		if (!ElangHjsNreWorkaround.TryRegister(_harmony, Log))
		{
			Log.LogInfo("ELang: in.hjs not found at plugin load; will poll the main thread briefly.");
			ElangHjsNreWorkaround.ScheduleDeferredTry(_harmony, Log);
		}
		BhAppStartTypeInitLoopWorkaround.TryRegister(_harmony, Log, cfg.SuppressBhAppStartTypeInitLoop);
		Homm3FastCityOpeningHook.TryRegister(
			_harmony,
			Log,
			cfg.Homm3FastCityOpening,
			cfg.Homm3FastCityOpeningMaxFrames);
		Homm3LoadTiming.Mark("Plugin.Load.beforeCityPresentationSourceValidation");
		ModActions.ValidateCustomCityPresentationSourcesOrFail(Log, cfg);
		Homm3LoadTiming.Mark("Plugin.Load.afterCityPresentationSourceValidation");
		#region agent log
		AgentDebugLog.Write(
			"D",
			"Plugin:Load",
			"config_snapshot",
			"{"
			+ "\"DamageHistograms\":" + (cfg.DamageHistograms ? "true" : "false")
			+ ",\"releaseSafeProfile\":" + (cfg.ReleaseSafeProfile ? "true" : "false")
			+ ",\"legacyOfflineUnlockPatches\":" + (cfg.LegacyOfflineUnlockPatches ? "true" : "false")
			+ ",\"uiScalePatches\":" + (cfg.UiScalePatches ? "true" : "false")
			+ ",\"suppressBhAppStart\":" + (cfg.SuppressBhAppStartTypeInitLoop ? "true" : "false")
			+ ",\"esquirePikemanVisuals\":" + (cfg.EsquirePikemanVisuals ? "true" : "false")
			+ ",\"esquirePikemanApplyHarmony\":" + (cfg.EsquirePikemanApplyHarmony ? "true" : "false")
			+ ",\"esquirePikemanPrewarmBundle\":" + (cfg.EsquirePikemanPrewarmBundle ? "true" : "false")
			+ ",\"esquirePikemanDiagnostics\":" + (cfg.EsquirePikemanDiagnostics ? "true" : "false")
			+ ",\"esquirePikemanDeferPatch\":" + (cfg.EsquirePikemanDeferPatch ? "true" : "false")
			+ ",\"esquirePikemanDeferBySceneLoad\":" + (cfg.EsquirePikemanDeferBySceneLoad ? "true" : "false")
			+ ",\"esquirePikemanDeferSceneLoadSkips\":" + cfg.EsquirePikemanDeferSceneLoadSkips
			+ ",\"esquirePikemanDeferPatchFrames\":" + cfg.EsquirePikemanDeferPatchFrames
			+ ",\"esquirePikemanSpawnerReflectionProbe\":" + (cfg.EsquirePikemanSpawnerReflectionProbe ? "true" : "false")
			+ ",\"esquirePikemanNarrowUiSpawnerHook\":" + (cfg.EsquirePikemanNarrowUiSpawnerHook ? "true" : "false")
			+ ",\"esquirePikemanDeferResManagerOffsetFrames\":" + cfg.EsquirePikemanDeferResManagerOffsetFrames
			+ ",\"esquirePikemanSwapAdventureMap\":" + (cfg.EsquirePikemanSwapAdventureMap ? "true" : "false")
			+ ",\"esquirePikemanMapBillboardMaterialMode\":" + AgentDebugLog.QuotedJsonString(cfg.EsquirePikemanMapBillboardMaterialMode)
			+ ",\"esquirePikemanResManagerPostfix\":" + (cfg.EsquirePikemanResManagerPostfix ? "true" : "false")
			+ ",\"esquirePikemanUnityErrorCorrelator\":" + (cfg.EsquirePikemanUnityErrorCorrelator ? "true" : "false")
			+ ",\"esquirePikemanVerbose\":" + (cfg.EsquirePikemanVerbose ? "true" : "false")
			+ ",\"releaseCustomGameUiProbes\":" + (cfg.ReleaseCustomGameUiProbes ? "true" : "false")
			+ ",\"homm3CustomBiomeRegistration\":" + (cfg.Homm3CustomBiomeRegistration ? "true" : "false")
			+ ",\"homm3SwampAutumnTintProof\":" + (cfg.Homm3SwampAutumnTintProof ? "true" : "false")
			+ ",\"homm3FastCityOpening\":" + (cfg.Homm3FastCityOpening ? "true" : "false")
			+ ",\"homm3FastCityOpeningMaxFrames\":" + cfg.Homm3FastCityOpeningMaxFrames
			+ ",\"homm3TownPrefabs\":" + (cfg.Homm3TownPrefabs ? "true" : "false")
			+ ",\"PluginVersion\":" + AgentDebugLog.QuotedJsonString(PluginVersion) + "}");
		#endregion
		if (cfg.ReleaseSafeProfile)
		{
			Log.LogInfo("Release-safe profile active: legacy offline unlock, UI scale, and retaliation hooks are suppressed."
				+ (cfg.AutoLaunchOnMenu
					? (cfg.PortSmokeProfile ? " Port-smoke auto-launch enabled." : " Release-safe diagnostic auto-launch enabled.")
					: " Auto-launch off unless port-smoke or releaseSafeAutoLaunchOnMenu requests it.")
				+ " Damage histogram can run only when explicitly enabled.");
		}
		if (cfg.PortSmokeProfile)
		{
			Log.LogInfo(
				"Port-smoke profile active: high-signal diagnostics enabled"
				+ (cfg.AutoLaunchOnMenu
					? "; autoLaunchOnMenu=true - configured match will start after main menu delay."
					: "; auto-launch off (set autoLaunchOnMenu in OfflineLauncherConfig.json).")
				+ " Grep BepInEx/LogOutput.log for HOMM3_UI_CARD_DIAG, RegisterRequired, and LogFatal.");
		}
		EsquirePikemanVisuals.ApplyMapBillboardMaterialModeFromLauncher(cfg.EsquirePikemanMapBillboardMaterialMode);
		if (!cfg.EsquirePikemanVisuals && cfg.Homm3ImportEnabled)
		{
			Log.LogInfo(
				"Map billboard material mode from launcher (Homm3 path; esquirePikemanVisuals=false): "
				+ cfg.EsquirePikemanMapBillboardMaterialMode
				+ " -> "
				+ LauncherConfigReader.NormalizeEsquireMapBillboardMaterialMode(cfg.EsquirePikemanMapBillboardMaterialMode)
				+ ". Set esquirePikemanMapBillboardMaterialMode=spritesDefault for adventure-map fog sync with Sprites/Default.");
		}

		if (cfg.EsquirePikemanVisuals)
		{
			EsquirePikemanVisuals.Configure(
				cfg.EsquirePikemanApplyHarmony,
				cfg.EsquirePikemanDiagnostics,
				PluginVersion,
				cfg.EsquirePikemanDeferPatch,
				cfg.EsquirePikemanDeferBySceneLoad,
				cfg.EsquirePikemanDeferSceneLoadSkips,
				cfg.EsquirePikemanDeferPatchFrames,
				cfg.EsquirePikemanDeferResManagerOffsetFrames,
				cfg.EsquirePikemanSwapAdventureMap,
				cfg.EsquirePikemanResManagerPostfix,
				cfg.EsquirePikemanUnityErrorCorrelator,
				cfg.EsquirePikemanVerbose,
				cfg.EsquirePikemanBattleSyncVanillaPresentation,
				cfg.EsquirePikemanBattleBeiSecondArgTrue,
				cfg.EsquirePikemanBattleAlignFeetToVanilla,
				cfg.EsquirePikemanBattleBillboardExtraY,
				cfg.EsquirePikemanMapBillboardMaterialMode,
				cfg.EsquireBattleSfxVolume);
			if (cfg.EsquirePikemanVisuals && cfg.EsquirePikemanApplyHarmony && cfg.EsquirePikemanResManagerPostfix)
			{
				Log.LogInfo(
					"EsquirePikeman: esquirePikemanResManagerPostfix=true is a legacy setting; current Esquire hooks avoid ResManager.Get<GameObject>.");
			}
			if (cfg.EsquirePikemanVisuals && cfg.EsquirePikemanVerbose)
			{
				Log.LogInfo(
					"EsquirePikeman: VERBOSE - extra Esquire hook state/resource paths are logged where supported. Set esquirePikemanVerbose to false when done.");
			}
			if (cfg.EsquirePikemanPrewarmBundle)
			{
				if (cfg.EsquirePikemanApplyHarmony)
				{
					Log.LogInfo(
						"EsquirePikeman: A/B: if launch still fails, set esquirePikemanPrewarmBundle to false in config.json (load bundle on first use instead of Plugin.Load).");
				}
				EsquirePikemanVisuals.PrewarmInPluginLoad(Log);
			}
			EsquirePikemanVisuals.TryRegister(_harmony, Log);
		}
		else
		{
			EsquireUnityErrorCorrelator.Disable();
			Log.LogInfo("EsquirePikeman: disabled (esquirePikemanVisuals=false). Set true in mod config.json to enable custom bundle swap.");
		}
		if (cfg.EsquirePikemanSpawnerReflectionProbe)
		{
			EsquirePikemanSpawnerReflectionProbe.TryRun(Log);
		}
		if (cfg.EsquirePikemanVisuals && cfg.EsquirePikemanNarrowUiSpawnerHook)
		{
			EsquirePikemanNarrowSpawnerHook.TryRegister(_harmony, Log, cfg.EsquirePikemanApplyHarmony);
		}
		if (cfg.ReleaseSafeProfile && cfg.Homm3ImportEnabled)
		{
			RegisterRequiredHomm3SelectedHudGuard(cfg);
		}
		try
		{
			if (cfg.Homm3ImportEnabled && cfg.Homm3ImportApplyHarmony)
			{
				if (cfg.ReleaseSafeProfile)
				{
					Log.LogInfo("Homm3 import release full feature slice active: custom mesh, battle, projectile, spawner, and tooltip surfaces are enabled while recovered release-safe UI slices keep ownership of army-strip portraits. Preview hooks follow homm3ImportPreviewHooks.");
					Homm3ImportVisuals.TryRegisterReleaseFullFeatureSlice(_harmony, Log, cfg);
					if (cfg.Homm3ReleaseCityMusic)
					{
						Homm3StrongholdCityMusic.TryRegister(_harmony, Log);
					}
					else
					{
						Log.LogInfo("Homm3Import release full feature slice: Stronghold city music skipped by bisection gate.");
					}
				}
				else
				{
					Homm3ImportVisuals.TryRegister(_harmony, Log, cfg.Homm3ImportPreviewHooks);
					if (cfg.Homm3ReleaseDeathFade)
					{
						Homm3MapBillboardDeathFadeHook.TryRegister(_harmony, Log);
					}
					Homm3StrongholdCityMusic.TryRegister(_harmony, Log);
					if (cfg.StrongholdAbilityPanelProbes)
					{
						StrongholdAbilityPanelProbe.TryRegister(_harmony, Log);
					}
					if (cfg.Homm3ImportPreviewHooks)
					{
						Homm3PreviewFineTuneBootstrap.Ensure();
					}
				}
			}
		}
		catch (Exception ex)
		{
			Log.LogWarning("Homm3 import hooks skipped (type resolution failed, likely obfuscation mismatch): " + ex.Message);
		}
		if (cfg.ReleaseSafeProfile && cfg.Homm3ImportEnabled && cfg.Homm3ReleaseCustomGameUi)
		{
			try
			{
				ReleaseCustomGameUiProbe.TryRegisterStrongholdGameHubIntegration(_harmony, Log);
			}
			catch (Exception ex)
			{
				Log.LogWarning("Release Stronghold Custom Game integration failed: " + ex.Message);
			}
		}
		else if (cfg.ReleaseSafeProfile)
		{
			Log.LogInfo("Release Stronghold Custom Game integration skipped: homm3ImportEnabled=" + cfg.Homm3ImportEnabled + ", homm3ReleaseCustomGameUi=" + cfg.Homm3ReleaseCustomGameUi + ".");
		}
		else if (cfg.ReleaseCustomGameUiProbes)
		{
			try
			{
				ReleaseCustomGameUiProbe.TryRegister(_harmony, Log);
			}
			catch (Exception ex)
			{
				Log.LogWarning("ReleaseCustomGameUiProbe failed: " + ex.Message);
			}
		}
		if (cfg.ReleaseSafeProfile && cfg.Homm3ImportEnabled && cfg.Homm3ReleaseSafeUiMapTown)
		{
			Log.LogInfo("Release Stronghold stable UI/map/town slice active; broad legacy warcry native behavior remains quarantined, with release-safe hero ability icon hooks enabled.");
			try
			{
				if (Homm3DiagnosticFlags.IsEnabled("homm3_runtime_probes_enabled.flag"))
					Homm3BattleUnitInitDiagnostics.RegisterRequiredReleaseSafeSlice(_harmony, Log);
			}
			catch (Exception ex) when (PortRequiredFeatureOff("HoMM3 battle unit init diagnostic", ex))
			{
			}
			catch (Exception ex)
			{
				Log.LogFatal("HoMM3 battle unit init diagnostic failed during startup: " + ex);
				throw;
			}
			if (cfg.Homm3ReleaseSafeHeroPortrait)
			{
				try
				{
					Homm3HeroPortraitHook.RegisterRequiredReleaseSafeUiSlice(_harmony, Log, cfg.Homm3ReleaseSafeHeroPortraitCityView);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3HeroPortrait release-safe UI slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3HeroPortrait release-safe UI slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3HeroPortrait release-safe UI slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseSafeHeroClassProfile)
			{
				try
				{
					Homm3HeroClassProfileHook.TryRegister(_harmony, Log);
				}
				catch (Exception ex)
				{
					Log.LogWarning("Homm3HeroClassProfile release-safe UI slice failed: " + ex.Message);
				}
			}
			else
			{
				Log.LogInfo("Homm3HeroClassProfile release-safe UI slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseSafeArmyStrip)
			{
				try
				{
					Homm3ImportArmyStripPortraitHook.TryRegisterReleaseSafeUiSlice(_harmony, Log);
				}
				catch (Exception ex)
				{
					Log.LogWarning("Homm3ImportArmyStripPortrait release-safe UI slice failed: " + ex.Message);
				}
			}
			else
			{
				Log.LogInfo("Homm3ImportArmyStripPortrait release-safe UI slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseSafeCustomUiIcon)
			{
				try
				{
					Homm3CustomUiIconHook.RegisterRequiredReleaseSafeUiSlice(_harmony, Log);
					Homm3DialogAvatarPortraitHook.TryRegister(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3CustomUiIcon release-safe UI slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3CustomUiIcon release-safe UI slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3CustomUiIcon release-safe UI slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseDetailPreview)
			{
				try
				{
					Homm3ImportUnitPreviewModelHook.RegisterRequiredDetailWindowOnly(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3Import unit detail preview release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3Import unit detail preview release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3Import unit detail preview release-safe slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseUnitView && Homm3MapLoadFlightRecorder.DisableUnitViewMapSwaps)
			{
				Log.LogWarning("Homm3Import UnitView map swap release-safe slice skipped by diagnostic flag " + Homm3MapLoadFlightRecorder.DisableUnitViewMapSwapsFlag + ".");
				Homm3MapLoadFlightRecorder.Mark("plugin.skip-unitview-registration", Homm3MapLoadFlightRecorder.DisableUnitViewMapSwapsFlag);
			}
			else if (cfg.Homm3ReleaseUnitView)
			{
				try
				{
					Homm3ImportUnitViewHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
					Log.LogInfo(
						"Homm3Import map adventure route marker: map-rife-v7-e89-scale "
						+ "(e89 scale normalize + unified homm3_map_visual; not 71e971f0 gigantic).");
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3Import UnitView map swap release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3Import UnitView map swap release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3Import UnitView map swap release-safe slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseBattlePool)
			{
				try
				{
					Homm3ImportBattlePoolHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
					Homm3ImportReleaseBattleVisualHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
					Homm3BattleAttackFacingHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
					Homm3BattleRosterPrewarm.Ensure(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3Import battle pool/visual release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3Import battle pool/visual release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3Import battle pool/visual release-safe slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseBattleUiSelectedHud
			    || cfg.Homm3ReleaseBattleUiSelectedUnitView
			    || cfg.Homm3ReleaseBattleUiTurnQueue
			    || cfg.Homm3ReleaseBattleUiHeroViews
			    || cfg.Homm3ReleaseBattleUiDiagnostics)
			{
				try
				{
					Homm3ImportReleaseBattleUiHook.RegisterRequiredReleaseSafeSlice(
						_harmony,
						Log,
						cfg.Homm3ReleaseBattleUiSelectedHud,
						cfg.Homm3ReleaseBattleUiSelectedUnitView,
						cfg.Homm3ReleaseBattleUiTurnQueue,
						cfg.Homm3ReleaseBattleUiHeroViews,
						cfg.Homm3ReleaseBattleUiDiagnostics);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3Import battle UI release-safe micro-slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3Import battle UI release-safe micro-slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3Import battle UI release-safe micro-slices skipped by bisection gates.");
			}
			if (cfg.Homm3SkeletalNecromancyPostBattle || cfg.Homm3SkeletalNecromancyProbe)
			{
				try
				{
					Homm3SkeletalNecromancyProbe.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("HoMM3 skeletal necromancy post-battle slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("HoMM3 skeletal necromancy post-battle slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("HoMM3 skeletal necromancy post-battle slice skipped by bisection gate.");
			}
			if (cfg.Homm3SwashbucklerGoldProduction)
			{
				try
				{
					Homm3SwashbucklerGoldHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("HoMM3 Swashbuckler gold release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("HoMM3 Swashbuckler gold release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("HoMM3 Swashbuckler gold release-safe slice skipped by bisection gate.");
			}
			if (cfg.Homm3TowerBottomlessKnowledgeManaWellAegis)
			{
				try
				{
					Homm3TowerBottomlessKnowledgeHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("HoMM3 Tower Arcane Battery Mana Well Aegis cleanse slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("HoMM3 Tower Arcane Battery Mana Well Aegis cleanse slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("HoMM3 Tower Arcane Battery Mana Well Aegis cleanse slice skipped by bisection gate.");
			}
			if (cfg.Homm3CovePlunder)
			{
				try
				{
					Homm3CovePlunderHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("HoMM3 Cove Treasure Hunting Plunder slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("HoMM3 Cove Treasure Hunting Plunder slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("HoMM3 Cove Treasure Hunting Plunder slice skipped by bisection gate.");
			}
			if (cfg.Homm3FortressHuntingGrounds)
			{
				try
				{
					Homm3FortressHuntingGroundsHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("HoMM3 Fortress Hunting Grounds slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("HoMM3 Fortress Hunting Grounds slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("HoMM3 Fortress Hunting Grounds slice skipped by bisection gate.");
			}
			GoldenEraGameplayOptions.TryRegisterRuntimeHooks(_harmony, Log);
			if (cfg.Homm3CoveAfterShotDisruptingRay)
			{
				try
				{
					Homm3CoveAfterShotHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("HoMM3 Cove after-shot Disrupting Ray release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("HoMM3 Cove after-shot Disrupting Ray release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("HoMM3 Cove after-shot Disrupting Ray release-safe slice skipped by bisection gate.");
			}
			if (cfg.Homm3DungeonDraconicDominion)
			{
				try
				{
					Homm3DungeonDraconicDominionHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
					// Captives owns the native escape click (capture) and the Execute/Ransom spells; fails closed on its own.
					Homm3DungeonCaptivesRuntime.TryRegister(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("HoMM3 Dungeon Draconic Dominion release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("HoMM3 Dungeon Draconic Dominion release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("HoMM3 Dungeon Draconic Dominion slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseProjectile)
			{
				try
				{
					Homm3ProjectileConfigHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3Import projectile config release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3Import projectile config release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3Import projectile config release-safe slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseResManager)
			{
				try
				{
					ResManagerGameObjectLaneHooks.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3Import ResManager GameObject lane release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3Import ResManager GameObject lane release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3Import ResManager GameObject lane release-safe slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseMapObjectUnitVisual && Homm3MapLoadFlightRecorder.DisableTownDwellingBillboards)
			{
				Log.LogWarning("Homm3Import map-object unit/town/dwelling visual slice skipped by diagnostic flag " + Homm3MapLoadFlightRecorder.DisableTownDwellingBillboardsFlag + ".");
				Homm3MapLoadFlightRecorder.Mark("plugin.skip-map-object-unit-visual", Homm3MapLoadFlightRecorder.DisableTownDwellingBillboardsFlag);
			}
			else if (cfg.Homm3ReleaseMapObjectUnitVisual)
			{
				try
				{
					Homm3MapObjectUnitVisualHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3Import map-object unit visual release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3Import map-object unit visual release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3Import map-object unit visual release-safe slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseDeathFade)
			{
				try
				{
					Homm3MapBillboardDeathFadeHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3 map billboard death fade release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3 map billboard death fade release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3 map billboard death fade release-safe slice quarantined by bisection gate; current removal/death surfaces need a static remap before enabling.");
			}
			Homm3ImportVisuals.SetMapSquadRuntimeAttachEnabled(false, Log);
			if (cfg.Homm3ReleaseMapSquadVisualController && Homm3MapLoadFlightRecorder.DisableMapSquadVisualController)
			{
				Log.LogWarning("Homm3Import map squad visual controller release-safe slice skipped by diagnostic flag " + Homm3MapLoadFlightRecorder.DisableMapSquadVisualControllerFlag + ".");
				Homm3MapLoadFlightRecorder.Mark("plugin.skip-map-squad-visual-controller", Homm3MapLoadFlightRecorder.DisableMapSquadVisualControllerFlag);
			}
			else if (cfg.Homm3ReleaseMapSquadVisualController)
			{
				try
				{
					Homm3MapSquadVisualControllerHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3Import map squad visual controller release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3Import map squad visual controller release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3Import map squad visual controller release-safe slice skipped by bisection gate.");
			}
			Homm3MapSquadSelectionDiag.TryRegister(_harmony, Log);
			if (cfg.Homm3ReleaseTooltipPortrait)
			{
				try
				{
					Homm3ImportTooltipPortraitHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3Import tooltip portrait release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3Import tooltip portrait release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3Import tooltip portrait release-safe slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseSafeHeroMapSprite)
			{
				try
				{
					Homm3HeroMapSpriteHook.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex)
				{
					Log.LogWarning("Homm3HeroMapSpriteHook release feature slice failed: " + ex.Message);
				}
				try
				{
					Homm3HomecomingWaterTraversalBridge.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3HomecomingWaterTraversalBridge release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3HomecomingWaterTraversalBridge release-safe slice failed during startup: " + ex);
					throw;
				}
				try
				{
					Homm3HomecomingNativeWaterMeshBridge.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3HomecomingNativeWaterMeshBridge release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3HomecomingNativeWaterMeshBridge release-safe slice failed during startup: " + ex);
					throw;
				}
				try
				{
					Homm3HomecomingWaterPresentationBridge.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3HomecomingWaterPresentationBridge release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3HomecomingWaterPresentationBridge release-safe slice failed during startup: " + ex);
					throw;
				}
				try
				{
					Homm3CampaignWaterEmptyTerrainCursorBridge.RegisterRequiredReleaseSafeSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3CampaignWaterEmptyTerrainCursorBridge release-safe slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3CampaignWaterEmptyTerrainCursorBridge release-safe slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3HeroMapSpriteHook release feature slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseSafeLawIcon)
			{
				try
				{
					Homm3StrongholdLawIconHook.RegisterRequiredReleaseSafe(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3StrongholdLawIconHook release feature slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3StrongholdLawIconHook release feature slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3StrongholdLawIconHook release feature slice skipped by bisection gate.");
			}
			Homm3LoadTiming.Mark("Plugin.Load.beforeLawRuntimeRegistration");
			Homm3CustomFactionLawRuntime.TryRegister(_harmony, Log);
			Homm3RuntimeMechanicHooks.TryRegister(_harmony, Log);
			// Castle Elite Strategem is a faction-skill spell-toggle runtime, not part of the
			// disabled custom-law mutator pass below. Keep it registered with the Castle magic rows.
			Homm3CastleEliteStrategemRuntime.TryRegister(_harmony, Log);
			Homm3FactorySplitAssemblyRuntime.TryRegister(_harmony, Log);
			Homm3TowerArtificingRuntime.TryRegister(_harmony, Log);
			// Diagnostic attribution scope for Artificing observation; gated by policy.observation.diagnostics, not Enabled.
			Homm3TowerArtificingObservation.TryRegister(_harmony, Log);
			Homm3FactorySplitAssemblyArmyStripHud.TryRegister(_harmony, Log);
			Homm3FactoryBulwarkCombatForceSetupPilot.TryRegister(_harmony, Log);
			Homm3BulwarkUnitAbilityRuntime.TryRegister(_harmony, Log);
			Homm3BulwarkRunesRuntime.TryRegister(_harmony, Log);
			Homm3MarshalSuppressingFireTrapBridge.TryRegister(_harmony, Log);
			Homm3HeroSkillApplyDiag.TryRegister(_harmony, Log);
			Homm3CounterstrokeDoctrineHook.TryRegister(_harmony, Log);
			Homm3CounterattackCorrelationLawDiagnostics.TryRegister(_harmony, Log);
			Log.LogInfo("HoMM3 custom law gameplay mutators remain limited to explicitly registered proven or active runtimes; Castle Elite Strategem is registered separately as a faction-skill spell-toggle runtime.");
			Homm3CustomFactionEconomyLawDiagnostics.TryRegister(_harmony, Log);
			Homm3RewardCommitLawDiagnostics.TryRegister(_harmony, Log);
			Homm3CustomConstructionLawDiagnostics.TryRegister(_harmony, Log);
			Homm3SpellbookLawDiagnostics.TryRegister(_harmony, Log);
			Homm3AdventureVisionLawDiagnostics.TryRegister(_harmony, Log);
			Homm3LayeredMapProof.TryRun(Log);
			Homm3HomecomingReducedSliceRuntimeProof.TryRun(Log);
			Homm3BattleEventLawDiagnostics.TryRegister(_harmony, Log);
			Homm3ConfluxSpellCopyVisualRuntime.TryRegister(_harmony, Log);
			// Custom law gameplay mutators are intentionally not registered in the native-data law pass.
			// Leaving speculative handlers active after replacing law text/rows with native bonuses would
			// reintroduce hidden runtime debt through stale profile effects.
			Homm3BattleResultLawDiagnostics.TryRegister(_harmony, Log);
			Homm3BattleResultSafeLawProbe.TryRegister(_harmony, Log);
			// Homm3SquadValueEconomyLawRuntime disabled with the custom law gameplay mutators above.
			Homm3FocusLawDiagnostics.TryRegister(_harmony, Log);
			Homm3BattleAiDecisionProbe.TryRegister(_harmony, Log);
#if !RELEASE_CANDIDATE_BUILD
			Homm3AdventureAiDecisionProbe.TryRegister(_harmony, Log);
#endif
#if ENABLE_SELECTED_UNIT_HUD_HOTKEY_PROBE
			Homm3SelectedUnitHudHotkeyProbe.TryRegister(_harmony, Log);
#endif
#if !RELEASE_CANDIDATE_BUILD
			Homm3AdventureAiWeightBridge.TryRegister(_harmony, Log);
#endif
			Homm3MoraleTriggerLawDiagnostics.TryRegister(_harmony, Log);
			// Homm3MoraleTriggerLawRuntime disabled with the custom law gameplay mutators above.
			Homm3BuffDebuffLawDiagnostics.TryRegister(_harmony, Log);
			// Rampart Avenger, battle-start status/morale, Conflux conjunction,
			// and custom spell-cooldown mutators remain disabled for the native-data law pass.
			Homm3SpellCooldownLawDiagnostics.TryRegister(_harmony, Log);
			Homm3SpellCastGateLawDiagnostics.TryRegister(_harmony, Log);
			Homm3CustomLawGameplayRegistrationAudit.TryRun(Log);
			if (cfg.Homm3ReleaseSafeWarcryIcon)
			{
				try
				{
					Homm3WarcriesHeroAbilityHook.RegisterRequiredReleaseSafeIconSlice(_harmony, Log);
				}
				catch (Exception ex) when (PortRequiredFeatureOff("Homm3WarcriesHeroAbility release-safe icon slice", ex))
				{
				}
				catch (Exception ex)
				{
					Log.LogFatal("Homm3WarcriesHeroAbility release-safe icon slice failed during startup: " + ex);
					throw;
				}
			}
			else
			{
				Log.LogInfo("Homm3WarcriesHeroAbility release-safe icon slice skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseSafeMapBillboards)
			{
				RegisterRequiredHomm3MapBillboardHooks();
			}
			else
			{
				Log.LogInfo("HoMM3 release-safe map billboard slices skipped by bisection gate.");
			}
			if (cfg.Homm3ReleaseSafeCityTownUi)
			{
				RegisterRequiredReleaseSafeCityTownUi();
			}
			else
			{
				Log.LogInfo("Release-safe city/town UI slice skipped by bisection gate.");
			}
		}
		else if (cfg.ReleaseSafeProfile)
		{
			Log.LogInfo("Release Stronghold stable UI/map/town slice skipped: homm3ImportEnabled=" + cfg.Homm3ImportEnabled + ", homm3ReleaseSafeUiMapTown=" + cfg.Homm3ReleaseSafeUiMapTown + ".");
		}
		else if (cfg.Homm3ImportEnabled)
		{
			if (Homm3MapLoadFlightRecorder.DisableTownDwellingBillboards)
			{
				Log.LogWarning("HoMM3 import-profile town/dwelling map billboard hooks skipped by diagnostic flag " + Homm3MapLoadFlightRecorder.DisableTownDwellingBillboardsFlag + ".");
				Homm3MapLoadFlightRecorder.Mark("plugin.skip-import-profile-town-dwelling-map-billboards", Homm3MapLoadFlightRecorder.DisableTownDwellingBillboardsFlag);
			}
			else
			{
				try
				{
					Homm3CustomTownMapBillboard.TryRegisterReleaseSafeMapObjectSlice(_harmony, Log);
					if (Homm3CustomTownMapBillboard.IsRegistered)
					{
						Log.LogInfo("HoMM3 generic custom-town billboard hook registered in import profile; legacy Stronghold/Tower town hooks skipped.");
					}
					else
					{
						Homm3StrongholdTownMapBillboard.TryRegister(_harmony, Log);
						Log.LogWarning("HoMM3 generic custom-town billboard hook did not register; legacy Stronghold hook attempted, but retired Tower-specific town billboard hook was not registered.");
					}
				}
				catch (Exception ex)
				{
					Log.LogWarning("HoMM3 custom town billboard registration failed (obfuscation mismatch, type missing): " + ex.Message);
				}
				try
				{
					Homm3StrongholdDwellingMapBillboard.TryRegisterReleaseSafeMapObjectSlice(_harmony, Log);
					if (!Homm3StrongholdDwellingMapBillboard.IsRegistered)
						Homm3StrongholdDwellingMapBillboard.TryRegister(_harmony, Log);
				}
				catch (Exception ex)
				{
					Log.LogWarning("Homm3StrongholdDwellingMapBillboard failed (obfuscation mismatch, type missing): " + ex.Message);
				}
			}
		try
		{
			Homm3HeroPortraitHook.TryRegister(_harmony, Log);
		}
		catch (Exception ex)
		{
			Log.LogWarning("Homm3HeroPortraitHook failed: " + ex.Message);
		}
		try
		{
			Homm3HeroMapSpriteHook.TryRegister(_harmony, Log);
		}
		catch (Exception ex)
		{
			Log.LogWarning("Homm3HeroMapSpriteHook failed: " + ex.Message);
		}
		try
		{
			Homm3StrongholdLawIconHook.TryRegister(_harmony, Log);
		}
		catch (Exception ex)
		{
			Log.LogWarning("Homm3StrongholdLawIconHook failed: " + ex.Message);
		}
		try
		{
			Homm3CustomUiIconHook.TryRegister(_harmony, Log);
		}
		catch (Exception ex)
		{
			Log.LogWarning("Homm3CustomUiIconHook failed: " + ex.Message);
		}
		try
		{
			Homm3HeroClassProfileHook.TryRegister(_harmony, Log);
		}
		catch (Exception ex)
		{
			Log.LogWarning("Homm3HeroClassProfileHook failed: " + ex.Message);
		}
		try
		{
			Homm3WarcriesHeroAbilityHook.TryRegister(_harmony, Log);
		}
		catch (Exception ex)
		{
			Log.LogWarning("Homm3WarcriesHeroAbilityHook failed: " + ex.Message);
		}
		try
		{
			Homm3WarcryWrapperProbe.TryRegister(_harmony, Log);
		}
		catch (Exception ex)
		{
			Log.LogWarning("Homm3WarcryWrapperProbe failed: " + ex.Message);
		}
		}
		try
		{
			Homm3FactoryCitySceneRegistrar.RegisterRequired(_harmony, Log, cfg.Homm3FactoryCitySceneReplace);
		}
		catch (Exception ex) when (PortRequiredFeatureOff("HoMM3 Factory city scene registrar", ex))
		{
		}
		catch (Exception ex)
		{
			Log.LogFatal("HoMM3 Factory city scene registrar failed during startup: " + ex);
			throw;
		}
		if (cfg.Homm3FactoryCitySceneReplace)
		{
			try
			{
				Homm3OwnedCityMapCursorSuppress.RegisterRequired(_harmony, Log);
			}
			catch (Exception ex) when (PortRequiredFeatureOff("Homm3OwnedCityMapCursorSuppress", ex))
			{
			}
			catch (Exception ex)
			{
				Log.LogFatal("Homm3OwnedCityMapCursorSuppress failed during startup: " + ex);
				throw;
			}
		}
		if (!cfg.Homm3ImportEnabled)
		{
			Log.LogInfo("Homm3UnitAbilityNativeHook skipped: homm3ImportEnabled=false.");
		}
		else if (cfg.ReleaseSafeProfile)
		{
			Log.LogInfo("Homm3UnitAbilityNativeHook skipped: release-safe profile active; native unit ability wrappers need release retracing.");
		}
		else
		{
			try
			{
				Homm3UnitAbilityNativeHook.TryRegister(_harmony, Log);
			}
			catch (Exception ex)
			{
				Log.LogWarning("Homm3UnitAbilityNativeHook failed: " + ex.Message);
			}
		}
		Homm3LoadTiming.Mark("Plugin.Load.beforeAnnotatedHarmonyPatches");
		PatchAnnotatedTypes(_harmony, assembly, cfg, includeProbes: false);
		Homm3LoadTiming.Mark("Plugin.Load.afterAnnotatedHarmonyPatches");
		if (cfg.ReleaseSafeProfile)
		{
			Log.LogInfo("Legacy city open backdrop hook skipped: release-safe profile active; release-safe city/town UI hooks are registered dynamically.");
		}
		else
		{
			PatchBhCityStart(_harmony);
			GroveBackdropAdjusterBootstrap.Ensure();
		}
		if (cfg.DamageHistograms)
		{
			DamageHistogramBootstrap.Ensure();
			_ = DamageHistogramSettings.ShouldApplyPatches();
			DamageHistogramForecastRecorder.TryRegisterForecastPatches(_harmony);
			DamageHistogramForecastRecorder.TryRegisterPanelPatches(_harmony);
		}

		Log.LogInfo(
			"Launcher config: damageHistograms=" + cfg.DamageHistograms
			+ ", releaseSafeProfile=" + cfg.ReleaseSafeProfile
			+ ", legacyOfflineUnlockPatches=" + cfg.LegacyOfflineUnlockPatches
			+ ", uiScalePatches=" + cfg.UiScalePatches
			+ ", damageHistogramUseNativeFrameSprite=" + cfg.DamageHistogramUseNativeFrameSprite
			+ ", modSettings=" + (string.IsNullOrEmpty(LauncherConfigReader.LastResolvedModSettingsPath) ? "none" : LauncherConfigReader.LastResolvedModSettingsPath)
			+ ", uiScalePercent=" + cfg.UiScalePercent
			+ ", suppressBhAppStartTypeInitLoop=" + cfg.SuppressBhAppStartTypeInitLoop
			+ ", esquirePikemanVisuals=" + cfg.EsquirePikemanVisuals
			+ ", esquirePikemanApplyHarmony=" + cfg.EsquirePikemanApplyHarmony
			+ ", esquirePikemanPrewarmBundle=" + cfg.EsquirePikemanPrewarmBundle
			+ ", esquirePikemanDiagnostics=" + cfg.EsquirePikemanDiagnostics
			+ ", esquirePikemanDeferPatch=" + cfg.EsquirePikemanDeferPatch
			+ ", esquirePikemanDeferBySceneLoad=" + cfg.EsquirePikemanDeferBySceneLoad
			+ ", esquirePikemanDeferSceneLoadSkips=" + cfg.EsquirePikemanDeferSceneLoadSkips
			+ ", esquirePikemanDeferPatchFrames=" + cfg.EsquirePikemanDeferPatchFrames
			+ ", esquirePikemanDeferResManagerOffsetFrames=" + cfg.EsquirePikemanDeferResManagerOffsetFrames
			+ ", esquirePikemanSwapAdventureMap=" + cfg.EsquirePikemanSwapAdventureMap
			+ ", esquirePikemanMapBillboardMaterialMode="
			+ LauncherConfigReader.NormalizeEsquireMapBillboardMaterialMode(cfg.EsquirePikemanMapBillboardMaterialMode)
			+ ", esquirePikemanResManagerPostfix=" + cfg.EsquirePikemanResManagerPostfix
			+ ", esquirePikemanUnityErrorCorrelator=" + cfg.EsquirePikemanUnityErrorCorrelator
			+ ", esquirePikemanVerbose=" + cfg.EsquirePikemanVerbose
			+ ", esquireBattleSfxVolume=" + cfg.EsquireBattleSfxVolume.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ", esquirePikemanNarrowUiSpawnerHook=" + cfg.EsquirePikemanNarrowUiSpawnerHook
			+ ", homm3ImportEnabled=" + cfg.Homm3ImportEnabled
			+ ", homm3ImportApplyHarmony=" + cfg.Homm3ImportApplyHarmony
			+ ", homm3ReleaseCustomGameUi=" + cfg.Homm3ReleaseCustomGameUi
			+ ", homm3ReleaseSafeUiMapTown=" + cfg.Homm3ReleaseSafeUiMapTown
			+ ", homm3ReleaseSafeHeroPortraitCityView=" + cfg.Homm3ReleaseSafeHeroPortraitCityView
			+ ", homm3ReleaseUnitView=" + cfg.Homm3ReleaseUnitView
			+ ", homm3ReleaseBattlePool=" + cfg.Homm3ReleaseBattlePool
			+ ", homm3ReleaseBattleUi=" + cfg.Homm3ReleaseBattleUi
			+ ", homm3ReleaseBattleUiSelectedHud=" + cfg.Homm3ReleaseBattleUiSelectedHud
			+ ", homm3ReleaseBattleUiSelectedUnitView=" + cfg.Homm3ReleaseBattleUiSelectedUnitView
			+ ", homm3ReleaseBattleUiTurnQueue=" + cfg.Homm3ReleaseBattleUiTurnQueue
			+ ", homm3ReleaseBattleUiHeroViews=" + cfg.Homm3ReleaseBattleUiHeroViews
			+ ", homm3ReleaseBattleUiDiagnostics=" + cfg.Homm3ReleaseBattleUiDiagnostics
			+ ", homm3ReleaseProjectile=" + cfg.Homm3ReleaseProjectile
			+ ", homm3ReleaseNarrowSpawner=" + cfg.Homm3ReleaseNarrowSpawner
			+ ", homm3ReleaseResManager=" + cfg.Homm3ReleaseResManager
			+ ", homm3ReleaseMapObjectUnitVisual=" + cfg.Homm3ReleaseMapObjectUnitVisual
			+ ", homm3ReleaseDeathFade=" + cfg.Homm3ReleaseDeathFade
			+ ", homm3ReleaseMapSquadVisualController=" + cfg.Homm3ReleaseMapSquadVisualController
			+ ", homm3PreviewUseStaticPortraits=" + cfg.Homm3PreviewUseStaticPortraits
			+ ", homm3DetailPreviewUseStaticPortraits=" + cfg.Homm3DetailPreviewUseStaticPortraits
			+ ", homm3CustomBiomeRegistration=" + cfg.Homm3CustomBiomeRegistration
			+ ", homm3SwampAutumnTintProof=" + cfg.Homm3SwampAutumnTintProof
			+ ", homm3ImportPreviewHooks=" + cfg.Homm3ImportPreviewHooks
			+ ", strongholdAbilityPanelProbes=" + cfg.StrongholdAbilityPanelProbes
			+ ", releaseCustomGameUiProbes=" + cfg.ReleaseCustomGameUiProbes
#if !RELEASE_CANDIDATE_BUILD
			+ ", homm3LiveProbeWorkbench=" + cfg.Homm3LiveProbeWorkbench
#endif
			+ " | build=" + PluginVersion
		);

		if (cfg.ReleaseSafeProfile && RetaliationDebug.IsEnabled())
		{
			Log.LogInfo("Retaliation probe patches skipped: release-safe profile active.");
		}
		else if (RetaliationDebug.IsEnabled() && Homm3DiagnosticFlags.IsEnabled("homm3_runtime_probes_enabled.flag"))
		{
			_probeHarmony = new Harmony(PluginGuid + ".probes");
			PatchAnnotatedTypes(_probeHarmony, assembly, cfg, includeProbes: true);
			Log.LogInfo("Retaliation probe patches loaded.");
		}
		else if (RetaliationDebug.IsEnabled())
		{
			Log.LogInfo("Retaliation probe patches skipped: homm3_runtime_probes_enabled.flag is not present.");
		}

		if (OfflinePerformanceProfiler.Enabled)
		{
			_performanceHarmony = new Harmony(PluginGuid + ".performance");
			OfflinePerformanceProfiler.RegisterHarmonyPatchedMethodProfiler(
				_performanceHarmony,
				PluginGuid,
				Log);
		}

		Log.LogInfo("Plugin patches loaded.");
		Homm3LoadTiming.Mark("Plugin.Load.end");
	}

	public override bool Unload()
	{
		_harmony?.UnpatchSelf();
		_probeHarmony?.UnpatchSelf();
		_performanceHarmony?.UnpatchSelf();
		OfflinePerformanceProfiler.FlushIfDue(force: true);
		EsquirePikemanVisuals.Unload();
		return true;
	}

	/// <summary>Log where BepInEx thinks the game root is and whether the on-disk plugin DLL under <see cref="Paths.PluginPath"/> matches; use this to confirm you are not running a different install / stale copy.</summary>
	private static void LogModDllProbe()
	{
		try
		{
			var expected = Path.Combine(
				Paths.PluginPath,
				"OfflineUnlockMod",
				"OfflineUnlockMod.dll"
			);
			var exists = File.Exists(expected);
			long size = 0;
			var writeUtc = "";
			if (exists)
			{
				var fi = new FileInfo(expected);
				size = fi.Length;
				writeUtc = fi.LastWriteTimeUtc.ToString("O");
			}
			LogSource?.LogInfo(
				"Mod DLL probe: build="
				+ PluginVersion
				+ " | GameRootPath="
				+ Paths.GameRootPath
				+ " | BepInExRootPath="
				+ Paths.BepInExRootPath
				+ " | PluginPath="
				+ Paths.PluginPath
				+ " | buildProfileSentinel="
				+ OfficialDeobfBuildSentinel
			);
			LogSource?.LogInfo(
				"Mod DLL probe: onDisk="
				+ expected
				+ " | exists="
				+ exists
				+ (exists
					? " | size="
					  + size
					  + " | lastWriteUtc="
					  + writeUtc
					: " (if you build elsewhere, copy the DLL to THIS GameRoot BepInEx\\plugins\\OfflineUnlockMod\\)")
			);
			var loc = typeof(Plugin).Assembly.Location;
			LogSource?.LogInfo(
				string.IsNullOrEmpty(loc)
					? "ExecutingAssembly.Location is empty (normal for some IL2CPP; use onDisk line above)."
					: "ExecutingAssembly.Location=" + loc
			);
		}
		catch (Exception ex)
		{
			LogSource?.LogWarning("Mod DLL probe failed: " + ex);
		}
	}

	private static void PatchAnnotatedTypes(Harmony harmony, Assembly assembly, LauncherConfig cfg, bool includeProbes)
	{
		var patchedCount = 0;
		var skippedCount = 0;
		var candidates = AccessTools.GetTypesFromAssembly(assembly)
			.Where(type => type != null)
			.OrderBy(type => type.FullName, StringComparer.Ordinal);

		foreach (var type in candidates)
		{
			if (ShouldSkipPatchForConfig(type, cfg))
			{
				skippedCount++;
				continue;
			}

			var isProbe = type.GetCustomAttributes(typeof(ProbePatchAttribute), inherit: false).Length > 0;
			if (isProbe != includeProbes)
			{
				continue;
			}

			var hasHarmonyPatch = type.GetCustomAttributes(typeof(HarmonyPatch), inherit: false).Length > 0;
			if (!hasHarmonyPatch)
			{
				continue;
			}

			try
			{
				harmony.CreateClassProcessor(type).Patch();
				patchedCount++;
			}
			catch (Exception ex)
			{
				LogSource?.LogWarning($"Failed to patch {type.FullName}: {ex.Message}");
			}
		}

		LogSource?.LogInfo($"Patched {patchedCount} {(includeProbes ? "probe" : "core")} Harmony classes; skipped {skippedCount} by config.");
	}

	private static bool ShouldSkipPatchForConfig(Type type, LauncherConfig cfg)
	{
		if (type == null || cfg == null)
		{
			return false;
		}

		var name = type.Name ?? "";
		if (cfg.ReleaseSafeProfile && type.GetCustomAttributes(typeof(ProbePatchAttribute), inherit: false).Length > 0)
		{
			return true;
		}

		if (!cfg.DamageHistograms && name.StartsWith("DamageHistogram", StringComparison.Ordinal))
		{
			return true;
		}

		if (cfg.ReleaseSafeProfile && IsReleaseUnsafeForecastPatchName(name))
		{
			return true;
		}

		if (cfg.ReleaseSafeProfile && IsReleaseUnsafeUiPatchName(name))
		{
			return true;
		}

		if (!cfg.LegacyOfflineUnlockPatches && IsLegacyOfflineUnlockPatchName(name))
		{
			return true;
		}

		if (!cfg.UiScalePatches && IsUiScalePatchName(name))
		{
			return true;
		}

		return false;
	}

	private static bool IsReleaseUnsafeForecastPatchName(string name)
	{
		return name == "EjzOezProbePatch"
			|| name == "EjzBdwuProbePatch"
			|| name == nameof(BhHealDamageForecastPanelShowPatch)
			|| name == nameof(BhHealDamageForecastPanelHidePatch);
	}

	private static bool IsReleaseUnsafeUiPatchName(string name)
	{
		return name == nameof(BhHUDSessionShowProbePatch)
			|| name == nameof(LoaderUttProbePatch)
			|| name == nameof(LoaderLlaProbePatch)
			|| name == nameof(CtaIaiProbePatch)
			|| name == nameof(CzkUvlProbePatch)
			|| name == nameof(CzkUvlBhHudIraNreGuardPatch)
			|| name == nameof(Homm3StrongholdTownLayersBhCityOpenPatch)
			|| name == nameof(Homm3StrongholdTownLayersBhBuildingsManagerRefreshPatch)
			|| name == nameof(Homm3StrongholdTownLayersBhBuildingsManagerHidePatch)
			|| name == nameof(Homm3StrongholdTownLayersBhTownExitPatch);
	}

	private static bool IsLegacyOfflineUnlockPatchName(string name)
	{
		return name == nameof(MainMenuNavigationViewStartPatch)
			|| name == nameof(ScEarlyAccessOpenPatch)
			|| name == nameof(ScDemoThankYouOpenPatch)
			|| name == nameof(BhDemoIconTxtUIStartPatch)
			|| name == nameof(BhDemoIconTxtUIShowPatch)
			|| name == nameof(BhDemoIconTxtUIShowAnimPatch)
			|| name == nameof(BhNavigationButtonClickPatch);
	}

	private static bool IsUiScalePatchName(string name)
	{
		return name == nameof(BhFontStartPatch)
			|| name == nameof(BhFontOnEnablePatch)
			|| name == nameof(BhFontInitPatch)
			|| name == nameof(CanvasScalerOnEnablePatch);
	}

	private static void PatchBhCityStart(Harmony harmony)
	{
		try
		{
			// BhCityUISession.tvw is the city screen open/show method (virtual void, no args).
			// Patch it so the backdrop fires after me.bynh (city data) is fully wired up.
			var sessionType = ModActions.GetHexType("Hex.UI.City.BhCityUISession");
			var openMethod = sessionType?.GetMethod("ghj", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
				?? sessionType?.GetMethod("ghk", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (openMethod == null)
			{
				LogSource?.LogWarning("Could not find BhCityUISession open method - custom city backdrops will not apply.");
				return;
			}

			var prefix = new HarmonyMethod(typeof(ModActions).GetMethod(nameof(ModActions.RecordCityOpenStart), BindingFlags.Static | BindingFlags.NonPublic));
			var postfix = new HarmonyMethod(typeof(ModActions).GetMethod(nameof(ModActions.AfterCityOpen), BindingFlags.Static | BindingFlags.NonPublic));
			harmony.Patch(openMethod, prefix: prefix, postfix: postfix);
			LogSource?.LogInfo($"Patched BhCityUISession.{openMethod.Name} for custom city backdrop (Grove / HoMM3 Stronghold).");
		}
		catch (Exception ex)
		{
			LogSource?.LogWarning($"Failed to patch BhCityUISession open method: {ex.Message}");
		}
	}

	private static int PatchReleaseSafeCityTownUi(Harmony harmony)
	{
		if (harmony == null)
			return 0;
		var patched = 0;
		var sessionType = ModActions.GetHexType("Hex.UI.City.BhCityUISession");
		if (sessionType != null)
		{
			var sessionPatchedBefore = patched;
			foreach (var name in GameSymbols.ReleaseTownUi.CitySessionRefresh.NameHints)
				patched += PatchCityTownMethod(harmony, sessionType, name, -1, nameof(ModActions.AfterReleaseCityTownUiRefreshCitySession));
			if (patched == sessionPatchedBefore)
			{
				var shapeMethods = GameMember.FindMethods(
					sessionType,
					typeof(void),
					Type.EmptyTypes,
					GameSymbols.ReleaseTownUi.CitySessionRefresh);
				var seen = new HashSet<string>();
				foreach (var method in shapeMethods)
				{
					if (method == null || !seen.Add(method.DeclaringType?.FullName + "." + method.Name))
						continue;
					patched += PatchCityTownMethodInfo(harmony, method, nameof(ModActions.AfterReleaseCityTownUiRefreshCitySession));
				}
			}
			foreach (var name in GameSymbols.ReleaseTownUi.CitySessionHide.NameHints)
				patched += PatchCityTownMethod(harmony, sessionType, name, 0, nameof(ModActions.ClearReleaseCityTownUi));
		}

		var buildingsManagerType = ModActions.GetHexType("Hex.Session.City.BhBuildingsManager");
		if (buildingsManagerType != null)
		{
			foreach (var name in GameSymbols.ReleaseTownUi.BuildingsManagerRefresh0.NameHints)
				patched += PatchCityTownMethod(harmony, buildingsManagerType, name, 0, nameof(ModActions.AfterReleaseCityTownUiRefresh));
			foreach (var name in GameSymbols.ReleaseTownUi.BuildingsManagerRefresh1.NameHints)
				patched += PatchCityTownMethod(harmony, buildingsManagerType, name, 1, nameof(ModActions.AfterReleaseCityTownUiRefresh));
			foreach (var name in GameSymbols.ReleaseTownUi.BuildingsManagerRefresh2.NameHints)
				patched += PatchCityTownMethod(harmony, buildingsManagerType, name, 2, nameof(ModActions.AfterReleaseCityTownUiRefresh));
			patched += PatchCityTownMethod(harmony, buildingsManagerType, "OnDisable", 0, nameof(ModActions.AfterReleaseCityTownUiRefresh));
		}

		var buildingSessionType = ModActions.GetHexType("Hex.UI.City.BhUIBuildingSession");
		if (buildingSessionType != null)
		{
			patched += PatchCityTownMethod(harmony, buildingSessionType, "Init", 1, nameof(ModActions.AfterReleaseCityTownUiRefreshBuildingSessionFbiArg0));
			foreach (var name in GameSymbols.ReleaseTownUi.BuildingSessionRefresh.NameHints)
				patched += PatchCityTownMethod(harmony, buildingSessionType, name, -1, nameof(ModActions.AfterReleaseCityTownUiRefreshBuildingSession));
		}

		foreach (var typeName in new[]
		{
			"Hex.UI.City.BhCityInfoGroup",
			"Hex.UI.City.BhCityInfoView",
			"Hex.UI.City.BhNavigationView",
			"Hex.UI.City.BhCitySpecialView",
			"Hex.Session.Hud.BhCityUIElement"
		})
		{
			var cityInitType = ModActions.GetHexType(typeName);
			if (cityInitType != null)
				patched += PatchCityTownMethod(harmony, cityInitType, "Init", 1, nameof(ModActions.AfterReleaseCityTownUiRefreshArg0));
		}

		var buildingViewType = ModActions.GetHexType("Hex.UI.City.BhBuildingView");
		if (buildingViewType != null)
		{
			foreach (var methodName in GameSymbols.ReleaseTownUi.BuildingViewBind.NameHints)
				patched += PatchCityTownMethod(harmony, buildingViewType, methodName, 3, nameof(ModActions.AfterReleaseCityTownUiRefreshArg0));
			patched += PatchCityTownMethod(harmony, buildingViewType, "UpdateView", 0, nameof(ModActions.AfterReleaseCityTownUiRefreshBuildingView));
			foreach (var name in GameSymbols.ReleaseTownUi.BuildingViewHide.NameHints)
				patched += PatchCityTownMethod(harmony, buildingViewType, name, 0, nameof(ModActions.AfterReleaseCityTownUiRefresh));
		}

		var townInputType = ModActions.GetHexType("Hex.Session.City.BhTownInput");
		if (townInputType != null)
			patched += PatchCityTownMethod(harmony, townInputType, "ExitTownCmd", 0, nameof(ModActions.ClearReleaseCityTownUi));

		var navigationType = ModActions.GetHexType("Hex.UI.City.BhNavigationView");
		if (navigationType != null)
		{
			foreach (var methodName in GameSymbols.ReleaseTownUi.NavigationTabSelect.NameHints)
				patched += PatchCityTownMethod(harmony, navigationType, methodName, 1, nameof(ModActions.AfterReleaseCityNavigationTabSelected));
			foreach (var methodName in GameSymbols.ReleaseTownUi.NavigationSelect.NameHints)
				patched += PatchCityTownMethod(harmony, navigationType, methodName, 1, nameof(ModActions.AfterReleaseCityNavigationSelected));
			foreach (var methodName in GameSymbols.ReleaseTownUi.NavigationBack.NameHints)
				patched += PatchCityTownMethodPrefix(harmony, navigationType, methodName, 0, nameof(ModActions.PrefixReleaseCityBackNavigation));
		}

		var navigationTabType = ModActions.GetHexType("Hex.UI.City.BhNavigationTabView");
		if (navigationTabType != null)
		{
			foreach (var methodName in GameSymbols.ReleaseTownUi.NavigationTabClick.NameHints)
				patched += PatchCityTownMethod(harmony, navigationTabType, methodName, 0, nameof(ModActions.AfterReleaseCityNavigationTabViewSelected));
			foreach (var methodName in GameSymbols.ReleaseTownUi.NavigationTabVisualSelect.NameHints)
				patched += PatchCityTownMethod(harmony, navigationTabType, methodName, 0, nameof(ModActions.AfterReleaseCityNavigationTabVisualSelected));
		}

		var dayPanelButtonType = ModActions.GetHexType("Hex.Session.Hud.BhDayPanelButtonManager");
		if (dayPanelButtonType != null)
			patched += PatchCityTownMethodPrefix(harmony, dayPanelButtonType, "OnPointerClick", 1, nameof(ModActions.PrefixReleaseCityDayPanelButtonClick));

		var dayPanelType = ModActions.GetHexType("Hex.Session.Hud.BhDayPanel");
		if (dayPanelType != null)
		{
			foreach (var methodName in GameSymbols.ReleaseTownUi.DayPanelBack.NameHints)
				patched += PatchCityTownMethodPrefix(harmony, dayPanelType, methodName, 0, nameof(ModActions.PrefixReleaseCityDayPanelBackAction));
		}

		var dayPanelV2Type = ModActions.GetHexType("Hex.Session.Hud.BhDayPanelV2");
		if (dayPanelV2Type != null)
		{
			foreach (var methodName in GameSymbols.ReleaseTownUi.DayPanelBack.NameHints)
				patched += PatchCityTownMethodPrefix(harmony, dayPanelV2Type, methodName, 0, nameof(ModActions.PrefixReleaseCityDayPanelV2BackAction));
		}

		var genericButtonType = ModActions.GetHexType("Hex.UI.GeneralKit.BhGenericButton") ?? ModActions.GetHexType("Hex.UI.BhGenericButton");
		if (genericButtonType != null)
		{
			patched += PatchCityTownMethodPrefix(harmony, genericButtonType, "OnPointerClick", 1, nameof(ModActions.PrefixReleaseCityGenericButtonClick));
			foreach (var methodName in GameSymbols.ReleaseTownUi.GenericButtonBack.NameHints)
				patched += PatchCityTownMethodPrefix(harmony, genericButtonType, methodName, 0, nameof(ModActions.PrefixReleaseCityGenericButtonBackAction));
		}

		var exitHudType = ModActions.GetHexType("Hex.Session.Hud.BhButtonExitHud");
		if (exitHudType != null)
		{
			LogSource?.LogInfo("Release-safe city/town UI slice: leaving BhButtonExitHud unmodified; older forced back-arrow binding can cover the town exit button.");
		}

		var upgradeType = ModActions.GetHexType("Hex.Session.City.ScUpgradeUnits");
		if (upgradeType != null)
		{
			foreach (var methodName in GameSymbols.ReleaseTownUi.UpgradeUiShown.NameHints)
			{
				var parameterCount =
					string.Equals(methodName, "vsf", StringComparison.Ordinal)
					|| string.Equals(methodName, "bano", StringComparison.Ordinal)
						? 1
						: 0;
				patched += PatchCityTownMethod(harmony, upgradeType, methodName, parameterCount, nameof(ModActions.AfterReleaseCityUpgradeUiShown));
			}
		}

		var hireType = typeof(BhHireCityView);
		foreach (var methodName in GameSymbols.ReleaseTownUi.HireUiShown.NameHints)
			patched += PatchCityTownMethod(harmony, hireType, methodName, 0, nameof(ModActions.AfterReleaseCityHireUiShown));

		var marketType = ModActions.GetHexType("Hex.Session.UI.BhExchangeUISession");
		if (marketType != null)
		{
			foreach (var methodName in GameSymbols.ReleaseTownUi.MarketUiShown.NameHints)
				patched += PatchCityTownMethod(harmony, marketType, methodName, 0, nameof(ModActions.AfterReleaseCityMarketUiShown));
		}

		var itemMarketType = ModActions.GetHexType("Hex.Session.UI.BhItemMarketUISession");
		if (itemMarketType != null)
		{
			foreach (var methodName in GameSymbols.ReleaseTownUi.ItemMarketUiShown.NameHints)
				patched += PatchCityTownMethod(harmony, itemMarketType, methodName, 0, nameof(ModActions.AfterReleaseCityItemMarketUiShown));
		}

		var artifactChangerType = ModActions.GetHexType("Hex.UI.City.BhArtifactChanger");
		if (artifactChangerType != null)
		{
			foreach (var methodName in GameSymbols.ReleaseTownUi.ArtifactChangerUiShown.NameHints)
				patched += PatchCityTownMethod(harmony, artifactChangerType, methodName, 0, nameof(ModActions.AfterReleaseCityArtifactChangerUiShown));
		}

		var tavernType = ModActions.GetHexType("Hex.Session.UI.BhHeroBuySession");
		if (tavernType != null)
		{
			foreach (var methodName in GameSymbols.ReleaseTownUi.TavernUiShown.NameHints)
				patched += PatchCityTownMethod(harmony, tavernType, methodName, 0, nameof(ModActions.AfterReleaseCityTavernUiShown));
		}

		if (patched == 0)
			LogSource?.LogWarning("Release-safe city/town UI slice: no methods registered.");
		else
			LogSource?.LogInfo("Release-safe city/town UI slice: registered " + patched + " patch(es).");
		return patched;
	}

	private static int PatchCityTownMethod(Harmony harmony, Type type, string methodName, int parameterCount, string postfixName)
	{
		try
		{
			var method = FindMethodByNameAndArity(type, methodName, parameterCount);
			if (method == null)
				return 0;
			return PatchCityTownMethodInfo(harmony, method, postfixName);
		}
		catch (Exception ex)
		{
			LogSource?.LogWarning("Release-safe city/town UI slice: failed to patch " + type?.FullName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static int PatchCityTownMethodInfo(Harmony harmony, MethodInfo method, string postfixName)
	{
		if (method == null)
			return 0;
		var postfix = typeof(ModActions).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
		if (postfix == null)
			return 0;
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			LogSource?.LogWarning("Release-safe city/town UI slice: refusing incompatible postfix for " + method.DeclaringType?.FullName + "." + method.Name + ": " + reason);
			return 0;
		}
		harmony.Patch(method, postfix: new HarmonyMethod(postfix));
		return 1;
	}

	private static int PatchCityTownMethodPrefix(Harmony harmony, Type type, string methodName, int parameterCount, string prefixName)
	{
		try
		{
			var method = FindMethodByNameAndArity(type, methodName, parameterCount);
			if (method == null)
				return 0;
			var prefix = typeof(ModActions).GetMethod(prefixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (prefix == null)
				return 0;
			if (!GameMember.IsHarmonyPatchCompatible(method, prefix, out var reason))
			{
				LogSource?.LogWarning("Release-safe city/town UI slice: refusing incompatible prefix for " + method.DeclaringType?.FullName + "." + method.Name + ": " + reason);
				return 0;
			}
			harmony.Patch(method, prefix: new HarmonyMethod(prefix));
			return 1;
		}
		catch (Exception ex)
		{
			LogSource?.LogWarning("Release-safe city/town UI slice: failed to prefix " + type?.FullName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static MethodInfo FindMethodByNameAndArity(Type type, string methodName, int parameterCount)
	{
		if (type == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
		{
			if (method.Name != methodName)
				continue;
			if (parameterCount >= 0 && method.GetParameters().Length != parameterCount)
				continue;
			return method;
		}
		return null;
	}
}

internal static class ModActions
{
	private static int _objCityConfigFractionReads;
	private static long _objCityConfigFractionReadTicks;
	private static int _objCityConfigFractionFallbackReads;
	private static int _objCityConfigFractionNullReads;
	private static int _objCityConfigFractionSlowLogs;
	private static bool _loggedMenuUnlock;
	private static bool _loggedOverlayHide;
	private static bool _loggedEarlyAccessSkip;
	private static bool _loggedDemoThankYouSkip;
	private static bool _loggedUiScale;
	private static bool _loggedGroveBackdropLoad;
	private static bool _loggedGroveBackdropApply;
	private static bool _loggedCityMenuCanvasLift;
	private static bool _loggedTownCanvasRaycasterLift;
	private static int _customTownUiLiftUntilFrame;
	private static int _cachedUiScalePercent = -1;
	private static float _cachedStrongholdTownBackdropScale = -1f;
	private static readonly HashSet<string> _loggedMissingHomm3TownBackdrop = new(StringComparer.OrdinalIgnoreCase);
	private const string CityBackdropObjectName = "OfflineUnlockCityBackdrop";
	private const string CustomTownArtRootObjectName = "OfflineUnlockCustomTownArtRoot";
	private const float CityBackdropReferenceWidth = 1920f;
	private const float CityBackdropReferenceHeight = 1080f;
	// Relative to CanvasCityPanel source canvas sortingOrder (Route A mirror domain).
	// Absolute Overlay ladders (100/220/260...) were the wrong owner vs BhScreen→jj.hqq.
	internal const int CustomTownBackdropSortingOrder = 0;
	internal const int CustomTownLayerSortingOrder = 1;
	private const int CustomTownArtToNativeUiGap = 20;
	private const int ReleaseTownActivePanelOrderGap = 40;
	private const int ReleaseTownNavigationOrderGap = 60;
	private const int ReleaseTownTooltipOrderGap = 80;
	private const int ReleaseTownTooltipRaycastOrderGap = 81;
	private static Canvas _cachedCityPanelSourceCanvas;
	private static int _cachedCityPanelSourceCanvasId;
	private static int _cachedCityPanelSourceSceneHandle;
	private static bool _loggedTownCanvasMirror;
	private static int _lastNativeTownMenuRaycasterFrame = -1;

	private static readonly HashSet<string> CityMenuCanvasNames = new(StringComparer.Ordinal)
	{
		"CanvasCityPanel",
		"CityNavigation",
		"GarnisonPanel",
		GameSymbols.ReleaseTownUi.BuildingViewPanelCanvasName,
		GameSymbols.ReleaseTownUi.HireViewPanelCanvasName,
		"CONVERT UNIT PANEL",
		"PortalSummoning",
		GameSymbols.ReleaseTownUi.ArtifactChangerPanelCanvasName,
		GameSymbols.ReleaseTownUi.MarketViewPanelCanvasName,
		GameSymbols.ReleaseTownUi.ItemMarketPanelCanvasName,
		GameSymbols.ReleaseTownUi.HeroBuyPanelCanvasName,
		"Mycelium Roots",
		"ShrineOfRebirth",
		"HERO TRAINING PANEL",
		"UNIT WINDOW SESSION",
		"OptionalVersionUnitRewardView",
		GameSymbols.ReleaseTownUi.UpgradeUnitPanelCanvasName,
		"FLOATING UI CANVAS",
		"CanvasCityTechHUDPanel"
	};
	// Active town windows that must stay above custom town backdrop/layers.
	// Includes Session.UI market/tavern canvases that are often outside the CityUI scene.
	private static readonly string[] ReleaseTownPrimaryPanelCanvasNames =
	{
		GameSymbols.ReleaseTownUi.BuildingViewPanelCanvasName,
		GameSymbols.ReleaseTownUi.HireViewPanelCanvasName,
		GameSymbols.ReleaseTownUi.UpgradeUnitPanelCanvasName,
		GameSymbols.ReleaseTownUi.MarketViewPanelCanvasName,
		GameSymbols.ReleaseTownUi.ItemMarketPanelCanvasName,
		GameSymbols.ReleaseTownUi.ArtifactChangerPanelCanvasName,
		GameSymbols.ReleaseTownUi.HeroBuyPanelCanvasName
	};
	private static readonly HashSet<string> ReleaseTownPrimaryPanelCanvasNameSet =
		new(ReleaseTownPrimaryPanelCanvasNames, StringComparer.Ordinal);
	private sealed class CachedFileStamp
	{
		internal CachedFileStamp(int frame, string stamp)
		{
			Frame = frame;
			Stamp = stamp;
		}

		internal int Frame { get; }
		internal string Stamp { get; }
	}

	/// <summary>Relative to the OfflineUnlockMod plugin folder under <see cref="Paths.PluginPath"/>, not game root.</summary>
	private static readonly string Homm3StrongholdCityBackdropPluginRelativePath = Path.Combine(
		"homm3_runtime_assets",
		"town_scene_refs",
		"homm3_stronghold",
		"mockups",
		"homm3_stronghold_background_mock_1920x1080.png");
	private static readonly Dictionary<long, FontScaleSnapshot> _fontScaleSnapshots = new();
	private static readonly Dictionary<long, CanvasScaleSnapshot> _canvasScaleSnapshots = new();
	private static OfflineQuickStartPlan _cachedPlan;
	private static bool _autoLaunchTerminal;
	private static float _autoLaunchMenuReadyRealtime = -1f;
	private static float _lastAutoLaunchStartRealtime = -1000f;
	private static bool _loggedAutoLaunchPending;
	private static float _lastAutoLaunchFailLogRealtime = -1000f;
	private static bool _loggedAutoLaunchDisabledInConfig;
	internal const string HomecomingPlayableShellMapSid = "h3_roe_castle_homecoming_single_layer";
	internal static string HomecomingPlayableShellLastResolvedHash;
	private const string HomecomingPlayableShellLogPrefix = "HOMM3_HOMECOMING_PLAYABLE_SHELL_LAUNCH";
    private static bool _homecomingPlayableShellCatalogInitInvoked;
    private static float _homecomingPlayableShellCatalogInitRealtime = -1f;
    private static bool _homecomingPlayableShellCatalogInitWaitLogged;
	private static bool _homecomingPlayableShellSceneObserverTypeRegistered;
	private static bool _homecomingPlayableShellSceneObserverAttached;
	private static RawImage _cityBackdropImage;
	private static readonly Dictionary<Graphic, bool> _suppressedTownDonorGraphics = new();
	private static Texture2D _cityBackdropTexture;
	private static string _cityBackdropTexturePath;
	private static string _cityBackdropTextureStamp;
	private static readonly Dictionary<string, CachedFileStamp> _cityBackdropStampCacheByPath = new(StringComparer.OrdinalIgnoreCase);
	private static RectTransform _cachedCityPanelRoot;
	private static RectTransform _customTownArtRoot;
	private static int _cachedCityPanelSceneHandle;
	private static string _cachedCityPanelSceneName;
	private static int _cityBackdropBasisSceneHandle;
	private static int _cityBackdropBasisRootId;
	private static float _cityBackdropBasisWidth;
	private static float _cityBackdropBasisHeight;
	private static int _lastCityBackdropApplyFrame = -1;
	private static int _loggedCityBackdropSlowApply;
	private static int _releaseTownUiDiagnosticCount;
	private static int _releaseTownUiEvidenceDiagnosticCount;
	private static int _releaseTownUiBackMainDiagnosticCount;
	private static int _releaseTownUiBackdropDecisionCount;
	private static int _releaseTownUiBackdropPostconditionCount;
	private static int _releaseTownUiCanvasCensusCount;
	private static int _releaseTownUiMemberDumpCount;
	private static int _releaseBuildSessionSnapshotCount;
	private static bool _loggedReleaseCityStaticFieldMissing;
	private static bool _loggedReleaseCityStaticFieldNull;
	private static readonly HashSet<string> _releaseTownUiDumpedTypes = new HashSet<string>(StringComparer.Ordinal);
	private static object _releaseTownUiCityWrapper;
	private static string _releaseTownUiFraction;
	private static Hex.Session.Data.ObjCity _releaseTownUiCityData;
	private static int _cityBackdropSiblingIndex = 0;
	private static float _cityBackdropOffsetX;
	private static float _cityBackdropOffsetY;
	private static float _cityBackdropScale = 1f;
	private static float _cityBackdropAlpha = 1f;

	internal static void KeepMenuUnlocked(ScMainMenu menu)
	{
		if (menu == null)
		{
			return;
		}

		KeepMenuUnlocked(menu.mainMenuNavigationView);
	}

	internal static void KeepMenuUnlocked(MainMenuNavigationView view)
	{
		if (view == null)
		{
			return;
		}

		try
		{
			ForceButtonEnabled(TryReadNavigationButton(view, GameSymbols.MainMenu.CampaignButtonFields));
			ForceButtonEnabled(TryReadNavigationButton(view, GameSymbols.MainMenu.QuickStartButtonFields));
			ForceButtonEnabled(TryReadNavigationButton(view, GameSymbols.MainMenu.SkirmishButtonFields));
			ForceButtonEnabled(TryReadNavigationButton(view, GameSymbols.MainMenu.StartNewSkirmishButtonFields));
			ForceButtonEnabled(TryReadNavigationButton(view, GameSymbols.MainMenu.LoadSkirmishButtonFields));
			ForceButtonEnabled(TryReadNavigationButton(view, GameSymbols.MainMenu.HotseatButtonFields));
			SuppressEarlyAccessWidgets(view);

			if (!_loggedMenuUnlock)
			{
				_loggedMenuUnlock = true;
				Plugin.LogSource?.LogInfo("Main menu offline buttons were re-enabled.");
			}
		}
		catch (Exception ex)
		{
			Warn("Failed to unlock main menu", ex);
		}
	}

	internal static Task<bool> CompletedTask(bool result)
	{
		var taskSource = new TaskCompletionSource<bool>();
		taskSource.SetResult(result);
		return taskSource.Task;
	}

	internal static void HideOverlay(BhDemoIconTxtUI overlay)
	{
		if (overlay == null)
		{
			return;
		}

		try
		{
			HideCanvasGroup(overlay.rootCg);
			HideCanvasGroup(overlay.pressAnyKeyCg);
			HideCanvasGroup(overlay.pressAnyKeyCgHelper);
			HideObject(overlay.portraitRoot);
			HideObject(overlay.line);
			HideObject(overlay.pressAnyKey);
			HideObject(overlay.pressAnyKeyHelper);
			HideObject(overlay.gameObject);

			if (!_loggedOverlayHide)
			{
				_loggedOverlayHide = true;
				Plugin.LogSource?.LogInfo("Demo overlay instance was hidden.");
			}
		}
		catch (Exception ex)
		{
			Warn("Failed to hide demo overlay", ex);
		}
	}

	internal static void SuppressEarlyAccessWidgets(MainMenuNavigationView view)
	{
		if (view == null)
		{
			return;
		}

		HideObject(view.earlyAccessHeader);
		HideObject(view.earlyAccessLinks);
		if (view.earlyAccessLinks != null)
		{
			HideObject(view.earlyAccessLinks.textContent);
			HideObject(view.earlyAccessLinks.feedbackButton);
			HideObject(view.earlyAccessLinks.bugButton);
			HideObject(view.earlyAccessLinks.youtubeButton);
			HideObject(view.earlyAccessLinks.discordButton);
		}
	}

	internal static void Warn(string message, Exception ex)
	{
		Plugin.LogSource?.LogWarning($"{message}: {ex.Message}");
	}

	internal static void ApplyCustomCityBackdrop()
	{
		var stopwatch = Stopwatch.StartNew();
		try
		{
			var frame = Time.frameCount;
			var root = FindCityPanelRectTransform();
			if (root == null)
			{
				LogCityBackdropApplyDecision("no-city-panel", null, default, null, null);
				LogCityPanelCensus("no-city-panel");
				LogReleaseTownUiDiagnostic("apply-skip-no-city-panel", "scene:" + SafeActiveSceneName() + "|frame:" + frame);
				return;
			}

			// Loader/adventure-map city lifecycle callbacks can run while no city UI is actually live.
			// Avoid clearing/rebuilding custom town UI unless CanvasCityPanel belongs to a town interior scene.
			var panelScene = root.gameObject.scene;
			if (!panelScene.IsValid() || !IsCityInteriorSceneName(panelScene.name))
			{
				LogCityBackdropApplyDecision("non-city-panel-scene", root, panelScene, null, null);
				LogReleaseTownUiDiagnostic(
					"apply-skip-non-city-panel-scene",
					"panelScene:" + (panelScene.IsValid() ? panelScene.name : "invalid") + "|activeScene:" + SafeActiveSceneName() + "|frame:" + frame);
				return;
			}

			if (_lastCityBackdropApplyFrame == frame)
			{
				LogReleaseTownUiDiagnostic("apply-skip-same-frame", "frame:" + frame);
				// Owned cityFactory presentation is idempotent after first apply; do not Sync
				// on every same-frame backdrop caller (live-negative load storm).
				if (!Homm3FactoryCitySceneRegistrar.OwnsActiveFactoryCityWorld(GetCurrentCityFraction()))
					Homm3StrongholdTownLayers.SyncCurrentCityLayers();
				return;
			}

			var fraction = GetCurrentCityFraction();
			LogCityBackdropApplyDecision("after-fraction", root, panelScene, fraction, null);
			if (fraction == null)
			{
				LogReleaseTownUiDiagnostic("apply-no-fraction", "frame:" + frame);
				return;
			}

			// Factory cityFactory ownership: world backdrop + native-owned Factory BhBuilding layers.
			// Do not install CanvasCityPanel OfflineUnlockCityBackdrop or Route A posters.
			var factoryOwned = Homm3FactoryCitySceneRegistrar.OwnsActiveFactoryCityWorld(fraction);
			if (factoryOwned)
			{
				RestoreTownDonorGraphics();
				ClearCustomCityBackdrop();
				_lastCityBackdropApplyFrame = frame;
				LogReleaseTownUiDiagnostic("apply-skip-factory-city-world-ownership", "fraction:" + fraction);
				// One Ensure via Sync — not Ensure then Sync (double presentation work).
				Homm3StrongholdTownLayers.SyncCurrentCityLayers();
				return;
			}

			var backdropPath = GetCityBackdropPath(fraction);
			LogCityBackdropApplyDecision("after-path", root, panelScene, fraction, backdropPath);
			if (string.IsNullOrEmpty(backdropPath))
			{
				LogReleaseTownUiDiagnostic("apply-no-backdrop-path", "fraction:" + fraction);
				ClearCustomCityBackdrop();
				return;
			}

			_lastCityBackdropApplyFrame = frame;

			SuppressCustomTownDonorScene(fraction);
			var image = EnsureCityBackdropImage(root);
			var texture = LoadCityBackdropTexture(backdropPath);
			if (image == null || texture == null)
			{
				LogReleaseTownUiDiagnostic(
					"apply-no-image-or-texture",
					"fraction:" + fraction + "|image:" + (image == null ? "null" : "ok") + "|texture:" + (texture == null ? "null" : "ok") + "|path:" + backdropPath);
				ClearCustomCityBackdrop();
				Homm3StrongholdTownLayers.ClearTownLayers();
				return;
			}

			image.texture = texture;
			image.color = new Color(1f, 1f, 1f, _cityBackdropAlpha);
			image.raycastTarget = false;
			image.maskable = false;

			var rect = image.rectTransform;
			rect.SetParent(EnsureCustomTownArtRoot(root) ?? root, worldPositionStays: false);
			ApplyCityBackdropTransform(root, rect);
			EnsureCityBackdropCanvasOrder(image.gameObject);
			rect.localScale = Vector3.one;
			rect.localRotation = Quaternion.identity;

			if (image.transform.parent == root)
				ApplyCityBackdropSiblingIndex(root, image.transform);
			EnsureCustomTownUiAboveTownArt(root);
			// Town music follows the same proven custom-city backdrop lifecycle instead of
			// depending on the separate building-layer root lookup.
			if (Homm3StrongholdCityMusic.HasTownMusicBundle(fraction))
				Homm3StrongholdCityMusic.EnsureTownMusicPlaying(fraction);
			Homm3StrongholdTownLayers.SyncCurrentCityLayers();
			// One reconcile pass after art+layers attach: preserve native BhScreen render domain,
			// only ensure raycasters / relative order above mirrored art.
			ScheduleNativeTownMenuLiftFrames(12);
			EnsureNativeTownMenusAboveCustomArt();
			ForceVisible(image.gameObject);
			LogCityBackdropPostcondition(root, image, texture, fraction, panelScene, backdropPath);
			if (!_loggedGroveBackdropApply)
			{
				_loggedGroveBackdropApply = true;
				Plugin.LogSource?.LogInfo($"Applied custom city backdrop for fraction '{fraction}' to CanvasCityPanel.");
				LogReleaseTownUiDiagnostic("apply-success", "fraction:" + fraction + "|scene:" + panelScene.name);
				LogCanvasSortOrders();
			}
		}
		catch (Exception ex)
		{
			Warn("Failed to apply custom city backdrop", ex);
			ClearCustomCityBackdrop();
			Homm3StrongholdTownLayers.ClearTownLayers();
		}
		finally
		{
			stopwatch.Stop();
			if (stopwatch.ElapsedMilliseconds >= 100 && _loggedCityBackdropSlowApply < 12)
			{
				_loggedCityBackdropSlowApply++;
				Plugin.LogSource?.LogInfo(
					"Custom city backdrop apply took "
					+ stopwatch.ElapsedMilliseconds
					+ " ms (logged slow calls only).");
			}
		}
	}

	internal static void ValidateCustomCityPresentationSourcesOrFail(ManualLogSource log, LauncherConfig cfg)
	{
		if (cfg == null)
			throw new ArgumentNullException(nameof(cfg));

		var stopwatch = Stopwatch.StartNew();
		var backdrops = 0;
		var layerSprites = 0;
		var animationFrames = 0;
		var fullScene3dRoutes = 0;
		var issues = new List<string>();
		var buildEffectsPrewarmStatus = "not-run";
		// Validate only the configured town presentation route; source checks never decode textures or prefabs.
		if (cfg.Homm3ReleaseSafeCityTownUi)
		{
			foreach (var fraction in Homm3CustomFactionRegistry.EnumerateReleaseUiPresentationFactionSids())
			{
				try
				{
					if (UsesConfiguredFullScene3dTownRoute(cfg, fraction))
					{
						fullScene3dRoutes++;
						continue;
					}

					var path = GetCityBackdropPath(fraction);
					if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
						issues.Add(fraction + ": required city backdrop is missing at " + (path ?? "(unresolved)"));
					else
						backdrops++;

					try
					{
						layerSprites += Homm3StrongholdTownLayers.ValidateFactionAssetSourcesOrFail(fraction);
					}
					catch (Exception ex)
					{
						issues.Add(fraction + ": " + ex.Message);
					}

					try
					{
						animationFrames += Homm3StrongholdTownAnimPlayer.ValidateFactionAnimationSourcesOrFail(fraction);
					}
					catch (Exception ex)
					{
						issues.Add(fraction + ": " + ex.Message);
					}
				}
				catch (Exception ex)
				{
					issues.Add(fraction + ": " + ex.Message);
				}
			}
		}

		// Keep the existing best-effort build-effect WAV warmup; playback no-ops when the clip is unavailable.
		buildEffectsPrewarmStatus = Homm3StrongholdTownBuildEffects.PrewarmBuildEffects(log);

		stopwatch.Stop();
		log?.LogInfo(
			"HoMM3 city presentation source validation: backdrops="
			+ backdrops
			+ ", layerSprites="
			+ layerSprites
			+ ", animationFrames="
			+ animationFrames
			+ ", fullScene3dRoutes="
			+ fullScene3dRoutes
			+ ", buildEffectsPrewarm="
			+ buildEffectsPrewarmStatus
			+ ", issues="
			+ issues.Count
			+ ", elapsedMs="
			+ stopwatch.ElapsedMilliseconds
			+ ".");
		if (issues.Count > 0)
			throw new InvalidOperationException("required HoMM3 city presentation sources are invalid: " + string.Join("; ", issues));
	}

	private static bool UsesConfiguredFullScene3dTownRoute(LauncherConfig cfg, string fraction)
	{
		if (!cfg.Homm3FactoryCitySceneReplace
			|| !cfg.Homm3TownScene3d
			|| !Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction)
			|| !GameSymbols.FactoryCityScene.IsOwnedCityWorldFaction(fraction))
			return false;

		if (!Homm3TownScene3d.TryGetCatalog(fraction, out var catalog))
			throw new FileNotFoundException("configured Factory full-3D town route has no scene catalog for " + fraction + ".");

		return catalog.FullScene3d;
	}

	internal static void RecordCityOpenStart(out long __state)
	{
		__state = Stopwatch.GetTimestamp();
	}

	internal static void AfterCityOpen(long __state)
	{
		try
		{
			var elapsedMs = (Stopwatch.GetTimestamp() - __state) * 1000.0 / Stopwatch.Frequency;
			if (elapsedMs >= 100)
			{
				Plugin.LogSource?.LogInfo(
					"BhCityUISession city open returned after "
					+ elapsedMs.ToString("0")
					+ " ms before custom backdrop sync.");
			}
		}
		catch
		{
			// Timing diagnostics must never affect city opening.
		}

		ApplyCustomCityBackdrop();
	}

	internal static void AfterReleaseCityTownUiRefresh(MethodBase __originalMethod, object __instance, object[] __args)
	{
		CaptureReleaseTownUiFbi(__instance, __args, __originalMethod);
		CaptureReleaseTownUiCityWrapper(__instance, __args, __originalMethod);
		LogReleaseTownUiDiagnostic(
			"refresh-postfix",
			"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		ApplyCustomCityBackdrop();
	}

	internal static void AfterReleaseCityTownUiRefreshCitySession(MethodBase __originalMethod, BhCityUISession __instance, object[] __args)
	{
		CaptureReleaseTownUiFbi(__instance, __args, __originalMethod);
		CaptureReleaseTownUiCityWrapper(__instance, __args, __originalMethod);
		LogReleaseTownUiDiagnostic(
			"refresh-postfix",
			"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		ApplyCustomCityBackdrop();
		EnsureReleaseBuildTreeVisibleIfSelected(__instance, __originalMethod, "city-session-refresh");
		LogReleaseCitySessionBuildSnapshot(__instance, __originalMethod);
	}

	internal static bool PrefixReleaseCityBackNavigation(MethodBase __originalMethod, BhNavigationView __instance)
	{
		return !TryHandleReleaseCityBackNavigation(__instance, __originalMethod);
	}

	internal static void AfterReleaseCityNavigationSelected(MethodBase __originalMethod, BhNavigationView __instance, ECityNavigation __0)
	{
		try
		{
			if (__instance == null || !IsActiveSceneCityInterior())
				return;
			if (__0 != ECityNavigation.BuildingsConstruction)
			{
				LiftReleaseTownNavigationTargetPanel(__0, "navigation-selected");
				return;
			}
			AfterReleaseCityConstructionNavigationSelected(__originalMethod, __instance, "navigation-build-selected");
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"navigation-build-selected-failed",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	internal static void AfterReleaseCityNavigationTabSelected(MethodBase __originalMethod, BhNavigationView __instance, BhNavigationTabView __0)
	{
		try
		{
			if (__instance == null || __0 == null || !IsActiveSceneCityInterior())
				return;
			var tabState = TryReadCityNavigationTabState(__0);
			LogReleaseTownUiDiagnostic(
				"navigation-tab-selected",
				"method:" + DescribeMethod(__originalMethod)
					+ "|state:" + tabState
					+ "|path:" + DescribeUnityPath(__0.gameObject));
			if (tabState != (int)ECityNavigation.BuildingsConstruction)
			{
				LiftReleaseTownNavigationTargetPanel((ECityNavigation)tabState, "navigation-tab-selected");
				return;
			}
			AfterReleaseCityConstructionNavigationSelected(__originalMethod, __instance, "navigation-tab-build-selected");
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"navigation-tab-selected-failed",
				"method:" + DescribeMethod(__originalMethod)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	internal static void AfterReleaseCityNavigationTabViewSelected(MethodBase __originalMethod, BhNavigationTabView __instance)
	{
		try
		{
			if (__instance == null || !IsActiveSceneCityInterior())
				return;
			var tabState = TryReadCityNavigationTabState(__instance);
			LogReleaseTownUiDiagnostic(
				"navigation-tab-view-selected",
				"method:" + DescribeMethod(__originalMethod)
					+ "|state:" + tabState
					+ "|path:" + DescribeUnityPath(__instance.gameObject));
			if (tabState != (int)ECityNavigation.BuildingsConstruction)
			{
				LiftReleaseTownNavigationTargetPanel((ECityNavigation)tabState, "navigation-tab-view-selected");
				return;
			}
			AfterReleaseCityConstructionTabSelected(__originalMethod, __instance, "navigation-tab-view-build-selected");
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"navigation-tab-view-selected-failed",
				"method:" + DescribeMethod(__originalMethod)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	internal static void AfterReleaseCityNavigationTabVisualSelected(MethodBase __originalMethod, BhNavigationTabView __instance)
	{
		try
		{
			if (__instance == null || !IsActiveSceneCityInterior())
				return;
			var tabState = TryReadCityNavigationTabState(__instance);
			LogReleaseTownUiDiagnostic(
				"navigation-tab-visual-selected",
				"method:" + DescribeMethod(__originalMethod)
					+ "|state:" + tabState
					+ "|path:" + DescribeUnityPath(__instance.gameObject));
			if (tabState != (int)ECityNavigation.BuildingsConstruction)
			{
				LiftReleaseTownNavigationTargetPanel((ECityNavigation)tabState, "navigation-tab-visual-selected");
				return;
			}
			LiftActiveReleaseTownPanelCanvas(GameSymbols.ReleaseTownUi.BuildingViewPanelCanvasName, "navigation-tab-visual-selected");
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"navigation-tab-visual-selected-failed",
				"method:" + DescribeMethod(__originalMethod)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static void AfterReleaseCityConstructionNavigationSelected(MethodBase originalMethod, BhNavigationView navigation, string source)
	{
		if (navigation == null || !IsActiveSceneCityInterior())
			return;
		LiftActiveReleaseTownPanelCanvas(GameSymbols.ReleaseTownUi.BuildingViewPanelCanvasName, source + "-active-panel");
		var session = FindCitySessionForNavigation(navigation);
		var buildingSession = TryGetReleaseCityBuildingSession(session, originalMethod);
		if (buildingSession == null)
		{
			LogReleaseTownUiDiagnostic(
				"navigation-build-selected-no-session",
				"method:" + DescribeMethod(originalMethod)
					+ "|source:" + source);
			return;
		}
		CloseReleaseCityHireAndUpgradeSubwindows();
		ShowReleaseBuildTreePanelOnlyIfPopulated(buildingSession, originalMethod, source, allowOpenHiddenPanel: true);
		// Owned cityFactory Main-hall open: SyncCurrentCityLayers re-enters presentation Ensure and
		// was live-negative for open-then-close plus load cost. HUD construction select still Syncs.
		if (source == null || !source.StartsWith("owned-city", StringComparison.Ordinal))
			Homm3StrongholdTownLayers.SyncCurrentCityLayers();
		LogReleaseBuildSessionSnapshot(buildingSession, originalMethod);
	}

	/// <summary>
	/// Open the release build tree the same way the city HUD BuildingsConstruction tab does.
	/// Used when owned cityFactory Main (town hall) world clicks must skip native Visit
	/// (Visit is a divergent open path from HUD navigation select).
	/// </summary>
	internal static bool TryOpenOwnedCityHallConstructionMenu(string source)
	{
		try
		{
			var fraction = GetCurrentCityFraction();
			if (!Homm3FactoryCitySceneRegistrar.OwnsActiveFactoryCityWorld(fraction))
			{
				LogReleaseTownUiEvidenceDiagnostic(
					"owned-city-hall-open-refused-not-owned",
					"source:" + (source ?? "null") + "|fraction:" + (fraction ?? "null"));
				return false;
			}
			if (!IsActiveSceneCityInterior())
			{
				LogReleaseTownUiEvidenceDiagnostic(
					"owned-city-hall-open-refused-not-city",
					"source:" + (source ?? "null"));
				return false;
			}
			var session = FindBestActiveReleaseCitySession();
			if (session == null)
			{
				LogReleaseTownUiEvidenceDiagnostic(
					"owned-city-hall-open-no-session",
					"source:" + (source ?? "null"));
				return false;
			}
			var navigation = TryGetReleaseCityNavigation(session, null);
			if (navigation == null)
			{
				LogReleaseTownUiEvidenceDiagnostic(
					"owned-city-hall-open-no-navigation",
					"source:" + (source ?? "null"));
				return false;
			}
			var alreadyConstruction = TryReadCityNavigationState(navigation)
				== (int)ECityNavigation.BuildingsConstruction;
			if (!alreadyConstruction && !TryInvokeCityNavigationSelect(navigation, ECityNavigation.BuildingsConstruction))
			{
				LogReleaseTownUiEvidenceDiagnostic(
					"owned-city-hall-open-select-failed",
					"source:" + (source ?? "null"));
				return false;
			}
			// Select postfix normally lifts the panel; call again so already-selected
			// BuildingsConstruction (or a missed postfix) still opens with allowOpenHiddenPanel.
			AfterReleaseCityConstructionNavigationSelected(null, navigation, source ?? "owned-city-hall");
			Plugin.LogSource?.LogInfo(
				"HoMM3 owned-city hall: opened BuildingsConstruction source="
				+ (source ?? "null")
				+ " fraction=" + (fraction ?? "null")
				+ " alreadyConstruction=" + alreadyConstruction);
			LogReleaseTownUiDiagnostic(
				"owned-city-hall-open",
				"source:" + (source ?? "null")
					+ "|fraction:" + (fraction ?? "null")
					+ "|alreadyConstruction:" + alreadyConstruction);
			return true;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"owned-city-hall-open-failed",
				"source:" + (source ?? "null")
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
			return false;
		}
	}

	private static bool TryInvokeCityNavigationSelect(BhNavigationView navigation, ECityNavigation target)
	{
		if (navigation == null)
			return false;
		foreach (var methodName in GameSymbols.ReleaseTownUi.NavigationSelect.NameHints)
		{
			if (string.IsNullOrEmpty(methodName))
				continue;
			var method = AccessTools.Method(typeof(BhNavigationView), methodName, new[] { typeof(ECityNavigation) })
				?? AccessTools.Method(typeof(BhNavigationView), methodName);
			if (method == null)
				continue;
			method.Invoke(navigation, new object[] { target });
			return true;
		}
		return false;
	}

	private static void AfterReleaseCityConstructionTabSelected(MethodBase originalMethod, BhNavigationTabView tab, string source)
	{
		if (tab == null || !IsActiveSceneCityInterior())
			return;
		LiftActiveReleaseTownPanelCanvas(GameSymbols.ReleaseTownUi.BuildingViewPanelCanvasName, source + "-active-panel");
		var session = FindBestActiveReleaseCitySession();
		var buildingSession = TryGetReleaseCityBuildingSession(session, originalMethod);
		if (buildingSession == null)
		{
			LogReleaseTownUiDiagnostic(
				"navigation-tab-build-selected-no-session",
				"method:" + DescribeMethod(originalMethod)
					+ "|source:" + source
					+ "|path:" + DescribeUnityPath(tab.gameObject));
			return;
		}
		CloseReleaseCityHireAndUpgradeSubwindows();
		ShowReleaseBuildTreePanelOnlyIfPopulated(buildingSession, originalMethod, source, allowOpenHiddenPanel: true);
		Homm3StrongholdTownLayers.SyncCurrentCityLayers();
		LogReleaseBuildSessionSnapshot(buildingSession, originalMethod);
	}

	private static void EnsureReleaseBuildTreeVisibleIfSelected(BhCityUISession citySession, MethodBase originalMethod, string source)
	{
		try
		{
			if (citySession == null || !IsActiveSceneCityInterior())
				return;
			var navigation = TryGetReleaseCityNavigation(citySession, originalMethod);
			if (navigation == null || TryReadCityNavigationState(navigation) != (int)ECityNavigation.BuildingsConstruction)
				return;
			LiftActiveReleaseTownPanelCanvas(GameSymbols.ReleaseTownUi.BuildingViewPanelCanvasName, source + "-active-panel");
			var buildingSession = TryGetReleaseCityBuildingSession(citySession, originalMethod);
			if (buildingSession == null)
				return;
			ShowReleaseBuildTreePanelOnlyIfPopulated(buildingSession, originalMethod, source, allowOpenHiddenPanel: false);
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"build-tree-selected-visible-failed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|source:" + source
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	internal static bool PrefixReleaseBuildingSessionBackAction(MethodBase __originalMethod, BhUIBuildingSession __instance)
	{
		return !TryHandleReleaseBuildingScreenBackAction(__instance, __originalMethod);
	}

	internal static bool PrefixReleaseHireCityBackAction(MethodBase __originalMethod, BhHireCityView __instance)
	{
		return !TryHandleReleaseHireScreenBackAction(__instance, __originalMethod);
	}

	internal static bool PrefixReleaseCityDayPanelButtonClick(MethodBase __originalMethod, BhDayPanelButtonManager __instance)
	{
		return !TryHandleReleaseCityDayPanelButtonClick(__instance, __originalMethod);
	}

	internal static bool PrefixReleaseCityDayPanelBackAction(MethodBase __originalMethod, BhDayPanel __instance)
	{
		return !TryHandleReleaseCityDayPanelBackAction(__instance, __originalMethod);
	}

	internal static bool PrefixReleaseCityDayPanelV2BackAction(MethodBase __originalMethod, object __instance)
	{
		return !TryHandleReleaseCityBackArrowFallback(__instance as Component, __originalMethod, "day-panel-v2-action");
	}

	internal static bool PrefixReleaseCityGenericButtonClick(MethodBase __originalMethod, BhGenericButton __instance)
	{
		return !TryHandleReleaseCityExitHudArrowClick(__instance, __originalMethod);
	}

	internal static bool PrefixReleaseCityGenericButtonBackAction(MethodBase __originalMethod, BhGenericButton __instance)
	{
		return !TryHandleReleaseCityExitHudArrowClick(__instance, __originalMethod);
	}

	internal static void AfterReleaseCityExitHudRefresh(MethodBase __originalMethod, BhButtonExitHud __instance)
	{
		TryPrepareReleaseCityExitHudBackArrow(__instance, __originalMethod);
	}

	internal static void AfterReleaseCityUpgradeUiShown(MethodBase __originalMethod, ScUpgradeUnits __instance)
	{
		try
		{
			if (__instance == null || !IsActiveSceneCityInterior())
				return;
			CloseReleaseCityBuildingAndHireSubwindows();
			EnsureReleaseTownScreenVisible(__instance, GameSymbols.ReleaseTownUi.UpgradeUnitPanelCanvasName, "upgrade-ui-shown");
			LogReleaseTownUiDiagnostic(
				"upgrade-ya-shown",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"upgrade-ya-shown-failed",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	internal static void AfterReleaseCityMarketUiShown(MethodBase __originalMethod, BhExchangeUISession __instance)
	{
		try
		{
			if (__instance == null || !IsActiveSceneCityInterior())
				return;
			CloseReleaseCityBuildingAndHireSubwindows();
			EnsureReleaseTownScreenVisible(__instance, GameSymbols.ReleaseTownUi.MarketViewPanelCanvasName, "market-view-shown");
			LogReleaseTownUiDiagnostic(
				"market-view-shown",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"market-view-shown-failed",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	internal static void AfterReleaseCityItemMarketUiShown(MethodBase __originalMethod, BhItemMarketUISession __instance)
	{
		try
		{
			if (__instance == null || !IsActiveSceneCityInterior())
				return;
			CloseReleaseCityBuildingAndHireSubwindows();
			EnsureReleaseTownScreenVisible(__instance, GameSymbols.ReleaseTownUi.ItemMarketPanelCanvasName, "item-market-shown");
			LogReleaseTownUiDiagnostic(
				"item-market-shown",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"item-market-shown-failed",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	internal static void AfterReleaseCityArtifactChangerUiShown(MethodBase __originalMethod, BhArtifactChanger __instance)
	{
		try
		{
			if (__instance == null || !IsActiveSceneCityInterior())
				return;
			CloseReleaseCityBuildingAndHireSubwindows();
			EnsureReleaseTownScreenVisible(__instance, GameSymbols.ReleaseTownUi.ArtifactChangerPanelCanvasName, "artifact-changer-shown");
			LogReleaseTownUiDiagnostic(
				"artifact-changer-shown",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"artifact-changer-shown-failed",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	internal static void AfterReleaseCityTavernUiShown(MethodBase __originalMethod, BhHeroBuySession __instance)
	{
		try
		{
			if (__instance == null || !IsActiveSceneCityInterior())
				return;
			CloseReleaseCityBuildingAndHireSubwindows();
			EnsureReleaseTownScreenVisible(__instance, GameSymbols.ReleaseTownUi.HeroBuyPanelCanvasName, "tavern-hero-buy-shown");
			LogReleaseTownUiDiagnostic(
				"tavern-hero-buy-shown",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"tavern-hero-buy-shown-failed",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static bool TryHandleReleaseCityBackNavigation(BhNavigationView navigation, MethodBase originalMethod)
	{
		try
		{
			if (navigation == null || !IsActiveComponent(navigation))
				return false;
			if (!IsActiveSceneCityInterior())
				return false;
			var navState = TryReadCityNavigationState(navigation);
			if (navState != 0 && navState != 1)
				return false;

			var session = FindCitySessionForNavigation(navigation);
			if (session == null)
				return false;

			if (!TryCloseReleaseCitySubwindow(session, navState, (BhDayPanelButtonManager)null, out var closeTarget))
				return false;

			LogReleaseTownUiDiagnostic(
				"back-navigation-close",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|state:" + navState
					+ "|target:" + closeTarget.GetType().FullName);
			ApplyCustomCityBackdrop();
			Homm3StrongholdTownLayers.SyncCurrentCityLayers();
			return true;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"back-navigation-close-failed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
			return false;
		}
	}

	private static bool TryHandleReleaseBuildingScreenBackAction(BhUIBuildingSession session, MethodBase originalMethod)
	{
		try
		{
			if (session == null || !IsActiveSceneCityInterior() || !IsReleaseCityBackScreenCandidate(session))
				return false;
			session.OnExitBtn();
			LogReleaseTownUiBackMainDiagnostic(
				"back-screen-close",
				"method:" + DescribeMethod(originalMethod)
					+ "|target:" + session.GetType().FullName
					+ "|path:" + DescribeUnityPath(session.gameObject));
			ApplyCustomCityBackdrop();
			Homm3StrongholdTownLayers.SyncCurrentCityLayers();
			return true;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiBackMainDiagnostic(
				"back-screen-close-failed",
				"method:" + DescribeMethod(originalMethod)
					+ "|target:building"
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
			return false;
		}
	}

	private static bool TryHandleReleaseHireScreenBackAction(BhHireCityView view, MethodBase originalMethod)
	{
		try
		{
			if (view == null || !IsActiveSceneCityInterior() || !IsReleaseCityBackScreenCandidate(view))
				return false;
			view.OnExitBtn();
			LogReleaseTownUiBackMainDiagnostic(
				"back-screen-close",
				"method:" + DescribeMethod(originalMethod)
					+ "|target:" + view.GetType().FullName
					+ "|path:" + DescribeUnityPath(view.gameObject));
			ApplyCustomCityBackdrop();
			Homm3StrongholdTownLayers.SyncCurrentCityLayers();
			return true;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiBackMainDiagnostic(
				"back-screen-close-failed",
				"method:" + DescribeMethod(originalMethod)
					+ "|target:hire"
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
			return false;
		}
	}

	private static bool TryHandleReleaseCityDayPanelButtonClick(BhDayPanelButtonManager button, MethodBase originalMethod)
	{
		try
		{
			if (button == null || !IsActiveComponent(button))
				return false;
			if (!IsActiveSceneCityInterior())
				return false;

			var session = FindCitySessionForDayPanelButton(button);
			if (session == null)
				return TryHandleReleaseCityOrphanDayPanelButton(button, originalMethod);
			if (!TryCloseReleaseCitySubwindow(session, -1, button, out var closeTarget))
				return false;

			LogReleaseTownUiDiagnostic(
				"back-navigation-close",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|state:day-panel"
					+ "|target:" + closeTarget.GetType().FullName);
			ApplyCustomCityBackdrop();
			Homm3StrongholdTownLayers.SyncCurrentCityLayers();
			return true;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"back-navigation-close-failed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
			return false;
		}
	}

	private static bool TryHandleReleaseCityOrphanDayPanelButton(BhDayPanelButtonManager button, MethodBase originalMethod)
	{
		try
		{
			if (button == null || button.gameObject == null || !IsActiveSceneCityInterior())
				return false;
			if (IsReleaseCityTownExitControl(button.gameObject))
				return TryHandleReleaseCityTownExitControl(button, originalMethod, "day-panel-button");
			var text = ReadComponentText(button);
			LogReleaseTownUiBackMainDiagnostic(
				"orphan-day-panel-button-disabled",
				"method:" + DescribeMethod(originalMethod)
					+ "|path:" + DescribeUnityPath(button.gameObject)
					+ "|text:" + (string.IsNullOrWhiteSpace(text) ? "(none)" : text));
			button.gameObject.SetActive(false);
			return true;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiBackMainDiagnostic(
				"orphan-day-panel-button-disable-failed",
				"method:" + DescribeMethod(originalMethod)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
			return false;
		}
	}

	private static bool TryHandleReleaseCityDayPanelBackAction(BhDayPanel panel, MethodBase originalMethod)
	{
		try
		{
			if (panel == null || !IsActiveComponent(panel))
				return false;
			if (!IsActiveSceneCityInterior())
				return false;

			var session = FindCitySessionForDayPanel(panel);
			if (session == null)
				return false;
			if (!TryCloseReleaseCitySubwindow(session, -1, panel, out var closeTarget))
				return false;

			LogReleaseTownUiDiagnostic(
				"back-navigation-close",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|state:day-panel-action"
					+ "|target:" + closeTarget.GetType().FullName);
			ApplyCustomCityBackdrop();
			Homm3StrongholdTownLayers.SyncCurrentCityLayers();
			return true;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"back-navigation-close-failed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
			return false;
		}
	}

	private static bool TryHandleReleaseCityExitHudArrowClick(BhGenericButton button, MethodBase originalMethod)
	{
		try
		{
			if (button == null || !IsActiveSceneCityInterior())
				return false;
			if (IsReleaseCityTownExitControl(button.gameObject))
				return TryHandleReleaseCityTownExitControl(button, originalMethod, "generic-button");
			var isArrow = IsReleaseCityExitHudArrowButton(button);
			var isBuildingTooltipBack = IsReleaseCityBuildingTooltipBackButton(button);
			LogReleaseTownUiBackMainDiagnostic(
				"back-generic-button-candidate",
				"method:" + DescribeMethod(originalMethod)
					+ "|isExitHudArrow:" + isArrow
					+ "|isBuildingTooltipBack:" + isBuildingTooltipBack
					+ "|path:" + DescribeUnityPath(button.gameObject));
			if (!isArrow && !isBuildingTooltipBack)
				return false;
			return TryHandleReleaseCityBackArrowFallback(button, originalMethod, isArrow ? "exit-hud-arrow" : "building-tooltip-back");
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"back-navigation-close-failed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
			return false;
		}
	}

	private static bool IsReleaseCityBuildingTooltipBackButton(BhGenericButton button)
	{
		if (button == null || button.gameObject == null)
			return false;
		var path = DescribeUnityPath(button.gameObject).Replace('\\', '/');
		var isBuildingTooltip =
			path.IndexOf("TOOLTIP UI CANVAS RAYCAST/BUILDING/", StringComparison.OrdinalIgnoreCase) >= 0
			|| path.IndexOf("TOOLTIP UI CANVAS RAYCAST/BUILDING(Clone)/", StringComparison.OrdinalIgnoreCase) >= 0;
		if (!isBuildingTooltip)
			return false;
		var text = ReadReleaseCityGenericButtonText(button);
		if (!string.IsNullOrWhiteSpace(text))
		{
			if (ContainsAny(text, "build", "construct", "buy", "upgrade", "hire", "recruit", "apply", "ok"))
				return false;
			return ContainsAny(text, "back", "close", "return");
		}
		if (path.IndexOf("/ROOT/MIDDLE/GameObject/GENERIC BUTTON", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			LogReleaseTownUiBackMainDiagnostic(
				"building-tooltip-back-path-no-text",
				"path:" + path);
			return true;
		}
		return false;
	}

	private static string ReadReleaseCityGenericButtonText(BhGenericButton button)
	{
		if (button == null)
			return null;
		try
		{
			if (TryReadMember(button, typeof(BhGenericButton), "label") is TMPro.TextMeshProUGUI label
			    && !string.IsNullOrWhiteSpace(label.text))
				return label.text;
		}
		catch { }
		try
		{
			var label = button.GetComponentInChildren<TMPro.TextMeshProUGUI>(true);
			if (label != null && !string.IsNullOrWhiteSpace(label.text))
				return label.text;
		}
		catch { }
		return null;
	}

	private static string ReadComponentText(Component component)
	{
		if (component == null)
			return null;
		try
		{
			var label = component.GetComponentInChildren<TMPro.TextMeshProUGUI>(true);
			if (label != null && !string.IsNullOrWhiteSpace(label.text))
				return label.text;
		}
		catch { }
		return null;
	}

	private static bool ContainsAny(string text, params string[] needles)
	{
		if (string.IsNullOrWhiteSpace(text) || needles == null)
			return false;
		for (var i = 0; i < needles.Length; i++)
		{
			var needle = needles[i];
			if (!string.IsNullOrWhiteSpace(needle)
			    && text.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0)
				return true;
		}
		return false;
	}

	internal static void AfterReleaseCityHireUiShown(MethodBase __originalMethod, BhHireCityView __instance)
	{
		try
		{
			if (__instance == null || !IsActiveSceneCityInterior())
				return;
			CloseReleaseCityBuildingAndUpgradeSubwindows();
			EnsureReleaseTownScreenVisible(__instance, GameSymbols.ReleaseTownUi.HireViewPanelCanvasName, "hire-view-shown");
			Homm3CustomUiIconHook.TryApplyHireCityView(__instance, "ModActions.AfterReleaseCityHireUiShown");
			LogReleaseTownUiDiagnostic(
				"hire-view-shown",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"hire-view-shown-failed",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static void EnsureReleaseTownScreenVisible(
		Component screenComponent,
		string panelCanvasName,
		string source,
		bool requireAlreadyOpenForBuildTree = true)
	{
		try
		{
			if (screenComponent == null || !IsActiveSceneCityInterior())
				return;
			var fraction = GetCurrentCityFraction();
			if (string.IsNullOrWhiteSpace(fraction)
			    || !Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction))
				return;
			var targetSortingOrder = GetReleaseTownScreenSortingOrder(screenComponent, panelCanvasName);

			var panelCanvas = FindCanvasByName(panelCanvasName, source);
			if (requireAlreadyOpenForBuildTree && IsBuildTreePanel(panelCanvasName) && !IsReleaseTownScreenAlreadyOpen(screenComponent, panelCanvas))
			{
				LogReleaseTownUiDiagnostic(
					"town-screen-visible-skip-inactive-build",
					"source:" + source
						+ "|panel:" + panelCanvasName
						+ "|fraction:" + fraction
						+ "|screen:" + screenComponent.GetType().FullName);
				return;
			}

			var changed = false;
			var go = screenComponent.gameObject;
			if (go != null)
			{
				ForceVisible(go);
				changed = true;
			}

			var screen = screenComponent as BhScreen;
			if (screen != null)
			{
				try
				{
					if (screen.canvas != null && !screen.canvas.enabled)
					{
						screen.canvas.enabled = true;
						changed = true;
					}
					if (screen.canvas != null)
					{
						if (!screen.canvas.overrideSorting)
						{
							screen.canvas.overrideSorting = true;
							changed = true;
						}
						if (screen.canvas.sortingOrder < targetSortingOrder)
						{
							screen.canvas.sortingOrder = targetSortingOrder;
							changed = true;
						}
					}
				}
                catch (Exception ex)
                {
                    LogReleaseTownUiEvidenceDiagnostic(
                        "town-screen-visible-canvas-lift-failed",
                        "source:" + source
                            + "|panel:" + panelCanvasName
                            + "|screen:" + screenComponent.GetType().FullName
                            + "|error:" + ex.GetType().Name + ":" + ex.Message);
                }
			}

			if (ForceReleaseTownScreenBodyVisible(screenComponent))
				changed = true;

			if (panelCanvas != null)
			{
				if (DemoteReleaseTownPeerPanelCanvases(panelCanvasName, source))
					changed = true;
				if (!panelCanvas.enabled)
				{
					panelCanvas.enabled = true;
					changed = true;
				}
				if (panelCanvas.gameObject != null)
				{
					ForceVisible(panelCanvas.gameObject);
					changed = true;
				}
				if (!panelCanvas.overrideSorting)
				{
					panelCanvas.overrideSorting = true;
					changed = true;
				}
				if (panelCanvas.sortingOrder < targetSortingOrder)
				{
					panelCanvas.sortingOrder = targetSortingOrder;
					changed = true;
				}
			}
			if (KeepReleaseNavigationCanvasesAbovePanel(source))
				changed = true;

			if (changed && !_loggedCityMenuCanvasLift)
			{
				_loggedCityMenuCanvasLift = true;
				LogReleaseTownUiDiagnostic(
					"town-screen-visible",
					"source:" + source
						+ "|panel:" + panelCanvasName
						+ "|fraction:" + fraction
						+ "|screen:" + screenComponent.GetType().FullName);
			}
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"town-screen-visible-failed",
				"source:" + source
					+ "|panel:" + panelCanvasName
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}


	private static int GetReleaseTownScreenSortingOrder(Component screenComponent, string panelCanvasName)
	{
		return GetReleaseTownActivePanelSortingOrder();
	}
	private static bool IsBuildTreePanel(string panelCanvasName)
	{
		return string.Equals(panelCanvasName, GameSymbols.ReleaseTownUi.BuildingViewPanelCanvasName, StringComparison.Ordinal);
	}

	private static string TryGetReleaseTownPrimaryPanelCanvasName(ECityNavigation navigation)
	{
		switch (navigation)
		{
			case ECityNavigation.BuildingsConstruction:
				return GameSymbols.ReleaseTownUi.BuildingViewPanelCanvasName;
			case ECityNavigation.Hire:
				return GameSymbols.ReleaseTownUi.HireViewPanelCanvasName;
			case ECityNavigation.Market:
				return GameSymbols.ReleaseTownUi.MarketViewPanelCanvasName;
			case ECityNavigation.Tavern:
				return GameSymbols.ReleaseTownUi.HeroBuyPanelCanvasName;
			case ECityNavigation.Upgrade:
				return GameSymbols.ReleaseTownUi.UpgradeUnitPanelCanvasName;
			case ECityNavigation.Items:
				return GameSymbols.ReleaseTownUi.ItemMarketPanelCanvasName;
			case ECityNavigation.Universal:
				return GameSymbols.ReleaseTownUi.ArtifactChangerPanelCanvasName;
			default:
				return null;
		}
	}

	private static bool LiftReleaseTownNavigationTargetPanel(ECityNavigation navigation, string source)
	{
		var panelCanvasName = TryGetReleaseTownPrimaryPanelCanvasName(navigation);
		if (!string.IsNullOrWhiteSpace(panelCanvasName)
		    && LiftActiveReleaseTownPanelCanvas(panelCanvasName, source + "-active-panel"))
		{
			return true;
		}
		return LiftAnyActiveReleaseTownPrimaryPanelCanvas(source);
	}

	private static bool IsReleaseTownSessionUiPanelCanvasName(string panelCanvasName)
	{
		return string.Equals(panelCanvasName, GameSymbols.ReleaseTownUi.MarketViewPanelCanvasName, StringComparison.Ordinal)
		       || string.Equals(panelCanvasName, GameSymbols.ReleaseTownUi.ItemMarketPanelCanvasName, StringComparison.Ordinal)
		       || string.Equals(panelCanvasName, GameSymbols.ReleaseTownUi.ArtifactChangerPanelCanvasName, StringComparison.Ordinal)
		       || string.Equals(panelCanvasName, GameSymbols.ReleaseTownUi.HeroBuyPanelCanvasName, StringComparison.Ordinal);
	}


	/// <summary>
	/// Owned cityFactory towns paint HotA art in the Unity world scene, not as CanvasCityPanel
	/// posters. The continuous / sortingOrder panel lift exists to keep native menus above Route A
	/// UI art; applying it on the world path is unnecessary and can fight native open/close.
	/// Explicit open helpers (ShowReleaseBuildTreePanelOnlyIfPopulated, CloseReleaseCityHire…) stay.
	/// </summary>
	private static bool ShouldSkipRouteATownPanelLift()
	{
		var fraction = GetCurrentCityFraction();
		return Homm3FactoryCitySceneRegistrar.OwnsActiveFactoryCityWorld(fraction);
	}

	private static bool LiftActiveReleaseTownPanelCanvas(string panelCanvasName, string source)
	{
		try
		{
			if (string.IsNullOrWhiteSpace(panelCanvasName) || !IsActiveSceneCityInterior())
				return false;
			if (ShouldSkipRouteATownPanelLift())
				return false;
			var fraction = GetCurrentCityFraction();
			if (string.IsNullOrWhiteSpace(fraction)
				|| !Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction))
			{
				return false;
			}

			var cityRoot = FindCityPanelRectTransform();
			var panelCanvas = FindCanvasByName(panelCanvasName, source);
			if (panelCanvas == null
				|| panelCanvas.gameObject == null
				|| !panelCanvas.enabled
				|| !IsReleaseTownPanelCanvasEligibleForLift(panelCanvas, cityRoot, panelCanvasName))
			{
				return false;
			}

			var changed = false;
			if (DemoteReleaseTownPeerPanelCanvases(panelCanvasName, source))
				changed = true;
			if (!panelCanvas.overrideSorting)
			{
				panelCanvas.overrideSorting = true;
				changed = true;
			}
			var activeOrder = GetReleaseTownActivePanelSortingOrder();
			if (panelCanvas.sortingOrder < activeOrder)
			{
				panelCanvas.sortingOrder = activeOrder;
				changed = true;
			}
			if (EnsureLiftedTownCanvasGraphicRaycaster(panelCanvas, source))
				changed = true;
			if (KeepReleaseNavigationCanvasesAbovePanel(source))
				changed = true;

			if (changed)
			{
				LogReleaseTownUiDiagnostic(
					"town-active-panel-lift",
					"source:" + (source ?? "null")
						+ "|panel:" + panelCanvasName
						+ "|fraction:" + fraction
						+ "|order:" + panelCanvas.sortingOrder);
			}
			return changed;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"town-active-panel-lift-failed",
				"source:" + (source ?? "null")
					+ "|panel:" + (panelCanvasName ?? "null")
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
		return false;
	}

	private static bool LiftAnyActiveReleaseTownPrimaryPanelCanvas(string source)
	{
		// One eligibility pass over the cached CityUI snapshot, then at most one lift.
		// Previously tried all 7 panel names, each doing FindCanvasByName + demote + nav walks.
		try
		{
			if (!IsActiveSceneCityInterior())
				return false;
			if (ShouldSkipRouteATownPanelLift())
				return false;
			var fraction = GetCurrentCityFraction();
			if (string.IsNullOrWhiteSpace(fraction)
			    || !Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction))
			{
				return false;
			}

			var cityRoot = FindCityPanelRectTransform();
			Canvas active = null;
			string activeName = null;
			ForEachCityUiCanvas(canvas =>
			{
				if (active != null || canvas == null || canvas.gameObject == null || !canvas.enabled)
					return;
				var name = canvas.gameObject.name ?? string.Empty;
				if (!ReleaseTownPrimaryPanelCanvasNameSet.Contains(name))
					return;
				if (!IsReleaseTownPanelCanvasEligibleForLift(canvas, cityRoot, name))
					return;
				active = canvas;
				activeName = name;
			});
			if (active == null || string.IsNullOrEmpty(activeName))
				return false;
			return LiftActiveReleaseTownPanelCanvas(activeName, source + "-active-panel");
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"town-active-panel-lift-any-failed",
				"source:" + (source ?? "null") + "|error:" + ex.GetType().Name + ":" + ex.Message);
			return false;
		}
	}

	internal static void ReassertCustomTownNativePanelOrdering(string source)
	{
		try
		{
			if (!IsActiveSceneCityInterior())
				return;
			if (ShouldSkipRouteATownPanelLift())
				return;
			var fraction = GetCurrentCityFraction();
			if (string.IsNullOrWhiteSpace(fraction)
			    || !Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction))
				return;

			// Keep reusing the proven native-panel lift path after custom town layer sync.
			// Town layers belong immediately above OfflineUnlockCityBackdrop; native town
			// menus must stay on their own higher-sorted canvases.
			LiftAnyActiveReleaseTownPrimaryPanelCanvas(source ?? "town-layer-sync");
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"town-panel-order-reassert-failed",
				"source:" + (source ?? "null") + "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static int _lastTownPresentationPanelReconcileFrame = -1;

	internal static void ReconcileCustomTownPresentationForNativePanels()
	{
		try
		{
			if (!IsActiveSceneCityInterior())
				return;
			// Owned cityFactory: no Route A UI art to stay above — skip continuous lift.
			if (ShouldSkipRouteATownPanelLift())
				return;
			var frame = Time.frameCount;
			if (frame == _lastTownPresentationPanelReconcileFrame)
				return;
			// Hot path used to thrash every frame (lift pump): full scene canvas walks + Overlay rewrites.
			// Keep a short post-entry window, then rare maintenance only.
			if (frame > _customTownUiLiftUntilFrame && frame % 30 != 0)
				return;
			_lastTownPresentationPanelReconcileFrame = frame;
			var fraction = GetCurrentCityFraction();
			if (string.IsNullOrWhiteSpace(fraction)
				|| !Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction))
			{
				return;
			}

			LiftAnyActiveReleaseTownPrimaryPanelCanvas("frame-reconcile-town-panel");
			EnsureNativeTownMenusAboveCustomArt();
			if (frame <= _customTownUiLiftUntilFrame || frame % 30 == 0)
				ReassertKnownCityMenuCanvasRaycasters("frame-reconcile-town-panel");
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"town-presentation-panel-reconcile-failed",
				ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static bool IsReleaseTownScreenAlreadyOpen(Component screenComponent, Canvas panelCanvas)
	{
		try
		{
			if (screenComponent == null)
				return false;
			if (screenComponent is BhUIBuildingSession buildingSession)
			{
				var root = TryReadIl2CppObjectField<GameObject>(
					buildingSession,
					typeof(BhUIBuildingSession),
					Il2CppClassPointerStore<BhUIBuildingSession>.NativeClassPtr,
					GameSymbols.ReleaseTownUi.BuildingSessionRoot,
					"building-screen-root-field-missing",
					null);
				if (root != null)
					return root.activeInHierarchy;
			}
			if (panelCanvas != null && panelCanvas.gameObject != null && panelCanvas.gameObject.activeInHierarchy)
				return true;
			if (!(screenComponent is BhUIBuildingSession) && screenComponent.gameObject != null && screenComponent.gameObject.activeInHierarchy)
				return true;
		}
		catch
		{
		}
		return false;
	}

	private static bool ForceReleaseTownScreenBodyVisible(Component screenComponent)
	{
		var changed = false;
		try
		{
			if (screenComponent is BhUIBuildingSession buildingSession)
			{
				changed |= ForceVisibleIfFound(TryReadIl2CppObjectField<GameObject>(
					buildingSession,
					typeof(BhUIBuildingSession),
					Il2CppClassPointerStore<BhUIBuildingSession>.NativeClassPtr,
					GameSymbols.ReleaseTownUi.BuildingSessionRoot,
					"building-screen-root-field-missing",
					null));
				changed |= ForceVisibleIfFound(TryReadIl2CppObjectField<Component>(
					buildingSession,
					typeof(BhUIBuildingSession),
					Il2CppClassPointerStore<BhUIBuildingSession>.NativeClassPtr,
					GameSymbols.ReleaseTownUi.BuildingSessionNavigation,
					"building-screen-navigation-field-missing",
					null));
			}
			else if (screenComponent is BhHireCityView hireView)
			{
				changed |= ForceVisibleIfFound(TryReadIl2CppObjectField<Component>(
					hireView,
					typeof(BhHireCityView),
					Il2CppClassPointerStore<BhHireCityView>.NativeClassPtr,
					GameSymbols.ReleaseTownUi.HireViewNavigation,
					"hire-view-navigation-field-missing",
					null));
			}
			else if (screenComponent is ScUpgradeUnits upgradeView)
			{
				for (var i = 0; i < GameSymbols.ReleaseTownUi.UpgradeViewBodyComponentFields.Length; i++)
				{
					changed |= ForceVisibleIfFound(
						TryReadMemberFieldOnly(upgradeView, typeof(ScUpgradeUnits), GameSymbols.ReleaseTownUi.UpgradeViewBodyComponentFields[i]) as Component);
				}
			}
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"town-screen-body-visible-failed",
				screenComponent.GetType().FullName + "|" + ex.GetType().Name + ":" + ex.Message);
		}
		return changed;
	}

	private static bool ForceVisibleIfFound(Component component)
	{
		return component != null && ForceVisibleIfFound(component.gameObject);
	}

	private static bool ForceVisibleIfFound(GameObject gameObject)
	{
		if (gameObject == null)
			return false;
		ForceVisible(gameObject);
		return true;
	}

	private static bool KeepReleaseNavigationCanvasesAbovePanel(string source)
	{
		var changed = false;
		try
		{
			var cityRoot = FindCityPanelRectTransform();
			var navigationOrder = GetReleaseTownNavigationSortingOrder();
			ForEachCityUiCanvas(canvas =>
			{
				if (canvas == null || !string.Equals(canvas.gameObject?.name, "CityNavigation", StringComparison.Ordinal))
					return;
				if (!IsCanvasInActiveCityScene(canvas, cityRoot, requireActive: true))
					return;
				ForceVisible(canvas.gameObject);
				if (!canvas.enabled)
				{
					canvas.enabled = true;
					changed = true;
				}
				if (!canvas.overrideSorting)
				{
					canvas.overrideSorting = true;
					changed = true;
				}
				if (canvas.sortingOrder < navigationOrder)
				{
					canvas.sortingOrder = navigationOrder;
					changed = true;
				}
			});
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"town-navigation-canvas-lift-failed",
				"source:" + (source ?? "null")
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
		return changed;
	}

	private static bool DemoteReleaseTownPeerPanelCanvases(string activePanelCanvasName, string source)
	{
		var changed = false;
		try
		{
			var cityRoot = FindCityPanelRectTransform();
			var activeOrder = GetReleaseTownActivePanelSortingOrder();
			ForEachCityUiCanvas(canvas =>
			{
				var name = canvas == null ? null : canvas.gameObject?.name;
				if (string.IsNullOrWhiteSpace(name)
				    || string.Equals(name, activePanelCanvasName, StringComparison.Ordinal)
				    || string.Equals(name, "CanvasCityPanel", StringComparison.Ordinal)
				    || string.Equals(name, "GarnisonPanel", StringComparison.Ordinal)
				    || string.Equals(name, "CanvasCityTechHUDPanel", StringComparison.Ordinal)
				    || string.Equals(name, "CityNavigation", StringComparison.Ordinal)
				    || !CityMenuCanvasNames.Contains(name))
				{
					return;
				}
				if (!IsCanvasInActiveCityScene(canvas, cityRoot, requireActive: true))
					return;

				if (canvas.sortingOrder >= activeOrder)
				{
					canvas.sortingOrder = activeOrder - 20;
					changed = true;
				}
			});
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"town-peer-panel-demote-failed",
				"source:" + (source ?? "null")
					+ "|activePanel:" + (activePanelCanvasName ?? "null")
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
		return changed;
	}

	private static bool IsCanvasInActiveCityScene(Canvas canvas, RectTransform cityRoot, bool requireActive)
	{
		if (canvas == null || canvas.gameObject == null)
			return false;
		var go = canvas.gameObject;
		if (requireActive && !go.activeInHierarchy)
			return false;
		var activeScene = SceneManager.GetActiveScene();
		if (!activeScene.IsValid() || !IsCityInteriorSceneName(activeScene.name))
			return false;
		var scene = go.scene;
		if (!scene.IsValid() || (scene.handle != activeScene.handle && !string.Equals(scene.name, "CityUI", StringComparison.Ordinal)))
			return false;
		if (cityRoot == null || cityRoot.gameObject == null)
			return true;
		var rootScene = cityRoot.gameObject.scene;
		return !rootScene.IsValid()
			|| rootScene.handle == scene.handle
			|| (string.Equals(rootScene.name, "CityUI", StringComparison.Ordinal) && string.Equals(scene.name, "CityUI", StringComparison.Ordinal));
	}

	private static bool IsReleaseTownPanelCanvasEligibleForLift(Canvas canvas, RectTransform cityRoot, string panelCanvasName)
	{
		if (canvas == null || canvas.gameObject == null || !canvas.gameObject.activeInHierarchy)
			return false;
		if (IsCanvasInActiveCityScene(canvas, cityRoot, requireActive: true))
			return true;
		// Marketplace / item-market screens are Session.UI and may live outside CityUI.
		return IsActiveSceneCityInterior()
		       && IsReleaseTownSessionUiPanelCanvasName(panelCanvasName);
	}

	private static void TryPrepareReleaseCityExitHudBackArrow(BhButtonExitHud hud, MethodBase originalMethod)
	{
		try
		{
			if (hud == null || !IsActiveSceneCityInterior())
				return;
			if (!HasClosableReleaseCitySubwindow())
				return;
			var arrow = TryReadMember(hud, typeof(BhButtonExitHud), "buttonArrow") as BhGenericButton;
			if (arrow == null || arrow.gameObject == null)
				return;
			ForceVisible(arrow.gameObject);
			TrySetMember(arrow, typeof(BhGenericButton), "clickable", true);
			TryInvokeMember(arrow, typeof(BhGenericButton), "sre", true);
			TryInvokeMember(arrow, typeof(BhGenericButton), "srf", true);
			try
			{
				arrow.Init(new Action(ReleaseCityExitHudBackArrowAction), null, null);
			}
			catch (Exception ex)
			{
				LogReleaseTownUiBackMainDiagnostic(
					"back-exit-hud-bind-failed",
					"method:" + DescribeMethod(originalMethod)
						+ "|path:" + DescribeUnityPath(arrow.gameObject)
						+ "|error:" + ex.GetType().Name + ":" + ex.Message);
				return;
			}
			LogReleaseTownUiBackMainDiagnostic(
				"back-exit-hud-bound",
				"method:" + DescribeMethod(originalMethod)
					+ "|path:" + DescribeUnityPath(arrow.gameObject)
					+ "|activeWindows:" + DescribeReleaseCitySubwindowCandidates());
		}
		catch (Exception ex)
		{
			LogReleaseTownUiBackMainDiagnostic(
				"back-exit-hud-prepare-failed",
				"method:" + DescribeMethod(originalMethod)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static void ReleaseCityExitHudBackArrowAction()
	{
		TryHandleReleaseCityBackArrowFallback(null, null, "exit-hud-bound-action");
	}

	private static bool HasClosableReleaseCitySubwindow()
	{
		try
		{
			foreach (var session in EnumerateReleaseCitySessions())
			{
				if (session == null)
					continue;
				var buildingSession = TryReadMember(session, typeof(BhCityUISession), "buildingSession") as BhUIBuildingSession;
				if (IsActiveComponent(buildingSession))
					return true;
				var hireView = TryReadMember(session, typeof(BhCityUISession), "hire") as BhHireCityView;
				if (IsActiveComponent(hireView))
					return true;
			}
		}
		catch
		{
		}
		return false;
	}

	private static bool TryHandleReleaseCityBackArrowFallback(Component source, MethodBase originalMethod, string sourceKind)
	{
		try
		{
			if (!IsActiveSceneCityInterior())
				return false;
			if (source != null && !IsActiveComponent(source))
				return false;

			var scanned = 0;
			foreach (var session in EnumerateReleaseCitySessions())
			{
				if (session == null)
					continue;
				scanned++;
				if (!TryCloseReleaseCitySubwindow(session, -1, (BhDayPanelButtonManager)null, out var closeTarget))
					continue;

				LogReleaseTownUiDiagnostic(
					"back-navigation-close",
					"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
						+ "|state:" + sourceKind
						+ "|target:" + closeTarget.GetType().FullName);
				ApplyCustomCityBackdrop();
				Homm3StrongholdTownLayers.SyncCurrentCityLayers();
				return true;
			}

			LogReleaseTownUiBackMainDiagnostic(
				"back-fallback-no-target",
				"method:" + DescribeMethod(originalMethod)
					+ "|state:" + sourceKind
					+ "|source:" + (source == null ? "null" : DescribeUnityPath(source.gameObject))
					+ "|sessions:" + scanned
					+ "|activeWindows:" + DescribeReleaseCitySubwindowCandidates());
			return false;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"back-navigation-close-failed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
			return false;
		}
	}

	private static bool IsReleaseCityTownExitControl(GameObject gameObject)
	{
		if (gameObject == null)
			return false;
		var path = DescribeUnityPath(gameObject).Replace('\\', '/');
		return path.IndexOf("CanvasCityTechHUDPanel/Roor/EndDayPanel2V2/BackClock/", StringComparison.OrdinalIgnoreCase) >= 0
			&& (path.EndsWith("/Door", StringComparison.OrdinalIgnoreCase)
				|| path.EndsWith("/ButtonManager", StringComparison.OrdinalIgnoreCase));
	}

	private static bool TryHandleReleaseCityTownExitControl(Component source, MethodBase originalMethod, string sourceKind)
	{
		try
		{
			if (source == null || !IsActiveSceneCityInterior())
				return false;
			var session = FindBestActiveReleaseCitySession();
			if (session == null)
			{
				LogReleaseTownUiBackMainDiagnostic(
					"town-exit-no-session",
					"method:" + DescribeMethod(originalMethod)
						+ "|sourceKind:" + sourceKind
						+ "|path:" + DescribeUnityPath(source.gameObject));
				return false;
			}
			LogReleaseTownUiBackMainDiagnostic(
				"town-exit-routed",
				"method:" + DescribeMethod(originalMethod)
					+ "|sourceKind:" + sourceKind
					+ "|path:" + DescribeUnityPath(source.gameObject));
			session.OnExitBtn();
			return true;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiBackMainDiagnostic(
				"town-exit-route-failed",
				"method:" + DescribeMethod(originalMethod)
					+ "|sourceKind:" + sourceKind
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
			return false;
		}
	}

	private static bool IsReleaseCityExitHudArrowButton(BhGenericButton button)
	{
		if (button == null)
			return false;
		try
		{
			foreach (var hud in Resources.FindObjectsOfTypeAll<BhButtonExitHud>())
			{
				if (hud == null || !IsActiveComponent(hud))
					continue;
				var arrow = TryReadMember(hud, typeof(BhButtonExitHud), "buttonArrow") as BhGenericButton;
				if (SameIl2CppObject(arrow, button))
					return true;
			}
		}
		catch
		{
		}
		return false;
	}

	private static bool TryCloseReleaseCitySubwindow(BhCityUISession session, int preferredState, BhDayPanelButtonManager button, out Component closeTarget)
	{
		return TryCloseReleaseCitySubwindow(session, preferredState, button, null, out closeTarget);
	}

	private static bool TryCloseReleaseCitySubwindow(BhCityUISession session, int preferredState, BhDayPanel panel, out Component closeTarget)
	{
		return TryCloseReleaseCitySubwindow(session, preferredState, null, panel, out closeTarget);
	}

	private static bool TryCloseReleaseCitySubwindow(BhCityUISession session, int preferredState, BhDayPanelButtonManager button, BhDayPanel panel, out Component closeTarget)
	{
		closeTarget = null;
		if (session == null)
			return false;

		if (preferredState != 1 && TryCloseReleaseBuildingSubwindow(session, button, panel, out closeTarget))
			return true;
		if (preferredState != 0 && TryCloseReleaseHireSubwindow(session, button, panel, out closeTarget))
			return true;
		return false;
	}

	private static bool TryCloseReleaseBuildingSubwindow(BhCityUISession session, BhDayPanelButtonManager button, BhDayPanel panel, out Component closeTarget)
	{
		closeTarget = null;
		var buildingSession = TryReadMember(session, typeof(BhCityUISession), "buildingSession") as BhUIBuildingSession;
		if (!IsActiveComponent(buildingSession))
			return false;
		if (button != null || panel != null)
		{
			var exitButton = TryReadMember(buildingSession, typeof(BhUIBuildingSession), "exitButton") as BhDayPanel;
			if (button != null && !IsDayPanelForButton(exitButton, button))
				return false;
			if (panel != null && !SameIl2CppObject(exitButton, panel))
				return false;
		}
		buildingSession.OnExitBtn();
		closeTarget = buildingSession;
		return true;
	}

	private static bool TryCloseReleaseHireSubwindow(BhCityUISession session, BhDayPanelButtonManager button, BhDayPanel panel, out Component closeTarget)
	{
		closeTarget = null;
		var hireView = TryReadMember(session, typeof(BhCityUISession), "hire") as BhHireCityView;
		if (!IsActiveComponent(hireView))
			return false;
		if (button != null || panel != null)
		{
			var dayPanel = TryReadMember(hireView, typeof(BhHireCityView), "dayPanel") as BhDayPanel;
			if (button != null && !IsDayPanelForButton(dayPanel, button))
				return false;
			if (panel != null && !SameIl2CppObject(dayPanel, panel))
				return false;
		}
		hireView.OnExitBtn();
		closeTarget = hireView;
		return true;
	}

	private static void CloseReleaseCityBuildingAndHireSubwindows()
	{
		foreach (var session in EnumerateReleaseCitySessions())
		{
			if (session == null)
				continue;
			if (TryCloseReleaseBuildingSubwindow(session, null, null, out _))
				continue;
			TryCloseReleaseHireSubwindow(session, null, null, out _);
		}
	}

	private static void CloseReleaseCityHireAndUpgradeSubwindows()
	{
		foreach (var session in EnumerateReleaseCitySessions())
		{
			if (session == null)
				continue;
			TryCloseReleaseHireSubwindow(session, null, null, out _);
		}
		CloseReleaseCityUpgradeSubwindows();
	}

	private static void CloseReleaseCityBuildingAndUpgradeSubwindows()
	{
		foreach (var session in EnumerateReleaseCitySessions())
		{
			if (session == null)
				continue;
			TryCloseReleaseBuildingSubwindow(session, null, null, out _);
		}
		CloseReleaseCityUpgradeSubwindows();
	}

	private static void CloseReleaseCityUpgradeSubwindows()
	{
		foreach (var upgrade in Resources.FindObjectsOfTypeAll<ScUpgradeUnits>())
		{
			if (!IsActiveGameObject(upgrade))
				continue;
			// CityUI panels stay activeInHierarchy while closed via Canvas/CanvasGroup.
			// OnEscapeClick on a visually closed UPGRADE UNIT PANEL still runs native nav
			// OnDeselect → Hide(BuildingsConstruction), which opens-then-closes the hall menu
			// (live-positive: HallCloseTrace + idle Canvas.enabled=false / alpha=0 on that panel).
			if (!IsReleaseTownPanelVisuallyOpen(upgrade))
				continue;
			var path = GetTransformPath(upgrade.transform);
			var escapeClosed = false;
			var hideClosed = false;
			try
			{
				escapeClosed = InvokeReleaseUpgradeUnitsClose(upgrade, GameSymbols.ReleaseTownUi.UpgradeUnitsEscapeClick, "escape", path);
			}
			catch (Exception ex)
			{
				LogReleaseTownUiEvidenceDiagnostic(
					"upgrade-close-escape-failed",
					"path:" + path + "|error:" + ex.GetType().Name + ":" + ex.Message);
			}

			if (IsReleaseTownPanelVisuallyOpen(upgrade))
			{
				try
				{
					hideClosed = InvokeReleaseUpgradeUnitsClose(upgrade, GameSymbols.ReleaseTownUi.UpgradeUnitsHide, "hide", path);
				}
				catch (Exception ex)
				{
					LogReleaseTownUiEvidenceDiagnostic(
						"upgrade-close-hide-failed",
						"path:" + path + "|error:" + ex.GetType().Name + ":" + ex.Message);
				}
			}

			if (IsReleaseTownPanelVisuallyOpen(upgrade))
			{
				LogReleaseTownUiEvidenceDiagnostic(
					"upgrade-close-postcondition-failed",
					"path:" + path
						+ "|escape:" + escapeClosed
						+ "|hide:" + hideClosed);
			}
		}
	}

	// Resolved by symbol, not a compile-time call: OnEscapeClick/OnHide are obfuscated on newer builds and a
	// direct reference fails to JIT there (ValidatePluginLiveInteropRefs against the 25509697 interop).
	private static bool InvokeReleaseUpgradeUnitsClose(ScUpgradeUnits upgrade, GameSymbols.MethodSymbol symbol, string step, string path)
	{
		var method = GameMember.FindFirstMethod(upgrade.GetType(), typeof(void), Type.EmptyTypes, symbol);
		if (method == null)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"upgrade-close-" + step + "-unresolved",
				"path:" + path + "|symbol:" + symbol.Id);
			return false;
		}
		method.Invoke(upgrade, null);
		return true;
	}

	/// <summary>
	/// True when a CityUI primary panel is user-visible. Hierarchy-active alone is not enough:
	/// closed panels keep activeInHierarchy and use Canvas.enabled / CanvasGroup to hide.
	/// </summary>
	private static bool IsReleaseTownPanelVisuallyOpen(Component panel)
	{
		try
		{
			if (panel == null || panel.gameObject == null || !panel.gameObject.activeInHierarchy)
				return false;
			var canvas = panel.GetComponent<Canvas>();
			if (canvas != null && !canvas.enabled)
				return false;
			var group = panel.GetComponent<CanvasGroup>();
			if (group != null && (group.alpha <= 0.01f || !group.interactable || !group.blocksRaycasts))
				return false;
			return canvas != null || group != null || panel.gameObject.activeInHierarchy;
		}
		catch
		{
			return false;
		}
	}

	private static bool IsActiveGameObject(Component component)
	{
		try
		{
			return component != null && component.gameObject != null && component.gameObject.activeInHierarchy;
		}
		catch
		{
			return false;
		}
	}

	private static int TryReadCityNavigationState(BhNavigationView navigation)
	{
		var state = TryReadFirstMember(navigation, typeof(BhNavigationView), GameSymbols.ReleaseTownUi.NavigationStateFields);
		if (state == null)
			return -1;
		try
		{
			return Convert.ToInt32(state);
		}
		catch
		{
			return -1;
		}
	}

	private static int TryReadCityNavigationTabState(BhNavigationTabView tab)
	{
		var state = TryReadFirstMemberFieldOnly(tab, typeof(BhNavigationTabView), GameSymbols.ReleaseTownUi.NavigationTabStateFields);
		if (state == null)
			return -1;
		try
		{
			return Convert.ToInt32(state);
		}
		catch
		{
			return -1;
		}
	}

	private static BhCityUISession FindCitySessionForNavigation(BhNavigationView navigation)
	{
		if (navigation == null)
			return null;
		foreach (var session in EnumerateReleaseCitySessions())
		{
			if (IsSessionForNavigation(session, navigation))
				return session;
		}
		return null;
	}

	private static BhCityUISession FindBestActiveReleaseCitySession()
	{
		BhCityUISession fallback = null;
		foreach (var session in EnumerateReleaseCitySessions())
		{
			if (session == null)
				continue;
			if (fallback == null)
				fallback = session;
			if (IsActiveComponent(session))
				return session;
		}
		return fallback;
	}

	private static BhNavigationView TryGetReleaseCityNavigation(BhCityUISession session, MethodBase originalMethod)
	{
		if (session == null)
			return null;
		return TryReadIl2CppObjectField<BhNavigationView>(
			(Il2CppObjectBase)(object)session,
			typeof(BhCityUISession),
			Il2CppClassPointerStore<BhCityUISession>.NativeClassPtr,
			GameSymbols.ReleaseTownUi.CitySessionNavigation,
			"city-session-navigation-field-missing",
			originalMethod);
	}

	private static BhUIBuildingSession TryGetReleaseCityBuildingSession(BhCityUISession session, MethodBase originalMethod)
	{
		if (session == null)
			return null;
		return TryReadIl2CppObjectField<BhUIBuildingSession>(
			(Il2CppObjectBase)(object)session,
			typeof(BhCityUISession),
			Il2CppClassPointerStore<BhCityUISession>.NativeClassPtr,
			GameSymbols.ReleaseTownUi.CitySessionBuildingSession,
			"city-session-buildingSession-field-missing",
			originalMethod);
	}

	private static BhCityUISession FindCitySessionForDayPanelButton(BhDayPanelButtonManager button)
	{
		if (button == null)
			return null;
		foreach (var session in EnumerateReleaseCitySessions())
		{
			if (IsSessionForDayPanelButton(session, button))
				return session;
		}
		return null;
	}

	private static BhCityUISession FindCitySessionForDayPanel(BhDayPanel panel)
	{
		if (panel == null)
			return null;
		foreach (var session in EnumerateReleaseCitySessions())
		{
			if (IsSessionForDayPanel(session, panel))
				return session;
		}
		return null;
	}

	private static IEnumerable<BhCityUISession> EnumerateReleaseCitySessions()
	{
		var staticSession = TryReadReleaseCityStaticSession();
		if (staticSession != null)
			yield return staticSession;

		BhCityUISession[] sessions = null;
		try
		{
			sessions = Resources.FindObjectsOfTypeAll<BhCityUISession>();
		}
		catch
		{
		}
		if (sessions == null)
			yield break;

		for (var i = 0; i < sessions.Length; i++)
		{
			var session = sessions[i];
			if (session == null || SameIl2CppObject(session, staticSession))
				continue;
			yield return session;
		}
	}

	private static bool IsSessionForNavigation(BhCityUISession session, BhNavigationView navigation)
	{
		if (session == null || navigation == null)
			return false;
		var sessionNavigation = TryReadMember(session, typeof(BhCityUISession), "navigation") as BhNavigationView;
		return SameIl2CppObject(sessionNavigation, navigation);
	}

	private static bool IsSessionForDayPanelButton(BhCityUISession session, BhDayPanelButtonManager button)
	{
		if (session == null || button == null)
			return false;
		var buildingSession = TryReadMember(session, typeof(BhCityUISession), "buildingSession") as BhUIBuildingSession;
		var buildingExitButton = TryReadMember(buildingSession, typeof(BhUIBuildingSession), "exitButton") as BhDayPanel;
		if (IsDayPanelForButton(buildingExitButton, button))
			return true;

		var hireView = TryReadMember(session, typeof(BhCityUISession), "hire") as BhHireCityView;
		var hireDayPanel = TryReadMember(hireView, typeof(BhHireCityView), "dayPanel") as BhDayPanel;
		return IsDayPanelForButton(hireDayPanel, button);
	}

	private static bool IsSessionForDayPanel(BhCityUISession session, BhDayPanel panel)
	{
		if (session == null || panel == null)
			return false;
		var buildingSession = TryReadMember(session, typeof(BhCityUISession), "buildingSession") as BhUIBuildingSession;
		var buildingExitButton = TryReadMember(buildingSession, typeof(BhUIBuildingSession), "exitButton") as BhDayPanel;
		if (SameIl2CppObject(buildingExitButton, panel))
			return true;

		var hireView = TryReadMember(session, typeof(BhCityUISession), "hire") as BhHireCityView;
		var hireDayPanel = TryReadMember(hireView, typeof(BhHireCityView), "dayPanel") as BhDayPanel;
		return SameIl2CppObject(hireDayPanel, panel);
	}

	private static bool IsDayPanelForButton(BhDayPanel panel, BhDayPanelButtonManager button)
	{
		if (panel == null || button == null || !IsActiveComponent(panel))
			return false;
		var panelButton = TryReadMember(panel, typeof(BhDayPanel), "button") as BhDayPanelButtonManager;
		if (SameIl2CppObject(panelButton, button))
			return true;
		try
		{
			return panel.transform != null && button.transform != null && button.transform.IsChildOf(panel.transform);
		}
		catch
		{
			return false;
		}
	}

	private static bool SameIl2CppObject(Il2CppObjectBase left, Il2CppObjectBase right)
	{
		if (left == null || right == null)
			return false;
		return IL2CPP.Il2CppObjectBaseToPtr(left) == IL2CPP.Il2CppObjectBaseToPtr(right);
	}

	private static bool IsActiveComponent(Component component)
	{
		if (component == null || component.gameObject == null || !component.gameObject.activeInHierarchy)
			return false;
		var screen = component as BhScreen;
		if (screen == null)
			return true;
		try
		{
			var group = component.gameObject.GetComponent<CanvasGroup>();
			if (group != null && group.alpha <= 0.01f)
				return false;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"town-screen-active-canvas-group-check-failed",
				component.GetType().FullName + "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
		try
		{
			if (screen.canvas != null && !screen.canvas.enabled)
				return false;
		}
		catch
		{
		}
		return true;
	}

	private static bool IsReleaseCityBackScreenCandidate(BhScreen screen)
	{
		if (screen == null || screen.gameObject == null || !screen.gameObject.activeInHierarchy)
			return false;
		try
		{
			if (screen.canvas != null && !screen.canvas.enabled)
				return false;
		}
		catch
		{
		}
		return true;
	}

	private static string DescribeMethod(MethodBase method)
	{
		return method == null ? "null" : method.DeclaringType?.FullName + "." + method.Name;
	}

	private static string DescribeUnityPath(GameObject gameObject)
	{
		try
		{
			if (gameObject == null)
				return "null";
			var names = new List<string>();
			var current = gameObject.transform;
			var guard = 0;
			while (current != null && guard++ < 24)
			{
				names.Add(current.name);
				current = current.parent;
			}
			names.Reverse();
			return string.Join("/", names);
		}
		catch
		{
			return "unavailable";
		}
	}

	private static string DescribeReleaseCitySubwindowCandidates()
	{
		try
		{
			var sb = new System.Text.StringBuilder();
			var index = 0;
			foreach (var session in EnumerateReleaseCitySessions())
			{
				if (session == null)
					continue;
				if (index++ > 0)
					sb.Append(";");
				sb.Append("session").Append(index).Append("{");
				var buildingSession = TryReadMember(session, typeof(BhCityUISession), "buildingSession") as BhUIBuildingSession;
				AppendBackScreenState(sb, "building", buildingSession);
				sb.Append(",");
				var hireView = TryReadMember(session, typeof(BhCityUISession), "hire") as BhHireCityView;
				AppendBackScreenState(sb, "hire", hireView);
				sb.Append("}");
				if (index >= 4)
					break;
			}
			return sb.Length == 0 ? "none" : sb.ToString();
		}
		catch (Exception ex)
		{
			return "error:" + ex.GetType().Name + ":" + ex.Message;
		}
	}

	private static void AppendBackScreenState(System.Text.StringBuilder sb, string label, BhScreen screen)
	{
		sb.Append(label).Append("=");
		if (screen == null)
		{
			sb.Append("null");
			return;
		}
		sb.Append(screen.GetType().Name);
		try
		{
			sb.Append(":activeSelf=").Append(screen.gameObject != null && screen.gameObject.activeSelf);
			sb.Append(":activeInHierarchy=").Append(screen.gameObject != null && screen.gameObject.activeInHierarchy);
		}
		catch
		{
		}
		try
		{
			sb.Append(":canvas=").Append(screen.canvas == null ? "null" : (screen.canvas.enabled ? "enabled" : "disabled"));
		}
		catch
		{
		}
		try
		{
			var group = screen.gameObject == null ? null : screen.gameObject.GetComponent<CanvasGroup>();
			sb.Append(":alpha=").Append(group == null ? "null" : group.alpha.ToString("0.###"));
		}
		catch (Exception ex)
		{
			sb.Append(":alpha=error:").Append(ex.GetType().Name);
		}
	}

	internal static void AfterReleaseCityTownUiRefreshArg0(MethodBase __originalMethod, object __instance, object __0)
	{
		if (IsTypeNameHintMatch(__0, GameSymbols.ReleaseTownUi.FbiCityWrapperTypeHints))
			CaptureReleaseTownUiTypedCity(__0, __originalMethod);
		CaptureReleaseTownUiCityWrapper(__instance, __0 == null ? null : new[] { __0 }, __originalMethod);
		LogReleaseTownUiDiagnostic(
			"refresh-postfix",
			"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		ApplyCustomCityBackdrop();
		if (__instance is BhBuildingView buildingView && buildingView.gameObject != null && buildingView.gameObject.activeInHierarchy)
		{
			var wrapper = TryReadReleaseBuildingViewCityWrapper(buildingView, __originalMethod);
			if (IsTypeNameHintMatch(wrapper, GameSymbols.ReleaseTownUi.CityWrapperTypeHints))
				CaptureReleaseTownUiTypedCityWrapper(wrapper, __originalMethod);
			else if (IsCityWrapperCandidate(wrapper))
			{
				_releaseTownUiCityWrapper = wrapper;
				CaptureReleaseTownUiCityWrapperPayload(wrapper);
			}
			Homm3StrongholdTownLayers.SyncCurrentCityLayers();
		}
	}

	internal static void AfterReleaseCityTownUiRefreshFbiArg0(MethodBase __originalMethod, object __instance, object __0)
	{
		CaptureReleaseTownUiTypedCity(__0, __originalMethod);
		LogReleaseTownUiDiagnostic(
			"refresh-postfix",
			"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		ApplyCustomCityBackdrop();
	}

	internal static void AfterReleaseCityTownUiRefreshBuildingView(MethodBase __originalMethod, BhBuildingView __instance)
	{
		try
		{
			var wrapper = TryReadReleaseBuildingViewCityWrapper(__instance, __originalMethod);
			if (IsTypeNameHintMatch(wrapper, GameSymbols.ReleaseTownUi.FbiCityWrapperTypeHints))
				CaptureReleaseTownUiTypedCity(wrapper, __originalMethod);
			else if (IsTypeNameHintMatch(wrapper, GameSymbols.ReleaseTownUi.CityWrapperTypeHints))
				CaptureReleaseTownUiTypedCityWrapper(wrapper, __originalMethod);
			else if (IsCityWrapperCandidate(wrapper))
			{
				_releaseTownUiCityWrapper = wrapper;
				CaptureReleaseTownUiCityWrapperPayload(wrapper);
			}
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"building-view-field-failed",
				"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
		LogReleaseTownUiDiagnostic(
			"refresh-postfix",
			"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		ApplyCustomCityBackdrop();
	}

	private static object TryReadReleaseBuildingViewCityWrapper(BhBuildingView view, MethodBase originalMethod)
	{
		if (view == null)
			return null;
		var viewObj = (Il2CppObjectBase)(object)view;
		var direct = TryReadIl2CppObjectField<Il2CppObjectBase>(
			viewObj,
			typeof(BhBuildingView),
			Il2CppClassPointerStore<BhBuildingView>.NativeClassPtr,
			GameSymbols.ReleaseTownUi.BuildingViewCityWrapper,
			"building-view-city-wrapper-field-missing",
			originalMethod);
		if (direct != null)
			return direct;
		foreach (var fieldName in GameSymbols.ReleaseTownUi.BuildingViewCityWrapperFields)
		{
			var fallback = TryReadMemberFieldOnly(view, typeof(BhBuildingView), fieldName);
			if (fallback != null)
				return fallback;
		}
		return null;
	}

	private static object TryReadFirstMember(object instance, Type declaredType, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryReadMember(instance, declaredType, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object TryReadFirstMemberFieldOnly(object instance, Type declaredType, string[] names)
	{
		if (names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = TryReadMemberFieldOnly(instance, declaredType, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static T TryReadFirstExactNoArgMethod<T>(object instance, Type declaredType, string[] names)
		where T : class
	{
		if (instance == null || names == null)
			return null;
		var type = declaredType ?? instance.GetType();
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrEmpty(name))
				continue;
			MethodInfo method;
			try
			{
				method = type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			}
			catch
			{
				method = null;
			}
			if (method == null || method.GetParameters().Length != 0 || !typeof(T).IsAssignableFrom(method.ReturnType))
				continue;
			try
			{
				return method.Invoke(instance, null) as T;
			}
			catch
			{
				return null;
			}
		}
		return null;
	}

	private static T TryReadIl2CppObjectField<T>(Il2CppObjectBase instance, Type managedType, IntPtr classPtr, string fieldInfoName, string fieldName, string diagnosticReason, MethodBase originalMethod)
		where T : Il2CppObjectBase
	{
		var fieldPtr = TryReadIl2CppFieldPointer(instance, managedType, classPtr, fieldInfoName, fieldName, diagnosticReason, originalMethod);
		return fieldPtr == IntPtr.Zero ? null : Il2CppObjectPool.Get<T>(fieldPtr);
	}

	private static T TryReadIl2CppObjectField<T>(Il2CppObjectBase instance, Type managedType, IntPtr classPtr, GameSymbols.FieldSymbol symbol, string diagnosticReason, MethodBase originalMethod)
		where T : Il2CppObjectBase
	{
		return TryReadIl2CppObjectField<T>(
			instance,
			managedType,
			classPtr,
			symbol.NativeFieldInfoName,
			symbol.FieldName,
			diagnosticReason,
			originalMethod);
	}

	private static string TryReadIl2CppStringField(Il2CppObjectBase instance, Type managedType, IntPtr classPtr, string fieldInfoName, string fieldName, string diagnosticReason, MethodBase originalMethod)
	{
		var fieldPtr = TryReadIl2CppFieldPointer(instance, managedType, classPtr, fieldInfoName, fieldName, diagnosticReason, originalMethod);
		return fieldPtr == IntPtr.Zero ? null : IL2CPP.Il2CppStringToManaged(fieldPtr);
	}

	private static string TryReadIl2CppStringField(Il2CppObjectBase instance, Type managedType, IntPtr classPtr, GameSymbols.FieldSymbol symbol, string diagnosticReason, MethodBase originalMethod)
	{
		return TryReadIl2CppStringField(
			instance,
			managedType,
			classPtr,
			symbol.NativeFieldInfoName,
			symbol.FieldName,
			diagnosticReason,
			originalMethod);
	}

	private static string ReadObjCityConfigFractionProfiled(object config, string source, MethodBase originalMethod)
	{
		var startTicks = Stopwatch.GetTimestamp();
		string fraction = null;
		var usedFallback = false;
		try
		{
			if (config is Il2CppObjectBase configObject)
			{
				fraction = TryReadIl2CppStringField(
					configObject,
					typeof(ObjCityConfig),
					Il2CppClassPointerStore<ObjCityConfig>.NativeClassPtr,
					GameSymbols.ReleaseTownUi.ObjCityConfigFraction,
					"city-config-fraction-field-missing",
					originalMethod);
			}

			if (string.IsNullOrWhiteSpace(fraction))
			{
				usedFallback = true;
				fraction = DeobfInteropCompat.GetObjCityConfigFraction(config);
			}

			return fraction;
		}
		finally
		{
			var elapsedTicks = Stopwatch.GetTimestamp() - startTicks;
			RecordObjCityConfigFractionRead(source, fraction, usedFallback, elapsedTicks);
		}
	}

	private static void RecordObjCityConfigFractionRead(string source, string fraction, bool usedFallback, long elapsedTicks)
	{
		try
		{
			_objCityConfigFractionReads++;
			_objCityConfigFractionReadTicks += elapsedTicks;
			if (usedFallback)
				_objCityConfigFractionFallbackReads++;
			if (string.IsNullOrWhiteSpace(fraction))
				_objCityConfigFractionNullReads++;

			var elapsedMs = elapsedTicks * 1000.0 / Stopwatch.Frequency;
			var shouldLog =
				_objCityConfigFractionReads == 1
				|| _objCityConfigFractionReads == 10
				|| _objCityConfigFractionReads == 50
				|| _objCityConfigFractionReads % 100 == 0
				|| (elapsedMs >= 2.0 && _objCityConfigFractionSlowLogs++ < 20);
			if (!shouldLog)
				return;

			var totalMs = _objCityConfigFractionReadTicks * 1000.0 / Stopwatch.Frequency;
			Plugin.LogSource?.LogInfo(
				"ObjCityConfig fraction read profile:"
				+ " count="
				+ _objCityConfigFractionReads
				+ ", fallback="
				+ _objCityConfigFractionFallbackReads
				+ ", null="
				+ _objCityConfigFractionNullReads
				+ ", lastMs="
				+ elapsedMs.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
				+ ", totalMs="
				+ totalMs.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
				+ ", source="
				+ (source ?? "unknown")
				+ ", fraction="
				+ (fraction ?? "null")
				+ ".");
		}
		catch
		{
			// Profiling must never affect town identity resolution.
		}
	}

	private static IntPtr TryReadIl2CppFieldPointer(Il2CppObjectBase instance, Type managedType, IntPtr classPtr, string fieldInfoName, string fieldName, string diagnosticReason, MethodBase originalMethod)
	{
		if (instance == null || classPtr == IntPtr.Zero || string.IsNullOrEmpty(fieldName))
			return IntPtr.Zero;
		var field = TryGetGeneratedNativeFieldInfoPtr(managedType, fieldInfoName) ?? TryGetIl2CppField(classPtr, fieldName);
		if (field == IntPtr.Zero)
		{
			if (!string.IsNullOrEmpty(diagnosticReason))
			{
				LogReleaseTownUiEvidenceDiagnostic(
					diagnosticReason,
					"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name) + "|field:" + fieldName);
			}
			return IntPtr.Zero;
		}
		var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(instance);
		return Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(field)));
	}

	private static IntPtr? TryGetGeneratedNativeFieldInfoPtr(Type managedType, string fieldInfoName)
	{
		if (managedType == null || string.IsNullOrEmpty(fieldInfoName))
			return null;
		try
		{
			var field = managedType.GetField(fieldInfoName, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (field == null || field.FieldType != typeof(IntPtr))
				return null;
			var value = (IntPtr)field.GetValue(null);
			return value == IntPtr.Zero ? null : value;
		}
		catch
		{
			return null;
		}
	}

	private static IntPtr TryGetNativeClassPtr(Type managedType)
	{
		if (managedType == null)
			return IntPtr.Zero;
		try
		{
			var field = managedType.GetField("NativeClassPtr", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (field == null || field.FieldType != typeof(IntPtr))
				return IntPtr.Zero;
			return (IntPtr)field.GetValue(null);
		}
		catch
		{
			return IntPtr.Zero;
		}
	}

	internal static void AfterReleaseCityTownUiRefreshBuildingSessionFbiArg0(MethodBase __originalMethod, BhUIBuildingSession __instance, object __0)
	{
		CaptureReleaseTownUiCityWrapper(__instance, __0 == null ? null : new[] { __0 }, __originalMethod);
		if (IsTypeNameHintMatch(__0, GameSymbols.ReleaseTownUi.FbiCityWrapperTypeHints))
			CaptureReleaseTownUiTypedCity(__0, __originalMethod);
		LogReleaseTownUiDiagnostic(
			"refresh-postfix",
			"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		ApplyCustomCityBackdrop();
		ShowReleaseBuildTreePanelOnlyIfPopulated(__instance, __originalMethod, "building-session-refresh-fbi", allowOpenHiddenPanel: false);
		LogReleaseBuildSessionSnapshot(__instance, __originalMethod);
	}

	internal static void AfterReleaseCityTownUiRefreshBuildingSession(MethodBase __originalMethod, BhUIBuildingSession __instance, object[] __args)
	{
		CaptureReleaseTownUiFbi(__instance, __args, __originalMethod);
		CaptureReleaseTownUiCityWrapper(__instance, __args, __originalMethod);
		LogReleaseTownUiDiagnostic(
			"refresh-postfix",
			"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		ApplyCustomCityBackdrop();
		ShowReleaseBuildTreePanelOnlyIfPopulated(__instance, __originalMethod, "building-session-refresh", allowOpenHiddenPanel: false);
		LogReleaseBuildSessionSnapshot(__instance, __originalMethod);
	}

	private static void LogReleaseBuildSessionSnapshot(BhUIBuildingSession session, MethodBase originalMethod)
	{
		try
		{
			if (!Homm3DiagnosticFlags.IsEnabled("releaseTownUiDiagnostics.flag"))
				return;

			var fraction = GetCurrentCityFraction();
			if (!Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction))
				return;
			if (_releaseBuildSessionSnapshotCount++ >= 12)
				return;

			var sb = new System.Text.StringBuilder();
			sb.Append("method:").Append(originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name);
			sb.Append("|fraction:").Append(fraction ?? "null");

			var panelCanvas = FindCanvasByName("BUILDING VIEW PANEL", "build-session-snapshot");
			if (panelCanvas == null)
			{
				sb.Append("|panelCanvas:null");
			}
			else
			{
				sb.Append("|panelCanvas:sort=").Append(panelCanvas.sortingOrder)
					.Append(",override=").Append(panelCanvas.overrideSorting)
					.Append(",enabled=").Append(panelCanvas.isActiveAndEnabled);
				AppendGameObjectSnapshot(sb, "panelGo", panelCanvas.gameObject);
			}

			if (session == null)
			{
				sb.Append("|session:null");
				LogReleaseTownUiEvidenceDiagnostic("build-session-snapshot", sb.ToString());
				return;
			}

			var sessionObj = (Il2CppObjectBase)(object)session;
			var sessionType = typeof(BhUIBuildingSession);
			var sessionClass = Il2CppClassPointerStore<BhUIBuildingSession>.NativeClassPtr;

			var root = TryReadIl2CppObjectField<GameObject>(
				sessionObj,
				sessionType,
				sessionClass,
				GameSymbols.ReleaseTownUi.BuildingSessionRoot,
				"build-session-root-field-missing",
				originalMethod);
			AppendGameObjectSnapshot(sb, "root", root);

			var arrowsCg = TryReadIl2CppObjectField<CanvasGroup>(
				sessionObj,
				sessionType,
				sessionClass,
				GameSymbols.ReleaseTownUi.BuildingSessionArrowsCg,
				"build-session-arrowsCg-field-missing",
				originalMethod);
			AppendCanvasGroupSnapshot(sb, "arrowsCg", arrowsCg);

			var allViews = TryReadIl2CppObjectField<Il2CppSystem.Collections.Generic.List<BhBuildingView>>(
				sessionObj,
				sessionType,
				sessionClass,
				GameSymbols.ReleaseTownUi.BuildingSessionAllViews,
				"build-session-buildingsUIs-field-missing",
				originalMethod);
			AppendBuildingViewListSnapshot(sb, "allViews", allViews);

			var currentViews = TryReadIl2CppObjectField<Il2CppSystem.Collections.Generic.List<BhBuildingView>>(
				sessionObj,
				sessionType,
				sessionClass,
				GameSymbols.ReleaseTownUi.BuildingSessionCurrentViews,
				"build-session-currentViews-field-missing",
				originalMethod)
				?? TryReadIl2CppObjectField<Il2CppSystem.Collections.Generic.List<BhBuildingView>>(
					sessionObj,
					sessionType,
					sessionClass,
					GameSymbols.ReleaseTownUi.BuildingSessionCurrentViewsOld,
					"build-session-currentViews-field-missing",
					originalMethod);
			AppendBuildingViewListSnapshot(sb, "currentViews", currentViews);
			AppendBuildingViewUiSnapshot(sb, "currentViewsUi", currentViews);

			var viewLookup = TryReadIl2CppObjectField<Il2CppSystem.Collections.Generic.Dictionary<string, BhBuildingView>>(
				sessionObj,
				sessionType,
				sessionClass,
				GameSymbols.ReleaseTownUi.BuildingSessionViewLookup,
				"build-session-viewLookup-field-missing",
				originalMethod)
				?? TryReadIl2CppObjectField<Il2CppSystem.Collections.Generic.Dictionary<string, BhBuildingView>>(
					sessionObj,
					sessionType,
					sessionClass,
					GameSymbols.ReleaseTownUi.BuildingSessionViewLookupOld,
					"build-session-viewLookup-field-missing",
					originalMethod);
			sb.Append("|viewLookupCount:").Append(viewLookup == null ? "null" : viewLookup.Count.ToString());

			LogReleaseTownUiEvidenceDiagnostic("build-session-snapshot", sb.ToString());
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"build-session-snapshot-failed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static void LogReleaseCitySessionBuildSnapshot(BhCityUISession citySession, MethodBase originalMethod)
	{
		try
		{
			if (!Homm3DiagnosticFlags.IsEnabled("releaseTownUiDiagnostics.flag"))
				return;
			var fraction = GetCurrentCityFraction();
			if (!Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction))
				return;
			if (citySession == null)
			{
				LogReleaseTownUiEvidenceDiagnostic(
					"city-session-build-snapshot",
					"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
						+ "|fraction:" + (fraction ?? "null")
						+ "|citySession:null");
				LogReleaseBuildSessionSnapshot(null, originalMethod);
				return;
			}

			var buildingSession = TryGetReleaseCityBuildingSession(citySession, originalMethod);
			LogReleaseTownUiEvidenceDiagnostic(
				"city-session-build-snapshot",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|fraction:" + (fraction ?? "null")
					+ "|buildingSession:" + (buildingSession == null ? "null" : buildingSession.GetInstanceID().ToString()));
			LogReleaseBuildSessionSnapshot(buildingSession, originalMethod);
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"city-session-build-snapshot-failed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static Canvas FindCanvasByName(string name, string source = null)
	{
		try
		{
			var activeScene = SceneManager.GetActiveScene();
			var cityRoot = FindCityPanelRectTransform();
			Canvas best = null;
			var foundPreferred = false;
			ForEachLoadedSceneCanvas(canvas =>
			{
				if (foundPreferred || canvas == null || !string.Equals(canvas.gameObject?.name, name, StringComparison.Ordinal))
					return;
				var go = canvas.gameObject;
				if (go == null)
					return;
				var inActiveScene = activeScene.IsValid() && go.scene.IsValid() && go.scene.handle == activeScene.handle;
				var underCityRoot = cityRoot != null && IsTransformDescendantOf(canvas.transform, cityRoot);
				if (underCityRoot && go.activeInHierarchy)
				{
					best = canvas;
					foundPreferred = true;
					return;
				}
				if (best == null
					|| (underCityRoot && !IsTransformDescendantOf(best.transform, cityRoot))
					|| (inActiveScene && (!best.gameObject.scene.IsValid() || best.gameObject.scene.handle != activeScene.handle))
					|| (go.activeInHierarchy && !best.gameObject.activeInHierarchy))
				{
					best = canvas;
				}
			});
			return best;
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"town-find-canvas-by-name-failed",
				"source:" + (source ?? "null")
					+ "|canvas:" + (name ?? "null")
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
		return null;
	}

	private static List<Canvas> _frameCanvasSnapshot;
	private static int _frameCanvasSnapshotFrame = -1;
	private static string _frameCanvasSnapshotFilter;
	private static int _frameCanvasSnapshotSceneCount = -1;

	private static void ForEachCityUiCanvas(Action<Canvas> action)
	{
		ForEachLoadedSceneCanvas(action, sceneNameFilter: "CityUI");
	}

	private static void ForEachLoadedSceneCanvas(Action<Canvas> action, string sceneNameFilter = null)
	{
		if (action == null)
			return;
		var snapshot = GetFrameCanvasSnapshot(sceneNameFilter);
		for (var i = 0; i < snapshot.Count; i++)
		{
			var canvas = snapshot[i];
			if (canvas != null)
				action(canvas);
		}
	}

	/// <summary>
	/// One GetComponentsInChildren pass per frame/filter. FindCanvasByName + panel lift used to
	/// re-walk every loaded scene root for each of ~7 primary panels (~200ms/sync live).
	/// </summary>
	private static List<Canvas> GetFrameCanvasSnapshot(string sceneNameFilter)
	{
		var frame = Time.frameCount;
		var sceneCount = SceneManager.sceneCount;
		var filterKey = sceneNameFilter ?? string.Empty;
		if (_frameCanvasSnapshot != null
		    && _frameCanvasSnapshotFrame == frame
		    && _frameCanvasSnapshotSceneCount == sceneCount
		    && string.Equals(_frameCanvasSnapshotFilter, filterKey, StringComparison.Ordinal))
		{
			return _frameCanvasSnapshot;
		}

		var list = new List<Canvas>(64);
		for (var sceneIndex = 0; sceneIndex < sceneCount; sceneIndex++)
		{
			var scene = SceneManager.GetSceneAt(sceneIndex);
			if (!scene.IsValid() || !scene.isLoaded)
				continue;
			if (!string.IsNullOrEmpty(sceneNameFilter)
			    && !string.Equals(scene.name, sceneNameFilter, StringComparison.Ordinal))
			{
				continue;
			}

			var roots = scene.GetRootGameObjects();
			for (var i = 0; i < roots.Length; i++)
			{
				var root = roots[i];
				if (root == null)
					continue;
				var canvases = root.GetComponentsInChildren<Canvas>(true);
				for (var j = 0; j < canvases.Length; j++)
				{
					var canvas = canvases[j];
					if (canvas != null)
						list.Add(canvas);
				}
			}
		}

		_frameCanvasSnapshot = list;
		_frameCanvasSnapshotFrame = frame;
		_frameCanvasSnapshotFilter = filterKey;
		_frameCanvasSnapshotSceneCount = sceneCount;
		return list;
	}

	private static bool IsTransformDescendantOf(Transform child, Transform root)
	{
		if (child == null || root == null)
			return false;
		for (var current = child; current != null; current = current.parent)
		{
			if (current == root)
				return true;
		}
		return false;
	}

	private static void AppendGameObjectSnapshot(System.Text.StringBuilder sb, string label, GameObject go)
	{
		if (sb == null)
			return;
		if (go == null)
		{
			sb.Append("|").Append(label).Append(":null");
			return;
		}

		sb.Append("|").Append(label)
			.Append(":name=").Append(go.name)
			.Append(",activeSelf=").Append(go.activeSelf)
			.Append(",activeInHierarchy=").Append(go.activeInHierarchy)
			.Append(",children=").Append(go.transform == null ? -1 : go.transform.childCount)
			.Append(",scene=").Append(go.scene.IsValid() ? go.scene.name : "invalid");

		try
		{
			var rect = go.GetComponent<RectTransform>();
			if (rect != null)
			{
				sb.Append(",rect=(")
					.Append(rect.rect.width.ToString("0.#")).Append("x")
					.Append(rect.rect.height.ToString("0.#")).Append(")")
					.Append(",anchored=(")
					.Append(rect.anchoredPosition.x.ToString("0.#")).Append(",")
					.Append(rect.anchoredPosition.y.ToString("0.#")).Append(")")
					.Append(",scale=(")
					.Append(rect.localScale.x.ToString("0.###")).Append(",")
					.Append(rect.localScale.y.ToString("0.###")).Append(",")
					.Append(rect.localScale.z.ToString("0.###")).Append(")");
			}
		}
		catch
		{
		}

		try
		{
			var group = go.GetComponent<CanvasGroup>();
			AppendCanvasGroupSnapshot(sb, label + ".cg", group);
		}
		catch
		{
		}
	}

	private static void AppendCanvasGroupSnapshot(System.Text.StringBuilder sb, string label, CanvasGroup group)
	{
		if (sb == null)
			return;
		if (group == null)
		{
			sb.Append("|").Append(label).Append(":null");
			return;
		}

		sb.Append("|").Append(label)
			.Append(":alpha=").Append(group.alpha.ToString("0.###"))
			.Append(",interactable=").Append(group.interactable)
			.Append(",blocks=").Append(group.blocksRaycasts)
			.Append(",enabled=").Append(group.isActiveAndEnabled);
	}

	private static void AppendBuildingViewListSnapshot(
		System.Text.StringBuilder sb,
		string label,
		Il2CppSystem.Collections.Generic.List<BhBuildingView> views)
	{
		if (sb == null)
			return;
		if (views == null)
		{
			sb.Append("|").Append(label).Append(":null");
			return;
		}

		sb.Append("|").Append(label)
			.Append(":count=").Append(views.Count)
			.Append(",sample=skipped-il2cpp-list-items");
	}

	private static void AppendBuildingViewUiSnapshot(
		System.Text.StringBuilder sb,
		string label,
		Il2CppSystem.Collections.Generic.List<BhBuildingView> views)
	{
		if (sb == null)
			return;
		if (views == null)
		{
			sb.Append("|").Append(label).Append(":null");
			return;
		}

		var sampled = 0;
		for (var i = 0; i < views.Count && sampled < 3; i++)
		{
			BhBuildingView view = null;
			try
			{
				view = views[i];
			}
			catch
			{
			}
			if (view == null || view.gameObject == null)
				continue;

			sb.Append("|").Append(label).Append("[").Append(i).Append("]");
			AppendGameObjectSnapshot(sb, "viewGo", view.gameObject);
			try
			{
				var images = view.GetComponentsInChildren<Image>(true);
				var enabled = 0;
				var active = 0;
				var visibleAlpha = 0;
				var sampleText = new System.Text.StringBuilder();
				for (var imageIndex = 0; imageIndex < images.Length; imageIndex++)
				{
					var image = images[imageIndex];
					if (image == null)
						continue;
					if (image.enabled)
						enabled++;
					if (image.gameObject != null && image.gameObject.activeInHierarchy)
						active++;
					if (image.enabled && image.color.a > 0.01f && image.gameObject != null && image.gameObject.activeInHierarchy)
						visibleAlpha++;
					if (sampleText.Length < 220)
					{
						if (sampleText.Length > 0)
							sampleText.Append(';');
						sampleText.Append(image.gameObject == null ? "null" : image.gameObject.name)
							.Append(":en=").Append(image.enabled)
							.Append(",a=").Append(image.color.a.ToString("0.##"))
							.Append(",active=").Append(image.gameObject != null && image.gameObject.activeInHierarchy)
							.Append(",sprite=").Append(image.sprite == null ? "null" : image.sprite.name);
					}
				}
				sb.Append(",images=").Append(images.Length)
					.Append(",enabled=").Append(enabled)
					.Append(",active=").Append(active)
					.Append(",visibleAlpha=").Append(visibleAlpha)
					.Append(",imageSample=").Append(sampleText);
			}
			catch (Exception ex)
			{
				sb.Append(",imageProbeError=").Append(ex.GetType().Name).Append(':').Append(ex.Message);
			}
			sampled++;
		}
		if (sampled == 0)
			sb.Append("|").Append(label).Append(":sampled=0");
	}

	internal static void ClearReleaseCityTownUi(MethodBase __originalMethod)
	{
		LogReleaseTownUiDiagnostic(
			"clear-postfix",
			"method:" + (__originalMethod == null ? "null" : __originalMethod.DeclaringType?.FullName + "." + __originalMethod.Name));
		_releaseTownUiCityWrapper = null;
		_releaseTownUiFraction = null;
		_releaseTownUiCityData = null;
		ClearCustomCityBackdrop();
		Homm3StrongholdTownLayers.ClearObservedBuildingData();
		Homm3StrongholdTownLayers.ClearTownLayers();
	}

	internal static void RememberReleaseTownUiCityIconKey(string cityIconKey, string source)
	{
		try
		{
			if (string.IsNullOrWhiteSpace(cityIconKey))
				return;
			if (!Homm3CustomFactionRegistry.TryGetFactionSidForCityIconKey(cityIconKey, out var factionSid)
				|| !Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(factionSid))
				return;
			var changed = !string.Equals(_releaseTownUiFraction, factionSid, StringComparison.Ordinal);

			_releaseTownUiFraction = factionSid;
			if (changed)
			{
				LogReleaseTownUiEvidenceDiagnostic(
					"captured-city-hud-key",
					"source:" + (source ?? "null")
						+ "|key:" + cityIconKey
						+ "|fraction:" + factionSid);
			}

			if (IsCityInteriorSceneName(SafeActiveSceneName()))
			{
				ApplyCustomCityBackdrop();
				Homm3StrongholdTownLayers.SyncCurrentCityLayers();
			}
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"captured-city-hud-key-failed",
				"source:" + (source ?? "null")
					+ "|key:" + (cityIconKey ?? "null")
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static void ShowReleaseBuildTreePanelOnlyIfPopulated(BhUIBuildingSession buildingSession, MethodBase originalMethod, string source, bool allowOpenHiddenPanel)
	{
		if (buildingSession == null)
			return;
		var currentViews = TryReadReleaseBuildingCurrentViewCount(buildingSession, originalMethod);
		var allViews = TryReadReleaseBuildingAllViewCount(buildingSession, originalMethod);
		if (currentViews > 0)
		{
			if (!allowOpenHiddenPanel && !IsReleaseBuildTreePanelAlreadyOpen(buildingSession))
			{
				LogReleaseTownUiEvidenceDiagnostic(
					"build-tree-panel-open-suppressed-closed-refresh",
					"source:" + (source ?? "null")
						+ "|currentViews:" + currentViews
						+ "|allViews:" + allViews
						+ "|frame:" + Time.frameCount);
				return;
			}
			RestoreReleaseBuildTreePanelCanvasGroup(buildingSession, source);
			EnsureReleaseTownScreenVisible(
				buildingSession,
				"BUILDING VIEW PANEL",
				source,
				requireAlreadyOpenForBuildTree: false);
			return;
		}
		if (currentViews < 0)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"build-tree-panel-native-state-unknown",
				"source:" + (source ?? "null")
					+ "|currentViews:" + currentViews
					+ "|allViews:" + allViews);
			return;
		}

		LogReleaseTownUiEvidenceDiagnostic(
			"build-tree-panel-empty-native-state-no-mutation",
			"source:" + (source ?? "null")
				+ "|currentViews:" + currentViews
				+ "|allViews:" + allViews);
	}

	private static bool IsReleaseBuildTreePanelAlreadyOpen(BhUIBuildingSession buildingSession)
	{
		var go = buildingSession == null ? null : buildingSession.gameObject;
		var panelCanvas = go == null ? null : go.GetComponent<Canvas>();
		if (go == null || panelCanvas == null || !go.activeInHierarchy || !panelCanvas.enabled)
			return false;
		var group = go.GetComponent<CanvasGroup>();
		return group == null || (group.alpha > 0.01f && group.interactable && group.blocksRaycasts);
	}

	private static void RestoreReleaseBuildTreePanelCanvasGroup(BhUIBuildingSession buildingSession, string source)
	{
		var go = buildingSession == null ? null : buildingSession.gameObject;
		var panelCanvas = go == null ? null : go.GetComponent<Canvas>();
		if (go == null || panelCanvas == null)
			return;

		panelCanvas.enabled = true;
		var group = go.GetComponent<CanvasGroup>();
		if (group != null)
			HideCanvasGroup(group, hide: false);
	}

	private static int TryReadReleaseBuildingCurrentViewCount(BhUIBuildingSession session, MethodBase originalMethod)
	{
		var list = TryReadReleaseBuildingViewList(
			session,
			GameSymbols.ReleaseTownUi.BuildingSessionCurrentViews,
			GameSymbols.ReleaseTownUi.BuildingSessionCurrentViewsOld,
			originalMethod);
		return list == null ? -1 : list.Count;
	}

	private static int TryReadReleaseBuildingAllViewCount(BhUIBuildingSession session, MethodBase originalMethod)
	{
		var list = TryReadReleaseBuildingViewList(
			session,
			GameSymbols.ReleaseTownUi.BuildingSessionAllViews,
			null,
			originalMethod);
		return list == null ? -1 : list.Count;
	}

	private static Il2CppSystem.Collections.Generic.List<BhBuildingView> TryReadReleaseBuildingViewList(
		BhUIBuildingSession session,
		GameSymbols.FieldSymbol primary,
		GameSymbols.FieldSymbol? fallback,
		MethodBase originalMethod)
	{
		if (session == null)
			return null;
		var sessionObj = (Il2CppObjectBase)(object)session;
		var sessionType = typeof(BhUIBuildingSession);
		var sessionClass = Il2CppClassPointerStore<BhUIBuildingSession>.NativeClassPtr;
		return TryReadIl2CppObjectField<Il2CppSystem.Collections.Generic.List<BhBuildingView>>(
			sessionObj,
			sessionType,
			sessionClass,
			primary,
			null,
			originalMethod)
			?? (!fallback.HasValue ? null : TryReadIl2CppObjectField<Il2CppSystem.Collections.Generic.List<BhBuildingView>>(
				sessionObj,
				sessionType,
				sessionClass,
				fallback.Value,
				null,
				originalMethod));
	}


	internal static void RememberReleaseTownUiCityWrapperFromBuildingViewBind(object wrapper, MethodBase originalMethod)
	{
		try
		{
			if (wrapper == null)
				return;
			if (IsTypeNameHintMatch(wrapper, GameSymbols.ReleaseTownUi.FbiCityWrapperTypeHints))
				CaptureReleaseTownUiTypedCity(wrapper, originalMethod);
			else if (IsTypeNameHintMatch(wrapper, GameSymbols.ReleaseTownUi.CityWrapperTypeHints))
				CaptureReleaseTownUiTypedCityWrapper(wrapper, originalMethod);
			else if (IsCityWrapperCandidate(wrapper))
			{
				_releaseTownUiCityWrapper = wrapper;
				CaptureReleaseTownUiCityWrapperPayload(wrapper);
			}
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"building-view-bind-wrapper-failed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|type:" + (wrapper == null ? "null" : wrapper.GetType().FullName)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static void CaptureReleaseTownUiTypedCityWrapper(object wrapper, MethodBase originalMethod)
	{
		try
		{
			if (wrapper is not Il2CppObjectBase)
				return;
			var wrapperType = wrapper.GetType();
			_releaseTownUiCityWrapper = wrapper;
			var config = TryReadReleaseCityWrapperConfig(wrapper, originalMethod);
			config ??= TryReadFirstMemberFieldOnly(wrapper, wrapperType, GameSymbols.ReleaseTownUi.SessionCityConfigFields) as ObjCityConfig;
			config ??= TryReadFirstExactNoArgMethod<ObjCityConfig>(wrapper, wrapperType, GameSymbols.ReleaseTownUi.SessionCityConfigMethods);
			var city = TryReadReleaseCityWrapperCity(wrapper, originalMethod);
			city ??= TryReadFirstMemberFieldOnly(wrapper, wrapperType, GameSymbols.ReleaseTownUi.SessionCityDataFields) as Hex.Session.Data.ObjCity;
			city ??= TryReadFirstExactNoArgMethod<Hex.Session.Data.ObjCity>(wrapper, wrapperType, GameSymbols.ReleaseTownUi.SessionCityDataMethods);
			var fraction = ReadObjCityConfigFractionProfiled(config, "captured-city-wrapper-typed", originalMethod);
			var cityConfigSid = DeobfInteropCompat.GetConfigElementId(config);
			if (Homm3CustomFactionRegistry.TryResolveTownPresentationFactionSid(fraction, cityConfigSid, out var presentationFaction))
				fraction = presentationFaction;
			if (!string.IsNullOrWhiteSpace(fraction))
				_releaseTownUiFraction = fraction;
			if (city != null)
				_releaseTownUiCityData = city;
			LogReleaseTownUiEvidenceDiagnostic(
				"captured-city-wrapper-typed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|fraction:" + (fraction ?? "null")
					+ "|cachedFraction:" + (_releaseTownUiFraction ?? "null")
					+ "|city:" + (city == null ? "null" : city.GetType().FullName));
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"typed-city-wrapper-failed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static void CaptureReleaseTownUiTypedCity(object cityWrapper, MethodBase originalMethod)
	{
		try
		{
			if (cityWrapper is not Il2CppObjectBase)
				return;
			var cityWrapperType = cityWrapper.GetType();
			_releaseTownUiCityWrapper = cityWrapper;
			var config = TryReadReleaseCityWrapperConfig(cityWrapper, originalMethod);
			config ??= TryReadFirstMemberFieldOnly(cityWrapper, cityWrapperType, GameSymbols.ReleaseTownUi.SessionCityConfigFields) as ObjCityConfig;
			config ??= TryReadFirstExactNoArgMethod<ObjCityConfig>(cityWrapper, cityWrapperType, GameSymbols.ReleaseTownUi.SessionCityConfigMethods);
			var city = TryReadReleaseCityWrapperCity(cityWrapper, originalMethod);
			city ??= TryReadFirstMemberFieldOnly(cityWrapper, cityWrapperType, GameSymbols.ReleaseTownUi.SessionCityDataFields) as Hex.Session.Data.ObjCity;
			city ??= TryReadFirstExactNoArgMethod<Hex.Session.Data.ObjCity>(cityWrapper, cityWrapperType, GameSymbols.ReleaseTownUi.SessionCityDataMethods);
			var fraction = ReadObjCityConfigFractionProfiled(config, "captured-city-fbi", originalMethod);
			var cityConfigSid = DeobfInteropCompat.GetConfigElementId(config);
			if (Homm3CustomFactionRegistry.TryResolveTownPresentationFactionSid(fraction, cityConfigSid, out var presentationFaction))
				fraction = presentationFaction;
			if (!string.IsNullOrWhiteSpace(fraction))
				_releaseTownUiFraction = fraction;
			if (city != null)
				_releaseTownUiCityData = city;
			LogReleaseTownUiEvidenceDiagnostic(
				"captured-city-fbi",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|fraction:" + (fraction ?? "null")
					+ "|cachedFraction:" + (_releaseTownUiFraction ?? "null")
					+ "|city:" + (city == null ? "null" : city.GetType().FullName));
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"typed-city-fbi-failed",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|error:" + ex.GetType().Name + ":" + ex.Message);
		}
	}

	private static ObjCityConfig TryReadReleaseCityWrapperConfig(object wrapper, MethodBase originalMethod)
	{
		if (wrapper is not Il2CppObjectBase wrapperObj)
			return null;
		var wrapperType = wrapper.GetType();
		var wrapperClassPtr = TryGetNativeClassPtr(wrapperType);
		if (wrapperClassPtr == IntPtr.Zero)
			return null;
		if (IsTypeNameHintMatch(wrapper, GameSymbols.ReleaseTownUi.FbiCityWrapperTypeHints))
		{
			var fbiConfig = TryReadIl2CppObjectField<ObjCityConfig>(
				wrapperObj,
				wrapperType,
				wrapperClassPtr,
				GameSymbols.ReleaseTownUi.FbiConfig,
				"city-fbi-config-field-missing",
				originalMethod);
			if (fbiConfig != null)
				return fbiConfig;
		}
		return TryReadIl2CppObjectField<ObjCityConfig>(
			wrapperObj,
			wrapperType,
			wrapperClassPtr,
			GameSymbols.ReleaseTownUi.CityWrapperConfig,
			"city-wrapper-config-field-missing",
			originalMethod)
		       ?? TryReadFirstExactNoArgMethod<ObjCityConfig>(
			       wrapper,
			       wrapperType,
			       GameSymbols.ReleaseTownUi.SessionCityConfigMethods);
	}

	private static Hex.Session.Data.ObjCity TryReadReleaseCityWrapperCity(object wrapper, MethodBase originalMethod)
	{
		if (wrapper is not Il2CppObjectBase wrapperObj)
			return null;
		var wrapperType = wrapper.GetType();
		var wrapperClassPtr = TryGetNativeClassPtr(wrapperType);
		if (wrapperClassPtr == IntPtr.Zero)
			return null;
		if (IsTypeNameHintMatch(wrapper, GameSymbols.ReleaseTownUi.FbiCityWrapperTypeHints))
		{
			var fbiCity = TryReadIl2CppObjectField<Hex.Session.Data.ObjCity>(
				wrapperObj,
				wrapperType,
				wrapperClassPtr,
				GameSymbols.ReleaseTownUi.FbiCity,
				"city-fbi-city-field-missing",
				originalMethod);
			if (fbiCity != null)
				return fbiCity;
		}
		return TryReadIl2CppObjectField<Hex.Session.Data.ObjCity>(
			wrapperObj,
			wrapperType,
			wrapperClassPtr,
			GameSymbols.ReleaseTownUi.CityWrapperCity,
			"city-wrapper-city-field-missing",
			originalMethod)
		       ?? TryReadFirstExactNoArgMethod<Hex.Session.Data.ObjCity>(
			       wrapper,
			       wrapperType,
			       GameSymbols.ReleaseTownUi.SessionCityDataMethods);
	}

	private static void CaptureReleaseTownUiFbi(object instance, object[] args, MethodBase originalMethod)
	{
		try
		{
			var cityWrapper = TryExtractReleaseTownUiFbi(instance, args, originalMethod?.DeclaringType);
			if (cityWrapper != null)
				CaptureReleaseTownUiTypedCity(cityWrapper, originalMethod);
		}
		catch
		{
		}
	}

	private static void CaptureReleaseTownUiCityWrapper(object instance, object[] args, MethodBase originalMethod)
	{
		try
		{
			var wrapper = TryExtractReleaseTownUiCityWrapper(instance, args, originalMethod?.DeclaringType);
			if (wrapper == null)
				return;
			_releaseTownUiCityWrapper = wrapper;
			if (wrapper is Il2CppObjectBase && IsTypeNameHintMatch(wrapper, GameSymbols.ReleaseTownUi.CityWrapperTypeHints))
				CaptureReleaseTownUiTypedCityWrapper(wrapper, originalMethod);
			else
				CaptureReleaseTownUiCityWrapperPayload(wrapper);
			LogReleaseTownUiEvidenceDiagnostic(
				"captured-city-wrapper",
				"method:" + (originalMethod == null ? "null" : originalMethod.DeclaringType?.FullName + "." + originalMethod.Name)
					+ "|type:" + wrapper.GetType().FullName
					+ "|fraction:" + (_releaseTownUiFraction ?? "null")
					+ "|city:" + (_releaseTownUiCityData == null ? "null" : _releaseTownUiCityData.GetType().FullName));
		}
		catch
		{
		}
	}

	private static object TryExtractReleaseTownUiFbi(object instance, object[] args, Type declaredType)
	{
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (IsTypeNameHintMatch(args[i], GameSymbols.ReleaseTownUi.FbiCityWrapperTypeHints))
				{
					LogReleaseTownUiEvidenceDiagnostic(
						"captured-city-fbi-arg",
						"arg:" + i + "|type:" + args[i].GetType().FullName);
					return args[i];
				}
			}
		}

		if (instance == null)
			return null;
		var type = declaredType ?? instance.GetType();
		foreach (var name in new[] { "bzac", "cdwl", "byza", "byzb", "cawv" })
		{
			var cityWrapper = TryReadMemberFieldOnly(instance, type, name);
			if (IsTypeNameHintMatch(cityWrapper, GameSymbols.ReleaseTownUi.FbiCityWrapperTypeHints))
			{
				LogReleaseTownUiEvidenceDiagnostic(
					"captured-city-fbi-field",
					(type.FullName ?? type.Name) + "." + name);
				return cityWrapper;
			}
		}
		return null;
	}

	private static void CaptureReleaseTownUiCityWrapperPayload(object wrapper)
	{
		if (wrapper == null)
			return;
		var config = TryReadReleaseCityWrapperConfig(wrapper, null)
		             ?? TryReadFirstMemberFieldOnly(wrapper, wrapper.GetType(), GameSymbols.ReleaseTownUi.SessionCityConfigFields)
		             ?? TryReadFirstExactNoArgMethod<ObjCityConfig>(wrapper, wrapper.GetType(), GameSymbols.ReleaseTownUi.SessionCityConfigMethods);
		var city = TryReadReleaseCityWrapperCity(wrapper, null)
		           ?? TryReadFirstMemberFieldOnly(wrapper, wrapper.GetType(), GameSymbols.ReleaseTownUi.SessionCityDataFields)
		           ?? TryReadFirstExactNoArgMethod<Hex.Session.Data.ObjCity>(wrapper, wrapper.GetType(), GameSymbols.ReleaseTownUi.SessionCityDataMethods);
		var fraction = ReadObjCityConfigFractionProfiled(config, "capture-city-wrapper-payload", null)
		               ?? TryReadMemberFieldOnly(config, config?.GetType(), "fraction") as string;
		var cityConfigSid = DeobfInteropCompat.GetConfigElementId(config);
		if (Homm3CustomFactionRegistry.TryResolveTownPresentationFactionSid(fraction, cityConfigSid, out var presentationFaction))
			_releaseTownUiFraction = presentationFaction;
		else if (!string.IsNullOrEmpty(fraction))
			_releaseTownUiFraction = fraction;
		if (city is Hex.Session.Data.ObjCity objCity)
			_releaseTownUiCityData = objCity;
	}

	private static object TryExtractReleaseTownUiCityWrapper(object instance, object[] args, Type declaredType)
	{
		var argWrapper = TryExtractReleaseTownUiCityWrapperFromArgs(args);
		if (IsCityWrapperCandidate(argWrapper))
			return argWrapper;
		if (instance == null)
			return null;
		var type = declaredType ?? instance.GetType();
		var direct = TryReadMemberFieldOnly(instance, type, GameSymbols.ReleaseTownUi.CitySessionCityWrapper.FieldName)
			?? TryReadMemberFieldOnly(instance, type, GameSymbols.ReleaseTownUi.BuildingSessionCityWrapper.FieldName)
			?? TryReadMemberFieldOnly(instance, type, "byik")
			?? TryReadMemberFieldOnly(instance, type, "byhj")
			?? TryReadMemberFieldOnly(instance, type, "cmhc")
			?? TryReadMemberFieldOnly(instance, type, "byyn")
			?? TryReadMemberFieldOnly(instance, type, "byxm")
			?? TryReadMemberFieldOnly(instance, type, "cduv")
			?? TryReadMemberFieldOnly(instance, type, "bzdm")
			?? TryReadMemberFieldOnly(instance, type, "cawv")
			?? TryReadMemberFieldOnly(instance, type, "cnen")
			?? TryReadMemberFieldOnly(instance, type, "bzac")
			?? TryReadMemberFieldOnly(instance, type, "cdwl");
		if (IsCityWrapperCandidate(direct))
			return direct;
		var discovered = TryDiscoverCityWrapperMember(instance, type);
		if (IsCityWrapperCandidate(discovered))
			return discovered;
		LogReleaseTownUiInstanceMembers(instance, type);
		return null;
	}

	private static object TryExtractReleaseTownUiCityWrapperFromArgs(object[] args)
	{
		if (args == null || args.Length == 0)
			return null;
		for (var i = 0; i < args.Length; i++)
		{
			var value = args[i];
			if (!IsCityWrapperCandidate(value))
				continue;
			LogReleaseTownUiEvidenceDiagnostic(
				"captured-city-wrapper-arg",
				"arg:" + i + "|type:" + value.GetType().FullName);
			return value;
		}
		return null;
	}

	private static object TryDiscoverCityWrapperMember(object instance, Type declaredType)
	{
		if (instance == null)
			return null;
		try
		{
			for (var current = declaredType ?? instance.GetType(); current != null && current != typeof(object); current = current.BaseType)
			{
				var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				FieldInfo[] fields;
				try
				{
					fields = current.GetFields(flags);
				}
				catch
				{
					fields = Array.Empty<FieldInfo>();
				}

				foreach (var field in fields)
				{
					try
					{
						var value = field.GetValue(instance);
						if (IsCityWrapperCandidate(value))
						{
							LogReleaseTownUiEvidenceDiagnostic("discovered-city-wrapper-field", current.FullName + "." + field.Name);
							return value;
						}
					}
					catch
					{
					}
				}
			}
		}
		catch
		{
		}
		return null;
	}

	private static void LogReleaseTownUiInstanceMembers(object instance, Type declaredType)
	{
		try
		{
			if (!Homm3DiagnosticFlags.IsEnabled("releaseTownUiDiagnostics.flag"))
				return;
			var type = declaredType ?? instance?.GetType();
			if (type == null)
				return;
			var typeName = type.FullName ?? type.Name;
			if (SafeActiveSceneName() != "cityDungeon"
				&& typeName.IndexOf("BhBuildingView", StringComparison.OrdinalIgnoreCase) < 0
				&& typeName.IndexOf("BhUIBuilding", StringComparison.OrdinalIgnoreCase) < 0)
			{
				return;
			}
			if (!_releaseTownUiDumpedTypes.Add(typeName))
				return;
			if (_releaseTownUiMemberDumpCount++ >= 12)
				return;
			var details = new System.Text.StringBuilder();
			details.Append("type:").Append(typeName);
			var written = 0;
			for (var current = type; current != null && current != typeof(object) && written < 30; current = current.BaseType)
			{
				FieldInfo[] fields;
				try
				{
					fields = current.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
				}
				catch
				{
					fields = Array.Empty<FieldInfo>();
				}
				foreach (var field in fields)
				{
					if (written++ >= 30)
						break;
					var valueType = "unreadable";
					try
					{
						var value = field.GetValue(instance);
						valueType = value == null ? "null" : value.GetType().FullName;
					}
					catch
					{
					}
					details.Append("|field:").Append(current.Name).Append('.').Append(field.Name).Append('=').Append(valueType);
				}
			}
			LogReleaseTownUiEvidenceDiagnostic("instance-member-dump", details.ToString());
		}
		catch
		{
		}
	}

	private static bool IsCityWrapperCandidate(object wrapper)
	{
		if (wrapper == null)
			return false;
		var wrapperType = wrapper.GetType();
		if ((IsTypeNameHintMatch(wrapper, GameSymbols.ReleaseTownUi.CityWrapperTypeHints)
		     || IsTypeNameHintMatch(wrapper, GameSymbols.ReleaseTownUi.FbiCityWrapperTypeHints))
		    && (TryReadReleaseCityWrapperConfig(wrapper, null) != null
		        || TryReadReleaseCityWrapperCity(wrapper, null) != null))
			return true;
		if (TryReadFirstMemberFieldOnly(wrapper, wrapperType, GameSymbols.ReleaseTownUi.SessionCityConfigFields) != null
		    || TryReadFirstMemberFieldOnly(wrapper, wrapperType, GameSymbols.ReleaseTownUi.SessionCityDataFields) != null)
			return true;
		return false;
	}

	private static void LogReleaseTownUiDiagnostic(string reason, string detail)
	{
		try
		{
			if (!Homm3DiagnosticFlags.IsEnabled("releaseTownUiDiagnostics.flag"))
				return;
			if (_releaseTownUiDiagnosticCount++ >= 80)
				return;
			AgentDebugLog.Write(
				"release-town-ya",
				"ModActions",
				reason,
				"{\"reason\":" + AgentDebugLog.QuotedJsonString(reason)
					+ ",\"detail\":" + AgentDebugLog.QuotedJsonString(detail)
					+ ",\"activeScene\":" + AgentDebugLog.QuotedJsonString(SafeActiveSceneName())
					+ ",\"frame\":" + Time.frameCount + "}");
		}
		catch
		{
		}
	}

	private static void LogCityBackdropApplyDecision(string stage, RectTransform root, Scene panelScene, string fraction, string backdropPath)
	{
		try
		{
			if (!Homm3DiagnosticFlags.IsEnabled("releaseTownUiDiagnostics.flag"))
				return;
			if (_releaseTownUiBackdropDecisionCount++ >= 32)
				return;

			var wrapper = GetCurrentCityWrapper();
			var config = wrapper == null
				? null
				: TryReadFirstMemberFieldOnly(wrapper, wrapper.GetType(), GameSymbols.ReleaseTownUi.SessionCityConfigFields);
			var rawFraction = config == null ? null : ReadObjCityConfigFractionProfiled(config, "diagnostic-current-city-fraction", null);
			var configSid = config == null ? null : DeobfInteropCompat.GetConfigElementId(config);
			var rootName = root == null || root.gameObject == null ? "(null)" : root.gameObject.name;
			var panelSceneName = panelScene.IsValid() ? panelScene.name : "invalid";
			var pathState = string.IsNullOrEmpty(backdropPath)
				? "empty"
				: File.Exists(backdropPath) ? "exists" : "missing";

			AgentDebugLog.Write(
				"release-town-ya",
				"ModActions",
				"city-backdrop-decision",
				"{\"stage\":" + AgentDebugLog.QuotedJsonString(stage)
					+ ",\"root\":" + AgentDebugLog.QuotedJsonString(rootName)
					+ ",\"panelScene\":" + AgentDebugLog.QuotedJsonString(panelSceneName)
					+ ",\"activeScene\":" + AgentDebugLog.QuotedJsonString(SafeActiveSceneName())
					+ ",\"fraction\":" + AgentDebugLog.QuotedJsonString(fraction)
					+ ",\"rawFraction\":" + AgentDebugLog.QuotedJsonString(rawFraction)
					+ ",\"configSid\":" + AgentDebugLog.QuotedJsonString(configSid)
					+ ",\"wrapperType\":" + AgentDebugLog.QuotedJsonString(wrapper == null ? null : wrapper.GetType().FullName)
					+ ",\"backdropPath\":" + AgentDebugLog.QuotedJsonString(backdropPath)
					+ ",\"pathState\":" + AgentDebugLog.QuotedJsonString(pathState)
					+ ",\"frame\":" + Time.frameCount + "}");
		}
		catch
		{
		}
	}

	private static void LogCityBackdropPostcondition(RectTransform root, RawImage image, Texture2D texture, string fraction, Scene panelScene, string backdropPath)
	{
		try
		{
			if (!Homm3DiagnosticFlags.IsEnabled("releaseTownUiDiagnostics.flag"))
				return;
			if (_releaseTownUiBackdropPostconditionCount++ >= 32)
				return;

			var imageObject = image == null ? null : image.gameObject;
			var imageTransform = image == null ? null : image.transform;
			var color = image == null ? default : image.color;
			AgentDebugLog.Write(
				"release-town-ya",
				"ModActions",
				"city-backdrop-postcondition",
				"{\"fraction\":" + AgentDebugLog.QuotedJsonString(fraction)
					+ ",\"panelScene\":" + AgentDebugLog.QuotedJsonString(panelScene.IsValid() ? panelScene.name : "invalid")
					+ ",\"activeScene\":" + AgentDebugLog.QuotedJsonString(SafeActiveSceneName())
					+ ",\"rootPath\":" + AgentDebugLog.QuotedJsonString(GetTransformPath(root == null ? null : root.transform))
					+ ",\"imagePath\":" + AgentDebugLog.QuotedJsonString(GetTransformPath(imageTransform))
					+ ",\"parentPath\":" + AgentDebugLog.QuotedJsonString(GetTransformPath(imageTransform == null ? null : imageTransform.parent))
					+ ",\"imageActiveSelf\":" + (imageObject != null && imageObject.activeSelf ? "true" : "false")
					+ ",\"imageActiveInHierarchy\":" + (imageObject != null && imageObject.activeInHierarchy ? "true" : "false")
					+ ",\"imageEnabled\":" + (image != null && image.enabled ? "true" : "false")
					+ ",\"alpha\":" + color.a.ToString("0.###", CultureInfo.InvariantCulture)
					+ ",\"siblingIndex\":" + (imageTransform == null ? -1 : imageTransform.GetSiblingIndex())
					+ ",\"rootChildCount\":" + (root == null ? -1 : root.childCount)
					+ ",\"texture\":" + AgentDebugLog.QuotedJsonString(texture == null ? null : texture.name)
					+ ",\"textureWidth\":" + (texture == null ? 0 : texture.width)
					+ ",\"textureHeight\":" + (texture == null ? 0 : texture.height)
					+ ",\"backdropPath\":" + AgentDebugLog.QuotedJsonString(backdropPath)
					+ ",\"frame\":" + Time.frameCount + "}");
		}
		catch
		{
		}
	}

	private static void LogCityPanelCensus(string reason)
	{
		try
		{
			if (!Homm3DiagnosticFlags.IsEnabled("releaseTownUiDiagnostics.flag"))
				return;
			if (_releaseTownUiCanvasCensusCount++ >= 12)
				return;

			var details = new StringBuilder();
			var seen = new HashSet<int>();
			var count = 0;
			var canvases = Resources.FindObjectsOfTypeAll<Canvas>();
			for (var pass = 0; pass < 3; pass++)
			{
				for (var i = 0; i < canvases.Length; i++)
				{
					var canvas = canvases[i];
					if (canvas == null || canvas.gameObject == null)
						continue;
					var go = canvas.gameObject;
					var id = go.GetInstanceID();
					if (seen.Contains(id) || !ShouldLogCityPanelCensusCanvas(canvas, pass))
						continue;
					seen.Add(id);
					if (count++ >= 12)
					{
						details.Append("|more");
						pass = 3;
						break;
					}

					var scene = go.scene;
					details.Append("|canvas:")
						.Append(go.name)
						.Append("@")
						.Append(scene.IsValid() ? scene.name : "invalid")
						.Append(":activeSelf=")
						.Append(go.activeSelf)
						.Append(":activeHierarchy=")
						.Append(go.activeInHierarchy)
						.Append(":enabled=")
						.Append(canvas.enabled)
						.Append(":path=")
						.Append(GetTransformPath(go.transform));
				}
			}
			LogReleaseTownUiDiagnostic(reason + "-canvas-census", details.Length == 0 ? "(none)" : details.ToString());
		}
		catch
		{
		}
	}

	private static bool ShouldLogCityPanelCensusCanvas(Canvas canvas, int pass)
	{
		var go = canvas == null ? null : canvas.gameObject;
		if (go == null)
			return false;
		var scene = go.scene;
		var activeScene = SceneManager.GetActiveScene();
		var name = go.name ?? "";
		var path = GetTransformPath(go.transform);
		var cityNamed = name.IndexOf("City", StringComparison.OrdinalIgnoreCase) >= 0
		                || name.IndexOf("Town", StringComparison.OrdinalIgnoreCase) >= 0
		                || path.IndexOf("City", StringComparison.OrdinalIgnoreCase) >= 0
		                || path.IndexOf("Town", StringComparison.OrdinalIgnoreCase) >= 0;
		return pass switch
		{
			0 => scene.IsValid()
			     && activeScene.IsValid()
			     && scene.handle == activeScene.handle
			     && go.activeInHierarchy,
			1 => cityNamed,
			_ => true
		};
	}

	private static string GetTransformPath(Transform transform)
	{
		try
		{
			if (transform == null)
				return "(null)";
			var parts = new List<string>();
			for (var current = transform; current != null && parts.Count < 16; current = current.parent)
				parts.Add(current.gameObject == null ? current.name : current.gameObject.name);
			parts.Reverse();
			return string.Join("/", parts);
		}
		catch
		{
			return "(error)";
		}
	}

	private static void LogReleaseTownUiBackMainDiagnostic(string reason, string detail)
	{
		try
		{
			if (_releaseTownUiBackMainDiagnosticCount++ >= 24)
				return;
			if (detail != null && detail.Length > 1200)
				detail = detail.Substring(0, 1200);
			Plugin.LogSource?.LogInfo(
				"Release town back arrow: "
				+ reason
				+ " | "
				+ detail
				+ " | scene="
				+ SafeActiveSceneName()
				+ " | frame="
				+ Time.frameCount);
		}
		catch
		{
		}
	}

	private static void LogReleaseTownUiEvidenceDiagnostic(string reason, string detail)
	{
		try
		{
			if (!Homm3DiagnosticFlags.IsEnabled("releaseTownUiDiagnostics.flag"))
				return;
			if (_releaseTownUiEvidenceDiagnosticCount++ >= 72)
				return;
			AgentDebugLog.Write(
				"release-town-ya",
				"ModActions",
				reason,
				"{\"reason\":" + AgentDebugLog.QuotedJsonString(reason)
					+ ",\"detail\":" + AgentDebugLog.QuotedJsonString(detail)
					+ ",\"activeScene\":" + AgentDebugLog.QuotedJsonString(SafeActiveSceneName())
					+ ",\"frame\":" + Time.frameCount + "}");
		}
		catch
		{
		}
	}

	private static string SafeActiveSceneName()
	{
		try
		{
			var scene = SceneManager.GetActiveScene();
			return scene.IsValid() ? scene.name : "invalid";
		}
		catch
		{
			return "unknown";
		}
	}

	internal static void ClearCustomCityBackdrop()
	{
		RestoreTownDonorGraphics();
		if (_cityBackdropImage == null)
		{
			return;
		}

		try
		{
			if (_cityBackdropImage.gameObject != null)
			{
				HideObject(_cityBackdropImage.gameObject);
			}
		}
		catch (Exception ex)
		{
			Warn("ClearCustomCityBackdrop", ex);
		}
		finally
		{
			_cityBackdropImage = null;
			_lastCityBackdropApplyFrame = -1;
			_cityBackdropBasisSceneHandle = 0;
			_cityBackdropBasisRootId = 0;
			_cityBackdropBasisWidth = 0f;
			_cityBackdropBasisHeight = 0f;
			ClearCustomTownUiAboveArtGate();
		}
	}

	internal static void EnsureCityMenuCanvasesVisible()
	{
	}

	internal static bool HasCityBackdrop => _cityBackdropImage != null && _cityBackdropImage.gameObject.activeInHierarchy;


	internal static void AdjustCityBackdropSibling(int delta)
	{
		_cityBackdropSiblingIndex = Math.Max(0, GetAppliedCityBackdropSiblingIndex() + delta);
		ApplyCustomCityBackdrop();
	}

	internal static void AdjustCityBackdropOffset(float deltaX, float deltaY)
	{
		_cityBackdropOffsetX += deltaX;
		_cityBackdropOffsetY += deltaY;
		ApplyCustomCityBackdrop();
	}

	internal static void AdjustCityBackdropScale(float delta)
	{
		_cityBackdropScale = Mathf.Clamp(_cityBackdropScale + delta, 0.25f, 3f);
		ApplyCustomCityBackdrop();
	}

	internal static void AdjustCityBackdropAlpha(float delta)
	{
		_cityBackdropAlpha = Mathf.Clamp01(_cityBackdropAlpha + delta);
		ApplyCustomCityBackdrop();
	}

	internal static void ResetCityBackdropAdjustments()
	{
		_cityBackdropSiblingIndex = 0;
		_cityBackdropOffsetX = 0f;
		_cityBackdropOffsetY = 0f;
		_cityBackdropScale = 1f;
		_cityBackdropAlpha = 1f;
		ApplyCustomCityBackdrop();
	}

	internal static string GetCityBackdropAdjusterStatus()
	{
		return $"layer={GetAppliedCityBackdropSiblingIndex()} offset={_cityBackdropOffsetX:0},{_cityBackdropOffsetY:0} scale={_cityBackdropScale:0.00} alpha={_cityBackdropAlpha:0.00}";
	}

	private static int GetAppliedCityBackdropSiblingIndex()
	{
		if (_cityBackdropImage == null || _cityBackdropImage.transform.parent == null)
		{
			return _cityBackdropSiblingIndex;
		}

		return _cityBackdropImage.transform.GetSiblingIndex();
	}

	private static void ApplyCityBackdropTransform(RectTransform root, RectTransform rect)
	{
		GetStableCityBackdropBasis(root, out var width, out var height);
		var ox = _cityBackdropOffsetX * (width / CityBackdropReferenceWidth);
		var oy = _cityBackdropOffsetY * (height / CityBackdropReferenceHeight);
		var effectiveScale = _cityBackdropScale * GetConfiguredCityBackdropScale();
		var growX = width * (effectiveScale - 1f);
		var growY = height * (effectiveScale - 1f);

		rect.anchorMin = Vector2.zero;
		rect.anchorMax = Vector2.one;
		rect.pivot = new Vector2(0.5f, 0.5f);
		if (IsCurrentHomm3TownBackdrop())
		{
			// HoMM3 town art lives in the top-left of a padded 1920x1080 plate.
			// Scale from the top-left so reducing black padding does not push content
			// off the left/top edges of the city panel.
			rect.offsetMin = new Vector2(ox, -growY + oy);
			rect.offsetMax = new Vector2(growX + ox, oy);
			return;
		}

		var padX = growX * 0.5f;
		var padY = growY * 0.5f;
		rect.offsetMin = new Vector2(-padX + ox, -padY + oy);
		rect.offsetMax = new Vector2(padX + ox, padY + oy);
	}

	private static void GetStableCityBackdropBasis(RectTransform root, out float width, out float height)
	{
		var rootRect = root != null ? root.rect : default;
		var currentWidth = rootRect.width > 1f ? rootRect.width : Screen.width;
		var currentHeight = rootRect.height > 1f ? rootRect.height : Screen.height;
		var scene = root != null && root.gameObject != null ? root.gameObject.scene : default;
		var sceneHandle = scene.IsValid() ? scene.handle : 0;
		var rootId = root != null ? root.GetInstanceID() : 0;
		var needsCapture = _cityBackdropBasisWidth <= 1f
			|| _cityBackdropBasisHeight <= 1f
			|| _cityBackdropBasisSceneHandle != sceneHandle
			|| _cityBackdropBasisRootId != rootId;
		// Live-positive Factory: first apply can lock a pre-layout size; refresh when panel grows/shrinks.
		if (!needsCapture
			&& _cityBackdropBasisWidth > 1f
			&& _cityBackdropBasisHeight > 1f
			&& (Mathf.Abs(currentWidth - _cityBackdropBasisWidth) > Mathf.Max(8f, _cityBackdropBasisWidth * 0.04f)
				|| Mathf.Abs(currentHeight - _cityBackdropBasisHeight) > Mathf.Max(8f, _cityBackdropBasisHeight * 0.04f)))
		{
			needsCapture = true;
		}

		if (needsCapture)
		{
			_cityBackdropBasisSceneHandle = sceneHandle;
			_cityBackdropBasisRootId = rootId;
			_cityBackdropBasisWidth = currentWidth;
			_cityBackdropBasisHeight = currentHeight;
		}
		width = _cityBackdropBasisWidth > 1f ? _cityBackdropBasisWidth : currentWidth;
		height = _cityBackdropBasisHeight > 1f ? _cityBackdropBasisHeight : currentHeight;
	}

	internal static void ResetCityBackdropBasisSize()
	{
		_cityBackdropBasisSceneHandle = 0;
		_cityBackdropBasisRootId = 0;
		_cityBackdropBasisWidth = 0f;
		_cityBackdropBasisHeight = 0f;
	}

	internal static void ApplyCityBackdropTransformToLayerRoot(RectTransform root, RectTransform rect)
	{
		ApplyCityBackdropTransform(root, rect);
	}

	private static void ApplyCustomTownOverlayRect(RectTransform rect)
	{
		if (rect == null)
			return;

		rect.anchorMin = Vector2.zero;
		rect.anchorMax = Vector2.one;
		rect.pivot = new Vector2(0.5f, 0.5f);
		rect.anchoredPosition = Vector2.zero;
		rect.sizeDelta = Vector2.zero;
		rect.localPosition = new Vector3(0f, 0f, 0f);
		rect.localRotation = Quaternion.identity;
		rect.localScale = Vector3.one;
	}

	internal static string GetCityBackdropTransformSignature(RectTransform root)
	{
		if (root == null)
		{
			return "none";
		}

		var rootRect = root.rect;
		var width = rootRect.width > 1f ? rootRect.width : Screen.width;
		var height = rootRect.height > 1f ? rootRect.height : Screen.height;
		// Quantize so sub-pixel rect jitter does not thrash town-layer signatures every sync.
		return Mathf.RoundToInt(width).ToString()
			+ "x"
			+ Mathf.RoundToInt(height).ToString()
			+ "@off="
			+ Mathf.RoundToInt(_cityBackdropOffsetX * 1000f).ToString()
			+ ","
			+ Mathf.RoundToInt(_cityBackdropOffsetY * 1000f).ToString()
			+ "@scale="
			+ Mathf.RoundToInt(_cityBackdropScale * 1000f).ToString()
			+ "@baseScale="
			+ Mathf.RoundToInt(GetConfiguredCityBackdropScale() * 1000f).ToString();
	}

	private static float GetConfiguredCityBackdropScale()
	{
		if (!IsCurrentHomm3TownBackdrop())
		{
			return 1f;
		}

		if (_cachedStrongholdTownBackdropScale > 0f)
		{
			return _cachedStrongholdTownBackdropScale;
		}

		var scale = 1.18f;
		try
		{
			var config = LauncherConfigReader.TryLoad();
			if (config != null)
			{
				var configType = config.GetType();
				var field = configType.GetField("Homm3StrongholdTownBackdropScale", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (field != null)
				{
					scale = Convert.ToSingle(field.GetValue(config));
				}
				else
				{
					var property = configType.GetProperty("Homm3StrongholdTownBackdropScale", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
					if (property != null)
					{
						scale = Convert.ToSingle(property.GetValue(config));
					}
				}
			}
		}
		catch
		{
			scale = 1.18f;
		}

		_cachedStrongholdTownBackdropScale = Mathf.Clamp(scale, 1f, 1.6f);
		return _cachedStrongholdTownBackdropScale;
	}

	private static bool IsCurrentHomm3TownBackdrop()
	{
		var fraction = GetCurrentCityFraction();
		return Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction);
	}

	private static void ApplyCityBackdropSiblingIndex(RectTransform root, Transform transform)
	{
		if (root == null || transform == null)
			return;

		// Custom town art must stay behind native town UI. Runtime adjustment is deliberately
		// ignored here after the canvas/prefab experiments proved forward ordering hides menus.
		transform.SetSiblingIndex(0);
	}

	private static void EnsureCityBackdropCanvasOrder(GameObject go)
	{
		if (go == null)
			return;

		var source = ResolveCityPanelSourceCanvas();
		if (source != null
		    && go.transform != null
		    && IsTransformUnder(go.transform, source.transform))
		{
			// Share CanvasCityPanel domain via parenting. Nested ScreenSpaceCamera canvases
			// drop sortingLayerID to 0 (live Route A proof) and break town art presentation.
			var nested = go.GetComponent<Canvas>();
			if (nested != null && nested.enabled)
				nested.enabled = false;
			LogTownCanvasNestedShareOnce(source, go);
			return;
		}

		var canvas = go.GetComponent<Canvas>() ?? go.AddComponent<Canvas>();
		EnsureCustomTownArtCanvas(canvas, CustomTownBackdropSortingOrder);
	}

	internal static Canvas ResolveCityPanelSourceCanvas(RectTransform cityPanelRoot = null)
	{
		cityPanelRoot ??= FindCityPanelRectTransform();
		if (cityPanelRoot == null || cityPanelRoot.gameObject == null)
		{
			_cachedCityPanelSourceCanvas = null;
			_cachedCityPanelSourceCanvasId = 0;
			_cachedCityPanelSourceSceneHandle = 0;
			return null;
		}

		var panelGo = cityPanelRoot.gameObject;
		var sceneHandle = panelGo.scene.IsValid() ? panelGo.scene.handle : 0;
		var panelId = panelGo.GetInstanceID();
		if (_cachedCityPanelSourceCanvas != null
		    && _cachedCityPanelSourceCanvas
		    && _cachedCityPanelSourceCanvasId == panelId
		    && _cachedCityPanelSourceSceneHandle == sceneHandle)
		{
			return _cachedCityPanelSourceCanvas;
		}

		var source = panelGo.GetComponent<Canvas>();
		if (source == null)
			source = cityPanelRoot.GetComponentInParent<Canvas>();

		_cachedCityPanelSourceCanvas = source;
		_cachedCityPanelSourceCanvasId = panelId;
		_cachedCityPanelSourceSceneHandle = sceneHandle;
		return source;
	}

	private static int GetCityPanelSourceSortingOrder()
	{
		var source = ResolveCityPanelSourceCanvas();
		return source != null ? source.sortingOrder : 0;
	}

	private static int GetCustomTownNativeUiFloorSortingOrder()
	{
		return GetCityPanelSourceSortingOrder() + CustomTownLayerSortingOrder + CustomTownArtToNativeUiGap;
	}

	private static int GetReleaseTownActivePanelSortingOrder()
	{
		return GetCustomTownNativeUiFloorSortingOrder() + ReleaseTownActivePanelOrderGap;
	}

	private static int GetReleaseTownNavigationSortingOrder()
	{
		return GetCustomTownNativeUiFloorSortingOrder() + ReleaseTownNavigationOrderGap;
	}

	/// <summary>
	/// Route A: share CanvasCityPanel render domain (BhScreen→jj.hqq is ScreenSpaceCamera-bound).
	/// Nested under the panel: disable child Canvas so graphics inherit the panel (live proof:
	/// nested ScreenSpaceCamera canvases keep sortingLayerID=0 while panel uses a UI layer).
	/// Sibling/orphan canvases: mirror panel mode/camera/plane/layer/order; never invent Overlay.
	/// </summary>
	internal static void EnsureCustomTownArtCanvas(Canvas canvas, int relativeOrder)
	{
		if (canvas == null)
			return;

		var source = ResolveCityPanelSourceCanvas();
		if (source != null
		    && source != canvas
		    && canvas.transform != null
		    && IsTransformUnder(canvas.transform, source.transform))
		{
			if (canvas.enabled)
				canvas.enabled = false;
			canvas.overrideSorting = false;
			LogTownCanvasNestedShareOnce(source, canvas.gameObject);
			return;
		}

		canvas.enabled = true;
		if (source == null || source == canvas)
		{
			// Fail closed on inventing Overlay: keep existing domain, only assert relative order.
			canvas.overrideSorting = true;
			canvas.sortingOrder = relativeOrder;
			if (!_loggedTownCanvasMirror)
			{
				_loggedTownCanvasMirror = true;
				Plugin.LogSource?.LogWarning(
					"HoMM3 town art canvas: CanvasCityPanel source canvas missing; left renderMode="
					+ canvas.renderMode
					+ " worldCamera="
					+ (canvas.worldCamera == null ? "null" : canvas.worldCamera.name)
					+ " sortingOrder="
					+ canvas.sortingOrder);
			}
			return;
		}

		var targetOrder = source.sortingOrder + relativeOrder;
		var needsWrite = canvas.renderMode != source.renderMode
			|| canvas.worldCamera != source.worldCamera
			|| !Mathf.Approximately(canvas.planeDistance, source.planeDistance)
			|| canvas.sortingLayerID != source.sortingLayerID
			|| !canvas.overrideSorting
			|| canvas.sortingOrder != targetOrder;
		if (!needsWrite)
			return;

		canvas.overrideSorting = true;
		canvas.renderMode = source.renderMode;
		canvas.worldCamera = source.worldCamera;
		canvas.planeDistance = source.planeDistance;
		canvas.sortingOrder = targetOrder;
		canvas.sortingLayerID = source.sortingLayerID;
		var layerName = SortingLayer.IDToName(source.sortingLayerID);
		if (!string.IsNullOrEmpty(layerName))
			canvas.sortingLayerName = layerName;

		if (!_loggedTownCanvasMirror)
		{
			_loggedTownCanvasMirror = true;
			Plugin.LogSource?.LogInfo(
				"HoMM3 town canvas mirror (Route A): source="
				+ DescribeUnityPath(source.gameObject)
				+ " mode="
				+ source.renderMode
				+ " cam="
				+ (source.worldCamera == null ? "null" : source.worldCamera.name)
				+ " layer="
				+ source.sortingLayerID
				+ " order="
				+ source.sortingOrder
				+ " -> target="
				+ DescribeUnityPath(canvas.gameObject)
				+ " mode="
				+ canvas.renderMode
				+ " cam="
				+ (canvas.worldCamera == null ? "null" : canvas.worldCamera.name)
				+ " layer="
				+ canvas.sortingLayerID
				+ " order="
				+ canvas.sortingOrder
				+ " relative="
				+ relativeOrder);
		}
	}

	private static void LogTownCanvasNestedShareOnce(Canvas source, GameObject target)
	{
		if (_loggedTownCanvasMirror || source == null || target == null)
			return;
		_loggedTownCanvasMirror = true;
		Plugin.LogSource?.LogInfo(
			"HoMM3 town canvas share (Route A nested): disabled child Canvas under "
			+ DescribeUnityPath(source.gameObject)
			+ " so art inherits mode="
			+ source.renderMode
			+ " cam="
			+ (source.worldCamera == null ? "null" : source.worldCamera.name)
			+ " layer="
			+ source.sortingLayerID
			+ " order="
			+ source.sortingOrder
			+ "; target="
			+ DescribeUnityPath(target));
	}

	internal static void EnsureNativeTownMenusAboveCustomArt()
	{
		if (!IsActiveSceneCityInterior())
			return;
		if (ShouldSkipRouteATownPanelLift())
			return;
		var cityRoot = FindCityPanelRectTransform();
		if (cityRoot == null || cityRoot.gameObject == null)
			return;
		var fraction = GetCurrentCityFraction();
		if (string.IsNullOrWhiteSpace(fraction)
		    || !Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction))
			return;

		var frame = Time.frameCount;
		var artRoot = _customTownArtRoot != null ? _customTownArtRoot.transform : null;
		ForEachLoadedSceneCanvas(canvas =>
		{
			if (canvas == null || canvas.gameObject == null)
				return;

			var go = canvas.gameObject;
			if (artRoot != null && IsTransformUnder(canvas.transform, artRoot))
				return;
			if (string.Equals(go.name, CityBackdropObjectName, StringComparison.Ordinal)
			    || string.Equals(go.name, CustomTownArtRootObjectName, StringComparison.Ordinal)
			    || string.Equals(go.name, "OfflineUnlockStrongholdTownLayers", StringComparison.Ordinal)
			    || string.Equals(go.name, "SkyBackground", StringComparison.Ordinal))
			{
				return;
			}

			if (!IsLiftableCustomTownUiCanvas(canvas, cityRoot))
				return;

			EnsureNativeTownUiCanvasAboveCustomArt(canvas);
			if (IsKnownCityMenuCanvas(canvas))
				EnsureLiftedTownCanvasGraphicRaycaster(canvas, "native-menu-above-art");
		});
		_lastNativeTownMenuRaycasterFrame = frame;
	}

	private static bool IsLiftableCustomTownUiCanvas(Canvas canvas, RectTransform cityRoot)
	{
		if (canvas == null || canvas.gameObject == null)
			return false;
		var go = canvas.gameObject;
		var scene = go.scene;
		if (!scene.IsValid())
			return false;

		var name = go.name ?? string.Empty;
		if (CityMenuCanvasNames.Contains(name) && canvas.enabled)
		{
			if (IsCanvasInActiveCityScene(canvas, cityRoot, requireActive: true))
				return true;
			// Marketplace / artifact-merchant Session.UI canvases may live outside CityUI.
			if (IsReleaseTownSessionUiPanelCanvasName(name)
			    && go.activeInHierarchy
			    && IsActiveSceneCityInterior())
			{
				return true;
			}
		}
		if (string.Equals(scene.name, "CityUI", StringComparison.Ordinal))
			return false;
		return IsReleaseTooltipUiCanvas(canvas)
		       && canvas.enabled
		       && go.activeInHierarchy;
	}

	private static bool IsReleaseTooltipUiCanvas(Canvas canvas)
	{
		if (canvas == null || canvas.gameObject == null)
			return false;
		var scene = canvas.gameObject.scene;
		if (!scene.IsValid() || !string.Equals(scene.name, "tooltipsUI", StringComparison.Ordinal))
			return false;

		var name = canvas.gameObject.name ?? string.Empty;
		return string.Equals(name, "TOOLTIP UI CANVAS", StringComparison.Ordinal)
		       || string.Equals(name, "TOOLTIP UI CANVAS RAYCAST", StringComparison.Ordinal)
		       || string.Equals(name, "TOOLTIP UI CANVAS OVERLAY", StringComparison.Ordinal);
	}

	private static int GetCustomTownUiTargetSortingOrder(Canvas canvas, Canvas source)
	{
		var floor = (source != null ? source.sortingOrder : 0)
			+ CustomTownLayerSortingOrder
			+ CustomTownArtToNativeUiGap;
		if (canvas == null || canvas.gameObject == null)
			return floor;

		var name = canvas.gameObject.name ?? string.Empty;
		var sceneName = canvas.gameObject.scene.IsValid() ? canvas.gameObject.scene.name : string.Empty;
		if (string.Equals(sceneName, "tooltipsUI", StringComparison.Ordinal))
		{
			if (string.Equals(name, "TOOLTIP UI CANVAS RAYCAST", StringComparison.Ordinal))
				return floor + ReleaseTownTooltipRaycastOrderGap;
			if (string.Equals(name, "TOOLTIP UI CANVAS", StringComparison.Ordinal)
			    || string.Equals(name, "TOOLTIP UI CANVAS OVERLAY", StringComparison.Ordinal))
			{
				return floor + ReleaseTownTooltipOrderGap;
			}
		}
		if (string.Equals(sceneName, "CityUI", StringComparison.Ordinal)
		    || ReleaseTownPrimaryPanelCanvasNameSet.Contains(name))
		{
			if (string.Equals(name, "CityNavigation", StringComparison.Ordinal))
				return floor + ReleaseTownNavigationOrderGap;
			if (ReleaseTownPrimaryPanelCanvasNameSet.Contains(name)
			    || string.Equals(name, "CONVERT UNIT PANEL", StringComparison.Ordinal)
			    || string.Equals(name, "PortalSummoning", StringComparison.Ordinal)
			    || string.Equals(name, "Mycelium Roots", StringComparison.Ordinal)
			    || string.Equals(name, "ShrineOfRebirth", StringComparison.Ordinal)
			    || string.Equals(name, "HERO TRAINING PANEL", StringComparison.Ordinal)
			    || string.Equals(name, "UNIT WINDOW SESSION", StringComparison.Ordinal)
			    || string.Equals(name, "FLOATING UI CANVAS", StringComparison.Ordinal)
			    || string.Equals(name, "OptionalVersionUnitRewardView", StringComparison.Ordinal))
			{
				// Hire/build/market + double-click unit preview windows must clear custom town art.
				return floor + ReleaseTownActivePanelOrderGap;
			}
			if (string.Equals(name, "CanvasCityPanel", StringComparison.Ordinal)
			    || string.Equals(name, "GarnisonPanel", StringComparison.Ordinal)
			    || string.Equals(name, "CanvasCityTechHUDPanel", StringComparison.Ordinal))
			{
				// TechHUD includes a full-screen plate — never raise it above navigation/menus.
				// Floor only keeps it comparable to CanvasCityPanel; native order is preserved
				// when already higher (see Math.Max fallthrough via early return of canvas.sortingOrder
				// when we skip forced lift in EnsureNativeTownUiCanvasAboveCustomArt).
				return floor;
			}
			if (string.Equals(name, "TABS PANEL", StringComparison.Ordinal))
				return floor + ReleaseTownActivePanelOrderGap + 20;
		}

		// Preserve unusually high native orders; otherwise keep at least above custom art.
		if (canvas.sortingOrder >= floor + ReleaseTownTooltipOrderGap)
			return canvas.sortingOrder;
		return Math.Max(canvas.sortingOrder, floor);
	}

	/// <summary>
	/// Preserve native BhScreen render domain. Only raise sortingOrder above mirrored custom art
	/// when already in a comparable domain — never force ScreenSpaceOverlay / null worldCamera.
	/// Nested city-panel HUD (GarnisonPanel): clear overrideSorting so input uses the parent
	/// CanvasCityPanel GraphicRaycaster instead of a lifted orphan canvas.
	/// </summary>
	private static void EnsureNativeTownUiCanvasAboveCustomArt(Canvas canvas)
	{
		if (canvas == null || canvas.gameObject == null)
			return;

		var source = ResolveCityPanelSourceCanvas();
		if (source != null
		    && source != canvas
		    && canvas.transform != null
		    && IsTransformUnder(canvas.transform, source.transform))
		{
			// Nested under CanvasCityPanel: inherit parent sort/raycast domain (native BhScreen shape).
			if (canvas.overrideSorting)
				canvas.overrideSorting = false;
			EnsureNativeTownNestedHudRaycaster(canvas);
			return;
		}

		// CanvasCityTechHUDPanel owns a full-screen plate. Forcing overrideSorting/order above
		// city menus hides navigation/garrison (live 2026-07-20). Leave native BhScreen order alone.
		var canvasName = canvas.gameObject.name ?? string.Empty;
		if (string.Equals(canvasName, "CanvasCityTechHUDPanel", StringComparison.Ordinal))
			return;

		if (source != null && canvas.renderMode != source.renderMode)
		{
			// Different render domain: do not invent Overlay lift ladders.
			if (IsReleaseTooltipUiCanvas(canvas))
				NormalizeReleaseTooltipOverlayDepth(canvas.transform);
			return;
		}

		var targetOrder = GetCustomTownUiTargetSortingOrder(canvas, source);
		if (!canvas.overrideSorting)
			canvas.overrideSorting = true;
		if (canvas.sortingOrder < targetOrder)
			canvas.sortingOrder = targetOrder;
		if (IsReleaseTooltipUiCanvas(canvas))
			NormalizeReleaseTooltipOverlayDepth(canvas.transform);
	}

	/// <summary>
	/// Nested HUD must keep its existing GraphicRaycaster enabled. Do not AddComponent — that was
	/// the June 22 brute-force path after overrideSorting lifts orphaned GarnisonPanel from BhScreen.
	/// </summary>
	private static void EnsureNativeTownNestedHudRaycaster(Canvas canvas)
	{
		if (canvas == null || canvas.gameObject == null)
			return;
		var raycaster = canvas.GetComponent<GraphicRaycaster>();
		if (raycaster != null && !raycaster.enabled)
			raycaster.enabled = true;
	}

	private static void NormalizeReleaseTooltipOverlayDepth(Transform root)
	{
		if (root == null)
			return;

		var rect = root.GetComponent<RectTransform>();
		if (rect != null)
		{
			var local = rect.localPosition;
			if (Math.Abs(local.z) > 0.01f)
			{
				local.z = 0f;
				rect.localPosition = local;
			}
		}

		for (var i = 0; i < root.childCount; i++)
			NormalizeReleaseTooltipOverlayDepth(root.GetChild(i));
	}

	private static bool ReassertKnownCityMenuCanvasRaycasters(string source)
	{
		var changed = false;
		ForEachCityUiCanvas(canvas =>
		{
			if (EnsureLiftedTownCanvasGraphicRaycaster(canvas, source))
				changed = true;
		});
		return changed;
	}
	private static bool EnsureLiftedTownCanvasGraphicRaycaster(Canvas canvas, string source)
	{
		if (canvas == null || canvas.gameObject == null)
			return false;
		if (!IsKnownCityMenuCanvas(canvas))
			return false;

		var cityPanel = ResolveCityPanelSourceCanvas();
		if (cityPanel != null
		    && cityPanel != canvas
		    && canvas.transform != null
		    && IsTransformUnder(canvas.transform, cityPanel.transform))
		{
			// Nested under CanvasCityPanel: never invent a second GraphicRaycaster.
			EnsureNativeTownNestedHudRaycaster(canvas);
			return false;
		}

		if (!CanvasOwnsActiveRaycastableGraphic(canvas))
			return false;

		var raycaster = canvas.GetComponent<GraphicRaycaster>();
		if (raycaster != null)
		{
			if (raycaster.enabled)
				return false;
			raycaster.enabled = true;
			return true;
		}

		canvas.gameObject.AddComponent<GraphicRaycaster>();
		if (!_loggedTownCanvasRaycasterLift)
		{
			_loggedTownCanvasRaycasterLift = true;
			// Separate root city menus only (not nested GarnisonPanel). Nested HUD uses parent domain.
			LogReleaseTownUiDiagnostic(
				"town-lifted-canvas-raycaster-added",
				"source:" + (source ?? "null")
					+ "|canvas:" + DescribeUnityPath(canvas.gameObject)
					+ "|order:" + canvas.sortingOrder);
		}
		return true;
	}

	private static bool IsKnownCityMenuCanvas(Canvas canvas)
	{
		if (canvas == null || canvas.gameObject == null)
			return false;
		var sceneName = canvas.gameObject.scene.IsValid() ? canvas.gameObject.scene.name : string.Empty;
		return string.Equals(sceneName, "CityUI", StringComparison.Ordinal)
		       && CityMenuCanvasNames.Contains(canvas.gameObject.name ?? string.Empty);
	}
	private static bool CanvasOwnsActiveRaycastableGraphic(Canvas canvas)
	{
		if (canvas == null || canvas.gameObject == null || !canvas.enabled || !canvas.gameObject.activeInHierarchy)
			return false;

		var graphics = canvas.GetComponentsInChildren<Graphic>(true);
		for (var i = 0; i < graphics.Length; i++)
		{
			var graphic = graphics[i];
			if (graphic == null || graphic.canvas != canvas)
				continue;
			if (graphic.enabled && graphic.raycastTarget && graphic.gameObject != null && graphic.gameObject.activeInHierarchy)
				return true;
		}
		return false;
	}
	private static void ScheduleNativeTownMenuLiftFrames(int frames)
	{
		if (frames > 0)
			_customTownUiLiftUntilFrame = Math.Max(_customTownUiLiftUntilFrame, Time.frameCount + frames);
	}

	private static bool IsTransformUnder(Transform child, Transform ancestor)
	{
		if (child == null || ancestor == null)
			return false;
		var current = child;
		while (current != null)
		{
			if (current == ancestor)
				return true;
			current = current.parent;
		}
		return false;
	}

	private static int _townUiAboveArtSceneHandle = -1;
	private static bool _townUiDonorSuppressApplied;

	internal static void EnsureUnitDetailPreviewWindowAboveTownArt()
	{
		try
		{
			if (!IsActiveSceneCityInterior())
				return;
			ForEachLoadedSceneCanvas(canvas =>
			{
				if (canvas == null || canvas.gameObject == null)
					return;
				var name = canvas.gameObject.name ?? string.Empty;
				if (!string.Equals(name, "UNIT WINDOW SESSION", StringComparison.Ordinal)
				    && !string.Equals(name, "FLOATING UI CANVAS", StringComparison.Ordinal))
				{
					return;
				}
				EnsureNativeTownUiCanvasAboveCustomArt(canvas);
				EnsureLiftedTownCanvasGraphicRaycaster(canvas, "unit-detail-preview-show");
			});
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"unit-detail-preview-above-art-failed",
				ex.GetType().Name + ":" + ex.Message);
		}
	}

	internal static void EnsureCustomTownUiAboveTownArt(RectTransform root)
	{
		if (root == null)
			return;

		EnsureCityPanelNativeHudSiblingOrder(root, null);

		var scene = root.gameObject != null ? root.gameObject.scene : default;
		var handle = scene.IsValid() ? scene.handle : -1;
		if (_townUiDonorSuppressApplied && _townUiAboveArtSceneHandle == handle)
			return;

		var suppressed = 0;
		for (var i = 0; i < root.childCount; i++)
		{
			var child = root.GetChild(i);
			var go = child == null ? null : child.gameObject;
			if (go == null)
				continue;

			var name = go.name ?? string.Empty;
			if (string.Equals(name, CityBackdropObjectName, StringComparison.Ordinal)
			    || string.Equals(name, "OfflineUnlockStrongholdTownLayers", StringComparison.Ordinal)
			    || string.Equals(name, CustomTownArtRootObjectName, StringComparison.Ordinal))
			{
				continue;
			}

			var rect = go.GetComponent<RectTransform>();
			if (rect == null)
				continue;

			if (LooksLikeNativeTownMenuOrHud(go))
			{
				var canvas = go.GetComponent<Canvas>();
				if (canvas != null)
					EnsureNativeTownUiCanvasAboveCustomArt(canvas);
				continue;
			}

			if (LooksLikeDonorTownBackgroundGraphic(root, go, rect))
			{
				suppressed += SuppressTownDonorGraphics(go);
				continue;
			}
		}

		_townUiDonorSuppressApplied = true;
		_townUiAboveArtSceneHandle = handle;
		if (suppressed > 0)
			Plugin.LogSource?.LogInfo("HoMM3 town backdrop: suppressed " + suppressed + " donor town background graphic(s) under CanvasCityPanel.");
	}

	/// <summary>
	/// Keep custom art/layers at the bottom of CanvasCityPanel; native HUD children (GarnisonPanel,
	/// etc.) must sort above them via sibling index so nested canvases can inherit the parent domain.
	/// </summary>
	internal static void EnsureCityPanelNativeHudSiblingOrder(RectTransform panelRoot, RectTransform layerRoot)
	{
		if (panelRoot == null)
			return;

		var artRootIndex = FindDirectChildIndex(panelRoot, CustomTownArtRootObjectName);
		if (artRootIndex >= 0 && artRootIndex != 0)
			panelRoot.GetChild(artRootIndex).SetSiblingIndex(0);

		if (layerRoot != null && layerRoot.parent == panelRoot)
		{
			if (layerRoot.GetSiblingIndex() != 1)
				layerRoot.SetSiblingIndex(1);
		}
		else
		{
			var layersIndex = FindDirectChildIndex(panelRoot, "OfflineUnlockStrongholdTownLayers");
			if (layersIndex >= 0 && layersIndex != 1)
				panelRoot.GetChild(layersIndex).SetSiblingIndex(1);
		}

		var artFloor = 0;
		var layersIdx = FindDirectChildIndex(panelRoot, "OfflineUnlockStrongholdTownLayers");
		if (layersIdx >= 0)
			artFloor = layersIdx;
		else if (FindDirectChildIndex(panelRoot, CustomTownArtRootObjectName) >= 0)
			artFloor = 0;

		// Only GarnisonPanel — do not reshuffle every CityMenuCanvasNames child (can promote
		// full-bleed plates over usable controls).
		var garrisonIndex = FindDirectChildIndex(panelRoot, "GarnisonPanel");
		if (garrisonIndex >= 0 && garrisonIndex <= artFloor)
			panelRoot.GetChild(garrisonIndex).SetSiblingIndex(artFloor + 1);
	}

	private static int FindDirectChildIndex(RectTransform parent, string childName)
	{
		if (parent == null || string.IsNullOrEmpty(childName))
			return -1;
		for (var i = 0; i < parent.childCount; i++)
		{
			var child = parent.GetChild(i);
			if (child != null && string.Equals(child.name, childName, StringComparison.Ordinal))
				return i;
		}
		return -1;
	}

	internal static void ClearCustomTownUiAboveArtGate()
	{
		_townUiDonorSuppressApplied = false;
		_townUiAboveArtSceneHandle = -1;
	}

	private static bool LooksLikeNativeTownMenuOrHud(GameObject go)
	{
		if (go == null)
			return false;
		return CityMenuCanvasNames.Contains(go.name ?? string.Empty);
	}

	private static bool LooksLikeDonorTownBackgroundGraphic(RectTransform root, GameObject go, RectTransform rect)
	{
		if (root == null || go == null || rect == null)
			return false;
		if (go.GetComponentInChildren<Selectable>(true) != null)
			return false;
		var graphics = go.GetComponentsInChildren<Graphic>(true);
		if (graphics == null || graphics.Length == 0)
			return false;
		var rootRect = root.rect;
		var rootArea = Math.Max(1f, rootRect.width * rootRect.height);
		var rectArea = Math.Abs(rect.rect.width * rect.rect.height);
		var name = go.name ?? string.Empty;
		return rectArea >= rootArea * 0.35f
		       || name.IndexOf("background", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("backdrop", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("scene", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static int SuppressTownDonorGraphics(GameObject go)
	{
		var count = 0;
		var graphics = go.GetComponentsInChildren<Graphic>(true);
		for (var i = 0; i < graphics.Length; i++)
		{
			var graphic = graphics[i];
			if (graphic == null || graphic == _cityBackdropImage)
				continue;
			if (!_suppressedTownDonorGraphics.ContainsKey(graphic))
				_suppressedTownDonorGraphics[graphic] = graphic.enabled;
			if (graphic.enabled)
			{
				graphic.enabled = false;
				count++;
			}
		}
		return count;
	}

	private static void RestoreTownDonorGraphics()
	{
		if (_suppressedTownDonorGraphics.Count == 0)
			return;
		foreach (var pair in _suppressedTownDonorGraphics.ToArray())
		{
			if (pair.Key != null)
				pair.Key.enabled = pair.Value;
		}
		_suppressedTownDonorGraphics.Clear();
	}
	private static void LogCanvasSortOrders()
	{
		try
		{
			var rows = new List<(int order, bool overrideSorting, bool enabled, string name)>();
			ForEachLoadedSceneCanvas(c =>
			{
				if (c == null || c.gameObject == null || !c.isActiveAndEnabled)
					return;
				rows.Add((c.sortingOrder, c.overrideSorting, c.isActiveAndEnabled, c.gameObject.name));
			});
			rows.Sort((a, b) => a.order.CompareTo(b.order));
			var sb = new System.Text.StringBuilder("Active canvases (name | sortOrder | overrideSort | enabled):");
			for (var i = 0; i < rows.Count; i++)
			{
				var c = rows[i];
				sb.Append($"\n  [{c.order,5}] override={c.overrideSorting,-5} enabled={c.enabled,-5}  {c.name}");
			}
			Plugin.LogSource?.LogInfo(sb.ToString());
		}
		catch (Exception ex)
		{
			Warn("Canvas sort order dump failed", ex);
		}
	}

	private static string GetCityBackdropPath(string fraction)
	{
		string rel = null;
		// Vanilla Grove ("nature") keeps its native town scene: the old 2D mockup overlay
		// covered the 3D town and its custom canvas reordering could leave town menus unusable.
		if (Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction))
		{
			rel = GetHomm3CityBackdropPluginRelativePath(fraction);
		}
		// dungeon_raw: Core generator --raw (Dungeon-parallel stress-test ids); same backdrop hook.
		else if (string.Equals(fraction, "dungeon_raw", StringComparison.Ordinal))
		{
			rel = Homm3StrongholdCityBackdropPluginRelativePath;
		}
		else if (!string.IsNullOrEmpty(fraction) && fraction.StartsWith("homm3_", StringComparison.Ordinal))
		{
			if (_loggedMissingHomm3TownBackdrop.Add(fraction))
			{
				Plugin.LogSource?.LogWarning("No release town backdrop is enabled for " + fraction + "; clearing custom backdrop instead of falling back to Stronghold art.");
			}
		}

		if (rel == null)
		{
			return null;
		}

		return Path.GetFullPath(Path.Combine(Paths.PluginPath, "OfflineUnlockMod", rel));
	}

	private static string GetHomm3CityBackdropPluginRelativePath(string factionSid)
	{
		return Path.Combine(
			"homm3_runtime_assets",
			"town_scene_refs",
			factionSid,
			"mockups",
			factionSid + "_background_mock_1920x1080.png");
	}

	internal static string GetCurrentCityFraction()
	{
		try
		{
			string rawFraction = null;
			string cityConfigSid = null;
			if (!string.IsNullOrEmpty(_releaseTownUiFraction))
				rawFraction = _releaseTownUiFraction;
			var config = GetCurrentCityConfig();
			if (config != null)
			{
				cityConfigSid = DeobfInteropCompat.GetConfigElementId(config);
				rawFraction ??= ReadObjCityConfigFractionProfiled(config, "get-current-city-fraction", null)
				              ?? TryReadMember(config, "fraction") as string;
			}
			if (Homm3CustomFactionRegistry.TryResolveTownPresentationFactionSid(rawFraction, cityConfigSid, out var presentationFaction))
				return presentationFaction;
			return rawFraction;
		}
		catch
		{
		}
		return null;
	}

	internal static Hex.Session.Data.ObjCity GetCurrentCityData()
	{
		try
		{
			if (_releaseTownUiCityData != null)
				return _releaseTownUiCityData;
			var wrapper = GetCurrentCityWrapper();
			var city = wrapper == null
				? null
				: TryReadReleaseCityWrapperCity(wrapper, null)
				  ?? TryReadFirstMemberFieldOnly(wrapper, wrapper.GetType(), GameSymbols.ReleaseTownUi.SessionCityDataFields)
				  ?? TryReadFirstExactNoArgMethod<Hex.Session.Data.ObjCity>(wrapper, wrapper.GetType(), GameSymbols.ReleaseTownUi.SessionCityDataMethods);
			return city as Hex.Session.Data.ObjCity;
		}
		catch
		{
			return null;
		}
	}

#if !RELEASE_CANDIDATE_BUILD
	internal static LiveProbeTownUiState GetLiveProbeTownUiState()
	{
		object wrapper = null;
		object config = null;
		Hex.Session.Data.ObjCity city = null;
		try
		{
			wrapper = GetCurrentCityWrapper();
			config = wrapper == null ? null : GetCurrentCityConfig();
			city = GetCurrentCityData();
		}
		catch
		{
		}

		return new LiveProbeTownUiState
		{
			ActiveScene = SafeActiveSceneName(),
			CachedFraction = _releaseTownUiFraction,
			CurrentFraction = GetCurrentCityFraction(),
			CachedWrapperPresent = wrapper != null,
			CachedWrapperType = wrapper == null ? null : wrapper.GetType().FullName,
			CachedWrapperKnownType = IsKnownLiveProbeTownWrapper(wrapper),
			CurrentCityConfigNonNull = config != null,
			CurrentCityConfigType = config == null ? null : config.GetType().FullName,
			CurrentCityDataNonNull = city != null,
			CurrentCityDataType = city == null ? null : city.GetType().FullName,
			Layers = Homm3StrongholdTownLayers.GetLiveProbeLayerState()
		};
	}

	internal static object GetLiveProbeTownWrapper()
	{
		return GetCurrentCityWrapper();
	}

	internal static LiveProbeTownLayerRefreshResult LiveProbeRefreshTownLayersFromCachedWrapper()
	{
		var result = new LiveProbeTownLayerRefreshResult
		{
			LayersBefore = Homm3StrongholdTownLayers.GetLiveProbeLayerState(),
			OldFraction = _releaseTownUiFraction,
			OldCityDataNonNull = _releaseTownUiCityData != null,
			OldCityConfigNonNull = GetCurrentCityConfig() != null
		};
		try
		{
			var activeScene = SafeActiveSceneName();
			if (!IsCityInteriorSceneName(activeScene))
				return FailLiveProbeRefresh(result, "out_of_scope", "Active scene must be cityHuman or cityHuman2; activeScene='" + activeScene + "'.");

			var wrapper = GetCurrentCityWrapper();
			result.WrapperType = wrapper == null ? null : wrapper.GetType().FullName;
			if (!IsKnownLiveProbeTownWrapper(wrapper))
				return FailLiveProbeRefresh(result, "unexpected_wrapper_type", "Cached town wrapper is not a known release town UI city wrapper type.");

			var wrapperType = wrapper.GetType();
			var config = TryReadFirstExactNoArgMethod<ObjCityConfig>(wrapper, wrapperType, GameSymbols.ReleaseTownUi.SessionCityConfigMethods);
			var city = TryReadFirstExactNoArgMethod<Hex.Session.Data.ObjCity>(wrapper, wrapperType, GameSymbols.ReleaseTownUi.SessionCityDataMethods);
			if (config == null || city == null)
				return FailLiveProbeRefresh(result, "getter_returned_null", "Exact ObjCityConfig/ObjCity getter returned null.");

			var fraction = ReadObjCityConfigFractionProfiled(config, "live-probe-refresh-town-layers", null);
			var cityConfigSid = DeobfInteropCompat.GetConfigElementId(config);
			if (Homm3CustomFactionRegistry.TryResolveTownPresentationFactionSid(fraction, cityConfigSid, out var presentationFaction))
				fraction = presentationFaction;
			if (!Homm3CustomFactionRegistry.IsCustomFactionSid(fraction))
				return FailLiveProbeRefresh(result, "not_custom_faction", "Resolved fraction is not a custom faction: '" + (fraction ?? "") + "'.");

			_releaseTownUiCityWrapper = wrapper;
			_releaseTownUiFraction = fraction;
			_releaseTownUiCityData = city;
			ApplyCustomCityBackdrop();
			Homm3StrongholdTownLayers.SyncCurrentCityLayers();

			result.Ok = true;
			result.NewFraction = _releaseTownUiFraction;
			result.NewCityDataNonNull = _releaseTownUiCityData != null;
			result.NewCityConfigNonNull = GetCurrentCityConfig() != null;
			result.LayersAfter = Homm3StrongholdTownLayers.GetLiveProbeLayerState();
			return result;
		}
		catch (Exception ex)
		{
			return FailLiveProbeRefresh(result, "exception", ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static LiveProbeTownLayerRefreshResult FailLiveProbeRefresh(LiveProbeTownLayerRefreshResult result, string code, string message)
	{
		result.Ok = false;
		result.ErrorCode = code;
		result.ErrorMessage = message;
		result.NewFraction = _releaseTownUiFraction;
		result.NewCityDataNonNull = _releaseTownUiCityData != null;
		result.NewCityConfigNonNull = GetCurrentCityConfig() != null;
		result.LayersAfter = Homm3StrongholdTownLayers.GetLiveProbeLayerState();
		return result;
	}

	private static bool IsKnownLiveProbeTownWrapper(object wrapper)
	{
		if (wrapper == null)
			return false;
		var type = wrapper.GetType();
		var fullName = type.FullName ?? "";
		var name = type.Name ?? "";
		foreach (var hint in GameSymbols.ReleaseTownUi.CityWrapperTypeHints)
		{
			if (string.Equals(fullName, hint, StringComparison.Ordinal)
			    || string.Equals(name, hint, StringComparison.Ordinal))
				return true;
		}
		return false;
	}
#endif

	private static object GetCurrentCityConfig()
	{
		var wrapper = GetCurrentCityWrapper();
		return wrapper == null
			? null
			: TryReadReleaseCityWrapperConfig(wrapper, null)
			  ?? TryReadFirstMemberFieldOnly(wrapper, wrapper.GetType(), GameSymbols.ReleaseTownUi.SessionCityConfigFields)
			  ?? TryReadFirstExactNoArgMethod<ObjCityConfig>(wrapper, wrapper.GetType(), GameSymbols.ReleaseTownUi.SessionCityConfigMethods);
	}

	internal static object GetCurrentCityWrapper()
	{
		var sessionType = GetHexType("Hex.UI.City.BhCityUISession");
		if (sessionType == null)
			return IsCityWrapperCandidate(_releaseTownUiCityWrapper) ? _releaseTownUiCityWrapper : null;
		var me = TryReadReleaseCityStaticSession();
		var sessionWrapper = me == null ? null
			: TryReadReleaseCitySessionWrapper(me)
			  ?? TryReadFirstMemberFieldOnly(me, sessionType, GameSymbols.ReleaseTownUi.CitySessionCityWrapperFields);
		if (IsCityWrapperCandidate(sessionWrapper))
			return sessionWrapper;
		return IsCityWrapperCandidate(_releaseTownUiCityWrapper) ? _releaseTownUiCityWrapper : null;
	}

	private static object TryReadReleaseCitySessionWrapper(BhCityUISession session)
	{
		if (session == null)
			return null;
		return TryReadIl2CppObjectField<Il2CppObjectBase>(
			(Il2CppObjectBase)(object)session,
			typeof(BhCityUISession),
			Il2CppClassPointerStore<BhCityUISession>.NativeClassPtr,
			GameSymbols.ReleaseTownUi.CitySessionCityWrapper,
			"city-session-wrapper-field-missing",
			null);
	}

	private static unsafe BhCityUISession TryReadReleaseCityStaticSession()
	{
		var type = typeof(BhCityUISession);
		var field = TryGetGeneratedNativeFieldInfoPtr(type, GameSymbols.ReleaseTownUi.CitySessionStaticCurrent.NativeFieldInfoName)
			?? TryGetIl2CppField(type, GameSymbols.ReleaseTownUi.CitySessionStaticCurrent.FieldName);
		if (field == IntPtr.Zero)
		{
			if (!_loggedReleaseCityStaticFieldMissing)
			{
				_loggedReleaseCityStaticFieldMissing = true;
				LogReleaseTownUiEvidenceDiagnostic(
					"city-session-static-field-missing",
					GameSymbols.ReleaseTownUi.CitySessionStaticCurrent.NativeFieldInfoName
						+ "|"
						+ GameSymbols.ReleaseTownUi.CitySessionStaticCurrent.FieldName);
			}
			return null;
		}
		try
		{
			IntPtr valuePtr;
			IL2CPP.il2cpp_field_static_get_value(field, &valuePtr);
			if (valuePtr == IntPtr.Zero)
			{
				if (!_loggedReleaseCityStaticFieldNull)
				{
					_loggedReleaseCityStaticFieldNull = true;
					LogReleaseTownUiEvidenceDiagnostic(
						"city-session-static-field-null",
						GameSymbols.ReleaseTownUi.CitySessionStaticCurrent.FieldName + "|frame:" + Time.frameCount);
				}
				return null;
			}
			return Il2CppObjectPool.Get<BhCityUISession>(valuePtr);
		}
		catch (Exception ex)
		{
			LogReleaseTownUiEvidenceDiagnostic(
				"city-session-static-field-read-failed",
				GameSymbols.ReleaseTownUi.CitySessionStaticCurrent.FieldName + "|error:" + ex.GetType().Name + ":" + ex.Message);
			return null;
		}
	}

	private static IntPtr TryGetIl2CppField(Type managedType, string fieldName)
	{
		if (managedType == null || string.IsNullOrWhiteSpace(fieldName))
			return IntPtr.Zero;
		// A refused current-build scope is already logged once by GameSymbolScope; asking Il2CppInterop for the
		// sentinel name logs an Error per call (2942 lines in one town visit on 25509697), so refuse it here.
		if (GameSymbolScope.IsSentinel(fieldName))
			return IntPtr.Zero;
		try
		{
			var classPtr = TryGetNativeClassPtr(managedType);
			return classPtr == IntPtr.Zero ? IntPtr.Zero : IL2CPP.GetIl2CppField(classPtr, fieldName);
		}
		catch
		{
			return IntPtr.Zero;
		}
	}

	private static IntPtr TryGetIl2CppField(IntPtr classPtr, string fieldName)
	{
		if (classPtr == IntPtr.Zero || string.IsNullOrWhiteSpace(fieldName))
			return IntPtr.Zero;
		if (GameSymbolScope.IsSentinel(fieldName))
			return IntPtr.Zero;
		try
		{
			return IL2CPP.GetIl2CppField(classPtr, fieldName);
		}
		catch
		{
			return IntPtr.Zero;
		}
	}

	private static object TryReadStaticMember(Type type, string name)
	{
		return type == null ? null : GetModActionMemberValue(null, type, name);
	}

	private static object TryReadMember(object instance, string name)
	{
		return instance == null ? null : GetModActionMemberValue(instance, instance.GetType(), name);
	}

	private static object TryReadMember(object instance, Type declaredType, string name)
	{
		return instance == null ? null : GetModActionMemberValue(instance, declaredType ?? instance.GetType(), name);
	}

	private static BhNavigationButton TryReadNavigationButton(MainMenuNavigationView view, string[] memberNames)
	{
		if (view == null || memberNames == null)
			return null;
		for (var i = 0; i < memberNames.Length; i++)
		{
			var button = TryReadMember(view, typeof(MainMenuNavigationView), memberNames[i]) as BhNavigationButton;
			if (button != null)
				return button;
		}
		return null;
	}

	private static object TryReadMemberFieldOnly(object instance, Type declaredType, string name)
	{
		if (instance == null || string.IsNullOrWhiteSpace(name))
			return null;
		var type = declaredType ?? instance.GetType();
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			try
			{
				var field = current.GetField(name, flags)
					?? current.GetField("<" + name + ">k__BackingField", flags)
					?? current.GetField("_" + name + "_k__BackingField", flags);
				if (field != null)
					return field.GetValue(instance);
			}
			catch
			{
			}
		}
		return null;
	}

	private static bool IsTypeNameHintMatch(object value, string[] typeHints)
	{
		if (value == null || typeHints == null || typeHints.Length == 0)
			return false;
		var type = value.GetType();
		var name = type.Name;
		var fullName = type.FullName;
		for (var i = 0; i < typeHints.Length; i++)
		{
			var hint = typeHints[i];
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			if (string.Equals(name, hint, StringComparison.Ordinal)
				|| string.Equals(fullName, hint, StringComparison.Ordinal)
				|| (fullName != null && fullName.EndsWith("." + hint, StringComparison.Ordinal)))
				return true;
		}
		return false;
	}

	private static bool TrySetMember(object instance, Type declaredType, string name, object value)
	{
		if (instance == null || string.IsNullOrWhiteSpace(name))
			return false;
		var type = declaredType ?? instance.GetType();
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			try
			{
				var property = current.GetProperty(name, flags)
					?? current.GetProperty("<" + name + ">k__BackingField", flags)
					?? current.GetProperty("_" + name + "_k__BackingField", flags);
				if (property != null && property.GetIndexParameters().Length == 0 && property.CanWrite)
				{
					property.SetValue(instance, value);
					return true;
				}
			}
			catch
			{
			}

			try
			{
				var field = current.GetField(name, flags)
					?? current.GetField("<" + name + ">k__BackingField", flags)
					?? current.GetField("_" + name + "_k__BackingField", flags);
				if (field != null)
				{
					field.SetValue(instance, value);
					return true;
				}
			}
			catch
			{
			}
		}
		return false;
	}

	private static bool TryInvokeMember(object instance, Type declaredType, string name, params object[] args)
	{
		if (instance == null || string.IsNullOrWhiteSpace(name))
			return false;
		var type = declaredType ?? instance.GetType();
		var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		var parameterCount = args == null ? 0 : args.Length;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			try
			{
				foreach (var method in current.GetMethods(flags))
				{
					if (method.Name != name || method.GetParameters().Length != parameterCount)
						continue;
					method.Invoke(instance, args);
					return true;
				}
			}
			catch
			{
			}
		}
		return false;
	}

	private static TMP_Text TryGetBhFontTextElement(BhFont font)
	{
		if (font == null)
			return null;
		try
		{
			var direct = TryReadMember(font, typeof(BhFont), "text")
				?? TryReadMember(font, typeof(BhFont), "label")
				?? TryReadMember(font, typeof(BhFont), "tmpText");
			if (direct is TMP_Text directText)
				return directText;

			foreach (var methodName in new[] { "shh", "sgi", "sgj" })
			{
				var method = FindInstanceMethod(typeof(BhFont), methodName, 0);
				var result = method != null ? method.Invoke(font, null) as TMP_Text : null;
				if (result != null)
					return result;
			}
		}
		catch { }
		return null;
	}

	private static bool TryStartSessionLoader(StartInfo startInfo)
	{
		if (startInfo == null)
			return false;
		try
		{
			var loaderType = typeof(Hex.Session.Loader);
			var loader = new Hex.Session.Loader();
			var startMethod = GameMember.FindFirstMethod(
				loaderType,
				typeof(void),
				new[] { typeof(StartInfo) },
				GameSymbols.SessionLoader.StartWithStartInfo);
			if (startMethod != null)
			{
				startMethod.Invoke(loader, new object[] { startInfo });
				return true;
			}

			foreach (var methodName in GameSymbols.SessionLoader.StartWithStartInfo.NameHints)
			{
				if (string.IsNullOrWhiteSpace(methodName))
					continue;
				if (TryInvokeMember(loader, loaderType, methodName, startInfo))
					return true;
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Failed to invoke session loader start method: " + ex.Message);
		}
		return false;
	}

	private static void TrySetNavigationButtonAvailable(BhNavigationButton button, bool available)
	{
		if (button == null)
			return;
		foreach (var methodName in new[] { "uay", "uaz" })
		{
			if (TryInvokeMember(button, typeof(BhNavigationButton), methodName, available))
				return;
		}
	}

	private static MethodInfo FindInstanceMethod(Type type, string methodName, int parameterCount)
	{
		if (type == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			foreach (var method in current.GetMethods(flags))
			{
				if (method.Name == methodName && method.GetParameters().Length == parameterCount)
					return method;
			}
		}
		return null;
	}

	private static object GetModActionMemberValue(object instance, Type type, string name)
	{
		if (type == null || string.IsNullOrWhiteSpace(name))
			return null;
		var flags = (instance == null ? BindingFlags.Static : BindingFlags.Instance)
			| BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			try
			{
				var property = current.GetProperty(name, flags)
					?? current.GetProperty("<" + name + ">k__BackingField", flags)
					?? current.GetProperty("_" + name + "_k__BackingField", flags);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(instance);
			}
			catch
			{
			}

			try
			{
				var field = current.GetField(name, flags)
					?? current.GetField("<" + name + ">k__BackingField", flags)
					?? current.GetField("_" + name + "_k__BackingField", flags);
				if (field != null)
					return field.GetValue(instance);
			}
			catch
			{
			}
		}
		return null;
	}

	private static object GetPropertyValueQuiet(Type type, string name, object instance)
	{
		return type?
			.GetProperty(name, BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
			?.GetValue(instance);
	}

	/// <summary>
	/// Native town interiors use scene names beginning with <c>city</c>; retired custom <c>homm3_*_city_scene</c> names are not valid here.
	/// Used so <see cref="ApplyCustomCityBackdrop"/> does not run on the adventure map (hooked from <c>CanvasScaler.OnEnable</c>).
	/// </summary>
	private static bool IsCityInteriorSceneName(string sceneName)
	{
		return !string.IsNullOrEmpty(sceneName)
			&& sceneName.StartsWith("city", StringComparison.OrdinalIgnoreCase);
	}

	/// <summary>
	/// Used by <see cref="GroveBackdropAdjusterBehaviour"/> so city-only canvas fixes do not run on the adventure map.
	/// </summary>
	internal static bool IsActiveSceneCityInterior()
	{
		try
		{
			var scene = SceneManager.GetActiveScene();
			return scene.IsValid() && IsCityInteriorSceneName(scene.name);
		}
		catch
		{
			return false;
		}
	}

	internal static string GetCurrentCityPresentationScopeKey()
	{
		try
		{
			if (!IsActiveSceneCityInterior())
				return null;
			var root = FindCityPanelRectTransform();
			if (root == null || root.gameObject == null)
				return null;
			var activeScene = SceneManager.GetActiveScene();
			var panelScene = root.gameObject.scene;
			if (!panelScene.IsValid() || !IsCityInteriorSceneName(panelScene.name))
				return null;
			return "active:" + (activeScene.IsValid() ? activeScene.handle.ToString(CultureInfo.InvariantCulture) : "0")
			       + ":" + (activeScene.IsValid() ? activeScene.name : "")
			       + "|panel:" + panelScene.handle.ToString(CultureInfo.InvariantCulture)
			       + ":" + panelScene.name
			       + "|root:" + root.GetInstanceID().ToString(CultureInfo.InvariantCulture);
		}
		catch
		{
			return null;
		}
	}

	private static RectTransform FindCityPanelRectTransform()
	{
		var scene = SceneManager.GetActiveScene();
		if (IsCachedCityPanelRootValid(scene))
			return _cachedCityPanelRoot;

		var cityPanel = GameObject.Find("CanvasCityPanel");
		if (cityPanel == null)
		{
			ClearCachedCityPanelRoot();
			return null;
		}

		var rect = cityPanel.GetComponent<RectTransform>();
		if (rect != null)
			CacheCityPanelRoot(rect, scene);
		return rect;
	}

	private static void CacheCityPanelRoot(RectTransform rect, Scene scene)
	{
		_cachedCityPanelRoot = rect;
		_cachedCityPanelSceneHandle = scene.IsValid() ? scene.handle : 0;
		_cachedCityPanelSceneName = scene.IsValid() ? scene.name : null;
	}

	private static void ClearCachedCityPanelRoot()
	{
		_cachedCityPanelRoot = null;
		_cachedCityPanelSceneHandle = 0;
		_cachedCityPanelSceneName = null;
		_cityBackdropBasisSceneHandle = 0;
		_cityBackdropBasisRootId = 0;
		_cityBackdropBasisWidth = 0f;
		_cityBackdropBasisHeight = 0f;
		_cachedCityPanelSourceCanvas = null;
		_cachedCityPanelSourceCanvasId = 0;
		_cachedCityPanelSourceSceneHandle = 0;
		_loggedTownCanvasMirror = false;
	}

	private static bool IsCachedCityPanelRootValid(Scene activeScene)
	{
		if (_cachedCityPanelRoot == null || !_cachedCityPanelRoot)
			return false;
		var go = _cachedCityPanelRoot.gameObject;
		if (go == null || !go || !go.activeInHierarchy || !string.Equals(go.name, "CanvasCityPanel", StringComparison.Ordinal))
			return false;
		var scene = go.scene;
		return scene.IsValid()
		       && activeScene.IsValid()
		       && scene.handle == activeScene.handle
		       && _cachedCityPanelSceneHandle == activeScene.handle
		       && string.Equals(scene.name, activeScene.name, StringComparison.Ordinal)
		       && string.Equals(_cachedCityPanelSceneName, activeScene.name, StringComparison.Ordinal);
	}


	private static RawImage EnsureCityBackdropImage(RectTransform root)
	{
		if (root == null)
			return null;

		var artRoot = EnsureCustomTownArtRoot(root) ?? root;
		RawImage selected = null;
		var destroy = new List<GameObject>();

		var scene = root.gameObject != null ? root.gameObject.scene : SceneManager.GetActiveScene();
		if (scene.IsValid())
		{
			var sceneRoots = scene.GetRootGameObjects();
			for (var i = 0; i < sceneRoots.Length; i++)
				CollectCityBackdropCandidates(sceneRoots[i] != null ? sceneRoots[i].transform : null, artRoot, ref selected, destroy);
		}
		else
		{
			CollectCityBackdropCandidates(artRoot, artRoot, ref selected, destroy);
		}

		for (var i = 0; i < destroy.Count; i++)
		{
			var go = destroy[i];
			if (go != null)
				UnityEngine.Object.Destroy(go);
		}

		if (selected == null)
		{
			var backdropObject = new GameObject(CityBackdropObjectName);
			backdropObject.AddComponent<RectTransform>();
			selected = backdropObject.AddComponent<RawImage>();
		}

		_cityBackdropImage = selected;
		_cityBackdropImage.name = CityBackdropObjectName;
		_cityBackdropImage.raycastTarget = false;
		_cityBackdropImage.maskable = false;
		_cityBackdropImage.gameObject.SetActive(true);
		var rect = _cityBackdropImage.rectTransform;
		if (rect.parent != artRoot)
			rect.SetParent(artRoot, worldPositionStays: false);
		ApplyCityBackdropTransform(root, rect);
		return _cityBackdropImage;
	}

	private static void CollectCityBackdropCandidates(Transform current, RectTransform artRoot, ref RawImage selected, List<GameObject> destroy)
	{
		if (current == null)
			return;

		if (string.Equals(current.name, CityBackdropObjectName, StringComparison.Ordinal))
		{
			var raw = current.GetComponent<RawImage>();
			if (raw == null)
			{
				destroy.Add(current.gameObject);
			}
			else if (selected == null)
			{
				selected = raw;
			}
			else if (selected.transform.parent != artRoot && raw.transform.parent == artRoot)
			{
				destroy.Add(selected.gameObject);
				selected = raw;
			}
			else if (selected.texture == null && raw.texture != null)
			{
				destroy.Add(selected.gameObject);
				selected = raw;
			}
			else
			{
				destroy.Add(current.gameObject);
			}
		}

		for (var i = 0; i < current.childCount; i++)
			CollectCityBackdropCandidates(current.GetChild(i), artRoot, ref selected, destroy);
	}

	internal static RectTransform EnsureCustomTownArtRoot(RectTransform cityPanelRoot)
	{
		if (cityPanelRoot == null)
			return null;

		var scene = cityPanelRoot.gameObject.scene;
		if (_customTownArtRoot != null && _customTownArtRoot.gameObject != null)
		{
			if (_customTownArtRoot.gameObject.scene != scene)
				SceneManager.MoveGameObjectToScene(_customTownArtRoot.gameObject, scene);
			ApplyCustomTownArtRootTransform(cityPanelRoot, _customTownArtRoot);
			ForceVisible(_customTownArtRoot.gameObject);
			return _customTownArtRoot;
		}

		var existing = GameObject.Find(CustomTownArtRootObjectName);
		if (existing != null)
			_customTownArtRoot = existing.GetComponent<RectTransform>() ?? existing.AddComponent<RectTransform>();
		else
		{
			var go = new GameObject(CustomTownArtRootObjectName);
			_customTownArtRoot = go.AddComponent<RectTransform>();
		}

		if (_customTownArtRoot.gameObject.scene != scene)
			SceneManager.MoveGameObjectToScene(_customTownArtRoot.gameObject, scene);
		ApplyCustomTownArtRootTransform(cityPanelRoot, _customTownArtRoot);
		ForceVisible(_customTownArtRoot.gameObject);
		return _customTownArtRoot;
	}

	private static void ApplyCustomTownArtRootTransform(RectTransform cityPanelRoot, RectTransform artRoot)
	{
		if (cityPanelRoot == null || artRoot == null)
			return;

		if (artRoot.parent != cityPanelRoot)
			artRoot.SetParent(cityPanelRoot, worldPositionStays: false);

		ApplyCustomTownOverlayRect(artRoot);
		artRoot.SetSiblingIndex(0);
		artRoot.gameObject.SetActive(true);
	}

	private static void SuppressCustomTownDonorScene(string fraction)
	{
		if (string.IsNullOrWhiteSpace(fraction))
			return;
		if (Homm3FactoryCitySceneRegistrar.OwnsActiveFactoryCityWorld(fraction))
			return;
		if (fraction != "dungeon_raw" && !Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(fraction))
			return;

		var scene = SceneManager.GetActiveScene();
		if (!scene.IsValid())
			return;

		var roots = scene.GetRootGameObjects();
		for (var i = 0; i < roots.Length; i++)
		{
			var root = roots[i];
			if (root == null)
				continue;

			if (root.name == "Terrain_environmnent" || root.name == "human_\u0441ity_allobject")
			{
				if (root.activeSelf)
					root.SetActive(false);
				continue;
			}

			if (root.name == "CityCamera")
			{
				var mainCamera = root.transform.Find("MainCamera");
				var camera = mainCamera != null ? mainCamera.GetComponent<Camera>() : root.GetComponentInChildren<Camera>(true);
				if (camera != null)
				{
					camera.clearFlags = CameraClearFlags.SolidColor;
					camera.backgroundColor = Color.black;
				}
			}
		}
	}

	private static Texture2D LoadCityBackdropTexture(string path)
	{
		var stamp = GetTextureStamp(path);
		if (_cityBackdropTexture != null
			&& string.Equals(_cityBackdropTexturePath, path, StringComparison.OrdinalIgnoreCase)
			&& string.Equals(_cityBackdropTextureStamp, stamp, StringComparison.Ordinal))
		{
			return _cityBackdropTexture;
		}

		if (!File.Exists(path))
		{
			Plugin.LogSource?.LogWarning($"Missing city backdrop image: {path}");
			return null;
		}

		var bytes = File.ReadAllBytes(path);
		var texture = new Texture2D(2, 2, TextureFormat.ARGB32, mipChain: false);
		if (!TryLoadTextureImage(texture, bytes))
		{
			UnityEngine.Object.Destroy(texture);
			Plugin.LogSource?.LogWarning($"Failed to decode city backdrop image: {path}");
			return null;
		}

		texture.name = Path.GetFileName(path);
		texture.filterMode = FilterMode.Point;
		texture.wrapMode = TextureWrapMode.Clamp;

		if (_cityBackdropTexture != null)
		{
			UnityEngine.Object.Destroy(_cityBackdropTexture);
		}

		_cityBackdropTexture = texture;
		_cityBackdropTexturePath = path;
		_cityBackdropTextureStamp = stamp;
		if (!_loggedGroveBackdropLoad)
		{
			_loggedGroveBackdropLoad = true;
			Plugin.LogSource?.LogInfo($"Loaded custom city backdrop from {path}.");
		}

		return _cityBackdropTexture;
	}

	private static string GetTextureStamp(string path)
	{
		try
		{
			var frame = Time.frameCount;
			if (!string.IsNullOrEmpty(path)
				&& _cityBackdropStampCacheByPath.TryGetValue(path, out var cached)
				&& cached != null
				&& cached.Frame == frame)
			{
				return cached.Stamp;
			}

			string stamp;
			if (!File.Exists(path))
			{
				stamp = null;
			}
			else
			{
				var info = new FileInfo(path);
				stamp = info.Length + ":" + info.LastWriteTimeUtc.Ticks;
			}

			if (!string.IsNullOrEmpty(path))
				_cityBackdropStampCacheByPath[path] = new CachedFileStamp(frame, stamp);
			return stamp;
		}
		catch
		{
			return null;
		}
	}

	private static bool TryLoadTextureImage(Texture2D texture, byte[] bytes)
	{
		// Call directly - reflection can't marshal byte[] to Il2CppStructArray<byte> correctly.
		var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
		for (var i = 0; i < bytes.Length; i++)
			il2cppBytes[i] = bytes[i];
		return ImageConversion.LoadImage(texture, il2cppBytes);
	}

	internal static Type GetHexType(string fullName)
	{
		return typeof(ObjCityConfig).Assembly.GetType(fullName, throwOnError: false);
	}

	internal static void ApplyConfiguredUiScale(BhFont font)
	{
		if (font == null || font.ignoreScaling)
		{
			return;
		}

		try
		{
			var uiScalePercent = GetConfiguredUiScalePercent();
			if (uiScalePercent == 100)
			{
				return;
			}

			var textElement = TryGetBhFontTextElement(font);
			if (textElement == null)
			{
				return;
			}

			var key = textElement.Pointer.ToInt64();
			if (!_fontScaleSnapshots.TryGetValue(key, out var snapshot))
			{
				snapshot = new FontScaleSnapshot
				{
					FontSize = textElement.fontSize,
					FontSizeMin = textElement.fontSizeMin,
					FontSizeMax = textElement.fontSizeMax,
					AutoSize = font.autosize
				};
				_fontScaleSnapshots[key] = snapshot;
			}

			var multiplier = uiScalePercent / 100f;
			textElement.fontSize = snapshot.FontSize * multiplier;
			if (snapshot.AutoSize)
			{
				textElement.fontSizeMin = snapshot.FontSizeMin * multiplier;
				textElement.fontSizeMax = snapshot.FontSizeMax * multiplier;
			}

			if (!_loggedUiScale)
			{
				_loggedUiScale = true;
				Plugin.LogSource?.LogInfo($"Applied UI scale: {uiScalePercent}%.");
			}
		}
		catch (Exception ex)
		{
			Warn("Failed to apply configured UI scale", ex);
		}
	}

	internal static void ApplyConfiguredUiScale(CanvasScaler scaler)
	{
		if (scaler == null)
		{
			return;
		}

		try
		{
			var uiScalePercent = GetConfiguredUiScalePercent();
			if (uiScalePercent == 100)
			{
				return;
			}

			var key = scaler.Pointer.ToInt64();
			if (!_canvasScaleSnapshots.TryGetValue(key, out var snapshot))
			{
				snapshot = new CanvasScaleSnapshot
				{
					UiScaleMode = scaler.uiScaleMode,
					ScaleFactor = scaler.scaleFactor,
					ReferenceResolution = scaler.referenceResolution,
					ReferencePixelsPerUnit = scaler.referencePixelsPerUnit,
					DynamicPixelsPerUnit = scaler.dynamicPixelsPerUnit
				};
				_canvasScaleSnapshots[key] = snapshot;
			}

			var multiplier = uiScalePercent / 100f;
			switch (snapshot.UiScaleMode)
			{
				case CanvasScaler.ScaleMode.ScaleWithScreenSize:
					scaler.referenceResolution = snapshot.ReferenceResolution / multiplier;
					break;
				case CanvasScaler.ScaleMode.ConstantPixelSize:
				case CanvasScaler.ScaleMode.ConstantPhysicalSize:
					scaler.scaleFactor = snapshot.ScaleFactor * multiplier;
					break;
			}

			scaler.referencePixelsPerUnit = snapshot.ReferencePixelsPerUnit;
			scaler.dynamicPixelsPerUnit = snapshot.DynamicPixelsPerUnit * multiplier;

			if (!_loggedUiScale)
			{
				_loggedUiScale = true;
				Plugin.LogSource?.LogInfo($"Applied UI scale: {uiScalePercent}%.");
			}
		}
		catch (Exception ex)
		{
			Warn("Failed to apply configured canvas scale", ex);
		}
	}

	private static int GetConfiguredUiScalePercent()
	{
		if (_cachedUiScalePercent >= 0)
		{
			return _cachedUiScalePercent;
		}

		var config = LauncherConfigReader.TryLoad();
		var uiScalePercent = 100;
		if (config != null)
		{
			var configType = config.GetType();
			var field = configType.GetField("UiScalePercent", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (field?.FieldType == typeof(int))
			{
				uiScalePercent = (int)field.GetValue(config);
			}
			else
			{
				var property = configType.GetProperty("UiScalePercent", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (property?.PropertyType == typeof(int))
				{
					uiScalePercent = (int)property.GetValue(config);
				}
			}
		}

		_cachedUiScalePercent = Math.Clamp(uiScalePercent, 80, 200);
		return _cachedUiScalePercent;
	}

	internal static void LogEarlyAccessSkip()
	{
		if (_loggedEarlyAccessSkip)
		{
			return;
		}

		_loggedEarlyAccessSkip = true;
		Plugin.LogSource?.LogInfo("Skipped ScEarlyAccess gate.");
	}

	internal static void LogDemoThankYouSkip()
	{
		if (_loggedDemoThankYouSkip)
		{
			return;
		}

		_loggedDemoThankYouSkip = true;
		Plugin.LogSource?.LogInfo("Skipped ScDemoThankYou gate.");
	}

	/// <summary>
	/// <summary>
	/// Runtime-gated proof launcher for the generated Homecoming playable shell. It uses the same main-menu
	/// <see cref="StartInfo"/> session-loader path as the disabled offline auto-launch feature, with <c>ELoad.NewMap</c>
	/// and the generated scenario-map hash. 2026-06-27: runtime route is source-prepared/build-unvalidated.
	/// </summary>
	private static void StartHomecomingPlayableShellSceneObserver()
	{
		if (_homecomingPlayableShellSceneObserverAttached)
		{
			return;
		}

		try
		{
			if (!_homecomingPlayableShellSceneObserverTypeRegistered)
			{
				Il2CppInterop.Runtime.Injection.ClassInjector.RegisterTypeInIl2Cpp<HomecomingPlayableShellSceneObserver>();
				_homecomingPlayableShellSceneObserverTypeRegistered = true;
			}

			var go = new GameObject("HOMM3_HOMECOMING_PLAYABLE_SHELL_SCENE_OBSERVER");
			go.hideFlags = HideFlags.HideAndDontSave;
			go.AddComponent<HomecomingPlayableShellSceneObserver>();
			UnityEngine.Object.DontDestroyOnLoad(go);
			_homecomingPlayableShellSceneObserverAttached = true;
			Plugin.LogSource?.LogInfo(HomecomingPlayableShellLogPrefix + " scene_observer_attached seconds=90");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError(HomecomingPlayableShellLogPrefix + " scene_observer_attach_failed error=" + ex.GetType().Name + ": " + ex.Message);
		}
	}


	private static bool TryInvokeHomecomingNativeQuickStartOpen(ScMainMenu menu)
	{
		if (menu == null || menu.mainMenuNavigationView == null)
		{
			return false;
		}
		try
		{
			var method = typeof(MainMenuNavigationView).GetMethod(
				GameSymbols.MainMenu.NativeQuickStartOpenHandler,
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly,
				null,
				new[] { typeof(bool) },
				null);
			if (method == null)
			{
				return false;
			}
			method.Invoke(menu.mainMenuNavigationView, new object[] { GameSymbols.MainMenu.NativeQuickStartOpenHandlerArgument });
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError(HomecomingPlayableShellLogPrefix + " native_quickstart_open result=FAIL native=pdj wrapper=Method_Private_Void_Boolean_0 error=" + ex.GetType().Name + ": " + ex.Message);
			return false;
		}
	}
	private static object TryInvokeHomecomingQuickStartStaticGetter(Type type, GameSymbols.MethodSymbol methodSymbol)
	{
		if (type == null || methodSymbol.NameHints == null || methodSymbol.NameHints.Length != 1)
		{
			return null;
		}
		var methodName = methodSymbol.NameHints[0];
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		var method = type.GetMethod(methodName, flags, null, Type.EmptyTypes, null);
		return method == null ? null : method.Invoke(null, null);
	}

	private static bool TryInvokeHomecomingQuickStartInstanceGetter(object instance, Type type, GameSymbols.MethodSymbol methodSymbol, out object value)
	{
		value = null;
		if (instance == null || type == null || methodSymbol.NameHints == null || methodSymbol.NameHints.Length != 1)
		{
			return false;
		}
		var methodName = methodSymbol.NameHints[0];
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		var method = type.GetMethod(methodName, flags, null, Type.EmptyTypes, null);
		if (method == null)
		{
			return false;
		}
		value = method.Invoke(instance, null);
		return true;
	}

	private static bool TryReadExactMemberValue(object instance, Type type, string name, out object value)
	{
		value = null;
		if (instance == null || type == null || string.IsNullOrWhiteSpace(name))
		{
			return false;
		}
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			var field = current.GetField(name, flags);
			if (field != null)
			{
				value = field.GetValue(instance);
				return true;
			}
			var property = current.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0)
			{
				value = property.GetValue(instance);
				return true;
			}
		}
		return false;
	}

	private static string DescribeQuickStartConfig(object config)
	{
		if (config == null)
		{
			return "null";
		}
		var type = config.GetType();
		return "present(type="
			+ type.FullName
			+ ",scenarios="
			+ DescribeCollectionMember(config, type, GameSymbols.HomecomingPlayableShell.QuickStartConfigScenariosField)
			+ ",classicMaps="
			+ DescribeCollectionMember(config, type, GameSymbols.HomecomingPlayableShell.QuickStartConfigClassicMapsField)
			+ ",singleHeroMaps="
			+ DescribeCollectionMember(config, type, GameSymbols.HomecomingPlayableShell.QuickStartConfigSingleHeroMapsField)
			+ ",difficulties="
			+ DescribeCollectionMember(config, type, GameSymbols.HomecomingPlayableShell.QuickStartConfigDifficultiesField)
			+ ")";
	}

	private static string DescribeCollectionMember(object instance, Type type, string memberName)
	{
		if (!TryReadExactMemberValue(instance, type, memberName, out var value) || value == null)
		{
			return "missing";
		}
		if (value is Array array)
		{
			return "array:" + array.Length;
		}
		if (value is System.Collections.ICollection collection)
		{
			return "collection:" + collection.Count;
		}
		return "present:" + value.GetType().FullName;
	}

	private static string DescribeObjectPresence(object value)
	{
		return value == null ? "null" : "present(type=" + value.GetType().FullName + ")";
	}

	private static string FormatSimpleValue(object value)
	{
		return value == null ? "null" : Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
	}
	private sealed class HomecomingPlayableShellCatalogCandidate
	{
		internal string Hash;
		internal string Evidence;
	}

	private static bool TryResolveHomecomingPlayableShellMapHash(out string mapHash, out string evidence, out string failure)
	{
		mapHash = null;
		evidence = null;
		failure = null;
		var candidates = new List<HomecomingPlayableShellCatalogCandidate>();
		var diagnostics = new List<string>();
		var inspectedEntries = 0;
		var inspectedDictionaries = 0;
		var catalogType = ResolveHomecomingPlayableShellCatalogType();
		if (catalogType == null)
		{
			failure = "catalog_type_missing symbol=" + GameSymbols.HomecomingPlayableShell.MapCatalogTypeId;
			return false;
		}

		CollectHomecomingPlayableShellCatalogCandidatesFromStaticMembers(catalogType, candidates, ref inspectedDictionaries, ref inspectedEntries);
		foreach (var methodName in GameSymbols.HomecomingPlayableShell.MapCatalogSingletonMethods)
		{
			var root = TryInvokeHomecomingPlayableShellCatalogSingleton(catalogType, methodName, diagnostics);
			CollectHomecomingPlayableShellCatalogCandidatesFromObject(root, "singleton:" + methodName, candidates, ref inspectedDictionaries, ref inspectedEntries);
		}
		CollectHomecomingPlayableShellCatalogCandidatesFromSingletonMethods(catalogType, candidates, diagnostics, ref inspectedDictionaries, ref inspectedEntries);

		var uniqueCandidates = candidates
			.GroupBy(candidate => candidate.Hash, StringComparer.OrdinalIgnoreCase)
			.Select(group => new HomecomingPlayableShellCatalogCandidate
			{
				Hash = group.Key,
				Evidence = string.Join(" || ", group.Select(candidate => candidate.Evidence).Distinct().Take(4).ToArray())
			})
			.ToList();
		if (uniqueCandidates.Count != 1)
		{
			failure = "catalog_match_count=" + uniqueCandidates.Count
				+ " rawCatalogMatchCount=" + candidates.Count
				+ " inspectedDictionaries=" + inspectedDictionaries
				+ " inspectedEntries=" + inspectedEntries
				+ " catalogType=" + catalogType.FullName
				+ " diagnostics=" + string.Join(" | ", diagnostics.Distinct().Take(12).ToArray());
			if (uniqueCandidates.Count > 1)
			{
				failure += " candidates=" + string.Join(" | ", uniqueCandidates.Select(c => c.Hash + ":" + c.Evidence).Take(8).ToArray());
			}
			return false;
		}

		mapHash = uniqueCandidates[0].Hash;
		evidence = uniqueCandidates[0].Evidence
			+ " rawCatalogMatchCount=" + candidates.Count
			+ " inspectedDictionaries=" + inspectedDictionaries
			+ " inspectedEntries=" + inspectedEntries;
		HomecomingPlayableShellLastResolvedHash = mapHash;
		return true;
	}

    private static bool MaybeDeferHomecomingPlayableShellLaunchForNativeCatalog(ScMainMenu menu, string catalogFailure)
    {
        if (!IsHomecomingPlayableShellCatalogInitializationMiss(catalogFailure))
        {
            return false;
        }
        if (!_homecomingPlayableShellCatalogInitInvoked)
        {
            _homecomingPlayableShellCatalogInitInvoked = true;
            _homecomingPlayableShellCatalogInitRealtime = Time.realtimeSinceStartup;
            if (!TryInvokeHomecomingNativeQuickStartOpen(menu))
            {
                Plugin.LogSource?.LogError(
                    HomecomingPlayableShellLogPrefix
                    + " native_catalog_init result=FAIL action=native_quickstart_open reason=invoke_failed mapSid="
                    + HomecomingPlayableShellMapSid
                    + " failure="
                    + catalogFailure);
                return false;
            }
            Plugin.LogSource?.LogWarning(
                HomecomingPlayableShellLogPrefix
                + " native_catalog_init result=DEFERRED action=native_quickstart_open mapSid="
                + HomecomingPlayableShellMapSid
                + " failure="
                + catalogFailure);
            return true;
        }
        if (_homecomingPlayableShellCatalogInitRealtime >= 0f && Time.realtimeSinceStartup - _homecomingPlayableShellCatalogInitRealtime < 12f)
        {
            if (!_homecomingPlayableShellCatalogInitWaitLogged)
            {
                _homecomingPlayableShellCatalogInitWaitLogged = true;
                Plugin.LogSource?.LogWarning(
                    HomecomingPlayableShellLogPrefix
                    + " native_catalog_init result=WAITING action=native_quickstart_open mapSid="
                    + HomecomingPlayableShellMapSid);
            }
            return true;
        }
        return false;
    }

    private static bool IsHomecomingPlayableShellCatalogInitializationMiss(string catalogFailure)
    {
        return !string.IsNullOrEmpty(catalogFailure)
            && catalogFailure.IndexOf("catalog_match_count=0", StringComparison.Ordinal) >= 0
            && catalogFailure.IndexOf("rawCatalogMatchCount=0", StringComparison.Ordinal) >= 0
            && catalogFailure.IndexOf("inspectedDictionaries=0", StringComparison.Ordinal) >= 0
            && catalogFailure.IndexOf("singleton:", StringComparison.Ordinal) >= 0
            && catalogFailure.IndexOf(":null", StringComparison.Ordinal) >= 0;
    }

	private static Type ResolveHomecomingPlayableShellCatalogType()
	{
		var hexAssembly = typeof(ObjCityConfig).Assembly;
		foreach (var typeName in GameSymbols.HomecomingPlayableShell.MapCatalogTypeHints)
		{
			var type = GetHexType(typeName);
			if (type != null)
				return type;
			try
			{
				foreach (var candidate in hexAssembly.GetTypes())
				{
					if (string.Equals(candidate.Name, typeName, StringComparison.Ordinal)
						|| string.Equals(candidate.FullName, typeName, StringComparison.Ordinal))
					{
						return candidate;
					}
				}
			}
			catch (ReflectionTypeLoadException ex)
			{
				foreach (var candidate in ex.Types)
				{
					if (candidate != null
						&& (string.Equals(candidate.Name, typeName, StringComparison.Ordinal)
							|| string.Equals(candidate.FullName, typeName, StringComparison.Ordinal)))
					{
						return candidate;
					}
				}
			}
		}
		return null;
	}

	private static object TryInvokeHomecomingPlayableShellCatalogSingleton(Type catalogType, string methodName, List<string> diagnostics)
	{
		if (catalogType == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		try
		{
			var method = catalogType.GetMethod(methodName, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
			if (!IsHomecomingPlayableShellCatalogSingletonMethod(catalogType, method))
			{
				diagnostics?.Add("singleton:" + methodName + ":not_found_or_shape_mismatch");
				return null;
			}
			var result = method.Invoke(null, null);
			diagnostics?.Add("singleton:" + methodName + ":" + (result == null ? "null" : "type=" + (result.GetType().FullName ?? result.GetType().Name ?? "")));
			return result;
		}
		catch (Exception ex)
		{
			diagnostics?.Add("singleton:" + methodName + ":throw=" + ex.GetType().Name + ":" + (ex.InnerException?.GetType().Name ?? ex.Message));
			return null;
		}
	}

	private static void CollectHomecomingPlayableShellCatalogCandidatesFromSingletonMethods(Type catalogType, List<HomecomingPlayableShellCatalogCandidate> candidates, List<string> diagnostics, ref int inspectedDictionaries, ref int inspectedEntries)
	{
		if (catalogType == null)
			return;
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		foreach (var method in catalogType.GetMethods(flags))
		{
			if (!IsHomecomingPlayableShellCatalogSingletonMethod(catalogType, method))
				continue;
			try
			{
				var result = method.Invoke(null, null);
				diagnostics?.Add("singleton:auto:" + method.Name + ":" + (result == null ? "null" : "type=" + (result.GetType().FullName ?? result.GetType().Name ?? "")));
				CollectHomecomingPlayableShellCatalogCandidatesFromObject(result, "singleton:auto:" + method.Name, candidates, ref inspectedDictionaries, ref inspectedEntries);
			}
			catch (Exception ex)
			{
				diagnostics?.Add("singleton:auto:" + method.Name + ":throw=" + ex.GetType().Name + ":" + (ex.InnerException?.GetType().Name ?? ex.Message));
			}
		}
	}

	private static bool IsHomecomingPlayableShellCatalogSingletonMethod(Type catalogType, MethodInfo method)
	{
		if (catalogType == null || method == null || !method.IsStatic || method.GetParameters().Length != 0)
			return false;
		var returnType = method.ReturnType;
		return returnType == catalogType || catalogType.IsAssignableFrom(returnType);
	}

	private static void CollectHomecomingPlayableShellCatalogCandidatesFromStaticMembers(Type catalogType, List<HomecomingPlayableShellCatalogCandidate> candidates, ref int inspectedDictionaries, ref int inspectedEntries)
	{
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		foreach (var field in catalogType.GetFields(flags))
		{
			try
			{
				CollectHomecomingPlayableShellCatalogCandidatesFromObject(field.GetValue(null), "static-field:" + field.Name, candidates, ref inspectedDictionaries, ref inspectedEntries);
			}
			catch
			{
			}
		}
		foreach (var property in catalogType.GetProperties(flags))
		{
			if (property.GetIndexParameters().Length != 0)
				continue;
			try
			{
				CollectHomecomingPlayableShellCatalogCandidatesFromObject(property.GetValue(null), "static-property:" + property.Name, candidates, ref inspectedDictionaries, ref inspectedEntries);
			}
			catch
			{
			}
		}
	}

	private static void CollectHomecomingPlayableShellCatalogCandidatesFromObject(object root, string label, List<HomecomingPlayableShellCatalogCandidate> candidates, ref int inspectedDictionaries, ref int inspectedEntries)
	{
		if (root == null)
			return;
		if (TryCollectHomecomingPlayableShellCatalogDictionary(root, label, candidates, ref inspectedDictionaries, ref inspectedEntries))
			return;
		var type = root.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		foreach (var field in type.GetFields(flags))
		{
			try
			{
				TryCollectHomecomingPlayableShellCatalogDictionary(field.GetValue(root), label + "." + field.Name, candidates, ref inspectedDictionaries, ref inspectedEntries);
			}
			catch
			{
			}
		}
		foreach (var property in type.GetProperties(flags))
		{
			if (property.GetIndexParameters().Length != 0)
				continue;
			try
			{
				TryCollectHomecomingPlayableShellCatalogDictionary(property.GetValue(root), label + "." + property.Name, candidates, ref inspectedDictionaries, ref inspectedEntries);
			}
			catch
			{
			}
		}
		foreach (var method in type.GetMethods(flags))
		{
			if (!IsHomecomingPlayableShellCatalogDictionaryAccessor(method))
				continue;
			try
			{
				TryCollectHomecomingPlayableShellCatalogDictionary(method.Invoke(root, null), label + "." + method.Name + "()", candidates, ref inspectedDictionaries, ref inspectedEntries);
			}
			catch
			{
			}
		}
	}

	private static bool IsHomecomingPlayableShellCatalogDictionaryAccessor(MethodInfo method)
	{
		if (method == null || method.IsStatic || method.GetParameters().Length != 0 || method.ReturnType == typeof(void))
			return false;
		var returnTypeName = method.ReturnType.FullName ?? string.Empty;
		var isStringKeyDictionary = returnTypeName.IndexOf("Dictionary`2", StringComparison.Ordinal) >= 0
			&& returnTypeName.IndexOf("System.String", StringComparison.Ordinal) >= 0;
		return isStringKeyDictionary
			|| (method.Name.StartsWith("get_field_", StringComparison.Ordinal) && returnTypeName.IndexOf("Dictionary", StringComparison.Ordinal) >= 0);
	}

	private static bool TryCollectHomecomingPlayableShellCatalogDictionary(object maybeDictionary, string label, List<HomecomingPlayableShellCatalogCandidate> candidates, ref int inspectedDictionaries, ref int inspectedEntries)
	{
		if (maybeDictionary == null || maybeDictionary is string)
			return false;
		var collected = false;
		if (maybeDictionary is IDictionary dictionary)
		{
			inspectedDictionaries++;
			foreach (DictionaryEntry entry in dictionary)
			{
				inspectedEntries++;
				TryAddHomecomingPlayableShellCatalogCandidate(entry.Key, entry.Value, label, candidates);
			}
			collected = true;
		}
		else if (maybeDictionary is IEnumerable enumerable)
		{
			var sawEntry = false;
			foreach (var item in enumerable)
			{
				if (item == null)
					continue;
				var key = TryReadMember(item, item.GetType(), "Key");
				var value = TryReadMember(item, item.GetType(), "Value");
				if (key == null && value == null)
					continue;
				if (!sawEntry)
				{
					inspectedDictionaries++;
					sawEntry = true;
				}
				inspectedEntries++;
				TryAddHomecomingPlayableShellCatalogCandidate(key, value, label, candidates);
			}
			collected = sawEntry;
		}
		if (!collected)
		{
			collected = TryCollectHomecomingPlayableShellIl2CppDictionary(maybeDictionary, label, candidates, ref inspectedDictionaries, ref inspectedEntries);
		}
		return collected;
	}

	private static bool TryCollectHomecomingPlayableShellIl2CppDictionary(object maybeDictionary, string label, List<HomecomingPlayableShellCatalogCandidate> candidates, ref int inspectedDictionaries, ref int inspectedEntries)
	{
		if (maybeDictionary == null)
			return false;
		var dictionaryType = maybeDictionary.GetType();
		var dictionaryTypeName = dictionaryType.FullName ?? string.Empty;
		if (dictionaryTypeName.IndexOf("Dictionary`2", StringComparison.Ordinal) < 0 || dictionaryTypeName.IndexOf("System.String", StringComparison.Ordinal) < 0)
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var getEnumerator = dictionaryType.GetMethod("GetEnumerator", flags, null, Type.EmptyTypes, null);
		if (getEnumerator == null)
			return false;
		var enumerator = getEnumerator.Invoke(maybeDictionary, null);
		if (enumerator == null)
			return false;
		var enumeratorType = enumerator.GetType();
		var moveNext = enumeratorType.GetMethod("MoveNext", flags, null, Type.EmptyTypes, null);
		var currentProperty = enumeratorType.GetProperty("Current", flags);
		var getCurrent = currentProperty == null ? enumeratorType.GetMethod("get_Current", flags, null, Type.EmptyTypes, null) : null;
		if (moveNext == null || (currentProperty == null && getCurrent == null))
			return false;
		inspectedDictionaries++;
		var guard = 0;
		while (guard++ < 20000 && moveNext.Invoke(enumerator, null) is bool hasNext && hasNext)
		{
			var item = currentProperty != null ? currentProperty.GetValue(enumerator) : getCurrent.Invoke(enumerator, null);
			if (item == null)
				continue;
			var key = TryReadMember(item, item.GetType(), "Key");
			var value = TryReadMember(item, item.GetType(), "Value");
			if (key == null && value == null)
				continue;
			inspectedEntries++;
			TryAddHomecomingPlayableShellCatalogCandidate(key, value, label, candidates);
		}
		return true;
	}

	private static void TryAddHomecomingPlayableShellCatalogCandidate(object key, object value, string label, List<HomecomingPlayableShellCatalogCandidate> candidates)
	{
		var hash = Convert.ToString(key, CultureInfo.InvariantCulture);
		if (!IsHomecomingPlayableShellCatalogHash(hash))
			return;
		var seen = new HashSet<object>();
		if (!CatalogEntryContainsHomecomingPlayableShellSid(value, 0, seen))
			return;
		candidates.Add(new HomecomingPlayableShellCatalogCandidate
		{
			Hash = hash,
			Evidence = label + "{" + SummarizeHomecomingPlayableShellCatalogEntry(value) + "}"
		});
	}

	private static bool IsHomecomingPlayableShellCatalogHash(string value)
	{
		return value != null && Regex.IsMatch(value, "^[0-9a-fA-F]{32}$", RegexOptions.CultureInvariant);
	}

	private static bool CatalogEntryContainsHomecomingPlayableShellSid(object value, int depth, HashSet<object> seen)
	{
		if (value == null || depth > 4)
			return false;
		if (value is string text)
			return text.IndexOf(HomecomingPlayableShellMapSid, StringComparison.OrdinalIgnoreCase) >= 0;
		var type = value.GetType();
		if (type.IsPrimitive || type.IsEnum || value is decimal || value is DateTime)
			return false;
		if (!seen.Add(value))
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			foreach (var field in current.GetFields(flags))
			{
				try
				{
					if (CatalogEntryContainsHomecomingPlayableShellSid(field.GetValue(value), depth + 1, seen))
						return true;
				}
				catch
				{
				}
			}
			foreach (var property in current.GetProperties(flags))
			{
				if (property.GetIndexParameters().Length != 0)
					continue;
				try
				{
					if (CatalogEntryContainsHomecomingPlayableShellSid(property.GetValue(value), depth + 1, seen))
						return true;
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static string SummarizeHomecomingPlayableShellCatalogEntry(object value)
	{
		var pieces = new List<string>();
		CollectHomecomingPlayableShellCatalogStrings(value, 0, new HashSet<object>(), pieces);
		return pieces.Count == 0 ? "matchedSid" : string.Join(",", pieces.Take(8).ToArray());
	}

	private static void CollectHomecomingPlayableShellCatalogStrings(object value, int depth, HashSet<object> seen, List<string> pieces)
	{
		if (value == null || depth > 3 || pieces.Count >= 8)
			return;
		if (value is string text)
		{
			if (!string.IsNullOrWhiteSpace(text) && (text.IndexOf(HomecomingPlayableShellMapSid, StringComparison.OrdinalIgnoreCase) >= 0 || text.IndexOf("Homecoming", StringComparison.OrdinalIgnoreCase) >= 0))
				pieces.Add(text.Replace(" ", "_"));
			return;
		}
		var type = value.GetType();
		if (type.IsPrimitive || type.IsEnum || value is decimal || value is DateTime || !seen.Add(value))
			return;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			foreach (var field in current.GetFields(flags))
			{
				try { CollectHomecomingPlayableShellCatalogStrings(field.GetValue(value), depth + 1, seen, pieces); } catch { }
				if (pieces.Count >= 8)
					return;
			}
			foreach (var property in current.GetProperties(flags))
			{
				if (property.GetIndexParameters().Length != 0)
					continue;
				try { CollectHomecomingPlayableShellCatalogStrings(property.GetValue(value), depth + 1, seen, pieces); } catch { }
				if (pieces.Count >= 8)
					return;
			}
		}
	}
	/// <summary>
	/// When OfflineLauncherConfig.json has autoLaunchOnMenu, start the configured skirmish after the menu is ready.
	/// </summary>
	internal static void MaybeAutoLaunchConfiguredMatch(ScMainMenu menu)
	{
		ResetAutoLaunchGateIfMenuReturned(menu);
		if (_autoLaunchTerminal)
		{
			return;
		}

		var cfg = LauncherConfigReader.TryLoad();
		if (cfg == null || !cfg.AutoLaunchOnMenu)
		{
			if (cfg != null && !cfg.AutoLaunchOnMenu && !_loggedAutoLaunchDisabledInConfig)
			{
				_loggedAutoLaunchDisabledInConfig = true;
				Plugin.LogSource?.LogInfo(
					"Auto-launch is off: set autoLaunchOnMenu to true in OfflineLauncherConfig.json (game folder, next to Core.zip) to start the configured match without clicking.");
			}

			return;
		}

		if (menu == null || menu.mainMenuNavigationView == null)
		{
			return;
		}

		if (_autoLaunchMenuReadyRealtime < 0f)
		{
			_autoLaunchMenuReadyRealtime = Time.realtimeSinceStartup;
			if (!_loggedAutoLaunchPending)
			{
				_loggedAutoLaunchPending = true;
				Plugin.LogSource?.LogInfo(
					"Auto-launch: main menu navigation ready - waiting "
					+ cfg.AutoLaunchDelayMs
					+ " ms, then starting configured match (see OfflineLauncherConfig.json).");
			}
		}

		var elapsedMs = (Time.realtimeSinceStartup - _autoLaunchMenuReadyRealtime) * 1000f;
		if (elapsedMs < cfg.AutoLaunchDelayMs)
		{
			return;
		}

		// Do not set _autoLaunchTerminal before a successful start: a single failed attempt used to block all retries.
		if (TryStartConfiguredNewGame())
		{
			_lastAutoLaunchStartRealtime = Time.realtimeSinceStartup;
			_autoLaunchTerminal = true;
			return;
		}

		if (Time.realtimeSinceStartup - _lastAutoLaunchFailLogRealtime > 5f)
		{
			_lastAutoLaunchFailLogRealtime = Time.realtimeSinceStartup;
			Plugin.LogSource?.LogWarning(
				"Auto-launch: TryStartConfiguredNewGame returned false (retrying). Check map/factions/heroes in Core.zip vs OfflineLauncherConfig.json.");
		}
	}

	internal static bool TryHandleMenuButtonClick(BhNavigationButton button)
	{
		var view = ScMainMenu.me?.mainMenuNavigationView;
		if (view == null || button == null)
		{
			return false;
		}

		var isQuickStart = SameButton(button, TryReadNavigationButton(view, GameSymbols.MainMenu.QuickStartButtonFields));
		var isNewGame = SameButton(button, TryReadNavigationButton(view, GameSymbols.MainMenu.StartNewSkirmishButtonFields));
		if (!isQuickStart && !isNewGame)
		{
			return false;
		}

		var handled = isNewGame ? TryStartConfiguredNewGame() : TryStartOfflineQuickMatch();
		if (!handled)
		{
			Plugin.LogSource?.LogWarning("Offline menu interception failed. Falling back to original handler.");
			return false;
		}

		return true;
	}

	private static bool TryStartOfflineQuickMatch()
	{
		try
		{
			var plan = GetOrCreateQuickStartPlan();
			if (plan == null)
			{
				return false;
			}

			var startInfo = new StartInfo
			{
				load = StartInfo.ELoad.Generate,
				fileHashSum = plan.TemplateHash,
				isQuickGame = true,
				settings = CreateGameStartInfo(plan)
			};

			SetEnumProperty(startInfo, nameof(StartInfo.play), "Local", 0);

			var mySides = new Il2CppStructArray<int>(1);
			mySides[0] = 0;
			startInfo.mySides = mySides;

			var sides = new Il2CppReferenceArray<StartSide>(2);
			sides[0] = CreateSide("Player", StartSide.EType.Player, plan.PlayerFraction, plan.PlayerHero, 0, 1);
			sides[1] = CreateSide("Bot", StartSide.EType.Bot, plan.BotFraction, plan.BotHero, 1, 2);
			startInfo.sides = sides;

			ScMainMenu.Hide();
			if (!TryStartSessionLoader(startInfo))
			{
				Plugin.LogSource?.LogWarning("Offline quick match: session loader start method did not run.");
				return false;
			}

			Plugin.LogSource?.LogInfo($"Started offline local match on '{plan.TemplateName}' with {plan.PlayerHero} vs {plan.BotHero}.");
			return true;
		}
		catch (Exception ex)
		{
			Warn("Failed to start offline quick match", ex);
			return false;
		}
	}

	internal static bool TryStartConfiguredNewGameForAiDriver(out string json, out string failure)
	{
		json = null;
		failure = null;
		if (!TryStartConfiguredNewGame())
		{
			failure = "configured local match startup returned false";
			return false;
		}
		var plan = Plugin.LastResolvedOfflineLaunchPlan;
		if (plan == null)
		{
			json = "\"loaderInvoked\":true,\"planKnown\":false";
			return true;
		}
		json = "\"loaderInvoked\":true,\"planKnown\":true"
			+ ",\"templateName\":\"" + EscapeAiDriverJson(plan.TemplateName) + "\""
			+ ",\"matchMode\":\"" + EscapeAiDriverJson(plan.SecondSideIsHuman ? "Hotseat" : "SinglePlayer") + "\""
			+ ",\"playerFaction\":\"" + EscapeAiDriverJson(plan.PlayerFraction) + "\""
			+ ",\"playerHero\":\"" + EscapeAiDriverJson(plan.PlayerHero) + "\""
			+ ",\"opponentFaction\":\"" + EscapeAiDriverJson(plan.BotFraction) + "\""
			+ ",\"opponentHero\":\"" + EscapeAiDriverJson(plan.BotHero) + "\"";
		return true;
	}

	private static string EscapeAiDriverJson(string value)
	{
		if (string.IsNullOrEmpty(value))
		{
			return "";
		}
		return value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n").Replace("\t", "\\t");
	}

	private static bool TryStartConfiguredNewGame()
	{
		try
		{
			var plan = GetConfiguredNewGamePlan();
			if (plan == null)
			{
				return false;
			}

			var startInfo = new StartInfo
			{
				load = StartInfo.ELoad.Generate,
				fileHashSum = plan.TemplateHash,
				isQuickGame = !plan.SecondSideIsHuman,
				settings = CreateGameStartInfo(plan)
			};

			SetEnumProperty(startInfo, nameof(StartInfo.play), "Local", 0);

			var mySides = plan.SecondSideIsHuman ? new Il2CppStructArray<int>(2) : new Il2CppStructArray<int>(1);
			mySides[0] = 0;
			if (plan.SecondSideIsHuman)
			{
				mySides[1] = 1;
			}
			startInfo.mySides = mySides;

			var playerName = plan.SecondSideIsHuman ? "Player 1" : "Player";
			var sideTwoName = plan.SecondSideIsHuman ? "Player 2" : "Bot";
			var sideTwoType = plan.SecondSideIsHuman ? StartSide.EType.Player : StartSide.EType.Bot;
			var sides = new Il2CppReferenceArray<StartSide>(2);
			sides[0] = CreateSide(playerName, StartSide.EType.Player, plan.PlayerFraction, plan.PlayerHero, 0, 1);
			sides[1] = CreateSide(sideTwoName, sideTwoType, plan.BotFraction, plan.BotHero, 1, 2);
			startInfo.sides = sides;

			ScMainMenu.Hide();
			Plugin.LogSource?.LogInfo(
				$"Configured launch resolved to map='{plan.TemplateName}', mode='{(plan.SecondSideIsHuman ? "Hotseat" : "SinglePlayer")}', " +
				$"p1={plan.PlayerFraction}/{plan.PlayerHero}, p2={plan.BotFraction}/{plan.BotHero}, " +
				$"difficulty={plan.Difficulty.economy}/{plan.Difficulty.neutrals}/{plan.Difficulty.ai}, quickGame={startInfo.isQuickGame}.");
			Plugin.LastResolvedOfflineLaunchPlan = plan;
			if (!TryStartSessionLoader(startInfo))
			{
				Plugin.LogSource?.LogWarning("Configured launch: session loader start method did not run.");
				return false;
			}

			Plugin.LogSource?.LogInfo($"Started configured {(plan.SecondSideIsHuman ? "hotseat" : "single-player")} match on '{plan.TemplateName}'.");
			return true;
		}
		catch (Exception ex)
		{
			Warn("Failed to start configured new game", ex);
			return false;
		}
	}

	private static void ResetAutoLaunchGateIfMenuReturned(ScMainMenu menu)
	{
		if (!_autoLaunchTerminal || menu == null || menu.mainMenuNavigationView == null)
		{
			return;
		}

		try
		{
			if (menu.gameObject == null || !menu.gameObject.activeInHierarchy)
			{
				return;
			}

			if (Time.realtimeSinceStartup - _lastAutoLaunchStartRealtime < 3f)
			{
				return;
			}

			_autoLaunchTerminal = false;
			_autoLaunchMenuReadyRealtime = Time.realtimeSinceStartup;
			_loggedAutoLaunchPending = false;
			Plugin.LogSource?.LogInfo("Auto-launch: main menu returned; configured match launch gate reset for another map load.");
		}
		catch
		{
		}
	}

	private static OfflineQuickStartPlan GetOrCreateQuickStartPlan()
	{
		if (_cachedPlan != null)
		{
			return _cachedPlan;
		}

		var streamingAssets = LauncherConfigReader.GetStreamingAssetsDirectory();
		var coreZipPath = LauncherConfigReader.GetCoreZipPath();
		using var archive = ZipFile.OpenRead(coreZipPath);

		var quickStart = ParseQuickStartData(ReadZipText(archive, "DB/quickStart.json"));
		var data = ParseDataIncData(ReadZipText(archive, "DB/data.json"));
		if (quickStart?.difficulties == null || quickStart.difficulties.Length == 0)
		{
			throw new InvalidOperationException("quickStart.json did not expose any difficulties.");
		}

		var heroesByFraction = LoadHeroesByFraction(archive);
		var playerFraction = PickFraction(data?.availableFractions, heroesByFraction, null);
		var botFraction = PickFraction(data?.availableFractions, heroesByFraction, playerFraction);
		if (string.IsNullOrEmpty(playerFraction) || string.IsNullOrEmpty(botFraction))
		{
			throw new InvalidOperationException("Could not find valid playable fractions in shipped data.");
		}

		var playerHero = PickHero(heroesByFraction, playerFraction);
		var botHero = PickHero(heroesByFraction, botFraction);
		if (string.IsNullOrEmpty(playerHero) || string.IsNullOrEmpty(botHero))
		{
			throw new InvalidOperationException("Could not find valid hero ids for offline match.");
		}

		var templateName = PickTemplateName(quickStart.classicMaps, streamingAssets);
		var templatePath = Path.Combine(streamingAssets, "map_templates", templateName + ".rmg.json");
		var templateJson = File.ReadAllText(templatePath);
		var templateHash = ComputeTemplateHash(templateJson);

		_cachedPlan = new OfflineQuickStartPlan
		{
			TemplateName = templateName,
			TemplateHash = templateHash,
			PlayerFraction = playerFraction,
			PlayerHero = playerHero,
			BotFraction = botFraction,
			BotHero = botHero,
			Difficulty = quickStart.difficulties[0],
			Timers = quickStart.timersSettings ?? new TimerSettingsData()
		};

		return _cachedPlan;
	}

	private static OfflineQuickStartPlan GetConfiguredNewGamePlan()
	{
		var streamingAssets = LauncherConfigReader.GetStreamingAssetsDirectory();
		var coreZipPath = LauncherConfigReader.GetCoreZipPath();
		using var archive = ZipFile.OpenRead(coreZipPath);

		var quickStart = ParseQuickStartData(ReadZipText(archive, "DB/quickStart.json"));
		var data = ParseDataIncData(ReadZipText(archive, "DB/data.json"));
		var heroesByFraction = LoadHeroesByFraction(archive);
		if (quickStart?.difficulties == null || quickStart.difficulties.Length == 0)
		{
			throw new InvalidOperationException("quickStart.json did not expose any difficulties.");
		}

		var config = LauncherConfigReader.TryLoad();
		if (config == null)
		{
			return CreateDefaultSinglePlayerPlan(quickStart);
		}

		var isHotseat = string.Equals(config.MatchMode, "Hotseat", StringComparison.OrdinalIgnoreCase);
		var templateName = ResolveTemplateName(config.MapTemplate, streamingAssets, quickStart.classicMaps);
		var templatePath = Path.Combine(streamingAssets, "map_templates", templateName + ".rmg.json");
		var templateJson = File.ReadAllText(templatePath);
		var random = new System.Random(Environment.TickCount);
		var playerFraction = ResolveConfiguredOrRandomFraction(config.PlayerOneFaction, data?.availableFractions, heroesByFraction, random, null);
		var playerHero = ResolveConfiguredOrRandomHero(config.PlayerOneHero, playerFraction, heroesByFraction, random);
		var excludeSecondFraction = string.IsNullOrWhiteSpace(config.PlayerTwoFaction) || string.Equals(config.PlayerTwoFaction, "random", StringComparison.OrdinalIgnoreCase)
			? playerFraction
			: null;
		var secondFraction = ResolveConfiguredOrRandomFraction(config.PlayerTwoFaction, data?.availableFractions, heroesByFraction, random, excludeSecondFraction);
		var secondHero = ResolveConfiguredOrRandomHero(config.PlayerTwoHero, secondFraction, heroesByFraction, random);

		return new OfflineQuickStartPlan
		{
			TemplateName = templateName,
			TemplateHash = ComputeTemplateHash(templateJson),
			PlayerFraction = playerFraction,
			PlayerHero = playerHero,
			BotFraction = secondFraction,
			BotHero = secondHero,
			Difficulty = ResolveDifficulty(quickStart.difficulties, config.DifficultyIndex),
			Timers = quickStart.timersSettings ?? new TimerSettingsData(),
			TurnModeName = isHotseat ? "Hotseat" : null,
			TurnModeFallback = isHotseat ? 4 : 2,
			SecondSideIsHuman = isHotseat
		};
	}

	private static OfflineQuickStartPlan CreateDefaultSinglePlayerPlan(QuickStartData quickStart)
	{
		var streamingAssets = LauncherConfigReader.GetStreamingAssetsDirectory();
		using var archive = ZipFile.OpenRead(LauncherConfigReader.GetCoreZipPath());
		var data = ParseDataIncData(ReadZipText(archive, "DB/data.json"));
		var heroesByFraction = LoadHeroesByFraction(archive);
		var random = new System.Random(Environment.TickCount);
		var playerFraction = ResolveConfiguredOrRandomFraction("random", data?.availableFractions, heroesByFraction, random, null);
		var botFraction = ResolveConfiguredOrRandomFraction("random", data?.availableFractions, heroesByFraction, random, playerFraction);

		return new OfflineQuickStartPlan
		{
			TemplateName = "Jebus Outcast",
			TemplateHash = ComputeTemplateHash(File.ReadAllText(Path.Combine(streamingAssets, "map_templates", "Jebus Outcast.rmg.json"))),
			PlayerFraction = playerFraction,
			PlayerHero = ResolveConfiguredOrRandomHero("random", playerFraction, heroesByFraction, random),
			BotFraction = botFraction,
			BotHero = ResolveConfiguredOrRandomHero("random", botFraction, heroesByFraction, random),
			Difficulty = quickStart.difficulties[quickStart.difficulties.Length - 1],
			Timers = quickStart.timersSettings ?? new TimerSettingsData()
		};
	}

	private static Dictionary<string, List<string>> LoadHeroesByFraction(ZipArchive archive)
	{
		var result = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
		foreach (var entry in archive.Entries)
		{
			if (!entry.FullName.StartsWith("DB/heroes/", StringComparison.OrdinalIgnoreCase) ||
				!entry.FullName.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
			{
				continue;
			}

			var text = ReadZipText(entry);
			var ids = Regex.Matches(text, "\"id\"\\s*:\\s*\"([^\"]+)\"");
			var fractions = Regex.Matches(text, "\"fraction\"\\s*:\\s*\"([^\"]+)\"");
			var count = Math.Min(ids.Count, fractions.Count);
			for (var i = 0; i < count; i++)
			{
				var id = ids[i].Groups[1].Value;
				var fraction = fractions[i].Groups[1].Value;
				if (string.IsNullOrEmpty(id) || string.IsNullOrEmpty(fraction))
				{
					continue;
				}

				if (!result.TryGetValue(fraction, out var list))
				{
					list = new List<string>();
					result[fraction] = list;
				}

				list.Add(id);
			}
		}

		return result;
	}

	private static QuickStartData ParseQuickStartData(string json)
	{
		var difficultiesBlock = ReadArrayBlock(json, "difficulties");
		var difficultyMatches = Regex.Matches(
			difficultiesBlock,
			"\"economy\"\\s*:\\s*(\\d+).*?\"neutrals\"\\s*:\\s*(\\d+).*?\"ai\"\\s*:\\s*(\\d+)",
			RegexOptions.Singleline);
		var difficulties = new DifficultyData[difficultyMatches.Count];
		for (var i = 0; i < difficultyMatches.Count; i++)
		{
			var match = difficultyMatches[i];
			difficulties[i] = new DifficultyData
			{
				economy = ReadInt(match.Groups[1].Value, 0),
				neutrals = ReadInt(match.Groups[2].Value, 0),
				ai = ReadInt(match.Groups[3].Value, 0)
			};
		}

		return new QuickStartData
		{
			difficulties = difficulties,
			classicMaps = ReadStringArray(ReadArrayBlock(json, "classicMaps")),
			timersSettings = ParseTimerSettings(json)
		};
	}

	private static DataIncData ParseDataIncData(string json)
	{
		return new DataIncData
		{
			availableFractions = ReadStringArray(ReadArrayBlock(json, "availableFractions"))
		};
	}

	private static TimerSettingsData ParseTimerSettings(string json)
	{
		return new TimerSettingsData
		{
			basicTimersEnabled = ReadBool(ReadValue(json, "basicTimersEnabled"), false),
			startTimeSide = ReadInt(ReadValue(json, "startTimeSide"), 60),
			extraTimeDay = ReadInt(ReadValue(json, "extraTimeDay"), 60),
			incTimeDay = ReadInt(ReadValue(json, "incTimeDay"), 15),
			extraTimeWeek = ReadInt(ReadValue(json, "extraTimeWeek"), 60),
			incTimeWeek = ReadInt(ReadValue(json, "incTimeWeek"), 60),
			maxAccumulationTimes = ReadInt(ReadValue(json, "maxAccumulationTimes"), 600),
			battlePVETimerEnabled = ReadBool(ReadValue(json, "battlePVETimerEnabled"), false)
		};
	}

	private static string[] ReadStringArray(string arrayBlock)
	{
		if (string.IsNullOrEmpty(arrayBlock))
		{
			return Array.Empty<string>();
		}

		var matches = Regex.Matches(arrayBlock, "\"([^\"]+)\"");
		if (matches.Count == 0)
		{
			return Array.Empty<string>();
		}

		var values = new string[matches.Count];
		for (var i = 0; i < matches.Count; i++)
		{
			values[i] = matches[i].Groups[1].Value;
		}

		return values;
	}

	private static string ReadArrayBlock(string json, string key)
	{
		var match = Regex.Match(json, $"\"{Regex.Escape(key)}\"\\s*:\\s*\\[(.*?)\\]", RegexOptions.Singleline);
		return match.Success ? match.Groups[1].Value : string.Empty;
	}

	private static string ReadValue(string json, string key)
	{
		var match = Regex.Match(json, $"\"{Regex.Escape(key)}\"\\s*:\\s*([^,\\r\\n\\}}]+)", RegexOptions.Singleline);
		return match.Success ? match.Groups[1].Value.Trim() : string.Empty;
	}

	private static string ReadQuotedValue(string json, string key, string fallback)
	{
		var match = Regex.Match(json, $"\"{Regex.Escape(key)}\"\\s*:\\s*\"([^\"]+)\"", RegexOptions.Singleline);
		return match.Success ? match.Groups[1].Value : fallback;
	}

	private static int ReadInt(string text, int fallback)
	{
		return int.TryParse(text, out var value) ? value : fallback;
	}

	private static bool ReadBool(string text, bool fallback)
	{
		return bool.TryParse(text, out var value) ? value : fallback;
	}

	private static string PickFraction(string[] availableFractions, Dictionary<string, List<string>> heroesByFraction, string exclude)
	{
		if (availableFractions != null)
		{
			for (var i = 0; i < availableFractions.Length; i++)
			{
				var fraction = availableFractions[i];
				if (string.IsNullOrEmpty(fraction) || string.Equals(fraction, exclude, StringComparison.OrdinalIgnoreCase))
				{
					continue;
				}

				if (heroesByFraction.TryGetValue(fraction, out var heroes) && heroes.Count > 0)
				{
					return fraction;
				}
			}
		}

		foreach (var pair in heroesByFraction)
		{
			if (string.Equals(pair.Key, exclude, StringComparison.OrdinalIgnoreCase) || pair.Value.Count == 0)
			{
				continue;
			}

			return pair.Key;
		}

		return null;
	}

	private static string PickHero(Dictionary<string, List<string>> heroesByFraction, string fraction)
	{
		if (!heroesByFraction.TryGetValue(fraction, out var heroes) || heroes.Count == 0)
		{
			return null;
		}

		for (var i = 0; i < heroes.Count; i++)
		{
			var hero = heroes[i];
			if (!hero.StartsWith("tutorial_", StringComparison.OrdinalIgnoreCase) &&
				!hero.StartsWith("campaign_", StringComparison.OrdinalIgnoreCase))
			{
				return hero;
			}
		}

		return heroes[0];
	}

	private static DifficultyData ResolveDifficulty(DifficultyData[] difficulties, int configuredIndex)
	{
		if (difficulties == null || difficulties.Length == 0)
		{
			return new DifficultyData();
		}

		if (configuredIndex < 0)
		{
			configuredIndex = 0;
		}
		else if (configuredIndex >= difficulties.Length)
		{
			configuredIndex = difficulties.Length - 1;
		}

		return difficulties[configuredIndex];
	}

	private static string ResolveConfiguredOrRandomFraction(string configuredFraction, string[] availableFractions, Dictionary<string, List<string>> heroesByFraction, System.Random random, string exclude)
	{
		if (!string.IsNullOrWhiteSpace(configuredFraction) && !string.Equals(configuredFraction, "random", StringComparison.OrdinalIgnoreCase))
		{
			for (var i = 0; availableFractions != null && i < availableFractions.Length; i++)
			{
				if (!string.Equals(availableFractions[i], configuredFraction, StringComparison.OrdinalIgnoreCase))
				{
					continue;
				}

				if (heroesByFraction.TryGetValue(availableFractions[i], out var heroes) && heroes.Count > 0)
				{
					return availableFractions[i];
				}
			}

			foreach (var pair in heroesByFraction)
			{
				if (string.Equals(pair.Key, configuredFraction, StringComparison.OrdinalIgnoreCase) && pair.Value.Count > 0)
				{
					return pair.Key;
				}
			}
		}

		var candidates = new List<string>();
		if (availableFractions != null)
		{
			for (var i = 0; i < availableFractions.Length; i++)
			{
				var fraction = availableFractions[i];
				if (string.IsNullOrWhiteSpace(fraction) || string.Equals(fraction, exclude, StringComparison.OrdinalIgnoreCase))
				{
					continue;
				}

				if (heroesByFraction.TryGetValue(fraction, out var heroes) && heroes.Count > 0)
				{
					candidates.Add(fraction);
				}
			}
		}

		if (candidates.Count == 0)
		{
			foreach (var pair in heroesByFraction)
			{
				if (pair.Value.Count == 0 || string.Equals(pair.Key, exclude, StringComparison.OrdinalIgnoreCase))
				{
					continue;
				}

				candidates.Add(pair.Key);
			}
		}

		if (candidates.Count == 0)
		{
			throw new InvalidOperationException("Could not resolve a playable faction for the configured match.");
		}

		return candidates[random.Next(candidates.Count)];
	}

	private static string ResolveConfiguredOrRandomHero(string configuredHero, string resolvedFraction, Dictionary<string, List<string>> heroesByFraction, System.Random random)
	{
		if (!heroesByFraction.TryGetValue(resolvedFraction, out var heroes) || heroes.Count == 0)
		{
			throw new InvalidOperationException($"Could not resolve a hero pool for faction '{resolvedFraction}'.");
		}

		if (!string.IsNullOrWhiteSpace(configuredHero) && !string.Equals(configuredHero, "random", StringComparison.OrdinalIgnoreCase))
		{
			for (var i = 0; i < heroes.Count; i++)
			{
				if (string.Equals(heroes[i], configuredHero, StringComparison.OrdinalIgnoreCase))
				{
					return heroes[i];
				}
			}
		}

		return heroes[random.Next(heroes.Count)];
	}

	private static string ResolveTemplateName(string configuredTemplate, string streamingAssetsPath, string[] configuredClassicMaps)
	{
		var templateDirectory = Path.Combine(streamingAssetsPath, "map_templates");
		if (!string.IsNullOrWhiteSpace(configuredTemplate) &&
			File.Exists(Path.Combine(templateDirectory, configuredTemplate + ".rmg.json")))
		{
			return configuredTemplate;
		}

		if (File.Exists(Path.Combine(templateDirectory, "Jebus Outcast.rmg.json")))
		{
			return "Jebus Outcast";
		}

		return PickTemplateName(configuredClassicMaps, streamingAssetsPath);
	}


	private static string PickTemplateName(string[] configuredClassicMaps, string streamingAssetsPath)
	{
		var templateDirectory = Path.Combine(streamingAssetsPath, "map_templates");
		if (File.Exists(Path.Combine(templateDirectory, "Arcade.rmg.json")))
		{
			return "Arcade";
		}

		if (configuredClassicMaps != null)
		{
			for (var i = 0; i < configuredClassicMaps.Length; i++)
			{
				var candidate = configuredClassicMaps[i];
				if (File.Exists(Path.Combine(templateDirectory, candidate + ".rmg.json")))
				{
					return candidate;
				}
			}
		}

		throw new FileNotFoundException("No shipped classic quick-start template was found.");
	}

	private static string ComputeTemplateHash(string templateJson)
	{
		var hash = default(Hash128);
		hash.Append(templateJson);
		return hash.ToString();
	}

	private static GameStartInfo CreateGameStartInfo(OfflineQuickStartPlan plan)
	{
		var settings = new GameStartInfo
		{
			RandomSeed = Environment.TickCount,
			MapSpeed = 1,
			BattleSpeed = 1,
			EconomicDifficulty = plan.Difficulty.economy,
			NeutralsDifficulty = plan.Difficulty.neutrals,
			AiDifficulty = plan.Difficulty.ai,
			RestartPoints = 2,
			RealtimeTurnsEndOnDay = false,
			RealtimeEndDay = 1,
			WeekEffectEnabled = true,
			OnlyAdminCanSave = false,
			SideTimerSettings = CreateSideTimerSettings(plan.Timers),
			EndRealtimeWeek = -1,
			EndRealtimeDay = -1,
			IsMatchMakingGame = false,
			DefeatAllEnemiesEnabled = true,
			CanManualManageTurnMode = true,
			ShowMapAfterGame = false,
			RestartPenalty = false
		};

		SetEnumProperty(settings, nameof(GameStartInfo.TurnMode), plan.TurnModeName ?? "Realtime", plan.TurnModeFallback);
		return settings;
	}

	private static Il2CppReferenceArray<StartSide> CreateHomecomingPlayableShellSides()
	{
		var sides = new Il2CppReferenceArray<StartSide>(3);
		sides[0] = CreateSide("Player", StartSide.EType.Player, "dungeon", "dungeon_hero_6", 0, 1);
		sides[1] = CreateSide("Bot 1", StartSide.EType.Bot, "demon", "demon_hero_2", 1, 2);
		sides[2] = CreateSide("Bot 2", StartSide.EType.Bot, "nature", "nature_hero_11", 2, 3);
		return sides;
	}

	private static GameStartInfo CreateHomecomingPlayableShellStartSettings()
	{
		var settings = new GameStartInfo
		{
			RandomSeed = Environment.TickCount,
			MapSpeed = 0,
			BattleSpeed = 0,
			EconomicDifficulty = 0,
			NeutralsDifficulty = 0,
			AiDifficulty = 1,
			RestartPoints = 0,
			RealtimeTurnsEndOnDay = false,
			RealtimeEndDay = 0,
			WeekEffectEnabled = false,
			OnlyAdminCanSave = false,
			SideTimerSettings = CreateHomecomingPlayableShellSideTimerSettings(),
			EndRealtimeWeek = -1,
			EndRealtimeDay = -1,
			IsMatchMakingGame = false,
			DefeatAllEnemiesEnabled = true,
			CanManualManageTurnMode = false,
			ShowMapAfterGame = false,
			RestartPenalty = true
		};
		SetEnumProperty(settings, nameof(GameStartInfo.TurnMode), "Hotseat", 4);
		return settings;
	}

	private static SideTimerSettings CreateHomecomingPlayableShellSideTimerSettings()
	{
		return new SideTimerSettings
		{
			BasicTimersEnabled = false,
			StartTimeSide = 60,
			ExtraTimeDay = 60,
			IncTimeDay = 15,
			ExtraTimeWeek = 60,
			IncTimeWeek = 60,
			MaxAccumulationTimes = 600,
			BattlePveTimerEnabled = false,
			StartPveTime = 30,
			MinTimeAfterFight = 10,
			ExtraTimeAfterFight = 10,
			MinExtraTimeInFight = 10,
			BattlePvpTimersEnabled = false,
			StartTimePvP = 60,
			ExtraTimePvP = 30,
			ArenaPvpTimersEnabled = false,
			ArenaStartPvpTime = 60,
			ArenaExtraPvpTime = 30,
			ArenaPreparationTimerEnabled = false,
			ArenaPreparationTime = 30000
		};
	}

	private static CampaignInfo CreateHomecomingPlayableShellCampaignInfo()
	{
		return new CampaignInfo();
	}

	private static SideTimerSettings CreateSideTimerSettings(TimerSettingsData source)
	{
		return new SideTimerSettings
		{
			BasicTimersEnabled = source.basicTimersEnabled,
			StartTimeSide = source.startTimeSide,
			ExtraTimeDay = source.extraTimeDay,
			IncTimeDay = source.incTimeDay,
			ExtraTimeWeek = source.extraTimeWeek,
			IncTimeWeek = source.incTimeWeek,
			MaxAccumulationTimes = source.maxAccumulationTimes,
			BattlePveTimerEnabled = source.battlePVETimerEnabled,
			StartPveTime = 30,
			MinTimeAfterFight = 5,
			ExtraTimeAfterFight = 5,
			MinExtraTimeInFight = 5,
			BattlePvpTimersEnabled = false,
			StartTimePvP = 60,
			ExtraTimePvP = 30,
			ArenaPvpTimersEnabled = false,
			ArenaStartPvpTime = 60,
			ArenaExtraPvpTime = 30,
			ArenaPreparationTimerEnabled = false,
			ArenaPreparationTime = 30000
		};
	}

	private static StartSide CreateSide(string name, StartSide.EType sideType, string fractionSid, string heroSid, int colorId, int spawnId)
	{
		var isFractionRandom = string.Equals(fractionSid, "random", StringComparison.OrdinalIgnoreCase);
		var isHeroRandom = string.Equals(heroSid, "random", StringComparison.OrdinalIgnoreCase);

		return new StartSide
		{
			name = name,
			eType = sideType,
			fractionSid = fractionSid,
			isFractionRandom = isFractionRandom,
			heroSid = heroSid,
			isHeroRandom = isHeroRandom,
			colorId = colorId,
			spawnId = spawnId,
			restartPoints = 2,
			startTimerPenalty = 0
		};
	}

	private static void SetEnumProperty(object target, string propertyName, string preferredName, int fallbackValue)
	{
		var property = target.GetType().GetProperty(propertyName);
		if (property == null)
		{
			throw new MissingMemberException(target.GetType().FullName, propertyName);
		}

		var enumType = property.PropertyType;
		object enumValue;
		if (!string.IsNullOrEmpty(preferredName))
		{
			try
			{
				enumValue = Enum.Parse(enumType, preferredName, ignoreCase: true);
			}
			catch
			{
				enumValue = Enum.ToObject(enumType, fallbackValue);
			}
		}
		else
		{
			enumValue = Enum.ToObject(enumType, fallbackValue);
		}

		property.SetValue(target, enumValue);
	}

	private static string ReadZipText(ZipArchive archive, string entryPath)
	{
		var entry = archive.GetEntry(entryPath);
		if (entry == null)
		{
			throw new FileNotFoundException($"Missing '{entryPath}' in Core.zip.");
		}

		return ReadZipText(entry);
	}

	private static string ReadZipText(ZipArchiveEntry entry)
	{
		using var stream = entry.Open();
		using var reader = new StreamReader(stream);
		return reader.ReadToEnd();
	}

	private static void ForceButtonEnabled(BhNavigationButton button)
	{
		if (button == null)
		{
			return;
		}

		button.enabled = true;
		TrySetNavigationButtonAvailable(button, true);
		ForceVisible(button.gameObject);
		HideObject(button.unavailableGroup);

		var selectable = button.GetComponent<Selectable>();
		if (selectable != null)
		{
			selectable.interactable = true;
		}

		if (button.label != null)
		{
			button.label.color = button.availableColor;
		}
	}

	private static void ForceVisible(GameObject gameObject)
	{
		if (gameObject == null)
		{
			return;
		}

		var current = gameObject.transform;
		while (current != null)
		{
			var currentObject = current.gameObject;
			if (currentObject != null && !currentObject.activeSelf)
			{
				currentObject.SetActive(true);
			}

			var canvasGroups = currentObject.GetComponents<CanvasGroup>();
			if (canvasGroups != null)
			{
				foreach (var canvasGroup in canvasGroups)
				{
					HideCanvasGroup(canvasGroup, hide: false);
				}
			}

			current = current.parent;
		}
	}

	private static void HideObject(Component component)
	{
		if (component == null)
		{
			return;
		}

		HideObject(component.gameObject);
	}

	private static void HideObject(GameObject gameObject)
	{
		if (gameObject == null)
		{
			return;
		}

		if (gameObject.activeSelf)
		{
			gameObject.SetActive(false);
		}
	}

	private static void HideCanvasGroup(CanvasGroup canvasGroup, bool hide = true)
	{
		if (canvasGroup == null)
		{
			return;
		}

		canvasGroup.alpha = hide ? 0f : 1f;
		canvasGroup.interactable = !hide;
		canvasGroup.blocksRaycasts = !hide;
	}

	private static bool SameButton(BhNavigationButton left, BhNavigationButton right)
	{
		if (left == null || right == null)
		{
			return false;
		}

		return left.Pointer == right.Pointer;
	}

}

internal sealed class OfflineQuickStartPlan
{
	public string TemplateName;
	public string TemplateHash;
	public string PlayerFraction;
	public string PlayerHero;
	public string BotFraction;
	public string BotHero;
	public DifficultyData Difficulty;
	public TimerSettingsData Timers;
	public string TurnModeName;
	public int TurnModeFallback = 2;
	public bool SecondSideIsHuman;
}

internal sealed class QuickStartData
{
	public TimerSettingsData timersSettings { get; set; }
	public DifficultyData[] difficulties { get; set; }
	public string[] classicMaps { get; set; }
}

internal sealed class DifficultyData
{
	public int economy { get; set; }
	public int neutrals { get; set; }
	public int ai { get; set; }
}

internal sealed class TimerSettingsData
{
	public bool basicTimersEnabled { get; set; }
	public int startTimeSide { get; set; } = 60;
	public int extraTimeDay { get; set; } = 60;
	public int incTimeDay { get; set; } = 15;
	public int extraTimeWeek { get; set; } = 60;
	public int incTimeWeek { get; set; } = 60;
	public int maxAccumulationTimes { get; set; } = 600;
	public bool battlePVETimerEnabled { get; set; }
}

internal sealed class DataIncData
{
	public string[] availableFractions { get; set; }
}

internal sealed class FontScaleSnapshot
{
	public float FontSize { get; set; }
	public float FontSizeMin { get; set; }
	public float FontSizeMax { get; set; }
	public bool AutoSize { get; set; }
}

public sealed class HomecomingPlayableShellSceneObserver : MonoBehaviour
{
	private const float SampleDurationSeconds = 90f;
	private const float SampleIntervalSeconds = 3f;
	private const int MaxIdentitySources = 4;
	private float _started;
	private float _lastLog;
	private int _logged;
	private bool _proofLogged;

	private void Awake()
	{
		_started = Time.realtimeSinceStartup;
		_lastLog = -1000f;
	}

	private void Update()
	{
		var now = Time.realtimeSinceStartup;
		if (now - _started > SampleDurationSeconds)
		{
			Plugin.LogSource?.LogInfo(
				"HOMM3_HOMECOMING_PLAYABLE_SHELL_LAUNCH scene_observer_complete samples="
				+ _logged
				+ " seconds="
				+ SampleDurationSeconds
				+ " proofLogged="
				+ _proofLogged);
			Destroy(gameObject);
			return;
		}

		if (now - _lastLog < SampleIntervalSeconds)
		{
			return;
		}

		_lastLog = now;
		_logged++;
		var activeScene = SceneManager.GetActiveScene();
		var scenes = new StringBuilder();
		var worldLightLoaded = false;
		var sessionHudLoaded = false;
		for (var i = 0; i < SceneManager.sceneCount; i++)
		{
			var scene = SceneManager.GetSceneAt(i);
			if (!scene.IsValid())
			{
				continue;
			}
			if (scenes.Length > 0)
			{
				scenes.Append(',');
			}
			scenes.Append(scene.name).Append(':').Append(scene.isLoaded ? "loaded" : "notLoaded");
			if (string.Equals(scene.name, "worldLight", StringComparison.Ordinal) && scene.isLoaded)
			{
				worldLightLoaded = true;
			}
			if (string.Equals(scene.name, "sessionHUD", StringComparison.Ordinal) && scene.isLoaded)
			{
				sessionHudLoaded = true;
			}
		}

		var mapCameraActive = CountActiveObjectsNamed<Camera>("Map Camera", "worldLight");
		var hudCanvasActive = CountActiveGameObjectsNamed("CanvasTech" + "HUDPanel", "sessionHUD");
		var minimapCanvasActive = CountActiveGameObjectsNamed("CanvasSide" + "MiniMapPanels", "sessionHUD");
		var worldLightActiveRenderers = CountActiveRenderersInScene("worldLight");
		var sessionIdentity = ReadSessionIdentityEvidence();
		var observedMapHash = ModActions.HomecomingPlayableShellLastResolvedHash;
		var routeHashSeen = !string.IsNullOrEmpty(observedMapHash) && sessionIdentity.IndexOf(observedMapHash, StringComparison.OrdinalIgnoreCase) >= 0;
		var homecomingNameSeen = sessionIdentity.IndexOf(ModActions.HomecomingPlayableShellMapSid, StringComparison.OrdinalIgnoreCase) >= 0;
		var visibleSessionReady = worldLightLoaded
			&& sessionHudLoaded
			&& mapCameraActive > 0
			&& hudCanvasActive > 0
			&& minimapCanvasActive > 0
			&& worldLightActiveRenderers > 0;
		if (!_proofLogged && visibleSessionReady && (routeHashSeen || homecomingNameSeen))
		{
			_proofLogged = true;
			Plugin.LogSource?.LogWarning(
				"HOMM3_HOMECOMING_PLAYABLE_SHELL_LAUNCH runtime_observation result=PARTIAL_UI_ONLY mapSid="
				+ ModActions.HomecomingPlayableShellMapSid
				+ " mapHash="
				+ ModActions.HomecomingPlayableShellLastResolvedHash
				+ " blocker=synthetic_StartInfo_missing_native_scenario_launch_context"
				+ " identity="
				+ sessionIdentity);
		}

		Plugin.LogSource?.LogInfo(
			"HOMM3_HOMECOMING_PLAYABLE_SHELL_LAUNCH scene_observer sample="
			+ _logged
			+ " activeScene="
			+ (activeScene.IsValid() ? activeScene.name : "invalid")
			+ " sceneCount="
			+ SceneManager.sceneCount
			+ " scenes="
			+ scenes
			+ " mapCameraActive="
			+ mapCameraActive
			+ " hudCanvasActive="
			+ hudCanvasActive
			+ " minimapCanvasActive="
			+ minimapCanvasActive
			+ " worldLightActiveRenderers="
			+ worldLightActiveRenderers
			+ " visibleSessionReady="
			+ visibleSessionReady
			+ " routeHashSeen="
			+ routeHashSeen
			+ " homecomingNameSeen="
			+ homecomingNameSeen
			+ " identity="
			+ sessionIdentity);
	}

	private static int CountActiveObjectsNamed<T>(string objectName, string sceneName) where T : Component
	{
		var count = 0;
		foreach (var component in Resources.FindObjectsOfTypeAll<T>())
		{
			if (component == null || component.gameObject == null)
			{
				continue;
			}
			if (!string.Equals(component.gameObject.name, objectName, StringComparison.Ordinal))
			{
				continue;
			}
			if (!string.Equals(component.gameObject.scene.name, sceneName, StringComparison.Ordinal))
			{
				continue;
			}
			if (component.gameObject.activeInHierarchy)
			{
				count++;
			}
		}
		return count;
	}

	private static int CountActiveGameObjectsNamed(string objectName, string sceneName)
	{
		var count = 0;
		foreach (var go in Resources.FindObjectsOfTypeAll<GameObject>())
		{
			if (go == null)
			{
				continue;
			}
			if (!string.Equals(go.name, objectName, StringComparison.Ordinal))
			{
				continue;
			}
			if (!string.Equals(go.scene.name, sceneName, StringComparison.Ordinal))
			{
				continue;
			}
			if (go.activeInHierarchy)
			{
				count++;
			}
		}
		return count;
	}

	private static int CountActiveRenderersInScene(string sceneName)
	{
		var count = 0;
		foreach (var renderer in Resources.FindObjectsOfTypeAll<Renderer>())
		{
			if (renderer == null || renderer.gameObject == null)
			{
				continue;
			}
			if (!renderer.enabled || !renderer.gameObject.activeInHierarchy)
			{
				continue;
			}
			if (string.Equals(renderer.gameObject.scene.name, sceneName, StringComparison.Ordinal))
			{
				count++;
			}
		}
		return count;
	}

	private static string ReadSessionIdentityEvidence()
	{
		var evidence = new StringBuilder();
		AppendStaticRootIdentity(evidence, "Hex.Session.Hud.BhHUDSession", "me");
		AppendStaticRootIdentity(evidence, "Hex.Session.BhSession", "me");
		AppendStaticRootIdentity(evidence, "Hex.Session.BhSession", "current");
		AppendActiveBehaviourIdentity(evidence);
		return evidence.Length == 0 ? "not_found" : evidence.ToString();
	}

	private static void AppendStaticRootIdentity(StringBuilder evidence, string typeName, string staticName)
	{
		if (CountIdentitySources(evidence) >= MaxIdentitySources)
		{
			return;
		}
		var type = ModActions.GetHexType(typeName);
		if (type == null || !TryReadMember(null, type, staticName, out var root) || root == null)
		{
			return;
		}
		AppendObjectIdentity(evidence, typeName + "." + staticName, root, 0);
	}

	private static void AppendActiveBehaviourIdentity(StringBuilder evidence)
	{
		foreach (var behaviour in Resources.FindObjectsOfTypeAll<MonoBehaviour>())
		{
			if (CountIdentitySources(evidence) >= MaxIdentitySources)
			{
				return;
			}
			if (behaviour == null || behaviour.gameObject == null || !behaviour.gameObject.activeInHierarchy)
			{
				continue;
			}
			var type = behaviour.GetType();
			var fullName = type.FullName ?? type.Name;
			if (fullName.IndexOf("Session", StringComparison.OrdinalIgnoreCase) < 0
				&& fullName.IndexOf("Loader", StringComparison.OrdinalIgnoreCase) < 0)
			{
				continue;
			}
			AppendObjectIdentity(evidence, fullName, behaviour, 0);
		}
	}

	private static void AppendObjectIdentity(StringBuilder evidence, string label, object root, int depth)
	{
		if (root == null || depth > 2 || CountIdentitySources(evidence) >= MaxIdentitySources)
		{
			return;
		}
		var type = root.GetType();
		foreach (var memberName in new[] { "startInfo", "restartInfo" })
		{
			if (TryReadMember(root, type, memberName, out var startInfo) && startInfo != null)
			{
				AppendIdentitySource(evidence, label + "." + memberName, startInfo);
			}
		}
		foreach (var memberName in new[] { "map", "data", "sessionData", "state", "logic", "world" })
		{
			if (TryReadMember(root, type, memberName, out var nested) && nested != null && !(nested is string))
			{
				AppendMapDataSource(evidence, label + "." + memberName, nested);
				AppendObjectIdentity(evidence, label + "." + memberName, nested, depth + 1);
			}
		}
	}

	private static void AppendIdentitySource(StringBuilder evidence, string label, object startInfo)
	{
		if (CountIdentitySources(evidence) >= MaxIdentitySources)
		{
			return;
		}
		var type = startInfo.GetType();
		TryReadMember(startInfo, type, "load", out var load);
		TryReadMember(startInfo, type, "fileHashSum", out var hash);
		TryReadMember(startInfo, type, "isQuickGame", out var quick);
		AppendDelimited(evidence, label + "{load=" + ValueOrNull(load) + ",fileHashSum=" + ValueOrNull(hash) + ",isQuickGame=" + ValueOrNull(quick) + "}");
	}

	private static void AppendMapDataSource(StringBuilder evidence, string label, object mapOrData)
	{
		if (CountIdentitySources(evidence) >= MaxIdentitySources)
		{
			return;
		}
		var type = mapOrData.GetType();
		var data = mapOrData;
		if (!TryReadMember(data, type, "fileMapName", out _) && TryReadMember(mapOrData, type, GameSymbols.HomecomingPlayableShell.MapDataNestedData.FieldName, out var nestedData) && nestedData != null)
		{
			data = nestedData;
			type = data.GetType();
		}
		if (!TryReadMember(data, type, "fileMapName", out var fileMapName)
			&& !TryReadMember(data, type, "mapName", out _)
			&& !TryReadMember(data, type, "mapDesc", out _))
		{
			return;
		}
		TryReadMember(data, type, "mapName", out var mapName);
		TryReadMember(data, type, "mapDesc", out var mapDesc);
		AppendDelimited(evidence, label + "{fileMapName=" + ValueOrNull(fileMapName) + ",mapName=" + ValueOrNull(mapName) + ",mapDesc=" + ValueOrNull(mapDesc) + "}");
	}

	private static bool TryReadMember(object instance, Type type, string name, out object value)
	{
		value = null;
		if (type == null || string.IsNullOrEmpty(name))
		{
			return false;
		}
		var flags = BindingFlags.Public | BindingFlags.NonPublic | (instance == null ? BindingFlags.Static : BindingFlags.Instance);
		for (var current = type; current != null; current = current.BaseType)
		{
			var property = current.GetProperty(name, flags | BindingFlags.DeclaredOnly)
				?? current.GetProperties(flags | BindingFlags.DeclaredOnly).FirstOrDefault(p => string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase));
			if (property != null && property.GetIndexParameters().Length == 0)
			{
				try
				{
					value = property.GetValue(instance);
					return true;
				}
				catch
				{
				}
			}
			var field = current.GetField(name, flags | BindingFlags.DeclaredOnly)
				?? current.GetFields(flags | BindingFlags.DeclaredOnly).FirstOrDefault(f => string.Equals(f.Name, name, StringComparison.OrdinalIgnoreCase));
			if (field != null)
			{
				try
				{
					value = field.GetValue(instance);
					return true;
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static void AppendDelimited(StringBuilder evidence, string value)
	{
		if (evidence.Length > 0)
		{
			evidence.Append(" || ");
		}
		evidence.Append(value);
	}

	private static int CountIdentitySources(StringBuilder evidence)
	{
		if (evidence.Length == 0)
		{
			return 0;
		}
		var count = 1;
		for (var i = 0; i < evidence.Length - 3; i++)
		{
			if (evidence[i] == ' ' && evidence[i + 1] == '|' && evidence[i + 2] == '|' && evidence[i + 3] == ' ')
			{
				count++;
			}
		}
		return count;
	}

	private static string ValueOrNull(object value)
	{
		return value == null ? "null" : Convert.ToString(value, CultureInfo.InvariantCulture);
	}
}
internal sealed class CanvasScaleSnapshot
{
	public CanvasScaler.ScaleMode UiScaleMode { get; set; }
	public float ScaleFactor { get; set; }
	public Vector2 ReferenceResolution { get; set; }
	public float ReferencePixelsPerUnit { get; set; }
	public float DynamicPixelsPerUnit { get; set; }
}

[HarmonyPatch(typeof(ScMainMenu), nameof(ScMainMenu.Start))]
internal static class ScMainMenuStartPatch
{
	private static void Postfix(ScMainMenu __instance)
	{
		var cfg = LauncherConfigReader.TryLoad();
		if (cfg != null && cfg.LegacyOfflineUnlockPatches)
		{
			ModActions.KeepMenuUnlocked(__instance);
		}
		if (cfg != null && cfg.Homm3ImportEnabled)
		{
			Homm3RuntimeManifestPreloader.PrewarmAtMainMenuOrFail(Plugin.LogSource);
		}
	}
}

[HarmonyPatch(typeof(ScMainMenu), nameof(ScMainMenu.Update))]
internal static class ScMainMenuUpdatePatch
{
	private static void Postfix(ScMainMenu __instance)
	{
		var cfg = LauncherConfigReader.TryLoad();
		if (cfg != null && cfg.LegacyOfflineUnlockPatches)
		{
			ModActions.KeepMenuUnlocked(__instance);
		}
		ModBugReportMenuBanner.MarkMainMenuFrame(__instance);
		GoldenEraGameplayOptions.ApplyIfNeeded();
		GoldenEraGameplayOptionsMenu.MarkMainMenuFrame(__instance);
		ModActions.MaybeAutoLaunchConfiguredMatch(__instance);
	}
}

[HarmonyPatch(typeof(MainMenuNavigationView), nameof(MainMenuNavigationView.Start))]
internal static class MainMenuNavigationViewStartPatch
{
	private static void Postfix(MainMenuNavigationView __instance)
	{
		ModActions.KeepMenuUnlocked(__instance);
	}
}

[HarmonyPatch(typeof(ScEarlyAccess), nameof(ScEarlyAccess.Open))]
internal static class ScEarlyAccessOpenPatch
{
	private static bool Prefix(ref Il2CppSystem.Threading.Tasks.Task<bool> __result)
	{
		ModActions.LogEarlyAccessSkip();
		var tcs = new Il2CppSystem.Threading.Tasks.TaskCompletionSource<bool>();
		tcs.SetResult(true);
		__result = tcs.Task;
		return false;
	}
}

[HarmonyPatch(typeof(ScDemoThankYou), nameof(ScDemoThankYou.Open))]
internal static class ScDemoThankYouOpenPatch
{
	private static bool Prefix(ref Hex.UI.BhScreen __result)
	{
		ModActions.LogDemoThankYouSkip();
		__result = null;
		return false;
	}
}

[HarmonyPatch(typeof(BhDemoIconTxtUI), nameof(BhDemoIconTxtUI.Start))]
internal static class BhDemoIconTxtUIStartPatch
{
	private static void Postfix(BhDemoIconTxtUI __instance)
	{
		ModActions.HideOverlay(__instance);
	}
}

// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(BhDemoIconTxtUI), nameof(BhDemoIconTxtUI.ypb))]
internal static class BhDemoIconTxtUIShowPatch
{
	private static void Postfix(BhDemoIconTxtUI __instance)
	{
		ModActions.HideOverlay(__instance);
	}
}

// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(BhDemoIconTxtUI), nameof(BhDemoIconTxtUI.ypc))]
internal static class BhDemoIconTxtUIShowAnimPatch
{
	private static void Postfix(BhDemoIconTxtUI __instance)
	{
		ModActions.HideOverlay(__instance);
	}
}

[HarmonyPatch(typeof(BhNavigationButton), nameof(BhNavigationButton.OnPointerClick))]
internal static class BhNavigationButtonClickPatch
{
	private static bool Prefix(BhNavigationButton __instance, PointerEventData _eventData)
	{
		return !ModActions.TryHandleMenuButtonClick(__instance);
	}
}

[HarmonyPatch(typeof(BhFont), nameof(BhFont.Start))]
internal static class BhFontStartPatch
{
	private static void Postfix(BhFont __instance)
	{
		ModActions.ApplyConfiguredUiScale(__instance);
	}
}

[HarmonyPatch(typeof(BhFont), nameof(BhFont.OnEnable))]
internal static class BhFontOnEnablePatch
{
	private static void Postfix(BhFont __instance)
	{
		ModActions.ApplyConfiguredUiScale(__instance);
		ModActions.ApplyCustomCityBackdrop();
	}
}

[HarmonyPatch(typeof(BhFont), nameof(BhFont.Init))]
internal static class BhFontInitPatch
{
	private static void Postfix(BhFont __instance)
	{
		ModActions.ApplyConfiguredUiScale(__instance);
	}
}

[HarmonyPatch(typeof(CanvasScaler), nameof(CanvasScaler.OnEnable))]
internal static class CanvasScalerOnEnablePatch
{
	private static void Postfix(CanvasScaler __instance)
	{
		ModActions.ApplyConfiguredUiScale(__instance);
		ModActions.ApplyCustomCityBackdrop();
	}
}

[HarmonyPatch]
internal static class SoFractionsCustomFactionAliasPatch
{
	private static readonly HashSet<string> Logged = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<string, FractionLobbyAsset> AssetCloneByFactionAndBase = new Dictionary<string, FractionLobbyAsset>(StringComparer.Ordinal);

	private static MethodBase TargetMethod()
	{
		var t = ModActions.GetHexType("Hex.GameHub.UICommon.SoFractions");
		if (t == null)
		{
			return null;
		}

		foreach (var method in t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			var parameters = method.GetParameters();
			if (parameters.Length == 1
				&& IsStringType(parameters[0].ParameterType)
				&& IsFractionLobbyAssetType(method.ReturnType))
			{
				return method;
			}
		}

		return t.GetMethod("pvr", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			?? t.GetMethod("pvs", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
			?? t.GetMethod("pqu", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
	}

	private static bool IsStringType(Type type)
	{
		return type == typeof(string) || string.Equals(type?.FullName, "System.String", StringComparison.Ordinal);
	}

	private static bool IsFractionLobbyAssetType(Type type)
	{
		return type == typeof(FractionLobbyAsset)
			|| string.Equals(type?.FullName, "Hex.GameHub.UICommon.FractionLobbyAsset", StringComparison.Ordinal)
			|| string.Equals(type?.Name, "FractionLobbyAsset", StringComparison.Ordinal);
	}

	private static void Prefix(ref string a, out string __state)
	{
		__state = a;
		if (!IsCustomFactionUsingDungeonUi(a))
		{
			return;
		}

		var original = a;
		a = "dungeon";
		if (Logged.Add(original))
		{
			Plugin.LogSource?.LogInfo($"SoFractions: aliasing UI asset lookup '{original}' -> 'dungeon'.");
		}
	}

	private static void Postfix(string __state, ref FractionLobbyAsset __result)
	{
		if (!IsCustomFactionUsingDungeonUi(__state) || __result == null)
		{
			return;
		}

		var clone = GetOrCreateCustomFactionClone(__state, __result);
		if (clone != null)
		{
			__result = clone;
		}
	}

	private static FractionLobbyAsset GetOrCreateCustomFactionClone(string factionSid, FractionLobbyAsset dungeonAsset)
	{
		try
		{
			var key = factionSid + ":" + Homm3DirectStateIdentity.ResolveKeyOrZero(dungeonAsset).ToString(CultureInfo.InvariantCulture);
			if (AssetCloneByFactionAndBase.TryGetValue(key, out var existing) && existing != null)
			{
				// Unity == is false for a freed sprite. The banner sprites are pinned with
				// DontUnloadUnusedAsset, so a freed one here is a fault: say so and rebuild the clone
				// instead of handing the HUD a dead factionPic sprite.
				if (existing.icon && existing.bigIcon)
				{
					return existing;
				}
				Plugin.LogSource?.LogWarning("SoFractions: cached UI asset clone for " + factionSid + " holds a freed icon sprite; rebuilding it.");
				AssetCloneByFactionAndBase.Remove(key);
			}

			var clone = new FractionLobbyAsset
			{
				icon = dungeonAsset.icon,
				slotFon = dungeonAsset.slotFon,
				statisticFon = dungeonAsset.statisticFon,
				versusFon = dungeonAsset.versusFon,
				bigIcon = dungeonAsset.bigIcon
			};
			DeobfInteropCompat.SetFractionLobbyAssetSid(clone, factionSid);
			var donorCard = DeobfInteropCompat.GetFractionLobbyAssetCard(dungeonAsset);
			if (donorCard)
				DeobfInteropCompat.SetFractionLobbyAssetCard(clone, donorCard);

			if (Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateSpriteForFaction(factionSid, out var banner) && banner)
			{
				clone.icon = banner;
				clone.bigIcon = banner;
			}
			if (Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateCardSpriteForFaction(factionSid, out var card) && card)
			{
				DeobfInteropCompat.SetFractionLobbyAssetCard(clone, card);
				clone.slotFon = card;
				clone.statisticFon = card;
				clone.versusFon = card;
			}

			AssetCloneByFactionAndBase[key] = clone;
			return clone;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("SoFractions: failed to clone custom faction UI asset for " + factionSid + ": " + ex.Message);
			return null;
		}
	}

	private static bool IsCustomFactionUsingDungeonUi(string sid)
	{
		return Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(sid)
			|| string.Equals(sid, "dungeon_raw", StringComparison.OrdinalIgnoreCase);
	}
}

[HarmonyPatch]
internal static class BhHUDSessionShowProbePatch
{
	private static MethodBase TargetMethod()
	{
		var t = ModActions.GetHexType("Hex.Session.Hud.BhHUDSession");
		return t == null ? null : AccessTools.Method(t, "ghj");
	}

	private static void Postfix()
	{
		SessionStateProbe.TryDump("BhHUDSession.ghj");
	}
}

// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(Hex.Session.Loader), nameof(Hex.Session.Loader.vdk))]
internal static class LoaderUttProbePatch
{
	private static void Prefix(object a)
	{
		SessionStateProbe.LogStartInfo(a);
		SessionStateProbe.TryDump("Loader.vdk.prefix");
	}

	private static void Postfix()
	{
		SessionStateProbe.TryDump("Loader.vdk.postfix");
	}
}

[HarmonyPatch]
internal static class LoaderLlaProbePatch
{
	private static MethodBase TargetMethod()
	{
		var t = ModActions.GetHexType("Hex.Session.Loader");
		return t == null ? null : AccessTools.Method(t, "lla");
	}

	private static void Prefix()
	{
		SessionStateProbe.TryDump("Loader.lla.prefix");
	}

	private static void Postfix()
	{
		SessionStateProbe.TryDump("Loader.lla.postfix");
	}
}

[HarmonyPatch]
internal static class CtaIaiProbePatch
{
	private static MethodBase TargetMethod()
	{
		var t = ModActions.GetHexType("cta");
		return t == null ? null : AccessTools.Method(t, "iai");
	}

	private static void Prefix()
	{
		SessionStateProbe.TryDump("cta.iai.prefix");
	}

	private static void Postfix()
	{
		SessionStateProbe.TryDump("cta.iai.postfix");
	}
}

[HarmonyPatch]
internal static class CzkUvlProbePatch
{
	private static MethodBase TargetMethod()
	{
		var t = ModActions.GetHexType("czk");
		return t == null ? null : AccessTools.Method(t, "uvl");
	}

	private static void Prefix()
	{
		SessionStateProbe.TryDump("czk.uvl.prefix");
	}

	private static void Postfix()
	{
		SessionStateProbe.TryDump("czk.uvl.postfix");
	}
}

/// <summary>
/// NRE from <see cref="BhHUDSession"/> often surfaces on <c>czk.uvl</c> after the Il2CppInterop trampoline logs;
/// swallow the same cases as the shared <see cref="BhHUDSessionIraNreGuardPatchMethods"/> helper so gameplay continues cleanly.
/// (Direct <c>BhHUDSession.ira</c> Harmony finalizer is skipped: Il2CppInterop can fail IL compile for that method.)
/// </summary>
[HarmonyPatch]
internal static class CzkUvlBhHudIraNreGuardPatch
{
	private static MethodBase TargetMethod()
	{
		var t = ModActions.GetHexType("czk");
		return t?.GetMethod("uvl", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
	}

	private static Exception Finalizer(Exception __exception)
	{
		return BhHUDSessionIraNreGuardPatchMethods.TrySwallowBhHudIraNre(__exception);
	}
}

/// <summary>Shared swallow helper for HUD NREs (used by <see cref="CzkUvlBhHudIraNreGuardPatch"/>).</summary>
internal static class BhHUDSessionIraNreGuardPatchMethods
{
	private static bool _loggedOnce;

	internal static Exception TrySwallowBhHudIraNre(Exception __exception)
	{
		if (__exception == null || !ShouldSwallow(__exception))
		{
			return __exception;
		}

		var cfg = LauncherConfigReader.TryLoad();
		if (cfg != null && !cfg.SuppressBhHudSessionIraNre)
		{
			if (!_loggedOnce)
			{
				_loggedOnce = true;
				Plugin.LogSource?.LogWarning(
					"BhHUDSession.ira: NOT suppressing NullReferenceException because suppressBhHudSessionIraNre=false. Full exception follows:\n"
					+ __exception);
			}
			return __exception;
		}

		if (!_loggedOnce)
		{
			_loggedOnce = true;
			Plugin.LogSource?.LogWarning(
				"BhHUDSession.ira: suppressed NullReferenceException (Il2CppInterop / HUD timing). "
				+ "Set suppressBhHudSessionIraNre=false in config.json to expose the original stack. "
				+ "First exception:\n"
				+ __exception);
		}

		return null;
	}

	private static bool ShouldSwallow(Exception ex)
	{
		var t = ex.ToString();
		if (t.IndexOf("NullReferenceException", StringComparison.Ordinal) < 0)
		{
			return false;
		}

		if (t.IndexOf("BhHUDSession", StringComparison.Ordinal) < 0)
		{
			return false;
		}

		return t.IndexOf("ira", StringComparison.Ordinal) >= 0;
	}
}

internal static class SessionStateProbe
{
	private const string EnableFlagName = "session_probe.flag";
	private static readonly HashSet<string> _dumpedSources = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
	private const int MaxSnapshotDumps = 14;
	private static bool _startInfoLogged;
	private static readonly HashSet<string> _configuredHeroSids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

	internal static void TryDump(string source)
	{
		if (!IsEnabled())
		{
			return;
		}

		if (string.IsNullOrWhiteSpace(source))
		{
			source = "(unknown)";
		}

		if (_dumpedSources.Contains(source))
		{
			return;
		}

		if (_dumpedSources.Count >= MaxSnapshotDumps)
		{
			return;
		}

		try
		{
			_dumpedSources.Add(source);
			var sb = new System.Text.StringBuilder();
			sb.Append("[SessionProbe] Snapshot from ").Append(source).AppendLine();
			sb.Append("[SessionProbe] activeScene=").Append(SceneManager.GetActiveScene().name).AppendLine();
			sb.Append("[SessionProbe] cityFractionViaBhCityUISession=").Append(ModActions.GetCurrentCityFraction() ?? "(null)").AppendLine();

			// Session holders before HUD (same order as CollectProbeGraphRoots).
			DumpKnownRoot(sb, "cta", new[] { "me" });
			DumpKnownRoot(sb, "hl", new[] { "me" });
			DumpKnownRoot(sb, "Hex.Session.Loader", new[] { "me", "instance", "current" });
			// This build has no managed types named Hex.Session.Session / SessionData; world state uses BhSession + obfuscated holders.
			DumpKnownRoot(sb, "Hex.Session.BhSession", new[] { "me", "instance", "current" });
			DumpKnownRoot(sb, "Hex.Session.Hud.BhHUDSession", new[] { "me" });
			DumpKnownRoot(sb, "Hex.UI.City.BhCityUISession", new[] { "me" });
			DumpHudBindingRoots(sb);
			DumpAssemblySingletonCandidates(sb);
			AppendSessionConsistencyDebugBundle(sb, source);
			Plugin.LogSource?.LogInfo(sb.ToString().TrimEnd());
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("[SessionProbe] dump failed: " + ex.Message);
		}
	}

	private static void MergeConfiguredHeroSidsFromLastLaunchPlan()
	{
		var plan = Plugin.LastResolvedOfflineLaunchPlan;
		if (plan == null)
		{
			return;
		}

		void add(string h)
		{
			if (string.IsNullOrWhiteSpace(h))
			{
				return;
			}

			if (string.Equals(h, "random", StringComparison.OrdinalIgnoreCase))
			{
				return;
			}

			_configuredHeroSids.Add(h);
		}

		add(plan.PlayerHero);
		add(plan.BotHero);
	}

	internal static void LogStartInfo(object startInfo)
	{
		if (!IsEnabled())
		{
			return;
		}

		if (_startInfoLogged)
		{
			return;
		}

		_startInfoLogged = true;
		if (startInfo == null)
		{
			_configuredHeroSids.Clear();
			MergeConfiguredHeroSidsFromLastLaunchPlan();
			Plugin.LogSource?.LogInfo("[SessionProbe] Loader.vdk startInfo=(null)");
			return;
		}

		try
		{
			var sb = new System.Text.StringBuilder();
			sb.Append("[SessionProbe] Loader.vdk startInfo type=").Append(startInfo.GetType().FullName).AppendLine();
			sb.Append("[SessionProbe] startInfo=").Append(SummarizeObject(startInfo)).AppendLine();
			_configuredHeroSids.Clear();
			var sides = GetMemberValue(startInfo, startInfo.GetType(), "sides") as IEnumerable;
			if (sides != null)
			{
				var i = 0;
				foreach (var s in sides)
				{
					if (i >= 8) break;
					sb.Append("  side[").Append(i).Append("] ").Append(SummarizeObject(s)).AppendLine();
					var heroSidObj = GetMemberValue(s, s.GetType(), "heroSid");
					if (heroSidObj is string hs && !string.IsNullOrWhiteSpace(hs))
					{
						_configuredHeroSids.Add(hs);
					}
					i++;
				}
			}

			MergeConfiguredHeroSidsFromLastLaunchPlan();
			Plugin.LogSource?.LogInfo(sb.ToString().TrimEnd());
		}
		catch (Exception probeEx)
		{
			Plugin.LogSource?.LogWarning("[SessionProbe] startInfo probe failed: " + probeEx.Message);
		}
	}

	private static bool IsEnabled()
	{
		try
		{
			var underPlugin = Path.Combine(Paths.PluginPath, "OfflineUnlockMod", EnableFlagName);
			if (File.Exists(underPlugin))
			{
				return true;
			}

			var underBepInEx = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", EnableFlagName);
			return File.Exists(underBepInEx);
		}
		catch
		{
			return false;
		}
	}

	private static void DumpAssemblySingletonCandidates(System.Text.StringBuilder sb)
	{
		var asm = typeof(ObjCityConfig).Assembly;
		sb.Append("[SessionProbe] singleton scan in ").Append(asm.GetName().Name).AppendLine();
		var matched = 0;
		foreach (var t in AccessTools.GetTypesFromAssembly(asm))
		{
			foreach (var n in new[] { "me", "instance", "current" })
			{
				var root = GetMemberValue(null, t, n);
				if (root == null)
				{
					continue;
				}

				var summary = SummarizeObject(root);
				var hasSessionWord = summary.IndexOf("Session", StringComparison.OrdinalIgnoreCase) >= 0
					|| (root.GetType().FullName ?? "").IndexOf("Session", StringComparison.OrdinalIgnoreCase) >= 0;
				if (!hasSessionWord)
				{
					continue;
				}

				sb.Append("  ").Append(t.FullName).Append('.').Append(n)
					.Append(" => ").Append(root.GetType().FullName).AppendLine();
				DumpObjectCollections(sb, "    ", root);
				matched++;
				if (matched >= 20)
				{
					sb.Append("  ... singleton scan capped at 20").AppendLine();
					return;
				}
			}
		}
	}

	private static void DumpKnownRoot(System.Text.StringBuilder sb, string typeName, string[] staticNames)
	{
		var t = ModActions.GetHexType(typeName);
		if (t == null)
		{
			sb.Append("[SessionProbe] ").Append(typeName).Append(" = (type not found)").AppendLine();
			return;
		}

		sb.Append("[SessionProbe] ").Append(typeName).AppendLine();
		foreach (var n in staticNames)
		{
			var root = GetMemberValue(null, t, n);
			if (root == null)
			{
				continue;
			}

			sb.Append("  static ").Append(n).Append(" => ").Append(root.GetType().FullName).AppendLine();
			DumpObjectCollections(sb, "    ", root);
		}
	}

	private static void DumpObjectCollections(System.Text.StringBuilder sb, string indent, object root)
	{
		if (root == null)
		{
			return;
		}

		var memberNames = new[]
		{
			"sides", "players", "heroes", "cities", "citys", "garrisons", "worldObjects",
			"data", "sessionData", "logic", "world", "state", "map"
		};

		foreach (var m in memberNames)
		{
			var value = GetMemberValue(root, root.GetType(), m);
			if (value == null)
			{
				continue;
			}

			if (value is string)
			{
				sb.Append(indent).Append(m).Append("=\"").Append(value).Append("\"").AppendLine();
				continue;
			}

			if (value is IEnumerable en)
			{
				var samples = new List<string>();
				var total = 0;
				foreach (var item in en)
				{
					total++;
					if (samples.Count < 5)
					{
						samples.Add(SummarizeObject(item));
					}
					if (total > 400)
					{
						break;
					}
				}

				sb.Append(indent).Append(m).Append(": count~").Append(total);
				if (samples.Count > 0)
				{
					sb.Append(" samples=").Append(string.Join(" || ", samples));
				}
				sb.AppendLine();
				continue;
			}

			sb.Append(indent).Append(m).Append(": ").Append(SummarizeObject(value)).AppendLine();
		}
	}

	private static readonly string[] HudBindingMemberNameTokens =
	{
		"hero", "city", "player", "side", "loc", "text", "label", "title", "name", "model", "view", "vm", "data", "state", "session"
	};

	private const int HudBindingDumpMaxMembers = 80;
	private const int HudBindingNestedMaxMembers = 24;

	private static void DumpHudBindingRoots(System.Text.StringBuilder sb)
	{
		sb.Append("[SessionProbe] HUD binding roots (BhHUDSession / BhHeroHUDPanel)").AppendLine();
		DumpHudBindingStaticMe(sb, "Hex.Session.Hud.BhHUDSession", "BhHUDSession.me");
		DumpHudBindingStaticMe(sb, "Hex.Session.Hud.BhHeroHUDPanel", "BhHeroHUDPanel.me");
	}

	private static void DumpHudBindingStaticMe(System.Text.StringBuilder sb, string typeFullName, string label)
	{
		var t = ModActions.GetHexType(typeFullName);
		if (t == null)
		{
			sb.Append("[SessionProbe] ").Append(label).Append(" type not found: ").Append(typeFullName).AppendLine();
			return;
		}

		var root = GetMemberValue(null, t, "me");
		if (root == null)
		{
			sb.Append("[SessionProbe] ").Append(label).Append("=(null)").AppendLine();
			return;
		}

		DumpHudBindingMembersForInstance(sb, label, root);
	}

	private static bool MemberNameMatchesHudBindingInterest(string memberName)
	{
		if (string.IsNullOrEmpty(memberName))
		{
			return false;
		}

		for (var i = 0; i < HudBindingMemberNameTokens.Length; i++)
		{
			if (memberName.IndexOf(HudBindingMemberNameTokens[i], StringComparison.OrdinalIgnoreCase) >= 0)
			{
				return true;
			}
		}

		return false;
	}

	private static void DumpHudBindingMembersForInstance(System.Text.StringBuilder sb, string label, object root)
	{
		try
		{
			sb.Append("[SessionProbe] ").Append(label).Append(" summary=").Append(SummarizeObject(root)).AppendLine();
		}
		catch (Exception ex)
		{
			sb.Append("[SessionProbe] ").Append(label).Append(" summary=<error: ").Append(ex.Message).Append(">").AppendLine();
			return;
		}

		var rt = root.GetType();
		var seen = new HashSet<string>(StringComparer.Ordinal);
		var entries = new List<HudBindingMemberRef>();

		foreach (var p in rt.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (p.GetIndexParameters().Length > 0 || !MemberNameMatchesHudBindingInterest(p.Name))
			{
				continue;
			}

			if (!seen.Add(p.Name))
			{
				continue;
			}

			entries.Add(new HudBindingMemberRef { Name = p.Name, Prop = p, Field = null });
		}

		foreach (var f in rt.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (!MemberNameMatchesHudBindingInterest(f.Name) || seen.Contains(f.Name))
			{
				continue;
			}

			seen.Add(f.Name);
			entries.Add(new HudBindingMemberRef { Name = f.Name, Prop = null, Field = f });
		}

		entries.Sort((a, b) => string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase));

		var dumpCount = Math.Min(HudBindingDumpMaxMembers, entries.Count);
		for (var i = 0; i < dumpCount; i++)
		{
			var name = entries[i].Name;
			object val;
			try
			{
				if (entries[i].Prop != null)
				{
					val = entries[i].Prop.GetValue(root);
				}
				else if (entries[i].Field != null)
				{
					val = entries[i].Field.GetValue(root);
				}
				else
				{
					sb.Append("[SessionProbe]   ").Append(name).Append("=<error: no prop/field ref>").AppendLine();
					continue;
				}
			}
			catch (Exception ex)
			{
				sb.Append("[SessionProbe]   ").Append(name).Append("=<error: ").Append(ex.Message).Append(">").AppendLine();
				continue;
			}

			if (val == null)
			{
				sb.Append("[SessionProbe]   ").Append(name).Append("=null").AppendLine();
			}
			else
			{
				try
				{
					sb.Append("[SessionProbe]   ").Append(name).Append("=nonnull ").Append(SummarizeObject(val)).AppendLine();
					DumpHudBindingNestedMembers(sb, "    ", name, val);
				}
				catch (Exception ex)
				{
					sb.Append("[SessionProbe]   ").Append(name).Append("=nonnull summarize=<error: ").Append(ex.Message).Append(">").AppendLine();
				}
			}
		}

		if (entries.Count > HudBindingDumpMaxMembers)
		{
			sb.Append("[SessionProbe]   ... HUD binding member dump capped at ")
				.Append(HudBindingDumpMaxMembers)
				.Append(" of ")
				.Append(entries.Count)
				.Append(" name-matched members")
				.AppendLine();
		}
	}

	private static void DumpHudBindingNestedMembers(System.Text.StringBuilder sb, string indent, string parentName, object value)
	{
		if (value == null || value is string)
		{
			return;
		}

		var vt = value.GetType();
		if (vt.IsPrimitive || value is decimal)
		{
			return;
		}

		if (value is IEnumerable en)
		{
			var total = 0;
			var samples = new List<string>();
			foreach (var item in en)
			{
				total++;
				if (samples.Count < 3)
				{
					samples.Add(item == null ? "(null)" : SummarizeObject(item));
				}
				if (total >= 200)
				{
					break;
				}
			}

			sb.Append("[SessionProbe] ").Append(indent).Append(parentName).Append("[] count~").Append(total);
			if (samples.Count > 0)
			{
				sb.Append(" samples=").Append(string.Join(" || ", samples));
			}
			sb.AppendLine();
			return;
		}

		var seen = new HashSet<string>(StringComparer.Ordinal);
		var entries = new List<HudBindingMemberRef>();
		foreach (var p in vt.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (p.GetIndexParameters().Length > 0 || !MemberNameMatchesHudBindingInterest(p.Name) || !seen.Add(p.Name))
			{
				continue;
			}
			entries.Add(new HudBindingMemberRef { Name = p.Name, Prop = p, Field = null });
		}
		foreach (var f in vt.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (!MemberNameMatchesHudBindingInterest(f.Name) || !seen.Add(f.Name))
			{
				continue;
			}
			entries.Add(new HudBindingMemberRef { Name = f.Name, Prop = null, Field = f });
		}

		entries.Sort((a, b) => string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase));
		var max = Math.Min(HudBindingNestedMaxMembers, entries.Count);
		for (var i = 0; i < max; i++)
		{
			object nestedVal;
			try
			{
				nestedVal = entries[i].Prop != null ? entries[i].Prop.GetValue(value) : entries[i].Field.GetValue(value);
			}
			catch (Exception ex)
			{
				sb.Append("[SessionProbe] ").Append(indent).Append(parentName).Append(".").Append(entries[i].Name)
					.Append("=<error: ").Append(ex.Message).Append(">").AppendLine();
				continue;
			}

			if (nestedVal == null)
			{
				sb.Append("[SessionProbe] ").Append(indent).Append(parentName).Append(".").Append(entries[i].Name).Append("=null").AppendLine();
			}
			else
			{
				sb.Append("[SessionProbe] ").Append(indent).Append(parentName).Append(".").Append(entries[i].Name)
					.Append("=nonnull ").Append(SummarizeObject(nestedVal)).AppendLine();
			}
		}
	}

	private struct HudBindingMemberRef
	{
		public string Name;
		public PropertyInfo Prop;
		public FieldInfo Field;
	}

	private const int ConsistencyMaxCities = 40;
	private const int ConsistencyMaxGarrisons = 40;
	private const int ConsistencyMaxHeroesMagic = 40;
	private const int ConsistencyMaxRuntimeSides = 40;
	private const int ConsistencyEnumerateCapPerCollection = 200;

	private static readonly string[] ConsistencyCollectionMemberHints =
	{
		"sides", "players", "heroes", "cities", "citys", "garrisons", "worldObjects",
		"data", "sessionData", "logic", "world", "state", "map", "nodes", "settlements", "objects"
	};

	private static readonly string[] RuntimeSideNestedMemberHints =
	{
		"hero", "mainHero", "selectedHero", "leaderHero", "heroData", "objHero", "primaryHero", "town", "mainCity", "capitalCity"
	};

	private static readonly string[] MagicMemberNameTokens =
	{
		"magic", "spell", "book", "school", "mana", "energy", "ability"
	};

	private static readonly string[] ShapeEntityValueTokens =
	{
		"hero_", "_hero", "_city", "city_", "garrison", "homm3_", "dungeon_hero", "dungeon_raw"
	};

	private static readonly string[] ShapeEntityNameTokens =
	{
		"hero", "city", "town", "garrison", "owner", "side", "player"
	};

	private const int ShapeScanMaxDepth = 4;
	private const int ShapeScanMaxNodes = 10000;
	private const int ShapeScanMaxAnomalies = 90;

	private static void AppendSessionConsistencyDebugBundle(System.Text.StringBuilder sb, string source)
	{
		try
		{
			var roots = CollectProbeGraphRoots();
			DumpResolvedRuntimeSides(sb, roots, source);
			DumpCityGarrisonConsistency(sb, roots);
			DumpHeroMagicInitProbe(sb, roots);
			// Do not run the broad reflective shape scan during live play. Some Unity value types
			// expose property getters that touch native memory and can hard-crash IL2CPP.
			DumpTargetedCityHeroState(sb, roots);
		}
		catch (Exception ex)
		{
			sb.Append("[SessionProbe][Consistency] bundle failed: ").Append(ex.Message).AppendLine();
		}
	}

	private const int TargetedGraphMaxDepth = 5;
	private const int TargetedGraphMaxNodes = 32000;
	private const int TargetedObjectListCap = 200;
	/// <summary>Hero/city lists can exceed 16 entries; ccg keeps queue size bounded (Shape probe uses a smaller slice).</summary>
	private const int TargetedEnumerableMaxItems = 128;

	private static int TargetMemberExpandPriority(string name)
	{
		if (string.IsNullOrEmpty(name))
		{
			return 0;
		}

		if (name.IndexOf("bzbw", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return 100;
		}

		if (name.IndexOf("city", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return 85;
		}

		if (name.IndexOf("objects", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return 80;
		}

		if (name.IndexOf("hero", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return 75;
		}

		if (name.IndexOf("winCondition", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return 10;
		}

		return 0;
	}

	private static void DumpTargetedCityHeroState(System.Text.StringBuilder sb, List<KeyValuePair<string, object>> roots)
	{
		var cities = new List<object>();
		var heroes = new List<object>();
		CollectTargetedObjectsFromRoots(roots, cities, heroes);
		sb.Append("[SessionProbe][Target] configuredHeroSids=").Append(_configuredHeroSids.Count == 0 ? "(none)" : string.Join(",", _configuredHeroSids.ToArray())).AppendLine();
		sb.Append("[SessionProbe][Target] collected cities=").Append(cities.Count).Append(" heroes=").Append(heroes.Count).AppendLine();

		var cityMax = Math.Min(80, cities.Count);
		for (var i = 0; i < cityMax; i++)
		{
			LogTargetCity(sb, cities[i], i);
		}

		var heroMax = Math.Min(120, heroes.Count);
		for (var i = 0; i < heroMax; i++)
		{
			LogTargetHero(sb, heroes[i], i);
		}

		AppendTargetConfiguredSidResolution(sb, heroes);
	}

	private static void AppendTargetConfiguredSidResolution(System.Text.StringBuilder sb, List<object> heroes)
	{
		if (_configuredHeroSids.Count == 0 || heroes == null || heroes.Count == 0)
		{
			return;
		}

		var sorted = new List<string>(_configuredHeroSids);
		sorted.Sort(StringComparer.OrdinalIgnoreCase);
		for (var s = 0; s < sorted.Count; s++)
		{
			var sid = sorted[s];
			var hit = -1;
			for (var i = 0; i < heroes.Count; i++)
			{
				var h = heroes[i];
				if (h == null)
				{
					continue;
				}

				var cfg = SafeFormatMember(h, h.GetType(), "configSid");
				if (cfg != "(absent)" && cfg != "(err)" && string.Equals(cfg, sid, StringComparison.OrdinalIgnoreCase))
				{
					hit = i;
					break;
				}
			}

			sb.Append("[SessionProbe][Target] resolve ").Append(sid).Append(" => ");
			if (hit >= 0)
			{
				sb.Append("Hero#").Append(hit);
			}
			else
			{
				sb.Append("not_in_sample heroes=").Append(heroes.Count);
			}

			sb.AppendLine();
		}
	}

	private static void CollectTargetedObjectsFromRoots(List<KeyValuePair<string, object>> roots, List<object> cities, List<object> heroes)
	{
		var q = new Queue<ShapeNode>();
		var seen = new HashSet<int>();
		for (var i = 0; i < roots.Count; i++)
		{
			var v = roots[i].Value;
			if (v != null)
			{
				q.Enqueue(new ShapeNode { RootLabel = roots[i].Key, Path = roots[i].Key, Value = v, Depth = 0 });
			}
		}

		var nodes = 0;
		while (q.Count > 0 && nodes < TargetedGraphMaxNodes && (cities.Count < TargetedObjectListCap || heroes.Count < TargetedObjectListCap))
		{
			var node = q.Dequeue();
			if (node.Value == null)
			{
				continue;
			}

			var key = RuntimeHelpers.GetHashCode(node.Value);
			if (!seen.Add(key))
			{
				continue;
			}

			nodes++;
			var t = node.Value.GetType();
			var zj = t.FullName ?? t.Name ?? "";
			if (IsUnityEngineFamilyTypeName(zj))
			{
				continue;
			}

			// Must be the exact Il2Cpp data type. Do not use substring: generic types like
			// Dictionary`2+Entry[...,Hex.Session.Data.Hero,...] would falsely match.
			var noGen = zj.IndexOf('`') < 0;
			var isCity = noGen && string.Equals(zj, "Hex.Session.Data.ObjCity", StringComparison.Ordinal);
			var isHero = noGen && string.Equals(zj, "Hex.Session.Data.Hero", StringComparison.Ordinal);
			if (isCity && cities.Count < TargetedObjectListCap)
			{
				cities.Add(node.Value);
			}
			if (isHero && heroes.Count < TargetedObjectListCap)
			{
				heroes.Add(node.Value);
			}

			if (node.Depth >= TargetedGraphMaxDepth || IsSimpleValueType(t) || node.Value is string)
			{
				continue;
			}

			var members = new List<HudBindingMemberRef>();
			foreach (var p in t.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
			{
				if (p.GetIndexParameters().Length != 0)
				{
					continue;
				}

				var ptn = p.PropertyType.FullName ?? p.PropertyType.Name ?? "";
				if (IsUnityEngineFamilyTypeName(ptn))
				{
					continue;
				}

				members.Add(new HudBindingMemberRef { Name = p.Name, Prop = p, Field = null });
			}
			foreach (var f in t.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
			{
				var ftn = f.FieldType.FullName ?? f.FieldType.Name ?? "";
				if (IsUnityEngineFamilyTypeName(ftn))
				{
					continue;
				}

				members.Add(new HudBindingMemberRef { Name = f.Name, Prop = null, Field = f });
			}

			// Prefer session map/city/hero blobs over winConditions/tutorial branches (same total breadth, faster to Hex.Session.Data.*).
			members.Sort((a, b) => TargetMemberExpandPriority(b.Name).CompareTo(TargetMemberExpandPriority(a.Name)));

			for (var mi = 0; mi < members.Count; mi++)
			{
				object nw = null;
				try
				{
					nw = members[mi].Prop != null ? members[mi].Prop.GetValue(node.Value) : members[mi].Field.GetValue(node.Value);
				}
				catch
				{
					nw = null;
				}
				if (nw == null || nw is string)
				{
					continue;
				}

				var mvType = nw.GetType();
				var mvTn = mvType.FullName ?? mvType.Name ?? "";
				if (IsUnityEngineFamilyTypeName(mvTn))
				{
					continue;
				}

				if (nw is IEnumerable en && !IsPrimitiveElementArrayObject(nw))
				{
					var idx = 0;
					try
					{
						foreach (var item in en)
						{
							if (idx >= TargetedEnumerableMaxItems)
							{
								break;
							}

							if (item != null)
							{
								var it = item.GetType();
								var itn = it.FullName ?? it.Name ?? "";
								if (!IsUnityEngineFamilyTypeName(itn))
								{
									q.Enqueue(new ShapeNode { RootLabel = node.RootLabel, Path = node.Path + "." + members[mi].Name + "[" + idx + "]", Value = item, Depth = node.Depth + 1 });
								}
							}

							idx++;
						}
					}
					catch
					{
						// Il2Cpp enumerators / mutated collections during probe
					}
				}
				else if (!(nw is IEnumerable))
				{
					q.Enqueue(new ShapeNode { RootLabel = node.RootLabel, Path = node.Path + "." + members[mi].Name, Value = nw, Depth = node.Depth + 1 });
				}
			}
		}
	}

	private static void LogTargetCity(System.Text.StringBuilder sb, object city, int index)
	{
		var t = city.GetType();
		var id = SafeFormatMemberAny(city, t, "id", "cityId", "objectId", "mapObjectId");
		var sidConfig = SafeFormatMember(city, t, "sidConfig");
		var cityName = SafeFormatMember(city, t, "cityName");
		var ownerSide = SafeFormatMember(city, t, "ownerSide");
		var visitorHeroId = SafeFormatMember(city, t, "visitorHeroId");
		var garnisonHeroId = SafeFormatMember(city, t, "garnisonHeroId");
		var node = SafeFormatMemberAny(city, t, "node", "mapNode", "nodeId");
		sb.Append("[SessionProbe][Target][City#").Append(index).Append("] id=").Append(id)
			.Append(" sidConfig=").Append(sidConfig)
			.Append(" cityName=").Append(cityName)
			.Append(" ownerSide=").Append(ownerSide)
			.Append(" visitorHeroId=").Append(visitorHeroId)
			.Append(" garnisonHeroId=").Append(garnisonHeroId)
			.Append(" node=").Append(node)
			.AppendLine();
	}

	private static void LogTargetHero(System.Text.StringBuilder sb, object hero, int index)
	{
		var t = hero.GetType();
		var id = SafeFormatMember(hero, t, "id");
		var cfg = SafeFormatMember(hero, t, "configSid");
		var sideId = SafeFormatMember(hero, t, "sideId");
		var node = SafeFormatMemberAny(hero, t, "node", "mapNode", "nodeId");
		var isDead = SafeFormatMemberAny(hero, t, "isDead", "dead");
		var matchedConfigured = (!string.IsNullOrEmpty(cfg) && cfg != "(absent)" && cfg != "(err)" && _configuredHeroSids.Contains(cfg)) ? " MATCH_CONFIGURED" : "";
		var tutorialPool = (!string.IsNullOrEmpty(cfg) && cfg != "(absent)" && cfg != "(err)"
			&& cfg.StartsWith("tutorial_", StringComparison.OrdinalIgnoreCase))
			? " TUTORIAL_POOL"
			: "";
		sb.Append("[SessionProbe][Target][Hero#").Append(index).Append("] id=").Append(id)
			.Append(" configSid=").Append(cfg)
			.Append(" sideId=").Append(sideId)
			.Append(" node=").Append(node)
			.Append(" isDead=").Append(isDead)
			.Append(matchedConfigured)
			.Append(tutorialPool)
			.AppendLine();
	}

	private static void DumpShapeGraphAnomalies(System.Text.StringBuilder sb, List<KeyValuePair<string, object>> roots, string source)
	{
		sb.Append("[SessionProbe][Shape] source=").Append(source).Append(" roots=").Append(roots.Count).AppendLine();
		var seen = new HashSet<int>();
		var q = new Queue<ShapeNode>();
		for (var i = 0; i < roots.Count; i++)
		{
			if (roots[i].Value != null)
			{
				q.Enqueue(new ShapeNode { RootLabel = roots[i].Key, Path = roots[i].Key, Value = roots[i].Value, Depth = 0 });
			}
		}

		var nodes = 0;
		var anomalyCount = 0;
		while (q.Count > 0 && nodes < ShapeScanMaxNodes && anomalyCount < ShapeScanMaxAnomalies)
		{
			var node = q.Dequeue();
			if (node.Value == null)
			{
				continue;
			}

			var k = RuntimeHelpers.GetHashCode(node.Value);
			if (!seen.Add(k))
			{
				continue;
			}

			nodes++;
			var t = node.Value.GetType();
			if (IsSimpleValueType(t) || node.Value is string)
			{
				continue;
			}

			var minusOneMembers = new List<string>();
			var entityStrings = new List<string>();
			var namedNulls = new List<string>();

			InspectShapeMembersAndQueue(sb, q, node, t, minusOneMembers, entityStrings, namedNulls);

			if ((minusOneMembers.Count > 0 && entityStrings.Count > 0) || (minusOneMembers.Count > 0 && namedNulls.Count > 0))
			{
				sb.Append("[SessionProbe][Shape] suspicious root=").Append(node.RootLabel)
					.Append(" path=").Append(node.Path)
					.Append(" type=").Append(t.FullName ?? t.Name)
					.Append(" minusOne=").Append(string.Join(",", minusOneMembers.ToArray()))
					.Append(" entityValues=").Append(string.Join(" || ", entityStrings.ToArray()));
				if (namedNulls.Count > 0)
				{
					sb.Append(" nulls=").Append(string.Join(",", namedNulls.ToArray()));
				}
				sb.AppendLine();
				anomalyCount++;
			}
		}

		sb.Append("[SessionProbe][Shape] scannedNodes=").Append(nodes)
			.Append(" anomalies=").Append(anomalyCount)
			.Append(" queuedRemaining=").Append(q.Count).AppendLine();
	}

	private static void InspectShapeMembersAndQueue(
		System.Text.StringBuilder sb,
		Queue<ShapeNode> q,
		ShapeNode node,
		Type t,
		List<string> minusOneMembers,
		List<string> entityStrings,
		List<string> namedNulls)
	{
		var members = new List<HudBindingMemberRef>();
		var seenNames = new HashSet<string>(StringComparer.Ordinal);
		foreach (var p in t.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (p.GetIndexParameters().Length > 0 || !seenNames.Add(p.Name))
			{
				continue;
			}
			members.Add(new HudBindingMemberRef { Name = p.Name, Prop = p, Field = null });
		}
		foreach (var f in t.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (!seenNames.Add(f.Name))
			{
				continue;
			}
			members.Add(new HudBindingMemberRef { Name = f.Name, Prop = null, Field = f });
		}

		for (var i = 0; i < members.Count; i++)
		{
			var m = members[i];
			object v = null;
			try
			{
				v = m.Prop != null ? m.Prop.GetValue(node.Value) : m.Field.GetValue(node.Value);
			}
			catch
			{
				continue;
			}

			if (v == null)
			{
				if (MemberNameContainsAny(m.Name, ShapeEntityNameTokens))
				{
					if (namedNulls.Count < 8) namedNulls.Add(m.Name);
				}
				continue;
			}

			if (TryGetLong(v, out var asLong) && asLong == -1)
			{
				if (minusOneMembers.Count < 10) minusOneMembers.Add(m.Name);
				continue;
			}

			if (v is string xv)
			{
				if (StringContainsAny(xv, ShapeEntityValueTokens) && entityStrings.Count < 6)
				{
					entityStrings.Add(m.Name + "=" + xv);
				}
				continue;
			}

			var vt = v.GetType();
			if (IsSimpleValueType(vt))
			{
				continue;
			}

			if (vt.FullName != null && vt.FullName.StartsWith("UnityEngine.", StringComparison.Ordinal))
			{
				continue;
			}

			if (node.Depth >= ShapeScanMaxDepth)
			{
				continue;
			}

			if (v is IEnumerable en && !(v is string))
			{
				var idx = 0;
				foreach (var item in en)
				{
					if (idx >= 5)
					{
						break;
					}
					if (item != null)
					{
						q.Enqueue(new ShapeNode
						{
							RootLabel = node.RootLabel,
							Path = node.Path + "." + m.Name + "[" + idx.ToString(System.Globalization.CultureInfo.InvariantCulture) + "]",
							Value = item,
							Depth = node.Depth + 1
						});
					}
					idx++;
				}
			}
			else
			{
				q.Enqueue(new ShapeNode
				{
					RootLabel = node.RootLabel,
					Path = node.Path + "." + m.Name,
					Value = v,
					Depth = node.Depth + 1
				});
			}
		}
	}

	private static bool IsSimpleValueType(Type t)
	{
		return t.IsPrimitive || t.IsEnum || t == typeof(decimal) || t == typeof(DateTime) || t == typeof(Guid);
	}

	/// <summary>
	/// Unity objects must not be reflected into from probe graphs: property getters can touch native
	/// memory and throw AccessViolationException (e.g. Camera.layerCullDistances).
	/// </summary>
	private static bool IsUnityEngineFamilyTypeName(string fullName)
	{
		if (string.IsNullOrEmpty(fullName))
		{
			return false;
		}

		return fullName.StartsWith("UnityEngine.", StringComparison.Ordinal)
			|| fullName.StartsWith("Unity.", StringComparison.Ordinal);
	}

	private static bool IsPrimitiveElementArrayObject(object nw)
	{
		if (nw is byte[])
		{
			return true;
		}

		if (nw is Array arr)
		{
			var et = arr.GetType().GetElementType();
			return et != null && et.IsPrimitive;
		}

		return false;
	}

	private static bool TryGetLong(object v, out long value)
	{
		try
		{
			switch (Type.GetTypeCode(v.GetType()))
			{
				case TypeCode.SByte: value = (sbyte)v; return true;
				case TypeCode.Byte: value = (byte)v; return true;
				case TypeCode.Int16: value = (short)v; return true;
				case TypeCode.UInt16: value = (ushort)v; return true;
				case TypeCode.Int32: value = (int)v; return true;
				case TypeCode.UInt32: value = (uint)v; return true;
				case TypeCode.Int64: value = (long)v; return true;
				case TypeCode.UInt64: value = unchecked((long)(ulong)v); return true;
				default:
					value = 0;
					return false;
			}
		}
		catch
		{
			value = 0;
			return false;
		}
	}

	private static bool MemberNameContainsAny(string name, string[] tokens)
	{
		if (string.IsNullOrEmpty(name))
		{
			return false;
		}

		for (var i = 0; i < tokens.Length; i++)
		{
			if (name.IndexOf(tokens[i], StringComparison.OrdinalIgnoreCase) >= 0)
			{
				return true;
			}
		}
		return false;
	}

	private static bool StringContainsAny(string value, string[] tokens)
	{
		if (string.IsNullOrEmpty(value))
		{
			return false;
		}

		for (var i = 0; i < tokens.Length; i++)
		{
			if (value.IndexOf(tokens[i], StringComparison.OrdinalIgnoreCase) >= 0)
			{
				return true;
			}
		}
		return false;
	}

	private struct ShapeNode
	{
		public string RootLabel;
		public string Path;
		public object Value;
		public int Depth;
	}

	private static List<KeyValuePair<string, object>> CollectProbeGraphRoots()
	{
		var list = new List<KeyValuePair<string, object>>();
		void add(string label, string typeFullName, string staticName)
		{
			var type = ModActions.GetHexType(typeFullName);
			if (type == null)
			{
				return;
			}

			var root = GetMemberValue(null, type, staticName);
			if (root != null)
			{
				list.Add(new KeyValuePair<string, object>(label, root));
			}
		}

		// Session / world roots first: HUD singletons are huge; targeted BFS must reach Hex.Session.Data.* before node ccg.
		add("cta.me", "cta", "me");
		add("hl.me", "hl", "me");
		add("Loader.me", "Hex.Session.Loader", "me");
		add("Loader.instance", "Hex.Session.Loader", "instance");
		add("Loader.current", "Hex.Session.Loader", "current");
		add("BhSession.me", "Hex.Session.BhSession", "me");
		add("BhSession.instance", "Hex.Session.BhSession", "instance");
		add("BhSession.current", "Hex.Session.BhSession", "current");
		add("BhHUDSession.me", "Hex.Session.Hud.BhHUDSession", "me");
		add("BhCityUISession.me", "Hex.UI.City.BhCityUISession", "me");

		try
		{
			var asm = typeof(ObjCityConfig).Assembly;
			var matched = 0;
			foreach (var t in AccessTools.GetTypesFromAssembly(asm))
			{
				if (t == null)
				{
					continue;
				}

				foreach (var n in new[] { "me", "instance", "current" })
				{
					object root = null;
					try
					{
						root = GetMemberValue(null, t, n);
					}
					catch
					{
						root = null;
					}

					if (root == null)
					{
						continue;
					}

					string summary;
					try
					{
						summary = SummarizeObject(root);
					}
					catch
					{
						summary = "";
					}

					var typeName = root.GetType().FullName ?? "";
					var hasSessionWord = summary.IndexOf("Session", StringComparison.OrdinalIgnoreCase) >= 0
						|| typeName.IndexOf("Session", StringComparison.OrdinalIgnoreCase) >= 0;
					if (!hasSessionWord)
					{
						continue;
					}

					list.Add(new KeyValuePair<string, object>(t.FullName + "." + n, root));
					matched++;
					if (matched >= 20)
					{
						return list;
					}
				}
			}
		}
		catch
		{
			// ignore
		}

		return list;
	}

	private static void DumpResolvedRuntimeSides(System.Text.StringBuilder sb, List<KeyValuePair<string, object>> roots, string snapshotSource)
	{
		sb.Append("[SessionProbe][RuntimeSides] BhHUD snapshot source=").Append(snapshotSource).AppendLine();
		var seenSide = new HashSet<int>();
		var logged = 0;
		for (var ri = 0; ri < roots.Count && logged < ConsistencyMaxRuntimeSides; ri++)
		{
			var label = roots[ri].Key;
			var root = roots[ri].Value;
			TryEnumerateSidesFromRoot(sb, label, root, seenSide, ref logged);
		}
	}

	private static void TryEnumerateSidesFromRoot(System.Text.StringBuilder sb, string rootLabel, object root, HashSet<int> seenSide, ref int logged)
	{
		if (root == null || logged >= ConsistencyMaxRuntimeSides)
		{
			return;
		}

		var rt = root.GetType();
		foreach (var hint in new[] { "sides", "players" })
		{
			object coll = null;
			try
			{
				coll = GetMemberValue(root, rt, hint);
			}
			catch
			{
				coll = null;
			}

			if (!(coll is IEnumerable en) || coll is string)
			{
				continue;
			}

			var idx = 0;
			foreach (var side in en)
			{
				if (side == null || logged >= ConsistencyMaxRuntimeSides)
				{
					idx++;
					continue;
				}

				if (idx >= ConsistencyEnumerateCapPerCollection)
				{
					break;
				}

				var key = RuntimeHelpers.GetHashCode(side);
				if (!seenSide.Add(key))
				{
					idx++;
					continue;
				}

				if (!LooksLikeRuntimeSide(side))
				{
					idx++;
					continue;
				}

				var wa = side.GetType();
				var sideId = SafeFormatMember(side, wa, "id");
				var sideIdAlt = SafeFormatMember(side, wa, "sideId");
				var fractionSid = SafeFormatMember(side, wa, "fractionSid");
				var heroSid = SafeFormatMember(side, wa, "heroSid");
				var name = SafeFormatMember(side, wa, "name");
				object hero = null;
				string heroSummary = "(no hero link)";
				for (var h = 0; h < RuntimeSideNestedMemberHints.Length; h++)
				{
					try
					{
						hero = GetMemberValue(side, wa, RuntimeSideNestedMemberHints[h]);
					}
					catch
					{
						hero = null;
					}

					if (hero != null)
					{
						try
						{
							heroSummary = SummarizeObject(hero);
						}
						catch (Exception ex)
						{
							heroSummary = "<summarize error: " + ex.Message + ">";
						}

						break;
					}
				}

				object city = null;
				string citySummary = "(no city link)";
				for (var c = 0; c < RuntimeSideNestedMemberHints.Length; c++)
				{
					var nm = RuntimeSideNestedMemberHints[c];
					if (nm.IndexOf("city", StringComparison.OrdinalIgnoreCase) < 0 && nm.IndexOf("town", StringComparison.OrdinalIgnoreCase) < 0)
					{
						continue;
					}

					try
					{
						city = GetMemberValue(side, wa, nm);
					}
					catch
					{
						city = null;
					}

					if (city != null)
					{
						try
						{
							citySummary = SummarizeObject(city);
						}
						catch (Exception ex)
						{
							citySummary = "<summarize error: " + ex.Message + ">";
						}

						break;
					}
				}

				sb.Append("[SessionProbe][RuntimeSides] root=").Append(rootLabel).Append(" member=").Append(hint).Append(" idx=").Append(idx)
					.Append(" side=").Append(SafeSummarize(side))
					.Append(" resolved id=").Append(sideId).Append("/").Append(sideIdAlt)
					.Append(" fractionSid=").Append(fractionSid).Append(" heroSid=").Append(heroSid).Append(" name=").Append(name)
					.Append(" hero=>").Append(heroSummary).Append(" city=>").Append(citySummary).AppendLine();
				logged++;
				if (logged >= ConsistencyMaxRuntimeSides)
				{
					return;
				}

				idx++;
			}
		}
	}

	private static bool LooksLikeRuntimeSide(object o)
	{
		if (o == null)
		{
			return false;
		}

		var t = o.GetType();
		if (GetMemberValue(o, t, "fractionSid") != null
			|| GetMemberValue(o, t, "heroSid") != null
			|| GetMemberValue(o, t, "sideId") != null)
		{
			return true;
		}

		var shortName = t.Name ?? "";
		return shortName.EndsWith("Side", StringComparison.OrdinalIgnoreCase);
	}

	private static void DumpCityGarrisonConsistency(System.Text.StringBuilder sb, List<KeyValuePair<string, object>> roots)
	{
		var seenCity = new HashSet<int>();
		var seenGar = new HashSet<int>();
		var cityCount = 0;
		var garCount = 0;
		for (var ri = 0; ri < roots.Count; ri++)
		{
			if (cityCount >= ConsistencyMaxCities && garCount >= ConsistencyMaxGarrisons)
			{
				break;
			}

			ScanRootForCityGarrison(sb, roots[ri].Key, roots[ri].Value, seenCity, seenGar, ref cityCount, ref garCount);
		}
	}

	private static void ScanRootForCityGarrison(
		System.Text.StringBuilder sb,
		string rootLabel,
		object root,
		HashSet<int> seenCity,
		HashSet<int> seenGar,
		ref int cityCount,
		ref int garCount)
	{
		if (root == null)
		{
			return;
		}

		var rt = root.GetType();
		for (var hi = 0; hi < ConsistencyCollectionMemberHints.Length; hi++)
		{
			if (cityCount >= ConsistencyMaxCities && garCount >= ConsistencyMaxGarrisons)
			{
				return;
			}

			var hint = ConsistencyCollectionMemberHints[hi];
			object coll = null;
			try
			{
				coll = GetMemberValue(root, rt, hint);
			}
			catch
			{
				coll = null;
			}

			if (!(coll is IEnumerable en) || coll is string)
			{
				continue;
			}

			var n = 0;
			foreach (var item in en)
			{
				if (n >= ConsistencyEnumerateCapPerCollection)
				{
					break;
				}

				n++;
				if (item == null)
				{
					continue;
				}

				if (cityCount < ConsistencyMaxCities && LooksLikeCityObject(item))
				{
					var key = RuntimeHelpers.GetHashCode(item);
					if (seenCity.Add(key))
					{
						LogCityConsistencyLine(sb, rootLabel, hint, item);
						cityCount++;
					}
				}

				if (garCount < ConsistencyMaxGarrisons && LooksLikeGarrisonObject(item))
				{
					var gk = RuntimeHelpers.GetHashCode(item);
					if (seenGar.Add(gk))
					{
						LogGarrisonConsistencyLine(sb, rootLabel, hint, item);
						garCount++;
					}
				}
			}
		}
	}

	private static bool LooksLikeCityObject(object o)
	{
		var zj = o.GetType().FullName ?? "";
		if (zj.IndexOf("City", StringComparison.OrdinalIgnoreCase) >= 0
			&& zj.IndexOf("Canvas", StringComparison.OrdinalIgnoreCase) < 0)
		{
			if (zj.IndexOf("BhCity", StringComparison.OrdinalIgnoreCase) >= 0 && zj.IndexOf("Session", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				return false;
			}

			return true;
		}

		if (zj.IndexOf("Settlement", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return true;
		}

		return GetMemberValue(o, o.GetType(), "citySid") != null
			|| GetMemberValue(o, o.GetType(), "ownerSideId") != null
			|| MemberExistsNameInsensitive(o.GetType(), "garrison");
	}

	private static bool LooksLikeGarrisonObject(object o)
	{
		var zj = o.GetType().FullName ?? "";
		if (zj.IndexOf("Garrison", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return true;
		}

		return MemberExistsNameInsensitive(o.GetType(), "city")
			&& (GetMemberValue(o, o.GetType(), "city") != null
				|| GetMemberValue(o, o.GetType(), "cityRef") != null
				|| GetMemberValue(o, o.GetType(), "ownerCity") != null);
	}

	private static bool MemberExistsNameInsensitive(Type t, string needle)
	{
		try
		{
			foreach (var p in t.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
			{
				if (p.Name.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0)
				{
					return true;
				}
			}

			foreach (var f in t.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
			{
				if (f.Name.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0)
				{
					return true;
				}
			}
		}
		catch
		{
			return false;
		}

		return false;
	}

	private static void LogCityConsistencyLine(System.Text.StringBuilder sb, string rootLabel, string memberHint, object city)
	{
		var ct = city.GetType();
		var id = SafeFormatMember(city, ct, "id");
		var sid = SafeFormatMember(city, ct, "sid");
		var citySid = SafeFormatMember(city, ct, "citySid");
		var ownerSide = SafeFormatMember(city, ct, "ownerSideId");
		if (ownerSide == "(err)" || ownerSide == "(absent)")
		{
			ownerSide = SafeFormatMember(city, ct, "owner");
		}

		object garrisonObj = null;
		try
		{
			garrisonObj = GetMemberValue(city, ct, "garrison");
		}
		catch
		{
			garrisonObj = null;
		}

		var garrisonRef = garrisonObj == null ? "null" : SafeSummarize(garrisonObj);
		var node = SafeFormatMember(city, ct, "node");
		if (node == "(err)" || node == "(absent)")
		{
			node = SafeSummarizeMember(city, ct, "node");
		}

		var warns = new List<string>();
		if (ownerSide == "(absent)" || ownerSide == "null" || ownerSide == "(err)")
		{
			warns.Add("no_owner_side");
		}

		var hasGarrisonField = MemberExistsNameInsensitive(ct, "garrison");
		if (hasGarrisonField && garrisonObj == null)
		{
			warns.Add("garrison_field_null");
		}

		if (garrisonObj != null)
		{
			try
			{
				var gt = garrisonObj.GetType();
				object back = null;
				foreach (var nm in new[] { "city", "cityRef", "ownerCity", "parentCity" })
				{
					try
					{
						back = GetMemberValue(garrisonObj, gt, nm);
					}
					catch
					{
						back = null;
					}

					if (back != null)
					{
						break;
					}
				}

				if (back != null && !object.ReferenceEquals(back, city))
				{
					warns.Add("garrison_city_backlink_mismatch");
				}
			}
			catch
			{
				// ignore
			}
		}

		var warnStr = warns.Count == 0 ? "" : " WARN=" + string.Join(",", warns.ToArray());
		sb.Append("[SessionProbe][Consistency] CITY root=").Append(rootLabel).Append(" via=").Append(memberHint)
			.Append(" id=").Append(id).Append(" sid=").Append(sid).Append(" citySid=").Append(citySid)
			.Append(" ownerSide=").Append(ownerSide).Append(" garrison=").Append(garrisonRef).Append(" node=").Append(node)
			.Append(warnStr).AppendLine();
	}

	private static void LogGarrisonConsistencyLine(System.Text.StringBuilder sb, string rootLabel, string memberHint, object gar)
	{
		var gt = gar.GetType();
		var id = SafeFormatMember(gar, gt, "id");
		var sid = SafeFormatMember(gar, gt, "sid");
		object cityBack = null;
		foreach (var nm in new[] { "city", "cityRef", "ownerCity", "parentCity", "town" })
		{
			try
			{
				cityBack = GetMemberValue(gar, gt, nm);
			}
			catch
			{
				cityBack = null;
			}

			if (cityBack != null)
			{
				break;
			}
		}

		var citySummary = cityBack == null ? "null" : SafeSummarize(cityBack);
		var warns = new List<string>();
		if (cityBack == null)
		{
			warns.Add("garrison_no_city_ref");
		}

		var warnStr = warns.Count == 0 ? "" : " WARN=" + string.Join(",", warns.ToArray());
		sb.Append("[SessionProbe][Consistency] GARRISON root=").Append(rootLabel).Append(" via=").Append(memberHint)
			.Append(" id=").Append(id).Append(" sid=").Append(sid).Append(" cityBack=").Append(citySummary).Append(warnStr).AppendLine();
	}

	private static void DumpHeroMagicInitProbe(System.Text.StringBuilder sb, List<KeyValuePair<string, object>> roots)
	{
		var seenHero = new HashSet<int>();
		var count = 0;
		for (var ri = 0; ri < roots.Count && count < ConsistencyMaxHeroesMagic; ri++)
		{
			ScanRootForHeroMagic(sb, roots[ri].Key, roots[ri].Value, seenHero, ref count);
		}
	}

	private static void ScanRootForHeroMagic(System.Text.StringBuilder sb, string rootLabel, object root, HashSet<int> seenHero, ref int count)
	{
		if (root == null || count >= ConsistencyMaxHeroesMagic)
		{
			return;
		}

		var rt = root.GetType();
		for (var hi = 0; hi < ConsistencyCollectionMemberHints.Length; hi++)
		{
			if (count >= ConsistencyMaxHeroesMagic)
			{
				return;
			}

			var hint = ConsistencyCollectionMemberHints[hi];
			object coll = null;
			try
			{
				coll = GetMemberValue(root, rt, hint);
			}
			catch
			{
				coll = null;
			}

			if (!(coll is IEnumerable en) || coll is string)
			{
				continue;
			}

			var n = 0;
			foreach (var item in en)
			{
				if (count >= ConsistencyMaxHeroesMagic || n >= ConsistencyEnumerateCapPerCollection)
				{
					break;
				}

				n++;
				if (item == null)
				{
					continue;
				}

				object hero = item;
				if (LooksLikeRuntimeSide(item))
				{
					hero = TryGetHeroFromSide(item);
				}

				if (hero == null || !LooksLikeHeroObject(hero))
				{
					continue;
				}

				var hk = RuntimeHelpers.GetHashCode(hero);
				if (!seenHero.Add(hk))
				{
					continue;
				}

				LogHeroMagicMembers(sb, rootLabel, hint, hero);
				count++;
			}
		}
	}

	private static object TryGetHeroFromSide(object side)
	{
		var wa = side.GetType();
		for (var h = 0; h < RuntimeSideNestedMemberHints.Length; h++)
		{
			var nm = RuntimeSideNestedMemberHints[h];
			if (nm.IndexOf("city", StringComparison.OrdinalIgnoreCase) >= 0 || nm.IndexOf("town", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				continue;
			}

			try
			{
				var v = GetMemberValue(side, wa, nm);
				if (v != null)
				{
					return v;
				}
			}
			catch
			{
				// ignore
			}
		}

		return null;
	}

	private static bool LooksLikeHeroObject(object o)
	{
		var zj = o.GetType().FullName ?? "";
		if (zj.IndexOf("Hero", StringComparison.OrdinalIgnoreCase) < 0)
		{
			return false;
		}

		if (zj.IndexOf("BhHeroHUD", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return false;
		}

		return true;
	}

	private static void LogHeroMagicMembers(System.Text.StringBuilder sb, string rootLabel, string memberHint, object hero)
	{
		var ht = hero.GetType();
		sb.Append("[SessionProbe][MagicInit] root=").Append(rootLabel).Append(" via=").Append(memberHint)
			.Append(" hero=").Append(SafeSummarize(hero)).AppendLine();

		var props = ht.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		for (var i = 0; i < props.Length; i++)
		{
			var p = props[i];
			if (p.GetIndexParameters().Length > 0 || !MemberNameHasMagicToken(p.Name))
			{
				continue;
			}

			try
			{
				var v = p.GetValue(hero);
				sb.Append("[SessionProbe][MagicInit]   prop ").Append(p.Name).Append("=").Append(v == null ? "null" : "nonnull")
					.Append(" ").Append(CompactTypeOrValue(v)).AppendLine();
			}
			catch (Exception ex)
			{
				sb.Append("[SessionProbe][MagicInit]   prop ").Append(p.Name).Append("=<error ").Append(ex.Message).Append(">").AppendLine();
			}
		}

		var fields = ht.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		for (var i = 0; i < fields.Length; i++)
		{
			var f = fields[i];
			if (!MemberNameHasMagicToken(f.Name))
			{
				continue;
			}

			try
			{
				var v = f.GetValue(hero);
				sb.Append("[SessionProbe][MagicInit]   field ").Append(f.Name).Append("=").Append(v == null ? "null" : "nonnull")
					.Append(" ").Append(CompactTypeOrValue(v)).AppendLine();
			}
			catch (Exception ex)
			{
				sb.Append("[SessionProbe][MagicInit]   field ").Append(f.Name).Append("=<error ").Append(ex.Message).Append(">").AppendLine();
			}
		}
	}

	private static bool MemberNameHasMagicToken(string name)
	{
		if (string.IsNullOrEmpty(name))
		{
			return false;
		}

		for (var i = 0; i < MagicMemberNameTokens.Length; i++)
		{
			if (name.IndexOf(MagicMemberNameTokens[i], StringComparison.OrdinalIgnoreCase) >= 0)
			{
				return true;
			}
		}

		return false;
	}

	private static string CompactTypeOrValue(object v)
	{
		if (v == null)
		{
			return "";
		}

		try
		{
			var vt = v.GetType();
			if (vt.IsPrimitive || v is string || v is decimal)
			{
				return Convert.ToString(v, System.Globalization.CultureInfo.InvariantCulture);
			}

			return "type=" + (vt.FullName ?? vt.Name);
		}
		catch
		{
			return "?";
		}
	}

	private static string SafeSummarize(object o)
	{
		try
		{
			return SummarizeObject(o);
		}
		catch (Exception ex)
		{
			return "<error " + ex.Message + ">";
		}
	}

	private static string SafeSummarizeMember(object o, Type t, string name)
	{
		try
		{
			if (!TryGetMemberValue(o, t, name, out var v))
			{
				return "(absent)";
			}

			if (v == null)
			{
				return "null";
			}

			return SafeSummarize(v);
		}
		catch
		{
			return "(err)";
		}
	}

	private static string SafeFormatMember(object o, Type t, string name)
	{
		try
		{
			if (!TryGetMemberValue(o, t, name, out var v))
			{
				return "(absent)";
			}

			if (v == null)
			{
				return "null";
			}

			try
			{
				return Convert.ToString(v, System.Globalization.CultureInfo.InvariantCulture);
			}
			catch
			{
				return v.GetType().Name;
			}
		}
		catch
		{
			return "(err)";
		}
	}

	/// <summary>First resolved member name wins; used for Il2Cpp types where the same concept uses different property names across versions.</summary>
	private static string SafeFormatMemberAny(object o, Type t, params string[] names)
	{
		if (names == null || names.Length == 0)
		{
			return "(absent)";
		}

		for (var i = 0; i < names.Length; i++)
		{
			var s = SafeFormatMember(o, t, names[i]);
			if (s != "(absent)" && s != "(err)")
			{
				return s;
			}
		}

		return "(absent)";
	}

	/// <summary>Legacy helper: returns null if the member is missing or unreadable (same as failed <see cref="TryGetMemberValue"/>).</summary>
	private static object GetMemberValue(object instance, Type t, string name)
	{
		return TryGetMemberValue(instance, t, name, out var v) ? v : null;
	}

	/// <summary>
	/// Il2Cpp + backing fields: exact name, case-insensitive name, or <c>&lt;name&gt;k__BackingField</c>.
	/// Walks the inheritance chain with <see cref="BindingFlags.DeclaredOnly"/> so private members on base types resolve (Il2Cpp hierarchies).
	/// When <paramref name="instance"/> is <c>null</c>, reads <b>static</b> members on <paramref name="t"/> (singleton <c>me</c> / <c>instance</c>).
	/// </summary>
	private static bool TryGetMemberValue(object instance, Type t, string name, out object value)
	{
		value = null;
		if (t == null || string.IsNullOrEmpty(name))
		{
			return false;
		}

		var staticOnly = instance == null;
		var invokeTarget = staticOnly ? null : instance;
		object candidate = null;

		bool TryProperty(PropertyInfo p)
		{
			if (p == null || p.GetIndexParameters().Length != 0)
			{
				return false;
			}

			try
			{
				candidate = p.GetValue(invokeTarget);
				return true;
			}
			catch
			{
				return false;
			}
		}

		bool TryField(FieldInfo f)
		{
			if (f == null)
			{
				return false;
			}

			try
			{
				candidate = f.GetValue(invokeTarget);
				return true;
			}
			catch
			{
				return false;
			}
		}

		for (var cur = t; cur != null && cur != typeof(object); cur = cur.BaseType)
		{
			var decl = (staticOnly ? BindingFlags.Static : BindingFlags.Instance)
				| BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

			PropertyInfo prop = null;
			try
			{
				prop = cur.GetProperty(name, decl);
			}
			catch
			{
				prop = null;
			}

			if (prop != null && TryProperty(prop))
			{
				value = candidate;
				return true;
			}

			try
			{
				var fExact = cur.GetField(name, decl);
				if (fExact != null && TryField(fExact))
				{
					value = candidate;
					return true;
				}
			}
			catch
			{
				// ignore
			}

			try
			{
				var bf = "<" + name + ">k__BackingField";
				var fBk = cur.GetField(bf, decl);
				if (fBk != null && TryField(fBk))
				{
					value = candidate;
					return true;
				}
			}
			catch
			{
				// ignore
			}

			try
			{
				foreach (var p in cur.GetProperties(decl))
				{
					if (p.GetIndexParameters().Length != 0)
					{
						continue;
					}

					if (string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase) && TryProperty(p))
					{
						value = candidate;
						return true;
					}
				}
			}
			catch
			{
				// ignore
			}

			try
			{
				foreach (var f in cur.GetFields(decl))
				{
					if (string.Equals(f.Name, name, StringComparison.OrdinalIgnoreCase) && TryField(f))
					{
						value = candidate;
						return true;
					}
				}
			}
			catch
			{
				// ignore
			}
		}

		value = null;
		return false;
	}

	private static string SummarizeObject(object obj)
	{
		if (obj == null)
		{
			return "(null)";
		}

		var t = obj.GetType();
		var parts = new List<string>();
		parts.Add("type=" + (t.FullName ?? t.Name));

		foreach (var key in new[] { "id", "sid", "name", "fraction", "fractionSid", "heroSid", "citySid", "owner", "ownerSideId", "sideId", "node", "nodeId" })
		{
			if (!TryGetMemberValue(obj, t, key, out var v))
			{
				continue;
			}

			parts.Add(v == null ? key + "=null" : key + "=" + v);
		}

		if (parts.Count == 1)
		{
			return parts[0];
		}

		return string.Join(", ", parts);
	}
}
