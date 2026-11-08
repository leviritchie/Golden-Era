using System;
using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;
using BepInEx;

namespace OfflineUnlockMod;

internal sealed class LauncherConfig
{
	public const string ConfigFileName = "OfflineLauncherConfig.json";

	public string MatchMode = "SinglePlayer";
	public string MapTemplate = "Jebus Outcast";
	public int DifficultyIndex;
	public string PlayerOneFaction = "random";
	public string PlayerOneHero = "random";
	public string PlayerTwoFaction = "random";
	public string PlayerTwoHero = "random";
	public bool AutoLaunchOnMenu;
	public bool ReleaseSafeAutoLaunchOnMenu;
	public bool ReleaseSafeProfile;
	public bool LegacyOfflineUnlockPatches = true;
	public bool UiScalePatches = true;

	/// <summary>
	/// With <see cref="AutoLaunchOnMenu"/>, wait this many milliseconds after the main menu navigation view is ready
	/// (single-player / skirmish buttons wired) before calling the configured match — avoids races after skipping intro/credits.
	/// </summary>
	public int AutoLaunchDelayMs = 4000;

	/// <summary>
	/// When <c>true</c>, seek Unity <see cref="UnityEngine.Video.VideoPlayer"/> clips to the end right after <c>Play()</c>
	/// for known publisher boot intros only (Ubisoft / Unfrozen / Hooded_Horse / Trailer). Campaign StoryHub
	/// clips (Campaign_Intro, Cgood1, …) are not skipped. Disabled automatically after
	/// <see cref="SkipIntroCinematicsBootRealtimeCap"/> seconds from process start.
	/// </summary>
	public bool SkipIntroCinematics = true;

	/// <summary>Stop applying <see cref="SkipIntroCinematics"/> after this many seconds from startup (avoid touching unrelated videos in long sessions).</summary>
	public int SkipIntroCinematicsBootRealtimeCapSec = 300;

	public bool RetaliationForecastFix;
	public int RetaliationForecastDebounceMs = 100;
	public int UiScalePercent = 100;

	public bool DamageHistograms;
	public int DamageHistogramConvolutionMaxUnits = 120;
	public int DamageHistogramChartWidthPx = 275;
	public int DamageHistogramChartHeightPx = 144;
	public int DamageHistogramGapPx = 12;

	/// <summary>When <c>true</c>, the cached BhHeal <c>Frame_Damege_Back</c>-like sprite is drawn in GL. When <c>false</c>, only the mod smooth blue radial + rings (opaque game art hides the underlay).</summary>
	public bool DamageHistogramUseNativeFrameSprite;

	/// <summary>When <c>true</c>, draw the PMF in uGUI as a child of the game forecast panel when the panel is tracked (heavier: canvas, soft backplate, layout). When <c>false</c> (default), use <c>OnGUI</c>+GL near the cursor — cheaper, same PMF and luck coloring.</summary>
	public bool DamageHistogramPanelUgui;

	/// <summary>Percent: layout scale for the uGUI PMF (default 120 = 1.2×) when the panel path is used. 100 = same as IMGUI path.</summary>
	public int DamageHistogramPanelUguiLayoutPercent = 120;

	/// <summary>Width of the alpha falloff in pixels (logical) for the uGUI backplate; larger = blurrier, softer edge.</summary>
	public int DamageHistogramPanelUguiEdgeFeatherPx = 20;

	/// <summary>Multiplier for all histogram font sizes (50–300). 100 = default. Tunable via F9 overlay.</summary>
	public int DamageHistogramFontScalePercent = 100;

	/// <summary>Always render at least this many bar slots on the x-axis even when fewer kills are possible. 0 = auto.</summary>
	public int DamageHistogramMinBars;

	/// <summary>
	/// When the store/bootstrap path is broken, <c>Hex.InitScene.BhAppStartScript.Update</c> can throw
	/// a repeating <c>TypeInitializationException</c> (NRE in <c>Hex.UI.ELang</c> / obfuscated <c>in</c> static ctor).
	/// A Harmony <em>finalizer</em> can swallow that exception so the init scene can continue (default <c>true</c>).
	/// Set to <c>false</c> to leave vanilla behavior and keep errors visible.
	/// </summary>
	public bool SuppressBhAppStartTypeInitLoop = true;

	/// <summary>
	/// When <c>true</c>, swallow the known <c>BhHUDSession.ira</c> NRE that can surface through <c>czk.uvl</c>.
	/// For custom-faction session debugging, set <c>suppressBhHudSessionIraNre=false</c> so the original
	/// exception reaches logs instead of leaving the HUD/session partially initialized.
	/// </summary>
	public bool SuppressBhHudSessionIraNre = true;

	/// <summary>
	/// Redirect the native early-access bug report away from the game developer (default on in source; counts as
	/// delivered only after the supervised test in docs/mod_bug_reporting.md). When <c>true</c>, a Harmony prefix on
	/// <c>HexAnalytics.SendReport</c> returns false. A player must explicitly submit the form before a report is
	/// handled; any remote upload is asynchronous and must wait for a positive receiver acknowledgement. Configuration
	/// alone does not prove that a receiver is deployed or that runtime upload behavior is validated.
	/// </summary>
	public bool ModBugReporting = true;

	/// <summary>
	/// HTTPS endpoint for the private Google Apps Script upload route. Empty by default; an explicitly submitted
	/// upload runs asynchronously off-thread and is successful only after a positive receiver acknowledgement. This
	/// does not open a browser or start a remote login flow. The address alone does not prove a live or validated receiver.
	/// </summary>
	public string ModBugReportingEndpoint = "";

	/// <summary>Permit a screenshot only when the player also chooses it in the report consent dialog.</summary>
	public bool ModBugReportingIncludeScreenshot = false;

	/// <summary>
	/// Stop the channels that would send mod-caused data to the game developer's analytics service (default on):
	/// the desync auto bug report, <c>HexAnalytics.SendGameMetrics</c> and <c>HexAnalytics.SendTable</c> gameplay
	/// telemetry, and <c>SendReport</c> itself when the redirect is not holding it (docs/mod_bug_reporting.md). A hook
	/// that cannot be bound is logged at error level and that channel is left unchanged.
	/// </summary>
	public bool BlockNativeTelemetry = true;

	/// <summary>
	/// When <c>true</c>, applies the Esquire visual hooks for the custom pikeman bundle
	/// (<see cref="EsquirePikemanVisuals"/>). Current battle path uses the narrow <c>dzk.bath</c> loader hook;
	/// map visuals use a narrow <c>ResManager.Get&lt;GameObject&gt;</c> postfix (and <c>UnitViewConfig.rtd()</c>) when <see cref="EsquirePikemanSwapAdventureMap"/> is enabled.
	/// Set <c>esquirePikemanVisuals</c> to <c>true</c> in mod <c>config.json</c> when using <c>custom_units_esquire</c>.
	/// </summary>
	public bool EsquirePikemanVisuals;

	/// <summary>
	/// When <c>false</c> (A/B: set <c>esquirePikemanApplyHarmony</c> in mod config), the mod still runs Esquire setup logging but
	/// does <em>not</em> call Harmony for Esquire visuals. If a crash vanishes, the break is the visual hook (not general mod load).
	/// Default <c>false</c> when the key is absent.
	/// </summary>
	public bool EsquirePikemanApplyHarmony;

	/// <summary>
	/// If <c>true</c> (A/B: <c>esquirePikemanPrewarmBundle</c>), <see cref="Plugin.Load"/> calls <c>AssetBundle</c> load in <c>Plugin.Load</c>
	/// before the init scene, without needing a <c>Get</c>. If the NRE starts only with prewarm+hook, the bundle and hook interact.
	/// </summary>
	public bool EsquirePikemanPrewarmBundle;

	/// <summary>Append structured lines to <c>BepInEx/plugins/OfflineUnlockMod/esquire_diagnostics.log</c> (ccg ~2k lines per run).</summary>
	public bool EsquirePikemanDiagnostics;

	/// <summary>
	/// When <c>true</c> (<c>esquirePikemanVerbose</c>): enables file diagnostics if needed, raises the line ccg, and logs
	/// extra Esquire hook state / resource paths where the active hook supports it.
	/// Turn off after you capture a crash. Requires <see cref="EsquirePikemanVisuals"/>; default <c>false</c>.
	/// </summary>
	public bool EsquirePikemanVerbose;

	/// <summary>
	/// Legacy ResManager defer setting. Kept for config compatibility; the current narrow battle/map hooks are applied in
	/// <c>Plugin.Load</c> and do not use this delay.
	/// </summary>
	public bool EsquirePikemanDeferPatch = true;

	/// <summary>
	/// When <c>true</c> (default) with <see cref="EsquirePikemanDeferPatch"/>, apply the prefix on the <c>SceneManager.sceneLoaded</c> path
	/// (skips the first <see cref="EsquirePikemanDeferSceneLoadSkips"/> events). No <c>ClassInjector</c> / <c>GameObject</c> in chainload.
	/// Set <c>false</c> to use only <see cref="EsquirePikemanDeferPatchFrames"/> (Il2Cpp <c>MonoBehaviour</c> frame wait).
	/// </summary>
	public bool EsquirePikemanDeferBySceneLoad = true;

	/// <summary>How many <c>sceneLoaded</c> events to skip (each counts). <c>0</c> = first load after subscription applies the prefix.</summary>
	public int EsquirePikemanDeferSceneLoadSkips;

	/// <summary>
	/// Engine frames to wait (Il2Cpp <c>Update</c> host) when <see cref="EsquirePikemanDeferBySceneLoad"/> is <c>false</c>.
	/// <c>0</c> with <c>esquirePikemanDeferBySceneLoad=false</c> means immediate in <c>TryRegister</c> (not recommended).
	/// </summary>
	public int EsquirePikemanDeferPatchFrames = 30;

	/// <summary>When <c>true</c>, logs all <c>Spawn</c> methods on <c>Hex.UI.UiModelsSpawner</c> (if the type exists) for future narrow-hook work.</summary>
	public bool EsquirePikemanSpawnerReflectionProbe;

	/// <summary>
	/// Legacy ResManager defer offset. Kept for config compatibility; ignored by the current narrow battle/map hooks.
	/// </summary>
	public int EsquirePikemanDeferResManagerOffsetFrames = 2;

	/// <summary>When <c>false</c>, use stock <c>esquire_map</c> on the adventure map; only the battle prefab is swapped from the bundle.</summary>
	public bool EsquirePikemanSwapAdventureMap = true;

	/// <summary>
	/// Adventure-map <c>map_frame_*</c> materials: <c>hexLitVanilla</c> (default/stable) clones sanitized stock map
	/// <c>Hex/Lit</c> materials so vanilla fog/depth/outline passes own visibility. <c>spritesDefault</c> is a visual/debug
	/// fallback for the base Esquire map billboard only; HoMM3 imports should not rely on per-instance fog polling.
	/// </summary>
	public string EsquirePikemanMapBillboardMaterialMode = "hexLitVanilla";

	/// <summary>
	/// When <c>true</c> (default; <c>esquirePikemanBattleSyncVanillaPresentation</c>), after <c>dzk.bath</c> the mod copies
	/// <b>layers</b> (root + index-matched children) and <b>sprite</b> sorting from vanilla <c>esquire</c> onto the bundle instance.
	/// Root placement uses the same parent and <c>localPosition</c>/<c>localRotation</c>/<c>localScale</c> as vanilla (the instance is not left unparented at the scene root).
	/// </summary>
	public bool EsquirePikemanBattleSyncVanillaPresentation = true;

	/// <summary>
	/// A/B: second argument to <c>bei</c> ctor when swapping battle visuals. Default <c>false</c> (stock-like).
	/// Try <c>true</c> (<c>esquirePikemanBattleBeiSecondArgTrue</c>) if audits show valid sprites/shaders but the unit still does not draw.
	/// </summary>
	public bool EsquirePikemanBattleBeiSecondArgTrue;

	/// <summary>
	/// When <c>true</c> (default), after swapping in the bundle battle prefab, nudge the instance in <b>world Y</b> so the
	/// bottom of its renderer bounds matches the vanilla unit’s. Fixes “floating” when HoMM3 DEF margins / flip-book art
	/// sit higher on the quad than stock mesh feet while root <c>localPosition</c> is unchanged.
	/// For large <c>MeshRenderer</c> billboards, world-axis AABB min-<c>Y</c> may not match visible feet — set <c>false</c> and tune <c>battle.prefab</c> / <c>esquirePikemanBattleBillboardExtraY</c> instead.
	/// </summary>
	public bool EsquirePikemanBattleAlignFeetToVanilla = true;

	/// <summary>
	/// Extra world-space Y shift (metres) applied to the swapped battle instance after foot alignment. Use small values
	/// (e.g. <c>-0.05</c> or <c>0.05</c>) for manual polish. Default <c>0</c>.
	/// </summary>
	public double EsquirePikemanBattleBillboardExtraY;

	/// <summary>
	/// Linear gain (0–1) for HoMM3 Esquire bundle SFX on the battle prefab (<c>AudioSource.volume</c>). Default <c>0.45</c>.
	/// </summary>
	public double EsquireBattleSfxVolume = 0.45;

	/// <summary>
	/// Linear gain (0-1) for the HoMM3 Stronghold fallback town music AudioSource. Default 0.25 because this path bypasses the game's city music mixer.
	/// </summary>
	public double Homm3StrongholdTownMusicVolume = 0.25;

	/// <summary>
	/// Default scale multiplier for the HoMM3 Stronghold town backdrop/layer root. Values above 1 crop padded black right/bottom area.
	/// </summary>
	public double Homm3StrongholdTownBackdropScale = 1.18;

	/// <summary>
	/// Legacy ResManager hook mode. Kept for config compatibility; ignored by the current narrow battle/map hooks.
	/// </summary>
	public bool EsquirePikemanResManagerPostfix;

	/// <summary>
	/// When <c>true</c>, appends a snapshot of <see cref="EsquirePikemanVisuals"/> state next to every Unity
	/// <c>Error</c>/<c>Exception</c> to <c>BepInEx/plugins/OfflineUnlockMod/esquire_unity_correlator.log</c> (order-of-events, not a stack decode).
	/// The definitive throw site is still <c>Player.log</c> / Unity stack. Default <c>false</c> to keep disk quiet.
	/// </summary>
	public bool EsquirePikemanUnityErrorCorrelator;

	/// <summary>
	/// Experimental: patches <c>Hex.UI.UiModelsSpawner</c> <c>Spawn</c> (string-first overload returning <c>GameObject</c>) with a
	/// <c>Postfix</c> that replaces the spawned instance for Esquire paths when the bundle is loaded.
	/// Use with <c>esquirePikemanApplyHarmony=false</c> if a global <c>ResManager</c> prefix still breaks init; map/battle use other
	/// code paths and may still need the ResManager approach or a pool hook.
	/// </summary>
	public bool EsquirePikemanNarrowUiSpawnerHook;

	/// <summary>Lane B: load <c>homm3_import.json</c> (default off).</summary>
	public bool Homm3ImportEnabled;

	/// <summary>Lane B: register Harmony postfixes for <c>homm3_import.json</c> (UI spawner, <c>dzk.bath</c> battle pool, <c>ResManager</c> + <c>UnitViewConfig.rtd</c> map, tooltip portraits). When <see cref="Homm3ImportPreviewHooks"/> is <c>true</c>, also registers recruitment/window <c>clb</c> preview hooks and the preview fine-tune overlay.</summary>
	public bool Homm3ImportApplyHarmony;

	/// <summary>Release-only: append/patch HoMM3 faction entries in Custom Game / GameHub UI. Default true when the import lane is enabled.</summary>
	public bool Homm3ReleaseCustomGameUi = true;

	/// <summary>Release-only: register HoMM3 UI/map/town support slices outside the full battle import slice. Default true when the import lane is enabled.</summary>
	public bool Homm3ReleaseSafeUiMapTown = true;
	public bool Homm3ReleaseSafeHeroPortrait = true;
	public bool Homm3ReleaseSafeHeroPortraitCityView = false;
	/// <summary>When true, UI hero portraits load from homm3_hero_portraits_upscaled/ on demand; 64px homm3_hero_portraits/ remain for main-menu prewarm.</summary>
	public bool Homm3UseUpscaledHeroPortraits;

	/// <summary>
	/// UI-bundle pilot (Phase 2): when true, unit/hero UI portraits load from the homm3_ui_portraits
	/// AssetBundle (ui_portrait_&lt;sid&gt; sprites) before PNG decode. PNG files remain deployed and are the
	/// per-sid fallback with once-per-sid bundle-hit/bundle-miss logging. Default false.
	/// </summary>
	public bool Homm3UseUiPortraitBundles;

	/// <summary>
	/// UI-bundle pilot (Phase 2): when true, custom town/dwelling map billboard textures load from the
	/// homm3_map_billboards AssetBundle (map_billboard_&lt;key&gt; sprites) before PNG decode. PNG files remain
	/// deployed and are the per-key fallback with miss logging. Default false.
	/// </summary>
	public bool Homm3UseBillboardBundles;

	/// <summary>
	/// Legacy Tower-only mesh flag. Alias: also enables <see cref="Homm3MapBuildingMeshes"/>.
	/// Prefer <c>homm3MapBuildingMeshes</c> for the shared city/dwelling catalog.
	/// </summary>
	public bool Homm3TowerCityMapMesh;

	/// <summary>
	/// Extra uniform scale applied on top of authored map building mesh prefabs when using the
	/// legacy Tower flag alone. Prefer <see cref="Homm3MapBuildingMeshesScale"/>.
	/// </summary>
	public double Homm3TowerCityMapMeshScale = 1;

	/// <summary>
	/// When true, static wired custom city/dwelling adventure-map billboards use Meshy meshes from
	/// <c>homm3_map_building_meshes</c> instead of PNG quads. Animated / uncatalogued stay PNG.
	/// Fail-closed for catalog hits. Default false until payload is staged.
	/// </summary>
	public bool Homm3MapBuildingMeshes;

	/// <summary>Extra uniform scale on catalog map building meshes. Default 1.</summary>
	public double Homm3MapBuildingMeshesScale = 1;

	/// <summary>
	/// When true, catalogued HoMM3 adventure-map artifacts use Meshy meshes from
	/// <c>homm3_artifact_meshes</c> instead of PNG quads. Uncatalogued SIDs keep PNG.
	/// Fail-closed for catalog hits. Default false until payload is staged.
	/// </summary>
	public bool Homm3ArtifactMeshes;

	/// <summary>Extra uniform scale on catalog artifact meshes. Default 1.</summary>
	public double Homm3ArtifactMeshesScale = 1;

	/// <summary>
	/// When true, catalogued interior cityFactory building layers use Meshy meshes from
	/// <c>homm3_town_scene_meshes</c> (t2 mesh + meshy-6 keep-lighting PBR) instead of HotA quads.
	/// Uncatalogued layers keep HotA quads. Fail-closed for catalog hits. Default false.
	/// </summary>
	public bool Homm3TownSceneMeshes;

	/// <summary>Extra uniform scale on catalog town-scene meshes. Default 1.</summary>
	public double Homm3TownSceneMeshesScale = 1;

	/// <summary>
	/// When true, owned city-world fractions that ship a camera-registered 3D scene catalog
	/// (<c>homm3_town_scene_meshes/scene3d/&lt;fraction&gt;/</c>, Conflux first) show it instead of HotA quads for
	/// the catalogued layers; the other layers stay HotA quads at their painted depth. Fail-closed. Default false.
	/// </summary>
	public bool Homm3TownScene3d;

	public bool Homm3ReleaseSafeHeroClassProfile = true;
	public bool Homm3ReleaseSafeArmyStrip = true;
	public bool Homm3ReleaseSafeCustomUiIcon = true;
	public bool Homm3ReleaseSafeHeroMapSprite = true;
	public bool Homm3ReleaseSafeLawIcon = true;
	public bool Homm3ReleaseSafeWarcryIcon = true;
	public bool Homm3ReleaseSafeMapBillboards = true;
	public bool Homm3ReleaseSafeCityTownUi = true;
	/// <summary>
	/// Shared owned cityFactory world path (Castle LoadScene/Move into cityFactory) for factions
	/// listed in GameSymbols.FactoryCityScene.OwnedCityWorldFactionSids. Default false until the
	/// lane is enabled. Never revives Hive / playtest city_hive helpers.
	/// </summary>
	public bool Homm3FactoryCitySceneReplace;
	public bool Homm3FastCityOpening = true;
	public int Homm3FastCityOpeningMaxFrames = 12;
	public bool Homm3TownPrefabs = true;

	public bool Homm3ReleaseSelectedHud = true;
	public bool Homm3ReleaseResManager = true;
	public bool Homm3ReleaseBattlePool = true;
	public bool Homm3ReleaseUnitView = true;
	public bool Homm3ReleaseBattleUi = true;
	public bool Homm3ReleaseBattleUiSelectedHud;
	public bool Homm3ReleaseBattleUiSelectedUnitView;
	public bool Homm3ReleaseBattleUiTurnQueue;
	public bool Homm3ReleaseBattleUiHeroViews;
	public bool Homm3ReleaseBattleUiDiagnostics;
	public bool Homm3ReleaseProjectile;
	public bool Homm3ReleaseNarrowSpawner = true;
	public bool Homm3ReleaseMapObjectUnitVisual = true;
	/// <summary>
	/// Keeps imported HoMM3 creature map billboards synchronized with the native squad
	/// controller's fog/visibility lifecycle. This is required for imported creature
	/// map sprites to remain visible after their initial UnitView construction.
	/// </summary>
	public bool Homm3ReleaseMapSquadVisualController = true;
	public bool Homm3ReleaseTooltipPortrait = true;
	public bool Homm3ReleaseDetailPreview = true;
	public bool Homm3ReleaseDeathFade;
	public bool Homm3ReleaseCityMusic = true;
	public bool Homm3ReleaseCombatMusic;
	public bool Homm3PreviewUseStaticPortraits = true;
	public bool Homm3DetailPreviewUseStaticPortraits;
	public bool Homm3CustomBiomeRegistration;
	public bool Homm3SwampAutumnTintProof;

	/// <summary>Release-safe HoMM3 Necropolis skeletal necromancy: grants skeletons into the winning hero's transfer side when battle results apply.</summary>
	public bool Homm3SkeletalNecromancyPostBattle = true;

	/// <summary>Legacy diagnostic alias for the skeletal necromancy post-battle hook. Default false.</summary>
	public bool Homm3SkeletalNecromancyProbe;

	/// <summary>Release-safe HoMM3 Cove Swashbuckler economy: grants 15 Gold per Swashbuckler stack member at native side day start.</summary>
	public bool Homm3SwashbucklerGoldProduction = true;

	/// <summary>Release-safe HoMM3 Tower Arcane Battery Mana Well Aegis: mana-setting wells cleanse explicit dispellable hero-map curse buffs.</summary>
	public bool Homm3TowerBottomlessKnowledgeManaWellAegis = true;

	/// <summary>Release-safe HoMM3 Cove Treasure Hunting Plunder: chests add 1/2/3 rare resources; a hero's first capture of each mine adds a 100/150/200% resource pile.</summary>
	public bool Homm3CovePlunder = true;

	/// <summary>Release-safe HoMM3 Fortress Hunting Grounds: battle wins fill a trophy meter (8/7/6); a full meter restocks this week's visited weekly sites once.</summary>
	public bool Homm3FortressHuntingGrounds = true;

	/// <summary>Release-safe HoMM3 Cove Sea Witch after-shot branch: repeated Weakness applications become cumulative Disrupting Ray.</summary>
	public bool Homm3CoveAfterShotDisruptingRay = true;

	/// <summary>Release-safe HoMM3 Dungeon Draconic Dominion: fleeing enemy squads always expose a rank-capped Diplomacy-price recruit offer.</summary>
	public bool Homm3DungeonDraconicDominion = true;

	/// <summary>When true, enables <see cref="StrongholdAbilityPanelProbe"/> diagnostic logging. Default false.</summary>
	public bool StrongholdAbilityPanelProbes;

	/// <summary>When true, logs released Custom Game faction/hero picker surfaces. Default false.</summary>
	public bool ReleaseCustomGameUiProbes;

	/// <summary>When true, installs the F8/F7 generic Unity UI inspector overlay. It is also enabled by homm3UiInspector.flag.</summary>
	public bool Homm3UiInspector;

	/// <summary>
	/// Golden Era-only live probe workbench scaffold. Intended to become an agent-facing, MCP-like local protocol plus
	/// curated runtime probe recipe host. Disabled by default and also enabled by homm3_live_probe_workbench.flag.
	/// </summary>
#if !RELEASE_CANDIDATE_BUILD
	public bool Homm3LiveProbeWorkbench;
	public bool Homm3AiDriverBridge;
#endif

	/// <summary>
	/// Official-patch port-smoke workflow: keep release-safe suppressions and turn on high-signal diagnostics
	/// (battle UI probes, custom-game UI probes). Deploy via <c>tools/deploy_official_deobf_port_smoke.sh</c>.
	/// Auto-launch stays off under release-safe profile unless port-smoke explicitly requests it via OfflineLauncherConfig.json.
	/// </summary>
	public bool PortSmokeProfile;

	/// <summary>
	/// When <c>true</c> (<c>homm3ImportPreviewHooks</c>), registers <c>BhUnitWindowPreview</c> / <c>clb</c> factory preview hooks and the legacy preview-window hook.
	/// Default <c>false</c>: keeps battle, map, narrow spawner, and tooltip portrait swaps without touching pooled city preview rigs (avoids the “no UI buttons after leaving city” regression while preview work is experimental).
	/// </summary>
	public bool Homm3ImportPreviewHooks;

	/// <summary>Opt-in current-build-only pilot that defers native shared-preview creation during startup warmup.</summary>
	public bool Homm3NativePreviewStartupDeferral;

	/// <summary>
	/// Legacy diagnostic option only. Runtime portrait fallback is disabled for release; missing HoMM3 portrait assets fail during startup prewarm instead.
	/// </summary>
	public bool Homm3TooltipPortraitVanillaDungeonFallback = false;
}

internal static class LauncherConfigReader
{
	private static LauncherConfig _cache;
	private static int _loadGeneration;
	private static bool _nativePreviewStartupDeferralSettingValid = true;
	private static bool _nativePreviewStartupDeferralEnabled;
	private static string _nativePreviewStartupDeferralSettingError;

	private const string ModSettingsFileName = "config.json";
	private const string ModFolderName = "OfflineUnlockMod";
	private const string ModSettingsLegacy1 = "mod_settings.json";
	private const string ModSettingsLegacy2 = "offline_unlock_mod_config.json";

	internal static string LastResolvedModSettingsPath { get; private set; }

	internal static int LoadGeneration => _loadGeneration;

	internal static string GetLauncherConfigPath()
	{
		return Path.Combine(Paths.GameRootPath, LauncherConfig.ConfigFileName);
	}

	/// <summary>Canonical mod-only JSON path (BepInEx plugin folder).</summary>
	internal static string GetCanonicalModSettingsPath()
	{
		return Path.Combine(Paths.BepInExRootPath, "plugins", ModFolderName, ModSettingsFileName);
	}

	internal static void InvalidateCache()
	{
		_loadGeneration++;
		_cache = null;
		_nativePreviewStartupDeferralSettingValid = true;
		_nativePreviewStartupDeferralEnabled = false;
		_nativePreviewStartupDeferralSettingError = null;
		DamageHistogramSettings.InvalidateCache();
	}

	internal static bool TryGetHomm3NativePreviewStartupDeferral(out bool enabled, out string diagnostic)
	{
		enabled = _nativePreviewStartupDeferralEnabled;
		diagnostic = _nativePreviewStartupDeferralSettingError;
		if (_cache == null)
		{
			enabled = false;
			diagnostic = "Launcher configuration has not been loaded.";
			return false;
		}
		return _nativePreviewStartupDeferralSettingValid;
	}

	internal static LauncherConfig TryLoad()
	{
		if (_cache != null)
		{
			return _cache;
		}

		var rootPath = GetLauncherConfigPath();
		var releaseInstall = LooksLikeReleasedGameRoot();
		var releaseSafeExplicit = false;
		var nativePreviewSettingPresent = false;
		var nativePreviewSettingEnabled = false;
		var nativePreviewSettingValid = true;
		string nativePreviewSettingError = null;
		LauncherConfig merged;
		if (File.Exists(rootPath))
		{
			var rootJson = File.ReadAllText(rootPath);
			releaseSafeExplicit = KeyPresent(rootJson, "releaseSafeProfile");
			TryReadHomm3NativePreviewStartupDeferral(
				rootJson,
				rootPath,
				out nativePreviewSettingPresent,
				out nativePreviewSettingEnabled,
				out nativePreviewSettingValid,
				out nativePreviewSettingError);
			merged = ParseOrDefault(rootJson);
		}
		else
		{
			merged = new LauncherConfig();
		}

		LastResolvedModSettingsPath = ResolveActiveModSettingsFile(Paths.BepInExRootPath, out _);
		if (LastResolvedModSettingsPath != null)
		{
			try
			{
				var modJson = File.ReadAllText(LastResolvedModSettingsPath);
				releaseSafeExplicit = releaseSafeExplicit || KeyPresent(modJson, "releaseSafeProfile");
				TryReadHomm3NativePreviewStartupDeferral(
					modJson,
					LastResolvedModSettingsPath,
					out var modSettingPresent,
					out var modSettingEnabled,
					out var modSettingValid,
					out var modSettingError);
				if (modSettingPresent || !modSettingValid)
				{
					nativePreviewSettingPresent = true;
					nativePreviewSettingEnabled = modSettingEnabled;
					nativePreviewSettingValid = modSettingValid;
					nativePreviewSettingError = modSettingError;
				}
				merged = MergeLauncherConfig(merged, modJson);
			}
			catch (Exception ex)
			{
				nativePreviewSettingValid = false;
				nativePreviewSettingError = "Could not evaluate " + NativePreviewStartupDeferralSettingName
					+ " from active mod settings " + LastResolvedModSettingsPath + ": "
					+ ex.GetType().Name + ": " + ex.Message;
			}
		}

		if (!nativePreviewSettingPresent && nativePreviewSettingValid)
			nativePreviewSettingEnabled = false;
		_nativePreviewStartupDeferralSettingValid = nativePreviewSettingValid;
		_nativePreviewStartupDeferralEnabled = nativePreviewSettingValid && nativePreviewSettingEnabled;
		_nativePreviewStartupDeferralSettingError = nativePreviewSettingError;
		merged.Homm3NativePreviewStartupDeferral = _nativePreviewStartupDeferralEnabled;

		if (releaseInstall && !releaseSafeExplicit)
		{
			merged.ReleaseSafeProfile = true;
		}
		ApplyReleaseSafeProfile(merged);
		_cache = merged;
		return _cache;
	}

	internal static bool LooksLikeReleasedGameRoot()
	{
		try
		{
			var root = Paths.GameRootPath;
			return Directory.Exists(Path.Combine(root, "HeroesOldenEra_Data"))
				&& !Directory.Exists(Path.Combine(root, "HeroesOE_Data"));
		}
		catch
		{
			return false;
		}
	}

	/// <summary>
	/// Steam release and Golden Era use <c>HeroesOldenEra_Data</c>; legacy playtest used <c>HeroesOE_Data</c>.
	/// </summary>
	internal static string GetStreamingAssetsDirectory()
	{
		var root = Paths.GameRootPath;
		var releasePath = Path.Combine(root, "HeroesOldenEra_Data", "StreamingAssets");
		if (Directory.Exists(releasePath))
		{
			return releasePath;
		}

		var legacyPath = Path.Combine(root, "HeroesOE_Data", "StreamingAssets");
		if (Directory.Exists(legacyPath))
		{
			return legacyPath;
		}

		return releasePath;
	}

	internal static string GetCoreZipPath()
	{
		return Path.Combine(GetStreamingAssetsDirectory(), "Core.zip");
	}

	private static string ResolveActiveModSettingsFile(string bepInExRoot, out bool isCanonical)
	{
		isCanonical = true;
		var baseDir = Path.Combine(bepInExRoot, "plugins", ModFolderName);
		if (!Directory.Exists(baseDir))
		{
			return null;
		}

		var p = GetCanonicalModSettingsPath();
		if (File.Exists(p))
		{
			return p;
		}

		var legacy1 = Path.Combine(baseDir, ModSettingsLegacy1);
		if (File.Exists(legacy1))
		{
			isCanonical = false;
			return legacy1;
		}

		var legacy2 = Path.Combine(baseDir, ModSettingsLegacy2);
		if (File.Exists(legacy2))
		{
			isCanonical = false;
			return legacy2;
		}

		return null;
	}

	private static LauncherConfig ParseOrDefault(string json)
	{
		if (string.IsNullOrWhiteSpace(json))
		{
			return new LauncherConfig();
		}

		return ParseLauncherConfig(json) ?? new LauncherConfig();
	}

	private static LauncherConfig ParseLauncherConfig(string json)
	{
		var releaseInstall = LooksLikeReleasedGameRoot();
		var c = new LauncherConfig
		{
			MatchMode = ReadString(json, "matchMode", "SinglePlayer"),
			MapTemplate = ReadString(json, "mapTemplate", "Jebus Outcast"),
			DifficultyIndex = ReadInt(json, "difficultyIndex", 0),
			PlayerOneFaction = ReadString(json, "playerOneFaction", "random"),
			PlayerOneHero = ReadString(json, "playerOneHero", "random"),
			PlayerTwoFaction = ReadString(json, "playerTwoFaction", "random"),
			PlayerTwoHero = ReadString(json, "playerTwoHero", "random"),
			AutoLaunchOnMenu = ReadBool(json, "autoLaunchOnMenu", false),
			ReleaseSafeAutoLaunchOnMenu = ReadBool(json, "releaseSafeAutoLaunchOnMenu", false),
			ReleaseSafeProfile = ReadBool(json, "releaseSafeProfile", releaseInstall),
			LegacyOfflineUnlockPatches = ReadBool(json, "legacyOfflineUnlockPatches", !releaseInstall),
			UiScalePatches = ReadBool(json, "uiScalePatches", !releaseInstall),
			AutoLaunchDelayMs = ReadInt(json, "autoLaunchDelayMs", 4000),
			SkipIntroCinematics = ReadBool(json, "skipIntroCinematics", true),
			SkipIntroCinematicsBootRealtimeCapSec = ReadInt(json, "skipIntroCinematicsBootRealtimeCapSec", 300),
			RetaliationForecastFix = ReadBool(json, "retaliationForecastFix", false),
			RetaliationForecastDebounceMs = ReadInt(json, "retaliationForecastDebounceMs", 100),
			UiScalePercent = ReadInt(json, "uiScalePercent", 100),
			DamageHistograms = ReadBool(json, "damageHistograms", false),
			DamageHistogramConvolutionMaxUnits = ReadInt(json, "damageHistogramConvolutionMaxUnits", 120),
			DamageHistogramChartWidthPx = ReadInt(json, "damageHistogramChartWidthPx", 275),
			DamageHistogramChartHeightPx = ReadInt(json, "damageHistogramChartHeightPx", 144),
			DamageHistogramGapPx = ReadInt(json, "damageHistogramGapPx", 12),
			DamageHistogramUseNativeFrameSprite = ReadBool(
				json,
				"damageHistogramUseNativeFrameSprite",
				false
			),
			DamageHistogramPanelUgui = ReadBool(
				json,
				"damageHistogramPanelUgui",
				false
			),
			DamageHistogramPanelUguiLayoutPercent = ReadInt(
				json,
				"damageHistogramPanelUguiLayoutPercent",
				120
			),
			DamageHistogramPanelUguiEdgeFeatherPx = ReadInt(
				json,
				"damageHistogramPanelUguiEdgeFeatherPx",
				20
			),
			DamageHistogramFontScalePercent = ReadInt(json, "damageHistogramFontScalePercent", 100),
			DamageHistogramMinBars = ReadInt(json, "damageHistogramMinBars", 0),
			SuppressBhAppStartTypeInitLoop = ReadBool(
				json,
				"suppressBhAppStartTypeInitLoop",
				true
			),
			SuppressBhHudSessionIraNre = ReadBool(
				json,
				"suppressBhHudSessionIraNre",
				true
			),
			ModBugReporting = ReadBool(json, "modBugReporting", true),
			ModBugReportingEndpoint = ReadString(json, "modBugReportingEndpoint", ""),
			ModBugReportingIncludeScreenshot = ReadBool(json, "modBugReportingIncludeScreenshot", false),
			BlockNativeTelemetry = ReadBool(json, "blockNativeTelemetry", true),
			EsquirePikemanVisuals = ReadBool(json, "esquirePikemanVisuals", false),
			EsquirePikemanApplyHarmony = ReadBool(json, "esquirePikemanApplyHarmony", false),
			EsquirePikemanPrewarmBundle = ReadBool(json, "esquirePikemanPrewarmBundle", false),
			EsquirePikemanDiagnostics = ReadBool(json, "esquirePikemanDiagnostics", false),
			EsquirePikemanDeferPatch = ReadBool(json, "esquirePikemanDeferPatch", true),
			EsquirePikemanDeferBySceneLoad = ReadBool(json, "esquirePikemanDeferBySceneLoad", true),
			EsquirePikemanDeferSceneLoadSkips = ReadInt(json, "esquirePikemanDeferSceneLoadSkips", 0),
			EsquirePikemanDeferPatchFrames = ReadInt(json, "esquirePikemanDeferPatchFrames", 30),
			EsquirePikemanSpawnerReflectionProbe = ReadBool(json, "esquirePikemanSpawnerReflectionProbe", false),
			EsquirePikemanDeferResManagerOffsetFrames = ReadInt(json, "esquirePikemanDeferResManagerOffsetFrames", 2),
			EsquirePikemanSwapAdventureMap = ReadBool(json, "esquirePikemanSwapAdventureMap", true),
			EsquirePikemanMapBillboardMaterialMode = ReadString(json, "esquirePikemanMapBillboardMaterialMode", "hexLitVanilla"),
			EsquirePikemanBattleSyncVanillaPresentation = ReadBool(json, "esquirePikemanBattleSyncVanillaPresentation", true),
			EsquirePikemanBattleBeiSecondArgTrue = ReadBool(json, "esquirePikemanBattleBeiSecondArgTrue", false),
			EsquirePikemanBattleAlignFeetToVanilla = ReadBool(json, "esquirePikemanBattleAlignFeetToVanilla", true),
			EsquirePikemanBattleBillboardExtraY = ReadDouble(json, "esquirePikemanBattleBillboardExtraY", 0),
			EsquireBattleSfxVolume = ReadDouble(json, "esquireBattleSfxVolume", 0.45),
			Homm3StrongholdTownMusicVolume = ReadDouble(json, "homm3StrongholdTownMusicVolume", 0.25),
			Homm3StrongholdTownBackdropScale = ReadDouble(json, "homm3StrongholdTownBackdropScale", 1.18),
			EsquirePikemanResManagerPostfix = ReadBool(json, "esquirePikemanResManagerPostfix", false),
			EsquirePikemanUnityErrorCorrelator = ReadBool(json, "esquirePikemanUnityErrorCorrelator", false),
			EsquirePikemanNarrowUiSpawnerHook = ReadBool(json, "esquirePikemanNarrowUiSpawnerHook", false),
			EsquirePikemanVerbose = ReadBool(json, "esquirePikemanVerbose", false),
			Homm3ImportEnabled = ReadBool(json, "homm3ImportEnabled", false),
			Homm3ImportApplyHarmony = ReadBool(json, "homm3ImportApplyHarmony", false),
			Homm3ReleaseCustomGameUi = ReadBool(json, "homm3ReleaseCustomGameUi", true),
			Homm3ReleaseSafeUiMapTown = ReadBool(json, "homm3ReleaseSafeUiMapTown", true),
			Homm3ReleaseSafeHeroPortrait = ReadBool(json, "homm3ReleaseSafeHeroPortrait", true),
			Homm3ReleaseSafeHeroPortraitCityView = ReadBool(json, "homm3ReleaseSafeHeroPortraitCityView", false),
			Homm3UseUpscaledHeroPortraits = ReadBool(json, "homm3UseUpscaledHeroPortraits", false),
			Homm3UseUiPortraitBundles = ReadBool(json, "homm3UseUiPortraitBundles", false),
			Homm3UseBillboardBundles = ReadBool(json, "homm3UseBillboardBundles", false),
			Homm3TowerCityMapMesh = ReadBool(json, "homm3TowerCityMapMesh", false),
			Homm3TowerCityMapMeshScale = ReadDouble(json, "homm3TowerCityMapMeshScale", 1),
			Homm3MapBuildingMeshes = ReadBool(json, "homm3MapBuildingMeshes", false),
			Homm3MapBuildingMeshesScale = ReadDouble(json, "homm3MapBuildingMeshesScale", 1),
			Homm3ArtifactMeshes = ReadBool(json, "homm3ArtifactMeshes", false),
			Homm3ArtifactMeshesScale = ReadDouble(json, "homm3ArtifactMeshesScale", 1),
			Homm3TownSceneMeshes = ReadBool(json, "homm3TownSceneMeshes", false),
			Homm3TownSceneMeshesScale = ReadDouble(json, "homm3TownSceneMeshesScale", 1),
			Homm3TownScene3d = ReadBool(json, "homm3TownScene3d", false),
			Homm3ReleaseSafeHeroClassProfile = ReadBool(json, "homm3ReleaseSafeHeroClassProfile", true),
			Homm3ReleaseSafeArmyStrip = ReadBool(json, "homm3ReleaseSafeArmyStrip", true),
			Homm3ReleaseSafeCustomUiIcon = ReadBool(json, "homm3ReleaseSafeCustomUiIcon", true),
			Homm3ReleaseSafeHeroMapSprite = ReadBool(json, "homm3ReleaseSafeHeroMapSprite", true),
			Homm3ReleaseSafeLawIcon = ReadBool(json, "homm3ReleaseSafeLawIcon", true),
			Homm3ReleaseSafeWarcryIcon = ReadBool(json, "homm3ReleaseSafeWarcryIcon", true),
			Homm3ReleaseSafeMapBillboards = ReadBool(json, "homm3ReleaseSafeMapBillboards", true),
			Homm3ReleaseSafeCityTownUi = ReadBool(json, "homm3ReleaseSafeCityTownUi", true),
			Homm3FactoryCitySceneReplace = ReadBool(json, "homm3FactoryCitySceneReplace", false),
			Homm3FastCityOpening = ReadBool(json, "homm3FastCityOpening", true),
			Homm3FastCityOpeningMaxFrames = ReadInt(json, "homm3FastCityOpeningMaxFrames", 12),
			Homm3TownPrefabs = ReadBool(json, "homm3TownPrefabs", true),
			Homm3ReleaseSelectedHud = ReadBool(json, "homm3ReleaseSelectedHud", true),
			Homm3ReleaseResManager = ReadBool(json, "homm3ReleaseResManager", true),
			Homm3ReleaseBattlePool = ReadBool(json, "homm3ReleaseBattlePool", true),
			Homm3ReleaseUnitView = ReadBool(json, "homm3ReleaseUnitView", true),
			Homm3ReleaseBattleUi = ReadBool(json, "homm3ReleaseBattleUi", true),
			Homm3ReleaseBattleUiSelectedHud = ReadBool(json, "homm3ReleaseBattleUiSelectedHud", false),
			Homm3ReleaseBattleUiSelectedUnitView = ReadBool(json, "homm3ReleaseBattleUiSelectedUnitView", false),
			Homm3ReleaseBattleUiTurnQueue = ReadBool(json, "homm3ReleaseBattleUiTurnQueue", false),
			Homm3ReleaseBattleUiHeroViews = ReadBool(json, "homm3ReleaseBattleUiHeroViews", false),
			Homm3ReleaseBattleUiDiagnostics = ReadBool(json, "homm3ReleaseBattleUiDiagnostics", false),
			Homm3ReleaseProjectile = ReadBool(json, "homm3ReleaseProjectile", false),
			Homm3ReleaseNarrowSpawner = ReadBool(json, "homm3ReleaseNarrowSpawner", true),
			Homm3ReleaseMapObjectUnitVisual = ReadBool(json, "homm3ReleaseMapObjectUnitVisual", true),
			Homm3ReleaseMapSquadVisualController = ReadBool(json, "homm3ReleaseMapSquadVisualController", true),
			Homm3ReleaseTooltipPortrait = ReadBool(json, "homm3ReleaseTooltipPortrait", true),
			Homm3ReleaseDetailPreview = ReadBool(json, "homm3ReleaseDetailPreview", true),
			Homm3ReleaseDeathFade = ReadBool(json, "homm3ReleaseDeathFade", false),
			Homm3ReleaseCityMusic = ReadBool(json, "homm3ReleaseCityMusic", true),
			Homm3ReleaseCombatMusic = ReadBool(json, "homm3ReleaseCombatMusic", true),
			Homm3PreviewUseStaticPortraits = ReadBool(json, "homm3PreviewUseStaticPortraits", true),
			Homm3DetailPreviewUseStaticPortraits = ReadBool(json, "homm3DetailPreviewUseStaticPortraits", false),
			Homm3CustomBiomeRegistration = ReadBool(json, "homm3CustomBiomeRegistration", true),
			Homm3SwampAutumnTintProof = ReadBool(json, "homm3SwampAutumnTintProof", false),
			Homm3SkeletalNecromancyPostBattle = ReadBool(json, "homm3SkeletalNecromancyPostBattle", true),
			Homm3SkeletalNecromancyProbe = ReadBool(json, "homm3SkeletalNecromancyProbe", false),
			Homm3SwashbucklerGoldProduction = ReadBool(json, "homm3SwashbucklerGoldProduction", true),
			Homm3TowerBottomlessKnowledgeManaWellAegis = ReadBool(json, "homm3TowerBottomlessKnowledgeManaWellAegis", true),
			Homm3CovePlunder = ReadBool(json, "homm3CovePlunder", true),
			Homm3FortressHuntingGrounds = ReadBool(json, "homm3FortressHuntingGrounds", true),
			Homm3CoveAfterShotDisruptingRay = ReadBool(json, "homm3CoveAfterShotDisruptingRay", true),
			Homm3DungeonDraconicDominion = ReadBool(json, "homm3DungeonDraconicDominion", true),
			Homm3ImportPreviewHooks = ReadBool(json, "homm3ImportPreviewHooks", false),
			Homm3NativePreviewStartupDeferral = ReadBool(json, NativePreviewStartupDeferralSettingName, false),
			StrongholdAbilityPanelProbes = ReadBool(json, "strongholdAbilityPanelProbes", false),
			ReleaseCustomGameUiProbes = ReadBool(json, "releaseCustomGameUiProbes", false),
			Homm3UiInspector = ReadBool(json, "homm3UiInspector", false),
#if !RELEASE_CANDIDATE_BUILD
			Homm3LiveProbeWorkbench = ReadBool(json, "homm3LiveProbeWorkbench", false),
			Homm3AiDriverBridge = ReadBool(json, "homm3AiDriverBridge", false),
#endif
			PortSmokeProfile = ReadBool(json, "portSmokeProfile", false),
			Homm3TooltipPortraitVanillaDungeonFallback = ReadBool(json, "homm3TooltipPortraitVanillaDungeonFallback", false)
		};

		if (c.RetaliationForecastDebounceMs is < 0 or > 1000)
		{
			c.RetaliationForecastDebounceMs = Math.Clamp(c.RetaliationForecastDebounceMs, 0, 1000);
		}

		if (c.UiScalePercent is < 80 or > 200)
		{
			c.UiScalePercent = Math.Clamp(c.UiScalePercent, 80, 200);
		}

		if (c.DamageHistogramConvolutionMaxUnits < 8)
		{
			c.DamageHistogramConvolutionMaxUnits = 8;
		}

		if (c.DamageHistogramChartWidthPx < 80)
		{
			c.DamageHistogramChartWidthPx = 80;
		}

		if (c.DamageHistogramChartHeightPx < 32)
		{
			c.DamageHistogramChartHeightPx = 32;
		}

		if (c.DamageHistogramGapPx < 0)
		{
			c.DamageHistogramGapPx = 0;
		}

		if (c.DamageHistogramPanelUguiLayoutPercent is < 80 or > 200)
		{
			c.DamageHistogramPanelUguiLayoutPercent = Math.Clamp(
				c.DamageHistogramPanelUguiLayoutPercent,
				80,
				200
			);
		}

		if (c.DamageHistogramPanelUguiEdgeFeatherPx is < 8 or > 120)
		{
			c.DamageHistogramPanelUguiEdgeFeatherPx = Math.Clamp(
				c.DamageHistogramPanelUguiEdgeFeatherPx,
				8,
				120
			);
		}

		if (c.DamageHistogramFontScalePercent is < 50 or > 300)
			c.DamageHistogramFontScalePercent = Math.Clamp(c.DamageHistogramFontScalePercent, 50, 300);
		if (c.DamageHistogramMinBars is < 0 or > 30)
			c.DamageHistogramMinBars = Math.Clamp(c.DamageHistogramMinBars, 0, 30);
		if (c.EsquirePikemanDeferPatchFrames is < 0 or > 600)
			c.EsquirePikemanDeferPatchFrames = Math.Clamp(c.EsquirePikemanDeferPatchFrames, 0, 600);
		if (c.EsquirePikemanDeferSceneLoadSkips is < 0 or > 20)
			c.EsquirePikemanDeferSceneLoadSkips = Math.Clamp(c.EsquirePikemanDeferSceneLoadSkips, 0, 20);
		if (c.EsquirePikemanDeferResManagerOffsetFrames is < 0 or > 30)
			c.EsquirePikemanDeferResManagerOffsetFrames = Math.Clamp(c.EsquirePikemanDeferResManagerOffsetFrames, 0, 30);
		c.EsquirePikemanMapBillboardMaterialMode = NormalizeEsquireMapBillboardMaterialMode(c.EsquirePikemanMapBillboardMaterialMode);
		if (double.IsNaN(c.EsquireBattleSfxVolume) || double.IsInfinity(c.EsquireBattleSfxVolume))
			c.EsquireBattleSfxVolume = 0.45;
		if (c.EsquireBattleSfxVolume < 0.0 || c.EsquireBattleSfxVolume > 1.0)
			c.EsquireBattleSfxVolume = Math.Clamp(c.EsquireBattleSfxVolume, 0.0, 1.0);
		if (double.IsNaN(c.Homm3StrongholdTownMusicVolume) || double.IsInfinity(c.Homm3StrongholdTownMusicVolume))
			c.Homm3StrongholdTownMusicVolume = 0.25;
		if (c.Homm3StrongholdTownMusicVolume < 0.0 || c.Homm3StrongholdTownMusicVolume > 1.0)
			c.Homm3StrongholdTownMusicVolume = Math.Clamp(c.Homm3StrongholdTownMusicVolume, 0.0, 1.0);
		if (double.IsNaN(c.Homm3StrongholdTownBackdropScale) || double.IsInfinity(c.Homm3StrongholdTownBackdropScale))
			c.Homm3StrongholdTownBackdropScale = 1.18;
		if (c.Homm3StrongholdTownBackdropScale < 1.0 || c.Homm3StrongholdTownBackdropScale > 1.6)
			c.Homm3StrongholdTownBackdropScale = Math.Clamp(c.Homm3StrongholdTownBackdropScale, 1.0, 1.6);
		if (c.AutoLaunchDelayMs < 0 || c.AutoLaunchDelayMs > 120000)
			c.AutoLaunchDelayMs = Math.Clamp(c.AutoLaunchDelayMs, 0, 120000);
		if (c.SkipIntroCinematicsBootRealtimeCapSec < 30 || c.SkipIntroCinematicsBootRealtimeCapSec > 3600)
			c.SkipIntroCinematicsBootRealtimeCapSec = Math.Clamp(c.SkipIntroCinematicsBootRealtimeCapSec, 30, 3600);

		return c;
	}

	private static LauncherConfig MergeLauncherConfig(LauncherConfig a, string jsonB)
	{
		if (string.IsNullOrWhiteSpace(jsonB))
		{
			return a;
		}

		var b = ParseLauncherConfig(jsonB);

		// mod layer overrides: only keys present in the second file
		if (KeyPresent(jsonB, "matchMode"))
		{
			a.MatchMode = b.MatchMode;
		}

		if (KeyPresent(jsonB, "mapTemplate"))
		{
			a.MapTemplate = b.MapTemplate;
		}

		if (KeyPresent(jsonB, "difficultyIndex"))
		{
			a.DifficultyIndex = b.DifficultyIndex;
		}

		if (KeyPresent(jsonB, "playerOneFaction"))
		{
			a.PlayerOneFaction = b.PlayerOneFaction;
		}

		if (KeyPresent(jsonB, "playerOneHero"))
		{
			a.PlayerOneHero = b.PlayerOneHero;
		}

		if (KeyPresent(jsonB, "playerTwoFaction"))
		{
			a.PlayerTwoFaction = b.PlayerTwoFaction;
		}

		if (KeyPresent(jsonB, "playerTwoHero"))
		{
			a.PlayerTwoHero = b.PlayerTwoHero;
		}

		if (KeyPresent(jsonB, "autoLaunchOnMenu"))
		{
			a.AutoLaunchOnMenu = b.AutoLaunchOnMenu;
		}

		if (KeyPresent(jsonB, "releaseSafeAutoLaunchOnMenu"))
		{
			a.ReleaseSafeAutoLaunchOnMenu = b.ReleaseSafeAutoLaunchOnMenu;
		}

		if (KeyPresent(jsonB, "releaseSafeProfile"))
		{
			a.ReleaseSafeProfile = b.ReleaseSafeProfile;
		}

		if (KeyPresent(jsonB, "legacyOfflineUnlockPatches"))
		{
			a.LegacyOfflineUnlockPatches = b.LegacyOfflineUnlockPatches;
		}

		if (KeyPresent(jsonB, "uiScalePatches"))
		{
			a.UiScalePatches = b.UiScalePatches;
		}

		if (KeyPresent(jsonB, "autoLaunchDelayMs"))
		{
			a.AutoLaunchDelayMs = b.AutoLaunchDelayMs;
		}

		if (KeyPresent(jsonB, "skipIntroCinematics"))
		{
			a.SkipIntroCinematics = b.SkipIntroCinematics;
		}

		if (KeyPresent(jsonB, "skipIntroCinematicsBootRealtimeCapSec"))
		{
			a.SkipIntroCinematicsBootRealtimeCapSec = b.SkipIntroCinematicsBootRealtimeCapSec;
		}

		if (KeyPresent(jsonB, "retaliationForecastFix"))
		{
			a.RetaliationForecastFix = b.RetaliationForecastFix;
		}

		if (KeyPresent(jsonB, "retaliationForecastDebounceMs"))
		{
			a.RetaliationForecastDebounceMs = b.RetaliationForecastDebounceMs;
		}

		if (KeyPresent(jsonB, "uiScalePercent"))
		{
			a.UiScalePercent = b.UiScalePercent;
		}

		if (KeyPresent(jsonB, "damageHistograms"))
		{
			a.DamageHistograms = b.DamageHistograms;
		}

		if (KeyPresent(jsonB, "damageHistogramConvolutionMaxUnits"))
		{
			a.DamageHistogramConvolutionMaxUnits = b.DamageHistogramConvolutionMaxUnits;
		}

		if (KeyPresent(jsonB, "damageHistogramChartWidthPx"))
		{
			a.DamageHistogramChartWidthPx = b.DamageHistogramChartWidthPx;
		}

		if (KeyPresent(jsonB, "damageHistogramChartHeightPx"))
		{
			a.DamageHistogramChartHeightPx = b.DamageHistogramChartHeightPx;
		}

		if (KeyPresent(jsonB, "damageHistogramGapPx"))
		{
			a.DamageHistogramGapPx = b.DamageHistogramGapPx;
		}

		if (KeyPresent(jsonB, "damageHistogramUseNativeFrameSprite"))
		{
			a.DamageHistogramUseNativeFrameSprite = b.DamageHistogramUseNativeFrameSprite;
		}

		if (KeyPresent(jsonB, "damageHistogramPanelUgui"))
		{
			a.DamageHistogramPanelUgui = b.DamageHistogramPanelUgui;
		}

		if (KeyPresent(jsonB, "damageHistogramPanelUguiLayoutPercent"))
		{
			a.DamageHistogramPanelUguiLayoutPercent = b.DamageHistogramPanelUguiLayoutPercent;
		}

		if (KeyPresent(jsonB, "damageHistogramPanelUguiEdgeFeatherPx"))
		{
			a.DamageHistogramPanelUguiEdgeFeatherPx = b.DamageHistogramPanelUguiEdgeFeatherPx;
		}

		if (KeyPresent(jsonB, "damageHistogramFontScalePercent"))
			a.DamageHistogramFontScalePercent = b.DamageHistogramFontScalePercent;
		if (KeyPresent(jsonB, "damageHistogramMinBars"))
			a.DamageHistogramMinBars = b.DamageHistogramMinBars;
		if (KeyPresent(jsonB, "suppressBhAppStartTypeInitLoop"))
			a.SuppressBhAppStartTypeInitLoop = b.SuppressBhAppStartTypeInitLoop;
		if (KeyPresent(jsonB, "suppressBhHudSessionIraNre"))
			a.SuppressBhHudSessionIraNre = b.SuppressBhHudSessionIraNre;
		if (KeyPresent(jsonB, "modBugReporting"))
			a.ModBugReporting = b.ModBugReporting;
		if (KeyPresent(jsonB, "modBugReportingEndpoint"))
			a.ModBugReportingEndpoint = b.ModBugReportingEndpoint;
		if (KeyPresent(jsonB, "modBugReportingIncludeScreenshot"))
			a.ModBugReportingIncludeScreenshot = b.ModBugReportingIncludeScreenshot;
		if (KeyPresent(jsonB, "blockNativeTelemetry"))
			a.BlockNativeTelemetry = b.BlockNativeTelemetry;
		if (KeyPresent(jsonB, "esquirePikemanVisuals"))
			a.EsquirePikemanVisuals = b.EsquirePikemanVisuals;
		if (KeyPresent(jsonB, "esquirePikemanApplyHarmony"))
			a.EsquirePikemanApplyHarmony = b.EsquirePikemanApplyHarmony;
		if (KeyPresent(jsonB, "esquirePikemanPrewarmBundle"))
			a.EsquirePikemanPrewarmBundle = b.EsquirePikemanPrewarmBundle;
		if (KeyPresent(jsonB, "esquirePikemanDiagnostics"))
			a.EsquirePikemanDiagnostics = b.EsquirePikemanDiagnostics;
		if (KeyPresent(jsonB, "esquirePikemanDeferPatch"))
			a.EsquirePikemanDeferPatch = b.EsquirePikemanDeferPatch;
		if (KeyPresent(jsonB, "esquirePikemanDeferBySceneLoad"))
			a.EsquirePikemanDeferBySceneLoad = b.EsquirePikemanDeferBySceneLoad;
		if (KeyPresent(jsonB, "esquirePikemanDeferSceneLoadSkips"))
			a.EsquirePikemanDeferSceneLoadSkips = b.EsquirePikemanDeferSceneLoadSkips;
		if (KeyPresent(jsonB, "esquirePikemanDeferPatchFrames"))
			a.EsquirePikemanDeferPatchFrames = b.EsquirePikemanDeferPatchFrames;
		if (KeyPresent(jsonB, "esquirePikemanDeferResManagerOffsetFrames"))
			a.EsquirePikemanDeferResManagerOffsetFrames = b.EsquirePikemanDeferResManagerOffsetFrames;
		if (KeyPresent(jsonB, "esquirePikemanSwapAdventureMap"))
			a.EsquirePikemanSwapAdventureMap = b.EsquirePikemanSwapAdventureMap;
		if (KeyPresent(jsonB, "esquirePikemanMapBillboardMaterialMode"))
			a.EsquirePikemanMapBillboardMaterialMode = NormalizeEsquireMapBillboardMaterialMode(b.EsquirePikemanMapBillboardMaterialMode);
		if (KeyPresent(jsonB, "esquirePikemanBattleSyncVanillaPresentation"))
			a.EsquirePikemanBattleSyncVanillaPresentation = b.EsquirePikemanBattleSyncVanillaPresentation;
		if (KeyPresent(jsonB, "esquirePikemanBattleBeiSecondArgTrue"))
			a.EsquirePikemanBattleBeiSecondArgTrue = b.EsquirePikemanBattleBeiSecondArgTrue;
		if (KeyPresent(jsonB, "esquirePikemanBattleAlignFeetToVanilla"))
			a.EsquirePikemanBattleAlignFeetToVanilla = b.EsquirePikemanBattleAlignFeetToVanilla;
		if (KeyPresent(jsonB, "esquirePikemanBattleBillboardExtraY"))
			a.EsquirePikemanBattleBillboardExtraY = b.EsquirePikemanBattleBillboardExtraY;
		if (KeyPresent(jsonB, "esquireBattleSfxVolume"))
			a.EsquireBattleSfxVolume = b.EsquireBattleSfxVolume;
		if (KeyPresent(jsonB, "homm3StrongholdTownMusicVolume"))
			a.Homm3StrongholdTownMusicVolume = b.Homm3StrongholdTownMusicVolume;
		if (KeyPresent(jsonB, "homm3StrongholdTownBackdropScale"))
			a.Homm3StrongholdTownBackdropScale = b.Homm3StrongholdTownBackdropScale;
		if (KeyPresent(jsonB, "esquirePikemanResManagerPostfix"))
			a.EsquirePikemanResManagerPostfix = b.EsquirePikemanResManagerPostfix;
		if (KeyPresent(jsonB, "esquirePikemanUnityErrorCorrelator"))
			a.EsquirePikemanUnityErrorCorrelator = b.EsquirePikemanUnityErrorCorrelator;
		if (KeyPresent(jsonB, "esquirePikemanSpawnerReflectionProbe"))
			a.EsquirePikemanSpawnerReflectionProbe = b.EsquirePikemanSpawnerReflectionProbe;
		if (KeyPresent(jsonB, "esquirePikemanNarrowUiSpawnerHook"))
			a.EsquirePikemanNarrowUiSpawnerHook = b.EsquirePikemanNarrowUiSpawnerHook;
		if (KeyPresent(jsonB, "esquirePikemanVerbose"))
			a.EsquirePikemanVerbose = b.EsquirePikemanVerbose;
		if (KeyPresent(jsonB, "homm3ImportEnabled"))
			a.Homm3ImportEnabled = b.Homm3ImportEnabled;
		if (KeyPresent(jsonB, "homm3ImportApplyHarmony"))
			a.Homm3ImportApplyHarmony = b.Homm3ImportApplyHarmony;
		if (KeyPresent(jsonB, "homm3ReleaseCustomGameUi"))
			a.Homm3ReleaseCustomGameUi = b.Homm3ReleaseCustomGameUi;
		if (KeyPresent(jsonB, "homm3ReleaseSafeUiMapTown"))
			a.Homm3ReleaseSafeUiMapTown = b.Homm3ReleaseSafeUiMapTown;
		if (KeyPresent(jsonB, "homm3ReleaseSafeHeroPortrait"))
			a.Homm3ReleaseSafeHeroPortrait = b.Homm3ReleaseSafeHeroPortrait;
		if (KeyPresent(jsonB, "homm3ReleaseSafeHeroPortraitCityView"))
			a.Homm3ReleaseSafeHeroPortraitCityView = b.Homm3ReleaseSafeHeroPortraitCityView;
		if (KeyPresent(jsonB, "homm3UseUpscaledHeroPortraits"))
			a.Homm3UseUpscaledHeroPortraits = b.Homm3UseUpscaledHeroPortraits;
		if (KeyPresent(jsonB, "homm3UseUiPortraitBundles"))
			a.Homm3UseUiPortraitBundles = b.Homm3UseUiPortraitBundles;
		if (KeyPresent(jsonB, "homm3UseBillboardBundles"))
			a.Homm3UseBillboardBundles = b.Homm3UseBillboardBundles;
		if (KeyPresent(jsonB, "homm3TowerCityMapMesh"))
			a.Homm3TowerCityMapMesh = b.Homm3TowerCityMapMesh;
		if (KeyPresent(jsonB, "homm3TowerCityMapMeshScale"))
			a.Homm3TowerCityMapMeshScale = b.Homm3TowerCityMapMeshScale;
		if (KeyPresent(jsonB, "homm3MapBuildingMeshes"))
			a.Homm3MapBuildingMeshes = b.Homm3MapBuildingMeshes;
		if (KeyPresent(jsonB, "homm3MapBuildingMeshesScale"))
			a.Homm3MapBuildingMeshesScale = b.Homm3MapBuildingMeshesScale;
		if (KeyPresent(jsonB, "homm3ArtifactMeshes"))
			a.Homm3ArtifactMeshes = b.Homm3ArtifactMeshes;
		if (KeyPresent(jsonB, "homm3ArtifactMeshesScale"))
			a.Homm3ArtifactMeshesScale = b.Homm3ArtifactMeshesScale;
		if (KeyPresent(jsonB, "homm3TownSceneMeshes"))
			a.Homm3TownSceneMeshes = b.Homm3TownSceneMeshes;
		if (KeyPresent(jsonB, "homm3TownSceneMeshesScale"))
			a.Homm3TownSceneMeshesScale = b.Homm3TownSceneMeshesScale;
		if (KeyPresent(jsonB, "homm3TownScene3d"))
			a.Homm3TownScene3d = b.Homm3TownScene3d;
		if (KeyPresent(jsonB, "homm3ReleaseSafeHeroClassProfile"))
			a.Homm3ReleaseSafeHeroClassProfile = b.Homm3ReleaseSafeHeroClassProfile;
		if (KeyPresent(jsonB, "homm3ReleaseSafeArmyStrip"))
			a.Homm3ReleaseSafeArmyStrip = b.Homm3ReleaseSafeArmyStrip;
		if (KeyPresent(jsonB, "homm3ReleaseSafeCustomUiIcon"))
			a.Homm3ReleaseSafeCustomUiIcon = b.Homm3ReleaseSafeCustomUiIcon;
		if (KeyPresent(jsonB, "homm3ReleaseSafeHeroMapSprite"))
			a.Homm3ReleaseSafeHeroMapSprite = b.Homm3ReleaseSafeHeroMapSprite;
		if (KeyPresent(jsonB, "homm3ReleaseSafeLawIcon"))
			a.Homm3ReleaseSafeLawIcon = b.Homm3ReleaseSafeLawIcon;
		if (KeyPresent(jsonB, "homm3ReleaseSafeWarcryIcon"))
			a.Homm3ReleaseSafeWarcryIcon = b.Homm3ReleaseSafeWarcryIcon;
		if (KeyPresent(jsonB, "homm3ReleaseSafeMapBillboards"))
			a.Homm3ReleaseSafeMapBillboards = b.Homm3ReleaseSafeMapBillboards;
		if (KeyPresent(jsonB, "homm3ReleaseSafeCityTownUi"))
			a.Homm3ReleaseSafeCityTownUi = b.Homm3ReleaseSafeCityTownUi;
		if (KeyPresent(jsonB, "homm3FactoryCitySceneReplace"))
			a.Homm3FactoryCitySceneReplace = b.Homm3FactoryCitySceneReplace;
		if (KeyPresent(jsonB, "homm3FastCityOpening"))
			a.Homm3FastCityOpening = b.Homm3FastCityOpening;
		if (KeyPresent(jsonB, "homm3FastCityOpeningMaxFrames"))
			a.Homm3FastCityOpeningMaxFrames = b.Homm3FastCityOpeningMaxFrames;
		if (KeyPresent(jsonB, "homm3TownPrefabs"))
			a.Homm3TownPrefabs = b.Homm3TownPrefabs;
		if (KeyPresent(jsonB, "homm3ReleaseSelectedHud"))
			a.Homm3ReleaseSelectedHud = b.Homm3ReleaseSelectedHud;
		if (KeyPresent(jsonB, "homm3ReleaseResManager"))
			a.Homm3ReleaseResManager = b.Homm3ReleaseResManager;
		if (KeyPresent(jsonB, "homm3ReleaseBattlePool"))
			a.Homm3ReleaseBattlePool = b.Homm3ReleaseBattlePool;
		if (KeyPresent(jsonB, "homm3ReleaseUnitView"))
			a.Homm3ReleaseUnitView = b.Homm3ReleaseUnitView;
		if (KeyPresent(jsonB, "homm3ReleaseBattleUi"))
			a.Homm3ReleaseBattleUi = b.Homm3ReleaseBattleUi;
		if (KeyPresent(jsonB, "homm3ReleaseBattleUiSelectedHud"))
			a.Homm3ReleaseBattleUiSelectedHud = b.Homm3ReleaseBattleUiSelectedHud;
		if (KeyPresent(jsonB, "homm3ReleaseBattleUiSelectedUnitView"))
			a.Homm3ReleaseBattleUiSelectedUnitView = b.Homm3ReleaseBattleUiSelectedUnitView;
		if (KeyPresent(jsonB, "homm3ReleaseBattleUiTurnQueue"))
			a.Homm3ReleaseBattleUiTurnQueue = b.Homm3ReleaseBattleUiTurnQueue;
		if (KeyPresent(jsonB, "homm3ReleaseBattleUiHeroViews"))
			a.Homm3ReleaseBattleUiHeroViews = b.Homm3ReleaseBattleUiHeroViews;
		if (KeyPresent(jsonB, "homm3ReleaseBattleUiDiagnostics"))
			a.Homm3ReleaseBattleUiDiagnostics = b.Homm3ReleaseBattleUiDiagnostics;
		if (KeyPresent(jsonB, "homm3ReleaseProjectile"))
			a.Homm3ReleaseProjectile = b.Homm3ReleaseProjectile;
		if (KeyPresent(jsonB, "homm3ReleaseNarrowSpawner"))
			a.Homm3ReleaseNarrowSpawner = b.Homm3ReleaseNarrowSpawner;
		if (KeyPresent(jsonB, "homm3ReleaseMapObjectUnitVisual"))
			a.Homm3ReleaseMapObjectUnitVisual = b.Homm3ReleaseMapObjectUnitVisual;
		if (KeyPresent(jsonB, "homm3ReleaseMapSquadVisualController"))
			a.Homm3ReleaseMapSquadVisualController = b.Homm3ReleaseMapSquadVisualController;
		if (KeyPresent(jsonB, "homm3ReleaseTooltipPortrait"))
			a.Homm3ReleaseTooltipPortrait = b.Homm3ReleaseTooltipPortrait;
		if (KeyPresent(jsonB, "homm3ReleaseDetailPreview"))
			a.Homm3ReleaseDetailPreview = b.Homm3ReleaseDetailPreview;
		if (KeyPresent(jsonB, "homm3ReleaseDeathFade"))
			a.Homm3ReleaseDeathFade = b.Homm3ReleaseDeathFade;
		if (KeyPresent(jsonB, "homm3ReleaseCityMusic"))
			a.Homm3ReleaseCityMusic = b.Homm3ReleaseCityMusic;
		if (KeyPresent(jsonB, "homm3ReleaseCombatMusic"))
			a.Homm3ReleaseCombatMusic = b.Homm3ReleaseCombatMusic;
		if (KeyPresent(jsonB, "homm3PreviewUseStaticPortraits"))
			a.Homm3PreviewUseStaticPortraits = b.Homm3PreviewUseStaticPortraits;
		if (KeyPresent(jsonB, "homm3DetailPreviewUseStaticPortraits"))
			a.Homm3DetailPreviewUseStaticPortraits = b.Homm3DetailPreviewUseStaticPortraits;
		if (KeyPresent(jsonB, "homm3CustomBiomeRegistration"))
			a.Homm3CustomBiomeRegistration = b.Homm3CustomBiomeRegistration;
		if (KeyPresent(jsonB, "homm3SwampAutumnTintProof"))
			a.Homm3SwampAutumnTintProof = b.Homm3SwampAutumnTintProof;
		if (KeyPresent(jsonB, "homm3SkeletalNecromancyPostBattle"))
			a.Homm3SkeletalNecromancyPostBattle = b.Homm3SkeletalNecromancyPostBattle;
		if (KeyPresent(jsonB, "homm3SkeletalNecromancyProbe"))
			a.Homm3SkeletalNecromancyProbe = b.Homm3SkeletalNecromancyProbe;
		if (KeyPresent(jsonB, "homm3SwashbucklerGoldProduction"))
			a.Homm3SwashbucklerGoldProduction = b.Homm3SwashbucklerGoldProduction;
		if (KeyPresent(jsonB, "homm3TowerBottomlessKnowledgeManaWellAegis"))
			a.Homm3TowerBottomlessKnowledgeManaWellAegis = b.Homm3TowerBottomlessKnowledgeManaWellAegis;
		if (KeyPresent(jsonB, "homm3CovePlunder"))
			a.Homm3CovePlunder = b.Homm3CovePlunder;
		if (KeyPresent(jsonB, "homm3FortressHuntingGrounds"))
			a.Homm3FortressHuntingGrounds = b.Homm3FortressHuntingGrounds;
		if (KeyPresent(jsonB, "homm3CoveAfterShotDisruptingRay"))
			a.Homm3CoveAfterShotDisruptingRay = b.Homm3CoveAfterShotDisruptingRay;
		if (KeyPresent(jsonB, "homm3DungeonDraconicDominion"))
			a.Homm3DungeonDraconicDominion = b.Homm3DungeonDraconicDominion;
		if (KeyPresent(jsonB, "homm3ImportPreviewHooks"))
			a.Homm3ImportPreviewHooks = b.Homm3ImportPreviewHooks;
		if (KeyPresent(jsonB, NativePreviewStartupDeferralSettingName))
			a.Homm3NativePreviewStartupDeferral = b.Homm3NativePreviewStartupDeferral;
		if (KeyPresent(jsonB, "strongholdAbilityPanelProbes"))
			a.StrongholdAbilityPanelProbes = b.StrongholdAbilityPanelProbes;
		if (KeyPresent(jsonB, "releaseCustomGameUiProbes"))
			a.ReleaseCustomGameUiProbes = b.ReleaseCustomGameUiProbes;
		if (KeyPresent(jsonB, "homm3UiInspector"))
			a.Homm3UiInspector = b.Homm3UiInspector;
#if !RELEASE_CANDIDATE_BUILD
		if (KeyPresent(jsonB, "homm3LiveProbeWorkbench"))
			a.Homm3LiveProbeWorkbench = b.Homm3LiveProbeWorkbench;
		if (KeyPresent(jsonB, "homm3AiDriverBridge"))
			a.Homm3AiDriverBridge = b.Homm3AiDriverBridge;
#endif
		if (KeyPresent(jsonB, "portSmokeProfile"))
			a.PortSmokeProfile = b.PortSmokeProfile;
		if (KeyPresent(jsonB, "homm3TooltipPortraitVanillaDungeonFallback"))
			a.Homm3TooltipPortraitVanillaDungeonFallback = b.Homm3TooltipPortraitVanillaDungeonFallback;

		return a;
	}

	private static void ApplyReleaseSafeProfile(LauncherConfig c)
	{
		if (c == null || !c.ReleaseSafeProfile)
		{
			return;
		}

		var autoLaunchRequested = c.AutoLaunchOnMenu;
		var allowReleaseSafeAutoLaunch = c.ReleaseSafeAutoLaunchOnMenu;

		c.AutoLaunchOnMenu = false;
		c.LegacyOfflineUnlockPatches = false;
		c.UiScalePatches = false;
		c.RetaliationForecastFix = false;
		c.EsquirePikemanVisuals = false;
		c.EsquirePikemanApplyHarmony = false;
		c.EsquirePikemanPrewarmBundle = false;
		c.EsquirePikemanDiagnostics = false;
		c.EsquirePikemanVerbose = false;
		c.EsquirePikemanUnityErrorCorrelator = false;
		c.Homm3ImportPreviewHooks = false;
		c.StrongholdAbilityPanelProbes = false;
		c.ReleaseCustomGameUiProbes = false;

		if (!c.PortSmokeProfile)
		{
			if (autoLaunchRequested && allowReleaseSafeAutoLaunch)
			{
				c.AutoLaunchOnMenu = true;
			}
			return;
		}

		if (Homm3DiagnosticFlags.IsEnabled("homm3_runtime_probes_enabled.flag"))
		{
			c.Homm3ReleaseBattleUiDiagnostics = true;
			c.ReleaseCustomGameUiProbes = true;
		}
		if (autoLaunchRequested)
		{
			c.AutoLaunchOnMenu = true;
		}
	}

	internal static string NormalizeEsquireMapBillboardMaterialMode(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return "hexLitVanilla";
		var s = raw.Trim();
		if (string.Equals(s, "hexLitVanilla", StringComparison.OrdinalIgnoreCase))
			return "hexLitVanilla";
		if (string.Equals(s, "spritesDefault", StringComparison.OrdinalIgnoreCase))
			return "spritesDefault";
		return "hexLitVanilla";
	}

	private static bool KeyPresent(string json, string key)
	{
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
		{
			return false;
		}

		if (json.IndexOf("\"" + key + "\"", StringComparison.OrdinalIgnoreCase) < 0)
		{
			return false;
		}

		return true;
	}

	private static string ReadString(string json, string key, string fallback)
	{
		var match = Regex.Match(
			json,
			$"\"{Regex.Escape(key)}\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"",
			RegexOptions.IgnoreCase);
		if (!match.Success)
		{
			return fallback;
		}

		return Regex.Unescape(match.Groups[1].Value);
	}

	private static int ReadInt(string json, string key, int fallback)
	{
		var match = Regex.Match(
			json,
			$"\"{Regex.Escape(key)}\"\\s*:\\s*(-?\\d+)",
			RegexOptions.IgnoreCase);
		if (!match.Success || !int.TryParse(match.Groups[1].Value, out var v))
		{
			return fallback;
		}

		return v;
	}

	private static bool ReadBool(string json, string key, bool fallback)
	{
		var match = Regex.Match(
			json,
			$"\"{Regex.Escape(key)}\"\\s*:\\s*(true|false)",
			RegexOptions.IgnoreCase);
		if (!match.Success || !bool.TryParse(match.Groups[1].Value, out var v))
		{
			return fallback;
		}

		return v;
	}

	private static double ReadDouble(string json, string key, double fallback)
	{
		var match = Regex.Match(
			json,
			$"\"{Regex.Escape(key)}\"\\s*:\\s*(-?\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?)",
			RegexOptions.IgnoreCase);
		if (!match.Success
		    || !double.TryParse(
			    match.Groups[1].Value,
			    NumberStyles.Float,
			    CultureInfo.InvariantCulture,
			    out var v))
		{
			return fallback;
		}

		return v;
	}

	private const string NativePreviewStartupDeferralSettingName = "homm3NativePreviewStartupDeferral";

	private static void TryReadHomm3NativePreviewStartupDeferral(
		string json,
		string path,
		out bool present,
		out bool enabled,
		out bool valid,
		out string diagnostic)
	{
		valid = ManagedModSettingsJson.TryReadTopLevelBoolean(
			json,
			NativePreviewStartupDeferralSettingName,
			out present,
			out enabled,
			out var helperDiagnostic);
		diagnostic = valid || helperDiagnostic == null
			? helperDiagnostic
			: "Could not validate " + NativePreviewStartupDeferralSettingName + " in " + path + ": " + helperDiagnostic;
	}
}
